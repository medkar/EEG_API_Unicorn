"""Mode neuro-monitoring : charge / somnolence / engagement. BCI **passive**.

Passif = l'utilisateur ne commande rien, on observe un état. Il n'y a donc ni cible, ni bonne
réponse, et un client ne doit PAS traiter ces valeurs comme une sélection.

⚠️ L'échelle est un z contre le repos du jour de CET utilisateur. `+1` veut dire « au-dessus de
mon propre repos », pas « chargé ». Les trois indices dérivent du même calcul spectral et restent
corrélés. À lire en TENDANCE.
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (NEURO_BASELINE_S, NEURO_REBASELINE_S, NEURO_SMOOTH,  # noqa: E402
                         NEURO_WARMUP_S)
from core.lsl_io import DecodedNeuroPublisher  # noqa: E402
from core.modes.contract import ModeSpec, Param, Rest  # noqa: E402

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
)
