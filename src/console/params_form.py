"""Le formulaire d'un mode, GÉNÉRÉ depuis son contrat. Il ne valide rien : le moteur s'en charge.

C'est délibéré, et c'est la règle de conception la plus importante de la console : aucune logique
ici que le moteur ne possède pas déjà. Une validation recopiée côté interface diverge tôt ou tard
de celle du moteur, et le jour où elle diverge, elle laisse passer un réglage qui ne décodera
rien — sans erreur, comme toujours avec ce genre de panne.

Le formulaire envoie donc, et affiche la RAISON du refus telle que le moteur l'a formulée.
"""

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)


def premiere_phrase(texte):
    """La première phrase de `texte`, ou `texte` entier si la couper n'apporte rien.

    Les aides du contrat sont écrites en deux temps : ce que le réglage FAIT, puis pourquoi il est
    ainsi. La page c-VEP en porte 2 719 caractères sur six champs — un mur de gris de plus de
    trente lignes, qui pousse le bloc « Brancher un client » hors de la fenêtre. C'est le constat
    1.10 de la recette (2026-08-17) : « tronqué en bas, et trop verbeux pour un étudiant ».

    On coupe donc au premier point, **et seulement si la coupe est franche** : trop courte (moins
    de 30 caractères) elle ne dirait rien, trop tardive (plus de 60 % du texte) elle ne gagnerait
    rien. Le texte entier ne disparaît jamais — il reste en infobulle, et le bouton « Aide
    détaillée » le remet en place d'un clic.
    """
    coupe = re.search(r"(?<=[.!?])\s", texte)
    if coupe and 30 <= coupe.start() + 1 <= len(texte) * 0.6:
        return texte[:coupe.start() + 1]
    return texte


class ParamsForm(QWidget):
    """Un champ par `Param`, plus son aide, plus un bouton et une ligne de refus."""

    appliquer = Signal(dict)
    proposer = Signal(str)      # la clé du réglage qui en PROPOSE un autre

    def __init__(self, params):
        super().__init__()
        self.params = list(params)
        self.champs = {}
        self.boutons_proposer = {}      # {clé : bouton} — pour qu'un smoke puisse le CLIQUER
        self.aides = {}                 # {clé : (QLabel, texte complet)}
        self.lignes = {}                # {clé : la ligne du champ} — cf. `ajouter_a_cote`
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
            formulaire.addRow(etiquette, ligne)
            if param.get("proposes"):
                bouton = QPushButton(f"Proposer « {param['proposes']} »")
                bouton.clicked.connect(lambda _c=False, k=param["key"]: self.proposer.emit(k))
                formulaire.addRow("", bouton)
                self.boutons_proposer[param["key"]] = bouton
            if param["key"] == "refresh_hz":
                ecran = QApplication.primaryScreen()
                if ecran is not None and ecran.refreshRate() > 0:
                    detecte = QLabel(f"cette fenêtre est sur un écran à "
                                     f"{ecran.refreshRate():g} Hz — mais c'est le rafraîchissement "
                                     f"de l'écran qui AFFICHE les cibles qu'il faut mettre ici")
                    detecte.setWordWrap(True)
                    detecte.setStyleSheet("color: #8a8f9c; font-size: 11px;")
                    formulaire.addRow("", detecte)
            if param["help"]:
                aide = QLabel(premiere_phrase(param["help"]))
                aide.setWordWrap(True)
                aide.setStyleSheet("color: #8a8f9c; font-size: 11px;")
                # L'infobulle porte le texte ENTIER, toujours : le bouton ci-dessous rend le
                # détail visible pour qui le cherche, l'infobulle le rend accessible sans le
                # chercher. Rien de ce que le contrat écrit n'est perdu par cet écran.
                aide.setToolTip(param["help"])
                champ.setToolTip(param["help"])
                self.aides[param["key"]] = (aide, param["help"])
                formulaire.addRow("", aide)

        self.bouton = QPushButton("Appliquer")
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
        # « Aide détaillée » : présent seulement si au moins une aide a VRAIMENT été raccourcie.
        # Un bouton qui ne changerait rien à l'écran est un réglage-décor, et ce projet en a déjà
        # payé le prix. `None` quand il n'y a rien à déplier — jamais un widget caché sans parent.
        self.detail = None
        if any(premiere_phrase(t) != t for _, t in self.aides.values()):
            self.detail = QCheckBox("Aide détaillée")
            self.detail.setToolTip("Affiche le POURQUOI de chaque réglage, en plus de ce qu'il "
                                   "fait. Le texte entier est aussi en infobulle.")
            self.detail.toggled.connect(self._deplier)
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
        if self.detail is not None:
            bas.addWidget(self.detail)
        bas.addStretch(1)

        # `None` quand il y a des réglages : un QLabel construit sans parent serait une fenêtre
        # de premier niveau en Qt, pas un widget inerte.
        # ⚠️ « ici » et pas « pour ce mode » : ce formulaire sert aussi les CALIBRATIONS et les
        # MESURES, qui ne sont pas des modes. Le contrôle alpha, qui n'expose délibérément aucun
        # réglage (ses durées font corps avec son repère chiffré), est le premier à l'afficher.
        self.vide = None if self.params else QLabel("aucun réglage à changer ici")
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

    def _deplier(self, ouvert):
        """Bascule les aides entre leur première phrase et le texte du contrat, mot pour mot."""
        for aide, complet in self.aides.values():
            aide.setText(complet if ouvert else premiere_phrase(complet))

    def _champ(self, param):
        kind = param["kind"]
        if kind == "bool":
            champ = QCheckBox()
            champ.setChecked(bool(param["default"]))
            return champ
        if kind == "choice":
            champ = QComboBox()
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
            champ.setPlaceholderText(f"entre {bornes[0]} et {bornes[1]} valeurs, séparées "
                                     f"par des virgules")
            return champ
        champ = QSpinBox() if kind == "int" else QDoubleSpinBox()
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
