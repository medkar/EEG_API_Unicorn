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
        self.stack.addWidget(self.grid)

        self.pages = {}
        for spec in registry.catalog():
            if spec["status"] != "moteur":
                continue          # pas de page pour un mode que le moteur ne sait pas faire
            page = ModePage(spec, self)
            page.retour.connect(self.show_grid)
            self.pages[spec["id"]] = page
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

    def show_mode(self, mode_id):
        page = self.pages.get(mode_id)
        if page is not None:
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
    chk(len(externes) == 4, f"{len(externes)} tuiles pour les modes de l'appli pygame")
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
    engine = EngineServer(serial=args.serial, synthetic=args.synthetic, verbose=args.verbose,
                          modes=modes, instance=args.instance)

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
