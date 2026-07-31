"""Le formulaire d'un mode, GÉNÉRÉ depuis son contrat. Il ne valide rien : le moteur s'en charge.

C'est délibéré, et c'est la règle de conception la plus importante de la console : aucune logique
ici que le moteur ne possède pas déjà. Une validation recopiée côté interface diverge tôt ou tard
de celle du moteur, et le jour où elle diverge, elle laisse passer un réglage qui ne décodera
rien — sans erreur, comme toujours avec ce genre de panne.

Le formulaire envoie donc, et affiche la RAISON du refus telle que le moteur l'a formulée.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)


class ParamsForm(QWidget):
    """Un champ par `Param`, plus son aide, plus un bouton et une ligne de refus."""

    appliquer = Signal(dict)
    proposer = Signal(str)      # la clé du réglage qui en PROPOSE un autre

    def __init__(self, params):
        super().__init__()
        self.params = list(params)
        self.champs = {}
        self.boutons_proposer = {}      # {clé : bouton} — pour qu'un smoke puisse le CLIQUER
        self._params_par_cle = {p["key"]: p for p in self.params}

        formulaire = QFormLayout()
        for param in self.params:
            champ = self._champ(param)
            self.champs[param["key"]] = champ
            etiquette = param["label"] + (f" ({param['unit']})" if param["unit"] else "")
            formulaire.addRow(etiquette, champ)
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
                aide = QLabel(param["help"])
                aide.setWordWrap(True)
                aide.setStyleSheet("color: #8a8f9c; font-size: 11px;")
                formulaire.addRow("", aide)

        self.bouton = QPushButton("Appliquer")
        self.bouton.clicked.connect(lambda: self.appliquer.emit(self.values()))
        self.refus = QLabel("")
        self.refus.setWordWrap(True)
        self.refus.setStyleSheet("color: #e2603f;")
        # Un avertissement dit qu'un réglage a été ACCEPTÉ, avec réserve — PAS refusé. Étiquette
        # séparée, couleur différente : le rouge de `refus` sur un succès ferait passer une
        # proposition acceptée pour une panne.
        self.avertissement = QLabel("")
        self.avertissement.setWordWrap(True)
        self.avertissement.setStyleSheet("color: #b8860b;")

        bas = QHBoxLayout()
        bas.addWidget(self.bouton)
        bas.addStretch(1)

        # `None` quand le mode a des réglages : un QLabel construit sans parent serait une
        # fenêtre de premier niveau en Qt, pas un widget inerte.
        self.vide = None if self.params else QLabel("aucun réglage pour ce mode")
        layout = QVBoxLayout(self)
        if self.vide is not None:
            layout.addWidget(self.vide)
        layout.addLayout(formulaire)
        layout.addLayout(bas)
        layout.addWidget(self.refus)
        layout.addWidget(self.avertissement)

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

    def show_refus(self, reason):
        """Un REFUS : ce qui vient d'être soumis n'a PAS été accepté."""
        self.refus.setText(reason or "")
        if reason:
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
