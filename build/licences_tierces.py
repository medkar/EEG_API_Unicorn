"""Écrit `THIRD-PARTY-NOTICES.txt` : la licence de tout ce que l'installeur embarque.

    python build/licences_tierces.py "dist/EEG API Unicorn"   # écrit le fichier dans ce dossier
    python build/licences_tierces.py --sources-lgpl "dist/EEG API Unicorn" sources-lgpl.md
                                      # le bloc Markdown des sources LGPL, pour la Release
    python build/licences_tierces.py --autotest               # les contrôles, sur des cas fabriqués
    python build/licences_tierces.py --rafraichir-qt          # (réseau) réécrit build/licences/qt.txt

Le programme lui-même est sous licence MIT (`LICENSE`, à la racine du dépôt). Le programme
installé contient aussi Python, des bibliothèques Python (numpy, PySide6…) et des DLL écrites par
d'autres (Qt, SDL, la bibliothèque du casque de g.tec…). Leurs licences demandent presque toutes
la même chose : que leur texte accompagne le programme. Ce script les rassemble, à chaque
construction, dans un fichier posé à côté des exécutables. `construire_installeur.ps1` l'appelle
juste après PyInstaller, avec le Python qui a construit : ce sont donc les versions réellement
embarquées qui sont citées.

Quatre composants sont sous LGPL : Qt, PySide6 et Shiboken6, FFmpeg (dans Qt Multimedia) et
pygame. La LGPL demande en plus d'offrir leur code source. Elle admet qu'il soit sur le serveur
d'un tiers, si des indications claires accompagnent le programme : la version exacte et l'adresse
de ce code, rangées dans `SOURCES_LGPL`. Elles sont écrites dans `THIRD-PARTY-NOTICES.txt` et,
par `--sources-lgpl`, dans un bloc Markdown que le workflow de release recopie dans les notes de
chaque Release, à côté de l'installeur.

D'où vient chaque texte :

- **les bibliothèques Python** : les paquets fixés dans `build/contraintes.txt`, moins les outils
  de construction (`OUTILS_DE_CONSTRUCTION`). Pour chacun, les fichiers de licence que ses
  métadonnées installées déclarent (`License-File`), plus les fichiers LICENSE*, COPYING*…
  rangés à côté. Quand un paquet n'en contient aucun, ou pas le bon, le texte est gardé dans
  `build/licences/` (`COMPLEMENTS`) ;
- **ce qui n'est pas une bibliothèque Python** : Python lui-même (son `LICENSE.txt`), et les
  bibliothèques natives qu'un paquet transporte sans leur licence (`AUTRES`) : le SDK du casque
  dans BrainFlow, liblsl dans pylsl, SDL dans pygame, Qt dans PySide6.

Le script REFUSE (code 1, en nommant le coupable) plutôt que d'écrire un fichier incomplet :

- un paquet embarqué sans aucun texte de licence ;
- un paquet installé qui n'est pas dans `contraintes.txt` (il serait embarqué sans être cité), ou
  dont la version installée n'est pas celle du fichier ;
- un texte de `build/licences/` relevé pour une autre version que celle installée (il faut le
  relire) ;
- une DLL ou un module natif du programme construit qui ne vient d'aucun paquet installé ni de
  Python (une bibliothèque attrapée sur la machine de construction) ;
- une DLL de Qt que la table `DLL_QT` ne connaît pas (son code tiers n'a pas été relevé) ;
- un composant sous LGPL que `SOURCES_LGPL` ne couvre pas, ou dont la version embarquée n'est pas
  celle pour laquelle l'adresse de son code source a été relevée.

Ainsi, une nouvelle dépendance ne part jamais en silence sans sa licence.
"""

from __future__ import annotations

import email.message
import html
import importlib.metadata as metadata
import os
import re
import sys
import tempfile
import textwrap
import urllib.parse
import urllib.request
from pathlib import Path
from typing import NamedTuple

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
LICENCES = ICI / "licences"
CONTRAINTES = ICI / "contraintes.txt"
NOM_FICHIER = "THIRD-PARTY-NOTICES.txt"
DEPOT_PUBLIC = "https://github.com/medkar/EEG_API_Unicorn"

# Les paquets que PyInstaller installe pour lui-même : ils construisent le programme, aucun de
# leurs fichiers n'est dedans (la recette exclut aussi PyInstaller).
OUTILS_DE_CONSTRUCTION = {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile",
                          "pywin32-ctypes"}
# Installés dans tout Python, jamais embarqués.
TOUJOURS_LA = {"pip"}

# Les textes partagés par plusieurs composants : écrits UNE fois, en partie 3 du fichier.
# La GPL v3 y est parce que la LGPL v3 (Qt, PySide6) n'est qu'un ajout à la GPL v3 et demande
# que les DEUX textes accompagnent le programme, et parce que la police que pygame embarque
# (FreeSans) est sous GPL.
TEXTES_PARTAGES = {
    "lgpl-3.0.txt": "GNU Lesser General Public License, version 3",
    "lgpl-2.1.txt": "GNU Lesser General Public License, version 2.1",
    "gpl-3.0.txt": "GNU General Public License, version 3",
}

_LGPL3 = ("lgpl-3.0.txt", "https://www.gnu.org/licenses/lgpl-3.0.txt")
_GPL3 = ("gpl-3.0.txt", "https://www.gnu.org/licenses/gpl-3.0.txt")

# Les textes que les métadonnées d'un paquet ne portent pas : {paquet: (version relevée,
# [(fichier de build/licences/, d'où il vient)], note)}. Le texte a été relu pour CETTE version :
# une autre version installée fait refuser, jusqu'à ce qu'on le relise.
COMPLEMENTS = {
    "array-api-compat": ("1.15.0", [("array-api-compat.txt", "https://github.com/data-apis/"
                                     "array-api-compat/blob/1.15/LICENSE")], None),
    "pylsl": ("1.18.6", [("pylsl.txt", "https://github.com/labstreaminglayer/pylsl/blob/"
                          "v1.18.6/LICENSE")], None),
    # pygame est sous LGPL « version 2 ou ultérieure » : il est distribué ici sous la version 3
    # (voir SOURCES_LGPL), dont les textes s'ajoutent au sien.
    "pygame": ("2.6.1", [("lgpl-2.1.txt", "https://github.com/pygame/pygame/blob/2.6.1/docs/"
                          "LGPL.txt"), _LGPL3, _GPL3],
               "The libraries pygame ships are in part 2."),
    # PySide6 et Shiboken6 sont sous LGPL v3 (ou GPL) ; leurs métadonnées ne portent que le
    # renvoi à la licence commerciale de Qt.
    "pyside6": ("6.12.0", [_LGPL3, _GPL3], None),
    "pyside6-essentials": ("6.12.0", [_LGPL3, _GPL3], None),
    "pyside6-addons": ("6.12.0", [_LGPL3, _GPL3], None),
    "pyside6-pdf": ("6.12.0.140", [_LGPL3, _GPL3], None),
    "pyside6-webengine": ("6.12.0.140", [_LGPL3, _GPL3], None),
    "shiboken6": ("6.12.0", [_LGPL3, _GPL3], None),
}

# Ce qui n'est pas une bibliothèque Python, transporté par un paquet : (titre, paquet qui le
# transporte, version de ce paquet quand le texte a été relevé, [(fichier, origine)], note).
TITRE_QT = "Qt (the libraries inside the PySide6 packages)"
AUTRES = (
    ("Unicorn C API library (Unicorn.dll), g.tec neurotechnology GmbH", "brainflow", "5.23.0",
     [("unicorn-c-api.txt", "https://github.com/brainflow-dev/brainflow/blob/master/"
       "third_party/unicorn/LICENSE")],
     "The library that talks to the Unicorn headset, shipped inside the BrainFlow package "
     "(brainflow/lib). g.tec publishes it under the MIT licence below."),
    ("liblsl (lsl.dll)", "pylsl", "1.18.6",
     [("liblsl.txt", "https://github.com/sccn/liblsl/blob/v1.18.0.b6/LICENSE")],
     "The Lab Streaming Layer library, shipped inside the pylsl package (pylsl/lib)."),
    ("Libraries shipped inside pygame (SDL 2 and its companions)", "pygame", "2.6.1",
     [("pygame.txt", None), _GPL3],   # chaque texte de pygame.txt porte sa propre adresse
     None),
    (TITRE_QT, "pyside6-essentials", "6.12.0",
     [_LGPL3, _GPL3, ("qt.txt", "https://doc.qt.io/qt-6.12/licenses-used-in-qt.html")],
     "Qt is Copyright (C) The Qt Company Ltd. and other contributors, used here under the GNU "
     "LGPL version 3, which adds to the GNU GPL version 3: both texts are in part 3. The Qt "
     "libraries are separate files in the installation folder (_internal/PySide6), which a "
     "user can replace with a modified version. The text below lists the third-party code "
     "that the Qt modules shipped here contain, FFmpeg among them, with its licences."),
)


# Les composants sous LGPL, et où trouver leur code source à la version embarquée. C'est la
# SEULE table de ces adresses : `THIRD-PARTY-NOTICES.txt` et le bloc des notes de la Release
# (`--sources-lgpl`) les lisent ici.
class SourceLGPL(NamedTuple):
    nom: str                # le composant, tel que le lit une personne qui télécharge
    role: str               # à quoi il sert dans le programme (en anglais, pour les notes)
    licence: str            # identifiant SPDX
    version: str            # la version pour laquelle les adresses ont été relevées et ouvertes
    lue_dans: str           # où lire la version EMBARQUÉE : « paquet:<nom> », ou « dll:<motif> »
                            # sous `_internal/` (la « ProductVersion » de la DLL)
    couvre: frozenset       # les clés de `composants_lgpl` qu'il couvre
    adresses: tuple         # ((ce que c'est, adresse https), …)
    sous: str = ""          # la licence sous laquelle il est distribué ici, quand la sienne
                            # (« … or later ») en laisse le choix


# Les paquets Python de Qt for Python : tous construits depuis les sources de pyside-setup.
_PAQUETS_PYSIDE = frozenset({"pyside6", "pyside6-essentials", "pyside6-addons", "pyside6-pdf",
                             "pyside6-webengine", "shiboken6"})

# Après une mise à jour de PySide6 ou de pygame, la construction refuse jusqu'à ce que ces
# adresses soient relevées pour la nouvelle version (et ouvertes une fois dans un navigateur).
# La version de FFmpeg est celle que Qt annonce sur sa page (build/licences/qt.txt, « upstream
# version ») et que ses DLL portent ; Qt la construit depuis l'archive officielle, sans la
# modifier, avec le script donné en second.
# FFmpeg et pygame sont sous LGPL « 2.1 (ou 2) ou ultérieure » : ils sont distribués ici sous la
# version 3 (`sous`), qui admet que le code source soit sur le serveur d'un tiers, pourvu que
# des indications claires accompagnent le programme (section 6 d de la GPL v3, à laquelle la
# LGPL v3 renvoie). La 2.1, elle, demande de l'offrir au même endroit que le programme.
SOURCES_LGPL = (
    SourceLGPL("Qt", "the user interface", "LGPL-3.0-only", "6.12.0",
               "dll:PySide6/Qt6Core.dll", frozenset({TITRE_QT}),
               (("source code", "https://download.qt.io/archive/qt/6.12/6.12.0/single/"
                                "qt-everywhere-src-6.12.0.tar.xz"),)),
    SourceLGPL("PySide6 and Shiboken6", "the Python binding of Qt", "LGPL-3.0-only", "6.12.0",
               "paquet:pyside6-essentials", _PAQUETS_PYSIDE,
               (("source code", "https://download.qt.io/official_releases/QtForPython/pyside6/"
                                "PySide6-6.12.0-src/pyside-setup-everywhere-src-6.12.0.tar.xz"),)),
    SourceLGPL("FFmpeg", "audio and video, inside Qt Multimedia", "LGPL-2.1-or-later", "9.0.1",
               "dll:PySide6/avcodec-*.dll", frozenset({"FFmpeg"}),
               (("source code", "https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz"),
                ("the script Qt builds it with", "https://code.qt.io/cgit/qt/qt5.git/tree/coin/"
                 "provisioning/common/windows/install-ffmpeg.ps1?h=v6.12.0")),
               sous="LGPL-3.0-or-later"),
    SourceLGPL("pygame", "the stimulus windows", "LGPL-2.1-or-later", "2.6.1",
               "paquet:pygame", frozenset({"pygame"}),
               (("source code", "https://github.com/pygame/pygame/archive/refs/tags/"
                                "2.6.1.tar.gz"),),
               sous="LGPL-3.0-or-later"),
)

# Les modules C++ de Qt que le programme embarque (`_internal/PySide6/*.dll`), et la section de
# la page « Third-Party Code Used in Qt » qui liste leur code tiers (None : aucun code tiers).
# Une DLL absente de cette table fait refuser : il faut regarder sa section sur doc.qt.io,
# l'ajouter ici, puis relancer `--rafraichir-qt`.
DLL_QT = {
    "Qt6Core.dll": "qt-core", "Qt6Gui.dll": "qt-gui", "Qt6Widgets.dll": None,
    "Qt6Network.dll": "qt-network", "Qt6Svg.dll": None, "Qt6OpenGL.dll": None,
    "Qt6OpenGLWidgets.dll": None, "Qt6Pdf.dll": "qt-pdf", "Qt6Qml.dll": "qt-qml",
    "Qt6QmlMeta.dll": "qt-qml", "Qt6QmlModels.dll": "qt-qml", "Qt6QmlWorkerScript.dll": "qt-qml",
    "Qt6Quick.dll": "qt-quick", "Qt6Multimedia.dll": "qt-multimedia",
    "Qt6MultimediaWidgets.dll": "qt-multimedia", "Qt6Test.dll": "qt-test",
    "Qt6VirtualKeyboard.dll": "qt-virtual-keyboard",
    # FFmpeg, que Qt Multimedia utilise pour le son.
    "avcodec-63.dll": "qt-multimedia", "avformat-63.dll": "qt-multimedia",
    "avutil-61.dll": "qt-multimedia", "swresample-7.dll": "qt-multimedia",
    "swscale-10.dll": "qt-multimedia",
    # Le rendu OpenGL logiciel (Mesa llvmpipe), quand la carte graphique n'a pas OpenGL.
    "opengl32sw.dll": "mesa",
    # La liaison Python de Qt, et l'environnement d'exécution de Microsoft (partie 2).
    "pyside6.abi3.dll": None, "MSVCP140.dll": None, "MSVCP140_1.dll": None,
    "MSVCP140_2.dll": None, "VCRUNTIME140.dll": None, "VCRUNTIME140_1.dll": None,
}
# Les sections de la page de Qt recopiées dans `qt.txt`. Les modules d'image (TIFF, WebP) sont
# toujours là : PyInstaller embarque les greffons d'images de Qt avec Qt GUI.
SECTIONS_QT = ("qt-core", "qt-gui", "qt-image-formats", "qt-multimedia", "qt-network", "qt-pdf",
               "qt-qml", "qt-quick", "qt-test", "qt-virtual-keyboard")
# Dans la section « Additional Information » : ce qui accompagne `opengl32sw.dll`.
PAGES_QT_EN_PLUS = {"mesa": ("qt-attribution-llvmpipe.html", "qt-attribution-llvm.html")}
PAGE_QT = "https://doc.qt.io/qt-{version}/licenses-used-in-qt.html"

NOTE_MICROSOFT = (
    "The Microsoft Visual C++ runtime files (vcruntime140*.dll, msvcp140*.dll, vcomp140.dll), "
    "shipped by Python, Qt and NumPy, are Microsoft Distributable Code, redistributed under the "
    "Microsoft Visual Studio licence terms. See \"Additional Conditions for this Windows binary "
    "build\" in the Python licence above.")


class Refus(Exception):
    """Un composant embarqué dont on ne sait pas citer la licence : on n'écrit rien."""


# ------------------------------------------------------------------------------ les paquets ----
def normaliser(nom: str) -> str:
    """Le nom d'un paquet tel que pip le compare : casse et « - _ . » ignorés."""
    return re.sub(r"[-_.]+", "-", nom).lower()


def lire_contraintes(texte: str) -> dict[str, tuple[str, str]]:
    """{nom normalisé: (nom écrit, version)} pour chaque ligne « nom==version »."""
    paquets = {}
    for ligne in texte.splitlines():
        ligne = ligne.split("#", 1)[0].strip()
        if "==" in ligne:
            nom, version = (x.strip() for x in ligne.split("==", 1))
            paquets[normaliser(nom)] = (nom, version)
    return paquets


def _dossier_metadonnees(dist) -> str | None:
    """Le nom du dossier `*.dist-info` du paquet (celui qui contient son METADATA)."""
    for f in dist.files or ():
        parties = Path(str(f)).parts
        if len(parties) == 2 and parties[1] == "METADATA" and parties[0].endswith(".dist-info"):
            return parties[0]
    return None


_NOM_DE_LICENCE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.IGNORECASE)


def textes_du_paquet(dist) -> list[tuple[str, str]]:
    """[(étiquette, texte)] : les fichiers de licence que le paquet installé contient.

    D'abord ceux que ses métadonnées déclarent (`License-File`, rangés sous `licenses/` depuis la
    version 2.4 des métadonnées, à la racine du dossier avant), puis tout fichier LICENSE*,
    COPYING*, NOTICE*, AUTHORS* de son dossier de métadonnées. Les dossiers de métadonnées des
    paquets qu'il contient lui-même (setuptools en range plusieurs) ne comptent pas."""
    dossier = _dossier_metadonnees(dist) or f"{dist.metadata['Name']}.dist-info"
    textes, vus = [], set()

    def ajouter(relatif):
        relatif = relatif.replace("\\", "/")
        if relatif in vus:
            return
        texte = dist.read_text(relatif)
        if texte is not None and texte.strip():
            vus.add(relatif)
            textes.append((f"{dossier}/{relatif}", texte))

    for declare in dist.metadata.get_all("License-File") or ():
        for relatif in (f"licenses/{declare}", declare):
            if dist.read_text(relatif) is not None:
                ajouter(relatif)
                break
    for f in dist.files or ():
        parties = Path(str(f)).parts
        if len(parties) >= 2 and parties[0] == dossier and _NOM_DE_LICENCE.match(parties[-1]):
            ajouter("/".join(parties[1:]))
    return textes


def expression_de_licence(meta: email.message.Message) -> str:
    """La licence en une ligne : `License-Expression`, sinon le champ `License` s'il est court,
    sinon les classificateurs « License :: … »."""
    if meta.get("License-Expression"):
        return meta["License-Expression"].strip()
    champ = (meta.get("License") or "").strip()
    if champ and "\n" not in champ and len(champ) <= 80:
        return champ
    classes = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or ()
               if c.startswith("License ::")]
    return " / ".join(classes) or "see the text below"


def adresse_du_projet(meta: email.message.Message) -> str | None:
    if meta.get("Home-page"):
        return meta["Home-page"].strip()
    for url in meta.get_all("Project-URL") or ():
        etiquette, _, adresse = url.partition(",")
        if etiquette.strip().lower() in ("homepage", "home", "source", "repository", "source code"):
            return adresse.strip()
    return None


def paquets_embarques(contraintes: dict, installes: dict) -> list:
    """Les paquets à citer, triés par nom ; lève `Refus` sur toute incohérence.

    `installes` : {nom normalisé: Distribution} de l'environnement qui a construit."""
    erreurs = []
    for nom, dist in sorted(installes.items()):
        if nom not in contraintes and nom not in OUTILS_DE_CONSTRUCTION | TOUJOURS_LA:
            erreurs.append(f"{dist.metadata['Name']} {dist.version} est installé mais absent de "
                           f"{CONTRAINTES.name} : il peut être embarqué sans être cité "
                           "(refaire contraintes.txt, voir son en-tête)")
    paquets = []
    for nom, (ecrit, version) in sorted(contraintes.items()):
        if nom in OUTILS_DE_CONSTRUCTION:
            continue
        dist = installes.get(nom)
        if dist is None:
            erreurs.append(f"{ecrit} : dans {CONTRAINTES.name}, mais pas installé")
        elif dist.version != version:
            erreurs.append(f"{ecrit} : {dist.version} installé, {version} dans {CONTRAINTES.name}")
        else:
            paquets.append(dist)
    if erreurs:
        raise Refus("\n".join(erreurs))
    return paquets


# --------------------------------------------------------------- les textes du dépôt ----
def texte_du_depot(fichier: str, dossier: Path = LICENCES) -> str:
    chemin = dossier / fichier
    if not chemin.is_file():
        raise Refus(f"{chemin} manque : ce texte de licence est gardé dans le dépôt")
    texte = chemin.read_text(encoding="utf-8")
    if not texte.strip():
        raise Refus(f"{chemin} est vide")
    return texte


def verifier_version_relevee(quoi: str, paquet: str, relevee: str, installes: dict) -> None:
    dist = installes.get(paquet)
    if dist is None:
        raise Refus(f"{quoi} : le paquet {paquet} qui le transporte n'est pas installé")
    if dist.version != relevee:
        raise Refus(f"{quoi} : texte relevé pour {paquet} {relevee}, {dist.version} installé. "
                    f"Relire la licence de cette version, mettre build/licences/ à jour, puis "
                    f"la version dans licences_tierces.py")


def lire_entete_qt(texte: str) -> tuple[str, set[str]]:
    """(version de Qt, sections recopiées), lues dans l'en-tête de `qt.txt`."""
    version = re.search(r"^Qt version: (\S+)$", texte, re.MULTILINE)
    sections = re.search(r"^Sections: (.+)$", texte, re.MULTILINE)
    if not version or not sections:
        raise Refus("build/licences/qt.txt n'a pas son en-tête (Qt version, Sections) : "
                    "le refaire avec --rafraichir-qt")
    return version.group(1), {s.strip() for s in sections.group(1).split(",")}


# ------------------------------------------------------------ le programme construit ----
def binaires(dossier_app: Path) -> list[Path]:
    """Les DLL et modules natifs (.pyd) du programme construit."""
    return sorted(p for p in dossier_app.rglob("*") if p.suffix.lower() in (".dll", ".pyd"))


def provenances(installes: dict, base_python: Path) -> dict[str, str]:
    """{nom de fichier en minuscules: d'où il vient} pour tout binaire qu'un paquet installé ou
    Python fournit. Le nom suffit : PyInstaller ne renomme pas les DLL qu'il recopie."""
    connus = {}
    for nom, dist in installes.items():
        for f in dist.files or ():
            if str(f).lower().endswith((".dll", ".pyd")):
                connus.setdefault(Path(str(f)).name.lower(), dist.metadata["Name"])
    for p in list(base_python.glob("*.dll")) + list((base_python / "DLLs").glob("*")):
        if p.suffix.lower() in (".dll", ".pyd"):
            connus.setdefault(p.name.lower(), "Python")
    return connus


def binaires_inconnus(dossier_app: Path, connus: dict[str, str]) -> list[str]:
    return [str(p.relative_to(dossier_app)) for p in binaires(dossier_app)
            if p.name.lower() not in connus]


def sections_qt_requises(dossier_app: Path) -> tuple[set[str], list[str]]:
    """(sections de la page de Qt à citer, DLL de Qt inconnues de `DLL_QT`)."""
    requises, inconnues = set(), []
    connues = {n.lower(): s for n, s in DLL_QT.items()}
    dossier_qt = dossier_app / "_internal" / "PySide6"
    for dll in sorted(dossier_qt.glob("*.dll")):
        if dll.name.lower() not in connues:
            inconnues.append(dll.name)
        elif connues[dll.name.lower()]:
            requises.add(connues[dll.name.lower()])
    if (dossier_qt / "plugins" / "imageformats").is_dir():
        requises.add("qt-image-formats")
    return requises, inconnues


# ------------------------------------------------------------------- les sources LGPL ----
def _est_lgpl(licence: str) -> bool:
    return "LGPL" in licence.upper() or "LESSER" in licence.upper()


def lgpl_de_qt(texte_qt: str) -> set[str]:
    """Les composants sous LGPL que `qt.txt` cite : chaque titre « Nom, version X (licence) »
    encadré de deux filets, dont la licence est une LGPL. Le nom est rendu sans la version."""
    noms = set()
    for titre in re.findall(r"^-{78}\n([^\n]+)\n-{78}$", texte_qt, re.MULTILINE):
        m = re.match(r"(.+?)(?:, version \S+)? \((.*)\)$", titre)
        if m and _est_lgpl(m.group(2)):
            noms.add(m.group(1))
    return noms


def composants_lgpl(paquets: list, licences: Path = LICENCES) -> dict[str, str]:
    """{clé: ce qui le dit} : chaque composant sous LGPL de ce que THIRD-PARTY-NOTICES.txt cite.

    Lu sans `SOURCES_LGPL`, pour qu'un composant qui y manque se voie : la licence d'un paquet
    Python (ses métadonnées, ou un texte LGPL de `COMPLEMENTS`), une entrée d'`AUTRES` qui cite
    un texte LGPL, et les composants que `qt.txt` dit sous LGPL. La clé : le nom normalisé du
    paquet, le titre de l'entrée d'`AUTRES`, ou le nom du composant de `qt.txt`."""
    trouves = {}
    for dist in paquets:
        nom = normaliser(dist.metadata["Name"])
        licence = expression_de_licence(dist.metadata)
        textes = [f for f, _o in COMPLEMENTS.get(nom, (None, [], None))[1]]
        if _est_lgpl(licence) or any(f.startswith("lgpl") for f in textes):
            trouves[nom] = f"{dist.metadata['Name']} {dist.version} ({licence})"
    for titre, _paquet, _v, fichiers, _note in AUTRES:
        noms = [f for f, _o in fichiers]
        if any(f.startswith("lgpl") for f in noms):
            trouves[titre] = titre
        if "qt.txt" in noms:
            for composant in lgpl_de_qt(texte_du_depot("qt.txt", licences)):
                trouves[composant] = f"{composant} (build/licences/qt.txt)"
    return trouves


def version_de_dll(chemin: Path) -> str:
    """La « ProductVersion » des ressources d'une DLL de Windows, sans les « .0 » au-delà de trois
    nombres (Qt écrit 6.12.0.0). Lue avec pefile, que PyInstaller installe avec lui."""
    try:
        import pefile
    except ImportError:
        raise Refus("pefile manque dans ce Python : il s'installe avec PyInstaller "
                    "(pip install pyinstaller==… -c build/contraintes.txt)") from None
    pe = pefile.PE(str(chemin), fast_load=True)
    try:
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        for info in getattr(pe, "FileInfo", None) or ():
            for bloc in info:
                for table in getattr(bloc, "StringTable", None) or ():
                    brute = table.entries.get(b"ProductVersion")
                    if brute:
                        nombres = brute.decode("utf-8", "replace").strip().split(".")
                        while len(nombres) > 3 and nombres[-1] == "0":
                            nombres.pop()
                        return ".".join(nombres)
    finally:
        pe.close()
    raise Refus(f"{chemin} ne dit pas sa version (pas de ProductVersion dans ses ressources)")


def version_embarquee(source: SourceLGPL, dossier_app: Path, installes: dict,
                      lire_dll=version_de_dll) -> str:
    """La version de `source` que le programme construit contient (voir `SourceLGPL.lue_dans`)."""
    genre, _, quoi = source.lue_dans.partition(":")
    if genre == "paquet":
        dist = installes.get(quoi)
        if dist is None:
            raise Refus(f"{source.nom} : le paquet {quoi} n'est pas installé (SOURCES_LGPL)")
        return dist.version
    if genre == "dll":
        dll = sorted((dossier_app / "_internal").glob(quoi))
        if not dll:
            raise Refus(f"{source.nom} : aucune DLL « {quoi} » sous _internal/ du programme "
                        "construit. S'il n'est plus embarqué, retirer son entrée de SOURCES_LGPL")
        versions = {lire_dll(d) for d in dll}
        if len(versions) != 1:
            raise Refus(f"{source.nom} : ses DLL ne disent pas la même version "
                        f"({', '.join(sorted(versions))})")
        return versions.pop()
    raise Refus(f"{source.nom} : « {source.lue_dans} » n'est ni « paquet:… » ni « dll:… »")


def verifier_sources_lgpl(paquets: list, dossier_app: Path, installes: dict,
                          licences: Path = LICENCES, sources=None,
                          lire_dll=version_de_dll) -> list[SourceLGPL]:
    """Les entrées de `SOURCES_LGPL`, après avoir vérifié qu'elles couvrent CHAQUE composant sous
    LGPL du programme construit, à la version embarquée, avec des adresses https. Lève `Refus`."""
    sources = SOURCES_LGPL if sources is None else sources
    trouves = composants_lgpl(paquets, licences)
    couverts = set().union(*(s.couvre for s in sources)) if sources else set()
    erreurs = [f"{trouves[c]} est sous LGPL, mais aucune entrée de SOURCES_LGPL ne dit où trouver "
               "son code source" for c in sorted(set(trouves) - couverts)]
    for s in sources:
        if not s.couvre & set(trouves):
            erreurs.append(f"{s.nom} : aucun des composants qu'il couvre n'est cité "
                           f"({', '.join(sorted(s.couvre))}) : clé mal écrite, ou entrée à "
                           "retirer")
            continue
        if not s.adresses or any(not a.startswith("https://") for _q, a in s.adresses):
            erreurs.append(f"{s.nom} : il faut au moins une adresse, et toutes en https://")
        embarquee = version_embarquee(s, dossier_app, installes, lire_dll)
        if embarquee != s.version:
            erreurs.append(f"{s.nom} : adresses relevées pour la version {s.version}, la "
                           f"{embarquee} est embarquée. Trouver le code source de la {embarquee}, "
                           "ouvrir ses adresses, puis mettre SOURCES_LGPL à jour")
    if erreurs:
        raise Refus("\n".join(erreurs))
    return list(sources)


def ligne_des_sources(source: SourceLGPL) -> str:
    """La phrase de THIRD-PARTY-NOTICES.txt qui dit où trouver le code source d'un composant.
    Sans point final : il se collerait à l'adresse quand on la copie."""
    adresses = [a if quoi == "source code" else f"{a} ({quoi})" for quoi, a in source.adresses]
    return (f"Source code of {source.nom} {source.version} ({_licence_dite(source)}): "
            + ", and ".join(adresses))


def _licence_dite(source: SourceLGPL) -> str:
    if source.sous:
        return f"{source.licence}, distributed here under {source.sous}"
    return source.licence


def bloc_sources_lgpl(sources: list[SourceLGPL]) -> str:
    """Le bloc Markdown des notes de la Release : chaque composant sous LGPL, sa version, sa
    licence et l'adresse de son code source."""
    lignes = ["### Source code of the LGPL components", "",
              "The installer contains these libraries, licensed under the GNU Lesser General "
              "Public License (LGPL). Their complete source code, at the exact version shipped, "
              "is available at these addresses:", ""]
    for s in sources:
        adresses = "; ".join(f"{quoi}: <{a}>" for quoi, a in s.adresses)
        lignes.append(f"- **{s.nom} {s.version}** ({_licence_dite(s)}), {s.role}. "
                      f"{adresses[0].upper()}{adresses[1:]}")
    lignes += ["", "Their licence texts, and those of every other library in the installer, are "
               f"in `{NOM_FICHIER}`, in the installation folder."]
    return "\n".join(lignes) + "\n"


def defauts_du_bloc(bloc: str, attendus: list[tuple[str, str]]) -> list[str]:
    """Les composants (nom, version) que le bloc ne nomme pas sur une ligne de liste avec leur
    version ET une adresse https. Fonction PURE."""
    fautes = []
    for nom, version in attendus:
        lignes = [ligne for ligne in bloc.splitlines()
                  if ligne.startswith(f"- **{nom} {version}**")]
        if not lignes:
            fautes.append(f"{nom} {version} : absent du bloc")
        elif not any(re.search(r"<https://[^\s>]+>", ligne) for ligne in lignes):
            fautes.append(f"{nom} {version} : aucune adresse https")
    return fautes


# ------------------------------------------------------------------------ l'écriture ----
TRAIT = "=" * 78
FILET = "-" * 78


def _ligne(texte: str) -> str:
    """Un paragraphe écrit par ce script, coupé à la largeur du fichier."""
    return textwrap.fill(texte, width=len(TRAIT), break_long_words=False,
                         break_on_hyphens=False)


def _propre(texte: str) -> str:
    return texte.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def composer(version_produit: str, paquets: list, base_python: Path, installes: dict,
             dossier_app: Path | None, licences: Path = LICENCES) -> str:
    """Le contenu de THIRD-PARTY-NOTICES.txt. Lève `Refus` au premier manque."""
    partages = []                       # les textes de la partie 3, dans l'ordre de leur appel

    def renvoi(fichier):
        if fichier not in partages:
            partages.append(fichier)
        return f"[Full text: {TEXTES_PARTAGES[fichier]}, in part 3.]"

    def bloc_du_depot(fichier, origine):
        if fichier in TEXTES_PARTAGES:
            texte_du_depot(fichier, licences)       # il doit exister
            return [renvoi(fichier)]
        entete = [f"[From {origine}]", ""] if origine else []
        return entete + [_propre(texte_du_depot(fichier, licences))]

    def sources_de(cles):
        """Les phrases « Source code of … » des composants sous LGPL que ces clés désignent."""
        return [_ligne(ligne_des_sources(s)) for s in SOURCES_LGPL if s.couvre & set(cles)]

    noms_lgpl = [s.nom for s in SOURCES_LGPL]
    sortie = [
        f"EEG API Unicorn {version_produit}: third-party notices",
        TRAIT,
        "",
        "EEG API Unicorn is Copyright (c) 2026 medkar, licensed under the MIT License (see",
        "LICENSE).",
        "",
        "This installation also contains software written by others. This file lists it and",
        "reproduces the licence notices that come with it:",
        "",
        "  Part 1. The Python packages the program was built with",
        "  Part 2. Other components (Python itself, and native libraries the packages carry)",
        "  Part 3. Licence texts referred to in parts 1 and 2",
        "",
    ]
    if noms_lgpl:
        sortie += [_ligne(
            "Some of these components are licensed under the GNU Lesser General Public License "
            f"(LGPL): {', '.join(noms_lgpl[:-1])}{' and ' if len(noms_lgpl) > 1 else ''}"
            f"{noms_lgpl[-1]}. The address of their source code, at the exact version shipped, "
            "is given with each of them below, and in the notes of each release: "
            f"{DEPOT_PUBLIC}/releases"), ""]
    sortie += [
        _ligne(f"This file is generated when the program is built, by build/licences_tierces.py "
               f"in {DEPOT_PUBLIC}."),
        "",
        "",
        TRAIT,
        f"PART 1. THE PYTHON PACKAGES ({len(paquets)})",
        TRAIT,
    ]
    sans_texte = []
    for dist in paquets:
        nom = normaliser(dist.metadata["Name"])
        textes = textes_du_paquet(dist)
        complement = COMPLEMENTS.get(nom)
        if not textes and not complement:
            sans_texte.append(f"{dist.metadata['Name']} {dist.version}")
            continue
        sortie += ["", "", FILET, f"{dist.metadata['Name']} {dist.version}",
                   f"License: {expression_de_licence(dist.metadata)}"]
        adresse = adresse_du_projet(dist.metadata)
        if adresse:
            sortie.append(f"Project: {adresse}")
        sortie.append(FILET)
        for etiquette, texte in textes:
            sortie += ["", f"[{etiquette}]", "", _propre(texte)]
        if complement:
            relevee, fichiers, note = complement
            verifier_version_relevee(f"build/licences/ pour {dist.metadata['Name']}", nom,
                                     relevee, installes)
            for fichier, origine in fichiers:
                sortie += [""] + bloc_du_depot(fichier, origine)
            if note:
                sortie += ["", _ligne(note)]
        for ligne in sources_de({nom}):
            sortie += ["", ligne]
    if sans_texte:
        raise Refus("aucun texte de licence (ni dans ses métadonnées, ni dans build/licences/) "
                    "pour : " + ", ".join(sans_texte))

    # Partie 2 : Python, puis ce que les paquets transportent.
    licence_python = base_python / "LICENSE.txt"
    if not licence_python.is_file():
        raise Refus(f"{licence_python} manque : la licence de Python n'est pas là où un Python "
                    "pour Windows la range")
    autres = [(f"Python {sys.version.split()[0]} (the interpreter and its standard library)",
               [("", [f"[{licence_python.name} of the Python installation that built the "
                          "program]", "", _propre(licence_python.read_text(encoding="utf-8"))])],
               "Its last part covers the Microsoft runtime and libraries that the Windows build "
               "of Python contains (bzip2, libffi, OpenSSL, Tcl/Tk). The Python documentation "
               "lists the licences of all the software Python incorporates: "
               f"https://docs.python.org/{sys.version_info[0]}.{sys.version_info[1]}/license.html"
               "#licenses-and-acknowledgements-for-incorporated-software", [])]
    for titre, paquet, relevee, fichiers, note in AUTRES:
        verifier_version_relevee(titre, paquet, relevee, installes)
        if dossier_app is not None and paquet == "pyside6-essentials":
            version_qt, sections = lire_entete_qt(texte_du_depot("qt.txt", licences))
            if version_qt != relevee:
                raise Refus(f"build/licences/qt.txt décrit Qt {version_qt}, PySide6 {relevee} est "
                            "embarqué : le refaire avec --rafraichir-qt")
            requises, inconnues = sections_qt_requises(dossier_app)
            if inconnues:
                raise Refus("DLL de Qt inconnues de DLL_QT (licences_tierces.py) : "
                            + ", ".join(inconnues) + ". Chercher leur module sur la page "
                            + PAGE_QT.format(version="6") + ", l'ajouter à DLL_QT et à "
                            "SECTIONS_QT, puis relancer --rafraichir-qt")
            manquantes = requises - sections
            if manquantes:
                raise Refus("build/licences/qt.txt ne recopie pas ces sections de la page de Qt : "
                            + ", ".join(sorted(manquantes)) + " (relancer --rafraichir-qt)")
        cles = {titre}
        if any(f == "qt.txt" for f, _o in fichiers):
            cles |= lgpl_de_qt(texte_du_depot("qt.txt", licences))
        autres.append((titre, [(f, bloc_du_depot(f, o)) for f, o in fichiers], note,
                       sources_de(cles)))
    sortie += ["", "", TRAIT, f"PART 2. OTHER COMPONENTS ({len(autres) + 1})", TRAIT]
    for titre, blocs, note, sources in autres:
        sortie += ["", "", FILET, titre, FILET]
        if note:
            sortie += ["", _ligne(note)]
        for ligne in sources:
            sortie += ["", ligne]
        for _fichier, lignes in blocs:
            sortie += [""] + lignes
    sortie += ["", "", FILET, "Microsoft Visual C++ runtime", FILET, "",
               _ligne(NOTE_MICROSOFT)]

    sortie += ["", "", TRAIT, "PART 3. LICENCE TEXTS REFERRED TO ABOVE", TRAIT]
    for fichier in partages:
        sortie += ["", "", FILET, TEXTES_PARTAGES[fichier], FILET, "",
                   _propre(texte_du_depot(fichier, licences))]
    return "\n".join(sortie) + "\n"


def distributions_installees() -> dict:
    """{nom normalisé: Distribution} de ce Python. Le premier trouvé sur `sys.path` gagne,
    comme à l'import."""
    installes = {}
    for dist in metadata.distributions():
        nom = dist.metadata["Name"]
        if nom:
            installes.setdefault(normaliser(nom), dist)
    return installes


def _paquets_du_programme(dossier_app: Path) -> tuple[dict, list]:
    """(paquets installés, paquets embarqués) pour le programme construit `dossier_app`."""
    if not dossier_app.is_dir():
        raise Refus(f"{dossier_app} n'existe pas : lancer PyInstaller d'abord")
    installes = distributions_installees()
    paquets = paquets_embarques(lire_contraintes(CONTRAINTES.read_text(encoding="utf-8")),
                                installes)
    return installes, paquets


def ecrire(dossier_app: Path) -> Path:
    """Vérifie tout, puis écrit `<dossier_app>/THIRD-PARTY-NOTICES.txt`."""
    installes, paquets = _paquets_du_programme(dossier_app)
    sys.path.insert(0, str(RACINE / "src"))
    from core.version import VERSION
    base_python = Path(sys.base_prefix)
    inconnus = binaires_inconnus(dossier_app, provenances(installes, base_python))
    if inconnus:
        raise Refus("binaires du programme construit qui ne viennent d'aucun paquet installé "
                    "ni de Python (leur licence est inconnue) : " + ", ".join(inconnus))
    # Les phrases « Source code of … » viennent de SOURCES_LGPL : elles doivent valoir pour les
    # versions embarquées.
    verifier_sources_lgpl(paquets, dossier_app, installes)
    contenu = composer(VERSION, paquets, base_python, installes, dossier_app)
    cible = dossier_app / NOM_FICHIER
    cible.write_text(contenu, encoding="utf-8", newline="\r\n")
    print(f"{cible} : {len(paquets)} paquets Python, {len(AUTRES) + 2} autres composants, "
          f"{len(contenu.encode('utf-8')) // 1024} Ko")
    return cible


def ecrire_sources_lgpl(dossier_app: Path, fichier: Path) -> Path:
    """Vérifie que SOURCES_LGPL couvre chaque composant sous LGPL du programme construit, à sa
    version, puis écrit le bloc Markdown des notes de la Release dans `fichier`."""
    installes, paquets = _paquets_du_programme(dossier_app)
    sources = verifier_sources_lgpl(paquets, dossier_app, installes)
    bloc = bloc_sources_lgpl(sources)
    fautes = defauts_du_bloc(bloc, [(s.nom, s.version) for s in sources])
    if fautes:
        raise Refus("le bloc des sources LGPL est incomplet : " + "; ".join(fautes))
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(bloc, encoding="utf-8", newline="\n")
    print(f"{fichier} : " + ", ".join(f"{s.nom} {s.version}" for s in sources))
    return fichier


# ------------------------------------------------------------- relever les textes de Qt ----
def _telecharger(url: str) -> str:
    requete = urllib.request.Request(url, headers={"User-Agent": "licences_tierces.py"})
    with urllib.request.urlopen(requete, timeout=60) as reponse:
        return reponse.read().decode("utf-8")


def _en_texte(fragment: str) -> str:
    """Le texte d'un morceau de page de la documentation de Qt : les blocs <pre> tels quels (les
    licences), les paragraphes en lignes. Certaines pages échappent deux fois (« &amp;quot; »)."""
    def sans_balises(s):
        return html.unescape(html.unescape(re.sub(r"<[^>]+>", "", s)))
    morceaux = []
    for bout in re.split(r"(<pre[^>]*>.*?</pre>)", fragment, flags=re.DOTALL):
        if bout.startswith("<pre"):
            morceaux.append(sans_balises(bout).strip("\n"))
            continue
        # Le lien de la version amont mène à une archive à télécharger, sans rien de juridique :
        # on garde le numéro, pas l'adresse.
        bout = re.sub(r"(upstream version: )<a [^>]*>(.*?)</a>", r"\1\2", bout, flags=re.DOTALL)
        bout = re.sub(r'<a [^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', r"\2 (\1)", bout,
                      flags=re.DOTALL)
        bout = re.sub(r"<li[^>]*>", "- ", bout)
        bout = re.sub(r"</p>|<br\s*/?>|</li>|</h\d>", "\n", bout)
        for ligne in sans_balises(bout).split("\n"):
            ligne = " ".join(ligne.split())
            if ligne:
                morceaux.append(ligne)
    return "\n\n".join(morceaux)


def _page_de_composant(url: str) -> tuple[str, str]:
    page = _telecharger(url)
    titre = re.search(r'<h1 class="title"[^>]*>(.*?)</h1>', page, re.DOTALL)
    corps = re.search(r'<div class="descr" id="details">(.*?)<!-- @@@', page, re.DOTALL)
    if not titre or not corps:
        raise Refus(f"page de Qt illisible (titre ou texte introuvable) : {url}")
    return _en_texte(titre.group(1)), _en_texte(corps.group(1))


def rafraichir_qt(version_qt: str) -> Path:
    """Relève sur doc.qt.io le code tiers des modules de Qt embarqués, dans build/licences/qt.txt.

    Geste de poste de développement (réseau), après une mise à jour de PySide6 : la construction,
    elle, ne lit que le fichier du dépôt."""
    majeure_mineure = ".".join(version_qt.split(".")[:2])
    adresse = PAGE_QT.format(version=majeure_mineure)
    page = _telecharger(adresse)
    annoncee = re.search(r"third-party components in Qt (\d+\.\d+\.\d+)", page)
    if not annoncee or annoncee.group(1) != version_qt:
        raise Refus(f"{adresse} décrit Qt {annoncee.group(1) if annoncee else '?'}, "
                    f"pas Qt {version_qt}")
    morceaux = re.split(r'<h2 id="([^"]+)">', page)
    sections = {morceaux[i]: morceaux[i + 1] for i in range(1, len(morceaux) - 1, 2)}
    lignes = [f"Qt {version_qt}: third-party code in the Qt modules shipped with EEG API Unicorn",
              "", f"Qt version: {version_qt}",
              "Sections: " + ", ".join(SECTIONS_QT + tuple(PAGES_QT_EN_PLUS)),
              f"From: {adresse} and the pages it links to.",
              "Each entry: the component, its licence as Qt names it, then the text of its page."]
    for section in SECTIONS_QT:
        if section not in sections:
            raise Refus(f"la section {section} manque sur {adresse}")
        corps = sections[section]
        nom = _en_texte(corps.split("</h2>", 1)[0]) or section
        lignes += ["", "", "=" * 78, nom, "=" * 78]
        for lien, _composant, licence in re.findall(
                r'<a href="([^"]+)">([^<]+)</a></p></td><td class="tblDescr"><p>(.*?)</p>', corps):
            titre, texte = _page_de_composant(urllib.parse.urljoin(adresse, lien))
            lignes += ["", "-" * 78, f"{titre} ({_en_texte(licence)})", "-" * 78, "", texte]
            print(f"  {nom} : {titre}")
    for cle, pages in PAGES_QT_EN_PLUS.items():
        lignes += ["", "", "=" * 78, f"Additional information ({cle})", "=" * 78]
        for lien in pages:
            titre, texte = _page_de_composant(urllib.parse.urljoin(adresse, lien))
            lignes += ["", "-" * 78, titre, "-" * 78, "", texte]
            print(f"  {cle} : {titre}")
    cible = LICENCES / "qt.txt"
    cible.write_text("\n".join(lignes) + "\n", encoding="utf-8", newline="\n")
    print(f"{cible} : {cible.stat().st_size // 1024} Ko")
    return cible


# --------------------------------------------------------------------------- autotest ----
def _faux_paquet(racine: Path, nom: str, version: str, metadonnees: str = "",
                 fichiers: dict[str, str] | None = None, binaires_: tuple[str, ...] = ()):
    """Fabrique un paquet installé (un dossier .dist-info avec METADATA et RECORD) et rend sa
    Distribution, lue par importlib.metadata comme une vraie."""
    dossier = racine / f"{nom.replace('-', '_')}-{version}.dist-info"
    dossier.mkdir(parents=True)
    (dossier / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: {nom}\nVersion: {version}\n{metadonnees}", encoding="utf-8")
    record = [f"{dossier.name}/METADATA,,", f"{dossier.name}/RECORD,,"]
    for relatif, texte in (fichiers or {}).items():
        chemin = racine / relatif
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(texte, encoding="utf-8")
        record.append(f"{relatif},,")
    for relatif in binaires_:           # `files` ne rend que les fichiers qui existent
        (racine / relatif).parent.mkdir(parents=True, exist_ok=True)
        (racine / relatif).write_bytes(b"")
        record.append(f"{relatif},,")
    (dossier / "RECORD").write_text("\n".join(record) + "\n", encoding="utf-8")
    return metadata.PathDistribution(dossier)


def autotest() -> int:
    echecs = []

    def chk(condition, message):
        print(f"  [{'ok' if condition else 'ÉCHEC'}] {message}")
        if not condition:
            echecs.append(message)

    def refuse(appel, *mots):
        try:
            appel()
        except Refus as e:
            return all(m in str(e) for m in mots)
        return False

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        site = tmp / "site"
        # Un paquet récent : la licence déclarée est rangée sous licenses/.
        moderne = _faux_paquet(site, "moderne", "1.0", "License-Expression: MIT\n"
                               "License-File: LICENSE\n",
                               {"moderne-1.0.dist-info/licenses/LICENSE": "MIT moderne\n"})
        # Un paquet ancien : LICENSE à la racine du dossier, sans License-File, plus un AUTHORS.
        ancien = _faux_paquet(site, "ancien", "2.0", "License: BSD-3-Clause\n",
                              {"ancien-2.0.dist-info/LICENSE.txt": "BSD ancien\n",
                               "ancien-2.0.dist-info/AUTHORS": "A. Auteur\n"})
        # Un paquet qui en contient un autre (setuptools range ainsi ses paquets internes).
        hote = _faux_paquet(site, "hote", "3.0", "License-File: LICENSE\n",
                            {"hote-3.0.dist-info/licenses/LICENSE": "hote\n",
                             "hote/_vendor/autre-1.0.dist-info/LICENSE": "autre\n"})
        muet = _faux_paquet(site, "muet", "0.1", "License: MIT\n", {}, ("muet/muet.dll",))

        t = textes_du_paquet(moderne)
        chk([e for e, _ in t] == ["moderne-1.0.dist-info/licenses/LICENSE"],
            f"License-File rangé sous licenses/ : lu ({[e for e, _ in t]})")
        t = textes_du_paquet(ancien)
        chk(sorted(e for e, _ in t) == ["ancien-2.0.dist-info/AUTHORS",
                                        "ancien-2.0.dist-info/LICENSE.txt"],
            f"sans License-File : LICENSE* et AUTHORS du dossier lus ({[e for e, _ in t]})")
        t = textes_du_paquet(hote)
        chk([x for _, x in t] == ["hote\n"],
            "les métadonnées d'un paquet CONTENU par un autre ne comptent pas pour lui")
        chk(textes_du_paquet(muet) == [], "un paquet sans fichier de licence : aucun texte")
        chk(expression_de_licence(moderne.metadata) == "MIT"
            and expression_de_licence(ancien.metadata) == "BSD-3-Clause",
            "la licence en une ligne : License-Expression, sinon License")

        contraintes = lire_contraintes("# en-tête\nmoderne==1.0\nAncien==2.0\npyinstaller==6\n")
        chk(set(contraintes) == {"moderne", "ancien", "pyinstaller"},
            f"contraintes.txt lu, commentaires ignorés ({sorted(contraintes)})")
        installes = {"moderne": moderne, "ancien": ancien, "pip": muet}
        chk([d.metadata["Name"] for d in paquets_embarques(contraintes, installes)]
            == ["ancien", "moderne"], "les outils de construction et pip ne sont pas cités")
        chk(refuse(lambda: paquets_embarques(contraintes, {**installes, "muet": muet}),
                   "muet 0.1", "absent de contraintes.txt"),
            "un paquet installé hors de contraintes.txt : refusé, nommé")
        chk(refuse(lambda: paquets_embarques({**contraintes, "moderne": ("moderne", "1.1")},
                                             installes), "moderne", "1.0 installé", "1.1"),
            "une version installée autre que celle de contraintes.txt : refusée")

        licences = tmp / "licences"
        licences.mkdir()
        (licences / "lgpl-2.1.txt").write_text("LGPL 2.1\n", encoding="utf-8")
        base = tmp / "python"
        (base / "DLLs").mkdir(parents=True)
        (base / "LICENSE.txt").write_text("PSF\n", encoding="utf-8")
        (base / "python313.dll").write_text("", encoding="utf-8")
        global AUTRES, COMPLEMENTS, SOURCES_LGPL
        sauve = AUTRES, COMPLEMENTS
        try:
            AUTRES, COMPLEMENTS = (), {}
            texte = composer("9.9", [ancien, moderne], base, installes, None, licences)
            chk("ancien 2.0" in texte and "BSD ancien" in texte and "MIT moderne" in texte
                and "PSF" in texte, "le fichier cite chaque paquet, son texte, et Python")
            chk(refuse(lambda: composer("9.9", [moderne, muet], base, installes, None, licences),
                       "muet 0.1"),
                "un paquet embarqué sans AUCUN texte de licence : refusé, nommé")
            COMPLEMENTS = {"muet": ("0.1", [("muet.txt", "x")], None)}
            chk(refuse(lambda: composer("9.9", [muet], base, {"muet": muet}, None, licences),
                       "muet.txt manque"),
                "un texte gardé dans build/licences/ qui manque : refusé, nommé")
            (licences / "muet.txt").write_text("texte du muet\n", encoding="utf-8")
            chk("texte du muet" in composer("9.9", [muet], base, {"muet": muet}, None,
                                            licences),
                "un paquet sans licence dans ses métadonnées : le texte du dépôt le couvre")
            COMPLEMENTS = {"muet": ("0.2", [("muet.txt", "x")], None)}
            chk(refuse(lambda: composer("9.9", [muet], base, {"muet": muet}, None, licences),
                       "relevé pour muet 0.2", "0.1 installé"),
                "un texte du dépôt relevé pour une autre version : refusé")
            COMPLEMENTS = {"muet": ("0.1", [("lgpl-2.1.txt", "x")], None),
                           "ancien": ("2.0", [("lgpl-2.1.txt", "x")], None)}
            texte = composer("9.9", [ancien, muet], base, {"muet": muet, "ancien": ancien},
                             None, licences)
            chk(texte.count("LGPL 2.1") == 1 and texte.count("[Full text: GNU Lesser") == 2,
                "un texte partagé : écrit une fois en partie 3, appelé par chacun")
        finally:
            AUTRES, COMPLEMENTS = sauve

        # Le programme construit : chaque binaire doit venir d'un paquet ou de Python.
        app = tmp / "app"
        (app / "_internal" / "muet").mkdir(parents=True)
        (app / "_internal" / "muet" / "muet.dll").write_text("", encoding="utf-8")
        (app / "_internal" / "python313.dll").write_text("", encoding="utf-8")
        connus = provenances({"muet": muet}, base)
        chk(binaires_inconnus(app, connus) == [],
            "les DLL d'un paquet installé et celles de Python sont reconnues")
        (app / "_internal" / "libssl-3-x64.dll").write_text("", encoding="utf-8")
        chk(binaires_inconnus(app, connus) == [os.path.join("_internal", "libssl-3-x64.dll")],
            "une DLL venue d'ailleurs (le PATH de la machine) : signalée")

        # Qt : une DLL inconnue de DLL_QT fait refuser ; les sections viennent des DLL.
        qt = app / "_internal" / "PySide6"
        (qt / "plugins" / "imageformats").mkdir(parents=True)
        for dll in ("Qt6Core.dll", "Qt6Widgets.dll", "avcodec-63.dll"):
            (qt / dll).write_text("", encoding="utf-8")
        requises, inconnues = sections_qt_requises(app)
        chk(requises == {"qt-core", "qt-multimedia", "qt-image-formats"} and inconnues == [],
            f"les sections de Qt viennent des DLL embarquées ({sorted(requises)})")
        (qt / "Qt6Bluetooth.dll").write_text("", encoding="utf-8")
        chk(sections_qt_requises(app)[1] == ["Qt6Bluetooth.dll"],
            "une DLL de Qt absente de DLL_QT : signalée")
        chk(lire_entete_qt("Qt version: 6.1.2\nSections: qt-core, mesa\n")
            == ("6.1.2", {"qt-core", "mesa"}), "l'en-tête de qt.txt se relit")

        # Les sources LGPL : chaque composant sous LGPL du programme a sa version et l'adresse
        # de son code source, dans THIRD-PARTY-NOTICES.txt et dans le bloc des notes de Release.
        print("Les sources LGPL")
        filet = "-" * 78
        (licences / "qt.txt").write_text(
            f"Qt version: 1.0\nSections: qt-core\n\n{filet}\nzlib, version 1.3 (Zlib License)\n"
            f"{filet}\n\ntexte\n\n{filet}\nFFmpeg, version 9.0.1 (GNU Lesser General Public "
            f"License v2.1 or later and MIT License)\n{filet}\n\ntexte\n", encoding="utf-8")
        (licences / "gpl-3.0.txt").write_text("GPL 3\n", encoding="utf-8")
        libre = _faux_paquet(site, "libre", "4.2", "License-Expression: LGPL-3.0-only\n"
                             "License-File: COPYING\n",
                             {"libre-4.2.dist-info/licenses/COPYING": "LGPL du libre\n"})
        installes_lgpl = {"libre": libre, "muet": muet}
        versions_dll = {"avcodec-63.dll": "9.0.1"}

        def lire(chemin):
            return versions_dll[chemin.name]

        def source(nom, version, lue_dans, couvre, adresse):
            return SourceLGPL(nom, "a role", "LGPL-x", version, lue_dans, frozenset(couvre),
                              (("source code", adresse),))
        sources = (source("Libre", "4.2", "paquet:libre", {"libre"}, "https://a.org/libre.tar"),
                   source("Muet", "0.1", "paquet:muet", {"muet", "Natif"}, "https://a.org/m.tar"),
                   source("FFmpeg", "9.0.1", "dll:PySide6/avcodec-*.dll", {"FFmpeg"},
                          "https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz"))
        sauve = AUTRES, COMPLEMENTS, SOURCES_LGPL
        try:
            COMPLEMENTS = {"muet": ("0.1", [("lgpl-2.1.txt", "x")], None)}
            AUTRES = (("Natif", "muet", "0.1", [("lgpl-2.1.txt", "x"), ("qt.txt", None)], None),)
            trouves = composants_lgpl([ancien, moderne, libre, muet], licences)
            chk(set(trouves) == {"libre", "muet", "Natif", "FFmpeg"},
                f"les composants sous LGPL se trouvent sans SOURCES_LGPL : métadonnées, texte "
                f"LGPL d'un paquet ou d'une autre entrée, qt.txt ({sorted(trouves)})")

            def verifier(sources_=sources):
                return verifier_sources_lgpl([libre, muet], app, installes_lgpl, licences,
                                             sources_, lire)
            chk(len(verifier()) == 3, "chaque composant couvert, à sa version : accepté")
            chk(refuse(lambda: verifier(sources[:2]), "FFmpeg", "aucune entrée de SOURCES_LGPL"),
                "un composant sous LGPL sans entrée (FFmpeg retiré) : refusé, nommé")
            chk(refuse(lambda: verifier((source("Libre", "4.1", "paquet:libre", {"libre"},
                                                "https://a.org/l.tar"),) + sources[1:]),
                       "Libre", "relevées pour la version 4.1", "4.2 est embarquée"),
                "un paquet embarqué à une autre version que ses adresses : refusé")
            versions_dll["avcodec-63.dll"] = "9.1"
            chk(refuse(verifier, "FFmpeg", "la 9.1 est embarquée"),
                "une DLL à une autre version (lue dans ses ressources) : refusée")
            versions_dll["avcodec-63.dll"] = "9.0.1"
            chk(refuse(lambda: verifier(sources[:2] + (source(
                "FFmpeg", "9.0.1", "dll:PySide6/avcodec-*.dll", {"FFmpeg"},
                "http://ffmpeg.org/x"),)), "FFmpeg", "https://"),
                "une adresse qui n'est pas en https : refusée")
            chk(refuse(lambda: verifier(sources + (source("Fantôme", "1", "paquet:muet",
                                                          {"fantome"}, "https://a.org/f"),)),
                       "Fantôme", "aucun des composants"),
                "une entrée qui ne couvre aucun composant (clé mal écrite) : refusée")
            chk(refuse(lambda: verifier(sources[:2] + (source(
                "FFmpeg", "9.0.1", "dll:PySide6/swscale-*.dll", {"FFmpeg"},
                "https://a.org/f"),)), "FFmpeg", "aucune DLL"),
                "une entrée dont la DLL n'est pas dans le programme : refusée")

            bloc = bloc_sources_lgpl(list(sources))
            attendus = [(s.nom, s.version) for s in sources]
            chk(defauts_du_bloc(bloc, attendus) == [],
                "le bloc de la Release nomme chaque composant, avec sa version et une adresse "
                "https")
            ampute = "\n".join(ligne for ligne in bloc.splitlines() if "FFmpeg" not in ligne)
            chk(defauts_du_bloc(ampute, attendus) == ["FFmpeg 9.0.1 : absent du bloc"],
                "un bloc sans FFmpeg : signalé")
            chk(defauts_du_bloc(bloc.replace("<https://ffmpeg", "<http://ffmpeg"), attendus)
                == ["FFmpeg 9.0.1 : aucune adresse https"],
                "une ligne sans adresse https : signalée")

            SOURCES_LGPL = sources
            plat = " ".join(composer("9.9", [libre, muet], base, installes_lgpl, None,
                                     licences).split())
            chk("Source code of Libre 4.2 (LGPL-x): https://a.org/libre.tar " in plat
                and "Source code of FFmpeg 9.0.1 (LGPL-x): https://ffmpeg.org/releases/"
                    "ffmpeg-9.0.1.tar.xz " in plat
                and "(LGPL): Libre, Muet and FFmpeg." in plat,
                "THIRD-PARTY-NOTICES.txt : les composants sous LGPL nommés en tête, et l'adresse "
                "de chaque code source avec lui (FFmpeg avec l'entrée qui cite qt.txt)")
        finally:
            AUTRES, COMPLEMENTS, SOURCES_LGPL = sauve

    try:
        import pefile  # noqa: F401
    except ImportError:
        print("  [--] pefile absent : la lecture de la version d'une DLL n'est pas vérifiée")
    else:
        majeure, mineure = sys.version_info[:2]
        dll_python = Path(sys.base_prefix) / f"python{majeure}{mineure}.dll"
        lue = version_de_dll(dll_python)
        chk(lue == sys.version.split()[0],
            f"la version d'une DLL se lit dans ses ressources ({dll_python.name} : {lue})")

    # Le dépôt : chaque texte appelé par les tables existe, et l'en-tête de qt.txt couvre les
    # sections que DLL_QT peut demander.
    appeles = {f for _v, fs, _n in COMPLEMENTS.values() for f, _o in fs}
    appeles |= {f for _t, _p, _v, fs, _n in AUTRES for f, _o in fs}
    manquants = sorted(f for f in appeles | set(TEXTES_PARTAGES) if not (LICENCES / f).is_file())
    chk(not manquants, f"chaque texte appelé est dans build/licences/ ({manquants or 'tous'})")
    if (LICENCES / "qt.txt").is_file():
        _v, sections = lire_entete_qt((LICENCES / "qt.txt").read_text(encoding="utf-8"))
        demandees = {s for s in DLL_QT.values() if s} | {"qt-image-formats"}
        chk(demandees <= sections, f"qt.txt recopie chaque section que DLL_QT demande "
                                   f"({sorted(demandees - sections) or 'toutes'})")
    # La LGPL v3 complète la GPL v3 : qui appelle l'une appelle l'autre.
    entrees = [(nom, fs) for nom, (_v, fs, _n) in COMPLEMENTS.items()]
    entrees += [(titre, fs) for titre, _p, _v, fs, _n in AUTRES]
    sans_gpl = [nom for nom, fs in entrees if {"lgpl-3.0.txt"} & {f for f, _o in fs}
                and "gpl-3.0.txt" not in {f for f, _o in fs}]
    chk(not sans_gpl,
        f"chaque entrée sous LGPL v3 appelle aussi la GPL v3 ({sans_gpl or 'toutes'})")
    # Les vraies tables : ce que COMPLEMENTS, AUTRES et qt.txt disent sous LGPL est couvert par
    # SOURCES_LGPL (les paquets dont seules les métadonnées le disent se vérifient à la
    # construction, sur le programme construit).
    couverts = set().union(*(s.couvre for s in SOURCES_LGPL))
    a_couvrir = set(composants_lgpl([], LICENCES))
    a_couvrir |= {nom for nom, (_v, fs, _n) in COMPLEMENTS.items()
                  if any(f.startswith("lgpl") for f, _o in fs)}
    chk(a_couvrir <= couverts, "SOURCES_LGPL couvre ce que les tables disent sous LGPL "
                               f"({sorted(a_couvrir - couverts) or 'tout'})")
    chk(all(s.version and s.adresses and all(a.startswith("https://") for _q, a in s.adresses)
            for s in SOURCES_LGPL), "chaque entrée de SOURCES_LGPL a une version et des "
                                    "adresses https")
    print(f"{'ÉCHEC' if echecs else 'OK'} : {len(echecs)} échec(s)")
    return 1 if echecs else 0


def main(argv: list[str]) -> int:
    for flux in (sys.stdout, sys.stderr):
        flux.reconfigure(encoding="utf-8")
    if argv == ["--autotest"]:
        return autotest()
    try:
        if argv == ["--rafraichir-qt"]:
            rafraichir_qt(metadata.version("PySide6_Essentials"))
            return 0
        if len(argv) == 1 and not argv[0].startswith("-"):
            ecrire(Path(argv[0]))
            return 0
        if len(argv) == 3 and argv[0] == "--sources-lgpl":
            ecrire_sources_lgpl(Path(argv[1]), Path(argv[2]))
            return 0
    except Refus as e:
        ecrit = argv[2] if argv[:1] == ["--sources-lgpl"] else NOM_FICHIER
        print(f"ÉCHEC : {ecrit} n'est pas écrit.\n{e}", file=sys.stderr)
        return 1
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
