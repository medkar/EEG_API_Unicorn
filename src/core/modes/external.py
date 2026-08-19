"""Les modes que le MOTEUR ne sait pas faire — décrits quand même.

C'est le point d'honnêteté de l'interface. Sans cette entrée, la grille ne montrerait que ce qui
est chargé : un étudiant croirait que le produit se limite aux modes du moteur, et ne saurait pas
qu'un décodeur c-VEP validé existe dans `src/research/app.py`. Le MI, le P300 et l'ErrP, eux, ont
tour à tour rejoint le moteur (`core/modes/mi.py`, `core/modes/p300.py`, `core/modes/errp.py`) :
ce ne sont plus des entrées « appli pygame », et il ne reste donc plus qu'UNE entrée ici. (Aucun
compte n'est écrit en dur : `registry.MODES` est la seule source, et un chiffre recopié dans une
prose finit toujours par mentir d'un mode.)

Elle porte la RAISON de son absence — et c'est le champ `unavailable` que l'étudiant lit
réellement : `console/grid.py` le pose sur la tuile grisée, `server.py` le ressort comme motif de
refus de `--mode <id>`. Il doit donc dire la MÊME chose que cette docstring, pas sa version
d'avant.

Le c-VEP ne peut pas se passer d'un stimulus verrouillé à la frame, que le moteur ne rend pas —
aucun lien avec les marqueurs entrants : c'est ce qui le distingue du P300 et de l'ErrP, tous deux
pilotés par le tuyau de marqueurs d'une application externe (`core/markers.py`).
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
