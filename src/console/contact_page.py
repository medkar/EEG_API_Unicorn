"""Le contrôle de liaison casque, AVANT tout lancement coûteux.

Repris de `archive/ui.py:signal_check`, qui existe depuis le 2026-07-20 : ce jour-là un câble
débranché a laissé enregistrer 3,4 minutes de signal plat, puis produire tranquillement un modèle
à 0 %. Rien ne le signalait. Mieux vaut bloquer cinq secondes ici que perdre une séance.

**Pourquoi cet écran vit dans la console et pas dans les fenêtres de `src/stimulus/`** : celles-ci
n'ouvrent PAS le casque — c'est exactement ce qui leur permet de tourner à côté du moteur. Elles
n'ont aucun σ à montrer. La console, elle, sonde `snapshot()` : elle les a.

⚠️ **Aucun verdict n'est calculé ici.** `quality["verdicts"]` vient du moteur (`verdict_from_sigma`,
`reference_lost`), et les voies clés du mode viennent de son contrat (`key_channels`). Cette page
ne fait que rendre visible, et refuser. Une seconde règle de qualité écrite dans l'interface
finirait par contredire celle du moteur, et ce jour-là c'est l'écran qu'on croirait.
"""

import os
import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import SIGNAL_SAT_SIGMA  # noqa: E402
from core.i18n import tr  # noqa: E402

# Jusqu'où va la barre d'un σ. Pas le seuil de saturation (500 µV) : à cette échelle, un EEG
# normal (5-20 µV) serait un trait invisible et l'écran ne montrerait plus rien. 40 µV est
# l'échelle qu'utilise déjà `archive/ui.py:signal_check`, choisie pour que l'EEG occupe le
# premier tiers et qu'une voie qui grimpe se voie tout de suite.
SPAN_SIGMA = 40.0


class ContactPage(QWidget):
    """Les σ par voie, les voies clés du mode surlignées, et un bouton qui REFUSE.

    Une seule instance, reconfigurée par `viser()` : les huit lignes sont les mêmes d'un mode à
    l'autre, seul le surlignage change.
    """

    lancer = Signal()
    annuler = Signal()

    def __init__(self, console):
        super().__init__()
        self.console = console
        self.spec = None
        self._lignes = []          # [(cadre, etiquette, barre, verdict)] — une par voie

        entete = QHBoxLayout()
        self.bouton_retour = QPushButton(tr("console.contact.annuler"))
        self.bouton_retour.clicked.connect(self.annuler)
        entete.addWidget(self.bouton_retour)
        self.titre = QLabel(tr("console.contact.titre"))
        entete.addWidget(self.titre)
        entete.addStretch(1)

        self.cles = QLabel("")
        self.cles.setWordWrap(True)
        self.cles.setStyleSheet("color: #4c8dff;")

        self.bloc_voies = QGroupBox(tr("console.contact.sigma_par_voie"))
        self.voies_layout = QVBoxLayout(self.bloc_voies)

        # Le refus est un TEXTE À L'ÉCRAN, pas seulement un bouton grisé. Un bouton qui ne
        # réagit pas se lit comme une interface cassée — c'est la panne que ce chantier répare.
        self.refus = QLabel("")
        self.refus.setWordWrap(True)
        self.refus.setStyleSheet("color: #e5484d; font-weight: bold;")
        self.conseil = QLabel(tr("console.contact.conseil"))
        self.conseil.setWordWrap(True)
        self.conseil.setStyleSheet("color: #8a8f9c; font-size: 11px;")

        self.bouton_lancer = QPushButton(tr("console.contact.lancer"))
        self.bouton_lancer.clicked.connect(self.lancer)

        layout = QVBoxLayout(self)
        layout.addLayout(entete)
        layout.addWidget(self.cles)
        layout.addWidget(self.bloc_voies)
        layout.addWidget(self.refus)
        layout.addWidget(self.conseil)
        layout.addWidget(self.bouton_lancer)
        layout.addStretch(1)

        # État initial : rien n'est encore connu, donc rien ne se lance. Le premier `update_from`
        # remplacera ce texte par le vrai verdict — mais un bouton actif avant toute mesure
        # laisserait passer un lancement à l'aveugle si l'état n'arrivait jamais.
        self.bouton_lancer.setEnabled(False)
        self.refus.setText(tr("console.contact.attente_premiere_mesure"))

    def viser(self, spec, quoi):
        """Configure la page pour le mode `spec`. `quoi` nomme ce qu'on s'apprête à lancer.

        Les voies clés viennent du CONTRAT (`key_channels`, des indices dans `CH_NAMES`) : aucune
        liste d'électrodes n'est recopiée ici. Un mode qui change ses voies clés change cet écran
        sans qu'on y touche.
        """
        self.spec = spec
        self.titre.setText(tr("console.contact.titre_vise", mode=spec["label"], geste=quoi))
        self.bouton_lancer.setText(quoi)

    def _cles(self):
        """Les INDICES des voies clés du mode visé, tels que le contrat les déclare."""
        return set((self.spec or {}).get("key_channels") or ())

    def _construire(self, noms):
        """(Re)construit une ligne par voie. Seulement quand leur NOMBRE change — repeindre huit
        widgets dix fois par seconde ne coûte rien, en reconstruire dix fois par seconde si."""
        while self.voies_layout.count():
            item = self.voies_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._lignes = []
        for nom in noms:
            ligne = QWidget()
            colonnes = QHBoxLayout(ligne)
            colonnes.setContentsMargins(0, 0, 0, 0)
            etiquette = QLabel(nom)
            etiquette.setMinimumWidth(70)
            barre = QProgressBar()
            barre.setTextVisible(False)
            barre.setRange(0, 100)
            verdict = QLabel("")
            verdict.setMinimumWidth(150)
            colonnes.addWidget(etiquette)
            colonnes.addWidget(barre, 1)
            colonnes.addWidget(verdict)
            self.voies_layout.addWidget(ligne)
            self._lignes.append((ligne, etiquette, barre, verdict))

    def update_from(self, state):
        """Rend la qualité reçue et décide si le lancement est permis. Ne mesure RIEN."""
        state = state or {}
        quality = state.get("quality") or {}
        noms = list(state.get("channels") or ())
        sigmas = list(quality.get("sigmas") or ())
        verdicts = list(quality.get("verdicts") or ())
        cles = self._cles()

        if not noms:
            # Le moteur n'a pas encore publié ses voies : on nomme les lignes par leur indice
            # plutôt que de laisser un écran vide (qui se lit « ça ne marche pas »).
            noms = [tr("console.contact.voie_numero", i=i) for i in range(len(sigmas))]
        if len(self._lignes) != len(noms):
            self._construire(noms)

        if cles:
            libelles = ", ".join(noms[i] for i in sorted(cles) if i < len(noms))
            self.cles.setText(tr("console.contact.voies_cles", voies=libelles))
        else:
            self.cles.setText("")

        for i, (ligne, etiquette, barre, verdict) in enumerate(self._lignes):
            sigma = sigmas[i] if i < len(sigmas) else None
            v = verdicts[i] if i < len(verdicts) else ""
            marque = " *" if i in cles else ""
            # Le gras d'une voie clé passe par le STYLE, pas par du balisage dans le texte.
            etiquette.setText(noms[i] + marque)
            etiquette.setStyleSheet("font-weight: bold;" if i in cles else "")
            barre.setValue(0 if sigma is None
                           else int(max(0.0, min(sigma / SPAN_SIGMA, 1.0)) * 100))
            verdict.setText(tr("console.contact.sigma_indisponible") if sigma is None
                            else tr("console.contact.sigma_voie", sigma=f"{sigma:.1f}",
                                    verdict=v))
            couleur = "#8a8f9c" if not v else ("#3fae5a" if v == "ok" else "#e5484d")
            verdict.setStyleSheet(f"color: {couleur};")
            ligne.setStyleSheet("border: 1px solid #4c8dff;" if i in cles else "")

        self.refus.setText(self._refus(quality, verdicts, noms))
        self.bouton_lancer.setEnabled(not self.refus.text())

    def _refus(self, quality, verdicts, noms):
        """La raison de ne pas lancer, ou une chaîne vide. Aucun seuil n'est appliqué ici : on
        ne fait que RASSEMBLER des verdicts que le moteur a déjà rendus."""
        if not quality or not verdicts:
            return tr("console.contact.refus_attente")
        if quality.get("reference_lost"):
            return tr("console.contact.refus_reference", correlation=quality.get("common_mode"))
        fautives = [(noms[i] if i < len(noms) else str(i), v)
                    for i, v in enumerate(verdicts) if v and v != "ok"]
        if fautives:
            detail = ", ".join(f"{nom} {v}" for nom, v in fautives)
            return tr("console.contact.refus_voies", n=len(fautives), detail=detail,
                      seuil=f"{SIGNAL_SAT_SIGMA:g}")
        return ""
