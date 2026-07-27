"""Décodeur c-VEP : filtre spatial + template appris, corrélation par lag.

Principe (méthode « template matching » standard, Bin et al. 2011) :

  1. CALIBRATION — on fixe des cibles dont on connaît le lag. Chaque cycle enregistré est
     **recalé** sur le code (roll de son lag) : toutes les époques deviennent alors la
     réponse au MÊME code à la phase 0. On les moyenne -> `template`.
  2. FILTRE SPATIAL — une CCA entre les époques et le template donne le vecteur de poids
     `w` qui combine les voies pour maximiser le rapport signal/bruit (l'équivalent appris
     de « prendre PO7/Oz/PO8 » en SSVEP, mais optimisé pour TON cerveau et TON montage).
  3. ONLINE — on projette la fenêtre courante par `w`, et on la corrèle au template décalé
     de chaque lag candidat. Le lag qui corrèle le mieux = la cible fixée.

Convention de phase (partagée avec cvep_code / le stimulus) : la cible de lag L affiche à
la frame f le bit `code[(f + lag) % L]`. Une fenêtre qui démarre à la phase `p` contient
donc la réponse au code à partir de l'indice `p + lag`.

⚠️ La latence constante du casque (Bluetooth + électronique) est absorbée par le template :
elle est présente à la calibration comme en ligne, donc elle s'annule. C'est pour ça que la
calibration et le pilotage DOIVENT utiliser la même chaîne d'alignement.

    python src/research/cvep_decoder.py     # validation sur c-VEP synthétique (aucun casque)
"""

import os
import sys

import numpy as np
from scipy.signal import butter, filtfilt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (CVEP_BAND, CVEP_CHANNELS, CVEP_CORR_MIN,  # noqa: E402
                    CVEP_DECISION_CYCLES, CVEP_MARGIN, CVEP_MODEL_PATH, FS_UNICORN,
                    use_utf8_console)
from research.cvep_code import build_targets, m_sequence  # noqa: E402


def bandpass(x, fs, band=CVEP_BAND, order=4):
    """Passe-bande zéro-phase (filtfilt) sur (n_samp x n_ch). Le zéro-phase est ESSENTIEL
    ici : un filtre à phase non nulle décalerait la réponse et casserait l'alignement."""
    lo, hi = band
    b, a = butter(order, [lo / (fs / 2), min(hi, fs / 2 - 1) / (fs / 2)], btype="band")
    return filtfilt(b, a, np.asarray(x, dtype=float), axis=0)


def cca_weights(X, Y, reg=1e-6):
    """Vecteurs de poids de la 1re paire canonique entre X (T x p) et Y (T x q).

    Même algèbre que `cca_decoder.canonical_correlation`, mais on garde les VECTEURS :
    wx sert de filtre spatial sur l'EEG, wy de filtre sur le template multi-voies.
    """
    X = np.asarray(X, float) - np.mean(X, axis=0)
    Y = np.asarray(Y, float) - np.mean(Y, axis=0)
    Cxx = X.T @ X + reg * np.eye(X.shape[1])
    Cyy = Y.T @ Y + reg * np.eye(Y.shape[1])
    Cxy = X.T @ Y
    M = np.linalg.solve(Cxx, Cxy) @ np.linalg.solve(Cyy, Cxy.T)
    vals, vecs = np.linalg.eig(M)
    k = int(np.argmax(np.real(vals)))
    wx = np.real(vecs[:, k])
    wy = np.linalg.solve(Cyy, Cxy.T @ wx)
    rho = float(np.sqrt(np.clip(np.real(vals[k]), 0.0, 1.0)))
    nx, ny = np.linalg.norm(wx), np.linalg.norm(wy)
    return wx / (nx or 1.0), wy / (ny or 1.0), rho


def _corr(a, b):
    """Corrélation de Pearson, robuste aux signaux plats."""
    a = a - a.mean()
    b = b - b.mean()
    d = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / d) if d > 0 else 0.0


class CVEPModel:
    """Template 1D + filtre spatial, appris à la calibration.

    `template` est indexé par la POSITION DANS LE CODE (0..n_cyc-1, phase 0).
    """

    def __init__(self, fs=FS_UNICORN, refresh=60.0, code_len=63, band=CVEP_BAND,
                 channels=None):
        self.fs = float(fs)
        self.refresh = float(refresh)
        self.code_len = int(code_len)
        self.band = tuple(band)
        # Indices (dans CH_NAMES) des voies sur lesquelles le filtre spatial est appris. On
        # ENREGISTRE toujours les 8, mais on n'en ajuste qu'un sous-ensemble : donner 8 voies à
        # une CCA calibrée sur peu de cycles surapprend (mesuré : 3-4 composantes canoniques
        # font chuter l'accuracy de 41 % à 34 %). Enregistrer tout laisse la porte ouverte à un
        # test hors ligne du meilleur sous-ensemble, sans jamais avoir à refaire une séance.
        self.channels = list(CVEP_CHANNELS if channels is None else channels)
        self.w = None
        self.template = None
        self.cv_ = None
        self.n_targets = 0     # renseigné à la sauvegarde (0 = inconnu)

    # --- géométrie temporelle -------------------------------------------
    @property
    def n_cyc(self):
        """Longueur d'un cycle de code en échantillons EEG (63 frames @60Hz -> 262 ech.)."""
        return int(round(self.code_len * self.fs / self.refresh))

    def _shift(self, frames):
        """Conversion frames -> échantillons (arrondi ; erreur < 1 ech. = 4 ms, sans effet
        car la réponse VEP est lissée sur ~150 ms)."""
        return int(round(frames * self.fs / self.refresh)) % self.n_cyc

    # --- entraînement ----------------------------------------------------
    def _align(self, epoch, lag):
        """Recale une époque enregistrée en fixant la cible `lag` sur la phase 0 du code."""
        return np.roll(epoch, self._shift(lag), axis=0)

    def fit(self, epochs, lags):
        """epochs : liste de (n_cyc x n_ch) BRUTES ; lags : lag (frames) fixé pour chacune."""
        filt = [bandpass(e, self.fs, self.band) for e in epochs]
        aligned = [self._align(e, l) for e, l in zip(filt, lags)]
        self.w, self.template = self._solve(aligned)
        self.cv_ = self._loo(filt, lags)
        return self

    def _solve(self, aligned):
        """CCA entre les époques recalées et leur moyenne -> (filtre spatial, template 1D)."""
        tavg = np.mean(aligned, axis=0)                       # (n_cyc x n_ch)
        Xcat = np.concatenate(aligned, axis=0)
        Ycat = np.tile(tavg, (len(aligned), 1))
        wx, wy, _ = cca_weights(Xcat, Ycat)
        tmpl = tavg @ wy
        return wx, tmpl - tmpl.mean()

    def _loo(self, filt_epochs, lags):
        """Accuracy leave-one-out : le vrai chiffre de mérite de la calibration."""
        uniq = sorted(set(lags))
        if len(filt_epochs) < 3 or len(uniq) < 2:
            return None
        ok = 0
        for i in range(len(filt_epochs)):
            rest = [(e, l) for j, (e, l) in enumerate(zip(filt_epochs, lags)) if j != i]
            w, tmpl = self._solve([self._align(e, l) for e, l in rest])
            sc = self._scores_filtered(filt_epochs[i], 0, uniq, w, tmpl)
            ok += (max(sc, key=sc.get) == lags[i])
        return ok / len(filt_epochs)

    # --- décodage --------------------------------------------------------
    def _scores_filtered(self, window, phase, lags, w=None, tmpl=None):
        """Corrélation par lag pour une fenêtre DÉJÀ filtrée démarrant à la phase `phase`."""
        w = self.w if w is None else w
        tmpl = self.template if tmpl is None else tmpl
        y = np.asarray(window)[:len(tmpl)] @ w
        return {lag: _corr(y, np.roll(tmpl, -self._shift(phase + lag))[:len(y)]) for lag in lags}

    def fold(self, window, n_cycles=None):
        """Moyenne les `n_cycles` derniers cycles de la fenêtre (k cycles -> 1 cycle).

        k*L frames = k périodes exactes du code : tous les cycles de la fenêtre démarrent
        donc à la même phase et se moyennent directement, ce qui gagne ~√k en SNR. C'est le
        levier qui fait passer la 1re calibration réelle de 57% (1 cycle) à 73% (2 cycles).

        `n_cycles` est EXPLICITE et non déduit de la longueur : sinon une fenêtre récupérée
        avec une marge de filtrage ferait silencieusement passer k de 2 à 3, changeant la
        latence de décision sans que rien ne le signale.
        """
        w = np.asarray(window, dtype=float)
        k = max(1, len(w) // self.n_cyc) if n_cycles is None else int(n_cycles)
        k = max(1, min(k, len(w) // self.n_cyc))
        return w[-k * self.n_cyc:].reshape(k, self.n_cyc, -1).mean(axis=0)

    def scores(self, window, phase, lags, n_cycles=None):
        """Corrélation par lag pour une fenêtre BRUTE se TERMINANT « maintenant », dont les
        `n_cycles` derniers cycles démarrent à `phase` (position dans le code, en frames).

        La fenêtre peut être plus longue que n_cycles*n_cyc : le surplus en tête sert de marge
        de filtrage (le transitoire du passe-bande y reste confiné) et est écarté par `fold`.
        On filtre AVANT de replier, pour que la marge joue son rôle.
        """
        return self._scores_filtered(
            self.fold(bandpass(window, self.fs, self.band), n_cycles), phase, lags)

    # --- persistance -----------------------------------------------------
    def save(self, path=CVEP_MODEL_PATH, n_targets=0):
        """`n_targets` : nombre de cibles utilisées à la calibration. Le template est commun à
        tous les lags, donc un modèle à 3 cibles « marche » techniquement à 6 — mais les lags
        supplémentaires n'auront jamais été validés. On le mémorise pour pouvoir prévenir."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.savez(path, w=self.w, template=self.template, fs=self.fs, refresh=self.refresh,
                 code_len=self.code_len, band=np.asarray(self.band), n_targets=int(n_targets),
                 channels=np.asarray(self.channels, dtype=int),
                 cv=(-1.0 if self.cv_ is None else self.cv_))
        return path

    @classmethod
    def load(cls, path=CVEP_MODEL_PATH):
        d = np.load(path)
        m = cls(fs=float(d["fs"]), refresh=float(d["refresh"]),
                code_len=int(d["code_len"]), band=tuple(d["band"]),
                channels=([int(c) for c in d["channels"]] if "channels" in d else None))
        m.w, m.template = d["w"], d["template"]
        m.cv_ = None if float(d["cv"]) < 0 else float(d["cv"])
        m.n_targets = int(d["n_targets"]) if "n_targets" in d else 0   # 0 = modèle antérieur
        return m


class CVEPDecoder:
    """Applique le modèle au plan de cibles + seuil de rejet (« rien fixé » -> stop)."""

    def __init__(self, model, plan, corr_min=CVEP_CORR_MIN, margin=CVEP_MARGIN,
                 n_cycles=CVEP_DECISION_CYCLES):
        self.model = model
        self.plan = plan
        self.lags = [c["lag"] for c in plan]
        self.lag_to_cmd = {c["lag"]: c for c in plan}
        self.corr_min = corr_min
        self.margin = margin
        self.n_cycles = n_cycles

    def classify(self, window, phase):
        """Retourne (commande|None, {nom: corrélation}). None = rien fixé de façon fiable."""
        sc = self.model.scores(window, phase, self.lags, n_cycles=self.n_cycles)
        named = {self.lag_to_cmd[l]["name"]: v for l, v in sc.items()}
        ranked = sorted(sc.items(), key=lambda kv: kv[1], reverse=True)
        best_lag, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        if best >= self.corr_min and (best - second) >= self.margin:
            return self.lag_to_cmd[best_lag], named
        return None, named


# --- Validation sur c-VEP synthétique (aucun casque) ----------------------

def _vep_kernel(fs, dur=0.18):
    """Réponse impulsionnelle VEP grossière : onde biphasique d'environ 180 ms."""
    t = np.arange(int(dur * fs)) / fs
    return np.sin(2 * np.pi * t / dur) * np.exp(-t / (dur / 2))


def synth_cvep(code, lag, n_ch, fs, refresh, snr_db=-10.0, rng=None, latency_s=0.06):
    """Fabrique un cycle de c-VEP : le code (décalé de `lag`) convolué par la réponse VEP,
    projeté sur les voies avec des gains différents, + bruit. `latency_s` simule le retard
    matériel constant que le template doit absorber."""
    rng = np.random.default_rng() if rng is None else rng
    L = len(code)
    n = int(round(L * fs / refresh))
    idx = (np.arange(n) * refresh / fs).astype(int) % L
    drive = 2.0 * code[(idx + lag) % L] - 1.0                  # ±1 à la cadence EEG
    resp = np.convolve(drive, _vep_kernel(fs), mode="full")[:n]
    resp = np.roll(resp, int(round(latency_s * fs)))
    gains = rng.uniform(0.4, 1.0, n_ch)
    sig = np.outer(resp, gains)
    noise_p = np.mean(sig ** 2) / (10 ** (snr_db / 10))
    return sig + rng.normal(0.0, np.sqrt(noise_p), sig.shape)


def _demo(n_ch=4, fs=FS_UNICORN, refresh=60.0, n_cal=10, n_test=40, seed=0):
    rng = np.random.default_rng(seed)
    plan, code = build_targets()
    lags = [c["lag"] for c in plan]
    print(f"Code L={len(code)} @ {refresh:.0f}Hz  cycle={len(code)/refresh:.2f}s  "
          f"voies={n_ch}  lags={lags}")

    for snr in (-6.0, -10.0, -14.0, -18.0):
        epochs = [synth_cvep(code, l, n_ch, fs, refresh, snr, rng)
                  for l in lags for _ in range(n_cal)]
        y = [l for l in lags for _ in range(n_cal)]
        model = CVEPModel(fs=fs, refresh=refresh, code_len=len(code)).fit(epochs, y)
        dec = CVEPDecoder(model, plan)

        ok, emitted, correct = 0, 0, 0
        for _ in range(n_test):
            true = lags[rng.integers(len(lags))]
            w = synth_cvep(code, true, n_ch, fs, refresh, snr, rng)
            sc = model.scores(w, 0, lags)
            ok += (max(sc, key=sc.get) == true)
            cmd, _ = dec.classify(w, 0)
            if cmd is not None:
                emitted += 1
                correct += (cmd["lag"] == true)
        # faux positifs : bruit pur = regard nulle part
        fp = sum(dec.classify(rng.normal(0, 1, (model.n_cyc, n_ch)), 0)[0] is not None
                 for _ in range(n_test))
        print(f"SNR {snr:>6.1f} dB | LOO calib {model.cv_*100:5.1f}% | argmax {ok/n_test*100:5.1f}% "
              f"| avec seuil {correct/n_test*100:5.1f}% émis ({emitted}/{n_test}) "
              f"| faux positifs bruit {fp/n_test*100:4.1f}%")

    # vérifie que la phase glissante est correctement gérée (décodage hors bord de cycle)
    epochs = [synth_cvep(code, l, n_ch, fs, refresh, -10.0, rng) for l in lags for _ in range(n_cal)]
    model = CVEPModel(fs=fs, refresh=refresh, code_len=len(code)).fit(
        epochs, [l for l in lags for _ in range(n_cal)])
    hits = 0
    for p in range(0, len(code), 7):
        true = lags[rng.integers(len(lags))]
        w = np.roll(synth_cvep(code, true, n_ch, fs, refresh, -10.0, rng),
                    -model._shift(p), axis=0)   # fenêtre démarrant à la phase p
        hits += (max(model.scores(w, p, lags), key=lambda k: model.scores(w, p, lags)[k]) == true)
    n_ph = len(range(0, len(code), 7))
    print(f"\nDécodage à phase glissante (hors bord de cycle) : {hits}/{n_ph} correct")
    return True


if __name__ == "__main__":
    use_utf8_console()
    _demo()
