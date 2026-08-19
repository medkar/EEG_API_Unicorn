"""Les modèles ErrP sur le disque : lesquels existent, lequel se charge vraiment.

Jumeau de `p300_models.py`, et pour la même raison : un modèle est propre à UNE personne, et le
mode doit pouvoir dire « aucun choix disponible » plutôt que démarrer muet.

⚠️ **Les modèles antérieurs au 2026-08-18 sont refusés, et c'est une décision.** Ils ont été
enregistrés quand le décodeur vivait dans `src/research/`, donc leur pickle référence le module NU
`errp_decoder`, qui n'existe plus sous ce nom (le décodeur P300 a fait le même trajet la veille, et
l'ErrP le suit aujourd'hui). On ne fabrique PAS de passerelle. C'est la TROISIÈME fois que ce projet
rencontre ce piège précis — la première fois (Motor Imagery), les époques avaient été écrasées, et
ça a coûté 4 modèles.

⚠️ **Et le remède qu'on aimerait donner n'existe pas encore.** Les époques de calibration ont bien
survécu (`data/errp_calib_last.npz`, plus des horodatées), mais **aucun code de ce dépôt ne les
lit** : le ré-entraînement du 2026-08-18 a été fait par un script jetable, non versionné. Prescrire
« ré-entraîne depuis les .npz » enverrait donc l'étudiant vers une porte fermée. Le seul remède
livré aujourd'hui est une nouvelle calibration au casque, et c'est ce que disent les messages de
refus, plus bas. Écrire ce lecteur de `.npz` reste la bonne idée ; elle n'est simplement pas faite.

Autotest :
    python src/core/errp_models.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from core.config import DATA_DIR, use_utf8_console  # noqa: E402


import glob as _glob  # noqa: E402
import time as _time  # noqa: E402

MOTIF = "errp_model*.joblib"   # tous les modèles ErrP ; la calibration en écrit d'HORODATÉS
_MODULE_ATTENDU = "core.errp_decoder"
_NOYAU_ATTENDU = "core.p300_decoder"


def charger(chemin):
    """(modèle, None) si le modèle se charge, (None, raison) sinon. Ne lève jamais.

    La `raison` est destinée à un étudiant : elle dit quoi FAIRE, pas seulement ce qui a raté.
    """
    # Un chemin vide n'est pas un incident : c'est l'état d'un formulaire dont la liste de
    # modèles est vide (dépôt fraîchement cloné, aucune calibration faite). La docstring promet
    # de ne jamais lever ; `os.path.isfile(None)` levait. Le refus doit dire quoi faire.
    if not chemin:
        # ⚠️ la console n'a PAS de page de calibration ErrP (le stimulus — piste + feedback — vit
        # dans l'appli pygame, cf. `errp_calibrate.py`) : ce texte est celui du `help` du réglage
        # « Modèle entraîné » côté console ET celui qu'un étudiant lit ici — le même geste dit du
        # même mot aux deux endroits où il peut le lire.
        return None, ("aucun modèle désigné — lance `python src/research/app.py`, mode ErrP, "
                      "et calibre pour en produire un")
    if not _os.path.isfile(chemin):
        return None, f"modèle introuvable : {chemin}"
    try:
        import joblib
        modele = joblib.load(chemin)
    except Exception as e:      # noqa: BLE001 - pickle casse de mille façons, toutes équivalentes ici
        return None, f"modèle illisible ({type(e).__name__}) : {_os.path.basename(chemin)}"
    if not hasattr(modele, "score") or not hasattr(modele, "is_error"):
        return None, f"ce n'est pas un modèle ErrP : {_os.path.basename(chemin)}"
    # Un pickle porte le CHEMIN DE MODULE de sa classe au moment de la sauvegarde. Un modèle
    # hérité (d'avant le déménagement du décodeur dans core/, 2026-08-18) porte "errp_decoder"
    # (module NU) — et RESSUSCITE selon la commande de lancement, exactement le mécanisme déjà
    # documenté dans `p300_models.charger` (vérifié empiriquement sur ce projet le 2026-08-17) :
    # sous `python src/core/server.py`, le dossier du script rejoint sys.path et rend "errp_decoder"
    # importable comme module de PREMIER NIVEAU, donc ce vieux pickle se CHARGE sans lever ; sous la
    # console ou l'appli pygame, ce chemin n'existe pas et le même fichier est refusé plus haut
    # (ModuleNotFoundError). Cette divergence selon la commande de lancement, pour un modèle
    # abandonné par décision de conception, est exactement le « pire des deux mondes » que ce module
    # existe pour éliminer : décoder avec les probabilités de quelqu'un d'autre, en silence.
    # Contrairement au MI, les époques de calibration ont survécu (`errp_calib_*.npz`) : on ne
    # garde donc PAS ce modèle « en dépannage », on dit de ré-entraîner.
    module = type(modele).__module__
    if module != _MODULE_ATTENDU:
        # ⚠️ Trois corrections de revue tiennent dans cette phrase. (a) Elle NOMME le fichier,
        # comme les trois autres refus de cette fonction et comme les deux jumeaux : deux modèles
        # hérités côte à côte donnaient sinon deux lignes de liste RIGOUREUSEMENT identiques.
        # (b) Elle ne dit plus « illisible » — on n'arrive ici que si `joblib.load` a RÉUSSI
        # (c'est comme ça qu'on connaît son module) ; le mot juste est « abandonné ». (c) Elle
        # prescrit le remède qui EXISTE. « Ré-entraîner depuis data/errp_calib_*.npz » n'était
        # tenable pour personne : aucun code de ce dépôt ne lit ces .npz (le ré-entraînement du
        # 18/08 a été fait par un script jetable, non versionné), et la branche « aucun modèle
        # désigné » 25 lignes plus haut disait déjà, elle, le vrai geste. Deux instructions
        # contradictoires pour la même panne : on garde celle qu'un étudiant peut suivre.
        return None, (f"modèle hérité (module {module!r}, attendu {_MODULE_ATTENDU!r}), abandonné "
                      f"délibérément — recalibre (`python src/research/app.py`, mode ErrP) : "
                      f"{_os.path.basename(chemin)}")
    # `ErrPModel` n'HÉRITE pas de `P300Model`, il le CONTIENT (`self.core`) : un pickle d'ErrP
    # porte donc DEUX chemins de module, et c'est le second qui SCORE (`score` -> `self.core.pipe`).
    # Le contrôle ci-dessus ne regarde que l'extérieur. La passerelle que ce chantier refuse
    # d'écrire finira par être écrite à moitié — un script « de dépannage » qui recharge sous un
    # `sys.modules["errp_decoder"] = core.errp_decoder` puis re-`save()` — et rendra un modèle dont
    # la coquille est neuve et le noyau ressuscité d'un module fantôme. `_desaccord_geometrie`
    # (`core/modes/errp.py`) ne le verrait pas non plus : fs/pre_s/post_s sont posés sur l'objet
    # EXTÉRIEUR. Ce serait le « pire des deux mondes » avec un tour de plus.
    noyau = type(getattr(modele, "core", None)).__module__
    if noyau != _NOYAU_ATTENDU:
        return None, (f"le noyau P300 de ce modèle vient du module {noyau!r} (attendu "
                      f"{_NOYAU_ATTENDU!r}) : sa coquille est neuve mais ce qui CALCULE les scores "
                      f"est hérité — recalibre (`python src/research/app.py`, mode ErrP) : "
                      f"{_os.path.basename(chemin)}")
    # ⚠️ Correction de revue (tâche 3) : `ErrPModel.fit` ne pose `oof_scores_`/`oof_y_` que si la
    # calibration a au moins 10 essais, 2 classes, et une classe minoritaire d'au moins 2 membres
    # (cf. sa garde, `errp_decoder.py`) — en dessous, ces deux attributs restent `None`. Rien
    # ci-dessus ne le voit : `hasattr(modele, "score"/"is_error")` est vrai même pour un modèle
    # jamais entraîné sur assez de données. Sans ce refus, un tel modèle apparaissait normalement
    # dans la liste proposée à l'étudiant, et `core/modes/errp.py` finissait par appeler
    # `pick_threshold(None, None, ...)` — mesuré, pas supposé : lève
    # `ValueError: zero-dimensional arrays cannot be concatenated`, une exception numpy BRUTE,
    # sans aucun rapport avec ce qu'il faut faire.
    if getattr(modele, "oof_scores_", None) is None or getattr(modele, "oof_y_", None) is None:
        # ⚠️ Correction de revue (tranche B) : ce message ÉNUMÉRAIT trois causes — « moins de 10
        # essais, une seule classe, ou une classe à moins de 2 membres » — et concluait
        # « recalibre AVEC PLUS D'ESSAIS ». Or `fit` laisse `oof_scores_` à None dans DEUX
        # situations, et la seconde (les trois nfilter tombés à la validation croisée : voie
        # plate, électrode décollée, dérive de version) n'a rien à voir avec le nombre d'essais.
        # Un étudiant qui venait d'en faire 200 était renvoyé en refaire davantage, pour rien.
        # On ne DEVINE donc plus : `ErrPModel.fit` enregistre ce qu'il a CONSTATÉ dans
        # `echec_oof_`, et on le cite tel quel.
        cause = getattr(modele, "echec_oof_", None) or (
            "cause non enregistrée — modèle produit avant que `fit` ne la note")
        return None, (f"pas de scores hors-pli, donc aucun seuil réglable ({cause}) : recalibre "
                      f"(`python src/research/app.py`, mode ErrP) : {_os.path.basename(chemin)}")
    return modele, None


def modeles_disponibles(dossier=DATA_DIR):
    """Les chemins des modèles ErrP RÉELLEMENT chargeables, du PLUS RÉCENT au plus ancien.

    Rend une **liste**, comme son jumeau `p300_models.modeles_disponibles` (et `mi_models` avant
    lui) : les trois alimentent le même `Param(kind="choice", choices_fn=…)`, et deux types
    différents pour la même fonction finissent par produire un `+` ou un `==` qui marche d'un côté
    et pas de l'autre.

    Le plus récent d'abord, parce que c'est le défaut proposé : après une calibration, c'est
    celui qu'on vient de faire qu'on veut essayer.

    On charge pour lister, au lieu de se fier au nom : un fichier au bon nom mais au mauvais
    format apparaîtrait dans le formulaire de la console et échouerait au démarrage du mode —
    exactement le genre de « ça a l'air bon » que ce produit cherche à supprimer. Les fichiers
    font quelques dizaines de kilo-octets, la liste est construite à l'ouverture du catalogue,
    pas en boucle.
    """
    # ⚠️ `key=_os.path.getmtime` s'évalue sur TOUS les candidats : un fichier qui disparaît (ou
    # qu'un antivirus verrouille) entre le `glob` et la clé faisait sortir un `FileNotFoundError`
    # de cette fonction. `Param.choices_status` (`core/modes/contract.py`) l'attrape, mais le
    # classe « un `choices_fn` qui lève est un DÉFAUT de déclaration » — donc le formulaire de la
    # console annonçait un bug du produit là où il n'y a qu'une course bénigne (catalogue ouvert
    # pendant qu'une calibration écrit son modèle). Un candidat évaporé passe en fin de tri, et
    # `charger` le refuse ensuite proprement (« modèle introuvable »).
    chemins = sorted(_glob.glob(_os.path.join(dossier, MOTIF)),
                     key=lambda c: _os.path.getmtime(c) if _os.path.isfile(c) else 0.0,
                     reverse=True)
    return [c for c in chemins if charger(c)[0] is not None]


def decrire(chemin):
    """Une ligne lisible pour la liste de la console : date, AUC honnête, nombre d'époques.
    Ne lève jamais, exactement comme `charger`, sa fonction sœur.

    ⚠️ AUCUN appelant en production aujourd'hui (vérifié sur tout `src/` : seul `_selftest`
    l'appelle) — la console n'importe pas encore ce module. Cette forme existe pour la PARITÉ
    avec `p300_models.decrire` et `mi_models.decrire` (celui-là réellement appelé, par
    `core/modes/mi_calib.py`), que la console lira quand elle affichera les listes de modèles :
    les trois doivent rendre les mêmes clés. Dit autrement pour le prochain lecteur : changer la
    forme de ce dict ne casse aujourd'hui aucun affichage — mais casserait les trois d'un coup
    le jour où il y en aura un.

    `cv_auc` est l'AUC erreur/correct en validation croisée PAR BLOC (`GroupKFold`), rendue par
    `ErrPModel.fit` quand une calibration lui fournit `groups` — c'est la seule mesure honnête ici :
    sans le groupement par bloc, des époques d'un MÊME bloc (donc d'un même feedback sous-jacent)
    se retrouveraient entre train et test, et gonfleraient le chiffre.
    """
    modele, raison = charger(chemin)
    # ⚠️ `charger` avait été durcie contre le chemin vide (« une exception ici remonterait
    # jusqu'au fil Qt »), mais le durcissement s'était arrêté une fonction trop tôt côté P300 : ici
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
    # `ErrPModel.fit` pose `n_epoques_` comme `P300Model.fit`, en une ligne (correction de revue :
    # la colonne « époques » était vide pour l'ErrP et remplie pour le P300, sans que rien ne dise
    # pourquoi, et le moteur avait dû contourner par `len(oof_y_)` — un second chiffre calculé
    # autrement pour la même quantité). Les modèles antérieurs à cette ligne n'ont pas l'attribut :
    # `getattr` rend None, et la clé reste None plutôt que de faire lever la liste.
    n = getattr(modele, "n_epoques_", None)
    infos["n_epoques"] = int(n) if n is not None else None
    return infos


class _ModeleEtranger:
    """Même interface qu'un `ErrPModel` (`score` + `is_error`), mais TOUJOURS d'un module
    différent de `core.errp_decoder` — sert `_selftest` à vérifier le refus d'un modèle hérité
    sans dépendre du répertoire de lancement pour le reproduire. Définie ICI, au niveau du
    module, et pas dans `_selftest` : `pickle`/`joblib` ne sait pas sérialiser une classe
    locale à une fonction (elle n'est pas retrouvable par son nom qualifié au chargement).
    """

    threshold_ = 0.0

    def score(self, epochs):
        return [0.0] * len(epochs)

    def is_error(self, epoch):
        return False


class _ModeleHerite:
    """Le VRAI cas hérité : une classe dont le pickle porte le module NU `errp_decoder`.

    ⚠️ C'est la seule forme qui protège la décision de conception de ce module. `_ModeleEtranger`
    ci-dessus porte `__module__ == "__main__"` (ou `"core.errp_models"` à l'import) — **jamais
    `"errp_decoder"`**. Donc l'assouplissement qu'un contributeur écrira un jour pour « juste faire
    marcher les vieux modèles » — `module.endswith("errp_decoder")`, la petite passerelle de
    compatibilité que ce chantier a explicitement refusé d'écrire — laissait toutes les assertions
    vertes pendant que `data/errp_model.joblib` redevenait acceptable, et que le moteur se
    remettait à décoder avec les probabilités de quelqu'un d'autre.

    `__module__` est posé en dur : c'est ce que `pickle` enregistre. **Elle doit vivre au niveau du
    MODULE, et pas être imbriquée dans `_selftest`** — contrairement à ce qu'un premier jet peut
    suggérer : une classe locale à une fonction a un `__qualname__` du type
    `_selftest.<locals>._ModeleHerite`, et le composant `<locals>` fait lever un
    `pickle.PicklingError` DÈS LE DUMP (« Can't pickle ... : it's not found as
    errp_decoder._selftest.<locals>._ModeleHerite »), avant même de consulter `sys.modules` —
    vérifié en pratique en écrivant la version imbriquée en premier. `_selftest` inscrit un
    `types.ModuleType("errp_decoder")` dans `sys.modules` le temps du dump ET du chargement (le
    retirer entre les deux ferait retrouver le VRAI `src/core/errp_decoder.py`, importable au
    premier niveau selon la commande de lancement — la divergence même que `charger` documente).
    """

    __module__ = "errp_decoder"
    threshold_ = 0.0

    def score(self, epochs):
        return [0.0] * len(epochs)

    def is_error(self, epoch):
        return False


class _ModeleP300Renomme:
    """Un modèle P300 (interface `scores` + `select`) déposé sous un nom de modèle ErrP.

    Ça arrive dès qu'on range `data/` : `p300_model.joblib` copié en `errp_model_vieux.joblib`.
    Sans le contrôle `hasattr(score/is_error)`, ce fichier tombait sur le contrôle de MODULE et
    l'étudiant lisait « modèle hérité (module 'core.p300_decoder') — recalibre » : on l'envoyait
    recalibrer le MAUVAIS mode. Aucune fixture ne présentait un objet dépourvu de l'interface —
    supprimer entièrement ce contrôle laissait tout l'autotest vert.
    """

    def scores(self, epochs):
        return [0.0] * len(epochs)

    def select(self, epochs_by_target, margin=0.0):
        return None, {}


class _NoyauEtranger:
    """Un faux `self.core` : l'objet qui CALCULE, venu d'un autre module que `core.p300_decoder`.

    Sert à fabriquer le seul modèle que le contrôle de module extérieur ne peut pas voir — une
    coquille `core.errp_decoder.ErrPModel` toute neuve autour d'un noyau ressuscité d'un module
    fantôme (cf. le commentaire de `charger`). Définie au niveau du MODULE : `pickle` ne
    sérialise pas une classe locale à une fonction.
    """

    def fit(self, Xf, y):
        return self

    def scores(self, epochs):
        return [0.0] * len(epochs)


def _selftest():
    """Sur un dossier temporaire : un modèle valide, un fichier corrompu, un dossier vide."""
    import shutil
    import tempfile

    import joblib
    import numpy as np

    from core.errp_decoder import ErrPModel, synth_errp_epoch

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    dossier = tempfile.mkdtemp(prefix="errp_models_")
    try:
        # (Il y avait ICI un `chk(modeles_disponibles(dossier) == [])`, doublon EXACT de celui de
        # la section 3 — au premier appel, `dossier` est vide lui aussi. Aucune mutation d'une
        # ligne de `modeles_disponibles` ne les rougissait : MOTIF faux, tri supprimé, filtre
        # inversé, filtre supprimé, tous verts sur un dossier vide. Un seul survit, et il mord
        # désormais : voir la section 3.)

        # Un petit jeu synthétique, dans la forme d'une vraie calibration (blocs, classe ERREUR
        # minoritaire) : de quoi obtenir une AUC groupée non triviale (>= 10 époques, 2 classes,
        # >= 2 par classe). n_perm=0 : ce fichier ne teste pas la significativité, juste le
        # chargement/tri/refus des modèles — la permutation est testée par `errp_decoder.py`.
        rng = np.random.default_rng(0)
        fs = 250.0
        n_trials, error_rate, blocks = 40, 0.3, 4
        epochs, y, groups = [], [], []
        per = max(1, n_trials // blocks)
        for i in range(n_trials):
            is_err = rng.random() < error_rate
            epochs.append(synth_errp_epoch(is_err, fs=fs, rng=rng))
            y.append(1 if is_err else 0)
            groups.append(min(blocks - 1, i // per))
        modele = ErrPModel(fs=fs).fit(np.asarray(epochs), np.asarray(y),
                                      groups=np.asarray(groups), n_perm=0)
        bon = _os.path.join(dossier, "errp_model.joblib")
        modele.save(bon)

        chk(modeles_disponibles(dossier) == [bon],
            f"un modèle valide est listé ({modeles_disponibles(dossier)})")

        # Un fichier au bon nom mais illisible : c'est exactement l'état des modèles hérités.
        casse = _os.path.join(dossier, "errp_model_casse.joblib")
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
        etranger = _os.path.join(dossier, "errp_model_etranger.joblib")
        joblib.dump(_ModeleEtranger(), etranger)
        _m, raison = charger(etranger)
        # ⚠️ Le refus doit NOMMER LE FICHIER — les trois autres refus de `charger` le font, et les
        # deux jumeaux (`p300_models`, `mi_models`) aussi pour cette branche-là. Deux modèles
        # hérités côte à côte (`errp_model.joblib` et une copie de sauvegarde) donnaient sinon
        # deux lignes de liste rigoureusement identiques, sans dire laquelle concerne quoi.
        chk(_m is None and "recalibre" in (raison or "").lower()
            and "errp_model_etranger.joblib" in (raison or ""),
            f"un modèle hérité est refusé en disant quoi faire ET sur QUEL fichier ({raison})")
        chk(etranger not in modeles_disponibles(dossier),
            "et il n'apparaît donc pas non plus dans la liste")

        # 1 quater. Ce n'est PAS un modèle ErrP : un P300 rangé sous un nom d'ErrP. Sans le
        # contrôle d'interface, il tombe sur le contrôle de module et on envoie l'étudiant
        # recalibrer le MAUVAIS mode.
        renomme = _os.path.join(dossier, "errp_model_vieux.joblib")
        joblib.dump(_ModeleP300Renomme(), renomme)
        _m, raison = charger(renomme)
        chk(_m is None and "pas un modèle ErrP" in (raison or ""),
            f"un modèle P300 rangé sous un nom d'ErrP est refusé POUR CE QU'IL EST, pas comme "
            f"un hérité ({raison})")

        # 1 bis. LE VRAI cas hérité : le pickle porte le module NU `errp_decoder`.
        #
        # ⚠️ L'assertion ci-dessus ne pouvait PAS attraper l'assouplissement de la règle, parce que
        # `_ModeleEtranger.__module__` vaut "__main__" (ou "core.errp_models" à l'import) et jamais
        # "errp_decoder" : la mutation `module.endswith("errp_decoder")` — la passerelle de
        # compatibilité que ce chantier a refusé d'écrire — la laissait verte tout en rendant
        # `data/errp_model.joblib` à nouveau acceptable. Celle-ci rougit dessus, parce que le module
        # refusé est EXACTEMENT celui que la mutation ré-autoriserait.
        #
        # Le faux module reste dans `sys.modules` pendant le dump ET le chargement : l'en retirer
        # entre les deux ferait résoudre `errp_decoder` vers le vrai `src/core/errp_decoder.py`
        # (importable au premier niveau sous `python src/core/…`), et on testerait alors un tout
        # autre refus.
        import types

        herite = _os.path.join(dossier, "errp_model_herite.joblib")
        faux_module = types.ModuleType("errp_decoder")
        faux_module._ModeleHerite = _ModeleHerite
        _sys.modules["errp_decoder"] = faux_module
        try:
            joblib.dump(_ModeleHerite(), herite)
            _m, raison = charger(herite)
            liste_avec_herite = modeles_disponibles(dossier)
        finally:
            _sys.modules.pop("errp_decoder", None)

        # Les quotes autour du nom sont voulues : elles distinguent « module 'errp_decoder' » de
        # « attendu 'core.errp_decoder' », qui contient lui aussi la sous-chaîne errp_decoder.
        chk(_m is None and "'errp_decoder'" in (raison or ""),
            f"un modèle dont le pickle porte le module NU 'errp_decoder' est refusé, et la "
            f"raison NOMME ce module — c'est ce qui interdit la passerelle endswith() ({raison})")
        chk(_m is None and "recalibre" in (raison or "").lower(),
            f"...en disant quoi faire à la place ({raison})")
        chk(herite not in liste_avec_herite,
            f"...et il ne se glisse pas non plus dans la liste ({liste_avec_herite})")

        # 1 quinquies. Le noyau. `ErrPModel` CONTIENT un `P300Model` (`self.core`), et c'est LUI
        # qui score. Un modèle à coquille neuve et noyau hérité — ce que produirait une passerelle
        # écrite à moitié — passe tous les contrôles ci-dessus. La fixture part d'un VRAI modèle
        # (module extérieur correct, scores hors-pli présents) : seul le noyau est étranger, donc
        # seul le contrôle visé peut le refuser.
        import copy

        noyau_etranger = _os.path.join(dossier, "errp_model_noyau.joblib")
        modele_noyau = copy.deepcopy(modele)
        modele_noyau.core = _NoyauEtranger()
        modele_noyau.save(noyau_etranger)
        _m, raison = charger(noyau_etranger)
        chk(_m is None and "noyau" in (raison or "")
            and "errp_model_noyau.joblib" in (raison or ""),
            f"un modèle à coquille neuve mais NOYAU hérité est refusé — c'est le noyau qui "
            f"calcule les scores ({raison})")
        chk(noyau_etranger not in modeles_disponibles(dossier),
            "...et il n'apparaît donc pas dans la liste")

        # 1 ter. ⚠️ Correction de revue (tâche 3) : un modèle dont la calibration était trop
        # courte pour avoir des scores hors-pli (`ErrPModel.fit` ne pose `oof_scores_`/`oof_y_`
        # que si len(y)>=10, 2 classes, et chaque classe >=2 membres — cf. `errp_decoder.py`) est
        # refusé ICI, EN LE NOMMANT. Sans ce refus, un tel modèle apparaissait normalement dans la
        # liste proposée à l'étudiant (`hasattr(modele, "score"/"is_error")` ne dit rien de
        # `oof_scores_`), et `core/modes/errp.py` finissait par appeler
        # `pick_threshold(None, None, ...)` — mesuré, pas supposé : lève
        # `ValueError: zero-dimensional arrays cannot be concatenated`, une exception numpy BRUTE
        # sans aucun rapport avec ce qu'il faut faire.
        #
        # ⚠️ La fixture est CONSTRUITE, pas tranchée dans le jeu ci-dessus (`epochs[:5], y[:5]`) :
        # une tranche viole PLUSIEURS clauses de la garde à la fois (moins de 10 essais ET, très
        # probablement, une classe à moins de 2 membres), et une classe unique ferait même lever
        # la LR sur un traceback au lieu d'un ÉCHEC lisible. Avec 5 essais alternés, « moins de
        # 10 » est la SEULE clause en cause — c'est ce qui rend la valeur 10 réellement testée.
        y_court = np.asarray([0, 1, 0, 1, 0])
        degenere = _os.path.join(dossier, "errp_model_degenere.joblib")
        modele_degenere = ErrPModel(fs=fs).fit(np.asarray(epochs[:5]), y_court, n_perm=0)
        chk(len(np.unique(y_court)) == 2 and int(np.bincount(y_court).min()) >= 2,
            f"fixture : les 2 classes sont là, avec >= 2 essais chacune — seul « moins de 10 "
            f"essais » peut refuser ce modèle ({np.bincount(y_court).tolist()})")
        chk(modele_degenere.oof_scores_ is None and modele_degenere.oof_y_ is None,
            f"fixture : 5 essais (< 10) ne posent PAS de scores hors-pli, la dégénérescence est "
            f"réelle, pas simulée ({modele_degenere.oof_scores_})")
        modele_degenere.save(degenere)
        _m, raison = charger(degenere)
        chk(_m is None and "hors-pli" in (raison or "")
            and "recalibre" in (raison or "").lower(),
            f"un modèle sans scores hors-pli est refusé EN LE NOMMANT, avec quoi faire ({raison})")
        # ...et la cause citée est celle que `fit` a CONSTATÉE, pas une liste de causes possibles
        # récitée de mémoire. C'est ce qui distingue « trop courte » de « validation croisée
        # échouée » — deux pannes dont une seule se répare en rallongeant la séance (cf. le
        # `_gardes` de `errp_decoder.py`, qui produit l'autre).
        chk(modele_degenere.echec_oof_ and modele_degenere.echec_oof_ in (raison or ""),
            f"...et la raison RECOPIE le diagnostic posé par fit lui-même, mot pour mot "
            f"({modele_degenere.echec_oof_!r})")
        chk(degenere not in modeles_disponibles(dossier),
            f"...et il n'apparaît donc pas dans la liste proposée à l'étudiant "
            f"({modeles_disponibles(dossier)})")

        d = decrire(bon)
        chk(d["nom"] == "errp_model.joblib", f"la description porte le nom du fichier ({d['nom']})")
        chk(isinstance(d["cv_auc"], float) and 0.0 <= d["cv_auc"] <= 1.0,
            f"l'AUC honnête (GroupKFold par bloc) est une proportion ({d['cv_auc']})")
        # ⚠️ Cette assertion était RETOURNÉE : elle exigeait `n_epoques is None`, c'est-à-dire
        # qu'elle interdisait le correctif. Analyse de mutation à l'appui : aucune mutation d'une
        # ligne de `charger`/`decrire` ne la rougissait, et la SEULE chose qui la rougissait était
        # d'ajouter `self.n_epoques_ = int(len(y))` à `ErrPModel.fit` — une amélioration correcte,
        # que ce test aurait fait passer pour une régression. Elle dit maintenant ce que dit son
        # jumeau (`p300_models.py`) : le chiffre est là, et c'est le bon.
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
        # key=_os.path.getmtime, le tri alphabétique réversé donnerait ["errp_model_z",
        # "errp_model_a"], OPPOSÉ au tri par date qu'on attend.
        ancien = _os.path.join(dossier, "errp_model_z.joblib")
        recent = _os.path.join(dossier, "errp_model_a.joblib")
        _os.rename(bon, ancien)
        modele.save(recent)
        _os.utime(ancien, (1_600_000_000, 1_600_000_000))
        dispo = modeles_disponibles(dossier)
        chk(dispo == [recent, ancien], f"le plus récent d'abord ({dispo})")

        # 3. Ce que la liste LAISSE DEHORS. La version d'avant demandait « un dossier vide rend
        # [] » — vrai, mais insensible à toute mutation d'une ligne (MOTIF faux, tri supprimé,
        # filtre inversé, filtre supprimé : tous verts sur un dossier vide). Ici le dossier
        # contient exactement les deux pièges, et le résultat attendu reste [] :
        #   (a) un modèle PARFAITEMENT valide sous un nom qui ne correspond PAS à MOTIF — il
        #       rougit `MOTIF = "*.joblib"`, l'élargissement qu'on écrit sans y penser ;
        #   (b) un fichier illisible sous un nom qui, lui, correspond — il rougit la suppression
        #       du filtre `charger(...)` et son inversion.
        vide = tempfile.mkdtemp(prefix="errp_models_vide_")
        try:
            hors_motif = _os.path.join(vide, "modele_errp.joblib")
            modele.save(hors_motif)
            illisible = _os.path.join(vide, "errp_model_illisible.joblib")
            with open(illisible, "wb") as f:
                f.write(b"ceci n'est pas un pickle")
            chk(modeles_disponibles(vide) == [],
                f"un dossier sans AUCUN modèle utilisable rend [], sans lever — ni le fichier "
                f"hors-motif, ni l'illisible ({modeles_disponibles(vide)})")

            # ...et un candidat qui s'ÉVAPORE entre le `glob` et le tri par date ne fait pas
            # lever : la console ouvre son catalogue pendant qu'une calibration écrit, et
            # `Param.choices_status` classerait cette course en « DÉFAUT de déclaration » du mode.
            # On rejoue la course en faisant rendre à `glob` un chemin qui n'existe plus — c'est
            # exactement ce qu'il rend quand le fichier part juste après.
            disparu = _os.path.join(vide, "errp_model_disparu.joblib")
            vrai_glob = _glob.glob
            _glob.glob = lambda motif: [disparu, illisible]
            try:
                liste_course = modeles_disponibles(vide)
                leve = None
            except Exception as e:      # noqa: BLE001 - c'est l'exception elle-même qu'on teste
                liste_course, leve = None, f"{type(e).__name__}: {e}"
            finally:
                _glob.glob = vrai_glob
            chk(leve is None and liste_course == [],
                f"un fichier disparu entre le glob et le tri par date ne fait pas lever la liste "
                f"({leve or liste_course})")
        finally:
            shutil.rmtree(vide, ignore_errors=True)
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[errp-models] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
