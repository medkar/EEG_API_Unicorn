"""La page d'un mode : des blocs NUMÉROTÉS, dans l'ordre où on les fait, et rien d'autre.

    ← Modes   SSVEP — quelle cible clignotante l'utilisateur regarde          arrêté

    ┌ 1. Régler ──────────────────────────┐   tous les modes
    ┌ 2. Entraîner ───────────────────────┐   si le contrat déclare une calibration
    ┌ 3. Tester ──────────────────────────┐   si le contrat déclare un `test_id`
    ☐ Décodage en direct                       replié : la vue en direct, toujours à jour

    …ou, pour un mode sans vérité-terrain (le Neuro, le Brut) :

    ┌ 1. Régler ──────────────────────────┐
    ┌ 2. Observer ────────────────────────┐   la vue en direct, en face ; aucun score

🔴 **Pourquoi cette forme (séance casque du 2026-09-22).** L'ancienne page mettait « Démarrer »,
« Calibrer » et « Lancer le stimulus » à plat, comme trois gestes de même rang. Il existe pourtant
un ORDRE, et en sauter un rend les autres inutiles sans que rien ne le dise : le stimulus a été
lancé sur un mode arrêté, et dix minutes de fixation se sont perdues dans le vide. La boucle réelle
est « régler → tester → ajuster → re-tester » ; « Tester » possède sa séquence entière (la mesure,
le contrôle de liaison, la fenêtre, le verdict), donc il n'y a plus d'ordre à respecter.

Ce qui a QUITTÉ la page — « Démarrer/Arrêter », « Lancer le stimulus », « Journal de séance »,
« Brancher un client » — reviendra avec « Connecter », le second chantier. La machinerie de la
`Console` qui les servait (`demander_stimulus`, le journal de `_lancer_fenetre`, les boutons des
tuiles de la grille) reste en place.

Rien ici ne sait qu'un SSVEP a des fréquences ou qu'un MI s'entraîne : c'est le CONTRAT qui le dit
(`calibration`, `test_id`), et le moteur qui déclare quelle mesure sait remplir quel réglage.
"""

import os
import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from console import PHASES_FR, live_views  # noqa: E402
from console.params_form import ParamsForm  # noqa: E402
from core.modes import registry  # noqa: E402

GRIS = "color: #8a8f9c; font-size: 11px;"


def _phrase(texte):
    """Une ligne d'explication sous un geste : courte, grise. Pas un mur de texte."""
    etiquette = QLabel(texte)
    etiquette.setWordWrap(True)
    etiquette.setStyleSheet(GRIS)
    return etiquette


class ModePage(QWidget):
    """Une page par mode, construite une fois, mise à jour à chaque rafraîchissement."""

    retour = Signal()
    marche = Signal(str, bool)      # (id, on) — exactement le signal de la tuile de la grille

    def __init__(self, spec, console):
        super().__init__()
        self.spec = spec
        self.console = console
        self.mode_id = spec["id"]
        self._derniers_params = None
        self._arrete = True

        # --- l'en-tête : où l'on est, et rien d'autre ------------------------------------------
        entete = QHBoxLayout()
        self.bouton_retour = QPushButton("← Modes")
        self.bouton_retour.clicked.connect(self.retour)
        entete.addWidget(self.bouton_retour)
        entete.addWidget(QLabel(f"<b>{spec['label']}</b> — {spec['summary']}"))
        entete.addStretch(1)
        self.etat = QLabel("")
        self.etat.setStyleSheet(GRIS)
        entete.addWidget(self.etat)

        # --- 1. Régler ---------------------------------------------------------------------------
        self.formulaire = ParamsForm(spec["params"])
        self.formulaire.appliquer.connect(self._appliquer)
        self.formulaire.proposer.connect(self._proposer)
        # « Mesurer » à côté d'un champ, quand le MOTEUR déclare une mesure qui sait le remplir (le
        # pic alpha, pour le SSVEP). Même page de mesure que « Vérifier le casque » sur l'accueil :
        # deux portes, un seul runtime. La page ne nomme aucune mesure — elle demande.
        self.boutons_mesurer = {}
        for param in spec["params"]:
            mesure_id = console.mesure_qui_remplit(self.mode_id, param["key"])
            if mesure_id is None:
                continue
            bouton = QPushButton("Mesurer")
            bouton.setToolTip(f"Mesure cette valeur sur toi : « "
                              f"{console.mesures[mesure_id]['label']} », puis « Appliquer » la "
                              f"renvoie dans ce champ.")
            bouton.clicked.connect(
                lambda _c=False, m=mesure_id: console.show_mesure(m, depuis=self))
            self.formulaire.ajouter_a_cote(param["key"], bouton)
            self.boutons_mesurer[param["key"]] = bouton

        numero = 1
        self.bloc_regler = QGroupBox(f"{numero}. Régler")
        QVBoxLayout(self.bloc_regler).addWidget(self.formulaire)
        blocs = [self.bloc_regler]

        # --- 2. Entraîner (si le contrat déclare une calibration) --------------------------------
        # ⚠️ Le critère d'activation est `jouable` — le moteur a-t-il un runtime pour cette
        # calibration — et non `kind` (qui dit seulement QUI mène le protocole). Le critère
        # précédent désignait une valeur que le contrat n'a plus : le bouton avait DISPARU de tous
        # les modes, MI compris, et aucun test ne l'a vu parce que le smoke ne cliquait jamais.
        calib = spec.get("calibration") or {}
        self.bloc_entrainer = self.bouton_entrainer = None
        if calib:
            numero += 1
            self.bloc_entrainer = QGroupBox(f"{numero}. Entraîner")
            self.bouton_entrainer = QPushButton("Entraîner")
            self.bouton_entrainer.clicked.connect(lambda: console.show_calibration(self.mode_id))
            if not calib.get("jouable"):
                # Déclarée mais pas livrée : le bouton reste VISIBLE — c'est ainsi qu'on apprend
                # que ce mode s'entraîne — mais grisé, et il DIT pourquoi.
                self.bouton_entrainer.setEnabled(False)
                self.bouton_entrainer.setToolTip(
                    f"L'entraînement de « {spec['label']} » est déclaré mais le moteur ne sait "
                    f"pas encore le jouer.")
            dedans = QVBoxLayout(self.bloc_entrainer)
            dedans.addWidget(_phrase("Produit un modèle à partir d'une séance guidée. Tu vois "
                                     "son score AVANT de décider de le garder."))
            dedans.addWidget(self.bouton_entrainer)
            blocs.append(self.bloc_entrainer)

        # --- 3. Tester (si le contrat déclare un `test_id`) --------------------------------------
        # UN bouton, qui ouvre la page de la mesure désignée : elle porte déjà le briefing,
        # « Commencer », le contrôle de liaison, la fenêtre et le verdict. La recopier ici serait
        # un second écran de protocole à tenir d'accord avec le premier.
        test_id = spec.get("test_id") or ""
        self.bloc_tester = self.bouton_tester = None
        if test_id:
            numero += 1
            self.bloc_tester = QGroupBox(f"{numero}. Tester")
            self.bouton_tester = QPushButton("Tester")
            self.bouton_tester.clicked.connect(self._tester)
            if not (console.mesures.get(test_id) or {}).get("jouable"):
                self.bouton_tester.setEnabled(False)
                self.bouton_tester.setToolTip(
                    f"Le test de « {spec['label']} » est déclaré mais le moteur ne sait pas "
                    f"encore le jouer.")
            dedans = QVBoxLayout(self.bloc_tester)
            dedans.addWidget(_phrase("Une séance courte, sur TES réglages : on te dit quoi faire, "
                                     "le décodage répond, on compare. Rend un score et son "
                                     "niveau de hasard ; n'écrit rien."))
            dedans.addWidget(self.bouton_tester)
            blocs.append(self.bloc_tester)

        # --- la vue en direct : en face (Observer) ou repliée ------------------------------------
        self.vue = live_views.build(spec["family"], spec["channels"])
        if hasattr(self.vue, "set_source") and console.engine is not None:
            # L'accesseur PUBLIC du moteur, qui rend une copie. Jamais `engine.recent`.
            self.vue.set_source(console.engine.recent_window)
        self.vue.setMinimumHeight(200)

        self.bloc_observer = self.bouton_observer = None
        self.direct = self.pli_direct = None
        if not calib and not test_id:
            # Aucune vérité-terrain (le Neuro, le Brut) : rien à entraîner, rien à noter. On
            # REGARDE, et on n'annonce aucun chiffre de justesse — il n'y a pas de bonne réponse.
            numero += 1
            self.bloc_observer = QGroupBox(f"{numero}. Observer")
            dedans = QVBoxLayout(self.bloc_observer)
            # Le bouton n'existe que si la vue a BESOIN que le mode tourne. Le Brut lit le tampon
            # d'acquisition (`set_source`), pas la sortie de son mode : il n'y a rien à démarrer
            # pour le regarder. Le libellé vient de l'ÉTAT REÇU (`_marche`), jamais d'une bascule
            # tenue ici, qui se désynchroniserait au premier refus du moteur.
            if not hasattr(self.vue, "set_source"):
                self.bouton_observer = QPushButton("Observer")
                self.bouton_observer.clicked.connect(
                    lambda: self.marche.emit(self.mode_id, self._arrete))
                haut = QHBoxLayout()
                haut.addWidget(self.bouton_observer)
                haut.addStretch(1)
                dedans.addLayout(haut)
            dedans.addWidget(self.vue, 1)
            blocs.append(self.bloc_observer)
        else:
            # ⚠️ REPLIÉE, pas supprimée : elle sert à regarder un décodage lancé depuis la grille,
            # et reviendra en face avec « Connecter ». Cachée SANS case pour l'ouvrir, elle serait
            # un widget testé que personne ne peut voir — le motif que ce dépôt traque.
            self.direct = QCheckBox("Décodage en direct")
            self.direct.setToolTip("Ce que le décodage continu rend en ce moment, s'il tourne.")
            self.pli_direct = QWidget()
            pli = QVBoxLayout(self.pli_direct)
            pli.setContentsMargins(0, 0, 0, 0)
            pli.addWidget(_phrase("Vide tant que le décodage continu ne tourne pas : il se "
                                  "démarre depuis la tuile du mode, sur l'accueil."))
            pli.addWidget(self.vue, 1)
            self.pli_direct.setVisible(False)
            self.direct.toggled.connect(self.pli_direct.setVisible)

        # ⚠️ Le corps DÉFILE (2026-09-10) : sans ça, une page plus haute que la fenêtre est
        # TRONQUÉE — Qt écrase les blocs du bas, il ne les rend pas défilables (constat 1.10 de la
        # recette). L'en-tête, lui, reste FIXE : « ← Modes » doit rester atteignable du bas.
        corps = QWidget()
        dedans = QVBoxLayout(corps)
        dedans.setContentsMargins(0, 0, 0, 0)
        for bloc in blocs:
            dedans.addWidget(bloc, 1 if bloc is self.bloc_observer else 0)
        if self.direct is not None:
            dedans.addWidget(self.direct)
            dedans.addWidget(self.pli_direct, 1)
            dedans.addStretch(1)       # repliée, la vue ne prend rien : les blocs restent en haut

        self.defilement = QScrollArea()
        self.defilement.setWidget(corps)
        self.defilement.setWidgetResizable(True)     # sinon le corps garde sa taille d'origine
        self.defilement.setFrameShape(QScrollArea.NoFrame)

        layout = QVBoxLayout(self)
        layout.addLayout(entete)
        layout.addWidget(self.defilement, 1)

    def _tester(self):
        """« Tester » teste CE QUI EST À L'ÉCRAN, et pas ce qui avait été appliqué avant.

        ⚠️ Relevé par l'auteur de cette page, à la livraison (2026-09-22) : sans ce premier geste,
        on change une fréquence, on clique « Tester » sans passer par « Appliquer », et c'est
        l'ANCIENNE configuration qui est testée — sans que rien ne le dise. Dans la boucle
        régler → tester → ajuster, c'est le piège exact. Le formulaire part donc d'abord au moteur
        comme par « Appliquer » ; s'il est refusé (17 Hz ne divise pas 60), le refus s'affiche
        dans « Régler » et le test n'est PAS ouvert — tester une configuration impossible ne
        mesurerait rien.
        """
        ack = self.console.commande("set_params", id=self.mode_id,
                                    params=self.formulaire.values())
        if not ack.get("accepted"):
            self.formulaire.show_refus(ack.get("reason", ""))
            return
        self.formulaire.show_refus("")
        # Les valeurs VALIDÉES par le moteur, pour pré-remplir le test tout de suite : l'état
        # sondé n'aura rattrapé ce réglage qu'au prochain tour de `QTimer`.
        self.console.show_mesure(self.spec["test_id"], depuis=self,
                                 reglages=ack.get("params"))

    def _appliquer(self, values):
        """Envoie les réglages. Le moteur accepte ou refuse ; on affiche ce qu'il dit.

        ⚠️ Appliquer un réglage que le DÉCODEUR lit — les fréquences, par exemple — relance le
        repos de ce mode et recrée son flux. C'est obligatoire, pas prudent : un plancher mesuré
        sous d'autres réglages est faux, et pour le SSVEP il est mesuré PAR FRÉQUENCE. Les clients
        doivent alors se réabonner. Les réglages qui ne servent qu'à proposer ou à valider — le
        rafraîchissement de l'écran, le pic alpha — ne coûtent rien de tout ça : c'est le contrat
        qui le déclare, et le moteur qui en décide.
        """
        ack = self.console.commande("set_params", id=self.mode_id, params=values)
        if ack.get("accepted"):
            self.formulaire.show_refus("")
            # Accepté sur un mode ARRÊTÉ : validé et retenu. En VERT, pas en orange (retour de
            # séance du 2026-09-22) — il n'y a aucune réserve à émettre, c'est un succès. La
            # nuance « pas encore en vigueur » est un fait de CALENDRIER, et elle est dans le
            # texte ; la couleur ne répond qu'à « est-ce accepté ». L'orange le faisait lire
            # comme un problème, alors que `mesure_page.py` disait déjà vert pour le même fait.
            self.formulaire.show_confirmation(
                "réglage RETENU : « " + self.spec["label"] + " » est arrêté, il démarrera avec."
                if ack.get("differe") else "")
            return
        # Un refus laisse la saisie fautive dans le champ — on la corrige plutôt qu'on la retape.
        # Mais il DIT ce qui reste en vigueur : sans ça, un champ rouge oublié finit par se lire
        # comme l'état du moteur, et l'étudiant croit décoder sur des réglages jamais appliqués.
        vigueur = self._derniers_params or {}
        rappel = ("  ·  en vigueur : " + ", ".join(f"{c} = {v}" for c, v in vigueur.items())
                  if vigueur else "")
        self.formulaire.show_refus(ack.get("reason", "") + rappel)

    def _proposer(self, cle):
        """Demande une proposition au MOTEUR et la met dans le champ. La console ne calcule rien.

        Envoie ce que le formulaire contient EN CE MOMENT (`params`) : sans ça, la proposition se
        calcule sur les réglages STOCKÉS plutôt que sur ce que l'étudiant est en train d'éditer —
        déclarer un nouvel écran ne servirait à rien tant qu'il n'a pas cliqué « Appliquer ».

        Le refus et l'avertissement sont deux étiquettes distinctes : un avertissement dit qu'un
        réglage a été ACCEPTÉ, avec réserve ; un refus dit qu'il ne l'a PAS été. Les confondre
        ferait passer un succès pour une panne.
        """
        ack = self.console.commande("propose_params", id=self.mode_id, key=cle,
                                    params=self.formulaire.values())
        if not ack.get("accepted"):
            self.formulaire.show_refus(ack.get("reason", ""))
            return
        # Un accusé incomplet (clé ou valeur absente) ne doit pas planter l'interface en séance :
        # on ne remplit rien plutôt que de lever, comme `_appliquer` le fait déjà pour son refus.
        cle_recue, valeur_recue = ack.get("key"), ack.get("value")
        if cle_recue is not None and valeur_recue is not None:
            self.formulaire.remplir(cle_recue, valeur_recue)
        self.formulaire.show_avertissement(ack.get("warning", ""))

    def update_from(self, state):
        mode_state = (state.get("modes_state") or {}).get(self.mode_id)
        self._marche(mode_state is not None)
        if mode_state is None:
            self.etat.setText("arrêté")
            self.vue.update_from(None)
            # ⚠️ Les RÉGLAGES RETENUS se montrent (2026-09-21). `modes_state` ne contient que
            # les modes actifs : sans cette branche, un réglage posé sur un mode arrêté était
            # accepté par le moteur, retenu, appliqué au démarrage — et INVISIBLE, le champ
            # gardant l'ancienne valeur. L'écran disait alors le contraire de la vérité, ce qui
            # est pire qu'un refus franc. Vu en séance : « mon pic alpha n'a pas été reporté ».
            retenus = (state.get("reglages") or {}).get(self.mode_id)
            if retenus and retenus != self._derniers_params:
                self._derniers_params = dict(retenus)
                self.formulaire.set_values(retenus)
            elif not retenus:
                self._derniers_params = None   # forcer la régénération au redémarrage
            return
        libelle = PHASES_FR
        self.etat.setText(libelle.get(mode_state["phase"], mode_state["phase"])
                          + ("" if mode_state["published"] else " · non publié"))
        self.vue.update_from(mode_state)
        params = mode_state.get("params") or {}
        if params != self._derniers_params:
            self._derniers_params = dict(params)
            self.formulaire.set_values(params)

    def _marche(self, tourne):
        """Le libellé de « Observer » vient de l'ÉTAT REÇU, jamais d'une bascule tenue ici.

        Même discipline que la tuile de la grille, et pour la même raison : une bascule locale se
        désynchronise au premier refus du moteur, et l'écran finit par proposer « Arrêter » sur un
        mode qui n'a jamais démarré.
        """
        self._arrete = not tourne
        if self.bouton_observer is not None:
            self.bouton_observer.setText("Observer" if self._arrete else "Arrêter")

    def rafraichir_choix(self):
        """Recharge les listes de choix DYNAMIQUES de ce mode (les modèles entraînés).

        Appelée sur ÉVÉNEMENT — à l'entrée dans la page (cf. `Console.show_mode`) — jamais dans le
        rafraîchissement périodique : résoudre ces choix lit le disque, et le faire dix fois par
        seconde a déjà coûté 30 % d'un cœur à ce projet. Revenir d'une calibration ramène sur la
        GRILLE, pas sur cette page : rouvrir le mode ensuite retombe dans ce même événement, donc
        un modèle fraîchement entraîné apparaît quand même dès la prochaine entrée.
        """
        spec = registry.get(self.mode_id)
        if spec is None:
            return
        for param in spec.params:
            if param.choices_fn is not None:
                self.formulaire.set_choices(param.key, param.choices_now())
