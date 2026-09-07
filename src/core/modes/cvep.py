"""Mode c-VEP : quelle cible est fixée, lue dans le DÉCALAGE d'un même code, jamais dans une
fréquence. BCI **active** : l'utilisateur choisit une cible en la fixant, comme le SSVEP — mais
là où le SSVEP cherche une fréquence, le c-VEP cherche une PHASE dans une m-séquence.

Le décodage (corrélation par lag) est dans `core/cvep_decoder.py` ; la m-séquence et le plan des
cibles dans `core/cvep_code.py` (tous deux déménagés dans `core/` à la tâche 1 de ce chantier, le
modèle `data/cvep_model.npz` survivant intact). Ici on décrit le MODE : ce qui se règle, ce qui se
publie, et — le cœur de CE fichier — **où en est le code affiché en ce moment**, sans quoi aucune
corrélation ne veut rien dire.

⚠️ **Ce fichier est différent de son patron, `core/modes/p300.py`/`core/modes/errp.py`, et c'est le
point à comprendre avant de lire plus loin.** Le P300 et l'ErrP DÉCOUPENT une époque **autour** de
chaque marqueur — le marqueur délimite un événement discret (un flash, un feedback). Le c-VEP, lui,
décode **en continu sur une fenêtre glissante**, comme le SSVEP : ses marqueurs ne délimitent RIEN,
ils **tiennent une horloge**. Un programme séparé (`stimulus/cvep.py`, tâche 5 de ce
chantier) affiche le clignotement et publie un marqueur `{"mode":"cvep","event":"cycle",
"refresh":…}` à CHAQUE redémarrage de la m-séquence (toutes les 63 frames). Ce runtime reconstruit,
à tout instant `t_fin`, la position dans le code que ce marqueur implique : c'est la **phase**.
`SPEC.marker_epoch_s` (voir plus bas) en découle : il **dimensionne le tampon du moteur**, il ne
décrit **aucune époque** — si ce champ te fait chercher un `pre_s`/`post_s` comme chez le P300 ou
l'ErrP, tu ne le trouveras pas ici, et c'est voulu : `CVEPRuntime` n'expose délibérément PAS ces
deux attributs de classe, pour que `registry.check()` n'applique pas la logique de troncature
d'époque (`pre_s+post_s` contre `marker_epoch_s`) à un mode qui n'en a pas.

⚠️ **Le cœur de ce fichier est la distinction entre `None` et `0`.** `phase_a` rend `None` quand il
n'y a pas de phase connue, et `0` est une position VALIDE du code (la toute première frame de la
m-séquence). Les confondre ferait décoder sur une horloge fausse tout en publiant des corrélations
d'apparence parfaitement normale — la panne muette que ce projet existe pour éliminer. TROIS
chemins rendent `None`, chacun une panne muette s'il n'est pas traité (cf. `phase_a`) :
    1. aucun marqueur de cycle n'a JAMAIS été reçu (`maj_reference` jamais appelée) ;
    2. `t_fin` est ANTÉRIEUR au dernier marqueur connu (horloges en désaccord, ou un appel avant
       la toute première référence utile) — sans cette garde, `int(age * refresh) % code_len` sur
       un `age` négatif rend un entier PLAUSIBLE (le modulo Python est toujours positif), sans la
       moindre exception ;
    3. la référence est PÉRIMÉE : plus de `CVEP_PEREMPTION_CYCLES` cycles se sont écoulés sans
       nouveau marqueur. Continuer en « roue libre » au-delà a été écarté par la spec (cf. le
       commentaire de la constante, `core/config.py`) : une petite dérive d'horloge entre l'écran
       et le moteur s'accumule vite au regard d'un code qui ne fait que 63 frames.

⚠️ Comme le P300 et l'ErrP : un modèle est propre à UNE personne, et ce mode ne démarre pas sans
un modèle ENTRAÎNÉ pour la même raison qu'eux — les scores d'un modèle entraîné sur quelqu'un
d'autre sont plausibles et faux, le pire des deux mondes. Le catalogue vit dans
`core/cvep_models.py` (jumeau de `mi_models`/`p300_models`/`errp_models`), et c'est LUI qui décide
du décodeur : le c-VEP est le seul mode du produit à en avoir **deux** sur le même stimulus (eCCA
et rCCA), et c'est le FICHIER de modèle qui déclare le sien. L'étudiant choisit un modèle, pas un
algorithme ; ce fichier lit `modele.decoder` et instancie la classe correspondante.

⚠️ **Second refus, propre à ce mode, à ne pas confondre avec le premier** : même avec un modèle
présent et lisible, `maj_reference` refuse tout marqueur dont le rafraîchissement déclaré
s'écarte de plus de 1 Hz de celui auquel le modèle a été calibré. Le modèle est calibré à UN
rafraîchissement, et c'est l'ÉMETTEUR qui tient l'écran — le moteur ne peut pas le voir avant de
recevoir un marqueur. Sans cette garde : le décodage tourne, les scores restent honnêtes, et RIEN
ne se déclenche jamais — c'est la panne qui a coûté une séance au SSVEP (cf. `SSVEP_WARMUP_S`).

⚠️ **QUATRE façons de ne pas décider, et elles sont COMPTÉES SÉPARÉMENT** (`state()`). Le flux, lui,
ne porte qu'un `-1` : c'est le contrat public, et il ne dit pas pourquoi. Or une séance casque coûte
cher et ne se répète pas — « ça ne détecte pas » sans la cause ne permet pas de distinguer
    1. `sans_reference`     — aucun marqueur d'horloge n'est jamais arrivé : l'émetteur n'est pas
                              lancé, ou il publie sous un autre nom de flux (`stream_in`) ;
    2. `reference_perimee`  — l'horloge s'est TUE : l'émetteur a planté, ou l'écran a été fermé ;
    3. `sous_les_seuils`    — le décodage a bien tourné, les corrélations ne passent pas
                              `corr_min`/`margin` : contact médiocre, ou personne qui ne fixe rien ;
    4. `vote_non_conclu`    — elles passent, mais les fenêtres récentes ne s'accordent pas : le
                              regard se promène d'une cible à l'autre.
Quatre causes, quatre gestes OPPOSÉS (relancer l'émetteur · vérifier le nom du flux · saliner ·
fixer UNE cible sans bouger les yeux). Les cinq compteurs — ces quatre plus `decodages` —
PARTITIONNENT les fenêtres traitées : chacune en incrémente exactement un. `age_reference_s`,
`corr_gagnant` et `corr_second` complètent le tableau : ils disent, en une ligne, si l'horloge est
vivante et à quelle hauteur les corrélations passent.

⚠️ **Le VOTE GLISSANT (spec §5) est dans le mode, pas dans le publieur.** Passer les deux seuils ne
suffit pas : il faut que `min_votes` des `vote_len` dernières fenêtres désignent la MÊME cible.
`core/lsl_io.py` est un transport sans état — y mettre une décision créerait une seconde logique de
décodage hors du mode. Ce vote n'est pas un raffinement : sans lui, le moteur décoderait à la même
cadence et sur la même géométrie que l'écran pygame que ce chantier archive, MOINS son 2-sur-3 —
donc strictement plus permissif que la référence à laquelle la séance casque doit le comparer.

⚠️ **Ce fichier ne rend AUCUN stimulus.** Comme le P300 et l'ErrP, c'est une application EXTERNE
(`stimulus/cvep.py`) qui affiche le clignotement et publie les marqueurs de cycle. Ce que
le c-VEP demande de plus qu'eux est un verrouillage à la FRAME : une seule frame sautée décale le
code et détruit la corrélation — c'est pourquoi sa calibration est `Calib(kind="fenetre")`, menée
par l'appli pygame et jamais par la console.

Autotest :
    python src/core/modes/cvep.py
"""

import os as _os
import sys as _sys
import time as _time

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (CVEP_BITS, CVEP_CHANNELS, CVEP_CORR_MIN,  # noqa: E402
                         CVEP_DECISION_CYCLES, CVEP_MARGIN, CVEP_MIN_VOTES,
                         CVEP_MODEL_PATH, CVEP_N_TARGETS, CVEP_PEREMPTION_CYCLES,
                         CVEP_VOTE_LEN, MARKER_STREAM_DEFAULT, SSVEP_WARMUP_S,
                         use_utf8_console)

from collections import Counter, deque  # noqa: E402

import numpy as np  # noqa: E402

from core import cvep_models  # noqa: E402
from core.cvep_code import build_targets  # noqa: E402
from core.cvep_decoder import CVEPDecoder, CVEPModel  # noqa: E402
from core.cvep_rcca import RCCADecoder  # noqa: E402
from core.lsl_io import DecodedCVEPPublisher, cvep_channel_labels, stream_name  # noqa: E402
from core.markers import flux_de_marqueurs_visibles  # noqa: E402
from core.modes.contract import Calib, ModeSpec, Param, Rest, validate  # noqa: E402
from core.modes.runtime import ModeRuntime  # noqa: E402

# Quel décodeur pour quel modèle. C'est le FICHIER qui déclare le sien (`cvep_models.charger` rend
# un objet dont l'attribut de classe `decoder` ne peut pas mentir) : l'étudiant choisit un modèle,
# jamais un algorithme. Les deux classes partagent EXACTEMENT le même contrat en ligne —
# `classify(fenêtre, phase) -> (cible|None, {nom: corrélation})` — et chacune apporte ses propres
# seuils DE CONSTRUCTION (`CVEP_CORR_MIN`/`CVEP_MARGIN` pour l'eCCA, `CVEP_RCCA_*` pour le rCCA),
# qui ne servent plus que de repli : `CVEPRuntime.decide` (tâche 7) leur impose ENSUITE un couple
# commun, relu dans `SPEC.params["corr_min"/"margin"]`. ⚠️ Il fut un temps où ce fichier écrivait
# ICI « ne pas partager un seuil entre les deux, leurs scores ne sont pas à la même échelle » —
# affirmation depuis RÉFUTÉE et corrigée dans `core/config.py` : mesurés, les deux décodeurs
# vivent à la MÊME échelle empirique (gagnant médian, essais corrects, k=2 : 0,323 pour l'eCCA,
# 0,261 pour le rCCA). Un couple commun n'est donc plus une approximation.
_DECODEURS = {"eCCA": CVEPDecoder, "rCCA": RCCADecoder}

# Paliers auxquels un marqueur de cycle refusé se DIT. Même motif que `p300._PALIERS_REFUS` et que
# les compteurs de marqueurs du moteur : une ligne par ordre de grandeur, jamais une par marqueur —
# ils arrivent à ~1 Hz, et un émetteur mal réglé les fait TOUS refuser.
_PALIERS_REFUS = (1, 10, 100, 1000)

# Le motif d'un -1, EN CLAIR. Les clés sont exactement celles des compteurs de `state()`, et
# c'est voulu : un seul vocabulaire pour le terminal, l'écran et le rapport de séance. Chaque
# phrase nomme le geste, parce que les trois causes en appellent trois DIFFÉRENTS — le compteur
# dit combien de fois, cette table dit quoi faire.
_MOTIFS_FR = {
    "sans_reference": "aucun marqueur d'horloge reçu — lance l'émetteur c-VEP, et vérifie qu'il "
                      "publie sur le flux réglé",
    "reference_perimee": "horloge PÉRIMÉE — l'émetteur s'est tu (planté ? fenêtre fermée ?)",
    "sous_les_seuils": "corrélations trop faibles ou trop serrées — vérifie le contact, saline, "
                      "et fixe UNE cible",
    "vote_non_conclu": "les fenêtres récentes ne s'accordent pas — fixe UNE cible sans bouger "
                       "les yeux",
}

# Tolérance flottante sur `age * refresh`, juste avant de tronquer en frame entière dans
# `phase_a`. ⚠️ MESURÉ, pas de précaution en l'air : à `ref_ts=100.0` et `t_fin=100.0+63/60.0`
# (exactement un cycle plus tard, le cas même que le test de ce fichier vérifie), `age` vaut
# `1.0499999999999972` au lieu de `1.05` — l'ARRONDI binaire de `100.0 + 63/60.0 - 100.0`, jamais
# `1.05` exactement. `age * 60.0` rend alors `62.99999999999983`, et `int(...)` TRONQUE vers 62 au
# lieu de 63 : la phase calculée retombe sur 62 au lieu de 0, un décalage d'UNE frame entière au
# pire moment (juste au wrap du code). Même classe de bug, même ordre de grandeur, que
# `registry._EPS_S` (« 0.15 + 0.80 vaut 0.9500000000000001 en flottant ») — 1e-9 s n'a aucune
# commune mesure avec un échantillon EEG (4 ms à 250 Hz) ni avec une frame d'écran (16,7 ms à
# 60 Hz), donc aucune vraie fraction de frame ne peut se glisser dessous.
_EPS_FRAME = 1e-9


def _modeles_disponibles():
    """Les modèles c-VEP chargeables, du plus récent au plus ancien. Délègue à `cvep_models`.

    ⚠️ Le dossier est DÉDUIT de `CVEP_MODEL_PATH` au lieu d'être laissé à son défaut, et ce n'est
    pas un détail de style : c'est la seule chose que l'autotest de ce fichier puisse repointer
    pour que ses fixtures ne lisent — ni n'écrivent — jamais le VRAI `data/`, qui contient des
    enregistrements EEG d'une personne identifiable sur un dépôt public. La constante est relue
    À CHAQUE APPEL (variable de module, pas valeur capturée) : c'est ce qui rend le repointage
    effectif.
    """
    return cvep_models.modeles_disponibles(_os.path.dirname(CVEP_MODEL_PATH))


class CVEPRuntime(ModeRuntime):
    """Tient la phase du code affiché, et refuse de décoder quand elle ne se connaît pas.

    ⚠️ N'expose PAS `pre_s`/`post_s` (contrairement à `P300Runtime`/`ErrPRuntime`) : ce mode ne
    découpe aucune époque autour d'un marqueur, cf. la docstring du module. En ajouter ferait
    croire à `registry.check()` que `marker_epoch_s` doit couvrir `pre_s+post_s`, alors qu'il
    dimensionne ici un tampon glissant, pas une tranche prélevée à un instant précis.
    """

    def __init__(self, spec, params, engine):
        super().__init__(spec, params, engine)
        self.model, raison = cvep_models.charger(params["model"])
        if self.model is None:
            # On lève ICI plutôt que de démarrer un mode muet. `validate` a déjà écarté le cas
            # « aucun modèle » ; il reste celui du fichier effacé entre la validation et le
            # démarrage, que seul le moteur peut voir — même garde que P300Runtime/ErrPRuntime.
            raise ValueError(raison)
        self.plan, self.code = build_targets()
        desaccord = self._desaccord_code()
        if desaccord is not None:
            raise ValueError(desaccord)
        # == len(self.code), vérifié juste au-dessus : `phase_a` s'appuie sur CETTE valeur (celle
        # que le modèle a APPRISE), pas sur `len(self.code)` — les deux sont égales par
        # construction ici, mais c'est le modèle qui fait autorité sur ce qu'il a décodé.
        self.code_len = self.model.code_len
        # Le décodeur suit le MODÈLE, pas un réglage : c'est le fichier qui déclare le sien.
        # `.decoder` est un attribut de CLASSE (cf. `cvep_decoder.CVEPModel`), donc un objet ne
        # peut pas mentir dessus — et `cvep_models.charger` a déjà refusé tout fichier déclarant
        # un décodeur inconnu, ce qui rend ce `[...]` sûr.
        self.decodeur = _DECODEURS[self.model.decoder](self.model, self.plan)
        # L'appariement NOM DE CIBLE -> INDICE PUBLIÉ, construit UNE fois. C'est le seul endroit
        # où l'indice du flux est décidé, et il est décidé à partir de ce que le DÉCODEUR rend :
        # refaire ici une recherche par `lag` créerait une seconde table d'appariement, qui
        # continuerait de désigner la bonne cible même si celle du décodeur était décalée d'un
        # cran — le défaut que la revue du P300 avait trouvé sur son propre mode, rendu
        # indétectable. (`cvep_code._selftest` garantit que les noms sont distincts.)
        self._indice = {c["name"]: i for i, c in enumerate(self.plan)}
        # Aucune phase connue tant qu'aucun marqueur de cycle n'est arrivé : c'est CE `None`,
        # distinct de `0`, qui fait refuser `phase_a` plutôt que de rendre une position plausible
        # et fausse. Cf. le ⚠️ de la docstring du module.
        self._ref_ts = None
        self._ref_refresh = None
        self._out = None
        self._decoded = None
        self._last_log = 0.0
        # Le VOTE GLISSANT (spec §5), sur le patron de `core/modes/mi.py`. Sans lui, le moteur
        # décoderait à la même cadence et sur la même géométrie que l'écran pygame que ce
        # chantier archive, MOINS son 2-sur-3 : strictement plus permissif que la référence à
        # laquelle la séance casque doit le comparer. On garde `(nom, corrélation)` et non le seul
        # nom, parce que c'est la MOYENNE des corrélations des fenêtres VOTANTES qui devient la
        # confiance publiée — cf. `_run_step`.
        self._votes = deque(maxlen=int(params["vote_len"]))
        # Le couple (corr_min, margin) sous lequel les votes ACTUELLEMENT empilés ont été jugés,
        # et celui que la dernière décision a réellement appliqué. Les deux existent parce que ces
        # deux seuils se règlent EN PLEINE SÉANCE sans reconstruire le runtime : sans eux, un
        # échantillon publié pouvait annoncer `corr_min = 0,40` à côté d'une `confidence` de 0,35
        # moyennée sur des fenêtres jugées à 0,26 — auto-contradictoire sur ses propres voies.
        # Cf. `decide` (qui capture) et `_publish` (qui publie le couple capturé).
        self._seuils_du_vote = None
        self._seuils_decision = None
        self._raz_compteurs()

    def _raz_compteurs(self):
        """Les compteurs de séance et les trois jauges de la dernière fenêtre décidée.

        ⚠️ Ce sont des compteurs DE SESSION, remis à zéro seulement par « Refaire le repos »
        (`_reset_rest`) — jamais par fenêtre : leur intérêt est de tenir le compte de toute une
        séance, qui ne se répète pas. Les trois jauges (`_age_reference_s`, `_corr_gagnant`,
        `_corr_second`) décrivent au contraire la DERNIÈRE fenêtre seule, et valent None tant
        qu'aucune ne s'applique — jamais 0, qui est une valeur parfaitement plausible pour une
        corrélation et se lirait comme une mesure.
        """
        self._decodages = 0            # fenêtres qui ont DÉSIGNÉ une cible
        self._sans_reference = 0       # ...aucun marqueur d'horloge jamais reçu
        self._reference_perimee = 0    # ...l'horloge s'est tue depuis trop longtemps
        # ⚠️ `sous_les_seuils` et `vote_non_conclu` sont DEUX refus distincts, et c'est la
        # correction la plus utile de ce fichier. Le brief n'en prévoyait qu'un, nommé
        # « vote_non_conclu », qui comptait en réalité les fenêtres sous `corr_min`/`margin` —
        # un vote qui n'existait pas encore. Maintenant qu'il existe :
        #   • `sous_les_seuils`  = cette fenêtre n'avait AUCUN candidat -> regarder le SIGNAL
        #                          (contact, saline, la personne fixe-t-elle quelque chose ?) ;
        #   • `vote_non_conclu`  = elle en avait un, mais les fenêtres récentes ne s'accordent
        #                          pas -> regarder la STABILITÉ du regard.
        # Deux gestes opposés. Les cinq compteurs PARTITIONNENT les fenêtres traitées : chaque
        # fenêtre en incrémente exactement un.
        self._sous_les_seuils = 0
        self._vote_non_conclu = 0
        self._marqueurs_refuses = 0    # marqueurs de cycle inutilisables (refresh manquant/faux)
        self._age_reference_s = None
        self._corr_gagnant = None
        self._corr_second = None

    def _desaccord_code(self):
        """La phrase à dire si le modèle n'a pas été calibré pour le code que la config ACTUELLE
        construit — None si tout concorde.

        `build_targets()` (donc `self.code`) dépend de `CVEP_BITS`/`CVEP_TAPS` dans
        `core/config.py`, jamais du modèle chargé. Un modèle calibré avant un changement de ces
        constantes porterait un `code_len` différent : sans ce contrôle, `phase_a` continuerait de
        rendre un entier plausible (juste modulo un AUTRE nombre que celui du code réellement
        affiché), et les lags de `self.plan` ne correspondraient à rien dans le template appris —
        un désaccord aussi silencieux que celui du rafraîchissement (`maj_reference`), découvert
        ici pour la même raison : un décodeur qui tourne, publie des scores honnêtes en apparence,
        et ne veut plus rien dire.
        """
        if self.model.code_len != len(self.code):
            return (f"ce modèle a été calibré pour un code de {self.model.code_len} frames, la "
                    f"config actuelle (CVEP_BITS={CVEP_BITS}) en construit un de "
                    f"{len(self.code)} — recalibre (`python src/research/app.py`, mode c-VEP), "
                    f"ou restaure CVEP_BITS à sa valeur de calibration.")
        # ...et le NOMBRE DE CIBLES sur lequel il a été calibré. `CVEPModel.save` enregistre ce
        # champ « pour pouvoir prévenir » (sa propre docstring) : jusqu'ici personne ne prévenait.
        # Le template eCCA est COMMUN à tous les lags, donc un modèle calibré sur 3 cibles
        # « marche » techniquement à 6 — il publie six corrélations d'apparence normale, dont
        # trois sortent de lags que la calibration n'a JAMAIS présentés. C'est la panne INVISIBLE
        # que ce fichier existe pour éliminer, et le comportement que l'appli pygame avait avant
        # ce chantier. `0` = modèle antérieur au champ : on ne peut alors rien en dire, et refuser
        # jetterait `data/cvep_model.npz`, le seul modèle réel du dépôt.
        cibles = int(getattr(self.model, "n_targets", 0) or 0)
        if cibles and cibles != len(self.plan):
            return (f"ce modèle a été calibré sur {cibles} cible(s), le stimulus actuel en "
                    f"affiche {len(self.plan)} (CVEP_N_TARGETS) — le template vaut pour tous les "
                    f"lags, mais les cibles supplémentaires n'ont JAMAIS été validées et leurs "
                    f"corrélations sont plausibles. Recalibre (`python src/research/app.py`, "
                    f"mode c-VEP) sans interrompre, ou remets CVEP_N_TARGETS à {cibles}.")
        return None

    def maj_reference(self, ts, refresh):
        """Un marqueur de cycle vient d'arriver : le code était à la frame 0 à l'instant `ts`.

        ⚠️ Le modèle est calibré à UN rafraîchissement, et c'est l'ÉMETTEUR qui tient l'écran — le
        moteur ne peut pas le voir avant de recevoir un marqueur. Sans cette garde : le décodage
        tourne, les scores restent honnêtes, et RIEN ne se déclenche jamais. C'est la panne qui a
        coûté une séance au SSVEP.
        """
        refresh = float(refresh)
        if abs(refresh - self.model.refresh) > 1.0:
            raise ValueError(
                f"l'émetteur affiche à {refresh:.1f} Hz, le modèle a été calibré à "
                f"{self.model.refresh:.1f} Hz — recalibre, ou lance l'émetteur avec "
                f"--refresh {self.model.refresh:.0f}")
        self._ref_ts = float(ts)
        self._ref_refresh = refresh

    def phase_a(self, t_fin):
        """Position dans le code à l'instant LSL `t_fin`, ou None s'il n'y a pas de phase.

        ⚠️ `None` et `0` sont deux choses DIFFÉRENTES : 0 est une position valide du code,
        None veut dire « je ne sais pas où j'en suis ». Les confondre ferait décoder sur une
        horloge fausse en publiant des corrélations d'apparence normale.

        ⚠️ Écart signalé au brief, MESURÉ : sa formule littérale (`int(age * refresh) %
        code_len`, sans `_EPS_FRAME`) échoue sur son PROPRE test de bord de cycle — cf. le
        commentaire de `_EPS_FRAME` ci-dessus pour les nombres exacts. Sans cette tolérance,
        `phase_a` rendrait 62 au lieu de 0 pile au wrap du code, une frame entière de moins que
        la position réelle, silencieusement (aucune exception, un entier plausible).
        """
        return self._phase_et_cause(t_fin)[0]

    def _phase_et_cause(self, t_fin):
        """(phase, None) quand l'horloge sert, (None, cause) sinon. `cause` nomme LAQUELLE.

        Le calcul vit ICI et `phase_a` s'y ramène, pour qu'il n'existe qu'UNE formule de
        péremption. La recopier dans `_run_step` pour y nommer la cause aurait donné deux
        arithmétiques à garder d'accord, sur exactement le genre de comparaison flottante qui a
        déjà coûté une frame entière à ce fichier (cf. `_EPS_FRAME`).

        Deux causes seulement là où la docstring du module en compte quatre : les deux autres
        (`sous_les_seuils`, `vote_non_conclu`) n'ont rien à voir avec l'horloge — elles se
        décident plus loin, sur des corrélations puis sur le vote glissant. Et le cas `age < 0` — un instant antérieur au dernier marqueur — est rangé
        sous `reference_perimee` plutôt que sous une quatrième cause : par le chemin du moteur il
        est INATTEIGNABLE (`markers_murs` ne rend jamais un marqueur postérieur au dernier
        échantillon acquis, et le moteur compte à part ceux qui viennent du futur, cf.
        `engine.marqueurs_futurs`), et la garde reste comme défense en profondeur — sans elle,
        `int(age * refresh) % code_len` sur un `age` négatif rendrait un entier PLAUSIBLE.
        """
        if self._ref_ts is None:
            return None, "sans_reference"
        age = float(t_fin) - self._ref_ts
        if age < 0.0 or age > CVEP_PEREMPTION_CYCLES * self.code_len / self._ref_refresh:
            return None, "reference_perimee"
        return int(age * self._ref_refresh + _EPS_FRAME) % self.code_len, None

    # --- le mode qui tourne -------------------------------------------------------------------

    def _open(self):
        # Le flux existe TOUT DE SUITE, avant même la fin de la chauffe, comme chez le SSVEP et
        # le P300 : un client qui le cherche au lancement ne doit pas dépendre de l'instant où
        # arrive le premier marqueur d'horloge (`resolve_byprop` a un délai fini).
        # ⚠️ `self.params["corr_min"/"margin"]`, PAS `self.decodeur.corr_min`/`.margin` : ces deux
        # réglages sont TOURNABLES en pleine séance (cf. `decide`), mais les métadonnées LSL sont
        # figées à l'ouverture du flux, qui elle N'EST PAS refaite quand on les change
        # (`affecte_decodage=False`). Elles décrivent donc le seuil EN VIGUEUR à l'ouverture, pas
        # une promesse de rester à jour — la sortie live (`_publish`) est la source qui reste
        # exacte après coup.
        self._out = DecodedCVEPPublisher(
            len(self.plan), decoder=self.model.decoder, refresh=self.model.refresh,
            code_len=self.code_len, corr_min=float(self.params["corr_min"]),
            margin=float(self.params["margin"]), cv=getattr(self.model, "cv_", None),
            votes=(int(self.params["min_votes"]), int(self.params["vote_len"])),
            instance=self.engine.instance)

    def _close(self):
        self._out = None

    def _reset_rest(self):
        self._decoded = None
        self._raz_compteurs()
        # ⚠️ La référence de phase part AUSSI : « refaire le repos » se fait en touchant les
        # électrodes, donc l'émetteur a eu tout le temps de dériver ou d'être relancé. Garder
        # l'ancienne ferait décoder sur une horloge qui n'a plus cours, en publiant des
        # corrélations d'apparence normale — la panne muette que ce mode existe pour éliminer.
        self._ref_ts = None
        self._ref_refresh = None
        # ...et le vote glissant avec elle : ses fenêtres décrivent un montage qu'on vient de
        # toucher, elles ne doivent pas peser sur la première décision d'après.
        self._votes.clear()

    def output(self):
        return self._decoded

    def channels(self):
        """Les voies suivent le PLAN de cibles construit à l'ouverture du mode, pas le contrat
        seul : `n_targets` est une géométrie de config (`CVEP_N_TARGETS`), et l'état publié ne
        doit pas pouvoir annoncer six voies pendant que le décodeur en note quatre."""
        return list(cvep_channel_labels(len(self.plan)))

    def state(self):
        """Comme `ModeRuntime.state()`, plus les compteurs qui disent POURQUOI il ne décide pas.

        Sans eux, une séance muette n'a qu'une lecture possible — « l'étudiant fixe mal » — et
        c'est le mode de panne le plus coûteux de ce projet. Les CINQ premiers PARTITIONNENT les
        fenêtres traitées (chacune en incrémente exactement un, cf. `_raz_compteurs`) ;
        `marqueurs_refuses` compte des MARQUEURS et non des fenêtres, il n'entre pas dans cette
        somme ; les trois derniers décrivent la dernière fenêtre seule.
        """
        base = super().state()
        base["decodages"] = self._decodages
        base["sans_reference"] = self._sans_reference
        base["reference_perimee"] = self._reference_perimee
        base["sous_les_seuils"] = self._sous_les_seuils
        base["vote_non_conclu"] = self._vote_non_conclu
        base["marqueurs_refuses"] = self._marqueurs_refuses
        base["age_reference_s"] = self._age_reference_s
        base["corr_gagnant"] = self._corr_gagnant
        base["corr_second"] = self._corr_second
        return base

    def _rest_step(self, engine, now):
        """Rien à mesurer : aucun plancher de repos ici (cf. `Rest.duration_s = 0`). Seule la
        chauffe compte, et elle est déjà passée quand on arrive ici. On en profite pour DIRE, en
        une ligne, les trois choses qu'on veut relire dans le journal d'une séance : quel modèle,
        quel décodeur, et où le mode écoute son horloge — le réglage le plus facile à se tromper.
        """
        if now < self._rest_until:
            return False
        # Lus dans `self.params`, pas dans `self.decodeur` : ce sont eux qui font foi (cf.
        # `decide`), et le repos peut suivre un changement de réglage fait avant même le premier
        # décodage.
        corr_min = float(self.params["corr_min"])
        margin = float(self.params["margin"])
        print(f"[cvep] modèle « {_os.path.basename(self.params['model'])} » ({self.model.decoder}, "
              f"seuils {corr_min:g}/{margin:g}) — horloge attendue "
              f"sur « {self.params['stream_in']} », publication sur "
              f"{stream_name(self.spec.stream)} ({len(self.plan)} cibles)")
        self.rest_report = {"kind": "cvep", "model": _os.path.basename(self.params["model"]),
                            "decodeur": self.model.decoder, "n_targets": len(self.plan),
                            "corr_min": corr_min, "margin": margin}
        return True

    def tick(self, engine, lsl_ts, now):
        """Comme `ModeRuntime.tick`, mais l'horloge tourne AUSSI pendant la chauffe.

        Le P300 JETTE ses marqueurs de chauffe : les siens délimitent des époques, et une époque
        prélevée pendant que l'offset DC dérive ne vaut rien. Ceux-ci ne délimitent rien — ils
        tiennent une horloge, et une horloge n'a pas besoin d'être « bonne » pour être à l'heure.
        On les ENCAISSE donc, et ça règle deux choses d'un coup :
          1. le curseur du moteur avance pendant les 15 s de chauffe. Sinon le premier
             `_run_step` avale l'arriéré, dont la douzaine de marqueurs déjà sortis du tampon
             EEG — comptés en `engine.marqueurs_perdus`, un compteur qui signale une VRAIE perte
             de données. Une alarme fausse à chaque démarrage apprend à ignorer l'alarme ;
          2. la première fenêtre décodée l'est avec une phase FRAÎCHE, au lieu d'attendre le
             marqueur suivant (jusqu'à 1,05 s de plus).
        """
        if self.phase != "running":
            self._encaisser_marqueurs(engine)
        super().tick(engine, lsl_ts, now)

    def _encaisser_marqueurs(self, engine):
        """Avance l'horloge sur tous les marqueurs de cycle mûrs. Ne lève jamais.

        ⚠️ `post_s=0.0`, et c'est un choix, pas un oubli. `markers_murs` attend que le tampon
        couvre les `post_s` secondes SUIVANT le marqueur. Pour une époque (P300, ErrP) c'est
        indispensable — il faut le signal d'après pour la découper. Pour une HORLOGE il n'y a
        rien à attendre : le marqueur dit où en était le code à `ts`, et c'est tout.

        Le second argument, celui de la MARGE, mérite d'être écrit avec ses chiffres parce qu'il
        est plus serré qu'il n'en a l'air. Avec `post_s = marker_epoch_s` (2,1 s), la référence
        la plus fraîche que le mode puisse tenir aurait toujours entre 2,1 s et 3,15 s d'âge, et
        la péremption tombe à `> 3,15` s : le mode ne serait donc PAS cassé avec un émetteur
        parfait — il fonctionnerait avec **zéro marge**. Le premier marqueur sauté (une frame
        perdue, un tour de boucle long) ferait basculer la référence en `reference_perimee`, et
        le mode cesserait de décoder pour une raison que personne ne rattacherait à ce réglage.
        """
        for ts, marqueur in engine.markers_murs(self.spec.id, post_s=0.0):
            if marqueur.get("event") != "cycle":
                # Tout autre événement est ignoré : le protocole s'enrichira, et un mode qui
                # refuserait ce qu'il ne connaît pas casserait au premier ajout.
                continue
            refresh = marqueur.get("refresh")
            # `isinstance(refresh, bool)` d'abord : en Python `bool` HÉRITE de `int`, donc `True`
            # passerait pour un rafraîchissement de 1 Hz. Un émetteur qui enverrait `true` en
            # JSON (le mot-clé existe) verrait alors tous ses marqueurs refusés pour la mauvaise
            # raison — ou pire, acceptés si la tolérance changeait un jour.
            if isinstance(refresh, bool) or not isinstance(refresh, (int, float)):
                self._refuse_marqueur(f"« {refresh!r} » n'est pas un rafraîchissement "
                                      f"({type(refresh).__name__}) — le marqueur de cycle doit "
                                      f"porter un champ `refresh` en Hz")
                continue
            try:
                self.maj_reference(ts, refresh)
            except ValueError as e:
                # Le désaccord de rafraîchissement entre l'émetteur et le modèle. Refuser est la
                # bonne réponse (cf. `maj_reference`) ; laisser l'exception remonter arrêterait
                # le moteur ENTIER, donc les autres modes actifs avec lui.
                self._refuse_marqueur(str(e))

    def _refuse_marqueur(self, detail):
        """Un marqueur de cycle inutilisable est un bug de l'émetteur. Compté toujours, dit par
        PALIERS : à ~1 marqueur/s, le dire à chaque fois noierait le terminal en une minute,
        et une seule fois par séance laisserait un émetteur mal réglé passer inaperçu."""
        self._marqueurs_refuses += 1
        if self._marqueurs_refuses in _PALIERS_REFUS:
            print(f"[cvep] marqueur de cycle refusé ({self._marqueurs_refuses} depuis le début) : "
                  f"{detail}")

    def _fenetre(self, engine):
        """La fenêtre BRUTE sur laquelle décider, ou None tant que le tampon est trop court.

        `n_cycles` cycles ENTIERS (ce que le décodeur va replier) plus la marge de filtrage, qui
        reste en TÊTE : le transitoire d'établissement du passe-bande y est confiné, et `fold`
        l'écarte en ne gardant que la queue. ⚠️ **Non filtrée**, exprès — `CVEPModel.scores`
        applique son propre passe-bande `CVEP_BAND` (2-45 Hz, LARGE, ≠ SSVEP). Filtrer ici
        filtrerait deux fois : phase décalée et amplitudes modifiées, donc une corrélation
        calculée contre autre chose que ce que le template a appris. Même piège, même formulation
        que `acquisition.motor_window` — c'est le défaut qui a déjà coûté un décodage au MI.

        Les colonnes sont celles du MODÈLE (`model.channels`, indices dans `CH_NAMES`), pas les
        premières venues : `w` est un filtre SPATIAL appris sur CES voies, dans CET ordre.
        """
        besoin = self.decodeur.n_cycles * self.model.n_cyc + engine.acq.margin_n
        bloc = engine.recent
        if bloc is None or len(bloc) < besoin:
            return None
        return np.asarray(bloc[-besoin:], dtype=float)[:, self.model.channels]

    def decide(self, fenetre, phase):
        """(cible|None, {nom: corrélation}) — même contrat que `self.decodeur.classify`.

        ⚠️ `corr_min`/`margin` sont relus ICI, dans `self.params`, à CHAQUE décision — jamais mis
        en cache dans `__init__`. C'est la SEULE raison pour laquelle `affecte_decodage=False` sur
        ces deux réglages (cf. `SPEC.params` et le commentaire du drapeau dans `contract.py`) n'est
        pas un mensonge : le contrat promet que les changer n'exige pas de reconstruire le runtime,
        et ce n'est vrai que tant qu'aucune valeur figée ne traîne. C'est aussi ce qui rend une
        séance casque réglable SANS l'interrompre : ni flux recréé, ni chauffe refaite (cf.
        `server._set_params`) — la garde que l'ErrP n'a pas sur son propre seuil (`tnr_target`).

        On les pose sur le DÉCODEUR juste avant de l'appeler, plutôt que de recopier ici son
        classement des corrélations : une seconde formule de décision à garder d'accord avec la
        sienne serait exactement le genre de vérité double que ce fichier évite ailleurs (cf.
        `self._indice`, et le défaut d'appariement que la revue du P300 avait trouvé sur son
        propre mode).
        """
        seuils = (float(self.params["corr_min"]), float(self.params["margin"]))
        self.decodeur.corr_min, self.decodeur.margin = seuils
        # ⚠️ Le couple RÉELLEMENT appliqué à CETTE fenêtre est retenu, parce que c'est lui qui
        # sera publié avec la décision qui en sort (cf. `_publish`) : un échantillon doit être
        # AUTO-COHÉRENT — les seuils qu'il annonce sont ceux contre lesquels il a été jugé, pas
        # ceux que l'opérateur a peut-être tournés depuis.
        self._seuils_decision = seuils
        return self.decodeur.classify(fenetre, phase)

    def _run_step(self, engine, lsl_ts):
        """Encaisser l'horloge, décoder la fenêtre courante, publier — ou dire pourquoi non."""
        self._encaisser_marqueurs(engine)
        fenetre = self._fenetre(engine)
        if fenetre is None:
            # Le tampon n'a pas encore de quoi replier deux cycles. Rien à publier et rien à
            # compter : ce n'est pas un refus de décider, c'est un mode qui n'a pas commencé.
            return

        # ⚠️ **L'instant auquel la phase se lit, et c'est le point le plus délicat du fichier.**
        # `CVEPModel.scores` documente `phase` comme la position du code au DÉBUT des cycles
        # repliés. On la lit pourtant à la FIN de la fenêtre, et les deux sont la même chose :
        # les cycles repliés couvrent exactement `n_cycles` périodes du code, donc la phase y
        # revient à l'identique. Le faire à l'endroit littéral serait au contraire FAUX en
        # pratique — le début de la fenêtre est 2,1 s dans le passé, tandis que le dernier
        # marqueur d'horloge a moins de 1,05 s : la référence tomberait presque toujours APRÈS
        # lui, `phase_a` verrait un âge négatif et refuserait de décoder à chaque fenêtre.
        t_fin = float(engine.recent_ts[-1]) if len(engine.recent_ts) else float(lsl_ts)
        self._age_reference_s = (None if self._ref_ts is None
                                 else round(t_fin - self._ref_ts, 3))
        phase, cause = self._phase_et_cause(t_fin)
        if phase is None:
            # On publie quand même, avec -1 : un client qui attend un échantillon par fenêtre ne
            # doit pas rester suspendu parce que le moteur a perdu l'horloge. Les scores valent
            # 0 — aucune corrélation n'a été calculée, et `no_decision_index` dit dans les
            # métadonnées qu'ils ne sont pas à lire.
            self._corr_gagnant = self._corr_second = None
            # ⚠️ ...et LA FILE DE VOTES avec, pour la raison même qui la vide dans `_reset_rest` :
            # ces votes décrivent un instant où l'horloge tenait ENCORE. Une référence périmée
            # rend ses votes périmés par construction — rien ne borne dans le temps une coupure
            # d'émetteur, elle peut durer dix minutes. Sans ce `clear`, la toute première fenêtre
            # d'après le retour de l'émetteur atteint `min_votes` sur des votes arbitrairement
            # vieux et publie une cible franche, avec une confiance parfaitement normale — la
            # panne muette que ce fichier existe pour éliminer, sur le chemin le PLUS fréquent
            # des deux (on relance l'émetteur plusieurs fois par séance, on « refait le repos »
            # une ou deux fois).
            self._votes.clear()
            if cause == "sans_reference":
                self._sans_reference += 1
            else:
                self._reference_perimee += 1
            self._publish(-1, 0.0, [0.0] * len(self.plan), t_fin, motif=cause)
            return

        cible, nommes = self.decide(fenetre, phase)
        # L'appariement score_<i> <-> cible i est le CONTRAT PUBLIC du flux. On le construit en
        # parcourant le plan DANS L'ORDRE et en relisant le nom que le décodeur a attaché à
        # chaque corrélation : c'est la SEULE lecture qui rougisse si la table d'appariement du
        # décodeur glisse d'un cran (elle désignerait alors la cible voisine, avec une confiance
        # parfaitement normale — prouvé par mutation dans `_selftest`).
        scores = [float(nommes[c["name"]]) for c in self.plan]
        ordonnes = sorted(scores, reverse=True)
        self._corr_gagnant = round(ordonnes[0], 3)
        self._corr_second = round(ordonnes[1], 3) if len(ordonnes) > 1 else None

        # Le VOTE GLISSANT. La fenêtre vote pour la cible que le décodeur a retenue, ou pour
        # personne (`None`) si elle n'a pas passé `corr_min`/`margin`. ⚠️ On empile AVANT de
        # consulter, et on consulte MÊME quand la fenêtre courante n'a rien retenu : c'est tout
        # l'intérêt d'un vote que d'absorber une mauvaise fenêtre au milieu de bonnes. Court-
        # circuiter sur `cible is None` rendrait le vote inutile — une fenêtre bruitée suffirait
        # à casser une fixation stable, ce qui est précisément ce qu'il existe pour éviter.
        # (Même mécanique que `MIRuntime._run_step`, jusqu'au `None` comptabilisé dans le
        # `Counter` : « aucune fenêtre récente n'était assez sûre » EST une réponse.)
        # ⚠️ Avant d'empiler : si le couple de seuils a bougé depuis que la file a été constituée,
        # elle part. Ces deux réglages se tournent EN PLEINE SÉANCE (`affecte_decodage=False`), et
        # chaque vote déjà empilé a été jugé contre le couple en vigueur AU MOMENT où il l'a été.
        # Les garder ferait publier une `confidence` — la moyenne de leurs corrélations — SOUS le
        # `corr_min` que le même échantillon annonce sur ses propres voies : un client qui refiltre
        # sur `confidence >= corr_min` (le geste que `cvep_channel_labels` l'invite explicitement à
        # faire) jetterait alors une fixation stable et valide. Coût du vidage : `vote_len - 1`
        # fenêtres, soit 0,4 s aux défauts — le prix d'un échantillon qui ne se contredit pas.
        if self._seuils_du_vote != self._seuils_decision:
            self._votes.clear()
            self._seuils_du_vote = self._seuils_decision
        nom = None if cible is None else cible["name"]
        self._votes.append((nom, 0.0 if nom is None else scores[self._indice[nom]]))

        gagnant, compte = Counter(n for n, _c in self._votes).most_common(1)[0]
        if gagnant is None or compte < int(self.params["min_votes"]):
            # Deux refus, deux GESTES. La fenêtre courante n'avait aucun candidat -> c'est le
            # SIGNAL qu'il faut regarder (contact, saline, fixation). Elle en avait un mais les
            # fenêtres récentes ne s'accordent pas -> c'est la STABILITÉ du regard. Les fondre
            # en un seul compteur, comme le nom `vote_non_conclu` du brief le faisait, envoie
            # chercher au mauvais endroit — et une séance casque ne se répète pas.
            if nom is None:
                self._sous_les_seuils += 1
                motif = "sous_les_seuils"
            else:
                self._vote_non_conclu += 1
                motif = "vote_non_conclu"
            self._publish(-1, 0.0, scores, t_fin, motif=motif)
            return
        # La confiance décrit le VOTE, comme l'indice qu'elle accompagne : la moyenne des
        # corrélations des fenêtres qui ont voté pour la cible retenue. Publier celle de la SEULE
        # dernière fenêtre mélangerait deux instants — un même échantillon dirait « CIBLE 2 » avec
        # une corrélation SOUS le `corr_min` que le flux annonce dans ses propres métadonnées, et
        # un client qui refiltre sur ce seuil (le geste naturel) jetterait les fixations stables.
        # Chacune de ces corrélations valant au moins `corr_min` par construction (sinon la
        # fenêtre aurait voté None), leur moyenne aussi : l'invariant est tenu par CONSTRUCTION.
        # ⚠️ « par construction » ne tient que parce que la file a été VIDÉE au moindre changement
        # de seuil juste au-dessus — sans ça, les votes de la file et le `corr_min` publié ne
        # seraient plus le même nombre pendant `vote_len - 1` fenêtres après chaque réglage.
        votantes = [c for n, c in self._votes if n == gagnant]
        self._decodages += 1
        self._publish(self._indice[gagnant], sum(votantes) / len(votantes), scores, t_fin,
                      seuils=self._seuils_du_vote)

    def _publish(self, target_index, confidence, scores, lsl_ts, motif=None, seuils=None):
        """`seuils` : le couple (corr_min, margin) contre lequel CETTE décision a été prise.

        ⚠️ Chaque échantillon doit être AUTO-COHÉRENT, et c'est toute la question ici, parce que
        ces deux seuils se règlent en pleine séance sans reconstruire le runtime :

        * un échantillon DÉCIDÉ (`target_index >= 0`) porte les seuils que la décision a
          réellement appliqués — ceux capturés par `decide`, sous lesquels toute la file de votes
          a été jugée. C'est ce qui rend vraie la promesse de `DecodedCVEPPublisher`
          (« `confidence` est toujours `>= corr_min` quand `target_index >= 0` ») ;
        * une fenêtre `-1` porte les seuils VIVANTS : rien n'a été décidé contre eux, et ce que
          l'opérateur veut lire là est le réglage en cours. C'est aussi le seul choix possible sur
          le chemin `phase is None`, qui ne passe jamais par `decide`.

        Lus dans `self.params` et jamais dans `self.decodeur` (cf. `decide`), et calculés une
        seule fois pour que le flux et l'écran ne puissent PAS diverger en lisant `self.params` à
        deux instants différents.
        """
        if seuils is None:
            seuils = (float(self.params["corr_min"]), float(self.params["margin"]))
        corr_min, margin = float(seuils[0]), float(seuils[1])
        if self._out is not None:
            # ⚠️ Transportés PAR ÉCHANTILLON (tâche 7, tour de correction 1), pas seulement dans
            # les métadonnées figées à l'ouverture du flux : ces deux seuils se règlent en pleine
            # séance SANS recréer ce flux, donc les métadonnées seules ne suffisent plus à dire
            # contre quel seuil UNE décision précise a été prise. Même geste que `threshold` chez
            # l'ErrP. Cf. `cvep_channel_labels`/`DecodedCVEPPublisher.push` dans `core/lsl_io.py`.
            self._out.push(target_index, confidence, scores, corr_min, margin, lsl_ts)
        self._decoded = {
            "target_index": int(target_index),
            "confidence": round(float(confidence), 3),
            "scores": [round(float(s), 3) for s in scores],
            # ⚠️ `corr_min`, PAS `threshold` : les deux consommateurs de cette sortie (la tuile de
            # la grille et la page du mode) choisissent leur rendu sur une CLÉ PRÉSENTE, jamais
            # sur l'identifiant du mode. `threshold` est celle du SSVEP, et elle emmène avec elle
            # une échelle en z et le texte « échelle z · seuil … » — appliqués à des corrélations
            # bornées dans [-1, 1], ils mentent d'un ordre de grandeur. Une clé propre force le
            # rendu propre, et le fait rougir s'il manque.
            "corr_min": corr_min,
            "margin": margin,
            # Le motif EN CLAIR, pas la clé du compteur : c'est le moteur qui possède ce
            # vocabulaire, et la console se contente de l'afficher. Le traduire côté interface
            # ferait deux tables à garder d'accord, et l'écran finirait par ne plus dire la même
            # chose que le terminal — pendant une séance, sur la seule ligne qui indique QUEL
            # geste faire.
            "motif": _MOTIFS_FR.get(motif, "") if motif else "",
        }
        self._log(target_index, scores, motif)

    def _log(self, target_index, scores, motif=None):
        """Trace la décision en console ~1×/s, comme le SSVEP : ce flux tourne à ~5 Hz, tout
        imprimer noierait le terminal. Les corrélations sont à CÔTÉ de la décision — c'est ce qui
        permet, pendant une séance, de dire si une non-détection vient d'un signal absent ou d'un
        seuil trop haut, sans brancher un troisième terminal."""
        now = _time.perf_counter()
        if now - self._last_log < 1.0:
            return
        self._last_log = now
        detail = "  ".join(f"{c['name']} {s:+.2f}" for c, s in zip(self.plan, scores))
        if target_index < 0:
            verdict = f"— ({_MOTIFS_FR.get(motif, motif or 'pas de décision')})"
        else:
            verdict = f"CIBLE {target_index} ({self.plan[target_index]['name']})"
        print(f"[cvep] {verdict:<46} {detail}")


def _channels(params):
    """Les voies du c-VEP : `CVEP_N_TARGETS` est une géométrie de config (couronne à 6 cibles,
    alignée sur le P300 pour comparer les deux paradigmes à cibles identiques), pas un réglage du
    mode. `params` n'est donc pas lu ; l'argument existe pour respecter le contrat `channels_fn`.
    """
    return cvep_channel_labels(CVEP_N_TARGETS)


SPEC = ModeSpec(
    id="cvep", label="c-VEP", family="actif",
    summary="Cible fixée parmi N, par codes pseudo-aléatoires décalés (le plus rapide).",
    status="moteur",
    key_channels=tuple(CVEP_CHANNELS),   # Pz, PO7, Oz, PO8 — le filtre spatial fait le tri
    params=(
        Param(key="model", label="Modèle entraîné", kind="choice",
              choices_fn=_modeles_disponibles,
              help="Le modèle produit par une calibration c-VEP, propre à TA personne — celui "
                   "de quelqu'un d'autre donne des corrélations plausibles et fausses. La liste "
                   "va du plus récent au plus ancien, donc le défaut est celui que tu viens de "
                   "calibrer. Les DEUX décodeurs (eCCA et rCCA) y figurent ensemble : c'est le "
                   "fichier qui déclare le sien, la question posée ici est « quel modèle », pas "
                   "« quel algorithme ». Aucun modèle dans la liste ? Lance "
                   "`python src/research/app.py`, mode c-VEP, et calibre."),
        Param(key="corr_min", label="Corrélation minimale", kind="float",
              default=CVEP_CORR_MIN, min=0.0, max=1.0, affecte_decodage=False,
              help="Le gagnant doit dépasser cette corrélation pour être retenu — en dessous, la "
                   "fenêtre compte en « sous_les_seuils » plutôt que d'émettre. Le produit part "
                   "STRICT par défaut : un seuil trop permissif est la panne la plus coûteuse de "
                   "ce projet, un décodage qui affiche avec assurance des corrélations "
                   "d'apparence normale sur du bruit. DESCENDS cette valeur en séance si le mode "
                   "reste muet malgré un bon contact — SANS risque : ce réglage est relu à CHAQUE "
                   "décision, il ne recrée ni le flux ni la chauffe."),
        Param(key="margin", label="Marge sur le second", kind="float",
              default=CVEP_MARGIN, min=0.0, max=1.0, affecte_decodage=False,
              help="Le gagnant doit en plus devancer le deuxième candidat de cette marge, sinon "
                   "la fenêtre compte en « sous_les_seuils » comme pour « Corrélation minimale » "
                   "— les deux seuils forment UNE règle, desserrer l'un sans l'autre laisse "
                   "l'autre trancher seul. TOURNABLE en pleine séance, comme lui."),
        Param(key="stream_in", label="Flux de marqueurs", kind="choice",
              choices_fn=flux_de_marqueurs_visibles, default=MARKER_STREAM_DEFAULT,
              affecte_decodage=False,
              help="Le nom du flux LSL sur lequel l'émetteur c-VEP publie son marqueur de "
                   "CYCLE — un par redémarrage du code, soit environ un par seconde. Ce n'est "
                   "pas un événement à épocher comme un flash P300 : c'est une HORLOGE, et sans "
                   "elle le moteur ne sait pas où en est le code affiché, donc il ne décode "
                   "rien du tout (compteur « sans_reference »). La liste montre les flux de "
                   "marqueurs VISIBLES au moment où tu ouvres cette page, plus le nom par "
                   "défaut, toujours proposé — c'est le cas normal, puisqu'on lance le moteur "
                   "avant l'émetteur. Ton émetteur n'y est pas ? Ressors de la page et reviens. "
                   "Le changer pendant que le mode tourne n'a AUCUN effet : l'inlet ouvert reste "
                   "sur l'ancien nom. ARRÊTER puis redémarrer ce mode suffit en revanche à "
                   "reprendre le nouveau. Un seul inlet existe pour tout le moteur, partagé par "
                   "tous les modes à marqueurs : deux modes actifs qui en réclameraient des noms "
                   "différents sont signalés bruyamment, un seul nom gagne."),
        Param(key="vote_len", label="Fenêtres du vote", kind="int",
              default=CVEP_VOTE_LEN, min=1, max=15,
              help="Sur combien de fenêtres récentes on vote avant d'émettre une cible. Le "
                   "décodage tourne à ~5 Hz, donc 3 fenêtres = 0,6 s de latence ajoutée. "
                   "Le mettre à 1 supprime le vote : chaque fenêtre décide seule, le mode "
                   "devient plus réactif ET nettement plus bruyant."),
        Param(key="min_votes", label="Votes concordants", kind="int",
              default=CVEP_MIN_VOTES, min=1, max=15,
              constraints=("votes_atteignables",),
              help="Combien de ces fenêtres doivent désigner la MÊME cible pour l'émettre. En "
                   "demander plus retarde la décision et la rend plus sûre. Ne peut pas dépasser "
                   "« Fenêtres du vote » : au-delà, aucun vote ne peut plus jamais aboutir et le "
                   "mode ne décide plus rien — en silence."),
    ),
    rest=Rest(
        warmup_s=SSVEP_WARMUP_S,   # 15 s : l'offset DC de l'Unicorn dérive après ouverture
        duration_s=0.0,            # pas de plancher à mesurer : la décision se joue sur une
        #                            corrélation contre un template appris, pas sur un z-score
        #                            contre un repos du jour (contrairement au SSVEP/neuro/ErrP)
        instruction="Le casque se stabilise — reste immobile.",
    ),
    calibration=Calib(kind="fenetre", stimulus_id="cvep", label="Calibrer le c-VEP"),
    # Le nom du flux vient du PUBLIEUR, il n'est pas réécrit ici : le contrat public s'écrirait
    # sinon à deux endroits sans que rien ne les relie — et deux façons de nommer la même chose
    # finissent toujours par diverger (cf. `DecodedP300Publisher.SUFFIXE`).
    stream=DecodedCVEPPublisher.SUFFIXE,
    channels_fn=_channels,
    runtime_cls=CVEPRuntime,
    # La fenêtre de décision : CVEP_DECISION_CYCLES cycles du code, 2 x 63 / 60 = 2,1 s. ⚠️ Ce
    # champ DIMENSIONNE LE TAMPON DU MOTEUR, il NE DÉCRIT AUCUNE ÉPOQUE — contrairement au P300 et
    # à l'ErrP, dont les marqueurs délimitent un événement discret. Les marqueurs c-VEP ne
    # délimitent rien : ils tiennent une horloge (cf. la docstring du module). Si tu cherches un
    # `pre_s`/`post_s` correspondant sur `CVEPRuntime`, il n'y en a pas, volontairement.
    marker_epoch_s=CVEP_DECISION_CYCLES * (2 ** CVEP_BITS - 1) / 60.0,
)


def _selftest():
    """Le runtime c-VEP : la phase et ses TROIS états muets (LE test de cette tâche, brief
    étape 1), plus les refus qui protègent `__init__` — sans modèle, modèle/rafraîchissement en
    désaccord avec l'émetteur, et modèle/config en désaccord sur la longueur du code.

    Aucun casque, aucune fenêtre EEG : ce fichier ne décode rien encore (cf. le ⚠️ de la docstring
    du module) — il tient l'horloge du code et refuse de la tenir à tort, rien de plus.
    """
    import contextlib
    import shutil
    import tempfile

    import numpy as np

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    @contextlib.contextmanager
    def _modele_temporaire(modele=None, n_targets=CVEP_N_TARGETS):
        """Pointe `CVEP_MODEL_PATH` vers CE modèle (sauvegardé dans un dossier temporaire) le
        temps du bloc `with` — ou vers un chemin qui n'existe pas si `modele` est None (« aucun
        modèle »). Restauré et le dossier nettoyé ENSUITE, quoi qu'il arrive.

        ⚠️ C'est le SEUL levier qui permette à `_modeles_disponibles`/`validate` de voir CE
        modèle plutôt que le vrai `data/cvep_model.npz` du dépôt — jamais touché, jamais même lu
        par ce fichier de test. Même geste que `errp.py` monkey-patchant
        `errp_models.modeles_disponibles` pour ses propres tests ; ici il n'existe pas encore de
        module `cvep_models` à monkey-patcher (tâche 3), donc c'est la constante elle-même,
        importée dans CE module, qui est repointée.
        """
        global CVEP_MODEL_PATH
        dossier = tempfile.mkdtemp(prefix="cvep_mode_test_")
        avant = CVEP_MODEL_PATH
        try:
            if modele is None:
                CVEP_MODEL_PATH = _os.path.join(dossier, "aucun_modele.npz")
            elif modele.decoder == "rCCA":
                # `RCCAModel.save` ne prend PAS de `n_targets` : il le DÉDUIT de ses codes (c'est
                # une propriété), là où l'eCCA doit l'enregistrer parce que son template est
                # commun à tous les lags. Deux signatures, une seule fabrique.
                CVEP_MODEL_PATH = modele.save(_os.path.join(dossier, "cvep_model.npz"))
            else:
                CVEP_MODEL_PATH = modele.save(_os.path.join(dossier, "cvep_model.npz"),
                                              n_targets=n_targets)
            yield
        finally:
            CVEP_MODEL_PATH = avant
            shutil.rmtree(dossier, ignore_errors=True)

    def _runtime_de_test(code_len=63, refresh=60.0, n_targets=CVEP_N_TARGETS, modele=None,
                         overrides=None, engine=None):
        """Fabrique minimale, sans moteur ni casque : un `CVEPModel` de la forme voulue (voies =
        CVEP_CHANNELS, `code_len`/`refresh` donnés), sauvegardé puis rechargé par le chemin RÉEL
        de `CVEPRuntime.__init__` (`validate` puis construction) — pas de raccourci qui
        court-circuiterait les refus que ce fichier doit protéger.

        Le modèle par défaut a un `template` PLAT : ses corrélations valent 0, ce qui est
        exactement ce qu'il faut aux tests de contrat et de compteurs (aucune décision ne peut
        sortir). Passer `modele=` fournit à la place un modèle RÉELLEMENT entraîné — c'est ce
        dont le test de bout en bout a besoin.

        `overrides` : réglages soumis à `validate` EN PLUS des défauts — ce qui permet de
        fabriquer un runtime démarré avec un `corr_min`/`margin` NON défaut, comme le ferait la
        commande initiale d'un client (tour de correction 1, revue de la tâche 7 : `_open` et
        `_rest_step` s'étaient avérés non protégés contre ce cas précis). `engine` : `None` par
        défaut (la plupart des tests ne décodent jamais assez pour en avoir besoin) — passer un
        objet portant `.instance` pour les tests qui appellent `_open()`, qui le lit.
        """
        if modele is None:
            modele = CVEPModel(fs=250.0, refresh=refresh, code_len=code_len,
                               channels=CVEP_CHANNELS)
            modele.w = np.ones(len(CVEP_CHANNELS))
            modele.template = np.zeros(code_len)
            modele.cv_ = 0.5
        with _modele_temporaire(modele, n_targets=n_targets):
            valeurs, raison = validate(SPEC, overrides or {})
            if raison is not None:
                raise RuntimeError(f"fabrique de test cassée : {raison}")
            rt = CVEPRuntime(SPEC, valeurs, engine=engine)
        return rt

    # --- 1. Sans modèle du tout : le mode REFUSE et dit comment en obtenir un. ----------------
    with _modele_temporaire(None):
        valeurs, raison = validate(SPEC, {})
    chk(raison is not None and "aucun choix disponible" in raison
        and "research/app.py" in raison,
        f"sans modèle, le mode refuse en disant quoi faire ({raison})")

    # --- 2. La phase, et ses TROIS états muets (LE test de cette tâche, brief étape 1) --------
    # Chacun est une panne muette s'il n'est pas traité : le mode continuerait de publier des
    # scores d'apparence honnête calculés sur une horloge fausse.
    rt = _runtime_de_test(code_len=63, refresh=60.0)

    chk(rt.phase_a(100.0) is None,
        "sans aucun marqueur reçu, il n'y a PAS de phase — et surtout pas 0, qui serait une "
        "position valide du code")

    rt.maj_reference(ts=100.0, refresh=60.0)
    chk(rt.phase_a(100.0) == 0, f"à l'instant du marqueur, la phase vaut 0 ({rt.phase_a(100.0)})")
    chk(rt.phase_a(100.0 + 10 / 60.0) == 10,
        f"dix frames plus tard, phase = 10 ({rt.phase_a(100.0 + 10 / 60.0)})")
    chk(rt.phase_a(100.0 + 63 / 60.0) == 0,
        "un cycle entier plus tard, la phase est REVENUE à 0 (modulo la longueur du code)")

    # Péremption : au-delà de CVEP_PEREMPTION_CYCLES, la référence ne vaut plus rien. Continuer
    # en roue libre est l'approche écartée par la spec : à 59,94 Hz réels contre 60 supposés,
    # l'erreur atteint 3,6 frames en une minute sur un code qui en fait 63.
    juste_avant = 100.0 + (CVEP_PEREMPTION_CYCLES * 63 / 60.0) - 0.01
    juste_apres = 100.0 + (CVEP_PEREMPTION_CYCLES * 63 / 60.0) + 0.01
    chk(rt.phase_a(juste_avant) is not None,
        "juste avant la péremption, la référence sert encore")
    chk(rt.phase_a(juste_apres) is None,
        "juste après, elle est PÉRIMÉE : on cesse de décoder au lieu de dériver en silence")

    # ⚠️ Le TROISIÈME état muet, documenté en commentaire dans `phase_a` mais pas exercé par le
    # test ci-dessus : `t_fin` ANTÉRIEUR au dernier marqueur connu (age < 0). Pas un cas d'école :
    # deux horloges en léger désaccord, ou un appel fait avant la toute première référence utile.
    # Sans la garde `age < 0.0`, `int(age * refresh) % code_len` sur un age NÉGATIF rend un entier
    # PLAUSIBLE (le modulo Python est toujours positif) — AUCUNE exception, juste une phase qui a
    # l'air normale et qui ne veut rien dire.
    chk(rt.phase_a(100.0 - 1.0) is None,
        f"un instant ANTÉRIEUR au dernier marqueur connu n'a pas de phase valide non plus "
        f"({rt.phase_a(100.0 - 1.0)})")

    # --- 3. Le refus de rafraîchissement : l'émetteur et le modèle doivent s'accorder --------
    rt2 = _runtime_de_test(code_len=63, refresh=60.0)
    try:
        rt2.maj_reference(ts=200.0, refresh=75.0)   # modèle calibré à 60 Hz, émetteur à 75 Hz
        refus_refresh = None
    except ValueError as e:
        refus_refresh = str(e)
    chk(refus_refresh is not None and "75.0" in refus_refresh and "60" in refus_refresh
        and "recalibre" in refus_refresh,
        f"un émetteur qui affiche à un AUTRE rafraîchissement que le modèle est refusé, en "
        f"nommant les deux fréquences ({refus_refresh})")
    chk(rt2.phase_a(200.0) is None,
        "...et le refus n'a laissé AUCUNE référence utilisable derrière lui")

    # 3bis. À l'inverse, un petit écart (bruit de mesure du refresh réel de l'écran) est toléré.
    rt2.maj_reference(ts=200.0, refresh=60.4)
    chk(rt2.phase_a(200.0) == 0,
        f"un écart de 0,4 Hz (sous la tolérance de 1 Hz) est accepté ({rt2.phase_a(200.0)})")

    # --- 4. Le refus de désaccord de code : un modèle calibré pour un AUTRE code_len ---------
    modele_faux = CVEPModel(fs=250.0, refresh=60.0, code_len=31, channels=CVEP_CHANNELS)
    modele_faux.w = np.ones(len(CVEP_CHANNELS))
    modele_faux.template = np.zeros(31)
    modele_faux.cv_ = 0.5
    with _modele_temporaire(modele_faux):
        valeurs, raison = validate(SPEC, {})
        chk(valeurs is not None, f"un modèle à 31 frames passe la validation du CHOIX ({raison})")
        try:
            CVEPRuntime(SPEC, valeurs, engine=None)
            refus_code = None
        except ValueError as e:
            refus_code = str(e)
    chk(refus_code is not None and "31" in refus_code and "63" in refus_code,
        f"...mais la CONSTRUCTION refuse un modèle calibré pour un AUTRE code que celui que la "
        f"config actuelle construit, en nommant les deux longueurs ({refus_code})")

    # --- 4bis. Le refus de NOMBRE DE CIBLES : `n_targets` PRÉVIENT enfin -----------------------
    # ⚠️ `CVEPModel.save` enregistre ce champ « pour pouvoir prévenir » (sa docstring) et personne
    # ne prévenait. Cas concret, et il n'a rien d'une hypothèse d'école : une calibration
    # interrompue à l'ESC après deux cibles sur six, ou un `CVEP_N_TARGETS` remis à 6 après une
    # calibration rapide à 3 (`core/config.py` documente des allers-retours 4 -> 6 -> 8 -> 6). Le
    # template eCCA étant COMMUN à tous les lags, le modèle « marche » : six corrélations
    # d'apparence normale, dont quatre issues de lags jamais validés.
    modele_partiel = CVEPModel(fs=250.0, refresh=60.0, code_len=63, channels=CVEP_CHANNELS)
    modele_partiel.w = np.ones(len(CVEP_CHANNELS))
    modele_partiel.template = np.zeros(63)
    modele_partiel.cv_ = 0.5
    with _modele_temporaire(modele_partiel, n_targets=2):
        valeurs, raison = validate(SPEC, {})
        chk(valeurs is not None, f"un modèle à 2 cibles passe la validation du CHOIX ({raison})")
        try:
            CVEPRuntime(SPEC, valeurs, engine=None)
            refus_cibles = None
        except ValueError as e:
            refus_cibles = str(e)
    chk(refus_cibles is not None and "2 cible" in refus_cibles
        and str(CVEP_N_TARGETS) in refus_cibles and "recalibre" in refus_cibles.lower(),
        f"...et un modèle calibré sur MOINS de cibles que le stimulus n'en affiche est refusé, en "
        f"nommant les deux nombres — sinon les cibles jamais validées publient des corrélations "
        f"plausibles ({refus_cibles})")
    # ...mais un modèle ANTÉRIEUR au champ (`n_targets = 0`) reste accepté : on ne peut rien en
    # dire, et refuser jetterait `data/cvep_model.npz`, le seul modèle c-VEP réel du dépôt.
    rt_ancien = _runtime_de_test(n_targets=0)
    chk(rt_ancien.model.n_targets == 0 and rt_ancien._desaccord_code() is None,
        f"un modèle antérieur au champ (n_targets = 0) n'est PAS refusé : 0 veut dire « inconnu », "
        f"pas « zéro cible » ({rt_ancien.model.n_targets})")

    # --- 5. Le contrat du mode -----------------------------------------------------------------
    chk(SPEC.id == "cvep" and SPEC.family == "actif" and SPEC.status == "moteur",
        f"identifiant, famille et statut du mode ({SPEC.id}, {SPEC.family}, {SPEC.status})")
    chk(SPEC.stream == "decoded_cvep", f"publié sur decoded_cvep ({SPEC.stream})")
    chk(abs(SPEC.marker_epoch_s - 2.1) < 1e-9,
        f"la fenêtre de décision dimensionne le tampon, 2 x 63/60 = 2,1 s ({SPEC.marker_epoch_s:g})")
    chk(SPEC.calibration is not None and SPEC.calibration.kind == "fenetre"
        and SPEC.calibration.stimulus_id == "cvep",
        "sa calibration est menée par une FENÊTRE : le code doit défiler frame par frame, et le "
        "marqueur de cycle qu'elle publie est l'horloge sans laquelle il n'y a pas de phase")
    chk(SPEC.rest is not None and SPEC.rest.warmup_s == SSVEP_WARMUP_S
        and SPEC.rest.duration_s == 0.0,
        f"chauffe seule, pas de repos à mesurer — le c-VEP ne normalise pas contre un plancher "
        f"({SPEC.rest})")
    chk(not hasattr(CVEPRuntime, "pre_s") and not hasattr(CVEPRuntime, "post_s"),
        "CVEPRuntime n'expose PAS pre_s/post_s : marker_epoch_s dimensionne un tampon, pas une "
        "époque (cf. docstring du module) — registry.check() ne doit pas y voir un troisième "
        "mode à marqueurs délimitant une tranche")

    # --- 5bis. Le flux entrant se RÈGLE, comme chez le P300 et l'ErrP -------------------------
    # Ce mode consomme `engine.markers_murs`, donc `server._nom_flux_marqueurs` va lire
    # `rt.params["stream_in"]`. Sans ce réglage déclaré, `contract.validate` REFUSE la clé : le
    # flux entrant serait GELÉ sur le nom par défaut, et `_libere_marker_inlet` — qui ne lâche
    # l'inlet que si plus aucun mode actif n'écoute — casserait la voie de secours que l'aide du
    # P300 promet (« arrêter puis redémarrer ce mode suffit »). Mesuré au chantier ErrP.
    rt_flux = _runtime_de_test(code_len=63, refresh=60.0)
    chk({p.key for p in SPEC.params} == {"model", "stream_in", "vote_len", "min_votes",
                                         "corr_min", "margin"},
        f"le modèle, le flux de marqueurs, le vote glissant ET les deux seuils se règlent "
        f"({sorted(p.key for p in SPEC.params)})")
    chk(rt_flux.params.get("stream_in") == MARKER_STREAM_DEFAULT,
        f"le RUNTIME porte le nom du flux entrant, là où le moteur va le chercher "
        f"({rt_flux.params.get('stream_in')})")
    chk(SPEC.marker_epoch_s > 0.0,
        f"ce mode CONSOMME des marqueurs, donc le moteur lit son stream_in — c'est ce qui rend "
        f"ce réglage obligatoire et non décoratif ({SPEC.marker_epoch_s})")

    # --- 5ter. Le VOTE GLISSANT : les deux constantes de la spec §5 sont enfin LUES ------------
    # ⚠️ `CVEP_VOTE_LEN`/`CVEP_MIN_VOTES` existent depuis toujours dans `core/config.py` et
    # n'étaient lues que par l'écran pygame (`research/app.py`), que ce chantier archive. Sans
    # elles ici, le moteur décoderait à la MÊME cadence sur la MÊME géométrie que la référence
    # qu'il remplace, MOINS son 2-sur-3 : strictement plus bruyant par construction. Or la séance
    # casque doit comparer les deux sur la même personne — une version moteur plus permissive
    # fausserait la seule comparaison chiffrée que ce chantier prévoit.
    chk(rt_flux.params["vote_len"] == CVEP_VOTE_LEN
        and rt_flux.params["min_votes"] == CVEP_MIN_VOTES,
        f"le vote prend les défauts du protocole ({rt_flux.params['vote_len']}, "
        f"{rt_flux.params['min_votes']})")
    # La contrainte croisée de `contract.py` : exiger plus d'accords qu'il n'y a de fenêtres pour
    # les compter ne peut JAMAIS être satisfait — le mode ne publierait plus que -1, en silence.
    _v, raison_vote = validate(SPEC, {"vote_len": 2, "min_votes": 5})
    chk(raison_vote is not None and "jamais atteignable" in raison_vote,
        f"...et exiger plus de votes que de fenêtres est refusé, pas accepté en silence "
        f"({raison_vote})")

    # --- 5quater. `_open`/`_rest_step` honorent un seuil NON DÉFAUT DÈS LA CONSTRUCTION ---------
    # ⚠️ Revue de la tâche 7, tour de correction 1 : ni `_open` ni `_rest_step` ne sont exercés
    # par la section 7bis ci-dessous (elle pose `rt._opened = True` À LA MAIN, sans jamais
    # appeler `_open`), et partout où `decide()` tourne, `self.decodeur.corr_min` vaut DÉJÀ
    # `self.params["corr_min"]` par construction — donc revenir à une lecture sur `self.decodeur`
    # dans `_open`/`_rest_step` laissait `modes/cvep.py`, `server.py --smoke` et
    # `console/app.py --smoke` tous verts. Scénario réel : un client démarre le mode avec un
    # `corr_min` NON défaut dès sa commande initiale (avant tout `decide()`) — les métadonnées et
    # le compte-rendu de repos doivent porter CE réglage, pas le défaut de construction du
    # décodeur (`CVEP_CORR_MIN`/`CVEP_MARGIN`, qui vaut ici par coïncidence le même défaut que
    # `SPEC.params` : sans un `overrides` explicitement DIFFÉRENT, ce test ne prouverait rien).
    from types import SimpleNamespace

    rt_ouv = _runtime_de_test(overrides={"corr_min": 0.501, "margin": 0.222},
                              engine=SimpleNamespace(instance="selftest-open"))
    chk(rt_ouv.params["corr_min"] == 0.501 and rt_ouv.params["margin"] == 0.222,
        f"fixture : le runtime démarre avec un seuil NON défaut, comme une commande initiale "
        f"({rt_ouv.params['corr_min']}, {rt_ouv.params['margin']})")

    rt_ouv.open()
    try:
        deco = rt_ouv._out.outlet.get_info().desc().child("decoding")
        corr_min_pub, margin_pub = deco.child_value("corr_min"), deco.child_value("margin")
        chk(corr_min_pub == "0.501" and margin_pub == "0.222",
            f"`_open` écrit dans les métadonnées LSL le seuil SOUMIS à la construction, pas le "
            f"défaut du décodeur ({corr_min_pub!r}, {margin_pub!r})")
    finally:
        rt_ouv.close()

    chk(rt_ouv._rest_until is None, "fixture : le repos n'a pas encore démarré")
    rt_ouv._rest_until = 0.0    # comme `tick` l'aurait posé — SPEC.rest.duration_s vaut 0 ici
    conclu = rt_ouv._rest_step(engine=None, now=0.0)
    chk(conclu and rt_ouv.rest_report is not None,
        f"fixture : ce repos NUL (cf. SPEC.rest.duration_s) conclut dès le premier pas ({conclu})")
    chk(rt_ouv.rest_report["corr_min"] == 0.501 and rt_ouv.rest_report["margin"] == 0.222,
        f"`_rest_step` rapporte le seuil SOUMIS à la construction, pas le défaut du décodeur "
        f"({rt_ouv.rest_report})")

    # =========================================================================================
    # Ce qui suit fait TOURNER le mode : un faux moteur, un tampon EEG horodaté, des marqueurs
    # d'horloge sur commande. Aucun casque, aucun flux LSL — `_out` est un faux publieur.
    # =========================================================================================
    from core.acquisition import UnicornAcquisition
    from core.cvep_decoder import synth_cvep

    class _FauxPublieur:
        """Même signature que `DecodedCVEPPublisher.push` (tâche 7, tour de correction 1 : les
        deux derniers arguments sont `corr_min`/`margin`, EXIGÉS comme chez le vrai publieur —
        un appel qui les omettrait doit lever ici aussi, pas être accepté en silence avec un
        défaut que le vrai publieur n'a pas."""

        def __init__(self):
            self.lignes = []

        def push(self, target_index, confidence, scores, corr_min, margin, lsl_ts=None):
            self.lignes.append((target_index, confidence, list(scores), corr_min, margin, lsl_ts))

    class _FauxMoteur:
        """Juste ce dont le runtime a besoin : un tampon EEG horodaté et une file de marqueurs.

        `markers_murs` rend un LOT à la fois, dans l'ordre fourni. La MATURITÉ elle-même
        (horodatage, curseur par mode, purge du tampon) est déjà prouvée côté `server.py`
        (`_smoke_marqueurs_murs`, `_smoke_marqueurs_file_coincee`) : ce fichier ne la
        réimplémente pas, il ne la rejoue donc pas. `post_s_recus` retient ce que le mode
        DEMANDE — pour une horloge, ce doit être 0 (cf. `_encaisser_marqueurs`).
        """

        def __init__(self, recent, recent_ts):
            self.acq = UnicornAcquisition(synthetic=True)
            self.instance = "selftest"
            self.recent = recent
            self.recent_ts = recent_ts
            self._lots = []
            self.post_s_recus = []

        def markers_murs(self, mode_id, post_s):
            self.post_s_recus.append(post_s)
            return self._lots.pop(0) if self._lots else []

    fs = 250.0
    # ⚠️ 262, pas 263 : 63 frames à 60 Hz font 262,5 échantillons à 250 Hz, et `round` en Python
    # arrondit au PAIR. Le modèle SOUS-compte donc d'un demi-échantillon par cycle — c'est la même
    # expression que `CVEPModel.n_cyc`, écrite ici pour que le tampon de test et le repliement du
    # décodeur tombent sur la même grille.
    n_cyc = int(round(63 * fs / 60.0))

    def _horloge(t0, k, refresh=60.0):
        """Le marqueur que l'émetteur publie au k-ième redémarrage du code.

        ⚠️ Placé sur l'horloge VRAIE (`k * code_len / refresh`), pas sur un multiple de `n_cyc`
        échantillons : un cycle dure 63/60 = 1,05 s = 262,5 échantillons, et `n_cyc` (262) n'en
        est que l'arrondi que le modèle utilise pour replier. Confondre les deux introduit un
        demi-échantillon de dérive par cycle.
        """
        return (float(t0) + k * 63.0 / refresh,
                {"mode": "cvep", "event": "cycle", "refresh": refresh})

    # --- 6. Les COMPTEURS PAR CAUSE (LE test de cette tâche, brief étape 1) -------------------
    # ⚠️ Les trois causes de « pas de décision » doivent être SÉPARÉES dans l'état. Une séance
    # casque coûte cher et ne se répète pas : « ça ne détecte pas » sans la cause ne permet pas
    # de distinguer une phase fausse d'un contact médiocre d'un étudiant qui ne fixe pas —
    # trois causes qui appellent trois gestes opposés.
    rng_c = np.random.default_rng(11)
    ts_c = 100.0 + np.arange(8 * n_cyc) / fs
    moteur_c = _FauxMoteur(rng_c.normal(0.0, 8.0, (len(ts_c), 8)), ts_c)
    t_fin_c = float(ts_c[-1])

    rt_c = _runtime_de_test(code_len=63, refresh=60.0)    # template PLAT : corrélations nulles
    rt_c._out = _FauxPublieur()
    rt_c._opened = True
    # ⚠️ Changé ICI, APRÈS la construction et AVANT le premier `_run_step` — donc AVANT que
    # `decide()` n'ait jamais tourné une seule fois (revue de la tâche 7, tour de correction 1) :
    # les trois premiers appels ci-dessous tombent tous sur le chemin `phase is None`
    # (`sans_reference`/`reference_perimee`), qui publie SANS jamais passer par `decide`. Un
    # opérateur qui tourne le seuil PENDANT que l'horloge est perdue est un scénario réaliste en
    # séance ; si `_publish` relisait `self.decodeur.corr_min`/`.margin` au lieu de
    # `self.params[...]`, il publierait le défaut de CONSTRUCTION du décodeur (0.26/0.09,
    # identique par coïncidence au défaut de `SPEC.params` — d'où des valeurs volontairement
    # DIFFÉRENTES ici) plutôt que ce changement, en silence.
    rt_c.params["corr_min"] = 0.501
    rt_c.params["margin"] = 0.222

    rt_c._run_step(moteur_c, lsl_ts=t_fin_c)              # (a) aucun marqueur jamais reçu
    rt_c._run_step(moteur_c, lsl_ts=t_fin_c)
    # (b) une référence trop VIEILLE : plus de CVEP_PEREMPTION_CYCLES cycles sans marqueur
    rt_c.maj_reference(ts=t_fin_c - CVEP_PEREMPTION_CYCLES * 63 / 60.0 - 1.0, refresh=60.0)
    rt_c._run_step(moteur_c, lsl_ts=t_fin_c)
    # (c) une référence FRAÎCHE, mais des corrélations qui ne tranchent pas
    rt_c.maj_reference(ts=t_fin_c - 0.5, refresh=60.0)
    for _ in range(3):
        rt_c._run_step(moteur_c, lsl_ts=t_fin_c)

    st = rt_c.state()
    chk(set(st) >= {"decodages", "sans_reference", "reference_perimee", "sous_les_seuils",
                    "vote_non_conclu", "age_reference_s", "corr_gagnant", "corr_second"},
        f"l'état sépare les causes de -1 et expose l'âge de la référence ({sorted(st)})")
    chk(st["sans_reference"] == 2 and st["reference_perimee"] == 1
        and st["sous_les_seuils"] == 3,
        f"...et chaque compteur compte SA cause, pas le total ({st})")
    chk(st["decodages"] == 0,
        f"aucune de ces six fenêtres n'a désigné de cible ({st['decodages']})")
    # ⚠️ `sous_les_seuils` et `vote_non_conclu` ne sont PAS le même refus, et c'est tout l'intérêt
    # de les avoir séparés : ici les corrélations elles-mêmes sont sous `corr_min`, donc aucune
    # fenêtre n'a jamais eu de candidat à soumettre au vote. Un `vote_non_conclu` non nul dirait
    # l'inverse — « le décodage passe les seuils mais les fenêtres se contredisent » — et
    # enverrait chercher un problème de stabilité de fixation là où il y a un problème de signal.
    chk(st["vote_non_conclu"] == 0,
        f"...et le VOTE n'est pas mis en cause : aucune fenêtre n'a passé les seuils, il n'a "
        f"jamais eu de candidat ({st['vote_non_conclu']})")
    # Chaque refus est PUBLIÉ, avec -1 : un client qui attend un échantillon par fenêtre ne doit
    # pas rester suspendu parce que le moteur ne sait pas où en est le code.
    chk(len(rt_c._out.lignes) == 6 and all(l[0] == -1 for l in rt_c._out.lignes),
        f"les six refus partent quand même sur le flux, en -1 ({rt_c._out.lignes})")
    # `lignes[0]` : le tout premier refus, publié AVANT que `decide()` n'ait jamais tourné (cf.
    # le commentaire à la construction de `rt_c` plus haut) — LA preuve que `_publish` lit
    # `self.params`, pas un `self.decodeur` qui n'aurait encore rien synchronisé.
    premiere = rt_c._out.lignes[0]
    chk(premiere[-3] == 0.501 and premiere[-2] == 0.222,
        f"`_publish` transporte le seuil VIVANT même sur une fenêtre qui n'est JAMAIS passée par "
        f"`decide` ({premiere})")
    # Et l'état affiché à la console (`output()`, écrasé à chaque publication) dit encore la même
    # chose à la FIN des six fenêtres — y compris après les trois qui, elles, ont bien traversé
    # `decide` : les deux sources ne doivent jamais pouvoir diverger.
    chk(rt_c.output()["corr_min"] == 0.501 and rt_c.output()["margin"] == 0.222,
        f"...et l'état affiché à la console dit la même chose ({rt_c.output()})")
    chk(abs(st["age_reference_s"] - 0.5) < 0.01,
        f"l'âge de la référence est celui de la DERNIÈRE fenêtre décidée ({st['age_reference_s']})")
    # `post_s = 0` : une horloge est utilisable dès que le tampon EEG a atteint son horodatage.
    # Attendre `marker_epoch_s` (2,1 s) après chaque marqueur mangerait les deux tiers des
    # 3,15 s de validité d'une référence, et le mode passerait son temps en `reference_perimee`.
    chk(set(moteur_c.post_s_recus) == {0.0},
        f"le mode réclame ses marqueurs SANS attendre de post-stimulus ({set(moteur_c.post_s_recus)})")

    # --- 7. LE test de BOUT EN BOUT (brief étape 5) : la chaîne entière, sans casque ----------
    # Un EEG synthétique portant le c-VEP de la cible 2, des marqueurs de cycle aux bons
    # instants, et le moteur doit désigner LA CIBLE 2. Le test de phase (tâche 5) dit que
    # l'horloge est juste ; celui-ci dit qu'elle est BRANCHÉE AU BON ENDROIT.
    #
    # ⚠️ Sa mutation est l'APPARIEMENT SCORE↔CIBLE : décaler d'un cran la table `lag_to_cmd` du
    # décodeur ne casse rien — le mode désigne juste la cible voisine, avec une confiance
    # normale. C'est exactement le défaut que la revue du P300 avait trouvé sur son propre mode.
    plan, code = build_targets()
    lags = [c["lag"] for c in plan]
    cible = 2
    lag_vrai = plan[cible]["lag"]
    rng_e = np.random.default_rng(7)

    modele_appris = CVEPModel(fs=fs, refresh=60.0, code_len=len(code), channels=CVEP_CHANNELS)
    modele_appris.fit([synth_cvep(code, l, len(CVEP_CHANNELS), fs, 60.0, -6.0, rng_e)
                       for l in lags for _ in range(6)],
                      [l for l in lags for _ in range(6)])

    def _tampon_synthetique(lag, n_cycles, snr_db):
        """`n_cycles` cycles consécutifs de c-VEP pour ce lag, sur les VOIES du modèle.

        Les quatre autres voies portent du bruit : le mode doit prélever `model.channels` dans
        le tampon à 8 voies du moteur, pas les quatre premières colonnes venues.
        """
        bloc = rng_e.normal(0.0, 1.0, (n_cycles * n_cyc, 8))
        for k in range(n_cycles):
            bloc[k * n_cyc:(k + 1) * n_cyc, CVEP_CHANNELS] = synth_cvep(
                code, lag, len(CVEP_CHANNELS), fs, 60.0, snr_db, rng_e)
        return bloc

    n_cycles_buf = 6

    def _moteur_sur(lag, snr_db=0.0):
        """Un faux moteur dont le tampon porte `n_cycles_buf` cycles du c-VEP de CE lag, et dont
        la file rend les marqueurs d'horloge correspondants.

        `snr_db` est réglable pour la section 8ter, qui a besoin de fenêtres FRANCHES et de
        fenêtres FAIBLES de la même cible : c'est le seul moyen d'encadrer un seuil par deux
        corrélations réelles, plutôt que d'en écrire une à la main dans la file de votes.
        """
        eeg = _tampon_synthetique(lag, n_cycles_buf, snr_db=snr_db)
        ts = 500.0 + np.arange(len(eeg)) / fs
        m = _FauxMoteur(eeg, ts)
        m._lots = [[_horloge(ts[0], k) for k in range(n_cycles_buf)]]
        return m

    moteur_e = _moteur_sur(lag_vrai)
    ts_e = moteur_e.recent_ts
    rt_e = _runtime_de_test(modele=modele_appris)
    rt_e._out = _FauxPublieur()
    rt_e._opened = True

    # ⚠️ `CVEP_MIN_VOTES` fenêtres, pas une : le vote glissant est DANS la chaîne, et le tester
    # avec une seule fenêtre prouverait le décodage sans jamais prouver le vote. La boucle décode
    # la même fenêtre glissante à ~5 Hz, exactement ce que la boucle du moteur fait en séance.
    for _ in range(CVEP_MIN_VOTES):
        rt_e._run_step(moteur_e, lsl_ts=float(ts_e[-1]))
    publie = rt_e.output()

    chk(publie is not None and publie["target_index"] == cible,
        f"le moteur désigne la cible RÉELLEMENT affichée "
        f"({None if publie is None else publie['target_index']} au lieu de {cible}) — la phase "
        f"est juste ET branchée au bon endroit")
    chk(publie is not None and publie["scores"][cible] == max(publie["scores"]),
        f"...et c'est bien elle qui porte la meilleure corrélation "
        f"({None if publie is None else publie['scores']})")
    # ⚠️ Le FLUX et l'écran ne doivent pas se contredire — mais le flux porte la pleine
    # précision, l'écran arrondit au millième (`_publish`). On compare donc les scores publiés
    # ARRONDIS de la même façon : exiger l'égalité stricte reviendrait à demander au contrat
    # public de s'aligner sur un confort d'affichage.
    chk(rt_e._out.lignes and rt_e._out.lignes[-1][0] == cible
        and [round(s, 3) for s in rt_e._out.lignes[-1][2]] == publie["scores"],
        f"...et c'est CE que le flux publie, pas seulement ce que l'écran montre "
        f"({rt_e._out.lignes[-1] if rt_e._out.lignes else None})")
    st_e = rt_e.state()
    chk(st_e["decodages"] == 1 and st_e["sous_les_seuils"] == 0,
        f"la dernière fenêtre est comptée comme un décodage, pas comme un refus ({st_e})")
    # Les fenêtres qui ont précédé la conclusion du vote sont comptées comme telles, et publiées
    # en -1 : ce n'est PAS un défaut de signal, c'est le vote qui remplit sa file.
    chk(st_e["vote_non_conclu"] == CVEP_MIN_VOTES - 1
        and [l[0] for l in rt_e._out.lignes] == [-1] * (CVEP_MIN_VOTES - 1) + [cible],
        f"...et les {CVEP_MIN_VOTES - 1} qui l'ont précédée sont des « vote non conclu », "
        f"publiées en -1 ({st_e['vote_non_conclu']}, {[l[0] for l in rt_e._out.lignes]})")

    # --- 7bis. Les SEUILS se règlent EN PLEINE SÉANCE (LE test de cette tâche, brief étape 1) ---
    # ⚠️ C'est la garde que l'ErrP N'A PAS : chez lui, changer `tnr_target` reconstruit le
    # runtime, détruit et recrée le flux, et relance 23 s de chauffe (mesuré). Le récepteur ouvert
    # devient muet, et l'opérateur lit ça comme une panne — en séance, ça se paie en minutes de
    # casque à chaque essai de réglage. Ici, `corr_min` et `margin` sont relus DANS `self.params`
    # à CHAQUE décision — jamais mis en cache dans `__init__` — ce qui permet de les tourner sans
    # réabonner personne ni refaire la chauffe. `decide` est la méthode qui porte cette garantie
    # (`_run_step` s'y ramène, cf. plus bas).
    p = {p.key for p in SPEC.params if not p.affecte_decodage}
    chk({"corr_min", "margin"} <= p,
        f"les deux seuils sont déclarés SANS reconstruction du runtime ({sorted(p)})")

    # Le template PLAT de `_runtime_de_test()` par défaut ne conviendrait pas ici (corrélations
    # nulles quel que soit le seuil) : on reprend `modele_appris` et une fenêtre synthétique de
    # la MÊME forme que celle du bout en bout, sur `rt_e` déjà construit avec ce modèle.
    # `[:, model.channels]` : comme `_fenetre(engine)` en production, `decide` attend une fenêtre
    # DÉJÀ réduite aux voies du modèle (4 ici), pas le tampon complet à 8 voies du faux moteur.
    fenetre_seuils = _tampon_synthetique(lag_vrai, n_cycles_buf, snr_db=0.0)[:, modele_appris.channels]
    rt_e.params["corr_min"] = 0.99          # personne ne passe ce seuil
    cmd_a, _ = rt_e.decide(fenetre_seuils, 0)
    rt_e.params["corr_min"] = 0.01          # tout le monde le passe
    cmd_b, _ = rt_e.decide(fenetre_seuils, 0)
    chk(cmd_a is None and cmd_b is not None,
        "changer le seuil change la décision SUR LA MÊME fenêtre, sans rien reconstruire")

    # --- 7ter. La MÊME chaîne, avec l'AUTRE décodeur ------------------------------------------
    # ⚠️ `_DECODEURS["rCCA"]` est devenu un chemin de PRODUCTION pendant ce chantier :
    # `cvep_calibrate.calibrate()` écrit un `cvep_rcca_model_<horodatage>.npz` à CHAQUE
    # calibration, `cvep_models.charger` l'accepte dès que ses codes sont ceux du stimulus du
    # jour, et la liste étant triée par date, c'est le défaut proposé juste après une calibration
    # — une chance sur deux, selon lequel des deux `save()` a la mtime la plus haute. Or aucun
    # test du dépôt ne construisait de `CVEPRuntime` sur un `RCCAModel` : la colle de niveau MODE
    # (`.corr_min`/`.margin`/`.n_cycles` posés sur `RCCADecoder`, `model.n_cyc`, `model.channels`,
    # `model.code_len`, `model.refresh`, `cv_`) n'avait JAMAIS tourné, ni ici ni au casque, sur le
    # chemin qu'un étudiant prend par défaut. Ce bloc la fait tourner une fois, de bout en bout.
    from core.cvep_rcca import RCCAModel

    codes_du_plan = np.stack([np.asarray(c["code"], dtype=int) for c in plan])
    rcca = RCCAModel(codes_du_plan, fs=fs, refresh=60.0, channels=list(CVEP_CHANNELS))
    rcca.fit([synth_cvep(code, l, len(CVEP_CHANNELS), fs, 60.0, -6.0, rng_e)
              for l in lags for _ in range(6)],
             [i for i in range(len(plan)) for _ in range(6)], compute_cv=False)
    rcca.cv_ = 0.5
    rt_r = _runtime_de_test(modele=rcca)
    chk(rt_r.model.decoder == "rCCA" and type(rt_r.decodeur).__name__ == "RCCADecoder",
        f"le décodeur suit le MODÈLE, pas un réglage — et le chemin rCCA traverse `charger` "
        f"comme en production ({rt_r.model.decoder}, {type(rt_r.decodeur).__name__})")
    rt_r._out, rt_r._opened = _FauxPublieur(), True
    moteur_r = _moteur_sur(lag_vrai)
    for _ in range(CVEP_MIN_VOTES):
        rt_r._run_step(moteur_r, lsl_ts=float(moteur_r.recent_ts[-1]))
    sortie_r = rt_r.output()
    chk(sortie_r is not None and len(sortie_r["scores"]) == len(plan)
        and sortie_r["scores"][cible] == max(sortie_r["scores"]),
        f"...et la chaîne entière tourne avec lui : phase, fenêtre réduite aux voies du modèle, "
        f"seuils, appariement score↔cible ({sortie_r})")
    chk(sortie_r["target_index"] == cible and rt_r.state()["decodages"] == 1,
        f"...jusqu'à la décision publiée, aux seuils RÉGLÉS du mode (pas ceux de construction du "
        f"RCCADecoder, cf. `decide`) ({sortie_r['target_index']}, {rt_r.state()})")

    # --- 8. LE VOTE : une seule fenêtre ne décide pas, et deux qui se contredisent non plus ----
    # C'est ce que `CVEP_VOTE_LEN`/`CVEP_MIN_VOTES` achètent, et c'est exactement ce que l'écran
    # pygame que ce chantier archive faisait déjà. Sans ce test, le vote pourrait être câblé à
    # `min_votes=1` sans que rien ne rougisse — le moteur serait alors plus permissif que la
    # référence à laquelle la séance casque doit le comparer.
    rt_v = _runtime_de_test(modele=modele_appris)
    rt_v._out = _FauxPublieur()
    rt_v._opened = True
    rt_v._run_step(_moteur_sur(lag_vrai), lsl_ts=float(ts_e[-1]))
    chk(rt_v.output()["target_index"] == -1 and rt_v.state()["vote_non_conclu"] == 1,
        f"une SEULE fenêtre, même franche, ne suffit pas à émettre ({rt_v.output()}) ")
    chk(rt_v.state()["corr_gagnant"] is not None and rt_v.state()["corr_gagnant"] >= 0.26,
        f"...et pourtant elle a bien passé les seuils : c'est le VOTE qui retient, pas le signal "
        f"({rt_v.state()['corr_gagnant']})")

    # `CVEP_MIN_VOTES` fenêtres FRANCHES mais qui désignent des cibles DIFFÉRENTES : le vote ne
    # conclut pas davantage. C'est ce qui distingue un vote à MAJORITÉ d'un simple compte : un
    # `compte` calculé sur la LONGUEUR de la file plutôt que sur la cible la plus représentée
    # (`len(self._votes) >= min_votes`, la simplification qu'on écrit sans y penser) publierait
    # ici une cible — dont une seule des deux serait la bonne, avec une confiance normale.
    rt_d = _runtime_de_test(modele=modele_appris)
    rt_d._out = _FauxPublieur()
    rt_d._opened = True
    lags_contradictoires = [plan[(cible + k) % len(plan)]["lag"] for k in range(CVEP_MIN_VOTES)]
    chk(len(set(lags_contradictoires)) == CVEP_MIN_VOTES,
        f"fixture : ces {CVEP_MIN_VOTES} fenêtres désignent VRAIMENT des cibles distinctes")
    for lag in lags_contradictoires:
        rt_d._run_step(_moteur_sur(lag), lsl_ts=float(ts_e[-1]))
    chk(all(l[0] == -1 for l in rt_d._out.lignes) and rt_d.state()["decodages"] == 0
        and rt_d.state()["sous_les_seuils"] == 0,
        f"des fenêtres franches qui se CONTREDISENT n'émettent rien non plus, et ce n'est pas "
        f"le SIGNAL qui est mis en cause ({[l[0] for l in rt_d._out.lignes]}, {rt_d.state()})")
    chk(rt_d.state()["vote_non_conclu"] == CVEP_MIN_VOTES,
        f"...c'est bien le VOTE, et il le dit ({rt_d.state()['vote_non_conclu']})")

    # --- 8ter. Tourner un seuil EN SÉANCE ne peut pas produire un échantillon qui SE CONTREDIT --
    # ⚠️ `DecodedCVEPPublisher` promet, sur ses propres voies, que « `confidence` est toujours
    # `>= corr_min` quand `target_index >= 0` », et `cvep_channel_labels` invite explicitement le
    # client à refiltrer là-dessus. Or `confidence` est la MOYENNE des corrélations des fenêtres
    # votantes, chacune jugée contre le seuil en vigueur AU MOMENT où elle a voté — et ce mode
    # est le premier du produit dont le seuil se tourne sans reconstruire le runtime. Sans le
    # vidage de la file au changement de couple (`_run_step`), un échantillon annonce donc une
    # confiance SOUS le `corr_min` qu'il porte lui-même : le client jette une fixation stable, et
    # un enregistrement dépouillé plus tard porte une ligne auto-contradictoire.
    #
    # Le seuil n'est pas choisi à la main : il est posé ENTRE deux corrélations RÉELLES — celle
    # que produirait le mélange (votes faibles + fenêtre franche) et celle de la fenêtre franche
    # seule. C'est exactement la plage où l'échantillon se contredirait.
    rt_s = _runtime_de_test(modele=modele_appris, overrides={"corr_min": 0.02, "margin": 0.0})
    rt_s._out, rt_s._opened = _FauxPublieur(), True
    for _ in range(CVEP_MIN_VOTES - 1):
        rt_s._run_step(_moteur_sur(lag_vrai, snr_db=-6.0), lsl_ts=float(ts_e[-1]))
    faibles = [c for _n, c in rt_s._votes]
    chk(len(faibles) == CVEP_MIN_VOTES - 1
        and all(n == plan[cible]["name"] for n, _c in rt_s._votes),
        f"fixture : {CVEP_MIN_VOTES - 1} fenêtres FAIBLES ont voté pour la bonne cible sous un "
        f"seuil permissif ({[(n, round(c, 3)) for n, c in rt_s._votes]})")

    moteur_franc = _moteur_sur(lag_vrai, snr_db=12.0)
    t_franc = float(moteur_franc.recent_ts[-1])
    rt_s._encaisser_marqueurs(moteur_franc)          # l'horloge d'abord, comme `_run_step`
    _c, nommes_franc = rt_s.decide(rt_s._fenetre(moteur_franc), rt_s.phase_a(t_franc))
    rho_franc = float(nommes_franc[plan[cible]["name"]])
    melange = (sum(faibles) + rho_franc) / (len(faibles) + 1)
    seuil_chaud = (melange + rho_franc) / 2.0
    chk(melange < seuil_chaud < rho_franc,
        f"fixture : le nouveau seuil sépare VRAIMENT la moyenne mélangée ({melange:.3f}) de la "
        f"corrélation de la fenêtre franche ({rho_franc:.3f}) — {seuil_chaud:.3f}")

    rt_s.params["corr_min"] = seuil_chaud            # l'opérateur resserre EN PLEINE SÉANCE
    rt_s._run_step(moteur_franc, lsl_ts=t_franc)
    # `l = (target_index, confidence, scores, corr_min, margin, lsl_ts)` — cf. `_FauxPublieur`.
    fautives = [l for l in rt_s._out.lignes if l[0] >= 0 and l[1] < l[3]]
    chk(not fautives,
        f"AUCUN échantillon décidé ne porte une confiance SOUS le `corr_min` qu'il annonce "
        f"lui-même, même après un réglage à chaud ({fautives})")

    # ...et le mode n'est pas pour autant coincé : la file se remplit à nouveau au NOUVEAU couple,
    # et la décision qui en sort porte ce couple-là. Le vidage coûte `vote_len - 1` fenêtres.
    for _ in range(CVEP_MIN_VOTES):
        rt_s._run_step(_moteur_sur(lag_vrai, snr_db=12.0), lsl_ts=float(ts_e[-1]))
    derniere = rt_s._out.lignes[-1]
    chk(derniere[0] == cible and derniere[3] == seuil_chaud and derniere[1] >= derniere[3],
        f"...et la décision d'après porte le couple sous lequel elle a été prise, avec une "
        f"confiance au-dessus ({derniere})")

    # --- 9. L'horloge tourne PENDANT LA CHAUFFE, et « refaire le repos » l'oublie --------------
    # Deux comportements qu'aucune assertion ne couvrait, et deux pannes différentes.
    rt_w = _runtime_de_test(modele=modele_appris)
    rt_w._out = _FauxPublieur()
    rt_w._opened = True
    moteur_w = _moteur_sur(lag_vrai)
    rt_w.begin_rest(now=0.0, warmup_s=10.0, duration_s=0.0)
    chk(rt_w.phase == "warmup", f"le mode commence par la chauffe ({rt_w.phase})")
    rt_w.tick(moteur_w, lsl_ts=float(moteur_w.recent_ts[-1]), now=1.0)
    # ⚠️ Sans le `tick` redéfini, `markers_murs` n'est PAS appelée de toute la chauffe : le
    # curseur du moteur ne bouge pas, puis le premier `_run_step` avale l'arriéré — dont tous les
    # marqueurs déjà sortis du tampon EEG, comptés en `engine.marqueurs_perdus`, un compteur qui
    # signale une VRAIE perte de données. Une alarme fausse à chaque démarrage apprend à ignorer
    # l'alarme.
    chk(moteur_w.post_s_recus and rt_w._ref_ts is not None,
        f"pendant la CHAUFFE, l'horloge est encaissée : le curseur du moteur avance et la phase "
        f"est déjà fraîche quand le décodage commence ({moteur_w.post_s_recus}, {rt_w._ref_ts})")
    chk(rt_w.phase == "warmup",
        f"...sans que la chauffe soit écourtée pour autant ({rt_w.phase})")

    # « Refaire le repos » se fait en touchant les électrodes : l'émetteur a eu tout le temps
    # d'être relancé, ou d'avoir dérivé. Garder l'ancienne référence ferait décoder sur une
    # horloge qui n'a plus cours, en publiant des corrélations d'apparence normale.
    rt_w.begin_rest(now=100.0, warmup_s=0.0, duration_s=0.0)
    chk(rt_w._ref_ts is None and rt_w.phase_a(float(moteur_w.recent_ts[-1])) is None,
        f"« refaire le repos » OUBLIE la référence de phase — sinon le mode déciderait sur une "
        f"horloge périmée ({rt_w._ref_ts})")
    chk(rt_w.state()["sans_reference"] == 0 and rt_w.state()["decodages"] == 0,
        f"...et les compteurs repartent de zéro avec elle ({rt_w.state()})")

    # ⚠️ Et la FILE DE VOTES part avec, ce qui est le même défaut que celui juste au-dessus, sur
    # l'état que le vote glissant vient d'ajouter. Le scénario tient en trois lignes : une fenêtre
    # franche AVANT le repos laisse un vote dans la file ; si « refaire le repos » ne la vide pas,
    # UNE SEULE fenêtre neuve suffit ensuite à atteindre `min_votes` — le mode émet une cible en
    # s'appuyant sur des votes qui décrivent un montage qu'on vient de démonter, avec une
    # confiance parfaitement normale.
    #
    # L'assertion porte sur le COMPORTEMENT (« une fenêtre seule n'émet toujours pas »), pas sur
    # `len(rt._votes)` : une file vidée par un autre chemin, ou un vote qui cesserait de lire sa
    # file, laisserait passer un test écrit sur l'attribut.
    rt_p = _runtime_de_test(modele=modele_appris)
    rt_p._out = _FauxPublieur()
    rt_p._opened = True
    rt_p._run_step(_moteur_sur(lag_vrai), lsl_ts=float(ts_e[-1]))   # 1er vote, avant le repos
    chk(rt_p.output()["target_index"] == -1 and len(rt_p._votes) == 1,
        f"fixture : la fenêtre d'avant le repos a bien laissé UN vote dans la file "
        f"({len(rt_p._votes)})")
    rt_p.begin_rest(now=0.0, warmup_s=0.0, duration_s=0.0)
    rt_p._run_step(_moteur_sur(lag_vrai), lsl_ts=float(ts_e[-1]))   # 1re fenêtre d'APRÈS
    chk(rt_p.output()["target_index"] == -1
        and rt_p.state()["vote_non_conclu"] == 1 and rt_p.state()["decodages"] == 0,
        f"...et « refaire le repos » VIDE la file de votes : la première fenêtre d'après ne peut "
        f"pas émettre en s'appuyant sur des votes d'avant ({rt_p.output()}, {rt_p.state()})")

    # --- 9bis. La PERTE D'HORLOGE vide la file EXACTEMENT DE MÊME ------------------------------
    # ⚠️ Le raisonnement de « refaire le repos » s'applique mot pour mot ici, et ce chemin-là est
    # le PLUS FRÉQUENT des deux : on relance l'émetteur plusieurs fois par séance (fenêtre pygame
    # fermée, second terminal coupé, plantage), on refait le repos une ou deux fois. Rien ne borne
    # la coupure dans le temps — une seconde ou dix minutes — et la file, elle, était GELÉE
    # pendant toute sa durée. Une référence périmée rend ses votes périmés par construction : la
    # première fenêtre d'après le retour de l'émetteur atteignait `min_votes` sur des votes
    # arbitrairement vieux et publiait une cible franche, indiscernable sur le flux d'une
    # sélection stable (indice valide, confiance au-dessus de `corr_min`, scores plausibles).
    rt_h = _runtime_de_test(modele=modele_appris)
    rt_h._out = _FauxPublieur()
    rt_h._opened = True
    moteur_h = _moteur_sur(lag_vrai)
    t_h = float(moteur_h.recent_ts[-1])
    rt_h._run_step(moteur_h, lsl_ts=t_h)          # (1) horloge vivante : un vote est empilé
    chk(rt_h.output()["target_index"] == -1 and len(rt_h._votes) == 1,
        f"fixture : la fenêtre d'avant la coupure a laissé UN vote dans la file "
        f"({len(rt_h._votes)})")
    # (2) l'émetteur SE TAIT : plus aucun marqueur (le lot a été consommé au pas précédent) et la
    #     référence vieillit au-delà de la péremption.
    rt_h._ref_ts = t_h - CVEP_PEREMPTION_CYCLES * 63 / 60.0 - 1.0
    rt_h._run_step(moteur_h, lsl_ts=t_h)
    chk(rt_h.state()["reference_perimee"] == 1,
        f"fixture : cette fenêtre-là est bien refusée pour cause d'HORLOGE "
        f"({rt_h.state()['reference_perimee']})")
    # (3) l'émetteur revient. UNE seule fenêtre franche ne peut pas suffire.
    moteur_h._lots = [[_horloge(float(moteur_h.recent_ts[0]), k) for k in range(n_cycles_buf)]]
    rt_h._run_step(moteur_h, lsl_ts=t_h)
    chk(rt_h.output()["target_index"] == -1 and rt_h.state()["decodages"] == 0
        and rt_h.state()["vote_non_conclu"] == 2,
        f"...une fenêtre non décodable pour raison d'HORLOGE vide la file : la première fenêtre "
        f"d'après le retour de l'émetteur ne peut pas conclure sur des votes d'avant la coupure "
        f"({rt_h.output()}, {rt_h.state()})")

    print(f"[cvep] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
