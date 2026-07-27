"""Décodeur P300 (oddball) : xDAWN + covariances riemanniennes + LR — SÉLECTION discrète.

Le P300 est une onde POSITIVE ~300 ms après un stimulus rare et ATTENDU (compté). On fait
clignoter les cibles une à une ; l'utilisateur fixe+compte celle qu'il veut ; son flash est
l'"oddball" -> P300. Le décodeur classe chaque époque de flash « cible / non-cible », puis pour
une SÉLECTION agrège les scores de chaque cible sur ses répétitions et prend l'argmax.

Pourquoi xDAWN + Riemann (pyriemann) et pas du fait-maison : c'est l'état de l'art du P300 à peu
de voies / peu d'essais, et c'est déjà installé (rien à recoder). xDAWN apprend des filtres
spatiaux qui maximisent le rapport (réponse évoquée)/(bruit) ; l'espace tangent riemannien +
LR fait un classifieur robuste. Voir Rivet et al. 2009 (xDAWN), Barachant/Congedo (Riemann-P300).

Étapes du signal, dans l'ordre :
  onset flash -> époque [-pre, +post] (via timestamp, cf. acquisition.get_raw) -> correction de
  ligne de base (moyenne pré-stimulus) -> passe-bande ERP (1-12 Hz) -> xDAWN+Riemann.

Validé ici sur P300 SYNTHÉTIQUE (pas de casque).   python src/research/p300_decoder.py
"""

import os
import sys

import joblib
import numpy as np
from scipy.signal import butter, filtfilt
from sklearn.base import clone
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (P300_BAND, P300_EPOCH_S, P300_PRE_S, P300_XDAWN_NFILTER,  # noqa: E402
                    use_utf8_console)

TARGET, NONTARGET = 1, 0


def bandpass(x, fs, band=P300_BAND, order=4):
    """Filtre 0-phase (filtfilt) le long du temps. x : (..., n_samples)."""
    lo, hi = band
    b, a = butter(order, [lo / (fs / 2), hi / (fs / 2)], btype="band")
    return filtfilt(b, a, np.asarray(x, dtype=float), axis=-1)


def epoch_from_stream(eeg, ts, flash_ts, fs, pre_s=P300_PRE_S, post_s=P300_EPOCH_S):
    """Découpe l'époque [flash_ts - pre_s, flash_ts + post_s] dans un flux (eeg (n,ch), ts (n,)).

    `ts` = canal timestamp BrainFlow (temps Unix par échantillon) -> alignement SANS dérive
    d'horloge, même sur une longue calibration. Retourne (n_pre+n_post, ch) ou None si l'époque
    déborde du flux enregistré."""
    n_pre, n_post = int(round(pre_s * fs)), int(round(post_s * fs))
    idx = int(np.searchsorted(ts, flash_ts))     # 1er échantillon à/après l'onset
    i0, i1 = idx - n_pre, idx + n_post
    if i0 < 0 or i1 > len(ts):
        return None
    return np.asarray(eeg[i0:i1], dtype=float)


def build_pipe(nfilter=P300_XDAWN_NFILTER):
    """xDAWN (covariances) -> espace tangent -> régression logistique. Import paresseux de
    pyriemann pour ne pas le charger si le mode P300 n'est pas utilisé."""
    from pyriemann.estimation import XdawnCovariances
    from pyriemann.tangentspace import TangentSpace
    return Pipeline([
        ("xdawn", XdawnCovariances(nfilter=nfilter, estimator="lwf", xdawn_estimator="scm")),
        ("ts", TangentSpace()),
        ("lr", LogisticRegression(max_iter=1000, class_weight="balanced")),
    ])


class P300Model:
    """Pipeline entraînable (xDAWN+Riemann+LR) + (dé)sérialisation. `cv_auc_` = AUC par manche."""

    def __init__(self, fs=250.0, band=P300_BAND, pre_s=P300_PRE_S, post_s=P300_EPOCH_S,
                 nfilter=P300_XDAWN_NFILTER):
        self.fs = fs
        self.band = band
        self.pre_s = pre_s
        self.post_s = post_s
        self.nfilter = nfilter
        self.pipe = build_pipe(nfilter)
        self.cv_auc_ = None

    def _prep(self, epochs):
        """(n_trials, n_samp, n_ch) [ou (n_samp, n_ch)] -> correction de base + passe-bande ->
        (n_trials, n_ch, n_samp) attendu par pyriemann."""
        X = np.asarray(epochs, dtype=float)
        if X.ndim == 2:
            X = X[None]
        n_pre = int(round(self.pre_s * self.fs))
        if n_pre > 0:
            X = X - X[:, :n_pre, :].mean(axis=1, keepdims=True)   # ligne de base pré-stimulus
        X = np.transpose(X, (0, 2, 1))                            # -> (n_trials, n_ch, n_samp)
        return bandpass(X, self.fs, self.band)

    def fit(self, epochs, y, groups=None, compute_cv=True):
        Xf, y = self._prep(epochs), np.asarray(y).astype(int)
        self.cv_auc_ = None
        if compute_cv and len(np.unique(y)) == 2 and len(y) >= 10:
            self.cv_auc_ = self._cv_auc(Xf, y, groups)
        self.pipe.fit(Xf, y)
        return self

    def _cv_auc(self, Xf, y, groups):
        """AUC honnête : GroupKFold par manche si `groups` fourni (aucune fuite d'époques d'une
        même manche entre train et test), sinon StratifiedKFold."""
        from sklearn.model_selection import (GroupKFold, StratifiedKFold,  # noqa: E402
                                             cross_val_score)
        try:
            if groups is not None:
                k = min(5, len(np.unique(groups)))
                sc = cross_val_score(clone(self.pipe), Xf, y, groups=groups,
                                     cv=GroupKFold(k), scoring="roc_auc")
            else:
                sc = cross_val_score(clone(self.pipe), Xf, y,
                                     cv=StratifiedKFold(5, shuffle=True, random_state=0),
                                     scoring="roc_auc")
            return float(np.mean(sc))
        except Exception as e:  # noqa: BLE001 - l'AUC est indicative, ne doit pas bloquer le fit
            print(f"[p300] AUC CV non calculée : {e}")
            return None

    def scores(self, epochs):
        """Score « cible » par époque (log-odds LR = decision_function : additif sur les répétitions)."""
        return self.pipe.decision_function(self._prep(epochs))

    def select(self, epochs_by_target, margin=0.0):
        """Agrège les scores de chaque cible sur ses répétitions -> (nom_choisi|None, {nom: score}).
        margin > 0 : refuse la sélection si l'écart 1er-2e est trop faible (ambiguë -> None)."""
        means = {nm: float(np.mean(self.scores(np.asarray(eps))))
                 for nm, eps in epochs_by_target.items()}
        order = sorted(means, key=means.get, reverse=True)
        if margin > 0 and len(order) > 1 and means[order[0]] - means[order[1]] < margin:
            return None, means
        return order[0], means

    def save(self, path):
        joblib.dump(self, path)

    @staticmethod
    def load(path):
        return joblib.load(path)


# --- Validation sur P300 SYNTHÉTIQUE (pas de casque requis) -----------------

def synth_p300_epoch(is_target, fs=250.0, pre_s=P300_PRE_S, post_s=P300_EPOCH_S,
                     amp=1.6, noise=1.0, rng=None):
    """Époque synthétique (n_samp, 8). Cible = bosse POSITIVE ~300 ms (P300) + petit N200,
    pondérée sur la ligne médiane Fz/Cz/Pz (indices 0,2,4). Non-cible = même bruit, sans bosse.
    Alpha ~10 Hz partagé pour un fond réaliste (le P300 doit émerger malgré lui)."""
    rng = np.random.default_rng() if rng is None else rng
    n_pre, n_post = int(round(pre_s * fs)), int(round(post_s * fs))
    n = n_pre + n_post
    t = (np.arange(n) - n_pre) / fs                       # temps depuis l'onset (s)
    X = rng.normal(0.0, noise, (n, 8))
    X += (0.8 * np.sin(2 * np.pi * 10 * t + rng.uniform(0, 2 * np.pi)))[:, None]  # alpha partagé
    if is_target:
        p300 = amp * np.exp(-0.5 * ((t - 0.30) / 0.06) ** 2)     # positivité ~300 ms
        n200 = -0.4 * amp * np.exp(-0.5 * ((t - 0.20) / 0.03) ** 2)
        w = np.zeros(8)
        w[[0, 2, 4]] = [0.7, 1.0, 0.9]                           # Fz, Cz, Pz
        X += (p300 + n200)[:, None] * w[None, :]
    return X


def _synth_dataset(rounds, n_targets, reps, fs, rng, amp=0.7, noise=1.6):
    """Simule une calibration : chaque manche cue une cible, on flashe les N cibles reps fois.
    amp/noise réglés pour un P300 mono-essai FAIBLE (AUC ~90 %, pas trivial) : la sélection ne
    doit réussir que par MOYENNAGE sur les répétitions — le vrai mécanisme du P300.
    Retourne epochs (liste), y (0/1), groups (indice de manche), et cues (par manche)."""
    epochs, y, groups, cues = [], [], [], []
    for r in range(rounds):
        cue = r % n_targets                                  # chaque cible cuée ~également
        cues.append(cue)
        for _ in range(reps):
            for tgt in range(n_targets):
                is_t = (tgt == cue)
                epochs.append(synth_p300_epoch(is_t, fs=fs, amp=amp, noise=noise, rng=rng))
                y.append(TARGET if is_t else NONTARGET)
                groups.append(r)
    return np.asarray(epochs), np.asarray(y), np.asarray(groups), cues


def _demo():
    fs, rounds, n_targets, reps = 250.0, 12, 6, 12
    rng = np.random.default_rng(0)
    epochs, y, groups, cues = _synth_dataset(rounds, n_targets, reps, fs, rng)
    print(f"P300 synthétique : {rounds} manches × {n_targets} cibles × {reps} rép = {len(y)} "
          f"époques ({int(y.sum())} cibles / {int((1 - y).sum())} non-cibles), fs={fs:g} Hz")

    # 1) AUC cible-vs-non-cible, honnête (GroupKFold par manche)
    model = P300Model(fs=fs).fit(epochs, y, groups=groups)
    auc = model.cv_auc_
    print(f"\n[1] AUC cible-vs-non-cible (GroupKFold par manche) : {auc*100:.1f}%  (hasard 50%)")

    # 2) Précision de SÉLECTION en leave-one-round-out (la vraie métrique : trouve-t-on la cible ?)
    ok = 0
    for r in range(rounds):
        tr = groups != r
        m = P300Model(fs=fs).fit(epochs[tr], y[tr], compute_cv=False)
        te = np.where(groups == r)[0]
        by_target = {}
        for i in te:
            # reconstruit l'appartenance cible depuis l'ordre de _synth_dataset
            tgt = int((i - te[0]) % n_targets)
            by_target.setdefault(tgt, []).append(epochs[i])
        pick, _ = m.select(by_target)
        ok += (pick == cues[r])
    sel = ok / rounds
    soa = 0.25
    t_sel = reps * n_targets * soa
    from research.itr import itr as _itr
    print(f"[2] Sélection leave-one-round-out : {ok}/{rounds} = {sel*100:.0f}%  "
          f"(hasard {100/n_targets:.0f}%)")
    print(f"    à {reps} rép × {n_targets} cibles × {soa*1000:.0f} ms = {t_sel:.1f} s/sélection "
          f"-> ITR ~{_itr(n_targets, sel, t_sel):.1f} bits/min")

    good = (auc or 0) > 0.75 and sel >= 0.9
    print(f"\n[p300] pipeline xDAWN+Riemann " + ("validé sur synthétique." if good
          else "à ajuster (AUC>75% et sélection>=90% attendus sur ce synthétique)."))
    return good


if __name__ == "__main__":
    use_utf8_console()
    _demo()
