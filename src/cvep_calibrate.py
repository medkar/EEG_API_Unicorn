"""Calibration c-VEP : fixer chaque cible quelques secondes -> template + filtre spatial.

Beaucoup plus courte que la calibration Motor Imagery (~1 min contre 5-7 min) parce qu'on
n'apprend pas une intention mentale, seulement la **forme de ta réponse visuelle** au code.

Déroulé : les 3 cibles clignotent en permanence avec le même code décalé ; on te demande
d'en fixer une, et on enregistre `CVEP_CAL_CYCLES` cycles complets. On recommence pour
chaque cible. Enregistrer les 3 (plutôt qu'une seule) coûte le même temps total et vérifie
en prime que l'alignement des lags est bon (l'accuracy leave-one-out le dit).

Chaque époque est prélevée EXACTEMENT à une frontière de cycle (frame % L == 0) : la
fenêtre couvre alors le cycle qui vient de s'écouler, donc démarre à la phase 0 du code.
"""

import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (CH_NAMES, CVEP_CAL_BLOCKS, CVEP_CAL_CYCLES,  # noqa: E402
                    CVEP_CHANNELS, CVEP_LAG_ROTATION, CVEP_MODEL_PATH, cvep_lag_gap_ms)
from cvep_code import build_targets, is_on  # noqa: E402
from cvep_decoder import CVEPModel  # noqa: E402
from itr import itr  # noqa: E402
from ui import BG, DIM, FG, GO, WARN, Abort  # noqa: E402

SETTLE_CYCLES = 2   # cycles jetés après un changement de cible (déplacement du regard + VEP qui s'installe)
# Plancher d'utilité pour le contrôle de séance (bits/min). ~1/3 du meilleur c-VEP mesuré
# (27,1) : en dessous, la séance n'apprend rien qu'on ne sache déjà. Voir `_early_check`.
EARLY_ITR_MIN = 10.0

BRIEF = [
    "Calibration c-VEP",
    "",
    "• Les cibles clignotent selon un code pseudo-aléatoire (ça « grésille », c'est normal).",
    "• Une cible est CERCLÉE : fixe-la, sans bouger les yeux, jusqu'au changement.",
    "• Regard bien PLANTÉ sur le disque (contrairement au Motor Imagery : ici le regard compte).",
    "• Cligne le moins possible pendant l'enregistrement, reste immobile.",
    "• La durée totale est affichée dans la console au lancement.",
    "",
    "Appuie sur une touche pour commencer (ESC pour annuler).",
]


def _briefing(app):
    while True:
        pressed = []
        app.drain(on_key=lambda e: pressed.append(True))
        if pressed:
            return True
        app.win.fill(BG)
        h = app.win.get_height()
        y = int(h * 0.16)
        for i, line in enumerate(BRIEF):
            f = app.big if i == 0 else app.small
            col = FG if i == 0 else (GO if line.startswith("Appuie") else FG)
            app.center(f, line, col, y)
            y += int(h * 0.085) if i == 0 else int(h * 0.056)
        app.pygame.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return True


def _make_blocks(plan, cycles, n_blocks):
    """Découpe les cycles de chaque cible en `n_blocks` blocs, puis MÉLANGE l'ordre de passage.

    ⚠️ Sans ça, chaque cible occupe une tranche de temps distincte et « quelle cible » devient
    indissociable de « à quel moment » : mesuré le 2026-07-20, l'accuracy passait de 34% sur le
    premier tiers de la séance à 66% sur le dernier, ce qui faisait passer les deux dernières
    cibles pour les meilleures. Entrelacer répartit l'effet d'apprentissage sur toutes les cibles.
    """
    per = max(1, cycles // n_blocks)
    blocks = []
    for target in plan:
        left = cycles
        for b in range(n_blocks):
            n = left if b == n_blocks - 1 else min(per, left)
            if n > 0:
                blocks.append((target, n))
            left -= n
    random.shuffle(blocks)
    return blocks


def _wilson_hi(acc, n, z=1.96):
    """Borne SUPÉRIEURE de l'intervalle de Wilson (petits effectifs)."""
    if n == 0:
        return 1.0
    d = 1 + z * z / n
    c = (acc + z * z / (2 * n)) / d
    h = z * ((acc * (1 - acc) / n + z * z / (4 * n * n)) ** 0.5) / d
    return min(1.0, c + h)


def _early_check(model, epochs, lags, n_targets):
    """Verdict à mi-parcours : « cette séance peut-elle encore donner quelque chose ? »

    Le 2026-07-20 on a dépensé 4,5 min de casque sur une séance à 3,0 bits/min, et AUCUN
    indicateur pré-séance ne l'avait vue venir (le ratio alpha valait 18,93, le meilleur
    jamais mesuré ; la dérive brute ne discrimine pas). La seule mesure qui marche est la
    performance elle-même — autant la lire pendant l'enregistrement plutôt qu'après.

    ⚠️ Critère volontairement ASYMÉTRIQUE : on convertit la borne HAUTE de Wilson en ITR et
    on n'alerte que si même l'hypothèse la PLUS FAVORABLE reste inutile. Un LOO à mi-parcours
    porte sur peu d'époques : le lire comme une estimation ponctuelle ferait abandonner des
    séances correctes. Pas d'alerte ne veut donc PAS dire « ça va bien », seulement « on ne
    peut pas encore l'exclure » — c'est exactement ce qu'on attend d'un garde-fou.

    ⚠️ Le critère est en BITS/MIN, pas en accuracy. Une première version comparait l'accuracy
    à 2x le hasard : elle attrapait les liaisons mortes mais RATAIT la séance à 8 cibles du
    2026-07-20 (LOO 21 %, borne haute 30 %, seuil 25 % -> « continue », résultat final
    3,0 bits/min). Normal : 21 % à 8 cibles est réellement au-dessus du hasard, la séance
    n'était pas morte, elle était médiocre — et « 2x le hasard » ne veut pas dire la même
    chose à 4, 6 ou 8 cibles. L'ITR est la seule échelle comparable entre configurations.

    Le seuil vient de l'UTILITÉ projet, pas d'un ajustement sur les données : une séance qui
    ne peut pas atteindre ~1/3 de notre meilleur c-VEP (27,1 bits/min) n'apprend rien.
    Distinction importante — sur les 6 séances archivées, n'importe quel seuil entre 9 et 15
    « fonctionne », donc les valider dessus ne prouverait rien (4 points informatifs, 2
    dégénérés à 0). À revoir quand on aura une dizaine de séances.

    LIMITE CONNUE : ne détecte pas une séance qui s'effondre APRÈS le contrôle (la séance
    14:09 était à 15,8 de borne haute à 40 % puis a fini à 0, avec une accuracy décroissante
    au fil des tiers). Un contrôle ponctuel ne peut pas prédire une dégradation ultérieure.

    Retourne (alerte, accuracy, itr_borne_haute) ou None si les données ne suffisent pas.
    """
    by_lag = {}
    for l in lags:
        by_lag[l] = by_lag.get(l, 0) + 1
    if len(by_lag) < n_targets or min(by_lag.values()) < 2:
        return None                      # toutes les cibles doivent avoir été vues
    probe = CVEPModel(fs=model.fs, refresh=model.refresh, code_len=model.code_len)
    probe.channels = model.channels          # suivre le modèle réel, pas le défaut de config
    probe.fit([e[:, probe.channels] for e in epochs], lags)
    acc = probe.cv_
    if acc is None:
        return None
    hi = _wilson_hi(acc, len(epochs))
    hi_itr = itr(n_targets, hi, model.n_cyc / model.fs)
    return (hi_itr < EARLY_ITR_MIN), acc, hi_itr


def _draw(app, plan, spots, frame, target, done, total, b_idx, n_blocks):
    """Rendu d'une frame : toutes les cibles clignotent, celle à fixer est cerclée."""
    app.win.fill(BG)
    app.draw_ring(plan, spots, lambda c, f: is_on(f, c["code"]), frame, cue=target["name"])
    app.center(app.big, f"FIXE la cible {target['name']}", FG, 52)
    app.center(app.mid, f"bloc {b_idx}/{n_blocks}  —  cycle {done}/{total}",
               GO if done else WARN, 100)
    app.hud("ESC = annuler")
    app.pygame.display.flip()


def calibrate(app, cycles=CVEP_CAL_CYCLES, save_path=CVEP_MODEL_PATH):
    """Enregistre, entraîne, sauvegarde. Retourne (ok, accuracy_loo|None)."""
    plan, code = build_targets()
    L = len(code)
    spots = app.ring_spots(plan)
    acq = app.acq
    model = CVEPModel(fs=acq.fs, refresh=app.refresh, code_len=L)
    # On ENREGISTRE les 8 voies (rien n'est perdu, on pourra chercher le meilleur sous-ensemble
    # hors ligne) mais on n'AJUSTE que sur `model.channels` — donner 8 voies à une CCA calibrée
    # sur peu de cycles surapprend.
    rows = acq.eeg_rows
    epoch_s = model.n_cyc / acq.fs
    if app.smoke:
        cycles = 2

    blocks = _make_blocks(plan, cycles, CVEP_CAL_BLOCKS)
    gap = cvep_lag_gap_ms(len(plan), L, app.refresh)
    n_blk = len(blocks)
    est = (len(plan) * cycles + n_blk * SETTLE_CYCLES) * L / app.refresh / 60.0 + n_blk * 1.8 / 60.0
    print(f"[cvep-cal] code L={L} @ {app.refresh:.0f}Hz -> cycle {L/app.refresh:.2f}s "
          f"({model.n_cyc} éch.)  8 voies enregistrées, ajustement sur {model.channels}")
    print(f"[cvep-cal] {len(plan)} cibles, écart entre lags {gap:.0f} ms"
          + ("" if gap >= 150 else "  ⚠️ < durée VEP ~150 ms : cibles voisines confusables"))
    print(f"[cvep-cal] {cycles} cycles/cible, {n_blk} blocs entrelacés (ordre mélangé) "
          f" ≈ {est:.1f} min")
    if not _briefing(app):
        return False, None
    # liaison casque vérifiée AVANT d'investir 3,4 min ; voies clés (occipitales) encadrées
    if not app.signal_check(highlight=CVEP_CHANNELS, mode_label="c-VEP"):
        return False, None

    epochs, lags = [], []
    check_at = max(1, int(round(n_blk * 0.4)))   # bloc où se déclenche le contrôle de séance
    got_by_lag = {c["lag"]: 0 for c in plan}
    frame, prev_phase = 0, -1
    settle = 0 if app.smoke else SETTLE_CYCLES
    try:
        for b_idx, (target, n_cyc) in enumerate(blocks, start=1):
            # Surveillance en cours de séance : une liaison qui lâche au bloc 3 produirait
            # sinon 3 minutes de signal plat, puis un modèle à 0 % sans le moindre indice.
            if not app.smoke:
                _, qrows = app.signal_ok(0.5)
                dead = [n for n, _, v in qrows if v == "morte"]
                if dead:
                    print(f"[cvep-cal] ⛔ LIAISON PERDUE (voies plates : {', '.join(dead)}) "
                          f"au bloc {b_idx}/{len(blocks)} — arrêt, rien n'est entraîné.")
                    print("[cvep-cal] vérifie le câble du casque, les électrodes et les mastoïdes.")
                    app.flash("Liaison casque perdue",
                              f"voies plates : {', '.join(dead)} — vérifie le câble", 4.0)
                    return False, None
            got, skip, start = 0, settle, frame
            while got < n_cyc:
                app.drain()
                phase = frame % L
                # frontière de cycle : la fenêtre qui précède couvre un cycle entier depuis la phase 0
                if phase == 0 and prev_phase != 0:
                    if skip > 0:
                        skip -= 1
                    else:
                        ep = acq.get_epoch(epoch_s, rows=rows, filtered=False)
                        if ep is not None and len(ep) >= model.n_cyc:
                            epochs.append(ep[:model.n_cyc])
                            lags.append(target["lag"])
                            got += 1
                            got_by_lag[target["lag"]] += 1
                prev_phase = phase
                _draw(app, plan, spots, frame, target, got, n_cyc, b_idx, len(blocks))
                app.clock.tick(int(app.refresh) + 5)
                frame += 1
                # garde-fou headless : borne le temps passé par bloc sans fausser le compte
                if app.smoke and (frame - start) > (n_cyc + settle + 2) * L:
                    break
            print(f"[cvep-cal] bloc {b_idx}/{len(blocks)} {target['name']:<10} "
                  f"lag={target['lag']:>3} : {got} cycles", flush=True)
            # Garde-fou de séance : une fois seulement, à ~40 % du parcours (assez d'époques
            # pour que le LOO ait un sens, assez tôt pour que l'abandon fasse gagner du temps).
            if b_idx == check_at and not app.smoke:
                verdict = _early_check(model, epochs, lags, len(plan))
                if verdict is not None:
                    bad, acc, hi_itr = verdict
                    print(f"[cvep-cal] contrôle à mi-parcours ({len(epochs)} cycles) : "
                          f"LOO {acc*100:.0f}% (hasard {100.0/len(plan):.0f}%)  ->  au MIEUX "
                          f"{hi_itr:.1f} bits/min"
                          + (f"  ⚠️ SOUS LE PLANCHER D'UTILITÉ ({EARLY_ITR_MIN:.0f})" if bad
                             else "  -> on continue"), flush=True)
                    if bad:
                        app.flash("Séance mal engagée",
                                  f"au mieux {hi_itr:.0f} bits/min — ESC pour arrêter "
                                  f"(le déjà-enregistré est conservé)", 6.0)
            if b_idx < len(blocks):
                # inter-bloc = point de PAUSE sûr (époques du bloc déjà ramassées, le settle du
                # bloc suivant absorbe le redémarrage) -> ESPACE met en pause pendant cet écran
                app.flash("Change de cible",
                          f"prépare-toi à fixer {blocks[b_idx][0]['name']}   ·   Espace = pause",
                          1.8, skippable=False, pausable=True)
    except Abort:
        print("[cvep-cal] interrompu — entraînement sur ce qui est déjà enregistré.")
    print("[cvep-cal] cycles par cible : "
          + "  ".join(f"{c['name']}={got_by_lag[c['lag']]}" for c in plan))

    if len(set(lags)) < 2 or len(epochs) < 4:
        print("[cvep-cal] pas assez de données pour entraîner.")
        return False, None

    # Les époques stockées ont 8 voies ; le modèle n'ajuste que sur `model.channels`.
    model.fit([e[:, model.channels] for e in epochs], lags)
    model.save(save_path, n_targets=len(plan))
    if not app.smoke:
        # ⚠️ ARCHIVER, ne jamais écraser : dans un projet d'exploration les jeux de données SONT
        # le résultat. Une version antérieure n'écrivait que « cvep_calib_last.npz » et la
        # meilleure séance (27,1 bits/min) a été perdue à la calibration suivante — impossible
        # de comparer les amplitudes pour diagnostiquer l'effondrement.
        data = dict(epochs=np.asarray(epochs), lags=np.asarray(lags), fs=acq.fs,
                    refresh=app.refresh, n_targets=len(plan), rotation=CVEP_LAG_ROTATION,
                    channels=np.asarray(model.channels, dtype=int),   # voies AJUSTÉES
                    ch_names=np.asarray(CH_NAMES),                    # les 8 ENREGISTRÉES
                    sigma=float(np.asarray(epochs).std()))
        folder = os.path.dirname(save_path)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        archive = os.path.join(
            folder, f"cvep_calib_{stamp}_n{len(plan)}_rot{CVEP_LAG_ROTATION}.npz")
        np.savez(archive, **data)
        np.savez(os.path.join(folder, "cvep_calib_last.npz"), **data)   # raccourci d'analyse
        print(f"[cvep-cal] données archivées : {os.path.basename(archive)}")

    # Avec N cibles variable, l'accuracy brute n'est plus comparable d'une config à l'autre
    # (70% sur 6 cibles vaut bien plus que 70% sur 3). On rapporte donc l'ITR, l'échelle qui
    # combine nombre de choix, justesse et vitesse — cf. itr.py.
    from itr import itr as _itr
    cv = model.cv_ * 100 if model.cv_ is not None else float("nan")
    chance = 100.0 / len(plan)
    cycle_s = L / app.refresh
    bits = _itr(len(plan), model.cv_ or 0.0, cycle_s)
    ref = _itr(3, 0.95, 1.5)   # SSVEP actuel = la barre à battre
    verdict = ("DÉPASSE LE SSVEP" if bits >= ref else
               "PROMETTEUR" if bits >= ref / 2 else
               "FAIBLE (contact électrodes ? regard qui décroche ? refais un essai)")
    print(f"[cvep-cal] {len(epochs)} cycles sur {len(plan)} cibles -> accuracy leave-one-out "
          f"{cv:.1f}%  (hasard {chance:.0f}%)")
    print(f"[cvep-cal] ITR ≈ {bits:.1f} bits/min à 1 cycle ({cycle_s:.2f}s) — "
          f"SSVEP de référence {ref:.1f} -> {verdict}")
    print(f"[cvep-cal] `python src/cvep_analyze.py` pour le gain en moyennant plusieurs cycles.")
    print(f"[cvep-cal] modèle sauvegardé : {save_path}")

    t0 = time.perf_counter()
    while time.perf_counter() - t0 < (0.1 if app.smoke else 5.0):
        try:
            app.drain(on_key=lambda e: None)
        except Abort:
            break
        app.win.fill(BG)
        h = app.win.get_height()
        app.center(app.big, f"{cv:.0f}% sur {len(plan)} cibles", FG, int(h * 0.40))
        app.center(app.mid, f"{bits:.0f} bits/min   (SSVEP de référence : {ref:.0f})",
                   GO if bits >= ref / 2 else WARN, int(h * 0.52))
        app.center(app.small, verdict, DIM, int(h * 0.62))
        app.center(app.small, "modèle sauvegardé — ESC pour continuer", DIM, int(h * 0.70))
        app.pygame.display.flip()
        app.clock.tick(60)
    return bits >= ref / 2, model.cv_
