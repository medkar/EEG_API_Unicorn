"""Ce que la console sait lancer. Le SEUL endroit du dépôt qui nomme un module de fenêtre.

Deux règles se rencontrent ici, et ce fichier existe pour les satisfaire toutes les deux :

- **`core` ne nomme aucune fenêtre.** Le contrat d'un mode porte une CLÉ (`Calib.stimulus_id`,
  par exemple `"p300"`), jamais un chemin. C'est ce qui garde l'arête `core -> stimulus`
  inexistante — le moteur doit tourner sur une machine sans écran.
- **La console ne tient aucun catalogue recopié.** Elle ne sait pas que le P300 se lance avec
  `p300.py` : elle demande, à ce module, la commande correspondant à la clé que le contrat lui a
  donnée. Un fichier renommé se corrige ICI, à un seul endroit.

Autotest :
    python src/stimulus/registry.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from core.config import use_utf8_console  # noqa: E402

_ICI = _os.path.dirname(_os.path.abspath(__file__))

# clé du contrat -> fichier de ce paquet. Les clés sont celles de `Calib.stimulus_id`.
FENETRES = {
    "p300": "p300.py",
    "errp": "errp.py",
    "cvep": "cvep.py",
}


def commande(stimulus_id, calibrer=False):
    """La ligne de commande complète d'une fenêtre. Lève `KeyError` si la clé est inconnue.

    `-u` n'est pas décoratif : la sortie de la fenêtre doit arriver NON TAMPONNÉE à la console,
    sinon le message d'erreur d'un processus qui vient de mourir reste bloqué dans son tampon —
    c'est-à-dire exactement quand on en a besoin.
    """
    if stimulus_id not in FENETRES:
        raise KeyError(
            f"aucune fenêtre pour « {stimulus_id} » (connues : {', '.join(sorted(FENETRES))})")
    argv = [_sys.executable, "-u", _os.path.join(_ICI, FENETRES[stimulus_id])]
    if calibrer:
        argv.append("--calibrer")
    return argv


def _selftest():
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    manquants = [k for k, f in FENETRES.items() if not _os.path.isfile(_os.path.join(_ICI, f))]
    chk(not manquants,
        f"chaque clé déclarée pointe un fichier qui EXISTE ({manquants or 'aucun manquant'}) — "
        f"sinon le bouton « Calibrer » lancerait un processus qui meurt aussitôt, et le clic "
        f"redeviendrait silencieux")

    argv = commande("p300")
    chk(argv[0] == _sys.executable and argv[1] == "-u" and argv[2].endswith("p300.py"),
        f"la commande passe par l'interpréteur COURANT et -u ({argv[1:]})")
    chk("--calibrer" not in argv, "…sans --calibrer par défaut : le décodage est le cas normal")
    chk(commande("p300", calibrer=True)[-1] == "--calibrer",
        "…et avec, quand on le demande")
    chk(_os.path.isabs(argv[2]),
        "le chemin est ABSOLU : la console ne partage pas forcément le dossier courant de la "
        "fenêtre qu'elle lance")

    try:
        commande("inconnu")
        chk(False, "une clé inconnue doit lever")
    except KeyError as e:
        chk("connues" in str(e), f"…en disant lesquelles sont connues ({e})")

    print(f"[stim-registry] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
