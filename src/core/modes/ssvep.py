"""Mode SSVEP : quelle cible clignotante l'utilisateur regarde. BCI **active**.

Le décodage lui-même est dans `core/cca_decoder.py` — une CCA, sans entraînement. Ici on décrit
le MODE : ce qui se règle, ce qui se publie, ce qu'il faut mesurer avant de décider.

⚠️ Le moteur ne rend AUCUN stimulus. C'est l'application cliente qui fait clignoter les cibles ;
elle déclare simplement leurs fréquences ici. Le couplage est lâche — aucune synchronisation à la
frame n'est nécessaire, contrairement au c-VEP.
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (BANDPASS, SSVEP_BASELINE_S, SSVEP_WARMUP_S,  # noqa: E402
                         choose_frequencies)
from core.lsl_io import ssvep_channel_labels  # noqa: E402
from core.modes.contract import ModeSpec, Param, Rest  # noqa: E402

# Le défaut vient de `choose_frequencies`, la MÊME fonction que le stimulus : passer le même
# refresh des deux côtés garantit l'accord sans recopier des décimales à la main.
FREQS_60HZ = tuple(c["actual_hz"] for c in choose_frequencies(60))   # 15 · 20 · 8,571 Hz


def _channels(params):
    return ssvep_channel_labels(params["freqs"])


SPEC = ModeSpec(
    id="ssvep",
    label="SSVEP",
    family="actif",
    summary="Quelle cible clignotante l'utilisateur regarde, ~5 fois par seconde.",
    status="moteur",
    params=(
        Param(
            key="freqs",
            label="Fréquences des cibles",
            kind="float_list",
            unit="Hz",
            default=FREQS_60HZ,
            count=(2, 8),
            constraints=("dans_la_bande", "separables"),
            help="Les fréquences que TON application fait clignoter. Le nombre de cibles est la "
                 "longueur de cette liste. Une fréquence n'est stable que si c'est un diviseur "
                 "entier du refresh de ton écran (à 60 Hz : 30, 20, 15, 12, 10, 8,57…). Évite le "
                 "voisinage de ton pic alpha (~10 Hz) : le fond de corrélation y est élevé au "
                 "repos. Changer cette liste RECRÉE le flux — les clients doivent se réabonner.",
        ),
        # `proposes` est déclaré nulle part dans ce chantier : le nombre de cibles se règle par la
        # LONGUEUR de la liste ci-dessus. La proposition automatique de fréquences est le
        # chantier 2 (spec §3.1) ; le contrat la permet déjà, on ne la livre pas à moitié.
    ),
    rest=Rest(
        warmup_s=SSVEP_WARMUP_S,
        duration_s=SSVEP_BASELINE_S,
        instruction="Ne fixe AUCUNE cible : on mesure le bruit de fond de chaque fréquence.",
    ),
    calibration=None,   # la CCA n'apprend rien ; le repos est un étalonnage, pas un modèle
    stream="decoded_ssvep",
    channels_fn=_channels,
)
