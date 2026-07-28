"""Mode « brut » : diffuser les 8 voies telles que le casque les rend.

C'est un mode comme un autre, et c'est le changement : on peut donc **arrêter** de diffuser le
brut, ce qui n'était pas possible avant. Les flux `quality` et `status` décrivent la santé du
MOTEUR, pas un mode : eux restent publiés en permanence, hors registre.
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import CH_NAMES, use_utf8_console  # noqa: E402
from core.lsl_io import RawPublisher  # noqa: E402
from core.modes.contract import ModeSpec  # noqa: E402
from core.modes.runtime import ModeRuntime  # noqa: E402


class RawRuntime(ModeRuntime):
    """Publie le bloc d'échantillons que le moteur vient de lire, sans le toucher.

    « Brut » = tel que le casque le rend, SANS filtrage : c'est un choix, pas un oubli. Chaque
    mode a besoin d'une bande différente (le passe-bande SSVEP 5-40 Hz couperait le P300 et le
    bas du thêta) — filtrer ici imposerait à tous les clients le compromis d'un seul mode.

    ⚠️ Arrêter ce mode arrête la PUBLICATION, pas la lecture du casque : `get_new_data()` vide le
    tampon de BrainFlow et alimente le tampon glissant dont tous les autres modes se servent.
    C'est le moteur qui lit, toujours ; ce mode ne fait que diffuser.
    """

    def __init__(self, spec, params, engine):
        super().__init__(spec, params, engine)
        self._out = None

    def _open(self):
        self._out = RawPublisher(ch_names=CH_NAMES, fs=self.engine.acq.fs,
                                 instance=self.engine.instance)

    def _close(self):
        self._out = None

    def period_s(self):
        # Zéro : le brut est servi à CHAQUE tour de boucle. L'échantillonner introduirait des
        # trous dans un flux continu à 250 Hz, ce qu'aucun client ne pardonnerait.
        return 0.0

    def _run_step(self, engine, lsl_ts):
        if engine.new_block is None or self._out is None:
            return
        eeg, stamps = engine.new_block
        engine.samples += self._out.push(eeg, stamps)

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
    runtime_cls=RawRuntime,
)


def _selftest():
    """Le brut publie ce que le moteur vient de lire — et rien du tout s'il est coupé."""
    import numpy as np

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _FauxPublieur:
        def __init__(self):
            self.blocs = []

        def push(self, eeg, lsl_ts):
            self.blocs.append(np.asarray(eeg))
            return len(eeg)

    class _FauxMoteur:
        samples = 0
        new_block = None

    moteur = _FauxMoteur()
    rt = RawRuntime(SPEC, {}, moteur)
    rt._out = _FauxPublieur()      # on court-circuite LSL : ici on teste le CÂBLAGE, pas le réseau
    rt._opened = True

    chk(rt.phase == "running", "le brut n'a pas de repos : il diffuse tout de suite")
    chk(rt.period_s() == 0.0, "et il est servi à chaque tour de boucle, pas échantillonné")

    bloc = np.zeros((25, 8))
    moteur.new_block = (bloc, np.arange(25, dtype=float))
    rt.tick(moteur, lsl_ts=0.0, now=0.0)
    chk(len(rt._out.blocs) == 1 and rt._out.blocs[0].shape == (25, 8),
        f"le bloc du tour est publié tel quel ({len(rt._out.blocs)} bloc)")
    chk(moteur.samples == 25, f"et compté ({moteur.samples} échantillons)")

    # Un tour sans nouvel échantillon (BrainFlow n'a rien rendu) ne doit rien publier.
    moteur.new_block = None
    rt.tick(moteur, lsl_ts=0.0, now=0.0)
    chk(len(rt._out.blocs) == 1, "un tour sans données ne publie rien")

    print(f"[raw] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
