"""Le transport UDP du pilotage : un appareil qui ne parle pas LSL (un ESP32 sur le Wi-Fi) se
fait connaître, se connecte au clic dans la console, et envoie les MÊMES commandes qu'une
application LSL, pour les MÊMES réponses.

    appareil ──hello (diffusion, chaque seconde)──▶ moteur, port 5010   listé si on cherche
    appareil ◀──identify──                                             « Identifier »
    appareil ◀──connect──    appareil ──connected──▶                   « Connecter »
    appareil ──commande──▶ Pilotage.traiter ──réponse──▶ appareil      les commandes
    appareil ◀──alive──▶ chaque seconde, dans les deux sens           le signe de vie
    appareil ◀──disconnected── (« Déconnecter »)   appareil ──bye──▶ (il s'arrête)

Un datagramme = un objet JSON en UTF-8 qui porte "v": 1 (`VERSION`), de `TAILLE_MAX` octets au
plus. Tout autre datagramme est ignoré, sans réponse. Les formes exactes sont dans
`docs/control.md`.

Ce module ne juge AUCUNE commande : il les passe à `Pilotage.servir`, le chemin des commandes LSL
(lecture, limite par seconde, `submit`, journal), et la réponse revient par le point de sortie du
pilotage, qui l'envoie ici (`envoyer`, avec "v" et un "seq" croissant). Une seule différence avec
LSL : un `start_mode` ou un `set_params` d'un mode hors `MODES_SERVIS` est refusé avec sa raison.
P300, ErrP et c-VEP ont besoin de marqueurs horodatés dans l'horloge LSL, qu'un microcontrôleur
n'a pas ; le Brut (8 voies à 250 Hz) n'a rien à faire sur un appareil réseau.

Aucun fil à lui : `tour()`, non bloquant, est appelé par le fil d'écoute du pilotage à chaque
tour. `connecter` et `identifier`, appelés d'un autre fil, ne font que noter ce qu'il faut
envoyer. Les délais (`MUET_S`, `ATTENTE_CONNEXION_S`, `VIE_S`, `SILENCE_S`) se lisent sur
l'horloge `maintenant`, que l'autotest remplace.

⚠️ L'appareil envoie depuis le port qu'il annonce dans son hello : c'est à cette adresse que le
moteur reconnaît SES messages. Un message venu d'un autre port est ignoré, sans réponse.

⚠️ Un hello n'est PAS un signe de vie : un appareil connecté qui redémarre s'annonce à nouveau,
et la connexion doit finir au bout de `SILENCE_S`, pas durer pour toujours.

Autotest (aucun casque ; ouvre des sockets UDP sur 127.0.0.1 et des flux LSL locaux) :
    python src/core/pilotage_udp.py
"""

import collections
import errno
import json
import os
import socket
import sys
import threading
import time
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import use_utf8_console  # noqa: E402
from core.i18n import tr  # noqa: E402
from core.pilotage import (COMMANDES_EN_ATTENTE, MAX_PAR_TOUR, TEMPS_PAR_FLUX_S,  # noqa: E402
                           Seau, _court, _decrire, _dire, _en_json, deconnexion, lire_commande,
                           refus_debit)

# Le port où le moteur écoute. Distinct des ports 5006/5007 de `pont.py` (JeuLed), qui peut
# encore tourner à côté.
PORT_UDP = 5010
VERSION = 1
# Un datagramme plus gros est ignoré. La lecture prend toujours de quoi recevoir le plus gros
# datagramme possible (`_LECTURE`) : jamais tronqué, sa taille se compare donc exactement.
TAILLE_MAX = 8192
_LECTURE = 65536
MODES_SERVIS = ("ssvep", "mi", "neuro")
# Seules ces commandes démarrent ou règlent un mode : ce sont elles que `MODES_SERVIS` filtre.
_COMMANDES_FILTREES = ("start_mode", "set_params")
# La valeur du champ "hello" : un datagramme d'un autre programme sur ce port n'est pas listé.
ANNONCE = "EEG_API_Unicorn"
# L'uid d'un appareil : "udp:<ip>:<port annoncé>". Il ne ressemble à aucun uid de flux LSL.
PREFIXE_UID = "udp:"
MUET_S = 5.0                # un appareil muet depuis ce temps sort de la liste
ATTENTE_CONNEXION_S = 3.0   # la réponse à « connect » attendue au plus ce temps
VIE_S = 1.0                 # un « alive » vers l'appareil connecté à ce rythme
SILENCE_S = 5.0             # rien de l'appareil connecté pendant ce temps : il est parti
# Par tour, au plus autant de datagrammes lus : un flot de datagrammes ne bloque pas le fil.
DATAGRAMMES_PAR_TOUR = 256
# Au plus autant d'appareils dans la liste : une rafale de faux hello ne la fait pas grossir
# sans fin (une salle en compte une trentaine).
APPAREILS_MAX = 100
# Les erreurs de `bind` qui veulent dire « le port est déjà pris ». Sous Windows : 10048
# (WSAEADDRINUSE), et 10013 (WSAEACCES) quand l'autre socket le tient en exclusivité.
_PORT_PRIS = {errno.EADDRINUSE, errno.EACCES, 10048, 10013}


def uid_de(ip, port):
    """L'uid d'un appareil réseau, tel que la liste et le moteur le connaissent."""
    return f"{PREFIXE_UID}{ip}:{port}"


def lire_message(donnees):
    """Un datagramme reçu, en dict, ou None s'il faut l'ignorer : plus de `TAILLE_MAX` octets,
    pas un objet JSON, ou pas de la version `VERSION`. Ne lève jamais.

    Les octets qui ne sont pas de l'UTF-8 sont remplacés, seulement pour CLASSER le message : une
    commande garde ses octets bruts, que `Pilotage.traiter` refuse alors pour cette raison-là, en
    rendant son « ref » à l'appareil, comme par LSL."""
    if not isinstance(donnees, (bytes, bytearray)) or len(donnees) > TAILLE_MAX:
        return None
    try:
        message = json.loads(bytes(donnees).decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - « ne lève jamais » : pas du JSON, trop imbriqué...
        return None
    if not isinstance(message, dict):
        return None
    v = message.get("v")
    if isinstance(v, bool) or v != VERSION:     # `True == 1` en Python : refusé à part
        return None
    return message


def refus_mode_non_servi(texte):
    """Le refus d'un `start_mode` ou d'un `set_params` pour un mode que le réseau ne sert pas
    (P300, ErrP, c-VEP, Brut), ou None.

    Une commande illisible, ou un mode INCONNU, passe : `traiter` et le moteur la refusent pour
    leur propre raison, la même que par LSL. Le registre est importé ici : il charge tout le
    catalogue des modes."""
    commande = lire_commande(texte)
    if (commande.refus is not None or commande.cmd not in _COMMANDES_FILTREES
            or not isinstance(commande.mode, str) or commande.mode in MODES_SERVIS):
        return None
    from core.modes import registry
    if registry.get(commande.mode) is None:
        return None
    return tr("moteur.reseau.mode_non_servi", mode=commande.mode, liste=", ".join(MODES_SERVIS))


def _port_pris(e):
    return getattr(e, "winerror", None) in _PORT_PRIS or e.errno in _PORT_PRIS


@dataclass
class _Annonce:
    """Un appareil vu sur le réseau : son dernier hello."""
    uid: str
    ip: str
    port: int
    app: str            # le nom annoncé, en entier ; la liste le coupe
    ident: object       # son identifiant (la fin de son adresse MAC, par exemple), ou None
    vu: float           # `maintenant()` de son dernier hello
    depuis: float       # `time.time()` de son premier hello, pour la console

    def annonce(self):
        return {"uid": self.uid, "nom": _court(self.app), "id": self.ident,
                "adresse": f"{self.ip}:{self.port}", "machine": self.ip, "origine": "udp",
                "depuis": self.depuis, "illisible": False}


@dataclass
class _Lien:
    """La connexion à UN appareil : la poignée de main, puis la vie de la connexion.

    `etat` : « attente » (connect à envoyer ou envoyé, pas encore de réponse), puis « connecte ».
    `fin` : (raison, hôte) quand l'appareil a dit busy ou bye ; `tour()` termine alors la
    connexion. Un `_Lien` est un objet neuf à chaque « Connecter » : le pilotage s'en sert de
    jeton (`oublier`)."""
    uid: str
    adresse: tuple
    app: str
    etat: str = "attente"
    envoye: bool = False
    echeance: float = 0.0       # la fin de l'attente de « connected »
    vu: float = 0.0             # le dernier message de l'appareil (connecté)
    vie: float = 0.0            # le prochain « alive » à lui envoyer
    seau: object = None         # sa limite de commandes par seconde, comme une application LSL
    fin: object = None


class TransportUDP:
    """Le transport UDP d'un `Pilotage` (écoute sur demande seulement : la console).

    - `ouvrir()` lie la socket (None, ou la raison : le port est pris) ; `fermer()` la rend.
    - `tour()` : appelé par le fil du pilotage à chaque tour, ne bloque jamais. Il lit les
      datagrammes en attente, tient la liste des appareils, mène la poignée de main, envoie
      « alive », sert les commandes de l'appareil connecté et repère sa fin (busy, sans réponse,
      silence, bye), qu'il dit au moteur par `pilotage._application_partie`.
    - `appareils()` : ceux vus depuis moins de `MUET_S`, au format de `Pilotage.annonces()`.
    - `identifier(uid)`, `connecter(uid)` : sûrs depuis n'importe quel fil.
    - `envoyer(uid, message)`, `deconnecter(uid, arretes, cause)`, `oublier(jeton)` : le fil du
      pilotage seulement — c'est lui qui écrit sur la socket.

    Une seule connexion à la fois : celle de l'application que le pilotage a choisie.
    """

    def __init__(self, pilotage, port=PORT_UDP, adresse="0.0.0.0", maintenant=time.monotonic):
        self.pilotage = pilotage
        self.port = int(port)           # 0 : un port libre, choisi au `bind` (l'autotest)
        self.adresse = str(adresse)
        self.maintenant = maintenant
        self._sock = None
        # Protège la liste, la connexion et les files. Toujours pris EN DERNIER : jamais tenu
        # pendant un appel au pilotage ou au moteur, ni pendant un envoi.
        self._verrou = threading.Lock()
        self._appareils = {}                                # uid -> _Annonce
        self._lien = None                                   # _Lien, ou None
        self._a_envoyer = collections.deque(maxlen=64)      # (adresse, message), d'autres fils
        # Les commandes de l'appareil connecté, servies à chaque tour dans les limites du
        # pilotage. Pleine, la file jette les plus ANCIENNES, comme l'inlet d'une application LSL.
        self._commandes = collections.deque(maxlen=COMMANDES_EN_ATTENTE)
        self._seq = 0
        self.envoyes = 0        # datagrammes envoyés
        self.ignores = 0        # datagrammes ignorés (illisibles, trop gros, d'un inconnu)
        self._dernier_dit = None

    # --- la socket ------------------------------------------------------------------------

    @property
    def ouvert(self):
        return self._sock is not None

    def ouvrir(self):
        """Lie la socket. None si elle écoute (le port réel est alors dans `self.port`), sinon
        la raison, un `Texte`.

        ⚠️ `SO_EXCLUSIVEADDRUSE` sous Windows : sans lui, une seconde console pourrait se lier au
        même port sur l'adresse « toutes les interfaces », et les deux se voleraient les
        datagrammes sans aucune erreur."""
        if self._sock is not None:
            return None
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind((self.adresse, self.port))
            sock.setblocking(False)
        except OSError as e:
            if sock is not None:
                sock.close()
            _dire(f"[pilotage] écoute UDP impossible sur le port {self.port} : {_decrire(e)}")
            if _port_pris(e):
                return tr("moteur.reseau.udp_port_pris", port=str(self.port))
            return tr("moteur.reseau.udp_indisponible", port=str(self.port), erreur=_decrire(e))
        self.port = sock.getsockname()[1]
        self._sock = sock
        _dire(f"[pilotage] écoute UDP sur {self.adresse}:{self.port}")
        return None

    def fermer(self):
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        with self._verrou:
            self._lien = None
            self._appareils = {}
            self._commandes.clear()
            self._a_envoyer.clear()

    # --- ce que le pilotage demande -------------------------------------------------------

    def est_a_lui(self, uid):
        """Cet uid est-il celui d'un appareil réseau ?"""
        return isinstance(uid, str) and uid.startswith(PREFIXE_UID)

    def appareils(self):
        """Les appareils vus depuis moins de `MUET_S`, au format de `Pilotage.annonces()`."""
        maintenant = self.maintenant()
        with self._verrou:
            vus = [a for a in self._appareils.values() if maintenant - a.vu < MUET_S]
        return sorted((a.annonce() for a in vus), key=lambda a: (a["depuis"], a["uid"]))

    def _vu(self, uid, maintenant):
        """L'annonce de `uid` s'il s'est annoncé depuis moins de `MUET_S`. Sous le verrou."""
        annonce = self._appareils.get(uid)
        if annonce is None or maintenant - annonce.vu >= MUET_S:
            return None
        return annonce

    def identifier(self, uid):
        """Demande à l'appareil `uid` de se signaler. True si la demande part (au tour suivant)."""
        if self._sock is None:
            return False
        maintenant = self.maintenant()
        with self._verrou:
            annonce = self._vu(uid, maintenant)
            if annonce is None:
                return False
            self._a_envoyer.append(((annonce.ip, annonce.port),
                                    {"v": VERSION, "identify": True}))
        return True

    def connecter(self, uid):
        """Commence la poignée de main avec `uid` : « connect » part au tour suivant. Remplace
        toute connexion en cours, sans rien lui dire (comme `Pilotage.connecter`)."""
        if self._sock is None:
            return False
        maintenant = self.maintenant()
        with self._verrou:
            annonce = self._vu(uid, maintenant)
            if annonce is None:
                return False
            self._lien = _Lien(uid=uid, adresse=(annonce.ip, annonce.port), app=annonce.app)
            self._commandes.clear()
        return True

    def lien(self):
        """Le jeton de la connexion en cours (connectée ou en attente), ou None."""
        return self._lien

    def connecte(self):
        """L'uid de l'appareil connecté (il a répondu « connected »), ou None."""
        lien = self._lien
        return lien.uid if lien is not None and lien.etat == "connecte" else None

    def oublier(self, jeton):
        """Oublie la connexion `jeton`, sans rien dire à l'appareil, si c'est encore elle."""
        with self._verrou:
            if self._lien is jeton and jeton is not None:
                self._lien = None
                self._commandes.clear()

    def envoyer(self, uid, message):
        """Envoie un message du contrat (réponse, échec, et ce que le moteur pousse) à l'appareil
        connecté `uid`, précédé de "v" et d'un "seq" croissant. False s'il n'est pas (ou plus)
        connecté : rien ne part vers un appareil que personne n'a connecté."""
        with self._verrou:
            lien = self._lien
            if lien is None or lien.uid != uid or lien.etat != "connecte":
                return False
            numerote = self._numeroter(message)
        return self._envoyer_brut(lien.adresse, numerote)

    def deconnecter(self, uid, arretes=(), cause="console"):
        """Termine la connexion à `uid` s'il est CONNECTÉ : lui envoie « disconnected » (le
        message du flux LSL, `deconnexion`, avec "v" et "seq"), puis l'oublie. Un appareil qui
        n'a pas encore répondu « connected » n'en reçoit pas : il ne s'est jamais cru
        connecté. `cause=None` : oublié sans message."""
        message = None
        with self._verrou:
            lien = self._lien
            if lien is None or lien.uid != uid or lien.etat != "connecte":
                return False
            self._lien = None
            self._commandes.clear()
            if cause is not None:
                try:
                    message = self._numeroter(deconnexion(lien.app, arretes, cause))
                except Exception as e:  # noqa: BLE001 - un message impossible : oublié quand même
                    _dire(f"[pilotage] message « disconnected » impossible à écrire : "
                          f"{_decrire(e)}")
        if message is not None:
            self._envoyer_brut(lien.adresse, message)
        _dire(f"[pilotage] appareil réseau « {lien.app} » déconnecté ({lien.adresse[0]})")
        return True

    # --- le tour du fil du pilotage --------------------------------------------------------

    def tour(self):
        """Un tour, sans jamais attendre : lire, envoyer ce qui attend, servir les commandes,
        tenir la connexion, oublier les muets. Les commandes passent AVANT la fin d'une
        connexion : un `stop_mode` suivi de `bye` est servi."""
        sock = self._sock
        if sock is None:
            return
        self._lire_tout(sock)
        self._envoyer_en_attente()
        self._servir_commandes()
        self._tenir_le_lien()
        maintenant = self.maintenant()
        with self._verrou:
            for uid in [u for u, a in self._appareils.items() if maintenant - a.vu >= MUET_S]:
                del self._appareils[uid]

    def _lire_tout(self, sock):
        for _ in range(DATAGRAMMES_PAR_TOUR):
            try:
                donnees, source = sock.recvfrom(_LECTURE)
            except (BlockingIOError, InterruptedError):
                return                          # plus rien en attente
            except ConnectionResetError:
                # Windows rend ici un envoi précédent vers un port fermé (un appareil éteint) :
                # ce n'est pas un datagramme, la lecture continue.
                continue
            except OSError as e:
                self._dire_une_fois(f"[pilotage] lecture UDP impossible : {_decrire(e)}")
                return
            try:
                self._recu(donnees, source[0], source[1])
            except Exception as e:  # noqa: BLE001 - un datagramme ne tue pas le fil d'écoute
                self._dire_une_fois(f"[pilotage] datagramme UDP impossible à lire : "
                                    f"{_decrire(e)}")

    def _recu(self, donnees, ip, port):
        """Un datagramme de `ip:port` : un hello, la réponse à « connect », ou un message de
        l'appareil connecté. Tout le reste est ignoré, sans réponse."""
        message = lire_message(donnees)
        if message is None:
            self.ignores += 1
            return
        maintenant = self.maintenant()
        if "hello" in message:
            self._noter_hello(message, ip, maintenant)
            return
        uid = uid_de(ip, port)
        with self._verrou:
            lien = self._lien
            if lien is None or lien.uid != uid:
                if message.get("bye") is True:
                    self._appareils.pop(uid, None)      # il s'arrête : il quitte la liste
                else:
                    self.ignores += 1                   # pas connecté : rien n'est entendu
                return
            if message.get("bye") is True and "cmd" not in message:
                self._appareils.pop(uid, None)
                lien.fin = ("bye", None)
            elif lien.etat == "attente":
                if lien.envoye and "connected" in message:
                    self._reponse_a_connect(lien, message, maintenant)
                else:
                    self.ignores += 1                   # pas encore connecté
            else:
                lien.vu = maintenant                    # tout message valide est signe de vie
                if "cmd" in message or not ("alive" in message or "connected" in message):
                    # Une commande : y compris un objet sans « cmd », que `traiter` refuse en
                    # disant ce qui manque, comme par LSL.
                    self._commandes.append(bytes(donnees))

    def _reponse_a_connect(self, lien, message, maintenant):
        """« connected » : true, la connexion commence ; false, l'appareil est occupé (busy :
        l'hôte de l'autre console). Sous le verrou."""
        reponse = message.get("connected")
        if reponse is True:
            lien.etat = "connecte"
            lien.vu = lien.vie = maintenant         # un premier « alive » part tout de suite
            lien.seau = Seau(maintenant=maintenant)
            _dire(f"[pilotage] appareil réseau connecté : « {lien.app} » ({lien.adresse[0]})")
        elif reponse is False:
            hote = message.get("busy")
            lien.fin = ("occupee", _court(hote) if isinstance(hote, str) else None)

    def _noter_hello(self, message, ip, maintenant):
        """Note l'appareil qui s'annonce, pendant une recherche ou non : la liste, elle, ne le
        montre que pendant une recherche (`Pilotage.annonces`)."""
        port = message.get("port")
        if (message.get("hello") != ANNONCE or isinstance(port, bool)
                or not isinstance(port, int) or not 0 < port < 65536):
            self.ignores += 1
            return
        app = message.get("app") if isinstance(message.get("app"), str) else ""
        ident = message.get("id")
        ident = (None if isinstance(ident, bool) or not isinstance(ident, (str, int))
                 else _court(str(ident)))
        uid = uid_de(ip, port)
        with self._verrou:
            avant = self._vu(uid, maintenant)
            if avant is None and uid not in self._appareils \
                    and len(self._appareils) >= APPAREILS_MAX:
                self.ignores += 1
                return
            depuis = avant.depuis if avant is not None else time.time()
            self._appareils[uid] = _Annonce(uid, ip, port, app, ident, maintenant, depuis)

    def _envoyer_en_attente(self):
        while True:
            with self._verrou:
                if not self._a_envoyer:
                    return
                adresse, message = self._a_envoyer.popleft()
            self._envoyer_brut(adresse, message)

    def _servir_commandes(self):
        """Les commandes de l'appareil connecté, dans les limites d'un tour du pilotage
        (`MAX_PAR_TOUR`, `TEMPS_PAR_FLUX_S`) et de sa limite par seconde."""
        fin = time.monotonic() + TEMPS_PAR_FLUX_S
        for _ in range(MAX_PAR_TOUR):
            if self.pilotage._arret.is_set() or time.monotonic() > fin:
                return
            with self._verrou:
                lien = self._lien
                if lien is None or lien.etat != "connecte" or not self._commandes:
                    return
                # Déconnecté en cours de tour : plus aucune commande, comme par LSL.
                if self.pilotage._choisie != lien.uid:
                    return
                donnees = self._commandes.popleft()
            refus = refus_debit(lien.seau, self.maintenant())
            if refus is None:
                refus = refus_mode_non_servi(donnees)
            self.pilotage.servir(donnees, refus, lien.uid)

    def _tenir_le_lien(self):
        """La poignée de main et la vie de la connexion : envoie « connect » puis attend
        `ATTENTE_CONNEXION_S` ; une fois connecté, un « alive » chaque `VIE_S` et la fin après
        `SILENCE_S` de silence. Une fin est dite au moteur hors du verrou."""
        if self._lien is None:
            return
        maintenant = self.maintenant()
        connect = {"v": VERSION,
                   "connect": str(getattr(self.pilotage.engine, "instance", "") or ""),
                   "host": self.pilotage.hote}
        envoi = fin = None
        with self._verrou:
            lien = self._lien
            if lien is None:
                return
            if lien.fin is not None:
                fin = lien.fin
            elif lien.etat == "attente":
                if not lien.envoye:
                    lien.envoye = True
                    lien.echeance = maintenant + ATTENTE_CONNEXION_S
                    envoi = connect
                elif maintenant >= lien.echeance:
                    fin = ("ne_repond_pas", None)
            elif maintenant - lien.vu >= SILENCE_S:
                fin = ("silence", None)
            elif maintenant >= lien.vie:
                lien.vie = maintenant + VIE_S
                envoi = {"v": VERSION, "alive": True}
            if fin is not None:
                self._lien = None
                self._commandes.clear()
        if envoi is not None:
            self._envoyer_brut(lien.adresse, envoi)
        if fin is not None:
            raison, hote = fin
            _dire(f"[pilotage] appareil réseau « {lien.app} » ({lien.adresse[0]}) : fin de la "
                  f"connexion ({raison})")
            self.pilotage._application_partie(lien.uid, raison=raison, hote=hote)

    # --- l'envoi -----------------------------------------------------------------------------

    def _numeroter(self, message):
        """`message` précédé de "v" et du "seq" suivant. Sous le verrou."""
        self._seq += 1
        return {"v": VERSION, "seq": self._seq, **message}

    def _envoyer_brut(self, adresse, message):
        """Un datagramme JSON en ASCII (les accents en « \\u00e9 »), comme le flux de réponses.
        Ne lève jamais."""
        sock = self._sock
        if sock is None:
            return False
        try:
            donnees = json.dumps(message, default=_en_json).encode("ascii")
            if len(donnees) > TAILLE_MAX:
                self._dire_une_fois(f"[pilotage] message UDP de {len(donnees)} octets : plus de "
                                    f"{TAILLE_MAX}, l'appareil peut l'ignorer")
            sock.sendto(donnees, adresse)
        except Exception as e:  # noqa: BLE001 - un envoi impossible ne tue pas le fil
            self._dire_une_fois(f"[pilotage] envoi UDP impossible vers {adresse[0]}:"
                                f"{adresse[1]} ({_decrire(e)})")
            return False
        self.envoyes += 1
        return True

    def _dire_une_fois(self, texte):
        """Un défaut au terminal, une fois de suite : un défaut qui se répète à chaque tour ne
        noie pas le terminal."""
        if texte != self._dernier_dit:
            self._dernier_dit = texte
            _dire(texte)


# --- Autotest ------------------------------------------------------------------------------------

class _FauxAppareil:
    """Un faux appareil réseau : une socket UDP sur 127.0.0.1, qui parle le protocole à la main
    (hello, connected, alive, commandes, bye) et lit ce que le moteur lui envoie."""

    def __init__(self, app, ident, port_moteur):
        self.app, self.ident = app, ident
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.02)
        self.port = self.sock.getsockname()[1]
        self.uid = uid_de("127.0.0.1", self.port)
        self.moteur = ("127.0.0.1", port_moteur)
        self.seqs = []          # chaque « seq » reçu, dans l'ordre d'arrivée

    def envoyer(self, message):
        """Envoie un dict (en JSON UTF-8) ou des octets tels quels ; rend les octets envoyés."""
        donnees = (bytes(message) if isinstance(message, (bytes, bytearray))
                   else json.dumps(message).encode("utf-8"))
        self.sock.sendto(donnees, self.moteur)
        return donnees

    def hello(self):
        return self.envoyer({"v": VERSION, "hello": ANNONCE, "app": self.app, "id": self.ident,
                             "port": self.port})

    def recevoir(self, n=1, delai_s=1.0, garder=None):
        """Jusqu'à `n` messages gardés par `garder` (tous, sans lui), en `delai_s` secondes au
        plus : des paires (texte reçu, dict). Les autres messages sont lus et laissés de côté."""
        gardes, echeance = [], time.perf_counter() + delai_s
        while len(gardes) < n and time.perf_counter() < echeance:
            try:
                donnees, _source = self.sock.recvfrom(65536)
            except (socket.timeout, ConnectionResetError):
                continue
            texte = donnees.decode("ascii")
            message = json.loads(texte)
            if "seq" in message:
                self.seqs.append(message["seq"])
            if garder is None or garder(message):
                gardes.append((texte, message))
        return gardes

    def messages(self, n=1, delai_s=1.0, garder=None):
        return [m for _texte, m in self.recevoir(n, delai_s, garder)]

    def vider(self):
        self.recevoir(1000, 0.05)

    def fermer(self):
        self.sock.close()


def _sans_v_seq(message):
    return {k: v for k, v in message.items() if k not in ("v", "seq")}


def _selftest():
    import traceback

    from core.i18n import choisir_langue, joint, nombre, pour_le_contrat
    from core.lsl_io import NOM_FLUX_COMMANDES
    from core.modes import registry
    from core.pilotage import FauxMoteur, Pilotage, echec

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    def interrompu(section, e):
        """Une exception dans une section est un ÉCHEC dit, pas un autotest qui plante."""
        traceback.print_exc()
        chk(False, f"{section} : interrompu sur une exception ({e!r})")

    def attendre(cond, delai_s=2.0):
        echeance = time.perf_counter() + delai_s
        while not cond() and time.perf_counter() < echeance:
            time.sleep(0.01)
        return cond()

    class _Horloge:
        """L'horloge injectée du transport : elle n'avance que quand le test le dit. Les délais
        (3 s, 5 s, 1 s) se vérifient ainsi sans attendre, et sans dépendre du rythme du fil."""

        def __init__(self):
            self.t = 1000.0

        def __call__(self):
            return self.t

        def avancer(self, dt):
            self.t += dt

    langue_avant = os.environ.get("EEG_LANGUE")
    # L'écran en français : tout ce qui part vers l'appareil doit rester en anglais.
    choisir_langue("fr")
    debut = time.perf_counter()
    pid = os.getpid()
    try:
        # 1. Lire un datagramme : un objet JSON de la version 1, au plus 8 Ko.
        chk(lire_message(b'{"v": 1, "alive": true}') == {"v": 1, "alive": True},
            "un objet JSON de la version 1 est lu")
        base = b'{"v": 1, "p": ""}'
        juste = b'{"v": 1, "p": "' + b"a" * (TAILLE_MAX - len(base)) + b'"}'
        chk(len(juste) == TAILLE_MAX and lire_message(juste) is not None
            and lire_message(juste[:-2] + b'a"}') is None,
            f"{TAILLE_MAX} octets passent, un de plus est ignoré")
        ignores = (b"pas du json", b"[1]", b"\xff\xfe\x00", b'{"alive": true}',
                   b'{"v": 2, "alive": true}', b'{"v": true, "alive": true}',
                   b'{"v": "1", "alive": true}', "texte, pas des octets")
        chk(all(lire_message(d) is None for d in ignores),
            "ignorés : pas du JSON, pas un objet, sans « v », une autre version, « v » booléen "
            "ou texte")

        # 2. Les modes servis par le réseau : SSVEP, Motor Imagery, Neuro.
        ids = {s.id for s in registry.MODES}
        chk(set(MODES_SERVIS) <= ids and ids - set(MODES_SERVIS) == {"p300", "errp", "cvep", "raw"},
            f"les modes servis existent, et ceux qui ne le sont pas sont P300, ErrP, c-VEP et le "
            f"Brut ({sorted(ids - set(MODES_SERVIS))})")
        refuses = []
        for cmd, mode in (("start_mode", "p300"), ("set_params", "raw"), ("start_mode", "errp"),
                          ("set_params", "cvep")):
            r = refus_mode_non_servi(json.dumps({"v": 1, "cmd": cmd, "mode": mode}).encode())
            refuses.append((getattr(r, "cle", None), pour_le_contrat(r) if r is not None else ""))
        chk(all(cle == "moteur.reseau.mode_non_servi" and f'"{m}"' in en
                and "ssvep, mi, neuro" in en and en.isascii()
                for (cle, en), m in zip(refuses, ("p300", "raw", "errp", "cvep"))),
            f"start_mode / set_params d'un mode non servi : refusé, la raison en anglais nomme le "
            f"mode et les modes servis ({refuses[0][1]!r})")
        passent = ('{"v": 1, "cmd": "start_mode", "mode": "ssvep"}',
                   '{"v": 1, "cmd": "stop_mode", "mode": "p300"}',
                   '{"v": 1, "cmd": "propose_params", "mode": "cvep"}',
                   '{"v": 1, "cmd": "start_mode", "mode": "inconnu"}',
                   '{"v": 1, "cmd": "set_params", "mode": 3}')
        chk(all(refus_mode_non_servi(t.encode()) is None for t in passent),
            "passent sans ce refus : un mode servi, stop_mode et propose_params, un mode INCONNU "
            "et un mode mal typé (le moteur les refuse alors pour leur propre raison, comme par "
            "LSL)")

        # Le même faux moteur pour le transport et pour la référence : une commande reçue par UDP
        # doit donner la réponse que `Pilotage.traiter` donne à la même commande.
        def accuses():
            reserve = joint(" ", [tr("moteur.contrat.flux_pas_vu", reglage="stream_in",
                                     nom=f"Absent_{pid}")])
            raison = tr("moteur.contrat.au_dessus_maximum", reglage=tr("moteur.bande.bas"),
                        valeur=nombre(240.5), borne=nombre(120.25))
            return {
                "set_params": {"accepted": True, "command": "set_params", "id": "ssvep",
                               "params": {"refresh_hz": 30.0}, "differe": True,
                               "warning": reserve},
                "start_mode": {"accepted": True, "command": "start_mode", "ids": ["ssvep"],
                               "deja": ["ssvep"], "warning": None},
                "stop_mode": {"accepted": True, "command": "stop_mode", "id": "ssvep",
                              "deja": True},
                "propose_params": {"accepted": False, "reason": raison}}

        horloge = _Horloge()
        faux = FauxMoteur(f"autotest-udp-{pid}")
        faux.accuses = accuses()
        faux_ref = FauxMoteur(f"autotest-udp-ref-{pid}")
        faux_ref.accuses = accuses()
        nom = f"{NOM_FLUX_COMMANDES}_autotest_udp_{pid}"
        pil = Pilotage(faux, nom_flux=nom, ecoute="sur_demande")
        ref = Pilotage(faux_ref, nom_flux=nom, ecoute="sur_demande")    # jamais démarré
        autres = []                         # les Pilotage et transports à refermer à la fin
        appareils = []

        def appareil(app, ident):
            a = _FauxAppareil(app, ident, pil._udp.port)
            appareils.append(a)
            return a

        def uids():
            return [a["uid"] for a in pil.annonces()]

        def connecter(a):
            """Recherche, hello, « Connecter », connect reçu, connected : l'appareil `a` est
            branché. Rend le message « connect » reçu."""
            pil.chercher(True)
            a.hello()
            attendre(lambda: a.uid in uids())
            nom_rendu = pil.connecter(a.uid)
            recu = a.messages(1, 1.0, garder=lambda m: "connect" in m)
            a.envoyer({"v": 1, "connected": True})
            attendre(pil.branchee)
            return nom_rendu, recu

        try:
            # 3. Ouvrir la socket ; le port pris ; l'écoute permanente n'en ouvre aucune.
            chk(pil.ouvrir_udp(port=0, adresse="127.0.0.1", maintenant=horloge) is None
                and pil.etat_udp() == {"ouvert": True, "raison": None, "port": pil._udp.port},
                f"la socket UDP s'ouvre sur un port de test ({pil.etat_udp()})")
            port = pil._udp.port
            chk(port > 0 and port != PORT_UDP, f"...un port libre, jamais {PORT_UDP} ({port})")
            pris = Pilotage(FauxMoteur(f"autotest-udp-pris-{pid}"), nom_flux=nom,
                            ecoute="sur_demande")
            autres.append(pris)
            raison = pris.ouvrir_udp(port=port, adresse="127.0.0.1")
            chk(getattr(raison, "cle", None) == "moteur.reseau.udp_port_pris"
                and str(port) in str(raison)
                and pris.etat_udp() == {"ouvert": False, "raison": raison, "port": None},
                f"un port déjà pris (une seconde console) : pas de socket, et la raison le dit "
                f"({raison!r})")
            mauvaise = TransportUDP(pil, port=0, adresse="256.0.0.1")
            raison = mauvaise.ouvrir()
            chk(getattr(raison, "cle", None) == "moteur.reseau.udp_indisponible"
                and not mauvaise.ouvert,
                f"une adresse impossible : pas de socket, la raison donne l'erreur ({raison!r})")
            permanent = Pilotage(FauxMoteur(f"autotest-udp-perm-{pid}"), nom_flux=nom)
            autres.append(permanent)
            chk(permanent.ouvrir_udp(port=0, adresse="127.0.0.1") is None
                and permanent._udp is None
                and permanent.etat_udp() == {"ouvert": False, "raison": None, "port": None},
                "en écoute permanente (server.py seul), aucune socket UDP n'est ouverte")

            # 4. La liste : seulement pendant une recherche ; deux appareils au même programme ;
            # « Identifier » ; un appareil muet depuis 5 s sort de la liste.
            chk(pil.demarrer() and pil.vivant, "le fil d'écoute du pilotage démarre")
            a1, a2 = appareil("jeu-led", "A1B2"), appareil("jeu-led", "C3D4")
            a1.hello()
            chk(attendre(lambda: any(d["uid"] == a1.uid for d in pil._udp.appareils()))
                and pil.annonces() == [],
                "hors recherche : le hello est lu par le fil du pilotage, mais rien n'est listé")
            pil.chercher(True)
            a2.hello()
            attendre(lambda: len(pil.annonces()) >= 2)
            vues = {a["uid"]: a for a in pil.annonces()}
            e1 = vues.get(a1.uid, {})
            chk(e1 == {"uid": a1.uid, "nom": "jeu-led", "id": "A1B2",
                       "adresse": f"127.0.0.1:{a1.port}", "machine": "127.0.0.1",
                       "origine": "udp", "depuis": e1.get("depuis"), "illisible": False}
                and isinstance(e1.get("depuis"), float) and e1["depuis"] > 0,
                f"pendant une recherche, l'appareil est listé : nom, identifiant, adresse, "
                f"machine (son IP), origine « udp » ({e1})")
            chk(set(vues) == {a1.uid, a2.uid} and vues.get(a2.uid, {}).get("id") == "C3D4"
                and vues[a1.uid]["adresse"] != vues.get(a2.uid, {}).get("adresse"),
                f"deux appareils au même programme : deux lignes, chacune avec son identifiant "
                f"et son adresse ({sorted(vues)})")
            chk(pil.identifier(a2.uid) is True
                and a2.messages(1, 1.0) == [{"v": 1, "identify": True}]
                and a1.messages(1, 0.3) == [],
                "« Identifier » : seul l'appareil visé reçoit {\"v\": 1, \"identify\": true}")
            chk(not pil.identifier(uid_de("127.0.0.1", 9)) and not pil.identifier("lsl-uid"),
                "...un appareil inconnu, ou une application LSL, ne s'identifie pas")
            x = appareil("parti", "X")
            x.hello()
            attendre(lambda: x.uid in uids())
            x.fermer()
            # Windows rend l'envoi vers un port fermé en erreur sur la LECTURE suivante
            # (WSAECONNRESET) : elle ne doit pas arrêter la lecture des autres appareils.
            pil.identifier(x.uid)
            horloge.avancer(MUET_S + 0.1)
            a2.hello()
            # 1 s au plus : un défaut qui sortirait de `tour()` ferait attendre le fil 2 s.
            chk(attendre(lambda: uids() == [a2.uid], 1.0),
                f"un appareil muet depuis {MUET_S:g} s sort de la liste ; celui qui s'annonce "
                f"reste, même après un envoi vers une socket fermée ({uids()})")
            chk(not pil.identifier(a1.uid), "...un appareil sorti de la liste ne s'identifie pas")
            a1.hello()
            chk(attendre(lambda: a1.uid in uids()), "...et il revient à son hello suivant")
            pil.chercher(False)
            a1.hello()
            time.sleep(0.1)
            chk(pil.annonces() == [] and any(d["uid"] == a1.uid for d in pil._udp.appareils()),
                "la recherche arrêtée : plus rien n'est listé, même si les hello arrivent")

            # 5. Connect, connected, puis les commandes : les réponses de `Pilotage.traiter`.
            a2.vider()
            n_appels = len(faux.appels)
            publiees_lsl = pil.publiees
            pil.chercher(True)
            a1.hello()
            attendre(lambda: a1.uid in uids())
            chk(pil.connecter(a1.uid) == "jeu-led" and pil.annonces() == [],
                "« Connecter » rend le nom de l'appareil et arrête la recherche")
            recu = a1.messages(1, 1.0)
            chk(recu == [{"v": 1, "connect": faux.instance, "host": pil.hote}],
                f"l'appareil reçoit connect, avec l'instance du moteur et le nom du PC ({recu})")
            chk(not pil.branchee(), "...pas encore branché : il n'a pas répondu")
            a1.envoyer({"v": 1, "cmd": "stop_mode", "mode": "ssvep", "ref": "trop-tot"})
            chk(a1.messages(1, 0.3) == [] and len(faux.appels) == n_appels,
                "une commande avant « connected » est ignorée, sans réponse")
            a1.envoyer({"v": 1, "connected": True})
            chk(attendre(pil.branchee), "connected : l'appareil est branché")
            a1.vider()
            datagrammes = [
                a1.envoyer({"v": 1, "cmd": "set_params", "mode": "ssvep", "params": {},
                            "ref": "u1"}),
                a1.envoyer({"v": 1, "cmd": "start_mode", "mode": "ssvep", "ref": "u2"}),
                a1.envoyer({"v": 1, "cmd": "propose_params", "mode": "ssvep", "ref": "u3"}),
                a1.envoyer({"v": 1, "mode": "ssvep", "ref": "u4"}),
                a1.envoyer({"v": 1, "cmd": "set_params", "mode": 3, "ref": "u5"}),
                a1.envoyer('{"v": 1, "cmd": "set_params", "mode": "ssvep", "params": '
                           '{"target_names": ["élève"]}, "ref": "u6"}'.encode("cp1252"))]
            recues = a1.recevoir(6, 3.0, garder=lambda m: "ref" in m)
            attendues = [ref.traiter(d) for d in datagrammes]
            chk([_sans_v_seq(m) for _t, m in recues] == attendues,
                f"six commandes (acceptées, refusées, illisibles, pas de l'UTF-8) : six réponses "
                f"identiques à celles de `Pilotage.traiter`, hors « v » et « seq » "
                f"({[m.get('ref') for _t, m in recues]})")
            chk(len(recues) == 6 and all(
                t == json.dumps({"v": 1, "seq": m["seq"], **att}, default=_en_json)
                for (t, m), att in zip(recues, attendues)),
                "...octet pour octet : le JSON de la réponse LSL, précédé de « v » et « seq »")
            chk(any(a[1] == ("u1", "set_params", "ssvep") for a in faux.appels)
                and len(faux.appels) == n_appels + 3,
                f"seules les trois commandes lisibles vont au moteur, avec leur jeton réseau "
                f"({len(faux.appels) - n_appels})")
            chk(pil.publiees == publiees_lsl,
                "rien n'est parti sur le flux LSL de réponses : tout est allé à l'appareil")

            # Les modes que le réseau ne sert pas : refusés, rien n'est soumis.
            n_appels = len(faux.appels)
            for i, (cmd, mode) in enumerate((("start_mode", "p300"), ("set_params", "raw"),
                                             ("start_mode", "errp"), ("set_params", "cvep"),
                                             ("start_mode", "raw"))):
                a1.envoyer({"v": 1, "cmd": cmd, "mode": mode, "ref": f"n{i}"})
            recues = a1.messages(5, 2.0, garder=lambda m: str(m.get("ref")).startswith("n"))
            chk(len(recues) == 5 and len(faux.appels) == n_appels
                and all(m.get("accepted") is False and f'"{m.get("mode")}"' in m.get("reason", "")
                        and "ssvep, mi, neuro" in m["reason"] and m["reason"].isascii()
                        for m in recues),
                f"P300, ErrP, c-VEP et le Brut : refusés avec leur raison en anglais, rien n'est "
                f"soumis au moteur ({recues[:1]})")
            refus_au_journal = [e for e in pil.journal()
                                if getattr(e.get("raison"), "cle", None)
                                == "moteur.reseau.mode_non_servi"]
            chk(len(refus_au_journal) == 5,
                f"...et ces refus sont au journal de la console, comme une commande LSL "
                f"({len(refus_au_journal)})")

            # Un échec après acceptation part, lui aussi, vers l'appareil.
            faux.rappel = pil.signaler_echec
            a1.envoyer({"v": 1, "cmd": "set_params", "mode": "ssvep", "params": {},
                        "ref": "vite"})
            recues = a1.messages(2, 2.0, garder=lambda m: m.get("ref") == "vite")
            faux.rappel = None
            chk(len(recues) == 2 and recues[0].get("accepted") is True
                and _sans_v_seq(recues[1]) == echec("vite", "set_params", "ssvep",
                                                    tr("moteur.refus.aucun_mode_demande")),
                f"un échec après acceptation (« event »: « failed ») suit la réponse, par UDP "
                f"({[m.get('event', m.get('accepted')) for m in recues]})")

            # La limite par seconde : la même que par LSL.
            horloge.avancer(2.0)                 # le seau se remplit : 20 jetons au plus
            a1.vider()
            for i in range(25):
                a1.envoyer({"v": 1, "cmd": "stop_mode", "mode": "ssvep", "ref": f"r{i}"})
            recues = a1.messages(25, 3.0, garder=lambda m: str(m.get("ref")).startswith("r"))
            trop = [m for m in recues if m.get("accepted") is False
                    and "Too many commands" in (m.get("reason") or "")]
            chk(len(recues) == 25 and len(trop) == 5
                and [m["ref"] for m in recues] == [f"r{i}" for i in range(25)],
                f"une rafale de 25 commandes : 20 servies, 5 refusées (« Too many commands »), "
                f"dans l'ordre ({len(recues)} réponses, {len(trop)} refus)")

            # Le signe de vie : un « alive » par seconde vers l'appareil ; le sien le garde.
            a1.vider()
            vies = []
            for _ in range(6):
                horloge.avancer(1.0)
                a1.envoyer({"v": 1, "alive": True})
                vies.append(a1.messages(1, 1.0, garder=lambda m: "alive" in m))
            chk(vies == [[{"v": 1, "alive": True}]] * 6,
                f"un « alive » par seconde vers l'appareil, sans « seq » ({vies[:2]})")
            chk(a1.messages(1, 0.3, garder=lambda m: "alive" in m) == [] and pil.branchee(),
                "...pas plus d'un par seconde ; et ses « alive » le gardent branché au-delà de "
                f"{SILENCE_S:g} s")

            # Ce qui est ignoré : illisible, trop gros, d'un autre appareil. Le fil survit.
            n_appels = len(faux.appels)
            a2.vider()
            gros = json.dumps({"v": 1, "cmd": "stop_mode", "mode": "ssvep", "ref": "gros",
                               "bourrage": "x" * TAILLE_MAX}).encode()
            for d in (b"pas du json", b"[1]", b"\xff\xfe\x00", gros,
                      b'{"cmd": "stop_mode", "mode": "ssvep", "ref": "sans-v"}',
                      b'{"v": 2, "cmd": "stop_mode", "mode": "ssvep", "ref": "v2"}'):
                a1.envoyer(d)
            a2.envoyer({"v": 1, "cmd": "start_mode", "mode": "ssvep", "ref": "pas-connecte"})
            inconnu = appareil("inconnu", "Z")
            inconnu.envoyer({"v": 1, "cmd": "start_mode", "mode": "ssvep", "ref": "inconnu"})
            a1.envoyer({"v": 1, "cmd": "stop_mode", "mode": "ssvep", "ref": "apres"})
            recues = a1.messages(3, 1.0, garder=lambda m: "ref" in m)
            chk([m.get("ref") for m in recues] == ["apres"] and len(faux.appels) == n_appels + 1
                and a2.messages(1, 0.2) == [] and inconnu.messages(1, 0.2) == []
                and pil.vivant,
                f"JSON illisible, plus de {TAILLE_MAX} octets, sans « v » ou d'une autre version, "
                f"commande d'un appareil NON connecté : ignorés, aucune commande exécutée ; le "
                f"fil répond encore ({[m.get('ref') for m in recues]})")

            # Ce que le moteur pousse (status, décisions) part vers l'appareil connecté, par le
            # fil du pilotage, numéroté comme le reste.
            a1.vider()
            decision = {"decision": {"mode": "ssvep", "target_index": -1.0}}
            pousse = pil.pousser(decision)
            recues = a1.messages(1, 1.0, garder=lambda m: "decision" in m)
            chk(pousse and len(recues) == 1 and _sans_v_seq(recues[0]) == decision
                and recues[0].get("v") == 1 and isinstance(recues[0].get("seq"), int),
                f"ce que le moteur pousse part vers l'appareil connecté, avec « v » et « seq » "
                f"({recues})")

            # « Déconnecter » : l'appareil reçoit « disconnected », puis plus rien.
            a1.vider()
            pil.deconnecter(arretes=("ssvep",))
            recues = a1.messages(1, 2.0, garder=lambda m: m.get("event") == "disconnected")
            chk(len(recues) == 1
                and _sans_v_seq(recues[0]) == deconnexion("jeu-led", ("ssvep",), "console")
                and recues[0].get("v") == 1,
                f"« Déconnecter » : « disconnected », le message du flux LSL, plus « v » et "
                f"« seq » ({recues})")
            chk(attendre(lambda: not pil.branchee()) and faux.fins == [],
                "...l'appareil n'est plus branché ; une déconnexion demandée n'est pas un départ")
            chk(not pil.pousser({"status": {"phase": "idle", "modes": {}}})
                and len(pil._poussees) == 0,
                "...ce que le moteur pousse ensuite est jeté : rien n'est gardé pour plus tard")
            horloge.avancer(1.5)
            a1.envoyer({"v": 1, "cmd": "stop_mode", "mode": "ssvep", "ref": "apres-fin"})
            chk(a1.messages(1, 0.4) == [],
                "...après : ni « alive », ni réponse à ses commandes")
            chk(len(a1.seqs) > 30 and all(b > a for a, b in zip(a1.seqs, a1.seqs[1:])),
                f"chaque message numéroté a un « seq » strictement croissant ({len(a1.seqs)} "
                f"messages, de {a1.seqs[:1]} à {a1.seqs[-1:]})")

            # 6. Les fins de la poignée de main : occupé, puis sans réponse en 3 s.
            pil.chercher(True)
            a2.hello()
            attendre(lambda: a2.uid in uids())
            chk(pil.connecter(a2.uid) == "jeu-led"
                and len(a2.messages(1, 1.0, garder=lambda m: "connect" in m)) == 1,
                "un second appareil reçoit connect")
            a2.envoyer({"v": 1, "connected": False, "busy": "AUTRE-PC"})
            chk(attendre(lambda: faux.fins[-1:] == [(a2.uid, "occupee", "AUTRE-PC")])
                and pil._choisie is None and not pil.branchee(),
                f"« busy » : le moteur apprend que l'appareil est occupé, et par quelle machine "
                f"({faux.fins})")
            pil.chercher(True)
            a2.hello()
            attendre(lambda: a2.uid in uids())
            pil.connecter(a2.uid)
            a2.messages(1, 1.0, garder=lambda m: "connect" in m)
            pil.deconnecter(arretes=("ssvep",))
            chk(a2.messages(1, 0.3, garder=lambda m: m.get("event") == "disconnected") == []
                and attendre(lambda: pil._udp.lien() is None) and len(faux.fins) == 1,
                "« Déconnecter » pendant la poignée de main : la connexion en attente est oubliée, "
                "sans « disconnected » (l'appareil n'a jamais répondu « connected »)")
            pil.chercher(True)
            a2.hello()
            attendre(lambda: a2.uid in uids())
            pil.connecter(a2.uid)
            a2.messages(1, 1.0, garder=lambda m: "connect" in m)
            horloge.avancer(ATTENTE_CONNEXION_S - 0.2)
            time.sleep(0.15)
            chk(pil._choisie == a2.uid and len(faux.fins) == 1,
                f"avant {ATTENTE_CONNEXION_S:g} s sans réponse, le moteur attend encore")
            horloge.avancer(0.4)
            chk(attendre(lambda: faux.fins[-1:] == [(a2.uid, "ne_repond_pas", None)])
                and pil._choisie is None,
                f"{ATTENTE_CONNEXION_S:g} s sans réponse : « ne répond pas » ({faux.fins[-1:]})")
            a2.envoyer({"v": 1, "connected": True})
            horloge.avancer(1.0)
            chk(a2.messages(1, 0.3, garder=lambda m: "alive" in m) == [] and not pil.branchee(),
                "...un « connected » en retard est ignoré : pas de connexion, pas d'« alive »")

            # 7. L'appareil redémarre pendant la connexion : plus d'alive, de nouveaux hello.
            connecter(a1)
            chk(pil.branchee(), "l'appareil est connecté à nouveau")
            for _ in range(4):
                horloge.avancer(1.0)
                a1.hello()
                time.sleep(0.05)
            chk(pil.branchee() and len(faux.fins) == 2,
                f"4 s sans « alive » (des hello seulement) : encore connecté ({faux.fins[2:]})")
            horloge.avancer(1.1)
            a1.hello()
            chk(attendre(lambda: faux.fins[-1:] == [(a1.uid, "silence", None)])
                and pil._choisie is None,
                f"{SILENCE_S:g} s sans signe de vie (un hello n'en est pas un) : application "
                f"partie ({faux.fins[-1:]})")
            pil.chercher(True)
            horloge.avancer(1.0)
            a1.hello()
            chk(attendre(lambda: a1.uid in uids()), "...il reparaît dans la liste")
            chk(a1.messages(1, 0.3, garder=lambda m: "connect" in m) == []
                and pil._choisie is None and not pil.branchee(),
                "...et il n'est PAS reconnecté tout seul")
            pil.chercher(False)

            # 8. bye : la fin immédiate ; un appareil listé qui dit bye quitte la liste.
            connecter(a1)
            n_fins = len(faux.fins)
            a1.vider()
            a1.envoyer({"v": 1, "bye": True})
            chk(attendre(lambda: faux.fins[n_fins:] == [(a1.uid, "bye", None)], 1.0)
                and not pil.branchee(),
                f"« bye » : application partie tout de suite, sans attendre {SILENCE_S:g} s "
                f"({faux.fins[n_fins:]})")
            chk(a1.messages(1, 0.3, garder=lambda m: m.get("event") == "disconnected") == [],
                "...et elle ne reçoit pas « disconnected » : elle ne lit plus rien")
            pil.chercher(True)
            a2.hello()
            attendre(lambda: a2.uid in uids())
            a2.envoyer({"v": 1, "bye": True})
            chk(attendre(lambda: a2.uid not in uids()),
                "un appareil listé qui dit « bye » quitte la liste tout de suite")
            pil.chercher(False)

            # 9. L'arrêt du MOTEUR pendant une connexion : « disconnected », cause
            # « engine_stopped ».
            connecter(a1)
            a1.vider()
            pil.annoncer_arret(("ssvep", "raw"))
            chk(pil.arreter(), "le fil d'écoute s'arrête")
            recues = a1.messages(1, 1.0, garder=lambda m: m.get("event") == "disconnected")
            chk(len(recues) == 1 and _sans_v_seq(recues[0])
                == deconnexion("jeu-led", ("ssvep", "raw"), "engine_stopped"),
                f"...l'appareil connecté reçoit « disconnected », cause « engine_stopped » "
                f"({recues})")

            # 10. Un appareil UDP choisi n'est pas une application LSL : le fil ne cherche pas
            # son flux, et ne le croit pas parti parce qu'aucun flux LSL ne porte son uid.
            class _Resolveur:
                def results(self):
                    return []

            pil._choisie = a1.uid
            chk(pil._doit_chercher() is False,
                "un appareil UDP choisi ne fait pas chercher les flux LSL")
            n_fins = len(faux.fins)
            pil._decouvrir(_Resolveur(), {}, {}, cree_a=None)
            chk(len(faux.fins) == n_fins and pil._choisie == a1.uid,
                "...et l'absence de flux LSL ne le fait pas passer pour parti")
            pil._choisie = None

            # 11. Refermer : la socket est rendue.
            pil.fermer()
            chk(pil.etat_udp() == {"ouvert": False, "raison": None, "port": None},
                "fermer() referme aussi la socket UDP")
            reprise = TransportUDP(pil, port=port, adresse="127.0.0.1")
            chk(reprise.ouvrir() is None, "...et le port est libre à nouveau")
            reprise.fermer()
        except Exception as e:  # noqa: BLE001
            interrompu("transport UDP", e)
        finally:
            for a in appareils:
                try:
                    a.fermer()
                except OSError:
                    pass
            for p in [pil, ref, *autres]:
                p.arreter()
                p.fermer()

        restants = [t.name for t in threading.enumerate() if t.name.startswith("pilotage")]
        chk(restants == [], f"aucun fil d'écoute ne reste vivant ({restants})")
        duree = time.perf_counter() - debut
        chk(duree < 30.0, f"l'autotest dure moins de 30 s ({duree:.1f} s)")
    finally:
        if langue_avant is None:
            os.environ.pop("EEG_LANGUE", None)
        else:
            os.environ["EEG_LANGUE"] = langue_avant

    print(f"[pilotage_udp] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    # Lancé en script, ce fichier est le module `__main__` ; le pilotage, lui, importe
    # `core.pilotage_udp`. L'autotest tourne dans CE second module, pour qu'il n'en existe qu'un.
    from core.pilotage_udp import _selftest as _autotest
    sys.exit(0 if _autotest() else 1)
