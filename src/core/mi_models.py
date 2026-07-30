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
    # Un chemin vide n'est pas un incident : c'est l'état d'un formulaire dont la liste de
    # modèles est vide (dépôt fraîchement cloné, aucune calibration faite). La docstring promet
    # de ne jamais lever ; `os.path.isfile(None)` levait. Le refus doit dire quoi faire.
    if not chemin:
        return None, ("aucun modèle désigné — lance une calibration depuis la console pour en "
                      "produire un")
    if not _os.path.isfile(chemin):
        return None, f"modèle introuvable : {chemin}"
    try:
        import joblib
        modele = joblib.load(chemin)
    except Exception as e:      # noqa: BLE001 - pickle casse de mille façons, toutes équivalentes ici
        return None, f"modèle illisible ({type(e).__name__}) : {_os.path.basename(chemin)}"
    if not hasattr(modele, "labels") or not hasattr(modele, "predict_proba"):
        return None, f"ce n'est pas un modèle MI : {_os.path.basename(chemin)}"
    # Un pickle porte le CHEMIN DE MODULE de sa classe au moment de la sauvegarde. Un modèle
    # hérité (d'avant le déménagement du décodeur dans core/) porte "mi_decoder" (racine) — et
    # RESSUSCITE selon la commande de lancement : sous `python src/core/server.py`, le dossier
    # du script rejoint sys.path et rend "mi_decoder" importable comme module de PREMIER
    # NIVEAU, donc ce vieux pickle se CHARGE sans lever ; sous la console ou l'appli pygame, ce
    # chemin n'existe pas et le même fichier est refusé plus haut (ModuleNotFoundError).
    # Vérifié empiriquement le 2026-07-30 : les quatre `.joblib` de `data/` portent bien
    # "mi_decoder" sous ce sys.path-là. Cette divergence selon la commande de lancement, pour
    # un modèle abandonné par décision de conception (spec §3), est exactement le « pire des
    # deux mondes » que ce module existe pour éliminer : décoder avec les probabilités de
    # quelqu'un d'autre, en silence.
    module = type(modele).__module__
    if module != "core.mi_decoder":
        return None, (f"modèle hérité (module {module!r}, attendu 'core.mi_decoder'), "
                      f"abandonné délibérément — refais une calibration : "
                      f"{_os.path.basename(chemin)}")
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


class _ModeleEtranger:
    """Même interface qu'un `MIModel` (`labels` + `predict_proba`), mais TOUJOURS d'un module
    différent de `core.mi_decoder` — sert `_selftest` à vérifier le refus d'un modèle hérité
    sans dépendre du répertoire de lancement pour le reproduire. Définie ICI, au niveau du
    module, et pas dans `_selftest` : `pickle`/`joblib` ne sait pas sérialiser une classe
    locale à une fonction (elle n'est pas retrouvable par son nom qualifié au chargement).
    """

    labels = ["GAUCHE", "DROITE", "REPOS"]

    def predict_proba(self, window):
        return {c: 1.0 / len(self.labels) for c in self.labels}


def _selftest():
    """Sur un dossier temporaire : un modèle valide, un fichier corrompu, un dossier vide."""
    import shutil
    import tempfile

    import joblib
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

        # `charger` promet dans sa docstring de ne JAMAIS lever. Elle levait pourtant sur None,
        # et la moitié B l'appelle avec ce que rend un formulaire — donc potentiellement rien du
        # tout, quand aucun modèle n'existe encore. Une exception ici remonterait jusqu'au fil Qt
        # et arrêterait toute la console.
        for entree in (None, "", 0):
            _m, raison = charger(entree)
            chk(_m is None and raison and "aucun modèle" in raison,
                f"charger({entree!r}) rend une raison au lieu de lever ({raison})")

        # Un modèle dont la classe vient d'un AUTRE module que core.mi_decoder : c'est
        # exactement l'état d'un modèle hérité une fois qu'un sys.path particulier (celui de
        # `python src/core/server.py`, entre autres) le rend importable malgré tout — un
        # défaut que « ça charge sans lever » ne peut PAS voir, puisque ce modèle-là charge
        # très bien et porte labels/predict_proba comme un vrai MIModel.
        etranger = _os.path.join(dossier, "mi_model_etranger.joblib")
        joblib.dump(_ModeleEtranger(), etranger)
        _m, raison = charger(etranger)
        chk(_m is None and "hérité" in (raison or "") and "core.mi_decoder" in (raison or ""),
            f"un modèle dont la classe vient d'ailleurs est refusé, même avec labels et "
            f"predict_proba ({raison})")
        chk(etranger not in modeles_disponibles(dossier),
            "et il n'apparaît donc pas non plus dans la liste")

        d = decrire(bon)
        chk(d["nom"] == "mi_model.joblib", f"la description porte le nom du fichier ({d['nom']})")
        chk(list(d["classes"]) == list(MI_LABELS), f"et les classes du modèle ({d['classes']})")
        chk(isinstance(d["cv_naive"], float) and 0.0 <= d["cv_naive"] <= 1.0,
            f"la CV du contrat d'entraînement est une proportion ({d['cv_naive']})")
        chk(d["cv_groupee"] is None,
            "la CV honnête est absente d'un modèle entraîné avant la moitié B — dit, pas inventé")
        chk(d["date"], f"et une date lisible ({d['date']})")

        # Le plus récent d'abord : c'est ce qui rend le défaut du réglage « le dernier entraîné ».
        # On renomme ainsi pour que le tri alphabétique et chronologique divergent : si on oublie
        # key=_os.path.getmtime, le tri alphabétique réversé donnerait ["mi_model_z", "mi_model_a"],
        # OPPOSÉ au tri par date qu'on attend. Le test ne peut donc passer que si on trie sur mtime.
        ancien = _os.path.join(dossier, "mi_model_z.joblib")
        recent = _os.path.join(dossier, "mi_model_a.joblib")
        _os.rename(bon, ancien)
        modele.save(recent)
        _os.utime(ancien, (1_600_000_000, 1_600_000_000))
        chk(modeles_disponibles(dossier)[0] == recent,
            f"le plus récent vient en tête ({modeles_disponibles(dossier)})")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[mi-models] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
