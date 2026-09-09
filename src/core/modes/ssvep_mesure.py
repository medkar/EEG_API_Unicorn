"""Le taux d'émission du SSVEP : **combien de fois le moteur parle, et a-t-il raison quand il parle**.

Le mode SSVEP décode en continu et publie une décision cinq fois par seconde — mais rien, dans ce
flux, ne dit s'il a RAISON : personne ne sait où le regard se pose. Cette mesure le dit, parce
qu'une fenêtre DÉSIGNE la cible à fixer (`src/stimulus/ssvep.py --guide`) et publie cette
vérité-terrain sur le flux de marqueurs. Le moteur écoute, prélève **une** fenêtre par essai,
applique **exactement sa propre règle de décision**, et rend deux chiffres :

  • le **taux d'émission** — sur combien d'essais le moteur a produit une cible plutôt que rien ;
  • la **justesse à l'émission** — quand il en produit une, à quelle fréquence est-ce la bonne.

⚠️ **Ces deux chiffres se lisent ENSEMBLE, toujours.** Mesuré sur casque le 2026-07-27 : **100 % de
justesse quand le moteur émet, mais 44 % d'émission seulement**. Le second sans le premier fait
passer un régime parfaitement normal pour une panne ; le premier sans le second fait croire à un
sans-faute. Un long silence entre deux verdicts justes EST le régime normal de ce mode.

⚠️ **Cette mesure ne change RIEN au décodage.** Elle reconstruit le chemin du mode —
`acq.occipital_window` -> `CCADecoder` calé sur le plancher de repos -> seuil `Z_MIN` -> rejet
d'artefact au-delà de `ARTIFACT_SIGMA_RATIO` × le σ du repos. Ce qui est mesuré est donc la règle
du PRODUIT, pas une variante écrite pour l'occasion. Un seuil local ici mesurerait un décodeur que
personne n'utilise, et le chiffre serait cité comme s'il décrivait le moteur.

⚠️ **UNE SEULE chose n'est PAS identique, et il faut la connaître avant de citer un taux : le σ du
rejet d'artefact ne se mesure pas sur les mêmes voies des deux côtés.** Le mode le prend sur la
fenêtre occipitale FILTRÉE, donc sur les 4 voies qu'il décode (`modes/ssvep.py::_run_step` :
`window.std(axis=0).mean()`) ; cette mesure le prend par `acq.sigma_from_block`, c'est-à-dire sur
les **8** voies. Les deux filtrent et écartent le transitoire de la même façon — la seule
différence est le jeu de voies. Conséquence : le rejet n'est pas garanti de tomber sur les mêmes
essais que celui du mode, et il est probablement plus sensible aux artefacts FRONTAUX (le
clignement, que Fz voit et qu'Oz voit peu). Le taux d'émission rendu ici est donc, sur ce point,
légèrement CONSERVATEUR par rapport à ce que le mode ferait en direct.

⚠️ **Cet écart est ANTÉRIEUR à ce fichier** : `research/ssvep_guided.py` mesurait déjà son σ par
`sigma_from_block`, et c'est sous cette règle-là que les repères du 2026-07-27 ont été obtenus.
Il est donc laissé TEL QUEL — l'aligner sur les 4 voies occipitales changerait la règle sous
laquelle 100 %/44 % ont été mesurés, et rendrait le prochain chiffre incomparable au seul dont on
dispose. C'est un constat à porter, pas un correctif à glisser dans un chantier de déménagement.

--- LES TROIS INVARIANTS DU PROTOCOLE -----------------------------------------------------------

Ils viennent de `research/ssvep_guided.py`, le monolithe (stimulus + acquisition + analyse) que ce
module et `src/stimulus/ssvep.py` remplacent. Chacun ferme une façon de se tromper en beauté.

1. **CHAUFFE AVANT TOUT.** L'Unicorn sort un offset DC énorme et DÉRIVANT pendant des dizaines de
   secondes après l'ouverture de session (10⁵ µV en rampe, mesuré le 2026-07-27). Mesurer le
   plancher de repos là-dedans revient à étalonner sur le transitoire d'un filtre — et tout le
   reste de la séance se compare ensuite à ce plancher-là. Tenu par `warmup_s`, hérité du socle.

2. **ESSAIS ENTRELACÉS ET TIRÉS AU SORT.** Un bloc contigu par cible rend « quelle cible »
   inséparable de « quand » : la dérive d'impédance, la fatigue et l'installation des électrodes se
   confondent avec l'effet cherché. **Le c-VEP a payé ce confond 76 % de débit** (cf. README).
   Tenu côté FENÊTRE (`stimulus/ssvep.py::schedule`), qui décide de l'ordre — le moteur ne fait que
   l'apprendre par les marqueurs. Ce module ne peut donc pas le défaire, et c'est voulu.

3. **UN ESSAI = UNE DÉCISION.** C'est l'invariant que ce fichier existe pour tenir, et le seul des
   trois qui puisse se perdre ICI. Les fenêtres du moteur se CHEVAUCHENT — 1,5 s glissées toutes
   les 0,2 s — donc une fixation de 3 s en contient sept ou huit. Les compter comme sept essais
   indépendants gonfle l'effectif d'un facteur ~7 et **rétrécit l'intervalle de confiance d'un
   facteur √7**, sans rien apporter : sept fenêtres qui partagent 80 % de leurs échantillons ne
   sont pas sept observations. On archive donc la fixation ENTIÈRE, et `_decision_de_l_essai` n'en
   retient qu'UNE fenêtre — **la dernière**, celle où la réponse SSVEP est la mieux établie.
   L'effectif annoncé est le nombre d'ESSAIS.

⚠️ **Ce que cette mesure ne mesure PAS** : le trajet réseau (publication LSL, horloges, deux
machines). Il est validé séparément. Ici on isole le décodage.

Autotest :
    python src/core/modes/ssvep_mesure.py
"""

import os as _os
import sys as _sys
from dataclasses import dataclass

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np  # noqa: E402

from core.cca_decoder import CCADecoder  # noqa: E402
from core.config import (ARTIFACT_SIGMA_RATIO, CALIB_FENETRE_ATTENTE_S,  # noqa: E402
                         CALIB_FENETRE_SILENCE_S, FILTER_MARGIN_S, MARKER_STREAM_DEFAULT,
                         SSVEP_GUIDE_CUE_S, SSVEP_GUIDE_FIX_S, SSVEP_GUIDE_GAP_S,
                         SSVEP_GUIDE_REPOS_S, SSVEP_GUIDE_TRIALS_PER_TARGET, WINDOW_S,
                         use_utf8_console)
from core.markers import flux_de_marqueurs_visibles  # noqa: E402
from core.modes.contract import Param  # noqa: E402
from core.modes.mesure import MesureRuntime, MesureSpec  # noqa: E402
# La cadence de décodage du MODE, importée et jamais recopiée : c'est elle qui dit combien de
# fenêtres chevauchantes une fixation contient, donc de combien l'effectif serait gonflé si on les
# comptait. Le test s'en sert pour fabriquer un essai réaliste.
from core.modes.ssvep import SSVEP_DECODE_HZ  # noqa: E402
from core.p300_decoder import epoch_from_stream  # noqa: E402

# L'étiquette des fenêtres du PLANCHER de repos. Une chaîne, là où un essai porte un `Essai` :
# `_mesurer` sépare les deux sur le TYPE, ce qui rend impossible de confondre un numéro d'essai
# avec le repos par une coïncidence d'étiquette.
REPOS = "repos"


@dataclass(frozen=True)
class Essai:
    """L'étiquette d'un essai : son rang dans la séance, et la cible que l'écran a DÉSIGNÉE.

    `numero` n'est pas décoratif : c'est la clé qui regroupe les fenêtres d'un même essai, donc
    ce qui rend l'invariant « un essai = une décision » exprimable. Sans lui, `_mesurer` ne verrait
    qu'une liste de fenêtres et n'aurait plus aucun moyen de savoir lesquelles se chevauchent.
    """

    numero: int
    cible: int


def wilson(k, n, z=1.96):
    """Intervalle de confiance de Wilson à 95 % pour une proportion. Rend (bas, haut).

    Préféré à l'intervalle normal parce qu'il reste dans [0, 1] et tient debout sur de petits
    effectifs — précisément notre cas : 36 essais, dont une moitié seulement produit une décision.

    ⚠️ **L'effectif `n` doit être un nombre d'ESSAIS**, jamais de fenêtres. C'est ici que la faute
    se paierait : la largeur de l'intervalle décroît en 1/√n, donc compter sept fenêtres
    chevauchantes par essai le rétrécit d'un facteur 2,6 et fait passer un « on ne sait pas » pour
    un « c'est mesuré ».
    """
    if n <= 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    demi = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - demi), min(1.0, centre + demi)


# --- Les repères, et la phrase qui les porte ----------------------------------------------------
# Mesurés sur casque le 2026-07-27, sur UNE personne et UNE séance. Ce sont les deux chiffres
# auxquels un résultat se compare — et ils ne se citent jamais l'un sans l'autre.
REFERENCE_JUSTESSE = 1.00      # 100 % de justesse QUAND le moteur émet (0 confusion sur 36)
REFERENCE_EMISSION = 0.44      # …mais 44 % d'essais seulement produisent une décision

HONNETETE = (
    f"Ces deux chiffres se lisent ENSEMBLE. Le 2026-07-27, sur ce casque, le moteur était juste "
    f"{REFERENCE_JUSTESSE * 100:.0f} % du temps QUAND il émettait — et il n'émettait que sur "
    f"{REFERENCE_EMISSION * 100:.0f} % des essais. Un long silence entre deux verdicts justes est "
    f"donc le régime NORMAL de ce mode, pas une panne : le seuil z est réglé pour se taire plutôt "
    f"que pour deviner.\n"
    "Ce que cette mesure ne dit PAS : rien du trajet réseau (publication LSL, horloges, deux "
    "machines), validé séparément — et rien de demain. La variance entre séances est de l'ordre "
    "d'un facteur 9 sur ce casque : un taux mesuré aujourd'hui décrit CETTE séance, avec CE "
    "montage, sur CETTE personne."
)

BRIEFING = (
    "Cette mesure répond à une seule question : quand le moteur annonce une cible, est-ce la "
    "bonne — et à quelle fréquence annonce-t-il quelque chose ?",
    "Une seconde fenêtre s'ouvre et fait clignoter quatre flèches. Elle DÉSIGNE une cible à "
    "chaque essai : fixe celle qui est entourée de bleu, jusqu'à ce que l'écran passe à autre "
    "chose.",
    f"Déroulé : stabilisation du casque, puis {SSVEP_GUIDE_REPOS_S:.0f} s de REPOS (fixe la croix "
    f"centrale, ne suis AUCUNE flèche — c'est là que le moteur mesure son fond de corrélation), "
    f"puis les essais.",
    "Reste immobile et cligne peu : une fenêtre dont l'amplitude explose est rejetée comme "
    "artefact, et un essai rejeté est un essai perdu.",
    "⚠️ Ne ferme pas la fenêtre de stimulus à la main pendant la séance : sans son marqueur de "
    "fin, aucun verdict ne sera calculé.",
)


class MesureSSVEP(MesureRuntime):
    """Le taux d'émission, mesuré sur une séance menée par la FENÊTRE.

    ⚠️ **La ligne du temps n'est PAS celle du socle**, et c'est la seule mesure dans ce cas : le
    stimulus doit être verrouillé au rafraîchissement de l'écran, donc c'est la fenêtre qui minute
    les essais et le moteur qui les SUBIT. `tick` est donc redéfinie, sur le patron exact de
    `modes/marker_calib.py` — même chauffe, mêmes deux délais d'abandon, même consommation des
    marqueurs à chaque tour, chauffe comprise.

    Ce qui reste hérité du socle, et qui est tout l'intérêt d'en hériter : `state()`, `cancel()`,
    `_terminer()`, `restant_s()`, `terminee`, le vocabulaire des phases, le refus d'écrire quoi que
    ce soit sur le disque. `src/console/mesure_page.py` est GÉNÉRIQUE : un seul champ manquant dans
    l'instantané la laisserait vide, sans lever la moindre erreur.
    """

    # Le `mode` que portent les marqueurs de la fenêtre guidée, et donc la clé sous laquelle le
    # moteur tient son curseur (`markers_murs`). C'est « ssvep » et pas l'identifiant de la mesure :
    # ces marqueurs décrivent un stimulus SSVEP, un étudiant qui lit `docs/markers.md` les cherche
    # sous ce nom-là, et le mode SSVEP lui-même ne consomme aucun marqueur — aucun vol possible.
    marker_mode_id = "ssvep"

    # Ce qu'on prélève autour de chaque `cue` : la FIXATION ENTIÈRE, plus la marge de filtre.
    # ⚠️ La fixation entière, et pas la seule fenêtre de décision, précisément pour que le choix
    # « une décision par essai » soit un CHOIX visible dans `_decision_de_l_essai` — et donc
    # testable — plutôt qu'un effet de bord de la longueur prélevée. Cette valeur dimensionne le
    # tampon du moteur (cf. `MesureRuntime.epoque_marqueur_s`).
    epoque_marqueur_s = SSVEP_GUIDE_FIX_S + FILTER_MARGIN_S

    def __init__(self, spec, params, engine, rng=None):
        super().__init__(spec, params, engine, rng=rng)
        self._annonce_recue = False      # un `calib_start` est arrivé : la fenêtre est VIVANTE
        self._essais_annonces = 0        # le champ `trials` de cette annonce ; 0 = inconnu
        self._freqs = []                 # les fréquences que l'écran AFFICHE, telles qu'annoncées
        self._refresh_hz = 0.0
        self._debut = None               # instant du premier tick (horloge de l'appelant)
        self._dernier_marqueur_s = None  # dernier tour où un marqueur est arrivé, MÊME horloge
        self._repos_fin_ts = None        # fin du plancher de repos, en horloge LSL
        self._dernier_repos_s = 0.0      # dernier prélèvement de repos (horloge de l'appelant)
        self._essais_vus = 0             # `cue` reçus, y compris ceux dont l'époque a débordé
        self._epoques_perdues = 0
        self._marqueurs_chauffe = 0
        self._chauffe_dite = False
        self._attente_fin_dite = False
        # L'acquisition du moteur, retenue à la construction. `_mesurer` en a besoin pour appliquer
        # EXACTEMENT le filtrage du mode (`occipital_window`) et sa définition du σ
        # (`sigma_from_block`) — or `cancel()` met `self.engine` à None, et une mesure abandonnée
        # puis relancée ne doit pas dépendre de l'ordre des deux.
        self._acq = getattr(engine, "acq", None)

    # --- ce que le socle attend --------------------------------------------------

    def protocole(self):
        """AUCUNE étape : la ligne du temps est tenue par la fenêtre, pas par le moteur.

        Un tuple vide plutôt qu'une `NotImplementedError` héritée : le socle exige que toute mesure
        déclare son protocole, et « je n'en mène aucun » est une réponse — la même que celle de
        `modes/marker_calib.py` pour les trois calibrations à fenêtre. Ce qui remplace les étapes
        est `tick`, redéfinie plus bas.
        """
        return ()

    def total(self):
        """Le nombre d'essais que la FENÊTRE a annoncés. 0 tant qu'elle ne s'est pas annoncée.

        Le moteur ne le calcule pas : il ne connaît ni le nombre de cibles à l'écran, ni le nombre
        d'essais par cible. Ce nombre vient du champ `trials` de `calib_start`, dans l'unité que
        `self.essai` compte — **un essai enregistré**.
        """
        return self._essais_annonces

    def duree_estimee_s(self):
        """La chauffe, plus ce que le moteur SAIT du protocole par ses constantes partagées.

        `SSVEP_GUIDE_*` vivent dans `core/config.py` justement pour ça : la fenêtre les JOUE, le
        moteur les lit pour annoncer une durée AVANT qu'on ne s'asseye. Deux copies feraient
        annoncer à l'écran une séance que la fenêtre ne tient pas.
        """
        essais = self._essais_annonces or (SSVEP_GUIDE_TRIALS_PER_TARGET * 3)
        par_essai = SSVEP_GUIDE_CUE_S + SSVEP_GUIDE_FIX_S + SSVEP_GUIDE_GAP_S
        return float(self.warmup_s) + SSVEP_GUIDE_REPOS_S + essais * par_essai

    def instruction(self):
        """Ce que la console affiche en grand. Le vrai protocole est dans l'AUTRE fenêtre, et le
        dire est le plus utile qu'on puisse faire ici : un étudiant qui cherche la consigne sur
        l'écran de la console pendant que le stimulus tourne à côté perd sa séance."""
        if self.phase == "chauffe":
            return "Le casque se stabilise — la fenêtre de stimulus prend la main dans un instant."
        if self.phase == "essais":
            if self._essais_vus == 0:
                return "REPOS : fixe la croix centrale, ne suis AUCUNE flèche."
            return "Fixe la flèche entourée de bleu, dans la fenêtre de stimulus."
        if self.phase == "mesure":
            return "Calcul du taux d'émission…"
        return ""

    def rappel(self):
        if self.phase == "essais" and self._essais_vus == 0:
            return "le moteur mesure ici son fond de corrélation : suivre une flèche le fausserait"
        if self.phase == "essais":
            return "immobile, cligne peu — une fenêtre trop agitée est rejetée comme artefact"
        return ""

    # --- la ligne du temps, menée par la fenêtre ---------------------------------

    def tick(self, engine, now):
        """Un pas. Appelée par la boucle du moteur, jamais par une interface.

        ⚠️ Les marqueurs sont consommés à CHAQUE TOUR, chauffe comprise. C'est l'APPEL qui fait
        avancer le curseur du moteur : sans lui pendant la chauffe, l'arriéré s'empile derrière un
        curseur immobile, et le premier tour de la phase « essais » avale d'un coup 15 s de
        marqueurs dont l'EEG a déjà quitté le tampon. Panne n°7 de `modes/p300.py`, à l'identique —
        et c'est le comportement PAR DÉFAUT, puisque la console lance la fenêtre au moment même où
        elle demande la mesure.
        """
        if self.terminee:
            return
        if not self._demarre:
            self._demarre = True
            self._debut = now
            self._echeance = now + self.warmup_s
            return

        phase_avant = self.phase

        # `post_s = SSVEP_GUIDE_FIX_S` : un `cue` n'est mûr que lorsque le tampon couvre la
        # fixation qu'il ouvre — c'est-à-dire quand l'époque qu'on va prélever existe vraiment.
        # Le demander plus tôt rendrait une époque tronquée, sans rien dire.
        lot = engine.markers_murs(self.marker_mode_id, post_s=SSVEP_GUIDE_FIX_S)
        for ts, marqueur in lot:
            self.encaisser(engine, ts, marqueur)
        if lot:
            self._dernier_marqueur_s = now

        if self.phase == "chauffe":
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
            self._echantillonne_le_repos(engine, now)
            self._verifie_silence(now)
            return

        if self.phase == "mesure" and phase_avant == "mesure":
            # ⚠️ `phase_avant`, et pas seulement `self.phase` : un tour APRÈS `calib_end`, jamais
            # dans le MÊME. `_terminer` bloque la boucle du moteur le temps du calcul, et la
            # console (qui sonde à 10 Hz) doit avoir pu peindre « Calcul… » au moins une fois
            # avant. Sans ce décalage, l'écran reste sur le dernier essai pendant tout le calcul :
            # exactement la tête d'un moteur figé. Même geste que `marker_calib.tick`.
            self._terminer(engine)

    def _ouvrir_les_essais(self, now):
        """Fin de la chauffe. Ce qui a été publié pendant est jeté, et dit."""
        self.phase = "essais"
        self.etape, self.classe, self._echeance = "", "", None
        self._dernier_marqueur_s = now
        self._dernier_repos_s = now
        print(f"[mesure-ssvep] chauffe terminée, {self.total()} essai(s) annoncé(s) par la "
              f"fenêtre — enregistrement en cours")

    def _echantillonne_le_repos(self, engine, now):
        """Le PLANCHER de repos, échantillonné à la cadence du mode pendant la phase « repos ».

        ⚠️ Ce n'est pas une commodité : le SSVEP décide sur z = (ρ − μ) / σ, et μ/σ sont mesurés
        ICI, cible par cible. Chaque fréquence a un fond de corrélation DIFFÉRENT au repos selon sa
        proximité au pic alpha du jour ; sans ce plancher, il n'y a pas de décision à mesurer.

        ⚠️ La borne de fin est lue dans l'horloge des MARQUEURS (`recent_ts`), pas dans `now` :
        le marqueur `repos` n'est libéré qu'une fois mûr, donc `SSVEP_GUIDE_FIX_S` après avoir été
        publié. Compter la durée du repos à partir de sa RÉCEPTION ferait mordre l'échantillonnage
        sur les premières secondes du premier essai — le moteur mesurerait alors son « fond » sur
        une fixation, et le seuil de cette cible-là deviendrait inatteignable.
        """
        if self._repos_fin_ts is None or self._essais_vus:
            return
        if not len(engine.recent_ts) or float(engine.recent_ts[-1]) >= self._repos_fin_ts:
            return
        if now - self._dernier_repos_s < 1.0 / SSVEP_DECODE_HZ:
            return
        self._dernier_repos_s = now
        bloc = engine.recent_window(self._duree_bloc_s())
        attendu = int(round(self._duree_bloc_s() * engine.acq.fs))
        if bloc is not None and len(bloc) >= attendu:
            self._enregistre.append((bloc, REPOS))

    def _duree_bloc_s(self):
        """La longueur d'un bloc de repos : la fenêtre de décision PLUS la marge de filtre.

        Lue sur l'acquisition (`window_n + margin_n`) et non recalculée depuis `WINDOW_S` : c'est
        exactement la longueur qu'`occipital_window` exige, et deux arithmétiques pour le même
        nombre finiraient par diverger d'un échantillon — donc par rendre None en silence.
        """
        acq = self._acq
        return float(acq.window_n + acq.margin_n) / float(acq.fs)

    def _verifie_silence(self, now):
        """Abandonne si la fenêtre s'est tue — la 2e des trois causes. Jumelle de `marker_calib`.

        La condition n'est PAS « plus de marqueur » seule : elle est « plus de marqueur ALORS QUE
        la fenêtre en annonçait davantage ». Une séance dont tous les essais annoncés sont arrivés
        et dont seul le `calib_end` manque n'est pas une fenêtre morte : c'est une séance complète
        dont le dernier marqueur s'est perdu, et la jeter détruirait quatre minutes de signal bon.
        """
        if self._dernier_marqueur_s is None:
            return
        silence = now - self._dernier_marqueur_s
        if silence <= CALIB_FENETRE_SILENCE_S:
            return
        if self._essais_annonces > 0 and self.essai >= self._essais_annonces:
            if not self._attente_fin_dite:
                self._attente_fin_dite = True
                print(f"[mesure-ssvep] les {self.essai} essais annoncés sont arrivés, mais aucun "
                      f"« calib_end » depuis {silence:.0f} s : la séance ATTEND. Si la fenêtre est "
                      f"morte, « Abandonner » dans la console — aucun verdict ne sera calculé.")
            return
        self._abandonne(
            f"aucun marqueur depuis {silence:.0f} s (> {CALIB_FENETRE_SILENCE_S:.0f} s) : la "
            f"fenêtre de stimulus s'est arrêtée en pleine séance. {self.essai} essai(s) "
            f"enregistré(s) sur les {self._essais_annonces or '?'} annoncés — aucun verdict n'est "
            f"calculé, un taux sur une séance tronquée serait indiscernable d'un taux complet")

    def _abandonne(self, raison):
        """Jette la séance en le DISANT, par le MÊME geste que l'abandon depuis la console."""
        print(f"[mesure-ssvep] mesure ABANDONNÉE : {raison}")
        self.cancel()
        # APRÈS `cancel()` : lui seul décide de la phase, et il ne pose aucun `probleme` (l'abandon
        # depuis la console n'en a pas). C'est ici qu'on ajoute la raison, que la console affiche.
        self.probleme = raison

    # --- les marqueurs -----------------------------------------------------------

    def encaisser(self, engine, ts, marqueur):
        """Un marqueur, un seul. Le point d'entrée unique de tout ce qui vient de la fenêtre.

        Séparé de `tick` exprès : c'est ce qui permet de le nourrir marqueur par marqueur dans un
        test, sans faux moteur à file, et de raisonner sur UN cas à la fois.
        """
        if self.terminee or not self._demarre:
            return
        event = marqueur.get("event")

        # L'annonce est retenue MÊME pendant la chauffe : c'est elle qui dit que la fenêtre est
        # vivante, et le délai d'absence court depuis un instant où elle n'existait pas encore. La
        # refuser pendant la chauffe obligerait la fenêtre à deviner la durée de celle-ci pour ne
        # pas être déclarée absente.
        if event == "calib_start":
            self._encaisse_annonce(marqueur)
            return

        if self.phase == "chauffe":
            self._marqueurs_chauffe += 1
            if not self._chauffe_dite:
                self._chauffe_dite = True
                print(f"[mesure-ssvep] marqueur(s) reçus pendant la CHAUFFE : jetés — l'offset DC "
                      f"du casque dérive encore ({self.warmup_s:.0f} s). Un plancher de repos "
                      f"mesuré là-dedans étalonnerait la séance sur le transitoire d'un filtre.")
            return

        if self.phase != "essais":
            # « mesure » ou phase terminale : la fenêtre parle encore alors que la séance est
            # close. Rien à faire, et surtout pas d'erreur — c'est le cas normal d'une fenêtre qui
            # se ferme un tour après son `calib_end`.
            return

        if event == "repos":
            self._repos_fin_ts = float(ts) + SSVEP_GUIDE_REPOS_S
            return

        if event == "calib_end":
            self.phase = "mesure"
            self.etape, self.classe, self._echeance = "", "", None
            print(f"[mesure-ssvep] « calib_end » reçu : {self.essai} essai(s) sur les "
                  f"{self._essais_annonces or '?'} annoncés — calcul du taux d'émission")
            return

        if event != "cue":
            # Un événement que ce protocole ne connaît pas est ignoré, pas refusé : le protocole
            # s'enrichira, et un moteur qui casserait au premier ajout serait inutilisable.
            return

        cible = marqueur.get("target")
        if isinstance(cible, bool) or not isinstance(cible, int):
            # `bool` HÉRITE de `int` en Python : `True` passerait pour la cible 1. Même piège que
            # `target` dans `modes/p300.py`.
            print(f"[mesure-ssvep] `cue` sans cible lisible ({cible!r}) : essai ignoré")
            return
        self._essais_vus += 1
        self.classe = f"essai {self._essais_vus}"

        # ⚠️ L'ancrage. L'époque se termine `SSVEP_GUIDE_FIX_S` APRÈS le `cue`, c'est-à-dire à la
        # FIN de la fixation — la fenêtre publie ce marqueur au premier flip de celle-ci. Un
        # ancrage sur le marqueur lui-même prélèverait la seconde de saccade qui le précède, où
        # aucune réponse SSVEP n'est encore établie : le taux s'effondrerait sans qu'une seule
        # exception ne soit levée.
        epoque = epoch_from_stream(engine.recent, engine.recent_ts,
                                   float(ts) + SSVEP_GUIDE_FIX_S, engine.acq.fs,
                                   pre_s=self.epoque_marqueur_s, post_s=0.0)
        if epoque is None:
            self._epoques_perdues += 1
            print(f"[mesure-ssvep] essai {self._essais_vus} ignoré : le marqueur était mûr mais "
                  f"son EEG avait déjà quitté le tampon du moteur")
            return
        self._enregistre.append((epoque, Essai(self._essais_vus, int(cible))))
        self.essai += 1

    def _encaisse_annonce(self, marqueur):
        """`calib_start` : la fenêtre est vivante, voici ses essais ET ses fréquences."""
        trials = marqueur.get("trials")
        if isinstance(trials, bool) or not isinstance(trials, (int, float)):
            print(f"[mesure-ssvep] « calib_start » sans nombre d'essais lisible ({trials!r}) : "
                  f"l'avancement ne pourra pas s'afficher, et un silence en cours de séance sera "
                  f"traité comme une fenêtre morte faute de pouvoir prouver qu'elle a fini")
            self._essais_annonces = 0
        else:
            self._essais_annonces = max(0, int(trials))
        # ⚠️ LES FRÉQUENCES VIENNENT DE L'ÉCRAN, jamais des réglages du mode. La fenêtre les déduit
        # du rafraîchissement qu'elle MESURE : sur un écran 120 Hz elle n'affichera pas celles d'un
        # 60 Hz. Un moteur qui garderait les siennes corrélerait contre des sinusoïdes que personne
        # ne montre, et rendrait un taux nul en accusant le montage.
        freqs = marqueur.get("freqs")
        if isinstance(freqs, (list, tuple)) and freqs:
            self._freqs = [float(f) for f in freqs]
        self._refresh_hz = float(marqueur.get("refresh_hz") or 0.0)
        if self._annonce_recue:
            print(f"[mesure-ssvep] ⚠️ second « calib_start » sans « calib_end » : les "
                  f"{self.essai} essai(s) déjà enregistrés RESTENT dans le calcul. Si la fenêtre a "
                  f"redémarré, abandonne et recommence la mesure.")
        self._annonce_recue = True

    # --- le calcul ---------------------------------------------------------------

    def _decision_de_l_essai(self, epoque):
        """**LA fenêtre de décision d'un essai : la DERNIÈRE de la fixation. Une seule.**

        ⚠️ C'est ici que vit l'invariant n°3, et c'est la seule ligne de ce fichier qu'on peut
        « améliorer » en cassant tout. L'époque reçue couvre la fixation ENTIÈRE : à 3 s de
        fixation et une fenêtre de 1,5 s glissée toutes les 0,2 s, elle contient sept ou huit
        fenêtres de décision valides. Les rendre TOUTES est tentant — « plus de données, intervalle
        plus serré » — et c'est faux : elles partagent 80 % de leurs échantillons, donc elles ne
        sont pas sept observations. L'effectif serait multiplié par ~7 et l'intervalle de confiance
        divisé par √7 ≈ 2,6, sans qu'aucun test de ce dépôt ne rougisse — sauf celui-ci.

        La DERNIÈRE, et pas la première ni la moyenne : la réponse SSVEP met environ une seconde à
        s'établir après la saccade, donc les premières fenêtres de la fixation contiennent une
        montée, pas un régime établi.
        """
        acq = self._acq
        besoin = acq.window_n + acq.margin_n
        return np.asarray(epoque, dtype=float)[-besoin:]

    def _mesurer(self, enregistre, fs):
        """L'adaptateur entre les MARQUEURS et le calcul : il groupe, choisit, puis délègue.

        Tout ce qui est décodage vit dans `rejouer`, partagé avec le banc d'essai. Ici il ne reste
        que ce qui appartient à une séance en direct : séparer le repos des essais, et appliquer
        l'invariant n°3.
        """
        acq = self._acq
        if acq is None:
            raise ValueError("aucune acquisition : la mesure ne peut pas reproduire le filtrage "
                             "du mode, donc elle ne mesurerait pas la règle du produit")
        if not self._freqs:
            raise ValueError(
                "la fenêtre de stimulus n'a annoncé aucune fréquence dans son « calib_start » : "
                "le moteur ne sait pas contre quoi corréler. Les fréquences viennent de l'ÉCRAN — "
                "il les déduit du rafraîchissement qu'il mesure — et les deviner ici reviendrait "
                "à mesurer un décodeur que personne n'utilise.")

        repos = [f for f, lab in enregistre if lab == REPOS]
        etiquetes = [(lab, f) for f, lab in enregistre if isinstance(lab, Essai)]

        # --- UNE décision par essai -----------------------------------------------------------
        # ⚠️ Le regroupement par `numero` d'abord : deux fenêtres du même essai ne sont pas deux
        # observations. C'est ce regroupement, et le `blocs[-1]` qui le suit, qui rendent
        # l'invariant EXPRIMABLE — et donc testable (cf. `_selftest`).
        par_essai = {}
        for lab, bloc in etiquetes:
            par_essai.setdefault(lab.numero, (lab.cible, []))[1].append(bloc)
        essais = [(self._decision_de_l_essai(blocs[-1]), cible)
                  for cible, blocs in (par_essai[n] for n in sorted(par_essai))]

        resultat = rejouer(essais, repos, self._freqs, fs, acq=acq)
        resultat["refresh_hz"] = self._refresh_hz
        return resultat


# --- Le calcul, PARTAGÉ avec le banc d'essai ----------------------------------------------------

def acquisition_de_reference():
    """Une `UnicornAcquisition` JAMAIS démarrée : on n'emprunte que ses filtres et sa géométrie.

    ⚠️ Elle n'ouvre aucune session — `start()` n'est jamais appelée — et ne touche donc à aucun
    casque. Ce qu'on lui prend est `occipital_window` et `sigma_from_block`, c'est-à-dire
    EXACTEMENT le chemin que le mode SSVEP emprunte en direct. Les rebâtir ailleurs créerait un
    second filtrage, qui coïnciderait le jour de son écriture et divergerait ensuite en silence —
    et c'est la seule chose qui rendrait ce module inutile, puisqu'il existe pour mesurer la règle
    du PRODUIT. C'est déjà le geste que faisait `research/ssvep_guided.analyze` ; il vit ici
    désormais, du côté du moteur, pour que le banc d'essai n'ait plus à connaître l'acquisition.

    ⚠️ **Publique, et c'est le point.** `src/research/` n'a plus le droit d'importer
    `core.acquisition` (règle vérifiée par `python src/core/server.py --smoke`), or ses analyses
    hors ligne doivent filtrer leurs fenêtres archivées EXACTEMENT comme le moteur filtre les
    siennes — sinon leurs chiffres cessent de décrire le produit. C'est ce point d'entrée-ci qui
    leur donne le bon filtrage sans leur donner le casque : `ssvep_analyze.py` s'en sert depuis le
    2026-09-09, `rejouer` et `longueur_bloc_attendue` sont publiques pour la même raison.

    ⚠️ Neuve à chaque appel, et NON mise en cache : un `BoardShim` gardé jusqu'à la fermeture de
    l'interpréteur y lève dans son `__del__` (« sys.meta_path is None »), et un étudiant lit ce
    traceback comme une panne. La construction ne fait que deux appels natifs de lecture.
    """
    from core.acquisition import UnicornAcquisition

    return UnicornAcquisition(synthetic=True)


def longueur_bloc_attendue(acq=None):
    """Le nombre d'échantillons qu'une fenêtre de décision doit porter : fenêtre PLUS marge.

    Publique pour que le banc d'essai puisse REFUSER un enregistrement pris sous d'autres
    constantes (`WINDOW_S`, `FILTER_MARGIN_S`) au lieu d'en tirer un taux. Le rejeu ne
    reproduirait alors plus la règle du moteur, et rien ne le dirait : `occipital_window` rendrait
    simplement None, chaque essai compterait comme « aucune cible », et le taux serait de 0 % —
    lu comme une panne de casque plutôt que comme un désaccord de réglages.
    """
    acq = acq or acquisition_de_reference()
    return int(acq.window_n + acq.margin_n)


def rejouer(essais, repos, freqs, fs, acq=None):
    """**La règle du moteur, rejouée sur des fenêtres — une décision par essai.** Rend le verdict.

    `essais` : `[(fenêtre BRUTE (n, 8), indice de la cible fixée), ...]`, **une par essai**.
    `repos`  : `[fenêtre BRUTE (n, 8), ...]`, les fenêtres du plancher.
    `freqs`  : les fréquences AFFICHÉES, dans l'ordre des indices de cible.

    ⚠️ Cette fonction est le SEUL chemin de décodage de la mesure, et elle est publique pour que le
    banc d'essai (`src/research/ssvep_guided.py`) rejoue un enregistrement archivé **par le même
    code**, avec d'autres réglages, sans le réécrire. Une seconde écriture serait un second
    décodeur : les deux s'accorderaient le jour de leur écriture, puis l'un des deux serait corrigé.

    ⚠️ Elle attend **une fenêtre par essai**, déjà choisie. Le choix (la dernière de la fixation)
    appartient à l'appelant, et c'est délibéré : c'est là qu'il est visible et testable.
    """
    acq = acq or acquisition_de_reference()
    freqs = [float(f) for f in freqs]
    if not freqs:
        raise ValueError("aucune fréquence : il n'y a rien contre quoi corréler")
    if len(essais) < 6:
        raise ValueError(
            f"{len(essais)} essai(s) : il n'y a pas de quoi conclure. Un taux calculé sur si peu "
            f"aurait un intervalle de confiance plus large que l'échelle elle-même, et serait "
            f"cité comme s'il disait quelque chose.")

    # --- Le plancher de repos, EXACTEMENT comme le mode le mesure -----------------------------
    decodeur = CCADecoder(freqs, fs=float(fs))
    fenetres_repos = [acq.occipital_window(b) for b in repos]
    scores_repos = [decodeur.scores(w) for w in fenetres_repos if w is not None]
    if not decodeur.fit_baseline(scores_repos):
        raise ValueError(
            f"plancher de repos impossible : {len(scores_repos)} fenêtre(s) de repos "
            f"exploitables. Le SSVEP décide sur z = (ρ − μ) / σ, mesurés cible par cible "
            f"pendant le repos ; sans lui il n'y a aucune décision à mesurer. La phase de "
            f"repos a-t-elle été jouée, ou la fenêtre a-t-elle été lancée trop tard ?")

    # Référence d'amplitude du rejet d'artefact : la MÉDIANE DU REPOS, comme dans le mode. La
    # prendre sur les essais eux-mêmes serait circulaire — les fenêtres à juger tireraient le
    # seuil vers le haut, et un essai bruité passerait pour normal.
    #
    # ⚠️ `sigma_from_block` travaille sur les **8** voies, là où le mode mesure son σ sur la
    # fenêtre occipitale filtrée (4 voies) — cf. l'avertissement en tête de module. Le seuil reste
    # cohérent avec lui-même (numérateur et dénominateur sortent du MÊME estimateur), mais il ne
    # rejette pas forcément les mêmes essais que le mode. Hérité de `research/ssvep_guided.py`, et
    # laissé tel quel : c'est la règle sous laquelle les repères du 2026-07-27 ont été obtenus.
    sigmas_repos = [acq.sigma_from_block(b) for b in repos]
    sigmas_repos = [float(np.mean(s)) for s in sigmas_repos if s is not None]
    sigma_ref = float(np.median(sigmas_repos)) if sigmas_repos else None

    decisions, artefacts = [], 0
    for fenetre_brute, cible in essais:
        sd = acq.sigma_from_block(fenetre_brute)
        if sigma_ref and sd is not None and float(np.mean(sd)) > ARTIFACT_SIGMA_RATIO * sigma_ref:
            decisions.append((cible, None))   # le mode publierait « aucune cible »
            artefacts += 1
            continue
        fenetre = acq.occipital_window(fenetre_brute)
        if fenetre is None:
            decisions.append((cible, None))
            continue
        freq, _scores = decodeur.classify(fenetre)
        decisions.append((cible, None if freq is None else freqs.index(freq)))

    n_essais = len(decisions)
    emis = [(cible, decide) for cible, decide in decisions if decide is not None]
    n_emis = len(emis)
    n_justes = sum(1 for cible, decide in emis if decide == cible)
    taux_emission = n_emis / n_essais
    justesse = (n_justes / n_emis) if n_emis else 0.0
    # ⚠️ L'intervalle porte sur la JUSTESSE À L'ÉMISSION, et son effectif est `n_emis` — un nombre
    # d'ESSAIS ayant produit une décision, jamais un nombre de fenêtres.
    ic_bas, ic_haut = wilson(n_justes, n_emis)

    return {
        "n_essais": int(n_essais),
        "n_emis": int(n_emis),
        "n_justes": int(n_justes),
        "n_artefacts": int(artefacts),
        "n_cibles": len(freqs),
        "taux_emission": round(float(taux_emission), 3),
        "justesse_emission": round(float(justesse), 3),
        "ic_bas": round(float(ic_bas), 3),
        "ic_haut": round(float(ic_haut), 3),
        "hasard": round(1.0 / len(freqs), 3),
        "freqs_hz": [round(f, 3) for f in freqs],
        "refresh_hz": 0.0,
        "fenetres_repos": len(scores_repos),
        "decisions": [(int(c), None if d is None else int(d)) for c, d in decisions],
        "verdict": verdict(len(freqs), n_essais, n_emis, n_justes, taux_emission, justesse,
                           ic_bas, ic_haut, artefacts),
        "honnetete": HONNETETE,
    }


def verdict(n_cibles, n_essais, n_emis, n_justes, taux, justesse, ic_bas, ic_haut, artefacts):
    """LA phrase. Les DEUX chiffres, toujours ensemble, et l'effectif qui les porte."""
    hasard = 1.0 / n_cibles
    phrase = (
        f"Sur {n_essais} ESSAIS (une décision par essai, jamais une par fenêtre), le moteur a "
        f"annoncé une cible {n_emis} fois — soit {taux * 100:.0f} % d'émission — et il avait "
        f"raison {n_justes} fois sur {n_emis}, soit {justesse * 100:.0f} % "
        f"[IC95 {ic_bas * 100:.0f} ; {ic_haut * 100:.0f}] pour un hasard à "
        f"{hasard * 100:.0f} %. ")
    if artefacts:
        phrase += (f"{artefacts} essai(s) rejeté(s) comme artefact (amplitude > "
                   f"{ARTIFACT_SIGMA_RATIO:g}× le repos) — ils comptent comme « aucune "
                   f"cible ». ")
    if n_emis == 0:
        return (phrase + "Le moteur n'a RIEN émis : ce n'est pas un mauvais score, c'est "
                         "l'absence de score. Le plancher de repos est probablement trop "
                         "dispersé pour que le seuil z soit atteignable — contact des "
                         "électrodes occipitales, ou repos refait immobile.")
    if ic_bas <= hasard:
        return (phrase + f"L'intervalle de confiance CONTIENT le hasard : à cet effectif, cette "
                         f"séance ne permet pas de conclure que le décodage marche. Ce n'est pas "
                         f"la preuve du contraire — c'est un « on ne sait pas ». Rallonge la "
                         f"séance, ou reprends le montage.")
    return (phrase + f"Le décodage marche sur CETTE séance : l'intervalle est au-dessus du "
                     f"hasard. À comparer aux repères du 2026-07-27 — "
                     f"{REFERENCE_JUSTESSE * 100:.0f} % de justesse à l'émission pour "
                     f"{REFERENCE_EMISSION * 100:.0f} % d'émission.")


SPEC = MesureSpec(
    id="ssvep_taux",
    label="Taux d'émission SSVEP",
    summary="Quand le moteur annonce une cible, est-ce la bonne — et à quelle fréquence "
            "annonce-t-il quelque chose ? Une fenêtre désigne la cible, le moteur mesure.",
    briefing=BRIEFING,
    params=(
        Param(key="stream_in", label="Flux de marqueurs", kind="choice",
              choices_fn=flux_de_marqueurs_visibles, default=MARKER_STREAM_DEFAULT,
              help="Le nom du flux LSL sur lequel la fenêtre guidée publie la cible désignée. La "
                   "console lance cette fenêtre elle-même sur le flux par défaut : ne change ce "
                   "réglage que si tu mènes le protocole depuis ta propre application."),
    ),
    runtime_cls=MesureSSVEP,
    # Pas une BARRIÈRE : c'est un chiffre à lire, pas un feu rouge. Le contrôle alpha, lui, arrête
    # la séance — sans alpha, plus rien ne veut dire quoi que ce soit. Un taux d'émission bas ne
    # dit rien de tel : à 44 % d'émission, le mode est dans son régime NORMAL.
    barriere=False,
    stimulus_id="ssvep",
)


def _selftest():
    """LE test de ce module : **un essai = une décision**, et il doit rougir si on compte les
    fenêtres.

    Aucun casque, aucune attente réelle : `tick` reçoit `now`, et le tampon EEG est fabriqué mais
    HORODATÉ, comme celui du vrai moteur.
    """
    import json

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    from core.acquisition import UnicornAcquisition
    from core.config import DATA_DIR, empreinte_dossier
    from core.modes import registry
    from core.modes.calibration import PHASES_TERMINALES
    from core.modes.mesure import PHASES

    empreinte_avant = empreinte_dossier(DATA_DIR)

    # Une acquisition JAMAIS démarrée : on ne veut que ses filtres et sa géométrie de fenêtre —
    # exactement ce que faisait `research/ssvep_guided.analyze`.
    acq = UnicornAcquisition(synthetic=True)
    FS = float(acq.fs)
    BESOIN = acq.window_n + acq.margin_n              # 625 échantillons = 2,5 s
    FREQS = [15.0, 20.0, 60.0 / 7.0]

    def _bruit(rng, n, sigma=8.0):
        return rng.normal(0.0, sigma, (n, 8))

    def _ssvep(rng, n, f_hz, gain=4.0, sigma=8.0):
        """Du bruit, plus une sinusoïde sur les seules voies occipitales. On CONNAÎT la réponse."""
        x = _bruit(rng, n, sigma)
        t = np.arange(n) / FS
        onde = gain * np.sin(2 * np.pi * f_hz * t)
        for c in (4, 5, 6, 7):
            x[:, c] += onde
        return x

    # === LE TEST : l'effectif est le nombre d'ESSAIS ==========================================
    def _mesurer_sur_essais(n_essais=24, fenetres_par_essai=7, gain=4.0, sur_trois=2, graine=0):
        """Joue `_mesurer` sur `n_essais` essais, chacun assez LONG pour contenir
        `fenetres_par_essai` fenêtres de décision chevauchantes.

        ⚠️ C'est la situation RÉELLE, pas une construction de test : la fixation dure 3 s et le
        moteur décode toutes les 0,2 s, donc chaque essai contient bel et bien sept ou huit
        fenêtres valides. La seule question est combien on en COMPTE.

        `sur_trois` : combien d'essais sur trois portent réellement un SSVEP. Les autres sont du
        bruit — l'étudiant a cligné, regardé ailleurs, ou la réponse n'est pas montée. C'est le
        régime NORMAL de ce mode (44 % d'émission le 2026-07-27), et le prendre comme cas de test
        plutôt qu'un sans-faute est ce qui donne un intervalle de confiance de taille réaliste :
        à 24 essais tous justes, l'intervalle est le plus ÉTROIT qu'il puisse être, donc le cas le
        moins représentatif de ce qu'on mesure vraiment.
        """
        rng = np.random.default_rng(graine)
        pas = int(round(FS / SSVEP_DECODE_HZ))                     # 50 échantillons = 0,2 s
        longueur = BESOIN + (fenetres_par_essai - 1) * pas
        # ⚠️ Le signal est fabriqué à une longueur FIXE, puis TRONQUÉ PAR LA FIN. C'est ce qui rend
        # la comparaison entre deux `fenetres_par_essai` exacte : la dernière fenêtre — la seule
        # que la mesure doit retenir — est alors rigoureusement la même. Générer deux longueurs
        # différentes tirerait deux bruits différents, et l'écart observé ne dirait plus si c'est
        # l'effectif qui a bougé ou le tirage.
        maximum = BESOIN + 20 * pas
        rt = MesureSSVEP(SPEC, {}, _FauxMoteur())
        rt._freqs = list(FREQS)
        enregistre = [(_bruit(rng, BESOIN), REPOS) for _ in range(40)]
        for i in range(1, n_essais + 1):
            cible = (i - 1) % len(FREQS)
            porte_un_ssvep = (i % 3) < sur_trois
            bloc = (_ssvep(rng, maximum, FREQS[cible], gain=gain) if porte_un_ssvep
                    else _bruit(rng, maximum))
            enregistre.append((bloc[-longueur:], Essai(i, cible)))
        return rt._mesurer(enregistre, FS), longueur, pas

    class _FausseAcq:
        fs = FS

    class _FauxMoteur:
        """Le strict nécessaire : l'acquisition (pour les filtres) et un tampon horodaté."""

        def __init__(self, secondes=30.0, t0=1000.0, graine=0):
            self.acq = acq
            self.t0 = t0
            self.recent_ts = np.arange(t0, t0 + secondes, 1.0 / FS)
            rng = np.random.default_rng(graine)
            self.recent = rng.normal(0.0, 8.0, (len(self.recent_ts), 8))
            self._lots = []

            def _rw(seconds):
                n = max(1, int(round(seconds * FS)))
                return np.array(self.recent[-n:], dtype=float, copy=True)

            self.recent_window = _rw

        def file(self, lot):
            self._lots.append(list(lot))

        def markers_murs(self, mode_id, post_s):
            return self._lots.pop(0) if self._lots else []

    res, longueur, pas = _mesurer_sur_essais(n_essais=24, fenetres_par_essai=7)
    fenetres_dispo = (longueur - BESOIN) // pas + 1
    chk(fenetres_dispo == 7,
        f"chaque essai contient bien {fenetres_dispo} fenêtres de décision chevauchantes — c'est "
        f"la situation réelle d'une fixation de {SSVEP_GUIDE_FIX_S:g} s décodée à "
        f"{SSVEP_DECODE_HZ:g} Hz, pas une construction de test")
    chk(res["n_essais"] == 24,
        f"l'effectif annoncé est le nombre d'ESSAIS ({res['n_essais']}), jamais celui des fenêtres "
        f"({24 * fenetres_dispo} ici) — les fenêtres se chevauchent, les compter gonfle "
        f"l'effectif d'un facteur ~{fenetres_dispo} et rétrécit l'intervalle de confiance d'autant")
    chk(res["n_emis"] <= res["n_essais"],
        f"…et le nombre d'émissions ne peut pas dépasser le nombre d'essais "
        f"({res['n_emis']} sur {res['n_essais']})")
    chk(res["ic_haut"] - res["ic_bas"] > 0.15,
        f"…et l'intervalle est LARGE comme il doit l'être à cet effectif "
        f"([{res['ic_bas']:.2f} ; {res['ic_haut']:.2f}], largeur "
        f"{res['ic_haut'] - res['ic_bas']:.2f})")
    # LE chiffre que la faute ferait gagner, calculé sur les mêmes proportions : si l'on comptait
    # les fenêtres, le même taux serait annoncé avec un intervalle 2,6 fois plus serré. C'est
    # exactement ce qu'on refuse — et sans cette ligne, « largeur > 0,15 » pourrait passer pour une
    # exigence arbitraire plutôt que pour la conséquence d'un effectif honnête.
    gonfle = wilson(res["n_justes"] * fenetres_dispo, res["n_emis"] * fenetres_dispo)
    chk((res["ic_haut"] - res["ic_bas"]) > 2.0 * (gonfle[1] - gonfle[0]),
        f"…et compter les fenêtres l'aurait rétréci d'un facteur ~√{fenetres_dispo} : "
        f"[{gonfle[0]:.2f} ; {gonfle[1]:.2f}] au lieu de "
        f"[{res['ic_bas']:.2f} ; {res['ic_haut']:.2f}] — le MÊME taux annoncé avec une précision "
        f"qu'aucune observation supplémentaire ne justifie")
    chk("44" in res["honnetete"] and "100" in res["honnetete"],
        "la phrase d'honnêteté porte les DEUX repères — 100 % de justesse à l'émission, mais "
        "44 % d'émission : le second sans le premier fait passer un silence normal pour une panne")
    chk("100" in res["honnetete"].split("Ce que cette mesure ne dit PAS")[0]
        and "44" in res["honnetete"].split("Ce que cette mesure ne dit PAS")[0],
        "…et les deux dans la MÊME phrase, pas l'un en tête et l'autre en note de bas de page")

    # Le contrôle qui rend l'assertion précédente FALSIFIABLE : le même calcul sur des essais deux
    # fois plus longs (donc deux fois plus de fenêtres) doit rendre EXACTEMENT le même effectif.
    res_long, longueur2, _pas = _mesurer_sur_essais(n_essais=24, fenetres_par_essai=14)
    chk(res_long["n_essais"] == res["n_essais"] == 24,
        f"doubler la longueur de chaque fixation ne change PAS l'effectif ({res_long['n_essais']} "
        f"contre {res['n_essais']}) : c'est la définition même d'« un essai = une décision »")
    chk(res_long["ic_haut"] - res_long["ic_bas"] == res["ic_haut"] - res["ic_bas"],
        f"…ni la largeur de l'intervalle ([{res_long['ic_bas']:.2f} ; {res_long['ic_haut']:.2f}]) "
        f"— sinon un protocole plus long ferait « gagner » de la précision sans une observation "
        f"de plus")

    # Et le contrôle de sens : à 48 essais, l'intervalle doit RÉTRÉCIR. Sans lui, un `_mesurer`
    # qui rendrait une largeur constante passerait les deux assertions ci-dessus.
    res48, _l, _p = _mesurer_sur_essais(n_essais=48, fenetres_par_essai=7)
    chk(res48["n_essais"] == 48
        and (res48["ic_haut"] - res48["ic_bas"]) < (res["ic_haut"] - res["ic_bas"]),
        f"doubler le nombre d'ESSAIS, lui, rétrécit bien l'intervalle "
        f"({res48['ic_haut'] - res48['ic_bas']:.3f} à n=48 contre "
        f"{res['ic_haut'] - res['ic_bas']:.3f} à n=24)")

    # === La règle mesurée est celle du MODE ===================================================
    # Sur un SSVEP synthétique FORT, le moteur doit émettre et avoir raison ; sur du bruit pur, il
    # doit se TAIRE plutôt que deviner. Les deux ensemble prouvent que le seuil z est bien appliqué.
    fort, _l, _p = _mesurer_sur_essais(n_essais=24, fenetres_par_essai=7, gain=6.0, sur_trois=3)
    chk(fort["n_emis"] > 0 and fort["justesse_emission"] > 0.8,
        f"sur un SSVEP synthétique franc, le moteur émet et a raison ({fort['n_emis']} émissions, "
        f"{fort['justesse_emission'] * 100:.0f} % justes)")

    rng = np.random.default_rng(7)
    rt_bruit = MesureSSVEP(SPEC, {}, _FauxMoteur())
    rt_bruit._freqs = list(FREQS)
    enregistre_bruit = [(_bruit(rng, BESOIN), REPOS) for _ in range(40)]
    pas = int(round(FS / SSVEP_DECODE_HZ))
    for i in range(1, 25):
        enregistre_bruit.append((_bruit(rng, BESOIN + 6 * pas), Essai(i, (i - 1) % 3)))
    plat = rt_bruit._mesurer(enregistre_bruit, FS)
    chk(plat["taux_emission"] < 0.3,
        f"sur du bruit pur, le moteur se TAIT plutôt que de deviner ({plat['taux_emission'] * 100:.0f} "
        f"% d'émission) — c'est le seuil z du mode, pas un seuil écrit ici")

    # === Le verdict : les DEUX chiffres, et l'effectif qui les porte ==========================
    chk("ESSAIS" in res["verdict"] and str(res["n_essais"]) in res["verdict"],
        f"le verdict dit l'effectif et son UNITÉ ({res['verdict'][:80]}…)")
    chk(f"{res['taux_emission'] * 100:.0f} %" in res["verdict"]
        and f"{res['justesse_emission'] * 100:.0f} %" in res["verdict"],
        "…et les deux chiffres, jamais l'un sans l'autre")
    chk("hasard" in res["verdict"].lower(),
        f"…avec le hasard, sans lequel un taux ne veut rien dire ({res['hasard']})")

    # Une séance où rien ne sort ne doit pas se lire comme un mauvais score : c'est l'ABSENCE de
    # score, et le verdict doit le dire autrement.
    muet = verdict(3, 24, 0, 0, 0.0, 0.0, 0.0, 0.0, 0)
    chk("RIEN" in muet and "absence de score" in muet,
        f"zéro émission se lit comme une ABSENCE de score, pas comme un mauvais score ({muet[:70]}…)")

    # === Les refus, avant tout calcul ==========================================================
    rt_vide = MesureSSVEP(SPEC, {}, _FauxMoteur())
    try:
        rt_vide._mesurer([], FS)
        chk(False, "une séance sans fréquences annoncées doit être REFUSÉE")
    except ValueError as e:
        chk("aucune fréquence" in str(e),
            f"…en disant que les fréquences viennent de l'ÉCRAN ({str(e)[:60]}…)")

    rt_court = MesureSSVEP(SPEC, {}, _FauxMoteur())
    rt_court._freqs = list(FREQS)
    try:
        rt_court._mesurer([(_bruit(rng, BESOIN), Essai(1, 0))], FS)
        chk(False, "une séance de 1 essai doit être REFUSÉE")
    except ValueError as e:
        chk("pas de quoi conclure" in str(e),
            f"…en disant qu'il n'y a pas de quoi conclure ({str(e)[:60]}…)")

    rt_sans_repos = MesureSSVEP(SPEC, {}, _FauxMoteur())
    rt_sans_repos._freqs = list(FREQS)
    try:
        rt_sans_repos._mesurer(
            [(_bruit(rng, BESOIN), Essai(i, 0)) for i in range(1, 13)], FS)
        chk(False, "une séance sans plancher de repos doit être REFUSÉE")
    except ValueError as e:
        chk("plancher de repos" in str(e) and "z" in str(e),
            f"…en disant que le SSVEP décide sur z et que le plancher lui manque ({str(e)[:70]}…)")

    # === La ligne du temps, menée par la FENÊTRE ==============================================
    def marqueur(event, **champs):
        return {"mode": "ssvep", "event": event, **champs}

    moteur = _FauxMoteur(secondes=40.0)
    rt = MesureSSVEP(SPEC, {}, moteur)
    t0 = moteur.t0
    rt.tick(moteur, t0)
    chk(rt.phase == "chauffe" and rt.state(now=t0)["restant_s"] > 14.0,
        f"on commence par la chauffe, et elle se décompte à l'écran ({rt.phase}, "
        f"{rt.state(now=t0)['restant_s']} s)")

    # L'annonce ARRIVE PENDANT la chauffe — le cas normal : la console lance la fenêtre au moment
    # même où elle demande la mesure.
    moteur.file([(t0 + 1.0, marqueur("calib_start", trials=6, freqs=FREQS, refresh_hz=60.0)),
                 (t0 + 1.5, marqueur("cue", target=0))])
    rt.tick(moteur, t0 + 2.0)
    chk(rt.phase == "chauffe" and rt.total() == 6 and rt._freqs == FREQS,
        f"l'annonce reçue pendant la chauffe est RETENUE, fréquences comprises ({rt.total()} "
        f"essais, {rt._freqs})")
    chk(rt.essai == 0 and rt._marqueurs_chauffe == 1,
        f"…mais les essais de cette période sont JETÉS et comptés : l'offset DC dérive encore "
        f"({rt.essai} enregistré(s), {rt._marqueurs_chauffe} jeté(s))")

    rt.tick(moteur, t0 + rt.warmup_s + 0.1)
    chk(rt.phase == "essais", f"la chauffe écoulée ouvre les essais ({rt.phase})")

    # Le REPOS, puis les essais. ⚠️ L'horodatage du `repos` est choisi pour que la fin de la phase
    # (`ts + SSVEP_GUIDE_REPOS_S`) tombe APRÈS le dernier échantillon du tampon fabriqué : c'est
    # l'état d'un repos EN COURS, le seul pendant lequel le plancher s'échantillonne. Le tampon de
    # ce faux moteur est figé sur 30 s, il ne « coule » pas comme celui du vrai.
    moteur.file([(t0 + 32.0, marqueur("repos"))])
    rt.tick(moteur, t0 + rt.warmup_s + 0.2)
    chk(rt._repos_fin_ts == t0 + 32.0 + SSVEP_GUIDE_REPOS_S,
        f"le `repos` fixe la fin du plancher dans l'horloge des MARQUEURS ({rt._repos_fin_ts}) — "
        f"la compter depuis sa RÉCEPTION la ferait mordre sur le premier essai")
    avant_repos = len(rt._enregistre)
    for i in range(1, 20):
        rt.tick(moteur, t0 + rt.warmup_s + 0.2 + 0.25 * i)
    chk(len(rt._enregistre) - avant_repos >= 10 and rt.essai == 0,
        f"le plancher s'échantillonne à la cadence du mode pendant le repos, et ce ne sont PAS des "
        f"essais ({len(rt._enregistre) - avant_repos} fenêtres de repos, {rt.essai} essais)")

    instants = [t0 + 6.0 + 5.0 * i for i in range(6)]
    moteur.file([(ts, marqueur("cue", target=i % 3)) for i, ts in enumerate(instants)])
    rt.tick(moteur, t0 + rt.warmup_s + 6.0)
    chk(rt.essai == 6 and rt.total() == 6,
        f"les six essais annoncés sont enregistrés ({rt.essai}/{rt.total()})")
    etiquettes = [lab for _f, lab in rt._enregistre if isinstance(lab, Essai)]
    chk([lab.cible for lab in etiquettes] == [i % 3 for i in range(6)],
        f"…étiquetés par la cible que l'écran a DÉSIGNÉE ({[lab.cible for lab in etiquettes]})")
    chk(all(len(f) == int(round(rt.epoque_marqueur_s * FS))
            for f, lab in rt._enregistre if isinstance(lab, Essai)),
        f"…et chaque époque couvre la FIXATION ENTIÈRE plus la marge de filtre "
        f"({rt.epoque_marqueur_s:g} s), pas la seule fenêtre de décision")

    # ⚠️ L'ANCRAGE : l'époque se termine à la FIN de la fixation, donc `SSVEP_GUIDE_FIX_S` APRÈS le
    # marqueur. Vérifié sur le tampon HORODATÉ, en comparant à l'appel de référence.
    attendu = epoch_from_stream(moteur.recent, moteur.recent_ts,
                                instants[0] + SSVEP_GUIDE_FIX_S, FS,
                                pre_s=rt.epoque_marqueur_s, post_s=0.0)
    premiere = next(f for f, lab in rt._enregistre if isinstance(lab, Essai) and lab.numero == 1)
    chk(attendu is not None and np.abs(np.asarray(premiere) - attendu).max() == 0,
        "l'époque est ancrée à la FIN de la fixation (cue + SSVEP_GUIDE_FIX_S) — ancrée sur le "
        "marqueur lui-même, elle prélèverait la saccade, où aucune réponse SSVEP n'est établie")

    moteur.file([(t0 + 20.0, marqueur("calib_end"))])
    rt.tick(moteur, t0 + rt.warmup_s + 7.0)
    chk(rt.phase == "mesure" and rt.resultat is None,
        f"`calib_end` ouvre le calcul mais ne l'exécute PAS dans le même tour : la console doit "
        f"pouvoir peindre « Calcul… » avant que la boucle ne bloque ({rt.phase})")
    rt.tick(moteur, t0 + rt.warmup_s + 7.1)
    chk(rt.phase == "fini" and rt.resultat and rt.resultat["n_essais"] == 6,
        f"le tour suivant calcule, sur les 6 ESSAIS ({rt.phase}, "
        f"{(rt.resultat or {}).get('n_essais')})")

    # === Les deux abandons ====================================================================
    moteur1 = _FauxMoteur()
    rt1 = MesureSSVEP(SPEC, {}, moteur1)
    rt1.tick(moteur1, moteur1.t0)
    rt1.tick(moteur1, moteur1.t0 + CALIB_FENETRE_ATTENTE_S - 1.0)
    chk(rt1.phase == "chauffe", f"avant le délai, la mesure attend encore la fenêtre ({rt1.phase})")
    rt1.tick(moteur1, moteur1.t0 + CALIB_FENETRE_ATTENTE_S + 1.0)
    chk(rt1.phase == "annule" and rt1.resultat is None
        and "fenêtre" in rt1.probleme and MARKER_STREAM_DEFAULT in rt1.probleme,
        f"sans `calib_start`, la mesure s'annule en disant les DEUX causes possibles : pas "
        f"lancée, ou publiant sous un autre nom ({rt1.probleme[:70]}…)")

    moteur2 = _FauxMoteur()
    rt2 = MesureSSVEP(SPEC, {}, moteur2)
    rt2.tick(moteur2, moteur2.t0)
    rt2.encaisser(moteur2, moteur2.t0, marqueur("calib_start", trials=10, freqs=FREQS))
    rt2.tick(moteur2, moteur2.t0 + rt2.warmup_s + 0.1)
    t2 = moteur2.t0 + rt2.warmup_s + 0.1
    moteur2.file([(moteur2.t0 + 5.0, marqueur("cue", target=0))])
    rt2.tick(moteur2, t2 + 1.0)
    chk(rt2.phase == "essais" and rt2.essai == 1,
        f"un marqueur arrive : la séance vit et compte son essai ({rt2.phase}, {rt2.essai})")
    rt2.tick(moteur2, t2 + 1.0 + CALIB_FENETRE_SILENCE_S - 0.5)
    chk(rt2.phase == "essais",
        f"un silence PLUS COURT que le seuil ne tue rien — le repos entre deux essais est normal "
        f"({rt2.phase})")
    rt2.tick(moteur2, t2 + 1.0 + CALIB_FENETRE_SILENCE_S + 0.5)
    chk(rt2.phase == "annule" and rt2.resultat is None and rt2._enregistre == [],
        f"au-delà du seuil, la fenêtre est réputée morte : la séance s'annule SANS calculer, et "
        f"les fenêtres déjà prélevées sont libérées ({rt2.phase}, {len(rt2._enregistre)})")

    # Le pendant : tous les essais annoncés SONT arrivés, seul `calib_end` manque. Ce n'est pas une
    # fenêtre morte — jeter la séance détruirait quatre minutes de signal bon.
    moteur3 = _FauxMoteur()
    rt3 = MesureSSVEP(SPEC, {}, moteur3)
    rt3.tick(moteur3, moteur3.t0)
    rt3.encaisser(moteur3, moteur3.t0, marqueur("calib_start", trials=1, freqs=FREQS))
    rt3.tick(moteur3, moteur3.t0 + rt3.warmup_s + 0.1)
    t3 = moteur3.t0 + rt3.warmup_s + 0.1
    moteur3.file([(moteur3.t0 + 5.0, marqueur("cue", target=1))])
    rt3.tick(moteur3, t3 + 1.0)
    rt3.tick(moteur3, t3 + 1.0 + CALIB_FENETRE_SILENCE_S + 0.5)
    chk(rt3.essai == 1 and rt3.phase == "essais",
        f"tous les essais annoncés reçus, `calib_end` manquant : la séance ATTEND au lieu de "
        f"jeter ({rt3.phase}, {rt3.essai}/{rt3.total()})")

    # === Le contrat public ====================================================================
    lus_par_la_console = {"mode_id", "phase", "etape", "classe", "instruction", "rappel",
                          "essai", "total", "restant_s", "duree_estimee_s", "resultat",
                          "probleme"}
    etat = rt.state(now=t0 + 40.0)
    chk(set(etat) >= lus_par_la_console,
        f"l'instantané porte tout ce qu'un écran de protocole lit "
        f"({sorted(lus_par_la_console - set(etat)) or 'aucun champ manquant'})")
    try:
        json.dumps(etat)
        serialisable = True
    except (TypeError, ValueError):
        serialisable = False
    chk(serialisable, "l'instantané est sérialisable en JSON — il part dans `snapshot()`")
    chk(etat["phase"] in PHASES and rt2.phase in PHASES_TERMINALES,
        f"les phases sont celles du vocabulaire PUBLIC de `modes/mesure.py` ({etat['phase']})")
    chk(etat["etape"] == "",
        f"`etape` reste VIDE : la console joue un top au front montant de `etape`, et cette "
        f"mesure ne doit pas biper par-dessus un stimulus visuel ({etat['etape']!r})")

    chk(SPEC.stimulus_id == "ssvep" and SPEC.barriere is False,
        f"la mesure DÉCLARE sa fenêtre et n'est PAS une barrière : un taux d'émission bas est le "
        f"régime normal de ce mode, pas un feu rouge ({SPEC.stimulus_id}, {SPEC.barriere})")
    chk([s.id for s in registry.MESURES] == ["alpha", "ssvep_taux"],
        f"…et elle est dans le catalogue du moteur, APRÈS la barrière alpha, qui se fait en "
        f"premier ({[s.id for s in registry.MESURES]})")
    sain, defauts = registry.check()
    chk(sain and not defauts, f"le registre reste sain avec elle ({defauts})")

    # Le tampon du moteur doit couvrir l'époque de cette mesure. Assertion DIRECTE sur `keep` :
    # observer qu'une époque « sort » ne prouve rien — un tampon sous-dimensionné rend quand même
    # ce qu'on lui demande, juste plus court.
    from core.server import EngineServer

    srv = EngineServer(synthetic=True, modes=(), instance="selftest-ssvep-mesure")
    try:
        chk(srv.keep >= int(round(MesureSSVEP.epoque_marqueur_s * srv.acq.fs)) + srv.acq.margin_n,
            f"le tampon du moteur couvre l'époque de cette mesure ({srv.keep} échantillons pour "
            f"{int(round(MesureSSVEP.epoque_marqueur_s * srv.acq.fs))} + "
            f"{srv.acq.margin_n} de marge) — sans ce terme NOMMÉ dans `keep`, chaque époque serait "
            f"tronquée en silence le jour où la calibration MI raccourcirait la sienne")
    finally:
        srv.close()

    chk(empreinte_dossier(DATA_DIR) == empreinte_avant,
        "et tout ce test n'a rien écrit dans `data/` — une mesure ne produit aucun fichier")

    print(f"[mesure-ssvep] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
