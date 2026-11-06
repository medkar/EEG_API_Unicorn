"""« Connecter une application » : la page de RECHERCHE, puis la page de CONTRÔLE.

Aucune décision ici. Le MOTEUR tient la connexion (`EngineServer` : `chercher_applications`,
`connecter`, `deconnecter`, `lancer_decodage`) ; ces pages affichent ce que `snapshot()` en dit,
et leurs boutons passent par la console, qui envoie la commande.

- `RecherchePage` : les applications qui s'annoncent, une ligne chacune — les applications LSL
  de ce PC et des autres PC du réseau, et les appareils réseau (UDP, un ESP32 en Wi-Fi par
  exemple). Chaque ligne dit d'où vient l'application. « Identifier » demande à un appareil
  réseau de se signaler. La recherche ne tourne que tant que la page est ouverte.
- `ControlePage` : la SEULE page pendant une connexion. D'où vient l'application, les
  électrodes, les réglages qu'elle a envoyés (en texte, sans champ de saisie), le décodage en
  direct et, pour un mode À MODÈLE, le choix du modèle puis « Lancer le décodage ». Aucun autre
  geste : le moteur refuserait tout le reste (sa liste blanche).
"""

import os
import sys
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QRadioButton, QSizePolicy,
                               QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from console import live_views  # noqa: E402
from console.banner import AMBRE, GRIS, ROUGE, VERT, nom_affiche, texte_fin  # noqa: E402
from console.contact_vue import VueContact  # noqa: E402
from console.params_form import infobulle, texte_affiche  # noqa: E402
from core.i18n import nombre, retraduit, tr  # noqa: E402
from core.modes import registry  # noqa: E402

# Combien de commandes de l'application la page montre : les plus récentes.
COMMANDES_MONTREES = 6

# Combien de secondes la liste des applications reste vide avant que la page conseille de
# vérifier le réseau et le pare-feu. Un appareil réseau s'annonce chaque seconde : 5 s sans rien,
# c'est qu'il n'arrive pas jusqu'ici.
CONSEIL_PARE_FEU_S = 5.0


def texte_souple(style=""):
    """Un texte qui passe à la ligne et n'élargit JAMAIS la page. Il recopie souvent ce que
    l'application annonce (son nom, son identifiant, son adresse) : un mot sans espace plus
    large que la fenêtre ne se couperait pas, et Windows élargirait la fenêtre pour lui. Sa
    largeur est donc celle que la mise en page lui donne."""
    texte = QLabel("")
    texte.setWordWrap(True)
    texte.setTextFormat(Qt.PlainText)
    texte.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    texte.setStyleSheet(style)
    return texte


def hote_du_moteur(moteur):
    """Le nom de ce PC, tel que le moteur le connaît (`Pilotage.hote`), ou None."""
    return getattr(getattr(moteur, "pilotage", None), "hote", None)


def texte_machine(entree, hote):
    """D'où vient une application : « ce PC », le nom d'une autre machine, ou l'adresse IP d'un
    appareil réseau. `entree` : une ligne de `snapshot()["applications"]`, ou la connexion.

    Les noms de machine se comparent SANS la casse, comme le fait le moteur
    (`core/pilotage._meme_hote`) : LSL et Windows n'écrivent pas toujours le nom du PC pareil."""
    machine = entree.get("machine")
    if not machine:
        return tr("console.connexion.machine_inconnue")
    if (entree.get("origine") != "udp" and hote
            and str(machine).casefold() == str(hote).casefold()):
        return tr("console.connexion.ce_pc")
    return str(machine)


def heure(t, format_="%H:%M"):
    """« 14:02 » pour un instant `time.time()`, ou « — »."""
    try:
        return time.strftime(format_, time.localtime(float(t)))
    except (TypeError, ValueError, OverflowError, OSError):
        return tr("console.controle.vide")


def heure_du_journal(t):
    """« 14:02:03 » pour un instant du journal du pilotage. Le journal date ses entrées avec
    `time.monotonic()`, une horloge sans heure : on la ramène à l'heure de la montre."""
    try:
        return heure(time.time() - (time.monotonic() - float(t)), "%H:%M:%S")
    except (TypeError, ValueError):
        return tr("console.controle.vide")


def texte_valeur(param, valeur):
    """La valeur d'un réglage, telle qu'on la lit : le libellé d'un choix (« cibles physiques »),
    le nom de fichier d'un modèle, des nombres dans la langue de l'écran, une liste jointe."""
    if valeur is None or valeur == "" or valeur == [] or valeur == ():
        return tr("console.controle.vide")
    if isinstance(valeur, bool):
        return tr("console.controle.oui") if valeur else tr("console.controle.non")
    choix, libelles = param.get("choices") or [], param.get("libelles") or []
    if libelles and valeur in choix:
        return str(libelles[choix.index(valeur)])
    if isinstance(valeur, (list, tuple)):
        # L'unité une seule fois, après la liste : « 13 · 15 Hz ». Le séparateur n'est pas une
        # virgule : en français, « 5, 7,5, 15 Hz » ne se lit pas (la virgule est aussi décimale).
        liste = " · ".join(str(texte_valeur({}, v)) for v in valeur)
        return f"{liste} {param.get('unit') or ''}".strip()
    if isinstance(valeur, (int, float)):
        unite = param.get("unit") or ""
        return f"{nombre(valeur, 'g')} {unite}".strip()
    # Seul un MODÈLE est un chemin de fichier : on n'en garde que le nom. Un nom de cible
    # « haut/bas » ou un flux « Jeu/marqueurs » s'affiche en entier.
    if param.get("key") == "model":
        return texte_affiche(str(valeur))
    return str(valeur)


def lignes_reglages(spec, valeurs):
    """Les réglages d'un mode, une ligne par réglage qui compte, sous le libellé de l'écran. Un
    réglage dont la condition (`actif_si`) ne tient pas est omis : il ne change rien."""
    lignes = []
    for param in spec.get("params") or ():
        if param["key"] not in valeurs:
            continue
        regle = param.get("actif_si")
        if regle and valeurs.get(regle[0]) != regle[1]:
            continue
        lignes.append(tr("console.controle.reglage", libelle=param["label"],
                         valeur=texte_valeur(param, valeurs[param["key"]])))
    return lignes


def modeles_du_mode(mode_id):
    """Les modèles de ce mode sur ce PC (chemins), tels que le contrat les déclare
    (`choices_fn`) : relus sur le disque. Vide pour un mode sans modèle."""
    spec = registry.get(mode_id)
    param = next((p for p in (spec.params if spec else ()) if p.key == "model"), None)
    return list(param.choices_now()) if param is not None else []


class RecherchePage(QWidget):
    """Les applications qui s'annoncent : celles de ce PC et des autres PC du réseau (LSL), et
    les appareils réseau (UDP). On en choisit une, on clique « Connecter » : c'est le moteur qui
    la connecte, ou refuse en disant pourquoi.

    Chaque ligne dit d'où vient l'application (« ce PC », une autre machine, l'adresse IP d'un
    appareil) et, pour un appareil, son identifiant : en salle, deux appareils du même programme
    restent deux lignes, et « Identifier » fait se signaler celui qu'on a choisi."""

    retour = Signal()
    connecter = Signal(str)        # l'uid de l'application choisie
    identifier = Signal(str)       # l'uid de l'appareil réseau choisi

    def __init__(self, hote=None):
        """`hote()` rend le nom de ce PC tel que le moteur le connaît (ou None) : la ligne d'une
        application de ce PC dit alors « ce PC »."""
        super().__init__()
        self._hote = hote or (lambda: None)
        # L'horloge du conseil sur le pare-feu. Remplaçable par l'autotest, qui n'attend pas 5 s.
        self.horloge = time.monotonic
        titre = QLabel(tr("console.connexion.titre"))
        titre.setStyleSheet("font-size: 16px; font-weight: bold;")
        aide = QLabel(tr("console.connexion.aide"))
        aide.setWordWrap(True)
        self.liste = QListWidget()
        # Un nom ou un identifiant très long passe à la ligne au lieu d'allonger la ligne.
        self.liste.setWordWrap(True)
        # L'écoute des appareils réseau manque (le port est pris par une autre console) : la
        # raison du moteur, en orange. Les applications LSL restent dans la liste.
        self.udp = texte_souple(f"color: {AMBRE};")
        self.vide = QLabel(tr("console.connexion.vide"))
        self.vide.setWordWrap(True)
        self.vide.setStyleSheet(f"color: {GRIS};")
        # La liste reste vide : le plus souvent, le réseau ou le pare-feu bloque l'annonce.
        self.pare_feu = texte_souple(f"color: {GRIS};")
        self.pare_feu.setText(tr("console.connexion.pare_feu"))
        self.refus = QLabel("")
        self.refus.setWordWrap(True)
        self.refus.setTextFormat(Qt.PlainText)
        self.refus.setStyleSheet(f"color: {ROUGE}; font-weight: bold;")
        self.bouton_retour = QPushButton(tr("console.connexion.retour"))
        self.bouton_retour.clicked.connect(self.retour)
        self.bouton_identifier = QPushButton(tr("console.connexion.identifier"))
        self.bouton_identifier.setToolTip(infobulle(tr("console.connexion.identifier_aide")))
        self.bouton_identifier.clicked.connect(self._identifier)
        self.bouton_connecter = QPushButton(tr("console.connexion.connecter"))
        self.bouton_connecter.clicked.connect(self._connecter)
        self.liste.itemSelectionChanged.connect(self._selection)
        self.liste.itemDoubleClicked.connect(lambda _item: self._connecter())
        bas = QHBoxLayout()
        bas.addWidget(self.bouton_retour)
        bas.addStretch(1)
        bas.addWidget(self.bouton_identifier)
        bas.addWidget(self.bouton_connecter)
        layout = QVBoxLayout(self)
        layout.addWidget(titre)
        layout.addWidget(aide)
        layout.addWidget(self.udp)
        layout.addWidget(self.liste, 1)
        layout.addWidget(self.vide)
        layout.addWidget(self.pare_feu)
        layout.addWidget(self.refus)
        layout.addLayout(bas)
        self._peint = None          # la dernière liste peinte : on ne repeint que ce qui change
        # Depuis quand la liste est vide (`horloge()`), ou None si elle ne l'est pas.
        self._vide_depuis = None
        # L'application dont « Connecter » ou « Identifier » vient d'être refusé. Son refus reste
        # à l'écran tant que la personne ne choisit pas une AUTRE ligne, même si la liste change
        # entre-temps : « cette application n'est plus sur le réseau » arrive justement quand
        # elle en sort.
        self._refus_pour = None
        # Cachés seulement : ils ont déjà un parent (la page), donc `hide()` ne crée aucune
        # fenêtre à part.
        self.udp.hide()
        self.pare_feu.hide()
        self.vider()

    def vider(self):
        """Une page neuve : liste vide, aucun refus. Les 5 s du conseil sur le pare-feu
        repartent de maintenant."""
        self._peint = None
        self._vide_depuis = None
        self.dire_refus("")
        self._peindre([])
        self._conseiller()

    def dire_refus(self, texte):
        self.refus.setText(str(texte or ""))
        self.refus.setVisible(bool(texte))
        if not texte:
            self._refus_pour = None

    def uid_choisi(self):
        item = self.liste.currentItem()
        return item.data(Qt.UserRole) if item is not None and item.isSelected() else None

    def _origine_choisie(self):
        """« lsl » ou « udp » : l'origine de la ligne choisie, ou None."""
        item = self.liste.currentItem()
        return item.data(Qt.UserRole + 1) if item is not None and item.isSelected() else None

    def update_from(self, state):
        state = state or {}
        self._peindre(state.get("applications") or [])
        self._conseiller()
        udp = state.get("udp") or {}
        raison = udp.get("raison")
        if udp.get("ouvert") is False and raison is not None:
            self.udp.setText(str(raison))
            self.udp.show()
        else:
            self.udp.hide()

    def _peindre(self, applications):
        hote = self._hote()
        cle = [(a.get("uid"), a.get("nom"), a.get("illisible"), a.get("depuis"),
                a.get("origine"), a.get("machine"), a.get("id")) for a in applications]
        cle.append(hote)
        if cle == self._peint:
            return
        self._peint = cle
        choisi = self.uid_choisi()
        # Une repeinte n'est pas un choix de la personne : la liste se tait pendant qu'on la
        # refait (sinon `_selection` effacerait le refus).
        self.liste.blockSignals(True)
        try:
            self.liste.clear()
            for a in applications:
                item = QListWidgetItem(str(self._ligne(a, hote)))
                item.setData(Qt.UserRole, a.get("uid"))
                item.setData(Qt.UserRole + 1, a.get("origine"))
                self.liste.addItem(item)
                if a.get("uid") == choisi:
                    self.liste.setCurrentItem(item)
                    item.setSelected(True)
        finally:
            self.liste.blockSignals(False)
        self.vide.setVisible(not applications)
        # Le compte des 5 s part quand la liste DEVIENT vide, et s'arrête quand une application
        # y apparaît.
        if applications:
            self._vide_depuis = None
        elif self._vide_depuis is None:
            self._vide_depuis = self.horloge()
        self._maj_boutons()

    @staticmethod
    def _ligne(a, hote):
        """Une ligne de la liste : nom · origine (· identifiant d'un appareil) — vue à HH:MM."""
        nom = nom_affiche(a.get("nom"), a.get("illisible"))
        if a.get("origine") == "udp":
            return tr("console.connexion.ligne_appareil", nom=nom, ip=texte_machine(a, hote),
                      id=a.get("id") or tr("console.controle.vide"), heure=heure(a.get("depuis")))
        return tr("console.connexion.ligne", nom=nom, origine=texte_machine(a, hote),
                  heure=heure(a.get("depuis")))

    def _conseiller(self):
        """Liste vide depuis `CONSEIL_PARE_FEU_S` : le conseil sur le réseau et le pare-feu."""
        self.pare_feu.setVisible(self._vide_depuis is not None
                                 and self.horloge() - self._vide_depuis >= CONSEIL_PARE_FEU_S)

    def _maj_boutons(self):
        self.bouton_connecter.setEnabled(self.uid_choisi() is not None)
        # Seul un appareil réseau sait se signaler : une application LSL n'a pas de LED.
        self.bouton_identifier.setEnabled(self._origine_choisie() == "udp")

    def _selection(self):
        """La personne a choisi une ligne. Une AUTRE application que celle refusée : le refus
        ne parle plus de ce qu'elle regarde, il s'efface."""
        uid = self.uid_choisi()
        if uid is not None and uid != self._refus_pour:
            self.dire_refus("")
        self._maj_boutons()

    def _connecter(self):
        uid = self.uid_choisi()
        if uid is not None:
            # Retenue AVANT l'émission : si la console refuse, son refus porte sur elle.
            self._refus_pour = uid
            self.connecter.emit(uid)

    def _identifier(self):
        uid = self.uid_choisi()
        if uid is not None and self._origine_choisie() == "udp":
            self._refus_pour = uid
            self.identifier.emit(uid)


class ControlePage(QWidget):
    """La seule page pendant une connexion. Elle lit `snapshot()` ; ses gestes (« Déconnecter »,
    « Lancer le décodage ») passent par la console — le moteur juge."""

    def __init__(self, console):
        super().__init__()
        self.console = console
        # La liste des modèles d'un mode, relue sur le disque UNE fois par connexion et par mode,
        # jamais à chaque rafraîchissement. Remplaçable par l'autotest.
        self.choix_modeles = modeles_du_mode
        self.titre = QLabel("")
        self.titre.setTextFormat(Qt.PlainText)
        self.titre.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.bouton_flux = QPushButton(tr("console.grille.flux"))
        self.bouton_flux.clicked.connect(lambda _c=False: self.console.show_flux())
        self.bouton_deconnecter = QPushButton(tr("console.controle.deconnecter"))
        self.bouton_deconnecter.clicked.connect(lambda _c=False: self.console.deconnecter())
        haut = QHBoxLayout()
        haut.addWidget(self.titre, 1)
        haut.addWidget(self.bouton_flux)
        haut.addWidget(self.bouton_deconnecter)
        # D'où vient l'application connectée : la machine d'une application LSL (« ce PC » ou une
        # autre), ou l'adresse et l'identifiant d'un appareil réseau.
        self.origine = texte_souple(f"color: {GRIS};")

        self.fin = QLabel("")
        self.fin.setWordWrap(True)
        self.fin.setTextFormat(Qt.PlainText)
        self.fin.setStyleSheet(f"color: {AMBRE}; font-weight: bold;")
        self.bouton_retour = QPushButton(tr("console.controle.retour"))
        self.bouton_retour.clicked.connect(lambda _c=False: self.console.show_grid())
        ligne_fin = QHBoxLayout()
        ligne_fin.addWidget(self.fin, 1)
        ligne_fin.addWidget(self.bouton_retour)

        self.contact = VueContact()
        self.groupe_reglages = QGroupBox(tr("console.controle.reglages_titre"))
        self.reglages = QLabel("")
        self.reglages.setWordWrap(True)
        self.reglages.setTextFormat(Qt.PlainText)
        QVBoxLayout(self.groupe_reglages).addWidget(self.reglages, 0, Qt.AlignTop)
        milieu = QHBoxLayout()
        milieu.addWidget(self.contact)
        milieu.addWidget(self.groupe_reglages, 1)

        self.zone_modeles = QWidget()
        self.zone_modeles_layout = QVBoxLayout(self.zone_modeles)
        self.zone_modeles_layout.setContentsMargins(0, 0, 0, 0)

        self.groupe_decodage = QGroupBox(tr("console.controle.decodage_titre"))
        self.decodage_layout = QVBoxLayout(self.groupe_decodage)
        self.decodage_aucun = QLabel(tr("console.controle.decodage_aucun"))
        self.decodage_aucun.setStyleSheet(f"color: {GRIS};")
        self.decodage_layout.addWidget(self.decodage_aucun)

        self.groupe_commandes = QGroupBox(tr("console.controle.commandes_titre"))
        self.commandes = QLabel("")
        self.commandes.setWordWrap(True)
        self.commandes.setTextFormat(Qt.PlainText)
        QVBoxLayout(self.groupe_commandes).addWidget(self.commandes, 0, Qt.AlignTop)

        layout = QVBoxLayout(self)
        layout.addLayout(haut)
        layout.addWidget(self.origine)
        layout.addLayout(ligne_fin)
        layout.addLayout(milieu)
        layout.addWidget(self.zone_modeles)
        layout.addWidget(self.groupe_decodage)
        layout.addWidget(self.groupe_commandes)
        layout.addStretch(1)

        self._vues = {}         # mode -> (cadre, titre, vue ou None, voyant « lu », marqueurs)
        # mode -> (groupe, {chemin: radio}, bouton, QButtonGroup, consigne). Construit une fois
        # par connexion et par mode : c'est là que la liste des modèles est lue sur le disque.
        self._choix = {}
        self._suggere = {}      # mode -> la dernière suggestion déjà présélectionnée
        self._heures = {}       # `t` d'une entrée du journal -> son heure, calculée une fois
        # Ce qui distingue une connexion d'une autre : (uid, t). L'uid seul ne suffit pas : une
        # application déconnectée garde son flux, donc son uid, et peut être reconnectée.
        self._connexion_cle = None
        # Les modes de la DERNIÈRE connexion : à sa fin, la page continue de peindre leurs
        # réglages (« arrêté ») et les dernières commandes, avec l'état courant.
        self._derniers_concernes = []
        # Cachés seulement : ils ont déjà un parent (la page), donc `hide()` ne crée aucune
        # fenêtre à part.
        self.origine.hide()
        self.fin.hide()
        self.bouton_retour.hide()

    # --- l'état ----------------------------------------------------------------------------

    def update_from(self, state):
        state = state or {}
        connexion = state.get("connexion")
        if connexion is None:
            # Plus de connexion : la page ne montre plus rien de VIVANT (ni bouton de modèle, ni
            # voyant « lu »), mais les électrodes restent peintes : le casque tourne toujours.
            self.contact.viser(())
            self.contact.update_from(state)
            self._peindre_modeles("", [], {}, {}, {}, {})
            self._peindre_decodage([], {}, state)
            self.origine.hide()
            self._montrer_fin(state.get("fin_connexion"))
            self._peindre_la_fin(state)
            return
        cle = (connexion.get("uid"), connexion.get("t"))
        if cle != self._connexion_cle:
            self._nouvelle_connexion(cle)
        self.fin.hide()
        self.bouton_retour.hide()
        self.bouton_deconnecter.setEnabled(True)
        nom = nom_affiche(connexion.get("nom"), connexion.get("illisible"))
        self.titre.setText(tr("console.controle.titre", nom=nom,
                              heure=heure(connexion.get("depuis"))))
        self.origine.setText(self._texte_origine(connexion))
        self.origine.show()
        actifs = state.get("modes_state") or {}
        attente = connexion.get("en_attente") or {}
        concernes = [mid for mid in self.console.catalogue
                     if mid in attente or mid in (connexion.get("regles") or ())
                     or mid in (connexion.get("demarres") or ())
                     or mid in (connexion.get("demandes") or ())]
        self._derniers_concernes = concernes
        cles = sorted({i for mid in concernes if mid in actifs
                       for i in (self.console.catalogue.get(mid) or {}).get("key_channels")
                       or ()})
        self.contact.viser(cles)
        self.contact.update_from(state)
        self._peindre_reglages(concernes, actifs, state.get("reglages") or {}, attente)
        self._peindre_modeles(nom, concernes, actifs, state.get("reglages") or {}, attente,
                              connexion.get("suggestions") or {})
        self._peindre_decodage(concernes, actifs, state)
        self._peindre_commandes(state.get("pilotage") or (), connexion.get("t"))

    def _nouvelle_connexion(self, cle):
        """Une autre connexion (une autre application, ou la même reconnectée) : ses vues et
        ses listes de modèles repartent de zéro. Les modèles sont relus sur le disque : on a pu
        en entraîner un entre-temps."""
        # Cachés d'abord : détruits seulement au prochain tour de la boucle de Qt, ils ne
        # doivent plus se montrer d'ici là.
        for cadre, *_ in self._vues.values():
            cadre.hide()
            cadre.deleteLater()
        for groupe, *_ in self._choix.values():
            groupe.hide()
            groupe.deleteLater()
        self._vues, self._choix, self._suggere, self._heures = {}, {}, {}, {}
        self._derniers_concernes = []
        self._connexion_cle = cle

    def _texte_origine(self, connexion):
        """D'où vient l'application connectée, en une ligne."""
        if connexion.get("origine") == "udp":
            return tr("console.controle.origine_appareil",
                      adresse=connexion.get("adresse") or connexion.get("machine")
                      or tr("console.connexion.machine_inconnue"),
                      id=connexion.get("id") or tr("console.controle.vide"))
        return tr("console.controle.origine_lsl",
                  machine=texte_machine(connexion,
                                         hote_du_moteur(getattr(self.console, "engine", None))))

    def _montrer_fin(self, fin):
        """Plus de connexion : « Retour à l'accueil » est la seule sortie. Si la fin ne vient
        pas de « Déconnecter » (l'application est partie, s'est arrêtée, ne répond plus…), la
        page dit pourquoi, en orange (`texte_fin`). Le titre ne dit plus « Connectée à … » : le
        nom de l'application est dans le texte orange."""
        self.titre.setText(tr("console.controle.titre_fin"))
        self.bouton_deconnecter.setEnabled(False)
        self.bouton_retour.show()
        if fin and fin.get("raison") != "deconnectee":
            self.fin.setText(texte_fin(fin, self._libelle))
            self.fin.show()
        else:
            self.fin.hide()

    def _peindre_la_fin(self, state):
        """La connexion vient de finir : ses réglages et ses dernières commandes restent à
        l'écran, peints avec l'état COURANT. Un mode que la fin a arrêté y dit « arrêté », et le
        dernier `stop_mode` de l'application apparaît. Rien à peindre si la page n'a jamais vu
        de connexion."""
        if self._connexion_cle is None:
            return
        fin = state.get("fin_connexion") or {}
        concernes = [mid for mid in self.console.catalogue
                     if mid in self._derniers_concernes or mid in (fin.get("arretes") or ())]
        # Plus rien n'attend un modèle : la fin a annulé les démarrages en attente.
        self._peindre_reglages(concernes, state.get("modes_state") or {},
                               state.get("reglages") or {}, {}, connectee=False)
        self._peindre_commandes(state.get("pilotage") or (), self._connexion_cle[1])

    def _libelle(self, mode_id):
        return (self.console.catalogue.get(mode_id) or {}).get("label")

    # --- les blocs -------------------------------------------------------------------------

    def _peindre_reglages(self, concernes, actifs, reglages, attente, connectee=True):
        if not concernes:
            self.reglages.setText(tr("console.controle.reglages_aucun") if connectee
                                  else tr("console.controle.reglages_aucun_fin"))
            return
        blocs = []
        for mid in concernes:
            spec = self.console.catalogue.get(mid) or {}
            if mid in actifs:
                etat = tr("console.controle.etat.en_marche")
            elif mid in attente:
                etat = tr("console.controle.etat.en_attente")
            else:
                etat = tr("console.controle.etat.arrete")
            valeurs = (actifs.get(mid) or {}).get("params") or reglages.get(mid) or {}
            if mid in attente and mid not in actifs:
                # Le modèle d'un mode qui attend se choisit juste en dessous : celui que le
                # moteur a retenu n'est pas forcément celui avec lequel il démarrera.
                valeurs = {cle: v for cle, v in valeurs.items() if cle != "model"}
            lignes = [str(tr("console.controle.mode_titre", mode=spec.get("label") or mid,
                             etat=etat))]
            lignes += [str(ligne) for ligne in lignes_reglages(spec, valeurs)]
            blocs.append("\n".join(lignes))
        self.reglages.setText("\n\n".join(blocs))

    def _peindre_modeles(self, nom, concernes, actifs, reglages, attente, suggestions):
        a_choisir = [mid for mid in concernes
                     if (mid in attente or mid in actifs)
                     and any(p["key"] == "model"
                             for p in (self.console.catalogue.get(mid) or {}).get("params")
                             or ())]
        for mid, (groupe, _radios, bouton, *_reste) in self._choix.items():
            groupe.setVisible(mid in a_choisir)
            if mid not in a_choisir:
                bouton.setEnabled(False)      # rendu actif plus bas si le mode revient
        for mid in a_choisir:
            suggestion = suggestions.get(mid)
            attend = mid in attente and mid not in actifs
            if mid not in self._choix:
                self._choix[mid] = self._groupe_modele(mid)
                radios = self._choix[mid][1]
                if attend:
                    # Un mode qui attend : la suggestion de l'application, sinon le modèle
                    # retenu par le moteur, sinon le plus récent.
                    self._suggere[mid] = suggestion
                    voulus = (suggestion, (reglages.get(mid) or {}).get("model"))
                else:
                    # Un mode qui TOURNE : le modèle avec lequel il décode, jamais la suggestion.
                    voulus = (((actifs.get(mid) or {}).get("params") or {}).get("model"),)
                if not any(self._cocher(radios, v) for v in voulus) and radios:
                    next(iter(radios.values())).setChecked(True)
            elif attend and suggestion != self._suggere.get(mid):
                # Une suggestion NOUVELLE de l'application, pour un mode qui attend : elle
                # devient la présélection. Une seule fois : ensuite, le choix de la personne ne
                # bouge plus.
                self._suggere[mid] = suggestion
                self._cocher(self._choix[mid][1], suggestion)
            groupe, radios, bouton, _boutons, consigne = self._choix[mid]
            libelle = self._libelle(mid) or mid
            if mid in actifs:
                bouton.setText(tr("console.controle.relancer"))
                consigne.setText("")
            else:
                bouton.setText(tr("console.controle.lancer"))
                consigne.setText(tr("console.controle.modele_demande", nom=nom, mode=libelle)
                                 if radios else
                                 tr("console.controle.modele_aucun", mode=libelle))
            bouton.setEnabled(any(r.isChecked() for r in radios.values()))

    def _groupe_modele(self, mid):
        """La liste des modèles d'un mode (lue sur le disque, une fois), et son bouton. Rien
        n'est coché ici : la présélection dépend de l'état du mode (`_peindre_modeles`)."""
        libelle = self._libelle(mid) or mid
        groupe = QGroupBox(str(tr("console.controle.modele_titre", mode=libelle)))
        lay = QVBoxLayout(groupe)
        consigne = QLabel("")
        consigne.setWordWrap(True)
        consigne.setTextFormat(Qt.PlainText)
        lay.addWidget(consigne)
        boutons = QButtonGroup(groupe)
        radios = {}
        for chemin in self.choix_modeles(mid):
            radio = QRadioButton(texte_affiche(str(chemin)))
            radio.toggled.connect(lambda _on=False, m=mid: self._choix_change(m))
            boutons.addButton(radio)
            lay.addWidget(radio)
            radios[chemin] = radio
        bouton = QPushButton(tr("console.controle.lancer"))
        bouton.clicked.connect(lambda _c=False, m=mid: self._lancer(m))
        lay.addWidget(bouton)
        # Ajouté à la zone (donc doté d'un parent) AVANT tout `setVisible` : un widget sans
        # parent rendu visible deviendrait une fenêtre à part.
        self.zone_modeles_layout.addWidget(groupe)
        return groupe, radios, bouton, boutons, consigne

    @staticmethod
    def _cocher(radios, voulu):
        """Coche le modèle `voulu` (un chemin ou un nom de fichier : comparé par le nom de
        fichier), s'il est sur ce PC. Rend True s'il l'a trouvé ; un modèle inconnu ne change
        rien."""
        if not voulu:
            return False
        nom = os.path.basename(str(voulu))
        radio = next((r for c, r in radios.items() if os.path.basename(str(c)) == nom), None)
        if radio is not None:
            radio.setChecked(True)
        return radio is not None

    def _choix_change(self, mid):
        entree = self._choix.get(mid)
        if entree is not None:
            entree[2].setEnabled(any(r.isChecked() for r in entree[1].values()))

    def _lancer(self, mid):
        _groupe, radios, *_reste = self._choix[mid]
        chemin = next((c for c, r in radios.items() if r.isChecked()), None)
        if chemin is not None:
            self.console.lancer_decodage(mid, chemin)

    def _peindre_decodage(self, concernes, actifs, state):
        visibles = [mid for mid in concernes if mid in actifs]
        for mid, (cadre, *_reste) in self._vues.items():
            cadre.setVisible(mid in visibles)
        self.decodage_aucun.setVisible(not visibles)
        # ⚠️ Le moteur ne dit qu'UN état de ses marqueurs entrants, pour tous les modes : deux
        # modes à marqueurs branchés sur deux flux différents partageraient le même voyant. Cas
        # rare, accepté.
        branche = (state.get("marqueurs") or {}).get("connecte")
        # Un appareil réseau ne lit pas le flux LSL : le moteur lui ENVOIE les décisions des
        # modes qu'il a demandés. Pour eux, le voyant LSL dirait « personne ne le lit » à tort.
        connexion = state.get("connexion") or {}
        envoyes = (connexion.get("demandes") or ()) if connexion.get("origine") == "udp" else ()
        for mid in visibles:
            if mid not in self._vues:
                self._vues[mid] = self._vue_de(mid)
            _cadre, titre, vue, lu, marqueurs = self._vues[mid]
            etat = actifs[mid]
            titre.setText(str(self._libelle(mid) or mid))
            if vue is not None:
                vue.update_from(etat)
            if mid in envoyes and etat.get("published", True):
                lu.setText(tr("console.controle.envoye_appareil"))
                lu.setStyleSheet(f"color: {VERT};")
                lu.setToolTip(infobulle(tr("console.controle.envoye_appareil_aide")))
            else:
                lecteur = etat.get("lu")
                lu.setText(tr("console.controle.lu") if lecteur
                           else tr("console.controle.pas_lu") if lecteur is False else "")
                lu.setStyleSheet(f"color: {VERT};" if lecteur
                                 else f"color: {ROUGE}; font-weight: bold;"
                                 if lecteur is False else "")
                lu.setToolTip(infobulle(tr("console.controle.lu_aide")))
            flux = (etat.get("params") or {}).get("stream_in")
            if not flux:
                marqueurs.setText("")
                continue
            texte = (tr("console.controle.marqueurs_ok", flux=flux) if branche
                     else tr("console.controle.marqueurs_absents", flux=flux))
            refuses = etat.get("marqueurs_refuses")
            if refuses:
                texte = tr("console.controle.marqueurs_refuses", texte=texte,
                           n=nombre(refuses, "g"))
            marqueurs.setText(texte)
            marqueurs.setStyleSheet(f"color: {VERT};" if branche and not refuses
                                    else f"color: {ROUGE}; font-weight: bold;")

    def _vue_de(self, mid):
        """Le cadre d'un mode en marche : son nom, ses voyants, et la vue « Décodage en direct »
        de sa famille (`live_views.build`), dans sa mise en page FIXE : toutes ses lignes et ses
        barres sont là dès que le cadre apparaît, seules les valeurs changent, et la page ne
        saute pas quand le mode passe de la stabilisation au décodage. Le brut n'a pas de tracés
        ici : une phrase suffit."""
        spec = self.console.catalogue.get(mid) or {}
        cadre = QWidget()
        lay = QVBoxLayout(cadre)
        lay.setContentsMargins(0, 4, 0, 4)
        titre = QLabel("")
        titre.setStyleSheet("font-weight: bold;")
        lu = QLabel("")
        lu.setToolTip(infobulle(tr("console.controle.lu_aide")))
        marqueurs = QLabel("")
        marqueurs.setTextFormat(Qt.PlainText)
        rang = QHBoxLayout()
        rang.addWidget(titre)
        rang.addStretch(1)
        rang.addWidget(marqueurs)
        rang.addWidget(lu)
        lay.addLayout(rang)
        if spec.get("family") == "brut":
            vue = None
            lay.addWidget(QLabel(tr("console.controle.brut")))
        else:
            vue = live_views.build(spec.get("family"), spec.get("channels") or (), fixe=True)
            lay.addWidget(vue)
        # Ajouté au groupe (donc doté d'un parent) AVANT tout `setVisible`, comme les modèles.
        self.decodage_layout.addWidget(cadre)
        return cadre, titre, vue, lu, marqueurs

    def _peindre_commandes(self, journal, t0):
        """Les dernières commandes de l'application, depuis sa connexion (`t0`, l'horloge du
        journal), chacune avec son heure, raisons dans la langue de l'écran."""
        entrees = [e for e in journal if t0 is None or e.get("t", 0.0) >= t0]
        lignes, heures = [], {}
        for e in entrees[-COMMANDES_MONTREES:]:
            # L'heure d'une entrée ne change pas : calculée une fois, gardée tant qu'elle est
            # montrée.
            t = e.get("t")
            heures[t] = self._heures.get(t) or heure_du_journal(t)
            mode = self._libelle(e.get("mode")) or e.get("mode") or tr("console.controle.vide")
            cmd = e.get("cmd") or "?"
            if e.get("event") == "failed":
                ligne = tr("console.controle.commande_echec", cmd=cmd, mode=mode,
                           raison=retraduit(e.get("raison")) or "…")
            elif not e.get("accepted"):
                ligne = tr("console.controle.commande_refus", cmd=cmd, mode=mode,
                           raison=retraduit(e.get("raison")) or "…")
            elif e.get("warning"):
                ligne = tr("console.controle.commande_ok_reserve", cmd=cmd, mode=mode,
                           reserve=retraduit(e.get("warning")))
            else:
                ligne = tr("console.controle.commande_ok", cmd=cmd, mode=mode)
            lignes.append(str(tr("console.controle.commande_heure", heure=heures[t],
                                 texte=ligne)))
        self._heures = heures
        self.commandes.setText("\n".join(lignes))
