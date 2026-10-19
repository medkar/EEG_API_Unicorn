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
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QSpinBox, QStyle, QStyledItemDelegate,
                               QStyleOptionComboBox, QStylePainter, QVBoxLayout, QWidget)

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

    Qt fait tourner la valeur d'une liste ou d'un champ numérique sous la souris : en faisant
    défiler une page de réglages, on changerait en passant un seuil ou un modèle, sans le voir.
    `ignore()` renvoie l'événement au parent — la zone qui défile.
    """

    def wheelEvent(self, event):  # noqa: N802 - nom imposé par Qt
        event.ignore()


def texte_affiche(texte):
    """Ce qu'une liste MONTRE d'un choix : le nom du fichier pour un chemin, le texte sinon."""
    return os.path.basename(texte) if ("/" in texte or "\\" in texte) else texte


class _NomDeFichier(QStyledItemDelegate):
    """Les lignes de la liste dépliée, réduites au nom du fichier (cf. `ListeSansMolette`)."""

    def displayText(self, valeur, locale):  # noqa: N802 - nom imposé par Qt
        return texte_affiche(super().displayText(valeur, locale))


class ListeSansMolette(_SansMolette, QComboBox):
    """Une liste qui MONTRE le nom du fichier, et dont la largeur ne dépend pas de ses choix.

    Afficher le chemin complet d'un modèle (~1 150 px) ferait déborder les réglages d'un écran de
    portable, et la page défilerait DE CÔTÉ. Le TEXTE de chaque ligne reste le chemin complet —
    c'est lui que `ParamsForm.values()` envoie au moteur, et lui que les pages comparent : seul
    le dessin change. Le chemin entier reste lisible au survol de la ligne.
    """

    LARGEUR_CAR = 30        # la largeur demandée, en caractères — assez pour un nom de modèle

    def __init__(self):
        super().__init__()
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(self.LARGEUR_CAR)
        self.setItemDelegate(_NomDeFichier(self))

    def remplir_choix(self, choix, libelles=()):
        """Ajoute les choix, avec le texte COMPLET en bulle quand la ligne n'en montre qu'une part.

        Avec des `libelles` (« un écran »), la ligne MONTRE le libellé et garde le choix
        (« ecran ») en donnée : c'est lui que `ParamsForm.values()` envoie au moteur.
        """
        for i, valeur in enumerate(choix):
            if libelles:
                self.addItem(str(libelles[i]), valeur)
                continue
            texte = str(valeur)
            self.addItem(texte)
            if texte_affiche(texte) != texte:
                self.setItemData(self.count() - 1, texte, Qt.ToolTipRole)

    def paintEvent(self, _evenement):  # noqa: N802 - nom imposé par Qt
        peintre = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        peintre.drawComplexControl(QStyle.CC_ComboBox, option)
        zone = self.style().subControlRect(QStyle.CC_ComboBox, option,
                                           QStyle.SC_ComboBoxEditField, self)
        option.currentText = self.fontMetrics().elidedText(
            texte_affiche(option.currentText), Qt.ElideMiddle, max(0, zone.width()))
        peintre.drawControl(QStyle.CE_ComboBoxLabel, option)


class ChoixRadio(_SansMolette, QWidget):
    """Un choix FERMÉ à libellés (« un écran » / « des cibles physiques »), en boutons radio.

    Toutes les options restent visibles d'un coup d'œil, sans ouvrir de menu. Il offre la même
    interface que la liste pour ce que le formulaire en utilise (`findData`, `setCurrentIndex`,
    `currentData`, `currentText`, `currentIndexChanged`) : le formulaire, la page et leurs
    autotests le lisent comme une liste.
    """

    currentIndexChanged = Signal(int)

    def __init__(self, choix, libelles):
        super().__init__()
        self._choix = list(choix)
        self._groupe = QButtonGroup(self)
        rang = QHBoxLayout(self)
        rang.setContentsMargins(0, 0, 0, 0)
        for i, libelle in enumerate(libelles):
            bouton = QRadioButton(str(libelle))
            self._groupe.addButton(bouton, i)
            rang.addWidget(bouton)
        rang.addStretch(1)
        if self._choix:
            self._groupe.button(0).setChecked(True)
        self._groupe.idToggled.connect(self._coche)

    def _coche(self, i, coche):
        if coche:
            self.currentIndexChanged.emit(i)

    def findData(self, valeur):  # noqa: N802 - même nom que QComboBox
        return self._choix.index(valeur) if valeur in self._choix else -1

    def setCurrentIndex(self, i):  # noqa: N802
        self._groupe.button(i).setChecked(True)

    def currentIndex(self):  # noqa: N802
        return self._groupe.checkedId()

    def currentData(self):  # noqa: N802
        i = self._groupe.checkedId()
        return self._choix[i] if i >= 0 else None

    def currentText(self):  # noqa: N802
        bouton = self._groupe.checkedButton()
        return bouton.text() if bouton is not None else ""


class EntierSansMolette(_SansMolette, QSpinBox):
    pass


class DecimalSansMolette(_SansMolette, QDoubleSpinBox):
    pass


class ListeDeTextes(QWidget):
    """Un réglage « text_list » : un NOMBRE, puis autant de champs que ce nombre.

    Pensé pour les tâches du Motor Imagery : 2 tâches, deux champs à remplir ; 3 tâches, trois
    champs. Les champs au-delà du nombre sont CACHÉS, pas détruits : passer
    de 3 à 2 puis revenir à 3 rend la troisième tâche telle qu'elle était tapée. Aucune
    validation ici — un champ vide ou un doublon part au moteur, qui le refuse avec sa raison.
    """

    def __init__(self, compte, defaut):
        super().__init__()
        mini, maxi = compte or (1, max(1, len(defaut or ())))
        self.nombre = EntierSansMolette()
        self.nombre.setRange(int(mini), int(maxi))
        self.nombre.setPrefix(tr("console.formulaire.nombre"))
        self.textes = []
        colonne = QVBoxLayout(self)
        colonne.setContentsMargins(0, 0, 0, 0)
        colonne.addWidget(self.nombre)
        for rang in range(1, int(maxi) + 1):
            champ = QLineEdit()
            champ.setPlaceholderText(tr("console.formulaire.texte_n", n=rang))
            self.textes.append(champ)
            colonne.addWidget(champ)
        self.nombre.valueChanged.connect(self._montrer)
        self.remplir(defaut or ())

    def _montrer(self, n):
        for rang, champ in enumerate(self.textes):
            champ.setVisible(rang < n)

    def remplir(self, valeurs):
        valeurs = [str(v) for v in valeurs]
        for champ, texte in zip(self.textes, valeurs):
            champ.setText(texte)
        self.nombre.setValue(len(valeurs))
        self._montrer(self.nombre.value())

    def valeurs(self):
        return [champ.text() for champ in self.textes[:self.nombre.value()]]


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
        self.lecture_seule = set()      # les clés figées par la page (cf. `figer`)
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
            # explique. Au bout de la ligne, elle se lirait comme une annexe du champ.
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
                # L'aide vit dans une bulle « ⓘ » juste APRÈS le libellé, lue au survol : une
                # ligne grise sous chaque réglage ferait, sur la page c-VEP, un mur de trente
                # lignes. Rien n'est perdu — la bulle porte le texte ENTIER du contrat, et le
                # champ aussi.
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
        # ⚠️ Aucun réglage = rien à appliquer, donc pas de bouton : il soumettrait un
        # dictionnaire VIDE, que le moteur accepterait sans rien changer, et l'élève aurait
        # cliqué sur quelque chose qui a l'air de faire quelque chose.
        #
        # Cette règle ne couvre QUE le formulaire vide — la page du mode « Brut ». Les deux
        # autres familles de pages cachent le bouton ELLES-MÊMES, sans condition, parce que
        # leurs réglages partent avec « Commencer », jamais avec « Appliquer » :
        # `console/calib_page.py` (les entraînements) et `console/mesure_page.py` (une mesure se
        # règle avant de partir, son formulaire part avec `start_mesure`).
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
        # ⚠️ TROIS canaux, pas deux. Un réglage RETENU sur un mode arrêté a été accepté : rien
        # ne cloche, il n'y a aucune réserve à émettre, et l'orange le ferait lire comme un
        # problème. La nuance « pas encore en vigueur » est dans le TEXTE ; la couleur ne répond
        # qu'à une question : est-ce que ça a été accepté. `console/mesure_page.py` dit VERT pour
        # le même événement (« pic appliqué ») : un fait, une couleur.
        self.confirmation = QLabel("")
        self.confirmation.setWordWrap(True)
        self.confirmation.setStyleSheet("color: #3fae5a;")

        # « Rétablir les valeurs par défaut », en bas à droite, partout où il y a des réglages.
        # Les défauts sont ceux que le MOTEUR déclare dans son contrat
        # (`param["default"]`) : la console n'en tient aucune copie. Il REMPLIT les champs, il
        # n'applique rien — comme « Proposer » : ce qui part au moteur part avec « Appliquer » ou
        # « Commencer », pour que l'élève voie ce qui change avant que ça change.
        self.bouton_defauts = QPushButton(tr("console.formulaire.defauts"))
        self.bouton_defauts.setToolTip(infobulle(tr("console.formulaire.defauts_aide")))
        self.bouton_defauts.clicked.connect(self.retablir_defauts)

        bas = QHBoxLayout()
        bas.addWidget(self.bouton)
        bas.addStretch(1)
        bas.addWidget(self.bouton_defauts)
        self.ligne_bas = bas
        self._montrer_defauts()

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

        # Un réglage qui ne compte que sous condition (`actif_si`) se grise quand elle tombe : le
        # rafraîchissement de l'écran, quand les cibles du SSVEP sont des LED. La règle est au
        # contrat ; ce formulaire ne fait que la lire.
        for param in self.params:
            source = self.champs.get((param.get("actif_si") or [None])[0])
            if isinstance(source, (QComboBox, ChoixRadio)):
                source.currentIndexChanged.connect(self._maj_actifs)
            elif isinstance(source, QCheckBox):
                source.toggled.connect(self._maj_actifs)
        self._maj_actifs()

    @staticmethod
    def _choisir(param, champ, valeur):
        """Sélectionne `valeur` dans une liste : par sa DONNÉE quand les lignes montrent un libellé."""
        if param.get("libelles"):
            i = champ.findData(valeur)
            if i >= 0:
                champ.setCurrentIndex(i)
        else:
            champ.setCurrentText(str(valeur))

    def _maj_actifs(self, *_):
        """Grise chaque réglage dont la condition `actif_si` ne tient pas avec ce qui est à l'écran."""
        valeurs = self.values()
        for param in self.params:
            regle = param.get("actif_si")
            if regle:
                actif = valeurs.get(regle[0]) == regle[1]
                self.champs[param["key"]].setEnabled(actif and param["key"] not in self.lecture_seule)

    def figer(self, cle):
        """Rend le champ `cle` non modifiable : il MONTRE une valeur qui se règle ailleurs.

        La page de test y range les réglages qui viennent du mode : les rétablir ici afficherait
        des défauts qui ne sont pas en vigueur. `retablir_defauts` les laisse donc tels quels, et le
        bouton disparaît s'il ne reste rien à rétablir.
        """
        champ = self.champs.get(cle)
        if champ is None:
            return
        # Désactivé EXPLICITEMENT : une page qui réactive le formulaire entier après une séance
        # ne réactive pas un enfant qu'on a désactivé lui-même.
        champ.setEnabled(False)
        self.lecture_seule.add(cle)
        self._montrer_defauts()

    def _montrer_defauts(self):
        """Pas de bouton quand il n'y a rien à rétablir : un bouton sans effet est un mensonge."""
        self.bouton_defauts.setVisible(
            any(p["key"] not in self.lecture_seule for p in self.params))

    def retablir_defauts(self):
        """Remet chaque champ MODIFIABLE à son défaut. N'applique rien."""
        for param in self.params:
            cle = param["key"]
            if cle in self.lecture_seule:
                continue
            if param["kind"] == "choice" and param["default"] is None:
                # Un choix sans défaut déclaré (les modèles) : le moteur prend le PREMIER de la
                # liste, le plus récent — `Param.default_now`. Même règle ici.
                self.champs[cle].setCurrentIndex(0)
            elif param["default"] is not None:
                self.remplir(cle, param["default"])

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
        if kind == "choice" and param.get("libelles"):
            # Un choix fermé dont le contrat nomme chaque option : des boutons radio.
            champ = ChoixRadio(param["choices"], param["libelles"])
            if param["default"] is not None:
                self._choisir(param, champ, param["default"])
            return champ
        if kind == "choice":
            champ = ListeSansMolette()
            champ.remplir_choix(param["choices"], param.get("libelles") or ())
            # Sans ce réglage, un QComboBox fraîchement rempli affiche son PREMIER élément. C'est
            # invisible quand le défaut est EN PREMIÈRE position (`model`, dont le défaut est
            # toujours choices_now()[0]), mais faux dès qu'il est ailleurs dans la liste
            # (`trials_per_class` de la calibration MI vaut MI_SESSIONS[1]) : le formulaire
            # afficherait 10 essais/classe alors que le contrat dit 14 — un mensonge visuel dès
            # la première ouverture de la page.
            if param["default"] is not None:
                self._choisir(param, champ, param["default"])
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
        if kind == "text_list":
            return ListeDeTextes(param["count"], param["default"])
        champ = EntierSansMolette() if kind == "int" else DecimalSansMolette()
        # Volontairement PLUS LARGES que les bornes du contrat, et pas seulement quand le contrat
        # n'en donne pas. Un QSpinBox écrête en silence : réglé sur [0 ; 0.99], il transforme un
        # « 5 » saisi en « 0.99 » et l'envoie sans un mot. L'élève croit avoir demandé 5, le
        # moteur reçoit 0.99, et personne ne lui dit pourquoi 5 était impossible. C'est le moteur
        # qui refuse, avec sa raison — c'est la règle de ce fichier, que l'écrêtage contournerait.
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
                self._choisir(param, champ, valeur)
            elif param["kind"] == "float_list":
                champ.setText(", ".join(f"{float(v):g}" for v in valeur))
            elif param["kind"] == "text_list":
                champ.remplir(valeur)
            else:
                champ.setValue(valeur)

    def remplir(self, cle, valeurs):
        """Écrit une proposition dans un champ, SANS l'appliquer.

        L'élève voit ce qu'on lui propose et clique « Appliquer » lui-même. Appliquer à sa
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
            self._choisir(param, champ, valeurs)
        elif param["kind"] == "float_list":
            champ.setText(", ".join(f"{float(v):g}" for v in valeurs))
        elif param["kind"] == "text_list":
            champ.remplir(valeurs)
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
            elif param["kind"] == "choice" and param.get("libelles"):
                out[param["key"]] = champ.currentData()   # le choix, pas son libellé
            elif param["kind"] == "choice":
                # `currentText()` ne rend jamais qu'une CHAÎNE — correct pour `model`, dont les
                # choix SONT des chaînes (des chemins), mais faux pour `trials_per_class` (la
                # calibration MI), dont les choix sont des ENTIERS (10, 14, 18, 26) : soumettre
                # "14" au lieu de 14 est refusé par `contract.validate` (`"14" not in (10, 14,
                # 18, 26)`). On retrouve donc le choix d'ORIGINE par sa représentation textuelle,
                # pour rendre au moteur le type qu'il a lui-même déclaré dans `param["choices"]`.
                texte = champ.currentText()
                correspond = [c for c in param["choices"] if str(c) == texte]
                out[param["key"]] = correspond[0] if correspond else texte
            elif param["kind"] == "float_list":
                morceaux = [m.strip() for m in champ.text().split(",") if m.strip()]
                try:
                    out[param["key"]] = [float(m) for m in morceaux]
                except ValueError:
                    out[param["key"]] = champ.text()      # tel quel : le moteur refusera
            elif param["kind"] == "text_list":
                out[param["key"]] = champ.valeurs()       # tels quels : le moteur refusera
            else:
                out[param["key"]] = champ.value()
        return out

    def show_confirmation(self, texte):
        """Un SUCCÈS : accepté, sans réserve. Vert — la couleur ne dit QUE ça.

        Distinct de `show_avertissement` (orange), qui dit « accepté, MAIS ». Confondre les deux
        fait lire un succès comme un problème : le message « réglage RETENU » n'annonce aucune
        réserve, juste un fait de calendrier.
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
        lit le disque (`joblib.load` par fichier), et le faire dix fois par seconde met environ
        30 % d'un cœur sur le fil Qt (mesuré). On appelle ceci sur ÉVÉNEMENT — entrée dans la
        page, fin d'une calibration.
        """
        champ = self.champs.get(cle)
        param = self._params_par_cle.get(cle)
        if champ is None or param is None or param["kind"] != "choice":
            return
        courant = champ.currentText()
        champ.blockSignals(True)
        champ.clear()
        champ.remplir_choix(choix)
        if garder and courant in [str(c) for c in choix]:
            champ.setCurrentText(courant)
        champ.blockSignals(False)
