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

    python src/core/cvep_decoder.py     # validation sur c-VEP synthétique (aucun casque)
"""

import os
import sys

import numpy as np
from scipy.signal import butter, filtfilt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (CVEP_BAND, CVEP_CHANNELS, CVEP_CORR_MIN,  # noqa: E402
                    CVEP_DECISION_CYCLES, CVEP_MARGIN, CVEP_MODEL_PATH, FS_UNICORN,
                    use_utf8_console)
from core.cvep_code import build_targets, m_sequence  # noqa: E402


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


def groupes_de_cycles(labels, k=1):
    """Indices des groupes de `k` cycles CONSÉCUTIFS portant la MÊME cible.

    Une calibration enregistre un cycle par époque ; le moteur, lui, décide sur `n_cycles`
    cycles moyennés (`CVEP_DECISION_CYCLES`). Pour mesurer un décodeur **à la géométrie où il
    servira**, il faut donc rejouer la calibration par groupes de `k` cycles voisins — et voisins
    de la MÊME cible, sinon on moyennerait deux réponses différentes.

    ⚠️ Un groupe à cheval sur un changement de cible est **écarté**, pas rogné : les blocs de
    calibration sont entrelacés, donc ces frontières existent réellement, et un groupe mélangé
    fabriquerait une époque que le moteur ne verra jamais. Conséquence à connaître en lisant les
    chiffres : à k=2 sur 90 cycles, il reste 37 décisions et non 45.

    Rend une liste de tuples d'indices. `k=1` rend simplement tous les cycles, un par groupe.
    """
    labels = [int(l) for l in labels]
    k = max(1, int(k))
    groupes, i = [], 0
    while i + k <= len(labels):
        if len(set(labels[i:i + k])) == 1:
            groupes.append(tuple(range(i, i + k)))
            i += k
        else:
            i += 1                      # frontière de cible : on avance d'un cran, on ne mélange pas
    return groupes


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

    # ⚠️ Ce que ce modèle EST, et ce que `cvep_models.charger` lit pour choisir le décodeur (voir
    # son jumeau `cvep_rcca.RCCAModel.decoder`). Posé au niveau de la CLASSE, pas relu du fichier :
    # un objet ne peut alors pas mentir sur lui-même. Le champ `decoder` ÉCRIT dans le fichier sert
    # à l'AIGUILLAGE, et à rien d'autre — un fichier qui ne le porte pas est un modèle d'avant le
    # chantier c-VEP-moteur, donc un eCCA : c'était le seul décodeur qui existait sous ce nom.
    decoder = "eCCA"

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

    def hors_pli(self, epochs, lags, n_cycles=1):
        """(scores, y, lags_triés) — les scores de validation croisée à la géométrie `n_cycles`.

        Leave-one-GROUPE-out : pour chaque groupe de `n_cycles` cycles consécutifs d'une même
        cible, on ré-apprend le template SANS aucun de ses cycles, puis on note la moyenne du
        groupe. `scores[j, i]` est la corrélation du groupe j au lag `lags_triés[i]` ; `y[j]` est
        l'index du vrai lag dans cette même liste.

        ⚠️ Cette fonction existe pour que **la moitié eCCA de la comparaison soit reproductible**.
        Le « jeu égal entre les deux décodeurs » est l'affirmation qui justifie de réintégrer le
        rCCA : un chiffre qu'aucune commande du dépôt n'imprime est un chiffre qu'il faut croire.
        `python src/core/cvep_rcca.py --seuils <calib.npz>` l'imprime, pour les deux décodeurs et
        les deux géométries.
        """
        filt = [bandpass(e, self.fs, self.band) for e in epochs]
        lags = [int(l) for l in lags]
        uniq = sorted(set(lags))
        scores, y = [], []
        for g in groupes_de_cycles(lags, n_cycles):
            dehors = set(g)
            reste = [(e, l) for i, (e, l) in enumerate(zip(filt, lags)) if i not in dehors]
            w, tmpl = self._solve([self._align(e, l) for e, l in reste])
            moyen = np.mean([filt[i] for i in g], axis=0)
            sc = self._scores_filtered(moyen, 0, uniq, w, tmpl)
            scores.append([sc[l] for l in uniq])
            y.append(uniq.index(lags[g[0]]))
        return np.asarray(scores, dtype=float), np.asarray(y, dtype=int), uniq

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
                 # Le fichier DÉCLARE son décodeur : `cvep_models.charger` lit ce champ pour
                 # savoir quelle classe instancier. Un fichier SANS le champ est un eCCA d'avant
                 # ce chantier — cf. le commentaire de `CVEPModel.decoder`.
                 decoder=self.decoder,
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


def _selftest():
    """Le modèle SURVIT au déménagement dans `core/` — LE test de cette tâche.

    Le P300 et l'ErrP ont perdu leur modèle à ce même déménagement : leur `.joblib` est un
    pickle qui référence le module `research.p300_decoder` / `research.errp_decoder`, disparu
    une fois le fichier déplacé — il a fallu ré-entraîner deux fois. `CVEPModel.save` écrit du
    `np.savez` de tableaux purs, sans nom de classe : il DEVRAIT survivre. Ce test transforme ce
    « devrait » en fait mesuré, avant que le fichier ne bouge.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # Le modèle SURVIT au déménagement — la question qui a coûté deux ré-entraînements.
    # On écrit un modèle, on le relit, et on vérifie que les tableaux sont identiques BIT
    # POUR BIT. Pas de pickle ici (np.savez de tableaux purs), donc aucun nom de module
    # n'est gravé dans le fichier : c'est ce qui rend `core.cvep_decoder` capable de relire
    # ce que `research.cvep_decoder` avait écrit.
    import os as _os
    import tempfile as _tf, shutil as _sh
    tmp = _tf.mkdtemp(prefix="cvep_selftest_")
    try:
        m = CVEPModel(fs=250.0, refresh=60.0, code_len=63, band=CVEP_BAND, channels=[4, 5, 6, 7])
        m.w = np.arange(4, dtype=float) * 1.5
        m.template = np.arange(63, dtype=float) / 7.0
        m.cv_ = 0.87
        chemin = m.save(_os.path.join(tmp, "cvep_model.npz"), n_targets=6)
        relu = CVEPModel.load(chemin)
        chk(np.array_equal(relu.w, m.w) and np.array_equal(relu.template, m.template),
            "un modèle écrit puis relu rend les MÊMES tableaux, bit pour bit")
        chk(relu.channels == [4, 5, 6, 7] and relu.code_len == 63 and relu.n_targets == 6,
            f"...et ses métadonnées ({relu.channels}, {relu.code_len}, {relu.n_targets})")
        chk("cvep_decoder" not in open(chemin, "rb").read(2048).decode("latin-1"),
            "le fichier ne contient AUCUN nom de module — c'est ce qui le rend déplaçable")
    finally:
        _sh.rmtree(tmp, ignore_errors=True)

    # La MOITIÉ eCCA de la comparaison entre décodeurs. C'est le « 43/90 de l'eCCA » qui justifie
    # de réintégrer le rCCA : sans une fonction du dépôt qui l'imprime, c'est un chiffre à croire
    # — exactement le reproche « un chiffre sans provenance » qu'on applique aux seuils.
    # `hors_pli` la rend reproductible ; `cvep_rcca.py --seuils` l'appelle.
    plan, code = build_targets()
    lags = [c["lag"] for c in plan]
    rng = np.random.default_rng(3)
    epochs = [synth_cvep(code, l, 4, 250.0, 60.0, -6.0, rng) for l in lags for _ in range(4)]
    etiquettes = [l for l in lags for _ in range(4)]
    m = CVEPModel(fs=250.0, refresh=60.0, code_len=len(code), channels=[0, 1, 2, 3])
    sc1, y1, uniq1 = m.hors_pli(epochs, etiquettes, n_cycles=1)
    sc2, y2, uniq2 = m.hors_pli(epochs, etiquettes, n_cycles=2)
    chk(uniq1 == sorted(set(lags)) and sc1.shape == (len(epochs), len(lags)),
        f"un score hors-pli par cycle et par lag, les lags TRIÉS ({sc1.shape}, {uniq1})")
    chk(sc2.shape[0] == len(groupes_de_cycles(etiquettes, 2)) and sc2.shape[0] < sc1.shape[0],
        f"à k=2 (la géométrie de décision du moteur), un score par GROUPE de deux cycles, et il "
        f"y en a moins ({sc2.shape} contre {sc1.shape})")
    chk(float((sc1.argmax(axis=1) == y1).mean()) > 1.5 / len(lags),
        f"...et ces scores DÉCODENT, très au-dessus du hasard "
        f"({(sc1.argmax(axis=1) == y1).mean()*100:.0f} % pour {100/len(lags):.0f} % de hasard)")
    # ⚠️ HORS-PLI VEUT DIRE HORS-PLI, et c'est CE test qui le prouve. Le template qui note un
    # groupe ne doit pas avoir vu ses cycles ; si l'exclusion saute, le template contient une part
    # de l'époque qu'il note, et la corrélation devient une auto-corrélation. Rien dans le
    # résultat ne le dirait : les chiffres montent, ils ont l'air meilleurs.
    #
    # On le rend visible en donnant à `hors_pli` du BRUIT PUR étiqueté au hasard. Il n'y a rien à
    # décoder, donc la seule justesse honnête est le hasard (1/6). MESURÉ sur ce jeu : 16,7 %
    # hors-pli — et **91,7 % si l'exclusion saute**. Une fuite d'un douzième d'époque suffit à
    # faire décoder du bruit à 92 %, exactement la panne muette que ce dépôt existe pour éliminer.
    rng_b = np.random.default_rng(5)
    bruit = [rng_b.normal(0.0, 1.0, (m.n_cyc, 4)) for _ in lags for _ in range(2)]
    et_bruit = [l for l in lags for _ in range(2)]
    m2 = CVEPModel(fs=250.0, refresh=60.0, code_len=len(code), channels=[0, 1, 2, 3])
    sc_b, y_b, _u = m2.hors_pli(bruit, et_bruit, n_cycles=1)
    just_bruit = float((sc_b.argmax(axis=1) == y_b).mean())
    chk(sc_b.shape[0] == len(bruit), f"un groupe par cycle ({sc_b.shape[0]} pour {len(bruit)})")
    chk(just_bruit <= 0.35,
        f"sur du BRUIT PUR, la validation croisée reste au niveau du hasard "
        f"({just_bruit*100:.1f} % pour {100/len(lags):.1f} %) — si l'exclusion du pli sautait, "
        f"ce même jeu monterait à 91,7 %, mesuré")

    print(f"[cvep-decoder] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _demo()
    # `sys.exit(0 si … sinon 1)`, comme `p300_decoder.py` et `errp_decoder.py` : avant ce test,
    # `_demo()` s'exécutait sans que son résultat ne soit vérifié, donc ce fichier sortait
    # TOUJOURS en 0 — un décodeur cassé aurait quand même passé pour vert. `_selftest()` est ce
    # qui rend cette sortie honnête.
    sys.exit(0 if _selftest() else 1)
