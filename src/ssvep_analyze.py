"""Analyse hors ligne d'un run guidé SSVEP — sans casque, sur `data/ssvep_guided_*.npz`.

Le pendant SSVEP de `cvep_analyze.py`. Jusqu'au 2026-07-20 le SSVEP ne conservait que les ρ,
c'est-à-dire la SORTIE du décodeur : toute idée d'amélioration exigeait une nouvelle séance.
`live_ssvep.py --guided` archive désormais les fenêtres brutes 8 voies, ce qui permet de rejouer
et de comparer des variantes sur les mêmes données.

Ce que l'outil répond :
  1. le signal est-il là ? (accuracy argmax sur les fixations, vs hasard)
  2. quelles voies ? (occipital seul vs + Pz — jamais tranché faute de données brutes)
  3. la normalisation z apporte-t-elle quelque chose sur CETTE séance ?
  4. combien de fenêtres sont des artefacts, et que coûtent-elles ?

⚠️ Les fenêtres se CHEVAUCHENT (1,5 s prélevée toutes les 0,25 s) : l'effectif indépendant vaut
environ `durée_de_phase / 1,5`, soit ~5 par cible et non 28. Les accuracies sont donc optimistes
et surtout TRÈS bruitées — comparer les configurations entre elles, jamais lire un chiffre absolu.

    python src/ssvep_analyze.py                     # dernier run archivé
    python src/ssvep_analyze.py --file data/ssvep_guided_20260720-151733.npz
"""

import argparse
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from acquisition import UnicornAcquisition  # noqa: E402
from cca_decoder import CCADecoder  # noqa: E402
from config import ARTIFACT_SIGMA_RATIO, CH_NAMES, OCCIPITAL, use_utf8_console  # noqa: E402

# Jeux de voies FIGÉS, indépendants de `OCCIPITAL` : depuis que Pz est passé dans la config,
# dériver la comparaison de OCCIPITAL rendrait les deux colonnes identiques et l'outil ne
# pourrait plus servir à re-trancher la question sur de nouveaux runs.
OCC3 = [CH_NAMES.index(n) for n in ("PO7", "Oz", "PO8")]
OCC_PZ = [CH_NAMES.index(n) for n in ("Pz", "PO7", "Oz", "PO8")]


def _latest():
    files = sorted(glob.glob(os.path.join(_ROOT, "data", "ssvep_guided_*.npz")))
    return files[-1] if files else None


def _scores(ep, lab, names, freqs, chans, flt, zscore):
    """ρ par fenêtre pour un jeu de voies, éventuellement normalisés par le repos."""
    dec = CCADecoder(freqs)
    f2n = {round(f, 4): n for f, n in zip(freqs, names)}
    S = []
    for e in ep:
        sig = flt._filter(np.ascontiguousarray(e[:, chans]))
        S.append({f2n[round(f, 4)]: v for f, v in dec.scores(sig).items()})
    if zscore:
        rest = [s for s, y in zip(S, lab) if y == "REPOS"]
        if len(rest) >= 5:
            mu = {n: float(np.mean([s[n] for s in rest])) for n in names}
            sd = {n: max(1e-3, float(np.std([s[n] for s in rest]))) for n in names}
            S = [{n: (s[n] - mu[n]) / sd[n] for n in names} for s in S]
    return S


def _eval(S, lab, names, keep=None):
    """(accuracy argmax sur les fixations, séparabilité fixation-repos par cible)."""
    idx = range(len(S)) if keep is None else [i for i, k in enumerate(keep) if k]
    fix = [(S[i], lab[i]) for i in idx if lab[i] in names]
    rest = [S[i] for i in idx if lab[i] == "REPOS"]
    if not fix or not rest:
        return None, {}
    acc = float(np.mean([max(s, key=s.get) == y for s, y in fix]))
    sep = {}
    for n in names:
        got = [s[n] for s, y in fix if y == n]
        sep[n] = (float(np.mean(got)) - float(np.mean([s[n] for s in rest]))) if got else 0.0
    return acc, sep


def analyze(path=None):
    path = path or _latest()
    if not path or not os.path.exists(path):
        print("[ssvep-an] aucun run guidé archivé. Lance `python src/live_ssvep.py --guided`.")
        return False
    d = np.load(path, allow_pickle=True)
    ep, lab = d["epochs"], [str(x) for x in d["labels"]]
    freqs = [float(f) for f in d["freqs"]]
    names = [str(n) for n in d["names"]]
    counts = {n: lab.count(n) for n in sorted(set(lab))}
    chance = 100.0 / len(names)

    print(f"\n== Run guidé SSVEP : {os.path.basename(path)}")
    print(f"   {len(ep)} fenêtres de {ep.shape[1]} éch. x {ep.shape[2]} voies · "
          f"fs={float(d['fs']):.0f}Hz")
    print(f"   cibles " + "  ".join(f"{n}={f:.2f}Hz" for n, f in zip(names, freqs))
          + f"   |  fenêtres {counts}   (hasard {chance:.0f}%)")

    flt = UnicornAcquisition(synthetic=True)   # emprunte _filter (aucune session ouverte)

    print("\n== 1. Voies et normalisation (accuracy argmax sur les fixations) ==")
    best = None
    cached = {}
    for chans, cname in ((OCC3, "occipital " + "/".join(CH_NAMES[i] for i in OCC3)),
                         (OCC_PZ, "+ Pz")):
        for z in (False, True):
            S = _scores(ep, lab, names, freqs, chans, flt, z)
            cached[(tuple(chans), z)] = S
            acc, sep = _eval(S, lab, names)
            if acc is None:   # run trop court : pas de fixation ou pas de repos exploitable
                print(f"   {cname:<28} (pas assez de fenêtres étiquetées)")
                continue
            seps = "  ".join(f"{n}={sep.get(n, 0.0):+.2f}" for n in names)
            tag = cname + (" + z" if z else "")
            print(f"   {tag:<28} {acc*100:5.1f}%   séparabilité  {seps}")
            if best is None or acc > best[0]:
                best = (acc, tuple(chans), z, cname)
    if best is None:
        # run interrompu avant la 1re fixation (observé : 24 fenêtres, toutes REPOS)
        print("   -> aucune fixation exploitable : run interrompu trop tôt, rien à analyser.")
        return False
    print(f"   -> meilleure config ici : {best[3]}{' + z' if best[2] else ''} "
          f"({best[0]*100:.1f}%)")
    print("   ⚠️ fenêtres chevauchantes -> effectif indépendant ~5/cible : NE PAS trancher sur")
    print("      une seule séance. Relancer sur plusieurs runs avant de toucher OCCIPITAL.")

    print("\n== 2. Artefacts (σ aberrant = mouvement/clignement, pas de l'EEG) ==")
    sig = np.array([float(np.mean(np.std(flt._filter(np.ascontiguousarray(e[:, OCC_PZ])), axis=0)))
                    for e in ep])
    med = float(np.median(sig))
    print(f"   σ médian {med:.1f}   max {sig.max():.0f} ({sig.max()/max(med,1e-9):.0f}x)   "
          f"au-delà de {ARTIFACT_SIGMA_RATIO}x : {(sig > ARTIFACT_SIGMA_RATIO*med).sum()}/{len(sig)}")
    S = cached[(tuple(best[1]), best[2])]
    for mult in (None, 5.0, ARTIFACT_SIGMA_RATIO, 2.0):
        keep = None if mult is None else (sig <= mult * med)
        acc, sep = _eval(S, lab, names, keep)
        if acc is None:
            continue
        n_fix = len([1 for i, y in enumerate(lab)
                     if y in names and (keep is None or keep[i])])
        seps = "  ".join(f"{n}={sep[n]:+.2f}" for n in names)
        tag = "aucun rejet" if mult is None else f"rejet > {mult:g}x médiane"
        print(f"   {tag:<22} {acc*100:5.1f}%  ({n_fix} fen.)   {seps}")
    return True


def _parse(argv):
    p = argparse.ArgumentParser(description="Analyse hors ligne d'un run guidé SSVEP.")
    p.add_argument("--file", default=None, help="npz (défaut : le plus récent)")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if analyze(_parse(sys.argv[1:]).file) else 1)
