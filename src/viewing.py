"""Géométrie visuelle du stimulus : taille et écartement des cibles en DEGRÉS d'angle.

Pourquoi ça compte : l'amplitude d'une réponse visuelle évoquée croît proportionnellement à la
taille du stimulus **en angle visuel** — pas en pixels. Une même fenêtre vue à 40 cm ou à 80 cm,
ce sont deux expériences différentes. C'est aussi le paramètre le plus mal contrôlé de nos
mesures : l'amplitude filtrée a varié du simple au double entre séances (σ 8 vs 18), et la
distance à l'écran n'a jamais été notée.

Deux contraintes opposées fixent un optimum :
  - PLUS PRÈS -> cibles plus grandes -> réponse plus forte (amplitude ∝ taille angulaire,
    testé de 0,67° à 8,9° ; réduire la distance est un levier reconnu de SNR).
  - PLUS LOIN -> cibles moins écartées ; la performance est meilleure quand l'écartement
    centre-à-centre reste dans ~4-13°, avec un optimum rapporté vers 3,8° de taille et
    4,8° d'écartement.

Sources :
  Towards an Optimization of Stimulus Parameters for SSVEP-based BCI, PLOS One 2014
    https://doi.org/10.1371/journal.pone.0112099
  Influence of Stimuli Spatial Proximity on a SSVEP-Based BCI Performance, IRBM 2022
    https://doi.org/10.1016/j.irbm.2022.04.002

    python src/viewing.py --screen-cm 53 --screen-px 1920 --distance 40 60 80
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import CVEP_N_TARGETS, use_utf8_console  # noqa: E402

# Doivent refléter ui.App.ring_spots / App.arrows.
RING_DIST_RATIO = 0.31
RING_SIZE_RATIO = 0.075

# Plages recommandées par la littérature (voir en-tête).
SIZE_OK = (3.0, 8.9)
SPACING_OK = (4.0, 13.0)


def angle_deg(px, px_per_cm, distance_cm):
    """Angle visuel sous-tendu par `px` pixels, vus à `distance_cm`."""
    cm = px / px_per_cm
    return math.degrees(2 * math.atan((cm / 2) / distance_cm))


def geometry(span_px, n_targets=CVEP_N_TARGETS):
    """(diamètre d'une cible, écart centre-à-centre entre voisines) en PIXELS."""
    r = span_px * RING_SIZE_RATIO
    ring_r = span_px * RING_DIST_RATIO
    spacing = 2 * ring_r * math.sin(math.pi / n_targets)   # corde entre cibles voisines
    return 2 * r, spacing


def report(screen_cm, screen_px, span_px, distances, n_targets=CVEP_N_TARGETS):
    px_per_cm = screen_px / screen_cm
    diam_px, space_px = geometry(span_px, n_targets)
    print(f"\n== Géométrie du stimulus c-VEP ({n_targets} cibles) ==")
    print(f"   écran {screen_cm:.1f} cm pour {screen_px} px  ->  {px_per_cm:.1f} px/cm")
    print(f"   fenêtre span={span_px} px  ->  cible {diam_px:.0f} px, "
          f"écart voisines {space_px:.0f} px\n")
    print(f"   {'distance':>8} | {'taille cible':>12} | {'écart voisines':>14} | verdict")
    print("   " + "-" * 62)
    best = None
    for d in distances:
        size = angle_deg(diam_px, px_per_cm, d)
        space = angle_deg(space_px, px_per_cm, d)
        size_ok = SIZE_OK[0] <= size <= SIZE_OK[1]
        space_ok = SPACING_OK[0] <= space <= SPACING_OK[1]
        if size_ok and space_ok:
            verdict, score = "OK", size          # à contrainte respectée, plus grand = mieux
        elif not size_ok and size < SIZE_OK[0]:
            verdict, score = "cibles TROP PETITES (recule moins / rapproche-toi)", -1
        elif not space_ok and space > SPACING_OK[1]:
            verdict, score = "cibles TROP ÉCARTÉES (éloigne-toi)", -1
        else:
            verdict, score = "hors plage", -1
        if score > 0 and (best is None or score > best[1]):
            best = (d, score)
        print(f"   {d:6.0f} cm | {size:11.1f}° | {space:13.1f}° | {verdict}")
    print(f"\n   plages visées : cible {SIZE_OK[0]}-{SIZE_OK[1]}°, "
          f"écart voisines {SPACING_OK[0]}-{SPACING_OK[1]}°")
    if best:
        print(f"   -> retenir ~{best[0]:.0f} cm : c'est la plus proche qui garde l'écartement")
        print("      dans la plage utile, donc la plus grande réponse sans crosstalk excessif.")
    else:
        print("   -> aucune distance ne satisfait les deux plages : il faut changer la GÉOMÉTRIE")
        print("      (RING_SIZE_RATIO / RING_DIST_RATIO dans ui.py), pas la distance.")
    print("\n   ⚠️ Quelle que soit la distance choisie, la GARDER CONSTANTE entre la calibration")
    print("      et le pilotage, et d'une séance à l'autre : le template encode la réponse à une")
    print("      taille angulaire donnée. Changer de distance invalide partiellement le modèle.")
    return best


def _parse(argv):
    p = argparse.ArgumentParser(description="Angle visuel du stimulus (EEG Waffle).")
    p.add_argument("--screen-cm", type=float, default=53.0,
                   help="largeur PHYSIQUE de l'écran en cm (24 pouces 16:9 ≈ 53)")
    p.add_argument("--screen-px", type=int, default=1920, help="largeur de l'écran en pixels")
    p.add_argument("--span-px", type=int, default=820,
                   help="plus petite dimension de la fenêtre (820 en --windowed, "
                        "hauteur écran en plein écran)")
    p.add_argument("--distance", type=float, nargs="+",
                   default=[30, 40, 50, 60, 70, 80], help="distances œil-écran à évaluer (cm)")
    p.add_argument("--targets", type=int, default=CVEP_N_TARGETS)
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    a = _parse(sys.argv[1:])
    report(a.screen_cm, a.screen_px, a.span_px, a.distance, a.targets)
