"""Moteur headless : casque Unicorn -> flux LSL. C'est le MVP de docs/SPEC.md §10.

Ce fichier est le **cœur du produit** : il tourne SANS interface graphique. L'application
pygame (`src/research/app.py`), le futur tableau de bord web et le code d'un étudiant sont tous, du
point de vue du moteur, des clients qui écoutent les mêmes flux.

Ce qu'il publie aujourd'hui (SPEC §4) :
    EEG_API_Unicorn_raw            les 8 voies, µV, 250 Hz
    EEG_API_Unicorn_quality        σ par voie, ~1 Hz (électrode décollée ?)
    EEG_API_Unicorn_status         état du moteur, JSON, à chaque changement + périodique
    EEG_API_Unicorn_decoded_ssvep  cible regardée, ~5 Hz (avec --mode ssvep)
    EEG_API_Unicorn_decoded_neuro  charge / somnolence / engagement, ~5 Hz (--mode neuro)

Les deux modes décodés illustrent les deux familles de la BCI, et un client ne doit pas les
traiter pareil : le SSVEP est **actif** (l'utilisateur choisit, il y a une bonne réponse, un
stimulus est requis côté client), le neuro est **passif** (on observe un état, il n'y a rien à
choisir et aucun stimulus). Un seul mode tourne à la fois — même casque, même boucle.

Pas encore : MI, c-VEP, P300, le control plane entrant, les marqueurs. Ils viendront poser
leurs publications sur le même squelette de boucle.

⚠️ Le moteur ne rend AUCUN stimulus. Pour le SSVEP, c'est l'application cliente qui fait
clignoter les cibles ; elle déclare simplement leurs fréquences au moteur (`--freqs`). Le
couplage est lâche — aucune synchronisation à la frame n'est nécessaire, contrairement au
c-VEP (SPEC §7).

Lancer :
    python src/core/server.py --synthetic              # sans casque (board de test BrainFlow)
    python src/core/server.py                           # vrai Unicorn, brut + qualité seulement
    python src/core/server.py --mode ssvep              # + décodage SSVEP (cibles par défaut)
    python src/core/server.py --mode ssvep --refresh 60 # cibles accordées à un écran 60 Hz
    python src/core/server.py --mode ssvep --freqs 15,20,8.57
    python src/core/server.py --duration 60             # s'arrête tout seul au bout de 60 s
    python src/core/server.py --smoke                   # test headless de bout en bout (CI)

Essai sur casque, en deux terminaux (le stimulus n'ouvre PAS le casque, aucun conflit) :
    python src/research/ssvep_stimulus.py --windowed --refresh 60   # les cibles clignotent
    python src/core/server.py --mode ssvep --refresh 60         # décode et trace en console
Un troisième terminal montre ce que reçoit un vrai client :
    python -u examples/receiver.py --stream decoded_ssvep
"""

import argparse
import math
import os
import queue
import signal
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.acquisition import UnicornAcquisition  # noqa: E402
from core.cca_decoder import CCADecoder  # noqa: E402
from core.config import (ARTIFACT_SIGMA_RATIO, BANDPASS, CH_NAMES,  # noqa: E402
                    NEURO_BASELINE_S, NEURO_REBASELINE_S, NEURO_SMOOTH, NEURO_UPDATE_HZ,
                    NEURO_WARMUP_S, NEURO_WINDOW_S, SSVEP_BASELINE_S, SSVEP_WARMUP_S,
                    WINDOW_S, choose_frequencies, reference_lost, use_utf8_console)
from core.lsl_io import (ClockBridge, DecodedNeuroPublisher,  # noqa: E402
                    DecodedSSVEPPublisher, QualityPublisher, RawPublisher, StatusPublisher,
                    default_instance_id, stream_name, verdict_from_sigma)
from core.neuro_monitor import NeuroDecoder  # noqa: E402

# Cadence de la boucle. On ne publie PAS échantillon par échantillon : on ramasse ~50 ms de
# signal d'un coup. Assez court pour rester très en dessous des fenêtres de décision d'un
# mode BCI (1-2 s), assez long pour ne pas réveiller le processus 250 fois par seconde.
POLL_S = 0.05
QUALITY_PERIOD_S = 1.0    # cadence du flux `quality`
STATUS_PERIOD_S = 2.0     # rappel périodique de l'état (pour un client qui arrive en retard)
QUALITY_WINDOW_S = 2.0    # longueur de signal sur laquelle on mesure le σ par voie
SSVEP_DECODE_HZ = 5.0     # cadence de décodage SSVEP (fenêtres glissantes de WINDOW_S)
SSVEP_BASELINE_SAMPLE_HZ = 5.0   # cadence d'échantillonnage du plancher de repos


def _json_float(value, digits=2):
    """Arrondi sûr pour un état destiné à JSON : rend None au lieu d'un NaN ou d'un infini.

    JSON n'a pas de NaN. Python l'écrit quand même (`NaN` nu, invalide), mais les
    sérialiseurs stricts — celui de Starlette, derrière le tableau de bord — lèvent une
    exception. Le prix d'une seule valeur indéfinie serait alors la perte de TOUT l'état :
    plus de qualité, plus de phase, plus de flux, une page vide et rien pour comprendre.
    """
    if value is None:
        return None
    value = float(value)
    return None if not math.isfinite(value) else round(value, digits)


class EngineServer:
    """Boucle acquisition -> publication. Un objet, une session casque, N flux.

    Le moteur tient **son propre tampon glissant** (`_recent`). C'est le point d'architecture
    central : `get_new_data()` VIDE le tampon de BrainFlow, donc les accesseurs à fenêtre
    glissante (`get_window`, `get_epoch`) ne peuvent plus servir. Diffuser et décoder en même
    temps n'est possible qu'en gardant l'historique ici, et en alimentant depuis lui à la fois
    la publication brute et les décodeurs.
    """

    def __init__(self, serial=None, synthetic=False, verbose=False, mode=None, freqs=None,
                 refresh=None, instance=None):
        self.synthetic = synthetic
        self.mode = mode
        self.acq = UnicornAcquisition(serial=serial, synthetic=synthetic, verbose=verbose)
        self.clock = ClockBridge()
        self.instance = instance or default_instance_id(serial, synthetic)
        self.raw_out = RawPublisher(ch_names=CH_NAMES, fs=self.acq.fs,
                                    instance=self.instance)
        self.quality_out = QualityPublisher(ch_names=CH_NAMES, instance=self.instance)
        self.status_out = StatusPublisher(instance=self.instance)
        self.samples = 0
        self._stop = False
        self._recent = np.zeros((0, len(CH_NAMES)))

        # Le tampon doit satisfaire le plus gourmand des consommateurs : la qualité veut
        # QUALITY_WINDOW_S, le SSVEP WINDOW_S, le neuro NEURO_WINDOW_S — chacun plus la marge
        # de filtre. On dimensionne sur TOUS les modes, pas sur celui qui tourne : changer de
        # mode en cours de séance ne doit pas dépendre de la taille d'un tampon.
        self.keep = max(int(QUALITY_WINDOW_S * self.acq.fs),
                        int(NEURO_WINDOW_S * self.acq.fs),
                        self.acq.window_n) + self.acq.margin_n

        self.decoder = None         # décodeur SSVEP (actif)
        self.ssvep_out = None
        self.freqs = []
        self.neuro = None           # décodeur neuro (passif) — les deux ne tournent jamais ensemble
        self.neuro_out = None
        self._neuro_samples = []
        self._neuro_state = None
        self._baseline_samples = []
        self._baseline_sigmas = []
        self._sigma_ref = None
        self._baseline_until = None
        self._baseline_s = SSVEP_BASELINE_S
        self._warmup_until = None
        self._baseline_done = False
        self._baseline_warned = False
        self._last_log = 0.0
        self._reference_lost = None
        self._commands = queue.Queue()
        self._warmup_s = SSVEP_WARMUP_S
        self._quality = None        # dernier σ par voie, pour l'afficheur
        self._decoded = None        # dernière décision, pour l'afficheur
        self._baseline_report = None
        if mode == "ssvep":
            self._setup_ssvep(freqs, refresh)
        elif mode == "neuro":
            self._setup_neuro()

    def _setup_neuro(self):
        """Prépare le neuro-monitoring passif : trois indices d'état, aucun stimulus.

        C'est le mode le moins exigeant côté client — rien à afficher, rien à synchroniser,
        aucun modèle à entraîner. Il ne demande qu'une chose, mais elle est impérative : un
        REPOS de `NEURO_BASELINE_S` en début de mode, parce que les indices sont des ratios
        spectraux individuels et dérivants, qui ne veulent rien dire sans un zéro personnel.

        La chauffe et le repos sont plus longs qu'en SSVEP (15 s + 25 s) : les échelles sont
        calées sur une MÉDIANE et une MAD, qui demandent plus de fenêtres qu'une moyenne.
        """
        self.neuro = NeuroDecoder(self.acq.fs)
        self.neuro_out = DecodedNeuroPublisher(instance=self.instance,
                                               smoothing=NEURO_SMOOTH,
                                               rebaseline_s=NEURO_REBASELINE_S)
        self._neuro_samples = []
        self._baseline_s, self._warmup_s = NEURO_BASELINE_S, NEURO_WARMUP_S

    def _setup_ssvep_durations(self):
        self._baseline_s, self._warmup_s = SSVEP_BASELINE_S, SSVEP_WARMUP_S

    def _setup_ssvep(self, freqs, refresh=None):
        """Prépare le décodage SSVEP. `freqs` = les fréquences que l'appli cliente affiche.

        Elles sont une ENTRÉE, pas une constante du moteur : c'est l'application externe qui
        rend le stimulus (SPEC §7) et qui déclare donc son jeu de fréquences.

        Trois façons de les fournir, de la plus explicite à la plus commode :
        `freqs` en clair ; `refresh` (le moteur applique alors `choose_frequencies`, la MÊME
        fonction que le stimulus — passer le même refresh des deux côtés garantit l'accord
        sans recopier des décimales) ; ou rien, et on retombe sur un écran 60 Hz.

        ⚠️ Une fréquence mal accordée ne produit aucune erreur, juste un décodage qui ne
        détecte jamais rien : la CCA corrèle contre une sinusoïde que personne n'affiche.

        Le flux décodé est créé TOUT DE SUITE, avant même la mesure du repos, et reste
        silencieux jusqu'à ce que le décodage commence. Le faire apparaître seulement à la
        fin du repos serait un piège : un client qui cherche le flux au lancement ne le
        trouve pas et abandonne (`resolve_byprop` a un délai fini) — c'est exactement ce qui
        s'est produit au premier essai casque. Un flux qui existe dès le départ et ne dit
        rien encore est bien plus facile à consommer ; c'est `status` qui explique pourquoi.
        """
        self._setup_ssvep_durations()
        if not freqs:
            freqs = [c["actual_hz"] for c in choose_frequencies(refresh or 60)]
        self.freqs = [float(f) for f in freqs]
        self.decoder = CCADecoder(self.freqs, fs=self.acq.fs)
        # L'échelle de décision fait partie du contrat et ne change donc jamais : le moteur
        # décide TOUJOURS sur z, quitte à prolonger le repos jusqu'à pouvoir le mesurer.
        self.ssvep_out = DecodedSSVEPPublisher(
            self.freqs, decision_scale="z",
            thresholds=(self.decoder.z_min, self.decoder.z_margin),
            instance=self.instance)

    def stop(self):
        self._stop = True

    @property
    def decoding(self):
        """Un mode décodé tourne-t-il ? (SSVEP actif ou neuro passif — jamais les deux.)"""
        return self.decoder is not None or self.neuro is not None

    @property
    def phase(self):
        """« baseline » pendant la mesure du repos, « decoding » ensuite, sinon « streaming »."""
        if not self.decoding:
            return "streaming"
        if self._baseline_done:
            return "decoding"
        if self._warmup_until is not None and time.perf_counter() < self._warmup_until:
            return "warmup"
        return "baseline"

    # --- API de commande interne (SPEC §12.1) --------------------------------
    # Le tableau de bord web et, plus tard, l'adaptateur de commandes LSL passent tous les
    # deux PAR ICI. Un seul chemin à tester, et le protocole de contrôle reste remplaçable
    # sans réécrire le moteur.
    #
    # Les commandes ne sont PAS appliquées par le thread qui les soumet : elles sont mises en
    # file et exécutées par la boucle du moteur. C'est ce qui garantit que la session
    # BrainFlow n'est touchée que depuis un seul thread — la partager entre le serveur web et
    # la boucle d'acquisition produirait des corruptions qu'aucun test ne rattraperait.

    def submit(self, command, **params):
        """Met une commande en file. Retourne un accusé, PAS le résultat (appliqué plus tard).

        Une exception à la règle « accusé seulement » : la VALIDITÉ des paramètres est
        vérifiée ici, tout de suite. Le refus d'une commande mal formée est une propriété du
        message, pas de l'état du moteur, et la renvoyer immédiatement évite à l'étudiant de
        chercher dans la console pourquoi son réglage n'a rien fait. Ce que `submit` ne
        promet toujours pas, c'est que la commande ait été APPLIQUÉE : ça s'observe sur
        `/api/state` ou sur le flux `status`.
        """
        if command not in ("set_mode", "set_freqs", "recalibrate", "stop"):
            return {"accepted": False, "reason": f"commande inconnue : {command}"}
        if command == "set_mode":
            mode = params.get("mode") or None
            if mode not in (None, "ssvep", "neuro"):
                return {"accepted": False,
                        "reason": f"mode inconnu : {mode} (attendu : ssvep, neuro, ou aucun)"}
        if command == "set_freqs":
            freqs, reason = self._validate_freqs(params.get("freqs"), params.get("refresh"))
            if freqs is None:
                return {"accepted": False, "reason": reason}
            params = {"freqs": freqs}
        self._commands.put((command, params))
        return {"accepted": True, "command": command}

    def _validate_freqs(self, freqs, refresh=None):
        """(liste de fréquences, None) si le jeu est exploitable, sinon (None, raison).

        Refuser tôt plutôt que décoder dans le vide : une fréquence hors bande passante ou
        deux cibles trop proches ne produisent AUCUNE erreur à l'exécution, seulement un
        décodage qui ne détecte jamais rien. C'est le mode de panne le plus coûteux du SSVEP
        parce qu'il ressemble à « l'utilisateur fixe mal ».
        """
        if self.mode != "ssvep":
            return None, "le moteur n'est pas en mode SSVEP — choisis d'abord « Décoder le SSVEP »"
        if not freqs and refresh:
            freqs = [c["actual_hz"] for c in choose_frequencies(float(refresh))]
        if not freqs:
            return None, "aucune fréquence fournie"
        try:
            freqs = [float(f) for f in freqs]
        except (TypeError, ValueError):
            return None, "fréquences illisibles (attendu : des nombres en Hz)"
        if len(freqs) < 2:
            return None, "il faut au moins 2 cibles"
        if len(freqs) > len(CH_NAMES):
            return None, f"trop de cibles (maximum {len(CH_NAMES)})"

        lo, hi = BANDPASS
        hors = [f for f in freqs if not (lo <= f <= hi)]
        if hors:
            return None, (f"hors bande passante {lo:g}-{hi:g} Hz : "
                          + ", ".join(f"{f:g}" for f in hors)
                          + " — le filtre d'acquisition les supprime avant le décodage")

        # Résolution fréquentielle d'une fenêtre de WINDOW_S : deux cibles plus proches que
        # 1/WINDOW_S ne sont pas séparables, quelle que soit la qualité du signal.
        ecart_min = 1.0 / WINDOW_S
        ordonne = sorted(freqs)
        trop_proches = [(a, b) for a, b in zip(ordonne, ordonne[1:]) if b - a < ecart_min]
        if trop_proches:
            return None, (f"cibles trop proches pour une fenêtre de {WINDOW_S:g} s "
                          f"(écart minimum {ecart_min:.2f} Hz) : "
                          + ", ".join(f"{a:g} et {b:g}" for a, b in trop_proches))
        return freqs, None

    def _drain_commands(self):
        while True:
            try:
                command, params = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                self._apply(command, params)
            except Exception as e:  # noqa: BLE001 - une commande fautive ne doit pas tuer le moteur
                print(f"[server] commande '{command}' rejetée : {e}")

    def _apply(self, command, params):
        if command == "stop":
            self.stop()
        elif command == "recalibrate":
            self._restart_baseline()
        elif command == "set_freqs":
            self._set_freqs(params["freqs"])
        elif command == "set_mode":
            mode = params.get("mode") or None
            if mode == self.mode and mode is not None:
                self._restart_baseline()
                return
            self.mode = mode
            self.decoder = None
            self.ssvep_out = None
            self.freqs = []
            self.neuro = None
            self.neuro_out = None
            self._neuro_state = None
            if mode == "ssvep":
                self._setup_ssvep(params.get("freqs"), params.get("refresh"))
                self._restart_baseline()
            elif mode == "neuro":
                self._setup_neuro()
                self._restart_baseline()
            print(f"[server] mode -> {self.mode or 'aucun (diffusion seule)'}")

    def _set_freqs(self, freqs):
        """Change les fréquences décodées en cours de séance (contrôle demandé par §12.2).

        Deux conséquences qu'on ne peut pas contourner, seulement assumer :

        1. **Le flux `decoded_ssvep` est RECRÉÉ.** Les fréquences ne sont pas qu'un réglage
           interne : elles nomment les voies du flux (`score_15Hz`) et figurent dans ses
           métadonnées. Or les métadonnées LSL sont figées à la création. Garder l'ancien
           flux reviendrait à publier des étiquettes fausses — un client afficherait « 15 Hz »
           pour une cible à 12. On préfère couper : **les clients connectés doivent se
           réabonner** (le NOM du flux, lui, ne change pas, donc un re-`resolve` suffit).
        2. **Le plancher de repos est refait.** Il est mesuré PAR FRÉQUENCE ; le réutiliser
           après changement comparerait les ρ d'une cible au bruit de fond d'une autre.
        """
        ancien = list(self.freqs)
        self.ssvep_out = None       # libère l'outlet avant d'en créer un autre
        self._setup_ssvep(freqs)
        self._restart_baseline()
        print(f"[server] fréquences {ancien} -> {self.freqs} Hz ; "
              "flux decoded_ssvep RECRÉÉ (les clients doivent se réabonner)")

    def _restart_baseline(self):
        """Refait chauffe + repos. Indispensable après avoir touché une électrode : un
        plancher mesuré pendant qu'un contact se stabilisait reste faux toute la séance."""
        self._baseline_samples, self._baseline_sigmas = [], []
        self._sigma_ref, self._baseline_until = None, None
        self._baseline_done = self._baseline_warned = False
        self._warmup_until = time.perf_counter() + self._warmup_s
        self._decoded = None
        if self.neuro is not None:
            # Un NeuroDecoder neuf : ses échelles (médiane/MAD des indices, σ et EMG de
            # référence) sont TOUTES issues du repos. En garder une partie mélangerait deux
            # états du casque, ce qui est précisément ce qu'un « refaire le repos » corrige.
            self.neuro = NeuroDecoder(self.acq.fs)
            self._neuro_samples = []
            self._neuro_state = None
        print(f"[server] repos relancé : stabilisation {self._warmup_s:.0f} s "
              f"puis {self._baseline_s:.0f} s sans rien fixer")

    def snapshot(self):
        """État complet pour un afficheur, en lecture seule. Sûr depuis un autre thread.

        On rend un dictionnaire déjà construit plutôt que des références vers l'état vivant :
        l'appelant ne peut donc pas lire une valeur à moitié écrite par la boucle.
        """
        state = self._state(not self._stop)
        state.update({
            "quality": self._quality,
            "decoded": self._decoded,
            "neuro": self._neuro_state,
            "baseline": self._baseline_report,
            "warmup_s": self._warmup_s,
            "baseline_s": self._baseline_s,
        })
        return state

    def _status_key(self, running):
        """Ce qui constitue un vrai CHANGEMENT d'état — hors compteurs (cf. StatusPublisher.push)."""
        return (running, self.synthetic, self.mode, self.phase)

    def _state(self, running):
        streams = ["raw", "quality", "status"]
        if self.decoder is not None:
            streams.append("decoded_ssvep")
        if self.neuro is not None:
            streams.append("decoded_neuro")
        state = {
            "running": running,
            "board": "synthetic" if self.synthetic else "unicorn",
            "instance": self.instance,
            "fs_hz": float(self.acq.fs),
            "channels": list(CH_NAMES),
            "mode": self.mode,
            "phase": self.phase,
            "samples_published": self.samples,
            "streams": [stream_name(s) for s in streams],
        }
        if self.decoder is not None:
            state["frequencies_hz"] = self.freqs
            # Ce que le client doit AFFICHER à l'utilisateur pendant le repos : sans cette
            # consigne, le plancher est mesuré pendant que l'étudiant fixe une cible, et
            # les seuils sortent faux pour toute la séance.
            state["instruction"] = ("Ne fixe AUCUNE cible : mesure du bruit de fond."
                                    if self.phase == "baseline" else "Fixe une cible.")
        if self.neuro is not None:
            state["indices"] = list(DecodedNeuroPublisher.KEYS)
            # Ici le repos ne sert pas à un seuil mais à un ZÉRO personnel : sans consigne, les
            # échelles se calent pendant que l'utilisateur travaille, et tout le reste de la
            # séance se lit contre un « repos » qui n'en était pas un.
            state["instruction"] = (
                "Repos : regarde l'écran, immobile et détendu — on cale TON zéro du jour."
                if self.phase == "baseline"
                else "Vaque à ton activité : les indices se lisent en écart à ton repos.")
        return state

    def _publish_quality(self, lsl_ts):
        """σ par voie sur les dernières secondes, calculé sur du signal FILTRÉ.

        Le filtrage est indispensable ICI (contrairement au flux brut) : sur du signal
        quasi-brut, le σ est dominé par le ronflement secteur 50 Hz et la dérive lente des
        électrodes sèches, pas par l'EEG — un σ mesuré ainsi ne dit rien de l'état du contact.

        Le calcul est délégué à `sigma_from_block` pour partager UNE seule définition du σ
        avec l'écran `signal_check` de l'appli : deux mesures de qualité qui divergeraient
        seraient pires que pas de mesure du tout.
        """
        sigmas = self.acq.sigma_from_block(self._recent)
        if sigmas is None:
            return
        self.quality_out.push(sigmas, lsl_ts)
        # Référence décrochée : invisible sur les σ, fatale pour la séance. On le dit
        # une fois par changement d'état plutôt qu'à chaque seconde.
        common = self.acq.common_mode(self._recent)
        # Sur le board de test il n'y a aucune électrode : un verdict sur la référence y serait
        # un contresens. On publie la mesure (honnête) mais jamais le verdict.
        lost = reference_lost(common) and not self.synthetic
        # `None` plutôt que NaN partout : l'état part en JSON, où NaN n'existe pas et fait
        # échouer la sérialisation entière (page blanche au lieu d'une valeur manquante).
        self._quality = {
            "sigmas": [_json_float(v) for v in sigmas],
            "verdicts": [verdict_from_sigma(float(v)) for v in sigmas],
            "common_mode": _json_float(common, digits=3),
            "reference_lost": bool(lost),
        }
        if lost != self._reference_lost and not self.synthetic:
            self._reference_lost = lost
            if lost:
                print(f"[server] ⚠️  RÉFÉRENCE DÉCROCHÉE (corrélation inter-voies "
                      f"{common:.2f}) — les 8 voies mesurent la même chose. Remets les "
                      f"MASTOÏDES et relance : tout ce qui suit est inexploitable.")
            else:
                print(f"[server] référence OK (corrélation inter-voies {common:.2f})")

    def _tick_ssvep(self, lsl_ts):
        """Un pas de décodage SSVEP : d'abord mesurer le repos, ensuite décider."""
        window = self.acq.occipital_window(self._recent)
        if window is None:
            return

        # Chauffe : on jette les premières secondes au lieu de les verser dans le plancher.
        if self._warmup_until is not None and time.perf_counter() < self._warmup_until:
            return

        if not self._baseline_done:
            self._collect_baseline(window)
            return

        # Rejet d'artefact : une fenêtre dont l'amplitude explose par rapport au repos ne
        # contient pas d'EEG (mouvement, clignement). En décoder des ρ produirait des
        # détections aléatoires ; on publie « aucune cible » plutôt que du bruit habillé.
        sd = float(window.std(axis=0).mean())
        if self._sigma_ref and sd > ARTIFACT_SIGMA_RATIO * self._sigma_ref:
            self.ssvep_out.push(-1, 0.0, 0.0, [0.0] * len(self.freqs), lsl_ts)
            self._remember_decision(-1, [0.0] * len(self.freqs), artifact=True)
            self._log_decision(-1, [0.0] * len(self.freqs), artifact=True)
            return

        freq, scores = self.decoder.classify(window)
        ordered = [scores[f] for f in self.freqs]
        if freq is None:
            self.ssvep_out.push(-1, 0.0, max(ordered), ordered, lsl_ts)
            self._remember_decision(-1, ordered)
            self._log_decision(-1, ordered)
        else:
            index = self.freqs.index(freq)
            self.ssvep_out.push(index, freq, scores[freq], ordered, lsl_ts)
            self._remember_decision(index, ordered)
            self._log_decision(index, ordered)

    def _tick_neuro(self, lsl_ts):
        """Un pas de neuro-monitoring : chauffe, puis repos, puis publication continue."""
        n = int(NEURO_WINDOW_S * self.acq.fs)
        if len(self._recent) < n:
            return
        # Fenêtre BRUTE : le passe-bande d'acquisition couperait le bas du θ. Le décodeur
        # applique lui-même son propre passe-haut avant la PSD.
        sample = self.neuro.sample(self._recent[-n:])
        if sample is None:
            return

        if self._warmup_until is not None and time.perf_counter() < self._warmup_until:
            return

        if not self._baseline_done:
            if self._baseline_until is None:
                self._baseline_until = time.perf_counter() + self._baseline_s
            self._neuro_samples.append(sample)
            if time.perf_counter() < self._baseline_until:
                return
            if not self.neuro.fit_baseline(self._neuro_samples):
                if not self._baseline_warned:
                    self._baseline_warned = True
                    print(f"[server] repos prolongé : {len(self._neuro_samples)} fenêtres, "
                          "pas encore de quoi caler les échelles")
                return
            centres = "  ".join(f"{k}: repos≈{self.neuro.norm.center(k):.3f}"
                                for k in self.neuro.norm.mu)
            print(f"[server] échelles calées ({len(self._neuro_samples)} fenêtres) — {centres}")
            print(f"[server] publication sur {stream_name('decoded_neuro')} "
                  "(z contre CE repos — ni comparable entre personnes, ni absolu)")
            self._baseline_report = {
                "kind": "neuro",
                "windows": len(self._neuro_samples),
                "targets": [{"index": k, "rest_center": _json_float(self.neuro.norm.center(k), 4)}
                            for k in self.neuro.norm.mu],
            }
            self._baseline_done = True
            return

        out = self.neuro.step(sample)
        self.neuro_out.push(out["z"], out["artifact"], lsl_ts)
        self._neuro_state = {
            "z": {k: _json_float(v) for k, v in out["z"].items()},
            "raw": {k: _json_float(v, 4) for k, v in (out["raw"] or {}).items()},
            "artifact": bool(out["artifact"]),
            "reason": out["reason"],
            "artifacts": self.neuro.artifacts,
        }
        now = time.perf_counter()
        if now - self._last_log >= 2.0:
            self._last_log = now
            print("[neuro] z " + "  ".join(f"{k}={v:+.2f}" for k, v in out["z"].items())
                  + f"  artefacts={self.neuro.artifacts}"
                  + (f"  ({out['reason']})" if out["artifact"] else ""))

    def _remember_decision(self, index, scores, artifact=False):
        self._decoded = {
            "target_index": int(index),
            "freq_hz": float(self.freqs[index]) if index >= 0 else 0.0,
            "scores": [round(float(v), 2) for v in scores],
            "artifact": bool(artifact),
            "threshold": float(self.decoder.z_min),
        }

    def _log_decision(self, index, scores, artifact=False):
        """Trace la décision en console ~1×/s.

        Le moteur est fait pour être consommé par un client, mais pendant une séance casque
        on veut voir ce qu'il décode SANS dépendre d'un troisième terminal branché au bon
        moment. Les scores sont affichés à côté de la décision : c'est ce qui permet de dire
        si une non-détection vient d'un signal absent ou d'un seuil trop haut.
        """
        now = time.perf_counter()
        if now - self._last_log < 1.0:
            return
        self._last_log = now
        detail = "  ".join(f"{f:g}Hz z={s:+5.2f}" for f, s in zip(self.freqs, scores))
        if artifact:
            verdict = "ARTEFACT (fenêtre rejetée)"
        elif index < 0:
            verdict = f"— (rien au-dessus de z={self.decoder.z_min})"
        else:
            verdict = f"CIBLE {index} ({self.freqs[index]:g} Hz)"
        print(f"[ssvep] {verdict:<34} {detail}")

    def _collect_baseline(self, window):
        """Accumule le plancher de ρ au repos, puis ajuste le décodeur.

        Pourquoi c'est nécessaire alors que le SSVEP est réputé « sans calibration » : chaque
        fréquence a un fond de corrélation DIFFÉRENT au repos, selon sa proximité au pic alpha
        du jour. Un seuil commun est donc structurellement injuste — mesuré sur ce casque, une
        cible proche de l'alpha n'émettait jamais alors que son ρ moyen dépassait le seuil.
        Ce n'est pas un modèle appris, juste un étalonnage de quelques secondes, à refaire à
        chaque séance. Le client DOIT afficher la consigne « ne fixe rien » (voir `_state`).
        """
        # Le décompte part de la PREMIÈRE fenêtre exploitable, pas du démarrage : il faut
        # d'abord WINDOW_S + la marge de filtre (2,5 s) pour que le tampon en produise une.
        # Compter depuis le lancement rognerait le repos d'autant — mesuré : 3 fenêtres
        # récoltées au lieu de 15, donc plancher rejeté faute d'effectif.
        if self._baseline_until is None:
            self._baseline_until = time.perf_counter() + self._baseline_s

        self._baseline_samples.append(self.decoder.scores(window))
        self._baseline_sigmas.append(float(window.std(axis=0).mean()))
        if time.perf_counter() < self._baseline_until:
            return

        if not self.decoder.fit_baseline(self._baseline_samples):
            # Pas encore assez de fenêtres pour un plancher fiable. On PROLONGE le repos au
            # lieu de basculer sur les ρ bruts : l'échelle de décision est annoncée dans les
            # métadonnées du flux, en changer en cours de route casserait le contrat. Les
            # fenêtres arrivent à 5 Hz, l'attente supplémentaire se compte en secondes.
            if not self._baseline_warned:
                self._baseline_warned = True
                print(f"[server] repos prolongé : {len(self._baseline_samples)} fenêtres, "
                      f"pas encore de quoi mesurer un plancher fiable")
            return

        self._sigma_ref = float(np.median(self._baseline_sigmas))
        line = "  ".join(f"{f:g}Hz: μ={m:.2f} σ={s:.2f}"
                         for f, (m, s) in self.decoder.baseline.items())
        print(f"[server] plancher de repos ({len(self._baseline_samples)} fenêtres) — {line}")

        # Un plancher trop DISPERSÉ rend le seuil inatteignable, en silence : on décide sur
        # z=(ρ-μ)/σ, donc un σ gonflé exige un ρ que le SSVEP ne produit jamais en électrodes
        # sèches. Vécu sur casque le 2026-07-27 : σ=0,19 => il aurait fallu ρ≈0,94. Mieux vaut
        # le dire tout de suite que laisser l'utilisateur fixer une cible qui ne peut pas sortir.
        for f, (mu, sd) in self.decoder.baseline.items():
            needed = mu + self.decoder.z_min * sd
            if needed > 0.85:
                print(f"[server] ⚠️  {f:g} Hz : plancher trop dispersé (μ={mu:.2f} σ={sd:.2f}) "
                      f"-> il faudrait ρ={needed:.2f} pour détecter. Cible quasi INDÉTECTABLE : "
                      f"contact des électrodes occipitales, ou refaire le repos immobile.")
        print(f"[server] σ de référence {self._sigma_ref:.1f} -> rejet d'artefact au-delà "
              f"de {ARTIFACT_SIGMA_RATIO * self._sigma_ref:.0f}")
        print(f"[server] décodage en cours sur {stream_name('decoded_ssvep')} "
              f"(échelle z, seuil {self.decoder.z_min}) — fixe une cible")
        self._baseline_report = {
            "kind": "ssvep",
            "windows": len(self._baseline_samples),
            "targets": [{"freq_hz": float(f), "mu": round(mu, 3), "sigma": round(sd, 3),
                         "rho_needed": round(mu + self.decoder.z_min * sd, 2)}
                        for f, (mu, sd) in self.decoder.baseline.items()],
        }
        self._baseline_done = True

    def run(self, duration_s=None, baseline_s=None, warmup_s=None):
        """Boucle principale. `duration_s=None` = jusqu'à Ctrl+C.

        `baseline_s` / `warmup_s` à None = les durées PROPRES AU MODE, posées par son
        `_setup_*` (SSVEP 8 s + 15 s ; neuro 25 s + 15 s — plus long parce que ses échelles
        reposent sur une médiane et une MAD, qui demandent plus de fenêtres qu'une moyenne).
        Les passer explicitement les remplace, pour les deux modes.
        """
        if baseline_s is not None:
            self._baseline_s = baseline_s
        if warmup_s is not None:
            self._warmup_s = warmup_s
        # Le moteur écrit des µ, des σ et des accents. Sous PowerShell, stdout est en cp1252
        # par défaut : un simple print tuait alors le thread d'acquisition sur un
        # UnicodeEncodeError. On le fait ici plutôt que dans le seul `__main__`, parce que
        # le moteur est aussi utilisé comme bibliothèque (tableau de bord, tests) — et
        # qu'un échec d'AFFICHAGE ne doit jamais interrompre une ACQUISITION.
        use_utf8_console()

        started = time.perf_counter()
        last_quality = last_status = last_decode = 0.0

        with self.acq:
            print(f"[server] board={self.acq.board_id.name} fs={self.acq.fs} Hz instance={self.instance}")
            for suffix in ("raw", "quality", "status"):
                print(f"[server] flux LSL publie : {stream_name(suffix)}")
            if self.decoder is not None:
                print(f"[server] flux LSL publie : {stream_name('decoded_ssvep')} "
                      f"(silencieux pendant le repos)")
                print(f"[server] mode {self.mode} — cibles "
                      + ", ".join(f"{f:g} Hz" for f in self.freqs))
                print(f"[server] stabilisation {self._warmup_s:.0f} s, puis REPOS "
                      f"{self._baseline_s:.0f} s : ne fixe AUCUNE cible (mesure du bruit de fond)")
                self._warmup_until = time.perf_counter() + self._warmup_s
            elif self.neuro is not None:
                print(f"[server] flux LSL publie : {stream_name('decoded_neuro')} "
                      f"(silencieux pendant le repos)")
                print(f"[server] mode {self.mode} — indices "
                      + ", ".join(DecodedNeuroPublisher.KEYS) + " (PASSIF : aucune commande)")
                print(f"[server] stabilisation {self._warmup_s:.0f} s, puis REPOS "
                      f"{self._baseline_s:.0f} s : immobile et détendu, on cale TON zéro du jour")
                self._warmup_until = time.perf_counter() + self._warmup_s
            self.status_out.push(self._state(True), key=self._status_key(True), force=True)

            while not self._stop:
                self._drain_commands()
                now = time.perf_counter()
                if duration_s is not None and now - started >= duration_s:
                    break

                eeg, ts_unix = self.acq.get_new_data()
                if eeg is not None and len(eeg):
                    self.samples += self.raw_out.push(eeg, self.clock.to_lsl(ts_unix))
                    self._recent = np.vstack([self._recent, eeg])[-self.keep:]

                if now - last_quality >= QUALITY_PERIOD_S:
                    self._publish_quality(self.clock.to_lsl(time.time()))
                    last_quality = now

                if self.decoder is not None:
                    period = 1.0 / (SSVEP_BASELINE_SAMPLE_HZ if not self._baseline_done
                                    else SSVEP_DECODE_HZ)
                    if now - last_decode >= period:
                        self._tick_ssvep(self.clock.to_lsl(time.time()))
                        last_decode = now
                elif self.neuro is not None:
                    if now - last_decode >= 1.0 / NEURO_UPDATE_HZ:
                        self._tick_neuro(self.clock.to_lsl(time.time()))
                        last_decode = now

                # Publié quand l'état change, plus un rappel périodique pour les clients qui
                # se connectent après le démarrage (LSL ne rejoue pas le passé).
                due = now - last_status >= STATUS_PERIOD_S
                if self.status_out.push(self._state(True), key=self._status_key(True),
                                        force=due) and due:
                    last_status = now

                time.sleep(POLL_S)

            self.status_out.push(self._state(False), key=self._status_key(False), force=True)

        elapsed = time.perf_counter() - started
        print(f"[server] arrêt : {self.samples} échantillons publiés en {elapsed:.1f} s "
              f"({self.samples / max(elapsed, 1e-9):.1f} Hz effectif)")
        return self.samples


def _resolve_own(suffix, instance, timeout=10.0):
    """Résout un flux en exigeant l'instance qui l'a publié.

    Chercher par NOM seul ne suffit pas : les noms sont un contrat public, donc identiques
    pour tous les moteurs. Un serveur laissé ouvert sur le poste — ou le casque d'un voisin
    en salle — répond alors à la place du nôtre, et le test mesure quelqu'un d'autre
    (vécu deux fois le 2026-07-27 : cadence lue à 401 Hz au lieu de 250, échantillons reçus
    en surnombre). On filtre donc sur le `source_id`, qui porte l'instance.
    """
    from pylsl import resolve_byprop
    # Deux précautions, chacune pour un piège distinct :
    # `minimum` élevé — sinon resolve_byprop rend la main dès le PREMIER flux trouvé et peut
    #   donc ne jamais voir le nôtre si un autre moteur répond en premier ;
    # passes COURTES répétées — parce que ce `minimum` fait justement consommer tout le délai
    #   à chaque appel, et trois résolutions de 10 s dépasseraient la durée du test.
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        for info in resolve_byprop("name", stream_name(suffix), minimum=32, timeout=0.5):
            if info.source_id().endswith(f"@{instance}"):
                return info
    return None


def _smoke():
    """Test de bout en bout sans casque : le serveur publie, un client local reçoit.

    Vérifie ce qui casserait silencieusement : la continuité du flux (pas de trou), la
    cadence réelle vs les 250 Hz annoncés, et la présence du flux qualité.
    """
    import threading

    from pylsl import StreamInlet, resolve_byprop

    instance = "smoke"
    server = EngineServer(synthetic=True, instance=instance)

    # Garde-fou : `_filter` ne doit JAMAIS modifier son entrée. Le serveur lui passe un
    # tampon persistant ; s'il était filtré sur place, les échantillons bruts suivants
    # seraient collés sur une queue déjà filtrée et le σ deviendrait absurde (vécu le
    # 2026-07-27 : 40 000 µV mesurés sur un EEG à 5 µV). Un tableau contigu float64 est
    # exactement le cas qui déclenchait le bug.
    probe = np.full((300, len(CH_NAMES)), 150000.0, dtype=np.float64)
    untouched = probe.copy()
    server.acq._filter(probe)
    if not np.array_equal(probe, untouched):
        print("[smoke] ÉCHEC : _filter modifie son entrée (voir acquisition._filter)")
        return False
    thread = threading.Thread(target=server.run, kwargs={"duration_s": 6.0}, daemon=True)
    thread.start()

    raw = _resolve_own("raw", instance)
    qual = _resolve_own("quality", instance, 5.0)
    stat = _resolve_own("status", instance, 5.0)
    if not raw or not qual or not stat:
        print("[smoke] ÉCHEC : flux introuvables")
        server.stop()
        return False

    raw_in, qual_in = StreamInlet(raw, max_buflen=30), StreamInlet(qual, max_buflen=30)
    stat_in = StreamInlet(stat, max_buflen=30)
    raw_in.open_stream(timeout=5.0)   # sinon on rate tout ce qui précède le 1er pull
    qual_in.open_stream(timeout=5.0)
    stat_in.open_stream(timeout=5.0)

    got, stamps, quality_rows, status_rows = 0, [], 0, 0
    watch_started = time.perf_counter()
    deadline = watch_started + 7.0
    while time.perf_counter() < deadline and thread.is_alive():
        chunk, ts = raw_in.pull_chunk(timeout=0.2, max_samples=512)
        got += len(chunk)
        stamps.extend(ts)
        qchunk, _ = qual_in.pull_chunk(timeout=0.0, max_samples=16)
        quality_rows += len(qchunk)
        schunk, _ = stat_in.pull_chunk(timeout=0.0, max_samples=256)
        status_rows += len(schunk)
    watched_s = time.perf_counter() - watch_started
    thread.join(timeout=5.0)

    ok = True
    print(f"[smoke] reçu {got} échantillons, {quality_rows} mesures de qualité, "
          f"{status_rows} messages d'état")
    # L'état est *événementiel* : il doit se taire tant que rien ne change. Un compteur
    # glissé dans la charge utile avait suffi à le faire émettre à 19,6 Hz au lieu de 0,5 Hz
    # (dédup défaite) — assez discret pour passer inaperçu, assez bruyant pour noyer un
    # client. On garde donc une borne dure ici.
    status_hz = status_rows / max(watched_s, 1e-9)
    if status_hz > 3.0:
        print(f"[smoke] ÉCHEC : le flux d'état émet à {status_hz:.1f} Hz (déduplication cassée ?)")
        ok = False
    if got < 500:
        print("[smoke] ÉCHEC : trop peu d'échantillons reçus")
        ok = False
    if quality_rows < 2:
        print("[smoke] ÉCHEC : le flux qualité ne publie pas")
        ok = False
    if len(stamps) > 2:
        gaps = np.diff(np.asarray(stamps))
        rate = 1.0 / np.median(gaps)
        print(f"[smoke] cadence mesurée {rate:.1f} Hz, plus grand trou {gaps.max() * 1000:.1f} ms")
        # Le board synthétique tourne à 250 Hz nominal comme l'Unicorn ; un écart franc
        # signalerait un timestamp mal converti, pas un problème de débit.
        if not 200.0 < rate < 300.0:
            print("[smoke] ÉCHEC : cadence incohérente avec les 250 Hz annoncés")
            ok = False

    print(f"[smoke] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok and _smoke_ssvep() and _smoke_neuro()


def _smoke_neuro():
    """Le mode neuro câblé de bout en bout, sur board synthétique.

    Comme pour le SSVEP, on ne juge PAS le contenu : des sinusoïdes fabriquées n'ont ni charge
    mentale ni somnolence. On vérifie le CÂBLAGE et le CONTRAT — le flux existe dès le
    démarrage, il se tait pendant le repos, puis publie 4 voies dans le bon ordre, avec un
    drapeau d'artefact binaire et des z finis (un NaN passerait inaperçu jusque chez le client).
    """
    import threading

    from pylsl import StreamInlet

    instance = "smoke-neuro"
    server = EngineServer(synthetic=True, mode="neuro", instance=instance)
    thread = threading.Thread(
        target=server.run,
        kwargs={"duration_s": 14.0, "baseline_s": 3.0, "warmup_s": 1.0}, daemon=True)
    thread.start()

    found = _resolve_own("decoded_neuro", instance, 5.0)
    if not found:
        print("[smoke-neuro] ÉCHEC : le flux décodé n'existe pas dès le démarrage")
        server.stop()
        return False
    inlet = StreamInlet(found)
    inlet.open_stream(timeout=5.0)
    n_ch = inlet.info().channel_count()
    labels, ch = [], inlet.info().desc().child("channels").child("channel")
    while not ch.empty():
        labels.append(ch.child_value("label"))
        ch = ch.next_sibling()
    scale = inlet.info().desc().child("decoding").child_value("decision_scale")
    print(f"[smoke-neuro] flux décodé : {n_ch} voies {labels}, échelle « {scale} »")

    t0 = time.perf_counter()
    while server.phase != "decoding" and time.perf_counter() - t0 < 12.0 and thread.is_alive():
        inlet.pull_chunk(timeout=0.1, max_samples=64)
    if server.phase != "decoding":
        print(f"[smoke-neuro] ÉCHEC : toujours en phase « {server.phase} » après 12 s")
        server.stop()
        return False

    rows, t0 = [], time.perf_counter()
    while time.perf_counter() - t0 < 3.0 and thread.is_alive():
        chunk, _ts = inlet.pull_chunk(timeout=0.2, max_samples=64)
        rows.extend(chunk)
    server.stop()
    thread.join(timeout=5.0)

    ok = True
    expected = list(DecodedNeuroPublisher.KEYS) + ["artifact"]
    if labels != expected:
        print(f"[smoke-neuro] ÉCHEC : voies {labels} au lieu de {expected}")
        ok = False
    if len(rows) < 5:
        print(f"[smoke-neuro] ÉCHEC : {len(rows)} publications reçues, trop peu")
        ok = False
    for r in rows:
        if not all(math.isfinite(v) for v in r):
            print(f"[smoke-neuro] ÉCHEC : valeur non finie publiée ({r})")
            ok = False
            break
        if r[3] not in (0.0, 1.0):
            print(f"[smoke-neuro] ÉCHEC : drapeau artifact non binaire ({r[3]})")
            ok = False
            break
    if rows:
        arts = sum(1 for r in rows if r[3] == 1.0)
        print(f"[smoke-neuro] {len(rows)} publications, dont {arts} marquées artefact "
              f"(contenu sans valeur sur board synthétique — on teste le câblage)")
    print(f"[smoke-neuro] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_ssvep():
    """Le mode SSVEP câblé de bout en bout, sur board synthétique.

    On ne vérifie PAS la justesse du décodage : le board synthétique n'émet aucun vrai SSVEP,
    donc la cible « détectée » n'a aucun sens. On vérifie le CÂBLAGE — que la baseline se
    termine, que le flux décodé apparaît, qu'il publie au bon rythme et que ses valeurs
    respectent le contrat annoncé (index dans les bornes, scores en nombre attendu).
    """
    import threading

    from pylsl import StreamInlet, resolve_byprop

    freqs = [15.0, 20.0, 8.57]
    instance = "smoke-ssvep"
    server = EngineServer(synthetic=True, mode="ssvep", freqs=freqs, instance=instance)
    thread = threading.Thread(
        target=server.run,
        kwargs={"duration_s": 14.0, "baseline_s": 3.0, "warmup_s": 1.0}, daemon=True)
    thread.start()

    # Le flux doit exister DÈS le démarrage, avant même la fin du repos : c'est ce qui
    # permet à un client de le trouver au lancement (cf. _setup_ssvep). Un délai court
    # vérifie donc une vraie propriété du contrat, pas seulement la présence du flux.
    found = _resolve_own("decoded_ssvep", instance, 5.0)
    if not found:
        print("[smoke-ssvep] ÉCHEC : le flux décodé n'existe pas dès le démarrage")
        server.stop()
        return False
    inlet = StreamInlet(found)
    inlet.open_stream(timeout=5.0)
    n_ch = inlet.info().channel_count()
    scale = inlet.info().desc().child("decoding").child_value("decision_scale")
    print(f"[smoke-ssvep] flux décodé : {n_ch} voies, échelle « {scale} »")

    # Le flux existe dès le départ mais reste muet pendant la chauffe et le repos : on
    # attend que le moteur annonce lui-même être passé en décodage avant de compter.
    t0 = time.perf_counter()
    while server.phase != "decoding" and time.perf_counter() - t0 < 12.0 and thread.is_alive():
        inlet.pull_chunk(timeout=0.1, max_samples=64)
    if server.phase != "decoding":
        print(f"[smoke-ssvep] ÉCHEC : toujours en phase « {server.phase} » après 12 s")
        server.stop()
        return False

    rows, t0 = [], time.perf_counter()
    while time.perf_counter() - t0 < 3.0 and thread.is_alive():
        chunk, _ts = inlet.pull_chunk(timeout=0.2, max_samples=64)
        rows.extend(chunk)
    server.stop()
    thread.join(timeout=5.0)

    ok = True
    if n_ch != 3 + len(freqs):
        print(f"[smoke-ssvep] ÉCHEC : {n_ch} voies au lieu de {3 + len(freqs)}")
        ok = False
    if len(rows) < 5:
        print(f"[smoke-ssvep] ÉCHEC : {len(rows)} décisions reçues, trop peu")
        ok = False
    for r in rows:
        if not (-1 <= int(r[0]) < len(freqs)):
            print(f"[smoke-ssvep] ÉCHEC : target_index hors bornes ({r[0]})")
            ok = False
            break
    if rows:
        detected = sum(1 for r in rows if int(r[0]) >= 0)
        print(f"[smoke-ssvep] {len(rows)} décisions, dont {detected} avec une cible "
              f"(sans valeur sur bruit synthétique — on teste le câblage)")
    print(f"[smoke-ssvep] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _parse_args(argv):
    p = argparse.ArgumentParser(description="EEG_API_Unicorn — moteur headless, sorties LSL.")
    p.add_argument("--synthetic", action="store_true", help="board de test BrainFlow (sans casque)")
    p.add_argument("--serial", default=None, help="numéro de série Unicorn (si plusieurs appairés)")
    p.add_argument("--duration", type=float, default=None, help="durée en s (défaut : jusqu'à Ctrl+C)")
    p.add_argument("--mode", choices=["ssvep", "neuro"], default=None,
                   help="décodeur à publier en plus du brut (défaut : aucun). ssvep = cible "
                        "regardée (actif, demande un stimulus côté client) ; neuro = charge / "
                        "somnolence / engagement (passif, aucun stimulus)")
    p.add_argument("--freqs", default=None,
                   help="fréquences des cibles affichées par l'appli cliente, ex. 15,20,8.57")
    p.add_argument("--refresh", type=float, default=None,
                   help="refresh de l'écran qui affiche le stimulus : le moteur en déduit les "
                        "mêmes fréquences que src/research/ssvep_stimulus.py lancé avec ce refresh")
    p.add_argument("--baseline", type=float, default=None,
                   help=f"durée du repos initial en s (défaut : {SSVEP_BASELINE_S:g} en ssvep, "
                        f"{NEURO_BASELINE_S:g} en neuro)")
    p.add_argument("--warmup", type=float, default=None,
                   help=f"stabilisation jetée avant le repos, dérive DC des électrodes sèches "
                        f"(défaut : {SSVEP_WARMUP_S:g} s)")
    p.add_argument("--id", dest="instance", default=None,
                   help="identité de cette instance (défaut : n° de série du casque). Distingue "
                        "les moteurs quand plusieurs tournent sur le même réseau — une salle de TP")
    p.add_argument("--smoke", action="store_true", help="test headless de bout en bout, puis quitte")
    p.add_argument("--verbose", action="store_true", help="logs BrainFlow détaillés")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    if args.smoke:
        sys.exit(0 if _smoke() else 1)

    freqs = [float(f) for f in args.freqs.split(",")] if args.freqs else None
    engine = EngineServer(serial=args.serial, synthetic=args.synthetic, verbose=args.verbose,
                          mode=args.mode, freqs=freqs, refresh=args.refresh,
                          instance=args.instance)
    # Ctrl+C doit fermer PROPREMENT la session BrainFlow : une session laissée ouverte
    # empêche la suivante de s'ouvrir (BOARD_NOT_READY au relancement).
    signal.signal(signal.SIGINT, lambda *_: engine.stop())
    print("[server] Ctrl+C pour arrêter.")
    engine.run(duration_s=args.duration, baseline_s=args.baseline, warmup_s=args.warmup)
