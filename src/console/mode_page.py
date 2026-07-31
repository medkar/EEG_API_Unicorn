"""La page d'un mode : sortie en direct · réglages · brancher un client.

Les trois blocs sont générés depuis le `ModeSpec`. Rien ici ne sait qu'un SSVEP a des fréquences
ou qu'un neuro a un lissage : c'est le contrat qui le dit. C'est ce qui permettra aux chantiers 2
et 3 d'enrichir les blocs sans toucher à la coquille.
"""

import os
import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from console import PHASES_FR, live_views  # noqa: E402
from console.params_form import ParamsForm  # noqa: E402
from core.lsl_io import stream_name  # noqa: E402
from core.modes import registry  # noqa: E402
from core.modes.contract import client_snippet  # noqa: E402


class ModePage(QWidget):
    """Une page par mode, construite une fois, mise à jour à chaque rafraîchissement."""

    retour = Signal()

    def __init__(self, spec, console):
        super().__init__()
        self.spec = spec
        self.console = console
        self.mode_id = spec["id"]
        self._derniers_params = None

        entete = QHBoxLayout()
        self.bouton_retour = QPushButton("← Modes")
        self.bouton_retour.clicked.connect(self.retour)
        entete.addWidget(self.bouton_retour)
        entete.addWidget(QLabel(f"<b>{spec['label']}</b> — {spec['summary']}"))
        # Le bouton n'existe que si le CONTRAT dit que ce mode se calibre depuis la console. Rien
        # ici ne sait qu'un MI s'entraîne et qu'un SSVEP non : c'est `Calib.kind` qui le dit.
        calib = spec.get("calibration") or {}
        self.bouton_calibrer = None
        if calib.get("kind") == "console":
            self.bouton_calibrer = QPushButton("Calibrer")
            self.bouton_calibrer.clicked.connect(
                lambda: console.show_calibration(self.mode_id))
            entete.addWidget(self.bouton_calibrer)
        entete.addStretch(1)
        self.etat = QLabel("")
        entete.addWidget(self.etat)

        self.vue = live_views.build(spec["family"], spec["channels"])
        if hasattr(self.vue, "set_source") and console.engine is not None:
            # L'accesseur PUBLIC du moteur, qui rend une copie. Jamais `engine.recent`.
            self.vue.set_source(console.engine.recent_window)
        bloc_sortie = QGroupBox("Sortie en direct")
        QVBoxLayout(bloc_sortie).addWidget(self.vue)

        self.formulaire = ParamsForm(spec["params"])
        self.formulaire.appliquer.connect(self._appliquer)
        self.formulaire.proposer.connect(self._proposer)
        self.reglages = QGroupBox("Réglages")
        QVBoxLayout(self.reglages).addWidget(self.formulaire)

        self.client = QGroupBox("Brancher un client")
        self.extrait = QPlainTextEdit()
        self.extrait.setReadOnly(True)
        self.extrait.setMaximumHeight(220)
        self.flux = QLabel("")
        self.copier = QPushButton("Copier")
        self.copier.clicked.connect(self._copier)
        client_layout = QVBoxLayout(self.client)
        client_layout.addWidget(self.flux)
        client_layout.addWidget(self.extrait)
        client_layout.addWidget(self.copier)

        layout = QVBoxLayout(self)
        layout.addLayout(entete)
        layout.addWidget(bloc_sortie, 1)
        layout.addWidget(self.reglages)
        layout.addWidget(self.client)

        self._remplir_extrait(None)

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

    def _copier(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.extrait.toPlainText())

    def _remplir_extrait(self, params):
        """L'extrait est regénéré quand les réglages changent : les voies SSVEP en dépendent."""
        spec = registry.get(self.mode_id)
        texte = client_snippet(spec, params)
        self.extrait.setPlainText(texte or "ce mode ne publie aucun flux")
        voies = ", ".join(spec.channels_for(params or spec.defaults()))
        # Le nom COMPLET, pas le suffixe : c'est celui-là qu'un `resolve_byprop` demande. Afficher
        # « decoded_ssvep » enverrait l'étudiant chercher un flux qui n'existe pas sous ce nom.
        self.flux.setText(f"{stream_name(self.spec['stream'])} · voies : {voies}"
                          if self.spec["stream"] else "aucun flux publié")

    def update_from(self, state):
        mode_state = (state.get("modes_state") or {}).get(self.mode_id)
        if mode_state is None:
            self.etat.setText("arrêté")
            self.vue.update_from(None)
            # Le bloc « brancher un client » doit le dire AUSSI. L'extrait reste lisible — c'est
            # ce qu'on vient copier — mais annoncer un nom de flux sans réserve enverrait
            # l'étudiant s'abonner à quelque chose que plus personne ne publie.
            self.flux.setText("mode ARRÊTÉ — ce flux n'est pas publié en ce moment")
            self._derniers_params = None      # forcer la régénération au redémarrage
            return
        libelle = PHASES_FR
        self.etat.setText(libelle.get(mode_state["phase"], mode_state["phase"])
                          + ("" if mode_state["published"] else " · non publié"))
        self.vue.update_from(mode_state)
        params = mode_state.get("params") or {}
        if params != self._derniers_params:
            self._derniers_params = dict(params)
            self._remplir_extrait(params)
            self.formulaire.set_values(params)

    def rafraichir_choix(self):
        """Recharge les listes de choix DYNAMIQUES de ce mode (les modèles entraînés).

        Appelée sur ÉVÉNEMENT — entrée dans la page, retour d'une calibration — jamais dans le
        rafraîchissement périodique : résoudre ces choix lit le disque, et le faire dix fois par
        seconde a déjà coûté 30 % d'un cœur à ce projet.
        """
        spec = registry.get(self.mode_id)
        if spec is None:
            return
        for param in spec.params:
            if param.choices_fn is not None:
                self.formulaire.set_choices(param.key, param.choices_now())
