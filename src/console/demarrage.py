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
import threading

from PySide6.QtCore import QEventLoop, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,  # noqa: E402
                               QLabel, QProgressDialog, QPushButton, QRadioButton, QVBoxLayout)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from console.params_form import ACCENT, ListeSansMolette, infobulle  # noqa: E402
from core.acquisition import casques_appaires, fonction_liste_unicorn  # noqa: E402
from core.config import SECTEUR_HZ, SECTEURS_HZ, UNICORN_SERIAL  # noqa: E402
from core.i18n import tr  # noqa: E402

# La page Bluetooth des Paramètres de Windows : l'Unicorn s'y appaire, la bibliothèque du casque
# n'ayant aucune fonction d'appairage (vérifié le 2026-09-25).
REGLAGES_BLUETOOTH = "ms-settings:bluetooth"

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

# Le SECTEUR électrique (2026-09-30), un réglage du POSTE : le coupe-bande de tous les décodeurs,
# que chaque modèle entraîné ENREGISTRE. Un libellé par valeur de `config.SECTEURS_HZ` — une
# valeur ajoutée là sans libellé ici lève à l'ouverture du dialogue, plutôt que d'afficher un
# choix muet.
SECTEURS = {
    50.0: tr("console.demarrage.secteur_50"),
    60.0: tr("console.demarrage.secteur_60"),
}


class Memoire:
    """Les derniers numéros de casque OUVERTS AVEC SUCCÈS, du plus récent au plus ancien — et le
    SECTEUR électrique du poste.

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

    # --- le secteur électrique du poste (2026-09-30) -------------------------------------------
    # Retenu dès que le dialogue est VALIDÉ, et non après une ouverture réussie comme un casque :
    # c'est une propriété de la prise murale, qu'un casque éteint ne rend pas moins vraie.

    def secteur(self):
        """Le secteur retenu sur ce poste, en Hz — le défaut du dépôt si rien, ou rien de valide.

        `QSettings` rend une CHAÎNE sous Windows (« 60 ») : lu en float, et une valeur que le
        moteur refuserait (base de registre éditée, version future) retombe sur le défaut plutôt
        que d'empêcher la console de s'ouvrir.
        """
        try:
            valeur = float(self._reglages.value("secteur_hz", SECTEUR_HZ))
        except (TypeError, ValueError):
            return SECTEUR_HZ
        return valeur if valeur in SECTEURS_HZ else SECTEUR_HZ

    def retenir_secteur(self, secteur_hz):
        valeur = float(secteur_hz)
        if valeur not in SECTEURS_HZ:
            raise ValueError(tr("moteur.refus.secteur_inconnu", valeur=secteur_hz,
                                liste=", ".join(f"{s:g}" for s in SECTEURS_HZ)))
        self._reglages.setValue("secteur_hz", valeur)


class DialogueDemarrage(QDialog):
    """Le choix de la source — et du casque —, avant que le moteur n'ouvre quoi que ce soit.

    `source()` rend `UNICORN`, `SYNTHETIQUE`, ou `None` si l'utilisateur ferme la fenêtre — auquel
    cas la console ne démarre pas. Ouvrir « par défaut » sur l'un des deux serait le repli
    silencieux que la docstring du module interdit, avec un clic de moins. `numero()` rend le
    numéro de série saisi.

    `erreur` : la raison du refus PRÉCÉDENT, affichée en tête quand la question est reposée.

    `secteur` : le secteur électrique à présélectionner, en Hz ; None = celui que retient la
    mémoire du poste. Il est ÉCRIT dans la mémoire quand on valide — c'est là que `ouvrir_session`
    le lit, et `secteur_hz()` le rend aussi.
    """

    def __init__(self, parent=None, defaut=UNICORN, numero=None, erreur="", memoire=None,
                 chercher=casques_appaires, recherche_auto=True, ouvrir_url=None, secteur=None):
        super().__init__(parent)
        self._chercher = chercher
        self._ouvrir_url = ouvrir_url or (lambda url: QDesktopServices.openUrl(QUrl(url)))
        self._recherche = None            # {"fil", "resultat", "erreur"} pendant une recherche
        self._accepter_apres = False      # « OK » cliqué pendant une recherche : on attend sa fin
        self.setWindowTitle(tr("console.demarrage.titre"))
        self.setMinimumWidth(560)
        memoire = memoire if memoire is not None else Memoire()
        self._memoire = memoire

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
                ligne = QHBoxLayout()
                ligne.addWidget(self.champ_numero, 1)
                # La liste des casques APPAIRÉS (2026-09-25) : chaque étudiant choisit SON casque
                # au lieu de taper un numéro de mémoire. Pas une détection — cf.
                # `core.acquisition.casques_appaires` : rien ne dit qu'un casque appairé est
                # allumé sans l'ouvrir, et l'écran ne le prétend pas.
                self.bouton_chercher = QPushButton(tr("console.demarrage.actualiser"))
                self.bouton_chercher.clicked.connect(self.chercher)
                ligne.addWidget(self.bouton_chercher)
                self.bouton_appairer = QPushButton(tr("console.demarrage.appairer"))
                self.bouton_appairer.setToolTip(tr("console.demarrage.appairer_aide"))
                self.bouton_appairer.clicked.connect(
                    lambda: self._ouvrir_url(REGLAGES_BLUETOOTH))
                ligne.addWidget(self.bouton_appairer)
                layout.addLayout(ligne)
                self.detection = QLabel("")
                self.detection.setWordWrap(True)
                self.detection.setStyleSheet("font-size: 11px; margin-left: 20px;")
                layout.addWidget(self.detection)
                layout.addWidget(aide_numero)

        # Le SECTEUR électrique (2026-09-30), pour les DEUX sources : le board de test passe par
        # le même filtre d'acquisition, et un modèle entraîné dessus l'enregistre aussi.
        self.choix_secteur = ListeSansMolette()
        for hz in SECTEURS_HZ:
            self.choix_secteur.addItem(SECTEURS[hz], hz)
        voulu = memoire.secteur() if secteur is None else float(secteur)
        self.choix_secteur.setCurrentIndex(max(0, self.choix_secteur.findData(voulu)))
        self.bulle_secteur = QLabel("ⓘ")
        self.bulle_secteur.setStyleSheet(f"color: {ACCENT}; font-size: 13px;")
        self.bulle_secteur.setCursor(Qt.WhatsThisCursor)
        self.bulle_secteur.setToolTip(infobulle(tr("console.demarrage.secteur_aide")))
        ligne_secteur = QHBoxLayout()
        ligne_secteur.setSpacing(4)
        ligne_secteur.addWidget(QLabel(tr("console.demarrage.secteur")))
        ligne_secteur.addWidget(self.bulle_secteur)
        ligne_secteur.addWidget(self.choix_secteur)
        ligne_secteur.addStretch(1)
        layout.addSpacing(8)
        layout.addLayout(ligne_secteur)

        self.manquant = QLabel("")
        self.manquant.setStyleSheet("color: #e5484d;")
        layout.addWidget(self.manquant)
        self.boutons[UNICORN].toggled.connect(self.champ_numero.setEnabled)
        self.boutons[UNICORN].toggled.connect(self.bouton_chercher.setEnabled)
        self.boutons[UNICORN].toggled.connect(self.bouton_appairer.setEnabled)
        self.champ_numero.setEnabled(self.boutons[UNICORN].isChecked())
        self.bouton_chercher.setEnabled(self.boutons[UNICORN].isChecked())
        self.bouton_appairer.setEnabled(self.boutons[UNICORN].isChecked())
        self._sondage = QTimer(self)
        self._sondage.timeout.connect(self._suivre_recherche)
        # Lire la liste des appairés est instantané (mesuré : 0,0 s) et ne balaie pas le Bluetooth.
        # Elle passe quand même par un fil : c'est un appel dans une DLL, et une DLL qui se bloque
        # ne doit pas figer l'écran de départ.
        if recherche_auto and self.boutons[UNICORN].isChecked():
            QTimer.singleShot(0, self.chercher)

        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def numero(self):
        return self.champ_numero.currentText().strip()

    def secteur_hz(self):
        """Le secteur choisi dans la liste, en Hz."""
        return float(self.choix_secteur.currentData())

    # --- la détection des casques ---------------------------------------------------------------

    def chercher(self):
        """Lit la liste des casques appairés, dans un fil (cf. le commentaire du constructeur)."""
        if self._recherche is not None:
            return
        recherche = {"resultat": None, "erreur": None}

        def travail():
            try:
                recherche["resultat"] = list(self._chercher())
            except Exception as e:  # noqa: BLE001 - dit à l'écran, jamais fatal : on peut taper
                recherche["erreur"] = str(e) or type(e).__name__

        recherche["fil"] = threading.Thread(target=travail, daemon=True)
        self._recherche = recherche
        self.bouton_chercher.setEnabled(False)
        self.detection.setStyleSheet("color: #8a8f9c; font-size: 11px; margin-left: 20px;")
        self.detection.setText(tr("console.demarrage.recherche_en_cours"))
        recherche["fil"].start()
        self._sondage.start(100)

    def _suivre_recherche(self):
        recherche = self._recherche
        if recherche is None or recherche["fil"].is_alive():
            return
        self._sondage.stop()
        self._recherche = None
        self.bouton_chercher.setEnabled(self.boutons[UNICORN].isChecked())
        if self._accepter_apres:
            self._accepter_apres = False
            self.manquant.setText("")
            QTimer.singleShot(0, self.accept)
        if recherche["erreur"] is not None:
            self.detection.setStyleSheet("color: #e5484d; font-size: 11px; margin-left: 20px;")
            self.detection.setText(tr("console.demarrage.recherche_impossible",
                                      raison=recherche["erreur"]))
            return
        appaires = recherche["resultat"] or []
        if not appaires:
            self.detection.setStyleSheet("color: #b8860b; font-size: 11px; margin-left: 20px;")
            self.detection.setText(tr("console.demarrage.aucun_appaire"))
            return
        # L'ORDRE : les appairés déjà utilisés sur ce poste d'abord (le dernier en tête), puis les
        # autres appairés, puis les casques dont on se souvient mais que Windows ne connaît plus.
        # Le choix en cours est gardé s'il est appairé : on ne change pas un choix que la liste
        # confirme.
        choisi = self.numero()
        connus = [self.champ_numero.itemText(i) for i in range(self.champ_numero.count())]
        ordre = ([c for c in connus if c in appaires] + [a for a in appaires if a not in connus]
                 + [c for c in connus if c not in appaires])
        self.champ_numero.clear()
        self.champ_numero.addItems(ordre)
        self.champ_numero.setCurrentText(choisi if choisi in appaires else ordre[0])
        # Gris et non vert : APPAIRÉ ne veut pas dire allumé, et un vert le laisserait croire.
        self.detection.setStyleSheet("color: #8a8f9c; font-size: 11px; margin-left: 20px;")
        self.detection.setText(tr("console.demarrage.casques_appaires", n=len(appaires),
                                  liste=", ".join(appaires)))

    def accept(self):
        """Refuse un casque SANS numéro : cf. la docstring du module.

        ⚠️ Et n'ouvre RIEN pendant une recherche : BrainFlow appellerait la bibliothèque du casque
        (pour l'ouvrir) pendant que notre fil l'interroge encore, et rien ne dit qu'elle supporte
        deux appels à la fois. Le clic est retenu, et honoré à la fin de la recherche.
        """
        if self.boutons[UNICORN].isChecked() and not self.numero():
            self.manquant.setText(tr("console.demarrage.numero_manquant"))
            return
        if self._recherche is not None:
            self._accepter_apres = True
            self.manquant.setText(tr("console.demarrage.attente_fin_recherche"))
            return
        # Le secteur part dans la mémoire du poste au moment où l'on VALIDE : c'est là que
        # `ouvrir_session` le lit. « Annuler » ne retient rien.
        self._memoire.retenir_secteur(self.secteur_hz())
        super().accept()

    def source(self):
        """La source retenue, ou None si la fenêtre a été fermée sans choisir."""
        if self.result() != QDialog.Accepted:
            return None
        for cle, radio in self.boutons.items():
            if radio.isChecked():
                return cle
        return None


def choisir_source(defaut=UNICORN, numero=None, erreur="", memoire=None, parent=None,
                   secteur=None):
    """Ouvre le dialogue ; rend `(source, numéro)`, ou None s'il a été fermé sans choisir.

    La recherche automatique ne se relance pas quand la question est REPOSÉE après un échec :
    l'étudiant vient de choisir un casque, la liste de la première recherche est toujours là
    dans sa mémoire, et le bouton « Rechercher » reste à portée.

    Le SECTEUR n'est pas dans ce qui est rendu : le dialogue l'écrit dans `memoire` quand on
    valide, et l'appelant l'y relit. `secteur` le présélectionne (`--secteur`), à la place de
    celui que la mémoire retient.
    """
    dlg = DialogueDemarrage(parent=parent, defaut=defaut, numero=numero, erreur=erreur,
                            memoire=memoire, recherche_auto=not erreur, secteur=secteur)
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
    # Aucun VRAI balayage dans un autotest : un casque est peut-être ouvert ailleurs sur ce poste,
    # et une recherche Bluetooth peut gêner sa liaison. Le chercheur est injecté.
    rien = dict(chercher=lambda: [], recherche_auto=False)
    dlg = DialogueDemarrage(defaut=UNICORN, memoire=memoire, **rien)
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

    dlg2 = DialogueDemarrage(defaut=SYNTHETIQUE, memoire=memoire, **rien)
    chk(not dlg2.champ_numero.isEnabled(),
        "le numéro de série est grisé tant que le board de test est choisi")
    dlg2.accept()
    chk(dlg2.source() == SYNTHETIQUE, f"…et l'autre aussi ({dlg2.source()})")

    # Un casque SANS numéro est refusé, et le dialogue le dit au lieu de se fermer.
    vide = DialogueDemarrage(defaut=UNICORN, memoire=memoire, **rien)
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
    rappel = DialogueDemarrage(defaut=UNICORN, memoire=memoire, **rien)
    chk(rappel.numero() == "UN-F" and rappel.champ_numero.count() == CASQUES_RETENUS,
        f"…et le dialogue propose le DERNIER casque ouvert, les autres dans la liste "
        f"({rappel.numero()}, {rappel.champ_numero.count()})")

    # Le SECTEUR électrique (2026-09-30) : une liste, retenue sur le poste, écrite à la VALIDATION.
    mem_s = Memoire(_Reglages())
    chk(mem_s.secteur() == SECTEUR_HZ,
        f"un poste neuf retient le secteur par défaut du dépôt ({mem_s.secteur()})")
    neuf = DialogueDemarrage(defaut=UNICORN, memoire=mem_s, **rien)
    donnees = [neuf.choix_secteur.itemData(i) for i in range(neuf.choix_secteur.count())]
    chk(donnees == list(SECTEURS_HZ) and neuf.secteur_hz() == SECTEUR_HZ
        and neuf.choix_secteur.currentText() == SECTEURS[SECTEUR_HZ]
        and isinstance(neuf.choix_secteur, ListeSansMolette),
        f"l'écran de départ propose les secteurs du poste, sur le défaut, et la molette ne le "
        f"change pas en passant ({donnees}, « {neuf.choix_secteur.currentText()} »)")
    chk("modèle" in neuf.bulle_secteur.toolTip() and "AVANT" in neuf.bulle_secteur.toolTip(),
        "…avec une bulle ⓘ qui dit à quoi il sert : le coupe-bande de tout, ENREGISTRÉ dans "
        "chaque modèle — donc à régler avant d'entraîner")
    neuf.choix_secteur.setCurrentIndex(neuf.choix_secteur.findData(60.0))
    neuf.reject()
    chk(mem_s.secteur() == SECTEUR_HZ,
        f"« Annuler » ne retient RIEN, même un secteur changé ({mem_s.secteur()})")
    choisi = DialogueDemarrage(defaut=SYNTHETIQUE, memoire=mem_s, **rien)
    choisi.choix_secteur.setCurrentIndex(choisi.choix_secteur.findData(60.0))
    choisi.accept()
    chk(choisi.result() == QDialog.Accepted and mem_s.secteur() == 60.0,
        f"VALIDER retient le secteur choisi dans la mémoire du poste — c'est là que "
        f"`ouvrir_session` le lit, board de test compris ({mem_s.secteur()})")
    rouvert = DialogueDemarrage(defaut=UNICORN, memoire=mem_s, **rien)
    chk(rouvert.secteur_hz() == 60.0
        and rouvert.choix_secteur.currentText() == SECTEURS[60.0],
        f"…et la liste l'AFFICHE à l'ouverture suivante (« {rouvert.choix_secteur.currentText()} »)")
    impose = DialogueDemarrage(defaut=UNICORN, memoire=mem_s, secteur=50, **rien)
    chk(impose.secteur_hz() == 50.0,
        f"`--secteur` présélectionne SA valeur à la place de celle retenue ({impose.secteur_hz()})")
    for brut, attendu in (("60", 60.0), ("55", SECTEUR_HZ), ("abc", SECTEUR_HZ)):
        chk(Memoire(_Reglages(secteur_hz=brut)).secteur() == attendu,
            f"une valeur retenue {brut!r} se relit {attendu:g} Hz : QSettings rend une chaîne, et "
            f"une valeur que le moteur refuserait retombe sur le défaut")
    try:
        mem_s.retenir_secteur(55)
        chk(False, "retenir un secteur à 55 Hz doit lever")
    except ValueError as refus:
        chk("55" in str(refus) and mem_s.secteur() == 60.0,
            f"…et retenir un secteur inconnu lève sans rien écrire ({refus})")

    # Quand la question est REPOSÉE après un échec, la raison est affichée — et la source reste
    # celle que l'étudiant avait choisie : on ne bascule pas pour lui sur le board de test.
    reposee = DialogueDemarrage(defaut=UNICORN, numero="UN-X", erreur="le casque ne répond pas",
                                memoire=memoire, **rien)
    chk(reposee.erreur.isVisibleTo(reposee) and "ne répond pas" in reposee.erreur.text()
        and reposee.boutons[UNICORN].isChecked() and reposee.numero() == "UN-X",
        "après un échec, la raison est affichée, et le casque et son numéro restent choisis — "
        "aucun repli sur le board de test")

    # La LISTE DES APPAIRÉS : lue dans un fil, puis l'ordre — les déjà utilisés d'abord.
    def attendre_recherche(dialogue):
        fin = __import__("time").monotonic() + 5.0
        while dialogue._recherche is not None and __import__("time").monotonic() < fin:
            app.processEvents()
            __import__("time").sleep(0.02)

    def lent():
        __import__("time").sleep(0.3)
        return ["UN-2024.01.01", "UN-F"]

    trouve = DialogueDemarrage(defaut=UNICORN, memoire=memoire, chercher=lent, recherche_auto=True)
    app.processEvents()
    chk(trouve._recherche is not None and not trouve.bouton_chercher.isEnabled()
        and trouve.detection.text(),
        f"à l'ouverture, la liste des appairés est lue d'elle-même, en arrière-plan, et le DIT "
        f"({trouve.detection.text()!r})")
    attendre_recherche(trouve)
    items = [trouve.champ_numero.itemText(i) for i in range(trouve.champ_numero.count())]
    chk(items[:2] == ["UN-F", "UN-2024.01.01"] and items.count("UN-F") == 1
        and trouve.numero() == "UN-F" and "2" in trouve.detection.text()
        and trouve.bouton_chercher.isEnabled(),
        f"le dernier casque utilisé ET appairé passe en tête, puis les autres appairés, sans "
        f"doublon, et le choix en cours est gardé ({items}, {trouve.numero()})")
    # 🔴 « Appairé » n'est pas « allumé » : ni « trouvé », ni vert — c'est ce que l'écran a
    # prétendu le 2026-09-25, casque éteint dans la liste.
    chk("trouv" not in trouve.detection.text().lower() and "appair" in trouve.detection.text()
        and "3fae5a" not in trouve.detection.styleSheet(),
        f"…et le message dit APPAIRÉ, jamais « trouvé », et n'est pas vert : rien ne dit que le "
        f"casque est allumé tant qu'on ne l'a pas ouvert ({trouve.detection.text()!r})")
    urls = []
    appairer = DialogueDemarrage(defaut=UNICORN, memoire=memoire, chercher=lambda: [],
                                 recherche_auto=False, ouvrir_url=urls.append)
    appairer.bouton_appairer.click()
    chk(urls == [REGLAGES_BLUETOOTH],
        f"« Appairer un casque… » ouvre la page Bluetooth des Paramètres de Windows — la "
        f"bibliothèque du casque ne sait pas appairer ({urls})")
    # « OK » PENDANT une recherche : rien ne s'ouvre avant sa fin, puis le clic est honoré.
    presse = DialogueDemarrage(defaut=UNICORN, memoire=memoire, chercher=lent, recherche_auto=True)
    app.processEvents()
    presse.accept()
    chk(presse.result() != QDialog.Accepted and presse._accepter_apres,
        "« OK » pendant la recherche n'ouvre rien tout de suite : BrainFlow interrogerait la "
        "bibliothèque du casque en même temps que notre fil")
    attendre_recherche(presse)
    app.processEvents()
    chk(presse.result() == QDialog.Accepted and presse.source() == UNICORN,
        f"…et le clic est honoré dès la fin de la recherche ({presse.result()})")

    aucun = DialogueDemarrage(defaut=UNICORN, memoire=memoire, chercher=lambda: [],
                              recherche_auto=True)
    app.processEvents()
    attendre_recherche(aucun)
    chk("appair" in aucun.detection.text().lower() and aucun.numero(),
        f"aucun casque appairé : la page dit d'en appairer un, et le champ garde un numéro à "
        f"tenter ({aucun.detection.text()!r})")

    def casse():
        raise OSError("Unicorn.dll introuvable")

    sans_dll = DialogueDemarrage(defaut=UNICORN, memoire=memoire, chercher=casse,
                                 recherche_auto=True)
    app.processEvents()
    attendre_recherche(sans_dll)
    chk("Unicorn.dll introuvable" in sans_dll.detection.text() and sans_dll.numero(),
        f"une recherche impossible le DIT, sans empêcher de taper un numéro "
        f"({sans_dll.detection.text()!r})")

    # La VRAIE bibliothèque du casque se charge — sans être appelée (un appel lance un balayage).
    # Sans ce contrôle, une faute dans le chargement n'apparaissait qu'à l'écran : tous les
    # autres tests de ce fichier remplacent la recherche entière (vu le 2026-09-25 : `_os`).
    if sys.platform == "win32":
        try:
            charge, raison = callable(fonction_liste_unicorn()), ""
        except Exception as e:  # noqa: BLE001 - l'échec EST le résultat à dire
            charge, raison = False, f"{type(e).__name__} : {e}"
        chk(charge, f"la bibliothèque du casque (Unicorn.dll de BrainFlow) se charge, et sa "
                    f"fonction de recherche existe ({raison or 'ok'})")

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
