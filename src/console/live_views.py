"""Ce qu'un mode produit, rendu selon sa FAMILLE — pas selon son identifiant.

Un mode **actif** propose des cibles et un seuil : l'utilisateur choisit, il y a une bonne
réponse. Un mode **passif** rend des indices qui divergent autour d'un repos : il n'y a rien à
choisir, et aucune bonne réponse. Les afficher pareil laisserait croire qu'un z d'engagement est
une sélection, ce qui est exactement le contresens que le contrat des flux cherche à éviter.
"""

from PySide6.QtWidgets import (QFormLayout, QLabel, QProgressBar, QVBoxLayout, QWidget)


class ActiveView(QWidget):
    """Une barre par cible, plus le seuil de décision, plus la cible retenue.

    Le seuil est affiché À CÔTÉ des scores, et pas seulement la décision : c'est ce qui permet
    de dire si une non-détection vient d'un signal absent ou d'un seuil trop haut. Sans ça, une
    séance muette n'a qu'une explication apparente — « l'utilisateur fixe mal ».
    """

    def __init__(self):
        super().__init__()
        self.verdict = QLabel("en attente")
        self.verdict.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.seuil = QLabel("")
        self.seuil.setStyleSheet("color: #8a8f9c;")
        self.barres = QFormLayout()
        layout = QVBoxLayout(self)
        layout.addWidget(self.verdict)
        layout.addWidget(self.seuil)
        layout.addLayout(self.barres)
        layout.addStretch(1)
        self._barres = []

    def _assure(self, n, etiquettes):
        while len(self._barres) < n:
            barre = QProgressBar()
            barre.setRange(0, 100)
            barre.setTextVisible(False)
            self._barres.append((QLabel(""), barre))
            self.barres.addRow(self._barres[-1][0], barre)
        for i, (etiquette, _b) in enumerate(self._barres):
            etiquette.setText(etiquettes[i] if i < len(etiquettes) else "")

    def update_from(self, mode_state):
        sortie = (mode_state or {}).get("output") or {}
        if not sortie:
            self.verdict.setText(mode_state["instruction"] if mode_state else "en attente")
            return

        freqs = (mode_state.get("params") or {}).get("freqs") or []
        scores = sortie.get("scores") or []
        seuil = float(sortie.get("threshold", 2.5))
        self._assure(len(scores), [f"{f:g} Hz" for f in freqs])
        self.seuil.setText(f"échelle z · seuil {seuil:g} — un score au-dessus déclenche")

        # L'échelle du remplissage va jusqu'à 2× le seuil : une barre pleine à ras le seuil
        # laisserait croire qu'on est au maximum alors qu'on vient à peine de déclencher.
        for i, (_e, barre) in enumerate(self._barres):
            valeur = scores[i] if i < len(scores) else 0.0
            barre.setValue(int(max(0.0, min(valeur / (2 * seuil), 1.0)) * 100))

        index = sortie.get("target_index", -1)
        if sortie.get("artifact"):
            self.verdict.setText("ARTEFACT — fenêtre rejetée (mouvement ou clignement)")
        elif index < 0:
            self.verdict.setText(f"aucune cible (rien au-dessus de z={seuil:g})")
        else:
            self.verdict.setText(f"CIBLE {index} · {sortie.get('freq_hz', 0):g} Hz")


class PassiveView(QWidget):
    """Un indice par ligne, en ÉCART au repos. Aucune sélection, aucune bonne réponse.

    ⚠️ L'échelle est un z contre le repos du jour de CET utilisateur. `+1` veut dire « au-dessus
    de mon propre repos », pas « chargé ». Les trois indices dérivent du même calcul spectral et
    restent corrélés. C'est écrit sous les barres, pas dans une documentation que personne
    n'ouvrira : un affichage qui présenterait ça comme une mesure de fatigue mentirait.
    """

    SPAN = 3.0     # au-delà de ±3 z, la barre est pleine

    def __init__(self):
        super().__init__()
        self.etat = QLabel("en attente")
        self.barres = QFormLayout()
        self.avertissement = QLabel(
            "z contre TON repos du jour, mesuré au démarrage du mode. Ni comparable entre "
            "personnes, ni entre séances, ni absolu. À lire en TENDANCE.")
        self.avertissement.setWordWrap(True)
        self.avertissement.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        layout = QVBoxLayout(self)
        layout.addWidget(self.etat)
        layout.addLayout(self.barres)
        layout.addWidget(self.avertissement)
        layout.addStretch(1)
        self._barres = {}

    def update_from(self, mode_state):
        sortie = (mode_state or {}).get("output") or {}
        z = sortie.get("z") or {}
        if not z:
            self.etat.setText(mode_state["instruction"] if mode_state else "en attente")
            return

        for cle, valeur in z.items():
            if cle not in self._barres:
                barre = QProgressBar()
                barre.setRange(-100, 100)
                barre.setFormat("%v")
                self._barres[cle] = barre
                self.barres.addRow(QLabel(cle), barre)
            part = max(-1.0, min(float(valeur) / self.SPAN, 1.0))
            self._barres[cle].setValue(int(part * 100))

        artefacts = sortie.get("artifacts", 0)
        if sortie.get("artifact"):
            self.etat.setText(f"fenêtre rejetée ({sortie.get('reason', 'artefact')}) — "
                              f"les derniers z valides sont maintenus")
        else:
            self.etat.setText(f"{artefacts} fenêtre(s) rejetée(s) depuis le début du mode")


def build(family):
    """Le rendu qui convient à cette famille. Le brut a le sien, ajouté à la tâche 15."""
    return PassiveView() if family == "passif" else ActiveView()
