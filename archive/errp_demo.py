"""Démonstrateur ErrP (potentiel d'erreur) — l'écran retiré de l'appli unifiée.

Ce module vivait comme `mode_errp` dans `src/research/app.py`, supprimé le 2026-09-08. L'ErrP est
maintenant DÉCODÉ par le MOTEUR (`python src/core/server.py --mode errp` -> flux `decoded_errp`),
sur les marqueurs de `src/stimulus/errp.py`, et se pilote depuis la console. Ce fichier reste ici,
ENCORE EXÉCUTABLE, pour la même raison que `cvep_pilot.py` : c'est la RÉFÉRENCE de décodage LOCAL
contre laquelle une séance casque compare le décodage réseau — même modèle, même piste, deux
décodeurs indépendants qui doivent voir la même réaction d'erreur au même pas.

⚠️ **La différence qui compte** : ici l'époque est découpée sur l'horloge de pygame (`_errp_epoch`,
l'écran horodate le pas qu'il vient d'afficher), alors que le moteur la découpe sur l'horodatage LSL
du marqueur `feedback`. Si les deux chemins divergent, regarder l'alignement avant le décodeur.

⚠️ Il est PASSIF : rien n'est envoyé à un actionneur. Il ANNONCE les détections et les compare à la
vérité-terrain (le pas éloignait-il de la cible ?), et tient un tableau TPR/TNR.

⚠️ Ne jamais le lancer en même temps que le moteur, la console ou un autre écran archivé : le casque
n'accepte qu'UNE connexion. Cet écran ouvre le casque LUI-MÊME.

    python archive/errp_demo.py                        # plein écran, casque réel
    python archive/errp_demo.py --model data/errp_model_20260818-153051.joblib
    python archive/errp_demo.py --synthetic            # sans casque (board de test BrainFlow)
    python archive/errp_demo.py --smoke                # test headless (CI) : calibre puis démontre
"""

import argparse
import os
import shutil
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))      # -> src/
from core.config import (DATA_DIR, empreinte_dossier, ERRP_DEMO_ERROR_RATE,  # noqa: E402
                    ERRP_EPOCH_S, ERRP_FEEDBACK_S, ERRP_MAX_RUN_STEPS, ERRP_MIDLINE,
                    ERRP_MODEL_PATH, ERRP_PRE_S, ERRP_TRACK_CELLS, use_utf8_console)
# La machinerie pygame partagée est le VOISIN `archive/ui.py` depuis le 2026-09-09 (elle était
# `research/ui.py`) : `research/` n'a plus le droit d'ouvrir le casque ni de dessiner. Nom de
# module NU, car Python met le dossier du script en tête de `sys.path`.
from ui import ACCENT, BG, DIM, FG, GO, Abort, App  # noqa: E402



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


def _errp_charger(model_path=None):
    """(modèle, raison, chemin) — le modèle ErrP à charger, ou une phrase qui dit quoi FAIRE.

    ⚠️ Les deux entrées ErrP de l'appli faisaient `os.path.exists(...)` puis `ErrPModel.load(...)`,
    c'est-à-dire un `joblib.load` nu. Or `data/errp_model.joblib` EXISTE — c'est le modèle du
    24 juillet — et ne se charge plus depuis que le décodeur a déménagé dans `core/` : son pickle
    référence le module NU `errp_decoder`. Mesuré, pas supposé :
    `ModuleNotFoundError: No module named 'errp_decoder'`, que personne n'attrape (`page_errp` et
    la boucle de `main` n'attrapent qu'`Abort`) — l'appli mourait sur un traceback EN PLEINE
    SÉANCE, après avoir fait mettre le casque et saliner les électrodes. `errp_models.charger` ne
    lève jamais et dit quoi faire ; c'est déjà par elle que passent le moteur (`core/modes/errp.py`)
    et le mode P300 de cette appli. Même défaut, même correctif, troisième et quatrième site.
    """
    from core.errp_models import charger, modeles_disponibles

    if model_path is None:
        dispo = modeles_disponibles()
        model_path = dispo[0] if dispo else ERRP_MODEL_PATH
    modele, probleme = charger(model_path)
    return modele, probleme, model_path


def _errp_status(dispo):
    """Le texte « modèles ErrP » de l'accueil, à partir des modèles RÉELLEMENT chargeables.

    Jumeau de `_p300_status`, et séparé pour la même raison : testable sans toucher à `data/`.
    L'accueil n'avait AUCUNE ligne ErrP — un étudiant lançait le mode pour découvrir sur place
    qu'aucun modèle n'était utilisable."""
    return f"{len(dispo)} ({os.path.basename(dispo[0])})" if dispo else "aucun utilisable"


def mode_errp(app, model_path=None):
    """Mode 5 : démonstrateur ErrP AUTONOME (aucun envoi robot).

    Tâche orientée-BUT curseur-vers-cible (Ferrez & Millán 2008) : un point doit rejoindre l'étoile ;
    ~ERRP_DEMO_ERROR_RATE des pas partent DANS LE MAUVAIS SENS -> vraie erreur RESSENTIE (violation
    d'attente + enjeu), bien plus saillante qu'une étiquette imposée. Chaque pas est lu en MONO-ESSAI :
    on annonce si la réaction d'erreur a été détectée + on compare à la vérité-terrain (le pas
    éloigne-t-il de la cible ?) + tableau TPR/TNR. Nécessite un modèle calibré."""
    import random as _random

    # `errp_calibrate` est le FICHIER VOISIN, dans `archive/` : les deux écrans partagent la piste,
    # la règle du pas et l'écran de réglage du seuil, et ils ont été archivés ensemble le
    # 2026-09-08. Même patron que `mi_pilot.py`, qui importe `mi_calibrate` de la même façon.
    from errp_calibrate import _decide_step, _new_goal, _step, _track_hold, adjust_threshold
    from core.errp_decoder import ERROR

    # `model_path=None` -> le PLUS RÉCENT des modèles réellement chargeables, comme `mode_p300`.
    # Le défaut était `ERRP_MODEL_PATH`, un nom fixe que la calibration n'écrit plus (elle
    # horodate, cf. `errp_calibrate.chemin_modele_horodate`) : garder ce défaut aurait fait
    # pointer le mode droit sur la trace du 24 juillet, précisément le modèle refusé.
    model, probleme, model_path = _errp_charger(model_path)
    if model is None:
        app.flash("Pas de modèle ErrP utilisable",
                  probleme or "lance d'abord « ErrP -> Calibrer » (~4-5 min)", 4.0)
        return
    if not app.signal_check(highlight=ERRP_MIDLINE, mode_label="ErrP"):
        return                    # liaison + voies clés (Fz/Cz/Pz) ; casque KO ou ESC -> retour
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


def _parse(argv):
    p = argparse.ArgumentParser(
        description="Démonstrateur ErrP (ARCHIVÉ — référence de décodage local).")
    # ⚠️ `--model` EXPLICITE, défaut `None` -> le plus récent des modèles réellement CHARGEABLES
    # (cf. `_errp_charger`). Le défaut historique était `ERRP_MODEL_PATH`, c'est-à-dire la trace du
    # 24 juillet, que `errp_models.charger` refuse : le mode mourait sur un `ModuleNotFoundError`
    # en pleine séance, après avoir fait mettre le casque.
    p.add_argument("--model", default=None,
                   help="chemin du modèle ErrP (défaut : le plus récent chargeable de data/)")
    p.add_argument("--windowed", action="store_true", help="fenêtre au lieu du plein écran")
    p.add_argument("--synthetic", action="store_true", help="board de test (sans casque)")
    p.add_argument("--smoke", action="store_true", help="test headless (CI)")
    return p.parse_args(argv)


def main(argv=None):
    a = _parse(sys.argv[1:] if argv is None else argv)
    app = App(windowed=a.windowed, synthetic=a.synthetic, smoke=a.smoke)
    tmp, model_path = None, a.model
    # `data/` porte des enregistrements EEG d'une personne identifiable sur un dépôt public :
    # aucun test n'a le droit d'y écrire. Vérifié, jamais supposé.
    empreinte_avant = empreinte_dossier(DATA_DIR) if a.smoke else None
    try:
        if a.smoke:
            # Un modèle chargeable n'existe pas forcément (dépôt fraîchement cloné) : on en
            # calibre un minuscule, headless, dans un dossier TEMPORAIRE — jamais dans `data/`.
            import errp_calibrate
            tmp = tempfile.mkdtemp(prefix="errp_demo_smoke_")
            model_path = os.path.join(tmp, "errp_model_smoke.joblib")
            errp_calibrate.calibrate(app, save_path=model_path)
            # ⚠️ `mode_errp` charge par `errp_models.charger`, qui EXIGE des scores hors-pli : si
            # le modèle du smoke (12 époques, board synthétique) venait à être refusé — une autre
            # version de pyriemann, une graine malheureuse — `mode_errp` se contenterait d'un
            # `flash` et sortirait AVANT sa boucle live, sans que rien ne rougisse. Le
            # démonstrateur (~120 lignes) ne serait plus exercé par aucun test.
            from core import errp_models
            assert errp_models.charger(model_path)[0] is not None, (
                f"le modèle du smoke doit être ACCEPTÉ par errp_models.charger(), sinon mode_errp "
                f"sort avant sa boucle et le démonstrateur n'est plus testé du tout : "
                f"{errp_models.charger(model_path)[1]}")
        else:
            from core.errp_models import modeles_disponibles
            print(f"[errp-demo] modèles ErrP : {_errp_status(modeles_disponibles())}")
        try:
            mode_errp(app, model_path=model_path)
        except Abort:
            pass
    finally:
        app.close()
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    if a.smoke:
        # Les deux invariants de chargement, montés ici AVEC l'écran qu'ils protègent (ils vivaient
        # dans le `_smoke` de `research/app.py`). Vérifiés sur le TEXTE SOURCE parce que c'est la
        # propriété qu'on veut tenir : un chargement direct réapparu ici passerait tous les tests de
        # décodage et ferait mourir l'écran sur un `ModuleNotFoundError` la première fois qu'un
        # modèle hérité traîne dans `data/` — ce qui est le cas sur ce poste.
        # ⚠️ C'est une recherche de TEXTE : ne pas écrire le nom interdit dans un commentaire de
        # `mode_errp`, même pour dire de ne pas s'en servir.
        import inspect
        interdit = "ErrPModel" + ".load"
        decodeur_local = ("research" + ".errp_decoder", "research import " + "errp_decoder")
        src = inspect.getsource(mode_errp)
        assert "_errp_charger" in src and interdit not in src, (
            f"mode_errp doit charger par `_errp_charger` (donc `errp_models.charger`, qui NOMME "
            f"le problème) et jamais par {interdit}, un joblib.load nu")
        assert not any(forme in src for forme in decodeur_local), (
            f"mode_errp doit décoder par `core.errp_decoder` : le décodeur ErrP vit dans `core` "
            f"depuis le chantier ErrP, et un import de {decodeur_local[0]} remis ici ferait "
            f"diverger cet écran du moteur en silence")
        assert _errp_status([]) == "aucun utilisable", (
            f"sans modèle ErrP CHARGEABLE, il faut le DIRE — un fichier présent mais hérité ne "
            f"vaut pas « oui » ({_errp_status([])})")
        empreinte_apres = empreinte_dossier(DATA_DIR)
        assert empreinte_apres == empreinte_avant, (
            f"ce smoke a touché data/ — la calibration doit écrire UNIQUEMENT dans le dossier "
            f"temporaire ci-dessus, jamais dans data/ (dossier gitignoré, mais qui porte des "
            f"enregistrements EEG d'une personne identifiable) : "
            f"{set(empreinte_apres) ^ set(empreinte_avant) or 'contenu modifié'}")
        print("[errp-demo] smoke OK : calibration + démonstrateur mono-essai câblés (headless).")
    return True


if __name__ == "__main__":
    use_utf8_console()
    main()
