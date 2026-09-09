"""L'écran de départ : sur quoi ouvre-t-on la session ? Casque, ou board de test.

Ce choix était un DRAPEAU À TAPER (`--synthetic`) jusqu'au 2026-09-09. C'était le dernier réglage
d'usage réel qui n'existait que sur la ligne de commande, et la règle du produit — *tout l'usage
réel se pilote depuis l'interface* — ne souffre pas d'exception : l'étudiant qui n'a pas de casque
sous la main est exactement celui qui n'ouvrira jamais un terminal.

⚠️ **JAMAIS DE REPLI AUTOMATIQUE, et c'est la seule chose sérieuse de ce fichier.** Un casque
introuvable ne doit PAS faire basculer en douce sur le board de test : on enregistrerait une séance
entière de signal fabriqué en croyant tenir du vrai, et rien dans les fichiers produits ne le
dirait. Ce dépôt a déjà dû corriger un écran qui laissait croire qu'un board de test était observé
(« Say plainly when the board is fake »). Le choix est donc EXPLICITE, et le bandeau le répète tant
que la console tourne.

Vérifié : au 2026-09-09, aucun repli n'existe dans `core/acquisition.py` ni `core/server.py`. La
garde de ce fichier — et son test dans `console/app.py --smoke` — sert à ce qu'on n'en ajoute pas
un le jour où un casque récalcitrant fera perdre dix minutes à quelqu'un.
"""

import os
import sys

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QRadioButton,  # noqa: E402
                               QVBoxLayout)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

UNICORN = "unicorn"
SYNTHETIQUE = "synthetic"

# Ce que chaque source est, dit à quelqu'un qui n'a pas lu la documentation. Le second texte est
# volontairement dissuasif : le board de test produit un signal qui RESSEMBLE à de l'EEG, et c'est
# précisément ce qui le rend dangereux si on oublie qu'on est dessus.
DESCRIPTIONS = {
    UNICORN: ("Casque Unicorn Hybrid Black",
              "8 voies sèches à 250 Hz, par Bluetooth. Allume le casque et vérifie qu'il est "
              "appairé avant de continuer."),
    SYNTHETIQUE: ("Board de test, SANS casque",
                  "Signal FABRIQUÉ par BrainFlow. Il sert à vérifier que le produit tourne — "
                  "jamais à mesurer quoi que ce soit : aucun cerveau ne le produit, et il "
                  "ressemble assez à de l'EEG pour qu'on l'oublie."),
}


class DialogueDemarrage(QDialog):
    """Le choix de la source, avant que le moteur n'ouvre quoi que ce soit.

    Rend `UNICORN`, `SYNTHETIQUE`, ou `None` si l'utilisateur ferme la fenêtre — auquel cas la
    console ne démarre pas. Ouvrir « par défaut » sur l'un des deux serait le repli silencieux que
    la docstring du module interdit, avec un clic de moins.
    """

    def __init__(self, parent=None, defaut=UNICORN):
        super().__init__(parent)
        self.setWindowTitle("EEG_API_Unicorn — sur quoi ouvrir la session ?")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        intro = QLabel("Ce choix ne se change pas en cours de séance : rouvrir la session "
                       "redémarre l'amplificateur, et C3/Cz saturent à la réouverture.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #8a8f9c;")
        layout.addWidget(intro)

        self.boutons = {}
        for cle in (UNICORN, SYNTHETIQUE):
            titre, aide = DESCRIPTIONS[cle]
            radio = QRadioButton(titre)
            radio.setChecked(cle == defaut)
            etiquette = QLabel(aide)
            etiquette.setWordWrap(True)
            etiquette.setStyleSheet("color: #8a8f9c; font-size: 11px; margin-left: 20px;")
            layout.addWidget(radio)
            layout.addWidget(etiquette)
            self.boutons[cle] = radio

        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def source(self):
        """La source retenue, ou None si la fenêtre a été fermée sans choisir."""
        if self.result() != QDialog.Accepted:
            return None
        for cle, radio in self.boutons.items():
            if radio.isChecked():
                return cle
        return None


def choisir_source(defaut=UNICORN, parent=None):
    """Ouvre le dialogue et rend la source, ou None. Fonction de commodité pour `app.run`."""
    dlg = DialogueDemarrage(parent=parent, defaut=defaut)
    dlg.exec()
    return dlg.source()


def _selftest():
    """Qt en `offscreen` : le dialogue se construit et répond, sans écran."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from core.config import use_utf8_console
    use_utf8_console()
    app = QApplication.instance() or QApplication([])
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    dlg = DialogueDemarrage(defaut=UNICORN)
    chk(dlg.boutons[UNICORN].isChecked() and not dlg.boutons[SYNTHETIQUE].isChecked(),
        "le défaut proposé est le CASQUE : c'est ce qu'on veut faire le plus souvent, et le "
        "board de test doit rester un geste délibéré")

    # ⚠️ Fermer la fenêtre ne choisit RIEN. Ouvrir « par défaut » sur l'une des deux sources
    # serait le repli silencieux que ce module interdit, avec un clic de moins : on croirait
    # avoir choisi le casque et on enregistrerait du signal fabriqué.
    chk(dlg.source() is None,
        "sans acceptation, aucune source n'est rendue — la console ne démarre pas plutôt que de "
        "démarrer sur un choix que personne n'a fait")

    dlg.accept()
    chk(dlg.source() == UNICORN, f"après acceptation, la source choisie est rendue ({dlg.source()})")

    dlg2 = DialogueDemarrage(defaut=SYNTHETIQUE)
    dlg2.accept()
    chk(dlg2.source() == SYNTHETIQUE, f"…et l'autre aussi ({dlg2.source()})")

    # Les deux textes doivent être DIFFÉRENTS et dire ce que la source est. Le board de test
    # produit un signal qui ressemble à de l'EEG : un libellé tiède le ferait oublier.
    titre_u, aide_u = DESCRIPTIONS[UNICORN]
    titre_s, aide_s = DESCRIPTIONS[SYNTHETIQUE]
    chk(titre_u != titre_s and "SANS casque" in titre_s,
        f"le board de test s'annonce comme tel dans son TITRE ({titre_s})")
    chk("FABRIQUÉ" in aide_s and "jamais" in aide_s.lower(),
        "…et son aide dit que le signal est fabriqué et ne mesure rien — ce dépôt a déjà dû "
        "corriger un écran qui laissait croire qu'un board de test était observé")

    print(f"[demarrage] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
