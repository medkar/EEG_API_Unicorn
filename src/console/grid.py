"""La grille : une tuile par mode, l'état du produit d'un seul coup d'œil.

Elle a cessé d'être un menu. Une tuile porte les quatre choses qu'on veut savoir sans cliquer :
l'état réel, un aperçu vivant de ce que le mode produit, s'il est publié, et pour les non publiés
POURQUOI (« demande des marqueurs », « verrouillé à la frame »).

Les modes que le moteur ne sait pas faire sont affichés, grisés, avec leur raison. Sans eux, un
étudiant croirait que le produit fait trois choses et ne saurait pas qu'un décodeur c-VEP validé
l'attend dans `src/research/app.py`.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

COLONNES = 4
VERT, BLEU, GRIS = QColor("#4ac97e"), QColor("#4c8dff"), QColor("#8a8f9c")


class MiniBars(QWidget):
    """Quelques barres, dessinées à la main. L'aperçu vivant d'une tuile.

    Au QPainter plutôt qu'en pyqtgraph : une tuile en montre trois ou quatre, elles sont
    redessinées 10 fois par seconde, et un widget de tracé complet par tuile coûterait cher
    pour trois rectangles.
    """

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(26)
        self._values, self._span = [], 1.0

    def set_values(self, values, span=1.0):
        self._values = [float(v) for v in (values or [])]
        self._span = max(float(span), 1e-6)
        self.update()

    def paintEvent(self, _event):
        if not self._values:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        largeur = self.width() / max(len(self._values), 1)
        haut = self.height()
        meilleur = max(range(len(self._values)), key=lambda i: self._values[i])
        for i, valeur in enumerate(self._values):
            part = min(abs(valeur) / self._span, 1.0)
            h = max(2.0, part * haut)
            painter.fillRect(int(i * largeur) + 2, int(haut - h),
                             int(largeur) - 4, int(h),
                             BLEU if i == meilleur else GRIS)


class ModeTile(QFrame):
    """Une tuile. Elle ne décide de rien : elle rend un `ModeSpec` et un état."""

    ouvrir = Signal(str)
    publier = Signal(str, bool)

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
            self.etat.setText({"appli_pygame": "appli pygame", "prevu": "prévu"}[spec["status"]])
            self.publie.hide()
            self.bouton.hide()

    def update_from(self, mode_state):
        """`mode_state` = None quand le mode n'est pas démarré."""
        if self.spec["status"] != "moteur":
            return
        if mode_state is None:
            self.etat.setText("arrêté")
            self.publie.setChecked(False)
            self.publie.setEnabled(False)
            self.apercu.set_values([])
            self.detail.setText(self.spec["summary"])
            return

        libelle = {"warmup": "chauffe", "rest": "repos", "running": "décode"}
        self.etat.setText(libelle.get(mode_state["phase"], mode_state["phase"]))
        self.publie.setEnabled(True)
        self.publie.blockSignals(True)     # sinon régler la case RÉÉMET la commande, en boucle
        self.publie.setChecked(bool(mode_state["published"]))
        self.publie.blockSignals(False)

        if mode_state["instruction"]:
            self.detail.setText(mode_state["instruction"])
        else:
            self.detail.setText(_resume(mode_state) or self.spec["summary"])

        sortie = mode_state.get("output") or {}
        if "scores" in sortie:
            self.apercu.set_values(sortie["scores"], span=max(sortie.get("threshold", 2.5), 1.0))
        elif "z" in sortie:
            self.apercu.set_values(list(sortie["z"].values()), span=3.0)
        else:
            self.apercu.set_values([])


def _resume(mode_state):
    """Une ligne : ce que le mode produit en ce moment. "" si rien de parlant."""
    sortie = mode_state.get("output") or {}
    if "scores" in sortie:
        index = sortie["target_index"]
        if sortie.get("artifact"):
            return "artefact — fenêtre rejetée"
        return "aucune cible" if index < 0 else f"cible {index} · {sortie['freq_hz']:g} Hz"
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

    def __init__(self, catalog):
        super().__init__()
        self.tuiles = {}
        layout = QGridLayout(self)
        layout.setSpacing(10)
        for i, spec in enumerate(catalog):
            tuile = ModeTile(spec)
            tuile.ouvrir.connect(self.ouvrir)
            tuile.publier.connect(self.publier)
            self.tuiles[spec["id"]] = tuile
            layout.addWidget(tuile, i // COLONNES, i % COLONNES)
        layout.setRowStretch(len(catalog) // COLONNES + 1, 1)

    def update_from(self, state):
        etats = state.get("modes_state") or {}
        for mode_id, tuile in self.tuiles.items():
            tuile.update_from(etats.get(mode_id))
