"""Décodeur SSVEP par CCA (Canonical Correlation Analysis).

Coeur de la détection : à partir d'une fenetre EEG (T echantillons x C voies occipitales),
on mesure la correlation canonique entre le signal et des sinus de reference construits à
chaque frequence cible (fondamentale + harmoniques). La cible la mieux correlee = la
frequence fixee du regard. Methode STANDARD du SSVEP, **sans entrainement**.

    fenetre EEG ---CCA vs {15,12,10,8.57 Hz}---> rho par frequence ---argmax---> commande
                                                (+ seuil : sous le seuil = "rien fixe")

Ce module ne depend PAS du casque : il est valide ici sur signal SYNTHETIQUE (faux SSVEP
+ bruit) pour derisquer l'algo avant de brancher l'Unicorn. Demain, `window` viendra de
BrainFlow (voies PO7/Oz/PO8) au lieu du generateur synthetique.

Reference : Lin et al. 2007, "Frequency Recognition Based on CCA for SSVEP-Based BCIs",
IEEE TBME. https://doi.org/10.1109/TBME.2006.889197

Lancer la validation :
    python src/cca_decoder.py
"""

import os
import sys

import numpy as np

# Permet `from config import ...` en script (`python src/cca_decoder.py`) ou en import.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (BANDPASS, FS_UNICORN, MARGIN, N_HARMONICS, RHO_MIN, Z_MARGIN,  # noqa: E402
                    Z_MIN, choose_frequencies, use_utf8_console)


def reference_signals(freq, n_samples, fs=FS_UNICORN, n_harmonics=2, max_freq=None):
    """Matrice de reference (n_samples x 2*n_utiles) : sin/cos de la fondamentale et de ses
    harmoniques. Les harmoniques comptent car le SSVEP en contient beaucoup.

    ⚠️ Les harmoniques au-dessus de `max_freq` (borne haute du passe-bande d'acquisition) sont
    OMISES : le signal ne les contient plus, donc les inclure n'ajoute que des dimensions de
    BRUIT a la reference. Comme la correlation canonique ne peut que croitre quand on agrandit
    l'espace de reference, ca donne a cette frequence-la de la liberte d'ajustement sans
    contrepartie -> rho gonfle par du bruit, et asymetrie entre cibles.
    Concretement avec BANDPASS=(5,40) et N_HARMONICS=3 : 8.57 et 12 Hz gardaient leurs 3
    harmoniques, mais 15 Hz voyait sa 3e (45 Hz) filtree en amont tout en restant dans sa
    reference. C'est le miroir du bug de 2026-07-17 (passe-bande 5-30 qui affamait 12/15 Hz) :
    on avait elargi la bande sans rendre le nombre d'harmoniques adaptatif.
    """
    t = np.arange(n_samples) / fs
    limit = min(fs / 2.0, max_freq if max_freq else fs / 2.0)
    cols = []
    for h in range(1, n_harmonics + 1):
        if h > 1 and h * freq > limit:   # la fondamentale est toujours gardee (garde-fou)
            break
        cols.append(np.sin(2 * np.pi * h * freq * t))
        cols.append(np.cos(2 * np.pi * h * freq * t))
    return np.column_stack(cols)


def usable_harmonics(freq, n_harmonics=N_HARMONICS, max_freq=None, fs=FS_UNICORN):
    """Nombre d'harmoniques reellement dans la bande, pour cette frequence."""
    limit = min(fs / 2.0, max_freq if max_freq else fs / 2.0)
    return max(1, sum(1 for h in range(1, n_harmonics + 1) if h * freq <= limit))


def canonical_correlation(X, Y, reg=1e-8):
    """Plus grande correlation canonique entre X (T x p) et Y (T x q).

    Forme close : rho^2 = plus grande valeur propre de Cxx^-1 Cxy Cyy^-1 Cyx.
    `reg` regularise les matrices de covariance (inversibilite / stabilite numerique).
    """
    X = X - X.mean(axis=0)
    Y = Y - Y.mean(axis=0)
    Cxx = X.T @ X + reg * np.eye(X.shape[1])
    Cyy = Y.T @ Y + reg * np.eye(Y.shape[1])
    Cxy = X.T @ Y
    M = np.linalg.solve(Cxx, Cxy) @ np.linalg.solve(Cyy, Cxy.T)
    eigvals = np.linalg.eigvals(M)
    rho2 = np.max(np.real(eigvals))
    return float(np.sqrt(np.clip(rho2, 0.0, 1.0)))


class CCADecoder:
    """Décodeur SSVEP CCA pour un jeu fixe de frequences cibles.

    Parametres de décision (à affiner sur EEG reel demain) :
      rho_min : correlation mini du gagnant pour accepter une detection.
      margin  : ecart mini entre rho du 1er et du 2e (evite les faux positifs ambigus).
    Si l'un des deux n'est pas satisfait -> classify() renvoie freq=None ("rien fixe").
    """

    def __init__(self, freqs, fs=FS_UNICORN, n_harmonics=N_HARMONICS, rho_min=RHO_MIN,
                 margin=MARGIN, z_min=Z_MIN, z_margin=Z_MARGIN, max_freq=BANDPASS[1]):
        self.freqs = list(freqs)
        self.fs = fs
        self.n_harmonics = n_harmonics
        self.max_freq = max_freq   # borne haute du passe-bande : au-dela, plus de signal
        self.rho_min = rho_min
        self.margin = margin
        self.z_min = z_min
        self.z_margin = z_margin
        self.baseline = None  # {freq: (mu, sigma)} mesure du repos -> decision sur z
        self._ref_cache = {}  # (freq, n_samples) -> matrice de reference

    def fit_baseline(self, samples, min_samples=10):
        """Apprend le plancher de bruit par frequence depuis des fenetres de REPOS.

        `samples` : liste de dicts {freq: rho} mesures pendant que les cibles clignotent
        mais qu'on ne fixe RIEN. Une fois appele, `classify` decide sur z=(rho-mu)/sigma :
        chaque cible est jugee par rapport a SON propre bruit, pas a un seuil commun.
        """
        if len(samples) < min_samples:
            return False
        self.baseline = {}
        for f in self.freqs:
            vals = np.array([s[f] for s in samples], dtype=float)
            self.baseline[f] = (float(vals.mean()), float(max(1e-3, vals.std())))
        return True

    def z_scores(self, scores):
        """Convertit les rho en ecarts-types au-dessus du bruit de repos (identite si non calibre)."""
        if self.baseline is None:
            return dict(scores)
        return {f: (v - self.baseline[f][0]) / self.baseline[f][1] for f, v in scores.items()}

    @property
    def thresholds(self):
        """(seuil, marge) sur l'echelle effectivement utilisee pour decider."""
        return (self.z_min, self.z_margin) if self.baseline else (self.rho_min, self.margin)

    def _ref(self, freq, n_samples):
        key = (freq, n_samples)
        if key not in self._ref_cache:
            self._ref_cache[key] = reference_signals(freq, n_samples, self.fs,
                                                     self.n_harmonics, self.max_freq)
        return self._ref_cache[key]

    def scores(self, window):
        """rho par frequence pour une fenetre (T x C). Retourne {freq: rho}."""
        window = np.asarray(window, dtype=float)
        if window.ndim == 1:
            window = window[:, None]
        n = window.shape[0]
        return {f: canonical_correlation(window, self._ref(f, n)) for f in self.freqs}

    def classify(self, window):
        """Retourne (freq_detectee|None, dict_scores_DE_DECISION).

        Les scores rendus sont ceux qui ont servi a decider : rho brut, ou z si un plancher
        de repos a ete appris (`fit_baseline`) — l'affichage montre ainsi ce qui decide.
        freq=None signifie "aucune cible fixee de facon fiable" -> le robot s'arretera
        (on n'envoie pas de commande ; un actionneur a chien de garde s'arrete de lui-meme).
        """
        sc = self.z_scores(self.scores(window))
        lo, mg = self.thresholds
        ranked = sorted(sc.items(), key=lambda kv: kv[1], reverse=True)
        (best_f, best_r) = ranked[0]
        second_r = ranked[1][1] if len(ranked) > 1 else 0.0
        if best_r >= lo and (best_r - second_r) >= mg:
            return best_f, sc
        return None, sc


# --- Validation sur signal synthetique (pas de casque requis) --------------

def synth_ssvep(freq, n_samples, fs=FS_UNICORN, n_channels=3, snr_db=-6.0,
                n_harmonics=2, rng=None):
    """Fabrique une fausse fenetre SSVEP : sinus a `freq` (+harmoniques, phase aleatoire
    par voie) noyes dans du bruit blanc calibre a `snr_db`. SSVEP reel = SNR tres bas."""
    rng = np.random.default_rng() if rng is None else rng
    t = np.arange(n_samples) / fs
    sig = np.zeros((n_samples, n_channels))
    for h in range(1, n_harmonics + 1):
        amp = 1.0 / h  # les harmoniques decroissent
        for c in range(n_channels):
            phase = rng.uniform(0, 2 * np.pi)
            sig[:, c] += amp * np.sin(2 * np.pi * h * freq * t + phase)
    sig_power = np.mean(sig ** 2)
    noise_power = sig_power / (10 ** (snr_db / 10))
    noise = rng.normal(0.0, np.sqrt(noise_power), sig.shape)
    return sig + noise


def _accuracy_table(freqs, fs, window_s, snr_list, n_trials=200, seed=0):
    rng = np.random.default_rng(seed)
    dec = CCADecoder(freqs, fs=fs)
    n = int(round(window_s * fs))
    print(f"\n== Precision argmax (fenetre {window_s:.1f}s = {n} ech., {n_trials} essais/cellule) ==")
    print("SNR(dB) | " + " | ".join(f"{f:>6.2f}Hz" for f in freqs) + " | global")
    for snr in snr_list:
        per_freq, tot_ok, tot = [], 0, 0
        for f_true in freqs:
            ok = 0
            for _ in range(n_trials):
                w = synth_ssvep(f_true, n, fs, snr_db=snr, rng=rng)
                best = max(dec.scores(w).items(), key=lambda kv: kv[1])[0]
                ok += (best == f_true)
            per_freq.append(ok / n_trials)
            tot_ok += ok
            tot += n_trials
        cells = " | ".join(f"{a*100:>6.1f}%" for a in per_freq)
        print(f"{snr:>6.1f}  | {cells} | {tot_ok/tot*100:5.1f}%")


def _threshold_check(freqs, fs, window_s, snr_db=-6.0, n_trials=400, seed=1):
    """Verifie que le seuil separe bien 'cible fixee' de 'rien fixe' (bruit pur)."""
    rng = np.random.default_rng(seed)
    dec = CCADecoder(freqs, fs=fs)
    n = int(round(window_s * fs))

    sig_rho, hit, detected = [], 0, 0
    for _ in range(n_trials):
        f_true = freqs[rng.integers(len(freqs))]
        w = synth_ssvep(f_true, n, fs, snr_db=snr_db, rng=rng)
        f_det, sc = dec.classify(w)
        sig_rho.append(max(sc.values()))
        if f_det is not None:
            detected += 1
            hit += (f_det == f_true)

    noise_rho, false_pos = [], 0
    for _ in range(n_trials):
        w = rng.normal(0.0, 1.0, (n, 3))  # bruit pur = regard nulle part
        f_det, sc = dec.classify(w)
        noise_rho.append(max(sc.values()))
        false_pos += (f_det is not None)

    print(f"\n== Seuil de detection (rho_min={dec.rho_min}, margin={dec.margin}, SNR={snr_db}dB) ==")
    print(f"rho gagnant  signal : moy {np.mean(sig_rho):.3f}  p10 {np.percentile(sig_rho,10):.3f}")
    print(f"rho gagnant  bruit  : moy {np.mean(noise_rho):.3f}  p90 {np.percentile(noise_rho,90):.3f}")
    print(f"detections correctes (signal) : {hit/n_trials*100:5.1f}%  "
          f"(dont {detected/n_trials*100:.1f}% au-dessus du seuil)")
    print(f"faux positifs (bruit pur)     : {false_pos/n_trials*100:5.1f}%  (vise ~0%)")


def _demo():
    # Fréquences reelles a 60 Hz (source unique : config.choose_frequencies)
    freqs = [c["actual_hz"] for c in choose_frequencies(60)]  # 15, 12, 10, 8.571 Hz
    print("Frequences cibles :", ", ".join(f"{f:.3f}" for f in freqs), "Hz")
    print("Echantillonnage    :", FS_UNICORN, "Hz (Unicorn)")

    # Effet de la longueur de fenetre (compromis reactivite <-> precision)
    for win_s in (1.0, 2.0):
        _accuracy_table(freqs, FS_UNICORN, win_s,
                        snr_list=[0.0, -3.0, -6.0, -9.0, -12.0], n_trials=200)
    _threshold_check(freqs, FS_UNICORN, window_s=2.0, snr_db=-6.0)


if __name__ == "__main__":
    use_utf8_console()
    _demo()
