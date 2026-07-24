"""Contexte partagé de l'appli unifiée : UNE fenêtre, UNE session casque, UN socket UDP.

Pourquoi centraliser : ouvrir/fermer la session BrainFlow entre deux modes coûte plusieurs
secondes (appairage Bluetooth) et fait perdre le buffer. Ici, `App` possède les ressources
et les modes se contentent de les emprunter — on passe du SSVEP au c-VEP instantanément.

Contient aussi les primitives d'affichage réutilisées par tous les modes (texte centré,
flèches, écrans de message) pour que les trois modes se ressemblent visuellement.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "examples"))
from config import CH_NAMES, UDP_HOST, UDP_PORT, apply_invert, signal_verdict  # noqa: E402
from ssvep_stimulus import arrow_polygon, measure_refresh  # noqa: E402

BG = (10, 10, 16)
FG = (225, 225, 235)
DIM = (120, 120, 140)
GO = (80, 210, 120)
WARN = (230, 160, 70)
ACCENT = (90, 170, 240)
OUTLINE = (55, 55, 70)
BAR_BG = (40, 40, 52)
ON_COLOR = (255, 255, 255)
FIX_DOT = (205, 60, 60)   # point de fixation : rouge = visible sur blanc ET sur noir
FIX_DOT_R = 2             # rayon en PIXELS (taille fixe, pas proportionnelle) -> ~5 px de diamètre


class Abort(Exception):
    """ESC pendant un mode -> retour au menu (et non sortie de l'appli)."""


class App:
    """Ressources partagées + état global (envoi robot, casque réel/synthétique)."""

    def __init__(self, windowed=False, synthetic=False, smoke=False, send=False,
                 host=UDP_HOST):
        if smoke:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
            synthetic = True
        import pygame

        self.pygame = pygame
        self.smoke = smoke
        self.synthetic = synthetic
        self.send = send
        self.host = host
        self._acq = None
        self._sender = None

        pygame.init()
        pygame.font.init()
        if windowed or smoke:
            size, flags = (1200, 820), pygame.SCALED
        else:
            info = pygame.display.Info()
            size, flags = (info.current_w, info.current_h), pygame.FULLSCREEN | pygame.SCALED
        try:  # vsync : indispensable au clignotement SSVEP/c-VEP
            self.win = pygame.display.set_mode(size, flags, vsync=1)
        except (TypeError, pygame.error):
            self.win = pygame.display.set_mode(size, flags)
        pygame.display.set_caption("EEG Waffle — pilotage par la pensée")
        pygame.mouse.set_visible(False)

        self.clock = pygame.time.Clock()
        span = min(size)
        self.big = pygame.font.SysFont("consolas", max(24, int(span * 0.042)), bold=True)
        self.mid = pygame.font.SysFont("consolas", max(17, int(span * 0.026)))
        self.small = pygame.font.SysFont("consolas", max(13, int(span * 0.019)))
        self.refresh = 60.0 if smoke else measure_refresh(pygame, self.win)

    # --- ressources paresseuses -----------------------------------------
    @property
    def acq(self):
        """Session BrainFlow, ouverte au premier besoin et gardée jusqu'à la sortie."""
        if self._acq is None:
            from acquisition import UnicornAcquisition
            self._acq = UnicornAcquisition(synthetic=self.synthetic).start()
        return self._acq

    def open_acq(self):
        """Ouvre la session casque en amont et RENVOIE un booléen, au lieu de crasher.

        L'Unicorn se coupe souvent (Bluetooth, veille, batterie) : le 2026-07-21, un casque
        en charge a fait remonter `BOARD_NOT_READY_ERROR:7` en plein `prepare_session()`, ce
        qui terminait l'appli en traceback au milieu d'un mode (juste après le choix des
        fréquences SSVEP). Mieux vaut un message clair et un retour au menu. Un échec laisse
        `_acq` à None (l'assignation n'a pas lieu), donc un nouvel essai est possible sans état
        résiduel. Retourne True si la session est prête, False sinon (message affiché).
        """
        if self._acq is not None:
            return True
        try:
            _ = self.acq                 # déclenche prepare_session() + start_stream()
            return True
        except Exception as e:           # BrainFlowError en tête, mais on ne veut RIEN laisser passer
            print(f"[app] casque indisponible : {e}")
            self.flash("Casque indisponible",
                       "Unicorn injoignable — allumé ? appairé ? batterie ? — retour au menu",
                       4.5)
            return False

    @property
    def sender(self):
        if self._sender is None:
            from send_joystick_udp import JoystickSender
            self._sender = JoystickSender(self.host, UDP_PORT)
        return self._sender

    def emit(self, jx, jy):
        """Envoi UDP si le mode robot est activé (sinon no-op). Applique la correction de sens."""
        if self.send and not self.smoke:
            self.sender.send(*apply_invert(jx, jy))

    def close(self):
        if self._sender is not None:
            try:
                self._sender.stop()
                self._sender.close()
            except OSError:
                pass
        if self._acq is not None:
            self._acq.stop()
        self.pygame.quit()

    # --- primitives d'affichage -----------------------------------------
    @property
    def size(self):
        return self.win.get_width(), self.win.get_height()

    def center(self, font, text, color, y):
        surf = font.render(text, True, color)
        self.win.blit(surf, surf.get_rect(center=(self.win.get_width() // 2, y)))

    def drain(self, on_key=None, pausable=False):
        """Vide la file d'événements. ESC/Q -> Abort. `on_key(event)` pour les autres touches.
        `pausable` : ESPACE ouvre l'écran de PAUSE — à n'utiliser qu'aux points d'attente SÛRS
        (entre essais/blocs, aucune époque en cours), JAMAIS pendant un stimulus timé."""
        for e in self.pygame.event.get():
            if e.type == self.pygame.QUIT:
                raise Abort
            if e.type == self.pygame.KEYDOWN:
                if e.key in (self.pygame.K_ESCAPE, self.pygame.K_q):
                    raise Abort
                if pausable and e.key == self.pygame.K_SPACE:
                    self.pause_screen()
                    continue
                if on_key is not None:
                    on_key(e)

    def pause_screen(self):
        """Fige l'appli : une touche reprend, Échap quitte (Abort -> menu). À déclencher UNIQUEMENT
        aux points sûrs (aucune époque en cours, aucun stimulus timé). No-op en smoke (headless)."""
        if self.smoke:
            return
        resume = []
        while not resume:
            self.drain(on_key=lambda e: resume.append(True))
            self.win.fill(BG)
            h = self.win.get_height()
            self.center(self.big, "PAUSE", ACCENT, int(h * 0.42))
            self.center(self.mid, "une touche pour reprendre     ·     Échap pour quitter",
                        DIM, int(h * 0.55))
            self.pygame.display.flip()
            self.clock.tick(30)

    def flash(self, title, subtitle, seconds, skippable=True, pausable=False):
        """Message centré pendant `seconds` (une touche passe si `skippable` ; ESPACE met en pause
        si `pausable`)."""
        import time
        skipped = []

        def _on_key(e):
            if pausable and e.key == self.pygame.K_SPACE:
                self.pause_screen()
            elif skippable:
                skipped.append(True)
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < seconds:
            self.drain(on_key=_on_key)
            if skipped:
                return
            self.win.fill(BG)
            h = self.win.get_height()
            self.center(self.big, title, FG, int(h * 0.44))
            self.center(self.mid, subtitle, DIM, int(h * 0.55))
            self.pygame.display.flip()
            self.clock.tick(60)
            if self.smoke:
                return

    def hud(self, text, color=DIM):
        self.win.blit(self.small.render(text, True, color), (14, 12))

    def signal_ok(self, seconds=1.0):
        """(tout_ok, [(nom, σ, verdict)]) — état instantané des voies. None si pas prêt."""
        sig = self.acq.quality(seconds)
        if sig is None:
            return None, []
        rows = [(CH_NAMES[i], float(s), signal_verdict(float(s)))
                for i, s in enumerate(sig)]
        return all(v == "ok" for _, _, v in rows), rows

    def signal_check(self, blocking=True, highlight=None, mode_label=None):
        """Écran de contrôle de la liaison casque AVANT tout enregistrement coûteux.

        Motivation : le 2026-07-20, un câble débranché a laissé enregistrer 3,4 min de signal
        plat, puis produire tranquillement un modèle à 0 %. Rien dans l'appli ne le signalait.
        Mieux vaut bloquer 5 secondes ici que perdre une séance entière.

        `highlight` : indices (dans CH_NAMES) des électrodes CLÉS du mode qu'on s'apprête à lancer
        -> elles sont ENCADRÉES et marquées d'une * (contact à vérifier/mouiller en priorité :
        occipitales pour SSVEP/c-VEP, C3/Cz/C4 pour MI, Fz/Cz/Pz pour P300). `mode_label` nomme
        le mode dans la légende. Retourne True si l'on peut continuer, False si annulé.
        """
        if not self.open_acq():   # casque injoignable -> message + retour menu, pas de crash
            return False
        highlight = set(highlight or [])
        pg = self.pygame
        while True:
            ok, rows = self.signal_ok()
            if self.smoke:
                return True
            pressed = []
            self.drain(on_key=lambda e: pressed.append(e))
            if pressed:
                return True   # une touche continue (même si défaut : à toi de juger) ; ESC -> Abort
            self.win.fill(BG)
            w, h = self.size
            self.center(self.big, "Contrôle de la liaison casque", FG, int(h * 0.14))
            if highlight:
                names = ", ".join(CH_NAMES[i] for i in sorted(highlight) if i < len(CH_NAMES))
                lab = f"Électrodes clés{f' — {mode_label}' if mode_label else ''} : {names}"
                self.center(self.small, lab, ACCENT, int(h * 0.21))
                self.center(self.small, "(encadrées : contact à vérifier/mouiller en priorité)",
                            DIM, int(h * 0.245))
            if not rows:
                self.center(self.mid, "acquisition en cours...", DIM, int(h * 0.45))
            else:
                y = int(h * 0.34)
                for i, (name, s, verdict) in enumerate(rows):
                    col = GO if verdict == "ok" else WARN
                    if i in highlight:   # cadre bleu autour de la voie clé du mode
                        pg.draw.rect(self.win, ACCENT,
                                     (int(w * 0.18), y - 12, int(w * 0.52), int(h * 0.04)), 2)
                    bar = int(min(s / 40.0, 1.0) * w * 0.30)
                    pg.draw.rect(self.win, BAR_BG, (int(w * 0.38), y - 8, int(w * 0.30), 16))
                    pg.draw.rect(self.win, col, (int(w * 0.38), y - 8, bar, 16))
                    mark = "*" if i in highlight else " "
                    txt = f"{name:<4}{mark} σ={s:7.1f}  {verdict}"
                    surf = self.small.render(txt, True, col)   # couleur = verdict (ok/défaut)
                    self.win.blit(surf, (int(w * 0.20), y - 10))
                    y += int(h * 0.045)
                msg = ("signal plausible sur les 8 voies — touche pour continuer"
                       if ok else
                       "VOIES EN DÉFAUT : vérifie le câble, les électrodes et les mastoïdes")
                self.center(self.mid, msg, GO if ok else WARN, int(h * 0.80))
                self.center(self.small,
                            "touche = continuer   ·   ESC = retour au menu", DIM, int(h * 0.87))
            pg.display.flip()
            self.clock.tick(30)
            if not blocking:
                return ok

    def ring_spots(self, plan, dist_ratio=0.31, size_ratio=0.075):
        """Positions (x, y, rayon) des cibles c-VEP réparties sur un cercle, indexées par nom.

        Disques pleins plutôt que flèches : plus de surface rétinienne stimulée (donc une
        réponse plus forte), et surtout aucune limite à 4 directions — c'est ce qui permet
        au c-VEP de monter à 6 cibles là où le SSVEP plafonne.
        """
        w, h = self.size
        cx, cy, span = w / 2, h / 2, min(w, h)
        dist, r = span * dist_ratio, span * size_ratio
        return {c["name"]: (int(cx + math.sin(c["angle"]) * dist),
                            int(cy - math.cos(c["angle"]) * dist),  # y écran vers le bas
                            int(r)) for c in plan}

    def draw_ring(self, plan, spots, on_fn, frame, cue=None, labels=True):
        """Dessine les cibles c-VEP. `cue` = nom de la cible à fixer (consigne de calibration).

        ⚠️ Le cercle de consigne est tracé LARGEMENT à l'extérieur du disque (1.7×le rayon) :
        posé sur le disque, un contour lumineux statique écraserait la modulation de contraste
        du stimulus et dégraderait la réponse qu'on cherche justement à enregistrer.
        """
        pg = self.pygame
        for c in plan:
            x, y, r = spots[c["name"]]
            pg.draw.circle(self.win, OUTLINE, (x, y), r, 2)   # repère quand la cible est OFF
            if on_fn(c, frame):
                pg.draw.circle(self.win, ON_COLOR, (x, y), r)
            # Point de fixation : ancre le regard, ce qui stabilise la réponse. Taille FIXE en
            # pixels (et non proportionnelle au disque) : quelques pixels suffisent à ancrer le
            # regard, et l'emprise sur le stimulus devient ainsi négligeable (~0.1% de la surface)
            # quelle que soit la résolution. CHROMATIQUE à dessein : la réponse c-VEP est pilotée
            # par la LUMINANCE, donc un marqueur rouge n'ampute quasiment pas la modulation, tout
            # en restant visible sur le disque allumé (blanc) comme éteint (noir). Un point blanc,
            # lui, aurait réduit la profondeur de modulation en pleine fovée.
            pg.draw.circle(self.win, FIX_DOT, (x, y), FIX_DOT_R)
            if labels:
                lab = self.small.render(c["name"], True, DIM)
                self.win.blit(lab, lab.get_rect(center=(x, y + int(r * 1.9))))
        if cue is not None:
            x, y, r = spots[cue]
            pg.draw.circle(self.win, ACCENT, (x, y), int(r * 1.7), 4)

    def arrows(self, plan, dist_ratio=0.30, size_ratio=0.12):
        """Polygones des flèches, disposition commune SSVEP / c-VEP / MI."""
        w, h = self.size
        cx, cy, span = w / 2, h / 2, min(w, h)
        dist, asize = span * dist_ratio, span * size_ratio
        pos = {"up": (cx, cy - dist), "down": (cx, cy + dist),
               "left": (cx - dist, cy), "right": (cx + dist, cy)}
        return {c["dir"]: arrow_polygon(*pos[c["dir"]], asize, c["dir"]) for c in plan}, pos
