"""Le contact de chaque électrode : la tête vue de dessus, et une barre de signal par voie.

Cette vue ne juge RIEN. Le verdict de chaque électrode (`quality["contact"]`), celui de la
référence (`quality["reference_ok"]`) et le seuil (`quality["seuil_contact"]`) viennent du moteur
(`core/config.contact_bon`). Elle les peint, de la même couleur sur le schéma et sur la barre :

- vert : bon contact ;
- rouge : mauvais contact (signal plat, ou trop de bruit : la barre dépasse le repère) ;
- cercle vide, barre vide : pas de mesure (casque déconnecté, liaison perdue).

Les électrodes CLÉS de ce qu'on s'apprête à lancer (`key_channels` du contrat : les occipitales
du SSVEP, C3/Cz/C4 du MI…) sont entourées en bleu sur le schéma, et leur barre est encadrée.

Une ligne de texte nomme aussi les électrodes à revoir : le rouge et le vert se confondent pour
certaines personnes.
"""

import os
import sys

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from console.banner import GRIS, ROUGE, VERT  # noqa: E402
from console.params_form import ACCENT, infobulle  # noqa: E402
from core.i18n import nombre, tr  # noqa: E402

# La place de chaque électrode, tête vue de dessus, nez en haut : (x, y) en fraction du rayon du
# dessin, x vers l'oreille droite de la personne, y vers son nez. C'est le système 10-20 : Cz au
# sommet du crâne ; Fz, Pz, C3 et C4 à 40 % du rayon ; Oz à 80 % derrière ; PO7 et PO8 sur le même
# cercle qu'Oz, 36° de part et d'autre.
POSITIONS = {
    "Fz": (0.0, 0.4), "C3": (-0.4, 0.0), "Cz": (0.0, 0.0), "C4": (0.4, 0.0),
    "Pz": (0.0, -0.4), "PO7": (-0.47, -0.65), "Oz": (0.0, -0.8), "PO8": (0.47, -0.65),
}
# Les deux pastilles collées derrière les oreilles (référence et masse). Un seul verdict pour les
# deux : celui de la référence.
MASTOIDES = ((-1.0, -0.3), (1.0, -0.3))


def couleur(verdict):
    """La couleur d'un verdict du moteur : vert, rouge, ou None (on ne remplit pas)."""
    if verdict is None:
        return None
    return VERT if verdict else ROUGE


class SchemaTete(QWidget):
    """La tête vue de dessus, une pastille par électrode, colorée par le verdict du moteur."""

    RAYON_TETE = 100.0
    RAYON_ELECTRODE = 15.0
    RAYON_MASTOIDE = 9.0
    ECART_ANNEAU = 5.0          # l'anneau bleu d'une électrode clé, autour de sa pastille

    def __init__(self):
        super().__init__()
        # Le dernier état peint, lisible par les autotests : {nom: True | False | None}.
        self.etats = {nom: None for nom in POSITIONS}
        self.reference = None
        self.cles = set()       # les NOMS des électrodes clés, entourées en bleu
        self.setFixedSize(QSize(260, 250))

    def montrer(self, etats, reference):
        self.etats = dict(etats)
        self.reference = reference
        self.update()

    def viser(self, cles):
        """Les noms des électrodes à entourer : celles que lit ce qu'on s'apprête à lancer."""
        self.cles = set(cles)
        self.update()

    def _point(self, x, y):
        """Une position du dessin (fraction du rayon) en pixels du widget."""
        cx, cy = self.width() / 2.0, self.height() / 2.0 + 8.0
        return QPointF(cx + x * self.RAYON_TETE, cy - y * self.RAYON_TETE)

    def _pastille(self, p, centre, rayon, verdict, texte):
        teinte = couleur(verdict)
        p.setPen(QPen(QColor(teinte or GRIS), 2))
        p.setBrush(QColor(teinte) if teinte else Qt.NoBrush)
        p.drawEllipse(centre, rayon, rayon)
        if texte:
            p.setPen(QColor("white") if teinte else self.palette().windowText().color())
            boite = QRectF(centre.x() - rayon - 6, centre.y() - rayon, 2 * rayon + 12, 2 * rayon)
            p.drawText(boite, Qt.AlignCenter, texte)

    def paintEvent(self, _evenement):  # noqa: N802 - nom imposé par Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        trait = QPen(QColor(GRIS), 2)
        centre = self._point(0.0, 0.0)
        r = self.RAYON_TETE
        # Le nez, puis les oreilles, puis la tête par-dessus.
        nez = QPainterPath(self._point(-0.12, 0.99))
        nez.lineTo(self._point(0.0, 1.14))
        nez.lineTo(self._point(0.12, 0.99))
        p.setPen(trait)
        p.setBrush(Qt.NoBrush)
        p.drawPath(nez)
        for cote in (-1, 1):
            oreille = self._point(cote * 1.03, 0.0)
            p.drawEllipse(oreille, 0.07 * r, 0.16 * r)
        p.drawEllipse(centre, r, r)

        police = QFont(self.font())
        police.setPointSizeF(7.5)
        police.setBold(True)
        p.setFont(police)
        for nom, (x, y) in POSITIONS.items():
            self._pastille(p, self._point(x, y), self.RAYON_ELECTRODE, self.etats.get(nom), nom)
        for x, y in MASTOIDES:
            self._pastille(p, self._point(x, y), self.RAYON_MASTOIDE, self.reference, "")
        # Un anneau, pas un remplissage : la couleur de la pastille reste celle du contact.
        p.setPen(QPen(QColor(ACCENT), 3))
        p.setBrush(Qt.NoBrush)
        rayon = self.RAYON_ELECTRODE + self.ECART_ANNEAU
        for nom in self.cles:
            if nom in POSITIONS:
                p.drawEllipse(self._point(*POSITIONS[nom]), rayon, rayon)
        p.end()


class BarreContact(QWidget):
    """Une barre de signal (σ de la voie) avec un REPÈRE : au-delà, le contact n'est pas bon.

    Le repère est au milieu : la barre va de 0 à deux fois le seuil du moteur.
    """

    def __init__(self):
        super().__init__()
        self.sigma = None
        self.seuil = None
        self.verdict = None
        self.setMinimumSize(QSize(180, 16))
        self.setMaximumWidth(480)

    def montrer(self, sigma, seuil, verdict):
        self.sigma, self.seuil, self.verdict = sigma, seuil, verdict
        self.update()

    def paintEvent(self, _evenement):  # noqa: N802 - nom imposé par Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cadre = QRectF(1, 2, self.width() - 2, self.height() - 4)
        p.setPen(QPen(QColor(GRIS), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(cadre)
        teinte = couleur(self.verdict)
        if self.seuil and self.sigma is not None and teinte:
            part = max(0.0, min(float(self.sigma) / (2.0 * float(self.seuil)), 1.0))
            p.fillRect(QRectF(cadre.x() + 1, cadre.y() + 1, (cadre.width() - 2) * part,
                              cadre.height() - 2), QColor(teinte))
        if self.seuil:
            x = cadre.x() + cadre.width() / 2.0
            p.setPen(QPen(self.palette().windowText().color(), 2))
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        p.end()


class VueContact(QGroupBox):
    """Le schéma de la tête et les huit barres, côte à côte, sous un titre et sa bulle « ⓘ ».

    `cles` : les INDICES des voies clés (`key_channels` du contrat), entourées en bleu.
    """

    LARGEUR_NOM = 40
    LARGEUR_VALEUR = 72

    def __init__(self, cles=()):
        super().__init__(tr("pages.electrodes.titre"))
        self.cles = tuple(cles)
        self.schema = SchemaTete()
        self.bulle = QLabel("ⓘ")
        self.bulle.setStyleSheet(f"color: {ACCENT}; font-size: 13px;")
        self.bulle.setCursor(Qt.WhatsThisCursor)
        self.bulle.setToolTip(infobulle(tr("pages.electrodes.aide")))

        # Une LIGNE par voie (nom, barre, valeur), pour pouvoir l'encadrer d'un bloc. Les largeurs
        # fixes alignent les barres d'une ligne à l'autre.
        self.colonne = QVBoxLayout()
        self.colonne.setSpacing(2)
        self.noms, self.barres, self.valeurs, self.lignes = {}, {}, {}, {}
        for nom in POSITIONS:
            ligne = QFrame()
            ligne.setObjectName("ligne_voie")
            rang = QHBoxLayout(ligne)
            rang.setContentsMargins(4, 1, 4, 1)
            etiquette = QLabel(nom)
            etiquette.setFixedWidth(self.LARGEUR_NOM)
            barre = BarreContact()
            valeur = QLabel("—")
            valeur.setFixedWidth(self.LARGEUR_VALEUR)
            rang.addWidget(etiquette)
            rang.addWidget(barre, 1)
            rang.addWidget(valeur)
            rang.addStretch(1)          # la valeur reste collée à sa barre
            self.colonne.addWidget(ligne)
            self.noms[nom], self.barres[nom], self.valeurs[nom] = etiquette, barre, valeur
            self.lignes[nom] = ligne
        self.repere = QLabel("")
        self.repere.setStyleSheet(f"color: {GRIS};")
        sous_les_barres = QHBoxLayout()
        sous_les_barres.setContentsMargins(4 + self.LARGEUR_NOM + 6, 0, 0, 0)
        sous_les_barres.addWidget(self.repere)
        self.colonne.addLayout(sous_les_barres)

        self.resume = QLabel("")
        self.resume.setWordWrap(True)
        self.resume.setStyleSheet("font-weight: bold;")

        haut = QHBoxLayout()
        haut.addWidget(self.bulle)
        haut.addWidget(self.resume, 1)
        cote = QHBoxLayout()
        cote.addWidget(self.schema)
        cote.addLayout(self.colonne, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(haut)
        layout.addLayout(cote)
        self.update_from(None)

    def viser(self, cles):
        """Les INDICES des voies clés de ce qu'on s'apprête à lancer (`key_channels`)."""
        self.cles = tuple(cles or ())

    def update_from(self, state):
        """Peint `state["quality"]` : rien à décider ici, tout vient du moteur."""
        qualite = (state or {}).get("quality") or {}
        voies = (state or {}).get("channels") or list(POSITIONS)
        cles = {voies[i] for i in self.cles if 0 <= i < len(voies)}
        self.schema.viser(cles)
        for nom, ligne in self.lignes.items():
            ligne.setStyleSheet(f"QFrame#ligne_voie {{ border: 1px solid {ACCENT}; }}"
                                if nom in cles else "")
            self.noms[nom].setStyleSheet("font-weight: bold;" if nom in cles else "")
        sigmas = qualite.get("sigmas") or []
        contact = qualite.get("contact") or []
        seuil = qualite.get("seuil_contact")
        reference = qualite.get("reference_ok")

        etats = {}
        for i, nom in enumerate(voies):
            sigma = sigmas[i] if i < len(sigmas) else None
            verdict = contact[i] if i < len(contact) else None
            etats[nom] = verdict
            if nom in self.barres:
                self.barres[nom].montrer(sigma, seuil, verdict)
                self.valeurs[nom].setText(
                    tr("pages.electrodes.valeur", s=nombre(sigma, ".1f"))
                    if sigma is not None and verdict is not None else "—")
                teinte = couleur(verdict)
                self.valeurs[nom].setStyleSheet(f"color: {teinte};" if teinte else "")
        self.schema.montrer(etats, reference)

        self.repere.setText(tr("pages.electrodes.repere", seuil=nombre(seuil, "g"))
                            if seuil else "")

        mauvaises = [nom for nom, v in etats.items() if v is False]
        if all(v is None for v in etats.values()):
            self.resume.setText(tr("pages.electrodes.sans_mesure"))
            self.resume.setStyleSheet(f"font-weight: bold; color: {GRIS};")
            return
        morceaux = []
        if reference is False:
            morceaux.append(tr("pages.electrodes.reference_decrochee"))
        if mauvaises:
            morceaux.append(tr("pages.electrodes.a_revoir", liste=", ".join(mauvaises)))
        if morceaux:
            self.resume.setText(" ".join(morceaux))
            self.resume.setStyleSheet(f"font-weight: bold; color: {ROUGE};")
        else:
            self.resume.setText(tr("pages.electrodes.tout_bon"))
            self.resume.setStyleSheet(f"font-weight: bold; color: {VERT};")
