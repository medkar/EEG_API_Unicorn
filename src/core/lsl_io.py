"""Publication des flux LSL — le contrat d'API de l'outil (docs/SPEC.md §4).

Un client (Unity, Python, MATLAB…) ne connaît de nous que ces flux : leur nom, leurs voies,
leurs unités. Tout ce qui est publié ici est donc du **contrat public** — le renommer casse le
code des étudiants. C'est aussi pour ça que chaque flux porte ses métadonnées (noms de voies,
unité, seuils) : un client peut se décrire l'API tout seul, sans documentation externe.

Trois flux au MVP :
    <PREFIX>_raw       8 voies µV @ 250 Hz     — le signal brut
    <PREFIX>_quality   8 σ par voie, ~1 Hz     — la santé des électrodes
    <PREFIX>_status    JSON, événementiel      — l'état du moteur

Autotest (sans casque, sans LSL entrant) :
    python src/core/lsl_io.py
"""

import json
import os
import socket
import sys
import time

import numpy as np
from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, local_clock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (CH_NAMES, FS_UNICORN, SIGNAL_DEAD_SIGMA,  # noqa: E402
                    SIGNAL_SAT_SIGMA, UNICORN_SERIAL)

# Préfixe de TOUS les flux. Figé avant diffusion aux étudiants (SPEC §12.3) : le changer
# après coup casserait leur code, puisque c'est par ce nom qu'ils trouvent le flux.
STREAM_PREFIX = "EEG_API_Unicorn"


def stream_name(suffix):
    """Nom public d'un flux, ex. `stream_name("raw")` -> "EEG_API_Unicorn_raw"."""
    return f"{STREAM_PREFIX}_{suffix}"


def default_instance_id(serial=None, synthetic=False):
    """Identité de CETTE instance du moteur — ce qui distingue deux casques sur un réseau.

    ⚠️ Sans identité distincte, deux moteurs qui tournent en même temps (une salle de TP
    entière) publient des flux de MÊME nom ET de même `source_id`. Or LSL se sert du
    `source_id` pour rattacher un flux après une coupure : deux sources identiques et il
    entremêle les deux casques dans un seul flux, en silence. Constaté le 2026-07-27 :
    1509 échantillons reçus pour 1491 publiés, cadence apparente 401 Hz au lieu de 250.

    On prend le numéro de série du casque (identité stable, propre à l'étudiant) plutôt
    qu'un identifiant de processus : `source_id` doit rester le MÊME d'un lancement à
    l'autre, sinon les clients perdent la capacité de se reconnecter après un redémarrage.
    """
    if synthetic:
        return f"synthetic-{socket.gethostname()}"
    return serial or UNICORN_SERIAL or socket.gethostname()


def _source_id(suffix, instance):
    """Identifiant LSL d'un flux : le nom du flux, plus l'instance qui le produit."""
    return f"{STREAM_PREFIX}_{suffix}@{instance}" if instance else f"{STREAM_PREFIX}_{suffix}"


# --- Ponts d'horloge ---------------------------------------------------------
# BrainFlow horodate chaque échantillon en temps UNIX (le domaine de `time.time()`).
# LSL, lui, travaille dans le domaine de `local_clock()` — une horloge monotone dont
# l'origine est arbitraire (typiquement le démarrage de la machine). Pousser un timestamp
# BrainFlow tel quel dans LSL produirait donc des dates absurdes, décalées de plusieurs
# années, et l'alignement EEG/marqueurs — l'atout principal de LSL — serait perdu.
#
# On mesure donc UNE FOIS l'écart entre les deux horloges, et on l'applique partout.
# Pourquoi une seule fois et pas en continu : les deux horloges peuvent dériver
# différemment (`time.time()` est recalé par NTP, pas `local_clock()`), mais re-mesurer
# introduirait des SAUTS dans la suite des timestamps publiés. Or, pour épocher un ERP,
# la cohérence relative des dates compte bien plus que leur justesse absolue. Un décalage
# constant est inoffensif ; un saut de 10 ms au milieu d'une époque ne l'est pas.
def _measure_clock_offset(n=11):
    """Écart `local_clock() - time.time()`, médiane de n lectures.

    La médiane plutôt qu'une lecture unique : entre les deux appels d'une paire, le système
    peut préempter le thread et gonfler l'écart de quelques ms. La médiane écarte ces
    lectures parasites pour quelques microsecondes de coût total.
    """
    deltas = []
    for _ in range(n):
        t_unix = time.time()
        t_lsl = local_clock()
        deltas.append(t_lsl - t_unix)
    return float(np.median(deltas))


class ClockBridge:
    """Convertit les horodatages BrainFlow (Unix) vers l'horloge LSL."""

    def __init__(self):
        self.offset = _measure_clock_offset()

    def to_lsl(self, unix_ts):
        """Accepte un scalaire ou un tableau d'horodatages Unix."""
        return np.asarray(unix_ts, dtype=np.float64) + self.offset


# --- Flux sortants -----------------------------------------------------------

def _describe_eeg_channels(info, labels, unit):
    """Écrit les noms/unités de voies dans les métadonnées du flux.

    C'est ce qui rend l'API auto-documentée : côté client, `inlet.info().desc()` permet de
    retrouver que la voie 3 s'appelle "C4" sans que personne n'ait eu à le dire.
    """
    chans = info.desc().append_child("channels")
    for label in labels:
        ch = chans.append_child("channel")
        ch.append_child_value("label", label)
        ch.append_child_value("unit", unit)
        ch.append_child_value("type", "EEG")


class RawPublisher:
    """`<PREFIX>_raw` : les 8 voies EEG brutes, en µV, à 250 Hz.

    « Brut » = tel que le casque le rend, SANS filtrage : c'est un choix, pas un oubli.
    Chaque mode a besoin d'une bande différente (le passe-bande SSVEP 5-40 Hz couperait le
    P300 et le bas du thêta) — filtrer ici imposerait à tous les clients le compromis d'un
    seul mode. Le décodage filtré est publié séparément par les flux `decoded_*`.
    """

    def __init__(self, ch_names=CH_NAMES, fs=FS_UNICORN, instance=""):
        self.ch_names = list(ch_names)
        info = StreamInfo(stream_name("raw"), "EEG", len(self.ch_names), float(fs),
                          "float32", _source_id("raw", instance))
        _describe_eeg_channels(info, self.ch_names, "microvolts")
        info.desc().append_child_value("manufacturer", "g.tec Unicorn Hybrid Black")
        # chunk_size=25 : on regroupe les échantillons par paquets de 100 ms au lieu d'un
        # datagramme par échantillon. Divise par 25 le nombre d'envois réseau pour un délai
        # ajouté négligeable devant la fenêtre de décision d'un mode BCI (1-2 s).
        self.outlet = StreamOutlet(info, chunk_size=25)

    def push(self, eeg, lsl_ts):
        """Publie un bloc d'échantillons. `eeg` = (n, 8) en µV, `lsl_ts` = (n,) horloge LSL."""
        if eeg is None or len(eeg) == 0:
            return 0
        # from_buffer (dans pylsl) exige un tableau float32 contigu et inscriptible.
        block = np.ascontiguousarray(eeg, dtype=np.float32)
        self.outlet.push_chunk(block, list(np.asarray(lsl_ts, dtype=np.float64)))
        return len(block)

    def has_consumers(self):
        return self.outlet.have_consumers()


class QualityPublisher:
    """`<PREFIX>_quality` : σ par voie, ~1 Hz — la santé des électrodes.

    Pourquoi ce flux existe : une électrode décollée ne produit AUCUN message d'erreur, juste
    des données inexploitables. Le 2026-07-20, 3,4 minutes ont été enregistrées dans le vide
    sans le moindre avertissement. Un client qui affiche ce flux voit le problème AVANT
    d'enregistrer.

    On publie le σ NUMÉRIQUE plutôt qu'un verdict textuel : c'est traçable sur une courbe, et
    les seuils voyagent dans les métadonnées du flux pour que le client reconstitue le verdict
    lui-même (cf. `verdict_from_sigma`).
    """

    def __init__(self, ch_names=CH_NAMES, instance=""):
        self.ch_names = list(ch_names)
        info = StreamInfo(stream_name("quality"), "Quality", len(self.ch_names),
                          IRREGULAR_RATE, "float32", _source_id("quality", instance))
        _describe_eeg_channels(info, self.ch_names, "microvolts_stddev")
        thr = info.desc().append_child("thresholds")
        thr.append_child_value("dead_below", str(SIGNAL_DEAD_SIGMA))
        thr.append_child_value("saturated_above", str(SIGNAL_SAT_SIGMA))
        self.outlet = StreamOutlet(info)

    def push(self, sigmas, lsl_ts=None):
        if sigmas is None:
            return False
        block = np.ascontiguousarray(np.asarray(sigmas).reshape(1, -1), dtype=np.float32)
        self.outlet.push_chunk(block, [float(lsl_ts) if lsl_ts else local_clock()])
        return True


def ssvep_channel_labels(freqs):
    """Voies du flux `decoded_ssvep` pour ce jeu de fréquences.

    Une seule fonction pour le publieur ET pour le `ModeSpec` : les voies sont du contrat public
    (un client les lit dans les métadonnées), et deux façons de les construire finiraient par
    diverger d'un espace ou d'une décimale.
    """
    return (["target_index", "freq_hz", "confidence"]
            + [f"score_{float(f):g}Hz" for f in freqs])


class DecodedSSVEPPublisher:
    """`<PREFIX>_decoded_ssvep` : quelle cible l'utilisateur regarde, ~5 Hz.

    Le contrat (SPEC §5) : on publie une **intention neutre** — quelle cible, à quelle
    fréquence, avec quelle confiance — et JAMAIS une commande d'actionneur. C'est ce qui
    rend le même flux utilisable par un jeu, une visualisation ou un robot : la traduction
    en action appartient au client.

    Voies : `target_index` (-1 = aucune cible fixée de façon fiable), `freq_hz` (0 si
    aucune), `confidence` (le score du gagnant sur l'échelle de décision), puis un score
    par cible. Le nombre de voies dépend donc du nombre de fréquences déclarées — elles
    sont nommées dans les métadonnées, un client ne doit pas les compter en dur.
    """

    def __init__(self, freqs, decision_scale="rho", thresholds=(0.0, 0.0), instance=""):
        self.freqs = [float(f) for f in freqs]
        labels = ssvep_channel_labels(self.freqs)
        info = StreamInfo(stream_name("decoded_ssvep"), "Decoded", len(labels),
                          IRREGULAR_RATE, "float32", _source_id("decoded_ssvep", instance))
        chans = info.desc().append_child("channels")
        for label in labels:
            ch = chans.append_child("channel")
            ch.append_child_value("label", label)
        desc = info.desc().append_child("decoding")
        desc.append_child_value("paradigm", "SSVEP")
        desc.append_child_value("frequencies_hz", ",".join(f"{f:g}" for f in self.freqs))
        # `decision_scale` dit au client sur quelle échelle lire `confidence` : "rho" =
        # corrélation CCA brute (0-1), "z" = écarts-types au-dessus du bruit de repos une
        # fois le plancher mesuré. Sans cette indication, un seuil côté client n'a pas de sens.
        desc.append_child_value("decision_scale", decision_scale)
        desc.append_child_value("threshold", str(thresholds[0]))
        desc.append_child_value("margin", str(thresholds[1]))
        self.outlet = StreamOutlet(info)

    def push(self, target_index, freq_hz, confidence, scores, lsl_ts=None):
        """`scores` : liste des scores dans le MÊME ordre que `freqs`."""
        row = [float(target_index), float(freq_hz), float(confidence)] + [float(s) for s in scores]
        block = np.ascontiguousarray(np.asarray(row).reshape(1, -1), dtype=np.float32)
        self.outlet.push_chunk(block, [float(lsl_ts) if lsl_ts else local_clock()])


class DecodedNeuroPublisher:
    """`<PREFIX>_decoded_neuro` : trois indices d'état mental, ~5 Hz. BCI **passif**.

    Passif = l'utilisateur ne commande rien, on observe un état. C'est la différence de nature
    avec `decoded_ssvep` : il n'y a pas de « cible », donc pas de bonne ou de mauvaise réponse,
    et un client ne doit PAS traiter ces valeurs comme une sélection.

    Voies : `charge`, `somnolence`, `engagement` (z lissés), puis `artifact` (1 = fenêtre
    rejetée : clignement, mouvement ou EMG). Sur une fenêtre rejetée on republie les DERNIERS
    z valides avec `artifact=1` plutôt que des indices calculés sur un clignement — ceux-ci
    seraient parfaitement plausibles, donc indétectables en aval.

    ⚠️ **L'échelle est un z contre le repos du jour de CET utilisateur**, mesuré au début du
    mode. Les valeurs ne sont comparables ni entre deux personnes, ni entre deux séances, ni
    dans l'absolu : `+1` veut dire « au-dessus de mon propre repos », pas « chargé ». Les trois
    indices dérivent en outre du même calcul spectral et restent corrélés entre eux. À lire en
    TENDANCE. Un client qui afficherait ça comme une mesure de fatigue mentirait à son
    utilisateur.
    """

    KEYS = ("charge", "somnolence", "engagement")

    def __init__(self, instance="", smoothing=0.0, rebaseline_s=0.0):
        labels = list(self.KEYS) + ["artifact"]
        info = StreamInfo(stream_name("decoded_neuro"), "Decoded", len(labels),
                          IRREGULAR_RATE, "float32", _source_id("decoded_neuro", instance))
        chans = info.desc().append_child("channels")
        for label in labels:
            ch = chans.append_child("channel")
            ch.append_child_value("label", label)
        desc = info.desc().append_child("decoding")
        desc.append_child_value("paradigm", "neuro-passive")
        desc.append_child_value("decision_scale", "z")
        desc.append_child_value("reference", "repos mesure en debut de mode, par utilisateur")
        desc.append_child_value("smoothing_ema", str(smoothing))
        desc.append_child_value("rebaseline_s", str(rebaseline_s))
        self.outlet = StreamOutlet(info)

    def push(self, z, artifact=False, lsl_ts=None):
        """`z` : dict {charge, somnolence, engagement}. Ordre de voies garanti par KEYS."""
        row = [float(z.get(k, 0.0)) for k in self.KEYS] + [1.0 if artifact else 0.0]
        block = np.ascontiguousarray(np.asarray(row).reshape(1, -1), dtype=np.float32)
        self.outlet.push_chunk(block, [float(lsl_ts) if lsl_ts else local_clock()])


def mi_channel_labels(classes):
    """Voies du flux `decoded_mi` pour ces classes.

    Une seule fonction pour le publieur ET pour le `ModeSpec`, comme pour le SSVEP : les voies
    sont du contrat public, et deux façons de les construire finiraient par diverger.
    """
    return ["intent_index", "confidence"] + [f"p_{c}" for c in classes]


class DecodedMIPublisher:
    """`<PREFIX>_decoded_mi` : quelle imagerie motrice l'utilisateur produit, ~5 Hz. BCI **active**.

    Le contrat (SPEC §5) : une **intention neutre** — quelle classe, avec quelle probabilité —
    et JAMAIS une commande d'actionneur. « GAUCHE » veut dire « imagerie de la main gauche »,
    pas « tourne à gauche » : c'est le client qui décide ce que ça déclenche.

    Voies : `intent_index`, `confidence`, puis une probabilité par classe.

    ⚠️ **Les trois ne décrivent pas le même instant.** `intent_index` et `confidence` décrivent
    le **vote** — jusqu'à `vote_len` fenêtres, dont `min_votes` d'accord ; `confidence` est la
    moyenne des probabilités de ces fenêtres-là, donc toujours `>= threshold` quand
    `intent_index >= 0`. Les `p_*`, eux, décrivent la **dernière fenêtre seule**. Pendant un
    changement d'intention, il est donc NORMAL de lire « intention GAUCHE » à côté d'un
    `p_DROITE` élevé : le vote n'a pas encore basculé. Pour filtrer, sers-toi de `confidence`,
    jamais du `p_*` de la classe retenue.

    ⚠️ **`-1` et la classe REPOS sont deux choses différentes.** `-1` = le vote n'a pas conclu
    (pas assez de fenêtres d'accord, ou probabilité sous le seuil) ; l'indice de REPOS = le
    modèle a décidé que la personne se repose. « Je ne sais pas » et « elle ne fait rien »
    n'appellent pas la même réaction dans une application. Les deux indices voyagent dans les
    métadonnées (`no_decision_index`, `rest_index`) : un client n'a pas à les deviner, ni à
    supposer que REPOS est toujours la dernière classe.

    ⚠️ Ce mode exige un modèle ENTRAÎNÉ, propre à une personne. Les probabilités d'un modèle
    entraîné sur quelqu'un d'autre sont plausibles et fausses.
    """

    def __init__(self, classes, prob_min=0.0, votes=(0, 0), instance="", rest_label="REPOS"):
        self.classes = [str(c) for c in classes]
        labels = mi_channel_labels(self.classes)
        info = StreamInfo(stream_name("decoded_mi"), "Decoded", len(labels),
                          IRREGULAR_RATE, "float32", _source_id("decoded_mi", instance))
        chans = info.desc().append_child("channels")
        for label in labels:
            ch = chans.append_child("channel")
            ch.append_child_value("label", label)
        desc = info.desc().append_child("decoding")
        desc.append_child_value("paradigm", "motor-imagery")
        desc.append_child_value("classes", ",".join(self.classes))
        # L'échelle est une PROBABILITÉ de classifieur, pas un z comme le SSVEP : sans cette
        # indication, un seuil posé côté client n'a pas le même sens d'un mode à l'autre.
        desc.append_child_value("decision_scale", "proba")
        desc.append_child_value("threshold", str(prob_min))
        desc.append_child_value("min_votes", str(votes[0]))
        desc.append_child_value("vote_len", str(votes[1]))
        # La distinction la plus coûteuse à confondre du mode est celle que les métadonnées
        # taisaient : « je ne sais pas » (-1) contre « la personne se repose » (l'indice de
        # REPOS). Ce module promet en tête qu'un client peut se décrire l'API tout seul — alors
        # les deux indices y sont, plutôt que dans une documentation qu'il n'ouvrira pas.
        # `rest_index` vaut -1 quand le modèle n'a pas de classe de repos : un modèle à deux
        # classes est possible, et supposer que REPOS existe toujours serait faux.
        desc.append_child_value("no_decision_index", "-1")
        rest_index = self.classes.index(rest_label) if rest_label in self.classes else -1
        desc.append_child_value("rest_index", str(rest_index))
        self.outlet = StreamOutlet(info)

    def push(self, intent_index, confidence, probas, lsl_ts=None):
        """`probas` : les probabilités dans le MÊME ordre que `classes`."""
        row = [float(intent_index), float(confidence)] + [float(p) for p in probas]
        block = np.ascontiguousarray(np.asarray(row).reshape(1, -1), dtype=np.float32)
        self.outlet.push_chunk(block, [float(lsl_ts) if lsl_ts else local_clock()])


def p300_channel_labels(n_targets):
    """Voies du flux `decoded_p300`. Une seule fonction pour le publieur ET le `ModeSpec`."""
    return (["target_index", "confidence", "n_flashes"]
            + [f"score_{i}" for i in range(int(n_targets))])


class DecodedP300Publisher:
    """`<PREFIX>_decoded_p300` : quelle cible l'utilisateur a sélectionnée. Une fois par manche.

    ⚠️ `target_index = -1` signifie **« pas de décision »** — jamais « la cible 0 », jamais
    « repos ». C'est mot pour mot la confusion qu'il a fallu inscrire en garde pour le MI, et
    elle se reproduira chez le premier client qui lira ce flux sans lire la doc — c'est pour ça
    que `no_decision_index` voyage aussi dans les métadonnées, pas seulement ici : un client
    Unity ou MATLAB qui lit `inlet.info().desc()` sans jamais ouvrir ce fichier doit pouvoir le
    découvrir tout seul, exactement comme `DecodedMIPublisher` le fait juste au-dessus.

    Ce flux est IRRÉGULIER et rare : un échantillon par `round_end`, pas ~5 Hz comme le SSVEP.
    Un client qui attend un débit régulier attendrait pour rien.
    """

    def __init__(self, n_targets, reps, instance=""):
        self.n_targets = int(n_targets)
        labels = p300_channel_labels(self.n_targets)
        info = StreamInfo(stream_name("decoded_p300"), "Decoded", len(labels),
                          IRREGULAR_RATE, "float32", _source_id("decoded_p300", instance))
        chans = info.desc().append_child("channels")
        for label in labels:
            ch = chans.append_child("channel")
            ch.append_child_value("label", label)
        desc = info.desc().append_child("decoding")
        desc.append_child_value("paradigm", "P300")
        desc.append_child_value("n_targets", str(self.n_targets))
        desc.append_child_value("reps", str(int(reps)))
        # « logodds » : les scores sont les log-odds moyens de la régression logistique, additifs
        # sur les répétitions. Ils ne sont ni bornés ni comparables d'une personne à l'autre —
        # sans cette indication, un seuil côté client n'aurait aucun sens.
        desc.append_child_value("decision_scale", "logodds")
        desc.append_child_value("no_decision_index", "-1")
        self.outlet = StreamOutlet(info)

    def push(self, target_index, confidence, n_flashes, scores, lsl_ts=None):
        """`scores` : un score par cible, dans l'ordre des indices 0..n_targets-1."""
        row = ([float(target_index), float(confidence), float(n_flashes)]
               + [float(s) for s in scores])
        block = np.ascontiguousarray(np.asarray(row).reshape(1, -1), dtype=np.float32)
        self.outlet.push_chunk(block, [float(lsl_ts) if lsl_ts else local_clock()])


class StatusPublisher:
    """`<PREFIX>_status` : état du moteur, en JSON, événementiel.

    Indispensable parce que LSL est *fire-and-forget* : un client qui envoie une commande ne
    reçoit aucun accusé de réception (SPEC §4). Il constate l'effet de sa commande ICI. Le
    moteur republie donc son état à chaque changement, et périodiquement pour qu'un client
    qui se connecte en cours de route sache où on en est.
    """

    def __init__(self, instance=""):
        info = StreamInfo(stream_name("status"), "Markers", 1, IRREGULAR_RATE,
                          "string", _source_id("status", instance))
        self.outlet = StreamOutlet(info)
        self._last_key = None

    def push(self, state, key=None, force=False):
        """Publie `state` (dict). Sans `force`, ne réémet que si `key` a changé.

        `key` (n'importe quoi de hachable) désigne ce qui compte comme « changement d'état ».
        Il est SÉPARÉ du contenu publié pour une raison concrète : l'état contient des
        compteurs qui bougent en permanence (échantillons publiés). Dédupliquer sur le
        message complet reviendrait à ne jamais dédupliquer — mesuré : 19,6 Hz de messages
        d'état au lieu de 0,5 Hz. Sans `key`, on retombe sur la comparaison du message entier.
        """
        payload = json.dumps(state, separators=(",", ":"), sort_keys=True)
        marker = payload if key is None else key
        if marker == self._last_key and not force:
            return False
        self._last_key = marker
        self.outlet.push_sample([payload])
        return True


def verdict_from_sigma(sigma):
    """'morte' | 'saturée' | 'ok' — le même verdict que côté serveur, reproductible client."""
    if sigma < SIGNAL_DEAD_SIGMA:
        return "morte"
    if sigma > SIGNAL_SAT_SIGMA:
        return "saturée"
    return "ok"


# --- Autotest ----------------------------------------------------------------

def _autotest():
    """Publie les 3 flux, les relit avec un client local, vérifie le contrat.

    Ne teste PAS le casque : uniquement que ce qu'on publie est bien ce qu'un étudiant
    recevra (noms de voies, unités, horodatage cohérent, valeurs intactes).
    """
    from pylsl import StreamInlet, resolve_byprop

    bridge = ClockBridge()
    instance = "autotest"
    raw = RawPublisher(instance=instance)
    qual, status = QualityPublisher(instance=instance), StatusPublisher(instance=instance)
    ok = True

    # 1. Découverte + métadonnées du flux brut.
    # On exige NOTRE instance : les noms de flux sont un contrat public, donc identiques pour
    # tous les moteurs. Sans ce filtre, un serveur laissé ouvert sur le poste répond à la
    # place du nôtre et l'autotest compare ses données à notre motif — il a échoué ainsi le
    # 2026-07-27 sur « valeurs altérées ». `minimum` élevé force à attendre tout le monde.
    found = [i for i in resolve_byprop("name", stream_name("raw"), minimum=32, timeout=2.0)
             if i.source_id().endswith(f"@{instance}")]
    if not found:
        print("[lsl] ÉCHEC : flux 'raw' introuvable")
        return False
    inlet = StreamInlet(found[0])
    desc = inlet.info().desc()
    labels, node = [], desc.child("channels").child("channel")
    for _ in range(inlet.info().channel_count()):
        labels.append(node.child_value("label"))
        node = node.next_sibling()
    print(f"[lsl] raw : {inlet.info().channel_count()} voies @ {inlet.info().nominal_srate()} Hz")
    print(f"[lsl] voies annoncées : {labels}")
    if labels != CH_NAMES:
        print(f"[lsl] ÉCHEC : voies annoncées != CH_NAMES ({CH_NAMES})")
        ok = False

    # 2. Aller-retour de données : on pousse un motif reconnaissable et on le relit.
    # ⚠️ `open_stream()` est OBLIGATOIRE avant de publier : un StreamInlet n'ouvre sa
    # connexion qu'au premier `pull_*`, et LSL ne rejoue RIEN de ce qui a été publié avant.
    # Sans cette ligne on perd la première seconde de signal — piège classique, à répéter
    # dans les exemples destinés aux étudiants.
    inlet.open_stream(timeout=5.0)
    time.sleep(0.2)
    n = 50
    unix_now = time.time()
    ts = unix_now + np.arange(n) / FS_UNICORN
    sent = np.tile(np.arange(n, dtype=np.float32).reshape(-1, 1), (1, len(CH_NAMES)))
    sent[:, 1] = 42.0  # une voie constante : détecte un mélange de voies (transposition)
    raw.push(sent, bridge.to_lsl(ts))
    time.sleep(0.5)
    chunk, stamps = inlet.pull_chunk(timeout=2.0, max_samples=n)
    print(f"[lsl] aller-retour : {len(chunk)}/{n} échantillons")
    if len(chunk) != n:
        print("[lsl] ÉCHEC : échantillons perdus ou incomplets")
        ok = False
    elif not np.allclose(np.asarray(chunk), sent):
        print("[lsl] ÉCHEC : valeurs altérées entre l'envoi et la réception")
        ok = False

    # 3. Horodatage : les dates reçues doivent coller à l'horloge LSL locale, pas au temps Unix.
    if stamps:
        drift_ms = (local_clock() - stamps[-1]) * 1000.0
        print(f"[lsl] dernier horodatage reçu : {drift_ms:+.1f} ms avant maintenant (horloge LSL)")
        if abs(drift_ms) > 2000.0:
            print("[lsl] ÉCHEC : horodatage hors du domaine local_clock() (pont d'horloge cassé ?)")
            ok = False

    # 4. Les deux autres flux publient sans erreur.
    qual.push(np.array([8.0, 0.1, 12.0, 9.0, 7.0, 11.0, 600.0, 10.0]))
    status.push({"running": True, "mode": None, "calibrated": {}})
    print(f"[lsl] verdicts : {[verdict_from_sigma(s) for s in (8.0, 0.1, 600.0)]}")

    # 5. decoded_mi : voies attendues, et le publieur pousse sans lever (indice ET repos).
    labels = mi_channel_labels(("GAUCHE", "DROITE", "REPOS"))
    print(f"  voies decoded_mi : {labels}")
    assert labels == ["intent_index", "confidence", "p_GAUCHE", "p_DROITE", "p_REPOS"], labels
    pub = DecodedMIPublisher(("GAUCHE", "DROITE", "REPOS"), prob_min=0.6, votes=(3, 5),
                             instance="selftest-mi")
    pub.push(0, 0.81, [0.81, 0.12, 0.07])
    pub.push(-1, 0.0, [0.34, 0.33, 0.33])
    print("  [lsl] decoded_mi publie sans lever")

    # 6. decoded_p300 : voies attendues (target_index/confidence/n_flashes puis un score par
    # cible), et le publieur pousse sans lever (une décision ET un refus, -1).
    labels = p300_channel_labels(6)
    print(f"  voies decoded_p300 : {labels}")
    assert labels == ["target_index", "confidence", "n_flashes",
                      "score_0", "score_1", "score_2", "score_3", "score_4", "score_5"], labels
    pub = DecodedP300Publisher(6, reps=8, instance="selftest-p300")
    pub.push(2, 4.1, 48, [-1.0, 0.5, 4.1, -0.2, 1.0, -3.0])
    pub.push(-1, 0.0, 12, [0.0] * 6)
    print("  [lsl] decoded_p300 publie sans lever")
    # Le sens de -1 doit être lisible dans les MÉTADONNÉES, pas seulement dans une docstring
    # qu'un client Unity/MATLAB n'ouvrira jamais — même exigence que `DecodedMIPublisher`
    # (no_decision_index) juste au-dessus.
    no_decision = pub.outlet.get_info().desc().child("decoding").child_value("no_decision_index")
    print(f"  decoded_p300 no_decision_index (métadonnées) : {no_decision!r}")
    assert no_decision == "-1", f"no_decision_index attendu '-1', reçu {no_decision!r}"

    print(f"[lsl] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    from core.config import use_utf8_console
    use_utf8_console()
    sys.exit(0 if _autotest() else 1)
