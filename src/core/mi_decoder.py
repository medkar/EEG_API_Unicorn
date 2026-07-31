"""Décodeur Motor Imagery (imagerie motrice) : CSP + LDA, deux classes de mouvement imaginé
(main gauche/droite) + un état REPOS explicite (indispensable pour distinguer un repos réel
d'une simple absence de décision).

Contrairement au SSVEP (CCA, zéro entraînement), le MI doit être ENTRAÎNÉ :
  1. calibration  -> essais EEG étiquetés GAUCHE / DROITE / REPOS   [src/core/modes/mi_calib.py]
  2. entraînement -> CSP (filtres spatiaux) + LDA                    [MIModel.fit]
  3. online       -> MIModel classe la fenêtre en direct            [MIModel.predict_proba]

Pourquoi REPOS comme 3e classe : un classifieur 2 classes choisit TOUJOURS un côté (même sans
imagerie) => faux mouvements au repos. En apprenant « repos », le modèle peut dire « la personne
ne fait rien » — ce qui est une intention à part entière, DIFFÉRENTE de « je ne sais pas ». Ce
que l'application en fait (s'arrêter, attendre, ignorer) ne regarde pas ce module : le flux
publie une intention neutre, jamais une commande d'actionneur (docs/SPEC.md §5).

Signal : ERD (désynchronisation) mu/beta du cortex moteur — la puissance chute sur l'hémisphère
OPPOSÉ à la main imaginée (main droite -> baisse sur C3 ; main gauche -> sur C4). Le CSP apprend
les filtres spatiaux qui maximisent ce contraste de variance.

Validé ici sur ERD SYNTHÉTIQUE (pas de casque).   python src/core/mi_decoder.py
"""

import os
import sys

import joblib
import numpy as np
from scipy.linalg import eigh
from scipy.signal import butter, filtfilt
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.model_selection import (StratifiedGroupKFold, cross_val_score,  # noqa: E402
                                     train_test_split)
from sklearn.pipeline import Pipeline

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import MI_METHOD, MI_REREF, use_utf8_console  # noqa: E402

MI_BAND = (8.0, 30.0)                       # mu (8-12) + beta (13-30) = rythmes sensorimoteurs
MI_CONTROL = ("GAUCHE", "DROITE")           # classes actives (hors REPOS)
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
        # La CV HONNÊTE (par essai) et le nombre d'essais. `None` tant qu'on n'a pas dit à `fit`
        # à quel essai appartient chaque fenêtre — voir `fit`. `mi_models.decrire()` les lit et
        # les affiche absents plutôt que de recopier `cv_`, qui est gonflée.
        self.cv_groupee_ = None
        self.n_essais_ = None

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

    def fit(self, epochs, y, groups=None):
        """Entraîne. `groups` = l'indice d'ESSAI de chaque fenêtre — c'est lui qui rend la CV honnête.

        Deux chiffres sortent d'ici, et ils ne disent pas la même chose :

        - `cv_` — validation croisée ORDINAIRE, fenêtres mélangées. Gardée parce qu'elle permet de
          comparer avec les mesures antérieures du projet, et parce que l'écart entre les deux EST
          l'information : c'est la fuite, chiffrée.
        - `cv_groupee_` — validation croisée par ESSAI : toutes les fenêtres d'un essai tombent
          dans le MÊME pli. C'est la seule qui réponde à la question de l'étudiant, « est-ce que ça
          marchera sur un essai que le modèle n'a jamais vu ? ». C'est celle-là, et elle seule,
          qu'on affiche.

        On prend `StratifiedGroupKFold` et non `GroupKFold` : le second ne regarde pas les
        étiquettes et peut composer un pli d'apprentissage où une classe manque entièrement — la
        LDA lève alors, ou pire, apprend sur deux classes et se fait juger sur trois. Le premier
        respecte les DEUX contraintes : groupes entiers ET classes représentées.

        `n_splits` est borné par le plus petit effectif d'essais par classe : demander 5 plis quand
        une classe n'a que 3 essais est irréalisable, et sklearn le refuserait en pleine fin de
        séance de calibration — après sept minutes d'imagerie. On borne AVANT plutôt que de laisser
        lever.
        """
        Xf, y = self._prep(epochs), np.asarray(y)
        self.cv_ = float(cross_val_score(self.pipe, Xf, y, cv=5).mean())
        self.cv_groupee_, self.n_essais_ = None, None
        if groups is not None:
            groups = np.asarray(groups)
            self.n_essais_ = int(len(np.unique(groups)))
            # Essais DISTINCTS par classe : c'est ce qui borne le nombre de plis, pas le nombre de
            # fenêtres (elles se comptent par trois pour un même essai).
            par_classe = [len(np.unique(groups[y == c])) for c in np.unique(y)]
            n_splits = min(5, min(par_classe)) if par_classe else 0
            if n_splits >= 2:
                cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=0)
                self.cv_groupee_ = float(
                    cross_val_score(self.pipe, Xf, y, groups=groups, cv=cv).mean())
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
    `window` = (n_samp, n_ch), comme côté acquisition. REPOS ou proba < prob_min -> None."""

    def __init__(self, model, prob_min=0.60, rest_label="REPOS"):
        self.model = model
        self.prob_min = prob_min
        self.rest_label = rest_label
        self.labels = [l for l in model.labels if l != rest_label]

    def scores(self, window):
        w = np.asarray(window, dtype=float).T   # (n_samp, n_ch) -> (n_ch, n_samp)
        return self.model.predict_proba(w)

    def classify(self, window):
        """⚠️ **Ce n'est PAS la règle de décision du flux réseau.** Elle vit dans
        `core/modes/mi.py`, `MIRuntime._run_step`, et c'est celle-là qui fait foi pour
        `decoded_mi`.

        Deux différences, et elles comptent :
          - ici, REPOS et « probabilité trop basse » rendent tous les deux `None` — deux
            situations confondues, alors que le flux les distingue par contrat (l'indice de
            REPOS d'un côté, `-1` de l'autre) ;
          - ici, une seule fenêtre décide ; là-bas, un vote glissant sur `vote_len` fenêtres.

        Cette méthode n'est plus utilisée que par `archive/mi_pilot.py`. Le moteur, lui, passe
        par `scores()` : voir `core/modes/mi.py`.
        """
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


def _test_cv_honnete():
    """L'invariant de la CV groupée : elle doit être INFÉRIEURE à la naïve, toujours.

    Pourquoi c'est un invariant et pas une observation : la CV naïve mélange entre plis des
    fenêtres GLISSANTES issues du même essai. Deux fenêtres d'un même essai partagent une seconde
    de signal sur deux et la même étiquette — le classifieur retrouve donc en test un morceau
    exact de ce qu'il a vu en apprentissage. Le score obtenu ne dit plus rien de sa capacité à
    généraliser à un NOUVEL essai, qui est pourtant la seule question qui compte pour un étudiant.

    Mesuré sur les 30 essais archivés du projet : 55,6 % naïve contre 40,0 % honnête à 3 classes,
    73,3 % contre 63,3 % à 2 classes. L'écart est de 10 à 16 points, et c'est CE chiffre-là qui
    était affiché à la fin d'une séance de calibration.

    Le test ne vérifie PAS une valeur : il vérifie le SENS de l'écart, qui ne dépend d'aucun jeu
    de données. Une valeur attendue serait fausse dès qu'on change la graine.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    rng = np.random.default_rng(0)
    fs, n_essais_par_classe = 250.0, 8
    n_fen = int(round(2.0 * fs))          # MI_WINDOW_S
    pas = int(round(1.0 * fs))            # MI_TRAIN_STEP_S -> 3 fenêtres par essai de 4 s
    X, y, groupes = [], [], []
    essai = 0
    for label in MI_LABELS:
        for _ in range(n_essais_par_classe):
            # Une époque de 4 s, comme en produira la calibration : (n_ch, 4*fs).
            epoque = synth_mi_trial(label, n_samp=int(4.0 * fs), fs=fs, rng=rng)
            for debut in range(0, epoque.shape[1] - n_fen + 1, pas):
                X.append(epoque[:, debut:debut + n_fen])
                y.append(label)
                groupes.append(essai)
            essai += 1
    X, y, groupes = np.asarray(X), np.asarray(y), np.asarray(groupes)
    chk(len(X) == essai * 3, f"3 fenêtres par essai de 4 s ({len(X)} pour {essai} essais)")

    modele = MIModel(fs=fs, reref_mode="none").fit(X, y, groups=groupes)
    chk(modele.cv_ is not None and modele.cv_groupee_ is not None,
        f"les deux CV sont calculées (naïve={modele.cv_}, groupée={modele.cv_groupee_})")
    chk(modele.n_essais_ == essai,
        f"le nombre d'ESSAIS est retenu, pas celui des fenêtres ({modele.n_essais_})")
    chk(modele.cv_groupee_ < modele.cv_,
        f"la CV groupée est INFÉRIEURE à la naïve : {modele.cv_groupee_*100:.1f}% contre "
        f"{modele.cv_*100:.1f}% — la fuite entre fenêtres d'un même essai vaut "
        f"{(modele.cv_ - modele.cv_groupee_)*100:.1f} points")

    # Sans `groups`, la CV honnête n'est pas INVENTÉE : elle reste absente. Recopier la naïve
    # ferait passer un chiffre gonflé pour un chiffre honnête — exactement le défaut corrigé.
    sans = MIModel(fs=fs, reref_mode="none").fit(X, y)
    chk(sans.cv_ is not None and sans.cv_groupee_ is None and sans.n_essais_ is None,
        f"sans `groups`, la CV honnête reste absente au lieu d'être inventée "
        f"({sans.cv_groupee_}, {sans.n_essais_})")

    print(f"[mi-cv] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


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
    ok_cv = _test_cv_honnete()
    ok_demo = _demo()
    sys.exit(0 if (ok_cv and ok_demo) else 1)
