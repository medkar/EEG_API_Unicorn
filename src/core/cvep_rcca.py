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
      k=1 (géométrie d'une ÉPOQUE de calib.)   eCCA 43/90 = 47,8 %   rCCA 43/90 = 47,8 %
      k=2 (géométrie DU MOTEUR)                eCCA 22/37 = 59,5 %   rCCA 24/37 = 64,9 %
      McNemar apparié à k=2 : 8 décisions discordantes sur 37 (3 eCCA seul, 5 rCCA seul), p = 0,727
      (hasard 16,7 % ; le rCCA contre le hasard : p = 0,0005 par permutation, 2000 tirages)

**Aucune différence n'est DÉTECTABLE entre les deux décodeurs sur ces données**, et c'est le
McNemar apparié qui le dit — pas l'égalité 43/90. Celle-là est une coïncidence de totaux, à une
géométrie que `core/config.py` déclare elle-même non représentative (le moteur décide sur
`CVEP_DECISION_CYCLES` cycles, pas un) ; à la géométrie du moteur les deux totaux ne sont plus
égaux, et c'est le test apparié, pas l'écart de pourcentage, qui autorise le mot. Reproductible :
`python src/core/cvep_rcca.py --seuils data/cvep_calib_last.npz` imprime les deux lignes.

⚠️ **« Pas de différence détectable » n'est PAS « équivalents ».** À 37 décisions, McNemar ne
verrait qu'un écart énorme. Ajouté à **une personne, une séance**, ça n'établit pas que les deux
décodeurs se valent en général : c'est une raison de ne pas JETER le rCCA, pas une preuve qu'il
vaut l'eCCA. C'est exactement pour ça que la calibration entraîne les DEUX, affiche les deux
chiffres, et ne nomme un gagnant que quand McNemar le défend.

Le rCCA sur codes Gold, lui, plafonnait à 35,6 % (`data/cvep_rcca_model.npz`, autre séance) : c'est
la moitié « codes Gold » de l'hypothèse qui était mauvaise, pas la reconvolution.

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

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (CVEP_BAND, CVEP_CHANNELS, CVEP_DECISION_CYCLES,  # noqa: E402
                         CVEP_RCCA_CORR_MIN, CVEP_RCCA_ENC, CVEP_RCCA_EVENT,
                         CVEP_RCCA_MARGIN, CVEP_RCCA_MODEL_PATH, FS_UNICORN, use_utf8_console)
from core.cvep_decoder import bandpass  # noqa: E402  (passe-bande zéro-phase partagé)


MSG_PYNTBCI = ("le décodeur c-VEP rCCA exige `pyntbci`, qui n'est pas installé : "
               "`pip install -r requirements.txt` (ou `pip install \"pyntbci>=1.9\"`). "
               "L'eCCA, lui, n'en dépend pas — les modèles eCCA restent utilisables.")


class PyntbciManquant(ImportError):
    """`pyntbci` absent — levée à la place d'un `ModuleNotFoundError` nu. Voir `MSG_PYNTBCI`.

    ⚠️ **Le NOM de cette classe fait partie du message**, et c'est délibéré :
    `core.cvep_models.charger` attrape toute exception et n'en garde que le TYPE
    (`f"modèle illisible ({type(e).__name__}) : {nom}"`). Avec un `ModuleNotFoundError` nu,
    l'étudiant lisait « modèle illisible (ModuleNotFoundError) : cvep_rcca_model.npz » et partait
    chercher un fichier corrompu là où il manque un `pip install`. Le message complet, lui, reste
    lisible partout où l'exception remonte : le moteur, `--seuils`, les autotests.

    ⚠️ **Ce qui reste à faire, HORS de ce fichier** (`core/cvep_models.py`, autre lot) : nommer ce
    cas explicitement (`except PyntbciManquant as e: return None, str(e)`) et surtout arrêter la
    disparition SILENCIEUSE — `modeles_disponibles` filtre sur `charger(c)[0] is not None`, donc
    sans la dépendance TOUS les modèles rCCA s'évaporent de la liste de la console sans un mot.
    Un fichier parfaitement bon qui disparaît est exactement la panne muette que ce module-là
    existe pour supprimer, retournée.
    """


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
        try:
            from pyntbci.classifiers import rCCA
        except ImportError as e:      # dépendance du MOTEUR : le dire, pas laisser deviner
            raise PyntbciManquant(MSG_PYNTBCI) from e
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

    def _hors_pli(self, X, y, groupes):
        """(scores, y_par_groupe) : pour chaque groupe, on ré-ajuste SANS aucun de ses cycles et
        on note la moyenne du groupe. `X` est déjà filtré, en (n_essais, n_ch, n_cyc).

        Sans effet de bord : c'est `_loo` (k=1, pour `fit`) et `hors_pli` (k quelconque, pour la
        mesure des seuils) qui l'appellent. Une seule boucle de ré-ajustement dans ce fichier, donc
        aucun risque que la géométrie de mesure et celle de la calibration divergent en silence.
        """
        scores = np.zeros((len(groupes), self.n_targets), dtype=float)
        yg = np.zeros(len(groupes), dtype=int)
        for j, g in enumerate(groupes):
            dehors = set(g)
            tr = [i for i in range(len(X)) if i not in dehors]
            clf = self._fit_clf(X[tr], y[tr])
            moyen = np.mean(X[list(g)], axis=0)[None]      # (1, n_ch, n_cyc)
            scores[j] = np.ravel(clf.decision_function(moyen))
            yg[j] = int(y[g[0]])
        return scores, yg

    def _loo(self, X, y):
        """Justesse leave-one-out (un cycle par décision), ET les scores hors-pli qui la produisent.

        On garde les SCORES et pas seulement le compte de bons coups : c'est la même boucle, et
        sans eux il faudrait la refaire ailleurs pour poser un seuil (N ré-ajustements pyntbci,
        soit ~8 s pour 90 essais sur ce poste). `cv_` reste la moyenne de `argmax == y`, donc
        les deux chiffres ne peuvent pas diverger.

        ⚠️ C'est un chiffre à **k=1**, la géométrie d'une ÉPOQUE de calibration — pas celle où le
        moteur décide (`CVEP_DECISION_CYCLES`). Pour mesurer à la géométrie de décision, c'est
        `hors_pli(..., n_cycles=…)`.
        """
        if len(X) < 3 or len(set(y.tolist())) < 2:
            self.oof_scores_, self.oof_y_ = None, None
            return None
        scores, yg = self._hors_pli(X, y, [(i,) for i in range(len(X))])
        self.oof_scores_, self.oof_y_ = scores, yg
        return float((scores.argmax(axis=1) == yg).mean())

    def hors_pli(self, epochs, labels, n_cycles=1):
        """(scores, y) — les scores de validation croisée à la géométrie `n_cycles`.

        Jumelle de `CVEPModel.hors_pli`, même contrat, pour que les deux décodeurs se comparent
        sur les mêmes époques ET la même géométrie. `epochs` : cycles BRUTS déjà réduits aux voies.

        ⚠️ Le modèle s'ajuste toujours sur des cycles SIMPLES (c'est ce que la calibration
        enregistre) et ne note que le groupe moyenné — exactement ce que fait le moteur, qui charge
        un modèle appris sur des cycles et lui présente une fenêtre repliée.
        """
        from core.cvep_decoder import groupes_de_cycles

        X = np.stack([bandpass(np.asarray(e, float), self.fs, self.band).T for e in epochs])
        y = np.asarray(labels, dtype=int)
        return self._hors_pli(X, y, groupes_de_cycles(y, n_cycles))

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
        ligne, lui, note à des phases quelconques (`archive/cvep_pilot.py`) : la variante
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
        # ⚠️ PAS d'`allow_pickle=True`. Ce format ne contient que des tableaux de types simples
        # (`fit` normalise les époques en float, donc jamais de tableau d'objets ragged), et le
        # drapeau autoriserait un `.npz` fabriqué à exécuter du code au chargement. Vérifié sur le
        # seul fichier réel du dépôt : `data/cvep_rcca_model.npz` se relit sans lui.
        d = np.load(path)
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

    # ⚠️ `n_cycles` vaut `CVEP_DECISION_CYCLES`, comme chez `CVEPDecoder`. Il valait 1 ici, sans
    # commentaire, et cette asymétrie n'était pas anodine : c'est la géométrie à laquelle le
    # décodeur décide, donc celle à laquelle ses seuils doivent être mesurés. Un décodeur réglé
    # sur des cycles simples et branché sur des fenêtres de deux cycles applique des seuils qui ne
    # décrivent pas ce qu'il fait — sans que rien ne le signale.
    def __init__(self, model, plan, corr_min=CVEP_RCCA_CORR_MIN, margin=CVEP_RCCA_MARGIN,
                 n_cycles=CVEP_DECISION_CYCLES):
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

    ⚠️ **C'est un critère de SENSIBILITÉ, et ce n'est PAS lui qui a fixé les seuils livrés.** Il
    répond à « quel plancher ne me fait rater aucun bon essai ? » — pas à « quel plancher rejette le
    bruit ? », qui est le travail réel d'un seuil de décision ici. Mesuré sur le seul jeu réel
    disponible, les deux questions donnent des réponses très différentes, et celle-ci donne un
    plancher SOUS le niveau du bruit (cf. `core/config.py`, où le choix est tranché et expliqué).
    Cette fonction reste livrée et testée parce qu'elle chiffre une borne utile — le plus bas qu'on
    puisse descendre sans perdre de bons essais — et parce que `--seuils` l'affiche à côté de
    l'autre couple, pour que la comparaison n'ait pas à être refaite à la main.

    Pour savoir ce qu'un couple de seuils FAIT réellement, c'est `point_de_fonctionnement`.
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


def point_de_fonctionnement(oof_scores, oof_y, corr_min, margin):
    """Ce qu'un couple de seuils FAIT, mesuré sur des scores hors-pli. Ne choisit rien, décrit.

    ⚠️ **Décrit — mais si vous CHOISISSEZ un couple en lisant ce tableau, le chiffre de la ligne
    retenue n'est plus une mesure : il est OPTIMISTE, parce qu'il a été sélectionné sur les mêmes
    décisions qui le produisent.** C'est exactement le cas des 0,24/0,08 livrés dans
    `core/config.py` : leur « 69 % de justesse quand le décodeur émet » a été lu sur les 37
    décisions de `data/cvep_calib_last.npz`, celles-là mêmes qui le mesurent. C'est un optimisme de
    SÉLECTION, distinct des deux réserves déjà écrites (généralisation « une personne, une séance »
    et petit n) — même famille que le `measured_on` de l'ErrP (« threshold chosen on these same
    out-of-fold scores, optimistic »). Le seul chiffre non biaisé se mesurerait sur une SECONDE
    séance, qui n'existe pas.

    Rend un dict de proportions dans [0, 1] :
      `corrects_gardes`  — part des essais BIEN classés que les seuils laissent passer (sensibilité) ;
      `emission`         — part de TOUS les essais sur lesquels le décodeur émettrait ;
      `justesse_si_emis` — part d'essais justes PARMI ceux émis (None si rien n'est émis) ;
      `n`, `n_corrects`  — de quoi juger si ces proportions veulent dire quelque chose.

    ⚠️ Un seuil ne se choisit pas sur `corrects_gardes` seul — c'est l'erreur que ce chantier a
    faite puis corrigée. Les trois chiffres se lisent ENSEMBLE : un seuil qui garde 88 % des bons
    essais mais fait émettre sur 89 % du total avec 48 % de justesse ne filtre rien. Et il manque
    ici le chiffre décisif, que des scores de calibration ne peuvent pas donner : la part de
    fenêtres « personne ne fixe » qui passeraient. `--seuils` la mesure sur du bruit blanc ; seul
    un enregistrement casque de repos yeux-ouverts la donnerait pour de vrai.
    """
    scores = np.asarray(oof_scores, dtype=float)
    y = np.asarray(oof_y, dtype=int)
    if scores.ndim != 2 or scores.shape[1] < 2 or len(y) != len(scores):
        raise ValueError(f"scores hors-pli mal formés : {scores.shape} pour {len(y)} étiquettes")
    # ⚠️ ZÉRO décision : `RCCAModel._hors_pli` PRÉ-ALLOUE `(0, n_targets)`, donc la garde de forme
    # ci-dessus laisse passer un tableau parfaitement bien formé qui ne contient RIEN. `np.mean`
    # d'un booléen vide rend `nan` — un `nan` là où cette docstring promet une proportion dans
    # [0, 1], puis un `ValueError: cannot convert float NaN to integer` plus loin chez l'appelant.
    # `None` partout, comme `entraine_les_deux` le fait déjà pour `justesse`/`n_cibles`.
    if len(y) == 0:
        return {"corrects_gardes": None, "emission": None, "justesse_si_emis": None,
                "n": 0, "n_corrects": 0}
    ordre = np.sort(scores, axis=1)[:, ::-1]
    gagnant, ecart = ordre[:, 0], ordre[:, 0] - ordre[:, 1]
    bons = scores.argmax(axis=1) == y
    # Exactement le test de `RCCADecoder.classify` — s'il divergeait, ce tableau décrirait un
    # décodeur qui n'existe pas.
    emis = (gagnant >= float(corr_min)) & (ecart >= float(margin))
    return {
        "corrects_gardes": float(emis[bons].mean()) if bons.any() else None,
        "emission": float(emis.mean()),
        "justesse_si_emis": float(bons[emis].mean()) if emis.any() else None,
        "n": int(len(y)),
        "n_corrects": int(bons.sum()),
    }


# --- Comparer DEUX décodeurs sur des décisions APPARIÉES (McNemar) ----------

def _mcnemar_p(b, c):
    """p-value BILATÉRALE EXACTE du test de McNemar, sur des décisions APPARIÉES.

    ⚠️ **C'est le test qui convient ici, et un test de deux proportions indépendantes serait le
    MAUVAIS test.** eCCA et rCCA sont notés sur les MÊMES groupes de cycles — même hasard du
    moment, même bruit, mêmes essais faciles ou difficiles. Comparer leurs deux justesses comme
    deux échantillons indépendants jetterait cette information et gonflerait la confiance dans un
    écart qui n'en a pas — exactement le péché cardinal que ce dépôt s'interdit (`CLAUDE.md`,
    « rigueur statistique »), déjà commis une fois pour le Motor Imagery. Deux pourcentages ÉGAUX
    ne sont pas plus un test que deux pourcentages différents : rien ne dit que ce sont les MÊMES
    décisions.

    `b` = décisions où SEUL eCCA est correct, `c` = décisions où SEUL rCCA l'est. Sous H0 (les
    deux décodeurs se valent), `b` suit Binomial(b+c, 1/2) ; la p-value est la somme des
    probabilités de tous les résultats AU MOINS aussi improbables que celui observé — la
    définition standard du test binomial exact bilatéral (`scipy.stats.binomtest`, `R
    binom.test`). Sans dépendance à `scipy.stats` : `math.comb` suffit, et le calcul se relit
    entièrement dans ces quelques lignes.

    ⚠️ **Vit dans `core/` et pas dans `research/cvep_calibrate.py`, où il est né** (commit
    `bd3b588`) : `core/cvep_rcca.py::_rejouer` en a besoin aussi, et `core/` n'importe JAMAIS
    `research/`. C'est la règle du dépôt appliquée telle quelle — « si l'envie s'en présente, c'est
    que le module visé doit DÉMÉNAGER dans `core` ». `cvep_calibrate` le ré-importe d'ici.

    Vérifié contre la seule séance réelle disponible : b=3, c=5 -> p=0,7265625, IDENTIQUE (à
    l'arrondi) au p=0,727 mesuré indépendamment par la revue.
    """
    n = b + c
    if n == 0:
        return 1.0
    probs = [math.comb(n, i) * (0.5 ** n) for i in range(n + 1)]
    p_obs = probs[min(b, c)]
    return min(1.0, sum(p for p in probs if p <= p_obs + 1e-12))


# Seuil de significativité usuel (5 %) — pas ajusté sur les données de ce dépôt : un seuil qui
# aurait été choisi POUR faire ressortir tel ou tel gagnant ne prouverait plus rien.
SEUIL_MCNEMAR = 0.05


# --- Rejouer une calibration réelle (LECTURE SEULE) -------------------------

def _bruit_gagnant_ecart(scoreur, n_cyc, n_ch, k, sigma, n=300, seed=0):
    """(gagnant, écart) sur `n` fenêtres de BRUIT PUR — le chiffre qui décide d'un seuil.

    `scoreur(fenêtre, phase, k)` note une fenêtre : `RCCAModel.scores` ou une petite enveloppe
    autour de `CVEPModel.scores`, pour que les deux décodeurs soient mesurés du même geste.

    « Bruit pur » = du bruit blanc de même écart-type que les époques filtrées, la convention que
    `cvep_decoder._demo` utilise déjà pour « regard nulle part ». On rend les DEUX tableaux plutôt
    qu'un taux : tous les couples de seuils s'évaluent alors sur le MÊME échantillon de bruit, ce
    qui rend leurs colonnes comparables entre elles (et fait une seule passe au lieu d'une par
    couple).

    ⚠️ C'est une APPROXIMATION du vrai cas à rejeter — un EEG de repos yeux ouverts porte de
    l'alpha, pas du bruit blanc. Elle donne un ordre de grandeur. Trancher pour de bon demande un
    enregistrement casque de « la personne ne fixe rien », qui n'existe dans aucun fichier du dépôt.
    """
    rng = np.random.default_rng(seed)
    gagnant, ecart = np.zeros(n), np.zeros(n)
    for i in range(n):
        sc = np.sort(np.ravel(scoreur(rng.normal(0.0, sigma, (k * n_cyc, n_ch)), 0, k)))[::-1]
        gagnant[i], ecart[i] = sc[0], sc[0] - sc[1]
    return gagnant, ecart


def _rejouer(chemin, n_bruit=300):
    """Rejoue un `cvep_calib_*.npz` à travers **les deux décodeurs** et **les deux géométries**, et
    imprime ce que valent plusieurs couples de seuils.

    ⚠️ **Ce fichier n'est jamais modifié** : `data/` contient des enregistrements EEG d'une
    personne identifiable, sur un dépôt public. On lit, on calcule, on imprime. (`data/` est
    entièrement gitignoré : `git status` ne prouve donc RIEN sur ce point — se vérifie par
    l'horodatage.)

    Trois choses que cette commande rend vérifiables au lieu d'être à croire :

    1. **l'absence de différence DÉTECTABLE entre eCCA et rCCA**, l'affirmation qui justifie de
       réintégrer le rCCA — testée par **McNemar apparié sur les MÊMES groupes de cycles**, pas par
       deux pourcentages côte à côte (`bd3b588` a banni cette comparaison de l'écran de
       calibration ; elle n'a pas plus de valeur ici, et deux pourcentages ÉGAUX n'en ont pas
       davantage : rien ne dit que ce sont les mêmes décisions) ;
    2. **l'effet de la GÉOMÉTRIE**. Une calibration enregistre un cycle par époque, le moteur
       décide sur `CVEP_DECISION_CYCLES`. Des seuils mesurés à k=1 ne décrivent pas le décodeur
       qui tourne — la ligne « k=2 » est celle qui compte pour `config.py` ;
    3. **le point de fonctionnement** de chaque couple, au lieu du seul seuil.

    Le projet s'est déjà fait avoir : les seuils de l'ErrP ont été posés par un script jetable et
    non versionné, et `errp_models.py` porte encore le regret de ne pas pouvoir dire à un étudiant
    comment les refaire. Ici, la commande est la trace.

    Rend **True si au moins une géométrie a produit une décision**, False sinon (fichier refusé,
    ou aucune paire de cycles consécutifs nulle part) : `sys.exit(0 if _rejouer(...) else 1)`
    n'avait aucun sens tant que cette fonction rendait `True` en dur — le défaut exact que la
    tâche 3 venait de corriger dans le jumeau `research/cvep_rcca.py::_demo`.
    """
    from core.cvep_code import build_targets
    from core.config import (CVEP_CORR_MIN, CVEP_MARGIN, CVEP_RCCA_CORR_MIN,
                             CVEP_RCCA_MARGIN)
    from core.cvep_decoder import CVEPModel, bandpass as _bp, groupes_de_cycles

    plan, code = build_targets()
    codes = np.stack([np.asarray(c["code"], dtype=int) for c in plan])
    lag_de_cible = [c["lag"] for c in plan]
    # ⚠️ UN refus nommé, AVANT tout calcul, pour toute la famille « ce fichier ne décrit pas le
    # stimulus affiché aujourd'hui ». Sans lui : `d["lags"]` sur un `.npz` qui n'est pas une
    # calibration -> `KeyError` ; `lag_de_cible.index(l)` sur une séance enregistrée à un autre
    # `CVEP_LAG_ROTATION` / `CVEP_N_TARGETS` / `CVEP_BITS` -> `ValueError: 21 is not in list`.
    # Trois tracebacks pour une seule cause, sur une commande qui accepte n'importe quel chemin
    # tapé par un étudiant. `core.cvep_models.charger` nomme déjà ce cas ; on dit la même chose.
    try:
        d = np.load(chemin)
        lags = [int(l) for l in d["lags"]]
        voies = [int(c) for c in d["channels"]]
        fs, refresh = float(d["fs"]), float(d["refresh"])
        epochs = [d["epochs"][i][:, voies] for i in range(len(d["epochs"]))]
        y = np.asarray([lag_de_cible.index(l) for l in lags])
    except Exception as e:      # noqa: BLE001 - un .npz étranger casse de mille façons équivalentes
        print(f"[seuils] ⛔ {os.path.basename(chemin)} n'est pas une calibration du stimulus "
              f"AFFICHÉ AUJOURD'HUI ({type(e).__name__}: {e}).")
        print(f"[seuils]    Soit ce n'est pas un `cvep_calib_*.npz` (il lui manque `lags`, "
              f"`epochs`, `channels`, `fs` ou `refresh`) ; soit il a été enregistré sur d'AUTRES "
              f"cibles — le plan d'aujourd'hui affiche les lags {lag_de_cible}, et un fichier "
              f"calibré à un autre CVEP_BITS / CVEP_TAPS / CVEP_N_TARGETS / CVEP_LAG_ROTATION en "
              f"porte d'autres. Rien à rejouer : même refus que `core.cvep_models.charger`.")
        return False

    rcca = RCCAModel(codes, fs=fs, refresh=refresh,
                     channels=list(range(len(voies)))).fit(epochs, y, compute_cv=False)
    ecca = CVEPModel(fs=fs, refresh=refresh, code_len=len(code),
                     channels=list(range(len(voies))))
    ecca.fit(epochs, lags)
    uniq = sorted(set(lags))
    sigma = float(np.std([_bp(e, fs, rcca.band) for e in epochs]))

    print(f"[seuils] {os.path.basename(chemin)} : {len(y)} cycles, {rcca.n_targets} cibles, "
          f"voies {voies}, {fs:.0f} Hz / {refresh:.0f} Hz")
    print(f"[seuils] ⚠️ UNE personne, UNE séance : ces chiffres ne valent que pour CE fichier, et "
          f"les justesses portent sur peu de décisions — lire les écarts avec prudence.")
    print(f"[seuils] ⚠️ Et le couple de seuils que vous retiendrez EN LISANT le tableau ci-dessous "
          f"aura un point de fonctionnement OPTIMISTE : il aura été choisi sur ces décisions-là, "
          f"celles-là mêmes qui le mesurent. C'est le cas des 0,24/0,08 livrés dans config.py. "
          f"Un chiffre non biaisé demanderait une SECONDE séance.")

    mesuree = False           # au moins une géométrie a-t-elle produit quelque chose ?
    for k in (1, CVEP_DECISION_CYCLES):
        n_dec = len(groupes_de_cycles(y, k))
        titre = "géométrie d'une ÉPOQUE de calibration" if k == 1 else \
                "géométrie de DÉCISION DU MOTEUR (CVEP_DECISION_CYCLES)"
        print(f"\n[seuils] === k = {k} cycle(s) par décision — {titre} : {n_dec} décisions ===")
        # ⚠️ Fermer ce chemin ICI, avant tout calcul, et pas le deviner en aval : à zéro groupe,
        # `CVEPModel.hors_pli` rend `(0,)` (AxisError sur `.argmax(axis=1)`) tandis que
        # `RCCAModel.hors_pli` rend `(0, n_cibles)`, qui passe les gardes de forme et fabrique un
        # `nan` — trois tracebacks différents pour une seule et même cause. Ce n'est pas
        # théorique : le protocole `--smoke` d'origine coupait systématiquement toute paire de
        # cycles consécutifs (mesuré, cf. `research/cvep_calibrate.calibrate`).
        if n_dec == 0:
            print(f"[seuils]   ⛔ AUCUN groupe de {k} cycles CONSÉCUTIFS de la même cible dans ce "
                  f"fichier — rien à mesurer à cette géométrie, et ce n'est pas une panne : "
                  f"`groupes_de_cycles` ÉCARTE (sans les rogner) les groupes à cheval sur un "
                  f"changement de cible, donc une séance courte ou très fragmentée n'en laisse "
                  f"aucun. Recalibrer avec plus de cycles consécutifs par cible.")
            continue
        mesuree = True

        sc_r, y_r = rcca.hors_pli(epochs, y, n_cycles=k)
        sc_e, y_e, _ = ecca.hors_pli(epochs, lags, n_cycles=k)
        loo_r = float((sc_r.argmax(axis=1) == y_r).mean())
        loo_e = float((sc_e.argmax(axis=1) == y_e).mean())
        print(f"[seuils]   leave-one-out   rCCA {loo_r*100:5.1f} % "
              f"({int(round(loo_r*n_dec))}/{n_dec})   "
              f"eCCA {loo_e*100:5.1f} % ({int(round(loo_e*n_dec))}/{n_dec})   "
              f"hasard {100/rcca.n_targets:.1f} %")
        # ⚠️ Les deux lignes ci-dessus sont deux POURCENTAGES BRUTS : elles décrivent, elles ne
        # comparent pas. Ce qui compare, c'est la ligne suivante. `groupes_de_cycles(y, k)` et
        # `groupes_de_cycles(lags, k)` parcourent des étiquettes en BIJECTION (`y[i] =
        # lag_de_cible.index(lags[i])`), donc rendent la MÊME liste de groupes dans le MÊME
        # ordre : `sc_r[j]` et `sc_e[j]` notent le même groupe de cycles, et les décisions sont
        # APPARIÉES — la condition qui rend McNemar applicable et un test de deux proportions
        # indépendantes faux.
        ok_r, ok_e = sc_r.argmax(axis=1) == y_r, sc_e.argmax(axis=1) == y_e
        # `b` / `c` de McNemar, nommés en toutes lettres : plus bas, `c` est le `corr_min` de la
        # boucle des candidats, et deux `c` dans la même fonction se relisent très mal.
        b_ecca_seul, c_rcca_seul = int((ok_e & ~ok_r).sum()), int((ok_r & ~ok_e).sum())
        p_mcnemar = _mcnemar_p(b_ecca_seul, c_rcca_seul)
        print(f"[seuils]   McNemar apparié (MÊMES groupes) : eCCA seul {b_ecca_seul}, rCCA seul "
              f"{c_rcca_seul} -> {b_ecca_seul + c_rcca_seul} décisions discordantes sur {n_dec}, "
              f"p={p_mcnemar:.3f} — "
              + ("aucune différence détectable entre les deux décodeurs (ce qui n'est PAS "
                 "« ils se valent »)" if p_mcnemar >= SEUIL_MCNEMAR else "écart DÉFENDABLE"))

        bruit = {
            "rCCA": _bruit_gagnant_ecart(rcca.scores, rcca.n_cyc, len(voies), k, sigma, n_bruit),
            "eCCA": _bruit_gagnant_ecart(
                lambda w, p, kk: list(ecca.scores(w, p, uniq, n_cycles=kk).values()),
                ecca.n_cyc, len(voies), k, sigma, n_bruit),
        }

        q05 = seuils_hors_pli(sc_r, y_r)
        candidats = [(CVEP_RCCA_CORR_MIN, CVEP_RCCA_MARGIN, "LIVRÉS pour le rCCA (config.py)")]
        if (CVEP_CORR_MIN, CVEP_MARGIN) != (CVEP_RCCA_CORR_MIN, CVEP_RCCA_MARGIN):
            candidats.append((CVEP_CORR_MIN, CVEP_MARGIN,
                              "seuils eCCA livrés (CVEP_CORR_MIN/MARGIN)"))
        if q05[0] is not None:
            candidats.append((q05[0], q05[1], f"quantile 5 % rCCA — SENSIBILITÉ, pas rejet "
                                              f"({q05[2]} essais corrects)"))
        def _pct(v, largeur):
            """« — » plutôt qu'un plantage. `corrects_gardes`, `emission` et `justesse_si_emis`
            valent `None` quand il n'y a rien à décrire : aucun essai correct dans la validation
            croisée, aucune émission, aucune décision. `None * 100` était le TROISIÈME traceback
            de la famille « rien à mesurer » (seul `justesse_si_emis` était protégé), et le plus
            probable des trois sur une séance médiocre — 6 cibles, 12 décisions, zéro correcte
            arrive une fois sur neuf par pur hasard."""
            return f"{v*100:{largeur}.0f} %" if v is not None else f"{'—':>{largeur}}  "

        print(f"[seuils]     seuils      | déc. | corrects gardés | émission | justesse si émis "
              f"| bruit passé")
        for c, mg, nom in candidats:
            for nom_dec, sc, yy in (("rCCA", sc_r, y_r), ("eCCA", sc_e, y_e)):
                pf = point_de_fonctionnement(sc, yy, c, mg)
                g, e = bruit[nom_dec]
                br = float(((g >= c) & (e >= mg)).mean())
                print(f"[seuils]  {c:6.3f} /{mg:6.3f} | {nom_dec} |"
                      f"{_pct(pf['corrects_gardes'], 12)} |{_pct(pf['emission'], 7)} |"
                      f"{_pct(pf['justesse_si_emis'], 14)} |{br*100:9.0f} %"
                      + (f"   <- {nom}" if nom_dec == "rCCA" else ""))
    if not mesuree:
        print(f"\n[seuils] ⛔ AUCUNE géométrie n'a produit la moindre décision sur ce fichier — "
              f"il n'y a rien à en tirer. (Sortie en 1 : c'est un échec, pas un rapport vide.)")
    # ⚠️ `mesuree` et non `True` en dur : `sys.exit(0 if _rejouer(...) else 1)` avait une branche
    # MORTE. Ce qui la rend vivante aujourd'hui, et ce qui est testé, c'est le `return False` du
    # refus de fichier ci-dessus ; cette ligne-ci reste défensive (k=1 ne rend `[]` que sur un
    # fichier à ZÉRO époque, que `fit` refuserait avant d'arriver ici).
    return mesuree


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
    #
    # ⚠️ **Ce n'est PAS un test d'accord, c'est un test de JUSTESSE doublé, et c'est CE qui le rend
    # robuste.** Les deux membres du `and` ci-dessous comparent chacun à la VÉRITÉ TERRAIN
    # (`plan[cible]["lag"]`, `cible`), jamais l'un à l'autre. La raison est mesurable : sous une
    # inversion SIMULTANÉE des deux conventions de phase, les deux décodeurs désignent la MÊME
    # cible fausse (celle de lag `lag_vrai + 2p`) — un test d'accord pur resterait donc vert, sur
    # 8 des 9 phases parcourues (la 9e est p=0, où `2p ≡ 0 mod 63` puisque 63 est impair). Exiger
    # la cible RÉELLEMENT AFFICHÉE, elle, rougit. C'est aussi la SEULE assertion du dépôt qui
    # épingle la convention de phase de l'eCCA : `cvep_decoder._demo` fait le même geste mais
    # IMPRIME sans affirmer, et `_loo`/`hors_pli` n'époquent qu'à la phase 0.
    # ⛔ Ne pas « simplifier » en comparant les deux sorties entre elles : c'est la seule voie par
    # laquelle ce garde peut être détruit sans que rien ne le signale.
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
        f"les DEUX décodeurs désignent la cible RÉELLEMENT AFFICHÉE, sur la même fenêtre à la "
        f"même phase : la convention de phase est commune ({accord}/{essais}). ⚠️ JUSTESSE et non "
        f"ACCORD, délibérément — deux conventions inversées ENSEMBLE se mettraient d'accord sur "
        f"la cible de lag `lag_vrai + 2p` et un test d'accord resterait vert")

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

    # ⚠️ Le DÉFAUT de `n_cycles` doit être celui de son jumeau `CVEPDecoder`. Il valait 1 ici, sans
    # commentaire : le décodeur décidait alors sur un cycle là où l'eCCA en prend deux, donc ses
    # seuils — mesurés à deux cycles — ne décrivaient pas ce qu'il faisait. Une asymétrie de
    # défaut entre deux classes jumelles ne se voit dans aucun test qui passe ses paramètres.
    from core.cvep_decoder import CVEPDecoder
    import inspect
    defaut_rcca = inspect.signature(RCCADecoder.__init__).parameters["n_cycles"].default
    defaut_ecca = inspect.signature(CVEPDecoder.__init__).parameters["n_cycles"].default
    chk(defaut_rcca == defaut_ecca == CVEP_DECISION_CYCLES,
        f"les deux décodeurs décident sur le MÊME nombre de cycles par défaut "
        f"(rCCA {defaut_rcca}, eCCA {defaut_ecca}, CVEP_DECISION_CYCLES {CVEP_DECISION_CYCLES})")

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

    # --- 3 ter. La GÉOMÉTRIE de mesure, et le fait qu'elle change les chiffres. ----------------
    # Un seuil se mesure à la géométrie où il servira. La calibration enregistre UN cycle par
    # époque, le moteur décide sur `CVEP_DECISION_CYCLES` : mesurer à k=1 et poser le seuil pour
    # un décodeur qui tourne à k=2 décrit un décodeur qui n'existe pas. `groupes_de_cycles` est
    # la pièce qui rend la mesure à k possible, et son piège est la FRONTIÈRE entre deux cibles.
    from core.cvep_decoder import groupes_de_cycles
    # Trois cibles, trois cycles chacune : à k=2, le 3e cycle de chaque cible n'a pas de voisin de
    # la même cible, donc les groupes (2,3) et (5,6) sont écartés — 3 décisions au lieu de 4.
    etiquettes = [0, 0, 0, 1, 1, 1, 2, 2, 2]
    chk(groupes_de_cycles(etiquettes, 1) == [(i,) for i in range(9)],
        f"à k=1, chaque cycle est son propre groupe ({groupes_de_cycles(etiquettes, 1)})")
    chk(groupes_de_cycles(etiquettes, 2) == [(0, 1), (3, 4), (6, 7)],
        f"à k=2, on groupe des cycles CONSÉCUTIFS de la MÊME cible, et un groupe à cheval sur "
        f"une frontière est ÉCARTÉ, pas rogné ({groupes_de_cycles(etiquettes, 2)})")
    chk(all(len({etiquettes[i] for i in g}) == 1 for g in groupes_de_cycles(etiquettes, 3)),
        "...à k=3 aussi : jamais deux cibles dans le même groupe, sinon on moyennerait deux "
        "réponses différentes et on fabriquerait une époque que le moteur ne verra jamais")
    chk(len(groupes_de_cycles(etiquettes, 2)) < len(etiquettes) // 2,
        f"...et il y a donc MOINS de décisions que de cycles/k : c'est ce qui fait 37 décisions "
        f"et non 45 sur les 90 cycles réels ({len(groupes_de_cycles(etiquettes, 2))})")

    # ...et la géométrie remonte jusqu'aux scores hors-pli : moins de décisions, et des scores
    # calculés sur des cycles MOYENNÉS. Sans ça, `--seuils` mesurerait toujours à k=1 en croyant
    # mesurer à k=2 — l'erreur exacte que ce tour de revue a corrigée.
    sc1, y1 = modele.hors_pli(epochs, labels, n_cycles=1)
    sc2, y2 = modele.hors_pli(epochs, labels, n_cycles=2)
    chk(sc1.shape == (len(labels), len(plan)) and len(y1) == len(labels),
        f"à k=1, un score hors-pli par cycle ({sc1.shape})")
    chk(sc2.shape[0] == len(groupes_de_cycles(labels, 2)) and sc2.shape[0] < sc1.shape[0],
        f"à k=2, un score par GROUPE, et il y en a moins ({sc2.shape} contre {sc1.shape})")
    chk(np.allclose(sc1, modele.oof_scores_) and np.array_equal(y1, modele.oof_y_),
        "à k=1, `hors_pli` rend EXACTEMENT ce que `fit(compute_cv=True)` avait déjà mesuré — une "
        "seule boucle de ré-ajustement dans ce fichier, donc pas deux géométries qui divergent")
    chk(float((sc2.argmax(axis=1) == y2).mean()) >= float((sc1.argmax(axis=1) == y1).mean()),
        f"...et moyenner deux cycles ne DÉGRADE pas la justesse ({(sc2.argmax(axis=1)==y2).mean():.2f} "
        f"contre {(sc1.argmax(axis=1)==y1).mean():.2f}) — c'est tout l'intérêt du repli")

    # ⚠️ HORS-PLI VEUT DIRE HORS-PLI, et c'est CE test qui le prouve — jumeau exact de celui de
    # `cvep_decoder._selftest`. Si le groupe noté restait dans le jeu d'ajustement, rien ne
    # lèverait : les chiffres monteraient, ils auraient l'air meilleurs, et TOUS les seuils posés
    # par `--seuils` seraient optimistes. On le rend visible en donnant du BRUIT PUR étiqueté au
    # hasard : il n'y a rien à décoder, donc la seule justesse honnête est le hasard (1/6).
    # MESURÉ sur ce jeu : 8,3 % hors-pli — et **75 % si l'exclusion saute**.
    rng_b = np.random.default_rng(5)
    bruit = [rng_b.normal(0.0, 1.0, (modele.n_cyc, n_ch)) for _ in range(12)]
    y_bruit = np.asarray([i for i in range(len(plan)) for _ in range(2)])
    sc_b, y_b = RCCAModel(codes, fs=fs, refresh=refresh,
                          channels=list(range(n_ch))).hors_pli(bruit, y_bruit, n_cycles=1)
    just_bruit = float((sc_b.argmax(axis=1) == y_b).mean())
    chk(just_bruit <= 0.35,
        f"sur du BRUIT PUR, la validation croisée reste au niveau du hasard "
        f"({just_bruit*100:.1f} % pour {100/len(plan):.1f} %) — si le groupe noté restait dans "
        f"l'ajustement, ce même jeu monterait à 75 %, mesuré")

    # --- 4 bis. Ce qu'un couple de seuils FAIT. --------------------------------------------
    # C'est CETTE fonction qui a fait changer d'avis sur les seuils livrés : le quantile à 5 %
    # gardait 88 % des bons essais tout en faisant émettre sur 89 % du total, donc en ne filtrant
    # rien. Un seuil ne se juge pas sur la sensibilité seule, et les trois chiffres doivent être
    # calculés séparément — les confondre est exactement l'erreur qu'on vient de corriger.
    #
    # Jeu fabriqué pour que les trois proportions soient DEUX À DEUX DIFFÉRENTES (sinon une
    # mutation qui rend l'une à la place de l'autre resterait verte) : 13 essais, 10 bien classés,
    # et 3 mal classés qui passent TOUS — le cas dangereux, un seuil que le faux franchit mieux
    # que le juste. ⚠️ Les deux essais `[0.50, 0.45]` sont là POUR la marge : ils ont un gagnant
    # très au-dessus de `corr_min` et un écart en dessous de `margin`, donc seule la marge peut
    # les refuser. Trouvé par analyse de mutation — sans eux, comparer `margin` au GAGNANT au lieu
    # de l'ÉCART laissait tout vert.
    pf_scores = np.zeros((13, 2))
    pf_y = np.zeros(13, dtype=int)
    pf_scores[:6] = [0.40, 0.10]          # corrects, au-dessus des deux seuils (écart 0.30)
    pf_scores[6:8] = [0.20, 0.15]         # corrects, refusés par corr_min      (écart 0.05)
    pf_scores[8:10] = [0.50, 0.45]        # corrects, refusés par la MARGE SEULE (écart 0.05)
    pf_scores[10:] = [0.05, 0.45]         # MAL classés, et ils passent         (écart 0.40)
    pf = point_de_fonctionnement(pf_scores, pf_y, corr_min=0.30, margin=0.10)
    chk(pf["n"] == 13 and pf["n_corrects"] == 10,
        f"le décompte des essais et des essais corrects ({pf['n']}, {pf['n_corrects']})")
    chk(abs(pf["corrects_gardes"] - 6 / 10) < 1e-12,
        f"« corrects gardés » se compte sur les essais BIEN CLASSÉS seulement "
        f"({pf['corrects_gardes']} pour 6/10)")
    chk(abs(pf["emission"] - 9 / 13) < 1e-12,
        f"« émission » se compte sur TOUS les essais ({pf['emission']} pour 9/13)")
    chk(abs(pf["justesse_si_emis"] - 6 / 9) < 1e-12,
        f"« justesse si émis » se compte sur les essais ÉMIS ({pf['justesse_si_emis']} pour 6/9)")
    chk(len({round(pf["corrects_gardes"], 9), round(pf["emission"], 9),
             round(pf["justesse_si_emis"], 9)}) == 3,
        f"...et les trois chiffres sont deux à deux DIFFÉRENTS sur cette fixture — c'est ce qui "
        f"interdit d'en rendre un à la place d'un autre ({pf})")
    # Des seuils que personne ne franchit ne font pas diviser par zéro — l'état d'un mode muet.
    pf_muet = point_de_fonctionnement(pf_scores, pf_y, corr_min=9.0, margin=0.0)
    chk(pf_muet["emission"] == 0.0 and pf_muet["justesse_si_emis"] is None
        and pf_muet["corrects_gardes"] == 0.0,
        f"des seuils infranchissables rendent « aucune émission » sans lever ({pf_muet})")
    # ...et le test appliqué est EXACTEMENT celui de `RCCADecoder.classify`, sinon ce tableau
    # décrirait un décodeur qui n'existe pas. Vérifié en le rejouant sur le vrai décodeur.
    sc_reel = modele.scores(fenetre, 0, 1)
    ordre_reel = np.sort(sc_reel)[::-1]
    dec_strict = RCCADecoder(modele, plan, corr_min=float(ordre_reel[0]),
                             margin=float(ordre_reel[0] - ordre_reel[1]), n_cycles=1)
    pf_reel = point_de_fonctionnement(sc_reel[None], np.array([int(np.argmax(sc_reel))]),
                                      dec_strict.corr_min, dec_strict.margin)
    chk((dec_strict.classify(fenetre, 0)[0] is not None) == (pf_reel["emission"] == 1.0),
        f"au seuil EXACT du score, la description et le décodeur décident pareil — les deux "
        f"comparent avec un >= ({pf_reel['emission']})")

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
        # ⚠️ `d["decoder"] if "decoder" in d.files` et pas `d["decoder"]` tout court : sans la
        # garde, une `save` qui cesserait d'écrire le champ ferait sortir un `KeyError` et un
        # traceback au lieu d'un ÉCHEC nommé — c'est-à-dire que la panne la plus probable de cette
        # ligne serait la moins lisible. Même durcissement que dans `cvep_models.charger`.
        # `allow_pickle` n'est PAS demandé : ce format n'a que des tableaux de types simples,
        # et c'est vérifié plus bas (aucun nom de classe dans le fichier).
        with np.load(chemin) as d:
            declare = str(d["decoder"]) if "decoder" in d.files else None
            chk(declare == "rCCA",
                f"le fichier DÉCLARE son décodeur — c'est ce que `cvep_models` lit pour choisir "
                f"la classe ({declare})")
        chk("RCCAModel" not in open(chemin, "rb").read(4096).decode("latin-1"),
            "le fichier ne contient AUCUN nom de classe : c'est ce qui l'a rendu déplaçable, là "
            "où le P300 et l'ErrP ont perdu leurs modèles")
        # Le modèle rechargé DÉCODE encore : un save/load qui rend les bons tableaux mais un
        # classifieur non ré-ajusté passerait les assertions ci-dessus sans décoder quoi que ce soit.
        chk(int(np.argmax(relu.scores(fenetre, 0, 1))) == cible,
            "...et le modèle rechargé décode encore : le classifieur pyntbci a bien été ré-ajusté")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- 6. `--seuils` REFUSE au lieu de mourir, et sort en 1 quand il n'a rien mesuré. --------
    # `_rejouer` accepte n'importe quel chemin tapé par un étudiant, et rendait `True` EN DUR :
    # `sys.exit(0 if _rejouer(...) else 1)` avait donc une branche morte, et les trois pannes
    # ci-dessous sortaient en traceback avec un code 0. Les fixtures sont écrites dans un dossier
    # TEMPORAIRE : `data/` n'est jamais lu ni écrit par cet autotest.
    import contextlib
    import io

    def _rejoue_capture(chemin):
        """(rendu, texte imprimé) — on juge sur les DEUX : un refus qui ne dit rien ne vaut pas
        mieux qu'un traceback, et un message parfait qui sort en 0 non plus."""
        cap = io.StringIO()
        with contextlib.redirect_stdout(cap):
            rendu = _rejouer(chemin, n_bruit=3)
        return rendu, cap.getvalue()

    tmp6 = tempfile.mkdtemp(prefix="cvep_rcca_seuils_")
    try:
        n_cyc = modele.n_cyc
        voies_f = list(range(n_ch))

        def _ecrire_calib(nom, lags_fixture, **extra):
            ch = os.path.join(tmp6, nom)
            n = len(lags_fixture)
            np.savez(ch, epochs=rng.normal(0.0, 1.0, (n, n_cyc, n_ch)),
                     lags=np.asarray(lags_fixture, dtype=int),
                     channels=np.asarray(voies_f, dtype=int), fs=fs, refresh=refresh, **extra)
            return ch

        # (a) m8 — le fichier a été calibré sur d'AUTRES cibles : `lag_de_cible.index(l)` levait
        #     `ValueError: 21 is not in list`, un traceback pour une cause parfaitement nommable.
        lag_etranger = max(lags) + 1
        chk(lag_etranger not in lags, f"fixture : {lag_etranger} n'est VRAIMENT pas un lag du plan")
        perime = _ecrire_calib("cvep_calib_perime.npz", [lag_etranger] * 4 + [lags[0]] * 4)
        rendu_a, txt_a = _rejoue_capture(perime)
        chk(rendu_a is False and "⛔" in txt_a and "AUTRES cibles" in txt_a
            and "cvep_calib_perime.npz" in txt_a,
            f"--seuils sur un fichier aux lags PÉRIMÉS refuse en le nommant et sort en 1, au lieu "
            f"d'un `ValueError: {lag_etranger} is not in list` ({rendu_a}, {txt_a.strip()[:90]!r})")

        # (b) m8 bis — ce n'est pas une calibration du tout (un `.npz` sans `lags`) : `KeyError`.
        pas_calib = os.path.join(tmp6, "pas_une_calib.npz")
        np.savez(pas_calib, quelque_chose=np.zeros(3))
        rendu_b, txt_b = _rejoue_capture(pas_calib)
        chk(rendu_b is False and "⛔" in txt_b and "pas une calibration" in txt_b.lower(),
            f"...et un `.npz` qui n'est pas une calibration est refusé POUR CE QU'IL EST, pas par "
            f"KeyError ({rendu_b}, {txt_b.strip()[:90]!r})")

        # (c) I1 — la géométrie k=2 ne rend AUCUN groupe. Chaque cible n'apparaît qu'une fois par
        #     tour, donc jamais deux cycles consécutifs de la même : `groupes_de_cycles(y, 2)` rend
        #     []. Les deux `hors_pli` divergent alors de forme — `(0,)` côté eCCA (AxisError sur
        #     `.argmax(axis=1)`), `(0, n_cibles)` côté rCCA (qui passe les gardes et fabrique un
        #     `nan`, puis un `ValueError: cannot convert float NaN to integer`) : trois tracebacks
        #     pour une seule cause. k=1, lui, doit continuer de mesurer normalement.
        alternes = [l for _ in range(2) for l in lags]
        from core.cvep_decoder import groupes_de_cycles as _gdc6
        chk(_gdc6([lags.index(l) for l in alternes], CVEP_DECISION_CYCLES) == []
            and len(_gdc6([lags.index(l) for l in alternes], 1)) == len(alternes),
            f"fixture : AUCUNE paire de cycles consécutifs à k={CVEP_DECISION_CYCLES}, mais des "
            f"décisions à k=1 ({len(_gdc6([lags.index(l) for l in alternes], 1))})")
        sans_paire = _ecrire_calib("cvep_calib_sans_paire.npz", alternes)
        rendu_c, txt_c = _rejoue_capture(sans_paire)
        chk(rendu_c is True and f"AUCUN groupe de {CVEP_DECISION_CYCLES} cycles" in txt_c,
            f"--seuils sur une séance SANS aucune paire consécutive nomme le refus À CETTE "
            f"GÉOMÉTRIE, une seule fois, sans traceback ({rendu_c}, "
            f"{[l for l in txt_c.splitlines() if '⛔' in l]})")
        chk("k = 1" in txt_c and "leave-one-out" in txt_c,
            "...et la géométrie k=1, elle, est mesurée normalement — le refus est LOCAL à la "
            "géométrie vide, il n'avale pas tout le rapport")
        chk("McNemar apparié" in txt_c,
            f"...et la comparaison des deux décodeurs passe par McNemar APPARIÉ, pas par les deux "
            f"pourcentages côte à côte que `bd3b588` a bannis de l'écran de calibration "
            f"({[l.strip() for l in txt_c.splitlines() if 'McNemar' in l]})")
        chk("OPTIMISTE" in txt_c and "choisi sur ces décisions" in txt_c,
            "...et le tableau dit, LÀ OÙ IL EST LU, que le couple qu'on y choisira aura un point "
            "de fonctionnement optimiste — sélectionné sur les décisions qui le mesurent")
    finally:
        shutil.rmtree(tmp6, ignore_errors=True)

    # ...et le McNemar que `--seuils` applique est celui de l'écran de calibration, à l'identique.
    # ⚠️ Il vit ICI et pas dans `research/cvep_calibrate.py` où il est né : `core/` n'importe
    # JAMAIS `research/` (vérifié par `server.py --smoke`), donc c'est le module visé qui a
    # DÉMÉNAGÉ. Que les deux appelants partagent bien le MÊME objet est vérifié de l'autre côté de
    # la frontière, par `python src/research/cvep_calibrate.py` — le sens d'import autorisé.
    chk(abs(_mcnemar_p(3, 5) - 0.7265625) < 1e-9 and abs(_mcnemar_p(5, 3) - 0.7265625) < 1e-9,
        f"_mcnemar_p(3, 5) = _mcnemar_p(5, 3) = 0,7265625 — le cas mesuré sur la vraie séance "
        f"({_mcnemar_p(3, 5)})")
    chk(_mcnemar_p(0, 0) == 1.0 and _mcnemar_p(10, 10) == 1.0,
        "...et les deux dégénérescences rendent p=1 (aucune discordance, partage parfait)")

    print(f"[cvep-rcca] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    if len(sys.argv) > 2 and sys.argv[1] == "--seuils":
        sys.exit(0 if _rejouer(sys.argv[2]) else 1)
    sys.exit(0 if _selftest() else 1)
