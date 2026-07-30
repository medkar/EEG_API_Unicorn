"""Décodeur Motor Imagery (imagerie motrice) : CSP + LDA, 2 commandes (main gauche/droite)
+ un état REPOS explicite (indispensable pour un « stop » fiable).

Contrairement au SSVEP (CCA, zéro entraînement), le MI doit être ENTRAÎNÉ :
  1. calibration  -> essais EEG étiquetés GAUCHE / DROITE / REPOS   [voir mi_calibrate.py, à venir]
  2. entraînement -> CSP (filtres spatiaux) + LDA                    [MIModel.fit]
  3. online       -> MIModel classe la fenêtre en direct            [MIDecoder.classify]

Pourquoi REPOS comme 3e classe : un classifieur 2 classes choisit TOUJOURS un côté (même sans
imagerie) => faux mouvements au repos. En apprenant « repos », le modèle peut dire « ne rien
faire » -> le robot s'arrête. Le contrôle reste à 2 commandes (REPOS -> None).

Signal : ERD (désynchronisation) mu/beta du cortex moteur — la puissance chute sur l'hémisphère
OPPOSÉ à la main imaginée (main droite -> baisse sur C3 ; main gauche -> sur C4). Le CSP apprend
les filtres spatiaux qui maximisent ce contraste de variance.

Validé ici sur ERD SYNTHÉTIQUE (pas de casque).   python src/research/mi_decoder.py
"""

import os
import sys

import joblib
import numpy as np
from scipy.linalg import eigh
from scipy.signal import butter, filtfilt
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import MI_METHOD, MI_REREF, use_utf8_console  # noqa: E402

MI_BAND = (8.0, 30.0)                       # mu (8-12) + beta (13-30) = rythmes sensorimoteurs
MI_CONTROL = ("GAUCHE", "DROITE")           # commandes réelles
MI_LABELS = ("GAUCHE", "DROITE", "REPOS")   # classes du modèle (REPOS = état neutre)


def reref(epochs, mode=MI_REREF):
    """Re-référencement spatial AVANT le CSP. epochs : (..., n_ch, n_samples).
    "none" -> inchangé ; "car" -> Common Average Reference (soustrait à chaque instant la moyenne
    des voies). Retire le mode commun (dérive/EMG/référence) : indispensable en online, sinon le
    décalage de puissance entre calibration et pilotage bloque le CSP sur une classe au repos.
    Linéaire spatialement -> commute avec le passe-bande temporel (ordre indifférent)."""
    if mode in ("none", None):
        return epochs
    if mode == "car":
        x = np.asarray(epochs, dtype=float)
        return x - x.mean(axis=-2, keepdims=True)
    raise ValueError(f"re-ref MI inconnu : {mode!r} (attendu 'none' ou 'car')")


def bandpass(epochs, fs, band=MI_BAND, order=4):
    """Filtre 0-phase (filtfilt) le long du temps. epochs : (..., n_samples)."""
    lo, hi = band
    b, a = butter(order, [lo / (fs / 2), hi / (fs / 2)], btype="band")
    return filtfilt(b, a, np.asarray(epochs, dtype=float), axis=-1)


class CSP(BaseEstimator, TransformerMixin):
    """Common Spatial Patterns multiclasse (one-vs-rest). Pour chaque classe, apprend des
    filtres spatiaux maximisant/minimisant sa variance vs le reste ; features = log-variance.
    Compatible scikit-learn (Pipeline / cross_val_score)."""

    def __init__(self, n_per_class=2, reg=1e-6):
        self.n_per_class = n_per_class
        self.reg = reg

    def _cov(self, X):
        acc = np.zeros((X.shape[1], X.shape[1]))
        for E in X:
            C = E @ E.T
            tr = np.trace(C)
            if tr > 0:
                acc += C / tr
        return acc / len(X)

    def fit(self, X, y):  # X : (n_trials, n_ch, n_samples)
        y = np.asarray(y)
        self.classes_ = np.unique(y)
        eye = self.reg * np.eye(X.shape[1])
        filt = []
        for c in self.classes_:
            c_pos, c_neg = self._cov(X[y == c]), self._cov(X[y != c])
            evals, evecs = eigh(c_pos + eye, c_pos + c_neg + 2 * eye)
            evecs = evecs[:, np.argsort(evals)]
            m = self.n_per_class
            filt.append(evecs[:, :m].T)     # variance MINI pour c (capte l'ERD)
            filt.append(evecs[:, -m:].T)     # variance MAXI pour c
        self.filters_ = np.vstack(filt)      # (2*m*n_classes, n_ch)
        return self

    def transform(self, X):
        out = []
        for E in X:
            Z = self.filters_ @ E
            v = np.clip(np.var(Z, axis=1), 1e-12, None)
            out.append(np.log(v / v.sum()))
        return np.asarray(out)


def build_pipe(method=MI_METHOD, n_per_class=2):
    """Pipeline de classification MI. 'csp' = CSP+LDA ; 'riemann' = covariances + espace
    tangent + régression logistique (géométrie riemannienne : robuste, efficace avec peu
    de données — recommandé)."""
    if method == "csp":
        return Pipeline([("csp", CSP(n_per_class)),
                         ("lda", LinearDiscriminantAnalysis())])
    if method == "riemann":
        from pyriemann.estimation import Covariances
        from pyriemann.tangentspace import TangentSpace
        from sklearn.linear_model import LogisticRegression
        return Pipeline([("cov", Covariances(estimator="oas")),
                         ("ts", TangentSpace()),
                         ("lr", LogisticRegression(max_iter=1000))])
    raise ValueError(f"méthode MI inconnue : {method!r} (attendu 'csp' ou 'riemann')")


class MIModel:
    """Pipeline entraînable (CSP+LDA ou Riemannien) + (dé)sérialisation. `cv_` = accuracy CV."""

    def __init__(self, labels=MI_LABELS, fs=250.0, band=MI_BAND, method=MI_METHOD,
                 n_per_class=2, reref_mode=MI_REREF):
        self.labels = list(labels)
        self.fs = fs
        self.band = band
        self.method = method
        self.reref_mode = reref_mode
        self.pipe = build_pipe(method, n_per_class)
        self.cv_ = None

    def _prep(self, epochs):
        epochs = np.asarray(epochs, dtype=float)
        if epochs.ndim == 2:            # essai unique (n_ch, n_samp) -> (1, n_ch, n_samp)
            epochs = epochs[None]
        # re-ref spatial AVANT le passe-bande (both linéaires -> ordre indifférent). getattr avec
        # défaut "none" : un modèle picklé AVANT l'ajout du CAR a été entraîné sans re-ref -> il faut
        # décoder sans re-ref aussi (sinon incohérence train/predict). Les modèles récents portent
        # l'attribut et utilisent leur propre mode.
        epochs = reref(epochs, getattr(self, "reref_mode", "none"))
        return bandpass(epochs, self.fs, self.band)

    def fit(self, epochs, y):
        Xf, y = self._prep(epochs), np.asarray(y)
        self.cv_ = float(cross_val_score(self.pipe, Xf, y, cv=5).mean())
        self.pipe.fit(Xf, y)
        return self

    def predict_proba(self, window):
        """window : (n_ch, n_samp). Retourne {label: proba}."""
        proba = self.pipe.predict_proba(self._prep(window))[0]
        return dict(zip(self.pipe.classes_, proba))

    def save(self, path):
        joblib.dump(self, path)

    @staticmethod
    def load(path):
        return joblib.load(path)


class MIDecoder:
    """Décodeur online. Interface commune à CCADecoder : `.classify(window) -> (label|None, scores)`.
    `window` = (n_samp, n_ch), comme côté acquisition. REPOS ou proba < prob_min -> None (stop)."""

    def __init__(self, model, prob_min=0.60, rest_label="REPOS"):
        self.model = model
        self.prob_min = prob_min
        self.rest_label = rest_label
        self.labels = [l for l in model.labels if l != rest_label]

    def scores(self, window):
        w = np.asarray(window, dtype=float).T   # (n_samp, n_ch) -> (n_ch, n_samp)
        return self.model.predict_proba(w)

    def classify(self, window):
        sc = self.scores(window)
        best = max(sc, key=sc.get)
        if best == self.rest_label or sc[best] < self.prob_min:
            return None, sc
        return best, sc


# --- Validation sur ERD synthétique (pas de casque requis) -----------------

# Ordre des voies Unicorn : Fz,C3,Cz,C4,Pz,PO7,Oz,PO8 -> C3=1, C4=3.
def synth_mi_trial(label, n_ch=8, n_samp=500, fs=250.0, erd=0.5, noise=1.0, mu_amp=1.5,
                   common=0.0, rng=None):
    """Rythme mu (10 Hz) partout ; ATTÉNUÉ (ERD) sur la voie controlatérale pour GAUCHE/DROITE,
    inchangé pour REPOS. `common` > 0 ajoute un MODE COMMUN in-band identique sur TOUTES les voies,
    d'amplitude aléatoire par essai : simule la dérive de référence/EMG que subit l'online et que
    le CAR retire. Sans CAR, il gonfle la variance corrélée et NOIE le contraste ERD."""
    rng = np.random.default_rng() if rng is None else rng
    t = np.arange(n_samp) / fs
    X = rng.normal(0.0, noise, (n_ch, n_samp))
    amp = np.ones(n_ch)
    if label == "DROITE":
        amp[1] *= (1 - erd)     # main droite -> ERD sur C3
    elif label == "GAUCHE":
        amp[3] *= (1 - erd)     # main gauche -> ERD sur C4
    # REPOS : aucune atténuation
    for c in range(n_ch):
        X[c] += amp[c] * mu_amp * np.sin(2 * np.pi * 10 * t + rng.uniform(0, 2 * np.pi))
    if common > 0:              # même signal sur toutes les voies -> annulé exactement par le CAR
        X += common * rng.uniform(0.5, 1.5) * np.sin(2 * np.pi * 11 * t + rng.uniform(0, 2 * np.pi))
    return X


def _eval(method, Xtr, ytr, Xte, yte, reref_mode=MI_REREF):
    model = MIModel(method=method, reref_mode=reref_mode).fit(Xtr, ytr)
    dec = MIDecoder(model, prob_min=0.60)
    ctrl_ok = ctrl_tot = rest_ok = rest_tot = 0
    for e, lab in zip(Xte, yte):        # e : (n_ch, n_samp) -> classify attend (n_samp, n_ch)
        pred, _ = dec.classify(e.T)
        if lab == "REPOS":
            rest_tot += 1
            rest_ok += (pred is None)
        else:
            ctrl_tot += 1
            ctrl_ok += (pred == lab)
    return model.cv_, ctrl_ok / ctrl_tot, rest_ok / rest_tot


def _demo():
    # Le synthétique = 8 oscillateurs INDÉPENDANTS (pas de conduction volumique ni de mode commun) :
    # il valide la MÉCANIQUE du classifieur (CSP+LDA sépare-t-il l'ERD ?), PAS le re-référencement.
    # Le CAR suppose un mode commun partagé + des sources corrélées spatialement — ABSENTS ici, donc
    # il dégrade le synthétique (attendu, cf. diagnostic). Le CAR (défaut réel) est validé sur
    # données RÉELLES via `python src/research/mi_compare.py`. -> ici on teste le classifieur en re-ref 'none'.
    rng = np.random.default_rng(0)
    n_per, n_samp = 60, 500
    epochs, y = [], []
    for lab in MI_LABELS:
        for _ in range(n_per):
            epochs.append(synth_mi_trial(lab, n_samp=n_samp, rng=rng))
            y.append(lab)
    epochs, y = np.asarray(epochs), np.asarray(y)
    print(f"Dataset synthétique : {len(y)} essais ({n_per}/classe : GAUCHE/DROITE/REPOS), "
          f"fenêtre {n_samp/250:.1f}s, 8 voies indépendantes\n")

    Xtr, Xte, ytr, yte = train_test_split(epochs, y, test_size=0.3, random_state=0, stratify=y)
    print("== Validation du classifieur (ERD synthétique propre, re-ref 'none') ==")
    print("méthode  | CV 5-fold | G/D test | repos->None")
    ok = False
    for m in ("csp", "riemann"):
        cv, ctrl, rest = _eval(m, Xtr, ytr, Xte, yte, reref_mode="none")
        star = "  <- défaut" if m == MI_METHOD else ""
        print(f"{m:<8} |   {cv*100:5.1f}% |  {ctrl*100:5.1f}% |   {rest*100:5.1f}%{star}")
        if m == MI_METHOD:
            ok = cv > 0.8 and ctrl > 0.85 and rest > 0.8
    print(f"\n[mi] classifieur {MI_METHOD} " + ("validé." if ok else "à ajuster.")
          + f" Re-ref défaut = {MI_REREF} (validé sur données réelles, pas sur ce synthétique).")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _demo()
