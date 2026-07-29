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
from console import live_views  # noqa: E402
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
        bouton = QPushButton("← Modes")
        bouton.clicked.connect(self.retour)
        entete.addWidget(bouton)
        entete.addWidget(QLabel(f"<b>{spec['label']}</b> — {spec['summary']}"))
        entete.addStretch(1)
        self.etat = QLabel("")
        entete.addWidget(self.etat)

        self.vue = live_views.build(spec["family"])
        bloc_sortie = QGroupBox("Sortie en direct")
        QVBoxLayout(bloc_sortie).addWidget(self.vue)

        self.reglages = QGroupBox("Réglages")
        QVBoxLayout(self.reglages).addWidget(
            QLabel("aucun réglage pour ce mode"))   # remplacé à la tâche 14

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

    def _copier(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.extrait.toPlainText())

    def _remplir_extrait(self, params):
        """L'extrait est regénéré quand les réglages changent : les voies SSVEP en dépendent."""
        spec = registry.get(self.mode_id)
        texte = client_snippet(spec, params)
        self.extrait.setPlainText(texte or "ce mode ne publie aucun flux")
        voies = ", ".join(spec.channels_for(params or spec.defaults()))
        self.flux.setText(f"{self.spec['stream'] or '—'} · voies : {voies}"
                          if self.spec["stream"] else "aucun flux publié")

    def update_from(self, state):
        mode_state = (state.get("modes_state") or {}).get(self.mode_id)
        if mode_state is None:
            self.etat.setText("arrêté")
            self.vue.update_from(None)
            return
        libelle = {"warmup": "chauffe", "rest": "repos", "running": "décode"}
        self.etat.setText(libelle.get(mode_state["phase"], mode_state["phase"])
                          + ("" if mode_state["published"] else " · non publié"))
        self.vue.update_from(mode_state)
        params = mode_state.get("params") or {}
        if params != self._derniers_params:
            self._derniers_params = dict(params)
            self._remplir_extrait(params)
