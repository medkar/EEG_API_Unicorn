"""La console d'expérimentation : régler, observer, publier — mode par mode.

Lancer :
    python src/console/app.py --synthetic          # sans casque (board de test BrainFlow)
    python src/console/app.py                      # vrai Unicorn, brut seul
    python src/console/app.py --mode ssvep         # + décodage SSVEP
    python src/console/app.py --mode ssvep,neuro   # les deux en même temps
    python src/console/app.py --smoke              # test headless (CI), puis quitte

⚠️ Ne jamais la lancer en même temps que `src/core/server.py` ni que `src/research/app.py` : le
casque n'accepte qu'une connexion, et les noms de flux sont un contrat public — deux moteurs
publient sous le même nom.
"""

import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_args(argv):
    p = argparse.ArgumentParser(description="EEG_API_Unicorn — console d'expérimentation.")
    p.add_argument("--synthetic", action="store_true", help="board de test BrainFlow (sans casque)")
    p.add_argument("--serial", default=None, help="numéro de série Unicorn")
    p.add_argument("--mode", default=None, help="modes à démarrer, séparés par des virgules")
    p.add_argument("--no-raw", action="store_true", help="ne pas diffuser le signal brut")
    p.add_argument("--id", dest="instance", default=None, help="identité de cette instance")
    p.add_argument("--baseline", type=float, default=None,
                   help="raccourcir le repos — pour REGARDER l'interface sans attendre. Jamais "
                        "pour une vraie séance : le plancher serait mesuré sur trop peu de "
                        "fenêtres et fausserait toute la suite")
    p.add_argument("--warmup", type=float, default=None,
                   help="raccourcir la stabilisation (même réserve que --baseline)")
    p.add_argument("--smoke", action="store_true", help="test headless, puis quitte")
    p.add_argument("--verbose", action="store_true", help="logs BrainFlow détaillés")
    return p.parse_args(argv)


# QT_QPA_PLATFORM doit être posé AVANT le premier import de PySide6 : Qt choisit son backend
# d'affichage à l'import, pas à la création de la QApplication. Posé après, il n'a aucun effet
# et le test headless échoue sur une machine sans écran (la CI, plus tard).
_ARGS = _parse_args(sys.argv[1:])
if _ARGS.smoke:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QProcess, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import (QApplication, QFormLayout, QMainWindow,  # noqa: E402
                               QStackedWidget, QVBoxLayout, QWidget)

from console.banner import Banner  # noqa: E402
from console.beeps import Beeps  # noqa: E402
from console.calib_page import CalibPage  # noqa: E402
from console.contact_page import ContactPage  # noqa: E402
from console.fenetres import LanceurFenetre  # noqa: E402
from console.grid import ModeGrid  # noqa: E402
from console.mode_page import ModePage  # noqa: E402
from console import live_views  # noqa: E402
from core import neuro_monitor  # noqa: E402  (les descriptions des indices, cf. _smoke)
from core.config import TOLERANCE_DIVISEUR, use_utf8_console  # noqa: E402
from core.modes import registry  # noqa: E402
from core.modes.calibration import PHASES_TERMINALES  # noqa: E402
from core.server import EngineServer  # noqa: E402

REFRESH_MS = 100    # ~10 Hz : le moteur décide à 5 Hz, sonder plus vite ne montrerait rien de plus

# Combien de temps on attend qu'un mode rende la main avant de lancer SA calibration. `stop_mode`
# est mis en FILE : la boucle l'applique à sa cadence (~50 ms), donc l'attente normale est d'un ou
# deux tours. Ce délai n'existe que pour ne pas attendre en SILENCE si la boucle est bloquée ou
# arrêtée — un écran qui ne dit rien pendant que rien ne se passe est la panne que ce chantier
# répare, et elle serait ici indiscernable d'une chauffe qui démarre.
DELAI_ARRET_S = 5.0


class Console(QMainWindow):
    """La fenêtre. Elle ne fait que deux choses : lire un état, envoyer des commandes."""

    def __init__(self, engine, fabrique_fenetre=None, horloge=None):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("EEG_API_Unicorn — console d'expérimentation")
        self.resize(1100, 720)

        # Le lanceur de fenêtres de stimulus. `fabrique_fenetre` est injectable pour que le smoke
        # n'ait JAMAIS à démarrer un vrai pygame ; `horloge` l'est pour que le délai d'attente
        # ci-dessous soit testable sans attendre cinq secondes.
        self.lanceur = LanceurFenetre(fabrique_fenetre)
        self._horloge = horloge or time.monotonic
        self._dernier_etat = {}
        # Ce qu'on s'apprête à lancer, le temps du contrôle de liaison. Et, une fois le contrôle
        # passé, le mode qu'on attend de voir s'arrêter avant de démarrer sa calibration.
        self._demande = None
        self._attente = None
        # Une calibration soumise dont la fenêtre a refusé de s'ouvrir. Elle doit être annulée,
        # mais pas avant que le moteur ne l'ait réellement démarrée — cf. `_suivre_attente`.
        self._a_annuler = False

        self.banner = Banner()
        self.stack = QStackedWidget()
        # ⚠️ UN SEUL appel, réutilisé par les trois boucles ci-dessous. Ce n'est pas de
        # l'élégance : depuis que le « Flux de marqueurs » du P300 et de l'ErrP se remplit en
        # DÉCOUVRANT les émetteurs du réseau (`markers.flux_de_marqueurs_visibles`), sérialiser le
        # catalogue coûte une résolution LSL bornée par mode marqueur. Mesuré sur ce poste :
        # 1,03 s l'appel, donc 1,9 s de fenêtre gelée au démarrage quand on en fait trois. Le
        # catalogue est une DÉCLARATION — il ne change pas entre deux lignes de ce constructeur.
        catalogue = registry.catalog()
        # Le catalogue indexé, pour retrouver le contrat d'un mode sans le resérialiser (ce qui
        # relirait le disque : `choices_fn` charge les modèles entraînés).
        self.catalogue = {spec["id"]: spec for spec in catalogue}
        self.grid = ModeGrid(catalogue)
        self.grid.ouvrir.connect(self.show_mode)
        self.grid.publier.connect(self._publier)
        self.grid.demarrer.connect(self._demarrer)
        self.stack.addWidget(self.grid)

        self.pages = {}
        for spec in catalogue:
            if spec["status"] != "moteur":
                continue          # pas de page pour un mode que le moteur ne sait pas faire
            page = ModePage(spec, self)
            page.retour.connect(self.show_grid)
            self.pages[spec["id"]] = page
            self.stack.addWidget(page)

        # Une page de calibration par mode que LE MOTEUR sait jouer. Le critère n'est plus `kind`
        # (qui dit seulement qui mène le protocole — le moteur ou une fenêtre de stimulus) mais
        # `jouable`, que le contrat calcule depuis son `runtime_cls`. Un mode dont la calibration
        # est déclarée mais pas encore livrée n'a donc pas de page, et son bouton ne ment pas.
        self.beeps = Beeps()
        self.calib_pages = {}
        for spec in catalogue:
            calib = spec.get("calibration") or {}
            if not calib.get("jouable") or spec["status"] != "moteur":
                continue
            page = CalibPage(spec, self)
            page.retour.connect(self.show_grid)
            self.calib_pages[spec["id"]] = page
            self.stack.addWidget(page)

        # UNE page de contrôle de liaison pour tous les modes : les huit voies sont les mêmes,
        # seul le surlignage des voies clés change d'un mode à l'autre (`viser`).
        self.contact = ContactPage(self)
        self.contact.lancer.connect(self._contact_lance)
        self.contact.annuler.connect(self._contact_annule)
        self.stack.addWidget(self.contact)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.banner)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MS)

    def refresh(self):
        """Sonde le moteur et redistribue l'état. Le SEUL endroit qui appelle `snapshot()`."""
        self.apply_state(self.engine.snapshot())

    def apply_state(self, state):
        self._dernier_etat = state or {}
        self.banner.update_from(state)
        # L'état de la fenêtre de stimulus est poussé À CHAQUE rafraîchissement, et dans le
        # bandeau : une fenêtre qui meurt pendant qu'on regarde une autre page doit se voir quand
        # même — et le moteur, lui, ne sait pas qu'elle existe.
        texte, alerte = self.lanceur.etat_texte()
        self.banner.set_fenetre(texte, alerte)
        self.grid.update_from(state)
        page = self.stack.currentWidget()
        if page is not self.grid:
            page.update_from(state)
        self._suivre_attente(state)

    def _publier(self, mode_id, on):
        """Publier ou non le flux de ce mode. Passe par la file de commandes, comme tout."""
        self.commande("set_published", id=mode_id, on=on)

    def _demarrer(self, mode_id, on):
        """Démarrer ou arrêter un mode. Le moteur valide et refuse ; on affiche ce qu'il dit.

        Sans ce geste, produire un modèle par calibration puis l'utiliser obligerait à fermer et
        rouvrir la console (`--mode mi` au lancement) — or **les voies C3/Cz saturent à la
        réouverture** (redémarrage de l'amplificateur), et ce sont précisément celles que lit le
        Motor Imagery. Le parcours entier du chantier passait donc par le geste qui abîme le
        signal qu'il vient de calibrer.

        On n'envoie AUCUN réglage : le moteur applique les défauts du contrat, qui pour le MI
        désignent le modèle le plus récemment entraîné. Les changer se fait ensuite dans la page
        du mode, avec les refus en clair — c'est déjà là.
        """
        self.commande("start_mode", id=mode_id) if on else self.commande("stop_mode", id=mode_id)

    def commande(self, name, **params):
        """Soumet une commande et retient le refus, s'il y en a un, pour l'afficher."""
        if self.engine is None:
            return {"accepted": False, "reason": "aucun moteur (mode test)"}
        ack = self.engine.submit(name, **params)
        if not ack.get("accepted"):
            print(f"[console] refusé : {ack.get('reason')}")
        return ack

    # --- lancer quelque chose : le contact d'abord, puis l'ORDRE ---------------------------
    #
    # 🔴 L'ordre est le piège de tout ce sous-système, et il ne lève aucune exception quand il est
    # faux. La fenêtre de stimulus attend ~15 s À PARTIR DE SON PROPRE LANCEMENT ; le moteur
    # compte sa chauffe À PARTIR DE `start_calibration`. Il n'existe AUCUNE poignée de main entre
    # les deux processus, et c'est délibéré (les tâches 4 et 5 ont refusé d'en inventer une).
    #
    # Donc : `start_calibration` D'ABORD, la fenêtre ENSUITE. L'initialisation de pygame (~3 s)
    # plus l'attente propre de la fenêtre couvrent alors la chauffe du moteur. Dans l'autre sens,
    # les premières manches tombent dans la chauffe : elles sont jetées, comptées et dites — mais
    # la séance est plus courte que ce que l'écran annonce, et c'est indiscernable d'un protocole
    # qui s'est bien passé.

    def demander_calibration(self, mode_id, params):
        """« Commencer » sur une page de calibration : on passe d'abord par le contrôle de liaison.

        Rien n'est soumis ici. Le lancement réel est dans `_contact_lance`, et il n'a lieu que si
        le contrôle de liaison ne refuse pas.
        """
        self._demande = {"quoi": "calibration", "mode_id": mode_id,
                         "params": dict(params or {}),
                         "retour": self.calib_pages.get(mode_id)}
        self._montrer_contact(mode_id, "Commencer la calibration")

    def demander_stimulus(self, mode_id):
        """« Lancer le stimulus » sur une page de mode : même chemin, sans calibration.

        La fenêtre est alors lancée en mode DÉCODAGE : c'est elle qui affiche les cibles et publie
        les marqueurs que le mode découpe. Elle n'ouvre pas le casque, donc elle vit à côté du
        moteur — c'est exactement pour ça qu'elle est un second processus.
        """
        self._demande = {"quoi": "stimulus", "mode_id": mode_id, "params": {},
                         "retour": self.pages.get(mode_id)}
        self._montrer_contact(mode_id, "Lancer le stimulus")

    def _montrer_contact(self, mode_id, quoi):
        spec = self.catalogue.get(mode_id)
        if spec is None:
            self._demande = None
            return
        self.contact.viser(spec, quoi)
        # L'état DÉJÀ reçu, tout de suite : sans lui, la page resterait sur « en attente de la
        # première mesure » jusqu'au prochain tour de `QTimer`, et un écran qui refuse pour une
        # raison périmée se lit comme un écran cassé.
        self.contact.update_from(self._dernier_etat)
        self.stack.setCurrentWidget(self.contact)

    def _contact_annule(self):
        demande, self._demande = self._demande, None
        retour = (demande or {}).get("retour")
        self.stack.setCurrentWidget(retour if retour is not None else self.grid)

    def _contact_lance(self):
        """Le contrôle de liaison est passé. On revient sur la page d'origine, puis on lance."""
        demande, self._demande = self._demande, None
        if demande is None:
            return
        retour = demande.get("retour")
        # Revenir AVANT de lancer : c'est sur cette page-là que s'affichera un éventuel refus du
        # moteur, et la page de contact ne doit pas rester devant un refus qu'elle ne porte pas.
        self.stack.setCurrentWidget(retour if retour is not None else self.grid)
        if demande["quoi"] == "stimulus":
            self._lancer_fenetre(demande["mode_id"], calibrer=False)
            return
        # ⚠️ Le mode doit être ARRÊTÉ avant que sa calibration ne démarre : les deux liraient la
        # même file de marqueurs, et `submit` refuse (tâche 5). On l'arrête donc nous-mêmes plutôt
        # que d'infliger deux gestes à l'étudiant — mais `stop_mode` est mis en FILE, et
        # `start_calibration` soumise dans la foulée verrait encore le mode actif et serait
        # refusée. On attend donc de le voir DISPARAÎTRE de l'état.
        if demande["mode_id"] in (self._dernier_etat.get("modes_state") or {}):
            self.commande("stop_mode", id=demande["mode_id"])
            self._attente = dict(demande, echeance=self._horloge() + DELAI_ARRET_S)
            self._avis(demande["mode_id"],
                       f"arrêt de « {demande['mode_id']} » demandé — sa calibration démarrera dès "
                       f"qu'il aura rendu la main (un mode et sa calibration ne peuvent pas lire "
                       f"la même file de marqueurs).", alerte=False)
            return
        self._demarrer_calibration(demande)

    def _suivre_attente(self, state):
        """Ce qu'on attend du moteur, tour par tour. Appelée à chaque rafraîchissement.

        Deux attentes, et toutes les deux existent pour la MÊME raison : `submit` ne fait que
        mettre en file, donc une commande soumise juste après une autre juge un moteur qui n'a pas
        encore appliqué la première.
        """
        # 1. Une calibration soumise dont la fenêtre a refusé de s'ouvrir : on l'annule dès
        #    qu'elle existe pour de bon. Sans ça, l'écran annonce une annulation qui n'a pas eu
        #    lieu, avec le décompte de la chauffe qui démarre juste en dessous.
        if self._a_annuler:
            calib = (state or {}).get("calibration")
            if calib is not None and calib.get("phase") not in PHASES_TERMINALES:
                self._a_annuler = False
                self.commande("cancel_calibration")
                self.lanceur.arreter()

        if self._attente is None:
            return
        mode_id = self._attente["mode_id"]
        if mode_id not in ((state or {}).get("modes_state") or {}):
            attente, self._attente = self._attente, None
            self._demarrer_calibration(attente)
        elif self._horloge() > self._attente["echeance"]:
            attente, self._attente = self._attente, None
            self._avis(mode_id,
                       f"« {mode_id} » ne s'est pas arrêté en {DELAI_ARRET_S:.0f} s : la "
                       f"calibration n'a PAS été lancée. Arrête-le depuis la grille, puis "
                       f"reclique « Commencer ».")

    def _demarrer_calibration(self, demande):
        """`start_calibration` D'ABORD, la fenêtre de stimulus ENSUITE. Jamais l'inverse."""
        mode_id = demande["mode_id"]
        ack = self.commande("start_calibration", id=mode_id, params=demande["params"])
        if not ack.get("accepted"):
            self._avis(mode_id, ack.get("reason", ""))
            return
        spec = self.catalogue.get(mode_id) or {}
        stimulus_id = (spec.get("calibration") or {}).get("stimulus_id")
        if not stimulus_id:
            return          # le moteur mène tout seul le protocole (Motor Imagery)
        ouvert = self._lancer_fenetre(mode_id, calibrer=True)
        if not ouvert.get("accepted"):
            # La calibration EST PARTIE, mais personne ne lui enverra de marqueurs : elle
            # attendrait jusqu'à l'abandon, en comptant une chauffe qui ne mène nulle part.
            #
            # ⚠️ On ne peut PAS l'annuler tout de suite : `start_calibration` vient d'être mise en
            # FILE, la boucle ne l'a pas encore appliquée, donc `self.calibration` est encore
            # `None` côté moteur et `submit("cancel_calibration")` répond « aucune calibration en
            # cours ». Annuler ici et écrire « la calibration a été annulée » serait une phrase
            # FAUSSE à l'écran, avec un décompte qui démarre juste en dessous. On note donc
            # l'annulation, et `_suivre_attente` la soumet dès que la séance apparaît.
            self._a_annuler = True
            self._avis(mode_id,
                       f"{ouvert.get('reason', '')}\nLa calibration est annulée : sans sa "
                       f"fenêtre, le moteur attendrait des marqueurs qui ne viendront jamais.")

    def _lancer_fenetre(self, mode_id, calibrer):
        """Demande la fenêtre au lanceur. La ligne de commande vient de `stimulus/registry.py`."""
        spec = self.catalogue.get(mode_id) or {}
        stimulus_id = (spec.get("calibration") or {}).get("stimulus_id")
        if not stimulus_id:
            return {"accepted": False,
                    "reason": f"« {spec.get('label', mode_id)} » ne déclare aucune fenêtre de "
                              f"stimulus : il n'y a rien à lancer."}
        return self.lanceur.lancer(stimulus_id, calibrer=calibrer,
                                   label=spec.get("label", mode_id))

    def arreter_calibration(self):
        """« Abandonner » : la commande au moteur ET la fenêtre. Les deux, toujours.

        Abandonner sans fermer la fenêtre laisserait un émetteur publier des marqueurs pour une
        séance qui n'existe plus — et la calibration SUIVANTE hériterait de ses premières manches.
        """
        self._attente = None
        self._a_annuler = False       # le geste explicite prime sur l'annulation en attente
        self.commande("cancel_calibration")
        self.lanceur.arreter()

    def _avis(self, mode_id, texte, alerte=True):
        """Affiche un message sur la page de calibration du mode, s'il en a une.

        C'est ce qui sépare « le refus est correct » de « le refus se VOIT » : la recette du
        projet (test 1.13) a relevé cinq clics d'affilée sur un bouton qui refusait correctement,
        mais dans le terminal.
        """
        print(f"[console] {mode_id} : {texte}")
        page = self.calib_pages.get(mode_id)
        if page is not None:
            page.montrer_avis(texte, alerte=alerte)

    def closeEvent(self, event):
        """Fermer la console doit fermer ce qu'elle a ouvert : la fenêtre, puis le moteur.

        `EngineServer.close()` est idempotente et supprime le dossier temporaire des candidats de
        calibration. Sans cet appel, un modèle EEG d'une personne identifiable pourrait survivre à
        la fermeture dans `%TEMP%` — inoffensif tant qu'il y reste, mais le premier remaniement
        qui le déplacerait le ferait ÉLIRE comme « modèle le plus récent ».
        """
        self.lanceur.arreter()
        if self.engine is not None:
            self.engine.close()
        super().closeEvent(event)

    def show_grid(self):
        self.stack.setCurrentWidget(self.grid)

    def show_calibration(self, mode_id):
        page = self.calib_pages.get(mode_id)
        if page is not None:
            self.stack.setCurrentWidget(page)

    def show_mode(self, mode_id):
        page = self.pages.get(mode_id)
        if page is not None:
            # Entrer dans la page est l'événement qui justifie de relire le disque : c'est là
            # qu'un modèle fraîchement entraîné doit apparaître dans la liste.
            page.rafraichir_choix()
            self.stack.setCurrentWidget(page)


def fake_state():
    """Un `snapshot()` fabriqué, pour monter l'interface sans casque ni moteur.

    Construit depuis le VRAI registre : si un `ModeSpec` change, ce qu'on teste change avec lui.
    Un état factice écrit à la main deviendrait faux en silence — exactement le défaut qu'on
    reproche à un catalogue de modes recopié dans l'interface.
    """
    return {
        "running": True, "board": "synthetic", "instance": "faux", "fs_hz": 250.0,
        "channels": ["Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8"],
        "mode": "ssvep", "modes": ["raw", "ssvep"], "phase": "decoding",
        "samples_published": 12345,
        "streams": ["EEG_API_Unicorn_raw", "EEG_API_Unicorn_quality",
                    "EEG_API_Unicorn_status", "EEG_API_Unicorn_decoded_ssvep"],
        "quality": {"sigmas": [7.2, 8.1, 6.9, 9.4, 5.5, 11.2, 6.1, 7.8],
                    "verdicts": ["ok"] * 8, "common_mode": 0.38, "reference_lost": False},
        "rest_instruction": "",
        "calibration": None,
        "modes_state": {
            "raw": {"id": "raw", "label": "Brut", "family": "brut", "phase": "running",
                    "published": True, "params": {}, "instruction": "", "stream": "raw",
                    "channels": ["Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8"],
                    "rest_report": None, "output": None},
            "ssvep": {"id": "ssvep", "label": "SSVEP", "family": "actif", "phase": "running",
                      "published": True, "params": {"freqs": [15.0, 20.0, 8.57]},
                      "instruction": "", "stream": "decoded_ssvep",
                      "channels": ["target_index", "freq_hz", "confidence",
                                   "score_15Hz", "score_20Hz", "score_8.57Hz"],
                      "rest_report": {"kind": "ssvep", "windows": 40, "targets": []},
                      "output": {"target_index": 0, "freq_hz": 15.0,
                                 "scores": [3.1, 0.4, 0.9], "artifact": False,
                                 "threshold": 2.5}},
        },
        "catalog": registry.catalog(),
    }


def _smoke():
    """Monte l'interface sans écran, depuis un état factice. Même philosophie que app.py --smoke.

    Ce qu'on vérifie ici est ce qui casse le plus souvent dans une interface : qu'elle se monte,
    qu'elle encaisse un état où tout est absent (moteur pas encore démarré), et qu'elle survit à
    une alarme. Le contenu métier, lui, est testé côté moteur — il n'y en a pas ici.
    """
    class _FauxMoteur:
        """Juste ce que la console lit : un état. Assez pour couvrir `refresh()`, qui est la
        SEULE ligne du fichier à toucher le moteur — sans ça, une faute de nom y passerait
        tous les tests et n'échouerait que devant un étudiant."""

        def __init__(self, journal):
            self.appels = 0
            self.commandes = []
            self.fermetures = 0
            # Le journal PARTAGÉ avec les faux processus. C'est lui, et lui seul, qui permet de
            # vérifier un ORDRE entre deux mécanismes différents (une commande au moteur, un
            # processus lancé) : deux listes séparées diraient que les deux ont eu lieu, jamais
            # lequel a précédé l'autre — or c'est exactement là qu'est le piège de cette page.
            self.journal = journal
            self.refus = {}       # {nom de commande : raison} — pour éprouver le chemin du refus

        def snapshot(self):
            self.appels += 1
            return fake_state()

        def submit(self, name, **params):
            """Simule la soumission d'une commande, et RETIENT ce qui a été soumis.

            Retenir compte : c'est ce qui permet de vérifier qu'un geste de l'interface arrive
            bien au moteur, avec les bons arguments. Sans ça, une case à cocher débranchée
            passerait tous les tests.
            """
            self.commandes.append((name, params))
            self.journal.append(("commande", name))
            if name in self.refus:
                return {"accepted": False, "reason": self.refus[name]}
            return {"accepted": True}

        def close(self):
            """`EngineServer.close()` : libère le dossier temporaire des candidats. Comptée ici
            parce que la console DOIT l'appeler en se fermant — sans ça, un modèle EEG d'une
            personne identifiable survit à la fermeture dans `%TEMP%`."""
            self.fermetures += 1

        def recent_window(self, seconds):
            """Un moteur factice n'a pas de tampon d'acquisition. La TracesView demande cette
            méthode, mais sur le faux moteur elle rend None. Le vrai tracé est éprouvé plus bas
            contre un vrai EngineServer."""
            return None

    class _FauxProcessus(QObject):
        """Un `QProcess` de façade : il n'exécute RIEN, il RETIENT ce qu'on lui a demandé.

        ⚠️ Aucun VRAI processus dans ce smoke. Un test qui démarre un pygame plein écran en CI est
        un test qu'on finit par désactiver, et le jour où on le désactive on perd d'un coup les
        trois règles du lanceur (une seule fenêtre, la commande vient du registre, une mort se
        voit). La surface imitée est exactement celle que `LanceurFenetre` utilise.
        """

        readyReadStandardOutput = Signal()
        finished = Signal(int, object)
        errorOccurred = Signal(object)

        def __init__(self, journal):
            super().__init__()
            self.journal = journal
            self.argv = None
            self.tue = False
            self.sortie = b""

        def setProcessChannelMode(self, mode):
            pass

        def start(self, program, args):
            self.argv = [program] + list(args)
            self.journal.append(("fenetre", tuple(self.argv)))

        def kill(self):
            self.tue = True

        def waitForFinished(self, ms=0):
            return True

        def readAllStandardOutput(self):
            sortie, self.sortie = self.sortie, b""
            return sortie

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    def rang(suite, valeur, depart=0):
        """L'indice de `valeur` à partir de `depart`, ou -1. Ne LÈVE jamais.

        `list.index` lèverait `ValueError` quand l'élément manque, et une assertion qui lève
        emporte avec elle TOUTES celles qui la suivent — c'est-à-dire exactement quand on a besoin
        de les lire. Mesuré : la preuve par mutation « le mode n'est pas arrêté avant sa
        calibration » faisait sauter la moitié de ce smoke sur un `index()` d'ordre.
        """
        try:
            return suite.index(valeur, depart)
        except ValueError:
            return -1

    app = QApplication.instance() or QApplication([])
    journal = []                  # la ligne du temps commune : commandes ET fenêtres
    processus = []                # les faux processus fabriqués, dans l'ordre
    horloge = [0.0]               # une horloge PILOTÉE : le délai d'attente doit être testable

    def _fabrique():
        processus.append(_FauxProcessus(journal))
        return processus[-1]

    moteur_faux = _FauxMoteur(journal)
    console = Console(moteur_faux, fabrique_fenetre=_fabrique, horloge=lambda: horloge[0])
    console.timer.stop()          # pas de moteur : on pilote l'état à la main
    console.show()

    state = fake_state()
    console.apply_state(state)
    chk("Unicorn" not in console.banner.liaison.text(),
        f"le bandeau dit que c'est un board de test — « {console.banner.liaison.text()} »")
    chk("σ" in console.banner.sigmas.text(), f"et les σ — « {console.banner.sigmas.text()} »")
    chk(console.banner.alarme.text() == "", "aucune alarme sur un montage sain")

    console.apply_state(state)
    chk(len(console.grid.tuiles) == len(registry.MODES),
        f"une tuile par mode du registre ({len(console.grid.tuiles)})")

    # Les modes que le moteur ne sait pas faire sont MONTRÉS, grisés, avec leur raison. Le
    # compte attendu est LU DANS LE REGISTRE, pas écrit ici : ce qui est vérifié est que la
    # grille ressort exactement ce que le moteur déclare, pas qu'il y en a deux aujourd'hui —
    # un chiffre en dur redeviendrait faux au premier mode qui migre (c'est arrivé au MI, puis
    # au P300).
    attendu_externes = sorted(s["id"] for s in registry.catalog() if s["status"] != "moteur")
    externes = [t for t in console.grid.tuiles.values() if t.spec["status"] != "moteur"]
    # Les IDENTITÉS, pas seulement le compte : « deux tuiles » resterait vrai si la grille
    # montrait le c-VEP deux fois. C'est donc plus strict que le `== 2` qu'elle remplace, en
    # plus de ne plus vieillir.
    chk(sorted(t.spec["id"] for t in externes) == attendu_externes,
        f"exactement les modes que le moteur ne fait pas ont une tuile grisée "
        f"({sorted(t.spec['id'] for t in externes)} pour {attendu_externes})")
    chk(all(not t.isEnabled() and t.detail.text() for t in externes),
        "chacune est grisée ET dit pourquoi elle ne démarre pas")
    # ⚠️ Les DEUX assertions ci-dessus sont VIDES depuis que le c-VEP a rejoint le moteur : plus
    # aucun mode n'a un statut autre que « moteur ». Elles restent — elles ne vieillissent pas, et
    # le prochain mode décrit avant d'être fait les réveillera — mais elles ne prouvent plus rien
    # aujourd'hui. Celle-ci prend le relais, dans l'autre sens : un mode du moteur doit être
    # CLIQUABLE. C'est le seul contrôle qui rougirait si un `ModeSpec` repassait « appli_pygame »,
    # ou si `status` cessait d'être ce qui dégrise la tuile.
    chk(all(t.isEnabled() for t in console.grid.tuiles.values()),
        f"...et toutes les autres sont dégrisées, c-VEP compris — 7 modes, 7 dans le moteur "
        f"({sorted(i for i, t in console.grid.tuiles.items() if not t.isEnabled())} grisée(s))")

    # ⚠️ ...et la branche INVERSE, sur un mode FABRIQUÉ. Depuis que le c-VEP a rejoint le moteur,
    # plus aucun `ModeSpec` du registre n'a `status != "moteur"` : le grisage, le message
    # `unavailable` et le masquage des boutons sont devenus du code à ZÉRO couverture, et c'est
    # MESURÉ — retirer `self.setEnabled(False)` de `grid.ModeTile.__init__` laissait ce smoke à
    # EXIT=0. C'est pourtant le « point d'honnêteté de l'interface » du projet : ce qui montre à
    # l'étudiant les modes que le produit décrit mais que le moteur ne sait pas faire, ET
    # pourquoi. On fabrique donc le `ModeSpec` que le registre n'a plus — même geste que
    # `core/modes/contract.py`, qui fabrique déjà des specs pour ses propres tests — plutôt que
    # de laisser un vrai mode fautif pour un test.
    from console.grid import ModeTile
    from core.modes.contract import ModeSpec as _ModeSpec

    def _tuile_fabriquee(**champs):
        return ModeTile(registry.serialize(_ModeSpec(
            id="pasfait", label="Pas fait", family="actif",
            summary="le résumé statique du mode", **champs)))

    grisee = _tuile_fabriquee(status="prevu",
                              unavailable="Demande un stimulus que le moteur ne rend pas.")
    chk(not grisee.isEnabled(), "une tuile de mode HORS moteur est grisée")
    chk(grisee.detail.text() == "Demande un stimulus que le moteur ne rend pas.",
        f"...et elle dit POURQUOI, à la place du résumé statique ({grisee.detail.text()!r})")
    chk(grisee.etat.text() == "prévu",
        f"...son statut est rendu en français, pas laissé en clé ({grisee.etat.text()!r})")
    chk(grisee.demarrage.isHidden() and grisee.bouton.isHidden() and grisee.publie.isHidden(),
        "...et ses trois boutons sont MASQUÉS : rien à cliquer sur un mode qui ne démarre pas")
    # Le CONTRASTE, sans quoi les quatre assertions ci-dessus passeraient sur une tuile qui
    # masquerait ses boutons pour tout le monde.
    active = _tuile_fabriquee(status="moteur", stream="decoded_pasfait", channels=("x",))
    chk(active.isEnabled() and not active.demarrage.isHidden()
        and active.detail.text() == "le résumé statique du mode",
        "...alors qu'un mode du MOTEUR reste cliquable et garde son résumé")
    # Un état reçu ne réanime pas la tuile grisée : `update_from` rend la main tout de suite.
    grisee.update_from({"phase": "running", "published": True, "output": None, "params": {}})
    chk(not grisee.isEnabled()
        and grisee.detail.text() == "Demande un stimulus que le moteur ne rend pas.",
        f"...et un état qui lui arriverait par erreur ne la réanime pas ({grisee.detail.text()!r})")

    chk(console.grid.tuiles["ssvep"].etat.text() == "décode",
        f"le SSVEP est annoncé « {console.grid.tuiles['ssvep'].etat.text()} »")
    chk(console.grid.tuiles["neuro"].etat.text() == "arrêté",
        "un mode non démarré est annoncé arrêté, pas absent")
    chk(console.grid.tuiles["ssvep"].publie.isChecked(), "et coché comme publié")

    # Le chemin « publier » de bout en bout : case cochée -> signal de la tuile -> signal de la
    # grille -> commande au moteur. C'est le seul geste de la grille qui change quelque chose sur
    # le RÉSEAU, et rien ne l'exerçait : une case débranchée aurait passé tous les tests.
    moteur_faux.commandes.clear()
    console.grid.tuiles["ssvep"].publie.click()
    chk(("set_published", {"id": "ssvep", "on": False}) in moteur_faux.commandes,
        f"décocher « publié » ordonne au moteur de retirer le flux ({moteur_faux.commandes})")
    console.grid.tuiles["ssvep"].publie.click()
    chk(("set_published", {"id": "ssvep", "on": True}) in moteur_faux.commandes,
        "et le recocher le remet")

    # ...et le rafraîchissement suivant ne doit PAS renvoyer la commande : la case se règle sur
    # l'état reçu, ce qui rejouerait le signal en boucle si `blockSignals` sautait un jour.
    moteur_faux.commandes.clear()
    console.apply_state(state)
    chk(not moteur_faux.commandes,
        f"et afficher l'état ne réémet aucune commande ({moteur_faux.commandes})")
    # ...y compris quand un mode PUBLIÉ vient de s'ARRÊTER. C'est l'autre branche de la même
    # méthode, et elle N'ÉTAIT PAS protégée : décocher la case émet `set_published`, donc la tuile
    # d'un mode arrêté postait une commande que personne n'avait demandée, engendrée par un simple
    # affichage. Trouvé en écrivant le test d'ORDRE de la calibration P300, où ce `set_published`
    # fantôme s'intercalait entre `stop_mode` et `start_calibration`.
    console.apply_state({**state, "modes_state": {}})
    chk(not moteur_faux.commandes,
        f"...et un mode publié qui s'ARRÊTE n'en réémet pas non plus ({moteur_faux.commandes})")
    console.apply_state(state)

    # Démarrer / arrêter de bout en bout : clic -> signal de la tuile -> signal de la grille ->
    # commande au moteur. Le bouton est CLIQUÉ, pas contourné : c'est la seule façon de prouver
    # que le lambda capture le bon identifiant et le bon sens.
    moteur_faux.commandes.clear()
    etiquette_avant_clic = console.grid.tuiles["neuro"].demarrage.text()
    console.grid.tuiles["neuro"].demarrage.click()      # neuro est arrêté dans l'état factice
    chk(("start_mode", {"id": "neuro"}) in moteur_faux.commandes,
        f"un mode arrêté se DÉMARRE depuis sa tuile ({moteur_faux.commandes})")
    # La règle centrale du sous-système : la tuile RESSORT l'état reçu, elle n'en déduit aucun.
    # Le clic poste une commande et rien d'autre — muter l'étiquette ICI la ferait mentir tant
    # que le moteur (le vrai, pas ce double factice) n'a pas réellement traité la commande.
    chk(console.grid.tuiles["neuro"].demarrage.text() == etiquette_avant_clic,
        f"et le clic ne mute PAS l'étiquette de sa propre tuile — seul le PROCHAIN état reçu le "
        f"fera ({console.grid.tuiles['neuro'].demarrage.text()})")
    chk(console.grid.tuiles["ssvep"].demarrage.text() == "Arrêter",
        f"et un mode qui décode propose « Arrêter » "
        f"({console.grid.tuiles['ssvep'].demarrage.text()})")

    moteur_faux.commandes.clear()
    console.grid.tuiles["ssvep"].demarrage.click()
    chk(("stop_mode", {"id": "ssvep"}) in moteur_faux.commandes,
        f"et un mode démarré s'ARRÊTE ({moteur_faux.commandes})")

    # Les modes que le moteur ne sait pas faire n'ont PAS de bouton : il ne mènerait qu'à un refus.
    chk(all(t.demarrage.isHidden() for t in console.grid.tuiles.values()
            if t.spec["status"] != "moteur"),
        "les modes de l'appli pygame n'exposent aucun bouton de démarrage")

    # Pendant un repos, la tuile porte la CONSIGNE — sans elle, le plancher est mesuré pendant
    # que l'étudiant fixe une cible, et il est faux pour toute la séance.
    en_repos = {**state, "modes_state": {**state["modes_state"], "ssvep": {
        **state["modes_state"]["ssvep"], "phase": "rest",
        "instruction": "Ne fixe AUCUNE cible : on mesure le bruit de fond."}}}
    console.apply_state(en_repos)
    chk("AUCUNE cible" in console.grid.tuiles["ssvep"].detail.text(),
        "pendant le repos, la tuile affiche la consigne")

    # Référence décrochée : le défaut qui rend une séance inexploitable sans autre symptôme.
    state["quality"] = {**state["quality"], "reference_lost": True, "common_mode": 1.0}
    console.apply_state(state)
    chk("RÉFÉRENCE DÉCROCHÉE" in console.banner.alarme.text(),
        "l'alarme de référence s'affiche, en clair")

    # Entrer dans une page de mode, en ressortir.
    console.apply_state(state)
    console.show_mode("ssvep")
    page = console.stack.currentWidget()
    chk(page is console.pages["ssvep"], "on entre dans la page du SSVEP")
    page.update_from(state)
    chk("CIBLE 0" in page.vue.verdict.text(),
        f"la sortie en direct montre la cible ({page.vue.verdict.text()})")
    chk(f"{state['modes_state']['ssvep']['output']['threshold']:g}" in page.vue.seuil.text(),
        f"et le seuil CHIFFRÉ, à côté des scores ({page.vue.seuil.text()})")
    chk(len(page.vue._barres) == 3, "une barre par cible")
    chk("score_15Hz" in page.extrait.toPlainText(),
        "l'extrait client porte les voies réellement publiées")
    chk("EEG_API_Unicorn_decoded_ssvep" in page.flux.text(),
        f"et le nom COMPLET du flux, celui que resolve_byprop demande ({page.flux.text()})")

    # « Copier » est le geste que fera l'étudiant : le smoke le CLIQUE, sinon le seul bouton qui
    # sort de l'application n'est jamais exercé.
    page.copier.click()
    chk(QApplication.clipboard().text() == page.extrait.toPlainText(),
        "cliquer « Copier » met l'extrait dans le presse-papiers")

    # Retirer une fréquence retire sa barre : sinon la vue garderait le score d'une cible morte.
    moins = {**state, "modes_state": {**state["modes_state"], "ssvep": {
        **state["modes_state"]["ssvep"], "params": {"freqs": [15.0, 20.0]},
        "output": {**state["modes_state"]["ssvep"]["output"], "scores": [3.1, 0.4]}}}}
    page.update_from(moins)
    chk(len(page.vue._barres) == 2,
        f"régler deux fréquences ne laisse que deux barres ({len(page.vue._barres)})")
    chk("score_8.57Hz" not in page.extrait.toPlainText(),
        "et l'extrait client est regénéré sur les nouvelles voies")

    # Mode arrêté : le bloc « brancher un client » doit le DIRE. Sans ça il continue d'annoncer
    # un nom de flux que plus personne ne publie, et l'étudiant s'abonne dans le vide.
    page.update_from({"modes_state": {}})
    chk("ARRÊTÉ" in page.flux.text(),
        f"un mode arrêté ne laisse pas croire que son flux existe ({page.flux.text()})")
    page.update_from(state)
    chk("EEG_API_Unicorn_decoded_ssvep" in page.flux.text(),
        "et le redémarrage rétablit le nom du flux")

    # Un mode PASSIF ne se rend pas comme un mode actif.
    neuro_state = {**state, "modes_state": {**state["modes_state"], "neuro": {
        "id": "neuro", "label": "Neuro", "family": "passif", "phase": "running",
        "published": True, "params": {"smoothing": 0.85, "rebaseline_s": 180.0},
        "instruction": "", "stream": "decoded_neuro",
        "channels": ["charge", "somnolence", "engagement", "artifact"], "rest_report": None,
        "output": {"z": {"charge": 1.2, "somnolence": -0.4, "engagement": 0.3},
                   "raw": {}, "artifact": False, "reason": "", "artifacts": 2}}}}
    console.show_mode("neuro")
    console.apply_state(neuro_state)
    page = console.pages["neuro"]
    chk(isinstance(page.vue, live_views.PassiveView), "le neuro a le rendu PASSIF, pas des cibles")
    chk("TENDANCE" in page.vue.avertissement.text(),
        "et l'avertissement sur l'échelle est sous les yeux, pas dans une doc")

    # L'APERÇU DE LA TUILE suit la même règle que la page : c'est la famille qui décide.
    # Un mode actif met en avant la cible que le MOTEUR a retenue ; un mode passif ne met rien
    # en avant du tout — surligner le plus grand indice le ferait passer pour une sélection.
    chk(console.grid.tuiles["ssvep"].apercu._retenue == 0
        and not console.grid.tuiles["ssvep"].apercu._centre,
        "la tuile d'un mode ACTIF montre la cible retenue par le moteur")
    chk(console.grid.tuiles["neuro"].apercu._retenue == -1
        and console.grid.tuiles["neuro"].apercu._centre,
        "celle d'un mode PASSIF ne désigne aucun gagnant, et signe ses valeurs")

    # Un indice qui cesse d'être rapporté perd sa barre, au lieu de rester figé sur sa dernière
    # valeur — le même défaut que la barre orpheline d'une cible SSVEP retirée.
    sans_engagement = {**neuro_state, "modes_state": {**neuro_state["modes_state"], "neuro": {
        **neuro_state["modes_state"]["neuro"],
        "output": {**neuro_state["modes_state"]["neuro"]["output"],
                   "z": {"charge": 1.2, "somnolence": -0.4}}}}}
    console.apply_state(sans_engagement)
    chk(set(page.vue._barres) == {"charge", "somnolence"},
        f"un indice qui disparaît perd sa barre ({sorted(page.vue._barres)})")
    z = neuro_state["modes_state"]["neuro"]["output"]["z"]
    attendu = int(z["charge"] / live_views.PassiveView.SPAN * 100)
    chk(page.vue._barres["charge"].value() == attendu,
        f"et la barre porte le z réellement reçu ({page.vue._barres['charge'].value()} pour "
        f"z={z['charge']:+.1f} sur ±{live_views.PassiveView.SPAN:g})")

    # Chaque barre porte le NOM en clair, la formule et le SENS de la montée — et les trois
    # viennent du moteur (`core.neuro_monitor.INDEX_DESCRIPTIONS`), pas d'une liste recopiée dans
    # l'interface. Cette page affichait la CLÉ brute (« charge ») pendant que l'écran pygame
    # montrait les trois : deux écrans du même produit qui disaient deux choses du même chiffre,
    # et le seul des deux qu'un étudiant gardera était le moins explicite.
    console.apply_state(neuro_state)
    etiquettes = [page.vue.barres.itemAt(i, QFormLayout.LabelRole).widget().text()
                  for i in range(page.vue.barres.rowCount())]
    nom, formule, sens = neuro_monitor.INDEX_DESCRIPTIONS["charge"]
    porteuse = [t for t in etiquettes if nom in t]
    chk(porteuse and formule in porteuse[0] and sens in porteuse[0],
        f"la barre « charge » porte son nom, sa formule et son sens de montée "
        f"({porteuse[0][:70] if porteuse else 'AUCUNE étiquette ne porte le nom'}…)")
    chk(all(cle in neuro_monitor.INDEX_DESCRIPTIONS for cle in neuro_monitor.INDEX_KEYS),
        "…et les trois indices publiés ont tous leur description : une clé sans description "
        "retomberait en silence sur son nom brut, sans formule ni sens")

    # Le bouton « ← Modes » est CLIQUÉ, pas contourné : c'est la seule sortie de la page.
    page.bouton_retour.click()
    chk(console.stack.currentWidget() is console.grid, "et « ← Modes » ramène sur la grille")

    # Motor Imagery : même famille « actif » que le SSVEP (donc la MÊME classe de vue), mais une
    # sortie de forme DIFFÉRENTE — des probabilités par classe, pas un score par cible. C'est
    # justement ce que la vue doit encaisser sans se mettre à mentir : avant ce correctif, elle
    # aurait affiché « aucune cible » en PERMANENCE (la clé `target_index` n'existe pas dans la
    # sortie du MI), quelle que soit l'intention réellement décodée.
    mi_state = {**state, "modes_state": {**state["modes_state"], "mi": {
        "id": "mi", "label": "Motor Imagery", "family": "actif", "phase": "running",
        "published": True,
        "params": {"model": "mi_model.joblib", "prob_min": 0.6, "vote_len": 5, "min_votes": 3},
        "instruction": "", "stream": "decoded_mi",
        "channels": ["intent_index", "confidence", "p_GAUCHE", "p_DROITE", "p_REPOS"],
        "rest_report": {"kind": "mi", "model": "mi_model.joblib",
                        "classes": ["GAUCHE", "DROITE", "REPOS"]},
        "output": {"intent_index": 0, "label": "GAUCHE", "confidence": 0.81,
                   "probas": {"GAUCHE": 0.81, "DROITE": 0.12, "REPOS": 0.07},
                   "threshold": 0.6}}}}
    console.show_mode("mi")
    console.apply_state(mi_state)
    mi_page = console.pages["mi"]
    chk(isinstance(mi_page.vue, live_views.ActiveView),
        "le MI a le rendu ACTIF, comme le SSVEP — même famille")
    chk("INTENTION GAUCHE" in mi_page.vue.verdict.text(),
        f"mais la sortie en direct nomme l'INTENTION décodée, pas une cible "
        f"({mi_page.vue.verdict.text()})")
    chk("probabilité" in mi_page.vue.seuil.text() and "z" not in mi_page.vue.seuil.text(),
        f"et l'échelle affichée est la PROBABILITÉ, jamais le z du SSVEP "
        f"({mi_page.vue.seuil.text()})")
    chk(len(mi_page.vue._barres) == 3,
        f"une barre par classe du modèle, pas par cible ({len(mi_page.vue._barres)})")
    chk(console.grid.tuiles["mi"].apercu._retenue == 0,
        "la tuile MI met aussi en avant la classe retenue par le moteur")

    # Vote non conclu (intent_index = -1) : ni cible, ni z — un message propre au MI, qui ne
    # doit jamais se lire comme le « aucune cible (rien au-dessus de z=...) » du SSVEP.
    mi_indecis = {**mi_state, "modes_state": {**mi_state["modes_state"], "mi": {
        **mi_state["modes_state"]["mi"],
        "output": {**mi_state["modes_state"]["mi"]["output"], "intent_index": -1}}}}
    console.apply_state(mi_indecis)
    chk("vote non conclu" in mi_page.vue.verdict.text() and "cible" not in mi_page.vue.verdict.text(),
        f"un vote non conclu le dit sans jamais parler de « cible » ({mi_page.vue.verdict.text()})")

    mi_page.bouton_retour.click()
    chk(console.stack.currentWidget() is console.grid, "et le MI ramène aussi sur la grille")

    # --- P300 : la TROISIÈME forme de sortie de la famille « actif » -------------
    # Elle n'a ni `probas` (ce n'est pas un vote de classes) ni `threshold` (le moteur prend
    # l'argmax, il ne compare ces scores à rien). C'est exactement cette absence de `threshold`
    # qui la faisait tomber dans le rendu du SSVEP : `params["freqs"]` absent -> six barres SANS
    # ÉTIQUETTE, `threshold` absent -> repli sur `Z_MIN`, et l'écran annonçait « échelle z ·
    # seuil 3 — un score au-dessus déclenche » AU-DESSUS de log-odds (négatifs, donc toutes les
    # barres à zéro), puis « CIBLE 3 · 0 Hz ». Quatre affirmations fausses, aucun message.
    # C'est la panne du MI recommencée un mode plus tard : d'où des assertions sur ce que
    # l'écran DIT, pas seulement sur la classe de vue instanciée.
    from console import SPAN_SEUILS
    from core.config import Z_MIN
    p300_state = {**state, "modes_state": {**state["modes_state"], "p300": {
        "id": "p300", "label": "P300", "family": "actif", "phase": "running", "published": True,
        "params": {"model": "p300_model_20260818_101500.joblib",
                   "stream_in": "EEG_API_Unicorn_stim"},
        "instruction": "", "stream": "decoded_p300",
        "channels": ["target_index", "confidence", "n_flashes"] + [f"score_{i}" for i in range(6)],
        "rest_report": {"kind": "p300", "model": "p300_model_20260818_101500.joblib",
                        "n_targets": 6},
        # Des log-odds RÉALISTES : tous négatifs, gagnant en 3. Des scores positifs cacheraient
        # la moitié du défaut (avec `Z_MIN` en seuil, des valeurs négatives donnent SIX barres à
        # zéro — un écran parfaitement muet).
        "output": {"target_index": 3, "confidence": -0.42, "n_flashes": 48,
                   "scores": [-1.9, -2.4, -1.2, -0.42, -2.0, -1.5]}}}}
    console.show_mode("p300")
    console.apply_state(p300_state)
    p3 = console.pages["p300"].vue
    chk(isinstance(p3, live_views.ActiveView),
        "le P300 a le rendu ACTIF, comme le SSVEP et le MI — même famille")
    chk(f"seuil {Z_MIN:g}" not in p3.seuil.text() and "échelle z" not in p3.seuil.text(),
        f"mais il n'annonce NI le z NI le seuil du SSVEP, qu'il n'a pas ({p3.seuil.text()})")
    chk("log-odds" in p3.seuil.text() and "AUCUN seuil" in p3.seuil.text(),
        f"il nomme son échelle et dit qu'il n'y a pas de seuil ({p3.seuil.text()})")
    chk(len(p3._barres) == 6 and all(e.text() for e, _b in p3._barres),
        f"six barres, et chacune porte une ÉTIQUETTE — pas six barres muettes "
        f"({[e.text() for e, _b in p3._barres]})")
    chk("CIBLE 3" in p3.verdict.text() and "Hz" not in p3.verdict.text(),
        f"le verdict nomme la cible retenue, et ne lui invente pas une fréquence "
        f"({p3.verdict.text()})")
    chk("48" in p3.verdict.text(),
        f"et dit sur combien de flashs elle repose — 48 et 12 ne se valent pas "
        f"({p3.verdict.text()})")
    # Les barres sont RELATIVES entre elles : la meilleure pleine, la pire vide. C'est le
    # classement qui décide, pas une position sur une règle graduée qui n'existe pas.
    valeurs = [b.value() for _e, b in p3._barres]
    chk(valeurs[3] == 100 and valeurs[1] == 0,
        f"la cible qui domine remplit sa barre, la plus faible est vide ({valeurs})")

    # L'APERÇU DE LA TUILE, sur les MÊMES données : il ne doit pas contredire la page.
    # ⚠️ Rien ne le touchait — les seules tuiles dont l'aperçu était lu sont `ssvep`, `neuro` et
    # `errp` — et c'est ce qui a laissé passer, dans du code DÉJÀ POUSSÉ, le repli sur `Z_MIN` :
    # le seuil du SSVEP (2,5) appliqué à des log-odds, avec `centre=False`, donc tout score
    # négatif écrasé à zéro. Or les scores P300 sont négatifs le plus souvent (une cible flashe
    # une fois sur six) : la tuile montrait SIX MOIGNONS DE 2 PX pendant que sa propre page
    # montrait un classement lisible. Deux écrans, mêmes données, verdicts opposés.
    apercu_p3 = console.grid.tuiles["p300"].apercu
    chk(apercu_p3._span != Z_MIN,
        f"la tuile P300 n'emprunte PAS le seuil du SSVEP pour mettre des log-odds à l'échelle "
        f"(span={apercu_p3._span}, Z_MIN={Z_MIN})")
    chk(apercu_p3._values and max(apercu_p3._values) == 1.0 and min(apercu_p3._values) == 0.0
        and apercu_p3._values.index(1.0) == 3,
        f"...elle montre le CLASSEMENT, comme la page : la cible qui domine pleine, la plus "
        f"faible vide — et AUCUNE écrasée à zéro parce qu'elle est négative ({apercu_p3._values})")
    chk(apercu_p3._retenue == 3,
        f"...et met en avant la cible que le MOTEUR a retenue, pas un maximum recalculé "
        f"({apercu_p3._retenue})")
    # ⚠️ L'assertion qui LIE les deux, et qui aurait attrapé le défaut ci-dessus le jour où il est
    # né : les deux précédentes lisent la page et la tuile SÉPARÉMENT, donc rien n'interdisait
    # qu'elles se contredisent (c'est arrivé, dans du code poussé). Elles appellent maintenant la
    # MÊME fonction, `console.classement_relatif` — cette ligne le vérifie sur les mêmes données.
    # `int()` et pas `round()` : c'est la conversion que la page applique (`QProgressBar` prend un
    # entier). Comparer deux arrondis différents ferait rougir sur 60,61 % contre 61 % — mesuré.
    chk([int(v * 100) for v in apercu_p3._values] == [b.value() for _e, b in p3._barres],
        f"la tuile et la page rendent le MÊME classement sur les mêmes données "
        f"({[int(v * 100) for v in apercu_p3._values]} contre "
        f"{[b.value() for _e, b in p3._barres]})")

    # Le SSVEP, lui, a bien un `threshold` publié : son échelle reste ABSOLUE, contre ce
    # seuil-là. Sans cette assertion, « ne plus jamais utiliser de seuil » passerait aussi.
    # ⚠️ `SPAN_SEUILS ×` le seuil, pas le seuil nu : la tuile s'arrêtait à 1× quand la page
    # va à 2×, donc sur ce fixture (score 3,1, seuil 2,5) la grille affichait une barre PLEINE et
    # la page 62 %. L'assertion figeait l'écart au lieu de l'interdire.
    seuil_ssvep = state["modes_state"]["ssvep"]["output"]["threshold"]
    chk(console.grid.tuiles["ssvep"].apercu._span == SPAN_SEUILS * seuil_ssvep,
        f"et la tuile SSVEP garde son échelle absolue, contre le seuil qu'elle PUBLIE, à la MÊME "
        f"échelle que sa page ({console.grid.tuiles['ssvep'].apercu._span} pour un seuil de "
        f"{seuil_ssvep})")
    # ...et on le VÉRIFIE sur le RENDU, pas seulement sur le réglage. Les deux côtés sont lus sur
    # les objets eux-mêmes (`_values`/`_span` pour la tuile, `value()` pour la page) : rien n'est
    # recalculé ici avec la formule de production, sans quoi le test ne prouverait que sa propre
    # arithmétique. `max(0, min(v/span, 1))` est la règle de dessin de `MiniBars.paintEvent`.
    console.apply_state(state)
    apercu_ssvep = console.grid.tuiles["ssvep"].apercu
    parts_tuile = [int(max(0.0, min(v / apercu_ssvep._span, 1.0)) * 100)
                   for v in apercu_ssvep._values]
    parts_page = [b.value() for _e, b in console.pages["ssvep"].vue._barres]
    chk(bool(parts_page) and parts_page == parts_tuile,
        f"la page SSVEP et sa tuile remplissent leurs barres à la MÊME hauteur "
        f"({parts_page} contre {parts_tuile}) — mêmes données, une seule lecture")

    # Manche non conclue : jamais le « aucune cible (rien au-dessus de z=...) » du SSVEP, et
    # surtout -1 n'est pas la cible 0 (cf. `no_decision_index` dans les métadonnées du flux).
    p300_indecis = {**p300_state, "modes_state": {**p300_state["modes_state"], "p300": {
        **p300_state["modes_state"]["p300"],
        "output": {**p300_state["modes_state"]["p300"]["output"], "target_index": -1}}}}
    console.apply_state(p300_indecis)
    chk("z=" not in p3.verdict.text() and "CIBLE" not in p3.verdict.text(),
        f"une manche non conclue le dit sans parler ni de z ni d'une cible retenue "
        f"({p3.verdict.text()})")

    console.pages["p300"].bouton_retour.click()
    chk(console.stack.currentWidget() is console.grid, "et le P300 ramène aussi sur la grille")

    # --- ErrP : la famille « passif » a une DEUXIÈME forme de sortie, différente du neuro -------
    # Round de correction 1 (tâche 4) : `PassiveView` et `grid.py` (aperçu de la tuile + résumé)
    # ne routaient que sur la clé "z", que la sortie de l'ErrP n'a jamais — la page restait
    # muette (texte vide), la tuile aussi, et rien ne rougissait puisqu'aucune valeur FABRIQUÉE
    # n'était montrée (le défaut symétrique au P300-rendu-en-SSVEP : là un SILENCE, pas un
    # mensonge). Ce détecteur, au réglage courant, n'attrape qu'une partie des erreurs :
    # l'écran ne doit donc JAMAIS afficher « ERREUR détectée » seul, comme un verdict fiable —
    # le score ET le point de fonctionnement doivent être lisibles ensemble, et `error=-1` (pas
    # de verdict) doit se lire différemment de `error=0` (correct).
    #
    # ⚠️ Le point de fonctionnement de ce fixture est CALQUÉ sur la seule séance réellement
    # mesurée du projet (docs/SPEC.md : à `tnr_target = 0.85`, TPR 0,500 / TNR 0,855). Il portait
    # 0,4615 / 0,9259 — 6/13 et 25/27, des ratios de très petit effectif — sous le mot
    # « mesuré ». Un contributeur qui ouvre ce fichier pour savoir ce que vaut l'ErrP y lisait
    # donc un troisième chiffre, contradictoire avec la doc, le contrat et l'autotest de
    # `lsl_io.py`. « Un chiffre recopié dans une prose finit toujours par mentir » : ce fixture n'en est
    # pas une, mais il ment aussi bien.
    errp_state = {**state, "modes_state": {**state["modes_state"], "errp": {
        "id": "errp", "label": "ErrP", "family": "passif", "phase": "running", "published": True,
        "params": {"model": "errp_model_20260818_150000.joblib", "tnr_target": 0.85},
        "instruction": "", "stream": "decoded_errp",
        "channels": ["error", "score", "threshold", "artifact"], "rest_report": None,
        "point_de_fonctionnement": {"tnr_target": 0.85, "seuil": 0.044, "tpr": 0.500,
                                    "tnr": 0.855},
        "output": {"error": 1, "score": 5.044, "artifact": 0, "threshold": 0.044}}}}
    console.show_mode("errp")
    errp_page = console.pages["errp"]

    # DÉMARRÉ, MAIS AUCUN FEEDBACK ENCORE (`output: None`) — l'état dans lequel la page vit ses
    # 23 premières secondes (chauffe + repos), plus le temps d'aller lancer `errp_stimulus.py`
    # dans un second terminal. Aucun état de ce smoke ne le construisait, et c'est le SEUL dans
    # lequel le défaut existait : `PassiveView` initialisait son avertissement avec le texte du
    # NEURO, et seule l'arrivée d'un feedback l'écrasait. La page de l'ErrP affirmait donc, en
    # toutes lettres et pendant tout ce temps, que son score est « un z contre TON repos du
    # jour ». C'est un log-odds contre le seuil d'une calibration. Une phrase FAUSSE sur l'unité
    # est pire qu'un silence — c'est la catégorie que ce chantier a lui-même classée comme la
    # pire (cf. le P300 rendu comme un SSVEP).
    errp_demarre = {**errp_state, "modes_state": {**errp_state["modes_state"], "errp": {
        **errp_state["modes_state"]["errp"], "output": None}}}
    console.apply_state(errp_demarre)
    avant = errp_page.vue.avertissement.text()
    chk("z contre" not in avant and "TENDANCE" not in avant,
        f"avant le premier feedback, la page ErrP ne parle JAMAIS d'un z contre le repos du "
        f"jour — c'est l'unité d'un AUTRE mode ({avant!r})")
    # ...et elle ne reste pas MUETTE pour autant. `ErrPRuntime.instruction()` rend "" une fois le
    # repos fini (il n'y a plus de consigne : c'est au stimulus de jouer), donc le label principal
    # de la page devenait VIDE. Un écran vide se lit « ça ne marche pas » — la panne canonique de
    # ce projet, sous une autre forme : l'étudiant traverse chauffe et repos, l'écran se vide, et
    # rien ne lui dit qu'il lui reste à lancer `errp_stimulus.py` dans un second terminal.
    chk(errp_page.vue.etat.text().strip() != "",
        f"...et elle dit tout de même quelque chose plutôt que de rester vide "
        f"({errp_page.vue.etat.text()!r})")

    console.apply_state(errp_state)
    chk(isinstance(errp_page.vue, live_views.PassiveView),
        "l'ErrP a le rendu PASSIF, comme le neuro — une réaction observée, pas un choix fait")
    chk("ERREUR" in errp_page.vue.etat.text(),
        f"un score au-dessus du seuil se lit comme une détection ({errp_page.vue.etat.text()!r})")
    chk("5.044" in errp_page.vue.avertissement.text()
        and "0.044" in errp_page.vue.avertissement.text(),
        f"...le score ET le seuil, CHIFFRÉS, côte à côte, jamais l'un sans l'autre "
        f"({errp_page.vue.avertissement.text()!r})")
    # ⚠️ Chaque taux ANCRÉ À SON LIBELLÉ, jamais « "50%" in texte ». Avec deux `in` indépendants,
    # échanger `tpr` et `tnr` dans `live_views._update_errp` — une ligne — laissait le test VERT
    # pendant que l'écran annonçait l'inverse exact de la vérité, sur le seul écran dont la
    # raison d'être est d'empêcher qu'on prenne ce verdict pour fiable.
    texte_errp = errp_page.vue.avertissement.text()
    chk("garde 86%" in texte_errp and "attrape 50%" in texte_errp,
        f"...ET le point de fonctionnement MESURÉ (pas seulement visé), chaque taux CÔTÉ SON "
        f"LIBELLÉ : « garde 86% des bonnes commandes » / « attrape 50% des erreurs » — un "
        f"échange tpr↔tnr doit rougir ICI ({texte_errp!r})")
    chk("visé 85%" in texte_errp,
        f"...et le taux VISÉ reste distinct des deux mesurés ({texte_errp!r})")

    # LE TAUX DE REJET ARTEFACT, que `ErrPRuntime.state()` calcule EXPRÈS pour cet écran. Il
    # arrivait dix fois par seconde dans `apply_state` et repartait à la poubelle : la console
    # est pourtant le SEUL client qui lit `state()` (le flux `status` ne porte pas `modes_state`).
    # Une séance à 36 rejets sur 40 publie 36 × `error=-1` — honnêtes, et indiscernables de 36
    # clignements. L'étudiant refait sa séance ; le « vérifie le contact des électrodes »
    # l'attendait sur le stdout du terminal de lancement.
    errp_rejet = {**errp_state, "modes_state": {**errp_state["modes_state"], "errp": {
        **errp_state["modes_state"]["errp"],
        "taux_rejet": 0.9, "epoques_vues": 40, "artefacts": 36,
        "output": {"error": -1, "score": 0.0, "artifact": 1, "threshold": 0.044}}}}
    console.apply_state(errp_rejet)
    texte_rejet = errp_page.vue.avertissement.text()
    chk("90%" in texte_rejet and "36/40" in texte_rejet,
        f"un sur-rejet d'artefact se VOIT sur la page, taux ET effectif — sans quoi 36 refus de "
        f"suite ressemblent à 36 clignements ({texte_rejet!r})")

    # `error = 0` (correct) ne doit plus jamais parler d'erreur.
    errp_correct = {**errp_state, "modes_state": {**errp_state["modes_state"], "errp": {
        **errp_state["modes_state"]["errp"],
        "output": {"error": 0, "score": -4.956, "artifact": 0, "threshold": 0.044}}}}
    console.apply_state(errp_correct)
    texte_correct = errp_page.vue.etat.text()
    chk("ERREUR" not in texte_correct,
        f"un score sous le seuil ne parle plus d'erreur ({texte_correct!r})")

    # `error = -1` (pas de verdict, ÉPOQUE PERDUE) : un troisième texte, distinct des deux autres
    # — le confondre avec « correct » affirmerait un « pas d'erreur » qu'on n'a pas observé.
    errp_perdu = {**errp_state, "modes_state": {**errp_state["modes_state"], "errp": {
        **errp_state["modes_state"]["errp"],
        "output": {"error": -1, "score": 0.0, "artifact": 0, "threshold": 0.044}}}}
    console.apply_state(errp_perdu)
    texte_perdu = errp_page.vue.etat.text()
    chk(texte_perdu != texte_correct and "ERREUR" not in texte_perdu,
        f"« pas de verdict » (-1, époque perdue) est un texte DIFFÉRENT de « correct » (0), et "
        f"ne parle jamais d'erreur ({texte_perdu!r} vs correct={texte_correct!r})")

    # `error = -1` mais ARTEFACT : un QUATRIÈME texte, distinct des trois autres — un rejet
    # d'artefact et une époque simplement hors du tampon ne sont pas la même panne.
    errp_artefact = {**errp_state, "modes_state": {**errp_state["modes_state"], "errp": {
        **errp_state["modes_state"]["errp"],
        "output": {"error": -1, "score": 0.0, "artifact": 1, "threshold": 0.044}}}}
    console.apply_state(errp_artefact)
    texte_artefact = errp_page.vue.etat.text()
    chk("artefact" in texte_artefact.lower() and texte_artefact != texte_perdu,
        f"...et un refus pour ARTEFACT se distingue lui aussi d'une époque simplement perdue "
        f"({texte_artefact!r} vs perdu={texte_perdu!r})")

    # L'APERÇU DE LA TUILE : deux valeurs signées (score, seuil), sur une échelle qui s'adapte à
    # LEUR PROPRE amplitude — jamais un axe fixe inventé (le même piège que le P300 rendu comme
    # un SSVEP, cf. `live_views.ActiveView`). Vide quand `error < 0` : `score`/`threshold` valent
    # alors 0.0 par CONVENTION, jamais une mesure (cf. `ErrPRuntime._traiter_feedback`) — les
    # montrer fabriquerait un chiffre.
    console.apply_state(errp_state)      # retour au verdict "erreur" : score=5.044, seuil=0.044
    chk(console.grid.tuiles["errp"].apercu._values == [5.044, 0.044]
        and console.grid.tuiles["errp"].apercu._centre
        and console.grid.tuiles["errp"].apercu._retenue == -1,
        f"la tuile montre score ET seuil, signés, sans rien mettre en avant "
        f"({console.grid.tuiles['errp'].apercu._values})")
    # ⚠️ `_span` — la valeur que le commentaire de `grid.py` présente comme le point important, et
    # que RIEN ne lisait : remplacer `max(abs(score), abs(seuil), 1.0)` par `NEURO_Z_SPAN`
    # laissait les trois assertions ci-dessus vertes et remettait la tuile ErrP dans le piège
    # exact que sa branche existe pour éviter (un log-odds rendu sur une échelle de z).
    chk(console.grid.tuiles["errp"].apercu._span == 5.044,
        f"...sur SA PROPRE amplitude, jamais l'échelle de z du neuro ni un axe fixe inventé "
        f"(span={console.grid.tuiles['errp'].apercu._span}, "
        f"NEURO_Z_SPAN={live_views.PassiveView.SPAN:g})")
    console.apply_state(errp_perdu)
    chk(console.grid.tuiles["errp"].apercu._values == [],
        f"...et rien quand il n'y a rien à montrer, pas un 0.0 fabriqué "
        f"({console.grid.tuiles['errp'].apercu._values})")

    # LE RÉSUMÉ de la tuile (`_resume`, affiché hors instruction active) porte lui aussi le
    # verdict ET le taux d'erreurs attrapées — jamais le texte statique du mode.
    console.apply_state(errp_state)
    resume_errp = console.grid.tuiles["errp"].detail.text()
    chk("ERREUR" in resume_errp and "attrape 50%" in resume_errp,
        f"le résumé de la tuile porte le verdict ET le point de fonctionnement "
        f"({resume_errp!r})")

    # ...et il l'encaisse INCOMPLET. `if pdf` protège du dict vide, pas du dict amputé : `_resume`
    # lisait `pdf['tpr']` en accès direct dans la fonction même qui explique, vingt-cinq lignes
    # plus haut, pourquoi il faut `.get` — « cette ligne tourne 10 fois par seconde […] un
    # KeyError y ferait tomber TOUTE l'interface, pas seulement sa propre tuile ». Faire évoluer
    # `point_de_fonctionnement` (ajouter `auc`, renommer `tpr` en `tpr_oof`) figeait donc la
    # grille entière en pleine séance.
    errp_pdf_partiel = {**errp_state, "modes_state": {**errp_state["modes_state"], "errp": {
        **errp_state["modes_state"]["errp"],
        "point_de_fonctionnement": {"tnr_target": 0.85, "seuil": 0.044, "auc": 0.71}}}}
    console.apply_state(errp_pdf_partiel)
    chk("ERREUR" in console.grid.tuiles["errp"].detail.text(),
        f"un point de fonctionnement INCOMPLET ne fait tomber NI la tuile NI la grille entière "
        f"({console.grid.tuiles['errp'].detail.text()!r})")

    errp_page.bouton_retour.click()
    chk(console.stack.currentWidget() is console.grid, "et l'ErrP ramène aussi sur la grille")

    # --- c-VEP : la QUATRIÈME forme de sortie de la famille « actif » ---------------------------
    # Des corrélations de Pearson, bornées dans [-1, 1], avec un seuil PUBLIÉ (`corr_min`) et une
    # marge. Ni le z du SSVEP (aucun plancher de repos n'est mesuré ici), ni les log-odds du P300
    # (aucun classifieur). Les valeurs du fixture sont celles de la seule séance réellement
    # mesurée du projet : ρ ≈ 0,33 quand la décision est juste, ≈ 0,21 quand elle est fausse
    # (cf. `core/config.py`, CVEP_CORR_MIN) — pas des chiffres ronds inventés, parce que c'est
    # justement à cette hauteur-là que l'échelle se joue.
    from core.lsl_io import cvep_channel_labels

    cvep_state = {**state, "modes_state": {**state["modes_state"], "cvep": {
        "id": "cvep", "label": "c-VEP", "family": "actif", "phase": "running", "published": True,
        "params": {"model": "cvep_model.npz", "stream_in": "EEG_API_Unicorn_stim",
                   "vote_len": 3, "min_votes": 2},
        "instruction": "", "stream": "decoded_cvep",
        # ⚠️ DÉRIVÉE, pas recopiée : cette ligne décrivait l'ANCIENNE forme du flux (8 voies, sans
        # `corr_min`/`margin`) et rien ne la reliait à sa source. Elle est inerte pour la console
        # (`mode_page` construit la vue avec `spec["channels"]` du registre), mais
        # `modes_state[*]["channels"]` part sur le flux `status` et un client le lit — et le
        # prochain test qui recopierait ce fixture hériterait de l'erreur.
        "channels": cvep_channel_labels(6),
        "rest_report": None,
        "decodages": 12, "sans_reference": 0, "reference_perimee": 0,
        "sous_les_seuils": 5, "vote_non_conclu": 2,
        "age_reference_s": 0.42, "corr_gagnant": 0.33, "corr_second": 0.21,
        "output": {"target_index": 2, "confidence": 0.33,
                   "scores": [0.11, 0.19, 0.33, 0.08, 0.21, 0.12],
                   "corr_min": 0.26, "margin": 0.09, "motif": ""}}}}
    console.show_mode("cvep")
    console.apply_state(cvep_state)
    cv = console.pages["cvep"].vue
    chk(isinstance(cv, live_views.ActiveView),
        "le c-VEP a le rendu ACTIF, comme le SSVEP, le MI et le P300 — même famille")
    chk("corrélation" in cv.seuil.text() and "échelle z" not in cv.seuil.text()
        and "log-odds" not in cv.seuil.text(),
        f"et il nomme SON échelle, ni celle du SSVEP ni celle du P300 ({cv.seuil.text()})")
    chk("0.26" in cv.seuil.text() and "0.09" in cv.seuil.text(),
        f"...avec SES DEUX seuils : `corr_min` seul ferait lire « 0,40 > 0,26, ça aurait dû "
        f"déclencher » sur une fenêtre où la 2e était à 0,38 ({cv.seuil.text()})")
    # ...ET le vote, qui fait partie de la même règle : sans lui, un étudiant qui voit une barre
    # franche sans verdict croit à un bug. La latence de `vote_len / 5 Hz` s'explique ici.
    chk("2 fenêtres d'accord sur les 3" in cv.seuil.text(),
        f"...et le VOTE, troisième moitié de la règle de décision ({cv.seuil.text()})")
    chk("CIBLE 2" in cv.verdict.text() and "Hz" not in cv.verdict.text(),
        f"le verdict nomme la cible retenue, et ne lui invente pas une fréquence — le c-VEP "
        f"cherche une PHASE ({cv.verdict.text()})")

    # ⚠️⚠️ L'APERÇU DE LA TUILE, sur les mêmes données. C'EST L'ASSERTION QUI MANQUAIT au P300 et
    # qui a laissé le repli sur `Z_MIN` survivre deux chantiers dans du code poussé. Ici le piège
    # est le SYMÉTRIQUE : le c-VEP publie bien un seuil, donc rien n'empêchait de lui appliquer
    # la formule du SSVEP — `max(2 × 0,26, 1.0)` = 1,0, sur des corrélations qui valent 0,21 à
    # 0,33. Toutes les barres s'écraseraient dans le tiers bas, visuellement identiques, alors
    # que 0,33 et 0,21 sont exactement ce qui sépare une décision juste d'une fausse.
    from console import SPAN_SEUILS
    apercu_cv = console.grid.tuiles["cvep"].apercu
    corr_min = cvep_state["modes_state"]["cvep"]["output"]["corr_min"]
    chk(apercu_cv._span == SPAN_SEUILS * corr_min,
        f"la tuile c-VEP met ses corrélations à l'échelle de SON `corr_min` publié "
        f"(span={apercu_cv._span} pour corr_min={corr_min})")
    chk(apercu_cv._span != Z_MIN and apercu_cv._span < 1.0,
        f"...donc NI le seuil du SSVEP, NI le plafond 1,0 de la formule du SSVEP, qui écraserait "
        f"0,21 et 0,33 dans le tiers bas de la barre (span={apercu_cv._span}, Z_MIN={Z_MIN})")
    chk(apercu_cv._values == cvep_state["modes_state"]["cvep"]["output"]["scores"]
        and apercu_cv._retenue == 2 and not apercu_cv._centre,
        f"...elle montre les corrélations TELLES QUELLES (échelle absolue, pas un classement) et "
        f"met en avant la cible que le MOTEUR a retenue ({apercu_cv._values}, {apercu_cv._retenue})")
    # L'assertion qui LIE la tuile et la page : les deux précédentes les lisent séparément, donc
    # rien ne leur interdirait de se contredire — c'est arrivé, dans du code poussé (cf. le bloc
    # P300 ci-dessus). `max(0, min(v/span, 1))` est la règle de dessin de `MiniBars.paintEvent`.
    parts_tuile = [int(max(0.0, min(v / apercu_cv._span, 1.0)) * 100) for v in apercu_cv._values]
    chk(parts_tuile == [b.value() for _e, b in cv._barres],
        f"la tuile et la page remplissent leurs barres à la MÊME hauteur "
        f"({parts_tuile} contre {[b.value() for _e, b in cv._barres]})")

    # ⚠️ ...ET À `corr_min = 0`, LE SEUL CAS QUI SÉPARE LES DEUX ÉCRITURES. C'est une valeur
    # LÉGALE (`min=0.0` sur le réglage) et ENCOURAGÉE en séance — l'aide dit « DESCENDS cette
    # valeur… SANS risque » et `docs/recette.md` 2.9 descend le seuil comme geste de routine. La
    # formule était écrite deux fois et différait déjà d'un `or 1.0` dans le commit qui
    # l'introduisait : la page affichait 33 %, la tuile TOUTES LES BARRES PLEINES (span 0 rattrapé
    # à 1e-6 par `MiniBars.set_values`). Mêmes données, deux diagnostics opposés — « rien n'est
    # fixé » d'un côté, « tout sature » de l'autre. L'assertion ci-dessus ne l'attrapait pas :
    # elle ne tournait que sur 0,26.
    cvep_zero = {**cvep_state, "modes_state": {**cvep_state["modes_state"], "cvep": {
        **cvep_state["modes_state"]["cvep"],
        "output": {**cvep_state["modes_state"]["cvep"]["output"], "corr_min": 0.0}}}}
    console.apply_state(cvep_zero)
    chk(apercu_cv._span == 1.0,
        f"à `corr_min = 0` l'échelle retombe sur celle d'une corrélation entière (1,0), jamais "
        f"sur 0 — une échelle nulle rendrait TOUTE barre pleine ({apercu_cv._span})")
    parts_zero = [int(max(0.0, min(v / apercu_cv._span, 1.0)) * 100) for v in apercu_cv._values]
    chk(parts_zero == [b.value() for _e, b in cv._barres] and max(parts_zero) < 100,
        f"...et la tuile et la page restent d'accord — c'est le cas où elles divergeaient "
        f"({parts_zero} contre {[b.value() for _e, b in cv._barres]})")
    console.apply_state(cvep_state)      # on rend l'état attendu par la suite du bloc

    # Pas de décision : le MOTIF est ce que l'écran doit montrer, pas « aucune cible ». Les trois
    # causes appellent trois gestes OPPOSÉS (relancer l'émetteur · vérifier le nom du flux ·
    # saliner), et la console ne les traduit pas — la phrase vient du moteur.
    cvep_muet = {**cvep_state, "modes_state": {**cvep_state["modes_state"], "cvep": {
        **cvep_state["modes_state"]["cvep"],
        "output": {**cvep_state["modes_state"]["cvep"]["output"], "target_index": -1,
                   "scores": [0.0] * 6, "confidence": 0.0,
                   "motif": "horloge PÉRIMÉE — l'émetteur s'est tu (planté ? fenêtre fermée ?)"}}}}
    console.apply_state(cvep_muet)
    chk("PÉRIMÉE" in cv.verdict.text() and "CIBLE" not in cv.verdict.text()
        and "z=" not in cv.verdict.text(),
        f"sans décision, l'écran dit LAQUELLE des trois causes — jamais « aucune cible » nu, "
        f"jamais le « rien au-dessus de z » du SSVEP ({cv.verdict.text()})")
    resume_cvep = console.grid.tuiles["cvep"].detail.text()
    chk("PÉRIMÉE" in resume_cvep and "Hz" not in resume_cvep,
        f"...et le résumé de la tuile aussi, sans inventer de fréquence ({resume_cvep!r})")

    console.pages["cvep"].bouton_retour.click()
    chk(console.stack.currentWidget() is console.grid, "et le c-VEP ramène aussi sur la grille")

    # --- la page de calibration -------------------------------------------------
    # Elle est éprouvée sur des états FABRIQUÉS, phase par phase : c'est le seul moyen de
    # vérifier chaque écran sans jouer sept minutes de séance.
    console.show_calibration("mi")
    cal = console.stack.currentWidget()
    chk(cal is console.calib_pages["mi"], "« Calibrer » ouvre la page de calibration du MI")
    # Là encore le compte vient du CONTRAT, et le critère a changé le 2026-09-07 : ce n'est plus
    # `kind == "console"` (OÙ la calibration vivait) mais `jouable` (le moteur a-t-il un runtime
    # pour elle). Les deux coïncidaient tant que le MI était seul ; ils divergent dès qu'une
    # calibration menée par une FENÊTRE devient jouable par le moteur — et c'est tout l'objet du
    # chantier. Prendre `kind` ici laisserait les trois nouvelles pages invisibles.
    attendu_calib = [s["id"] for s in registry.catalog()
                     if s["status"] == "moteur" and (s.get("calibration") or {}).get("jouable")]
    chk(sorted(console.calib_pages) == sorted(attendu_calib),
        f"et exactement les modes dont le moteur sait JOUER la calibration en ont une "
        f"({sorted(console.calib_pages)} pour {sorted(attendu_calib)})")

    # 1. Avant : le briefing du CONTRAT, pas un texte recopié dans l'interface.
    console.apply_state({**mi_state, "calibration": None})
    from core.modes import mi_calib
    chk(mi_calib.BRIEFING[0] in cal.briefing.text(),
        "le briefing affiché vient du contrat du mode")
    chk(cal.bouton_commencer.isEnabled(), "et « Commencer » est actif")

    # --- le CONTRÔLE DE LIAISON s'interpose, et il REFUSE ---------------------------------
    # Il vient de `research/ui.py:signal_check`, qui existe depuis le jour où un câble débranché a
    # laissé enregistrer 3,4 min de signal plat puis produire un modèle à 0 %. Les fenêtres de
    # `src/stimulus/` ne peuvent pas le reprendre — elles n'ouvrent pas le casque, elles n'ont
    # aucun σ à montrer. La console, elle, sonde `snapshot()`.
    # ⚠️ Une qualité NEUVE, relue depuis `fake_state()` : l'état `state` de ce smoke a été mué
    # plus haut pour éprouver l'alarme du bandeau (`reference_lost: True`), et tous les fixtures
    # qui en descendent — `mi_state`, `p300_state` — portent cette référence décrochée. Les
    # réutiliser ici ferait refuser le contrôle de liaison pour la MAUVAISE raison, et les
    # assertions sur la voie morte passeraient à côté de leur sujet.
    qualite_saine = fake_state()["quality"]
    # Le MI est ARRÊTÉ ici (`modes_state` sans lui) : c'est le chemin nominal d'une calibration.
    # La console arrête toujours le mode avant SA calibration — règle uniforme, elle ne recopie
    # PAS la table du moteur disant lesquels se voleraient les marqueurs — et ce chemin-là est
    # éprouvé plus bas, sur le P300 qui décode.
    mi_sain = {**mi_state, "calibration": None, "quality": qualite_saine,
               "modes_state": state["modes_state"]}

    moteur_faux.commandes.clear()
    # Capturé AVANT le clic : c'est ce que le formulaire contient RÉELLEMENT en ce moment, pas une
    # valeur supposée — un formulaire qui soumettrait 999 en dur, peu importe ce qu'il affiche,
    # doit faire échouer la comparaison plus bas.
    valeurs_formulaire = cal.formulaire.values()
    cal.bouton_commencer.click()
    chk(console.stack.currentWidget() is console.contact,
        "« Commencer » passe D'ABORD par le contrôle de la liaison casque")
    chk(not moteur_faux.commandes,
        f"et RIEN n'est encore soumis au moteur à ce stade ({moteur_faux.commandes})")

    # Une voie MORTE : le lancement doit être refusé, et le refus doit se LIRE. Un bouton
    # simplement grisé se lit comme une interface cassée — c'est la panne que ce chantier répare
    # (recette 1.13 : cinq clics d'affilée sur un bouton qui refusait, dans le terminal).
    mauvais = {**mi_sain, "quality": {
        **qualite_saine, "sigmas": [7.2, 0.0, 6.9, 9.4, 5.5, 11.2, 6.1, 7.8],
        "verdicts": ["ok", "morte", "ok", "ok", "ok", "ok", "ok", "ok"]}}
    console.apply_state(mauvais)
    chk(not console.contact.bouton_lancer.isEnabled(),
        "une voie morte empêche le lancement")
    chk("C3" in console.contact.refus.text() and "morte" in console.contact.refus.text(),
        f"...et le DIT à l'écran, en nommant la voie — pas seulement en grisant un bouton "
        f"({console.contact.refus.text()[:90]}…)")
    # La RÉFÉRENCE DÉCROCHÉE, le défaut que les huit σ ne montrent PAS : les voies mesurent alors
    # toutes la même référence flottante, avec des amplitudes parfaitement plausibles.
    reference = {**mi_sain, "quality": {
        **qualite_saine, "reference_lost": True, "common_mode": 0.99}}
    console.apply_state(reference)
    chk(not console.contact.bouton_lancer.isEnabled()
        and "MASTOÏDES" in console.contact.refus.text(),
        f"une référence décrochée refuse elle aussi, en nommant le geste qui la répare "
        f"({console.contact.refus.text()[:70]}…)")
    # ...et un état SANS qualité (tampon pas encore rempli) refuse aussi : lancer là reviendrait à
    # enregistrer à l'aveugle, ce qui est exactement l'accident d'origine.
    console.apply_state({**mi_sain, "quality": None})
    chk(not console.contact.bouton_lancer.isEnabled() and console.contact.refus.text(),
        f"...et tant qu'AUCUN σ n'est mesuré, on ne lance pas non plus "
        f"({console.contact.refus.text()[:70]}…)")

    # Les voies CLÉS du mode visé sont surlignées, et la liste vient du CONTRAT.
    console.apply_state(mi_sain)
    cles_mi = registry.get("mi").key_channels
    chk(all(state["channels"][i] in console.contact.cles.text() for i in cles_mi),
        f"les voies clés du MI sont nommées, telles que son contrat les déclare "
        f"({console.contact.cles.text()[:80]}…)")
    chk(console.contact.bouton_lancer.isEnabled() and not console.contact.refus.text(),
        "et sur un montage sain, le lancement est permis")

    # Le clic qui lance pour de bon.
    moteur_faux.commandes.clear()
    console.contact.bouton_lancer.click()
    chk(console.stack.currentWidget() is cal,
        "cliquer « Commencer la calibration » ramène sur la page de calibration")
    envoyees = [c for c in moteur_faux.commandes if c[0] == "start_calibration"]
    chk(envoyees and envoyees[0][1]["id"] == "mi"
        and envoyees[0][1]["params"] == valeurs_formulaire,
        f"...et soumet EXACTEMENT ce que le formulaire contenait ({envoyees} "
        f"pour un formulaire à {valeurs_formulaire})")
    chk(not processus,
        f"le MI ne lance AUCUNE fenêtre : son contrat ne déclare pas de stimulus, le moteur mène "
        f"seul son protocole ({processus})")

    # Un refus du moteur DOIT s'afficher sur la page, pas seulement sur stdout.
    moteur_faux.refus["start_calibration"] = "une calibration est déjà en cours (P300)"
    console.apply_state(mi_sain)
    cal.bouton_commencer.click()
    console.contact.bouton_lancer.click()
    chk("déjà en cours" in cal.avis.text(),
        f"un refus du moteur est AFFICHÉ sur la page, mot pour mot ({cal.avis.text()!r})")
    moteur_faux.refus.clear()

    # 2. Pendant : la consigne, la classe, le décompte, la progression — tous reçus, aucun calculé.
    en_cours = {**mi_state, "calibration": {
        "mode_id": "mi", "label": "Calibration Motor Imagery", "phase": "essais",
        "etape": "imagerie", "classe": "GAUCHE",
        "instruction": "Imagine : SERRE le POING GAUCHE", "rappel": "sens le serrement",
        "essai": 7, "total": 42, "restant_s": 2.4, "duree_estimee_s": 400.0,
        "params": {"trials_per_class": 14}, "classes": ["GAUCHE", "DROITE", "REPOS"],
        "resultat": None, "probleme": ""}}
    console.apply_state(en_cours)
    chk("SERRE le POING GAUCHE" in cal.consigne.text(),
        f"la consigne du moteur est affichée telle quelle ({cal.consigne.text()})")
    chk("2.4" in cal.decompte.text() or "2,4" in cal.decompte.text(),
        f"le décompte vient du moteur, pas d'un timer local ({cal.decompte.text()})")
    # Égalité, pas sous-chaîne : un mutant qui inverserait en « essai 42 sur 7 » contient
    # toujours « 7 » et « 42 » et passerait un test par `in`.
    chk(cal.progression.text() == "essai 7 sur 42",
        f"et la progression nomme les deux nombres, à l'identique ({cal.progression.text()!r})")
    chk(not cal.formulaire.isEnabled(),
        "le formulaire est verrouillé pendant la séance : le changer n'aurait aucun effet")

    moteur_faux.commandes.clear()
    cal.bouton_abandon.click()
    chk(("cancel_calibration", {}) in moteur_faux.commandes,
        f"« Abandonner » passe par la file de commandes ({moteur_faux.commandes})")

    # 3. Après : l'accuracy HONNÊTE, le hasard à côté, et la phrase qui dit ce que ça vaut.
    fini = {**mi_state, "calibration": {**en_cours["calibration"], "phase": "fini",
            "etape": "", "classe": "", "instruction": "", "restant_s": 0.0,
            "resultat": {"modele": "/tmp/mi_model_20260730-141205.joblib",
                         "nom": "mi_model_20260730-141205.joblib",
                         "enregistrement": "/tmp/mi_calib_20260730-141205_n42.npz",
                         "n_essais": 42, "n_fenetres": 126, "cv_groupee": 0.401,
                         "cv_naive": 0.556, "hasard": 1 / 3,
                         "classes": ["GAUCHE", "DROITE", "REPOS"],
                         "honnetete": mi_calib.HONNETETE,
                         "verdict": "FAIBLE — ré-essaie"},
            # Le CANDIDAT : le modèle est écrit, mais dans un dossier temporaire. Tant que ce
            # champ est renseigné, RIEN n'est dans `data/` (tâche 5) et il reste une décision.
            "candidat": {"modele": "/tmp/calib/candidat_mi_model_20260730-141205.joblib"}}}
    console.apply_state(fini)
    chk("40.1" in cal.resultat.text() or "40,1" in cal.resultat.text(),
        f"l'accuracy affichée est l'HONNÊTE ({cal.resultat.text()})")
    chk("55.6" not in cal.resultat.text() and "55,6" not in cal.resultat.text(),
        f"et JAMAIS la naïve, qui est gonflée de 10 à 16 points ({cal.resultat.text()})")
    chk("33" in cal.resultat.text(),
        f"le niveau du hasard est à côté — sans lui, 40 % ne veut rien dire ({cal.resultat.text()})")
    chk("mi_model_20260730-141205.joblib" in cal.details.text(),
        f"le nom du modèle produit est donné ({cal.details.text()})")
    # ⚠️ La phrase d'honnêteté vient du RÉSULTAT DU MOTEUR, plus d'une constante de la page. Elle
    # vivait dans `calib_page.py` — donc affichée sous TOUS les résultats de calibration, la page
    # ne connaissant aucun mode. Depuis que le P300 se calibre lui aussi ici, ce « 40 % à trois
    # classes » se serait affiché mot pour mot sous une SÉLECTION parmi six cibles.
    chk("séance de référence" in cal.honnetete.text(),
        "et la page dit franchement ce qu'un résultat modeste signifie")
    chk(cal.honnetete.text() == mi_calib.HONNETETE,
        "...avec la phrase que la calibration MI publie elle-même, pas une constante d'interface")

    # --- LA DÉCISION : « Enregistrer » ou « Refaire » -------------------------------------
    # Sans ces deux boutons, PLUS AUCUNE calibration n'atteint `data/` : la tâche 5 a déplacé
    # l'écriture derrière un geste explicite, pour qu'un modèle soit JUGÉ avant d'être gardé.
    chk(cal.bouton_enregistrer.isVisibleTo(cal) and cal.bouton_refaire.isVisibleTo(cal),
        "un candidat en attente fait apparaître « Enregistrer » et « Refaire »")
    chk("temporaire" in cal.decision.text() and "data/" in cal.decision.text(),
        f"...et l'écran DIT qu'un chiffre affiché n'est pas encore un modèle enregistré "
        f"({cal.decision.text()[:80]}…)")

    # ⚠️ La console n'écrit JAMAIS sur le disque : elle envoie des commandes. On le PROUVE en
    # comparant l'empreinte du VRAI `data/` avant et après le clic, servi par un moteur FACTICE
    # (qui ne fait rien d'autre que retenir la commande). `git status` ne prouverait rien : `data/`
    # est gitignoré.
    from core.config import DATA_DIR, empreinte_dossier
    avant_disque = empreinte_dossier(DATA_DIR)
    moteur_faux.commandes.clear()
    cal.bouton_enregistrer.click()
    chk(("save_calibration", {}) in moteur_faux.commandes,
        f"« Enregistrer » envoie `save_calibration` au moteur ({moteur_faux.commandes})")
    cal.bouton_refaire.click()
    chk(("discard_calibration", {}) in moteur_faux.commandes,
        f"« Refaire » envoie `discard_calibration` ({moteur_faux.commandes})")
    chk(empreinte_dossier(DATA_DIR) == avant_disque,
        "et NI l'un NI l'autre n'a touché au disque : c'est la boucle du moteur qui déplace les "
        "fichiers, depuis le fil qui les a écrits")

    # Le candidat RETIRÉ (« Enregistrer » appliqué par le moteur) : plus rien à décider, mais le
    # verdict RESTE à l'écran — il faut pouvoir le lire après avoir enregistré.
    enregistre = {**fini, "calibration": {**fini["calibration"], "candidat": None,
                  "resultat": {**fini["calibration"]["resultat"],
                               "modele": "data/mi_model_20260730-141205.joblib"}}}
    console.apply_state(enregistre)
    chk("40.1" in cal.resultat.text() or "40,1" in cal.resultat.text(),
        f"une fois enregistré, le verdict reste lisible ({cal.resultat.text()[:60]}…)")
    chk(not cal.bouton_enregistrer.isVisibleTo(cal),
        "mais « Enregistrer » disparaît : il n'y a plus rien à trancher")
    chk("data/mi_model_20260730-141205.joblib" in cal.decision.text(),
        f"...et l'écran dit OÙ le modèle est désormais ({cal.decision.text()!r})")

    # Un refus de `save_calibration` (candidat déjà tranché ailleurs) doit se VOIR lui aussi.
    console.apply_state(fini)
    moteur_faux.refus["save_calibration"] = "rien à enregistrer : aucune calibration n'attend"
    cal.bouton_enregistrer.click()
    chk("rien à enregistrer" in cal.decision.text(),
        f"un refus d'enregistrement s'affiche mot pour mot ({cal.decision.text()[:60]}…)")
    moteur_faux.refus.clear()

    # --- le résultat d'un AUTRE mode : aucun chiffre fabriqué -----------------------------
    # Le P300 ne mesure ni « fenêtres d'entraînement » ni « classes » : il compte des manches et
    # une SÉLECTION. La page écrivait les lignes du MI en dur — elle affichait donc, sous un
    # résultat P300, « 0 fenêtres d'entraînement — classes : ». Deux chiffres inventés et une
    # liste vide, sur le seul écran qui sert à décider si on garde le modèle.
    from core.modes import p300_calib
    cal_p3 = console.calib_pages["p300"]
    console.show_calibration("p300")
    p300_fini = {**state, "calibration": {
        "mode_id": "p300", "label": "Calibrer le P300", "phase": "fini", "etape": "",
        "classe": "", "instruction": "", "rappel": "", "restant_s": 0.0, "essai": 12,
        "total": 12, "duree_estimee_s": 132.0, "params": {}, "probleme": "",
        "resultat": {"modele": "/tmp/calib/candidat_p300_model_20260907_101500.joblib",
                     "nom": "p300_model_20260907_101500.joblib",
                     "enregistrement": "/tmp/calib/candidat_p300_calib_20260907_101500.npz",
                     "n_essais": 576, "n_manches": 12, "auc": 0.71,
                     "selection": 10 / 12, "selection_ok": 10, "selection_total": 12,
                     "hasard": 1 / 6, "verdict": "EXCELLENT",
                     "honnetete": p300_calib.HONNETETE},
        "candidat": {"modele": "/tmp/calib/candidat_p300_model_20260907_101500.joblib"}}}
    console.apply_state(p300_fini)
    chk("83.3" in cal_p3.resultat.text() and "17 %" in cal_p3.resultat.text(),
        f"le P300 affiche SA mesure — la sélection — et SON hasard (1/6) "
        f"({cal_p3.resultat.text()})")
    chk("fenêtres" not in cal_p3.details.text() and "classes" not in cal_p3.details.text(),
        f"...et AUCUN chiffre du MI n'est fabriqué à côté ({cal_p3.details.text()!r})")
    chk("12 manches" in cal_p3.details.text() and "576 essais" in cal_p3.details.text(),
        f"...seulement ce que son résultat porte vraiment ({cal_p3.details.text()!r})")
    # L'AUC du P300 est un DÉTAIL — elle accompagne la sélection sans jamais la remplacer. Cette
    # ligne est le pendant de celle de l'ErrP juste en dessous : la page n'affiche l'AUC en détail
    # que lorsqu'elle n'est PAS la mesure qui décide, et retirer ce détail pour l'ErrP ne doit pas
    # le retirer ici du même geste.
    chk("AUC cible/non-cible 71 %" in cal_p3.details.text(),
        f"...dont son AUC, en DÉTAIL et jamais comme mesure qui décide ({cal_p3.details.text()!r})")
    chk(cal_p3.honnetete.text() == p300_calib.HONNETETE
        and "40 %" not in cal_p3.honnetete.text(),
        "et sa phrase d'honnêteté est CELLE DU P300, jamais celle du MI")

    # --- et le TROISIÈME mode qui se calibre ici : l'ErrP -----------------------------------
    # Il ne mesure NI accuracy par essai (MI), NI sélection parmi six cibles (P300) : il répond
    # oui/non à chaque feedback, et le seul de ses chiffres qui ne soit pas mesuré au seuil qui l'a
    # choisi est son AUC hors-pli. La page doit donc l'afficher COMME MESURE, contre un hasard de
    # 50 %, sans rien fabriquer des deux autres modes. Les valeurs sont celles de la seule séance
    # ErrP réellement enregistrée sur un cerveau (2026-07-24 : AUC 0,776, p = 0,0099, 200 essais).
    from core.modes import errp_calib
    cal_errp = console.calib_pages["errp"]
    console.show_calibration("errp")
    errp_fini = {**state, "calibration": {
        "mode_id": "errp", "label": "Calibrer l'ErrP", "phase": "fini", "etape": "",
        "classe": "", "instruction": "", "rappel": "", "restant_s": 0.0, "essai": 200,
        "total": 200, "duree_estimee_s": 420.0, "params": {}, "probleme": "",
        "resultat": {"modele": "/tmp/calib/candidat_errp_model_20260907_101500.joblib",
                     "nom": "errp_model_20260907_101500.joblib",
                     "enregistrement": "/tmp/calib/candidat_errp_calib_20260907_101500_n200.npz",
                     "n_essais": 200, "n_erreurs": 56, "auc": 0.776, "perm_p": 0.0099,
                     "tpr": 0.500, "tnr": 0.855, "hasard": 0.5,
                     "verdict": "BON pour un ErrP mono-essai",
                     "honnetete": errp_calib.HONNETETE},
        "candidat": {"modele": "/tmp/calib/candidat_errp_model_20260907_101500.joblib"}}}
    console.apply_state(errp_fini)
    chk(("77.6" in cal_errp.resultat.text() or "77,6" in cal_errp.resultat.text())
        and "50 %" in cal_errp.resultat.text(),
        f"l'ErrP affiche SA mesure — l'AUC hors-pli — et SON hasard (50 %, pas 33 % ni 17 %) "
        f"({cal_errp.resultat.text()})")
    chk("AUC" in cal_errp.resultat.text() and "sélection" not in cal_errp.resultat.text(),
        f"...sous SON libellé : ce mode n'a aucune cible à retrouver ({cal_errp.resultat.text()})")
    chk("fenêtres" not in cal_errp.details.text() and "classes" not in cal_errp.details.text()
        and "manches" not in cal_errp.details.text(),
        f"...et AUCUN chiffre du MI ni du P300 n'est fabriqué à côté ({cal_errp.details.text()!r})")
    chk("200 essais" in cal_errp.details.text() and "dont 56 erreurs" in cal_errp.details.text(),
        f"...le nombre d'époques ET celui d'ERREURS, qui est la classe minoritaire dont tout "
        f"dépend ({cal_errp.details.text()!r})")
    # « attrape 50% » / « garde 86% » sans espace insécable : c'est la MÊME formulation, au
    # caractère près, que la tuile ErrP de `live_views` — le même taux doit se lire pareil sur les
    # deux écrans qui le montrent, et l'écart typographique avec le « 50 % » de la ligne du dessus
    # est le prix assumé de cet alignement-là.
    chk("attrape 50%" in cal_errp.details.text()
        and "garde 86%" in cal_errp.details.text()
        and "permutation p = 0.010" in cal_errp.details.text(),
        f"...son point de fonctionnement et sa p-value, en DÉTAIL — jamais comme mesure qui "
        f"décide : ces deux taux sont mesurés au seuil qui les a choisis "
        f"({cal_errp.details.text()!r})")
    # ⚠️ L'AUC est ici la mesure qui DÉCIDE : la répéter en détail l'afficherait deux fois, la
    # seconde sous « cible/non-cible » — le vocabulaire du P300, qui n'a aucun sens pour un mode
    # qui n'a ni cible ni non-cible mais des feedbacks corrects et erronés.
    chk("cible/non-cible" not in cal_errp.details.text(),
        f"...et l'AUC n'est PAS répétée sous le libellé d'un autre paradigme "
        f"({cal_errp.details.text()!r})")
    chk(cal_errp.honnetete.text() == errp_calib.HONNETETE
        and "optimiste" in cal_errp.honnetete.text().lower(),
        "et sa phrase d'honnêteté est CELLE DE L'ErrP — celle qui dit que ses deux taux sont "
        "eux-mêmes optimistes, le seuil ayant été choisi sur les scores qui le mesurent")
    chk("40 %" not in cal_errp.honnetete.text()
        and "leave-one-round-out" not in cal_errp.honnetete.text(),
        "...ni celle du MI, ni celle du P300")

    # --- et le QUATRIÈME : le c-VEP, le seul à entraîner DEUX décodeurs ----------------------
    # Il ne mesure ni accuracy par essai (MI), ni sélection (P300), ni AUC (ErrP) : une justesse
    # hors-pli à SIX cibles, donc contre un hasard de 16,7 % — et il en rend DEUX, une par
    # décodeur. Les valeurs sont celles de la séance de référence (2026-07-21, k=2) : eCCA 59,5 %,
    # rCCA 64,9 %, 8 décisions discordantes sur 37, McNemar p = 0,727.
    # ⚠️ Le point de cet écran-ci : les cinq points d'écart entre les deux décodeurs sont du
    # BRUIT, et la page ne doit pas les présenter comme un choix à faire. C'est le `verdict` qui
    # porte le test, et le second décodeur qui reste en DÉTAIL.
    from core.modes import cvep_calib
    cal_cvep = console.calib_pages["cvep"]
    console.show_calibration("cvep")
    cvep_fini = {**state, "calibration": {
        "mode_id": "cvep", "label": "Calibrer le c-VEP", "phase": "fini", "etape": "",
        "classe": "", "instruction": "", "rappel": "", "restant_s": 0.0, "essai": 90,
        "total": 90, "duree_estimee_s": 185.0, "params": {}, "probleme": "",
        "resultat": {"modele": "/tmp/calib/candidat_cvep_model_20260907-101500.npz",
                     "modele_rcca": "/tmp/calib/candidat_cvep_rcca_model_20260907-101500.npz",
                     "nom": "cvep_model_20260907-101500.npz",
                     "enregistrement": "/tmp/calib/candidat_cvep_calib_20260907-101500_n090.npz",
                     "n_essais": 90, "n_cibles": 6, "acc_ecca": 22 / 37, "acc_rcca": 24 / 37,
                     "mcnemar_p": 0.7265625, "n_discordantes": 8, "n_decisions": 37,
                     "hasard": 1 / 6,
                     "verdict": cvep_calib.verdict(24 / 37, {"gagnant": None, "p": 0.7265625,
                                                             "b": 3, "c": 5, "n_discordantes": 8}),
                     "honnetete": cvep_calib.HONNETETE},
        "candidat": {"modele": "/tmp/calib/candidat_cvep_model_20260907-101500.npz"}}}
    console.apply_state(cvep_fini)
    chk(("59.5" in cal_cvep.resultat.text() or "59,5" in cal_cvep.resultat.text())
        and "17 %" in cal_cvep.resultat.text(),
        f"le c-VEP affiche SA mesure — une justesse hors-pli — contre SON hasard (1/6 = 17 %, "
        f"jamais 50 %) ({cal_cvep.resultat.text()})")
    chk("INDISCERNABLES" in cal_cvep.resultat.text()
        and "0.727" in cal_cvep.resultat.text().replace(",", "."),
        f"...et son verdict rend le TEST qui compare les deux décodeurs, avec sa p-value — pas "
        f"l'écart de cinq points, qui est du bruit ({cal_cvep.resultat.text()})")
    chk("fenêtres" not in cal_cvep.details.text() and "manches" not in cal_cvep.details.text()
        and "AUC" not in cal_cvep.details.text(),
        f"...et AUCUN chiffre des trois autres modes n'est fabriqué à côté "
        f"({cal_cvep.details.text()!r})")
    chk("90 essais" in cal_cvep.details.text()
        and "rCCA" in cal_cvep.details.text()
        and "8 décision(s) discordante(s)" in cal_cvep.details.text(),
        f"...le second décodeur reste en DÉTAIL, à côté du nombre de décisions DISCORDANTES — "
        f"c'est LUI qui porte l'information, pas les deux pourcentages pris isolément "
        f"({cal_cvep.details.text()!r})")
    chk(cal_cvep.honnetete.text() == cvep_calib.HONNETETE
        and "16,7" in cal_cvep.honnetete.text() and "46 %" in cal_cvep.honnetete.text(),
        "et sa phrase d'honnêteté est CELLE DU c-VEP — le hasard à six cibles, et le couple "
        "émission/justesse que le moteur produira vraiment")
    console.show_calibration("mi")      # la suite éprouve de nouveau la page du MI

    # 3bis. Après, mais SANS CV honnête mesurable (B2) : `cv_groupee: None` — pas assez d'essais
    # DISTINCTS par classe pour former deux plis, cf. mi_calib.py. C'est le pendant console d'un
    # défaut déjà corrigé côté moteur : `calib_page.py` avait son PROPRE effondrement en 0.0,
    # indépendant de celui du moteur — corrigé, cette page-ci ne doit JAMAIS afficher « 0 % »,
    # un diagnostic (contact des électrodes, immobilité…) qui n'a aucun rapport avec la vraie
    # cause. Elle doit montrer la raison à la place.
    sans_cv = {**mi_state, "calibration": {**en_cours["calibration"], "phase": "fini",
              "etape": "", "classe": "", "instruction": "", "restant_s": 0.0,
              "resultat": {"modele": "/tmp/mi_model_20260731-090000.joblib",
                           "nom": "mi_model_20260731-090000.joblib",
                           "enregistrement": "/tmp/mi_calib_20260731-090000_n06.npz",
                           "n_essais": 6, "n_fenetres": 18, "cv_groupee": None,
                           "cv_naive": 0.50, "hasard": 1 / 3,
                           "classes": ["GAUCHE", "DROITE", "REPOS"],
                           "verdict": "justesse non mesurable : pas assez d'essais distincts "
                                      "par classe pour une validation croisée"}}}
    console.apply_state(sans_cv)
    chk("non mesurable" in cal.resultat.text(),
        f"une CV absente affiche la RAISON en clair, jamais un chiffre inventé "
        f"({cal.resultat.text()})")
    chk("0.0" not in cal.resultat.text() and "0,0" not in cal.resultat.text()
        and "0 %" not in cal.resultat.text(),
        f"et surtout pas « 0 % » — le second effondrement, indépendant de celui du moteur, que "
        f"ce correctif ferme ({cal.resultat.text()})")

    # 4. Abandon : pas de modèle, et la raison.
    annule = {**mi_state, "calibration": {**en_cours["calibration"], "phase": "annule",
              "resultat": None, "probleme": "ValueError : pas assez de données"}}
    console.apply_state(annule)
    chk("pas assez de données" in cal.resultat.text(),
        f"une calibration annulée dit pourquoi ({cal.resultat.text()})")

    cal.bouton_retour.click()
    chk(console.stack.currentWidget() is console.grid,
        "et la page de calibration ramène sur la grille")

    # --- 🔴 L'ORDRE DE LANCEMENT, et la fenêtre de stimulus --------------------------------
    # C'est le piège de tout ce sous-système, et il ne lève aucune exception quand il est faux.
    # La fenêtre attend ~15 s À PARTIR DE SON PROPRE lancement ; le moteur compte sa chauffe À
    # PARTIR DE `start_calibration`. Il n'existe aucune poignée de main entre les deux processus.
    # Dans le mauvais ordre, les premières manches tombent dans la chauffe : elles sont jetées,
    # comptées et dites — mais la séance est PLUS COURTE que ce que l'écran annonce, et c'est
    # indiscernable d'un protocole qui s'est bien passé.
    console.show_calibration("p300")
    cal_p3 = console.stack.currentWidget()
    # Le P300 est ARRÊTÉ dans cet état : le chemin nominal, sans arrêt préalable à attendre. La
    # qualité est la SAINE (cf. plus haut : `state` porte une référence décrochée depuis le test
    # du bandeau), sans quoi le contrôle de liaison refuserait avant même d'arriver au sujet.
    p300_pret = {**state, "calibration": None, "quality": qualite_saine}
    console.apply_state(p300_pret)
    journal.clear()
    processus.clear()
    cal_p3.bouton_commencer.click()
    console.contact.bouton_lancer.click()
    noms = [e[0] for e in journal]
    chk(("commande", "start_calibration") in journal and ("fenetre" in noms),
        f"une calibration P300 soumet la commande ET lance la fenêtre ({journal})")
    chk(0 <= rang(noms, "commande") < rang(noms, "fenetre"),
        f"🔴 et dans CET ordre : `start_calibration` AVANT la fenêtre — sinon les premières "
        f"manches tombent dans la chauffe du moteur ({journal})")

    # La commande de la fenêtre vient de `stimulus/registry.py`, jamais d'une chaîne écrite ici.
    from stimulus import registry as stim_registry
    attendue = stim_registry.commande("p300", calibrer=True)
    lancees = [e[1] for e in journal if e[0] == "fenetre"]
    chk(lancees and list(lancees[0]) == list(attendue),
        f"la ligne de commande est CELLE du registre des stimulus, à l'identique "
        f"({lancees} pour {list(attendue)})")
    chk(lancees and "--calibrer" in lancees[0],
        f"...et elle porte `--calibrer` : c'est la fenêtre en mode CALIBRATION ({lancees})")

    # Deux fenêtres publieraient les mêmes marqueurs sous le même nom, et le moteur mélangerait
    # les deux séances sans rien signaler. Le second lancement est refusé — et le refus se VOIT.
    avant_second = len(processus)
    refus = console.lanceur.lancer("p300", calibrer=True)
    chk(not refus.get("accepted") and len(processus) == avant_second,
        f"une SECONDE fenêtre est refusée, et aucun processus de plus n'est créé ({refus})")
    console.apply_state(p300_pret)
    chk("tourne déjà" in console.banner.fenetre.text(),
        f"...et le refus est AFFICHÉ dans le bandeau, pas seulement rendu à l'appelant "
        f"({console.banner.fenetre.text()[:70]}…)")

    # Une fenêtre qui MEURT anormalement doit le dire. Le silence est le défaut d'origine : le
    # moteur attendrait alors des marqueurs qui ne viendront plus, indiscernable d'un étudiant
    # qui fixe mal.
    fenetre = processus[-1]
    fenetre.sortie = b"ModuleNotFoundError: No module named 'pygame'\n"
    fenetre.readyReadStandardOutput.emit()
    fenetre.finished.emit(1, QProcess.ExitStatus.NormalExit)
    console.apply_state(p300_pret)
    chk("pygame" in console.banner.fenetre.text()
        and "anormalement" in console.banner.fenetre.text(),
        f"une fenêtre morte le DIT à l'écran, avec sa dernière sortie ({console.banner.fenetre.text()})")
    chk(not console.lanceur.en_cours(),
        "...et le lanceur la considère bien terminée : on peut en relancer une")

    # Une fenêtre qu'on tue SOI-MÊME (abandon, fermeture) n'est pas une panne : ne pas crier.
    console.lanceur.lancer("p300", calibrer=True)
    console.lanceur.arreter()
    console.apply_state(p300_pret)
    chk(console.banner.fenetre.text() == "",
        f"une fenêtre arrêtée par la console ne s'annonce pas comme une panne "
        f"({console.banner.fenetre.text()!r})")

    # --- le lanceur contre un VRAI `QProcess` ------------------------------------------------
    # Tout ce qui précède tourne sur un `QProcess` de façade : ça prouve la LOGIQUE du lanceur, et
    # rien du contact avec Qt. Une signature qui changerait (`finished(int, ExitStatus)`, un
    # `readAllStandardOutput` qui rend un `QByteArray`) laisserait ces assertions vertes et
    # n'échouerait qu'en séance — sous la forme exacte du défaut qu'on répare : la fenêtre meurt,
    # et rien ne le dit.
    #
    # ⚠️ Ce n'est PAS un pygame : c'est un `python -c` qui écrit sur stderr et sort en 3, borné par
    # `waitForFinished`. Un smoke qui ouvre une fenêtre plein écran en CI est un smoke qu'on
    # désactive, et le jour où on le désactive on perd tout ce bloc. La commande est détournée le
    # temps de ce test SEULEMENT — en production, `stimulus/registry.py` en reste la seule source,
    # et c'est vérifié plus haut sur la ligne de commande réellement lancée.
    from console import fenetres as mod_fenetres
    vraie_commande = mod_fenetres.stimulus_registry.commande
    try:
        mod_fenetres.stimulus_registry.commande = lambda sid, calibrer=False: [
            sys.executable, "-u", "-c",
            "import sys; sys.stderr.write('BOUM : dépendance absente\\n'); sys.exit(3)"]
        vrai = LanceurFenetre()
        chk(vrai.lancer("p300", calibrer=True).get("accepted"),
            "un VRAI QProcess démarre")
        vrai._proc.waitForFinished(5000)
        app.processEvents()
        chk(not vrai.en_cours(), "...et le lanceur le voit terminé (signal `finished` reçu)")
        chk("code 3" in vrai.probleme and "BOUM" in vrai.probleme,
            f"...avec son code de sortie ET sa dernière ligne de stderr, non tamponnée grâce au "
            f"`-u` du registre ({vrai.probleme})")
        # L'autre mort, celle où `finished` n'arrive JAMAIS : exécutable introuvable. Sans la
        # branche `errorOccurred`, le lanceur resterait « en cours » pour toujours et le bouton
        # redeviendrait silencieux.
        mod_fenetres.stimulus_registry.commande = lambda sid, calibrer=False: [
            "programme-qui-nexiste-pas-12345"]
        introuvable = vrai.lancer("p300")
        app.processEvents()
        chk(not introuvable.get("accepted") and not vrai.en_cours(),
            f"un exécutable introuvable est rendu comme un REFUS, pas comme un succès qui "
            f"n'arrivera jamais ({introuvable})")
        chk("n'a pas DÉMARRÉ" in vrai.probleme,
            f"...et il le dit à l'écran ({vrai.probleme[:60]}…)")
    finally:
        mod_fenetres.stimulus_registry.commande = vraie_commande

    # Une calibration dont la FENÊTRE refuse de s'ouvrir : le moteur attendrait des marqueurs qui
    # ne viendront jamais, en comptant une chauffe qui ne mène nulle part. La console l'annule —
    # mais PAS tout de suite : `start_calibration` vient d'être mise en file, donc
    # `cancel_calibration` soumise dans la foulée s'entendrait dire « aucune calibration en
    # cours », et l'écran annoncerait une annulation qui n'a pas eu lieu, décompte à l'appui.
    journal.clear()
    processus.clear()
    console.apply_state(p300_pret)
    console.lanceur.lancer("p300")                 # une fenêtre occupe déjà la place
    cal_p3.bouton_commencer.click()
    console.contact.bouton_lancer.click()
    chk("tourne déjà" in cal_p3.avis.text() and "annulée" in cal_p3.avis.text(),
        f"une fenêtre indisponible annule la calibration, et le DIT ({cal_p3.avis.text()[:80]}…)")
    chk([e[1] for e in journal if e[0] == "commande"] == ["start_calibration"],
        f"...sans soumettre `cancel_calibration` à un moteur qui n'a encore rien démarré "
        f"({journal})")
    # La séance apparaît : c'est MAINTENANT que l'annulation part, sans un clic de plus.
    en_chauffe = {**p300_pret, "calibration": {
        "mode_id": "p300", "label": "Calibrer le P300", "phase": "chauffe", "etape": "",
        "classe": "", "instruction": "", "rappel": "", "restant_s": 12.0, "essai": 0,
        "total": 12, "duree_estimee_s": 132.0, "params": {}, "resultat": None, "probleme": "",
        "candidat": None}}
    console.apply_state(en_chauffe)
    chk([e[1] for e in journal if e[0] == "commande"]
        == ["start_calibration", "cancel_calibration"],
        f"...mais dès que la séance existe, l'annulation part toute seule ({journal})")
    console.lanceur.arreter()

    # ⚠️ Le mode P300 qui DÉCODE pendant qu'on lance sa calibration : les deux liraient la même
    # file de marqueurs, et le moteur REFUSE (tâche 5). La console arrête donc le mode elle-même —
    # mais `stop_mode` est mis en FILE : soumettre `start_calibration` dans la foulée serait
    # refusé. Elle attend de voir le mode DISPARAÎTRE de l'état.
    journal.clear()
    processus.clear()
    p300_actif = {**p300_state, "calibration": None, "quality": qualite_saine}
    console.apply_state(p300_actif)
    cal_p3.bouton_commencer.click()
    console.contact.bouton_lancer.click()
    chk([e[1] for e in journal if e[0] == "commande"] == ["stop_mode"],
        f"le mode qui décode est ARRÊTÉ d'abord, et rien d'autre n'est soumis ({journal})")
    chk(not processus, f"...et AUCUNE fenêtre n'est lancée tant qu'il décode ({processus})")
    chk("arrêt de" in cal_p3.avis.text(),
        f"...et l'écran dit ce qu'on attend, au lieu de ne rien faire ({cal_p3.avis.text()[:70]}…)")
    # Le mode a rendu la main : la calibration part, dans le bon ordre, sans autre clic.
    console.apply_state(p300_pret)
    noms = [e[0] for e in journal]
    chk([e[1] for e in journal if e[0] == "commande"] == ["stop_mode", "start_calibration"],
        f"dès qu'il a rendu la main, la calibration part toute seule ({journal})")
    chk(0 <= rang(noms, "commande", 1) < rang(noms, "fenetre"),
        f"...et la fenêtre vient encore APRÈS `start_calibration` ({journal})")
    console.lanceur.arreter()

    # ...et si le mode ne s'arrête JAMAIS, on renonce en le DISANT. Sans ce délai, l'écran
    # attendrait en silence — indiscernable d'une chauffe qui démarre.
    journal.clear()
    console.apply_state(p300_actif)
    cal_p3.bouton_commencer.click()
    console.contact.bouton_lancer.click()
    horloge[0] += DELAI_ARRET_S + 1.0
    console.apply_state(p300_actif)          # il décode toujours
    chk("PAS été lancée" in cal_p3.avis.text(),
        f"un mode qui ne s'arrête pas fait renoncer la calibration, à l'écran "
        f"({cal_p3.avis.text()[:80]}…)")
    chk([e[1] for e in journal if e[0] == "commande"] == ["stop_mode"],
        f"...et `start_calibration` n'est JAMAIS soumise ({journal})")

    # « Lancer le stimulus » : la même fenêtre, SANS `--calibrer`, depuis la page du mode.
    journal.clear()
    processus.clear()
    console.show_mode("p300")
    page_p3 = console.pages["p300"]
    chk(page_p3.bouton_stimulus is not None and page_p3.bouton_calibrer is not None,
        "la page du P300 porte « Calibrer » ET « Lancer le stimulus »")
    console.apply_state(p300_pret)
    page_p3.bouton_stimulus.click()
    chk(console.stack.currentWidget() is console.contact,
        "« Lancer le stimulus » passe lui aussi par le contrôle de liaison")
    console.contact.bouton_lancer.click()
    lancees = [e[1] for e in journal if e[0] == "fenetre"]
    chk(lancees and list(lancees[0]) == list(stim_registry.commande("p300")),
        f"...et lance la fenêtre en mode DÉCODAGE, sans --calibrer ({lancees})")
    chk(not [e for e in journal if e[0] == "commande"],
        f"...sans soumettre la moindre commande au moteur : le mode se démarre depuis la grille "
        f"({journal})")
    console.lanceur.arreter()

    # « Annuler » sur le contrôle de liaison ne lance rien et ramène d'où l'on vient.
    journal.clear()
    processus.clear()
    console.apply_state(p300_pret)
    page_p3.bouton_stimulus.click()
    console.contact.bouton_retour.click()
    chk(console.stack.currentWidget() is page_p3 and not journal,
        f"« Annuler » revient sur la page d'origine sans rien lancer ({journal})")

    # Les boutons sont posés par le CONTRAT, pas par une liste écrite ici. Le SSVEP n'a ni
    # calibration ni stimulus ; l'ErrP en déclare une que le moteur ne sait pas encore jouer.
    chk(console.pages["ssvep"].bouton_calibrer is None
        and console.pages["ssvep"].bouton_stimulus is None,
        "un mode sans calibration n'expose aucun de ces deux boutons")
    chk(console.pages["mi"].bouton_calibrer is not None
        and console.pages["mi"].bouton_stimulus is None,
        "le MI se calibre mais n'a AUCUNE fenêtre : le moteur mène seul son protocole")
    errp_calib = (console.pages["errp"].spec.get("calibration") or {})
    chk(console.pages["errp"].bouton_calibrer.isEnabled() == bool(errp_calib.get("jouable")),
        f"et « Calibrer » n'est actif que si le moteur sait JOUER la calibration "
        f"(errp jouable={errp_calib.get('jouable')})")
    chk(bool(console.pages["errp"].bouton_calibrer.toolTip())
        or errp_calib.get("jouable"),
        "...un bouton grisé DIT pourquoi il l'est, il ne se contente pas de ne rien faire")
    console.show_grid()

    # --- régression : les tops de l'ÉCHAUFFEMENT, pas seulement ceux des essais enregistrés ----
    # `essai` (le compteur d'essais ENREGISTRÉS) ne bouge JAMAIS pendant l'échauffement — seule
    # la phase « essais » l'incrémente (core/modes/calibration.py::_pas_essai, `if self.phase ==
    # "essais":`). Et `phase` elle-même reste constante tout du long d'une même phase. Une clé
    # anti-répétition assise sur (phase, essai, etape) — la version précédente de cette page —
    # vaut donc EXACTEMENT la même chose pour les six essais d'échauffement du MI (2 par classe ×
    # 3 classes), quelle que soit la classe tirée : le premier top sonne, les cinq suivants
    # produisent la MÊME clé et ne sonnent JAMAIS. Pas une coïncidence de tirage — une garantie, à
    # chaque séance. Aucun `chk` plus haut ne le voit : la fixture « en_cours » démarre
    # directement en phase « essais ». Celui-ci exerce l'échauffement pour de vrai.
    console.show_calibration("mi")
    cal = console.stack.currentWidget()

    class _BeepsEnregistreur:
        """Remplace `console.beeps` le temps du test : compte les tops RÉELLEMENT déclenchés par
        `_maybe_beep`, sans dépendre d'une vraie sortie audio (présente ou non sur la machine qui
        lance ce smoke)."""

        def __init__(self):
            self.appels = []

        def jouer(self, classe):
            self.appels.append(classe)

    vrais_beeps = console.beeps
    console.beeps = _BeepsEnregistreur()
    try:
        base = {"mode_id": "mi", "label": "Calibration Motor Imagery", "phase": "echauffement",
                "essai": 0, "total": 42, "duree_estimee_s": 400.0,
                "params": {"trials_per_class": 14}, "classes": ["GAUCHE", "DROITE", "REPOS"],
                "resultat": None, "probleme": ""}
        # Six essais d'échauffement (2 par classe × 3 classes) ; classes délibérément PAS toutes
        # distinctes d'un essai au suivant (comme un mélange aléatoire peut en produire) : la clé
        # correcte ne doit dépendre NI de la classe NI d'un compteur qui ne bouge pas ici.
        classes_echauffement = ["GAUCHE", "DROITE", "REPOS", "GAUCHE", "DROITE", "REPOS"]
        for classe in classes_echauffement:
            cue = {**base, "etape": "cue", "classe": classe,
                  "instruction": f"Imagine : {classe}", "rappel": "", "restant_s": 3.0}
            console.apply_state({**mi_state, "calibration": cue})
            # Le MÊME état, rejoué (la page est repeinte ~10 fois par seconde pendant les 3 s du
            # cue) : ça ne doit PAS déclencher un second top pour le même essai.
            console.apply_state({**mi_state, "calibration": cue})
            imagerie = {**base, "etape": "imagerie", "classe": classe,
                       "instruction": "", "rappel": "", "restant_s": 4.0}
            console.apply_state({**mi_state, "calibration": imagerie})
            repos = {**base, "etape": "repos", "classe": "",
                    "instruction": "", "rappel": "", "restant_s": 1.5}
            console.apply_state({**mi_state, "calibration": repos})

        chk(console.beeps.appels == classes_echauffement,
            f"chacun des SIX essais d'échauffement sonne son propre top, pas un seul sur six, "
            f"et sans doublon sur le rafraîchissement répété du même cue ({console.beeps.appels})")
    finally:
        console.beeps = vrais_beeps

    cal.bouton_retour.click()
    chk(console.stack.currentWidget() is console.grid,
        "et la page de calibration ramène sur la grille, après ce test aussi")

    # --- régression : le premier top d'une séance RELANCÉE après un ABANDON (B1) ---------------
    # `cancel()` (core/modes/calibration.py) pose l'étape vide ET la phase terminale dans le MÊME
    # appel : contrairement à la fin NORMALE (qui traverse la phase "entrainement", non
    # terminale, étape vide — capturée par `_maybe_beep` toute seule), il n'existe donc AUCUN état
    # intermédiaire où `en_cours` est vrai avec une étape vide à observer. Sans remise à zéro
    # explicite de `_etape_precedente`, la page (jamais recréée : elle vit tant que la console
    # tourne) reste bloquée sur la dernière étape non vide vue avant l'abandon — ici "cue" — et le
    # tout premier top de la séance SUIVANTE ne sonnerait pas. Silencieusement, sans rapport avec
    # le tirage : l'étudiant relance justement pour de MEILLEURES données après avoir repéré une
    # électrode mal placée pendant la mise en route, et perd le seul repère qui lui évite de LIRE
    # l'instruction à l'écran — la contamination du regard que les tops existent pour empêcher.
    console.show_calibration("mi")
    cal = console.stack.currentWidget()
    console.beeps = _BeepsEnregistreur()
    try:
        base = {"mode_id": "mi", "label": "Calibration Motor Imagery", "phase": "echauffement",
                "essai": 0, "total": 42, "duree_estimee_s": 400.0,
                "params": {"trials_per_class": 14}, "classes": ["GAUCHE", "DROITE", "REPOS"],
                "resultat": None, "probleme": ""}

        # Première séance : elle sonne son premier top, pendant la mise en route (échauffement)
        # — le moment le plus probable pour s'apercevoir d'une électrode mal placée...
        premier_cue = {**base, "etape": "cue", "classe": "GAUCHE",
                       "instruction": "Imagine : GAUCHE", "rappel": "", "restant_s": 3.0}
        console.apply_state({**mi_state, "calibration": premier_cue})
        chk(console.beeps.appels == ["GAUCHE"],
            f"la première séance sonne son premier top normalement ({console.beeps.appels})")

        # ...et qu'on ABANDONNE EN PLEIN dedans : le moteur livre directement l'état terminal,
        # comme `cancel()` le fait réellement — jamais d'étape vide non terminale entre les deux.
        annule = {**base, "phase": "annule", "etape": "", "classe": "",
                 "instruction": "", "rappel": "", "restant_s": 0.0}
        console.apply_state({**mi_state, "calibration": annule})

        # Relance, sur la MÊME page : son tout premier "cue" doit sonner, sans exception.
        console.beeps.appels = []
        cue_relance = {**base, "etape": "cue", "classe": "DROITE",
                       "instruction": "Imagine : DROITE", "rappel": "", "restant_s": 3.0}
        console.apply_state({**mi_state, "calibration": cue_relance})
        chk(console.beeps.appels == ["DROITE"],
            f"et le premier top de la séance RELANCÉE après un abandon sonne aussi — pas muet "
            f"({console.beeps.appels})")
    finally:
        console.beeps = vrais_beeps

    cal.bouton_retour.click()
    chk(console.stack.currentWidget() is console.grid,
        "et la page de calibration ramène sur la grille, après l'abandon aussi")

    # Le formulaire contre un VRAI moteur : c'est le seul moyen de prouver que ce qu'il produit
    # est ce que le moteur attend. Le moteur n'est pas démarré — `submit` valide à la
    # soumission, sans avoir besoin de la boucle.
    moteur = EngineServer(synthetic=True, modes=("raw", "ssvep", "neuro"),
                          instance="console-smoke")
    reelle = Console(moteur)
    reelle.timer.stop()
    page = reelle.pages["ssvep"]
    chk(set(page.formulaire.champs) == {"freqs", "refresh_hz", "alpha_hz"},
        f"le SSVEP expose ses trois réglages ({sorted(page.formulaire.champs)})")
    chk(page.formulaire.champs["freqs"].text().startswith("15"),
        f"pré-rempli avec le défaut du contrat ({page.formulaire.champs['freqs'].text()})")

    # `submit` ne peut valider que sur un mode DÉMARRÉ : on applique la commande à la main,
    # comme la boucle le ferait.
    moteur._start(["raw", "ssvep", "neuro"], {s.id: v for s, v in moteur._pending}, now=0.0)

    page.formulaire.champs["freqs"].setText("12, 15, 20")
    page._appliquer(page.formulaire.values())
    chk(page.formulaire.refus.text() == "",
        f"un jeu valide est accepté ({page.formulaire.refus.text()})")

    page.formulaire.champs["freqs"].setText("15, 60")
    page._appliquer(page.formulaire.values())
    chk("hors bande passante" in page.formulaire.refus.text(),
        f"et un jeu hors bande est refusé AVEC sa raison — « {page.formulaire.refus.text()[:60]}… »")

    page.formulaire.champs["freqs"].setText("15, 15.2")
    page._appliquer(page.formulaire.values())
    chk("trop proches" in page.formulaire.refus.text(),
        "deux cibles trop proches pour la fenêtre : refusées, avec l'écart minimum indiqué")

    page.formulaire.champs["freqs"].setText("quinze, vingt")
    page._appliquer(page.formulaire.values())
    chk("liste de nombres" in page.formulaire.refus.text(),
        "une saisie illisible est refusée par le MOTEUR, pas par le formulaire")

    # Le bouton « Proposer » de bout en bout : clic -> commande au moteur -> champ rempli -> et la
    # valeur obtenue est ACCEPTÉE. C'est ce dernier point qui compte : une proposition que la
    # validation refuse serait le pire des deux mondes. Le bouton est CLIQUÉ, pas contourné en
    # appelant `_proposer` directement — sinon une clé mal capturée par le lambda du bouton, ou un
    # `proposes` sur le mauvais champ, passerait tous les tests sans jamais être exercé.
    page = reelle.pages["ssvep"]
    page.formulaire.champs["freqs"].setText("15, 20, 8.57143")
    page.formulaire.boutons_proposer["refresh_hz"].click()
    propose = page.formulaire.values()["freqs"]
    chk(len(propose) == 3, f"« Proposer » remplit le champ ({propose})")
    chk(all(abs(60.0 / f - round(60.0 / f)) < TOLERANCE_DIVISEUR for f in propose),
        "avec des diviseurs du rafraîchissement déclaré")
    page._appliquer(page.formulaire.values())
    chk(page.formulaire.refus.text() == "",
        f"et le moteur accepte ce qu'il a lui-même proposé ({page.formulaire.refus.text()})")

    # Un avertissement (proposition ACCEPTÉE, mais hors de la plage confortable) ne doit PAS
    # ressembler à un refus. Cas connu : 60 Hz, alpha 10,5 Hz, 5 cibles — le même triplet que le
    # test de non-régression `propose_frequencies` de config.py, qui produit déjà cet avertissement.
    # Seule la LONGUEUR du texte tapé dans « freqs » compte ici (c'est elle qui fixe `n`) : les
    # valeurs elles-mêmes n'ont pas besoin d'être un jeu SSVEP valide, on ne les applique jamais.
    page.formulaire.champs["alpha_hz"].setValue(10.5)
    page.formulaire.champs["freqs"].setText("1, 2, 3, 4, 5")
    page.formulaire.boutons_proposer["refresh_hz"].click()
    chk(len(page.formulaire.values()["freqs"]) == 5,
        f"la proposition avec avertissement remplit quand même le champ "
        f"({page.formulaire.values()['freqs']})")
    chk("hors de la plage confortable" in page.formulaire.avertissement.text(),
        f"l'avertissement est affiché, en ambre — « {page.formulaire.avertissement.text()[:60]}… »")
    chk(page.formulaire.refus.text() == "",
        f"et rien dans l'étiquette de refus ({page.formulaire.refus.text()!r})")

    # Le refus qui ferme le trou, vu depuis l'interface.
    page.formulaire.champs["freqs"].setText("15, 17")
    page._appliquer(page.formulaire.values())
    chk("diviseur entier" in page.formulaire.refus.text(),
        f"17 Hz est refusé avec sa raison ({page.formulaire.refus.text()[:70]}…)")

    # Un réglage BORNÉ par le contrat (le lissage du neuro, 0 à 0.99) : le champ ne doit PAS
    # écrêter la saisie. Un QSpinBox réglé sur les bornes du contrat transformerait « 5 » en
    # « 0.99 » sans un mot, et le moteur n'aurait jamais l'occasion de dire pourquoi 5 est exclu.
    neuro = reelle.pages["neuro"]
    reelle.show_mode("neuro")
    reelle.apply_state(moteur.snapshot())      # comme le ferait le QTimer : la page apprend l'état
    neuro.formulaire.champs["smoothing"].setValue(5.0)
    chk(neuro.formulaire.values()["smoothing"] == 5.0,
        f"une valeur hors bornes SORT du formulaire telle quelle "
        f"({neuro.formulaire.values()['smoothing']}, et non écrêtée à 0.99)")
    neuro._appliquer(neuro.formulaire.values())
    chk(neuro.formulaire.refus.text() != "",
        "et c'est le MOTEUR qui la refuse, avec sa raison")
    chk("en vigueur" in neuro.formulaire.refus.text(),
        f"le refus rappelle ce qui reste appliqué — « {neuro.formulaire.refus.text()[-40:]} »")
    chk(neuro.formulaire.champs["smoothing"].value() == 5.0,
        "et la saisie fautive reste dans le champ, pour être corrigée plutôt que retapée")

    # Le mode « brut » n'a aucun réglage : la page doit le DIRE, pas afficher un cadre vide.
    chk(len(reelle.pages["raw"].formulaire.champs) == 0,
        "le brut n'a aucun réglage")
    chk(reelle.pages["raw"].formulaire.vide is not None
        and reelle.pages["raw"].formulaire.vide.isVisibleTo(reelle.pages["raw"]),
        "et le formulaire l'écrit, au lieu de laisser un cadre vide")

    # --- régression : un « choice » NUMÉRIQUE round-trip son TYPE, contre le VRAI validateur ----
    # Trouvé en écrivant cette page, AVANT tout écran : `trials_per_class` (calibration MI) est le
    # premier « choice » du projet dont le défaut n'est PAS le premier choix (MI_SESSIONS[1] = 14,
    # pas 10) et dont les choix sont des ENTIERS, pas des chemins de fichiers (`model`, le seul
    # autre « choice » existant). `ParamsForm` ne couvrait ni l'un ni l'autre cas : le QComboBox
    # affichait le PREMIER choix (10, pas 14) et `values()` rendait toujours une CHAÎNE ("10"),
    # que `contract.validate` refuse contre (10, 14, 18, 26) — des entiers. Corrigés dans
    # `params_form.py` (`_champ` et `values`) ; vérifié ici contre le VRAI validateur — le moteur
    # FACTICE du bloc « calibration » plus haut n'appelle jamais `contract.validate` et n'aurait
    # rien détecté.
    cal_reelle = reelle.calib_pages["mi"]
    chk(cal_reelle.formulaire.champs["trials_per_class"].currentText() == "14",
        f"le formulaire de calibration affiche le DÉFAUT déclaré (14), pas le premier choix "
        f"({cal_reelle.formulaire.champs['trials_per_class'].currentText()})")
    valeurs_calib = cal_reelle.formulaire.values()
    chk(valeurs_calib["trials_per_class"] == 14
        and isinstance(valeurs_calib["trials_per_class"], int),
        f"et rend un ENTIER, pas '14' — sinon le moteur le refuse comme choix invalide "
        f"({valeurs_calib['trials_per_class']!r})")
    ack_calib = reelle.commande("start_calibration", id="mi", params=valeurs_calib)
    chk(ack_calib.get("accepted"),
        f"soumis au VRAI validateur (pas au moteur factice), ce défaut est accepté ({ack_calib})")

    # Les tracés, contre un vrai tampon. `recent_window` rend une COPIE : la modifier ne doit
    # rien changer au moteur — c'est ce qui protège l'acquisition du fil Qt.
    import numpy as np

    moteur_channels = ["Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8"]
    moteur.recent = np.random.default_rng(0).normal(0.0, 20.0, (1000, 8))
    bloc = moteur.recent_window(2.0)
    chk(bloc is not None and bloc.shape == (500, 8),
        f"recent_window rend 2 s de signal ({None if bloc is None else bloc.shape})")
    bloc[0, 0] = 999999.0
    chk(moteur.recent[-500, 0] != 999999.0,
        "et c'est une COPIE : l'afficheur ne peut pas abîmer le tampon d'acquisition")

    page = reelle.pages["raw"]
    page.update_from({"modes_state": {"raw": {
        "id": "raw", "label": "Brut", "family": "brut", "phase": "running", "published": True,
        "params": {}, "instruction": "", "stream": "raw", "channels": list(moteur_channels),
        "rest_report": None, "output": None}}})
    chk(len(page.vue.courbes) == 8, f"huit courbes, une par voie ({len(page.vue.courbes)})")
    chk(page.vue.courbes[0].xData is not None and len(page.vue.courbes[0].xData) > 100,
        "et elles portent des données après un rafraîchissement")

    # Moteur pas encore démarré : rien ne doit lever.
    console.apply_state({"running": False, "board": "unicorn", "fs_hz": 250.0,
                         "modes": [], "quality": None, "catalog": []})
    chk("attente" in console.banner.sigmas.text(),
        f"un état vide est encaissé — « {console.banner.sigmas.text()} »")

    # `refresh()` est la SEULE ligne qui touche le moteur : assurer qu'elle fonctionne.
    console.refresh()
    chk(moteur_faux.appels == 1,
        f"refresh() a consulté le moteur (appels={moteur_faux.appels})")

    # --- la FERMETURE : ce que la console a ouvert, elle le referme ------------------------
    # `EngineServer.close()` supprime le dossier temporaire des candidats de calibration. Sans cet
    # appel, un modèle EEG d'une personne identifiable survit à la fermeture dans `%TEMP%` — et
    # le premier remaniement qui le déplacerait le ferait ÉLIRE comme « modèle le plus récent ».
    console.apply_state(p300_pret)
    console.lanceur.lancer("p300", calibrer=True)
    fenetre_ouverte = processus[-1]
    console.close()
    chk(moteur_faux.fermetures == 1,
        f"fermer la console appelle `EngineServer.close()` ({moteur_faux.fermetures})")
    chk(fenetre_ouverte.tue and not console.lanceur.en_cours(),
        "...et tue la fenêtre de stimulus restée ouverte, plutôt que de la laisser plein écran "
        "devant l'étudiant")

    app.processEvents()
    print(f"[console-smoke] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def run(args):
    modes = [m.strip() for m in (args.mode or "").split(",") if m.strip()]
    if not args.no_raw:
        modes.insert(0, "raw")
    # `EngineServer` valide les modes demandés dans son constructeur et lève un `ValueError`
    # déjà rédigé pour être lu (cf. core/server.py) — sans modèle MI entraîné, par exemple,
    # c'est le refus normal d'un poste fraîchement cloné, pas un plantage. Un traceback autour
    # n'ajouterait rien et enterrait ce message sous la pile : on l'attrape ici, comme le fait
    # déjà `core/server.py` pour le même appel lancé sans interface.
    try:
        engine = EngineServer(serial=args.serial, synthetic=args.synthetic, verbose=args.verbose,
                              modes=modes, instance=args.instance)
    except ValueError as refus:
        print(f"[console] {refus}")
        sys.exit(2)

    # Le moteur tourne dans SON fil et possède seul la session BrainFlow. Le fil Qt ne fait que
    # lire `snapshot()` et poser des commandes en file.
    thread = threading.Thread(
        target=engine.run,
        kwargs={"baseline_s": args.baseline, "warmup_s": args.warmup}, daemon=True)
    thread.start()

    try:
        app = QApplication([])
        console = Console(engine)
        console.show()
        app.exec()
    finally:
        # Ctrl+C ou fermeture de la fenêtre doivent fermer PROPREMENT la session BrainFlow :
        # une session laissée ouverte empêche la suivante de s'ouvrir (BOARD_NOT_READY).
        engine.stop()
        thread.join(timeout=5.0)


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if _smoke() else 1) if _ARGS.smoke else run(_ARGS)
