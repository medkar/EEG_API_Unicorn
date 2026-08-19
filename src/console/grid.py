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
# `Z_MIN` n'est PLUS importé, et c'est le correctif : c'était le seuil du SSVEP, servant de
# repli à des modes qui n'ont pas de seuil du tout (cf. `ModeTile._apercu_scores`). Ne pas le
# réintroduire ici — une constante d'un mode ne met pas à l'échelle la sortie d'un autre.
from core.config import NEURO_Z_SPAN  # noqa: E402

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
        # Démarrer / arrêter. Le moteur possède déjà les deux commandes et les valide (mode
        # inconnu, déjà démarré, réglages invalides) : la tuile ne fait que les poster. Elle
        # n'affiche AUCUN état déduit — c'est le prochain `snapshot()` qui dira ce qui s'est
        # réellement passé.
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
            self._apercu_scores(sortie)
        elif "probas" in sortie:
            # Motor Imagery : une probabilité par classe, déjà bornée à 1 — pas de seuil à
            # dépasser pour l'échelle du dessin, contrairement au z du SSVEP.
            self.apercu.set_values(list(sortie["probas"].values()), span=1.0,
                                   retenue=sortie.get("intent_index", -1))
        elif "z" in sortie:
            self.apercu.set_values(list(sortie["z"].values()), span=NEURO_Z_SPAN, centre=True)
        elif "error" in sortie:
            # ⚠️ Correction de revue (tour 1, tâche 4) : cette clé n'existait dans AUCUNE des
            # branches ci-dessus, donc l'ErrP tombait toujours dans le `else` — l'aperçu vivant
            # restait vide en permanence. `error < 0` (pas de verdict) : `score`/`threshold`
            # valent 0.0 par CONVENTION, jamais une mesure (cf. `ErrPRuntime._traiter_feedback`)
            # — les montrer fabriquerait un chiffre, donc rien plutôt qu'un faux zéro.
            if sortie.get("error", -1) < 0:
                self.apercu.set_values([])
            else:
                score = sortie.get("score", 0.0)
                seuil = sortie.get("threshold", 0.0)
                # Échelle qui s'adapte à SA PROPRE amplitude, jamais NEURO_Z_SPAN (un z n'a rien
                # à voir avec un log-odds) ni un axe fixe inventé — le même piège que le P300
                # rendu comme un SSVEP (cf. `live_views.ActiveView`).
                self.apercu.set_values([score, seuil],
                                       span=max(abs(score), abs(seuil), 1.0), centre=True)
        else:
            self.apercu.set_values([])

    def _apercu_scores(self, sortie):
        """Un score par cible. DEUX échelles, choisies sur ce que la sortie DÉCLARE.

        ⚠️ Correction de revue (tour 2) : cette branche appliquait `max(sortie.get("threshold",
        Z_MIN), 1.0)` à tout le monde. Or la sortie du P300 n'a PAS de clé `threshold`, et c'est
        délibéré — le moteur prend l'argmax, il ne compare ces scores à rien (cf.
        `live_views.ActiveView._update_selection`). Le repli `Z_MIN` (le seuil du SSVEP, 2,5)
        s'appliquait donc systématiquement à des LOG-ODDS, et `centre=False` écrase à zéro tout
        ce qui est négatif : sur une manche P300 ordinaire (les scores sont négatifs le plus
        souvent — une cible flashe une fois sur six), la tuile montrait SIX MOIGNONS DE 2 PX,
        dont un bleu. L'étudiant y lisait « la sélection n'a aucune preuve derrière elle », ce
        qui est faux : c'est l'ÉCART 1er-2e qui décide, et il peut être franc. La même tuile,
        ouverte sur sa page, montrait un classement lisible : la tuile et la page se
        contredisaient sur les mêmes données.

        C'est exactement le défaut que le chantier précédent a corrigé SUR LA PAGE, jamais sur la
        tuile. Il est corrigé ici de la même façon, et pour la même raison : sans `threshold`,
        aucune échelle absolue n'existe, donc on montre le CLASSEMENT.
        """
        scores = [float(s) for s in (sortie.get("scores") or [])]
        seuil = sortie.get("threshold")
        retenue = sortie.get("target_index", -1)
        if seuil is not None:
            # SSVEP : un z, comparé à un seuil publié. L'échelle absolue a un sens.
            self.apercu.set_values(scores, span=max(float(seuil), 1.0), retenue=retenue)
            return
        # P300 (et tout futur mode qui ACCUMULE des preuves sans seuil) : échelle RELATIVE,
        # recalculée à chaque manche, comme `_update_selection` le fait sur la page. `etendue
        # <= 0` (scores tous égaux, ou une seule cible) laisse tout à mi-hauteur plutôt que de
        # désigner un gagnant qui n'en est pas un.
        bas, haut = (min(scores), max(scores)) if scores else (0.0, 0.0)
        etendue = haut - bas
        valeurs = [0.5 if etendue <= 0 else (s - bas) / etendue for s in scores]
        self.apercu.set_values(valeurs, span=1.0, retenue=retenue)


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
    if "error" in sortie:
        # ⚠️ Correction de revue (tour 1, tâche 4) : sans cette branche, le résumé retombait sur
        # `params`/`""`, donc sur `spec["summary"]` (le texte STATIQUE du mode) — jamais ce que ce
        # feedback précis vient de décider. Le verdict ne se montre JAMAIS seul : ce détecteur
        # n'attrape qu'une partie des erreurs, `pdf['tpr']` le rappelle à chaque ligne.
        error = sortie.get("error", -1)
        if sortie.get("artifact"):
            return "artefact — fenêtre rejetée"
        if error < 0:
            return "pas de verdict (époque hors tampon)"
        pdf = mode_state.get("point_de_fonctionnement") or {}
        verdict = "ERREUR détectée" if error == 1 else "correct"
        # `.get` ici aussi, comme vingt-cinq lignes plus haut : `if pdf` protège du dict VIDE,
        # pas du dict INCOMPLET. Un `point_de_fonctionnement` qui évoluerait (une clé `auc`
        # ajoutée, `tpr` renommé `tpr_oof`) ferait tomber `ModeGrid.update_from` sur un
        # KeyError — donc TOUTE la grille, pas seulement cette tuile, en pleine séance.
        taux = f" · attrape {pdf.get('tpr', 0.0):.0%} des erreurs" if pdf else ""
        return f"{verdict} · score {sortie.get('score', 0.0):+.2f}{taux}"
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
