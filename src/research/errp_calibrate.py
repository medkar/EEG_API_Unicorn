"""Calibration ErrP : élicite des potentiels d'erreur en faisant SE TROMPER la machine.

Déroulé d'un ESSAI : (1) on affiche l'INTENTION de l'utilisateur (« prépare : GAUCHE ») ; (2) court
gap avec point de fixation ; (3) FEEDBACK — la machine « exécute » une direction, affichée AU CENTRE
et HORODATÉE (onset). Dans ~ERRP_ERROR_RATE des essais la machine choisit DÉLIBÉRÉMENT une autre
direction que l'intention -> l'utilisateur perçoit une ERREUR -> ErrP. La vérité-terrain (chosen ==
intended ?) donne l'étiquette. On épocher chaque feedback [-ERRP_PRE_S, +ERRP_EPOCH_S] via le
timestamp BrainFlow (epoch_from_stream), exactement comme un flash P300.

Pourquoi ce protocole (revue littérature 2026-07-23) : l'ErrP naît du MISMATCH intention/résultat.
Le feedback est CENTRAL et TEXTUEL (position d'écran FIXE) pour ne pas confondre l'ErrP avec une
réponse visuelle qui dépendrait de la position de la cible — et c'est aussi le miroir de l'usage en
ligne (on affichera la commande décodée au centre, puis on l'annule si ErrP). ⚠️ onset = la FRAME
écran, JAMAIS le mouvement du robot (jitter UDP/ROS2 qui étalerait l'ErrP en mono-essai).

Sortie : `data/errp_model_AAAAMMJJ_HHMMSS.joblib` (ErrPModel : xDAWN+Riemann+LR, seuil asymétrique)
+ un .npz des époques brutes. Le nom est HORODATÉ, jamais fixe : `data/errp_model.joblib` est la
trace casque du 24 juillet, et une calibration ne doit rien écraser (cf. `chemin_modele_horodate`). Métriques honnêtes : AUC (GroupKFold par bloc) + TPR/TNR séparés (pas l'accuracy
brute, trompeuse sous déséquilibre). Se lance depuis l'appli (mode ErrP -> Calibrer) ou en smoke.
"""

import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (ERRP_CAL_BLOCKS, ERRP_CAL_TRIALS, ERRP_EPOCH_S,  # noqa: E402
                    ERRP_ERROR_RATE, ERRP_FEEDBACK_S, ERRP_MAX_RUN_STEPS, ERRP_MIDLINE,
                    ERRP_MODEL_PATH, ERRP_PRE_S, ERRP_TRACK_CELLS)
from core.p300_decoder import epoch_from_stream  # noqa: E402
from core.errp_decoder import CORRECT, ERROR, ErrPModel, rates  # noqa: E402
from research.ui import (ACCENT, BAR_BG, BG, DIM, FG, GO, ON_COLOR,  # noqa: E402,F401
                OUTLINE, WARN, Abort)

BRIEF = [
    "Calibration ErrP (potentiel d'erreur)",
    "",
    "• Un POINT lumineux doit rejoindre l'ÉTOILE ★ : c'est le BUT.",
    "• À chaque pas il avance d'une case — le plus souvent VERS l'étoile.",
    "• Parfois il part DANS LE MAUVAIS SENS (il s'éloigne) : c'est une ERREUR.",
    "• Tu n'as rien à faire d'autre que SUIVRE le point et VOULOIR qu'il atteigne l'étoile.",
    "• Reste immobile, cligne le moins possible au moment PRÉCIS où le point bouge.",
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


def _new_goal(rng, n_cells):
    """Cible à l'UNE des deux extrémités (tirage 50/50). Choix voulu : sur l'ensemble, les erreurs
    (pas qui éloignent) sont autant à gauche qu'à droite -> le SENS du mouvement est décorrélé de
    l'étiquette erreur/correct, donc xDAWN ne peut pas tricher sur la direction, il doit apprendre
    l'ErrP temporel (Chavarriaga 2010 équilibre ainsi)."""
    return rng.choice([0, n_cells - 1])


def _decide_step(rng, pos, goal, n_cells, error_rate, force=None):
    """Un pas du point (avance d'une case). `force` (smoke) impose erreur=True/correct=False ; sinon
    tirage à `error_rate`. Erreur = pas qui ÉLOIGNE de la cible. Rebond au bord (renvoie dans l'autre
    sens). Retourne (new_pos, label) ; l'étiquette suit l'EFFET RÉEL du pas (après rebond éventuel)."""
    toward = 1 if goal > pos else -1
    is_err = (rng.random() < error_rate) if force is None else force
    move = -toward if is_err else toward
    new_pos = pos + move
    if new_pos < 0 or new_pos >= n_cells:            # bord -> rebond dans l'autre sens
        new_pos = pos - move
    label = ERROR if abs(new_pos - goal) > abs(pos - goal) else CORRECT
    return new_pos, label


def _draw_track(app, n_cells, pos, goal, title=None):
    """Dessine la piste (cases), la cible ★ et le point (curseur). NE FLIPPE PAS : l'appelant peut
    ajouter des lignes sous la piste puis flipper. Géométrie centrée, indépendante de n_cells."""
    pg = app.pygame
    w, h = app.size
    app.win.fill(BG)
    app.center(app.big, title or "Amène le point à l'étoile  ★", FG, int(h * 0.16))
    cy = int(h * 0.42)
    dx = int(w * 0.09)
    x0 = w // 2 - (n_cells - 1) * dx // 2
    r = max(6, int(min(dx * 0.32, h * 0.05)))
    for i in range(n_cells):
        pg.draw.circle(app.win, OUTLINE, (x0 + i * dx, cy), r, 2)      # cases de la piste
    pg.draw.circle(app.win, GO, (x0 + goal * dx, cy), r + 3)          # cible = pastille verte (dessinée,
    pg.draw.circle(app.win, ON_COLOR, (x0 + pos * dx, cy), r)         # pas un glyphe) ; curseur au-dessus


def _step(app, n_cells, new_pos, goal, seconds, title=None):
    """Le point SAUTE à `new_pos` (apparition abrupte, horodatée à la 1re frame = ONSET), puis on
    maintient `seconds` (fenêtre de feedback = fenêtre de décision). Retourne l'onset (time.time())."""
    n_fr = 1 if app.smoke else max(1, int(round(seconds * app.refresh)))
    onset = None
    defer = _defer_key(app)
    for f in range(n_fr):
        app.drain(on_key=defer)             # 'P'/'T' re-postées (pas d'interruption de l'époque)
        _draw_track(app, n_cells, new_pos, goal, title=title)
        app.pygame.display.flip()
        if f == 0:
            onset = time.time()
        app.clock.tick(int(app.refresh) + 5)
        if app.smoke:
            break
    return onset


def _pause(app):
    """Fige la séance : une touche pour reprendre, Échap pour quitter (Abort -> menu). Déclenchée
    par ESPACE ENTRE deux pas (jamais pendant `_step`) -> aucune époque en cours n'est corrompue.
    No-op en smoke."""
    if app.smoke:
        return
    resume = []
    while not resume:
        app.drain(on_key=lambda e: resume.append(True))     # ESC/Q -> Abort (quitter la séance)
        app.win.fill(BG)
        h = app.size[1]
        app.center(app.big, "PAUSE", ACCENT, int(h * 0.42))
        app.center(app.mid, "une touche pour reprendre     ·     Échap pour quitter", DIM, int(h * 0.54))
        app.pygame.display.flip()
        app.clock.tick(30)


def _defer_key(app):
    """on_key pour `_step` : ne TRAITE pas ESPACE/'T' (on n'interrompt pas l'époque en cours) mais les
    RE-POSTE pour que le prochain `_track_hold` les capte -> la touche n'est pas perdue."""
    pg = app.pygame

    def on_key(e):
        if e.key == pg.K_SPACE or (e.unicode and e.unicode.lower() == "t"):
            pg.event.post(e)
    return on_key


def _track_hold(app, n_cells, pos, goal, seconds, title=None, note=None, note_col=None,
                sub=None, scoreboard=None, skip=False, hotkeys=None, pausable=True):
    """Maintient la piste STATIQUE `seconds` : pause inter-pas, annonce de cible, OU écran de verdict
    (lignes optionnelles sous la piste). ESC -> Abort (retour menu). `skip` : une touche interrompt
    (verdicts du démo). `pausable` : ESPACE met en pause. `hotkeys` : {char: fn} (ex. 'T' -> seuil)."""
    pressed = []

    def on_key(e):
        c = e.unicode.lower() if e.unicode else ""
        if pausable and e.key == app.pygame.K_SPACE:
            _pause(app)
        elif hotkeys and c in hotkeys:
            hotkeys[c]()
        elif skip:
            pressed.append(True)

    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        app.drain(on_key=on_key)
        if skip and pressed:
            return
        _draw_track(app, n_cells, pos, goal, title=title)
        h = app.size[1]
        if note is not None:
            app.center(app.big, note, note_col or FG, int(h * 0.60))
        if sub is not None:
            app.center(app.mid, sub, DIM, int(h * 0.70))
        if scoreboard is not None:
            app.center(app.small, scoreboard, DIM, int(h * 0.80))
        hint = "Espace = pause" + ("     ·     T = régler le seuil" if hotkeys and "t" in hotkeys else "")
        app.center(app.small, hint, DIM, int(h * 0.90))
        app.pygame.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return


def _epoch_now(app, onset, fs):
    """Épocher IMMÉDIATEMENT le pas qui vient d'avoir lieu. `_step` a maintenu le point à sa nouvelle
    case ERRP_FEEDBACK_S (~1 s) -> l'époque [-pre, +post] est DÉJÀ dans le buffer. Cet épochage
    incrémental (au lieu d'un ramassage en fin de bloc) découple l'époque de la durée du bloc : une
    PAUSE ultérieure ne peut plus la faire sortir du ring BrainFlow (~180 s). (n_samp, 8) ou None."""
    eeg, ts = app.acq.get_raw(time.time() - onset + ERRP_PRE_S + 0.5)
    if eeg is None:
        return None
    return epoch_from_stream(eeg, ts, onset, fs, pre_s=ERRP_PRE_S, post_s=ERRP_EPOCH_S)


def _run_block(app, n_cells, per, rng, error_rate, r, rounds, fs, epochs, labels, groups):
    """Un bloc = plusieurs COURSES (le point rejoint la cible) découpées en pas, jusqu'à `per` pas
    ÉPOCHÉS. Chaque pas est épocher TOUT DE SUITE (`_epoch_now`) et ajouté à epochs/labels/groups ->
    insensible aux pauses. La machine se trompe ~error_rate (pas qui éloigne). Retourne le nombre de
    pas ajoutés. Pause 'P' possible aux temps d'attente (`_track_hold`)."""
    title = f"Bloc {r + 1}/{rounds}"
    start = n_cells // 2
    pos, goal, steps, added, tries = start, _new_goal(rng, n_cells), 0, 0, 0
    _track_hold(app, n_cells, pos, goal, 0.9, title=title, note="nouvelle cible", note_col=DIM)
    while added < per and tries < per * 3 + 20:            # garde-fou anti-boucle si le board cale
        tries += 1
        force = (added % 2 == 0) if app.smoke else None    # smoke : garantir les 2 classes
        new_pos, label = _decide_step(rng, pos, goal, n_cells, error_rate, force=force)
        onset = _step(app, n_cells, new_pos, goal, ERRP_FEEDBACK_S, title=title)
        if app.smoke:
            time.sleep(ERRP_EPOCH_S + 0.25)     # headless : _step instantané -> laisser le board remplir
        ep = _epoch_now(app, onset, fs)
        if ep is not None:
            epochs.append(ep); labels.append(label); groups.append(r); added += 1
        pos, steps = new_pos, steps + 1
        if pos == goal or steps >= ERRP_MAX_RUN_STEPS:
            _track_hold(app, n_cells, pos, goal, 0.7, title=title,
                        note="atteinte" if pos == goal else "on recommence",
                        note_col=GO if pos == goal else DIM)
            pos, goal, steps = start, _new_goal(rng, n_cells), 0
            # ⚠️ DEUX écrans statiques par fin de course, pas un — et le second est celui qui
            # compte. Le premier montre l'état FINAL (point sur la cible) ; celui-ci montre l'état
            # NEUF, point revenu au centre et cible déplacée. Sans lui, cette remise à zéro — le
            # point saute de 2 à 4 cases ET la cible change d'extrémité une fois sur deux — tombait
            # dans la frame horodatée du pas SUIVANT : l'époque commençait sur un transitoire
            # visuel plein écran qui n'est pas le feedback qu'elle prétend mesurer.
            # Mesuré sur 200 séances simulées : **14,9 % des époques** partaient ainsi.
            # Corrélation avec l'étiquette : +1,2 point (z = 1,84), et elle ne vient pas du saut
            # mais du rebond de bord — après une transition le point repart du CENTRE, où aucun
            # rebond ne peut retourner l'étiquette. Trop petit pour fabriquer une AUC, donc le
            # modèle du 2026-07-24 (0,7763) reste valide ; c'était du bruit ajouté, pas un biais.
            # C'est le MÊME écran qu'en tête de bloc, aux mêmes 0,9 s, et le même que joue
            # `research/errp_stimulus.py` : les deux protocoles ne divergent plus.
            _track_hold(app, n_cells, pos, goal, 0.9, title=title,
                        note="nouvelle cible", note_col=DIM)
        else:
            _track_hold(app, n_cells, pos, goal, 0.45, title=title)     # pause inter-pas / settle
    return added


def adjust_threshold(app, model, save_path=None):
    """Réglage MANUEL du point de fonctionnement (le SEUIL de décision). ←/→ déplacent le seuil ;
    l'écran montre le TPR (part des ERREURS détectées) et le TNR (part des BONNES commandes gardées)
    ESTIMÉS sur la calibration (scores out-of-fold). ⚠️ TPR et TNR sont COUPLÉS par l'unique seuil :
    baisser le seuil détecte plus d'erreurs (TPR↑) mais annule plus de bonnes commandes (TNR↓), et
    inversement — on choisit un COMPROMIS, pas deux valeurs indépendantes. Entrée = appliquer (session) ;
    S = appliquer + sauver le modèle ; Échap = annuler."""
    scores, y = getattr(model, "oof_scores_", None), getattr(model, "oof_y_", None)
    if scores is None or y is None or len(np.unique(np.asarray(y))) < 2:
        app.flash("Réglage indisponible",
                  "pas de scores de calibration mémorisés (recalibre pour activer le réglage)", 3.5)
        return
    if app.smoke:
        return
    scores, y = np.asarray(scores, dtype=float), np.asarray(y).astype(int)
    lo, hi = float(scores.min()) - 0.5, float(scores.max()) + 0.5
    span = max(hi - lo, 1e-6)
    stepsz = span / 60.0
    th0 = float(model.threshold_)               # repère : seuil issu de la calibration
    cur = [float(np.clip(th0, lo, hi))]
    done = {"commit": False, "save": False}
    pg = app.pygame

    def on_key(e):
        if e.key in (pg.K_LEFT, pg.K_a):
            cur[0] = max(lo, cur[0] - stepsz)
        elif e.key in (pg.K_RIGHT, pg.K_d):
            cur[0] = min(hi, cur[0] + stepsz)
        elif e.key in (pg.K_RETURN, pg.K_KP_ENTER):
            done["commit"] = True
        elif e.unicode and e.unicode.lower() == "s":
            done["commit"] = done["save"] = True

    while not done["commit"]:
        try:
            app.drain(on_key=on_key)
        except Abort:
            return                              # Échap = annuler le réglage (aucun changement)
        w, h = app.size
        app.win.fill(BG)
        app.center(app.big, "Réglage du seuil ErrP", FG, int(h * 0.12))
        app.center(app.small, "compromis :  ← détecte plus d'erreurs (TPR↑, TNR↓)      "
                              "→ garde plus de bonnes commandes (TNR↑, TPR↓)", DIM, int(h * 0.20))
        bx, bw, by = int(w * 0.15), int(w * 0.70), int(h * 0.32)

        def xof(v):
            return bx + int(bw * (v - lo) / span)
        pg.draw.line(app.win, OUTLINE, (bx, by), (bx + bw, by), 3)
        pg.draw.line(app.win, DIM, (xof(th0), by - 13), (xof(th0), by + 13), 2)   # seuil calibration
        pg.draw.circle(app.win, ACCENT, (xof(cur[0]), by), 11)                    # seuil courant
        app.center(app.small, f"seuil = {cur[0]:+.2f}    (calibration : {th0:+.2f})", DIM, int(h * 0.39))
        tpr, tnr, bal = rates(y, scores >= cur[0])
        for i, (lab, val, col) in enumerate((("erreurs détectées (TPR)", tpr, GO),
                                             ("bonnes commandes gardées (TNR)", tnr, ACCENT))):
            ry = int(h * (0.50 + 0.13 * i))
            app.center(app.mid, f"{lab} : {val * 100:.0f}%", col, ry)
            pg.draw.rect(app.win, BAR_BG, (int(w * 0.28), ry + int(h * 0.03), int(w * 0.44), 18))
            pg.draw.rect(app.win, col, (int(w * 0.28), ry + int(h * 0.03), int(w * 0.44 * val), 18))
        app.center(app.small, f"balanced-acc {bal * 100:.0f}%     ·     {len(y)} pas de calibration",
                   DIM, int(h * 0.80))
        app.center(app.small,
                   "←/→ régler     ·     Entrée appliquer     ·     S appliquer+sauver     ·     Échap annuler",
                   ACCENT, int(h * 0.90))
        app.pygame.display.flip()
        app.clock.tick(60)

    th = cur[0]
    tpr, tnr, bal = rates(y, scores >= th)
    model.threshold_ = float(th)
    model.metrics_ = {"tpr": tpr, "tnr": tnr, "bal_acc": bal}
    print(f"[errp] seuil réglé manuellement -> {th:+.2f}  TPR={tpr * 100:.0f}%  TNR={tnr * 100:.0f}%"
          + ("  (sauvé)" if done["save"] and save_path else "  (session seulement)"))
    if done["save"] and save_path:
        model.save(save_path)
        app.flash("Seuil sauvegardé",
                  f"TPR {tpr * 100:.0f}%   ·   TNR {tnr * 100:.0f}%   ·   seuil {th:+.2f}", 2.2)


def _archive(save_path, epochs, labels, groups, fs):
    """Sauve un .npz horodaté des époques brutes (ré-analyse hors ligne, comme le P300)."""
    data_dir = os.path.dirname(save_path)
    os.makedirs(data_dir, exist_ok=True)
    payload = dict(epochs=np.asarray(epochs), labels=np.asarray(labels),
                   groups=np.asarray(groups), fs=fs, pre_s=ERRP_PRE_S, post_s=ERRP_EPOCH_S)
    last = os.path.join(data_dir, "errp_calib_last.npz")
    np.savez(last, **payload)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    np.savez(os.path.join(data_dir, f"errp_calib_{stamp}_n{len(labels)}.npz"), **payload)
    return last


def chemin_modele_horodate(dossier=None):
    """`data/errp_model_AAAAMMJJ_HHMMSS.joblib` — un fichier NEUF, jamais un écrasement.

    ⚠️ La calibration écrivait dans `ERRP_MODEL_PATH` (`data/errp_model.joblib`), un nom FIXE :
    la calibration suivante effaçait donc la précédente. Or `data/errp_model.joblib` est la trace
    du 24 juillet que ce chantier a explicitement choisi de préserver — le seul modèle ErrP
    enregistré au casque, celui dont viennent l'AUC 0,7763 (validation croisée groupée par bloc,
    200 essais, 5 blocs) et le p = 0,0099 sur 100 permutations. Une calibration de démonstration
    par un étudiant le détruisait sans un mot. Les époques survivaient (`_archive` horodate les
    `.npz`), mais aucun code de ce dépôt ne sait ré-entraîner depuis elles : le remède aurait été
    une séance casque complète. Le MI a déjà perdu ses quatre modèles de cette façon, faute
    d'époques ; le P300 a corrigé exactement ceci la veille (`p300_calibrate`, même fonction).
    Rien n'appliquait cet invariant : seule une prose l'affirmait.

    `errp_models.MOTIF` (`errp_model*.joblib`) liste déjà ces fichiers, du plus récent au plus
    ancien : le mode ErrP du moteur et l'appli pygame prennent donc automatiquement le dernier,
    sans qu'un nom fixe soit nécessaire nulle part.
    """
    dossier = os.path.dirname(ERRP_MODEL_PATH) if dossier is None else dossier
    return os.path.join(dossier, f"errp_model_{time.strftime('%Y%m%d_%H%M%S')}.joblib")


def _results(app, model, n_err, n_tot, save_path=None):
    """Écran de résultat (attend une touche) — AUC + significativité (permutation) + TPR/TNR + sLDA.
    'R' ouvre le réglage MANUEL du seuil (TPR/TNR) ; les chiffres se rafraîchissent au retour."""
    auc = model.cv_auc_
    pp = model.perm_p_
    sig = pp is not None and pp < 0.05
    pressed = []

    def on_key(e):
        if e.unicode and e.unicode.lower() == "r" and save_path is not None:
            adjust_threshold(app, model, save_path=save_path)   # met à jour threshold_/metrics_
        else:
            pressed.append(True)

    while not pressed:
        app.drain(on_key=on_key)
        mt = model.metrics_ or {"tpr": 0.0, "tnr": 0.0, "bal_acc": 0.0}   # rafraîchi après réglage
        app.win.fill(BG)
        h = app.size[1]
        app.center(app.big, "Calibration ErrP terminée", FG, int(h * 0.12))
        app.center(app.small, f"{n_err} erreurs / {n_tot} pas  ·  nfilter retenu = {model.nfilter_}",
                   DIM, int(h * 0.22))
        auc_txt = "—" if auc is None else f"{auc * 100:.1f}%"
        # AUC significative SEULEMENT si p<0,05 : sinon l'AUC peut être du bruit (petit N)
        col = GO if ((auc or 0) >= 0.70 and sig) else WARN
        app.center(app.mid, f"AUC erreur/correct : {auc_txt}", col, int(h * 0.34))
        perm_txt = ("permutation : non testée" if pp is None else
                    (f"permutation p={pp:.3f} — SIGNIFICATIF" if sig else
                     f"permutation p={pp:.3f} — NON significatif (prudence : peut être du bruit)"))
        app.center(app.small, perm_txt, GO if sig else WARN, int(h * 0.42))
        app.center(app.mid, f"détecte {mt['tpr'] * 100:.0f}% des erreurs  ·  "
                            f"garde {mt['tnr'] * 100:.0f}% des bonnes commandes",
                   DIM, int(h * 0.51))
        slda_txt = ("" if model.slda_auc_ is None else
                    f"   ·   baseline sLDA {model.slda_auc_ * 100:.1f}%")
        app.center(app.small, f"seuil asymétrique = {model.threshold_:+.2f}  "
                              f"(balanced-acc {mt['bal_acc'] * 100:.0f}%){slda_txt}",
                   DIM, int(h * 0.59))
        app.center(app.small, "R = régler le seuil (TPR / TNR)     ·     une autre touche = menu",
                   ACCENT, int(h * 0.80))
        app.pygame.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return


def calibrate(app, trials=ERRP_CAL_TRIALS, blocks=ERRP_CAL_BLOCKS,
              error_rate=ERRP_ERROR_RATE, save_path=None):
    """Calibration complète. En smoke : 2 blocs × quelques feedbacks (erreur/correct alternés),
    fit léger, sauvegarde dans save_path. Retourne True si un modèle a été entraîné.

    `save_path=None` -> un fichier HORODATÉ, jamais `data/errp_model.joblib` : voir
    `chemin_modele_horodate`.
    """
    save_path = save_path or chemin_modele_horodate()
    n_cells = ERRP_TRACK_CELLS

    # câble/électrodes AVANT d'enregistrer ; voies clés ErrP (Fz/Cz/Pz) encadrées. ⚠️ Cz sature à la
    # réouverture de l'app (piège #0ter) -> ne pas fermer/rouvrir ; saliner Fz/C3/Cz/C4.
    if not app.smoke and not app.signal_check(highlight=ERRP_MIDLINE, mode_label="ErrP"):
        return False
    if not _briefing(app):
        return False

    fs = app.acq.fs
    if app.smoke:
        time.sleep(1.0)                    # pré-remplir le board (époques avec pré-feedback valide)
    rng = random.Random() if not app.smoke else random.Random(0)
    eff_blocks = 2 if app.smoke else blocks
    per = 6 if app.smoke else max(1, trials // blocks)
    print(f"[errp-cal] {eff_blocks} blocs × {per} pas  erreurs≈{error_rate:.0%}  "
          f"(curseur-vers-cible ; onset = frame écran du pas, PAS le robot)")

    epochs, labels, groups = [], [], []
    for r in range(eff_blocks):
        before = len(labels)
        added = _run_block(app, n_cells, per, rng, error_rate, r, eff_blocks, fs, epochs, labels, groups)
        n_e = sum(1 for lbl in labels[before:] if lbl == ERROR)
        print(f"[errp-cal] bloc {r + 1}/{eff_blocks} : {added} époques ({n_e} erreurs)")

    n_tot = len(labels)
    n_err = int(sum(1 for lbl in labels if lbl == ERROR))
    if n_tot < 8 or len(set(labels)) < 2:
        print("[errp-cal] pas assez de données (ou une seule classe) -> pas d'entraînement.")
        if not app.smoke:
            app.flash("Calibration insuffisante",
                      "trop peu d'époques d'erreur — rallonge la séance / vérifie la liaison", 3.5)
        return False

    if not app.smoke:      # fit balaie nfilter + AUC OOF + permutation (~30 s) -> prévenir (écran figé)
        app.win.fill(BG)
        app.center(app.big, "Analyse...", FG, int(app.size[1] * 0.45))
        app.center(app.small, "balayage nfilter, seuil, baseline sLDA, test de permutation (~30 s)",
                   DIM, int(app.size[1] * 0.55))
        app.pygame.display.flip()
    # smoke : n_perm=0 (permutation sautée, synthétique non signifiant) ; réel : ERRP_PERM_N
    model = ErrPModel(fs=fs).fit(epochs, labels, groups=np.asarray(groups),
                                 n_perm=0 if app.smoke else None)
    model.save(save_path)
    last = save_path if app.smoke else _archive(save_path, epochs, labels, groups, fs)

    auc = model.cv_auc_
    mt = model.metrics_ or {"tpr": 0.0, "tnr": 0.0, "bal_acc": 0.0}
    sweep = "  ".join(f"nf{nf}={a * 100:.0f}%" for nf, a in sorted((model.sweep_ or {}).items()))
    pp = "—" if model.perm_p_ is None else f"{model.perm_p_:.3f}"
    slda = "—" if model.slda_auc_ is None else f"{model.slda_auc_ * 100:.1f}%"
    print(f"[errp-cal] {n_err}/{n_tot} erreurs  "
          f"AUC={'—' if auc is None else f'{auc * 100:.1f}%'} (nf retenu={model.nfilter_} ; {sweep})  "
          f"perm p={pp}  sLDA={slda}  "
          f"TPR={mt['tpr'] * 100:.0f}% TNR={mt['tnr'] * 100:.0f}% "
          f"bal-acc={mt['bal_acc'] * 100:.0f}%  seuil={model.threshold_:+.2f}  "
          f"modèle -> {os.path.basename(save_path)}  époques -> {os.path.basename(last)}")
    if not app.smoke:
        _results(app, model, n_err, n_tot, save_path)
    return True


if __name__ == "__main__":
    from core.config import use_utf8_console
    use_utf8_console()
    print("Ce module se lance depuis l'appli (mode ErrP -> Calibrer). "
          "Test de câblage headless : python src/research/app.py --smoke")
