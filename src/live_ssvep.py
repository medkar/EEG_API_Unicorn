"""Diagnostic SSVEP en direct : flèches clignotantes + ρ (CCA) temps réel par cible.

Assemble tout : stimulus (ssvep_stimulus) + acquisition (BrainFlow) + décodage (CCA) +
lissage (SSVEPController), et AFFICHE par-dessus les flèches, en temps réel :
  - la corrélation ρ de chaque cible (barres),
  - la cible gagnante et si elle passe le seuil rho_min,
  - la décision lissée (ce qui serait envoyé au robot),
  - le σ du signal (contrôle du contact électrodes).

Sert à : vérifier que fixer une flèche fait bien monter SON ρ, mesurer les faux positifs
alpha quand on ne fixe rien, et CALIBRER rho_min — avant de brancher le robot.

    python src/live_ssvep.py                 # plein écran, casque réel, ESC pour quitter
    python src/live_ssvep.py --windowed      # fenêtre (voir la console à côté)
    python src/live_ssvep.py --send          # + envoi UDP à l'actionneur (config.UDP_HOST)
    python src/live_ssvep.py --synthetic     # sans casque (board de test) — pour déboguer l'UI
    python src/live_ssvep.py --smoke         # test headless (CI), n'affiche rien
"""

import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (CH_NAMES, UDP_HOST, UDP_PORT, WINDOW_S, apply_invert,  # noqa: E402
                    choose_frequencies, use_utf8_console)
from cca_decoder import CCADecoder  # noqa: E402
from controller import SSVEPController  # noqa: E402
from acquisition import UnicornAcquisition  # noqa: E402
from ssvep_stimulus import arrow_polygon, is_on, measure_refresh  # noqa: E402

BG = (0, 0, 0)
ON_COLOR = (255, 255, 255)
OUTLINE = (55, 55, 70)
LABEL = (150, 150, 170)
BAR_BG = (40, 40, 52)
BAR_LOW = (90, 100, 120)
BAR_WIN = (80, 210, 120)
TEXT = (210, 210, 225)
WARN = (230, 160, 70)


class _Shared:
    """État partagé entre le thread de décodage et la boucle de rendu."""
    def __init__(self):
        self.lock = threading.Lock()
        self.scores = {}
        self.decision = None   # dict commande lissée, ou None
        self.best = (None, 0.0)
        self.sigma = 0.0
        self.ready = False


def _decode_thread(acq, decoder, ctrl, shared, stop, sender, plan, hz=5.0, log=True):
    dt = 1.0 / hz
    every = max(1, int(hz // 2))  # log throttlé à ~2 Hz
    i = 0
    while not stop.is_set():
        w = acq.get_window()
        if w is not None:
            scores = decoder.scores(w)
            cmd = ctrl.decide(w)
            best_f = max(scores, key=scores.get)
            sd = float(w.std(axis=0).mean())
            with shared.lock:
                shared.scores = scores
                shared.decision = cmd
                shared.best = (best_f, scores[best_f])
                shared.sigma = sd
                shared.ready = True
            if sender is not None:
                jx, jy = (cmd["jx"], cmd["jy"]) if cmd else (0.0, 0.0)
                sender.send(*apply_invert(jx, jy))  # correction de sens (config)
            if log and i % every == 0:
                rhos = "  ".join(f"{c['name'][:3]}({c['actual_hz']:.1f})={scores[c['actual_hz']]:.2f}"
                                 for c in plan)
                dec = cmd["name"] if cmd else "-"
                print(f"ρ {rhos}  | best={best_f:.1f}Hz  décision={dec:<8} σ={sd:.0f}", flush=True)
            i += 1
        time.sleep(dt)


def run(windowed=False, send=False, synthetic=False, smoke=False):
    if smoke:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        synthetic = True

    import pygame
    pygame.init()
    pygame.font.init()

    if windowed or smoke:
        size, flags = (1100, 780), pygame.SCALED
    else:
        info = pygame.display.Info()
        size, flags = (info.current_w, info.current_h), pygame.FULLSCREEN | pygame.SCALED
    try:
        win = pygame.display.set_mode(size, flags, vsync=1)
    except (TypeError, pygame.error):
        win = pygame.display.set_mode(size, flags)
    pygame.display.set_caption("SSVEP live — EEG_API_Unicorn")
    pygame.mouse.set_visible(False)

    refresh = 60.0 if smoke else measure_refresh(pygame, win)
    plan = choose_frequencies(refresh)
    freqs = [c["actual_hz"] for c in plan]
    decoder = CCADecoder(freqs)
    ctrl = SSVEPController(plan)

    # Géométrie des flèches (même disposition que le stimulus).
    w, h = size
    cx, cy, span = w / 2, h / 2, min(w, h)
    dist, asize = span * 0.30, span * 0.12
    pos = {"up": (cx, cy - dist), "down": (cx, cy + dist),
           "left": (cx - dist, cy), "right": (cx + dist, cy)}
    polys = {c["dir"]: arrow_polygon(*pos[c["dir"]], asize, c["dir"]) for c in plan}
    fps_by_dir = {c["dir"]: c["frames_per_cycle"] for c in plan}

    big = pygame.font.SysFont("consolas", max(20, int(span * 0.030)), bold=True)
    small = pygame.font.SysFont("consolas", max(13, int(span * 0.018)))

    acq = UnicornAcquisition(synthetic=synthetic).start()
    sender = None
    if send:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples"))
        from actuator_udp import ActuatorSender
        sender = ActuatorSender(UDP_HOST, UDP_PORT)

    shared = _Shared()
    stop = threading.Event()
    dt_thread = threading.Thread(target=_decode_thread,
                                 args=(acq, decoder, ctrl, shared, stop, sender, plan),
                                 kwargs={"log": not smoke}, daemon=True)
    dt_thread.start()

    clock = pygame.time.Clock()
    frame = 0
    running = True
    try:
        while running:
            for e in pygame.event.get():
                if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_q)):
                    running = False

            win.fill(BG)
            for c in plan:
                d = c["dir"]
                pygame.draw.polygon(win, OUTLINE, polys[d], 2)
                if is_on(frame, fps_by_dir[d]):
                    pygame.draw.polygon(win, ON_COLOR, polys[d])

            with shared.lock:
                scores, decision = dict(shared.scores), shared.decision
                best_f, best_r = shared.best
                sigma, ready = shared.sigma, shared.ready
            _draw_panel(win, small, big, plan, scores, decision, best_f, best_r, sigma, ready,
                        decoder.rho_min, send)

            pygame.display.flip()
            clock.tick(int(refresh) + 5)
            frame += 1
            if smoke and frame >= 40:
                running = False
    finally:
        stop.set()
        dt_thread.join(timeout=1.0)
        acq.stop()
        if sender is not None:
            sender.stop()
            sender.close()
        pygame.quit()
    if smoke:
        print("[live] smoke OK : acquisition+décodage+rendu câblés (board synthétique, headless).")


def _draw_panel(win, small, big, plan, scores, decision, best_f, best_r, sigma, ready,
                rho_min, send):
    import pygame
    x, y, barw = 24, int(win.get_height() * 0.60), int(win.get_width() * 0.24)
    if not ready:
        win.blit(big.render("acquisition... (remplissage 2 s)", True, LABEL), (x, y))
        return

    title = decision["name"] if decision else "—  (rien / sous le seuil)"
    col = BAR_WIN if decision else LABEL
    win.blit(big.render(f"décision : {title}", True, col), (x, y - 46))

    for i, c in enumerate(plan):
        f = c["actual_hz"]
        rho = scores.get(f, 0.0)
        row_y = y + i * 30
        is_best = (f == best_f)
        bar_col = BAR_WIN if (is_best and rho >= rho_min) else BAR_LOW
        pygame.draw.rect(win, BAR_BG, (x + 190, row_y + 4, barw, 16))
        pygame.draw.rect(win, bar_col, (x + 190, row_y + 4, int(barw * min(rho, 1.0)), 16))
        # marque du seuil rho_min
        tx = x + 190 + int(barw * rho_min)
        pygame.draw.line(win, WARN, (tx, row_y + 1), (tx, row_y + 22), 2)
        label = f"{c['name']:<8} {f:5.2f}Hz  ρ={rho:.2f}"
        win.blit(small.render(label, True, TEXT if is_best else LABEL), (x, row_y))

    sig_col = TEXT if sigma < 800 else WARN  # σ énorme => contact douteux (cf. alpha_check)
    hud = f"σ≈{sigma:.0f}   seuil ρ_min={rho_min:.2f}   {'UDP:ON' if send else 'UDP:off'}   ESC=quitter"
    win.blit(small.render(hud, True, sig_col), (x, y + len(plan) * 30 + 12))


# --- Mode GUIDÉ : le test dicte les consignes, enregistre les ρ par étape ----

def _guided_phases(plan, scale=1.0):
    """Séquence d'étapes, générée depuis `plan` (s'adapte au nombre de cibles).
    `dir`=flèche à surligner (None=repos), `expected`=cible attendue."""
    instr = {"up": "FIXE la flèche AVANT (haut)", "left": "FIXE la flèche GAUCHE",
             "right": "FIXE la flèche DROITE", "down": "FIXE la flèche ARRIERE (bas)"}
    phases = [{"key": "REPOS-1", "instr": "REPOS — ne fixe AUCUNE flèche, détends-toi",
               "dir": None, "expected": None, "dur": 8 * scale}]
    for c in plan:
        phases.append({"key": c["name"], "instr": instr[c["dir"]], "dir": c["dir"],
                       "expected": c["name"], "dur": 7 * scale})
    phases.append({"key": "REPOS-2", "instr": "REPOS — ne fixe rien, détends-toi",
                   "dir": None, "expected": None, "dur": 6 * scale})
    return phases


def _phase_summary(phase, samples, f2name, rho_min):
    """Imprime moyenne ρ par cible + verdict pour une étape. Retourne le dict moyen."""
    if not samples:
        print(f">> {phase['key']} : pas de données (fenêtre pas prête).", flush=True)
        return None
    freqs = list(samples[0].keys())
    mean = {f: sum(s[f] for s in samples) / len(samples) for f in freqs}
    line = "  ".join(f"{f2name[f]}({f:.1f})={mean[f]:.2f}" for f in freqs)
    dom = max(mean, key=mean.get)
    print(f">> MOYENNE {phase['key']} ({len(samples)} pts) : {line}", flush=True)
    exp = phase["expected"]
    if exp is None:
        over = [f2name[f] for f in freqs if mean[f] >= rho_min]
        verdict = (f"repos: dominant={f2name[dom]}({dom:.1f}Hz) ρ={mean[dom]:.2f} ; "
                   + ("aucune cible au-dessus du seuil = BON"
                      if not over else f"AU-DESSUS DU SEUIL {rho_min}: {over} = faux positif (alpha ?)"))
    else:
        ok = (f2name[dom] == exp and mean[dom] >= rho_min)
        verdict = (f"attendu={exp} ; dominant={f2name[dom]}({dom:.1f}Hz) ρ={mean[dom]:.2f} "
                   f"-> {'OK' if ok else 'FAIBLE/ECHEC'}")
    print(f">> VERDICT {phase['key']} : {verdict}", flush=True)
    return mean


def _decision_verdict(phase, decisions):
    """Juge la décision LISSÉE émise pendant une étape (le vrai signal envoyé au robot)."""
    from collections import Counter
    n = len(decisions)
    emitted = [d for d in decisions if d]
    if n == 0:
        print(f">> DÉCISION {phase['key']} : pas de données.", flush=True)
        return
    if phase["expected"] is None:  # repos : on veut le SILENCE
        dom = Counter(emitted).most_common(1)[0][0] if emitted else "-"
        verdict = "SILENCE = BON" if not emitted else f"{len(emitted)} parasites (surtout {dom}) = à surveiller"
        print(f">> DÉCISION {phase['key']} : {len(emitted)}/{n} fenêtres émettent -> {verdict}", flush=True)
    else:  # fixation : on veut la bonne commande, sans autre
        good = sum(1 for d in emitted if d == phase["expected"])
        wrong = len(emitted) - good
        ok = good > 0 and wrong == 0
        print(f">> DÉCISION {phase['key']} : {phase['expected']} sur {good}/{n} fenêtres, {wrong} autres "
              f"-> {'OK' if ok else ('OK-ish' if good > wrong else 'PROBLEME')}", flush=True)


def guided(windowed=False, synthetic=False, smoke=False):
    if smoke:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        synthetic = True

    import pygame
    pygame.init()
    pygame.font.init()
    if windowed or smoke:
        size, flags = (1100, 780), pygame.SCALED
    else:
        info = pygame.display.Info()
        size, flags = (info.current_w, info.current_h), pygame.FULLSCREEN | pygame.SCALED
    try:
        win = pygame.display.set_mode(size, flags, vsync=1)
    except (TypeError, pygame.error):
        win = pygame.display.set_mode(size, flags)
    pygame.display.set_caption("SSVEP guidé — EEG_API_Unicorn")
    pygame.mouse.set_visible(False)

    refresh = 60.0 if smoke else measure_refresh(pygame, win)
    plan = choose_frequencies(refresh)
    decoder = CCADecoder([c["actual_hz"] for c in plan])
    ctrl = SSVEPController(plan)  # décision lissée (mêmes paramètres calibrés que le robot)
    f2name = {c["actual_hz"]: c["name"] for c in plan}

    w, h = size
    cx, cy, span = w / 2, h / 2, min(w, h)
    dist, asize = span * 0.30, span * 0.12
    pos = {"up": (cx, cy - dist), "down": (cx, cy + dist),
           "left": (cx - dist, cy), "right": (cx + dist, cy)}
    polys = {c["dir"]: arrow_polygon(*pos[c["dir"]], asize, c["dir"]) for c in plan}
    fpc = {c["dir"]: c["frames_per_cycle"] for c in plan}

    big = pygame.font.SysFont("consolas", max(22, int(span * 0.040)), bold=True)
    mid = pygame.font.SysFont("consolas", max(16, int(span * 0.024)))
    count_font = pygame.font.SysFont("consolas", max(40, int(span * 0.10)), bold=True)

    acq = UnicornAcquisition(synthetic=synthetic).start()

    phases = _guided_phases(plan, scale=0.2 if smoke else 1.0)
    prep = 1.0 if smoke else 3.0
    print("\n############ TEST SSVEP GUIDÉ — suis les consignes à l'écran ############")
    print(f"# refresh={refresh:.0f}Hz  seuil rho_min={decoder.rho_min}  "
          + " ".join(f"{c['name']}={c['actual_hz']:.2f}Hz" for c in plan))
    print("# Chaque étape : décompte, puis ENREGISTREMENT. Colle toute la console à la fin.\n")

    clock = pygame.time.Clock()
    frame, idx, state = 0, 0, "prep"
    t_phase = time.perf_counter()
    t_rec = t_phase
    samples, decisions, recap, last_decode = [], [], [], 0.0
    raw_epochs, raw_labels = [], []
    running = True
    try:
        while running and idx < len(phases):
            for e in pygame.event.get():
                if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_q)):
                    running = False
            now = time.perf_counter()
            phase = phases[idx]

            if state == "prep" and (now - t_phase) >= prep:
                state, t_rec, samples, decisions = "record", now, [], []
                ctrl.buffer.clear()  # vote propre à chaque étape (mesure sans traîne)
                print(f"\n=== ENREGISTREMENT {phase['key']} ({phase['dur']:.0f}s) : {phase['instr']} ===", flush=True)
            elif state == "record" and (now - t_rec) >= phase["dur"]:
                recap.append((phase["key"], _phase_summary(phase, samples, f2name, decoder.rho_min)))
                _decision_verdict(phase, decisions)
                idx, state, t_phase = idx + 1, "prep", now
                if idx < len(phases):
                    print(f"\n--- Prépare-toi : {phases[idx]['instr']} ---", flush=True)
                continue

            if now - last_decode >= 0.25:
                last_decode = now
                wnd = acq.get_window()
                if wnd is not None and state == "record":
                    sc = decoder.scores(wnd)
                    cmd = ctrl.decide(wnd)
                    samples.append(sc)
                    decisions.append(cmd["name"] if cmd else None)
                    # Archive du signal BRUT 8 voies, étiqueté par phase. Sans ça, le SSVEP est
                    # le seul mode dont on ne conserve que la SORTIE du décodeur (les ρ) : toute
                    # amélioration d'algorithme exigeait alors une nouvelle séance casque.
                    raw = acq.get_epoch(WINDOW_S)
                    if raw is not None:
                        raw_epochs.append(raw)
                        raw_labels.append(phase["expected"] or "REPOS")
                    best = max(sc, key=sc.get)
                    print(f"  [{phase['key']}] " + "  ".join(f"{f2name[f][:3]}={sc[f]:.2f}" for f in sc)
                          + f"  best={f2name[best]}({best:.1f})  déc={cmd['name'] if cmd else '-':<8} "
                          f"σ={wnd.std(axis=0).mean():.0f}", flush=True)

            # --- rendu : flèches + surlignage + consigne + décompte ---
            win.fill(BG)
            for c in plan:
                d = c["dir"]
                pygame.draw.polygon(win, OUTLINE, polys[d], 2)
                if is_on(frame, fpc[d]):
                    pygame.draw.polygon(win, ON_COLOR, polys[d])
            if phase["dir"] is not None:  # surligne la flèche à fixer
                pygame.draw.polygon(win, BAR_WIN, polys[phase["dir"]], 8)
            else:  # repos : croix de fixation centrale
                pygame.draw.line(win, WARN, (cx - 18, cy), (cx + 18, cy), 3)
                pygame.draw.line(win, WARN, (cx, cy - 18), (cx, cy + 18), 3)

            remain = (prep - (now - t_phase)) if state == "prep" else (phase["dur"] - (now - t_rec))
            head = ("PRÉPARE-TOI" if state == "prep" else "ENREGISTREMENT") + f"  ({idx + 1}/{len(phases)})"
            instr_surf = big.render(phase["instr"], True, TEXT)
            win.blit(instr_surf, instr_surf.get_rect(center=(cx, 46)))
            head_surf = mid.render(head, True, BAR_WIN if state == "record" else WARN)
            win.blit(head_surf, head_surf.get_rect(center=(cx, 92)))
            cnum = count_font.render(str(max(0, int(remain) + 1)), True, WARN if state == "prep" else BAR_WIN)
            win.blit(cnum, cnum.get_rect(center=(cx, h - 60)))

            pygame.display.flip()
            clock.tick(int(refresh) + 5)
            frame += 1
            if smoke and frame >= 40:
                running = False
    finally:
        acq.stop()
        pygame.quit()

    print("\n############ RÉCAPITULATIF ############")
    for key, mean in recap:
        if mean:
            print(f"{key:<9}: " + "  ".join(f"{f2name[f]}={mean[f]:.2f}" for f in mean))
    _save_raw(raw_epochs, raw_labels, plan, acq.fs, refresh, smoke)
    if smoke:
        print("[guided] smoke OK : protocole guidé câblé (headless).")


def _save_raw(epochs, labels, plan, fs, refresh, smoke):
    """Archive horodatée des fenêtres brutes 8 voies du protocole guidé."""
    if smoke or len(epochs) < 4:
        return
    import numpy as np
    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"ssvep_guided_{time.strftime('%Y%m%d-%H%M%S')}.npz")
    np.savez(path, epochs=np.asarray(epochs), labels=np.asarray(labels),
             fs=fs, refresh=refresh, ch_names=np.asarray(CH_NAMES),
             freqs=np.asarray([c["actual_hz"] for c in plan]),
             names=np.asarray([c["name"] for c in plan]))
    print(f"[guided] {len(epochs)} fenêtres brutes archivées : {os.path.basename(path)}")


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Diagnostic SSVEP live (EEG_API_Unicorn).")
    p.add_argument("--guided", action="store_true", help="protocole guidé (consignes + ρ par étape)")
    p.add_argument("--windowed", action="store_true")
    p.add_argument("--send", action="store_true", help="envoyer {jx,jy} en UDP à l'actionneur")
    p.add_argument("--synthetic", action="store_true", help="board de test (sans casque)")
    p.add_argument("--smoke", action="store_true", help="test headless (CI)")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    a = _parse_args(sys.argv[1:])
    if a.guided:
        guided(windowed=a.windowed, synthetic=a.synthetic, smoke=a.smoke)
    else:
        run(windowed=a.windowed, send=a.send, synthetic=a.synthetic, smoke=a.smoke)
