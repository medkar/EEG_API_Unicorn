"""L'écran de départ : sur quoi ouvre-t-on la session ? Casque (lequel ?), ou board de test.

Ce choix était un DRAPEAU À TAPER (`--synthetic`) jusqu'au 2026-09-09, et le numéro du casque
l'était encore jusqu'au 2026-09-25 (`--serial`, faute de quoi le moteur ouvrait le casque écrit en
dur dans `core/config.py`). La règle du produit — *tout l'usage réel se pilote depuis
l'interface* — ne souffre pas d'exception : chaque étudiant vient avec SON casque, et celui qui
n'en a pas sous la main est exactement celui qui n'ouvrira jamais un terminal.

⚠️ **JAMAIS DE REPLI AUTOMATIQUE, et c'est la seule chose sérieuse de ce fichier.** Un casque
introuvable ne doit PAS faire basculer en douce sur le board de test : on enregistrerait une séance
entière de signal fabriqué en croyant tenir du vrai, et rien dans les fichiers produits ne le
dirait. Ce dépôt a déjà dû corriger un écran qui laissait croire qu'un board de test était observé
(« Say plainly when the board is fake »). Le choix est donc EXPLICITE, et le bandeau le répète tant
que la console tourne. Quand le casque refuse de s'ouvrir, la question est REPOSÉE, avec la raison
— jamais tranchée à la place de l'étudiant.

Vérifié : au 2026-09-09, aucun repli n'existe dans `core/acquisition.py` ni `core/server.py`. La
garde de ce fichier — et son test dans `console/app.py --smoke` — sert à ce qu'on n'en ajoute pas
un le jour où un casque récalcitrant fera perdre dix minutes à quelqu'un.

⚠️ **Le numéro n'est pas facultatif ici**, bien que BrainFlow le dise optionnel pour l'Unicorn :
sa documentation le déclare « important si plusieurs appareils sont au même endroit » — une salle
de TP — et ne dit pas ce qu'il fait SANS lui. On ne promet donc rien sur un champ vide.
"""

import os
import sys

from PySide6.QtCore import QEventLoop, QSettings, Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QLabel,  # noqa: E402
                               QProgressDialog, QRadioButton, QVBoxLayout)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import UNICORN_SERIAL  # noqa: E402
from core.i18n import tr  # noqa: E402

UNICORN = "unicorn"
SYNTHETIQUE = "synthetic"

# Combien de numéros de casque la console retient. Assez pour un poste partagé par un binôme ou
# deux, pas une liste qu'on fait défiler.
CASQUES_RETENUS = 5

# Ce que chaque source est, dit à quelqu'un qui n'a pas lu la documentation. Le second texte est
# volontairement dissuasif : le board de test produit un signal qui RESSEMBLE à de l'EEG, et c'est
# précisément ce qui le rend dangereux si on oublie qu'on est dessus.
DESCRIPTIONS = {
    UNICORN: (tr("console.demarrage.unicorn"), tr("console.demarrage.unicorn_aide")),
    SYNTHETIQUE: (tr("console.demarrage.synthetique"), tr("console.demarrage.synthetique_aide")),
}


class Memoire:
    """Les derniers numéros de casque OUVERTS AVEC SUCCÈS, du plus récent au plus ancien.

    Dans les préférences de l'utilisateur (`QSettings` : la base de registre sous Windows), pas
    dans le dépôt : c'est une commodité d'écran, propre à un poste, qui n'a rien à faire à côté
    des modèles de `data/` ni des séances de `seances/`. Un numéro n'y entre qu'APRÈS une
    ouverture réussie — une faute de frappe ne se propose pas deux fois.
    """

    def __init__(self, reglages=None):
        self._reglages = reglages if reglages is not None else QSettings("EEG_API_Unicorn",
                                                                         "console")

    def casques(self):
        valeur = self._reglages.value("casques", [])
        if isinstance(valeur, str):          # QSettings rend une chaîne seule pour une liste d'un
            valeur = [valeur]                # élément, selon la plateforme
        return [str(v) for v in (valeur or []) if str(v).strip()]

    def retenir(self, numero):
        numero = (numero or "").strip()
        if not numero:
            return
        liste = [numero] + [c for c in self.casques() if c != numero]
        self._reglages.setValue("casques", liste[:CASQUES_RETENUS])


class DialogueDemarrage(QDialog):
    """Le choix de la source — et du casque —, avant que le moteur n'ouvre quoi que ce soit.

    `source()` rend `UNICORN`, `SYNTHETIQUE`, ou `None` si l'utilisateur ferme la fenêtre — auquel
    cas la console ne démarre pas. Ouvrir « par défaut » sur l'un des deux serait le repli
    silencieux que la docstring du module interdit, avec un clic de moins. `numero()` rend le
    numéro de série saisi.

    `erreur` : la raison du refus PRÉCÉDENT, affichée en tête quand la question est reposée.
    """

    def __init__(self, parent=None, defaut=UNICORN, numero=None, erreur="", memoire=None):
        super().__init__(parent)
        self.setWindowTitle(tr("console.demarrage.titre"))
        self.setMinimumWidth(560)
        memoire = memoire if memoire is not None else Memoire()

        layout = QVBoxLayout(self)
        self.erreur = QLabel(erreur or "")
        self.erreur.setWordWrap(True)
        self.erreur.setStyleSheet("color: #e5484d;")
        self.erreur.setVisible(bool(erreur))
        layout.addWidget(self.erreur)

        intro = QLabel(tr("console.demarrage.intro"))
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
            if cle == UNICORN:
                # Le numéro, juste sous le casque qu'il désigne. Une liste MODIFIABLE : les derniers
                # casques ouverts sur ce poste, et la place d'en taper un nouveau.
                self.champ_numero = QComboBox()
                self.champ_numero.setEditable(True)
                connus = memoire.casques()
                self.champ_numero.addItems(connus)
                self.champ_numero.setCurrentText(numero or (connus[0] if connus
                                                            else UNICORN_SERIAL))
                self.champ_numero.setStyleSheet("margin-left: 20px;")
                aide_numero = QLabel(tr("console.demarrage.numero_aide"))
                aide_numero.setWordWrap(True)
                aide_numero.setStyleSheet("color: #8a8f9c; font-size: 11px; margin-left: 20px;")
                layout.addWidget(QLabel(tr("console.demarrage.numero")))
                layout.addWidget(self.champ_numero)
                layout.addWidget(aide_numero)

        self.manquant = QLabel("")
        self.manquant.setStyleSheet("color: #e5484d;")
        layout.addWidget(self.manquant)
        self.boutons[UNICORN].toggled.connect(self.champ_numero.setEnabled)
        self.champ_numero.setEnabled(self.boutons[UNICORN].isChecked())

        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def numero(self):
        return self.champ_numero.currentText().strip()

    def accept(self):
        """Refuse un casque SANS numéro : cf. la docstring du module."""
        if self.boutons[UNICORN].isChecked() and not self.numero():
            self.manquant.setText(tr("console.demarrage.numero_manquant"))
            return
        super().accept()

    def source(self):
        """La source retenue, ou None si la fenêtre a été fermée sans choisir."""
        if self.result() != QDialog.Accepted:
            return None
        for cle, radio in self.boutons.items():
            if radio.isChecked():
                return cle
        return None


def choisir_source(defaut=UNICORN, numero=None, erreur="", memoire=None, parent=None):
    """Ouvre le dialogue ; rend `(source, numéro)`, ou None s'il a été fermé sans choisir."""
    dlg = DialogueDemarrage(parent=parent, defaut=defaut, numero=numero, erreur=erreur,
                            memoire=memoire)
    dlg.exec()
    source = dlg.source()
    return None if source is None else (source, dlg.numero() if source == UNICORN else None)


def attendre_ouverture(engine, vivant, texte, intervalle_ms=100):
    """Attend que le moteur ait OUVERT le casque. Rend « ouvert », « echec » ou « abandon ».

    `vivant` : le prédicat du fil du moteur (`thread.is_alive`). L'ouverture Bluetooth prend
    quelques secondes, et un casque éteint fait mourir ce fil — c'est ce qui distingue l'échec
    de l'attente. « Abandonner » ferme la console : on ne peut pas interrompre BrainFlow en
    pleine ouverture, mais on n'oblige personne à regarder un sablier.
    """
    attente = QProgressDialog(texte, tr("console.demarrage.abandonner"), 0, 0)
    attente.setWindowTitle(tr("console.demarrage.titre"))
    attente.setWindowModality(Qt.ApplicationModal)
    attente.setMinimumDuration(0)
    boucle = QEventLoop()
    issue = {"etat": None}

    def sonder():
        if getattr(engine, "acquisition_ouverte", False):
            issue["etat"] = "ouvert"
        elif not vivant():
            issue["etat"] = "echec"
        elif attente.wasCanceled():
            issue["etat"] = "abandon"
        if issue["etat"] is not None:
            minuterie.stop()
            boucle.quit()

    minuterie = QTimer()
    minuterie.timeout.connect(sonder)
    minuterie.start(intervalle_ms)
    attente.show()
    sonder()
    if issue["etat"] is None:
        boucle.exec()
    attente.close()
    return issue["etat"]


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

    class _Reglages(dict):
        """Un `QSettings` en mémoire : l'autotest n'écrit RIEN dans la base de registre."""

        def value(self, cle, defaut=None):
            return self.get(cle, defaut)

        def setValue(self, cle, valeur):  # noqa: N802 - nom de l'API Qt
            self[cle] = valeur

    memoire = Memoire(_Reglages())
    dlg = DialogueDemarrage(defaut=UNICORN, memoire=memoire)
    chk(dlg.boutons[UNICORN].isChecked() and not dlg.boutons[SYNTHETIQUE].isChecked(),
        "le défaut proposé est le CASQUE : c'est ce qu'on veut faire le plus souvent, et le "
        "board de test doit rester un geste délibéré")
    chk(dlg.numero() == UNICORN_SERIAL and dlg.champ_numero.isEnabled(),
        f"sans casque retenu sur ce poste, le numéro proposé est celui de la configuration "
        f"({dlg.numero()})")

    # ⚠️ Fermer la fenêtre ne choisit RIEN. Ouvrir « par défaut » sur l'une des deux sources
    # serait le repli silencieux que ce module interdit, avec un clic de moins : on croirait
    # avoir choisi le casque et on enregistrerait du signal fabriqué.
    chk(dlg.source() is None,
        "sans acceptation, aucune source n'est rendue — la console ne démarre pas plutôt que de "
        "démarrer sur un choix que personne n'a fait")

    dlg.accept()
    chk(dlg.source() == UNICORN, f"après acceptation, la source choisie est rendue ({dlg.source()})")

    dlg2 = DialogueDemarrage(defaut=SYNTHETIQUE, memoire=memoire)
    chk(not dlg2.champ_numero.isEnabled(),
        "le numéro de série est grisé tant que le board de test est choisi")
    dlg2.accept()
    chk(dlg2.source() == SYNTHETIQUE, f"…et l'autre aussi ({dlg2.source()})")

    # Un casque SANS numéro est refusé, et le dialogue le dit au lieu de se fermer.
    vide = DialogueDemarrage(defaut=UNICORN, memoire=memoire)
    vide.champ_numero.setCurrentText("  ")
    vide.accept()
    chk(vide.result() != QDialog.Accepted and vide.manquant.text(),
        f"un casque sans numéro n'est pas accepté, et le dialogue dit pourquoi "
        f"({vide.manquant.text()!r})")

    # La MÉMOIRE : le dernier casque ouvert revient en tête, sans doublon, borné.
    for n in ("UN-A", "UN-B", "UN-A", "UN-C", "UN-D", "UN-E", "UN-F"):
        memoire.retenir(n)
    chk(memoire.casques() == ["UN-F", "UN-E", "UN-D", "UN-C", "UN-A"],
        f"les derniers casques ouverts, du plus récent au plus ancien, sans doublon, "
        f"{CASQUES_RETENUS} au plus ({memoire.casques()})")
    rappel = DialogueDemarrage(defaut=UNICORN, memoire=memoire)
    chk(rappel.numero() == "UN-F" and rappel.champ_numero.count() == CASQUES_RETENUS,
        f"…et le dialogue propose le DERNIER casque ouvert, les autres dans la liste "
        f"({rappel.numero()}, {rappel.champ_numero.count()})")

    # Quand la question est REPOSÉE après un échec, la raison est affichée — et la source reste
    # celle que l'étudiant avait choisie : on ne bascule pas pour lui sur le board de test.
    reposee = DialogueDemarrage(defaut=UNICORN, numero="UN-X", erreur="le casque ne répond pas",
                                memoire=memoire)
    chk(reposee.erreur.isVisibleTo(reposee) and "ne répond pas" in reposee.erreur.text()
        and reposee.boutons[UNICORN].isChecked() and reposee.numero() == "UN-X",
        "après un échec, la raison est affichée, et le casque et son numéro restent choisis — "
        "aucun repli sur le board de test")

    # L'ATTENTE de l'ouverture : les trois issues.
    class _Moteur:
        acquisition_ouverte = False

    ouvert = _Moteur()
    ouvert.acquisition_ouverte = True
    chk(attendre_ouverture(ouvert, lambda: True, "x") == "ouvert",
        "un casque ouvert laisse passer à la console")
    chk(attendre_ouverture(_Moteur(), lambda: False, "x") == "echec",
        "un fil de moteur MORT avant l'ouverture est un échec — la question sera reposée")
    QTimer.singleShot(150, lambda: app.activeModalWidget() and app.activeModalWidget().cancel())
    chk(attendre_ouverture(_Moteur(), lambda: True, "x", intervalle_ms=20) == "abandon",
        "« Abandonner » pendant l'attente rend la main, sans console")

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
