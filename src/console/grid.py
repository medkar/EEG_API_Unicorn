"""La grille : une tuile par mode, l'état du produit d'un seul coup d'œil.

Elle a cessé d'être un menu. Une tuile porte les quatre choses qu'on veut savoir sans cliquer :
l'état réel, un aperçu vivant de ce que le mode produit, s'il est publié, et pour les non publiés
POURQUOI (« demande des marqueurs », « verrouillé à la frame »).

Les modes que le moteur ne sait pas faire sont affichés, grisés, avec leur raison. Sans eux, un
étudiant croirait que le produit fait trois choses et ne saurait pas qu'un décodeur c-VEP validé
l'attend dans `src/research/app.py`.
"""

import os
import sys

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from console import PHASES_FR  # noqa: E402
from core.config import NEURO_Z_SPAN, Z_MIN  # noqa: E402

COLONNES = 4
BLEU, GRIS = QColor("#4c8dff"), QColor("#8a8f9c")


class MiniBars(QWidget):
    """Quelques barres, dessinées à la main. L'aperçu vivant d'une tuile.

    Au QPainter plutôt qu'en pyqtgraph : une tuile en montre trois ou quatre, elles sont
    redessinées 10 fois par seconde, et un widget de tracé complet par tuile coûterait cher
    pour trois rectangles.

    **Deux rendus, choisis par la famille du mode, comme les vues de la page.** Un mode ACTIF a
    une décision : la barre mise en avant est celle que le MOTEUR a retenue, jamais un maximum
    recalculé ici. Un mode PASSIF n'a aucune décision et ses valeurs sont signées : elles se
    dessinent de part et d'autre d'un axe, et rien n'est mis en avant. Colorier le plus grand
    indice comme une sélection laisserait croire qu'un z d'engagement est une commande — le
    contresens exact que le contrat des flux cherche à empêcher.
    """

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(26)
        self._values, self._span = [], 1.0
        self._retenue, self._centre = -1, False

    def set_values(self, values, span=1.0, retenue=-1, centre=False):
        """`retenue` : l'indice choisi par le MOTEUR (-1 = aucun). `centre` : valeurs signées."""
        self._values = [float(v) for v in (values or [])]
        self._span = max(float(span), 1e-6)
        self._retenue, self._centre = int(retenue), bool(centre)
        self.update()

    def paintEvent(self, _event):
        if not self._values:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        largeur = self.width() / max(len(self._values), 1)
        haut, demi = self.height(), self.height() / 2.0
        for i, valeur in enumerate(self._values):
            part = max(-1.0, min(valeur / self._span, 1.0))
            if self._centre:
                # Passif : un -3 et un +3 ne doivent PAS se ressembler, c'est tout ce que
                # l'indice dit. On dessine donc de part et d'autre de l'axe médian.
                h = part * demi
                y, hauteur = (demi - h, h) if h >= 0 else (demi, -h)
            else:
                # Actif : un score négatif veut dire « aucune preuve », donc rien à montrer.
                hauteur = max(part, 0.0) * haut
                y = haut - hauteur
            painter.fillRect(int(i * largeur) + 2, int(y), int(largeur) - 4,
                             max(2, int(hauteur)), BLEU if i == self._retenue else GRIS)


class ModeTile(QFrame):
    """Une tuile. Elle ne décide de rien : elle rend un `ModeSpec` et un état."""

    ouvrir = Signal(str)
    publier = Signal(str, bool)
    demarrer = Signal(str, bool)     # (id, on) — on=True pour démarrer, False pour arrêter

    def __init__(self, spec):
        super().__init__()
        self.spec = spec
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumHeight(130)

        self.titre = QLabel(f"<b>{spec['label']}</b>")
        self.etat = QLabel("")
        self.detail = QLabel(spec["summary"])
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        self.apercu = MiniBars()
        self.publie = QCheckBox("publié")
        self._arrete = True
        self.demarrage = QPushButton("Démarrer")
        self.demarrage.clicked.connect(
            lambda: self.demarrer.emit(self.spec["id"], self._arrete))
        self.bouton = QPushButton("Ouvrir")
        self.bouton.clicked.connect(lambda: self.ouvrir.emit(self.spec["id"]))
        self.publie.toggled.connect(lambda on: self.publier.emit(self.spec["id"], on))

        haut = QHBoxLayout()
        haut.addWidget(self.titre)
        haut.addStretch(1)
        haut.addWidget(self.etat)
        bas = QHBoxLayout()
        bas.addWidget(self.publie)
        bas.addStretch(1)
        bas.addWidget(self.demarrage)
        bas.addWidget(self.bouton)

        layout = QVBoxLayout(self)
        layout.addLayout(haut)
        layout.addWidget(self.detail)
        layout.addWidget(self.apercu, 1)
        layout.addLayout(bas)

        if spec["status"] != "moteur":
            # Grisée mais LISIBLE, et surtout : elle dit pourquoi.
            self.setEnabled(False)
            self.detail.setText(spec["unavailable"])
            self.etat.setText({"appli_pygame": "appli pygame", "prevu": "prévu"}.get(spec["status"], spec["status"]))
            self.publie.hide()
            self.demarrage.hide()
            self.bouton.hide()

    def update_from(self, mode_state):
        """`mode_state` = None quand le mode n'est pas démarré."""
        if self.spec["status"] != "moteur":
            return
        if mode_state is None:
            self._arrete = True
            self.demarrage.setText("Démarrer")
            self.etat.setText("arrêté")
            self.publie.setChecked(False)
            self.publie.setEnabled(False)
            self.apercu.set_values([])
            self.detail.setText(self.spec["summary"])
            return

        libelle = PHASES_FR
        self.etat.setText(libelle.get(mode_state["phase"], mode_state["phase"]))
        self.publie.setEnabled(True)
        self.publie.blockSignals(True)     # sinon régler la case RÉÉMET la commande, en boucle
        self.publie.setChecked(bool(mode_state["published"]))
        self.publie.blockSignals(False)
        self._arrete = False
        self.demarrage.setText("Arrêter")

        if mode_state["instruction"]:
            self.detail.setText(mode_state["instruction"])
        else:
            self.detail.setText(_resume(mode_state) or self.spec["summary"])

        sortie = mode_state.get("output") or {}
        if "scores" in sortie:
            self.apercu.set_values(sortie["scores"],
                                   span=max(sortie.get("threshold", Z_MIN), 1.0),
                                   retenue=sortie.get("target_index", -1))
        elif "probas" in sortie:
            # Motor Imagery : une probabilité par classe, déjà bornée à 1 — pas de seuil à
            # dépasser pour l'échelle du dessin, contrairement au z du SSVEP.
            self.apercu.set_values(list(sortie["probas"].values()), span=1.0,
                                   retenue=sortie.get("intent_index", -1))
        elif "z" in sortie:
            self.apercu.set_values(list(sortie["z"].values()), span=NEURO_Z_SPAN, centre=True)
        else:
            self.apercu.set_values([])


def _resume(mode_state):
    """Une ligne : ce que le mode produit en ce moment. "" si rien de parlant."""
    sortie = mode_state.get("output") or {}
    if "scores" in sortie:
        # `.get` et pas `[...]` : cette ligne tourne 10 fois par seconde dans le rafraîchissement
        # de la grille. Un mode actif qui publierait des scores sans cible nommée y ferait tomber
        # TOUTE l'interface sur un KeyError, pas seulement sa propre tuile.
        index = sortie.get("target_index", -1)
        if sortie.get("artifact"):
            return "artefact — fenêtre rejetée"
        return "aucune cible" if index < 0 else f"cible {index} · {sortie.get('freq_hz', 0):g} Hz"
    if "probas" in sortie:
        # Motor Imagery : pas de "cible", une INTENTION — les deux mots ne sont pas
        # interchangeables (cf. DecodedMIPublisher), donc pas le même résumé que le SSVEP.
        index = sortie.get("intent_index", -1)
        return ("vote non conclu" if index < 0
                else f"intention {sortie.get('label', '')} · {sortie.get('confidence', 0):.2f}")
    if "z" in sortie:
        return "  ".join(f"{k} {v:+.1f}" for k, v in sortie["z"].items())
    params = mode_state.get("params") or {}
    if "freqs" in params:
        return " · ".join(f"{f:g} Hz" for f in params["freqs"])
    return ""


class ModeGrid(QWidget):
    """Toutes les tuiles, construites UNE FOIS depuis le catalogue, mises à jour ensuite."""

    ouvrir = Signal(str)
    publier = Signal(str, bool)
    demarrer = Signal(str, bool)

    def __init__(self, catalog):
        super().__init__()
        self.tuiles = {}
        layout = QGridLayout(self)
        layout.setSpacing(10)
        for i, spec in enumerate(catalog):
            tuile = ModeTile(spec)
            tuile.ouvrir.connect(self.ouvrir)
            tuile.publier.connect(self.publier)
            tuile.demarrer.connect(self.demarrer)
            self.tuiles[spec["id"]] = tuile
            layout.addWidget(tuile, i // COLONNES, i % COLONNES)
        layout.setRowStretch(len(catalog) // COLONNES + 1, 1)

    def update_from(self, state):
        etats = state.get("modes_state") or {}
        for mode_id, tuile in self.tuiles.items():
            tuile.update_from(etats.get(mode_id))
