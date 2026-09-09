"""La page d'une MESURE : briefing, déroulé, verdict. Elle ne calcule RIEN.

Jumelle de `calib_page.py`, et pour la même raison : tout ce qu'elle affiche vient de
`snapshot()["mesure"]` — la phase, la consigne, l'étape en cours, le décompte, le verdict, la
phrase d'honnêteté. Le ratio, le pic et la phrase qui arrête sont calculés par le moteur
(`core/modes/alpha.py`) ; cette page les met en forme et rien de plus. Une seconde règle de
décision écrite ici finirait par contredire celle du moteur, et ce jour-là c'est l'écran qu'on
croirait.

⚠️ **Deux choses la distinguent d'une page de calibration, et les deux comptent.**

1. **Le sujet a les YEUX FERMÉS pendant la moitié de la mesure — il ne peut RIEN lire.** Un
   protocole entièrement visuel serait donc inutilisable là où il compte. Cette page joue un TOP
   SONORE à chaque changement d'étape (cf. `_maybe_beep`), et **le dit franchement** quand la
   machine n'a pas de son : un top silencieux se ferait passer pour un départ manqué, et la
   personne rouvrirait les yeux au hasard.
2. **Une mesure peut être une BARRIÈRE** (`spec["barriere"]`). Quand elle ne passe pas, le verdict
   n'est pas un chiffre à interpréter mais une phrase qui ARRÊTE la séance : la page la peint
   comme telle, en tête, avant tout détail.

⚠️ **Aucun fichier, nulle part.** Une mesure n'écrit rien (c'est sa définition, cf.
`core/modes/mesure.py`), donc cette page n'a ni « Enregistrer » ni « Refaire » — il n'y a aucun
candidat à retenir ou à jeter. Le seul geste qu'elle propose après coup est d'APPLIQUER un réglage
que le moteur a lui-même désigné.

⚠️ **Certaines mesures ont une FENÊTRE de stimulus, d'autres non**, et cette page ne le sait pas :
c'est `Console._demarrer_mesure` qui lit `stimulus_id` dans le contrat et lance la fenêtre juste
après la commande. Le contrôle alpha n'en a aucune (les yeux sont fermés la moitié du temps) ; le
taux d'émission SSVEP en a une, puisqu'il n'y a rien à décoder sans cibles qui clignotent. Le
briefing de chaque mesure dit lequel des deux cas s'applique — écrit par le moteur, pas ici.
"""

import os
import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from console.beeps import TOP_ETAPE  # noqa: E402
from console.params_form import ParamsForm  # noqa: E402
# Le vocabulaire des phases vient du MOTEUR, importé plutôt que recopié — même geste que
# `calib_page.py`. `mesure.PHASES_TERMINALES` EST l'objet de `calibration.py` (cf. son
# commentaire) : renommer une phase d'un côté ne peut pas laisser cette page sans écran de verdict.
from core.modes.mesure import PHASES_TERMINALES  # noqa: E402


class MesurePage(QWidget):
    """Trois écrans construits UNE FOIS, montrés ou cachés selon la phase reçue.

    Même découpage que `CalibPage` : « Avant » (rien en cours, ou une séance terminée) porte le
    briefing et « Commencer » ; « Pendant » porte la consigne et le décompte ; « Après » porte le
    verdict. « Avant » et « Après » sont visibles ENSEMBLE une fois la mesure finie — il faut
    pouvoir lire le verdict ET relancer sans naviguer ailleurs, ce qui est le geste normal quand
    une barrière n'est pas franchie et qu'on vient de re-saliner.
    """

    retour = Signal()

    # Le détail, indexé par CLÉ DE RÉSULTAT — jamais par identifiant de mesure. C'est la
    # discipline de `CalibPage.DETAILS`, et elle a la même raison : la page ne connaît aucune
    # mesure. Le contrôle alpha publie un ratio et un pic ; le taux d'émission SSVEP publiera un
    # effectif et un intervalle de confiance. On n'affiche QUE ce qui est présent, jamais un zéro
    # fabriqué qui se lirait comme une mesure.
    DETAILS = (
        ("ratio", "ratio fermé/ouvert {:.2f}"),
        ("repere_ratio", "repère > {:g}"),
        ("pic_hz", "pic à {:.1f} Hz les yeux fermés"),
        ("pic_ouvert_hz", "pic à {:.1f} Hz les yeux ouverts"),
        # Le taux d'émission SSVEP. ⚠️ `n_essais` porte son UNITÉ dans le libellé, et ce n'est pas
        # de la coquetterie : c'est le seul endroit de l'interface où l'on peut confondre un
        # nombre d'essais avec un nombre de fenêtres du moteur, et l'écart entre les deux vaut un
        # facteur 7 sur l'effectif (cf. `core/modes/ssvep_mesure.py`).
        ("n_essais", "{:d} essais"),
        ("n_emis", "{:d} avec décision"),
        ("n_justes", "dont {:d} justes"),
        ("n_artefacts", "{:d} rejetés (artefact)"),
        ("fenetres_repos", "plancher sur {:d} fenêtres de repos"),
    )

    def __init__(self, spec, console):
        super().__init__()
        self.spec = spec
        self.console = console
        self.mesure_id = spec["id"]
        # L'étape telle que vue au DERNIER rafraîchissement, pour détecter le changement et ne
        # sonner qu'une fois (cf. `_maybe_beep`). `None` = aucune séance observée.
        self._etape_precedente = None
        # Le réglage que le moteur propose d'appliquer, tel qu'il est arrivé dans le résultat.
        # Retenu ici parce que le clic arrive plus tard que l'affichage — jamais recalculé.
        self._propose = None

        entete = QHBoxLayout()
        self.bouton_retour = QPushButton("← Modes")
        self.bouton_retour.clicked.connect(self.retour)
        entete.addWidget(self.bouton_retour)
        entete.addWidget(QLabel(f"<b>{spec['label']}</b>"))
        entete.addStretch(1)

        # --- écran 1 : avant (ou de nouveau, une fois la séance TERMINÉE) --------------------
        self.bloc_avant = QGroupBox("Avant de commencer")
        self.briefing = QLabel("\n".join(spec.get("briefing") or ()))
        self.briefing.setWordWrap(True)
        self.audio_avertissement = QLabel("")
        self.audio_avertissement.setWordWrap(True)
        self.audio_avertissement.setStyleSheet("color: #b8860b; font-weight: bold;")
        if not console.beeps.disponible:
            # Fixé une fois pour toutes : la disponibilité de l'audio ne change pas en cours de
            # session. ⚠️ Le message est PLUS ferme que celui d'une calibration, parce que l'enjeu
            # l'est : sur une calibration MI, les tops épargnent un regard vers l'écran ; ici, la
            # personne a les yeux FERMÉS et n'a aucun autre moyen de savoir quand rouvrir.
            self.audio_avertissement.setText(
                f"⚠ Pas de son sur cette machine ({console.beeps.raison}). Or la seconde moitié "
                f"de cette mesure se fait LES YEUX FERMÉS : sans top, tu ne sauras pas quand "
                f"rouvrir. Fais-toi accompagner par quelqu'un qui lit l'écran et te le dit à "
                f"voix haute, ou branche une sortie audio avant de commencer.")
        self.formulaire = ParamsForm(list(spec.get("params") or ()))
        # Cette page n'APPLIQUE aucun réglage en cours de route : une mesure se règle avant de
        # partir, et son formulaire est soumis avec `start_mesure`. Le bouton du formulaire
        # générique n'aurait donc rien à faire, et un bouton sans effet est un mensonge.
        self.formulaire.bouton.hide()
        self.duree = QLabel("")
        self.duree.setWordWrap(True)
        self.duree.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        # Ce que le MOTEUR a répondu quand on a essayé de commencer. Un refus qui ne s'affiche que
        # sur stdout est un bouton qui ne fait rien.
        self.avis = QLabel("")
        self.avis.setWordWrap(True)
        self.avis.setStyleSheet("color: #e2603f;")
        self.bouton_commencer = QPushButton("Commencer")
        self.bouton_commencer.clicked.connect(self._commencer)
        avant = QVBoxLayout(self.bloc_avant)
        avant.addWidget(self.briefing)
        avant.addWidget(self.audio_avertissement)
        avant.addWidget(self.formulaire)
        avant.addWidget(self.duree)
        avant.addWidget(self.bouton_commencer)
        avant.addWidget(self.avis)

        # --- écran 2 : pendant ----------------------------------------------------------------
        self.bloc_pendant = QGroupBox("Mesure en cours")
        self.consigne = QLabel("")
        self.consigne.setWordWrap(True)
        self.consigne.setStyleSheet("font-size: 22px; font-weight: bold;")
        self.etape = QLabel("")
        self.etape.setStyleSheet("color: #4c8dff; font-weight: bold;")
        self.rappel = QLabel("")
        self.rappel.setWordWrap(True)
        self.rappel.setStyleSheet("color: #8a8f9c;")
        self.decompte = QLabel("")
        self.decompte.setStyleSheet("font-size: 22px;")
        self.progression = QLabel("")
        self.barre = QProgressBar()
        self.barre.setTextVisible(False)
        self.bouton_abandon = QPushButton("Abandonner")
        self.bouton_abandon.clicked.connect(self._abandonner)
        pendant = QVBoxLayout(self.bloc_pendant)
        pendant.addWidget(self.consigne)
        pendant.addWidget(self.etape)
        pendant.addWidget(self.rappel)
        pendant.addWidget(self.decompte)
        pendant.addWidget(self.progression)
        pendant.addWidget(self.barre)
        pendant.addWidget(self.bouton_abandon)

        # --- écran 3 : après ------------------------------------------------------------------
        self.bloc_apres = QGroupBox("Verdict")
        # La BARRIÈRE, en tête et en gras. Elle passe AVANT le verdict détaillé parce que c'est la
        # seule chose à savoir quand elle n'est pas franchie : on s'arrête et on reprend le
        # montage. Un chiffre lu d'abord invite à négocier avec.
        self.barriere = QLabel("")
        self.barriere.setWordWrap(True)
        self.barriere.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        self.verdict.setStyleSheet("font-size: 14px;")
        self.details = QLabel("")
        self.details.setWordWrap(True)
        self.honnetete = QLabel("")
        self.honnetete.setWordWrap(True)
        self.honnetete.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        # LE geste qui ferme la boucle : appliquer au moteur le réglage que la mesure vient de
        # produire. Le mode et la clé viennent du RÉSULTAT (`reglage_propose`) — cette page
        # n'écrit ni « ssvep » ni « alpha_hz », donc elle servira la mesure suivante sans changer.
        self.appliquer_pic = QPushButton("")
        self.appliquer_pic.clicked.connect(self._appliquer_propose)
        self.reponse_pic = QLabel("")
        self.reponse_pic.setWordWrap(True)
        gestes = QHBoxLayout()
        gestes.addWidget(self.appliquer_pic)
        gestes.addStretch(1)
        apres = QVBoxLayout(self.bloc_apres)
        apres.addWidget(self.barriere)
        apres.addWidget(self.verdict)
        apres.addWidget(self.details)
        apres.addWidget(self.honnetete)
        apres.addLayout(gestes)
        apres.addWidget(self.reponse_pic)

        layout = QVBoxLayout(self)
        layout.addLayout(entete)
        layout.addWidget(self.bloc_pendant)
        layout.addWidget(self.bloc_apres)
        layout.addWidget(self.bloc_avant)
        layout.addStretch(1)

        self.bloc_avant.setVisible(True)
        self.bloc_pendant.setVisible(False)
        self.bloc_apres.setVisible(False)

    # --- les gestes ------------------------------------------------------------------------

    def _commencer(self):
        """Demande la mesure à la CONSOLE, qui l'orchestre — contrôle de liaison d'abord.

        Cette page ne soumet pas `start_mesure` elle-même, pour la même raison que
        `CalibPage._commencer` : le contrôle de la liaison casque s'interpose, et il REFUSE. Pour
        cette mesure-ci c'est plus qu'une précaution — quatre voies plates donnent un rapport de
        puissances calculé sur du bruit d'arrondi, et 37 s de casque pour un verdict qui accuse
        le sujet au lieu du câble.
        """
        self.avis.setText("")
        self.console.demander_mesure(self.mesure_id, self.formulaire.values())

    def _abandonner(self):
        """Émet `cancel_mesure`. Aucun `id` : le moteur ne tient qu'UNE mesure à la fois."""
        self.console.arreter_mesure()

    def _appliquer_propose(self):
        """Envoie au moteur le réglage que la mesure a produit. La console ne calcule rien.

        ⚠️ C'est la boucle que la recette faisait faire à la main : noter le pic alpha sur un
        carnet, aller sur la page du SSVEP, le retaper, cliquer « Proposer ». Une valeur recopiée
        entre deux écrans est exactement ce que ce dépôt a déjà vu diverger.

        Le refus du moteur est AFFICHÉ, et il en existe un vrai : `set_params` n'atteint qu'un
        mode DÉMARRÉ (« SSVEP n'est pas démarré »). On le montre tel quel plutôt que de deviner —
        un bouton qui échoue en silence est la panne que ce chantier répare.
        """
        propose = self._propose
        if not propose:
            return
        ack = self.console.commande("set_params", id=propose["mode"],
                                    params={propose["cle"]: propose["valeur"]})
        if ack.get("accepted"):
            self.reponse_pic.setText(
                f"« {propose['label']} » = {propose['valeur']:g} {propose.get('unite', '')} "
                f"appliqué à « {propose.get('mode_label', propose['mode'])} ». Ouvre sa page et "
                f"clique « Proposer » pour en tirer un jeu de fréquences qui évite ton alpha.")
            self.reponse_pic.setStyleSheet("color: #3fae5a;")
        else:
            self.reponse_pic.setText(ack.get("reason", ""))
            self.reponse_pic.setStyleSheet("color: #e2603f;")

    def montrer_avis(self, texte, alerte=True):
        """Affiche ce que le moteur (ou le contrôle de liaison) a répondu à « Commencer »."""
        self.avis.setText(texte or "")
        self.avis.setStyleSheet("color: #e2603f;" if alerte else "color: #8a8f9c;")

    # --- le top sonore ----------------------------------------------------------------------

    def _maybe_beep(self, etat):
        """Un TOP à chaque CHANGEMENT d'étape. C'est le seul canal que le sujet ait les yeux fermés.

        ⚠️ On suit `classe` (le nom de l'étape en cours) et non `etape`, qui reste VIDE de bout en
        bout sur une mesure — c'est un choix explicite de `core/modes/mesure.py` : `etape` est ce
        que `CalibPage` guette pour sonner sur le « cue » d'une calibration MI, et le remplir ici
        ferait sonner l'autre page au hasard des noms d'étapes choisis par une mesure.

        ⚠️ Le déclencheur est la TRANSITION, pas un compteur — même leçon que
        `CalibPage._maybe_beep`, mesurée là-bas : `essai` ne bouge pas d'une étape à l'autre (les
        préparations n'incrémentent rien) et `phase` reste « essais » tout du long. Une clé assise
        dessus ne sonnerait qu'une fois pour les quatre étapes.

        Le premier état observé ne sonne JAMAIS (`None` au départ) : sinon ouvrir la page pendant
        la chauffe déclencherait un top qui n'annonce rien.
        """
        etape = etat.get("classe") or ""
        if self._etape_precedente is not None and etape != self._etape_precedente:
            self.console.beeps.jouer(TOP_ETAPE)
        self._etape_precedente = etape

    # --- l'état ------------------------------------------------------------------------------

    def update_from(self, state):
        """Ressort `state["mesure"]`, choisit les écrans, ne calcule rien.

        Filtre sur `mode_id` : le moteur ne tient qu'UNE mesure à la fois, mais rien ne garantit
        que ce soit celle de CETTE page — elle ne doit jamais présenter la séance d'une autre
        comme si c'était la sienne.
        """
        etat = (state or {}).get("mesure")
        if etat is not None and etat.get("mode_id") != self.mesure_id:
            etat = None

        phase = etat.get("phase") if etat else None
        en_cours = etat is not None and phase not in PHASES_TERMINALES
        termine = etat is not None and phase in PHASES_TERMINALES

        self.bloc_avant.setVisible(not en_cours)
        self.bloc_pendant.setVisible(en_cours)
        self.bloc_apres.setVisible(termine)
        self.formulaire.setEnabled(not en_cours)
        self.bouton_commencer.setEnabled(not en_cours)

        if etat is not None:
            self.duree.setText(
                f"Durée de cette mesure, stabilisation du casque comprise : "
                f"≈ {etat.get('duree_estimee_s', 0.0):.0f} s, pour "
                f"{etat.get('total', 0)} fenêtre(s) prélevée(s).")
        else:
            self.duree.setText("")

        # Remise à zéro du suivi de top hors séance — même geste et même raison que
        # `CalibPage.update_from` : `cancel()` pose l'étape vide ET la phase terminale dans le
        # MÊME appel, donc aucun rafraîchissement ne voit « en cours avec une étape vide ». Sans
        # cette ligne, le premier top d'une mesure RELANCÉE après un abandon ne sonnerait pas —
        # et c'est justement après un abandon qu'on relance.
        if en_cours:
            self.avis.setText("")
            self._maybe_beep(etat)
            self.consigne.setText(etat.get("instruction") or "")
            self.etape.setText(etat.get("classe") or "")
            self.rappel.setText(etat.get("rappel") or "")
            self.decompte.setText(f"{float(etat.get('restant_s', 0.0)):.1f} s")
            fait = int(etat.get("essai", 0))
            total = int(etat.get("total", 0))
            self.progression.setText(f"{fait} phase(s) enregistrée(s) sur {total}")
            self.barre.setRange(0, max(total, 1))
            self.barre.setValue(min(fait, max(total, 1)))
        else:
            self._etape_precedente = None

        if termine:
            self._montrer_resultat(etat.get("resultat"), etat.get("probleme", ""))

    def _montrer_resultat(self, resultat, probleme):
        """Le verdict, rendu sur ce que le résultat PORTE — jamais sur une mesure connue."""
        if resultat is None:
            # Abandon, ou calcul impossible. Aucun chiffre, donc rien à sur-interpréter — et
            # surtout pas de « barrière non franchie », qui accuserait le montage alors que la
            # mesure n'a simplement pas été jouée jusqu'au bout.
            self.barriere.setText("")
            self.verdict.setText(f"Mesure interrompue : {probleme or 'aucun verdict produit'}")
            self.details.setText("")
            self.honnetete.setText("")
            self._montrer_proposition(None)
            return

        self._montrer_barriere(resultat)
        self.verdict.setText(resultat.get("verdict", ""))

        morceaux = [gabarit.format(resultat[cle]) for cle, gabarit in self.DETAILS
                    if resultat.get(cle) is not None]
        if resultat.get("voies"):
            # Les voies moyennées viennent du MOTEUR : l'écran d'origine imprimait « PO7/Oz/PO8 »
            # alors qu'il en moyennait quatre, et personne ne l'a vu pendant des mois.
            morceaux.append("moyenne sur " + "/".join(resultat["voies"]))
        self.details.setText(" — ".join(morceaux))
        self.honnetete.setText(resultat.get("honnetete") or "")
        self._montrer_proposition(resultat.get("reglage_propose"))

    def _montrer_barriere(self, resultat):
        """La ligne qui ARRÊTE, ou celle qui autorise la suite. Absente si la mesure n'en est pas une.

        `barriere` (le contrat de la mesure) et `barriere_franchie` (son résultat) sont DEUX
        choses : la première dit que cette mesure a le pouvoir d'arrêter la séance, la seconde ce
        qu'elle a décidé aujourd'hui. Une mesure qui n'est pas une barrière et qui publierait
        `barriere_franchie` n'arrêterait donc rien — et c'est voulu : le taux d'émission SSVEP est
        un chiffre à lire, pas un feu rouge.
        """
        franchie = resultat.get("barriere_franchie")
        if not self.spec.get("barriere") or franchie is None:
            self.barriere.setText("")
            return
        if franchie:
            self.barriere.setText("BARRIÈRE FRANCHIE — la séance peut continuer.")
            self.barriere.setStyleSheet("font-size: 15px; font-weight: bold; color: #3fae5a;")
        else:
            self.barriere.setText(
                "🛑 BARRIÈRE NON FRANCHIE — ARRÊTE LA SÉANCE ICI. Tant que ce contrôle ne passe "
                "pas, aucune autre mesure et aucun décodage ne veulent rien dire : ils lisent "
                "tous ce même signal. Reprends le montage, puis relance CE contrôle.")
            self.barriere.setStyleSheet("font-size: 15px; font-weight: bold; color: #e2603f;")

    def _montrer_proposition(self, propose):
        """Le bouton qui applique le réglage produit — visible seulement s'il y en a un.

        ⚠️ C'est le MOTEUR qui décide s'il y en a un (cf. `core/modes/alpha.py` : rien n'est
        proposé quand la barrière n'est pas franchie, parce que le « pic » d'un spectre de bruit
        est le plus grand bin du bruit). Le tester ici serait une seconde règle de décision dans
        l'interface, et c'est exactement ce que cette console s'interdit.
        """
        self._propose = propose or None
        self.appliquer_pic.setVisible(bool(propose))
        self.reponse_pic.setText("")
        if propose:
            self.appliquer_pic.setText(
                f"Appliquer « {propose['label']} » = {propose['valeur']:g} "
                f"{propose.get('unite', '')} à « "
                f"{propose.get('mode_label', propose['mode'])} »")
