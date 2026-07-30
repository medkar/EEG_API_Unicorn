"""Les modèles MI présents sur le disque : lesquels existent, lesquels se chargent, ce qu'ils valent.

Un modèle MI est un objet `MIModel` picklé par joblib. Le pickle porte le CHEMIN DU MODULE de la
classe : un modèle écrit avant que `mi_decoder` ne rejoigne `core/` ne se recharge donc plus. On
ne tente pas de les rattraper (décision de conception, cf. spec §3) — on les rend invisibles en ne
listant que ce qui se charge vraiment.

Autotest :
    python src/core/mi_models.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from core.config import DATA_DIR, use_utf8_console  # noqa: E402


import glob as _glob  # noqa: E402
import time as _time  # noqa: E402

MOTIF = "mi_model*.joblib"     # tous les modèles MI ; la calibration en écrira d'horodatés


def charger(chemin):
    """(modèle, None) ou (None, raison en clair). Ne lève JAMAIS.

    Un modèle illisible n'est pas un incident exceptionnel ici : c'est l'état normal de tout
    modèle écrit avant que `mi_decoder` ne rejoigne `core/`. Le signaler par une exception
    ferait tomber le moteur pour un fichier qu'on aurait simplement dû ignorer.
    """
    if not _os.path.isfile(chemin):
        return None, f"modèle introuvable : {chemin}"
    try:
        import joblib
        modele = joblib.load(chemin)
    except Exception as e:      # noqa: BLE001 - pickle casse de mille façons, toutes équivalentes ici
        return None, f"modèle illisible ({type(e).__name__}) : {_os.path.basename(chemin)}"
    if not hasattr(modele, "labels") or not hasattr(modele, "predict_proba"):
        return None, f"ce n'est pas un modèle MI : {_os.path.basename(chemin)}"
    return modele, None


def modeles_disponibles(dossier=DATA_DIR):
    """Les modèles MI RÉELLEMENT chargeables, du plus récent au plus ancien.

    On charge pour lister, au lieu de se fier au nom : un fichier au bon nom mais au mauvais
    format apparaîtrait dans le formulaire de la console et échouerait au démarrage du mode —
    exactement le genre de « ça a l'air bon » que ce produit cherche à supprimer. Les fichiers
    font quelques kilo-octets, la liste est construite à l'ouverture du catalogue, pas en boucle.
    """
    chemins = sorted(_glob.glob(_os.path.join(dossier, MOTIF)),
                     key=_os.path.getmtime, reverse=True)
    return [c for c in chemins if charger(c)[0] is not None]


def decrire(chemin):
    """Ce qu'il faut afficher à côté d'un modèle pour le choisir en connaissance de cause.

    `cv_groupee` est la validation croisée HONNÊTE (par essai). Elle vaut None pour tout modèle
    entraîné avant la moitié B : on l'affiche absente plutôt que de recopier `cv_naive`, qui est
    gonflée de 10 à 16 points par la fuite entre fenêtres d'un même essai.
    """
    modele, raison = charger(chemin)
    horodatage = _os.path.getmtime(chemin) if _os.path.isfile(chemin) else 0.0
    infos = {
        "chemin": chemin,
        "nom": _os.path.basename(chemin),
        "date": _time.strftime("%Y-%m-%d %H:%M", _time.localtime(horodatage)) if horodatage else "",
        "classes": (),
        "cv_naive": None,
        "cv_groupee": None,
        "n_essais": None,
        "probleme": raison,
    }
    if modele is None:
        return infos
    infos["classes"] = tuple(modele.labels)
    cv = getattr(modele, "cv_", None)
    infos["cv_naive"] = float(cv) if cv is not None else None
    groupee = getattr(modele, "cv_groupee_", None)
    infos["cv_groupee"] = float(groupee) if groupee is not None else None
    essais = getattr(modele, "n_essais_", None)
    infos["n_essais"] = int(essais) if essais is not None else None
    return infos


def _selftest():
    """Sur un dossier temporaire : un modèle valide, un fichier corrompu, un dossier vide."""
    import shutil
    import tempfile

    import numpy as np

    from core.mi_decoder import MI_LABELS, MIModel, synth_mi_trial

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    dossier = tempfile.mkdtemp(prefix="mi_models_")
    try:
        chk(modeles_disponibles(dossier) == [],
            "un dossier sans modèle rend une liste vide, il ne lève pas")

        rng = np.random.default_rng(0)
        epochs, y = [], []
        for label in MI_LABELS:
            for _ in range(6):
                epochs.append(synth_mi_trial(label, rng=rng))
                y.append(label)
        modele = MIModel(fs=250.0).fit(np.asarray(epochs), np.asarray(y))
        bon = _os.path.join(dossier, "mi_model.joblib")
        modele.save(bon)

        chk(modeles_disponibles(dossier) == [bon],
            f"un modèle valide est listé ({modeles_disponibles(dossier)})")

        # Un fichier au bon nom mais illisible : c'est exactement l'état des modèles hérités.
        casse = _os.path.join(dossier, "mi_model_casse.joblib")
        with open(casse, "wb") as f:
            f.write(b"ceci n'est pas un pickle")
        listes = modeles_disponibles(dossier)
        chk(casse not in listes,
            f"un modèle illisible n'apparaît PAS dans la liste ({listes})")

        _m, raison = charger(casse)
        chk(_m is None and raison,
            f"et le charger rend une raison au lieu de lever ({raison})")

        _m, raison = charger(_os.path.join(dossier, "absent.joblib"))
        chk(_m is None and "introuvable" in (raison or ""),
            f"un chemin inexistant est signalé comme tel ({raison})")

        d = decrire(bon)
        chk(d["nom"] == "mi_model.joblib", f"la description porte le nom du fichier ({d['nom']})")
        chk(list(d["classes"]) == list(MI_LABELS), f"et les classes du modèle ({d['classes']})")
        chk(isinstance(d["cv_naive"], float) and 0.0 <= d["cv_naive"] <= 1.0,
            f"la CV du contrat d'entraînement est une proportion ({d['cv_naive']})")
        chk(d["cv_groupee"] is None,
            "la CV honnête est absente d'un modèle entraîné avant la moitié B — dit, pas inventé")
        chk(d["date"], f"et une date lisible ({d['date']})")

        # Le plus récent d'abord : c'est ce qui rend le défaut du réglage « le dernier entraîné ».
        recent = _os.path.join(dossier, "mi_model_2.joblib")
        modele.save(recent)
        _os.utime(bon, (1_600_000_000, 1_600_000_000))
        chk(modeles_disponibles(dossier)[0] == recent,
            f"le plus récent vient en tête ({modeles_disponibles(dossier)})")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[mi-models] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
