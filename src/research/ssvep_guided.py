"""Rejouer un run guidé SSVEP archivé — sans casque, sans écran, avec d'autres réglages.

⚠️ **Ce fichier a perdu ses deux tiers le 2026-09-09**, et c'est la moitié qui reste qui est
décrite ici. Il était un monolithe : il affichait le stimulus, ouvrait le casque, enregistrait, et
analysait. Les deux premières parties sont **dans l'application** depuis ce jour-là, parce
qu'afficher un stimulus et ouvrir le casque sont de l'USAGE RÉEL, et que l'usage réel ne se tape
pas dans un terminal :

  • le stimulus et la désignation des cibles -> `src/stimulus/ssvep.py --guide`, que la console
    lance elle-même ;
  • l'acquisition et la décision -> `src/core/modes/ssvep_mesure.py`, la mesure « Taux d'émission
    SSVEP » de la grille.

Ce qui reste ICI est du travail de banc d'essai : **rejouer un enregistrement déjà pris**, avec
d'autres réglages, pour répondre à des questions que la mesure ne pose pas — un test de
permutation, une matrice de confusion, l'effet d'un jeu de voies ou d'un seuil. Ça ne touche ni au
casque ni à un écran, donc ça a le droit de vivre dans `research/`.

⚠️ **Le décodage n'est PAS réécrit ici.** Tout passe par `core.modes.ssvep_mesure.rejouer`,
c'est-à-dire par le code que la mesure exécute en séance. Une seconde écriture serait un second
décodeur : les deux s'accorderaient le jour de leur écriture, puis l'un des deux serait corrigé et
les chiffres du banc d'essai cesseraient de décrire le produit — sans que rien ne le dise.

⚠️ **Les trois invariants du protocole ne sont plus tenus ici**, et il faut savoir où ils sont
passés avant de conclure quoi que ce soit sur un vieux fichier :
  1. la CHAUFFE  -> `MesureRuntime.warmup_s` ;
  2. l'ordre ENTRELACÉ et tiré au sort -> `stimulus/ssvep.py::schedule` ;
  3. **un essai = une décision** -> `MesureSSVEP._decision_de_l_essai`, et l'effectif rendu par
     `rejouer` est un nombre d'ESSAIS. Ne le recompte pas en fenêtres ici : elles se chevauchent
     (1,5 s toutes les 0,2 s), et les compter gonflerait l'effectif d'un facteur ~7 pour un
     intervalle de confiance faux d'un facteur √7.

⚠️ **Les archives que ce fichier lit sont HISTORIQUES.** La mesure du moteur n'écrit rien — c'est
sa définition — donc plus aucun `data/ssvep_run_*.npz` n'est produit depuis le 2026-09-09. Ce qui
reste dans `data/` vient du monolithe.

    python src/research/ssvep_guided.py                 # rejoue le dernier run archivé
    python src/research/ssvep_guided.py --file data/ssvep_run_20260727-104512.npz
    python src/research/ssvep_guided.py --permutations 50000
    python src/research/ssvep_guided.py --smoke         # autotest : rejeu sur un run FABRIQUÉ
"""

import argparse
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))      # -> src/
from core.config import DATA_DIR, use_utf8_console  # noqa: E402
# ⚠️ Le décodage ET l'intervalle de confiance viennent du MOTEUR, importés et jamais recopiés.
# `wilson` en particulier : deux écritures d'un intervalle de Wilson se ressemblent assez pour
# qu'on ne compare jamais leurs sorties, et assez peu pour qu'elles diffèrent sur les petits
# effectifs — c'est-à-dire exactement le cas de ce protocole.
from core.modes.ssvep_mesure import longueur_bloc_attendue, rejouer, wilson  # noqa: E402


def _latest():
    files = sorted(glob.glob(os.path.join(DATA_DIR, "ssvep_run_*.npz")))
    return files[-1] if files else None


def analyze(path=None, permutations=10000, seed=0):
    """Rejoue la règle du moteur sur un run archivé, puis va PLUS LOIN que la mesure.

    Ce que la mesure du moteur rend déjà : le taux d'émission, la justesse, l'intervalle de
    confiance, le verdict. Ce qu'on ajoute ici, parce que ça n'a de sens qu'après coup et sur un
    fichier : un test de PERMUTATION (le taux observé survit-il à un étiquetage au hasard ?) et une
    matrice de CONFUSION (quelle cible pose problème ?).
    """
    path = path or _latest()
    if not path or not os.path.exists(path):
        print("[guidé] aucun run archivé (data/ssvep_run_*.npz).\n"
              "        Ces fichiers sont HISTORIQUES : la mesure du moteur n'écrit rien. Pour "
              "mesurer\n        le taux d'émission d'aujourd'hui, ouvre la console et lance la "
              "tuile « Taux d'émission SSVEP ».")
        return False

    d = np.load(path, allow_pickle=False)
    names = [str(n) for n in d["names"]]
    freqs = [float(f) for f in d["freqs"]]
    blocs, etiquettes = d["trials"], [str(s) for s in d["labels"]]
    repos = list(d["baseline"])

    print(f"\n=== {os.path.basename(path)} ===")
    print(f"{len(blocs)} essais · {len(repos)} fenêtres de repos · "
          f"refresh {float(d['refresh']):.1f} Hz")
    print("cibles : " + "  ".join(f"{n}@{f:.2f}Hz" for n, f in zip(names, freqs)))

    # Le run doit avoir été pris sous les MÊMES constantes de fenêtre, sinon le rejeu ne
    # reproduirait plus la règle du moteur — et ça ne se verrait pas : chaque essai compterait
    # comme « aucune cible » et le taux tomberait à 0 %, lu comme une panne de casque.
    attendu = longueur_bloc_attendue()
    if blocs.shape[1] != attendu:
        print(f"⚠️ run enregistré avec d'autres réglages (bloc {blocs.shape[1]} éch. contre "
              f"{attendu} attendus) : WINDOW_S / FILTER_MARGIN_S ont changé depuis. Le rejeu ne "
              f"reproduirait plus la règle du moteur. Abandon.")
        return False

    index = {n: i for i, n in enumerate(names)}
    essais = [(bloc, index[nom]) for bloc, nom in zip(blocs, etiquettes) if nom in index]
    try:
        res = rejouer(essais, repos, freqs, float(d["fs"]))
    except ValueError as e:
        print(f"[guidé] rejeu impossible : {e}")
        return False

    print(f"\n--- La règle du moteur, rejouée ---")
    print(res["verdict"])

    # --- Ce que la mesure ne fait PAS (1) : le test de permutation -------------------------
    # Le taux observé survit-il à un étiquetage au hasard ? Calculé sur l'accuracy GLOBALE (un
    # essai sans décision compte comme faux), parce que c'est elle qui se compare au hasard.
    decisions = res["decisions"]
    vraies = np.array([c for c, _d in decisions])
    predites = np.array([-1 if d is None else d for _c, d in decisions])
    justes = int(np.sum(vraies == predites))
    n = len(decisions)
    lo, hi = wilson(justes, n)
    rng = np.random.default_rng(seed)
    nul = np.empty(permutations)
    for i in range(permutations):
        nul[i] = np.mean(predites == rng.permutation(vraies))
    pval = (np.sum(nul >= justes / n) + 1) / (permutations + 1)
    print(f"\n--- Ce que la mesure ne calcule pas ---")
    print(f"ACCURACY GLOBALE (sans décision = faux) = {justes}/{n} = {justes / n * 100:.1f} %   "
          f"IC95 [{lo * 100:.1f} ; {hi * 100:.1f}]   (hasard {res['hasard'] * 100:.1f} %)")
    print(f"permutation ({permutations} tirages) : p = {pval:.4f}"
          + ("  -> significatif" if pval < 0.05 else "  -> NON significatif (= bruit)"))

    # --- Ce que la mesure ne fait PAS (2) : QUELLE cible pose problème ---------------------
    print(f"\n--- Confusion (lignes = fixé, colonnes = décodé) ---")
    print("         " + "".join(f"{c[:6]:>8}" for c in names) + f"{'rien':>8}")
    for i, nom in enumerate(names):
        ligne = [int(np.sum((vraies == i) & (predites == j))) for j in range(len(names))]
        rien = int(np.sum((vraies == i) & (predites == -1)))
        total = sum(ligne) + rien
        acc = ligne[i] / total * 100 if total else 0.0
        print(f"{nom[:8]:<9}" + "".join(f"{v:>8}" for v in ligne) + f"{rien:>8}   ({acc:.0f} %)")

    print("\nLecture : l'effectif est le nombre d'ESSAIS (fenêtres non chevauchantes), pas le "
          "nombre de\nfenêtres du moteur. Un taux au-dessus du hasard avec p < 0,05 dit que le "
          "décodage marchait\nCE jour-là ; il ne dit pas qu'il marchera demain — la variance entre "
          "séances est de l'ordre\nd'un facteur 9 sur ce casque.")
    return True


def _smoke():
    """Rejeu sur un run FABRIQUÉ, dans un dossier temporaire. `data/` n'est jamais touché.

    Ce que ça prouve : que ce fichier sait encore lire un archive et que le chemin de décodage
    qu'il APPELLE (celui du moteur) rend un verdict — pas que le décodage est juste, ce que
    `python src/core/modes/ssvep_mesure.py` vérifie déjà sur du signal dont on connaît la réponse.
    """
    import tempfile

    from core.config import FS_UNICORN, empreinte_dossier

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    empreinte_avant = empreinte_dossier(DATA_DIR)
    besoin = longueur_bloc_attendue()
    noms = ["AVANT", "GAUCHE", "DROITE"]
    freqs = [15.0, 20.0, 60.0 / 7.0]
    rng = np.random.default_rng(3)

    def _bloc(f_hz=None, gain=5.0):
        x = rng.normal(0.0, 8.0, (besoin, 8))
        if f_hz is not None:
            onde = gain * np.sin(2 * np.pi * f_hz * np.arange(besoin) / FS_UNICORN)
            for c in (4, 5, 6, 7):
                x[:, c] += onde
        return x

    with tempfile.TemporaryDirectory(prefix="ssvep_guide_smoke_") as dossier:
        chemin = os.path.join(dossier, "ssvep_run_20260101-000000.npz")
        etiquettes = [noms[i % 3] for i in range(24)]
        np.savez_compressed(
            chemin,
            trials=np.asarray([_bloc(freqs[noms.index(n)]) for n in etiquettes]),
            labels=np.asarray(etiquettes),
            sigmas=np.zeros(24),
            baseline=np.asarray([_bloc() for _ in range(30)]),
            baseline_sigmas=np.zeros(30),
            names=np.asarray(noms), freqs=np.asarray(freqs),
            fs=FS_UNICORN, refresh=60.0, window_s=1.5)
        chk(analyze(chemin, permutations=200), "un run archivé se rejoue de bout en bout")

        # Un run pris sous d'AUTRES constantes est REFUSÉ, pas rejoué à 0 %.
        court = os.path.join(dossier, "ssvep_run_19990101-000000.npz")
        np.savez_compressed(
            court,
            trials=np.asarray([_bloc()[: besoin - 10] for _ in etiquettes]),
            labels=np.asarray(etiquettes), sigmas=np.zeros(24),
            baseline=np.asarray([_bloc() for _ in range(30)]),
            baseline_sigmas=np.zeros(30),
            names=np.asarray(noms), freqs=np.asarray(freqs),
            fs=FS_UNICORN, refresh=60.0, window_s=1.5)
        chk(not analyze(court, permutations=10),
            "…et un run pris sous d'autres constantes de fenêtre est REFUSÉ, pas rejoué à 0 % — "
            "un taux nul se lirait comme une panne de casque, jamais comme un désaccord de "
            "réglages")

    chk(analyze("chemin/qui/nexiste/pas.npz") is False,
        "un fichier absent est dit, pas planté")
    chk(empreinte_dossier(DATA_DIR) == empreinte_avant,
        "et tout ce test n'a rien écrit dans `data/`")

    print(f"[guidé] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Rejoue un run guidé SSVEP archivé (banc d'essai, sans casque ni écran).")
    p.add_argument("--file", default=None, help="run précis à rejouer (npz)")
    p.add_argument("--permutations", type=int, default=10000, help="tirages du test de permutation")
    p.add_argument("--seed", type=int, default=0, help="graine du test de permutation")
    p.add_argument("--smoke", action="store_true", help="autotest sur un run FABRIQUÉ")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    a = _parse_args(sys.argv[1:])
    if a.smoke:
        sys.exit(0 if _smoke() else 1)
    sys.exit(0 if analyze(a.file, permutations=a.permutations, seed=a.seed) else 1)
