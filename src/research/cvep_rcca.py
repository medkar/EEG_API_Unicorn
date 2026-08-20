"""c-VEP variante CODES GOLD DISTINCTS — l'hypothèse RÉFUTÉE, gardée lisible.

⚠️ **Ce fichier ne contient plus le décodeur.** `RCCAModel` et `RCCADecoder` sont partis dans
`src/core/cvep_rcca.py` : le moteur en a besoin, donc ils suivent la règle du déménagement. Ce qui
reste ici, c'est la **fabrique de codes Gold** et le plan de cibles qui va avec — c'est-à-dire la
moitié de l'hypothèse qui a été mesurée et **réfutée**.

Ce qui a été testé, et ce qui a été conclu :
  - stimulus classique : UNE m-séquence, décalée circulairement (un lag par cible). C'est le
    stimulus que le produit garde.
  - stimulus d'ICI : chaque cible affiche un CODE GOLD DIFFÉRENT (intercorrélation basse), décodé
    par RECONVOLUTION (rCCA de pyntbci) — on apprend une courte réponse transitoire commune à tous
    les codes, qui se transfère de l'un à l'autre. C'était LE cas où la reconvolution pouvait payer.

Verdict : **codes Gold = non**. Mais les deux moitiés de l'hypothèse (« rCCA » et « codes
distincts ») ont toujours été mesurées ENSEMBLE, et `RCCAModel` prend ses codes en paramètre — il
n'a jamais su d'où ils venaient. Rebranché sur le stimulus décalé, le rCCA fait jeu égal avec
l'eCCA (43/90 chacun, cf. `core/cvep_rcca.py`). C'est la moitié « codes Gold » qui était mauvaise.

⚠️ **Une hypothèse réfutée se garde LISIBLE, pas BRANCHÉE.** Après ce découpage, les seuls
appelants de `make_distinct_codes` / `build_targets_rcca` sont les écrans Gold de
`research/app.py`, qui partent dans `archive/`. C'est voulu : `cvep_models.charger` refuse
d'ailleurs tout modèle rCCA dont les codes ne sont pas ceux du stimulus affiché aujourd'hui, ce
qui met `data/cvep_rcca_model.npz` (calibré sur des codes Gold) définitivement hors de la liste
proposée à un étudiant.

    python src/research/cvep_rcca.py     # autotest sur c-VEP synthétique à codes distincts (aucun casque)
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (CVEP_CHANNELS, CVEP_RCCA_MODEL_PATH,  # noqa: E402
                    FS_UNICORN, use_utf8_console)
# Le décodeur vit maintenant dans `core/`. Ré-exporté ici pour que les écrans Gold de
# `research/app.py` continuent de tourner jusqu'à leur archivage — un import qui casse ne rend
# personne plus savant sur une hypothèse réfutée.
from core.cvep_rcca import RCCADecoder, RCCAModel  # noqa: E402,F401  (ré-export)


def make_distinct_codes(n, seed_offset=0):
    """`n` codes Gold DISTINCTS de longueur 63 (pyntbci). Intercorrélation bornée -> séparables.

    Les codes Gold forment une famille où toutes les paires ont une intercorrélation basse, ce
    qui est exactement la propriété voulue pour des cibles à codes différents. ⚠️ Le produit ne
    les affiche plus : cf. la docstring du module.
    """
    import pyntbci.stimulus as st
    gold = np.asarray(st.make_gold_codes())          # (63, 63), valeurs 0/1
    if n > gold.shape[0]:
        raise ValueError(f"{n} codes demandés, {gold.shape[0]} disponibles")
    return gold[seed_offset:seed_offset + n].astype(int)


def build_targets_rcca(n=None):
    """Plan de cibles à CODES DISTINCTS : géométrie + joystick (cvep_targets) + un code Gold par
    cible. Retourne (plan, codes). Chaque cible porte `code` (pour l'affichage) et `idx`."""
    from core.config import CVEP_N_TARGETS, cvep_targets
    n = CVEP_N_TARGETS if n is None else int(n)
    geom = cvep_targets(n)                       # name, angle, jx, jy (même géométrie que le c-VEP classique)
    codes = make_distinct_codes(n)
    plan = [{**g, "code": codes[i].tolist(), "idx": i} for i, g in enumerate(geom)]
    return plan, codes


def calibrate_rcca(app, cycles=None, save_path=CVEP_RCCA_MODEL_PATH):
    """Calibration du mode rCCA + codes distincts. Reprend le protocole c-VEP classique (fixer
    chaque cible en blocs entrelacés) mais chaque cible affiche SON code, et on ajuste un rCCA.

    Réutilise les helpers éprouvés de cvep_calibrate (briefing, blocs mélangés, rendu, garde-fous)
    pour ne pas diverger du protocole validé. Retourne (ok, cv_loo|None).
    """
    import time
    from core.config import CVEP_CAL_BLOCKS, CVEP_CAL_CYCLES
    from research.cvep_calibrate import (_briefing, _draw, _make_blocks, _wilson_hi,  # noqa: E402
                                EARLY_ITR_MIN, SETTLE_CYCLES)
    from research.itr import itr as _itr
    from research.ui import Abort

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


# --- Autotest sur c-VEP synthétique à codes distincts (aucun casque) ---------

def _vep_kernel(fs, dur=0.18):
    t = np.arange(int(dur * fs)) / fs
    return np.sin(2 * np.pi * t / dur) * np.exp(-t / (dur / 2))


def _synth(code_up, n_ch, fs, snr_db, rng, latency_s=0.06):
    n = len(code_up)
    drive = 2.0 * code_up - 1.0
    resp = np.convolve(drive, _vep_kernel(fs), "full")[:n]
    resp = np.roll(resp, int(round(latency_s * fs)))
    sig = np.outer(resp, rng.uniform(0.4, 1.0, n_ch))
    p = np.mean(sig ** 2) / (10 ** (snr_db / 10))
    return sig + rng.normal(0.0, np.sqrt(p), sig.shape)


def _demo(n_targets=6, n_ch=4, fs=FS_UNICORN, refresh=60.0, n_cal=12, n_test=48, seed=0):
    rng = np.random.default_rng(seed)
    codes = make_distinct_codes(n_targets)
    plan = [{"name": f"C{i+1}"} for i in range(n_targets)]
    model = RCCAModel(codes, fs=fs, refresh=refresh, channels=list(range(n_ch)))
    stim = model._stimulus()
    print(f"rCCA + codes distincts : {n_targets} codes Gold L={model.code_len} "
          f"cycle={model.code_len/refresh:.2f}s voies={n_ch}")

    for snr in (-6.0, -10.0, -14.0):
        ep = [_synth(stim[c], n_ch, fs, snr, rng) for c in range(n_targets) for _ in range(n_cal)]
        y = [c for c in range(n_targets) for _ in range(n_cal)]
        model = RCCAModel(codes, fs=fs, refresh=refresh, channels=list(range(n_ch))).fit(ep, y)
        dec = RCCADecoder(model, plan, n_cycles=1)
        ok = 0
        for _ in range(n_test):
            c = int(rng.integers(n_targets))
            w = _synth(stim[c], n_ch, fs, snr, rng)
            ok += int(np.argmax(model.scores(w, 0, 1)) == c)
        print(f"SNR {snr:+5.1f} dB | LOO {model.cv_*100:5.1f}% | argmax {ok/n_test*100:5.1f}% "
              f"(hasard {100/n_targets:.0f}%)")

    # Phase glissante : décodage hors frontière de cycle (le recalage doit compenser).
    #
    # ⚠️ Le `-` du `np.roll` ci-dessous était un `+`, et il CACHAIT un vrai défaut : le `scores`
    # d'origine recalait dans le mauvais sens, et cette ligne fabriquait sa fenêtre dans le
    # mauvais sens aussi — les deux erreurs s'annulaient ici, et seulement ici. Le pilotage en
    # ligne (`research/app.py::_cvep_decode`), lui, note à des phases quelconques avec la
    # convention de l'eCCA, donc à travers un alignement retourné. Le défaut a survécu parce que
    # cette ligne IMPRIME son résultat sans jamais l'affirmer. La convention, désormais commune
    # aux deux décodeurs : une fenêtre « à la phase p » est le signal AVANCÉ de p frames, donc
    # `np.roll(..., -shift(p))` (cf. `cvep_decoder._demo`, même geste).
    ep = [_synth(stim[c], n_ch, fs, -8.0, rng) for c in range(n_targets) for _ in range(n_cal)]
    model = RCCAModel(codes, fs=fs, refresh=refresh, channels=list(range(n_ch))).fit(
        ep, [c for c in range(n_targets) for _ in range(n_cal)])
    hits, phases = 0, range(0, model.code_len, 9)
    for p in phases:
        c = int(rng.integers(n_targets))
        w = np.roll(_synth(stim[c], n_ch, fs, -8.0, rng), -model._shift(p), axis=0)
        hits += int(np.argmax(model.scores(w, p, 1)) == c)
    print(f"\nPhase glissante : {hits}/{len(list(phases))} correct (recalage OK si ≈ tout)")

    # Persistance : save + reload + re-décode.
    #
    # ⚠️ Dans un dossier TEMPORAIRE, nettoyé dans un `finally`. Cette ligne écrivait
    # `data/cvep_rcca_smoke.npz` puis l'effaçait — sauf si l'autotest était interrompu, auquel cas
    # le fichier restait. `data/` porte les enregistrements EEG d'une personne identifiable sur un
    # dépôt PUBLIC : aucun test n'y écrit, même une seconde, même en promettant d'effacer. (Et
    # `git status` ne l'aurait jamais signalé : `data/` est entièrement gitignoré.)
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="cvep_rcca_demo_")
    try:
        path = model.save(os.path.join(tmp, "cvep_rcca_smoke.npz"))
        back = RCCAModel.load(path)
        same = np.array_equal(back.codes, model.codes) and back.n_targets == model.n_targets
        print(f"Save/reload : codes identiques={same}, LOO rechargé={back.cv_*100:.0f}%")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return True


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if _demo() else 1)
