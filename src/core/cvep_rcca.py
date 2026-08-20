"""Décodeur c-VEP par RECONVOLUTION (rCCA) : le second décodeur du mode, sur le MÊME stimulus.

Là où `cvep_decoder.CVEPModel` (eCCA) apprend un **template** de cycle entier et le corrèle à
chaque lag, le rCCA apprend une **réponse transitoire courte** (`CVEP_RCCA_ENC = 0,30 s`, environ
une réponse VEP) et la **reconvolue** avec le code de chaque cible. Moins de paramètres à estimer,
donc en principe moins d'époques nécessaires — c'est l'argument de la méthode.

⚠️ **Lire ceci avant de conclure quoi que ce soit sur le rCCA.** Ce dépôt a longtemps porté écrit
que « le rCCA est réfuté ». C'est vrai de **`rCCA + codes Gold distincts`**, jamais testés
séparément : les deux moitiés de l'hypothèse ont toujours été mesurées ensemble. Or
`RCCAModel.__init__` prend ses **codes en paramètre** — le décodeur ne sait pas d'où ils viennent.
Rebranché sur le stimulus qu'on garde (UNE m-séquence, six **décalages**), il n'avait tout
simplement jamais été mesuré. Il l'est maintenant :

    fichier data/cvep_calib_last.npz (2026-07-21, 1 personne, 90 cycles, 6 cibles, stimulus décalé)
      eCCA  leave-one-out 43/90 = 47,8 %       (hasard 16,7 %)
      rCCA  leave-one-out 43/90 = 47,8 %       (hasard 16,7 %, p = 0,0005 par permutation)

Les deux décodeurs sont **indiscernables** sur ces données ; le rCCA sur codes Gold, lui, plafonnait
à 35,6 % (`data/cvep_rcca_model.npz`, autre séance). C'est la moitié « codes Gold » de l'hypothèse
qui était mauvaise, pas la reconvolution. ⚠️ **Une personne, une séance** : ça n'établit pas que les
deux décodeurs se valent en général, seulement que rien ne justifie de jeter celui-ci. C'est
exactement pour ça que la calibration entraîne les DEUX et affiche les deux chiffres.

⚠️ **Les codes Gold distincts, eux, restent réfutés et restent DEHORS.** `make_distinct_codes` et
`build_targets_rcca` sont restés dans `src/research/cvep_rcca.py` : une hypothèse réfutée se garde
**lisible, pas branchée**. `cvep_models.charger` refuse d'ailleurs tout modèle rCCA dont les codes ne
sont pas ceux que `build_targets()` affiche aujourd'hui — sans quoi le seul modèle rCCA existant
(celui des codes Gold) réapparaîtrait dans la liste de la console, et le moteur décoderait un
stimulus que plus personne n'affiche.

`pyntbci` (BSD-3) est isolé dans CE fichier, et il est une dépendance du **moteur** : `save` ne
sérialise pas l'objet pyntbci, il stocke les époques et **ré-ajuste au chargement** (fit < 1 s), ce
qui évite de graver un nom de classe dans le fichier — la panne qui a coûté leurs modèles au P300 et
à l'ErrP — et garde les données pour ré-analyse.

Autotest (aucun casque, aucune donnée réelle) :
    python src/core/cvep_rcca.py

Rejouer une calibration réelle pour en tirer des seuils (LECTURE SEULE du fichier) :
    python src/core/cvep_rcca.py --seuils data/cvep_calib_last.npz
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (CVEP_BAND, CVEP_CHANNELS, CVEP_RCCA_CORR_MIN,  # noqa: E402
                         CVEP_RCCA_ENC, CVEP_RCCA_EVENT, CVEP_RCCA_MARGIN,
                         CVEP_RCCA_MODEL_PATH, FS_UNICORN, use_utf8_console)
from core.cvep_decoder import bandpass  # noqa: E402  (passe-bande zéro-phase partagé)


class RCCAModel:
    """Modèle rCCA (reconvolution). Interface calquée sur `CVEPModel`, décodeur différent.

    Les `codes` sont ceux **affichés par chaque cible à partir de la frame 0** — pour le stimulus
    du produit, la m-séquence décalée de chaque lag, c'est-à-dire exactement les `c["code"]` que
    `core.cvep_code.build_targets()` rend. La classe ne sait pas d'où ils viennent : c'est ce qui
    lui permet de tourner aussi sur les codes Gold de `research/`, et c'est ce qui avait fait
    condamner les deux ensemble (cf. la docstring du module).
    """

    # ⚠️ Ce que ce modèle EST, et ce que `cvep_models.charger` lit pour choisir le décodeur. Posé
    # au niveau de la CLASSE (pas relu du fichier) : un objet ne peut alors pas mentir sur
    # lui-même, même chargé d'un fichier dont le champ `decoder` aurait été bricolé. Le champ
    # ÉCRIT dans le fichier, lui, sert à l'aiguillage — c'est le seul rôle qu'il a.
    decoder = "rCCA"

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
        self.cv_ = None          # justesse leave-one-out, ou None si pas mesurable
        # Les scores HORS-PLI de cette validation croisée : (n_essais, n_cibles). C'est d'eux que
        # sortent les seuils (cf. `seuils_hors_pli`) — un seuil calculé sur les scores du modèle
        # entraîné SUR l'essai qu'il note serait optimiste, du même ordre que le « chiffre gonflé »
        # de la calibration MI. Même rôle que `oof_scores_`/`oof_y_` chez l'ErrP.
        self.oof_scores_ = None
        self.oof_y_ = None
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
        """Justesse leave-one-out, ET les scores hors-pli qui la produisent.

        On garde les SCORES et pas seulement le compte de bons coups : c'est la même boucle, et
        sans eux il faudrait la refaire ailleurs pour poser un seuil (N ré-ajustements pyntbci,
        soit ~8 s pour 90 essais sur ce poste). `cv_` reste la moyenne de `argmax == y`, donc
        les deux chiffres ne peuvent pas diverger.
        """
        if len(X) < 3 or len(set(y.tolist())) < 2:
            self.oof_scores_, self.oof_y_ = None, None
            return None
        scores = np.zeros((len(X), self.n_targets), dtype=float)
        for i in range(len(X)):
            tr = [j for j in range(len(X)) if j != i]
            clf = self._fit_clf(X[tr], y[tr])
            scores[i] = np.ravel(clf.decision_function(X[i:i + 1]))
        self.oof_scores_ = scores
        self.oof_y_ = np.asarray(y, dtype=int)
        return float((scores.argmax(axis=1) == self.oof_y_).mean())

    # --- décodage en ligne ----------------------------------------------
    def _fold(self, window, n_cycles):
        w = np.asarray(window, float)
        k = max(1, min(int(n_cycles), len(w) // self.n_cyc))
        return w[-k * self.n_cyc:].reshape(k, self.n_cyc, -1).mean(axis=0)

    def scores(self, window, phase, n_cycles=1):
        """Scores par cible (n_targets,) pour une fenêtre BRUTE se terminant « maintenant ».

        On filtre, on moyenne les `n_cycles` derniers cycles, on RECALE sur la frame 0 du code,
        puis rCCA note chaque cible. `self.codes[i]` décrit ce que la cible i affiche **à partir
        de la frame 0** ; une fenêtre qui démarre à la phase `p` porte donc, à son échantillon
        `k`, la réponse à la position `p + k` du code. `np.roll(avg, +shift(p))[k] =
        avg[k - shift(p)]`, c'est-à-dire la réponse à la position `k` : la fenêtre est ramenée
        à la phase 0, qui est celle où le classifieur a été ajusté.

        ⚠️ **Ce `+` était un `-` dans le code hérité de `research/cvep_rcca.py`, et c'était un
        VRAI défaut, pas un détail de convention.** Mesuré sur c-VEP synthétique, 21 fenêtres
        prises à des phases réparties sur le cycle : `-shift` décode 2/21, `+shift` décode 21/21.
        Personne ne l'avait vu parce que le seul test du fichier d'origine IMPRIMAIT le résultat
        de la phase glissante sans l'affirmer (« recalage OK si ≈ tout »), et parce que la
        calibration, elle, n'épochait qu'à la phase 0 — donc `cv_` restait juste. Le PILOTAGE en
        ligne, lui, note à des phases quelconques (`research/app.py::_cvep_decode`) : la variante
        rCCA a donc été jugée en séance à travers un alignement retourné. C'est une raison de
        plus de ne pas prendre pour acquis le verdict « le rCCA est moins bon ».
        """
        avg = self._fold(bandpass(window, self.fs, self.band), n_cycles)   # (n_cyc x n_ch) réduit
        aligned = np.roll(avg, self._shift(phase), axis=0)
        X = aligned.T[None]                               # (1, n_ch, n_cyc)
        return np.ravel(self.clf.decision_function(X))    # (n_targets,)

    # --- persistance : on stocke les données et on ré-entraîne au chargement ---
    def save(self, path=CVEP_RCCA_MODEL_PATH):
        """`np.savez` de tableaux PURS, aucun nom de classe gravé — c'est ce qui a permis au
        modèle eCCA de survivre à son déménagement dans `core/` là où le P300 et l'ErrP ont perdu
        les leurs. Ne pas y introduire de pickle d'objet.
        """
        if self._epochs is None:
            raise ValueError("modèle rCCA jamais ajusté : rien à sauvegarder (appelle `fit`)")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        np.savez(path, codes=self.codes, epochs=np.asarray(self._epochs),
                 labels=self._labels, fs=self.fs, refresh=self.refresh,
                 band=np.asarray(self.band), channels=np.asarray(self.channels, dtype=int),
                 event=self.event, enc=self.enc,
                 # Le fichier DÉCLARE son décodeur : `cvep_models.charger` lit ce champ pour
                 # savoir quelle classe instancier. Deviner d'après les clés présentes marcherait
                 # aujourd'hui et casserait au premier champ ajouté.
                 decoder=self.decoder,
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
    """Applique RCCAModel au plan de cibles + rejet (« rien fixé » -> None). Calqué sur CVEPDecoder.

    ⚠️ `plan[i]` doit décrire la cible dont `model.codes[i]` est le code : c'est le SEUL
    appariement qui existe entre un score et un nom de cible. Décalé d'un cran, tout continue de
    tourner en désignant systématiquement la cible voisine — le défaut que la revue du P300 avait
    trouvé sur son propre mode.
    """

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


# --- Les seuils, tirés des scores HORS-PLI d'une calibration ----------------

# En dessous de tant d'essais CORRECTS, on refuse de poser un quantile à 5 % : il serait
# littéralement porté par le minimum de l'échantillon. 20 est le point où `np.quantile(x, 0.05)`
# cesse d'être exactement `min(x)` — c'est un plancher de définition, pas un plancher de
# confiance ; à 43 essais (le seul jeu réel dont ce projet dispose) le chiffre reste dominé par
# une poignée d'essais faibles, et c'est écrit là où il est utilisé (`core/config.py`).
SEUILS_N_MIN = 20


def seuils_hors_pli(oof_scores, oof_y, garde=0.95, n_min=SEUILS_N_MIN):
    """(corr_min, margin, n_corrects) — les deux seuils de rejet, ou (None, None, n) si l'on n'a
    pas de quoi les poser.

    `oof_scores` : (n_essais, n_cibles), les scores produits par une validation croisée — donc par
    un modèle qui n'a **pas** vu l'essai qu'il note. `oof_y` : la vraie cible de chaque essai.

    On ne regarde que les essais que la validation croisée a **correctement classés** : ce sont les
    seuls dont on sache qu'ils portaient bien la réponse cherchée. `corr_min` est le quantile qui
    en **garde `garde`** (95 % par défaut), `margin` le quantile qui garde la même proportion de
    leurs écarts gagnant-second.

    ⚠️ **Ce que ce réglage fait, et ce qu'il ne fait pas.** Il cale sur « ne pas rater ce qui est
    bon » — le c-VEP n'a pas de coût asymétrique comme l'ErrP, où manquer une erreur et en inventer
    une n'ont pas le même prix. Il ne sépare PAS les essais corrects des incorrects : mesuré sur le
    seul jeu réel disponible, les deux distributions se recouvrent presque entièrement. Ce qui
    protège contre « personne ne fixe » est le vote glissant, pas ce plancher. Les chiffres et
    leurs conséquences mesurées sont dans `core/config.py`, à côté des constantes.
    """
    scores = np.asarray(oof_scores, dtype=float)
    y = np.asarray(oof_y, dtype=int)
    if scores.ndim != 2 or scores.shape[1] < 2 or len(y) != len(scores):
        raise ValueError(f"scores hors-pli mal formés : {scores.shape} pour {len(y)} étiquettes")
    ordre = np.sort(scores, axis=1)[:, ::-1]
    gagnant, ecart = ordre[:, 0], ordre[:, 0] - ordre[:, 1]
    bons = scores.argmax(axis=1) == y
    n = int(bons.sum())
    if n < n_min:
        return None, None, n
    q = 1.0 - float(garde)
    return (float(np.quantile(gagnant[bons], q)), float(np.quantile(ecart[bons], q)), n)


# --- Rejouer une calibration réelle (LECTURE SEULE) -------------------------

def _rejouer(chemin):
    """Rejoue un `cvep_calib_*.npz` à travers le rCCA et imprime les seuils qu'il implique.

    ⚠️ **Ce fichier n'est jamais modifié** : `data/` contient des enregistrements EEG d'une
    personne identifiable, sur un dépôt public. On lit, on calcule, on imprime.

    Cette commande existe parce que le projet s'est déjà fait avoir : les seuils de l'ErrP ont été
    posés par un script jetable et non versionné, et `errp_models.py` porte encore le regret de ne
    pas pouvoir dire à un étudiant comment les refaire. Ici, la commande est la trace.
    """
    from core.cvep_code import build_targets

    d = np.load(chemin, allow_pickle=True)
    plan, _code = build_targets()
    codes = np.stack([np.asarray(c["code"], dtype=int) for c in plan])
    lag_de_cible = [c["lag"] for c in plan]
    voies = [int(c) for c in d["channels"]]
    epochs = [d["epochs"][i][:, voies] for i in range(len(d["epochs"]))]
    y = np.asarray([lag_de_cible.index(int(l)) for l in d["lags"]])

    m = RCCAModel(codes, fs=float(d["fs"]), refresh=float(d["refresh"]),
                  channels=list(range(len(voies)))).fit(epochs, y, compute_cv=True)
    corr_min, margin, n_bons = seuils_hors_pli(m.oof_scores_, m.oof_y_)
    print(f"[rcca] {os.path.basename(chemin)} : {len(y)} époques, {m.n_targets} cibles, "
          f"voies {voies}")
    print(f"[rcca] leave-one-out : {m.cv_*100:.1f} %  ({int(round(m.cv_*len(y)))}/{len(y)}, "
          f"hasard {100/m.n_targets:.1f} %)")
    if corr_min is None:
        print(f"[rcca] seuils NON posés : {n_bons} essais corrects, moins que le plancher de "
              f"{SEUILS_N_MIN} — un quantile à 5 % y vaudrait le minimum de l'échantillon.")
        return True
    print(f"[rcca] seuils sur {n_bons} essais corrects : CVEP_RCCA_CORR_MIN = {corr_min:.3f}  "
          f"CVEP_RCCA_MARGIN = {margin:.3f}")
    return True


# --- Autotest sur c-VEP synthétique, sur le stimulus DÉCALÉ (aucun casque) --

def _jeu_synthetique(snr_db=-6.0, n_par_cible=8, n_ch=4, fs=250.0, refresh=60.0, seed=0):
    """(codes, plan, epochs, labels) : le stimulus RÉEL du produit (m-séquence + lags), joué à
    travers le générateur de c-VEP synthétique déjà écrit pour l'eCCA — `synth_cvep`. Les deux
    décodeurs sont donc éprouvés sur exactement la même fabrique, ce qui est tout l'intérêt
    d'avoir gardé un stimulus unique.
    """
    from core.cvep_code import build_targets
    from core.cvep_decoder import synth_cvep

    rng = np.random.default_rng(seed)
    plan, code = build_targets()
    codes = np.stack([np.asarray(c["code"], dtype=int) for c in plan])
    epochs, labels = [], []
    for i, cible in enumerate(plan):
        for _ in range(n_par_cible):
            epochs.append(synth_cvep(code, cible["lag"], n_ch, fs, refresh, snr_db, rng))
            labels.append(i)
    return codes, plan, epochs, np.asarray(labels), rng


def _selftest():
    """Le rCCA sur le stimulus DÉCALÉ : il décode, il s'aligne sur la phase, il se relit, et ses
    seuils sortent de scores hors-pli. Aucun casque, aucun fichier de `data/`.
    """
    import shutil
    import tempfile

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    fs, refresh, n_ch = 250.0, 60.0, 4
    codes, plan, epochs, labels, rng = _jeu_synthetique(fs=fs, refresh=refresh, n_ch=n_ch)
    modele = RCCAModel(codes, fs=fs, refresh=refresh,
                       channels=list(range(n_ch))).fit(epochs, labels, compute_cv=True)

    # --- 1. LE point de cette tâche : le rCCA décode la m-séquence DÉCALÉE. -------------------
    # C'est la mesure que personne n'avait faite : le rCCA n'avait jamais été jugé que sur des
    # codes Gold distincts, et condamné avec eux. Sur 6 cibles, le hasard vaut 16,7 %.
    chk(modele.cv_ is not None and modele.cv_ > 0.8,
        f"le rCCA décode le stimulus DÉCALÉ (m-séquence + lags), pas seulement des codes "
        f"distincts : leave-one-out {None if modele.cv_ is None else f'{modele.cv_*100:.0f} %'} "
        f"pour un hasard de {100/len(plan):.0f} %")
    chk(modele.oof_scores_ is not None
        and modele.oof_scores_.shape == (len(labels), len(plan))
        and np.array_equal(modele.oof_y_, labels),
        f"...et la validation croisée garde ses scores HORS-PLI, un par cible et par essai "
        f"({None if modele.oof_scores_ is None else modele.oof_scores_.shape})")
    chk(modele.cv_ is not None
        and abs(modele.cv_ - float((modele.oof_scores_.argmax(axis=1) == labels).mean())) < 1e-12,
        "...et `cv_` est EXACTEMENT la justesse de ces scores-là — les deux chiffres ne peuvent "
        "pas diverger, ils sortent de la même boucle")

    # --- 2. L'alignement de phase. Le test qui protège ce fichier. ----------------------------
    # Une fenêtre qui démarre au milieu du code doit être ramenée à la frame 0 avant d'être notée.
    # Si `scores` ne recalait pas (ou recalait dans le mauvais sens), RIEN ne lèverait : les
    # corrélations resteraient d'apparence normale et le décodage chercherait le code là où il
    # n'est pas. On exige donc les DEUX moitiés : avec la bonne phase ça marche, et en prétendant
    # la phase 0 sur la même fenêtre décalée, ça ne marche plus.
    from core.cvep_code import build_targets
    from core.cvep_decoder import synth_cvep
    code = build_targets()[1]
    bons_phase, bons_phase0, essais = 0, 0, 0
    for p in range(0, len(code), 7):
        cible = int(rng.integers(len(plan)))
        w = np.roll(synth_cvep(code, plan[cible]["lag"], n_ch, fs, refresh, -6.0, rng),
                    -modele._shift(p), axis=0)          # fenêtre démarrant à la phase p
        bons_phase += int(np.argmax(modele.scores(w, p, 1)) == cible)
        bons_phase0 += int(np.argmax(modele.scores(w, 0, 1)) == cible)
        essais += 1
    chk(bons_phase >= essais - 1,
        f"une fenêtre prise HORS bord de cycle est décodée quand on lui donne sa phase "
        f"({bons_phase}/{essais})")
    chk(bons_phase0 <= essais // 2,
        f"...et la MÊME fenêtre notée comme si elle commençait à la phase 0 se trompe "
        f"({bons_phase0}/{essais}) — c'est ce qui prouve que le recalage fait quelque chose")

    # 2 bis. La convention de phase est celle de l'eCCA, pas une convention maison. C'est ce qui
    # fait que le mode peut passer LA MÊME `phase` (celle de `CVEPRuntime.phase_a`) aux deux
    # décodeurs. L'eCCA est le décodeur validé au casque (22 bits/min) : c'est LUI la référence,
    # et deux conventions opposées se seraient annulées dans n'importe quel test écrit pour le
    # seul rCCA — c'est exactement comme ça que le défaut de signe ci-dessus avait survécu.
    from core.cvep_decoder import CVEPModel
    ecca = CVEPModel(fs=fs, refresh=refresh, code_len=len(code),
                     channels=list(range(n_ch))).fit(epochs, [plan[i]["lag"] for i in labels])
    lags = [c["lag"] for c in plan]
    accord = 0
    for p in range(0, len(code), 7):
        cible = int(rng.integers(len(plan)))
        w = np.roll(synth_cvep(code, plan[cible]["lag"], n_ch, fs, refresh, -6.0, rng),
                    -modele._shift(p), axis=0)
        sc_e = ecca.scores(w, p, lags, n_cycles=1)
        accord += int(max(sc_e, key=sc_e.get) == plan[cible]["lag"]
                      and int(np.argmax(modele.scores(w, p, 1))) == cible)
    chk(accord >= essais - 1,
        f"les DEUX décodeurs désignent la même cible sur la même fenêtre à la même phase : la "
        f"convention de phase est commune ({accord}/{essais})")

    # 2 ter. `_fold` moyenne les DERNIERS cycles, pas les premiers. Le moteur décode sur une
    # fenêtre glissante DÉLIBÉRÉMENT plus longue que sa décision : le surplus en tête sert de
    # marge au transitoire du passe-bande, et seuls les `n_cycles` derniers cycles démarrent à la
    # `phase` annoncée. Replier les PREMIERS cycles noterait un morceau de passé, à une phase
    # fausse, sans que rien ne lève. (Trouvé par analyse de mutation : `w[-k*n:]` -> `w[:k*n]`
    # laissait TOUT le reste de ce fichier vert, parce qu'aucune autre assertion n'utilise une
    # fenêtre de plus d'un cycle — or c'est exactement ce que le moteur passera.)
    leurre, vraie = 0, 4
    fen3 = np.concatenate([
        synth_cvep(code, plan[leurre]["lag"], n_ch, fs, refresh, -6.0, rng),
        synth_cvep(code, plan[vraie]["lag"], n_ch, fs, refresh, -6.0, rng),
        synth_cvep(code, plan[vraie]["lag"], n_ch, fs, refresh, -6.0, rng)])
    chk(int(np.argmax(modele.scores(fen3, 0, 1))) == vraie,
        f"sur 3 cycles dont le PREMIER est un leurre, un repli d'un cycle lit le DERNIER "
        f"({plan[int(np.argmax(modele.scores(fen3, 0, 1)))]['name']} pour "
        f"{plan[vraie]['name']} attendu)")
    chk(int(np.argmax(modele.scores(fen3, 0, 2))) == vraie,
        f"...et un repli de deux cycles lit les DEUX derniers, pas le leurre "
        f"({plan[int(np.argmax(modele.scores(fen3, 0, 2)))]['name']})")
    # ...et le repli est EXACTEMENT k cycles, ni plus ni moins. `n_cycles` est explicite et jamais
    # déduit de la longueur (même règle que `CVEPModel.fold`) : une fenêtre récupérée avec une
    # marge de filtrage ferait sinon passer k de 2 à 3 en silence, changeant la latence de décision
    # sans que rien ne le signale. Assertion sur `_fold` lui-même, parce que le décodage seul ne
    # le voit pas : replier 3 cycles au lieu des 2 demandés désigne encore la bonne cible ici.
    n = modele.n_cyc
    chk(np.allclose(modele._fold(fen3, 1), fen3[-n:]),
        "un repli d'un cycle rend EXACTEMENT le dernier cycle de la fenêtre")
    chk(np.allclose(modele._fold(fen3, 2), (fen3[-2 * n:-n] + fen3[-n:]) / 2.0),
        "un repli de deux cycles rend la moyenne des DEUX derniers, pas des trois")
    chk(np.allclose(modele._fold(fen3, 9), modele._fold(fen3, 3)),
        "demander plus de cycles que la fenêtre n'en contient les prend tous, sans lever")

    # --- 3. L'appariement score <-> cible, et le rejet. ---------------------------------------
    # `RCCADecoder` est la seule pièce qui relie un score à un NOM de cible. Décalée d'un cran,
    # elle désigne toujours la voisine, sans que rien ne lève.
    cible = 3
    fenetre = synth_cvep(code, plan[cible]["lag"], n_ch, fs, refresh, -6.0, rng)
    dec = RCCADecoder(modele, plan, corr_min=-1e9, margin=0.0, n_cycles=1)
    choisi, nommes = dec.classify(fenetre, 0)
    chk(choisi is not None and choisi["name"] == plan[cible]["name"],
        f"le décodeur nomme la cible RÉELLEMENT affichée ({None if choisi is None else choisi['name']} "
        f"au lieu de {plan[cible]['name']})")
    chk(set(nommes) == {c["name"] for c in plan}
        and max(nommes, key=nommes.get) == plan[cible]["name"],
        f"...et le score le plus haut porte SON nom, pas celui du voisin ({nommes})")

    # Le seuil de corrélation et la marge refusent chacun pour LEUR raison.
    sc = np.sort(modele.scores(fenetre, 0, 1))[::-1]
    trop_haut = RCCADecoder(modele, plan, corr_min=float(sc[0]) + 0.01, margin=0.0, n_cycles=1)
    chk(trop_haut.classify(fenetre, 0)[0] is None,
        f"un corr_min au-dessus du meilleur score fait refuser ({sc[0]:.3f})")
    marge_haute = RCCADecoder(modele, plan, corr_min=-1e9,
                              margin=float(sc[0] - sc[1]) + 0.01, n_cycles=1)
    chk(marge_haute.classify(fenetre, 0)[0] is None,
        f"une marge au-dessus de l'écart 1er-2e fait refuser aussi ({sc[0]-sc[1]:.3f})")

    # --- 4. Les seuils sortent des scores hors-pli, et de ceux-là seulement. -------------------
    # Jeu fabriqué à la main : 4 cibles, 24 essais, dont 22 corrects. Les valeurs sont choisies
    # pour que le quantile attendu se calcule DE TÊTE.
    faux = np.zeros((24, 4))
    y_f = np.zeros(24, dtype=int)
    for i in range(24):
        faux[i] = [0.10, 0.10, 0.10, 0.10]
        faux[i, 0] = 0.50 + i * 0.01          # gagnant : 0.50 ... 0.73
        faux[i, 1] = 0.30
    faux[22] = [0.0, 9.0, 0.0, 0.0]           # deux essais MAL classés, aux scores énormes :
    faux[23] = [0.0, 9.0, 0.0, 0.0]           # ils doivent être ignorés, sinon ils tirent tout
    corr_min, marge, n_bons = seuils_hors_pli(faux, y_f, garde=0.95, n_min=20)
    attendu_c = float(np.quantile(faux[:22, 0], 0.05))
    attendu_m = float(np.quantile(faux[:22, 0] - 0.30, 0.05))
    chk(n_bons == 22, f"seuls les essais CORRECTS de la validation croisée comptent ({n_bons}/24)")
    chk(corr_min is not None and abs(corr_min - attendu_c) < 1e-12,
        f"corr_min = le quantile qui garde 95 % de ces essais ({corr_min} vs {attendu_c})")
    chk(marge is not None and abs(marge - attendu_m) < 1e-12,
        f"margin = le même quantile sur l'écart gagnant-second ({marge} vs {attendu_m})")
    chk(corr_min < float(np.median(faux[:22, 0])),
        f"...un quantile BAS, pas la médiane : on cale sur « ne pas rater ce qui est bon » "
        f"({corr_min:.3f} < {np.median(faux[:22, 0]):.3f})")
    # Trop peu d'essais corrects : on refuse de poser un chiffre plutôt que d'en inventer un.
    _c, _m, n_court = seuils_hors_pli(faux[:10], y_f[:10], garde=0.95, n_min=20)
    chk(_c is None and _m is None and n_court == 10,
        f"sous le plancher d'essais, AUCUN seuil n'est rendu — un quantile à 5 % sur 10 points "
        f"vaut son minimum ({_c}, {_m}, {n_court})")

    # --- 5. Persistance : tableaux purs, décodeur DÉCLARÉ, aucun nom de classe gravé. ----------
    tmp = tempfile.mkdtemp(prefix="cvep_rcca_selftest_")
    try:
        chemin = modele.save(os.path.join(tmp, "cvep_rcca_model.npz"))
        relu = RCCAModel.load(chemin)
        chk(np.array_equal(relu.codes, modele.codes) and relu.n_targets == modele.n_targets
            and relu.code_len == modele.code_len,
            "un modèle rCCA écrit puis relu rend les MÊMES codes, bit pour bit")
        chk(relu.cv_ == modele.cv_ and relu.channels == modele.channels
            and relu.event == modele.event and relu.enc == modele.enc,
            f"...et ses métadonnées ({relu.cv_}, {relu.channels}, {relu.event}, {relu.enc})")
        with np.load(chemin, allow_pickle=True) as d:
            chk(str(d["decoder"]) == "rCCA",
                f"le fichier DÉCLARE son décodeur — c'est ce que `cvep_models` lit pour choisir "
                f"la classe ({d['decoder']})")
        chk("RCCAModel" not in open(chemin, "rb").read(4096).decode("latin-1"),
            "le fichier ne contient AUCUN nom de classe : c'est ce qui l'a rendu déplaçable, là "
            "où le P300 et l'ErrP ont perdu leurs modèles")
        # Le modèle rechargé DÉCODE encore : un save/load qui rend les bons tableaux mais un
        # classifieur non ré-ajusté passerait les assertions ci-dessus sans décoder quoi que ce soit.
        chk(int(np.argmax(relu.scores(fenetre, 0, 1))) == cible,
            "...et le modèle rechargé décode encore : le classifieur pyntbci a bien été ré-ajusté")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"[cvep-rcca] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    if len(sys.argv) > 2 and sys.argv[1] == "--seuils":
        sys.exit(0 if _rejouer(sys.argv[2]) else 1)
    sys.exit(0 if _selftest() else 1)
