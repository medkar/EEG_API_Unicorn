"""Moteur headless : casque Unicorn -> flux LSL.

Ce fichier est le **cœur du produit** : il tourne SANS interface graphique. La console PySide6,
les fenêtres de `src/stimulus/` et le code d'un étudiant sont tous, du point de vue du moteur,
des clients — les uns écoutent ses flux, les autres lui envoient des marqueurs.

Le moteur ne garde que le **vraiment commun** : la session BrainFlow, le tampon glissant, le pont
d'horloge, la qualité du signal, la file de commandes. Tout le reste — la séquence chauffe /
repos / décodage, ce qui se règle, ce qui se publie — vit dans `src/core/modes/` : un
`ModeRuntime` par mode actif, tenu dans `self.active`. Plusieurs modes tournent EN MÊME TEMPS,
chacun à sa propre phase ; lancés ENSEMBLE ils partagent une seule mesure de repos
(`_begin_shared_rest`), lancés séparément chacun fait la sienne.

Ce qu'il publie aujourd'hui :
    EEG_API_Unicorn_raw            les 8 voies, µV, 250 Hz (mode "raw", actif par défaut)
    EEG_API_Unicorn_quality        σ par voie, ~1 Hz (électrode décollée ?) — toujours publié
    EEG_API_Unicorn_status         état du moteur, JSON, à chaque changement + périodique — idem
    EEG_API_Unicorn_decoded_ssvep  cible regardée, ~5 Hz (mode "ssvep")
    EEG_API_Unicorn_decoded_neuro  charge / somnolence / engagement, ~5 Hz (mode "neuro")
    EEG_API_Unicorn_decoded_mi     intention gauche/droite/repos, ~5 Hz (mode "mi")
    EEG_API_Unicorn_decoded_p300   cible sélectionnée, UN échantillon par manche (mode "p300")
    EEG_API_Unicorn_replies        une réponse JSON par commande reçue du réseau — toujours publié

Et ce qu'il ÉCOUTE (docs/markers.md) :
    EEG_API_Unicorn_stim           marqueurs entrants d'une application externe (mode "p300")
    EEG_API_Unicorn_control        commandes d'une application (core/pilotage.py) : de CETTE
                                   machine pour le moteur seul, de tout le réseau pour la console
    port UDP 5010                  appareils réseau qui ne parlent pas LSL (console seulement,
                                   core/pilotage_udp.py)

SSVEP et neuro illustrent les deux familles de la BCI, et un client ne doit pas les traiter
pareil : le SSVEP est **actif** (l'utilisateur choisit, il y a une bonne réponse, un stimulus est
requis côté client), le neuro est **passif** (on observe un état, il n'y a rien à choisir et
aucun stimulus). Le MI est actif lui aussi, mais SANS stimulus (il est endogène) — en échange, il
exige un modèle ENTRAÎNÉ propre à la personne, là où le SSVEP décode sans calibration : sans
modèle, le mode refuse de démarrer plutôt que de publier des probabilités qui ne veulent rien dire.
Le P300 est actif ET évoqué : il exige un modèle entraîné (comme le MI) **et** que l'application
cliente dise au moteur QUAND chaque cible s'est allumée — c'est à ça que sert le flux entrant.

Le moteur publie les SIX modes et joue les QUATRE calibrations — voir `src/core/modes/registry.py`
pour le catalogue complet. Une application de la MÊME machine peut régler, démarrer et arrêter un
mode par le réseau (`core/pilotage.py`, exemple : `examples/control_client.py`) ; les entraînements
restent dans la console. Les MARQUEURS entrants existent aussi : le moteur ouvre un inlet LSL dès
qu'un mode qui en consomme démarre (`core/markers.py`), et le contrat public de ces marqueurs est
dans `docs/markers.md`.

⚠️ Le moteur ne rend AUCUN stimulus. Pour le SSVEP, c'est l'application cliente qui fait
clignoter les cibles ; elle déclare simplement leurs fréquences au moteur (`--freqs`). Le
couplage est lâche — aucune synchronisation à la frame n'est nécessaire, contrairement au
c-VEP.

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
    python src/stimulus/ssvep.py --windowed --refresh 60        # les cibles clignotent
    python src/core/server.py --mode ssvep --refresh 60         # décode et trace en console
Un troisième terminal montre ce que reçoit un vrai client :
    python -u examples/receiver.py --stream decoded_ssvep

Même montage pour le P300, à ceci près que le stimulus PARLE au moteur (il publie l'onset de
chaque flash sur `EEG_API_Unicorn_stim`) et qu'un modèle entraîné est exigé :
    python src/stimulus/p300.py --windowed  # affiche et MARQUE (n'ouvre pas le casque)
    python src/core/server.py --mode p300            # découpe sur les marqueurs et décide
"""

import argparse
import collections
import dataclasses
import json
import math
import os
import queue
import re
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time
import types
import weakref

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.acquisition import NOTCH_SECTEUR, UnicornAcquisition  # noqa: E402
from core.config import (ALPHA_DEFAUT_HZ, CALIB_TMP_PREFIX, CH_NAMES, CONTACT_SIGMA_MAX,  # noqa: E402
                    DATA_DIR, DECROCHAGE_S, FENETRE_PAQUETS_S, MARKER_LATE_S, MARKER_STREAM_DEFAULT,
                    MI_WINDOW_S, NEURO_WINDOW_S, REESSAI_S, SECTEUR_HZ, SECTEURS_HZ,
                    SEANCES_DIR, TOLERANCE_DIVISEUR, TRACES_AFFICHAGE_S, TRACES_AMORCE_S,
                    barres_liaison, chemin_libre, contact_bon,
                    choose_frequencies,
                    empreinte_dossier, json_float, nom_retenu, propose_frequencies,
                    reference_lost, use_utf8_console)
from core.i18n import catalogue, joint, message_erreur, pour_le_contrat, tr  # noqa: E402
from core.lsl_io import (NOM_FLUX_COMMANDES, NOM_FLUX_REPONSES, STREAM_PREFIX,  # noqa: E402
                    ClockBridge, DecodedNeuroPublisher, QualityPublisher, StatusPublisher,
                    default_instance_id, mi_channel_labels, stream_name, verdict_from_sigma)
from core.markers import MarkerInlet  # noqa: E402
from core.modes import contract, registry  # noqa: E402
from core.modes.marker_calib import MarkerCalibrationRuntime  # noqa: E402
from core.pilotage import COMMANDES_RESEAU, Pilotage  # noqa: E402
from core.pilotage_udp import PORT_UDP  # noqa: E402
from core.version import VERSION  # noqa: E402

# Le suffixe du flux de réponses du pilotage, tiré de son nom public (`lsl_io`) : un renommage
# là-bas suit partout ici.
_SUFFIXE_REPONSES = NOM_FLUX_REPONSES[len(stream_name("")):]

# Cadence de la boucle. On ne publie PAS échantillon par échantillon : on ramasse ~50 ms de
# signal d'un coup. Assez court pour rester très en dessous des fenêtres de décision d'un
# mode BCI (1-2 s), assez long pour ne pas réveiller le processus 250 fois par seconde.
POLL_S = 0.05
QUALITY_PERIOD_S = 1.0    # cadence du flux `quality`
STATUS_PERIOD_S = 2.0     # rappel périodique de l'état (pour un client qui arrive en retard)
QUALITY_WINDOW_S = 2.0    # longueur de signal sur laquelle on mesure le σ par voie

# Le rappel du « status » poussé à l'appareil réseau connecté, même sans changement : un appareil
# qui vient de se brancher l'apprend en moins de cette durée.
STATUT_APPAREIL_S = 1.0

# Cadence maximale du message « inlet de marqueurs en erreur ». Mesuré sur un inlet perdu : 310
# exceptions en 20 s. Sans cette limite, la boucle imprime 20 lignes par seconde et noie tout le
# reste du journal — y compris les messages des modes qui tournent à côté et vont très bien.
_MARQUEUR_ERREUR_PERIODE_S = 10.0
# Seuils auxquels un compteur de marqueurs s'annonce tout seul (cf. `_dit_compteurs_marqueurs`).
# Le premier vaut 1 : le tout premier incident doit se voir, c'est celui qui explique tous les
# suivants.
_SEUILS_MARQUEURS = (1, 10, 100, 1000, 10000)

# ⚠️ LE VOL DE MARQUEURS. `markers_murs(mode_id)` ne tient qu'UN curseur par `mode_id`, et l'appel
# le fait AVANCER. Un mode à marqueurs et sa calibration (ou son TEST) se réclament tous les deux du
# MÊME `spec.id` : lancés ensemble, chacun n'obtient qu'une partie des marqueurs, l'autre partie
# disparaît pour de bon — aucune exception, aucun compteur, deux chiffres plausibles et faux.
#
# ⚠️ UN SEUL PROTOCOLE MINUTÉ À LA FOIS — calibrations et mesures confondues. Autre cause : ici
# rien n'est volé, c'est la PERSONNE qui ne peut pas obéir à deux consignes. Deux protocoles
# prélèveraient leurs fenêtres dans le MÊME tampon glissant pendant qu'un seul écran affiche une
# seule consigne : « ferme les yeux » et « imagine ton poing » obtiendraient le même signal.
#
# Les refus qui l'expliquent à l'écran sont lus dans `core/langues/<langue>/moteur.json`
# (`moteur.refus.*`) : UNE phrase par sens de chaque refus. Celui qui vient de cliquer « Tester »
# lit « son test », jamais « sa calibration ».


def _lit_les_marqueurs(rt):
    """Ce runtime consomme-t-il la file de marqueurs du moteur ?

    Lu sur l'OBJET, par la présence d'un `marker_mode_id` non vide : c'est ce champ qui nomme la
    clé passée à `markers_murs`, donc un runtime qui le déclare est exactement un runtime qui
    appelle `markers_murs`. Servi aux MESURES, qui n'ont pas de `Calib` sur quoi raisonner.
    """
    return bool(getattr(rt, "marker_mode_id", ""))


def _publie_le_flux_du_mode(test):
    """Ce test (sa CLASSE, ou l'objet qui tourne) publie-t-il ses décisions sur le flux décodé de son
    mode (`decoded_<marker_mode_id>`) ? Déduit par `MesureMarqueurs.publie_le_flux_du_mode`."""
    publie = getattr(test, "publie_le_flux_du_mode", None)
    return bool(callable(publie) and publie())


def _calibration_lit_les_marqueurs(calib):
    """La calibration DÉCLARÉE par un mode consomme-t-elle la file de marqueurs du moteur ?

    Lu sur la CLASSE du runtime (`issubclass(..., MarkerCalibrationRuntime)`), jamais sur
    `Calib.kind` : c'est cette classe-là qui appelle `markers_murs`, donc c'est elle qui vole.
    `kind` est une DÉCLARATION, et une déclaration peut cesser de décrire le code sans que rien
    ne le dise. Les deux se recoupent ; c'est la classe qui fait foi.

    `runtime_cls` peut valoir None (calibration déclarée, runtime pas encore livré) : elle n'est
    alors jamais jouée, donc elle ne vole rien. D'où le `isinstance(cls, type)` avant le
    `issubclass`, qui lèverait sinon.
    """
    cls = None if calib is None else calib.runtime_cls
    return isinstance(cls, type) and issubclass(cls, MarkerCalibrationRuntime)


class _Enregistrement:
    """Une séance en train de s'écrire : un JSONL, **une ligne par DÉCISION PUBLIÉE**.

    ⚠️ **C'est le MOTEUR qui écrit, jamais la console.** La console est un client : elle envoie
    `start_enregistrement` et lit l'état, elle ne touche pas au disque — exactement le partage de
    `save_calibration`. Et l'écriture se fait sur le fil de la BOUCLE, comme tout ce qui a un
    effet : `submit` ne fait que mettre en file.

    ⚠️ **Le fichier ne va pas dans `data/`** (cf. `config.SEANCES_DIR`) : ce sont des verdicts de
    séance, ni un modèle ni un enregistrement EEG, et `data/` garde son autorité d'écriture unique.

    ⚠️ **Une ligne par décision PUBLIÉE, pas par tour de boucle**, et c'est toute la subtilité de
    `noter`. Les six modes reconstruisent leur dictionnaire de sortie à CHAQUE publication ; un
    tour où le mode n'a rien publié (fenêtre incomplète, époque hors tampon, mode encore en repos)
    rend donc le MÊME objet qu'au tour d'avant. On compare par IDENTITÉ, et on n'écrit que du
    neuf : sinon le fichier porterait une décision par tour de boucle, et un mode qui n'émet que
    44 % du temps — le régime NORMAL du SSVEP, mesuré sur ce casque — se relirait à 100 %. Le
    fichier mentirait précisément sur la grandeur qu'on vient y chercher.

    ⚠️ Cette règle repose sur une propriété des modes (« publier reconstruit la sortie ») que le
    smoke pin par un runtime factice : le mode #7 qui MUTERAIT son dict en place perdrait des
    lignes en silence. C'est écrit ici et vérifié là-bas, pas laissé à la discipline.

    L'horodatage est celui que le mode a donné à son publieur — donc l'horloge LSL, la MÊME que le
    journal d'une fenêtre de stimulus (`stimulus/cvep.py --log`). C'est ce qui rend la jointure des
    deux fichiers purement numérique, et c'est la raison d'être de tout ceci.
    """

    def __init__(self, chemin, mode_id, flux):
        self.chemin = chemin
        self.mode_id = mode_id
        self.flux = flux
        self.lignes = 0          # verdicts écrits — ni l'en-tête ni le bilan ne comptent
        self.actif = False
        self.probleme = ""
        self._fichier = None
        self._derniere = None    # l'OBJET de la dernière sortie notée, cf. le ⚠️ de la classe

    def ouvrir(self, runtime, instance="", fs_hz=0.0):
        """Crée le fichier et écrit l'en-tête. Lève si le disque refuse — et c'est voulu.

        Le seul endroit de cette classe qui a le droit de lever : `_start_enregistrement` en fait
        un refus AFFICHÉ. Un dossier non inscriptible doit se dire au moment du clic, pas à la fin
        d'une séance qu'on croyait enregistrée.
        """
        os.makedirs(os.path.dirname(self.chemin) or ".", exist_ok=True)
        # "a" et non "w" : `chemin_libre` garantit déjà que le nom est neuf, et l'ajout est le
        # mode qui ne peut pas détruire une séance sur un nom qu'on aurait mal calculé.
        self._fichier = open(self.chemin, "a", encoding="utf-8")
        self.actif = True
        from pylsl import local_clock

        self._ecrire({
            "kind": "header",
            "t": float(local_clock()),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "flux": self.flux,
            "mode": self.mode_id,
            "instance": instance,
            "fs_hz": float(fs_hz),
            # Les voies et les réglages EN VIGUEUR au départ. Sans eux, une colonne de verdicts ne
            # se relit pas six mois plus tard : « score_15Hz » n'existe que pour ce jeu de
            # fréquences-là, et c'est le genre de contexte qu'on croit toujours se rappeler.
            "voies": list(runtime.channels()),
            "params": {k: (list(v) if isinstance(v, tuple) else v)
                       for k, v in dict(runtime.params).items()},
            # ⚠️ DIT, pas supposé : un mode peut décoder sans PUBLIER (case « publié » décochée).
            # Le fichier serait alors parfaitement rempli pendant qu'aucun client ne reçoit rien —
            # et personne ne pourrait, après coup, distinguer les deux situations.
            "publie": bool(runtime.published),
        })

    def noter(self, runtime, lsl_ts):
        """Écrit la sortie du mode SI elle est neuve. True si une ligne a été écrite."""
        if not self.actif:
            return False
        sortie = runtime.output()
        if sortie is None or sortie is self._derniere:
            return False
        self._derniere = sortie
        self._ecrire({"kind": "verdict", "t": float(lsl_ts), "phase": runtime.phase,
                      # La sortie du mode telle qu'il l'a publiée, sous ses PROPRES clés — jamais
                      # aplatie en colonnes. Un mode qui gagnerait un champ demain ne décalerait
                      # donc rien de ce qui précède, et un dépouillement écrit contre ce fichier
                      # lit des noms, pas des positions.
                      "sortie": sortie})
        self.lignes += 1
        return True

    def fermer(self):
        """Écrit le bilan et referme. Idempotente : `close()` et l'arrêt de la boucle l'appellent
        tous les deux, et une séance ne doit pas dépendre de qui arrive en premier."""
        if not self.actif:
            return
        from pylsl import local_clock

        self._ecrire({"kind": "fin", "t": float(local_clock()), "verdicts": self.lignes})
        self.actif = False
        fichier, self._fichier = self._fichier, None
        if fichier is not None:
            try:
                fichier.close()
            except OSError:
                pass

    def state(self):
        """Ce que la console lit. `actif` False APRÈS un arrêt, jamais None : le chemin doit
        rester à l'écran, c'est ce qu'on vient chercher pour dépouiller."""
        return {"actif": self.actif, "chemin": self.chemin, "lignes": self.lignes,
                "flux": self.flux, "mode": self.mode_id, "probleme": self.probleme}

    def _ecrire(self, objet):
        """Une ligne JSON, écrite ET VIDÉE tout de suite — même geste que `stimulus/cvep.py`.

        Le `flush` est le point de l'exercice : un moteur tué au milieu d'une séance laisse alors
        un fichier complet jusqu'à sa dernière ligne, ce qu'un JSON global écrit à la fin ne
        permettrait pas. Une séance casque ne se refait pas.

        Une écriture qui échoue (disque plein, fichier verrouillé) ARRÊTE l'enregistrement en le
        DISANT, et ne remonte pas dans la boucle : perdre la trace d'une séance est fâcheux,
        perdre l'acquisition qui la produit l'est bien davantage.
        """
        if self._fichier is None:
            return
        try:
            self._fichier.write(json.dumps(objet, ensure_ascii=False, default=float) + "\n")
            self._fichier.flush()
        except Exception as e:  # noqa: BLE001 - cf. docstring : jamais dans la boucle
            self.probleme = tr("moteur.enregistrement.ecriture_impossible",
                               erreur=f"{type(e).__name__} : {e}")
            self.actif = False
            print(f"[server] ⚠️ enregistrement INTERROMPU : {self.probleme} — "
                  f"{self.lignes} verdict(s) sauvés dans {self.chemin}")


def _a_un_modele(spec):
    """Le mode a-t-il un réglage `model` ? C'est le CONTRAT qui le dit, jamais une liste de
    modes : un mode à modèle ajouté demain attendra son modèle sans une ligne de plus."""
    return any(p.key == "model" for p in spec.params)


# La longueur gardée d'un `model` suggéré par l'application : un nom de fichier, pas un texte
# sans fin qu'une application mal écrite ferait afficher par la page de contrôle.
_SUGGESTION_MAX = 60


@dataclasses.dataclass
class _Connexion:
    """L'application connectée, quand la console écoute sur demande."""
    uid: str
    nom: str
    depuis: float           # time.time() : l'heure affichée
    t: float                # time.monotonic() : l'horloge du journal du pilotage
    demarres: set = dataclasses.field(default_factory=set)    # arrêtés à la fin
    # Les modes qu'elle a demandés (`start_mode` accepté), même s'ils tournaient déjà : un
    # appareil réseau en reçoit les décisions. Seuls ceux de `demarres` s'arrêtent à la fin.
    demandes: set = dataclasses.field(default_factory=set)
    regles: set = dataclasses.field(default_factory=set)      # montrés par la page
    en_attente: dict = dataclasses.field(default_factory=dict)   # mode -> jeton du start_mode
    suggestions: dict = dataclasses.field(default_factory=dict)  # mode -> `model` proposé
    illisible: bool = False  # son nom (`source_id`) ne se lit pas : la console le dit ainsi
    # D'où elle vient, recopié de son annonce (`Pilotage.annonces`) : « lsl » ou « udp » (un
    # appareil réseau) ; sa machine (nom d'hôte LSL, adresse IP d'un appareil) ; l'identifiant
    # qu'annonce un appareil (None pour LSL) ; son adresse « ip:port » (None pour LSL).
    origine: str = "lsl"
    machine: str = ""
    ident: object = None
    adresse: object = None


class _SortieObservee:
    """L'outlet LSL d'un mode, qui publie comme avant ET signale chaque échantillon au moteur.

    C'est par lui que les décisions d'un mode partent aussi vers l'appareil réseau connecté : le
    moteur l'installe à la place de l'outlet du publieur (`_out.outlet`, la convention des
    modes), juste avant le pas du mode (`EngineServer._observer_la_sortie`). Tout le reste est
    passé à l'outlet d'origine (`have_consumers`, par exemple).

    Il ne tient le moteur que par une référence FAIBLE : moteur → mode → publieur → ici → moteur
    serait un cycle, libéré seulement par le ramasse-miettes (cf. le `finally` de `run`)."""

    def __init__(self, outlet, mode_id, voies, moteur):
        self._outlet = outlet
        self._mode_id = mode_id
        self._voies = list(voies)
        self._moteur = weakref.ref(moteur)

    def push_chunk(self, x, *args, **kwargs):
        self._outlet.push_chunk(x, *args, **kwargs)
        self._signaler(x)

    def push_sample(self, x, *args, **kwargs):
        self._outlet.push_sample(x, *args, **kwargs)
        self._signaler([x])

    def __getattr__(self, nom):
        return getattr(self._outlet, nom)

    def _signaler(self, rangees):
        """Chaque rangée publiée, au moteur. Ne lève jamais : le décodage du mode continue."""
        moteur = self._moteur()
        if moteur is None:
            return
        try:
            for rangee in rangees:
                moteur._decision_publiee(self._mode_id, self._voies, rangee)
        except Exception as e:  # noqa: BLE001 - une poussée ratée ne doit pas arrêter le mode
            print(f"[server] décision impossible à pousser à l'appareil réseau : {e!r}")


def _valeur_json(x):
    """Une valeur d'un flux décodé (float32), en nombre JSON : 7 chiffres significatifs, ceux d'un
    float32 (« 0.3 » et non « 0.30000001192092896 »), et None pour une valeur qui n'est pas finie
    (le JSON n'a ni NaN ni infini)."""
    x = float(x)
    if not math.isfinite(x):
        return None
    return float(format(x, ".7g"))


class EngineServer:
    """Boucle acquisition -> publication. Un objet, une session casque, N modes actifs.

    Le moteur tient **son propre tampon glissant** (`recent`). C'est le point d'architecture
    central : `get_new_data()` VIDE le tampon de BrainFlow, donc les accesseurs à fenêtre
    glissante (`get_window`, `get_epoch`) ne peuvent plus servir. Diffuser et décoder en même
    temps n'est possible qu'en gardant l'historique ici, et en alimentant depuis lui à la fois
    la publication brute et les décodeurs des `ModeRuntime` actifs.
    """

    def __init__(self, serial=None, synthetic=False, verbose=False, modes=("raw",),
                 params=None, instance=None, data_dir=None, seances_dir=None,
                 secteur_hz=SECTEUR_HZ, flux_commandes=NOM_FLUX_COMMANDES, ecoute="permanente",
                 port_udp=PORT_UDP):
        """`modes` : les identifiants à démarrer. `params` : {mode_id: {clé: valeur}}, facultatif.

        Un identifiant inconnu ou un réglage invalide lève ici, au démarrage — bruyamment et
        tout de suite, plutôt qu'en séance sur un décodage qui ne détecte jamais rien.

        `data_dir` : où atterrit un modèle qu'on RETIENT. Injectable pour que les tests
        n'approchent jamais le vrai `data/` — enregistrements EEG d'une personne identifiable, sur
        un dépôt public, et dont le fichier le plus récent est ce que le moteur ÉLIT par défaut.

        `seances_dir` : où atterrissent les VERDICTS d'une séance enregistrée. Un dossier distinct
        de `data_dir`, et injectable pour la même raison — à ceci près que le risque est inverse :
        ici on ne craint pas d'élire un fichier de test, on craint de semer dans le dossier d'un
        utilisateur des séances qui n'en sont pas.

        `secteur_hz` : le SECTEUR électrique du poste, 50 Hz (Europe) ou 60 Hz (Amériques) —
        `config.SECTEURS_HZ`. Un réglage du POSTE, pas d'un mode : l'écran de départ le choisit,
        `--secteur` le donne au moteur seul. Tout ce qui coupe le secteur le lit ICI : le filtre
        d'acquisition (σ du bandeau, contrôle de liaison, SSVEP), le contrôle alpha, le rejet
        d'artefact du Neuro, les tracés du Brut, et chaque entraînement, qui l'ENREGISTRE dans son
        modèle. Une autre valeur est refusée ici, avant d'ouvrir quoi que ce soit : un coupe-bande
        à 55 Hz ne couperait aucun secteur, et chaque modèle entraîné le porterait.

        `flux_commandes` : le nom du flux LSL où une application envoie ses commandes
        (`core/pilotage.py`). Un test en prend un qui lui est propre : un moteur oublié
        sur le poste écoute le nom par défaut, et obéirait sinon aux commandes du test.

        `ecoute` : « permanente » (le moteur seul, `server.py`) écoute toutes les applications de
        cette machine ; « sur_demande » (la console) n'en écoute AUCUNE tant que la personne n'a
        pas choisi la sienne (« Connecter une application », commande `connecter`), parmi les
        applications LSL de tout le réseau et les appareils réseau (UDP).

        `port_udp` : le port UDP où la console écoute les appareils réseau
        (`pilotage_udp.PORT_UDP`). Un test en prend un qui lui est propre (0 : un port libre,
        choisi par le système) : une console ouverte sur le poste tient le port par défaut. Le
        moteur seul n'ouvre aucune socket.
        """
        try:
            secteur = float(secteur_hz)
        except (TypeError, ValueError):
            secteur = None
        if secteur not in SECTEURS_HZ:
            raise ValueError(tr("moteur.refus.secteur_inconnu", valeur=secteur_hz,
                                liste=", ".join(f"{s:g}" for s in SECTEURS_HZ)))
        # Lu par attribut, `getattr(engine, "secteur_hz", SECTEUR_HZ)`, par chaque entraînement
        # et par les mesures : ⚠️ un nom différent ici ne lèverait rien, tout retomberait en
        # silence sur le défaut. `[smoke-calib]` entraîne donc sur un moteur à 60 Hz.
        self.secteur_hz = secteur
        self.synthetic = synthetic
        self.acq = UnicornAcquisition(serial=serial, synthetic=synthetic, verbose=verbose,
                                      notch=NOTCH_SECTEUR[secteur])
        # Passe à True dès que le casque (ou le board de test) est OUVERT, dans le fil de `run()`.
        # C'est ce que la console attend avant de s'afficher : un casque qui refuse
        # de s'ouvrir tue ce fil avant que l'indicateur ne passe, et l'écran de départ peut alors
        # reposer la question au lieu d'afficher une console déjà morte.
        self.acquisition_ouverte = False
        # La SURVEILLANCE DE LA LIAISON (cf. `DECROCHAGE_S`). `_liaison` : « ok » ou
        # « perdue » ; les instants sont en `perf_counter`, l'horloge de la boucle. Attributs
        # d'instance pour que les tests les raccourcissent sans attendre 2 s réelles.
        self.decrochage_s = DECROCHAGE_S
        self.reessai_s = REESSAI_S
        self._liaison = "ok"
        self._dernier_echantillon = None
        self._perdue_depuis = None
        self._tentatives = 0
        self._erreur_liaison = ""
        self._erreur_lecture = ""       # la dernière erreur de LECTURE dite au terminal (`_lire`)
        self._retablie_a = None
        self._coupure_s = None
        self._prochain_essai = 0.0
        # L'historique des cumuls de paquets (instant, reçus, perdus), pour un taux de perte sur
        # les `FENETRE_PAQUETS_S` dernières secondes — pas depuis l'ouverture, où une vieille
        # perte diluée dans une heure de séance ne dirait rien de la liaison MAINTENANT.
        self._paquets = collections.deque()
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
        # AU PLUS UNE mesure, et jamais en même temps qu'une calibration : c'est le même casque et
        # la même personne (cf. « UN SEUL PROTOCOLE MINUTÉ », en tête). Elle vit dans son propre
        # emplacement, à côté de `self.calibration` et pour la même raison — un protocole minuté
        # n'est pas un mode : il ne publie aucun flux, il rend un VERDICT qu'on lit à l'écran.
        #
        # ⚠️ Ce qui la sépare vraiment d'une calibration : **elle n'écrit rien**. Pas de dossier
        # candidat, pas de `save_mesure`, aucun fichier — donc rien à nettoyer dans `close()`.
        self.mesure = None
        # ⚠️ OÙ UNE CALIBRATION ÉCRIT, ET OÙ ELLE N'ÉCRIT PAS.
        # Elle écrit un CANDIDAT dans un dossier temporaire propre à CE moteur, et
        # `save_calibration` est le seul geste qui touche `data/`. Le moteur, la console et les
        # applis proposent tous le modèle chargeable le PLUS RÉCENT : un modèle écrit dans `data/`
        # avant d'être jugé deviendrait le défaut en silence, sans que personne puisse le refuser.
        self.data_dir = data_dir or DATA_DIR
        # Là où le moteur écrit les VERDICTS d'une séance, sur commande de la console. ⚠️ Un
        # dossier distinct de `data_dir`, et ce n'est pas cosmétique : la moitié de la valeur de
        # `empreinte_dossier(DATA_DIR)` vient de ce que RIEN d'autre n'a le droit d'écrire là.
        self.seances_dir = seances_dir or SEANCES_DIR
        # AU PLUS UN enregistrement à la fois. Un `_Enregistrement` (arrêté ou non) survit à son
        # arrêt : `state()` garde le chemin à l'écran, c'est ce qu'on vient chercher pour
        # dépouiller. Il n'est remplacé qu'au démarrage du suivant.
        self.enregistrement = None
        # Le dossier est créé à la PREMIÈRE calibration, pas à la construction du moteur : `run()`
        # le balaie dans son `finally`, mais un `EngineServer` construit sans être lancé (les
        # autotests, un `--mode` refusé) laisserait sinon un dossier vide dans le temporaire du
        # système, que rien n'efface sous Windows. Un dossier par moteur, créé par lui, jamais
        # partagé. Cf. `_dossier_candidat`.
        self.calib_dir = None
        self.candidat = None        # le dict rendu par `_entrainer`, tant qu'il n'est pas tranché
        # La calibration DONT le candidat courant provient. Sert à n'adopter le résultat qu'UNE
        # fois : sans elle, `save`/`discard` remettraient `candidat` à None et le tour de boucle
        # suivant le ré-adopterait depuis une calibration toujours en phase « fini ».
        self._candidat_de = None
        self.rest_instruction = ""  # la consigne du repos en cours, partagée s'il l'est
        self._stop = False
        self._last_tick = {}
        self._commands = queue.Queue()
        # Le dernier `start_mode` ou `stop_mode` ACCEPTÉ de chaque mode, tant que la boucle ne l'a
        # pas appliqué : {mode_id: (numéro, "start" | "stop")}. `submit` dit à l'appelant si le
        # mode tournait déjà (« deja ») d'après ce que le moteur FERA une fois la file vidée, pas
        # d'après l'instant présent : une application qui envoie `stop_mode` puis `start_mode`
        # sans attendre la boucle (~50 ms) s'entendrait sinon répondre « déjà en marche » pour un
        # mode qui va être arrêté puis redémarré. Cf. `_tourneront`.
        self._en_attente = {}
        self._en_attente_n = 0
        self._en_attente_verrou = threading.Lock()
        # L'adaptateur réseau : une application règle, démarre et arrête un mode, par LSL ou par
        # UDP (`core/pilotage.py`) — de CETTE machine seulement pour le moteur seul. Son flux de réponses existe dès maintenant ; son fil
        # d'écoute tourne pendant `run()`, et appelle `submit` comme le fait la console.
        # ⚠️ Il ne tient le moteur que par une référence FAIBLE. Une référence forte formerait un
        # cycle moteur ↔ adaptateur, libéré seulement par le ramasse-miettes cyclique, à une date
        # quelconque : le destructeur de la session BrainFlow de ce moteur libérerait alors celle
        # du moteur SUIVANT du même processus (cf. le `finally` de `run`).
        self.ecoute = ecoute
        self.port_udp = port_udp
        self.pilotage = Pilotage(weakref.proxy(self), nom_flux=flux_commandes, ecoute=ecoute)
        # L'application CONNECTÉE (écoute sur demande), ou None ; et la dernière fin de
        # connexion, que la page de contrôle et le bandeau disent.
        self.connexion = None
        self.fin_connexion = None
        # Le dernier « status » poussé à l'appareil réseau connecté et son instant
        # (`perf_counter`) : il repart à chaque changement, et au plus tard chaque
        # `STATUT_APPAREIL_S`. Lus et écrits par la boucle seulement.
        self._statut_pousse = None
        self._statut_pousse_a = 0.0
        self._pannes_dites = set()   # les poussées en panne déjà dites (`_dire_une_panne`)
        # Le verrou de la CONNEXION. Sous lui : une commande de l'application en entier
        # (`submit`), « Connecter », « Déconnecter », le départ de l'application et « Lancer le
        # décodage ». Une fin de connexion passe donc avant ou après une commande, jamais au
        # milieu : sinon un mode démarré à cet instant échapperait à la liste de ce qu'on arrête.
        # ⚠️ Deux règles :
        #   1. ne JAMAIS le reprendre dans le fil qui le tient : c'est un `Lock`, le fil
        #      s'attendrait lui-même pour toujours (d'où le refus des `COMMANDES_CONSOLE` venues
        #      du réseau AVANT de le prendre, dans `submit`) ;
        #   2. ne JAMAIS appeler `pilotage.arreter()` en le tenant : `arreter` attend la fin du
        #      fil d'écoute, qui peut lui-même attendre ce verrou dans `submit`.
        # Ordre des verrous, toujours dans ce sens : `pilotage._verrou_ordre` →
        # `_connexion_verrou` → (`_en_attente_verrou` | `pilotage._verrou`), et
        # `TransportUDP._verrou` toujours le dernier (sous `pilotage._verrou`, jamais l'inverse).
        self._connexion_verrou = threading.Lock()
        # Un appelable `(reseau, command, raison)`, ou None : appelé par la BOUCLE quand une
        # commande portant un jeton `reseau` échoue après avoir été acceptée. L'adaptateur publie
        # alors l'échec à l'application.
        self.sur_echec = self.pilotage.signaler_echec
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
        # DÉCLARÉE mais dont le runtime n'est pas livré n'est jamais jouée par le moteur, donc son
        # `epoch_s`, purement documentaire, ne doit dimensionner AUCUN tampon ici. Sans ce filtre,
        # un `epoch_s` posé pour la lisibilité gonflerait `keep` en silence — et, par ricochet, la
        # fenêtre de mesure de la qualité (`_publish_quality`, cf. son propre avertissement).
        epoque_calib = max([spec.calibration.epoch_s for spec in registry.MODES
                            if spec.calibration is not None
                            and spec.calibration.runtime_cls is not None] or [0.0])
        # L'époque prélevée autour d'un marqueur, plus le retard qu'on tolère pour ce marqueur.
        # ⚠️ Ce besoin doit être NOMMÉ ici, et non couvert par `QUALITY_WINDOW_S` ou `MI_WINDOW_S` :
        # les baisser un jour tronquerait CHAQUE époque P300 en silence.
        #
        # ⚠️ À ne pas confondre avec le filtre juste au-dessus : l'`epoch_s` d'une calibration
        # SANS RUNTIME ne dimensionne rien, parce que le moteur ne la joue pas. Ici c'est l'époque
        # du RUNTIME, que le moteur prélève lui-même à chaque marqueur — et c'est elle, pas
        # `epoch_s`, qui dimensionne le tampon des calibrations menées par une FENÊTRE, puisque
        # celles-ci prélèvent par le même chemin que le décodage (cf. `modes/marker_calib.py`).
        epoque_marqueur = max([spec.marker_epoch_s for spec in registry.MODES] or [0.0])
        # Et l'époque des MESURES menées par une fenêtre. ⚠️ Ce terme doit être NOMMÉ, pas couvert
        # par `epoque_calib` : la mesure du taux SSVEP prélève la fixation entière (4 s), grandeur
        # sans rapport avec l'`epoch_s` de la calibration MI. Si le MI raccourcissait la sienne,
        # CHAQUE époque de la mesure serait tronquée en silence, et le taux porterait sur moins de
        # signal que ce que l'écran annonce. Déclaré par `MesureRuntime.epoque_marqueur_s`.
        epoque_mesure = max([getattr(spec.runtime_cls, "epoque_marqueur_s", 0.0) or 0.0
                             for spec in registry.MESURES if spec.runtime_cls is not None] or [0.0])
        # ⚠️ **Et la plus longue ÉTAPE d'un protocole de mesure**, distincte de la précédente : le
        # contrôle alpha ne prélève AUCUNE époque autour d'un marqueur (son `epoque_marqueur_s`
        # vaut 0, à raison) mais demande deux fenêtres de 8 s à sa propre ligne du temps. Sans ce
        # terme, `keep` serait de 5 s, les deux étapes seraient ignorées, et la BARRIÈRE D'ENTRÉE
        # DE TOUTE SÉANCE ne pourrait jamais être franchie.
        etape_mesure = max([spec.runtime_cls.epoque_etape_s()
                            for spec in registry.MESURES if spec.runtime_cls is not None] or [0.0])
        self.keep = max(int(QUALITY_WINDOW_S * self.acq.fs),
                        int(NEURO_WINDOW_S * self.acq.fs),
                        int(MI_WINDOW_S * self.acq.fs),
                        int(epoque_calib * self.acq.fs),
                        int(round((epoque_marqueur + MARKER_LATE_S) * self.acq.fs)),
                        int(round(epoque_mesure * self.acq.fs)),
                        int(round(etape_mesure * self.acq.fs)),
                        # Les tracés du Brut : ce qu'ils affichent, plus l'amorce de leur filtre.
                        int(round((TRACES_AFFICHAGE_S + TRACES_AMORCE_S) * self.acq.fs)),
                        self.acq.window_n) + self.acq.margin_n

        # Les DERNIERS réglages connus de chaque mode, qu'il tourne ou non. C'est ce qui permet de
        # régler un mode AVANT de le démarrer — le geste naturel : on cale ses fréquences sur son
        # écran, son pic alpha sur sa tête, puis on lance. `set_params` et `propose_params`, les
        # deux moitiés du même geste, acceptent donc l'une et l'autre un mode arrêté.
        #
        # 🔴 C'est le DERNIER MOT ACCEPTÉ, pas l'état appliqué : `submit("set_params")` et
        # `submit("start_mode")` l'écrivent AU MOMENT où ils acceptent, avant que la boucle n'ait
        # rien appliqué. Les deux jugent un nouveau réglage en le fusionnant sur ce magasin, et
        # `_start` y lit, au moment où la boucle l'APPLIQUE, ce avec quoi le mode démarre. Juger
        # sur les réglages du runtime (l'état appliqué) perdait des réglages acceptés : deux
        # `set_params` envoyés coup sur coup, le second fusionné sur un runtime qui n'avait pas
        # encore reçu le premier, annulaient le premier — sans un mot.
        # `_set_params` n'y touche pas (on n'y arrive que par la file, que `submit` a déjà servie),
        # sauf pour le REMETTRE quand le runtime refuse.
        self.reglages = {}
        self._pending = self._prepare(modes or (), params or {})
        for spec, values in self._pending:
            self.reglages[spec.id] = dict(values)
        if not self._pending:
            # `--no-raw` sans `--mode` donne un moteur qui n'a rien à publier. Il tourne, il
            # acquiert, et le réseau reste muet — panne silencieuse dont le seul symptôme est un
            # client qui ne trouve jamais son flux. On le dit plutôt que de le laisser deviner.
            print(f"[server] AUCUN mode demandé : seuls {stream_name('quality')}, "
                  f"{stream_name('status')} et {NOM_FLUX_REPONSES} seront publiés. "
                  f"Ajoute --mode, ou retire --no-raw.")

    def _prepare(self, modes, params):
        """Valide les modes demandés au démarrage. Retourne [(spec, réglages), ...]."""
        prepared = []
        for spec in registry.MODES:            # l'ordre du registre, toujours
            if spec.id not in modes:
                continue
            if spec.runtime_cls is None:
                raise ValueError(tr("moteur.refus.pas_dans_le_moteur", mode=spec.label,
                                    raison=spec.unavailable))
            values, reason = contract.validate(spec, params.get(spec.id, {}))
            if values is None:
                raise ValueError(reason)
            prepared.append((spec, values))
        inconnus = sorted(set(modes) - {s.id for s, _ in prepared})
        if inconnus:
            connus = ", ".join(s.id for s in registry.runnable())
            raise ValueError(tr("moteur.refus.mode_inconnu",
                                id=", ".join(contract.recopie(i, brut=True) for i in inconnus),
                                liste=connus))
        return prepared

    def stop(self):
        self._stop = True

    # --- démarrer, arrêter, régler — les opérations sur les modes -----------

    # --- le refus du vol de marqueurs, dans ses DEUX sens ---------------------
    # Les deux méthodes rendent une RAISON (à afficher) ou None. Elles servent à la fois à
    # `submit` — qui refuse tout de suite, avec sa raison — et à la BOUCLE, qui doit refuser une
    # seconde fois : `submit` juge sur l'état à l'instant où la commande est SOUMISE, et deux
    # commandes soumises dans la même fenêtre de sondage (`start_mode` et `start_calibration`)
    # voient toutes les deux un moteur vierge et sont acceptées toutes les deux. C'est exactement
    # la course que `_start_calibration` documente déjà pour le double-clic sur « Commencer ».

    def _refus_calibration_pendant_mode(self, spec, actifs):
        """Refuser la calibration de `spec` parce que SON mode décode ? La raison, ou None.

        `actifs` : une copie de `self.active` prise par l'appelant (même discipline que
        `_phase_of`) — `submit` tourne sur le fil de l'interface pendant que la boucle démarre et
        arrête des modes sur le sien.
        """
        if spec is None or spec.id not in actifs or spec.marker_epoch_s <= 0:
            return None
        if not _calibration_lit_les_marqueurs(spec.calibration):
            return None
        return tr("moteur.refus.calibration_pendant_mode", mode=spec.label)

    def _refus_mode_pendant_calibration(self, spec, calibration):
        """Refuser de démarrer `spec` parce que SA calibration tourne ? La raison, ou None.

        `calibration` : une copie de `self.calibration` prise par l'appelant, pour la même raison
        que ci-dessus. Ici on interroge l'OBJET qui tourne (`isinstance`), pas une déclaration :
        c'est lui qui appelle `markers_murs`, donc lui qui vole.
        """
        if spec is None or calibration is None or calibration.terminee:
            return None
        if calibration.spec.id != spec.id or spec.marker_epoch_s <= 0:
            return None
        if not isinstance(calibration, MarkerCalibrationRuntime):
            return None
        return tr("moteur.refus.mode_pendant_calibration", mode=spec.label)

    # --- le même vol, entre un mode et son TEST ------------------------------------------------
    # Une mesure menée par une fenêtre lit ses marqueurs par
    # `markers_murs(marker_mode_id)`, et `marker_mode_id` est l'identifiant DU MODE (« p300 »). Le
    # moteur n'y tient qu'UN curseur par identifiant : un test lancé pendant que son mode décode
    # verrait la moitié des flashs, le mode l'autre moitié, sans la moindre erreur. Exactement le
    # défaut que les deux méthodes ci-dessus empêchent entre un mode et sa calibration — le test
    # est un troisième lecteur de la même file, il fallait lui fermer la même porte.

    def _refus_mesure_pendant_mode(self, mesure_spec, actifs):
        """Refuser la mesure parce que le mode dont elle lit les marqueurs DÉCODE ? La raison, ou None.

        Lu sur la CLASSE du runtime (`marker_mode_id`), la seule chose connue avant construction.
        Une mesure sans marqueurs (le contrôle alpha, le test du MI) n'est jamais concernée.

        ⚠️ **Deux raisons, pas une.** Un test peut voler les marqueurs de son mode
        (`marker_epoch_s > 0`), OU publier sur son flux : le c-VEP, le P300 et le SSVEP publient
        leurs décisions de test sur `decoded_<mode>` (`_publie_le_flux_du_mode`). Deux publieurs,
        même nom, même instance : un client reçoit leurs décisions mêlées, ou se rattache au
        mauvais. C'est la seconde raison qui ferme la porte au SSVEP, qui ne lit aucun marqueur.
        """
        cls = getattr(mesure_spec, "runtime_cls", None)
        cible = getattr(cls, "marker_mode_id", "") or ""
        if not cible or cible not in actifs:
            return None
        mode = registry.get(cible)
        if mode is None:
            return None
        if mode.marker_epoch_s > 0:
            return tr("moteur.refus.mesure_pendant_mode", mode=mode.label)
        if _publie_le_flux_du_mode(cls):
            return tr("moteur.refus.mesure_pendant_mode_flux", mode=mode.label)
        return None

    def _refus_test_hors_condition(self, mesure_spec):
        """Refuser le test d'un mode dont un réglage l'exclut (`ModeSpec.tests_si`) ? La raison, ou None.

        Le SSVEP à cibles PHYSIQUES : son test fait clignoter des disques à l'écran, que personne
        ne regarde. Les réglages lus sont ceux du mode qui tourne, sinon ceux retenus — ceux que
        « Tester » vient d'appliquer.
        """
        mode = next((m for m in registry.runnable() if m.test_id == mesure_spec.id), None)
        if mode is None or not mode.tests_si:
            return None
        cle, valeur, raison = mode.tests_si
        runtime = self.active.get(mode.id)
        reglages = dict(runtime.params) if runtime is not None else self._reglages_de(mode)
        return None if reglages.get(cle, valeur) == valeur else raison

    def _refus_reglage_pendant_test(self, spec, mesure):
        """Refuser de régler `spec` parce que SON test tourne ? La raison, ou None.

        Le test tourne sur les réglages qu'il a reçus au départ. Les changer en route ne change
        pas le test, mais change ceux que le mode gardera ensuite : le verdict parlerait alors
        d'une configuration qui n'est plus celle du mode, sans que rien ne le dise.
        """
        if mesure is None or mesure.terminee or not spec.test_id:
            return None
        if mesure.spec.id != spec.test_id:
            return None
        return tr("moteur.refus.reglage_pendant_test", mode=spec.label, test=mesure.spec.label)

    def _refus_mode_pendant_mesure(self, spec, mesure):
        """Refuser de démarrer `spec` parce qu'une mesure lit SES marqueurs ? La raison, ou None.

        Ici on interroge l'OBJET qui tourne, comme `_refus_mode_pendant_calibration` : c'est lui
        qui appelle `markers_murs`, donc lui qui vole — ou lui qui publie sur le flux du mode.
        """
        if spec is None or mesure is None or mesure.terminee:
            return None
        if getattr(mesure, "marker_mode_id", "") != spec.id:
            return None
        if spec.marker_epoch_s > 0:
            return tr("moteur.refus.mode_pendant_mesure", mode=spec.label)
        if _publie_le_flux_du_mode(mesure):
            return tr("moteur.refus.mode_pendant_mesure_flux", mode=spec.label)
        return None

    # --- le refus d'une SECONDE ACTIVITÉ, dans ses DEUX sens -------------------
    # Même discipline que les deux méthodes ci-dessus : une RAISON ou None, sur une copie prise
    # par l'appelant, et servie à la fois à `submit` (qui refuse tout de suite) et à la BOUCLE
    # (`_start_calibration`, `_start_mesure`), qui doit refuser une seconde fois — deux commandes
    # soumises dans la même fenêtre de sondage voient toutes les deux un moteur vierge.
    #
    # ⚠️ Le sens qu'on oublie est TOUJOURS le second. La porte se ferme naturellement dans le sens
    # où l'on pense en l'écrivant (« ne pas calibrer pendant une mesure ») et reste ouverte dans
    # l'autre, parce que rien ne la rappelle. Les deux sont donc écrits côte à côte, et les deux
    # sont testés (`core/modes/mesure.py`).

    def _refus_pour_calibration_en_cours(self, calibration):
        """Refuser une nouvelle activité parce qu'une CALIBRATION tourne ? La raison, ou None.

        `calibration` : une copie de `self.calibration` prise par l'appelant — `submit` tourne sur
        le fil de l'interface pendant que la boucle en démarre et en abandonne sur le sien.
        """
        if calibration is None or calibration.terminee:
            return None
        return tr("moteur.refus.calibration_en_cours", mode=calibration.spec.label)

    def _refus_pour_mesure_en_cours(self, mesure):
        """Refuser une nouvelle activité parce qu'une MESURE tourne ? La raison, ou None.

        `mesure` : une copie de `self.mesure`, pour la même raison que ci-dessus.
        """
        if mesure is None or mesure.terminee:
            return None
        return tr("moteur.refus.mesure_en_cours", mesure=mesure.spec.label)

    def _signale_echec(self, reseau, command, raison):
        """Dit à l'appelant réseau qu'une commande ACCEPTÉE a échoué dans la boucle.

        Sans jeton (la console), rien : elle voit l'échec dans `snapshot()` et au terminal.
        Un rappel qui lève ne doit pas tuer la boucle.
        """
        if reseau is None or self.sur_echec is None:
            return
        try:
            self.sur_echec(reseau, command, raison)
        except Exception as e:  # noqa: BLE001 - la boucle du moteur ne meurt pas d'un rappel
            print(f"[server] rappel d'échec en panne : {e}")

    def _start(self, ids, values, now, reseau=None, avant=None):
        """Démarre des modes. Ceux lancés ENSEMBLE partagent une seule phase de repos.

        `values` : `{mode_id: réglages}` imposés par l'appelant (les autotests), ou None. Sans
        eux, chaque mode part du MAGASIN (`self.reglages`) tel qu'il est au moment où la BOUCLE
        applique la commande — pas au moment où elle a été soumise. Entre les deux, un
        `set_params` accepté a pu écrire le magasin : le lire ici est ce qui le fait partir avec
        le démarrage, au lieu d'être effacé par des valeurs figées à la soumission.

        `avant` : `{mode_id: réglages}` du magasin AVANT que `submit` y écrive ceux de ce
        démarrage. Si le runtime refuse de se construire, le magasin les reprend (cf. plus bas).
        """
        demarres = []
        calibration = self.calibration     # une seule copie, pour tous les modes de ce lot
        mesure = self.mesure
        for spec in registry.MODES:            # ordre du registre : il arbitre les égalités
            if spec.id not in ids:
                continue
            impose = values is not None and spec.id in values
            reglages = dict(values[spec.id]) if impose else self._reglages_de(spec)
            if spec.id in self.active:
                # Le mode tourne déjà (un jeu qui redémarre renvoie son `start_mode`, ou deux
                # « démarrer » en file avant le même tour) : on ne recrée pas le runtime — le repos
                # déjà mesuré serait jeté —, mais ses réglages s'appliquent par le chemin de
                # `set_params`. Une panne ici n'arrête pas les autres modes du lot.
                try:
                    if impose:
                        self.reglages[spec.id] = dict(reglages)
                    self._set_params(spec.id, reglages)
                    # Une APPLICATION qui démarre un mode veut ses décisions : un mode décodé
                    # « pour l'affichage seulement » (case « publié » décochée) n'a pas de flux,
                    # donc ni elle (LSL) ni un appareil réseau (UDP) ne recevraient rien, alors
                    # que la réponse dit « déjà en route ». Il se republie.
                    runtime = self.active.get(spec.id)
                    if reseau is not None and runtime is not None and not runtime.published:
                        self._set_published(spec.id, True)
                except Exception as e:  # noqa: BLE001
                    print(f"[server] réglages de « {spec.id} » refusés au redémarrage : {e}")
                    self._signale_echec(reseau, "start_mode", message_erreur(e))
                continue
            refus = (self._refus_mode_pendant_calibration(spec, calibration)
                     or self._refus_mode_pendant_mesure(spec, mesure))
            if refus:
                # Le second contrôle, côté BOUCLE : `submit` a jugé sur un moteur où la
                # calibration n'était pas encore appliquée. Sans lui, `start_mode` et
                # `start_calibration` soumis dans la même fenêtre de sondage passent tous les deux.
                print(f"[server] démarrage refusé : {refus}")
                self._signale_echec(reseau, "start_mode", refus)
                continue
            try:
                runtime = spec.runtime_cls(spec, reglages, self)
                runtime.open()
            except Exception:
                # `validate` a accepté, le RUNTIME refuse (un modèle disparu, un modèle entraîné
                # sur une autre géométrie). Le magasin, écrit par `submit`, doit redire les
                # réglages d'avant — sinon `snapshot()` annonce ceux qui ont échoué, « Tester » les
                # relit, et le démarrage suivant échoue de nouveau. Seulement s'il porte ENCORE
                # ceux-ci : un `set_params` soumis depuis a écrit les siens (cf. `_set_params`).
                if (not impose and (avant or {}).get(spec.id) is not None
                        and self.reglages.get(spec.id) == dict(reglages)):
                    self.reglages[spec.id] = dict(avant[spec.id])
                raise
            self.active[spec.id] = runtime
            # Des réglages IMPOSÉS entrent au magasin : c'est avec eux que le mode a démarré. Ceux
            # du magasin y sont déjà — les réécrire ici effacerait un `set_params` accepté PENDANT
            # la construction du runtime (le chargement d'un modèle prend du temps).
            if impose:
                self.reglages[spec.id] = dict(reglages)
            self._last_tick[spec.id] = 0.0
            demarres.append(runtime)
        self._begin_shared_rest(demarres, now)
        for runtime in demarres:
            if runtime.spec.stream:
                print(f"[server] {runtime.spec.label} démarré — flux "
                      f"{stream_name(runtime.spec.stream)}"
                      + (" (silencieux pendant le repos)" if runtime.spec.rest else ""))

    def _lire(self):
        """La lecture d'un tour : `(eeg, ts)`, ou `(None, None)` — JAMAIS une exception.

        🔴 Deux règles : sans elles, une batterie à plat TUE le fil du moteur au lieu de produire
        la coupure attendue, reprise toute seule.
        1. **Pendant une coupure, on ne lit PAS la session.** `reouvrir()` la LIBÈRE avant de
           rouvrir ; si le casque ne répond pas (éteint, à plat), elle reste libérée, et BrainFlow
           LÈVE sur une session libérée (`BOARD_NOT_CREATED_ERROR:15`). Le fil mourait au tour
           qui suivait la première réouverture ratée. C'est `_surveille_liaison` qui réessaie.
        2. **Une lecture qui lève compte comme « aucun échantillon ».** C'est la surveillance de
           la liaison qui en juge ensuite (`DECROCHAGE_S`), jamais un traceback qui arrête tout.
           Le message part une fois au terminal, pour qu'on sache ce que BrainFlow a dit.
        """
        if self._liaison == "perdue":
            return None, None
        try:
            return self.acq.get_new_data()
        except Exception as e:  # noqa: BLE001 - une session morte casse de plusieurs façons
            raison = message_erreur(e)
            if raison != self._erreur_lecture:
                print(f"[server] ⚠️ lecture du casque impossible : {raison} — traité comme une "
                      f"coupure")
                self._erreur_lecture = raison
            return None, None

    def _surveille_liaison(self, now):
        """Appelée quand un tour n'a apporté AUCUN échantillon. True si la liaison est perdue.

        Au-delà de `decrochage_s` sans échantillon, la liaison est déclarée perdue : les séances
        minutées en cours sont annulées (leurs données auraient un trou), puis la session est
        ROUVERTE, un essai toutes les `reessai_s` — chaque essai bloque ce fil le temps que
        BrainFlow cherche le casque ; la console, elle, continue de lire `snapshot()`, qui ne
        prend aucun verrou. Au retour, le tampon repart vide et les modes refont leur repos : leur
        plancher a été mesuré sur un signal d'avant la coupure, et la réouverture redémarre
        l'amplificateur.
        """
        if self._dernier_echantillon is None:
            self._dernier_echantillon = now          # la chauffe de BrainFlow n'est pas une coupure
            return False
        if self._liaison == "ok":
            if now - self._dernier_echantillon < self.decrochage_s:
                return False
            self._liaison = "perdue"
            self._perdue_depuis = now
            self._tentatives = 0
            self._erreur_liaison = ""
            self._prochain_essai = now
            print(f"[server] ⚠️ liaison PERDUE : aucun échantillon depuis "
                  f"{now - self._dernier_echantillon:.1f} s — reconnexion")
            self._interrompt_seances(tr("moteur.liaison.seance_annulee"))
        if now < self._prochain_essai:
            return True
        self._tentatives += 1
        try:
            self.acq.reouvrir()
        except Exception as e:  # noqa: BLE001 - un casque éteint est l'attendu, pas un incident
            self._erreur_liaison = str(e) or type(e).__name__
            self._prochain_essai = time.perf_counter() + self.reessai_s
            print(f"[server] reconnexion {self._tentatives} échouée : {self._erreur_liaison}")
            return True
        retour = time.perf_counter()
        self._coupure_s = retour - self._perdue_depuis
        self._liaison = "ok"
        self._retablie_a = retour
        self._dernier_echantillon = retour
        self._erreur_lecture = ""            # une prochaine erreur de lecture sera de nouveau dite
        self.recent = np.zeros((0, len(CH_NAMES)))
        self.recent_ts = np.zeros((0,))
        print(f"[server] liaison RÉTABLIE après {self._coupure_s:.1f} s "
              f"({self._tentatives} tentative(s)) — les modes refont leur repos")
        self._begin_shared_rest(list(self.active.values()), retour)
        return True

    def _interrompt_seances(self, raison):
        """Annule l'entraînement et le test en cours, en disant pourquoi. Rien n'est entraîné."""
        for seance in (self.calibration, self.mesure):
            if seance is not None and not seance.terminee:
                seance.probleme = raison
                seance.cancel()

    def _etat_casque(self):
        """Batterie et paquets perdus, lus dans les voies de service du casque.

        ⚠️ La batterie du board de TEST est FABRIQUÉE (tirée entre 80 et 100 %, vérifié) : elle
        n'est pas rendue, un « batterie 93 % » sur du signal synthétique serait une invention de
        plus sur un écran qui en porte déjà une.
        """
        historique = list(self._paquets)
        perte = None
        if len(historique) >= 2:
            recus = historique[-1][1] - historique[0][1]
            perdus = historique[-1][2] - historique[0][2]
            if recus + perdus > 0:
                perte = round(100.0 * perdus / (recus + perdus), 2)
        # Le board de test n'a ni batterie (la sienne est tirée au hasard) ni liaison radio : ni
        # l'une ni l'autre ne s'affiche, plutôt que 4 barres sur un signal fabriqué.
        if self.synthetic:
            return {"batterie_pc": None, "perte_pc": None, "signal_barres": None,
                    "perdus_total": 0}
        # Liaison coupée : la batterie est INCONNUE, pas « la dernière lue » (figée à 0 % à la
        # coupure, elle afficherait « recharge le casque » sur un casque allumé et chargé).
        batterie = None if self._liaison == "perdue" else self.acq.batterie
        return {
            "batterie_pc": None if batterie is None else round(float(batterie)),
            "perte_pc": perte,
            "signal_barres": barres_liaison(perte, perdue=self._liaison == "perdue"),
            "perdus_total": int(getattr(self.acq, "paquets_perdus", 0)),
        }

    def _etat_liaison(self):
        """La liaison avec le casque, pour la console. Durées calculées maintenant."""
        now = time.perf_counter()
        return {
            "etat": self._liaison,
            "depuis_s": (None if self._perdue_depuis is None or self._liaison == "ok"
                         else round(now - self._perdue_depuis, 1)),
            "tentatives": self._tentatives,
            "erreur": self._erreur_liaison,
            "retablie_depuis_s": (None if self._retablie_a is None
                                  else round(now - self._retablie_a, 1)),
            "coupure_s": None if self._coupure_s is None else round(self._coupure_s, 1),
        }

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
        # Le magasin `self.reglages` n'est PAS écrit ici : `submit` l'a déjà fait avant de mettre
        # la commande en file, et on n'arrive ici QUE par cette file. Il n'est touché ici que pour
        # être REMIS quand le runtime refuse (cf. plus bas).
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
        # Dans l'autre ordre, l'ancien runtime resterait dans `active` avec son flux déjà fermé mais
        # `published = True` : la console afficherait « publié, en décodage » alors que plus rien
        # ne sortirait du réseau. Aucun doublon de flux à craindre ici — un constructeur n'ouvre aucun
        # outlet, c'est `open()` qui le fait, et il n'est appelé qu'après la fermeture.
        try:
            runtime = spec.runtime_cls(spec, values, self)
        except Exception:
            # `validate` a accepté, le RUNTIME refuse (c-VEP : modèle calibré sur un autre nombre
            # de cibles). Le mode continue sur `avant` ; le magasin, écrit par `submit`, doit le
            # redire — sinon `snapshot()` annonce le réglage refusé et « Tester » le relit.
            # Seulement s'il porte ENCORE ce réglage-ci : un `set_params` soumis depuis a écrit le
            # sien, qu'une remise aveugle effacerait.
            if self.reglages.get(mode_id) == dict(values):
                self.reglages[mode_id] = dict(avant)
            raise
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
        # Le SECOND sens de la même porte : une mesure tourne, et `submit` a jugé sur un moteur où
        # `start_mesure` n'était pas encore appliqué. Sans ce contrôle-ci, côté boucle, les deux
        # protocoles tourneraient bel et bien ensemble.
        refus_mesure = self._refus_pour_mesure_en_cours(self.mesure)
        if refus_mesure:
            print(f"[server] calibration refusée : {refus_mesure}")
            return
        spec = registry.get(mode_id)
        # Le second contrôle du VOL DE MARQUEURS, côté boucle — jumeau exact de celui de `_start`,
        # et pour la même course : `submit` a jugé sur un moteur où `start_mode` n'était pas
        # encore appliqué.
        refus = self._refus_calibration_pendant_mode(spec, self.active)
        if refus:
            print(f"[server] calibration refusée : {refus}")
            return
        # Un candidat encore en attente appartient à la séance PRÉCÉDENTE. Le garder pendant
        # qu'une nouvelle tourne laisserait « Enregistrer » actif sur un résultat qui n'est plus
        # celui qu'on regarde — et personne ne saurait lequel des deux part dans `data/`.
        self._efface_candidat("une nouvelle calibration commence")
        # ⚠️ Lâcher la calibration PRÉCÉDENTE, pas seulement son candidat. `_candidat_de` la
        # référence, et une calibration terminée avec succès garde ses époques (`_enregistre`,
        # plusieurs minutes de signal) et une référence vers le moteur entier : seul `cancel()`
        # les libère, et `_terminer` ne l'appelle pas. Sans cela, chaque séance de la journée
        # resterait vivante en mémoire derrière la suivante.
        if self._candidat_de is not None:
            self._candidat_de.cancel()      # sur une calibration « fini », ne change QUE ça
            self._candidat_de = None
        # `dossier=` : le dossier CANDIDAT, et il est passé à TOUTES les calibrations sans
        # distinction — l'argument vit sur `CalibrationRuntime`, pas sur telle ou telle
        # sous-classe. C'est ce qui empêche une calibration future de retomber sur `data/` :
        # elle n'a plus de défaut à retomber dessus (cf. `dossier_ou_lever`).
        self.calibration = spec.calibration.runtime_cls(spec, values, self,
                                                        dossier=self._dossier_candidat())
        print(f"[server] {spec.calibration.label or spec.label} : "
              f"{self.calibration.total()} essais, "
              f"≈ {self.calibration.duree_estimee_s() / 60:.0f} min — "
              f"stabilisation {self.calibration.warmup_s:.0f} s d'abord")

    def _start_mesure(self, mesure_id, values):
        """Construit la mesure. Appelée par la boucle, jamais par le fil d'une interface.

        ⚠️ **Les DEUX refus sont refaits ICI**, et ce n'est pas de la ceinture et des bretelles :
        `submit()` a jugé sur l'état du moteur à l'instant où la commande a été SOUMISE. Deux
        commandes soumises dans la même fenêtre de sondage — `start_mesure` et
        `start_calibration`, ou deux `start_mesure` sur un double-clic — ont toutes les deux vu un
        moteur vierge et ont donc été acceptées toutes les deux. Sans ce second contrôle, la
        seconde écraserait SILENCIEUSEMENT la première, et les deux protocoles prélèveraient dans
        le même tampon. C'est le jumeau exact du contrôle de `_start_calibration`.
        """
        refus = (self._refus_pour_mesure_en_cours(self.mesure)
                 or self._refus_pour_calibration_en_cours(self.calibration))
        if refus:
            print(f"[server] mesure refusée : {refus}")
            return
        spec = registry.get_mesure(mesure_id)
        if spec is None or spec.runtime_cls is None:
            # `submit` a déjà refusé les deux cas ; on ne construit pas un `None(spec, …)` pour
            # autant si la commande arrive par un autre chemin.
            print(f"[server] mesure ignorée : « {mesure_id} » est inconnue ou n'est pas livrée")
            return
        # Le vol de marqueurs, côté BOUCLE : `start_mode` et `start_mesure` soumis dans la même
        # fenêtre de sondage voient tous les deux un moteur où aucun des deux ne tourne encore.
        refus = self._refus_mesure_pendant_mode(spec, dict(self.active))
        if refus:
            print(f"[server] mesure refusée : {refus}")
            return
        # ⚠️ Aucun `dossier=`, à la différence d'une calibration : une mesure n'écrit RIEN. Son
        # runtime n'accepte même pas l'argument (cf. `modes/mesure.py`), pour qu'un ajout distrait
        # échoue bruyamment au lieu de faire entrer un verdict de séance dans `data/`.
        self.mesure = spec.runtime_cls(spec, values, self)
        print(f"[server] {spec.label} : ≈ {self.mesure.duree_estimee_s() / 60:.1f} min, "
              f"{self.mesure.total()} fenêtre(s) prélevée(s) — stabilisation "
              f"{self.mesure.warmup_s:.0f} s d'abord. Rien ne sera écrit sur le disque.")

    def _start_enregistrement(self, mode_id):
        """Ouvre le fichier de séance. Appelée par la BOUCLE, jamais par le fil d'une interface.

        ⚠️ **Le refus est REFAIT ici**, comme pour `_start_mesure` et `_start_calibration`, et
        pour la même raison : `submit` a jugé sur l'état du moteur à l'instant de la SOUMISSION.
        Deux `start_enregistrement` soumises dans la même fenêtre de sondage — un double-clic y
        suffit — ont toutes les deux vu un moteur vierge. Sans ce second contrôle, la seconde
        remplacerait silencieusement la première : le premier fichier resterait ouvert, sans
        bilan, et personne ne saurait lequel des deux porte la séance.

        ⚠️ **Le NOM du fichier se décide ici**, pas à la soumission — cf. le commentaire de
        `submit`. C'est ce qui garantit qu'aucun chemin n'est annoncé pour un fichier qui ne sera
        pas créé, et accessoirement que `chemin_libre` juge du disque depuis le seul fil qui y
        écrit.
        """
        en_cours = self.enregistrement
        if en_cours is not None and en_cours.actif:
            print(f"[server] enregistrement refusé : un autre écrit déjà dans {en_cours.chemin}")
            return
        runtime = self.active.get(mode_id)
        if runtime is None:
            # Le mode s'est arrêté entre la soumission et l'application. On ne crée AUCUN fichier :
            # un fichier vide se lit après coup comme une séance ratée.
            print(f"[server] enregistrement annulé : « {mode_id} » s'est arrêté entre-temps")
            return
        # `chemin_libre` n'écrase jamais rien : le format d'horodatage a une résolution d'une
        # seconde, et deux enregistrements démarrés dans la même produiraient sinon le même nom.
        chemin = chemin_libre(
            self.seances_dir,
            f"moteur_{runtime.spec.stream}_{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
        enr = _Enregistrement(chemin, mode_id, stream_name(runtime.spec.stream))
        try:
            enr.ouvrir(runtime, instance=self.instance, fs_hz=self.acq.fs)
        except OSError as e:
            # Dossier non inscriptible, disque plein, antivirus : ça se dit MAINTENANT, pas à la
            # fin d'une séance qu'on croyait enregistrée.
            print(f"[server] enregistrement IMPOSSIBLE ({chemin}) : {e}")
            return
        self.enregistrement = enr
        print(f"[server] enregistrement de « {runtime.spec.label} » -> {chemin} "
              f"(une ligne par décision publiée ; rien n'est écrit dans {self.data_dir})")

    # --- le candidat : produit, montré, puis retenu ou jeté --------------------
    # `_entrainer` écrit dans `self.calib_dir`. Le résultat est ADOPTÉ ici (une fois), affiché par
    # la console, et ne rejoint `data/` que sur `save_calibration`. Trois gestes, dans cet ordre :
    # produire, annoncer, puis seulement écrire dans `data/`.

    # ⚠️ Les clés de `_entrainer` qui portent un CHEMIN DE FICHIER, et rien d'autre. Une clé
    # oubliée ici ne lève rien : son fichier n'est ni déplacé à l'enregistrement (le modèle reste
    # dans le temporaire, donc perdu à la fermeture) ni supprimé au rejet. `modele_rcca` est le
    # SECOND modèle du c-VEP — le seul mode du produit à en produire deux par séance, un par
    # décodeur. Une valeur `None` (séance c-VEP interrompue : pas de rCCA écrivable) est ignorée
    # par les deux boucles, qui testent `os.path.isfile`.
    # ⚠️ **L'ORDRE compte, et il est l'inverse de l'ordre naturel.** L'`enregistrement` (le .npz
    # des époques) part EN PREMIER, les modèles ensuite — exactement la règle que les quatre
    # `_entrainer` s'appliquent à l'écriture, et pour la même raison, qu'ils écrivent chacun en
    # toutes lettres : si un déplacement échoue à mi-course (verrou antivirus sur `data/`, disque
    # plein), ce qui reste dans `data/` doit être INOFFENSIF. Un `.npz` orphelin ne l'est : rien
    # ne le liste, rien ne le propose. Un MODÈLE orphelin, lui, est découvert par son catalogue,
    # élu « le plus récent », et proposé par défaut à la séance suivante — sans son enregistrement
    # ni sa provenance.
    _FICHIERS_CANDIDAT = ("enregistrement", "modele", "modele_rcca")

    def _dossier_candidat(self):
        """Le dossier temporaire de CE moteur, créé au premier besoin. Jamais `data/`.

        Appelée par `_start_calibration` et par elle seule : c'est le seul moment où quelqu'un a
        quelque chose à y écrire. `close()` le supprime ; un appel ultérieur en recrée un — rien
        ici ne dépend de sa persistance, et un moteur qui ne calibre jamais n'en a jamais.
        """
        if not self.calib_dir or not os.path.isdir(self.calib_dir):
            self.calib_dir = tempfile.mkdtemp(prefix=CALIB_TMP_PREFIX)
        return self.calib_dir

    def _adopte_candidat(self):
        """Ramasse le résultat d'une calibration qui vient d'aboutir. Appelée à chaque tour.

        Idempotente par `_candidat_de` : le résultat d'une calibration donnée n'est adopté qu'une
        seule fois, sans quoi un candidat enregistré (donc remis à None) serait ré-adopté au tour
        suivant, avec des chemins qui n'existent plus.
        """
        calib = self.calibration
        if calib is None or calib is self._candidat_de:
            return
        if calib.phase != "fini" or not calib.resultat:
            return
        self._candidat_de = calib
        self.candidat = calib.resultat
        visibles = self._candidats_visibles()
        if visibles:
            # Le garde qui protège les calibrations À VENIR (ErrP, c-VEP). Un candidat qui
            # correspond à un motif de découverte redeviendrait « le modèle chargeable le plus
            # récent » dès que ce dossier serait scanné — le défaut qu'on ferme, rouvert par sa
            # propre correction. On le DIT fort plutôt que de jeter un modèle qui vaut plusieurs
            # minutes de séance.
            print(f"[server] ⚠️ le candidat de « {calib.spec.label} » est DÉCOUVRABLE par un "
                  f"catalogue de modèles : {', '.join(os.path.basename(v) for v in visibles)}. "
                  f"Sa calibration doit écrire avec `prefixe=CALIB_CANDIDAT_PREFIXE` "
                  f"(cf. core/config.py) — sans ça, un candidat oublié se fait ÉLIRE.")
        print(f"[server] candidat prêt : {os.path.basename(self.candidat.get('modele') or '?')} "
              f"— rien n'est encore dans {self.data_dir}. « Enregistrer » ou « Jeter ».")

    def _candidats_visibles(self, dossier=None):
        """Ce que les QUATRE catalogues de modèles découvriraient dans le dossier candidat.

        Doit rendre `[]`. Les modules sont importés ICI et non en tête : ils ne servent qu'à ce
        contrôle, qui ne tourne qu'à la fin d'une calibration — et `modeles_disponibles` CHARGE
        chaque fichier qui correspond, ce qui ne coûte rien quand la réponse est vide.
        """
        from core import cvep_models, errp_models, mi_models, p300_models

        dossier = self.calib_dir if dossier is None else dossier
        if not dossier or not os.path.isdir(dossier):
            return []
        trouves = []
        for module in (mi_models, p300_models, errp_models, cvep_models):
            try:
                trouves.extend(module.modeles_disponibles(dossier))
            except Exception as e:  # noqa: BLE001 - un catalogue qui casse ne doit pas tuer la boucle
                print(f"[server] catalogue {module.__name__} illisible sur le dossier "
                      f"candidat : {type(e).__name__} : {e}")
        return trouves

    def _efface_candidat(self, pourquoi):
        """Supprime les fichiers du candidat en attente et oublie le verdict. Sans effet s'il
        n'y en a pas. Ne touche JAMAIS à `data/` : ne sont effacés que des chemins du candidat."""
        candidat = self.candidat
        if not candidat:
            self.candidat = None
            return
        for cle in self._FICHIERS_CANDIDAT:
            chemin = candidat.get(cle)
            if chemin and os.path.isfile(chemin):
                try:
                    os.remove(chemin)
                except OSError as e:
                    print(f"[server] candidat non supprimé ({chemin}) : {e}")
        # Oublié APRÈS les fichiers : `candidat is None` veut dire « le disque est propre ».
        self.candidat = None
        print(f"[server] candidat jeté — {pourquoi}. Aucun modèle n'a rejoint {self.data_dir}.")

    def _save_calibration(self):
        """DÉPLACE les fichiers du candidat vers `data_dir`, sous un nom libre. Jamais une copie.

        Déplacer et non copier : une copie laisserait l'original dans le temporaire — bénin, il
        sera balayé — mais surtout ferait exister le MÊME modèle deux fois, sous deux noms, le
        temps que le nettoyage passe. `shutil.move` et non `os.replace` : le dossier temporaire du
        système peut vivre sur un autre volume, où `os.replace` lève `OSError`.

        `chemin_libre` garantit qu'on n'écrase rien : le format d'horodatage a une résolution
        d'une seconde, et `data/` porte des enregistrements qui ne se refont pas.
        """
        candidat = self.candidat
        if not candidat:
            print("[server] rien à enregistrer : aucune calibration en attente de décision")
            return
        os.makedirs(self.data_dir, exist_ok=True)
        retenu = dict(candidat)
        for cle in self._FICHIERS_CANDIDAT:
            source = candidat.get(cle)
            if not source or not os.path.isfile(source):
                continue
            destination = chemin_libre(self.data_dir, nom_retenu(source))
            shutil.move(source, destination)
            retenu[cle] = destination
            print(f"[server] enregistré : {destination}")
        if retenu.get("modele"):
            retenu["nom"] = os.path.basename(retenu["modele"])
            self._retenir_modele(self._candidat_de or self.calibration, retenu["modele"])
        # Le verdict reste LISIBLE à l'écran, avec les chemins définitifs : on remplace le dict
        # d'un coup (une affectation d'attribut est atomique) plutôt que de le modifier en place,
        # que la console pourrait lire à moitié réécrit depuis son propre fil.
        if self.calibration is not None:
            self.calibration.resultat = retenu
        self.candidat = None

    def _retenir_modele(self, calib, chemin):
        """Pose le modèle qu'on vient d'ENREGISTRER comme réglage « model » du mode, au magasin.

        🔴 Réentraîner est le cas NORMAL d'une séance : le magasin tient déjà le modèle d'avant.
        Si « Enregistrer » rangeait le nouveau dans `data/` sans y toucher, la page du mode
        garderait l'ancien sélectionné et « Tester » testerait l'ANCIEN — deux noms qui ne
        diffèrent que par l'horodatage, donc sans que rien ne se remarque. Le modèle qu'on vient
        de garder est celui qu'on veut tester.

        Validé par le CONTRAT avant d'être écrit, comme tout ce qui entre au magasin : un modèle
        qu'aucun catalogue ne retrouve (un `data_dir` détourné, un nom mal formé) ne s'y pose pas —
        on le dit, et le magasin garde ce qu'il avait. Seul « model » change. Le mode n'est PAS
        redémarré s'il tourne : c'est un réglage retenu, en vigueur au prochain démarrage, au
        prochain test, ou au prochain réglage de ce mode (qui se fusionne sur le magasin).
        """
        spec = getattr(calib, "spec", None)
        if spec is None or not any(p.key == "model" for p in getattr(spec, "params", ())):
            return
        base = self._reglages_de(spec)
        base["model"] = chemin
        valeurs, raison = contract.validate(spec, base)
        if valeurs is None:
            print(f"[server] ⚠️ modèle enregistré, mais PAS posé comme réglage de "
                  f"« {spec.label} » : {raison}")
            return
        self.reglages[spec.id] = dict(valeurs)
        print(f"[server] « {spec.label} » : réglage « model » -> {os.path.basename(chemin)} "
              f"(c'est lui que « Tester » utilisera)")

    def _discard_calibration(self):
        """Jette le candidat ET l'écran de verdict : plus rien à décider, plus rien à montrer."""
        if not self.candidat and self.calibration is None:
            print("[server] rien à jeter : aucune calibration en attente de décision")
            return
        if self.calibration is not None:
            # `cancel()` sur une calibration déjà terminée ne change pas sa phase, mais il libère
            # ses époques et sa référence vers le moteur — le même cycle que les modes actifs.
            self.calibration.cancel()
        self.calibration = None
        self._candidat_de = None
        # EN DERNIER : `_efface_candidat` ne pose `candidat = None` qu'une fois les fichiers
        # partis, et l'écran de verdict est déjà effacé — qui lit `candidat is None` lit un état
        # FINI. Dans un autre ordre, on pourrait voir `None` avec le fichier encore là et le
        # verdict encore affiché (suppression lente, Windows qui scanne un fichier fraîchement
        # copié) : un échec intermittent, attribué à tort à une machine chargée.
        self._efface_candidat("« Jeter » demandé")

    def close(self):
        """Libère ce que CE moteur a créé sur le disque. Idempotente, appelable de partout.

        ⚠️ **Inconditionnelle**, et appelée aussi bien par le `finally` de `run()` que par la
        console qui se ferme : si l'interface disparaît entre l'entraînement et la décision, aucun
        candidat ne doit survivre. Un `.joblib` orphelin dans un dossier temporaire est inoffensif
        tant qu'il y reste — mais c'est un modèle EEG d'une personne identifiable, et le premier
        remaniement qui le déplacerait le ferait élire.

        Le dossier est SUPPRIMÉ, pas vidé. Une calibration démarrée après un `close()` en obtient
        un neuf (`_dossier_candidat`), et le `close()` suivant le reprendra : rien ne dépend de sa
        persistance.
        """
        self._efface_candidat("le moteur se ferme")
        self._candidat_de = None
        # L'enregistrement se REFERME proprement (bilan compris), il ne se supprime pas : à la
        # différence d'un candidat de calibration, ce fichier est exactement ce qu'on voulait
        # garder. Chaque ligne est déjà vidée sur le disque, donc ce `fermer()` ne sauve pas les
        # verdicts — il sauve le BILAN qui dit combien il y en a, et donc la possibilité de savoir
        # qu'une séance a été tronquée.
        if self.enregistrement is not None:
            self.enregistrement.fermer()
        if self.calib_dir:
            shutil.rmtree(self.calib_dir, ignore_errors=True)
            self.calib_dir = None

    def retirer_flux(self):
        """Retire du réseau les flux `quality`, `status` et `replies` de CE moteur, sans attendre
        le ramasse-miettes.

        Pour un moteur qu'on JETTE : la console qui repose la question après un casque qui refuse
        de s'ouvrir. Le moteur suivant publie sous les mêmes noms, et un client qui tomberait sur
        l'ancien flux, muet, conclurait que rien n'est publié. À n'appeler qu'une fois le fil du
        moteur terminé : il ne publie plus rien ensuite.
        """
        self.quality_out = self.status_out = None
        self.pilotage.fermer()

    # --- API de commande interne --------------------------------
    # La console et l'adaptateur réseau (`core/pilotage.py`) passent tous les deux PAR ICI.
    # Un seul chemin à tester, et le protocole de contrôle reste remplaçable sans réécrire le
    # moteur.
    #
    # Les commandes ne sont PAS appliquées par le fil qui les soumet : elles sont mises en file
    # et exécutées par la boucle. C'est ce qui garantit que la session BrainFlow n'est touchée
    # que depuis un seul fil — la partager entre l'interface et l'acquisition produirait des
    # corruptions qu'aucun test ne rattraperait.

    COMMANDS = ("start_mode", "propose_params", "stop_mode", "set_params", "set_published",
                "recalibrate", "start_calibration", "cancel_calibration", "save_calibration",
                "discard_calibration", "start_mesure", "cancel_mesure",
                "start_enregistrement", "stop_enregistrement", "stop",
                "chercher_applications", "connecter", "deconnecter", "lancer_decodage",
                "identifier")

    # Pendant une connexion, les SEULES commandes de la CONSOLE que le moteur accepte. Une liste
    # BLANCHE : une commande ajoutée demain est refusée pendant une connexion tant que personne ne
    # l'a déclarée sûre ici. « Enregistrer les verdicts » observe sans rien changer ; `stop` ferme
    # la console.
    PERMISES_PENDANT_CONNEXION = ("deconnecter", "lancer_decodage", "start_enregistrement",
                                  "stop_enregistrement", "stop")

    # Les commandes de la CONNEXION viennent de la console, jamais d'une application : avec un
    # jeton réseau, `submit` les refuse avant de prendre `_connexion_verrou`, qu'elles reprennent.
    # « Identifier » en est : une application ne fait pas clignoter l'appareil d'un autre.
    COMMANDES_CONSOLE = ("chercher_applications", "connecter", "deconnecter", "lancer_decodage",
                         "identifier")

    def _mode_du_flux(self, nom):
        """Le `ModeSpec` ACTIF qui publie ce flux, ou (None, raison). Ne lève jamais.

        Accepte le nom PUBLIC (`EEG_API_Unicorn_decoded_ssvep`) comme le suffixe
        (`decoded_ssvep`) : la console désigne ce qu'elle a vu sur le réseau — donc le nom
        complet —, alors qu'un appel écrit à la main désigne naturellement le suffixe du contrat.
        Les refuser l'un ou l'autre serait un piège dont la seule cause est un préfixe.
        """
        suffixe = str(nom or "")
        prefixe = stream_name("")
        if suffixe.startswith(prefixe):
            suffixe = suffixe[len(prefixe):]
        actifs = dict(self.active)     # une copie, comme partout ici : `submit` ne lève jamais
        publiables = [s.stream for s in registry.MODES if s.stream]
        for spec in registry.MODES:
            if spec.stream and spec.stream == suffixe:
                if spec.id not in actifs:
                    # Refusé plutôt qu'un fichier vide : il se lirait après coup comme une séance
                    # ratée, pas comme un mode qu'on a oublié de lancer.
                    return None, tr("moteur.refus.enregistrement_mode_arrete", mode=spec.label)
                return spec, ""
        return None, tr("moteur.refus.flux_inconnu", flux=nom,
                        liste=", ".join(stream_name(s) for s in publiables))

    def _calibration_de(self, mode_id):
        """(spec, None) si ce mode a une calibration que le moteur sait jouer, sinon (None, raison)."""
        spec = registry.get(mode_id)
        if spec is None:
            connus = ", ".join(s.id for s in registry.MODES if s.calibration is not None)
            return None, tr("moteur.refus.mode_inconnu_calibration",
                            id=contract.recopie(mode_id, brut=True), liste=connus)
        if spec.calibration is None:
            return None, tr("moteur.refus.sans_calibration", mode=spec.label)
        if spec.calibration.runtime_cls is None:
            # Une calibration DÉCLARÉE mais dont le runtime n'est pas encore livré : dire « pas
            # encore livrée » plutôt que d'inventer une cause.
            return None, tr("moteur.refus.calibration_pas_livree", mode=spec.label)
        return spec, None

    def valider_calibration(self, mode_id, params=None):
        """(réglages complets, None) si `start_calibration` accepterait cet entraînement, sinon
        (None, raison) — sans RIEN changer : ni file, ni état, ni disque.

        La console l'appelle au clic sur « Commencer », AVANT le contrôle de liaison et avant
        d'arrêter le décodage du mode. Sans elle, une coupure haute à 50 Hz sur un MI plafonné à
        40 ne serait refusée qu'au `start_calibration` : le décodage serait déjà arrêté, et le
        flux de l'application de l'étudiant coupé pour rien. Aucune validation n'est recopiée côté
        interface : c'est CETTE méthode que `submit("start_calibration")` appelle aussi.

        ⚠️ Un seul refus n'y est PAS : le vol de marqueurs (le mode décode pendant sa propre
        calibration). La console le lève elle-même en arrêtant le mode — le refuser ici
        interdirait justement le geste qu'elle s'apprête à faire. `submit` le fait avant d'appeler
        cette méthode.
        """
        spec, raison = self._calibration_de(mode_id)
        if spec is None:
            return None, raison
        # ⚠️ Ce mode n'a PAS besoin d'être démarré : c'est même le cas normal. Le mode MI refuse de
        # démarrer sans modèle, or c'est justement la calibration qui en produit un.
        # Copie LOCALE de `self.calibration`, prise UNE fois : la boucle peut la remettre à `None`
        # entre deux lectures (arrêt du moteur, cf. le `finally` de `run()`) — `submit` promet en
        # toutes lettres de ne JAMAIS lever, y compris depuis le fil de l'interface pendant que la
        # boucle tourne sur le sien. Trois lectures de `self.calibration` de suite (`is not None`,
        # `.terminee`, `.spec.label`) couraient ce risque ; une seule variable locale l'élimine par
        # construction, comme le fait déjà `_status_key`.
        en_cours = self.calibration
        if en_cours is not None and not en_cours.terminee:
            return None, tr("moteur.refus.calibration_deja", mode=en_cours.spec.label)
        # ⚠️ Et le SECOND sens de la même porte, celui qu'on oublie : une MESURE tourne. Placé ici,
        # AVANT `contract.validate`, pour la même raison que le refus du vol de marqueurs dans
        # `submit` — c'est une propriété de l'ÉTAT du moteur, pas des réglages soumis, et le faire
        # passer après ferait dépendre le message de l'existence d'un modèle dans `data/`.
        refus_mesure = self._refus_pour_mesure_en_cours(self.mesure)
        if refus_mesure:
            return None, refus_mesure
        return contract.validate(spec.calibration, params or {})

    @staticmethod
    def _avertissement(textes):
        """Les avertissements d'un accusé, joints en un seul texte réécrivable, ou None."""
        return joint(" ", textes) if textes else None

    def _valider_reglages(self, spec, runtime, nouveaux):
        """Le chemin COMMUN de `set_params` et de `start_mode` : fusionne `nouveaux` sur les
        réglages courants, les valide, et prépare les avertissements. Ne pose RIEN.

        Les réglages courants sont ceux du MAGASIN (ou les défauts), que le mode tourne ou non :
        le magasin porte le dernier réglage ACCEPTÉ, y compris celui qui attend encore dans la
        file. Fusionner sur `runtime.params` (l'état appliqué) annulerait ce dernier. `runtime`
        ne sert qu'aux avertissements. Rend `(valeurs, textes, None)` ou `(None, None, raison)`.
        """
        base = self._reglages_de(spec)
        base.update(nouveaux or {})
        values, reason = contract.validate(spec, base)
        if values is None:
            return None, None, reason
        return values, self._textes_de_reglage(spec, runtime, values), None

    def _textes_de_reglage(self, spec, runtime, values):
        """Les avertissements d'un jeu de réglages validé : ceux du contrat, plus « le flux de
        marqueurs ne change qu'au redémarrage » quand le mode tourne (`runtime`) et que le nom
        demandé n'est pas celui que le moteur ÉCOUTE vraiment.

        On compare au nom de l'inlet, pas à `runtime.params` : la boucle écrit la nouvelle valeur
        dans le runtime tout de suite, mais l'inlet reste sur l'ancien nom jusqu'à ce que le mode
        (et tout autre mode à marqueurs, car ils partagent l'inlet) soit relancé. Comparer au
        runtime ferait taire l'avertissement au deuxième envoi du même nom.
        """
        textes = contract.avertissements(spec, values)
        if runtime is not None and "stream_in" in values:
            inlet = self.marker_inlet           # une seule lecture : la boucle peut le lâcher
            ecoute = inlet.nom if inlet is not None else runtime.params.get("stream_in")
            if ecoute != values["stream_in"]:
                textes.append(tr("moteur.reglage.stream_in_au_redemarrage", mode=spec.label))
        return textes

    def _mettre_en_file(self, command, params, reseau=None):
        """Met une commande dans la file de la boucle, avec le jeton de son appelant réseau (ou
        None pour la console). Le jeton revient à `sur_echec` si la commande échoue plus tard."""
        self._commands.put((command, params, reseau))

    # --- juger sur ce que le moteur FERA, pas sur l'instant présent -----------------------------
    # `submit` répond tout de suite, la boucle applique ~50 ms plus tard. Une application qui
    # attend chaque réponse avant d'envoyer la suivante tombe souvent entre les deux : sa commande
    # précédente est ACCEPTÉE mais pas encore appliquée. Juger sur `self.active` répondait alors
    # « déjà arrêté » à un `stop_mode` qui suivait un `start_mode` encore en file — et le mode
    # finissait en marche. D'où trois règles : `start_mode` et `stop_mode` vont TOUJOURS dans la
    # file (la boucle sait ignorer ce qui est déjà fait) ; les réglages se fusionnent sur le
    # magasin (`_valider_reglages`) ; et « deja » se lit sur ce que le moteur fera (ci-dessous).

    def _tourneront(self, ids):
        """Parmi `ids`, ceux qui TOURNERONT une fois la file de commandes vidée.

        Le dernier `start_mode` ou `stop_mode` accepté et pas encore appliqué décide ; sans lui,
        c'est l'état appliqué (`self.active`). ⚠️ L'ordre des deux lectures compte : la file
        D'ABORD, l'état ENSUITE. La boucle applique une commande PUIS l'efface de la file
        (`_attente_appliquee`) : dans l'autre ordre, une commande appliquée entre les deux lectures
        ne se verrait ni dans l'état (lu trop tôt) ni dans la file (lue trop tard).
        """
        attente = dict(self._en_attente)        # copies prises d'un coup, jamais les dicts vivants
        actifs = dict(self.active)
        return [i for i in ids
                if (attente[i][1] == "start" if i in attente else i in actifs)]

    def _inscrire_marche(self, command, ids, reseau, avant=None):
        """Met en file un `start_mode` ou un `stop_mode`, et l'inscrit comme le dernier mot de ces
        modes. Rend ceux qui tournaient déjà (`_tourneront`), lus au MÊME instant, sous le verrou :
        deux appelants (la console, l'application) ne peuvent pas s'intercaler entre la lecture
        et l'inscription."""
        with self._en_attente_verrou:
            tournaient = self._tourneront(ids)
            self._en_attente_n += 1
            numero = self._en_attente_n
            sens = "start" if command == "start_mode" else "stop"
            for mode_id in ids:
                self._en_attente[mode_id] = (numero, sens)
            params = {"ids": list(ids)} if command == "start_mode" else {"id": ids[0]}
            params["n"] = numero
            if avant is not None:
                params["avant"] = avant
            self._mettre_en_file(command, params, reseau)
        return tournaient

    def _attente_appliquee(self, params):
        """La boucle vient d'appliquer ce `start_mode`/`stop_mode` : il n'attend plus. Seulement
        s'il est ENCORE le dernier mot du mode — une commande soumise depuis garde sa place."""
        numero = params.get("n")
        if numero is None:          # mise en file sans `_inscrire_marche` (certains autotests)
            return
        ids = params.get("ids") or ([params["id"]] if params.get("id") else [])
        with self._en_attente_verrou:
            for mode_id in ids:
                if self._en_attente.get(mode_id, (None, None))[0] == numero:
                    del self._en_attente[mode_id]

    def submit(self, command, reseau=None, **params):
        """Met une commande en file. Retourne un accusé, PAS le résultat (appliqué plus tard).

        Une exception à la règle « accusé seulement » : la VALIDITÉ est vérifiée ici, tout de
        suite. Le refus d'une commande mal formée est une propriété du message, pas de l'état du
        moteur, et la renvoyer immédiatement évite à l'étudiant de chercher pourquoi son réglage
        n'a rien fait. Ce que `submit` ne promet toujours pas, c'est que la commande ait été
        APPLIQUÉE : ça s'observe sur `snapshot()` ou sur le flux `status`.

        `reseau` : le jeton d'une commande de l'APPLICATION (`core/pilotage.py`), None pour la
        console. Une commande de la connexion (`COMMANDES_CONSOLE`) qui porte un jeton est
        refusée. En écoute sur demande, une commande de l'application est jugée EN ENTIER sous
        `_connexion_verrou` : « Déconnecter » et le départ de l'application passent avant elle
        ou après elle, jamais au milieu.
        """
        if reseau is not None and command in self.COMMANDES_CONSOLE:
            return {"accepted": False,
                    "reason": tr("moteur.reseau.commande_non_permise",
                                 commande=json.dumps(command, ensure_ascii=False),
                                 liste=", ".join(COMMANDES_RESEAU))}
        if reseau is not None and self.ecoute == "sur_demande":
            with self._connexion_verrou:
                return self._submit(command, reseau, **params)
        return self._submit(command, reseau, **params)

    def _submit(self, command, reseau=None, **params):
        """Le corps de `submit` (cf. sa docstring). Une commande de l'application en écoute sur
        demande arrive ici SOUS `_connexion_verrou` : rien ici ne doit le reprendre."""
        if command not in self.COMMANDS:
            return {"accepted": False,
                    "reason": tr("moteur.refus.commande_inconnue", commande=command,
                                 liste=", ".join(self.COMMANDS))}
        connexion = self.connexion             # une seule lecture : un autre fil peut la finir
        if (connexion is not None and reseau is None
                and command not in self.PERMISES_PENDANT_CONNEXION):
            return {"accepted": False,
                    "reason": tr("moteur.connexion.console_verrouillee",
                                 nom=self._nom_de(connexion))}
        if connexion is None and reseau is not None and self.ecoute == "sur_demande":
            # Sur demande, le moteur n'entend AUCUNE application avant « Connecter ». L'écoute
            # fermée ne lit déjà rien ; ce refus couvre la commande lue juste avant la fin d'une
            # connexion, et jugée juste après (sous `_connexion_verrou`, elle voit la fin).
            return {"accepted": False, "reason": tr("moteur.connexion.pas_connectee")}
        if command == "chercher_applications":
            return self._chercher_applications(bool(params.get("on", True)))
        if command == "connecter":
            return self._connecter(params.get("uid"))
        if command == "deconnecter":
            return self._deconnecter("deconnectee")
        if command == "lancer_decodage":
            return self._lancer_decodage(params.get("id"), params.get("model"))
        if command == "identifier":
            return self._identifier(params.get("uid"))

        if command == "stop":
            self._mettre_en_file("stop", {})
            return {"accepted": True, "command": "stop"}

        if command == "start_mode":
            ids = params.get("ids") or ([params["id"]] if params.get("id") else [])
            if not ids:
                return {"accepted": False, "reason": tr("moteur.refus.aucun_mode_demande")}
            specs, reason = self._resolve(ids, doit_tourner=None)
            if specs is None:
                return {"accepted": False, "reason": reason}
            # Une seule lecture de `self.active` : la boucle peut arrêter un mode entre deux lignes.
            # Les refus se jugent sur l'état APPLIQUÉ : un mode qui n'est pas encore actif sera
            # CONSTRUIT par la boucle, c'est lui que le vol de marqueurs concerne.
            actifs = dict(self.active)
            a_demarrer = [s for s in specs if s.id not in actifs]
            wanted, values, textes = params.get("params") or {}, {}, []
            # ⚠️ AVANT `contract.validate`, délibérément. Le refus du vol de marqueurs est une
            # propriété de l'ÉTAT du moteur (« sa calibration tourne »), pas des réglages soumis :
            # le faire passer après la validation ferait dépendre le message de l'existence d'un
            # modèle entraîné dans `data/` — un dépôt fraîchement cloné s'entendrait dire « aucun
            # choix disponible » là où la vraie raison est qu'une calibration est en cours.
            en_calibration = self.calibration   # copie unique, cf. `start_calibration` plus bas
            en_mesure = self.mesure             # idem : la boucle peut la remettre à None
            for spec in a_demarrer:
                refus = (self._refus_mode_pendant_calibration(spec, en_calibration)
                         or self._refus_mode_pendant_mesure(spec, en_mesure))
                if refus:
                    return {"accepted": False, "reason": refus}
            # Le test d'un mode fige ses réglages, que le mode tourne ou non : un `start_mode`
            # qui en porte serait un `set_params` par la porte de côté (le test du MI n'empêche
            # pas de démarrer le MI, il empêche d'en changer les réglages).
            for spec in specs:
                if spec.id in actifs or wanted.get(spec.id):
                    refus = self._refus_reglage_pendant_test(spec, en_mesure)
                    if refus:
                        return {"accepted": False, "reason": refus}
            # On VALIDE tout avant de poser quoi que ce soit : un lot refusé ne change rien. Chaque
            # mode part de son MAGASIN — les réglages posés avant le démarrage, sinon on jetterait
            # en silence le travail de quelqu'un qui vient de caler ses fréquences sur son écran —
            # complété par ce que la commande porte.
            tourneront = set(self._tourneront([s.id for s in specs]))
            suggestions = {}
            for spec in specs:
                demande, retire, suggestion = self._retirer_modele(
                    connexion, spec, wanted.get(spec.id, {}), reseau)
                v, t, reason = self._valider_reglages(
                    spec, actifs.get(spec.id) if spec.id in tourneront else None, demande)
                if v is None:
                    return {"accepted": False,
                            "reason": self._refus_en_connexion(connexion, reason)}
                values[spec.id] = v
                textes += t
                if retire:
                    textes.append(tr("moteur.connexion.modele_suggere"))
                if suggestion is not None:
                    suggestions[spec.id] = suggestion
            # Le magasin d'abord, la file ensuite : la boucle lit le magasin en appliquant. Ce
            # qu'il portait avant part avec la commande : si le runtime refuse de se construire,
            # `_start` le remet.
            avant = {spec.id: self._reglages_de(spec) for spec in specs}
            for spec in specs:
                self.reglages[spec.id] = dict(values[spec.id])
            # Toujours en file, même pour un mode qui tourne : `_start` lui applique alors ses
            # réglages sans le recréer. Ne rien mettre en file parce qu'il tourne « maintenant »
            # perdait la commande quand un `stop_mode` attendait encore son tour.
            # SAUF pendant une connexion : un mode À MODÈLE que l'application démarre ATTEND que
            # la console choisisse son modèle (« Lancer le décodage ») ; il n'est pas mis en file.
            self._noter_suggestions(connexion, suggestions)
            attente = self._attendre_un_modele(connexion, specs, reseau)
            a_lancer = [s.id for s in specs if s.id not in attente]
            deja = (self._inscrire_marche("start_mode", a_lancer, reseau,
                                          avant={i: avant[i] for i in a_lancer})
                    if a_lancer else [])
            self._noter_l_application(connexion, reseau, [s.id for s in specs], a_lancer, deja)
            if attente:
                textes.append(tr("moteur.connexion.attend_un_modele"))
            ack = {"accepted": True, "command": "start_mode", "ids": [s.id for s in specs],
                   "warning": self._avertissement(textes)}
            if attente:
                ack["differe"] = True
            if len(specs) == 1:
                # Les réglages avec lesquels CE mode tournera (ceux d'un lot sont dans le magasin).
                ack["params"] = values[specs[0].id]
                if attente:
                    # Il attend le modèle que la console choisira : celui du magasin n'est PAS
                    # celui avec lequel il démarrera. La réponse n'en nomme aucun.
                    ack["params"] = dict(ack["params"], model=None)
            if deja:
                # Informatif : ces modes tournaient déjà (ou un démarrage attendait déjà son tour).
                ack["deja"] = deja
            return ack

        if command == "set_params":
            # Cette commande ne passe PAS par `_one` (qui exige un mode démarré) : on règle un mode
            # AVANT de le lancer. Un réglage soumis à un mode arrêté est VALIDÉ comme les autres —
            # c'est là qu'on apprend que 17 Hz ne divise pas 60 — puis RETENU pour le prochain
            # démarrage. Sinon il faudrait démarrer sur des réglages qu'on sait faux, subir 23 s de
            # repos, puis les corriger et refaire le repos.
            spec = registry.get(params.get("id"))
            if spec is None:
                connus = ", ".join(s.id for s in registry.runnable())
                return {"accepted": False,
                        "reason": tr("moteur.refus.mode_inconnu", id=params.get("id"),
                                     liste=connus)}
            if spec.runtime_cls is None:
                return {"accepted": False,
                        "reason": tr("moteur.refus.pas_dans_le_moteur", mode=spec.label,
                                     raison=spec.unavailable)}
            refus = self._refus_reglage_pendant_test(spec, self.mesure)
            if refus:
                return {"accepted": False, "reason": refus}
            # Le mode tournera-t-il une fois la file vidée ? (`_tourneront` : un `stop_mode` en
            # attente compte.) Une seule lecture de `self.active` ensuite : `submit` tourne sur le
            # fil de l'APPELANT, la boucle peut arrêter ce mode entre deux lignes, et `submit`
            # promet de ne jamais lever.
            tourne = bool(self._tourneront([spec.id]))
            runtime = self.active.get(spec.id) if tourne else None
            # On fusionne sur le MAGASIN, le dernier réglage accepté : un appelant peut n'envoyer
            # que ce qu'il change, sans avoir à relire et renvoyer tout le reste — et deux
            # `set_params` envoyés coup sur coup ne s'annulent pas.
            demande, retire, suggestion = self._retirer_modele(
                connexion, spec, params.get("params"), reseau)
            values, textes, reason = self._valider_reglages(spec, runtime, demande)
            if values is None:
                return {"accepted": False,
                        "reason": self._refus_en_connexion(connexion, reason)}
            if retire:
                textes = list(textes) + [tr("moteur.connexion.modele_suggere")]
            if suggestion is not None:
                self._noter_suggestions(connexion, {spec.id: suggestion})
            self._noter_l_application(connexion, reseau, [spec.id], [])
            avertissement = self._avertissement(textes)
            with self._en_attente_verrou:
                # Sous le même verrou que `start_mode`/`stop_mode` : leur ordre dans la file est
                # celui où ils ont été jugés.
                self.reglages[spec.id] = dict(values)
                tourne = bool(self._tourneront([spec.id]))
                if tourne:
                    self._mettre_en_file("set_params", {"id": spec.id, "params": values}, reseau)
            rendus = values
            if (connexion is not None and reseau is not None and _a_un_modele(spec)
                    and not tourne):
                # Pendant une connexion, un mode à modèle ARRÊTÉ démarrera avec le modèle que la
                # console choisira : la réponse n'en nomme aucun. Un mode qui TOURNE garde celui
                # qu'il décode, choisi dans la console : la réponse le nomme.
                rendus = dict(values, model=None)
            # Mode arrêté : rien à mettre en file, il n'y a pas de runtime à régler, et le prochain
            # démarrage lira le magasin. `differe` dit à l'appelant que c'est ACCEPTÉ mais pas
            # encore en vigueur — un « appliqué » nu ferait croire que le mode décode déjà sous ces
            # réglages.
            return {"accepted": True, "command": command, "id": spec.id,
                    "params": rendus, "differe": not tourne, "warning": avertissement}

        if command == "propose_params":
            # Une commande en LECTURE : elle ne met rien en file et ne touche pas la session
            # BrainFlow, donc elle peut répondre tout de suite. Elle reste ici pour que la console
            # et un client LSL empruntent le même chemin — un seul endroit à tester.
            spec = registry.get(params.get("id"))
            if spec is None:
                connus = ", ".join(s.id for s in registry.runnable())
                return {"accepted": False,
                        "reason": tr("moteur.refus.mode_inconnu", id=params.get("id"),
                                     liste=connus)}
            cle = params.get("key")
            source = next((p for p in spec.params if p.key == cle and p.proposes), None)
            if source is None:
                # Trois refus distincts : un mode qui ne propose rien, un réglage à proposer non
                # désigné, un réglage désigné qui ne propose rien.
                proposeurs = [p.key for p in spec.params if p.proposes]
                if not proposeurs:
                    raison = tr("moteur.refus.mode_ne_propose_rien", mode=spec.label)
                elif cle is None:
                    raison = tr("moteur.refus.propose_quelle_cle", mode=spec.label,
                                liste=", ".join(proposeurs))
                else:
                    raison = tr("moteur.refus.ne_propose_rien", reglage=cle, mode=spec.label,
                                liste=", ".join(proposeurs))
                return {"accepted": False, "reason": raison}
            # ⚠️ Le MAGASIN, pas les défauts du contrat, ni les réglages du runtime. Sinon les deux
            # moitiés du même geste se contredisent : on applique son pic alpha (accepté, retenu,
            # ou encore dans la file d'un mode qui tourne), puis « Proposer » recalcule sur 9,6 Hz
            # — le pic de la population, pas le sien — et rend un jeu de fréquences accordé à la
            # mauvaise tête.
            courant = self._reglages_de(spec)
            # Ce que l'appelant est en train d'éditer prime sur ce qui est stocké : sans ça,
            # déclarer un écran 144 Hz est refusé (les anciennes fréquences ne le divisent pas)
            # ET la proposition continue de calculer sur 60 — l'étudiant n'a aucune porte de sortie.
            courant.update(params.get("params") or {})
            cible = source.proposes

            # `courant[cible]` peut être une CHAÎNE si l'étudiant a mal tapé la liste : `len()`
            # rendrait alors le nombre de CARACTÈRES, pas de fréquences. On ne compte que sur une
            # vraie liste, sinon on retombe sur le nombre de cibles par défaut du contrat.
            valeur_cible = courant.get(cible)
            n = (len(valeur_cible) if isinstance(valeur_cible, (list, tuple))
                 else len(spec.defaults().get(cible) or ()))
            # Les ENTRÉES du calcul — rafraîchissement, pic alpha et BANDE réglée —
            # telles qu'elles sont à l'écran, JUGÉES par le contrat, un réglage à la fois
            # (`contract.valider_un`) : le refus est celui qu'« Appliquer » rendrait, mot pour mot.
            # Les fréquences, elles, ne sont PAS jugées : c'est ce qu'on remplace.
            # ⚠️ Pas d'écrêtage : une bande saisie hors bornes ramenée en silence dans les bornes
            # ferait répondre « Proposer » sur une bande que l'écran ne montre pas, puis refuser
            # « Appliquer ». Et un rafraîchissement non borné (« inf », 10⁹ Hz) ferait tourner
            # sans fin ou des minutes la boucle des diviseurs de `available_frequencies`, sur le
            # fil de l'interface. `submit` promet de ne jamais lever ; il doit aussi rendre la main.
            par_cle = {p.key: p for p in spec.params}
            entrees = {}
            for cle in ("refresh_hz", "alpha_hz", "band_low", "band_high"):
                if cle not in par_cle:
                    continue
                valeur, raison = contract.valider_un(
                    par_cle[cle], courant.get(cle, par_cle[cle].default_now()))
                if raison:
                    return {"accepted": False, "reason": raison}
                entrees[cle] = valeur
            # Un mode sans bande réglable garde la bande de l'acquisition (le défaut de
            # `propose_frequencies`). Avec une, « Proposer » ne propose jamais ce que son filtre
            # supprime — et que « Appliquer » refuserait au clic suivant.
            bande = ({"bande": (entrees["band_low"], entrees["band_high"])}
                     if "band_low" in entrees and "band_high" in entrees else {})
            # Des cibles PHYSIQUES n'ont pas d'écran : `None` fait proposer sur une grille fine,
            # là où un écran impose les diviseurs de son rafraîchissement.
            physiques = courant.get("targets_on") == contract.CIBLES_PHYSIQUES
            valeurs, note = propose_frequencies(None if physiques
                                                else entrees.get("refresh_hz", 60.0), n,
                                                entrees.get("alpha_hz", ALPHA_DEFAUT_HZ),
                                                **bande)
            if not valeurs:
                return {"accepted": False, "reason": note}
            return {"accepted": True, "command": command, "id": spec.id,
                    "key": cible, "value": valeurs, "warning": note}

        if command == "start_calibration":
            spec, reason = self._calibration_de(params.get("id"))
            if spec is None:
                return {"accepted": False, "reason": reason}
            # ⚠️ LE VOL DE MARQUEURS, premier sens. `dict(self.active)` : une copie atomique, prise
            # une seule fois — `submit` tourne sur le fil de l'appelant pendant que la boucle
            # démarre et arrête des modes sur le sien. C'est le SEUL refus que
            # `valider_calibration` ne fait pas : la console le lève elle-même, en arrêtant le mode.
            refus = self._refus_calibration_pendant_mode(spec, dict(self.active))
            if refus:
                return {"accepted": False, "reason": refus}
            # Tout le reste — une autre séance minutée en cours, les réglages — par LA méthode que
            # la console appelle au clic, avant le contrôle de liaison. Une seule écriture : un refus
            # que « Commencer » ne verrait pas au clic serait rendu ici, APRÈS que la console a
            # arrêté le décodage pour rien.
            values, reason = self.valider_calibration(spec.id, params.get("params"))
            if values is None:
                return {"accepted": False, "reason": reason}
            self._mettre_en_file("start_calibration", {"id": spec.id, "params": values})
            return {"accepted": True, "command": command, "id": spec.id, "params": values}

        if command == "cancel_calibration":
            en_cours = self.calibration   # même motif que start_calibration juste au-dessus
            if en_cours is None or en_cours.terminee:
                return {"accepted": False, "reason": tr("moteur.refus.aucune_calibration")}
            self._mettre_en_file("cancel_calibration", {})
            return {"accepted": True, "command": command, "id": en_cours.spec.id}

        if command == "start_mesure":
            # Une MESURE : un protocole minuté qui rend un VERDICT à l'écran et n'écrit rien
            # (cf. `core/modes/mesure.py`). D'où l'absence totale de `save_mesure`/`discard_mesure`
            # en face de `save_calibration` : il n'y a aucun fichier à retenir ou à jeter.
            spec = registry.get_mesure(params.get("id"))
            if spec is None:
                connus = (", ".join(s.id for s in registry.MESURES)
                          or tr("moteur.refus.aucune_mesure_connue"))
                return {"accepted": False,
                        "reason": tr("moteur.refus.mesure_inconnue", id=params.get("id"),
                                     liste=connus)}
            if spec.runtime_cls is None:
                return {"accepted": False,
                        "reason": tr("moteur.refus.mesure_pas_livree", mesure=spec.label)}
            # ⚠️ LES DEUX SENS DU REFUS, sur des copies prises UNE fois chacune (la boucle peut
            # les remettre à `None` entre deux lectures, et `submit` promet en toutes lettres de
            # ne jamais lever). Le premier refuse une mesure pendant une calibration ; le second,
            # une mesure pendant une autre mesure — un double-clic sur « Commencer » y suffit.
            refus = (self._refus_pour_calibration_en_cours(self.calibration)
                     or self._refus_pour_mesure_en_cours(self.mesure)
                     or self._refus_mesure_pendant_mode(spec, dict(self.active))
                     or self._refus_test_hors_condition(spec))
            if refus:
                return {"accepted": False, "reason": refus}
            values, reason = contract.validate(spec, params.get("params") or {})
            if values is None:
                return {"accepted": False, "reason": reason}
            self._mettre_en_file("start_mesure", {"id": spec.id, "params": values})
            return {"accepted": True, "command": command, "id": spec.id, "params": values}

        if command == "cancel_mesure":
            en_cours = self.mesure   # même motif de copie que `cancel_calibration` plus haut
            if en_cours is None or en_cours.terminee:
                return {"accepted": False, "reason": tr("moteur.refus.aucune_mesure")}
            self._mettre_en_file("cancel_mesure", {})
            return {"accepted": True, "command": command, "id": en_cours.spec.id}

        if command == "start_enregistrement":
            # Enregistrer les VERDICTS d'une séance, dans `seances/` — jamais dans `data/`. Les
            # mêmes conventions d'acceptation que `save_calibration` juste en dessous : un accusé
            # avec un motif LISIBLE, et rien d'appliqué avant que la boucle ne le fasse.
            spec, refus = self._mode_du_flux(params.get("stream"))
            if spec is None:
                return {"accepted": False, "reason": refus}
            # Une seule lecture, comme partout ici : la boucle peut le remettre à None entre deux.
            en_cours = self.enregistrement
            if en_cours is not None and en_cours.actif:
                # Deux fichiers écrits en parallèle sur la même séance ne se distingueraient plus.
                return {"accepted": False,
                        "reason": tr("moteur.refus.enregistrement_deja", chemin=en_cours.chemin)}
            # ⚠️ **Aucun `chemin` dans cet accusé, et c'est délibéré.** Le nom du fichier est
            # décidé par la BOUCLE, et l'écran le lit dans `snapshot()["enregistrement"]`. Le
            # calculer ici pour le rendre tout de suite serait plus commode et FAUX : deux clics
            # dans la même fenêtre de sondage (100 ms) voient tous les deux `self.enregistrement`
            # à None, donc les deux seraient acceptés — et le second afficherait le chemin d'un
            # fichier que la boucle refusera de créer. Ne rien promettre qu'on ne puisse tenir.
            self._mettre_en_file("start_enregistrement", {"id": spec.id})
            return {"accepted": True, "command": command, "id": spec.id,
                    "stream": stream_name(spec.stream)}

        if command == "stop_enregistrement":
            en_cours = self.enregistrement
            if en_cours is None or not en_cours.actif:
                return {"accepted": False, "reason": tr("moteur.refus.aucun_enregistrement")}
            self._mettre_en_file("stop_enregistrement", {})
            # Le chemin et le compte sont rendus TOUT DE SUITE, alors que la fermeture, elle,
            # attend la boucle : c'est ce que l'écran a besoin d'afficher, et `submit` ne promet
            # de toute façon jamais que la commande soit déjà appliquée (cf. sa docstring).
            return {"accepted": True, "command": command, "chemin": en_cours.chemin,
                    "lignes": en_cours.lignes}

        if command in ("save_calibration", "discard_calibration"):
            # Une seule lecture de `self.candidat`, comme partout ici : la boucle peut le remettre
            # à `None` (arrêt du moteur, nouvelle calibration) entre deux lectures, et `submit`
            # promet en toutes lettres de ne jamais lever.
            candidat = self.candidat
            if not candidat:
                # Un candidat n'existe qu'entre la fin d'un entraînement et le clic qui le
                # retient ou le jette.
                return {"accepted": False,
                        "reason": (tr("moteur.refus.rien_a_enregistrer")
                                   if command == "save_calibration"
                                   else tr("moteur.refus.rien_a_jeter"))}
            self._mettre_en_file(command, {})
            return {"accepted": True, "command": command,
                    "modele": candidat.get("modele")}

        if command == "stop_mode" and params.get("id"):
            # Arrêter un mode arrêté est déjà fait : on le dit (« deja »). Une application peut
            # ainsi rejouer sa commande sans connaître l'état du moteur. Mais l'arrêt part
            # TOUJOURS en file : un `start_mode` accepté peut y attendre son tour, et le mode
            # démarrerait après cet « arrêté » (`_stop_mode` tolère un mode déjà arrêté).
            specs, reason = self._resolve([params["id"]], doit_tourner=None)
            if specs is None:
                return {"accepted": False, "reason": reason}
            tournait = self._inscrire_marche("stop_mode", [specs[0].id], reseau)
            if connexion is not None and reseau is not None:
                # Un `stop_mode` de l'application annule aussi son démarrage EN ATTENTE.
                connexion.en_attente.pop(specs[0].id, None)
            ack = {"accepted": True, "command": "stop_mode", "id": specs[0].id}
            if not tournait:
                ack["deja"] = True
            return ack

        # `stop_mode` sans « id » arrive ici, et `_one` le refuse (« aucun mode désigné »).
        spec, reason = self._one(params.get("id"))
        if spec is None:
            return {"accepted": False, "reason": reason}

        if command == "set_published":
            self._mettre_en_file("set_published",
                                 {"id": spec.id, "on": bool(params.get("on", True))})
        elif command == "recalibrate":
            if spec.rest is None:
                return {"accepted": False,
                        "reason": tr("moteur.refus.sans_repos", mode=spec.label)}
            self._mettre_en_file("recalibrate", {"id": spec.id})
        return {"accepted": True, "command": command, "id": spec.id}

    # --- la connexion d'une application (écoute sur demande, la console) ------------------------

    def _nom_de(self, connexion):
        """Le nom d'une application connectée, ou un texte qui dit qu'elle n'en a pas donné."""
        return connexion.nom or tr("moteur.connexion.sans_nom")

    def _chercher_applications(self, on):
        """Lance ou arrête la recherche des applications du réseau — LSL de toutes les machines,
        et appareils réseau (UDP) — (la page « Connecter une application » ouverte, puis
        quittée). Aucun flux n'est ouvert."""
        if self.ecoute != "sur_demande":
            return {"accepted": False, "reason": tr("moteur.connexion.ecoute_permanente")}
        self.pilotage.chercher(on)
        return {"accepted": True, "command": "chercher_applications", "on": bool(on)}

    def _connecter(self, uid):
        """Connecte l'application `uid`, que la recherche voit. Refusé pendant un protocole
        minuté (un seul casque), quand un modèle entraîné attend d'être tranché, et quand une
        application est déjà connectée."""
        if self.ecoute != "sur_demande":
            return {"accepted": False, "reason": tr("moteur.connexion.ecoute_permanente")}
        with self._connexion_verrou:
            if self.connexion is not None:
                return {"accepted": False,
                        "reason": tr("moteur.connexion.deja", nom=self._nom_de(self.connexion))}
            calibration, mesure = self.calibration, self.mesure
            if calibration is not None and not calibration.terminee:
                return {"accepted": False, "reason": tr("moteur.connexion.entrainement")}
            if mesure is not None and not mesure.terminee:
                return {"accepted": False, "reason": tr("moteur.connexion.test")}
            if self.candidat is not None:
                return {"accepted": False, "reason": tr("moteur.connexion.candidat")}
            annonce = next((a for a in self.pilotage.annonces() if a["uid"] == uid), None)
            if annonce is None:
                return {"accepted": False, "reason": tr("moteur.connexion.introuvable")}
            # La connexion EXISTE avant que l'écoute ne s'ouvre : la première commande de
            # l'application est jugée en connexion (son `model` n'est qu'une suggestion).
            self.connexion = _Connexion(uid=uid, nom=annonce["nom"], depuis=time.time(),
                                        t=time.monotonic(),
                                        illisible=bool(annonce.get("illisible")),
                                        origine=annonce.get("origine") or "lsl",
                                        machine=annonce.get("machine") or "",
                                        ident=annonce.get("id"),
                                        adresse=annonce.get("adresse"))
            if self.pilotage.connecter(uid) is None:
                self.connexion = None
                return {"accepted": False, "reason": tr("moteur.connexion.introuvable")}
            # Effacée seulement une fois connectée : un refus laisse la fin précédente à l'écran.
            self.fin_connexion = None
        print(f"[server] application connectée : « {annonce['nom'] or '?'} »")
        return {"accepted": True, "command": "connecter", "nom": annonce["nom"]}

    def _identifier(self, uid):
        """« Identifier » : demande à l'appareil réseau `uid`, que la recherche voit, de se
        signaler (une LED qui clignote). Une application LSL n'a pas de quoi le faire."""
        if self.ecoute != "sur_demande":
            return {"accepted": False, "reason": tr("moteur.connexion.ecoute_permanente")}
        if not self.pilotage.identifier(uid):
            return {"accepted": False, "reason": tr("moteur.connexion.identifier_impossible")}
        return {"accepted": True, "command": "identifier", "uid": uid}

    def _deconnecter(self, raison, uid=None, cause=None, hote=None):
        """Termine la connexion : les modes que l'application a démarrés s'arrêtent, ses
        démarrages en attente sont oubliés, son flux est refermé. `raison` : « deconnectee » (la
        console) ou « partie » (l'application a disparu). Un mode qui tournait avant elle
        continue.

        `cause`, `hote` : ce qu'un appareil réseau dit de son départ (`application_partie`). La
        fin de connexion porte alors `cause` comme raison (« occupee », « ne_repond_pas »,
        « silence », « bye »), et `hote` la console qui le tient déjà (« occupee »).

        `uid` (le départ) : ne termine la connexion que si c'est encore CETTE application,
        vérifié sous le verrou — une « Déconnecter » suivie d'une nouvelle connexion peut avoir
        pris les devants.

        « Déconnecter » est DIT à l'application, sur le flux de réponses, avec les modes arrêtés
        (`pilotage.deconnecter`) : LSL ne le lui dirait qu'à son prochain envoi, et une
        application qui attend ses décisions n'envoie rien. Une application partie ne lit plus
        rien : pas de message."""
        with self._connexion_verrou:
            connexion = self.connexion
            if connexion is None or (uid is not None and connexion.uid != uid):
                return {"accepted": False, "reason": tr("moteur.connexion.aucune")}
            self.connexion = None
            arretes = self._tourneront([s.id for s in registry.MODES
                                        if s.id in connexion.demarres])
            self.pilotage.deconnecter(arretes, adieu=(raison == "deconnectee"))
            for mode_id in arretes:
                self._inscrire_marche("stop_mode", [mode_id], None)
            # Un tuple : `snapshot()` n'en fait qu'une copie superficielle.
            self.fin_connexion = {"nom": connexion.nom, "illisible": connexion.illisible,
                                  "raison": cause or raison, "hote": hote,
                                  "origine": connexion.origine, "arretes": tuple(arretes),
                                  "t": time.monotonic()}
        print(f"[server] application « {connexion.nom or '?'} » "
              f"{'partie' if raison == 'partie' else 'déconnectée'}"
              f"{f' ({cause})' if cause else ''} — arrêtés : {', '.join(arretes) or 'aucun'}")
        return {"accepted": True, "command": "deconnecter", "arretes": arretes}

    def application_partie(self, uid, raison=None, hote=None):
        """Le rappel du fil d'écoute : l'application connectée a disparu du réseau. Appelé depuis
        CE fil, qui ne tient alors aucun verrou du pilotage : il attend au plus la commande en
        cours de jugement. Sans effet si `uid` n'est plus la connexion en cours.

        `raison` : None pour une application LSL ; pour un appareil réseau, « occupee » (il est
        déjà connecté à la console `hote`), « ne_repond_pas » (pas de « connected » à temps),
        « silence » (plus rien de lui depuis 5 s) ou « bye » (il s'arrête). La fin de connexion
        la porte, et la console la dit."""
        self._deconnecter("partie", uid=uid, cause=raison, hote=hote)

    def _lancer_decodage(self, mode_id, model):
        """« Lancer le décodage » de la page de contrôle : démarre un mode À MODÈLE que
        l'application a demandé, avec le modèle choisi DANS LA CONSOLE — ou relance avec un
        autre modèle un mode à modèle qui tourne. Seulement pendant une connexion.

        Tout se juge sous `_connexion_verrou` : la fin de la connexion, ou un `stop_mode` de
        l'application, passe avant ou après, jamais entre le contrôle et le démarrage."""
        with self._connexion_verrou:
            connexion = self.connexion
            if connexion is None:
                return {"accepted": False, "reason": tr("moteur.connexion.aucune")}
            spec = registry.get(mode_id)
            if spec is None:
                connus = ", ".join(s.id for s in registry.runnable())
                return {"accepted": False,
                        "reason": tr("moteur.refus.mode_inconnu",
                                     id=contract.recopie(mode_id, brut=True), liste=connus)}
            if not _a_un_modele(spec):
                return {"accepted": False,
                        "reason": tr("moteur.connexion.sans_modele", mode=spec.label)}
            tourne = bool(self._tourneront([spec.id]))
            if not tourne and spec.id not in connexion.en_attente:
                return {"accepted": False,
                        "reason": tr("moteur.connexion.pas_demande", mode=spec.label)}
            runtime = self.active.get(spec.id) if tourne else None
            values, textes, reason = self._valider_reglages(spec, runtime, {"model": model})
            if values is None:
                return {"accepted": False,
                        "reason": self._refus_en_connexion(connexion, reason)}
            avant = {spec.id: self._reglages_de(spec)}
            with self._en_attente_verrou:
                self.reglages[spec.id] = dict(values)
                if tourne:
                    self._mettre_en_file("set_params", {"id": spec.id, "params": values})
            if not tourne:
                # Le jeton du `start_mode` de l'APPLICATION : un échec au démarrage lui arrive
                # sur SA commande (`event: failed`).
                jeton = connexion.en_attente.pop(spec.id, None)
                self._inscrire_marche("start_mode", [spec.id], jeton, avant=avant)
                connexion.demarres.add(spec.id)
                connexion.demandes.add(spec.id)
            return {"accepted": True, "command": "lancer_decodage", "id": spec.id,
                    "params": values, "relance": tourne,
                    "warning": self._avertissement(textes)}

    @staticmethod
    def _refus_en_connexion(connexion, raison):
        """Pendant une connexion, la console ne fait qu'afficher : « clique Entraîner » y est
        impossible. Le refus « aucun modèle entraîné » dit alors de déconnecter d'abord."""
        if connexion is not None and getattr(raison, "cle", None) == contract.SANS_MODELE.cle:
            return tr("moteur.connexion.sans_modele_entraine")
        return raison

    @staticmethod
    def _retirer_modele(connexion, spec, demande, reseau):
        """Pendant une connexion, le `model` qu'envoie l'APPLICATION n'est qu'une suggestion : le
        modèle se choisit dans la console. Rend (réglages sans `model`, `model` retiré ?,
        suggestion). La suggestion est un NOM de fichier court (`_SUGGESTION_MAX`), ou None si
        l'application n'a pas envoyé de texte : le `model` est retiré quand même."""
        if (connexion is None or reseau is None or not isinstance(demande, dict)
                or "model" not in demande or not _a_un_modele(spec)):
            return demande, False, None
        valeur = demande["model"]
        suggestion = ((os.path.basename(valeur)[:_SUGGESTION_MAX] or None)
                      if isinstance(valeur, str) else None)
        return {k: v for k, v in demande.items() if k != "model"}, True, suggestion

    @staticmethod
    def _noter_suggestions(connexion, suggestions):
        """Garde les `model` suggérés par l'application (mode -> nom de fichier), À CÔTÉ du
        magasin, jamais dedans : la page de contrôle les présélectionne, rien ne les applique."""
        if connexion is not None and suggestions:
            connexion.suggestions.update(suggestions)

    def _attendre_un_modele(self, connexion, specs, reseau):
        """Pendant une connexion, le `start_mode` de l'APPLICATION sur un mode À MODÈLE qui ne
        tourne pas : le mode attend « Lancer le décodage ». Rend les identifiants mis en
        attente."""
        if connexion is None or reseau is None:
            return []
        tourneront = set(self._tourneront([s.id for s in specs]))
        attente = [s.id for s in specs if _a_un_modele(s) and s.id not in tourneront]
        for mode_id in attente:
            connexion.en_attente[mode_id] = reseau
        return attente

    @staticmethod
    def _noter_l_application(connexion, reseau, modes_regles, modes_demarres, deja=()):
        """Pendant une connexion, ce que l'application a réglé (la page de contrôle le montre)
        et ce qu'elle a démarré (la fin de la connexion l'arrête). Un mode qui tournait déjà
        n'est pas « démarré par elle »."""
        if connexion is None or reseau is None:
            return
        connexion.regles.update(modes_regles)
        connexion.demarres.update(i for i in modes_demarres if i not in (deja or ()))
        connexion.demandes.update(modes_demarres)

    def _etat_connexion(self):
        """La connexion, pour la console (`snapshot()["connexion"]`), ou None."""
        connexion = self.connexion
        if connexion is None:
            return None
        en_attente = list(connexion.en_attente)
        return {"uid": connexion.uid, "nom": connexion.nom, "illisible": connexion.illisible,
                "depuis": connexion.depuis, "t": connexion.t,
                "origine": connexion.origine, "machine": connexion.machine,
                "id": connexion.ident, "adresse": connexion.adresse,
                "branchee": self.pilotage.branchee(),
                "demarres": [s.id for s in registry.MODES if s.id in connexion.demarres],
                # Les modes que l'application a demandés : ceux dont un appareil réseau reçoit
                # les décisions (la page le dit à la place du voyant LSL).
                "demandes": [s.id for s in registry.MODES if s.id in connexion.demandes],
                "regles": [s.id for s in registry.MODES if s.id in connexion.regles],
                "en_attente": {m: {"suggestion": connexion.suggestions.get(m)}
                               for m in en_attente},
                "suggestions": dict(connexion.suggestions)}

    # --- ce que le moteur pousse à l'appareil réseau connecté (UDP) ----------------------------
    # La boucle dépose ; le fil du pilotage envoie (`Pilotage.pousser`). La boucle ne touche
    # jamais la socket : un envoi ne la ralentit pas, et un seul fil écrit sur la socket.

    def _ouvrir_udp(self):
        """Sur demande (la console) : ouvre l'écoute des appareils réseau, au démarrage de `run`.
        Un port pris ne bloque rien : les applications LSL restent connectables, et `snapshot()`
        dit pourquoi l'écoute UDP manque (`udp.raison`). Le moteur seul n'ouvre rien."""
        if self.ecoute != "sur_demande":
            return
        raison = self.pilotage.ouvrir_udp(port=self.port_udp)
        if raison is not None:
            print(f"[server] ⚠️ {raison}")

    def _appareil_connecte(self):
        """La connexion en cours si c'est un appareil réseau, sinon None. Une seule lecture : un
        autre fil peut la finir."""
        connexion = self.connexion
        if connexion is None or connexion.origine != "udp":
            return None
        return connexion

    def _dire_une_panne(self, quoi, e):
        """Une poussée vers l'appareil réseau qui lève : dite UNE fois au terminal, jamais
        propagée. C'est une fonction secondaire : le décodage et la publication LSL continuent."""
        if quoi not in self._pannes_dites:
            self._pannes_dites.add(quoi)
            print(f"[server] ⚠️ {quoi} impossible à pousser à l'appareil réseau : {e!r}")

    def _observer_la_sortie(self, mode_id, runtime):
        """Juste avant le pas d'un mode que l'appareil réseau connecté a demandé : chaque
        échantillon que ce mode publiera sur son flux décodé lui sera aussi poussé
        (`_SortieObservee`). Un flux recréé (de nouvelles fréquences) est observé à son tour.
        Ne lève jamais (appelé par la boucle du moteur)."""
        try:
            connexion = self._appareil_connecte()
            if connexion is None or mode_id not in connexion.demandes:
                return
            publieur = getattr(runtime, "_out", None)
            outlet = getattr(publieur, "outlet", None)
            if outlet is None or isinstance(outlet, _SortieObservee):
                return
            publieur.outlet = _SortieObservee(outlet, mode_id, runtime.channels(), self)
        except Exception as e:  # noqa: BLE001 - une poussée ratée ne doit pas arrêter le moteur
            self._dire_une_panne("decision", e)

    def _decision_publiee(self, mode_id, voies, rangee):
        """Un échantillon publié sur `decoded_<mode>` : poussé en « decision » à l'appareil
        réseau connecté, s'il a demandé ce mode. Les voies par NOM, celles du flux décodé, `-1`
        compris : l'appareil choisit ce qu'il en fait."""
        connexion = self._appareil_connecte()
        if connexion is None or mode_id not in connexion.demandes:
            return
        decision = {"mode": mode_id}
        decision.update((nom, _valeur_json(v)) for nom, v in zip(voies, rangee))
        self.pilotage.pousser({"decision": decision})

    def _statut_appareil(self, connexion, active):
        """Le « status » de l'appareil réseau : la phase publique de chacun de SES modes
        (« deferred » : un mode à modèle qui attend « Lancer le décodage »), la moins avancée
        d'entre elles (« idle » s'il n'en a aucun), et la consigne du repos en anglais pendant
        la chauffe et le repos, comme le flux `status`."""
        modes = {}
        for spec in registry.MODES:
            if spec.id in connexion.en_attente:
                modes[spec.id] = "deferred"
            elif spec.id in connexion.demandes and spec.id in active:
                interne = active[spec.id].phase
                modes[spec.id] = self._PHASES_PUBLIQUES.get(interne, interne)
        phase = next((p for p in ("deferred", "warmup", "baseline", "decoding")
                      if p in modes.values()), "idle" if not modes else "decoding")
        statut = {"phase": phase, "modes": modes}
        if self.rest_instruction and phase in ("warmup", "baseline"):
            statut["instruction"] = pour_le_contrat(self.rest_instruction)
        return statut

    def _pousser_statut(self, now):
        """Pousse le « status » à l'appareil réseau connecté quand il change, et au plus tard
        chaque `STATUT_APPAREIL_S`. Tant que l'appareil n'a pas répondu « connected », rien ne
        part : le premier « status » part dès qu'il l'a fait. Ne lève jamais (appelé par la
        boucle du moteur)."""
        try:
            connexion = self._appareil_connecte()
            if connexion is None or not self.pilotage.branchee():
                self._statut_pousse = None
                return
            statut = self._statut_appareil(connexion, dict(self.active))
            if (statut == self._statut_pousse
                    and now - self._statut_pousse_a < STATUT_APPAREIL_S):
                return
            if self.pilotage.pousser({"status": statut}):
                self._statut_pousse, self._statut_pousse_a = statut, now
        except Exception as e:  # noqa: BLE001 - une poussée ratée ne doit pas arrêter le moteur
            self._dire_une_panne("status", e)

    def _reglages_de(self, spec):
        """Les derniers réglages connus de ce mode, ou ses défauts. Toujours une COPIE.

        Rendre le dictionnaire stocké laisserait un appelant le muter par accident — et un
        `merged.update(...)` sur la valeur du magasin écrirait dans le magasin AVANT la
        validation, donc y installerait des réglages refusés.
        """
        return dict(self.reglages.get(spec.id) or spec.defaults())

    def _resolve(self, ids, doit_tourner):
        """(specs dans l'ordre du registre, None) ou (None, raison). Refuse tôt et en clair.

        `doit_tourner=True` exige que chaque mode tourne ; `None` ne regarde pas l'état (c'est
        le cas de `start_mode` et `stop_mode`, qui se rejouent sans risque).
        """
        for mode_id in ids:
            spec = registry.get(mode_id)
            if spec is None:
                connus = ", ".join(s.id for s in registry.runnable())
                return None, tr("moteur.refus.mode_inconnu",
                                id=contract.recopie(mode_id, brut=True), liste=connus)
            if spec.runtime_cls is None:
                # C'est exactement ce que la tuile doit dire à l'étudiant : POURQUOI ça ne
                # démarre pas, jamais un échec silencieux.
                return None, tr("moteur.refus.pas_dans_le_moteur", mode=spec.label,
                                raison=spec.unavailable)
            if doit_tourner and spec.id not in self.active:
                return None, tr("moteur.refus.non_demarre", mode=spec.label)
        return [s for s in registry.MODES if s.id in ids], None

    def _one(self, mode_id):
        specs, reason = self._resolve([mode_id] if mode_id else [], doit_tourner=True)
        if specs is None:
            return None, reason
        if not specs:
            return None, tr("moteur.refus.aucun_mode_designe")
        return specs[0], None

    def _apply(self, command, params, reseau=None):
        if command == "stop":
            self.stop()
        elif command == "start_mode":
            # Sans « params » (le chemin de `submit`), `_start` lit le MAGASIN maintenant.
            try:
                self._start(params["ids"], params.get("params"), time.perf_counter(), reseau,
                            avant=params.get("avant"))
            finally:
                self._attente_appliquee(params)
        elif command == "stop_mode":
            try:
                self._stop_mode(params["id"])
            finally:
                self._attente_appliquee(params)
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
                # ⚠️ `cancel()` ne change PAS la phase d'une calibration déjà « fini », et c'est
                # voulu là-bas. Mais `_terminer` BLOQUE la boucle le temps du `fit` (plusieurs
                # secondes) : c'est l'instant où l'écran est figé et où l'on clique « Abandonner ».
                # La commande est acceptée, le `fit` se termine, le candidat est adopté : sans
                # le jeter AUSSI, « aucun modèle produit » serait faux, un modèle attendant à un
                # clic de `data/` avec « Enregistrer » actif.
                jete = self.candidat is not None
                self.calibration.cancel()
                self._efface_candidat("abandon demandé pendant l'entraînement")
                print(f"[server] calibration abandonnée — aucun modèle produit"
                      + (" (le candidat entraîné pendant l'abandon a été jeté)" if jete else ""))
        elif command == "save_calibration":
            self._save_calibration()
        elif command == "discard_calibration":
            self._discard_calibration()
        elif command == "start_enregistrement":
            self._start_enregistrement(params["id"])
        elif command == "stop_enregistrement":
            if self.enregistrement is not None and self.enregistrement.actif:
                self.enregistrement.fermer()
                print(f"[server] enregistrement arrêté : {self.enregistrement.lignes} verdict(s) "
                      f"dans {self.enregistrement.chemin}")
        elif command == "start_mesure":
            self._start_mesure(params["id"], params["params"])
        elif command == "cancel_mesure":
            if self.mesure is not None:
                # Plus simple que `cancel_calibration` : une mesure n'écrit rien, donc aucun
                # candidat à jeter en même temps.
                self.mesure.cancel()
                print("[server] mesure abandonnée — aucun verdict produit")

    def _drain_commands(self):
        while True:
            try:
                command, params, reseau = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                self._apply(command, params, reseau)
            except Exception as e:  # noqa: BLE001 - une commande fautive ne doit pas tuer le moteur
                print(f"[server] commande '{command}' rejetée : {e}")
                self._signale_echec(reseau, command, message_erreur(e))

    # --- la phase globale et l'état publié ------------------------------------
    # Le contrat public de `status` emploie « baseline » et « decoding » depuis le début ; les
    # runtimes emploient un autre vocabulaire (« rest », « running »). On traduit ici
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
        # valeur PUBLIQUE du flux `status` — un client peut s'en servir pour mettre son
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
        streams = ["quality", "status", _SUFFIXE_REPONSES]
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
        inlet = self.marker_inlet   # une seule lecture : la boucle peut le lâcher entre deux
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
            # Les quatre compteurs de marqueurs sortent ici : `modes/p300.py` les annonce comme le
            # moyen par lequel trois de ses six pannes sont dites, et `docs/markers.md` dit à
            # l'étudiant « si ce nombre grimpe ». Sans eux, un P300 qui ne déclenche jamais
            # serait indiscernable d'un sujet distrait.
            #
            # Ils n'entrent PAS dans `_status_key` : un compteur qui bouge ne doit pas compter
            # comme un changement d'état, sinon la déduplication du flux `status` tombe (19,6 Hz
            # de messages au lieu de 0,5 Hz). Ils voyagent donc avec le rappel périodique,
            # ce qui suffit largement pour un indicateur de santé.
            "marqueurs": {
                "perdus": self.marqueurs_perdus,
                "futurs": self.marqueurs_futurs,
                "illisibles": self.marqueurs_illisibles,
                "inlet_erreurs": self.marqueurs_inlet_erreurs,
                "connecte": inlet is not None and inlet.connecte,
            },
        }
        if self.rest_instruction and phase in ("warmup", "baseline"):
            # Le flux `status` est un contrat : la consigne y part en anglais, quelle que soit la
            # langue de l'écran. La console lit `rest_instruction` dans `snapshot()`.
            state["instruction"] = pour_le_contrat(self.rest_instruction)
        return state

    def snapshot(self):
        """État complet pour un afficheur, en lecture seule. Sûr depuis un autre fil.

        La console sonde ceci depuis le fil Qt, à 10 Hz, pendant que la boucle du
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
        # UNE copie, comme pour `calib` : sans elle, un même instantané pourrait porter un
        # `resultat` déjà déplacé dans `data/` ET le `candidat` d'avant le déplacement.
        candidat = self.candidat
        # UNE copie de la mesure, pour la même raison exactement : la boucle peut la remettre à
        # `None` (arrêt du moteur) entre deux lectures, et `None.state()` lèverait ICI, dans le
        # fil de la console.
        mesure = self.mesure
        enregistrement = self.enregistrement
        state = self._state(not self._stop, active=active, calibration=calib)
        etat_calib = None if calib is None else calib.state(now=time.perf_counter())
        if etat_calib is not None:
            # Ce que la console lit pour savoir s'il reste une DÉCISION à prendre. `resultat` dit
            # ce que vaut la séance ; `candidat` dit que le fichier n'est encore nulle part.
            # Après « Enregistrer », `resultat` reste (le verdict est toujours à l'écran) et
            # `candidat` retombe à None : plus rien à trancher.
            etat_calib["candidat"] = candidat
        state.update({
            "quality": self._qualite_affichee(),
            "rest_instruction": self.rest_instruction,
            "modes_state": {mid: r.state() for mid, r in active.items()},
            # La liaison avec le casque : dans `snapshot()` seulement, pas dans le
            # flux `status`, contrat public.
            "liaison": self._etat_liaison(),
            "casque": self._etat_casque(),
            # Le secteur du POSTE, fixé à la construction : ce que le moteur coupe,
            # et ce que chaque entraînement enregistre. Pas dans le flux `status` : ce n'est pas
            # un état qui change, et le contrat public n'a pas à grossir pour le dire.
            "secteur_hz": self.secteur_hz,
            # `now` est passé pour que le décompte affiché soit celui de MAINTENANT, pas celui du
            # dernier tick. La console sonde à 10 Hz, le moteur tourne à sa propre cadence : sans
            # ça le décompte avancerait par à-coups.
            "calibration": etat_calib,
            # La MESURE en cours, dans la MÊME forme qu'une calibration — c'est tout l'intérêt du
            # socle : `MesureRuntime` hérite de `state()` sans la redéfinir, donc un écran de
            # protocole peint l'une comme l'autre sans une ligne de plus.
            #
            # ⚠️ Elle ne figure pas dans `_state()`, donc pas dans le flux LSL `status` — comme
            # `calibration`, et pour la même raison : c'est un état d'INTERFACE, pas un contrat
            # public. La phase publiée, elle, reste celle des modes : une mesure n'empêche aucun
            # décodage (le taux d'émission SSVEP a précisément besoin que le mode tourne), donc
            # annoncer autre chose que « decoding » à un client serait faux.
            "mesure": None if mesure is None else mesure.state(now=time.perf_counter()),
            # L'enregistrement de séance : `None` tant qu'il n'y en a jamais eu, puis le dernier
            # — ARRÊTÉ OU NON. Le garder après l'arrêt est délibéré : c'est le chemin du fichier
            # qu'on vient chercher pour dépouiller, et une console qui l'oublie à la seconde où on
            # clique « Arrêter » obligerait à aller fouiller le dossier à la main. Copie prise une
            # seule fois, comme les trois voisines : la boucle peut le remplacer entre deux
            # lectures, et `None.state()` lèverait ICI, dans le fil de la console.
            "enregistrement": None if enregistrement is None else enregistrement.state(),
            # ⚠️ Les derniers réglages connus de CHAQUE mode, qu'il tourne ou non. Sans eux, un
            # réglage posé sur un mode ARRÊTÉ serait accepté, retenu, appliqué au démarrage… et
            # INVISIBLE : `modes_state` ne contient que les modes actifs, donc la page d'un mode
            # arrêté garderait l'ancienne valeur à l'écran, ce qui est pire qu'un refus franc.
            # Une COPIE par mode, jamais la référence : la boucle écrit dedans. Et le dict copié
            # d'un coup AVANT d'être parcouru (`dict(...)`, en C) : le fil de l'adaptateur réseau
            # y AJOUTE des modes pendant que la console lit, et parcourir le dict vivant lèverait
            # « dictionary changed size during iteration » dans le fil de la console.
            "reglages": {mid: dict(v) for mid, v in dict(self.reglages).items()},
            # Les dernières commandes reçues du RÉSEAU (des copies), pour que la console montre ce
            # que l'application a fait. Les raisons y sont dans la langue de l'écran.
            "pilotage": self.pilotage.journal(),
            # L'écoute du réseau, ce que la recherche voit, l'application connectée et la dernière
            # fin de connexion. Pas dans le flux `status` : un état d'INTERFACE.
            "ecoute": self.ecoute,
            "applications": self.pilotage.annonces(),
            # L'écoute des appareils réseau (UDP) : ouverte, ou pourquoi elle ne l'est pas (le
            # port est pris par une autre console, par exemple), et son port.
            "udp": self.pilotage.etat_udp(),
            "connexion": self._etat_connexion(),
            "fin_connexion": (None if self.fin_connexion is None
                              else dict(self.fin_connexion)),
            # Pas de catalogue ici : c'est une déclaration, pas de la télémétrie, et il ne change
            # pas avec l'état du moteur. Le republier dix fois par seconde coûterait des
            # entrées-sorties (joblib.load, système de fichiers) : on appelle `registry.catalog()`.
        })
        return state

    def recent_window(self, seconds):
        """Copie des `seconds` dernières secondes de signal BRUT (n, 8), ou None.

        Accesseur PUBLIC pour un afficheur — ET la source des époques
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
        noms = [self._flux_attendu(rt) for rt in self._ecouteurs_de_marqueurs()]
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
        (`p300.py`), pas seulement ici. Un entraînement ou un test à fenêtre qui finit libère
        l'inlet de la même façon (cf. `run()`), s'il était le dernier à écouter.
        """
        if self.marker_inlet is not None:
            return
        if not any(True for _rt in self._ecouteurs_de_marqueurs()):
            # Ouvrir un flux entrant qui ne sert à personne ferait chercher sur le réseau à
            # chaque tour pour rien.
            return
        self.marker_inlet = MarkerInlet(self._nom_flux_marqueurs(), timeout_s=0.0)
        self._marqueur_attente_dite = False
        self._resout_marker_inlet()

    def flux_a_ecouter(self, mode_id, params=None):
        """Le flux de marqueurs que `mode_id` entendrait s'il démarrait MAINTENANT, et qui tient
        l'écoute : `{"flux": nom, "tenu_par": [libellés]}`, ou None pour un mode sans marqueurs.

        Une QUESTION, sans effet, sûre depuis un autre fil : la console la pose avant un essai
        libre, au lieu de recopier la règle d'écoute. Cette règle : l'écoute est UNE pour tout le
        moteur (`_ouvre_marker_inlet`) ; tant que quelqu'un l'utilise, un mode qui démarre entend
        CE flux-là, quel que soit son `stream_in`. Sinon, il entend son `stream_in` : celui de
        `params`, à défaut celui du magasin.
        """
        spec = registry.get(mode_id)
        if spec is None or "stream_in" not in {p.key for p in spec.params}:
            return None
        inlet = self.marker_inlet
        tenu = [getattr(getattr(rt, "spec", None), "label", None) or "?"
                for rt in self._ecouteurs_de_marqueurs()]
        if inlet is not None and tenu:
            return {"flux": inlet.nom, "tenu_par": tenu}
        reglages = dict(params) if params is not None else self._reglages_de(spec)
        nom = (reglages.get("stream_in") or (spec.defaults() or {}).get("stream_in")
               or MARKER_STREAM_DEFAULT)
        return {"flux": nom, "tenu_par": []}

    def _ecouteurs_de_marqueurs(self):
        """Tout ce qui, dans CE moteur, consomme la file de marqueurs : les modes ET la calibration.

        ⚠️ Les quatre décisions « faut-il une oreille, sous quel nom, quand la lâcher, jusqu'où
        purger » ne doivent pas se prendre sur `self.active` SEUL. Une calibration ne vit PAS
        dans `self.active` (invariant de `modes/calibration.py`) : elle a son emplacement propre,
        parce qu'un mode qui refuse de démarrer sans modèle rendrait sa propre calibration
        inatteignable.

        Sur le parcours NORMAL du produit, la console arrête le mode avant de démarrer sa
        calibration (refus du vol de marqueurs) : plus aucun mode à marqueurs n'est actif. Sans
        cette méthode, aucun inlet ne s'ouvrirait, la fenêtre publierait ses marqueurs dans le
        vide, et le moteur abandonnerait au bout de `CALIB_FENETRE_ATTENTE_S` en annonçant « la
        fenêtre ne s'est pas lancée, ou elle publie sous un autre nom » — deux causes fausses
        qui enverraient l'étudiant vérifier une fenêtre qui tourne parfaitement.
        `_smoke_marqueurs_calibration` couvre ce chemin, que des autotests sur un moteur
        factice (file de marqueurs déjà remplie) ne voient pas.
        """
        # Une COPIE de `self.active` : `flux_a_ecouter` passe ici depuis le fil de la console,
        # pendant que la boucle peut démarrer ou arrêter un mode.
        for rt in list(dict(self.active).values()):
            if rt.spec.marker_epoch_s > 0.0:
                yield rt
        calib = self.calibration
        if (calib is not None and not calib.terminee
                and _calibration_lit_les_marqueurs(calib.spec.calibration)):
            yield calib
        # ⚠️ Et la MESURE, qui a exactement le même besoin et vit dans un troisième emplacement.
        # Elle n'est ni dans `self.active` ni dans `self.calibration` : l'oublier ici ferait
        # publier la fenêtre guidée dans le vide, et la mesure abandonnerait en annonçant « la
        # fenêtre ne s'est pas lancée, ou elle publie sous un autre nom », deux causes fausses.
        # Le critère est le même que pour une calibration : est-ce que cet
        # objet-là appelle `markers_murs` ? Il le déclare par `marker_mode_id`.
        mesure = self.mesure
        if mesure is not None and not mesure.terminee and _lit_les_marqueurs(mesure):
            yield mesure

    @staticmethod
    def _cle_marqueurs(rt):
        """Sous quelle clé CE runtime range son curseur dans `_marqueur_curseur`.

        Un mode et sa calibration la rangent sous l'identifiant du mode — c'est exactement pourquoi
        les deux ne peuvent pas tourner ensemble. Une MESURE, elle, porte son propre identifiant
        (`ssvep_taux`) mais lit des marqueurs estampillés d'un AUTRE `mode` (`ssvep`, celui du
        stimulus qu'elle mesure), et `markers_murs` filtre là-dessus. Sans cette lecture, la purge
        chercherait un curseur sous « ssvep_taux » qui n'existe pas et couperait devant la mesure,
        perdant en silence tout ce qui lui était adressé.
        """
        return getattr(rt, "marker_mode_id", None) or rt.spec.id

    @staticmethod
    def _flux_attendu(rt):
        """Le nom du flux de marqueurs que CE runtime attend.

        Un mode le déclare dans ses `params` (`stream_in`). Une calibration, elle, porte les
        `params` de la CALIBRATION, qui n'ont pas cette clé : on retombe alors sur le défaut
        DÉCLARÉ PAR LE MODE, pas sur la constante globale — sinon une calibration n'écouterait
        jamais le flux personnalisé de son propre mode, et `stream_in` redeviendrait le
        réglage-décor que ce projet combat.

        Un TEST (une mesure menée par une fenêtre) n'a pas cette clé non plus, et ce n'est pas un
        oubli : il lance NOTRE fenêtre, qui publie sur le flux par défaut, donc il l'écoute — le
        repli ci-dessous (`MesureSpec.defaults()` n'a pas de `stream_in`) y mène. Cf.
        `modes/mesure_marqueurs.CLE_FLUX`.
        """
        nom = rt.params.get("stream_in")
        if not nom:
            # `getattr` plutôt qu'un appel direct : plusieurs smokes du dépôt fabriquent des
            # `spec` factices (`SimpleNamespace`) qui ne portent que les deux ou trois champs
            # dont ils ont besoin. Un moteur ne doit pas tomber parce qu'un mode déclare moins
            # que le contrat complet — il retombe sur le défaut global, qui est le bon.
            defauts = getattr(rt.spec, "defaults", None)
            nom = (defauts() or {}).get("stream_in") if callable(defauts) else None
        return nom or MARKER_STREAM_DEFAULT

    def _resout_marker_inlet(self):
        """Tente la résolution si besoin, et DIT la transition — une seule fois par transition.

        `resolve_byprop(timeout=0.0)` échoue aux tout premiers appels d'un processus neuf (0
        succès sur 5 en rafale, le temps que le résolveur de liblsl remplisse son cache), puis
        marche. `_ouvre_marker_inlet` et la re-tentative de `_tire_marqueurs` passent donc par
        cette méthode, pour que le message suive l'ÉVÉNEMENT (la connexion) et non le chemin : sinon
        l'étudiant lirait « pas encore là » sans jamais voir de confirmation.
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
        """Lâche l'inlet s'il ne sert plus à aucun écouteur. True s'il y avait quelque chose.

        Appelée depuis `_stop_mode`, à chaque tour de `run()` (un entraînement ou un test à
        fenêtre qui finit) et à l'arrêt du moteur : garder un inlet ouvert pour personne empêche
        la re-résolution (`_ouvre_marker_inlet` ne recrée rien tant qu'il est non-None) — le
        prochain mode écouterait l'ANCIEN nom — et fait grossir `_marqueurs` sans personne pour
        les consommer.
        """
        if self.marker_inlet is None:
            return False
        if any(True for _rt in self._ecouteurs_de_marqueurs()):
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

        ⚠️ `modes/p300.py` annonce ces quatre compteurs comme le moyen par lequel trois de ses six
        pannes sont dites, et `docs/markers.md` dit à l'étudiant « si ce nombre grimpe ». Le cas le
        plus probable — un `time_correction()` oublié côté émetteur, donc TOUT qui part dans
        `marqueurs_futurs` — donne un P300 qui tourne, ne déclenche jamais, et ne dit rien : il
        faut que les compteurs se disent (ici, et dans `_state`).

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

        ⚠️ SANS écouteur, en revanche, « ce que TOUS les écouteurs ont dépassé » est TOUT : rendre
        la main (`if not ecouteurs: return`) ferait croître le tampon sans borne (~5 Mo en 30 min,
        sans un compteur ni un message). Ce chemin ne devrait plus être atteignable depuis que
        l'inlet est lâché dès que le dernier écouteur s'en va (`_stop_mode` pour un mode, chaque
        tour de `run()` pour un entraînement ou un test qui finit) ; il reste écrit juste, parce
        qu'un garde qui ne tient que par un autre garde ne tient pas.
        """
        if len(self._marqueurs) <= 4096:
            return
        # `spec.id` et non la clé de `self.active` : une CALIBRATION est un écouteur elle aussi
        # (cf. `_ecouteurs_de_marqueurs`), et elle n'a pas d'entrée dans `self.active`. Son curseur
        # est rangé dans `_marqueur_curseur` sous l'identifiant de son mode, comme celui du mode —
        # ce qui est exactement pourquoi les deux ne peuvent pas tourner ensemble.
        ecouteurs = [self._cle_marqueurs(rt) for rt in self._ecouteurs_de_marqueurs()]
        if not ecouteurs:
            print(f"[server] marqueurs entrants : {len(self._marqueurs)} marqueur(s) jetés — "
                  f"plus personne ne les écoute (aucun mode à marqueurs actif, aucune "
                  f"calibration en cours).")
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

        « Mûr » = le tampon couvre déjà les `post_s` secondes qui SUIVENT le marqueur. Sinon
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
            # ⚠️ Dans l'ordre inverse (maturité d'abord), un marqueur horodaté loin dans le futur
            # n'est PAR DÉFINITION jamais « mûr » : il déclenche le `break` juste en dessous AVANT
            # ce contrôle, `marqueurs_futurs` devient inatteignable, et le curseur ne le dépasse
            # jamais — tout ce qui arrive après lui (y compris des marqueurs valides) reste
            # bloqué derrière, pour toujours. Tenu par `_smoke_marqueurs_file_coincee`.
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

    def _qualite_affichee(self):
        """`_quality`, tel que la console le montre. Liaison perdue : plus aucun verdict de
        contact ni de référence. Le dernier σ date d'avant la coupure, et une électrode peinte en
        vert sur un casque muet mentirait."""
        qualite = self._quality
        if qualite is None or self._liaison != "perdue":
            return qualite
        return dict(qualite, contact=[None] * len(qualite["contact"]), reference_ok=None)

    def _publish_quality(self, lsl_ts):
        """σ par voie sur les dernières secondes, calculé sur du signal FILTRÉ.

        Le filtrage est indispensable ICI (contrairement au flux brut) : sur du signal
        quasi-brut, le σ est dominé par le ronflement secteur 50 Hz et la dérive lente des
        électrodes sèches, pas par l'EEG — un σ mesuré ainsi ne dit rien de l'état du contact.

        Le calcul est délégué à `sigma_from_block` pour partager UNE seule définition du σ
        avec l'écran `signal_check` de l'appli : deux mesures de qualité qui divergeraient
        seraient pires que pas de mesure du tout.

        ⚠️ On ne passe PAS `self.recent` en entier : ce tampon est dimensionné (`self.keep`,
        cf. `__init__`) pour le plus gourmand de TOUS ses consommateurs — la calibration MI, qui
        prélève des époques de 4 s là où cette fenêtre de qualité n'en veut que
        `QUALITY_WINDOW_S` (2 s). Passer le tampon entier ferait dépendre le σ, flux PUBLIC, de
        la plus longue époque de calibration, sans que rien ne le dise. On borne donc le bloc à
        la fenêtre déclarée plus sa marge de filtre, comme tous les autres lecteurs du tampon
        (`recent_window`, `motor_window`, `occipital_window`…).
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
            # Le CONTACT de chaque électrode, pour « Vérifier le casque » : True, False, ou None
            # sans mesure. Plus strict que `verdicts`, qui ne repère que les voies plates ou
            # saturées : au-delà de `seuil_contact`, l'électrode capte surtout du bruit.
            "contact": [contact_bon(v) for v in sigmas],
            "seuil_contact": CONTACT_SIGMA_MAX,
            # La référence (les pastilles derrière les oreilles) : None sur le board de test, qui
            # n'a pas d'électrode, ou quand la corrélation n'a pas pu se calculer.
            "reference_ok": None if self.synthetic or common is None else not lost,
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
        # défaut : un simple print tuerait le fil d'acquisition sur un UnicodeEncodeError. On
        # le fait ici plutôt que dans le seul `__main__`, parce que le moteur est aussi utilisé
        # comme bibliothèque (console, tests) — et qu'un échec d'AFFICHAGE ne doit jamais
        # interrompre une ACQUISITION.
        use_utf8_console()

        started = time.perf_counter()
        last_quality = last_status = 0.0

        with self.acq:
            self.acquisition_ouverte = True
            print(f"[server] board={self.acq.board_id.name} fs={self.acq.fs} Hz "
                  f"secteur={self.secteur_hz:g} Hz instance={self.instance}")
            for suffix in ("quality", "status", _SUFFIXE_REPONSES):
                print(f"[server] flux LSL publie : {stream_name(suffix)}")
            if self.ecoute == "permanente":
                print(f"[server] écoute les commandes des applications de cette machine sur : "
                      f"{self.pilotage.nom_flux}")
            else:
                print(f"[server] écoute sur demande : l'application qu'on connecte, par LSL "
                      f"({self.pilotage.nom_flux}) ou par le réseau (UDP)")
            try:
                # `_start` est DANS le `try`, et pas avant : un constructeur de runtime peut lever
                # — celui du MI le fait PAR CONCEPTION quand le modèle a disparu entre la
                # validation et le démarrage. Or le `finally` plus bas casse le cycle
                # `active ↔ engine`, sans quoi un `BoardShim.__del__` tardif libère la session d'un
                # AUTRE moteur (voir son long commentaire) : le sauter ferait payer l'incident au
                # moteur SUIVANT du même processus.
                # Depuis le MAGASIN, où la construction a rangé les réglages de `_pending` : un
                # `set_params` accepté entre la construction et ce démarrage part avec.
                self._start([s.id for s, _ in self._pending], None, time.perf_counter())
                self.status_out.push(self._state(True, calibration=self.calibration),
                                     key=self._status_key(True), force=True)
                # L'écoute du réseau commence une fois les flux annoncés et les modes demandés
                # démarrés. Son fil ne fait qu'appeler `submit` : c'est cette boucle qui applique.
                # Une écoute qui ne démarre pas se DIT : le moteur vient d'annoncer qu'il écoute,
                # et une application lui parlerait sans jamais recevoir de réponse.
                # Sur demande, l'écoute des appareils réseau (UDP) s'ouvre juste avant.
                self._ouvrir_udp()
                if not self.pilotage.demarrer():
                    print(f"[server] ⚠️ l'écoute de {self.pilotage.nom_flux} n'a PAS démarré : "
                          f"aucune application ne peut piloter ce moteur.")

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
                    eeg, ts_unix = self._lire()
                    self.new_block = None
                    if eeg is not None and len(eeg):
                        ts_lsl = self.clock.to_lsl(ts_unix)
                        self.new_block = (eeg, ts_lsl)
                        self.recent = np.vstack([self.recent, eeg])[-self.keep:]
                        self.recent_ts = np.concatenate([self.recent_ts, ts_lsl])[-self.keep:]
                        self._dernier_echantillon = now
                        self._paquets.append((now, self.acq.paquets_recus,
                                              self.acq.paquets_perdus))
                        while self._paquets and now - self._paquets[0][0] > FENETRE_PAQUETS_S:
                            self._paquets.popleft()
                    elif self._surveille_liaison(now):
                        # Liaison PERDUE : aucun mode ne décode, aucune séance ne tourne. Décoder
                        # le tampon figé republierait la dernière décision en boucle — un SSVEP
                        # qui annonce la même cible pendant toute la coupure, et une application
                        # qui continue d'agir dessus. On ne fait que les commandes et le statut —
                        # et la PAUSE : sans elle, la boucle tournerait à vide entre deux essais.
                        due = now - last_status >= STATUS_PERIOD_S
                        if self.status_out.push(self._state(True, calibration=self.calibration),
                                                key=self._status_key(True), force=due) and due:
                            last_status = now
                        self._pousser_statut(now)
                        time.sleep(POLL_S)
                        continue

                    self._tire_marqueurs()

                    if now - last_quality >= QUALITY_PERIOD_S:
                        self._publish_quality(self.clock.to_lsl(time.time()))
                        last_quality = now

                    for mode_id, runtime in list(self.active.items()):
                        if now - self._last_tick.get(mode_id, 0.0) >= runtime.period_s():
                            # L'horodatage est calculé UNE fois et servi deux fois : au mode (qui
                            # le donne à son publieur) puis à l'enregistrement. Le recalculer pour
                            # le fichier écrirait une date légèrement différente de celle partie
                            # sur le réseau : un écart invisible, qu'on ne retrouve jamais.
                            lsl_ts = self.clock.to_lsl(time.time())
                            # Avant le pas : ce qu'il publiera part aussi vers l'appareil réseau
                            # connecté, s'il a démarré ce mode.
                            self._observer_la_sortie(mode_id, runtime)
                            runtime.tick(self, lsl_ts, now)
                            self._last_tick[mode_id] = now
                            # L'enregistrement de séance, juste après le tick du mode qu'il suit.
                            # `noter` n'écrit que si une NOUVELLE décision a été publiée (cf.
                            # `_Enregistrement`), donc un tour muet ne laisse aucune trace.
                            enr = self.enregistrement
                            if enr is not None and enr.actif and enr.mode_id == mode_id:
                                enr.noter(runtime, float(lsl_ts))

                    # La calibration tourne à CHAQUE tour, sans période minimale : sa ligne du
                    # temps se compte en dixièmes de seconde et un décompte qui saute serait vu.
                    if self.calibration is not None and not self.calibration.terminee:
                        try:
                            self.calibration.tick(self, now)
                        except Exception as e:  # noqa: BLE001 - un tick fautif ne doit tuer NI
                            # le moteur NI la séance en cours des AUTRES modes : on perd cette
                            # calibration (potentiellement plusieurs minutes d'imagerie), pas le
                            # reste. Marquer « annulé » avec sa raison, comme `_terminer` pour un
                            # entraînement qui lève.
                            self.calibration.probleme = message_erreur(e)
                            self.calibration.phase = "annule"
                            print(f"[server] calibration interrompue par une exception : "
                                  f"{self.calibration.probleme}")
                    # Hors du `if` ci-dessus, et c'est le point : une calibration qui vient
                    # d'aboutir EST terminée, donc ce `if` ne l'exécute plus.
                    self._adopte_candidat()

                    # La MESURE, exactement au même régime que la calibration : chaque tour, sans
                    # période minimale, et sous le même filet. ⚠️ Aucun `_adopte_candidat` en
                    # face : une mesure ne produit AUCUN fichier, donc il n'y a rien à ramasser —
                    # son verdict vit dans `self.mesure.resultat` et part dans `snapshot()`.
                    if self.mesure is not None and not self.mesure.terminee:
                        try:
                            self.mesure.tick(self, now)
                        except Exception as e:  # noqa: BLE001 - un tick fautif ne doit tuer NI le
                            # moteur NI la séance des autres modes. Même traitement que la
                            # calibration juste au-dessus : « annulé » avec sa raison à l'écran.
                            self.mesure.probleme = message_erreur(e)
                            self.mesure.phase = "annule"
                            print(f"[server] mesure interrompue par une exception : "
                                  f"{self.mesure.probleme}")
                            # …et ABANDONNÉE pour de bon : un test qui publie sur le flux de
                            # son mode le ferme ici, sinon l'outlet survivrait au test et
                            # doublerait celui du mode qu'on démarrera ensuite. ⚠️ GARDÉ : un
                            # `cancel()` qui lève ici sortirait de la boucle — moteur tué, et
                            # l'exception d'ORIGINE masquée par la sienne.
                            try:
                                self.mesure.cancel()
                            except Exception as e_cancel:  # noqa: BLE001 - cf. ci-dessus
                                print(f"[server] abandon de la mesure en erreur, ignoré : "
                                      f"{e_cancel!r}")

                    # Un entraînement ou un test À FENÊTRE qui vient de finir n'écoute plus les
                    # marqueurs. S'il était le dernier à écouter, l'inlet part avec lui : sinon il
                    # restait ouvert sur le flux de NOTRE fenêtre, et un P300 démarré ensuite sur
                    # le flux d'un jeu (`stream_in`) l'aurait gardé — `_ouvre_marker_inlet` ne
                    # recrée rien tant qu'un inlet existe —, muet, sans un mot. Sans effet tant
                    # qu'un écouteur reste.
                    self._libere_marker_inlet("plus personne n'écoute les marqueurs")

                    # Publié quand l'état change, plus un rappel périodique pour les clients qui
                    # se connectent après le démarrage (LSL ne rejoue pas le passé).
                    due = now - last_status >= STATUS_PERIOD_S
                    if self.status_out.push(self._state(True, calibration=self.calibration),
                                            key=self._status_key(True), force=due) and due:
                        last_status = now
                    # Et la phase des modes de l'appareil réseau connecté, à son propre rythme.
                    self._pousser_statut(now)

                    time.sleep(POLL_S)

                self.status_out.push(self._state(False, calibration=self.calibration),
                                     key=self._status_key(False), force=True)
            finally:
                # DOIT s'exécuter sur TOUTE sortie de la boucle, y compris une EXCEPTION — casque
                # perdu en séance, erreur BrainFlow : précisément ce que ce produit doit survivre.
                # Sans ce `finally`, une exception levée par `get_new_data()` ou par un `tick()`
                # saute tout ce bloc : ni les flux ne se ferment, ni le cycle plus bas ne se
                # rompt, et le PROCHAIN moteur du même processus en subit les conséquences.
                #
                # L'écoute du réseau s'arrête EN PREMIER : une commande acceptée maintenant ne
                # serait plus jamais appliquée. Le flux de réponses, lui, reste annoncé jusqu'à
                # `retirer_flux()` ou la fin du moteur. Juste avant, l'arrêt du moteur est
                # ANNONCÉ : en s'arrêtant, le fil d'écoute le dit à chaque application qu'il
                # écoute (« disconnected »), avec les modes qui tournaient. Sans ça, une
                # application qui attend sans limite (un démarrage différé) attendrait toujours.
                try:
                    self.pilotage.annoncer_arret(list(self.active))
                except Exception as e:  # noqa: BLE001 - la suite de ce `finally` doit s'exécuter
                    print(f"[server] annonce de l'arrêt aux applications en erreur : {e!r}")
                try:
                    self.pilotage.arreter()
                except Exception as e:  # noqa: BLE001 - la suite de ce `finally` doit s'exécuter
                    print(f"[server] arrêt de l'écoute du réseau en erreur : {e!r}")
                # Le port UDP est rendu : une console rouverte (ou le moteur suivant) le reprend.
                try:
                    self.pilotage.fermer_udp()
                except Exception as e:  # noqa: BLE001 - la suite de ce `finally` doit s'exécuter
                    print(f"[server] fermeture de l'écoute UDP en erreur : {e!r}")
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
                # cible. Mesuré : deux `EngineServer` synthétiques lancés l'un après l'autre dans
                # le même processus, le second échoue sur `get_new_data()` avec
                # `BOARD_NOT_CREATED_ERROR`.
                #
                # Vider `active` casse le cycle : `self` (et son `BoardShim`) redevient
                # collectable par simple comptage de références, donc nettoyé tout de suite —
                # avant qu'un `__del__` tardif ait la moindre chance de viser la mauvaise
                # session. Sans ce test-là (deux moteurs de suite, comme le fait `--smoke`),
                # rien ne révèle le problème : un seul moteur par processus ne le voit jamais.
                #
                # Une calibration en cours ne survit pas à l'arrêt du moteur : elle tient des
                # époques en mémoire et une référence vers `self` — le même cycle que les modes.
                # ⚠️ Les deux `cancel()` sont GARDÉS : un qui lève sauterait tout ce qui suit —
                # `close()`, le cycle rompu, l'inlet de marqueurs libéré —, c'est-à-dire
                # exactement ce que ce `finally` existe pour garantir.
                if self.calibration is not None:
                    try:
                        self.calibration.cancel()
                    except Exception as e:  # noqa: BLE001 - cf. ci-dessus
                        print(f"[server] abandon de la calibration à l'arrêt, ignoré : {e!r}")
                    self.calibration = None
                # Une mesure non plus : elle tient les mêmes fenêtres de signal et la même
                # référence vers `self`, donc le même cycle. Le verdict disparaît avec elle, et
                # c'est sans conséquence : le moteur ne s'arrête que quand la console se ferme,
                # et il n'y a aucun fichier à récupérer.
                if self.mesure is not None:
                    try:
                        self.mesure.cancel()
                    except Exception as e:  # noqa: BLE001 - cf. ci-dessus
                        print(f"[server] abandon de la mesure à l'arrêt, ignoré : {e!r}")
                    self.mesure = None
                # ⚠️ INCONDITIONNEL, dans le `finally` : si le moteur s'arrête entre
                # l'entraînement et la décision — console fermée, Ctrl+C, exception BrainFlow —
                # aucun candidat ne doit survivre au processus. `close()` est idempotente, la
                # console peut donc l'appeler aussi de son côté sans rien casser.
                self.close()
                self.active = {}
                # APRÈS `self.active = {}`, jamais avant : `_libere_marker_inlet` ne lâche que
                # s'il ne reste plus un seul écouteur, et c'est cette ligne-là qui le garantit.
                # Un moteur arrêté n'a plus rien à écouter : aucun inlet LSL ne doit survivre à la
                # boucle.
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
    (cadence lue à 401 Hz au lieu de 250, échantillons reçus en surnombre). On filtre donc sur le `source_id`, qui porte l'instance.
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
    server = EngineServer(synthetic=True, instance=instance)               # raw seul

    # Garde-fou : `_filter` ne doit JAMAIS modifier son entrée. Le serveur lui passe un
    # tampon persistant ; s'il était filtré sur place, les échantillons bruts suivants
    # seraient collés sur une queue déjà filtrée et le σ deviendrait absurde (40 000 µV
    # mesurés sur un EEG à 5 µV). Un tableau contigu float64 est exactement le cas à risque.
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
    # glissé dans la charge utile suffit à le faire émettre à 19,6 Hz au lieu de 0,5 Hz
    # (dédup défaite) — discret, mais assez bruyant pour noyer un client. D'où la borne dure.
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
    # cascade. Un `and` court-circuite : dès le premier `False`, les suivants ne sont plus appelés
    # et restent muets, donc un seul test instable (timing réseau, SSVEP…) masquerait
    # SILENCIEUSEMENT tous ceux placés après lui. Avec la liste, chaque appel s'exécute et imprime
    # son propre VERDICT ; `all()` ne fait que COMBINER des résultats déjà obtenus.
    resultats = [
        ok,
        integre,
        _smoke_frontiere(),
        _smoke_version(),
        _smoke_chemins(),
        _smoke_point_entree(),
        _smoke_journal(),
        _smoke_textes(),
        _smoke_exemples(),
        _smoke_repos_partage(),
        _smoke_ssvep(),
        _smoke_neuro(),
        _smoke_mi(),
        _smoke_calibration(),
        _smoke_calibration_refus(),
        _smoke_oreille_calibration(),
        _smoke_vol_marqueurs(),
        _smoke_mesure(),
        _smoke_retour_en_direct(),
        _smoke_liaison(),
        _smoke_casque(),
        _smoke_secteur(),
        _smoke_enregistrement(),
        _smoke_cumul(),
        _smoke_proposition(),
        _smoke_dimensionnement(),
        _smoke_tampon_horodate(),
        _smoke_marqueurs_murs(),
        _smoke_marqueurs_file_coincee(),
        _smoke_marqueurs_inlet(),
        _smoke_inlet_apres_seance(),
        _smoke_marqueurs_relance(),
        _smoke_marqueurs_stream_in(),
        _smoke_stream_in_ouvert(),
        _smoke_reseau_moteur(),
        _smoke_magasin_refus_du_runtime(),
        _smoke_pilotage(),
        _smoke_connexion_a_froid(),
        _smoke_connexion(),
        _smoke_deconnexion(),
        _smoke_appareil_udp(),
        _smoke_exemple_udp(),
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
    # stimulus. Le littéral arrondi 8.57 n'est PAS un diviseur entier de 60 Hz
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

    **Tout est écrit dans un dossier temporaire. Le vrai `data/` n'est jamais approché** — comme
    son voisin `_smoke_calibration`. Écrire puis effacer un fichier dans `data/` ne survivrait
    qu'à un arrêt DUR (Ctrl+Break, taskkill, coupure), mais `empreinte_dossier` est AVEUGLE à un
    créer-puis-effacer dans la même fenêtre de mesure (cf. sa docstring) : le remède est de ne
    jamais approcher `data/`, pas de réduire la fenêtre d'exposition.

    Le levier est en place, et délibérément : `modes/mi.py` déclare
    `choices_fn=lambda: mi_models.modeles_disponibles()` — un lambda qui résout la fonction À
    L'APPEL, précisément pour qu'un autotest puisse rediriger la recherche ailleurs. Le chemin du
    modèle, lui, est déjà passé explicitement ; `data/` ne servait qu'à faire passer le contrôle
    d'appartenance de `validate` sur un `kind="choice"`.

    Le `finally` reste obligatoire, et il doit couvrir l'ÉCRITURE du fichier ET la construction du
    serveur : `EngineServer.__init__` lève PAR CONCEPTION dès qu'un réglage est invalide (« lève
    ici, au démarrage — bruyamment et tout de suite », cf. sa docstring), et peut aussi lever si
    la session BrainFlow refuse de s'ouvrir. `server`/`thread` sont donc initialisés à `None`
    AVANT le `try`, pour que le `finally` puisse s'exécuter même si `EngineServer(...)` n'a jamais
    rendu la main, sans jamais lire une variable non assignée.

    Comme pour le SSVEP et le neuro (cf. leurs docstrings), on ne juge PAS la justesse du
    décodage : le board synthétique n'émet aucune vraie imagerie motrice. On vérifie le
    CÂBLAGE — le flux existe, porte le bon nombre de voies, publie en continu, ses valeurs
    restent finies et somment à 1, et le décodeur LIT vraiment la fenêtre qu'on lui passe (les
    probabilités varient d'un échantillon à l'autre) plutôt que de republier une valeur figée.
    """
    import shutil
    import tempfile
    import threading

    from core import mi_models
    from core.mi_decoder import MI_LABELS, MIModel, synth_mi_trial

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    dossier = tempfile.mkdtemp(prefix="smoke_mi_")
    chemin = os.path.join(dossier, "mi_model_smoke.joblib")
    vrai_dispo = mi_models.modeles_disponibles
    mi_models.modeles_disponibles = lambda d=dossier: vrai_dispo(d)
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
            # voies ne prouve rien sur ce que le client lit. Les voies sont numérotées (`p_0`…) ;
            # ce sont les `classes` annoncées qui disent quelle tâche porte chaque numéro. Un
            # publieur câblé sur de mauvaises `classes` publierait le bon nombre de voies pour un
            # modèle qui n'a pas ces tâches-là — invisible à un compte.
            etiquettes, noeud = [], inlet.info().desc().child("channels").child("channel")
            while not noeud.empty():
                etiquettes.append(noeud.child_value("label"))
                noeud = noeud.next_sibling()
            decodage = inlet.info().desc().child("decoding")
            echelle = decodage.child_value("decision_scale")
            sans_decision = decodage.child_value("no_decision_index")
            repos = decodage.child_value("rest_index")
            classes_annoncees = decodage.child_value("classes")
            attendues = mi_channel_labels(MI_LABELS)
            chk(etiquettes == attendues and etiquettes[2:] == ["p_0", "p_1", "p_2"],
                f"les voies annoncées sont celles du contrat, numérotées ({etiquettes})")
            chk(classes_annoncees == ",".join(MI_LABELS),
                f"…et les métadonnées nomment les tâches du MODÈLE, dans l'ordre des voies "
                f"({classes_annoncees!r})")
            # La console nomme les barres et la tâche décodée AVANT la première décision : les
            # noms viennent de l'état du moteur, qui tient le modèle (elle ne le lit pas).
            noms_etat = (server.snapshot()["modes_state"].get("mi") or {}).get("noms")
            chk(noms_etat == list(MI_LABELS),
                f"…et l'état du moteur nomme les mêmes tâches, dans le même ordre ({noms_etat})")
            chk(echelle == "proba",
                f"l'échelle de décision annoncée est « proba », pas le z du SSVEP ({echelle!r})")
            # « Je ne sais pas » n'est aucune des tâches : le flux le dit lui-même. Le repos, lui,
            # est une tâche comme les autres — aucune métadonnée ne le met à part.
            chk(sans_decision == "-1" and repos == "",
                f"le flux dit lui-même ce que vaut « aucune décision », et ne met aucune tâche à "
                f"part, le repos compris (no_decision_index={sans_decision!r}, "
                f"rest_index={repos!r})")
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
        # La RESTAURATION du catalogue passe en premier : la laisser après un `join` qui peut
        # lever rendrait `mi_models.modeles_disponibles` définitivement pointé sur un dossier
        # temporaire effacé, pour tout le reste du processus (donc pour les smokes suivants).
        # Le `join` ne s'exécute que sur un fil réellement démarré — `thread.join()` sur un fil
        # jamais démarré lève `RuntimeError`.
        mi_models.modeles_disponibles = vrai_dispo
        shutil.rmtree(dossier, ignore_errors=True)
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

    Il couvre aussi TOUT LE CYCLE DU CANDIDAT : le
    modèle est écrit dans le dossier temporaire du moteur, invisible aux quatre catalogues, et ne
    rejoint `data/` que sur `save_calibration`. C'est ici qu'il faut le vérifier, parce que le
    candidat y est produit par une VRAIE calibration passée par la boucle — pas fabriqué à la main.

    Tout est écrit dans des dossiers temporaires : le `data/` du moteur est DÉTOURNÉ (`data_dir`),
    et le vrai est comparé avant/après par son empreinte. Aucun des deux n'est approché.
    """
    import shutil
    import tempfile
    import threading
    from fnmatch import fnmatch

    from core.config import CALIB_CANDIDAT_PREFIXE, empreinte_dossier

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    from core.mi_decoder import MI_LABELS
    from core.modes import mi_calib

    # Le `data/` DÉTOURNÉ : la destination de `save_calibration`. Le vrai `data/` porte des
    # enregistrements EEG d'une personne identifiable, sur un dépôt public, et son fichier le plus
    # récent est celui que le moteur ÉLIT — un modèle de test qui y atterrirait serait proposé à
    # la prochaine séance casque.
    data_dir = tempfile.mkdtemp(prefix="srv_data_")
    empreinte_avant = empreinte_dossier()
    # On raccourcit le protocole POUR LE TEST en remplaçant les durées sur la classe : c'est la
    # seule façon de jouer une séance de sept minutes en quelques secondes sans donner à
    # `CalibrationRuntime` une horloge accélérée, qui serait un chemin de code que la séance
    # réelle n'emprunte jamais.
    # Pas de monkeypatch de `MICalibration.__init__` : c'est le MOTEUR qui donne son dossier
    # candidat à la calibration, et ce test prouve que ce câblage fonctionne.
    anciens = {c: getattr(mi_calib.MICalibration, c)
               for c in ("cue_s", "imagery_s", "rest_s", "warmup_s", "warmup_per_class",
                         "window_s", "step_s")}
    try:
        # ⚠️ `window_s` et `step_s` sont raccourcis AVEC `imagery_s`, pas séparément : avec une
        # imagerie de 0,20 s et une fenêtre restée à 2 s, `decouper` ne rend AUCUNE fenêtre et
        # l'entraînement refuse. Le rapport est conservé — 0,32 / 0,16 / 0,08 donne 3 fenêtres
        # par essai, comme 4 / 2 / 1 en séance réelle.
        #
        # ⚠️ Pas plus court que 0,32 s : `MIModel.fit` passe chaque fenêtre dans un filtre
        # passe-bande 0-phase (`scipy.signal.filtfilt`, ordre 4), qui EXIGE plus d'échantillons
        # que son `padlen` (27 : `3 * (2*ordre+1)`). Une imagerie de 0,20 s (fenêtre de 0,10 s,
        # soit 25 échantillons à 250 Hz) est sous ce plancher : l'entraînement lèverait avant la
        # comparaison honnête/naïve. 0,32 s donne une fenêtre de 40 échantillons.
        mi_calib.MICalibration.cue_s = 0.05
        mi_calib.MICalibration.imagery_s = 0.32
        mi_calib.MICalibration.rest_s = 0.05
        mi_calib.MICalibration.warmup_s = 0.10
        mi_calib.MICalibration.warmup_per_class = 1
        mi_calib.MICalibration.window_s = 0.16
        mi_calib.MICalibration.step_s = 0.08

        # Un moteur au secteur des AMÉRIQUES, exprès (`[smoke-secteur]`) : chaque entraînement le
        # lit par `getattr(engine, "secteur_hz", SECTEUR_HZ)`, donc un attribut mal nommé ou mal
        # posé retomberait EN SILENCE sur 50 Hz — et seul un moteur qui n'est PAS au défaut le voit.
        server = EngineServer(synthetic=True, modes=("raw",), instance="smoke-calib",
                              data_dir=data_dir, secteur_hz=60.0)
        # 120 s, pas 60 : la séance mesure ~27 s mais le PAS de boucle (POLL_S, plus la latence
        # des E/S) ajoute couramment ~8,5 s de plus, et un dépassement de
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

            # « Essais par classe » est un « choice » borné à MI_SESSIONS (core/config.py), pas un
            # entier libre : 6 est refusé par `contract.validate`. Le plus PETIT choix valide, 10,
            # est accepté mais rend la comparaison honnête/naïve plus bas peu fiable sur du bruit
            # pur (~1 essai sur 2 viole l'invariant sur 4 tirages répétés) : la fenêtre
            # d'entraînement n'a aucun signal réel à apprendre, contrairement aux autotests de
            # mi_calib.py/mi_decoder.py qui fabriquent une ERD. 18 (3e choix) ramène cela à ~1
            # tirage sur 6, pour un coût en temps raisonnable.
            # Deux `start_calibration` soumis dans la MÊME fenêtre de sondage (avant que la
            # boucle n'ait drainé le premier) doivent produire UNE SEULE calibration, pas deux
            # qui se chevauchent. `submit()` ne peut PAS voir venir cette course :
            # `self.calibration` est encore `None` pour LES DEUX au moment où elles sont
            # soumises — c'est la garde côté BOUCLE (`_start_calibration`) qui compte. Les deux
            # commandes partent donc DOS À DOS, sans attendre entre les deux : attendre
            # `server.calibration is not None` avant la seconde contournerait la fenêtre de
            # course qu'il s'agit de couvrir.
            # Les TROIS tâches d'origine, explicitement (le défaut est de deux) : les comptes
            # ci-dessous (18 × 3 = 54) et le signal appris portent sur elles.
            ack = server.submit("start_calibration", id="mi",
                                params={"taches": list(MI_LABELS), "trials_per_class": 18})
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

            # Une fois la première APPLIQUÉE, cette fois `submit()` lui-même la voit et refuse.
            refus = server.submit("start_calibration", id="mi", params={})
            chk(not refus.get("accepted") and "déjà en cours" in (refus.get("reason") or ""),
                f"une troisième, soumise APRÈS coup, est refusée par submit() lui-même ({refus})")
            chk(server.phase == "calibrating",
                f"la phase publique du moteur devient « calibrating » ({server.phase})")
            etat = server.snapshot().get("calibration")
            chk(etat is not None and etat["mode_id"] == "mi" and etat["total"] == 54,
                f"et snapshot() porte l'état complet, celui de la PREMIÈRE (18×3=54) ({etat})")

            # 18 essais/classe jouent 54 essais, à ~0,42 s/essai avec les durées raccourcies :
            # ~27 s mesurées de bout en bout. 45 s laisse une marge confortable.
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
            # et continue) — déréférencer `calib._enregistre` sans garde donnerait une trace
            # Python brute au lieu du diagnostic ligne à ligne que ce smoke doit rendre.
            attendu = int(round(mi_calib.MICalibration.imagery_s * server.acq.fs))
            longueurs = {len(e) for e, _l in calib._enregistre} if calib is not None else set()
            chk(longueurs == {attendu},
                f"chaque époque fait exactement {attendu} échantillons ({sorted(longueurs)})")

            # ⚠️ Ce contrôle ne dépend PAS de la séance jouée, qui tourne sur des durées
            # rabotées. Le tampon du moteur doit tenir la plus longue époque que le CONTRAT annonce
            # (`Calib.epoch_s` = 4 s pour le MI), pas seulement la fenêtre de décodage (2 s). Sans
            # ce terme dans `keep`, chaque époque d'une séance RÉELLE serait tronquée de moitié —
            # sans erreur, avec un tiers des fenêtres d'entraînement attendues. Deux
            # vérifications, parce qu'aucune ne suffit seule : le dimensionnement calculé, et le
            # bloc réellement rendu.
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

            # === LE CYCLE DU CANDIDAT ===================================================
            # 1. Le candidat vit dans le dossier du MOTEUR, et `data/` n'a RIEN reçu.
            candidat = server.snapshot().get("calibration", {}).get("candidat")
            chk(candidat is not None and candidat.get("modele") == res.get("modele"),
                f"`snapshot()[\"calibration\"][\"candidat\"]` porte le résultat de l'entraînement "
                f"({None if candidat is None else os.path.basename(candidat.get('modele') or '')})")
            chk(bool(res.get("modele")) and os.path.dirname(res["modele"]) == server.calib_dir,
                f"le modèle est écrit dans le dossier CANDIDAT du moteur, pas dans data/ "
                f"({res.get('modele')})")
            chk(os.path.basename(res.get("modele", "")).startswith(CALIB_CANDIDAT_PREFIXE),
                f"…sous un nom qui le marque comme candidat "
                f"({os.path.basename(res.get('modele', ''))})")
            chk(os.listdir(data_dir) == [],
                f"…et une calibration TERMINÉE n'a rien écrit dans data/ : le chiffre s'affiche "
                f"AVANT que quoi que ce soit ne soit retenu ({os.listdir(data_dir)})")
            # [smoke-secteur] L'entraînement joué par CE moteur (60 Hz) produit un modèle à 60 Hz :
            # dans le résultat affiché ET dans le FICHIER, relu tel que le décodage le relira.
            relu, raison_relu = mi_models.charger(res.get("modele"))
            relu_secteur = getattr(relu, "secteur_hz", None) if relu is not None else raison_relu
            chk(server.secteur_hz == 60.0 and res.get("secteur_hz") == 60.0
                and relu_secteur == 60.0,
                f"[smoke-secteur] l'entraînement joué par un moteur réglé à 60 Hz produit un "
                f"modèle à 60 Hz — résultat {res.get('secteur_hz')!r}, fichier relu "
                f"{relu_secteur!r} ; 50 dirait que le secteur du poste n'atteint pas le modèle")

            # 2. Aucun des QUATRE catalogues ne découvre le candidat. Sinon un candidat
            #    orphelin (nettoyage sauté, dossier rouvert) redeviendrait « le modèle chargeable
            #    le plus récent ».
            chk(server._candidats_visibles() == [],
                f"aucun des quatre catalogues ne découvre quoi que ce soit dans le dossier "
                f"candidat ({server._candidats_visibles()})")
            from core import cvep_models, errp_models, p300_models

            motifs = ((mi_models.MOTIF, p300_models.MOTIF, errp_models.MOTIF)
                      + tuple(cvep_models.MOTIFS))
            fuit = [m for m in motifs
                    if not fnmatch(os.path.basename(res.get("modele", "")), m)]
            decouvre = [m for m in motifs if fnmatch(nom_retenu(res.get("modele", "")), m)]
            chk(len(fuit) == len(motifs) and len(decouvre) == 1,
                f"le NOM d'un candidat échappe aux {len(motifs)} motifs de découverte, et le nom "
                f"RETENU en retrouve exactement un ({len(fuit)}/{len(motifs)} fuis, "
                f"{decouvre} retrouvé)")

            # 3. `save_calibration` DÉPLACE — et n'écrase jamais. On plante d'abord un fichier
            #    au nom exact que le candidat va réclamer : la panne à fermer est un `move` qui
            #    passe par-dessus un enregistrement existant, et `data/` ne se refait pas.
            occupe = os.path.join(data_dir, nom_retenu(res["modele"]))
            with open(occupe, "wb") as f:
                f.write(b"un modele qui existait deja")
            source = res["modele"]
            npz_source = res.get("enregistrement")
            # 🔴 Le magasin du mode tient DÉJÀ un modèle, l'ancien — l'état de toute séance où
            # l'on RÉentraîne. « Enregistrer » doit y poser le nouveau, sinon « Tester » testerait
            # l'ANCIEN modèle, en silence (deux noms qui ne diffèrent que par l'horodatage). La
            # découverte des modèles est pointée sur le `data/` DÉTOURNÉ le temps
            # de cette étape : c'est là que le moteur enregistre, donc là que le choix doit exister.
            ancien_magasin = dict(registry.get("mi").defaults(), model=occupe)
            server.reglages["mi"] = dict(ancien_magasin)
            vrai_catalogue_mi = mi_models.modeles_disponibles
            mi_models.modeles_disponibles = lambda d=data_dir: vrai_catalogue_mi(d)
            ack_save = server.submit("save_calibration")
            chk(ack_save.get("accepted"), f"« Enregistrer » est accepté ({ack_save})")
            t0 = time.perf_counter()
            while server.candidat is not None and time.perf_counter() - t0 < 5.0:
                time.sleep(0.05)
            retenu = (server.snapshot().get("calibration") or {}).get("resultat") or {}
            mi_models.modeles_disponibles = vrai_catalogue_mi
            magasin_mi = (server.snapshot().get("reglages") or {}).get("mi") or {}
            chk(bool(retenu.get("modele")) and magasin_mi.get("model") == retenu.get("modele"),
                f"🔴 « Enregistrer » pose le modèle ENREGISTRÉ comme réglage « model » du mode "
                f"dans le magasin — c'est lui que « Tester » relit ; l'ancien "
                f"({os.path.basename(occupe)}) n'y reste pas "
                f"({os.path.basename(str(magasin_mi.get('model')))})")
            chk(all(magasin_mi.get(k) == v for k, v in ancien_magasin.items() if k != "model"),
                "…et seul « model » change : les autres réglages retenus du mode restent les siens")
            chk(server.candidat is None,
                "…et après application, plus aucun candidat n'attend de décision")
            chk(not os.path.exists(source) and (not npz_source or not os.path.exists(npz_source)),
                f"le candidat a été DÉPLACÉ, pas copié : l'original n'existe plus "
                f"({os.path.basename(source)})")
            chk(bool(retenu.get("modele")) and os.path.dirname(retenu["modele"]) == data_dir
                and os.path.isfile(retenu["modele"]),
                f"…et il est maintenant dans data/ ({retenu.get('modele')})")
            with open(occupe, "rb") as f:
                intact = f.read() == b"un modele qui existait deja"
            chk(intact and retenu.get("modele") != occupe,
                f"…sans avoir écrasé le fichier qui portait déjà ce nom "
                f"({os.path.basename(retenu.get('modele') or '')} à côté de "
                f"{os.path.basename(occupe)})")
            chk(bool(retenu.get("verdict")) and retenu.get("cv_groupee") == res.get("cv_groupee"),
                f"…et le VERDICT reste lisible à l'écran après l'enregistrement "
                f"({retenu.get('verdict')})")
            refus_save = server.submit("save_calibration")
            chk(not refus_save.get("accepted")
                and "aucun entraînement" in (refus_save.get("reason") or ""),
                f"un second « Enregistrer » est refusé, avec un motif ({refus_save})")

            # 3ter. TOUS les fichiers d'un candidat sont déplacés, pas seulement le premier.
            # ⚠️ Le c-VEP est le seul mode à produire DEUX modèles par séance (eCCA et rCCA, sur
            # les mêmes époques) : sa clé `modele_rcca` doit figurer dans `_FICHIERS_CANDIDAT`. Une
            # clé oubliée là ne lève RIEN — le fichier reste dans le dossier temporaire, que la
            # fermeture du moteur efface, et l'étudiant perd la moitié d'une calibration en
            # croyant l'avoir enregistrée. La calibration jouée ci-dessus est celle du MI, qui n'a
            # qu'un modèle : on fabrique donc un candidat à trois fichiers pour exercer la boucle.
            # ⚠️ Les clés sont écrites EN DUR ici, surtout pas relues sur `_FICHIERS_CANDIDAT` :
            # une fixture construite depuis la constante qu'elle vérifie ne peut rien prouver —
            # retirer une clé retirerait le fichier de la fixture du même geste, et le test
            # resterait vert. Cette liste-ci est celle des clés de chemin que les
            # calibrations rendent vraiment : `modele` + `enregistrement` (MI, P300, ErrP) et
            # `modele_rcca` en plus pour le c-VEP (`core/modes/cvep_calib.py::entrainer`).
            cles_de_chemin = ("modele", "modele_rcca", "enregistrement")
            manquantes = [c for c in cles_de_chemin
                          if c not in EngineServer._FICHIERS_CANDIDAT]
            chk(not manquantes,
                f"toutes les clés de chemin que les calibrations produisent sont connues de "
                f"`_FICHIERS_CANDIDAT` ({manquantes or 'aucune manquante'})")
            faux = {}
            for cle in cles_de_chemin:
                chemin = os.path.join(server.calib_dir, f"{CALIB_CANDIDAT_PREFIXE}faux_{cle}.npz")
                with open(chemin, "wb") as f:
                    f.write(cle.encode())
                faux[cle] = chemin
            server.candidat = dict(faux, nom=os.path.basename(faux["modele"]))
            server._save_calibration()
            restes = [c for c in faux.values() if os.path.exists(c)]
            arrives = [n for n in os.listdir(data_dir) if n.startswith("faux_")]
            chk(not restes and len(arrives) == len(faux),
                f"les {len(faux)} fichiers d'un candidat rejoignent TOUS data/, pas seulement le "
                f"premier — une clé absente de `_FICHIERS_CANDIDAT` laisserait son fichier dans le "
                f"temporaire, effacé à la fermeture, sans un mot ({len(arrives)} arrivé(s), "
                f"{len(restes)} resté(s))")
            for n in arrives:
                os.remove(os.path.join(data_dir, n))

            # 3bis. Une séance terminée est LÂCHÉE quand la suivante commence. Elle garde sinon
            # ses époques (plusieurs minutes de signal) et une référence vers le moteur entier :
            # seul `cancel()` les libère, et `_terminer` ne l'appelle pas. Sans ce lâcher
            # explicite, chaque séance de la journée resterait vivante derrière la suivante.
            # La nouvelle est abandonnée aussitôt : ce qu'on éprouve ici est le passage de
            # relais, pas une seconde séance.
            ancienne = server.calibration
            server.submit("start_calibration", id="mi", params={})
            t0 = time.perf_counter()
            while server.calibration is ancienne and time.perf_counter() - t0 < 5.0:
                time.sleep(0.05)
            chk(ancienne is not None and ancienne.engine is None and ancienne._enregistre == [],
                f"la séance précédente est LÂCHÉE quand la suivante commence : époques et "
                f"référence au moteur libérées "
                f"({None if ancienne is None else len(ancienne._enregistre)} époque(s) retenue(s))")
            server.submit("cancel_calibration")
            t0 = time.perf_counter()
            while server.phase == "calibrating" and time.perf_counter() - t0 < 5.0:
                time.sleep(0.05)

            produits = mi_models.modeles_disponibles(data_dir)
            chk(produits == [retenu.get("modele")],
                f"le modèle RETENU, lui, est chargeable et listé — c'est le motif "
                f"`{mi_models.MOTIF}` qui le veut ({[os.path.basename(p) for p in produits]})")
            # Que la CV honnête soit RAPPORTÉE est un fait déterministe : c'est une assertion.
            # Que cv_groupee < cv_naive n'en est pas une : ce test entraîne sur le bruit RÉEL du
            # board synthétique, donc sans aucun signal appris l'ORDRE des deux CV est un tirage
            # (~1 échec sur 6 même à 18 essais/classe). Conclure sur du bruit est ce que ce projet
            # interdit (rigueur statistique). L'invariant est vérifié là où il a un
            # sens : sur de l'ERD FABRIQUÉE, par `mi_calib._selftest()` et
            # `mi_decoder._test_cv_honnete()`. On imprime les deux chiffres sans en juger l'ordre.
            chk(res.get("cv_groupee") is not None,
                f"l'accuracy HONNÊTE (validation croisée par essai) est rapportée "
                f"({res.get('cv_groupee')})")
            print(f"[smoke-calib] pour mémoire, PAS une assertion (cf. commentaire ci-dessus) : "
                  f"cv_groupee={res.get('cv_groupee')} cv_naive={res.get('cv_naive')}")

            # Et le mode MI peut alors démarrer sur ce modèle : c'est tout l'objet du chantier.
            #
            # Le Param « model » de `mi.SPEC` résout ses choix via
            # `mi_models.modeles_disponibles()` SANS argument, donc contre le VRAI `data/` — jamais
            # le dossier temporaire de ce test. Sans redirection, `start_mode` refuserait TOUJOURS
            # avec « aucun choix disponible », même juste après l'entraînement : ne jamais toucher
            # `data/` et démarrer le mode sur le modèle produit exigent ce monkeypatch, le même que
            # `core/modes/mi.py::_selftest`.
            # `contract.validate` (donc `choices_fn`) tourne DANS `submit`, sur CE fil, de façon
            # SYNCHRONE : la redirection n'a besoin de vivre que le temps de cet appel — la suite
            # (`MIRuntime.__init__`) charge le modèle par CHEMIN direct (`mi_models.charger`), qui
            # ne consulte jamais `modeles_disponibles`.
            vrai_disponibles = mi_models.modeles_disponibles
            mi_models.modeles_disponibles = lambda d=data_dir: vrai_disponibles(d)
            try:
                # `if produits else ...` : pour rendre le diagnostic ligne à ligne jusqu'au bout
                # (cf. le commentaire sur `calib`) plutôt qu'une trace Python brute sur un
                # `IndexError` si `produits` est vide ici.
                demarrage = (server.submit("start_mode", id="mi",
                                           params={"mi": {"model": produits[0]}})
                            if produits else
                            {"accepted": False, "reason": "aucun modèle produit (diagnostic plus haut)"})
            finally:
                mi_models.modeles_disponibles = vrai_disponibles
            chk(demarrage.get("accepted"),
                f"le mode MI démarre sur le modèle qui vient d'être entraîné ({demarrage})")

            # 4. « Jeter » : le fichier disparaît, et l'écran de verdict avec lui.
            #    Le candidat est REFABRIQUÉ à partir du modèle réellement produit (on le recopie
            #    dans le dossier candidat) : refaire une seconde séance complète coûterait 30 s
            #    de plus pour éprouver quatre lignes de suppression.
            refait = os.path.join(server.calib_dir, os.path.basename(source))
            shutil.copy2(retenu["modele"], refait)
            server.candidat = {"modele": refait, "nom": os.path.basename(refait)}
            avant_data = sorted(os.listdir(data_dir))
            # Une suppression LENTE, exprès : sous Windows, un fichier fraîchement copié peut
            # être scanné, et `os.remove` attendre. Le moteur ne doit dire « plus de candidat »
            # qu'une fois le disque propre ; sans ce ralenti, un ordre fautif ne se verrait qu'une
            # fois sur deux.
            vrai_remove = os.remove

            def _remove_lent(chemin, *a, **k):
                time.sleep(0.3)
                return vrai_remove(chemin, *a, **k)
            os.remove = _remove_lent
            try:
                ack_jeter = server.submit("discard_calibration")
                chk(ack_jeter.get("accepted"), f"« Jeter » est accepté ({ack_jeter})")
                t0 = time.perf_counter()
                while server.candidat is not None and time.perf_counter() - t0 < 5.0:
                    time.sleep(0.05)
            finally:
                os.remove = vrai_remove
            chk(not os.path.exists(refait) and server.candidat is None,
                f"…et le candidat est SUPPRIMÉ du disque ({refait})")
            chk(sorted(os.listdir(data_dir)) == avant_data,
                f"…sans toucher à data/, qui n'a rien à voir avec ce refus "
                f"({sorted(os.listdir(data_dir))})")
            chk(server.snapshot().get("calibration") is None,
                f"…et l'écran de verdict est effacé : il n'y a plus rien à décider "
                f"({server.snapshot().get('calibration')})")
            refus_jeter = server.submit("discard_calibration")
            chk(not refus_jeter.get("accepted")
                and "aucun entraînement" in (refus_jeter.get("reason") or ""),
                f"un second « Jeter » est refusé, avec un motif ({refus_jeter})")

            # 5. Le moteur s'arrête SANS qu'on ait tranché : aucun candidat ne survit.
            #    C'est le cas de la console fermée entre l'entraînement et la décision, et il ne
            #    doit dépendre d'AUCUN geste de l'utilisateur — d'où le `finally` de `run()`.
            orphelin = os.path.join(server.calib_dir, os.path.basename(source))
            shutil.copy2(retenu["modele"], orphelin)
            server.candidat = {"modele": orphelin, "nom": os.path.basename(orphelin)}
            calib_dir = server.calib_dir
        finally:
            server.stop()
            thread.join(timeout=10.0)
        chk(server.candidat is None and not os.path.exists(orphelin)
            and not os.path.isdir(calib_dir),
            f"arrêter le moteur SANS trancher ne laisse aucun candidat orphelin : le dossier "
            f"entier est balayé par le `finally` de run() ({calib_dir})")
        chk(sorted(os.listdir(data_dir)) == avant_data,
            f"…et le candidat jamais tranché n'a PAS été enregistré au passage "
            f"({sorted(os.listdir(data_dir))})")
    finally:
        for cle, valeur in anciens.items():
            setattr(mi_calib.MICalibration, cle, valeur)
        shutil.rmtree(data_dir, ignore_errors=True)

    # ⚠️ L'instrument de preuve, et ce n'est PAS `git status` : `data/` est gitignoré, donc
    # `git status --short data/` rend une sortie vide même quand un modèle vient d'y être écrit.
    chk(empreinte_dossier() == empreinte_avant,
        "AUCUN fichier n'a bougé dans le VRAI `data/` — enregistrements EEG d'une personne "
        "identifiable sur un dépôt public, et son fichier le plus récent est celui que le moteur "
        "propose à la prochaine séance casque")

    print(f"[smoke-calib] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_calibration_refus():
    """Les quatre refus de `start_calibration`/`cancel_calibration`, et l'annulation de bout en
    bout — ce sont les quatre premiers messages qu'un étudiant voit s'il se trompe de mode ou
    clique « Entraîner » sans y penser.

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
    chk(not r2.get("accepted") and "rien à entraîner" in (r2.get("reason") or ""),
        f"mode SANS calibration (SSVEP, la CCA n'apprend rien) : refusé ({r2.get('reason')})")

    # Ce contrôle porte sur un mode FABRIQUÉ : plus aucun mode réel n'a une calibration déclarée
    # sans `runtime_cls`. Il protège le prochain mode déclaré avant d'être jouable, qui
    # repartirait sinon sur un `None(spec, …)` incompréhensible au lieu d'une phrase. On injecte
    # donc un mode le temps du contrôle, et on restaure le registre juste après.
    from dataclasses import replace as _replace

    faux = _replace(registry.get("cvep"), id="__pas_livre__", label="Mode pas livré",
                    calibration=_replace(registry.get("cvep").calibration, runtime_cls=None))
    registry.BY_ID[faux.id] = faux
    try:
        r3 = froid.submit("start_calibration", id=faux.id)
    finally:
        registry.BY_ID.pop(faux.id, None)
    chk(not r3.get("accepted") and "pas livré" in (r3.get("reason") or ""),
        f"calibration DÉCLARÉE mais sans runtime : refusée, en disant que le moteur ne sait pas "
        f"encore la jouer ({r3.get('reason')})")
    # …et le pendant, vérifié SANS rien soumettre : soumettre un `start_calibration` accepté à ce
    # moteur froid créerait son dossier candidat et laisserait une commande en file, ce que deux
    # contrôles plus bas mesurent justement.
    chk(all(s.calibration is None or s.calibration.runtime_cls is not None
            for s in registry.MODES),
        f"…et plus AUCUN mode réel n'est dans ce cas : les six calibrations déclarées sont "
        f"jouables par le moteur ("
        f"{[s.id for s in registry.MODES if s.calibration and s.calibration.runtime_cls is None]})")

    r4 = froid.submit("cancel_calibration")
    chk(not r4.get("accepted") and "aucun entraînement" in (r4.get("reason") or ""),
        f"annuler sans calibration en cours : refusé ({r4.get('reason')})")

    # 4bis. « Enregistrer » et « Jeter » sans candidat. Ce sont les deux boutons que la console
    # affichera sur l'écran de verdict : cliqués hors de ce moment-là (ou deux fois de suite),
    # ils doivent refuser AVEC un motif, jamais tomber sur un chemin qui n'existe plus.
    for commande, mot in (("save_calibration", "enregistrer"), ("discard_calibration", "jeter")):
        r = froid.submit(commande)
        chk(not r.get("accepted") and mot in (r.get("reason") or "")
            and "aucun entraînement" in (r.get("reason") or ""),
            f"« {commande} » sans candidat : refusé, en disant ce qui manque ({r.get('reason')})")

    # 4ter. La validation AU CLIC. La console demande au moteur, AVANT le contrôle de liaison et
    # avant d'arrêter le décodage, si l'entraînement serait accepté. Sans elle, une coupure
    # haute à 50 Hz sur le MI (maximum 40) ne serait refusée qu'au `start_calibration` — le flux
    # de l'application de l'étudiant déjà coupé pour rien.
    v_ok, r_ok = froid.valider_calibration("mi", {})
    chk(v_ok is not None and r_ok is None and {"band_low", "band_high"} <= set(v_ok),
        f"un entraînement valide est validé, réglages COMPLETS rendus ({r_ok or sorted(v_ok)})")
    v_ko, r_ko = froid.valider_calibration("mi", {"band_high": 50.0})
    s_ko = froid.submit("start_calibration", id="mi", params={"band_high": 50.0})
    chk(v_ko is None and r_ko and "maximum" in r_ko and r_ko == s_ko.get("reason"),
        f"une coupure haute à 50 Hz sur le MI est refusée AU CLIC, avec la raison exacte que "
        f"`start_calibration` donnerait ({r_ko})")
    chk(froid.valider_calibration("bogus", {})[1] == r1.get("reason")
        and froid.valider_calibration("ssvep", {})[1] == r2.get("reason"),
        "…et les refus de mode (inconnu, sans calibration) sont les mêmes que ceux de `submit`")
    chk(froid._commands.empty() and froid.calibration is None,
        "…et valider ne met RIEN en file, ne construit RIEN : c'est une question, pas un geste")
    chk(froid.calib_dir is None,
        f"…et un moteur qui n'a jamais calibré n'a créé AUCUN dossier temporaire "
        f"({froid.calib_dir})")

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
    # calibration <-> moteur (cf. son long commentaire) : on vérifie qu'il s'exécute vraiment sur
    # ce chemin et pas seulement sur le chemin `cancel_calibration` testé au-dessus.
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


def _smoke_oreille_calibration():
    """Une calibration à FENÊTRE, seule, fait-elle ouvrir l'oreille du moteur ?

    ⚠️ Les quatre décisions « faut-il une oreille, sous quel nom, quand la lâcher, jusqu'où
    purger » ne doivent pas se prendre sur `self.active` SEUL. Une calibration ne vit pas dans
    `self.active` (invariant de `modes/calibration.py`) et la console ARRÊTE le mode avant de
    démarrer sa calibration (cf. `_smoke_vol_marqueurs`). Sur le parcours NORMAL du produit,
    si plus personne n'écoutait, la fenêtre publierait ses marqueurs dans le vide, et le moteur
    abandonnerait au bout de `CALIB_FENETRE_ATTENTE_S` en annonçant « la fenêtre ne s'est pas
    lancée, ou elle publie sous un autre nom » : deux causes fausses.

    Les autotests des quatre calibrations passent par un moteur factice dont `markers_murs` rend
    une file DÉJÀ REMPLIE, donc ils n'exercent que le chemin où les marqueurs sont là : ce test
    couvre le chemin manquant.

    Aucun casque, aucune boucle, aucun émetteur : on interroge les prédicats eux-mêmes.
    """
    import shutil
    import tempfile

    from core.modes.p300 import SPEC as SPEC_P300
    from core.modes.p300_calib import P300Calibration

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    dossier = tempfile.mkdtemp(prefix="smoke_oreille_")
    srv = EngineServer(synthetic=True, modes=(), instance="smoke-oreille")
    try:
        chk(not list(srv._ecouteurs_de_marqueurs()),
            "moteur vierge : personne n'écoute de marqueurs")
        srv._ouvre_marker_inlet()
        chk(srv.marker_inlet is None,
            "…donc aucun inlet n'est ouvert — chercher sur le réseau pour personne coûterait un "
            "tour de boucle à chaque tour")

        # LE cas du parcours normal : une calibration à fenêtre, et AUCUN mode actif.
        srv.calibration = P300Calibration(SPEC_P300, {}, srv, dossier=dossier)
        ecouteurs = list(srv._ecouteurs_de_marqueurs())
        chk(ecouteurs == [srv.calibration],
            f"une calibration à fenêtre écoute les marqueurs, MÊME sans aucun mode actif — c'est "
            f"le cas normal, la console ayant dû arrêter le mode pour la démarrer "
            f"({[type(e).__name__ for e in ecouteurs]})")
        srv._ouvre_marker_inlet()
        chk(srv.marker_inlet is not None,
            "…et le moteur ouvre son oreille pour elle. Sans ça la fenêtre publie dans le vide "
            "pendant toute la séance, et l'abandon accuse une fenêtre qui marche")
        chk(srv._nom_flux_marqueurs() == srv._flux_attendu(srv.calibration),
            f"le nom résolu est celui que la calibration attend ({srv._nom_flux_marqueurs()})")

        # Le nom vient du MODE, pas de la constante globale : une calibration porte les `params`
        # de la CALIBRATION, qui n'ont pas de `stream_in`.
        defaut_du_mode = (SPEC_P300.defaults() or {}).get("stream_in")
        chk(defaut_du_mode and srv._flux_attendu(srv.calibration) == defaut_du_mode,
            f"…et il vient du défaut DÉCLARÉ PAR LE MODE ({defaut_du_mode!r}), pas de la "
            f"constante globale — sinon `stream_in` serait un réglage-décor pour la calibration")

        # Une calibration TERMINÉE cesse d'écouter, et l'oreille se lâche.
        srv.calibration.phase = "fini"
        chk(not list(srv._ecouteurs_de_marqueurs()),
            "une calibration TERMINÉE n'écoute plus rien")
        chk(srv._libere_marker_inlet("smoke") and srv.marker_inlet is None,
            "…et l'inlet est lâché : le garder ouvert empêcherait sa re-résolution et ferait "
            "grossir la file sans personne pour la consommer")
    finally:
        srv.calibration = None
        srv.close()
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[smoke-oreille-calib] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_secteur():
    """Le SECTEUR du poste : ce que le moteur coupe, et ce qu'il refuse.

    Un secteur mal transmis ne casse RIEN : le bourdonnement reste dans le signal, un peu plus de
    σ au bandeau, un modèle qui apprend avec un coupe-bande à côté du secteur. Aucune exception,
    aucun chiffre aberrant — d'où des assertions sur le FILTRE lui-même, pas sur un score.

    L'ENTRAÎNEMENT à 60 Hz est vérifié dans `[smoke-calib]`, qui joue une vraie calibration MI
    par la boucle d'un moteur construit à 60 Hz — la rejouer ici coûterait 30 s pour la même
    preuve. La RÉOUVERTURE du casque, dans `[smoke-liaison]`, sur le vrai chemin de reconnexion.
    """
    from brainflow.data_filter import NoiseTypes

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    chk(set(NOTCH_SECTEUR) == set(SECTEURS_HZ),
        f"la table des coupe-bandes BrainFlow couvre exactement les secteurs du poste "
        f"({sorted(NOTCH_SECTEUR)} pour {list(SECTEURS_HZ)}) : un secteur ajouté à `config` sans "
        f"son coupe-bande serait accepté puis coupé par personne")
    defaut = EngineServer(synthetic=True, instance="smoke-secteur-50")
    chk(defaut.secteur_hz == SECTEUR_HZ == 50.0 and defaut.acq.notch is NoiseTypes.FIFTY,
        f"sans réglage, le moteur coupe le secteur par défaut du dépôt : 50 Hz ({defaut.secteur_hz}, "
        f"{defaut.acq.notch.name})")
    srv = EngineServer(synthetic=True, instance="smoke-secteur", secteur_hz=60)
    chk(srv.secteur_hz == 60.0 and isinstance(srv.secteur_hz, float)
        and srv.acq.notch is NoiseTypes.SIXTY,
        f"un moteur réglé à 60 Hz le porte (en float, comme `SECTEURS_HZ`) et son acquisition "
        f"coupe 60 Hz ({srv.secteur_hz!r}, {srv.acq.notch.name})")
    etat = srv.snapshot()
    chk(etat.get("secteur_hz") == 60.0,
        f"…et `snapshot()` le dit, pour un afficheur qui ne lit que l'état "
        f"({etat.get('secteur_hz')!r})")

    # Le FILTRE, pas l'étiquette : 20 µV de secteur à 60 Hz, filtrés par l'acquisition de chacun
    # des deux moteurs. Mesuré au milieu du bloc, loin des bords où le filtre s'établit : ~0 µV
    # rms à 60 Hz, ~1,2 µV à 50 (le passe-bande 5-40 Hz n'en retire qu'une partie).
    fs = srv.acq.fs
    temps = np.arange(int(10 * fs)) / fs
    bourdon = np.stack([20.0 * np.sin(2 * np.pi * 60.0 * temps)] * 4, axis=1)
    milieu = slice(len(temps) // 4, 3 * len(temps) // 4)

    def residu(acq):
        return float(np.sqrt(np.mean(acq._filter(bourdon)[milieu] ** 2)))

    reste_60, reste_50 = residu(srv.acq), residu(defaut.acq)
    chk(reste_60 < 0.05 and reste_50 > 0.5,
        f"le filtre d'acquisition du moteur à 60 Hz retire un secteur à 60 Hz ({reste_60:.3f} µV "
        f"rms restants pour 14,1), celui du moteur à 50 Hz le laisse ({reste_50:.2f} µV) — ce "
        f"filtre fait le σ du bandeau, le contrôle de liaison et le SSVEP")

    for mauvais in (55, "60 Hz", None):
        try:
            EngineServer(synthetic=True, instance="smoke-secteur-refus", secteur_hz=mauvais)
            chk(False, f"un secteur à {mauvais!r} doit être REFUSÉ")
        except Exception as refus:  # noqa: BLE001 - un KeyError plus loin est aussi un échec à dire
            chk(isinstance(refus, ValueError) and str(mauvais) in str(refus)
                and all(f"{s:g}" in str(refus) for s in SECTEURS_HZ),
                f"un secteur à {mauvais!r} est refusé à la construction, en disant lesquels "
                f"existent ({type(refus).__name__} : {refus})")
    chk(_parse_args([]).secteur == int(SECTEUR_HZ) and _parse_args(["--secteur", "60"]).secteur == 60,
        "le moteur seul prend `--secteur`, 50 par défaut")
    import contextlib
    import io
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            _parse_args(["--secteur", "55"])
            refuse = False
        except SystemExit:
            refuse = True
    chk(refuse, "…et `--secteur 55` est refusé dès la ligne de commande")
    srv.close()
    defaut.close()
    # Détruits MAINTENANT, pendant qu'aucune session n'est ouverte : `BoardShim.__del__` libère la
    # session du board de test que BrainFlow PARTAGE entre boards aux mêmes paramètres — celle du
    # moteur d'un autre test, si le ramasse-miettes passait plus tard (cf. `[smoke-liaison]`).
    del srv, defaut
    import gc
    gc.collect()
    print(f"[smoke-secteur] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_casque():
    """L'état du casque : paquets perdus comptés sur le compteur, batterie non inventée.

    Le compteur du casque monte de 1 à chaque échantillon (mesuré) ; un saut = des
    échantillons perdus en route. Deux pièges : un compteur qui REPART (réouverture, bouclage du
    board de test à 255) n'est pas une perte ; et un saut à la JOINTURE de deux blocs en est une.
    """
    from core.acquisition import compter_paquets

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    chk(compter_paquets([1, 2, 3, 4], None) == (4, 0, 4), "un compteur continu : aucune perte")
    chk(compter_paquets([1, 2, 5, 6], None) == (4, 2, 6),
        "un saut de 2 à 5 : DEUX échantillons perdus (3 et 4)")
    chk(compter_paquets([9, 10], 6) == (2, 2, 10),
        "…et un saut à la JOINTURE de deux blocs en est un aussi (6 puis 9 : 7 et 8 perdus)")
    from core.config import barres_liaison
    chk([barres_liaison(p) for p in (0.0, 0.1, 0.5, 1.0, 3.0, 5.0, 12.0)] == [4, 4, 3, 3, 2, 2, 1]
        and barres_liaison(None) is None and barres_liaison(0.0, perdue=True) == 0,
        "les barres de liaison : 4 sans perte, 3 jusqu'au seuil d'alerte, 2, puis 1 ; 0 quand "
        "la liaison est perdue ; rien tant qu'on ne sait pas")
    # La RÉOUVERTURE libère l'ancienne session même quand l'arrêt du flux lève — le cas d'une
    # liaison morte. Si la libération saute, BrainFlow refuse toute réouverture
    # (`ANOTHER_BOARD_IS_CREATED_ERROR:16`). Un faux board rejoue exactement ce cas.
    from core.acquisition import UnicornAcquisition

    class _BoardMort:
        def __init__(self):
            self.gestes = []

        def is_prepared(self):
            return True

        def stop_stream(self):
            self.gestes.append("stop_stream")
            raise RuntimeError("UNICORN_StopAcquisition : liaison morte")

        def release_session(self):
            self.gestes.append("release_session")

        def prepare_session(self):
            self.gestes.append("prepare_session")

        def start_stream(self):
            self.gestes.append("start_stream")

    acq = UnicornAcquisition(synthetic=True)
    acq.board = _BoardMort()
    acq.reouvrir()
    chk(acq.board.gestes == ["stop_stream", "release_session", "prepare_session", "start_stream"],
        f"une liaison morte dont l'arrêt de flux LÈVE est quand même LIBÉRÉE avant d'être "
        f"rouverte ({acq.board.gestes})")
    import collections as _collections
    import types as _types
    coupe = _types.SimpleNamespace(synthetic=False, _paquets=_collections.deque(),
                                   _liaison="perdue",
                                   acq=_types.SimpleNamespace(batterie=0.0, paquets_perdus=0))
    etat_coupe = EngineServer._etat_casque(coupe)
    chk(etat_coupe["batterie_pc"] is None and etat_coupe["signal_barres"] == 0,
        f"liaison coupée : batterie INCONNUE (pas la dernière lue, figée à 0 %), et 0 barre "
        f"({etat_coupe})")
    chk(compter_paquets([254, 255, 0, 1], None) == (4, 0, 1)
        and compter_paquets([1, 2], 2490) == (2, 0, 2),
        "un compteur qui REPART (bouclage du board de test, réouverture du casque) n'est PAS "
        "une perte")

    srv = EngineServer(synthetic=True, instance="smoke-casque", modes=("raw",))
    try:
        import threading
        fil = threading.Thread(target=srv.run, kwargs={"duration_s": 4.0}, daemon=True)
        fil.start()
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 3.0 and fil.is_alive():
            time.sleep(0.1)
        casque = srv.snapshot().get("casque") or {}
        chk(casque.get("batterie_pc") is None and casque.get("signal_barres") is None,
            f"le board de test n'a NI batterie NI barres de liaison à l'écran : sa batterie est "
            f"tirée au hasard, et il n'a pas de liaison radio ({casque})")
        chk(srv.acq.paquets_recus > 0 and srv.acq.paquets_perdus == 0,
            f"…et son compteur, qui boucle à 255, ne fabrique AUCUNE fausse perte "
            f"({srv.acq.paquets_recus} reçus, {srv.acq.paquets_perdus} perdus)")
        srv.stop()
        fil.join(timeout=5.0)
    finally:
        srv.close()
    print(f"[smoke-casque] VERDICT : {'OK' if ok else 'ÉCHEC'}")
    return ok


def _smoke_liaison():
    """Un casque qui DÉCROCHE : détecté, rien n'est décodé pendant la coupure, et il revient.

    Sans surveillance, une déconnexion d'une seconde figerait tout jusqu'à relancer la console.
    BrainFlow ne lève rien — les échantillons cessent d'arriver —, donc ce test coupe
    les échantillons d'un VRAI moteur (board de test) et fait échouer la réouverture tant qu'il
    ne l'a pas décidé : c'est la seule façon de voir la coupure DURER, et de vérifier ce que le
    moteur fait pendant.
    """
    import threading

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    freqs = [c["actual_hz"] for c in choose_frequencies(60.0)]
    # À 60 Hz (`[smoke-secteur]`) : le casque ROUVERT doit garder le coupe-bande du poste, pas
    # retomber sur celui par défaut de `UnicornAcquisition` (50 Hz).
    srv = EngineServer(synthetic=True, instance="smoke-liaison", modes=("raw", "ssvep"),
                       params={"ssvep": {"freqs": freqs}}, secteur_hz=60.0)
    acq_avant = srv.acq
    srv.decrochage_s = 0.5
    srv.reessai_s = 0.3
    coupe, retour, essais, leve = {"on": False}, {"ok": False}, [], {"on": False}
    lire, rouvrir = srv.acq.get_new_data, srv.acq.reouvrir

    lectures_coupees = {"n": 0}

    def lire_coupe():
        if srv._liaison == "perdue":
            lectures_coupees["n"] += 1
        if leve["on"]:
            # Une session morte en pleine séance : BrainFlow LÈVE au lieu de rendre un bloc vide.
            raise RuntimeError("BOARD_NOT_CREATED_ERROR:15 (simulé)")
        donnees = lire()                      # on VIDE quand même le tampon de BrainFlow
        return (None, None) if coupe["on"] else donnees

    def rouvrir_si_permis():
        essais.append(time.perf_counter())
        if not retour["ok"]:
            # FIDÈLE au vrai `reouvrir` sur un casque éteint : il LIBÈRE d'abord la session
            # (`stop()`), PUIS l'ouverture échoue. La session n'est alors plus lisible, et
            # BrainFlow LÈVE (`BOARD_NOT_CREATED_ERROR:15`) sur une session libérée : un faux qui
            # lèverait sans rien libérer ne verrait pas le tour qui suit la première réouverture
            # ratée, celui où une batterie à plat tue un moteur mal protégé.
            srv.acq.stop()
            raise RuntimeError("UNABLE_TO_OPEN_PORT_ERROR (simulé)")
        coupe["on"] = False
        return rouvrir()

    srv.acq.get_new_data = lire_coupe
    srv.acq.reouvrir = rouvrir_si_permis
    tours = {"n": 0}
    vider = srv._drain_commands

    def vider_compte():
        tours["n"] += 1
        return vider()

    srv._drain_commands = vider_compte
    fil = threading.Thread(target=srv.run,
                           kwargs={"duration_s": 25.0, "baseline_s": 1.0, "warmup_s": 0.5},
                           daemon=True)
    ssvep = None
    fil.start()
    try:
        t0 = time.perf_counter()
        while srv.phase != "decoding" and time.perf_counter() - t0 < 10.0 and fil.is_alive():
            time.sleep(0.05)
        ssvep = srv.active.get("ssvep")
        decisions = {"n": 0}
        if ssvep is not None:
            tick = ssvep.tick

            def tick_compte(*a, **k):
                decisions["n"] += 1
                return tick(*a, **k)

            ssvep.tick = tick_compte
        chk(srv.snapshot()["liaison"]["etat"] == "ok" and ssvep is not None,
            f"au départ la liaison est « ok » ({srv.snapshot()['liaison']})")
        # Le CONTACT de chaque électrode : un verdict par voie, tiré du σ et du seuil publiés.
        t0 = time.perf_counter()
        while srv.snapshot().get("quality") is None and time.perf_counter() - t0 < 5.0:
            time.sleep(0.05)
        qualite = srv.snapshot().get("quality") or {}
        attendus = [None if s is None else 0.5 <= s <= qualite.get("seuil_contact", -1)
                    for s in qualite.get("sigmas", [])]
        chk(len(qualite.get("contact", [])) == 8 and qualite.get("contact") == attendus
            and qualite.get("seuil_contact") == CONTACT_SIGMA_MAX
            and qualite.get("reference_ok") is None,
            f"un verdict de contact par électrode, tiré de son σ et du seuil publié ; la référence "
            f"sans verdict sur le board de test ({qualite.get('contact')}, "
            f"{qualite.get('sigmas')}, référence {qualite.get('reference_ok')})")
        chk(contact_bon(0.1) is False and contact_bon(12.0) is True
            and contact_bon(CONTACT_SIGMA_MAX + 1) is False and contact_bon(None) is None
            and contact_bon(float("nan")) is None,
            "une voie plate ou trop bruitée a un MAUVAIS contact, une voie sans mesure n'en a "
            "aucun")
        # Un test en cours au moment de la coupure : il doit être ANNULÉ, avec sa raison.
        srv.submit("start_mesure", id="alpha")
        t0 = time.perf_counter()
        while srv.snapshot().get("mesure") is None and time.perf_counter() - t0 < 3.0:
            time.sleep(0.05)

        coupe["on"] = True
        t0 = time.perf_counter()
        while (srv.snapshot()["liaison"]["etat"] != "perdue" and time.perf_counter() - t0 < 3.0
               and fil.is_alive()):
            time.sleep(0.05)
        liaison = srv.snapshot()["liaison"]
        chk(liaison["etat"] == "perdue",
            f"sans échantillon depuis plus de {srv.decrochage_s} s, la liaison est déclarée "
            f"PERDUE ({liaison})")
        qualite = srv.snapshot().get("quality") or {}
        chk(qualite.get("contact") == [None] * 8 and qualite.get("reference_ok") is None,
            f"liaison perdue : plus aucun verdict de contact — le dernier σ date d'avant la "
            f"coupure ({qualite.get('contact')})")

        avant, tours_avant = decisions["n"], tours["n"]
        time.sleep(1.0)
        liaison = srv.snapshot()["liaison"]
        chk(decisions["n"] == avant,
            f"pendant la coupure, le SSVEP ne décode PLUS : sinon il republierait sa dernière "
            f"cible en boucle sur un tampon figé ({decisions['n'] - avant} décision(s))")
        chk(fil.is_alive(),
            "🔴 le moteur SURVIT à une réouverture ratée, qui a libéré la session (une batterie à "
            "plat, par exemple)")
        chk(lectures_coupees["n"] == 0,
            f"…parce qu'il ne LIT plus la session pendant la coupure : elle peut être libérée, et "
            f"la relire à chaque tour ne ferait que faire lever BrainFlow "
            f"({lectures_coupees['n']} lecture(s) pendant la coupure)")
        chk(len(essais) >= 2 and "simulé" in liaison["erreur"] and liaison["tentatives"] >= 2
            and liaison["depuis_s"] and liaison["depuis_s"] > 0.5,
            f"…il RÉESSAIE de rouvrir le casque, et l'état dit depuis quand et pourquoi ça échoue "
            f"({liaison})")
        n_tours = tours["n"] - tours_avant
        chk(0 < n_tours <= 1.0 / POLL_S * 1.5 + 5,
            f"…la boucle continue de servir les commandes, mais en marquant sa PAUSE — pas une "
            f"boucle à vide entre deux essais ({n_tours} tours en 1 s)")
        mesure = srv.snapshot().get("mesure") or {}
        chk(mesure.get("phase") == "annule"
            and mesure.get("probleme") == tr("moteur.liaison.seance_annulee"),
            f"…et le test en cours est ANNULÉ, en disant pourquoi : ses données auraient un trou "
            f"({mesure.get('phase')}, {mesure.get('probleme')!r})")

        retour["ok"] = True
        t0 = time.perf_counter()
        while (srv.snapshot()["liaison"]["etat"] != "ok" and time.perf_counter() - t0 < 3.0
               and fil.is_alive()):
            time.sleep(0.05)
        liaison = srv.snapshot()["liaison"]
        chk(liaison["etat"] == "ok" and liaison["coupure_s"] and liaison["coupure_s"] > 1.0
            and liaison["retablie_depuis_s"] is not None,
            f"le casque revenu, la liaison est RÉTABLIE, et l'état dit combien de temps elle a "
            f"été coupée ({liaison})")
        chk(ssvep.phase in ("warmup", "rest"),
            f"…et le SSVEP REFAIT son repos : son plancher datait d'avant la coupure, et la "
            f"réouverture redémarre l'amplificateur ({ssvep.phase})")
        t0 = time.perf_counter()
        while len(srv.recent) == 0 and time.perf_counter() - t0 < 3.0:
            time.sleep(0.05)
        chk(len(srv.recent) > 0 and fil.is_alive(),
            f"…les échantillons arrivent de nouveau, sans relancer la console "
            f"({len(srv.recent)} dans le tampon)")
        # 🔴 Règle 2 de `_lire` : une lecture qui LÈVE en pleine séance compte comme « aucun
        # échantillon ». La liaison est déclarée perdue, le moteur rouvre — le fil ne meurt pas.
        # La réouverture est permise ici (`retour`), donc l'état « perdue » ne dure qu'un tour :
        # on compte les RÉOUVERTURES — c'est elles qui prouvent que la lecture qui lève a été prise
        # pour une coupure.
        essais_avant = len(essais)
        leve["on"] = True
        time.sleep(1.0)
        leve["on"] = False
        chk(fil.is_alive() and len(essais) > essais_avant,
            f"🔴 une lecture qui LÈVE en pleine séance ne tue pas le moteur : elle compte comme "
            f"« aucun échantillon », la coupure est déclarée et le casque rouvert "
            f"({len(essais) - essais_avant} réouverture(s), fil vivant : {fil.is_alive()})")
        t0 = time.perf_counter()
        while (srv.snapshot()["liaison"]["etat"] != "ok" and time.perf_counter() - t0 < 3.0
               and fil.is_alive()):
            time.sleep(0.05)
        chk(srv.snapshot()["liaison"]["etat"] == "ok",
            f"…puis elle revient, comme après une coupure ({srv.snapshot()['liaison']['etat']})")
        from brainflow.data_filter import NoiseTypes
        chk(srv.acq is acq_avant and srv.acq.notch is NoiseTypes.SIXTY,
            f"[smoke-secteur] …et le casque rouvert coupe toujours le secteur du POSTE (60 Hz), "
            f"pas le défaut de l'acquisition ({srv.acq.notch.name})")
    finally:
        srv.stop()
        fil.join(timeout=5.0)
        srv.close()
        # 🔴 DÉFAIRE les remplacements, puis détruire le moteur MAINTENANT. Chacun (`lire_coupe`,
        # `rouvrir_si_permis`, `vider_compte`, `tick_compte`) garde une méthode liée du moteur ou
        # de son acquisition : un CYCLE, que seul le ramasse-miettes défait, plus tard, au hasard.
        # Et ce jour-là, `BoardShim.__del__` libère la session du board de test — que BrainFlow
        # PARTAGE entre tous les boards de test aux mêmes paramètres, donc celle du moteur d'un
        # AUTRE test (fil orphelin `BOARD_NOT_CREATED_ERROR:15`, `[smoke-cumul]` rouge à chaque
        # passage complet, vert seul). C'est le piège du `finally` de `run()`, reproduit ici.
        for nom in ("get_new_data", "reouvrir"):
            srv.acq.__dict__.pop(nom, None)
        srv.__dict__.pop("_drain_commands", None)
        if ssvep is not None:
            ssvep.__dict__.pop("tick", None)
        del srv, fil, ssvep, lire, rouvrir, vider, acq_avant
        import gc
        gc.collect()
    print(f"[smoke-liaison] VERDICT : {'OK' if ok else 'ÉCHEC'}")
    return ok


def _smoke_mesure():
    """Les mesures : leur ligne du temps ET le refus d'une seconde activité.

    ⚠️ **DÉLÉGUÉ, pas recopié.** Le refus vit dans CE fichier (`_refus_pour_mesure_en_cours` /
    `_refus_pour_calibration_en_cours`, plus leurs jumeaux côté boucle), mais il n'a de sens
    qu'avec un `MesureRuntime` en face, et l'autotest de `core/modes/mesure.py` en construit
    déjà un — avec son protocole, son horloge fabriquée et son moteur factice. Écrire la même
    vérité aux deux endroits la laisserait diverger : l'un serait corrigé et pas l'autre.

    Ce qui compte est que `python src/core/server.py --smoke` rougisse si l'un des deux sens du
    refus disparaît — et c'est ce que cet appel garantit.
    """
    from core.modes.mesure import _selftest as _selftest_mesure

    return _selftest_mesure()


def _smoke_retour_en_direct():
    """Le retour en direct : un TEST publie ses décisions sur le flux de son mode.

    Sur un VRAI moteur et un VRAI test SSVEP : un client LSL qui résout `decoded_ssvep` reçoit,
    pendant le test, une décision par essai — celle que le verdict note — ; et le refus croisé
    test SSVEP ↔ mode SSVEP, dans les DEUX sens, à la soumission comme dans la boucle.

    ⚠️ **DÉLÉGUÉ, pas recopié**, comme `_smoke_mesure` : la séance est jouée par
    `core/modes/ssvep_mesure.py`, qui sait fabriquer un repos et des fixations ; l'écrire deux
    fois la laisserait diverger.
    """
    from core.modes.ssvep_mesure import _selftest_retour_en_direct

    return _selftest_retour_en_direct()


def _smoke_enregistrement():
    """Enregistrer une séance : le MOTEUR tient la plume, et JAMAIS au-dessus de `data/`.

    ⚠️ **Ce test existe surtout pour la deuxième moitié de cette phrase.** L'enregistrement est
    la seule capacité d'ÉCRITURE du moteur en dehors des modèles de calibration : `data/` peut
    donc être touché par accident. `data/` porte des
    enregistrements EEG d'une personne identifiable, sur un dépôt PUBLIC, et le fichier le plus
    récent qui s'y trouve est ce que le moteur ÉLIT par défaut — un verdict de séance déposé là ne
    se contenterait pas d'encombrer. On prend donc l'empreinte du VRAI `data/` avant et après.

    ⚠️ **Ce que le fichier vaut se juge à la JOINTURE, pas ici.** Une séance c-VEP ne se dépouille
    qu'avec DEUX fichiers : la vérité-terrain côté fenêtre (`stimulus/cvep.py --log`) et les
    verdicts côté moteur (celui-ci). Les deux portent la même horloge `local_clock()`, et c'est
    tout ce qui rend la jointure possible — d'où l'assertion sur le DOMAINE de l'horodatage, qui
    est la seule chose qu'un test sans casque puisse vraiment prouver de ce fichier.
    """
    import json
    import shutil
    import tempfile
    import threading

    from pylsl import local_clock

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # 1. LE DOSSIER. Vérifié sur la CONSTANTE, sans rien écrire : le test tourne dans un
    #    temporaire (il ne doit pas semer dans le `seances/` de l'utilisateur), donc si personne
    #    ne regardait le défaut, le jour où il repointerait sur `data/` aucun test ne rougirait.
    chk(os.path.abspath(SEANCES_DIR) != os.path.abspath(DATA_DIR)
        and not os.path.abspath(SEANCES_DIR).startswith(os.path.abspath(DATA_DIR) + os.sep),
        f"le dossier des séances vit HORS de data/ ({SEANCES_DIR})")

    dossier = tempfile.mkdtemp(prefix="smoke_seances_")
    try:
        # 2. LES REFUS, à la SOUMISSION — sans boucle : `submit` n'en dépend pas (cf. sa docstring).
        srv = EngineServer(synthetic=True, instance="smoke-enr", modes=("raw",),
                           seances_dir=dossier)
        chk(srv.snapshot().get("enregistrement") is None,
            "aucun enregistrement au démarrage — le champ existe et vaut None, il ne manque pas")
        r = srv.submit("start_enregistrement", stream="decoded_pasdemode")
        chk(not r.get("accepted") and "decoded_pasdemode" in (r.get("reason") or ""),
            f"un flux inconnu est refusé, en le nommant ({r})")
        r = srv.submit("start_enregistrement", stream="decoded_ssvep")
        chk(not r.get("accepted") and "démarr" in (r.get("reason") or "").lower(),
            f"…et un flux dont le mode n'est PAS démarré aussi : un fichier vide se lit comme "
            f"une séance ratée, pas comme un mode oublié ({r})")
        r = srv.submit("stop_enregistrement")
        chk(not r.get("accepted") and r.get("reason"),
            f"arrêter alors que rien n'enregistre est refusé avec un motif ({r})")

        # 3. LA RÈGLE DU FICHIER, sur l'objet seul : **une ligne par DÉCISION PUBLIÉE**, jamais une
        #    par tour de boucle. Les modes republient leur sortie dans un dict NEUF à chaque
        #    publication ; un tour où rien n'a été publié rend donc le MÊME objet, et écrire une
        #    ligne pour lui fabriquerait une décision que personne n'a prise. C'est la faute qui
        #    ferait lire 100 % d'émission à un mode qui n'émet que 44 % du temps.
        class _RuntimeFactice:
            def __init__(self):
                self.spec = registry.get("ssvep")
                self.params, self.published, self.phase = {}, True, "running"
                self._sortie = None

            def channels(self):
                return ["target_index"]

            def output(self):
                return self._sortie

        rt = _RuntimeFactice()
        enr = _Enregistrement(os.path.join(dossier, "regle.jsonl"), "ssvep",
                              stream_name("decoded_ssvep"))
        enr.ouvrir(rt, instance="test", fs_hz=250.0)
        rt._sortie = {"target_index": 1}
        enr.noter(rt, 100.0)
        enr.noter(rt, 100.2)               # même objet : rien n'a été publié entre les deux
        chk(enr.lignes == 1,
            f"deux tours de boucle sans NOUVELLE décision = UNE ligne ({enr.lignes}) — sinon un "
            f"mode qui émet 44 % du temps se relirait à 100 %")
        rt._sortie = {"target_index": 1}   # même CONTENU, objet neuf : une vraie 2e publication
        enr.noter(rt, 100.4)
        chk(enr.lignes == 2,
            f"…et une décision RÉPÉTÉE à l'identique compte quand même ({enr.lignes}) : c'est une "
            f"émission de plus, et le taux d'émission est précisément ce qu'on vient mesurer")
        enr.fermer()

        # 4. DE BOUT EN BOUT, avec une vraie boucle : le moteur décode, on enregistre, on arrête.
        empreinte_avant = empreinte_dossier(DATA_DIR)
        freqs = [c["actual_hz"] for c in choose_frequencies(60.0)]
        srv = EngineServer(synthetic=True, instance="smoke-enr2", modes=("raw", "ssvep"),
                           params={"ssvep": {"freqs": freqs}}, seances_dir=dossier)
        fil = threading.Thread(target=srv.run,
                               kwargs={"duration_s": 12.0, "baseline_s": 1.0, "warmup_s": 0.5},
                               daemon=True)
        fil.start()
        t0 = time.perf_counter()
        while srv.phase != "decoding" and time.perf_counter() - t0 < 10.0 and fil.is_alive():
            time.sleep(0.05)

        depart = local_clock()
        r = srv.submit("start_enregistrement", stream="decoded_ssvep")
        chk(r.get("accepted"), f"l'enregistrement démarre ({r})")
        # ⚠️ **L'accusé de départ ne promet AUCUN chemin**, et c'est ce que cette assertion
        # protège. Le nom du fichier est décidé par la BOUCLE : `submit` ne fait que mettre en
        # file, donc un chemin rendu ici serait celui d'un fichier que la boucle peut refuser de
        # créer (cas du double-clic juste en dessous). L'écran lit le chemin dans `snapshot()`,
        # où il est vrai.
        chk("chemin" not in r,
            f"…sans promettre de chemin : c'est la BOUCLE qui le décide, et l'écran le lit dans "
            f"l'état ({r})")
        # LE DOUBLE-CLIC, dans la MÊME fenêtre de sondage : les deux commandes voient un moteur
        # vierge (la boucle n'a pas encore appliqué la première), donc les deux sont ACCEPTÉES —
        # c'est le motif exact de `start_mesure`, et c'est pourquoi le refus est refait dans la
        # boucle. Ce qui compte n'est pas l'accusé, c'est qu'UN SEUL fichier existe au bout.
        srv.submit("start_enregistrement", stream="decoded_ssvep")
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 2.5 and fil.is_alive():
            time.sleep(0.1)
        chk(len([f for f in os.listdir(dossier) if f.startswith("moteur_")]) == 1,
            f"un double-clic ne produit qu'UN fichier : le second départ est refusé par la BOUCLE, "
            f"pas par l'accusé ({sorted(os.listdir(dossier))})")

        etat = (srv.snapshot() or {}).get("enregistrement") or {}
        chk(etat.get("actif") and etat.get("lignes", 0) > 0 and etat.get("chemin"),
            f"pendant l'enregistrement, l'état PUBLIÉ dit qu'il tourne, où, et combien "
            f"({etat})")
        # …et une fois la boucle passée, `submit` refuse tout seul : c'est le cas NORMAL (deux
        # clics à une seconde d'intervalle), celui où l'utilisateur mérite un motif à l'écran.
        r2 = srv.submit("start_enregistrement", stream="decoded_ssvep")
        chk(not r2.get("accepted") and "cours" in (r2.get("reason") or "").lower(),
            f"…et un SECOND enregistrement est alors refusé, en disant lequel tourne ({r2})")

        r = srv.submit("stop_enregistrement")
        chemin = r.get("chemin") or ""
        chk(r.get("accepted") and os.path.isfile(chemin),
            f"l'enregistrement produit un fichier ({chemin})")
        # On attend que la BOUCLE ait appliqué l'arrêt : `submit` ne fait que mettre en file, et
        # c'est le fil de la boucle qui ferme le fichier (la console, elle, ne touche rien).
        t0 = time.perf_counter()
        while ((srv.snapshot().get("enregistrement") or {}).get("actif")
               and time.perf_counter() - t0 < 5.0 and fil.is_alive()):
            time.sleep(0.05)
        r2 = srv.submit("stop_enregistrement")
        chk(not r2.get("accepted") and r2.get("reason"),
            f"arrêter deux fois est refusé avec un motif ({r2})")
        srv.stop()
        fil.join(timeout=5.0)

        chk(empreinte_dossier(DATA_DIR) == empreinte_avant,
            "…et data/ est INTACT : une séance n'est ni un modèle ni un enregistrement EEG, et "
            "data/ garde son autorité unique")
        chk(os.path.abspath(DATA_DIR) not in os.path.abspath(chemin),
            f"le fichier vit hors de data/ ({chemin})")

        with open(chemin, encoding="utf-8") as f:
            lignes = [json.loads(l) for l in f if l.strip()]
        genres = [l.get("kind") for l in lignes]
        verdicts = [l for l in lignes if l.get("kind") == "verdict"]
        chk(genres[:1] == ["header"] and genres[-1:] == ["fin"],
            f"le fichier s'ouvre par un en-tête et se ferme par un bilan ({genres[:2]}…{genres[-1:]})")
        chk(len(verdicts) >= 3,
            f"…et porte les verdicts du moteur, un par décision publiée ({len(verdicts)})")
        chk(lignes[0].get("flux") == stream_name("decoded_ssvep")
            and lignes[0].get("voies"),
            f"l'en-tête nomme le flux COMPLET et ses voies ({lignes[0].get('flux')})")
        chk(lignes[-1].get("verdicts") == len(verdicts),
            f"le bilan compte ce que le fichier contient vraiment "
            f"({lignes[-1].get('verdicts')} annoncés, {len(verdicts)} écrits)")
        # ⚠️ **L'HORLOGE.** C'est la seule chose de ce fichier qu'un test sans casque puisse
        # vraiment prouver, et c'est celle dont tout dépend : sans elle, la jointure avec le
        # journal de la fenêtre ne se fait pas. `local_clock()` compte depuis le
        # démarrage de la machine — un horodatage pris en temps UNIX y serait ~50 ans trop grand
        # et personne ne s'en apercevrait avant de dépouiller.
        ts = [l["t"] for l in verdicts]
        chk(all(depart - 1.0 <= t <= local_clock() + 1.0 for t in ts),
            f"les verdicts sont horodatés dans l'horloge LSL, la MÊME que le journal de la "
            f"fenêtre de stimulus ({ts[0] if ts else '?'} pour local_clock()={local_clock():.1f})")
        chk(ts == sorted(ts), "…et dans l'ordre, comme les recevrait un client")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[smoke-enregistrement] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_vol_marqueurs():
    """LE VOL DE MARQUEURS, refusé DANS LES DEUX SENS — mode puis calibration, et l'inverse.

    C'est la panne la plus coûteuse de ce sous-système parce qu'elle ne casse RIEN : le mode P300
    et sa calibration se réclament du même `spec.id`, `markers_murs` n'y tient qu'UN curseur, et
    chacun n'obtient donc qu'une moitié arbitraire des marqueurs. Aucune exception, aucun
    compteur qui bouge — une séance entière d'époques trouées, et un modèle qui décodera du bruit
    avec de belles probabilités.

    Les DEUX sens sont exercés, et c'est délibéré : c'est exactement le genre de garde qu'on pose
    dans un sens en croyant avoir fermé la porte. Chacun l'est deux fois — à la SOUMISSION
    (`submit`) et dans la BOUCLE (`_start`, `_start_calibration`), qui sont deux instants
    différents : deux commandes soumises dans la même fenêtre de sondage voient toutes les deux un
    moteur vierge.

    Aucun casque, aucune boucle : `submit` ne dépend pas de la boucle (cf. sa docstring) et les
    deux gardes côté boucle sont des méthodes appelables directement.
    """
    import shutil
    import tempfile

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    from core import p300_models
    from core.modes.p300 import SPEC as SPEC_P300
    from core.modes.p300_calib import P300Calibration

    dossier = tempfile.mkdtemp(prefix="smoke_vol_")
    srv = EngineServer(synthetic=True, modes=(), instance="smoke-vol")

    class _ModeFactice:
        """Un P300 « démarré » sans casque ni modèle.

        `submit` et les deux gardes ne lisent que les CLÉS de `self.active` — démarrer un vrai
        `P300Runtime` exigerait un modèle entraîné dans le VRAI `data/`, c'est-à-dire faire
        dépendre ce refus de l'état du disque de la machine qui lance le test.
        """

        spec = SPEC_P300
        params = {}
        phase = "running"
        published = True

        def state(self):
            return {}

        def close(self):
            pass

    try:
        chk(_calibration_lit_les_marqueurs(SPEC_P300.calibration)
            and SPEC_P300.marker_epoch_s > 0,
            f"le P300 est bien le cas à protéger : son mode ÉPOQUE sur marqueurs "
            f"({SPEC_P300.marker_epoch_s:g} s) et sa calibration LIT la même file "
            f"({SPEC_P300.calibration.runtime_cls.__name__})")

        # === SENS 1 : le mode DÉCODE, on demande sa calibration ==========================
        srv.active["p300"] = _ModeFactice()
        r = srv.submit("start_calibration", id="p300")
        raison = r.get("reason") or ""
        chk(not r.get("accepted") and "décode en ce moment" in raison,
            f"sens 1 — calibrer un mode qui décode est REFUSÉ ({raison[:60]}…)")
        chk("« P300 »" in raison and "même file de marqueurs" in raison,
            f"…en NOMMANT le mode à arrêter et en disant la panne ({raison})")
        # …mais la validation AU CLIC ne refuse PAS pour ça : c'est le refus que la
        # console lève elle-même, en arrêtant le mode avant l'entraînement. Le refuser ici
        # interdirait le geste qu'elle s'apprête à faire.
        v_clic, r_clic = srv.valider_calibration("p300", {})
        chk(v_clic is not None and r_clic is None,
            f"…alors que la validation au clic l'ACCEPTE : la console arrête le mode d'abord "
            f"({r_clic})")
        v_clic, r_clic = srv.valider_calibration("p300", {"band_high": 50.0})
        chk(v_clic is None and r_clic and "maximum" in r_clic and "décode" not in r_clic,
            f"…et une bande invalide y est refusée pour ELLE-MÊME, mode actif ou pas ({r_clic})")

        # Le négatif qui prouve que le refus est ciblé : un AUTRE mode, dont la calibration ne
        # lit aucun marqueur (le MI est endogène), n'est pas concerné par ce refus-là.
        r_mi = srv.submit("start_calibration", id="mi", params={})
        chk(r_mi.get("accepted"),
            f"…et la calibration d'un mode SANS marqueurs reste acceptée pendant ce temps "
            f"({r_mi})")

        # La garde côté BOUCLE, même sens : c'est elle qui attrape la course.
        srv.calibration = None
        srv._start_calibration("p300", {})
        chk(srv.calibration is None,
            f"sens 1, côté BOUCLE — la course (start_mode et start_calibration soumis dans la "
            f"même fenêtre de sondage) est rattrapée : aucune calibration n'est construite "
            f"({srv.calibration})")

        # === SENS 2 : la CALIBRATION tourne, on demande le mode ==========================
        srv.active.pop("p300", None)
        srv._commands = queue.Queue()          # on jette ce que les refus ci-dessus ont mis en file
        srv.calibration = P300Calibration(SPEC_P300, {}, srv, dossier=dossier)
        chk(isinstance(srv.calibration, MarkerCalibrationRuntime)
            and not srv.calibration.terminee,
            f"une VRAIE calibration P300 tourne ({type(srv.calibration).__name__}, "
            f"phase={srv.calibration.phase})")
        # La validation au clic refuse un SECOND entraînement : la console n'arrêtera pas un
        # décodage pour un refus certain.
        v_clic, r_clic = srv.valider_calibration("mi", {})
        chk(v_clic is None and "déjà en cours" in (r_clic or ""),
            f"pendant un entraînement, la validation au clic en refuse un second ({r_clic})")

        # ⚠️ La liste de modèles est VIDÉE le temps de l'appel. Sans ça, ce test passerait pour la
        # mauvaise raison sur un dépôt fraîchement cloné (« aucun choix disponible »), et aussi
        # si le refus était placé après `contract.validate` : c'est la preuve que la garde ne
        # dépend pas de l'état de `data/`.
        vrai_dispo = p300_models.modeles_disponibles
        p300_models.modeles_disponibles = lambda d=None: []
        try:
            r = srv.submit("start_mode", id="p300")
        finally:
            p300_models.modeles_disponibles = vrai_dispo
        raison = r.get("reason") or ""
        chk(not r.get("accepted") and "entraînement de « P300 » est en cours" in raison,
            f"sens 2 — démarrer un mode dont la calibration tourne est REFUSÉ ({raison[:60]}…)")
        chk("même file de marqueurs" in raison and "choix disponible" not in raison,
            f"…pour LA bonne raison, et sans dépendre d'un modèle présent dans data/ ({raison})")

        # Le négatif, dans ce sens aussi : un AUTRE mode démarre pendant la calibration P300.
        r_ssvep = srv.submit("start_mode", id="ssvep")
        chk(r_ssvep.get("accepted"),
            f"…et un mode qui n'est pas celui qu'on calibre démarre normalement ({r_ssvep})")

        # La garde côté BOUCLE, même sens. `values` volontairement vides : si la garde tombait,
        # `P300Runtime.__init__` lèverait — on l'attrape pour rendre un ÉCHEC lisible plutôt
        # qu'une trace Python qui ferait sauter les sous-tests suivants de `_smoke()`.
        try:
            srv._start(["p300"], {"p300": {}}, time.perf_counter())
            leve = None
        except Exception as e:  # noqa: BLE001 - la garde a sauté, on veut le dire proprement
            leve = f"{type(e).__name__} : {e}"
        chk("p300" not in srv.active and leve is None,
            f"sens 2, côté BOUCLE — la course symétrique est rattrapée elle aussi : le mode n'est "
            f"pas démarré ({sorted(srv.active)}, exception={leve})")

        # === Le contrôle qui rend la garde FALSIFIABLE ==================================
        # Une calibration TERMINÉE ne lit plus rien : elle ne doit plus rien bloquer. Sans cette
        # ligne, un refus écrit « dès qu'une calibration existe » passerait les six assertions
        # ci-dessus et interdirait le mode P300 pour le reste de la séance.
        srv.calibration.cancel()
        r = srv.submit("start_mode", id="p300")
        chk((r.get("reason") or "").find("même file de marqueurs") < 0,
            f"une calibration TERMINÉE ne bloque plus rien — le refus porte sur « en cours », pas "
            f"sur « existe » ({r})")

        # === 🔴 LE TROISIÈME LECTEUR DE LA MÊME FILE : le TEST d'un mode =======================
        # Une mesure menée par une fenêtre lit par `markers_murs(marker_mode_id)`, et `marker_mode_id` est l'identifiant DU
        # MODE. Un test P300 lancé pendant que le mode P300 décode serait donc le même vol, par un
        # troisième lecteur. Le test factice ci-dessous ne déclare que ce que le refus examine : la
        # CLASSE et son `marker_mode_id`.
        from core.modes import registry as _reg
        from core.modes.mesure import MesureSpec
        from core.modes.mesure_marqueurs import MesureMarqueurs

        from core.modes.p300 import P300Runtime

        class _TestFactice(MesureMarqueurs):
            """CONSTRUCTIBLE, et c'est ce qui rend l'assertion « côté boucle » falsifiable : sans
            le refus, la boucle construit bel et bien cette mesure, et l'assertion rougit. Une
            classe réduite à `marker_mode_id` lèverait à la construction, et la garde ne
            rougirait que par accident, sur une exception."""
            marker_mode_id = "p300"
            runtime_cls_du_mode = P300Runtime
            evenement_unite = "round_end"
            epoque_marqueur_s = SPEC_P300.marker_epoch_s

            def _encaisser_protocole(self, engine, ts, marqueur):
                pass

            def _mesurer(self, enregistre, fs):
                return {}

        spec_test = MesureSpec(id="test_p300_factice", label="Test P300 (factice)",
                               runtime_cls=_TestFactice)

        class _MesureEnCours:
            """Un test qui TOURNE : ce que `_refus_mode_pendant_mesure` interroge, l'objet."""
            spec = spec_test
            marker_mode_id = "p300"
            terminee = False

        vraies = _reg.MESURES
        _reg.MESURES = tuple(vraies) + (spec_test,)
        try:
            # Sens 1 : le mode DÉCODE, son test est refusé — à la soumission et dans la boucle.
            srv.active["p300"] = _ModeFactice()
            r = srv.submit("start_mesure", id="test_p300_factice")
            chk(not r.get("accepted") and "décode en ce moment" in (r.get("reason") or "")
                and "tester" in (r.get("reason") or "")
                and "calibration" not in (r.get("reason") or ""),
                f"sens 1 — tester un mode qui DÉCODE est refusé, en disant quoi arrêter "
                f"({(r.get('reason') or '')[:70]}…)")
            srv._start_mesure("test_p300_factice", {})
            chk(srv.mesure is None,
                "sens 1, côté BOUCLE — la course (start_mode et start_mesure dans la même fenêtre "
                "de sondage) est rattrapée : aucune mesure n'est construite")
            srv.active.pop("p300", None)

            # Sens 2 : le test TOURNE, le mode est refusé — à la soumission et dans la boucle.
            srv.mesure = _MesureEnCours()
            r = srv.submit("start_mode", id="p300")
            chk(not r.get("accepted")
                and "test de « P300 » est en cours" in (r.get("reason") or ""),
                f"sens 2 — démarrer un mode pendant que son TEST lit ses marqueurs est refusé "
                f"({(r.get('reason') or '')[:70]}…)")
            srv._start(["p300"], {"p300": {}}, time.perf_counter())
            chk("p300" not in srv.active,
                f"sens 2, côté BOUCLE — la course symétrique est rattrapée ({sorted(srv.active)})")

            # Les contrôles qui rendent la garde FALSIFIABLE : elle porte sur « ce test-là, en
            # cours, d'un mode qui lit des marqueurs » — pas sur « une mesure existe ».
            _MesureEnCours.terminee = True
            r = srv.submit("start_mode", id="p300")
            chk("est en cours" not in (r.get("reason") or ""),
                f"un test TERMINÉ ne bloque plus le mode ({(r.get('reason') or 'accepté')[:60]})")
            _MesureEnCours.terminee, _MesureEnCours.marker_mode_id = False, "errp"
            r = srv.submit("start_mode", id="p300")
            chk("est en cours" not in (r.get("reason") or ""),
                "…et le test d'un AUTRE mode ne bloque pas celui-ci : chacun a sa propre file")
            srv.mesure = None
            # Le SSVEP ne lit AUCUN marqueur, mais son test publie sur `decoded_ssvep` : refusé
            # pour CETTE raison-là, pas pour un vol (cf. `_smoke_retour_en_direct`).
            srv.active["ssvep"] = _ModeFactice()
            refus_ssvep = srv._refus_mesure_pendant_mode(_reg.get_mesure("ssvep_taux"),
                                                         dict(srv.active)) or ""
            chk("même flux" in refus_ssvep and "file de marqueurs" not in refus_ssvep,
                f"…et le test SSVEP, qui ne vole rien, est refusé pour le FLUX qu'il partage avec "
                f"son mode ({refus_ssvep[:70]}…)")
            srv.active.pop("ssvep", None)

            # Pendant le TEST d'un mode, ses réglages ne bougent pas ; ceux des AUTRES modes, si.
            class _TestSsvepEnCours:
                spec = _reg.get_mesure("ssvep_taux")
                marker_mode_id = ""
                terminee = False

            srv.mesure = _TestSsvepEnCours()
            pendant = srv.submit("set_params", id="ssvep", params={})
            autre = srv.submit("set_params", id="neuro", params={})
            chk(not pendant.get("accepted") and "SSVEP" in (pendant.get("reason") or "")
                and autre.get("accepted"),
                f"pendant son test, un mode refuse qu'on change ses réglages, et un autre mode "
                f"les accepte ({(pendant.get('reason') or 'accepté')[:70]}…)")
            _TestSsvepEnCours.terminee = True
            apres = srv.submit("set_params", id="ssvep", params={})
            chk(apres.get("accepted"),
                f"…et le test fini, les réglages se changent de nouveau "
                f"({apres.get('reason', 'accepté')})")
            srv.mesure = None
        finally:
            _reg.MESURES = vraies
            srv.mesure = None

        # Les VRAIS tests de mode, une fois branchés : le refus ne doit pas tenir au seul test
        # factice ci-dessus. Chaque mesure désignée par le `test_id` d'un mode qui LIT des
        # marqueurs doit être refusée pendant que ce mode décode — sinon il suffirait qu'un test
        # déclare mal son `marker_mode_id` pour rouvrir la porte, sans qu'aucun test ne rougisse.
        a_proteger = [s for s in registry.MODES if s.test_id and (
            s.marker_epoch_s > 0
            or _publie_le_flux_du_mode(registry.get_mesure(s.test_id).runtime_cls))]
        non_couverts = [s.test_id for s in a_proteger
                        if srv._refus_mesure_pendant_mode(registry.get_mesure(s.test_id),
                                                          {s.id: _ModeFactice()}) is None]
        chk({"ssvep_taux", "cvep_test", "p300_test"} <= {s.test_id for s in a_proteger}
            and not non_couverts,
            f"chaque VRAI test d'un mode à marqueurs, ou qui publie sur le flux de son mode, est "
            f"refusé pendant que ce mode décode ({[s.test_id for s in a_proteger]} ; non "
            f"couverts : {non_couverts or 'aucun'})")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[smoke-vol-marqueurs] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


# Les paquets que `core` n'a pas le droit d'importer : les deux autres paquets du dépôt, et les
# deux bibliothèques d'écran. Le nom n'est écrit QU'ICI — jamais dans une prose voisine, jamais
# sous la forme d'un import complet dans un commentaire : voir `_imports_interdits`.
_FRONTIERE_INTERDITS = ("research", "console", "stimulus", "pygame", "qtpy", "pyqtgraph")
_FRONTIERE_INTERDITS_RE = r"PySide\d+|PyQt\d+"

# Ce que `src/stimulus/` n'a pas le droit d'importer. La liste est PLUS COURTE que celle de
# `core` — et c'est le point : une fenêtre de stimulus EST du pygame, l'interdire ici n'aurait
# aucun sens. Ce qu'on lui interdit, c'est de tirer le banc d'essai ou la console derrière elle :
# la console l'importe (`stimulus/registry.py`), donc `stimulus -> research` ferait entrer tout
# `research` dans la console, et `stimulus -> console` rendrait une fenêtre inlançable sur une
# machine sans Qt — alors qu'elle n'a besoin que d'un écran.
_FRONTIERE_STIMULUS_INTERDITS = ("research", "console", "brainflow")

# ⚠️ **Et l'acquisition, nommément.** L'invariant fondateur de `src/stimulus/` — *« une fenêtre
# n'ouvre JAMAIS le casque »* — est ce qui autorise le montage à deux programmes : l'Unicorn
# n'accepte qu'une connexion, et c'est parce que la fenêtre n'en ouvre aucune qu'elle peut tourner
# à côté du moteur. Il est vérifié par un test, pas par la prose de `stimulus/__init__.py`.
# `brainflow` ci-dessus ferme la porte d'en bas ; celle-ci ferme la porte d'en haut, car
# `core.acquisition` est un import de `core`, donc autorisé par la liste des paquets.
_FRONTIERE_STIMULUS_MODULES_INTERDITS = ("core.acquisition",)

# Ce que le paquet `research` (le banc d'essai, absent de la copie publique) n'a pas le droit
# d'importer. Le banc d'essai peut tout CALCULER sur des
# fichiers archivés — c'est son métier : rejouer, comparer, mesurer hors ligne — mais il ne
# touche NI au casque NI à un écran : ces deux gestes-là
# sont de l'USAGE RÉEL, et l'usage réel se pilote depuis la console.
#
# ⚠️ Tout l'usage réel se pilote depuis l'interface graphique : une contrainte tenue par la
# discipline n'est pas tenue, donc elle est tenue par ce scanner, comme la frontière entre les
# paquets.
#
# `console` est dans la liste : le tableau des quatre flèches donne à `research` le droit
# d'importer `core` et `stimulus`, et RIEN d'autre. Un `research -> console` tirerait Qt dans une
# analyse hors ligne — donc rendrait le banc d'essai inutilisable sur une machine sans écran,
# alors que c'est précisément là qu'il tourne.
_FRONTIERE_RESEARCH_INTERDITS = ("pygame", "brainflow", "console")
_FRONTIERE_RESEARCH_MODULES_INTERDITS = ("core.acquisition",)

# Ce que `src/console/` n'a pas le droit d'importer. **Un seul nom**, et c'est tout ce que le
# tableau des quatre flèches lui interdit : la console importe `core` (elle est un CLIENT du
# moteur), `stimulus` (elle lance les fenêtres) et Qt (elle EST du Qt). Ce qu'elle ne doit pas
# faire, c'est tirer le banc d'essai derrière un bouton : `research` contient des analyses hors
# ligne, des protocoles chiffrés et des hypothèses réfutées, dont rien n'est du parcours d'un
# étudiant. Un import suffirait à en faire entrer un dans l'interface sans qu'on l'ait décidé.
#
# ⚠️ `src/console/` est scanné lui aussi : la règle ÉCRITE ne doit jamais être plus large que sa
# VÉRIFICATION (c'est toujours le cran qui manque qui compte), et « aujourd'hui personne ne le
# fait » est de la discipline, pas un test.
_FRONTIERE_CONSOLE_INTERDITS = ("research",)


def _imports_interdits(source, nom_fichier="<extrait>", interdits=None, interdits_re=None,
                       exacts=None):
    """Les paquets interdits que CE CODE importe. Retourne [(ligne, paquet), ...].

    ⚠️ **Juge le CODE, pas le texte.** Une expression régulière `^\\s*(?:from|import)\\s+(…)`
    verrait aussi les docstrings et les chaînes : un simple reflow d'un paragraphe contenant
    l'exemple « un import de PySide6 » ferait échouer `--smoke` sur de la PROSE, et un
    contributeur chercherait un import qui n'existe pas. Une garde qui se déclenche sur sa propre
    documentation est une garde qu'on finit par désactiver.

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

    # `interdits` est paramétrable pour que les quatre paquets soient scannés par le MÊME code,
    # avec des listes différentes : une fonction copiée-collée par paquet divergerait, et celle
    # qui ne sert qu'à un paquet est celle qu'on oublie de corriger.
    noms = tuple(_FRONTIERE_INTERDITS if interdits is None else interdits)
    motif_re = _FRONTIERE_INTERDITS_RE if interdits_re is None else interdits_re
    alternatives = "|".join(noms)
    if motif_re:
        alternatives = f"{alternatives}|{motif_re}" if alternatives else motif_re
    motif = re.compile(rf"^(?:{alternatives})$")
    fautes = []
    for noeud in ast.walk(ast.parse(source, filename=nom_fichier)):
        if isinstance(noeud, ast.Import):
            cibles = [alias.name for alias in noeud.names]
            formes = list(cibles)
        elif isinstance(noeud, ast.ImportFrom):
            # `node.module` vaut None pour `from . import x` ; `level > 0` est un import relatif,
            # examiné lui aussi : `core` n'a aucun sous-module portant l'un de ces noms, donc un
            # match ne peut désigner qu'une remontée hors de `core`.
            # ⚠️ **Les ALIAS comptent, pas seulement le module.** `from core import acquisition`
            # ne nomme jamais `core.acquisition` dans `noeud.module` — il y a `core`, autorisé —
            # et l'interdit passerait EN SILENCE. Or `from X import Y` est l'idiome dominant de ce
            # dépôt : c'est « la faute plausible, celle qu'on écrit sans y penser ». Deux règles
            # en dépendent : « rien dans `research` n'ouvre le casque », et l'invariant fondateur
            # de `stimulus/` (une fenêtre qui ouvrirait le casque volerait sa connexion au moteur
            # en séance).
            base = noeud.module or ""
            # Le PAQUET se juge sur le module seul — sinon `from console.grid import Grille`
            # compterait deux fois la même faute. Les formes complètes servent aux `exacts`.
            cibles = [base]
            formes = [base] + [f"{base}.{alias.name}" if base else alias.name
                               for alias in noeud.names]
        else:
            continue
        for cible in cibles:
            paquet = cible.split(".")[0]
            if motif.match(paquet):
                fautes.append((noeud.lineno, paquet))
            else:
                # Un module PRÉCIS, pas un paquet entier : `core.acquisition` est interdit dans
                # `stimulus/` alors que `core` y est autorisé. On rend la forme COMPLÈTE qui a
                # matché — `core.acquisition`, pas `core` — pour que le message dise ce qui est
                # interdit et pas seulement où. C'est aussi ce qui permet d'attraper
                # `from core import acquisition`, dont le module seul (`core`) est autorisé.
                touchees = [f for f in formes
                            for m in (exacts or ()) if f == m or f.startswith(m + ".")]
                if touchees:
                    fautes.append((noeud.lineno, touchees[0]))
    return fautes


PAQUETS_REQUIS = ("core", "stimulus", "console")
PAQUETS_CONNUS = PAQUETS_REQUIS + ("research",)


def paquets_de_src(racine):
    """Compare les dossiers de `racine` (le dossier `src/`) aux quatre paquets connus.

    Rend `(manquants, inconnus, presents)`, trois listes triées :
    - `manquants` : un paquet obligatoire (`core`, `stimulus`, `console`) est absent ;
    - `inconnus` : un dossier qui n'est pas l'un des quatre paquets ; un paquet renommé
      échapperait sinon à sa règle d'import ;
    - `presents` : les paquets connus trouvés. `research` est facultatif : la copie publique
      ne l'a pas.
    Ne comptent pas : un fichier `.py` directement dans `src/` (ce n'est pas un paquet), et les
    dossiers que des outils déposent (`__pycache__`, un nom qui commence par un point comme
    `.mypy_cache`, un `*.egg-info`) : aucun ne contient du code du projet.
    """
    def _outil(nom):
        return nom == "__pycache__" or nom.startswith(".") or nom.endswith(".egg-info")

    dossiers = sorted(n for n in os.listdir(racine)
                      if os.path.isdir(os.path.join(racine, n)) and not _outil(n))
    presents = [n for n in dossiers if n in PAQUETS_CONNUS]
    inconnus = [n for n in dossiers if n not in PAQUETS_CONNUS]
    manquants = [n for n in PAQUETS_REQUIS if n not in dossiers]
    return manquants, inconnus, presents


def _smoke_frontiere():
    """`core` n'importe ni `research`, ni `console`, ni pygame, NI QT.

    La règle est vérifiable, c'est tout son intérêt : un module est dans `core` si et seulement
    si `server.py` en a besoin pour tourner, et le moteur doit tourner sur une machine sans
    écran. Le jour où un import de `research` devient nécessaire, ce n'est pas ce test qu'il
    faut assouplir — c'est le module visé qui doit DÉMÉNAGER dans `core`.

    ⚠️ La règle vérifiée doit couvrir Qt (« ni pygame **ni Qt** dans core »), pas seulement
    `research|console|pygame` : Qt n'arrive PAS dans `core` par le paquet `console`, il arrive
    par son propre nom. Un import de PySide6 glissé dans un utilitaire du moteur le ferait mourir
    sur un `ImportError` au démarrage, sur toute machine sans Qt (installation minimale, poste de
    TP, CI sans libGL), alors que son contrat est de tourner sans écran.

    ⚠️ Les quatre paquets sont scannés, chacun avec sa liste : `console -> research` ET
    `research -> console` doivent échouer, comme les deux autres flèches du tableau.

    La détection elle-même vit dans `_imports_interdits` (voir sa docstring pour ce qui lui
    échappe). Ce test l'applique à tout `src/core/**/*.py`, `src/stimulus/`, le paquet `research` et
    `src/console/`, ET la met à l'épreuve sur des extraits fabriqués — sans quoi une garde muette
    (motif vidé, parcours cassé) rendrait « 0 violation » et passerait pour un succès. Chaque
    dossier est de plus vérifié PRÉSENT et NON VIDE, pour la même raison.
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
        # `stimulus` est interdit dans `core` au même titre que `research` et `console` : le
        # moteur tourne sans écran, et une fenêtre de stimulus est du pygame. Sans ces deux
        # lignes, la règle ÉCRITE serait plus large que la règle VÉRIFIÉE.
        ("from stimulus.registry import commande\n", ["stimulus"]),
        ("import stimulus.p300\n", ["stimulus"]),
    ]
    for source, attendu in fabrique:
        trouve = [paquet for _ligne, paquet in _imports_interdits(source)]
        chk(trouve == attendu,
            f"« {source.strip().splitlines()[0][:52]} » -> {trouve or 'rien'} "
            f"(attendu {attendu or 'rien'})")

    def _scanner(racine_dir, etiquette, interdits, interdits_re, exacts=None):
        """Applique la garde à tout un arbre. Rend (violations, fichiers scannés)."""
        trouvees, vus = [], 0
        for dossier, _sous, fichiers in os.walk(racine_dir):
            if "__pycache__" in dossier:
                continue
            for nom in fichiers:
                if not nom.endswith(".py"):
                    continue
                chemin = os.path.join(dossier, nom)
                rel = os.path.relpath(chemin, racine_dir)
                vus += 1
                with open(chemin, encoding="utf-8") as f:
                    for ligne, paquet in _imports_interdits(f.read(), rel, interdits=interdits,
                                                            interdits_re=interdits_re,
                                                            exacts=exacts):
                        trouvees.append(f"{etiquette}/{rel}:{ligne} importe {paquet}")
        return trouvees, vus

    # 1 bis. La règle du paquet `stimulus`, sur des extraits fabriqués eux aussi. Elle diffère de
    # celle de `core` par les deux bouts : `pygame` y est AUTORISÉ (une fenêtre de stimulus est du
    # pygame), et `core.acquisition` y est INTERDIT alors que `core` ne l'est pas. Ce second point
    # est l'invariant fondateur du paquet — *une fenêtre n'ouvre JAMAIS le casque* — qui autorise
    # le montage à deux programmes : l'Unicorn n'accepte qu'une connexion.
    for source, attendu in (
            ("from core.acquisition import UnicornAcquisition\n", ["core.acquisition"]),
            ("import core.acquisition as acq\n", ["core.acquisition"]),
            ("import brainflow\n", ["brainflow"]),
            ("from brainflow.board_shim import BoardShim\n", ["brainflow"]),
            ("from core.config import DATA_DIR\n", []),          # `core` reste autorisé
            ("import pygame\n", []),                             # et pygame aussi, ici
            ("from core import acquisition\n", ["core.acquisition"]),
            ("from research.ui import App\n", ["research"])):
        trouve = [p for _ligne, p in _imports_interdits(
            source, interdits=_FRONTIERE_STIMULUS_INTERDITS, interdits_re="",
            exacts=_FRONTIERE_STIMULUS_MODULES_INTERDITS)]
        chk(trouve == attendu,
            f"règle stimulus — « {source.strip()} » -> {trouve or 'rien'} "
            f"(attendu {attendu or 'rien'})")

    # 1 ter. La règle de `research`, sur des extraits fabriqués. Elle diffère encore des deux
    # autres : `pygame` y est INTERDIT — le banc d'essai n'affiche AUCUN stimulus, c'est le travail
    # de `stimulus/` — alors qu'il est autorisé là-bas. Calculer, en revanche, reste entièrement
    # libre : c'est tout le métier de `research`.
    for source, attendu in (
            ("from core.acquisition import UnicornAcquisition\n", ["core.acquisition"]),
            # ⚠️ La forme qui passerait en silence sans la lecture des alias, et c'est l'idiome
            # dominant du dépôt : `from X import Y` ne nomme jamais `X.Y` dans `noeud.module`.
            ("from core import acquisition\n", ["core.acquisition"]),
            ("from core import acquisition as acq\n", ["core.acquisition"]),
            ("import pygame\n", ["pygame"]),
            ("import brainflow\n", ["brainflow"]),
            # `research -> console`, interdit lui aussi.
            ("from console.grid import ModeGrid\n", ["console"]),
            ("from core.config import DATA_DIR\n", []),               # calculer reste libre
            ("import numpy as np\n", []),
            ("from stimulus.refresh import measure_refresh\n", [])):  # research -> stimulus, OK
        trouve = [p for _ligne, p in _imports_interdits(
            source, interdits=_FRONTIERE_RESEARCH_INTERDITS, interdits_re="",
            exacts=_FRONTIERE_RESEARCH_MODULES_INTERDITS)]
        chk(trouve == attendu,
            f"règle research — « {source.strip()} » -> {trouve or 'rien'} "
            f"(attendu {attendu or 'rien'})")

    # 1 quater. La règle de `src/console/`, sur des extraits fabriqués. C'est la plus COURTE des
    # quatre — un seul nom interdit — et c'est justement pour ça qu'elle manquait : une liste d'un
    # élément n'a pas l'air d'une règle. Les trois cas autorisés ci-dessous sont aussi importants
    # que le cas interdit : ce sont eux qui disent que `interdits_re=""` est délibéré. La console
    # EST du Qt, et le motif par défaut (`PySide\d+`) la déclarerait fautive de haut en bas.
    for source, attendu in (
            ("from research.ssvep_guided import analyze\n", ["research"]),
            ("import research.itr\n", ["research"]),
            ("def f():\n    from research.mi_compare import charger\n", ["research"]),  # indenté
            ("from core.server import EngineServer\n", []),        # elle est un CLIENT du moteur
            ("from stimulus import registry\n", []),               # elle lance les fenêtres
            ("from PySide6.QtWidgets import QLabel\n", [])):       # …et elle EST du Qt
        trouve = [p for _ligne, p in _imports_interdits(
            source, interdits=_FRONTIERE_CONSOLE_INTERDITS, interdits_re="")]
        chk(trouve == attendu,
            f"règle console — « {source.strip().splitlines()[-1].strip()[:48]} » -> "
            f"{trouve or 'rien'} (attendu {attendu or 'rien'})")

    # 1 bis. La règle des dossiers de `src/`, sur des arbres fabriqués : `research` est facultatif
    #    (copie publique), un dossier inconnu est une faute, un fichier `.py` n'est pas un paquet.
    with tempfile.TemporaryDirectory() as tmp_src:
        def arbre(*noms, fichiers=()):
            dossier = tempfile.mkdtemp(dir=tmp_src)
            for nom in noms:
                os.makedirs(os.path.join(dossier, nom))
            for nom in fichiers:
                open(os.path.join(dossier, nom), "w").close()
            return dossier

        chk(paquets_de_src(arbre("core", "stimulus", "console", "research"))
            == ([], [], ["console", "core", "research", "stimulus"]),
            "arbre complet : rien ne manque, rien d'inconnu")
        chk(paquets_de_src(arbre("core", "stimulus", "console", "__pycache__",
                                 fichiers=("eeg_api_unicorn.py",)))
            == ([], [], ["console", "core", "stimulus"]),
            "sans research (copie publique), avec __pycache__ et un .py à la racine : accepté")
        chk(paquets_de_src(arbre("core", "stimulus", "console", ".mypy_cache", ".ruff_cache",
                                 "eeg_api_unicorn.egg-info"))
            == ([], [], ["console", "core", "stimulus"]),
            "les dossiers déposés par des outils (.mypy_cache, *.egg-info) ne comptent pas")
        chk(paquets_de_src(arbre("core", "stimulus", "console", "bench"))[1] == ["bench"],
            "un dossier src/bench/ est signalé comme inconnu")
        chk(paquets_de_src(arbre("core", "stimulus", "research"))[0] == ["console"],
            "un paquet obligatoire absent est signalé comme manquant")

    # 2. Et maintenant le vrai `src/core/`.
    racine = os.path.dirname(os.path.abspath(__file__))
    fautes, fichiers_vus = _scanner(racine, "core", None, None)

    # 3. Et `src/stimulus/`, avec sa liste à lui (cf. `_FRONTIERE_STIMULUS_INTERDITS`). Le dossier
    #    DOIT exister : sans cette vérification, supprimer le paquet rendrait « 0 violation » et
    #    passerait pour un succès — la garde muette que la partie 1 existe pour éviter.
    racine_stim = os.path.join(os.path.dirname(racine), "stimulus")
    chk(os.path.isdir(racine_stim), f"le paquet src/stimulus/ existe ({racine_stim})")
    if os.path.isdir(racine_stim):
        fautes_stim, vus_stim = _scanner(racine_stim, "stimulus", _FRONTIERE_STIMULUS_INTERDITS,
                                         "", _FRONTIERE_STIMULUS_MODULES_INTERDITS)
        chk(vus_stim >= 4, f"…et il contient au moins les quatre fenêtres ({vus_stim} fichiers)")
        fautes += fautes_stim
        fichiers_vus += vus_stim

    # 4. Le paquet `research` : le banc d'essai ne touche ni au casque ni à un écran. Il est
    #    FACULTATIF : la copie publique n'en a pas. Mais tout dossier de `src/` doit être l'un des
    #    quatre paquets connus, sinon un paquet renommé (renommé en `bench`, par exemple)
    #    désarmerait sa règle en rendant « 0 violation » : une garde muette.
    racine_res = os.path.join(os.path.dirname(racine), "research")
    manquants, inconnus, _presents = paquets_de_src(os.path.dirname(racine))
    chk(not manquants, f"les paquets obligatoires de src/ sont présents (manquants : {manquants})")
    chk(not inconnus,
        f"src/ ne contient que les quatre paquets connus (dossiers inconnus : {inconnus})")
    if not os.path.isdir(racine_res):
        print("[smoke-frontiere] paquet research absent : copie publique, règle non appliquée")
    if os.path.isdir(racine_res):
        fautes_res, vus_res = _scanner(racine_res, "research", _FRONTIERE_RESEARCH_INTERDITS,
                                       "", _FRONTIERE_RESEARCH_MODULES_INTERDITS)
        if fautes_res:
            print("[smoke-frontiere]   → RÈGLE : un utilisateur ne tape pas de commande. Si cette "
                  "capacité lui est destinée, elle doit avoir un chemin dans la console ; sinon "
                  "elle n'a pas sa place dans le produit.")
        chk(vus_res >= 10,
            f"…et il contient bien le banc d'essai ({vus_res} fichiers) — un dossier vidé "
            f"rendrait « 0 violation » sans que la règle ait rien vérifié")
        fautes += fautes_res
        fichiers_vus += vus_res

    # 5. `src/console/` : la console est un client du MOTEUR, pas du banc d'essai. Quatrième et
    #    dernière section — c'est elle qui rend le tableau des quatre flèches
    #    entièrement vérifié, `research -> console` étant fermé par la liste ci-dessus.
    #    Même `chk` d'existence et d'effectif que les sections précédentes : sans eux, supprimer
    #    ou vider le dossier rendrait « 0 violation » et « VERDICT : OK ».
    racine_console = os.path.join(os.path.dirname(racine), "console")
    chk(os.path.isdir(racine_console), f"la console src/console/ existe ({racine_console})")
    if os.path.isdir(racine_console):
        fautes_con, vus_con = _scanner(racine_console, "console", _FRONTIERE_CONSOLE_INTERDITS, "")
        if fautes_con:
            print("[smoke-frontiere]   → RÈGLE : la console importe `core` et `stimulus`, jamais "
                  "`research`. Si cette analyse doit être à portée de clic, elle doit DÉMÉNAGER "
                  "dans `core` ; sinon elle reste une commande de développeur.")
        chk(vus_con >= 10,
            f"…et elle contient bien ses pages ({vus_con} fichiers) — un dossier vidé rendrait "
            f"« 0 violation » sans que la règle ait rien vérifié")
        fautes += fautes_con
        fichiers_vus += vus_con

    for faute in fautes:
        print(f"[smoke-frontiere] ÉCHEC : {faute}")
    print(f"[smoke-frontiere] {fichiers_vus} fichiers scannés, "
          f"{len(fautes)} violation(s) de frontière")
    ok = ok and not fautes
    print(f"[smoke-frontiere] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_version():
    """La version vit à UN seul endroit (`core/version.py`) et `--version` la donne.

    Deux gardes : la CI lit la version avec un motif de ligne, qui doit trouver exactement une
    ligne, et REFUSE de construire si le tag de la version n'est pas `v<VERSION>` (elle ne
    réécrit rien : un tag faux se corrige à la source) ; et `server.py --version` répond avant
    d'ouvrir le casque ou le réseau.
    """
    import subprocess
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.py")
    with open(chemin, encoding="utf-8") as f:
        lignes = f.read().splitlines()
    trouvees = [l for l in lignes if re.match(r'^VERSION = ".*"$', l)]
    chk(len(trouvees) == 1, f"le motif de la CI trouve exactement une ligne dans version.py "
                            f"({len(trouvees)})")
    chk(re.fullmatch(r"\d+\.\d+\.\d+", VERSION) is not None, f"VERSION a la forme X.Y.Z ({VERSION})")
    res = subprocess.run([sys.executable, os.path.abspath(__file__), "--version"],
                         capture_output=True, text=True, timeout=60)
    chk(res.returncode == 0 and VERSION in res.stdout,
        f"server.py --version imprime la version et sort en 0 (code {res.returncode}, "
        f"sortie {res.stdout.strip()!r})")
    print(f"[smoke-version] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_point_entree():
    """Le point d'entrée unique (`src/eeg_api_unicorn.py`) ouvre la console, une fenêtre ou le moteur.

    Chaque cas est joué dans un sous-processus, comme le fera l'exécutable installé : la console
    relance le programme lui-même avec `--fenetre <clé>` pour ouvrir un stimulus. Chaque
    fenêtre est lancée avec `--help` : en quelques secondes, ça prouve que le point d'entrée
    trouve son module, que le module se charge (pygame compris) et lit ses arguments, et que le
    code de sortie remonte. Les autotests complets des fenêtres (`--smoke`) restent les gardes
    de chaque fenêtre ; les rejouer ici allongerait ce smoke de plusieurs minutes.
    """
    import subprocess
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    entree = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "eeg_api_unicorn.py")

    def lancer(*args, delai=120):
        try:
            return subprocess.run([sys.executable, entree, *args], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=delai,
                                  env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(args, -999, "", f"délai de {delai} s dépassé")

    chk(os.path.isfile(entree), f"le point d'entrée existe ({entree})")
    res = lancer("--version", delai=60)
    chk(res.returncode == 0 and VERSION in res.stdout,
        f"--version imprime la version, code 0 (code {res.returncode}, {res.stdout.strip()!r})")
    res = lancer("--verifier-modules", delai=180)
    chk(res.returncode == 0 and "numpy" in res.stdout and "pyntbci" in res.stdout,
        f"--verifier-modules importe tout ce dont le produit a besoin, code 0 "
        f"(code {res.returncode}, {res.stdout.strip().splitlines()[-1:]!r}, {res.stderr[-200:]!r})")
    # …puis charge chaque DLL et fait l'aller-retour d'un modèle de chaque sorte : c'est ce que
    # l'exécutable installé rejoue pour prouver qu'il n'a rien oublié.
    attendues = ("BoardController.dll", "DataHandler.dll", "Unicorn.dll", "lsl.dll",
                 "MI (CSP + LDA)", "MI (FBCSP)", "P300", "ErrP", "c-VEP eCCA", "c-VEP rCCA")
    lignes = [l for l in res.stdout.splitlines() if l.startswith(("bibliothèque ", "modèle "))]
    absentes = [a for a in attendues if not any(a in l for l in lignes)]
    chk(not absentes and len(lignes) == len(attendues),
        f"…une ligne par bibliothèque native et par sorte de modèle "
        f"({len(lignes)} lignes ; absentes : {absentes or 'aucune'})")
    # Une vérification qui ne sait pas échouer ne vérifie rien : un modèle P300 que la relecture
    # refuse doit donner le code 1 et NOMMER le modèle.
    code = ("import sys, runpy; sys.path.insert(0, %r); import core.p300_models as m; "
            "m.charger = lambda chemin: (None, 'refus simulé'); "
            "sys.argv = ['eeg_api_unicorn.py', '--verifier-modules']; "
            "runpy.run_path(%r, run_name='__main__')" % (os.path.dirname(entree), entree))
    try:
        res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=180,
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        code_sortie, erreur = res.returncode, res.stderr
    except subprocess.TimeoutExpired:
        code_sortie, erreur = -999, "délai dépassé"
    chk(code_sortie == 1 and "P300" in erreur and "refus simulé" in erreur,
        f"…et un modèle que la relecture refuse donne le code 1, en le nommant "
        f"(code {code_sortie}, {erreur.strip()[-160:]!r})")
    res = lancer("--fenetre", "inconnue", delai=60)
    chk(res.returncode == 2 and all(cle in res.stderr for cle in ("p300", "errp", "cvep", "ssvep", "mi")),
        f"une fenêtre inconnue : code 2 et les clés connues dans le message "
        f"(code {res.returncode}, {res.stderr.strip()!r})")
    for cle in ("p300", "errp", "cvep", "ssvep", "mi"):
        res = lancer("--fenetre", cle, "--help", delai=60)
        chk(res.returncode == 0 and "usage" in res.stdout.lower(),
            f"--fenetre {cle} --help : la fenêtre se charge par le point d'entrée et lit ses "
            f"arguments, code 0 (code {res.returncode}, "
            f"{(res.stdout + res.stderr).strip()[-160:]!r})")
    res = lancer("--serveur", "--version", delai=60)
    chk(res.returncode == 0 and VERSION in res.stdout,
        f"--serveur --version atteint le moteur, code 0 (code {res.returncode}, "
        f"{res.stdout.strip()!r})")
    print(f"[smoke-point-entree] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_journal():
    """Le JOURNAL de l'exécutable sans terminal (`rediriger_vers_journal`, dans le point d'entrée).

    Lancé par son raccourci, `EEG API Unicorn.exe` n'a pas de sortie (`sys.stdout is None`) : sans
    journal, l'erreur qui arrête le moteur serait perdue. Chaque essai tourne dans son propre
    sous-processus, parce que la redirection remplace les sorties du processus entier. Tout
    s'écrit dans un dossier temporaire, jamais dans les Documents de l'utilisateur.
    """
    import subprocess
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def jouer(code, empaquete=False):
        """Lance `code` après `import eeg_api_unicorn as e` ; rend (code de sortie, sortie)."""
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        env.pop("EEG_API_EMPAQUETE", None)
        if empaquete:
            env["EEG_API_EMPAQUETE"] = "1"
        prologue = "import sys; sys.path.insert(0, %r); import eeg_api_unicorn as e\n" % src
        try:
            res = subprocess.run([sys.executable, "-c", prologue + code], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=60,
                                 env=env)
            return res.returncode, res.stdout + res.stderr
        except subprocess.TimeoutExpired:
            return -999, "délai de 60 s dépassé"

    def lire(chemin):
        if not os.path.isfile(chemin):
            return None
        with open(chemin, encoding="utf-8") as f:
            return f.read()

    with tempfile.TemporaryDirectory() as tmp:
        dossier = os.path.join(tmp, "journaux")
        journal = os.path.join(dossier, "console.log")
        precedent = os.path.join(dossier, "console.precedent.log")

        # 1. Premier lancement : le dossier n'existe pas encore. Ce qui s'écrit APRÈS la
        #    redirection (sortie standard ET sortie d'erreur) arrive dans le journal, pas au
        #    terminal.
        code = ("chemin = e.rediriger_vers_journal(%r)\n"
                "print('lancement-1 é', chemin)\n"
                "print('erreur-1', file=sys.stderr)\n" % dossier)
        sortie_code, sortie = jouer(code)
        texte = lire(journal) or ""
        chk(sortie_code == 0 and "lancement-1 é" in texte and "erreur-1" in texte,
            f"1er lancement : le dossier est créé, la sortie et les erreurs vont dans le journal "
            f"(code {sortie_code}, journal {texte.strip()!r})")
        chk(journal in texte, "…et la fonction rend le chemin du journal")
        chk("lancement-1" not in sortie and "erreur-1" not in sortie,
            f"…et plus rien n'arrive au terminal ({sortie.strip()[-120:]!r})")

        # 2. Second lancement : le journal du premier devient `console.precedent.log`.
        sortie_code, sortie = jouer("e.rediriger_vers_journal(%r)\nprint('lancement-2')\n" % dossier)
        texte, texte_precedent = lire(journal) or "", lire(precedent) or ""
        chk(sortie_code == 0 and "lancement-2" in texte and "lancement-1" not in texte,
            f"2e lancement : un journal neuf ({texte.strip()!r})")
        chk("lancement-1" in texte_precedent,
            f"…et celui d'avant est gardé sous console.precedent.log ({texte_precedent.strip()!r})")

        # 3. Un dossier qu'on ne peut pas créer (son parent est un FICHIER) : la fonction rend
        #    None, les sorties restent celles d'avant, et le programme continue.
        bloque = os.path.join(tmp, "un_fichier")
        open(bloque, "w").close()
        code = ("avant = sys.stdout\n"
                "chemin = e.rediriger_vers_journal(%r)\n"
                "print('dossier impossible :', chemin, sys.stdout is avant)\n"
                % os.path.join(bloque, "journaux"))
        sortie_code, sortie = jouer(code)
        chk(sortie_code == 0 and "dossier impossible : None True" in sortie,
            f"un dossier impossible à créer : None, et les sorties ne changent pas "
            f"(code {sortie_code}, {sortie.strip()[-120:]!r})")

        # 4. Le branchement dans `main()`. Installé (EEG_API_EMPAQUETE=1) et SANS sortie, comme
        #    l'exécutable lancé par son raccourci : `--version` s'écrit dans le journal, et
        #    `config.journal_actif` (ce que la console cite) est ce fichier-là.
        dossier_main = os.path.join(tmp, "main")
        code = ("from core import config\n"
                "config.JOURNAUX_DIR = %r\n"
                "sys.stdout = sys.stderr = None\n"
                "e.main(['--version'])\n"
                "sys.__stdout__.write('journal_actif=%%s\\n' %% config.journal_actif)\n"
                % dossier_main)
        sortie_code, sortie = jouer(code, empaquete=True)
        journal_main = os.path.join(dossier_main, "console.log")
        texte = lire(journal_main) or ""
        chk(sortie_code == 0 and VERSION in texte,
            f"installé et sans sortie : --version s'écrit dans le journal "
            f"(code {sortie_code}, journal {texte.strip()!r}, {sortie.strip()[-120:]!r})")
        chk(f"journal_actif={journal_main}" in sortie,
            f"…et config.journal_actif est ce journal ({sortie.strip()[-120:]!r})")

        # 5. Installé AVEC une sortie (l'exécutable en mode console, celui des fenêtres de
        #    stimulus) : rien n'est redirigé. La console lit ce que la fenêtre écrit : un journal
        #    le lui cacherait.
        dossier_cli = os.path.join(tmp, "cli")
        code = ("from core import config\n"
                "config.JOURNAUX_DIR = %r\n"
                "e.main(['--version'])\n"
                "print('journal_actif=%%s' %% config.journal_actif)\n" % dossier_cli)
        sortie_code, sortie = jouer(code, empaquete=True)
        chk(sortie_code == 0 and VERSION in sortie and "journal_actif=None" in sortie
            and not os.path.exists(dossier_cli),
            f"installé avec une sortie (mode console) : rien n'est redirigé "
            f"(code {sortie_code}, {sortie.strip()[-120:]!r})")
    print(f"[smoke-journal] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_chemins():
    """Où vivent les modèles et les séances : dans le dépôt depuis les sources, dans les
    Documents de l'utilisateur une fois installé.

    Le cas « installé » est joué dans un sous-processus avec `EEG_API_EMPAQUETE=1` (sans
    exécutable PyInstaller). On vérifie aussi que l'import de `config` ne crée aucun dossier.
    """
    import subprocess

    from core import config
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    def meme(a, b):
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))

    def sous(chemin, dossier):
        chemin = os.path.normcase(os.path.abspath(chemin))
        dossier = os.path.normcase(os.path.abspath(dossier))
        return chemin == dossier or chemin.startswith(dossier + os.sep)

    chk(not config.empaquete(), "depuis les sources, le programme n'est pas « installé »")
    chk(meme(config.DATA_DIR, os.path.join(config.PROJECT_ROOT, "data")),
        f"depuis les sources, DATA_DIR est <dépôt>/data ({config.DATA_DIR})")
    chk(meme(config.SEANCES_DIR, os.path.join(config.PROJECT_ROOT, "seances")),
        f"depuis les sources, SEANCES_DIR est <dépôt>/seances ({config.SEANCES_DIR})")
    chk(config.JOURNAUX_DIR is None,
        f"depuis les sources, pas de dossier de journaux : les messages vont au terminal "
        f"({config.JOURNAUX_DIR})")

    documents = config.dossier_documents()
    chk(os.path.isdir(documents), f"le dossier Documents existe ({documents})")
    racine_donnees = os.path.join(documents, "EEG API Unicorn")
    existait = os.path.exists(racine_donnees)

    code = ("import sys, json; sys.path.insert(0, %r); from core import config; "
            "print(json.dumps([config.empaquete(), config.DATA_DIR, config.SEANCES_DIR, "
            "config.JOURNAUX_DIR]))"
            % os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env = dict(os.environ, EEG_API_EMPAQUETE="1")
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         timeout=60, env=env)
    try:
        installe, data_dir, seances_dir, journaux_dir = json.loads(
            res.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        installe, data_dir, seances_dir, journaux_dir = False, "", "", ""
        print(f"  sortie du sous-processus illisible : {res.stdout!r} {res.stderr[-300:]!r}")
    chk(installe, "avec EEG_API_EMPAQUETE=1, le programme se dit « installé »")
    chk(meme(data_dir, os.path.join(racine_donnees, "modeles")),
        f"installé, DATA_DIR est Documents/EEG API Unicorn/modeles ({data_dir})")
    chk(meme(seances_dir, os.path.join(racine_donnees, "seances")),
        f"installé, SEANCES_DIR est Documents/EEG API Unicorn/seances ({seances_dir})")
    chk(journaux_dir and meme(journaux_dir, os.path.join(racine_donnees, "journaux")),
        f"installé, JOURNAUX_DIR est Documents/EEG API Unicorn/journaux ({journaux_dir})")
    interdits = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.path.dirname(os.path.abspath(sys.executable))]
    chk(data_dir and seances_dir and journaux_dir
        and not any(sous(d, i) for d in (data_dir, seances_dir, journaux_dir) for i in interdits),
        "installé, rien n'est sous Program Files ni sous le dossier de l'exécutable")
    chk(os.path.exists(racine_donnees) == existait,
        "l'import de config n'a rien créé dans les Documents")
    print(f"[smoke-chemins] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_textes():
    """Aucun texte affiché n'est écrit en dur : tout passe par `tr()` et `langues/<langue>/`.

    La règle existe pour pouvoir ajouter des langues. Même idiome que la frontière : elle est
    tenue par un test, pas par la discipline. `core.i18n.controle` refuse une clé qui
    n'existe pas, une clé calculée, des `{valeurs}` qui ne correspondent pas au texte, un texte
    que plus rien n'affiche, une autre langue qui diverge du français — et tout texte passé EN DUR
    à un widget de la console.

    ⚠️ Le scanner des widgets ne voit que la console, et que les appels Qt directs : un texte en
    dur qui passerait par une fonction intermédiaire, ou un texte du moteur écrit sans `tr`, lui
    échappe. C'est la relecture qui les tient — ce test ferme la porte la plus large, pas toutes.
    """
    from core import i18n

    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fautes = i18n.controle(racine)
    for faute in fautes:
        print(f"  ÉCHEC {faute}")
    n_cles = len(i18n.catalogue(i18n.LANGUE_DEFAUT))
    n_appels = len(i18n.appels_tr(racine))
    # Des compteurs VISIBLES : « 0 faute » sur un catalogue vide ou sans un seul appel ne voudrait
    # rien dire — la garde muette que `[smoke-frontiere]` rend visible de la même façon.
    ok = not fautes and n_cles > 0 and n_appels > 0
    print(f"[smoke-textes] {n_cles} textes en français, {n_appels} appels à tr(), "
          f"{len(fautes)} faute(s)")
    print(f"[smoke-textes] VERDICT : {'OK' if ok else 'ÉCHEC'}")
    return ok


def _smoke_exemples():
    """`examples/` et `clients/` ne nomment aucun flux que le moteur ne publie plus.

    ⚠️ Ce sont les deux endroits du dépôt qui montrent comment CONSOMMER le produit. Un exemple
    qui nomme un flux disparu ne lève rien : `resolve_byprop` attend, puis rend une liste vide, et
    l'utilisateur conclut que le moteur ne publie pas — alors qu'il publie sous un autre nom.

    La panne la plus probable est un renommage : c'est le registre des modes qui décide des
    suffixes, et rien ne le relie à ces fichiers. Ce test fait ce lien, et rien de plus — il ne
    lance ni LSL, ni moteur, ni Unity (le bout en bout des clients : `outils/tester_clients.py`).

    Ne sont cherchés que les noms COMPLETS (`EEG_API_Unicorn_…`) et les suffixes `decoded_…` :
    « raw », « quality » et « status » sont des mots trop courants pour être scannés en prose sans
    fabriquer des faux positifs, et ce sont aussi les trois seuls qui ne peuvent pas disparaître.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # Ce que le moteur publie VRAIMENT, calculé depuis le registre — jamais recopié ici. Plus les
    # deux flux du pilotage, pris aux constantes de `lsl_io` : `control`, que l'application crée,
    # et `replies`, où le moteur répond.
    prefixe = stream_name("")
    pilotage = {nom[len(prefixe):] for nom in (NOM_FLUX_COMMANDES, NOM_FLUX_REPONSES)
                if nom.startswith(prefixe)}
    suffixes = ({spec.stream for spec in registry.MODES if spec.stream}
                | {"quality", "status"} | pilotage)
    chk(len(pilotage) == 2,
        f"les deux flux du pilotage sont connus ({', '.join(sorted(pilotage)) or 'aucun'})")
    chk(len(suffixes) >= 10,
        f"le registre donne les suffixes publiés ({len(suffixes)} : {', '.join(sorted(suffixes))})")

    motif = re.compile(rf"(?:{re.escape(STREAM_PREFIX)}_|\b)(decoded_[a-z0-9_]+|"
                       rf"(?<={re.escape(STREAM_PREFIX)}_)[a-z0-9_]+)")
    depot = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    racine = os.path.join(depot, "examples")
    # `clients/` aussi : les bibliothèques prêtes à l'emploi, dans tous les langages du dépôt.
    racines = (racine, os.path.join(depot, "clients"))
    extensions = (".py", ".cs", ".md", ".m", ".h", ".cpp", ".ino", ".json", ".yaml")

    fautes, vus, cites = [], {}, set()
    for dossier_lu in racines:
        chk(os.path.isdir(dossier_lu), f"le dossier {os.path.basename(dossier_lu)}/ existe")
        vus[dossier_lu] = 0
        for dossier, _sous, fichiers in os.walk(dossier_lu):
            if "__pycache__" in dossier:
                continue
            for nom in sorted(fichiers):
                if not nom.lower().endswith(extensions):
                    continue
                chemin = os.path.join(dossier, nom)
                vus[dossier_lu] += 1
                rel = os.path.relpath(chemin, depot).replace("\\", "/")
                with open(chemin, encoding="utf-8") as f:
                    for no, ligne in enumerate(f, 1):
                        for suffixe in motif.findall(ligne):
                            # Un PRÉFIXE de noms publiés (`…_decoded_` + le mode) n'est pas un flux.
                            if suffixe.endswith("_") and any(s.startswith(suffixe)
                                                             for s in suffixes):
                                continue
                            cites.add(suffixe)
                            if suffixe not in suffixes:
                                fautes.append(f"{rel}:{no} nomme le flux « {suffixe} », que le "
                                              f"moteur ne publie pas")
    # Un dossier vidé — ou une extension oubliée — rendrait « 0 faute » sans avoir rien lu. Même
    # garde muette que les quatre sections de `_smoke_frontiere`, pour la même raison.
    for dossier_lu, n in vus.items():
        chk(n >= 4, f"…{os.path.basename(dossier_lu)}/ contient bien des fichiers ({n} lus)")
    vus = sum(vus.values())
    chk(len(cites) >= 5,
        f"…dont {len(cites)} nom(s) de flux effectivement trouvé(s) : un motif cassé ne doit pas "
        f"passer pour « aucune faute » ({', '.join(sorted(cites)) or 'aucun'})")

    for faute in fautes:
        print(f"[smoke-exemples] ÉCHEC : {faute}")
    if fautes:
        print("[smoke-exemples]   → RÈGLE : les suffixes viennent du registre des modes. Si un "
              "mode a été renommé, l'exemple qui le consomme se renomme avec lui — sinon "
              "`resolve_byprop` attend un flux qui n'existe plus, sans jamais lever.")
    ok = ok and not fautes
    print(f"[smoke-exemples] {vus} fichier(s), {len(cites)} nom(s) de flux, {len(fautes)} faute(s)")

    # Le guide d'intégration (docs/guide/) montre les fichiers de configuration des clients : ils
    # sont recopiés par `outils/construire_guide.py`, jamais tapés à la main. Un fichier modifié
    # sans relancer ce script laisserait au lecteur une configuration qui n'est plus celle que le
    # client lit : on le vérifie ici.
    import subprocess
    script = os.path.join(os.path.dirname(racine), "outils", "construire_guide.py")
    verif = subprocess.run([sys.executable, script, "--verifier"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    for ligne in verif.stdout.splitlines():
        print(f"  {ligne}")
    chk(verif.returncode == 0,
        "les fichiers montrés par le guide (docs/guide/) sont ceux du dépôt — sinon : "
        "python outils/construire_guide.py")
    print(f"[smoke-exemples] VERDICT : {'OK' if ok else 'PROBLÈME'}")
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
    # ⚠️ Assertion FAIBLE : SSVEP_WARMUP_S == NEURO_WARMUP_S == 15.0, donc cette égalité passerait
    # MÊME SI le partage de la chauffe était cassé (chacun garderait sa propre chauffe, qui vaut
    # 15 s des deux côtés par coïncidence). Elle documente le comportement attendu sur les VRAIS
    # modes ; c'est la partie 1b, sur des contrats fabriqués à valeurs distinctes, qui prouve la
    # règle « chauffe = maximum ».
    chk(a._warmup_s == b._warmup_s == max(ssvep.rest.warmup_s, neuro.rest.warmup_s),
        f"une seule chauffe, la plus longue ({a._warmup_s:g} s)")
    chk(server.rest_instruction == neuro.rest.instruction,
        f"la consigne est celle du repos le plus long — « {server.rest_instruction[:40]}… »")
    publiee = server._state(True, calibration=None).get("instruction")
    chk(publiee == catalogue("en")["mode.neuro.repos"],
        f"le flux `status` publie la consigne en ANGLAIS, quelle que soit la langue de l'écran "
        f"— « {publiee} »")
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
    # SSVEP_WARMUP_S et NEURO_WARMUP_S valent tous deux 15 s, donc l'égalité vérifiée ci-dessus
    # passerait même si le partage était cassé. On la prouve sur des contrats FABRIQUÉS, aux
    # valeurs distinctes — valables même si l'une des deux constantes bouge.
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
    # Même cleanup que les trois autres blocs. Ici `_begin_shared_rest` est appelée DIRECTEMENT
    # (pas via `_start`), donc `a`/`b` ne sont jamais entrés dans `faux.active` : ce bloc est un
    # no-op en pratique, sans cycle formé. On le garde pour que le motif reste identique, y
    # compris si ce test évolue vers `_start`.
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

    ack = server.submit("propose_params", id="ssvep", key="alpha_hz")
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
    ack5 = server.submit("propose_params", id="ssvep", key="alpha_hz",
                         params={"refresh_hz": 144.0})
    chk(ack5.get("accepted") and len(ack5.get("value") or []) == 3,
        f"proposer avec un refresh en cours d'édition rend 3 cibles ({ack5.get('value')})")
    chk(all(abs(144.0 / f - round(144.0 / f)) < TOLERANCE_DIVISEUR for f in ack5["value"]),
        f"et ce sont des diviseurs de 144 Hz, pas de 60 ({ack5.get('value')})")
    ack6 = server.submit("set_params", id="ssvep",
                         params={"freqs": ack5["value"], "refresh_hz": 144.0})
    chk(ack6.get("accepted"),
        f"et le jeu proposé pour 144 Hz est accepté avec refresh_hz=144 ({ack6})")

    # --- 🔴 RÉGLER UN MODE AVANT DE LE DÉMARRER --------------------------------------------
    #
    # `set_params` et `propose_params`, les deux moitiés du même geste, doivent accepter l'une et
    # l'autre un mode arrêté : sinon le moteur proposerait un jeu de fréquences, le mettrait dans
    # le champ, puis refuserait de l'appliquer. On règle EN AMONT : on cale ses fréquences sur son
    # écran, son pic alpha sur sa tête, puis on lance — sans démarrer sur des réglages faux, subir
    # les 23 s de repos, corriger et refaire le repos.
    libre = EngineServer(synthetic=True, modes=("raw",), instance="smoke-reglage-amont")
    chk("ssvep" not in libre.active, "un moteur dont le SSVEP n'est PAS démarré")
    refus_amont = libre.submit("set_params", id="ssvep", params={"freqs": [15.0, 17.0]})
    chk(not refus_amont.get("accepted") and "diviseur" in (refus_amont.get("reason") or ""),
        f"…dit quand même ce qui cloche dans les réglages, au lieu de « n'est pas démarré » "
        f"— « {(refus_amont.get('reason') or '')[:70]}… »")
    bon = libre.submit("set_params", id="ssvep", params={"freqs": [12.0, 15.0, 20.0]})
    chk(bon.get("accepted") and bon.get("differe") is True,
        f"…un réglage valide est RETENU, et l'accusé dit qu'il est DIFFÉRÉ — sans ce drapeau, "
        f"l'écran annoncerait « appliqué » sur un mode qui ne décode rien ({bon})")
    # ⚠️ Par `submit` PUIS `_drain_commands`, le vrai chemin — pas `_start` appelé à la main avec
    # des valeurs qu'on aurait composées ici. C'est dans `submit("start_mode")` que le magasin est
    # relu, donc un `_start` direct court-circuiterait exactement ce qu'on veut prouver.
    libre.submit("start_mode", ids=["ssvep"])
    libre._drain_commands()
    chk(tuple(libre.active["ssvep"].params["freqs"]) == (12.0, 15.0, 20.0),
        f"…et le démarrage part AVEC, sans que personne ne les repasse "
        f"({libre.active['ssvep'].params['freqs']})")
    # Un réglage pris EN ROUTE doit survivre à un arrêt/redémarrage, sans quoi les réglages
    # d'avant reviendraient par-dessus ceux qu'on vient d'appliquer.
    libre.submit("set_params", id="ssvep", params={"freqs": [10.0, 20.0]})
    libre._drain_commands()
    libre.submit("stop_mode", id="ssvep")
    libre._drain_commands()
    libre.submit("start_mode", ids=["ssvep"])
    libre._drain_commands()
    chk(tuple(libre.active["ssvep"].params["freqs"]) == (10.0, 20.0),
        f"…et un réglage pris EN ROUTE survit à un arrêt/redémarrage, au lieu de laisser "
        f"revenir celui d'avant ({libre.active['ssvep'].params['freqs']})")
    # La SECONDE écriture du magasin : `start_mode` peut porter ses propres réglages (c'est le
    # chemin d'un client LSL, et celui de `--mode` en ligne de commande). Sans elle, ces
    # réglages-là ne survivraient pas au premier arrêt.
    libre.submit("stop_mode", id="ssvep")
    libre._drain_commands()
    libre.submit("start_mode", ids=["ssvep"], params={"ssvep": {"freqs": [12.0, 30.0]}})
    libre._drain_commands()
    libre.submit("stop_mode", id="ssvep")
    libre._drain_commands()
    libre.submit("start_mode", ids=["ssvep"])
    libre._drain_commands()
    chk(tuple(libre.active["ssvep"].params["freqs"]) == (12.0, 30.0),
        f"…et des réglages portés par « start_mode » lui-même survivent aussi "
        f"({libre.active['ssvep'].params['freqs']})")
    mort = libre.submit("set_params", id="bogus", params={})
    chk(not mort.get("accepted") and "inconnu" in (mort.get("reason") or ""),
        f"…un mode inconnu reste refusé en le nommant ({(mort.get('reason') or '')[:50]})")

    # --- 🔴 LE MAGASIN SE VOIT, ET « PROPOSER » LE LIT ---------------------------------------
    #
    # Deux exigences découlent de ce qu'un réglage peut être retenu sur un mode arrêté.
    #
    # (1) `snapshot()` doit porter les réglages retenus : `modes_state` ne contient que les modes
    #     ACTIFS, donc la page d'un mode arrêté n'aurait aucune source et garderait l'ancienne
    #     valeur à l'écran. Le réglage serait en vigueur et l'écran dirait le contraire — pire
    #     qu'un refus franc.
    libre.submit("stop_mode", id="ssvep")
    libre._drain_commands()
    libre.submit("set_params", id="ssvep", params={"alpha_hz": 11.0})
    vu = (libre.snapshot().get("reglages") or {}).get("ssvep") or {}
    chk(vu.get("alpha_hz") == 11.0,
        f"un réglage retenu sur un mode ARRÊTÉ est PUBLIÉ dans snapshot() — sans quoi l'écran ne "
        f"peut pas le montrer, et dit le contraire de la vérité ({vu.get('alpha_hz')})")
    chk("ssvep" not in (libre.snapshot().get("modes_state") or {}),
        "…et c'est bien le seul endroit où il apparaît : `modes_state` ne porte que les actifs")
    # (2) « Proposer » doit calculer sur le pic qu'on vient d'appliquer, pas sur celui de la
    #     POPULATION (9,6 Hz). Le choix de 11,0 Hz n'est pas neutre : c'est LA valeur qui sépare
    #     les deux réponses. À 9,6 Hz le moteur propose 12 · 15 · 20 ; à 11,0 il garde 8,571, qui
    #     est alors assez loin de l'alpha. Une valeur où les deux jeux coïncident rendrait cette
    #     assertion infalsifiable.
    prop = libre.submit("propose_params", id="ssvep", key="alpha_hz")
    chk(prop.get("accepted") and any(abs(f - 60.0 / 7) < 1e-6 for f in (prop.get("value") or [])),
        f"…et « Proposer » calcule sur CE pic-là, pas sur celui de la population "
        f"({prop.get('value')} — à 9,6 Hz il rendrait 12, 15, 20)")
    libre.close()

    # --- LE STIMULUS D'UN MODE N'EST PAS CELUI DE SA CALIBRATION ----------------------------
    #
    # Deux questions distinctes : « avec quoi décode-t-on » et « avec quoi s'entraîne-t-on ».
    # Elles ont la même réponse pour le P300, l'ErrP et le c-VEP, ce qui peut cacher la
    # différence. Le SSVEP a un stimulus et AUCUNE calibration : le critère « a une calibration »
    # ne suffit donc pas à savoir qu'un mode a un stimulus.
    ssvep_spec = registry.serialize(registry.get("ssvep"))
    chk(ssvep_spec["stimulus_id"] == "ssvep" and ssvep_spec["calibration"] is None,
        f"le SSVEP déclare un stimulus SANS déclarer de calibration — le cas que l'ancien critère "
        f"ne pouvait pas voir ({ssvep_spec['stimulus_id']!r}, calib={ssvep_spec['calibration']})")
    desaccords = [s.id for s in registry.MODES
                  if s.calibration is not None and s.calibration.stimulus_id
                  and s.stimulus_id != s.calibration.stimulus_id]
    chk(not desaccords,
        f"…et là où les DEUX existent, elles désignent la même fenêtre : deux clés qui divergent "
        f"feraient calibrer sur un écran et décoder sur un autre ({desaccords or 'aucun écart'})")
    sans_stimulus = [s.id for s in registry.MODES if s.stimulus_id and not s.stream]
    chk(not sans_stimulus,
        f"…et aucun mode ne déclare un stimulus sans publier de flux ({sans_stimulus or 'aucun'})")

    # --- UN MODE DÉCLARE LA MESURE QUI L'ÉPROUVE -------------------------------------------
    #
    # `test_id` désigne une MESURE du registre, jamais un mode : ce sont deux catalogues distincts,
    # et `registry.check` interdit déjà qu'un même mot serve aux deux. Une clé qui ne désigne rien
    # donnerait un bouton « Tester » qui refuse au clic — c'est-à-dire un bouton cassé, la panne
    # que tout ce projet combat.
    mesures_connues = {m.id for m in registry.MESURES}
    orphelins = [s.id for s in registry.MODES if s.test_id and s.test_id not in mesures_connues]
    chk(not orphelins,
        f"chaque `test_id` déclaré par un mode désigne une mesure du registre "
        f"({orphelins or 'aucun orphelin'})")
    chk("test_id" in registry.serialize(registry.get("ssvep")),
        "…et le contrat SÉRIALISÉ le porte : sans lui la console ne peut pas savoir qui est "
        "testable, et il lui faudrait une liste recopiée")
    # ⚠️ Neuro et Brut n'ont AUCUNE vérité-terrain — il n'y a pas de bonne réponse à comparer.
    # Leur donner un test annoncerait une justesse inventée.
    testables_sans_raison = [s.id for s in registry.MODES if s.test_id and s.family == "brut"]
    chk(not testables_sans_raison,
        f"…et le BRUT n'est pas testable : il ne décide rien, il montre du signal "
        f"({testables_sans_raison or 'aucun'})")

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
    # propositions, jamais leur source (contrairement à `alpha_hz`) : elle ne
    # propose donc jamais rien elle-même.
    ack3 = server.submit("propose_params", id="ssvep", key="freqs")
    chk(not ack3.get("accepted") and "propose" in (ack3.get("reason") or ""),
        f"un réglage qui ne propose rien est refusé ({ack3.get('reason')})")

    # Proposer AVANT d'avoir démarré le mode doit marcher : on se règle puis on lance.
    arrete = EngineServer(synthetic=True, modes=(), instance="smoke-proposition-2")
    ack4 = arrete.submit("propose_params", id="ssvep", key="alpha_hz")
    chk(ack4.get("accepted") and ack4.get("value"),
        f"on peut demander une proposition sur un mode PAS ENCORE démarré ({ack4.get('reason')})")

    # --- 🔴 « PROPOSER » LIT LA BANDE À L'ÉCRAN, SES DEUX COUPURES, ET REFUSE L'ABSURDE ----------
    # Ces gardes sont aussi vérifiées dans `modes/ssvep_mesure.py`. Quatre cibles à 60 Hz, pic alpha par défaut : sous 5-40 Hz le moteur propose
    # 5 · 12 · 20 · 30 — une cible sous 8 Hz ET une au-dessus de 20, ce qui rend les deux
    # coupures observables.
    quatre = [15.0, 20.0, 60.0 / 7, 12.0]

    def proposer(**ecran):
        ack = arrete.submit("propose_params", id="ssvep", key="alpha_hz",
                            params={"freqs": quatre, **ecran})
        return ack, list(ack.get("value") or [])

    retenu = arrete.submit("set_params", id="ssvep", params={"band_high": 20.0})
    _ack, du_magasin = proposer()
    chk(retenu.get("differe") and du_magasin and max(du_magasin) <= 20.0,
        f"(précondition) coupure haute RETENUE à 20 Hz, rien à l'écran : « Proposer » lit le "
        f"magasin ({[round(f, 3) for f in du_magasin]})")
    # (a) Ce qui est à l'écran PRIME sur le magasin — la bande comme le rafraîchissement : la
    #     console envoie tout le formulaire, et c'est lui que l'étudiant regarde.
    _ack, de_l_ecran = proposer(band_high=40.0)
    chk(de_l_ecran and max(de_l_ecran) > 20.0,
        f"la coupure haute À L'ÉCRAN (40 Hz) prime sur celle du magasin (20 Hz) "
        f"({[round(f, 3) for f in de_l_ecran]})")
    chk(min(de_l_ecran or [99.0]) < 8.0,
        f"(précondition) sous une coupure basse à 5 Hz, la proposition descend sous 8 Hz "
        f"({[round(f, 3) for f in de_l_ecran]})")
    # (b) La coupure BASSE compte aussi — et la proposition reste acceptée par « Appliquer ».
    _ack, sous_8 = proposer(band_low=8.0, band_high=40.0)
    applique = arrete.submit("set_params", id="ssvep",
                             params={"freqs": sous_8, "band_low": 8.0, "band_high": 40.0})
    chk(sous_8 and min(sous_8) >= 8.0 and applique.get("accepted"),
        f"la coupure BASSE à l'écran (8 Hz) borne la proposition, et « Appliquer » accepte ce "
        f"qu'elle rend ({[round(f, 3) for f in sous_8]}, {applique.get('reason', 'accepté')})")
    # (c) Une saisie absurde est REFUSÉE, avec la raison d'« Appliquer » — jamais écrêtée en
    #     silence (0 → 5, « ? » → 40, NaN), et jamais une boucle sans fin : un rafraîchissement
    #     infini ferait tourner `available_frequencies` à jamais, sur le fil de l'interface.
    #     D'où le délai : un « Proposer » qui ne rend pas la main est un ROUGE ici,
    #     pas un smoke figé.
    import threading as _threading

    par_cle = {p.key: p for p in registry.get("ssvep").params}
    for saisie in ({"band_low": 0.0}, {"band_high": "?"}, {"band_low": float("nan")},
                   {"refresh_hz": 1e9}, {"refresh_hz": float("nan")}, {"alpha_hz": 50.0},
                   {"refresh_hz": float("inf")}):
        (cle, valeur), = saisie.items()
        boite = {}
        fil = _threading.Thread(target=lambda s=saisie: boite.update(r=proposer(**s)[0]),
                                daemon=True)
        fil.start()
        fil.join(5.0)
        rendu = boite.get("r") or {}
        attendu = contract.valider_un(par_cle[cle], valeur)[1]
        applique = arrete.submit("set_params", id="ssvep", params=saisie)
        vu = ("TOUJOURS EN COURS après 5 s" if fil.is_alive()
              else rendu.get("reason") or rendu.get("value"))
        chk(not fil.is_alive() and not rendu.get("accepted") and attendu
            and rendu.get("reason") == attendu == applique.get("reason"),
            f"« Proposer » avec {saisie} à l'écran rend la main et REFUSE, avec la raison "
            f"d'« Appliquer » ({vu})")

    # --- CIBLES PHYSIQUES (des LED) : pas d'écran, donc pas de diviseurs à respecter ------------
    # 17 Hz ne divise pas 60 : refusé pour un écran, accepté pour des LED, qui clignotent à la
    # fréquence qu'on leur programme.
    trio_17 = [12.0, 17.0, 20.0]
    ecran_17 = arrete.submit("set_params", id="ssvep", params={"targets_on": "screen", "freqs": trio_17})
    led_17 = arrete.submit("set_params", id="ssvep",
                           params={"targets_on": "physical", "freqs": trio_17})
    chk(not ecran_17.get("accepted") and "diviseur entier" in (ecran_17.get("reason") or "")
        and led_17.get("accepted"),
        f"17 Hz : refusé sur un écran à 60 Hz, accepté sur des cibles physiques "
        f"({(ecran_17.get('reason') or 'accepté')[:50]}… / {led_17.get('reason', 'accepté')})")
    _ack, sur_grille = proposer(targets_on="physical", band_low=5.0, band_high=40.0)
    chk(sur_grille and all(abs(f * 2 - round(f * 2)) < 1e-9 for f in sur_grille)
        and any(abs(60.0 / f - round(60.0 / f)) > TOLERANCE_DIVISEUR for f in sur_grille),
        f"« Proposer » sur des cibles physiques choisit au demi-hertz, hors des seuls diviseurs "
        f"de l'écran ({sur_grille})")
    # Les deux « Tester » font clignoter des disques À L'ÉCRAN : avec des LED, le test est refusé,
    # avec la raison du contrat — celle que la console affiche sous ses boutons grisés.
    refuse = arrete.submit("start_mesure", id="ssvep_taux")
    chk(not refuse.get("accepted") and refuse.get("reason") == tr("mode.ssvep.tests_ecran"),
        f"le test SSVEP est refusé sur des cibles physiques ({refuse.get('reason')})")
    retour = arrete.submit("set_params", id="ssvep",
                           params={"targets_on": "screen",
                                   "freqs": list(registry.get("ssvep").defaults()["freqs"])})
    chk(retour.get("accepted")
        and arrete._refus_test_hors_condition(registry.get_mesure("ssvep_taux")) is None,
        f"…et il redevient possible sur un écran ({retour.get('reason', 'accepté')})")
    arrete.close()

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
    # dans ModeRuntime.set_published) : un flux qui refuserait de disparaître serait un défaut
    # SILENCIEUX, invisible à l'étudiant qui l'a coupé.
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
    plus court (piège rencontré sur la calibration MI).

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
    # contre 4 s pour la calibration MI, la plus gourmande — aucune ambiguïté sur
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

    ⚠️ Ce test juge `server.py`, pas BrainFlow. Un vrai board jugé sur 3 s de temps MURAL
    produirait des horodatages que `server.py` se contente de RECOPIER (`clock.to_lsl(ts_unix)`
    du canal TIMESTAMP) : une préemption suivie d'un rattrapage en rafale effondrerait la médiane
    des écarts et ferait rougir un test dont aucune ligne de ce fichier n'est la cause (« cadence
    médiane 0.02 ms attendu 4.00 ms »). La réponse n'est PAS d'élargir la tolérance : un test qui
    juge la mauvaise chose ne devient pas bon en devenant permissif, il devient un test qu'on
    relance jusqu'au vert — donc qu'on apprend à ignorer. Le producteur est donc remplacé par
    `_AcqDeterministe`, et chaque assertion est une question sur `server.py` :

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
    # ligne ne dit rien de la troncature. Le régime plein est exercé plus bas, sur un SECOND
    # moteur.
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
        "le dernier tour de boucle a bien lu un bloc — GARANTI, le producteur en rend à chaque "
        "tour (sans bloc, les trois assertions suivantes ne vérifieraient rien)")
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
    # milliers). Sans les deux `[-self.keep:]` de la boucle, il `vstack` un tableau qui grandit
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
    # suivants, sans même imprimer un verdict. Un marqueur qui échapperait au filtre n'a pas
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

    # Les FRONTIÈRES EXACTES des trois comparaisons : sans elles, chaque test tombe franchement
    # d'un côté ou de l'autre, et passer un `>` en `>=` (ou l'inverse) ne ferait rougir aucune
    # assertion. Ce sont pourtant les trois seules décisions de `markers_murs`, et un marqueur
    # pile à la limite est le cas NORMAL d'un émetteur régulier.
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

    # Et les compteurs SORTENT : `modes/p300.py` les annonce comme le moyen par lequel trois de
    # ses six pannes sont dites, et `docs/markers.md` promet à l'étudiant qu'il les verra grimper.
    # Ils valent 1 et 1 ici (pas 0), donc un `_state()` qui écrirait des zéros en dur ne
    # passerait pas.
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

    Contrôler la MATURITÉ avant le FUTUR (l'ordre inverse de `markers_murs`) a deux défauts d'un
    coup : un marqueur horodaté loin dans le futur n'est par définition jamais
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
    # sûre à instancier telle quelle (comme `_smoke_repos_partage`) — `_open`/`_close`/
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
        srv._mettre_en_file(
            "start_mode", {"ids": ["smoke-ecoute"], "params": {"smoke-ecoute": {}}})

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
    # destructeur zombie (`BOARD_NOT_CREATED_ERROR`). Inoffensif ici
    # seulement parce qu'aucun sous-test ne démarre de board APRÈS celui-ci ; ça ne se remarque
    # pas quand ça cesse d'être vrai, donc on casse le cycle explicitement.
    srv2.active = {}

    print(f"[smoke-marqueurs-inlet] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_inlet_apres_seance():
    """Un test (ou un entraînement) À FENÊTRE qui finit rend l'oreille du moteur.

    Le parcours normal d'une séance : on entraîne et on teste le P300 dans la console — sa fenêtre
    publie sur `EEG_API_Unicorn_stim` —, puis on branche son jeu, qui publie sur SON flux
    (`stream_in`). Si l'inlet ouvert pour la fenêtre survivait au test, `_ouvre_marker_inlet` ne
    recréerait rien : le mode écouterait la fenêtre fermée, muet, pendant que la console montre
    le nom du jeu. Joué dans la VRAIE boucle (`run()`), avec un faux test, un faux inlet et un
    mode fabriqué : seul compte le moment où l'inlet est lâché, puis rouvert sous le bon nom.
    """
    import threading
    import types

    from core.modes import registry as _registry
    from core.modes.contract import ModeSpec
    from core.modes.runtime import ModeRuntime

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _InletDeLaFenetre:
        """Ce que la boucle lit d'un inlet : déjà connecté (à la fenêtre), aucun marqueur."""
        nom = MARKER_STREAM_DEFAULT
        connecte = True
        illisibles = 0
        refus = ""

        def __init__(self):
            self.lache_pour = None

        def resolve(self):
            return True

        def pull(self, max_n=64):
            return []

        def lache(self, raison=""):
            self.lache_pour = raison
            return True

    class _TestQuiFinit:
        """Un test à fenêtre — il lit les marqueurs du P300 — qui finit au premier tour."""
        marker_mode_id = "p300"
        spec = types.SimpleNamespace(id="test_factice", label="Test factice")

        def __init__(self):
            self.terminee = False
            self.params = {}

        def tick(self, engine, now):
            self.terminee = True

        def cancel(self):
            self.terminee = True

    nom_du_jeu = f"MonJeu_smoke_{os.getpid()}"
    ecoute = ModeSpec(id="smoke-jeu", label="Jeu (test)", family="actif", summary="",
                      status="moteur", stream="decoded_smoke_jeu", channels=("x",),
                      marker_epoch_s=0.8, runtime_cls=ModeRuntime)
    srv = EngineServer(synthetic=True, modes=(), params={}, instance="smoke-inlet-apres-seance")
    fenetre = _InletDeLaFenetre()
    srv.marker_inlet = fenetre
    srv.mesure = _TestQuiFinit()
    # Une durée large : c'est `stop()` qui arrête le moteur. Il doit encore tourner au second
    # contrôle, sinon la fin de `run()` lâcherait l'inlet et le premier serait vrai à vide.
    thread = threading.Thread(target=srv.run, kwargs={"duration_s": 60.0}, daemon=True)
    avant_registre = _registry.MODES
    try:
        thread.start()
        echeance = time.time() + 8.0
        while fenetre.lache_pour is None and thread.is_alive() and time.time() < echeance:
            time.sleep(0.05)
        chk(fenetre.lache_pour is not None and thread.is_alive()
            and srv.marker_inlet is not fenetre,
            f"le test fini, la boucle LÂCHE l'inlet de la fenêtre, moteur toujours en marche "
            f"(raison : {fenetre.lache_pour!r}, moteur vivant : {thread.is_alive()})")

        # Le jeu se branche : un mode à marqueurs démarre sur SON flux. La commande part dans la
        # file, comme `submit` ; c'est le fil de `run()` qui l'applique.
        _registry.MODES = avant_registre + (ecoute,)
        srv._mettre_en_file("start_mode", {"ids": [ecoute.id],
                                           "params": {ecoute.id: {"stream_in": nom_du_jeu}}})
        echeance = time.time() + 8.0
        while (getattr(srv.marker_inlet, "nom", None) != nom_du_jeu and thread.is_alive()
               and time.time() < echeance):
            time.sleep(0.05)
        chk(getattr(srv.marker_inlet, "nom", None) == nom_du_jeu,
            f"...et le mode démarré ensuite écoute le flux du JEU, pas celui de la fenêtre "
            f"({getattr(srv.marker_inlet, 'nom', None)!r} pour {nom_du_jeu!r})")
    finally:
        _registry.MODES = avant_registre
        srv.stop()
        thread.join(timeout=10.0)
        srv.retirer_flux()

    print(f"[smoke-inlet-apres-seance] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_marqueurs_relance():
    """L'émetteur meurt, puis REVIENT. Le moteur doit le réentendre tout seul.

    « Je ferme le stimulus et je le relance » est un geste de routine en TP, et la panne est
    silencieuse : si l'inlet n'est re-résolu que `if not connecte`, `connecte` reste `True` à vie,
    et le `recover=True` par défaut de LSL fait attendre indéfiniment le retour de l'ANCIEN
    `source_id` — que l'émetteur de référence déclare par PID, donc qui ne revient jamais. Le
    moteur reste muet, sans exception, `marqueurs_inlet_erreurs` immobile à 0, et redémarrer le
    mode n'y change rien. Avec `recover=False`, la disparition lève `LostError`,
    `MarkerInlet.pull` lâche l'inlet, et la boucle re-résout (mesuré sur deux processus : 51
    marqueurs après relance, contre 0 avec `recover=True`).

    ⚠️ Ce test ne lance PAS deux processus : détruire le `StreamOutlet` côté Python produit
    exactement le même `LostError` côté inlet. Il ne couvre donc PAS la mort BRUTALE d'un
    processus émetteur (Ctrl-C, plantage), où c'est le système qui ferme les sockets ; une sonde à
    deux processus y a montré le même comportement.
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

    # --- B. L'émetteur DISPARAÎT : l'inlet doit redevenir « non connecté ». -----------------
    avant_erreurs = srv.marqueurs_inlet_erreurs
    vu = tourne(srv, 20.0, lambda: not srv.marker_inlet.connecte)
    chk(vu and not srv.marker_inlet.connecte,
        "l'émetteur disparu, l'inlet redevient NON CONNECTÉ — sans quoi le moteur se croit "
        "connecté pour toujours et ne re-résout jamais")
    chk(srv.marqueurs_inlet_erreurs > avant_erreurs,
        f"...et l'incident est COMPTÉ, pas avalé ({srv.marqueurs_inlet_erreurs})")

    # --- C. Un émetteur NEUF (source_id différent, comme un vrai relancement). -------------
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
    # Sans limite : 310 exceptions en 20 s, soit 20 lignes par seconde, qui noient le journal des
    # modes qui tournent à côté. On martèle 50 tours sur un inlet qui échoue toujours
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


def _smoke_magasin_refus_du_runtime():
    """`set_params` sur un mode EN MARCHE écrit le magasin à la soumission, puis la boucle
    RECONSTRUIT le runtime — qui peut refuser (c-VEP : un modèle calibré sur un autre nombre de
    cibles, `_desaccord_code`). Le mode continue alors sur l'ancien réglage : le magasin doit être
    remis dessus, sinon `snapshot()["reglages"]` annonce le nouveau et la console (« le magasin
    d'abord ») lance « Tester » avec ce réglage refusé. Joué sur un mode FABRIQUÉ dont le
    constructeur refuse un gain > 5 : aucun vrai mode ne peut être laissé fautif pour le test.
    """
    from core.modes.contract import ModeSpec, Param
    from core.modes.runtime import ModeRuntime

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _RuntimeExigeant(ModeRuntime):
        def __init__(self, spec, params, engine):
            if float(params.get("gain", 0.0)) > 5.0:
                raise ValueError("ce runtime refuse un gain au-dessus de 5")
            super().__init__(spec, params, engine)

    spec = ModeSpec(id="smoke-magasin", label="Smoke magasin", family="actif", summary="",
                    status="moteur", stream="", channels=("x",), runtime_cls=_RuntimeExigeant,
                    params=(Param("gain", "Gain", "float", default=1.0, min=0.0, max=10.0,
                                  help="refusé par le runtime au-dessus de 5"),))
    vrais = registry.MODES
    registry.MODES = vrais + (spec,)
    registry.BY_ID[spec.id] = spec          # `registry.get` lit cet index, pas `MODES`
    srv = EngineServer(synthetic=True, modes=(), instance="smoke-magasin")
    try:
        srv.active[spec.id] = _RuntimeExigeant(spec, {"gain": 1.0}, srv)
        srv.reglages[spec.id] = {"gain": 1.0}
        ack = srv.submit("set_params", id=spec.id, params={"gain": 8.0})
        chk(ack.get("accepted") and ack.get("differe") is False,
            f"le contrat accepte 8 (dans ses bornes) et la commande part en file ({ack})")
        srv._drain_commands()
        chk(srv.active[spec.id].params.get("gain") == 1.0,
            f"la boucle : le runtime REFUSE, le mode continue sur l'ancien réglage "
            f"({srv.active[spec.id].params})")
        vu = (srv.snapshot().get("reglages") or {}).get(spec.id) or {}
        chk(vu.get("gain") == 1.0,
            f"…et le magasin est REMIS sur ce que le mode fait vraiment — pas sur la valeur "
            f"refusée, que « Tester » relirait ({vu})")
        # Le contrôle qui rend la remise FALSIFIABLE et sûre : un réglage soumis APRÈS le refusé (un
        # second clic, avant que la boucle ne passe) n'est pas écrasé par la remise du premier.
        srv.submit("set_params", id=spec.id, params={"gain": 9.0})
        srv.submit("set_params", id=spec.id, params={"gain": 2.0})
        srv._drain_commands()
        vu = (srv.snapshot().get("reglages") or {}).get(spec.id) or {}
        chk(srv.active[spec.id].params.get("gain") == 2.0 and vu.get("gain") == 2.0,
            f"…mais un réglage ACCEPTÉ soumis juste après n'est pas effacé par cette remise "
            f"(runtime {srv.active[spec.id].params}, magasin {vu})")

        # Le DÉMARRAGE : `start_mode` écrit lui aussi le magasin à la soumission. Le runtime
        # refuse de se construire : le mode reste arrêté, et le magasin reprend ce qu'il portait.
        srv.active.pop(spec.id, None)
        srv.reglages[spec.id] = {"gain": 3.0}
        ack = srv.submit("start_mode", id=spec.id, params={spec.id: {"gain": 7.0}})
        chk(ack.get("accepted") and (srv.reglages.get(spec.id) or {}).get("gain") == 7.0,
            f"`start_mode` avec un gain de 7 : accepté par le contrat, écrit au magasin "
            f"({ack.get('accepted')}, {srv.reglages.get(spec.id)})")
        try:
            srv._drain_commands()
        except Exception:  # noqa: BLE001 - la boucle signale l'échec ; seul l'état compte ici
            pass
        vu = (srv.snapshot().get("reglages") or {}).get(spec.id) or {}
        chk(spec.id not in srv.active and vu.get("gain") == 3.0,
            f"…le runtime REFUSE : le mode reste arrêté, et le magasin REDIT le gain d'avant — pas "
            f"le 7 qui a échoué, que le prochain « Démarrer » referait échouer ({vu})")
    finally:
        registry.MODES = vrais
        registry.BY_ID.pop(spec.id, None)
        srv.active.pop(spec.id, None)
        srv.close()
    print(f"[smoke-magasin] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_marqueurs_stream_in():
    """`stream_in` doit vraiment choisir le flux écouté, pas rester un réglage-décor.

    Si `_ouvre_marker_inlet` avait `MARKER_STREAM_DEFAULT` EN DUR, le réglage « Flux de
    marqueurs » du P300 s'afficherait dans la console, se validerait, se sauvegarderait — et ne
    servirait à RIEN. Ce test utilise des runtimes FABRIQUÉS (`types.SimpleNamespace`) plutôt
    qu'un vrai `P300Runtime`, pour ne pas dépendre d'un modèle entraîné ni d'un mode marqueur
    réel : un futur mode marqueur ne le change pas.
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

    # 4. Un mode marqueur qui NE DÉCLARE PAS `stream_in` compte pour le défaut, pas pour une
    # absence.
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
    # son inlet sur le nom du mode actif — c'est LA méthode qui ne doit pas porter
    # `MARKER_STREAM_DEFAULT` en dur.
    srv2 = EngineServer(synthetic=True, modes=(), params={}, instance="smoke-marqueurs-stream-in-2")
    srv2.active = {"p300": faux_runtime(0.95, stream_in="flux_bout_en_bout")}
    srv2._ouvre_marker_inlet()
    chk(srv2.marker_inlet is not None
        and srv2.marker_inlet.nom == "flux_bout_en_bout",
        f"_ouvre_marker_inlet crée son inlet sur le nom du mode actif, pas le défaut en dur "
        f"({srv2.marker_inlet.nom if srv2.marker_inlet else None})")
    # La QUESTION que la console pose avant un essai libre : quel flux ce mode entendrait-il,
    # et qui tient l'écoute ? Elle suit la MÊME règle que `_ouvre_marker_inlet`.
    dit = srv2.flux_a_ecouter("cvep", {"stream_in": "autre_flux"})
    chk(dit is not None and dit["flux"] == "flux_bout_en_bout" and len(dit["tenu_par"]) == 1,
        f"un mode qui démarrerait maintenant entend le flux DÉJÀ écouté, pas son `stream_in`, et "
        f"la réponse dit qui tient l'écoute ({dit})")
    srv2.active = {}
    dit = srv2.flux_a_ecouter("cvep", {"stream_in": "autre_flux"})
    chk(dit == {"flux": "autre_flux", "tenu_par": []},
        f"...personne ne l'utilise plus : il entendra son propre `stream_in` ({dit})")
    chk(srv2.flux_a_ecouter("ssvep") is None and srv2.flux_a_ecouter("inconnu") is None,
        "...et un mode sans marqueurs (ou inconnu) n'a rien à répondre")

    print(f"[smoke-marqueurs-stream-in] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_stream_in_ouvert():
    """`stream_in` est un choix OUVERT : un nom pas encore vu est accepté, avec un avertissement.

    L'application qui publie ses marqueurs peut ne pas être lancée au moment du réglage. Avant,
    le moteur refusait le nom (ou l'écrasait en silence par le défaut). Le test ne dépend pas de
    `data/` : la liste des modèles est remplacée par un faux chemin le temps du test.
    """
    import types

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    spec = registry.get("p300")
    param_modele = next(p for p in spec.params if p.key == "model")
    ancien = param_modele.choices_fn
    object.__setattr__(param_modele, "choices_fn", lambda: ("faux_modele.joblib",))
    try:
        srv = EngineServer(synthetic=True, modes=(), params={}, instance="smoke-stream-in-ouvert")

        # 1. Mode ARRÊTÉ : le nom absent est accepté, retenu, et signalé.
        srv.active = {}
        ack = srv.submit("set_params", id="p300", params={"stream_in": "Absent_xyz"})
        chk(ack.get("accepted") and ack.get("differe") is True,
            f"un nom pas encore visible est accepté et différé ({ack})")
        chk("Absent_xyz" in str(ack.get("warning")),
            f"...avec un avertissement qui nomme le flux ({ack.get('warning')!r})")
        # `.get` : un KeyError ici ferait sauter tous les smokes suivants de `_smoke()`.
        chk((srv.reglages.get("p300") or {}).get("stream_in") == "Absent_xyz",
            "...et le nom est RETENU pour le prochain démarrage")

        # 2. Le défaut est toujours visible : aucun avertissement.
        ack = srv.submit("set_params", id="p300", params={"stream_in": MARKER_STREAM_DEFAULT})
        chk(ack.get("accepted") and ack.get("warning") is None,
            f"le flux par défaut n'avertit pas ({ack.get('warning')!r})")

        # 3. Mode qui TOURNE : changer le flux ne prend effet qu'au redémarrage, et le dit.
        rt = types.SimpleNamespace()
        rt.spec = types.SimpleNamespace(marker_epoch_s=0.95)
        rt.params = {"model": "faux_modele.joblib", "stream_in": MARKER_STREAM_DEFAULT}
        srv.active = {"p300": rt}
        ack = srv.submit("set_params", id="p300", params={"stream_in": "Absent_xyz"})
        redemarrage = tr("moteur.reglage.stream_in_au_redemarrage", mode=spec.label)
        chk(ack.get("accepted") and str(redemarrage) in str(ack.get("warning")),
            f"changer le flux d'un mode qui tourne dit « au redémarrage » ({ack.get('warning')!r})")
        chk("Absent_xyz" in str(ack.get("warning")),
            "...et garde l'avertissement « pas encore visible » en plus")
        ack = srv.submit("set_params", id="p300", params={"stream_in": MARKER_STREAM_DEFAULT})
        chk(ack.get("accepted") and ack.get("warning") is None,
            f"sans changement réel de flux, aucun avertissement ({ack.get('warning')!r})")

        # 3 bis. Le nom de référence est celui que le moteur ÉCOUTE (l'inlet), pas la valeur du
        # runtime : la boucle écrit la nouvelle valeur dans le runtime tout de suite, l'inlet
        # reste sur l'ancien nom jusqu'au redémarrage. Renvoyer le même nom doit donc avertir
        # encore ; avec l'ancienne référence, le deuxième envoi se taisait.
        rt.params = {"model": "faux_modele.joblib", "stream_in": MARKER_STREAM_DEFAULT}
        srv.marker_inlet = types.SimpleNamespace(nom="flux_A")
        try:
            ack = srv.submit("set_params", id="p300", params={"stream_in": "flux_B"})
            chk(str(redemarrage) in str(ack.get("warning")),
                f"flux_B alors que l'inlet écoute flux_A : avertit ({ack.get('warning')!r})")
            rt.params["stream_in"] = "flux_B"       # ce que fait la boucle en appliquant
            ack = srv.submit("set_params", id="p300", params={"stream_in": "flux_B"})
            chk(str(redemarrage) in str(ack.get("warning")),
                f"renvoyer flux_B : avertit ENCORE, l'inlet est toujours sur flux_A "
                f"({ack.get('warning')!r})")
            ack = srv.submit("set_params", id="p300", params={"stream_in": "flux_A"})
            chk(str(redemarrage) not in str(ack.get("warning")),
                f"revenir au nom réellement écouté n'avertit pas ({ack.get('warning')!r})")
        finally:
            srv.marker_inlet = None

        # 4. `start_mode` porte le même avertissement.
        srv.active = {}
        ack = srv.submit("start_mode", id="p300", params={"p300": {"stream_in": "Absent_xyz"}})
        chk(ack.get("accepted") and "Absent_xyz" in str(ack.get("warning")),
            f"start_mode avertit aussi d'un flux pas encore visible ({ack})")
        ack = srv.submit("set_params", id="p300", params={"stream_in": ""})
        chk(not ack.get("accepted"), f"un nom vide est refusé ({ack.get('reason')!r})")
    finally:
        object.__setattr__(param_modele, "choices_fn", ancien)

    print(f"[smoke-stream-in-ouvert] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_reseau_moteur():
    """Ce que le moteur garantit à un appelant RÉSEAU : commandes rejouables, commandes qui se
    suivent sans attendre la boucle, modèle par son nom de fichier, échec après acceptation
    signalé.

    Pas de fil : `submit` puis `_drain_commands` jouent un tour de boucle, comme les autres
    smokes. Deux `submit` de suite AVANT le `_drain_commands`, c'est exactement ce que vit une
    application qui attend chaque réponse puis envoie la suivante : la réponse part tout de suite,
    la boucle applique ~50 ms plus tard. Les dossiers de données sont temporaires, et la liste des
    modèles du P300 est remplacée par de faux chemins le temps du test (elle ne dépend jamais de
    `data/`).
    """
    import gc
    import tempfile
    import traceback
    import types

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # Tous les moteurs du test, nettoyés à la fin QUOI QU'IL ARRIVE (cf. le `finally`).
    moteurs = []

    def moteur(instance, tmp, n):
        m = EngineServer(synthetic=True, modes=("raw",), instance=instance,
                         data_dir=os.path.join(tmp, f"data{n}"),
                         seances_dir=os.path.join(tmp, f"seances{n}"))
        moteurs.append(m)
        return m

    def reglage(m, mode_id, cle):
        """Le réglage `cle` du mode qui TOURNE, ou None — jamais un KeyError : une exception ici
        ferait sauter tous les smokes suivants de `_smoke()`."""
        rt = m.active.get(mode_id)
        return None if rt is None else rt.params.get(cle)

    def retenu(m, mode_id, cle):
        """Le réglage `cle` du MAGASIN, ou None."""
        return (m.reglages.get(mode_id) or {}).get(cle)

    with tempfile.TemporaryDirectory() as tmp:
        try:
            srv = moteur("smoke-reseau-moteur", tmp, 1)

            # 1. `start_mode` sur un mode arrêté, puis REJOUÉ sur le mode qui tourne : ses
            #    réglages sont posés, rien n'est refusé, et le runtime n'est PAS recréé (un jeu
            #    qui redémarre perdrait sinon 23 s de repos, et son flux serait recréé).
            ack = srv.submit("start_mode", id="ssvep")
            srv._drain_commands()
            chk(ack.get("accepted") and "ssvep" in srv.active,
                f"start_mode démarre le SSVEP ({ack})")
            chk(ack.get("deja") in (None, []), f"...et ne déclare rien de « déjà » ({ack.get('deja')})")
            chk(isinstance(ack.get("params"), dict)
                and set(ack["params"]) == set(registry.get("ssvep").defaults())
                and ack["params"] == dict(srv.active["ssvep"].params if "ssvep" in srv.active
                                          else {}),
                f"...et l'accusé porte TOUS les réglages avec lesquels le mode tourne "
                f"({sorted(ack.get('params') or {})})")
            avant = srv.active.get("ssvep")
            actuel = reglage(srv, "ssvep", "alpha_hz") or 0.0
            v = 10.2 if abs(actuel - 10.2) > 0.05 else 10.6
            ack = srv.submit("start_mode", id="ssvep", params={"ssvep": {"alpha_hz": v}})
            chk(ack.get("accepted") and ack.get("deja") == ["ssvep"],
                f"start_mode sur un mode qui tourne est ACCEPTÉ et dit « deja » ({ack})")
            srv._drain_commands()
            chk(reglage(srv, "ssvep", "alpha_hz") == v,
                f"...et ses réglages sont posés par le chemin de set_params "
                f"({reglage(srv, 'ssvep', 'alpha_hz')} pour {v})")
            chk(retenu(srv, "ssvep", "alpha_hz") == v, "...et retenus dans le magasin")
            chk(avant is not None and srv.active.get("ssvep") is avant,
                "...sans RECRÉER le runtime : c'est le même objet, le repos déjà mesuré est gardé")
            # Un lot refusé ne change RIEN : ni le magasin, ni la file.
            magasin_avant = dict(srv.reglages.get("ssvep") or {})
            ack = srv.submit("start_mode", id="ssvep", params={"ssvep": {"alpha_hz": -3}})
            chk(not ack.get("accepted"), f"des réglages invalides sont refusés même pour un mode "
                                        f"qui tourne ({ack.get('reason')!r})")
            ack = srv.submit("start_mode", ids=["ssvep", "neuro"],
                             params={"ssvep": {"alpha_hz": 11.0}, "neuro": {"inconnu": 1}})
            chk(not ack.get("accepted") and srv.reglages.get("ssvep") == magasin_avant
                and "neuro" not in srv.reglages and srv._commands.empty(),
                f"un lot dont UN mode est refusé ne change rien : ni le magasin du SSVEP (pourtant "
                f"valide), ni celui du Neuro, ni la file ({ack.get('reason')!r})")
            ack = srv.submit("start_mode", ids=["ssvep", "neuro"])
            srv._drain_commands()
            chk(ack.get("accepted") and ack.get("deja") == ["ssvep"] and "neuro" in srv.active,
                f"un lot mixte démarre l'arrêté et déclare celui qui tournait ({ack.get('deja')})")

            # 2. `stop_mode` sur un mode arrêté : accepté, « deja ». L'arrêt part QUAND MÊME en
            #    file : un `start_mode` accepté peut y attendre son tour (cas b ci-dessous), et
            #    ne rien mettre en file laissait ce mode démarrer après un « déjà arrêté ».
            srv.submit("stop_mode", id="neuro")
            srv._drain_commands()
            chk("neuro" not in srv.active, "stop_mode arrête un mode qui tourne")
            ack = srv.submit("stop_mode", id="neuro")
            chk(ack == {"accepted": True, "command": "stop_mode", "id": "neuro", "deja": True},
                f"stop_mode sur un mode arrêté est accepté avec « deja » ({ack})")
            chk(not srv._commands.empty(), "...et l'arrêt part quand même en file")
            srv._drain_commands()
            chk("neuro" not in srv.active and "neuro" not in srv._en_attente,
                f"...que la boucle applique (rien ne démarre), puis efface de l'attente : un « arrêt "
                f"en attente » oublié ferait répondre « déjà arrêté » à tort ({srv._en_attente})")
            ack = srv.submit("stop_mode", id="inconnu")
            chk(not ack.get("accepted"), "stop_mode d'un mode inconnu reste refusé")

            # 2 bis. Deux commandes de suite, AVANT que la boucle n'applique la première. Chaque
            #    accusé doit dire vrai, et l'état final être celui que la SUITE demande.
            #    (a) arrêter puis démarrer un mode qui tourne : il tourne à la fin, redémarré.
            chk("ssvep" in srv.active, "(a) point de départ : le SSVEP tourne")
            avant = srv.active.get("ssvep")
            a1 = srv.submit("stop_mode", id="ssvep")
            a2 = srv.submit("start_mode", id="ssvep")
            srv._drain_commands()
            chk(a1.get("accepted") and "deja" not in a1 and a2.get("accepted")
                and "deja" not in a2 and srv.active.get("ssvep") is not None
                and srv.active.get("ssvep") is not avant,
                f"(a) stop_mode puis start_mode : le SSVEP finit EN MARCHE, redémarré (nouveau "
                f"runtime), et le démarrage ne se dit pas « déjà en marche » ({a1}, "
                f"deja={a2.get('deja')}, actif={'ssvep' in srv.active})")
            #    (b) démarrer puis arrêter un mode arrêté : il est arrêté à la fin.
            srv.submit("stop_mode", id="ssvep")
            srv._drain_commands()
            chk("ssvep" not in srv.active, "(b) point de départ : le SSVEP est arrêté")
            b1 = srv.submit("start_mode", id="ssvep")
            b2 = srv.submit("stop_mode", id="ssvep")
            srv._drain_commands()
            chk(b1.get("accepted") and "deja" not in b1 and b2.get("accepted")
                and "deja" not in b2 and "ssvep" not in srv.active,
                f"(b) start_mode puis stop_mode : le SSVEP finit ARRÊTÉ, et l'arrêt ne se dit pas "
                f"« déjà arrêté » ({b2}, actif={'ssvep' in srv.active})")
            #    (c) démarrer puis régler un mode ARRÊTÉ : le démarrage part AVEC le réglage. Chaque
            #    cas pose son point de départ lui-même : hérité du cas d'avant, il dépendrait de
            #    sa réussite (un SSVEP resté en marche par (b) rendrait (c) vrai à vide).
            srv.submit("stop_mode", id="ssvep")
            srv._drain_commands()
            chk("ssvep" not in srv.active, "(c) point de départ : le SSVEP est arrêté")
            x = 9.4 if abs((retenu(srv, "ssvep", "alpha_hz") or 0.0) - 9.4) > 0.05 else 9.8
            c1 = srv.submit("start_mode", id="ssvep")
            c2 = srv.submit("set_params", id="ssvep", params={"alpha_hz": x})
            srv._drain_commands()
            chk(c1.get("accepted") and c2.get("accepted") and c2.get("differe") is False
                and reglage(srv, "ssvep", "alpha_hz") == x and retenu(srv, "ssvep", "alpha_hz") == x,
                f"(c) start_mode puis set_params : le mode tourne avec le réglage, retenu au "
                f"magasin, et l'accusé ne le dit pas différé (runtime "
                f"{reglage(srv, 'ssvep', 'alpha_hz')}, magasin {retenu(srv, 'ssvep', 'alpha_hz')}, "
                f"pour {x} ; differe={c2.get('differe')})")
            #    (d) deux réglages de suite sur un mode qui tourne : ni l'un ni l'autre n'est perdu.
            if "ssvep" not in srv.active:
                srv.submit("start_mode", id="ssvep")
                srv._drain_commands()
            chk("ssvep" in srv.active, "(d) point de départ : le SSVEP tourne")
            y = 10.8 if abs((reglage(srv, "ssvep", "alpha_hz") or 0.0) - 10.8) > 0.05 else 11.2
            rafraichi = 120.0 if reglage(srv, "ssvep", "refresh_hz") != 120.0 else 60.0
            d1 = srv.submit("set_params", id="ssvep", params={"alpha_hz": y})
            d2 = srv.submit("set_params", id="ssvep", params={"refresh_hz": rafraichi})
            srv._drain_commands()
            chk(d1.get("accepted") and d2.get("accepted")
                and (d2.get("params") or {}).get("alpha_hz") == y
                and reglage(srv, "ssvep", "alpha_hz") == y
                and reglage(srv, "ssvep", "refresh_hz") == rafraichi
                and retenu(srv, "ssvep", "alpha_hz") == y
                and retenu(srv, "ssvep", "refresh_hz") == rafraichi,
                f"(d) deux set_params de suite : le second garde le premier — dans son accusé, "
                f"dans le runtime et au magasin (alpha {reglage(srv, 'ssvep', 'alpha_hz')} pour "
                f"{y}, rafraîchissement {reglage(srv, 'ssvep', 'refresh_hz')} pour {rafraichi} ; "
                f"accusé {(d2.get('params') or {}).get('alpha_hz')})")
            srv.submit("stop_mode", id="ssvep")
            srv._drain_commands()

            # 3. Un modèle se désigne par son NOM DE FICHIER ; le refus ne montre pas les dossiers.
            #    Des chemins de CE poste (`os.path.join`) : un chemin écrit avec des « / » ne
            #    prouverait rien du séparateur de Windows.
            spec = registry.get("p300")
            param_modele = next(p for p in spec.params if p.key == "model")
            ancien = param_modele.choices_fn
            chemin_a = os.path.join(tmp, "poste", "data", "p300_A.joblib")
            chemin_b = os.path.join(tmp, "poste", "data", "p300_B.joblib")
            object.__setattr__(param_modele, "choices_fn", lambda: (chemin_a, chemin_b))
            try:
                ack = srv.submit("set_params", id="p300", params={"model": "p300_B.joblib"})
                chk(ack.get("accepted") and retenu(srv, "p300", "model") == chemin_b,
                    f"model par nom de fichier : le chemin complet est retenu ({ack})")
                ack = srv.submit("set_params", id="p300", params={"model": "absent.joblib"})
                raison = str(ack.get("reason"))
                chk(not ack.get("accepted") and "p300_A.joblib" in raison
                    and os.path.join(tmp, "poste") not in raison,
                    f"model inconnu : le refus liste des NOMS, pas des chemins ({raison})")
            finally:
                object.__setattr__(param_modele, "choices_fn", ancien)

            # 4. Un échec APRÈS acceptation est signalé à l'appelant réseau, jamais à la console.
            class _RuntimeQuiLeve:
                def __init__(self, spec, params, serveur):
                    raise ValueError("panne de test")

            spec_ssvep = registry.get("ssvep")
            ancien_cls = spec_ssvep.runtime_cls
            object.__setattr__(spec_ssvep, "runtime_cls", _RuntimeQuiLeve)
            try:
                srv2 = moteur("smoke-reseau-echec", tmp, 2)
                recus = []                               # appelé par la boucle : un append suffit
                srv2.sur_echec = lambda reseau, commande, raison: recus.append(
                    (reseau, commande, str(raison)))
                jeton = ("r1", "start_mode", "ssvep")
                ack = srv2.submit("start_mode", id="ssvep", reseau=jeton)
                chk(ack.get("accepted"), f"la commande est ACCEPTÉE avant d'échouer ({ack})")
                srv2._drain_commands()
                chk(recus == [(jeton, "start_mode", "panne de test")],
                    f"l'échec en boucle revient à sur_echec avec le jeton et la raison ({recus})")
                srv2.submit("start_mode", id="ssvep")
                srv2._drain_commands()
                chk(len(recus) == 1, "la même panne sans jeton (la console) ne signale rien")
            finally:
                object.__setattr__(spec_ssvep, "runtime_cls", ancien_cls)

            # 5. Un refus pris DANS la boucle (une mesure qui publie le flux du mode est apparue
            #    entre la soumission et le tour) est signalé, AVEC sa raison. `submit` a jugé sur
            #    un moteur sans mesure ; on pose la fausse mesure ensuite, comme le ferait la boucle.
            srv3 = moteur("smoke-reseau-refus", tmp, 3)
            recus3 = []
            srv3.sur_echec = lambda reseau, commande, raison: recus3.append(
                (reseau, commande, str(raison)))
            jeton3 = ("r2", "start_mode", "ssvep")
            ack = srv3.submit("start_mode", id="ssvep", reseau=jeton3)
            chk(ack.get("accepted"), f"la commande est acceptée sur un moteur sans mesure ({ack})")
            srv3.mesure = types.SimpleNamespace(
                terminee=False, marker_mode_id="ssvep", publie_le_flux_du_mode=lambda: True,
                spec=types.SimpleNamespace(label="Mesure de test"))
            srv3._drain_commands()
            attendu = str(tr("moteur.refus.mode_pendant_mesure_flux",
                             mode=registry.get("ssvep").label))
            chk(recus3 == [(jeton3, "start_mode", attendu)] and "ssvep" not in srv3.active,
                f"un démarrage refusé par la boucle est signalé avec sa raison ({recus3})")
            srv3.mesure = None

            # 6. Un `sur_echec` qui LÈVE ne tue pas le moteur : la commande suivante est appliquée.
            def explose(reseau, commande, raison):
                raise RuntimeError("rappel en panne")

            srv3.sur_echec = explose
            srv3.mesure = types.SimpleNamespace(
                terminee=False, marker_mode_id="ssvep", publie_le_flux_du_mode=lambda: True,
                spec=types.SimpleNamespace(label="Mesure de test"))
            srv3._mettre_en_file("start_mode", {"ids": ["ssvep"], "params": {
                "ssvep": registry.get("ssvep").defaults()}}, jeton3)
            try:
                srv3._drain_commands()
                leve = None
            except Exception as e:  # noqa: BLE001 - c'est précisément ce qui est vérifié
                leve = e
            chk(leve is None, f"un rappel d'échec qui lève ne remonte pas de la boucle ({leve!r})")
            srv3.mesure = None
            srv3.submit("start_mode", id="neuro")
            srv3._drain_commands()
            chk("neuro" in srv3.active,
                "après un rappel qui lève, la commande suivante est quand même appliquée")

            # 7. Deux « démarrer » mis en file avant le même tour : le dernier gagne, et le runtime
            #    n'est construit QU'UNE fois. Compté sur une sous-classe du vrai runtime : vérifier
            #    seulement le réglage final passerait aussi si la boucle recréait le runtime.
            constructions = []
            vraie_cls = spec_ssvep.runtime_cls

            class _RuntimeCompte(vraie_cls):
                def __init__(self, *args, **kwargs):
                    constructions.append(1)
                    super().__init__(*args, **kwargs)

            object.__setattr__(spec_ssvep, "runtime_cls", _RuntimeCompte)
            try:
                srv4 = moteur("smoke-reseau-double", tmp, 4)
                srv4.submit("start_mode", id="ssvep", params={"ssvep": {"alpha_hz": 9.0}})
                srv4.submit("start_mode", id="ssvep", params={"ssvep": {"alpha_hz": 10.4}})
                srv4._drain_commands()
            finally:
                object.__setattr__(spec_ssvep, "runtime_cls", vraie_cls)
            chk(len(constructions) == 1 and reglage(srv4, "ssvep", "alpha_hz") == 10.4
                and retenu(srv4, "ssvep", "alpha_hz") == 10.4,
                f"deux démarrages en file : un seul runtime construit ({len(constructions)}), "
                f"réglages du dernier ({reglage(srv4, 'ssvep', 'alpha_hz')})")

            # 8. Le test d'un mode fige ses réglages, même quand le mode est ARRÊTÉ : le test du
            #    MI n'empêche pas de démarrer le MI, mais un `start_mode` qui porte des réglages est
            #    un `set_params` par la porte de côté. Sans réglages, rien ne change : accepté.
            spec_mi = registry.get("mi")
            modele_mi = next(p for p in spec_mi.params if p.key == "model")
            ancien_mi = modele_mi.choices_fn
            object.__setattr__(modele_mi, "choices_fn", lambda: ("faux_mi.joblib",))
            try:
                srv5 = moteur("smoke-reseau-test-mi", tmp, 5)
                srv5.mesure = types.SimpleNamespace(
                    terminee=False, marker_mode_id="",
                    spec=types.SimpleNamespace(id=spec_mi.test_id, label="Test du MI"))
                avec = srv5.submit("start_mode", id="mi", params={"mi": {"prob_min": 0.75}})
                attendu = str(tr("moteur.refus.reglage_pendant_test", mode=spec_mi.label,
                                 test="Test du MI"))
                sans = srv5.submit("start_mode", id="mi")
                chk(not avec.get("accepted") and str(avec.get("reason")) == attendu
                    and sans.get("accepted") and retenu(srv5, "mi", "prob_min") != 0.75,
                    f"pendant le test du MI, un start_mode qui RÈGLE le MI arrêté est refusé, un "
                    f"start_mode sans réglage passe ({avec.get('reason')!r} / {sans.get('accepted')})")
                srv5.mesure = None
            finally:
                object.__setattr__(modele_mi, "choices_fn", ancien_mi)
        except Exception as e:  # noqa: BLE001 - une exception ici est un échec du test, pas du smoke
            traceback.print_exc()
            chk(False, f"le test s'est interrompu sur une exception ({e!r})")
        finally:
            # Les runtimes ouverts par ce test libèrent leurs flux de sortie, et chaque moteur
            # retire les siens (`quality`, `status`, `replies`). ⚠️ `active` est VIDÉ : un runtime
            # garde son moteur, donc un moteur jamais passé par `run()` forme un cycle que seul le
            # ramasse-miettes casse — et un `BoardShim.__del__` tardif libérerait alors la session
            # du moteur RÉEL de `_smoke_pilotage`, juste après (clé BrainFlow partagée par le
            # processus, cf. le `finally` de `run`).
            for m in moteurs:
                for rt in list(m.active.values()):
                    try:
                        rt.close()
                    except Exception as e:  # noqa: BLE001 - fermer les autres quand même
                        print(f"  (fermeture d'un runtime du test en erreur : {e!r})")
                m.active = {}
                try:
                    m.retirer_flux()
                except Exception as e:  # noqa: BLE001 - idem
                    print(f"  (retrait des flux d'un moteur du test en erreur : {e!r})")
            del moteurs[:]
            srv = srv2 = srv3 = srv4 = srv5 = None
            gc.collect()

    print(f"[smoke-reseau-moteur] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_pilotage():
    """Une application de CETTE machine pilote le vrai moteur par le réseau, de bout en bout.

    Le client exemple (`examples/control_client.py`) tourne dans un AUTRE processus, contre un
    moteur réel sur le board de test : l'exemple ne peut pas cesser de marcher sans faire rougir
    ce test. Le moteur écoute un nom de flux de commandes PROPRE au test : un moteur oublié sur le
    poste écoute le nom par défaut, et n'obéit donc pas aux commandes du test.

    Vérifie aussi : une commande envoyée avant que le moteur ait découvert l'outlet de
    l'application est perdue (le piège que la doc enseigne est réel) ; une commande sans objet est
    refusée en anglais, pour LA raison attendue ; un démarrage accepté puis refusé par la boucle
    (un modèle MI disparu) envoie un second message, qui nomme le FICHIER et pas le dossier du
    poste ; un avertissement part en anglais ; juger une rafale de commandes ne ralentit pas
    l'acquisition ; le moteur arrêté ne laisse ni fil d'écoute, ni flux de réponses, ni objet
    retenu en mémoire.

    L'écran est en français : tout ce qui part vers l'application doit rester en anglais. Les
    dossiers de données sont temporaires, et les listes de modèles du P300 et du MI sont remplacées
    par de faux noms le temps du test (elles ne dépendent jamais de `data/`).
    """
    import gc
    import subprocess
    import threading
    import traceback

    from pylsl import IRREGULAR_RATE, StreamInfo, StreamInlet, StreamOutlet, resolve_byprop

    from core.i18n import choisir_langue
    from core.lsl_io import _source_id

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _MoteurAbsent(Exception):
        """Le moteur n'a jamais démarré : rien de ce qui suit n'aurait de sens."""

    def virgule_decimale(texte):
        return re.search(r"\d,\d", str(texte)) is not None

    def lire(entree, delai_s, jusqua=None):
        """Les réponses JSON lues sur `entree` pendant `delai_s` secondes au plus, ou jusqu'à ce
        que `jusqua(reçues)` soit vrai."""
        recues, echeance = [], time.perf_counter() + delai_s
        while time.perf_counter() < echeance:
            echantillon, _ts = entree.pull_sample(timeout=0.05)
            if echantillon is not None:
                try:
                    recues.append(json.loads(echantillon[0]))
                except ValueError:
                    recues.append({"illisible": echantillon[0]})
            if jusqua is not None and jusqua(recues):
                break
        return recues

    def etape_du_client(sortie, n):
        """Ce que le client exemple a imprimé à son étape `n` : (ses réponses « <- {...} »
        relues en JSON, le texte de l'étape)."""
        dedans, reps, lignes = False, [], []
        for ligne in sortie.splitlines():
            if ligne.startswith("["):
                dedans = ligne.startswith(f"[{n}/")
            elif dedans:
                lignes.append(ligne)
                if ligne.strip().startswith("<- "):
                    try:
                        reps.append(json.loads(ligne.strip()[3:]))
                    except ValueError:
                        pass
        return reps, "\n".join(lignes)

    def texte_de(flux):
        """La sortie capturée d'un processus en texte : en octets, en texte ou absente."""
        if flux is None:
            return ""
        return flux.decode("utf-8", "replace") if isinstance(flux, bytes) else str(flux)

    def surveiller(moteur, arret, releves):
        """Relève (instant, échantillons publiés) toutes les 20 ms, jusqu'à `arret`."""
        while not arret.is_set():
            releves.append((time.perf_counter(), moteur.samples))
            arret.wait(0.02)

    def pannes(releves):
        """Chaque durée passée sans qu'un seul échantillon de plus soit publié, de la plus longue
        à la plus courte. `[inf]` sans relevés exploitables."""
        if len(releves) < 2:
            return [float("inf")]
        durees, depuis, dernier = [], releves[0][0], releves[0][1]
        for t, n in releves[1:]:
            if n != dernier:
                durees.append(t - depuis)
                depuis, dernier = t, n
        durees.append(releves[-1][0] - depuis)          # la dernière, encore en cours
        return sorted(durees, reverse=True)

    pid = os.getpid()
    nom_commandes = f"{NOM_FLUX_COMMANDES}_smoke_{pid}"
    # Le nom d'hôte dans l'instance : deux postes de la salle qui lancent le smoke au même PID
    # publieraient sinon sous le même `source_id`, et `_resolve_own` prendrait le flux du voisin.
    instance = f"smoke-pilotage-{socket.gethostname()}-{pid}"
    racine = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    exemple = os.path.join(racine, "examples", "control_client.py")
    # La boucle publie le brut à CHAQUE tour (~50 ms) : sans à-coup, elle ne reste jamais plus
    # d'environ 0,1 s sans publier. Une boucle qui attendrait le jugement de chaque commande
    # (~0,3 s de recherche réseau pour `stream_in`) resterait muette plus longtemps que ce seuil,
    # À CHAQUE commande de la rafale (20 fois). Un ordinateur chargé (antivirus, mise à jour) a
    # droit à quelques hoquets isolés : au plus `pannes_tolerees` au-delà du seuil.
    panne_max_s = 0.2
    pannes_tolerees = 2

    langue_avant = os.environ.get("EEG_LANGUE")
    remises = []                    # (réglage, liste d'origine), remis en place à la fin
    srv = fil = entree = app = arret = sonde = None
    tmp = tempfile.mkdtemp(prefix="smoke-pilotage-")
    # Le faux modèle MI : un chemin du POSTE (sous `tmp`), que la boucle ne trouvera pas. La
    # raison de l'échec doit nommer le FICHIER, jamais ce dossier : le flux de réponses se lit de
    # tout le réseau.
    faux_mi = os.path.join(tmp, f"absent_mi_{pid}.joblib")
    try:
        choisir_langue("fr")
        # Les listes de modèles du P300 et du MI sont remplacées par un faux nom : le P300 peut
        # alors être réglé, et le MI est ACCEPTÉ puis refuse de démarrer dans la boucle (son
        # fichier n'existe pas).
        for mode_id, faux in (("p300", "faux_modele.joblib"), ("mi", faux_mi)):
            param = next(p for p in registry.get(mode_id).params if p.key == "model")
            remises.append((param, param.choices_fn))
            object.__setattr__(param, "choices_fn", lambda faux=faux: (faux,))

        srv = EngineServer(synthetic=True, modes=("raw",), instance=instance,
                           data_dir=os.path.join(tmp, "data"),
                           seances_dir=os.path.join(tmp, "seances"),
                           flux_commandes=nom_commandes)
        # Une durée large : c'est `stop()` qui arrête le moteur, à la fin du test.
        fil = threading.Thread(target=srv.run, daemon=True, name="smoke-pilotage-moteur",
                               kwargs={"duration_s": 300.0, "baseline_s": 1.0, "warmup_s": 0.5})
        fil.start()
        echeance = time.perf_counter() + 20.0
        while (not (srv.acquisition_ouverte and srv.pilotage.vivant)
               and fil.is_alive() and time.perf_counter() < echeance):
            time.sleep(0.05)
        chk(srv.pilotage.vivant,
            f"le moteur écoute les commandes de cette machine sur « {nom_commandes} »")
        if not srv.pilotage.vivant:
            # Sans moteur, le client attendrait 150 s pour rien, et chaque contrôle suivant
            # rougirait pour la même cause : on s'arrête ici, la cause est dite juste au-dessus.
            raise _MoteurAbsent()

        # 1. Le client exemple, dans un AUTRE processus, comme l'application d'un élève.
        # `PYTHONUNBUFFERED` : la sortie d'un client tué au bout du délai n'est pas perdue.
        t0 = time.perf_counter()
        try:
            fini = subprocess.run(
                [sys.executable, exemple, "--stream", nom_commandes, "--timeout", "30"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=150, env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                  "PYTHONUNBUFFERED": "1"})
            code, sortie = fini.returncode, texte_de(fini.stdout) + texte_de(fini.stderr)
        except subprocess.TimeoutExpired as e:
            code, sortie = None, texte_de(e.stdout) + texte_de(e.stderr)
        duree = time.perf_counter() - t0
        client_ok = code == 0
        chk(client_ok, f"le client exemple reçoit la réponse attendue à chaque étape "
                       f"(code {code}, {duree:.1f} s)")
        # Ce que le moteur en montre : la console lit le journal (dans la langue de l'écran),
        # l'application le flux `status`.
        journal = srv.snapshot()["pilotage"]
        cmds = [e["cmd"] for e in journal[-5:]]
        # L'étape 2 du client : le rafraîchissement SEUL est refusé. Sa raison, sur le réseau, est
        # la relecture en anglais de celle du journal — et pas son texte français.
        ecran2 = journal[-5].get("raison") if len(journal) >= 5 else None
        reps2, texte2 = etape_du_client(sortie, 2)
        raison2 = reps2[0].get("reason") if reps2 else None
        etape2_ok = (len(reps2) == 1 and reps2[0].get("accepted") is False
                     and isinstance(raison2, str) and bool(raison2)
                     and ecran2 is not None and raison2 == pour_le_contrat(ecran2)
                     and raison2 != str(ecran2) and not virgule_decimale(raison2)
                     and "that is expected" in texte2)
        chk(etape2_ok, f"étape 2 : le rafraîchissement SEUL est refusé pour la raison que "
                       f"l'exemple explique, en anglais, nombres avec un point ({raison2!r} / à "
                       f"l'écran : {str(ecran2)!r})")
        if not (client_ok and etape2_ok):
            print("  --- sortie du client exemple ---")
            for ligne in sortie.splitlines():
                print(f"  | {ligne}")
            print("  --- fin de la sortie ---")

        # 2. Le journal du moteur, et le flux `status`.
        chk(len(journal) >= 5 and cmds == ["set_params", "propose_params", "set_params",
                                           "start_mode", "stop_mode"]
            and journal[-5]["accepted"] is False and all(e["accepted"] for e in journal[-4:]),
            f"le journal du moteur garde les commandes de l'application ({len(journal)} "
            f"entrées : {cmds})")
        echeance = time.perf_counter() + 5.0
        while "ssvep" in srv.active and time.perf_counter() < echeance:
            time.sleep(0.05)
        chk("ssvep" not in srv.active and srv.reglages.get("ssvep", {}).get("refresh_hz") == 30.0,
            f"le SSVEP est arrêté, et son rafraîchissement de 30 Hz est retenu "
            f"({srv.reglages.get('ssvep', {}).get('refresh_hz')})")
        info_statut = _resolve_own("status", instance, 5.0)
        flux_annonces = []
        if info_statut is not None:
            statut_in = StreamInlet(info_statut, recover=False)
            statut_in.open_stream(timeout=5.0)
            # Republié toutes les 2 s : un message arrive en moins de 5 s.
            messages = lire(statut_in, 5.0, jusqua=lambda r: len(r) >= 1)
            statut_in.close_stream()
            statut_in = None
            flux_annonces = messages[0].get("streams", []) if messages else []
        chk(NOM_FLUX_REPONSES in flux_annonces,
            f"le flux `status` annonce « {NOM_FLUX_REPONSES} » ({flux_annonces})")

        # 3. Une commande SANS OBJET : refusée en anglais, sans exception, et pour LA raison
        # attendue (la clé du texte au journal). `traiter` rattrape toute exception du moteur en
        # « erreur interne » — rendue elle aussi en anglais : sans la clé, une exception passerait
        # tous les autres contrôles.
        attendu_mi = pour_le_contrat(tr("moteur.refus.mode_ne_propose_rien",
                                        mode=registry.get("mi").label))
        for texte, ref, attendu, cle in (
                ('{"cmd":"propose_params","mode":"mi","ref":"a"}', "a", attendu_mi,
                 "moteur.refus.mode_ne_propose_rien"),
                ('{"cmd":"set_params","mode":"raw","params":{"x":1},"ref":"b"}', "b", None,
                 "moteur.contrat.inconnu")):
            try:
                rep, leve = srv.pilotage.traiter(texte), None
            except Exception as e:  # noqa: BLE001 - c'est justement ce qui est vérifié
                rep, leve = {}, e
            ecran = srv.pilotage.journal()[-1].get("raison")
            raison = rep.get("reason")
            chk(leve is None and rep.get("ref") == ref and rep.get("accepted") is False
                and getattr(ecran, "cle", None) == cle
                and type(raison) is str and raison == pour_le_contrat(ecran)
                and raison != str(ecran) and not virgule_decimale(raison)
                and (attendu is None or raison == attendu),
                f"{texte} : refusé en anglais (« {cle} »), l'écran en français, sans exception "
                f"({raison!r} / à l'écran : {str(ecran)!r}, clé {getattr(ecran, 'cle', None)!r}, "
                f"{leve!r})")
        # Sans « key », sur un mode qui propose : le refus dit quel réglage nommer. (Par le réseau,
        # l'adaptateur complète « key » quand le mode n'a qu'un réglage qui propose.)
        ack = srv.submit("propose_params", id="ssvep")
        spec_ssvep = registry.get("ssvep")
        attendu = tr("moteur.refus.propose_quelle_cle", mode=spec_ssvep.label,
                     liste=", ".join(p.key for p in spec_ssvep.params if p.proposes))
        chk(not ack.get("accepted") and str(ack.get("reason")) == str(attendu),
            f"propose_params sans « key » : le refus nomme le réglage à désigner "
            f"({ack.get('reason')!r})")

        info_rep = _resolve_own(_SUFFIXE_REPONSES, instance, 5.0)
        chk(info_rep is not None, "le flux de réponses du moteur est trouvé")
        if info_rep is not None:
            # 4. Le piège « commande avant que le moteur écoute » : une commande envoyée avant que
            # le moteur ait découvert l'outlet de l'application est PERDUE.
            entree = StreamInlet(info_rep, recover=False)
            # Et le piège « réponse avant que l'application écoute » : on ouvre l'inlet de
            # réponses AVANT d'envoyer la première commande.
            entree.open_stream(timeout=5.0)
            app = StreamOutlet(StreamInfo(nom_commandes, "Markers", 1, IRREGULAR_RATE, "string",
                                          f"smoke-pilotage-app-{pid}"))
            app.push_sample([json.dumps({"cmd": "stop_mode", "mode": "neuro", "ref": "avant"})])
            recues = lire(entree, 2.0)
            chk(not any(r.get("ref") == "avant" for r in recues),
                f"une commande envoyée sans attendre le moteur n'a AUCUNE réponse en 2 s, et rien "
                f"ne lève ({len(recues)} réponse(s))")
            t0 = time.perf_counter()
            branche = app.wait_for_consumers(10.0)
            attente = time.perf_counter() - t0
            app.push_sample([json.dumps({"cmd": "stop_mode", "mode": "neuro", "ref": "apres"})])
            recues = lire(entree, 5.0, jusqua=lambda r: any(x.get("ref") == "apres" for x in r))
            apres = [r for r in recues if r.get("ref") == "apres"]
            chk(branche and len(apres) == 1 and apres[0].get("accepted") is True
                and apres[0].get("already_stopped") is True
                and not any(r.get("ref") == "avant" for r in recues),
                f"après `wait_for_consumers` ({attente:.2f} s), la même commande a sa réponse, qui "
                f"dit le Neuro déjà arrêté ({apres})")

            # 5. Un échec APRÈS l'acceptation arrive à l'application. `submit` accepte le MI (son
            # modèle figure dans la liste) ; dans la boucle, son runtime refuse de démarrer (le
            # fichier n'existe pas). Un second message, au même « ref », le dit, en anglais, en
            # nommant le FICHIER — jamais le dossier du poste (`tmp`).
            app.push_sample([json.dumps({"cmd": "start_mode", "mode": "mi", "ref": "mi-1"})])
            recues = lire(entree, 10.0, jusqua=lambda r: any(
                x.get("ref") == "mi-1" and x.get("event") == "failed" for x in r))
            du_mi = [r for r in recues if r.get("ref") == "mi-1"]
            echoue = next((r for r in du_mi if r.get("event") == "failed"), {})
            ecran = next((e.get("raison") for e in reversed(srv.pilotage.journal())
                          if e.get("event") == "failed" and e.get("mode") == "mi"), None)
            raison = echoue.get("reason")
            chk(len(du_mi) == 2 and du_mi[0].get("accepted") is True and "event" not in du_mi[0]
                and set(echoue) == {"ref", "cmd", "mode", "event", "reason"}
                and echoue.get("cmd") == "start_mode" and echoue.get("mode") == "mi"
                and getattr(ecran, "cle", None) == "mode.modele.introuvable"
                and type(raison) is str and raison == pour_le_contrat(ecran)
                and raison != str(ecran) and "mi" not in srv.active,
                f"start_mode accepté puis refusé par la boucle : l'application reçoit l'accusé, "
                f"puis « event »: « failed » au même « ref », raison en anglais ({du_mi} / à "
                f"l'écran : {str(ecran)!r}, clé {getattr(ecran, 'cle', None)!r})")
            chk(isinstance(raison, str) and os.path.basename(faux_mi) in raison
                and tmp not in raison and os.path.dirname(faux_mi) not in raison,
                f"...et la raison nomme le FICHIER du modèle, pas le dossier du poste ({raison!r})")

            # 6. La boucle ne bloque pas. Chaque réglage `stream_in` du P300 fait chercher le flux
            # sur le réseau (~0,3 s) : c'est le fil de l'adaptateur qui attend. Chaque réglage du
            # SSVEP, qui tourne, part dans la file de la boucle. Entre deux échantillons publiés,
            # la boucle ne reste muette plus de `panne_max_s` qu'au plus `pannes_tolerees` fois.
            app.push_sample([json.dumps({"cmd": "start_mode", "mode": "ssvep", "ref": "ssvep-1"})])
            echeance = time.perf_counter() + 10.0
            while "ssvep" not in srv.active and time.perf_counter() < echeance:
                time.sleep(0.05)
            lire(entree, 1.0, jusqua=lambda r: any(x.get("ref") == "ssvep-1" for x in r))
            alpha = srv.reglages.get("ssvep", {}).get("alpha_hz")
            chk("ssvep" in srv.active and alpha is not None,
                f"le SSVEP tourne, ses réglages partent dans la file de la boucle ({alpha})")
            fs = float(srv.acq.fs)
            releves, arret = [], threading.Event()
            sonde = threading.Thread(target=surveiller, args=(srv, arret, releves), daemon=True,
                                     name="smoke-pilotage-sonde")
            sonde.start()
            n0, t0 = srv.samples, time.perf_counter()
            from core.pilotage import DEBIT_MAX
            for i in range(20):
                app.push_sample([json.dumps({"cmd": "set_params", "mode": "p300",
                                             "params": {"stream_in": f"Smoke_absent_{pid}_{i}"},
                                             "ref": f"rafale-p300-{i}"})])
                app.push_sample([json.dumps({"cmd": "set_params", "mode": "ssvep",
                                             "params": {"alpha_hz": alpha},
                                             "ref": f"rafale-ssvep-{i}"})])
                # Deux commandes à 80 % de `DEBIT_MAX` : la rafale est jugée en entier, sans dépendre
                # du temps que met le moteur à juger chacune (la limite refuserait le surplus).
                time.sleep(2.0 / (0.8 * DEBIT_MAX))

            def rafale_servie(r):
                return sum(1 for x in r if str(x.get("ref", "")).startswith("rafale-")) >= 40
            recues = lire(entree, 40.0, jusqua=rafale_servie)
            n1, t1 = srv.samples, time.perf_counter()
            arret.set()
            sonde.join(timeout=2.0)
            rafale = [r for r in recues if str(r.get("ref", "")).startswith("rafale-")]
            p300 = [r for r in rafale if r["ref"].startswith("rafale-p300-")]
            ssvep = [r for r in rafale if r["ref"].startswith("rafale-ssvep-")]
            chk(len(p300) == 20 and all(r.get("accepted") and r.get("deferred") for r in p300)
                and len(ssvep) == 20
                and all(r.get("accepted") and r.get("deferred") is False for r in ssvep),
                f"la rafale est servie : 20 réglages du P300 retenus, 20 du SSVEP mis en file "
                f"({len(p300)} et {len(ssvep)} réponses)")
            # L'AVERTISSEMENT d'une vraie réponse part en anglais : un nom de flux pas encore vu,
            # nommé, mot pour mot la relecture anglaise du texte du moteur — le réglage nommé par
            # son libellé ET sa clé, celle que l'application a envoyée. Et un réglage sans
            # réserve répond `null`.
            from core.i18n import reglage as _reglage
            premier = next((r for r in p300 if r.get("ref") == "rafale-p300-0"), {})
            libelle = next(p.label for p in registry.get("p300").params if p.key == "stream_in")
            attendu = pour_le_contrat(tr("moteur.contrat.flux_pas_vu",
                                         reglage=_reglage(libelle, "stream_in"),
                                         nom=f"Smoke_absent_{pid}_0"))
            avertissement = premier.get("warning")
            chk(type(avertissement) is str and f"Smoke_absent_{pid}_0" in avertissement
                and "(stream_in)" in avertissement and avertissement == attendu,
                f"l'avertissement d'un flux pas encore vu part en anglais, le flux nommé "
                f"({avertissement!r})")
            chk(bool(ssvep) and all("warning" in r and r["warning"] is None for r in ssvep),
                f"...et un réglage sans réserve répond « warning »: null "
                f"({sorted({repr(r.get('warning', 'absent')) for r in ssvep})})")
            durees = pannes(releves)
            longues = [d for d in durees if d >= panne_max_s]
            chk(len(releves) >= 10 and len(longues) <= pannes_tolerees,
                f"pendant la rafale ({t1 - t0:.1f} s), la boucle ne reste muette plus de "
                f"{panne_max_s:g} s qu'au plus {pannes_tolerees} fois ({len(longues)} fois ; les "
                f"trois plus longues : {', '.join(f'{d:.2f} s' for d in durees[:3])} ; "
                f"{len(releves)} relevés)")
            attendus = fs * (t1 - t0)
            chk(n1 - n0 >= 0.8 * attendus,
                f"...et l'acquisition publie au moins 80 % de {fs:g} Hz "
                f"({n1 - n0} échantillons pour {attendus:.0f})")

        # 7. Le moteur s'arrête : plus de fil d'écoute, et son flux de réponses quitte le réseau.
        srv.stop()
        fil.join(timeout=15.0)
        chk(not fil.is_alive(), "le moteur s'arrête")
        chk(not srv.pilotage.vivant, "la fin de `run()` arrête le fil d'écoute")
        srv.retirer_flux()
        if entree is not None:
            entree.close_stream()
        entree = app = None
        restants = [i.source_id() for i in resolve_byprop("name", NOM_FLUX_REPONSES, minimum=32,
                                                         timeout=1.0)
                    if i.source_id() == _source_id(_SUFFIXE_REPONSES, instance)]
        chk(restants == [], f"`retirer_flux()` retire aussi le flux de réponses ({restants})")

        # 8. L'adaptateur ne retient pas le moteur. Un cycle moteur ↔ adaptateur ne serait libéré
        # que par le ramasse-miettes cyclique, à une date quelconque : le destructeur de la session
        # BrainFlow libérerait alors celle du moteur SUIVANT (cf. le `finally` de `run`).
        gc_actif = gc.isenabled()
        gc.disable()
        try:
            temoin = weakref.ref(srv)
            srv = None
            libre = temoin() is None
        finally:
            if gc_actif:
                gc.enable()
        chk(libre, "le moteur arrêté est libéré tout de suite, sans le ramasse-miettes cyclique")
    except _MoteurAbsent:
        pass                        # dit par le contrôle qui l'a constaté
    except Exception as e:  # noqa: BLE001 - une exception ici est un échec du test, pas du smoke
        traceback.print_exc()
        chk(False, f"le test s'est interrompu sur une exception ({e!r})")
    finally:
        # D'abord ce qui ne peut pas échouer et que les smokes suivants lisent : les listes de
        # modèles et la langue. Ensuite seulement le moteur, dont l'arrêt peut lever ; le dossier
        # temporaire en tout dernier, quoi qu'il arrive.
        for param, choix in reversed(remises):
            object.__setattr__(param, "choices_fn", choix)
        if langue_avant is None:
            os.environ.pop("EEG_LANGUE", None)
        else:
            os.environ["EEG_LANGUE"] = langue_avant
        try:
            if arret is not None:
                arret.set()             # la sonde, si un contrôle a levé pendant la rafale
            if sonde is not None:
                sonde.join(timeout=2.0)
            entree = app = None
            if srv is not None:
                srv.stop()
                if fil is not None:
                    fil.join(timeout=15.0)
                srv.retirer_flux()
                srv = None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"[smoke-pilotage] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_connexion_a_froid():
    """La connexion d'une application, sur des moteurs construits À FROID : jamais lancés, sans
    application LSL, une connexion posée à la main. Déterministe : rien n'attend le réseau ni la
    boucle.

    Vérifie : la règle « à modèle » lue sur le contrat ; la liste BLANCHE de la console (une
    commande ajoutée demain est refusée) ; une commande de la connexion arrivée du réseau est
    refusée, sans bloquer ; les refus de « Connecter » (déjà connectée, entraînement, test) ; un
    mode d'avant que l'application « redémarre » n'est pas arrêté à la fin ; un mode à modèle
    qui ATTEND (réponse sans modèle, suggestion courte gardée à côté du magasin, `stop_mode` qui
    annule l'attente) ; un mode à modèle qui TOURNE n'attend pas et garde son modèle ; « aucun
    modèle entraîné » dit, pendant une connexion, de déconnecter d'abord.

    Et les trois COURSES, rejouées pas à pas : le jugement s'arrête au milieu
    (`_valider_reglages` ralenti) pendant qu'un autre fil termine la connexion ou arrête le mode.
    Après coup, rien de ce que l'application a démarré ne tourne. Sans `_connexion_verrou`,
    elles rougissent.

    ⚠️ Chaque moteur est DÉTRUIT avant le suivant (fonctions de remplacement retirées, flux
    retirés, ramasse-miettes). Une fonction posée sur l'instance qui cite le moteur forme un
    cycle, et le `BoardShim.__del__` d'un moteur ramassé trop tard libérerait la session
    BrainFlow du moteur VIVANT de `[smoke-connexion]`, juste après.
    """
    import gc
    import threading
    import traceback
    from types import SimpleNamespace

    from core import mi_models
    from core.i18n import choisir_langue

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    def cle(texte):
        return getattr(texte, "cle", None)

    def cles(avertissement):
        """Les clés des textes d'un avertissement (un `Joint` de `Texte`)."""
        return {cle(m) for m in getattr(avertissement, "morceaux", ())}

    pid = os.getpid()
    compte = [0]

    def jeton(commande, mode):
        return (f"cx-{commande}-{mode}", commande, mode)

    def reglages_toujours_valides(spec, runtime, nouveaux):
        """Ce test juge la CONNEXION, pas le contrat : des réglages toujours acceptés, et un
        modèle « du magasin » pour les modes à modèle. Ne cite aucun moteur : pas de cycle."""
        valeurs = {"model": "magasin.joblib"} if _a_un_modele(spec) else {}
        valeurs.update(nouveaux or {})
        return valeurs, [], None

    def connecter(srv):
        srv.connexion = _Connexion(uid="u", nom="app", depuis=time.time(), t=time.monotonic())

    def essai(nom, corps, connecte=True, valides=True):
        """Un moteur froid neuf pour `corps(srv)`, DÉTRUIT ensuite quoi qu'il arrive."""
        compte[0] += 1
        srv = EngineServer(synthetic=True, modes=(), instance=f"smoke-cx-froid-{pid}-{compte[0]}",
                           flux_commandes=f"{NOM_FLUX_COMMANDES}_smoke_cx_froid_{pid}_{compte[0]}",
                           ecoute="sur_demande")
        try:
            if valides:
                srv._valider_reglages = reglages_toujours_valides
            if connecte:
                connecter(srv)
            corps(srv)
        except Exception as e:  # noqa: BLE001 - une exception ici est un échec du test
            traceback.print_exc()
            chk(False, f"{nom} : interrompu sur une exception ({e!r})")
        finally:
            for attribut in ("_valider_reglages", "COMMANDS"):
                srv.__dict__.pop(attribut, None)
            srv.calibration = srv.mesure = None
            srv.retirer_flux()
            srv.close()
            del srv
            gc.collect()

    def sans_blocage(geste, delai_s=2.0):
        """`geste()` dans un autre fil : son résultat, ou None s'il reste BLOQUÉ (un verrou
        repris par le fil qui le tient). Un test qui bloquerait ne rendrait jamais son verdict."""
        rendu = {}
        fil = threading.Thread(target=lambda: rendu.setdefault("ack", geste()), daemon=True)
        fil.start()
        fil.join(delai_s)
        return rendu.get("ack")

    def ralentir(srv):
        """Arrête le jugement AU MILIEU : `_valider_reglages` (celui en place) rend la main
        après avoir signalé `en_jugement`, puis attendu `reprise` (1 s au plus). Sans verrou,
        l'autre fil passe pendant cette pause ; avec, il attend la fin du jugement."""
        vraie = srv._valider_reglages
        en_jugement, reprise = threading.Event(), threading.Event()

        def lente(spec, runtime, nouveaux):
            rendu = vraie(spec, runtime, nouveaux)
            en_jugement.set()
            reprise.wait(1.0)
            return rendu

        srv._valider_reglages = lente
        return en_jugement, reprise

    def course(srv, action, geste):
        """Joue `action(srv)` ici et `geste(srv)` dans un autre fil, PENDANT le jugement de
        l'action. Rend (accusé de l'action, accusé du geste)."""
        en_jugement, reprise = ralentir(srv)
        rendu = {}

        def concurrent():
            if en_jugement.wait(5.0):
                rendu["geste"] = geste(srv)
            reprise.set()

        fil = threading.Thread(target=concurrent, daemon=True)
        fil.start()
        ack = action(srv)
        fil.join(5.0)
        return ack, rendu.get("geste")

    vrai_dispo = mi_models.modeles_disponibles
    langue_avant = os.environ.get("EEG_LANGUE")
    vide = tempfile.mkdtemp(prefix="smoke-connexion-froid-")
    try:
        choisir_langue("fr")

        # R. La règle « à modèle » se lit sur le contrat.
        chk({s.id for s in registry.MODES if _a_un_modele(s)} == {"mi", "p300", "errp", "cvep"},
            "R. les modes à modèle sont ceux dont le contrat déclare un réglage `model`")

        def liste_blanche(srv):
            srv.COMMANDS = tuple(EngineServer.COMMANDS) + ("commande_de_demain",)
            rep = srv.submit("commande_de_demain", id="ssvep")
            chk(not rep["accepted"]
                and cle(rep["reason"]) == "moteur.connexion.console_verrouillee",
                f"L. une commande ajoutée demain est refusée pendant la connexion : la liste est "
                f"BLANCHE ({cle(rep.get('reason'))})")
        essai("L", liste_blanche)

        def commandes_console(srv):
            srv.connexion.en_attente["mi"] = jeton("start_mode", "mi")
            refus = {c: sans_blocage(lambda c=c: srv.submit(c, reseau=jeton(c, "mi"), id="mi",
                                                            uid="u", model="x.joblib"))
                     for c in srv.COMMANDES_CONSOLE}
            chk(all(r is not None and not r["accepted"]
                    and cle(r["reason"]) == "moteur.reseau.commande_non_permise"
                    for r in refus.values())
                and srv.connexion is not None and srv._tourneront(["mi"]) == [],
                f"N. une commande de la connexion qui arrive du réseau est refusée, sans bloquer "
                f"ni rien changer ({ {c: cle((r or {}).get('reason')) for c, r in refus.items()} })")
        essai("N", commandes_console)

        def refus_connecter(srv):
            rep = srv.submit("connecter", uid="v")
            chk(not rep["accepted"]
                and cle(rep["reason"]) == "moteur.connexion.console_verrouillee",
                f"K. connectée, la console ne peut pas « Connecter » ({cle(rep.get('reason'))})")
            # Deux clics de la console jugés ensemble passent tous deux le verrou de la console :
            # c'est `_connecter` qui refuse le second.
            rep = srv._connecter("v")
            chk(not rep["accepted"] and cle(rep["reason"]) == "moteur.connexion.deja",
                f"K. ...et une seconde connexion est refusée ({cle(rep.get('reason'))})")
            srv.connexion = None
            srv.calibration = SimpleNamespace(terminee=False)
            rep = srv.submit("connecter", uid="v")
            chk(not rep["accepted"] and cle(rep["reason"]) == "moteur.connexion.entrainement",
                f"K. « Connecter » est refusé pendant un entraînement ({cle(rep.get('reason'))})")
            srv.calibration = None
            srv.mesure = SimpleNamespace(terminee=False)
            rep = srv.submit("connecter", uid="v")
            chk(not rep["accepted"] and cle(rep["reason"]) == "moteur.connexion.test",
                f"K. ...et pendant un test ({cle(rep.get('reason'))})")
        essai("K", refus_connecter)

        def mode_d_avant(srv):
            srv._inscrire_marche("start_mode", ["neuro"], None)      # la console, AVANT
            connecter(srv)
            rep = srv.submit("start_mode", reseau=jeton("start_mode", "neuro"), id="neuro")
            chk(rep["accepted"] and rep.get("deja") == ["neuro"]
                and "neuro" not in srv.connexion.demarres,
                f"D. l'application « redémarre » un mode d'avant : il n'est pas à elle "
                f"({rep.get('deja')})")
            fin = srv.submit("deconnecter")
            chk(fin["accepted"] and fin["arretes"] == [] and srv.fin_connexion["arretes"] == ()
                and srv._tourneront(["neuro"]) == ["neuro"],
                f"D. ...et la fin ne l'arrête pas ({fin.get('arretes')})")
        essai("D", mode_d_avant, connecte=False)

        def mode_d_avant_appareil(srv):
            # Un APPAREIL réseau qui demande un mode déjà lancé par la console en reçoit les
            # décisions et la phase : sinon il attendrait en silence. Le mode n'est pas à lui
            # pour autant (la fin ne l'arrête pas, test D).
            srv._inscrire_marche("start_mode", ["neuro"], None)      # la console, AVANT
            connecter(srv)
            srv.connexion.origine = "udp"
            poussees = []
            srv.pilotage.pousser = lambda message: poussees.append(message) or True
            srv.pilotage.branchee = lambda: True
            rep = srv.submit("start_mode", reseau=jeton("start_mode", "neuro"), id="neuro")
            srv._decision_publiee("neuro", ["a"], [1.0])
            chk(rep["accepted"] and "neuro" not in srv.connexion.demarres
                and poussees == [{"decision": {"mode": "neuro", "a": 1.0}}],
                f"D2. un appareil réseau reçoit les décisions d'un mode d'avant qu'il a demandé "
                f"({poussees})")
            # Une poussée qui lève ne sort jamais de la boucle du moteur : elle est dite, et le
            # décodage continue.
            srv._statut_appareil = lambda *_: 1 / 0
            casse = types.SimpleNamespace(_out=types.SimpleNamespace(outlet=object()),
                                          channels=lambda: 1 / 0)
            try:
                srv._pousser_statut(0.0)
                srv._observer_la_sortie("neuro", casse)
                leve = None
            except Exception as e:  # noqa: BLE001 - c'est ce que le test vérifie
                leve = e
            chk(leve is None and srv._pannes_dites == {"status", "decision"},
                f"D2. ...et une poussée qui lève ne sort pas de la boucle ({leve!r})")
        essai("D2", mode_d_avant_appareil, connecte=False)

        def mode_d_avant_non_publie(srv):
            # Un mode lancé par la console, sa case « publié » décochée : il n'a pas de flux.
            # Le `start_mode` d'une application (`already_running`) le republie, sinon elle ne
            # recevrait rien ; celui de la console ne touche pas à sa publication.
            appels = []
            spec = registry.BY_ID["neuro"]
            runtime = SimpleNamespace(spec=spec, published=False,
                                      set_published=lambda on: appels.append(on))
            srv.active["neuro"] = runtime
            srv._set_params = lambda *_args: None
            srv._start(["neuro"], None, 0.0)
            console = list(appels)
            srv._start(["neuro"], None, 0.0, reseau=jeton("start_mode", "neuro"))
            chk(console == [] and appels == [True],
                f"D3. un mode d'avant non publié : le « start_mode » d'une application le "
                f"republie, celui de la console non ({console}, {appels})")
            srv.active.pop("neuro", None)
            srv.__dict__.pop("_set_params", None)
        essai("D3", mode_d_avant_non_publie, connecte=False)

        def depart_d_une_autre(srv):
            # Le départ d'une application qu'on a déconnectée, signalé après qu'une autre s'est
            # connectée : il ne termine pas la connexion en cours (vérifié sous le verrou).
            srv.application_partie("ancienne")
            chk(srv.connexion is not None and srv.connexion.uid == "u"
                and srv.fin_connexion is None,
                "P. le départ d'une AUTRE application ne termine pas la connexion en cours")
            srv.application_partie("u")
            chk(srv.connexion is None and (srv.fin_connexion or {}).get("raison") == "partie",
                "P. ...celui de l'application connectée, si")
        essai("P", depart_d_une_autre)

        def nom_illisible(srv):
            # Une application dont le nom (`source_id`) ne se lit pas : la connexion et sa fin le
            # portent, pour que la console dise « nom illisible » et non « sans nom ».
            srv.pilotage.chercher(True)
            srv.pilotage._noter_annonces({"i": (None, srv.pilotage.hote, None)})
            ack = srv.submit("connecter", uid="i")
            cx = srv.snapshot()["connexion"] or {}
            chk(ack["accepted"] and cx.get("nom") == "" and cx.get("illisible") is True,
                f"I. une application au nom illisible se connecte, et la connexion le dit ({cx})")
            srv.submit("deconnecter")
            fin = srv.snapshot()["fin_connexion"] or {}
            chk(fin.get("illisible") is True, f"I. ...sa fin aussi ({fin})")
        essai("I", nom_illisible, connecte=False)

        def attente(srv):
            rep = srv.submit("start_mode", reseau=jeton("start_mode", "mi"), id="mi",
                             params={"mi": {"model": "/ailleurs/suggere.joblib"}})
            chk(rep["accepted"] and rep.get("differe") is True and srv._tourneront(["mi"]) == []
                and srv.connexion.en_attente.get("mi") == jeton("start_mode", "mi"),
                "M. le MI que démarre l'application ATTEND son modèle, avec le jeton de sa "
                "commande")
            chk("model" in (rep.get("params") or {}) and rep["params"]["model"] is None
                and {"moteur.connexion.modele_suggere", "moteur.connexion.attend_un_modele"}
                <= cles(rep.get("warning")),
                f"M. ...sa réponse ne nomme aucun modèle, et dit pourquoi "
                f"({(rep.get('params') or {}).get('model')}, {cles(rep.get('warning'))})")
            chk(srv.reglages["mi"]["model"] == "magasin.joblib"
                and srv.connexion.suggestions.get("mi") == "suggere.joblib",
                f"M. ...la suggestion est gardée À CÔTÉ du magasin, jamais dedans, et réduite à "
                f"un nom de fichier ({srv.reglages['mi']['model']}, "
                f"{srv.connexion.suggestions.get('mi')})")
            rep = srv.submit("set_params", reseau=jeton("set_params", "mi"), id="mi",
                             params={"model": 42, "prob_min": 0.7})
            chk(rep["accepted"] and rep["params"]["model"] is None
                and rep["params"]["prob_min"] == 0.7
                and "moteur.connexion.modele_suggere" in cles(rep.get("warning"))
                and srv.connexion.suggestions.get("mi") == "suggere.joblib",
                f"M. un `model` qui n'est pas du texte est retiré quand même, l'avertissement "
                f"reste, la suggestion d'avant aussi ; le reste s'applique ({rep.get('params')})")
            srv.submit("set_params", reseau=jeton("set_params", "mi"), id="mi",
                       params={"model": "m" * 200})
            chk(len(srv.connexion.suggestions.get("mi") or "") == _SUGGESTION_MAX,
                f"M. une suggestion trop longue est coupée à {_SUGGESTION_MAX} caractères")
            stop = srv.submit("stop_mode", reseau=jeton("stop_mode", "mi"), id="mi")
            refus = srv.submit("lancer_decodage", id="mi", model="x.joblib")
            chk(stop["accepted"] and "mi" not in srv.connexion.en_attente
                and cle(refus.get("reason")) == "moteur.connexion.pas_demande",
                "M. un `stop_mode` de l'application annule l'attente ; « Lancer » est alors "
                "refusé")
        essai("M", attente)

        def tourne_deja(srv):
            srv._inscrire_marche("start_mode", ["mi"], None)
            connecter(srv)
            rep = srv.submit("start_mode", reseau=jeton("start_mode", "mi"), id="mi")
            chk(rep["accepted"] and not rep.get("differe") and "mi" not in srv.connexion.en_attente
                and rep["params"]["model"] == "magasin.joblib",
                f"T. un mode à modèle qui TOURNE n'attend pas, et garde son modèle "
                f"({rep.get('params')})")
            rep = srv.submit("set_params", reseau=jeton("set_params", "mi"), id="mi",
                             params={"model": "autre.joblib"})
            chk(rep["accepted"] and rep["params"]["model"] == "magasin.joblib"
                and srv.reglages["mi"]["model"] == "magasin.joblib",
                f"T. ...un `set_params` de l'application ne change pas son modèle, et la "
                f"réponse le nomme ({rep.get('params')})")
        essai("T", tourne_deja, connecte=False)

        def sans_modele(srv):
            mi_models.modeles_disponibles = lambda d=vide: vrai_dispo(d)
            rep = srv.submit("start_mode", id="mi")
            chk(not rep["accepted"] and cle(rep["reason"]) == "moteur.contrat.sans_modele",
                f"S. sans connexion, « aucun modèle » dit d'entraîner ({cle(rep.get('reason'))})")
            connecter(srv)
            rep = srv.submit("start_mode", reseau=jeton("start_mode", "mi"), id="mi")
            chk(not rep["accepted"]
                and cle(rep["reason"]) == "moteur.connexion.sans_modele_entraine",
                f"S. connectée, il dit de déconnecter d'abord ({cle(rep.get('reason'))})")
            srv.connexion.en_attente["mi"] = jeton("start_mode", "mi")
            rep = srv.submit("lancer_decodage", id="mi", model=None)
            chk(not rep["accepted"]
                and cle(rep["reason"]) == "moteur.connexion.sans_modele_entraine",
                f"S. ...« Lancer le décodage » aussi ({cle(rep.get('reason'))})")
        essai("S", sans_modele, connecte=False, valides=False)
        mi_models.modeles_disponibles = vrai_dispo

        # Les COURSES. Course A : `start_mode` de l'application contre « Déconnecter ».
        def course_a(srv):
            ack, fin = course(
                srv,
                lambda s: s.submit("start_mode", reseau=jeton("start_mode", "ssvep"), id="ssvep"),
                lambda s: s.submit("deconnecter"))
            chk(ack["accepted"] and (fin or {}).get("accepted") and srv.connexion is None
                and srv._tourneront(["ssvep"]) == []
                and "ssvep" in (srv.fin_connexion or {}).get("arretes", ()),
                f"C-A. un `start_mode` de l'application jugé pendant « Déconnecter » : le SSVEP "
                f"ne tourne pas après la fin ({(srv.fin_connexion or {}).get('arretes')})")
        essai("C-A", course_a, valides=False)       # le vrai contrat : le SSVEP n'a pas de modèle

        # Course B : « Lancer le décodage » contre le départ de l'application.
        def course_b(srv):
            srv.connexion.en_attente["mi"] = jeton("start_mode", "mi")
            ack, _ = course(srv,
                            lambda s: s.submit("lancer_decodage", id="mi", model="x.joblib"),
                            lambda s: s.application_partie("u"))
            fin = srv.fin_connexion or {}
            chk(ack["accepted"] and srv.connexion is None and fin.get("raison") == "partie"
                and srv._tourneront(["mi"]) == [] and "mi" in fin.get("arretes", ()),
                f"C-B. « Lancer le décodage » jugé pendant le départ de l'application : le MI ne "
                f"tourne pas après la fin ({fin.get('arretes')})")
        essai("C-B", course_b)

        # Course C : `stop_mode` de l'application contre « Lancer le décodage ».
        def course_c(srv):
            srv.connexion.en_attente["mi"] = jeton("start_mode", "mi")
            ack, stop = course(
                srv,
                lambda s: s.submit("lancer_decodage", id="mi", model="x.joblib"),
                lambda s: s.submit("stop_mode", reseau=jeton("stop_mode", "mi"), id="mi"))
            chk(ack["accepted"] and (stop or {}).get("accepted")
                and srv._tourneront(["mi"]) == [],
                f"C-C. un `stop_mode` de l'application jugé pendant « Lancer le décodage » : le "
                f"MI ne tourne pas après cet arrêt accepté ({stop})")
        essai("C-C", course_c)
    except Exception as e:  # noqa: BLE001 - une exception ici est un échec du test
        traceback.print_exc()
        chk(False, f"le test s'est interrompu sur une exception ({e!r})")
    finally:
        mi_models.modeles_disponibles = vrai_dispo
        if langue_avant is None:
            os.environ.pop("EEG_LANGUE", None)
        else:
            os.environ["EEG_LANGUE"] = langue_avant
        shutil.rmtree(vide, ignore_errors=True)
        gc.collect()

    print(f"[smoke-connexion-froid] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_connexion():
    """« Connecter une application » contre un VRAI moteur en écoute SUR DEMANDE, celle de la
    console. Une vraie application : un outlet LSL de ce processus, sous un nom de flux propre au
    test (un moteur oublié sur le poste écoute le nom par défaut).

    Vérifie : personne n'est entendu avant « Connecter » ; la recherche liste sans ouvrir ;
    pendant la connexion la console n'a droit qu'à sa liste blanche, « Enregistrer les
    verdicts » compris ; un mode À MODÈLE (le MI, trois modèles entraînés à la volée dans un
    dossier temporaire : le plus récent, celui que l'application suggère et celui que la console
    choisit sont trois modèles différents) attend que la console choisisse son modèle, démarre
    avec lui, se relance avec un autre, et le `model` de l'application n'est qu'une suggestion ;
    un `stop_mode` de l'application annule l'attente ; le voyant « lu » ; la fin (départ de
    l'application, puis « Déconnecter ») arrête ce que l'application a démarré, et seulement ça :
    un mode d'avant qu'elle « redémarre » continue. Le moteur seul refuse la recherche.

    Une commande RÉSEAU qui arrive sans connexion (avant la première, après la dernière) est
    refusée par le moteur lui-même, pas seulement par l'écoute fermée ; le moteur seul, en écoute
    permanente, l'accepte toujours. Les courses et les refus rares sont dans
    `[smoke-connexion-froid]`, déterministes.
    """
    import gc
    import threading
    import traceback

    from pylsl import IRREGULAR_RATE, StreamInfo, StreamInlet, StreamOutlet, resolve_byprop

    from core import mi_models
    from core.i18n import choisir_langue
    from core.lsl_io import _source_id
    from core.mi_decoder import MI_LABELS, MIModel, synth_mi_trial

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    def attendre(cond, delai_s=5.0):
        echeance = time.perf_counter() + delai_s
        while not cond() and time.perf_counter() < echeance:
            time.sleep(0.05)
        return cond()

    def cle(texte):
        return getattr(texte, "cle", None)

    pid = os.getpid()
    nom = f"{NOM_FLUX_COMMANDES}_smoke_connexion_{pid}"
    instance = f"smoke-connexion-{socket.gethostname()}-{pid}"
    nom_app, nom_app2 = f"smoke-connexion-app-{pid}", f"smoke-connexion-app2-{pid}"
    tmp = tempfile.mkdtemp(prefix="smoke-connexion-")
    vrai_dispo = mi_models.modeles_disponibles
    langue_avant = os.environ.get("EEG_LANGUE")
    srv = fil = entree = app = app2 = lecteur = froid = None
    try:
        choisir_langue("fr")
        # Trois modèles MI entraînés à la volée, dans le dossier du test : jamais `data/`. Datés
        # à la main, c le plus récent : c'est lui que le moteur prend PAR DÉFAUT. L'application
        # suggère b, la console choisit a puis b. Trois noms différents : un test ne peut pas
        # passer parce que deux d'entre eux se confondent.
        chemins = {}
        maintenant = time.time()
        for graine, lettre in ((0, "a"), (1, "b"), (2, "c")):
            rng = np.random.default_rng(graine)
            epochs, y = [], []
            for label in MI_LABELS:
                for _ in range(8):
                    epochs.append(synth_mi_trial(label, rng=rng))
                    y.append(label)
            chemins[lettre] = os.path.join(tmp, f"mi_model_smoke_{lettre}.joblib")
            MIModel(fs=250.0).fit(np.asarray(epochs), np.asarray(y)).save(chemins[lettre])
            date = maintenant - {"a": 30.0, "b": 20.0, "c": 10.0}[lettre]
            os.utime(chemins[lettre], (date, date))
        mi_models.modeles_disponibles = lambda d=tmp: vrai_dispo(d)
        chk(mi_models.modeles_disponibles()[0] == chemins["c"],
            "le modèle le plus récent, celui du moteur par défaut, est c")

        # 0. Le moteur seul écoute en permanence : rien à chercher, rien à connecter.
        froid = EngineServer(synthetic=True, modes=(), instance=f"{instance}-permanent",
                             flux_commandes=f"{nom}_permanent")
        refus = froid.submit("chercher_applications", on=True)
        chk(not refus["accepted"] and cle(refus["reason"]) == "moteur.connexion.ecoute_permanente",
            f"0. le moteur seul refuse la recherche : il écoute déjà tout ({refus})")
        ack = froid.submit("set_params", reseau=("cx-permanent", "set_params", "ssvep"),
                           id="ssvep", params={})
        chk(ack["accepted"],
            f"...et il accepte toujours une commande réseau, sans aucune connexion ({ack})")
        froid.retirer_flux()
        froid.close()
        froid = None

        srv = EngineServer(synthetic=True, modes=("raw",), instance=instance,
                           data_dir=os.path.join(tmp, "data"),
                           seances_dir=os.path.join(tmp, "seances"),
                           flux_commandes=nom, ecoute="sur_demande")
        file_vue = []
        vraie_file = srv._mettre_en_file

        def espion(command, params, reseau=None):
            file_vue.append((command, dict(params), reseau))
            vraie_file(command, params, reseau)

        srv._mettre_en_file = espion
        fil = threading.Thread(target=srv.run, daemon=True, name="smoke-connexion-moteur",
                               kwargs={"duration_s": 300.0, "baseline_s": 1.0, "warmup_s": 0.5})
        fil.start()
        attendre(lambda: srv.acquisition_ouverte and srv.pilotage.vivant, 20.0)
        if not srv.pilotage.vivant:
            raise RuntimeError("le moteur n'a pas démarré son écoute")
        info = next(iter(resolve_byprop("source_id", _source_id(_SUFFIXE_REPONSES, instance),
                                        timeout=5.0)), None)
        entree = StreamInlet(info, recover=False)
        entree.open_stream(timeout=5.0)

        def envoyer(sortie, commande, delai_s=5.0):
            """Envoie une commande JSON et rend SA réponse (par « ref »), ou None."""
            sortie.push_sample([json.dumps(commande)])
            echeance = time.perf_counter() + delai_s
            while time.perf_counter() < echeance:
                ech, _ts = entree.pull_sample(timeout=0.05)
                if ech is None:
                    continue
                try:
                    rep = json.loads(ech[0])
                except ValueError:
                    continue
                if rep.get("ref") == commande.get("ref") and "event" not in rep:
                    return rep
            return None

        def lire_messages(delai_s, jusqua=None):
            """Les messages JSON lus sur le flux de réponses pendant `delai_s` secondes au plus,
            ou jusqu'au premier pour lequel `jusqua(message)` est vrai."""
            lus, echeance = [], time.perf_counter() + delai_s
            while time.perf_counter() < echeance:
                ech, _ts = entree.pull_sample(timeout=0.05)
                if ech is None:
                    continue
                try:
                    lus.append(json.loads(ech[0]))
                except ValueError:
                    continue
                if jusqua is not None and jusqua(lus[-1]):
                    break
            return lus

        def refus_hors_connexion(etape):
            """Une commande RÉSEAU sans connexion : le moteur la refuse lui-même."""
            rep = srv.submit("set_params", reseau=("cx-hors", "set_params", "ssvep"),
                             id="ssvep", params={})
            chk(not rep["accepted"] and cle(rep["reason"]) == "moteur.connexion.pas_connectee",
                f"{etape} une commande réseau sans connexion est refusée par le moteur ({rep})")

        app = StreamOutlet(StreamInfo(nom, "Markers", 1, IRREGULAR_RATE, "string", nom_app))
        etat = srv.snapshot()
        chk(etat.get("ecoute") == "sur_demande" and etat.get("connexion") is None
            and etat.get("applications") == [] and etat.get("fin_connexion") is None,
            "1. la console écoute sur demande : aucune connexion, rien de listé")
        chk(not app.wait_for_consumers(1.5),
            "...et personne n'écoute l'application avant la recherche")
        refus_hors_connexion("...")
        refus = srv.submit("connecter", uid="inconnu")
        chk(not refus["accepted"] and cle(refus["reason"]) == "moteur.connexion.introuvable",
            f"2. on ne connecte pas une application que la recherche ne voit pas ({refus})")

        chk(srv.submit("chercher_applications", on=True)["accepted"]
            and attendre(lambda: any(a["nom"] == nom_app
                                     for a in srv.snapshot()["applications"])),
            "3. la recherche liste l'application de cette machine, par son nom")
        chk(not app.wait_for_consumers(1.0), "...sans ouvrir son flux")

        chk(srv.submit("start_mode", id="neuro")["accepted"]
            and attendre(lambda: "neuro" in srv.active),
            "4. la console démarre le Neuro AVANT la connexion")

        srv.candidat = {"modele": "faux"}
        refus = srv.submit("connecter", uid=srv.snapshot()["applications"][0]["uid"])
        srv.candidat = None
        chk(not refus["accepted"] and cle(refus["reason"]) == "moteur.connexion.candidat",
            f"5. connecter est refusé tant qu'un modèle attend « Enregistrer » ({refus})")

        uid = next(a["uid"] for a in srv.snapshot()["applications"] if a["nom"] == nom_app)
        ack = srv.submit("connecter", uid=uid)
        chk(ack["accepted"] and ack.get("nom") == nom_app and app.wait_for_consumers(5.0)
            and srv.snapshot()["applications"] == []
            and attendre(lambda: (srv.snapshot()["connexion"] or {}).get("branchee")),
            f"6. connecter ouvre son flux, arrête la recherche, et le moteur la dit branchée "
            f"({ack})")
        chk((srv.snapshot()["connexion"] or {}).get("illisible") is False,
            "...son nom se lit : la connexion n'est pas marquée « illisible »")

        # 7. La liste blanche : toute autre commande de la console est refusée, pour CETTE raison.
        passent = []
        for commande in srv.COMMANDS:
            if commande in srv.PERMISES_PENDANT_CONNEXION:
                continue
            rep = srv.submit(commande, id="ssvep")
            if rep.get("accepted") or cle(rep.get("reason")) != "moteur.connexion.console_verrouillee":
                passent.append(commande)
        chk(passent == [], f"7. pendant la connexion, la console n'a droit qu'à sa liste blanche "
                           f"(passées : {passent})")
        chk(set(srv.PERMISES_PENDANT_CONNEXION) == {"deconnecter", "lancer_decodage", "stop",
                                                     "start_enregistrement",
                                                     "stop_enregistrement"},
            f"...et la liste blanche est exactement celle du contrat "
            f"({sorted(srv.PERMISES_PENDANT_CONNEXION)})")

        # 8. L'application règle et démarre le SSVEP (sans modèle : il démarre tout de suite).
        rep = envoyer(app, {"cmd": "set_params", "mode": "ssvep", "ref": "cx-1",
                            "params": {"targets_on": "physical", "freqs": [13.0, 15.0]}})
        chk(rep is not None and rep["accepted"] and rep.get("deferred") is True,
            f"8. l'application règle le SSVEP ({rep})")
        rep = envoyer(app, {"cmd": "start_mode", "mode": "ssvep", "ref": "cx-2"})
        chk(rep is not None and rep["accepted"] and not rep.get("deferred")
            and attendre(lambda: "ssvep" in srv.active),
            f"...et le démarre : sans modèle, aucune attente ({rep})")
        cx = srv.snapshot()["connexion"] or {}
        chk(cx.get("demarres") == ["ssvep"] and "ssvep" in (cx.get("regles") or ()),
            f"...le moteur note ce qu'elle a démarré et réglé ({cx})")
        # Le Neuro tournait AVANT la connexion : le `start_mode` de l'application (idempotent)
        # ne le fait pas compter parmi ce qu'elle a démarré. La fin (14) ne l'arrête donc pas.
        rep = envoyer(app, {"cmd": "start_mode", "mode": "neuro", "ref": "cx-neuro"})
        cx = srv.snapshot()["connexion"] or {}
        chk(rep is not None and rep["accepted"] and rep.get("already_running") is True
            and cx.get("demarres") == ["ssvep"],
            f"...un mode d'avant qu'elle « redémarre » n'est pas à elle ({rep}, "
            f"{cx.get('demarres')})")

        # 9. Le voyant « lu » : personne, puis un lecteur.
        chk(srv.snapshot()["modes_state"]["ssvep"].get("lu") is False,
            "9. personne ne lit encore le flux décodé du SSVEP")
        info_dec = next(iter(resolve_byprop("source_id", _source_id("decoded_ssvep", instance),
                                            timeout=5.0)), None)
        lecteur = StreamInlet(info_dec, recover=False)
        lecteur.open_stream(timeout=5.0)
        chk(attendre(lambda: srv.snapshot()["modes_state"]["ssvep"].get("lu") is True),
            "...un lecteur ouvert : le voyant passe à « lu »")
        # « Enregistrer les verdicts » est permis pendant la connexion : il observe sans rien
        # changer. Accepté, puis APPLIQUÉ par la boucle, puis arrêté.
        ack = srv.submit("start_enregistrement", stream="decoded_ssvep")
        actif = attendre(lambda: (srv.snapshot()["enregistrement"] or {}).get("actif") is True)
        stop = srv.submit("stop_enregistrement")
        chk(ack["accepted"] and actif and stop["accepted"],
            f"...« Enregistrer les verdicts » marche pendant la connexion ({ack}, {stop})")

        # 10. Le MI, mode À MODÈLE : accepté, mais EN ATTENTE ; le `model` envoyé est une
        # suggestion.
        demande_mi = {"cmd": "start_mode", "mode": "mi", "ref": "cx-mi",
                      "params": {"model": "mi_model_smoke_b.joblib"}}
        rep = envoyer(app, demande_mi)
        avert = (rep or {}).get("warning") or ""
        chk(rep is not None and rep["accepted"] and rep.get("deferred") is True
            and "choose a model" in avert and "suggestion" in avert,
            f"10. le MI est accepté EN ATTENTE, la réserve le dit en anglais ({rep})")
        chk(rep is not None and "model" in (rep.get("params") or {})
            and rep["params"]["model"] is None,
            f"...sa réponse ne nomme AUCUN modèle : ni le défaut (c), ni la suggestion (b) "
            f"({(rep or {}).get('params')})")
        # Pas d'attente ici : `_tourneront` lit aussi la file, un démarrage mis en file se verrait.
        cx = srv.snapshot()["connexion"] or {}
        chk(srv._tourneront(["mi"]) == []
            and cx.get("en_attente") == {"mi": {"suggestion": "mi_model_smoke_b.joblib"}}
            and srv.reglages["mi"]["model"] == chemins["c"],
            f"...il ne démarre pas, la suggestion est gardée À CÔTÉ du magasin, qui garde le "
            f"défaut ({cx.get('en_attente')}, {os.path.basename(srv.reglages['mi']['model'])})")
        # Un `stop_mode` de l'application annule l'attente : « Lancer le décodage » n'a alors
        # plus rien à lancer. Puis elle redemande le MI, pour la suite.
        rep = envoyer(app, {"cmd": "stop_mode", "mode": "mi", "ref": "cx-mi-stop"})
        refus = srv.submit("lancer_decodage", id="mi", model=chemins["a"])
        chk(rep is not None and rep["accepted"]
            and (srv.snapshot()["connexion"] or {}).get("en_attente") == {}
            and not refus["accepted"]
            and cle(refus["reason"]) == "moteur.connexion.pas_demande",
            f"...un `stop_mode` de l'application annule l'attente, « Lancer » est refusé "
            f"({rep}, {refus})")
        rep = envoyer(app, demande_mi)
        chk(rep is not None and rep["accepted"] and rep.get("deferred") is True
            and "mi" in ((srv.snapshot()["connexion"] or {}).get("en_attente") or {}),
            f"...elle redemande le MI : il attend de nouveau ({rep})")

        # 11. « Lancer le décodage » avec le modèle a : le démarrage porte le jeton de
        # l'application (un échec lui arriverait sur SA commande).
        n = len(file_vue)
        ack = srv.submit("lancer_decodage", id="mi", model=chemins["a"])
        jetons = [r for c, p, r in file_vue[n:] if c == "start_mode" and p.get("ids") == ["mi"]]
        chk(ack["accepted"] and jetons and jetons[0] and jetons[0][0] == "cx-mi",
            f"11. « Lancer le décodage » démarre le MI avec le jeton de l'application ({ack}, "
            f"{jetons})")
        chk(attendre(lambda: "mi" in srv.active
                     and srv.active["mi"].params.get("model") == chemins["a"]),
            "...sur le modèle choisi dans la console")
        cx = srv.snapshot()["connexion"] or {}
        chk(cx.get("en_attente") == {} and "mi" in (cx.get("demarres") or ()),
            f"...il n'attend plus, et compte parmi ce que l'application a démarré ({cx})")

        # 12. Relancer avec le modèle b.
        ack = srv.submit("lancer_decodage", id="mi", model=chemins["b"])
        chk(ack["accepted"] and ack.get("relance") is True
            and attendre(lambda: srv.active.get("mi") is not None
                         and srv.active["mi"].params.get("model") == chemins["b"]),
            f"12. « Relancer avec ce modèle » relance le MI sur le modèle b ({ack})")

        # 13. Un `model` envoyé par `set_params` n'est pas appliqué non plus.
        # Pas d'attente : le magasin est ce que la boucle appliquera.
        rep = envoyer(app, {"cmd": "set_params", "mode": "mi", "ref": "cx-3",
                            "params": {"model": "mi_model_smoke_a.joblib"}})
        chk(rep is not None and rep["accepted"] and "suggestion" in (rep.get("warning") or "")
            and srv.reglages["mi"]["model"] == chemins["b"]
            and (rep.get("params") or {}).get("model") == "mi_model_smoke_b.joblib",
            f"13. un `model` dans `set_params` reste une suggestion : le MI garde celui de la "
            f"console, et la réponse le nomme ({rep})")

        # 14. L'application part : ce qu'elle a démarré s'arrête, le Neuro (d'avant) continue.
        app = None
        gc.collect()
        chk(attendre(lambda: srv.snapshot()["connexion"] is None, 10.0),
            "14. une application qui disparaît termine la connexion")
        fin = srv.snapshot()["fin_connexion"] or {}
        chk(fin.get("raison") == "partie" and fin.get("nom") == nom_app
            and sorted(fin.get("arretes") or ()) == ["mi", "ssvep"],
            f"...la fin dit pourquoi, et ce qu'elle arrête ({fin})")
        # `snapshot()` rend une COPIE : la console qui l'écrit ne change pas l'état du moteur.
        fin["raison"] = "modifiée par la console"
        chk(srv.snapshot()["fin_connexion"]["raison"] == "partie"
            and isinstance(fin.get("arretes"), tuple),
            "...et `snapshot()` n'en rend qu'une copie")
        chk(attendre(lambda: "ssvep" not in srv.active and "mi" not in srv.active)
            and "neuro" in srv.active and "raw" in srv.active,
            f"...le SSVEP et le MI s'arrêtent ; le Neuro et le brut, d'avant, continuent "
            f"({sorted(srv.active)})")
        # Partie d'elle-même, elle ne lit plus rien ; une copie relancée sous le même nom
        # prendrait le message pour elle.
        chk(not any(m.get("event") == "disconnected" for m in lire_messages(0.5)),
            "...et aucun « disconnected » n'est publié pour une application partie")

        # 15. Une seconde application, puis « Déconnecter ».
        app2 = StreamOutlet(StreamInfo(nom, "Markers", 1, IRREGULAR_RATE, "string", nom_app2))
        srv.submit("chercher_applications", on=True)
        attendre(lambda: any(a["nom"] == nom_app2 for a in srv.snapshot()["applications"]))
        uid2 = next((a["uid"] for a in srv.snapshot()["applications"] if a["nom"] == nom_app2),
                    None)
        chk(srv.submit("connecter", uid=uid2)["accepted"] and app2.wait_for_consumers(5.0),
            "15. une seconde application se connecte")
        rep = envoyer(app2, {"cmd": "start_mode", "mode": "ssvep", "ref": "cx-4"})
        chk(rep is not None and rep["accepted"] and attendre(lambda: "ssvep" in srv.active),
            f"...et démarre le SSVEP ({rep})")
        ack = srv.submit("deconnecter")
        chk(ack["accepted"] and ack.get("arretes") == ["ssvep"],
            f"...« Déconnecter » arrête le SSVEP qu'elle a démarré ({ack})")
        # L'application n'envoie rien (elle attendrait ses décisions) : le moteur le lui DIT.
        adieux = [m for m in lire_messages(2.0, jusqua=lambda m: m.get("event") == "disconnected")
                  if m.get("event") == "disconnected"]
        chk(adieux == [{"ref": None, "event": "disconnected", "cause": "console", "app": nom_app2,
                        "stopped": ["ssvep"],
                        "reason": pour_le_contrat(tr("moteur.reseau.deconnectee"))}],
            f"...et le DIT à l'application sur le flux de réponses, avec son nom et le SSVEP "
            f"arrêté, sans qu'elle ait rien envoyé ({adieux})")
        fin = srv.snapshot()["fin_connexion"] or {}
        # Le flux est refermé, mais LSL ne le dit à l'application qu'APRÈS un envoi :
        # `have_consumers()` reste vrai tant qu'elle n'envoie rien (mesuré). On envoie donc une
        # commande sans effet ; personne ne la lit.
        referme = False
        echeance = time.perf_counter() + 2.0
        while not referme and time.perf_counter() < echeance:
            app2.push_sample(['{"cmd": "set_params", "mode": "ssvep", "params": {}, '
                              '"ref": "cx-apres-la-fin"}'])
            time.sleep(0.2)
            referme = not app2.have_consumers()
        chk(fin.get("raison") == "deconnectee" and referme
            and attendre(lambda: "ssvep" not in srv.active) and "neuro" in srv.active,
            f"...son flux est refermé (LSL le dit à l'application à son envoi suivant), et le "
            f"Neuro continue ({fin})")
        chk(srv.submit("stop_mode", id="neuro")["accepted"],
            "16. déconnectée, la console reprend la main")
        refus = srv.submit("deconnecter")
        chk(not refus["accepted"] and cle(refus["reason"]) == "moteur.connexion.aucune",
            f"...et « Déconnecter » sans connexion est refusé ({refus})")
        refus_hors_connexion("...après la fin,")
    except Exception as e:  # noqa: BLE001 - une exception ici est un échec du test
        traceback.print_exc()
        chk(False, f"le test s'est interrompu sur une exception ({e!r})")
    finally:
        mi_models.modeles_disponibles = vrai_dispo
        if langue_avant is None:
            os.environ.pop("EEG_LANGUE", None)
        else:
            os.environ["EEG_LANGUE"] = langue_avant
        try:
            lecteur = entree = app = app2 = None
            if froid is not None:
                froid.retirer_flux()
                froid.close()
            if srv is not None:
                srv.stop()
                if fil is not None:
                    fil.join(timeout=15.0)
                srv.retirer_flux()
                # L'espion cite le moteur (par `vraie_file`) et vit SUR lui : un cycle, que seul
                # le ramasse-miettes casserait, à une date quelconque. Retiré, puis ramassé ici.
                srv.__dict__.pop("_mettre_en_file", None)
                srv = vraie_file = espion = None
                gc.collect()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"[smoke-connexion] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_deconnexion():
    """« Déconnecter » et l'arrêt du moteur, vus par le CLIENT EXEMPLE
    (`examples/control_client.py`) dans un AUTRE processus, contre un vrai moteur en écoute sur
    demande (celle de la console).

    Le client attend ses décisions sans rien envoyer. LSL ne lui dirait qu'on ne le lit plus qu'à
    son prochain envoi (`have_consumers()` reste vrai, mesuré) : c'est le message
    « disconnected » du moteur qui le lui dit. Vérifie :
    1. « Déconnecter » pendant que le client attend les premières décisions du SSVEP (la chauffe
       dure plus longtemps que le test) : il le dit en moins de 5 s, n'envoie pas de `stop_mode`,
       et sort avec le code 1 — pas au bout de son délai de 60 s. Juste avant, deux messages
       « disconnected » qui ne sont PAS les siens — pour une autre application de son moteur, et
       pour lui mais venu d'un AUTRE moteur de la machine — ne l'arrêtent pas : le flux de
       réponses est commun à toutes les applications de la machine ;
    2. le moteur s'arrête (la console qu'on ferme) pendant que le client attend, SANS limite,
       qu'on choisisse le modèle de son MI : il le dit en moins de 5 s et sort avec le code 1 —
       sans ce message, il attendrait pour toujours ;
    3. lancé avec `--watch`, le client continue de lire les décisions après les trois premières,
       et « Déconnecter » l'arrête quand même : il le dit en moins de 5 s, n'envoie pas de
       `stop_mode`, et sort avec le code 1 ;
    4. « Déconnecter » pendant que le client attend la réponse de son étape 2 (perdue en route,
       exprès) : il échoue À L'ÉTAPE 2 sur la déconnexion, en moins de 2 s — pas au bout de ses
       5 s d'attente, sur « no reply ».
    Le modèle MI est entraîné à la volée dans un dossier temporaire, jamais dans `data/`.
    """
    import gc
    import subprocess
    import threading
    import traceback

    from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet

    from core import mi_models
    from core.i18n import choisir_langue
    from core.lsl_io import _source_id
    from core.mi_decoder import MI_LABELS, MIModel, synth_mi_trial
    from core.pilotage import deconnexion

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    def attendre(cond, delai_s=5.0):
        echeance = time.perf_counter() + delai_s
        while not cond() and time.perf_counter() < echeance:
            time.sleep(0.05)
        return cond()

    pid = os.getpid()
    nom = f"{NOM_FLUX_COMMANDES}_smoke_deconnexion_{pid}"
    instance = f"smoke-deconnexion-{socket.gethostname()}-{pid}"
    racine = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    exemple = os.path.join(racine, "examples", "control_client.py")

    class _Client:
        """Le client exemple dans un AUTRE processus. Un fil lit sa sortie ligne par ligne, avec
        l'instant de chacune : on mesure quand il a dit ce qu'il a vu."""

        def __init__(self, *args):
            self.lignes = []            # (time.perf_counter(), ligne)
            # `PYTHONUNBUFFERED` : chaque ligne arrive quand le client l'écrit.
            self.proc = subprocess.Popen(
                [sys.executable, exemple, "--stream", nom, *args],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                       "PYTHONUNBUFFERED": "1"})
            self.fil = threading.Thread(target=self._lire, daemon=True,
                                        name="smoke-deconnexion-client")
            self.fil.start()

        def _lire(self):
            for ligne in self.proc.stdout:
                self.lignes.append((time.perf_counter(), ligne.rstrip("\n")))

        def vu(self, texte):
            """L'instant de la première ligne qui contient `texte`, ou None."""
            return next((t for t, ligne in list(self.lignes) if texte in ligne), None)

        def nom(self):
            """Le nom que le client donne à son flux de commandes, lu dans ce qu'il imprime (le
            PID d'un lanceur de Python ne serait pas forcément le sien)."""
            for _t, ligne in list(self.lignes):
                trouve = re.search(r"pick '(control-client-\d+-[0-9a-f]+)'", ligne)
                if trouve:
                    return trouve.group(1)
            return None

        def texte(self):
            return "\n".join(ligne for _t, ligne in list(self.lignes))

        def finir(self, delai_s):
            """Le code de sortie, ou None si le client tourne encore après `delai_s` (il est
            alors tué)."""
            try:
                code = self.proc.wait(timeout=delai_s)
            except subprocess.TimeoutExpired:
                code = None
            self.tuer()
            return code

        def tuer(self):
            if self.proc.poll() is None:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    pass
            self.fil.join(timeout=2.0)

    def montrer(client):
        print("  --- sortie du client exemple (sans les lignes INFO de liblsl) ---")
        for ligne in client.texte().splitlines():
            if " INFO| " not in ligne:
                print(f"  | {ligne}")
        print("  --- fin de la sortie ---")

    class _ParLeFil:
        """Fait publier des messages sur le flux de réponses du moteur par SON FIL D'ÉCOUTE, le
        seul qui y écrit : ils partent au tour suivant, avec les échecs. `retirer()` rend au
        moteur son geste d'origine."""

        def __init__(self, pilotage):
            self.pilotage = pilotage
            self.a_publier = queue.SimpleQueue()
            self.publies = []            # ce que `_publier` a rendu, message par message
            vrai = pilotage._publier_echecs

            def publier_echecs():
                while True:
                    try:
                        message = self.a_publier.get_nowait()
                    except queue.Empty:
                        break
                    self.publies.append(pilotage._publier(message))
                vrai()

            pilotage._publier_echecs = publier_echecs

        def retirer(self):
            self.pilotage.__dict__.pop("_publier_echecs", None)

    def sans_reaction(client, n_avant, delai_s):
        """Vrai si, pendant `delai_s`, le client tourne toujours et n'a rien dit de plus d'une
        déconnexion que les `n_avant` lignes qui en parlaient déjà."""
        time.sleep(delai_s)
        dits = [ligne for _t, ligne in list(client.lignes) if "disconnected" in ligne]
        return client.proc.poll() is None and len(dits) == n_avant

    tmp = tempfile.mkdtemp(prefix="smoke-deconnexion-")
    vrai_dispo = mi_models.modeles_disponibles
    langue_avant = os.environ.get("EEG_LANGUE")
    srv = fil = autre = None
    clients = []
    try:
        choisir_langue("fr")
        rng = np.random.default_rng(0)
        epochs, y = [], []
        for label in MI_LABELS:
            for _ in range(8):
                epochs.append(synth_mi_trial(label, rng=rng))
                y.append(label)
        MIModel(fs=250.0).fit(np.asarray(epochs), np.asarray(y)).save(
            os.path.join(tmp, "mi_model_smoke_deconnexion.joblib"))
        mi_models.modeles_disponibles = lambda d=tmp: vrai_dispo(d)

        srv = EngineServer(synthetic=True, modes=("raw",), instance=instance,
                           data_dir=os.path.join(tmp, "data"),
                           seances_dir=os.path.join(tmp, "seances"),
                           flux_commandes=nom, ecoute="sur_demande")
        # La chauffe (120 s) dure plus longtemps que le test : le SSVEP ne publie aucune
        # décision, et le client les attend sans rien envoyer.
        fil = threading.Thread(target=srv.run, daemon=True, name="smoke-deconnexion-moteur",
                               kwargs={"duration_s": 300.0, "baseline_s": 1.0, "warmup_s": 120.0})
        fil.start()
        attendre(lambda: srv.acquisition_ouverte and srv.pilotage.vivant, 20.0)
        if not srv.pilotage.vivant:
            raise RuntimeError("le moteur n'a pas démarré son écoute")

        def connecter(client):
            """« Connecter une application » : chercher, puis choisir CE client."""
            if not attendre(lambda: client.nom() is not None, 30.0):
                return False
            srv.submit("chercher_applications", on=True)
            attendre(lambda: any(a["nom"] == client.nom()
                                 for a in srv.snapshot()["applications"]), 15.0)
            uid = next((a["uid"] for a in srv.snapshot()["applications"]
                        if a["nom"] == client.nom()), None)
            return uid is not None and srv.submit("connecter", uid=uid)["accepted"]

        # 1. « Déconnecter » pendant que le client attend les décisions du SSVEP. Un AUTRE moteur
        # de la machine publie lui aussi son flux de réponses (un moteur oublié, par exemple) :
        # créé avant le client, pour que celui-ci l'écoute.
        autre = StreamOutlet(StreamInfo(NOM_FLUX_REPONSES, "Markers", 1, IRREGULAR_RATE,
                                        "string", _source_id(_SUFFIXE_REPONSES,
                                                             f"{instance}-autre")))
        c1 = _Client("--timeout", "60")
        clients.append(c1)
        chk(connecter(c1), "1. le client exemple est connecté")
        chk(attendre(lambda: c1.vu("status: 'ssvep' is running") is not None, 30.0)
            and "ssvep" in srv.active,
            "...il a démarré le SSVEP et attend ses premières décisions (la chauffe dure plus "
            "longtemps que le test)")
        time.sleep(1.0)                 # le client est dans sa boucle d'attente des décisions
        # Deux messages « disconnected » qui ne sont pas les siens. Le premier, sur le flux de
        # réponses de SON moteur, pour une autre application dont le nom commence comme le sien
        # (deux PID, 123 et 1230) ; le second, à son nom, sur celui de l'autre moteur.
        nom_c1 = c1.nom() or "control-client-?"
        deja = len([ligne for _t, ligne in list(c1.lignes) if "disconnected" in ligne])
        par_le_fil = _ParLeFil(srv.pilotage)
        try:
            par_le_fil.a_publier.put(deconnexion(f"{nom_c1}0", ("ssvep",), "console"))
            publie = attendre(lambda: par_le_fil.publies == [True], 2.0)
            chk(publie and sans_reaction(c1, deja, 2.5) and "ssvep" in srv.active,
                f"...un « disconnected » de son moteur pour une AUTRE application ({nom_c1}0) : "
                f"il l'ignore, ne s'arrête pas et ne dit rien (publié : {par_le_fil.publies})")
        finally:
            par_le_fil.retirer()
        ecoute = autre.wait_for_consumers(2.0)
        autre.push_sample([json.dumps(deconnexion(nom_c1, ("ssvep",), "console"))])
        chk(ecoute and sans_reaction(c1, deja, 2.5) and "ssvep" in srv.active,
            f"...un « disconnected » à SON nom, venu d'un AUTRE moteur de la machine (qu'il "
            f"écoute : {ecoute}) : il l'ignore aussi")
        t_clic = time.perf_counter()
        ack = srv.submit("deconnecter")
        code = c1.finir(15.0)
        sortie = c1.texte()
        vu = c1.vu("disconnected in the console: the engine stopped what we started")
        delai = None if vu is None else vu - t_clic
        chk(ack["accepted"] and ack.get("arretes") == ["ssvep"],
            f"...« Déconnecter » arrête le SSVEP qu'il a démarré ({ack})")
        # Jamais négatif : une ligne écrite AVANT le clic serait une réaction à autre chose.
        chk(delai is not None and 0.0 <= delai < 5.0,
            f"...le client dit qu'il est déconnecté en moins de 5 s, sans rien avoir envoyé "
            f"({'jamais' if delai is None else f'{delai:.2f} s'} ; son délai est de 60 s)")
        etape1_ok = (code == 1 and "FAILED at step 6: disconnected in the console." in sortie
                     and "stop_mode: skipped" in sortie and '"cmd": "stop_mode"' not in sortie)
        chk(etape1_ok,
            f"...il n'envoie pas de `stop_mode` dans le vide, et sort avec le code 1 (code "
            f"{code})")
        chk(attendre(lambda: "ssvep" not in srv.active), "...et le SSVEP est arrêté")
        if delai is None or not etape1_ok:
            montrer(c1)

        # 2. Le moteur s'arrête pendant que le client attend, sans limite, le choix du modèle.
        autre = None                    # l'autre moteur s'en va : les clients suivants l'ignorent
        c2 = _Client("--mode", "mi", "--timeout", "60")
        clients.append(c2)
        chk(connecter(c2), "2. un second client exemple est connecté")
        chk(attendre(lambda: c2.vu('"deferred": this mode needs a MODEL') is not None, 30.0),
            "...son MI attend qu'on choisisse le modèle, sans limite de temps")
        time.sleep(1.0)                 # le client est dans sa boucle d'attente du statut
        t_arret = time.perf_counter()
        srv.stop()
        code = c2.finir(15.0)
        sortie = c2.texte()
        vu = c2.vu("the engine stopped (the console closed, or server.py stopped)")
        delai = None if vu is None else vu - t_arret
        chk(delai is not None and 0.0 <= delai < 5.0,
            f"...le moteur s'arrête : le client le dit en moins de 5 s "
            f"({'jamais' if delai is None else f'{delai:.2f} s'})")
        etape2_ok = (code == 1 and "FAILED at step 6: the engine stopped." in sortie
                     and '"cmd": "stop_mode"' not in sortie)
        chk(etape2_ok, f"...et sort avec le code 1, sans `stop_mode` (code {code})")
        if delai is None or not etape2_ok:
            montrer(c2)

        # 3. `--watch` : le client lit les décisions sans s'arrêter, puis « Déconnecter ». Un
        # moteur neuf, à la chauffe courte : le MI publie ses décisions en quelques secondes.
        fil.join(timeout=15.0)
        srv.retirer_flux()
        srv = None
        gc.collect()
        srv = EngineServer(synthetic=True, modes=("raw",), instance=instance,
                           data_dir=os.path.join(tmp, "data"),
                           seances_dir=os.path.join(tmp, "seances"),
                           flux_commandes=nom, ecoute="sur_demande")
        fil = threading.Thread(target=srv.run, daemon=True, name="smoke-deconnexion-moteur-3",
                               kwargs={"duration_s": 300.0, "baseline_s": 1.0, "warmup_s": 0.5})
        fil.start()
        attendre(lambda: srv.acquisition_ouverte and srv.pilotage.vivant, 20.0)
        c3 = _Client("--mode", "mi", "--watch", "--timeout", "60")
        clients.append(c3)
        chk(connecter(c3), "3. un client exemple lancé avec --watch est connecté")
        chk(attendre(lambda: c3.vu('"deferred": this mode needs a MODEL') is not None, 30.0),
            "...son MI attend qu'on choisisse le modèle")
        lance = srv.submit("lancer_decodage", id="mi",
                           model=os.path.join(tmp, "mi_model_smoke_deconnexion.joblib"))
        chk(lance["accepted"] and attendre(lambda: c3.vu("decision 6:") is not None, 30.0),
            f"...le modèle choisi, il lit ses trois décisions puis CONTINUE de les lire "
            f"({lance.get('reason') or 'lancé'})")
        t_clic = time.perf_counter()
        ack = srv.submit("deconnecter")
        code = c3.finir(15.0)
        sortie = c3.texte()
        vu = c3.vu("disconnected in the console: the engine stopped what we started")
        delai = None if vu is None else vu - t_clic
        etape3_ok = (ack["accepted"] and delai is not None and 0.0 <= delai < 5.0 and code == 1
                     and "FAILED at step 6: disconnected in the console." in sortie
                     and '"cmd": "stop_mode"' not in sortie)
        chk(etape3_ok,
            f"...« Déconnecter » pendant qu'il lit : il le dit en moins de 5 s, n'envoie pas de "
            f"`stop_mode`, et sort avec le code 1 "
            f"({'jamais' if delai is None else f'{delai:.2f} s'}, code {code})")
        if not etape3_ok:
            montrer(c3)

        # 4. « Déconnecter » pendant que le client attend une RÉPONSE (étape 2). Le moteur ne
        # publie pas celle-là — perdue en route, comme LSL perd une réponse publiée trop tôt : le
        # client attendrait sinon ses 5 s, puis échouerait sur « no reply », une fausse piste.
        vrai_publier = srv.pilotage._publier
        perdues = []

        def publier_sauf_l_etape_2(message):
            if (not perdues and isinstance(message, dict) and message.get("cmd") == "set_params"
                    and str(message.get("ref") or "").startswith("control-client-")):
                perdues.append(message)
                return True
            return vrai_publier(message)

        srv.pilotage._publier = publier_sauf_l_etape_2
        try:
            c4 = _Client("--timeout", "60")
            clients.append(c4)
            chk(connecter(c4), "4. un client exemple est connecté")
            chk(attendre(lambda: bool(perdues), 30.0),
                "...il envoie son étape 2, dont la réponse se perd")
            time.sleep(0.5)             # le client est dans son attente de la réponse
            t_clic = time.perf_counter()
            ack = srv.submit("deconnecter")
            code = c4.finir(15.0)
            sortie = c4.texte()
            vu = c4.vu("FAILED at step 2")
            delai = None if vu is None else vu - t_clic
            etape4_ok = (ack["accepted"] and code == 1 and delai is not None and 0.0 <= delai < 2.0
                         and "FAILED at step 2: disconnected in the console." in sortie
                         and "no reply" not in sortie)
            chk(etape4_ok,
                f"...« Déconnecter » pendant qu'il attend sa réponse : il échoue à l'étape 2 sur "
                f"la déconnexion, en moins de 2 s (pas au bout de ses 5 s, sur « no reply ») "
                f"({'jamais' if delai is None else f'{delai:.2f} s'}, code {code})")
            if not etape4_ok:
                montrer(c4)
        finally:
            srv.pilotage.__dict__.pop("_publier", None)
    except Exception as e:  # noqa: BLE001 - une exception ici est un échec du test
        traceback.print_exc()
        chk(False, f"le test s'est interrompu sur une exception ({e!r})")
    finally:
        for client in clients:
            client.tuer()
        autre = None
        mi_models.modeles_disponibles = vrai_dispo
        if langue_avant is None:
            os.environ.pop("EEG_LANGUE", None)
        else:
            os.environ["EEG_LANGUE"] = langue_avant
        try:
            if srv is not None:
                srv.stop()
                if fil is not None:
                    fil.join(timeout=15.0)
                srv.retirer_flux()
                srv = None
                gc.collect()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"[smoke-deconnexion] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


# Le faux appareil réseau de `[smoke-appareil-udp]`, lancé dans un AUTRE processus : une vraie
# socket UDP, la bibliothèque standard seulement. Il s'annonce chaque seconde (hello), répond
# « connected » à « connect », envoie « alive » chaque seconde une fois connecté, envoie à
# l'identique chaque ligne JSON reçue sur son entrée standard, et imprime chaque message reçu
# (« RECU <json> »). Sa première ligne donne son port (« PORT <n> »).
_FAUX_APPAREIL_UDP = r'''
import json, os, socket, sys, threading, time
port_moteur, app = int(sys.argv[1]), sys.argv[2]
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", 0))
sock.settimeout(0.05)
port = sock.getsockname()[1]
moteur = ("127.0.0.1", port_moteur)
etat = {"connecte": False}

def envoyer(message):
    sock.sendto(json.dumps(message).encode("utf-8"), moteur)

def lire_les_ordres():
    for ligne in sys.stdin:
        if ligne.strip():
            envoyer(json.loads(ligne))
    os._exit(0)     # le test est fini (ou mort) : l'appareil s'arrête avec lui

print("PORT", port, flush=True)
threading.Thread(target=lire_les_ordres, daemon=True).start()
prochain = 0.0
while True:
    if time.monotonic() >= prochain:
        prochain = time.monotonic() + 1.0
        envoyer({"v": 1, "alive": True} if etat["connecte"] else
                {"v": 1, "hello": "EEG_API_Unicorn", "app": app, "id": "AB:CD", "port": port})
    try:
        donnees, _source = sock.recvfrom(65536)
    except (socket.timeout, ConnectionResetError):
        continue
    message = json.loads(donnees.decode("ascii"))
    if "connect" in message:
        etat["connecte"] = True
        envoyer({"v": 1, "connected": True})
    elif message.get("event") == "disconnected":
        etat["connecte"] = False
    print("RECU", json.dumps(message), flush=True)
'''


def _smoke_appareil_udp():
    """Un appareil RÉSEAU (UDP) contre un VRAI moteur en écoute sur demande, celle de la console.
    Le faux appareil tourne dans un AUTRE processus (`_FAUX_APPAREIL_UDP`), sur un port de test
    choisi par le système : jamais 5010, qu'une console ouverte occupe.

    Vérifie : le moteur ouvre l'écoute UDP au démarrage (pas le moteur seul) ; l'appareil est
    listé avec son adresse et son identifiant ; « Identifier » ; « Connecter » ; ses commandes
    (SSVEP sur cibles physiques, 13 et 15 Hz) ; les « status » puis les « decision » poussés,
    voies par NOM, `-1` compris, « seq » croissant ; « Déconnecter » le lui dit et arrête le SSVEP,
    puis plus rien ne lui est poussé ; son « bye » termine la connexion, raison comprise. Et un
    second moteur sur le MÊME port : l'écoute UDP est indisponible, dite, et la recherche des
    applications LSL marche encore.
    """
    import gc
    import subprocess
    import threading
    import traceback

    from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet

    from core.i18n import choisir_langue
    from core.lsl_io import ssvep_channel_labels

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    def attendre(cond, delai_s=5.0):
        echeance = time.perf_counter() + delai_s
        while not cond() and time.perf_counter() < echeance:
            time.sleep(0.05)
        return cond()

    def cle(texte):
        return getattr(texte, "cle", None)

    class _Appareil:
        """Le faux appareil dans un AUTRE processus. Un fil lit sa sortie : `recus` garde chaque
        message que le moteur lui a envoyé, dans l'ordre d'arrivée."""

        def __init__(self, port_moteur, app):
            self.port, self.recus = None, []
            self.proc = subprocess.Popen(
                [sys.executable, "-u", "-c", _FAUX_APPAREIL_UDP, str(port_moteur), app],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace")
            self.fil = threading.Thread(target=self._lire, daemon=True, name="smoke-appareil-udp")
            self.fil.start()

        def _lire(self):
            for ligne in self.proc.stdout:
                mot, _, reste = ligne.strip().partition(" ")
                if mot == "PORT":
                    self.port = int(reste)
                elif mot == "RECU":
                    self.recus.append(json.loads(reste))
                else:
                    print(f"  [appareil] {ligne.rstrip()}")

        def envoyer(self, message):
            self.proc.stdin.write(json.dumps({"v": 1, **message}) + "\n")
            self.proc.stdin.flush()

        def premier(self, garder, depuis=0, delai_s=5.0):
            """Le premier message reçu (à partir du rang `depuis`) que `garder` accepte, ou None
            au bout de `delai_s` secondes."""
            echeance = time.perf_counter() + delai_s
            while True:
                trouve = next((m for m in list(self.recus)[depuis:] if garder(m)), None)
                if trouve is not None or time.perf_counter() >= echeance:
                    return trouve
                time.sleep(0.05)

        def reponse(self, ref, delai_s=5.0):
            return self.premier(lambda m: m.get("ref") == ref and "event" not in m,
                                delai_s=delai_s)

        def tuer(self):
            if self.proc.poll() is None:
                try:
                    self.proc.stdin.close()     # l'appareil s'arrête de lui-même
                    self.proc.wait(timeout=3.0)
                except (OSError, subprocess.TimeoutExpired):
                    self.proc.kill()
                    self.proc.wait(timeout=5.0)
            self.fil.join(timeout=2.0)

    pid = os.getpid()
    nom = f"{NOM_FLUX_COMMANDES}_smoke_udp_{pid}"
    instance = f"smoke-udp-{socket.gethostname()}-{pid}"
    nom_app = f"smoke-appareil-{pid}"
    tmp = tempfile.mkdtemp(prefix="smoke-udp-")
    langue_avant = os.environ.get("EEG_LANGUE")
    srv = fil = appareil = froid = second = app_lsl = None
    try:
        choisir_langue("fr")
        # 0. Le moteur seul (écoute permanente) n'ouvre aucune socket : sans écran, personne ne
        # peut cliquer « Connecter ».
        froid = EngineServer(synthetic=True, modes=(), instance=f"{instance}-permanent",
                             flux_commandes=f"{nom}_permanent", port_udp=0)
        froid._ouvrir_udp()
        chk(froid.snapshot().get("udp") == {"ouvert": False, "raison": None, "port": None},
            f"0. le moteur seul n'ouvre pas l'écoute UDP ({froid.snapshot().get('udp')})")
        froid.retirer_flux()
        froid.close()
        froid = None

        # Port 0 : le système choisit un port libre, le moteur dit lequel. Deux passages du test,
        # ou une socket oubliée, ne peuvent pas se gêner.
        srv = EngineServer(synthetic=True, modes=("raw",), instance=instance,
                           data_dir=os.path.join(tmp, "data"),
                           seances_dir=os.path.join(tmp, "seances"),
                           flux_commandes=nom, ecoute="sur_demande", port_udp=0)
        fil = threading.Thread(target=srv.run, daemon=True, name="smoke-udp-moteur",
                               kwargs={"duration_s": 300.0, "baseline_s": 1.0, "warmup_s": 0.5})
        fil.start()
        attendre(lambda: srv.acquisition_ouverte and srv.pilotage.vivant, 20.0)
        if not srv.pilotage.vivant:
            raise RuntimeError("le moteur n'a pas démarré son écoute")
        udp = srv.snapshot().get("udp") or {}
        port = udp.get("port")
        chk(udp.get("ouvert") is True and udp.get("raison") is None
            and isinstance(port, int) and port > 0 and port != 5010,
            f"1. la console ouvre l'écoute UDP au démarrage, sur le port de test ({udp})")
        if not udp.get("ouvert"):
            raise RuntimeError("l'écoute UDP n'est pas ouverte : la suite n'a pas de sens")

        appareil = _Appareil(port, nom_app)
        chk(attendre(lambda: appareil.port is not None, 10.0),
            f"...le faux appareil tourne dans un autre processus (port {appareil.port})")
        uid = f"udp:127.0.0.1:{appareil.port}"
        time.sleep(1.5)     # deux hello, au moins, avant la recherche
        chk(not any(a["uid"] == uid for a in srv.snapshot()["applications"]),
            "2. un appareil qui s'annonce n'est pas listé hors d'une recherche")
        srv.submit("chercher_applications", on=True)
        chk(attendre(lambda: any(a["uid"] == uid for a in srv.snapshot()["applications"]), 5.0),
            "...il l'est pendant la recherche")
        vue = next((a for a in srv.snapshot()["applications"] if a["uid"] == uid), {})
        chk(vue.get("nom") == nom_app and vue.get("origine") == "udp"
            and vue.get("machine") == "127.0.0.1" and vue.get("id") == "AB:CD"
            and vue.get("adresse") == f"127.0.0.1:{appareil.port}",
            f"...avec son nom, son origine, sa machine, son identifiant et son adresse ({vue})")

        # 3. « Identifier » : une demande à CET appareil ; refusée pour un uid inconnu.
        ack = srv.submit("identifier", uid=uid)
        chk(ack.get("accepted") is True
            and appareil.premier(lambda m: m.get("identify") is True) is not None,
            f"3. « Identifier » lui demande de se signaler ({ack})")
        refus = srv.submit("identifier", uid="udp:127.0.0.1:1")
        chk(not refus["accepted"]
            and cle(refus["reason"]) == "moteur.connexion.identifier_impossible",
            f"...refusé pour un appareil que le réseau ne voit pas ({refus})")
        refus = srv.submit("identifier", reseau=("u-x", "identifier", None), uid=uid)
        chk(not refus["accepted"], f"...et jamais pour une application ({refus})")

        # 4. « Connecter » : la poignée de main, puis la connexion dit d'où vient l'appareil.
        ack = srv.submit("connecter", uid=uid)
        chk(ack.get("accepted") is True and ack.get("nom") == nom_app
            and appareil.premier(lambda m: "connect" in m) is not None
            and attendre(lambda: (srv.snapshot()["connexion"] or {}).get("branchee")),
            f"4. « Connecter » : l'appareil reçoit « connect », répond, et il est branché ({ack})")
        cx = srv.snapshot()["connexion"] or {}
        chk(cx.get("uid") == uid and cx.get("origine") == "udp"
            and cx.get("machine") == "127.0.0.1" and cx.get("id") == "AB:CD"
            and cx.get("adresse") == f"127.0.0.1:{appareil.port}",
            f"...la connexion dit son origine, sa machine, son identifiant et son adresse "
            f"({ {k: cx.get(k) for k in ('origine', 'machine', 'id', 'adresse')} })")
        refus = srv.submit("identifier", uid=uid)
        chk(not refus["accepted"]
            and cle(refus["reason"]) == "moteur.connexion.console_verrouillee",
            f"...pendant la connexion, la console n'identifie plus personne ({refus})")

        # 5. Ses commandes : le SSVEP sur cibles physiques, 13 et 15 Hz, puis son démarrage.
        appareil.envoyer({"cmd": "set_params", "mode": "ssvep", "ref": "u-1",
                          "params": {"targets_on": "physical", "freqs": [13.0, 15.0]}})
        rep = appareil.reponse("u-1")
        chk(rep is not None and rep.get("accepted") is True,
            f"5. l'appareil règle le SSVEP : cibles physiques, 13 et 15 Hz ({rep})")
        n_avant = len(appareil.recus)
        appareil.envoyer({"cmd": "start_mode", "mode": "ssvep", "ref": "u-2"})
        rep = appareil.reponse("u-2")
        chk(rep is not None and rep.get("accepted") is True
            and attendre(lambda: "ssvep" in srv.active),
            f"...et le démarre ({rep})")
        demandes = (srv.snapshot()["connexion"] or {}).get("demandes")
        chk(demandes == ["ssvep"],
            f"...la connexion dit les modes qu'il a demandés : ceux dont il reçoit les décisions "
            f"(la page de contrôle le dit à la place du voyant LSL) ({demandes})")

        # 6. Les « status » : la phase de SES modes, à chaque changement et chaque seconde.
        statut = appareil.premier(lambda m: "status" in m
                                  and "ssvep" in (m["status"].get("modes") or {}), n_avant)
        chk(statut is not None and statut["status"].get("phase") in ("warmup", "baseline",
                                                                     "decoding"),
            f"6. un « status » lui dit la phase de son SSVEP ({statut})")
        # 7. Les « decision » : chaque sortie de `decoded_ssvep`, voies par NOM, `-1` compris.
        decision = appareil.premier(lambda m: "decision" in m, n_avant, delai_s=40.0)
        voies = ["mode"] + ssvep_channel_labels([13.0, 15.0])
        chk(decision is not None and sorted(decision["decision"]) == sorted(voies)
            and decision["decision"]["mode"] == "ssvep",
            f"7. les décisions du SSVEP lui arrivent, voies par nom ({decision})")
        chk(appareil.premier(lambda m: "decision" in m
                             and m["decision"].get("target_index") == -1, n_avant) is not None,
            "...« -1 » (aucune cible) compris")
        statut_decode = appareil.premier(lambda m: "status" in m
                                         and m["status"].get("phase") == "decoding", n_avant)
        chk(statut_decode is not None
            and statut_decode["status"].get("modes") == {"ssvep": "decoding"},
            f"...et le « status » dit qu'il décode ({statut_decode})")
        # La phase ne change plus : seul le rappel de chaque seconde fait repartir le « status ».
        n_statuts = len([m for m in list(appareil.recus) if "status" in m])
        time.sleep(2.5)
        n_statuts = len([m for m in list(appareil.recus) if "status" in m]) - n_statuts
        chk(2 <= n_statuts <= 3,
            f"...et il revient chaque seconde, même sans changement ({n_statuts} en 2,5 s)")
        seqs = [m["seq"] for m in list(appareil.recus) if "seq" in m]
        chk(len(seqs) > 3 and all(b > a for a, b in zip(seqs, seqs[1:]))
            and all(m.get("v") == 1 for m in list(appareil.recus)),
            f"...chaque message porte « v »: 1 et un « seq » croissant ({len(seqs)} messages)")

        # 8. « Déconnecter » : dit à l'appareil, le SSVEP qu'il a démarré s'arrête, puis plus
        # rien ne lui est poussé.
        ack = srv.submit("deconnecter")
        adieu = appareil.premier(lambda m: m.get("event") == "disconnected")
        chk(ack.get("accepted") is True and adieu is not None
            and adieu.get("cause") == "console" and adieu.get("app") == nom_app
            and adieu.get("stopped") == ["ssvep"]
            and attendre(lambda: "ssvep" not in srv.active),
            f"8. « Déconnecter » le lui dit et arrête son SSVEP ({adieu})")
        fin = srv.snapshot()["fin_connexion"] or {}
        chk(fin.get("raison") == "deconnectee" and fin.get("origine") == "udp",
            f"...la fin dit pourquoi et d'où venait l'appareil ({fin})")
        n_apres = len(appareil.recus)
        time.sleep(1.5)
        chk(len(appareil.recus) == n_apres,
            f"...et plus rien ne lui est poussé ({appareil.recus[n_apres:]})")

        # 9. Reconnecté, il dit « bye » : fin immédiate, raison comprise, son SSVEP arrêté.
        srv.submit("chercher_applications", on=True)
        attendre(lambda: any(a["uid"] == uid for a in srv.snapshot()["applications"]), 5.0)
        ack = srv.submit("connecter", uid=uid)
        branche = attendre(lambda: (srv.snapshot()["connexion"] or {}).get("branchee"))
        appareil.envoyer({"cmd": "start_mode", "mode": "ssvep", "ref": "u-3"})
        rep = appareil.reponse("u-3")
        demarre = attendre(lambda: "ssvep" in srv.active)
        appareil.envoyer({"bye": True})
        chk(ack.get("accepted") is True and branche and rep is not None and rep.get("accepted")
            and demarre and attendre(lambda: srv.snapshot()["connexion"] is None, 3.0),
            f"9. reconnecté, son « bye » termine la connexion tout de suite ({ack}, {rep})")
        fin = srv.snapshot()["fin_connexion"] or {}
        chk(fin.get("raison") == "bye" and fin.get("arretes") == ("ssvep",)
            and attendre(lambda: "ssvep" not in srv.active),
            f"...la fin porte la raison de l'appareil, et son SSVEP s'arrête ({fin})")

        # 10. Un second moteur sur le MÊME port (une seconde console sur le poste). Deux
        # sessions BrainFlow du board de test ne tiennent pas dans un processus : celui-ci ouvre
        # son écoute comme le fait `run()`, sans casque.
        second = EngineServer(synthetic=True, modes=(), instance=f"{instance}-second",
                              flux_commandes=f"{nom}_second", ecoute="sur_demande",
                              port_udp=port)
        second._ouvrir_udp()
        udp2 = second.snapshot().get("udp") or {}
        chk(udp2.get("ouvert") is False
            and cle(udp2.get("raison")) == "moteur.reseau.udp_port_pris",
            f"10. un second moteur sur le même port : l'écoute UDP est indisponible, et dite "
            f"({udp2})")
        chk(second.pilotage.demarrer(), "...son écoute LSL démarre quand même")
        app_lsl = StreamOutlet(StreamInfo(f"{nom}_second", "Markers", 1, IRREGULAR_RATE,
                                          "string", f"{nom_app}-lsl"))
        second.submit("chercher_applications", on=True)
        chk(attendre(lambda: any(a["nom"] == f"{nom_app}-lsl" and a["origine"] == "lsl"
                                 for a in second.snapshot()["applications"]), 8.0),
            "...et la recherche y trouve encore les applications LSL")
    except Exception as e:  # noqa: BLE001 - une exception ici est un échec du test
        traceback.print_exc()
        chk(False, f"le test s'est interrompu sur une exception ({e!r})")
    finally:
        if langue_avant is None:
            os.environ.pop("EEG_LANGUE", None)
        else:
            os.environ["EEG_LANGUE"] = langue_avant
        try:
            app_lsl = None
            if appareil is not None:
                appareil.tuer()
            for moteur in (froid, second):
                if moteur is not None:
                    moteur.retirer_flux()
                    moteur.close()
            froid = second = None
            if srv is not None:
                srv.stop()
                if fil is not None:
                    fil.join(timeout=15.0)
                chk(not (srv.snapshot().get("udp") or {}).get("ouvert"),
                    "11. le moteur arrêté rend son port UDP")
                srv.retirer_flux()
                srv = None
                gc.collect()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"[smoke-appareil-udp] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_exemple_udp():
    """L'appareil réseau EXEMPLE (`examples/udp_device.py`), lancé dans un AUTRE processus comme
    un étudiant le lancerait, contre un vrai moteur en écoute sur demande (celle de la console).

    `[smoke-appareil-udp]` teste le MOTEUR en détail, avec son propre faux appareil. Celui-ci
    teste l'EXEMPLE : c'est lui qu'un programmeur d'ESP32 recopiera. Vérifie :
    1. il s'annonce : la recherche le liste avec son nom et son identifiant, et « Identifier »
       lui fait dire de clignoter ;
    2. connecté au premier hello vu, il répond « busy » à une SECONDE console qui veut le
       connecter, règle le SSVEP sur cibles physiques (13 et 15 Hz, avec des noms), le démarre,
       affiche ses décisions (« decision: »), arrête le mode, dit « bye » et sort avec le code 0 ;
    3. un second passage, déconnecté pendant la chauffe (il attend ses premières décisions et
       n'en reçoit aucune) : il le dit en moins de 5 s et sort avec le code 1.
    Le port du moteur et celui de l'appareil sont choisis par le système (jamais 5010, qu'une
    console ouverte occupe), sur 127.0.0.1.
    """
    import gc
    import subprocess
    import threading
    import traceback

    from core.i18n import choisir_langue

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    def attendre(cond, delai_s=5.0):
        echeance = time.perf_counter() + delai_s
        while not cond() and time.perf_counter() < echeance:
            time.sleep(0.05)
        return cond()

    pid = os.getpid()
    racine = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    exemple = os.path.join(racine, "examples", "udp_device.py")

    class _Appareil:
        """L'exemple dans un AUTRE processus. Un fil lit sa sortie ligne par ligne, avec
        l'instant de chacune : on mesure quand il a dit ce qu'il a vu."""

        def __init__(self, port_moteur, nom, ident, *args):
            self.lignes = []            # (time.perf_counter(), ligne)
            # `PYTHONUNBUFFERED` : chaque ligne arrive quand l'exemple l'écrit.
            self.proc = subprocess.Popen(
                [sys.executable, exemple, "--name", nom, "--id", ident, "--port", "0",
                 "--engine-host", "127.0.0.1", "--engine-port", str(port_moteur), *args],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                       "PYTHONUNBUFFERED": "1"})
            self.fil = threading.Thread(target=self._lire, daemon=True,
                                        name="smoke-exemple-udp")
            self.fil.start()

        def _lire(self):
            for ligne in self.proc.stdout:
                self.lignes.append((time.perf_counter(), ligne.rstrip("\n")))

        def vu(self, texte):
            """L'instant de la première ligne qui contient `texte`, ou None."""
            return next((t for t, ligne in list(self.lignes) if texte in ligne), None)

        def texte(self):
            return "\n".join(ligne for _t, ligne in list(self.lignes))

        def finir(self, delai_s):
            """Le code de sortie, ou None s'il tourne encore après `delai_s` (il est alors
            tué)."""
            try:
                code = self.proc.wait(timeout=delai_s)
            except subprocess.TimeoutExpired:
                code = None
            self.tuer()
            return code

        def tuer(self):
            if self.proc.poll() is None:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    pass
            self.fil.join(timeout=2.0)

    def montrer(appareil):
        print("  --- sortie de l'exemple ---")
        for ligne in appareil.texte().splitlines():
            print(f"  | {ligne}")
        print("  --- fin de la sortie ---")

    def trouver(srv, nom):
        """L'annonce de l'appareil `nom` dans la liste de la recherche, ou None."""
        return next((a for a in srv.snapshot()["applications"]
                     if a.get("nom") == nom and a.get("origine") == "udp"), None)

    instance = f"smoke-exemple-udp-{socket.gethostname()}-{pid}"
    nom_flux = f"{NOM_FLUX_COMMANDES}_smoke_exemple_udp_{pid}"
    tmp = tempfile.mkdtemp(prefix="smoke-exemple-udp-")
    langue_avant = os.environ.get("EEG_LANGUE")
    srv = fil = premier = second = intrus = None
    try:
        choisir_langue("fr")
        # Une chauffe de 8 s : assez longue pour déconnecter le second passage PENDANT elle,
        # même sur une machine lente, assez courte pour que le premier reçoive vite ses
        # décisions.
        srv = EngineServer(synthetic=True, modes=("raw",), instance=instance,
                           data_dir=os.path.join(tmp, "data"),
                           seances_dir=os.path.join(tmp, "seances"),
                           flux_commandes=nom_flux, ecoute="sur_demande", port_udp=0)
        fil = threading.Thread(target=srv.run, daemon=True, name="smoke-exemple-udp-moteur",
                               kwargs={"duration_s": 300.0, "baseline_s": 1.0, "warmup_s": 8.0})
        fil.start()
        attendre(lambda: srv.acquisition_ouverte and srv.pilotage.vivant, 20.0)
        port = (srv.snapshot().get("udp") or {}).get("port")
        if not (srv.pilotage.vivant and isinstance(port, int) and port > 0):
            raise RuntimeError(f"le moteur n'écoute pas l'UDP ({srv.snapshot().get('udp')})")

        # 1. Il s'annonce : la recherche le liste, avec son nom et son identifiant.
        srv.submit("chercher_applications", on=True)
        nom1 = f"smoke-ex-{pid}"
        premier = _Appareil(port, nom1, "EX:01", "--timeout", "30")
        vue = None
        if attendre(lambda: trouver(srv, nom1) is not None, 10.0):
            vue = trouver(srv, nom1)
        chk(vue is not None and vue.get("id") == "EX:01"
            and str(vue.get("uid", "")).startswith("udp:127.0.0.1:"),
            f"1. l'exemple s'annonce : la recherche le liste avec son nom et son identifiant "
            f"({vue})")
        if vue is None:
            raise RuntimeError("l'exemple n'est pas listé : la suite n'a pas de sens")
        uid = vue["uid"]
        ack = srv.submit("identifier", uid=uid)
        chk(ack.get("accepted") is True and attendre(lambda: premier.vu("IDENTIFY") is not None),
            "...« Identifier » lui fait dire de clignoter (« IDENTIFY »)")

        # 2. Connecté au premier hello vu, il mène toute sa séance tout seul.
        ack = srv.submit("connecter", uid=uid)
        chk(ack.get("accepted") is True
            and attendre(lambda: (srv.snapshot()["connexion"] or {}).get("branchee")),
            f"2. « Connecter » : l'exemple répond, il est branché ({ack})")
        # Une SECONDE console veut le connecter : il répond « busy », avec l'hôte de la première.
        intrus = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        intrus.bind(("127.0.0.1", 0))
        intrus.settimeout(3.0)
        intrus.sendto(json.dumps({"v": 1, "connect": "une-autre-console", "host": "AUTRE-PC"})
                      .encode("utf-8"), ("127.0.0.1", int(uid.rsplit(":", 1)[1])))
        try:
            occupe = json.loads(intrus.recvfrom(65536)[0].decode("utf-8"))
        except (OSError, ValueError):
            occupe = None
        chk(occupe == {"v": 1, "connected": False, "busy": srv.pilotage.hote},
            f"...déjà connecté, il répond « busy » à une seconde console ({occupe})")
        code = premier.finir(60.0)
        sortie = premier.texte()
        chk(code == 0, f"...il sort avec le code 0 (code {code})")
        chk('"targets_on": "physical"' in sortie and '"freqs": [13.0, 15.0]' in sortie
            and '"cmd": "start_mode"' in sortie and '"cmd": "stop_mode"' in sortie,
            "...il a réglé le SSVEP sur cibles physiques (13 et 15 Hz), l'a démarré puis arrêté")
        reglage = srv.reglages.get("ssvep") or {}
        chk(reglage.get("targets_on") == "physical"
            and [float(f) for f in reglage.get("freqs") or ()] == [13.0, 15.0]
            and len(reglage.get("target_names") or ()) == 2,
            f"...et le moteur a retenu ses réglages ({reglage})")
        chk("decision: target=" in sortie,
            "...il affiche ses décisions (« decision: target=… freq=… »)")
        termine = attendre(lambda: srv.snapshot()["connexion"] is None, 3.0)
        fin = srv.snapshot()["fin_connexion"] or {}
        chk(termine and fin.get("raison") == "bye" and "ssvep" not in srv.active,
            f"...son « bye » termine la connexion, son SSVEP arrêté ({fin})")
        if not ok:
            montrer(premier)

        # 3. Un second passage, déconnecté PENDANT la chauffe : il attend ses premières
        # décisions, n'en reçoit aucune, et doit quand même entendre « disconnected ».
        nom2 = f"smoke-ex2-{pid}"
        second = _Appareil(port, nom2, "EX:02", "--timeout", "30")
        srv.submit("chercher_applications", on=True)
        vue2 = None
        if attendre(lambda: trouver(srv, nom2) is not None, 10.0):
            vue2 = trouver(srv, nom2)
        ack = srv.submit("connecter", uid=vue2["uid"]) if vue2 else {}
        demarre = attendre(lambda: "ssvep" in srv.active, 10.0)
        chk(ack.get("accepted") is True and demarre and second.vu("decision:") is None,
            f"3. un second passage : connecté, son SSVEP démarre, aucune décision encore "
            f"(chauffe) ({ack})")
        t0 = time.perf_counter()
        srv.submit("deconnecter")
        code = second.finir(8.0)
        t_dit = second.vu("FAILED: disconnected in the console.")
        chk(code == 1 and t_dit is not None and t_dit - t0 < 5.0,
            f"...« Déconnecter » pendant la chauffe : il le dit en moins de 5 s et sort avec le "
            f"code 1 (code {code}, "
            f"{'jamais dit' if t_dit is None else f'{t_dit - t0:.1f} s'})")
        chk('"event": "disconnected"' in second.texte() and second.vu('"cmd": "stop_mode"') is None,
            "...il affiche le message « disconnected » et n'envoie pas de stop_mode (le moteur a "
            "déjà arrêté ce qu'il avait démarré)")
        chk(attendre(lambda: "ssvep" not in srv.active), "...et son SSVEP est arrêté")
        if not ok:
            montrer(second)
    except Exception as e:  # noqa: BLE001 - une exception ici est un échec du test
        traceback.print_exc()
        chk(False, f"le test s'est interrompu sur une exception ({e!r})")
        for appareil in (premier, second):
            if appareil is not None:
                montrer(appareil)
    finally:
        if langue_avant is None:
            os.environ.pop("EEG_LANGUE", None)
        else:
            os.environ["EEG_LANGUE"] = langue_avant
        try:
            if intrus is not None:
                intrus.close()
            for appareil in (premier, second):
                if appareil is not None:
                    appareil.tuer()
            if srv is not None:
                srv.stop()
                if fil is not None:
                    fil.join(timeout=15.0)
                srv.retirer_flux()
                srv = None
                gc.collect()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"[smoke-exemple-udp] VERDICT : {'OK' if ok else 'PROBLÈME'}")
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
                        "mêmes fréquences que src/stimulus/ssvep.py lancé avec ce "
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
    p.add_argument("--secteur", type=int, choices=[int(s) for s in SECTEURS_HZ],
                   default=int(SECTEUR_HZ),
                   help="secteur électrique du poste, en Hz : 50 (Europe) ou 60 (Amériques). Le "
                        "coupe-bande de l'acquisition, du contrôle alpha, du Neuro et de chaque "
                        "entraînement, qui l'enregistre dans son modèle")
    p.add_argument("--version", action="store_true", help="affiche la version et quitte")
    p.add_argument("--smoke", action="store_true", help="test headless de bout en bout, puis quitte")
    p.add_argument("--verbose", action="store_true", help="logs BrainFlow détaillés")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    if args.version:
        print(VERSION)
        sys.exit(0)
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
    # rédigé pour être lu. Un traceback autour enterrerait ce message sous quinze lignes de pile —
    # or c'est le PREMIER contact de tout étudiant qui lance `--mode mi` avant d'avoir calibré :
    # sans modèle entraîné, ce refus est le comportement normal du mode, pas un plantage. Code de
    # sortie 2 : « la commande est mal formée », comme argparse.
    try:
        engine = EngineServer(serial=args.serial, synthetic=args.synthetic, verbose=args.verbose,
                              modes=modes, params=params, instance=args.instance,
                              secteur_hz=float(args.secteur))
    except ValueError as refus:
        print(f"[server] {refus}")
        sys.exit(2)
    # Ctrl+C doit fermer PROPREMENT la session BrainFlow : une session laissée ouverte
    # empêche la suivante de s'ouvrir (BOARD_NOT_READY au relancement).
    signal.signal(signal.SIGINT, lambda *_: engine.stop())
    print("[server] Ctrl+C pour arrêter.")
    engine.run(duration_s=args.duration, baseline_s=args.baseline, warmup_s=args.warmup)
