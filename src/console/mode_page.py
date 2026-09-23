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
from console import live_views, nom_phase  # noqa: E402
from console.params_form import ParamsForm  # noqa: E402
from core.i18n import tr  # noqa: E402
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
        self.bouton_retour = QPushButton(tr("console.nav.retour_modes"))
        self.bouton_retour.clicked.connect(self.retour)
        entete.addWidget(self.bouton_retour)
        entete.addWidget(QLabel(tr("console.mode.entete", mode=spec["label"],
                                   resume=spec["summary"])))
        entete.addStretch(1)
        # L'état du décodage (« arrêté », « décode »…). Placé UNE fois, plus bas, selon la page :
        # en tête quand la page l'observe, dans le repli « Décodage en direct » sinon.
        self.etat = QLabel("")
        self.etat.setStyleSheet(GRIS)

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
            bouton = QPushButton(tr("console.mode.mesurer"))
            bouton.setToolTip(tr("console.mode.mesurer_aide",
                                 mesure=console.mesures[mesure_id]["label"]))
            bouton.clicked.connect(lambda _c=False, m=mesure_id: self._mesurer(m))
            self.formulaire.ajouter_a_cote(param["key"], bouton)
            self.boutons_mesurer[param["key"]] = bouton

        numero = 1
        self.bloc_regler = QGroupBox(tr("console.mode.bloc_regler", n=numero))
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
            self.bloc_entrainer = QGroupBox(tr("console.mode.bloc_entrainer", n=numero))
            self.bouton_entrainer = QPushButton(tr("console.mode.entrainer"))
            self.bouton_entrainer.clicked.connect(lambda: console.show_calibration(self.mode_id))
            if not calib.get("jouable"):
                # Déclarée mais pas livrée : le bouton reste VISIBLE — c'est ainsi qu'on apprend
                # que ce mode s'entraîne — mais grisé, et il DIT pourquoi.
                self.bouton_entrainer.setEnabled(False)
                self.bouton_entrainer.setToolTip(
                    tr("console.mode.entrainer_pas_livre", mode=spec["label"]))
            dedans = QVBoxLayout(self.bloc_entrainer)
            dedans.addWidget(_phrase(tr("console.mode.entrainer_phrase")))
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
            self.bloc_tester = QGroupBox(tr("console.mode.bloc_tester", n=numero))
            self.bouton_tester = QPushButton(tr("console.mode.tester"))
            self.bouton_tester.clicked.connect(self._tester)
            if not (console.mesures.get(test_id) or {}).get("jouable"):
                self.bouton_tester.setEnabled(False)
                self.bouton_tester.setToolTip(
                    tr("console.mode.tester_pas_livre", mode=spec["label"]))
            dedans = QVBoxLayout(self.bloc_tester)
            dedans.addWidget(_phrase(tr("console.mode.tester_phrase")))
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
            self.bloc_observer = QGroupBox(tr("console.mode.bloc_observer", n=numero))
            dedans = QVBoxLayout(self.bloc_observer)
            # Le bouton n'existe que si la vue a BESOIN que le mode tourne. Le Brut lit le tampon
            # d'acquisition (`set_source`), pas la sortie de son mode : il n'y a rien à démarrer
            # pour le regarder. Le libellé vient de l'ÉTAT REÇU (`_marche`), jamais d'une bascule
            # tenue ici, qui se désynchroniserait au premier refus du moteur.
            if not hasattr(self.vue, "set_source"):
                self.bouton_observer = QPushButton(tr("console.mode.observer"))
                self.bouton_observer.clicked.connect(
                    lambda: self.marche.emit(self.mode_id, self._arrete))
                haut = QHBoxLayout()
                haut.addWidget(self.bouton_observer)
                haut.addStretch(1)
                dedans.addLayout(haut)
            dedans.addWidget(self.vue, 1)
            blocs.append(self.bloc_observer)
            entete.addWidget(self.etat)      # ici l'état EST l'objet de la page
        else:
            # ⚠️ REPLIÉE, pas supprimée : elle sert à regarder un décodage lancé depuis la grille,
            # et reviendra en face avec « Connecter ». Cachée SANS case pour l'ouvrir, elle serait
            # un widget testé que personne ne peut voir — le motif que ce dépôt traque.
            self.direct = QCheckBox(tr("console.mode.direct"))
            self.direct.setToolTip(tr("console.mode.direct_aide"))
            self.pli_direct = QWidget()
            pli = QVBoxLayout(self.pli_direct)
            pli.setContentsMargins(0, 0, 0, 0)
            pli.addWidget(_phrase(tr("console.mode.direct_vide")))
            # L'état du décodage (« arrêté », « décode »…) vit ICI, et plus dans l'en-tête : une
            # page testable ne démarre ni n'arrête rien, donc un « arrêté » en tête de page n'y
            # disait rien d'utile — il laissait croire qu'il fallait démarrer quelque chose avant
            # de tester (relevé à la livraison de la page en blocs).
            pli.addWidget(self.etat)
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

    def _appliquer_avant_de_partir(self):
        """Envoie ce qui est À L'ÉCRAN avant de quitter la page. Rend (parti, réglages validés).

        Le geste commun à « Tester » et à « Mesurer » : les deux quittent la page, et les deux
        reviennent dessus. `parti` faux = le moteur a refusé ; le refus s'affiche dans « Régler »,
        et l'on RESTE — partir tester (ou mesurer) une configuration que le moteur refuse ne
        mesurerait rien, et la saisie fautive serait perdue au retour.

        ⚠️ Pendant que le TEST de ce mode tourne, rien n'est envoyé (constat M7 de la revue) : il
        est parti avec ses réglages, et changer le magasin sous lui ferait afficher à cette page
        une configuration que son verdict ne décrira pas. Le clic mène alors simplement à la
        page du test en cours.
        """
        if self.console.mesure_en_cours(self.spec.get("test_id") or ""):
            return True, None
        ack = self.console.commande("set_params", id=self.mode_id,
                                    params=self.formulaire.values())
        if not ack.get("accepted"):
            self.formulaire.show_refus(ack.get("reason", ""))
            return False, None
        self.formulaire.show_refus("")
        return True, ack.get("params")

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
        parti, reglages = self._appliquer_avant_de_partir()
        if not parti:
            return
        # Les valeurs VALIDÉES par le moteur, pour pré-remplir le test tout de suite : l'état
        # sondé n'aura rattrapé ce réglage qu'au prochain tour de `QTimer`.
        self.console.show_mesure(self.spec["test_id"], depuis=self, reglages=reglages)

    def _mesurer(self, mesure_id):
        """« Mesurer » applique d'abord ce qui est à l'écran, comme « Tester » (constat I4).

        🔴 Sans ce geste, l'aller-retour ÉCRASAIT la saisie : on tape « Rafraîchissement 30 » et
        de nouvelles fréquences sans « Appliquer », on clique « Mesurer », on applique le pic
        alpha — qui écrit le magasin du mode —, on revient, et `update_from` recharge le
        formulaire depuis ce magasin : 60 Hz et le trio du dépôt étaient de retour, et « Tester »
        testait ce que l'étudiant venait d'effacer sans le savoir.
        """
        parti, _ = self._appliquer_avant_de_partir()
        if parti:
            self.console.show_mesure(mesure_id, depuis=self)

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
            # (La page ne démarre plus rien : ce sont « Tester » et le décodage continu qui
            # partiront avec — constat M14 de la revue.)
            self.formulaire.show_confirmation(
                tr("console.mode.reglage_retenu", mode=self.spec["label"])
                if ack.get("differe") else "")
            return
        # Un refus laisse la saisie fautive dans le champ — on la corrige plutôt qu'on la retape.
        # Mais il DIT ce qui reste en vigueur : sans ça, un champ rouge oublié finit par se lire
        # comme l'état du moteur, et l'étudiant croit décoder sur des réglages jamais appliqués.
        vigueur = self._derniers_params or {}
        raison = ack.get("reason", "")
        self.formulaire.show_refus(
            tr("console.mode.refus_en_vigueur", raison=raison,
               valeurs=", ".join(f"{c} = {v}" for c, v in vigueur.items()))
            if vigueur else raison)

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
            self.etat.setText(tr("console.etat.arrete"))
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
        phase = nom_phase(mode_state["phase"])
        self.etat.setText(phase if mode_state["published"]
                          else tr("console.etat.non_publie", phase=phase))
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
            self.bouton_observer.setText(tr("console.mode.observer") if self._arrete
                                         else tr("console.mode.arreter"))

    def rafraichir_choix(self):
        """Recharge les listes de choix DYNAMIQUES de ce mode (les modèles entraînés).

        Appelée sur ÉVÉNEMENT — à l'entrée dans la page (cf. `Console.show_mode`) — jamais dans le
        rafraîchissement périodique : résoudre ces choix lit le disque, et le faire dix fois par
        seconde a déjà coûté 30 % d'un cœur à ce projet. Revenir d'un entraînement, d'un test ou
        d'une mesure ramène sur CETTE page par `show_mode`, donc par ce même événement : un modèle
        fraîchement enregistré est dans la liste dès le retour. Quel modèle y est SÉLECTIONNÉ,
        c'est le magasin du moteur qui le dit (`update_from`), pas cette liste.
        """
        spec = registry.get(self.mode_id)
        if spec is None:
            return
        for param in spec.params:
            if param.choices_fn is not None:
                self.formulaire.set_choices(param.key, param.choices_now())
