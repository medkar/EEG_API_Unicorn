"""« Ce que voit ton application » — le flux sortant, lu PAR LE RÉSEAU, comme un client.

C'est le cœur du produit : un moteur qui décode et **diffuse sur LSL**. Il n'existait aucun moyen
de le REGARDER depuis l'application — la console montrait ce que le moteur pense publier, jamais
ce qui sort vraiment.

⚠️ **Cette page lit par LSL, jamais l'état interne du moteur.** C'est la seule version honnête :
si le panneau montre des valeurs, un vrai client en verrait aussi. Lire `engine.snapshot()`
donnerait un panneau qui défile joliment pendant que le réseau est MUET — c'est-à-dire exactement
la panne qu'on vient regarder ici. La page ne tient donc aucune référence vers le moteur, et un
test le vérifie (`console/app.py --smoke`) : `update_from()` reçoit un état complet et n'en tire
RIEN pour ce panneau ; seul `rafraichir()`, qui tire sur un inlet, le remplit.

⚠️ **Elle ne recopie pas l'extrait « Brancher un client ».** `mode_page.py` le génère déjà depuis
le contrat (`contract.client_snippet`) : cette page montre le FLUX, celle du mode montre le CODE
qui le lit. Deux textes qui disent la même chose finissent toujours par diverger, et ce dépôt en a
déjà payé le prix (`classement_relatif`, `span_correlation`).

Le patron de découverte est celui de `core/markers.flux_de_marqueurs_visibles`, avec ses raisons :
on résout LARGEMENT (LSL répond une fois par interface réseau), on fond les doublons par NOM, on
trie pour que la liste soit stable d'une ouverture à l'autre, et **on ne lève jamais** — le réseau
casse de mille façons, aucune ne doit fermer la console.
"""

import os
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# La borne de découverte vient du MOTEUR, importée plutôt que recopiée : elle a été MESURÉE
# (cf. son commentaire dans `core/markers.py` — avec `minimum=32`, la borne EST le coût, pas le
# pire cas), et deux valeurs pour la même décision finiraient par diverger.
from core.markers import DECOUVERTE_TIMEOUT_S  # noqa: E402
from core.lsl_io import STREAM_PREFIX  # noqa: E402

# Combien de lignes du flux restent à l'écran. Un panneau qui garde tout finirait par tenir une
# séance entière en mémoire dans un QPlainTextEdit — et personne ne relit la 4000e ligne : ce
# panneau sert à voir que ça BOUGE et ce que ça vaut, pas à archiver (c'est le rôle du bouton
# « Enregistrer », qui écrit un fichier côté moteur).
LIGNES_GARDEES = 14

# Ce qu'on tire par rafraîchissement. La page est sondée à ~10 Hz et les flux décodés émettent à
# ~5 Hz : 64 est deux ordres de grandeur au-dessus du besoin, donc une rafale (moteur qui repart,
# client rebranché) se rattrape en un tour au lieu de s'accumuler.
ECHANTILLONS_PAR_TOUR = 64

# Bornes des appels LSL qui peuvent BLOQUER. Même leçon que `markers.TIME_CORRECTION_TIMEOUT_S` :
# un appel C bloquant fige la fenêtre Qt entière et Ctrl-C ne l'interrompt pas. `info()` attend
# que les métadonnées (les noms de voies) arrivent de l'émetteur ; 2 s est large devant le coût
# mesuré d'une connexion locale et borne le pire cas.
OUVERTURE_S = 2.0


def _voies_de(info):
    """Les étiquettes de voies déclarées par le flux, ou des numéros. Ne lève jamais.

    Les métadonnées sont ce qui rend cette API auto-documentée (`_describe_eeg_channels` côté
    moteur) — mais un émetteur écrit par un étudiant n'en déclare pas forcément, et un flux à
    demi décrit est plus trompeur qu'un flux pas décrit du tout : on NUMÉROTE dès que le compte
    ne tombe pas juste, plutôt que d'afficher trois noms pour six colonnes.
    """
    try:
        total = int(info.channel_count())
    except Exception:  # noqa: BLE001 - cf. docstring : cette fonction ne lève jamais
        return []
    voies = []
    try:
        noeud = info.desc().child("channels").child("channel")
        while not noeud.empty():
            voies.append(noeud.child_value("label"))
            noeud = noeud.next_sibling()
    except Exception:  # noqa: BLE001 - des métadonnées illisibles ne valent pas mieux qu'absentes
        voies = []
    if len(voies) != total or not all(voies):
        return [f"voie {i}" for i in range(total)]
    return voies


class FluxLSL:
    """Un flux LSL OUVERT, réduit à ce que la page en lit : ses voies et ses échantillons.

    ⚠️ **C'est la couture qui rend cette page testable sans réseau.** Le smoke injecte un objet
    de même surface (`nom`, `voies`, `tirer()`, `fermer()`) : aucun vrai flux n'est publié pendant
    un test. Un smoke qui dépend du réseau est un smoke qu'on finit par désactiver — et ce projet
    interdit déjà de lancer deux programmes à la fois, donc un vrai flux y serait de toute façon
    fragile (les noms sont un contrat public : un moteur oublié répondrait à la place).

    `recover=False`, comme `markers.MarkerInlet`, et pour la raison qu'il a mesurée : un inlet qui
    « récupère » tout seul attend le retour de l'ANCIEN émetteur, identifié par son `source_id`.
    Un moteur relancé en porte un neuf — l'inlet resterait donc muet POUR TOUJOURS, sans une
    exception. Avec `recover=False`, la disparition LÈVE, la page le dit, et on rouvre.
    """

    def __init__(self, info):
        from pylsl import StreamInlet

        self.nom = info.name()
        self.type = info.type()
        self.source_id = info.source_id()
        inlet = StreamInlet(info, max_buflen=6, recover=False)
        # Obligatoire AVANT le premier tirage : un inlet ne se connecte qu'à la première lecture
        # et LSL ne rejoue RIEN de ce qui précède (même piège que `MarkerInlet.resolve`).
        inlet.open_stream(timeout=OUVERTURE_S)
        self.voies = _voies_de(inlet.info(timeout=OUVERTURE_S))
        self._inlet = inlet

    def tirer(self):
        """Les échantillons arrivés depuis le dernier appel : [(horodatage, [valeurs]), ...].

        `timeout=0.0` : on ne bloque JAMAIS le fil Qt. Un flux muet rend une liste vide, ce qui
        est une information — pas une attente.
        """
        valeurs, horodatages = self._inlet.pull_chunk(timeout=0.0,
                                                      max_samples=ECHANTILLONS_PAR_TOUR)
        return list(zip(horodatages, valeurs))

    def fermer(self):
        """Lâche l'inlet. Ne lève jamais : refermer un flux déjà mort est le cas NORMAL ici."""
        try:
            self._inlet.close_stream()
        except Exception:  # noqa: BLE001 - cf. docstring
            pass


def flux_visibles(timeout_s=DECOUVERTE_TIMEOUT_S):
    """Tous les flux LSL du réseau, les NÔTRES en tête. Ne lève jamais.

    On rend les `StreamInfo` et non des noms : ouvrir un inlet demande l'objet, et re-résoudre
    par nom juste après ferait courir le risque de tomber sur un AUTRE homonyme que celui qu'on a
    montré (le réseau d'une salle de TP en est plein — c'est la panne que `MarkerInlet._arbitre`
    documente).

    ⚠️ Les flux des VOISINS sont montrés eux aussi, délibérément : cette page répond à « ce que
    voit ton application », et une application voit tout le réseau. Les nôtres passent devant
    parce que c'est ce qu'on vient chercher, jamais parce que les autres n'existeraient pas.
    """
    try:
        from pylsl import resolve_streams

        vus = list(resolve_streams(wait_time=float(timeout_s)))
    except Exception as e:  # noqa: BLE001 - cf. `markers.flux_de_marqueurs_visibles` règle 4 :
        # le réseau casse de mille façons, et aucune ne doit fermer la console.
        print(f"[console] impossible de lister les flux du réseau ({type(e).__name__} : {e})")
        return []
    # LSL répond UNE FOIS PAR INTERFACE RÉSEAU : le même flux revient deux ou trois fois, avec le
    # même `source_id`. Le projet s'est déjà fait prendre (`examples/receiver.py` annonçait
    # « 3 moteurs » sur une installation normale). On fond donc sur (nom, source_id) — deux
    # émetteurs réellement distincts qui portent le même nom restent, eux, deux entrées.
    uniques = {}
    for info in vus:
        uniques.setdefault((info.name(), info.source_id()), info)
    # Trié pour que la liste soit STABLE d'une ouverture à l'autre : une liste déroulante qui
    # rebat ses lignes fait cliquer à côté (même raison que `flux_de_marqueurs_visibles`).
    return sorted(uniques.values(),
                  key=lambda i: (not i.name().startswith(STREAM_PREFIX), i.name(),
                                 i.source_id() or ""))


class FluxPage(QWidget):
    """La page. Elle choisit un flux, l'ouvre, et montre ce qui en sort.

    Elle ne connaît AUCUN mode : ni les noms de flux, ni les voies, ni le sens des colonnes. Tout
    vient du réseau — c'est le point de l'exercice. Un catalogue recopié ici dirait ce que le
    moteur DEVRAIT publier, jamais ce qu'il publie.
    """

    retour = Signal()

    def __init__(self, console=None, decouvrir=None, ouvrir=None):
        """`decouvrir` et `ouvrir` sont les DEUX coutures qui sortent le réseau des tests.

        `decouvrir() -> [StreamInfo]` remplace la résolution LSL, `ouvrir(info) -> FluxLSL`
        remplace l'ouverture d'un inlet. Injectables pour la même raison que `fabrique_fenetre`
        chez `LanceurFenetre` et `ouvrir` chez `Console._ouvrir_source` : un smoke qui dépend du
        réseau est un smoke qu'on finit par désactiver, et ce projet interdit déjà de lancer deux
        programmes à la fois — un vrai flux y serait de toute façon fragile, puisque les noms sont
        un contrat PUBLIC et qu'un moteur oublié sur le poste répondrait à la place.
        """
        super().__init__()
        # ⚠️ **Le moteur n'est PAS retenu**, et ce n'est pas une négligence : c'est l'invariant de
        # cette page (cf. l'en-tête du module). On ne garde qu'un canal de COMMANDES — de quoi
        # demander quelque chose au moteur, jamais de quoi LIRE son état. Un `self.console` suffit
        # à rendre `console.engine.snapshot()` atteignable, donc à rendre l'erreur possible : on
        # ne le garde pas non plus.
        self.commande = getattr(console, "commande", None)
        self._decouvrir = decouvrir or flux_visibles
        self._fabrique_inlet = ouvrir or FluxLSL
        self._inlet = None            # `FluxLSL` ouvert, ou None
        self._infos = []              # les `StreamInfo` de la dernière découverte
        self._derniers = []           # les dernières lignes reçues, les plus récentes en bas
        # Le sens du bouton d'enregistrement, tel que le MOTEUR l'a dit au dernier état reçu.
        # Jamais une bascule tenue ici : elle se désynchroniserait au premier refus.
        self._enregistre = False
        # 🔴 **LES DEUX DIAGNOSTICS RETENUS, et c'est le correctif du 2026-09-10.**
        #
        # Cette page est peinte à ~10 Hz. Ses trois messages de panne — « aucun flux nommé X »,
        # « X n'a pas pu être ouvert », et surtout « X a disparu du réseau » — étaient écrits
        # directement dans `self.etat`, que le tour SUIVANT écrasait par une des trois phrases
        # neutres de `_dire_etat` (« N flux visible(s) — choisis-en un »). Durée de vie du
        # diagnostic : **UN tick, 100 ms.** Et aucun de ces chemins ne passe par
        # `Console.commande`, donc le bandeau ne les rattrapait pas non plus.
        #
        # Sur la page dont la raison d'être est de VOIR les pannes réseau, c'était le
        # refus-invisible du test 1.13 de la recette, à l'endroit le plus coûteux.
        #
        # Un diagnostic tient donc jusqu'au GESTE qui y répond — une nouvelle recherche, un flux
        # ouvert, un clic de plus — jamais jusqu'au prochain tour d'horloge.
        self._diagnostic = ""         # côté flux : effacé par `chercher()` et par une ouverture
        self._diagnostic_enr = ""     # côté enregistrement : effacé par le clic suivant

        entete = QHBoxLayout()
        self.bouton_retour = QPushButton("← Modes")
        self.bouton_retour.clicked.connect(self.retour)
        entete.addWidget(self.bouton_retour)
        entete.addWidget(QLabel("<b>Ce que voit ton application</b>"))
        entete.addStretch(1)

        explication = QLabel(
            "Ce panneau lit le réseau LSL <b>comme le ferait ton application</b> — il n'a aucun "
            "accès privilégié au moteur. Ce qui s'affiche ici, un client Unity, Python ou MATLAB "
            "le reçoit aussi ; ce qui reste vide ici est vide pour lui aussi. Le code qui lit un "
            "flux est sur la page du mode, bloc « Brancher un client ».")
        explication.setWordWrap(True)
        explication.setStyleSheet("color: #8a8f9c; font-size: 11px;")

        self.bloc_flux = QGroupBox("Flux visibles sur le réseau")
        self.choix = QComboBox()
        self.choix.setMinimumWidth(340)
        self.choix.activated.connect(self._choisir_index)
        self.bouton_chercher = QPushButton("Chercher les flux")
        self.bouton_chercher.clicked.connect(self.chercher)
        ligne_choix = QHBoxLayout()
        ligne_choix.addWidget(self.choix, 1)
        ligne_choix.addWidget(self.bouton_chercher)

        self.etat = QLabel("")
        self.etat.setWordWrap(True)
        self.entetes = QLabel("")
        self.entetes.setWordWrap(True)
        self.entetes.setStyleSheet("font-weight: bold;")
        self.lignes = QPlainTextEdit()
        self.lignes.setReadOnly(True)
        self.lignes.setMinimumHeight(220)
        # Une police à chasse fixe : les colonnes d'un flux ne s'alignent pas autrement, et un
        # panneau de valeurs qui danse d'une ligne à l'autre ne se lit pas en séance.
        self.lignes.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        flux_layout = QVBoxLayout(self.bloc_flux)
        flux_layout.addLayout(ligne_choix)
        flux_layout.addWidget(self.etat)
        flux_layout.addWidget(self.entetes)
        flux_layout.addWidget(self.lignes, 1)

        # --- enregistrer la séance ------------------------------------------------------------
        # ⚠️ **C'est le MOTEUR qui écrit**, sur commande : la console reste un client qui ne
        # touche jamais au disque, exactement comme pour `save_calibration`. Elle envoie
        # `start_enregistrement` / `stop_enregistrement` et LIT où ça écrit — elle ne compose
        # aucun chemin et n'ouvre aucun fichier.
        self.bloc_enregistrement = QGroupBox("Enregistrer cette séance")
        pourquoi = QLabel(
            "Écrit les verdicts du moteur dans un fichier, une ligne par décision publiée, "
            "horodatée sur la MÊME horloge que le « Journal de séance » de la fenêtre de "
            "stimulus. C'est le second des deux fichiers qu'il faut pour dépouiller une séance "
            "après coup : sans lui, il ne reste que ce qui a défilé à l'écran.")
        pourquoi.setWordWrap(True)
        pourquoi.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        self.bouton_enregistrer = QPushButton("Enregistrer les verdicts")
        self.bouton_enregistrer.clicked.connect(self._basculer_enregistrement)
        self.etat_enregistrement = QLabel("")
        self.etat_enregistrement.setWordWrap(True)
        # Sélectionnable à la souris : c'est un CHEMIN, et le geste suivant est de le copier pour
        # aller ouvrir le fichier. Un chemin qu'on doit retaper à la main est un chemin qu'on
        # retape faux.
        self.etat_enregistrement.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ligne_enr = QHBoxLayout()
        ligne_enr.addWidget(self.bouton_enregistrer)
        ligne_enr.addStretch(1)
        enr_layout = QVBoxLayout(self.bloc_enregistrement)
        enr_layout.addWidget(pourquoi)
        enr_layout.addLayout(ligne_enr)
        enr_layout.addWidget(self.etat_enregistrement)

        layout = QVBoxLayout(self)
        layout.addLayout(entete)
        layout.addWidget(explication)
        layout.addWidget(self.bloc_flux, 1)
        layout.addWidget(self.bloc_enregistrement)

        self._dire_etat()

    # --- la découverte et le choix -----------------------------------------------------------

    def chercher(self):
        """Re-résout le réseau et remplit la liste. Sur ÉVÉNEMENT, jamais dans le rafraîchissement.

        La résolution coûte sa borne ENTIÈRE (cf. `DECOUVERTE_TIMEOUT_S`) : appelée dix fois par
        seconde elle gèlerait la fenêtre en permanence. Elle est donc branchée sur l'entrée dans
        la page et sur le bouton, exactement comme `mode_page.rafraichir_choix`.

        Le flux DÉJÀ ouvert n'est pas refermé : chercher est un geste d'inventaire, pas un
        changement de source. Rater une découverte n'est jamais définitif — on reclique.
        """
        courant = self.choix.currentText()
        # Le geste qui répond au diagnostic l'efface : c'est exactement ce que les trois messages
        # demandent de faire (« Reclique “Chercher les flux” »). Effacé AVANT la découverte, pour
        # qu'un nouvel échec puisse en reposer un.
        self._diagnostic = ""
        self._infos = list(self._decouvrir())
        self.choix.blockSignals(True)     # remplir la liste ne doit pas ouvrir un flux au hasard
        self.choix.clear()
        for info in self._infos:
            self.choix.addItem(self._etiquette(info))
        self.choix.blockSignals(False)
        if courant:
            index = self.choix.findText(courant)
            if index >= 0:
                self.choix.setCurrentIndex(index)
        self._dire_etat()

    @staticmethod
    def _etiquette(info):
        """Ce qu'on lit dans la liste : le NOM COMPLET, son type, son nombre de voies.

        Le nom complet et pas le suffixe : c'est celui-là qu'un `resolve_byprop("name", …)`
        demande côté client. Afficher « decoded_ssvep » enverrait l'étudiant chercher un flux qui
        n'existe sous ce nom nulle part.
        """
        try:
            return f"{info.name()}  ·  {info.type()}  ·  {info.channel_count()} voie(s)"
        except Exception:  # noqa: BLE001 - un StreamInfo illisible ne doit pas vider la liste
            return "flux illisible"

    def choisir(self, nom):
        """Ouvre le flux qui porte ce NOM. True si un inlet a été ouvert.

        Le nom, et non l'index : c'est ce qu'un test — et un futur raccourci « voir le flux de ce
        mode » depuis sa page — a sous la main. Si le nom n'a pas encore été découvert, on cherche
        une fois avant de renoncer : l'ordre normal d'une séance démarre le moteur APRÈS avoir
        ouvert la console, donc la première liste est souvent vide.
        """
        info = next((i for i in self._infos if i.name() == nom), None)
        if info is None:
            self.chercher()
            info = next((i for i in self._infos if i.name() == nom), None)
        if info is None:
            self._fermer()
            self._dire_probleme(f"aucun flux nommé « {nom} » sur le réseau en ce moment.")
            return False
        return self._ouvrir(info)

    def _choisir_index(self, index):
        """La liste déroulante, activée par l'UTILISATEUR (`activated`, pas `currentIndexChanged`).

        `activated` ne part que sur un geste : remplir la liste par programme n'ouvre donc aucun
        flux — sans quoi chaque `chercher()` rouvrirait un inlet, et le panneau perdrait ses
        lignes à chaque fois qu'on rafraîchit l'inventaire.
        """
        if 0 <= index < len(self._infos):
            self._ouvrir(self._infos[index])

    def _ouvrir(self, info):
        """Ferme le flux courant, ouvre celui-là. Ne lève jamais : le DIRE suffit."""
        self._fermer()
        try:
            self._inlet = self._fabrique_inlet(info)
        except Exception as e:  # noqa: BLE001 - un émetteur qui meurt pendant la connexion est le
            # cas NORMAL d'une séance (fenêtre fermée, moteur relancé), pas un incident de console.
            self._inlet = None
            self._dire_probleme(f"« {info.name()} » n'a pas pu être ouvert "
                                f"({type(e).__name__} : {e}). Reclique « Chercher les flux ».")
            return False
        self._derniers = []
        self.lignes.setPlainText("")
        # Un flux OUVERT règle la question : le diagnostic précédent n'a plus rien à dire.
        self._diagnostic = ""
        self._dire_etat()
        return True

    def _fermer(self):
        inlet, self._inlet = self._inlet, None
        if inlet is not None:
            inlet.fermer()

    # --- ce qui défile -----------------------------------------------------------------------

    def rafraichir(self):
        """Tire ce qui est arrivé et le met à l'écran. LE seul chemin qui remplit ce panneau.

        ⚠️ Aucun argument, et surtout pas l'état du moteur : c'est ce qui rend le panneau
        HONNÊTE. S'il montre une ligne, c'est qu'un inlet LSL l'a rendue — donc qu'un client en
        aurait reçu une aussi.
        """
        if self._inlet is None:
            self.entetes.setText("")
            self._dire_etat()
            return
        try:
            recus = self._inlet.tirer()
        except Exception as e:  # noqa: BLE001 - `recover=False` fait LEVER la disparition de
            # l'émetteur : c'est le signal, pas le silence. On lâche et on le dit.
            nom = self._inlet.nom
            self._fermer()
            self.entetes.setText("")
            # ⚠️ **LE message de cette page**, celui qui distingue « mon appli ne reçoit plus »
            # de « mon appli n'a jamais reçu ». Sans `_dire_probleme`, le tour suivant — 100 ms
            # plus tard — le remplaçait par « N flux visible(s) — choisis-en un ».
            self._dire_probleme(
                f"« {nom} » a disparu du réseau ({type(e).__name__} : {e}). Le moteur a-t-il été "
                f"arrêté, ou le mode dépublié ? Reclique « Chercher les flux » pour rouvrir.")
            return
        voies = self._inlet.voies
        self.entetes.setText("voies : " + (" · ".join(voies) if voies else "(non déclarées)"))
        for horodatage, valeurs in recus:
            self._derniers.append(_ligne(horodatage, valeurs))
        if recus:
            self._derniers = self._derniers[-LIGNES_GARDEES:]
            self.lignes.setPlainText("\n".join(self._derniers))
        self._dire_etat(recus=len(recus))

    def _dire_probleme(self, texte):
        """RETIENT un diagnostic et l'affiche. Le seul chemin par lequel une panne s'écrit ici.

        Écrire dans `self.etat` directement fonctionne le temps d'un tour, et d'un seul : c'est
        exactement le défaut que ce champ répare (cf. `_diagnostic`, dans le constructeur).
        """
        self._diagnostic = texte
        self.etat.setText(texte)

    def _dire_etat(self, recus=0):
        """L'état du panneau, en une phrase. « Rien » se DIT, il ne se laisse pas deviner.

        C'est la règle du projet : un écran vide est indiscernable d'un écran cassé. Trois
        situations, trois phrases — aucun flux sur le réseau, un flux à choisir, un flux ouvert —
        plus le DIAGNOSTIC retenu, qui passe devant les deux phrases neutres.
        """
        if self._inlet is not None:
            fin = (f"{recus} échantillon(s) au dernier tour" if recus
                   else "rien depuis le dernier tour — ce mode est-il démarré et publié ?")
            self.etat.setText(f"ouvert : {self._inlet.nom} ({self._inlet.type}) — {fin}")
            return
        if self._diagnostic:
            # Un flux OUVERT passe devant (ci-dessus) : il répond à la question mieux que
            # n'importe quel diagnostic d'hier. En revanche une phrase neutre, elle, ne dit rien
            # que le diagnostic ne dise déjà mieux — elle ne doit jamais le remplacer.
            self.etat.setText(self._diagnostic)
            return
        if not self._infos:
            self.etat.setText(
                "Aucun flux visible sur le réseau. Démarre un mode dans la grille (et laisse la "
                "case « publié » cochée), puis reclique « Chercher les flux ». Si rien n'apparaît "
                "alors qu'un mode décode, c'est que la panne est côté RÉSEAU, pas côté décodage — "
                "et c'est précisément ce que cette page sert à voir.")
            return
        self.etat.setText(f"{len(self._infos)} flux visible(s) — choisis-en un dans la liste "
                          f"pour voir ce qu'il envoie.")

    # --- enregistrer la séance : la console DEMANDE, le moteur écrit -------------------------

    def _basculer_enregistrement(self):
        """Un seul bouton pour les deux gestes : ce qui est en cours décide lequel.

        Le sens du clic se lit sur l'ÉTAT REÇU (`_enregistre`), jamais sur une bascule tenue ici :
        une variable locale se désynchroniserait du moteur au premier refus, et le bouton
        demanderait alors l'inverse de ce qu'il annonce.

        ⚠️ Le refus du moteur est AFFICHÉ. Il en existe des vrais et ils sont utiles : « ce mode
        n'est pas démarré », « un enregistrement est déjà en cours ». Un bouton qui échoue en
        silence est la panne que ce chantier répare — la recette du projet a relevé cinq clics
        d'affilée sur un bouton qui refusait correctement, mais dans le terminal.
        """
        # Ce clic-ci reprend la question à zéro : le diagnostic du précédent a fait son temps.
        self._diagnostic_enr = ""
        if self.commande is None:
            self._dire_probleme_enr("aucun moteur (mode test) : rien à enregistrer.")
            return
        if self._enregistre:
            ack = self.commande("stop_enregistrement")
        else:
            flux = self._inlet.nom if self._inlet is not None else ""
            if not flux:
                self._dire_probleme_enr(
                    "Choisis d'abord le flux à enregistrer dans la liste ci-dessus : le moteur "
                    "enregistre les verdicts d'UN mode, pas tout le réseau.")
                return
            ack = self.commande("start_enregistrement", stream=flux)
        if not ack.get("accepted"):
            self._dire_probleme_enr(ack.get("reason", ""))

    def _dire_probleme_enr(self, texte):
        """Même remède que `_dire_probleme`, sur l'autre bloc de la page.

        ⚠️ Sans la rétention, ces deux messages-là vivaient un tour eux aussi : dès qu'un
        enregistrement existait dans l'état — même TERMINÉ —, `_montrer_enregistrement` repeignait
        « terminé — N verdict(s) dans … » par-dessus, 100 ms après le clic. Un étudiant qui clique
        sans avoir choisi de flux voyait donc le chemin d'un fichier, jamais la raison du refus.
        """
        self._diagnostic_enr = texte
        self.etat_enregistrement.setText(texte)
        self.etat_enregistrement.setStyleSheet("color: #e2603f;")

    def _montrer_enregistrement(self, etat):
        """Peint l'état de l'enregistrement TEL QUE LE MOTEUR le publie. Ne déduit rien.

        ⚠️ Le chemin vient d'ici et de nulle part ailleurs. L'accusé de `start_enregistrement` n'en
        porte volontairement AUCUN (cf. `server.submit`) : deux clics dans la même fenêtre de
        sondage sont tous les deux acceptés, et le second annoncerait un fichier que la boucle
        refuse de créer. Ce champ-là, lui, est écrit par le fil qui écrit le fichier.
        """
        self._enregistre = bool((etat or {}).get("actif"))
        self.bouton_enregistrer.setText(
            "Arrêter l'enregistrement" if self._enregistre else "Enregistrer les verdicts")
        if (etat or {}).get("probleme"):
            # ⚠️ **Une INTERRUPTION passe devant un diagnostic retenu**, et c'est la seule chose
            # qui le fasse. C'est une nouvelle du moteur sur un fichier qui existe, elle annonce
            # une PERTE, et le moteur ne la dit qu'une fois. Un refus de clic, lui, se rejoue en
            # recliquant : le masquer un instant ne coûte rien, masquer celle-ci coûterait la
            # séance.
            self._diagnostic_enr = ""
            self.etat_enregistrement.setText(
                f"⚠ enregistrement INTERROMPU : {etat['probleme']} — {etat.get('lignes', 0)} "
                f"verdict(s) tout de même sauvés dans {etat.get('chemin', '')}")
            self.etat_enregistrement.setStyleSheet("color: #e2603f;")
            return
        # Le BOUTON suit toujours le moteur (ci-dessus) : c'est lui qui dit ce que fera le clic
        # suivant, et le désynchroniser serait pire. Le TEXTE, lui, appartient au diagnostic tant
        # qu'un clic ne l'a pas repris — sinon le refus qu'on vient de lire disparaît en 100 ms.
        if self._diagnostic_enr or not etat:
            return
        self.etat_enregistrement.setStyleSheet("color: #8a8f9c;")
        if self._enregistre:
            self.etat_enregistrement.setText(
                f"en cours — {etat.get('lignes', 0)} verdict(s) écrits dans "
                f"{etat.get('chemin', '')}")
        else:
            self.etat_enregistrement.setText(
                f"terminé — {etat.get('lignes', 0)} verdict(s) dans {etat.get('chemin', '')}. "
                f"Pour dépouiller la séance, ce fichier se joint au journal de la fenêtre de "
                f"stimulus sur la colonne « t ».")

    # --- le cycle de la page ------------------------------------------------------------------

    def update_from(self, state):
        """Appelée à ~10 Hz par la console tant que cette page est devant.

        ⚠️ **`state` n'alimente PAS le panneau de flux.** Il ne sert QU'À l'enregistrement — un
        fichier écrit par le moteur, dont seul le moteur connaît le chemin et le compte. Les
        valeurs qui défilent, elles, viennent de `rafraichir()`, donc du réseau, et de nulle part
        ailleurs : le smoke le prouve en passant un état complet du moteur et en vérifiant que le
        panneau reste vide.

        Les deux blocs de cette page lisent donc deux sources différentes, et c'est exactement ce
        qu'ils doivent faire — l'un montre ce qui SORT (donc le réseau), l'autre ce que le moteur
        ÉCRIT (donc le moteur).
        """
        self._montrer_enregistrement((state or {}).get("enregistrement"))
        self.rafraichir()

    def entrer(self):
        """À l'entrée dans la page : on cherche une fois. Le geste que personne ne devrait taper."""
        self.chercher()

    def quitter(self):
        """En sortant : on LÂCHE l'inlet. Un flux ouvert derrière une page qu'on ne regarde plus
        est un abonné LSL que l'émetteur croit servir — et l'habitude que ce dépôt corrige
        partout ailleurs (cf. `server._libere_marker_inlet`)."""
        self._fermer()
        self._dire_etat()


def _ligne(horodatage, valeurs):
    """Un échantillon en une ligne lisible. Les valeurs telles quelles, jamais réinterprétées.

    L'horodatage est celui de LSL — `local_clock()` de la machine qui a publié, corrigé par
    l'inlet. C'est LA colonne qui permet de recouper cette page avec le journal d'une fenêtre de
    stimulus : les deux fichiers portent la même horloge, donc la jointure est purement numérique.

    Une valeur peut être une CHAÎNE (les flux de marqueurs en portent) : on ne force donc rien en
    float — un `float("cue")` lèverait ici, dans le fil Qt, pour un flux parfaitement normal.
    """
    morceaux = []
    for valeur in valeurs:
        if isinstance(valeur, str):
            morceaux.append(valeur if len(valeur) <= 40 else valeur[:37] + "…")
        else:
            morceaux.append(f"{float(valeur):g}")
    return f"t={float(horodatage):.3f}  " + "  ".join(morceaux)
