"""Décodeur ErrP (potentiel d'erreur) : détection BINAIRE erreur/correct, MONO-ESSAI.

L'INTERACTION-ErrP est un ERP fronto-central médian (FCz/Cz, source ACC) émis quand l'utilisateur
perçoit que la MACHINE s'est trompée. Onde LENTE multiphasique après le FEEDBACK : +200 / −250 /
+320 / −450 ms (cœur discriminant N250+P320). On classe CHAQUE époque de feedback « erreur / correct »
et, en ligne, on ANNULE la dernière commande si erreur détectée.

RÉUTILISATION de la pile P300 (revue littérature 2026-07-23, cf. eeg-modes-a-venir) : le décodeur
xDAWN + covariances riemanniennes + LR est l'ÉTAT DE L'ART de l'ErrP (famille gagnante du Kaggle NER
2015). On réutilise `core.p300_decoder` (build_pipe, bandpass, epoch_from_stream, P300Model._prep)
via composition ; on change 4 choses : bande 1-10 Hz, pre_s=0.2, post_s=0.7, onset = feedback.

DIFFÉRENCES CLÉS avec le P300 (durement établies par la revue) :
- **MONO-ESSAI** : une action = UNE époque, AUCUN moyennage sur répétitions (ce qui portait le P300
  à ~95 %). L'ErrP est plus petit -> AUC réaliste ~0,65-0,78 en électrodes sèches. C'est un DÉTECTEUR
  imparfait, pas un interrupteur propre.
- **Déséquilibre** : l'erreur est la classe MINORITAIRE (~20-30 %). `class_weight="balanced"` (déjà
  dans la LR) + on NE garde PAS le seuil 0,5 : seuil ASYMÉTRIQUE calé pour une haute SPÉCIFICITÉ
  (TNR >= ERRP_TNR_TARGET), car annuler une commande CORRECTE coûte plus que rater une erreur.
- **Métriques** : jamais l'accuracy brute (dire toujours « correct » = 75 %). On rapporte AUC +
  balanced-accuracy + TPR/TNR séparés (GroupKFold par bloc).

AFFINEMENTS post-revue (2026-07-23), tous à petit N donc anti-surapprentissage/anti-bruit :
- **nfilter TRANCHÉ PAR AUC** (pas figé) : `fit` balaie ERRP_XDAWN_NFILTER_CANDIDATES {2,3,4} et retient
  le meilleur AUC out-of-fold. Sur ~55 époques erreur, nfilter=4 (rang plein) surapprend souvent.
- **TEST DE PERMUTATION** : p-value de l'AUC (garde-fou « conclure sur du bruit » à petit N).
- **BASELINE sLDA** : comparateur honnête (features temporelles fenêtrées + LDA à shrinkage), la
  méthode la plus robuste du survey Yasemin 2023 — on ne « croit » le riemannien que s'il la dépasse.

Validé ici sur ErrP SYNTHÉTIQUE (pas de casque).   python src/core/errp_decoder.py
"""

import os
import sys

import joblib
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (ERRP_BAND, ERRP_EPOCH_S, ERRP_PRE_S, ERRP_TNR_TARGET,  # noqa: E402
                    ERRP_XDAWN_NFILTER, use_utf8_console)
from core.p300_decoder import (P300Model, bandpass, build_pipe,  # noqa: E402,F401  (réutilisés/ré-exportés)
                          epoch_from_stream)

ERROR, CORRECT = 1, 0


def rates(y, pred):
    """(TPR, TNR, balanced_acc) pour une prédiction binaire. TPR = rappel des ERREURS (classe 1),
    TNR = rappel des CORRECTS (classe 0). L'accuracy brute est trompeuse sous déséquilibre."""
    y, pred = np.asarray(y).astype(int), np.asarray(pred).astype(int)
    tpr = float(pred[y == ERROR].mean()) if (y == ERROR).any() else 0.0
    tnr = float((1 - pred)[y == CORRECT].mean()) if (y == CORRECT).any() else 0.0
    return tpr, tnr, 0.5 * (tpr + tnr)


def pick_threshold(y, scores, tnr_target=ERRP_TNR_TARGET):
    """Seuil ASYMÉTRIQUE sur les scores (log-odds « erreur »). Parmi les seuils atteignant
    TNR >= cible, retient celui qui MAXIMISE la TPR ; si aucun, celui qui maximise la TNR.
    Renvoie (seuil, {tpr, tnr, bal_acc}). Rationnel : un faux veto (annuler une bonne commande)
    coûte plus qu'une erreur ratée (récupérable) -> on privilégie la spécificité.

    ⚠️ Elle se défend ELLE-MÊME (correction de revue) : deux gardes avaient été posées chez ses
    appelants (`errp_models.charger` et `ErrPRuntime._sans_scores_oof`), aucune dans la fonction
    qui produit l'erreur. Sans ce contrôle, `pick_threshold(None, None)` lève
    `ValueError: zero-dimensional arrays cannot be concatenated` (`np.asarray(None, dtype=float)`
    rend un tableau 0-d) et des scores VIDES lèvent encore autrement (`scores.min()` ->
    « zero-size array to reduction operation minimum ») — deux exceptions numpy brutes, sans
    rapport avec ce qu'il faut faire. Le 3e appelant (page de console, script d'analyse) ne
    doit pas avoir à redécouvrir la garde : elle est à la source.
    """
    scores = np.asarray(scores, dtype=float)
    y_arr = np.asarray(y)
    if scores.ndim != 1 or scores.size == 0 or y_arr.ndim != 1 or y_arr.size != scores.size:
        raise ValueError(
            f"pick_threshold : il faut des scores hors-pli 1-D NON VIDES et alignés sur y "
            f"(reçu scores de forme {scores.shape}, y de forme {y_arr.shape}). Un modèle dont "
            f"la calibration n'a pas produit de scores hors-pli doit être REFUSÉ en amont "
            f"(cf. `errp_models.charger` et `ErrPRuntime._sans_scores_oof`), pas amené ici.")
    cand = np.unique(np.concatenate([scores, [scores.min() - 1e-6, scores.max() + 1e-6]]))
    rows = []
    for th in cand:
        tpr, tnr, bal = rates(y, scores >= th)
        rows.append((float(th), tpr, tnr, bal))
    ok = [r for r in rows if r[2] >= tnr_target]
    th, tpr, tnr, bal = (max(ok, key=lambda r: (r[1], r[2])) if ok
                         else max(rows, key=lambda r: (r[2], r[1])))
    return th, {"tpr": tpr, "tnr": tnr, "bal_acc": bal}


# --- Validation honnête : CV out-of-fold, balayage nfilter, permutation, baseline sLDA ---

def _cv_splitter(y, groups):
    """(splitter, groups_ou_None) : GroupKFold par bloc si `groups` fourni (pas de fuite d'époques
    d'un même bloc entre train et test), sinon StratifiedKFold. k borné par le plus petit effectif."""
    from sklearn.model_selection import GroupKFold, StratifiedKFold
    if groups is not None and len(np.unique(groups)) >= 2:
        return GroupKFold(min(5, len(np.unique(groups)))), np.asarray(groups)
    k = max(2, min(5, int(np.bincount(y).min())))
    return StratifiedKFold(k, shuffle=True, random_state=0), None


def _oof_auc(pipe, Xf, y, cv, groups):
    """(AUC pooled-OOF, scores OOF) pour un pipeline donné — aucune époque évaluée par un modèle
    qui l'a vue. Lève si le CV échoue (appelant responsable du try/except)."""
    from sklearn.base import clone
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import cross_val_predict
    oof = cross_val_predict(clone(pipe), Xf, y, groups=groups, cv=cv, method="decision_function")
    return float(roc_auc_score(y, oof)), oof


def _permutation_p(pipe, Xf, y, cv, groups, observed_auc, n_perm, seed=0):
    """p-value par permutation des étiquettes : fraction des tirages NULS dont l'AUC OOF atteint
    l'AUC observée, p=(k+1)/(n+1). Garde-fou contre « conclure sur du bruit » à petit N
    (cf. rigueur-statistique-eeg). n_perm<=0 -> None (sauté)."""
    from sklearn.base import clone
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import cross_val_predict
    if n_perm <= 0 or observed_auc is None:
        return None
    rng = np.random.default_rng(seed)
    ge = 0
    for _ in range(n_perm):
        yp = rng.permutation(y)
        try:
            oof = cross_val_predict(clone(pipe), Xf, yp, groups=groups, cv=cv,
                                    method="decision_function")
            a = roc_auc_score(yp, oof)
        except Exception:  # noqa: BLE001 - un pli mono-classe sous permutation -> tirage neutre
            a = 0.5
        ge += int(a >= observed_auc)
    return (ge + 1) / (n_perm + 1)


def _window_features(Xf, fs, win_s=0.1, step_s=0.05):
    """Xf (n_trials, n_ch, n_samp) -> (n_trials, n_ch*n_fenêtres) : moyennes de fenêtres CHEVAUCHANTES
    (~100 ms, pas ~50 ms). Réduit la dimension et débruite — features de la baseline sLDA (Yasemin 2023)."""
    n_tr, n_ch, n_s = Xf.shape
    w = max(1, int(round(win_s * fs)))
    st = max(1, int(round(step_s * fs)))
    starts = range(0, max(1, n_s - w + 1), st)
    feats = np.stack([Xf[:, :, s:s + w].mean(axis=2) for s in starts], axis=2)
    return feats.reshape(n_tr, -1)


def _slda_auc(Xf, y, cv, groups, fs):
    """AUC OOF d'une baseline sLDA (shrinkage) sur features temporelles fenêtrées — comparateur
    HONNÊTE (Yasemin 2023 : sLDA = méthode la plus robuste en mono-essai). None si le CV échoue."""
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    try:
        feats = _window_features(Xf, fs)
        lda = LinearDiscriminantAnalysis(solver="lsqr", shrinkage="auto")
        auc, _ = _oof_auc(lda, feats, y, cv, groups)
        return auc
    except Exception as e:  # noqa: BLE001 - baseline indicative, ne doit pas bloquer le fit
        print(f"[errp] baseline sLDA non calculée : {e}")
        return None


class ErrPModel:
    """Détecteur ErrP binaire (composé sur P300Model pour réutiliser _prep + pipeline xDAWN+Riemann+LR).

    `cv_auc_` = AUC out-of-fold (GroupKFold par bloc) ; `threshold_` = seuil asymétrique appris ;
    `metrics_` = {tpr, tnr, bal_acc} au seuil. `is_error(epoch)` applique le seuil en ligne.
    `n_epoques_` = combien d'époques l'ont entraîné (comme `P300Model` : c'est ce que la liste de
    modèles affiche) ; `echec_oof_` = pourquoi il n'y a PAS de scores hors-pli, quand il n'y en a
    pas — dit par celui qui l'a CONSTATÉ, pour que le refus en aval n'ait rien à deviner.
    """

    def __init__(self, fs=250.0, band=ERRP_BAND, pre_s=ERRP_PRE_S, post_s=ERRP_EPOCH_S,
                 nfilter=ERRP_XDAWN_NFILTER, tnr_target=ERRP_TNR_TARGET):
        self.core = P300Model(fs=fs, band=band, pre_s=pre_s, post_s=post_s, nfilter=nfilter)
        self.fs, self.band, self.pre_s, self.post_s = fs, band, pre_s, post_s
        self.nfilter, self.tnr_target = nfilter, tnr_target
        self.threshold_ = 0.0
        self.cv_auc_ = None       # AUC OOF du nfilter retenu
        self.metrics_ = None      # {tpr, tnr, bal_acc} au seuil
        self.nfilter_ = nfilter   # nfilter RETENU par le balayage
        self.sweep_ = None        # {nfilter: AUC} du balayage
        self.perm_p_ = None       # p-value par permutation de l'AUC retenue
        self.slda_auc_ = None     # AUC de la baseline sLDA (comparateur)
        self.oof_scores_ = None   # scores out-of-fold du nfilter retenu (pour régler le seuil a posteriori)
        self.oof_y_ = None        # étiquettes alignées sur oof_scores_ (recalcul TPR/TNR à tout seuil)
        self.n_epoques_ = None    # nombre d'époques d'entraînement (parité avec P300Model)
        self.echec_oof_ = None    # POURQUOI il n'y a pas de scores hors-pli (None si tout va bien)

    def fit(self, epochs, y, groups=None, n_perm=None):
        """Entraîne le détecteur. BALAIE ERRP_XDAWN_NFILTER_CANDIDATES et retient le nfilter au
        MEILLEUR AUC out-of-fold (pas figé) ; règle le seuil asymétrique sur ses scores OOF ; compare
        à une baseline sLDA ; teste la significativité par permutation. `n_perm=0` saute la
        permutation (ex. smoke / synthétique) ; None -> ERRP_PERM_N."""
        from core.config import ERRP_PERM_N, ERRP_XDAWN_NFILTER_CANDIDATES
        y = np.asarray(y).astype(int)
        Xf = self.core._prep(epochs)
        n_perm = ERRP_PERM_N if n_perm is None else n_perm
        self.cv_auc_ = self.metrics_ = self.perm_p_ = self.slda_auc_ = self.sweep_ = None
        self.oof_scores_ = self.oof_y_ = self.echec_oof_ = None
        self.nfilter_ = self.nfilter
        self.n_epoques_ = int(len(y))

        if len(np.unique(y)) == 2 and len(y) >= 10 and int(np.bincount(y).min()) >= 2:
            cv, g = _cv_splitter(y, groups)
            sweep, best = {}, None
            for nf in ERRP_XDAWN_NFILTER_CANDIDATES:
                try:
                    auc, oof = _oof_auc(build_pipe(nf), Xf, y, cv, g)
                except Exception as e:  # noqa: BLE001 - un nfilter peut échouer (rang), on continue
                    print(f"[errp] nfilter={nf} : CV échouée ({e})")
                    continue
                sweep[nf] = auc
                if best is None or auc > best[1]:
                    best = (nf, auc, oof)
            if best is not None:
                self.nfilter_, self.cv_auc_, oof = best
                self.sweep_ = sweep
                self.threshold_, self.metrics_ = pick_threshold(y, oof, self.tnr_target)
                self.oof_scores_, self.oof_y_ = np.asarray(oof, dtype=float), y.copy()
                self.core.nfilter = self.nfilter_
                self.core.pipe = build_pipe(self.nfilter_)        # pipe final = nfilter retenu
                self.perm_p_ = _permutation_p(build_pipe(self.nfilter_), Xf, y, cv, g,
                                              self.cv_auc_, n_perm)
                self.slda_auc_ = _slda_auc(Xf, y, cv, g, self.fs)
            else:
                # ⚠️ Le SECOND chemin qui laisse `oof_scores_` à None, et il n'a RIEN à voir avec
                # le premier : la garde est passée (assez d'essais, deux classes), mais les trois
                # nfilter ont levé au CV et ont été avalés par le `except … continue` ci-dessus.
                # Sans cette phrase, le refus en aval accusait « calibration trop courte » et
                # ordonnait « recalibre avec plus d'essais » — un diagnostic INVENTÉ, qui renvoie
                # l'étudiant refaire une séance casque de 5 min pour rien.
                self.echec_oof_ = (
                    f"validation croisée échouée pour TOUTES les valeurs de nfilter essayées "
                    f"({', '.join(str(nf) for nf in ERRP_XDAWN_NFILTER_CANDIDATES)}) sur "
                    f"{len(y)} essais — ce n'est PAS un manque d'essais : voir les lignes "
                    f"« [errp] nfilter=… : CV échouée » de l'entraînement (voie plate/électrode "
                    f"décollée rendant la covariance singulière, ou dérive de version sklearn)")
        else:
            compte = np.bincount(y, minlength=2)
            self.echec_oof_ = (
                f"calibration trop courte : {len(y)} essais ({int(compte[CORRECT])} corrects / "
                f"{int(compte[ERROR])} erreurs) — il en faut au moins 10, des DEUX classes, et "
                f"au moins 2 de chaque")
        self.core.pipe.fit(Xf, y)     # modèle final (nfilter retenu) sur TOUTES les données
        return self

    def score(self, epochs):
        """Score « erreur » (log-odds LR, decision_function) par époque."""
        return self.core.scores(epochs)

    def is_error(self, epoch):
        """Décision binaire mono-essai en ligne : score >= seuil asymétrique -> ERREUR (veto)."""
        return bool(np.ravel(self.score(epoch))[0] >= self.threshold_)

    def save(self, path):
        joblib.dump(self, path)

    @staticmethod
    def load(path):
        return joblib.load(path)


# --- Validation sur ErrP SYNTHÉTIQUE (pas de casque requis) -----------------

def _g(t, mu, sd):
    return np.exp(-0.5 * ((t - mu) / sd) ** 2)


def synth_errp_epoch(is_error, fs=250.0, pre_s=ERRP_PRE_S, post_s=ERRP_EPOCH_S,
                     amp=0.95, noise=2.0, rng=None):
    """Époque synthétique (n_samp, 8). ERREUR = onde multiphasique +200/−250/+320/−450 ms pondérée
    fronto-central (Fz/Cz cœur, Pz tardif) ; CORRECT = même fond, sans l'onde. Alpha ~10 Hz partagé.
    amp/noise réglés pour un ErrP mono-essai FAIBLE (AUC ~0,75) — réaliste, pas trivial."""
    rng = np.random.default_rng() if rng is None else rng
    n_pre, n_post = int(round(pre_s * fs)), int(round(post_s * fs))
    n = n_pre + n_post
    t = (np.arange(n) - n_pre) / fs                          # temps depuis le feedback (s)
    X = rng.normal(0.0, noise, (n, 8))
    X += (0.7 * np.sin(2 * np.pi * 10 * t + rng.uniform(0, 2 * np.pi)))[:, None]   # alpha partagé
    if is_error:
        erp = amp * (0.6 * _g(t, 0.20, 0.035) - 1.0 * _g(t, 0.25, 0.030)
                     + 0.8 * _g(t, 0.32, 0.045) - 0.5 * _g(t, 0.45, 0.060))
        w = np.zeros(8)
        w[[0, 2]] = [1.0, 0.95]                              # Fz, Cz (cœur)
        w[4] = 0.4                                           # Pz (composante tardive)
        X += erp[:, None] * w[None, :]
    return X


def _synth_dataset(n_trials, error_rate, blocks, fs, rng, amp=0.95, noise=2.0):
    """Simule une calibration ErrP : `n_trials` feedbacks, une fraction `error_rate` = erreurs,
    répartis en `blocks` blocs (groupes GroupKFold). Retourne epochs, y (0/1), groups."""
    epochs, y, groups = [], [], []
    per = max(1, n_trials // blocks)
    for i in range(n_trials):
        is_err = rng.random() < error_rate
        epochs.append(synth_errp_epoch(is_err, fs=fs, amp=amp, noise=noise, rng=rng))
        y.append(ERROR if is_err else CORRECT)
        groups.append(min(blocks - 1, i // per))
    return np.asarray(epochs), np.asarray(y), np.asarray(groups)


def _rapport(m):
    """Imprime le verdict d'un modèle entraîné, et rend True s'il est validé.

    ⚠️ Séparé de `_demo` EXPRÈS : ce bloc doit rester imprimable sur un modèle DÉGÉNÉRÉ (aucune
    AUC, aucune p-value, aucune métrique) — c'est précisément l'état dans lequel il levait un
    `TypeError` sur `f"{None:.3f}"` au lieu d'imprimer le diagnostic. `_gardes` le rappelle sur
    un tel modèle ; sans cette séparation, la correction n'aurait aucun test.
    """
    auc = m.cv_auc_ or 0.0
    mt = m.metrics_ or {"tpr": 0, "tnr": 0, "bal_acc": 0}
    sweep = "  ".join(f"nf{nf}={a * 100:.1f}%" for nf, a in sorted((m.sweep_ or {}).items()))
    print(f"\n[1] balayage nfilter (AUC OOF) : {sweep}  -> RETENU nfilter={m.nfilter_}")
    print(f"[2] AUC erreur/correct (GroupKFold par bloc) : {auc * 100:.1f}%  (hasard 50%)")
    pp = m.perm_p_
    # ⚠️ `pp` est None dès que `fit` n'a pas de scores hors-pli (garde non atteinte, ou tous les
    # nfilter tombés au CV). Le garde-fou était posé sur le MAUVAIS opérande : la f-string qui
    # formate `pp` s'évalue la première, sans condition, et `f"{None:.3f}"` lève
    # `TypeError: unsupported format string passed to NoneType.__format__`. Le diagnostic imprimé
    # juste au-dessus (« nfilter=… : CV échouée ») était alors noyé sous un traceback qui parle
    # d'autre chose. Même correction que `p300_decoder`, pour la même raison.
    pp_txt = "non testée" if pp is None else f"{pp:.3f}"
    print(f"    test de permutation : p={pp_txt}" + ("" if pp is None else
          (" (significatif)" if pp < 0.05 else " (NON significatif — prudence)")))
    print(f"    baseline sLDA (comparateur) : "
          f"{'—' if m.slda_auc_ is None else f'{m.slda_auc_ * 100:.1f}%'}  "
          f"-> {'riemannien meilleur' if (m.slda_auc_ or 0) < auc else 'sLDA >= riemannien (à préférer ?)'}")
    print(f"[3] seuil ASYMÉTRIQUE (cible TNR>={m.tnr_target:.0%}) : seuil={m.threshold_:+.2f}")
    print(f"    TPR (rappel ERREURS) = {mt['tpr'] * 100:.0f}%   "
          f"TNR (rappel CORRECTS) = {mt['tnr'] * 100:.0f}%   "
          f"balanced-acc = {mt['bal_acc'] * 100:.0f}%")
    print(f"    -> {mt['tpr'] * 100:.0f}% des erreurs annulées, "
          f"{(1 - mt['tnr']) * 100:.0f}% de bonnes commandes annulées à tort")

    good = auc > 0.65 and mt["tnr"] >= m.tnr_target - 0.05 and (pp is None or pp < 0.05)
    print("\n[errp] pipeline xDAWN+Riemann " + ("validé sur synthétique (mono-essai)." if good
          else "à ajuster (AUC>65%, TNR~cible, permutation significative attendus)."))
    return good


def _gardes():
    """Ce que ce décodeur promet QUAND ÇA SE PASSE MAL — la moitié du fichier que la validation
    sur données propres n'exerce jamais. Aucun casque, aucun fichier écrit, ~2 s."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    fs = 250.0
    rng = np.random.default_rng(1)
    epochs, y, groups = _synth_dataset(24, 0.4, 3, fs, rng)

    # 1. `pick_threshold` se défend ELLE-MÊME : ses deux appelants ont chacun une garde, mais un
    #    troisième arrivera (page de console, script d'analyse hors ligne) et recevrait sinon
    #    l'exception numpy brute que ces gardes existent pour cacher.
    for etiquette, args in (("(None, None) — le cas mesuré en revue", (None, None)),
                            ("des scores VIDES — gardé nulle part jusqu'ici", ([], [])),
                            ("y et scores de longueurs différentes", ([0, 1, 0], [0.1, 0.2]))):
        try:
            pick_threshold(*args)
            refus = None
        except ValueError as e:
            refus = str(e)
        except Exception as e:      # noqa: BLE001 - toute autre exception EST le défaut visé
            refus = f"!! {type(e).__name__}: {e}"
        chk(refus is not None and refus.startswith("pick_threshold"),
            f"pick_threshold refuse {etiquette} en le NOMMANT ({refus})")

    # 2. Une calibration trop courte laisse `oof_scores_` à None — et dit POURQUOI, elle-même.
    #    Le refus en aval (`errp_models.charger`) ne devine plus : il recopie cette phrase.
    court = ErrPModel(fs=fs).fit(epochs[:5], np.asarray([CORRECT, ERROR, CORRECT, ERROR, CORRECT]),
                                 n_perm=0)
    chk(court.oof_scores_ is None and court.echec_oof_ and "trop courte" in court.echec_oof_
        and "10" in court.echec_oof_,
        f"5 essais : pas de scores hors-pli, et la cause est ENREGISTRÉE ({court.echec_oof_})")
    chk(court.n_epoques_ == 5, f"...et le nombre d'époques d'entraînement aussi ({court.n_epoques_})")

    # 3. L'AUTRE chemin vers « pas de scores hors-pli », celui qu'aucun message ne nommait : la
    #    garde est passée (24 essais, 2 classes), mais TOUS les nfilter tombent au CV (voie plate,
    #    covariance singulière, dérive de version). On le reproduit en faisant lever `build_pipe`,
    #    exactement là où `fit` l'appelle. Le modèle est construit AVANT le remplacement : son
    #    pipeline interne (celui de `P300Model.__init__`) reste le vrai, et le fit final marche.
    modele_cv = ErrPModel(fs=fs)
    vrai_build = globals()["build_pipe"]

    def _build_qui_leve(nfilter):
        raise RuntimeError(f"simulation : covariance singulière (nfilter={nfilter})")

    globals()["build_pipe"] = _build_qui_leve
    try:
        modele_cv.fit(epochs, y, groups=groups, n_perm=0)
    finally:
        globals()["build_pipe"] = vrai_build
    chk(modele_cv.oof_scores_ is None and modele_cv.echec_oof_
        and "validation croisée" in modele_cv.echec_oof_
        and "trop courte" not in modele_cv.echec_oof_,
        f"CV échouée sur tous les nfilter : la cause dit CE QUI s'est passé, et surtout PAS "
        f"« trop courte » — 24 essais n'ont pas manqué d'essais ({modele_cv.echec_oof_})")

    # 4. Et ce modèle-là doit rester RAPPORTABLE : c'est sur lui que `_rapport` levait un
    #    TypeError (`f"{None:.3f}"`), noyant les trois lignes « CV échouée » imprimées juste
    #    au-dessus — le seul endroit où la vraie cause était écrite.
    try:
        _rapport(modele_cv)
        leve = None
    except Exception as e:      # noqa: BLE001 - c'est l'exception elle-même qu'on teste
        leve = f"{type(e).__name__}: {e}"
    chk(leve is None, f"le rapport d'un modèle SANS AUC ni p-value s'imprime au lieu de lever ({leve})")

    print(f"[errp-gardes] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _demo():
    fs = 250.0
    rng = np.random.default_rng(0)
    from core.config import ERRP_CAL_BLOCKS, ERRP_CAL_TRIALS, ERRP_ERROR_RATE
    epochs, y, groups = _synth_dataset(ERRP_CAL_TRIALS, ERRP_ERROR_RATE, ERRP_CAL_BLOCKS, fs, rng)
    n_err = int((y == ERROR).sum())
    print(f"ErrP synthétique : {len(y)} feedbacks ({n_err} erreurs / {len(y) - n_err} corrects, "
          f"{100 * n_err / len(y):.0f}% erreurs — classe minoritaire), "
          f"{len(set(groups.tolist()))} blocs, fs={fs:g} Hz")

    m = ErrPModel(fs=fs).fit(epochs, y, groups=groups, n_perm=100)
    bon = _rapport(m)
    print("\n[errp] gardes (ce qui est promis quand la calibration se passe MAL) :")
    return _gardes() and bon      # les deux, et les gardes s'exécutent toujours


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if _demo() else 1)
