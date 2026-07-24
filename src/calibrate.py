"""Calibration des seuils de décision SSVEP à partir d'un log guidé étiqueté.

Lit un fichier produit par `live_ssvep.py --guided` (lignes `[PHASE] AVA=.. GAU=.. DRO=..
ARR=..`), et cherche les paramètres de décision qui SÉPARENT le mieux :
  - REPOS (ne rien fixer) : on veut 0 commande émise (faux positif = mauvais),
  - FIXATION d'une cible : on veut la bonne commande émise (vrai positif).

Décision d'une fenêtre = argmax ρ, ACCEPTÉE si ρ_max >= rho_min ET (ρ_max - ρ_2e) >= margin,
sinon "rien". Le lissage (vote glissant) est simulé par phase pour estimer les commandes
réellement émises.

    python src/calibrate.py                       # lit data/session1_2026-07-17.log
    python src/calibrate.py chemin/vers/mon.log
"""

import os
import re
import sys

_ORDER = ["AVANT", "GAUCHE", "DROITE", "ARRIERE"]
_ABBR = {"AVA": "AVANT", "GAU": "GAUCHE", "DRO": "DROITE", "ARR": "ARRIERE"}
_KEY = re.compile(r"\[([A-Z0-9\-]+)\]")
_TOK = re.compile(r"\b(AVA|GAU|DRO|ARR)=([\d.]+)")


def parse(path):
    """Retourne une liste de (phase_key, expected|None, {name: rho}). S'adapte au nombre
    de cibles (3 ou 4 colonnes) en lisant les tokens AVA=/GAU=/DRO=/ARR= présents."""
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            km, toks = _KEY.search(line), _TOK.findall(line)
            if not km or not toks:
                continue
            key = km.group(1)
            rho = {_ABBR[a]: float(v) for a, v in toks}
            expected = None if key.startswith("REPOS") else key
            rows.append((key, expected, rho))
    return rows


def target_names(rows):
    """Cibles présentes dans le dataset (ordre canonique)."""
    seen = {r[1] for r in rows if r[1] is not None}
    return [n for n in _ORDER if n in seen]


def decide(rho, rho_min, margin):
    """argmax + seuil + marge. Retourne un nom de commande, ou None."""
    ranked = sorted(rho.items(), key=lambda kv: kv[1], reverse=True)
    (best_name, best), (_, second) = ranked[0], ranked[1]
    if best >= rho_min and (best - second) >= margin:
        return best_name
    return None


def smoothed_emissions(seq, rho_min, margin, vote_len, min_votes):
    """Simule le vote glissant sur une séquence de fenêtres. Retourne la liste des
    commandes émises (une par fenêtre où un consensus existe ; peut répéter)."""
    from collections import Counter, deque
    buf, emitted = deque(maxlen=vote_len), []
    for rho in seq:
        buf.append(decide(rho, rho_min, margin))
        winner, count = Counter(buf).most_common(1)[0]
        emitted.append(winner if (winner is not None and count >= min_votes) else None)
    return emitted


def evaluate(rows, rho_min, margin):
    """Métriques fenêtre-par-fenêtre (sans lissage)."""
    rest = [r for r in rows if r[1] is None]
    rest_fp = sum(decide(r[2], rho_min, margin) is not None for r in rest) / max(1, len(rest))
    tp = {}
    for name in target_names(rows):
        fix = [r for r in rows if r[1] == name]
        if fix:
            tp[name] = sum(decide(r[2], rho_min, margin) == name for r in fix) / len(fix)
    return rest_fp, tp


def _phase_sequences(rows):
    """Regroupe les fenêtres en séquences consécutives par clé de phase."""
    seqs, cur_key, cur = [], None, []
    for key, expected, rho in rows:
        if key != cur_key and cur:
            seqs.append((cur_key, cur))
            cur = []
        cur_key, _ = key, cur.append(rho)
    if cur:
        seqs.append((cur_key, cur))
    return seqs


def homogeneity(rows, names, rho_min, margin):
    """Les cibles ont-elles VRAIMENT des taux de détection différents ? (khi-deux)

    Sous l'hypothèse « toutes les cibles se valent », les détections par cible suivent une
    binomiale de même paramètre. Sur quelques dizaines de fenêtres, un écart spectaculaire à
    l'œil est souvent banal. Ce test a déjà annulé une fausse piste côté c-VEP (p=0.53 sur
    l'écart qui avait lancé l'hypothèse) — et côté SSVEP la cible réputée « fragile » a changé
    trois fois de nom entre séances, ce qui est la signature du bruit, pas d'une faiblesse réelle.
    """
    from scipy.stats import chi2
    hits, tots = [], []
    for n in names:
        fix = [r for r in rows if r[1] == n]
        if not fix:
            return None
        hits.append(sum(decide(r[2], rho_min, margin) == n for r in fix))
        tots.append(len(fix))
    glob = sum(hits) / sum(tots)
    if glob <= 0 or glob >= 1:
        return None
    stat = sum((h - t * glob) ** 2 / (t * glob) for h, t in zip(hits, tots))
    return stat, len(names) - 1, float(chi2.sf(stat, len(names) - 1)), hits, tots


def baselines(rows, key):
    """ρ moyen par cible sur une phase de REPOS = plancher de bruit propre à chaque fréquence.

    Ce plancher n'est PAS le même pour toutes : une cible proche du pic alpha hérite d'un ρ
    de fond élevé. Un seuil global est donc structurellement injuste — il est trop bas pour
    la cible contaminée et trop haut pour la cible propre.
    """
    sel = [r[2] for r in rows if r[0] == key]
    if not sel:
        return None
    return {n: sum(r[n] for r in sel) / len(sel) for n in sel[0]}


def debias(rows, bias):
    return [(k, e, {n: v - bias.get(n, 0.0) for n, v in r.items()}) for k, e, r in rows]


def spreads(rows, key):
    """Écart-type du ρ au repos, par cible. Une fréquence contaminée par l'alpha n'a pas
    seulement un plancher plus haut : elle FLUCTUE plus (bouffées alpha). Normaliser par
    cette dispersion rend un seuil unique équitable entre cibles."""
    sel = [r[2] for r in rows if r[0] == key]
    if not sel:
        return None
    mu = {n: sum(r[n] for r in sel) / len(sel) for n in sel[0]}
    return {n: max(1e-3, (sum((r[n] - mu[n]) ** 2 for r in sel) / len(sel)) ** 0.5)
            for n in sel[0]}


def zscore(rows, mu, sd):
    """ρ exprimé en écarts-types au-dessus du bruit propre à CHAQUE fréquence."""
    return [(k, e, {n: (v - mu.get(n, 0.0)) / sd.get(n, 1.0) for n, v in r.items()})
            for k, e, r in rows]


def _best_point(rows, max_fp=0.02):
    """Meilleur (rho_min, margin) : TP moyen max sous contrainte de faux positifs au repos.

    La grille est déduite de l'étendue réelle des scores : brut (0..1), débiaisé (-0.3..0.4)
    et z-score (-2..+5) n'ont pas du tout les mêmes plages, un balayage en dur serait faux.
    """
    vals = [v for _, _, r in rows for v in r.values()]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    best = None
    for rm in [lo + span * i / 32 for i in range(33)]:
        for mg in [span * i / 24 for i in range(25)]:
            fp, tp = evaluate(rows, rm, mg)
            if not tp:
                continue
            # On maximise le TP MINIMUM, pas le moyen : sur une interface à 3 commandes, un
            # réglage à 89%/0%/0% a un excellent TP moyen et ne sert à rien (le robot ne sait
            # qu'avancer). Le maillon faible est ce qui décide de l'utilisabilité.
            score = min(tp.values())
            if fp <= max_fp and (best is None or score > best[3]):
                best = (rm, mg, fp, score, tp)
    return best


def compare_debias(rows, names):
    """Compare décision brute vs débiaisée, À ARMES ÉGALES.

    Le biais est estimé sur REPOS-1 et l'évaluation se fait sur tout le reste (REPOS-2 +
    fixations) : aucune donnée d'estimation ne sert à l'évaluation.
    """
    bias = baselines(rows, "REPOS-1")
    if bias is None:
        print("\n(pas de phase REPOS-1 : comparaison débiaisée impossible)")
        return
    held = [r for r in rows if r[0] != "REPOS-1"]
    n_rest = sum(1 for r in held if r[1] is None)
    print(f"\n== Débiaisage par fréquence (biais estimé sur REPOS-1, évalué sur le reste : "
          f"{n_rest} fenêtres de repos) ==")
    print("   plancher au repos : " + "  ".join(f"{n}={bias[n]:.2f}" for n in names))

    sd = spreads(rows, "REPOS-1")
    print("   dispersion repos  : " + "  ".join(f"{n}={sd[n]:.2f}" for n in names))
    variants = (("brut     ", held),
                ("débiaisé ", debias(held, bias)),
                ("z-score  ", zscore(held, bias, sd)))
    for label, rws in variants:
        best = _best_point(rws)
        if best is None:
            print(f"   {label} : AUCUN réglage n'atteint ≤2% de faux positifs au repos.")
            continue
        rm, mg, fp, worst, tp = best
        print(f"   {label} : rho_min={rm:.2f} margin={mg:.2f} -> FP repos {fp*100:4.1f}%  "
              f"TP mini {worst*100:5.1f}%   (" + " ".join(f"{n}={tp.get(n,0)*100:.0f}%"
                                                          for n in names) + ")")
        seqs = _phase_sequences(rws)
        rest_emit = fix_ok = fix_total = 0
        for key, seq in seqs:
            em = smoothed_emissions(seq, rm, mg, 4, 3)
            if key.startswith("REPOS"):
                rest_emit += sum(e is not None for e in em)
            else:
                fix_total += 1
                fix_ok += any(e == key for e in em)
        print(f"   {' ' * len(label)}   vote 3/4 -> émissions au REPOS = {rest_emit} (vise 0) ; "
              f"cibles détectées = {fix_ok}/{fix_total}")


def main(path):
    rows = parse(path)
    names = target_names(rows)
    rest = [r for r in rows if r[1] is None]
    print(f"Dataset : {len(rows)} fenêtres  (repos={len(rest)}, "
          + ", ".join(f"{n}={sum(1 for r in rows if r[1]==n)}" for n in names) + ")\n")

    # Séparabilité par cible : ρ moyen en fixation vs ρ de cette même fréquence au repos.
    print("Séparabilité (ρ de la cible quand on la fixe  vs  au repos) :")
    for name in names:
        fix = [r[2][name] for r in rows if r[1] == name]
        rst = [r[2][name] for r in rest]
        mf, mr = sum(fix) / len(fix), sum(rst) / len(rst)
        print(f"  {name:<8} fixation μ={mf:.2f}   repos μ={mr:.2f}   écart={mf - mr:+.2f}")

    # Grille (rho_min x margin) : FP repos (fenêtre) / TP moyen fixation (fenêtre).
    print("\nGrille — faux positifs REPOS % (fenêtre) :")
    margins = [0.00, 0.05, 0.10, 0.15, 0.20]
    print("rho_min \\ margin | " + "  ".join(f"{m:.2f}" for m in margins))
    for rm in [0.25, 0.35, 0.40, 0.45, 0.50]:
        cells = []
        for mg in margins:
            fp, _ = evaluate(rows, rm, mg)
            cells.append(f"{fp*100:4.0f}")
        print(f"      {rm:.2f}      | " + "   ".join(cells))

    # Choix : plus petit couple qui donne ~0% FP repos, puis TP fixation.
    best = None
    for rm in [0.40, 0.42, 0.45, 0.48, 0.50]:
        for mg in [0.10, 0.12, 0.15, 0.18, 0.20]:
            fp, tp = evaluate(rows, rm, mg)
            mean_tp = sum(tp.values()) / len(tp)
            if fp <= 0.02 and (best is None or mean_tp > best[3]):
                best = (rm, mg, fp, mean_tp, tp)

    print("\n== Point de fonctionnement recommandé (FP repos ≤ 2%) ==")
    if best is None:
        print("  Aucun couple n'atteint <2% de FP au repos par fenêtre — le lissage devient")
        print("  indispensable (voir ci-dessous), ou il faut changer les fréquences basses.")
        rm, mg = 0.45, 0.15
    else:
        rm, mg, fp, mean_tp, tp = best
        print(f"  rho_min={rm:.2f}  margin={mg:.2f}")
        print(f"  FP repos (fenêtre) : {fp*100:.1f}%")
        print("  TP fixation        : " + "  ".join(f"{n}={tp.get(n,0)*100:.0f}%" for n in names))

    # Effet du lissage à ce point (vote 5/6 vs 3/4).
    print("\n== Avec lissage (vote glissant) à rho_min="
          f"{rm:.2f}, margin={mg:.2f} ==")
    seqs = _phase_sequences(rows)
    for vote_len, min_votes in [(4, 3), (6, 5)]:
        rest_emit = fix_ok = fix_total = 0
        for key, seq in seqs:
            em = smoothed_emissions(seq, rm, mg, vote_len, min_votes)
            if key.startswith("REPOS"):
                rest_emit += sum(e is not None for e in em)
            else:
                fix_total += 1
                if any(e == key for e in em):
                    fix_ok += 1
        print(f"  vote {min_votes}/{vote_len} : commandes émises au REPOS = {rest_emit} "
              f"(vise 0) ; cibles détectées en fixation = {fix_ok}/{fix_total}")

    h = homogeneity(rows, names, rm, mg)
    if h:
        stat, ddl, pval, hits, tots = h
        print(f"\n== Les cibles diffèrent-elles vraiment ? (khi-deux à rho_min={rm:.2f}, "
              f"margin={mg:.2f}) ==")
        print("  " + "  ".join(f"{n}={hi}/{to}" for n, hi, to in zip(names, hits, tots)))
        print(f"  χ²={stat:.2f}  ddl={ddl}  p={pval:.3f}")
        print("  -> " + ("ÉCARTS RÉELS (p<0.05) : il y a quelque chose à expliquer."
                         if pval < 0.05 else
                         "écarts COMPATIBLES avec le hasard.\n"
                         "     Ne PAS bâtir d'hypothèse ni retoucher les fréquences là-dessus :\n"
                         "     la cible « la plus faible » change de nom d'une séance à l'autre."))

    compare_debias(rows, names)


if __name__ == "__main__":
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "session1_2026-07-17.log")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from config import use_utf8_console
    use_utf8_console()
    main(sys.argv[1] if len(sys.argv) > 1 else default)
