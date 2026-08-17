"""Application EEG_API_Unicorn : un menu, cinq modes de décodage, une seule session casque.

    python src/research/app.py                 # plein écran, casque réel
    python src/research/app.py --windowed      # fenêtre (pour garder la console à côté)
    python src/research/app.py --send          # envoi UDP au robot armé dès le départ
    python src/research/app.py --synthetic     # sans casque (board de test BrainFlow)
    python src/research/app.py --smoke         # test headless (CI)

Les modes de commande produisent la MÊME chose — une consigne {jx, jy} émise en UDP —
mais par trois voies neurophysiologiques différentes :

  [1] SSVEP   flèches clignotant à 8.57/15/20 Hz, décodage CCA. Aucune calibration, marche
              tout de suite. C'est le mode de référence, validé sur le robot.
  [2] c-VEP   flèches affichant une m-séquence décalée, décodage par template appris.
              Calibration courte (~1 min) ; spectre étalé, donc pas de concurrence avec
              le pic alpha (contrairement au SSVEP).
  [3] P300    oddball : les cibles clignotent une à une, on fixe+compte celle qu'on veut ;
              son flash évoque un P300 (ligne médiane Fz/Cz/Pz). SÉLECTION DISCRÈTE (pas de
              contrôle continu) décodée par xDAWN+Riemann. Calibration ~3-4 min.

Le Motor Imagery, quatrième voie historique de cette famille, a quitté cette appli : il est
publié par le moteur et se pilote (calibration comprise) depuis la console — voir
`src/core/modes/mi.py` et `src/core/modes/mi_calib.py`. Son écran pygame d'origine est archivé,
encore exécutable, dans `archive/` (voir `archive/README.md`).

L'appli garde UNE session BrainFlow et UN socket ouverts pour toute la durée : passer d'un
mode à l'autre est instantané (ESC ramène au menu, sans rouvrir le Bluetooth).
"""

import argparse
import contextlib
import os
import sys
import threading
import time
from collections import Counter, deque

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (ALPHA_PEAK_HZ, ARTIFACT_SIGMA_RATIO, BANDPASS, COMMANDS,  # noqa: E402
                    CVEP_CHANNELS, CVEP_CORR_MIN, CVEP_DECISION_CYCLES,
                    CVEP_MIN_VOTES, CVEP_MODEL_PATH, CVEP_RCCA_CORR_MIN, CVEP_RCCA_MODEL_PATH,
                    CVEP_VOTE_LEN, ERRP_DEMO_ERROR_RATE, ERRP_EPOCH_S, ERRP_FEEDBACK_S,
                    ERRP_MAX_RUN_STEPS, ERRP_MIDLINE, ERRP_MODEL_PATH, ERRP_PRE_S,
                    ERRP_TRACK_CELLS, N_HARMONICS,
                    NEURO_BASELINE_S, NEURO_KEY_CHANNELS, NEURO_UPDATE_HZ,
                    NEURO_WARMUP_S, NEURO_WINDOW_S, NEURO_Z_SPAN, OCCIPITAL,
                    P300_BURST_S, P300_EPOCH_S, P300_FLASH_OFF_FR, P300_FLASH_ON_FR,
                    P300_MIDLINE, P300_MIN_REPS, P300_MODEL_PATH, P300_PRE_S, P300_REPS,
                    P300_SELECT_MARGIN, P300_STOP_MARGIN,
                    p300_targets, RHO_MIN, SSVEP_BASELINE_S, UDP_HOST,
                    available_frequencies, choose_frequencies, use_utf8_console)
from core.neuro_monitor import IndexNormalizer, NeuroDecoder  # noqa: E402
from research.controller import SSVEPController  # noqa: E402
from research.itr import itr as _itr  # noqa: E402
from research.ssvep_stimulus import is_on as ssvep_on  # noqa: E402
from research.ui import (ACCENT, BAR_BG, BG, DIM, FG, GO, ON_COLOR, OUTLINE, WARN, Abort, App)  # noqa: E402


# --- État partagé entre le rendu (60 fps) et le décodage (thread séparé) ----
# Le décodage ne DOIT PAS tourner dans la boucle de rendu : une CCA de 10 ms suffirait à
# faire sauter une frame, et le clignotement perdrait sa régularité (SSVEP/c-VEP inutilisables).

class Live:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.cmd, self.scores, self.sigma, self.ready = None, {}, 0.0, False
        self.frame, self.t_flip = 0, time.perf_counter()

    def publish(self, cmd, scores, sigma):
        with self.lock:
            self.cmd, self.scores, self.sigma, self.ready = cmd, scores, sigma, True

    def snapshot(self):
        with self.lock:
            return self.cmd, dict(self.scores), self.sigma, self.ready

    def mark_frame(self, frame):
        """Horodate la frame qui vient d'être affichée (sert à retrouver la phase du code)."""
        with self.lock:
            self.frame, self.t_flip = frame, time.perf_counter()

    def phase(self, refresh, code_len):
        """Position actuelle dans le code, extrapolée depuis la dernière frame affichée."""
        with self.lock:
            f, t = self.frame, self.t_flip
        return int(f + (time.perf_counter() - t) * refresh) % code_len


def _sender_loop(app, live, hz=15.0):
    """Ré-émet la consigne courante en continu : sans réémission, le chien de garde de
    l'actionneur coupe au bout de 0,5 s (cf. docs/robot_testbed.md)."""
    while not live.stop.is_set():
        cmd, _, _, _ = live.snapshot()
        app.emit(cmd["jx"] if cmd else 0.0, cmd["jy"] if cmd else 0.0)
        time.sleep(1.0 / hz)


def _vote(buffer, min_votes, name_to_cmd):
    winner, count = Counter(buffer).most_common(1)[0]
    return name_to_cmd[winner] if (winner is not None and count >= min_votes) else None


# --- Rendu commun aux modes ------------------------------------------------

def _panel(app, order, scores, threshold, cmd, sigma, ready, subtitle, scale=1.0):
    pg = app.pygame
    w, h = app.size
    x, y = int(w * 0.06), int(h * 0.68)
    barw = int(w * 0.30)
    if not ready:
        app.center(app.big, "acquisition...", DIM, int(h * 0.62))
        return
    title = cmd["name"] if cmd else "—   (rien détecté)"
    app.center(app.big, title, GO if cmd else DIM, int(h * 0.60))
    for i, name in enumerate(order):
        v = float(scores.get(name, 0.0))
        ry = y + i * int(h * 0.045)
        pg.draw.rect(app.win, BAR_BG, (x + int(w * 0.13), ry, barw, 16))
        col = GO if (cmd and cmd["name"] == name) else ACCENT
        pg.draw.rect(app.win, col,
                     (x + int(w * 0.13), ry, int(barw * min(max(v / scale, 0.0), 1.0)), 16))
        tx = x + int(w * 0.13) + int(barw * min(threshold / scale, 1.0))
        pg.draw.line(app.win, WARN, (tx, ry - 3), (tx, ry + 19), 2)   # repère du seuil
        app.win.blit(app.small.render(f"{name:<8} {v:5.2f}", True, FG), (x, ry - 2))
    app.hud(f"{subtitle}   σ≈{sigma:.0f}   seuil={threshold:.2f}   "
            f"{'⚠ UDP ROBOT ACTIF' if app.send else 'UDP off'}   ESC=menu",
            WARN if app.send else DIM)


def _arrow_painter(app, plan, polys, on_fn, highlight_target=False):
    """Peintre « flèches » (SSVEP). Voir l'avertissement sur `highlight_target`."""
    pg = app.pygame

    def paint(frame, cmd):
        for c in plan:
            d = c["dir"]
            pg.draw.polygon(app.win, OUTLINE, polys[d], 2)
            if on_fn is not None and on_fn(c, frame):
                pg.draw.polygon(app.win, ON_COLOR, polys[d])
            if highlight_target and cmd is not None and cmd["dir"] == d:
                pg.draw.polygon(app.win, GO, polys[d], 8)
    return paint


def _live_loop(app, live, order, threshold, subtitle, paint, scale=1.0):
    """Boucle de rendu commune : `paint(frame, cmd)` dessine les cibles, le reste est partagé.

    Le paramètre `paint` existe parce que les modes n'ont plus la même géométrie : SSVEP
    utilise 4 directions de flèche, le c-VEP une couronne de N cibles (c'est justement ce qui
    lui permet de dépasser 4 commandes).

    ⚠️ Aucun mode à stimulus ne doit surligner la cible détectée : un élément statique lumineux
    en pleine fovée écrase la modulation de contraste, donc la réponse — la détection retombe,
    le surlignage disparaît, puis revient. Le retour visuel passe par le panneau, hors du regard.
    """
    frame = 0
    while True:
        app.drain()
        app.win.fill(BG)
        cmd, scores, sigma, ready = live.snapshot()
        paint(frame, cmd)
        _panel(app, order, scores, threshold, cmd, sigma, ready, subtitle, scale=scale)
        app.pygame.display.flip()
        live.mark_frame(frame)
        app.clock.tick(int(app.refresh) + 5)
        frame += 1
        if app.smoke and frame >= 40:
            return


@contextlib.contextmanager
def _running(app, decode_fn, *args):
    """Démarre décodage + émission, puis nettoie — y compris un stop robot franc en sortant."""
    live = Live()
    threading.Thread(target=decode_fn, args=(app, live) + args, daemon=True).start()
    threading.Thread(target=_sender_loop, args=(app, live), daemon=True).start()
    try:
        yield live
    except Abort:
        pass                 # ESC = retour au menu, pas une erreur
    finally:
        live.stop.set()
        time.sleep(0.15)
        app.emit(0.0, 0.0)   # consigne neutre en quittant le mode


# --- Mode 1 : SSVEP --------------------------------------------------------

def _ssvep_decode(app, live, ctrl, f2name, sigma_ref=None, hz=5.0):
    """`sigma_ref` : amplitude de référence mesurée au repos. Une fenêtre dont le σ la dépasse
    d'un facteur ARTIFACT_SIGMA_RATIO est un artefact (mouvement, clignement) : on la rejette
    au lieu d'en décoder des ρ aléatoires."""
    limit = None if not sigma_ref else ARTIFACT_SIGMA_RATIO * sigma_ref
    while not live.stop.is_set():
        w = app.acq.get_window()
        if w is not None:
            sd = float(w.std(axis=0).mean())
            if limit and sd > limit:
                live.publish(ctrl.skip(), live.snapshot()[1], sd)
            else:
                cmd, sc = ctrl.decide_scored(w)
                live.publish(cmd, {f2name[round(f, 4)]: v for f, v in sc.items()}, sd)
        time.sleep(1.0 / hz)


def _ssvep_baseline(app, ctrl, plan, polys, fpc, seconds, f2name):
    """Mesure le plancher de ρ au repos, CIBLES CLIGNOTANTES mais sans rien fixer.

    C'est la condition de repos réelle : chaque fréquence hérite d'un fond différent selon
    sa proximité avec le pic alpha du jour. Sans cette mesure, un seuil global favorise les
    cibles éloignées de l'alpha et étouffe les autres (mesuré : GAUCHE 0/27 émissions alors
    que son ρ moyen dépassait le seuil). Refaite à chaque session -> s'adapte à l'état du jour.
    """
    pg = app.pygame
    samples, sigmas, frame, t0, last = [], [], 0, time.perf_counter(), 0.0
    while True:
        app.drain()
        now = time.perf_counter()
        left = seconds - (now - t0)
        if left <= 0:
            break
        if now - last >= 0.2:
            last = now
            w = app.acq.get_window()
            if w is not None:
                samples.append(ctrl.decoder.scores(w))
                sigmas.append(float(w.std(axis=0).mean()))
        app.win.fill(BG)
        for c in plan:
            d = c["dir"]
            pg.draw.polygon(app.win, OUTLINE, polys[d], 2)
            if ssvep_on(frame, fpc[d]):
                pg.draw.polygon(app.win, ON_COLOR, polys[d])
        h = app.size[1]
        app.center(app.big, "REPOS — ne fixe AUCUNE flèche", FG, 52)
        app.center(app.mid, "mesure du bruit de fond (adapte les seuils à ta journée)",
                   DIM, 100)
        app.center(app.big, f"{int(left) + 1}", WARN, int(h * 0.86))
        pg.display.flip()
        app.clock.tick(int(app.refresh) + 5)
        frame += 1
        if app.smoke and frame >= 20:
            break
    sigma_ref = float(np.median(sigmas)) if sigmas else None
    if ctrl.decoder.fit_baseline(samples):
        line = "  ".join(f"{f2name[round(f, 4)]}: μ={m:.2f} σ={s:.2f}"
                         for f, (m, s) in ctrl.decoder.baseline.items())
        print(f"[ssvep] plancher repos ({len(samples)} fenêtres) — {line}")
        if sigma_ref:
            print(f"[ssvep] amplitude de référence σ={sigma_ref:.1f} -> rejet d'artefact "
                  f"au-delà de {ARTIFACT_SIGMA_RATIO * sigma_ref:.0f}")
        _log_baseline(app, ctrl, f2name, len(samples))
        return sigma_ref
    print(f"[ssvep] plancher non mesuré ({len(samples)} fenêtres) -> seuil ρ brut {RHO_MIN}")
    return sigma_ref


def _log_baseline(app, ctrl, f2name, n_samples):
    """Ajoute une ligne à data/ssvep_baselines.csv à chaque session.

    Le plancher de repos varie d'un jour à l'autre avec l'alpha, et c'est LUI qui décide si une
    cible proche du pic (12 Hz) sera fragile ce jour-là. Accumuler la série permet de vérifier
    l'hypothèse « la performance de GAUCHE suit son plancher » sans travail supplémentaire —
    au lieu de laisser le chiffre défiler dans la console et de raisonner de mémoire.
    """
    path = os.path.join(DATA_DIR, "ssvep_baselines.csv")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        new = not os.path.exists(path)
        cols = [f2name[round(f, 4)] for f in ctrl.decoder.freqs]
        with open(path, "a", encoding="utf-8") as fh:
            if new:
                fh.write("horodatage,fenetres," + ",".join(
                    f"{c}_mu,{c}_sigma" for c in cols) + "\n")
            vals = []
            for f in ctrl.decoder.freqs:
                mu, sd = ctrl.decoder.baseline[f]
                vals += [f"{mu:.4f}", f"{sd:.4f}"]
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')},{n_samples}," + ",".join(vals) + "\n")
        print(f"[ssvep] plancher consigné dans data/{os.path.basename(path)}")
    except OSError as e:   # journalisation best-effort : ne doit jamais empêcher de piloter
        print(f"[ssvep] (plancher non consigné : {e})")


def _freq_flags(freq, others):
    """Infos d'aide au choix pour une fréquence : (harmoniques dans la bande, note alpha,
    nom d'une direction en conflit d'harmonique | None). Purement indicatif — rien n'est
    interdit, l'exploration est le but."""
    lo, hi = BANDPASS
    mine = [h * freq for h in range(1, N_HARMONICS + 1) if h * freq <= hi]
    d = abs(freq - ALPHA_PEAK_HZ)
    alpha = "SUR le pic alpha" if d < 1.0 else ("proche du pic alpha" if d < 2.5 else "")
    clash = None
    for name, f2 in others:
        theirs = [h * f2 for h in range(1, N_HARMONICS + 1) if h * f2 <= hi]
        if any(abs(a - b) <= 0.25 for a in mine for b in theirs):
            clash = name
            break
    return [round(x, 2) for x in mine], alpha, clash


def _draw_freq_picker(app, plan, avail, sel, row):
    """Écran de sélection : une ligne par direction, la ligne active est surlignée."""
    app.win.fill(BG)
    w, h = app.size
    app.center(app.big, f"SSVEP — fréquences (écran {app.refresh:.0f} Hz)", FG, int(h * 0.11))
    app.center(app.small,
               "HAUT/BAS : direction     GAUCHE/DROITE : fréquence     "
               "ENTRÉE : lancer     ESC : menu", DIM, int(h * 0.18))
    y = int(h * 0.32)
    for i, c in enumerate(plan):
        n, f = avail[sel[i]]
        others = [(plan[j]["name"], avail[sel[j]][1]) for j in range(len(plan)) if j != i]
        harm, alpha, clash = _freq_flags(f, others)
        active = (i == row)
        mark = "> " if active else "  "
        app.center(app.mid, f"{mark}{c['name']:<7} {f:7.3f} Hz   (1 frame /{n})",
                   ACCENT if active else DIM, y)
        if active:
            app.center(app.small,
                       "harmoniques en bande : " + ", ".join(f"{x:g}" for x in harm),
                       DIM, y + int(h * 0.045))
            tags = [t for t in (alpha, (f"conflit d'harmonique avec {clash}" if clash else ""))
                    if t]
            if tags:
                app.center(app.small, "  ·  ".join(tags), WARN, y + int(h * 0.072))
        y += int(h * 0.155)
    app.pygame.display.flip()
    app.clock.tick(60)


def _pick_ssvep_frequencies(app, plan):
    """Sélecteur manuel des fréquences SSVEP, une par direction, avant de lancer le mode.

    But : explorer LIBREMENT toutes les fréquences sans jitter (diviseurs entiers du refresh),
    y compris celles en conflit d'harmoniques — le conflit est SIGNALÉ, pas interdit (le but
    est de tester, p. ex. GAUCHE à 12 Hz trop près de l'alpha vs 20 Hz). Seul cas REFUSÉ :
    deux directions sur la même fréquence, que le décodeur confondrait (clé `actual_hz` unique).

    Retourne un plan aux mêmes clés que choose_frequencies(), ou lève Abort (ESC = retour menu).
    """
    if app.smoke:
        return plan
    pg = app.pygame
    avail = available_frequencies(app.refresh)             # [(n, freq)] de la plus haute à la plus basse
    def _start_index(c):
        if c["frames_per_cycle"] in [n for n, _ in avail]:
            return [n for n, _ in avail].index(c["frames_per_cycle"])
        return min(range(len(avail)), key=lambda i: abs(avail[i][1] - c["actual_hz"]))
    sel = [_start_index(c) for c in plan]
    row, go = [0], []

    def on_key(e):
        if e.key in (pg.K_UP, pg.K_w):
            row[0] = (row[0] - 1) % len(plan)
        elif e.key in (pg.K_DOWN, pg.K_s):
            row[0] = (row[0] + 1) % len(plan)
        elif e.key in (pg.K_RIGHT, pg.K_d):        # droite = fréquence plus HAUTE (indice plus bas)
            sel[row[0]] = (sel[row[0]] - 1) % len(avail)
        elif e.key in (pg.K_LEFT, pg.K_a):
            sel[row[0]] = (sel[row[0]] + 1) % len(avail)
        elif e.key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE):
            go.append(True)

    while True:
        app.drain(on_key=on_key)                   # ESC -> Abort, remonte au menu
        if go:
            ns = [avail[sel[i]][0] for i in range(len(plan))]
            if len(set(ns)) < len(ns):
                app.flash("Même fréquence sur deux directions",
                          "le décodeur les confondrait — modifie l'une d'elles", 3.0)
                go.clear()
                continue
            return [{**c, "frames_per_cycle": avail[i][0], "actual_hz": app.refresh / avail[i][0]}
                    for c, i in zip(plan, sel)]
        _draw_freq_picker(app, plan, avail, sel, row[0])


def mode_ssvep(app):
    # contrôle de liaison + voies clés (occipitales) encadrées AVANT le run ; casque injoignable
    # ou ESC -> retour menu (pas de traceback)
    if not app.signal_check(highlight=OCCIPITAL, mode_label="SSVEP"):
        return
    plan = choose_frequencies(app.refresh)
    try:
        plan = _pick_ssvep_frequencies(app, plan)
    except Abort:
        return   # ESC dans le sélecteur = retour au menu
    ctrl = SSVEPController(plan)
    f2name = {round(c["actual_hz"], 4): c["name"] for c in plan}
    polys, _ = app.arrows(plan)
    fpc = {c["dir"]: c["frames_per_cycle"] for c in plan}
    print("[ssvep] " + "  ".join(f"{c['name']}={c['actual_hz']:.2f}Hz" for c in plan)
          + f"  vote={ctrl.min_votes}/{ctrl.buffer.maxlen}")

    sigma_ref = None
    try:
        if SSVEP_BASELINE_S > 0:
            sigma_ref = _ssvep_baseline(app, ctrl, plan, polys, fpc, SSVEP_BASELINE_S, f2name)
    except Abort:
        return   # ESC pendant la mesure = retour au menu
    thr, _ = ctrl.decoder.thresholds
    scale = 6.0 if ctrl.decoder.baseline else 1.0   # échelle z (~0..6) vs ρ (0..1)
    label = "SSVEP (CCA, normalisé)" if ctrl.decoder.baseline else "SSVEP (CCA, ρ brut)"

    paint = _arrow_painter(app, plan, polys, lambda c, f: ssvep_on(f, fpc[c["dir"]]))
    with _running(app, _ssvep_decode, ctrl, f2name, sigma_ref) as live:
        _live_loop(app, live, [c["name"] for c in plan], thr, label, paint, scale=scale)


# --- Mode 2 : c-VEP --------------------------------------------------------

def _cvep_decode(app, live, dec, rows, epoch_s, n_win, code_len, name_to_cmd, hz=5.0):
    votes = deque(maxlen=CVEP_VOTE_LEN)
    chans = dec.model.channels          # mêmes voies qu'à l'apprentissage du filtre spatial
    while not live.stop.is_set():
        ep = app.acq.get_epoch(epoch_s, rows=rows, filtered=False)
        phase = live.phase(app.refresh, code_len)   # lu juste après la fenêtre = même instant
        if ep is not None and len(ep) >= n_win:
            cmd, sc = dec.classify(ep[-n_win:, chans], phase)
            votes.append(cmd["name"] if cmd else None)
            live.publish(_vote(votes, CVEP_MIN_VOTES, name_to_cmd), sc,
                         float(ep.std(axis=0).mean()))
        time.sleep(1.0 / hz)


def mode_cvep(app, model_path=CVEP_MODEL_PATH):
    from research.cvep_code import build_targets, is_on as cvep_on
    from research.cvep_decoder import CVEPDecoder, CVEPModel

    if not os.path.exists(model_path):
        app.flash("Pas de modèle c-VEP",
                  "lance d'abord « c-VEP -> classique -> Calibrer » (~1 min)", 3.5)
        return
    plan, code = build_targets()
    model = CVEPModel.load(model_path)
    if abs(model.refresh - app.refresh) > 1.0:
        app.flash("Modèle c-VEP incompatible",
                  f"calibré à {model.refresh:.0f}Hz, écran à {app.refresh:.0f}Hz — recalibre", 4.0)
        return
    if not app.signal_check(highlight=CVEP_CHANNELS, mode_label="c-VEP"):
        return                    # liaison + voies clés (occipitales) ; casque KO ou ESC -> retour
    dec = CVEPDecoder(model, plan)
    spots = app.ring_spots(plan)
    rows = app.acq.eeg_rows          # on lit les 8, le modèle sélectionne ses voies
    name_to_cmd = {c["name"]: c for c in plan}
    cv = "?" if model.cv_ is None else f"{model.cv_*100:.0f}%"
    n_win = CVEP_DECISION_CYCLES * model.n_cyc          # fenêtre = k cycles, moyennés au décodage
    decision_s = CVEP_DECISION_CYCLES * len(code) / app.refresh
    # Le template est commun à tous les lags : un modèle à 3 cibles « fonctionne » à 6 sans
    # erreur, mais les 3 lags supplémentaires n'ont jamais été validés -> résultats trompeurs.
    n_saved = model.n_targets or 3   # modèles antérieurs au multi-cibles : tous à 3 cibles
    if n_saved != len(plan):
        app.flash(f"Modèle calibré pour {n_saved} cibles",
                  f"l'affichage en compte {len(plan)} — recalibre (c-VEP -> Calibrer)", 4.0)
        return
    if model.w is None or len(model.w) != len(model.channels):
        app.flash("Modèle c-VEP incohérent",
                  f"filtre spatial sur {0 if model.w is None else len(model.w)} voies pour "
                  f"{len(model.channels)} sélectionnées — recalibre (c-VEP -> Calibrer)", 4.0)
        return
    print(f"[cvep] {len(plan)} cibles  code L={len(code)} cycle={len(code)/app.refresh:.2f}s  "
          f"lags={[c['lag'] for c in plan]}  calib LOO={cv}")
    print(f"[cvep] décision sur {CVEP_DECISION_CYCLES} cycles ({decision_s:.2f}s)  "
          f"vote={CVEP_MIN_VOTES}/{CVEP_VOTE_LEN}  "
          f"ITR potentiel {_itr(len(plan), model.cv_ or 0.0, decision_s):.1f} bits/min")

    def paint(frame, cmd):
        app.draw_ring(plan, spots, lambda c, f: cvep_on(f, c["code"]), frame)

    with _running(app, _cvep_decode, dec, rows, n_win / app.acq.fs, n_win,
                  len(code), name_to_cmd) as live:
        _live_loop(app, live, [c["name"] for c in plan], CVEP_CORR_MIN,
                   f"c-VEP {len(plan)} cibles (calib {cv})", paint)


def mode_cvep_rcca(app, model_path=CVEP_RCCA_MODEL_PATH):
    """2e variante c-VEP : CODES DISTINCTS (Gold) décodés par reconvolution (rCCA, pyntbci).
    Réutilise _cvep_decode (interface classify(window, phase) identique à l'eCCA)."""
    from research.cvep_code import is_on as cvep_on
    from research.cvep_rcca import RCCADecoder, RCCAModel, build_targets_rcca

    if not os.path.exists(model_path):
        app.flash("Pas de modèle c-VEP rCCA",
                  "calibre d'abord « c-VEP -> rCCA + codes distincts -> Calibrer »", 3.5)
        return
    model = RCCAModel.load(model_path)
    if abs(model.refresh - app.refresh) > 1.0:
        app.flash("Modèle rCCA incompatible",
                  f"calibré à {model.refresh:.0f}Hz, écran à {app.refresh:.0f}Hz — recalibre", 4.0)
        return
    if not app.signal_check(highlight=CVEP_CHANNELS, mode_label="c-VEP rCCA"):
        return                    # liaison + voies clés (occipitales) ; casque KO ou ESC -> retour
    plan, _ = build_targets_rcca(model.n_targets)
    for i, c in enumerate(plan):
        c["code"] = model.codes[i].tolist()          # afficher EXACTEMENT les codes du modèle
    dec = RCCADecoder(model, plan, n_cycles=CVEP_DECISION_CYCLES)
    spots = app.ring_spots(plan)
    rows = app.acq.eeg_rows
    name_to_cmd = {c["name"]: c for c in plan}
    n_win = CVEP_DECISION_CYCLES * model.n_cyc
    cv = "?" if model.cv_ is None else f"{model.cv_*100:.0f}%"
    decision_s = CVEP_DECISION_CYCLES * model.code_len / app.refresh
    print(f"[rcca] {len(plan)} cibles à CODES DISTINCTS  cycle={model.code_len/app.refresh:.2f}s  "
          f"calib LOO={cv}")
    print(f"[rcca] décision sur {CVEP_DECISION_CYCLES} cycles ({decision_s:.2f}s)  "
          f"vote={CVEP_MIN_VOTES}/{CVEP_VOTE_LEN}  "
          f"ITR potentiel {_itr(len(plan), model.cv_ or 0.0, decision_s):.1f} bits/min")

    def paint(frame, cmd):
        app.draw_ring(plan, spots, lambda c, f: cvep_on(f, c["code"]), frame)

    with _running(app, _cvep_decode, dec, rows, n_win / app.acq.fs, n_win,
                  model.code_len, name_to_cmd) as live:
        _live_loop(app, live, [c["name"] for c in plan], CVEP_RCCA_CORR_MIN,
                   f"c-VEP rCCA {len(plan)} cibles (calib {cv})", paint)


# --- Mode 3 : P300 (oddball, sélection discrète par attention) --------------

def _p300_ready(app, plan, spots, seconds=2.2):
    """Court écran « choisis ta cible » avant chaque sélection (anneau au repos, rien ne clignote)."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        app.drain()
        app.win.fill(BG)
        h = app.size[1]
        app.center(app.big, "Choisis ta cible", FG, int(h * 0.12))
        app.center(app.mid, "fixe-la et COMPTE ses éclairs — la sélection démarre", DIM,
                   int(h * 0.19))
        app.draw_ring(plan, spots, lambda c, f: False, 0)
        app.pygame.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return


def _p300_panel(app, order, scores, cmd):
    """Barres des scores « cible » par direction (log-odds moyens), gagnant en vert."""
    if not scores:
        return
    pg = app.pygame
    w, h = app.size
    lo = min(scores.values())
    span = max(1e-6, max(scores.values()) - lo)
    x, y, barw = int(w * 0.06), int(h * 0.66), int(w * 0.30)
    for i, name in enumerate(order):
        v = (scores.get(name, lo) - lo) / span
        ry = y + i * int(h * 0.045)
        pg.draw.rect(app.win, BAR_BG, (x + int(w * 0.16), ry, barw, 16))
        col = GO if (cmd and cmd["name"] == name) else ACCENT
        pg.draw.rect(app.win, col, (x + int(w * 0.16), ry, int(barw * v), 16))
        app.win.blit(app.small.render(f"{name:<10} {scores.get(name, 0.0):+5.2f}", True, FG),
                     (x, ry - 2))


def _p300_emit_burst(app, plan, spots, cmd, scores):
    """Exécute la commande sélectionnée en RAFALE pendant P300_BURST_S (ré-émission ~15 Hz pour
    le chien de garde de l'actionneur), puis STOP. Aucune commande nette -> rien émis."""
    order = [c["name"] for c in plan]
    t0 = time.perf_counter()
    last = 0.0
    while time.perf_counter() - t0 < P300_BURST_S:
        app.drain()
        now = time.perf_counter()
        if cmd and now - last >= 1.0 / 15.0:
            app.emit(cmd["jx"], cmd["jy"])
            last = now
        app.win.fill(BG)
        h = app.size[1]
        title = cmd["name"] if cmd else "—  (aucune sélection nette)"
        app.center(app.big, title, GO if cmd else DIM, int(h * 0.14))
        app.draw_ring(plan, spots, lambda c, f: False, 0, cue=(cmd["name"] if cmd else None))
        _p300_panel(app, order, scores, cmd)
        app.hud(f"P300 — exécution {P300_BURST_S:.1f}s   "
                f"{'⚠ UDP ROBOT ACTIF' if app.send else 'UDP off'}   ESC=menu",
                WARN if app.send else DIM)
        app.pygame.display.flip()
        app.clock.tick(int(app.refresh) + 5)
        if app.smoke:
            break
    app.emit(0.0, 0.0)


def _p300_margin(scores):
    """Marge = score du 1er - score du 2e (log-odds moyens). Critère d'arrêt dynamique."""
    vals = sorted(scores.values(), reverse=True)
    return (vals[0] - vals[1]) if len(vals) > 1 else float("inf")


def _p300_log_scores(scores, pick, by, reps):
    """Console : score moyen (log-odds « cible ») par direction, trié, + marge 1er-2e, nombre de
    répétitions utilisées et d'époques par cible. Diagnostique un biais fixe (une cible toujours
    en tête) vs un signal faible (marges minuscules), et montre l'économie de l'arrêt dynamique."""
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    margin = (ranked[0][1] - ranked[1][1]) if len(ranked) > 1 else 0.0
    print(f"[p300] pick={pick}  {reps} rép  marge_1er-2e={margin:+.2f}  "
          f"n_époques={ {nm: len(v) for nm, v in by.items()} }")
    print("        scores: " + "  ".join(f"{nm}={sc:+.2f}" for nm, sc in ranked))


def _p300_save_debug(debug, fs):
    """Sauve les époques live (par cible, par sélection) dans data/p300_live_last.npz, pour
    rejouer le décodage hors ligne — indispensable pour diagnostiquer le « toujours la même
    cible » sans monopoliser le casque."""
    eps, names, sel = [], [], []
    for si, (by, _scores, _pick) in enumerate(debug):
        for nm, arr in by.items():
            for e in arr:
                eps.append(np.asarray(e))
                names.append(nm)
                sel.append(si)
    if not eps:
        return
    path = os.path.join(os.path.dirname(P300_MODEL_PATH), "p300_live_last.npz")
    try:
        np.savez(path, epochs=np.asarray(eps), names=np.asarray(names),
                 sel=np.asarray(sel), fs=fs)
        print(f"[p300] {len(eps)} époques live sauvées -> {os.path.basename(path)} (diagnostic)")
    except OSError as e:   # best-effort, ne doit pas gêner la sortie du mode
        print(f"[p300] (sauvegarde debug live échouée : {e})")


def mode_p300(app, model_path=P300_MODEL_PATH, dynamic=False):
    import random as _random

    from research.p300_calibrate import _blank_ring, _flash_targets
    from core.p300_decoder import epoch_from_stream
    from core.p300_models import charger

    # `os.path.exists` ne suffit pas : un modèle antérieur au déménagement du décodeur dans
    # core/ (2026-08-17) EXISTE toujours sur le disque mais ne se charge plus (pickle sous
    # l'ancien module nu `p300_decoder`) -> `P300Model.load` lèverait en pleine séance, après le
    # signal_check. `charger` ne lève jamais et dit quoi faire (ré-entraîner depuis une calibration).
    model, probleme = charger(model_path)
    if model is None:
        app.flash("Pas de modèle P300 utilisable",
                  probleme or "lance d'abord « P300 -> Calibrer » (~4-5 min)", 4.0)
        return
    if not app.signal_check(highlight=P300_MIDLINE, mode_label="P300"):
        return                    # liaison + voies clés (Fz/Cz/Pz) ; casque KO ou ESC -> retour
    plan = p300_targets()
    n = len(plan)
    spots = app.ring_spots(plan)
    name_to_cmd = {c["name"]: c for c in plan}
    on_fr, off_fr = P300_FLASH_ON_FR, P300_FLASH_OFF_FR
    rng = _random.Random()
    fs = app.acq.fs
    soa = (on_fr + off_fr) / app.refresh
    auc = "?" if model.cv_auc_ is None else f"{model.cv_auc_*100:.0f}%"
    mode = (f"ARRÊT DYNAMIQUE (min {P300_MIN_REPS}, max {P300_REPS} rép, marge {P300_STOP_MARGIN})"
            if dynamic else f"{P300_REPS} rép fixes (~{P300_REPS*n*soa:.1f}s)")
    print(f"[p300] {n} cibles  SOA={soa*1000:.0f}ms  AUC calib={auc}  {mode}")

    def extract(all_flashes, extracted, by, t_start):
        """Découpe les époques désormais COMPLÈTES (post-stim rempli) pas encore extraites."""
        eeg, ts = app.acq.get_raw(time.time() - t_start + P300_PRE_S + 0.5)
        if eeg is None:
            return
        for i, (t, onset) in enumerate(all_flashes):
            if i in extracted:
                continue
            ep = epoch_from_stream(eeg, ts, onset, fs)
            if ep is not None:
                by[plan[t]["name"]].append(ep)
                extracted.add(i)

    debug = []          # (by, scores, pick) par sélection -> sauvés à la sortie pour diagnostic
    try:
        while True:
            _p300_ready(app, plan, spots)
            by = {c["name"]: [] for c in plan}
            all_flashes, extracted = [], set()
            t_start = time.time()
            used = P300_REPS
            for rep in range(P300_REPS):
                order = list(range(n))
                rng.shuffle(order)
                all_flashes += _flash_targets(app, plan, spots, None, order, on_fr, off_fr)
                if dynamic:      # accumule au fil de l'eau et stoppe si la cible se détache
                    extract(all_flashes, extracted, by, t_start)
                    if rep + 1 >= P300_MIN_REPS and all(len(v) >= P300_MIN_REPS
                                                        for v in by.values()):
                        _, sc = model.select(by)
                        if _p300_margin(sc) >= P300_STOP_MARGIN:
                            used = rep + 1
                            break
                if app.smoke:
                    used = rep + 1
                    break
            _blank_ring(app, plan, spots, None, int(round((P300_EPOCH_S + 0.15) * app.refresh)))
            extract(all_flashes, extracted, by, t_start)     # récupère les derniers flashs
            if any(by.values()):
                pick, scores = model.select(by, margin=P300_SELECT_MARGIN)
                _p300_log_scores(scores, pick, by, used)
                debug.append((by, scores, pick))
                _p300_emit_burst(app, plan, spots, name_to_cmd.get(pick), scores)
            if app.smoke:
                return
    except Abort:
        app.emit(0.0, 0.0)
        _p300_save_debug(debug, fs)                        # capture les époques live (diagnostic)
        return


# --- Mode 4 : Neuro-monitoring passif (workload / vigilance / attention) -----
# BCI PASSIF : rien n'est envoyé au robot. On mesure des indices spectraux (θ/α/β) et on les
# affiche en HISTOGRAMME temps réel, normalisés en z contre un repos mesuré à l'entrée du mode.
# Voir neuro_monitor.py pour les formules et leur limite (indices corrélés, dérivants). Pas de
# thread de décodage/émission : sans stimulus clignotant, le calcul (PSD ~ms) tient dans la boucle.

_NEURO_VIEW = [   # (clé, libellé, formule courte, couleur, sens de la montée)
    ("charge",     "Charge mentale", "θ(Fz,Cz) / α post.", ACCENT, "+ = plus chargé"),
    ("somnolence", "Somnolence",     "α postérieur",       WARN,   "+ = assoupissement"),
    ("engagement", "Engagement",     "β/(α+θ) post-c.",    GO,     "+ = plus attentif"),
]


def _neuro_sample(app, decoder):
    """Une fenêtre BRUTE (n, 8) -> échantillon du décodeur, ou None si le buffer n'est pas prêt.

    Le calcul lui-même vit dans `core.neuro_monitor.NeuroDecoder`, partagé avec le moteur : ce
    mode s'affiche ici ET se publie sur le réseau, et deux copies du même calcul finiraient par
    diverger — l'écran montrerait une charge mentale, le flux LSL une autre."""
    return decoder.sample(app.acq.get_epoch(NEURO_WINDOW_S, filtered=False))


def _neuro_warmup(app, seconds):
    """Écran de stabilisation JETÉ avant le repos : laisse les électrodes sèches se poser (le settling
    d'impédance fausserait le repos et ferait dériver le zéro, cf. eeg-hardware piège #0ter)."""
    if seconds <= 0:
        return
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        app.drain()
        left = seconds - (time.perf_counter() - t0)
        app.win.fill(BG)
        h = app.size[1]
        app.center(app.big, "Stabilisation du casque...", FG, int(h * 0.40))
        app.center(app.mid, "on laisse les électrodes se poser avant de mesurer le repos",
                   DIM, int(h * 0.50))
        app.center(app.big, f"{int(left) + 1}", WARN, int(h * 0.62))
        app.pygame.display.flip()
        app.clock.tick(30)
        if app.smoke:
            return


def _neuro_baseline(app, decoder, seconds):
    """Repos yeux ouverts (précédé d'un warm-up jeté) : cale les échelles du jour sur `decoder`.

    Retourne True si le plancher a pu être mesuré."""
    _neuro_warmup(app, NEURO_WARMUP_S)
    t0, last, samples = time.perf_counter(), 0.0, []
    while True:
        app.drain()                          # ESC -> Abort -> retour menu (absorbé par _mode_page)
        now = time.perf_counter()
        left = seconds - (now - t0)
        if left <= 0:
            break
        if now - last >= 1.0 / NEURO_UPDATE_HZ:
            last = now
            s = _neuro_sample(app, decoder)
            if s is not None:
                samples.append(s)
        app.win.fill(BG)
        h = app.size[1]
        app.center(app.big, "REPOS — regarde l'écran, détends-toi", FG, int(h * 0.30))
        app.center(app.mid, "calage des échelles sur TON repos du jour (yeux ouverts, immobile)",
                   DIM, int(h * 0.40))
        app.center(app.small, f"{len(samples)} fenêtres", DIM, int(h * 0.47))
        app.center(app.big, f"{int(left) + 1}", WARN, int(h * 0.64))
        app.pygame.display.flip()
        app.clock.tick(30)
        if app.smoke and (len(samples) >= 3 or time.perf_counter() - t0 > 1.0):
            break
    if not decoder.fit_baseline(samples):
        return False
    print("[neuro] repos %d fenêtres — %s  σ_ref(moy)=%.0f  emg_ref=%.2f" % (
        len(samples), "  ".join(f"{k}:μ≈{decoder.norm.center(k):.2f}" for k in decoder.norm.mu),
        float(np.mean(decoder.sigma_ref)), decoder.emg_ref))
    return True


def _neuro_bars(app, z, artifact, arts, reason):
    """Histogramme : 3 barres verticales divergentes autour d'une ligne « repos » (z=0). Une barre
    qui monte = indice au-dessus du repos, qui descend (grise) = en dessous."""
    pg = app.pygame
    w, h = app.size
    app.win.fill(BG)
    app.center(app.big, "Neuro-monitoring passif", FG, int(h * 0.08))
    app.center(app.small, "indices relatifs à TON repos (z) — une TENDANCE, pas une mesure absolue",
               DIM, int(h * 0.14))
    y_top, y_bot = int(h * 0.26), int(h * 0.70)
    y_mid = (y_top + y_bot) // 2
    half = y_mid - y_top
    barw = int(w * 0.09)
    pg.draw.line(app.win, OUTLINE, (int(w * 0.14), y_mid), (int(w * 0.86), y_mid), 1)
    app.win.blit(app.small.render("repos (0)", True, DIM), (int(w * 0.05), y_mid - 8))
    for i, (key, label, formula, col, sense) in enumerate(_NEURO_VIEW):
        cx = int(w * (0.28 + 0.22 * i))
        pg.draw.rect(app.win, BAR_BG, (cx - barw // 2, y_top, barw, y_bot - y_top))
        zi = float(z.get(key, 0.0))
        frac = float(np.tanh(zi / NEURO_Z_SPAN))   # compression douce : pas de plafond brutal
        bh = int(abs(frac) * half)
        if frac >= 0:
            pg.draw.rect(app.win, col, (cx - barw // 2, y_mid - bh, barw, bh))
        else:
            pg.draw.rect(app.win, DIM, (cx - barw // 2, y_mid, barw, bh))
        for dy, font, text, c in ((0.055, app.mid, label, FG),
                                  (0.10, app.small, formula, DIM),
                                  (0.135, app.small, sense, DIM),
                                  (0.185, app.mid, f"z={zi:+.1f}", col)):
            s = font.render(text, True, c)
            app.win.blit(s, s.get_rect(center=(cx, y_bot + int(h * dy))))
    if artifact:
        app.center(app.mid, f"ARTEFACT ({reason}) — fenêtre ignorée", WARN, int(h * 0.20))
    app.hud(f"Neuro-monitoring PASSIF (aucun envoi robot)   artefacts ignorés={arts}   ESC=menu", DIM)


def _neuro_live(app, decoder):
    """Boucle d'affichage : recalcule les indices à NEURO_UPDATE_HZ et dessine l'histogramme.

    Le veto d'artefact, la normalisation et le re-calage lent du zéro sont dans le décodeur
    partagé — ici il ne reste que le rythme, l'affichage et le journal."""
    z = {k: 0.0 for k, *_ in _NEURO_VIEW}
    last, artifact, reason, frame, last_log = 0.0, False, "", 0, 0.0
    while True:
        app.drain()
        now = time.perf_counter()
        if now - last >= 1.0 / NEURO_UPDATE_HZ:
            last = now
            s = _neuro_sample(app, decoder)
            if s is not None:
                out = decoder.step(s)
                z, artifact, reason = out["z"], out["artifact"], out["reason"]
                if now - last_log >= 1.0:           # diagnostic : brut vs normalisé, ~1×/s
                    last_log = now
                    keys = [k for k, *_ in _NEURO_VIEW]
                    print("[neuro] brut " +
                          "  ".join(f"{k}={s['idx'][k]:.3f}" for k in keys) +
                          "  z " + "  ".join(f"{k}={z[k]:+.2f}" for k in keys) +
                          f"  centre_eng≈{decoder.norm.center('engagement'):.3f}"
                          f"  artefacts={decoder.artifacts}" + (f"  ({reason})" if artifact else ""))
        _neuro_bars(app, z, artifact, decoder.artifacts, reason)
        app.pygame.display.flip()
        app.clock.tick(30)
        frame += 1
        if app.smoke and frame >= 40:
            return


def mode_neuro(app):
    """Mode 4 : histogramme temps réel de 3 indices d'état mental. PASSIF (aucune commande robot).

    Déroulé : contrôle liaison (Fz/Pz encadrées) -> warm-up jeté -> repos yeux ouverts (cale les
    échelles z du jour) -> histogramme live jusqu'à ESC (z re-calé lentement contre la dérive)."""
    if not app.signal_check(highlight=NEURO_KEY_CHANNELS, mode_label="Neuro-monitoring"):
        return                    # liaison + voies clés (Fz/Pz) ; casque KO ou ESC -> retour
    print(f"[neuro] fenêtre PSD {NEURO_WINDOW_S}s  maj {NEURO_UPDATE_HZ:.0f}Hz  "
          f"warm-up {NEURO_WARMUP_S:.0f}s + repos {NEURO_BASELINE_S:.0f}s  (passif — aucun envoi robot)")
    decoder = NeuroDecoder(app.acq.fs)
    if not _neuro_baseline(app, decoder, NEURO_BASELINE_S):
        if app.smoke:             # pas de vraies données en headless -> normaliseur neutre
            decoder.norm = IndexNormalizer.identity([k for k, *_ in _NEURO_VIEW])
        else:
            app.flash("Repos trop court",
                      "pas assez de fenêtres pour caler les échelles — réessaie", 3.0)
            return
    _neuro_live(app, decoder)


# --- Mode 5 : ErrP — démonstrateur autonome (potentiel d'erreur) -------------
# DÉMONSTRATEUR PASSIF (aucun envoi robot). Tâche orientée-BUT curseur-vers-cible (Ferrez & Millán
# 2008) : un point doit rejoindre une cible (pastille verte) ; ~ERRP_DEMO_ERROR_RATE des pas partent
# DANS LE MAUVAIS SENS = erreur RESSENTIE. Chaque pas est épocher en MONO-ESSAI et passé au décodeur
# ErrP (xDAWN+Riemann, seuil asymétrique) : l'écran n'affiche QUE les détections + compare à la
# VÉRITÉ-TERRAIN (le pas éloigne-t-il de la cible ?) et tient un tableau TPR/TNR. But : MONTRER que le
# casque distingue la réaction cérébrale à une erreur — pas piloter. Réutilise les primitives de la
# calibration (_new_goal/_decide_step/_step/_track_hold). En direct : 'P' pause, 'T' règle le seuil.

_ERRP_DEMO_INTRO = [
    "Démonstrateur ErrP — ta réaction cérébrale à l'erreur",
    "",
    "• Un POINT lumineux doit rejoindre la CIBLE (pastille verte). À chaque pas il avance",
    "  d'une case, le plus souvent vers la cible — mais ~1 fois sur 3 il part À L'ENVERS.",
    "• À chaque pas ton cerveau est lu EN DIRECT (un seul essai) : l'écran signale quand ta",
    "  réaction d'erreur est détectée, et la compare à la vérité.",
    "• Tu n'as RIEN à faire : SUIS le point et VEUX qu'il atteigne la cible. Reste immobile,",
    "  cligne le moins possible au moment PRÉCIS où le point bouge.",
    "",
    "Une touche pour commencer  ·  en cours : Espace = pause, T = régler le seuil  ·  ESC = menu.",
]


def _errp_intro(app):
    """Écran d'accueil du démonstrateur (une touche = lancer ; ESC -> Abort -> menu)."""
    while True:
        pressed = []
        app.drain(on_key=lambda e: pressed.append(True))
        if pressed:
            return True
        app.win.fill(BG)
        h = app.size[1]
        y = int(h * 0.16)
        for i, line in enumerate(_ERRP_DEMO_INTRO):
            f = app.big if i == 0 else app.small
            col = GO if line.startswith("Une touche") else FG
            app.center(f, line, col, y)
            y += int(h * 0.085) if i == 0 else int(h * 0.05)
        app.pygame.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return True


def _errp_epoch(app, onset, fs):
    """Récupère le flux BRUT depuis l'onset du feedback et découpe l'époque mono-essai (ou None si
    l'époque déborde encore du buffer). Même alignement timestampé que le P300 (robuste à la dérive)."""
    from core.p300_decoder import epoch_from_stream
    eeg, ts = app.acq.get_raw(time.time() - onset + ERRP_PRE_S + 0.5)
    if eeg is None:
        return None
    return epoch_from_stream(eeg, ts, onset, fs, pre_s=ERRP_PRE_S, post_s=ERRP_EPOCH_S)


def _errp_scoreboard(tally):
    """(TPR, TNR, n_total) depuis les compteurs {tp, fp, tn, fn}. TPR = part des ERREURS détectées,
    TNR = part des BONNES commandes laissées passer — mêmes métriques honnêtes que la calibration
    (l'accuracy brute serait trompeuse). None tant qu'une classe n'a pas encore d'essai."""
    tp, fp, tn, fn = tally["tp"], tally["fp"], tally["tn"], tally["fn"]
    n_err, n_ok = tp + fn, tn + fp
    tpr = tp / n_err if n_err else None
    tnr = tn / n_ok if n_ok else None
    return tpr, tnr, tp + fp + tn + fn


def mode_errp(app, model_path=ERRP_MODEL_PATH):
    """Mode 5 : démonstrateur ErrP AUTONOME (aucun envoi robot).

    Tâche orientée-BUT curseur-vers-cible (Ferrez & Millán 2008) : un point doit rejoindre l'étoile ;
    ~ERRP_DEMO_ERROR_RATE des pas partent DANS LE MAUVAIS SENS -> vraie erreur RESSENTIE (violation
    d'attente + enjeu), bien plus saillante qu'une étiquette imposée. Chaque pas est lu en MONO-ESSAI :
    on annonce si la réaction d'erreur a été détectée + on compare à la vérité-terrain (le pas
    éloigne-t-il de la cible ?) + tableau TPR/TNR. Nécessite un modèle calibré."""
    import random as _random

    from research.errp_calibrate import _decide_step, _new_goal, _step, _track_hold, adjust_threshold
    from research.errp_decoder import ERROR, ErrPModel

    if not os.path.exists(model_path):
        app.flash("Pas de modèle ErrP",
                  "lance d'abord « ErrP -> Calibrer » (~4-5 min)", 3.5)
        return
    if not app.signal_check(highlight=ERRP_MIDLINE, mode_label="ErrP"):
        return                    # liaison + voies clés (Fz/Cz/Pz) ; casque KO ou ESC -> retour
    model = ErrPModel.load(model_path)
    n_cells = ERRP_TRACK_CELLS
    fs = app.acq.fs
    rng = _random.Random(0) if app.smoke else _random.Random()
    auc = "?" if model.cv_auc_ is None else f"{model.cv_auc_ * 100:.0f}%"
    print(f"[errp] démonstrateur curseur-vers-cible — AUC calib={auc}  seuil={model.threshold_:+.2f}  "
          f"erreurs≈{ERRP_DEMO_ERROR_RATE:.0%}  (PASSIF — aucun envoi robot)")
    if not app.smoke and not _errp_intro(app):
        return

    def pct(x):
        return "—" if x is None else f"{x * 100:.0f}%"

    # 'T' (hotkey des _track_hold) ouvre le réglage manuel du seuil EN DIRECT ; 'P' met en pause
    hk = {"t": lambda: adjust_threshold(app, model, save_path=model_path)}

    tally = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    start = n_cells // 2
    pos, goal, steps, trial = start, _new_goal(rng, n_cells), 0, 0
    _track_hold(app, n_cells, pos, goal, 1.0, title="Démonstrateur ErrP", hotkeys=hk,
                note="nouvelle cible — le point doit la rejoindre", note_col=DIM)
    try:
        while True:
            force = True if app.smoke else None      # smoke : forcer une erreur (exercer le scoring)
            new_pos, label = _decide_step(rng, pos, goal, n_cells, ERRP_DEMO_ERROR_RATE, force=force)
            onset = _step(app, n_cells, new_pos, goal, ERRP_FEEDBACK_S, title="Démonstrateur ErrP")
            pos, steps = new_pos, steps + 1
            if app.smoke:
                time.sleep(ERRP_EPOCH_S + 0.25)      # headless : laisser le board accumuler
            else:
                _track_hold(app, n_cells, pos, goal, ERRP_EPOCH_S + 0.2, title="Démonstrateur ErrP",
                            hotkeys=hk)
            ep = _errp_epoch(app, onset, fs)
            if ep is not None:
                score = float(np.ravel(model.score(ep))[0])
                detected = score >= model.threshold_
                was_error = label == ERROR
                key = ("tp" if detected else "fn") if was_error else ("fp" if detected else "tn")
                tally[key] += 1
                trial += 1
                tpr, tnr, ntot = _errp_scoreboard(tally)
                print(f"[errp] pas {trial} : {'ÉLOIGNÉ(erreur)' if was_error else 'rapproché(correct)'}  "
                      f"score={score:+.2f}/seuil{model.threshold_:+.2f}  "
                      f"détecté={'oui' if detected else 'non'}  {'OK' if was_error == detected else 'RATÉ'}")
                if detected:            # n'afficher QUE les détections (demande utilisateur) ; une
                    # non-détection laisse le point poursuivre sans interrompre le flux
                    sub = ("le point s'était ÉLOIGNÉ de la cible — bien vu" if was_error
                           else "le point s'était rapproché — fausse alerte")
                    _track_hold(app, n_cells, pos, goal, 2.4, title="Démonstrateur ErrP", hotkeys=hk,
                                note="réaction d'erreur DÉTECTÉE", note_col=ACCENT, sub=sub,
                                scoreboard=f"score {score:+.2f}/{model.threshold_:+.2f}   ·   "
                                           f"détectées {pct(tpr)}   ·   gardées {pct(tnr)}   ·   "
                                           f"{ntot} pas   ·   touche = passer", skip=True)
            elif app.smoke:
                return                               # époque perdue en headless -> on arrête là
            if pos == goal or steps >= ERRP_MAX_RUN_STEPS:
                _track_hold(app, n_cells, pos, goal, 1.0, title="Démonstrateur ErrP", hotkeys=hk,
                            note="cible atteinte" if pos == goal else "on recommence",
                            note_col=GO if pos == goal else DIM)
                pos, goal, steps = start, _new_goal(rng, n_cells), 0
                _track_hold(app, n_cells, pos, goal, 0.9, title="Démonstrateur ErrP", hotkeys=hk,
                            note="nouvelle cible", note_col=DIM)
            if app.smoke:
                return
    except Abort:
        tpr, tnr, ntot = _errp_scoreboard(tally)
        print(f"[errp] fin démonstrateur : {ntot} pas  "
              f"TPR={'—' if tpr is None else f'{tpr * 100:.0f}%'}  "
              f"TNR={'—' if tnr is None else f'{tnr * 100:.0f}%'}")
        return


# --- Calibrations ----------------------------------------------------------

def calib_cvep(app):
    import research.cvep_calibrate as cvep_calibrate
    try:
        cvep_calibrate.calibrate(app)
    except Abort:
        pass


def calib_cvep_rcca(app):
    import research.cvep_rcca as cvep_rcca
    try:
        cvep_rcca.calibrate_rcca(app)
    except Abort:
        pass


def calib_p300(app):
    import research.p300_calibrate as p300_calibrate
    try:
        p300_calibrate.calibrate(app)
    except Abort:
        pass


def calib_errp(app):
    import research.errp_calibrate as errp_calibrate
    try:
        errp_calibrate.calibrate(app)
    except Abort:
        pass


# --- Navigation (menus aux FLÈCHES + SOURIS, retour ←/Échap) ----------------

def _status(app):
    cv = "oui" if os.path.exists(CVEP_MODEL_PATH) else "absent"
    p3 = "oui" if os.path.exists(P300_MODEL_PATH) else "absent"
    casque = "board SYNTHÉTIQUE" if app.synthetic else "Unicorn"
    robot = f"ON -> {app.host}" if app.send else "OFF (aucun envoi)"
    return [f"casque : {casque}    écran : {app.refresh:.0f} Hz",
            f"modèles — c-VEP : {cv}    P300 : {p3}",
            f"envoi robot : {robot}"]


def _toggle_robot(app):
    app.send = not app.send
    if not app.send:
        app.emit(0.0, 0.0)


def _check_signal(app):
    """Contrôle de la liaison casque (hotkey C de l'accueil). Échap y lève Abort : on l'absorbe
    pour revenir à l'accueil au lieu de quitter l'appli."""
    try:
        app.signal_check()
    except Abort:
        pass


def _navigate(app, title, options, subtitle=None, allow_back=True,
              status_fn=None, hotkeys=None):
    """Menu vertical, navigable au CLAVIER (↑↓ + Entrée/→) ET à la SOURIS (survol = surligne,
    clic = valide ; clic sur « ⟵ Retour » = reculer). Retourne l'index choisi, ou None pour
    reculer (←/Échap/clic Retour) — sur l'accueil (allow_back=False), None = quitter.

    `options` : liste de (label, description). `status_fn` : callable -> lignes d'état affichées
    sous le titre (recalculées chaque frame). `hotkeys` : {char: fn(app)} exécuté sans quitter
    (R robot, C liaison). La souris est VISIBLE dans les menus et RECACHÉE à la sortie : un
    curseur ne doit pas rester sur les cibles pendant un stimulus.
    """
    pg = app.pygame
    pg.mouse.set_visible(True)
    sel = 0
    w, h = app.size
    many = len(options) > 4          # >4 modes : on resserre pour ne pas mordre sur le bas d'écran
    oy0 = int(h * (0.36 if many else 0.42))
    ody = int(h * (0.105 if many else 0.12))
    back_y = int(h * 0.85)

    def option_at(pos):
        if abs(pos[0] - w / 2) > w * 0.42:
            return None
        for i in range(len(options)):
            if abs(pos[1] - (oy0 + i * ody)) <= ody * 0.5:
                return i
        return None

    def on_back(pos):
        return (allow_back and abs(pos[1] - back_y) <= int(h * 0.03)
                and abs(pos[0] - w / 2) <= w * 0.25)

    def leave(v):
        pg.mouse.set_visible(False)
        return v

    while True:
        for e in pg.event.get():
            if e.type == pg.QUIT:
                return leave(None)
            if e.type == pg.KEYDOWN:
                if e.key == pg.K_ESCAPE:
                    return leave(None)
                if allow_back and e.key in (pg.K_LEFT, pg.K_BACKSPACE):
                    return leave(None)
                if e.key in (pg.K_UP, pg.K_w):
                    sel = (sel - 1) % len(options)
                elif e.key in (pg.K_DOWN, pg.K_s):
                    sel = (sel + 1) % len(options)
                elif e.key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE, pg.K_RIGHT):
                    return leave(sel)
                elif hotkeys and e.unicode and e.unicode.lower() in hotkeys:
                    hotkeys[e.unicode.lower()](app)
            elif e.type == pg.MOUSEMOTION:
                i = option_at(e.pos)
                if i is not None:
                    sel = i
            elif e.type == pg.MOUSEBUTTONDOWN and e.button == 1:
                i = option_at(e.pos)
                if i is not None:
                    return leave(i)
                if on_back(e.pos):
                    return leave(None)

        app.win.fill(BG)
        app.center(app.big, title, FG, int(h * 0.12))
        yy = int(h * 0.20)
        if subtitle:
            app.center(app.small, subtitle, DIM, yy)
            yy += int(h * 0.04)
        if status_fn:
            for line in status_fn():
                app.center(app.small, line, WARN if "ON ->" in line else DIM, yy)
                yy += int(h * 0.035)
        for i, (label, desc) in enumerate(options):
            act = i == sel
            cy = oy0 + i * ody
            app.center(app.mid, f"{'>  ' if act else '    '}{label}", ACCENT if act else FG, cy)
            app.center(app.small, desc, DIM, cy + int(h * 0.036))
        if allow_back:
            app.center(app.mid, "<-  Retour", ACCENT, back_y)
            app.center(app.small, "<-  ou  Échap", DIM, back_y + int(h * 0.035))
            app.center(app.small, "Flèches / souris : naviguer       Entrée / clic : valider",
                       DIM, int(h * 0.93))
        else:
            app.center(app.small, "[R] armer/désarmer robot        [C] vérifier la liaison casque",
                       DIM, int(h * 0.87))
            app.center(app.small,
                       "Flèches / souris : naviguer    ·    Entrée / clic : valider    ·    Échap : quitter",
                       ACCENT, int(h * 0.93))
        pg.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return leave(None)


def _mode_page(app, title, live_fn, calib_fn=None, live_desc="", calib_desc=""):
    """Page d'un mode : « Lancer le live » et (si dispo) « Calibrer ». Boucle jusqu'au retour
    (←/Échap) ; après un live ou une calibration, on revient sur cette page."""
    while True:
        options = [("Lancer le live", live_desc or "démarre le décodage en direct")]
        if calib_fn is not None:
            options.append(("Calibrer", calib_desc or "enregistre puis entraîne le modèle"))
        sub = None if calib_fn else "Ce mode ne nécessite aucune calibration"
        idx = _navigate(app, title, options, subtitle=sub)
        if idx is None:
            return
        try:                       # Échap dans le contrôle de liaison (Abort) -> revient ICI
            if idx == 0:
                live_fn(app)
            elif idx == 1 and calib_fn is not None:
                calib_fn(app)
        except Abort:
            pass
        if app.smoke:
            return


def page_cvep(app):
    """c-VEP : d'abord le choix de variante (eCCA / rCCA), puis la page du mode choisi."""
    while True:
        v = _navigate(app, "c-VEP — quelle variante ?",
                      [("classique (eCCA, 1 m-séquence décalée)", "mode validé, template partagé"),
                       ("rCCA + codes distincts (Gold)",
                        "exploration : reconvolution, 1 code par cible")])
        if v is None:
            return
        if v == 0:
            _mode_page(app, "c-VEP classique (eCCA)", mode_cvep, calib_cvep,
                       "fixe une cible, décodage par template appris",
                       "~1 min, fixer chaque cible (blocs entrelacés)")
        else:
            _mode_page(app, "c-VEP rCCA + codes distincts", mode_cvep_rcca, calib_cvep_rcca,
                       "codes Gold distincts, décodage par reconvolution",
                       "reconvolution, un code Gold par cible")
        if app.smoke:
            return


def page_p300(app):
    """Page P300 : case à cocher « arrêt dynamique » (on peut comparer avec/sans) + Lancer / Calibrer.
    La case se coche/décoche en la validant (Entrée ou clic) ; on reste sur la page."""
    dyn = [False]
    while True:
        cb = f"[{'x' if dyn[0] else ' '}]  Arrêt dynamique (plus rapide, expérimental)"
        opts = [(cb, "s'arrête dès que la cible est sûre — vise ~3 s au lieu de ~7"),
                ("Lancer le live", "sélection en rafales (modèle requis)"),
                ("Calibrer", "fixer et compter la cible cerclée, ~4-5 min")]
        idx = _navigate(app, "P300", opts,
                        subtitle="arrêt dynamique = "
                                 + ("ACTIVÉ" if dyn[0] else "désactivé (répétitions fixes)"))
        if idx is None:
            return
        if idx == 0:
            dyn[0] = not dyn[0]                 # bascule la case, reste sur la page
        elif idx == 1:
            try:
                mode_p300(app, dynamic=dyn[0])
            except Abort:
                pass
        elif idx == 2:
            try:
                calib_p300(app)
            except Abort:
                pass
        if app.smoke:
            return


def page_errp(app):
    """Page ErrP : Lancer le démonstrateur / Régler le seuil (TPR/TNR) / Calibrer. Le réglage et le
    live nécessitent un modèle calibré ; le réglage sur la page sauve le seuil sur disque."""
    from research.errp_calibrate import adjust_threshold
    from research.errp_decoder import ErrPModel

    while True:
        opts = [("Lancer le démonstrateur", "la machine se trompe, ton cerveau est lu en direct"),
                ("Régler le seuil (TPR / TNR)", "ajuste le compromis détection / fausses alertes"),
                ("Calibrer", "~4-5 min : guide le point vers la cible, on entraîne le décodeur")]
        idx = _navigate(app, "ErrP (démonstrateur)", opts,
                        subtitle="réglage du seuil possible aussi EN DIRECT (touche T) pendant le live")
        if idx is None:
            return
        try:
            if idx == 0:
                mode_errp(app)
            elif idx == 1:
                if os.path.exists(ERRP_MODEL_PATH):
                    adjust_threshold(app, ErrPModel.load(ERRP_MODEL_PATH), save_path=ERRP_MODEL_PATH)
                else:
                    app.flash("Pas de modèle ErrP", "calibre d'abord (ErrP -> Calibrer)", 3.0)
            elif idx == 2:
                calib_errp(app)
        except Abort:
            pass
        if app.smoke:
            return


def home(app):
    """Accueil : les 5 modes. Retourne 'ssvep'|'cvep'|'p300'|'neuro'|'errp', ou None pour quitter."""
    modes = [("SSVEP", "flèches clignotantes — sans calibration, marche tout de suite"),
             ("c-VEP", "codes — 2 variantes : classique (eCCA) ou rCCA + codes distincts"),
             ("P300", "oddball — fixe et compte la cible (6 cibles) — nécessite une calibration"),
             ("Neuro-monitoring", "état mental passif (charge / somnolence / engagement) — histogramme, aucun robot"),
             ("ErrP", "la machine se trompe exprès, ton cerveau réagit — démonstrateur, aucun robot")]
    idx = _navigate(app, "EEG_API_Unicorn — choisis un mode", modes, allow_back=False,
                    status_fn=lambda: _status(app),
                    hotkeys={"r": _toggle_robot, "c": _check_signal})
    return None if idx is None else ("ssvep", "cvep", "p300", "neuro", "errp")[idx]


PAGES = {
    "ssvep": lambda app: _mode_page(app, "SSVEP", mode_ssvep, None,
                                    "choix des fréquences, puis run en direct"),
    "cvep": page_cvep,
    "p300": page_p300,
    "neuro": lambda app: _mode_page(app, "Neuro-monitoring passif", mode_neuro, None,
                                    "3 indices spectraux en histogramme (aucun envoi robot)"),
    "errp": page_errp,
}


def main(windowed=False, synthetic=False, send=False, smoke=False, host=UDP_HOST):
    app = App(windowed=windowed, synthetic=synthetic, smoke=smoke, send=send, host=host)
    print(f"[app] écran {app.refresh:.0f} Hz  casque={'synthétique' if app.synthetic else 'Unicorn'}"
          f"  robot={'ARMÉ -> ' + host if send else 'désarmé'}")
    if send:
        print("[app] ⚠️  envoi UDP armé : roues en l'air pour les premiers essais.")
    try:
        if smoke:   # exerce les modes + la navigation sans interaction
            _smoke(app)
        else:
            while True:
                choice = home(app)         # accueil : Échap = quitter
                if choice is None:
                    break
                try:
                    PAGES[choice](app)     # page du mode ; ←/Échap = retour à l'accueil
                except Abort:
                    pass                   # filet : un mode ne doit pas laisser fuir Abort
    finally:
        app.close()
    return True


def _smoke(app):
    """Câblage de bout en bout, headless : menu + calibrations + les modes de pilotage (c-VEP, P300).
    Les modèles sont écrits à part (suffixe _smoke) pour ne JAMAIS écraser une vraie calibration."""
    import research.cvep_calibrate as cvep_calibrate

    tmp = os.path.dirname(CVEP_MODEL_PATH)
    cvep_path = os.path.join(tmp, "cvep_model_smoke.npz")

    import research.cvep_rcca as cvep_rcca
    import research.errp_calibrate as errp_calibrate
    import research.p300_calibrate as p300_calibrate
    rcca_path = os.path.join(tmp, "cvep_rcca_model_smoke.npz")
    p300_path = os.path.join(tmp, "p300_model_smoke.joblib")
    errp_path = os.path.join(tmp, "errp_model_smoke.joblib")

    home(app)                 # accueil (rend + retour immédiat en smoke)
    _mode_page(app, "SSVEP", mode_ssvep, None)    # rend une page de mode (retour immédiat)
    page_cvep(app)            # rend l'écran de choix de variante c-VEP
    page_p300(app)            # rend la page P300 (case arrêt dynamique)
    page_errp(app)            # rend la page ErrP (démonstrateur / réglage seuil / calibrer)
    mode_neuro(app)           # mode 4 : neuro-monitoring passif (baseline + histogramme headless)
    mode_ssvep(app)
    cvep_calibrate.calibrate(app, save_path=cvep_path)
    mode_cvep(app, model_path=cvep_path)
    cvep_rcca.calibrate_rcca(app, save_path=rcca_path)
    mode_cvep_rcca(app, model_path=rcca_path)
    p300_calibrate.calibrate(app, save_path=p300_path)
    mode_p300(app, model_path=p300_path)                       # chemin fixe
    mode_p300(app, model_path=p300_path, dynamic=True)         # chemin arrêt dynamique
    errp_calibrate.calibrate(app, save_path=errp_path)         # ErrP : calibration (décodeur, sans robot)
    mode_errp(app, model_path=errp_path)                       # ErrP : démonstrateur solo (détection live)
    for p in (cvep_path, rcca_path, p300_path, errp_path):
        if os.path.exists(p):
            os.remove(p)
    print("[app] smoke OK : menu + SSVEP + c-VEP (eCCA & rCCA) + P300 + neuro + ErrP(cal+démo) câblés (headless).")


def _parse(argv):
    p = argparse.ArgumentParser(description="Application EEG_API_Unicorn (SSVEP / c-VEP / P300 / neuro / ErrP).")
    p.add_argument("--windowed", action="store_true", help="fenêtre au lieu du plein écran")
    p.add_argument("--send", action="store_true", help="armer l'envoi UDP dès le lancement")
    p.add_argument("--synthetic", action="store_true", help="board de test (sans casque)")
    p.add_argument("--host", default=UDP_HOST, help="hôte de l'actionneur UDP (exemple de sortie applicative)")
    p.add_argument("--smoke", action="store_true", help="test headless (CI)")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    a = _parse(sys.argv[1:])
    main(windowed=a.windowed, synthetic=a.synthetic, send=a.send, smoke=a.smoke, host=a.host)
