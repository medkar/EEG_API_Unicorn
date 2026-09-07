"""`MarkerCalibrationRuntime` — la calibration menée par une FENÊTRE, subie par le moteur.

`CalibrationRuntime` (le voisin, à lire avant celui-ci) décrit une calibration que le MOTEUR mène :
il tire les classes, affiche les consignes, décompte les essais. C'est le Motor Imagery, qui est
ENDOGÈNE — il n'a aucun stimulus à montrer à la frame près.

Ici, c'est l'inverse. Le P300, l'ErrP et le c-VEP exigent un stimulus verrouillé au
rafraîchissement de l'écran, donc une fenêtre de `src/stimulus/`. **Le moteur est PASSIF** : il
n'affiche rien, ne tire aucune consigne, ne décompte aucun essai. Il attend que la fenêtre
s'annonce (`calib_start`), encaisse les marqueurs qu'elle publie, prélève une époque autour de
ceux qui en délimitent une, et entraîne quand elle annonce la fin (`calib_end`).

⚠️ **L'INVARIANT QUE CE MODULE EXISTE POUR TENIR.** `pre_s` et `post_s` ne sont **pas** redéclarés
ici : ils sont LUS sur la classe du runtime de DÉCODAGE (`runtime_cls_du_mode`), et l'époque est
prélevée par le MÊME appel que le décodage (`core.p300_decoder.epoch_from_stream`). Jusqu'ici les
époques d'entraînement étaient découpées par un chemin de code (l'appli pygame et son horloge) et
celles du décodage par un autre (le tampon du moteur, les marqueurs LSL, `time_correction`), et
RIEN ne vérifiait qu'ils s'accordent. Un décalage de quelques échantillons ne lève aucune
exception : le modèle est entraîné sur un alignement, appliqué sur un autre, et il décode du bruit
avec une confiance élevée pendant que tous les autres tests restent verts — mesuré sur
`core/modes/p300.py`, où la mutation déplace le pic de −38 échantillons (−152 ms) et 46 autres
assertions ne bronchent pas. Lire la géométrie plutôt que la recopier rend le désaccord
**structurellement impossible** au lieu de seulement testé.

⚠️ **Cette classe HÉRITE de `CalibrationRuntime`, et ce n'est pas de la commodité.** Ce qu'elle en
reprend sans y toucher — `state()`, `cancel()`, `_terminer()`, `restant_s()`, `terminee`, les
phases — est exactement le CONTRAT PUBLIC que `src/console/calib_page.py` consomme. Cette page est
générique, elle ne connaît aucun mode : si la forme de `snapshot()["calibration"]` diffère d'un
seul champ, elle reste VIDE sans lever la moindre erreur. Hériter au lieu de recopier est ce qui
interdit à ce champ de manquer un jour.

⚠️ **Ce qu'elle n'utilise PAS de son parent** : la phase `echauffement` (la fenêtre gère son propre
briefing), le tirage au sort des classes, le découpage d'un essai en cue/imagerie/repos. Les
attributs correspondants sont neutralisés plus bas, avec la raison de chacun.

Autotest :
    python src/core/modes/marker_calib.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (CALIB_FENETRE_ATTENTE_S, CALIB_FENETRE_SILENCE_S,  # noqa: E402
                         MARKER_STREAM_DEFAULT, SSVEP_WARMUP_S, use_utf8_console)
from core.modes.calibration import CalibrationRuntime  # noqa: E402
from core.p300_decoder import epoch_from_stream  # noqa: E402

# Paliers auxquels une perte se DIT, dans le journal. Même motif que `_PALIERS_REFUS` de
# `core/modes/p300.py` et que les compteurs de marqueurs du moteur : une ligne par ordre de
# grandeur. Le dire à chaque perte noierait le terminal (une séance P300 fait des centaines
# d'époques) ; le dire une seule fois laisserait une panne massive imprimer la même ligne qu'une
# perte isolée.
_PALIERS = (1, 10, 100, 1000)


class MarkerCalibrationRuntime(CalibrationRuntime):
    """Une calibration dont la ligne du temps est tenue par une fenêtre de stimulus.

    Une sous-classe (P300, ErrP, c-VEP) fournit trois choses, et rien d'autre :
      1. `runtime_cls_du_mode` — la classe du `ModeRuntime` qui DÉCODE ce mode. C'est d'elle que
         viennent `pre_s`/`post_s`, jamais d'une redéclaration locale.
      2. `_etiquette(ts, marqueur)` — quel marqueur délimite une époque, et sous quelle étiquette.
      3. `_entrainer(enregistre, fs)` — l'entraînement et la sauvegarde, comme chez le MI.
    """

    # --- à renseigner par la sous-classe ------------------------------------
    # La classe du runtime de DÉCODAGE de ce mode (`P300Runtime`, `ErrPRuntime`, `CVEPRuntime`).
    # Sans elle la calibration n'a aucune géométrie d'époque à lire — et la seule autre façon d'en
    # obtenir une serait de la redéclarer ici, c'est-à-dire de rouvrir le second chemin que ce
    # module existe pour supprimer.
    runtime_cls_du_mode = None
    # Ce que la sous-classe sait de la DURÉE de son protocole, hors chauffe. 0 = « je ne sais
    # pas », et c'est le défaut honnête : le moteur, lui, ne peut PAS la deviner, puisque c'est la
    # fenêtre qui mène. Une sous-classe la calcule depuis les constantes de `core/config.py`
    # (P300_CAL_ROUNDS, P300_REPS, le SOA en frames…) — jamais depuis `src/stimulus/`, que `core`
    # n'a pas le droit d'importer.
    duree_protocole_s = 0.0
    # Les étiquettes de la séance, pour l'affichage. Comme chez le parent, mais elles ne servent
    # ici qu'à être MONTRÉES : ce n'est pas le moteur qui tire l'ordre des essais.
    classes = ()

    # La MÊME chauffe que les modes et que la calibration MI : c'est la même dérive DC de
    # l'Unicorn (mesurée le 2026-07-27 : 10⁵ µV en rampe après ouverture de session), et elle ne
    # dépend pas de qui mène le protocole. Une époque prélevée là-dedans ne vaut rien.
    warmup_s = SSVEP_WARMUP_S

    # --- ce qui appartient à la ligne du temps du MOTEUR, et pas à celle-ci ------------------
    # Ces trois-là découpent un essai que le moteur mène (top, imagerie, repos) et comptent un
    # échauffement qu'il joue. Ici la fenêtre tient tout ça, et le moteur ne le connaît même pas.
    # Mis à zéro plutôt que laissé à la valeur héritée : un `cue_s = 3.0` visible sur une classe
    # qui ne cue rien est une invitation à croire qu'il sert.
    cue_s = 0.0
    rest_s = 0.0
    warmup_per_class = 0
    # ⚠️ `imagery_s = None` est un CONTRÔLE, pas un oubli, et le retirer casse les trois modes.
    # `registry.check()` compare `Calib.epoch_s` à `getattr(runtime_cls, "imagery_s", None)` pour
    # empêcher qu'un tampon sous-dimensionné tronque chaque époque en silence. Ce contrôle vaut
    # pour une calibration MENÉE PAR LE MOTEUR, qui prélève `imagery_s` secondes à la fin de chaque
    # essai. Ici on ne prélève rien de tel : on découpe `pre_s + post_s` autour d'un marqueur.
    # Laisser hériter le `4.0` du parent ferait donc refuser, en bloc et à tort, les trois
    # calibrations à fenêtre (« epoch_s=0,95 s est SOUS imagery_s=4 s »), pour une grandeur que
    # personne ici ne prélève.
    # ⚠️ Ce que ce None NE dit pas : que le tampon soit assez grand. Il l'est — mais par un autre
    # chemin, déjà vérifié : `EngineServer.__init__` le dimensionne aussi sur
    # `marker_epoch_s + MARKER_LATE_S` du MODE, et `registry.check()` lie déjà `marker_epoch_s` à
    # `pre_s + post_s` du runtime de décodage. C'est-à-dire à la géométrie même que cette
    # calibration prélève. `Calib.epoch_s` d'une calibration « fenetre » ne dimensionne donc rien
    # de plus ; il doit seulement être > 0 pour que `check()` ne le signale pas comme oublié.
    imagery_s = None

    def __init__(self, spec, params, engine, rng=None, dossier=None):
        super().__init__(spec, params, engine, rng=rng, dossier=dossier)
        self._annonce_recue = False     # un `calib_start` est arrivé (la fenêtre est VIVANTE)
        self._essais_annonces = 0       # le champ `trials` de cet annonce ; 0 = inconnu
        self._debut = None              # instant du premier tick (horloge de l'appelant)
        self._dernier_marqueur_s = None  # dernier tour où un marqueur est arrivé, MÊME horloge
        self._marqueurs_recus = 0       # tout ce qui est passé, accepté ou non
        self._marqueurs_chauffe = 0     # jetés parce que reçus pendant la chauffe
        self._epoques_perdues = 0       # marqueurs mûrs dont l'époque a quand même débordé
        self._chauffe_dite = False      # l'avertissement de chauffe, une fois par séance
        self._attente_fin_dite = False  # « tout est arrivé, calib_end manque », une fois

        # ⚠️ Le mode et sa calibration lisent la MÊME file de marqueurs, sous le MÊME identifiant :
        # `EngineServer.markers_murs` tient UN curseur par `mode_id`, et il avance à chaque appel.
        # Les deux tourneraient donc en se volant les marqueurs, chacun n'en voyant qu'une partie
        # au hasard du tour de boucle — deux décodages muets, sans la moindre erreur. On le DIT ;
        # c'est à la console de ne pas proposer les deux à la fois.
        if spec.id in (getattr(engine, "active", None) or {}):
            print(f"[marker-calib] ⚠️ « {spec.id} » DÉCODE pendant que sa calibration démarre : "
                  f"les deux lisent la même file de marqueurs sous le même identifiant, donc "
                  f"chaque marqueur ne sera vu que par l'un des deux. Arrête le mode.")

    # --- ce que la sous-classe fournit ---------------------------------------

    def _etiquette(self, ts, marqueur):
        """L'étiquette de l'époque à prélever à l'instant de CE marqueur — None s'il n'en
        délimite aucune.

        ⚠️ **Le marqueur qui PORTE l'étiquette n'est pas forcément celui qui DÉLIMITE l'époque**,
        et c'est pour ça que ce hook est un point d'entrée à état plutôt qu'une table :
          • P300  — `cue` annonce la cible de la manche (à MÉMORISER, rendre None), puis chaque
            `flash` délimite une époque étiquetée cible/non-cible selon qu'il porte cette cible ;
          • c-VEP — `cue` annonce la cible (à mémoriser), puis chaque `cycle` délimite une époque ;
          • ErrP  — il n'y a PAS de `cue` : l'étiquette voyage sur l'événement `feedback` lui-même,
            qui gagne un champ `error` pendant la calibration.
        Une classe de base qui supposerait « l'étiquette arrive par `cue` » interdirait le
        troisième cas.

        `calib_start` et `calib_end` ne passent JAMAIS par ici : ils appartiennent à la ligne du
        temps, que cette classe tient seule.

        La sous-classe peut aussi poser `self.classe` au passage — c'est ce que la console affiche
        sous la consigne. Elle ne doit en revanche jamais toucher `self.etape` : cf. `state()`.
        """
        raise NotImplementedError

    # --- la géométrie de l'époque, LUE et jamais redéclarée --------------------

    def _geometrie(self):
        """La classe du runtime de DÉCODAGE. Lève avec une phrase lisible si elle manque."""
        if self.runtime_cls_du_mode is None:
            raise ValueError(
                f"{type(self).__name__} ne déclare pas `runtime_cls_du_mode` : cette calibration "
                f"n'a alors aucune géométrie d'époque à LIRE, et la seule autre façon d'en obtenir "
                f"une serait de redéclarer pre_s/post_s ici — c'est-à-dire de rouvrir le second "
                f"chemin de découpage que ce module existe pour supprimer")
        return self.runtime_cls_du_mode

    @property
    def pre_s(self):
        return float(self._geometrie().pre_s)

    @property
    def post_s(self):
        return float(self._geometrie().post_s)

    # --- la ligne du temps ---------------------------------------------------

    def total(self):
        """Le nombre d'essais que la FENÊTRE a annoncés. 0 tant qu'elle ne s'est pas annoncée.

        ⚠️ Le moteur ne le calcule pas : il ne connaît ni le nombre de manches, ni le nombre de
        répétitions, ni le SOA du protocole. Ce nombre vient du champ `trials` de `calib_start`,
        et l'unité est celle que compte `self.essai` — **une époque enregistrée**. C'est à la
        fenêtre d'annoncer le nombre d'ÉPOQUES qu'elle produira, pas son nombre de manches : une
        unité différente ne casserait rien mais afficherait un avancement faux, et ferait mal
        régler la détection de fenêtre morte (cf. `_verifie_silence`).
        """
        return self._essais_annonces

    def duree_estimee_s(self):
        """La chauffe, plus ce que la sous-classe sait de son protocole (`duree_protocole_s`).

        Le parent additionne cue + imagerie + repos parce que c'est LUI qui les tient. Ici rien de
        tout ça n'existe côté moteur : rendre une somme de durées qu'il ne contrôle pas serait
        inventer un chiffre. Ce qu'il contrôle vraiment, c'est sa chauffe.
        """
        return float(self.warmup_s) + float(self.duree_protocole_s)

    def instruction(self):
        """Ce que la console affiche en grand. Le vrai protocole est dans l'autre fenêtre, et le
        dire est le plus utile qu'on puisse faire ici : un étudiant qui cherche la consigne sur
        l'écran de la console pendant que le stimulus tourne ailleurs perd sa séance."""
        if self.phase == "chauffe":
            return "Le casque se stabilise — la fenêtre de stimulus prend la main dans un instant."
        if self.phase == "essais":
            return "La séance se déroule dans la fenêtre de stimulus : suis SES consignes."
        if self.phase == "entrainement":
            return "Entraînement du modèle…"
        return ""

    def tick(self, engine, now):
        """Un pas. Appelé par la boucle du moteur, jamais par une interface.

        ⚠️ Un runtime ne lit JAMAIS l'horloge lui-même : `now` arrive d'en haut. C'est ce qui
        permet de jouer une séance de sept minutes en quelques millisecondes dans un test — et
        c'est aussi la seule horloge sur laquelle les deux délais d'abandon sont comptés. Les
        horodatages des marqueurs, eux, sont sur l'horloge LSL : les mélanger donnerait des délais
        faux d'un décalage arbitraire entre deux machines.
        """
        if self.terminee:
            return
        if not self._demarre:
            self._demarre = True
            self._debut = now
            # Le décompte que la console affiche pendant la chauffe. Remis à None dès qu'elle est
            # finie : après ça, plus rien n'est décomptable ici, c'est la fenêtre qui mène.
            self._echeance = now + self.warmup_s
            return

        # La phase telle qu'elle était AVANT d'encaisser le lot de ce tour. Elle sert au seul
        # endroit où « depuis quand » compte : l'entraînement, plus bas.
        phase_avant = self.phase

        # 1. Consommer les marqueurs mûrs À CHAQUE TOUR, chauffe comprise. C'est l'APPEL qui fait
        # avancer le curseur du moteur : sans lui pendant la chauffe, l'arriéré s'empile derrière
        # un curseur immobile, et le premier tour de la phase « essais » avale d'un coup 15 s de
        # marqueurs dont l'EEG a déjà quitté le tampon. Panne n°7 de `core/modes/p300.py`, à
        # l'identique — c'est le comportement PAR DÉFAUT, puisque la console lance la fenêtre en
        # même temps qu'elle demande la calibration.
        lot = engine.markers_murs(self.spec.id, post_s=self.post_s)
        for ts, marqueur in lot:
            self.encaisser(engine, ts, marqueur)
        if lot:
            # Le seul témoin que la fenêtre est VIVANTE. Un marqueur reçu compte, qu'il ait été
            # accepté ou non : une fenêtre qui numérote mal ses cibles est bien vivante, et la
            # déclarer morte enverrait chercher la panne à l'opposé de là où elle est.
            self._dernier_marqueur_s = now

        if self.phase == "chauffe":
            # La chauffe est un PLANCHER, pas une fenêtre d'écoute : `calib_start` reçu pendant
            # est bien retenu (`encaisser`), mais la séance ne commence qu'une fois la dérive DC
            # passée. Ce qui a été publié entre-temps est jeté, et dit.
            if self._annonce_recue and now - self._debut >= self.warmup_s:
                self._ouvrir_les_essais(now)
            elif not self._annonce_recue and now - self._debut >= CALIB_FENETRE_ATTENTE_S:
                flux = self.params.get("stream_in") or MARKER_STREAM_DEFAULT
                self._abandonne(
                    f"aucun « calib_start » reçu en {CALIB_FENETRE_ATTENTE_S:.0f} s : la fenêtre "
                    f"de stimulus ne s'est pas lancée, ou elle publie ses marqueurs sous un autre "
                    f"nom que « {flux} »")
            return

        if self.phase == "essais":
            self._verifie_silence(now)
            return

        if self.phase == "entrainement" and phase_avant == "entrainement":
            # ⚠️ `phase_avant`, et pas seulement `self.phase` : un tour APRÈS `calib_end`, jamais
            # dans le MÊME. `_terminer` bloque la boucle du moteur le temps du `fit` (plusieurs
            # secondes), et la console doit avoir pu peindre « entraînement » au moins une fois
            # avant — elle sonde à 10 Hz un état qui, sans ce décalage, passerait directement des
            # essais au résultat. L'écran resterait sur le dernier essai pendant tout
            # l'entraînement : exactement la tête d'un moteur figé. Sans cette condition, la
            # transition et l'entraînement tombaient dans le même tour (attrapé par `_selftest`,
            # pas par relecture).
            self._terminer(engine)

    def _ouvrir_les_essais(self, now):
        """Fin de la chauffe : la séance commence pour de bon."""
        self.phase = "essais"
        self.etape, self.classe, self._echeance = "", "", None
        self._dernier_marqueur_s = now
        print(f"[marker-calib] {self.calib.label or self.spec.label} : chauffe terminée, "
              f"{self.total()} essai(s) annoncé(s) par la fenêtre — enregistrement en cours")

    def _verifie_silence(self, now):
        """Abandonne la séance si la fenêtre s'est tue — la 2e des trois causes.

        La condition n'est PAS « plus de marqueur » seule : elle est « plus de marqueur ALORS QUE
        la fenêtre en annonçait davantage ». Une séance dont tous les essais annoncés sont arrivés
        et dont seul le `calib_end` manque n'est pas une fenêtre morte : c'est une séance complète
        dont le dernier marqueur s'est perdu, et la jeter détruirait des minutes de signal
        parfaitement bon.

        ⚠️ Le prix de ce choix, assumé et DIT : dans ce cas-là précisément, la calibration attend
        indéfiniment. Elle n'entraîne pas toute seule — ce serait un second déclencheur
        d'entraînement à côté de `calib_end`, donc une seconde vérité sur « quand la séance est
        finie ». C'est « Abandonner » dans la console qui en sort, et le journal le dit une fois
        pour qu'on ne cherche pas ailleurs.

        Un total annoncé de 0 (fenêtre muette sur son `trials`, ou champ illisible) est traité
        comme « on ne sait pas » : le silence redevient alors une mort, faute de pouvoir prouver
        que la séance est complète.
        """
        if self._dernier_marqueur_s is None:
            return
        silence = now - self._dernier_marqueur_s
        if silence <= CALIB_FENETRE_SILENCE_S:
            return
        if self._essais_annonces > 0 and self.essai >= self._essais_annonces:
            if not self._attente_fin_dite:
                self._attente_fin_dite = True
                print(f"[marker-calib] les {self.essai} essais annoncés sont arrivés, mais aucun "
                      f"« calib_end » depuis {silence:.0f} s : la séance ATTEND. Si la fenêtre est "
                      f"morte, « Abandonner » dans la console — rien ne sera entraîné.")
            return
        self._abandonne(
            f"aucun marqueur depuis {silence:.0f} s (> {CALIB_FENETRE_SILENCE_S:.0f} s) : la "
            f"fenêtre de stimulus s'est arrêtée en pleine séance. "
            f"{self.essai} essai(s) enregistré(s) sur les "
            f"{self._essais_annonces or '?'} annoncés — rien n'est entraîné ni sauvegardé")

    def _abandonne(self, raison):
        """Jette la séance en le DISANT, par le MÊME geste que l'abandon depuis la console.

        `cancel()` — celui du parent, pas une variante locale — libère les époques ET la référence
        au moteur, et n'entraîne rien. C'est délibérément la seule et même porte pour les trois
        causes d'abandon : une séance tronquée qui produirait quand même un modèle donnerait une
        entrée que RIEN ne distingue d'un modèle complet dans la liste de la console, et des
        probabilités plausibles et fausses ensuite. Une seule porte, une seule règle.
        """
        print(f"[marker-calib] calibration ABANDONNÉE : {raison}")
        self.cancel()
        # APRÈS `cancel()` : lui seul décide de la phase, et il ne pose aucun `probleme` (l'abandon
        # depuis la console n'en a pas). C'est ici qu'on ajoute la raison, que la console affiche.
        self.probleme = raison

    # --- les marqueurs -------------------------------------------------------

    def encaisser(self, engine, ts, marqueur):
        """Un marqueur, un seul. Le point d'entrée unique de tout ce qui vient de la fenêtre.

        Séparé de `tick` exprès : c'est ce qui permet de le nourrir marqueur par marqueur dans un
        test, sans faux moteur à file, et de raisonner sur UN cas à la fois.

        ⚠️ **Un marqueur reçu hors calibration est ignoré, sans erreur.** C'est le cas normal d'une
        fenêtre lancée en mode calibration pendant qu'un décodage tourne : le moteur n'a pas à
        s'arrêter pour ça, et une exception ici tuerait la séance des AUTRES modes.
        """
        if self.terminee or not self._demarre:
            return
        self._marqueurs_recus += 1
        event = marqueur.get("event")

        # L'annonce est retenue MÊME pendant la chauffe : c'est elle qui dit que la fenêtre est
        # vivante, et le délai de 30 s court depuis un instant où la fenêtre n'existait pas encore
        # (cf. CALIB_FENETRE_ATTENTE_S). La refuser pendant la chauffe obligerait la fenêtre à
        # deviner la durée de celle-ci pour ne pas être déclarée absente.
        if event == "calib_start":
            self._encaisse_annonce(marqueur)
            return

        if self.phase == "chauffe":
            self._marqueurs_chauffe += 1
            if not self._chauffe_dite:
                self._chauffe_dite = True
                print(f"[marker-calib] marqueur(s) reçus pendant la CHAUFFE : jetés — l'offset DC "
                      f"du casque dérive encore ({self.warmup_s:.0f} s), ces époques ne valent "
                      f"rien. La fenêtre devrait attendre avant son premier essai ; ce qu'elle a "
                      f"publié entre-temps ne sera pas enregistré.")
            return

        if self.phase != "essais":
            # « entrainement » ou phase terminale : la fenêtre parle encore alors que la séance est
            # close. Rien à faire, et surtout pas d'erreur — c'est le cas normal d'une fenêtre qui
            # se ferme un tour après son `calib_end`.
            return

        if event == "calib_end":
            self.phase = "entrainement"
            self.etape, self.classe, self._echeance = "", "", None
            print(f"[marker-calib] « calib_end » reçu : {self.essai} essai(s) enregistré(s) sur "
                  f"les {self._essais_annonces or '?'} annoncés — entraînement")
            return

        etiquette = self._etiquette(ts, marqueur)
        if etiquette is None:
            return

        # ⚠️ LE point du module. Même fonction, mêmes bornes, même tampon horodaté que le
        # décodage : `core/modes/p300.py::_encaisser_flash` écrit littéralement le même appel. Une
        # géométrie recopiée ici pourrait dériver de l'autre sans qu'aucun test ne rougisse.
        epoque = epoch_from_stream(engine.recent, engine.recent_ts, ts, engine.acq.fs,
                                   pre_s=self.pre_s, post_s=self.post_s)
        if epoque is None:
            # Le marqueur était mûr et l'époque déborde quand même : le tampon a été vidé
            # entre-temps. Compté et dit par paliers, jamais tu — une séance qui perdrait la
            # moitié de ses époques doit se voir pendant qu'elle tourne, pas à l'entraînement.
            self._epoques_perdues += 1
            if self._epoques_perdues in _PALIERS:
                print(f"[marker-calib] {self._epoques_perdues} époque(s) perdue(s) : le marqueur "
                      f"était mûr mais son EEG avait déjà quitté le tampon du moteur")
            return
        self._enregistre.append((epoque, etiquette))
        self.essai += 1

    def _encaisse_annonce(self, marqueur):
        """`calib_start` : la fenêtre est vivante, et voici combien d'essais elle promet."""
        trials = marqueur.get("trials")
        # `isinstance(trials, bool)` d'abord : en Python `bool` HÉRITE de `int`, donc `True`
        # passerait pour 1 essai annoncé — et une séance de 300 époques serait alors déclarée
        # « complète » dès la première. Même piège que `target` dans `core/modes/p300.py`.
        if isinstance(trials, bool) or not isinstance(trials, (int, float)):
            print(f"[marker-calib] « calib_start » sans nombre d'essais lisible ({trials!r}) : "
                  f"l'avancement ne pourra pas s'afficher, et un silence en cours de séance sera "
                  f"traité comme une fenêtre morte faute de pouvoir prouver qu'elle a fini")
            self._essais_annonces = 0
        else:
            self._essais_annonces = max(0, int(trials))
        if self._annonce_recue:
            # Un second `calib_start` sans `calib_end` entre les deux : la fenêtre a redémarré sa
            # séance. On le DIT plutôt que d'empiler deux séances dans le même jeu d'entraînement
            # — c'est la panne n°6 du P300, transposée à la calibration.
            print(f"[marker-calib] ⚠️ second « calib_start » sans « calib_end » : les "
                  f"{self.essai} essai(s) déjà enregistrés RESTENT dans le jeu d'entraînement. "
                  f"Si la fenêtre a redémarré, abandonne et recommence la calibration.")
        self._annonce_recue = True

    # --- l'état, pour l'afficheur -------------------------------------------

    def state(self, now=None):
        """Le contrat public du parent, plus les compteurs de tout ce que cette séance JETTE.

        Le dictionnaire vient de `super().state()` et n'est jamais reconstruit : c'est ce qui
        garantit à `src/console/calib_page.py` — page générique, qui ne connaît aucun mode — de
        trouver tous les champs qu'elle lit. Un champ manquant ne lèverait rien : la page
        resterait simplement vide.

        ⚠️ **`etape` reste vide de bout en bout, et c'est délibéré.** La console joue un top audio
        sur le front montant de `etape` vers « cue » (`CalibPage._maybe_beep`), pour une
        calibration MI où le moteur donne la consigne à l'oreille. Recopier ici le nom de
        l'événement reçu ferait donc SONNER la console à chaque `cue` du P300 ou du c-VEP —
        par-dessus un stimulus visuel verrouillé à la frame, dans une séance où le sujet doit
        rester immobile et fixer une cible. Le seul rôle du son ici serait de gêner.
        """
        base = super().state(now)
        base.update({
            "marqueurs_recus": self._marqueurs_recus,
            "marqueurs_chauffe": self._marqueurs_chauffe,
            "epoques_perdues": self._epoques_perdues,
        })
        return base


def _selftest():
    """L'accord des deux épochages, les trois abandons, et la forme de l'instantané.

    Aucun casque, aucune fenêtre, aucune attente réelle : l'horloge est FABRIQUÉE (`tick` reçoit
    `now`) et le tampon EEG est synthétique mais HORODATÉ, comme celui du vrai moteur.
    """
    import json

    import numpy as np

    from core.modes.calibration import PHASES, PHASES_TERMINALES
    from core.modes.p300 import SPEC as SPEC_P300, P300Runtime

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _FausseAcq:
        fs = 250.0

    class _MoteurFactice:
        """Le strict nécessaire : un tampon EEG HORODATÉ et la file de marqueurs du moteur.

        Le signal porte une RAMPE sur sa première voie, en plus du bruit. Ce n'est pas cosmétique :
        avec du bruit seul, deux échantillons voisins peuvent coïncider et un décalage d'un
        échantillon ne se verrait que par chance. Avec la rampe, tout décalage change forcément la
        valeur, donc le test d'alignement ne dépend plus du tirage.
        """

        def __init__(self, secondes=20.0, t0=1000.0, graine=0):
            self.acq = _FausseAcq()
            self.t0 = t0
            self.recent_ts = np.arange(t0, t0 + secondes, 1.0 / self.acq.fs)
            rng = np.random.default_rng(graine)
            self.recent = rng.normal(0.0, 5.0, (len(self.recent_ts), 8))
            self.recent[:, 0] = np.arange(len(self.recent_ts), dtype=float)
            self._lots = []
            self.appels_murs = 0

        def file(self, lot):
            """Un lot de marqueurs, rendu au PROCHAIN appel de `markers_murs`."""
            self._lots.append(list(lot))

        def markers_murs(self, mode_id, post_s):
            self.appels_murs += 1
            return self._lots.pop(0) if self._lots else []

    class _CalibrationDeTest(MarkerCalibrationRuntime):
        """Le patron exact d'une sous-classe réelle : elle ne fournit que la géométrie, l'étiquette
        et l'entraînement. Calquée sur le P300 — `cue` porte l'étiquette, `flash` délimite
        l'époque — précisément parce que ce sont deux marqueurs DIFFÉRENTS."""

        runtime_cls_du_mode = P300Runtime
        classes = ("non-cible", "cible")
        duree_protocole_s = 60.0

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._cible = None
            self.entrainements = 0        # combien de fois `_entrainer` a été APPELÉE

        def _etiquette(self, ts, marqueur):
            event = marqueur.get("event")
            if event == "cue":
                self._cible = marqueur.get("target")
                self.classe = f"cible {self._cible}"
                return None
            if event == "flash":
                return "cible" if marqueur.get("target") == self._cible else "non-cible"
            return None

        def _entrainer(self, enregistre, fs):
            self.entrainements += 1
            return {"n_essais": len(enregistre), "fs": fs,
                    "classes": sorted({lab for _e, lab in enregistre}),
                    "cv_groupee": 0.5, "cv_naive": 0.6, "hasard": 0.5,
                    "n_fenetres": len(enregistre), "nom": "essai.joblib", "verdict": "ESSAI"}

    def marqueur(event, **champs):
        return {"mode": "p300", "event": event, **champs}

    def demarree(moteur, essais_annonces=6, cls=None):
        """Une calibration lancée, annonce reçue, chauffe PASSÉE — l'état normal d'une séance."""
        rt = (cls or _CalibrationDeTest)(SPEC_P300, {}, moteur)
        rt.tick(moteur, moteur.t0)                     # démarre la chauffe
        rt.encaisser(moteur, moteur.t0, marqueur("calib_start", trials=essais_annonces))
        rt.tick(moteur, moteur.t0 + rt.warmup_s + 0.1)  # la chauffe s'écoule -> « essais »
        return rt

    # Une SECONDE géométrie d'époque, et elle n'est pas décorative — sans elle, LE test ci-dessous
    # serait INFALSIFIABLE, ce qui est mesuré, pas supposé.
    #
    # ⚠️ À la géométrie du P300 (pre_s = 0,15 s, fs = 250 Hz), un « décalage d'un échantillon »
    # écrit `pre_s + 1/fs` N'EN EST PAS UN : `epoch_from_stream` calcule
    # `int(round(pre_s * fs))`, et `round()` de Python arrondit la moitié vers le PAIR —
    # `round(37,5)` et `round(38,5)` valent tous les deux 38. La mutation ne déplace donc RIEN, et
    # un test écrit sur cette seule géométrie resterait vert en la subissant : impossible de
    # prouver qu'il sait rougir, c'est-à-dire qu'il teste quelque chose.
    # À 0,30 s l'absorption n'a pas lieu (75 -> 76), et la même mutation se voit. On vérifie donc
    # l'accord sur les DEUX.
    class _AutreGeometrie:
        pre_s, post_s = 0.30, 0.40

    class _CalibAutreGeometrie(_CalibrationDeTest):
        runtime_cls_du_mode = _AutreGeometrie

    def accord(cls):
        """Fait vivre une séance à `cls`, puis rejoue les MÊMES instants par le chemin du décodage.

        Rend `(rt, époques enregistrées, époques décodées)` — deux listes obtenues avec exactement
        les mêmes entrées, par deux chemins de code différents.
        """
        moteur_a = _MoteurFactice()
        rt_a = demarree(moteur_a, essais_annonces=12, cls=cls)
        rt_a.encaisser(moteur_a, moteur_a.t0 + 4.0, marqueur("cue", target=1))
        instants_a = [moteur_a.t0 + 5.0 + 0.37 * i for i in range(12)]
        for ts in instants_a:
            rt_a.encaisser(moteur_a, ts, marqueur("flash", target=1))
        enregistrees = [np.asarray(e) for e, _lab in rt_a._enregistre]
        # La géométrie est lue sur le runtime de DÉCODAGE, ici comme dans le mode : c'est le seul
        # endroit du test qui a le droit de la nommer.
        decodees = [epoch_from_stream(moteur_a.recent, moteur_a.recent_ts, ts, moteur_a.acq.fs,
                                      pre_s=cls.runtime_cls_du_mode.pre_s,
                                      post_s=cls.runtime_cls_du_mode.post_s)
                    for ts in instants_a]
        return rt_a, enregistrees, decodees

    # === LE test : l'accord des deux épochages ==============================================
    # Deux chemins, EXACTEMENT les mêmes entrées : (a) la calibration qui enregistre ses époques,
    # (b) l'appel que le mode fait en décodant. Un décalage entre les deux ne lève rien et se
    # traduit par un modèle qui décode du bruit avec confiance — la panne la plus coûteuse de ce
    # projet, et la seule que ce module existe pour fermer.
    for cls_geo, nom_geo in ((_CalibrationDeTest, "géométrie P300 (0,15 / 0,80 s)"),
                             (_CalibAutreGeometrie, "géométrie 0,30 / 0,40 s")):
        rt_g, enregistrees, decodees = accord(cls_geo)
        chk(len(enregistrees) == 12 and all(e is not None for e in decodees),
            f"[{nom_geo}] les deux chemins produisent une époque pour chacun des 12 marqueurs "
            f"({len(enregistrees)} enregistrées)")
        chk(all(a.shape == b.shape for a, b in zip(enregistrees, decodees)),
            f"[{nom_geo}] …de MÊME FORME : même nombre d'échantillons, mêmes voies "
            f"({enregistrees[0].shape} contre {decodees[0].shape})")
        ecarts = [int(np.abs(a - b).max() > 0)
                  for a, b in zip(enregistrees, decodees) if a.shape == b.shape]
        chk(len(ecarts) == 12 and sum(ecarts) == 0,
            f"[{nom_geo}] et IDENTIQUES À L'ÉCHANTILLON PRÈS : un décalage d'un seul échantillon "
            f"entraînerait le modèle sur un alignement et l'appliquerait sur un autre, sans lever "
            f"d'exception ({sum(ecarts)} époque(s) différente(s) sur {len(ecarts)} comparables)")
        chk(rt_g.pre_s == cls_geo.runtime_cls_du_mode.pre_s
            and rt_g.post_s == cls_geo.runtime_cls_du_mode.post_s,
            f"[{nom_geo}] la calibration LIT pre_s/post_s sur le runtime de DÉCODAGE "
            f"({rt_g.pre_s}, {rt_g.post_s})")

    # La preuve que c'est bien une LECTURE et pas une coïncidence de valeurs : les deux géométries
    # ci-dessus ne diffèrent QUE par `runtime_cls_du_mode`, et la longueur prélevée suit. Deux
    # constantes recopiées passeraient les assertions du jour de leur écriture, et divergeraient
    # au premier changement, en silence.
    _rt_p300, epo_p300, _d = accord(_CalibrationDeTest)
    _rt_autre, epo_autre, _d = accord(_CalibAutreGeometrie)
    chk(len(epo_p300[0]) == int(round(P300Runtime.pre_s * 250.0))
        + int(round(P300Runtime.post_s * 250.0))
        and len(epo_autre[0]) == 175 and len(epo_p300[0]) != len(epo_autre[0]),
        f"changer la géométrie du runtime de décodage DÉPLACE la calibration du même coup "
        f"({len(epo_p300[0])} échantillons contre {len(epo_autre[0])})")

    # Une séance VIVANTE, à la géométrie réelle, réutilisée par deux contrôles plus bas.
    rt, moteur = _rt_p300, _rt_p300.engine

    # Et l'oubli de la déclarer se dit, au lieu de sortir un `NoneType` incompréhensible.
    class _SansGeometrie(_CalibrationDeTest):
        runtime_cls_du_mode = None

    try:
        _SansGeometrie(SPEC_P300, {}, _MoteurFactice()).pre_s
        chk(False, "une sous-classe sans `runtime_cls_du_mode` doit être refusée")
    except ValueError as e:
        chk("runtime_cls_du_mode" in str(e),
            f"…et le refus nomme le champ manquant ({str(e)[:60]}…)")

    # === Cause d'abandon n°1 : la fenêtre ne s'est jamais annoncée ===========================
    moteur1 = _MoteurFactice()
    rt1 = _CalibrationDeTest(SPEC_P300, {}, moteur1)
    rt1.tick(moteur1, moteur1.t0)
    rt1.tick(moteur1, moteur1.t0 + CALIB_FENETRE_ATTENTE_S - 1.0)
    chk(rt1.phase == "chauffe",
        f"avant le délai, la calibration attend encore la fenêtre ({rt1.phase})")
    rt1.tick(moteur1, moteur1.t0 + CALIB_FENETRE_ATTENTE_S + 1.0)
    chk(rt1.phase == "annule" and rt1.resultat is None,
        f"sans calib_start dans les {CALIB_FENETRE_ATTENTE_S:.0f} s, la calibration s'annule "
        f"({rt1.phase})")
    chk("fenêtre" in rt1.probleme and MARKER_STREAM_DEFAULT in rt1.probleme,
        f"…en disant les DEUX causes possibles : pas lancée, ou publiant sous un autre nom que "
        f"celui qu'on écoute ({rt1.probleme})")
    chk(rt1.entrainements == 0, "et sans avoir appelé l'entraînement une seule fois")

    # === Cause d'abandon n°2 : la fenêtre est morte en cours ================================
    # Piloté par la VRAIE porte (`markers_murs` -> `tick`), pas par `encaisser` : c'est `tick` qui
    # tient l'horloge du silence, et un test qui court-circuiterait cette porte ne prouverait rien
    # du délai.
    moteur2 = _MoteurFactice()
    rt2 = demarree(moteur2, essais_annonces=10)
    t2 = moteur2.t0 + rt2.warmup_s + 0.1
    moteur2.file([(moteur2.t0 + 5.0, marqueur("cue", target=0)),
                  (moteur2.t0 + 5.2, marqueur("flash", target=0))])
    rt2.tick(moteur2, t2 + 1.0)
    chk(rt2.phase == "essais" and rt2.essai == 1,
        f"un marqueur arrive : la séance vit et compte son essai ({rt2.phase}, {rt2.essai})")
    rt2.tick(moteur2, t2 + 1.0 + CALIB_FENETRE_SILENCE_S - 0.5)
    chk(rt2.phase == "essais",
        f"un silence PLUS COURT que le seuil ne tue rien — la pause de 2,5 s entre deux manches "
        f"P300 est normale ({rt2.phase})")
    rt2.tick(moteur2, t2 + 1.0 + CALIB_FENETRE_SILENCE_S + 0.5)
    chk(rt2.phase == "annule" and rt2.resultat is None and rt2.entrainements == 0,
        f"au-delà du seuil, la fenêtre est réputée morte : la séance s'annule SANS entraîner "
        f"({rt2.phase}, {rt2.entrainements} entraînement(s))")
    chk(rt2._enregistre == [],
        "et les époques déjà enregistrées sont LIBÉRÉES : une séance tronquée produirait un "
        "modèle que rien ne distingue d'un modèle complet dans la liste")
    chk("10" in rt2.probleme and "1" in rt2.probleme,
        f"…le refus disant combien d'essais sont arrivés sur combien d'annoncés ({rt2.probleme})")

    # Le pendant du précédent : tous les essais annoncés SONT arrivés, seul `calib_end` manque.
    # Ce n'est pas une fenêtre morte, c'est une séance complète — la jeter détruirait des minutes
    # de signal bon.
    moteur2b = _MoteurFactice()
    rt2b = demarree(moteur2b, essais_annonces=1)
    t2b = moteur2b.t0 + rt2b.warmup_s + 0.1
    moteur2b.file([(moteur2b.t0 + 5.0, marqueur("flash", target=0))])
    rt2b.tick(moteur2b, t2b + 1.0)
    rt2b.tick(moteur2b, t2b + 1.0 + CALIB_FENETRE_SILENCE_S + 0.5)
    chk(rt2b.essai == 1 and rt2b.phase == "essais",
        f"tous les essais annoncés reçus, calib_end manquant : la séance ATTEND au lieu de jeter "
        f"({rt2b.phase}, {rt2b.essai}/{rt2b.total()})")

    # === Cause d'abandon n°3 : l'utilisateur annule =========================================
    moteur3 = _MoteurFactice()
    rt3 = demarree(moteur3, essais_annonces=4)
    rt3.encaisser(moteur3, moteur3.t0 + 5.0, marqueur("flash", target=0))
    chk(len(rt3._enregistre) == 1, "une époque est bien enregistrée avant l'abandon")
    rt3.cancel()
    chk(rt3.terminee and rt3.phase == "annule" and rt3.resultat is None
        and rt3._enregistre == [] and rt3.engine is None and rt3.entrainements == 0,
        f"l'abandon libère les époques ET la référence au moteur, et n'entraîne rien "
        f"({rt3.phase}, {len(rt3._enregistre)} époque(s), engine={rt3.engine})")
    rt3.tick(moteur3, moteur3.t0 + 500.0)
    chk(rt3.phase == "annule" and rt3.essai == 1,
        "et une calibration annulée ne repart pas toute seule au tick suivant")

    # === Un marqueur reçu HORS calibration est ignoré, sans erreur ==========================
    moteur4 = _MoteurFactice()
    rt4 = _CalibrationDeTest(SPEC_P300, {}, moteur4)      # jamais démarrée
    rt4.encaisser(moteur4, moteur4.t0 + 1.0, marqueur("cue", target=3))
    rt4.encaisser(moteur4, moteur4.t0 + 1.2, marqueur("flash", target=3))
    chk(rt4._enregistre == [] and rt4.phase == "chauffe",
        "un marqueur reçu hors calibration est ignoré sans erreur : c'est une fenêtre lancée en "
        "mode calibration pendant qu'un décodage tourne, et le moteur n'a pas à s'arrêter pour ça")
    rt5 = demarree(_MoteurFactice(), essais_annonces=2)
    rt5.cancel()
    rt5.encaisser(moteur4, moteur4.t0 + 2.0, marqueur("flash", target=0))
    chk(rt5._enregistre == [],
        "…et une fenêtre qui parle encore APRÈS l'abandon ne réveille rien non plus")
    avant_inconnu = len(rt._enregistre)
    rt.encaisser(moteur, moteur.t0 + 6.0, marqueur("un_evenement_futur", valeur=1))
    chk(len(rt._enregistre) == avant_inconnu,
        "un événement que la sous-classe ne connaît pas est ignoré, pas refusé : le protocole "
        "s'enrichira, et un moteur qui casserait au premier ajout serait inutilisable")

    # === La séance NOMINALE, de bout en bout, par la vraie porte ============================
    moteur6 = _MoteurFactice()
    rt6 = _CalibrationDeTest(SPEC_P300, {}, moteur6)
    t0 = moteur6.t0
    rt6.tick(moteur6, t0)
    chk(rt6.phase == "chauffe" and rt6.state(now=t0)["restant_s"] > 0.0,
        f"on commence par la chauffe, et elle se décompte à l'écran ({rt6.phase}, "
        f"{rt6.state(now=t0)['restant_s']} s)")

    # L'annonce ARRIVE PENDANT la chauffe — le cas normal : la console lance la fenêtre au moment
    # même où elle demande la calibration. Elle est retenue ; ce qui suit est jeté.
    moteur6.file([(t0 + 1.0, marqueur("calib_start", trials=4)),
                  (t0 + 1.5, marqueur("cue", target=2)),
                  (t0 + 2.0, marqueur("flash", target=2))])
    rt6.tick(moteur6, t0 + 2.5)
    chk(rt6.phase == "chauffe" and rt6.total() == 4,
        f"l'annonce reçue pendant la chauffe est RETENUE — sinon la fenêtre devrait deviner la "
        f"durée de la chauffe pour ne pas être déclarée absente ({rt6.total()} essais)")
    chk(rt6.essai == 0 and rt6._marqueurs_chauffe == 2,
        f"…mais les époques de cette période sont JETÉES et comptées : la dérive DC de l'Unicorn "
        f"les rendrait sans valeur ({rt6.essai} enregistrée(s), {rt6._marqueurs_chauffe} jetée(s))")

    rt6.tick(moteur6, t0 + rt6.warmup_s + 0.1)
    chk(rt6.phase == "essais" and rt6.state(now=t0 + rt6.warmup_s + 0.1)["restant_s"] == 0.0,
        f"la chauffe écoulée ouvre les essais, et plus rien n'y est décompté : c'est la FENÊTRE "
        f"qui mène, le moteur ne connaît pas son protocole ({rt6.phase})")

    moteur6.file([(t0 + 5.0, marqueur("cue", target=2))]
                 + [(t0 + 5.5 + 0.2 * i, marqueur("flash", target=(2 if i == 0 else 3)))
                    for i in range(4)])
    rt6.tick(moteur6, t0 + rt6.warmup_s + 0.5)
    chk(rt6.essai == 4 and rt6.total() == 4,
        f"les quatre essais annoncés sont enregistrés ({rt6.essai}/{rt6.total()})")
    etiquettes = [lab for _e, lab in rt6._enregistre]
    chk(etiquettes == ["cible", "non-cible", "non-cible", "non-cible"],
        f"l'étiquette vient du `cue`, l'époque du `flash` : deux marqueurs DIFFÉRENTS, et c'est "
        f"la sous-classe qui décide lequel fait quoi ({etiquettes})")

    moteur6.file([(t0 + 6.5, marqueur("calib_end"))])
    rt6.tick(moteur6, t0 + rt6.warmup_s + 0.7)
    chk(rt6.phase == "entrainement" and rt6.entrainements == 0,
        f"`calib_end` ouvre l'entraînement mais ne l'exécute PAS dans le même tour : la console "
        f"doit pouvoir peindre « entraînement » avant que la boucle ne bloque plusieurs secondes "
        f"({rt6.phase})")
    rt6.tick(moteur6, t0 + rt6.warmup_s + 0.8)
    chk(rt6.phase == "fini" and rt6.entrainements == 1,
        f"le tour suivant entraîne, une seule fois ({rt6.phase}, {rt6.entrainements})")
    chk(rt6.resultat and rt6.resultat["n_essais"] == 4
        and rt6.resultat["fs"] == moteur6.acq.fs,
        f"et c'est bien les 4 époques enregistrées qui partent à l'entraînement, à la fréquence "
        f"du moteur ({rt6.resultat})")

    # Un entraînement qui lève ne tue pas le moteur : il se solde en « annulé » + raison. Hérité de
    # `CalibrationRuntime._terminer`, donc rejoué ici sur CETTE ligne du temps, qui n'est pas la
    # sienne.
    class _Casse(_CalibrationDeTest):
        def _entrainer(self, enregistre, fs):
            raise ValueError("pas assez de données")

    moteur7 = _MoteurFactice()
    rt7 = _Casse(SPEC_P300, {}, moteur7)
    rt7.tick(moteur7, moteur7.t0)
    rt7.encaisser(moteur7, moteur7.t0, marqueur("calib_start", trials=1))
    rt7.tick(moteur7, moteur7.t0 + rt7.warmup_s + 0.1)
    rt7.encaisser(moteur7, moteur7.t0 + 5.0, marqueur("calib_end"))
    rt7.tick(moteur7, moteur7.t0 + rt7.warmup_s + 0.2)
    chk(rt7.phase == "annule" and "pas assez de données" in rt7.probleme,
        f"un entraînement qui lève se solde par un refus lisible, pas par un moteur à terre "
        f"({rt7.phase}, {rt7.probleme})")

    # === La forme de l'instantané ==========================================================
    # `console/calib_page.py` est GÉNÉRIQUE : elle ne connaît aucun mode et lit ces champs sans
    # jamais les tester. Un champ manquant ne lève RIEN — la page reste simplement vide.
    lus_par_la_console = {"mode_id", "phase", "etape", "classe", "instruction", "rappel",
                          "essai", "total", "restant_s", "duree_estimee_s", "resultat",
                          "probleme"}
    etat = rt6.state(now=t0 + 20.0)
    chk(set(etat) >= lus_par_la_console,
        f"l'instantané porte tout ce que la page de calibration lit "
        f"({sorted(lus_par_la_console - set(etat)) or 'aucun champ manquant'})")

    # Et la garantie STRUCTURELLE derrière : la forme n'est pas recopiée, elle vient du parent.
    class _CalibMoteur(CalibrationRuntime):
        classes = ("A",)

        def _entrainer(self, enregistre, fs):
            return {}

    reference = _CalibMoteur(SPEC_P300, {}, None).state(now=0.0)
    chk(set(reference) <= set(etat),
        f"…et c'est un SUR-ENSEMBLE de celui d'une calibration menée par le moteur : la forme "
        f"vient de `CalibrationRuntime.state`, elle n'est pas recopiée "
        f"({sorted(set(reference) - set(etat)) or 'aucun écart'})")

    try:
        json.dumps(etat)
        serialisable = True
    except (TypeError, ValueError):
        serialisable = False
    chk(serialisable, "l'instantané est sérialisable en JSON — il part dans `snapshot()`")
    chk(etat["phase"] in PHASES and rt3.phase in PHASES_TERMINALES,
        f"les phases sont celles du vocabulaire PUBLIC, importées et non redéclarées "
        f"({etat['phase']})")
    chk(etat["mode_id"] == SPEC_P300.id,
        f"l'instantané se réclame de SON mode : la page filtre dessus pour ne jamais présenter la "
        f"séance d'un autre mode comme la sienne ({etat['mode_id']})")

    # ⚠️ Le piège de l'affichage : `CalibPage._maybe_beep` joue un top au front montant de `etape`
    # vers « cue ». Recopier ici le nom de l'événement reçu ferait sonner la console à chaque cue
    # du P300, par-dessus un stimulus visuel, dans une séance où le sujet doit rester immobile.
    etapes = {rt6.state(now=t0)["etape"], rt.state(now=t0)["etape"], etat["etape"]}
    chk(etapes == {""},
        f"`etape` reste VIDE de bout en bout : la console ne doit jamais biper par-dessus le "
        f"stimulus d'une fenêtre ({etapes})")

    chk(abs(rt6.duree_estimee_s() - (rt6.warmup_s + 60.0)) < 1e-9,
        f"la durée estimée est la chauffe plus ce que la SOUS-CLASSE sait de son protocole — le "
        f"moteur, lui, ne peut pas le deviner ({rt6.duree_estimee_s():.1f} s)")

    # === Les garde-fous de l'annonce =======================================================
    moteur8 = _MoteurFactice()
    rt8 = _CalibrationDeTest(SPEC_P300, {}, moteur8)
    rt8.tick(moteur8, moteur8.t0)
    rt8.encaisser(moteur8, moteur8.t0, marqueur("calib_start", trials=True))
    chk(rt8.total() == 0,
        f"`trials: true` n'est PAS 1 essai annoncé : en Python `bool` hérite de `int`, et une "
        f"séance de 300 époques serait déclarée complète dès la première ({rt8.total()})")
    rt8.tick(moteur8, moteur8.t0 + rt8.warmup_s + 0.1)
    rt8.tick(moteur8, moteur8.t0 + rt8.warmup_s + CALIB_FENETRE_SILENCE_S + 1.0)
    chk(rt8.phase == "annule",
        f"…et un total inconnu fait traiter le silence comme une mort, faute de pouvoir prouver "
        f"que la séance est complète ({rt8.phase})")

    chk(MarkerCalibrationRuntime.imagery_s is None,
        "⚠️ `imagery_s` est NEUTRALISÉE : `registry.check()` la compare à `Calib.epoch_s` pour une "
        "calibration menée par le moteur, et le 4 s hérité ferait refuser les trois calibrations "
        "à fenêtre pour une grandeur que personne n'y prélève")

    print(f"[marker-calib] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
