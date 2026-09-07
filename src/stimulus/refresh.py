"""Mesurer le rafraîchissement RÉEL de l'écran, en le chronométrant.

Cette fonction vivait dans `research/ssvep_stimulus.py` et les trois fenêtres l'importaient de là.
Elle a déménagé ici le 2026-09-07 avec elles : la laisser dans `research/` aurait créé l'arête
`stimulus -> research`, celle que la frontière de `server.py --smoke` interdit — la console importe
`stimulus`, donc tout `research` serait entré dans la console par la bande.

⚠️ **Pourquoi mesurer plutôt que croire.** Le rafraîchissement ANNONCÉ n'est pas toujours celui que
l'écran tient. Un `--refresh 60` sur un écran à 59,94 Hz fait dériver la phase du c-VEP d'une frame
toutes les ~17 s, ce qui ne lève aucune exception et fait juste baisser les corrélations. La mesure
est donc le défaut, et l'annonce l'exception.
"""

import os as _os
import sys as _sys
import time as _time

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from core.config import COMMON_REFRESH  # noqa: E402

FOND = (0, 0, 0)   # le fond noir des trois fenêtres — contraste ON/OFF maximal


def measure_refresh(pygame, surface, frames=90):
    """Estime le refresh en chronométrant des flips (vsync). Snappe sur une valeur usuelle.

    `pygame` est passé en PARAMÈTRE, pas importé ici : les trois fenêtres l'importent tardivement,
    pour que leur module s'importe (et que leur `--smoke` tourne) sur une machine où pygame n'est
    pas installé.
    """
    surface.fill(FOND)
    pygame.display.flip()
    pygame.event.pump()
    t0 = _time.perf_counter()
    for _ in range(frames):
        surface.fill(FOND)
        pygame.display.flip()
        pygame.event.pump()
    dt = _time.perf_counter() - t0
    if dt <= 0:
        return 60.0
    fps = frames / dt
    return float(min(COMMON_REFRESH, key=lambda r: abs(r - fps)))
