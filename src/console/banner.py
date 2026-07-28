"""Le bandeau permanent : liaison casque, σ par voie, référence décrochée.

Il ne disparaît sur aucun écran, et c'est délibéré. Une référence décrochée rend une séance
entière inexploitable **sans autre symptôme** : les 8 voies mesurent alors la même référence
flottante avec des amplitudes parfaitement plausibles, et un écran de contrôle affiche 8 barres
rassurantes sur un signal vide. Ça a coûté 3,4 minutes d'enregistrement dans le vide le
2026-07-20, sans le moindre avertissement.
"""

import os
import sys

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Banner(QWidget):
    """Une ligne, trois informations, jamais masquée."""

    def __init__(self):
        super().__init__()
        self.liaison = QLabel("moteur non démarré")
        self.sigmas = QLabel("")
        self.alarme = QLabel("")
        self.alarme.setStyleSheet("color: #e2603f; font-weight: bold;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        for widget in (self.liaison, self.sigmas, self.alarme):
            layout.addWidget(widget)
        layout.addStretch(1)

    def update_from(self, state):
        board = state.get("board", "?")
        casque = "board de test" if board == "synthetic" else "Unicorn"
        actifs = len(state.get("modes") or ())
        self.liaison.setText(f"{casque} · {state.get('fs_hz', 0):.0f} Hz · "
                             f"{actifs} mode{'s' if actifs > 1 else ''} actif"
                             f"{'s' if actifs > 1 else ''}")

        quality = state.get("quality")
        if not quality:
            self.sigmas.setText("σ : en attente du tampon…")
            self.alarme.setText("")
            return

        sigmas = quality.get("sigmas", [])
        valeurs = [v for v in sigmas if v is not None]
        verdicts = quality.get("verdicts", [])
        mortes = sum(1 for v in verdicts if v == "morte")
        saturees = sum(1 for v in verdicts if v == "saturée")
        detail = f"σ {min(valeurs):.1f}–{max(valeurs):.1f} µV sur {len(valeurs)} voies" \
            if valeurs else "σ indisponible"
        if mortes:
            detail += f" · {mortes} morte{'s' if mortes > 1 else ''}"
        if saturees:
            detail += f" · {saturees} saturée{'s' if saturees > 1 else ''}"
        self.sigmas.setText(detail)

        if quality.get("reference_lost"):
            self.alarme.setText(
                f"⚠ RÉFÉRENCE DÉCROCHÉE (corrélation inter-voies "
                f"{quality.get('common_mode')}) — remets les MASTOÏDES : "
                f"tout ce qui suit est inexploitable")
        else:
            self.alarme.setText("")
