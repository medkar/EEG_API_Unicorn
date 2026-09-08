"""Pilotage c-VEP par TEMPLATE APPRIS (eCCA) — l'écran de PILOTAGE retiré de l'appli unifiée.

Ce module vivait comme `mode_cvep` dans `src/research/app.py`. Le c-VEP est maintenant DÉCODÉ par
le MOTEUR (`python src/core/server.py --mode cvep` -> flux `decoded_cvep`), et se pilote depuis la
console — plus depuis pygame. Ce fichier reste ici, ENCORE EXÉCUTABLE, pour une seule raison : c'est
la RÉFÉRENCE contre laquelle on compare le décodage réseau lors d'une séance casque — même modèle,
mêmes cibles, deux décodeurs indépendants (celui-ci en pygame local, celui du moteur sur le réseau)
qui doivent désigner la MÊME cible.

La CALIBRATION, elle, a bougé DEUX FOIS depuis : c'est le MOTEUR qui calibre (la console lance
`src/stimulus/cvep.py --calibrer`, le moteur entraîne, la console fait juger avant d'enregistrer),
et l'écran pygame qui le faisait est archivé à côté d'ici, dans `archive/cvep_calibrate.py`. Ce
fichier-ci ne fait que PILOTER un modèle déjà entraîné.

    python archive/cvep_pilot.py                       # plein écran, casque réel
    python archive/cvep_pilot.py --windowed
    python archive/cvep_pilot.py --synthetic            # sans casque (board de test BrainFlow)
    python archive/cvep_pilot.py --model data/cvep_model.npz
    python archive/cvep_pilot.py --smoke                # test headless (CI) : calibre puis pilote
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
from collections import deque

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))      # -> src/
from core.config import (CVEP_CHANNELS, CVEP_CORR_MIN, CVEP_DECISION_CYCLES,  # noqa: E402
                    CVEP_MIN_VOTES, CVEP_MODEL_PATH, CVEP_VOTE_LEN, DATA_DIR,
                    empreinte_dossier, use_utf8_console)
from research.itr import itr as _itr  # noqa: E402
# La machinerie PARTAGÉE (Live, le fil de décodage/émission, le rendu, le vote) vivait dans
# `research/app.py` ; elle est dans `research/ui.py` depuis le 2026-09-08, l'appli pygame ayant été
# supprimée — voir `archive/README.md`.
from research.ui import Abort, App, Live, _live_loop, _running, _vote  # noqa: E402


def _cvep_decode(app, live, dec, rows, epoch_s, n_win, code_len, name_to_cmd, hz=5.0):
    """Copie EXACTE du `_cvep_decode` de `research/app.py` (avant la suppression de ce fichier,
    le 2026-09-08) : le fil qui décode en
    continu et publie le vote. Dupliquée dans `cvep_rcca_pilot.py` à dessein — les deux fichiers
    archivés doivent rester compréhensibles et exécutables SEULS, sans dépendre l'un de l'autre."""
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
    """Copie EXACTE du `mode_cvep` de `research/app.py` (avant son retrait, tâche 6 du chantier
    c-VEP ; ce fichier-là a été supprimé le 2026-09-08)."""
    from core.cvep_code import build_targets, is_on as cvep_on
    from core.cvep_decoder import CVEPDecoder, CVEPModel

    if not os.path.exists(model_path):
        app.flash("Pas de modèle c-VEP",
                  "calibre d'abord : console -> c-VEP -> Calibrer", 3.5)
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
                  f"l'affichage en compte {len(plan)} — recalibre (page c-VEP -> Calibrer)", 4.0)
        return
    if model.w is None or len(model.w) != len(model.channels):
        app.flash("Modèle c-VEP incohérent",
                  f"filtre spatial sur {0 if model.w is None else len(model.w)} voies pour "
                  f"{len(model.channels)} sélectionnées — recalibre (page c-VEP -> Calibrer)", 4.0)
        return
    print(f"[cvep-pilot] {len(plan)} cibles  code L={len(code)} cycle={len(code)/app.refresh:.2f}s  "
          f"lags={[c['lag'] for c in plan]}  calib LOO={cv}")
    print(f"[cvep-pilot] décision sur {CVEP_DECISION_CYCLES} cycles ({decision_s:.2f}s)  "
          f"vote={CVEP_MIN_VOTES}/{CVEP_VOTE_LEN}  "
          f"ITR potentiel {_itr(len(plan), model.cv_ or 0.0, decision_s):.1f} bits/min")

    def paint(frame, cmd):
        app.draw_ring(plan, spots, lambda c, f: cvep_on(f, c["code"]), frame)

    with _running(app, _cvep_decode, dec, rows, n_win / app.acq.fs, n_win,
                  len(code), name_to_cmd) as live:
        _live_loop(app, live, [c["name"] for c in plan], CVEP_CORR_MIN,
                   f"c-VEP {len(plan)} cibles (calib {cv})", paint)


def _parse(argv):
    p = argparse.ArgumentParser(description="Pilotage c-VEP eCCA (ARCHIVÉ — référence casque).")
    p.add_argument("--model", default=CVEP_MODEL_PATH, help="chemin du modèle eCCA")
    p.add_argument("--windowed", action="store_true", help="fenêtre au lieu du plein écran")
    p.add_argument("--send", action="store_true", help="armer l'envoi UDP dès le lancement")
    p.add_argument("--synthetic", action="store_true", help="board de test (sans casque)")
    p.add_argument("--smoke", action="store_true", help="test headless (CI)")
    return p.parse_args(argv)


def main(argv=None):
    a = _parse(sys.argv[1:] if argv is None else argv)
    app = App(windowed=a.windowed, synthetic=a.synthetic, smoke=a.smoke, send=a.send)
    tmp = None
    model_path = a.model
    # ⚠️ Le garde qui manquait le 2026-08-21 : ce fichier a RÉELLEMENT écrit dans le vrai
    # `data/cvep_rcca_model.npz` un jour où `rcca_save_path` n'était pas détourné — et RIEN, dans
    # ce fichier, ne s'en serait aperçu. `empreinte_dossier` (déménagée dans `core/config.py`
    # exactement pour être appelable ICI) rend cette classe d'accident impossible à manquer,
    # même le jour où le détournement ci-dessous est oublié ou mal fait.
    empreinte_avant = empreinte_dossier(DATA_DIR) if a.smoke else None
    try:
        if a.smoke:
            # Un modèle par défaut n'existe pas forcément (dépôt fraîchement cloné) : on en
            # calibre un minuscule, headless, comme le faisait l'ancien smoke de `app.py`.
            # ⚠️ `calibrate()` entraîne DÉSORMAIS les deux décodeurs (tâche 6) et sauvegarde LES
            # DEUX fichiers : `rcca_save_path` DOIT être détourné aussi, sinon son défaut
            # (`CVEP_RCCA_MODEL_PATH`) écrit dans le VRAI `data/cvep_rcca_model.npz` — data/ porte
            # des enregistrements EEG d'une personne identifiable sur un dépôt public.
            import cvep_calibrate            # le FICHIER VOISIN, archivé le 2026-09-08
            tmp = tempfile.mkdtemp(prefix="cvep_pilot_smoke_")
            model_path = os.path.join(tmp, "cvep_model_smoke.npz")
            cvep_calibrate.calibrate(app, save_path=model_path,
                                     rcca_save_path=os.path.join(tmp, "cvep_rcca_model_smoke.npz"))
        # ⚠️ `mode_cvep` sort AVANT sa boucle live sur plusieurs conditions (pas de modèle,
        # refresh incompatible, nombre de cibles incohérent, filtre spatial incohérent) — chacune
        # via un simple `return` après un `app.flash(...)`, donc SANS exception. Un smoke qui se
        # contente d'appeler `mode_cvep` et de constater qu'il n'a pas levé ne prouve RIEN : la
        # revue de tâche 6 a mesuré qu'un modèle mal calibré (n_targets faux) fait sortir
        # `mode_cvep` en silence, avec `exit=0` et « smoke OK » imprimé quand même. On espionne
        # donc `app.flash` PENDANT l'appel : si l'un de ces titres apparaît, la boucle live n'a
        # jamais tourné, et ce smoke doit le dire au lieu de le cacher.
        avortements = []
        flash_reel = app.flash

        def _flash_espion(titre, *a2, **kw2):
            if titre.startswith(("Pas de modèle", "Modèle")):
                avortements.append(titre)
            return flash_reel(titre, *a2, **kw2)

        app.flash = _flash_espion
        try:
            mode_cvep(app, model_path=model_path)
        except Abort:
            pass
        finally:
            app.flash = flash_reel
        if a.smoke:
            assert not avortements, (
                f"mode_cvep a été refusé SILENCIEUSEMENT ({avortements}) — il serait sorti AVANT "
                f"sa boucle live, et rien d'autre que cette assertion ne l'aurait remarqué")
    finally:
        app.close()
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    if a.smoke:
        empreinte_apres = empreinte_dossier(DATA_DIR)
        assert empreinte_apres == empreinte_avant, (
            f"ce smoke a touché data/ — la calibration doit écrire UNIQUEMENT dans le dossier "
            f"temporaire ci-dessus, jamais dans data/ (dossier gitignoré, mais qui porte des "
            f"enregistrements EEG d'une personne identifiable) : "
            f"{set(empreinte_apres) ^ set(empreinte_avant) or 'contenu modifié'}")
        print("[cvep-pilot] smoke OK : calibration + décodage + affichage câblés (headless).")
    return True


if __name__ == "__main__":
    use_utf8_console()
    main()
