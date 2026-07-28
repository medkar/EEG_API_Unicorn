"""Mode « brut » : diffuser les 8 voies telles que le casque les rend.

C'est un mode comme un autre, et c'est le changement : on peut donc **arrêter** de diffuser le
brut, ce qui n'était pas possible avant. Les flux `quality` et `status` décrivent la santé du
MOTEUR, pas un mode : eux restent publiés en permanence, hors registre.
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import CH_NAMES  # noqa: E402
from core.modes.contract import ModeSpec  # noqa: E402

SPEC = ModeSpec(
    id="raw",
    label="Brut",
    family="brut",
    summary="Les 8 voies EEG telles que le casque les rend, en µV à 250 Hz.",
    status="moteur",
    params=(),          # rien à régler : « brut » veut dire brut
    rest=None,          # aucun plancher à mesurer : on ne décide de rien
    calibration=None,
    stream="raw",
    channels=tuple(CH_NAMES),
)
