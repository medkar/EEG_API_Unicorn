"""Le point d'entrée unique du programme : la console, une fenêtre de stimulus ou le moteur seul.

Une fois le programme installé, il n'y a plus d'interpréteur Python ni de fichiers `.py` à lancer.
Deux exécutables lancent ce fichier : `EEG API Unicorn.exe`, sans terminal (la console), et
`eeg-api-unicorn-cli.exe`, le même en mode console (il écrit dans le terminal qui le lance). Pour
ouvrir une fenêtre de stimulus, la console relance le second avec `--fenetre <clé>` : c'est ce
fichier qui aiguille. Le premier n'a pas de terminal où écrire : ses messages vont dans
`Documents\\EEG API Unicorn\\journaux\\console.log` (voir `rediriger_vers_journal`). Depuis les
sources, il marche aussi :

    python src/eeg_api_unicorn.py [arguments]

    (aucun argument spécial)    la console ; les arguments sont ceux de `src/console/app.py`
                                (`--synthetic`, `--mode ssvep`, `--smoke`…)
    --fenetre <clé> [args]      une fenêtre de stimulus (p300, errp, cvep, ssvep, mi) ; les
                                arguments sont ceux du fichier de la fenêtre (`--calibrer`…)
    --serveur [args]            le moteur seul, sans écran ; arguments de `src/core/server.py`
    --version                   affiche la version et quitte
    --verifier-modules          importe tout ce dont le produit a besoin, compte les DLL de
                                BrainFlow (programme construit), fait servir chaque DLL, puis
                                entraîne un petit modèle de chaque sorte sur des données
                                fabriquées, l'enregistre dans un dossier temporaire, le relit et
                                lui fait prendre une décision ; code 0, ou code 1 au premier
                                échec (nommé)
"""

import os
import runpy
import sys

# Les autres scripts du dépôt font pareil : les paquets (`core`, `stimulus`, `console`) sont
# des sous-dossiers de celui-ci.
_ICI = os.path.dirname(os.path.abspath(__file__))
if _ICI not in sys.path:
    sys.path.insert(0, _ICI)

# Modules importés par `--verifier-modules`. Au-delà des bibliothèques directes, on liste les
# sous-modules que les modèles enregistrés (joblib) font recharger : un exécutable qui oublie l'un
# d'eux démarre bien, puis échoue au chargement d'un modèle. La liste ne prouve pas tout : un
# modèle peut avoir besoin d'un sous-module qu'on n'a pas pensé à écrire ici. C'est pourquoi la
# vérification ENTRAÎNE et RELIT ensuite un vrai modèle de chaque sorte (`_verifier_modeles`).
MODULES_REQUIS = (
    "numpy",
    "scipy.signal",
    "scipy.stats",
    "scipy.linalg",
    "scipy.integrate",
    "sklearn",
    "sklearn.base",
    "sklearn.pipeline",
    "sklearn.preprocessing",
    "sklearn.covariance",
    "sklearn.utils",
    "sklearn.linear_model",
    "sklearn.discriminant_analysis",
    "sklearn.feature_selection",
    "sklearn.model_selection",
    "sklearn.metrics",
    "sklearn.svm",              # importé par pyntbci
    "pyriemann",
    "pyriemann.utils",
    "pyriemann.estimation",
    "pyriemann.spatialfilters",  # le filtre xDAWN du P300 et de l'ErrP
    "pyriemann.tangentspace",
    "matplotlib",               # importé par pyntbci (ses tracés) : sans lui, pas de rCCA
    "pyntbci",
    "pyntbci.classifiers",
    "joblib",
    "brainflow.board_shim",
    "pylsl",
    "pygame",
    "PySide6.QtWidgets",
    "pyqtgraph",
    # Les modules du produit qui entraînent, enregistrent et relisent les modèles.
    "core.mi_decoder",
    "core.mi_models",
    "core.p300_decoder",
    "core.p300_models",
    "core.errp_decoder",
    "core.errp_models",
    "core.cvep_decoder",
    "core.cvep_rcca",
    "core.cvep_models",
)


def _lancer_module(nom, argv0, args):
    """Exécute le module `nom` comme s'il était lancé en script, avec ses propres arguments.

    Le code de sortie du module (`SystemExit`) remonte tel quel.
    """
    sys.argv = [argv0, *args]
    runpy.run_module(nom, run_name="__main__", alter_sys=True)


def _verifier_modules():
    """Importe chaque module requis et affiche sa version, puis vérifie les modèles.

    Code 1 au premier module manquant ou au premier modèle qui échoue."""
    import importlib
    for nom in MODULES_REQUIS:
        try:
            module = importlib.import_module(nom)
        except Exception as e:  # un import peut échouer autrement que par ImportError
            print(f"module manquant ou inutilisable : {nom} ({type(e).__name__} : {e})",
                  file=sys.stderr)
            return 1
        racine = sys.modules.get(nom.split(".")[0])
        if nom.startswith("core."):     # un module du produit : la version du produit
            from core.version import VERSION as version
        else:
            version = getattr(module, "__version__", None) or getattr(racine, "__version__", "?")
        print(f"{nom} {version}")
    return _verifier_natives() or _verifier_modeles()


def _verifier_dll_brainflow():
    """Le programme construit contient EXACTEMENT les DLL de BrainFlow de `DLL_BRAINFLOW`.

    Une DLL de plus serait le SDK d'un autre fabricant, distribué sans sa licence ; une de moins,
    et le casque ou les filtres ne marchent plus. Depuis les sources, le dossier de BrainFlow
    contient toutes ses DLL : on ne compte que dans le programme construit."""
    if not getattr(sys, "frozen", False):
        print("DLL de BrainFlow : non comptées (lancé depuis les sources, pas depuis le "
              "programme construit)")
        return 0
    import brainflow
    from core.acquisition import DLL_BRAINFLOW
    dossier = os.path.join(os.path.dirname(brainflow.__file__), "lib")
    presentes = {n.lower(): n for n in os.listdir(dossier) if n.lower().endswith(".dll")}
    attendues = {n.lower(): n for n in DLL_BRAINFLOW}       # Windows ignore la casse
    en_trop = sorted(presentes[n] for n in presentes.keys() - attendues.keys())
    manquantes = sorted(attendues[n] for n in attendues.keys() - presentes.keys())
    if en_trop or manquantes:
        print(f"DLL de BrainFlow : ÉCHEC dans {dossier} (en trop : {en_trop or 'aucune'} ; "
              f"manquantes : {manquantes or 'aucune'} ; attendues : {list(DLL_BRAINFLOW)})",
              file=sys.stderr)
        return 1
    print(f"DLL de BrainFlow : exactement {', '.join(DLL_BRAINFLOW)}")
    return 0


def _verifier_natives():
    """Charge chaque bibliothèque native (DLL) du produit et la fait servir, sans ouvrir le casque
    ni le réseau.

    Une DLL oubliée par l'empaquetage ne se voit pas à l'import du module Python qui l'utilise :
    seulement au premier appel. On fait donc, pour chacune, un vrai appel : ouvrir le board de test
    de BrainFlow et lire son signal, filtrer un signal, trouver la fonction qui liste les casques."""
    def unicorn():
        from core.acquisition import fonction_liste_unicorn
        fonction_liste_unicorn()        # charge la DLL et trouve la fonction, sans l'appeler
        return "chargée, UNICORN_GetAvailableDevices trouvée"

    def boardcontroller():
        import time
        from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams
        BoardShim.disable_board_logger()
        board = BoardShim(BoardIds.SYNTHETIC_BOARD, BrainFlowInputParams())
        board.prepare_session()
        try:
            board.start_stream()
            time.sleep(0.5)
            donnees = board.get_board_data()
            board.stop_stream()
        finally:
            board.release_session()
        if donnees.shape[1] == 0:
            raise RuntimeError("le board de test n'a rendu aucun échantillon en 0,5 s")
        return f"{BoardShim.get_version()}, board de test : {donnees.shape[1]} échantillons lus"

    def datahandler():
        # 2 s d'une sinusoïde à 10 Hz plus une dérive lente : le passe-bande 1-40 Hz garde la
        # sinusoïde et retire la dérive. On vérifie seulement que le filtre répond, pas sa qualité.
        import numpy as np
        from brainflow.data_filter import DataFilter, FilterTypes
        t = np.arange(500) / 250.0
        signal = np.ascontiguousarray(10 * np.sin(2 * np.pi * 10 * t) + 100 * t)
        DataFilter.perform_bandpass(signal, 250, 1.0, 40.0, 4, FilterTypes.BUTTERWORTH.value, 0)
        if not np.all(np.isfinite(signal)):
            raise RuntimeError("le passe-bande a rendu des valeurs non finies")
        return f"{DataFilter.get_version()}, passe-bande 1-40 Hz appliqué"

    def liblsl():
        import pylsl
        return pylsl.library_version()

    if _verifier_dll_brainflow():
        return 1
    for nom, essai in (("BrainFlow (BoardController.dll)", boardcontroller),
                       ("BrainFlow (DataHandler.dll)", datahandler),
                       ("SDK du casque (Unicorn.dll)", unicorn),
                       ("LSL (lsl.dll)", liblsl)):
        try:
            print(f"bibliothèque {nom} : {essai()}")
        except Exception as e:  # noqa: BLE001 - une DLL absente lève de plusieurs façons
            print(f"bibliothèque {nom} : ÉCHEC ({type(e).__name__} : {e})", file=sys.stderr)
            return 1
    return 0


# --- Les modèles : entraîner, enregistrer, relire, décider ---------------------------------
#
# Chaque fonction ci-dessous fabrique un petit jeu de données avec le générateur synthétique du
# module concerné (le même que son autotest), entraîne un modèle, l'enregistre avec la fonction
# d'enregistrement du produit, le relit avec la fonction de chargement du produit (celle qu'utilise
# le moteur) et compare une décision avant et après la relecture. Elle rend une courte phrase, ou
# lève une exception qui dit ce qui a échoué.

def _relire(charger, chemin):
    """Relit un modèle avec la fonction `charger` d'un module `*_models` ; lève si elle refuse."""
    modele, raison = charger(chemin)
    if modele is None:
        raise RuntimeError(f"relecture refusée : {raison}")
    return modele


def _meme_decision(avant, apres):
    """Lève si la décision du modèle relu n'est pas celle du modèle d'origine."""
    import numpy as np
    avant = np.asarray(avant, dtype=float)
    apres = np.asarray(apres, dtype=float)
    if avant.shape != apres.shape or not np.allclose(avant, apres, rtol=1e-6, atol=1e-9):
        raise RuntimeError(f"le modèle relu ne décide pas comme l'original "
                           f"({np.round(avant, 4).tolist()} contre {np.round(apres, 4).tolist()})")


def _modele_mi(dossier, methode):
    """Motor Imagery, méthode `csp` (le défaut) ou `fbcsp` (l'option d'« Entraîner »)."""
    import numpy as np
    from core import mi_models
    from core.mi_decoder import MI_LABELS, MIModel, synth_mi_trial
    rng = np.random.default_rng(0)
    essais, etiquettes = [], []
    for tache in MI_LABELS:
        for _ in range(6):
            essais.append(synth_mi_trial(tache, rng=rng))
            etiquettes.append(tache)
    modele = MIModel(fs=250.0, method=methode, secteur_hz=50.0).fit(
        np.asarray(essais), np.asarray(etiquettes))
    chemin = os.path.join(dossier, f"mi_model_{methode}.joblib")
    modele.save(chemin)
    relu = _relire(mi_models.charger, chemin)
    avant, apres = modele.predict_proba(essais[0]), relu.predict_proba(essais[0])
    _meme_decision([avant[t] for t in MI_LABELS], [apres[t] for t in MI_LABELS])
    return f"tâche décidée : {max(apres, key=apres.get)}"


def _modele_p300(dossier):
    import numpy as np
    from core import p300_models
    from core.p300_decoder import P300Model, synth_p300_epoch
    rng = np.random.default_rng(0)
    epoques, etiquettes, manches = [], [], []
    for manche in range(6):
        consigne = manche % 3
        for _ in range(4):
            for cible in range(3):
                epoques.append(synth_p300_epoch(cible == consigne, rng=rng))
                etiquettes.append(1 if cible == consigne else 0)
                manches.append(manche)
    modele = P300Model(fs=250.0).fit(np.asarray(epoques), np.asarray(etiquettes),
                                     groups=np.asarray(manches))
    chemin = os.path.join(dossier, "p300_model_verif.joblib")
    modele.save(chemin)
    relu = _relire(p300_models.charger, chemin)
    _meme_decision(modele.scores(np.asarray(epoques[:6])), relu.scores(np.asarray(epoques[:6])))
    return "scores identiques après relecture"


def _modele_errp(dossier):
    import numpy as np
    from core import errp_models
    from core.errp_decoder import ErrPModel, synth_errp_epoch
    rng = np.random.default_rng(0)
    epoques, etiquettes, blocs = [], [], []
    for i in range(40):
        erreur = rng.random() < 0.3
        epoques.append(synth_errp_epoch(erreur, fs=250.0, rng=rng))
        etiquettes.append(1 if erreur else 0)
        blocs.append(min(3, i // 10))
    # `n_perm=0` : pas de test de permutation (long, et sans objet ici).
    modele = ErrPModel(fs=250.0).fit(np.asarray(epoques), np.asarray(etiquettes),
                                     groups=np.asarray(blocs), n_perm=0)
    chemin = os.path.join(dossier, "errp_model_verif.joblib")
    modele.save(chemin)
    relu = _relire(errp_models.charger, chemin)
    _meme_decision(modele.score(np.asarray(epoques[:4])), relu.score(np.asarray(epoques[:4])))
    return f"erreur détectée sur le 1er essai : {'oui' if relu.is_error(epoques[0]) else 'non'}"


def _jeu_cvep():
    """Six cibles c-VEP, quatre cycles chacune, quatre voies (le générateur de `cvep_decoder`)."""
    import numpy as np
    from core.cvep_code import build_targets
    from core.cvep_decoder import synth_cvep
    plan, code = build_targets()
    rng = np.random.default_rng(3)
    cycles, indices = [], []
    for i, cible in enumerate(plan):
        for _ in range(4):
            cycles.append(synth_cvep(code, cible["lag"], 4, 250.0, 60.0, -6.0, rng))
            indices.append(i)
    return plan, code, cycles, indices


def _modele_ecca(dossier):
    from core import cvep_models
    from core.cvep_decoder import CVEPModel
    plan, code, cycles, indices = _jeu_cvep()
    lags = [c["lag"] for c in plan]
    modele = CVEPModel(fs=250.0, refresh=60.0, code_len=len(code), channels=[0, 1, 2, 3]).fit(
        cycles, [lags[i] for i in indices])
    chemin = modele.save(os.path.join(dossier, "cvep_model_verif.npz"),
                         n_targets=len(plan), n_plan=len(plan))
    relu = _relire(cvep_models.charger, chemin)
    avant, apres = modele.scores(cycles[0], 0, lags), relu.scores(cycles[0], 0, lags)
    _meme_decision([avant[l] for l in lags], [apres[l] for l in lags])
    return f"cible décidée : {plan[lags.index(max(apres, key=apres.get))]['name']}"


def _modele_rcca(dossier):
    import numpy as np
    from core import cvep_models
    from core.cvep_rcca import RCCAModel
    plan, _code, cycles, indices = _jeu_cvep()
    codes = np.stack([np.asarray(c["code"], dtype=int) for c in plan])
    modele = RCCAModel(codes, fs=250.0, refresh=60.0, channels=[0, 1, 2, 3]).fit(
        cycles, indices, compute_cv=False)
    chemin = modele.save(os.path.join(dossier, "cvep_rcca_model_verif.npz"))
    relu = _relire(cvep_models.charger, chemin)
    apres = relu.scores(cycles[0], 0)
    _meme_decision(modele.scores(cycles[0], 0), apres)
    return f"cible décidée : {plan[int(np.argmax(apres))]['name']}"


MODELES_VERIFIES = (
    ("MI (CSP + LDA)", lambda d: _modele_mi(d, "csp")),
    ("MI (FBCSP)", lambda d: _modele_mi(d, "fbcsp")),
    ("P300 (xDAWN + espace tangent)", _modele_p300),
    ("ErrP", _modele_errp),
    ("c-VEP eCCA", _modele_ecca),
    ("c-VEP rCCA", _modele_rcca),
)


def _verifier_modeles():
    """Une ligne par sorte de modèle ; 1 au premier échec, en le nommant.

    Tout s'écrit dans un dossier TEMPORAIRE, effacé à la fin : jamais dans les modèles de
    l'utilisateur."""
    import shutil
    import tempfile
    import time
    dossier = tempfile.mkdtemp(prefix="eeg_api_unicorn_verif_")
    try:
        for nom, essai in MODELES_VERIFIES:
            debut = time.perf_counter()
            try:
                bilan = essai(dossier)
            except Exception as e:  # noqa: BLE001 - on veut nommer TOUTE panne, quelle qu'elle soit
                print(f"modèle {nom} : ÉCHEC ({type(e).__name__} : {e})", file=sys.stderr)
                return 1
            print(f"modèle {nom} : entraîné, enregistré, relu ; {bilan} "
                  f"({time.perf_counter() - debut:.1f} s)")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)
    return 0


# Le journal, dans le dossier `config.JOURNAUX_DIR`, et celui du lancement d'avant.
JOURNAL = "console.log"
JOURNAL_PRECEDENT = "console.precedent.log"


def rediriger_vers_journal(dossier):
    """Envoie la sortie standard et la sortie d'erreur dans `<dossier>/console.log`.

    Lancé par son raccourci, l'exécutable sans terminal n'a pas de sortie : `sys.stdout` et
    `sys.stderr` valent `None`, et tout ce que le programme écrit (les messages du moteur,
    l'erreur qui l'arrête) serait perdu. Le journal du lancement d'avant devient
    `console.precedent.log` (il remplace le plus ancien) : après un arrêt, c'est souvent lui qu'on
    veut lire, et le relancer ne l'efface pas.

    Le journal est en UTF-8, écrit ligne par ligne (une ligne est sur le disque dès qu'elle est
    finie, même si le programme s'arrête juste après), et un caractère impossible à écrire est
    remplacé au lieu de lever.

    Rend le chemin du journal. Si le dossier n'est pas utilisable (Documents en lecture seule,
    disque plein, journal ouvert par un autre programme), rend `None` et ne touche à rien : le
    programme démarre quand même, sans journal.
    """
    try:
        os.makedirs(dossier, exist_ok=True)
        chemin = os.path.join(dossier, JOURNAL)
        if os.path.exists(chemin):
            os.replace(chemin, os.path.join(dossier, JOURNAL_PRECEDENT))
        journal = open(chemin, "w", encoding="utf-8", errors="replace", buffering=1)
    except Exception:  # noqa: BLE001 - quoi qu'il arrive ici, le programme doit démarrer
        return None
    sys.stdout = sys.stderr = journal
    return chemin


def main(argv):
    # Lancé par son raccourci, l'exécutable sans terminal n'a pas de sortie (`None`) : ses
    # messages vont alors dans le journal, que la console cite si le moteur s'arrête.
    from core import config
    if config.empaquete() and sys.stdout is None:
        config.journal_actif = rediriger_vers_journal(config.JOURNAUX_DIR)
    # La console lit la sortie d'une fenêtre ligne par ligne, en UTF-8 : sans `python -u`, on met
    # le mode ligne ici, et l'UTF-8 (sinon Windows écrit les accents dans son ancien codage, et la
    # console les afficherait mal). Le journal est déjà ouvert ainsi. Une sortie absente (`None`,
    # sans journal) reste absente.
    if config.journal_actif is None:
        for flux in (sys.stdout, sys.stderr):
            if flux is not None:
                flux.reconfigure(encoding="utf-8", line_buffering=True)

    premier = argv[0] if argv else None
    if premier == "--version":
        from core.version import VERSION
        print(VERSION)
        return 0
    if premier == "--verifier-modules":
        return _verifier_modules()
    if premier == "--serveur":
        _lancer_module("core.server", "server.py", argv[1:])
        return 0
    if premier == "--fenetre":
        from stimulus.registry import FENETRES
        cle = argv[1] if len(argv) > 1 else ""
        if cle not in FENETRES:
            print(f"Fenêtre inconnue : « {cle} ». Clés connues : {', '.join(sorted(FENETRES))}.",
                  file=sys.stderr)
            return 2
        module = FENETRES[cle][:-3] if FENETRES[cle].endswith(".py") else FENETRES[cle]
        _lancer_module(f"stimulus.{module}", f"{module}.py", argv[2:])
        return 0
    _lancer_module("console.app", "app.py", argv)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
