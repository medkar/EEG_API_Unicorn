"""c-VEP à CODES GOLD DISTINCTS (rCCA) — calibration ET pilotage, l'hypothèse RÉFUTÉE archivée.

Ce module vivait comme `calib_cvep_rcca` (via `research.cvep_rcca.calibrate_rcca`) et `mode_cvep_rcca`
dans `src/research/app.py`. Codes Gold distincts + reconvolution ont été mesurés et RÉFUTÉS : voir
`src/core/cvep_rcca.py` (docstring du module) — le rCCA lui-même n'est PAS réfuté (rebranché sur le
stimulus décalé que le produit garde, il fait jeu égal avec l'eCCA), c'est la moitié « codes Gold »
de l'hypothèse qui l'était. La calibration DÉSORMAIS au menu (`python src/research/app.py`, page
c-VEP) entraîne le rCCA sur le stimulus décalé, pas sur des codes Gold — elle REMPLACE celle-ci.

Ce fichier reste ici, ENCORE EXÉCUTABLE, pour une seule raison : c'est la trace vivante de ce qui a
été mesuré et écarté — le rejouer reste le moyen le plus direct de vérifier qu'un futur changement
n'a pas fait revivre l'hypothèse par accident. `make_distinct_codes` / `build_targets_rcca` restent
lisibles dans `src/research/cvep_rcca.py`, dont ce fichier importe le décodeur (`RCCADecoder`,
`RCCAModel`, ré-exportés depuis `core/cvep_rcca.py`).

    python archive/cvep_rcca_pilot.py --calibrate --windowed   # calibrer PUIS piloter (Gold)
    python archive/cvep_rcca_pilot.py                          # piloter un modèle Gold déjà calibré
    python archive/cvep_rcca_pilot.py --synthetic
    python archive/cvep_rcca_pilot.py --smoke                  # test headless (CI)
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
from core.config import (CVEP_CHANNELS, CVEP_DECISION_CYCLES, CVEP_MIN_VOTES,  # noqa: E402
                    CVEP_RCCA_CORR_MIN, CVEP_RCCA_MODEL_PATH, CVEP_VOTE_LEN, DATA_DIR,
                    empreinte_dossier, use_utf8_console)
from research.app import Live, _live_loop, _running, _vote  # noqa: E402  (machinerie PARTAGÉE avec
                                                             # le SSVEP, resté dans app.py : Live,
                                                             # le fil de décodage/émission, le rendu)
from research.cvep_rcca import RCCADecoder, RCCAModel, build_targets_rcca  # noqa: E402
from research.itr import itr as _itr  # noqa: E402
from research.ui import Abort, App  # noqa: E402


def _cvep_decode(app, live, dec, rows, epoch_s, n_win, code_len, name_to_cmd, hz=5.0):
    """Copie EXACTE de `research.app._cvep_decode` (avant son retrait) : le fil qui décode en
    continu et publie le vote. Dupliquée dans `cvep_pilot.py` à dessein — les deux fichiers
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


def calibrate_rcca(app, cycles=None, save_path=CVEP_RCCA_MODEL_PATH):
    """Copie EXACTE de `research.cvep_rcca.calibrate_rcca` (avant son retrait, tâche 6). Calibration
    du mode rCCA + CODES DISTINCTS. Reprend le protocole c-VEP classique (fixer chaque cible en
    blocs entrelacés) mais chaque cible affiche SON code Gold, et on ajuste un rCCA.

    Réutilise les helpers éprouvés de cvep_calibrate (briefing, blocs mélangés, rendu, garde-fous)
    pour ne pas diverger du protocole validé. Retourne (ok, cv_loo|None).
    """
    from core.config import CVEP_CAL_BLOCKS, CVEP_CAL_CYCLES
    from research.cvep_calibrate import (_briefing, _draw, _make_blocks, _wilson_hi,  # noqa: E402
                                EARLY_ITR_MIN, SETTLE_CYCLES)

    cycles = CVEP_CAL_CYCLES if cycles is None else cycles
    plan, codes = build_targets_rcca()
    L = int(codes.shape[1])
    spots = app.ring_spots(plan)
    acq = app.acq
    model = RCCAModel(codes, fs=acq.fs, refresh=app.refresh)
    rows = acq.eeg_rows                          # on enregistre les 8 voies
    epoch_s = model.n_cyc / acq.fs
    if app.smoke:
        cycles = 2

    blocks = _make_blocks(plan, cycles, CVEP_CAL_BLOCKS)
    n_blk = len(blocks)
    est = (len(plan) * cycles + n_blk * SETTLE_CYCLES) * L / app.refresh / 60.0 + n_blk * 1.8 / 60.0
    print(f"[rcca-cal] {len(plan)} cibles à CODES DISTINCTS (Gold L={L}), ajustement sur "
          f"{model.channels}")
    print(f"[rcca-cal] {cycles} cycles/cible, {n_blk} blocs entrelacés  ≈ {est:.1f} min")
    if not _briefing(app):
        return False, None
    if not app.signal_check(highlight=CVEP_CHANNELS, mode_label="c-VEP rCCA"):
        return False, None

    epochs, labels = [], []
    got_by_idx = {c["idx"]: 0 for c in plan}
    check_at = max(1, int(round(n_blk * 0.4)))
    frame, prev_phase = 0, -1
    settle = 0 if app.smoke else SETTLE_CYCLES
    try:
        for b_idx, (target, n_cyc) in enumerate(blocks, start=1):
            if not app.smoke:
                _, qrows, _ = app.signal_ok(0.5)
                dead = [nm for nm, _, v in qrows if v == "morte"]
                if dead:
                    print(f"[rcca-cal] ⛔ LIAISON PERDUE (voies plates : {', '.join(dead)}) "
                          f"au bloc {b_idx}/{n_blk} — arrêt, rien n'est entraîné.")
                    app.flash("Liaison casque perdue",
                              f"voies plates : {', '.join(dead)} — vérifie le câble", 4.0)
                    return False, None
            got, skip, start = 0, settle, frame
            while got < n_cyc:
                app.drain()
                phase = frame % L
                if phase == 0 and prev_phase != 0:
                    if skip > 0:
                        skip -= 1
                    else:
                        ep = acq.get_epoch(epoch_s, rows=rows, filtered=False)
                        if ep is not None and len(ep) >= model.n_cyc:
                            epochs.append(ep[:model.n_cyc])
                            labels.append(target["idx"])
                            got += 1
                            got_by_idx[target["idx"]] += 1
                prev_phase = phase
                _draw(app, plan, spots, frame, target, got, n_cyc, b_idx, n_blk)
                app.clock.tick(int(app.refresh) + 5)
                frame += 1
                if app.smoke and (frame - start) > (n_cyc + settle + 2) * L:
                    break
            print(f"[rcca-cal] bloc {b_idx}/{n_blk} {target['name']:<10} "
                  f"code#{target['idx']} : {got} cycles", flush=True)
            if b_idx == check_at and not app.smoke and len(set(labels)) == len(plan):
                probe = RCCAModel(codes, fs=acq.fs, refresh=app.refresh)
                probe.fit([e[:, probe.channels] for e in epochs], labels)
                if probe.cv_ is not None:
                    hi = _itr(len(plan), _wilson_hi(probe.cv_, len(epochs)), model.n_cyc / acq.fs)
                    bad = hi < EARLY_ITR_MIN
                    print(f"[rcca-cal] contrôle mi-parcours ({len(epochs)} cycles) : LOO "
                          f"{probe.cv_*100:.0f}% -> au mieux {hi:.1f} bits/min"
                          + ("  ⚠️ SOUS LE PLANCHER" if bad else "  -> on continue"), flush=True)
                    if bad:
                        app.flash("Séance mal engagée",
                                  f"au mieux {hi:.0f} bits/min — ESC pour arrêter", 6.0)
            if b_idx < n_blk:
                app.flash("Change de cible",   # inter-bloc = point de PAUSE sûr (ESPACE)
                          f"prépare-toi à fixer {blocks[b_idx][0]['name']}   ·   Espace = pause",
                          1.8, skippable=False, pausable=True)
    except Abort:
        print("[rcca-cal] interrompu — entraînement sur ce qui est déjà enregistré.")
    print("[rcca-cal] cycles par cible : "
          + "  ".join(f"{c['name']}={got_by_idx[c['idx']]}" for c in plan))

    if len(set(labels)) < 2 or len(epochs) < 4:
        print("[rcca-cal] pas assez de données pour entraîner.")
        return False, None

    model.fit([e[:, model.channels] for e in epochs], labels)
    model.save(save_path)
    if not app.smoke:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        archive = os.path.join(os.path.dirname(save_path),
                               f"cvep_rcca_calib_{stamp}_n{len(plan)}.npz")
        import numpy as np
        np.savez(archive, epochs=np.asarray(epochs), labels=np.asarray(labels), codes=codes,
                 fs=acq.fs, refresh=app.refresh, channels=np.asarray(model.channels, dtype=int),
                 sigma=float(np.asarray(epochs).std()))
        print(f"[rcca-cal] données archivées : {os.path.basename(archive)}")

    cv = model.cv_ or 0.0
    decision_s = model.n_cyc / acq.fs
    bits = _itr(len(plan), cv, decision_s)
    print(f"[rcca-cal] {len(epochs)} cycles sur {len(plan)} cibles -> LOO {cv*100:.1f}%  "
          f"ITR ≈ {bits:.1f} bits/min (1 cycle) — SSVEP réf. 49.9")
    if not app.smoke:
        app.flash("Calibration rCCA terminée",
                  f"LOO {cv*100:.0f}%   {bits:.0f} bits/min", 3.5)
    return True, model.cv_


def mode_cvep_rcca(app, model_path=CVEP_RCCA_MODEL_PATH):
    """Copie EXACTE de `research.app.mode_cvep_rcca` (avant son retrait, tâche 6). 2e variante
    c-VEP : CODES DISTINCTS (Gold) décodés par reconvolution (rCCA, pyntbci). Réutilise
    `_cvep_decode` (interface `classify(window, phase)` identique à l'eCCA)."""
    from core.cvep_code import is_on as cvep_on

    if not os.path.exists(model_path):
        app.flash("Pas de modèle c-VEP rCCA",
                  "calibre d'abord (python archive/cvep_rcca_pilot.py --calibrate)", 3.5)
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
    print(f"[rcca-pilot] {len(plan)} cibles à CODES DISTINCTS  cycle={model.code_len/app.refresh:.2f}s  "
          f"calib LOO={cv}")
    print(f"[rcca-pilot] décision sur {CVEP_DECISION_CYCLES} cycles ({decision_s:.2f}s)  "
          f"vote={CVEP_MIN_VOTES}/{CVEP_VOTE_LEN}  "
          f"ITR potentiel {_itr(len(plan), model.cv_ or 0.0, decision_s):.1f} bits/min")

    def paint(frame, cmd):
        app.draw_ring(plan, spots, lambda c, f: cvep_on(f, c["code"]), frame)

    with _running(app, _cvep_decode, dec, rows, n_win / app.acq.fs, n_win,
                  model.code_len, name_to_cmd) as live:
        _live_loop(app, live, [c["name"] for c in plan], CVEP_RCCA_CORR_MIN,
                   f"c-VEP rCCA {len(plan)} cibles (calib {cv})", paint)


def _parse(argv):
    p = argparse.ArgumentParser(
        description="c-VEP rCCA + codes Gold distincts (ARCHIVÉ — hypothèse réfutée).")
    p.add_argument("--model", default=CVEP_RCCA_MODEL_PATH, help="chemin du modèle rCCA (Gold)")
    p.add_argument("--calibrate", action="store_true", help="calibrer AVANT de piloter")
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
    # ⚠️ Le garde qui manquait le 2026-08-21 : `cvep_pilot.py` a RÉELLEMENT écrit dans le vrai
    # `data/cvep_rcca_model.npz` un jour où son détournement était oublié, et RIEN dans son smoke
    # ne s'en serait aperçu. `empreinte_dossier` rend cette classe d'accident impossible à
    # manquer ICI AUSSI, même le jour où le détournement ci-dessous est oublié ou mal fait.
    empreinte_avant = empreinte_dossier(DATA_DIR) if a.smoke else None
    try:
        if a.smoke:
            # ⚠️ `save_path` DOIT être détourné vers un dossier temporaire : le défaut
            # (`CVEP_RCCA_MODEL_PATH`) est le VRAI `data/cvep_rcca_model.npz`, qui porte déjà le
            # SEUL modèle Gold jamais calibré au casque — data/ ne doit JAMAIS être touché par un
            # test (dossier gitignoré, mais des enregistrements EEG d'une personne identifiable).
            tmp = tempfile.mkdtemp(prefix="cvep_rcca_pilot_smoke_")
            model_path = os.path.join(tmp, "cvep_rcca_model_smoke.npz")
            calibrate_rcca(app, save_path=model_path)
        elif a.calibrate:
            try:
                calibrate_rcca(app, save_path=model_path)
            except Abort:
                pass
        # ⚠️ `mode_cvep_rcca` sort AVANT sa boucle live (sans exception, juste un `app.flash(...)`
        # puis `return`) si le modèle est absent ou incompatible. La revue de tâche 6 a mesuré
        # qu'un smoke qui se contente d'appeler la fonction et de constater l'absence d'exception
        # ne prouve rien : « smoke OK », `exit=0`, boucle live jamais exercée. On espionne donc
        # `app.flash` PENDANT l'appel — même parade que `cvep_pilot.py`.
        avortements = []
        flash_reel = app.flash

        def _flash_espion(titre, *a2, **kw2):
            if titre.startswith(("Pas de modèle", "Modèle")):
                avortements.append(titre)
            return flash_reel(titre, *a2, **kw2)

        app.flash = _flash_espion
        try:
            mode_cvep_rcca(app, model_path=model_path)
        except Abort:
            pass
        finally:
            app.flash = flash_reel
        if a.smoke:
            assert not avortements, (
                f"mode_cvep_rcca a été refusé SILENCIEUSEMENT ({avortements}) — il serait sorti "
                f"AVANT sa boucle live, et rien d'autre que cette assertion ne l'aurait remarqué")
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
        print("[rcca-pilot] smoke OK : calibration Gold + décodage + affichage câblés (headless).")
    return True


if __name__ == "__main__":
    use_utf8_console()
    main()
