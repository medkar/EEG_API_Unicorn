"""La page de calibration : briefing, déroulé, résultat. Elle ne décide de RIEN.

Tout ce qu'elle affiche vient de `snapshot()["calibration"]` : la phase, la consigne, la classe
cuée, le décompte, le numéro d'essai, le verdict. Aucun `QTimer` local ne tient de décompte, aucune
phase n'est déduite. C'est la règle de la console (« aucune logique que le moteur ne possède
déjà »), et ici elle a une raison de plus : le minutage d'une calibration est le protocole. Deux
horloges qui divergent donneraient un écran qui ment sur ce que le moteur enregistre vraiment.
"""

import os
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from console import compter  # noqa: E402
from console.beeps import TOP_ETAPE, connait  # noqa: E402
from console.params_form import ParamsForm  # noqa: E402
from console.resultat import BlocResultat  # noqa: E402
from core.i18n import nombre, tr  # noqa: E402
# Le vocabulaire des phases vient du MOTEUR, importé plutôt que recopié : renommer une phase côté
# moteur laisserait sinon cette page sans écran de résultat, sans qu'aucune erreur ne le signale.
from core.modes.calibration import PHASES_TERMINALES  # noqa: E402

# La phrase d'honnêteté n'est pas une constante de ce fichier. Elle vit dans chaque calibration
# (`mi_calib.HONNETETE`, `p300_calib.HONNETETE`) et voyage dans son résultat, sous la clé
# `honnetete` : cette page ne connaît AUCUN mode. Celle du MI parle d'un hasard à 33 % ; sous
# une sélection P300 parmi six cibles elle n'aurait aucun sens.


def _diagnostic(calib_state):
    """Ce que le moteur a REFUSÉ pendant cette séance, en une ligne — ou "" s'il n'a rien refusé.

    Les clés viennent du `state()` de chaque calibration ; on n'en invente aucune et on ne branche
    sur aucun identifiant de mode. Une clé absente vaut zéro : ce qui n'est pas compté ne
    s'affiche pas.
    """
    # Dans les mots de l'élève, pas dans ceux du moteur (« marqueur », « époque », « tampon »,
    # « mode calibration ») : il n'a lancé qu'un « Entraîner », seule chose qu'il puisse vérifier.
    # Une fonction par ligne, pas une clé de texte rangée dans la table : `tr` exige une clé
    # écrite en toutes lettres, pour que son existence se vérifie (cf. `core/i18n.py`).
    quoi = [(("refus_cible", "refus_etiquette", "refus_marqueur"),
             lambda n: tr("pages.calib.diag.refus", n=n)),
            (("epoques_perdues",), lambda n: tr("pages.calib.diag.perdus", n=n)),
            (("marqueurs_chauffe",), lambda n: tr("pages.calib.diag.chauffe", n=n))]
    morceaux = []
    for cles, phrase in quoi:
        n = sum(int(calib_state.get(c, 0) or 0) for c in cles)
        if n:
            morceaux.append(phrase(n))
    return " · ".join(morceaux)


class CalibPage(QWidget):
    """Trois écrans construits UNE FOIS, montrés ou cachés selon la phase reçue.

    « Avant » (rien en cours, ou une séance terminée) porte le briefing et le bouton « Commencer » ;
    « Pendant » porte la consigne et le décompte ; « Après » porte le résultat. Les deux premiers
    ne sont jamais visibles en même temps, mais « Avant » et « Après » le sont : dès qu'une séance
    se termine, il faut à la fois LIRE le résultat et pouvoir relancer sans naviguer ailleurs.
    """

    retour = Signal()

    def __init__(self, spec, console):
        super().__init__()
        self.spec = spec
        self.console = console
        self.mode_id = spec["id"]
        self.calib = spec.get("calibration") or {}
        # `etape` telle que vue au DERNIER rafraîchissement — pour détecter le FRONT MONTANT
        # vers "cue" (cf. _maybe_beep), indépendamment de `essai` et de `phase` : ni l'un ni
        # l'autre ne varie forcément d'un essai au suivant (l'échauffement, notamment, ne fait
        # avancer aucun des deux).
        self._etape_precedente = None

        entete = QHBoxLayout()
        self.bouton_retour = QPushButton(tr("pages.commun.retour_modes"))
        self.bouton_retour.clicked.connect(self.retour)
        entete.addWidget(self.bouton_retour)
        # Le titre vient du CONTRAT (le moteur l'écrit) ; le gras est une affaire de style, pas
        # de texte : pas de balise `<b>` à traduire.
        titre = QLabel(self.calib.get("label") or spec["label"])
        titre.setStyleSheet("font-weight: bold;")
        entete.addWidget(titre)
        entete.addStretch(1)

        # --- écran 1 : avant (ou de nouveau, une fois la séance TERMINÉE) --------------------
        self.bloc_avant = QGroupBox(tr("pages.commun.avant_de_commencer"))
        self.briefing = QLabel("\n".join(self.calib.get("briefing") or ()))
        self.briefing.setWordWrap(True)
        self.audio_avertissement = QLabel("")
        self.audio_avertissement.setWordWrap(True)
        self.audio_avertissement.setStyleSheet("color: #b8860b;")
        if not console.beeps.disponible:
            # Fixé une fois pour toutes : la disponibilité de l'audio ne change pas en cours de
            # session. Le dire franchement plutôt que de laisser un top silencieux se faire
            # passer pour un départ manqué.
            self.audio_avertissement.setText(
                tr("pages.calib.sans_son", raison=console.beeps.raison))
        self.formulaire = ParamsForm(list(self.calib.get("params") or ()))
        # Les réglages d'un entraînement partent AVEC « Commencer » (`start_calibration`) : le
        # bouton « Appliquer » du formulaire générique n'est branché à rien ici, et un bouton
        # sans effet se clique en croyant régler quelque chose. `mesure_page` cache le sien aussi.
        self.formulaire.bouton.hide()
        self.duree = QLabel("")
        self.duree.setWordWrap(True)
        self.duree.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        # Ce que le MOTEUR a répondu quand on a essayé de commencer. Un refus qui ne s'affiche que
        # sur stdout est un bouton qui ne fait rien.
        # Une NOTE sur le déroulé qui doit survivre au changement de bloc — « tel mode a été
        # arrêté pour cette séance, et le restera ». Hors des trois blocs, sous l'en-tête : l'avis,
        # lui, disparaît avec « Avant de commencer » dès que la séance démarre.
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #8a8f9c;")
        self.avis = QLabel("")
        self.avis.setWordWrap(True)
        self.avis.setStyleSheet("color: #e5484d;")
        self.bouton_commencer = QPushButton(tr("pages.commun.commencer"))
        self.bouton_commencer.clicked.connect(self._commencer)
        avant = QVBoxLayout(self.bloc_avant)
        avant.addWidget(self.briefing)
        avant.addWidget(self.audio_avertissement)
        avant.addWidget(self.formulaire)
        avant.addWidget(self.duree)
        avant.addWidget(self.bouton_commencer)
        avant.addWidget(self.avis)

        # --- écran 2 : pendant ----------------------------------------------------------------
        self.bloc_pendant = QGroupBox(tr("pages.commun.seance_en_cours"))
        self.consigne = QLabel("")
        self.consigne.setWordWrap(True)
        self.consigne.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.classe_cuee = QLabel("")
        self.classe_cuee.setStyleSheet("color: #4c8dff; font-weight: bold;")
        self.rappel = QLabel("")
        self.rappel.setStyleSheet("color: #8a8f9c;")
        self.decompte = QLabel("")
        self.decompte.setStyleSheet("font-size: 22px;")
        self.progression = QLabel("")
        # 🔴 Ce que le moteur REFUSE pendant la séance doit se VOIR ici. Les trois calibrations à
        # fenêtre comptent leurs refus (`refus_cible`, `refus_etiquette`, `refus_marqueur`) et le
        # socle compte ses époques perdues et ses marqueurs de chauffe ; ces compteurs sont dans
        # `snapshot()`, mais invisibles tant que la page ne les peint pas.
        # Cas rattrapé : la fenêtre lancée sans `--calibrer`. Sans ce diagnostic, l'écran montre
        # une progression normale à zéro essai, et l'élève découvre au bout de six minutes que la
        # séance est vide.
        self.diagnostic = QLabel("")
        self.diagnostic.setWordWrap(True)
        self.diagnostic.setStyleSheet("color: #b8860b;")
        self.barre = QProgressBar()
        self.barre.setTextVisible(False)
        self.bouton_abandon = QPushButton(tr("pages.commun.abandonner"))
        self.bouton_abandon.clicked.connect(self._abandonner)
        # La CROIX de fixation, quand le protocole en a une (le Motor Imagery) : c'est
        # le moteur qui dit quand (`croix` de l'instantané : None = pas de croix dans ce protocole,
        # False = sa place reste, vide, pendant la pause). Au-dessus de la consigne, centrée.
        self.croix = QLabel("")
        self.croix.setAlignment(Qt.AlignCenter)
        self.croix.setStyleSheet("font-size: 72px; font-weight: bold;")
        # Hauteur FIGÉE sur celle du « + » : vide pendant la pause, la croix garde sa place.
        self.croix.setText("+")
        self.croix.ensurePolished()
        self.croix.setFixedHeight(self.croix.sizeHint().height())
        self.croix.setText("")
        self.croix.setVisible(False)
        pendant = QVBoxLayout(self.bloc_pendant)
        pendant.addWidget(self.croix)
        pendant.addWidget(self.consigne)
        pendant.addWidget(self.classe_cuee)
        pendant.addWidget(self.rappel)
        pendant.addWidget(self.decompte)
        pendant.addWidget(self.progression)
        pendant.addWidget(self.diagnostic)
        pendant.addWidget(self.barre)
        # « Abandonner » doit exister pendant TOUTE la séance (chauffe, échauffement, essais,
        # entraînement) : un étudiant qui a mal placé une électrode doit pouvoir sortir sans
        # tuer la console. Il vit dans ce bloc, qui reste visible sur toute cette plage — cf.
        # `update_from`, où « pendant » couvre tout sauf « fini »/« annule ».
        pendant.addWidget(self.bouton_abandon)

        # --- écran 3 : après ------------------------------------------------------------------
        self.bloc_apres = QGroupBox(tr("pages.commun.resultat"))
        self.resultat = QLabel("")
        self.resultat.setWordWrap(True)
        self.resultat.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.details = QLabel("")
        self.details.setWordWrap(True)
        self.honnetete = QLabel("")
        self.honnetete.setWordWrap(True)
        self.honnetete.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        # La DÉCISION. Le moteur écrit son modèle dans un dossier temporaire et attend un geste :
        # tant que « Enregistrer » n'est pas cliqué, RIEN n'est dans `data/`, et la fermeture de
        # la console effacerait le candidat. Le dire, sinon un élève qui lit son score croit
        # légitimement que son modèle existe.
        self.decision = QLabel("")
        self.decision.setWordWrap(True)
        self.decision.setStyleSheet("font-weight: bold;")
        # Le REFUS d'« Enregistrer » ou de « Refaire », sur SA propre ligne : `decision` est
        # réécrit à chaque rafraîchissement, et un refus y serait effacé en 100 ms par « Pas
        # encore enregistré ». Seuls un nouveau geste ou une nouvelle séance l'effacent.
        self.refus_decision = QLabel("")
        self.refus_decision.setWordWrap(True)
        self.refus_decision.setStyleSheet("color: #e5484d; font-weight: bold;")
        self.bouton_enregistrer = QPushButton(tr("pages.calib.enregistrer"))
        self.bouton_enregistrer.clicked.connect(self._enregistrer)
        self.bouton_refaire = QPushButton(tr("pages.calib.refaire"))
        self.bouton_refaire.clicked.connect(self._refaire)
        gestes = QHBoxLayout()
        gestes.addWidget(self.bouton_enregistrer)
        gestes.addWidget(self.bouton_refaire)
        gestes.addStretch(1)
        # ⚠️ EN FACE, trois lignes écrites par le MOTEUR (`core/modes/affichage.py`) : le verdict
        # en couleur, la mesure avec son hasard, une réserve. La phrase complète, les chiffres
        # secondaires, le nom du fichier et l'honnêteté passent DANS le repli « Détails » — ils
        # sont rangés, pas supprimés.
        self.bloc = BlocResultat(corps_auto=False)
        self.bloc.ajouter_au_detail(self.resultat, self.details, self.honnetete)
        apres = QVBoxLayout(self.bloc_apres)
        apres.addWidget(self.bloc)
        apres.addWidget(self.refus_decision)
        apres.addWidget(self.decision)
        apres.addLayout(gestes)

        layout = QVBoxLayout(self)
        # Ordre choisi pour la lecture, pas pour la construction : « pendant » et « après » ne
        # sont jamais visibles en même temps que ne serait-ce que l'un des deux autres blocs sauf
        # « avant » (cf. `update_from`), donc seul l'ordre AVANT/APRÈS compte vraiment — et un
        # étudiant qui revient sur cette page après une séance veut lire son résultat AVANT de
        # retomber sur le briefing d'une nouvelle séance.
        layout.addLayout(entete)
        # Le CORPS défile : « Détails » déplié, les textes se tassaient les uns sur
        # les autres faute de hauteur. L'en-tête reste en haut, hors du défilement.
        corps = QWidget()
        dedans = QVBoxLayout(corps)
        dedans.setContentsMargins(0, 0, 0, 0)
        dedans.addWidget(self.note)
        dedans.addWidget(self.bloc_pendant)
        dedans.addWidget(self.bloc_apres)
        dedans.addWidget(self.bloc_avant)
        dedans.addStretch(1)
        self.defilement = QScrollArea()
        self.defilement.setWidget(corps)
        self.defilement.setWidgetResizable(True)     # sinon le corps garde sa taille d'origine
        self.defilement.setFrameShape(QScrollArea.NoFrame)
        layout.addWidget(self.defilement, 1)

        # État initial cohérent avant le premier `update_from` : rien n'a encore tourné.
        self.bloc_avant.setVisible(True)
        self.bloc_pendant.setVisible(False)
        self.bloc_apres.setVisible(False)
        # La séance de CE mode tournait-elle au dernier `update_from` ? Retenu pour `_geler`, que
        # `montrer_avis` appelle entre deux rafraîchissements.
        self._en_cours = False

    def _geler(self):
        """Fige le formulaire et « Commencer » pendant la séance ET entre le clic et son départ.

        Pendant la séance : changer un réglage n'aurait aucun effet sur une séance déjà lancée, et
        un champ actif sans effet est un mensonge. ENTRE le clic et le départ : les valeurs sont
        déjà copiées dans la demande de la console, qui passe par le contrôle de liaison, l'arrêt
        du mode, puis l'attente de la séance — une valeur changée pendant ce temps ne partirait
        pas, et la séance démarrerait avec l'ancienne, sans un mot. Le « en route » est lu dans
        la CONSOLE (`entrainement_en_route`), jamais tenu ici : un drapeau de page survivrait à
        une demande abandonnée. Tout se dégèle dès que la séance est TERMINÉE (pas seulement
        absente), pour en relancer une autre sans naviguer ailleurs.
        """
        fige = self._en_cours or self.console.entrainement_en_route(self.mode_id)
        self.formulaire.setEnabled(not fige)
        self.bouton_commencer.setEnabled(not fige)

    def _commencer(self):
        """Demande une calibration à la CONSOLE, qui l'orchestre. Cette page n'envoie pas
        `start_calibration` elle-même, et c'est l'ordre qui l'impose.

        Trois choses doivent arriver, dans cet ordre, et deux d'entre elles ne sont pas de son
        ressort : contrôler la liaison casque, ARRÊTER le mode s'il décode (sans quoi le moteur
        refuse — un mode et sa calibration liraient la même file de marqueurs), puis seulement
        soumettre `start_calibration` et lancer la fenêtre de stimulus. Cf.
        `Console.demander_calibration`.
        """
        self.avis.setText("")
        self.note.setText("")
        self.console.demander_calibration(self.mode_id, self.formulaire.values())
        # Figé DÈS le clic — sauf si le moteur a refusé les réglages sur-le-champ : il n'y a
        # alors rien en route, et le formulaire reste ouvert pour les corriger.
        self._geler()

    def _abandonner(self):
        """Émet `cancel_calibration`. Aucun `id` à fournir : le moteur ne tient qu'UNE
        calibration à la fois, la sienne, quel que soit le mode qui l'a démarrée."""
        self.console.arreter_calibration()

    def _enregistrer(self):
        """Émet `save_calibration` : le candidat REJOINT `data/`, sous un nom horodaté libre.

        ⚠️ La console n'écrit RIEN sur le disque, ici pas plus qu'ailleurs. Elle envoie une
        commande ; c'est la boucle du moteur qui déplace les fichiers, depuis le fil qui les a
        écrits. Un `shutil.move` dans le fil Qt toucherait un dossier que l'autre fil est en train
        de balayer.
        """
        ack = self.console.commande("save_calibration")
        self.refus_decision.setText("" if ack.get("accepted")
                                    else tr("pages.commun.refuse", raison=ack.get("reason", "")))

    def _refaire(self):
        """Émet `discard_calibration` : le candidat est supprimé et l'écran de verdict effacé.

        Le moteur remet alors `calibration` à `None`, donc `update_from` ramène tout seul sur
        l'écran « Avant » — cette page ne navigue pas, elle attend l'état comme pour le reste.
        """
        ack = self.console.commande("discard_calibration")
        self.refus_decision.setText("" if ack.get("accepted")
                                    else tr("pages.commun.refuse", raison=ack.get("reason", "")))

    def montrer_note(self, texte):
        """Une note de déroulé qui RESTE jusqu'au prochain « Commencer » (cf. `self.note`)."""
        self.note.setText(texte or "")

    def montrer_avis(self, texte, alerte=True):
        """Affiche ce que le moteur (ou le lanceur de fenêtre) a répondu à « Commencer ».

        `alerte=False` pour une information de déroulé (« arrêt du mode demandé… ») : la peindre
        en rouge la ferait lire comme un échec, alors que c'est le début du succès.
        """
        self.avis.setText(texte or "")
        self.avis.setStyleSheet("color: #e5484d;" if alerte else "color: #8a8f9c;")
        # Un avis clôt souvent une demande (refus, renoncement) : dégeler TOUT DE SUITE ce qui n'est
        # plus en route, plutôt qu'au rafraîchissement suivant.
        self._geler()

    def _maybe_beep(self, calib_state):
        """Joue le top de la classe cuée sur le FRONT MONTANT de `etape` vers « cue », jamais de
        plus.

        ⚠️ Ne PAS retenir `(phase, essai, etape)` comme clé : `essai` (le compteur d'essais
        ENREGISTRÉS) ne bouge JAMAIS pendant l'échauffement, seule la phase « essais » l'incrémente
        (`core/modes/calibration.py::_pas_essai`), et `phase` reste constante tout au long d'une
        phase. Une telle clé vaut la même chose pour tous les essais d'échauffement du MI : le
        premier top sonne, les suivants jamais, à chaque séance. Ce qui distingue de façon fiable
        « un nouvel essai commence » de « la page se repeint pendant le même cue » (~10 fois par
        seconde) est la TRANSITION de `etape` elle-même.

        Une tâche sans son propre (pieds, mains, un repos…) reçoit le top neutre, centré : la même
        règle que le test (`MesurePage._maybe_beep`). Jamais le silence — l'élève ne saurait pas
        quand commencer.
        """
        etape = calib_state.get("etape")
        if etape == "cue" and self._etape_precedente != "cue":
            classe = calib_state.get("classe")
            self.console.beeps.jouer(classe if connait(classe) else TOP_ETAPE)
        self._etape_precedente = etape

    def update_from(self, state):
        """Ressort `state["calibration"]`, choisit les écrans, ne calcule rien.

        Filtre sur `mode_id` : le moteur ne tient qu'une calibration à la fois, mais rien ne
        garantit qu'elle soit celle de CE mode — une page ne doit jamais présenter la séance
        d'un autre mode comme si c'était la sienne.
        """
        calib_state = (state or {}).get("calibration")
        if calib_state is not None and calib_state.get("mode_id") != self.mode_id:
            calib_state = None

        phase = calib_state.get("phase") if calib_state else None
        en_cours = calib_state is not None and phase not in PHASES_TERMINALES
        termine = calib_state is not None and phase in PHASES_TERMINALES

        self.bloc_avant.setVisible(not en_cours)
        self.bloc_pendant.setVisible(en_cours)
        self.bloc_apres.setVisible(termine)
        self._en_cours = en_cours
        self._geler()

        # L'unité de `essai`/`total`, publiée par le moteur ; « essai » si elle manque.
        unite = (calib_state or {}).get("unite") or tr("pages.calib.unite_defaut")
        if calib_state is not None:
            minutes = calib_state.get("duree_estimee_s", 0.0) / 60.0
            self.duree.setText(tr(
                "pages.calib.duree", minutes=nombre(minutes, ".1f"),
                compte=compter(int(calib_state.get("total", 0)), unite)))
        else:
            self.duree.setText("")

        # Remettre `_etape_precedente` à zéro dès qu'AUCUNE séance ne tourne. Ça semble redondant
        # pour la fin NORMALE : `_pas_essai`/`_commencer_essais`/`_terminer` posent tous
        # `etape = ""` AVANT `entrainement`/`fini` (cf. core/modes/calibration.py), donc un poll
        # voit cette étape vide pendant que `en_cours` est ENCORE vrai (phase "entrainement" n'est
        # pas terminale), et `_maybe_beep` la capture déjà toute seule. Mais c'est FAUX pour
        # l'abandon : `cancel()` pose `etape = ""` ET la phase terminale dans le MÊME appel — il
        # n'existe donc AUCUN poll où `en_cours` est vrai avec une étape vide à observer.
        # `_etape_precedente` resterait alors bloqué sur la dernière étape non vide vue avant
        # l'abandon (souvent "cue"), et le tout premier top d'une séance relancée ensuite ne
        # sonnerait pas — silencieusement, sans rapport avec le tirage. Remettre ICI, hors du
        # `if en_cours`, couvre les DEUX sorties (fin normale et abandon) par le même geste, sans
        # dépendre de la manière dont chacune est sortie.
        if en_cours:
            # Une séance TOURNE : le refus affiché avant elle parlait d'une tentative qui n'a plus
            # cours. Le laisser à l'écran ferait lire « ça n'a pas démarré » pendant que ça tourne.
            self.avis.setText("")
            self.refus_decision.setText("")
            self._maybe_beep(calib_state)
            self.consigne.setText(calib_state.get("instruction") or "")
            croix = calib_state.get("croix")
            self.croix.setVisible(croix is not None)
            self.croix.setText("+" if croix else "")
            self.classe_cuee.setText(calib_state.get("classe") or "")
            self.rappel.setText(calib_state.get("rappel") or "")
            self.decompte.setText(tr(
                "pages.commun.decompte", s=nombre(float(calib_state.get('restant_s', 0.0)), ".1f")))
            essai = int(calib_state.get("essai", 0))
            total = int(calib_state.get("total", 0))
            self.progression.setText(tr("pages.calib.progression", unite=unite, n=essai,
                                        total=total))
            self.barre.setRange(0, max(total, 1))
            self.barre.setValue(min(essai, max(total, 1)))
            self.diagnostic.setText(_diagnostic(calib_state))
        else:
            self._etape_precedente = None

        if termine:
            resultat = calib_state.get("resultat")
            if resultat is not None:
                self._montrer_resultat(resultat)
            else:
                raison = tr("pages.calib.abandonne",
                            raison=calib_state.get("probleme", "")
                            or tr("pages.calib.aucun_modele"))
                # EN FACE, et en gris : pas de verdict, donc rien à peindre en couleur. Cette
                # phrase ne doit pas vivre que dans `self.resultat`, que le repli « Détails »
                # cache : un test qui lit le texte du label ne vérifie pas qu'on le VOIT.
                self.bloc.montrer({"verdict": raison})
                self.resultat.setText(raison)
                self.details.setText("")
                # Rien à mettre en garde : sans accuracy, il n'y a rien à sur-interpréter.
                self.honnetete.setVisible(False)
            # `candidat` non nul = il reste une DÉCISION à prendre. Le moteur a écrit le modèle
            # dans un dossier temporaire et n'a rien mis dans `data/` : sans les deux boutons
            # ci-dessous, aucune calibration n'atteindrait jamais `data/`.
            self._montrer_decision(calib_state.get("candidat"), resultat)

    # --- le verdict : rendu sur ce que le résultat PORTE, jamais sur un mode connu -------------
    #
    # Chaque calibration rend son propre dictionnaire, et il n'y a pas deux modes qui mesurent la
    # même chose : le MI publie une accuracy par essai sur 3 classes, le P300 un taux de cibles
    # retrouvées sur 6. Les deux tables ci-dessous sont indexées par CLÉ DE RÉSULTAT, jamais par
    # identifiant de mode — c'est la même discipline que `live_views`, qui route sur la forme de
    # la sortie et pas sur `spec["id"]`.
    #
    # ⚠️ On n'écrit que ce qui est présent : des lignes du MI en dur afficheraient « 0 fenêtres
    # d'entraînement — classes : » sous un résultat P300, qui n'a ni fenêtres ni classes — des
    # chiffres fabriqués, sous le seul écran qui sert à décider si on garde le modèle.

    # La mesure qui DÉCIDE. Une seule est présente à la fois ; à `None` (mesure impossible), on
    # passe à la suivante, et s'il n'en reste aucune on n'affiche AUCUN chiffre — jamais un 0 %,
    # qui se lirait comme un diagnostic précis (« contact des électrodes ») sans rapport avec la
    # vraie cause.
    #
    # Une MÉTHODE, pas une constante : les libellés sont lus au moment d'afficher, dans la
    # langue choisie (une constante serait lue au chargement, avant ce choix).
    @staticmethod
    def _mesures():
        return (
            ("cv_groupee", tr("pages.calib.mesure.cv_groupee")),
            ("selection", tr("pages.calib.mesure.selection")),
            # ⚠️ L'AUC vient EN DERNIER : sa place dans cette liste la rend correcte pour les deux
            # modes qui la publient. Le P300 la rend AUSSI, mais chez lui le chiffre qui décide est
            # la sélection ; plus haut, l'AUC ferait afficher la mauvaise mesure. L'ErrP ne publie
            # qu'elle (il répond oui/non à chaque feedback), et son AUC hors-pli est le seul de ses
            # chiffres qui ne soit pas mesuré au seuil qui l'a choisi.
            ("auc", tr("pages.calib.mesure.auc")),
            # Le c-VEP est le seul mode à entraîner DEUX décodeurs sur les mêmes époques. La mesure
            # qui décide est celle de l'eCCA, arbitrairement : les deux sont indiscernables sur la
            # seule séance réelle (McNemar p = 0,727), donc en mettre un plutôt que l'autre ne
            # choisit rien. Celle du rCCA est en détail, et le `verdict` porte le test qui dit s'il
            # y a lieu de les départager.
            ("acc_ecca", tr("pages.calib.mesure.acc_ecca")),
        )
    # Le détail, par clé présente elle aussi. `cv_naive` n'y figure pas : elle est gonflée de 10
    # à 16 points, et l'afficher à côté de l'honnête invite à choisir la plus belle.
    # Une fonction par ligne (valeur -> texte) : le NOMBRE se met en forme ici, le texte vient du
    # fichier de langue, avec une clé écrite en toutes lettres.
    DETAILS = (
        ("n_essais", lambda v: tr("pages.calib.detail.n_essais", n=v)),
        ("n_fenetres", lambda v: tr("pages.calib.detail.n_fenetres", n=v)),
        ("n_manches", lambda v: tr("pages.calib.detail.n_manches", n=v)),
        ("n_erreurs", lambda v: tr("pages.calib.detail.n_erreurs", n=v)),
        # Le point de FONCTIONNEMENT de l'ErrP, en détail et jamais comme mesure qui décide : ces
        # deux taux sont mesurés au seuil qui les a choisis, donc optimistes par construction (sa
        # phrase d'honnêteté le dit au long, juste en dessous).
        ("tpr", lambda v: tr("pages.calib.detail.tpr", pct=f"{v:.0%}")),
        ("tnr", lambda v: tr("pages.calib.detail.tnr", pct=f"{v:.0%}")),
        ("perm_p", lambda v: tr("pages.calib.detail.perm_p", p=nombre(v, ".3f"))),
        # Le SECOND décodeur du c-VEP, en détail et jamais comme mesure qui décide : afficher deux
        # pourcentages côte à côte invite à prendre le plus beau, et cinq points d'écart sur
        # 37 décisions sont du bruit. C'est `n_discordantes` qui porte l'information, et le
        # `verdict` qui rend le test de McNemar.
        ("acc_rcca", lambda v: tr("pages.calib.detail.acc_rcca", pct=f"{v:.1%}")),
        ("n_discordantes", lambda v: tr("pages.calib.detail.n_discordantes", n=v)),
    )

    def _mesure(self, resultat):
        """(clé, libellé, valeur) de la mesure qui décide, ou None si le résultat n'en publie
        aucune. La CLÉ est rendue pour que le détail ne répète pas le chiffre principal."""
        for cle, libelle in self._mesures():
            valeur = resultat.get(cle)
            if valeur is not None:
                return cle, libelle, float(valeur)
        return None

    def _montrer_resultat(self, resultat):
        # En face : les trois lignes du moteur. Tout ce qui suit remplit le REPLI « Détails ».
        self.bloc.montrer(resultat)
        mesure = self._mesure(resultat)
        if mesure is None:
            # Le `verdict` du moteur porte déjà la raison en clair dans ce cas (« justesse non
            # mesurable : … ») — l'afficher SEUL évite de le faire suivre d'un chiffre inexistant.
            self.resultat.setText(resultat.get("verdict", ""))
        else:
            _cle, libelle, valeur = mesure
            hasard = resultat.get("hasard")
            # Le niveau du hasard À CÔTÉ : « 40 % » seul ne veut rien dire, et il ne vaut pas la
            # même chose à 3 classes (33 %) qu'à 6 cibles (17 %) qu'à une AUC (50 %).
            if hasard is None:
                self.resultat.setText(tr(
                    "pages.calib.ligne_mesure", verdict=resultat.get("verdict", ""),
                    libelle=libelle, valeur=nombre(valeur*100, ".1f")))
            else:
                self.resultat.setText(tr(
                    "pages.calib.ligne_mesure_hasard", verdict=resultat.get("verdict", ""),
                    libelle=libelle, valeur=nombre(valeur*100, ".1f"),
                    hasard=f"{float(hasard)*100:.0f}"))

        lignes = [tr("pages.calib.detail.modele", nom=resultat.get("nom", ""))]
        # AVEC QUOI il a appris — bande, coupe-bande, méthode. Un texte déjà rédigé par le moteur
        # (`affichage.texte_filtre`) : la page ne connaît ni les bandes ni les méthodes.
        if resultat.get("filtre"):
            lignes.append(resultat["filtre"])
        morceaux = [texte(resultat[cle]) for cle, texte in self.DETAILS
                    if resultat.get(cle) is not None]
        # ⚠️ L'AUC ne figure en détail que quand elle n'est PAS la mesure qui décide — chez le P300,
        # où elle accompagne la sélection. Chez l'ErrP elle EST la mesure : la répéter afficherait
        # le même chiffre deux fois, la seconde fois sous un libellé (« cible/non-cible ») qui
        # appartient à un autre paradigme.
        if resultat.get("auc") is not None and (mesure is None or mesure[0] != "auc"):
            morceaux.append(tr("pages.calib.detail.auc_cible",
                               pct=f"{float(resultat['auc'])*100:.0f}"))
        if resultat.get("classes"):
            morceaux.append(tr("pages.calib.detail.classes",
                               liste=", ".join(resultat["classes"])))
        if morceaux:
            lignes.append(" — ".join(morceaux))
        self.details.setText("\n".join(lignes))

        # ⚠️ La phrase d'honnêteté vient du RÉSULTAT, jamais d'une constante de ce fichier : celle
        # du MI parle de 40 % à trois classes, celle du P300 d'AUC et de sélection parmi six
        # cibles. Une calibration qui n'en fournirait pas n'affiche rien plutôt que celle d'un
        # autre mode.
        phrase = resultat.get("honnetete") or ""
        self.honnetete.setText(phrase)
        self.honnetete.setVisible(bool(phrase) and mesure is not None)

    def _montrer_decision(self, candidat, resultat):
        """Ce qu'il reste à faire du modèle : le garder, ou le refaire.

        ⚠️ Le point d'honnêteté de cet écran. Un chiffre affiché n'est PAS un modèle enregistré :
        tant que `candidat` est renseigné, le fichier vit dans un dossier temporaire que la
        fermeture de la console efface (`EngineServer.close()`). L'écrire noir sur blanc.
        """
        a_decider = bool(candidat)
        self.bouton_enregistrer.setVisible(a_decider)
        self.bouton_refaire.setVisible(a_decider)
        if a_decider:
            # UNE ligne, qui garde le point d'honnêteté entier : un chiffre affiché n'est pas
            # un modèle enregistré.
            self.decision.setText(tr("pages.calib.pas_encore_enregistre"))
            self.decision.setStyleSheet("color: #b8860b; font-weight: bold;")
        elif resultat is not None:
            self.decision.setText(tr("pages.calib.modele_en_place",
                                     chemin=resultat.get("modele", "")))
            self.decision.setStyleSheet("color: #3fae5a; font-weight: bold;")
        else:
            self.decision.setText("")
