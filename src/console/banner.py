"""Le bandeau permanent : liaison casque, σ par voie, référence décrochée.

Il ne disparaît sur aucun écran, et c'est délibéré. Une référence décrochée rend une séance
entière inexploitable **sans autre symptôme** : les 8 voies mesurent alors la même référence
flottante avec des amplitudes parfaitement plausibles, et un écran de contrôle affiche 8 barres
rassurantes sur un signal vide.

DEUX lignes : en haut l'ÉTAT — source, σ, corrélation, et tout à droite deux icônes qui
évoluent, la batterie du casque et les barres de sa liaison ; en dessous les MESSAGES
(référence décrochée, liaison perdue, refus, fenêtre…), et cette seconde ligne n'existe que
lorsqu'il y a quelque chose à dire.
"""

import os
import sys
import time

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import BATTERIE_FAIBLE_PC, PERTE_PAQUETS_PC  # noqa: E402
from core.i18n import nombre, retraduit, tr  # noqa: E402


# Combien de temps la ligne « liaison rétablie » reste affichée après le retour du casque : le
# temps que la stabilisation et le repos des modes se refassent (15 + 25 s pour le plus long).
REPRISE_VISIBLE_S = 60.0

# Combien de temps la dernière commande de l'application reste écrite dans le bandeau.
AFFICHAGE_PILOTAGE_S = 10.0

VERT, AMBRE, ROUGE, GRIS = "#3fae5a", "#b8860b", "#e5484d", "#8a8f9c"


def entree_a_montrer(pilotage, maintenant):
    """L'entrée du journal du pilotage que le bandeau montre, ou None s'il n'y a rien à dire.

    Parmi les entrées de moins de `AFFICHAGE_PILOTAGE_S` : le dernier REFUS ou ÉCHEC, sauf si une
    entrée ACCEPTÉE plus récente, de la même commande et du même mode, l'a remplacé ; sinon la
    dernière entrée. Une application envoie souvent ses commandes d'affilée (régler, puis
    démarrer) : ne montrer que la dernière ferait disparaître un refus sous le « démarrage
    demandé » qui le suit, en moins d'une seconde.

    `maintenant` est un `time.monotonic()`, comme le `t` de chaque entrée.
    """
    recentes = [e for e in pilotage or ()
                if maintenant - e.get("t", float("-inf")) <= AFFICHAGE_PILOTAGE_S]
    for i in range(len(recentes) - 1, -1, -1):
        e = recentes[i]
        if e.get("accepted") and e.get("event") != "failed":
            continue
        remplace = any(f.get("accepted") and f.get("event") != "failed"
                       and f.get("cmd") == e.get("cmd") and f.get("mode") == e.get("mode")
                       for f in recentes[i + 1:])
        if not remplace:
            return e
    return recentes[-1] if recentes else None


def nom_affiche(nom, illisible=False):
    """Le nom d'une application, ou un texte qui dit qu'elle n'en a pas donné — ou que celui
    qu'elle annonce ne se lit pas (`illisible`)."""
    if nom:
        return nom
    return tr("console.connexion.illisible") if illisible else tr("console.connexion.sans_nom")


def texte_arretes(ids, libelle_mode=None):
    """« Arrêtés : SSVEP, MI. » — les modes qu'une fin de connexion a arrêtés —, ou « Aucun mode
    à arrêter. » quand l'application avait déjà tout arrêté elle-même."""
    noms = [(libelle_mode(m) if libelle_mode else None) or m for m in ids or ()]
    return (tr("console.controle.arretes", liste=", ".join(noms)) if noms
            else tr("console.controle.rien_arrete"))


def texte_fin(fin, libelle_mode=None):
    """La fin d'une connexion en une phrase, avec les modes qu'elle a arrêtés.

    Chaque raison du moteur (`fin_connexion["raison"]`) a son texte. Seule « deconnectee » vient
    d'un clic sur « Déconnecter » ; les autres viennent de l'application, et ne se disent jamais
    comme si la personne l'avait déconnectée :
      - « partie » : l'application a quitté le réseau ;
      - « occupee » : l'appareil réseau est déjà connecté à la console d'un autre PC (`hote`) ;
      - « ne_repond_pas » : l'appareil n'a pas répondu à la connexion ;
      - « silence » : l'appareil ne donne plus de nouvelles ;
      - « bye » : l'appareil a annoncé qu'il s'arrête.
    Une raison inconnue se dit comme « partie ».
    """
    nom = nom_affiche(fin.get("nom"), fin.get("illisible"))
    arretes = texte_arretes(fin.get("arretes"), libelle_mode)
    raison = fin.get("raison")
    if raison == "deconnectee":
        return tr("console.bandeau.connexion.deconnectee", nom=nom, arretes=arretes)
    if raison == "occupee":
        return tr("console.controle.fin.occupee", nom=nom, arretes=arretes,
                  hote=fin.get("hote") or tr("console.connexion.machine_inconnue"))
    if raison == "ne_repond_pas":
        return tr("console.controle.fin.ne_repond_pas", nom=nom, arretes=arretes)
    if raison == "silence":
        return tr("console.controle.fin.silence", nom=nom, arretes=arretes)
    if raison == "bye":
        return tr("console.controle.fin.bye", nom=nom, arretes=arretes)
    return tr("console.controle.partie", nom=nom, arretes=arretes)


def couleur_batterie(pc):
    """Vert, puis ambre sous la moitié, rouge sous le seuil où le bandeau demande de recharger."""
    if pc < BATTERIE_FAIBLE_PC:
        return ROUGE
    return AMBRE if pc < 50 else VERT


def couleur_barres(barres):
    """La couleur d'un nombre de barres : c'est le MOTEUR qui a décidé combien (cf. config)."""
    return VERT if barres >= 3 else AMBRE if barres == 2 else ROUGE


class IconeBatterie(QWidget):
    """Une pile qui se vide, dessinée — pas une image : elle suit le niveau au pourcent près."""

    def __init__(self):
        super().__init__()
        self.niveau = None
        self.setFixedSize(QSize(30, 16))

    def montrer(self, pc):
        self.niveau = pc
        self.update()

    def paintEvent(self, _evenement):  # noqa: N802 - nom imposé par Qt
        if self.niveau is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        corps = QRectF(1, 2, 24, 12)
        p.setPen(QPen(QColor(GRIS), 1.5))
        p.drawRoundedRect(corps, 2, 2)
        p.fillRect(QRectF(26, 6, 3, 4), QColor(GRIS))          # la borne
        largeur = max(0.0, min(float(self.niveau), 100.0)) / 100.0 * 20
        p.fillRect(QRectF(3, 4, largeur, 8), QColor(couleur_batterie(self.niveau)))
        p.end()


class IconeSignal(QWidget):
    """Quatre barres, comme un téléphone ; celles du moteur sont pleines, les autres en creux."""

    def __init__(self):
        super().__init__()
        self.barres = None
        self.setFixedSize(QSize(22, 16))

    def montrer(self, barres):
        self.barres = barres
        self.update()

    def paintEvent(self, _evenement):  # noqa: N802 - nom imposé par Qt
        if self.barres is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pleine = QColor(couleur_barres(self.barres))
        for i in range(4):
            hauteur = 4 + 3 * i
            barre = QRectF(1 + 5 * i, 15 - hauteur, 3.5, hauteur)
            if i < self.barres:
                p.fillRect(barre, pleine)
            else:
                p.setPen(QPen(QColor(GRIS), 1))
                p.drawRect(barre)
        if self.barres == 0:                                   # liaison perdue : une croix
            p.setPen(QPen(QColor(ROUGE), 2))
            p.drawLine(4, 3, 12, 11)
            p.drawLine(12, 3, 4, 11)
        p.end()


class LigneAbregee(QLabel):
    """Une ligne de texte qui ne fait JAMAIS grandir la fenêtre.

    Un QLabel sans retour à la ligne exige la largeur de TOUT son texte : c'est sa largeur
    minimale, et Windows élargit la fenêtre pour la respecter, au gré des messages du bandeau.
    Ici la largeur minimale est nulle ; faute de place, la ligne s'abrège (« … ») et le texte
    entier passe dans la bulle. Elle ne passe PAS à la ligne : la hauteur du bandeau changerait,
    et tout ce qui est dessous sauterait. `text()` rend le texte ENTIER."""

    def __init__(self, texte=""):
        super().__init__()
        self._plein = ""
        self.setText(texte)

    def setText(self, texte):  # noqa: N802 - nom imposé par Qt
        self._plein = texte or ""
        self._abreger()
        self.updateGeometry()

    def text(self):
        return self._plein

    def _abreger(self):
        court = self.fontMetrics().elidedText(self._plein, Qt.ElideRight, max(0, self.width()))
        QLabel.setText(self, court)
        QLabel.setToolTip(self, self._plein if court != self._plein else "")

    def sizeHint(self):  # noqa: N802 - nom imposé par Qt
        # La place qu'elle VOUDRAIT (tout son texte) : la mise en page la lui donne quand il y en a.
        return QSize(self.fontMetrics().horizontalAdvance(self._plein) + 4,
                     super().sizeHint().height())

    def minimumSizeHint(self):  # noqa: N802 - nom imposé par Qt
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, evenement):  # noqa: N802 - nom imposé par Qt
        super().resizeEvent(evenement)
        self._abreger()


class Banner(QWidget):
    """Deux lignes, jamais masquées : l'état en haut, les messages en dessous."""

    def __init__(self, libelle_mode=None):
        """`libelle_mode(id)` rend le libellé d'un mode dans la langue de l'écran (ou None) : le
        bandeau ne tient aucune liste de modes, c'est la console qui lui prête son catalogue."""
        super().__init__()
        self._libelle_mode = libelle_mode
        self.liaison = LigneAbregee(tr("console.bandeau.moteur_non_demarre"))
        self.sigmas = LigneAbregee("")
        self.alarme = QLabel("")
        self.alarme.setWordWrap(True)   # un MESSAGE : il passe à la ligne, il n'élargit rien
        self.alarme.setStyleSheet(f"color: {ROUGE}; font-weight: bold;")
        # L'état de la FENÊTRE de stimulus, s'il y en a une. Ici et pas sur une page, pour la même
        # raison que le reste du bandeau : une fenêtre qui meurt pendant qu'on regarde la grille
        # doit se voir quand même. Et une fenêtre morte en silence, c'est un moteur qui attend des
        # marqueurs qui ne viendront plus — indiscernable d'un étudiant qui fixe mal.
        self.fenetre = QLabel("")
        self.fenetre.setWordWrap(True)
        # Le dernier REFUS du moteur, quel qu'il soit. Ici, et pas sur une page, parce que le
        # refus le plus banal du produit arrive depuis la GRILLE — cliquer « Démarrer » sur un
        # mode sans modèle entraîné — et que la grille n'a aucune page où l'écrire.
        # ⚠️ Un refus imprimé seulement dans le terminal laisserait l'écran immobile : le clic
        # sur « Démarrer » semblerait muet.
        self.refus = QLabel("")
        self.refus.setWordWrap(True)
        self.refus.setStyleSheet(f"color: {ROUGE}; font-weight: bold;")
        # La MORT du fil du moteur. Ici, et pas sur une page, pour la raison de tout ce bandeau :
        # elle peut arriver pendant qu'on regarde n'importe quel écran, et elle rend faux tout ce
        # qui s'affiche ailleurs.
        self.moteur = QLabel("")
        self.moteur.setWordWrap(True)
        self.moteur.setStyleSheet(f"color: {ROUGE}; font-weight: bold;")
        # Sélectionnable : le message peut finir par le chemin du journal, qu'on veut copier.
        self.moteur.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # Ce que l'APPLICATION vient de demander au moteur par le réseau (démarrer un mode, poser
        # des réglages…), refus compris : elle ne lit sa réponse que dans son propre code.
        self.application = QLabel("")
        self.application.setWordWrap(True)
        # ⚠️ Elle recopie ce que l'APPLICATION a envoyé (sa commande, son nom de mode), qui peut
        # n'avoir aucune espace : un mot plus large que la fenêtre ne se coupe pas, et Windows
        # élargirait la fenêtre pour lui. Sa largeur est donc celle que la mise en page lui donne.
        self.application.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # …et en TEXTE BRUT : une commande « <h1>… » serait sinon dessinée en HTML.
        self.application.setTextFormat(Qt.PlainText)
        # L'application CONNECTÉE (le voyant permanent), puis, un moment, la fin de la connexion.
        # Son nom vient de l'application : même largeur imposée et même texte brut qu'au-dessus.
        self.connexion_app = QLabel("")
        self.connexion_app.setWordWrap(True)
        self.connexion_app.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.connexion_app.setTextFormat(Qt.PlainText)
        # Batterie faible, liaison dégradée : le MOT qui accompagne les icônes quand ça va mal.
        self.alerte_casque = QLabel("")
        self.alerte_casque.setWordWrap(True)
        self.alerte_casque.setStyleSheet(f"color: {AMBRE}; font-weight: bold;")
        # Après une coupure du casque : la minute qui suit son retour.
        self.reprise = QLabel("")
        self.reprise.setWordWrap(True)
        self.reprise.setStyleSheet(f"color: {AMBRE};")

        # Les icônes du casque, tout à droite.
        self.batterie = IconeBatterie()
        self.batterie_pc = QLabel("")
        self.signal = IconeSignal()

        haut = QHBoxLayout()
        haut.setContentsMargins(0, 0, 0, 0)
        haut.addWidget(self.liaison)
        haut.addWidget(self.sigmas)
        haut.addStretch(1)
        haut.addWidget(self.batterie)
        haut.addWidget(self.batterie_pc)
        haut.addSpacing(10)
        haut.addWidget(self.signal)

        self.messages = QWidget()
        self.ligne_messages = QVBoxLayout(self.messages)
        self.ligne_messages.setContentsMargins(0, 2, 0, 0)
        self.ligne_messages.setSpacing(2)
        for widget in (self.alarme, self.alerte_casque, self.reprise, self.fenetre,
                       self.connexion_app, self.application, self.refus, self.moteur):
            self.ligne_messages.addWidget(widget)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        layout.addLayout(haut)
        layout.addWidget(self.messages)
        self._icones({})
        self._ranger()

    # --- les messages : une seconde ligne qui n'existe que s'il y a quelque chose à dire ----------

    def _ranger(self):
        """Montre les messages non vides, et la seconde ligne seulement s'il y en a un."""
        visibles = False
        for i in range(self.ligne_messages.count()):
            etiquette = self.ligne_messages.itemAt(i).widget()
            etiquette.setVisible(bool(etiquette.text()))
            visibles = visibles or bool(etiquette.text())
        self.messages.setVisible(visibles)

    def set_moteur(self, texte):
        """Le fil du moteur est-il encore vivant ? `""` quand oui.

        ⚠️ **Il ÉCRASE le reste du bandeau quand il est non vide, et c'est tout l'intérêt.** Un fil
        mort laisse `snapshot()` figé sur son dernier état : « Unicorn · 250 Hz · 0 mode actif » et
        « σ : en attente du tampon… » restent alors à l'écran POUR TOUJOURS, tous les deux
        parfaitement plausibles — la console a l'air d'attendre le tampon d'un casque qui ne
        s'ouvrira jamais. C'est pour ça que cette méthode est appelée APRÈS `update_from` : l'écran
        doit dire que plus rien n'arrive, pas continuer à décrire un moteur qui n'existe plus.
        """
        self.moteur.setText(texte or "")
        if texte:
            self.application.setText("")      # un moteur mort ne fait plus rien pour l'application
            self.connexion_app.setText("")
            self.sigmas.setText(tr("console.bandeau.sigmas_moteur_arrete"))
            self.alarme.setText("")
            self._icones({})
        self._ranger()

    def set_refus(self, texte):
        """Le dernier refus du moteur, ou "" pour l'effacer. Un refus ACCEPTÉ n'efface pas le
        précédent : c'est l'appelant qui décide quand la question est réglée."""
        self.refus.setText(texte or "")
        self._ranger()

    def set_fenetre(self, texte, alerte=False):
        """Ce que devient la fenêtre de stimulus. Vient de `LanceurFenetre`, pas du moteur : le
        moteur ne sait pas qu'elle existe, et c'est délibéré (il tourne sans écran)."""
        self.fenetre.setText(texte or "")
        self.fenetre.setStyleSheet(f"color: {ROUGE}; font-weight: bold;" if alerte
                                   else f"color: {GRIS};")
        self._ranger()

    def update_from(self, state):
        self._mettre_a_jour(state)
        self._montrer_connexion(state)
        self._montrer_application(state.get("pilotage") or ())
        self._ranger()

    def _montrer_connexion(self, state):
        """L'application connectée — le voyant permanent —, puis, `AFFICHAGE_PILOTAGE_S` durant,
        la fin de la connexion et les modes qu'elle a arrêtés. Le moteur décide de tout ;
        `fin_connexion["t"]` est un `time.monotonic()` du même processus."""
        connexion = state.get("connexion")
        fin = state.get("fin_connexion")
        if connexion:
            self.connexion_app.setText(tr("console.bandeau.connexion.en_cours",
                                          nom=nom_affiche(connexion.get("nom"),
                                                          connexion.get("illisible"))))
            self.connexion_app.setStyleSheet(f"color: {VERT}; font-weight: bold;")
        elif fin and time.monotonic() - fin.get("t", float("-inf")) <= AFFICHAGE_PILOTAGE_S:
            # Le même texte que la page de contrôle : une raison, une phrase.
            self.connexion_app.setText(texte_fin(fin, self._libelle_mode))
            self.connexion_app.setStyleSheet(f"color: {AMBRE};")
        else:
            self.connexion_app.setText("")

    def _montrer_application(self, pilotage):
        """Ce que l'application vient de demander par le réseau : l'entrée que choisit
        `entree_a_montrer`, un refus récent passant avant ce qui l'a suivi.

        Un échec après acceptation est une entrée à part (`event == "failed"`) : on lit donc
        `event` avant `accepted`. Gris si la commande est passée, ambre si elle est passée avec
        une réserve (un flux de marqueurs pas encore vu…), rouge si elle est refusée ou a
        échoué. `t` est un `time.monotonic()` du même processus que la console."""
        e = entree_a_montrer(pilotage, time.monotonic())
        if e is None:
            self.application.setText("")
            return
        mode_id = e.get("mode")
        libelle = (self._libelle_mode(mode_id) if self._libelle_mode and mode_id else None)
        mode = libelle or mode_id or "—"
        commande = e.get("cmd") or "?"
        if e.get("event") == "failed":
            texte = tr("console.bandeau.application.echec", cmd=commande,
                       raison=retraduit(e.get("raison")) or "…", mode=mode)
        elif not e.get("accepted"):
            texte = tr("console.bandeau.application.refus", cmd=commande,
                       raison=retraduit(e.get("raison")) or "…", mode=mode)
        elif commande == "start_mode" and e.get("deja"):
            texte = tr("console.bandeau.application.start_mode_deja", mode=mode)
        elif commande == "start_mode" and e.get("differe"):
            # Un mode à modèle mis en attente : la console choisira son modèle. Ni ambre ni
            # réserve recopiée, c'est une attente normale.
            texte = tr("console.bandeau.application.start_mode_attente", mode=mode)
        elif commande == "start_mode":
            texte = tr("console.bandeau.application.start_mode", mode=mode)
        elif commande == "stop_mode" and e.get("deja"):
            texte = tr("console.bandeau.application.stop_mode_deja", mode=mode)
        elif commande == "stop_mode":
            texte = tr("console.bandeau.application.stop_mode", mode=mode)
        elif commande == "propose_params":
            texte = tr("console.bandeau.application.propose_params", mode=mode)
        elif e.get("differe"):
            texte = tr("console.bandeau.application.set_params_retenu", mode=mode)
        else:
            texte = tr("console.bandeau.application.set_params", mode=mode)
        reserve = e.get("warning") if e.get("accepted") else None
        if e.get("event") == "failed" or not e.get("accepted"):
            style = f"color: {ROUGE}; font-weight: bold;"
        elif reserve and not (commande == "start_mode" and e.get("differe")):
            # Accepté, MAIS : la réserve que l'application a reçue, ici dans la langue de l'écran.
            texte = tr("console.bandeau.application.reserve", texte=texte,
                       reserve=retraduit(reserve))
            style = f"color: {AMBRE};"
        else:
            style = f"color: {GRIS};"
        self.application.setText(texte)
        self.application.setStyleSheet(style)

    def _mettre_a_jour(self, state):
        board = state.get("board", "?")
        source = (tr("console.bandeau.source_test") if board == "synthetic"
                  else tr("console.bandeau.source_unicorn"))
        actifs = len(state.get("modes") or ())
        fs = f"{state.get('fs_hz', 0):.0f}"
        self.liaison.setText(
            tr("console.bandeau.liaison.plusieurs", source=source, fs=fs, n=actifs) if actifs > 1
            else tr("console.bandeau.liaison.un", source=source, fs=fs, n=actifs))
        self._icones(state.get("casque") or {})

        quality = state.get("quality")
        if not quality:
            self.sigmas.setText(tr("console.bandeau.sigmas_attente"))
            self.alarme.setText("")
            return

        sigmas = quality.get("sigmas", [])
        valeurs = [v for v in sigmas if v is not None]
        verdicts = quality.get("verdicts", [])
        mortes = sum(1 for v in verdicts if v == "morte")
        saturees = sum(1 for v in verdicts if v == "saturée")
        morceaux = [tr("console.bandeau.sigmas", min=nombre(min(valeurs), ".1f"),
                       max=nombre(max(valeurs), ".1f"), n=len(valeurs))
                    if valeurs else tr("console.bandeau.sigma_indisponible")]
        if mortes:
            morceaux.append(tr("console.bandeau.mortes.plusieurs", n=mortes) if mortes > 1
                            else tr("console.bandeau.mortes.un", n=mortes))
        if saturees:
            morceaux.append(tr("console.bandeau.saturees.plusieurs", n=saturees) if saturees > 1
                            else tr("console.bandeau.saturees.un", n=saturees))
        # La corrélation inter-voies, TOUJOURS visible (pas seulement dans l'alarme, au-delà de
        # 0,90) : on la lit au montage. C'est le signe d'une référence qui flotte ; ~0,3-0,5 sur
        # un montage sain.
        if quality.get("common_mode") is not None:
            morceaux.append(tr("console.bandeau.correlation",
                               correlation=nombre(float(quality["common_mode"]), ".2f")))
        self.sigmas.setText(" · ".join(morceaux))

        if quality.get("reference_lost"):
            self.alarme.setText(tr("console.bandeau.reference_decrochee",
                                   correlation=nombre(float(quality.get("common_mode") or 0.0),
                                                      ".2f")))
        else:
            self.alarme.setText("")
        self._montrer_liaison(state.get("liaison") or {})

    def _icones(self, casque):
        """Batterie et barres de liaison, tout à droite ; rien de ce que le moteur ne sait pas.

        La batterie PRÉVIENT : un casque à plat refuse de s'ouvrir et décroche en pleine séance.
        Les barres aussi : un casque qui s'éloigne perd des échantillons AVANT
        de décrocher. Le board de test n'a ni l'une ni les autres (sa batterie est fabriquée, il
        n'a pas de liaison radio) : le moteur rend None, et rien ne s'affiche.
        """
        # ⚠️ Les icônes ne se CACHENT jamais : une icône « inconnue » reste à sa place, vide (son
        # `paintEvent` ne dessine rien). La cacher puis la remontrer change la hauteur de la ligne,
        # donc fait sauter tout ce qui est dessous (la batterie devient inconnue pendant une
        # coupure, puis revient).
        batterie = casque.get("batterie_pc")
        self.batterie.montrer(batterie)
        self.batterie_pc.setText("" if batterie is None
                                 else tr("console.bandeau.batterie", pc=batterie))
        aide_batterie = "" if batterie is None else tr("console.bandeau.batterie_aide")
        self.batterie.setToolTip(aide_batterie)
        self.batterie_pc.setToolTip(aide_batterie)

        barres = casque.get("signal_barres")
        perte = casque.get("perte_pc")
        self.signal.montrer(barres)
        self.signal.setToolTip("" if barres is None else tr("console.bandeau.signal_aide",
                                                            pc=nombre(float(perte or 0.0), ".1f")))

        alertes = []
        if batterie is not None and batterie < BATTERIE_FAIBLE_PC:
            alertes.append(tr("console.bandeau.batterie_faible", pc=batterie))
        if perte is not None and perte >= PERTE_PAQUETS_PC:
            alertes.append(tr("console.bandeau.paquets_perdus", pc=nombre(float(perte), ".1f")))
        self.alerte_casque.setText("   ".join(alertes))

    def _montrer_liaison(self, liaison):
        """Le casque a-t-il décroché ? Prioritaire sur tout le reste du bandeau.

        Pendant la coupure, le moteur ne décode plus rien et réessaie seul : l'écran doit le dire,
        sinon il montre des σ figés sur le dernier tampon — l'écran « où plus rien ne bouge » que
        l'on fermait pour relancer. Après le retour, une minute d'avertissement : les modes
        refont leur repos, et la réouverture redémarre l'amplificateur (C3/Cz saturent un moment).
        """
        if liaison.get("etat") == "perdue":
            self.alarme.setText(tr("console.bandeau.liaison_perdue",
                                   depuis=int(liaison.get("depuis_s") or 0),
                                   tentatives=liaison.get("tentatives", 0),
                                   raison=liaison.get("erreur") or "…"))
            self.sigmas.setText(tr("console.bandeau.sigmas_liaison_perdue"))
            self.reprise.setText("")
            return
        retablie = liaison.get("retablie_depuis_s")
        if retablie is not None and retablie < REPRISE_VISIBLE_S:
            self.reprise.setText(tr("console.bandeau.liaison_retablie",
                                    coupure=nombre(float(liaison.get("coupure_s") or 0.0), ".0f")))
        else:
            self.reprise.setText("")
