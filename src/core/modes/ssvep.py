"""Mode SSVEP : quelle cible clignotante l'utilisateur regarde. BCI **active**.

Le décodage lui-même est dans `core/cca_decoder.py` — une CCA, sans entraînement. Ici on décrit
le MODE : ce qui se règle, ce qui se publie, ce qu'il faut mesurer avant de décider.

⚠️ Le moteur ne rend AUCUN stimulus. C'est l'application cliente qui fait clignoter les cibles ;
elle déclare simplement leurs fréquences ici. Le couplage est lâche — aucune synchronisation à la
frame n'est nécessaire, contrairement au c-VEP.
"""

import os as _os
import sys as _sys
import time as _time

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (SSVEP_BASELINE_S, SSVEP_WARMUP_S, ARTIFACT_SIGMA_RATIO,  # noqa: E402
                         ALPHA_DEFAUT_HZ, BANDPASS, OCCIPITAL, Z_MIN, use_utf8_console,
                         choose_frequencies)
import numpy as np  # noqa: E402

from core.cca_decoder import CCADecoder  # noqa: E402
from core.i18n import nombre, tr  # noqa: E402
from core.lsl_io import DecodedSSVEPPublisher, ssvep_channel_labels, stream_name  # noqa: E402
from core.modes.contract import ModeSpec, Param, Rest, bande_de, params_bande, validate  # noqa: E402
from core.modes.runtime import ModeRuntime  # noqa: E402

# Le défaut vient de `choose_frequencies`, la MÊME fonction que le stimulus : passer le même
# refresh des deux côtés garantit l'accord sans recopier des décimales à la main.
FREQS_60HZ = tuple(c["actual_hz"] for c in choose_frequencies(60))   # 15 · 20 · 8,571 Hz

# Les bornes de la BANDE réglable (2026-09-30). Défaut : `BANDPASS`, la bande de toujours.
# ⚠️ La coupure basse ne descend PAS sous 3 Hz, et c'est MESURÉ, pas choisi : le filtre de la
# fenêtre (`acquisition._filter`, Butterworth à PASSE UNIQUE) ne dispose que de `FILTER_MARGIN_S`
# (1 s) pour s'établir, et son transitoire s'éteint d'autant plus lentement que la coupure est
# basse. Sur un offset qui dérive de 2000 µV/s (l'Unicorn le fait, cf. `Rest.warmup_s`), le σ de
# la fenêtre vaut 1,00 × celui du régime établi à 5 Hz, 1,01 × à 3 Hz, 1,5 × à 2 Hz et 15,6 × à
# 1 Hz : sous 3 Hz, le mode décoderait le transitoire de son propre filtre. L'autotest de
# `modes/ssvep_mesure.py` rejoue cette mesure à la borne déclarée ici.
# La coupure haute ne descend pas sous 20 Hz : c'est la plus haute cible du trio du dépôt, et les
# bornes garantissent ainsi que les réglages par défaut restent valides quelle que soit la bande.
# ⚠️ Et elle ne MONTE pas au-dessus de 45 Hz (revue du 2026-09-30) : le filtre de la fenêtre finit
# par le coupe-bande SECTEUR (`remove_environmental_noise`), qui éteint 48-52 Hz à 50 Hz et
# 58-62 Hz à 60 Hz — mesuré, un sinus ressort à 0,50 à 48 Hz, à 0,999 à 45 Hz. À 60, la bande
# acceptait une cible dans ce trou (50 Hz sur un écran à 100 Hz, que « Proposer » proposait), et la
# référence CCA y gardait des harmoniques (25 × 2 = 50) que le filtre avait retirées : du bruit dans
# le ρ, une cible qui ne sort jamais, rien qui lève. Plafonnée ici, la coupure haute borne AUSSI les
# harmoniques (`max_freq`) : rien de ce que le décodeur corrèle n'approche le secteur.
SSVEP_BANDE_BAS = (3.0, 8.0)
SSVEP_BANDE_HAUT = (20.0, 45.0)

SSVEP_DECODE_HZ = 5.0            # cadence de décodage (fenêtres glissantes de WINDOW_S)
SSVEP_BASELINE_SAMPLE_HZ = 5.0   # cadence d'échantillonnage du plancher de repos


class SsvepRuntime(ModeRuntime):
    """Mesure d'abord le plancher de repos, décide ensuite. Publie sur l'échelle z, toujours.

    Pourquoi un plancher alors que le SSVEP est réputé « sans calibration » : chaque fréquence a
    un fond de corrélation DIFFÉRENT au repos, selon sa proximité au pic alpha du jour. Un seuil
    commun est donc structurellement injuste — mesuré sur ce casque, une cible proche de l'alpha
    n'émettait jamais alors que son ρ moyen dépassait le seuil. Ce n'est pas un modèle appris,
    juste un étalonnage de quelques secondes, à refaire à chaque séance.
    """

    def __init__(self, spec, params, engine):
        super().__init__(spec, params, engine)
        self._out = None
        self.decoder = None
        self._samples, self._sigmas = [], []
        self._sigma_ref = None
        self._warned = False
        self._decoded = None
        self._last_log = 0.0
        self._new_decoder()

    def bande(self):
        """La bande `(bas, haut)` de CE décodage : celle que `_new_decoder` a FIGÉE avec lui.

        ⚠️ Jamais relue dans `self.params` à chaque fenêtre. Le plancher μ/σ par fréquence, la
        coupure des références (`max_freq`) et le σ de référence du rejet d'artefact se mesurent au
        REPOS, sous la bande de ce moment-là. Relue en direct, une bande changée « en place » (le
        chemin du moteur pour un réglage `affecte_decodage=False`, `server._set_params`) ferait
        filtrer chaque fenêtre sous la NOUVELLE bande et la comparer à un plancher mesuré sous
        l'ANCIENNE : des z décalés, sans rien lever. Une bande nouvelle prend donc effet avec un
        décodeur neuf, c'est-à-dire avec un repos refait — et c'est pour ça que ses deux réglages
        affectent le décodage (vérifié par l'autotest).
        """
        return self._bande

    def _new_decoder(self):
        # Le seuil de détection est un RÉGLAGE (2026-09-24) : lu dans les paramètres, jamais dans
        # la constante seule. `.get` parce qu'un appelant du banc d'essai peut ne passer que les
        # fréquences — il retombe alors sur le défaut du réglage, qui EST `Z_MIN`.
        # La BANDE est lue ICI, et nulle part ailleurs (2026-09-30) : figée avec le décodeur dont
        # le plancher sera mesuré sous elle (cf. `bande`). Même repli que le seuil : un appelant
        # du banc d'essai qui ne passe que les fréquences retombe sur `BANDPASS`, le défaut.
        # `max_freq` = sa coupure HAUTE : une harmonique au-dessus, le filtre l'a supprimée, et la
        # garder dans la référence n'ajouterait que du bruit au ρ de SA cible
        # (cf. `cca_decoder.reference_signals`) — exactement ce qui se passait déjà à 40 Hz.
        self._bande = bande_de(self.params, BANDPASS)
        self.decoder = CCADecoder(list(self.params["freqs"]), fs=self.engine.acq.fs,
                                  z_min=float(self.params.get("z_min", Z_MIN)),
                                  max_freq=self._bande[1])

    def _open(self):
        # Le flux est créé TOUT DE SUITE, avant même la mesure du repos, et reste silencieux
        # jusqu'à ce que le décodage commence. Le faire apparaître seulement à la fin du repos
        # serait un piège : un client qui cherche le flux au lancement ne le trouve pas et
        # abandonne (`resolve_byprop` a un délai fini) — vécu au premier essai casque.
        #
        # L'échelle de décision fait partie du contrat et ne change donc jamais : on décide
        # TOUJOURS sur z, quitte à prolonger le repos jusqu'à pouvoir le mesurer.
        self._out = DecodedSSVEPPublisher(
            list(self.params["freqs"]), decision_scale="z",
            thresholds=(self.decoder.z_min, self.decoder.z_margin),
            instance=self.engine.instance)

    def _close(self):
        self._out = None

    def _reset_rest(self):
        self._samples, self._sigmas = [], []
        self._sigma_ref = None
        self._warned = False
        self._decoded = None
        self._new_decoder()   # un décodeur neuf : son plancher est TOUT ce qu'il a appris

    def period_s(self):
        return 1.0 / (SSVEP_DECODE_HZ if self.phase == "running" else SSVEP_BASELINE_SAMPLE_HZ)

    def output(self):
        return self._decoded

    def _rest_step(self, engine, now):
        # SA bande, au repos comme en décodage : un plancher mesuré sous un autre filtre que les
        # fenêtres qu'on lui compare décalerait tous les z, sans rien lever.
        window = engine.acq.occipital_window(engine.recent, bande=self.bande())
        if window is None:
            return False

        self._samples.append(self.decoder.scores(window))
        self._sigmas.append(float(window.std(axis=0).mean()))
        if now < self._rest_until:
            return False

        if not self.decoder.fit_baseline(self._samples):
            # Pas encore assez de fenêtres. On PROLONGE le repos au lieu de basculer sur les ρ
            # bruts : l'échelle de décision est annoncée dans les métadonnées du flux, en
            # changer en cours de route casserait le contrat. Les fenêtres arrivent à 5 Hz.
            if not self._warned:
                self._warned = True
                self._dire(f"[ssvep] repos prolongé : {len(self._samples)} fenêtres, "
                      f"pas encore de quoi mesurer un plancher fiable")
            return False

        self._sigma_ref = float(np.median(self._sigmas))
        line = "  ".join(f"{f:g}Hz: μ={m:.2f} σ={s:.2f}"
                         for f, (m, s) in self.decoder.baseline.items())
        self._dire(f"[ssvep] plancher de repos ({len(self._samples)} fenêtres) — {line}")

        # Un plancher trop DISPERSÉ rend le seuil inatteignable, en silence : on décide sur
        # z=(ρ-μ)/σ, donc un σ gonflé exige un ρ que le SSVEP ne produit jamais en électrodes
        # sèches. Vécu sur casque le 2026-07-27 : σ=0,19 => il aurait fallu ρ≈0,94. Mieux vaut le dire tout de
        # suite que laisser l'utilisateur fixer une cible qui ne peut pas sortir.
        for f, (mu, sd) in self.decoder.baseline.items():
            needed = mu + self.decoder.z_min * sd
            if needed > 0.85:
                self._dire(f"[ssvep] ⚠️  {f:g} Hz : plancher trop dispersé (μ={mu:.2f} σ={sd:.2f}) "
                      f"-> il faudrait ρ={needed:.2f} pour détecter. Cible quasi INDÉTECTABLE : "
                      f"contact des électrodes occipitales, ou refaire le repos immobile.")
        self._dire(f"[ssvep] σ de référence {self._sigma_ref:.1f} -> rejet d'artefact au-delà "
              f"de {ARTIFACT_SIGMA_RATIO * self._sigma_ref:.0f}")
        self._dire(f"[ssvep] décodage en cours sur {stream_name('decoded_ssvep')} "
              f"(échelle z, seuil {self.decoder.z_min}) — fixe une cible")
        self.rest_report = {
            "kind": "ssvep",
            "windows": len(self._samples),
            "targets": [{"freq_hz": float(f), "mu": round(mu, 3), "sigma": round(sd, 3),
                         "rho_needed": round(mu + self.decoder.z_min * sd, 2)}
                        for f, (mu, sd) in self.decoder.baseline.items()],
        }
        return True

    def _run_step(self, engine, lsl_ts):
        window = engine.acq.occipital_window(engine.recent, bande=self.bande())
        if window is None:
            return
        freqs = list(self.params["freqs"])

        # Rejet d'artefact : une fenêtre dont l'amplitude explose par rapport au repos ne
        # contient pas d'EEG (mouvement, clignement). En décoder des ρ produirait des
        # détections aléatoires ; on publie « aucune cible » plutôt que du bruit habillé.
        sd = float(window.std(axis=0).mean())
        if self._sigma_ref and sd > ARTIFACT_SIGMA_RATIO * self._sigma_ref:
            zeros = [0.0] * len(freqs)
            self._publish(-1, 0.0, 0.0, zeros, lsl_ts, artifact=True)
            return

        freq, scores = self.decoder.classify(window)
        ordered = [scores[f] for f in freqs]
        if freq is None:
            self._publish(-1, 0.0, max(ordered), ordered, lsl_ts)
        else:
            index = freqs.index(freq)
            self._publish(index, freq, scores[freq], ordered, lsl_ts)

    def _publish(self, index, freq_hz, confidence, scores, lsl_ts, artifact=False):
        if self._out is not None:
            self._out.push(index, freq_hz, confidence, scores, lsl_ts)
        self._decoded = {
            "target_index": int(index),
            "freq_hz": float(freq_hz),
            "scores": [round(float(v), 2) for v in scores],
            "artifact": bool(artifact),
            "threshold": float(self.decoder.z_min),
        }
        self._log(index, scores, artifact)

    def _dire(self, texte):
        """Les messages du REPOS (plancher, σ de référence, « décodage en cours »). Une méthode, et
        pas des `print` épars, pour la même raison que `_log` : le TEST du SSVEP rejoue ce repos
        par le code du mode (`ssvep_mesure._DecideurSSVEP`) et coupe ces lignes, qui feraient
        croire au terminal que le mode tourne et publie."""
        print(texte)

    def _log(self, index, scores, artifact):
        """Trace la décision en console ~1×/s.

        Le moteur est fait pour être consommé par un client, mais pendant une séance casque on
        veut voir ce qu'il décode SANS dépendre d'un troisième terminal branché au bon moment.
        Les scores sont affichés à côté de la décision : c'est ce qui permet de dire si une
        non-détection vient d'un signal absent ou d'un seuil trop haut.
        """
        now = _time.perf_counter()
        if now - self._last_log < 1.0:
            return
        self._last_log = now
        freqs = list(self.params["freqs"])
        detail = "  ".join(f"{f:g}Hz z={s:+5.2f}" for f, s in zip(freqs, scores))
        if artifact:
            verdict = "ARTEFACT (fenêtre rejetée)"
        elif index < 0:
            verdict = f"— (rien au-dessus de z={self.decoder.z_min})"
        else:
            verdict = f"CIBLE {index} ({freqs[index]:g} Hz)"
        print(f"[ssvep] {verdict:<34} {detail}")


def _channels(params):
    return ssvep_channel_labels(params["freqs"])


SPEC = ModeSpec(
    id="ssvep",
    label=tr("mode.ssvep.label"),
    family="actif",
    summary=tr("mode.ssvep.summary"),
    status="moteur",
    key_channels=tuple(OCCIPITAL),   # les 4 occipitales : le SSVEP y est maximal
    # La fenêtre qui fait clignoter les cibles PENDANT le décodage. Le SSVEP n'a aucune
    # calibration (la CCA n'apprend rien) : sans ce champ, son bouton « Lancer le stimulus »
    # n'existait nulle part, et on ne pouvait pas éprouver le mode depuis l'application.
    stimulus_id="ssvep",
    # Le « Tester » de ce mode : la mesure du taux d'émission, jouée sur les réglages COURANTS
    # (la console passe les fréquences retenues à sa fenêtre guidée, qui les annonce au moteur).
    test_id="ssvep_taux",
    params=(
        Param(
            key="freqs",
            label=tr("mode.ssvep.param.freqs.label"),
            kind="float_list",
            unit="Hz",
            default=FREQS_60HZ,
            count=(2, 8),
            constraints=("dans_la_bande", "separables", "divise_le_refresh"),
            help=tr("mode.ssvep.param.freqs.aide"),
        ),
        Param(
            key="refresh_hz",
            label=tr("mode.ssvep.param.refresh_hz.label"),
            kind="float",
            unit="Hz",
            default=60.0,
            min=20.0, max=480.0,
            proposes="freqs",
            affecte_decodage=False,
            help=tr("mode.ssvep.param.refresh_hz.aide"),
        ),
        Param(
            key="alpha_hz",
            label=tr("mode.ssvep.param.alpha_hz.label"),
            kind="float",
            unit="Hz",
            default=ALPHA_DEFAUT_HZ,
            min=6.0, max=14.0,
            proposes="freqs",
            affecte_decodage=False,
            help=tr("mode.ssvep.param.alpha_hz.aide"),
        ),
        # Le seuil de détection (2026-09-24, demandé au casque : « un réglage pour augmenter ou
        # diminuer la détection »). UN seul réglage, exprès : la marge sur le 2e (`Z_MARGIN`, à 0)
        # et un vote glissant jouent sur le MÊME compromis et se compenseraient. Il affecte le
        # décodage (défaut de `Param`) : le seuil est annoncé dans les métadonnées du flux
        # `decoded_ssvep`, un contrat public ; le changer pendant que le mode tourne recrée donc
        # le flux, pour que ce qu'il annonce reste vrai. On le règle mode ARRÊTÉ, puis « Tester ».
        Param(
            key="z_min",
            label=tr("mode.ssvep.param.z_min.label"),
            kind="float",
            default=Z_MIN,
            min=1.0, max=6.0,
            help=tr("mode.ssvep.param.z_min.aide"),
        ),
        # La BANDE du filtre qui précède le décodage (2026-09-30). Réglée dans « Régler », parce
        # que le SSVEP n'a pas de modèle : aucun apprentissage ne dépend d'elle, contrairement aux
        # quatre modes à modèle, qui la règlent à l'entraînement. Elle affecte le décodage (défaut
        # de `Param`) : le plancher de repos est mesuré PAR fréquence SOUS ce filtre, il est donc
        # refait quand elle change. ⚠️ Ce n'est pas une politesse : le runtime FIGE la bande avec
        # son décodeur (`SsvepRuntime.bande`), donc une bande `affecte_decodage=False` serait
        # acceptée, annoncée, et resterait sans effet jusqu'au prochain repos. La contrainte
        # `dans_la_bande` des fréquences la lit.
        *params_bande(BANDPASS, SSVEP_BANDE_BAS, SSVEP_BANDE_HAUT,
                      tr("mode.ssvep.param.bande.aide", bas=nombre(BANDPASS[0]),
                         haut=nombre(BANDPASS[1]), plancher=nombre(SSVEP_BANDE_BAS[0]),
                         plafond=nombre(SSVEP_BANDE_HAUT[1]))),
    ),
    rest=Rest(
        warmup_s=SSVEP_WARMUP_S,
        duration_s=SSVEP_BASELINE_S,
        # ⚠️ PAS de `tr()` ici, exprès : cette consigne part AUSSI sur le flux LSL `status` (champ
        # `instruction`, cf. `server._state` et docs/SPEC.md), un contrat public qui ne doit changer
        # ni de mots ni de langue avec l'écran. Même règle pour les quatre autres `Rest`.
        instruction="Ne fixe AUCUNE cible : on mesure le bruit de fond de chaque fréquence.",
    ),
    calibration=None,   # la CCA n'apprend rien ; le repos est un étalonnage, pas un modèle
    stream="decoded_ssvep",
    channels_fn=_channels,
    runtime_cls=SsvepRuntime,
)


def _selftest():
    """Le repos, puis la décision — sur du signal FABRIQUÉ, avec un faux moteur.

    On ne juge PAS la justesse du décodage : du bruit synthétique n'a pas de SSVEP, donc la
    cible « détectée » n'a aucun sens. On vérifie l'ENCHAÎNEMENT et le CONTRAT : que le plancher
    se mesure, qu'une fenêtre d'artefact est rejetée plutôt que décodée, et qu'une décision
    publiée porte bien un index dans les bornes.
    """
    from core.acquisition import UnicornAcquisition

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _FauxPublieur:
        def __init__(self):
            self.lignes = []

        def push(self, index, freq_hz, confidence, scores, lsl_ts=None):
            self.lignes.append((index, freq_hz, confidence, list(scores)))

    class _FauxMoteur:
        """Juste ce dont un runtime a besoin : une acquisition et un tampon récent."""

        def __init__(self, recent):
            self.acq = UnicornAcquisition(synthetic=True)
            self.instance = "selftest"
            self.recent = recent

    rng = np.random.default_rng(0)
    fs = 250
    bruit = rng.normal(0.0, 8.0, (int(4.0 * fs), 8))
    moteur = _FauxMoteur(bruit)

    values, reason = validate(SPEC, {})
    chk(values is not None, f"les réglages par défaut du SSVEP sont valides ({reason})")

    rt = SsvepRuntime(SPEC, values, moteur)
    rt._out = _FauxPublieur()
    rt._opened = True
    chk(rt.phase == "warmup", "le SSVEP commence par une chauffe")
    chk(len(rt.params["freqs"]) == 3, f"3 cibles par défaut ({rt.params['freqs']})")

    # Le SEUIL DE DÉTECTION est un réglage (2026-09-24) : lu dans les paramètres, et relu quand le
    # repos refait un décodeur neuf — sinon « Refaire le repos » ramènerait en douce la constante.
    chk(values["z_min"] == Z_MIN and rt.decoder.z_min == Z_MIN,
        f"le seuil par défaut est {Z_MIN} écarts-types ({values['z_min']}, {rt.decoder.z_min})")
    v17, _r = validate(SPEC, {"z_min": 1.7})
    rt17 = SsvepRuntime(SPEC, v17, moteur)
    rt17._reset_rest()
    chk(rt17.decoder.z_min == 1.7, f"un seuil réglé atteint le décodeur, repos refait compris "
        f"({rt17.decoder.z_min})")
    _v, refus = validate(SPEC, {"z_min": 0.5})
    chk(_v is None and "Seuil de détection" in (refus or ""),
        f"un seuil hors bornes est refusé, en nommant le réglage ({refus})")

    # Repos : on force des durées courtes, comme le fait `--baseline` / `--warmup`.
    rt.begin_rest(now=0.0, warmup_s=0.0, duration_s=1.0)
    now = 0.0
    for _ in range(40):
        now += 0.2
        moteur.recent = rng.normal(0.0, 8.0, (int(4.0 * fs), 8))
        rt.tick(moteur, lsl_ts=now, now=now)
        if rt.phase == "running":
            break
    chk(rt.phase == "running", f"le plancher finit par tenir (phase={rt.phase})")
    chk(rt.rest_report and rt.rest_report["kind"] == "ssvep"
        and len(rt.rest_report["targets"]) == 3,
        f"le repos rend un compte-rendu par cible ({rt.rest_report})")
    chk(rt._sigma_ref and rt._sigma_ref > 0,
        f"un σ de référence est mesuré pour le rejet d'artefact ({rt._sigma_ref})")

    # Décision sur du bruit : l'index doit rester dans les bornes, quoi qu'il décide.
    avant = len(rt._out.lignes)
    rt.tick(moteur, lsl_ts=now, now=now + 0.2)
    chk(len(rt._out.lignes) == avant + 1, "une décision est publiée à chaque pas")
    index, _freq, _conf, scores = rt._out.lignes[-1]
    chk(-1 <= index < 3, f"index de cible dans les bornes ({index})")
    chk(len(scores) == 3, f"un score par cible ({scores})")

    # Artefact : une fenêtre dont l'amplitude explose ne contient pas d'EEG. On publie
    # « aucune cible » plutôt que des corrélations calculées sur un clignement.
    moteur.recent = rng.normal(0.0, 8.0 * 50, (int(4.0 * fs), 8))
    rt.tick(moteur, lsl_ts=now, now=now + 0.4)
    index, _f, _c, scores = rt._out.lignes[-1]
    chk(index == -1 and rt.output()["artifact"],
        f"une fenêtre d'artefact est rejetée, pas décodée (index={index})")

    # === La BANDE réglable : mesurée au repos, FIGÉE avec le décodeur (2026-09-30) ==============
    # Plancher μ/σ, coupure des références et σ de référence du rejet d'artefact se mesurent sous
    # la bande du REPOS. On les recalcule ici à la main sous une bande NON défaut, sur les blocs
    # mêmes que le runtime a vus : un σ de référence pris sous `BANDPASS` (par `sigma_from_block`,
    # ou une fenêtre filtrée sans la bande) garderait le rejet d'artefact sur l'ancienne échelle.
    acq_b = moteur.acq
    bande_r = (8.0, 25.0)
    v_b, raison_b = validate(SPEC, {"bande_bas": bande_r[0], "bande_haut": bande_r[1]})
    rt_b = SsvepRuntime(SPEC, v_b or values, moteur)
    rt_b._out = _FauxPublieur()
    rt_b._opened = True
    rt_b.begin_rest(now=0.0, warmup_s=0.0, duration_s=1.0)
    repos_b, now_b = [], 0.0
    while rt_b.phase != "running" and len(repos_b) < 40:
        now_b += 0.2
        moteur.recent = rng.normal(0.0, 8.0, (int(4.0 * fs), 8))
        repos_b.append(moteur.recent)
        rt_b.tick(moteur, lsl_ts=now_b, now=now_b)

    def _sigma_main(bande):
        return float(np.median([acq_b.occipital_window(b, bande=bande).std(axis=0).mean()
                                for b in repos_b]))

    chk(v_b is not None and rt_b.phase == "running" and len(rt_b._sigmas) == len(repos_b)
        and abs(rt_b._sigma_ref - _sigma_main(bande_r)) <= 1e-9 * _sigma_main(bande_r),
        f"🔴 le σ de référence du rejet d'artefact est mesuré sous la bande RÉGLÉE "
        f"{bande_r[0]:g}-{bande_r[1]:g} Hz ({rt_b._sigma_ref} ; à la main {_sigma_main(bande_r)} ; "
        f"{raison_b})")
    chk(abs(_sigma_main(bande_r) - _sigma_main(BANDPASS)) > 0.05 * _sigma_main(BANDPASS),
        f"…et la comparaison MORD : sous {BANDPASS[0]:g}-{BANDPASS[1]:g} Hz, les mêmes blocs "
        f"donnent σ = {_sigma_main(BANDPASS):.2f}")

    # Le moteur applique un réglage « EN PLACE » (`rt.params` remplacé, rien reconstruit) quand
    # aucun réglage qui affecte le décodage n'a bougé. On rejoue ce geste avec une AUTRE bande :
    # le runtime doit continuer à décider sous la bande de SON plancher — filtre, références et z
    # recalculés à la main sous l'ancienne. Relue en direct, la fenêtre serait filtrée sur
    # 5-40 Hz et comparée à un plancher mesuré sur 8-25 Hz.
    rt_b.params = dict(rt_b.params, bande_bas=BANDPASS[0], bande_haut=BANDPASS[1])
    moteur.recent = rng.normal(0.0, 8.0, (int(4.0 * fs), 8))
    rt_b.tick(moteur, lsl_ts=now_b, now=now_b + 0.2)
    dec_b = rt_b.decoder
    z_main = dec_b.z_scores(dec_b.scores(acq_b.occipital_window(moteur.recent, bande=bande_r)))
    publie = rt_b._out.lignes[-1][3] if rt_b._out.lignes else None
    chk(rt_b.bande() == bande_r and dec_b.max_freq == bande_r[1]
        and not (rt_b.output() or {}).get("artifact", True)
        and publie == [z_main[f] for f in rt_b.params["freqs"]],
        f"🔴 une bande changée EN PLACE ne touche pas le décodeur en cours : il décide sous "
        f"{bande_r[0]:g}-{bande_r[1]:g} Hz, celle de son plancher (bande {rt_b.bande()}, "
        f"max_freq {dec_b.max_freq})")
    rt_b.begin_rest(now=now_b + 0.4, warmup_s=0.0, duration_s=1.0)
    chk(rt_b.bande() == tuple(BANDPASS) and rt_b.decoder.max_freq == BANDPASS[1],
        f"…et un repos refait la prend, avec un décodeur neuf ({rt_b.bande()}, "
        f"max_freq {rt_b.decoder.max_freq})")

    # === La coupure haute ne monte pas jusqu'au SECTEUR (revue du 2026-09-30) ==================
    # L'exemple de la revue : écran 100 Hz, coupure haute 60, une cible à 50 Hz — accepté, et le
    # coupe-bande secteur l'éteignait avant le décodage.
    _v, refus_60 = validate(SPEC, {"refresh_hz": 100.0, "bande_haut": 60.0,
                                   "freqs": [12.5, 20.0, 50.0]})
    chk(_v is None and refus_60 and tr("moteur.bande.haut") in refus_60,
        f"une coupure haute à 60 Hz (cible à 50 Hz sur un écran à 100 Hz) est refusée ({refus_60})")
    # Et, à la coupure haute MAXIMALE, rien de ce que le décodeur CORRÈLE — cibles et harmoniques
    # de ses références, lues dans la matrice qu'il construit — ne tombe dans le coupe-bande, à 50
    # comme à 60 Hz. Le coupe-bande est l'appel même de `acquisition._filter`. Deux jeux : 25 × 2
    # = 50 (l'harmonique de la revue), et une cible posée SUR la coupure (45 Hz, écran à 90 Hz).
    from brainflow.data_filter import DataFilter
    from core.acquisition import NOTCH_SECTEUR

    t_s = np.arange(20 * fs) / fs

    def _passe(f, bruit):
        x = np.ascontiguousarray(np.sin(2 * np.pi * f * t_s))
        DataFilter.remove_environmental_noise(x, fs, bruit.value)
        return float(x[5 * fs:-5 * fs].std() / np.sin(2 * np.pi * f * t_s)[5 * fs:-5 * fs].std())

    correles, refus_max = set(), []
    for refresh, cibles in ((100.0, [12.5, 20.0, 25.0]), (90.0, [15.0, 22.5, 45.0])):
        v_max, r_max = validate(SPEC, {"refresh_hz": refresh, "freqs": cibles,
                                       "bande_haut": SSVEP_BANDE_HAUT[1]})
        if v_max is None:
            refus_max.append(r_max)
            continue
        dec_m = SsvepRuntime(SPEC, v_max, moteur).decoder
        n_ref = acq_b.window_n
        correles |= {h * f for f in dec_m.freqs
                     for h in range(1, dec_m._ref(f, n_ref).shape[1] // 2 + 1)}
    pire = min((_passe(f, bruit), f, s) for f in correles for s, bruit in NOTCH_SECTEUR.items())
    chk(not refus_max and pire[0] > 0.99,
        f"🔴 à la coupure haute maximale ({SSVEP_BANDE_HAUT[1]:g} Hz), aucune cible ni harmonique "
        f"corrélée ne tombe dans le coupe-bande secteur : la pire ressort à {pire[0]:.3f} "
        f"({pire[1]:g} Hz, secteur {pire[2]:g} Hz ; {sorted(correles)} ; {refus_max})")

    # Les défauts du mode ne bougent PAS : ils sont validés sur casque réel. La proposition est
    # une action que l'étudiant déclenche, jamais un recalcul silencieux au démarrage.
    defauts = SPEC.defaults()
    chk(tuple(round(f, 6) for f in defauts["freqs"]) == tuple(round(f, 6) for f in FREQS_60HZ),
        f"les fréquences par défaut sont inchangées ({defauts['freqs']})")
    chk(defauts["refresh_hz"] == 60.0 and defauts["alpha_hz"] == ALPHA_DEFAUT_HZ,
        f"le refresh et l'alpha ont leurs défauts ({defauts['refresh_hz']}, {defauts['alpha_hz']})")

    # Et les défauts doivent être COHÉRENTS entre eux : 15/20/8,571 sont bien des diviseurs de 60.
    _v, raison = validate(SPEC, {})
    chk(raison is None, f"les défauts du mode passent leur propre validation ({raison})")

    # Aucun des deux nouveaux réglages ne relance le repos.
    par_cle = {p.key: p for p in SPEC.params}
    chk(par_cle["freqs"].affecte_decodage is True, "changer les fréquences affecte le décodage")
    chk(par_cle["refresh_hz"].affecte_decodage is False
        and par_cle["alpha_hz"].affecte_decodage is False,
        "le refresh et l'alpha, non")
    # La bande, elle, AFFECTE le décodage — et il le faut : le runtime la fige avec son décodeur
    # (cf. `SsvepRuntime.bande`). Appliquée « en place », elle serait acceptée, annoncée « appliqué »,
    # et sans effet jusqu'au prochain repos.
    chk(par_cle["bande_bas"].affecte_decodage is True
        and par_cle["bande_haut"].affecte_decodage is True,
        "🔴 changer la bande affecte le décodage : le moteur reconstruit le runtime et refait le "
        "repos, seul chemin par lequel une bande nouvelle atteint le décodeur")
    chk(par_cle["refresh_hz"].proposes == "freqs", "et le refresh PROPOSE les fréquences")
    chk(par_cle["alpha_hz"].proposes == "freqs",
        "l'alpha aussi PROPOSE les fréquences — sans bouton, changer son pic ne recalcule rien")

    # Le refus qui ferme le trou.
    _v, raison = validate(SPEC, {"freqs": [15.0, 17.0]})
    chk(raison is not None and "diviseur entier" in raison,
        f"17 Hz sur un écran 60 Hz est refusé ({raison})")

    print(f"[ssvep] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
