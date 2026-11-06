# -*- mode: python ; coding: utf-8 -*-
#
# Recette PyInstaller de « EEG API Unicorn » : transforme les sources Python en un dossier qui
# tourne sur un Windows SANS Python installé.
#
# Construire (depuis la racine du dépôt ; `construire_installeur.ps1` le fait pour toi) :
#
#     .venv\Scripts\python.exe -m PyInstaller build\eeg_api_unicorn.spec --noconfirm
#
# Résultat : `dist\EEG API Unicorn\`, un dossier « one-folder » :
#   - `EEG API Unicorn.exe`       le programme, sans fenêtre de terminal : la console ;
#   - `eeg-api-unicorn-cli.exe`   le MÊME programme, mais qui écrit dans un terminal ;
#   - `_internal\`                Python, les bibliothèques et les données, partagés par les deux.
#
# Les deux exécutables lancent le même fichier, `src/eeg_api_unicorn.py` : sans argument la
# console, avec `--fenetre <clé>` une fenêtre de stimulus, avec `--serveur` le moteur sans écran.
# Pourquoi deux (mesuré, voir `LISEZMOI.md`) : un programme « fenêtré » n'écrit rien dans le
# terminal qui le lance, et s'il plante, le lanceur de PyInstaller affiche une boîte « Unhandled
# exception » qui le garde en vie jusqu'à ce qu'on clique. Le second, en mode console, se comporte comme
# `python script.py` : il écrit dans le terminal, et un plantage le termine en écrivant l'erreur.
# La console relance donc `eeg-api-unicorn-cli.exe --fenetre <clé>` pour ses fenêtres de
# stimulus (`stimulus/registry.py`), et c'est lui qu'on tape pour le moteur seul.
#
# Ce fichier est du Python, exécuté par PyInstaller : `SPECPATH` (le dossier de ce fichier),
# `Analysis`, `PYZ`, `EXE` et `COLLECT` sont fournis par lui.

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

RACINE = os.path.dirname(os.path.abspath(SPECPATH))     # la racine du dépôt
SRC = os.path.join(RACINE, "src")

# Les trois paquets du produit (`core`, `console`, `stimulus`) sont des dossiers de `src/` : il
# faut les rendre importables ICI aussi, pour que `collect_submodules` les trouve.
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def _sans_tests(nom):
    """Écarte les tests des bibliothèques : inutiles au programme, et ils importent pytest. Écarte
    aussi les branches écrites pour d'autres bibliothèques de calcul (torch, cupy, dask, jax), que
    le programme n'utilise pas et qui ne sont pas installées."""
    morceaux = set(nom.split("."))
    return not morceaux & {"tests", "conftest", "testing", "vendor_tests",
                           "torch", "cupy", "dask", "jax"}


# ─── Les données (fichiers qui ne sont pas du Python) ──────────────────────────────────────
# Format : (source sur le disque, dossier de destination dans `_internal\`).
datas = [
    # Les textes affichés, une langue par dossier. `core/i18n.py` les cherche à côté de lui :
    # la destination doit donc être `core\langues`.
    (os.path.join(SRC, "core", "langues"), os.path.join("core", "langues")),
    # L'icône de la fenêtre (lue par `config.chemin_ressource`).
    (os.path.join(RACINE, "assets", "logo"), os.path.join("assets", "logo")),
]

# ─── Les bibliothèques natives (DLL) ───────────────────────────────────────────────────────
# BrainFlow parle au casque par ses DLL, rangées dans `brainflow\lib\`. Il les charge par leur
# chemin à côté de son propre code, donc elles doivent arriver au MÊME endroit :
# `_internal\brainflow\lib\`.
#
# On n'en prend que TROIS, nommées dans `core/acquisition.py` (`DLL_BRAINFLOW`) :
# `BoardController.dll` (les sessions : le casque et le board de test), `DataHandler.dll` (les
# filtres) et `Unicorn.dll` (le SDK du casque, que `BoardController.dll` charge à l'ouverture
# d'un Unicorn). Leurs tables d'import ne demandent que des DLL de Windows. Le dossier de
# BrainFlow contient aussi les SDK des casques d'autres fabricants (BrainBit, Muse, Ganglion,
# ANT Neuro, gForce…) et le module d'apprentissage de BrainFlow, que le produit n'utilise jamais.
# Les embarquer obligerait à distribuer leurs licences, et celle du SDK d'ANT Neuro
# (`eego-SDK.dll`) impose en plus une clause de publicité. `--verifier-modules`
# vérifie que le programme construit contient exactement ces trois DLL, et les fait servir.
import brainflow  # noqa: E402
from core.acquisition import DLL_BRAINFLOW  # noqa: E402

_LIB_BRAINFLOW = os.path.join(os.path.dirname(brainflow.__file__), "lib")
binaries = []
for _nom in DLL_BRAINFLOW:
    _chemin = os.path.join(_LIB_BRAINFLOW, _nom)
    if not os.path.isfile(_chemin):
        raise SystemExit(f"{_nom} manque dans {_LIB_BRAINFLOW} : la version de BrainFlow "
                         "installée ne fournit plus cette DLL")
    binaries.append((_chemin, os.path.join("brainflow", "lib")))
# `lsl.dll` (pylsl) n'a pas besoin d'une ligne ici : le crochet (« hook ») de pylsl fourni avec
# PyInstaller la range déjà dans `_internal\pylsl\lib\`, là où pylsl la cherche.

# ─── Les modules que PyInstaller ne peut pas deviner ───────────────────────────────────────
# PyInstaller suit les `import` écrits dans le code. Il manque donc :
#   - les modules lancés par leur NOM (`runpy` dans `src/eeg_api_unicorn.py` : la console, les
#     fenêtres de stimulus, le moteur) et ceux importés à l'intérieur d'une fonction ;
#   - ce que RELIT un modèle enregistré (joblib) : il désigne ses classes par leur nom
#     (`sklearn.pipeline.Pipeline`, `pyriemann.estimation.XdawnCovariances`…), que rien
#     n'importe avant le chargement ;
#   - `array_api_compat` et `array_api_extra`, que pyriemann utilise : ils chargent leur partie
#     « numpy » par son nom (`array_api_compat.numpy.fft`), à la première utilisation.
# On prend donc tous les sous-modules du produit, des trois bibliothèques de décodage et de ces
# deux-là. `eeg-api-unicorn-cli.exe --verifier-modules` vérifie le résultat : il charge chaque
# DLL, puis entraîne, enregistre et relit un modèle de chaque sorte.
hiddenimports = []
for _paquet in ("core", "console", "stimulus"):
    hiddenimports += collect_submodules(_paquet)
for _paquet in ("sklearn", "pyriemann", "pyntbci", "array_api_compat", "array_api_extra"):
    hiddenimports += collect_submodules(_paquet, filter=_sans_tests)

# ─── Ce qu'on laisse dehors ────────────────────────────────────────────────────────────────
excludes = [
    "research",          # le banc d'essai hors ligne du dépôt : pas une partie du programme
    "tkinter", "_tkinter",
    "pytest", "_pytest",
    "IPython", "jupyter", "notebook",
    "PyInstaller",       # l'outil de construction lui-même
]

a = Analysis(
    [os.path.join(SRC, "eeg_api_unicorn.py")],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# ─── Rien qui vienne d'ailleurs que de l'environnement Python et du dépôt ──────────────────
# PyInstaller cherche aussi les DLL dans le PATH de la machine qui construit. Le crochet de Qt
# y trouve par exemple l'OpenSSL de Git for Windows (`libssl-3-x64.dll`, `libcrypto-3-x64.dll`),
# que Qt ne chargerait que pour une connexion HTTPS, que le produit n'ouvre jamais (Qt a de toute
# façon le chiffrement de Windows). Une telle DLL change d'une machine à l'autre, aucun fichier du
# dépôt ne fixe sa version, et sa licence ne serait pas dans `THIRD-PARTY-NOTICES.txt`. On ne
# garde donc que ce qui vient de l'interpréteur, de ses bibliothèques installées et du dépôt.
_RACINES_PERMISES = tuple(os.path.normcase(os.path.abspath(r)) + os.sep
                          for r in {sys.prefix, sys.base_prefix, RACINE})


def _vient_d_ici(source):
    return os.path.normcase(os.path.abspath(source)).startswith(_RACINES_PERMISES)


for _dest, _source, _type in a.binaries:
    if not _vient_d_ici(_source):
        print(f"[eeg_api_unicorn.spec] écartée (hors de l'environnement Python) : {_source}")
a.binaries = [b for b in a.binaries if _vient_d_ici(b[1])]

pyz = PYZ(a.pure)

ICONE = os.path.join(RACINE, "assets", "logo", "eeg-api-unicorn.ico")

# La console : un programme à fenêtres, sans terminal noir à côté. S'il plante au démarrage,
# la boîte d'erreur de PyInstaller montre l'erreur à l'utilisateur, qui sinon ne verrait rien.
exe_fenetre = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EEG API Unicorn",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # pas de compression UPX : elle déclenche des alertes d'antivirus
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICONE,
)

# Le même programme en mode console. ⚠️ Son nom est écrit aussi dans `stimulus/registry.py`
# (`EXE_CONSOLE`), qui le cherche à côté de la console : l'autotest du registre vérifie l'accord.
exe_console = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="eeg-api-unicorn-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICONE,
)

# Un seul dossier, un seul `_internal\` pour les deux exécutables.
coll = COLLECT(
    exe_fenetre,
    exe_console,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="EEG API Unicorn",
)
