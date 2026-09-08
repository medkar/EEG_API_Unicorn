"""Pilotage SSVEP par flèches clignotantes (CCA) — l'écran de PILOTAGE retiré de l'appli unifiée.

Ce module vivait comme `mode_ssvep` dans `src/research/app.py`, supprimé le 2026-09-08. Le SSVEP est
maintenant DÉCODÉ par le MOTEUR (`python src/core/server.py --mode ssvep` -> flux `decoded_ssvep`)
et se pilote depuis la console — plus depuis pygame. Ce fichier reste ici, ENCORE EXÉCUTABLE, pour
la même raison que `cvep_pilot.py` : c'est la RÉFÉRENCE de décodage LOCAL contre laquelle une séance
casque compare le décodage réseau. Même signal, même CCA, deux chemins indépendants qui doivent
désigner la même flèche.

Le SSVEP ne demande AUCUNE calibration : il n'y a donc pas de `--model` ici, contrairement aux trois
autres écrans archivés. Ce qu'il a en propre, c'est le SÉLECTEUR DE FRÉQUENCES (une par direction,
parmi les diviseurs entiers du rafraîchissement) et la MESURE DE PLANCHER au repos — deux choses que
le moteur fait autrement (réglages de la console, `alpha_hz` et bouton « Proposer »).

⚠️ Ne jamais le lancer en même temps que le moteur, la console ou un autre écran archivé : le casque
n'accepte qu'UNE connexion.

    python archive/ssvep_pilot.py                      # plein écran, casque réel
    python archive/ssvep_pilot.py --windowed
    python archive/ssvep_pilot.py --synthetic          # sans casque (board de test BrainFlow)
    python archive/ssvep_pilot.py --smoke              # test headless (CI)
"""

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))      # -> src/
from core.config import (ALPHA_PEAK_HZ, ARTIFACT_SIGMA_RATIO, BANDPASS,  # noqa: E402
                    DATA_DIR, empreinte_dossier, N_HARMONICS, OCCIPITAL, RHO_MIN,
                    SSVEP_BASELINE_S, UDP_HOST, available_frequencies, choose_frequencies,
                    use_utf8_console)
from research.controller import SSVEPController  # noqa: E402
from research.ssvep_stimulus import is_on as ssvep_on  # noqa: E402
# La machinerie PARTAGÉE (Live, le fil de décodage/émission, le rendu) vivait dans `research/app.py`
# avec cet écran ; elle est dans `research/ui.py` depuis le 2026-09-08 — voir `archive/README.md`.
from research.ui import (ACCENT, BG, DIM, FG, GO, ON_COLOR, OUTLINE, WARN,  # noqa: E402
                         Abort, App, _live_loop, _running)


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
        if not app.smoke:      # un test ne consigne RIEN dans data/ (cf. la garde de `main`)
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


def _parse(argv):
    p = argparse.ArgumentParser(
        description="Pilotage SSVEP par CCA (ARCHIVÉ — référence de décodage local).")
    p.add_argument("--windowed", action="store_true", help="fenêtre au lieu du plein écran")
    p.add_argument("--send", action="store_true", help="armer l'envoi UDP dès le lancement")
    p.add_argument("--synthetic", action="store_true", help="board de test (sans casque)")
    p.add_argument("--host", default=UDP_HOST, help="hôte de l'actionneur UDP")
    p.add_argument("--smoke", action="store_true", help="test headless (CI)")
    return p.parse_args(argv)


def main(argv=None):
    a = _parse(sys.argv[1:] if argv is None else argv)
    app = App(windowed=a.windowed, synthetic=a.synthetic, smoke=a.smoke, send=a.send,
              host=a.host)
    # Même garde que les autres fichiers archivés : `data/` porte des enregistrements EEG d'une
    # personne identifiable sur un dépôt public, et cet écran-ci y ÉCRIT en usage réel
    # (`ssvep_baselines.csv`). Le smoke ne doit rien y laisser — vérifié, pas supposé.
    empreinte_avant = empreinte_dossier(DATA_DIR) if a.smoke else None
    try:
        mode_ssvep(app)
    except Abort:
        pass                       # ESC = sortie normale
    finally:
        app.close()
    if a.smoke:
        empreinte_apres = empreinte_dossier(DATA_DIR)
        assert empreinte_apres == empreinte_avant, (
            f"ce smoke a touché data/ — le plancher de repos ne doit être CONSIGNÉ qu'en séance "
            f"réelle (dossier gitignoré, mais qui porte des enregistrements EEG d'une personne "
            f"identifiable) : {set(empreinte_apres) ^ set(empreinte_avant) or 'contenu modifié'}")
        print("[ssvep-pilot] smoke OK : plancher + décodage + affichage câblés (headless).")
    return True


if __name__ == "__main__":
    use_utf8_console()
    main()
