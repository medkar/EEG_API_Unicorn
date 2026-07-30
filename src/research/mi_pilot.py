"""Pilotage du robot par Motor Imagery + feedback en direct (= entraînement neurofeedback).

Charge le modèle MI entraîné (calibration), lit l'EEG en continu, décode GAUCHE/DROITE/REPOS,
lisse par vote, et envoie {jx,jy} en UDP à l'actionneur. En 2 classes, ça pilote les ROTATIONS :
  GAUCHE -> tourne à gauche · DROITE -> tourne à droite · REPOS/incertain -> stop.
L'écran montre la commande décodée + les probabilités (utile pour progresser : tu vois l'effet).

    python src/research/mi_pilot.py                    # feedback seul (pas d'envoi robot) — pour s'entraîner
    python src/research/mi_pilot.py --send             # + pilote le robot (roues en l'air d'abord !)
    python src/research/mi_pilot.py --calibrate --send  # calibration PUIS pilotage, d'un coup
    python src/research/mi_pilot.py --calibrate --session 5min
    python src/research/mi_pilot.py --smoke            # test headless (CI)
"""

import argparse
import os
import sys
import threading
import time
from collections import Counter, deque

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))      # -> src/
from core.config import (COMMANDS, EXAMPLES_DIR, MI_MIN_VOTES, MI_MODEL_PATH,  # noqa: E402
                    MI_PROB_MIN, MI_VOTE_LEN, MI_WINDOW_S, UDP_HOST, UDP_PORT,
                    apply_invert, use_utf8_console)
from core.acquisition import UnicornAcquisition  # noqa: E402
from core.mi_decoder import MI_LABELS, MIDecoder, MIModel  # noqa: E402
from research.ssvep_stimulus import arrow_polygon  # noqa: E402

sys.path.insert(0, EXAMPLES_DIR)  # l'actionneur d'exemple vit dans examples/, hors du paquet
from actuator_udp import ActuatorSender  # noqa: E402

BG = (12, 12, 18)
FG = (225, 225, 235)
DIM = (110, 110, 130)
GO = (80, 210, 120)
BAR_BG = (40, 40, 52)
WARN = (230, 160, 70)
COLROW = {"GAUCHE": (90, 170, 240), "DROITE": (240, 140, 90), "REPOS": (150, 150, 160)}


class MIController:
    """Vote glissant sur les labels MI + mapping label -> commande {jx,jy}."""

    def __init__(self, decoder, label_to_cmd, vote_len=MI_VOTE_LEN, min_votes=MI_MIN_VOTES):
        self.decoder = decoder
        self.label_to_cmd = label_to_cmd
        self.buffer = deque(maxlen=vote_len)
        self.min_votes = min_votes

    def step(self, window):
        """Retourne (commande|None, scores). Un seul predict par fenêtre."""
        label, scores = self.decoder.classify(window)
        self.buffer.append(label)
        winner, count = Counter(self.buffer).most_common(1)[0]
        cmd = self.label_to_cmd[winner] if (winner is not None and count >= self.min_votes) else None
        return cmd, scores


def _dummy_model():
    rng = np.random.default_rng(0)
    ep, y = [], []
    for lab in MI_LABELS:
        for _ in range(8):
            ep.append(rng.normal(0, 1, (8, 500)))
            y.append(lab)
    return MIModel(fs=250).fit(np.asarray(ep), np.asarray(y))


def pilot(calibrate_first=False, session=None, synthetic=False, send=False,
          windowed=True, smoke=False, host=UDP_HOST):
    if smoke:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        synthetic = True

    if calibrate_first and not smoke:
        import research.mi_calibrate as mi_calibrate
        mi_calibrate.calibrate(session=session, synthetic=synthetic)

    # Modèle + source de fenêtres
    acq = None
    if smoke:
        model = _dummy_model()
        rng = np.random.default_rng(0)
        provider = lambda: rng.normal(0, 1, (int(MI_WINDOW_S * 250), 8))  # noqa: E731
    else:
        if not os.path.exists(MI_MODEL_PATH):
            print(f"[mi-pilot] pas de modèle ({MI_MODEL_PATH}). Lance d'abord une calibration "
                  "(mi_calibrate.py) ou ajoute --calibrate.")
            return False
        model = MIModel.load(MI_MODEL_PATH)
        acq = UnicornAcquisition(synthetic=synthetic).start()
        provider = lambda: acq.get_epoch(MI_WINDOW_S)  # noqa: E731

    decoder = MIDecoder(model, prob_min=MI_PROB_MIN)
    label_to_cmd = {c["name"]: c for c in COMMANDS if c["name"] in decoder.labels}
    ctrl = MIController(decoder, label_to_cmd)
    sender = ActuatorSender(host, UDP_PORT) if (send and not smoke) else None
    print(f"[mi-pilot] classes={model.labels} méthode={model.method} "
          f"fenêtre={MI_WINDOW_S}s vote={ctrl.min_votes}/{ctrl.buffer.maxlen} "
          f"UDP={'ON -> ' + host if sender else 'off (feedback seul)'}")

    state = {"name": "STOP", "jx": 0.0, "jy": 0.0, "scores": {}, "sigma": 0.0, "ready": False}
    lock, stop = threading.Lock(), threading.Event()

    def decode_loop():
        dt = 1.0 / 2.5   # ~2.5 décisions/s (fenêtre glissante de 2 s)
        while not stop.is_set():
            w = provider()
            if w is not None:
                cmd, scores = ctrl.step(w)
                with lock:
                    state["scores"] = scores
                    state["sigma"] = float(np.asarray(w).std(axis=0).mean())
                    state["ready"] = True
                    state.update({"name": cmd["name"], "jx": cmd["jx"], "jy": cmd["jy"]}
                                 if cmd else {"name": "STOP", "jx": 0.0, "jy": 0.0})
            time.sleep(dt)

    def send_loop():
        dt = 1.0 / 15.0
        while not stop.is_set():
            if sender is not None:
                with lock:
                    jx, jy = state["jx"], state["jy"]
                sender.send(*apply_invert(jx, jy))
            time.sleep(dt)

    threading.Thread(target=decode_loop, daemon=True).start()
    threading.Thread(target=send_loop, daemon=True).start()
    _render_loop(state, lock, stop, decoder, sender is not None, windowed or smoke, smoke)

    stop.set()
    time.sleep(0.2)
    if acq is not None:
        acq.stop()
    if sender is not None:
        sender.stop()
        sender.close()
    if smoke:
        print("[mi-pilot] smoke OK : décodage + feedback + envoi câblés (headless).")
    return True


def _render_loop(state, lock, stop, decoder, sending, windowed, smoke):
    import pygame
    pygame.init()
    pygame.font.init()
    size = (1000, 700)
    flags = pygame.SCALED if windowed else (pygame.FULLSCREEN | pygame.SCALED)
    win = pygame.display.set_mode(size, flags)
    pygame.display.set_caption("Motor Imagery — pilotage robot")
    w, h = size
    cx, cy, span = w // 2, int(h * 0.42), min(w, h)
    dist, asize = span * 0.28, span * 0.11
    poly = {"left": arrow_polygon(cx - dist, cy, asize, "left"),
            "right": arrow_polygon(cx + dist, cy, asize, "right")}
    big = pygame.font.SysFont("consolas", max(26, int(span * 0.055)), bold=True)
    small = pygame.font.SysFont("consolas", max(14, int(span * 0.022)))
    clock = pygame.time.Clock()
    frame = 0
    running = True
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_q)):
                running = False
        with lock:
            name, scores, sigma, ready = state["name"], dict(state["scores"]), state["sigma"], state["ready"]

        win.fill(BG)
        for d, lab in (("left", "GAUCHE"), ("right", "DROITE")):
            active = (name == lab)
            pygame.draw.polygon(win, GO if active else DIM, poly[d], 0 if active else 3)
        if name == "STOP":
            pygame.draw.circle(win, WARN, (cx, cy), int(asize * 0.35), 4)

        head = "acquisition..." if not ready else ("→ " + name if name != "STOP" else "STOP")
        s = big.render(head, True, GO if name not in ("STOP", "acquisition...") else DIM)
        win.blit(s, s.get_rect(center=(cx, int(h * 0.80))))

        # barres de probabilité (neurofeedback)
        y0, bw = int(h * 0.88), int(w * 0.5)
        for i, lab in enumerate(["GAUCHE", "DROITE", "REPOS"]):
            p = scores.get(lab, 0.0)
            ry = y0 + i * 22
            pygame.draw.rect(win, BAR_BG, (int(w * 0.28), ry, bw, 14))
            pygame.draw.rect(win, COLROW[lab], (int(w * 0.28), ry, int(bw * p), 14))
            win.blit(small.render(f"{lab:<7} {p:.2f}", True, FG), (int(w * 0.28) + bw + 12, ry - 2))
        win.blit(small.render(f"σ≈{sigma:.0f}   seuil={decoder.prob_min:.2f}   "
                              f"{'UDP:ON' if sending else 'UDP:off'}   ESC=quitter", True, DIM),
                 (12, 10))

        pygame.display.flip()
        clock.tick(60)
        frame += 1
        if smoke and frame >= 40:
            running = False
    pygame.quit()


def _parse(argv):
    p = argparse.ArgumentParser(description="Pilotage par Motor Imagery (EEG_API_Unicorn).")
    p.add_argument("--calibrate", action="store_true", help="calibration AVANT le pilotage")
    p.add_argument("--session", default=None, help="durée de calibration (court/5min/7min/long)")
    p.add_argument("--send", action="store_true", help="envoyer {jx,jy} au robot (roues en l'air !)")
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--synthetic", action="store_true", help="board de test (sans casque)")
    p.add_argument("--smoke", action="store_true", help="test headless (CI)")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    a = _parse(sys.argv[1:])
    pilot(calibrate_first=a.calibrate, session=a.session, synthetic=a.synthetic,
          send=a.send, windowed=not a.fullscreen, smoke=a.smoke)
