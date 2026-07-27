"""Calibration P300 : fixer+compter une cible cuée pendant que les cibles clignotent une à une.

Déroulé d'une MANCHE : une cible est cerclée (la « cible attendue »). Tu la fixes et tu COMPTES
ses flashs. On fait clignoter les N cibles chacune leur tour, en ordre mélangé, `reps` fois. Le
flash de la cible attendue est rare (1/N) et compté -> il évoque un P300 ; les autres non. On
enregistre chaque flash comme une époque étiquetée « cible / non-cible » (via le timestamp du
flux, cf. p300_decoder.epoch_from_stream). On change de cible attendue à chaque manche.

Ensuite : xDAWN + Riemann appris sur cible-vs-non-cible (voir p300_decoder). Deux chiffres de
contrôle : l'AUC cible/non-cible (GroupKFold par manche) et surtout la PRÉCISION DE SÉLECTION en
leave-one-round-out — retrouve-t-on la cible attendue ? — d'où découle l'ITR.

Compter les flashs n'est pas un gadget : la tâche mentale (« combien de fois ? ») est ce qui rend
le stimulus attendu SAILLANT et amplifie le P300. Sans tâche, l'onde s'effondre.
"""

import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (P300_CAL_ROUNDS, P300_EPOCH_S, P300_FLASH_OFF_FR,  # noqa: E402
                    P300_FLASH_ON_FR, P300_MIDLINE, P300_MODEL_PATH, P300_PRE_S, P300_REPS,
                    p300_targets)
from research.itr import itr  # noqa: E402
from research.p300_decoder import NONTARGET, TARGET, P300Model, epoch_from_stream  # noqa: E402
from research.ui import ACCENT, BG, DIM, FG, GO, WARN, Abort  # noqa: E402

BRIEF = [
    "Calibration P300",
    "",
    "• Une cible est CERCLÉE (bleu) : c'est celle que tu dois fixer.",
    "• Les cibles s'allument une à une, en bref éclair, dans le désordre.",
    "• FIXE la cible cerclée et COMPTE mentalement ses éclairs (c'est la tâche : elle crée le P300).",
    "• Reste immobile, cligne le moins possible pendant les flashs.",
    "• À chaque manche, la cible à fixer change. Durée totale affichée dans la console.",
    "",
    "Appuie sur une touche pour commencer (ESC pour annuler).",
]


def _briefing(app):
    while True:
        pressed = []
        app.drain(on_key=lambda e: pressed.append(True))
        if pressed:
            return True
        app.win.fill(BG)
        h = app.win.get_height()
        y = int(h * 0.15)
        for i, line in enumerate(BRIEF):
            f = app.big if i == 0 else app.small
            col = FG if i == 0 else (GO if line.startswith("Appuie") else FG)
            app.center(f, line, col, y)
            y += int(h * 0.085) if i == 0 else int(h * 0.055)
        app.pygame.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return True


def _intro(app, plan, spots, cue_name, r, rounds, seconds=2.5):
    """Écran « fixe et compte X » avant les flashs de la manche (cible cerclée, rien ne clignote).
    Point de PAUSE sûr : les époques de la manche précédente sont déjà ramassées, aucun stimulus
    ne tourne encore -> ESPACE met en pause ici (entre manches)."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        app.drain(pausable=True)                 # ESPACE = pause (sûr entre deux manches)
        app.win.fill(BG)
        h = app.size[1]
        app.center(app.big, f"Manche {r + 1}/{rounds}", FG, int(h * 0.10))
        app.center(app.mid, f"FIXE et COMPTE les éclairs de : {cue_name}", GO, int(h * 0.17))
        app.draw_ring(plan, spots, lambda c, f: False, 0, cue=cue_name)
        app.center(app.small, "Espace = pause (entre les manches)", DIM, int(h * 0.92))
        app.pygame.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return


def _blank_ring(app, plan, spots, cue_name, frames):
    """Rend l'anneau ÉTEINT pendant `frames` (settle / gap), ESC actif."""
    for _ in range(frames):
        app.drain()
        app.win.fill(BG)
        app.draw_ring(plan, spots, lambda c, f: False, 0, cue=cue_name)
        app.pygame.display.flip()
        app.clock.tick(int(app.refresh) + 5)
        if app.smoke:
            return


def _flash_targets(app, plan, spots, cue_name, order, on_fr, off_fr):
    """UNE répétition P300 : flashe une fois chaque cible de `order` (indices dans plan), avec un
    gap éteint entre chaque. Retourne [(target_index, onset_unix_ts)] (onset horodaté à la 1re
    frame allumée). ESC actif. Réutilisé par la calibration ET par le live (fixe ou dynamique)."""
    flashes = []
    for t in order:
        lit = plan[t]["name"]
        for f in range(on_fr):                  # phase ALLUMÉE (la cible t)
            app.drain()
            app.win.fill(BG)
            app.draw_ring(plan, spots, lambda c, fr, L=lit: c["name"] == L, 0, cue=cue_name)
            app.pygame.display.flip()
            if f == 0:
                flashes.append((t, time.time()))
            app.clock.tick(int(app.refresh) + 5)
            if app.smoke:
                break
        for _ in range(off_fr):                 # phase ÉTEINTE (gap avant le flash suivant)
            app.drain()
            app.win.fill(BG)
            app.draw_ring(plan, spots, lambda c, fr: False, 0, cue=cue_name)
            app.pygame.display.flip()
            app.clock.tick(int(app.refresh) + 5)
            if app.smoke:
                break
    return flashes


def _run_round(app, plan, spots, cue_name, reps, on_fr, off_fr, rng):
    """Une manche de calibration = `reps` répétitions, chacune = les N cibles flashées une fois
    dans un ordre mélangé. Retourne (flashes, t_start)."""
    n = len(plan)
    t_start = time.time()
    flashes = []
    for _ in range(1 if app.smoke else reps):   # headless : 1 rép (6 flashs) suffit au câblage
        order = list(range(n))
        rng.shuffle(order)
        flashes += _flash_targets(app, plan, spots, cue_name, order, on_fr, off_fr)
    return flashes, t_start


def _collect(app, plan, spots, cue_name, flashes, t_start, cue_idx, fs,
             epochs, labels, flashed, groups, r):
    """Laisse le dernier post-stimulus se remplir, récupère le flux de la manche, découpe et
    étiquette chaque époque. Ajoute in-place aux listes fournies."""
    settle_fr = int(round((P300_EPOCH_S + 0.15) * app.refresh))
    _blank_ring(app, plan, spots, cue_name, settle_fr)
    if app.smoke:
        time.sleep(P300_EPOCH_S + 0.3)   # headless : le rendu est instantané -> laisse le board
        #                                  synthétique accumuler le post-stimulus, sinon 0 époque
    eeg, ts = app.acq.get_raw(time.time() - t_start + P300_PRE_S + 0.5)
    if eeg is None:
        return 0
    added = 0
    for t, onset in flashes:
        ep = epoch_from_stream(eeg, ts, onset, fs)
        if ep is None:
            continue
        epochs.append(ep)
        labels.append(TARGET if t == cue_idx else NONTARGET)
        flashed.append(t)
        groups.append(r)
        added += 1
    return added


def _loro_selection(epochs, flashed, groups, cues, fs):
    """Précision de SÉLECTION en leave-one-round-out : pour chaque manche tenue à l'écart, le
    modèle appris sur les autres retrouve-t-il la cible attendue ? Renvoie (ok, total)."""
    epochs, flashed, groups = np.asarray(epochs), np.asarray(flashed), np.asarray(groups)
    y = np.array([TARGET if flashed[i] == cues[groups[i]] else NONTARGET
                  for i in range(len(groups))])
    ok = tot = 0
    for r in sorted(set(groups.tolist())):
        tr = groups != r
        if len(set(y[tr].tolist())) < 2:
            continue
        m = P300Model(fs=fs).fit(epochs[tr], y[tr], compute_cv=False)
        te = np.where(groups == r)[0]
        by = {}
        for i in te:
            by.setdefault(int(flashed[i]), []).append(epochs[i])
        pick, _ = m.select(by)
        ok += int(pick == cues[r])
        tot += 1
    return ok, tot


def _results(app, auc, sel_ok, sel_tot, t_sel, n_targets):
    """Écran de résultat (6 s ou une touche)."""
    sel = sel_ok / sel_tot if sel_tot else 0.0
    itr_val = itr(n_targets, sel, t_sel) if sel_tot else 0.0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 6.0:
        pressed = []
        app.drain(on_key=lambda e: pressed.append(True))
        if pressed:
            return
        app.win.fill(BG)
        h = app.size[1]
        app.center(app.big, "Calibration P300 terminée", FG, int(h * 0.20))
        auc_txt = "—" if auc is None else f"{auc * 100:.1f}%"
        app.center(app.mid, f"AUC cible/non-cible (par manche) : {auc_txt}", DIM, int(h * 0.36))
        col = GO if sel >= 0.6 else WARN
        app.center(app.mid, f"Sélection retrouvée : {sel_ok}/{sel_tot} = {sel * 100:.0f}%  "
                            f"(hasard {100 / n_targets:.0f}%)", col, int(h * 0.46))
        app.center(app.mid, f"ITR ~ {itr_val:.1f} bits/min  ({t_sel:.1f} s/sélection)",
                   DIM, int(h * 0.56))
        app.center(app.small, "une touche pour revenir au menu", DIM, int(h * 0.8))
        app.pygame.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return


def _archive(save_path, epochs, labels, flashed, groups, cues, fs):
    """Sauvegarde le modèle + un .npz horodaté des époques brutes (pour ré-analyse hors ligne)."""
    data_dir = os.path.dirname(save_path)
    os.makedirs(data_dir, exist_ok=True)
    last = os.path.join(data_dir, "p300_calib_last.npz")
    np.savez(last, epochs=np.asarray(epochs), labels=np.asarray(labels),
             flashed=np.asarray(flashed), groups=np.asarray(groups),
             cues=np.asarray(cues), fs=fs, pre_s=P300_PRE_S, post_s=P300_EPOCH_S)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    np.savez(os.path.join(data_dir, f"p300_calib_{stamp}_n{len(cues)}.npz"),
             epochs=np.asarray(epochs), labels=np.asarray(labels),
             flashed=np.asarray(flashed), groups=np.asarray(groups),
             cues=np.asarray(cues), fs=fs, pre_s=P300_PRE_S, post_s=P300_EPOCH_S)
    return last


def calibrate(app, rounds=P300_CAL_ROUNDS, reps=P300_REPS, save_path=None):
    """Calibration complète. En smoke : 2 manches × quelques flashs, fit léger, sauvegarde
    dans save_path (le _smoke de app.py passe un chemin _smoke). Retourne True si un modèle a
    été entraîné et sauvegardé."""
    save_path = save_path or P300_MODEL_PATH
    plan = p300_targets()
    n = len(plan)
    on_fr, off_fr = P300_FLASH_ON_FR, P300_FLASH_OFF_FR

    # câble/électrodes AVANT d'enregistrer (piège #0) ; voies clés P300 (Fz/Cz/Pz) encadrées
    if not app.smoke and not app.signal_check(highlight=P300_MIDLINE, mode_label="P300"):
        return False
    if not _briefing(app):
        return False

    spots = app.ring_spots(plan)
    rng = random.Random() if not app.smoke else random.Random(0)
    eff_rounds = 2 if app.smoke else rounds
    eff_reps = 1 if app.smoke else reps
    soa_s = (on_fr + off_fr) / app.refresh
    print(f"[p300-cal] {eff_rounds} manches × {n} cibles × {eff_reps} rép  "
          f"SOA={soa_s * 1000:.0f} ms  ~{eff_rounds * n * eff_reps * soa_s + eff_rounds * 3:.0f} s")

    epochs, labels, flashed, groups, cues = [], [], [], [], []
    fs = app.acq.fs
    for r in range(eff_rounds):
        cue_idx = r % n
        cue_name = plan[cue_idx]["name"]
        cues.append(cue_idx)
        _intro(app, plan, spots, cue_name, r, eff_rounds)
        fl, t_start = _run_round(app, plan, spots, cue_name, eff_reps, on_fr, off_fr, rng)
        added = _collect(app, plan, spots, cue_name, fl, t_start, cue_idx, fs,
                         epochs, labels, flashed, groups, r)
        print(f"[p300-cal] manche {r + 1}/{eff_rounds} cible={cue_name}  {added} époques")

    if len(epochs) < 2 * n or len(set(labels)) < 2:
        print("[p300-cal] pas assez de données (ou une seule classe) -> pas d'entraînement.")
        if not app.smoke:
            app.flash("Calibration insuffisante",
                      "trop peu d'époques — relance et vérifie la liaison casque", 3.5)
        return False

    if not app.smoke:   # fit + AUC + LORO enchaînent ~17 ré-entraînements : prévenir (écran figé)
        app.win.fill(BG)
        app.center(app.big, "Analyse...", FG, int(app.size[1] * 0.45))
        app.center(app.small, "entraînement du modèle et évaluation de la sélection", DIM,
                   int(app.size[1] * 0.55))
        app.pygame.display.flip()
    model = P300Model(fs=fs).fit(epochs, labels, groups=np.asarray(groups),
                                 compute_cv=not app.smoke)
    model.save(save_path)
    last = save_path if app.smoke else \
        _archive(save_path, epochs, labels, flashed, groups, cues, fs)   # pas d'archive en smoke

    sel_ok, sel_tot = (1, 1) if app.smoke else _loro_selection(epochs, flashed, groups, cues, fs)
    t_sel = eff_reps * n * soa_s
    auc = model.cv_auc_
    print(f"[p300-cal] AUC={'—' if auc is None else f'{auc*100:.1f}%'}  "
          f"sélection LORO={sel_ok}/{sel_tot}  modèle -> {os.path.basename(save_path)}  "
          f"époques -> {os.path.basename(last)}")
    if not app.smoke:
        _results(app, auc, sel_ok, sel_tot, t_sel, n)
    return True


if __name__ == "__main__":
    from core.config import use_utf8_console
    use_utf8_console()
    print("Ce module se lance depuis l'appli (touche de calibration P300). "
          "Test de câblage headless : python src/research/app.py --smoke")
