"""Analyse hors ligne d'un run P300 live (data/p300_live_last.npz) — SANS casque.

Trois sorties :
  [1] accuracy réelle du run (pick vs cible visée), sélection par sélection ;
  [2] biais par position : score moyen par cible sur tout le run (un chiffre haut PARTOUT sur
      une même cible = artefact fixe ; à plat = pas de biais) ;
  [3] accuracy vs nombre de répétitions moyennées (sous-échantillonnage) -> règle P300_REPS.

PROTOCOLE DE CAPTURE (pour que l'accuracy ait un sens) : lance « P300 -> Lancer le live » et VISE
LES CIBLES DANS L'ORDRE HORAIRE DEPUIS LE HAUT, une sélection chacune :
    AVANT · AV-DROITE · AR-DROITE · ARRIERE · AR-GAUCHE · AV-GAUCHE
(recommence le tour pour plus d'essais), puis ESC. C'est l'ordre par défaut ci-dessous.

    python src/research/p300_analyze.py
    python src/research/p300_analyze.py --order AVANT,ARRIERE,AVANT,...   # si tu as visé un autre ordre
    python src/research/p300_analyze.py chemin/vers.npz
"""

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import DATA_DIR, P300_MODEL_PATH, p300_targets, use_utf8_console  # noqa: E402
from research.p300_decoder import P300Model  # noqa: E402

RING = [c["name"] for c in p300_targets()]     # ordre horaire depuis le haut (= ordre à viser)
DATA = os.path.join(DATA_DIR, "p300_live_last.npz")


def _load(path):
    d = np.load(path, allow_pickle=True)
    return d["epochs"], d["names"].astype(str), d["sel"].astype(int), float(d["fs"])


def _group(names, sel):
    """sel -> {nom_cible: [indices d'époques]} (dans l'ordre d'enregistrement)."""
    out = {}
    for i in range(len(sel)):
        out.setdefault(int(sel[i]), {}).setdefault(names[i], []).append(i)
    return out


def main(path, order):
    if not os.path.exists(path):
        print(f"[p300-an] fichier absent : {path}\n"
              "  Lance d'abord un run live P300 (il sauve data/p300_live_last.npz à l'ESC).")
        return
    if not os.path.exists(P300_MODEL_PATH):
        print("[p300-an] pas de modèle P300 (data/p300_model.joblib) — calibre d'abord.")
        return
    model = P300Model.load(P300_MODEL_PATH)
    epochs, names, sel, fs = _load(path)
    sels = _group(names, sel)
    order_sels = sorted(sels)
    n_sel = len(order_sels)
    intended = [(order * (n_sel // len(order) + 1))[:n_sel][k] for k in range(n_sel)]
    reps = min(len(idxs) for s in sels.values() for idxs in s.values())
    print(f"{os.path.basename(path)} : {len(epochs)} époques, {n_sel} sélections, "
          f"{reps} rép/cible, fs={fs:g} Hz  (modèle AUC calib={model.cv_auc_ and round(model.cv_auc_*100)}%)")
    print(f"cibles visées supposées : {' · '.join(intended)}\n")

    # [1] accuracy pleine + détail
    ok = 0
    per_target_scores = {nm: [] for nm in RING}
    print("[1] Accuracy pleine (toutes les répétitions) :")
    for k, si in enumerate(order_sels):
        by = {nm: epochs[np.asarray(idxs)] for nm, idxs in sels[si].items()}
        pick, scores = model.select(by)
        for nm, sc in scores.items():
            per_target_scores.setdefault(nm, []).append(sc)
        good = (pick == intended[k])
        ok += good
        s_pick = scores.get(pick, float("nan"))
        s_want = scores.get(intended[k], float("nan"))
        print(f"   {'OK ' if good else 'XX '} visé={intended[k]:<10} pick={pick:<10} "
              f"(score pick {s_pick:+.2f} / visé {s_want:+.2f})")
    print(f"   => {ok}/{n_sel} = {ok/n_sel*100:.0f}%  (hasard {100/len(RING):.0f}%)\n")

    # [2] biais par position
    print("[2] Score moyen « cible » par position (biais fixe si une cible reste haute partout) :")
    for nm in sorted(per_target_scores, key=lambda n: -np.mean(per_target_scores[n] or [0])):
        v = np.asarray(per_target_scores[nm] or [np.nan])
        print(f"   {nm:<10} moy={v.mean():+.2f}   [min {v.min():+.2f}  max {v.max():+.2f}]")
    print()

    # [3] accuracy vs répétitions moyennées
    print("[3] Accuracy vs nombre de répétitions moyennées (20 tirages aléatoires) :")
    rng = np.random.default_rng(0)
    for kk in range(1, reps + 1):
        accs = []
        for _ in range(20):
            good = 0
            for k, si in enumerate(order_sels):
                by = {nm: epochs[rng.choice(np.asarray(idxs), size=kk, replace=False)]
                      for nm, idxs in sels[si].items()}
                pick, _ = model.select(by)
                good += (pick == intended[k])
            accs.append(good / n_sel)
        bar = "#" * int(round(np.mean(accs) * 30))
        print(f"   {kk:2d} rép -> {np.mean(accs)*100:5.1f}%  {bar}")
    print("\n(le genou de la courbe [3] = le P300_REPS à retenir : au-delà, on paie du temps "
          "pour ~rien)")


if __name__ == "__main__":
    use_utf8_console()
    p = argparse.ArgumentParser(description="Analyse hors ligne d'un run P300 live (EEG_API_Unicorn).")
    p.add_argument("path", nargs="?", default=DATA, help="npz (défaut : data/p300_live_last.npz)")
    p.add_argument("--order", default=",".join(RING),
                   help="cibles visées, séparées par des virgules (défaut : ordre horaire)")
    a = p.parse_args(sys.argv[1:])
    order = [s.strip() for s in a.order.split(",") if s.strip()]
    main(a.path, order)
