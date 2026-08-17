"""Les modes que le MOTEUR ne sait pas faire — décrits quand même.

C'est le point d'honnêteté de l'interface. Sans ces deux entrées, la grille ne montrerait que
ce qui est chargé : un étudiant croirait que le produit ne fait que cinq choses (brut, SSVEP,
neuro, MI, P300), et ne saurait pas qu'un décodeur c-VEP validé existe dans `src/research/app.py`.
Le MI et le P300, eux, ont rejoint le moteur (`core/modes/mi.py`, `core/modes/p300.py`) : ce ne
sont plus des entrées « appli pygame ».

Chacun porte la RAISON de son absence. Le c-VEP ne peut pas se passer d'un stimulus verrouillé à
la frame, que le moteur ne rend pas — aucun lien avec les marqueurs. L'ErrP, lui, a besoin d'un
marqueur entrant (l'instant où le feedback s'affiche) : l'INFRASTRUCTURE existe désormais (le
P300 s'en sert), mais personne n'a encore écrit son mode dans `core/modes/` — un chantier restant,
pas une impossibilité.
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.modes.contract import Calib, ModeSpec  # noqa: E402

_PYGAME = "Lance `python src/research/app.py` — jamais en même temps que le moteur, le casque " \
          "n'accepte qu'une connexion."

CVEP = ModeSpec(
    id="cvep", label="c-VEP", family="actif",
    summary="Cible fixée parmi N, par codes pseudo-aléatoires décalés (le plus rapide).",
    status="appli_pygame",
    unavailable="Demande un stimulus verrouillé à la FRAME : une seule frame sautée décale le "
                "code et détruit la corrélation. " + _PYGAME,
    calibration=Calib(kind="natif",
                      reason="chaque frame doit afficher le bon bit du code"),
)

ERRP = ModeSpec(
    id="errp", label="ErrP", family="passif",
    summary="Détecte que la machine vient de se tromper (potentiel d'erreur).",
    status="appli_pygame",
    unavailable="Demande un MARQUEUR entrant : l'instant exact où le feedback s'affiche. " + _PYGAME,
    calibration=Calib(kind="natif",
                      reason="l'onset du feedback écran doit être horodaté à la frame"),
)
