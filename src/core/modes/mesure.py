"""`MesureRuntime` — un protocole minuté qui rend un VERDICT, pas un modèle.

Le moteur sait déjà jouer une CALIBRATION : chauffe, essais, entraînement, un modèle sur le
disque. Une MESURE est la même mécanique amputée de sa fin. Elle joue une suite d'étapes minutées,
prélève une fenêtre de signal à la fin de celles qui sont enregistrées, et rend une PHRASE qu'on
lit à l'écran. **Rien ne va sur le disque** : ni modèle, ni enregistrement, ni dossier candidat.

Ce que ce socle existe pour porter — les deux premières mesures du produit, écrites ailleurs :

  • le **contrôle alpha** (effet de Berger : yeux ouverts / yeux fermés), qui est une BARRIÈRE —
    si l'alpha ne monte pas, aucune autre mesure de la séance ne veut rien dire ;
  • le **taux d'émission du SSVEP**, qui compte des décisions du moteur plutôt que des fenêtres.

⚠️ **Cette classe HÉRITE de `CalibrationRuntime`, et ce n'est pas de la commodité** — c'est le
même argument que `modes/marker_calib.py`, son autre frère. Ce qu'elle en reprend sans y toucher
— `state()`, `restant_s()`, `terminee`, `_terminer()` et son traitement d'exception — est
exactement le CONTRAT PUBLIC que `src/console/calib_page.py` consomme. Cette page est générique,
elle ne connaît aucun mode : **si la forme de l'instantané diffère d'un seul champ, elle reste
VIDE sans lever la moindre erreur**. Hériter au lieu de recopier est ce qui interdit à ce champ de
manquer un jour.

⚠️ **Ce qu'une mesure n'a PAS, et c'est toute la différence** : pas de `dossier` candidat, pas de
`save_calibration`, aucun fichier. `dossier_ou_lever()` est donc neutralisée ici — elle refuse au
lieu de rendre un chemin — et `_entrainer` est SCELLÉE : le point d'extension d'une mesure est
`_mesurer(enregistre, fs)`, qui rend le dictionnaire de verdict.

⚠️ **Un runtime ne lit jamais l'horloge lui-même** : `tick` reçoit `now`, comme `ModeRuntime` et
comme `CalibrationRuntime`. C'est ce qui permet de jouer une séance de trois minutes en quelques
millisecondes dans un test — chauffe de 15 s comprise.

⚠️ **Le moteur n'en tient AU PLUS UNE, et jamais en même temps qu'une calibration.** Il n'y a
qu'un casque et qu'une personne : deux protocoles minutés prélèveraient leurs fenêtres dans le
MÊME tampon glissant pendant que chacun affiche sa propre consigne. Le refus vit dans
`EngineServer` (`_refus_pour_mesure` / `_refus_pour_calibration`), dans les deux sens et aux deux
instants ; il est vérifié plus bas, par cet autotest.

Autotest :
    python src/core/modes/mesure.py
"""

import os as _os
import sys as _sys
from dataclasses import dataclass

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import SSVEP_WARMUP_S, use_utf8_console  # noqa: E402
from core.modes.calibration import PHASES_TERMINALES, CalibrationRuntime  # noqa: E402
from core.modes.contract import _defaults_of  # noqa: E402

# Les phases publiques d'une MESURE, dans l'ordre où elles s'enchaînent. Elles sortent telles
# quelles dans `snapshot()["mesure"]["phase"]`.
#
# ⚠️ Ce n'est PAS la liste des calibrations, et le seul mot qui diffère porte tout l'écart : là où
# une calibration ENTRAÎNE, une mesure MESURE. Publier « entrainement » sur un protocole qui
# n'entraîne rien serait un mensonge dans l'état publié — pour un confort d'héritage.
PHASES = ("chauffe", "essais", "mesure", "fini", "annule")

# ⚠️ Le sous-ensemble terminal, lui, est IMPORTÉ de `modes/calibration.py` et **jamais recopié** :
# c'est la constante que `src/console/calib_page.py` importe pour décider quand montrer l'écran de
# résultat. Deux tuples `("fini", "annule")` écrits côte à côte se ressembleraient jusqu'au jour
# où l'un des deux serait renommé — et la page resterait alors sans écran de verdict, en silence.
# Le `chk` de `_selftest` vérifie que les deux vocabulaires s'accordent encore.
PHASES_TERMINALES = PHASES_TERMINALES


@dataclass(frozen=True)
class Etape:
    """Un segment minuté du protocole : ce qu'on demande, combien de temps, et si on l'enregistre.

    `enregistre=False` est la PRÉPARATION : les trois secondes pendant lesquelles on lit « ferme
    les yeux dans 3… 2… 1 ». Le signal y est celui d'un sujet qui bouge encore, et le compter avec
    le reste noierait l'effet cherché dans la transition qui le précède. C'est la même distinction
    que l'échauffement d'une calibration : joué, montré, **pas** enregistré.

    ⚠️ `duree_s` sert DEUX fois, et c'est délibéré : elle minute l'étape, ET c'est la longueur de
    la fenêtre prélevée à sa fin (`engine.recent_window(duree_s)`). Une étape de 8 s rend donc
    exactement les 8 s qu'elle a durées — jamais une fenêtre plus longue, qui déborderait sur
    l'étape précédente, où le sujet faisait autre chose.
    """

    nom: str                    # "yeux fermés" — l'étiquette rendue à `_mesurer`, et affichée
    duree_s: float
    enregistre: bool = True
    instruction: str = ""       # la consigne à afficher EN GRAND pendant cette étape
    rappel: str = ""            # la ligne secondaire, sous la consigne


@dataclass(frozen=True)
class MesureSpec:
    """Ce que le produit sait d'une mesure. L'équivalent d'un `ModeSpec`, en beaucoup plus court.

    Une mesure ne publie AUCUN flux, n'a ni repos, ni voies, ni marqueurs : elle n'a qu'un nom, un
    briefing, des réglages et un runtime. D'où un contrat propre plutôt qu'un `ModeSpec` dont sept
    champs sur douze resteraient vides — et sept champs vides sont sept invitations à croire
    qu'ils servent.

    `params` sont de vrais `contract.Param` : c'est ce qui fait que `contract.validate` les valide
    sans une ligne de plus, et que la console en génère un formulaire avec le même `ParamsForm`
    que les modes et les calibrations. Un second validateur serait une seconde vérité.
    """

    id: str                     # "alpha" — clé stable, celle de la commande `start_mesure`
    label: str                  # "Contrôle alpha"
    summary: str = ""           # une phrase : ce que cette mesure répond
    briefing: tuple = ()        # les consignes à lire AVANT de commencer, une ligne par élément
    params: tuple = ()          # les `Param` réglables de la mesure
    runtime_cls: object = None  # la classe `MesureRuntime`, ou None si elle n'est pas livrée
    barriere: bool = False      # cette mesure ARRÊTE-t-elle la séance quand elle échoue ?
    #                             (le contrôle alpha, oui : sans alpha rien d'autre ne veut dire
    #                             quoi que ce soit. Le taux SSVEP, non : c'est un chiffre à lire.)
    stimulus_id: str = ""       # la CLÉ de la fenêtre à ouvrir en même temps, ou "" si la mesure
    #                             se joue sans écran. Exactement la même clé et le même rôle que
    #                             `Calib.stimulus_id` : `core` ne nomme aucun fichier de fenêtre,
    #                             c'est `stimulus/registry.py` qui détient la correspondance. Le
    #                             contrôle alpha n'en a pas (rien à montrer, les yeux sont fermés
    #                             la moitié du temps) ; le taux SSVEP en a un, puisqu'il n'y a
    #                             rien à décoder sans cibles qui clignotent.

    def defaults(self):
        """Les réglages par défaut de cette mesure, résolus maintenant.

        Même mécanique que `ModeSpec.defaults` et `Calib.defaults` — la fonction est PARTAGÉE, pas
        recopiée, pour que `validate` traite les trois sans distinction.
        """
        return _defaults_of(self.params)

    @property
    def calibration(self):
        """Elle-même. ⚠️ Ce n'est pas une bizarrerie : c'est ce qui permet d'HÉRITER du contrat.

        `CalibrationRuntime.__init__` fait `self.calib = spec.calibration`, et `state()` en tire
        le libellé de l'écran. Une calibration est déclarée PAR un mode ; une mesure, elle, n'a
        pas de mode au-dessus d'elle — elle EST ce que la console affiche. Rendre `self` ici est
        donc la traduction exacte de « son propre `Calib` », et c'est ce qui évite de réécrire
        `__init__` et `state()` juste pour un libellé. Un `state()` recopié est un champ qui
        manquera un jour, et la page restera vide sans lever la moindre erreur.
        """
        return self


class MesureRuntime(CalibrationRuntime):
    """Une mesure en cours. Le moteur en tient AU PLUS UNE, et jamais avec une calibration.

    Une sous-classe fournit DEUX choses, et rien d'autre :
      1. `protocole()` — la suite d'`Etape` à jouer, dans l'ordre ;
      2. `_mesurer(enregistre, fs)` — le calcul, qui rend le dictionnaire de verdict.
    """

    # La MÊME chauffe que les modes, que la calibration MI et que les calibrations à fenêtre :
    # c'est la même dérive DC de l'Unicorn (mesurée le 2026-07-27 : 10⁵ µV en rampe après ouverture
    # de session), et elle ne dépend pas de ce qu'on mesure ensuite. Une fenêtre prélevée là-dedans
    # ne vaut rien — et pour le contrôle alpha, dont tout le verdict tient dans un RAPPORT de
    # puissances, un offset dérivant fausse les deux termes de façon différente. Ne pas la
    # raccourcir « pour les tests » : `tick` reçoit son horloge, donc 15 s ne coûtent rien à un
    # test (cf. `_selftest`, qui joue trois protocoles complets en quelques millisecondes).
    warmup_s = SSVEP_WARMUP_S

    # Comment cette séance se nomme dans le journal. `_terminer` est HÉRITÉE (c'est tout l'intérêt
    # de ce module), et sans ces deux mots un contrôle alpha raté s'annoncerait « [calib]
    # entraînement impossible » — un étudiant irait chercher un modèle que personne n'a demandé.
    _journal = "mesure"
    _nom_du_calcul = "calcul du verdict"

    # Ce que cette mesure prélève AUTOUR D'UN MARQUEUR, en secondes. 0 = elle n'en prélève pas (le
    # contrôle alpha, dont les fenêtres viennent de sa propre ligne du temps).
    #
    # ⚠️ Ce champ existe pour DIMENSIONNER le tampon du moteur (`EngineServer.__init__`, terme
    # `epoque_mesure`), et il doit être déclaré ici plutôt que déduit. Le tampon n'était couvert
    # que par accident, à travers l'`epoch_s` de la calibration MI (4 s) — une grandeur qui n'a
    # aucun rapport avec une mesure. Le jour où le MI raccourcirait la sienne, chaque époque de
    # cette mesure serait TRONQUÉE en silence, et le verdict porterait sur moins de signal que ce
    # que l'écran annonce. Nommer le besoin est ce qui empêche cette panne-là.
    epoque_marqueur_s = 0.0

    # ⚠️ **La plus longue étape ENREGISTRÉE de ce protocole, en secondes.** Le moteur dimensionne
    # son tampon dessus, exactement comme il le fait sur `Calib.epoch_s` et `marker_epoch_s`.
    #
    # Sans ce terme, le contrôle alpha demandait des fenêtres de 8 s à un tampon qui n'en gardait
    # que 5 : les deux étapes étaient « IGNORÉES », `_mesurer` recevait une liste VIDE, et la
    # séance se soldait en `annule` avec un message qui accusait le PROTOCOLE (« phase
    # manquante ») au lieu du tampon. La barrière d'entrée de toute séance ne pouvait donc jamais
    # être franchie — trouvé par la revue de branche du 2026-09-10, jamais par un test, parce que
    # les deux moteurs factices rendent TOUJOURS la longueur demandée.
    #
    # `epoque_marqueur_s` ne pouvait pas couvrir ce cas et n'était pas censé le faire : sa
    # docstring dit « autour d'un MARQUEUR », et le contrôle alpha y met légitimement 0 — ses
    # fenêtres viennent de sa propre ligne du temps. Deux besoins, deux déclarations.
    @classmethod
    def epoque_etape_s(cls):
        """Calculée depuis `protocole()`, jamais recopiée : une constante à tenir à jour à la main
        finirait par mentir le jour où quelqu'un rallonge une étape."""
        try:
            etapes = cls.protocole(cls)
        except Exception:      # noqa: BLE001 - un protocole qui exige une instance : on ne devine pas
            return 0.0
        return max([float(e.duree_s) for e in etapes if getattr(e, "enregistre", True)] or [0.0])

    # --- ce qui appartient à la ligne du temps d'une CALIBRATION, et pas à celle-ci -----------
    # Ces quatre-là découpent un essai que le moteur mène (top, imagerie, repos) et comptent un
    # échauffement qu'il joue. Une mesure n'a rien de tout ça : elle a des ÉTAPES, de durées
    # libres, dont certaines seulement sont enregistrées. Mis à zéro plutôt que laissés à la
    # valeur héritée : un `cue_s = 3.0` visible sur une classe qui ne cue rien est une invitation
    # à croire qu'il sert.
    cue_s = 0.0
    rest_s = 0.0
    warmup_per_class = 0
    classes = ()
    # ⚠️ `imagery_s = None` comme dans `marker_calib.py`, et pour la même raison : c'est
    # `registry.check()` qui compare `Calib.epoch_s` à `imagery_s` pour empêcher un tampon
    # sous-dimensionné. Une mesure n'a pas de `Calib`, donc ce contrôle ne la vise pas ; laisser
    # hériter le `4.0` du parent afficherait une durée d'époque que personne ici ne prélève.
    imagery_s = None

    def __init__(self, spec, params, engine, rng=None):
        """`spec` : le `MesureSpec`. `params` : les réglages VALIDÉS de la mesure.

        ⚠️ **Pas de `dossier`, et l'argument est absent de la signature** — un appelant qui en
        passerait un obtient un `TypeError` bruyant plutôt qu'un chemin ignoré en silence. Une
        mesure n'écrit RIEN : c'est sa définition, pas une limitation à contourner (cf.
        `dossier_ou_lever`).
        """
        super().__init__(spec, params, engine, rng=rng, dossier=None)
        # Le protocole est figé À LA CONSTRUCTION, et pas au premier tick : la console affiche la
        # durée estimée et « essai 0 sur N » AVANT que la séance ne démarre, et le moteur imprime
        # la même estimation quand il l'accepte. Un protocole recalculé à chaque appel pourrait
        # rendre deux réponses différentes — l'écran annoncerait alors une séance et en jouerait
        # une autre.
        self._etapes = tuple(self.protocole())
        self._etape_courante = None

    # --- ce que la sous-classe fournit ---------------------------------------

    def protocole(self):
        """La suite d'`Etape` de CETTE mesure, dans l'ordre. À fournir par la sous-classe.

        Une MÉTHODE et non une constante de classe : la mesure SSVEP tire son nombre d'essais d'un
        réglage (`self.params`), qu'une constante ne peut pas lire.
        """
        raise NotImplementedError(
            f"{type(self).__name__} ne déclare aucun protocole : une mesure sans étape ne "
            f"prélèverait rien et rendrait un verdict sur une liste vide")

    def _mesurer(self, enregistre, fs):
        """Le calcul. Rend le dict de VERDICT, ou lève avec un message lisible.

        `enregistre` : `[(fenêtre (n, 8) non filtrée, nom de l'étape), ...]`, dans l'ordre de la
        séance — même forme que ce qu'une calibration passe à `_entrainer`.

        Le dictionnaire rendu doit porter au minimum `verdict` (la PHRASE qu'on lit) et
        `honnetete` (ce que ce chiffre ne dit pas). Les autres clés sont libres : la console rend
        ce qui est PRÉSENT, jamais ce qu'elle croit connaître d'un mode.

        ⚠️ **Aucun fichier.** Une mesure qui écrirait sur le disque rouvrirait exactement le
        défaut que `CalibrationRuntime.dossier_ou_lever` a fermé : un résultat retenu avant
        d'avoir été annoncé, donc jamais refusable.
        """
        raise NotImplementedError

    # --- ce qu'une mesure n'a PAS ---------------------------------------------

    def _entrainer(self, enregistre, fs):
        """SCELLÉE : elle délègue à `_mesurer` et ne doit pas être redéfinie.

        `_terminer` (hérité, non touché) appelle `_entrainer` et attrape ce qui lève pour solder
        la séance en « annulé » avec sa raison affichée. On garde donc ce chemin-là entier, et on
        n'expose qu'un seul nom aux sous-classes. Une sous-classe qui redéfinirait `_entrainer`
        court-circuiterait `_mesurer` sans que rien ne le dise — d'où le nom différent, qui rend
        la confusion visible à la lecture.
        """
        return self._mesurer(enregistre, fs)

    def dossier_ou_lever(self):
        """Refuse, toujours. Une mesure n'a pas de dossier parce qu'elle n'écrit rien.

        Le parent rend ici le dossier CANDIDAT d'une calibration. Hériter de ce comportement
        laisserait une future mesure y écrire un fichier que `save_calibration` déplacerait dans
        `data/` — c'est-à-dire faire entrer un verdict de séance dans le dossier qui porte les
        modèles et les enregistrements EEG, dont l'autorité doit rester unique.
        """
        raise ValueError(
            f"{type(self).__name__} est une MESURE : elle rend un verdict qu'on lit à l'écran et "
            f"n'écrit rien sur le disque. Elle n'a donc aucun dossier — si un fichier doit être "
            f"produit, c'est une calibration qu'il faut écrire, pas une mesure.")

    # --- la ligne du temps ---------------------------------------------------

    def etapes_enregistrees(self):
        """Les étapes du protocole dont la fenêtre part au calcul. L'unité de l'avancement."""
        return tuple(e for e in self._etapes if e.enregistre)

    def total(self):
        """Le nombre d'étapes ENREGISTRÉES. C'est l'unité que compte `self.essai`.

        Les préparations n'en font pas partie — comme l'échauffement d'une calibration : afficher
        « étape 1 sur 4 » pour un protocole qui ne prélève que deux fenêtres ferait lire une
        progression deux fois trop lente, et ferait attendre deux mesures là où il n'y en a
        qu'une.
        """
        return len(self.etapes_enregistrees())

    def duree_estimee_s(self):
        """La chauffe, plus TOUTES les étapes — préparations comprises. Calculé, jamais stocké.

        Les préparations comptent ici alors qu'elles ne comptent pas dans `total()`, et les deux
        sont justes : la personne les VIT (c'est du temps casque sur la tête), mais elles ne
        produisent aucune fenêtre.
        """
        return float(self.warmup_s) + sum(float(e.duree_s) for e in self._etapes)

    def instruction(self):
        """La consigne à afficher MAINTENANT, en grand. Elle vient de l'étape en cours.

        Une sous-classe peut la remplacer, mais n'a pas à le faire : porter la consigne dans
        l'`Etape` met le protocole et son texte au même endroit, donc une durée changée sans son
        texte se voit à la relecture.
        """
        if self.phase == "chauffe":
            return "Le casque se stabilise — la mesure commence dans un instant."
        if self.phase == "essais" and self._etape_courante is not None:
            return self._etape_courante.instruction
        if self.phase == "mesure":
            return "Calcul du verdict…"
        return ""

    def rappel(self):
        """La ligne secondaire, sous la consigne. Celle de l'étape en cours, ou "" ."""
        if self.phase == "essais" and self._etape_courante is not None:
            return self._etape_courante.rappel
        return ""

    def cancel(self):
        """Abandon. Aucun verdict n'est calculé sur ce qui a déjà été prélevé.

        Même choix que `CalibrationRuntime.cancel`, et pour une raison encore plus directe : un
        contrôle alpha interrompu après la seule phase « yeux ouverts » n'a pas de terme de
        comparaison — il rendrait un rapport calculé sur une moitié de protocole, sans que rien ne
        distingue ce chiffre d'un chiffre complet.
        """
        super().cancel()
        # Les mêmes deux lignes que le parent, un cran plus loin : `_suite` et l'étape en cours
        # portent le protocole, `super().cancel()` ne connaît que ses propres champs.
        self._etape_courante = None
        self._suite = []

    def tick(self, engine, now):
        """Un pas. Appelée par la boucle du moteur, jamais par une interface."""
        if self.terminee:
            return
        if not self._demarre:
            self._demarre = True
            self._echeance = now + self.warmup_s
            return

        if self._echeance is not None and now < self._echeance:
            return

        if self.phase == "chauffe":
            self._commencer_les_etapes(now)
        elif self.phase == "essais":
            self._pas_etape(engine, now)
        elif self.phase == "mesure":
            self._terminer(engine)

    def _commencer_les_etapes(self, now):
        """Fin de la chauffe : le protocole commence. Rien n'a été prélevé jusqu'ici."""
        self._suite = list(self._etapes)
        if not self._suite:
            # Un protocole vide ne bloque pas la boucle : on passe au calcul, qui recevra une
            # liste vide et dira lui-même ce qu'il en pense. Une mesure coincée en « essais »
            # pour toujours ressemblerait à un moteur figé.
            self._passer_au_calcul(now)
            return
        self.phase = "essais"
        self._entrer_dans_etape(now)

    def _entrer_dans_etape(self, now):
        etape = self._suite.pop(0)
        self._etape_courante = etape
        # `classe` est ce que la console affiche sous la consigne (« yeux fermés »). C'est le seul
        # champ de l'instantané qui nomme l'étape en cours — `etape`, lui, reste vide, cf. plus bas.
        self.classe = etape.nom
        self._echeance = now + float(etape.duree_s)

    def _pas_etape(self, engine, now):
        """L'étape en cours vient de se terminer : on prélève si elle est enregistrée, puis suite."""
        etape = self._etape_courante
        if etape is not None and etape.enregistre:
            # La fenêtre est prélevée À LA FIN de l'étape, exactement comme une époque d'imagerie
            # : le tampon glissant du moteur contient les `duree_s` dernières secondes, et ce sont
            # celles-là qu'on veut. ⚠️ `recent_window` rend du signal BRUT, non filtré — c'est
            # l'invariant de son accesseur, et chaque mesure applique le traitement qui la
            # concerne (le contrôle alpha veut voir tout le spectre, pas une bande déjà coupée).
            fenetre = engine.recent_window(etape.duree_s)
            attendu = int(round(float(etape.duree_s) * engine.acq.fs))
            if fenetre is not None and len(fenetre) >= attendu:
                self._enregistre.append((fenetre, etape.nom))
                self.essai += 1
            else:
                # On le DIT plutôt que de garder une fenêtre courte : deux fenêtres de longueurs
                # différentes donnent deux résolutions spectrales différentes, donc un rapport de
                # puissances qui compare autre chose que ce qu'on croit — en silence.
                obtenu = 0 if fenetre is None else len(fenetre)
                print(f"[mesure] étape IGNORÉE ({etape.nom}) : {obtenu} échantillons au lieu de "
                      f"{attendu} — le tampon du moteur n'était pas encore rempli")

        if self._suite:
            self._entrer_dans_etape(now)
        else:
            self._passer_au_calcul(now)

    def _passer_au_calcul(self, now):
        """Ouvre la phase « mesure », SANS calculer dans le même tour.

        ⚠️ Un tour d'écart, délibérément — même raison que `marker_calib.tick` : `_terminer`
        bloque la boucle du moteur le temps du calcul, et la console (qui sonde à 10 Hz) doit
        avoir pu peindre « Calcul du verdict… » au moins une fois avant. Sans ce décalage, l'écran
        reste sur la dernière étape pendant tout le calcul : exactement la tête d'un moteur figé.
        """
        self.phase = "mesure"
        self._etape_courante = None
        self.etape, self.classe, self._echeance = "", "", now

    # --- l'état, pour l'afficheur -------------------------------------------
    #
    # ⚠️ **`state()` n'est PAS redéfinie**, et c'est le point de tout ce module. Elle vient
    # entière de `CalibrationRuntime`, donc `src/console/calib_page.py` — page générique, qui ne
    # connaît aucun mode — y trouve tous les champs qu'elle lit, aujourd'hui et après le prochain
    # champ ajouté là-bas. Un champ manquant ne lèverait rien : la page resterait vide.
    #
    # ⚠️ **`etape` reste vide de bout en bout, et c'est délibéré**, exactement comme dans
    # `marker_calib.py`. La console joue un top audio sur le front montant de `etape` vers
    # « cue » (`CalibPage._maybe_beep`), pour une calibration MI où le moteur donne la consigne à
    # l'oreille. Recopier ici le nom de l'étape ferait sonner la console au hasard des noms
    # choisis par une mesure. Le nom de l'étape voyage dans `classe`, qui n'a pas cet effet de
    # bord ; une mesure qui aurait vraiment besoin d'un top (le contrôle alpha, dont le sujet a
    # les yeux fermés et ne peut RIEN lire) devra le demander explicitement, pas l'obtenir par
    # accident.


def _selftest():
    """La ligne du temps sur une horloge FABRIQUÉE, et le refus d'une seconde activité.

    Aucun casque, aucune attente réelle : `tick` reçoit `now`, donc une chauffe de 15 s et un
    protocole de trois minutes se jouent en quelques millisecondes.
    """
    import json

    import numpy as np

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    from core.config import DATA_DIR, empreinte_dossier
    from core.modes import registry
    from core.modes.calibration import PHASES as PHASES_CALIB
    from core.modes.calibration import PHASES_TERMINALES as TERMINALES_CALIB
    from core.modes.contract import Param

    empreinte_avant = empreinte_dossier(DATA_DIR)

    class _FausseAcq:
        fs = 250.0

    class _FauxMoteur:
        """Rend toujours une fenêtre de la bonne longueur : on teste la LIGNE DU TEMPS."""

        def __init__(self):
            self.acq = _FausseAcq()
            self.demandes = []

        def recent_window(self, seconds):
            self.demandes.append(seconds)
            return np.zeros((int(round(seconds * self.acq.fs)), 8))

    # Le patron exact d'une mesure réelle : deux préparations NON enregistrées encadrant deux
    # phases enregistrées. C'est littéralement la forme du contrôle alpha (tâche 3).
    class _MesureDEssai(MesureRuntime):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.calculs = 0            # combien de fois `_mesurer` a été APPELÉE

        def protocole(self):
            duree = float(self.params.get("duree_s", 8.0))
            return (Etape("préparation", 3.0, enregistre=False,
                          instruction="Yeux OUVERTS dans un instant"),
                    Etape("ouvert", duree, instruction="YEUX OUVERTS", rappel="immobile"),
                    Etape("préparation", 3.0, enregistre=False,
                          instruction="Yeux FERMÉS dans un instant"),
                    Etape("fermé", duree, instruction="YEUX FERMÉS", rappel="immobile"))

        def _mesurer(self, enregistre, fs):
            self.calculs += 1
            return {"n_fenetres": len(enregistre), "fs": fs,
                    "etiquettes": [lab for _f, lab in enregistre],
                    "longueurs": [len(f) for f, _lab in enregistre],
                    "verdict": "ESSAI", "honnetete": "aucun cerveau n'a été vu ici"}

    SPEC = MesureSpec(
        id="essai", label="Mesure d'essai", summary="le socle, sans mesure réelle",
        briefing=("Première ligne.", "Deuxième ligne."),
        params=(Param("duree_s", "Durée par phase", "float", unit="s", default=8.0,
                      min=1.0, max=60.0, help="Assez long pour que le spectre ait du sens."),),
        runtime_cls=_MesureDEssai)

    # === Le vocabulaire public ==============================================================
    chk(PHASES_TERMINALES is TERMINALES_CALIB,
        "les phases TERMINALES sont l'objet IMPORTÉ de `modes/calibration.py`, pas une copie — "
        "c'est celui que `console/calib_page.py` importe pour montrer l'écran de résultat")
    chk(PHASES[-2:] == PHASES_TERMINALES,
        f"…et les deux vocabulaires s'accordent : une mesure finit par les mêmes deux mots "
        f"({PHASES[-2:]})")
    chk("entrainement" not in PHASES and "mesure" in PHASES,
        f"une mesure MESURE, elle n'entraîne rien : publier « entrainement » dans son état serait "
        f"un mensonge pour un confort d'héritage ({PHASES})")
    chk(set(PHASES) - set(PHASES_CALIB) == {"mesure"}
        and set(PHASES_CALIB) - set(PHASES) == {"echauffement", "entrainement"},
        f"et l'écart aux phases d'une calibration se réduit à ça ({PHASES})")

    # === La ligne du temps NOMINALE =========================================================
    moteur = _FauxMoteur()
    rt = _MesureDEssai(SPEC, {"duree_s": 8.0}, moteur)

    chk(rt.total() == 2,
        f"l'avancement compte les étapes ENREGISTRÉES, pas les préparations ({rt.total()} sur "
        f"{len(rt._etapes)} étapes jouées)")
    chk(abs(rt.duree_estimee_s() - (15.0 + 3.0 + 8.0 + 3.0 + 8.0)) < 1e-9,
        f"la durée annoncée, elle, compte TOUT — la personne vit aussi les préparations "
        f"({rt.duree_estimee_s():.1f} s)")
    chk(rt.warmup_s == SSVEP_WARMUP_S == 15.0,
        f"la chauffe est celle du reste du produit, pas une valeur locale ({rt.warmup_s:g} s)")

    t = 100.0
    rt.tick(moteur, t)
    chk(rt.phase == "chauffe", f"on commence par la chauffe ({rt.phase})")
    chk(rt.state(now=t)["restant_s"] > 14.0,
        f"…et elle se décompte à l'écran ({rt.state(now=t)['restant_s']} s)")
    rt.tick(moteur, t + 14.9)
    chk(rt.phase == "chauffe" and not moteur.demandes,
        "pendant la chauffe, RIEN n'est prélevé : l'offset DC de l'Unicorn dérive encore, et un "
        "rapport de puissances calculé là-dedans compare deux dérives")

    t = 115.0
    for _ in range(4000):
        rt.tick(moteur, t)
        if rt.terminee:
            break
        t += 0.25

    chk(rt.phase == "fini", f"la séance se termine ({rt.phase}, problème={rt.probleme!r})")
    chk(rt.essai == 2 and rt.calculs == 1,
        f"deux fenêtres enregistrées, un seul calcul ({rt.essai}, {rt.calculs})")
    chk(len(moteur.demandes) == 2 and all(abs(s - 8.0) < 1e-9 for s in moteur.demandes),
        f"les préparations ne prélèvent RIEN, et chaque prélèvement demande la durée de SON étape "
        f"— pas celle du protocole ({moteur.demandes})")
    chk(rt.resultat and rt.resultat["etiquettes"] == ["ouvert", "fermé"],
        f"les fenêtres partent au calcul dans l'ordre, étiquetées par leur étape ({rt.resultat})")
    chk(rt.resultat and rt.resultat["longueurs"] == [2000, 2000],
        f"…et chacune fait exactement sa durée × fs ({rt.resultat['longueurs']})")

    # === Rien, absolument rien, sur le disque ================================================
    chk(rt.dossier is None,
        f"une mesure n'a AUCUN dossier d'écriture ({rt.dossier!r})")
    try:
        rt.dossier_ou_lever()
        chk(False, "…et le lui demander doit être REFUSÉ, pas retomber sur un chemin quelconque")
    except ValueError as e:
        chk("MESURE" in str(e) and "n'écrit rien" in str(e),
            f"…par un refus qui dit ce qu'est une mesure ({str(e)[:70]}…)")
    chk(empreinte_dossier(DATA_DIR) == empreinte_avant,
        "et une séance complète laisse `data/` INTACT — c'est la différence entière avec une "
        "calibration, et data/ garde son autorité unique sur les modèles")

    # === Le tampon pas encore rempli : une étape ignorée, pas une séance perdue ==============
    class _MoteurTronque(_FauxMoteur):
        def recent_window(self, seconds):
            fenetre = super().recent_window(seconds)
            return fenetre[:-1] if len(self.demandes) == 1 else fenetre

    moteur2 = _MoteurTronque()
    rt2 = _MesureDEssai(SPEC, {"duree_s": 8.0}, moteur2)
    t = 0.0
    for _ in range(4000):
        rt2.tick(moteur2, t)
        if rt2.terminee:
            break
        t += 0.25
    chk(rt2.phase == "fini" and rt2.essai == 1,
        f"une fenêtre trop courte est ignorée et DITE, la séance continue ({rt2.essai} sur "
        f"{rt2.total()})")

    # === Un calcul qui lève ne tue pas le moteur ============================================
    class _Casse(_MesureDEssai):
        def _mesurer(self, enregistre, fs):
            raise ValueError("les deux phases sont identiques")

    moteur3 = _FauxMoteur()
    rt3 = _Casse(SPEC, {"duree_s": 2.0}, moteur3)
    t = 0.0
    for _ in range(4000):
        rt3.tick(moteur3, t)
        if rt3.terminee:
            break
        t += 0.25
    chk(rt3.phase == "annule" and "identiques" in rt3.probleme and rt3.resultat is None,
        f"un calcul qui lève se solde par un refus lisible, pas par un moteur à terre "
        f"({rt3.phase}, {rt3.probleme})")

    # === L'abandon ==========================================================================
    moteur4 = _FauxMoteur()
    rt4 = _MesureDEssai(SPEC, {"duree_s": 8.0}, moteur4)
    t = 0.0
    for _ in range(120):
        rt4.tick(moteur4, t)
        t += 0.25
    chk(rt4.phase == "essais" and rt4.essai == 1,
        f"la séance tourne et a déjà prélevé ({rt4.phase}, {rt4.essai})")
    # ⚠️ Capturé MAINTENANT, pendant que la séance tourne — le contrôle du top audio, tout en bas,
    # s'en sert. Le prendre après `cancel()` ne prouverait rien : l'abandon met `etape` à "" de
    # toute façon, donc l'assertion serait vraie même si une étape en cours la remplissait.
    milieu = rt4.state(now=t)
    # 30 s de séance = 15 (chauffe) + 3 (prép.) + 8 (ouvert) + 3 (prép.) → on est dans « fermé »,
    # et UNE seule fenêtre a été prélevée. L'écran doit donc montrer la 4e consigne alors que
    # l'avancement en est à 1 sur 2 : c'est exactement la paire que les préparations rendent
    # possible, et un `total()` qui les compterait afficherait « 3 sur 4 » ici.
    chk(milieu["classe"] == "fermé" and milieu["instruction"] == "YEUX FERMÉS"
        and milieu["rappel"] == "immobile",
        f"…et l'écran montre l'étape en cours : sa consigne EN GRAND, son nom et son rappel en "
        f"dessous ({milieu['instruction']!r}, {milieu['classe']!r}, {milieu['rappel']!r})")
    chk(milieu["essai"] == 1 and milieu["total"] == 2,
        f"…pendant que l'avancement compte les FENÊTRES, pas les étapes jouées "
        f"({milieu['essai']} sur {milieu['total']}, 4e étape sur 4)")
    rt4.cancel()
    chk(rt4.terminee and rt4.phase == "annule" and rt4.resultat is None
        and rt4._enregistre == [] and rt4.engine is None and rt4.calculs == 0,
        f"l'abandon libère les fenêtres ET la référence au moteur, et ne calcule RIEN — un "
        f"contrôle alpha interrompu après « yeux ouverts » n'a pas de terme de comparaison "
        f"({rt4.phase}, {len(rt4._enregistre)} fenêtre(s), engine={rt4.engine})")
    avant = rt4.essai
    rt4.tick(moteur4, t + 500.0)
    chk(rt4.essai == avant and rt4.phase == "annule",
        "et une mesure annulée ne repart pas toute seule au tick suivant")

    # === La forme de l'instantané ===========================================================
    # `console/calib_page.py` est GÉNÉRIQUE : elle lit ces champs sans jamais les tester. Un champ
    # manquant ne lève RIEN — la page reste simplement vide.
    lus_par_la_console = {"mode_id", "phase", "etape", "classe", "instruction", "rappel",
                          "essai", "total", "restant_s", "duree_estimee_s", "resultat",
                          "probleme"}
    etat = rt.state(now=t)
    chk(set(etat) >= lus_par_la_console,
        f"l'instantané porte tout ce qu'un écran de protocole lit "
        f"({sorted(lus_par_la_console - set(etat)) or 'aucun champ manquant'})")

    # La garantie STRUCTURELLE derrière : la forme n'est pas recopiée, elle vient du parent.
    class _CalibMoteur(CalibrationRuntime):
        classes = ("A",)

        def _entrainer(self, enregistre, fs):
            return {}

    from core.modes.p300 import SPEC as SPEC_P300

    reference = _CalibMoteur(SPEC_P300, {}, None).state(now=0.0)
    chk(set(reference) == set(etat),
        f"…et c'est EXACTEMENT celui d'une calibration : `state()` n'est pas redéfinie ici, elle "
        f"est héritée ({sorted(set(reference) ^ set(etat)) or 'aucun écart'})")
    chk(etat["mode_id"] == SPEC.id and etat["label"] == SPEC.label,
        f"l'instantané se réclame de SA mesure — la page filtre dessus pour ne jamais présenter "
        f"la séance d'une autre comme la sienne ({etat['mode_id']}, {etat['label']!r})")

    try:
        json.dumps(etat)
        serialisable = True
    except (TypeError, ValueError):
        serialisable = False
    chk(serialisable, "l'instantané est sérialisable en JSON — il part dans `snapshot()`")
    chk(etat["phase"] in PHASES and rt3.phase in PHASES_TERMINALES,
        f"les phases sont celles du vocabulaire PUBLIC de ce module ({etat['phase']})")

    # ⚠️ Le piège de l'affichage : `CalibPage._maybe_beep` joue un top au front montant de `etape`
    # vers « cue ». Le nom de l'étape voyage dans `classe`, jamais dans `etape` — vérifié sur
    # `milieu`, pris PENDANT une étape (cf. sa capture plus haut), et pas sur une séance close.
    chk({etat["etape"], milieu["etape"]} == {""},
        f"`etape` reste VIDE de bout en bout : la console ne doit pas biper au hasard des noms "
        f"d'étapes choisis par une mesure ({ {etat['etape'], milieu['etape']} })")

    # === Le contrat de la sous-classe : les deux hooks sont OBLIGATOIRES =====================
    class _SansProtocole(MesureRuntime):
        def _mesurer(self, enregistre, fs):
            return {}

    try:
        _SansProtocole(SPEC, {}, _FauxMoteur())
        chk(False, "une mesure sans `protocole()` doit être refusée à la construction")
    except NotImplementedError as e:
        chk("protocole" in str(e),
            f"…en nommant ce qui manque ({str(e)[:60]}…)")

    # === LE refus d'une seconde activité, DANS LES DEUX SENS =================================
    # ⚠️ Il n'y a qu'UN casque et qu'une personne. Une calibration et une mesure qui tourneraient
    # ensemble prélèveraient dans le MÊME tampon glissant pendant que chacune affiche sa propre
    # consigne : celle qui demande « ferme les yeux » et celle qui demande « imagine ton poing »
    # obtiendraient le même signal, et les deux rendraient des chiffres plausibles et faux.
    #
    # Chaque sens est exercé DEUX fois — à la SOUMISSION (`submit`) et dans la BOUCLE
    # (`_start_mesure`, `_start_calibration`) : deux commandes soumises dans la même fenêtre de
    # sondage voient toutes les deux un moteur vierge. C'est le patron exact du refus du vol de
    # marqueurs (`server._smoke_vol_marqueurs`).
    from core.server import EngineServer

    vrais = registry.MESURES
    registry.MESURES = (SPEC,)
    srv = EngineServer(synthetic=True, modes=(), instance="selftest-mesure")
    try:
        r = srv.submit("start_mesure", id="essai")
        chk(r.get("accepted"), f"une mesure démarre sur un moteur libre ({r})")
        # ⚠️ `submit` ne fait que METTRE EN FILE (cf. sa docstring) : sans ce drain, `srv.mesure`
        # est encore None et la suite testerait un moteur vierge — c'est-à-dire rien du tout.
        srv._drain_commands()
        chk(srv.mesure is not None and not srv.mesure.terminee,
            f"…et la boucle l'applique ({srv.mesure})")

        r2 = srv.submit("start_calibration", id="mi")
        chk(not r2.get("accepted") and "mesure" in (r2.get("reason") or "").lower(),
            f"…et une CALIBRATION est alors refusée, en nommant la mesure en cours ({r2})")

        r2b = srv.submit("start_mesure", id="essai")
        chk(not r2b.get("accepted") and "mesure" in (r2b.get("reason") or "").lower(),
            f"…une SECONDE mesure aussi : deux protocoles, un seul casque ({r2b})")

        # La garde côté BOUCLE, sens 1 : c'est elle qui rattrape la course.
        srv._start_calibration("mi", {})
        chk(srv.calibration is None,
            f"sens 1, côté BOUCLE — la course (start_mesure et start_calibration soumis dans la "
            f"même fenêtre de sondage) est rattrapée : aucune calibration n'est construite "
            f"({srv.calibration})")

        # === SENS 2 : une calibration tourne, on demande une mesure ==========================
        class _CalibrationFactice:
            """Le strict nécessaire que les gardes lisent : `terminee` et `spec.label`."""

            spec = registry.get("mi")
            terminee = False

            def cancel(self):
                pass

        srv.mesure = None
        srv.calibration = _CalibrationFactice()
        r3 = srv.submit("start_mesure", id="essai")
        chk(not r3.get("accepted") and "calibration" in (r3.get("reason") or "").lower(),
            f"et RÉCIPROQUEMENT — c'est le sens qu'on oublie en croyant avoir fermé la porte "
            f"({r3})")

        srv._start_mesure("essai", {})
        chk(srv.mesure is None,
            f"sens 2, côté BOUCLE — la course symétrique est rattrapée elle aussi : aucune mesure "
            f"n'est construite ({srv.mesure})")

        # === Le contrôle qui rend les gardes FALSIFIABLES ====================================
        # Une activité TERMINÉE ne prélève plus rien : elle ne doit plus rien bloquer. Sans cette
        # ligne, un refus écrit « dès qu'une calibration existe » passerait tout ce qui précède et
        # interdirait toute mesure pour le reste de la séance.
        _CalibrationFactice.terminee = True
        r4 = srv.submit("start_mesure", id="essai")
        chk(r4.get("accepted"),
            f"une calibration TERMINÉE ne bloque plus rien — le refus porte sur « en cours », pas "
            f"sur « existe » ({r4})")

        # Et l'identifiant inconnu, qui est le premier message qu'un étudiant peut voir.
        r5 = srv.submit("start_mesure", id="bogus")
        chk(not r5.get("accepted") and "bogus" in (r5.get("reason") or ""),
            f"une mesure inconnue est refusée en la nommant ({r5.get('reason')})")

        r6 = srv.submit("cancel_mesure")
        chk(not r6.get("accepted") and "aucune mesure" in (r6.get("reason") or ""),
            f"…et annuler sans mesure en cours est refusé avec un motif ({r6.get('reason')})")
    finally:
        registry.MESURES = vrais
        # `cancel()` AVANT de lâcher le moteur : un runtime garde `self.engine`, donc `srv` se
        # référence lui-même à travers lui — le même cycle que `self.active`, et le `finally` de
        # `run()` le casse pour la même raison (cf. son long commentaire). Ce moteur-ci n'a jamais
        # tourné, donc rien de grave ne peut en sortir ; on tient quand même la discipline, parce
        # que c'est elle qui empêche le cas grave d'arriver ailleurs.
        if srv.mesure is not None:
            srv.mesure.cancel()
            srv.mesure = None
        srv.close()

    chk(empreinte_dossier(DATA_DIR) == empreinte_avant,
        "tout ce test n'a rien écrit dans `data/`")

    print(f"[mesure] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
