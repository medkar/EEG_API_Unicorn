"""Stimulus SSVEP — 4 flèches clignotantes (avant / arrière / gauche / droite).

Brique « affichage » de l'appli EEG. Aucune dépendance au casque : ce module ne fait
QUE présenter les stimuli visuels. Demain, le décodeur (BrainFlow + CCA) lira l'EEG
pendant que ces flèches clignotent, identifiera la fréquence fixée par le regard, et
produira {jx, jy} pour le robot.

Pourquoi « comptage de frames » et pas un timer ?
  Un stimulus SSVEP doit clignoter à une fréquence STABLE. Si on se base sur l'horloge,
  on rate/duplique des frames et la fréquence jitter -> le pic SSVEP s'étale et devient
  indétectable. On impose donc que chaque fréquence soit un DIVISEUR ENTIER du
  rafraîchissement écran : à 60 Hz, une flèche « ON k frames / OFF k frames » clignote
  exactement à 60/(2k) Hz. C'est à la fois « affichable » (pas de jitter) et
  « détectable » (dans la bande 8-15 Hz où le SSVEP occipital répond le mieux).

Mapping (utilisé plus tard par le décodeur, pas ici) :
    AVANT  -> jy > 0     ARRIERE -> jy < 0
    GAUCHE -> jx < 0     DROITE  -> jx > 0
    (aucune cible fixée -> aucune détection -> chien de garde de l'actionneur -> stop)

Lancer :
    python src/research/ssvep_stimulus.py                 # plein écran, ESC pour quitter
    python src/research/ssvep_stimulus.py --windowed      # fenêtre 1000x700 (dev)
    python src/research/ssvep_stimulus.py --refresh 60    # forcer le refresh (sinon auto-mesuré)
    python src/research/ssvep_stimulus.py --seconds 20    # auto-quit après 20 s
    python src/research/ssvep_stimulus.py --smoke         # test sans écran (CI), n'affiche rien
"""

import argparse
import math
import os
import sys
import time

# Permet `from config import ...` que le module soit lancé via `python src/research/ssvep_stimulus.py`
# ou importé comme `src.ssvep_stimulus`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import COMMANDS, COMMON_REFRESH, choose_frequencies, use_utf8_console  # noqa: E402

# --- Réglages d'affichage (les fréquences/commandes viennent de config.py) --

BG = (0, 0, 0)          # fond noir -> contraste ON/OFF maximal (meilleur SSVEP)
ON_COLOR = (255, 255, 255)
OUTLINE = (55, 55, 70)  # contour statique : garde le repère spatial quand la flèche est OFF
LABEL = (120, 120, 140)
HUD = (70, 90, 70)


# --- Clignotement (fonction pure, testable sans écran) --------------------

def is_on(frame, frames_per_cycle):
    """True pendant la moitié « ON » du cycle (duty ~50 %, exact si période paire)."""
    return (frame % frames_per_cycle) < (frames_per_cycle + 1) // 2


# --- Géométrie des flèches ------------------------------------------------

def _up_arrow_points(size):
    """Points d'une flèche pointant vers le haut, centrée sur (0,0), coords écran (y bas)."""
    h = size            # demi-hauteur totale
    head_h = size * 0.9  # hauteur de la pointe
    head_w = size * 0.75  # demi-largeur de la pointe
    shaft_w = size * 0.32  # demi-largeur de la tige
    top = -h
    return [
        (0.0, top),                 # pointe
        (head_w, top + head_h),     # base droite de la pointe
        (shaft_w, top + head_h),    # haut tige droite
        (shaft_w, h),               # bas tige droite
        (-shaft_w, h),              # bas tige gauche
        (-shaft_w, top + head_h),   # haut tige gauche
        (-head_w, top + head_h),    # base gauche de la pointe
    ]


_DIR_ANGLE = {"up": 0.0, "right": math.pi / 2, "down": math.pi, "left": -math.pi / 2}


def arrow_polygon(cx, cy, size, direction):
    """Points absolus (liste de (x,y)) d'une flèche orientée, centrée en (cx, cy)."""
    ang = _DIR_ANGLE[direction]
    c, s = math.cos(ang), math.sin(ang)
    pts = []
    for x, y in _up_arrow_points(size):
        rx = x * c - y * s
        ry = x * s + y * c
        pts.append((cx + rx, cy + ry))
    return pts


# --- Mesure du refresh écran ----------------------------------------------

def measure_refresh(pygame, surface, frames=90):
    """Estime le refresh en chronométrant des flips (vsync). Snappe sur une valeur usuelle."""
    surface.fill(BG)
    pygame.display.flip()
    pygame.event.pump()
    t0 = time.perf_counter()
    for _ in range(frames):
        surface.fill(BG)
        pygame.display.flip()
        pygame.event.pump()
    dt = time.perf_counter() - t0
    if dt <= 0:
        return 60.0
    fps = frames / dt
    return float(min(COMMON_REFRESH, key=lambda r: abs(r - fps)))


# --- Boucle principale ----------------------------------------------------

def run(windowed=False, refresh=None, seconds=None, smoke=False):
    if smoke:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

    import pygame  # import tardif : le module s'importe même sans pygame installé

    pygame.init()
    pygame.font.init()

    if windowed or smoke:
        size = (1000, 700)
        flags = pygame.SCALED
    else:
        info = pygame.display.Info()
        size = (info.current_w, info.current_h)
        flags = pygame.FULLSCREEN | pygame.SCALED

    # vsync=1 : le clignotement est cadencé par le balayage écran (indispensable au SSVEP)
    try:
        win = pygame.display.set_mode(size, flags, vsync=1)
    except (TypeError, pygame.error):
        win = pygame.display.set_mode(size, flags)
    pygame.display.set_caption("SSVEP stimulus — EEG_API_Unicorn")
    pygame.mouse.set_visible(False)

    if refresh is None:
        refresh = 60.0 if smoke else measure_refresh(pygame, win)
    plan = choose_frequencies(refresh)

    print(f"[ssvep] refresh ecran   : {refresh:.0f} Hz")
    print(f"[ssvep] taille fenetre  : {size[0]}x{size[1]}")
    for c in plan:
        print(f"[ssvep]   {c['name']:<8} {c['dir']:<5} desire={c['desired_hz']:>5.2f} Hz "
              f"-> {c['actual_hz']:>5.2f} Hz  ({c['frames_per_cycle']} frames/cycle)")

    w, h = size
    cx, cy = w / 2, h / 2
    span = min(w, h)
    dist = span * 0.30   # éloignement des flèches par rapport au centre
    asize = span * 0.13  # demi-taille d'une flèche
    pos = {
        "up":    (cx, cy - dist),
        "down":  (cx, cy + dist),
        "left":  (cx - dist, cy),
        "right": (cx + dist, cy),
    }
    polys = {c["dir"]: arrow_polygon(*pos[c["dir"]], asize, c["dir"]) for c in plan}

    font = pygame.font.SysFont("consolas", max(14, int(span * 0.022)))
    hud_font = pygame.font.SysFont("consolas", max(12, int(span * 0.016)))

    clock = pygame.time.Clock()
    frame = 0
    running = True
    t_start = time.perf_counter()
    fps_acc, fps_n, fps_show = 0.0, 0, refresh

    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False

        win.fill(BG)
        for c in plan:
            d = c["dir"]
            pygame.draw.polygon(win, OUTLINE, polys[d], 2)  # repère statique
            if is_on(frame, c["frames_per_cycle"]):
                pygame.draw.polygon(win, ON_COLOR, polys[d])  # phase ON
            # étiquette statique (n'interfère pas avec le clignotement)
            label = font.render(f"{c['name']}  {c['actual_hz']:.2f} Hz", True, LABEL)
            px, py = pos[d]
            win.blit(label, label.get_rect(center=(px, py + asize * 1.35)))

        hud = hud_font.render(
            f"{fps_show:.0f} fps  |  ESC = quitter", True, HUD)
        win.blit(hud, (12, 10))

        pygame.display.flip()
        dt = clock.tick(int(refresh) + 5) / 1000.0  # garde-fou si vsync absent
        if dt > 0:
            fps_acc += 1.0 / dt
            fps_n += 1
            if fps_n >= 30:
                fps_show, fps_acc, fps_n = fps_acc / fps_n, 0.0, 0

        frame += 1
        if smoke and frame >= 30:
            running = False
        if seconds is not None and (time.perf_counter() - t_start) >= seconds:
            running = False

    pygame.quit()
    if smoke:
        print("[ssvep] smoke OK : rendu de 30 frames sans erreur (aucun ecran requis).")


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Stimulus SSVEP 4 fleches (EEG_API_Unicorn).")
    p.add_argument("--windowed", action="store_true", help="fenetre au lieu du plein ecran")
    p.add_argument("--refresh", type=float, default=None, help="forcer le refresh (Hz)")
    p.add_argument("--seconds", type=float, default=None, help="auto-quit apres N secondes")
    p.add_argument("--smoke", action="store_true", help="test headless (SDL dummy), n'affiche rien")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    run(windowed=args.windowed, refresh=args.refresh, seconds=args.seconds, smoke=args.smoke)
