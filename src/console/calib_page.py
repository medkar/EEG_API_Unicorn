"""La page de calibration : briefing, déroulé, résultat. Elle ne décide de RIEN.

Tout ce qu'elle affiche vient de `snapshot()["calibration"]` : la phase, la consigne, la classe
cuée, le décompte, le numéro d'essai, le verdict. Aucun `QTimer` local ne tient de décompte, aucune
phase n'est déduite. C'est la règle de la console (« aucune logique que le moteur ne possède
déjà »), et ici elle a une raison de plus : le minutage d'une calibration est le protocole. Deux
horloges qui divergent donneraient un écran qui ment sur ce que le moteur enregistre vraiment.
"""

import os
import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from console.params_form import ParamsForm  # noqa: E402

# Les phases où une séance TOURNE (ni pas-encore-commencée, ni terminée) — le complément de
# `CalibrationRuntime.terminee` (cf. core/modes/calibration.py), recopié en dur ici plutôt
# qu'importé : cette page n'a besoin que de ce vocabulaire de deux mots, pas du reste de
# `core.modes.calibration`. Si le moteur ajoute une phase, ce fichier doit le savoir.
PHASES_TERMINALES = ("fini", "annule")

# La phrase d'honnêteté : OBLIGATOIRE avec le résultat, quelle que soit l'accuracy. Un « 40 % »
# sans elle ne veut rien dire, et le Motor Imagery ne marche pas également bien chez tout le
# monde — le produit le dit au lieu de le laisser découvrir.
HONNETETE = (
    "Ce chiffre est une validation croisée PAR ESSAI : il estime ce que le modèle fera sur un "
    "essai qu'il n'a jamais vu. C'est plus bas — et plus vrai — que ce qu'affichait l'ancien "
    "écran de calibration, qui mélangeait des fenêtres d'un même essai entre apprentissage et "
    "test et se gonflait ainsi de 10 à 16 points.\n"
    "Repère : sur la seule séance de référence du projet, mesurée honnêtement, 40 % à 3 classes "
    "(pas significatif) et 63 % à 2 classes. Le Motor Imagery ne marche pas également bien chez "
    "tout le monde, et une séance modeste est un résultat ordinaire, pas une faute."
)


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
        # (phase, essai, etape) du dernier top JOUÉ — pour ne jamais rejouer sur un simple
        # rafraîchissement (la page est mise à jour ~10 fois par seconde), cf. _maybe_beep.
        self._derniere_cue_sonnee = None

        entete = QHBoxLayout()
        self.bouton_retour = QPushButton("← Modes")
        self.bouton_retour.clicked.connect(self.retour)
        entete.addWidget(self.bouton_retour)
        entete.addWidget(QLabel(f"<b>{self.calib.get('label') or spec['label']}</b>"))
        entete.addStretch(1)

        # --- écran 1 : avant (ou de nouveau, une fois la séance TERMINÉE) --------------------
        self.bloc_avant = QGroupBox("Avant de commencer")
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
                f"⚠ pas de son sur cette machine ({console.beeps.raison}) — la séance se déroule "
                f"quand même ; suis la consigne écrite à l'écran, sans les tops.")
        self.formulaire = ParamsForm(list(self.calib.get("params") or ()))
        self.duree = QLabel("")
        self.duree.setWordWrap(True)
        self.duree.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        self.bouton_commencer = QPushButton("Commencer")
        self.bouton_commencer.clicked.connect(self._commencer)
        avant = QVBoxLayout(self.bloc_avant)
        avant.addWidget(self.briefing)
        avant.addWidget(self.audio_avertissement)
        avant.addWidget(self.formulaire)
        avant.addWidget(self.duree)
        avant.addWidget(self.bouton_commencer)

        # --- écran 2 : pendant ----------------------------------------------------------------
        self.bloc_pendant = QGroupBox("Séance en cours")
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
        self.barre = QProgressBar()
        self.barre.setTextVisible(False)
        self.bouton_abandon = QPushButton("Abandonner")
        self.bouton_abandon.clicked.connect(self._abandonner)
        pendant = QVBoxLayout(self.bloc_pendant)
        pendant.addWidget(self.consigne)
        pendant.addWidget(self.classe_cuee)
        pendant.addWidget(self.rappel)
        pendant.addWidget(self.decompte)
        pendant.addWidget(self.progression)
        pendant.addWidget(self.barre)
        # « Abandonner » doit exister pendant TOUTE la séance (chauffe, échauffement, essais,
        # entraînement) : un étudiant qui a mal placé une électrode doit pouvoir sortir sans
        # tuer la console. Il vit dans ce bloc, qui reste visible sur toute cette plage — cf.
        # `update_from`, où « pendant » couvre tout sauf « fini »/« annule ».
        pendant.addWidget(self.bouton_abandon)

        # --- écran 3 : après ------------------------------------------------------------------
        self.bloc_apres = QGroupBox("Résultat")
        self.resultat = QLabel("")
        self.resultat.setWordWrap(True)
        self.resultat.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.details = QLabel("")
        self.details.setWordWrap(True)
        self.honnetete = QLabel(HONNETETE)
        self.honnetete.setWordWrap(True)
        self.honnetete.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        apres = QVBoxLayout(self.bloc_apres)
        apres.addWidget(self.resultat)
        apres.addWidget(self.details)
        apres.addWidget(self.honnetete)

        layout = QVBoxLayout(self)
        # Ordre choisi pour la lecture, pas pour la construction : « pendant » et « après » ne
        # sont jamais visibles en même temps que ne serait-ce que l'un des deux autres blocs sauf
        # « avant » (cf. `update_from`), donc seul l'ordre AVANT/APRÈS compte vraiment — et un
        # étudiant qui revient sur cette page après une séance veut lire son résultat AVANT de
        # retomber sur le briefing d'une nouvelle séance.
        layout.addLayout(entete)
        layout.addWidget(self.bloc_pendant)
        layout.addWidget(self.bloc_apres)
        layout.addWidget(self.bloc_avant)
        layout.addStretch(1)

        # État initial cohérent avant le premier `update_from` : rien n'a encore tourné.
        self.bloc_avant.setVisible(True)
        self.bloc_pendant.setVisible(False)
        self.bloc_apres.setVisible(False)

    def _commencer(self):
        """Émet `start_calibration` avec les réglages choisis. Le moteur valide, refuse ou
        accepte — cette page ne devine jamais laquelle des deux, elle envoie et attend l'état."""
        self.console.commande("start_calibration", id=self.mode_id,
                              params=self.formulaire.values())

    def _abandonner(self):
        """Émet `cancel_calibration`. Aucun `id` à fournir : le moteur ne tient qu'UNE
        calibration à la fois, la sienne, quel que soit le mode qui l'a démarrée."""
        self.console.commande("cancel_calibration")

    def _maybe_beep(self, calib_state):
        """Joue le top de la classe cuée UNE SEULE fois par mise en route, jamais de plus.

        La clé retenue est `(phase, essai, etape)` : elle ne bouge PAS entre deux
        rafraîchissements de la MÊME étape (la page est repeinte ~10 fois par seconde), et
        change dès qu'une nouvelle étape « cue » commence. Elle est remise à zéro dès que la
        séance n'est plus « en cours » (cf. `update_from`), pour qu'une séance ultérieure sonne
        de nouveau son tout premier essai.
        """
        cle = (calib_state.get("phase"), calib_state.get("essai"), calib_state.get("etape"))
        if calib_state.get("etape") == "cue" and cle != self._derniere_cue_sonnee:
            self.console.beeps.jouer(calib_state.get("classe"))
            self._derniere_cue_sonnee = cle

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
        # Changer la durée en cours de route n'aurait aucun effet sur une séance déjà lancée :
        # un champ actif sans effet est un mensonge. Réactivé dès que la séance est TERMINÉE
        # (pas seulement absente), pour permettre d'en relancer une autre sans naviguer ailleurs.
        self.formulaire.setEnabled(not en_cours)
        self.bouton_commencer.setEnabled(not en_cours)

        if calib_state is not None:
            minutes = calib_state.get("duree_estimee_s", 0.0) / 60.0
            self.duree.setText(
                f"Durée estimée de cette configuration (chauffe et échauffement compris) : "
                f"≈ {minutes:.1f} min, pour {calib_state.get('total', 0)} essais enregistrés.")
        else:
            self.duree.setText("")

        if not en_cours:
            self._derniere_cue_sonnee = None      # une future séance repart sonner de zéro

        if en_cours:
            self._maybe_beep(calib_state)
            self.consigne.setText(calib_state.get("instruction") or "")
            self.classe_cuee.setText(calib_state.get("classe") or "")
            self.rappel.setText(calib_state.get("rappel") or "")
            self.decompte.setText(f"{float(calib_state.get('restant_s', 0.0)):.1f} s")
            essai = int(calib_state.get("essai", 0))
            total = int(calib_state.get("total", 0))
            self.progression.setText(f"essai {essai} sur {total}")
            self.barre.setRange(0, max(total, 1))
            self.barre.setValue(min(essai, max(total, 1)))

        if termine:
            resultat = calib_state.get("resultat")
            if resultat is not None:
                # `cv_groupee` — jamais `cv_naive` (gonflée de 10 à 16 points, cf. HONNETETE) —
                # et le niveau du hasard À CÔTÉ : un « 40 % » seul ne veut rien dire.
                cv = float(resultat.get("cv_groupee") or 0.0)
                hasard = float(resultat.get("hasard") or 0.0)
                self.resultat.setText(
                    f"{resultat.get('verdict', '')} — accuracy honnête (validation croisée par "
                    f"essai) : {cv*100:.1f} % (hasard {hasard*100:.0f} %)")
                self.details.setText(
                    f"Modèle : {resultat.get('nom', '')}\n"
                    f"{resultat.get('n_essais', 0)} essais enregistrés, "
                    f"{resultat.get('n_fenetres', 0)} fenêtres d'entraînement — classes : "
                    f"{', '.join(resultat.get('classes') or [])}")
                self.honnetete.setVisible(True)
            else:
                self.resultat.setText(
                    f"Calibration abandonnée : "
                    f"{calib_state.get('probleme', '') or 'aucun modèle produit'}")
                self.details.setText("")
                # Rien à mettre en garde : sans accuracy, il n'y a rien à sur-interpréter.
                self.honnetete.setVisible(False)
