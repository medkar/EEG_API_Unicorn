"""Le formulaire d'un mode, GÉNÉRÉ depuis son contrat. Il ne valide rien : le moteur s'en charge.

C'est délibéré, et c'est la règle de conception la plus importante de la console : aucune logique
ici que le moteur ne possède pas déjà. Une validation recopiée côté interface diverge tôt ou tard
de celle du moteur, et le jour où elle diverge, elle laisse passer un réglage qui ne décodera
rien — sans erreur, comme toujours avec ce genre de panne.

Le formulaire envoie donc, et affiche la RAISON du refus telle que le moteur l'a formulée.
"""

import html
import os
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.i18n import nombre, tr  # noqa: E402

# La bulle « ⓘ » : la couleur d'accent de la console (celle des voies clés, des barres retenues).
ACCENT = "#4c8dff"


def infobulle(*paragraphes):
    """Une infobulle en TEXTE RICHE, pour qu'elle passe à la ligne.

    Qt n'enroule une infobulle que si elle est en texte riche : en texte brut, une aide de trois
    phrases s'affiche sur une seule ligne qui traverse l'écran. Chaque paragraphe est échappé —
    une aide qui contiendrait « < » ou « & » ne doit pas devenir du balisage.
    """
    corps = "<br><br>".join(html.escape(p, quote=False) for p in paragraphes if p)
    return "<qt>" + corps + "</qt>"


class _SansMolette:
    """Un champ que la MOLETTE ne modifie pas : elle fait défiler la page, pas la valeur.

    Demandé le 2026-09-24. Qt fait tourner la valeur d'une liste ou d'un champ numérique sous la
    souris : en faisant défiler une page de réglages, on changeait en passant un seuil ou un
    modèle, sans le voir. `ignore()` renvoie l'événement au parent — la zone qui défile.
    """

    def wheelEvent(self, event):  # noqa: N802 - nom imposé par Qt
        event.ignore()


class ListeSansMolette(_SansMolette, QComboBox):
    pass


class EntierSansMolette(_SansMolette, QSpinBox):
    pass


class DecimalSansMolette(_SansMolette, QDoubleSpinBox):
    pass


class ParamsForm(QWidget):
    """Un champ par `Param`, plus son aide, plus un bouton et une ligne de refus."""

    appliquer = Signal(dict)
    proposer = Signal(str)      # la clé du réglage qui en PROPOSE un autre

    def __init__(self, params):
        super().__init__()
        self.params = list(params)
        self.champs = {}
        self.boutons_proposer = {}      # {clé : bouton} — pour qu'un smoke puisse le CLIQUER
        self.aides = {}                 # {clé : (la bulle « ⓘ », le texte complet du contrat)}
        self.lignes = {}                # {clé : la ligne du champ} — cf. `ajouter_a_cote`
        self.titres = {}                # {clé : la ligne du libellé, suivi de sa bulle « ⓘ »}
        self._params_par_cle = {p["key"]: p for p in self.params}

        formulaire = QFormLayout()
        for param in self.params:
            champ = self._champ(param)
            self.champs[param["key"]] = champ
            etiquette = param["label"] + (f" ({param['unit']})" if param["unit"] else "")
            # Le champ vit dans une LIGNE, pour qu'une page puisse poser un geste juste à côté
            # (le « Mesurer » du pic alpha) sans que ce formulaire sache lequel.
            ligne = QHBoxLayout()
            ligne.addWidget(champ, 1)
            self.lignes[param["key"]] = ligne
            # Le libellé et sa bulle « ⓘ » forment UN bloc, la bulle collée au texte qu'elle
            # explique (demandé le 2026-09-23 : « juste après les textes plutôt qu'au bout de la
            # ligne »). Au bout de la ligne, elle se lisait comme une annexe du champ.
            titre = QWidget()
            rang = QHBoxLayout(titre)
            rang.setContentsMargins(0, 0, 0, 0)
            rang.setSpacing(4)
            rang.addWidget(QLabel(etiquette))
            self.titres[param["key"]] = rang
            formulaire.addRow(titre, ligne)
            if param.get("proposes"):
                # Le LIBELLÉ du champ proposé, jamais sa clé : « freqs » est un nom de variable.
                cible = (self._params_par_cle.get(param["proposes"], {}).get("label")
                         or param["proposes"])
                bouton = QPushButton(tr("console.formulaire.proposer", champ=cible))
                bouton.clicked.connect(lambda _c=False, k=param["key"]: self.proposer.emit(k))
                formulaire.addRow("", bouton)
                self.boutons_proposer[param["key"]] = bouton
            if param["help"]:
                # L'aide vit dans une bulle « ⓘ » juste APRÈS le libellé, lue au survol (2026-09-23).
                # Elle était une ligne grise sous chaque réglage, plus une case « Aide détaillée »
                # qui dépliait le reste : la page c-VEP en portait un mur de trente lignes. Rien
                # n'est perdu — la bulle porte le texte ENTIER du contrat, et le champ aussi.
                paragraphes = [param["help"]]
                if param["key"] == "refresh_hz":
                    # L'écran PRINCIPAL, lu une fois au lancement — pas forcément celui où est la
                    # console. C'est le bon : les fenêtres de stimulus que lance la console s'ouvrent
                    # sans choisir d'écran, donc sur l'écran n° 0 de Windows, en général le principal.
                    # Une indication, pas un défaut : l'application peut afficher ailleurs.
                    ecran = QApplication.primaryScreen()
                    if ecran is not None and ecran.refreshRate() > 0:
                        paragraphes.append(tr("console.formulaire.ecran_detecte",
                                              hz=nombre(ecran.refreshRate())))
                bulle = QLabel("ⓘ")
                bulle.setStyleSheet(f"color: {ACCENT}; font-size: 13px;")
                bulle.setCursor(Qt.WhatsThisCursor)
                bulle.setToolTip(infobulle(*paragraphes))
                champ.setToolTip(infobulle(*paragraphes))
                rang.addWidget(bulle)
                self.aides[param["key"]] = (bulle, param["help"])
            rang.addStretch(1)

        self.bouton = QPushButton(tr("console.formulaire.appliquer"))
        self.bouton.clicked.connect(lambda: self.appliquer.emit(self.values()))
        # ⚠️ Aucun réglage = rien à appliquer, donc pas de bouton (2026-09-21, trouvé en recette
        # 1.5). Il soumettait un dictionnaire VIDE : le moteur l'acceptait, rien ne changeait, et
        # l'étudiant avait cliqué sur quelque chose qui avait l'air de faire quelque chose. C'est
        # la définition du réglage-décor que ce projet combat ailleurs.
        #
        # La règle vit ICI et pas chez les appelants, parce que QUATRE pages sont concernées et
        # qu'aucune ne le savait : le mode « Brut », et les trois calibrations menées par une
        # fenêtre (P300, ErrP, c-VEP), dont le `Calib.params` est vide. `console/mesure_page.py`
        # cachait déjà ce bouton, mais pour une AUTRE raison — une mesure se règle avant de
        # partir, son formulaire part avec `start_mesure` — donc son geste reste, et il couvre
        # aussi le cas où une mesure a des réglages.
        if not self.params:
            self.bouton.hide()
        self.refus = QLabel("")
        self.refus.setWordWrap(True)
        self.refus.setStyleSheet("color: #e5484d;")
        # Un avertissement dit qu'un réglage a été ACCEPTÉ, avec réserve — PAS refusé. Étiquette
        # séparée, couleur différente : le rouge de `refus` sur un succès ferait passer une
        # proposition acceptée pour une panne.
        self.avertissement = QLabel("")
        self.avertissement.setWordWrap(True)
        self.avertissement.setStyleSheet("color: #b8860b;")
        # ⚠️ TROIS canaux, pas deux (2026-09-22, retour de séance). Un réglage RETENU sur un mode
        # arrêté a été accepté : rien ne cloche, il n'y a aucune réserve à émettre, et l'orange
        # le faisait lire comme un problème. La nuance « pas encore en vigueur » est dans le
        # TEXTE ; la couleur, elle, ne répond qu'à une question : est-ce que ça a été accepté.
        # `console/mesure_page.py` disait déjà VERT pour le même événement (« pic appliqué ») —
        # deux écrans, deux couleurs pour un seul fait : c'est ça qu'on corrige.
        self.confirmation = QLabel("")
        self.confirmation.setWordWrap(True)
        self.confirmation.setStyleSheet("color: #3fae5a;")

        bas = QHBoxLayout()
        bas.addWidget(self.bouton)
        bas.addStretch(1)

        # `None` quand il y a des réglages : un QLabel construit sans parent serait une fenêtre
        # de premier niveau en Qt, pas un widget inerte.
        # ⚠️ « ici » et pas « pour ce mode » : ce formulaire sert aussi les CALIBRATIONS et les
        # MESURES, qui ne sont pas des modes. Le contrôle alpha, qui n'expose délibérément aucun
        # réglage (ses durées font corps avec son repère chiffré), est le premier à l'afficher.
        self.vide = None if self.params else QLabel(tr("console.formulaire.aucun_reglage"))
        layout = QVBoxLayout(self)
        if self.vide is not None:
            layout.addWidget(self.vide)
        layout.addLayout(formulaire)
        layout.addLayout(bas)
        layout.addWidget(self.refus)
        layout.addWidget(self.avertissement)
        layout.addWidget(self.confirmation)

    def ajouter_a_cote(self, cle, widget):
        """Pose `widget` à droite du champ `cle`. Ne fait rien si ce formulaire n'a pas ce champ."""
        ligne = self.lignes.get(cle)
        if ligne is not None:
            ligne.addWidget(widget)

    def _champ(self, param):
        kind = param["kind"]
        if kind == "bool":
            champ = QCheckBox()
            champ.setChecked(bool(param["default"]))
            return champ
        if kind == "choice":
            champ = ListeSansMolette()
            champ.addItems([str(c) for c in param["choices"]])
            # Sans ce réglage, un QComboBox fraîchement rempli affiche son PREMIER élément —
            # c'était invisible tant que tous les « choice » du projet avaient leur défaut EN
            # PREMIÈRE position (`model`, dont le défaut est toujours choices_now()[0]). La
            # calibration MI est le premier à déclarer un défaut ailleurs dans la liste
            # (`trials_per_class` vaut MI_SESSIONS[1]) : sans cette ligne, le formulaire
            # affichait 10 essais/classe alors que le contrat dit « commence par la valeur par
            # défaut » (14) — un mensonge visuel dès la première ouverture de la page.
            if param["default"] is not None:
                champ.setCurrentText(str(param["default"]))
            return champ
        if kind == "float_list":
            # Une ligne de valeurs séparées par des virgules : c'est la MÊME écriture que
            # `--freqs 15,20,8.571` en ligne de commande, et le nombre d'éléments se règle en
            # ajoutant ou retirant une valeur — c'est ainsi qu'on choisit le nombre de cibles.
            champ = QLineEdit(", ".join(f"{float(v):g}" for v in (param["default"] or ())))
            bornes = param["count"] or [0, 0]
            champ.setPlaceholderText(tr("console.formulaire.liste_indice",
                                        min=bornes[0], max=bornes[1]))
            return champ
        champ = EntierSansMolette() if kind == "int" else DecimalSansMolette()
        # Volontairement PLUS LARGES que les bornes du contrat, et pas seulement quand le contrat
        # n'en donne pas. Un QSpinBox écrête en silence : réglé sur [0 ; 0.99], il transforme un
        # « 5 » saisi en « 0.99 » et l'envoie sans un mot. L'étudiant croit avoir demandé 5, le
        # moteur reçoit 0.99, et personne ne lui dit pourquoi 5 était impossible. C'est le moteur
        # qui refuse, avec sa raison — c'est la règle de ce fichier, et l'écrêtage la contournait.
        champ.setRange(-1e9, 1e9)
        if kind != "int":
            champ.setDecimals(3)
            champ.setSingleStep(0.05)
        champ.setValue(param["default"] if param["default"] is not None else 0)
        return champ

    def set_values(self, values):
        """Recharge les champs depuis l'état du moteur — appelé quand les réglages EN VIGUEUR changent.

        Donc pas après un refus : un refus ne change rien au moteur, et la saisie fautive reste
        sous les yeux pour être corrigée plutôt qu'à retaper. C'est `show_refus()` qui se charge
        de dire, dans le même mouvement, ce qui reste réellement en vigueur.
        """
        for param in self.params:
            if param["key"] not in values:
                continue
            champ, valeur = self.champs[param["key"]], values[param["key"]]
            if param["kind"] == "bool":
                champ.setChecked(bool(valeur))
            elif param["kind"] == "choice":
                champ.setCurrentText(str(valeur))
            elif param["kind"] == "float_list":
                champ.setText(", ".join(f"{float(v):g}" for v in valeur))
            else:
                champ.setValue(valeur)

    def remplir(self, cle, valeurs):
        """Écrit une proposition dans un champ, SANS l'appliquer.

        L'étudiant voit ce qu'on lui propose et clique « Appliquer » lui-même. Appliquer à sa
        place lui retirerait la seule occasion de comprendre ce qui vient de changer.

        Aiguille sur `kind`, comme `set_values` : un `setText` à l'aveugle lève `AttributeError`
        dès que `proposes` désigne un champ qui n'en a pas (un `QSpinBox`, par exemple). Un type
        non géré ne fait rien plutôt que de lever — dans le fil Qt, une exception ici arrêterait
        toute la console.
        """
        champ = self.champs.get(cle)
        param = self._params_par_cle.get(cle)
        if champ is None or param is None:
            return
        if param["kind"] == "bool":
            champ.setChecked(bool(valeurs))
        elif param["kind"] == "choice":
            champ.setCurrentText(str(valeurs))
        elif param["kind"] == "float_list":
            champ.setText(", ".join(f"{float(v):g}" for v in valeurs))
        elif param["kind"] in ("float", "int"):
            champ.setValue(valeurs)

    def values(self):
        """Ce que l'utilisateur a saisi, tel quel. Aucune conversion « intelligente ».

        Une liste illisible part en texte brut : c'est le moteur qui dira « liste de nombres
        attendue », avec les mêmes mots que pour toutes les autres erreurs.
        """
        out = {}
        for param in self.params:
            champ = self.champs[param["key"]]
            if param["kind"] == "bool":
                out[param["key"]] = champ.isChecked()
            elif param["kind"] == "choice":
                # `currentText()` ne rend jamais qu'une CHAÎNE — correct pour `model`, dont les
                # choix SONT des chaînes (des chemins), mais faux pour `trials_per_class` (la
                # calibration MI), dont les choix sont des ENTIERS (10, 14, 18, 26) : soumettre
                # "14" au lieu de 14 est refusé par `contract.validate` (`"14" not in (10, 14,
                # 18, 26)`), en silence pour l'étudiant jusqu'à ce qu'il lise le refus. On
                # retrouve donc le choix d'ORIGINE par sa représentation textuelle, pour rendre
                # au moteur le type qu'il a lui-même déclaré dans `param["choices"]`.
                texte = champ.currentText()
                correspond = [c for c in param["choices"] if str(c) == texte]
                out[param["key"]] = correspond[0] if correspond else texte
            elif param["kind"] == "float_list":
                morceaux = [m.strip() for m in champ.text().split(",") if m.strip()]
                try:
                    out[param["key"]] = [float(m) for m in morceaux]
                except ValueError:
                    out[param["key"]] = champ.text()      # tel quel : le moteur refusera
            else:
                out[param["key"]] = champ.value()
        return out

    def show_confirmation(self, texte):
        """Un SUCCÈS : accepté, sans réserve. Vert — la couleur ne dit QUE ça.

        Distinct de `show_avertissement` (orange), qui dit « accepté, MAIS ». Confondre les deux
        fait lire un succès comme un problème : c'est le retour de séance du 2026-09-22 sur le
        message « réglage RETENU », qui n'annonce aucune réserve — juste un fait de calendrier.
        """
        self.confirmation.setText(texte or "")
        if texte:
            self.refus.setText("")
            self.avertissement.setText("")

    def show_refus(self, reason):
        """Un REFUS : ce qui vient d'être soumis n'a PAS été accepté."""
        self.refus.setText(reason or "")
        if reason:
            self.confirmation.setText("")
            # Un refus frais rend caduc tout avertissement affiché avant lui — il parlait d'un
            # réglage qu'on est en train de remplacer par celui-ci, refusé.
            self.avertissement.setText("")

    def show_avertissement(self, texte):
        """Un AVERTISSEMENT : ce qui vient d'être soumis a été ACCEPTÉ, mais mérite une réserve.

        `show_refus` et `show_avertissement` s'effacent mutuellement dès que l'un des deux a un
        vrai message à montrer — un seul est vrai à la fois. Mais un avertissement VIDE (le cas
        courant : proposition acceptée sans réserve) ne touche PAS `refus` : sinon un « Proposer »
        réussi effacerait le rappel « en vigueur : … » qu'un refus précédent affichait, sans rien
        mettre à la place.
        """
        self.avertissement.setText(texte or "")
        if texte:
            self.refus.setText("")
            self.confirmation.setText("")

    def set_choices(self, cle, choix, garder=True):
        """Recharge la liste d'un champ « choice » sans reconstruire le formulaire.

        Nécessaire parce qu'une calibration fait APPARAÎTRE un modèle : la liste résolue à
        l'ouverture de la page devient fausse à la seconde où la séance se termine, et
        reconstruire tout le formulaire perdrait la saisie en cours dans les autres champs.

        ⚠️ N'est PAS appelée à chaque rafraîchissement : résoudre les choix du réglage `model`
        lit le disque (`joblib.load` par fichier). Une version antérieure de ce projet a mis
        30 % d'un cœur sur le fil Qt en résolvant un catalogue dix fois par seconde. On appelle
        ceci sur ÉVÉNEMENT — entrée dans la page, fin d'une calibration.
        """
        champ = self.champs.get(cle)
        param = self._params_par_cle.get(cle)
        if champ is None or param is None or param["kind"] != "choice":
            return
        courant = champ.currentText()
        champ.blockSignals(True)
        champ.clear()
        champ.addItems([str(c) for c in choix])
        if garder and courant in [str(c) for c in choix]:
            champ.setCurrentText(courant)
        champ.blockSignals(False)
