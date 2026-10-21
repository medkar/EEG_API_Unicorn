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
