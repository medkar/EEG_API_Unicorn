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

SSVEP et neuro illustrent les deux familles de la BCI, et un client ne doit pas les traiter
pareil : le SSVEP est **actif** (l'utilisateur choisit, il y a une bonne réponse, un stimulus est
requis côté client), le neuro est **passif** (on observe un état, il n'y a rien à choisir et
aucun stimulus).

Pas encore dans le moteur : MI, c-VEP, P300, ErrP — voir `src/core/modes/registry.py` pour le
catalogue complet ; ils restent l'affaire de `src/research/app.py`. Pas encore non plus : le
control plane entrant, les marqueurs.

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
    python src/core/server.py --mode ssvep,neuro        # plusieurs modes EN MÊME TEMPS
    python src/core/server.py --mode neuro --no-raw     # sans le flux brut
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
from core.config import (CH_NAMES, NEURO_WINDOW_S, choose_frequencies,  # noqa: E402
                    json_float, reference_lost, use_utf8_console)
from core.lsl_io import (ClockBridge, DecodedNeuroPublisher, QualityPublisher,  # noqa: E402
                    StatusPublisher, default_instance_id, stream_name, verdict_from_sigma)
from core.modes import contract, registry  # noqa: E402

# Cadence de la boucle. On ne publie PAS échantillon par échantillon : on ramasse ~50 ms de
# signal d'un coup. Assez court pour rester très en dessous des fenêtres de décision d'un
# mode BCI (1-2 s), assez long pour ne pas réveiller le processus 250 fois par seconde.
POLL_S = 0.05
QUALITY_PERIOD_S = 1.0    # cadence du flux `quality`
STATUS_PERIOD_S = 2.0     # rappel périodique de l'état (pour un client qui arrive en retard)
QUALITY_WINDOW_S = 2.0    # longueur de signal sur laquelle on mesure le σ par voie


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
        self.active = {}            # {mode_id: ModeRuntime}, dans l'ordre du registre
        self.rest_instruction = ""  # la consigne du repos en cours, partagée s'il l'est
        self._stop = False
        self._last_tick = {}
        self._commands = queue.Queue()
        self._quality = None
        self._reference_lost = None
        self._warmup_override = None
        self._rest_override = None

        # Le tampon doit satisfaire le plus gourmand des consommateurs : la qualité veut
        # QUALITY_WINDOW_S, le SSVEP WINDOW_S, le neuro NEURO_WINDOW_S — chacun plus la marge de
        # filtre. On dimensionne sur TOUS les modes, pas sur ceux qui tournent : démarrer un mode
        # en cours de séance ne doit pas dépendre de la taille d'un tampon.
        self.keep = max(int(QUALITY_WINDOW_S * self.acq.fs),
                        int(NEURO_WINDOW_S * self.acq.fs),
                        self.acq.window_n) + self.acq.margin_n

        self._pending = self._prepare(modes or (), params or {})

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
        ancien.close()
        runtime = spec.runtime_cls(spec, values, self)
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

    # --- API de commande interne (SPEC §12.1) --------------------------------
    # La console et, plus tard, l'adaptateur de commandes LSL passent tous les deux PAR ICI.
    # Un seul chemin à tester, et le protocole de contrôle reste remplaçable sans réécrire le
    # moteur.
    #
    # Les commandes ne sont PAS appliquées par le fil qui les soumet : elles sont mises en file
    # et exécutées par la boucle. C'est ce qui garantit que la session BrainFlow n'est touchée
    # que depuis un seul fil — la partager entre l'interface et l'acquisition produirait des
    # corruptions qu'aucun test ne rattraperait.

    COMMANDS = ("start_mode", "stop_mode", "set_params", "set_published", "recalibrate", "stop")

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

    def _phase_of(self, active):
        """La phase publique, calculée sur une COPIE de la table des modes actifs.

        Séparée de la propriété pour que `_state` puisse la calculer sur la MÊME copie que le
        reste de son payload : deux copies distinctes laisseraient `phase` et `modes` se
        contredire à l'intérieur d'un seul appel. `active` doit déjà être une copie — cette
        méthode ne protège rien elle-même, elle fait confiance à l'appelant (voir `phase` et
        `_state` pour les deux qui en fournissent une).
        """
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
        fil : ELLE copie `self.active` avant de le lire — une propriété nue ne peut pas recevoir
        la copie déjà prise par un appelant, donc c'est ici, et nulle part ailleurs, qu'elle doit
        se faire. `_smoke_ssvep`/`_smoke_neuro` sondent `server.phase` depuis le fil du test
        pendant que la boucle du moteur tourne sur le sien : exactement la lecture inter-fils
        que cette copie protège.

        « streaming » quand aucun mode actif n'a de repos à faire : c'est le cas du brut seul.
        """
        return self._phase_of(dict(self.active))

    def _status_key(self, running):
        """Ce qui constitue un vrai CHANGEMENT d'état — hors compteurs (cf. StatusPublisher.push).

        Un compteur glissé ici défait la déduplication : mesuré une fois à 19,6 Hz de messages
        d'état au lieu de 0,5 Hz, assez discret pour passer inaperçu, assez bruyant pour noyer
        un client.
        """
        return (running, self.synthetic, self.phase,
                tuple((mid, r.phase, r.published) for mid, r in sorted(self.active.items())))

    def _state(self, running, active=None):
        """État public (`status` / `snapshot`).

        `active` : copie déjà prise de `self.active`, à passer quand l'appelant en a déjà une
        (voir `snapshot`) pour ne pas en reprendre une seconde qui pourrait différer de la
        première si la boucle a bougé entre-temps. Sans argument, `_state` en prend une elle-même
        — jamais `self.active` en direct : un `for mid in self.active` ou un dict-comprehension
        sur `self.active.items()` itère le dict VIVANT, et la boucle peut démarrer ou arrêter un
        mode entre deux pas de cette itération (elle tourne sur un autre fil que l'appelant de
        `snapshot`) — ce qui lève `RuntimeError: dictionary changed size during iteration` chez
        l'appelant. `dict(self.active)` copie en C, sans repasser la main : c'est pour ça que la
        boucle de `run()` fait déjà `list(self.active.items())` avant d'itérer, même depuis SON
        propre fil.

        Même discipline pour la phase : on appelle `_phase_of(active)` sur CETTE copie, une
        seule fois, plutôt que de lire la propriété `self.phase` (qui en reprendrait une AUTRE,
        à un instant différent). Deux copies pourraient se contredire — `modes` listant un mode
        que `phase` ne voit plus, par exemple — la même copie ne le peut pas.
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
        phase = self._phase_of(active)
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
        }
        if self.rest_instruction and phase in ("warmup", "baseline"):
            state["instruction"] = self.rest_instruction
        return state

    def snapshot(self):
        """État complet pour un afficheur, en lecture seule. Sûr depuis un autre fil.

        La console (tâches 11-15) sonde ceci depuis le fil Qt, à 10 Hz, pendant que la boucle du
        moteur tourne sur le sien et peut démarrer ou arrêter un mode À TOUT INSTANT. On prend
        donc UNE SEULE copie atomique de `self.active` (`dict(...)`, copié en C d'un coup — pas
        de point où l'autre fil pourrait s'intercaler) et on la fait servir PARTOUT dans cet
        appel : à `_state()` d'abord, à `modes_state` ensuite. Reprendre `self.active` une
        seconde fois pour `modes_state` referait courir le même risque, ET pourrait rendre un
        `modes_state` qui ne correspond plus au `modes` déjà écrit dans `state` (un mode présent
        dans l'un, absent de l'autre) si la boucle a bougé entre les deux lectures. On rend
        ensuite un dictionnaire déjà construit plutôt que des références vers l'état vivant :
        l'appelant ne peut donc pas lire une valeur à moitié écrite par la boucle.
        """
        active = dict(self.active)
        state = self._state(not self._stop, active=active)
        state.update({
            "quality": self._quality,
            "rest_instruction": self.rest_instruction,
            "modes_state": {mid: r.state() for mid, r in active.items()},
            "catalog": registry.catalog(),
        })
        return state

    def recent_window(self, seconds):
        """Copie des `seconds` dernières secondes de signal BRUT (n, 8), ou None.

        Accesseur PUBLIC pour un afficheur. Le tampon est réécrit par le fil d'acquisition : le
        lire directement depuis le fil Qt donnerait, tôt ou tard, une vue à moitié écrite. On
        rend donc une copie — c'est quelques centaines de Ko, payés une fois par rafraîchissement.
        """
        buffer = self.recent
        if buffer is None or len(buffer) == 0:
            return None
        n = max(1, int(seconds * self.acq.fs))
        return np.array(buffer[-n:], dtype=float, copy=True)

    def _publish_quality(self, lsl_ts):
        """σ par voie sur les dernières secondes, calculé sur du signal FILTRÉ.

        Le filtrage est indispensable ICI (contrairement au flux brut) : sur du signal
        quasi-brut, le σ est dominé par le ronflement secteur 50 Hz et la dérive lente des
        électrodes sèches, pas par l'EEG — un σ mesuré ainsi ne dit rien de l'état du contact.

        Le calcul est délégué à `sigma_from_block` pour partager UNE seule définition du σ
        avec l'écran `signal_check` de l'appli : deux mesures de qualité qui divergeraient
        seraient pires que pas de mesure du tout.
        """
        sigmas = self.acq.sigma_from_block(self.recent)
        if sigmas is None:
            return
        self.quality_out.push(sigmas, lsl_ts)
        # Référence décrochée : invisible sur les σ, fatale pour la séance. On le dit
        # une fois par changement d'état plutôt qu'à chaque seconde.
        common = self.acq.common_mode(self.recent)
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
            self._start([s.id for s, _ in self._pending],
                        {s.id: v for s, v in self._pending}, time.perf_counter())
            self.status_out.push(self._state(True), key=self._status_key(True), force=True)

            try:
                while not self._stop:
                    self._drain_commands()
                    now = time.perf_counter()
                    if duration_s is not None and now - started >= duration_s:
                        break

                    # UNE seule lecture par tour, quels que soient les modes actifs :
                    # `get_new_data()` VIDE le tampon de BrainFlow. C'est l'invariant central du
                    # moteur — c'est aussi pourquoi le tampon glissant est tenu ICI et pas là-bas.
                    eeg, ts_unix = self.acq.get_new_data()
                    self.new_block = None
                    if eeg is not None and len(eeg):
                        self.new_block = (eeg, self.clock.to_lsl(ts_unix))
                        self.recent = np.vstack([self.recent, eeg])[-self.keep:]

                    if now - last_quality >= QUALITY_PERIOD_S:
                        self._publish_quality(self.clock.to_lsl(time.time()))
                        last_quality = now

                    for mode_id, runtime in list(self.active.items()):
                        if now - self._last_tick.get(mode_id, 0.0) >= runtime.period_s():
                            runtime.tick(self, self.clock.to_lsl(time.time()), now)
                            self._last_tick[mode_id] = now

                    # Publié quand l'état change, plus un rappel périodique pour les clients qui
                    # se connectent après le démarrage (LSL ne rejoue pas le passé).
                    due = now - last_status >= STATUS_PERIOD_S
                    if self.status_out.push(self._state(True), key=self._status_key(True),
                                            force=due) and due:
                        last_status = now

                    time.sleep(POLL_S)

                self.status_out.push(self._state(False), key=self._status_key(False), force=True)
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
                self.active = {}

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

    freqs = [15.0, 20.0, 8.57]
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
                   help="fréquences des cibles affichées par l'appli cliente, ex. 15,20,8.57 "
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
    engine = EngineServer(serial=args.serial, synthetic=args.synthetic, verbose=args.verbose,
                          modes=modes, params=params, instance=args.instance)
    # Ctrl+C doit fermer PROPREMENT la session BrainFlow : une session laissée ouverte
    # empêche la suivante de s'ouvrir (BOARD_NOT_READY au relancement).
    signal.signal(signal.SIGINT, lambda *_: engine.stop())
    print("[server] Ctrl+C pour arrêter.")
    engine.run(duration_s=args.duration, baseline_s=args.baseline, warmup_s=args.warmup)
