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
            if param["key"] == "refresh_hz":
                ecran = QApplication.primaryScreen()
                if ecran is not None:
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

    def _champ(self, param):
        kind = param["kind"]
        if kind == "bool":
            champ = QCheckBox()
            champ.setChecked(bool(param["default"]))
            return champ
        if kind == "choice":
            champ = QComboBox()
            champ.addItems([str(c) for c in param["choices"]])
            return champ
        if kind == "float_list":
            # Une ligne de valeurs séparées par des virgules : c'est la MÊME écriture que
            # `--freqs 15,20,8.57` en ligne de commande, et le nombre d'éléments se règle en
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
        """
        champ = self.champs.get(cle)
        if champ is None:
            return
        champ.setText(", ".join(f"{float(v):g}" for v in valeurs))

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
                out[param["key"]] = champ.currentText()
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
        self.refus.setText(reason or "")
