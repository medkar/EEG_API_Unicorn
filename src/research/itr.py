"""ITR — débit d'information (bits/min) : l'échelle commune pour comparer les paradigmes.

Comparer SSVEP, Motor Imagery et c-VEP sur « l'accuracy » est trompeur : 100 % sur 2 classes
vaut moins que 70 % sur 8, et une décision en 1,5 s ne vaut pas une décision en 4 s. L'ITR de
Wolpaw combine les trois dimensions — **nombre de choix, justesse, vitesse** — en un seul chiffre.

    B = log2(N) + P·log2(P) + (1-P)·log2((1-P)/(N-1))     bits par décision
    ITR = B × 60/T                                         bits par minute

C'est la métrique standard de la littérature BCI, ce qui permet aussi de situer ce casque
8 voies sèches face aux systèmes publiés (un bon SSVEP de labo, en gel, monte à 60-150 bits/min ;
les records c-VEP dépassent 200).

Deux usages, dans une démarche d'exploration :
  - `python src/research/itr.py`            compare les 3 modes tels qu'ils sont mesurés aujourd'hui ;
  - `python src/research/itr.py --scale`    montre comment l'ITR évolue avec le NOMBRE DE CIBLES, ce qui
                                   est précisément l'axe où le c-VEP peut battre le SSVEP.

Référence : Wolpaw et al. 2002, "Brain-computer interfaces for communication and control",
Clin. Neurophysiol. 113(6):767-91. https://doi.org/10.1016/S1388-2457(02)00057-3
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import use_utf8_console  # noqa: E402


def bits_per_decision(n_classes, accuracy):
    """Bits transmis par décision (Wolpaw). 0 si on ne fait pas mieux que le hasard."""
    n, p = int(n_classes), float(accuracy)
    if n < 2:
        return 0.0
    p = min(max(p, 1e-9), 1.0 - 1e-9)
    if p <= 1.0 / n:
        return 0.0
    b = math.log2(n) + p * math.log2(p) + (1 - p) * math.log2((1 - p) / (n - 1))
    return max(0.0, b)


def itr(n_classes, accuracy, seconds_per_decision):
    """Débit d'information en bits/minute."""
    if seconds_per_decision <= 0:
        return 0.0
    return bits_per_decision(n_classes, accuracy) * 60.0 / seconds_per_decision


# Mesures réelles sur CE casque (à tenir à jour — c'est le tableau de bord de l'exploration).
# accuracy = taux de bonne décision par fenêtre/essai ; secondes = latence d'une décision.
MEASURED = [
    ("SSVEP (normalisé z)", 3, 0.95, 1.5,
     "3 cibles solides après la mesure du plancher au repos (2026-07-20)"),
    ("SSVEP (seuil ρ brut)", 3, 0.55, 1.5,
     "avant normalisation : GAUCHE quasi muette sur séance dégradée"),
    ("c-VEP 6 cibles, 2 cyc", 6, 0.683, 2.10,
     "126 cycles, protocole ENTRELACÉ — meilleur résultat c-VEP à ce jour"),
    ("c-VEP 6 cibles ordre fixe", 6, 0.427, 1.05,
     "même montage, ordre de présentation FIXE : le confondant coûtait 12 bits/min"),
    ("c-VEP 3 cibles, 2 cyc", 3, 0.60, 2.1,
     "moyenne des 2 calibrations ; IC très larges, 30 cycles = trop peu"),
    ("Motor Imagery (CSP+LDA)", 3, 0.48, 2.0,
     "meilleur run par essai ; hasard 33%"),
]


def _table(rows):
    print(f"{'paradigme':<24} {'N':>2} {'acc':>6} {'T(s)':>5} {'bits/déc':>9} {'bits/min':>9}")
    print("-" * 70)
    for name, n, acc, t, note in rows:
        print(f"{name:<24} {n:>2} {acc*100:5.0f}% {t:5.1f} "
              f"{bits_per_decision(n, acc):9.2f} {itr(n, acc, t):9.1f}   {note}")


def compare():
    print("\n== Débit d'information mesuré sur l'Unicorn Hybrid Black (8 voies sèches) ==\n")
    _table(MEASURED)
    print("\nRepères littérature : SSVEP de labo (électrodes gel, écran dédié) 60-150 bits/min ;")
    print("meilleurs c-VEP publiés > 200 bits/min ; P300 speller classique ~20-25 bits/min.")


def discrimination(n_classes, accuracy):
    """`q` = probabilité que la vraie cible batte UN concurrent donné.

    Modèle : la décision est un argmax, elle est correcte si la vraie cible dépasse ses N-1
    concurrents. En les supposant échangeables et indépendants, acc = q^(N-1), donc
    q = acc^(1/(N-1)). `q` mesure la qualité du signal INDÉPENDAMMENT du nombre de cibles,
    ce qui permet de projeter ce que donnerait un autre N sur le même montage.
    """
    n, p = int(n_classes), float(accuracy)
    return p ** (1.0 / (n - 1)) if n > 1 else 1.0


def project(n_obs, acc_obs, t_cycle, n_range=range(2, 9), cycles=1):
    """Projette l'ITR pour d'autres nombres de cibles, à partir d'une mesure réelle.

    ⚠️⚠️ CE MODÈLE EST TROP PESSIMISTE — ne pas s'en servir pour décider d'un nombre de cibles.
    Il suppose les N-1 concurrents INDÉPENDANTS. En réalité leurs corrélations partagent la même
    fenêtre EEG et le même template, donc leurs bruits sont corrélés et ajouter une cible coûte
    beaucoup moins que q^(N-1) ne le prédit. Vérifié sur données réelles (2026-07-20) : 90 %
    à 2 cibles, l'indépendance prédit 59 % à 6 cibles, on en mesure 70 %. Conséquence : ce modèle
    annonçait un optimum plat vers 4-5 cibles alors que l'ITR croît en réalité jusqu'à 6 au moins.

    ==> La méthode FIABLE est `cvep_analyze.py` §2b : rejouer les MÊMES enregistrements en
    restreignant la décision à un sous-ensemble de lags. Signal, template et fatigue identiques,
    seul le nombre de choix varie — c'est la seule comparaison non confondue.
    Garder `project()` comme borne basse, jamais comme recommandation.
    """
    q = discrimination(n_obs, acc_obs)
    t = t_cycle * cycles
    print(f"\n== Projection depuis une mesure réelle : {n_obs} cibles, {acc_obs*100:.1f}%, "
          f"{t:.2f}s ==")
    print(f"   qualité de discrimination q = {q:.4f} "
          f"(proba de battre UN concurrent donné)\n")
    print(f"   {'cibles':>6} | {'accuracy':>9} | {'bits/déc':>8} | {'bits/min':>8}")
    print("   " + "-" * 42)
    best = (0, 0.0)
    for n in n_range:
        acc = q ** (n - 1)
        val = itr(n, acc, t)
        mark = "  <- mesuré" if n == n_obs else ""
        if val > best[1]:
            best = (n, val)
        print(f"   {n:>6} | {acc*100:8.1f}% | {bits_per_decision(n, acc):8.2f} | {val:8.1f}{mark}")
    print(f"\n   -> optimum de CE MODÈLE : {best[0]} cibles ({best[1]:.1f} bits/min)")
    print("   ⚠️ BORNE BASSE, pas une recommandation : le modèle suppose les concurrents")
    print("      indépendants, ce qui surestime le coût d'une cible supplémentaire. Sur données")
    print("      réelles l'ITR croît plus longtemps que ça ne le prédit. Pour décider d'un")
    print("      nombre de cibles, utiliser `cvep_analyze.py` §2b (comparaison à séance constante).")
    return best


def scaling(accs=(0.95, 0.85, 0.70, 0.60), n_max=8):
    """ITR en fonction du NOMBRE de cibles — l'axe d'exploration le plus intéressant ici.

    Le SSVEP est plafonné par les diviseurs entiers du refresh : à 60 Hz on ne dispose que de
    ~4 fréquences utilisables hors du pic alpha. Le c-VEP, lui, dispose d'autant de lags que
    le code a de bits (63) : c'est le SEUL des trois modes qui puisse monter en nombre de
    commandes. La question expérimentale devient donc « jusqu'à combien de cibles ? », et ce
    tableau dit ce que ça rapporterait si l'accuracy tenait.
    """
    print("\n== ITR (bits/min) en fonction du nombre de cibles, à latence 2.1 s (c-VEP 2 cycles) ==\n")
    print("accuracy | " + " | ".join(f"N={n:>2}" for n in range(2, n_max + 1)))
    print("-" * (11 + 8 * (n_max - 1)))
    for acc in accs:
        cells = " | ".join(f"{itr(n, acc, 2.1):5.1f}" for n in range(2, n_max + 1))
        print(f"  {acc*100:3.0f}%   | {cells}")
    ref = itr(3, 0.95, 1.5)
    print(f"\nRéférence à battre : SSVEP actuel = 3 cibles / 95% / 1.5s = {ref:.1f} bits/min.")
    print("Le c-VEP part avec un handicap de latence (2.1s), donc monter en cibles ne suffit")
    print("pas : à 6 cibles il lui faut encore ~90% d'accuracy pour égaler, et 8 cibles à 85%")
    print(f"({itr(8, 0.85, 2.1):.1f}) pour passer devant. C'est ça, la vraie cible expérimentale.")
    print("Contrainte pratique : la disposition actuelle n'a que 4 directions de flèche ;")
    print("au-delà il faut une autre géométrie (grille ou couronne de cibles).")


def _parse(argv):
    p = argparse.ArgumentParser(description="Débit d'information (ITR) des paradigmes BCI.")
    p.add_argument("--scale", action="store_true", help="ITR vs nombre de cibles (accuracy fixée)")
    p.add_argument("--project", nargs=3, metavar=("N", "ACC", "SEC"), default=None,
                   help="projette l'ITR pour d'autres N depuis une mesure réelle")
    p.add_argument("--point", nargs=3, metavar=("N", "ACC", "SEC"), default=None,
                   help="calculer un point : nb de classes, accuracy 0-1, secondes/décision")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    a = _parse(sys.argv[1:])
    if a.project:
        project(int(a.project[0]), float(a.project[1]), float(a.project[2]))
    elif a.point:
        n, acc, t = int(a.point[0]), float(a.point[1]), float(a.point[2])
        print(f"N={n}  accuracy={acc*100:.0f}%  T={t:.1f}s  ->  "
              f"{bits_per_decision(n, acc):.2f} bits/décision, {itr(n, acc, t):.1f} bits/min")
    elif a.scale:
        scaling()
    else:
        compare()
        scaling()
