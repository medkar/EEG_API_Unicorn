"""Mode 5 — neuro-monitoring PASSIF : indices spectraux workload / vigilance / attention.

BCI PASSIF : aucune commande n'est envoyée au robot. On lit un ÉTAT mental à partir des
puissances de bande (θ/α/β) et on l'affiche en histogramme temps réel (voir app.mode_neuro).

Les trois indices reposent tous sur les MÊMES puissances de bande — un seul calcul PSD, trois
ratios. Ils sont donc CORRÉLÉS (l'engagement de Pope β/(α+θ) est ~l'inverse de la somnolence
(θ+α)/β) : ce sont des TENDANCES RELATIVES à comparer à un repos, PAS des mesures indépendantes.
Formules (v2 2026-07-23, après revue littérature multi-agent — cf. eeg-modes-a-venir) :
  - charge / workload      = θ_(Fz,Cz) / α_pariétal   (« task load index » de Holm 2009 ; θ
        frontal-médian MOYENNÉ Fz+Cz — pas Fz seul, trop sensible au clignement — sur l'α pariétal)
  - somnolence / vigilance = α_postérieur             (α pariéto-occipital, normalisé au repos :
        marqueur classique de somnolence/relâchement, monte quand la vigilance baisse — Jap 2009.
        REMPLACE l'ancien (θ+α)/β qui était l'INVERSE EXACT de l'engagement = barre redondante)
  - engagement / attention = β / (α + θ)  sur sites POSTÉRO-CENTRAUX (Cz,Pz,PO7,Oz,PO8, PAS Fz)
        (indice de Pope 1995 : sites central-pariétaux ; exclure Fz retire l'EMG/clignement frontal)
Bande β bornée à 25 Hz (moins d'EMG, cf. Goncharova 2003) ; VETO EMG sur une bande 30-45 Hz ;
passe-haut léger avant PSD (dérive électrode SÈCHE) ; re-calage lent du repos (dérive multi-min).

⚠️ Ces ratios DÉRIVENT et sont individuels. Sans repères ils n'affichent que du bruit -> l'appli
les NORMALISE en z **dans l'espace LOG** contre un repos mesuré en début de mode (IndexNormalizer :
les ratios de bande ont une queue lourde à droite, le log la redresse sinon le moindre effort
sature l'échelle), les LISSE (EMA) et REJETTE les fenêtres à σ aberrant (clignement/EMG : le θ
frontal est pollué en premier). À lire comme « au-dessus / en-dessous de mon repos », jamais en
absolu. (cf. rigueur-statistique-eeg.)

Le calcul travaille sur le flux BRUT (non filtré) : le passe-bande d'acquisition SSVEP (5-40 Hz)
couperait le bas du θ. La PSD de Welch détend (linéaire) chaque segment -> l'offset DC et la
dérive lente de l'électrode mouillée ne polluent pas les bandes (toutes ≥ 4 Hz).

    python src/core/neuro_monitor.py        # auto-test : les indices bougent-ils dans le bon sens ?
"""

import os
import sys

import numpy as np
from scipy.integrate import trapezoid
from scipy.signal import butter, filtfilt, welch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (FS_UNICORN, NEURO_ARTIFACT_RATIO, NEURO_BANDS,  # noqa: E402
                    NEURO_EMG_RATIO, NEURO_ENGAGEMENT_CH, NEURO_FRONTAL,
                    NEURO_HIGHPASS_HZ, NEURO_PARIETAL, NEURO_REBASELINE_S,
                    NEURO_SMOOTH, NEURO_UPDATE_HZ, use_utf8_console)

INDEX_KEYS = ("charge", "somnolence", "engagement")


def highpass_filter(x, fs, cutoff):
    """Passe-haut léger (Butterworth ordre 2, filtfilt) — retire la dérive lente des électrodes
    SÈCHES avant la PSD. `cutoff`=None/0 => renvoie le signal tel quel. `x` = (n_samples, n_ch)."""
    x = np.asarray(x, dtype=np.float64)
    if not cutoff:
        return x
    b, a = butter(2, cutoff / (fs / 2.0), btype="high")
    return filtfilt(b, a, x, axis=0)


def artifact_sigma(window, fs, band=(1.0, 30.0), notch_hz=50.0):
    """σ PAR VOIE pour le rejet d'artefact — sur un signal BANDE-LIMITÉ + NOTCH secteur, PAS le
    signal quasi-brut utilisé pour la PSD des indices.

    ⚠️ Piège corrigé (retour utilisateur 2026-07-23 : « ça se déclenche même à l'arrêt complet ») :
    calculer le σ sur un signal seulement passe-haut à 0,5 Hz laisse passer TOUT le reste (ronflement
    secteur 50 Hz, bruit haute fréquence, dérive sub-1 Hz) -> ce σ est intrinsèquement bien plus
    volatil minute à minute que celui utilisé ailleurs dans l'app (SSVEP compare son ratio ×4 sur un
    signal DÉJÀ passe-bande+notch). Comparer un σ non filtré à un seuil ×4 mesuré sur seulement 25 s
    de repos déclenche donc de faux rejets même sans bouger. Ici : passe-bande 1-30 Hz (coupe la
    dérive très lente ET l'EMG >30 Hz, cf. bande "emg" du veto séparé) + notch 50 Hz, comme
    `acquisition.UnicornAcquisition._filter`. Cette version filtrée sert UNIQUEMENT à juger la
    qualité de la fenêtre ; les indices restent calculés sur le signal large-bande (highpass_filter)."""
    x = np.asarray(window, dtype=np.float64)
    b, a = butter(4, [band[0] / (fs / 2.0), band[1] / (fs / 2.0)], btype="band")
    xf = filtfilt(b, a, x, axis=0)
    if notch_hz:
        bn, an = butter(2, [(notch_hz - 1) / (fs / 2.0), (notch_hz + 1) / (fs / 2.0)], btype="bandstop")
        xf = filtfilt(bn, an, xf, axis=0)
    return xf.std(axis=0)


def band_powers(window, fs, bands=NEURO_BANDS, highpass=None):
    """Puissance par bande et par voie. `window` = (n_samples, n_ch).

    Retourne {nom_bande: array (n_ch,)}. Passe-haut optionnel (dérive électrode sèche), puis PSD de
    Welch (détend linéaire, segments de ~1 s -> résolution ~1 Hz), puissance = intégrale de la PSD
    sur la bande (trapèze). L'intégrale, pas la moyenne : vraie puissance de bande, indépendante du
    nombre de points fréquentiels. `bands` inclut aussi une bande "emg" (30-45 Hz) pour le veto EMG.
    """
    x = highpass_filter(window, fs, highpass)
    if x.ndim == 1:
        x = x[:, None]
    n = x.shape[0]
    nperseg = max(16, min(n, int(round(fs))))          # ~1 s/segment, borné pour les fenêtres courtes
    freqs, psd = welch(x, fs=fs, nperseg=nperseg, detrend="linear", axis=0)
    out = {}
    for name, (lo, hi) in bands.items():
        mask = (freqs >= lo) & (freqs < hi)
        out[name] = (trapezoid(psd[mask, :], freqs[mask], axis=0)
                     if mask.sum() >= 2 else np.zeros(x.shape[1]))
    return out


def indices_from_bp(bp, frontal=NEURO_FRONTAL, parietal=NEURO_PARIETAL,
                    engagement_ch=NEURO_ENGAGEMENT_CH, eps=1e-9):
    """Les 3 indices BRUTS depuis des puissances de bande déjà calculées (dict `bp`).

    Voies (ordre device — Fz=0, Cz=2, Pz=4...) : `frontal`=θ frontal-médian (Fz+Cz), `parietal`=α
    pariéto-occipital, `engagement_ch`=sites postéro-centraux de Pope (EXCLUANT Fz). Voir l'en-tête
    pour les formules et leur limite (indices encore corrélés — à normaliser, à lire en tendance).
    """
    theta, alpha, beta = bp["theta"], bp["alpha"], bp["beta"]
    th_f = float(theta[frontal].mean())               # θ frontal-médian (Fz+Cz)
    al_p = float(alpha[parietal].mean())              # α pariéto-occipital
    e_th = float(theta[engagement_ch].mean())         # engagement sur sites postéro-centraux (Pope)
    e_al = float(alpha[engagement_ch].mean())
    e_be = float(beta[engagement_ch].mean())
    return {
        "charge":     th_f / (al_p + eps),
        "somnolence": al_p,                           # α postérieur absolu (z-normalisé au repos)
        "engagement": e_be / (e_th + e_al + eps),
    }


def indices(window, fs, frontal=NEURO_FRONTAL, parietal=NEURO_PARIETAL,
            engagement_ch=NEURO_ENGAGEMENT_CH, bands=NEURO_BANDS, highpass=None, eps=1e-9):
    """Convenance : calcule les puissances de bande puis les 3 indices. Voir indices_from_bp."""
    bp = band_powers(window, fs, bands, highpass=highpass)
    return indices_from_bp(bp, frontal, parietal, engagement_ch, eps)


def emg_power(bp):
    """Proxy EMG = puissance moyenne (toutes voies) de la bande "emg" (30-45 Hz), pour le veto."""
    return float(bp["emg"].mean()) if "emg" in bp else 0.0


class IndexNormalizer:
    """Normalise chaque indice en z contre un REPOS, EN ESPACE LOG, avec lissage EMA.

    Deux robustesses délibérées :
    - **log** : ces indices sont des RATIOS de bande, à distribution très asymétrique (queue lourde
      à droite : quand l'α s'effondre, le ratio explose de façon multiplicative). En z direct, le
      moindre effort SATURAIT l'échelle (charge « qui plafonne »). log(ratio) redresse la queue ->
      un doublement compte autant qu'une division par deux, le z reste borné et symétrique. C'est
      la pratique standard pour les ratios spectraux.
    - **médiane + MAD** (pas moyenne/écart-type) : un clignement résiduel pendant le repos ne fausse
      pas les échelles. L'EMA absorbe la variabilité fenêtre-à-fenêtre (ces ratios sont bruités).
    """

    def __init__(self, smooth=NEURO_SMOOTH, log=True):
        self.smooth = float(smooth)
        self.log = bool(log)
        self.mu, self.sd = {}, {}
        self._ema = {}

    def _tf(self, v):
        """Transforme un indice brut avant normalisation (log si activé, borné > 0)."""
        if not self.log:
            return float(v)
        return float(np.log(v if v > 1e-12 else 1e-12))

    def fit(self, samples):
        """`samples` : liste de dicts d'indices bruts mesurés au repos. Renvoie self."""
        keys = samples[0].keys()
        for k in keys:
            vals = np.array([self._tf(s[k]) for s in samples], dtype=float)
            mu = float(np.median(vals))
            mad = float(np.median(np.abs(vals - mu))) * 1.4826    # MAD -> σ robuste
            self.mu[k] = mu
            self.sd[k] = mad or float(vals.std()) or 1.0          # planchers si dispersion nulle
        return self

    @classmethod
    def identity(cls, keys, smooth=0.0):
        """Normaliseur neutre (μ=0, σ=1, sans log) — utilisé si le repos n'a pas pu être mesuré (smoke)."""
        self = cls(smooth=smooth, log=False)
        for k in keys:
            self.mu[k], self.sd[k] = 0.0, 1.0
        return self

    def center(self, k):
        """Centre de repos dans l'espace BRUT (lisible) : exp(μ) si log, sinon μ."""
        mu = self.mu.get(k, 0.0)
        return float(np.exp(mu)) if self.log else mu

    def z(self, raw):
        """z-scores LISSÉS (EMA) de l'échantillon courant, dict même clés que `raw`."""
        out = {}
        for k, v in raw.items():
            z = (self._tf(v) - self.mu.get(k, 0.0)) / (self.sd.get(k, 1.0) or 1.0)
            prev = self._ema.get(k, z)                 # 1re valeur : pas de lissage
            z = self.smooth * prev + (1.0 - self.smooth) * z
            self._ema[k] = z
            out[k] = z
        return out

    def creep(self, raw, rate):
        """Recale LENTEMENT le centre de repos (mu) vers l'échantillon courant — corrige la DÉRIVE
        multi-minutes (settling d'impédance des électrodes sèches, non-stationnarité de séance).

        `rate` petit (≈ dt/τ, τ ~ 2-5 min) : sur cette échelle, la dérive d'électrode est suivie
        tandis que les fluctuations d'état mental (plus rapides) se moyennent à zéro. N'affecte QUE
        mu (le zéro), jamais sd (l'échelle). À n'appeler que sur des fenêtres NON artefactées.
        rate<=0 => baseline figé (pas de re-calage)."""
        if rate <= 0.0:
            return
        for k, v in raw.items():
            if k in self.mu:
                self.mu[k] = (1.0 - rate) * self.mu[k] + rate * self._tf(v)


class NeuroDecoder:
    """Une fenêtre brute -> trois z lissés, veto d'artefact compris. **Une seule définition.**

    Cette classe existe pour une raison précise : le mode est utilisé par DEUX programmes —
    l'appli pygame (histogramme) et le moteur (flux `decoded_neuro`). Les mêmes vingt lignes
    recopiées des deux côtés dériveraient au premier réglage, et on afficherait alors une
    charge mentale à l'écran pendant qu'on en publierait une autre sur le réseau. Le projet a
    déjà payé ce genre de divergence sur la mesure de qualité (cf. `sigma_from_block`).

    Cycle d'utilisation :
        d = NeuroDecoder(fs)
        # 1. repos : accumuler des échantillons pendant NEURO_BASELINE_S
        s = d.sample(window);  reposes.append(s)
        # 2. caler les échelles du jour
        d.fit_baseline(reposes)
        # 3. en continu
        out = d.step(d.sample(window))   # {"z": {...}, "artifact": bool, "reason": str}

    Ce que la classe NE fait pas : la chauffe (jeter les premières secondes) et le rythme
    d'appel. Ils appartiennent à la boucle appelante, qui seule sait afficher un décompte.
    """

    def __init__(self, fs, update_hz=NEURO_UPDATE_HZ, rebaseline_s=NEURO_REBASELINE_S):
        self.fs = float(fs)
        self.norm = None
        self.sigma_ref = None      # σ par voie au repos -> rejet par voie
        self.emg_ref = None        # puissance 30-45 Hz au repos -> veto EMG
        # Vitesse de re-calage du zéro : une fraction dt/τ par fenêtre. Sur cette échelle
        # (τ ~ 3 min) la dérive d'impédance est suivie, tandis que les variations d'état
        # mental, plus rapides, se moyennent à zéro et ne sont donc PAS absorbées.
        self.rate = (1.0 / update_hz) / rebaseline_s if rebaseline_s > 0 else 0.0
        self.z = {k: 0.0 for k in INDEX_KEYS}
        self.artifacts = 0

    @property
    def ready(self):
        return self.norm is not None

    def sample(self, window):
        """Fenêtre BRUTE (n, 8) -> {"idx", "emg", "sig"}, ou None si la fenêtre est trop courte.

        Brute à dessein : le passe-bande d'acquisition (5-40 Hz) couperait le bas du θ. Le σ de
        contrôle, lui, est calculé à part sur une version bande-limitée + notch — un σ pris sur
        du quasi-brut est dominé par le secteur et la dérive, et déclenche de faux rejets même
        immobile (retour utilisateur 2026-07-23).
        """
        if window is None or len(window) < int(0.5 * self.fs):
            return None
        w = np.asarray(window, dtype=np.float64)
        wf = highpass_filter(w, self.fs, NEURO_HIGHPASS_HZ)
        bp = band_powers(wf, self.fs, NEURO_BANDS, highpass=None)   # wf déjà passe-hauté
        return {"idx": indices_from_bp(bp), "emg": emg_power(bp),
                "sig": artifact_sigma(w, self.fs)}

    def fit_baseline(self, samples, min_samples=3):
        """Cale les échelles du jour sur des échantillons de REPOS. False si trop peu."""
        samples = [s for s in samples if s is not None]
        if len(samples) < min_samples:
            return False
        self.norm = IndexNormalizer().fit([s["idx"] for s in samples])
        self.sigma_ref = np.median(np.stack([s["sig"] for s in samples]), axis=0)
        self.emg_ref = float(np.median([s["emg"] for s in samples]))
        return True

    def step(self, sample):
        """Échantillon courant -> {"z", "artifact", "reason", "raw"}.

        Une fenêtre artefactée ne met à jour NI les z NI le zéro : on rend les derniers z
        valides en signalant `artifact`. Publier des indices calculés sur un clignement serait
        pire que ne rien publier — ils sont plausibles, donc indétectables en aval.
        """
        if sample is None or not self.ready:
            return {"z": dict(self.z), "artifact": False, "reason": "", "raw": None}

        emg_limit = None if not self.emg_ref else NEURO_EMG_RATIO * self.emg_ref
        sig_limit = None if self.sigma_ref is None else NEURO_ARTIFACT_RATIO * np.asarray(self.sigma_ref)
        bad_emg = emg_limit is not None and sample["emg"] > emg_limit
        bad_sig = sig_limit is not None and bool(np.any(sample["sig"] > sig_limit))
        if bad_emg or bad_sig:
            self.artifacts += 1
            return {"z": dict(self.z), "artifact": True, "raw": sample["idx"],
                    "reason": "EMG mâchoire/muscle" if bad_emg else "mouvement / clignement"}

        self.z = self.norm.z(sample["idx"])
        self.norm.creep(sample["idx"], self.rate)   # re-calage lent, fenêtres propres seulement
        return {"z": dict(self.z), "artifact": False, "reason": "", "raw": sample["idx"]}


# --- Auto-test (les indices vont-ils dans le bon sens ?) --------------------

def _synth(fs=FS_UNICORN, secs=4.0, theta=0.0, alpha=0.0, beta=0.0,
           frontal_theta=0.0, emg=0.0, seed=0):
    """Signal (n, 8) = bruit blanc + sinusoïdes injectées par bande (amplitudes données).
    `frontal_theta` ajoute du θ sur Fz+Cz (voies 0,2) -> teste la charge ; `emg` injecte du 35 Hz
    sur toutes les voies -> teste le veto EMG (35 Hz est HORS de la bande β bornée à 25)."""
    rng = np.random.default_rng(seed)
    n = int(fs * secs)
    t = np.arange(n) / fs
    x = rng.standard_normal((n, 8)) * 0.5
    for freq, amp, chans in ((6.0, theta, range(8)), (10.0, alpha, range(8)),
                             (18.0, beta, range(8)), (6.0, frontal_theta, (0, 2)),
                             (35.0, emg, range(8))):
        if amp:
            for c in chans:
                x[:, c] += amp * np.sin(2 * np.pi * freq * t + rng.uniform(0, 2 * np.pi))
    return x


def _demo():
    import math
    fs = FS_UNICORN
    conds = {
        "repos       ": _synth(fs, theta=1.0, alpha=1.0, beta=1.0, seed=1),
        "engagé (β↑) ": _synth(fs, theta=1.0, alpha=1.0, beta=3.0, seed=2),
        "assoupi (α↑)": _synth(fs, theta=1.5, alpha=3.5, beta=0.6, seed=3),
        "charge (θf↑)": _synth(fs, theta=1.0, alpha=1.0, beta=1.0, frontal_theta=3.0, seed=4),
    }
    vals = {}
    print(f"[neuro] auto-test v2  fs={fs:.0f}Hz  bandes={NEURO_BANDS}")
    for name, x in conds.items():
        idx = indices(x, fs)
        vals[name.strip()] = idx
        print(f"  {name} : " + "  ".join(f"{k}={idx[k]:7.2f}" for k in INDEX_KEYS))

    ok = [True]
    def chk(cond, msg):
        if not cond:
            ok[0] = False; print("  ✗ " + msg)

    R = vals["repos"]
    chk(vals["engagé (β↑)"]["engagement"] > R["engagement"], "engagement ne monte pas avec β")
    chk(vals["assoupi (α↑)"]["somnolence"] > R["somnolence"], "somnolence ne monte pas avec α")
    chk(vals["assoupi (α↑)"]["engagement"] < R["engagement"], "engagement ne baisse pas avec α")
    chk(vals["charge (θf↑)"]["charge"] > R["charge"], "charge ne monte pas avec le θ frontal")

    # NON-REDONDANCE : sous β↑ seul, l'engagement bouge fort, la somnolence (α postérieur) ~pas.
    som_rel = abs(math.log(vals["engagé (β↑)"]["somnolence"] / R["somnolence"]))
    eng_rel = abs(math.log(vals["engagé (β↑)"]["engagement"] / R["engagement"]))
    print(f"  non-redondance (β↑ seul) : |Δlog som|={som_rel:.2f}  |Δlog eng|={eng_rel:.2f}")
    chk(som_rel < 0.5 * eng_rel, "somnolence suit encore l'engagement (redondance non levée)")

    # VETO EMG : un 35 Hz gonfle la bande emg SANS toucher β (13-25) -> engagement ~inchangé.
    bp0 = band_powers(_synth(fs, theta=1.0, alpha=1.0, beta=1.0, seed=7), fs)
    bpE = band_powers(_synth(fs, theta=1.0, alpha=1.0, beta=1.0, emg=4.0, seed=7), fs)
    e0, eE = emg_power(bp0), emg_power(bpE)
    print(f"  veto EMG : puissance bande emg  repos={e0:.2f} -> avec EMG 35 Hz={eE:.2f}")
    chk(eE > 3.0 * e0, "la bande EMG (30-45 Hz) ne détecte pas l'injection 35 Hz")
    chk(abs(math.log(indices_from_bp(bpE)["engagement"] / indices_from_bp(bp0)["engagement"])) < 0.3,
        "l'EMG 35 Hz contamine encore l'engagement (β mal borné)")

    # Normalisation : repos ~0 en z, perturbation qui sort ; re-calage (creep) déplace bien le zéro.
    norm = IndexNormalizer(smooth=0.0).fit(
        [indices(_synth(fs, theta=1.0, alpha=1.0, beta=1.0, seed=s), fs) for s in range(10, 25)])
    z_rest = norm.z(indices(_synth(fs, theta=1.0, alpha=1.0, beta=1.0, seed=99), fs))
    z_eng = norm.z(indices(_synth(fs, theta=1.0, alpha=1.0, beta=3.0, seed=99), fs))
    print("  z(repos)     : " + "  ".join(f"{k}={z_rest[k]:+5.2f}" for k in INDEX_KEYS))
    print("  z(engagé β↑) : " + "  ".join(f"{k}={z_eng[k]:+5.2f}" for k in INDEX_KEYS))
    chk(abs(z_rest["engagement"]) < 3.0, "le repos ne retombe pas ~0 en z")
    chk(z_eng["engagement"] > z_rest["engagement"] + 1.0, "l'engagement normalisé ne se détache pas du repos")
    mu0 = norm.mu["engagement"]
    for _ in range(50):
        norm.creep(indices(_synth(fs, theta=1.0, alpha=1.0, beta=3.0, seed=99), fs), 0.05)
    chk(norm.mu["engagement"] > mu0, "le re-calage lent (creep) ne déplace pas le zéro")

    print("[neuro] auto-test OK" if ok[0] else "[neuro] auto-test ÉCHOUÉ")
    return ok[0]


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if _demo() else 1)
