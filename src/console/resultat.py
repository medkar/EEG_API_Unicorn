"""Le bloc de résultat : trois lignes en face, tout le reste replié derrière « Détails ».

    ┌─────────────────────────────────────────────────────┐
    │  UTILISABLE                              (en couleur) │
    │  38 % de cibles justes (hasard 17 %) sur 90 essais    │
    │  Chiffre calculé sur les essais d'entraînement : …    │
    │  ☐ Détails                                            │
    └─────────────────────────────────────────────────────┘

⚠️ **Ce widget ne juge RIEN.** Le niveau (vert, orange, rouge), le mot, la ligne de chiffres et la
réserve sont écrits par le MOTEUR (`core/modes/affichage.py`), avec la même table de seuils que la
phrase de verdict. Déduire une couleur du texte ou d'un pourcentage, ici, serait tenir une seconde
table de seuils côté écran — qui peindrait un jour en vert ce que le moteur juge faible.

⚠️ **Rien n'est supprimé, tout est RANGÉ.** La phrase de verdict complète, la phrase d'honnêteté et
le nom du fichier produit passent sous « Détails ». Chacune a été écrite après une conclusion fausse
réellement tirée sur ce projet ; elles ne sont pas de la verbosité, elles étaient seulement au
mauvais endroit (séance du 2026-09-22 : « c'est pas clair du tout et beaucoup trop verbeux »).
"""

import os
import sys

from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.i18n import tr  # noqa: E402
from core.modes.affichage import NIVEAUX  # noqa: E402

# Le code couleur, et rien d'autre. Les mêmes teintes que le reste de la console : le rouge des
# refus, l'ambre des avertissements, le vert des réglages retenus.
COULEURS = {"bon": "#3fae5a", "moyen": "#b8860b", "faible": "#e5484d"}
NEUTRE = "#8a8f9c"      # un résultat SANS niveau : on ne l'invente pas, on le laisse gris
# La RÉSERVE a sa propre teinte, celle des avertissements de la console (« accepté, MAIS »), quel
# que soit le verdict. Peinte de la couleur du verdict, elle se lisait en VERT sous un bon
# résultat — comme un encouragement, alors qu'elle dit de quoi se méfier (constat M5).
RESERVE = "#b8860b"

assert set(COULEURS) == set(NIVEAUX), (
    f"la console doit savoir peindre CHAQUE niveau que le moteur publie, et aucun autre "
    f"({sorted(COULEURS)} contre {sorted(NIVEAUX)})")


def couleur_du_niveau(niveau):
    """La teinte d'un niveau publié par le moteur. Gris s'il n'y en a pas — jamais deviné."""
    return COULEURS.get(niveau, NEUTRE)


class BlocResultat(QWidget):
    """Trois lignes et un repli. `montrer(resultat)` à chaque résultat reçu."""

    def __init__(self, corps_auto=True):
        """`corps_auto=False` : la page hôte range dans le repli ses PROPRES widgets détaillés
        (`ajouter_au_detail`), au lieu du texte que ce bloc compose. C'est le cas des pages de
        calibration et de mesure, dont les détails sont déjà écrits, testés, et propres à chaque
        protocole — les réécrire ici serait en perdre."""
        super().__init__()
        self.corps_auto = corps_auto
        self._hotes = 0
        self._dernier = None        # le dernier résultat montré : seul un NOUVEAU referme le repli
        self.verdict = QLabel("")
        self.chiffres = QLabel("")
        self.chiffres.setWordWrap(True)
        self.chiffres.setStyleSheet("font-size: 15px;")
        self.reserve = QLabel("")
        self.reserve.setWordWrap(True)
        self.details = QCheckBox(tr("console.resultat.details"))
        self.details.toggled.connect(self._deplier)
        self.corps = QLabel("")
        self.corps.setWordWrap(True)
        self.corps.setStyleSheet(f"color: {NEUTRE}; font-size: 11px;")
        # Le repli est UN conteneur : le corps composé ici, plus ce que la page hôte y range.
        self.pli = QWidget()
        self._pli = QVBoxLayout(self.pli)
        self._pli.setContentsMargins(0, 0, 0, 0)
        self._pli.addWidget(self.corps)
        self.pli.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for w in (self.verdict, self.chiffres, self.reserve, self.details, self.pli):
            layout.addWidget(w)

    def ajouter_au_detail(self, *widgets):
        """Range des widgets de la page hôte DANS le repli : présents, lisibles d'un clic, jamais
        en face."""
        for w in widgets:
            self._pli.addWidget(w)
            self._hotes += 1

    def montrer(self, resultat):
        """Affiche un résultat. Tolère un résultat ANCIEN, sans les quatre clés : son verdict
        s'affiche alors en gris, tel quel — c'est honnête, et ça ne casse pas une page ouverte
        pendant qu'un protocole pas encore migré rend son chiffre."""
        resultat = resultat or {}
        niveau = resultat.get("niveau")
        couleur = couleur_du_niveau(niveau)
        mot = resultat.get("mot") or resultat.get("verdict") or ""
        self.verdict.setText(mot)
        self.verdict.setWordWrap(not resultat.get("mot"))
        self.verdict.setStyleSheet(f"color: {couleur}; font-size: 22px; font-weight: bold;")
        self.chiffres.setText(resultat.get("chiffres", ""))
        self.chiffres.setVisible(bool(resultat.get("chiffres")))
        # « ⚠ » en tête, comme la maquette de la spec (§3) : c'est une mise en garde, pas une suite
        # du verdict.
        self.reserve.setText(f"⚠ {resultat['reserve']}" if resultat.get("reserve") else "")
        self.reserve.setStyleSheet(f"color: {RESERVE};")
        self.reserve.setVisible(bool(resultat.get("reserve")))

        # Le repli. Ordre : la phrase de verdict complète d'abord — c'est elle qui porte les
        # tests statistiques et les repères du projet —, puis l'honnêteté, puis le fichier.
        morceaux = []
        if resultat.get("mot") and resultat.get("verdict"):
            morceaux.append(resultat["verdict"])
        if resultat.get("honnetete"):
            morceaux.append(resultat["honnetete"])
        if resultat.get("nom"):
            morceaux.append(tr("console.resultat.fichier", nom=resultat["nom"]))
        self.corps.setText("\n\n".join(morceaux) if self.corps_auto else "")
        self.corps.setVisible(self.corps_auto and bool(morceaux))
        self.details.setVisible((self.corps_auto and bool(morceaux)) or self._hotes > 0)
        # 🔴 Le repli ne se referme que sur un NOUVEAU résultat. La page appelle `montrer` à chaque
        # rafraîchissement (dix fois par seconde) avec le MÊME résultat : le refermer à chaque
        # appel, c'était refermer « Détails » 100 ms après qu'on l'a ouvert — la phrase
        # d'honnêteté, le McNemar et le nom du modèle étaient donc ILLISIBLES, et « rangé, pas
        # supprimé » ne tenait pas. Trouvé par la revue de branche ; le smoke restait vert parce
        # qu'il cochait puis lisait sans rafraîchir entre les deux.
        if resultat != self._dernier:
            self.details.setChecked(False)
            self._deplier(False)
        self._dernier = resultat

    def _deplier(self, ouvert):
        self.pli.setVisible(bool(ouvert))
