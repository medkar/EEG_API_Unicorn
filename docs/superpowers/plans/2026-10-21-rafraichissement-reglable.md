# Le rafraîchissement se règle, et l'écran du poste suit — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** le rafraîchissement du c-VEP se règle dans « Entraîner » et voyage avec le modèle, et les
fenêtres SSVEP et c-VEP font passer l'écran principal au rafraîchissement voulu le temps de la
séance.

**Architecture:** un module neuf, `src/stimulus/ecran.py`, décide et bascule l'écran (Windows,
`user32` par `ctypes`, mode temporaire) ; les deux fenêtres gagnent `--ecran-hz` ; le registre des
fenêtres déclare qui l'accepte et d'où vient la valeur ; la console la calcule (réglage
d'« Entraîner », modèle choisi, ou réglage du mode) et tend un filet qui rétablit l'écran après
toute fenêtre. Côté moteur, la calibration c-VEP porte le réglage, refuse un premier marqueur à un
autre rafraîchissement, et écrit le rafraîchissement dans le nom de ses fichiers.

**Tech Stack:** Python 3.13 (`.venv`), pygame 2.6, PySide6, pylsl, numpy, `ctypes` (Windows).

**Spec :** [docs/superpowers/specs/2026-10-21-rafraichissement-reglable-design.md](../specs/2026-10-21-rafraichissement-reglable-design.md)

## Conventions de ce dépôt, à lire avant la tâche 1

- Les tests sont des **autotests DANS les modules** (`_selftest()` ou `_smoke()`), lancés par
  `python <fichier>` ou `python <fichier> --smoke`. Chaque vérification est un `chk(cond, msg)` qui
  imprime `OK` ou `ÉCHEC`, et le module finit par `VERDICT : OK` ou `VERDICT : PROBLÈME`.
- Toutes les commandes se lancent **depuis la racine du dépôt**, avec l'interpréteur du venv :
  `.venv/Scripts/python` (Git Bash) ou `.venv\Scripts\python` (PowerShell).
- **Aucun texte affiché n'est écrit en dur** : il passe par `tr("cle", valeur=…)` et vit dans
  `src/core/langues/fr/*.json` ET `src/core/langues/en/*.json`. Les catalogues sont triés par clé
  et se réécrivent à l'identique avec `json.dumps(d, ensure_ascii=False, indent=2,
  sort_keys=True) + "\n"` : on les modifie avec le script de l'étape 1.1, jamais à la main.
- Commentaires et messages d'autotest en français, au présent, sans histoire du chantier
  (`docs/charte-redaction.md`). Messages de commit en anglais, terminés par
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Frontières d'import vérifiées par `server.py --smoke` : `stimulus -> core` seulement,
  `console -> core, stimulus`, jamais pygame ni Qt dans `core`.
- `data/` n'existe pas sur ce poste : la garde `src/core/modes/cvep.py` a **déjà** une `ÉCHEC`
  (« exiger plus de votes que de fenêtres ») faute de modèle entraîné. Elle n'est pas à corriger
  ici ; toute AUTRE `ÉCHEC` dans ce fichier en est une.

## Fichiers

| Fichier | Rôle dans ce chantier |
|---|---|
| `src/stimulus/ecran.py` (neuf) | décide et bascule le rafraîchissement de l'écran principal ; filet de la console |
| `src/stimulus/refresh.py` | + `frequence_mesuree` : mesure robuste, sans arrondi |
| `src/stimulus/ssvep.py` | + `--ecran-hz`, `run(ecran_hz=…)` |
| `src/stimulus/cvep.py` | + `--ecran-hz`, `run(ecran_hz=…)` |
| `src/stimulus/registry.py` | + `ECRAN`, `option_ecran` |
| `src/core/cvep_models.py` | + `refresh_de`, `decrire()["refresh"]` |
| `src/core/modes/cvep.py` | + réglage `refresh_hz` dans `Calib.params` |
| `src/core/modes/cvep_calib.py` | refus du premier marqueur, durée, suffixe `_<hz>Hz` des fichiers |
| `src/core/modes/cvep_test.py` | durée au rafraîchissement du modèle |
| `src/console/app.py` | `_ecran_hz`, options des trois lancements, autotest |
| `src/console/fenetres.py` | filet `retablir_ecran` après chaque fenêtre |
| `src/core/langues/{fr,en}/fenetres.json`, `modes.json` | textes |
| `CLAUDE.md`, `README.md`, `docs/qa.md`, `docs/recette.md` | documentation |

---

### Task 1 : la mesure robuste, et le module `stimulus/ecran.py`

**Files:**
- Modify: `src/stimulus/refresh.py` (ajout en fin de fichier)
- Create: `src/stimulus/ecran.py`
- Modify: `src/core/langues/fr/fenetres.json`, `src/core/langues/en/fenetres.json`

- [ ] **Step 1.1 : l'outil qui ajoute des textes sans casser le format**

Créer, HORS du dépôt (dossier temporaire de session), `ajoute_textes.py` :

```python
"""Ajoute (ou remplace) des clés dans un catalogue de textes, en gardant son format exact."""
import json
import sys

chemin, fragment = sys.argv[1], sys.argv[2]
with open(fragment, encoding="utf-8") as f:
    ajouts = json.load(f)
with open(chemin, encoding="utf-8") as f:
    d = json.load(f)
d.update(ajouts)
with open(chemin, "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps(d, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
print(chemin, ":", len(ajouts), "clé(s)")
```

- [ ] **Step 1.2 : les textes de l'écran**

Fragment `ecran_fr.json` (dossier temporaire) :

```json
{
  "fenetre.ecran.bascule": "Écran passé à {hz} Hz le temps de la séance (il était à {avant} Hz).",
  "fenetre.ecran.refus_absent": "Cet écran ne sait pas afficher à {voulu} Hz : il propose {offerts} Hz. Règle l'un de ces rafraîchissements, ou passe par un autre écran principal.",
  "fenetre.ecran.refus_bascule": "Windows a refusé de passer l'écran à {voulu} Hz. Règle-le à la main dans les paramètres d'affichage, puis recommence.",
  "fenetre.ecran.refus_mesure": "L'écran affiche à {mesure} Hz, pas aux {voulu} Hz demandés : le stimulus irait à la mauvaise vitesse. Règle l'écran à {voulu} Hz dans les paramètres d'affichage, puis recommence."
}
```

Fragment `ecran_en.json` :

```json
{
  "fenetre.ecran.bascule": "Screen switched to {hz} Hz for this session (it was at {avant} Hz).",
  "fenetre.ecran.refus_absent": "This screen cannot display at {voulu} Hz: it offers {offerts} Hz. Set one of these refresh rates, or use another main screen.",
  "fenetre.ecran.refus_bascule": "Windows refused to switch the screen to {voulu} Hz. Set it by hand in the display settings, then try again.",
  "fenetre.ecran.refus_mesure": "The screen displays at {mesure} Hz, not at the requested {voulu} Hz: the stimulus would run at the wrong speed. Set the screen to {voulu} Hz in the display settings, then try again."
}
```

Run :

```bash
.venv/Scripts/python -I <tmp>/ajoute_textes.py src/core/langues/fr/fenetres.json <tmp>/ecran_fr.json
.venv/Scripts/python -I <tmp>/ajoute_textes.py src/core/langues/en/fenetres.json <tmp>/ecran_en.json
git diff --stat
```

Expected : deux fichiers, 4 lignes ajoutées chacun, aucune autre ligne touchée.

- [ ] **Step 1.3 : la mesure robuste dans `src/stimulus/refresh.py`**

Ajouter à la fin du fichier :

```python
def frequence_mesuree(pygame, surface, images=120, horloge=_time.perf_counter):
    """Le rafraîchissement RÉEL de l'écran, en Hz, sans l'arrondir à une valeur usuelle.

    C'est l'inverse de l'intervalle MÉDIAN entre deux images (vsync). La médiane ignore une image
    sautée, qui ferait croire à un écran plus lent : juste après un changement de mode, les
    premières images sont souvent irrégulières. Rend 0.0 si rien n'a pu être mesuré.

    `horloge` n'existe que pour l'autotest de `stimulus/ecran.py`.
    """
    surface.fill(FOND)
    pygame.display.flip()
    pygame.event.pump()
    intervalles = []
    avant = horloge()
    for _ in range(int(images)):
        surface.fill(FOND)
        pygame.display.flip()
        pygame.event.pump()
        maintenant = horloge()
        intervalles.append(maintenant - avant)
        avant = maintenant
    if not intervalles:
        return 0.0
    intervalles.sort()
    milieu = intervalles[len(intervalles) // 2]
    return 1.0 / milieu if milieu > 0 else 0.0
```

- [ ] **Step 1.4 : écrire `src/stimulus/ecran.py` avec son autotest, et des fonctions VIDES**

Écrire le fichier complet de l'étape 1.6, mais avec ces quatre corps remplacés par
`raise NotImplementedError` : `choisir`, `confirme`, `Bascule.__enter__`, `retablir_si_change`.

- [ ] **Step 1.5 : vérifier que l'autotest échoue**

Run : `.venv/Scripts/python src/stimulus/ecran.py`
Expected : une trace `NotImplementedError`, sortie non nulle.

- [ ] **Step 1.6 : le module complet**

`src/stimulus/ecran.py` :

```python
"""L'écran principal au rafraîchissement que demande un stimulus, le temps d'une séance.

Le SSVEP et le c-VEP ne s'affichent juste qu'à un rafraîchissement précis. Le code c-VEP change à
chaque image : à 60 Hz, une image dure 16,7 ms, soit 2,75 images d'un écran à 165 Hz. Tenir ses
bits tantôt 2 images, tantôt 3, déformerait le code, et le modèle apprendrait ce code déformé. La
fenêtre demande donc à Windows de passer l'écran principal au rafraîchissement voulu pendant
qu'elle est ouverte, puis de le rétablir.

Deux couches :
- la DÉCISION (`choisir`, `confirme`, `Bascule`, `retablir_si_change`), qui reçoit les appels
  système en paramètre et se teste sans écran ;
- les appels système : `_Windows` parle à `user32` par `ctypes` ; ailleurs, `_Inconnu` ne sait ni
  lire ni changer le mode, et c'est la mesure de la fenêtre qui décide seule.

Autotest (lit l'écran, ne le change jamais) :
    python src/stimulus/ecran.py
"""

import contextlib as _contextlib
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from core.config import use_utf8_console  # noqa: E402
from core.i18n import nombre, tr  # noqa: E402

# L'écart toléré entre le rafraîchissement voulu et celui de l'écran. C'est celui du moteur entre
# un marqueur de cycle c-VEP et son modèle : au-delà, il refuserait l'horloge.
TOLERANCE_HZ = 1.0


class EcranRefuse(Exception):
    """Le stimulus ne peut pas s'afficher au rafraîchissement demandé. Le message est la raison,
    dans la langue de l'écran : la console l'affiche telle quelle."""


def choisir(voulu, offerts):
    """Le rafraîchissement proposé le plus proche de `voulu`, à `TOLERANCE_HZ` près, ou None."""
    voulu = float(voulu)
    proches = [float(f) for f in offerts if abs(float(f) - voulu) <= TOLERANCE_HZ]
    return min(proches, key=lambda f: abs(f - voulu)) if proches else None


def confirme(voulu, mesure):
    """`voulu` si l'écran, MESURÉ, le tient à `TOLERANCE_HZ` près ; lève `EcranRefuse` sinon.

    C'est `voulu` qui sort, pas la mesure : c'est lui que portent les marqueurs, donc le modèle.
    """
    if abs(float(mesure) - float(voulu)) > TOLERANCE_HZ:
        raise EcranRefuse(tr("fenetre.ecran.refus_mesure", voulu=nombre(float(voulu)),
                             mesure=nombre(round(float(mesure), 1))))
    return float(voulu)


class Bascule:
    """L'écran principal à `voulu` Hz le temps d'un `with`, puis son retour.

    `systeme` fournit cinq appels : `actuel()` et `enregistre()` (en Hz, ou None s'il ne sait
    pas), `offerts()`, `basculer(hz)` (True si Windows accepte) et `retablir()`. Par défaut, ceux
    de cette machine.

    En entrée : rien si l'écran tient déjà `voulu`, sinon le passage, ou `EcranRefuse` sans rien
    avoir touché. En sortie, quelle qu'en soit la cause : le retour, si quelque chose a changé.
    """

    def __init__(self, voulu, systeme=None):
        self.voulu = float(voulu)
        self.systeme = systeme if systeme is not None else systeme_de_la_machine()
        self.change = False

    def __enter__(self):
        actuel = self.systeme.actuel()
        if actuel is None or abs(actuel - self.voulu) <= TOLERANCE_HZ:
            return self
        offerts = sorted({float(f) for f in self.systeme.offerts()})
        cible = choisir(self.voulu, offerts)
        if cible is None:
            raise EcranRefuse(tr("fenetre.ecran.refus_absent", voulu=nombre(self.voulu),
                                 offerts=" · ".join(nombre(f) for f in offerts)))
        if not self.systeme.basculer(cible):
            raise EcranRefuse(tr("fenetre.ecran.refus_bascule", voulu=nombre(self.voulu)))
        self.change = True
        print(tr("fenetre.ecran.bascule", hz=nombre(cible), avant=nombre(actuel)))
        return self

    def __exit__(self, *_exc):
        if self.change:
            self.change = False
            self.systeme.retablir()
        return False


def au_rafraichissement(voulu, systeme=None):
    """`Bascule(voulu)` si un rafraîchissement est demandé, sinon un `with` qui ne fait rien."""
    if voulu is None:
        return _contextlib.nullcontext()
    return Bascule(voulu, systeme)


def retablir_si_change(systeme=None):
    """Remet l'écran principal au rafraîchissement enregistré dans Windows, s'il n'y est plus.

    C'est le filet de la console : une fenêtre TUÉE ne passe pas par la sortie de son `with`, et
    Windows ne rétablit pas toujours seul un mode temporaire. Sans écart, ne fait rien : pas de
    passage au noir inutile. Rend True si elle a rétabli.
    """
    systeme = systeme if systeme is not None else systeme_de_la_machine()
    actuel, enregistre = systeme.actuel(), systeme.enregistre()
    if actuel is None or enregistre is None or abs(actuel - enregistre) < 0.5:
        return False
    systeme.retablir()
    return True


def hz_positif(texte):
    """Pour `argparse` : un rafraîchissement strictement positif, en Hz."""
    import argparse

    try:
        valeur = float(texte)
    except ValueError:
        raise argparse.ArgumentTypeError(f"« {texte} » n'est pas un nombre de Hz") from None
    if valeur <= 0:
        raise argparse.ArgumentTypeError(f"un rafraîchissement est strictement positif ({texte})")
    return valeur


# --- Les appels système -------------------------------------------------------------------------

class _Inconnu:
    """Hors Windows : on ne sait ni lire ni changer le mode. La mesure de la fenêtre décide seule."""

    def actuel(self):
        return None

    def enregistre(self):
        return None

    def offerts(self):
        return []

    def basculer(self, hz):
        return False

    def retablir(self):
        pass


class _Windows:
    """Les appels à `user32` pour l'écran principal, et rien d'autre : tout ce qui décide est
    au-dessus. Le passage est TEMPORAIRE (`CDS_FULLSCREEN`) : il n'est jamais écrit dans les
    réglages de Windows, et `retablir` revient à ceux-ci."""

    ENUM_CURRENT_SETTINGS = 0xFFFFFFFF      # (DWORD)-1
    ENUM_REGISTRY_SETTINGS = 0xFFFFFFFE     # (DWORD)-2
    DM_DISPLAYFREQUENCY = 0x00400000
    CDS_FULLSCREEN = 0x00000004
    DISP_CHANGE_SUCCESSFUL = 0
    DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class DEVMODEW(ctypes.Structure):
            _fields_ = [
                ("dmDeviceName", wintypes.WCHAR * 32),
                ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD),
                ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD),
                ("dmFields", wintypes.DWORD),
                ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
                ("dmDisplayOrientation", wintypes.DWORD),
                ("dmDisplayFixedOutput", wintypes.DWORD),
                ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
                ("dmCollate", ctypes.c_short),
                ("dmFormName", wintypes.WCHAR * 32),
                ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD),
                ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD),
                ("dmDisplayFlags", wintypes.DWORD), ("dmDisplayFrequency", wintypes.DWORD),
                ("dmICMMethod", wintypes.DWORD), ("dmICMIntent", wintypes.DWORD),
                ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD),
                ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD),
                ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD),
            ]

        class DISPLAY_DEVICEW(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                        ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                        ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                                ctypes.POINTER(DEVMODEW)]
        user32.EnumDisplaySettingsW.restype = wintypes.BOOL
        user32.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                               ctypes.POINTER(DISPLAY_DEVICEW), wintypes.DWORD]
        user32.EnumDisplayDevicesW.restype = wintypes.BOOL
        user32.ChangeDisplaySettingsExW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(DEVMODEW),
                                                    wintypes.HWND, wintypes.DWORD,
                                                    wintypes.LPVOID]
        user32.ChangeDisplaySettingsExW.restype = wintypes.LONG
        self._ctypes, self._user32, self.DEVMODEW = ctypes, user32, DEVMODEW
        # Le périphérique de l'écran PRINCIPAL, celui où s'ouvrent les fenêtres de stimulus.
        # None, s'il ne se trouve pas, veut dire « le périphérique par défaut » pour `user32`.
        self.peripherique = None
        i = 0
        while True:
            dd = DISPLAY_DEVICEW()
            dd.cb = ctypes.sizeof(dd)
            if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
                break
            if dd.StateFlags & self.DISPLAY_DEVICE_PRIMARY_DEVICE:
                self.peripherique = dd.DeviceName
                break
            i += 1

    def _mode(self, numero):
        dm = self.DEVMODEW()
        dm.dmSize = self._ctypes.sizeof(dm)
        if not self._user32.EnumDisplaySettingsW(self.peripherique, numero,
                                                 self._ctypes.byref(dm)):
            return None
        return dm

    def _hz(self, numero):
        dm = self._mode(numero)
        # 0 et 1 veulent dire « le défaut du matériel » : ce n'est pas un rafraîchissement.
        if dm is None or dm.dmDisplayFrequency <= 1:
            return None
        return float(dm.dmDisplayFrequency)

    def actuel(self):
        return self._hz(self.ENUM_CURRENT_SETTINGS)

    def enregistre(self):
        return self._hz(self.ENUM_REGISTRY_SETTINGS)

    def offerts(self):
        """Les rafraîchissements proposés à la définition et à la profondeur ACTUELLES."""
        courant = self._mode(self.ENUM_CURRENT_SETTINGS)
        if courant is None:
            return []
        forme = (courant.dmPelsWidth, courant.dmPelsHeight, courant.dmBitsPerPel)
        vus, i = set(), 0
        while True:
            dm = self._mode(i)
            if dm is None:
                break
            if ((dm.dmPelsWidth, dm.dmPelsHeight, dm.dmBitsPerPel) == forme
                    and dm.dmDisplayFrequency > 1):
                vus.add(float(dm.dmDisplayFrequency))
            i += 1
        return sorted(vus)

    def basculer(self, hz):
        dm = self._mode(self.ENUM_CURRENT_SETTINGS)
        if dm is None:
            return False
        dm.dmDisplayFrequency = int(round(float(hz)))
        dm.dmFields = self.DM_DISPLAYFREQUENCY
        code = self._user32.ChangeDisplaySettingsExW(self.peripherique, self._ctypes.byref(dm),
                                                     None, self.CDS_FULLSCREEN, None)
        return code == self.DISP_CHANGE_SUCCESSFUL

    def retablir(self):
        self._user32.ChangeDisplaySettingsExW(self.peripherique, None, None, 0, None)


def systeme_de_la_machine():
    """`_Windows` sous Windows, `_Inconnu` ailleurs, ou si `user32` ne répond pas."""
    if _sys.platform == "win32":
        try:
            return _Windows()
        except (OSError, AttributeError):
            pass
    return _Inconnu()


def _selftest():  # noqa: C901 - un autotest se lit de haut en bas
    """La décision sur un Windows FACTICE ; sur cette machine, une LECTURE de l'écran, jamais un
    changement."""
    from stimulus.refresh import frequence_mesuree

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _Faux:
        """Un Windows factice : un écran à `actuel` Hz, qui propose `offerts`."""

        def __init__(self, actuel, offerts, accepte=True, enregistre=None):
            self.hz, self._offerts, self.accepte = actuel, list(offerts), accepte
            self._enregistre = actuel if enregistre is None else enregistre
            self.journal = []

        def actuel(self):
            return self.hz

        def enregistre(self):
            return self._enregistre

        def offerts(self):
            return list(self._offerts)

        def basculer(self, hz):
            self.journal.append(("basculer", hz))
            if self.accepte:
                self.hz = hz
            return self.accepte

        def retablir(self):
            self.journal.append(("retablir",))
            self.hz = self._enregistre

    poste = (59.0, 60.0, 120.0, 144.0, 165.0)

    # --- 1. Le choix du mode ---
    chk(choisir(60, poste) == 60.0 and choisir(59.94, poste) == 60.0
        and choisir(144.5, poste) == 144.0,
        f"le mode retenu est le plus proche du voulu, à 1 Hz près (60 -> {choisir(60, poste)}, "
        f"59,94 -> {choisir(59.94, poste)}, 144,5 -> {choisir(144.5, poste)})")
    chk(choisir(75, poste) is None and choisir(61.5, poste) is None,
        "…et aucun quand rien n'est à 1 Hz près : jamais un mode « à peu près »")

    # --- 2. Déjà au bon rafraîchissement : rien ne change ---
    for actuel in (60.0, 59.0):
        f = _Faux(actuel, poste)
        with Bascule(60.0, f) as b:
            dedans = (b.change, f.hz)
        chk(f.journal == [] and dedans == (False, actuel),
            f"un écran déjà à {actuel:g} Hz pour 60 demandés : rien n'est touché ({f.journal})")

    # --- 3. Le passage, puis le retour ---
    f = _Faux(165.0, poste)
    with Bascule(60.0, f) as b:
        dedans = (b.change, f.hz)
    chk(dedans == (True, 60.0) and f.journal == [("basculer", 60.0), ("retablir",)]
        and f.hz == 165.0,
        f"un écran à 165 Hz pour 60 demandés passe à 60 pendant la séance, puis revient à 165 "
        f"({dedans}, {f.journal})")

    # --- 4. Le retour, même quand la séance plante ---
    f = _Faux(165.0, poste)
    try:
        with Bascule(60.0, f):
            raise RuntimeError("la fenêtre plante")
    except RuntimeError:
        pass
    chk(f.journal[-1:] == [("retablir",)] and f.hz == 165.0,
        f"…et il revient aussi quand la séance plante ({f.journal})")

    # --- 5. Les refus, sans rien avoir touché ---
    f = _Faux(165.0, poste)
    try:
        with Bascule(75.0, f):
            pass
        refus = None
    except EcranRefuse as e:
        refus = str(e)
    chk(refus is not None and "75" in refus and "144" in refus and f.journal == [],
        f"75 Hz que l'écran ne propose pas : REFUS qui nomme le voulu et la liste, rien touché "
        f"({refus}, {f.journal})")
    f = _Faux(165.0, poste, accepte=False)
    try:
        with Bascule(60.0, f):
            pass
        refus = None
    except EcranRefuse as e:
        refus = str(e)
    chk(refus is not None and "60" in refus and f.journal == [("basculer", 60.0)]
        and f.hz == 165.0,
        f"Windows refuse le passage : REFUS, et rien à rétablir ({refus}, {f.journal})")

    # --- 6. Hors Windows, et sans demande ---
    with Bascule(60.0, _Inconnu()) as b:
        dedans = b.change
    chk(dedans is False, "hors Windows, rien ne change : la mesure de la fenêtre décide seule")
    with au_rafraichissement(None) as rien:
        chk(rien is None, "sans rafraîchissement demandé, `au_rafraichissement` ne fait rien")

    # --- 7. La confirmation par la mesure ---
    chk(confirme(60.0, 59.6) == 60.0 and confirme(60.0, 60.9) == 60.0,
        "une mesure à 1 Hz près confirme, et c'est le VOULU qui sort, celui des marqueurs")
    for mesure in (165.0, 61.2, 58.7):
        try:
            confirme(60.0, mesure)
            refus = None
        except EcranRefuse as e:
            refus = str(e)
        chk(refus is not None and "60" in refus and nombre(round(mesure, 1)) in refus,
            f"une mesure à {mesure:g} Hz pour 60 demandés : REFUS qui nomme les deux ({refus})")

    # --- 8. Le filet de la console ---
    f = _Faux(60.0, poste, enregistre=165.0)
    chk(retablir_si_change(f) is True and f.hz == 165.0 and f.journal == [("retablir",)],
        f"un écran resté à 60 Hz alors que Windows a 165 enregistrés : le filet le rétablit "
        f"({f.journal})")
    f = _Faux(165.0, poste)
    chk(retablir_si_change(f) is False and f.journal == [],
        "…et sans écart, il ne fait rien : pas de passage au noir inutile")
    chk(retablir_si_change(_Inconnu()) is False, "…ni hors Windows")

    # --- 9. La mesure, robuste à une image sautée ---
    class _Ecran:
        """Un écran et un pygame factices : chaque `flip` avance l'horloge d'une période."""

        def __init__(self, periodes):
            self.t, self._periodes = 0.0, iter(periodes)
            self.display, self.event = self, self

        def flip(self):
            self.t += next(self._periodes)

        def pump(self):
            pass

        def fill(self, _couleur):
            pass

    periodes = [1 / 165] * 121
    periodes[30] = periodes[80] = 2 / 165          # deux images sautées
    e = _Ecran(periodes)
    hz = frequence_mesuree(e, e, images=120, horloge=lambda: e.t)
    moyenne = 120 / sum(periodes[1:])
    chk(abs(hz - 165.0) < 0.01 and moyenne < 163.0,
        f"deux images sautées ne déplacent pas la mesure : {hz:.2f} Hz (une moyenne dirait "
        f"{moyenne:.1f} Hz, et refuserait à tort)")

    # --- 10. Cette machine, en LECTURE seule ---
    machine = systeme_de_la_machine()
    if isinstance(machine, _Windows):
        taille = machine._ctypes.sizeof(machine.DEVMODEW)
        actuel = machine.actuel()
        chk(taille == 220, f"la structure DEVMODEW a la taille que Windows attend ({taille} octets)")
        chk(actuel is not None and actuel in machine.offerts(),
            f"l'écran principal se lit : {actuel} Hz, parmi {machine.offerts()}")
    else:
        print("  (cette machine n'est pas sous Windows : lecture de l'écran non vérifiée)")

    print(f"[ecran] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    raise SystemExit(0 if _selftest() else 1)
```

- [ ] **Step 1.7 : l'autotest passe**

Run : `.venv/Scripts/python src/stimulus/ecran.py`
Expected : toutes les lignes `OK`, `[ecran] VERDICT : OK`, sortie 0. Sur ce poste, la ligne 10
lit 165 Hz parmi `[59.0, 60.0, 120.0, 144.0, 165.0]`.

- [ ] **Step 1.8 : les textes et la frontière**

Run : `.venv/Scripts/python src/core/i18n.py`
Expected : `0 faute(s) — VERDICT : OK` (les quatre clés sont utilisées, l'anglais les a toutes).

- [ ] **Step 1.9 : commit**

```bash
git add src/stimulus/ecran.py src/stimulus/refresh.py src/core/langues/fr/fenetres.json src/core/langues/en/fenetres.json
git commit -m "Stimulus screen: switch the main screen to the wanted refresh rate, then back" -m "stimulus/ecran.py decides (pure, tested on a fake Windows) and switches the primary display through user32, as a temporary mode. refresh.py gains a median-based measure that a dropped frame does not move." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2 : vérifier sur ce poste le passage réel, et le rétablissement après un processus tué

Ce n'est pas un test du dépôt : c'est la réponse à la question ouverte de la spec (§ 10, risque 1).
**L'écran principal passe au noir quelques secondes.**

**Files:** aucun dans le dépôt. Script `essai_bascule.py` dans le dossier temporaire.

- [ ] **Step 2.1 : le script**

```python
"""Sur CE poste : un processus passe l'écran principal à 60 Hz, il est TUÉ, et on regarde si
Windows rétablit seul. Puis le filet de la console."""
import subprocess
import sys
import time

sys.path.insert(0, "src")
from stimulus.ecran import retablir_si_change, systeme_de_la_machine  # noqa: E402

m = systeme_de_la_machine()
print("avant      :", m.actuel(), "Hz, enregistré", m.enregistre(), "Hz, proposés", m.offerts())
enfant = subprocess.Popen([sys.executable, "-c",
                           "import sys, time; sys.path.insert(0, 'src');"
                           "from stimulus.ecran import systeme_de_la_machine as s;"
                           "print('bascule    :', s().basculer(60), flush=True); time.sleep(60)"])
time.sleep(5)
print("pendant    :", m.actuel(), "Hz")
enfant.kill()
enfant.wait()
time.sleep(3)
apres = m.actuel()
seul = apres == m.enregistre()
print("après kill :", apres, "Hz —", "Windows a rétabli SEUL" if seul else "PAS rétabli par Windows")
print("filet      :", "a rétabli" if retablir_si_change() else "rien à faire")
time.sleep(2)
print("fin        :", m.actuel(), "Hz")
```

- [ ] **Step 2.2 : le lancer, depuis la racine du dépôt**

Run : `.venv/Scripts/python -I <tmp>/essai_bascule.py`
Expected : `avant : 165.0`, `bascule : True`, `pendant : 60.0`, puis l'une des deux lignes
« après kill », et `fin : 165.0` dans tous les cas.

- [ ] **Step 2.3 : noter le résultat** pour la tâche 11 (CLAUDE.md et recette) : Windows
rétablit-il seul un mode temporaire après la mort du processus, sur ce poste ? Si `fin` n'est pas
165, arrêter et rétablir l'écran à la main dans Paramètres → Affichage avant de continuer.

---

### Task 3 : la fenêtre SSVEP accepte `--ecran-hz`

**Files:**
- Modify: `src/stimulus/ssvep.py` (imports vers la ligne 559, `run` ligne 608, mesure vers la
  ligne 688, `_smoke` vers la ligne 1220, `_parse_args` ligne 1925, bloc `__main__`)

- [ ] **Step 3.1 : l'autotest d'abord**

Dans `_smoke()`, juste APRÈS :

```python
    chk(run(smoke=True, refresh=60.0),
        "le décodage libre rend 30 frames sans erreur (aucun écran requis)")
```

ajouter :

```python
    # --- A ter. L'ÉCRAN DU STIMULUS (`ecran_hz`) -----------------------------------------
    # `refresh` tient ici le rôle de la MESURE : l'écran factice n'a pas de vsync. 165 Hz mesurés
    # pour 60 demandés : la fenêtre refuse AVANT de créer son flux de marqueurs, sinon un émetteur
    # fantôme resterait sur le réseau. En mode guidé, parce que c'est lui qui en crée un.
    module = globals()
    vrai_outlet, crees = module["StreamOutlet"], []

    def _espion(*a, **k):
        crees.append(a)
        return vrai_outlet(*a, **k)

    module["StreamOutlet"] = _espion
    try:
        try:
            run(smoke=True, refresh=165.0, ecran_hz=60.0, guide=True, per_target=1, seed=5,
                stream=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
                attente_moteur_s=0.0)
            refus_ecran = None
        except EcranRefuse as e:
            refus_ecran = str(e)
    finally:
        module["StreamOutlet"] = vrai_outlet
    chk(refus_ecran is not None and "165" in refus_ecran and "60" in refus_ecran and not crees,
        f"un écran mesuré à 165 Hz pour 60 Hz demandés : REFUS qui nomme les deux, avant tout "
        f"flux de marqueurs ({refus_ecran}, {len(crees)} flux créé(s))")
    bilan_ecran = {}
    chk(run(smoke=True, refresh=59.6, ecran_hz=60.0, bilan=bilan_ecran)
        and bilan_ecran.get("refresh") == 60.0,
        f"un écran mesuré à 59,6 Hz pour 60 demandés : la séance tourne à 60 Hz, le VOULU "
        f"({bilan_ecran.get('refresh')})")
```

- [ ] **Step 3.2 : vérifier qu'il échoue**

Run : `.venv/Scripts/python src/stimulus/ssvep.py --smoke`
Expected : `NameError: name 'EcranRefuse' is not defined` (ou `TypeError` sur `ecran_hz`).

- [ ] **Step 3.3 : les imports**

Juste après `from stimulus.refresh import measure_refresh  # noqa: E402,F401`, ajouter :

```python
from stimulus.refresh import frequence_mesuree  # noqa: E402
from stimulus.ecran import EcranRefuse, au_rafraichissement, confirme, hz_positif  # noqa: E402
```

- [ ] **Step 3.4 : `run()`**

Dans la signature, remplacer `        source_statut=None):` (dernière ligne de la signature de `run`)
par :

```python
        source_statut=None, ecran_hz=None):
```

Dans la docstring de `run`, juste avant le paragraphe qui commence par ``    `freqs` IMPOSE``,
ajouter :

```python
    `ecran_hz` (`--ecran-hz`) : le rafraîchissement auquel la séance DOIT tourner. L'écran a été
    passé à cette valeur avant l'appel (`stimulus/ecran.py`) ; ici, on le MESURE, et on lève
    `EcranRefuse` s'il ne la tient pas, avant de créer le moindre flux. `refresh`, s'il est
    donné aussi, tient lieu de mesure : c'est l'écran factice de l'autotest.

```

Remplacer :

```python
    if refresh is None:
        refresh = 60.0 if smoke else measure_refresh(pygame, win)
    try:
        plan = plan_du_stimulus(refresh, freqs)
```

par :

```python
    if ecran_hz is not None:
        try:
            refresh = confirme(ecran_hz, refresh if refresh is not None
                               else frequence_mesuree(pygame, win))
        except EcranRefuse:
            # On FERME avant de propager, comme pour un refus de fréquences : un plein écran noir
            # cacherait le message qui explique le refus.
            pygame.quit()
            for s in (source_dec, source_rep):
                if s is not None:
                    s.fermer()
            raise
    elif refresh is None:
        refresh = 60.0 if smoke else measure_refresh(pygame, win)
    try:
        plan = plan_du_stimulus(refresh, freqs)
```

- [ ] **Step 3.5 : l'option**

Dans `_parse_args`, remplacer :

```python
    p.add_argument("--refresh", type=float, default=None, help="forcer le refresh (Hz)")
```

par :

```python
    rafraichissement = p.add_mutually_exclusive_group()
    rafraichissement.add_argument("--refresh", type=float, default=None,
                                  help="forcer le refresh (Hz), sans le mesurer")
    rafraichissement.add_argument(
        "--ecran-hz", type=hz_positif, default=None,
        help="le rafraîchissement auquel AFFICHER (Hz) : l'écran principal y passe le temps de la "
             "séance, puis revient, et la fenêtre REFUSE (sortie 2) si l'écran ne le tient pas. "
             "C'est ce que la console passe")
```

- [ ] **Step 3.6 : le bloc `__main__`**

Remplacer :

```python
    try:
        fait = run(windowed=args.windowed, refresh=args.refresh, seconds=args.seconds,
                   guide=args.guide, per_target=args.trials, seed=args.seed, freqs=freqs,
                   retour=args.retour)
    except FreqsRefusees as refus:
```

par :

```python
    try:
        with au_rafraichissement(args.ecran_hz):
            fait = run(windowed=args.windowed, refresh=args.refresh, seconds=args.seconds,
                       guide=args.guide, per_target=args.trials, seed=args.seed, freqs=freqs,
                       retour=args.retour, ecran_hz=args.ecran_hz)
    except EcranRefuse as refus:
        # Sortie 2, comme un refus de fréquences : la fenêtre n'a rien affiché. L'écran est déjà
        # revenu : la sortie du `with` passe avant ce message.
        print(f"[ssvep-stim] ⚠️ REFUS : {refus}")
        sys.exit(2)
    except FreqsRefusees as refus:
```

- [ ] **Step 3.7 : l'autotest passe**

Run : `.venv/Scripts/python src/stimulus/ssvep.py --smoke`
Expected : les deux nouvelles lignes `OK`, `[ssvep-stim] VERDICT : OK`, sortie 0.

- [ ] **Step 3.8 : commit**

```bash
git add src/stimulus/ssvep.py
git commit -m "SSVEP window: --ecran-hz runs the session at the wanted refresh rate, or refuses" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4 : la fenêtre c-VEP accepte `--ecran-hz`

**Files:**
- Modify: `src/stimulus/cvep.py` (imports ligne 186, `run` ligne 501, mesure ligne 633,
  `_smoke` vers la ligne 1383, `_parse_args` ligne 2218, bloc `__main__`)

- [ ] **Step 4.1 : l'autotest d'abord**

Dans `_smoke()`, juste APRÈS la boucle qui se termine par :

```python
            f"--refresh {mauvais:g} est REFUSÉ avant d'ouvrir la moindre fenêtre (il divisait par "
            f"zéro après, donc traceback nu et plein écran resté à l'écran)")
```

ajouter :

```python
    # --- `ecran_hz` : l'écran du stimulus ------------------------------------------------------
    # `refresh` tient ici le rôle de la MESURE : l'écran factice n'a pas de vsync. Le refus arrive
    # AVANT le flux de marqueurs : sinon une horloge fantôme resterait sur le réseau.
    module = globals()
    vrai_outlet, crees = module["StreamOutlet"], []

    def _espion(*a, **k):
        crees.append(a)
        return vrai_outlet(*a, **k)

    module["StreamOutlet"] = _espion
    try:
        try:
            run(windowed=True, refresh=165.0, ecran_hz=60.0, max_frames=L,
                stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0)
            refus_ecran = None
        except EcranRefuse as e:
            refus_ecran = str(e)
        chk(refus_ecran is not None and "165" in refus_ecran and "60" in refus_ecran
            and not crees,
            f"un écran mesuré à 165 Hz pour 60 Hz demandés : REFUS qui nomme les deux, avant "
            f"tout flux de marqueurs ({refus_ecran}, {len(crees)} flux créé(s))")
        journal_ecran = []
        run(windowed=True, refresh=59.6, ecran_hz=60.0, max_frames=2 * L,
            stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
            journal=journal_ecran)
        cycles_ecran = [m for m, _ts, _f, _c in journal_ecran if m.get("event") == "cycle"]
        chk(len(crees) == 1 and cycles_ecran
            and all(m.get("refresh") == 60.0 for m in cycles_ecran),
            f"un écran mesuré à 59,6 Hz pour 60 demandés : chaque marqueur de cycle porte 60, le "
            f"VOULU, celui que le modèle apprendra ({[m.get('refresh') for m in cycles_ecran]})")
    finally:
        module["StreamOutlet"] = vrai_outlet
```

- [ ] **Step 4.2 : vérifier qu'il échoue**

Run : `.venv/Scripts/python src/stimulus/cvep.py --smoke`
Expected : `NameError: name 'EcranRefuse' is not defined` (ou `TypeError` sur `ecran_hz`).

- [ ] **Step 4.3 : les imports**

Juste après `from stimulus import fermeture  # noqa: E402 - le dernier geste, partagé par les 4 fenêtres`,
ajouter :

```python
from stimulus.ecran import EcranRefuse, au_rafraichissement, confirme, hz_positif  # noqa: E402
```

Dans `run()`, remplacer :

```python
    from stimulus.refresh import measure_refresh  # même mesure que les autres stimuli
```

par :

```python
    from stimulus.refresh import frequence_mesuree, measure_refresh  # comme les autres stimuli
```

- [ ] **Step 4.4 : `run()`**

Dans la signature de `run`, remplacer `        source_statut=None):` par :

```python
        source_statut=None, ecran_hz=None):
```

Dans la docstring de `run`, juste après le premier paragraphe (celui qui finit par
``    (cf. `stimulus/retour.py`).``), ajouter :

```python

    `ecran_hz` (`--ecran-hz`) : le rafraîchissement auquel la séance DOIT tourner, celui que
    portera chaque marqueur, donc le modèle. L'écran a été passé à cette valeur avant l'appel
    (`stimulus/ecran.py`) ; ici, on le MESURE, et on lève `EcranRefuse` s'il ne la tient pas,
    avant de créer le moindre flux. `refresh`, s'il est donné aussi, tient lieu de mesure.
```

Remplacer :

```python
    pygame.mouse.set_visible(False)

    if refresh is None:
        refresh = measure_refresh(pygame, win)
```

par :

```python
    pygame.mouse.set_visible(False)

    if ecran_hz is not None:
        try:
            refresh = confirme(ecran_hz, refresh if refresh is not None
                               else frequence_mesuree(pygame, win))
        except EcranRefuse:
            # On FERME tout avant de propager : un plein écran noir cacherait la raison du refus.
            pygame.quit()
            for s in (source_dec, source_rep):
                if s is not None:
                    s.fermer()
            if fichier_log is not None:
                fichier_log.close()
            raise
    elif refresh is None:
        refresh = measure_refresh(pygame, win)
```

- [ ] **Step 4.5 : l'option**

Dans `_parse_args`, remplacer :

```python
    p.add_argument("--refresh", type=float, default=None,
                   help="forcer le refresh (Hz) — sinon auto-mesuré. C'est la valeur PUBLIÉE dans "
                        "chaque marqueur : le moteur refuse tout marqueur qui s'écarte de plus de "
                        "1 Hz du refresh auquel le modèle a été calibré, et le dit")
```

par :

```python
    rafraichissement = p.add_mutually_exclusive_group()
    rafraichissement.add_argument(
        "--refresh", type=float, default=None,
        help="forcer le refresh (Hz) — sinon auto-mesuré. C'est la valeur PUBLIÉE dans chaque "
             "marqueur : le moteur refuse tout marqueur qui s'écarte de plus de 1 Hz du refresh "
             "auquel le modèle a été calibré, et le dit")
    rafraichissement.add_argument(
        "--ecran-hz", type=hz_positif, default=None,
        help="le rafraîchissement auquel AFFICHER (Hz) : l'écran principal y passe le temps de la "
             "séance, puis revient, et la fenêtre REFUSE (sortie 2) si l'écran ne le tient pas. "
             "C'est ce que la console passe : le réglage d'« Entraîner », ou celui du modèle")
```

- [ ] **Step 4.6 : le bloc `__main__`**

Remplacer :

```python
    ok = run(windowed=args.windowed, refresh=args.refresh, seconds=args.seconds,
             smoke=args.smoke, seed=args.seed, log_path=args.log,
             calibrer=args.calibrer or args.tester, tester=args.tester,
             cycles_calib=args.cycles, libre=args.libre, retour=args.retour,
             attente_consommateur_s=0.0 if args.no_wait else 5.0)
    sys.exit(0 if ok else 1)
```

par :

```python
    try:
        with au_rafraichissement(args.ecran_hz):
            ok = run(windowed=args.windowed, refresh=args.refresh, seconds=args.seconds,
                     smoke=args.smoke, seed=args.seed, log_path=args.log,
                     calibrer=args.calibrer or args.tester, tester=args.tester,
                     cycles_calib=args.cycles, libre=args.libre, retour=args.retour,
                     attente_consommateur_s=0.0 if args.no_wait else 5.0,
                     ecran_hz=args.ecran_hz)
    except EcranRefuse as refus:
        # Sortie 2 : la fenêtre n'a rien affiché. L'écran est déjà revenu (sortie du `with`).
        print(f"[cvep-stim] ⚠️ REFUS : {refus}")
        sys.exit(2)
    sys.exit(0 if ok else 1)
```

- [ ] **Step 4.7 : l'autotest passe**

Run : `.venv/Scripts/python src/stimulus/cvep.py --smoke`
Expected : les deux nouvelles lignes `OK`, `[cvep-stim] VERDICT : OK`, sortie 0.

- [ ] **Step 4.8 : commit**

```bash
git add src/stimulus/cvep.py
git commit -m "c-VEP window: --ecran-hz runs the code at the wanted refresh rate, or refuses" -m "Every cycle marker carries the wanted rate, the one the model learns." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5 : le registre déclare les fenêtres qui font passer l'écran

**Files:**
- Modify: `src/stimulus/registry.py`

- [ ] **Step 5.1 : l'autotest d'abord**

Dans `_selftest()`, juste après :

```python
    inconnus += [(k, a) for k, args in LIBRE.items() for a in args if not _declare(k, a)]
```

ajouter :

```python
    inconnus += [(k, "--ecran-hz") for k in ECRAN if not _declare(k, "--ecran-hz")]
```

Et juste AVANT `    print(f"[stim-registry] VERDICT : {'OK' if ok else 'PROBLÈME'}")`, ajouter :

```python
    # --- L'ÉCRAN DU STIMULUS ----------------------------------------------
    chk(option_ecran("cvep", 60.0) == ("--ecran-hz", "60")
        and option_ecran("ssvep", "59.94") == ("--ecran-hz", "59.94"),
        f"le rafraîchissement part sous `--ecran-hz`, écrit sans zéro inutile "
        f"({option_ecran('cvep', 60.0)}, {option_ecran('ssvep', '59.94')})")
    chk(option_ecran("cvep", None) == () and option_ecran("cvep", 0) == ()
        and option_ecran("cvep", "abc") == () and option_ecran("p300", 60.0) == (),
        "…et rien sans valeur, sur une valeur absurde, ou pour une fenêtre qui ne fait pas "
        "passer l'écran : elle mesure alors l'écran, comme avant")
    chk(set(ECRAN) == {"ssvep", "cvep"} and set(ECRAN.values()) <= {"reglage", "modele"},
        f"seuls le SSVEP et le c-VEP font passer l'écran, et chacun dit d'où vient la valeur "
        f"({ECRAN})")
```

- [ ] **Step 5.2 : vérifier qu'il échoue**

Run : `.venv/Scripts/python src/stimulus/registry.py`
Expected : `NameError: name 'ECRAN' is not defined`.

- [ ] **Step 5.3 : la table et l'option**

Juste après la fonction `option_frequences` (qui finit par
`    return (argument, ",".join(f"{float(f):g}" for f in freqs))`), ajouter :

```python


# Les fenêtres qui font passer l'écran principal au rafraîchissement voulu (`--ecran-hz`), et
# d'où vient ce rafraîchissement hors entraînement : le RÉGLAGE du mode pour le SSVEP, le MODÈLE
# choisi pour le c-VEP, qui ne marche qu'au rafraîchissement de son entraînement. À
# l'entraînement, il vient des réglages d'« Entraîner ». La console demande, elle ne sait pas.
ECRAN = {"ssvep": "reglage", "cvep": "modele"}


def option_ecran(stimulus_id, hz):
    """Les arguments qui font passer l'écran à `hz` Hz. `()` si la fenêtre ne sait pas, ou si `hz`
    n'est pas un nombre positif : la fenêtre mesure alors l'écran, comme avant."""
    if stimulus_id not in ECRAN:
        return ()
    try:
        hz = float(hz)
    except (TypeError, ValueError):
        return ()
    if hz <= 0:
        return ()
    return ("--ecran-hz", f"{hz:g}")
```

- [ ] **Step 5.4 : l'autotest passe**

Run : `.venv/Scripts/python src/stimulus/registry.py`
Expected : `[stim-registry] VERDICT : OK`, sortie 0.

- [ ] **Step 5.5 : commit**

```bash
git add src/stimulus/registry.py
git commit -m "Stimulus registry: which windows switch the screen, and where the rate comes from" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6 : un modèle c-VEP dit son rafraîchissement sans être rechargé

**Files:**
- Modify: `src/core/cvep_models.py` (`decrire` ligne 238, autotest en fin de fichier)

- [ ] **Step 6.1 : l'autotest d'abord**

Remplacer la fin de `_selftest()` :

```python
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[cvep-models] VERDICT : {'OK' if ok else 'PROBLÈME'}")
```

par :

```python
        # --- Le RAFRAÎCHISSEMENT d'un modèle, lu sans le recharger ---------------------------
        ecca_hz = _ecca().save(_os.path.join(dossier, "cvep_model_hz.npz"), n_targets=6)
        rcca_hz = _rcca(codes_du_jour).save(_os.path.join(dossier, "cvep_rcca_model_hz.npz"))
        chk(refresh_de(ecca_hz) == 60.0 and refresh_de(rcca_hz) == 60.0
            and decrire(ecca_hz)["refresh"] == 60.0,
            f"un modèle dit le rafraîchissement de son entraînement, eCCA comme rCCA "
            f"({refresh_de(ecca_hz)}, {refresh_de(rcca_hz)}, {decrire(ecca_hz)['refresh']})")
        seul = _os.path.join(dossier, "seul_refresh.npz")
        _np.savez(seul, refresh=75.0)
        chk(refresh_de(seul) == 75.0 and charger(seul)[0] is None,
            "…lu dans le SEUL champ `refresh`, sans charger le modèle : un rCCA ré-ajuste au "
            "chargement, et la console le lit à chaque lancement de fenêtre")
        sans = _os.path.join(dossier, "sans_refresh.npz")
        _np.savez(sans, w=_np.ones(3))
        piege = _os.path.join(dossier, "refresh_pickle.npz")
        _np.savez(piege, refresh=_np.array([{"x": 1}], dtype=object))
        chk(all(refresh_de(c) is None for c in (None, "", _os.path.join(dossier, "absent.npz"),
                                                sans, piege)),
            "…et None, sans lever ni dépickler, pour un chemin vide ou absent, un fichier sans "
            "champ `refresh`, ou un `refresh` en pickle")
        chk(decrire(_os.path.join(dossier, "absent.npz"))["refresh"] is None,
            "…et `decrire` d'un fichier absent porte la clé, à None")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[cvep-models] VERDICT : {'OK' if ok else 'PROBLÈME'}")
```

- [ ] **Step 6.2 : vérifier qu'il échoue**

Run : `.venv/Scripts/python src/core/cvep_models.py`
Expected : `NameError: name 'refresh_de' is not defined`.

- [ ] **Step 6.3 : `refresh_de`, et la clé de `decrire`**

Juste AVANT `def decrire(chemin):`, ajouter :

```python
def refresh_de(chemin):
    """Le rafraîchissement auquel ce modèle a été entraîné, en Hz, ou None s'il ne se lit pas.

    Ne lit QUE le champ `refresh`, sans charger le modèle : un rCCA ré-ajuste au chargement, et la
    console pose la question à chaque lancement de fenêtre. Sans `allow_pickle`, comme `charger` :
    un champ en pickle rend None au lieu d'exécuter quoi que ce soit. Ne lève jamais.
    """
    if not chemin or not _os.path.isfile(chemin):
        return None
    try:
        with _np.load(chemin) as d:
            if "refresh" not in d.files:
                return None
            valeur = float(d["refresh"])
    except Exception:  # noqa: BLE001 - « ne lève jamais » : tout fichier illisible rend None
        return None
    return valeur if valeur > 0 else None


```

Dans `decrire`, remplacer :

```python
        "n_epoques": None,
        "probleme": raison,
    }
```

par :

```python
        "n_epoques": None,
        "refresh": None,
        "probleme": raison,
    }
```

et remplacer :

```python
    infos["decodeur"] = modele.decoder
```

par :

```python
    infos["decodeur"] = modele.decoder
    infos["refresh"] = float(modele.refresh)
```

Dans la docstring de `decrire`, remplacer la première ligne
`    """Une ligne lisible pour la liste de la console : date, décodeur, justesse honnête, cibles.`
par :

```python
    """Une ligne lisible pour la liste de la console : date, décodeur, justesse honnête, cibles,
    et le rafraîchissement de l'entraînement, le seul auquel le modèle marche.
```

- [ ] **Step 6.4 : l'autotest passe**

Run : `.venv/Scripts/python src/core/cvep_models.py`
Expected : `[cvep-models] VERDICT : OK`, sortie 0.

- [ ] **Step 6.5 : commit**

```bash
git add src/core/cvep_models.py
git commit -m "c-VEP models: read the training refresh rate without reloading the model" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7 : l'entraînement c-VEP règle son rafraîchissement

**Files:**
- Modify: `src/core/modes/cvep.py` (import ligne 112, `Calib.params` ligne 781, autotest ligne 1011)
- Modify: `src/core/modes/cvep_calib.py` (import ligne 74, `chemins_libres` ligne 366,
  `entrainer_dans` ligne 543, `CVEPCalibration`, autotest)
- Modify: `src/core/langues/fr/modes.json`, `src/core/langues/en/modes.json`

- [ ] **Step 7.1 : l'autotest du mode d'abord**

Dans `src/core/modes/cvep.py`, `_selftest()`, juste APRÈS :

```python
    chk(SPEC.calibration is not None and SPEC.calibration.kind == "fenetre"
        and SPEC.calibration.stimulus_id == "cvep",
        "sa calibration est menée par une FENÊTRE : le code doit défiler frame par frame, et le "
        "marqueur de cycle qu'elle publie est l'horloge sans laquelle il n'y a pas de phase")
```

ajouter :

```python
    p_ecran = {p.key: p for p in SPEC.calibration.params}.get("refresh_hz")
    chk(p_ecran is not None and p_ecran.default == 60.0
        and (p_ecran.min, p_ecran.max) == (30.0, 480.0)
        and "refresh_hz" not in {p.key for p in SPEC.params},
        f"le rafraîchissement se règle à l'ENTRAÎNEMENT (60 Hz par défaut, de 30 à 480), jamais "
        f"dans « Régler » : le modèle n'apprend que lui "
        f"({p_ecran and (p_ecran.default, p_ecran.min, p_ecran.max)})")
```

- [ ] **Step 7.2 : l'autotest de la calibration**

Dans `src/core/modes/cvep_calib.py`, `_selftest()` :

(a) juste APRÈS :

```python
        chk(bool(res.get("enregistrement")) and _os.path.exists(res["enregistrement"]),
            f"…et les époques BRUTES sont archivées à côté ({res.get('enregistrement')})")
```

ajouter :

```python
        noms = [_os.path.basename(res.get(c) or "") for c in ("modele", "modele_rcca",
                                                              "enregistrement")]
        chk(all(n.endswith(f"_{REFRESH:g}Hz.npz") for n in noms),
            f"les TROIS fichiers portent le rafraîchissement de la séance dans leur nom : c'est le "
            f"titre que la console affiche dans la liste des modèles ({noms})")
```

(b) juste APRÈS :

```python
            f"…tandis qu'un émetteur à 60 Hz est REFUSÉ, en nommant les deux chiffres : c'est ce "
            f"refus qui rend le test précédent falsifiable ({refus60})")
```

ajouter :

```python
        chk(_os.path.basename(res80.get("modele") or "").endswith("_80Hz.npz"),
            f"…et son nom le DIT ({_os.path.basename(res80.get('modele') or '')})")

        # --- 5 bis 0. Le rafraîchissement que l'entraînement DEMANDE (`refresh_hz`) --------------
        # Dans un SOUS-dossier : le compte des modèles écrits à la racine, plus bas, reste le sien.
        dossier_hz = _os.path.join(dossier, "refresh_demande")
        _os.makedirs(dossier_hz, exist_ok=True)
        marq_hz, eeg_hz, ts_hz, att_hz = seance(refresh=80.0, graine=2)
        moteur_ok = _MoteurFactice(eeg_hz, ts_hz)
        rt_ok = CVEPCalibration(_cvep.SPEC, {"refresh_hz": 80.0}, moteur_ok, dossier=dossier_hz)
        duree_80 = rt_ok.duree_estimee_s() - rt_ok.warmup_s
        chk(abs(duree_80 - CVEPCalibration.duree_protocole_s * 60.0 / 80.0) < 1e-9,
            f"la durée annoncée suit le rafraîchissement demandé : le protocole compte des images, "
            f"plus courtes à 80 Hz ({duree_80:.1f} s, contre "
            f"{CVEPCalibration.duree_protocole_s:.1f} s à 60 Hz)")
        joue(rt_ok, moteur_ok, marq_hz, att_hz)
        chk(rt_ok.phase == "fini" and rt_ok.resultat is not None,
            f"réglé à 80 Hz, affiché à 80 Hz : l'entraînement va au bout "
            f"({rt_ok.phase}, {rt_ok.probleme})")
        moteur_ko = _MoteurFactice(eeg_hz, ts_hz)
        rt_ko = CVEPCalibration(_cvep.SPEC, {"refresh_hz": 60.0}, moteur_ko, dossier=dossier_hz)
        joue(rt_ko, moteur_ko, marq_hz, att_hz)
        chk(rt_ko.phase == "annule" and rt_ko.resultat is None and rt_ko.essai == 0
            and "80" in (rt_ko.probleme or "") and "60" in (rt_ko.probleme or ""),
            f"réglé à 60 Hz mais affiché à 80 Hz : ABANDONNÉ au premier marqueur de cycle, sans "
            f"une époque, en nommant les deux ({rt_ko.phase}, {rt_ko.essai} époque(s), "
            f"{(rt_ko.probleme or '')[:90]})")
        chk(len(_glob.glob(_os.path.join(dossier_hz, "*cvep_model*.npz"))) == 1,
            f"…et seule la séance au bon rafraîchissement a écrit un modèle "
            f"({_glob.glob(_os.path.join(dossier_hz, '*cvep_model*.npz'))})")
```

- [ ] **Step 7.3 : vérifier que les deux échouent**

Run :

```bash
.venv/Scripts/python src/core/modes/cvep.py
.venv/Scripts/python src/core/modes/cvep_calib.py
```

Expected : `cvep.py` a une `ÉCHEC` de plus que l'existante (« le rafraîchissement se règle à
l'ENTRAÎNEMENT ») ; `cvep_calib.py` rougit sur les noms de fichiers, la durée, et l'abandon.

- [ ] **Step 7.4 : les textes**

Fragment `calib_fr.json` :

```json
{
  "calib.cvep.param.refresh_hz.aide": "Le rafraîchissement auquel ton application affichera le code, en images par seconde. Le modèle ne marchera qu'à ce rafraîchissement : règle celui de ton application. Si l'écran de ce poste n'y est pas, il y passe le temps de l'entraînement, puis revient.",
  "calib.cvep.param.refresh_hz.label": "Rafraîchissement de l'écran du stimulus",
  "calib.cvep.refresh_autre": "La fenêtre affiche à {annonce} Hz, mais l'entraînement est réglé à {voulu} Hz : le modèle ne marcherait pas pour ton application. Rien n'a été entraîné. Relance « Entraîner » depuis la console : elle règle l'écran elle-même."
}
```

Fragment `calib_en.json` :

```json
{
  "calib.cvep.param.refresh_hz.aide": "The refresh rate at which your application will display the code, in frames per second. The model will only work at this refresh rate: set your application's. If this computer's screen is not at it, the screen switches to it for the training, then back.",
  "calib.cvep.param.refresh_hz.label": "Stimulus screen refresh rate",
  "calib.cvep.refresh_autre": "The window displays at {annonce} Hz, but the training is set to {voulu} Hz: the model would not work for your application. Nothing was trained. Start \"Train\" again from the console: it sets the screen itself."
}
```

Run :

```bash
.venv/Scripts/python -I <tmp>/ajoute_textes.py src/core/langues/fr/modes.json <tmp>/calib_fr.json
.venv/Scripts/python -I <tmp>/ajoute_textes.py src/core/langues/en/modes.json <tmp>/calib_en.json
```

- [ ] **Step 7.5 : le réglage dans le contrat du mode**

Dans `src/core/modes/cvep.py`, remplacer :

```python
from core.modes.cvep_calib import BRIEFING as BRIEFING_CALIB, CVEPCalibration  # noqa: E402
```

par :

```python
from core.modes.cvep_calib import BRIEFING as BRIEFING_CALIB, CVEPCalibration  # noqa: E402
from core.modes.cvep_calib import REFRESH_REFERENCE_HZ  # noqa: E402
```

et remplacer :

```python
        params=params_bande(CVEP_BAND, _COUPURE_BASSE, _COUPURE_HAUTE,
                            tr("calib.cvep.param.bande.aide", plancher=_COUPURE_BASSE[0])),
```

par :

```python
        params=(*params_bande(CVEP_BAND, _COUPURE_BASSE, _COUPURE_HAUTE,
                              tr("calib.cvep.param.bande.aide", plancher=_COUPURE_BASSE[0])),
                # Le RAFRAÎCHISSEMENT auquel l'application affichera le code : le modèle n'apprend
                # que celui-là, et le moteur refuse une horloge à plus de 1 Hz de lui. Il se règle
                # donc ICI, comme la bande, jamais dans « Régler ». La fenêtre d'entraînement fait
                # passer l'écran du poste à cette valeur (`stimulus/ecran.py`). Pas sous 30 Hz : un
                # cycle y dure 2,1 s, la plus longue époque que couvre le tampon du moteur
                # (`marker_epoch_s`, plus bas).
                Param(key="refresh_hz", label=tr("calib.cvep.param.refresh_hz.label"),
                      kind="float", unit="Hz", default=REFRESH_REFERENCE_HZ, min=30.0, max=480.0,
                      help=tr("calib.cvep.param.refresh_hz.aide"))),
```

- [ ] **Step 7.6 : les noms de fichiers**

Dans `src/core/modes/cvep_calib.py`, remplacer :

```python
def chemins_libres(dossier, n_epoques, prefixe=""):
```

par :

```python
def chemins_libres(dossier, n_epoques, prefixe="", refresh=None):
```

Dans sa docstring, juste avant le `"""` de fin, ajouter :

```python

    `refresh` : le rafraîchissement de la séance. Les trois noms le portent en suffixe
    (`…_60Hz.npz`) : la liste de la console montre le nom du fichier, c'est le titre du modèle,
    et un modèle ne marche qu'à ce rafraîchissement.
```

Dans son corps, remplacer :

```python
    maintenant = _time.time()
    while True:
        stamp = horodatage(maintenant)
        ecca = _os.path.join(dossier, f"{prefixe}cvep_model_{stamp}.npz")
        rcca = _os.path.join(dossier, f"{prefixe}cvep_rcca_model_{stamp}.npz")
        npz = _os.path.join(dossier,
                            f"{prefixe}cvep_calib_{stamp}_n{int(n_epoques):03d}.npz")
```

par :

```python
    suffixe = f"_{float(refresh):g}Hz" if refresh else ""
    maintenant = _time.time()
    while True:
        stamp = horodatage(maintenant)
        ecca = _os.path.join(dossier, f"{prefixe}cvep_model_{stamp}{suffixe}.npz")
        rcca = _os.path.join(dossier, f"{prefixe}cvep_rcca_model_{stamp}{suffixe}.npz")
        npz = _os.path.join(dossier,
                            f"{prefixe}cvep_calib_{stamp}_n{int(n_epoques):03d}{suffixe}.npz")
```

Dans `entrainer_dans`, remplacer :

```python
    chemin_ecca, chemin_rcca, chemin_npz = chemins_libres(dossier, len(labels), prefixe=prefixe)
```

par :

```python
    chemin_ecca, chemin_rcca, chemin_npz = chemins_libres(dossier, len(labels), prefixe=prefixe,
                                                          refresh=refresh)
```

- [ ] **Step 7.7 : la calibration**

Remplacer `from core.i18n import tr  # noqa: E402` par :

```python
from core.i18n import nombre, tr  # noqa: E402
```

Dans `CVEPCalibration.__init__`, juste après `        self._blocs = 0                # blocs ouverts par un `cue``,
ajouter :

```python
        # Le rafraîchissement que cet entraînement DEMANDE (son réglage `refresh_hz`), ou None sans
        # réglage. La fenêtre le tient ; le PREMIER marqueur de cycle le confirme (`_etiquette`).
        voulu = self.params.get("refresh_hz")
        self.refresh_voulu = float(voulu) if voulu is not None else None
```

Dans la propriété `refresh`, remplacer :

```python
        return REFRESH_REFERENCE_HZ if self._refresh_seance is None else self._refresh_seance
```

par :

```python
        if self._refresh_seance is None:
            return self.refresh_voulu or REFRESH_REFERENCE_HZ
        return self._refresh_seance
```

et dans sa docstring, remplacer ``        Avant le premier marqueur : `REFRESH_REFERENCE_HZ`, pour que `pre_s` ait une valeur``
par ``        Avant le premier marqueur : le rafraîchissement DEMANDÉ, sinon `REFRESH_REFERENCE_HZ`, pour que `pre_s` ait une valeur``.

Juste APRÈS la propriété `post_s` (qui finit par `        return 0.0`), ajouter :

```python

    def duree_estimee_s(self):
        """La chauffe, plus le protocole au rafraîchissement DEMANDÉ : le protocole compte des
        images, et `duree_protocole_s` les compte à `REFRESH_REFERENCE_HZ`."""
        hz = self.refresh_voulu or REFRESH_REFERENCE_HZ
        return float(self.warmup_s) + self.duree_protocole_s * REFRESH_REFERENCE_HZ / hz
```

Dans `_etiquette`, remplacer :

```python
        if event != "cycle":
            return None      # un événement inconnu s'ignore : le protocole grandira

        refresh, souci = self._refresh_lisible(marqueur.get("refresh"))
```

par :

```python
        if event != "cycle":
            return None      # un événement inconnu s'ignore : le protocole grandira

        annonce = marqueur.get("refresh")
        if self._refresh_seance is None and self._ecran_autre(annonce):
            # Le PREMIER marqueur dit à quel rafraîchissement la fenêtre affiche. S'il n'est pas
            # celui que l'entraînement demande, la séance entraînerait un modèle pour un autre
            # écran que celui de l'application : on l'abandonne en le disant, avant toute époque.
            self._abandonne(tr("calib.cvep.refresh_autre", annonce=nombre(float(annonce)),
                               voulu=nombre(self.refresh_voulu)))
            return None
        refresh, souci = self._refresh_lisible(annonce)
```

Juste AVANT `    def _refresh_lisible(self, refresh):`, ajouter :

```python
    def _ecran_autre(self, annonce):
        """Vrai si `annonce` est un rafraîchissement LISIBLE à plus de 1 Hz de celui que
        l'entraînement demande. Sans réglage, ou sur une valeur illisible, rien n'est jugé ici :
        `_refresh_lisible` refuse l'illisible."""
        if self.refresh_voulu is None:
            return False
        if isinstance(annonce, bool) or not isinstance(annonce, (int, float)) or annonce <= 0:
            return False
        return abs(float(annonce) - self.refresh_voulu) > 1.0

```

- [ ] **Step 7.8 : les autotests passent**

Run :

```bash
.venv/Scripts/python src/core/modes/cvep_calib.py
.venv/Scripts/python src/core/modes/cvep.py
.venv/Scripts/python src/core/i18n.py
```

Expected : `cvep_calib.py` → `VERDICT : OK`. `cvep.py` → la seule `ÉCHEC` restante est
l'existante (« exiger plus de votes que de fenêtres », faute de modèle dans `data/`).
`i18n.py` → `0 faute(s) — VERDICT : OK`.

- [ ] **Step 7.9 : commit**

```bash
git add src/core/modes/cvep.py src/core/modes/cvep_calib.py src/core/langues/fr/modes.json src/core/langues/en/modes.json
git commit -m "c-VEP training: the refresh rate is a training setting, carried in the model's file name" -m "The calibration refuses a window that shows another rate than the one set, at its first cycle marker, and its announced duration follows the rate." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8 : la durée du test c-VEP suit le rafraîchissement du modèle

**Files:**
- Modify: `src/core/modes/cvep_test.py` (`_duree_protocole_s` ligne 129, `duree_estimee_s` ligne
  232, autotest ligne 698)

- [ ] **Step 8.1 : l'autotest d'abord**

Juste APRÈS :

```python
            f"la durée annoncée suit `essais` : 3 -> 18 × (4 jetés + 1 + 2 de retour) + 1 cycles, "
            f"{rt3.duree_estimee_s() / 60:.1f} min ; 2 -> {rt2.duree_estimee_s() / 60:.1f} min")
```

ajouter :

```python
        hz_modele = rt3._decideur.model.refresh
        rt3._decideur.model.refresh = 120.0
        duree_120 = rt3.duree_estimee_s() - rt3.warmup_s
        rt3._decideur.model.refresh = hz_modele
        chk(abs(duree_120 - 127 * L / 120.0) < 1e-6,
            f"…et le rafraîchissement du MODÈLE : un modèle à 120 Hz fait un test deux fois plus "
            f"court ({duree_120:.1f} s)")
```

- [ ] **Step 8.2 : vérifier qu'il échoue**

Run : `.venv/Scripts/python src/core/modes/cvep_test.py`
Expected : une `ÉCHEC` sur « le rafraîchissement du MODÈLE ».

- [ ] **Step 8.3 : l'implémentation**

Remplacer :

```python
def _duree_protocole_s(cycles):
    """La séance de la fenêtre hors chauffe, à 60 Hz : par bloc le settle, les cycles enregistrés
    et la phase de retour, plus le cycle de garde dont le marqueur ferme le dernier bloc."""
```

par :

```python
def _duree_protocole_s(cycles, refresh=REFRESH_REFERENCE_HZ):
    """La séance de la fenêtre hors chauffe, à `refresh` Hz : par bloc le settle, les cycles
    enregistrés et la phase de retour, plus le cycle de garde dont le marqueur ferme le dernier
    bloc."""
```

remplacer :

```python
    return joues * len(_CODE) / REFRESH_REFERENCE_HZ
```

par :

```python
    return joues * len(_CODE) / float(refresh)
```

et dans `MesureCVEP`, remplacer :

```python
    def duree_estimee_s(self):
        return float(self.warmup_s) + _duree_protocole_s(self.params.get("essais", ESSAIS_DEFAUT))
```

par :

```python
    def duree_estimee_s(self):
        """La chauffe, plus la séance au rafraîchissement du MODÈLE testé : la fenêtre affiche à
        celui-là (la console le lui passe), et le protocole compte des images."""
        return float(self.warmup_s) + _duree_protocole_s(self.params.get("essais", ESSAIS_DEFAUT),
                                                         self._decideur.model.refresh)
```

- [ ] **Step 8.4 : l'autotest passe**

Run : `.venv/Scripts/python src/core/modes/cvep_test.py`
Expected : `[cvep-test] VERDICT : OK`, sortie 0.

- [ ] **Step 8.5 : commit**

```bash
git add src/core/modes/cvep_test.py
git commit -m "c-VEP test: the announced duration follows the model's refresh rate" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9 : la console passe le rafraîchissement aux fenêtres, et tend le filet de l'écran

**Files:**
- Modify: `src/console/fenetres.py` (imports ligne 32, classe `LanceurFenetre`, `arreter`, `_fini`)
- Modify: `src/console/app.py` (imports ligne 72, `_demarrer_calibration` ligne 730,
  `_lancer_fenetre_calibration` ligne 815, `_lancer_fenetre_mesure` ligne 822, `_lancer_fenetre`
  ligne 849, `_smoke`)
- Modify: `src/core/langues/fr/modes.json`, `src/core/langues/en/modes.json` (aide du SSVEP)

- [ ] **Step 9.1 : l'autotest d'abord — l'espion de l'écran**

Dans `src/console/app.py`, `_smoke()`, juste APRÈS la docstring de `_smoke` (avant
`    class _FauxMoteur:`), ajouter :

```python
    # L'autotest ne touche JAMAIS l'écran : le filet qui rétablit le rafraîchissement après chaque
    # fenêtre est remplacé par un espion, pour tout l'autotest (il tourne dans son propre
    # processus). L'espion sert aussi à vérifier que le filet est tendu (« 3 bis »).
    appels_ecran = []
    LanceurFenetre.retablir_ecran = staticmethod(lambda: appels_ecran.append("retablir"))
```

- [ ] **Step 9.2 : l'autotest — le test SSVEP et l'essai libre SSVEP**

Juste APRÈS :

```python
    chk(apres_freqs == ["12,15,20"],
        f"…et elle part avec les fréquences RETENUES du mode arrêté (12 · 15 · 20), pas celles du "
        f"dépôt ({argv_test[3:]})")
```

ajouter :

```python
    apres_ecran = (argv_test[argv_test.index("--ecran-hz") + 1:][:1]
                   if "--ecran-hz" in argv_test else [])
    chk(apres_ecran == ["60"],
        f"…et avec le rafraîchissement RETENU du mode, que l'écran du poste doit tenir pendant le "
        f"test ({argv_test[3:]})")
```

Juste APRÈS :

```python
    chk("--freqs" in argv_ess and argv_ess[argv_ess.index("--freqs") + 1:][:1] == ["12,15,20"],
        f"…et les FRÉQUENCES du mode : sans elles, l'indice entouré désignerait une autre flèche "
        f"que celle que le moteur a décodée ({argv_ess[3:]})")
```

ajouter :

```python
    chk("--ecran-hz" in argv_ess and argv_ess[argv_ess.index("--ecran-hz") + 1:][:1] == ["60"],
        f"…et le RAFRAÎCHISSEMENT du mode, que l'écran du poste doit tenir ({argv_ess[3:]})")
```

- [ ] **Step 9.3 : l'autotest — c-VEP, et le filet**

Juste AVANT la ligne :

```python
    # 4. Un mode qui TOURNAIT DÉJÀ (lancé depuis sa tuile, pour une application) : rien à
```

ajouter :

```python
    # 3 bis. L'ÉCRAN DU STIMULUS : la fenêtre part avec le rafraîchissement qu'elle doit tenir —
    #        celui d'« Entraîner », celui du MODÈLE choisi (c-VEP), celui du mode (SSVEP).
    import tempfile as _tempfile

    import numpy as _np

    _remise_a_zero()
    with _tempfile.TemporaryDirectory() as dossier_ecran:
        modele_75 = os.path.join(dossier_ecran, "cvep_model_20261021-120000_75Hz.npz")
        _np.savez(modele_75, refresh=75.0)
        sauve_ecran = console._dernier_etat
        console._dernier_etat = {"reglages": {"cvep": {"model": modele_75},
                                              "ssvep": {"refresh_hz": 120.0}}}
        vus = (console._ecran_hz("cvep", "cvep", {"refresh_hz": 144.0}, calibrer=True),
               console._ecran_hz("cvep", "cvep"),
               console._ecran_hz("cvep", None, {"model": modele_75}),
               console._ecran_hz("ssvep", "ssvep"),
               console._ecran_hz("p300", "p300"))
        chk(vus == (144.0, 75.0, 75.0, 120.0, None),
            f"le rafraîchissement d'une fenêtre : celui d'« Entraîner », celui du MODÈLE choisi "
            f"(c-VEP, lu dans son fichier, pour l'essai libre comme pour le test), celui du mode "
            f"(SSVEP), et rien pour une fenêtre qui ne fait pas passer l'écran ({vus})")
        console._lancer_fenetre("cvep", calibrer=True, params={"refresh_hz": 144.0})
        argv_cal = (_fenetres_lancees() or [[]])[-1]
        chk("--ecran-hz" in argv_cal and argv_cal[argv_cal.index("--ecran-hz") + 1:][:1] == ["144"]
            and "--calibrer" in argv_cal,
            f"« Entraîner » c-VEP lance sa fenêtre avec le rafraîchissement RÉGLÉ ({argv_cal[3:]})")
        avant_filet = len(appels_ecran)
        console.lanceur.arreter()
        chk(len(appels_ecran) == avant_filet + 1,
            f"une fenêtre TUÉE tend le filet qui rétablit l'écran "
            f"({len(appels_ecran) - avant_filet} appel(s))")
        console._dernier_etat = sauve_ecran
    _remise_a_zero()

```

- [ ] **Step 9.4 : vérifier qu'il échoue**

Run : `.venv/Scripts/python src/console/app.py --smoke`
Expected : des `ÉCHEC` sur `--ecran-hz` et une `AttributeError` sur `_ecran_hz` (le smoke peut
s'arrêter là).

- [ ] **Step 9.5 : le filet dans `src/console/fenetres.py`**

Juste après `from stimulus import registry as stimulus_registry  # noqa: E402`, ajouter :

```python
from stimulus import ecran as stimulus_ecran  # noqa: E402
```

Dans `class LanceurFenetre(QObject):`, juste après
`    change = Signal()      # l'état a bougé : la console doit repeindre son bandeau`, ajouter :

```python

    # Le FILET de l'écran : une fenêtre SSVEP ou c-VEP fait passer l'écran principal au
    # rafraîchissement de sa séance, et le rétablit en se fermant. Tuée (« Abandonner »,
    # fermeture de la console), elle ne le fait pas, et Windows ne le rétablit pas toujours seul.
    # Sans écart, le filet ne fait rien. Remplaçable : l'autotest de la console ne touche jamais
    # l'écran.
    retablir_ecran = staticmethod(stimulus_ecran.retablir_si_change)
```

Dans `arreter`, remplacer :

```python
        if hasattr(proc, "waitForFinished"):
            proc.waitForFinished(2000)
        self._quoi = ""
```

par :

```python
        if hasattr(proc, "waitForFinished"):
            proc.waitForFinished(2000)
        self.retablir_ecran()
        self._quoi = ""
```

Dans `_fini`, remplacer :

```python
        self._encaisser_sortie()
        self._proc = None
```

par :

```python
        self._encaisser_sortie()
        self.retablir_ecran()
        self._proc = None
```

- [ ] **Step 9.6 : le calcul du rafraîchissement dans `src/console/app.py`**

Juste après `from core import neuro_monitor  # noqa: E402  (les descriptions des indices, cf. _smoke)`,
ajouter :

```python
from core import cvep_models  # noqa: E402  (le rafraîchissement d'un modèle c-VEP, cf. _ecran_hz)
```

Juste AVANT `    def _mode_teste_par(self, mesure_id):`, ajouter :

```python
    def _ecran_hz(self, stimulus_id, mode_id, params=None, calibrer=False):
        """Le rafraîchissement auquel cette fenêtre doit afficher, ou None : elle mesure alors
        l'écran, comme avant.

        À l'entraînement : celui des réglages d'« Entraîner ». Sinon, d'où le registre des
        fenêtres dit qu'il vient : le réglage du mode (SSVEP), ou le MODÈLE choisi (c-VEP), qui
        ne marche qu'au rafraîchissement de son entraînement — celui du test s'il en porte un,
        sinon celui du mode.
        """
        source = stimulus_registry.ECRAN.get(stimulus_id)
        if source is None:
            return None
        params = params or {}
        if calibrer:
            return params.get("refresh_hz")
        reglages = self._reglages_du_mode(mode_id) if mode_id else {}
        if source == "modele":
            return cvep_models.refresh_de(params.get("model") or reglages.get("model"))
        return reglages.get("refresh_hz")

```

Dans `_demarrer_calibration`, remplacer :

```python
            lancer=lambda: self._lancer_fenetre_calibration(mode_id))
```

par :

```python
            lancer=lambda: self._lancer_fenetre_calibration(mode_id, demande["params"]))
```

Remplacer :

```python
    def _lancer_fenetre_calibration(self, mode_id):
        """La fenêtre d'une calibration, et l'annulation si elle refuse de s'ouvrir."""
        ouvert = self._lancer_fenetre(mode_id, calibrer=True)
```

par :

```python
    def _lancer_fenetre_calibration(self, mode_id, params=None):
        """La fenêtre d'une calibration, et l'annulation si elle refuse de s'ouvrir. `params` :
        les réglages d'« Entraîner », dont la fenêtre reçoit le rafraîchissement."""
        ouvert = self._lancer_fenetre(mode_id, calibrer=True, params=params)
```

Dans `_lancer_fenetre_mesure`, remplacer :

```python
        options.extend(stimulus_registry.option_compte(stimulus_id, (params or {}).get("essais")))
```

par :

```python
        options.extend(stimulus_registry.option_compte(stimulus_id, (params or {}).get("essais")))
        # Et le RAFRAÎCHISSEMENT que la fenêtre doit tenir : le réglage du mode (SSVEP), ou celui
        # du modèle testé (c-VEP). Sans lui, elle afficherait à celui de l'écran du poste.
        options.extend(stimulus_registry.option_ecran(
            stimulus_id, self._ecran_hz(stimulus_id, mode_id, params)))
```

Remplacer :

```python
    def _lancer_fenetre(self, mode_id, calibrer, libre=False):
```

par :

```python
    def _lancer_fenetre(self, mode_id, calibrer, libre=False, params=None):
```

Dans la docstring de `_lancer_fenetre`, juste avant le `"""` de fin, ajouter :

```python

        `params` : les réglages d'« Entraîner » quand `calibrer`, dont le rafraîchissement.
```

Et dans son corps, remplacer :

```python
        options.extend(stimulus_registry.option_frequences(
            stimulus_id, self._reglages_du_mode(mode_id).get("freqs")))
        # L'ESSAI LIBRE ajoute ce que le registre déclare
```

par :

```python
        options.extend(stimulus_registry.option_frequences(
            stimulus_id, self._reglages_du_mode(mode_id).get("freqs")))
        # 🔴 Et le RAFRAÎCHISSEMENT que la fenêtre doit tenir, quand elle sait faire passer l'écran.
        # Sans lui, elle afficherait à celui de l'écran du poste, et un modèle c-VEP ne décode
        # qu'au rafraîchissement de son entraînement.
        options.extend(stimulus_registry.option_ecran(
            stimulus_id, self._ecran_hz(stimulus_id, mode_id, params, calibrer)))
        # L'ESSAI LIBRE ajoute ce que le registre déclare
```

- [ ] **Step 9.7 : l'aide du rafraîchissement du SSVEP**

Créer `complete_texte.py` (dossier temporaire) :

```python
"""Ajoute une phrase à la fin d'un texte existant d'un catalogue, en gardant son format exact."""
import json
import sys

chemin, cle, phrase = sys.argv[1], sys.argv[2], sys.argv[3]
with open(chemin, encoding="utf-8") as f:
    d = json.load(f)
if phrase not in d[cle]:
    d[cle] = d[cle].rstrip() + " " + phrase
with open(chemin, "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps(d, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
print(cle, "->", d[cle][-90:])
```

Run :

```bash
.venv/Scripts/python -I <tmp>/complete_texte.py src/core/langues/fr/modes.json mode.ssvep.param.refresh_hz.aide "Pendant un test, l'écran de ce poste passe à cette valeur, puis revient."
.venv/Scripts/python -I <tmp>/complete_texte.py src/core/langues/en/modes.json mode.ssvep.param.refresh_hz.aide "During a test, this computer's screen switches to this value, then back."
```

- [ ] **Step 9.8 : l'autotest passe**

Run : `.venv/Scripts/python src/console/app.py --smoke`
Expected : `[console-smoke] VERDICT : OK`, sortie 0, et les nouvelles lignes `OK` :
`--ecran-hz` du test et de l'essai libre SSVEP, « 3 bis » c-VEP et filet.

- [ ] **Step 9.9 : commit**

```bash
git add src/console/app.py src/console/fenetres.py src/core/langues/fr/modes.json src/core/langues/en/modes.json
git commit -m "Console: windows get the refresh rate they must hold, and the screen is restored after each" -m "Training passes its setting, c-VEP test and free trial the chosen model's rate, SSVEP the mode's. After any window, even a killed one, the console puts the main screen back to its registered rate." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10 : vérification complète, puis l'essai réel sur ce poste

- [ ] **Step 10.1 : le bloc 0 de la QA**

Run (PowerShell, depuis la racine) — une ligne par commande, code de sortie et dernier verdict :

```powershell
$env:PYTHONUTF8 = '1'
$py = ".venv\Scripts\python.exe"
$cmds = @(
  @('src/core/server.py','--smoke'), @('src/console/app.py','--smoke'),
  @('src/stimulus/ssvep.py','--smoke'), @('src/stimulus/cvep.py','--smoke'),
  @('src/stimulus/p300.py','--smoke'), @('src/stimulus/errp.py','--smoke'),
  @('src/stimulus/ecran.py'), @('src/stimulus/registry.py'), @('src/core/cvep_models.py'),
  @('src/core/modes/mesure.py'), @('src/core/modes/mesure_marqueurs.py'),
  @('src/core/modes/affichage.py'), @('src/core/modes/alpha.py'),
  @('src/core/modes/ssvep_mesure.py'), @('src/core/modes/marker_calib.py'),
  @('src/core/modes/p300.py'), @('src/core/modes/cvep.py'), @('src/core/modes/cvep_calib.py'),
  @('src/core/modes/mi_test.py'), @('src/core/modes/p300_test.py'),
  @('src/core/modes/cvep_test.py'), @('src/core/modes/errp_test.py'),
  @('src/core/acquisition.py','--synthetic'), @('src/core/filtres_affichage.py'),
  @('src/core/i18n.py'))
foreach ($c in $cmds) {
  $log = & $py @c 2>&1 | Out-String
  $echecs = ([regex]::Matches($log, 'ÉCHEC')).Count
  $verdict = ($log -split "`n" | Select-String 'VERDICT' | Select-Object -Last 1)
  "{0,-3} échecs={1,-2} {2,-40} {3}" -f $LASTEXITCODE, $echecs, ($c -join ' '), $verdict
}
```

Expected : tout à `0`, sauf `src/core/modes/cvep.py` à `1` avec **exactement une** `ÉCHEC`,
l'existante (pas de modèle dans `data/`). Un `server.py --smoke` rouge sur
`[smoke-marqueurs-relance]` seul se rejoue une fois avant de conclure (résolution LSL lente).

- [ ] **Step 10.2 : l'essai réel de la fenêtre SSVEP, fenêtrée, à 60 Hz**

L'écran principal passe au noir une seconde, deux fois.

```bash
.venv/Scripts/python src/stimulus/ssvep.py --windowed --ecran-hz 60 --seconds 4
```

Expected : une ligne « Écran passé à 60 Hz le temps de la séance (il était à 165 Hz) »,
`refresh ecran : 60 Hz`, sortie 0. Puis :

```bash
.venv/Scripts/python -c "import sys; sys.path.insert(0, 'src'); from stimulus.ecran import systeme_de_la_machine as s; print(s().actuel())"
```

Expected : `165.0`.

- [ ] **Step 10.3 : le refus réel**

```bash
.venv/Scripts/python src/stimulus/ssvep.py --windowed --ecran-hz 75 --seconds 2; echo "sortie=$?"
```

Expected : `⚠️ REFUS : Cet écran ne sait pas afficher à 75 Hz : il propose 59 · 60 · 120 · 144 ·
165 Hz…`, `sortie=2`, écran inchangé.

- [ ] **Step 10.4 : la fenêtre c-VEP réelle, à 60 Hz**

```bash
.venv/Scripts/python src/stimulus/cvep.py --windowed --ecran-hz 60 --seconds 3 --no-wait
```

Expected : « Écran passé à 60 Hz… », `refresh écran : 60 Hz`, un bilan `fin : … cycles émis`,
sortie 0, et l'écran revenu à 165 Hz (commande de l'étape 10.2).

Si une fenêtre FENÊTRÉE mesure mal (composition de Windows) et refuse à tort, refaire l'étape sans
`--windowed` : c'est le plein écran que la console utilise.

---

### Task 11 : la documentation

**Files:** `CLAUDE.md`, `README.md`, `docs/qa.md`, `docs/recette.md`

- [ ] **Step 11.1 : vérifier le nom du champ des métadonnées**

Run : `grep -n -E 'refresh' src/core/lsl_io.py | head`
Expected : le champ s'appelle `refresh` dans la description du flux `decoded_cvep`. Si un autre
nom sort, l'utiliser dans le README à l'étape 11.3.

- [ ] **Step 11.2 : `CLAUDE.md`**

(a) Dans « Commandes utiles », juste après la ligne
`python src/stimulus/registry.py            # clé -> commande, et la correspondance avec le contrat`,
ajouter :

```text
python src/stimulus/ecran.py               # l'écran au rafraîchissement du stimulus (lit l'écran, ne le change pas)
```

(b) Juste AVANT `## Pièges matériels à connaître`, ajouter (en remplaçant `<RÉSULTAT TÂCHE 2>` par
ce que la tâche 2 a montré) :

```markdown
- **Le rafraîchissement se règle (2026-10-21)**, pour un écran ou une application qui ne tourne
  pas à 60 Hz. Le c-VEP le règle dans « Entraîner » (défaut 60, de 30 à 480) : le modèle le
  porte, jusque dans son nom (`cvep_model_…_60Hz.npz`), et « Tester » comme « Tester librement »
  le reprennent du modèle choisi (`cvep_models.refresh_de`). Le SSVEP garde le sien dans
  « Régler ». Les fenêtres SSVEP et c-VEP font passer l'écran PRINCIPAL à ce rafraîchissement le
  temps de la séance (`stimulus/ecran.py`, `--ecran-hz`, mode temporaire de Windows), le
  confirment par une mesure médiane, et refusent sinon ; la console rétablit l'écran après toute
  fenêtre, tuée comprise (`LanceurFenetre.retablir_ecran`). Sur ce poste : <RÉSULTAT TÂCHE 2>.
  **Jamais joué au casque** : ni un entraînement à un autre rafraîchissement que 60 Hz, ni l'effet
  du passage de l'écran sur une séance.
```

(c) À la fin de « Pièges matériels à connaître », ajouter :

```markdown
- **Une fenêtre SSVEP ou c-VEP change le rafraîchissement de l'écran principal** le temps de sa
  séance : noir d'une seconde à l'ouverture et à la fermeture, c'est voulu. Si l'écran restait au
  mauvais rafraîchissement (console plantée), le remettre dans Paramètres → Affichage.
```

- [ ] **Step 11.3 : `README.md`** (en anglais)

(a) Juste après le paragraphe qui finit par
`engine now refuses those, and the console has a **Propose** button that asks it for a valid set.`,
ajouter :

```markdown

The SSVEP test windows run at the refresh rate set on the page: if this computer's main screen
runs at another rate, they switch it for the length of the test, then switch it back.
```

(b) Juste après le paragraphe qui finit par
``says so. ⚠️ It refuses the *markers*, not the *start* — the mode keeps running and keeps publishing``
puis `` `-1`, so do not wait for a crash.``, ajouter :

```markdown

**Train at your application's refresh rate.** The code changes at every frame, so a c-VEP model
only works at the refresh rate it was trained at. Set it in **Train** (60 Hz by default). The model
carries it in its file name (`cvep_model_…_60Hz.npz`) and in the `refresh` field of the
`decoded_cvep` metadata, which your application can read. A 165 Hz screen cannot show a 60 Hz code
by itself — each bit would last 2.75 frames — so the training and test windows switch this
computer's main screen to the wanted rate while they are open, then switch it back.
```

- [ ] **Step 11.4 : `docs/qa.md`**

(a) Bloc 0.3 : juste après la ligne `python src/core/i18n.py` du bloc de commandes, ajouter
`python src/stimulus/ecran.py`, et remplacer `✅ **0.3.1** Quinze sorties à 0.` par
`✅ **0.3.1** Seize sorties à 0.`

(b) Remplacer :

```markdown
✅ **1.14.3** Même chose sur les pages « Entraîner » de l'**ErrP** (1–10), du **c-VEP** (2–45) et du **MI**
(8–30, plus une case **« FBCSP (banc de filtres) »** décochée).
```

par :

```markdown
✅ **1.14.3** Même chose sur les pages « Entraîner » de l'**ErrP** (1–10), du **c-VEP** (2–45, plus
**« Rafraîchissement de l'écran du stimulus ⓘ »** à 60) et du **MI** (8–30, plus une case
**« FBCSP (banc de filtres) »** décochée).
```

(c) Juste AVANT la ligne `# Bloc 2 — au casque` (et après le `---` qui la précède), insérer :

```markdown
### ☐ 1.18 — L'écran passe au rafraîchissement du stimulus (2026-10-21)

Board de test, sur un poste dont l'écran principal ne tourne pas à 60 Hz (le poste de dev : 165 Hz).
Note d'abord son rafraîchissement, dans Paramètres → Affichage → Affichage avancé : ___ Hz.

1. Page **SSVEP**, « 1. Régler » : « Rafraîchissement de l'écran du stimulus » à **60**,
   « Proposer », « Appliquer ». Puis **« Tester sur une session »** → « Commencer ».
   ✅ **1.18.1** L'écran passe au noir une seconde, puis le test clignote. Échap : l'écran revient
   au rafraîchissement noté plus haut.
2. Page **c-VEP** → **« Entraîner »**.
   ✅ **1.18.2** « Avant de commencer » montre **« Rafraîchissement de l'écran du stimulus ⓘ »** à
   60 ; « 1. Régler » ne le montre pas.
   « Commencer », laisse tourner ~30 s, puis **« Abandonner »**.
   ✅ **1.18.3** L'écran passe à 60 Hz pendant l'entraînement, et revient au rafraîchissement noté
   après l'abandon, alors que la fenêtre a été TUÉE.
3. Refais l'entraînement c-VEP jusqu'au bout (~3,1 min), et enregistre le modèle.
   ✅ **1.18.4** Dans la liste des modèles du c-VEP, son nom finit par **`_60Hz.npz`**.
4. Page **SSVEP** : un rafraîchissement que l'écran ne propose pas (75 sur le poste de dev),
   « Proposer », « Appliquer », « Tester sur une session » → « Commencer ».
   ✅ **1.18.5** Le bandeau dit que la fenêtre s'est arrêtée, avec la raison : l'écran ne sait pas
   afficher à 75 Hz, et la liste de ce qu'il propose. L'écran n'a pas changé.

❌ Régression : un écran qui ne revient pas à son rafraîchissement, une fenêtre qui s'ouvre au
mauvais rafraîchissement, un modèle c-VEP sans `_…Hz` dans son nom.

---

```

- [ ] **Step 11.5 : `docs/recette.md`**

Juste AVANT `## Niveau 2 — au casque` (et après le `---` qui la précède), insérer (en remplaçant
`<RÉSULTAT TÂCHE 2>`) :

```markdown
### 1.23 — Le rafraîchissement se règle, et l'écran du poste suit (2026-10-21)

**Pourquoi.** Le code c-VEP change à chaque image, donc un modèle n'apprend qu'un rafraîchissement :
le moteur refuse une horloge à plus de 1 Hz du modèle. L'application d'un étudiant affiche à SON
rafraîchissement, pas forcément à celui du poste qui entraîne. Le rafraîchissement se règle donc
dans « Entraîner », et le modèle le porte, jusque dans son nom (`…_60Hz.npz`).

**Pourquoi la fenêtre ne ralentit pas d'elle-même.** À 60 Hz une image dure 16,7 ms, soit 2,75
images d'un écran à 165 Hz. Tenir les bits 2 ou 3 images, 12 ou 18 ms, déformerait le code, et le
modèle apprendrait ce code déformé. La fenêtre fait donc passer l'écran principal au
rafraîchissement voulu, en mode TEMPORAIRE de Windows (`src/stimulus/ecran.py`), le confirme par
une mesure, et le rétablit en se fermant. La console tend un filet pour une fenêtre tuée. Le SSVEP
en profite : ses tests suivent le réglage de « Régler ».

**Sur le poste de dev** (écran principal à 165 Hz, qui propose 59 · 60 · 120 · 144 · 165) :
<RÉSULTAT TÂCHE 2>.

**Jamais vu au casque** : ni un entraînement à un autre rafraîchissement que 60 Hz, ni l'effet du
passage de l'écran sur une séance.

---

```

- [ ] **Step 11.6 : commit**

```bash
git add CLAUDE.md README.md docs/qa.md docs/recette.md docs/superpowers/specs/2026-10-21-rafraichissement-reglable-design.md docs/superpowers/plans/2026-10-21-rafraichissement-reglable.md
git commit -m "Docs: the refresh rate is a c-VEP training setting, and the stimulus screen follows it" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
