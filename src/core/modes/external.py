"""Les modes que le MOTEUR ne sait pas faire — décrits quand même.

C'est le point d'honnêteté de l'interface. Sans ces trois entrées, la grille ne montrerait que
ce qui est chargé : un étudiant croirait que le produit ne fait que quatre choses (brut, SSVEP,
neuro, MI), et ne saurait pas qu'un décodeur c-VEP validé existe dans `src/research/app.py`.
Le MI, lui, a rejoint le moteur (`core/modes/mi.py`) : ce n'est plus une entrée « appli pygame ».

Chacun porte la RAISON de son absence, et c'est presque toujours la même famille de raison : le
moteur ne reçoit pas de marqueurs entrants, et ne rend pas de stimulus verrouillé à la frame.
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

P300 = ModeSpec(
    id="p300", label="P300", family="actif",
    summary="Sélection parmi 6 cibles par onde P300 (oddball attentionnel).",
    status="appli_pygame",
    unavailable="Demande des MARQUEURS entrants (l'onset de chaque flash), que le moteur ne "
                "reçoit pas encore. " + _PYGAME,
    calibration=Calib(kind="natif",
                      reason="époques calées sur l'onset exact de chaque flash"),
)

ERRP = ModeSpec(
    id="errp", label="ErrP", family="passif",
    summary="Détecte que la machine vient de se tromper (potentiel d'erreur).",
    status="appli_pygame",
    unavailable="Demande un MARQUEUR entrant : l'instant exact où le feedback s'affiche. " + _PYGAME,
    calibration=Calib(kind="natif",
                      reason="l'onset du feedback écran doit être horodaté à la frame"),
)
