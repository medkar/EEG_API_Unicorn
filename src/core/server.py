"""Moteur headless : casque Unicorn -> flux LSL. C'est le MVP de docs/SPEC.md §10.

Ce fichier est le **cœur du produit** : il tourne SANS interface graphique. L'application
pygame (`src/research/app.py`), la future console PySide6 et le code d'un étudiant sont tous, du
point de vue du moteur, des clients qui écoutent les mêmes flux.

Le moteur ne garde que le **vraiment commun** : la session BrainFlow, le tampon glissant, le pont
d'horloge, la qualité du signal, la file de commandes. Tout le reste — la séquence chauffe /
repos / décodage, ce qui se règle, ce qui se publie — vit dans `src/core/modes/` : un
`ModeRuntime` par mode actif, tenu dans `self.active`. Plusieurs modes tournent EN MÊME TEMPS,
chacun à sa propre phase ; lancés ENSEMBLE ils partagent une seule mesure de repos
(`_begin_shared_rest`), lancés séparément chacun fait la sienne.

Ce qu'il publie aujourd'hui (SPEC §4) :
    EEG_API_Unicorn_raw            les 8 voies, µV, 250 Hz (mode "raw", actif par défaut)
    EEG_API_Unicorn_quality        σ par voie, ~1 Hz (électrode décollée ?) — toujours publié
    EEG_API_Unicorn_status         état du moteur, JSON, à chaque changement + périodique — idem
    EEG_API_Unicorn_decoded_ssvep  cible regardée, ~5 Hz (mode "ssvep")
    EEG_API_Unicorn_decoded_neuro  charge / somnolence / engagement, ~5 Hz (mode "neuro")
    EEG_API_Unicorn_decoded_mi     intention gauche/droite/repos, ~5 Hz (mode "mi")
    EEG_API_Unicorn_decoded_p300   cible sélectionnée, UN échantillon par manche (mode "p300")

Et ce qu'il ÉCOUTE (SPEC §4, docs/markers.md) :
    EEG_API_Unicorn_stim           marqueurs entrants d'une application externe (mode "p300")

SSVEP et neuro illustrent les deux familles de la BCI, et un client ne doit pas les traiter
pareil : le SSVEP est **actif** (l'utilisateur choisit, il y a une bonne réponse, un stimulus est
requis côté client), le neuro est **passif** (on observe un état, il n'y a rien à choisir et
aucun stimulus). Le MI est actif lui aussi, mais SANS stimulus (il est endogène) — en échange, il
exige un modèle ENTRAÎNÉ propre à la personne, là où le SSVEP décode sans calibration : sans
modèle, le mode refuse de démarrer plutôt que de publier des probabilités qui ne veulent rien dire.
Le P300 est actif ET évoqué : il exige un modèle entraîné (comme le MI) **et** que l'application
cliente dise au moteur QUAND chaque cible s'est allumée — c'est à ça que sert le flux entrant.

Pas encore dans le moteur : c-VEP et ErrP — voir `src/core/modes/registry.py` pour le catalogue
complet ; ils restent l'affaire de `src/research/app.py`. Pas encore non plus : le control plane
entrant (démarrer un mode depuis le réseau). Les MARQUEURS entrants, eux, existent depuis le
2026-08-17 : le moteur ouvre un inlet LSL dès qu'un mode qui en consomme démarre (`core/markers.py`),
et le contrat public de ces marqueurs est dans `docs/markers.md`.

⚠️ Le moteur ne rend AUCUN stimulus. Pour le SSVEP, c'est l'application cliente qui fait
clignoter les cibles ; elle déclare simplement leurs fréquences au moteur (`--freqs`). Le
couplage est lâche — aucune synchronisation à la frame n'est nécessaire, contrairement au
c-VEP (SPEC §7).

Lancer :
    python src/core/server.py --synthetic              # sans casque (board de test BrainFlow)
    python src/core/server.py                           # vrai Unicorn, brut + qualité seulement
    python src/core/server.py --mode ssvep              # + décodage SSVEP (cibles par défaut)
    python src/core/server.py --mode ssvep --refresh 60 # cibles accordées à un écran 60 Hz
    python src/core/server.py --mode ssvep --freqs 15,20,8.571
    python src/core/server.py --mode ssvep,neuro        # plusieurs modes EN MÊME TEMPS
    python src/core/server.py --mode p300               # écoute les marqueurs d'une appli externe
    python src/core/server.py --mode neuro --no-raw     # sans le flux brut
    python src/core/server.py --duration 60             # s'arrête tout seul au bout de 60 s
    python src/core/server.py --smoke                   # test headless de bout en bout (CI)

Essai sur casque, en deux terminaux (le stimulus n'ouvre PAS le casque, aucun conflit) :
    python src/research/ssvep_stimulus.py --windowed --refresh 60   # les cibles clignotent
    python src/core/server.py --mode ssvep --refresh 60         # décode et trace en console
Un troisième terminal montre ce que reçoit un vrai client :
    python -u examples/receiver.py --stream decoded_ssvep

Même montage pour le P300, à ceci près que le stimulus PARLE au moteur (il publie l'onset de
chaque flash sur `EEG_API_Unicorn_stim`) et qu'un modèle entraîné est exigé :
    python src/research/p300_stimulus.py --windowed  # affiche et MARQUE (n'ouvre pas le casque)
    python src/core/server.py --mode p300            # découpe sur les marqueurs et décide
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
from core.config import (ALPHA_DEFAUT_HZ, CH_NAMES, MARKER_LATE_S, MARKER_STREAM_DEFAULT,  # noqa: E402
                    MI_WINDOW_S, NEURO_WINDOW_S, TOLERANCE_DIVISEUR, choose_frequencies,
                    json_float, propose_frequencies, reference_lost, use_utf8_console)
from core.lsl_io import (ClockBridge, DecodedNeuroPublisher, QualityPublisher,  # noqa: E402
                    StatusPublisher, default_instance_id, mi_channel_labels, stream_name,
                    verdict_from_sigma)
from core.markers import MarkerInlet  # noqa: E402
from core.modes import contract, registry  # noqa: E402

# Cadence de la boucle. On ne publie PAS échantillon par échantillon : on ramasse ~50 ms de
# signal d'un coup. Assez court pour rester très en dessous des fenêtres de décision d'un
# mode BCI (1-2 s), assez long pour ne pas réveiller le processus 250 fois par seconde.
POLL_S = 0.05
QUALITY_PERIOD_S = 1.0    # cadence du flux `quality`
STATUS_PERIOD_S = 2.0     # rappel périodique de l'état (pour un client qui arrive en retard)
QUALITY_WINDOW_S = 2.0    # longueur de signal sur laquelle on mesure le σ par voie

# Cadence maximale du message « inlet de marqueurs en erreur ». Mesuré sur un inlet perdu : 310
# exceptions en 20 s. Sans cette limite, la boucle imprime 20 lignes par seconde et noie tout le
# reste du journal — y compris les messages des modes qui tournent à côté et vont très bien.
_MARQUEUR_ERREUR_PERIODE_S = 10.0
# Seuils auxquels un compteur de marqueurs s'annonce tout seul (cf. `_dit_compteurs_marqueurs`).
# Le premier vaut 1 : le tout premier incident doit se voir, c'est celui qui explique tous les
# suivants.
_SEUILS_MARQUEURS = (1, 10, 100, 1000, 10000)


class EngineServer:
    """Boucle acquisition -> publication. Un objet, une session casque, N modes actifs.

    Le moteur tient **son propre tampon glissant** (`recent`). C'est le point d'architecture
    central : `get_new_data()` VIDE le tampon de BrainFlow, donc les accesseurs à fenêtre
    glissante (`get_window`, `get_epoch`) ne peuvent plus servir. Diffuser et décoder en même
    temps n'est possible qu'en gardant l'historique ici, et en alimentant depuis lui à la fois
    la publication brute et les décodeurs des `ModeRuntime` actifs.
    """

    def __init__(self, serial=None, synthetic=False, verbose=False, modes=("raw",),
                 params=None, instance=None):
        """`modes` : les identifiants à démarrer. `params` : {mode_id: {clé: valeur}}, facultatif.

        Un identifiant inconnu ou un réglage invalide lève ici, au démarrage — bruyamment et
        tout de suite, plutôt qu'en séance sur un décodage qui ne détecte jamais rien.
        """
        self.synthetic = synthetic
        self.acq = UnicornAcquisition(serial=serial, synthetic=synthetic, verbose=verbose)
        self.clock = ClockBridge()
        self.instance = instance or default_instance_id(serial, synthetic)
        self.quality_out = QualityPublisher(ch_names=CH_NAMES, instance=self.instance)
        self.status_out = StatusPublisher(instance=self.instance)
        self.samples = 0
        self.new_block = None       # le bloc lu au tour courant : (eeg, horodatages LSL) ou None
        self.recent = np.zeros((0, len(CH_NAMES)))
        # Les horodatages des mêmes échantillons, en temps LSL. Sans eux on ne peut pas SITUER
        # un marqueur dans le tampon — c'est ce qui manquait pour épocher sur un événement
        # extérieur. Tenus rigoureusement en phase avec `recent` : même longueur, même troncature.
        self.recent_ts = np.zeros((0,))
        self.marker_inlet = None       # créé au démarrage si un mode écoute des marqueurs
        self._marqueurs = []           # tous les marqueurs reçus, dans l'ordre d'arrivée
        self._marqueur_curseur = {}    # mode_id -> index du prochain marqueur à examiner
        self.marqueurs_perdus = 0      # arrivés trop tard pour trouver leur EEG
        self.marqueurs_futurs = 0      # horodatés en avance : time_correction() oublié ?
        self.marqueurs_inlet_erreurs = 0   # incidents réseau/LSL sur l'inlet, comptés plutôt
                                            # qu'avalés (voir _tire_marqueurs)
        # `illisibles` est porté par l'inlet, qui peut être LÂCHÉ et refait (émetteur relancé,
        # mode arrêté) : sans ce report, le compteur repartirait de zéro à chaque incident et le
        # total affiché mentirait par le bas — exactement le genre de chiffre rassurant et faux
        # que ce projet refuse. On cumule donc ce qu'emportent les inlets fermés.
        self._marqueurs_illisibles_clos = 0
        self._marqueur_attente_dite = False    # « pas encore là » : dit une fois, pas à 20 Hz
        self._marqueur_erreur_dite_a = 0.0     # dernier message d'erreur d'inlet (perf_counter)
        self._marqueur_erreurs_tues = 0        # erreurs tues depuis, dites au prochain message
        self._marqueurs_seuils_dits = {}       # compteur -> dernier seuil déjà annoncé
        self.active = {}            # {mode_id: ModeRuntime}, dans l'ordre du registre
        # AU PLUS UNE calibration à la fois, tous modes confondus : il n'y a qu'un casque et qu'une
        # personne. Elle vit ICI et non dans `self.active` — un mode qui refuse de démarrer sans
        # modèle (le MI) rendrait sa propre calibration inatteignable.
        self.calibration = None
        self.rest_instruction = ""  # la consigne du repos en cours, partagée s'il l'est
        self._stop = False
        self._last_tick = {}
        self._commands = queue.Queue()
        self._quality = None
        self._reference_lost = None
        self._warmup_override = None
        self._rest_override = None

        # Le tampon doit satisfaire le plus gourmand des consommateurs : la qualité veut
        # QUALITY_WINDOW_S, le SSVEP WINDOW_S, le neuro NEURO_WINDOW_S, le MI MI_WINDOW_S — chacun
        # plus la marge de filtre. On dimensionne sur TOUS les modes, pas sur ceux qui tournent :
        # démarrer un mode en cours de séance ne doit pas dépendre de la taille d'un tampon.
        #
        # ⚠️ Et sur les CALIBRATIONS, qui prélèvent des tranches BIEN PLUS LONGUES que n'importe
        # quel décodeur : le MI enregistre des époques de 4 s là où il en décode 2. Sans ce terme,
        # chaque époque serait tronquée à la longueur du tampon — sans erreur, sans avertissement,
        # avec un tiers des fenêtres d'entraînement attendues. C'est `Calib.epoch_s` qui le déclare.
        #
        # `runtime_cls is not None` EN PLUS de `calibration is not None` : une calibration
        # « native » (c-VEP, P300) n'est JAMAIS jouée par le moteur — c'est `research/app.py` qui
        # la joue — donc son `epoch_s`, purement documentaire, ne doit dimensionner AUCUN tampon
        # ici. Sans ce filtre, un `epoch_s` posé sur une calibration native pour la lisibilité
        # gonflerait `keep` en silence — et, par ricochet, la fenêtre de mesure de la qualité
        # (`_publish_quality`, cf. son propre avertissement).
        epoque_calib = max([spec.calibration.epoch_s for spec in registry.MODES
                            if spec.calibration is not None
                            and spec.calibration.runtime_cls is not None] or [0.0])
        # L'époque prélevée autour d'un marqueur, plus le retard qu'on tolère pour ce marqueur.
        # ⚠️ Ce besoin doit être NOMMÉ ici. Les 2 s qui suffisaient jusqu'ici venaient de
        # `QUALITY_WINDOW_S` et `MI_WINDOW_S` : personne ne pense à les protéger, et les baisser
        # un jour tronquerait CHAQUE époque P300 en silence.
        #
        # ⚠️ À ne pas confondre avec le filtre juste au-dessus : l'`epoch_s` d'une calibration
        # NATIVE ne dimensionne rien, parce que le moteur ne joue jamais ces calibrations. Ici
        # c'est l'époque du RUNTIME, que le moteur prélève lui-même à chaque marqueur.
        epoque_marqueur = max([spec.marker_epoch_s for spec in registry.MODES] or [0.0])
        self.keep = max(int(QUALITY_WINDOW_S * self.acq.fs),
                        int(NEURO_WINDOW_S * self.acq.fs),
                        int(MI_WINDOW_S * self.acq.fs),
                        int(epoque_calib * self.acq.fs),
                        int(round((epoque_marqueur + MARKER_LATE_S) * self.acq.fs)),
                        self.acq.window_n) + self.acq.margin_n

        self._pending = self._prepare(modes or (), params or {})
        if not self._pending:
            # `--no-raw` sans `--mode` donne un moteur qui n'a rien à publier. Il tourne, il
            # acquiert, et le réseau reste muet — panne silencieuse dont le seul symptôme est un
            # client qui ne trouve jamais son flux. On le dit plutôt que de le laisser deviner.
            print("[server] AUCUN mode demandé : seuls `quality` et `status` seront publiés. "
                  "Ajoute --mode, ou retire --no-raw.")

    def _prepare(self, modes, params):
        """Valide les modes demandés au démarrage. Retourne [(spec, réglages), ...]."""
        prepared = []
        for spec in registry.MODES:            # l'ordre du registre, toujours
            if spec.id not in modes:
                continue
            if spec.runtime_cls is None:
                raise ValueError(f"« {spec.label} » ne tourne pas dans le moteur : "
                                 f"{spec.unavailable}")
            values, reason = contract.validate(spec, params.get(spec.id, {}))
            if values is None:
                raise ValueError(reason)
            prepared.append((spec, values))
        inconnus = sorted(set(modes) - {s.id for s, _ in prepared})
        if inconnus:
            connus = ", ".join(s.id for s in registry.runnable())
            raise ValueError(f"mode inconnu : {', '.join(inconnus)} (disponibles : {connus})")
        return prepared

    def stop(self):
        self._stop = True

    # --- démarrer, arrêter, régler — les opérations sur les modes -----------

    def _start(self, ids, values, now):
        """Démarre des modes. Ceux lancés ENSEMBLE partagent une seule phase de repos."""
        demarres = []
        for spec in registry.MODES:            # ordre du registre : il arbitre les égalités
            if spec.id not in ids:
                continue
            runtime = spec.runtime_cls(spec, values[spec.id], self)
            runtime.open()
            self.active[spec.id] = runtime
            self._last_tick[spec.id] = 0.0
            demarres.append(runtime)
        self._begin_shared_rest(demarres, now)
        for runtime in demarres:
            if runtime.spec.stream:
                print(f"[server] {runtime.spec.label} démarré — flux "
                      f"{stream_name(runtime.spec.stream)}"
                      + (" (silencieux pendant le repos)" if runtime.spec.rest else ""))

    def _begin_shared_rest(self, runtimes, now):
        """Un seul repos pour tous ceux qui en demandent un, si on les lance ensemble.

        Les consignes sont compatibles — « ne fixe aucune cible » et « immobile et détendu »
        décrivent le même moment — donc imposer deux repos de suite ferait attendre l'étudiant
        pour rien. Lancés SÉPARÉMENT, chacun fait le sien : un mode démarré alors qu'un autre
        tourne déjà ne peut pas réutiliser un repos qu'il n'a pas observé.

        Trois règles déterministes, pour qu'il n'y ait rien à interpréter : la durée retenue est
        le MAXIMUM des durées demandées, la chauffe le MAXIMUM des chauffes, et la consigne
        affichée celle du mode dont le repos est le plus long. À égalité, `max` rend le premier
        de la liste — qui est dans l'ordre du registre.
        """
        for runtime in runtimes:
            if runtime.spec.rest is None:
                runtime.begin_rest(now)        # met la phase à « running », rien de plus
        au_repos = [r for r in runtimes if r.spec.rest is not None]
        if not au_repos:
            return

        chauffe = max(r.spec.rest.warmup_s for r in au_repos)
        duree = max(r.spec.rest.duration_s for r in au_repos)
        if self._warmup_override is not None:
            chauffe = self._warmup_override
        if self._rest_override is not None:
            duree = self._rest_override
        meneur = max(au_repos, key=lambda r: r.spec.rest.duration_s)
        self.rest_instruction = meneur.spec.rest.instruction
        for runtime in au_repos:
            runtime.begin_rest(now, warmup_s=chauffe, duration_s=duree)
        quoi = ", ".join(r.spec.label for r in au_repos)
        print(f"[server] repos ({quoi}) : stabilisation {chauffe:.0f} s puis {duree:.0f} s — "
              f"{self.rest_instruction}")

    def _stop_mode(self, mode_id):
        runtime = self.active.pop(mode_id, None)
        if runtime is None:
            return
        runtime.close()
        self._last_tick.pop(mode_id, None)
        # Sans ce nettoyage, un curseur FIGÉ à l'index où ce mode s'est arrêté resterait à
        # traîner dans `_marqueur_curseur` pour le reste du processus — inoffensif tant que
        # `_purge_marqueurs` ne regarde que les modes encore actifs, mais une entrée morte de
        # plus à chaque cycle démarrer/arrêter d'une longue séance, pour rien.
        self._marqueur_curseur.pop(mode_id, None)
        # ⚠️ Et l'INLET lui-même, dès qu'il ne reste plus un seul mode actif pour l'écouter.
        # Sans ça, `self.marker_inlet` vivait pour toute la durée du processus : `_ouvre_marker_
        # inlet` ne recrée rien tant qu'il est non-None, donc redémarrer le mode ne rouvrait PAS
        # l'inlet — et un étudiant qui ferme puis relance son application de stimulus (le geste
        # de routine en TP) restait MUET pour toujours, sans exception, sans compteur qui bouge.
        # Lâcher ici, c'est rendre au tour suivant sa chance de re-résoudre.
        self._libere_marker_inlet("plus aucun mode actif n'écoute les marqueurs")
        if not any(r.phase in ("warmup", "rest") for r in self.active.values()):
            self.rest_instruction = ""
        print(f"[server] {runtime.spec.label} arrêté — son flux disparaît du réseau")

    def _set_params(self, mode_id, values):
        """Applique des réglages. Le repos de CE mode repart s'il en a un.

        Un plancher mesuré sous d'autres réglages est faux : pour le SSVEP il est mesuré PAR
        FRÉQUENCE, le garder après changement comparerait le ρ d'une cible au bruit de fond
        d'une autre. On recrée aussi le flux, parce que les métadonnées LSL sont figées à la
        création et que les voies portent les fréquences (`score_15Hz`) — garder l'ancien flux
        publierait des étiquettes fausses. Les clients doivent se réabonner, le NOM ne change
        pas, un nouveau `resolve_byprop` suffit.

        ⚠️ Une commande peut être appliquée après que la boucle a arrêté ce mode entre-temps
        (soumise puis le mode stoppé avant d'être drainée) : `mode_id` peut donc avoir disparu
        de `self.active`. On l'ignore avec un message clair plutôt que de laisser un `KeyError`
        remonter jusqu'à `_drain_commands`.
        """
        ancien = self.active.get(mode_id)
        if ancien is None:
            print(f"[server] réglage ignoré : « {mode_id} » a été arrêté entre-temps")
            return
        spec = ancien.spec
        avant = dict(ancien.params)
        # Le décodeur ne lit pas tous les réglages : le rafraîchissement de l'écran et le pic
        # alpha ne servent qu'à proposer et à valider. Quand rien de ce qu'il lit n'a bougé, on
        # met les réglages à jour EN PLACE. Reconstruire le runtime jetterait le plancher de repos
        # déjà mesuré et recréerait le flux — 23 secondes et un réabonnement des clients, pour un
        # changement qui n'affecte ni l'un ni l'autre. Et ça apprendrait à l'étudiant à ne plus
        # toucher aux réglages, ce qui est l'inverse du but.
        comptent = {p.key for p in spec.params if p.affecte_decodage}
        if not [k for k, v in values.items() if k in comptent and avant.get(k) != v]:
            ancien.params = dict(values)
            hors = ", ".join(f"{k} : {avant.get(k)} -> {v}"
                             for k, v in values.items() if avant.get(k) != v)
            print(f"[server] {spec.label} — {hors or 'aucun changement'} "
                  f"(sans effet sur le décodage : ni repos refait, ni flux recréé)")
            return
        # CONSTRUIRE d'abord, FERMER ensuite. Un constructeur de runtime peut lever — celui du MI
        # le fait PAR CONCEPTION quand le modèle a disparu entre la validation et le démarrage.
        # Dans l'autre ordre, l'ancien runtime restait dans `active` avec son flux déjà fermé mais
        # `published = True` : la console affichait « publié, en décodage » alors que plus rien ne
        # sortait du réseau. Aucun doublon de flux à craindre ici — un constructeur n'ouvre aucun
        # outlet, c'est `open()` qui le fait, et il n'est appelé qu'après la fermeture.
        runtime = spec.runtime_cls(spec, values, self)
        ancien.close()
        runtime.published = ancien.published
        if runtime.published:
            runtime.open()
        self.active[mode_id] = runtime
        self._last_tick[mode_id] = 0.0
        self._begin_shared_rest([runtime], time.perf_counter())
        changes = ", ".join(f"{k} : {avant[k]} -> {v}" for k, v in values.items()
                            if avant.get(k) != v)
        print(f"[server] {spec.label} — {changes or 'aucun changement'}"
              + (f" ; flux {stream_name(spec.stream)} RECRÉÉ (réabonnez-vous)"
                 if spec.stream else ""))

    def _set_published(self, mode_id, on):
        """⚠️ Même tolérance que `_set_params` : le mode peut avoir été arrêté entre-temps."""
        runtime = self.active.get(mode_id)
        if runtime is None:
            print(f"[server] publication ignorée : « {mode_id} » a été arrêté entre-temps")
            return
        runtime.set_published(on)
        print(f"[server] {runtime.spec.label} : "
              + ("publié sur le réseau" if on else "décodé pour l'affichage seulement, "
                                                   "son flux disparaît du réseau"))

    def _recalibrate(self, mode_id):
        """⚠️ Même tolérance que `_set_params` : le mode peut avoir été arrêté entre-temps."""
        runtime = self.active.get(mode_id)
        if runtime is None:
            print(f"[server] repos ignoré : « {mode_id} » a été arrêté entre-temps")
            return
        self._begin_shared_rest([runtime], time.perf_counter())

    def _start_calibration(self, mode_id, values):
        """Construit la calibration. Appelée par la boucle, jamais par le fil d'une interface.

        ⚠️ Même garde que `_set_params`/`_set_published`/`_recalibrate` : `submit()` a déjà
        refusé une calibration EN COURS au moment où elle a été SOUMISE, mais deux commandes
        `start_calibration` soumises dans la MÊME fenêtre de sondage (avant que la boucle n'ait
        drainé la première) ont toutes deux vu `self.calibration` à `None` et ont donc été
        acceptées toutes les deux. Sans ce second contrôle, ICI, côté boucle, la seconde
        écraserait SILENCIEUSEMENT la première — un double-clic sur « Commencer » y suffit.
        """
        if self.calibration is not None and not self.calibration.terminee:
            print(f"[server] calibration ignorée : « {self.calibration.spec.label} » est déjà "
                  f"en cours")
            return
        spec = registry.get(mode_id)
        self.calibration = spec.calibration.runtime_cls(spec, values, self)
        print(f"[server] {spec.calibration.label or spec.label} : "
              f"{self.calibration.total()} essais, "
              f"≈ {self.calibration.duree_estimee_s() / 60:.0f} min — "
              f"stabilisation {self.calibration.warmup_s:.0f} s d'abord")

    # --- API de commande interne (SPEC §12.1) --------------------------------
    # La console et, plus tard, l'adaptateur de commandes LSL passent tous les deux PAR ICI.
    # Un seul chemin à tester, et le protocole de contrôle reste remplaçable sans réécrire le
    # moteur.
    #
    # Les commandes ne sont PAS appliquées par le fil qui les soumet : elles sont mises en file
    # et exécutées par la boucle. C'est ce qui garantit que la session BrainFlow n'est touchée
    # que depuis un seul fil — la partager entre l'interface et l'acquisition produirait des
    # corruptions qu'aucun test ne rattraperait.

    COMMANDS = ("start_mode", "propose_params", "stop_mode", "set_params", "set_published",
                "recalibrate", "start_calibration", "cancel_calibration", "stop")

    def submit(self, command, **params):
        """Met une commande en file. Retourne un accusé, PAS le résultat (appliqué plus tard).

        Une exception à la règle « accusé seulement » : la VALIDITÉ est vérifiée ici, tout de
        suite. Le refus d'une commande mal formée est une propriété du message, pas de l'état du
        moteur, et la renvoyer immédiatement évite à l'étudiant de chercher pourquoi son réglage
        n'a rien fait. Ce que `submit` ne promet toujours pas, c'est que la commande ait été
        APPLIQUÉE : ça s'observe sur `snapshot()` ou sur le flux `status`.
        """
        if command not in self.COMMANDS:
            return {"accepted": False,
                    "reason": f"commande inconnue : {command} "
                              f"(connues : {', '.join(self.COMMANDS)})"}

        if command == "stop":
            self._commands.put(("stop", {}))
            return {"accepted": True, "command": "stop"}

        if command == "start_mode":
            ids = params.get("ids") or ([params["id"]] if params.get("id") else [])
            if not ids:
                return {"accepted": False, "reason": "aucun mode demandé (id ou ids)"}
            specs, reason = self._resolve(ids, doit_tourner=False)
            if specs is None:
                return {"accepted": False, "reason": reason}
            wanted, values = params.get("params") or {}, {}
            for spec in specs:
                v, reason = contract.validate(spec, wanted.get(spec.id, {}))
                if v is None:
                    return {"accepted": False, "reason": reason}
                values[spec.id] = v
            ids = [s.id for s in specs]
            self._commands.put(("start_mode", {"ids": ids, "params": values}))
            return {"accepted": True, "command": "start_mode", "ids": ids}

        if command == "propose_params":
            # Une commande en LECTURE : elle ne met rien en file et ne touche pas la session
            # BrainFlow, donc elle peut répondre tout de suite. Elle reste ici pour que la console
            # et un client LSL empruntent le même chemin — un seul endroit à tester.
            spec = registry.get(params.get("id"))
            if spec is None:
                connus = ", ".join(s.id for s in registry.runnable())
                return {"accepted": False,
                        "reason": f"mode inconnu : {params.get('id')} (disponibles : {connus})"}
            cle = params.get("key")
            source = next((p for p in spec.params if p.key == cle and p.proposes), None)
            if source is None:
                proposeurs = [p.key for p in spec.params if p.proposes]
                return {"accepted": False,
                        "reason": f"« {cle} » ne propose aucun réglage pour « {spec.label} » "
                                  f"(qui propose : {', '.join(proposeurs) or 'aucun'})"}
            runtime = self.active.get(spec.id)
            courant = dict(runtime.params) if runtime is not None else spec.defaults()
            # Ce que l'appelant est en train d'éditer prime sur ce qui est stocké : sans ça,
            # déclarer un écran 144 Hz est refusé (les anciennes fréquences ne le divisent pas)
            # ET la proposition continue de calculer sur 60 — l'étudiant n'a aucune porte de sortie.
            courant.update(params.get("params") or {})
            cible = source.proposes

            def _nombre(valeur, repli):
                """Convertit en float avec un repli : `submit` ne doit JAMAIS lever — il tourne
                sur le fil de l'interface, et une saisie illisible ne doit pas le faire planter."""
                try:
                    return float(valeur) if valeur else repli
                except (TypeError, ValueError):
                    return repli

            # `courant[cible]` peut être une CHAÎNE si l'étudiant a mal tapé la liste : `len()`
            # rendrait alors le nombre de CARACTÈRES, pas de fréquences. On ne compte que sur une
            # vraie liste, sinon on retombe sur le nombre de cibles par défaut du contrat.
            valeur_cible = courant.get(cible)
            n = (len(valeur_cible) if isinstance(valeur_cible, (list, tuple))
                 else len(spec.defaults().get(cible) or ()))
            valeurs, note = propose_frequencies(_nombre(courant.get("refresh_hz"), 60.0), n,
                                                _nombre(courant.get("alpha_hz"), ALPHA_DEFAUT_HZ))
            if not valeurs:
                return {"accepted": False, "reason": note}
            return {"accepted": True, "command": command, "id": spec.id,
                    "key": cible, "value": valeurs, "warning": note}

        if command == "start_calibration":
            spec = registry.get(params.get("id"))
            if spec is None:
                connus = ", ".join(s.id for s in registry.MODES if s.calibration is not None)
                return {"accepted": False,
                        "reason": f"mode inconnu : {params.get('id')} "
                                  f"(se calibrent : {connus})"}
            calib = spec.calibration
            if calib is None:
                return {"accepted": False,
                        "reason": f"« {spec.label} » n'a pas de calibration — il n'apprend rien"}
            if calib.runtime_cls is None:
                # Le c-VEP et le P300 : leur stimulus est verrouillé à la frame, une interface Qt
                # ne peut pas le rendre. La raison est dans le contrat, on la transmet telle quelle.
                return {"accepted": False,
                        "reason": f"la calibration de « {spec.label} » n'est pas jouable par le "
                                  f"moteur : {calib.reason or 'stimulus natif requis'} — passe "
                                  f"par `python src/research/app.py`"}
            # ⚠️ Ce mode n'a PAS besoin d'être démarré : c'est même le cas normal. Le mode MI
            # refuse de démarrer sans modèle, or c'est justement la calibration qui en produit un.
            # Copie LOCALE de `self.calibration`, prise UNE fois : la boucle peut la remettre à
            # `None` entre deux lectures (arrêt du moteur, cf. le `finally` de `run()`) — `submit`
            # promet en toutes lettres de ne JAMAIS lever, y compris depuis le fil de l'interface
            # pendant que la boucle tourne sur le sien. Trois lectures de `self.calibration` de
            # suite (`is not None`, `.terminee`, `.spec.label`) couraient ce risque ; une seule
            # variable locale l'élimine par construction, comme le fait déjà `_status_key`.
            en_cours = self.calibration
            if en_cours is not None and not en_cours.terminee:
                return {"accepted": False,
                        "reason": f"une calibration est déjà en cours ({en_cours.spec.label}) — "
                                  f"abandonne-la avant d'en lancer une autre"}
            values, reason = contract.validate(calib, params.get("params") or {})
            if values is None:
                return {"accepted": False, "reason": reason}
            self._commands.put(("start_calibration", {"id": spec.id, "params": values}))
            return {"accepted": True, "command": command, "id": spec.id, "params": values}

        if command == "cancel_calibration":
            en_cours = self.calibration   # même motif que start_calibration juste au-dessus
            if en_cours is None or en_cours.terminee:
                return {"accepted": False, "reason": "aucune calibration en cours"}
            self._commands.put(("cancel_calibration", {}))
            return {"accepted": True, "command": command, "id": en_cours.spec.id}

        spec, reason = self._one(params.get("id"))
        if spec is None:
            return {"accepted": False, "reason": reason}

        if command == "stop_mode":
            self._commands.put(("stop_mode", {"id": spec.id}))
        elif command == "set_published":
            self._commands.put(("set_published",
                                {"id": spec.id, "on": bool(params.get("on", True))}))
        elif command == "recalibrate":
            if spec.rest is None:
                return {"accepted": False,
                        "reason": f"« {spec.label} » n'a pas de repos à refaire"}
            self._commands.put(("recalibrate", {"id": spec.id}))
        elif command == "set_params":
            # ⚠️ `_one` (juste au-dessus) vient de vérifier que `spec.id` est dans `self.active`
            # — mais `submit` tourne sur le fil de l'APPELANT (la console), pas sur celui de la
            # boucle, qui peut arrêter ce mode entre les deux. Indexer `self.active[spec.id]`
            # sans garde lèverait un `KeyError` ICI, dans le fil appelant : exactement ce que
            # `submit` promet de ne jamais faire (un accusé, toujours — jamais une exception).
            runtime = self.active.get(spec.id)
            if runtime is None:
                return {"accepted": False,
                        "reason": f"« {spec.label} » a été arrêté entre-temps"}
            # On fusionne sur les réglages COURANTS : un appelant peut n'envoyer que ce qu'il
            # change, sans avoir à relire et renvoyer tout le reste.
            merged = dict(runtime.params)
            merged.update(params.get("params") or {})
            values, reason = contract.validate(spec, merged)
            if values is None:
                return {"accepted": False, "reason": reason}
            self._commands.put(("set_params", {"id": spec.id, "params": values}))
        return {"accepted": True, "command": command, "id": spec.id}

    def _resolve(self, ids, doit_tourner):
        """(specs dans l'ordre du registre, None) ou (None, raison). Refuse tôt et en clair."""
        for mode_id in ids:
            spec = registry.get(mode_id)
            if spec is None:
                connus = ", ".join(s.id for s in registry.runnable())
                return None, f"mode inconnu : {mode_id} (disponibles : {connus})"
            if spec.runtime_cls is None:
                # C'est exactement ce que la tuile doit dire à l'étudiant : POURQUOI ça ne
                # démarre pas, jamais un échec silencieux.
                return None, f"« {spec.label} » ne tourne pas dans le moteur : {spec.unavailable}"
            if not doit_tourner and spec.id in self.active:
                return None, (f"« {spec.label} » est déjà démarré — utilise « refaire le repos » "
                              f"pour le relancer")
            if doit_tourner and spec.id not in self.active:
                return None, f"« {spec.label} » n'est pas démarré"
        return [s for s in registry.MODES if s.id in ids], None

    def _one(self, mode_id):
        specs, reason = self._resolve([mode_id] if mode_id else [], doit_tourner=True)
        if specs is None:
            return None, reason
        if not specs:
            return None, "aucun mode désigné (id manquant)"
        return specs[0], None

    def _apply(self, command, params):
        if command == "stop":
            self.stop()
        elif command == "start_mode":
            self._start(params["ids"], params["params"], time.perf_counter())
        elif command == "stop_mode":
            self._stop_mode(params["id"])
        elif command == "set_params":
            self._set_params(params["id"], params["params"])
        elif command == "set_published":
            self._set_published(params["id"], params["on"])
        elif command == "recalibrate":
            self._recalibrate(params["id"])
        elif command == "start_calibration":
            self._start_calibration(params["id"], params["params"])
        elif command == "cancel_calibration":
            if self.calibration is not None:
                self.calibration.cancel()
                print(f"[server] calibration abandonnée — aucun modèle produit")

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

    # --- la phase globale et l'état publié ------------------------------------
    # Le contrat public de `status` emploie « baseline » et « decoding » depuis le début ; les
    # runtimes emploient le vocabulaire de la spec (« rest », « running »). On traduit ici
    # plutôt que de renommer une valeur du contrat pour un confort interne.
    _PHASES_PUBLIQUES = {"warmup": "warmup", "rest": "baseline", "running": "decoding"}

    def _phase_of(self, active, calibration):
        """La phase publique, calculée sur une COPIE de la table des modes actifs ET une COPIE
        de `self.calibration` — toutes deux prises par l'APPELANT, jamais relues ici.

        Séparée de la propriété pour que `_state` puisse la calculer sur les MÊMES copies que le
        reste de son payload : des copies distinctes, prises à des instants différents,
        laisseraient `phase`, `modes` et `calibration` se contredire à l'intérieur d'un seul
        appel — un même `snapshot()` pourrait alors rendre `phase: "calibrating"` ET
        `calibration: null`, deux valeurs contradictoires dans un seul état publié. Cette
        méthode ne protège rien elle-même, elle fait confiance à l'appelant (voir `phase` et
        `_state`/`snapshot`, les seuls qui en fournissent).
        """
        # Une calibration en cours prime sur tout : c'est ce que la personne est en train de
        # faire, et les modes qui décodent en même temps sont secondaires. `calibrating` est une
        # valeur PUBLIQUE du flux `status` (spec §6) — un client peut s'en servir pour mettre son
        # application en pause pendant qu'on entraîne.
        if calibration is not None and not calibration.terminee:
            return "calibrating"
        phases = [r.phase for r in active.values() if r.spec.rest is not None]
        if not phases:
            return "streaming"
        for interne in ("warmup", "rest", "running"):
            if interne in phases:
                return self._PHASES_PUBLIQUES[interne]
        return "streaming"

    @property
    def phase(self):
        """La phase la MOINS avancée parmi les modes qui mesurent un repos. Sûre depuis un autre
        fil : ELLE copie `self.active` ET `self.calibration` avant de les lire — une propriété
        nue ne peut pas recevoir des copies déjà prises par un appelant, donc c'est ici, et nulle
        part ailleurs, qu'elles doivent se faire. `_smoke_ssvep`/`_smoke_neuro` sondent
        `server.phase` depuis le fil du test pendant que la boucle du moteur tourne sur le sien :
        exactement la lecture inter-fils que ces copies protègent.

        « streaming » quand aucun mode actif n'a de repos à faire : c'est le cas du brut seul.
        """
        return self._phase_of(dict(self.active), self.calibration)

    def _status_key(self, running):
        """Ce qui constitue un vrai CHANGEMENT d'état — hors compteurs (cf. StatusPublisher.push).

        Un compteur glissé ici défait la déduplication : mesuré une fois à 19,6 Hz de messages
        d'état au lieu de 0,5 Hz, assez discret pour passer inaperçu, assez bruyant pour noyer
        un client.
        """
        calib = self.calibration
        return (running, self.synthetic, self.phase,
                tuple((mid, r.phase, r.published) for mid, r in sorted(self.active.items())),
                None if calib is None else (calib.spec.id, calib.phase, calib.etape, calib.essai))

    def _state(self, running, *, calibration, active=None):
        """État public (`status` / `snapshot`).

        `calibration` : copie déjà prise de `self.calibration`, TOUJOURS EXIGÉE — jamais un
        défaut à `None` pour dire « pas encore copiée ». Contrairement à `active` (juste en
        dessous), `None` est ICI aussi la valeur RÉELLE d'« aucune calibration en cours » :
        confondre les deux ferait relire `self.calibration` en douce et annulerait la copie
        prise par l'appelant si la boucle a bougé entre-temps — exactement le bug que cette
        signature existe pour rendre impossible plutôt que discipliné. Chaque appelant en prend
        UNE et la réutilise PARTOUT dans son propre appel (cf. `snapshot`).

        `active` : copie déjà prise de `self.active`, à passer quand l'appelant en a déjà une
        (voir `snapshot`) pour ne pas en reprendre une seconde qui pourrait différer de la
        première si la boucle a bougé entre-temps. Sans argument, `_state` en prend une elle-même
        — jamais `self.active` en direct : un `for mid in self.active` ou un dict-comprehension
        sur `self.active.items()` itère le dict VIVANT, et la boucle peut démarrer ou arrêter un
        mode entre deux pas de cette itération (elle tourne sur un autre fil que l'appelant de
        `snapshot`) — ce qui lève `RuntimeError: dictionary changed size during iteration` chez
        l'appelant. `dict(self.active)` copie en C, sans repasser la main : c'est pour ça que la
        boucle de `run()` fait déjà `list(self.active.items())` avant d'itérer, même depuis SON
        propre fil. `active` PEUT rester optionnelle, à la différence de `calibration` :
        `self.active` n'est jamais `None` lui-même, donc rien ici ne confond « pas fourni » et
        « la vraie valeur est vide ».

        Même discipline pour la phase : on appelle `_phase_of(active, calibration)` sur CES
        copies, une seule fois, plutôt que de lire la propriété `self.phase` (qui en reprendrait
        d'AUTRES, à un instant différent). Des copies désaccordées pourraient se contredire —
        `modes` listant un mode que `phase` ne voit plus, par exemple — les mêmes copies ne le
        peuvent pas.
        """
        if active is None:
            active = dict(self.active)
        streams = ["quality", "status"]
        for spec in registry.MODES:
            runtime = active.get(spec.id)
            if runtime is not None and runtime.published and spec.stream:
                streams.append(spec.stream)
        actifs = list(active)
        # `mode` (au singulier) reste publié pour ne pas casser un client écrit contre le flux
        # `status` d'hier : il porte le premier mode DÉCODÉ actif, ou null. `modes` porte la
        # vérité complète. Le jour où plusieurs modes décodent, `mode` en montre un seul — c'est
        # assumé, et c'est pour ça que `modes` existe.
        decodes = [mid for mid in actifs if mid != "raw"]
        phase = self._phase_of(active, calibration)
        state = {
            "running": running,
            "board": "synthetic" if self.synthetic else "unicorn",
            "instance": self.instance,
            "fs_hz": float(self.acq.fs),
            "channels": list(CH_NAMES),
            "mode": decodes[0] if decodes else None,
            "modes": actifs,
            "phase": phase,
            "samples_published": self.samples,
            "streams": [stream_name(s) for s in streams],
            # ⚠️ Les quatre compteurs de marqueurs SORTENT ici, et c'est le point : ils étaient
            # incrémentés avec soin et lus par personne. `modes/p300.py` les annonce comme le
            # moyen par lequel trois de ses six pannes sont dites, et `docs/markers.md` dit à
            # l'étudiant « si ce nombre grimpe » — sans ce champ, la chaîne ne menait nulle part
            # et un P300 qui ne déclenche jamais restait indiscernable d'un sujet distrait.
            #
            # Ils n'entrent PAS dans `_status_key` : un compteur qui bouge ne doit pas compter
            # comme un changement d'état, sinon la déduplication du flux `status` tombe (mesuré
            # une fois à 19,6 Hz au lieu de 0,5 Hz). Ils voyagent donc avec le rappel périodique,
            # ce qui suffit largement pour un indicateur de santé.
            "marqueurs": {
                "perdus": self.marqueurs_perdus,
                "futurs": self.marqueurs_futurs,
                "illisibles": self.marqueurs_illisibles,
                "inlet_erreurs": self.marqueurs_inlet_erreurs,
                "connecte": self.marker_inlet is not None and self.marker_inlet.connecte,
            },
        }
        if self.rest_instruction and phase in ("warmup", "baseline"):
            state["instruction"] = self.rest_instruction
        return state

    def snapshot(self):
        """État complet pour un afficheur, en lecture seule. Sûr depuis un autre fil.

        La console (tâches 11-15) sonde ceci depuis le fil Qt, à 10 Hz, pendant que la boucle du
        moteur tourne sur le sien et peut démarrer ou arrêter un mode, ou une calibration, À TOUT
        INSTANT. On prend donc UNE SEULE copie atomique de `self.active` (`dict(...)`, copié en C
        d'un coup — pas de point où l'autre fil pourrait s'intercaler) ET UNE SEULE copie de
        `self.calibration`, et on les fait servir PARTOUT dans cet appel : à `_state()` d'abord,
        à `modes_state`/`calibration` ensuite. Reprendre `self.active` ou `self.calibration` une
        seconde fois referait courir le même risque — et pour `calibration` spécifiquement, un
        même appel pourrait alors rendre `phase: "calibrating"` (calculé sur la PREMIÈRE lecture)
        ET `calibration: null` (calculé sur une SECONDE lecture, après que la boucle l'a remise à
        `None` entre les deux) : deux valeurs contradictoires dans un seul état publié, que la
        docstring de `_state` interdit désormais par sa signature. On rend ensuite un
        dictionnaire déjà construit plutôt que des références vers l'état vivant : l'appelant ne
        peut donc pas lire une valeur à moitié écrite par la boucle.
        """
        active = dict(self.active)
        calib = self.calibration
        state = self._state(not self._stop, active=active, calibration=calib)
        state.update({
            "quality": self._quality,
            "rest_instruction": self.rest_instruction,
            "modes_state": {mid: r.state() for mid, r in active.items()},
            # `now` est passé pour que le décompte affiché soit celui de MAINTENANT, pas celui du
            # dernier tick. La console sonde à 10 Hz, le moteur tourne à sa propre cadence : sans
            # ça le décompte avancerait par à-coups.
            "calibration": (None if calib is None
                            else calib.state(now=time.perf_counter())),
            # Un catalogue est une déclaration, pas de la télémétrie — il ne change pas avec l'état
            # du moteur. Le republier dix fois par seconde était déjà du gaspillage avant que des
            # entrées-sorties (joblib.load, accès au système de fichiers) ne se trouvent derrière.
            # Un client qui voudra le catalogue le demandera explicitement — c'est la forme correcte
            # pour une donnée de ce genre (appel `registry.catalog()` direct, plutôt que via snapshot).
        })
        return state

    def recent_window(self, seconds):
        """Copie des `seconds` dernières secondes de signal BRUT (n, 8), ou None.

        Accesseur PUBLIC pour un afficheur — ET, depuis la moitié B, la source des époques
        D'ENTRAÎNEMENT du Motor Imagery (`CalibrationRuntime._pas_essai` l'appelle avec
        `imagery_s`). Elle DOIT rester non filtrée pour cette seconde raison, exactement comme
        `UnicornAcquisition.motor_window` (qui sert le décodage EN LIGNE, cf. son avertissement) :
        le modèle applique son propre re-référencement CAR puis son passe-bande 8-30 Hz dans
        `MIModel._prep`. Filtrer ICI filtrerait deux fois — phase décalée, variances modifiées,
        or ce sont exactement les variances que le CSP exploite — et entraînerait le MI sur autre
        chose que ce que le modèle verra en ligne : sans erreur, avec des probabilités
        parfaitement plausibles. Quelqu'un qui trouverait les tracés live bruyants et filtrerait
        ici pour les lisser entraînerait donc le MI sur du signal doublement filtré, en silence.

        Le tampon est réécrit par le fil d'acquisition : le lire directement depuis le fil Qt
        donnerait, tôt ou tard, une vue à moitié écrite. On rend donc une copie — c'est quelques
        centaines de Ko, payés une fois par rafraîchissement.
        """
        buffer = self.recent
        if buffer is None or len(buffer) == 0:
            return None
        # `int(round(...))`, PAS `int(...)` : la garde de longueur côté calibration
        # (`CalibrationRuntime._pas_essai`, `attendu = int(round(self.imagery_s * fs))`) arrondit
        # déjà, comme le fait tout le reste du fichier pour cette même conversion
        # (`motor_window`, `occipital_window`, `window_n`, `margin_n`…). Tronquer ICI aurait
        # rendu `n` strictement INFÉRIEUR à `attendu` dès que `seconds * fs` a une partie
        # fractionnaire >= 0,5 — et donc TOUS les essais auraient été écartés comme « tampon pas
        # rempli », jamais un seul. Inatteignable à 4,0 s × 250 Hz (produit entier), mais
        # `imagery_s` est explicitement conçue pour être raccourcie (cf. les smokes de test).
        n = max(1, int(round(seconds * self.acq.fs)))
        return np.array(buffer[-n:], dtype=float, copy=True)

    def _nom_flux_marqueurs(self):
        """Le nom du flux de marqueurs à écouter, d'après les modes ACTIFS qui en consomment.

        Chaque mode marqueur peut déclarer SON `stream_in` dans ses `params` (le P300 le fait) ;
        un mode qui ne le déclare pas (aucun aujourd'hui, un futur mode pourrait) compte pour
        `MARKER_STREAM_DEFAULT`. Sans cette lecture, `stream_in` serait un réglage-DÉCOR : affiché
        dans la console, lu par personne — exactement le genre de piège que ce projet combat.

        ⚠️ Un seul inlet existe pour TOUT le moteur (`self.marker_inlet`, cf. `_ouvre_marker_inlet`) :
        si deux modes actifs réclament des noms DIFFÉRENTS, aucun choix silencieux n'est correct.
        On le dit bruyamment et on retient le premier rencontré (ordre de `self.active`, qui suit
        l'ordre de démarrage) plutôt que de deviner lequel l'utilisateur voulait vraiment.
        """
        noms = [rt.params.get("stream_in", MARKER_STREAM_DEFAULT)
                for rt in self.active.values() if rt.spec.marker_epoch_s > 0.0]
        if not noms:
            return MARKER_STREAM_DEFAULT
        distincts = sorted(set(noms))
        if len(distincts) > 1:
            print(f"[server] ⚠️ désaccord sur le flux de marqueurs à écouter : "
                  f"{', '.join(distincts)} — un seul inlet existe pour tout le moteur, "
                  f"« {noms[0]} » est retenu (vérifie les réglages « Flux de marqueurs » des "
                  f"modes actifs)")
        return noms[0]

    def _ouvre_marker_inlet(self):
        """Crée l'inlet de marqueurs si un mode ACTIF en a besoin et qu'il n'existe pas déjà.

        Appelée à CHAQUE tour de boucle dans `run()`, pas une seule fois avant le `while` :
        `self.active` n'est pas figé à l'entrée dans la boucle, `_drain_commands` (juste
        au-dessus dans `run()`) peut y ajouter un mode en cours de route — c'est exactement ce
        que fait la console au clic « Démarrer » sur une tuile (« start_mode » traité PENDANT
        que la boucle tourne). Un mode marqueur démarré ainsi doit trouver son inlet lui aussi :
        l'évaluer une seule fois avant le `while` le laisserait sans, pour toujours, en silence
        — indiscernable d'un flux calme.

        ⚠️ Le nom est résolu à la création de CET inlet. Changer « Flux de marqueurs » sur un mode
        déjà démarré ne rouvre PAS l'inlet sur un nouveau nom : il faut ARRÊTER le mode (ce qui
        libère l'inlet, cf. `_stop_mode`) puis le redémarrer. C'est écrit dans l'aide du réglage
        (`p300.py`), pas seulement ici.
        """
        if self.marker_inlet is not None:
            return
        if not any(rt.spec.marker_epoch_s > 0.0 for rt in self.active.values()):
            # Ouvrir un flux entrant qui ne sert à personne ferait chercher sur le réseau à
            # chaque tour pour rien.
            return
        self.marker_inlet = MarkerInlet(self._nom_flux_marqueurs(), timeout_s=0.0)
        self._marqueur_attente_dite = False
        self._resout_marker_inlet()

    def _resout_marker_inlet(self):
        """Tente la résolution si besoin, et DIT la transition — une seule fois par transition.

        ⚠️ Le message « connecté » était sur le chemin qui n'aboutit presque jamais. Mesuré :
        `resolve_byprop(timeout=0.0)` échoue aux tout premiers appels d'un processus neuf (0 sur
        5 en rafale, le temps que le résolveur de liblsl remplisse son cache), puis marche. Or
        `_ouvre_marker_inlet` ne donnait qu'UNE chance puis imprimait « pas encore là », tandis
        que la re-tentative de `_tire_marqueurs` — celle qui connecte réellement — n'imprimait
        RIEN. L'étudiant qui lance le moteur avec son stimulus déjà en route lisait donc « pas
        encore là » et n'avait jamais la moindre confirmation. Les deux chemins passent
        maintenant ICI, donc le message suit l'ÉVÉNEMENT et non le chemin.
        """
        inlet = self.marker_inlet
        if inlet is None or inlet.connecte:
            return
        if inlet.resolve():
            self._marqueur_attente_dite = False
            print(f"[server] marqueurs entrants : connecté à « {inlet.nom} ».")
            return
        if not self._marqueur_attente_dite:
            # Pas une erreur : l'application de stimulus démarre souvent APRÈS le moteur. Dit UNE
            # fois — la boucle repasse ici 20 fois par seconde.
            self._marqueur_attente_dite = True
            print(f"[server] marqueurs entrants : « {inlet.nom} » pas encore là — j'attends "
                  f"({inlet.refus}). Lance ton application de stimulus, la connexion se fera "
                  f"toute seule.")

    def _libere_marker_inlet(self, raison):
        """Lâche l'inlet s'il ne sert plus à aucun mode actif. True s'il y avait quelque chose.

        Appelée depuis `_stop_mode` : garder un inlet ouvert pour personne empêche la
        re-résolution (`_ouvre_marker_inlet` ne recrée rien tant qu'il est non-None) et fait
        grossir `_marqueurs` sans personne pour le consommer.
        """
        if self.marker_inlet is None:
            return False
        if any(rt.spec.marker_epoch_s > 0.0 for rt in self.active.values()):
            return False
        self._marqueurs_illisibles_clos += self.marker_inlet.illisibles
        self.marker_inlet.lache(raison)
        self.marker_inlet = None
        # Le tampon part avec l'inlet : plus aucun mode ne peut les consommer, donc les garder
        # ne ferait que gonfler la mémoire d'une longue séance. On le DIT quand il y avait
        # quelque chose dedans — une perte silencieuse, même inoffensive, reste une perte tue.
        if self._marqueurs:
            print(f"[server] marqueurs entrants : flux relâché ({raison}) — "
                  f"{len(self._marqueurs)} marqueur(s) en attente jetés, plus personne pour les "
                  f"lire.")
        self._marqueurs = []
        self._marqueur_curseur = {}
        return True

    @property
    def marqueurs_illisibles(self):
        """Marqueurs reçus mais indécodables, inlets déjà fermés COMPRIS.

        `docs/markers.md` promet à l'étudiant qu'il verra ce nombre grimper si son émetteur
        publie autre chose que le JSON attendu. Le lire sur le seul inlet vivant le remettrait à
        zéro à chaque relance d'émetteur, c'est-à-dire précisément quand il devient intéressant.
        """
        vivant = self.marker_inlet.illisibles if self.marker_inlet is not None else 0
        return self._marqueurs_illisibles_clos + vivant

    def _tire_marqueurs(self):
        """Récupère les marqueurs arrivés depuis le tour précédent, puis purge le tampon.

        Protégée par un `try`, comme le tick de calibration juste à côté dans `run()` : l'inlet
        est une entrée EXTERNE non maîtrisée, sur une machine potentiellement distincte, qui peut
        disparaître en cours de séance (réseau coupé, application de stimulus fermée). Une
        exception ici ne doit tuer NI le moteur NI la séance en cours des AUTRES modes — on
        compte l'incident (`marqueurs_inlet_erreurs`) plutôt que de l'avaler.

        ⚠️ Le message est LIMITÉ EN CADENCE. Mesuré sur un inlet perdu : 310 exceptions en 20 s,
        soit 20 lignes par seconde, qui noient tout le reste du journal — dont les messages du
        SSVEP et du neuro qui tournent à côté. On dit la première tout de suite, puis au plus une
        toutes les `_MARQUEUR_ERREUR_PERIODE_S`, en annonçant combien ont été tues entre-temps :
        limiter la cadence n'autorise pas à cacher le nombre.
        """
        if self.marker_inlet is None:
            return
        try:
            self._resout_marker_inlet()
            self._marqueurs.extend(self.marker_inlet.pull())
        except Exception as e:  # noqa: BLE001 - un incident sur CETTE entrée externe ne doit
            # jamais faire tomber le moteur ni la séance en cours des autres modes (cf. docstring).
            # L'inlet, lui, s'est déjà LÂCHÉ tout seul si le flux a disparu (`MarkerInlet.pull`) :
            # le tour suivant re-résoudra, y compris sur un émetteur RELANCÉ.
            self.marqueurs_inlet_erreurs += 1
            maintenant = time.perf_counter()
            if maintenant - self._marqueur_erreur_dite_a >= _MARQUEUR_ERREUR_PERIODE_S:
                tues = self._marqueur_erreurs_tues
                suite = f" ({tues} autre(s) incident(s) tu(s) depuis)" if tues else ""
                print(f"[server] inlet de marqueurs en erreur : {e}{suite} — je réessaie de me "
                      f"connecter à chaque tour.")
                self._marqueur_erreur_dite_a = maintenant
                self._marqueur_erreurs_tues = 0
            else:
                self._marqueur_erreurs_tues += 1
        self._dit_compteurs_marqueurs()
        self._purge_marqueurs()

    def _dit_compteurs_marqueurs(self):
        """Annonce un compteur de marqueurs quand il franchit un seuil. Une fois par seuil.

        ⚠️ Ces quatre compteurs étaient comptés et lus par PERSONNE : ni `_state`, ni `snapshot`,
        ni le flux `status`, ni un `print`. Or `modes/p300.py` les ANNONCE comme le moyen par
        lequel trois de ses six pannes sont dites, et `docs/markers.md` dit à l'étudiant « si ce
        nombre grimpe ». La chaîne ne menait nulle part. Le cas le plus probable en vrai — un
        `time_correction()` oublié côté émetteur, donc TOUT qui part dans `marqueurs_futurs` —
        produisait un P300 qui tourne, ne déclenche jamais, et ne dit rien.

        Par SEUILS (1, 10, 100…) et non à chaque incrément : à 6,7 flashs par seconde, un
        message par marqueur perdu serait aussi illisible que pas de message du tout.
        """
        for cle, valeur, quoi in (
            ("perdus", self.marqueurs_perdus,
             "arrivés trop tard pour trouver leur EEG (émetteur en retard, ou tampon trop court)"),
            ("futurs", self.marqueurs_futurs,
             "horodatés dans le futur du moteur : `time_correction()` oublié côté émetteur ?"),
            ("illisibles", self.marqueurs_illisibles,
             "reçus mais indécodables (JSON invalide, ou « mode »/« event » manquant)"),
            ("inlet_erreurs", self.marqueurs_inlet_erreurs,
             "incidents réseau sur le flux entrant"),
        ):
            seuil = 0
            for candidat in _SEUILS_MARQUEURS:
                if valeur >= candidat:
                    seuil = candidat
            if seuil and seuil > self._marqueurs_seuils_dits.get(cle, 0):
                self._marqueurs_seuils_dits[cle] = seuil
                print(f"[server] ⚠️ marqueurs {cle} : {valeur} — {quoi}")

    def _purge_marqueurs(self):
        """Jette les marqueurs que TOUS les modes qui les écoutent ont dépassés.

        Sans ça, une séance d'une heure garde des dizaines de milliers de marqueurs en mémoire
        pour rien. La coupe se calcule sur les modes ACTIFS qui écoutent des marqueurs
        (`marker_epoch_s > 0`) — jamais sur les seules clés déjà présentes dans
        `_marqueur_curseur` : un mode tout juste démarré (encore en chauffe) n'a pas encore
        appelé `markers_murs` et n'y a donc AUCUNE entrée. Le compter comme absent plutôt que
        comme curseur 0 couperait devant lui, perdant en silence tout ce qui lui était adressé —
        sans jamais passer par `marqueurs_perdus`, que `markers_murs` réserve au SEUL rejet muet
        qu'elle autorise (et celui-ci n'en fait pas partie).

        ⚠️ SANS écouteur, en revanche, « ce que TOUS les écouteurs ont dépassé » est TOUT : la
        version précédente rendait la main (`if not ecouteurs: return`), soit l'inverse exact de
        cette phrase, et le tampon croissait alors sans borne — mesuré ~5 Mo en 30 min, sans un
        compteur ni un message. Ce chemin ne devrait plus être atteignable depuis que `_stop_mode`
        libère l'inlet dès le dernier écouteur arrêté ; il reste écrit juste, parce qu'un garde
        qui ne tient que par un autre garde ne tient pas.
        """
        if len(self._marqueurs) <= 4096:
            return
        ecouteurs = [mode_id for mode_id, rt in self.active.items()
                    if rt.spec.marker_epoch_s > 0.0]
        if not ecouteurs:
            print(f"[server] marqueurs entrants : {len(self._marqueurs)} marqueur(s) jetés — "
                  f"aucun mode actif ne les écoute plus.")
            self._marqueurs = []
            self._marqueur_curseur = {}
            return
        coupe = min(self._marqueur_curseur.get(mode_id, 0) for mode_id in ecouteurs)
        if coupe > 2048:
            self._marqueurs = self._marqueurs[coupe:]
            # `max(0, ...)` : les curseurs des modes NON écouteurs (un mode arrêté dont l'entrée
            # traînerait, un mode dont le `marker_epoch_s` serait passé à 0) n'entrent pas dans
            # le calcul de `coupe` et peuvent donc être plus PETITS qu'elle. Un index négatif ne
            # lève pas en Python : il repart de la FIN de la liste, et ce mode relirait alors la
            # queue du tampon comme si elle était neuve.
            self._marqueur_curseur = {k: max(0, v - coupe)
                                      for k, v in self._marqueur_curseur.items()}

    def markers_murs(self, mode_id, post_s):
        """Les marqueurs de CE mode dont l'époque tient entièrement dans le tampon.

        « Mûr » = le tampon couvre déjà les `post_s` secondes qui SUIVENT le marqueur. Avant,
        l'époque déborderait et le découpage rendrait None — sans rien dire. Cette attente est
        générique, donc elle vit ici : chaque mode qui la réimplémenterait la referait un peu
        différemment.

        Chaque marqueur n'est rendu qu'une fois par mode (curseur par mode). Ceux d'un autre
        mode sont sautés en silence : c'est le SEUL rejet muet autorisé, parce qu'il est normal.
        """
        if not len(self.recent_ts):
            return []
        plus_vieux, plus_recent = float(self.recent_ts[0]), float(self.recent_ts[-1])
        i = self._marqueur_curseur.get(mode_id, 0)
        murs = []
        while i < len(self._marqueurs):
            ts, d = self._marqueurs[i]
            # Le futur d'ABORD : un marqueur aberrant ne doit jamais pouvoir coincer la file
            # derrière lui. Un horodatage très en avance est la signature du `time_correction()`
            # oublié entre deux machines — on le compte, on le saute, et la séance continue.
            #
            # ⚠️ L'ordre inverse (maturité d'abord) a deux défauts d'un coup : un marqueur
            # horodaté loin dans le futur n'est PAR DÉFINITION jamais « mûr », donc il déclenche
            # le `break` juste en dessous AVANT d'atteindre ce contrôle — `marqueurs_futurs`
            # devient inatteignable, et pire, le curseur ne le dépasse jamais : ce marqueur reste
            # indéfiniment le premier examiné, et tout ce qui arrive après lui dans la file
            # (y compris des marqueurs parfaitement valides) reste bloqué derrière, pour
            # toujours. Prouvé par mutation dans `_smoke_marqueurs_file_coincee`.
            if ts > plus_recent + MARKER_LATE_S:
                self.marqueurs_futurs += 1
                i += 1
                continue
            if ts + post_s > plus_recent:
                # Pas encore mûr, et les suivants le sont encore moins : on s'arrête ici SANS
                # avancer le curseur — ce marqueur sera réexaminé au prochain tour.
                break
            i += 1
            if d.get("mode") != mode_id:
                continue
            if ts < plus_vieux:
                self.marqueurs_perdus += 1
                continue
            murs.append((ts, d))
        self._marqueur_curseur[mode_id] = i
        return murs

    def _publish_quality(self, lsl_ts):
        """σ par voie sur les dernières secondes, calculé sur du signal FILTRÉ.

        Le filtrage est indispensable ICI (contrairement au flux brut) : sur du signal
        quasi-brut, le σ est dominé par le ronflement secteur 50 Hz et la dérive lente des
        électrodes sèches, pas par l'EEG — un σ mesuré ainsi ne dit rien de l'état du contact.

        Le calcul est délégué à `sigma_from_block` pour partager UNE seule définition du σ
        avec l'écran `signal_check` de l'appli : deux mesures de qualité qui divergeraient
        seraient pires que pas de mesure du tout.

        ⚠️ On ne passe PAS `self.recent` en entier : ce tampon est dimensionné (`self.keep`,
        cf. `__init__`) pour le plus gourmand de TOUS ses consommateurs — aujourd'hui la
        calibration MI, qui prélève des époques de 4 s là où cette fenêtre de qualité n'en veut
        que `QUALITY_WINDOW_S` (2 s). Passer le tampon entier mesurait donc le σ sur `self.keep`
        (4 s dès que le MI est calibrable), un couplage NON borné : demain un `epoch_s` de
        calibration plus long élargirait encore la fenêtre de qualité SANS que rien ne le dise
        — un flux PUBLIC, consommé par n'importe quel client. On borne donc explicitement le
        bloc à la fenêtre déclarée plus sa marge de filtre, comme le font déjà tous les autres
        lecteurs du tampon (`recent_window`, `motor_window`, `occipital_window`…) : `_publish_
        quality` était le seul à consommer le tampon entier.
        """
        n = int(round(QUALITY_WINDOW_S * self.acq.fs)) + self.acq.margin_n
        bloc = self.recent[-n:]
        sigmas = self.acq.sigma_from_block(bloc)
        if sigmas is None:
            return
        self.quality_out.push(sigmas, lsl_ts)
        # Référence décrochée : invisible sur les σ, fatale pour la séance. On le dit
        # une fois par changement d'état plutôt qu'à chaque seconde.
        common = self.acq.common_mode(bloc)
        # Sur le board de test il n'y a aucune électrode : un verdict sur la référence y serait
        # un contresens. On publie la mesure (honnête) mais jamais le verdict.
        lost = reference_lost(common) and not self.synthetic
        # `None` plutôt que NaN partout : l'état part en JSON, où NaN n'existe pas et fait
        # échouer la sérialisation entière (page blanche au lieu d'une valeur manquante).
        self._quality = {
            "sigmas": [json_float(v) for v in sigmas],
            "verdicts": [verdict_from_sigma(float(v)) for v in sigmas],
            "common_mode": json_float(common, digits=3),
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

    def run(self, duration_s=None, baseline_s=None, warmup_s=None):
        """Boucle principale. `duration_s=None` = jusqu'à Ctrl+C.

        `baseline_s` / `warmup_s` à None = les durées PROPRES À CHAQUE MODE, posées par son
        contrat. Les passer explicitement les remplace, pour tous les modes — ce dont les tests
        headless ont besoin pour ne pas durer 40 s chacun.
        """
        self._warmup_override = warmup_s
        self._rest_override = baseline_s
        # Le moteur écrit des µ, des σ et des accents. Sous PowerShell, stdout est en cp1252 par
        # défaut : un simple print tuait alors le fil d'acquisition sur un UnicodeEncodeError. On
        # le fait ici plutôt que dans le seul `__main__`, parce que le moteur est aussi utilisé
        # comme bibliothèque (console, tests) — et qu'un échec d'AFFICHAGE ne doit jamais
        # interrompre une ACQUISITION.
        use_utf8_console()

        started = time.perf_counter()
        last_quality = last_status = 0.0

        with self.acq:
            print(f"[server] board={self.acq.board_id.name} fs={self.acq.fs} Hz "
                  f"instance={self.instance}")
            for suffix in ("quality", "status"):
                print(f"[server] flux LSL publie : {stream_name(suffix)}")
            try:
                # `_start` est DANS le `try`, et pas avant : un constructeur de runtime peut lever
                # — celui du MI le fait PAR CONCEPTION quand le modèle a disparu entre la
                # validation et le démarrage. Or le `finally` plus bas n'est pas un nettoyage
                # optionnel : c'est lui qui casse le cycle `active ↔ engine`, sans quoi un
                # `BoardShim.__del__` tardif libère la session d'un AUTRE moteur (voir son long
                # commentaire). Le sauter parce qu'un mode n'a pas su démarrer ferait payer
                # l'incident au moteur SUIVANT du même processus.
                self._start([s.id for s, _ in self._pending],
                            {s.id: v for s, v in self._pending}, time.perf_counter())
                self.status_out.push(self._state(True, calibration=self.calibration),
                                     key=self._status_key(True), force=True)

                while not self._stop:
                    self._drain_commands()
                    now = time.perf_counter()
                    if duration_s is not None and now - started >= duration_s:
                        break

                    # Réévalué à CHAQUE tour — voir la docstring de `_ouvre_marker_inlet` pour
                    # pourquoi une évaluation UNIQUE avant le `while` ne suffit pas.
                    self._ouvre_marker_inlet()

                    # UNE seule lecture par tour, quels que soient les modes actifs :
                    # `get_new_data()` VIDE le tampon de BrainFlow. C'est l'invariant central du
                    # moteur — c'est aussi pourquoi le tampon glissant est tenu ICI et pas là-bas.
                    eeg, ts_unix = self.acq.get_new_data()
                    self.new_block = None
                    if eeg is not None and len(eeg):
                        ts_lsl = self.clock.to_lsl(ts_unix)
                        self.new_block = (eeg, ts_lsl)
                        self.recent = np.vstack([self.recent, eeg])[-self.keep:]
                        self.recent_ts = np.concatenate([self.recent_ts, ts_lsl])[-self.keep:]

                    self._tire_marqueurs()

                    if now - last_quality >= QUALITY_PERIOD_S:
                        self._publish_quality(self.clock.to_lsl(time.time()))
                        last_quality = now

                    for mode_id, runtime in list(self.active.items()):
                        if now - self._last_tick.get(mode_id, 0.0) >= runtime.period_s():
                            runtime.tick(self, self.clock.to_lsl(time.time()), now)
                            self._last_tick[mode_id] = now

                    # La calibration tourne à CHAQUE tour, sans période minimale : sa ligne du
                    # temps se compte en dixièmes de seconde et un décompte qui saute serait vu.
                    if self.calibration is not None and not self.calibration.terminee:
                        try:
                            self.calibration.tick(self, now)
                        except Exception as e:  # noqa: BLE001 - un tick fautif ne doit tuer NI
                            # le moteur NI la séance en cours des AUTRES modes : on perd cette
                            # calibration (potentiellement plusieurs minutes d'imagerie), pas le
                            # reste. Marquer « annulé » avec sa raison est ce que `_terminer` fait
                            # déjà pour un entraînement qui lève ; un tick qui lève méritait le
                            # même traitement, pas un crash du processus entier.
                            self.calibration.probleme = f"{type(e).__name__} : {e}"
                            self.calibration.phase = "annule"
                            print(f"[server] calibration interrompue par une exception : "
                                  f"{self.calibration.probleme}")

                    # Publié quand l'état change, plus un rappel périodique pour les clients qui
                    # se connectent après le démarrage (LSL ne rejoue pas le passé).
                    due = now - last_status >= STATUS_PERIOD_S
                    if self.status_out.push(self._state(True, calibration=self.calibration),
                                            key=self._status_key(True), force=due) and due:
                        last_status = now

                    time.sleep(POLL_S)

                self.status_out.push(self._state(False, calibration=self.calibration),
                                     key=self._status_key(False), force=True)
            finally:
                # DOIT s'exécuter sur TOUTE sortie de la boucle, y compris une EXCEPTION — casque
                # perdu en séance, erreur BrainFlow : précisément ce que ce produit doit survivre.
                # Sans ce `finally`, une exception levée par `get_new_data()` ou par un `tick()`
                # saute tout ce bloc et va droit à `__exit__` : ni les flux ne se ferment, ni le
                # cycle plus bas ne se rompt. Le bug revient alors pour le PROCHAIN moteur du même
                # processus — au pire moment, celui où on relance juste après l'incident.
                for runtime in self.active.values():
                    try:
                        runtime.close()
                    except Exception as e:  # noqa: BLE001 - la fermeture d'UN flux ne doit pas
                        # empêcher les autres de se libérer.
                        print(f"[server] fermeture de {runtime.spec.label} en erreur : {e}")
                # Un `ModeRuntime` garde `self.engine` : `self.active` référence donc `self`, qui
                # référence `self.active` — un cycle. CPython ne le casse pas par comptage de
                # références, seulement par un passage du ramasse-miettes CYCLIQUE, à une date
                # que rien ici ne contrôle.
                #
                # Ce que le cycle retarde n'est PAS la session BrainFlow : `UnicornAcquisition.
                # __exit__`, juste en dessous, la libère bel et bien tout de suite. Ce qu'il
                # retarde, c'est le nettoyage de l'OBJET PYTHON `BoardShim` — et donc l'appel de
                # son destructeur `__del__`, qui rappelle `release_session()` si `is_prepared()`
                # répond vrai. Le piège tient dans COMMENT BrainFlow identifie une session :
                # `prepare_session`, `release_session` et `is_prepared` passent tous
                # `(self.board_id, self.input_json)` au MÊME singleton `BoardControllerDLL.
                # get_instance()`, un objet DLL partagé par tout le PROCESSUS — jamais par
                # identité d'objet Python (vérifié dans brainflow/board_shim.py). Deux moteurs
                # synthétiques — ou deux vrais casques de même numéro de série — adressent donc
                # la MÊME clé.
                #
                # Quand le ramasse-miettes finit par appeler `__del__` sur le `BoardShim` du
                # PREMIER moteur, `is_prepared()` répond sur CETTE clé — et si un DEUXIÈME
                # moteur a, entre-temps, préparé sa propre session sous la même clé, la réponse
                # est vraie pour LA SESSION DU DEUXIÈME. Le destructeur zombie du premier appelle
                # alors `release_session()` et libère la session du second, en pleine séance :
                # ce n'est pas une session qui traîne, c'est un destructeur qui se trompe de
                # cible. Mesuré le 2026-07-28 : deux `EngineServer` synthétiques lancés l'un
                # après l'autre dans le même processus, le second échoue sur `get_new_data()`
                # avec `BOARD_NOT_CREATED_ERROR`.
                #
                # Vider `active` casse le cycle : `self` (et son `BoardShim`) redevient
                # collectable par simple comptage de références, donc nettoyé tout de suite —
                # avant qu'un `__del__` tardif ait la moindre chance de viser la mauvaise
                # session. Sans ce test-là (deux moteurs de suite, comme le fait `--smoke`),
                # rien ne révèle le problème : un seul moteur par processus ne le voit jamais.
                #
                # Une calibration en cours ne survit pas à l'arrêt du moteur : elle tient des
                # époques en mémoire et une référence vers `self` — le même cycle que les modes.
                if self.calibration is not None:
                    self.calibration.cancel()
                    self.calibration = None
                self.active = {}
                # APRÈS `self.active = {}`, jamais avant : `_libere_marker_inlet` ne lâche que
                # s'il ne reste plus un seul écouteur, et c'est cette ligne-là qui le garantit.
                # Un moteur arrêté n'a plus rien à écouter — garder un inlet LSL ouvert après la
                # boucle, c'est exactement l'habitude que ce chantier corrige partout ailleurs.
                self._libere_marker_inlet("le moteur s'arrête")

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
    server = EngineServer(synthetic=True, instance=instance)               # inchangé (raw seul)

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
        span = float(stamps[-1] - stamps[0])
        # Cadence sur la DURÉE TOTALE, pas la médiane des écarts. Le board synthétique livre
        # par RAFALES (mesuré : écarts de 6 µs à 20 ms, médiane 15 µs, moyenne 4001 µs), donc
        # une médiane d'écart mesure la gigue de livraison et non le débit — elle s'effondre
        # dès que la machine est chargée. Ce contrôle vise un timestamp mal CONVERTI (pont
        # d'horloge cassé), pas un problème de débit : la cadence moyenne le dit, pas la médiane.
        rate = (len(stamps) - 1) / span if span > 0 else 0.0
        print(f"[smoke] cadence mesurée {rate:.1f} Hz, plus grand trou {gaps.max() * 1000:.1f} ms")
        # Le board synthétique tourne à 250 Hz nominal comme l'Unicorn ; un écart franc
        # signalerait un timestamp mal converti, pas un problème de débit.
        if not 200.0 < rate < 300.0:
            print("[smoke] ÉCHEC : cadence incohérente avec les 250 Hz annoncés")
            ok = False

    print(f"[smoke] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    # Le contrat et le registre d'abord : un défaut là-dedans explique tous les suivants, et
    # c'est instantané.
    integre, defauts = registry.check()
    for d in defauts:
        print(f"[smoke-registry] ÉCHEC : {d}")
    print(f"[smoke-registry] {len(registry.MODES)} modes, "
          f"dont {len(registry.runnable())} dans le moteur — "
          f"{'OK' if integre else 'PROBLÈME'}")
    # ⚠️ Chaque sous-test est appelé INCONDITIONNELLEMENT, dans une LISTE — pas dans un `and` en
    # cascade. Un `and` court-circuite : dès le premier `False`, Python n'appelle même plus les
    # suivants, qui restent alors muets. Un seul test instable (timing réseau, SSVEP…) masquait
    # ainsi SILENCIEUSEMENT tous les tests placés après lui dans la chaîne — déjà rencontré sur ce
    # projet. En construisant la liste d'abord, chaque appel s'exécute et imprime son propre
    # VERDICT quoi qu'il arrive ; `all()` ne fait que COMBINER des résultats déjà obtenus, donc un
    # échec en signale un seul, jamais plus.
    resultats = [
        ok,
        integre,
        _smoke_frontiere(),
        _smoke_repos_partage(),
        _smoke_ssvep(),
        _smoke_neuro(),
        _smoke_mi(),
        _smoke_calibration(),
        _smoke_calibration_refus(),
        _smoke_cumul(),
        _smoke_proposition(),
        _smoke_dimensionnement(),
        _smoke_tampon_horodate(),
        _smoke_marqueurs_murs(),
        _smoke_marqueurs_file_coincee(),
        _smoke_marqueurs_inlet(),
        _smoke_marqueurs_relance(),
        _smoke_marqueurs_stream_in(),
    ]
    return all(resultats)


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
    server = EngineServer(synthetic=True, modes=("raw", "neuro"), instance=instance)
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

    # Les fréquences viennent de `choose_frequencies`, comme celles du mode et celles du
    # stimulus. Le littéral arrondi 8.57 qui était ici n'est PAS un diviseur entier de 60 Hz
    # (60/8.57 = 7,0012, soit un millier de fois la tolérance) : il passait tant que personne ne
    # le vérifiait, et il tombe maintenant que la contrainte `divise_le_refresh` existe. Repasser
    # par la fonction supprime la classe entière du problème plutôt que ce cas-là.
    freqs = [c["actual_hz"] for c in choose_frequencies(60.0)]
    instance = "smoke-ssvep"
    server = EngineServer(synthetic=True, modes=("raw", "ssvep"),
                          params={"ssvep": {"freqs": freqs}}, instance=instance)
    thread = threading.Thread(
        target=server.run,
        kwargs={"duration_s": 14.0, "baseline_s": 3.0, "warmup_s": 1.0}, daemon=True)
    thread.start()

    # Le flux doit exister DÈS le démarrage, avant même la fin du repos : c'est ce qui
    # permet à un client de le trouver au lancement (cf. modes/ssvep.py). Un délai court
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


def _smoke_mi():
    """Le mode MI de bout en bout, sans casque : un modèle entraîné à la volée, puis le flux.

    Le modèle est écrit dans `data/` sous un nom réservé, puis retiré : le mode découvre ses
    choix dans ce dossier, donc un modèle ailleurs ne serait pas proposable. Le `finally` est
    obligatoire — un `mi_model_smoke.joblib` oublié se retrouverait proposé à l'étudiant — et il
    doit couvrir l'ÉCRITURE du fichier ET la construction du serveur : `EngineServer.__init__`
    lève PAR CONCEPTION dès qu'un réglage est invalide (« lève ici, au démarrage — bruyamment et
    tout de suite », cf. sa docstring), et peut aussi lever si la session BrainFlow refuse de
    s'ouvrir. Sans cette couverture, une levée à cet endroit laisserait le fichier orphelin —
    exactement ce que ce `finally` existe pour empêcher. `server`/`thread` sont donc initialisés
    à `None` AVANT le `try`, pour que le `finally` puisse s'exécuter même si `EngineServer(...)`
    n'a jamais rendu la main, sans jamais lire une variable non assignée.

    Comme pour le SSVEP et le neuro (cf. leurs docstrings), on ne juge PAS la justesse du
    décodage : le board synthétique n'émet aucune vraie imagerie motrice. On vérifie le
    CÂBLAGE — le flux existe, porte le bon nombre de voies, publie en continu, ses valeurs
    restent finies et somment à 1, et le décodeur LIT vraiment la fenêtre qu'on lui passe (les
    probabilités varient d'un échantillon à l'autre) plutôt que de republier une valeur figée.
    """
    import threading

    from core.config import DATA_DIR
    from core.mi_decoder import MI_LABELS, MIModel, synth_mi_trial

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    chemin = os.path.join(DATA_DIR, "mi_model_smoke.joblib")
    os.makedirs(DATA_DIR, exist_ok=True)
    server = None
    thread = None
    try:
        rng = np.random.default_rng(0)
        epochs, y = [], []
        for label in MI_LABELS:
            for _ in range(8):
                epochs.append(synth_mi_trial(label, rng=rng))
                y.append(label)
        MIModel(fs=250.0).fit(np.asarray(epochs), np.asarray(y)).save(chemin)

        instance = "smoke-mi"
        server = EngineServer(synthetic=True, modes=("mi",), params={"mi": {"model": chemin}},
                              instance=instance)
        thread = threading.Thread(target=server.run,
                                 kwargs={"duration_s": 12.0, "baseline_s": 0.0, "warmup_s": 1.0},
                                 daemon=True)
        thread.start()
        info = _resolve_own("decoded_mi", instance, timeout=15.0)
        chk(info is not None, "le flux decoded_mi est publié")
        if info is not None:
            chk(info.channel_count() == 2 + len(MI_LABELS),
                f"5 voies : intent_index, confidence, et une par classe ({info.channel_count()})")
            from pylsl import StreamInlet
            inlet = StreamInlet(info)
            inlet.open_stream(timeout=5.0)

            # Les MÉTADONNÉES relues sur le flux réel, comme le fait `_smoke_neuro` : compter les
            # voies ne prouve rien sur leurs NOMS, et ce sont les noms que le client lit. Un
            # `mi_channel_labels` correct câblé sur de mauvaises `classes` publierait cinq voies
            # bien nommées pour un modèle qui n'a pas ces classes-là — invisible à un compte.
            etiquettes, noeud = [], inlet.info().desc().child("channels").child("channel")
            while not noeud.empty():
                etiquettes.append(noeud.child_value("label"))
                noeud = noeud.next_sibling()
            decodage = inlet.info().desc().child("decoding")
            echelle = decodage.child_value("decision_scale")
            sans_decision = decodage.child_value("no_decision_index")
            repos = decodage.child_value("rest_index")
            attendues = mi_channel_labels(MI_LABELS)
            chk(etiquettes == attendues,
                f"les voies annoncées sont celles du contrat ({etiquettes})")
            chk(echelle == "proba",
                f"l'échelle de décision annoncée est « proba », pas le z du SSVEP ({echelle!r})")
            # « Je ne sais pas » et « la personne se repose » sont la confusion la plus coûteuse
            # du mode : les deux indices doivent voyager dans les métadonnées, et être DIFFÉRENTS.
            chk(sans_decision == "-1" and repos == str(MI_LABELS.index("REPOS")),
                f"le flux dit lui-même ce que valent « aucune décision » et « repos » "
                f"(no_decision_index={sans_decision!r}, rest_index={repos!r})")
            recus, indices, probas_vues = 0, set(), set()
            fin = time.perf_counter() + 8.0
            while time.perf_counter() < fin:
                echantillon, _ts = inlet.pull_sample(timeout=1.0)
                if echantillon is None:
                    continue
                recus += 1
                # `math.isfinite` d'abord : une comparaison AVEC un NaN rend toujours False
                # (sémantique IEEE-754), donc le contrôle de somme juste en dessous ne verrait
                # JAMAIS un NaN passer — exactement comme `_smoke_neuro` s'en protège déjà.
                if not all(math.isfinite(v) for v in echantillon):
                    chk(False, f"toutes les valeurs publiées sont finies (reçu {list(echantillon)})")
                    break
                indices.add(int(round(echantillon[0])))
                probas_vues.add(tuple(echantillon[2:]))
                somme = sum(echantillon[2:])
                if abs(somme - 1.0) > 1e-2:
                    chk(False, f"les probabilités doivent sommer à 1 (reçu {somme:.3f})")
                    break
            chk(recus >= 10, f"des décisions arrivent en continu ({recus} en 8 s)")
            chk(all(-1 <= i < len(MI_LABELS) for i in indices),
                f"tous les indices sont dans les bornes ({sorted(indices)})")
            # Ne prouve PAS la justesse du décodage (cf. docstring) : prouve que le décodeur LIT
            # la fenêtre qu'on lui passe. Le tampon glissant change en continu ; un décodeur
            # sourd à son entrée, ou qui republierait une valeur figée, donnerait toujours le
            # MÊME jeu de probabilités — ce que la seule borne sur les indices ne peut pas voir
            # (elle passerait même avec indices == {-1} tout seul).
            chk(len(probas_vues) > 1,
                f"les probabilités varient d'un échantillon à l'autre — signe que le décodeur "
                f"lit la fenêtre, pas qu'il republie une valeur figée ({len(probas_vues)} "
                f"jeu(x) distinct(s) sur {recus} échantillons)")
    finally:
        # Le retrait du fichier PASSE EN PREMIER, et le `join` ne s'exécute que sur un fil
        # réellement démarré. `thread.join()` sur un fil jamais démarré lève `RuntimeError` :
        # dans l'ordre inverse, un `thread.start()` en échec sautait le `os.remove` et laissait
        # `mi_model_smoke.joblib` dans le VRAI `data/`, donc proposé à l'étudiant au prochain
        # lancement de la console — précisément ce que ce `finally` existe pour empêcher.
        if os.path.exists(chemin):
            os.remove(chemin)
        if server is not None:
            server.stop()
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)

    print(f"[smoke-mi] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_calibration():
    """Une calibration MI complète, jouée par le VRAI moteur sur board synthétique.

    Ce que ce test couvre et qu'aucun autre ne peut : la calibration tourne dans la boucle du
    moteur, prélève dans le tampon glissant RÉEL (donc éprouve le dimensionnement de `keep`), et
    produit un modèle que `modeles_disponibles` retrouve. L'autotest de `mi_calib.py`, lui, joue
    la même séance sur un faux moteur : il valide le protocole, pas l'intégration.

    Tout est écrit dans un dossier temporaire. Le vrai `data/` n'est jamais approché.
    """
    import shutil
    import tempfile
    import threading

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    from core.modes import mi_calib

    dossier = tempfile.mkdtemp(prefix="srv_calib_")
    # On raccourcit le protocole POUR LE TEST en remplaçant les durées sur la classe : c'est la
    # seule façon de jouer une séance de sept minutes en quelques secondes sans donner à
    # `CalibrationRuntime` une horloge accélérée, qui serait un chemin de code que la séance
    # réelle n'emprunte jamais.
    anciens = {c: getattr(mi_calib.MICalibration, c)
               for c in ("cue_s", "imagery_s", "rest_s", "warmup_s", "warmup_per_class",
                         "window_s", "step_s")}
    ancien_init = mi_calib.MICalibration.__init__

    def _init_temporaire(self, spec, params, engine, rng=None, dossier=dossier):
        ancien_init(self, spec, params, engine, rng=rng, dossier=dossier)

    try:
        # ⚠️ `window_s` et `step_s` sont raccourcis AVEC `imagery_s`, pas séparément : avec une
        # imagerie de 0,20 s et une fenêtre restée à 2 s, `decouper` ne rend AUCUNE fenêtre et
        # l'entraînement refuse. Le rapport est conservé — 0,32 / 0,16 / 0,08 donne 3 fenêtres
        # par essai, comme 4 / 2 / 1 en séance réelle.
        #
        # ⚠️ ÉCART AU BRIEF (documenté dans le rapport de tâche) : le brief proposait 0,20 / 0,10 /
        # 0,05. Ça respecte la règle ci-dessus (le rapport 0,5 / 0,25 est conservé) mais ÉCHOUE
        # quand même — `MIModel.fit` passe chaque fenêtre dans un filtre passe-bande 0-phase
        # (`scipy.signal.filtfilt`, ordre 4), qui EXIGE plus d'échantillons que son `padlen`
        # (27, mesuré : `3 * (2*ordre+1)`). Une fenêtre de 0,10 s à 250 Hz ne fait que 25
        # échantillons — sous le plancher — et l'entraînement lève AVANT même d'atteindre la
        # comparaison honnête/naïve. 0,32 s donne une fenêtre de 40 échantillons, confortablement
        # au-dessus. Le seuil du brief n'est donc pas juste inconfortable : il est INFAISABLE tel
        # quel avec le filtre réellement utilisé par `MIModel`.
        mi_calib.MICalibration.cue_s = 0.05
        mi_calib.MICalibration.imagery_s = 0.32
        mi_calib.MICalibration.rest_s = 0.05
        mi_calib.MICalibration.warmup_s = 0.10
        mi_calib.MICalibration.warmup_per_class = 1
        mi_calib.MICalibration.window_s = 0.16
        mi_calib.MICalibration.step_s = 0.08
        mi_calib.MICalibration.__init__ = _init_temporaire

        server = EngineServer(synthetic=True, modes=("raw",), instance="smoke-calib")
        # 120 s, pas 60 : la séance mesure ~27 s mais le PAS de boucle (POLL_S, plus la latence
        # des E/S) ajoute couramment ~8,5 s de plus sur ce poste, et un dépassement de
        # `duration_s` arrête le moteur EN PLEINE séance — un échec de timing du test, pas de la
        # calibration elle-même. Large marge plutôt qu'un ajustement fin.
        thread = threading.Thread(target=server.run, kwargs={"duration_s": 120.0}, daemon=True)
        thread.start()
        try:
            # Laisser le tampon se remplir : sans ça les premières époques seraient trop courtes
            # et le moteur les ignorerait (il le dit, mais le test doit passer sans ce cas).
            # ⚠️ Attendre « non-None » ne suffit PAS : `recent_window` rend ce qu'elle a dès le
            # premier échantillon, sans dire qu'il en manque. On attend la LONGUEUR voulue.
            besoin_amorce = int(round(mi_calib.MICalibration.imagery_s * server.acq.fs))
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 10.0:
                bloc = server.recent_window(mi_calib.MICalibration.imagery_s)
                if bloc is not None and len(bloc) >= besoin_amorce:
                    break
                time.sleep(0.1)

            # ⚠️ ÉCART AU BRIEF, documenté dans le rapport de tâche : « Essais par classe » est un
            # « choice » borné à MI_SESSIONS = (10, 14, 18, 26) (core/config.py), pas un entier
            # libre — 6 (la valeur du brief) est refusé par `contract.validate`. Le plus PETIT
            # choix valide, 10, est ACCEPTÉ mais rend la comparaison honnête/naïve juste plus bas
            # peu fiable sur du bruit pur (mesuré : ~1 essai sur 2 viole l'invariant sur 4 tirages
            # répétés) — la fenêtre d'entraînement n'a alors aucun signal réel à apprendre, contrairement
            # aux autotests de mi_calib.py/mi_decoder.py qui fabriquent une ERD. 18 (3e choix) ramène
            # ça à ~1 tirage sur 6 dans les mêmes conditions, pour un coût en temps encore raisonnable.
            # Deux `start_calibration` soumis dans la MÊME fenêtre de sondage (avant que la
            # boucle n'ait drainé le premier) doivent produire UNE SEULE calibration, pas deux
            # qui se chevauchent. `submit()` ne peut PAS voir venir cette course :
            # `self.calibration` est encore `None` pour LES DEUX au moment où elles sont
            # soumises — c'est la garde côté BOUCLE (`_start_calibration`) qui compte. Les deux
            # commandes partent donc DOS À DOS, sans attendre entre les deux : une version
            # antérieure de ce test attendait `server.calibration is not None` avant la seconde,
            # ce qui contournait exactement la fenêtre de course qu'il prétendait couvrir.
            ack = server.submit("start_calibration", id="mi", params={"trials_per_class": 18})
            ack_course = server.submit("start_calibration", id="mi", params={"trials_per_class": 10})
            chk(ack.get("accepted"), f"la première calibration est acceptée ({ack})")
            chk(ack_course.get("accepted"),
                f"submit() ne peut pas refuser la seconde : rien n'est encore appliqué à cet "
                f"instant ({ack_course})")

            t0 = time.perf_counter()
            while server.calibration is None and time.perf_counter() - t0 < 5.0:
                time.sleep(0.05)
            chk(server.calibration is not None
                and server.calibration.params.get("trials_per_class") == 18,
                f"mais côté BOUCLE, la seconde est ignorée : c'est bien la PREMIÈRE (18) qui "
                f"tourne, pas la seconde (10) "
                f"({None if server.calibration is None else server.calibration.params})")

            # Une fois la première APPLIQUÉE, cette fois `submit()` lui-même la voit et refuse —
            # le scénario que l'ancienne version de ce test croyait déjà couvrir.
            refus = server.submit("start_calibration", id="mi", params={})
            chk(not refus.get("accepted") and "déjà en cours" in (refus.get("reason") or ""),
                f"une troisième, soumise APRÈS coup, est refusée par submit() lui-même ({refus})")
            chk(server.phase == "calibrating",
                f"la phase publique du moteur devient « calibrating » ({server.phase})")
            etat = server.snapshot().get("calibration")
            chk(etat is not None and etat["mode_id"] == "mi" and etat["total"] == 54,
                f"et snapshot() porte l'état complet, celui de la PREMIÈRE (18×3=54) ({etat})")

            # Bornes ÉLARGIES par rapport au brief (25 s), pour la même raison que trials_per_class
            # ci-dessus : 18 essais/classe jouent 54 essais au lieu de 18, à ~0,42 s/essai avec les
            # durées raccourcies — mesuré ~27 s de bout en bout. 45 s laisse une marge confortable.
            t0 = time.perf_counter()
            while (server.calibration is not None and not server.calibration.terminee
                   and time.perf_counter() - t0 < 45.0):
                time.sleep(0.1)

            calib = server.calibration
            chk(calib is not None and calib.phase == "fini",
                f"la séance aboutit ({None if calib is None else calib.phase} ; "
                f"problème={None if calib is None else calib.probleme!r})")
            res = (calib.resultat if calib else None) or {}
            chk(res.get("n_essais") == 54, f"54 essais enregistrés ({res.get('n_essais')})")

            # Les époques prélevées dans le VRAI tampon glissant font la longueur annoncée.
            # ⚠️ `calib` peut être None ici : le `chk` ci-dessus ne court-circuite PAS (il imprime
            # et continue) — sur un build réellement cassé, déréférencer `calib._enregistre` sans
            # garde donnerait une trace Python brute au lieu du diagnostic ligne à ligne que ce
            # smoke doit rendre jusqu'au bout.
            attendu = int(round(mi_calib.MICalibration.imagery_s * server.acq.fs))
            longueurs = {len(e) for e, _l in calib._enregistre} if calib is not None else set()
            chk(longueurs == {attendu},
                f"chaque époque fait exactement {attendu} échantillons ({sorted(longueurs)})")

            # ⚠️ ET LE VRAI TEST DU DÉFAUT — celui-ci ne dépend PAS de la séance jouée, qui
            # tourne sur des durées rabotées. Le tampon du moteur doit tenir la plus longue
            # époque que le CONTRAT annonce (`Calib.epoch_s` = 4 s pour le MI), pas seulement la
            # fenêtre de décodage (2 s). Sans ce terme dans `keep`, chaque époque d'une séance
            # RÉELLE serait tronquée de moitié — sans erreur, avec un tiers des fenêtres
            # d'entraînement attendues. Deux vérifications, parce qu'aucune ne suffit seule :
            # le dimensionnement calculé, et le bloc réellement rendu.
            from core.config import MI_IMAGERY_S

            besoin = int(round(MI_IMAGERY_S * server.acq.fs))
            chk(server.keep >= besoin + server.acq.margin_n,
                f"le tampon du moteur tient une époque de calibration entière : keep="
                f"{server.keep} pour {besoin} + marge {server.acq.margin_n}")
            bloc = server.recent_window(MI_IMAGERY_S)
            chk(bloc is not None and len(bloc) == besoin,
                f"et il en rend une COMPLÈTE : {0 if bloc is None else len(bloc)} échantillons "
                f"pour {besoin} demandés")

            from core import mi_models

            produits = mi_models.modeles_disponibles(dossier)
            chk(len(produits) == 1 and produits[0] == res.get("modele"),
                f"le modèle produit est chargeable et listé ({produits})")
            # Que la CV honnête soit RAPPORTÉE est un fait déterministe — une vraie propriété du
            # chantier — donc reste une assertion. Que cv_groupee < cv_naive, en revanche, n'EN
            # est plus une : `_smoke_calibration` entraîne sur le bruit RÉEL du board synthétique
            # (c'est tout l'intérêt du test), donc sans aucun signal appris, l'ORDRE des deux CV
            # est un tirage — mesuré ~1 échec sur 6 même à 18 essais/classe. Conclure sur du bruit
            # est justement ce que ce projet interdit (CLAUDE.md, « rigueur statistique »).
            # L'invariant reste vérifié, lui, là où il a un sens : sur de l'ERD FABRIQUÉE, par
            # `mi_calib._selftest()` et `mi_decoder._test_cv_honnete()` — pas abandonné ici, mesuré
            # au bon endroit. On imprime donc les deux chiffres pour mémoire, sans en juger l'ordre.
            chk(res.get("cv_groupee") is not None,
                f"l'accuracy HONNÊTE (validation croisée par essai) est rapportée "
                f"({res.get('cv_groupee')})")
            print(f"[smoke-calib] pour mémoire, PAS une assertion (cf. commentaire ci-dessus) : "
                  f"cv_groupee={res.get('cv_groupee')} cv_naive={res.get('cv_naive')}")

            # Et le mode MI peut alors démarrer sur ce modèle : c'est tout l'objet du chantier.
            #
            # ⚠️ ÉCART AU BRIEF, documenté dans le rapport de tâche : le Param « model » de
            # `mi.SPEC` résout ses choix via `mi_models.modeles_disponibles()` SANS argument,
            # donc contre le VRAI `data/` — jamais le dossier temporaire de ce test. Sans
            # redirection, `start_mode` refuserait TOUJOURS avec « aucun choix disponible », même
            # juste après l'entraînement : le brief demande à la fois « ne jamais toucher data/ »
            # et « le mode démarre sur le modèle produit », deux exigences incompatibles sans ce
            # monkeypatch — le même que `core/modes/mi.py::_selftest` utilise pour la même raison.
            # `contract.validate` (donc `choices_fn`) tourne DANS `submit`, sur CE fil, de façon
            # SYNCHRONE : la redirection n'a besoin de vivre que le temps de cet appel — la suite
            # (`MIRuntime.__init__`) charge le modèle par CHEMIN direct (`mi_models.charger`), qui
            # ne consulte jamais `modeles_disponibles`.
            vrai_disponibles = mi_models.modeles_disponibles
            mi_models.modeles_disponibles = lambda d=dossier: vrai_disponibles(d)
            try:
                # `if produits else ...` : pas pour éviter un faux vert (un build réellement
                # cassé échoue de toute façon, `produits` serait déjà vide plus haut) mais pour
                # la règle que ce fichier s'est donnée pour le `chk` juste au-dessus de `calib`
                # (cf. son commentaire) : rendre le diagnostic ligne à ligne jusqu'au bout plutôt
                # qu'une trace Python brute sur un `IndexError` si `produits` est vide ici.
                demarrage = (server.submit("start_mode", id="mi",
                                           params={"mi": {"model": produits[0]}})
                            if produits else
                            {"accepted": False, "reason": "aucun modèle produit (diagnostic plus haut)"})
            finally:
                mi_models.modeles_disponibles = vrai_disponibles
            chk(demarrage.get("accepted"),
                f"le mode MI démarre sur le modèle qui vient d'être entraîné ({demarrage})")
        finally:
            server.stop()
            thread.join(timeout=10.0)
    finally:
        mi_calib.MICalibration.__init__ = ancien_init
        for cle, valeur in anciens.items():
            setattr(mi_calib.MICalibration, cle, valeur)
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[smoke-calib] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_calibration_refus():
    """Les quatre refus de `start_calibration`/`cancel_calibration`, et l'annulation de bout en
    bout — rien de tout ça n'était exercé, alors que ce sont les quatre premiers messages qu'un
    étudiant voit s'il se trompe de mode ou clique « Calibrer » sans y penser.

    Coût délibérément bas pour les quatre premiers : `submit` ne dépend pas de la boucle (cf. sa
    docstring — la validité se vérifie tout de suite, l'application se fait plus tard), donc ils
    se testent sur un moteur qui n'a JAMAIS tourné — aucune session BrainFlow, aucun fil.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # 1-4. Les quatre refus, sur un moteur JAMAIS démarré.
    froid = EngineServer(synthetic=True, modes=(), instance="smoke-calib-refus")

    r1 = froid.submit("start_calibration", id="bogus")
    chk(not r1.get("accepted") and "mode inconnu" in (r1.get("reason") or ""),
        f"mode inconnu : refusé, en le nommant ({r1.get('reason')})")

    r2 = froid.submit("start_calibration", id="ssvep")
    chk(not r2.get("accepted") and "n'a pas de calibration" in (r2.get("reason") or ""),
        f"mode SANS calibration (SSVEP, la CCA n'apprend rien) : refusé ({r2.get('reason')})")

    r3 = froid.submit("start_calibration", id="cvep")
    chk(not r3.get("accepted") and "src/research/app.py" in (r3.get("reason") or ""),
        f"calibration NATIVE (c-VEP) : refusée, en disant où aller à la place ({r3.get('reason')})")

    r4 = froid.submit("cancel_calibration")
    chk(not r4.get("accepted") and "aucune calibration" in (r4.get("reason") or ""),
        f"annuler sans calibration en cours : refusé ({r4.get('reason')})")

    # 5. L'annulation de bout en bout : commande -> boucle -> retour à « streaming » -> l'état de
    # la calibration elle-même. Ici il FAUT un moteur qui tourne : `submit` met en file, seule la
    # boucle applique.
    import threading

    chaud = EngineServer(synthetic=True, modes=(), instance="smoke-calib-refus-2")
    thread = threading.Thread(target=chaud.run, kwargs={"duration_s": 30.0}, daemon=True)
    thread.start()
    try:
        ack = chaud.submit("start_calibration", id="mi", params={})
        chk(ack.get("accepted"), f"la calibration démarre ({ack})")

        t0 = time.perf_counter()
        while chaud.calibration is None and time.perf_counter() - t0 < 5.0:
            time.sleep(0.05)
        chk(chaud.calibration is not None and chaud.phase == "calibrating",
            f"la boucle l'a appliquée, la phase publique le dit ({chaud.phase})")

        ack_annule = chaud.submit("cancel_calibration")
        chk(ack_annule.get("accepted"), f"l'annulation est acceptée ({ack_annule})")

        t0 = time.perf_counter()
        while chaud.phase == "calibrating" and time.perf_counter() - t0 < 5.0:
            time.sleep(0.05)
        chk(chaud.phase == "streaming",
            f"la phase publique revient à « streaming » (aucun autre mode actif) ({chaud.phase})")
        chk(chaud.calibration is not None and chaud.calibration.phase == "annule",
            f"la calibration elle-même se souvient qu'elle a été abandonnée "
            f"({None if chaud.calibration is None else chaud.calibration.phase})")
        chk(chaud.calibration is not None and chaud.calibration.resultat is None,
            "et n'a produit aucun résultat")
    finally:
        chaud.stop()
        thread.join(timeout=5.0)

    # 6. Le `finally` de `run()` : arrêter le moteur EN PLEINE calibration, SANS l'annuler
    # explicitement, doit quand même la couper proprement — c'est lui qui casse le cycle
    # calibration <-> moteur (cf. son long commentaire), et rien ne vérifiait qu'il s'exécute
    # vraiment sur ce chemin plutôt que sur le seul chemin `cancel_calibration` testé au-dessus.
    encore = EngineServer(synthetic=True, modes=(), instance="smoke-calib-refus-3")
    thread2 = threading.Thread(target=encore.run, kwargs={"duration_s": 30.0}, daemon=True)
    thread2.start()
    try:
        ack = encore.submit("start_calibration", id="mi", params={})
        chk(ack.get("accepted"), f"seconde calibration démarrée, pour tester l'arrêt sec ({ack})")
        t0 = time.perf_counter()
        while encore.calibration is None and time.perf_counter() - t0 < 5.0:
            time.sleep(0.05)
        chk(encore.calibration is not None, "elle est bien appliquée avant l'arrêt du moteur")
    finally:
        encore.stop()
        thread2.join(timeout=5.0)
    chk(encore.calibration is None,
        "arrêter le moteur EN PLEINE calibration, sans l'annuler explicitement, la coupe quand "
        "même — c'est le `finally` de run() qui le fait, pas cancel() tout seul")

    print(f"[smoke-calib-refus] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


# Les paquets que `core` n'a pas le droit d'importer : les deux autres paquets du dépôt, et les
# deux bibliothèques d'écran. Le nom n'est écrit QU'ICI — jamais dans une prose voisine, jamais
# sous la forme d'un import complet dans un commentaire : voir `_imports_interdits`.
_FRONTIERE_INTERDITS = ("research", "console", "pygame", "qtpy", "pyqtgraph")
_FRONTIERE_INTERDITS_RE = r"PySide\d+|PyQt\d+"


def _imports_interdits(source, nom_fichier="<extrait>"):
    """Les paquets interdits que CE CODE importe. Retourne [(ligne, paquet), ...].

    ⚠️ **Juge le CODE, pas le texte** (correction de revue, 2026-08-19). La version précédente
    passait le fichier à une expression régulière `^\\s*(?:from|import)\\s+(…)` : elle voyait donc
    aussi les docstrings et les chaînes. Sa propre documentation contenait l'exemple
    « un import de PySide6 » écrit sous forme d'import complet, une ligne plus bas que le début
    de phrase — **un simple reflow du paragraphe** (ou un mot ajouté à la phrase précédente)
    aurait suffi à faire échouer `--smoke` sur de la PROSE, avec le message « core/server.py
    importe PySide6 » et un contributeur envoyé chercher un import qui n'existe pas. Une garde
    qui se déclenche sur sa propre documentation est une garde qu'on finit par désactiver.

    Ici c'est `ast` qui répond : seuls les vrais nœuds `Import`/`ImportFrom` sont examinés, donc
    ni les docstrings, ni les commentaires, ni les chaînes ne peuvent produire de verdict. En
    prime, l'arbre attrape des formes que la regex laissait passer : import indenté dans une
    fonction, import multi-lignes entre parenthèses, et import RELATIF (`from ...research import
    x`), qui n'a plus besoin d'être listé comme angle mort.

    Ce qui échappe ENCORE, à connaître avant de s'y fier :

    - l'import DYNAMIQUE (`importlib.import_module("console.grid")`) — une chaîne reste une
      chaîne ;
    - l'import TRANSITIF (`import matplotlib.backends.backend_qt5agg`, ou tout paquet tiers qui
      tire Qt derrière lui) : la frontière porte sur ce que `core` ÉCRIT, pas sur ce que ses
      dépendances chargent.

    Ce test attrape la faute plausible — celle qu'on écrit sans y penser — pas celle qu'on
    cherche à cacher.
    """
    import ast
    import re

    motif = re.compile(rf"^(?:{'|'.join(_FRONTIERE_INTERDITS)}|{_FRONTIERE_INTERDITS_RE})$")
    fautes = []
    for noeud in ast.walk(ast.parse(source, filename=nom_fichier)):
        if isinstance(noeud, ast.Import):
            cibles = [alias.name for alias in noeud.names]
        elif isinstance(noeud, ast.ImportFrom):
            # `node.module` vaut None pour `from . import x` ; `level > 0` est un import relatif,
            # examiné lui aussi : `core` n'a aucun sous-module portant l'un de ces noms, donc un
            # match ne peut désigner qu'une remontée hors de `core`.
            cibles = [noeud.module or ""]
        else:
            continue
        for cible in cibles:
            paquet = cible.split(".")[0]
            if motif.match(paquet):
                fautes.append((noeud.lineno, paquet))
    return fautes


def _smoke_frontiere():
    """`core` n'importe ni `research`, ni `console`, ni pygame, NI QT.

    La règle est vérifiable, c'est tout son intérêt : un module est dans `core` si et seulement
    si `server.py` en a besoin pour tourner, et le moteur doit tourner sur une machine sans
    écran. Le jour où un import de `research` devient nécessaire, ce n'est pas ce test qu'il
    faut assouplir — c'est le module visé qui doit DÉMÉNAGER dans `core`.

    ⚠️ Correction de revue (tour 2) : la règle vérifiée ne couvrait que `research|console|pygame`,
    alors que CLAUDE.md (« ni pygame **ni Qt** dans core »), `core/__init__.py` et cette docstring
    même promettent aussi Qt. Or Qt n'arrive PAS dans `core` par le paquet `console` : il arrive
    par son propre nom. Un import de PySide6 glissé dans un utilitaire du moteur passait donc en
    silence — et `python src/core/server.py --mode ssvep` mourait sur un `ImportError` au
    démarrage, sur toute machine sans Qt (installation minimale, poste de TP, CI sans libGL), pour
    un moteur dont le contrat est justement de tourner sans écran. La règle VÉRIFIÉE était plus
    étroite d'un cran que la règle ÉCRITE, et c'était le cran qui compte.

    La détection elle-même vit dans `_imports_interdits` (voir sa docstring pour ce qui lui
    échappe). Ce test l'applique à tout `src/core/**/*.py`, ET la met à l'épreuve sur des extraits
    fabriqués — sans quoi une garde muette (motif vidé, parcours cassé) rendrait « 0 violation »
    et passerait pour un succès.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # 1. La garde attrape-t-elle encore un VRAI import — et se tait-elle sur la prose ?
    #    ⚠️ Les formes interdites sont écrites ICI, dans des chaînes, et nulle part ailleurs dans
    #    `src/core/` : c'est précisément ce que la partie 2 va scanner.
    fabrique = [
        ("from PySide6.QtCore import QTimer\n", ["PySide6"]),
        ("import PySide6.QtCore as qtc\n", ["PySide6"]),
        ("from PyQt5 import QtCore\n", ["PyQt5"]),
        ("import pygame\n", ["pygame"]),
        ("from research.ui import App\n", ["research"]),
        ("import qtpy, pyqtgraph as pg\n", ["qtpy", "pyqtgraph"]),
        ("def f():\n    from console.grid import Grille\n", ["console"]),      # indenté
        ("from research.ui import (App,\n                          Abort)\n", ["research"]),
        ("from ...research import x\n", ["research"]),                          # relatif
        ('"""from PySide6.QtCore import QTimer en docstring."""\n', []),        # PROSE
        ("# from PySide6.QtCore import QTimer\n", []),                          # commentaire
        ("x = 'import pygame'\n", []),                                          # chaîne
        ("import numpy\nfrom core.config import DATA_DIR\n", []),               # légitime
    ]
    for source, attendu in fabrique:
        trouve = [paquet for _ligne, paquet in _imports_interdits(source)]
        chk(trouve == attendu,
            f"« {source.strip().splitlines()[0][:52]} » -> {trouve or 'rien'} "
            f"(attendu {attendu or 'rien'})")

    # 2. Et maintenant le vrai `src/core/`.
    racine = os.path.dirname(os.path.abspath(__file__))
    fautes, fichiers_vus = [], 0
    for dossier, _sous, fichiers in os.walk(racine):
        if "__pycache__" in dossier:
            continue
        for nom in fichiers:
            if not nom.endswith(".py"):
                continue
            chemin = os.path.join(dossier, nom)
            rel = os.path.relpath(chemin, racine)
            fichiers_vus += 1
            with open(chemin, encoding="utf-8") as f:
                for ligne, paquet in _imports_interdits(f.read(), rel):
                    fautes.append(f"core/{rel}:{ligne} importe {paquet}")

    for faute in fautes:
        print(f"[smoke-frontiere] ÉCHEC : {faute}")
    print(f"[smoke-frontiere] {fichiers_vus} fichiers scannés, "
          f"{len(fautes)} violation(s) de frontière")
    ok = ok and not fautes
    print(f"[smoke-frontiere] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_repos_partage():
    """Lancés ENSEMBLE : un seul repos. Lancés SÉPARÉMENT : chacun le sien.

    La règle vient du terrain : « ne fixe aucune cible » et « immobile et détendu » décrivent le
    même moment, donc enchaîner deux repos ferait attendre l'étudiant pour rien. Mais un mode
    démarré alors qu'un autre tourne déjà ne peut PAS réutiliser un repos qu'il n'a pas observé.

    Sans LSL ni fil : c'est de la logique pure, et un test qui ne dort pas se relance sans
    hésiter. ⚠️ Les trois `EngineServer` ouvrent des `StreamOutlet` sans jamais tourner (`run()`
    n'est jamais appelé) : sûr (aucune session BrainFlow n'est ouverte, `self.acq` n'est démarré
    que par `run`), mais chacun reçoit un `instance=` distinct pour ne pas se confondre sur le
    réseau, et chacun est nettoyé explicitement en fin de bloc (voir plus bas).
    """
    from core.modes.contract import ModeSpec, Rest
    from core.modes.runtime import ModeRuntime

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    ssvep, neuro = registry.get("ssvep"), registry.get("neuro")

    # 1. Ensemble : durée = max, chauffe = max, consigne = celle du repos le plus long.
    server = EngineServer(synthetic=True, modes=("ssvep", "neuro"), instance="smoke-repos")
    server._start(["ssvep", "neuro"], {s.id: v for s, v in server._pending}, now=0.0)
    a, b = server.active["ssvep"], server.active["neuro"]
    chk(a._rest_s == b._rest_s == max(ssvep.rest.duration_s, neuro.rest.duration_s),
        f"une seule durée de repos, la plus longue ({a._rest_s:g} s)")
    # ⚠️ Assertion FAIBLE : SSVEP_WARMUP_S == NEURO_WARMUP_S == 15.0 aujourd'hui, donc cette
    # égalité passerait MÊME SI le partage de la chauffe était cassé (chacun garderait sa propre
    # chauffe, qui vaut 15 s des deux côtés par pure coïncidence). Elle documente quand même le
    # comportement attendu sur les VRAIS modes — c'est la partie 1b, sur des contrats fabriqués à
    # valeurs distinctes, qui prouve réellement la règle « chauffe = maximum ».
    chk(a._warmup_s == b._warmup_s == max(ssvep.rest.warmup_s, neuro.rest.warmup_s),
        f"une seule chauffe, la plus longue ({a._warmup_s:g} s)")
    chk(server.rest_instruction == neuro.rest.instruction,
        f"la consigne est celle du repos le plus long — « {server.rest_instruction[:40]}… »")
    # ⚠️ Assertion FAIBLE, même raison : ssvep et neuro démarrent dans le MÊME appel `_start`, au
    # MÊME `now` — donc même si chacun gardait SA PROPRE chauffe (15 s, non partagée),
    # `_warmup_until = now + 15` coïnciderait quand même pour les deux. Ne prouve que « même
    # instant affiché », pas « chauffe réellement partagée » ; 1b couvre ce trou.
    chk(a._warmup_until == b._warmup_until,
        "les deux modes sortent de chauffe au MÊME instant (un seul repos, pas deux)")
    # Casse le cycle self.active <-> ModeRuntime.engine (cf. le commentaire de run().finally) :
    # sans ça, un __del__ tardif du BoardShim de CE moteur peut libérer la session BrainFlow
    # d'un AUTRE moteur créé plus tard dans ce même processus — exactement ce que `--smoke` révèle.
    for runtime in server.active.values():
        runtime.close()
    server.active = {}

    # 1b. La règle « chauffe = maximum » ne peut PAS être prouvée par les deux VRAIS modes :
    # SSVEP_WARMUP_S et NEURO_WARMUP_S valent tous deux 15 s aujourd'hui, donc l'égalité
    # vérifiée ci-dessus passerait même si le partage était cassé. On la prouve donc sur des
    # contrats FABRIQUÉS, aux valeurs distinctes — et le test restera valable le jour où l'une
    # des deux constantes bougera.
    #
    # Le mode qui a la plus longue CHAUFFE n'est volontairement pas celui qui a le plus long
    # REPOS : c'est ce qui vérifie que les deux maximums sont calculés séparément, et que la
    # consigne affichée suit bien la DURÉE du repos et non la chauffe.
    court = ModeSpec(id="court", label="Court", family="actif", summary="", status="moteur",
                     rest=Rest(warmup_s=2.0, duration_s=30.0,
                               instruction="consigne du repos le plus long"),
                     stream="decoded_court", channels=("x",))
    longue = ModeSpec(id="longue", label="Longue chauffe", family="actif", summary="",
                      status="moteur",
                      rest=Rest(warmup_s=9.0, duration_s=5.0,
                                instruction="consigne de la chauffe la plus longue"),
                      stream="decoded_longue", channels=("x",))
    faux = EngineServer(synthetic=True, modes=(), instance="smoke-repos-4")
    a, b = ModeRuntime(court, {}, faux), ModeRuntime(longue, {}, faux)
    faux._begin_shared_rest([a, b], now=0.0)
    chk(a._warmup_s == b._warmup_s == 9.0,
        f"chauffe partagée = le MAXIMUM des chauffes ({a._warmup_s:g} s pour 2 et 9)")
    chk(a._rest_s == b._rest_s == 30.0,
        f"durée partagée = le MAXIMUM des durées ({a._rest_s:g} s pour 30 et 5)")
    chk(faux.rest_instruction == court.rest.instruction,
        f"la consigne suit la DURÉE du repos, pas la chauffe — « {faux.rest_instruction} »")
    # Même cleanup que les trois autres blocs, par cohérence. Ici `_begin_shared_rest` est
    # appelée DIRECTEMENT (pas via `_start`), donc `a`/`b` ne sont jamais entrés dans
    # `faux.active` : ce bloc est un no-op en pratique, sans session BrainFlow ni cycle formé
    # (rien dans `faux` ne référence `a`/`b` en retour). On le garde quand même pour que le
    # motif reste identique aux trois autres blocs, y compris si ce test évolue vers `_start`.
    for runtime in faux.active.values():
        runtime.close()
    faux.active = {}

    # 2. Séparément : chacun garde la sienne.
    server = EngineServer(synthetic=True, modes=("ssvep",), instance="smoke-repos-2")
    server._start(["ssvep"], {s.id: v for s, v in server._pending}, now=0.0)
    seul_a = server.active["ssvep"]._rest_s
    values, _ = contract.validate(neuro, {})
    server._start(["neuro"], {"neuro": values}, now=100.0)
    seul_b = server.active["neuro"]._rest_s
    chk(seul_a == ssvep.rest.duration_s and seul_b == neuro.rest.duration_s,
        f"lancés séparément, chacun garde sa durée ({seul_a:g} s et {seul_b:g} s)")
    chk(server.active["ssvep"]._warmup_until != server.active["neuro"]._warmup_until,
        "et leurs repos ne sont pas alignés")
    # Même cycle à casser qu'au bloc 1 — ce moteur-ci a démarré deux fois (ssvep puis neuro).
    for runtime in server.active.values():
        runtime.close()
    server.active = {}

    # 3. Un mode sans repos ne déclenche rien et démarre tout de suite.
    server = EngineServer(synthetic=True, modes=("raw",), instance="smoke-repos-3")
    server._start(["raw"], {s.id: v for s, v in server._pending}, now=0.0)
    chk(server.active["raw"].phase == "running" and server.rest_instruction == "",
        "le brut seul ne déclenche aucun repos")
    # Toujours le même cycle : ce moteur non plus n'est jamais passé par `run()`.
    for runtime in server.active.values():
        runtime.close()
    server.active = {}

    print(f"[smoke-repos] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_proposition():
    """La proposition et le repos sélectif, contre un VRAI moteur — jamais une maquette."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    server = EngineServer(synthetic=True, modes=("ssvep",), instance="smoke-proposition")
    server._start(["ssvep"], {s.id: v for s, v in server._pending}, now=0.0)

    ack = server.submit("propose_params", id="ssvep", key="refresh_hz")
    chk(ack.get("accepted") and len(ack.get("value") or []) == 3,
        f"proposer rend autant de cibles qu'il y en a réglées ({ack.get('value')})")
    chk(all(abs(60.0 / f - round(60.0 / f)) < TOLERANCE_DIVISEUR for f in ack["value"]),
        "et toutes divisent le refresh déclaré")

    # La proposition doit être ACCEPTABLE par le moteur : c'est ce qui prouve que la règle et la
    # validation sont d'accord. Deux morceaux qui divergeraient produiraient un bouton qui propose
    # des valeurs aussitôt refusées — le pire des deux mondes.
    ack2 = server.submit("set_params", id="ssvep", params={"freqs": ack["value"]})
    chk(ack2.get("accepted"), f"et le moteur accepte ce qu'il vient de proposer ({ack2}) ")

    # La proposition doit se calculer sur ce que l'appelant est EN TRAIN D'ÉDITER (`params`), pas
    # sur ce qui est stocké : sinon déclarer un écran 144 Hz est refusé (les fréquences en vigueur,
    # calées sur 60, ne le divisent pas) ET la proposition continue de calculer sur 60 — aucune
    # porte de sortie pour l'étudiant qui change d'écran.
    ack5 = server.submit("propose_params", id="ssvep", key="refresh_hz",
                         params={"refresh_hz": 144.0})
    chk(ack5.get("accepted") and len(ack5.get("value") or []) == 3,
        f"proposer avec un refresh en cours d'édition rend 3 cibles ({ack5.get('value')})")
    chk(all(abs(144.0 / f - round(144.0 / f)) < TOLERANCE_DIVISEUR for f in ack5["value"]),
        f"et ce sont des diviseurs de 144 Hz, pas de 60 ({ack5.get('value')})")
    ack6 = server.submit("set_params", id="ssvep",
                         params={"freqs": ack5["value"], "refresh_hz": 144.0})
    chk(ack6.get("accepted"),
        f"et le jeu proposé pour 144 Hz est accepté avec refresh_hz=144 ({ack6})")

    # Un réglage sans effet sur le décodage ne reconstruit RIEN. On compare l'objet lui-même et
    # pas la phase : les deux chemins laissent le mode en « warmup » juste après un démarrage, donc
    # la phase ne prouverait rien. L'identité du runtime, si — et c'est elle qui porte le plancher
    # de repos déjà mesuré.
    avant = server.active["ssvep"]
    server._set_params("ssvep", {**avant.params, "refresh_hz": 144.0})
    chk(server.active["ssvep"] is avant,
        "changer le refresh seul garde le MÊME runtime, donc son plancher de repos")
    chk(server.active["ssvep"].params["refresh_hz"] == 144.0,
        f"et le réglage est bien pris ({server.active['ssvep'].params['refresh_hz']})")

    # Un réglage que le décodeur lit, lui, reconstruit et refait le repos.
    avant = server.active["ssvep"]
    server._set_params("ssvep", {**avant.params, "freqs": [12.0, 18.0], "refresh_hz": 60.0})
    chk(server.active["ssvep"] is not avant,
        "changer les fréquences reconstruit le mode")
    chk(server.active["ssvep"].phase == "warmup",
        f"et relance le repos (phase {server.active['ssvep'].phase})")

    # Une clé qui ne propose rien est refusée AVEC sa raison : la commande reste atteignable
    # depuis un client LSL même quand la console n'affiche aucun bouton. `freqs` est la CIBLE des
    # propositions, jamais leur source (contrairement à `refresh_hz` ET, depuis la critique 5,
    # `alpha_hz`) : elle ne propose donc jamais rien elle-même.
    ack3 = server.submit("propose_params", id="ssvep", key="freqs")
    chk(not ack3.get("accepted") and "propose" in (ack3.get("reason") or ""),
        f"un réglage qui ne propose rien est refusé ({ack3.get('reason')})")

    # Proposer AVANT d'avoir démarré le mode doit marcher : on se règle puis on lance.
    arrete = EngineServer(synthetic=True, modes=(), instance="smoke-proposition-2")
    ack4 = arrete.submit("propose_params", id="ssvep", key="refresh_hz")
    chk(ack4.get("accepted") and ack4.get("value"),
        f"on peut demander une proposition sur un mode PAS ENCORE démarré ({ack4.get('reason')})")

    # Ce moteur n'est jamais passé par `run()` : on casse le cycle à la main, comme les autres
    # smokes de ce fichier, sinon un `__del__` tardif du BoardShim libère la session BrainFlow.
    for runtime in server.active.values():
        runtime.close()
    server.active = {}
    print(f"[smoke-proposition] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_cumul():
    """Deux modes qui tournent ENSEMBLE : chacun publie, arrêter l'un ne perturbe pas l'autre.

    C'est la propriété neuve de ce chantier, et celle qu'on ne peut pas déduire des tests par
    mode : deux décodeurs sur le même tampon glissant, deux flux, deux phases.
    """
    import threading

    from pylsl import StreamInlet

    instance = "smoke-cumul"
    server = EngineServer(synthetic=True, modes=("raw", "ssvep", "neuro"), instance=instance)
    thread = threading.Thread(
        target=server.run,
        kwargs={"duration_s": 20.0, "baseline_s": 3.0, "warmup_s": 1.0}, daemon=True)
    thread.start()

    ok = True
    inlets = {}
    for suffix in ("decoded_ssvep", "decoded_neuro"):
        found = _resolve_own(suffix, instance, 6.0)
        if not found:
            print(f"[smoke-cumul] ÉCHEC : {suffix} introuvable — les deux modes doivent "
                  f"publier en même temps")
            server.stop()
            return False
        inlets[suffix] = StreamInlet(found)
        inlets[suffix].open_stream(timeout=5.0)

    t0 = time.perf_counter()
    while server.phase != "decoding" and time.perf_counter() - t0 < 15.0 and thread.is_alive():
        for inlet in inlets.values():
            inlet.pull_chunk(timeout=0.05, max_samples=64)
    if server.phase != "decoding":
        print(f"[smoke-cumul] ÉCHEC : toujours en « {server.phase} » après 15 s")
        server.stop()
        return False

    recu = {suffix: 0 for suffix in inlets}
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 3.0 and thread.is_alive():
        for suffix, inlet in inlets.items():
            chunk, _ts = inlet.pull_chunk(timeout=0.1, max_samples=64)
            recu[suffix] += len(chunk)
    print(f"[smoke-cumul] reçu {recu} pendant que les deux décodent")
    for suffix, n in recu.items():
        if n < 3:
            print(f"[smoke-cumul] ÉCHEC : {suffix} n'a publié que {n} fois")
            ok = False

    # `set_published` doit couper la publication SANS toucher au décodage (contrat documenté
    # dans ModeRuntime.set_published) — et jusqu'ici rien ne le vérifiait : un flux qui refuserait
    # de disparaître serait un défaut SILENCIEUX, invisible à l'étudiant qui l'a coupé.
    ack = server.submit("set_published", id="ssvep", on=False)
    if not ack.get("accepted"):
        print(f"[smoke-cumul] ÉCHEC : set_published(on=False) refusé ({ack})")
        ok = False
    parti = False
    for _ in range(40):
        time.sleep(0.1)
        if stream_name("decoded_ssvep") not in server.snapshot()["streams"]:
            parti = True
            break
    if not parti:
        print("[smoke-cumul] ÉCHEC : le flux SSVEP est toujours annoncé après set_published(on=False)")
        ok = False
    etat = server.snapshot()
    if stream_name("decoded_neuro") not in etat["streams"]:
        print("[smoke-cumul] ÉCHEC : couper la publication du SSVEP a aussi coupé celle du neuro")
        ok = False
    if etat["modes_state"].get("ssvep", {}).get("phase") != "running":
        print(f"[smoke-cumul] ÉCHEC : couper la publication a aussi arrêté le décodage "
              f"({etat['modes_state'].get('ssvep')})")
        ok = False
    else:
        print("[smoke-cumul] set_published(on=False) : flux SSVEP disparu, décodage toujours actif")

    ack = server.submit("set_published", id="ssvep", on=True)
    if not ack.get("accepted"):
        print(f"[smoke-cumul] ÉCHEC : set_published(on=True) refusé ({ack})")
        ok = False
    revenu = False
    for _ in range(40):
        time.sleep(0.1)
        if stream_name("decoded_ssvep") in server.snapshot()["streams"]:
            revenu = True
            break
    if not revenu:
        print("[smoke-cumul] ÉCHEC : le flux SSVEP ne revient pas après set_published(on=True)")
        ok = False
    else:
        print("[smoke-cumul] set_published(on=True) : le flux SSVEP est revenu")

    # Arrêter l'un ne doit pas perturber l'autre : c'est ce qui rend le cumul utilisable.
    ack = server.submit("stop_mode", id="ssvep")
    if not ack.get("accepted"):
        print(f"[smoke-cumul] ÉCHEC : stop_mode refusé ({ack})")
        ok = False
    arrete = False
    for _ in range(40):
        time.sleep(0.1)
        if "ssvep" not in server.snapshot()["modes"]:
            arrete = True
            break
    if not arrete:
        print("[smoke-cumul] ÉCHEC : le SSVEP est toujours actif après stop_mode")
        ok = False

    apres, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < 2.0 and thread.is_alive():
        chunk, _ts = inlets["decoded_neuro"].pull_chunk(timeout=0.1, max_samples=64)
        apres += len(chunk)
    print(f"[smoke-cumul] le neuro a publié {apres} fois APRÈS l'arrêt du SSVEP")
    if apres < 3:
        print("[smoke-cumul] ÉCHEC : arrêter un mode a perturbé l'autre")
        ok = False

    # Dernier mode décodé arrêté : le moteur reste vivant, quality et status continuent.
    server.submit("stop_mode", id="neuro")
    time.sleep(0.5)
    state = server.snapshot()
    if not state["running"] or stream_name("quality") not in state["streams"]:
        print(f"[smoke-cumul] ÉCHEC : le moteur ne survit pas au dernier mode arrêté ({state})")
        ok = False

    server.stop()
    thread.join(timeout=5.0)
    print(f"[smoke-cumul] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_dimensionnement():
    """`keep` couvre-t-il l'époque du mode le plus gourmand EN MARQUEURS, retard compris ?

    ⚠️ Assertion DIRECTE sur `server.keep`, et c'est délibéré. Observer qu'une époque « sort »
    ne prouve RIEN : un tampon sous-dimensionné rend quand même ce qu'on lui demande, juste
    plus court. Ce piège a déjà été rencontré au chantier 3B, sur la calibration MI.

    ⚠️ Et surtout : les deux premières assertions ne peuvent PAS ÉCHOUER telles quelles. Le seul
    mode marqueur du catalogue demande 0,95 s, donc `attendu` vaut 488 échantillons contre un
    `keep` de 1250 imposé par d'AUTRES consommateurs (la calibration MI et ses époques de 4 s).
    Elles sont vraies par construction — et elles resteraient vraies si le terme `marker_epoch_s`
    disparaissait entièrement du `max()` de `__init__`. Un test qui ne peut pas rougir ne protège
    rien. Le troisième bloc ci-dessous existe pour ça : il déclare un mode marqueur PLUS GOURMAND
    que tous les autres consommateurs réunis, ce qui rend le terme, et lui seul, décisif.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    srv = EngineServer(synthetic=True, modes=(), params={}, instance="smoke-dimensionnement")
    besoin = max([spec.marker_epoch_s for spec in registry.MODES] or [0.0])
    attendu = int(round((besoin + MARKER_LATE_S) * srv.acq.fs))
    chk(srv.keep >= attendu,
        f"keep={srv.keep} couvre l'époque du marqueur ({besoin:g} s) plus le retard toléré "
        f"({MARKER_LATE_S:g} s) = {attendu} échantillons")
    chk(besoin > 0.0,
        f"au moins un mode déclare une époque de marqueur ({besoin:g} s) — sans ça l'assertion "
        f"ci-dessus serait vraie à vide et ne prouverait rien")

    # Le mode marqueur le plus gourmand du catalogue est DOMINÉ par les autres consommateurs du
    # tampon : on en déclare donc un qui les domine tous, le temps de ce test. 30 s d'époque
    # contre 4 s pour la calibration MI, la plus gourmande aujourd'hui — aucune ambiguïté sur
    # quel terme décide. Le motif (patcher `registry.MODES` puis restaurer) est celui de
    # `_smoke_marqueurs_inlet`.
    from core.modes import registry as _registry
    from core.modes.contract import ModeSpec
    from core.modes.runtime import ModeRuntime

    gourmand = ModeSpec(id="smoke-gourmand", label="Gourmand (test)", family="actif", summary="",
                        status="moteur", stream="decoded_smoke_gourmand", channels=("x",),
                        marker_epoch_s=30.0, runtime_cls=ModeRuntime)
    avant_registre = _registry.MODES
    _registry.MODES = avant_registre + (gourmand,)
    try:
        gros = EngineServer(synthetic=True, modes=(), params={},
                            instance="smoke-dimensionnement-2")
        exige = int(round((30.0 + MARKER_LATE_S) * gros.acq.fs))
        chk(gros.keep >= exige,
            f"un mode déclarant une époque de 30 s force keep={gros.keep} >= {exige} — c'est "
            f"CETTE assertion qui tombe si le terme `marker_epoch_s` quitte le max() de __init__")
    finally:
        _registry.MODES = avant_registre
    print(f"[smoke-dimensionnement] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


class _AcqDeterministe:
    """Un producteur d'échantillons PRÉVISIBLE, à la place du thread interne de BrainFlow.

    Tout est DÉLÉGUÉ à la vraie `UnicornAcquisition` (`fs`, `window_n`, `margin_n`, `board_id`,
    `sigma_from_block`, `common_mode`…) : seules l'ouverture de session et la lecture des
    échantillons sont remplacées — c'est-à-dire exactement les deux choses qui rendaient
    `_smoke_tampon_horodate` dépendant de l'ordonnanceur du système.

    Les horodatages rendus sont CONTIGUS d'un appel au suivant, espacés de 1/fs pile. Ce que le
    test compare ensuite n'est donc plus « le board a-t-il tenu la cadence pendant ces 3
    secondes de temps mural » (une question sur BrainFlow, sur laquelle `server.py` n'a aucune
    prise) mais « `server.py` a-t-il recopié fidèlement ce qu'on lui a donné » — une question
    sur ce fichier, et à laquelle une préemption ne peut pas répondre non.
    """

    def __init__(self, vraie, par_tour=13):
        self._vraie = vraie          # posé EN PREMIER : c'est ce que `__getattr__` va lire
        self.par_tour = int(par_tour)
        self.t0 = 1_700_000_000.0    # une date Unix quelconque, mais FIXE
        self.produits = 0
        self._rng = np.random.default_rng(20260819)

    def __getattr__(self, nom):
        return getattr(self._vraie, nom)

    def __enter__(self):
        return self                  # aucune session BrainFlow : rien à ouvrir, rien à perdre

    def __exit__(self, *exc):
        return False

    def get_new_data(self):
        """(eeg (n, 8), horodatages UNIX). Même contrat que `UnicornAcquisition.get_new_data`."""
        n, fs = self.par_tour, self._vraie.fs
        eeg = self._rng.normal(0.0, 20.0, (n, len(CH_NAMES)))
        ts = self.t0 + (self.produits + np.arange(n)) / fs
        self.produits += n
        return eeg, ts


def _smoke_tampon_horodate():
    """Les deux tampons ont-ils toujours la même longueur, et le temps y avance-t-il ?

    Un décalage d'un seul échantillon entre `recent` et `recent_ts` déplace TOUTES les époques
    sans rien casser de visible : le décodeur reçoit du signal, de la bonne taille, pris au
    mauvais endroit.

    ⚠️ Une égalité de LONGUEURS ne prouve pas l'ALIGNEMENT, et c'était le seul contrôle existant.
    Elle ne voit aucun décalage TEMPOREL à longueur égale, et elle devient vide dès que les deux
    tampons saturent à `keep` — c'est-à-dire toujours, en séance réelle. La mutation
    `np.concatenate([self.recent_ts, ts_lsl + 1.0 / self.acq.fs])` (un échantillon d'écart, la
    faute la plus plausible) passait TOUTE la suite de tests, y compris le test d'alignement du
    P300, qui travaille sur des tableaux fabriqués.

    L'assertion qui ferme le trou est la dernière : `srv.new_block` porte `(eeg, ts_lsl)` du
    DERNIER bloc lu par la boucle, celui-là même qui vient d'être empilé. La QUEUE des deux
    tampons doit donc être exactement ce bloc — valeurs ET horodatages, à l'identique. Ça
    épingle d'un coup la longueur, l'ordre, le décalage et toute transformation glissée en route.

    ⚠️ **Correction de revue (tour 2) : ce test jugeait le mauvais objet, et il était instable
    depuis cinq tâches.** Il faisait tourner un vrai board pendant 3 s de temps MURAL, puis
    jugeait les horodatages produits par le thread interne de BrainFlow — que `server.py` se
    contente de RECOPIER (`clock.to_lsl(ts_unix)` du canal TIMESTAMP). Une préemption suivie
    d'un rattrapage en rafale effondrait la médiane des écarts et faisait rougir un test dont
    aucune ligne de ce fichier n'était la cause : échec journalisé « cadence médiane 0.02 ms
    attendu 4.00 ms », précédé dans le log de `data_receiver.cpp ERR| Stream transmission broke
    off`, et jusqu'à quatre fois de suite pendant qu'une autre charge tournait. Trois
    implémenteurs y ont dépensé du temps à prouver que ce n'était pas eux.

    La réponse n'est PAS d'élargir la tolérance : un test qui juge la mauvaise chose ne devient
    pas bon en devenant permissif, il devient un test qu'on relance jusqu'au vert — donc un test
    qu'on a appris à ignorer. Le producteur est donc remplacé par `_AcqDeterministe`, et chaque
    assertion redevient une question sur `server.py` :

    - la cadence médiane vaut EXACTEMENT 1/fs parce qu'on l'a fournie ainsi : ce qui est vérifié
      est que le moteur TRANSMET les horodatages du producteur au lieu d'en régénérer ;
    - `new_block` est toujours peuplé (chaque tour rend des échantillons), donc l'alignement est
      jugé à chaque exécution au lieu de dépendre du hasard d'un tour à vide ;
    - plus aucune seconde de temps mural n'entre dans un verdict.

    Ce que ce test ne couvre PLUS, et qui est couvert ailleurs : l'intégration avec le vrai board
    BrainFlow (`_smoke`, `_smoke_ssvep`, `_smoke_mi`… font tourner de vrais `EngineServer`
    synthétiques) et le contrat de `get_new_data` lui-même (`python src/core/acquisition.py
    --synthetic`).
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    srv = EngineServer(synthetic=True, modes=(), params={}, instance="smoke-tampon")
    srv.acq = _AcqDeterministe(srv.acq)
    fs = srv.acq.fs
    print(f"[smoke-tampon] producteur DÉTERMINISTE ({srv.acq.par_tour} échantillons par tour, "
          f"1/fs = {1000.0 / fs:.2f} ms) — aucune session BrainFlow n'est ouverte ici")
    srv.run(duration_s=0.4)

    chk(len(srv.recent) == len(srv.recent_ts),
        f"les deux tampons ont la même longueur ({len(srv.recent)} et {len(srv.recent_ts)})")
    # `min(produits, keep)` — c'est l'invariant exact du `[-self.keep:]` : tout ce qui a été
    # produit tant que le tampon n'est pas plein, sa taille ensuite.
    #
    # ⚠️ Ici, et ICI SEULEMENT, le `min()` est INERTE : 0,4 s à POLL_S = 0,05 s font 8 tours de
    # 13 échantillons, soit 104 pour un `keep` de 1250 — le tampon ne sature jamais, donc cette
    # ligne ne dit rien de la troncature (elle l'a longtemps prétendu ; correction de revue
    # 2026-08-19). Le régime plein est exercé plus bas, sur un SECOND moteur.
    chk(len(srv.recent_ts) == min(srv.acq.produits, srv.keep) > 0,
        f"et ils portent tout ce que le producteur a rendu, borné à `keep` "
        f"({len(srv.recent_ts)} pour {srv.acq.produits} produits, keep={srv.keep})")
    diffs = np.diff(srv.recent_ts)
    chk(bool(np.all(diffs > 0)),
        "le temps avance strictement, sans doublon ni retour en arrière — la concaténation "
        "empile bien la queue APRÈS la tête")
    attendu = 1.0 / fs
    # Tolérance de 10 µs : quatre ordres de grandeur sous la période d'échantillon (4 ms), et
    # trois au-dessus du bruit du flottant sur des dates Unix (~0,24 µs). Aucun ordonnanceur
    # n'entre dans cette fenêtre — seule une transformation des horodatages par `server.py` peut
    # l'en faire sortir, et c'est tout ce qu'on veut savoir.
    ecart = float(abs(np.median(diffs) - attendu))
    chk(ecart < 1e-5,
        f"et la cadence RECOPIÉE vaut exactement celle du producteur, à {ecart * 1e6:.3f} µs "
        f"près ({np.median(diffs) * 1000:.4f} ms pour {attendu * 1000:.4f} ms fournis)")

    # L'ALIGNEMENT lui-même, contre le dernier bloc réellement lu.
    bloc = srv.new_block
    chk(bloc is not None,
        "le dernier tour de boucle a bien lu un bloc — désormais GARANTI, le producteur en rend "
        "à chaque tour (avant, un tour à vide emportait les trois assertions suivantes)")
    if bloc is not None:
        eeg, ts_lsl = bloc
        n = len(eeg)
        chk(n > 0 and n <= len(srv.recent),
            f"ce bloc ({n} échantillons) tient dans le tampon ({len(srv.recent)})")
        chk(bool(np.array_equal(srv.recent[-n:], eeg)),
            f"la QUEUE de `recent` est exactement le dernier bloc lu, valeur pour valeur "
            f"({n} échantillons)")
        chk(bool(np.array_equal(srv.recent_ts[-n:], ts_lsl)),
            f"...et la queue de `recent_ts` est exactement les horodatages de CE bloc — c'est "
            f"l'assertion qui rougit sur un décalage d'un seul échantillon "
            f"(écart max {float(np.max(np.abs(srv.recent_ts[-n:] - ts_lsl))) * 1000:.4f} ms)")

    # --- LE RÉGIME PLEIN : le tampon SATURE et la troncature s'exerce -----------------------
    #
    # Le moteur passe sa vie dans ce régime (`keep` = 5 s de signal, une séance en dure des
    # milliers) et aucun test ne l'atteignait : retirer les deux `[-self.keep:]` de la boucle
    # laissait TOUT le fichier vert. Le moteur se mettait alors à `vstack` un tableau qui grandit
    # sans borne, dix fois par seconde — ça ne casse pas, ça ralentit puis ça sature la mémoire,
    # la panne la plus difficile à imputer.
    #
    # `keep` est réduit à la main et le producteur rend PLUS que `keep` en UN SEUL tour : le
    # régime est donc atteint dès le premier passage, et le verdict ne dépend ni de POLL_S, ni de
    # la durée demandée, ni de la machine. Après n'importe quel nombre de tours ≥ 1, le tampon
    # doit être exactement la FIN du dernier bloc lu.
    plein = EngineServer(synthetic=True, modes=(), params={}, instance="smoke-tampon-plein")
    plein.keep = 20
    plein.acq = _AcqDeterministe(plein.acq, par_tour=plein.keep + 17)
    plein.run(duration_s=0.2)
    chk(plein.acq.produits > plein.keep,
        f"le producteur a bien débordé le tampon ({plein.acq.produits} échantillons pour "
        f"keep={plein.keep}) — sans ce régime, les deux assertions suivantes ne prouvent rien")
    chk(len(plein.recent) == len(plein.recent_ts) == plein.keep,
        f"le tampon SATURE à `keep` au lieu de grandir ({len(plein.recent)} lignes et "
        f"{len(plein.recent_ts)} dates pour keep={plein.keep}) — c'est l'assertion qui rougit "
        f"quand un `[-self.keep:]` disparaît de la boucle")
    bloc_plein = plein.new_block
    if bloc_plein is not None:
        eeg_p, ts_p = bloc_plein
        chk(bool(np.array_equal(plein.recent, eeg_p[-plein.keep:])
                 and np.array_equal(plein.recent_ts, ts_p[-plein.keep:])),
            "et ce qui reste est la FIN du dernier bloc, pas son début — une troncature écrite "
            "`[:keep]` garderait les échantillons les plus VIEUX et le moteur décoderait du passé")
    print(f"[smoke-tampon] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_marqueurs_murs():
    """Un marqueur n'est rendu que quand son époque tient ENTIÈREMENT dans le tampon."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    srv = EngineServer(synthetic=True, modes=(), params={}, instance="smoke-marqueurs")
    fs = srv.acq.fs
    # Tampon fabriqué : 3 s de temps qui avance, à partir de t=100.
    srv.recent_ts = np.arange(100.0, 103.0, 1.0 / fs)
    srv.recent = np.zeros((len(srv.recent_ts), 8))

    srv._marqueurs = [(101.0, {"mode": "p300", "event": "flash", "target": 1}),
                      (102.9, {"mode": "p300", "event": "flash", "target": 2}),
                      (101.5, {"mode": "errp", "event": "feedback"})]
    srv._marqueur_curseur = {}

    # `.get("target")` partout, jamais `["target"]` : la liste `resultats` de `_smoke()` est
    # construite EN AMONT, donc une exception levée ICI ferait sauter TOUS les sous-tests
    # suivants — exactement le court-circuit que le passage de `and` à `all()` venait de
    # supprimer, et sans même imprimer un verdict. Un marqueur qui échapperait au filtre n'a pas
    # forcément de clé « target » : on veut un ÉCHEC propre via `chk`, pas un `KeyError`.
    murs = srv.markers_murs("p300", post_s=0.80)
    chk([m[1].get("target") for m in murs] == [1],
        f"seul le marqueur dont les 0,80 s suivantes sont dans le tampon est rendu ({murs})")
    chk(all(m[1]["mode"] == "p300" for m in murs),
        "et le marqueur d'un AUTRE mode n'est jamais rendu à celui-ci")

    # Le curseur avance : un marqueur mûr n'est rendu qu'UNE fois.
    chk(srv.markers_murs("p300", post_s=0.80) == [],
        "un marqueur déjà rendu ne l'est pas deux fois")

    # Le tampon avance : le second devient mûr à son tour.
    srv.recent_ts = np.arange(100.0, 104.0, 1.0 / fs)
    srv.recent = np.zeros((len(srv.recent_ts), 8))
    murs = srv.markers_murs("p300", post_s=0.80)
    chk([m[1].get("target") for m in murs] == [2],
        f"le tampon ayant avancé, le suivant mûrit à son tour ({murs})")

    # Un marqueur PLUS VIEUX que le tampon est PERDU, et compté.
    avant = srv.marqueurs_perdus
    srv._marqueurs.append((50.0, {"mode": "p300", "event": "flash", "target": 3}))
    srv.markers_murs("p300", post_s=0.80)
    chk(srv.marqueurs_perdus == avant + 1,
        f"un marqueur trop vieux pour le tampon est COMPTÉ perdu, pas ignoré "
        f"({srv.marqueurs_perdus})")

    # Un marqueur dans le FUTUR est la signature du time_correction() oublié.
    avant = srv.marqueurs_futurs
    srv._marqueurs.append((200.0, {"mode": "p300", "event": "flash", "target": 4}))
    srv.markers_murs("p300", post_s=0.80)
    chk(srv.marqueurs_futurs == avant + 1,
        f"un marqueur très en avance est compté à part : c'est le piège des deux machines "
        f"({srv.marqueurs_futurs})")

    # L'assertion plus haut (« le marqueur d'un AUTRE mode n'est jamais rendu ») ne teste rien
    # à l'endroit où elle est posée : à cet instant, le `break` de maturité arrête déjà la
    # boucle à l'index 1 (le second marqueur p300, pas encore mûr) — le marqueur `errp` d'index 2
    # n'est donc JAMAIS atteint. Elle passerait à l'identique si le filtre
    # `if d.get("mode") != mode_id: continue` était purement supprimé.
    #
    # Scénario dédié, isolé du reste (tampon et file neufs) : le marqueur d'un AUTRE mode est
    # placé AVANT un marqueur p300, tous deux mûrs dans ce même tampon — pour qu'il soit
    # réellement MÛR et EXAMINÉ par la boucle avant qu'un `break` puisse jamais l'atteindre.
    #
    # `.get("target")`, pas `["target"]` : un marqueur errp qui échapperait au filtre n'a pas de
    # clé « target » — s'il se retrouvait dans `murs`, on veut un ÉCHEC propre via `chk`, pas un
    # `KeyError` qui ferait planter le smoke entier avant même d'imprimer le verdict.
    srv.recent_ts = np.arange(200.0, 203.0, 1.0 / fs)
    srv.recent = np.zeros((len(srv.recent_ts), 8))
    srv._marqueurs = [(201.0, {"mode": "errp", "event": "feedback"}),
                      (201.9, {"mode": "p300", "event": "flash", "target": 5})]
    srv._marqueur_curseur = {}
    murs = srv.markers_murs("p300", post_s=0.80)
    chk(len(murs) == 1 and murs[0][1].get("target") == 5,
        f"le marqueur errp, MÛR et EXAMINÉ dans ce même appel, n'empêche pas le p300 valide de "
        f"sortir mais lui-même n'est jamais rendu à p300 ({murs})")

    # Les FRONTIÈRES EXACTES des trois comparaisons. Elles n'étaient testées nulle part : chaque
    # test tombait franchement d'un côté ou de l'autre, donc passer un `>` en `>=` (ou l'inverse)
    # ne faisait rougir aucune assertion. Ce sont pourtant les trois seules décisions de
    # `markers_murs`, et un marqueur pile à la limite est le cas NORMAL d'un émetteur régulier.
    srv.recent_ts = np.arange(300.0, 303.0, 1.0 / fs)
    srv.recent = np.zeros((len(srv.recent_ts), 8))
    vieux, recent = float(srv.recent_ts[0]), float(srv.recent_ts[-1])
    srv._marqueurs = [(recent + MARKER_LATE_S, {"mode": "p300", "event": "flash", "target": 6})]
    srv._marqueur_curseur = {}
    avant_f = srv.marqueurs_futurs
    srv.markers_murs("p300", post_s=0.80)
    chk(srv.marqueurs_futurs == avant_f,
        f"un marqueur PILE à la tolérance de futur n'est pas compté futur : la comparaison est "
        f"strictement > (futurs={srv.marqueurs_futurs}, attendu {avant_f})")

    srv._marqueurs = [(vieux, {"mode": "p300", "event": "flash", "target": 7})]
    srv._marqueur_curseur = {}
    avant_p = srv.marqueurs_perdus
    murs = srv.markers_murs("p300", post_s=0.80)
    chk(srv.marqueurs_perdus == avant_p and [m[1].get("target") for m in murs] == [7],
        f"un marqueur PILE sur le plus vieil échantillon du tampon n'est pas perdu, il sort "
        f"(perdus={srv.marqueurs_perdus}, rendus={[m[1].get('target') for m in murs]})")

    srv._marqueurs = [(recent - 0.80, {"mode": "p300", "event": "flash", "target": 8})]
    srv._marqueur_curseur = {}
    murs = srv.markers_murs("p300", post_s=0.80)
    chk([m[1].get("target") for m in murs] == [8],
        f"un marqueur dont l'époque finit PILE sur le dernier échantillon est MÛR, pas retenu "
        f"un tour de plus ({murs})")

    # Et les compteurs SORTENT : ils étaient incrémentés avec soin et lus par personne, alors que
    # `modes/p300.py` les annonce comme le moyen par lequel trois de ses six pannes sont dites et
    # que `docs/markers.md` promet à l'étudiant qu'il les verra grimper. Ils valent 1 et 1 ici
    # (pas 0), donc un `_state()` qui écrirait des zéros en dur ne passerait pas.
    etat = srv._state(True, calibration=None)
    chk(etat.get("marqueurs", {}).get("perdus") == srv.marqueurs_perdus == 1,
        f"l'état publié porte le compte des marqueurs PERDUS ({etat.get('marqueurs')})")
    chk(etat.get("marqueurs", {}).get("futurs") == srv.marqueurs_futurs == 1,
        f"...et celui des marqueurs FUTURS ({etat.get('marqueurs')})")
    chk(etat.get("marqueurs", {}).get("illisibles") == 0
        and etat.get("marqueurs", {}).get("inlet_erreurs") == 0,
        f"...et les deux autres, à zéro tant que rien n'a mal tourné ({etat.get('marqueurs')})")
    chk(etat.get("marqueurs", {}).get("connecte") is False,
        f"...et l'état dit aussi si l'oreille est CONNECTÉE ({etat.get('marqueurs')})")
    # Un compteur ne doit PAS compter comme un changement d'état : sans ça la déduplication du
    # flux `status` tombe et le moteur émet à 20 Hz au lieu de 0,5 Hz (mesuré une fois à 19,6 Hz).
    cle_avant = srv._status_key(True)
    srv.marqueurs_perdus += 100
    chk(srv._status_key(True) == cle_avant,
        "un compteur qui bouge ne déclenche PAS une republication d'état (déduplication)")

    print(f"[smoke-marqueurs] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_marqueurs_file_coincee():
    """Un marqueur ABERRANT (futur) ne doit jamais coincer ceux qui le suivent dans la file.

    Contrôler la MATURITÉ avant le FUTUR (l'ordre initialement proposé pour `markers_murs`) a
    deux défauts d'un coup : un marqueur horodaté loin dans le futur n'est par définition jamais
    « mûr », donc il déclenche le `break` avant même d'atteindre le contrôle du futur —
    `marqueurs_futurs` devient inatteignable, et surtout le curseur ne le dépasse JAMAIS. Ce
    marqueur reste indéfiniment le premier examiné, et tout ce qui le suit dans la file — y
    compris des marqueurs par ailleurs parfaitement valides — reste bloqué derrière lui, pour
    toujours. C'est exactement ce que produit un `time_correction()` oublié entre deux machines :
    la panne la plus coûteuse possible, puisqu'elle ne se limite pas à perdre CE marqueur-là, elle
    fait taire tout le flux qui suit.

    Ce test place volontairement le marqueur futur AVANT un marqueur valide dans la file, pour
    distinguer cette conséquence (silence permanent) du simple mauvais comptage que
    `_smoke_marqueurs_murs` détecte déjà de son côté. Sans cette disposition précise, une version
    fautive et une version correcte de `markers_murs` passent toutes les deux.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    srv = EngineServer(synthetic=True, modes=(), params={}, instance="smoke-marqueurs-file")
    fs = srv.acq.fs
    srv.recent_ts = np.arange(100.0, 103.0, 1.0 / fs)
    srv.recent = np.zeros((len(srv.recent_ts), 8))

    # Le marqueur futur est placé EN PREMIER dans la file, DEVANT un marqueur par ailleurs mûr,
    # du bon mode et dans le tampon — c'est la position qui coince tout dans la version fautive.
    srv._marqueurs = [(9999.0, {"mode": "p300", "event": "flash", "target": 9}),
                      (101.0, {"mode": "p300", "event": "flash", "target": 1})]
    srv._marqueur_curseur = {}

    avant = srv.marqueurs_futurs
    murs = srv.markers_murs("p300", post_s=0.80)
    chk([m[1].get("target") for m in murs] == [1],
        f"un marqueur futur placé DEVANT un marqueur valide ne le bloque pas : le valide sort "
        f"quand même ({murs})")
    chk(srv.marqueurs_futurs == avant + 1,
        f"...et le futur est COMPTÉ au passage, pas seulement sauté en silence "
        f"({srv.marqueurs_futurs})")

    print(f"[smoke-marqueurs-file] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_marqueurs_inlet():
    """Le cycle de vie de l'inlet : créé PARESSEUSEMENT, y compris pour un mode démarré tard.

    `_smoke_marqueurs_murs` et `_smoke_marqueurs_file_coincee` fixent `_marqueurs` et
    `_marqueur_curseur` à la main : ils ne touchent jamais `marker_inlet`, `_ouvre_marker_inlet`,
    `_tire_marqueurs` ni `_purge_marqueurs`. C'est précisément par ce trou qu'un mode marqueur
    démarré APRÈS le début de la boucle pouvait ne JAMAIS trouver d'inlet — indiscernable d'un
    flux calme, sans le moindre message.
    """
    import threading

    from core.modes import registry as _registry
    from core.modes.contract import ModeSpec
    from core.modes.runtime import ModeRuntime

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # Spec de test, absente du vrai catalogue. `runtime_cls=ModeRuntime` : la classe de BASE,
    # sûre à instancier telle quelle (déjà fait par `_smoke_repos_partage`) — `_open`/`_close`/
    # `_run_step` y sont des no-op. `rest=None` : elle démarre directement en "running", sans
    # séquence chauffe/repos à gérer ici.
    ecoute = ModeSpec(id="smoke-ecoute", label="Écoute (test)", family="actif", summary="",
                      status="moteur", stream="decoded_smoke_ecoute", channels=("x",),
                      marker_epoch_s=0.8, runtime_cls=ModeRuntime)

    # --- A. Le CRITIQUE 1 : un mode marqueur démarré APRÈS le début de la boucle --------------
    instance = "smoke-marqueurs-inlet"
    srv = EngineServer(synthetic=True, modes=(), instance=instance)
    thread = threading.Thread(target=srv.run, kwargs={"duration_s": 5.0}, daemon=True)
    thread.start()

    time.sleep(0.3)     # plusieurs tours de boucle, encore AUCUN mode marqueur actif
    chk(srv.marker_inlet is None,
        "tant qu'aucun mode actif n'écoute les marqueurs, aucun inlet n'est créé")

    # `ecoute` n'est pas dans `registry.MODES` : on l'y ajoute le temps de ce test, pour que
    # `_start` (appelé par `_drain_commands` → `_apply`, DANS le fil de `run()`) puisse la
    # trouver. La commande part directement dans la file THREAD-SAFE de `srv` — exactement ce
    # que fait `submit("start_mode", ...)`, sans sa validation (qui a besoin de `registry.BY_ID`,
    # pas seulement de `registry.MODES`) : c'est le fil de `run()` qui la traite à son prochain
    # tour, jamais ce fil-ci — aucune mutation croisée de `srv.active` entre les deux fils.
    avant_registre = _registry.MODES
    _registry.MODES = avant_registre + (ecoute,)
    try:
        srv._commands.put(
            ("start_mode", {"ids": ["smoke-ecoute"], "params": {"smoke-ecoute": {}}}))

        echeance = time.time() + 5.0
        while srv.marker_inlet is None and time.time() < echeance and thread.is_alive():
            time.sleep(0.05)
        chk(srv.marker_inlet is not None,
            "un mode marqueur démarré APRÈS le début de la boucle obtient quand même un inlet — "
            "le CRITIQUE 1 : évalué hors boucle, ce `marker_inlet` resterait None pour toujours")
    finally:
        _registry.MODES = avant_registre
        srv.stop()
        thread.join(timeout=5.0)

    # --- B, C, D, E : purge, arrêt, robustesse — sur un moteur qui ne tourne pas ---------------
    srv2 = EngineServer(synthetic=True, modes=(), params={}, instance="smoke-marqueurs-inlet-2")
    a = ModeSpec(id="smoke-marqueur-a", label="A", family="actif", summary="", status="moteur",
                stream="decoded_smoke_a", channels=("x",), marker_epoch_s=0.8,
                runtime_cls=ModeRuntime)
    b = ModeSpec(id="smoke-marqueur-b", label="B", family="actif", summary="", status="moteur",
                stream="decoded_smoke_b", channels=("x",), marker_epoch_s=0.8,
                runtime_cls=ModeRuntime)
    srv2.active["smoke-marqueur-a"] = ModeRuntime(a, {}, srv2)
    srv2.active["smoke-marqueur-b"] = ModeRuntime(b, {}, srv2)

    # B. Le CRITIQUE 2 : un mode ACTIF qui écoute mais n'a pas encore de curseur compte comme 0.
    srv2._marqueurs = [(float(i), {"mode": "smoke-marqueur-a", "event": "flash"})
                       for i in range(5000)]
    srv2._marqueur_curseur = {"smoke-marqueur-a": 3000}   # "b" encore en chauffe : pas d'entrée
    srv2._purge_marqueurs()
    chk(len(srv2._marqueurs) == 5000,
        f"« b » actif sans curseur compte comme 0 : la purge n'a PAS lieu, rien n'est jeté "
        f"avant qu'il ait pu consommer ({len(srv2._marqueurs)} marqueurs restants)")

    # Contrôle positif : une fois que LES DEUX ont un curseur, la coupe reprend, à leur MINIMUM.
    srv2._marqueur_curseur["smoke-marqueur-b"] = 2500
    srv2._purge_marqueurs()
    chk(len(srv2._marqueurs) == 2500
        and srv2._marqueur_curseur == {"smoke-marqueur-a": 500, "smoke-marqueur-b": 0},
        f"...et une fois que LES DEUX ont un curseur, la coupe reprend à leur MINIMUM "
        f"({len(srv2._marqueurs)} marqueurs, curseurs {srv2._marqueur_curseur})")

    # C. L'IMPORTANT 3 : _stop_mode nettoie le curseur du mode qu'il arrête.
    srv2._marqueur_curseur["smoke-marqueur-a"] = 12345
    srv2._stop_mode("smoke-marqueur-a")
    chk("smoke-marqueur-a" not in srv2._marqueur_curseur,
        f"_stop_mode retire le curseur du mode qu'il arrête ({srv2._marqueur_curseur})")

    # D. L'IMPORTANT 4 : une exception de l'inlet est comptée, pas avalée en silence.
    # Le faux inlet porte les MÊMES attributs que le vrai (`illisibles`, `lache`) : un double de
    # test qui n'expose qu'une partie de l'interface finit par diverger d'elle en silence, et
    # c'est alors le test qui casse au lieu du code.
    class _InletExplosif:
        connecte = True
        illisibles = 0
        nom = "inlet-explosif"
        refus = ""

        def resolve(self):
            return True

        def lache(self, raison=""):
            return False

        def pull(self):
            raise RuntimeError("réseau perdu (simulé)")

    srv2.marker_inlet = _InletExplosif()
    avant = srv2.marqueurs_inlet_erreurs
    srv2._tire_marqueurs()
    chk(srv2.marqueurs_inlet_erreurs == avant + 1,
        f"une exception de l'inlet est COMPTÉE, pas avalée en silence "
        f"({srv2.marqueurs_inlet_erreurs})")

    # E. Le chemin nominal : rien ne publie sous ce nom sur ce réseau, resolve() échoue
    #    proprement, pull() sur un inlet non connecté ne lève pas, et un second appel n'ouvre
    #    pas un second inlet (pas de nouvelle résolution réseau à chaque tour).
    srv2.marker_inlet = None
    srv2._ouvre_marker_inlet()
    chk(srv2.marker_inlet is not None, "« b », toujours actif, obtient bien un inlet")
    chk(srv2.marker_inlet.connecte is False,
        "aucune application de stimulus ne tourne sur ce réseau : l'inlet existe, non connecté")
    chk(srv2.marker_inlet.pull() == [], "tirer sur un inlet non connecté rend [], sans lever")
    objet_avant = srv2.marker_inlet
    srv2._ouvre_marker_inlet()
    chk(srv2.marker_inlet is objet_avant, "un appel suivant ne recrée pas l'inlet (idempotent)")

    # `srv2` n'est jamais passé par `run()`, or c'est le `finally` de `run()` qui casse le cycle
    # `EngineServer ↔ ModeRuntime` (un runtime garde `self.engine`). Laissé vivant, ce cycle
    # retarde le nettoyage du `BoardShim` jusqu'à un passage du ramasse-miettes cyclique, et son
    # `__del__` tardif peut alors libérer la session d'un AUTRE moteur du même processus — le
    # destructeur zombie documenté le 2026-07-28 (`BOARD_NOT_CREATED_ERROR`). Inoffensif ici
    # seulement parce qu'aucun sous-test ne démarre de board APRÈS celui-ci ; ça ne se remarque
    # pas quand ça cesse d'être vrai, donc on casse le cycle explicitement.
    srv2.active = {}

    print(f"[smoke-marqueurs-inlet] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_marqueurs_relance():
    """L'émetteur meurt, puis REVIENT. Le moteur doit le réentendre tout seul.

    « Je ferme le stimulus et je le relance » est un geste de routine en TP, et c'était la panne
    la plus coûteuse du sous-système : l'inlet n'était re-résolu que `if not connecte`, `connecte`
    restait `True` à vie, et le `recover=True` par défaut faisait attendre indéfiniment le retour
    de l'ANCIEN `source_id` — que l'émetteur de référence déclare par PID, donc qui ne revient
    jamais. Mesuré, deux processus, avant correctif :

        [B] émetteur #1 vivant : 13 marqueurs | [C] fermé : 1 | [D] #2 RELANCÉ : 0 -> MUET
        [E] un inlet NEUF : 13 -> le flux #2 est pourtant bien là

    Aucune exception, `marqueurs_inlet_erreurs` immobile à 0, et redémarrer le mode n'y changeait
    rien. Avec `recover=False`, la disparition lève `LostError`, `MarkerInlet.pull` lâche l'inlet,
    et la boucle re-résout : mesuré 51 marqueurs après relance, contre 0.

    ⚠️ Ce test ne lance PAS deux processus : détruire le `StreamOutlet` côté Python suffit à
    produire exactement le même `LostError` côté inlet (vérifié en sonde avant d'écrire ce test —
    même enchaînement B/C/D/E/F que la mesure à deux processus ci-dessus). Ce qu'il ne couvre
    donc PAS, et qu'il faut savoir : la mort BRUTALE d'un processus émetteur (Ctrl-C, plantage),
    où c'est le système qui ferme les sockets. La sonde à deux processus a montré le même
    comportement dans ce cas, mais elle n'est pas rejouée ici.
    """
    import io
    import types
    from contextlib import redirect_stdout

    from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, local_clock

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    nom = "EEG_API_Unicorn_smoke_relance"

    def faux_runtime():
        """Un écouteur minimal : `_stop_mode` et `_nom_flux_marqueurs` n'en demandent pas plus.

        Un vrai `P300Runtime` exigerait un modèle entraîné, que ce test n'a aucune raison d'avoir.
        """
        rt = types.SimpleNamespace()
        rt.spec = types.SimpleNamespace(marker_epoch_s=0.8, label="Écoute (test)")
        rt.params = {"stream_in": nom}
        rt.phase = "running"
        rt.close = lambda: None
        return rt

    def tourne(srv, secondes, condition):
        """Fait tourner `_tire_marqueurs` comme la boucle du moteur, jusqu'à `condition`."""
        echeance = time.time() + secondes
        while time.time() < echeance:
            srv._tire_marqueurs()
            if condition():
                return True
            time.sleep(0.05)
        return False

    srv = EngineServer(synthetic=True, modes=(), params={}, instance="smoke-marqueurs-relance")
    srv.active = {"smoke-ecoute": faux_runtime()}

    # --- A. Un premier émetteur : le moteur se connecte et reçoit. -----------------------------
    o1 = StreamOutlet(StreamInfo(nom, "Markers", 1, IRREGULAR_RATE, "string", "smoke-emetteur-1"))
    try:
        srv._ouvre_marker_inlet()
        tourne(srv, 10.0, lambda: srv.marker_inlet is not None and srv.marker_inlet.connecte)
        chk(srv.marker_inlet is not None and srv.marker_inlet.connecte,
            "le moteur se connecte au premier émetteur")
        o1.push_sample(['{"mode":"p300","event":"flash","target":1}'], timestamp=local_clock())
        tourne(srv, 5.0, lambda: bool(srv._marqueurs))
        chk(len(srv._marqueurs) == 1 and srv._marqueurs[0][1].get("target") == 1,
            f"...et ses marqueurs arrivent ({srv._marqueurs})")
    finally:
        del o1

    # --- B. L'émetteur DISPARAÎT : l'inlet doit redevenir « non connecté ». (IMPORTANT 1.5) ----
    avant_erreurs = srv.marqueurs_inlet_erreurs
    vu = tourne(srv, 20.0, lambda: not srv.marker_inlet.connecte)
    chk(vu and not srv.marker_inlet.connecte,
        "l'émetteur disparu, l'inlet redevient NON CONNECTÉ — sans quoi le moteur se croit "
        "connecté pour toujours et ne re-résout jamais")
    chk(srv.marqueurs_inlet_erreurs > avant_erreurs,
        f"...et l'incident est COMPTÉ, pas avalé ({srv.marqueurs_inlet_erreurs})")

    # --- C. Un émetteur NEUF (source_id différent, comme un vrai relancement). (CRITIQUE 1.4) --
    o2 = StreamOutlet(StreamInfo(nom, "Markers", 1, IRREGULAR_RATE, "string", "smoke-emetteur-2"))
    try:
        srv._marqueurs = []
        srv._marqueur_curseur = {}
        tourne(srv, 15.0, lambda: srv.marker_inlet.connecte)
        chk(srv.marker_inlet.connecte,
            "le moteur se RECONNECTE tout seul à l'émetteur relancé : c'est le CRITIQUE 1.4, "
            "où il restait muet pour toujours sans qu'aucun compteur ne bouge")
        o2.push_sample(['{"mode":"p300","event":"flash","target":2}'], timestamp=local_clock())
        tourne(srv, 5.0, lambda: bool(srv._marqueurs))
        chk(len(srv._marqueurs) >= 1 and srv._marqueurs[-1][1].get("target") == 2,
            f"...et les marqueurs du NOUVEL émetteur arrivent vraiment ({srv._marqueurs})")
    finally:
        del o2

    # --- D. Le message d'erreur est LIMITÉ EN CADENCE. ----------------------------------------
    # Mesuré avant correctif : 310 exceptions en 20 s, soit 20 lignes par seconde, qui noient le
    # journal des modes qui tournent à côté. On martèle 50 tours sur un inlet qui échoue toujours
    # et on COMPTE les lignes imprimées, plutôt que de faire confiance à la relecture.
    class _InletMort:
        connecte = True
        illisibles = 0
        nom = "inlet-mort"
        refus = ""

        def resolve(self):
            return True

        def lache(self, raison=""):
            return False

        def pull(self):
            raise RuntimeError("réseau perdu (simulé)")

    srv.marker_inlet = _InletMort()
    srv._marqueur_erreur_dite_a = 0.0
    srv._marqueur_erreurs_tues = 0
    avant_erreurs = srv.marqueurs_inlet_erreurs
    capture = io.StringIO()
    with redirect_stdout(capture):
        for _ in range(50):
            srv._tire_marqueurs()
    lignes = [ligne for ligne in capture.getvalue().splitlines()
              if "inlet de marqueurs en erreur" in ligne]
    chk(len(lignes) == 1,
        f"50 tours en erreur = UN seul message, pas 50 ({len(lignes)}) : {lignes[:2]}")
    chk(srv.marqueurs_inlet_erreurs == avant_erreurs + 50,
        f"...mais les 50 incidents sont TOUS comptés — limiter la cadence n'autorise pas à "
        f"cacher le nombre ({srv.marqueurs_inlet_erreurs - avant_erreurs})")

    # --- E. Le dernier écouteur s'arrête : l'inlet est LÂCHÉ, le tampon aussi. -----------------
    srv.marker_inlet = None
    srv._ouvre_marker_inlet()
    chk(srv.marker_inlet is not None, "un écouteur actif : un inlet existe")
    srv._marqueurs = [(1.0, {"mode": "p300", "event": "flash", "target": 0})]
    srv._stop_mode("smoke-ecoute")
    chk(srv.marker_inlet is None,
        "arrêter le DERNIER écouteur libère l'inlet — sans ça, `_ouvre_marker_inlet` ne recrée "
        "jamais rien et redémarrer le mode ne répare pas")
    chk(srv._marqueurs == [] and srv._marqueur_curseur == {},
        f"...et le tampon de marqueurs part avec lui, plutôt que de croître sans personne pour "
        f"le lire ({srv._marqueurs})")
    srv.active = {"smoke-ecoute": faux_runtime()}
    srv._ouvre_marker_inlet()
    chk(srv.marker_inlet is not None,
        "...et redémarrer un mode marqueur en ouvre un NEUF, qui peut donc trouver le nouvel "
        "émetteur")
    srv.active = {}

    print(f"[smoke-marqueurs-relance] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_marqueurs_stream_in():
    """`stream_in` doit vraiment choisir le flux écouté, pas rester un réglage-décor.

    Avant ce correctif, `_ouvre_marker_inlet` avait `MARKER_STREAM_DEFAULT` EN DUR : le réglage
    « Flux de marqueurs » du P300 s'affichait dans la console, se validait, se sauvegardait — et
    ne servait à RIEN. `_nom_flux_marqueurs` fait des runtimes FABRIQUÉS (`types.SimpleNamespace`,
    pas un vrai `P300Runtime` : ça éviterait un modèle entraîné pour rien) pour ne pas dépendre
    d'un mode marqueur réel — seul le P300 en a un aujourd'hui, un futur mode pourrait s'y ajouter
    sans que ce test doive changer.
    """
    import io
    import types
    from contextlib import redirect_stdout

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    def faux_runtime(marker_epoch_s, stream_in=None):
        rt = types.SimpleNamespace()
        rt.spec = types.SimpleNamespace(marker_epoch_s=marker_epoch_s)
        rt.params = {"stream_in": stream_in} if stream_in is not None else {}
        return rt

    srv = EngineServer(synthetic=True, modes=(), params={}, instance="smoke-marqueurs-stream-in")

    # 1. Aucun mode actif n'écoute les marqueurs -> le défaut.
    srv.active = {}
    chk(srv._nom_flux_marqueurs() == MARKER_STREAM_DEFAULT,
        f"sans mode marqueur actif, le défaut ({srv._nom_flux_marqueurs()})")

    # 2. Un mode qui écoute, avec un nom personnalisé -> CE nom, pas le défaut en dur.
    srv.active = {"p300": faux_runtime(0.95, stream_in="mon_flux_perso")}
    chk(srv._nom_flux_marqueurs() == "mon_flux_perso",
        f"le nom déclaré par le mode actif est repris ({srv._nom_flux_marqueurs()})")

    # 3. Un mode actif qui n'écoute PAS les marqueurs (marker_epoch_s == 0) ne pèse pas sur le
    # choix, même s'il portait un stream_in par accident (cas hypothétique aujourd'hui : aucun
    # mode du registre actuel n'est dans ce cas).
    srv.active = {"ssvep": faux_runtime(0.0, stream_in="ignore_moi"),
                 "p300": faux_runtime(0.95, stream_in="mon_flux_perso")}
    chk(srv._nom_flux_marqueurs() == "mon_flux_perso",
        "un mode qui ne consomme pas de marqueurs ne pèse pas sur le choix, même avec stream_in")

    # 4. Un mode marqueur qui NE DÉCLARE PAS `stream_in` (aucun aujourd'hui, un futur mode
    # pourrait) compte pour le défaut, pas pour une absence.
    srv.active = {"futur-mode": faux_runtime(0.5)}
    chk(srv._nom_flux_marqueurs() == MARKER_STREAM_DEFAULT,
        f"un mode marqueur sans stream_in déclaré retombe sur le défaut "
        f"({srv._nom_flux_marqueurs()})")

    # 5. DEUX modes actifs réclament des noms DIFFÉRENTS -> dit BRUYAMMENT, choix déterministe.
    srv.active = {"p300": faux_runtime(0.95, stream_in="flux_a"),
                 "smoke-ecoute": faux_runtime(0.8, stream_in="flux_b")}
    capture = io.StringIO()
    with redirect_stdout(capture):
        nom = srv._nom_flux_marqueurs()
    texte = capture.getvalue()
    print(texte, end="")
    chk(nom in ("flux_a", "flux_b"), f"un choix est fait malgré le désaccord ({nom})")
    chk("flux_a" in texte and "flux_b" in texte and "désaccord" in texte,
        f"...et il est dit BRUYAMMENT, en nommant les deux flux en désaccord ({texte!r})")

    # 6. Preuve BOUT EN BOUT : `_ouvre_marker_inlet` (pas seulement le helper isolé) crée bien
    # son inlet sur le nom du mode actif — c'est LA méthode qui portait `MARKER_STREAM_DEFAULT`
    # en dur avant ce correctif, celle que la preuve rouge/vert du rapport casse et répare.
    srv2 = EngineServer(synthetic=True, modes=(), params={}, instance="smoke-marqueurs-stream-in-2")
    srv2.active = {"p300": faux_runtime(0.95, stream_in="flux_bout_en_bout")}
    srv2._ouvre_marker_inlet()
    chk(srv2.marker_inlet is not None
        and srv2.marker_inlet.nom == "flux_bout_en_bout",
        f"_ouvre_marker_inlet crée son inlet sur le nom du mode actif, pas le défaut en dur "
        f"({srv2.marker_inlet.nom if srv2.marker_inlet else None})")

    print(f"[smoke-marqueurs-stream-in] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _parse_args(argv):
    p = argparse.ArgumentParser(description="EEG_API_Unicorn — moteur headless, sorties LSL.")
    p.add_argument("--synthetic", action="store_true", help="board de test BrainFlow (sans casque)")
    p.add_argument("--serial", default=None, help="numéro de série Unicorn (si plusieurs appairés)")
    p.add_argument("--duration", type=float, default=None, help="durée en s (défaut : jusqu'à Ctrl+C)")
    p.add_argument("--mode", default=None,
                   help="décodeurs à démarrer, séparés par des virgules : "
                        + ", ".join(s.id for s in registry.runnable() if s.id != "raw")
                        + ". Ils tournent EN MÊME TEMPS et partagent une seule phase de repos. "
                          "Le brut est diffusé en plus, sauf avec --no-raw")
    p.add_argument("--no-raw", action="store_true",
                   help="ne pas diffuser le signal brut (le décodage continue)")
    p.add_argument("--freqs", default=None,
                   help="fréquences des cibles affichées par l'appli cliente, ex. 15,20,8.571 "
                        "(diviseurs entiers du refresh — 8,571 est 60/7, et 8,57 serait refusé) "
                        "(mode ssvep uniquement)")
    p.add_argument("--refresh", type=float, default=None,
                   help="refresh de l'écran qui affiche le stimulus : le moteur en déduit les "
                        "mêmes fréquences que src/research/ssvep_stimulus.py lancé avec ce "
                        "refresh (mode ssvep uniquement)")
    p.add_argument("--baseline", type=float, default=None,
                   help="durée du repos initial en s, pour TOUS les modes démarrés ensemble "
                        "(défaut : celle du contrat de chaque mode, voir modes/ssvep.py et "
                        "modes/neuro.py)")
    p.add_argument("--warmup", type=float, default=None,
                   help="stabilisation jetée avant le repos, dérive DC des électrodes sèches, "
                        "pour TOUS les modes démarrés ensemble (défaut : celle du contrat de "
                        "chaque mode)")
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

    modes = [m.strip() for m in (args.mode or "").split(",") if m.strip()]
    if not args.no_raw:
        modes.insert(0, "raw")
    params = {}
    if args.freqs:
        params["ssvep"] = {"freqs": [float(f) for f in args.freqs.split(",")]}
    elif args.refresh:
        params["ssvep"] = {"freqs": [c["actual_hz"] for c in choose_frequencies(args.refresh)]}
    # `_prepare` ignore de toute façon un réglage dont le mode n'a pas été demandé (elle boucle
    # sur `registry.MODES` et ne lit `params.get(spec.id)` que pour les id présents dans
    # `modes`) : filtrer ici est donc redondant pour la validité. On le fait quand même — un
    # `--freqs` donné sans `--mode ssvep` ne doit pas laisser un réglage mort dans ce qui part
    # au moteur, même inoffensif.
    params = {mode_id: settings for mode_id, settings in params.items() if mode_id in modes}
    # `_prepare` refuse un réglage invalide en levant un `ValueError` dont le message est déjà
    # rédigé pour être lu. Un traceback autour ne dit rien de plus et enterre ce message sous
    # quinze lignes de pile — or c'est le PREMIER contact de tout étudiant qui lance `--mode mi`
    # avant d'avoir calibré : sans modèle entraîné, ce refus est le comportement normal du mode,
    # pas un plantage. Code de sortie 2 : « la commande est mal formée », comme argparse.
    try:
        engine = EngineServer(serial=args.serial, synthetic=args.synthetic, verbose=args.verbose,
                              modes=modes, params=params, instance=args.instance)
    except ValueError as refus:
        print(f"[server] {refus}")
        sys.exit(2)
    # Ctrl+C doit fermer PROPREMENT la session BrainFlow : une session laissée ouverte
    # empêche la suivante de s'ouvrir (BOARD_NOT_READY au relancement).
    signal.signal(signal.SIGINT, lambda *_: engine.stop())
    print("[server] Ctrl+C pour arrêter.")
    engine.run(duration_s=args.duration, baseline_s=args.baseline, warmup_s=args.warmup)
