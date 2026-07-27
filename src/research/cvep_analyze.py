"""Analyse hors ligne d'une calibration c-VEP — sans casque, sur `data/cvep_calib_last.npz`.

Quand l'accuracy de calibration est faible, trois causes ont des remèdes OPPOSÉS. Cet outil
les sépare, en rejouant les cycles déjà enregistrés :

  1. DÉCALAGE SYSTÉMATIQUE — la fenêtre EEG n'est pas alignée sur le code comme on le croit
     (latence Bluetooth + électronique + tampon BrainFlow). `--offset` balaie un retard
     constant : si l'accuracy grimpe nettement à un décalage donné, on l'inscrit dans le
     modèle et le problème disparaît définitivement.
  2. SNR INSUFFISANT — un seul cycle ne suffit pas. `--cycles` simule des décisions prises
     sur k cycles consécutifs moyennés : si l'accuracy monte avec k, il « suffit » d'accepter
     une décision plus lente (1 cycle = 1,05 s, 2 cycles = 2,1 s, comparable au SSVEP).
  3. CIBLE PROBLÉMATIQUE — la matrice de confusion dit si une seule cible plombe le score
     (regard qui décroche, lag mal séparé) ou si la dégradation est uniforme.

Enfin, l'outil propose des seuils `CVEP_CORR_MIN` / `CVEP_MARGIN` à partir de la
distribution réelle des corrélations (les valeurs par défaut sont issues du synthétique).

    python src/research/cvep_analyze.py
    python src/research/cvep_analyze.py --file data/cvep_calib_last.npz --max-offset 60
"""

import argparse
import os
import sys
from itertools import combinations

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import CVEP_BAND, DATA_DIR, use_utf8_console  # noqa: E402
from research.cvep_decoder import CVEPModel, bandpass  # noqa: E402
from research.itr import itr as _itr  # noqa: E402

DEFAULT_FILE = os.path.join(DATA_DIR, "cvep_calib_last.npz")


def _groups(lags, k):
    """Indices groupés par blocs de k cycles CONSÉCUTIFS d'une même cible.

    Les cycles ont été enregistrés à la suite pour chaque cible : moyenner k blocs
    consécutifs simule donc fidèlement une décision prise sur k cycles en ligne.
    """
    out = []
    for lag in sorted(set(lags)):
        idx = [i for i, l in enumerate(lags) if l == lag]
        for s in range(0, len(idx) - k + 1, k):
            out.append((lag, idx[s:s + k]))
    return out


def _loo(model, epochs, lags, offset=0, k=1):
    """Accuracy leave-one-group-out. Retourne (accuracy, confusions, marges).

    `offset` > 0 : on considère que l'EEG arrive avec `offset` échantillons de RETARD sur
    le code (on avance donc le signal d'autant avant de l'aligner).
    """
    shifted = [np.roll(e, -offset, axis=0) for e in epochs] if offset else epochs
    uniq = sorted(set(lags))
    groups = _groups(lags, k)
    if len(groups) < 3:
        return None, None, None, None
    ok, conf, margins, raw = 0, {}, [], []
    for true_lag, idx in groups:
        held = set(idx)
        rest = [(shifted[i], lags[i]) for i in range(len(shifted)) if i not in held]
        w, tmpl = model._solve([model._align(e, l) for e, l in rest])
        test = np.mean([shifted[i] for i in idx], axis=0)
        sc = model._scores_filtered(test, 0, uniq, w, tmpl)
        ranked = sorted(sc.items(), key=lambda kv: kv[1], reverse=True)
        pred = ranked[0][0]
        ok += (pred == true_lag)
        conf[(true_lag, pred)] = conf.get((true_lag, pred), 0) + 1
        # idx[0] = position dans l'ENREGISTREMENT : permet de distinguer un effet de cible
        # d'un effet d'apprentissage (les cibles sont enregistrées en blocs successifs).
        margins.append((pred == true_lag, ranked[0][1], ranked[0][1] - ranked[1][1], idx[0]))
        raw.append((true_lag, sc))   # vecteur de scores complet -> permet de rejouer des SOUS-ENSEMBLES
    return ok / len(groups), conf, margins, raw


def _bar(v, width=30):
    return "#" * int(round(v * width))


def _wilson(acc, n, z=1.96):
    """Intervalle de confiance 95% (score de Wilson, correct sur petits effectifs).

    Indispensable ici : une calibration de 30 cycles ne donne que 6 décisions à k=4. Sans
    l'intervalle, on lit « 83% » puis « 33% » d'une séance à l'autre et on croit à une
    régression, alors que les deux mesures sont compatibles avec le même vrai taux.
    """
    if n == 0:
        return 0.0, 1.0
    d = 1 + z * z / n
    c = (acc + z * z / (2 * n)) / d
    h = z * ((acc * (1 - acc) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, c - h), min(1.0, c + h)


def analyze(path=DEFAULT_FILE, max_offset=50, step=5, max_k=4):
    if not os.path.exists(path):
        print(f"[cvep-an] fichier introuvable : {path}\n"
              "           lance d'abord une calibration c-VEP (app.py : c-VEP -> Calibrer).")
        return False
    d = np.load(path)
    epochs_raw, lags = d["epochs"], [int(x) for x in d["lags"]]
    fs, refresh = float(d["fs"]), float(d["refresh"])
    # Les enregistrements récents contiennent les 8 voies ; on restreint à celles sur lesquelles
    # le filtre spatial est ajusté. (Les anciens fichiers n'ont que les 4 voies déjà filtrées.)
    fit_ch = [int(c) for c in d["channels"]] if "channels" in d else None
    if fit_ch and epochs_raw.shape[2] > len(fit_ch):
        epochs_raw = epochs_raw[:, :, fit_ch]
    n_ep, n_cyc, n_ch = epochs_raw.shape
    code_len = int(round(n_cyc * refresh / fs))
    model = CVEPModel(fs=fs, refresh=refresh, code_len=code_len, band=CVEP_BAND)
    epochs = [bandpass(e, fs, CVEP_BAND) for e in epochs_raw]
    per_lag = {l: lags.count(l) for l in sorted(set(lags))}
    uniq = sorted(set(lags))
    # Amplitude APRÈS filtrage = ce que voit réellement le décodeur, et le seul indicateur de
    # qualité comparable d'une séance à l'autre. Une chute d'accuracy à amplitude anormale
    # (contact, batterie) n'a rien à voir avec une chute à amplitude normale (fatigue, regard).
    amp = np.asarray(epochs).std(axis=(0, 1))
    drift = np.asarray(epochs_raw).std(axis=(0, 1))

    print(f"\n== Calibration c-VEP : {os.path.basename(path)}")
    print(f"   {n_ep} cycles de {n_cyc} éch. x {n_ch} voies · fs={fs:.0f}Hz · écran={refresh:.0f}Hz"
          + (f" · rotation={int(d['rotation'])}" if "rotation" in d else ""))
    print(f"   cycles par cible : {per_lag}   (hasard = {100/len(per_lag):.0f}%)")
    print("   amplitude filtrée par voie (σ) : " + "  ".join(f"{v:5.1f}" for v in amp)
          + f"   [dérive brute : {'  '.join(f'{v:.0f}' for v in drift)}]")

    # --- 1. jitter d'alignement ---------------------------------------
    # NB : inutile de balayer un décalage CONSTANT — un roll circulaire appliqué à toutes les
    # époques commute avec l'alignement et la corrélation, donc le template l'absorbe par
    # construction (c'est la propriété qui rend la latence Bluetooth inoffensive). Seul un
    # décalage VARIABLE d'une époque à l'autre dégrade la moyenne : c'est ce qu'on mesure ici.
    best_off = 0
    print(f"\n== 1. Jitter d'alignement (indicatif, ±{max_offset} éch.) ==")
    shifts = []
    for i in range(len(epochs)):
        rest = [(epochs[j], lags[j]) for j in range(len(epochs)) if j != i]
        w, tmpl = model._solve([model._align(e, l) for e, l in rest])
        y = model._align(epochs[i], lags[i]) @ w
        y = y - y.mean()
        best_d, best_c = 0, -2.0
        for d in range(-max_offset, max_offset + 1):
            r = np.roll(tmpl, d)
            c = float(y @ (r - r.mean()) / ((np.linalg.norm(y) * np.linalg.norm(r - r.mean())) or 1))
            if c > best_c:
                best_d, best_c = d, c
        shifts.append(best_d)
    sd = float(np.std(shifts))
    print(f"   décalage optimal par époque : médiane {np.median(shifts):+.0f} éch., "
          f"écart-type {sd:.1f} éch. ({sd/fs*1000:.0f} ms)")
    print("   ⚠️ à bas SNR cette estimation est elle-même bruitée : un écart-type élevé ne")
    print("      prouve pas un jitter matériel, il peut n'être que du bruit. Indicatif.")

    # --- 2. nombre de cycles par décision ------------------------------
    print("\n== 2. Cycles moyennés par décision (compromis latence/fiabilité) ==")
    print("  Moyenner plus de cycles monte l'accuracy MAIS allonge la décision. L'ITR arbitre :")
    accs_k, itrs, confs, raws = {}, {}, {}, {}
    n_tgt = len(per_lag)
    for k in range(1, max_k + 1):
        a, cf, _, rw = _loo(model, epochs, lags, offset=best_off, k=k)
        accs_k[k], confs[k], raws[k] = a, cf, rw
        if a is None:
            print(f"  {k} cycle(s) : pas assez de données")
            continue
        t = k * code_len / refresh
        itrs[k] = _itr(n_tgt, a, t)
        n_g = len(_groups(lags, k))
        lo_ci, hi_ci = _wilson(a, n_g)
        flag = "  ← trop peu de décisions" if n_g < 15 else ""
        print(f"  {k} cycle(s) = {t:4.2f}s | {a*100:5.1f}% [{lo_ci*100:4.0f}-{hi_ci*100:3.0f}%] "
              f"| {itrs[k]:5.1f} bits/min  {_bar(itrs[k]/40)}  ({n_g} déc.){flag}")
    # Un résultat SOUS le hasard n'est pas « une mauvaise performance » : c'est structurellement
    # impossible sur du bruit (qui donne le hasard). Ça signale un jeu de données pathologique —
    # liaison casque mourante, artefact périodique constant que l'alignement recale de travers.
    # Observé le 2026-07-20 : 1,6% pour un hasard à 16,7%, sur la séance où le casque s'est coupé
    # (dérive brute 19 contre 196-716 les séances saines). Ne surtout pas l'interpréter.
    if accs_k.get(1) is not None:
        from scipy.stats import binomtest
        n1 = len(_groups(lags, 1))
        p_low = float(binomtest(int(round(accs_k[1] * n1)), n1, 1 / n_tgt,
                                alternative="less").pvalue)
        if p_low < 0.01:
            print(f"\n  ⛔ ACCURACY SOUS LE HASARD (p={p_low:.1e}) — jeu de données PATHOLOGIQUE.")
            print("     Du bruit donnerait le hasard ; être en dessous trahit un artefact")
            print("     systématique (liaison casque perdue ?). Vérifier la dérive brute plus haut")
            print("     et REJETER cet enregistrement — les chiffres qui suivent n'ont pas de sens.")

    # On retient le k qui maximise l'ITR, PAS celui qui maximise l'accuracy : sur une échelle
    # d'information, gagner 24 points d'accuracy en quadruplant la latence est une perte nette.
    best_k = max(itrs, key=itrs.get) if itrs else 1
    ref = _itr(3, 0.95, 1.5)
    print(f"  -> optimum ITR : {best_k} cycle(s) = {itrs.get(best_k, 0):.1f} bits/min "
          f"(SSVEP de référence : {ref:.1f})")
    # La courbe d'ITR est souvent PLATE : désigner un « optimum » à 5% près sur des effectifs
    # qui fondent avec k (126 décisions à k=1, 30 à k=4) revient à suivre le bruit. D'une séance
    # à l'autre l'optimum a sauté de k=1 à k=2 puis k=4 sans que rien de réel ne change.
    close = [k for k, v in itrs.items() if k != best_k and v >= 0.85 * itrs[best_k]]
    if close:
        print(f"     ⚠️ optimum PLAT : {', '.join(str(k) for k in sorted(close))} cycle(s) "
              f"à moins de 15% — ne pas re-régler config.py sur cet écart, c'est du bruit.")

    # --- 3. confusion + seuils ----------------------------------------
    # --- Effet du NOMBRE DE CIBLES, à séance constante -----------------
    # Comparer 4 et 6 cibles entre DEUX séances est sans valeur : la qualité du signal (q) change
    # d'un jour à l'autre et domine l'effet cherché. Ici on rejoue les mêmes enregistrements en
    # restreignant la décision à un sous-ensemble de lags : le signal, le template et la fatigue
    # sont rigoureusement identiques, seul le nombre de choix varie. On moyenne sur TOUS les
    # sous-ensembles de chaque taille.
    raw_k = raws.get(best_k) or raws.get(1)
    if raw_k and n_tgt >= 3:
        print(f"\n== 2b. Effet du nombre de cibles (mêmes données, {best_k} cycle(s)) ==")
        print(f"   {'cibles':>6} | {'accuracy':>9} | {'bits/min':>8}")
        print("   " + "-" * 32)
        t_dec = best_k * code_len / refresh
        for m in range(2, n_tgt + 1):
            accs_m = []
            for sub in combinations(uniq, m):
                sel = [(t, sc) for t, sc in raw_k if t in sub]
                if not sel:
                    continue
                good_m = sum(1 for t, sc in sel
                             if max(sub, key=lambda l: sc[l]) == t)
                accs_m.append(good_m / len(sel))
            if accs_m:
                am = sum(accs_m) / len(accs_m)
                mark = "  <- config actuelle" if m == n_tgt else ""
                print(f"   {m:>6} | {am*100:8.1f}% | {_itr(m, am, t_dec):8.1f}{mark}")

    acc, conf, margins, _ = _loo(model, epochs, lags, offset=best_off, k=best_k)
    print(f"\n== 3. Confusion au réglage retenu ({best_k} cycle(s), "
          f"{len(margins)} décisions) ==")
    print("   vrai \\ prédit | " + " | ".join(f"lag{l:>3}" for l in uniq))
    for t in uniq:
        row = " | ".join(f"{conf.get((t, p), 0):>6d}" for p in uniq)
        tot = sum(conf.get((t, p), 0) for p in uniq)
        hit = conf.get((t, t), 0)
        print(f"   lag{t:>3}        | {row}   -> {hit}/{tot}")

    # Les cibles diffèrent-elles VRAIMENT ? Test du khi-deux sur la diagonale : sous l'hypothèse
    # « toutes les cibles ont la même accuracy », les succès par cible suivent une binomiale de
    # même paramètre. Un écart visuellement spectaculaire (6/21 contre 14/21) peut être tout à
    # fait banal à cet effectif — c'est ce test qui l'avait manqué et m'a fait poursuivre une
    # anomalie inexistante pendant deux séances.
    from scipy.stats import chi2 as _chi2
    hits = [confs[1].get((t, t), 0) for t in uniq]
    tots = [sum(confs[1].get((t, p), 0) for p in uniq) for t in uniq]
    glob = sum(hits) / max(1, sum(tots))
    if glob > 0 and all(tots):
        stat = sum((h - n * glob) ** 2 / (n * glob) for h, n in zip(hits, tots))
        pval = float(_chi2.sf(stat, len(uniq) - 1))
        print(f"\n   homogénéité des cibles (khi-deux, k=1) : χ²={stat:.2f} "
              f"ddl={len(uniq)-1}  p={pval:.3f}")
        print("   -> " + ("ÉCARTS RÉELS entre cibles (p<0.05) : il y a quelque chose à expliquer."
                          if pval < 0.05 else
                          "écarts COMPATIBLES avec le hasard : ne pas chercher d'explication,\n"
                          "      la variation par cible est du bruit d'échantillonnage."))

    # Par cible, avec intervalle de confiance — au meilleur k il ne reste que quelques décisions
    # par cible, donc on regarde AUSSI k=1, où l'effectif par cible est maximal. Une cible qui
    # décroche aux DEUX est un vrai écart ; une seule, c'est du bruit d'échantillonnage.
    print(f"\n   accuracy par cible (chance {100/n_tgt:.0f}%) :")
    print(f"   {'cible':<8} | {'k=1':^22} | {'k=' + str(best_k):^22}")
    for t in uniq:
        cells = []
        for kk in (1, best_k):
            cf = confs.get(kk) or {}
            tot = sum(cf.get((t, p), 0) for p in uniq)
            hit = cf.get((t, t), 0)
            if tot:
                lo_t, hi_t = _wilson(hit / tot, tot)
                cells.append(f"{hit:>2}/{tot:<2} {hit/tot*100:3.0f}% [{lo_t*100:2.0f}-{hi_t*100:3.0f}]")
            else:
                cells.append(" " * 22)
        chance_hi = _wilson(1.0 / n_tgt, sum(confs[1].get((t, p), 0) for p in uniq))[1]
        k1_acc = confs[1].get((t, t), 0) / max(1, sum(confs[1].get((t, p), 0) for p in uniq))
        # ⚠️ Deux intervalles DIFFÉRENTS cohabitent sur cette ligne : les colonnes affichent
        # l'IC autour de l'accuracy OBSERVÉE, le drapeau compare au plafond de l'IC autour du
        # HASARD. Sans le seuil affiché on lit « [14-50] alors que le hasard est à 12 % » et le
        # drapeau paraît faux — il ne l'est pas, il répond à une autre question.
        flag = (f"  ← dans le bruit du hasard (≤{chance_hi*100:.0f}%)"
                if k1_acc <= chance_hi else "")
        print(f"   lag{t:<5} | {cells[0]} | {cells[1]}{flag}")

    # Les erreurs tombent-elles sur les cibles VOISINES ? C'est le test décisif du choix de N :
    # si oui, c'est l'écart entre lags (175 ms à 6 cibles) qui limite, et il faut moins de
    # cibles ou un code plus long. Si les erreurs sont réparties uniformément, la contrainte
    # est le rapport signal/bruit, et le nombre de cibles n'est PAS le facteur limitant.
    pos = {l: i for i, l in enumerate(uniq)}
    nt = len(uniq)
    by_d, cls_at_d = {}, {}
    for d in range(1, nt // 2 + 1):
        cls_at_d[d] = sum(1 for j in range(1, nt) if min(j, nt - j) == d)
    for (t, p), c in conf.items():
        if t == p:
            continue
        d = min((pos[p] - pos[t]) % nt, (pos[t] - pos[p]) % nt)
        by_d[d] = by_d.get(d, 0) + c
    n_err = sum(by_d.values())
    if n_err:
        print(f"\n== 4. Répartition des {n_err} erreurs selon l'éloignement de la cible ==")
        for d in sorted(cls_at_d):
            obs = by_d.get(d, 0)
            exp = cls_at_d[d] / (nt - 1)
            print(f"   distance {d} ({cls_at_d[d]} cible(s), {d*code_len/nt/refresh*1000:.0f} ms) : "
                  f"{obs:>2}/{n_err} = {obs/n_err*100:4.0f}%   attendu si uniforme {exp*100:4.0f}%")
        near = by_d.get(1, 0) / n_err
        exp_near = cls_at_d[1] / (nt - 1)
        print("   -> " + ("les VOISINES dominent : c'est l'écart entre lags qui limite, "
                          "réduire N ou allonger le code."
                          if near > exp_near * 1.5 else
                          "erreurs RÉPARTIES : l'écart entre lags n'est pas le facteur limitant, "
                          "c'est le SNR.\n      Augmenter N ne coûterait donc pas en confusion "
                          "de voisinage."))

    # Effet du TEMPS : les cibles sont enregistrées en blocs successifs, donc une accuracy qui
    # croît au fil de la séance se lit à tort comme « les dernières cibles sont meilleures ».
    n_tot = len(epochs)
    thirds = [[m for m in margins if lo <= m[3] < hi]
              for lo, hi in ((0, n_tot // 3), (n_tot // 3, 2 * n_tot // 3), (2 * n_tot // 3, n_tot))]
    if all(thirds):
        # Le protocole est-il entrelacé ? On compte les « plages » de lag identique consécutif :
        # une plage par cible = blocs contigus (ordre fixe) ; beaucoup plus = blocs entrelacés.
        runs = 1 + sum(1 for i in range(1, len(lags)) if lags[i] != lags[i - 1])
        interleaved = runs > 1.5 * n_tgt
        print("\n== 6. Accuracy selon la position dans l'enregistrement (effet apprentissage) ==")
        print(f"   protocole : {'ENTRELACÉ' if interleaved else 'blocs contigus'} "
              f"({runs} plages pour {n_tgt} cibles)")
        for i, part in enumerate(thirds, 1):
            a = sum(1 for m in part if m[0]) / len(part)
            print(f"   tiers {i} ({len(part)} déc.) : {a*100:5.1f}%  {_bar(a)}")
        a1 = sum(1 for m in thirds[0] if m[0]) / len(thirds[0])
        a3 = sum(1 for m in thirds[-1] if m[0]) / len(thirds[-1])
        if a3 - a1 <= 0.15:
            print("   -> pas de progression marquée.")
        elif interleaved:
            # Point important : entrelacer ne supprime pas l'apprentissage, il le REND INOFFENSIF.
            # Chaque cible étant répartie sur toute la séance, une progression globale les affecte
            # toutes également et ne peut plus créer d'écart artificiel entre elles.
            print("   -> PROGRESSION nette, mais blocs ENTRELACÉS : chaque cible est répartie sur")
            print("      toute la séance, donc l'apprentissage les affecte TOUTES également.")
            print("      Ce n'est pas un confondant — les écarts du §3 restent interprétables.")
        else:
            print("   -> PROGRESSION nette ET blocs contigus : l'ordre est un CONFONDANT.")
            print("      Les écarts entre cibles du §3 ne sont pas interprétables tels quels.")

    good = [(c, m) for ok, c, m, _ in margins if ok]
    bad = [(c, m) for ok, c, m, _ in margins if not ok]
    print("\n== 5. Seuils suggérés (distribution réelle des corrélations) ==")
    if good:
        gc = np.array([c for c, _ in good])
        gm = np.array([m for _, m in good])
        print(f"   décisions CORRECTES ({len(good)}) : ρ moy {gc.mean():.3f}  p10 {np.percentile(gc,10):.3f}"
              f"   marge moy {gm.mean():.3f}  p10 {np.percentile(gm,10):.3f}")
    if bad:
        bc = np.array([c for c, _ in bad])
        bm = np.array([m for _, m in bad])
        print(f"   décisions FAUSSES   ({len(bad)}) : ρ moy {bc.mean():.3f}  p90 {np.percentile(bc,90):.3f}"
              f"   marge moy {bm.mean():.3f}  p90 {np.percentile(bm,90):.3f}")
    if good and bad and np.mean([c for c, _ in bad]) >= np.mean([c for c, _ in good]):
        print("   ⚠️ ρ NE DISCRIMINE PAS : les décisions fausses ont un ρ moyen ≥ celui des")
        print("      bonnes. Un seuil sur ρ ne filtrerait donc pas les erreurs — c'est le VOTE")
        print("      glissant qui doit assurer la sécurité, pas CVEP_CORR_MIN.")
    if len(margins) < 15:
        print(f"   ⚠️ seulement {len(margins)} décisions : bien trop peu pour fixer un seuil.")
        print("      Ne PAS régler CVEP_CORR_MIN/CVEP_MARGIN là-dessus — allonge la calibration.")
    elif good and bad:
        corr_min = float(np.percentile([c for c, _ in good], 25))
        marg = float(max(0.02, np.percentile([m for _, m in bad], 75)))
        print(f"   -> CVEP_CORR_MIN ≈ {corr_min:.2f}   CVEP_MARGIN ≈ {marg:.2f}")
        print("      (rejeter plutôt que se tromper : le robot s'arrête, il ne part pas de travers)")

    best_itr = itrs.get(best_k, 0.0)
    print(f"\n== Bilan == {n_tgt} cibles, optimum à {best_k} cycle(s) "
          f"({best_k*code_len/refresh:.2f}s) : accuracy {acc*100:.1f}%, "
          f"**{best_itr:.1f} bits/min**")
    print(f"   -> mettre CVEP_DECISION_CYCLES = {best_k} dans config.py.")
    if best_itr < ref:
        print(f"   Reste sous le SSVEP ({ref:.0f} bits/min), qui garde l'avantage de la latence")
        print("   (1.5 s) et de l'absence de calibration.")
    else:
        print(f"   DÉPASSE le SSVEP ({ref:.0f} bits/min).")
    return True


def _parse(argv):
    p = argparse.ArgumentParser(description="Analyse hors ligne d'une calibration c-VEP.")
    p.add_argument("--file", default=DEFAULT_FILE)
    p.add_argument("--max-offset", type=int, default=50, help="balayage en échantillons (250 Hz)")
    p.add_argument("--step", type=int, default=5)
    p.add_argument("--max-k", type=int, default=4, help="cycles max moyennés par décision")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    a = _parse(sys.argv[1:])
    sys.exit(0 if analyze(a.file, a.max_offset, a.step, a.max_k) else 1)
