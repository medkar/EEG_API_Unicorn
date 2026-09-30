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

Trois méthodes (`build_pipe`) : "csp" (le défaut), "riemann", et "fbcsp" (2026-09-30, option
d'entraînement décochée par défaut — Ang et al. 2008, JAMAIS mesurée sur ce casque). Le FBCSP
découpe la bande en sous-bandes d'~4 Hz, apprend un CSP par sous-bande et laisse une sélection
par information mutuelle garder celles qui séparent les classes de CETTE personne : son pic mu
n'est pas forcément à 10 Hz.

Validé ici sur ERD SYNTHÉTIQUE (pas de casque).   python src/core/mi_decoder.py
"""

import os
import sys
from functools import partial

import joblib
import numpy as np
from scipy.linalg import eigh
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.feature_selection import SelectKBest, mutual_info_classif
from sklearn.model_selection import (StratifiedGroupKFold, cross_val_score,
                                     train_test_split)
from sklearn.pipeline import Pipeline

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import MI_METHOD, MI_REREF, use_utf8_console  # noqa: E402
from core.filtrage import passe_bande  # noqa: E402

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


def bandpass(epochs, fs, band=MI_BAND, order=4, secteur_hz=None):
    """Filtre 0-phase le long du temps, puis coupe-bande `secteur_hz` s'il est donné.
    epochs : (..., n_samples). Le calcul vit dans `core/filtrage.py`, partagé par les décodeurs."""
    return passe_bande(epochs, fs, band, secteur_hz=secteur_hz, axis=-1, ordre=order)


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


def sous_bandes(bande):
    """Les sous-bandes du FBCSP : la bande découpée en `max(2, round(largeur / 4))` morceaux égaux.

    8-30 Hz -> 6 sous-bandes de 3,67 Hz ; 4-40 Hz -> 9 de 4 Hz. Contiguës, et elles recouvrent
    EXACTEMENT la bande réglée : le FBCSP ne regarde ni plus ni moins que ce que l'étudiant a choisi.
    ~4 Hz est la largeur de Ang et al. (2008) : assez étroite pour isoler un pic mu d'une personne,
    assez large pour qu'un Butterworth d'ordre 4 y reste stable sur une fenêtre de 2 s.
    """
    bas, haut = float(bande[0]), float(bande[1])
    n = max(2, int(round((haut - bas) / 4.0)))
    bords = np.linspace(bas, haut, n + 1)
    return tuple((float(bords[i]), float(bords[i + 1])) for i in range(n))


class FilterBankCSP(BaseEstimator, TransformerMixin):
    """Un CSP par sous-bande ; les log-variances de toutes les sous-bandes, mises bout à bout.

    Chaque sous-bande est filtrée par `bandpass` — le filtre commun des décodeurs, coupe-bande
    secteur COMPRIS : dans un modèle FBCSP, c'est ce banc qui filtre, et lui seul (`MIModel._prep`
    ne pose aucun passe-bande global pour cette méthode).

    Picklable par joblib : que des attributs simples et des `CSP`, aucune fonction anonyme — un
    modèle enregistré doit se relire dans un autre processus (le moteur).
    """

    def __init__(self, fs, sous_bandes, n_per_class=2, secteur_hz=None):
        self.fs = fs
        self.sous_bandes = sous_bandes
        self.n_per_class = n_per_class
        self.secteur_hz = secteur_hz

    def _filtrer(self, X, bande):
        return bandpass(X, self.fs, bande, secteur_hz=self.secteur_hz)

    def fit(self, X, y):  # X : (n_trials, n_ch, n_samples), NON filtré
        X = np.asarray(X, dtype=float)
        self.csps_ = [CSP(self.n_per_class).fit(self._filtrer(X, b), y)
                      for b in self.sous_bandes]
        return self

    def transform(self, X):
        X = np.asarray(X, dtype=float)
        return np.hstack([csp.transform(self._filtrer(X, b))
                          for csp, b in zip(self.csps_, self.sous_bandes)])


def build_pipe(method=MI_METHOD, n_per_class=2, fs=250.0, band=MI_BAND, secteur_hz=None,
               n_classes=len(MI_LABELS)):
    """Pipeline de classification MI. 'csp' = CSP+LDA ; 'riemann' = covariances + espace
    tangent + régression logistique (géométrie riemannienne : robuste, efficace avec peu
    de données) ; 'fbcsp' = banc de CSP par sous-bande + sélection + LDA.

    `fs`, `band` et `secteur_hz` ne servent qu'au FBCSP, qui filtre lui-même : les deux autres
    reçoivent un signal déjà filtré par `MIModel._prep`.

    ⚠️ FBCSP : la sélection par information mutuelle vit DANS le pipeline, donc elle est refaite
    dans CHAQUE pli de la validation croisée, sur les seules lignes d'apprentissage du pli. Faite
    une fois sur tout le jeu avant la CV, elle aurait choisi les sous-bandes en regardant les essais
    de test : une CV optimiste, sans rien casser. `k` = la dimension d'UN CSP (2 × n_per_class ×
    n_classes) : le FBCSP ne garde pas plus de caractéristiques qu'un CSP simple, il les choisit
    dans plus de sous-bandes. `random_state=0` : l'estimateur de l'information mutuelle bruite
    légèrement les données, et un modèle doit se réentraîner à l'identique.
    """
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
    if method == "fbcsp":
        # `partial` et non `lambda` : le modèle se sérialise par joblib, et un lambda ne se picke pas.
        return Pipeline([("banc", FilterBankCSP(fs, sous_bandes(band), n_per_class, secteur_hz)),
                         ("selection", SelectKBest(partial(mutual_info_classif, random_state=0),
                                                   k=2 * n_per_class * n_classes)),
                         ("lda", LinearDiscriminantAnalysis())])
    raise ValueError(f"méthode MI inconnue : {method!r} (attendu 'csp', 'riemann' ou 'fbcsp')")


class MIModel:
    """Pipeline entraînable (CSP+LDA, Riemannien ou FBCSP) + (dé)sérialisation. `cv_` = accuracy
    CV. Le modèle PORTE son filtre (`band`, `secteur_hz`) et sa méthode : le décodage les relit."""

    def __init__(self, labels=MI_LABELS, fs=250.0, band=MI_BAND, method=MI_METHOD,
                 n_per_class=2, reref_mode=MI_REREF, secteur_hz=None):
        self.labels = list(labels)
        self.fs = fs
        self.band = band
        # Le SECTEUR du coupe-bande (2026-09-30), enregistré avec la bande : le décodage filtre
        # exactement comme l'entraînement. None = pas de coupe-bande — c'est ce que rend un modèle
        # d'avant ce réglage, qui doit décoder comme il a appris.
        self.secteur_hz = secteur_hz
        self.method = method
        self.reref_mode = reref_mode
        self.pipe = build_pipe(method, n_per_class, fs=fs, band=band, secteur_hz=secteur_hz,
                               n_classes=len(self.labels))
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
        # FBCSP : AUCUN passe-bande global — le banc filtre lui-même, sous-bande par sous-bande,
        # coupe-bande compris. Filtrer aussi ici ferait passer chaque sous-bande dans DEUX filtres
        # en cascade, et le modèle n'apprendrait plus sur la bande qu'il annonce.
        if getattr(self, "method", MI_METHOD) == "fbcsp":
            return epochs
        return bandpass(epochs, self.fs, self.band, secteur_hz=getattr(self, "secteur_hz", None))

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
            # ⚠️ `n_splits >= 2` (donc `cv_groupee_` non None) dépend d'avoir >= 2 essais DISTINCTS
            # par classe. Le seul appelant aujourd'hui (`mi_calib._entrainer`) exige >= 5 FENÊTRES
            # par classe avant même d'arriver ici, et un essai en produit 3 (window_s=2s, step_s=1s,
            # imagery_s=4s) : 5 fenêtres impliquent donc déjà >= 2 essais — une COÏNCIDENCE
            # ARITHMÉTIQUE entre deux fichiers, pas un lien garanti. Si ces durées changent côté
            # calibration, ou si des essais sont ignorés en séance (coupure Bluetooth), `n_splits`
            # peut retomber à 1 alors que le seuil de 5 fenêtres est atteint. Commentaire jumeau
            # dans `core/modes/mi_calib.py::MICalibration._entrainer`.
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

    # L'invariant ci-dessus (`cv_groupee_ < cv_`) ne protège PAS contre une DÉCOTE ARBITRAIRE :
    # un faux `cv_groupee_ = 0.85 * cv_`, qui ne regarderait même pas `groups`, satisferait cette
    # inégalité sur N'IMPORTE QUEL jeu de données. On teste donc le MÉCANISME plutôt que
    # d'inférer sa correction depuis un agrégat — en espionnant le VRAI découpage que `fit`
    # utilise (pas un découpage reconstruit à côté, qui ne prouverait que la sûreté de
    # sklearn, jamais celle de `fit`) et en vérifiant qu'à CHAQUE pli, les groupes (essais)
    # d'apprentissage et de test sont bien DISJOINTS.
    plis_espionnes = []
    vraie_split = StratifiedGroupKFold.split

    def _split_espion(self, X_arg, y_arg=None, groups=None):
        for train_idx, test_idx in vraie_split(self, X_arg, y_arg, groups=groups):
            plis_espionnes.append((set(groups[train_idx]), set(groups[test_idx])))
            yield train_idx, test_idx

    StratifiedGroupKFold.split = _split_espion
    try:
        MIModel(fs=fs, reref_mode="none").fit(X, y, groups=groupes)
    finally:
        StratifiedGroupKFold.split = vraie_split

    chk(len(plis_espionnes) >= 2,
        f"le VRAI découpage utilisé par fit() a bien produit au moins 2 plis "
        f"({len(plis_espionnes)})")
    chk(all(not (train_g & test_g) for train_g, test_g in plis_espionnes),
        "et à CHAQUE pli, les groupes d'apprentissage et de test sont DISJOINTS — vérifié sur "
        "le découpage RÉELLEMENT utilisé, pas un équivalent reconstruit à côté")

    print(f"[mi-cv] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _test_n_splits_insuffisant():
    """La garde `n_splits < 2` : rien ne l'exerçait, alors que sa sûreté ne tenait QUE sur une
    coïncidence arithmétique non documentée entre deux fichiers (cf. `mi_calib._entrainer`).

    Moins de 2 essais DISTINCTS pour au moins une classe doit laisser `cv_groupee_` à `None` —
    MÊME quand cette classe a plein de FENÊTRES (un seul essai en produit plusieurs, cf.
    `decouper`) : c'est le nombre d'essais qui compte pour la CV groupée, jamais celui des
    fenêtres. GAUCHE et DROITE ont ici 8 essais distincts chacune (comme d'habitude) ; REPOS
    n'en a qu'UN SEUL, découpé en 10 fenêtres — assez de fenêtres pour que la CV NAÏVE (5-fold
    ordinaire, indifférente aux groupes) se calcule sans encombre, mais un seul groupe, donc
    `n_splits` retomberait à 1 pour la CV groupée : sous le plancher de 2 posé par `fit`.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    rng = np.random.default_rng(0)
    fs = 250.0
    n_fen = int(round(2.0 * fs))          # MI_WINDOW_S -> une fenêtre MI ordinaire
    X, y, groupes = [], [], []
    essai = 0
    for label in MI_CONTROL:              # ("GAUCHE", "DROITE") : 8 essais distincts chacune
        for _ in range(8):
            for _ in range(3):            # 3 fenêtres par essai, comme un essai réel de 4 s
                X.append(synth_mi_trial(label, n_samp=n_fen, fs=fs, rng=rng))
                y.append(label)
                groupes.append(essai)
            essai += 1
    for _ in range(10):                   # REPOS : 10 FENÊTRES, mais un SEUL essai (le groupe
        X.append(synth_mi_trial("REPOS", n_samp=n_fen, fs=fs, rng=rng))  # ne change pas)
        y.append("REPOS")
        groupes.append(essai)
    n_essais_attendu = essai + 1          # +1 pour l'unique essai REPOS

    modele = MIModel(fs=fs, reref_mode="none").fit(np.asarray(X), np.asarray(y),
                                                    groups=np.asarray(groupes))
    chk(modele.cv_ is not None,
        f"la CV naïve se calcule quand même — son n_splits=5 est FIXE, indifférent aux groupes "
        f"({modele.cv_})")
    chk(modele.n_essais_ == n_essais_attendu,
        f"le nombre d'essais DISTINCTS est bien recensé (17 = 8+8+1) ({modele.n_essais_})")
    chk(modele.cv_groupee_ is None,
        f"mais la CV honnête reste ABSENTE : REPOS n'a qu'UN essai distinct malgré ses 10 "
        f"fenêtres, `n_splits` tomberait à 1, sous le plancher de 2 ({modele.cv_groupee_})")

    print(f"[mi-cv-n_splits] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _test_fbcsp():
    """Le FBCSP (2026-09-30) : il sépare, il choisit la bonne sous-bande, sa sélection ne fuit pas,
    il se relit.

    ⚠️ La panne qu'on garde ici ne lève RIEN : une sélection des sous-bandes faite UNE fois sur
    tout le jeu, avant la validation croisée, choisit ses caractéristiques en regardant les essais
    de test. La CV sort plus belle, le modèle est le même, et l'étudiant garde un modèle sur un
    chiffre gonflé. Un score ne peut pas la voir (il serait seulement un peu meilleur) : on
    ESPIONNE ce que reçoit l'information mutuelle dans chaque pli, comme `_test_cv_honnete`
    espionne le découpage.
    """
    import tempfile

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    chk(sous_bandes((8.0, 30.0)) == tuple((8.0 + i * 22.0 / 6, 8.0 + (i + 1) * 22.0 / 6)
                                          for i in range(6)),
        "8-30 Hz -> 6 sous-bandes égales de 3,67 Hz")
    b = sous_bandes((4.0, 40.0))
    chk(len(b) == 9 and all(abs((h - l) - 4.0) < 1e-9 for l, h in b)
        and b[0][0] == 4.0 and b[-1][1] == 40.0
        and all(b[i][1] == b[i + 1][0] for i in range(len(b) - 1)),
        f"4-40 Hz -> 9 sous-bandes contiguës de 4 Hz, qui recouvrent la bande exactement ({b})")

    # Un jeu d'essais dans un ordre MÉLANGÉ : la suite des étiquettes des lignes d'apprentissage
    # devient alors l'EMPREINTE d'un pli — deux plis différents n'ont pas la même. C'est ce qui
    # permet à l'espion de dire « ces lignes-là exactement », pas seulement « ce nombre de lignes ».
    rng = np.random.default_rng(0)
    fs, bande = 250.0, (4.0, 40.0)
    n_fen, pas = int(round(2.0 * fs)), int(round(1.0 * fs))
    essais = [lab for lab in MI_LABELS for _ in range(20)]
    rng.shuffle(essais)
    X, y, groupes = [], [], []
    for indice, label in enumerate(essais):
        epoque = synth_mi_trial(label, n_samp=int(4.0 * fs), fs=fs, rng=rng)
        for debut in range(0, epoque.shape[1] - n_fen + 1, pas):
            X.append(epoque[:, debut:debut + n_fen])
            y.append(label)
            groupes.append(indice)
    X, y, groupes = np.asarray(X), np.asarray(y), np.asarray(groupes)

    # --- les espions : l'information mutuelle, et le VRAI découpage de la CV groupée ---------
    # `build_pipe` lit `mutual_info_classif` dans les globales de CE module au moment où il
    # construit le pipeline : le remplacer ici, avant `MIModel(...)`, met l'espion DANS le
    # pipeline — donc dans chacun de ses clones, pli par pli.
    appels, plis = [], []
    vraie_mi = globals()["mutual_info_classif"]
    vraie_split = StratifiedGroupKFold.split

    def _mi_espion(X_arg, y_arg, **kw):
        appels.append((len(y_arg), tuple(y_arg), kw.get("random_state")))
        return vraie_mi(X_arg, y_arg, **kw)

    def _split_espion(self, X_arg, y_arg=None, groups=None):
        for train_idx, test_idx in vraie_split(self, X_arg, y_arg, groups=groups):
            plis.append(np.array(train_idx))
            yield train_idx, test_idx

    globals()["mutual_info_classif"] = _mi_espion
    StratifiedGroupKFold.split = _split_espion
    try:
        modele = MIModel(fs=fs, band=bande, method="fbcsp", reref_mode="none",
                         secteur_hz=50.0).fit(X, y, groups=groupes)
    finally:
        globals()["mutual_info_classif"] = vraie_mi
        StratifiedGroupKFold.split = vraie_split

    # (a) il sépare — l'ERD synthétique est à 10 Hz, dans une bande large exprès.
    hasard = 1.0 / len(MI_LABELS)
    chk(modele.cv_groupee_ is not None and modele.cv_groupee_ > 0.5,
        f"FBCSP sur une bande large (4-40 Hz) sépare l'ERD : CV groupée "
        f"{(modele.cv_groupee_ or 0) * 100:.1f} % pour un hasard à {hasard * 100:.0f} % "
        f"({modele.n_essais_} essais)")
    # (a') ...et pour la bonne raison : la sélection va chercher la sous-bande du mu.
    dim = 2 * 2 * len(MI_LABELS)          # la dimension d'UN CSP = le `k` de la sélection
    selection = modele.pipe.named_steps["selection"]
    bandes = modele.pipe.named_steps["banc"].sous_bandes
    meilleure = bandes[int(np.argmax(selection.scores_)) // dim]
    retenues = np.flatnonzero(selection.get_support()) // dim
    dans_le_mu = int(np.sum([bandes[i][0] <= 10.0 < bandes[i][1] for i in retenues]))
    chk(selection.k == dim and len(retenues) == dim,
        f"la sélection garde la dimension d'UN CSP ({len(retenues)} sur "
        f"{len(bandes) * dim} caractéristiques)")
    chk(meilleure[0] <= 10.0 < meilleure[1] and dans_le_mu > dim // 2,
        f"...et va les chercher dans la sous-bande du mu : la plus informative est "
        f"{meilleure[0]:g}-{meilleure[1]:g} Hz, et {dans_le_mu} des {dim} retenues y sont")

    # (b) l'espion : dans CHAQUE pli de la CV groupée, la sélection n'a vu QUE ses lignes
    # d'apprentissage. L'empreinte (la suite des étiquettes) désigne les lignes exactes.
    n = len(y)
    empreintes = {a[1] for a in appels}
    chk(len(plis) >= 2, f"la CV groupée a bien découpé au moins 2 plis ({len(plis)})")
    chk(all(len(t) < n and tuple(y[t]) in empreintes for t in plis),
        f"dans CHAQUE pli, l'information mutuelle a reçu EXACTEMENT les lignes d'apprentissage "
        f"du pli, moins que le total ({[len(t) for t in plis]} sur {n}) — la sélection est "
        f"refaite pli par pli, elle ne voit jamais les essais de test")
    chk(sum(1 for a in appels if a[0] == n) == 1,
        f"et elle n'a vu TOUTES les lignes qu'une fois : l'entraînement final, après la CV "
        f"({[a[0] for a in appels]})")
    chk(all(a[2] == 0 for a in appels),
        "avec `random_state=0` à chaque appel : un modèle se réentraîne à l'identique")

    # (c) le modèle PORTE son filtre, et c'est le banc qui filtre — pas `_prep`.
    banc = modele.pipe.named_steps["banc"]
    chk(banc.secteur_hz == 50.0 and banc.sous_bandes == sous_bandes(bande) and banc.fs == fs,
        f"le banc reçoit la bande, le secteur et fs du modèle ({banc.secteur_hz}, "
        f"{len(banc.sous_bandes)} sous-bandes, {banc.fs})")
    fenetre = X[0]
    chk(np.array_equal(modele._prep(fenetre)[0], reref(fenetre, "none")),
        "FBCSP : `_prep` ne pose AUCUN passe-bande global — le banc filtre seul")
    chk(not np.allclose(MIModel(fs=fs, band=bande)._prep(fenetre)[0],
                        reref(fenetre, MI_REREF)),
        "(le CSP simple, lui, filtre toujours dans `_prep`)")

    # (d) aller-retour joblib. Un modèle FRAIS : celui du dessus porte l'espion dans sa sélection,
    # et c'est justement le genre d'objet (une fonction locale) qu'un pickle refuse.
    reel = MIModel(fs=fs, band=bande, method="fbcsp", secteur_hz=60.0).fit(X, y, groups=groupes)
    with tempfile.TemporaryDirectory() as dossier:
        chemin = os.path.join(dossier, "mi_model_fbcsp.joblib")
        reel.save(chemin)
        relu = MIModel.load(chemin)
    p_avant, p_apres = reel.predict_proba(fenetre), relu.predict_proba(fenetre)
    chk(relu.method == "fbcsp" and tuple(relu.band) == bande and relu.secteur_hz == 60.0,
        f"relu par joblib, le modèle porte sa méthode, sa bande et son secteur "
        f"({relu.method}, {relu.band}, {relu.secteur_hz})")
    chk(set(p_apres) == set(MI_LABELS)
        and all(abs(p_avant[c] - p_apres[c]) < 1e-12 for c in MI_LABELS),
        f"et il décode À L'IDENTIQUE après relecture ({ {c: round(v, 3) for c, v in p_apres.items()} })")

    print(f"[mi-fbcsp] VERDICT : {'OK' if ok else 'PROBLÈME'}")
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
    for m in ("csp", "riemann", "fbcsp"):
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
    ok_n_splits = _test_n_splits_insuffisant()
    ok_fbcsp = _test_fbcsp()
    ok_demo = _demo()
    sys.exit(0 if (ok_cv and ok_n_splits and ok_fbcsp and ok_demo) else 1)
