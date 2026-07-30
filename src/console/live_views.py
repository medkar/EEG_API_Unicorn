"""Ce qu'un mode produit, rendu selon sa FAMILLE — pas selon son identifiant.

Un mode **actif** propose des cibles et un seuil : l'utilisateur choisit, il y a une bonne
réponse. Un mode **passif** rend des indices qui divergent autour d'un repos : il n'y a rien à
choisir, et aucune bonne réponse. Les afficher pareil laisserait croire qu'un z d'engagement est
une sélection, ce qui est exactement le contresens que le contrat des flux cherche à éviter.
"""

import os
import sys

import numpy as np
from PySide6.QtWidgets import (QFormLayout, QLabel, QProgressBar, QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import NEURO_Z_SPAN, Z_MIN  # noqa: E402


class TracesView(QWidget):
    """Les 8 voies en direct. La seule vue qui lit le SIGNAL et pas une décision.

    Elle ne touche pas au tampon du moteur : `set_source` lui donne un accesseur
    (`engine.recent_window`) qui rend une COPIE. Le tampon est réécrit par le fil d'acquisition ;
    le lire depuis le fil Qt donnerait, tôt ou tard, une vue à moitié écrite.

    Les voies sont DÉCALÉES verticalement plutôt que superposées : superposées, une seule voie
    qui dérive écrase les sept autres et on ne voit plus rien — or la dérive d'une voie est
    précisément ce qu'on cherche à repérer ici.
    """

    SECONDES = 4.0
    ECART_UV = 100.0     # décalage vertical entre deux voies

    def __init__(self, ch_names):
        super().__init__()
        import pyqtgraph as pg

        self.source = None
        self.ch_names = list(ch_names)
        self.plot = pg.PlotWidget()
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.showGrid(x=True, y=False, alpha=0.2)
        self.plot.setLabel("bottom", "secondes")
        self.plot.getAxis("left").setTicks([[
            (-i * self.ECART_UV, nom) for i, nom in enumerate(self.ch_names)]])
        self.courbes = [self.plot.plot(pen=pg.mkPen(width=1)) for _ in self.ch_names]

        self.echelle = QLabel(f"signal BRUT, non filtré · une graduation = {self.ECART_UV:g} µV "
                              f"· {self.SECONDES:g} dernières secondes")
        self.echelle.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        layout = QVBoxLayout(self)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.echelle)

    def set_source(self, source):
        """`source(seconds) -> (n, 8) ou None`. En pratique : `engine.recent_window`."""
        self.source = source

    def update_from(self, _mode_state):
        if self.source is None:
            return
        bloc = self.source(self.SECONDES)
        if bloc is None or len(bloc) < 2:
            return
        t = np.arange(len(bloc)) / max(len(bloc) / self.SECONDES, 1e-9)
        for i, courbe in enumerate(self.courbes):
            if i >= bloc.shape[1]:
                break
            # Centré voie par voie : l'Unicorn sort un offset DC énorme (10⁵ µV, en rampe après
            # l'ouverture de session). Sans ce centrage, les 8 courbes sortiraient de l'écran.
            voie = bloc[:, i] - float(np.median(bloc[:, i]))
            courbe.setData(t, voie - i * self.ECART_UV)


class ActiveView(QWidget):
    """Une barre par cible, plus le seuil de décision, plus la cible retenue.

    Le seuil est affiché À CÔTÉ des scores, et pas seulement la décision : c'est ce qui permet
    de dire si une non-détection vient d'un signal absent ou d'un seuil trop haut. Sans ça, une
    séance muette n'a qu'une explication apparente — « l'utilisateur fixe mal ».

    ⚠️ **Deux modes « actif » du moteur, deux formes de sortie.** Le SSVEP publie un score PAR
    CIBLE sur l'échelle z (`scores`, `target_index`, `freq_hz`) ; le Motor Imagery publie une
    PROBABILITÉ par classe (`probas`, `intent_index`, `label`, `confidence`) — il n'a ni cible
    ni z, la référence y est APPRISE, pas mesurée au repos du jour. Confondre les deux
    afficherait « aucune cible » en PERMANENCE pour le MI, puisque `target_index` n'existe
    simplement pas dans sa sortie : silencieusement faux, le genre de panne que ce produit
    existe pour éliminer. D'où les deux rendus ci-dessous, choisis sur la CLÉ présente dans la
    sortie plutôt que sur l'identifiant du mode — cohérent avec le principe du fichier (rendre
    par famille), affiné ici parce que la famille « actif » recouvre déjà deux formes.
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
        """Exactement `n` barres : on en ajoute, et surtout on en RETIRE.

        Le retrait compte autant que l'ajout : régler moins de fréquences en cours de séance
        laisserait sinon une barre orpheline, figée sur le score d'une cible qui n'existe plus.
        """
        while len(self._barres) < n:
            barre = QProgressBar()
            barre.setRange(0, 100)
            barre.setTextVisible(False)
            self._barres.append((QLabel(""), barre))
            self.barres.addRow(self._barres[-1][0], barre)
        while len(self._barres) > n:
            self._barres.pop()
            self.barres.removeRow(self.barres.rowCount() - 1)
        for i, (etiquette, _b) in enumerate(self._barres):
            etiquette.setText(etiquettes[i] if i < len(etiquettes) else "")

    def update_from(self, mode_state):
        sortie = (mode_state or {}).get("output") or {}
        if not sortie:
            self.verdict.setText(mode_state["instruction"] if mode_state else "en attente")
            return
        if "probas" in sortie:
            self._update_probas(mode_state, sortie)
        else:
            self._update_scores(mode_state, sortie)

    def _update_scores(self, mode_state, sortie):
        """SSVEP (et tout futur mode à score continu) : un score par cible, sur l'échelle z."""
        freqs = (mode_state.get("params") or {}).get("freqs") or []
        scores = sortie.get("scores") or []
        seuil = float(sortie.get("threshold", Z_MIN))
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

    def _update_probas(self, mode_state, sortie):
        """Motor Imagery (et tout futur mode à vote de classe) : une probabilité par classe.

        Pas d'échelle 2× ici : une probabilité est déjà bornée à 1, contrairement au z du
        SSVEP qui n'a pas de plafond naturel.

        ⚠️ **Les barres et le verdict ne décrivent pas le même instant.** Les barres montrent la
        dernière fenêtre, le verdict sort du VOTE sur les `vote_len` dernières. Il est donc
        NORMAL de les voir se contredire pendant que l'utilisateur change d'intention — d'où la
        règle affichée en toutes lettres au-dessus des barres.

        Cette règle est celle du MOTEUR, écrite avec les valeurs que le moteur publie
        (`threshold` dans la sortie, `min_votes` et `vote_len` dans les réglages) : rien n'est
        décidé ici. L'écran annonçait « la classe gagnante doit dépasser le seuil », ce qui est
        faux — le seuil filtre CHAQUE fenêtre, puis c'est le vote qui décide — et il affichait
        donc « 0,99 » à côté de « vote non conclu », sur le même écran.
        """
        params = (mode_state or {}).get("params") or {}
        probas = sortie.get("probas") or {}
        classes = list(probas.keys())
        seuil = float(sortie.get("threshold", 0.0))
        min_votes, vote_len = params.get("min_votes"), params.get("vote_len")
        vote_connu = min_votes is not None and vote_len is not None
        self._assure(len(classes), classes)
        regle = (f"puis {min_votes} fenêtres d'accord sur les {vote_len} dernières"
                 if vote_connu else "puis un vote sur les fenêtres récentes")
        self.seuil.setText(f"échelle probabilité · seuil {seuil:g} par fenêtre, {regle}")

        for i, (_e, barre) in enumerate(self._barres):
            valeur = probas.get(classes[i], 0.0) if i < len(classes) else 0.0
            barre.setValue(int(max(0.0, min(valeur, 1.0)) * 100))

        index = sortie.get("intent_index", -1)
        if index < 0:
            manque = (f"moins de {min_votes} des {vote_len} dernières fenêtres d'accord"
                      if vote_connu else "pas assez de fenêtres récentes d'accord")
            self.verdict.setText(f"— (vote non conclu : {manque})")
        else:
            # « du vote » n'est pas décoratif : le moteur publie ici la moyenne des fenêtres qui
            # ont voté pour cette classe, pas la probabilité de la dernière fenêtre affichée
            # au-dessus. Sans ce mot, les deux chiffres semblent devoir coïncider.
            self.verdict.setText(f"INTENTION {sortie.get('label', '')} "
                                 f"· confiance du vote {sortie.get('confidence', 0.0):.2f}")


class PassiveView(QWidget):
    """Un indice par ligne, en ÉCART au repos. Aucune sélection, aucune bonne réponse.

    ⚠️ L'échelle est un z contre le repos du jour de CET utilisateur. `+1` veut dire « au-dessus
    de mon propre repos », pas « chargé ». Les trois indices dérivent du même calcul spectral et
    restent corrélés. C'est écrit sous les barres, pas dans une documentation que personne
    n'ouvrira : un affichage qui présenterait ça comme une mesure de fatigue mentirait.
    """

    # Au-delà de ±NEURO_Z_SPAN, la barre est pleine. La constante vient de `core/config.py`,
    # comme celle de l'appli pygame : la recopier ici ferait diverger les deux affichages le jour
    # où quelqu'un la retouche pour rendre les barres plus ou moins sensibles.
    SPAN = NEURO_Z_SPAN

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

        # Un indice qui cesse d'être rapporté perd sa barre. Sans ça elle resterait à l'écran,
        # figée sur sa dernière valeur, sans rien pour dire qu'elle ne mesure plus rien.
        for disparu in [c for c in self._barres if c not in z]:
            self.barres.removeRow(self._barres.pop(disparu))

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


def build(family, ch_names=()):
    """Le rendu qui convient à cette famille — jamais à un identifiant de mode."""
    if family == "brut":
        return TracesView(ch_names)
    return PassiveView() if family == "passif" else ActiveView()
