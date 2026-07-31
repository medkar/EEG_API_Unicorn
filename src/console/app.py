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

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import (QApplication, QMainWindow, QStackedWidget,  # noqa: E402
                               QVBoxLayout, QWidget)

from console.banner import Banner  # noqa: E402
from console.beeps import Beeps  # noqa: E402
from console.calib_page import CalibPage  # noqa: E402
from console.grid import ModeGrid  # noqa: E402
from console.mode_page import ModePage  # noqa: E402
from console import live_views  # noqa: E402
from core.config import TOLERANCE_DIVISEUR, use_utf8_console  # noqa: E402
from core.modes import registry  # noqa: E402
from core.server import EngineServer  # noqa: E402

REFRESH_MS = 100    # ~10 Hz : le moteur décide à 5 Hz, sonder plus vite ne montrerait rien de plus


class Console(QMainWindow):
    """La fenêtre. Elle ne fait que deux choses : lire un état, envoyer des commandes."""

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("EEG_API_Unicorn — console d'expérimentation")
        self.resize(1100, 720)

        self.banner = Banner()
        self.stack = QStackedWidget()
        self.grid = ModeGrid(registry.catalog())
        self.grid.ouvrir.connect(self.show_mode)
        self.grid.publier.connect(self._publier)
        self.grid.demarrer.connect(self._demarrer)
        self.stack.addWidget(self.grid)

        self.pages = {}
        for spec in registry.catalog():
            if spec["status"] != "moteur":
                continue          # pas de page pour un mode que le moteur ne sait pas faire
            page = ModePage(spec, self)
            page.retour.connect(self.show_grid)
            self.pages[spec["id"]] = page
            self.stack.addWidget(page)

        # Une page de calibration par mode qui se calibre DEPUIS la console. Les autres (c-VEP,
        # P300 : stimulus verrouillé à la frame) n'en ont pas — leur contrat le dit, et le moteur
        # refuserait la commande de toute façon.
        self.beeps = Beeps()
        self.calib_pages = {}
        for spec in registry.catalog():
            calib = spec.get("calibration") or {}
            if calib.get("kind") != "console" or spec["status"] != "moteur":
                continue
            page = CalibPage(spec, self)
            page.retour.connect(self.show_grid)
            self.calib_pages[spec["id"]] = page
            self.stack.addWidget(page)

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
        self.banner.update_from(state)
        self.grid.update_from(state)
        page = self.stack.currentWidget()
        if page is not self.grid:
            page.update_from(state)

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

        def __init__(self):
            self.appels = 0
            self.commandes = []

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
            return {"accepted": True}

        def recent_window(self, seconds):
            """Un moteur factice n'a pas de tampon d'acquisition. La TracesView demande cette
            méthode, mais sur le faux moteur elle rend None. Le vrai tracé est éprouvé plus bas
            contre un vrai EngineServer."""
            return None

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    app = QApplication.instance() or QApplication([])
    moteur_faux = _FauxMoteur()
    console = Console(moteur_faux)
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

    # Les modes que le moteur ne sait pas faire sont MONTRÉS, grisés, avec leur raison.
    externes = [t for t in console.grid.tuiles.values() if t.spec["status"] != "moteur"]
    chk(len(externes) == 3, f"{len(externes)} tuiles pour les modes de l'appli pygame")
    chk(all(not t.isEnabled() and t.detail.text() for t in externes),
        "chacune est grisée ET dit pourquoi elle ne démarre pas")

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

    # Démarrer / arrêter de bout en bout : clic -> signal de la tuile -> signal de la grille ->
    # commande au moteur. Le bouton est CLIQUÉ, pas contourné : c'est la seule façon de prouver
    # que le lambda capture le bon identifiant et le bon sens.
    moteur_faux.commandes.clear()
    console.grid.tuiles["neuro"].demarrage.click()      # neuro est arrêté dans l'état factice
    chk(("start_mode", {"id": "neuro"}) in moteur_faux.commandes,
        f"un mode arrêté se DÉMARRE depuis sa tuile ({moteur_faux.commandes})")
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

    # --- la page de calibration -------------------------------------------------
    # Elle est éprouvée sur des états FABRIQUÉS, phase par phase : c'est le seul moyen de
    # vérifier chaque écran sans jouer sept minutes de séance.
    console.show_calibration("mi")
    cal = console.stack.currentWidget()
    chk(cal is console.calib_pages["mi"], "« Calibrer » ouvre la page de calibration du MI")
    chk(len(console.calib_pages) == 1,
        f"et seul le MI en a une — le c-VEP et le P300 ont un stimulus natif "
        f"({sorted(console.calib_pages)})")

    # 1. Avant : le briefing du CONTRAT, pas un texte recopié dans l'interface.
    console.apply_state({**mi_state, "calibration": None})
    from core.modes import mi_calib
    chk(mi_calib.BRIEFING[0] in cal.briefing.text(),
        "le briefing affiché vient du contrat du mode")
    chk(cal.bouton_commencer.isEnabled(), "et « Commencer » est actif")

    moteur_faux.commandes.clear()
    cal.bouton_commencer.click()
    envoyees = [c for c in moteur_faux.commandes if c[0] == "start_calibration"]
    chk(envoyees and envoyees[0][1]["id"] == "mi"
        and "trials_per_class" in envoyees[0][1]["params"],
        f"cliquer « Commencer » soumet start_calibration avec la durée choisie ({envoyees})")

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
    chk("7" in cal.progression.text() and "42" in cal.progression.text(),
        f"et la progression nomme les deux nombres ({cal.progression.text()})")
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
                         "verdict": "FAIBLE — ré-essaie"}}}
    console.apply_state(fini)
    chk("40.1" in cal.resultat.text() or "40,1" in cal.resultat.text(),
        f"l'accuracy affichée est l'HONNÊTE ({cal.resultat.text()})")
    chk("55.6" not in cal.resultat.text() and "55,6" not in cal.resultat.text(),
        f"et JAMAIS la naïve, qui est gonflée de 10 à 16 points ({cal.resultat.text()})")
    chk("33" in cal.resultat.text(),
        f"le niveau du hasard est à côté — sans lui, 40 % ne veut rien dire ({cal.resultat.text()})")
    chk("mi_model_20260730-141205.joblib" in cal.details.text(),
        f"le nom du modèle produit est donné ({cal.details.text()})")
    chk("séance de référence" in cal.honnetete.text(),
        "et la page dit franchement ce qu'un résultat modeste signifie")

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
