"""Calibration Motor Imagery : enregistre des essais étiquetés, entraîne CSP+LDA, sauvegarde.

Déroulé : un menu propose 4 durées de session. Puis, essai par essai (ordre aléatoire), une
consigne s'affiche — « SERRE la main GAUCHE / DROITE » ou « REPOS » — et l'EEG est enregistré
pendant l'imagerie. À la fin : entraînement du modèle + **ton accuracy en validation croisée**
(le moment de vérité : le MI marche-t-il pour toi ?), et sauvegarde de `data/mi_model.joblib`.

⚠️ EN DIRECT dans un terminal (il faut suivre les consignes). Casque bien porté, immobile.
Imagerie KINESTHÉSIQUE : *sentir* le serrement de la main, pas se le représenter visuellement.

    python src/mi_calibrate.py                 # menu de durée puis calibration
    python src/mi_calibrate.py --session 7min   # saute le menu
    python src/mi_calibrate.py --synthetic      # sans casque (board de test) — debug UI
    python src/mi_calibrate.py --smoke          # test headless (CI)
"""

import argparse
import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (FS_UNICORN, MI_KEY_CHANNELS, MI_MODEL_PATH,  # noqa: E402
                    MI_WINDOW_S, use_utf8_console)
from acquisition import UnicornAcquisition  # noqa: E402
from mi_decoder import MI_LABELS, MIModel  # noqa: E402

# Durées sélectionnables (essais PAR CLASSE). Le temps estimé est calculé plus bas.
PRESETS = {
    "court": {"key": "1", "tpc": 10, "label": "court  (< 5 min)"},
    "5min":  {"key": "2", "tpc": 14, "label": "~ 5 min"},
    "7min":  {"key": "3", "tpc": 18, "label": "~ 7 min"},
    "long":  {"key": "4", "tpc": 26, "label": "long  (> 7 min)"},
}
# CUE_S = mise en route NON enregistrée après le bip (le temps d'établir l'imagerie), puis on garde
# les IMAGERY_S suivantes. 2026-07-22 : CUE_S 2->3 s — l'utilisateur met « environ 2 s » à bien
# lancer le poing, 2 s ne laissait aucune marge (le début du signal enregistré attrapait la fin de
# la montée). IMAGERY_S gardé à 4 s : allonger l'enregistrement n'aiderait pas (le facteur limitant
# mesuré est la FATIGUE, pas la durée par essai — le 3-classes tombe de 57 % à 33 % en 2e moitié).
CUE_S, IMAGERY_S, REST_S = 3.0, 4.0, 1.5   # mise en route + enregistrement + repos entre essais
WARMUP_PER_CLASS = 2                        # essais d'échauffement NON enregistrés (le MI s'améliore
                                            # en cours de séance -> on garde que le post-échauffement)

BG = (10, 10, 16)
FG = (225, 225, 235)
DIM = (120, 120, 140)
GO = (80, 210, 120)
REST_COL = (230, 160, 70)

INSTR = {
    "GAUCHE": "Imagine : SERRE le POING GAUCHE",
    "DROITE": "Imagine : SERRE le POING DROIT",
    "REPOS":  "REPOS — détends-toi, ne rien imaginer",
}
REMINDER = "sens le serrement — NE BOUGE PAS"

BRIEF = [
    "Consignes Motor Imagery",
    "",
    "• Un BIP au DÉBUT donne le côté : oreille GAUCHE = poing gauche, DROITE = poing droit,",
    "  les DEUX oreilles (bip plus long) = repos. Imagine dès le bip et TIENS jusqu'au bip suivant.",
    "• La croix rappelle le côté en périphérie ; regard détendu, yeux flous mais alertes.",
    "• Imagine le serrement en le SENTANT (tension dans l'avant-bras), sans bouger la main.",
    "• Maintiens ou pompe le serrement toute la durée (pas un seul clic).",
    "• Astuce : serre vraiment 3-4 fois AVANT pour mémoriser la sensation, puis imagine-la.",
    "• Immobile, cligne le moins possible pendant l'imagerie.",
    "• REPOS = ne rien faire de spécial : relâche, respire NORMALEMENT, aucune imagerie de main.",
    "",
    "Appuie sur une touche pour commencer (ESC pour annuler).",
]


def _est_minutes(tpc):
    return len(MI_LABELS) * tpc * (CUE_S + IMAGERY_S + REST_S) / 60.0


def _blit_center(win, font, text, color, y):
    surf = font.render(text, True, color)
    win.blit(surf, surf.get_rect(center=(win.get_width() // 2, y)))


def _slice_windows(epoch, n, step):
    """Découpe une époque (n_samp x n_ch) en fenêtres glissantes (n_ch x n) pour l'entraînement."""
    return [epoch[i:i + n].T for i in range(0, len(epoch) - n + 1, step)]


def _flash(win, pygame, big, small, title, subtitle, seconds, clock):
    """Message centré pendant `seconds` (une touche passe, ESC annule)."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                raise KeyboardInterrupt
            if e.type == pygame.KEYDOWN:
                return
        win.fill(BG)
        _blit_center(win, big, title, FG, int(win.get_height() * 0.42))
        _blit_center(win, small, subtitle, DIM, int(win.get_height() * 0.54))
        pygame.display.flip()
        clock.tick(60)


def _rest(win, pygame, small, clock, big=None, mid=None, smoke=False):
    """Courte pause inter-essai (croix éteinte). ESPACE = PAUSE : sûr ICI car l'époque de l'essai
    précédent est déjà enregistrée (le MI épocher par essai) et aucun stimulus ne tourne."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < REST_S:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                raise KeyboardInterrupt
            if e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE and big is not None:
                _pause_mi(win, pygame, big, mid, clock, smoke)
        win.fill(BG)
        _blit_center(win, small, "...", DIM, win.get_height() // 2)
        if big is not None:
            _blit_center(win, small, "Espace = pause", DIM, int(win.get_height() * 0.62))
        pygame.display.flip()
        clock.tick(60)


def _pause_mi(win, pygame, big, mid, clock, smoke):
    """Écran de PAUSE pour la calibration MI (une touche reprend, Échap quitte). No-op en smoke."""
    if smoke:
        return
    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                raise KeyboardInterrupt
            if e.type == pygame.KEYDOWN:
                return
        win.fill(BG)
        _blit_center(win, big, "PAUSE", GO, int(win.get_height() * 0.42))
        _blit_center(win, mid, "une touche pour reprendre  ·  Échap pour quitter",
                     DIM, int(win.get_height() * 0.55))
        pygame.display.flip()
        clock.tick(30)


def _menu(win, pygame, big, mid, small, clock, smoke):
    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                return None
            if e.type == pygame.KEYDOWN:
                for name, p in PRESETS.items():
                    if e.unicode == p["key"]:
                        return name
        win.fill(BG)
        cx, h = win.get_width() // 2, win.get_height()
        _blit_center(win, big, "Calibration Motor Imagery", FG, int(h * 0.16))
        _blit_center(win, small, "Choisis une durée (touche 1-4) — ESC pour annuler", DIM, int(h * 0.26))
        y = int(h * 0.42)
        for name, p in PRESETS.items():
            txt = f"[{p['key']}]  {p['label']}   —   {p['tpc']}/classe  ≈ {_est_minutes(p['tpc']):.0f} min"
            _blit_center(win, mid, txt, FG, y)
            y += int(h * 0.10)
        pygame.display.flip()
        clock.tick(60)
        if smoke:
            return "court"


def _briefing(win, pygame, big, small, clock):
    """Écran de consignes avant la session. Retourne False si annulé (ESC)."""
    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                return False
            if e.type == pygame.KEYDOWN:
                return True
        win.fill(BG)
        y = int(win.get_height() * 0.14)
        for i, line in enumerate(BRIEF):
            f = big if i == 0 else small
            col = FG if i == 0 else (GO if line.startswith("Appuie") else FG)
            _blit_center(win, f, line, col, y)
            y += int(win.get_height() * 0.085) if i == 0 else int(win.get_height() * 0.058)
        pygame.display.flip()
        clock.tick(60)


# Position horizontale de la croix = la commande (pas de texte à lire, vision périphérique).
POS_X = {"GAUCHE": 0.25, "REPOS": 0.5, "DROITE": 0.75}


def _draw_cross(win, pygame, label, color, size):
    x, y = int(win.get_width() * POS_X[label]), win.get_height() // 2
    pygame.draw.line(win, color, (x - size, y), (x + size, y), 4)
    pygame.draw.line(win, color, (x, y - size), (x, y + size), 4)


def _make_beeps(pygame):
    """Bips stéréo : GAUCHE=oreille gauche, DROITE=oreille droite, REPOS=les deux + plus LONG.
    None si l'audio indispo. Le côté est porté par la spatialisation ; le centre par la durée."""
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2)
        import pygame.sndarray as sndarray
    except Exception:  # noqa: BLE001
        return None
    sr = pygame.mixer.get_init()[0]

    def snd(left, right, dur):
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        env = np.clip(np.minimum(t / 0.01, (dur - t) / 0.01), 0, 1)   # fondu (anti-clic)
        tone = (0.35 * np.sin(2 * np.pi * 880 * t) * env * 32767).astype(np.int16)
        st = np.zeros((len(tone), 2), dtype=np.int16)
        if left:
            st[:, 0] = tone
        if right:
            st[:, 1] = tone
        try:
            return sndarray.make_sound(np.ascontiguousarray(st))
        except Exception:  # noqa: BLE001
            return None

    return {"GAUCHE": snd(True, False, 0.18),
            "DROITE": snd(False, True, 0.18),
            "REPOS": snd(True, True, 0.40)}   # centre = les deux oreilles + plus long


def _run_trial(win, pygame, big, small, clock, acq, label, imagery_s, beeps=None):
    """Bip AU DÉBUT (côté = oreille G/D ; centre = les deux + plus long), puis imagerie continue.
    On laisse CUE_S de mise en route (non enregistrée, le temps de se concentrer) après le bip,
    puis on garde les dernières `imagery_s`. Croix à couleur constante = repère du côté."""
    cross = (175, 175, 195)
    if beeps and beeps.get(label) is not None:
        beeps[label].play()                          # BIP au départ = côté + top de mise en route
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < CUE_S + imagery_s:
        _drain(pygame)
        win.fill(BG)
        _draw_cross(win, pygame, label, cross, 20)
        pygame.display.flip()
        clock.tick(60)
    return acq.get_epoch(imagery_s)   # imagerie établie (le bip est déjà loin -> pas d'artefact)


def _drain(pygame):
    for e in pygame.event.get():
        if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
            raise KeyboardInterrupt


def calibrate(session=None, synthetic=False, smoke=False, imagery_s=IMAGERY_S, app=None):
    """`app` (ui.App) : réutilise la fenêtre et la session casque de l'appli unifiée au lieu
    d'en ouvrir de nouvelles (l'appairage Bluetooth coûte plusieurs secondes)."""
    owns = app is None
    if owns:
        if smoke:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
            synthetic = True

        import pygame
        pygame.init()
        pygame.font.init()
        size = (1100, 760)
        flags = pygame.SCALED | (0 if (synthetic or smoke) else pygame.FULLSCREEN)
        win = pygame.display.set_mode(size, flags)
        pygame.display.set_caption("MI calibration — EEG Waffle")
        pygame.mouse.set_visible(False)
        span = min(size)
        big = pygame.font.SysFont("consolas", max(24, int(span * 0.045)), bold=True)
        mid = pygame.font.SysFont("consolas", max(18, int(span * 0.028)))
        small = pygame.font.SysFont("consolas", max(14, int(span * 0.020)))
        clock = pygame.time.Clock()
    else:
        pygame, win, clock = app.pygame, app.win, app.clock
        big, mid, small = app.big, app.mid, app.small
        synthetic, smoke = app.synthetic, app.smoke
    beeps = _make_beeps(pygame)   # cues sonores spatialisés (None si audio indispo)

    if session is None:
        session = _menu(win, pygame, big, mid, small, clock, smoke)
        if session is None:
            if owns:
                pygame.quit()
            print("[mi-cal] annulé.")
            return False
    tpc = PRESETS[session]["tpc"] if not smoke else 2
    imagery_s = 2.5 if smoke else imagery_s

    if not smoke and not _briefing(win, pygame, big, small, clock):
        if owns:
            pygame.quit()
        print("[mi-cal] annulé.")
        return False

    acq = UnicornAcquisition(synthetic=synthetic).start() if owns else app.acq
    if not owns and not smoke and not app.signal_check(highlight=MI_KEY_CHANNELS,
                                                       mode_label="Motor Imagery"):
        print("[mi-cal] annulé (liaison casque).")
        return False
    print(f"[mi-cal] session={session}  {tpc}/classe  ≈ {_est_minutes(tpc):.0f} min  "
          f"(imagerie {imagery_s:.1f}s, fenêtre {MI_WINDOW_S:.1f}s)")

    recorded = []
    try:
        # Échauffement NON enregistré (le MI s'améliore en cours de séance)
        if not smoke and WARMUP_PER_CLASS > 0:
            _flash(win, pygame, big, small, "Échauffement",
                   f"{WARMUP_PER_CLASS*len(MI_LABELS)} essais pour te caler — NON enregistrés", 3.0, clock)
            warm = [lab for lab in MI_LABELS for _ in range(WARMUP_PER_CLASS)]
            random.shuffle(warm)
            for label in warm:
                _run_trial(win, pygame, big, small, clock, acq, label, imagery_s, beeps)
                _rest(win, pygame, small, clock, big, mid, smoke)
            _flash(win, pygame, big, small, "C'est parti !",
                   "Les essais suivants SONT enregistrés", 3.0, clock)

        # Essais enregistrés
        trials = [lab for lab in MI_LABELS for _ in range(tpc)]
        random.shuffle(trials)
        for i, label in enumerate(trials):
            print(f"[mi-cal] essai {i+1}/{len(trials)} : {label}", flush=True)
            epoch = _run_trial(win, pygame, big, small, clock, acq, label, imagery_s, beeps)
            if epoch is not None:
                recorded.append((epoch, label))
            _rest(win, pygame, small, clock, big, mid, smoke)
            if smoke and i >= 1:
                break
    except KeyboardInterrupt:
        print("[mi-cal] interrompu — entraînement sur ce qui est déjà enregistré.")
    finally:
        if owns:
            acq.stop()

    ok = _train_and_save(recorded, acq.fs, win, pygame, big, mid, smoke)
    if owns:
        pygame.quit()
    return ok


def _train_and_save(recorded, fs, win, pygame, big, mid, smoke):
    n = int(round(MI_WINDOW_S * fs))
    step = int(round(1.0 * fs))
    X, y = [], []
    for epoch, label in recorded:
        for w in _slice_windows(epoch, n, step):
            X.append(w)
            y.append(label)
    counts = {lab: y.count(lab) for lab in MI_LABELS}
    print(f"[mi-cal] {len(recorded)} essais -> {len(X)} fenêtres d'entraînement {counts}")
    if smoke:
        print("[mi-cal] smoke OK : UI + enregistrement + découpage câblés (pas d'entraînement).")
        return True
    if min(counts.values()) < 5:
        print("[mi-cal] pas assez de données pour entraîner (min 5 fenêtres/classe).")
        return False

    model = MIModel(fs=fs).fit(np.asarray(X), np.asarray(y))
    os.makedirs(os.path.dirname(MI_MODEL_PATH), exist_ok=True)
    model.save(MI_MODEL_PATH)
    raw_path = os.path.join(os.path.dirname(MI_MODEL_PATH), "mi_calib_last.npz")
    np.savez(raw_path, epochs=np.asarray([e for e, _ in recorded]),
             labels=np.asarray([l for _, l in recorded]), fs=fs, window_s=MI_WINDOW_S)

    cv = model.cv_ * 100
    verdict = ("EXCELLENT" if cv >= 75 else "UTILISABLE" if cv >= 60 else
               "FAIBLE (ré-essaie : contact, immobilité, imagerie kinesthésique)")
    print(f"[mi-cal] accuracy validation croisée : {cv:.1f}%  (hasard 3 classes = 33%) -> {verdict}")
    print(f"[mi-cal] modèle sauvegardé : {MI_MODEL_PATH}")

    # écran de résultat
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 6.0:
        for e in pygame.event.get():
            if e.type in (pygame.QUIT, pygame.KEYDOWN):
                t0 -= 10
        win.fill(BG)
        _blit_center(win, big, f"Accuracy : {cv:.0f}%", FG, int(win.get_height() * 0.42))
        _blit_center(win, mid, verdict, GO if cv >= 60 else REST_COL, int(win.get_height() * 0.56))
        _blit_center(win, mid, "modèle sauvegardé — touche pour quitter", DIM, int(win.get_height() * 0.68))
        pygame.display.flip()
        pygame.time.Clock().tick(60)
    return cv >= 60


def _parse(argv):
    p = argparse.ArgumentParser(description="Calibration Motor Imagery (EEG Waffle).")
    p.add_argument("--session", choices=list(PRESETS), default=None, help="durée (saute le menu)")
    p.add_argument("--synthetic", action="store_true", help="board de test (sans casque)")
    p.add_argument("--smoke", action="store_true", help="test headless (CI)")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    a = _parse(sys.argv[1:])
    calibrate(session=a.session, synthetic=a.synthetic, smoke=a.smoke)
