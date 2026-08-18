"""Les modèles P300 sur le disque : lesquels existent, lequel se charge vraiment.

Jumeau de `mi_models.py`, et pour la même raison : un modèle est propre à UNE personne, et le
mode doit pouvoir dire « aucun choix disponible » plutôt que démarrer muet.

⚠️ **Les modèles antérieurs au 2026-08-17 sont refusés, et c'est une décision.** Ils ont été
enregistrés quand le décodeur vivait dans `src/research/`, donc leur pickle référence le module
NU `p300_decoder`, qui n'existe plus sous ce nom. On ne fabrique PAS de passerelle : les époques
de calibration ayant survécu (`data/p300_calib_*.npz`), un modèle se ré-entraîne depuis le disque
en quelques secondes. C'est ce qui manquait au MI, dont les époques avaient été écrasées — et ce
qui a coûté ses 4 modèles.

Autotest :
    python src/core/p300_models.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from core.config import DATA_DIR, use_utf8_console  # noqa: E402


import glob as _glob  # noqa: E402
import time as _time  # noqa: E402

MOTIF = "p300_model*.joblib"   # tous les modèles P300 ; le ré-entraînement en écrit d'horodatés


def charger(chemin):
    """(modèle, None) si le modèle se charge, (None, raison) sinon. Ne lève jamais.

    La `raison` est destinée à un étudiant : elle dit quoi FAIRE, pas seulement ce qui a raté.
    """
    # Un chemin vide n'est pas un incident : c'est l'état d'un formulaire dont la liste de
    # modèles est vide (dépôt fraîchement cloné, aucune calibration faite). La docstring promet
    # de ne jamais lever ; `os.path.isfile(None)` levait. Le refus doit dire quoi faire.
    if not chemin:
        # ⚠️ « depuis la console » était FAUX : la console n'a pas de page de calibration P300
        # (son stimulus doit être verrouillé à la frame, cf. `Calib(kind="natif")` du mode). Ce
        # texte est celui du `help` du réglage « Modèle entraîné » — le même geste dit du même
        # mot aux deux endroits où un étudiant peut le lire.
        return None, ("aucun modèle désigné — lance `python src/research/app.py`, mode P300, et "
                      "calibre : c'est l'appli pygame qui rend ce stimulus, pas la console")
    if not _os.path.isfile(chemin):
        return None, f"modèle introuvable : {chemin}"
    try:
        import joblib
        modele = joblib.load(chemin)
    except Exception as e:      # noqa: BLE001 - pickle casse de mille façons, toutes équivalentes ici
        return None, f"modèle illisible ({type(e).__name__}) : {_os.path.basename(chemin)}"
    if not hasattr(modele, "select") or not hasattr(modele, "scores"):
        return None, f"ce n'est pas un modèle P300 : {_os.path.basename(chemin)}"
    # Un pickle porte le CHEMIN DE MODULE de sa classe au moment de la sauvegarde. Un modèle
    # hérité (d'avant le déménagement du décodeur dans core/, 2026-08-17) porte "p300_decoder"
    # (module NU) — et RESSUSCITE selon la commande de lancement : sous `python src/core/server.py`,
    # le dossier du script rejoint sys.path et rend "p300_decoder" importable comme module de
    # PREMIER NIVEAU, donc ce vieux pickle se CHARGE sans lever ; sous la console ou l'appli
    # pygame, ce chemin n'existe pas et le même fichier est refusé plus haut (ModuleNotFoundError).
    # Vérifié empiriquement le 2026-08-17 : `data/p300_model.joblib` porte bien "p300_decoder"
    # (module nu) sous ce sys.path-là. Cette divergence selon la commande de lancement, pour un
    # modèle abandonné par décision de conception, est exactement le « pire des deux mondes » que
    # ce module existe pour éliminer : décoder avec les probabilités de quelqu'un d'autre, en
    # silence. Contrairement au MI, les époques de calibration ont survécu (`p300_calib_*.npz`) :
    # on ne garde donc PAS ce modèle « en dépannage », on dit de ré-entraîner.
    module = type(modele).__module__
    if module != "core.p300_decoder":
        return None, (f"modèle hérité (module {module!r}, attendu 'core.p300_decoder'), "
                      f"abandonné délibérément — ré-entraîner depuis les époques de calibration "
                      f"conservées (data/p300_calib_*.npz) : {_os.path.basename(chemin)}")
    return modele, None


def modeles_disponibles(dossier=DATA_DIR):
    """Les chemins des modèles P300 RÉELLEMENT chargeables, du PLUS RÉCENT au plus ancien.

    Rend une **liste**, comme son jumeau `mi_models.modeles_disponibles` : les deux alimentent le
    même `Param(kind="choice", choices_fn=…)`, et deux types différents pour la même fonction
    finissent par produire un `+` ou un `==` qui marche d'un côté et pas de l'autre.

    Le plus récent d'abord, parce que c'est le défaut proposé : après une calibration, c'est
    celui qu'on vient de faire qu'on veut essayer.

    On charge pour lister, au lieu de se fier au nom : un fichier au bon nom mais au mauvais
    format apparaîtrait dans le formulaire de la console et échouerait au démarrage du mode —
    exactement le genre de « ça a l'air bon » que ce produit cherche à supprimer. Les fichiers
    font quelques dizaines de kilo-octets, la liste est construite à l'ouverture du catalogue,
    pas en boucle.
    """
    chemins = sorted(_glob.glob(_os.path.join(dossier, MOTIF)),
                     key=_os.path.getmtime, reverse=True)
    return [c for c in chemins if charger(c)[0] is not None]


def decrire(chemin):
    """Une ligne lisible pour la liste de la console : date, nombre d'époques, AUC honnête.
    Ne lève jamais, exactement comme `charger` — c'est sa fonction sœur, et la console appelle
    les deux depuis le même formulaire.

    `cv_auc` est l'AUC cible/non-cible en validation croisée PAR MANCHE (`GroupKFold`), rendue
    par `P300Model.fit` quand une calibration lui fournit `groups` — c'est la seule mesure
    honnête ici : sans le groupement par manche, des époques d'une MÊME manche (donc d'un même
    P300 sous-jacent) se retrouveraient entre train et test, et gonfleraient le chiffre.
    """
    modele, raison = charger(chemin)
    # ⚠️ `charger` avait été durcie contre le chemin vide (« une exception ici remonterait
    # jusqu'au fil Qt »), mais le durcissement s'était arrêté une fonction trop tôt : ici
    # `os.path.isfile(None)` et `os.path.basename(None)` lèvent tous les deux un TypeError, sur
    # la fonction PUBLIQUE qui remplit la liste de modèles. Le `chemin and` court-circuite aussi
    # l'entier 0, que `os.path.isfile` prendrait pour un descripteur de fichier (stdin).
    horodatage = _os.path.getmtime(chemin) if chemin and _os.path.isfile(chemin) else 0.0
    infos = {
        "chemin": chemin,
        "nom": _os.path.basename(chemin) if chemin else "",
        "date": _time.strftime("%Y-%m-%d %H:%M", _time.localtime(horodatage)) if horodatage else "",
        "cv_auc": None,
        "n_epoques": None,
        "probleme": raison,
    }
    if modele is None:
        return infos
    cv = getattr(modele, "cv_auc_", None)
    infos["cv_auc"] = float(cv) if cv is not None else None
    n = getattr(modele, "n_epoques_", None)
    infos["n_epoques"] = int(n) if n is not None else None
    return infos


class _ModeleEtranger:
    """Même interface qu'un `P300Model` (`select` + `scores`), mais TOUJOURS d'un module
    différent de `core.p300_decoder` — sert `_selftest` à vérifier le refus d'un modèle hérité
    sans dépendre du répertoire de lancement pour le reproduire. Définie ICI, au niveau du
    module, et pas dans `_selftest` : `pickle`/`joblib` ne sait pas sérialiser une classe
    locale à une fonction (elle n'est pas retrouvable par son nom qualifié au chargement).
    """

    def scores(self, epochs):
        return [0.0] * len(epochs)

    def select(self, epochs_by_target, margin=0.0):
        return None, {}


class _ModeleHerite:
    """Le VRAI cas hérité : une classe dont le pickle porte le module NU `p300_decoder`.

    ⚠️ C'est la seule forme qui protège la décision de conception de ce module. `_ModeleEtranger`
    ci-dessus porte `__module__ == "__main__"` (ou `"core.p300_models"` à l'import) — **jamais
    `"p300_decoder"`**. Donc l'assouplissement qu'un contributeur écrira un jour pour « juste
    faire marcher les vieux modèles » — `module.endswith("p300_decoder")`, la petite passerelle
    de compatibilité que ce chantier a explicitement refusé d'écrire — laissait toutes les
    assertions vertes pendant que `data/p300_model.joblib` redevenait acceptable, et que le
    moteur se remettait à décoder avec les probabilités de quelqu'un d'autre.

    `__module__` est posé en dur : c'est ce que `pickle` enregistre. `_selftest` inscrit un
    `types.ModuleType("p300_decoder")` dans `sys.modules` le temps du dump ET du chargement (le
    retirer entre les deux ferait retrouver le VRAI `src/core/p300_decoder.py`, importable au
    premier niveau selon la commande de lancement — la divergence même que `charger` documente).
    """

    __module__ = "p300_decoder"

    def scores(self, epochs):
        return [0.0] * len(epochs)

    def select(self, epochs_by_target, margin=0.0):
        return None, {}


def _selftest():
    """Sur un dossier temporaire : un modèle valide, un fichier corrompu, un dossier vide."""
    import shutil
    import tempfile

    import joblib
    import numpy as np

    from core.p300_decoder import P300Model, synth_p300_epoch

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    dossier = tempfile.mkdtemp(prefix="p300_models_")
    try:
        chk(modeles_disponibles(dossier) == [],
            "un dossier sans modèle rend une liste vide, il ne lève pas")

        # Un petit jeu synthétique, dans la forme d'une vraie calibration (manches cuées, cible
        # rare) : de quoi obtenir une AUC groupée non triviale (>= 10 époques, 2 classes).
        rng = np.random.default_rng(0)
        n_rounds, n_targets, reps = 6, 3, 4
        epochs, y, groups = [], [], []
        for r in range(n_rounds):
            cue = r % n_targets
            for _ in range(reps):
                for tgt in range(n_targets):
                    is_t = (tgt == cue)
                    epochs.append(synth_p300_epoch(is_t, rng=rng))
                    y.append(1 if is_t else 0)
                    groups.append(r)
        modele = P300Model(fs=250.0).fit(np.asarray(epochs), np.asarray(y),
                                         groups=np.asarray(groups))
        bon = _os.path.join(dossier, "p300_model.joblib")
        modele.save(bon)

        chk(modeles_disponibles(dossier) == [bon],
            f"un modèle valide est listé ({modeles_disponibles(dossier)})")

        # Un fichier au bon nom mais illisible : c'est exactement l'état des modèles hérités.
        casse = _os.path.join(dossier, "p300_model_casse.joblib")
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

        # `charger` promet dans sa docstring de ne JAMAIS lever. Elle lèverait pourtant sur None
        # (os.path.isfile(None) lève) — et un formulaire de console peut très bien rendre None ou
        # "" quand aucun modèle n'existe encore. Une exception ici remonterait jusqu'au fil Qt.
        for entree in (None, "", 0):
            _m, raison = charger(entree)
            chk(_m is None and raison and "aucun modèle" in raison,
                f"charger({entree!r}) rend une raison au lieu de lever ({raison})")

        # 1. Un modèle d'un module ÉTRANGER est refusé EN LE NOMMANT, pas par une exception obscure.
        etranger = _os.path.join(dossier, "p300_model_etranger.joblib")
        joblib.dump(_ModeleEtranger(), etranger)
        _m, raison = charger(etranger)
        chk(_m is None and "ré-entraîner" in raison and "calibration" in raison,
            f"un modèle hérité est refusé en disant quoi faire ({raison})")
        chk(etranger not in modeles_disponibles(dossier),
            "et il n'apparaît donc pas non plus dans la liste")

        # 1 bis. Le VRAI cas hérité : le pickle porte le module NU `p300_decoder`.
        #
        # ⚠️ L'assertion ci-dessus ne pouvait PAS attraper l'assouplissement de la règle, parce
        # que `_ModeleEtranger.__module__` vaut "__main__" et jamais "p300_decoder" : la mutation
        # `module.endswith("p300_decoder")` — la passerelle de compatibilité que ce chantier a
        # refusé d'écrire — la laissait verte tout en rendant `data/p300_model.joblib` à nouveau
        # acceptable. Celle-ci rougit dessus, parce que le module refusé est EXACTEMENT celui que
        # la mutation ré-autoriserait.
        #
        # Le faux module reste dans `sys.modules` pendant le dump ET le chargement : l'en
        # retirer entre les deux ferait résoudre `p300_decoder` vers le vrai
        # `src/core/p300_decoder.py` (importable au premier niveau sous `python src/core/…`), et
        # on testerait alors un tout autre refus.
        import types

        herite = _os.path.join(dossier, "p300_model_herite.joblib")
        faux_module = types.ModuleType("p300_decoder")
        faux_module._ModeleHerite = _ModeleHerite
        _sys.modules["p300_decoder"] = faux_module
        try:
            joblib.dump(_ModeleHerite(), herite)
            _m, raison = charger(herite)
            liste_avec_herite = modeles_disponibles(dossier)
        finally:
            _sys.modules.pop("p300_decoder", None)

        # Les quotes autour du nom sont voulues : elles distinguent « module 'p300_decoder' » de
        # « attendu 'core.p300_decoder' », qui contient lui aussi la sous-chaîne p300_decoder.
        chk(_m is None and "'p300_decoder'" in (raison or ""),
            f"un modèle dont le pickle porte le module NU 'p300_decoder' est refusé, et la "
            f"raison NOMME ce module — c'est ce qui interdit la passerelle endswith() ({raison})")
        chk(_m is None and "ré-entraîner" in (raison or ""),
            f"...en disant quoi faire à la place ({raison})")
        chk(herite not in liste_avec_herite,
            f"...et il ne se glisse pas non plus dans la liste ({liste_avec_herite})")

        d = decrire(bon)
        chk(d["nom"] == "p300_model.joblib", f"la description porte le nom du fichier ({d['nom']})")
        chk(isinstance(d["cv_auc"], float) and 0.0 <= d["cv_auc"] <= 1.0,
            f"l'AUC honnête (GroupKFold par manche) est une proportion ({d['cv_auc']})")
        chk(d["n_epoques"] == len(y),
            f"et le nombre d'époques d'entraînement est retenu ({d['n_epoques']})")
        chk(d["date"], f"et une date lisible ({d['date']})")

        # `decrire` est la fonction SŒUR de `charger`, publique, et c'est elle qui remplit la
        # liste de modèles de la console. Elle levait un TypeError sur les mêmes entrées contre
        # lesquelles `charger` avait été durcie (`os.path.isfile(None)`), à un fil Qt de distance.
        for entree in (None, "", 0):
            d_vide = decrire(entree)
            chk(d_vide["probleme"] and d_vide["cv_auc"] is None and d_vide["nom"] == "",
                f"decrire({entree!r}) décrit un problème au lieu de lever ({d_vide['probleme']})")

        # 2. Le tri va du plus récent au plus ancien.
        # On renomme ainsi pour que le tri alphabétique et chronologique divergent : si on oublie
        # key=_os.path.getmtime, le tri alphabétique réversé donnerait ["p300_model_z",
        # "p300_model_a"], OPPOSÉ au tri par date qu'on attend.
        ancien = _os.path.join(dossier, "p300_model_z.joblib")
        recent = _os.path.join(dossier, "p300_model_a.joblib")
        _os.rename(bon, ancien)
        modele.save(recent)
        _os.utime(ancien, (1_600_000_000, 1_600_000_000))
        dispo = modeles_disponibles(dossier)
        chk(dispo == [recent, ancien], f"le plus récent d'abord ({dispo})")

        # 3. Un dossier sans modèle rend une liste vide, sans lever — l'état normal d'un dépôt cloné.
        vide = tempfile.mkdtemp(prefix="p300_models_vide_")
        try:
            chk(modeles_disponibles(vide) == [], "un dossier vide rend [], sans lever")
        finally:
            shutil.rmtree(vide, ignore_errors=True)
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[p300-models] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
