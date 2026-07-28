"""Mode neuro-monitoring : charge / somnolence / engagement. BCI **passive**.

Passif = l'utilisateur ne commande rien, on observe un état. Il n'y a donc ni cible, ni bonne
réponse, et un client ne doit PAS traiter ces valeurs comme une sélection.

⚠️ L'échelle est un z contre le repos du jour de CET utilisateur. `+1` veut dire « au-dessus de
mon propre repos », pas « chargé ». Les trois indices dérivent du même calcul spectral et restent
corrélés. À lire en TENDANCE.
"""

import os as _os
import sys as _sys
import time as _time

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (NEURO_BASELINE_S, NEURO_REBASELINE_S, NEURO_SMOOTH,  # noqa: E402
                         NEURO_WARMUP_S, NEURO_UPDATE_HZ, NEURO_WINDOW_S, json_float, use_utf8_console)
from core.lsl_io import DecodedNeuroPublisher, stream_name  # noqa: E402
from core.modes.contract import ModeSpec, Param, Rest, validate  # noqa: E402
from core.modes.runtime import ModeRuntime  # noqa: E402
from core.neuro_monitor import NeuroDecoder  # noqa: E402


class NeuroRuntime(ModeRuntime):
    """Trois indices d'état mental, en z contre le repos du jour. Aucun stimulus, aucune commande.

    C'est le mode le moins exigeant côté client — rien à afficher, rien à synchroniser, aucun
    modèle à entraîner. Il ne demande qu'une chose, mais elle est impérative : un REPOS en début
    de mode, parce que les indices sont des ratios spectraux individuels et dérivants, qui ne
    veulent rien dire sans un zéro personnel.
    """

    def __init__(self, spec, params, engine):
        super().__init__(spec, params, engine)
        self._out = None
        self.decoder = None
        self._samples = []
        self._state = None
        self._warned = False
        self._last_log = 0.0
        self._new_decoder()

    def _new_decoder(self):
        self.decoder = NeuroDecoder(self.engine.acq.fs,
                                    rebaseline_s=self.params["rebaseline_s"],
                                    smoothing=self.params["smoothing"])

    def _open(self):
        self._out = DecodedNeuroPublisher(instance=self.engine.instance,
                                          smoothing=self.params["smoothing"],
                                          rebaseline_s=self.params["rebaseline_s"])

    def _close(self):
        self._out = None

    def _reset_rest(self):
        # Un NeuroDecoder neuf : ses échelles (médiane/MAD des indices, σ et EMG de référence)
        # sont TOUTES issues du repos. En garder une partie mélangerait deux états du casque,
        # ce qui est précisément ce qu'un « refaire le repos » corrige.
        self._samples = []
        self._state = None
        self._warned = False
        self._new_decoder()

    def period_s(self):
        return 1.0 / NEURO_UPDATE_HZ

    def output(self):
        return self._state

    def _window(self, engine):
        """Fenêtre BRUTE : le passe-bande d'acquisition couperait le bas du θ. Le décodeur
        applique lui-même son propre passe-haut avant la PSD."""
        n = int(NEURO_WINDOW_S * engine.acq.fs)
        recent = engine.recent
        return None if recent is None or len(recent) < n else recent[-n:]

    def _rest_step(self, engine, now):
        window = self._window(engine)
        if window is None:
            return False
        sample = self.decoder.sample(window)
        if sample is None:
            return False

        self._samples.append(sample)
        if now < self._rest_until:
            return False

        if not self.decoder.fit_baseline(self._samples):
            if not self._warned:
                self._warned = True
                print(f"[neuro] repos prolongé : {len(self._samples)} fenêtres, "
                      "pas encore de quoi caler les échelles")
            return False

        centres = "  ".join(f"{k}: repos≈{self.decoder.norm.center(k):.3f}"
                            for k in self.decoder.norm.mu)
        print(f"[neuro] échelles calées ({len(self._samples)} fenêtres) — {centres}")
        print("[neuro] z contre CE repos — ni comparable entre personnes, ni absolu")
        print(f"[neuro] publication sur {stream_name('decoded_neuro')} "
              "(z contre CE repos — ni comparable entre personnes, ni absolu)")
        self.rest_report = {
            "kind": "neuro",
            "windows": len(self._samples),
            "targets": [{"index": k, "rest_center": json_float(self.decoder.norm.center(k), 4)}
                        for k in self.decoder.norm.mu],
        }
        return True

    def _run_step(self, engine, lsl_ts):
        window = self._window(engine)
        if window is None:
            return
        sample = self.decoder.sample(window)
        if sample is None:
            return

        out = self.decoder.step(sample)
        if self._out is not None:
            self._out.push(out["z"], out["artifact"], lsl_ts)
        self._state = {
            "z": {k: json_float(v, 2) for k, v in out["z"].items()},
            "raw": {k: json_float(v, 4) for k, v in (out["raw"] or {}).items()},
            "artifact": bool(out["artifact"]),
            "reason": out["reason"],
            "artifacts": self.decoder.artifacts,
        }
        now = _time.perf_counter()
        if now - self._last_log >= 2.0:
            self._last_log = now
            print("[neuro] z " + "  ".join(f"{k}={v:+.2f}" for k, v in out["z"].items())
                  + f"  artefacts={self.decoder.artifacts}"
                  + (f"  ({out['reason']})" if out["artifact"] else ""))


SPEC = ModeSpec(
    id="neuro",
    label="Neuro",
    family="passif",
    summary="Charge mentale, somnolence et engagement, en écart au repos du jour.",
    status="moteur",
    params=(
        Param(
            key="smoothing", label="Lissage", kind="float",
            default=NEURO_SMOOTH, min=0.0, max=0.99,
            help="Moyenne glissante (EMA) sur les z. 0 = brut et très nerveux, 0,95 = très lisse "
                 "et lent à réagir. Ces indices sont bruités : le défaut lisse beaucoup.",
        ),
        Param(
            key="rebaseline_s", label="Re-calage du repos", kind="float", unit="s",
            default=NEURO_REBASELINE_S, min=0.0, max=1800.0,
            help="Constante de temps du re-calage LENT du zéro, contre la dérive des électrodes "
                 "sèches sur plusieurs minutes. 0 = zéro figé. Trop court, ça effacerait les "
                 "états mentaux eux-mêmes, qui sont plus rapides que la dérive.",
        ),
    ),
    rest=Rest(
        warmup_s=NEURO_WARMUP_S,
        duration_s=NEURO_BASELINE_S,
        # Plus long que le SSVEP : les échelles sont calées sur une MÉDIANE et une MAD, qui
        # demandent plus de fenêtres qu'une moyenne.
        instruction="Repos : regarde l'écran, immobile et détendu — on cale TON zéro du jour.",
    ),
    calibration=None,
    stream="decoded_neuro",
    channels=tuple(DecodedNeuroPublisher.KEYS) + ("artifact",),
    runtime_cls=NeuroRuntime,
)


def _selftest():
    """Chauffe, repos, publication — sur du bruit fabriqué, avec un faux moteur.

    Le CONTENU n'a aucun sens sur du bruit (il n'y a ni charge mentale ni somnolence dans du
    bruit blanc) : on vérifie le câblage, les phases, et que les z publiés sont FINIS — un NaN
    passerait inaperçu jusque chez le client.
    """
    import math

    import numpy as np

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _FauxPublieur:
        def __init__(self):
            self.lignes = []

        def push(self, z, artifact=False, lsl_ts=None):
            self.lignes.append((dict(z), bool(artifact)))

    class _FauxMoteur:
        instance = "selftest"

        class acq:
            fs = 250

        recent = None

    rng = np.random.default_rng(0)
    moteur = _FauxMoteur()
    moteur.recent = rng.normal(0.0, 10.0, (int(4.0 * 250), 8))

    values, reason = validate(SPEC, {})
    chk(values is not None, f"les réglages par défaut du neuro sont valides ({reason})")
    chk(values["smoothing"] == NEURO_SMOOTH, f"lissage par défaut {values['smoothing']}")

    rt = NeuroRuntime(SPEC, values, moteur)
    rt._out = _FauxPublieur()
    rt._opened = True
    rt.begin_rest(now=0.0, warmup_s=0.0, duration_s=1.0)

    now = 0.0
    for _ in range(60):
        now += 0.2
        moteur.recent = rng.normal(0.0, 10.0, (int(4.0 * 250), 8))
        rt.tick(moteur, lsl_ts=now, now=now)
        if rt.phase == "running":
            break
    chk(rt.phase == "running", f"les échelles finissent par se caler (phase={rt.phase})")
    chk(rt.rest_report and rt.rest_report["kind"] == "neuro",
        f"le repos rend un compte-rendu ({rt.rest_report})")

    for _ in range(5):
        now += 0.2
        moteur.recent = rng.normal(0.0, 10.0, (int(4.0 * 250), 8))
        rt.tick(moteur, lsl_ts=now, now=now)
    chk(len(rt._out.lignes) >= 3, f"{len(rt._out.lignes)} publications après le repos")

    z, _artefact = rt._out.lignes[-1]
    chk(set(z) == set(DecodedNeuroPublisher.KEYS), f"les trois indices attendus ({sorted(z)})")
    chk(all(math.isfinite(v) for v in z.values()), f"tous les z sont finis ({z})")

    sortie = rt.output()
    chk(sortie and set(sortie["z"]) == set(DecodedNeuroPublisher.KEYS),
        "la sortie pour l'affichage porte les trois indices")
    chk(all(v is None or math.isfinite(v) for v in sortie["z"].values())
        and all(v is None or math.isfinite(v) for v in sortie["raw"].values()),
        f"la sortie pour l'affichage ne contient ni NaN ni infini ({sortie['z']})")

    print(f"[neuro] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
