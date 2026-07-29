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
                         ALPHA_DEFAUT_HZ, use_utf8_console, choose_frequencies)
import numpy as np  # noqa: E402

from core.cca_decoder import CCADecoder  # noqa: E402
from core.lsl_io import DecodedSSVEPPublisher, ssvep_channel_labels, stream_name  # noqa: E402
from core.modes.contract import ModeSpec, Param, Rest, validate  # noqa: E402
from core.modes.runtime import ModeRuntime  # noqa: E402

# Le défaut vient de `choose_frequencies`, la MÊME fonction que le stimulus : passer le même
# refresh des deux côtés garantit l'accord sans recopier des décimales à la main.
FREQS_60HZ = tuple(c["actual_hz"] for c in choose_frequencies(60))   # 15 · 20 · 8,571 Hz

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

    def _new_decoder(self):
        self.decoder = CCADecoder(list(self.params["freqs"]), fs=self.engine.acq.fs)

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
        window = engine.acq.occipital_window(engine.recent)
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
                print(f"[ssvep] repos prolongé : {len(self._samples)} fenêtres, "
                      f"pas encore de quoi mesurer un plancher fiable")
            return False

        self._sigma_ref = float(np.median(self._sigmas))
        line = "  ".join(f"{f:g}Hz: μ={m:.2f} σ={s:.2f}"
                         for f, (m, s) in self.decoder.baseline.items())
        print(f"[ssvep] plancher de repos ({len(self._samples)} fenêtres) — {line}")

        # Un plancher trop DISPERSÉ rend le seuil inatteignable, en silence : on décide sur
        # z=(ρ-μ)/σ, donc un σ gonflé exige un ρ que le SSVEP ne produit jamais en électrodes
        # sèches. Vécu sur casque le 2026-07-27 : σ=0,19 => il aurait fallu ρ≈0,94. Mieux vaut le dire tout de
        # suite que laisser l'utilisateur fixer une cible qui ne peut pas sortir.
        for f, (mu, sd) in self.decoder.baseline.items():
            needed = mu + self.decoder.z_min * sd
            if needed > 0.85:
                print(f"[ssvep] ⚠️  {f:g} Hz : plancher trop dispersé (μ={mu:.2f} σ={sd:.2f}) "
                      f"-> il faudrait ρ={needed:.2f} pour détecter. Cible quasi INDÉTECTABLE : "
                      f"contact des électrodes occipitales, ou refaire le repos immobile.")
        print(f"[ssvep] σ de référence {self._sigma_ref:.1f} -> rejet d'artefact au-delà "
              f"de {ARTIFACT_SIGMA_RATIO * self._sigma_ref:.0f}")
        print(f"[ssvep] décodage en cours sur {stream_name('decoded_ssvep')} "
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
        window = engine.acq.occipital_window(engine.recent)
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
    label="SSVEP",
    family="actif",
    summary="Quelle cible clignotante l'utilisateur regarde, ~5 fois par seconde.",
    status="moteur",
    params=(
        Param(
            key="freqs",
            label="Fréquences des cibles",
            kind="float_list",
            unit="Hz",
            default=FREQS_60HZ,
            count=(2, 8),
            constraints=("dans_la_bande", "separables", "divise_le_refresh"),
            help="Les fréquences que TON application fait clignoter. Le nombre de cibles est la "
                 "longueur de cette liste. Une fréquence n'est stable que si c'est un diviseur "
                 "entier du refresh de ton écran (à 60 Hz : 30, 20, 15, 12, 10, 8,571…). Évite le "
                 "voisinage de ton pic alpha : réglage « alpha_hz » ci-dessous — le fond de "
                 "corrélation y est élevé au repos. Changer cette liste RECRÉE le flux — les "
                 "clients doivent se réabonner.",
        ),
        Param(
            key="refresh_hz",
            label="Rafraîchissement de l'écran du stimulus",
            kind="float",
            unit="Hz",
            default=60.0,
            min=20.0, max=480.0,
            proposes="freqs",
            affecte_decodage=False,
            help="Le rafraîchissement de l'écran qui AFFICHE les cibles — pas celui de cette "
                 "fenêtre : ton jeu tourne peut-être sur un autre écran, ou une autre machine. "
                 "Les fréquences affichables sans saut de cycle en sont les diviseurs entiers. "
                 "Le changer PROPOSE un nouveau jeu de fréquences ; il ne relance pas le repos, "
                 "parce que le décodeur ne le lit jamais.",
        ),
        Param(
            key="alpha_hz",
            label="Pic alpha de la personne",
            kind="float",
            unit="Hz",
            default=ALPHA_DEFAUT_HZ,
            min=6.0, max=14.0,
            proposes="freqs",
            affecte_decodage=False,
            help="Le pic alpha varie FORTEMENT d'une personne à l'autre (moyenne ~9,6 Hz, plage "
                 "6-14 Hz) et il est stable chez chacun. Une cible posée dessus ne se distingue "
                 "pas du fond au repos. La proposition s'en écarte. Pour mesurer le tien : "
                 "`python src/research/alpha_check.py`. Ne relance pas le repos.",
        ),
    ),
    rest=Rest(
        warmup_s=SSVEP_WARMUP_S,
        duration_s=SSVEP_BASELINE_S,
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
