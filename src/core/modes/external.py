"""Les modes que le MOTEUR ne sait pas faire — décrits quand même.

C'est le point d'honnêteté de l'interface. Sans ces entrées, la grille ne montrerait que ce qui
est chargé : un étudiant croirait que le produit se limite aux modes du moteur, et ne saurait pas
qu'un décodeur c-VEP validé existe dans `src/research/app.py`. Le MI et le P300, eux, ont rejoint
le moteur (`core/modes/mi.py`, `core/modes/p300.py`) : ce ne sont plus des entrées « appli
pygame ». (Aucun compte n'est écrit ici : `registry.MODES` est la seule source, et un chiffre
recopié dans une prose finit toujours par mentir d'un mode.)

Chacun porte la RAISON de son absence — et c'est le champ `unavailable` que l'étudiant lit
réellement : `console/grid.py` le pose sur la tuile grisée, `server.py` le ressort comme motif de
refus de `--mode <id>`. Il doit donc dire la MÊME chose que cette docstring, pas sa version
d'avant.

Le c-VEP ne peut pas se passer d'un stimulus verrouillé à la frame, que le moteur ne rend pas —
aucun lien avec les marqueurs. L'ErrP, lui, a besoin d'un marqueur entrant (l'instant où le
feedback s'affiche) : l'INFRASTRUCTURE existe désormais et le P300 s'en sert (`core/markers.py`,
contrat public dans `docs/markers.md`) ; ce qui manque est le mode lui-même dans `core/modes/` —
un chantier restant, pas une impossibilité.
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
    unavailable="Personne n'a encore écrit son décodeur dans core/modes/. Le marqueur entrant "
                "dont il a besoin (l'instant où le feedback s'affiche) est déjà transporté par le "
                "moteur — c'est ce que le P300 utilise, cf. docs/markers.md — donc c'est du "
                "travail restant, pas un blocage. " + _PYGAME,
    calibration=Calib(kind="natif",
                      reason="l'onset du feedback écran doit être horodaté à la frame"),
)
