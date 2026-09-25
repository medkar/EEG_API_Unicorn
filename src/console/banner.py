"""Le bandeau permanent : liaison casque, σ par voie, référence décrochée.

Il ne disparaît sur aucun écran, et c'est délibéré. Une référence décrochée rend une séance
entière inexploitable **sans autre symptôme** : les 8 voies mesurent alors la même référence
flottante avec des amplitudes parfaitement plausibles, et un écran de contrôle affiche 8 barres
rassurantes sur un signal vide. Ça a coûté 3,4 minutes d'enregistrement dans le vide le
2026-07-20, sans le moindre avertissement.

DEUX lignes (2026-09-25, demandé à l'écran) : en haut l'ÉTAT — source, σ, corrélation, et tout à
droite deux icônes qui évoluent, la batterie du casque et les barres de sa liaison ; en dessous
les MESSAGES (référence décrochée, liaison perdue, refus, fenêtre…), et cette seconde ligne
n'existe que lorsqu'il y a quelque chose à dire.
"""

import os
import sys

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import BATTERIE_FAIBLE_PC, PERTE_PAQUETS_PC  # noqa: E402
from core.i18n import nombre, tr  # noqa: E402


# Combien de temps la ligne « liaison rétablie » reste affichée après le retour du casque : le
# temps que la stabilisation et le repos des modes se refassent (15 + 25 s pour le plus long).
REPRISE_VISIBLE_S = 60.0

VERT, AMBRE, ROUGE, GRIS = "#3fae5a", "#b8860b", "#e5484d", "#8a8f9c"


def couleur_batterie(pc):
    """Vert, puis ambre sous la moitié, rouge sous le seuil où le bandeau demande de recharger."""
    if pc < BATTERIE_FAIBLE_PC:
        return ROUGE
    return AMBRE if pc < 50 else VERT


def couleur_barres(barres):
    """La couleur d'un nombre de barres : c'est le MOTEUR qui a décidé combien (cf. config)."""
    return VERT if barres >= 3 else AMBRE if barres == 2 else ROUGE


class IconeBatterie(QWidget):
    """Une pile qui se vide, dessinée — pas une image : elle suit le niveau au pourcent près."""

    def __init__(self):
        super().__init__()
        self.niveau = None
        self.setFixedSize(QSize(30, 16))

    def montrer(self, pc):
        self.niveau = pc
        self.update()

    def paintEvent(self, _evenement):  # noqa: N802 - nom imposé par Qt
        if self.niveau is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        corps = QRectF(1, 2, 24, 12)
        p.setPen(QPen(QColor(GRIS), 1.5))
        p.drawRoundedRect(corps, 2, 2)
        p.fillRect(QRectF(26, 6, 3, 4), QColor(GRIS))          # la borne
        largeur = max(0.0, min(float(self.niveau), 100.0)) / 100.0 * 20
        p.fillRect(QRectF(3, 4, largeur, 8), QColor(couleur_batterie(self.niveau)))
        p.end()


class IconeSignal(QWidget):
    """Quatre barres, comme un téléphone ; celles du moteur sont pleines, les autres en creux."""

    def __init__(self):
        super().__init__()
        self.barres = None
        self.setFixedSize(QSize(22, 16))

    def montrer(self, barres):
        self.barres = barres
        self.update()

    def paintEvent(self, _evenement):  # noqa: N802 - nom imposé par Qt
        if self.barres is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pleine = QColor(couleur_barres(self.barres))
        for i in range(4):
            hauteur = 4 + 3 * i
            barre = QRectF(1 + 5 * i, 15 - hauteur, 3.5, hauteur)
            if i < self.barres:
                p.fillRect(barre, pleine)
            else:
                p.setPen(QPen(QColor(GRIS), 1))
                p.drawRect(barre)
        if self.barres == 0:                                   # liaison perdue : une croix
            p.setPen(QPen(QColor(ROUGE), 2))
            p.drawLine(4, 3, 12, 11)
            p.drawLine(12, 3, 4, 11)
        p.end()


class Banner(QWidget):
    """Deux lignes, jamais masquées : l'état en haut, les messages en dessous."""

    def __init__(self):
        super().__init__()
        self.liaison = QLabel(tr("console.bandeau.moteur_non_demarre"))
        self.sigmas = QLabel("")
        self.alarme = QLabel("")
        self.alarme.setStyleSheet(f"color: {ROUGE}; font-weight: bold;")
        # L'état de la FENÊTRE de stimulus, s'il y en a une. Ici et pas sur une page, pour la même
        # raison que le reste du bandeau : une fenêtre qui meurt pendant qu'on regarde la grille
        # doit se voir quand même. Et une fenêtre morte en silence, c'est un moteur qui attend des
        # marqueurs qui ne viendront plus — indiscernable d'un étudiant qui fixe mal.
        self.fenetre = QLabel("")
        self.fenetre.setWordWrap(True)
        # Le dernier REFUS du moteur, quel qu'il soit. Ici, et pas sur une page, parce que le
        # refus le plus banal du produit arrive depuis la GRILLE — cliquer « Démarrer » sur un
        # mode sans modèle entraîné — et que la grille n'a aucune page où l'écrire.
        #
        # ⚠️ Jusqu'au 2026-09-10, `Console.commande` imprimait ces refus dans le TERMINAL et nulle
        # part ailleurs. Sur un dépôt fraîchement cloné, cliquer « Démarrer » sur le MI, le P300,
        # l'ErrP ou le c-VEP laissait l'écran STRICTEMENT immobile — le moteur refusait
        # correctement, avec son message complet, derrière la fenêtre. La recette du projet
        # (test 1.13) a relevé cinq clics d'affilée sur ce bouton muet. C'est le défaut que ce
        # chantier a passé son temps à réparer ailleurs ; il vivait encore ici.
        self.refus = QLabel("")
        self.refus.setWordWrap(True)
        self.refus.setStyleSheet(f"color: {ROUGE}; font-weight: bold;")
        # La MORT du fil du moteur. Ici, et pas sur une page, pour la raison de tout ce bandeau :
        # elle peut arriver pendant qu'on regarde n'importe quel écran, et elle rend faux tout ce
        # qui s'affiche ailleurs.
        self.moteur = QLabel("")
        self.moteur.setWordWrap(True)
        self.moteur.setStyleSheet(f"color: {ROUGE}; font-weight: bold;")
        # Batterie faible, liaison dégradée : le MOT qui accompagne les icônes quand ça va mal.
        self.alerte_casque = QLabel("")
        self.alerte_casque.setWordWrap(True)
        self.alerte_casque.setStyleSheet(f"color: {AMBRE}; font-weight: bold;")
        # Après une coupure du casque : la minute qui suit son retour (2026-09-25).
        self.reprise = QLabel("")
        self.reprise.setWordWrap(True)
        self.reprise.setStyleSheet(f"color: {AMBRE};")

        # Les icônes du casque, tout à droite (2026-09-25).
        self.batterie = IconeBatterie()
        self.batterie_pc = QLabel("")
        self.signal = IconeSignal()

        haut = QHBoxLayout()
        haut.setContentsMargins(0, 0, 0, 0)
        haut.addWidget(self.liaison)
        haut.addWidget(self.sigmas)
        haut.addStretch(1)
        haut.addWidget(self.batterie)
        haut.addWidget(self.batterie_pc)
        haut.addSpacing(10)
        haut.addWidget(self.signal)

        self.messages = QWidget()
        self.ligne_messages = QVBoxLayout(self.messages)
        self.ligne_messages.setContentsMargins(0, 2, 0, 0)
        self.ligne_messages.setSpacing(2)
        for widget in (self.alarme, self.alerte_casque, self.reprise, self.fenetre, self.refus,
                       self.moteur):
            self.ligne_messages.addWidget(widget)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        layout.addLayout(haut)
        layout.addWidget(self.messages)
        self._icones({})
        self._ranger()

    # --- les messages : une seconde ligne qui n'existe que s'il y a quelque chose à dire ----------

    def _ranger(self):
        """Montre les messages non vides, et la seconde ligne seulement s'il y en a un."""
        visibles = False
        for i in range(self.ligne_messages.count()):
            etiquette = self.ligne_messages.itemAt(i).widget()
            etiquette.setVisible(bool(etiquette.text()))
            visibles = visibles or bool(etiquette.text())
        self.messages.setVisible(visibles)

    def set_moteur(self, texte):
        """Le fil du moteur est-il encore vivant ? `""` quand oui.

        ⚠️ **Il ÉCRASE le reste du bandeau quand il est non vide, et c'est tout l'intérêt.** Un fil
        mort laisse `snapshot()` figé sur son dernier état : « Unicorn · 250 Hz · 0 mode actif » et
        « σ : en attente du tampon… » restent alors à l'écran POUR TOUJOURS, tous les deux
        parfaitement plausibles — la console a l'air d'attendre le tampon d'un casque qui ne
        s'ouvrira jamais. C'est pour ça que cette méthode est appelée APRÈS `update_from` : l'écran
        doit dire que plus rien n'arrive, pas continuer à décrire un moteur qui n'existe plus.
        """
        self.moteur.setText(texte or "")
        if texte:
            self.sigmas.setText(tr("console.bandeau.sigmas_moteur_arrete"))
            self.alarme.setText("")
            self._icones({})
        self._ranger()

    def set_refus(self, texte):
        """Le dernier refus du moteur, ou "" pour l'effacer. Un refus ACCEPTÉ n'efface pas le
        précédent : c'est l'appelant qui décide quand la question est réglée."""
        self.refus.setText(texte or "")
        self._ranger()

    def set_fenetre(self, texte, alerte=False):
        """Ce que devient la fenêtre de stimulus. Vient de `LanceurFenetre`, pas du moteur : le
        moteur ne sait pas qu'elle existe, et c'est délibéré (il tourne sans écran)."""
        self.fenetre.setText(texte or "")
        self.fenetre.setStyleSheet(f"color: {ROUGE}; font-weight: bold;" if alerte
                                   else f"color: {GRIS};")
        self._ranger()

    def update_from(self, state):
        self._mettre_a_jour(state)
        self._ranger()

    def _mettre_a_jour(self, state):
        board = state.get("board", "?")
        source = (tr("console.bandeau.source_test") if board == "synthetic"
                  else tr("console.bandeau.source_unicorn"))
        actifs = len(state.get("modes") or ())
        fs = f"{state.get('fs_hz', 0):.0f}"
        self.liaison.setText(
            tr("console.bandeau.liaison.plusieurs", source=source, fs=fs, n=actifs) if actifs > 1
            else tr("console.bandeau.liaison.un", source=source, fs=fs, n=actifs))
        self._icones(state.get("casque") or {})

        quality = state.get("quality")
        if not quality:
            self.sigmas.setText(tr("console.bandeau.sigmas_attente"))
            self.alarme.setText("")
            return

        sigmas = quality.get("sigmas", [])
        valeurs = [v for v in sigmas if v is not None]
        verdicts = quality.get("verdicts", [])
        mortes = sum(1 for v in verdicts if v == "morte")
        saturees = sum(1 for v in verdicts if v == "saturée")
        morceaux = [tr("console.bandeau.sigmas", min=nombre(min(valeurs), ".1f"),
                       max=nombre(max(valeurs), ".1f"), n=len(valeurs))
                    if valeurs else tr("console.bandeau.sigma_indisponible")]
        if mortes:
            morceaux.append(tr("console.bandeau.mortes.plusieurs", n=mortes) if mortes > 1
                            else tr("console.bandeau.mortes.un", n=mortes))
        if saturees:
            morceaux.append(tr("console.bandeau.saturees.plusieurs", n=saturees) if saturees > 1
                            else tr("console.bandeau.saturees.un", n=saturees))
        # La corrélation inter-voies, TOUJOURS visible (passe au casque du 2026-09-24 : la QA
        # demandait de la lire au montage, et elle ne s'affichait que dans l'alarme, au-delà de
        # 0,90). C'est le signe d'une référence qui flotte : ~0,3-0,5 sur un montage sain.
        if quality.get("common_mode") is not None:
            morceaux.append(tr("console.bandeau.correlation",
                               correlation=nombre(float(quality["common_mode"]), ".2f")))
        self.sigmas.setText(" · ".join(morceaux))

        if quality.get("reference_lost"):
            self.alarme.setText(tr("console.bandeau.reference_decrochee",
                                   correlation=nombre(float(quality.get("common_mode") or 0.0),
                                                      ".2f")))
        else:
            self.alarme.setText("")
        self._montrer_liaison(state.get("liaison") or {})

    def _icones(self, casque):
        """Batterie et barres de liaison, tout à droite ; rien de ce que le moteur ne sait pas.

        La batterie PRÉVIENT : un casque à plat refuse de s'ouvrir et décroche en pleine séance
        (vu le 2026-09-25). Les barres aussi : un casque qui s'éloigne perd des échantillons AVANT
        de décrocher. Le board de test n'a ni l'une ni les autres (sa batterie est fabriquée, il
        n'a pas de liaison radio) : le moteur rend None, et rien ne s'affiche.
        """
        batterie = casque.get("batterie_pc")
        self.batterie.montrer(batterie)
        self.batterie.setVisible(batterie is not None)
        self.batterie_pc.setText("" if batterie is None
                                 else tr("console.bandeau.batterie", pc=batterie))
        self.batterie_pc.setVisible(batterie is not None)
        self.batterie.setToolTip(tr("console.bandeau.batterie_aide"))
        self.batterie_pc.setToolTip(tr("console.bandeau.batterie_aide"))

        barres = casque.get("signal_barres")
        perte = casque.get("perte_pc")
        self.signal.montrer(barres)
        self.signal.setVisible(barres is not None)
        self.signal.setToolTip(tr("console.bandeau.signal_aide",
                                  pc=nombre(float(perte or 0.0), ".1f")))

        alertes = []
        if batterie is not None and batterie < BATTERIE_FAIBLE_PC:
            alertes.append(tr("console.bandeau.batterie_faible", pc=batterie))
        if perte is not None and perte >= PERTE_PAQUETS_PC:
            alertes.append(tr("console.bandeau.paquets_perdus", pc=nombre(float(perte), ".1f")))
        self.alerte_casque.setText("   ".join(alertes))

    def _montrer_liaison(self, liaison):
        """Le casque a-t-il décroché ? (2026-09-25) Prioritaire sur tout le reste du bandeau.

        Pendant la coupure, le moteur ne décode plus rien et réessaie seul : l'écran doit le dire,
        sinon il montre des σ figés sur le dernier tampon — l'écran « où plus rien ne bouge » que
        l'on fermait pour relancer. Après le retour, une minute d'avertissement : les modes
        refont leur repos, et la réouverture redémarre l'amplificateur (C3/Cz saturent un moment).
        """
        if liaison.get("etat") == "perdue":
            self.alarme.setText(tr("console.bandeau.liaison_perdue",
                                   depuis=int(liaison.get("depuis_s") or 0),
                                   tentatives=liaison.get("tentatives", 0),
                                   raison=liaison.get("erreur") or "…"))
            self.sigmas.setText(tr("console.bandeau.sigmas_liaison_perdue"))
            self.reprise.setText("")
            return
        retablie = liaison.get("retablie_depuis_s")
        if retablie is not None and retablie < REPRISE_VISIBLE_S:
            self.reprise.setText(tr("console.bandeau.liaison_retablie",
                                    coupure=nombre(float(liaison.get("coupure_s") or 0.0), ".0f")))
        else:
            self.reprise.setText("")
