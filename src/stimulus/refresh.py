"""Mesurer le rafraîchissement RÉEL de l'écran, en le chronométrant.

Elle vit dans `stimulus/` et non dans `research/` : sinon les fenêtres importeraient `research`
(arête `stimulus -> research` interdite par la frontière de `server.py --smoke`), et comme la
console importe `stimulus`, tout `research` entrerait dans la console par la bande.

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


def frequence_mesuree(pygame, surface, images=120, horloge=_time.perf_counter, chauffe_s=0.5):
    """Le rafraîchissement RÉEL de l'écran, en Hz, sans l'arrondir à une valeur usuelle.

    D'abord `chauffe_s` secondes d'images NON comptées : une fenêtre qui vient de s'ouvrir, ou un
    écran qui vient de changer de mode, rend ses premières images à une autre cadence (mesuré sur
    le poste de dev : 61,7 Hz à la première mesure après un passage à 60 Hz, puis 60,0 à chacune
    des suivantes). Ensuite, l'inverse de l'intervalle MÉDIAN entre deux images (vsync) : la
    médiane ignore une image sautée, qui ferait croire à un écran plus lent. Rend 0.0 si rien n'a
    pu être mesuré.

    `horloge` n'existe que pour l'autotest de `stimulus/ecran.py`.
    """
    debut = horloge()
    while True:
        surface.fill(FOND)
        pygame.display.flip()
        pygame.event.pump()
        if horloge() - debut >= chauffe_s:
            break
    intervalles = []
    avant = horloge()
    for _ in range(int(images)):
        surface.fill(FOND)
        pygame.display.flip()
        pygame.event.pump()
        maintenant = horloge()
        intervalles.append(maintenant - avant)
        avant = maintenant
    if not intervalles:
        return 0.0
    intervalles.sort()
    milieu = intervalles[len(intervalles) // 2]
    return 1.0 / milieu if milieu > 0 else 0.0
