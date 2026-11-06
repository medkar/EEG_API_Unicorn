"""Le PILOTAGE par le réseau : une application règle, démarre et arrête un mode.

L'application crée un flux LSL `EEG_API_Unicorn_control` (type Markers, une chaîne JSON par
échantillon) et y envoie ses commandes. Ce module, dans son PROPRE fil, écoute les flux de ce
nom — ceux de CETTE machine pour le moteur seul, celui qu'on a connecté, de n'importe quelle
machine, pour la console —, transforme chaque commande en un appel de `EngineServer.submit` —
le seul juge : rien n'est validé ici — et publie la réponse sur `EEG_API_Unicorn_replies`.

    application ──control──▶ Pilotage ──submit()──▶ moteur
    application ◀──replies── Pilotage ◀──accusé───┘

LSL ne permet pas de recevoir sur un flux qu'on publie : c'est donc l'application qui crée
l'outlet de commandes, et le moteur qui l'écoute.

Deux façons d'écouter (`ECOUTES`). « permanente », celle du moteur seul (`server.py`) : tous les
flux de ce nom de cette machine, dès qu'ils existent. « sur_demande », celle de la console :
aucun, tant qu'on n'a pas cherché les applications (`chercher`, celles de TOUTES les machines du
réseau) et choisi l'une d'elles (`connecter`) ; seule celle-là est alors écoutée, et son départ
est signalé au moteur.

Quatre commandes, et seulement elles (`COMMANDES_RESEAU`) : `start_mode`, `stop_mode`,
`set_params`, `propose_params`. Les entraînements et les mesures restent dans la console.

Une réponse par commande reçue, illisible comprise. Tout ce qui part vers l'application est en
ANGLAIS, nombres avec un point, quelle que soit la langue de l'écran (`i18n.pour_le_contrat`).
Le champ `ref` de la commande, recopié tel quel, permet à chaque application de reconnaître SA
réponse : le flux de réponses est commun à toutes les applications de la machine.

Quand le moteur cesse de lire une application — « Déconnecter » dans la console, ou l'arrêt du
moteur —, il le lui DIT sur ce même flux, avant de refermer le sien : un message au `ref` null,
`{"ref", "event": "disconnected", "cause", "app", "stopped", "reason"}` (`deconnexion`), où
`app` est le `source_id` complet de son flux de commandes. LSL, lui, ne le dirait à
l'application qu'à son prochain envoi.

Une application envoie au plus `DEBIT_MAX` commandes par seconde : au-delà, chaque commande en
trop reçoit un refus. Sans cette borne, une application qui renvoie sa commande en boucle, sans
pause, remplirait la file du moteur.

⚠️ **Deux pièges LSL, qui perdent un message sans rien lever :**
1. Une commande envoyée AVANT que le moteur ait découvert l'outlet de l'application est perdue :
   LSL ne rejoue rien. L'application attend donc le moteur (`outlet.wait_for_consumers(...)`)
   avant d'envoyer. Ce module ouvre son inlet tout de suite (`open_stream`) pour que cette attente
   réussisse dès qu'il écoute vraiment.
2. Une réponse publiée AVANT que l'application écoute est perdue aussi. L'application ouvre son
   inlet de réponses (`open_stream()`) avant d'envoyer sa première commande.

🔴 En écoute permanente (le moteur seul), seule une application de la MÊME machine pilote ce
moteur (nom d'hôte comparé sans casse) : en salle, chaque moteur écoute le même nom de flux, et
l'application d'un voisin ne doit pas piloter le tien. Sur demande (la console), c'est le clic
« Connecter » qui protège : la liste montre la machine de chaque application.

Sur demande, un second transport s'ajoute : UDP (`core/pilotage_udp.py`, `ouvrir_udp`), pour un
appareil qui ne parle pas LSL (un ESP32). Ses commandes passent par le MÊME `traiter`, et tout
ce qui part vers l'application connectée passe par UN point de sortie (`_envoyer`) : le flux de
réponses pour une application LSL, sa socket pour un appareil réseau. Le moteur pousse en plus à
l'appareil la phase de ses modes et chacune de leurs décisions (`pousser`).

Autotest (aucun casque ; ouvre des flux LSL locaux) :
    python src/core/pilotage.py
"""

import collections
import json
import math
import os
import queue
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass, field

from pylsl import (IRREGULAR_RATE, ContinuousResolver, StreamInfo, StreamInlet, StreamOutlet,
                   resolve_byprop)

# `LostError` vit dans `pylsl.util` en 1.18 (cf. `core/markers.py`). Le repli est un surensemble :
# on lâche un inlet un peu trop souvent, jamais trop peu.
try:
    from pylsl.util import LostError
except ImportError:                      # pragma: no cover - dépend de la version de pylsl
    LostError = RuntimeError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import use_utf8_console  # noqa: E402
from core.i18n import (Texte, choisir_langue, message_erreur, nombre,  # noqa: E402
                       pour_le_contrat, tr)
from core.lsl_io import (NOM_FLUX_COMMANDES, NOM_FLUX_REPONSES, _source_id,  # noqa: E402
                         stream_name)

COMMANDES_RESEAU = ("start_mode", "stop_mode", "set_params", "propose_params")

# Le suffixe du flux de réponses (« replies »), tiré de son nom public : il entre dans le
# `source_id` du flux, et un renommage dans `lsl_io` ne doit rien laisser derrière lui.
SUFFIXE_REPONSES = NOM_FLUX_REPONSES[len(stream_name("")):]

# Le rythme du fil d'écoute. Une commande attend au plus une pause avant d'être lue.
PAUSE_S = 0.02
# Le résolveur cherche en tâche de fond ; on relit sa liste à ce rythme.
DECOUVERTE_S = 0.1
# Borne de l'ouverture d'un inlet. MESURÉ : 0,01 s sur un flux vivant de cette machine ; sur un
# flux mort, l'appel attend la borne entière, et aucune application n'est servie pendant ce
# temps. Elle borne aussi l'arrêt du fil.
OUVERTURE_S = 0.25
# Une ouverture ratée sur un flux encore annoncé est retentée après ce délai. C'est aussi la
# pause du fil d'écoute après un défaut imprévu, avant de reprendre.
REESSAI_S = 2.0
# Le résolveur oublie un flux qu'il ne voit plus après ce délai. MESURÉ : un outlet détruit reste
# annoncé ~5 s.
OUBLI_S = 5.0
# Un flux PERDU n'est pas rouvert pendant ce délai : plus long que `OUBLI_S`, pour qu'un outlet
# mort ait disparu de la liste avant (l'ouvrir attendrait `OUVERTURE_S` pour rien) ; un outlet
# encore vivant dont la connexion a cassé est, lui, rebranché ensuite.
BANNI_PERDU_S = OUBLI_S + 3.0
# `arreter()` attend le fil au plus ce temps.
ARRET_S = 2.0
# Par flux et par tour, au plus autant de commandes ET au plus ce temps : une application bavarde,
# ou un moteur lent à juger (~0,3 s pour résoudre un `stream_in`), ne fait pas attendre les autres.
MAX_PAR_TOUR = 32
TEMPS_PAR_FLUX_S = 0.1
# Au plus autant de commandes par seconde et par application, en rafale de `DEBIT_MAX` au plus
# (un seau de jetons, `Seau`). Une commande en trop reçoit un refus : une réponse quand même.
DEBIT_MAX = 20
# Le tampon de l'inlet de chaque application : au plus ~`COMMANDES_EN_ATTENTE` commandes. MESURÉ :
# plein, il jette les plus ANCIENNES, sans réponse. pylsl le compte « in seconds if there is a
# nominal sampling rate, otherwise x100 in samples » : pour un flux IRRÉGULIER (celui du contrat),
# 1 garde 100 commandes ; pour un flux qui déclare un débit, `_tampon` le convertit en secondes.
# Le défaut de pylsl (360) en garderait 36 000.
COMMANDES_EN_ATTENTE = 100
TAMPON_INLET = 1
# Au plus autant de messages poussés (status, décisions) en attente d'envoi vers l'appareil réseau
# connecté : de quoi couvrir plusieurs secondes de décisions de trois modes. Pleine, la file jette
# les plus ANCIENS : une décision périmée ne sert plus à rien.
POUSSEES_MAX = 256
# Les dernières commandes que la console peut montrer : de quoi couvrir les 10 s où son bandeau
# garde une ligne, pour une application à la cadence maximale (`DEBIT_MAX`). Plus court, un refus
# sortait du journal en une demi-seconde, sous les commandes acceptées qui le suivaient.
JOURNAL_N = 10 * DEBIT_MAX
# Longueur maximale de la valeur de « cmd » recopiée dans un refus, et de « cmd » et « mode »
# inscrits au journal : la console les affiche, et une application peut y mettre n'importe quoi.
CMD_AFFICHEE_MAX = 60

# Les deux façons d'écouter. « permanente » : toutes les applications de cette machine, dès
# qu'elles existent — le moteur seul (`server.py`). « sur_demande » : aucune, sauf celle que la
# personne a choisie dans la console (« Connecter une application »).
ECOUTES = ("permanente", "sur_demande")


@dataclass
class Commande:
    """Une commande lue sur le réseau.

    `kwargs` est prêt pour `engine.submit(cmd, **kwargs)`. `refus` est un `Texte` (dans la langue
    de l'écran) quand la commande ne peut pas être soumise, sinon None. `ref`, `cmd` et `mode`
    sont recopiés dans la réponse quand ils ont un type valable, sinon None.
    """
    ref: object = None
    cmd: object = None
    mode: object = None
    kwargs: dict = field(default_factory=dict)
    refus: object = None


def _ref_valable(ref):
    """Une chaîne, ou un nombre fini. Un booléen n'est pas un nombre (`True` vaut 1 en Python)."""
    if isinstance(ref, bool):
        return False
    if isinstance(ref, (str, int)):
        # Un entier est toujours fini. `math.isfinite` le convertirait en réel, et LÈVERAIT sur
        # un entier trop grand (400 chiffres) : la commande perdrait sa réponse.
        return True
    return isinstance(ref, float) and math.isfinite(ref)


def _commande_pas_utf8(d):
    """Une commande qui n'est pas du texte UTF-8 : toujours refusée, pour cette raison-là.

    Ses « ref », « cmd » et « mode » sont recopiés quand ils ont survécu au décodage — souvent de
    l'ASCII, seul un accent dans un nom était dans un autre encodage : l'application reconnaît
    alors SON refus. Un champ abîmé (il contient U+FFFD, le caractère qui remplace un octet
    illisible) part en null : ce n'est plus ce que l'application a envoyé.
    """
    d = d if isinstance(d, dict) else {}

    def intact(x):
        return isinstance(x, str) and "�" not in x

    ref = d.get("ref")
    if not (_ref_valable(ref) and (intact(ref) or not isinstance(ref, str))):
        ref = None
    cmd = d.get("cmd") if intact(d.get("cmd")) else None
    mode = d.get("mode") if intact(d.get("mode")) else None
    return Commande(ref=ref, cmd=cmd, mode=mode, refus=tr("moteur.reseau.pas_utf8"))


def lire_commande(texte):
    """Le JSON d'une commande en `Commande`. Ne lève jamais : une application mal écrite ne doit
    pas pouvoir tuer le fil d'écoute.

    `texte` est une chaîne, ou les OCTETS bruts d'une commande que pylsl n'a pas pu décoder en
    UTF-8 : celle-là est refusée pour sa propre raison (`_commande_pas_utf8`).

    Seuls les TYPES sont vérifiés ici — de quoi appeler `submit` sans lui passer n'importe quoi.
    Le sens (mode connu, réglage valide, commande possible maintenant) est jugé par `submit`.
    Les champs inconnus sont ignorés.
    """
    pas_utf8 = False
    if isinstance(texte, (bytes, bytearray)):
        try:
            texte = bytes(texte).decode("utf-8")
        except UnicodeDecodeError:
            # Lue quand même, octets fautifs remplacés : de quoi rendre son « ref » à l'application.
            pas_utf8 = True
            texte = bytes(texte).decode("utf-8", "replace")
    try:
        d = json.loads(texte)
    except Exception:  # noqa: BLE001 - « ne lève jamais » : texte absent, mal encodé, pas du JSON
        d = None
    if pas_utf8:
        return _commande_pas_utf8(d)
    if not isinstance(d, dict):
        return Commande(refus=tr("moteur.reseau.json_illisible"))

    ref, cmd, mode = d.get("ref"), d.get("cmd"), d.get("mode")
    params, cle = d.get("params"), d.get("key")
    # Recopiés dans la réponse seulement s'ils ont le bon type : la réponse doit rester du JSON
    # simple, et l'application reconnaître sa commande.
    cmd_lu = cmd if isinstance(cmd, str) else None
    mode_lu = mode if isinstance(mode, str) else None

    def refus(texte_refus, ref_lu=ref):
        return Commande(ref=ref_lu, cmd=cmd_lu, mode=mode_lu, refus=texte_refus)

    if ref is not None and not _ref_valable(ref):
        return refus(tr("moteur.reseau.champ_invalide", champ="ref"), ref_lu=None)
    if cmd is None:
        return refus(tr("moteur.reseau.commande_absente", liste=", ".join(COMMANDES_RESEAU)))
    if not isinstance(cmd, str) or cmd not in COMMANDES_RESEAU:
        vu = json.dumps(cmd, ensure_ascii=False)
        if len(vu) > CMD_AFFICHEE_MAX:
            vu = vu[:CMD_AFFICHEE_MAX] + "…"
        return refus(tr("moteur.reseau.commande_non_permise", commande=vu,
                        liste=", ".join(COMMANDES_RESEAU)))
    if mode is not None and not isinstance(mode, str):
        return refus(tr("moteur.reseau.champ_invalide", champ="mode"))
    if params is not None and not isinstance(params, dict):
        return refus(tr("moteur.reseau.champ_invalide", champ="params"))
    if cle is not None and not isinstance(cle, str):
        return refus(tr("moteur.reseau.champ_invalide", champ="key"))

    kwargs = {} if mode is None else {"id": mode}
    if cmd == "start_mode":
        # `submit("start_mode")` peut démarrer plusieurs modes d'un coup : ses réglages sont donc
        # rangés sous le nom de chaque mode, `{"ssvep": {...}}`.
        if params and mode is not None:
            kwargs["params"] = {mode: params}
    elif cmd in ("set_params", "propose_params"):
        if params is not None:
            kwargs["params"] = params
        if cmd == "propose_params" and cle is not None:
            kwargs["key"] = cle
    return Commande(ref=ref, cmd=cmd, mode=mode, kwargs=kwargs)


def _completer_cle(commande):
    """`propose_params` sans « key » : si le mode n'a qu'UN réglage qui propose, c'est lui.

    Sinon la commande part telle quelle et `submit` refuse avec sa propre raison. Le registre est
    importé ici, pas en tête du module : il charge tout le catalogue des modes.
    """
    if (commande.cmd != "propose_params" or commande.refus is not None
            or "key" in commande.kwargs or not isinstance(commande.mode, str)):
        return
    from core.modes import registry
    spec = registry.get(commande.mode)
    if spec is None:
        return
    proposeurs = [p.key for p in spec.params if p.proposes]
    if len(proposeurs) == 1:
        commande.kwargs["key"] = proposeurs[0]


def _court(x):
    """Une chaîne de l'application, coupée à `CMD_AFFICHEE_MAX` caractères pour l'affichage."""
    if isinstance(x, str) and len(x) > CMD_AFFICHEE_MAX:
        return x[:CMD_AFFICHEE_MAX] + "…"
    return x


def reponse(commande, ack):
    """La réponse réseau à une commande, d'après l'accusé de `submit`. En ANGLAIS.

    `{"ref", "cmd", "mode", "accepted"}`, plus selon le cas : `reason` (refus) ; `params`,
    `deferred` (réglage RETENU sur un mode arrêté) ; `already_running` (`start_mode` sur un mode
    qui tourne) ; `already_stopped` (`stop_mode` sur un mode arrêté) ; `key`, `value`
    (`propose_params`). Toute réponse ACCEPTÉE porte `warning` : une réserve, ou null.

    Le réglage `model` part en NOM DE FICHIER : le moteur le tient en chemin complet, et le flux de
    réponses se lit de tout le réseau. Les réglages du moteur, eux, ne sont jamais touchés :
    `pour_le_contrat` en fait une copie.
    """
    accepte = bool(ack.get("accepted"))
    rep = {"ref": commande.ref, "cmd": commande.cmd, "mode": commande.mode, "accepted": accepte}
    if not accepte:
        rep["reason"] = ack.get("reason")
        return pour_le_contrat(rep)
    if "params" in ack:
        rep["params"] = ack["params"]
    if "differe" in ack:
        rep["deferred"] = bool(ack["differe"])
    if commande.cmd == "start_mode":
        rep["already_running"] = commande.mode in (ack.get("deja") or ())
    elif commande.cmd == "stop_mode":
        rep["already_stopped"] = ack.get("deja") is True
    elif commande.cmd == "propose_params":
        rep["key"] = ack.get("key")
        rep["value"] = ack.get("value")
    # Le moteur dit « pas d'avertissement » par None, par une chaîne vide ou en n'en mettant pas :
    # l'application reçoit toujours null.
    rep["warning"] = ack.get("warning") or None
    rep = pour_le_contrat(rep)
    params = rep.get("params")
    if isinstance(params, dict) and isinstance(params.get("model"), str) and params["model"]:
        params["model"] = os.path.basename(params["model"])
    return rep


def echec(ref, cmd, mode, raison):
    """Le second message d'une commande ACCEPTÉE qui a échoué ensuite dans la boucle du moteur.

    Sans lui, l'application attendrait un mode qui ne démarrera jamais."""
    return {"ref": ref, "cmd": cmd, "mode": mode, "event": "failed",
            "reason": pour_le_contrat(raison)}


# Les deux causes du message « disconnected » : « Déconnecter » dans la console, ou l'arrêt du
# moteur (la console qu'on ferme, `server.py` qu'on arrête).
CAUSES_DECONNEXION = ("console", "engine_stopped")


def deconnexion(app, arretes, cause):
    """Le message qui dit à une application que le moteur ne lit plus son flux de commandes. En
    ANGLAIS. Ce n'est pas une réponse : son « ref » vaut null. Il est là quand même, comme dans
    tout message du flux de réponses : un client qui lit `reply["ref"]` sans précaution (ou
    `msg.ref` après `jsondecode` en MATLAB) lèverait sinon sur celui-ci, et sur lui seul.

    `app` : le `source_id` COMPLET de son flux de commandes — le flux de réponses est commun à
    toutes les applications de la machine, et c'est lui qui fait reconnaître à chacune SON
    message (le nom de la liste de la console est coupé à `CMD_AFFICHEE_MAX` caractères : deux
    noms longs coupés pourraient se confondre). `arretes` : les modes que le moteur arrête.
    `cause` : une de `CAUSES_DECONNEXION`.

    ⚠️ Sans ce message, l'application ne saurait rien : LSL ne lui dit qu'un lecteur est parti
    (`have_consumers()` faux) qu'à son PROCHAIN envoi (mesuré : vrai plus de 6 s sans envoi), et
    une application qui attend ses décisions n'envoie rien.
    """
    if cause not in CAUSES_DECONNEXION:
        # Une faute de frappe partirait sinon sur le réseau avec la raison de la console.
        raise ValueError(f"cause inconnue : {cause!r} (attendu : {', '.join(CAUSES_DECONNEXION)})")
    raison = (tr("moteur.reseau.moteur_arrete") if cause == "engine_stopped"
              else tr("moteur.reseau.deconnectee"))
    return {"ref": None, "event": "disconnected", "cause": cause, "app": app,
            "stopped": [str(m) for m in arretes], "reason": pour_le_contrat(raison)}


def _meme_hote(a, b):
    """Deux noms d'hôte égaux SANS casse — le nom que publie liblsl et celui de
    `socket.gethostname()` sont égaux sur le poste, à la casse près."""
    return (a or "").casefold() == (b or "").casefold()


def _tampon(info):
    """Le `max_buflen` de l'inlet d'une application : ~`COMMANDES_EN_ATTENTE` commandes.

    Une application peut déclarer un débit nominal (par erreur : le contrat dit « irrégulier ») ;
    pylsl compte alors le tampon en SECONDES, et `TAMPON_INLET` ne garderait qu'une seconde de
    commandes, voire rien sous 1 Hz."""
    try:
        debit = float(info.nominal_srate())
    except Exception:  # noqa: BLE001 - un flux mal formé garde le tampon du contrat
        debit = 0.0
    if debit > 0.0 and math.isfinite(debit):
        return max(1, math.ceil(COMMANDES_EN_ATTENTE / debit))
    return TAMPON_INLET


def _decrire(e):
    """« Type : message » d'une exception, pour le terminal. Ne lève jamais."""
    try:
        return f"{type(e).__name__} : {e}"
    except Exception:  # noqa: BLE001 - un message d'exception qui ne s'écrit pas
        return type(e).__name__


class Seau:
    """Un seau de jetons : `prendre()` est vrai tant que l'application reste sous `debit`
    commandes par seconde, rafales de `debit` commandes comprises.

    Le seau se remplit de `debit` jetons par seconde, jusqu'à `debit` ; chaque commande en prend
    un. Le temps est celui de la LECTURE de la commande, pas l'horodatage de l'application : une
    application choisit ses horodatages, et pourrait ainsi passer la borne.
    """

    def __init__(self, debit=DEBIT_MAX, maintenant=None):
        self.debit = float(debit)
        self.jetons = float(debit)
        self.t = time.monotonic() if maintenant is None else maintenant

    def prendre(self, maintenant=None):
        maintenant = time.monotonic() if maintenant is None else maintenant
        self.jetons = min(self.debit, self.jetons + (maintenant - self.t) * self.debit)
        self.t = maintenant
        if self.jetons >= 1.0:
            self.jetons -= 1.0
            return True
        return False


def refus_debit(seau, maintenant=None):
    """Le refus d'une commande en trop (au-delà de `DEBIT_MAX` par seconde), ou None si le seau
    de l'application a encore un jeton. Le même pour les deux transports, LSL et UDP."""
    if seau.prendre(maintenant):
        return None
    return tr("moteur.reseau.trop_de_commandes", n=nombre(DEBIT_MAX))


@dataclass
class _Application:
    """Une application branchée : l'inlet de son flux de commandes, son seau de jetons, et le
    `source_id` COMPLET de son flux ("" s'il n'en a pas, None s'il est illisible), que le message
    « disconnected » lui rend."""
    inlet: object
    seau: Seau = field(default_factory=Seau)
    source: object = None


def _octets_illisibles(e):
    """Les octets d'une commande que pylsl n'a pas pu décoder : `UnicodeDecodeError.object`.

    L'échantillon est déjà retiré de l'inlet : ces octets sont tout ce qui en reste. Le flux du
    contrat n'a qu'une voie, donc ce sont ceux de la commande. Sans eux (une exception fabriquée
    ailleurs), un octet invalide quelconque garde à la commande sa raison : « pas de l'UTF-8 »."""
    octets = getattr(e, "object", None)
    return bytes(octets) if isinstance(octets, (bytes, bytearray)) else b"\xff"


def _jeton(reseau, command):
    """(ref, cmd, mode) d'un jeton réseau. Ne lève jamais."""
    if isinstance(reseau, tuple) and len(reseau) == 3:
        return reseau
    return None, command, None


def _en_json(x):
    """Ce que `json` ne sait pas écrire seul : un nombre ou un tableau numpy, un ensemble."""
    for methode in ("item", "tolist"):
        if hasattr(x, methode):
            try:
                return getattr(x, methode)()
            except Exception:  # noqa: BLE001 - `item()` lève sur un tableau de plusieurs
                continue       # valeurs : on essaie `tolist()`
    if isinstance(x, (set, frozenset)):
        return sorted(x, key=str)
    return str(x)


def _dire(message):
    """Un message au terminal. Ne lève jamais (sortie fermée, encodage)."""
    try:
        print(message, flush=True)
    except Exception:  # noqa: BLE001 - un affichage impossible ne tue pas le fil d'écoute
        pass


def _referme(inlet):
    try:
        inlet.close_stream()
    except Exception:  # noqa: BLE001 - refermer un flux déjà mort ne doit rien lever
        pass


class Pilotage:
    """L'adaptateur réseau du moteur. Un seul fil écrit dans l'outlet de réponses : le sien.

    - `__init__` crée l'outlet de réponses tout de suite : il existe dès que le moteur existe.
    - `demarrer()` lance le fil d'écoute ; `arreter()` l'arrête (en moins de 2 s) ; `fermer()`
      retire le flux de réponses du réseau, définitivement.
    - `traiter(texte)` lit une commande, la soumet, inscrit le résultat au journal et rend la
      réponse (sans la publier : c'est le fil qui publie).
    - `signaler_echec(reseau, command, raison)` est le rappel `sur_echec` du moteur, appelé depuis
      SA boucle : il ne fait que déposer l'échec dans une file que le fil d'écoute publie.
    - `journal()` : les dernières commandes, pour la console, raisons dans la langue de l'écran.
    - Écoute « sur_demande » (la console) : `chercher(True)` lit les annonces SANS ouvrir de flux,
      `annonces()` les rend, `connecter(uid)` ouvre CETTE application seulement,
      `deconnecter(arretes)` la referme, après lui avoir publié le message « disconnected »
      (`deconnexion`) ; une application connectée qui disparaît est signalée au moteur par
      `engine.application_partie(uid)`.
    - `annoncer_arret(arretes)` : le MOTEUR s'arrête. À l'arrêt du fil (`arreter()`), chaque
      application écoutée reçoit « disconnected », cause « engine_stopped ». Un simple arrêt du
      fil, sans cette annonce, ne dit rien : le fil peut redémarrer.
    - Sur demande seulement, `ouvrir_udp()` ouvre le transport UDP (`etat_udp()` dit s'il est
      ouvert) : ses appareils rejoignent `annonces()` pendant une recherche, `connecter(uid)`
      fait la poignée de main, `identifier(uid)` demande à l'un d'eux de se signaler. Son fil
      est celui-ci : `TransportUDP.tour()` est appelé à chaque tour.

    `engine` n'est utilisé que par `engine.submit(...)`, `engine.instance` et, sur demande,
    `engine.application_partie(uid)` — `(uid, raison=…, hote=…)` pour un appareil UDP (busy, sans
    réponse, silence, bye). `hote` n'existe que pour l'autotest, qui fait passer cette machine
    pour une autre.
    """

    def __init__(self, engine, nom_flux=NOM_FLUX_COMMANDES, hote=None, ecoute="permanente"):
        if ecoute not in ECOUTES:
            raise ValueError(f"écoute inconnue : {ecoute!r} (attendu : {', '.join(ECOUTES)})")
        self.engine = engine
        self.ecoute = ecoute
        self.nom_flux = str(nom_flux)
        self.hote = socket.gethostname() if hote is None else str(hote)
        info = StreamInfo(NOM_FLUX_REPONSES, "Markers", 1, IRREGULAR_RATE, "string",
                          _source_id(SUFFIXE_REPONSES, getattr(engine, "instance", "")))
        self._outlet = StreamOutlet(info)
        self._echecs = queue.SimpleQueue()      # (ref, cmd, mode, raison), de n'importe quel fil
        self._journal = collections.deque(maxlen=JOURNAL_N)
        self._verrou = threading.Lock()         # protège le journal et l'écoute sur demande
        # Tenu de `submit` jusqu'au journal (`traiter`), et pour inscrire un échec : un échec
        # signalé PENDANT `submit` n'est inscrit qu'après l'accusé de sa commande.
        self._verrou_ordre = threading.Lock()
        self._arret = threading.Event()
        self._fil = None
        self._ferme = False
        self.connexions = 0     # inlets ouverts sur une application
        self.perdus = 0         # applications parties (leur flux a disparu)
        self.publiees = 0       # réponses et échecs publiés
        self._etrangers_dits = set()   # uid des flux d'une autre machine déjà signalés
        self._illisibles_dits = set()  # uid (ou None) des flux mal formés déjà signalés
        # L'écoute SUR DEMANDE : la recherche, ce qu'elle voit, l'application choisie.
        self._recherche = False
        self._annonces = {}            # uid -> {"uid", "nom", "illisible", "depuis"}
        # `_choisie` est écrite sous le verrou et lue SANS lui par le fil d'écoute : une seule
        # valeur, qu'une écriture remplace d'un coup ; au pire, la lecture a un tour de retard.
        self._choisie = None           # uid de l'application connectée, ou None
        self._branchee = False         # son flux est-il ouvert ? (écrit par le fil d'écoute)
        # Les messages « disconnected » à publier avant de refermer un flux : uid -> les modes
        # arrêtés. Écrits sous le verrou par `deconnecter()` (n'importe quel fil), publiés par le
        # fil d'écoute, le seul qui écrit sur le flux de réponses.
        self._adieux = {}
        # L'arrêt du MOTEUR annoncé (`annoncer_arret`) : les modes arrêtés, ou None.
        self._arret_moteur = None
        # Le transport UDP (sur demande, `ouvrir_udp`), ou None ; et pourquoi il n'a pas pu
        # s'ouvrir (un `Texte`), ou None.
        self._udp = None
        self._udp_raison = None
        # Ce que le moteur pousse à l'appareil réseau connecté (`pousser`), déposé par la boucle
        # du moteur et envoyé par CE fil, à chaque tour (`_envoyer_poussees`).
        self._poussees = collections.deque(maxlen=POUSSEES_MAX)

    # --- le cycle de vie ---------------------------------------------------------------------

    @property
    def vivant(self):
        fil = self._fil
        return fil is not None and fil.is_alive()

    def demarrer(self):
        """Lance le fil d'écoute. True s'il tourne. Sans effet s'il tourne déjà ; False après
        `fermer()`."""
        if self._ferme:
            return False
        if self.vivant:
            if not self._arret.is_set():
                return True
            # Un fil qu'on vient d'arrêter n'est pas encore sorti : on l'attend, pour ne jamais
            # en avoir deux qui lisent les mêmes commandes.
            self._fil.join(timeout=ARRET_S)
            if self.vivant:
                return False
        self._arret.clear()
        with self._verrou:
            self._arret_moteur = None   # une écoute neuve : aucun arrêt n'est annoncé
        self._fil = threading.Thread(target=self._boucle, daemon=True,
                                     name=f"pilotage-{self.nom_flux}")
        self._fil.start()
        return True

    def annoncer_arret(self, arretes=()):
        """Le MOTEUR s'arrête : à l'arrêt du fil d'écoute (`arreter()`, juste après), chaque
        application écoutée reçoit le message « disconnected », cause « engine_stopped », avec
        `arretes` (les modes qui tournaient), avant que son flux ne se referme. Sans lui, une
        application qui attend sans limite (un démarrage différé) attendrait pour toujours.

        Ne publie rien lui-même : seul le fil d'écoute écrit sur le flux de réponses."""
        with self._verrou:
            self._arret_moteur = tuple(arretes)

    def arreter(self):
        """Arrête le fil d'écoute et referme ses inlets. True s'il est mort à la sortie."""
        self._arret.set()
        fil = self._fil
        if fil is not None and fil is not threading.current_thread():
            fil.join(timeout=ARRET_S)
        return not self.vivant

    def fermer(self):
        """Retire le flux de réponses du réseau : sans ça, il resterait annoncé, muet, sous le
        nom que le moteur suivant publiera. Arrête d'abord le fil s'il tourne, et rend le port
        UDP."""
        self.arreter()
        self._ferme = True
        self._outlet = None
        self.fermer_udp()

    def fermer_udp(self):
        """Rend le port UDP (le moteur s'arrête). Le flux de réponses, lui, reste annoncé jusqu'à
        `fermer()`. À appeler une fois le fil arrêté : c'est lui qui se sert de la socket."""
        udp, self._udp = self._udp, None
        self._poussees.clear()
        if udp is not None:
            udp.fermer()

    # --- le transport UDP (sur demande) ------------------------------------------------------

    def ouvrir_udp(self, port=None, adresse="0.0.0.0", maintenant=time.monotonic):
        """Ouvre le transport UDP sur `port` (`pilotage_udp.PORT_UDP` par défaut). Rend None s'il
        écoute, sinon la raison (un `Texte` : le port est pris, par exemple).

        En écoute permanente (`server.py` seul), rien ne s'ouvre et rien n'est refusé : sans
        écran, personne ne peut cliquer « Connecter ». `etat_udp()` dit alors `ouvert: False`,
        sans raison. `maintenant` : l'horloge des délais du transport (l'autotest la remplace)."""
        if self.ecoute != "sur_demande" or self._ferme:
            return None
        if self._udp is not None:
            return None
        # Importé ici : `pilotage_udp` importe ce module.
        from core.pilotage_udp import PORT_UDP, TransportUDP
        transport = TransportUDP(self, port=PORT_UDP if port is None else port,
                                 adresse=adresse, maintenant=maintenant)
        raison = transport.ouvrir()
        self._udp_raison = raison
        self._udp = transport if raison is None else None
        return raison

    def etat_udp(self):
        """`{"ouvert", "raison", "port"}` : le transport UDP écoute-t-il, et sinon pourquoi (un
        `Texte`, ou None) ; son port quand il écoute, sinon None."""
        udp = self._udp
        ouvert = udp is not None and udp.ouvert
        return {"ouvert": ouvert, "raison": self._udp_raison,
                "port": udp.port if ouvert else None}

    def pousser(self, message):
        """Dépose un message que le moteur pousse à l'appareil réseau connecté : `{"status":
        …}` ou `{"decision": …}`. Sûr depuis n'importe quel fil : la boucle du moteur l'appelle,
        le fil d'écoute l'envoie au tour suivant, précédé de "v" et de "seq".

        Rend False sans rien garder si aucun appareil réseau n'est connecté : rien n'est gardé
        pour plus tard, une décision périmée ne sert à rien."""
        udp = self._udp
        if udp is None or udp.connecte() is None:
            return False
        self._poussees.append(message)
        return True

    def _envoyer_poussees(self):
        """Envoie ce que le moteur a poussé, par le point de sortie unique. Seul le fil d'écoute
        l'appelle. Un message déposé avant une déconnexion est jeté : rien ne part après
        « disconnected »."""
        udp = self._udp
        while True:
            try:
                message = self._poussees.popleft()
            except IndexError:
                return
            lie = udp.connecte() if udp is not None else None
            if lie is not None and lie == self._choisie:
                self._envoyer(message, lie)

    def identifier(self, uid):
        """Demande à l'appareil réseau `uid` de se signaler (« Identifier » : une LED qui
        clignote). True si la demande part ; False pour une application LSL ou un appareil que
        le réseau ne voit plus."""
        udp = self._udp
        return bool(udp is not None and udp.identifier(uid))

    def _est_udp(self, uid):
        udp = self._udp
        return udp is not None and udp.est_a_lui(uid)
    # --- l'écoute sur demande (la console) ---------------------------------------------------

    def chercher(self, actif):
        """Lance ou arrête la RECHERCHE : lire les annonces des applications du réseau,
        sans ouvrir aucun flux. Sans effet en écoute permanente."""
        with self._verrou:
            self._recherche = bool(actif) and self.ecoute == "sur_demande"
            if not self._recherche:
                self._annonces = {}

    def annonces(self):
        """Ce que la recherche voit, de la plus ancienne à la plus récente (des copies) :
        `{"uid", "nom", "illisible", "depuis", "origine", "machine", "id"}`. `origine` vaut
        "lsl" ici ; `machine` est le nom d'hôte du flux ; `id` vaut None pour LSL. `nom` est le `source_id` du flux ("" s'il n'en a
        pas ou s'il est illisible, `illisible` le dit) ; `depuis` est un `time.time()`.

        Les appareils réseau (`origine` « udp », `TransportUDP.appareils`) s'y ajoutent pendant
        une recherche, et seulement pendant elle."""
        with self._verrou:
            vues = [dict(a) for a in self._annonces.values()]
            recherche = self._recherche
        udp = self._udp
        if recherche and udp is not None:
            vues.extend(udp.appareils())
        return sorted(vues, key=lambda a: (a["depuis"], a["uid"]))

    def connecter(self, uid):
        """Choisit l'application `uid` parmi celles que la recherche voit. Rend son nom, ou None
        si elle n'y est pas. La recherche s'arrête ; le fil ouvre son flux au tour suivant.

        ⚠️ Le nom peut être vide (un flux sans `source_id`) : le refus se teste par `is None`,
        jamais par la valeur de vérité. Choisir une application quand une autre l'est déjà la
        REMPLACE sans signaler de départ : refuser une seconde connexion est l'affaire du
        MOTEUR.

        Un appareil réseau reçoit alors « connect » ; s'il ne répond pas « connected » en 3 s,
        ou s'il est occupé, le moteur l'apprend par `engine.application_partie`."""
        udp = self._udp
        if udp is not None and udp.est_a_lui(uid):
            with self._verrou:
                annonce = next((a for a in udp.appareils() if a["uid"] == uid), None)
                if (self.ecoute != "sur_demande" or not self._recherche or annonce is None
                        or not udp.connecter(uid)):
                    return None
                self._choisie = uid
                self._recherche = False
                self._annonces = {}
                return annonce["nom"]
        with self._verrou:
            annonce = self._annonces.get(uid)
            if self.ecoute != "sur_demande" or annonce is None:
                return None
            self._choisie = uid
            self._recherche = False
            self._annonces = {}
            return annonce["nom"]

    def deconnecter(self, arretes=(), adieu=True):
        """N'écoute plus aucune application. Le fil referme son flux au tour suivant.

        `adieu` : le fil lui publie d'abord le message « disconnected » (cause « console »), avec
        `arretes`, les modes que le moteur arrête. Seulement si son flux était OUVERT : une
        application jamais ouverte ne s'est jamais crue connectée. `adieu=False` quand
        l'application est partie d'elle-même : elle ne lit plus rien, et une copie relancée sous
        le même nom prendrait le message pour elle."""
        with self._verrou:
            if adieu and self._choisie is not None:
                self._adieux[self._choisie] = tuple(arretes)
            self._choisie = None

    def branchee(self):
        """Le flux de l'application choisie est-il ouvert ?"""
        return self._branchee

    def _doit_chercher(self):
        """Faut-il lire les annonces du réseau ? Toujours en écoute permanente ; sur demande,
        seulement pendant une recherche ou pour l'application LSL choisie (un appareil réseau
        n'a pas de flux à chercher)."""
        choisie = self._choisie
        return (self.ecoute == "permanente" or self._recherche
                or (choisie is not None and not self._est_udp(choisie)))

    def _noter_annonces(self, annonces):
        """La recherche : les applications de TOUTES les machines que le résolveur voit, avec
        l'heure où chacune est apparue et leur machine. Aucun flux n'est ouvert ici."""
        with self._verrou:
            if not self._recherche:
                return
            vues = {}
            for uid, (_info, hote, source) in annonces.items():
                avant = self._annonces.get(uid)
                # Le nom vient du `source_id` de l'application, sans borne de longueur : coupé
                # comme au journal, pour qu'un nom démesuré n'envahisse ni la liste ni le bandeau.
                vues[uid] = {"uid": uid, "nom": _court(source or ""), "illisible": source is None,
                             "depuis": avant["depuis"] if avant else time.time(),
                             "origine": "lsl", "machine": _court(hote or ""), "id": None}
            self._annonces = vues

    def _lacher_les_autres(self, inlets):
        """Sur demande : referme le flux de toute application qui n'est plus la choisie
        (« Déconnecter »), et tient `branchee` à jour.

        Le message « disconnected » part AVANT la fermeture, pour chaque application dont le
        flux est ouvert. L'application choisie et ses messages sont lus ENSEMBLE, sous le
        verrou : `deconnecter()` les écrit ensemble, et un message ne peut donc pas manquer à une
        application qu'on referme.

        Un appareil réseau suit la même règle : « disconnected » seulement s'il a répondu
        « connected », puis il est oublié. Sa connexion est lue avec l'application choisie, sous
        le même verrou : un « Connecter » qui passe entre les deux ne peut pas être oublié."""
        if self.ecoute != "sur_demande":
            return
        udp = self._udp
        with self._verrou:
            choisie = self._choisie
            adieux, self._adieux = self._adieux, {}
            lien = udp.lien() if udp is not None else None
        for uid, arretes in adieux.items():
            app = inlets.get(uid)
            if app is not None:     # jamais ouverte : elle ne s'est jamais crue connectée
                self._dire_adieu(app, arretes, "console")
            elif udp is not None and udp.est_a_lui(uid):
                udp.deconnecter(uid, arretes, "console")
        for uid in [u for u in inlets if u != choisie]:
            _referme(inlets.pop(uid).inlet)
            _dire(f"[pilotage] application déconnectée de « {self.nom_flux} »")
        if lien is not None and lien.uid != choisie:
            udp.oublier(lien)       # une autre application est choisie : oublié, sans message
        self._branchee = choisie is not None and (
            choisie in inlets or (udp is not None and udp.connecte() == choisie))

    def _dire_adieu(self, app, arretes, cause):
        """Publie le message « disconnected » à l'application `app` (`_Application`). Seul le fil
        d'écoute l'appelle. Ne lève jamais : un message impossible ne tue pas le fil."""
        try:
            message = deconnexion(app.source, arretes, cause)
        except Exception as e:  # noqa: BLE001 - un texte du catalogue introuvable, par exemple
            _dire(f"[pilotage] message « disconnected » impossible à écrire : {_decrire(e)}")
            return
        self._publier(message)

    def _adieux_a_l_arret(self, inlets):
        """Le fil d'écoute s'arrête : chaque flux encore ouvert reçoit le message « disconnected »
        qui l'attend (« Déconnecter » juste avant l'arrêt), ou, si le MOTEUR s'arrête
        (`annoncer_arret`), celui de cause « engine_stopped ». Sans annonce, rien : le fil peut
        redémarrer, et l'application rester connectée."""
        with self._verrou:
            adieux, self._adieux = self._adieux, {}
            arret = self._arret_moteur
        for uid, app in inlets.items():
            if uid in adieux:
                self._dire_adieu(app, adieux[uid], "console")
            elif arret is not None:
                self._dire_adieu(app, arret, "engine_stopped")
        udp = self._udp
        lie = udp.connecte() if udp is not None else None
        if lie is not None:
            if lie in adieux:
                udp.deconnecter(lie, adieux[lie], "console")
            elif arret is not None:
                udp.deconnecter(lie, arret, "engine_stopped")

    def _application_partie(self, uid, raison=None, hote=None):
        """L'application choisie a disparu : on ne l'écoute plus, et on le dit au moteur, qui
        arrête ce qu'elle avait démarré. Le rappel ne doit jamais tuer le fil. Rend True si `uid`
        était bien l'application choisie (le départ est alors dit au terminal et au moteur),
        False sinon (une déconnexion demandée a pris les devants : rien à signaler).

        `raison`, `hote` : ceux d'un appareil UDP (`TransportUDP`), passés au moteur ; une
        application LSL partie n'en a pas."""
        with self._verrou:
            if self._choisie != uid:
                return False
            self._choisie = None
        self._branchee = False
        _dire(f"[pilotage] l'application connectée est partie de « {self.nom_flux} »"
              + (f" ({raison})" if raison else ""))
        precisions = {k: v for k, v in (("raison", raison), ("hote", hote)) if v is not None}
        try:
            self.engine.application_partie(uid, **precisions)
        except Exception as e:  # noqa: BLE001 - un rappel en panne ne tue pas le fil d'écoute
            _dire(f"[pilotage] fin de connexion impossible à signaler : {_decrire(e)}")
        return True

    # --- commandes, réponses, journal --------------------------------------------------------

    def traiter(self, texte, refus=None):
        """Lit une commande, la soumet au moteur, l'inscrit au journal et rend la réponse.

        Le jeton passé à `submit` est (ref, cmd, mode) : le moteur le rend à `signaler_echec` si
        la commande échoue plus tard, et la réponse d'échec en tire ce que l'application a envoyé.

        `refus` (un `Texte`) refuse la commande sans la soumettre : l'application a dépassé
        `DEBIT_MAX`. Une commande illisible garde sa propre raison, plus utile à corriger.
        """
        commande = lire_commande(texte)
        if refus is not None and commande.refus is None:
            commande.refus = refus
        with self._verrou_ordre:
            if commande.refus is not None:
                ack = {"accepted": False, "reason": commande.refus}
            else:
                _completer_cle(commande)
                try:
                    ack = self.engine.submit(commande.cmd,
                                             reseau=(commande.ref, commande.cmd, commande.mode),
                                             **commande.kwargs)
                except Exception as e:  # noqa: BLE001 - `submit` ne doit pas lever ; s'il le
                    # fait, l'application reçoit un refus et le fil continue
                    _dire(f"[pilotage] « {commande.cmd} » a fait lever le moteur : {e!r}")
                    ack = {"accepted": False, "reason": message_erreur(e)}
            rep = reponse(commande, ack)
            # Au journal, la réserve et la raison restent dans la langue de l'ÉCRAN (des `Texte`
            # que la console retraduit) ; c'est la réponse qui part en anglais.
            accepte = rep["accepted"]
            self._inscrire(commande.cmd, commande.mode, accepte,
                           None if accepte else ack.get("reason"), None,
                           bool(rep.get("already_running") or rep.get("already_stopped")),
                           bool(rep.get("deferred")),
                           (ack.get("warning") or None) if accepte else None)
        return rep

    def signaler_echec(self, reseau, command, raison):
        """Une commande acceptée a échoué dans la boucle du moteur. Sûr depuis n'importe quel fil.

        La commande et le mode viennent du JETON, pas de `command` : le jeton porte ce que
        l'application a envoyé, `command` le nom de ce que la boucle exécutait — le même
        aujourd'hui, mais rien ne l'impose (une commande interne qui en sert une autre). Et
        l'application ne connaît que ce qu'elle a envoyé.

        L'échec est inscrit au journal par le fil d'écoute, quand il le publie : le journal suit
        ainsi l'ordre du réseau (l'accusé, puis l'échec), même quand la boucle signale l'échec
        avant que `submit` ait rendu son accusé.
        """
        self._echecs.put((*_jeton(reseau, command), raison))

    def journal(self):
        """Les dernières entrées, de la plus ancienne à la plus récente (copies).

        `{"t": time.monotonic(), "cmd", "mode", "accepted", "raison", "event", "deja", "differe",
        "warning"}` : `raison` et `warning` sont dans la langue de l'ÉCRAN (des `Texte`, que la
        console peut retraduire), `warning` étant la réserve d'une commande acceptée, ou None ;
        `event` vaut "failed" pour un échec après acceptation (alors `accepted` vaut False : la
        commande n'a pas abouti) ; `deja` dit « déjà en route » / « déjà arrêté » ; `differe` dit
        qu'un réglage est RETENU sur un mode arrêté. `cmd` et `mode` sont ceux de l'application,
        coupés à `CMD_AFFICHEE_MAX` caractères.
        """
        with self._verrou:
            return [dict(e) for e in self._journal]

    def _inscrire(self, cmd, mode, accepte, raison, event, deja, differe, warning=None):
        entree = {"t": time.monotonic(), "cmd": _court(cmd), "mode": _court(mode),
                  "accepted": bool(accepte), "raison": raison, "event": event,
                  "deja": bool(deja), "differe": bool(differe), "warning": warning}
        with self._verrou:
            self._journal.append(entree)

    def _publier(self, message):
        """Publie un message JSON sur le flux de réponses. Seul le fil d'écoute l'appelle.

        ⚠️ LSL ne garde rien pour une application qui n'écoute pas encore : ce qui est publié
        avant qu'elle ait ouvert son inlet de réponses est perdu (piège 2 de l'en-tête).
        """
        outlet = self._outlet            # une seule lecture : `fermer()` peut le lâcher
        if outlet is None:
            return False
        try:
            # JSON en ASCII (les accents deviennent « \u00e9 ») : lisible par toutes les
            # bibliothèques LSL, quel que soit l'encodage qu'elles supposent pour une chaîne.
            outlet.push_sample([json.dumps(message, default=_en_json)])
        except Exception as e:  # noqa: BLE001 - une réponse impossible ne tue pas le fil
            _dire(f"[pilotage] réponse impossible à publier ({type(e).__name__} : {e})")
            return False
        self.publiees += 1
        return True

    def _envoyer(self, message, uid=None):
        """LE point de sortie vers les applications : réponses, échecs, et ce que le moteur
        pousse. Seul le fil d'écoute l'appelle.

        `uid` : l'application destinataire ; None = celle qui est connectée. Un appareil réseau
        reçoit le message par sa socket (`TransportUDP.envoyer`, seulement s'il est connecté) ;
        tout le reste part sur le flux de réponses, commun aux applications LSL."""
        cible = self._choisie if uid is None else uid
        udp = self._udp
        if udp is not None and udp.est_a_lui(cible):
            return udp.envoyer(cible, message)
        return self._publier(message)

    def servir(self, texte, refus, uid):
        """Une commande lue par un transport, venue de l'application `uid` : le chemin unique
        (`traiter`, ou son refus s'il lève), puis la réponse par le point de sortie unique.
        `refus` : un `Texte` qui refuse la commande sans la soumettre (trop de commandes, un
        mode que le transport ne sert pas), ou None."""
        return self._envoyer(self._traiter_sans_lever(texte, refus), uid)

    def _traiter_sans_lever(self, texte, refus=None):
        """`traiter`, ou — si un défaut le fait lever — un refus au bon « ref », inscrit au
        journal pour que la console le montre."""
        try:
            return self.traiter(texte, refus)
        except Exception as e:  # noqa: BLE001 - un défaut ici ne doit pas tuer le fil d'écoute
            _dire(f"[pilotage] commande impossible à traiter : {_decrire(e)}")
            commande = lire_commande(texte)        # ne lève jamais : de quoi répondre au « ref »
            raison = message_erreur(e)
            self._inscrire(commande.cmd, commande.mode, False, raison, None, False, False)
            return {"ref": commande.ref, "cmd": commande.cmd, "mode": commande.mode,
                    "accepted": False, "reason": pour_le_contrat(raison)}

    def _publier_echecs(self):
        while True:
            try:
                ref, cmd, mode, raison = self._echecs.get_nowait()
            except queue.Empty:
                return
            try:
                message = echec(ref, cmd, mode, raison)
            except Exception as e:  # noqa: BLE001
                message = echec(ref, cmd, mode, message_erreur(e))
            with self._verrou_ordre:
                self._inscrire(cmd, mode, False, raison, "failed", False, False)
            self._envoyer(message)

    # --- le fil d'écoute ---------------------------------------------------------------------

    def _boucle(self):
        """Découvre les applications, lit leurs commandes, publie réponses et échecs.

        Une application par flux de commandes écouté, repérée par son `uid` (unique
        pour chaque outlet créé : une application relancée a un uid neuf). `ecartes[uid]` :
        jusqu'à quand ne pas (re)ouvrir ce flux — `BANNI_PERDU_S` pour un flux perdu, `REESSAI_S`
        après une ouverture ratée. Un uid qui n'est plus annoncé est oublié.

        ⚠️ `self._arret` est relu avant CHAQUE ouverture et CHAQUE commande : une ouverture peut
        attendre `OUVERTURE_S`, un `submit` ~0,3 s. L'arrêt attend donc au plus une ouverture ou
        un `submit` en cours, jamais une rafale entière.

        🔴 Ce fil ne meurt pas avant `arreter()`. Un défaut imprévu pendant un tour est dit au
        terminal (une fois de suite), puis le fil attend `REESSAI_S` et reprend. Mort, il ne
        répondrait plus à aucune commande jusqu'à la fin de la séance, sans aucun signe.

        Sur demande (la console), le résolveur n'existe que pendant une recherche ou pour
        l'application choisie : sinon le fil ne lit RIEN du réseau. `resolveur_ne` est l'instant
        de sa création, dont `_decouvrir` a besoin pour savoir s'il a eu le temps de voir.
        """
        resolveur, dit_resolveur = None, False
        resolveur_ne = None
        inlets, ecartes = {}, {}
        prochaine = 0.0
        dernier_defaut = None
        try:
            while not self._arret.is_set():
                try:
                    maintenant = time.monotonic()
                    if maintenant >= prochaine:
                        prochaine = maintenant + DECOUVERTE_S
                        if not self._doit_chercher():
                            # Sur demande, sans recherche ni application choisie : on ne lit
                            # RIEN du réseau. Le résolveur lâché s'arrête de lui-même.
                            resolveur = None
                        elif resolveur is None:
                            try:
                                # Par NOM, jamais par type : le moteur publie lui-même des flux
                                # Markers (status, replies) et ne doit pas s'écouter.
                                resolveur = ContinuousResolver(prop="name", value=self.nom_flux,
                                                               forget_after=OUBLI_S)
                                # Pris APRÈS la création : l'âge ne peut être que sous-estimé.
                                resolveur_ne = time.monotonic()
                            except Exception as e:  # noqa: BLE001 - réessayé au tour suivant
                                if not dit_resolveur:
                                    dit_resolveur = True
                                    _dire(f"[pilotage] recherche des applications impossible : "
                                          f"{_decrire(e)}")
                        if resolveur is not None:
                            self._decouvrir(resolveur, inlets, ecartes, resolveur_ne)
                    self._lacher_les_autres(inlets)
                    for uid, app in list(inlets.items()):
                        if self._arret.is_set():
                            break
                        self._lire(uid, app, inlets, ecartes)
                    udp = self._udp
                    if udp is not None and not self._arret.is_set():
                        udp.tour()      # non bloquant : datagrammes, poignée de main, alive
                        self._envoyer_poussees()    # status et décisions du moteur
                    self._publier_echecs()
                    dernier_defaut = None   # un tour réussi : le prochain défaut sera redit
                except Exception as e:  # noqa: BLE001 - le fil d'écoute ne meurt pas : il reprend
                    texte = (f"[pilotage] défaut dans le fil d'écoute ({_decrire(e)}) - reprise "
                             f"dans {REESSAI_S:g} s")
                    if texte != dernier_defaut:
                        dernier_defaut = texte
                        _dire(texte)
                    self._arret.wait(REESSAI_S)
                    continue
                self._arret.wait(PAUSE_S)
        finally:
            # Un échec signalé juste avant l'arrêt part quand même. Puis le message
            # « disconnected » de chaque flux encore ouvert, AVANT qu'il ne se referme.
            try:
                self._publier_echecs()
            except Exception as e:  # noqa: BLE001 - les inlets sont refermés quoi qu'il arrive
                _dire(f"[pilotage] échecs impossibles à publier à l'arrêt : {_decrire(e)}")
            try:
                self._adieux_a_l_arret(inlets)
            except Exception as e:  # noqa: BLE001 - les inlets sont refermés quoi qu'il arrive
                _dire(f"[pilotage] messages « disconnected » impossibles à publier à l'arrêt : "
                      f"{_decrire(e)}")
            for app in inlets.values():
                _referme(app.inlet)
            inlets.clear()
            self._branchee = False
            resolveur = None

    def _lire_annonce(self, info):
        """(uid, nom d'hôte, source_id) d'un flux annoncé, ou None s'il faut l'ignorer.

        🔴 Ce que publie une application, ou N'IMPORTE QUELLE machine du réseau, ne doit pas faire
        lever le fil d'écoute. Une bibliothèque LSL d'un autre langage peut écrire ces champs dans
        l'encodage de Windows (« élève » en cp1252) : selon la version de pylsl, `uid()` ou
        `hostname()` LÈVENT alors (décodage UTF-8 strict), ou rendent un texte décodé autrement
        (pylsl 1.18 retombe sur latin-1). Sans uid, on ne peut pas suivre le flux ; sans nom
        d'hôte, on ne sait pas de quelle machine il vient : il est ignoré, et le terminal le dit
        une fois. Le source_id ne sert qu'au terminal : illisible, il vaut None et le flux reste
        écouté — ses commandes, elles, peuvent être du bon UTF-8.
        """
        uid = None
        try:
            uid = info.uid()
            hote = info.hostname() or ""
        except Exception as e:  # noqa: BLE001 - un flux mal formé est ignoré, pas fatal
            if uid not in self._illisibles_dits:
                self._illisibles_dits.add(uid)
                _dire(f"[pilotage] un flux « {self.nom_flux} » mal formé est ignoré "
                      f"({_decrire(e)}) : son identifiant ou son nom d'hôte n'est pas du texte "
                      f"UTF-8.")
            return None
        try:
            source = info.source_id() or ""
        except Exception:  # noqa: BLE001 - seulement affiché : le flux reste écouté
            source = None
        return uid, hote, source

    def _decouvrir(self, resolveur, inlets, ecartes, cree_a=None):
        """Branche chaque flux de commandes à écouter qui ne l'est pas encore : ceux de CETTE
        machine en écoute permanente, l'application choisie sur demande. Une annonce mal formée
        est ignorée sans empêcher les autres (`_lire_annonce`).

        `cree_a` : l'instant (`time.monotonic()`) où le résolveur a été créé. Sans lui, on le
        suppose assez vieux pour que ce qu'il ne voit pas soit vraiment absent."""
        try:
            resultats = list(resolveur.results())
        except Exception:  # noqa: BLE001 - la liste sera relue au tour suivant
            return
        annonces = {}                   # uid -> (info, nom d'hôte, source_id)
        for info in resultats:
            lue = self._lire_annonce(info)
            if lue is not None:
                annonces[lue[0]] = (info, lue[1], lue[2])
        for uid in [u for u in ecartes if u not in annonces]:
            del ecartes[uid]
        if self.ecoute == "sur_demande":
            self._noter_annonces(annonces)
            choisie = self._choisie
            # ⚠️ Une absence ne prouve rien avant que le résolveur ait eu le temps de voir : son
            # premier `results()` est TOUJOURS vide (mesuré). Un fil qu'on redémarre, application
            # toujours branchée, la prendrait pour partie dès son premier tour. On attend donc
            # que le résolveur ait `OUBLI_S` secondes, le délai qu'il met lui-même à oublier un
            # flux disparu.
            assez_vieux = cree_a is None or time.monotonic() - cree_a >= OUBLI_S
            # Un appareil réseau n'a pas de flux LSL : son départ, c'est son transport qui le dit.
            if (choisie is not None and not self._est_udp(choisie) and choisie not in inlets
                    and choisie not in annonces and assez_vieux):
                # Choisie, pas (ou plus) ouverte, et plus annoncée : elle est partie avant qu'on
                # ait pu l'écouter, ou après une erreur de lecture qui a fait lâcher son flux.
                self._application_partie(choisie)
                return
        maintenant = time.monotonic()
        for uid, (info, hote, source) in annonces.items():
            if self._arret.is_set():
                return
            if uid in inlets or ecartes.get(uid, 0.0) > maintenant:
                continue
            # Écoute permanente : seule la même machine pilote. Sur demande, le clic de l'élève
            # protège : une application d'une autre machine se choisit comme les autres.
            if self.ecoute == "permanente" and not _meme_hote(hote, self.hote):
                if uid not in self._etrangers_dits:
                    self._etrangers_dits.add(uid)
                    _dire(f"[pilotage] flux « {self.nom_flux} » d'une AUTRE machine "
                          f"(« {hote} ») ignoré : seule une application de "
                          f"« {self.hote} » pilote ce moteur.")
                continue
            if self.ecoute == "sur_demande" and uid != self._choisie:
                continue        # sur demande : seule l'application choisie est ouverte
            inlet = None
            try:
                # `recover=False` : quand l'application disparaît, `pull_sample` LÈVE, et on peut
                # lâcher l'inlet. Avec `recover=True`, il attendrait pour toujours l'ancien outlet.
                # `_tampon` : au plus ~100 commandes en attente (cf. `TAMPON_INLET`).
                inlet = StreamInlet(info, max_buflen=_tampon(info), recover=False)
                # Piège 1 : ouvrir TOUT DE SUITE. C'est cette connexion qui fait réussir le
                # `wait_for_consumers` de l'application ; tout ce qu'elle envoie ensuite arrive.
                inlet.open_stream(timeout=OUVERTURE_S)
            except Exception as e:  # noqa: BLE001 - application partie pendant la connexion
                if inlet is not None:
                    _referme(inlet)
                ecartes[uid] = maintenant + REESSAI_S
                _dire(f"[pilotage] connexion à une application impossible "
                      f"({_decrire(e)}) - nouvel essai dans {REESSAI_S:g} s")
                continue
            inlets[uid] = _Application(inlet, source=source)
            self.connexions += 1
            nom = source or ("sans source_id" if source is not None else "source_id illisible")
            _dire(f"[pilotage] application branchée sur « {self.nom_flux} » (« {nom} »)")

    def _lire(self, uid, app, inlets, ecartes):
        """Lit et sert les commandes en attente d'UNE application (`_Application`), dans les
        limites d'un tour (`MAX_PAR_TOUR`, `TEMPS_PAR_FLUX_S`). Chaque commande lue reçoit sa
        réponse ; au-delà de `DEBIT_MAX` par seconde, c'est un refus."""
        fin = time.monotonic() + TEMPS_PAR_FLUX_S
        for _ in range(MAX_PAR_TOUR):
            if self._arret.is_set() or time.monotonic() > fin:
                return                  # la suite au tour suivant : les autres flux d'abord
            if self.ecoute == "sur_demande" and uid != self._choisie:
                return                  # déconnectée en cours de tour : plus aucune commande
            try:
                echantillon, _ts = app.inlet.pull_sample(timeout=0.0)
            except LostError:
                # L'application est partie : on lâche. Une application relancée a un uid neuf,
                # découvert au tour suivant ; l'ancien n'est pas rouvert avant `BANNI_PERDU_S`.
                del inlets[uid]
                _referme(app.inlet)
                ecartes[uid] = time.monotonic() + BANNI_PERDU_S
                self.perdus += 1
                # Sur demande, le départ de l'application choisie est dit (et signalé au moteur)
                # par `_application_partie` : un seul message au terminal.
                if not (self.ecoute == "sur_demande" and self._application_partie(uid)):
                    _dire(f"[pilotage] application partie de « {self.nom_flux} »")
                return
            except UnicodeDecodeError as e:
                # Une commande qui n'est pas du texte UTF-8 (une bibliothèque LSL d'un autre
                # langage, qui écrit dans l'encodage de Windows). pylsl l'a déjà retirée de
                # l'inlet : elle est refusée pour cette raison et a sa réponse, comme les autres.
                # ⚠️ On garde l'inlet : lâché, il perdrait les commandes suivantes, sans réponse.
                texte = _octets_illisibles(e)
            except Exception as e:  # noqa: BLE001 - erreur LSL inattendue : on lâche et on réessaie
                del inlets[uid]
                _referme(app.inlet)
                ecartes[uid] = time.monotonic() + REESSAI_S
                _dire(f"[pilotage] lecture impossible ({_decrire(e)}) - "
                      f"nouvel essai dans {REESSAI_S:g} s")
                return
            else:
                if echantillon is None:
                    return
                # Un échantillon sans voie n'a pas de commande : il est illisible, et répondu.
                texte = echantillon[0] if echantillon else None
            self.servir(texte, refus_debit(app.seau), uid)


# --- Autotest ------------------------------------------------------------------------------------

class FauxMoteur:
    """Un moteur réduit à son `submit` : il note chaque appel et rend l'accusé préparé pour la
    commande. Selon le `ref` de la commande :
    - « boum » : `submit` LÈVE, pour vérifier que le fil d'écoute y survit ;
    - « nondict » : `submit` rend None au lieu d'un accusé (un défaut du moteur) ;
    - « vite » : la boucle du moteur signale l'échec (`rappel`) AVANT que `submit` ait rendu son
      accusé, puis `submit` tarde encore 0,1 s ;
    - « bloque » : `submit` tarde 1 s, le temps qu'une application envoie encore des commandes.
    `delai_s` : le temps que met `submit` à juger (une résolution réseau de `stream_in` ~0,3 s)."""

    def __init__(self, instance):
        self.instance = instance     # le `source_id` du flux de réponses en dépend
        self.appels = []             # (commande, jeton réseau, réglages)
        self.accuses = {}
        self.delai_s = 0.0
        self.rappel = None           # le `sur_echec` du vrai moteur
        self.parties = []            # les uid annoncés partis (`application_partie`)
        self.fins = []               # (uid, raison, hote) de chacun de ces départs

    def submit(self, command, reseau=None, **params):
        self.appels.append((command, reseau, params))
        ref = reseau[0] if isinstance(reseau, tuple) and reseau else None
        if self.delai_s:
            time.sleep(self.delai_s)
        if ref == "boum":
            raise RuntimeError("panne simulée du moteur")
        if ref == "nondict":
            return None
        if ref == "bloque":
            time.sleep(1.0)
        if ref == "vite" and self.rappel is not None:
            self.rappel(reseau, "set_params", tr("moteur.refus.aucun_mode_demande"))
            time.sleep(0.1)
        return dict(self.accuses.get(command, {"accepted": True, "command": command}))

    def application_partie(self, uid, raison=None, hote=None):
        """Le rappel du vrai moteur : l'application connectée a disparu. `raison` et `hote`
        viennent d'un appareil UDP (busy, sans réponse, silence, bye)."""
        self.parties.append(uid)
        self.fins.append((uid, raison, hote))


def _trouver_reponses(instance, delai_s):
    """Le flux de réponses de CE faux moteur : par son nom, PUIS par son `source_id`. Un moteur réel
    oublié sur le poste publie le même nom ; on ne doit pas prendre ses réponses pour les nôtres."""
    voulu = _source_id(SUFFIXE_REPONSES, instance)
    echeance = time.perf_counter() + delai_s
    while time.perf_counter() < echeance:
        for info in resolve_byprop("name", NOM_FLUX_REPONSES, minimum=32, timeout=0.2):
            if info.source_id() == voulu:
                return info
    return None


def _recevoir_brut(entree, n, delai_s, fini=None):
    """Jusqu'à `n` réponses TELLES QUE PUBLIÉES (le texte JSON) lues sur `entree`, en `delai_s`
    secondes au plus, ou jusqu'à ce que `fini(texte)` soit vrai pour l'une d'elles."""
    recues, echeance = [], time.perf_counter() + delai_s
    while len(recues) < n and time.perf_counter() < echeance:
        echantillon, _ts = entree.pull_sample(timeout=0.05)
        if echantillon is not None:
            recues.append(echantillon[0])
            if fini is not None and fini(echantillon[0]):
                break
    return recues


def _recevoir(entree, n, delai_s):
    """Jusqu'à `n` réponses JSON lues sur `entree`, en `delai_s` secondes au plus."""
    return [json.loads(t) for t in _recevoir_brut(entree, n, delai_s)]


def _deconnexions(entree, n, delai_s):
    """Jusqu'à `n` messages « disconnected » lus sur `entree`, en `delai_s` secondes au plus.
    Les autres messages sont lus et laissés de côté."""
    vus, echeance = [], time.perf_counter() + delai_s
    while len(vus) < n and time.perf_counter() < echeance:
        echantillon, _ts = entree.pull_sample(timeout=0.05)
        if echantillon is not None:
            message = json.loads(echantillon[0])
            if message.get("event") == "disconnected":
                vus.append(message)
    return vus


def _ferme_au_prochain_envoi(app, delai_s=2.0):
    """Vrai si LSL dit à l'application `app` que plus personne ne lit son flux de commandes.

    ⚠️ LSL ne le dit qu'APRÈS un envoi : un lecteur parti reste compté (`have_consumers()` vrai)
    tant que l'outlet ne pousse rien (mesuré : plus de 6 s). On pousse donc une commande sans
    effet toutes les 0,2 s. Personne ne la lit : elle n'a pas de réponse."""
    echeance = time.perf_counter() + delai_s
    while time.perf_counter() < echeance:
        app.push_sample(['{"cmd": "set_params", "mode": "ssvep", "params": {}, '
                         '"ref": "apres-la-fin"}'])
        time.sleep(0.2)
        if not app.have_consumers():
            return True
    return False


def _pousser_octets(app, octets):
    """Publie des OCTETS bruts sur l'outlet `app`, sans l'encodage UTF-8 de pylsl : ce que fait
    une bibliothèque LSL d'un autre langage qui écrit ses chaînes dans l'encodage de Windows.

    Deux versions de pylsl, deux chemins :
    - depuis 1.18.6, `push_sample` envoie des `bytes` tels quels ;
    - en 1.18.2, il encode CHAQUE valeur en UTF-8, et des `bytes` le font lever
      (`'bytes' object has no attribute 'encode'`) avant tout envoi. On appelle alors la
      fonction de liblsl qu'il appelle lui-même, avec les octets tels quels. ⚠️ Cet appel direct
      ne vaut QUE pour 1.18.2 : en 1.18.6 la même fonction attend en plus les longueurs, et
      l'appeler sans elles fait planter le processus (violation d'accès)."""
    try:
        app.push_sample([bytes(octets)])
        return
    except AttributeError:
        pass
    import ctypes

    from pylsl.util import handle_error
    handle_error(app.do_push_sample(app.obj, app.sample_type(bytes(octets)),
                                    ctypes.c_double(0.0), ctypes.c_int(1)))


def _selftest():
    import io
    import traceback
    from contextlib import redirect_stdout

    from core.i18n import Joint, joint

    # Raccourci le temps d'un test (section 8), puis remis.
    global REESSAI_S

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    def interrompu(section, e):
        """Une exception dans une section est un ÉCHEC dit, pas un autotest qui plante : les
        sections suivantes tournent quand même."""
        traceback.print_exc()
        chk(False, f"{section} : interrompu sur une exception ({e!r})")

    def virgule_decimale(texte):
        return re.search(r"\d,\d", str(texte)) is not None

    langue_avant = os.environ.get("EEG_LANGUE")
    # L'écran en français : tout ce qui part vers l'application doit rester en anglais.
    choisir_langue("fr")
    debut = time.perf_counter()
    try:
        # 1. Lire une commande : les quatre commandes permises, prêtes pour `submit`.
        c = lire_commande('{"cmd": "set_params", "mode": "ssvep", '
                          '"params": {"refresh_hz": 30}, "ref": "43"}')
        chk(c.refus is None and (c.ref, c.cmd, c.mode) == ("43", "set_params", "ssvep")
            and c.kwargs == {"id": "ssvep", "params": {"refresh_hz": 30}},
            f"set_params : « mode » devient « id », les réglages passent tels quels ({c})")
        c = lire_commande('{"cmd": "start_mode", "mode": "ssvep", "params": {"alpha_hz": 10}, '
                          '"ref": 44}')
        chk(c.refus is None and c.ref == 44
            and c.kwargs == {"id": "ssvep", "params": {"ssvep": {"alpha_hz": 10}}},
            f"start_mode : les réglages sont rangés sous le nom du mode, comme `submit` les "
            f"attend ; un « ref » numérique est gardé ({c})")
        c = lire_commande('{"cmd": "stop_mode", "mode": "ssvep"}')
        chk(c.refus is None and c.ref is None and c.kwargs == {"id": "ssvep"},
            f"stop_mode : seulement le mode ; sans « ref », il vaut None ({c})")
        c = lire_commande('{"cmd": "propose_params", "mode": "ssvep", "key": "alpha_hz", '
                          '"params": {"refresh_hz": 30}, "ref": "42"}')
        chk(c.refus is None
            and c.kwargs == {"id": "ssvep", "key": "alpha_hz", "params": {"refresh_hz": 30}},
            f"propose_params : le mode, le réglage qui propose et les réglages en cours ({c})")
        c = lire_commande('{"cmd": "start_mode", "mode": "ssvep", "ids": ["neuro"], "reseau": 1, '
                          '"id": "raw", "key": "k", "params": {"alpha_hz": 10}, "ref": "w0"}')
        chk(c.refus is None and c.kwargs == {"id": "ssvep", "params": {"ssvep": {"alpha_hz": 10}}},
            f"les champs en trop (« ids », « reseau », « id », « key ») ne passent jamais à "
            f"`submit` ({c.kwargs})")

        # 2. Lire une commande : ce qui est refusé, sans jamais lever.
        for illisible in ("pas du json", "[1]", None):
            c = lire_commande(illisible)
            chk(isinstance(c.refus, Texte) and c.refus.cle == "moteur.reseau.json_illisible"
                and (c.ref, c.cmd, c.mode) == (None, None, None),
                f"{illisible!r} n'est pas un objet JSON : refusé, sans « ref » ({c.refus!r})")
        c = lire_commande('{"cmd": "start_calibration", "mode": "mi", "ref": "x"}')
        en = pour_le_contrat(c.refus)
        chk(c.refus is not None and c.refus.cle == "moteur.reseau.commande_non_permise"
            and all(n in en for n in COMMANDES_RESEAU) and c.ref == "x",
            f"une commande interne (start_calibration) est refusée, et la raison liste les "
            f"quatre commandes permises ({en!r})")
        c = lire_commande('{"mode": "ssvep", "ref": "y"}')
        en = pour_le_contrat(c.refus) if c.refus is not None else ""
        chk(c.refus is not None and c.refus.cle == "moteur.reseau.commande_absente"
            and "missing" in en and all(n in en for n in COMMANDES_RESEAU) and c.ref == "y",
            f"une commande SANS « cmd » est refusée pour cette raison-là, avec la liste des "
            f"commandes permises ({en!r})")
        for texte, champ in (('{"cmd": "set_params", "mode": 3}', "mode"),
                             ('{"cmd": "set_params", "mode": "ssvep", "params": [1]}', "params"),
                             ('{"cmd": "propose_params", "mode": "ssvep", "key": 5}', "key"),
                             ('{"cmd": "stop_mode", "mode": "ssvep", "ref": {}}', "ref"),
                             ('{"cmd": "stop_mode", "mode": "ssvep", "ref": true}', "ref")):
            c = lire_commande(texte)
            chk(c.refus is not None and c.refus.cle == "moteur.reseau.champ_invalide"
                and c.refus.valeurs.get("champ") == champ
                and (c.ref is None if champ == "ref" else True),
                f"{texte} : refusé, la raison nomme le champ « {champ} » ({c.refus!r})")
        grand = '{"cmd": "stop_mode", "mode": "ssvep", "ref": 1' + "0" * 400 + "}"
        try:
            c, leve = lire_commande(grand), None
        except Exception as e:  # noqa: BLE001 - c'est justement ce qui est vérifié
            c, leve = None, e
        chk(c is not None and c.refus is None and c.ref == 10 ** 400,
            f"un « ref » entier, même de 401 chiffres, est gardé sans lever (un entier est "
            f"toujours fini) ({leve!r})")
        try:
            c, leve = lire_commande('{"cmd": "stop_mode", "mode": "ssvep", "ref": 1e400}'), None
        except Exception as e:  # noqa: BLE001
            c, leve = None, e
        chk(c is not None and c.refus is not None and c.refus.valeurs.get("champ") == "ref"
            and c.ref is None,
            f"un « ref » réel infini (1e400) est refusé ({leve!r})")
        # Des OCTETS : du bon UTF-8 se lit comme du texte ; un autre encodage est refusé pour
        # cette raison-là, et l'application retrouve son « ref » quand il est intact.
        ligne = ('{"cmd": "set_params", "mode": "ssvep", "params": {"target_names": ["élève"]}, '
                 '"ref": "u0"}')
        c = lire_commande(ligne.encode("utf-8"))
        chk(c.refus is None and c.ref == "u0"
            and c.kwargs == {"id": "ssvep", "params": {"target_names": ["élève"]}},
            f"des octets UTF-8 se lisent comme le texte ({c})")
        c = lire_commande(ligne.replace("u0", "u1").encode("cp1252"))
        en = pour_le_contrat(c.refus) if c.refus is not None else ""
        chk(getattr(c.refus, "cle", None) == "moteur.reseau.pas_utf8"
            and (c.ref, c.cmd, c.mode) == ("u1", "set_params", "ssvep") and "UTF-8" in en
            and en != pour_le_contrat(tr("moteur.reseau.json_illisible")),
            f"des octets cp1252 (« élève ») : refusés parce que ce n'est pas de l'UTF-8, et le "
            f"« ref » intact est rendu ({c.ref!r}, {en!r})")
        c = lire_commande('{"cmd": "stop_mode", "mode": "ssvep", "ref": "jeu-é"}'.encode("cp1252"))
        chk(getattr(c.refus, "cle", None) == "moteur.reseau.pas_utf8"
            and (c.ref, c.cmd, c.mode) == (None, "stop_mode", "ssvep"),
            f"...un « ref » abîmé par le décodage part en null : ce n'est plus celui de "
            f"l'application ({c.ref!r})")

        # 3. La réponse : les mots du contrat, en anglais.
        c = lire_commande('{"cmd": "set_params", "mode": "ssvep", "params": {}, "ref": "43"}')
        r = reponse(c, {"accepted": True, "command": "set_params", "id": "ssvep",
                        "params": {"refresh_hz": 30.0}, "differe": True, "warning": None})
        chk(r == {"ref": "43", "cmd": "set_params", "mode": "ssvep", "accepted": True,
                  "params": {"refresh_hz": 30.0}, "deferred": True, "warning": None},
            f"set_params : « differe » devient « deferred », les réglages validés repartent ({r})")
        c = lire_commande('{"cmd": "start_mode", "mode": "ssvep", "ref": "44"}')
        r = reponse(c, {"accepted": True, "command": "start_mode", "ids": ["ssvep"],
                        "deja": ["ssvep"], "warning": None})
        r2 = reponse(c, {"accepted": True, "command": "start_mode", "ids": ["ssvep"],
                         "warning": None})
        chk(r.get("already_running") is True and r2.get("already_running") is False,
            f"start_mode : « already_running » dit si le mode tournait déjà ({r}, {r2})")
        c = lire_commande('{"cmd": "stop_mode", "mode": "ssvep", "ref": "45"}')
        r = reponse(c, {"accepted": True, "command": "stop_mode", "id": "ssvep", "deja": True})
        r2 = reponse(c, {"accepted": True, "command": "stop_mode", "id": "ssvep"})
        chk(r.get("already_stopped") is True and r2.get("already_stopped") is False,
            f"stop_mode : « already_stopped » dit si le mode était déjà arrêté ({r}, {r2})")
        c = lire_commande('{"cmd": "propose_params", "mode": "ssvep", "ref": "46"}')
        note = tr("moteur.contrat.au_dessus_maximum", reglage=tr("moteur.bande.bas"),
                  valeur=nombre(9.6), borne=nombre(8.5))
        r = reponse(c, {"accepted": True, "command": "propose_params", "id": "ssvep",
                        "key": "freqs", "value": [7.5, 12.0], "warning": note})
        chk(r.get("key") == "freqs" and r.get("value") == [7.5, 12.0]
            and type(r.get("warning")) is str and not virgule_decimale(r["warning"])
            and "above the maximum" in r["warning"],
            f"propose_params : « key », « value », et l'avertissement en anglais ({r})")
        raison = tr("moteur.contrat.au_dessus_maximum", reglage=tr("moteur.bande.bas"),
                    valeur=nombre(240.5), borne=nombre(120.25))
        r = reponse(c, {"accepted": False, "reason": raison})
        chk(virgule_decimale(raison) and "dépasse" in raison,
            f"(le refus est écrit en français à l'écran : {raison!r})")
        chk(r.get("accepted") is False and type(r.get("reason")) is str
            and "above the maximum" in r["reason"] and "240.5" in r["reason"]
            and not virgule_decimale(r["reason"]),
            f"un refus part en ANGLAIS, nombres avec un point, écran en français ({r})")
        chk(json.loads(json.dumps(r)) == r, "la réponse s'écrit en JSON telle quelle")
        e = echec("44", "start_mode", "ssvep", tr("moteur.refus.aucun_mode_demande"))
        chk(e == {"ref": "44", "cmd": "start_mode", "mode": "ssvep", "event": "failed",
                  "reason": "No mode requested."} and type(e["reason"]) is str,
            f"un échec après acceptation : « event »: « failed », la raison en anglais ({e})")
        fins = [deconnexion("mon-jeu", ("ssvep",), cause) for cause in CAUSES_DECONNEXION]
        try:
            deconnexion("mon-jeu", (), "engine_stoped")
            faute = None
        except ValueError as erreur:
            faute = erreur
        # « ref » est là, à null : chaque message du flux de réponses en porte un, et un client
        # strict (`reply["ref"]` en Python, `msg.ref` après `jsondecode` en MATLAB) lèverait sur
        # le seul qui n'en aurait pas.
        chk(all(set(f) == {"ref", "event", "cause", "app", "stopped", "reason"}
                and f["ref"] is None and json.loads(json.dumps(f))["ref"] is None
                and f["event"] == "disconnected" and f["stopped"] == ["ssvep"]
                and type(f["reason"]) is str and f["reason"].isascii() for f in fins)
            and fins[0]["reason"] != fins[1]["reason"] and faute is not None,
            f"« disconnected » : six champs, « ref » à null, une raison en anglais par cause ; "
            f"une cause inconnue est refusée ({fins}, {faute!r})")
        c = lire_commande('{"cmd": "propose_params", "mode": "ssvep", "ref": "47"}')
        r = reponse(c, {"accepted": True, "command": "propose_params", "id": "ssvep",
                        "key": "freqs", "value": [7.5, 12.0], "warning": ""})
        c = lire_commande('{"cmd": "set_params", "mode": "ssvep", "ref": "48"}')
        r2 = reponse(c, {"accepted": True, "command": "set_params", "id": "ssvep", "params": {},
                         "differe": False, "warning": ""})
        chk("warning" in r and r["warning"] is None and "warning" in r2 and r2["warning"] is None,
            f"un avertissement vide part en null, comme l'absence d'avertissement ({r}, {r2})")
        # Toute réponse ACCEPTÉE porte « warning », null sans réserve — même quand l'accusé du
        # moteur n'en a pas (celui de stop_mode n'en a jamais).
        sans = [reponse(lire_commande(f'{{"cmd": "{cmd}", "mode": "ssvep"}}'), ack)
                for cmd, ack in (
                    ("stop_mode", {"accepted": True, "command": "stop_mode", "id": "ssvep"}),
                    ("start_mode", {"accepted": True, "command": "start_mode", "ids": ["ssvep"]}),
                    ("set_params", {"accepted": True, "command": "set_params", "id": "ssvep",
                                    "params": {}, "differe": True}),
                    ("propose_params", {"accepted": True, "command": "propose_params",
                                        "id": "ssvep", "key": "freqs", "value": [7.5]}))]
        chk(all("warning" in r and r["warning"] is None for r in sans),
            f"toute réponse acceptée porte « warning »: null, même sans avertissement dans "
            f"l'accusé ({[r.get('warning', 'ABSENT') for r in sans]})")
        # Un avertissement fait de MORCEAUX (`joint`, comme le vrai moteur les écrit) part en
        # anglais, d'un seul texte.
        reserve = joint(" ", [tr("moteur.contrat.flux_pas_vu", reglage="stream_in",
                                 nom="MonJeu"),
                              tr("moteur.reglage.stream_in_au_redemarrage", mode="P300")])
        c = lire_commande('{"cmd": "set_params", "mode": "p300", "ref": "50"}')
        r = reponse(c, {"accepted": True, "command": "set_params", "id": "p300", "params": {},
                        "differe": False, "warning": reserve})
        chk(type(r.get("warning")) is str and r["warning"] == pour_le_contrat(reserve)
            and r["warning"] != str(reserve) and "MonJeu" in r["warning"]
            and "not visible" in r["warning"],
            f"un avertissement en plusieurs morceaux part en anglais, d'un seul texte "
            f"({r.get('warning')!r})")
        # Le modèle part en NOM DE FICHIER, jamais en chemin du poste : le flux de réponses se
        # lit de tout le réseau. Le réglage du moteur, lui, garde son chemin.
        chemin = os.path.join(os.path.expanduser("~"), "poste", "data",
                              "mi_model_20261021_101500.joblib")
        regl = {"model": chemin, "prob_min": 0.6}
        c = lire_commande('{"cmd": "start_mode", "mode": "mi", "ref": "49"}')
        r = reponse(c, {"accepted": True, "command": "start_mode", "ids": ["mi"],
                        "params": regl, "warning": None})
        r2 = reponse(lire_commande('{"cmd": "set_params", "mode": "mi", "ref": "51"}'),
                     {"accepted": True, "command": "set_params", "id": "mi", "params": regl,
                      "differe": True, "warning": None})
        chk(r.get("params", {}).get("model") == "mi_model_20261021_101500.joblib"
            and r2.get("params", {}).get("model") == "mi_model_20261021_101500.joblib"
            and r["params"].get("prob_min") == 0.6 and regl["model"] == chemin,
            f"« model » part en nom de fichier (start_mode, set_params), le réglage du moteur "
            f"garde son chemin ({r.get('params')}, {regl['model']!r})")
        import numpy as np
        chk(_en_json(np.array([15.0, 20.0])) == [15.0, 20.0] and _en_json(np.float64(1.5)) == 1.5
            and json.dumps({"freqs": np.array([15.0, 20.0])}, default=_en_json)
            == '{"freqs": [15.0, 20.0]}',
            f"un tableau numpy part en liste JSON, pas en texte "
            f"({json.dumps({'freqs': np.array([15.0, 20.0])}, default=_en_json)})")

        # 4. Seule une application de CETTE machine pilote le moteur.
        garde = [h for h in ("POSTE-1", "autre", "poste-1", "", None) if _meme_hote(h, "poste-1")]
        chk(garde == ["POSTE-1", "poste-1"],
            f"seuls les flux de CETTE machine sont gardés, sans tenir compte de la casse "
            f"({garde})")
        ici = socket.gethostname()
        chk(_meme_hote(ici.upper(), ici) and _meme_hote(ici.lower(), ici)
            and not _meme_hote("autre", ici),
            "le nom de cette machine est reconnu quelle que soit sa casse")

        # 4 ter. Le tampon d'une application : ~100 commandes, que son flux déclare un débit ou non.
        class _Debit:
            def __init__(self, debit):
                self.debit = debit

            def nominal_srate(self):
                return self.debit

        tampons = [_tampon(_Debit(d)) for d in (0.0, 1.0, 0.5, 500.0)]
        chk(tampons == [TAMPON_INLET, 100, 200, 1],
            f"le tampon garde ~{COMMANDES_EN_ATTENTE} commandes : 1 (×100) pour un flux irrégulier, "
            f"des SECONDES pour un flux qui déclare un débit — jamais 0 sous 1 Hz ({tampons})")

        # 4 bis. Le seau de jetons, à des instants choisis.
        s = Seau(debit=20, maintenant=0.0)
        rafale = [s.prendre(0.0) for _ in range(25)]
        apres = [s.prendre(0.5) for _ in range(12)]
        plein = sum(s.prendre(100.0) for _ in range(40))
        chk(rafale == [True] * 20 + [False] * 5 and apres == [True] * 10 + [False] * 2
            and plein == 20,
            f"le seau de jetons : une rafale de 20 passe, la 21e est refusée ; 0,5 s rend 10 "
            f"jetons ; jamais plus de 20 en réserve ({sum(rafale)}, {sum(apres)}, {plein})")

        # 5. En LSL réel, contre un faux moteur. Le nom du flux de commandes est PROPRE au test :
        # un moteur réel oublié sur ce poste écoute le nom par défaut et n'obéit donc pas au test.
        pid = os.getpid()
        faux = FauxMoteur(f"autotest-pilotage-{pid}")
        # Comme le vrai moteur, une réserve faite de morceaux (`joint`).
        reserve = joint(" ", [tr("moteur.contrat.flux_pas_vu", reglage="stream_in",
                                 nom=f"Absent_{pid}")])
        faux.accuses = {
            "set_params": {"accepted": True, "command": "set_params", "id": "ssvep",
                           "params": {"refresh_hz": 30.0}, "differe": True, "warning": reserve},
            "start_mode": {"accepted": True, "command": "start_mode", "ids": ["ssvep"],
                           "deja": ["ssvep"], "warning": None},
            "stop_mode": {"accepted": False, "reason": raison},
        }
        nom = f"{NOM_FLUX_COMMANDES}_autotest_{pid}"

        def nouvelle_app():
            """L'outlet de commandes d'une application, toujours sous le même nom et la même
            identité : c'est ce que fait une application qu'on relance."""
            return StreamOutlet(StreamInfo(nom, "Markers", 1, IRREGULAR_RATE, "string",
                                           f"autotest-app-{pid}"))

        pil = Pilotage(faux, nom_flux=nom)
        app = entree = None
        try:
            chk(pil.hote == socket.gethostname(),
                f"sans hôte donné, c'est le nom de cette machine qui compte ({pil.hote!r})")
            chk(pil.demarrer() is True and pil.vivant, "le fil d'écoute démarre")
            app = nouvelle_app()
            info_rep = _trouver_reponses(faux.instance, 5.0)
            chk(info_rep is not None, "le flux de réponses du faux moteur est trouvé")
            if info_rep is None:
                raise RuntimeError("sans flux de réponses, la suite de cette section n'a pas de sens")
            entree = StreamInlet(info_rep, recover=False)
            # Piège 2 : une réponse publiée avant que l'application écoute est perdue. On ouvre
            # donc l'inlet de réponses AVANT d'envoyer la première commande.
            entree.open_stream(timeout=5.0)
            # Piège 1 : une commande envoyée avant que le moteur ait découvert l'outlet est
            # perdue. On attend qu'il écoute.
            t0 = time.perf_counter()
            chk(app.wait_for_consumers(5.0),
                f"le moteur se branche sur l'application ({time.perf_counter() - t0:.2f} s)")
            for ligne in ('{"cmd": "set_params", "mode": "ssvep", "params": {}, "ref": "c1"}',
                          '{"cmd": "start_mode", "mode": "ssvep", "ref": "c2"}',
                          '{"cmd": "stop_mode", "mode": "ssvep", "ref": "c3"}'):
                app.push_sample([ligne])
            recues = _recevoir(entree, 3, 5.0)
            par_ref = {r.get("ref"): r for r in recues}
            chk([r.get("ref") for r in recues] == ["c1", "c2", "c3"],
                f"trois commandes, trois réponses, dans l'ordre et au bon « ref » "
                f"({[r.get('ref') for r in recues]})")
            chk(par_ref.get("c1", {}).get("deferred") is True
                and par_ref.get("c2", {}).get("already_running") is True,
                f"les réponses portent les mots du contrat ({recues[:2]})")
            avertissement = par_ref.get("c1", {}).get("warning")
            chk(type(avertissement) is str and avertissement == pour_le_contrat(reserve)
                and avertissement != str(reserve) and f"Absent_{pid}" in avertissement,
                f"la réserve du moteur (des morceaux joints, comme le vrai) arrive en anglais "
                f"({avertissement!r})")
            refus = par_ref.get("c3", {})
            chk(refus.get("accepted") is False and "above the maximum" in refus.get("reason", "")
                and not virgule_decimale(refus.get("reason", "")),
                f"un refus du moteur arrive en anglais ({refus})")
            chk([(a[0], a[1]) for a in faux.appels]
                == [("set_params", ("c1", "set_params", "ssvep")),
                    ("start_mode", ("c2", "start_mode", "ssvep")),
                    ("stop_mode", ("c3", "stop_mode", "ssvep"))],
                f"chaque commande passe par `submit`, avec son jeton (ref, cmd, mode) "
                f"({[(a[0], a[1]) for a in faux.appels]})")

            # Un échec APRÈS l'acceptation : le moteur rappelle avec le nom de ce que sa boucle
            # exécutait (ici, exprès, un autre que celui de l'application) ; la réponse prend la
            # commande du jeton, celle que l'application a envoyée.
            pil.signaler_echec(("c2", "start_mode", "ssvep"), "set_params",
                               tr("moteur.refus.aucun_mode_demande"))
            rec = _recevoir(entree, 1, 5.0)
            chk(rec == [{"ref": "c2", "cmd": "start_mode", "mode": "ssvep", "event": "failed",
                         "reason": "No mode requested."}],
                f"l'échec arrive au bon « ref », avec la commande de l'application ({rec})")
            j = pil.journal()
            cles = {"t", "cmd", "mode", "accepted", "raison", "event", "deja", "differe",
                    "warning"}
            chk(len(j) == 4 and all(set(e) == cles for e in j),
                f"le journal garde chaque commande et l'échec, réserve comprise ({len(j)} "
                f"entrées, {sorted(set(j[0])) if j else '-'})")
            if len(j) == 4:
                chk(j[0]["differe"] is True and j[1]["deja"] is True and j[0]["raison"] is None,
                    f"le journal dit « retenu » et « déjà en route » ({j[:2]})")
                chk(isinstance(j[0].get("warning"), Joint)
                    and str(j[0]["warning"]) == str(reserve)
                    and j[1].get("warning") is None and j[2].get("warning") is None,
                    f"le journal garde la réserve dans la langue de l'ÉCRAN, prête à être "
                    f"retraduite ; None sans réserve ({j[0].get('warning')!r})")
                chk(j[2]["accepted"] is False and isinstance(j[2]["raison"], Texte)
                    and "dépasse" in j[2]["raison"],
                    f"la raison du journal est dans la langue de l'ÉCRAN, et se retraduit "
                    f"({j[2]['raison']!r})")
                chk(j[3]["event"] == "failed" and j[3]["cmd"] == "start_mode"
                    and isinstance(j[3]["raison"], Texte)
                    and j[3]["raison"] == "Aucun mode demandé.",
                    f"l'échec est au journal, en français, et se retraduit ({j[3]})")

            # Des champs de mauvais type : un refus motivé, et le fil répond à la suivante.
            for ligne in ('{"cmd": "set_params", "mode": 3, "ref": "m1"}',
                          'pas du json',
                          '{"cmd": "stop_mode", "mode": "ssvep", "ref": {}}',
                          '{"cmd": "set_params", "mode": "ssvep", "ref": "boum"}',
                          '{"cmd": "set_params", "mode": "ssvep", "ref": "m3"}'):
                app.push_sample([ligne])
            rec = _recevoir(entree, 5, 5.0)
            chk([(r.get("ref"), r.get("cmd")) for r in rec]
                == [("m1", "set_params"), (None, None), (None, "stop_mode"),
                    ("boum", "set_params"), ("m3", "set_params")],
                f"une réponse par commande, même illisible "
                f"({[(r.get('ref'), r.get('cmd')) for r in rec]})")
            if len(rec) == 5:
                chk(rec[0]["accepted"] is False and rec[0].get("reason")
                    == pour_le_contrat(tr("moteur.reseau.champ_invalide", champ="mode")),
                    f"« mode »: 3 est refusé en anglais, en nommant le champ ({rec[0]})")
                chk(rec[1]["accepted"] is False and "JSON" in rec[1].get("reason", ""),
                    f"du texte qui n'est pas du JSON est refusé ({rec[1]})")
                chk(rec[3]["accepted"] is False and "Internal error" in rec[3].get("reason", ""),
                    f"un `submit` qui lève donne un refus, pas un fil mort ({rec[3]})")
                chk(rec[4]["accepted"] is True, f"la commande suivante est servie ({rec[4]})")
            chk(pil.vivant, "le fil d'écoute est toujours vivant")

            # Une commande qui n'est pas du texte UTF-8 (une bibliothèque LSL d'un autre langage,
            # chaînes dans l'encodage de Windows) : un refus qui le dit, au bon « ref » s'il est
            # intact — et la commande SUIVANTE est servie aussitôt. Lâcher l'inlet sur cette
            # erreur perdrait les suivantes, sans réponse.
            _pousser_octets(app, ('{"cmd": "set_params", "mode": "ssvep", "params": '
                                  '{"target_names": ["élève"]}, "ref": "u1"}').encode("cp1252"))
            _pousser_octets(app, '{"cmd": "set_params", "mode": "ssvep", "ref": "é"}'
                            .encode("cp1252"))
            app.push_sample(['{"cmd": "set_params", "mode": "ssvep", "ref": "u2"}'])
            rec = _recevoir(entree, 3, 1.0)
            pas_utf8 = pour_le_contrat(tr("moteur.reseau.pas_utf8"))
            chk([(r.get("ref"), r.get("accepted")) for r in rec]
                == [("u1", False), (None, False), ("u2", True)]
                and all(r.get("reason") == pas_utf8 for r in rec[:2]),
                f"deux commandes en cp1252 : refusées en anglais parce que ce n'est pas de "
                f"l'UTF-8, au bon « ref » quand il est intact ; la suivante est servie en moins "
                f"d'1 s ({rec})")

            # Le JSON publié est en ASCII seul (« é » devient « é ») : toute bibliothèque
            # LSL le lit, quel que soit l'encodage qu'elle suppose. Et une « cmd » trop longue :
            # recopiée telle quelle dans la réponse, coupée dans la raison et au journal.
            app.push_sample(['{"cmd": "stop_mode", "mode": "ssvep", "ref": "élève-1"}'])
            bruts = _recevoir_brut(entree, 1, 5.0)
            chk(len(bruts) == 1 and bruts[0].isascii() and "\\u00e9" in bruts[0]
                and json.loads(bruts[0]).get("ref") == "élève-1",
                f"la réponse est du JSON en ASCII seul, qui rend le « ref » « élève-1 » intact "
                f"({bruts})")
            longue = "x" * 200
            app.push_sample([json.dumps({"cmd": longue, "mode": "m" * 200, "ref": "long"})])
            rec = _recevoir(entree, 1, 5.0)
            raison_longue = rec[0].get("reason", "") if rec else ""
            chk(len(rec) == 1 and rec[0].get("cmd") == longue and rec[0].get("mode") == "m" * 200
                and json.dumps(longue)[:CMD_AFFICHEE_MAX] + "…" in raison_longue
                and longue not in raison_longue,
                f"une « cmd » de 200 caractères : recopiée telle quelle dans la réponse, coupée à "
                f"{CMD_AFFICHEE_MAX} dans la raison ({raison_longue[:80]!r}…)")
            e = pil.journal()[-1]
            chk(e["cmd"] == "x" * CMD_AFFICHEE_MAX + "…" and e["mode"] == "m" * CMD_AFFICHEE_MAX + "…",
                f"...et coupée au journal, que la console affiche ({e['cmd']!r}, {e['mode']!r})")

            # `propose_params` sans « key » : le seul réglage qui propose est complété.
            avant = pil.journal()
            n = len(faux.appels)
            r = pil.traiter('{"cmd": "propose_params", "mode": "ssvep", "ref": "p1"}')
            chk(len(faux.appels) == n + 1 and faux.appels[-1][2].get("key") == "alpha_hz",
                f"SSVEP n'a qu'un réglage qui propose : « key » est complété "
                f"({faux.appels[-1][2] if len(faux.appels) > n else '-'})")
            pil.traiter('{"cmd": "propose_params", "mode": "mi", "ref": "p2"}')
            chk("key" not in faux.appels[-1][2],
                f"un mode sans réglage qui propose : la commande part telle quelle, et c'est "
                f"`submit` qui répond ({faux.appels[-1][2]})")
            pil.traiter('{"cmd": "propose_params", "mode": "ssvep", "key": "freqs", "ref": "p3"}')
            chk(faux.appels[-1][2].get("key") == "freqs",
                f"une « key » donnée par l'application n'est jamais remplacée "
                f"({faux.appels[-1][2]})")
            chk(r.get("ref") == "p1" and "accepted" in r and _recevoir(entree, 1, 0.5) == [],
                "`traiter` rend la réponse sans la publier : c'est le fil qui publie")
            j = pil.journal()
            chk(len(j) == len(avant) + 3 and j[-1].get("cmd") == "propose_params",
                f"`traiter` inscrit chaque commande au journal ({len(j)} entrées)")
            for k in range(JOURNAL_N + 5):
                pil._inscrire("set_params", f"plein-{k}", True, None, None, False, False)
            j = pil.journal()
            ancienne = {"t": None, "cmd": "set_params", "mode": "plein-5"}
            chk(len(j) == JOURNAL_N and j[0].get("mode") == "plein-5"
                and j[-1].get("mode") == f"plein-{JOURNAL_N + 4}",
                f"le journal garde les {JOURNAL_N} dernières (10 s à {DEBIT_MAX} commandes/s), et "
                f"la plus ancienne gardée est la "
                f"bonne ({len(j)} ; la plus ancienne : {j[0].get('mode') if j else '-'}, "
                f"attendue : {ancienne.get('mode')})")

            # L'ordre : l'acceptation, PUIS l'échec — même quand la boucle du moteur signale
            # l'échec avant que `submit` ait rendu son accusé.
            faux.rappel = pil.signaler_echec
            app.push_sample(['{"cmd": "start_mode", "mode": "ssvep", "ref": "vite"}'])
            rec = _recevoir(entree, 2, 5.0)
            chk([(r.get("ref"), r.get("event")) for r in rec]
                == [("vite", None), ("vite", "failed")],
                f"le réseau reçoit l'accusé, puis l'échec ({rec})")
            dernieres = [(e["cmd"], e["event"], e["accepted"]) for e in pil.journal()[-2:]]
            chk(dernieres == [("start_mode", None, True), ("start_mode", "failed", False)],
                f"le journal suit le même ordre ({dernieres})")
            # Même appelé depuis un AUTRE fil que celui d'écoute (qui publie les échecs pendant ce
            # temps), `traiter` inscrit son accusé avant l'échec. Dans un fil à part, borné : un
            # interblocage rend un ÉCHEC, il ne fige pas l'autotest.
            fil_traiter = threading.Thread(
                target=pil.traiter, args=('{"cmd": "start_mode", "mode": "ssvep", "ref": "vite"}',),
                daemon=True, name="autotest-traiter")
            fil_traiter.start()
            fil_traiter.join(timeout=5.0)
            chk(not fil_traiter.is_alive(),
                "`traiter`, appelé pendant que la boucle du moteur signale un échec, rend la main "
                "(aucun interblocage)")
            if fil_traiter.is_alive():
                raise RuntimeError("`traiter` est bloqué : la suite de cette section le serait aussi")
            rec = _recevoir(entree, 1, 2.0)
            dernieres = [(e["cmd"], e["event"], e["accepted"]) for e in pil.journal()[-2:]]
            chk([r.get("event") for r in rec] == ["failed"]
                and dernieres == [("start_mode", None, True), ("start_mode", "failed", False)],
                f"...appelé d'un autre fil, le journal garde l'ordre ({dernieres})")
            faux.rappel = None

            # Seuls les champs du contrat atteignent `submit`.
            for ligne, attendu in (
                    ('{"cmd": "start_mode", "mode": "ssvep", "ref": "w1", "ids": ["neuro"], '
                     '"reseau": 1, "id": "raw", "key": "k", "params": {"alpha_hz": 10}}',
                     {"id": "ssvep", "params": {"ssvep": {"alpha_hz": 10}}}),
                    ('{"cmd": "stop_mode", "mode": "ssvep", "ref": "w2", "params": {"x": 1}, '
                     '"key": "k"}', {"id": "ssvep"}),
                    ('{"cmd": "set_params", "mode": "ssvep", "ref": "w3", "key": "k", '
                     '"ids": ["mi"]}', {"id": "ssvep"})):
                pil.traiter(ligne)
                chk(faux.appels[-1][2] == attendu,
                    f"{faux.appels[-1][0]} : `submit` reçoit exactement {attendu} "
                    f"({faux.appels[-1][2]})")

            # Un défaut du moteur (un accusé qui n'en est pas un) : un refus au bon « ref », et le
            # journal le montre.
            app.push_sample(['{"cmd": "set_params", "mode": "ssvep", "ref": "nondict"}'])
            rec = _recevoir(entree, 1, 5.0)
            chk(len(rec) == 1 and rec[0].get("ref") == "nondict" and rec[0].get("accepted") is False
                and rec[0].get("cmd") == "set_params"
                and "Internal error" in rec[0].get("reason", ""),
                f"un accusé illisible donne un refus en anglais, au bon « ref » ({rec})")
            e = pil.journal()[-1]
            chk(e["cmd"] == "set_params" and e["accepted"] is False
                and isinstance(e["raison"], Texte) and "Erreur interne" in e["raison"],
                f"...et le journal le montre, en français ({e})")

            # L'application redémarre : son outlet disparaît, un nouveau revient sous le même nom.
            app = None
            app = nouvelle_app()
            t0 = time.perf_counter()
            retrouve = app.wait_for_consumers(5.0)
            chk(retrouve, f"l'application relancée sous le même nom est retrouvée "
                          f"({time.perf_counter() - t0:.2f} s)")
            app.push_sample(['{"cmd": "stop_mode", "mode": "ssvep", "ref": "apres"}'])
            rec = _recevoir(entree, 1, 5.0)
            chk([r.get("ref") for r in rec] == ["apres"],
                f"...et sa commande suivante a sa réponse, sans redémarrer le moteur ({rec})")
            chk(pil.connexions == 2 and pil.perdus == 1,
                f"une connexion perdue, une nouvelle ouverte ({pil.connexions} connexions, "
                f"{pil.perdus} perdue)")

            # Le moteur s'arrête : le fil finit en moins de 2 s, le flux de réponses disparaît.
            t0 = time.perf_counter()
            arrete = pil.arreter()
            duree = time.perf_counter() - t0
            chk(arrete and not pil.vivant and duree < 2.0,
                f"`arreter()` : le fil d'écoute est mort ({duree:.2f} s)")
            # Un échec signalé JUSTE AVANT l'arrêt part quand même : c'est le dernier geste du fil
            # d'écoute. Rejoué ici sans fil, l'arrêt déjà demandé : c'est donc bien ce geste-là,
            # et pas un tour ordinaire, qui publie.
            pil.signaler_echec(("f1", "start_mode", "ssvep"), "start_mode",
                               tr("moteur.refus.aucun_mode_demande"))
            pil._boucle()
            rec = _recevoir(entree, 1, 2.0)
            chk([(r.get("ref"), r.get("event")) for r in rec] == [("f1", "failed")],
                f"un échec signalé juste avant l'arrêt est publié quand même ({rec})")
            pil.fermer()
            entree.close_stream()
            entree = None
            restants = [i for i in resolve_byprop("name", NOM_FLUX_REPONSES, minimum=32,
                                                  timeout=1.0)
                        if i.source_id() == _source_id(SUFFIXE_REPONSES, faux.instance)]
            chk(restants == [], f"`fermer()` retire le flux de réponses ({len(restants)} restant)")
        except Exception as e:  # noqa: BLE001 - un ÉCHEC dit, pas un autotest qui plante
            interrompu("pilotage par LSL", e)
        finally:
            pil.arreter()
            pil.fermer()
            app = entree = None

        # 5 bis. `demarrer()` : jamais deux fils d'écoute, et plus rien après `fermer()`.
        nom_d = f"{NOM_FLUX_COMMANDES}_autotest_demarrer_{pid}"
        dem = Pilotage(FauxMoteur(f"autotest-pilotage-demarrer-{pid}"), nom_flux=nom_d)

        def fils_de(nom_flux):
            return [t for t in threading.enumerate()
                    if t.name == f"pilotage-{nom_flux}" and t.is_alive()]
        try:
            premier, second = dem.demarrer(), dem.demarrer()
            chk(premier and second and len(fils_de(nom_d)) == 1,
                f"`demarrer()` deux fois : un seul fil d'écoute ({len(fils_de(nom_d))})")
            ancien = dem._fil
            dem._arret.set()            # « on vient de l'arrêter » : le fil n'est pas encore sorti
            relance = dem.demarrer()
            chk(relance and dem._fil is not ancien and not ancien.is_alive()
                and len(fils_de(nom_d)) == 1,
                f"`demarrer()` juste après un arrêt attend que l'ancien fil soit sorti : jamais "
                f"deux qui lisent les mêmes commandes ({len(fils_de(nom_d))})")
            dem.arreter()
            dem.fermer()
            chk(dem.demarrer() is False and fils_de(nom_d) == [],
                f"`demarrer()` après `fermer()` : refusé, aucun fil ({len(fils_de(nom_d))})")
        except Exception as e:  # noqa: BLE001
            interrompu("demarrer", e)
        finally:
            dem.arreter()
            dem.fermer()

        # 6. Une application d'une AUTRE machine ne pilote pas ce moteur. On fait passer ce poste
        # pour un autre : le flux de l'application est alors « étranger ».
        voisin_faux = FauxMoteur(f"autotest-pilotage-voisin-{pid}")
        nom2 = f"{NOM_FLUX_COMMANDES}_autotest_voisin_{pid}"
        voisin = Pilotage(voisin_faux, nom_flux=nom2, hote="poste-du-voisin")
        app2 = None
        capture = io.StringIO()
        try:
            with redirect_stdout(capture):
                voisin.demarrer()
                app2 = StreamOutlet(StreamInfo(nom2, "Markers", 1, IRREGULAR_RATE, "string",
                                               f"autotest-app-voisin-{pid}"))
                branche = app2.wait_for_consumers(1.5)
                app2.push_sample(['{"cmd": "start_mode", "mode": "ssvep", "ref": "v1"}'])
                # Le terminal le dit au premier passage de la découverte : on attend le message
                # (5 s au plus), plutôt que de parier sur un délai.
                echeance = time.perf_counter() + 5.0
                while ("AUTRE machine" not in capture.getvalue()
                       and time.perf_counter() < echeance):
                    time.sleep(0.05)
                # Le temps que la commande v1 SERAIT jugée, et que la découverte repasse : les
                # deux contrôles ci-dessous sont négatifs.
                time.sleep(0.3)
            texte = capture.getvalue()
            print(texte, end="")
            chk(not branche and voisin_faux.appels == [],
                f"un flux de commandes d'une autre machine n'est jamais écouté "
                f"({len(voisin_faux.appels)} appel)")
            chk(texte.count("AUTRE machine") == 1,
                f"...et le terminal le dit UNE fois ({texte.count('AUTRE machine')})")
        except Exception as e:  # noqa: BLE001
            interrompu("autre machine", e)
        finally:
            voisin.arreter()
            voisin.fermer()
            app2 = None

        # 7. Sous charge : un moteur lent à juger (0,3 s par commande, le coût d'une résolution
        # réseau de `stream_in`) et une application qui envoie ses réglages en rafale.
        lent = FauxMoteur(f"autotest-pilotage-lent-{pid}")
        lent.delai_s = 0.3
        nom3 = f"{NOM_FLUX_COMMANDES}_autotest_lent_{pid}"
        charge = Pilotage(lent, nom_flux=nom3)
        app_a = app_b = entree3 = None
        try:
            charge.demarrer()
            app_a = StreamOutlet(StreamInfo(nom3, "Markers", 1, IRREGULAR_RATE, "string",
                                            f"autotest-app-a-{pid}"))
            branche_a = app_a.wait_for_consumers(5.0)
            app_b = StreamOutlet(StreamInfo(nom3, "Markers", 1, IRREGULAR_RATE, "string",
                                            f"autotest-app-b-{pid}"))
            branche_b = app_b.wait_for_consumers(5.0)
            info3 = _trouver_reponses(lent.instance, 5.0)
            chk(branche_a and branche_b and info3 is not None,
                "deux applications branchées sur le même moteur")
            entree3 = StreamInlet(info3, recover=False)
            entree3.open_stream(timeout=5.0)
            for i in range(8):
                app_a.push_sample([f'{{"cmd": "set_params", "mode": "ssvep", "ref": "a{i}"}}'])
            app_b.push_sample(['{"cmd": "stop_mode", "mode": "ssvep", "ref": "b0"}'])
            rec = _recevoir(entree3, 3, 3.0)
            refs = [r.get("ref") for r in rec]
            chk("b0" in refs,
                f"la rafale de A ne fait pas attendre B : B est servi parmi les 3 premières "
                f"réponses ({refs})")
            for i in range(20):
                app_a.push_sample([f'{{"cmd": "set_params", "mode": "ssvep", "ref": "r{i}"}}'])
            echeance = time.perf_counter() + 3.0
            while (not any(a[1] and str(a[1][0]).startswith("r") for a in lent.appels)
                   and time.perf_counter() < echeance):
                time.sleep(0.01)
            n_avant = len(lent.appels)
            t0 = time.perf_counter()
            arrete = charge.arreter()
            duree = time.perf_counter() - t0
            chk(arrete and duree < 2.0,
                f"`arreter()` en pleine rafale : le fil finit sa commande en cours et s'arrête "
                f"({duree:.2f} s, {len(lent.appels) - n_avant} commande(s) jugée(s) après l'ordre)")
        except Exception as e:  # noqa: BLE001
            interrompu("sous charge", e)
        finally:
            charge.arreter()
            charge.fermer()
            app_a = app_b = entree3 = None

        # 8. Ce qu'annonce une application, ou une AUTRE machine du réseau, ne tue jamais le fil
        # d'écoute. pylsl décode en UTF-8 strict l'uid, le nom d'hôte et le source_id d'un flux
        # annoncé : une bibliothèque LSL d'un autre langage peut les écrire dans l'encodage de
        # Windows, et leur lecture LÈVE.
        reessai = REESSAI_S
        nom4 = f"{NOM_FLUX_COMMANDES}_autotest_robuste_{pid}"
        faux4 = FauxMoteur(f"autotest-pilotage-robuste-{pid}")
        robuste = Pilotage(faux4, nom_flux=nom4)
        app4 = entree4 = None
        try:
            app4 = StreamOutlet(StreamInfo(nom4, "Markers", 1, IRREGULAR_RATE, "string",
                                           f"autotest-app-robuste-{pid}"))
            vrai = None
            echeance = time.perf_counter() + 5.0
            while vrai is None and time.perf_counter() < echeance:
                vrai = next((i for i in resolve_byprop("name", nom4, timeout=0.5)
                             if i.source_id() == f"autotest-app-robuste-{pid}"), None)
            chk(vrai is not None, "le flux de l'application de test est trouvé")
            if vrai is None:
                raise RuntimeError("sans flux d'application, la suite de cette section n'a pas de sens")
            mauvais = UnicodeDecodeError("utf-8", b"\xe9", 0, 1, "invalid continuation byte")

            class _Annonce:
                """Un vrai flux de cette machine, dont le champ `illisible` ne se décode pas ;
                `uid` en remplace l'identifiant, pour ne pas être confondu avec le vrai."""

                def __init__(self, vrai, illisible, uid=None):
                    self._vrai, self._illisible, self._uid = vrai, illisible, uid

                def __getattr__(self, attribut):
                    if attribut == self._illisible:
                        def leve():
                            raise mauvais
                        return leve
                    if attribut == "uid" and self._uid is not None:
                        return lambda: self._uid
                    return getattr(self._vrai, attribut)

            class _Resolveur:
                def __init__(self, infos):
                    self.infos = infos

                def results(self):
                    return list(self.infos)

            annonces = [_Annonce(vrai, "uid"), _Annonce(vrai, "hostname", uid=f"faux-{pid}"),
                        _Annonce(vrai, "source_id")]
            inlets, ecartes, leve = {}, {}, None
            capture = io.StringIO()
            with redirect_stdout(capture):
                try:
                    robuste._decouvrir(_Resolveur(annonces), inlets, ecartes)
                    robuste._decouvrir(_Resolveur(annonces), inlets, ecartes)
                except Exception as e:  # noqa: BLE001 - c'est justement ce qui est vérifié
                    leve = e
            texte = capture.getvalue()
            print(texte, end="")
            chk(leve is None,
                f"un uid, un nom d'hôte ou un source_id illisible ne fait pas lever la "
                f"découverte ({leve!r})")
            chk(list(inlets) == [vrai.uid()] and texte.count("mal formé") == 2
                and "source_id illisible" in texte,
                f"...les flux sans uid ou sans nom d'hôte lisible sont ignorés, et dits UNE fois "
                f"chacun ; celui au source_id illisible est écouté ({len(inlets)} écouté(s), "
                f"{texte.count('mal formé')} message(s))")
            for branchee in inlets.values():
                _referme(branchee.inlet)

            class _InletVide:
                """Un inlet dont l'échantillon n'a aucune voie, puis plus rien."""

                def __init__(self):
                    self.n = 0

                def pull_sample(self, timeout=0.0):
                    self.n += 1
                    return ([], 1.0) if self.n == 1 else (None, None)

            vide = {"vide": _Application(_InletVide())}
            publiees = robuste.publiees
            try:
                robuste._lire("vide", vide["vide"], vide, {})
                leve = None
            except Exception as e:  # noqa: BLE001
                leve = e
            e = robuste.journal()[-1] if robuste.journal() else {}
            chk(leve is None and robuste.publiees == publiees + 1
                and getattr(e.get("raison"), "cle", None) == "moteur.reseau.json_illisible",
                f"un échantillon SANS voie : une commande illisible, qui a sa réponse, sans lever "
                f"({leve!r})")

            # Un défaut imprévu pendant un tour : le fil le dit (une fois de suite), attend et
            # reprend. `REESSAI_S` est raccourci le temps du test.
            REESSAI_S = 0.2
            pannes = []

            def en_panne(*_args):
                pannes.append(time.perf_counter())
                if len(pannes) >= 2:
                    del robuste._decouvrir      # deux tours en panne, puis la vraie méthode
                raise RuntimeError("panne simulée de la découverte")

            # Une application NEUVE : l'inlet de test ouvert plus haut sur la première peut encore
            # compter comme un lecteur, et `wait_for_consumers` réussirait trop tôt (piège 1).
            app4 = None
            app4 = StreamOutlet(StreamInfo(nom4, "Markers", 1, IRREGULAR_RATE, "string",
                                           f"autotest-app-reprise-{pid}"))
            info4 = _trouver_reponses(faux4.instance, 5.0)
            entree4 = StreamInlet(info4, recover=False)
            entree4.open_stream(timeout=5.0)
            robuste._decouvrir = en_panne
            capture = io.StringIO()
            with redirect_stdout(capture):
                robuste.demarrer()
                branche = app4.wait_for_consumers(5.0)
                app4.push_sample(['{"cmd": "stop_mode", "mode": "ssvep", "ref": "reprise"}'])
                rec = _recevoir(entree4, 1, 5.0)
            texte = capture.getvalue()
            print(texte, end="")
            chk(len(pannes) == 2 and robuste.vivant and branche
                and [r.get("ref") for r in rec] == ["reprise"],
                f"deux tours en panne : le fil d'écoute survit, se branche, puis répond "
                f"({len(pannes)} pannes, vivant : {robuste.vivant}, {rec})")
            chk(texte.count("défaut dans le fil d'écoute") == 1 and "panne simulée" in texte,
                f"...et le terminal le dit une fois, pas à chaque tour "
                f"({texte.count('défaut dans le fil d')} fois)")
            # …mais le MÊME défaut qui revient après une reprise réussie est redit : le terminal
            # est le seul signe.
            encore = []

            def en_panne_encore(*_args):
                encore.append(time.perf_counter())
                del robuste._decouvrir
                raise RuntimeError("panne simulée de la découverte")

            capture = io.StringIO()
            with redirect_stdout(capture):
                robuste._decouvrir = en_panne_encore
                echeance = time.perf_counter() + 3.0
                while not encore and time.perf_counter() < echeance:
                    time.sleep(0.02)
                time.sleep(0.1)
            texte2 = capture.getvalue()
            print(texte2, end="")
            chk(len(encore) == 1 and texte2.count("défaut dans le fil d'écoute") == 1,
                f"...et le même défaut, revenu après une reprise, est redit "
                f"({texte2.count('défaut dans le fil d')} fois)")
        except Exception as e:  # noqa: BLE001
            interrompu("annonces mal formées", e)
        finally:
            REESSAI_S = reessai
            robuste.arreter()
            robuste.fermer()
            app4 = entree4 = None

        # 9. Une application ne peut pas noyer le moteur : au plus `DEBIT_MAX` commandes par
        # seconde, et chaque commande en trop a sa réponse, un refus qui le dit. L'inlet, lui, ne
        # garde que 100 commandes en attente (`TAMPON_INLET`) : au-delà, les plus anciennes sont
        # perdues, sans réponse.
        nom5 = f"{NOM_FLUX_COMMANDES}_autotest_debit_{pid}"
        faux5 = FauxMoteur(f"autotest-pilotage-debit-{pid}")
        borne = Pilotage(faux5, nom_flux=nom5)
        app5 = app6 = entree5 = None
        try:
            info5 = _trouver_reponses(faux5.instance, 5.0)
            entree5 = StreamInlet(info5, recover=False)
            entree5.open_stream(timeout=5.0)
            borne.demarrer()
            # La bavarde d'abord, la sage ensuite : la bavarde est lue la première à chaque tour.
            app5 = StreamOutlet(StreamInfo(nom5, "Markers", 1, IRREGULAR_RATE, "string",
                                           f"autotest-app-bavarde-{pid}"))
            branche5 = app5.wait_for_consumers(5.0)
            app6 = StreamOutlet(StreamInfo(nom5, "Markers", 1, IRREGULAR_RATE, "string",
                                           f"autotest-app-sage-{pid}"))
            chk(branche5 and app6.wait_for_consumers(5.0),
                "deux applications branchées, une bavarde et une sage")
            t0 = time.perf_counter()
            for i in range(60):
                app5.push_sample([f'{{"cmd": "set_params", "mode": "ssvep", "ref": "d{i}"}}'])
            envoi = time.perf_counter() - t0
            app6.push_sample(['{"cmd": "stop_mode", "mode": "ssvep", "ref": "sage"}'])
            rec = _recevoir(entree5, 61, 5.0)
            des_d = [r for r in rec if str(r.get("ref", "")).startswith("d")]
            acceptees = [r["ref"] for r in des_d if r.get("accepted")]
            refusees = [r for r in des_d if not r.get("accepted")]
            trop = pour_le_contrat(tr("moteur.reseau.trop_de_commandes", n=nombre(DEBIT_MAX)))
            chk(len(des_d) == 60 and DEBIT_MAX <= len(acceptees) <= DEBIT_MAX + 5
                and acceptees[:DEBIT_MAX] == [f"d{i}" for i in range(DEBIT_MAX)]
                and bool(refusees) and all(r.get("reason") == trop for r in refusees)
                and sum(1 for a in faux5.appels if str(a[1][0]).startswith("d")) == len(acceptees),
                f"60 commandes en {envoi * 1000:.0f} ms : une réponse pour chacune, "
                f"{len(acceptees)} acceptées, {len(refusees)} refusées sans atteindre le moteur "
                f"({refusees[0].get('reason') if refusees else '-'!r})")
            chk(any(getattr(e.get("raison"), "cle", None) == "moteur.reseau.trop_de_commandes"
                    for e in borne.journal()),
                "...et le journal montre le refus, dans la langue de l'écran")
            sage = [r for r in rec if r.get("ref") == "sage"]
            chk(len(sage) == 1 and sage[0].get("accepted") is True,
                f"...la borne est PAR application : la sage est servie pendant la rafale ({sage})")

            # Le tampon : l'adaptateur est occupé 1 s par une commande pendant que l'application
            # en envoie 150 autres. L'inlet n'en garde que les 100 dernières.
            time.sleep(1.0)                 # le seau de la bavarde se remplit à nouveau
            app5.push_sample(['{"cmd": "set_params", "mode": "ssvep", "ref": "bloque"}'])
            echeance = time.perf_counter() + 5.0
            while (not any(a[1] and a[1][0] == "bloque" for a in faux5.appels)
                   and time.perf_counter() < echeance):
                time.sleep(0.01)
            for i in range(150):
                app5.push_sample([f'{{"cmd": "set_params", "mode": "ssvep", "ref": "t{i}"}}'])
            rec = [json.loads(t) for t in _recevoir_brut(entree5, 151, 8.0,
                                                         fini=lambda t: '"t149"' in t)]
            des_t = [r.get("ref") for r in rec if str(r.get("ref", "")).startswith("t")]
            chk(any(r.get("ref") == "bloque" for r in rec) and 90 <= len(des_t) <= 101
                and des_t[-1:] == ["t149"] and "t0" not in des_t,
                f"150 commandes pendant que l'adaptateur est occupé : l'inlet garde les ~100 "
                f"dernières, chacune avec sa réponse ; les plus anciennes sont perdues "
                f"({len(des_t)} réponses, de {des_t[0] if des_t else '-'} à "
                f"{des_t[-1] if des_t else '-'})")

            # Le MOTEUR s'arrête : en écoute permanente, CHAQUE application écoutée reçoit
            # « disconnected », avant que son flux ne se referme.
            borne.annoncer_arret(("raw",))
            borne.arreter()
            vus = _deconnexions(entree5, 2, 2.0)
            noms5 = sorted(m.get("app") or "" for m in vus)
            attendu = deconnexion("?", ("raw",), "engine_stopped")
            chk(noms5 == sorted([f"autotest-app-bavarde-{pid}", f"autotest-app-sage-{pid}"])
                and all({**m, "app": "?"} == attendu for m in vus),
                f"écoute permanente : à l'arrêt du moteur, les deux applications écoutées "
                f"reçoivent « disconnected » (cause « engine_stopped », modes arrêtés) "
                f"({noms5}, {vus[:1]})")
        except Exception as e:  # noqa: BLE001
            interrompu("débit", e)
        finally:
            borne.arreter()
            borne.fermer()
            app5 = app6 = entree5 = None

        # 10. L'écoute SUR DEMANDE, celle de la console : personne n'est entendu avant qu'on ait
        # choisi une application ; la recherche lit les annonces SANS ouvrir aucun flux ; une
        # seule application est écoutée ; une déconnexion referme son flux ; son départ est
        # signalé au moteur, qu'elle ferme son flux ou qu'elle disparaisse avant d'avoir été
        # ouverte ; un fil redémarré ne la prend pas pour partie. Et la recherche liste aussi les
        # applications d'une AUTRE machine, avec leur machine.
        nom6 = f"{NOM_FLUX_COMMANDES}_autotest_demande_{pid}"
        faux6 = FauxMoteur(f"autotest-pilotage-demande-{pid}")
        demande = Pilotage(faux6, nom_flux=nom6, ecoute="sur_demande")
        etranger = Pilotage(FauxMoteur(f"autotest-pilotage-etranger-{pid}"), nom_flux=nom6,
                            hote="une-autre-machine", ecoute="sur_demande")
        faux_direct = FauxMoteur(f"autotest-pilotage-direct-{pid}")
        direct = Pilotage(faux_direct, nom_flux=nom6, ecoute="sur_demande")   # jamais démarré
        app7 = app8 = entree6 = entree8 = None
        # Le nom de l'application choisie dépasse `CMD_AFFICHEE_MAX` : la liste l'affiche coupé
        # (`court7`), le message « disconnected » doit le porter EN ENTIER.
        nom7, nom8 = f"autotest-app-choisie-{'n' * 50}-{pid}", f"autotest-app-ignoree-{pid}"
        court7 = _court(nom7)
        nom9l = f"autotest-app-lointaine-{pid}"

        def attendre(cond, delai_s=5.0):
            echeance = time.perf_counter() + delai_s
            while not cond() and time.perf_counter() < echeance:
                time.sleep(0.05)
            return cond()

        class _UneCommande:
            """Un flux qui n'a qu'une commande à donner et compte combien de fois on le lit."""

            def __init__(self):
                self.lectures, self.restantes = 0, 1

            def pull_sample(self, timeout=0.0):
                self.lectures += 1
                if self.restantes:
                    self.restantes -= 1
                    return ['{"cmd": "stop_mode", "mode": "ssvep", "ref": "z"}'], 0.0
                return None, None

        try:
            try:
                Pilotage(faux6, nom_flux=nom6, ecoute="parfois")
                chk(False, "une écoute inconnue est refusée")
            except ValueError:
                chk(True, "une écoute inconnue est refusée")

            # Les gestes internes, sans réseau : un départ ne concerne que l'application choisie,
            # et une application déconnectée en cours de tour n'est plus lue.
            direct._choisie = "a"
            direct._application_partie("b")
            chk(faux_direct.parties == [] and direct._choisie == "a",
                "le départ d'une application qui n'est pas la choisie ne signale rien")
            flux = _UneCommande()
            direct._choisie = None
            direct._lire("a", _Application(flux), {}, {})
            chk(flux.lectures == 0 and faux_direct.appels == [],
                "une application déconnectée n'est plus lue, même au milieu d'un tour")
            direct._choisie = "a"
            direct._lire("a", _Application(flux), {}, {})
            chk(flux.lectures >= 1 and len(faux_direct.appels) == 1,
                "...et la même, choisie, est lue (la garde ne coupe pas tout)")
            direct._application_partie("a")
            chk(faux_direct.parties == ["a"] and direct._choisie is None,
                "le départ de l'application choisie est signalé au moteur")
            # Le nom d'une annonce vient du `source_id` de l'application, sans borne : il est
            # coupé comme au journal, pour n'envahir ni la liste ni le bandeau de la console.
            direct.chercher(True)
            direct._noter_annonces({"longue": (None, direct.hote, "n" * 300),
                                    "muette": (None, direct.hote, None)})
            vues = {a["uid"]: a for a in direct.annonces()}
            longue, muette = vues.get("longue") or {}, vues.get("muette") or {}
            chk(longue.get("nom") == "n" * CMD_AFFICHEE_MAX + "…" and not longue.get("illisible")
                and muette.get("nom") == "" and muette.get("illisible") is True,
                f"un nom d'application de 300 caractères est coupé à {CMD_AFFICHEE_MAX} ; un nom "
                f"illisible reste vide, et marqué comme tel ({len(longue.get('nom') or '')} "
                f"caractères, {muette})")
            # Une application d'une AUTRE machine : listée avec sa machine, et connectable.
            direct.chercher(True)
            direct._noter_annonces({"loin": (None, "AUTRE-PC", "appli-distante")})
            loin = next((a for a in direct.annonces() if a["uid"] == "loin"), {})
            chk(loin.get("machine") == "AUTRE-PC" and loin.get("origine") == "lsl"
                and loin.get("id") is None and loin.get("nom") == "appli-distante",
                f"sur demande, une annonce d'AUTRE-PC est listée avec sa machine ({loin})")
            chk(direct.connecter("loin") == "appli-distante",
                "...et connecter() l'accepte")
            direct.deconnecter(adieu=False)
            direct.chercher(False)

            info6 = _trouver_reponses(faux6.instance, 5.0)
            entree6 = StreamInlet(info6, recover=False)
            entree6.open_stream(timeout=5.0)
            # Le flux de réponses est COMMUN : l'autre application de la machine l'écoute aussi.
            entree8 = StreamInlet(info6, recover=False)
            entree8.open_stream(timeout=5.0)
            demande.demarrer()
            etranger.demarrer()
            app7 = StreamOutlet(StreamInfo(nom6, "Markers", 1, IRREGULAR_RATE, "string", nom7))
            app8 = StreamOutlet(StreamInfo(nom6, "Markers", 1, IRREGULAR_RATE, "string", nom8))
            chk(not app7.wait_for_consumers(1.5) and demande.annonces() == [],
                "sur demande, sans recherche : personne n'écoute l'application, rien n'est listé")
            chk(etranger._etrangers_dits == set(),
                "...et le fil ne lit rien du réseau : aucun flux vu, pas même pour l'ignorer")
            demande.chercher(True)
            etranger.chercher(True)
            attendre(lambda: len(demande.annonces()) >= 2)
            vues = demande.annonces()
            noms = sorted(a["nom"] for a in vues)
            chk(noms == sorted([court7, nom8]) and all(a["depuis"] > 0 for a in vues),
                f"la recherche voit les deux applications de cette machine, par leur nom ({noms})")
            # La recherche de la console liste aussi les applications d'une AUTRE machine : le clic
            # de l'élève protège. Ici « autre » = l'hôte de ce moteur diffère de celui des flux.
            attendre(lambda: len(etranger.annonces()) >= 2)
            chk(len(etranger.annonces()) >= 2
                and all(a["origine"] == "lsl" and a["id"] is None
                        and _meme_hote(a["machine"], socket.gethostname())
                        for a in etranger.annonces()),
                f"la recherche d'une AUTRE machine liste ces flux, avec leur machine "
                f"({etranger.annonces()})")
            chk(not app7.wait_for_consumers(1.0) and not app8.have_consumers(),
                "...et elle n'ouvre aucun flux : aucune application ne se croit écoutée")
            uid7 = next((a["uid"] for a in vues if a["nom"] == court7), None)
            uid8 = next((a["uid"] for a in vues if a["nom"] == nom8), None)
            chk(demande.connecter("inconnu") is None,
                "on ne connecte pas une application que la recherche ne voit pas")
            chk(demande.connecter(uid7) == court7 and demande.annonces() == [],
                "connecter rend le nom de l'application et arrête la recherche")
            chk(app7.wait_for_consumers(5.0) and attendre(demande.branchee),
                "le flux de l'application choisie est ouvert, et l'écoute le sait")
            chk(demande.annonces() == [],
                "...et la recherche reste coupée : rien n'est relisté")
            chk(not app8.wait_for_consumers(1.0), "...celui de l'autre ne l'est pas")
            app7.push_sample(['{"cmd": "stop_mode", "mode": "ssvep", "ref": "e1"}'])
            app8.push_sample(['{"cmd": "stop_mode", "mode": "ssvep", "ref": "e2"}'])
            rec = _recevoir(entree6, 2, 2.0)
            chk([r.get("ref") for r in rec] == ["e1"],
                f"seule l'application choisie est entendue ({[r.get('ref') for r in rec]})")
            # « Déconnecter » pendant que l'application attend ses décisions : elle n'envoie RIEN.
            # Le moteur le lui dit sur le flux de réponses, avec son source_id COMPLET.
            t_fin = time.perf_counter()
            demande.deconnecter()
            vus = _deconnexions(entree6, 1, 2.0)
            delai_fin = time.perf_counter() - t_fin
            encore_compte = app7.have_consumers()
            message = vus[0] if len(vus) == 1 else {}
            chk(message.get("app") == nom7 and message.get("cause") == "console"
                and message.get("stopped") == [] and isinstance(message.get("reason"), str)
                and delai_fin < 2.0,
                f"déconnecter : l'application reçoit « disconnected » en moins de 2 s sans rien "
                f"envoyer, avec son source_id complet ({len(nom7)} caractères, la liste en "
                f"montre {len(court7)}) ({delai_fin:.2f} s, {vus})")
            autres = _deconnexions(entree8, 1, 1.0)
            chk(len(autres) == 1 and autres[0].get("app") == nom7
                and autres[0].get("app") != nom8,
                f"...l'autre application de la machine le lit aussi, et y voit que « app » n'est "
                f"pas le sien ({[m.get('app') for m in autres]})")
            chk(attendre(lambda: not demande.branchee()) and _ferme_au_prochain_envoi(app7),
                f"...son flux est refermé, et LSL ne le dit à l'application qu'à son PROCHAIN "
                f"envoi (`have_consumers()` juste après le message : {encore_compte})")
            chk(faux6.parties == [], "une déconnexion demandée n'est pas un départ")
            demande.chercher(True)
            attendre(lambda: any(a["uid"] == uid7 for a in demande.annonces()))
            chk(demande.connecter(uid7) == court7 and app7.wait_for_consumers(5.0)
                and attendre(demande.branchee),
                "la même application se reconnecte")

            # Le fil d'écoute redémarre alors que l'application est toujours là : son résolveur
            # neuf ne voit rien pendant son premier tour, ce qui ne veut pas dire qu'elle est
            # partie. Un simple arrêt du fil n'est pas un arrêt du MOTEUR : aucun message.
            demande.arreter()
            chk(_deconnexions(entree6, 1, 0.5) == [],
                "un fil d'écoute arrêté sans que le moteur s'arrête ne dit pas « disconnected »")
            demande.demarrer()
            chk(app7.wait_for_consumers(5.0) and attendre(demande.branchee)
                and faux6.parties == [],
                f"un fil d'écoute redémarré rebranche l'application, sans la croire partie "
                f"({faux6.parties})")

            # Le flux de l'application se ferme : LSL le dit en ~30 ms (`LostError`). La règle
            # « choisie et plus annoncée » prend ~5 s : avec 3 s d'attente, elle ne peut pas
            # être celle qui répond.
            app7 = None                     # l'application se ferme : son outlet disparaît
            chk(attendre(lambda: faux6.parties == [uid7], 3.0) and not demande.branchee(),
                f"une application connectée qui disparaît : le moteur est prévenu "
                f"({faux6.parties})")
            # Partie d'elle-même, elle ne lit plus rien ; une copie relancée sous le même nom
            # prendrait le message pour elle.
            chk(_deconnexions(entree6, 1, 0.5) == [],
                "...et aucun « disconnected » n'est publié pour une application partie")

            # Une application choisie qui disparaît AVANT d'avoir été ouverte : son outlet
            # détruit reste annoncé ~5 s, on peut donc la choisir, son ouverture échoue, puis elle
            # n'est plus annoncée.
            demande.chercher(True)
            chk(attendre(lambda: any(a["uid"] == uid8 for a in demande.annonces())),
                "la recherche revoit l'autre application")
            app8 = None
            debut8 = time.perf_counter()
            chk(demande.connecter(uid8) == nom8,
                "...détruite mais encore annoncée : on peut la choisir")
            vue_branchee = False
            while (uid8 not in faux6.parties
                   and time.perf_counter() - debut8 < OUBLI_S + 4.0):
                vue_branchee = vue_branchee or demande.branchee()
                time.sleep(0.05)
            chk(not vue_branchee and not demande.branchee(),
                "...son flux n'a jamais pu s'ouvrir : l'écoute ne se dit jamais branchée")
            chk(uid8 in faux6.parties,
                f"une application choisie qui disparaît sans avoir été ouverte : le moteur est "
                f"prévenu ({faux6.parties}, {time.perf_counter() - debut8:.1f} s)")

            # Sur demande, une application d'une autre machine s'OUVRE une fois choisie (la garde
            # « même machine » ne vaut qu'en écoute permanente).
            app9 = StreamOutlet(StreamInfo(nom6, "Markers", 1, IRREGULAR_RATE, "string", nom9l))
            uid9 = None
            if attendre(lambda: any(a["nom"] == nom9l for a in etranger.annonces())):
                uid9 = next(a["uid"] for a in etranger.annonces() if a["nom"] == nom9l)
            chk(uid9 is not None and etranger.connecter(uid9) == nom9l
                and app9.wait_for_consumers(5.0) and attendre(etranger.branchee),
                "sur demande, le flux d'une application d'une AUTRE machine s'ouvre une fois choisie")
            app9 = None

            # Les gestes internes du message « disconnected », sans fil d'écoute ni réseau : ce
            # que le fil publierait est noté avec l'état du flux à cet instant.
            class _FluxOuvert:
                def __init__(self):
                    self.ferme = False

                def close_stream(self):
                    self.ferme = True

            publies = []
            ouvert = _FluxOuvert()
            direct._publier = lambda message: publies.append((message, ouvert.ferme)) or True
            direct._choisie = "a"
            direct.deconnecter(arretes=("ssvep",))
            direct._lacher_les_autres({})
            chk(publies == [] and direct._adieux == {},
                "une application choisie mais jamais ouverte ne reçoit pas « disconnected » : "
                "elle ne s'est jamais crue connectée")
            inlets = {"a": _Application(ouvert, source="s" * 80)}
            direct._choisie = "a"
            direct.deconnecter(arretes=("ssvep",))
            direct._lacher_les_autres(inlets)
            direct._lacher_les_autres(inlets)
            chk(publies == [(deconnexion("s" * 80, ("ssvep",), "console"), False)]
                and ouvert.ferme and inlets == {},
                f"...ouverte : le message part UNE fois, AVANT que son flux ne se referme "
                f"({publies})")
            publies.clear()
            ouvert = _FluxOuvert()
            direct._choisie = "a"
            direct.deconnecter(arretes=("ssvep",), adieu=False)
            direct._lacher_les_autres({"a": _Application(ouvert, source="s")})
            chk(publies == [] and ouvert.ferme,
                "`deconnecter(adieu=False)` (l'application est partie) referme sans message")
        except Exception as e:  # noqa: BLE001
            interrompu("sur demande", e)
        finally:
            for p in (demande, etranger, direct):
                p.arreter()
                p.fermer()
            app7 = app8 = entree6 = entree8 = None

        # 11. Le message « disconnected » avec les modes arrêtés, puis l'arrêt du MOTEUR pendant
        # une connexion : sans ce dernier message, une application qui attend sans limite (un
        # démarrage différé) attendrait pour toujours.
        nom9 = f"{NOM_FLUX_COMMANDES}_autotest_adieu_{pid}"
        faux9 = FauxMoteur(f"autotest-pilotage-adieu-{pid}")
        adieu = Pilotage(faux9, nom_flux=nom9, ecoute="sur_demande")
        nom_a = f"autotest-app-adieu-{pid}"
        app9 = entree9 = None

        def connecter_app9():
            adieu.chercher(True)
            attendre(lambda: any(a["nom"] == nom_a for a in adieu.annonces()))
            uid = next((a["uid"] for a in adieu.annonces() if a["nom"] == nom_a), None)
            return (uid is not None and adieu.connecter(uid) == nom_a
                    and attendre(adieu.branchee))

        try:
            info9 = _trouver_reponses(faux9.instance, 5.0)
            entree9 = StreamInlet(info9, recover=False)
            entree9.open_stream(timeout=5.0)
            adieu.demarrer()
            app9 = StreamOutlet(StreamInfo(nom9, "Markers", 1, IRREGULAR_RATE, "string", nom_a))
            chk(connecter_app9(), "11. une application connectée")
            adieu.deconnecter(arretes=("ssvep", "neuro"))
            vus = _deconnexions(entree9, 1, 2.0)
            chk(vus == [deconnexion(nom_a, ("ssvep", "neuro"), "console")]
                and vus[0]["stopped"] == ["ssvep", "neuro"]
                and vus[0]["reason"].startswith("Disconnected in the console"),
                f"...« Déconnecter » : le message nomme les modes que le moteur arrête, raison en "
                f"anglais ({vus})")
            # Le compte de LSL remis à jour avant de rebrancher : sans lui, `wait_for_consumers`
            # verrait encore l'ancien lecteur, et la reconnexion ne prouverait rien.
            chk(_ferme_au_prochain_envoi(app9),
                "...son flux est refermé (LSL le dit à l'application à son envoi suivant)")
            chk(connecter_app9(), "...reconnectée")
            adieu.annoncer_arret(("ssvep", "raw"))
            t0 = time.perf_counter()
            arrete = adieu.arreter()
            duree = time.perf_counter() - t0
            vus = _deconnexions(entree9, 1, 2.0)
            chk(vus == [deconnexion(nom_a, ("ssvep", "raw"), "engine_stopped")]
                and vus[0]["reason"] != deconnexion(nom_a, (), "console")["reason"],
                f"...le MOTEUR s'arrête : elle reçoit « disconnected », cause « engine_stopped », "
                f"avec une autre raison ({vus})")
            chk(arrete and duree < 2.0 and not adieu.branchee() and _ferme_au_prochain_envoi(app9),
                f"...le fil s'arrête quand même en moins de 2 s, et son flux est refermé "
                f"({duree:.2f} s)")
        except Exception as e:  # noqa: BLE001
            interrompu("message disconnected", e)
        finally:
            adieu.arreter()
            adieu.fermer()
            app9 = entree9 = None

        restants = [t.name for t in threading.enumerate() if t.name.startswith("pilotage")]
        chk(restants == [], f"aucun fil d'écoute ne reste vivant ({restants})")
        duree = time.perf_counter() - debut
        # La section 10 attend des connexions LSL réelles (~15 s) : la borne suit.
        chk(duree < 45.0, f"l'autotest dure moins de 45 s ({duree:.1f} s)")
    finally:
        if langue_avant is None:
            os.environ.pop("EEG_LANGUE", None)
        else:
            os.environ["EEG_LANGUE"] = langue_avant

    print(f"[pilotage] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if _selftest() else 1)
