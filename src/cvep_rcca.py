"""c-VEP variante rCCA + CODES DISTINCTS (2e mode c-VEP, exploration).

Différence avec le c-VEP classique (`cvep_decoder.py`) :
  - classique : UNE m-séquence, décalée circulairement (lags). Notre eCCA apprend un template
    partagé -> déjà maximalement efficace en données ; rCCA n'y gagne rien (mesuré 2026-07-21).
  - ICI : chaque cible a un CODE GOLD DIFFÉRENT (intercorrélation basse), et on décode par
    RECONVOLUTION (rCCA de pyntbci) : on apprend une courte réponse transitoire, commune à tous
    les codes, qui se transfère de l'un à l'autre. C'est LE cas où la reconvolution peut payer.

pyntbci (BSD-3) est isolé dans CE fichier : le reste de l'appli ne le voit pas. Le modèle stocke
les époques de calibration et RÉ-ENTRAÎNE rCCA au chargement (fit < 1 s), ce qui évite de
sérialiser un objet pyntbci et garde les données pour ré-analyse.

    python src/cvep_rcca.py     # autotest sur c-VEP synthétique à codes distincts (aucun casque)
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (CVEP_BAND, CVEP_CHANNELS, CVEP_RCCA_CORR_MIN,  # noqa: E402
                    CVEP_RCCA_ENC, CVEP_RCCA_EVENT, CVEP_RCCA_MARGIN,
                    CVEP_RCCA_MODEL_PATH, FS_UNICORN, use_utf8_console)
from cvep_decoder import bandpass  # noqa: E402  (passe-bande zéro-phase partagé)


def make_distinct_codes(n, seed_offset=0):
    """`n` codes Gold DISTINCTS de longueur 63 (pyntbci). Intercorrélation bornée -> séparables.

    Les codes Gold forment une famille où toutes les paires ont une intercorrélation basse, ce
    qui est exactement la propriété voulue pour des cibles à codes différents.
    """
    import pyntbci.stimulus as st
    gold = np.asarray(st.make_gold_codes())          # (63, 63), valeurs 0/1
    if n > gold.shape[0]:
        raise ValueError(f"{n} codes demandés, {gold.shape[0]} disponibles")
    return gold[seed_offset:seed_offset + n].astype(int)


class RCCAModel:
    """Modèle rCCA (reconvolution) sur codes distincts. Interface calquée sur CVEPModel."""

    def __init__(self, codes, fs=FS_UNICORN, refresh=60.0, band=CVEP_BAND,
                 channels=None, event=CVEP_RCCA_EVENT, enc=CVEP_RCCA_ENC):
        self.codes = np.asarray(codes, dtype=int)         # (n_targets, code_len)
        self.fs = float(fs)
        self.refresh = float(refresh)
        self.code_len = int(self.codes.shape[1])
        self.band = tuple(band)
        self.channels = list(CVEP_CHANNELS if channels is None else channels)
        self.event = event
        self.enc = float(enc)
        self.clf = None          # classifieur pyntbci rCCA (ré-entraîné au besoin)
        self.cv_ = None
        self._epochs = None      # époques de calibration conservées (pour save/refit)
        self._labels = None

    @property
    def n_targets(self):
        return int(self.codes.shape[0])

    @property
    def n_cyc(self):
        """Longueur d'un cycle en échantillons EEG (63 frames @60Hz -> 262 éch.)."""
        return int(round(self.code_len * self.fs / self.refresh))

    def _shift(self, frames):
        return int(round(frames * self.fs / self.refresh)) % self.n_cyc

    def _stimulus(self):
        """(n_targets, n_cyc) : chaque code suréchantillonné du refresh à fs, sur un cycle."""
        frame = (np.arange(self.n_cyc) * self.refresh / self.fs).astype(int) % self.code_len
        return self.codes[:, frame].astype(float)

    def _fit_clf(self, X, y):
        from pyntbci.classifiers import rCCA
        clf = rCCA(stimulus=self._stimulus(), fs=self.fs, event=self.event,
                   encoding_length=self.enc, onset_event=True)
        clf.fit(X, y)
        return clf

    def fit(self, epochs, labels, compute_cv=True):
        """epochs : liste de (n_cyc x n_ch) BRUTES, DÉJÀ réduites aux voies (comme CVEPModel :
        c'est l'appelant qui sélectionne `channels`). labels : index de cible (0..n_targets-1).

        `compute_cv=False` saute le leave-one-out interne (N ré-entraînements) : indispensable
        au CHARGEMENT (cv_ est déjà stocké) et quand un appelant fait lui-même sa validation
        croisée — sinon chaque fit relance un LOO complet et l'entrée du mode traîne plusieurs s.
        """
        self._epochs = [np.asarray(e, float) for e in epochs]
        self._labels = np.asarray(labels, dtype=int)
        X = np.stack([bandpass(e, self.fs, self.band).T
                      for e in self._epochs])           # (n_trials, n_ch, n_cyc)
        self.clf = self._fit_clf(X, self._labels)
        if compute_cv:
            self.cv_ = self._loo(X, self._labels)
        return self

    def _loo(self, X, y):
        if len(X) < 3 or len(set(y.tolist())) < 2:
            return None
        ok = 0
        for i in range(len(X)):
            tr = [j for j in range(len(X)) if j != i]
            clf = self._fit_clf(X[tr], y[tr])
            ok += int(np.ravel(clf.predict(X[i:i + 1]))[0] == y[i])
        return ok / len(X)

    # --- décodage en ligne ----------------------------------------------
    def _fold(self, window, n_cycles):
        w = np.asarray(window, float)
        k = max(1, min(int(n_cycles), len(w) // self.n_cyc))
        return w[-k * self.n_cyc:].reshape(k, self.n_cyc, -1).mean(axis=0)

    def scores(self, window, phase, n_cycles=1):
        """Scores par cible (n_targets,) pour une fenêtre BRUTE se terminant « maintenant ».

        On filtre, on moyenne les `n_cycles` derniers cycles, on RECALE sur la phase 0 du code
        (les codes distincts démarrent tous ensemble à la frame 0), puis rCCA note chaque cible.
        """
        avg = self._fold(bandpass(window, self.fs, self.band), n_cycles)   # (n_cyc x n_ch) déjà réduit
        aligned = np.roll(avg, -self._shift(phase), axis=0)
        X = aligned.T[None]                               # (1, n_ch, n_cyc)
        return np.ravel(self.clf.decision_function(X))    # (n_targets,)

    # --- persistance : on stocke les données et on ré-entraîne au chargement ---
    def save(self, path=CVEP_RCCA_MODEL_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.savez(path, codes=self.codes, epochs=np.asarray(self._epochs),
                 labels=self._labels, fs=self.fs, refresh=self.refresh,
                 band=np.asarray(self.band), channels=np.asarray(self.channels, dtype=int),
                 event=self.event, enc=self.enc,
                 cv=(-1.0 if self.cv_ is None else self.cv_))
        return path

    @classmethod
    def load(cls, path=CVEP_RCCA_MODEL_PATH):
        d = np.load(path, allow_pickle=True)
        m = cls(codes=d["codes"], fs=float(d["fs"]), refresh=float(d["refresh"]),
                band=tuple(d["band"]), channels=[int(c) for c in d["channels"]],
                event=str(d["event"]), enc=float(d["enc"]))
        m.fit([e for e in d["epochs"]], d["labels"], compute_cv=False)   # refit rapide (pas de LOO)
        m.cv_ = None if float(d["cv"]) < 0 else float(d["cv"])           # cv_ déjà mesuré à la calib
        return m


class RCCADecoder:
    """Applique RCCAModel au plan de cibles + rejet (« rien fixé » -> None). Calqué sur CVEPDecoder."""

    def __init__(self, model, plan, corr_min=CVEP_RCCA_CORR_MIN, margin=CVEP_RCCA_MARGIN,
                 n_cycles=1):
        self.model = model
        self.plan = plan                                  # cibles, dans l'ordre des codes
        self.corr_min = corr_min
        self.margin = margin
        self.n_cycles = n_cycles

    def classify(self, window, phase):
        sc = self.model.scores(window, phase, self.n_cycles)
        named = {self.plan[i]["name"]: float(sc[i]) for i in range(len(self.plan))}
        order = np.argsort(sc)[::-1]
        best, second = float(sc[order[0]]), float(sc[order[1]]) if len(sc) > 1 else 0.0
        if best >= self.corr_min and (best - second) >= self.margin:
            return self.plan[int(order[0])], named
        return None, named


def build_targets_rcca(n=None):
    """Plan de cibles à CODES DISTINCTS : géométrie + joystick (cvep_targets) + un code Gold par
    cible. Retourne (plan, codes). Chaque cible porte `code` (pour l'affichage) et `idx`."""
    from config import CVEP_N_TARGETS, cvep_targets
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
    from config import CVEP_CAL_BLOCKS, CVEP_CAL_CYCLES
    from cvep_calibrate import (_briefing, _draw, _make_blocks, _wilson_hi,  # noqa: E402
                                EARLY_ITR_MIN, SETTLE_CYCLES)
    from itr import itr as _itr
    from ui import Abort

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

    # phase glissante : décodage hors frontière de cycle (le recalage doit compenser)
    ep = [_synth(stim[c], n_ch, fs, -8.0, rng) for c in range(n_targets) for _ in range(n_cal)]
    model = RCCAModel(codes, fs=fs, refresh=refresh, channels=list(range(n_ch))).fit(
        ep, [c for c in range(n_targets) for _ in range(n_cal)])
    hits, phases = 0, range(0, model.code_len, 9)
    for p in phases:
        c = int(rng.integers(n_targets))
        w = np.roll(_synth(stim[c], n_ch, fs, -8.0, rng), model._shift(p), axis=0)
        hits += int(np.argmax(model.scores(w, p, 1)) == c)
    print(f"\nPhase glissante : {hits}/{len(list(phases))} correct (recalage OK si ≈ tout)")

    # persistance : save + reload + re-décode
    path = model.save(os.path.join(os.path.dirname(CVEP_RCCA_MODEL_PATH), "cvep_rcca_smoke.npz"))
    back = RCCAModel.load(path)
    os.remove(path)
    same = np.array_equal(back.codes, model.codes) and back.n_targets == model.n_targets
    print(f"Save/reload : codes identiques={same}, LOO rechargé={back.cv_*100:.0f}%")
    return True


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if _demo() else 1)
