"""Stimulus SSVEP — les disques clignotants, et le run GUIDÉ qui permet de le MESURER.

⚠️ **TROIS cibles par défaut, quatre au maximum.** Ce fichier a annoncé « 4 flèches » jusqu'au
2026-09-09, dans sa docstring, dans son `--help` et dans le briefing de la mesure, alors que
`choose_frequencies` en rendait TROIS (AVANT, GAUCHE, DROITE). Le nombre vient du PLAN et de nulle
part ailleurs : quelqu'un qui s'assoit 3,6 minutes devant cet écran ne doit pas y chercher une
cible qui n'existe pas. Depuis le 2026-09-21, `--freqs` décide de ce plan — donc le nombre de
cibles est la LONGUEUR de la liste, entre 2 et 4. Quatre est la borne de la GÉOMÉTRIE (elle a
quatre places), pas celle du moteur, qui accepte jusqu'à 8 cibles.

**Des DISQUES, plus des flèches** (2026-10-02, demandé au QA : « des cibles rondes, comme pour les
autres modes »). Mêmes places qu'avant, même clignotement image par image. Le disque est un peu
PLUS grand que la flèche qu'il remplace (`RAYON_RATIO`) : une cible SSVEP plus petite donne une
réponse plus faible, et `--smoke` compte sa surface dans les pixels. La consigne est un cercle
BLEU à `CUE_MARGE_PX` du bord, comme au P300 ; l'anneau de retour suit la règle commune
(`stimulus/retour.py:rayon_anneau`). Les flèches ne vivent plus que dans `archive/ui.py`, pour les
écrans archivés. Au centre de chaque disque, à chaque image, le point de fixation ROUGE du c-VEP
et du P300 (`FIX_DOT`, QA 1.17.1) : les sondes de `--smoke` lisent donc l'état ON/OFF à mi-rayon.

⚠️ **Aucun texte sur une cible** (2026-10-02). Le titre du guidé était posé à 10 % de la hauteur,
PAR-DESSUS le haut du disque AVANT pendant qu'il clignotait : un texte sur une cible change sa
luminance moyenne, donc la réponse SSVEP mesurée. Les textes vont dans une bande libre calculée
depuis `geometrie` (`mise_en_page`) ; `--smoke` (section K) relit, à quatre résolutions, le
rectangle de chaque texte posé et les pixels de la zone de chaque anneau.

🔴 **`--freqs`, et pourquoi il a manqué.** Jusqu'au 2026-09-21 cette fenêtre affichait le jeu du
DÉPÔT quoi qu'on règle dans la console : un étudiant qui pose 12 · 15 · 20 voyait clignoter
15 · 20 · 8,571, et le moteur corrélait contre des sinusoïdes que PERSONNE n'affichait. Rien ne
lève, rien ne compte, le mode ne détecte simplement plus rien — la panne caractéristique de ce
produit. Trouvé en séance casque, pas par un test.

⚠️ Et le corollaire, qui compte autant : une fréquence qui ne divise pas le rafraîchissement est
**REFUSÉE**, jamais arrondie en silence. `choose_frequencies` ajuste `frames_per_cycle` sans rien
dire — une valeur impossible deviendrait donc une AUTRE fréquence, affichée sans prévenir, pendant
que le moteur corrèle sur celle qu'on lui a demandée. La règle du refus n'est pas réécrite ici :
c'est celle du moteur (`core/modes/contract.py`, contrainte `divise_le_refresh`), APPELÉE.

Brique « affichage » du produit. **Ce programme n'ouvre PAS le casque** : il ne fait que présenter
les stimuli visuels et, en mode guidé, publier des marqueurs. C'est ce qui lui permet de tourner
EN MÊME TEMPS que le moteur, dans deux processus — le même montage que le P300, l'ErrP et le c-VEP.

⚠️ **Ce fichier vivait dans `src/research/`** (`ssvep_stimulus.py`) et n'était lançable qu'à la
main. Il a déménagé ici le 2026-09-09 : afficher un stimulus est de l'USAGE RÉEL, et l'usage réel
se pilote depuis la console. La règle est vérifiée par `python src/core/server.py --smoke`.

Pourquoi « comptage de frames » et pas un timer ?
  Un stimulus SSVEP doit clignoter à une fréquence STABLE. Si on se base sur l'horloge,
  on rate/duplique des frames et la fréquence jitter -> le pic SSVEP s'étale et devient
  indétectable. On impose donc que chaque fréquence soit un DIVISEUR ENTIER du
  rafraîchissement écran : à 60 Hz, une cible « ON k frames / OFF k frames » clignote
  exactement à 60/(2k) Hz. C'est à la fois « affichable » (pas de jitter) et
  « détectable » (dans la bande 8-15 Hz où le SSVEP occipital répond le mieux).

--- Le mode GUIDÉ (`--guide`) ------------------------------------------------------------------

Le décodage libre ne dit pas si le moteur a RAISON : personne ne sait où le regard se pose. Le run
guidé le dit, parce qu'il DÉSIGNE la cible à fixer et publie cette vérité-terrain. C'est la moitié
« stimulus » de l'ancien `research/ssvep_guided.py` ; sa moitié « acquisition et décision » est
montée dans le moteur (`src/core/modes/ssvep_mesure.py`), et sa moitié « analyse d'un run archivé »
est restée au banc d'essai.

Protocole publié sur le flux `MARKER_STREAM_DEFAULT` (core/config.py), type "Markers", 1 voie
"string", cadence irrégulière — quatre événements, dans cet ordre :

    {"mode": "ssvep", "event": "calib_start", "trials": 36,
     "freqs": [15.0, 20.0, 8.571], "refresh_hz": 60.0}   # la séance s'ouvre
    {"mode": "ssvep", "event": "repos"}                   # plancher de repos : ne fixe RIEN
    {"mode": "ssvep", "event": "cue", "target": 1, "freq_hz": 20.0}   # la FIXATION commence
    {"mode": "ssvep", "event": "calib_end"}               # la séance est finie -> le moteur mesure

⚠️ **Le `cue` part au premier flip de la FIXATION**, pas au début de la consigne. L'instant qui
compte pour le moteur est celui où le regard est DÉJÀ posé sur la cible : les `SSVEP_GUIDE_CUE_S`
secondes de saccade qui précèdent ne contiennent pas de réponse SSVEP établie, et le moteur, qui
prélève sa fenêtre `SSVEP_GUIDE_FIX_S` secondes APRÈS ce marqueur, tomberait à côté.

⚠️ **Les trois marqueurs `calib_*` portent le même vocabulaire que les trois fenêtres sœurs**
(`p300.py`, `errp.py`, `cvep.py`) alors que ce n'est pas une calibration : rien n'est entraîné, le
moteur rend un VERDICT. Le vocabulaire est partagé parce que le TUYAU l'est — `markers_murs`,
l'inlet, le mûrissement — et qu'un cinquième vocabulaire pour le même tuyau se paierait en
divergences.

⚠️ **Une séance interrompue (ESC, `--seconds`) ne publie PAS de `calib_end`.** Le moteur ne rendra
donc aucun verdict, et le dira. Un taux calculé sur une séance tronquée serait indiscernable d'un
taux complet, et c'est le chiffre entier qu'on irait ensuite citer.

⚠️ **L'ORDRE DES ESSAIS est entrelacé et tiré au sort, et c'est un INVARIANT** — cf. `_schedule`.

--- Les frames SAUTÉES ---------------------------------------------------------------------------

⚠️ **Une image figée n'est pas un ralentissement : c'est une cible qui CESSE de clignoter.** Pendant
la durée d'une frame sautée, la cible n'émet plus à la fréquence annoncée, donc la réponse SSVEP
cherchée n'existe plus — et le moteur, lui, continue de corréler. Observé en séance le 2026-09-21
(« périodiquement, l'image se figeait ») : rien n'a levé, rien n'a compté, et le verdict de la
mesure n'en savait rien. Le compteur `sautees` est celui de `stimulus/cvep.py`, à l'identique :
même seuil, même façon de mesurer l'écart entre deux flips, et la même honnêteté — **le compte est
AFFICHÉ, jamais corrigé**. Il tourne dans les DEUX modes, s'affiche au HUD en direct, et
`bilan_de_seance` l'imprime en fin de séance.

--- Le RETOUR (`--retour`) ------------------------------------------------------------------------

La fenêtre lit `decoded_ssvep` comme l'application d'un étudiant, en tâche de fond, et entoure le
disque décodé d'un anneau (`stimulus/retour.py` porte la règle, et sa TAILLE : `rayon_anneau`, la
même qu'au P300 et au c-VEP). L'anneau passe au-delà du cercle de consigne, dans le noir : il ne
touche aucun pixel que les sondes de `--smoke` relisent. Il est VERT, en libre comme en `--guide` :
il montre la cible décodée, il ne juge pas. En libre (sans `--guide`) il suit la dernière décision. En
`--guide`, la décision d'un essai arrive pendant le retour à la croix, et l'anneau s'éteint au
début de la CONSIGNE suivante — soit
`SSVEP_GUIDE_CUE_S` avant la fixation, dont le moteur ne lit que la fin. L'essai se ferme
`MARGE_DECISION_S` AVANT la fin de la fixation : le moteur décide à la fin exacte, et une décision
arrivée avant la fermeture serait perdue (revue C-M4). Sans `--guide`, cette fenêtre n'affiche
déjà que ses cibles : elle n'a pas besoin d'un `--libre` — mais tant que le moteur chauffe ou
mesure son plancher (son flux `status`), elle montre la croix et l'écran de REPOS du guidé : le
plancher se mesure AVEC le clignotement, sans fixer aucune cible.

Lancer :
    python src/stimulus/ssvep.py                 # plein écran, ESC pour quitter
    python src/stimulus/ssvep.py --retour        # ESSAYER LIBREMENT : l'anneau dit ce que le
                                                 # moteur décode (lancé par la console)
    python src/stimulus/ssvep.py --windowed      # fenêtre 1000x700 (dev)
    python src/stimulus/ssvep.py --refresh 60    # forcer le refresh (sinon auto-mesuré)
    python src/stimulus/ssvep.py --seconds 20    # auto-quit après 20 s
    python src/stimulus/ssvep.py --freqs 12,15,20     # LES FRÉQUENCES DU MODE, dans cet ordre —
                                                      # c'est ce que la console passe elle-même
    python src/stimulus/ssvep.py --freqs 10,12,15,20  # quatre cibles (la géométrie en a quatre)
    python src/stimulus/ssvep.py --guide         # le run GUIDÉ (la console le lance elle-même)
    python src/stimulus/ssvep.py --guide --trials 6   # plus court (6 essais par cible)
    python src/stimulus/ssvep.py --guide --seed 5     # rejouer le MÊME ordre d'essais
    python src/stimulus/ssvep.py --smoke         # test sans écran (CI), n'affiche rien

Sortie : 0 si tout s'est déroulé, 1 si une séance guidée a été INTERROMPUE, **2 si les fréquences
demandées ont été refusées** — rien n'a alors été affiché. La console lance cette fenêtre : « elle
a refusé de s'ouvrir » et « elle s'est arrêtée en route » ne doivent pas se confondre.
"""

import argparse
import json
import os
import sys
import time
from collections import namedtuple

# Permet `from core.config import ...` que le module soit lancé via `python src/stimulus/ssvep.py`
# ou importé comme `stimulus.ssvep`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402

from core.config import (COMMANDS, MARKER_STREAM_DEFAULT,  # noqa: E402
                         SSVEP_GUIDE_CUE_S, SSVEP_GUIDE_FIX_S, SSVEP_GUIDE_GAP_S,
                         SSVEP_GUIDE_REPOS_S, SSVEP_GUIDE_TRIALS_PER_TARGET, SSVEP_WARMUP_S,
                         choose_frequencies, use_utf8_console)
from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, local_clock  # noqa: E402

# --- Réglages d'affichage (les fréquences/commandes viennent de config.py) --

BG = (0, 0, 0)          # fond noir -> contraste ON/OFF maximal (meilleur SSVEP)
ON_COLOR = (255, 255, 255)
OUTLINE = (55, 55, 70)  # contour statique : garde le repère spatial quand le disque est OFF
LABEL = (120, 120, 140)
HUD = (70, 90, 70)

# Le mode guidé, en plus.
FG = (225, 225, 235)
DIM = (110, 110, 130)
# ⚠️ La couleur de DÉSIGNATION, et elle n'est utilisée NULLE PART AILLEURS dans ce fichier — ni
# pour un titre, ni pour un sous-titre, ni pour un décor. C'est ce qui permet à `--smoke` de LIRE
# dans les pixels quelle cible l'écran désigne (cf. `_cible_designee_a_l_ecran`) : un second
# cercle de ce bleu serait pris pour une seconde désignation.
CUE = (60, 130, 255)
# Le cercle de consigne, comme au P300 : son bord extérieur à `CUE_MARGE_PX` du disque, tracé vers
# l'intérieur sur `CUE_EPAISSEUR_PX` — il reste 4 px de noir entre les deux, et le disque garde
# toute sa surface clignotante (l'ancien liseré, posé SUR le bord de la flèche, en mangeait).
# L'anneau de retour passe au-delà (`retour.rayon_anneau`) et ne coexiste jamais avec lui.
CUE_MARGE_PX = 8
CUE_EPAISSEUR_PX = 4
# L'étiquette « NOM  f Hz » sous chaque disque : ce nombre de px SOUS l'anneau de retour, jamais
# dessous — `--smoke` compte les pixels non-fond que l'anneau couvrirait.
ETIQUETTE_ECART_PX = 4

# Le POINT DE FIXATION au centre de chaque disque (QA 1.17.1, 2026-10-02 : « mets aussi le point
# rouge au centre pour fixer le regard »), comme au c-VEP et au P300. Dessiné à CHAQUE image,
# disque allumé comme éteint, après le disque. CHROMATIQUE : la réponse SSVEP est pilotée par la
# LUMINANCE du clignotement blanc/noir, un petit point rouge STATIQUE n'ampute donc quasiment pas
# la modulation, et il reste visible dans les deux phases. Rayon en PIXELS, pas proportionnel :
# 12 px sur ~12 400 à 1000×700 (0,1 % du disque) — `--smoke` (A bis) compte la surface qui
# clignote VRAIMENT.
#
# ⚠️ RECOPIÉS de `stimulus/cvep.py` et `stimulus/p300.py` (`FIX_DOT`, `FIX_DOT_R`), pas importés :
# une fenêtre n'importe pas une fenêtre sœur — chacune est un programme que la console lance
# seul, et `stimulus.cvep` traînerait le code c-VEP derrière celle-ci. Leur ACCORD est tenu par
# `--smoke` (section L), pas par la discipline — même règle que `SEUIL_SAUT`.
FIX_DOT = (200, 40, 40)
FIX_DOT_R = 2

# En `--guide --retour`, l'essai se FERME ce délai AVANT la fin de la fixation : le moteur décide
# à la fin EXACTE (`cue` + `SSVEP_GUIDE_FIX_S`), jamais avant — fermer À la fin était une course à
# marge nulle, une décision arrivée une image trop tôt était perdue (revue C-M4).
MARGE_DECISION_S = 0.25

# Les écrans de REPOS : du guidé, et de l'essai libre tant que le moteur se repose. UNE écriture.
TITRE_CHAUFFE = "Le casque se stabilise"
SOUS_CHAUFFE = "installe-toi, ne fixe aucune cible — la mesure commence après"
TITRE_REPOS = "REPOS"
SOUS_REPOS = "fixe la CROIX centrale, ne suis AUCUNE cible"
# …et TOUS les autres textes de cette fenêtre, sortis de `_guide` et de `dessine` le 2026-10-02 sans
# en changer un mot : `mise_en_page` mesure le plus large pour placer le bloc une fois pour toutes,
# et la section K de `--smoke` exige de les avoir tous vus posés HORS des cibles.
TITRE_CONSIGNE = "REGARDE : {nom}"
SOUS_CONSIGNE = "essai {i}/{n}"
SOUS_FIXATION = "fixe la cible entourée"
TITRE_PAUSE = "—"
SOUS_PAUSE = "repose les yeux sur la croix"
ETIQUETTE = "{nom}  {hz:.2f} Hz"
HUD_TEXTE = "{fps:.0f} fps  |  sautées {sautees}  |  ESC = quitter"
# Le HUD le plus LARGE qu'on réserve : 3 chiffres de fps, 5 de frames sautées.
HUD_PIRE = HUD_TEXTE.format(fps=999, sautees=99999)

# Quand le bloc titre + sous-titre ne tient dans aucune bande libre à sa taille, on le RÉDUIT par ces
# paliers, jamais sous `POLICE_PLANCHER_PX`. Au-delà, il n'est PAS affiché (le terminal le dit) : un
# texte posé sur une cible serait pire qu'aucun texte — la consigne bleue désigne déjà la cible.
ECHELLES_TEXTE = (1.0, 0.9, 0.8, 0.7, 0.6)
POLICE_PLANCHER_PX = 10

# La fenêtre de dev (`--windowed`) et l'écran factice de `--smoke`. Nommée plutôt qu'écrite deux
# fois : `--smoke` relit des PIXELS à des coordonnées calculées sur cette taille, et deux valeurs
# feraient regarder le test à côté des cibles — sans rien casser, juste en ne prouvant rien.
TAILLE_FENETRE = (1000, 700)

# La géométrie, en proportion du plus petit côté (l'« empan »). Une seule écriture : `geometrie`
# la sert au rendu ET à `--smoke`.
DIST_RATIO = 0.30       # éloignement des cibles par rapport au centre
# Le RAYON d'un disque. 0,09 et pas le 0,075 du P300 et du c-VEP : le disque remplace une flèche de
# demi-taille 0,13, dont la surface clignotante valait 1,379 × 0,13² ≈ 0,0233 empan² (11 758 px
# à 1000×700, 27 485 en 1920×1080). Un disque de 0,075 n'en aurait gardé que 72 % — et une cible
# SSVEP plus petite donne une réponse plus faible. À 0,09 : π × 0,09² ≈ 0,0254 empan² (12 384 px,
# 29 432 px), soit +5 à +7 %.
RAYON_RATIO = 0.09
# Le plancher que `--smoke` compte dans les pixels : la surface de la flèche d'avant.
SURFACE_MIN_RATIO = 0.0233

# Les QUATRE places de la géométrie, DANS L'ORDRE où `--freqs` les remplit. Les trois premières
# sont celles du dépôt (`core.config.COMMANDS`), LUES et non recopiées : donner à `--freqs` le trio
# du dépôt doit redonner EXACTEMENT l'écran du dépôt, et une recopie divergerait au premier
# changement de `COMMANDS`.
#
# ⚠️ La quatrième n'est qu'une PLACE. Elle ne rend aucun jeu de quatre fréquences bon : savoir si
# quatre cibles tiennent à ce rafraîchissement, hors du pic alpha et séparables, est le métier du
# moteur (`core.config.propose_frequencies`), pas de cet écran. Elle est là parce que la géométrie
# a toujours eu quatre directions et n'en montrait que trois — un étudiant qui règle quatre cibles
# dans la console a droit à quatre disques, pas à un refus d'affichage.
EMPLACEMENTS = list(COMMANDS) + [{"name": "ARRIERE", "dir": "down", "jx": 0.0, "jy": -0.6}]

# Une image qui met plus que ça à basculer est une frame SAUTÉE. 1,5 période : un demi-intervalle
# de marge de part et d'autre, assez pour ne pas compter la gigue ordinaire du planificateur,
# assez peu pour attraper une image manquée.
#
# ⚠️ **La MÊME valeur et la MÊME mesure que `stimulus/cvep.py:SEUIL_SAUT`, et c'est délibéré** :
# deux fenêtres qui comptent « la même chose » de deux façons finissent par rendre deux chiffres
# qu'on n'ose plus comparer. Les deux constantes sont aujourd'hui chacune chez elle parce qu'aucun
# module partagé ne les accueille (`core/` ne connaît pas les écrans) ; leur ACCORD est donc tenu
# par une assertion de `--smoke` (section H), pas par la discipline. À la troisième fenêtre qui en
# aura besoin, ceci déménage — comme `core/errp_track.py` l'a fait pour la piste ErrP.
SEUIL_SAUT = 1.5

# Au-dessus de cette PROPORTION de frames sautées, le bilan de fin AVERTIT au lieu de se contenter
# de compter. 1 % de 60 Hz = une image figée toutes les 1,7 s : à ce régime, une fixation de 4 s en
# contient deux, et le taux d'émission mesuré n'est plus celui du cerveau. En dessous, on compte
# quand même — le chiffre est toujours imprimé.
SEUIL_ALERTE_SAUTEES = 0.01

# Ce que le MOTEUR jette avant d'enregistrer pour de bon : sa chauffe (l'offset DC de l'Unicorn
# dérive après ouverture de session — 10⁵ µV en rampe, mesuré le 2026-07-27). Valeur LUE dans
# `core/config.py` comme le fait `stimulus/p300.py`, jamais recopiée. Sans cette attente, le
# plancher de repos serait mesuré dans la dérive, c'est-à-dire étalonné sur le transitoire d'un
# filtre — et tout le reste de la séance se compare à ce plancher-là.
ATTENTE_MOTEUR_S = SSVEP_WARMUP_S


# --- Clignotement (fonction pure, testable sans écran) --------------------

def is_on(frame, frames_per_cycle):
    """True pendant la moitié « ON » du cycle (duty ~50 %, exact si période paire)."""
    return (frame % frames_per_cycle) < (frames_per_cycle + 1) // 2


# --- Géométrie des cibles -------------------------------------------------

def positions_cibles(plan, size, dist_ratio=DIST_RATIO):
    """Les centres ENTIERS des disques, DANS L'ORDRE DU PLAN — donc dans l'ordre des indices publiés.

    ⚠️ **Dans l'ordre du plan, jamais indexée par direction.** L'indice qu'un `cue` publie, et que
    le moteur compare au rang de SA liste de fréquences, est un rang dans ce plan. Retrouver « la
    cible 1 » par sa direction supposerait que l'ordre des directions est celui du plan, ce qui
    n'est vrai que par accident — et devient faux dès qu'un `--freqs` réordonne les cibles.

    Écrite UNE fois : elle sert au rendu et à `--smoke`, qui relit les pixels à ces points exacts.
    Deux géométries et le test regarderait à côté des cibles — sans rien casser, juste en ne
    prouvant plus rien. Même raison, même forme que `stimulus/cvep.py:positions_cibles`. ENTIERS,
    comme ceux du P300 : un cercle se trace et se relit au pixel près.
    """
    w, h = size
    cx, cy = w / 2.0, h / 2.0
    dist = min(w, h) * dist_ratio
    par_direction = {"up": (cx, cy - dist), "down": (cx, cy + dist),
                     "left": (cx - dist, cy), "right": (cx + dist, cy)}
    return [tuple(int(round(v)) for v in par_direction[c["dir"]]) for c in plan]


def geometrie(plan, size):
    """`(positions, rayon, rayon_cue, rayon_retour)` : les centres des disques, leur rayon, celui du
    cercle de consigne et celui de l'anneau de retour — ENTIERS, et calculés une seule fois.

    Le rendu et `--smoke` l'appellent tous les deux : ce sont les rayons exacts auxquels les cercles
    sont tracés, donc ceux auxquels le test les RELIT. L'anneau, lui, suit la règle COMMUNE aux
    trois fenêtres (`retour.rayon_anneau`), et `--smoke` la rappelle de son côté au lieu de lire
    `rayon_retour` ici : un écart local serait sinon d'accord avec lui-même."""
    rayon = int(min(size) * RAYON_RATIO)
    return (positions_cibles(plan, size), rayon, rayon + CUE_MARGE_PX,
            _retour.rayon_anneau(rayon))


def point_de_sonde(x, y, r):
    """Le point de l'écran où l'état ON/OFF du disque centré en `(x, y)`, de rayon `r`, se LIT dans
    les pixels — pour `--smoke`, qui ne croit pas l'émetteur sur parole.

    ⚠️ PAS le centre : le point de fixation y est dessiné, rouge dans les deux phases, et sa couleur
    ne dit rien de l'état du disque (la sonde lisait le centre avant l'arrivée du point). À
    mi-rayon on est DANS le disque (blanc quand il est allumé), loin du point et en deçà du contour
    (fond noir quand il est éteint). Même règle que `stimulus/cvep.py:point_de_sonde`."""
    return (int(x) + int(r) // 2, int(y))


# --- Les TEXTES : jamais sur une cible (2026-10-02) ---------------------------

MiseEnPage = namedtuple("MiseEnPage", "titre sous etiquette hud y_bloc ou echelle ancre_hud")


def etiquette(c):
    """Le texte statique sous un disque. Une écriture : le rendu le pose, `mise_en_page` le mesure."""
    return ETIQUETTE.format(nom=c["name"], hz=c["actual_hz"])


def _hors_des_cibles(rect, centres, garde):
    """True si AUCUN pixel de `rect` n'est à moins de `garde` du centre d'une cible."""
    for x, y in centres:
        qx, qy = min(max(x, rect.left), rect.right - 1), min(max(y, rect.top), rect.bottom - 1)
        if (qx - x) ** 2 + (qy - y) ** 2 < garde ** 2:
            return False
    return True


def mise_en_page(pygame, plan, size, n_essais):
    """Où poser les textes, et à quelle taille — calculé UNE fois par séance, depuis `geometrie`.

    ⚠️ **Aucun texte sur une cible, ni sur la zone de son anneau.** Jusqu'au 2026-10-02 le titre
    du guidé était posé à 10 % de la hauteur, c'est-à-dire PAR-DESSUS le haut du disque AVANT
    pendant qu'il clignotait (« fixe la cible entourée », « REGARDE : … », chauffe, repos). Un
    texte sur une cible change sa luminance moyenne, donc la réponse SSVEP qu'on mesure — sans
    rien casser. La zone interdite est le disque de rayon `rayon_retour + retour.EPAISSEUR_PX` :
    l'anneau de retour et une épaisseur de garde ; l'étiquette sous chaque disque en touche le bord.

    Le bloc titre + sous-titre va dans une BANDE LIBRE pleine largeur : au-dessus du disque du haut
    si elle suffit, sinon sous les cibles ET leurs étiquettes, sinon RÉDUIT (`ECHELLES_TEXTE`) ; si
    rien ne tient au plancher, il n'est pas affiché. La place est celle du texte le plus LARGE de
    la séance, pas celle de l'écran courant : un titre qui sauterait d'une bande à l'autre entre
    deux écrans serait un événement visuel en pleine mesure. Le HUD prend ensuite le premier coin
    libre (cibles, étiquettes, bloc), et n'est pas affiché si aucun ne l'est.

    La section K de `--smoke` relit les rectangles réellement POSÉS et les pixels, à plusieurs
    résolutions — pas cette fonction, qui ne pourrait que se donner raison.
    """
    w, h = size
    span = min(size)
    positions, _rayon, _cue, rayon_retour = geometrie(plan, size)
    garde = rayon_retour + _retour.EPAISSEUR_PX
    ecart = ETIQUETTE_ECART_PX

    def police(px):
        return pygame.font.SysFont("consolas", int(px))

    p_etiquette = police(max(14, int(span * 0.022)))
    p_hud = police(max(12, int(span * 0.016)))
    etiquettes = []
    for c, (x, y) in zip(plan, positions):
        r = pygame.Rect((0, 0), p_etiquette.size(etiquette(c)))
        r.midtop = (x, y + rayon_retour + ecart)   # la place exacte où `dessine` la pose
        etiquettes.append(r)

    # Les deux bandes, en lignes de pixels [début, fin) : la ligne `y - garde` est encore permise.
    bandes = (("en haut", ecart, min(y for _x, y in positions) - garde + 1),
              ("en bas", max([y + garde for _x, y in positions]
                             + [r.bottom + ecart for r in etiquettes]), h - ecart))
    noms = [c["name"] for c in plan]
    titres = [TITRE_CHAUFFE, TITRE_REPOS, TITRE_PAUSE] + noms + [
        TITRE_CONSIGNE.format(nom=n) for n in noms]
    sous = [SOUS_CHAUFFE, SOUS_REPOS, SOUS_FIXATION, SOUS_PAUSE,
            SOUS_CONSIGNE.format(i=n_essais, n=n_essais)]
    bloc = ou = None
    for echelle in ECHELLES_TEXTE:
        p_titre = police(max(POLICE_PLANCHER_PX, int(max(20, int(span * 0.040)) * echelle)))
        p_sous = police(max(POLICE_PLANCHER_PX, int(max(12, int(span * 0.016)) * echelle)))
        haut = p_titre.get_height() + p_sous.get_height()
        large = max([p_titre.size(t)[0] for t in titres] + [p_sous.size(t)[0] for t in sous])
        for nom, y0, y1 in bandes:
            if y1 - y0 >= haut and large <= w - 2 * ecart:
                bloc, ou = pygame.Rect(0, 0, large, haut), nom
                bloc.midtop = (int(w / 2), y0 + (y1 - y0 - haut) // 2)
                break
        if bloc is not None:
            break

    hud = pygame.Rect((0, 0), p_hud.size(HUD_PIRE))
    obstacles = [r.inflate(2 * ecart, 2 * ecart) for r in etiquettes]
    if bloc is not None:
        obstacles.append(bloc.inflate(2 * ecart, 2 * ecart))
    ancre_hud = None
    for ancre, point in (("topleft", (12, 10)), ("bottomleft", (12, h - 10)),
                         ("topright", (w - 12, 10)), ("bottomright", (w - 12, h - 10))):
        setattr(hud, ancre, point)
        if (pygame.Rect(0, 0, w, h).contains(hud) and _hors_des_cibles(hud, positions, garde)
                and hud.collidelist(obstacles) < 0):
            ancre_hud = {ancre: point}
            break
    return MiseEnPage(p_titre, p_sous, p_etiquette, p_hud,
                      None if bloc is None else bloc.top, ou, echelle, ancre_hud)


def pose_texte(win, police, texte, couleur, **ancre):
    """UN SEUL geste pour écrire à l'écran : rend, place (`ancre` = `midtop=…`, `topleft=…`),
    pose, et rend le rectangle posé.

    La section K de `--smoke` l'espionne pour relever le rectangle de CHAQUE texte affiché — d'où
    l'appel par son nom GLOBAL dans `dessine`, relu à chaque image (jamais une référence gardée en
    local), et le refus, par la même section, de tout `blit` direct dans `run` : il échapperait à
    la garde."""
    rendu = police.render(texte, True, couleur)
    rect = rendu.get_rect(**ancre)
    win.blit(rendu, rect)
    return rect


# --- Les fréquences AFFICHÉES : celles du mode, ou rien ---------------------

class FreqsRefusees(ValueError):
    """Le jeu de fréquences demandé n'est pas affichable ici. Rien n'a été affiché."""


def parse_freqs(texte):
    """`(liste de fréquences, None)` ou `(None, raison)`. Le format de `--freqs`, comme `--mode`.

    Fonction PURE, donc testable sans écran — et c'est la moitié « lecture » d'un geste dont la
    console tient la moitié « écriture » (`stimulus/registry.py:option_frequences`). Les deux
    moitiés d'un même geste, testées chacune sur son propre décor et jamais sur leur accord, sont
    la forme exacte des deux défauts que la QA du 2026-09-21 a trouvés ; leur aller-retour est
    donc vérifié par `--smoke`.
    """
    morceaux = [m.strip() for m in str(texte).split(",") if m.strip()]
    if not morceaux:
        return None, ("« --freqs » est vide — donne les fréquences séparées par des virgules, "
                      "par exemple 12,15,20")
    out = []
    for m in morceaux:
        try:
            out.append(float(m))
        except ValueError:
            return None, (f"« --freqs » : « {m} » n'est pas un nombre. Le séparateur est la "
                          f"VIRGULE et le séparateur décimal le POINT — écris 15,20,8.571 et non "
                          f"15,20,8,571, qui ferait quatre cibles dont une à 571 Hz")
    return out, None


def commandes_pour(freqs):
    """Les commandes du plan pour une liste de fréquences IMPOSÉE, dans CET ordre.

    ⚠️ L'ordre est celui de la liste, et ce n'est pas cosmétique : l'indice qu'un `cue` publie est
    un rang dans ce plan, et le moteur le compare au rang de sa propre liste. Trier ici ferait
    décrire la cible 0 par la fréquence d'une autre — sans qu'aucune exception ne le dise, et avec
    un taux d'émission parfaitement plausible.
    """
    return [{**EMPLACEMENTS[i], "desired_hz": float(f)} for i, f in enumerate(freqs)]


def verifie_freqs(freqs, refresh):
    """`None` si ce jeu est affichable ET décodable ici, sinon la RAISON en clair.

    ⚠️ **La règle n'est pas réécrite ici, elle est APPELÉE.** Bande passante, séparabilité et
    surtout « diviseur entier du rafraîchissement » — avec sa tolérance RELATIVE, celle qui
    accepte le « 8.57143 » que la console écrit pour 60/7 — vivent dans le contrat du mode
    (`core/modes/contract.py`). Une seconde écriture accepterait un jour ce que le moteur refuse,
    ou l'inverse : la fenêtre afficherait alors un jeu que le décodeur n'a pas, c'est-à-dire
    exactement la panne que `--freqs` existe pour supprimer.

    Le seul refus qui appartienne à la FENÊTRE est le nombre de places. Le moteur accepte jusqu'à
    8 cibles ; cet écran a quatre directions et ne sait pas en dessiner davantage.

    ⚠️ **La BANDE n'est pas l'affaire de la fenêtre** (passe C1, 2026-09-30). Elle ne la reçoit
    pas, et `validate` complète ce qu'on ne lui passe pas avec les DÉFAUTS du contrat : la fenêtre
    jugeait donc les fréquences contre 5-40 Hz, en parlant de « la bande RÉGLÉE ». Aux boutons :
    coupure basse à 3 Hz, « Proposer » rend 3 · 12 · 20 · 30, « Appliquer » accepte, « Tester »
    lance cette fenêtre… qui refuse. On juge donc contre la bande la PLUS LARGE que les réglages
    du mode permettent : aucune bande que le moteur accepte n'en sort, et tout le reste — les
    diviseurs du rafraîchissement, la séparabilité — est jugé comme avant, par le contrat.
    """
    # Import TARDIF : la fenêtre doit rester importable et lançable sans traîner le décodeur du
    # mode derrière elle. Même geste que `stimulus/cvep.py` pour `core.modes`.
    from core.modes.contract import validate
    from core.modes.ssvep import SPEC

    freqs = list(freqs)
    if len(freqs) > len(EMPLACEMENTS):
        return (f"« --freqs » : {len(freqs)} fréquences demandées, mais cet écran n'a que "
                f"{len(EMPLACEMENTS)} places ("
                + ", ".join(e["name"] for e in EMPLACEMENTS)
                + "). Le moteur, lui, en accepte davantage : c'est la GÉOMÉTRIE qui borne, pas le "
                  "décodage.")
    par_cle = {p.key: p for p in SPEC.params}
    la_plus_large = {"bande_bas": par_cle["bande_bas"].min, "bande_haut": par_cle["bande_haut"].max}
    _valides, raison = validate(SPEC, {"freqs": freqs, "refresh_hz": float(refresh),
                                       **la_plus_large})
    return raison


def plan_du_stimulus(refresh, freqs=None):
    """Le plan RÉELLEMENT affiché. Lève `FreqsRefusees` si `freqs` n'est pas affichable ici.

    `freqs=None` — l'absence de `--freqs` — rend le plan du dépôt, inchangé : c'est le seul chemin
    qui n'est pas validé, et c'est voulu. `choose_frequencies` y ARRONDIT au diviseur le plus
    proche (à 75 Hz, les 15 · 20 · 8,571 du dépôt deviennent 15 · 18,75 · 8,33), ce qui est le
    comportement historique de cette fenêtre lancée seule. Dès qu'on IMPOSE des fréquences, en
    revanche, cet arrondi devient le mensonge qu'on traque : le moteur corrélerait sur ce qu'on a
    demandé pendant que l'écran montre autre chose. On refuse donc au lieu d'arrondir.
    """
    if freqs is None:
        return choose_frequencies(refresh)
    raison = verifie_freqs(freqs, refresh)
    if raison is not None:
        raise FreqsRefusees(raison)
    return choose_frequencies(refresh, commands=commandes_pour(freqs))


# --- Le bilan de fin de séance --------------------------------------------

def bilan_de_seance(frames, sautees, refresh):
    """Le bilan de fin : ce qu'on IMPRIME et ce que `--smoke` relit, au même endroit.

    Même forme, même vocabulaire et même honnêteté que `stimulus/cvep.py:bilan_de_seance` — **le
    compte est AFFICHÉ, jamais corrigé**. Un bilan qui ne serait qu'une suite de `print` n'est
    gardé par aucune assertion ; il rend donc un dictionnaire, que `run` recopie dans son paramètre
    `bilan`, et les deux ne peuvent pas diverger puisqu'il n'y a qu'une source.

    ⚠️ En mode GUIDÉ, ce bilan est ce que le test du SSVEP peut lire dans le
    terminal. Sans lui, un taux mesuré sur un stimulus qui s'est figé est indiscernable d'un taux
    mesuré sur un stimulus propre — et c'est le chiffre entier qu'on irait ensuite citer.
    """
    part = (sautees / frames) if frames else 0.0
    if frames:
        print(f"[ssvep-stim] fin : {frames} frames affichées, {sautees} sautée(s) ({part:.1%})")
    else:
        print("[ssvep-stim] fin : aucune frame affichée")
    avertissement = None
    if frames and part > SEUIL_ALERTE_SAUTEES:
        avertissement = (
            f"⚠️ {part:.1%} des images ont été SAUTÉES (au-delà de "
            f"{SEUIL_ALERTE_SAUTEES:.0%}) : pendant ce temps les cibles ne clignotaient PAS aux "
            f"fréquences annoncées, et le moteur corrélait quand même. Ferme ce qui charge la "
            f"machine, reste en PLEIN ÉCRAN (c'est là qu'il y a un vsync), et REFAIS la mesure — "
            f"un taux d'émission pris sur un stimulus qui se fige mesure la machine, pas le "
            f"cerveau.")
        print(f"[ssvep-stim] {avertissement}")
    return {"frames": frames, "sautees": sautees, "part_sautees": part,
            "refresh": float(refresh), "avertissement": avertissement}


# --- Mesure du refresh écran ----------------------------------------------

# `measure_refresh` a DÉMÉNAGÉ dans `stimulus/refresh.py` le 2026-09-07, avec les trois fenêtres
# qui l'importaient. Réexporté sous son nom d'origine : `archive/ui.py` et les écrans de
# `archive/` l'importent encore d'ici.
from stimulus.refresh import measure_refresh  # noqa: E402,F401
from stimulus.garde import sous_garde_data  # noqa: E402
from stimulus import retour as _retour  # noqa: E402 - la croix s'appelle par le module (smoke)
from stimulus.retour import (ReposDuMoteur, Retour, SourceDecisions,  # noqa: E402
                             StatutDuMoteur)


# --- L'ordre des essais du run guidé (fonction PURE, testable sans écran) ---

def _groups(seq):
    """Découpe une séquence en séries d'éléments identiques consécutifs."""
    out, cur = [], []
    for x in seq:
        if cur and x == cur[-1]:
            cur.append(x)
        else:
            if cur:
                out.append(cur)
            cur = [x]
    if cur:
        out.append(cur)
    return out


def schedule(n_targets, per_target, rng):
    """Ordre des essais : ÉQUILIBRÉ, tiré au sort, sans plus de 2 fois la même cible d'affilée.

    ⚠️ **C'est l'un des trois invariants du protocole, et il n'est pas cosmétique.** Un bloc
    contigu par cible rend « quelle cible » inséparable de « quand » : la dérive d'impédance, la
    fatigue et l'installation des électrodes se confondent alors avec l'effet cherché, et le taux
    obtenu mesure autant le temps qui passe que le décodage. **Le c-VEP a payé ce confond 76 % de
    débit** (cf. README) ; on ne le refait pas ici.

    L'équilibre garantit que chaque cible est jugée sur le même effectif. Le tirage casse le
    confond « cible / moment ». La contrainte anti-série évite qu'une cible hérite d'un bloc
    contigu PAR HASARD — ce serait retomber sur le défaut qu'on cherche à éviter, et sur 36 essais
    le hasard produit ce genre de série plus souvent qu'on ne le croit.
    """
    pool = list(range(int(n_targets))) * int(per_target)
    for _ in range(200):
        rng.shuffle(pool)
        if max(len(g) for g in _groups(pool)) <= 2:
            return pool
    return pool  # tirage acceptable non trouvé : on garde le dernier (contrainte non critique)


# --- Boucle principale ----------------------------------------------------

def run(windowed=False, refresh=None, seconds=None, smoke=False, guide=False,
        per_target=SSVEP_GUIDE_TRIALS_PER_TARGET, seed=None, freqs=None,
        stream=MARKER_STREAM_DEFAULT, attente_consommateur_s=5.0, attente_moteur_s=None,
        journal=None, bilan=None, sonde_ecran=None,
        cue_s=None, fix_s=None, gap_s=None, repos_s=None, retour=False, source_retour=None,
        source_statut=None):
    """La boucle du stimulus — décodage libre (défaut) ou run GUIDÉ (`guide=True`).

    `retour` (`--retour`) entoure la cible décodée — et, sans `guide`, montre l'écran de repos
    tant que le moteur se repose. `source_retour` et `source_statut` n'existent que pour `--smoke`
    (des sources FACTICES à la place de `decoded_ssvep` et `status`, cf. `stimulus/retour.py`).

    ⚠️ Les deux modes partagent le MÊME rendu du clignotement, le MÊME compteur de frames et le
    MÊME compteur de frames SAUTÉES. Écrire une seconde boucle « pour le mode guidé » rouvrirait la
    duplication que ce dépôt a passé son temps à supprimer ailleurs — et surtout, le clignotement
    du guidé cesserait d'être exactement celui du décodage, donc le taux mesuré ne dirait plus rien
    du taux réel.

    `freqs` IMPOSE le jeu de cibles (l'option `--freqs`, celle que la console passe). `None` garde
    le jeu du dépôt. Une liste inaffichable à ce rafraîchissement lève `FreqsRefusees` **sans rien
    afficher** : l'arrondir en silence ferait décoder le moteur contre une sinusoïde absente.

    `bilan`, s'il est fourni, reçoit le dictionnaire de `bilan_de_seance` — c'est ce qui permet à
    `--smoke` d'ASSERTER sur le compte de frames sautées au lieu de le laisser en `print` que rien
    ne garde.

    `journal`, s'il est fourni, reçoit `(marqueur, horodatage)` pour CHAQUE marqueur réellement
    poussé — c'est ce qui permet à `--smoke` de vérifier la séance réelle et pas une séquence
    théorique.

    `sonde_ecran(surface, positions)` n'existe QUE pour `--smoke` : appelée juste après le `flip`
    sur lequel un `cue` vient de partir, elle donne à voir l'écran EXACT que ce marqueur prétend
    décrire. Le test y LIT la cible désignée dans les pixels, au lieu de croire le compteur de
    l'émetteur — qui, lui, ne peut que se donner raison.

    Les quatre durées (`cue_s`, `fix_s`, `gap_s`, `repos_s`) valent par défaut les constantes de
    `core/config.py`, celles que le MOTEUR lit de son côté. Ne les changer que pour un test : le
    moteur prélève sa fenêtre `SSVEP_GUIDE_FIX_S` secondes après le `cue`, et un `fix_s` plus court
    le ferait prélever APRÈS la fin de la fixation, sans qu'aucune exception ne le dise.
    """
    if smoke:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

    import pygame  # import tardif : le module s'importe même sans pygame installé

    cue_s = SSVEP_GUIDE_CUE_S if cue_s is None else float(cue_s)
    fix_s = SSVEP_GUIDE_FIX_S if fix_s is None else float(fix_s)
    gap_s = SSVEP_GUIDE_GAP_S if gap_s is None else float(gap_s)
    repos_s = SSVEP_GUIDE_REPOS_S if repos_s is None else float(repos_s)
    attente_moteur_s = ATTENTE_MOTEUR_S if attente_moteur_s is None else float(attente_moteur_s)

    # Les flux du RETOUR, construits AVANT d'ouvrir la fenêtre : le nom se lit dans le catalogue des
    # modes (1 à 2 s d'import), qui volait le GIL au clignotement depuis un fil (revue C-M5). Le
    # `status` ne sert qu'à l'essai LIBRE : en guidé, la fenêtre mène elle-même chauffe et repos.
    source_dec = source_retour
    if retour and source_dec is None:
        source_dec = SourceDecisions(stimulus_id="ssvep")
    source_rep = source_statut
    if retour and not guide and source_rep is None:
        source_rep = StatutDuMoteur()

    pygame.init()
    pygame.font.init()

    if windowed or smoke:
        size = TAILLE_FENETRE
        flags = pygame.SCALED
    else:
        info = pygame.display.Info()
        size = (info.current_w, info.current_h)
        flags = pygame.FULLSCREEN | pygame.SCALED

    # vsync=1 : le clignotement est cadencé par le balayage écran (indispensable au SSVEP)
    try:
        win = pygame.display.set_mode(size, flags, vsync=1)
    except (TypeError, pygame.error):
        win = pygame.display.set_mode(size, flags)
    pygame.display.set_caption("SSVEP stimulus — EEG_API_Unicorn")
    pygame.mouse.set_visible(False)

    if refresh is None:
        refresh = 60.0 if smoke else measure_refresh(pygame, win)
    try:
        plan = plan_du_stimulus(refresh, freqs)
    except FreqsRefusees:
        # ⚠️ On FERME avant de propager : un refus qui laisse un écran noir en plein écran par
        # dessus le terminal cache justement le message qui explique le refus.
        pygame.quit()
        for s in (source_dec, source_rep):
            if s is not None:
                s.fermer()
        raise

    print(f"[ssvep-stim] refresh ecran   : {refresh:.0f} Hz")
    print(f"[ssvep-stim] taille fenetre  : {size[0]}x{size[1]}")
    for c in plan:
        print(f"[ssvep-stim]   {c['name']:<8} {c['dir']:<5} desire={c['desired_hz']:>5.2f} Hz "
              f"-> {c['actual_hz']:>5.2f} Hz  ({c['frames_per_cycle']} frames/cycle)")

    w, h = size
    cx, cy = w / 2, h / 2
    # Les positions des cibles DANS L'ORDRE DU PLAN — c'est-à-dire dans l'ordre des indices que
    # les marqueurs `cue` publient et que le moteur compare à ses fréquences. Tout ce qui suit est
    # indexé par ce RANG, jamais par direction : `--freqs` réordonne les cibles, et un
    # dictionnaire par direction ferait alors décrire la cible 1 par le disque d'une autre.
    positions, rayon, rayon_cue, rayon_retour = geometrie(plan, size)
    # Le RETOUR cherche `decoded_ssvep` depuis l'ouverture, dans son fil. Par essai en guidé (une
    # décision par fixation), continu en libre (le mode décide à ~5 Hz).
    anneau = Retour(source_dec, len(plan), par_essai=guide) if retour else None
    # L'écran de REPOS de l'essai libre, tant que le moteur se repose (son flux `status`).
    repos = ReposDuMoteur(source_rep) if source_rep is not None else None

    # Les polices et la PLACE de chaque texte, une fois pour la séance : jamais sur une cible.
    page = mise_en_page(pygame, plan, size, len(plan) * per_target)
    print(f"[ssvep-stim] textes          : "
          + (f"{page.ou} (titre {page.titre.get_height()} px, police à {page.echelle:.0%})"
             if page.y_bloc is not None
             else "⚠️ AUCUNE bande libre hors des cibles — titres NON affichés")
          + (f", HUD {next(iter(page.ancre_hud))}" if page.ancre_hud
             else ", HUD NON affiché (aucun coin libre)"))

    clock = pygame.time.Clock()
    fps = int(refresh) + 5
    frame = 0
    sautees = 0              # images FIGÉES : cf. le ⚠️ « Les frames SAUTÉES » en tête de module
    t_flip_precedent = None  # l'instant du flip précédent — un ÉCART, donc pas de prédécesseur
    #                          pour la toute première image, qui ne peut jamais être comptée
    running = True
    t_start = time.perf_counter()
    fps_acc, fps_n, fps_show = 0.0, 0, refresh

    outlet = None
    if guide:
        # Le flux de marqueurs : nom et type FIGÉS (contrat public, core/config.py). `source_id`
        # unique par PID -> deux instances de cette fenêtre ne se confondent jamais l'une l'autre.
        info = StreamInfo(stream, "Markers", 1, IRREGULAR_RATE, "string",
                          f"ssvep-stim-{os.getpid()}")
        outlet = StreamOutlet(info)
        print(f"[ssvep-stim] marqueurs publiés sur « {stream} »")

    def emet(m):
        """Pousse un marqueur et l'horodate. UN SEUL endroit prend `local_clock()`."""
        ts = local_clock()
        if outlet is not None:
            outlet.push_sample([json.dumps(m)], timestamp=ts)
        if journal is not None:
            journal.append((m, ts))
        return ts

    def poll():
        """Événements + la limite `--seconds`. Les DEUX ici : une limite regardée seulement en fin
        d'essai ferait tourner `--seconds 20` pendant 25 s."""
        nonlocal running
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False
        if seconds is not None and (time.perf_counter() - t_start) >= seconds:
            running = False

    def dessine(designee=None, titre="", sous="", croix=False):
        """UN SEUL dessin pour tous les écrans du programme.

        Les deux modes avaient chacun leur boucle dans l'ancien découpage
        (`ssvep_stimulus.py` / `ssvep_guided.py`) et elles avaient déjà divergé sur la taille des
        flèches de l'époque (0,13 contre 0,12 de l'empan). Un stimulus qui n'est pas celui du
        décodage rend le taux mesuré inutilisable pour prédire le décodage.
        """
        win.fill(BG)
        for i, c in enumerate(plan):
            px, py = positions[i]
            pygame.draw.circle(win, OUTLINE, (px, py), rayon, 2)  # repère statique
            if is_on(frame, c["frames_per_cycle"]):
                pygame.draw.circle(win, ON_COLOR, (px, py), rayon)  # phase ON
            # le point de fixation : APRÈS le disque, à CHAQUE image, allumé comme éteint
            pygame.draw.circle(win, FIX_DOT, (px, py), FIX_DOT_R)
            # étiquette statique, SOUS l'anneau de retour (n'interfère pas avec le clignotement)
            pose_texte(win, page.etiquette, etiquette(c), LABEL,
                       midtop=(px, py + rayon_retour + ETIQUETTE_ECART_PX))
        if designee is not None:
            pygame.draw.circle(win, CUE, positions[designee], rayon_cue, CUE_EPAISSEUR_PX)
        # L'anneau de RETOUR : après les disques et la consigne, AVANT le texte — au-delà du cercle
        # de consigne, dans le noir (cf. `retour.rayon_anneau`).
        if anneau is not None:
            anneau.dessiner(pygame, win, positions, rayon_retour)
        if croix:
            _retour.dessine_croix(pygame, win, (cx, cy), DIM)
        # ⚠️ Les titres, dans la bande LIBRE que `mise_en_page` a choisie — jamais sur un disque
        # ni sur la zone de son anneau (cf. sa docstring : le titre a recouvert le disque AVANT).
        if page.y_bloc is not None:
            if titre:
                pose_texte(win, page.titre, titre, FG, midtop=(int(cx), page.y_bloc))
            if sous:
                pose_texte(win, page.sous, sous, DIM,
                           midtop=(int(cx), page.y_bloc + page.titre.get_height()))
        # ⚠️ Le HUD, EN DERNIER et dans un coin où il ne recouvre aucune cible (`mise_en_page`) : ce
        # qu'on ajoute par-dessus un stimulus change ce que l'œil reçoit ET ce que les sondes en
        # pixels de `--smoke` relisent. Il est DANS ce dessin partagé, donc le mode guidé l'a
        # aussi — il n'affichait rien du tout jusqu'au 2026-09-21, pas même le FPS, alors que
        # c'est lui qui MESURE : la seule chose qui distingue « ça marche » de « ça a l'air de
        # marcher » manquait justement là où elle compte.
        if page.ancre_hud is not None:
            pose_texte(win, page.hud, HUD_TEXTE.format(fps=fps_show, sautees=sautees), HUD,
                       **page.ancre_hud)

    def apres_flip():
        """Le comptage qui suit CHAQUE image affichée : une frame de plus, et une frame SAUTÉE si
        le basculement a pris plus de `SEUIL_SAUT` périodes.

        ⚠️ **Écrit UNE fois pour le décodage libre ET pour le run guidé.** Deux compteurs, même
        posés le même jour, cessent de compter la même chose au premier changement — et ce serait
        le mode guidé, celui qui MESURE, qui hériterait du plus vieux. Même mesure, au même
        endroit du tour de boucle, que `stimulus/cvep.py` : l'écart entre deux instants pris
        juste APRÈS le flip.
        """
        nonlocal frame, sautees, t_flip_precedent, fps_acc, fps_n, fps_show
        t_flip = time.perf_counter()
        if t_flip_precedent is not None and (t_flip - t_flip_precedent) > SEUIL_SAUT / refresh:
            sautees += 1
        t_flip_precedent = t_flip
        dt = clock.tick(fps) / 1000.0   # garde-fou si vsync absent
        if dt > 0:
            fps_acc += 1.0 / dt
            fps_n += 1
            if fps_n >= 30:
                fps_show, fps_acc, fps_n = fps_acc / fps_n, 0.0, 0
        frame += 1

    def phase(duree, marqueur=None, sonde=False, avant_la_fin=None, **kw):
        """Affiche pendant `duree` secondes en gardant le clignotement verrouillé à la frame.

        ⚠️ **`marqueur` part APRÈS le premier `flip`**, c'est-à-dire une fois que l'écran qu'il
        décrit est RÉELLEMENT affiché. Publié avant, il annonce la phase une frame trop tôt : rien
        ne lève d'exception, le moteur prélève simplement sa fenêtre décalée. C'est le même geste,
        et la même raison, que l'horodatage des flashs de `stimulus/p300.py`.

        `avant_la_fin = (secondes, geste)` : `geste()` est appelé une fois, AVANT de dessiner la
        première image à moins de `secondes` de la fin (cf. `MARGE_DECISION_S`).
        """
        premiere = True
        t_end = time.perf_counter() + duree
        while running and time.perf_counter() < t_end:
            poll()
            if avant_la_fin is not None and t_end - time.perf_counter() <= avant_la_fin[0]:
                avant_la_fin[1]()
                avant_la_fin = None
            dessine(**kw)
            pygame.display.flip()
            if premiere:
                premiere = False
                if marqueur is not None:
                    emet(marqueur)
                    if sonde and sonde_ecran is not None:
                        sonde_ecran(win, list(positions))
            apres_flip()
            lit_le_retour()
        if avant_la_fin is not None and running:
            avant_la_fin[1]()       # une image plus longue que la marge : le geste n'est pas perdu
        return running

    def lit_le_retour():
        """⚠️ En fin de tour : APRÈS le flip, le marqueur et la mesure de cadence de l'image. Lu
        avant le flip, il retarderait l'image que le marqueur horodate ; `--smoke` le vérifie."""
        if anneau is not None:
            anneau.lire()
        if repos is not None:
            repos.lire()

    seance_complete = False
    try:
        if not guide:
            # --- décodage libre : les disques du plan clignotent, rien d'autre ---------------
            # …sauf, en essai libre, tant que le MOTEUR se repose : l'écran de repos du guidé,
            # disques clignotants — le plancher se mesure dans ces conditions (cf. `_guide`).
            while running:
                poll()
                if repos is not None and repos.en_repos:
                    chauffe = repos.phase in (None, "warmup")
                    dessine(titre=TITRE_CHAUFFE if chauffe else TITRE_REPOS,
                            sous=SOUS_CHAUFFE if chauffe else SOUS_REPOS, croix=True)
                else:
                    dessine()
                pygame.display.flip()
                apres_flip()
                lit_le_retour()
                if smoke and frame >= 30:
                    running = False
        else:
            seance_complete = _guide(
                plan, per_target, seed, phase, emet, refresh,
                cue_s, fix_s, gap_s, repos_s, attente_moteur_s,
                outlet, attente_consommateur_s, anneau)
    finally:
        if anneau is not None:
            anneau.bilan("[ssvep-stim]")
            anneau.fermer()
        if repos is not None:
            repos.bilan("[ssvep-stim]")
            repos.fermer()
        pygame.quit()

    # Un BILAN, toujours, et dans les DEUX modes : « 0 frame sautée » doit se LIRE, pas se
    # deviner. En guidé, c'est la seule trace que la mesure puisse relire dans le terminal.
    resume = bilan_de_seance(frame, sautees, refresh)
    if bilan is not None:
        bilan.update(resume)

    if smoke and not guide:
        print("[ssvep-stim] smoke OK : rendu de 30 frames sans erreur (aucun ecran requis).")
    return True if not guide else seance_complete


def _guide(plan, per_target, seed, phase, emet, refresh,
           cue_s, fix_s, gap_s, repos_s, attente_moteur_s, outlet, attente_consommateur_s,
           anneau=None):
    """La ligne du temps du run guidé. Rend True si la séance est allée jusqu'au `calib_end`.

    Chauffe -> plancher de repos -> essais entrelacés -> fin. Le clignotement TOURNE du début à la
    fin, plancher de repos COMPRIS : celui-ci doit être mesuré dans les mêmes conditions visuelles
    que les essais, sinon le moteur soustrait un fond qui n'est pas celui du test.

    `anneau` (le RETOUR) : l'essai se FERME `MARGE_DECISION_S` avant la fin de la fixation, la
    décision arrive pendant le retour à la croix ; l'anneau s'éteint au début de la CONSIGNE
    suivante, `SSVEP_GUIDE_CUE_S` avant la fixation — hors des données notées, et jamais sous le
    grand titre « REGARDE : … » (revue E-M5). Cf. `stimulus/retour.py`.
    """
    noms = [c["name"] for c in plan]
    freqs = [float(c["actual_hz"]) for c in plan]
    rng = np.random.default_rng(seed)
    ordre = schedule(len(plan), per_target, rng)

    print(f"[ssvep-stim] GUIDÉ : {len(ordre)} essais ({per_target}/cible), ordre entrelacé tiré "
          f"au sort" + (f" (graine {seed})" if seed is not None else ""))
    print(f"[ssvep-stim] cibles : " + "  ".join(f"{n}@{f:.2f}Hz" for n, f in zip(noms, freqs)))

    # ⚠️ Attendre le moteur AVANT le premier marqueur utile. Sans ça, un étudiant qui a oublié de
    # lancer la mesure — ou qui a tapé un autre nom de flux — regarde un écran parfaitement
    # fonctionnel pendant quatre minutes, sans le moindre signe que personne n'écoute. LSL sait
    # répondre à la question, on la pose. L'attente est BORNÉE et on démarre quand même après.
    if attente_consommateur_s > 0 and outlet is not None:
        if not outlet.wait_for_consumers(attente_consommateur_s):
            print(f"[ssvep-stim] ⚠️ PERSONNE n'écoute « {outlet.get_info().name()} » après "
                  f"{attente_consommateur_s:g} s. La mesure est-elle lancée dans la console "
                  f"(bouton « Tester » de la page SSVEP) ? Je clignote quand même.")
        else:
            print("[ssvep-stim] le moteur écoute — on peut commencer.")

    # `trials` compte des ESSAIS, l'unité que le moteur incrémente à chaque fenêtre prélevée.
    # Annoncer autre chose (des cibles, des secondes) n'écraserait rien mais afficherait un
    # avancement faux, et ferait déclarer la séance complète bien avant qu'elle ne le soit.
    emet({"mode": "ssvep", "event": "calib_start", "trials": len(ordre),
          "freqs": freqs, "refresh_hz": float(refresh)})

    if attente_moteur_s > 0:
        print(f"[ssvep-stim] le moteur JETTE tout pendant sa chauffe (~{attente_moteur_s:g} s) : "
              f"consigne à l'écran en attendant.")
        if not phase(attente_moteur_s, titre=TITRE_CHAUFFE, croix=True, sous=SOUS_CHAUFFE):
            return _interrompu(0, len(ordre))

    if not phase(repos_s, marqueur={"mode": "ssvep", "event": "repos"},
                 titre=TITRE_REPOS, croix=True, sous=SOUS_REPOS):
        return _interrompu(0, len(ordre))

    for i, cible in enumerate(ordre, 1):
        # 1. La consigne : on désigne, le regard se déplace. AUCUN marqueur — cette seconde
        #    contient la saccade, et sa fin de course polluerait la fenêtre du moteur. L'anneau
        #    précédent s'éteint ICI, bien avant les données notées.
        if anneau is not None:
            anneau.mesure_commence()
        if not phase(cue_s, designee=cible, titre=TITRE_CONSIGNE.format(nom=noms[cible]),
                     sous=SOUS_CONSIGNE.format(i=i, n=len(ordre))):
            return _interrompu(i - 1, len(ordre))
        # 2. La fixation. Le `cue` part ICI, au premier flip : c'est l'instant à partir duquel le
        #    moteur compte `SSVEP_GUIDE_FIX_S` pour prélever la DERNIÈRE fenêtre de la fixation.
        fermer = None
        if anneau is not None:
            fermer = (min(MARGE_DECISION_S, fix_s / 2.0),
                      anneau.mesure_finie)
        if not phase(fix_s, designee=cible, titre=noms[cible], sous=SOUS_FIXATION,
                     marqueur={"mode": "ssvep", "event": "cue", "target": int(cible),
                               "freq_hz": freqs[cible]},
                     sonde=True, avant_la_fin=fermer):
            return _interrompu(i - 1, len(ordre))
        # 3. Le retour à la croix, pour que deux essais consécutifs ne se recouvrent pas.
        if not phase(gap_s, titre=TITRE_PAUSE, croix=True, sous=SOUS_PAUSE):
            return _interrompu(i, len(ordre))

    emet({"mode": "ssvep", "event": "calib_end"})
    print(f"[ssvep-stim] run guidé terminé : {len(ordre)} essais, « calib_end » envoyé — le "
          f"moteur calcule, le verdict s'affiche dans la console.")
    return True


def _interrompu(faits, total):
    """Une séance interrompue ne publie AUCUN `calib_end`. Elle le DIT, et rend False."""
    print(f"[ssvep-stim] ⚠️ run guidé INTERROMPU à l'essai {faits}/{total} : AUCUN « calib_end » "
          f"envoyé, donc aucun verdict ne sera calculé. Un taux mesuré sur une séance tronquée "
          f"serait indiscernable d'un taux complet, et c'est le chiffre entier qu'on citerait "
          f"ensuite. Clique « Abandonner » dans la console, puis recommence.")
    return False


# --- --smoke : le rendu libre, PUIS le run guidé sur un écran factice ------

def _rayon_lu(surface, centre, couleur, r_max):
    """Le rayon d'un cercle de `couleur` EXACTE autour de `centre`, lu dans les PIXELS ; None si
    aucun pixel de cette couleur à moins de `r_max`.

    On part de `r_max` vers le centre, à GAUCHE et AU-DESSUS, et on garde le pixel le plus éloigné :
    `pygame.draw.circle` atteint exactement `rayon` de ces deux côtés (un côté de moins à droite et
    en bas — mesuré, et revérifié en précondition par `--smoke`). Deux axes, parce qu'un texte posé
    plus tard peut masquer l'un ; il ne peut pas AJOUTER un pixel de cette couleur (`CUE` et le vert
    de l'anneau n'existent nulle part ailleurs). La valeur rendue est donc le rayon TRACÉ, au pixel
    près : c'est elle qui fait rougir un cercle tracé à un autre rayon que la règle."""
    largeur, hauteur = surface.get_width(), surface.get_height()
    x, y = int(centre[0]), int(centre[1])
    vus = []
    for dx, dy in ((-1, 0), (0, -1)):
        for d in range(int(r_max), -1, -1):
            px, py = x + dx * d, y + dy * d
            if (0 <= px < largeur and 0 <= py < hauteur
                    and tuple(surface.get_at((px, py)))[:3] == tuple(couleur)):
                vus.append(d)
                break
    return max(vus) if vus else None


def _cible_designee_a_l_ecran(surface, positions, rayon_cue):
    """LA cible que l'écran DÉSIGNE, lue dans les PIXELS. -1 si aucune, **-2 si la désignation est
    FAUTIVE** : plusieurs disques cerclés, ou un cercle à un autre rayon que `rayon_cue`.

    ⚠️ C'est le point de ce garde-fou : on ne demande pas à l'émetteur quelle cible il croit
    désigner — il ne peut que se donner raison. On regarde l'image. Même famille de test que la
    sonde de `stimulus/p300.py` (qui relit la cible cerclée) et celle de `stimulus/cvep.py` (qui
    relit la phase du code).

    Autour de chaque disque, on cherche le cercle `CUE` EXACT (`draw.circle` ne lisse pas) jusqu'à
    deux fois son rayon — moins que la distance au disque voisin ou à la croix — et on exige son
    rayon au pixel près (`_rayon_lu`).

    ⚠️ **Ce que cette sonde n'attrape PAS, et il faut le savoir avant de s'y fier** : remonter le
    `emet` AU-DESSUS du `flip`. Sous le pilote logiciel à tampon UNIQUE (`SDL_VIDEODRIVER=dummy`,
    celui du smoke), la surface porte déjà l'image dessinée avant même le `flip` — la sonde lirait
    donc la même chose des deux côtés. Elle prouve QUELLE cible est à l'écran, jamais QUAND elle y
    est arrivée. Même limite, même cause et même formulation que `stimulus/p300.py`.

    Ce trou-là est **fermé depuis le 2026-09-10 par la partie F du smoke**, qui ne regarde aucun
    pixel : elle compte les `flip` ENTRE deux marqueurs. Aucun pixel ne pouvait répondre à la
    question, parce que la question n'est pas « quoi » mais « quand ».
    """
    vus = [(i, r) for i, r in ((i, _rayon_lu(surface, p, CUE, 2 * rayon_cue))
                               for i, p in enumerate(positions)) if r is not None]
    if not vus:
        return -1
    if len(vus) == 1 and vus[0][1] == rayon_cue:
        return vus[0][0]
    return -2


def _etats_a_l_ecran(surface, positions, rayon):
    """Pour chaque cible et DANS L'ORDRE DU PLAN : True si elle est ALLUMÉE, lu dans les PIXELS.

    Le point de lecture est `point_de_sonde`, à MI-RAYON : blanc plein quand la phase est ON, fond
    noir sinon. Ni le point de fixation (au centre), ni le contour (sur le bord), ni le cercle de
    consigne (au-delà), ni l'étiquette (sous l'anneau), ni le HUD et les titres (hors de toute
    cible, `mise_en_page`) n'y passent — c'est ce qui fait de ce point une lecture de l'ÉTAT du
    clignotement et de rien d'autre. ⚠️ Il ne dit rien du RESTE de la surface : c'est la section K
    du smoke qui la garde des textes.
    """
    import pygame

    arr = pygame.surfarray.array3d(surface)          # (largeur, hauteur, 3)
    return [tuple(arr[point_de_sonde(x, y, rayon)]) == ON_COLOR for x, y in positions]


def _empreinte_point():
    """Les décalages `(dx, dy)` des pixels qu'occupe le point de fixation tracé SEUL, sur une toile
    vierge — la référence à laquelle `--smoke` compare chaque disque de chaque image."""
    import pygame

    m = FIX_DOT_R + 3
    toile = pygame.Surface((2 * m + 1, 2 * m + 1))
    toile.fill(BG)
    pygame.draw.circle(toile, FIX_DOT, (m, m), FIX_DOT_R)
    rouge = (pygame.surfarray.array3d(toile) == FIX_DOT).all(axis=2)
    return {(int(x) - m, int(y) - m) for x, y in zip(*np.nonzero(rouge))}


def _points_a_l_ecran(surface, positions, empreinte):
    """Pour chaque cible et DANS L'ORDRE DU PLAN : True si son point de fixation est RÉELLEMENT à
    l'écran — les pixels `FIX_DOT` autour de son centre forment EXACTEMENT `empreinte` : ni absent,
    ni décalé, ni d'une autre taille, ni d'une autre couleur. Lu dans les PIXELS."""
    import pygame

    m = FIX_DOT_R + 3
    arr = pygame.surfarray.array3d(surface)
    vus = []
    for x, y in positions:
        x, y = int(x), int(y)
        bloc = arr[x - m:x + m + 1, y - m:y + m + 1]
        rouge = (bloc == FIX_DOT).all(axis=2)
        vus.append({(int(a) - m, int(b) - m) for a, b in zip(*np.nonzero(rouge))} == empreinte)
    return vus


def _smoke_points(images, n_cibles):
    """La garde L, sur `[(états, points), …]` lus image par image : `None` si le point de fixation
    était à l'écran sur CHAQUE disque de CHAQUE image ET que chaque disque a été vu allumé ET
    éteint (sinon la garde ne prouverait rien sur la phase manquante) ; la faute sinon."""
    manques = [(i, k) for i, (_e, p) in enumerate(images) for k, vu in enumerate(p) if not vu]
    if manques:
        return f"point ABSENT ou faux (image, disque) : {manques[:4]} sur {len(manques)}"
    phases = [{e[k] for e, _p in images} for k in range(n_cibles)]
    if not images or any(ph != {True, False} for ph in phases):
        return f"phases vues par disque : {phases} — il faut allumé ET éteint"
    return None


def _periode_observee(suite):
    """La plus petite période qui explique cette suite ON/OFF, ou None si aucune ne la couvre.

    ⚠️ C'est la FRÉQUENCE AFFICHÉE, reconstruite depuis l'écran : `refresh / période`. On ne
    demande pas au plan ce qu'il croit afficher — c'est justement le maillon qu'on soupçonne,
    puisque `run()` a ignoré `--freqs` pendant tout le temps où cette option n'existait pas.

    La recherche s'arrête à la moitié de la suite : une « période » qu'on n'a pas vue se répéter
    au moins deux fois n'est pas une période, c'est un motif.
    """
    for p in range(2, len(suite) // 2 + 1):
        if all(v == suite[i % p] for i, v in enumerate(suite)):
            return p
    return None


def _rejouer_libre(freqs=None, cales=0):
    """Joue le décodage libre sur un écran factice. Rend (périodes LUES DANS LES PIXELS, bilan,
    cales réellement posées, flips comptés, pixels ALLUMÉS de chaque disque à la première image —
    où tous le sont : `is_on(0, …)` —, et par image `(états, points de fixation)` lus à l'écran).

    ⚠️ Écrite le 2026-09-21 et jamais appelée jusqu'au 2026-10-02 : la fréquence AFFICHÉE n'était
    relue nulle part. C'est la partie A bis du smoke.

    `cales` FABRIQUE des frames sautées, en retenant le flip assez longtemps pour dépasser
    `SEUIL_SAUT`. C'est le seul moyen d'exercer le compteur de bout en bout — sous `dummy` il n'y
    a jamais de vsync manqué, donc il resterait à 0 quoi qu'on fasse, et le neutraliser ne
    rougirait rien. Même geste, même raison que la section C3 de `stimulus/cvep.py --smoke`.

    ⚠️ Les premières images sont ÉPARGNÉES (`attendre`) : l'émetteur mesure un ÉCART entre deux
    flips, donc la toute première image n'a pas de prédécesseur et ne peut par construction pas
    être comptée. Caler les toutes premières ferait poser N cales pour N-1 comptées.
    """
    import pygame

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    # Là où regarder : la MÊME géométrie que le rendu, appelée et non recalculée ici.
    positions, rayon, _c, _a = geometrie(plan_du_stimulus(60.0, freqs), TAILLE_FENETRE)
    etats, allumes, points = [], [], []
    empreinte = _empreinte_point()
    compteur = {"restantes": int(cales), "faites": 0, "attendre": 5}
    vrai_flip = pygame.display.flip

    def flip_espion(*a, **k):
        r = vrai_flip(*a, **k)
        surface = pygame.display.get_surface()
        etats.append(_etats_a_l_ecran(surface, positions, rayon))
        points.append((etats[-1], _points_a_l_ecran(surface, positions, empreinte)))
        if not allumes:
            pixels = pygame.surfarray.array3d(surface)
            allumes.extend(int((pixels[x - rayon - 1:x + rayon + 2, y - rayon - 1:y + rayon + 2]
                                == ON_COLOR).all(axis=2).sum()) for x, y in positions)
        if compteur["attendre"] > 0:
            compteur["attendre"] -= 1
        elif compteur["restantes"] > 0:
            compteur["restantes"] -= 1
            compteur["faites"] += 1
            time.sleep(SEUIL_SAUT * 1.4 / 60.0)
        return r

    bilan = {}
    pygame.display.flip = flip_espion
    try:
        run(smoke=True, refresh=60.0, freqs=freqs, bilan=bilan)
    finally:
        pygame.display.flip = vrai_flip
    suites = [list(s) for s in zip(*etats)] if etats else []
    return ([_periode_observee(s) for s in suites], bilan, compteur["faites"], len(etats),
            allumes, points)


def _smoke():
    """Deux moitiés : le rendu libre, puis LE RUN GUIDÉ, sur `SDL_VIDEODRIVER=dummy`.

    La seconde est celle qui compte. Elle rejoue une séance entière et vérifie les trois choses
    qu'un protocole de mesure ne peut pas se permettre de perdre : la séance s'ouvre et se ferme
    comme les trois fenêtres sœurs, la cible ANNONCÉE est celle que l'écran a réellement DÉSIGNÉE
    (lue dans les pixels), et l'ordre des essais est ENTRELACÉ et équilibré.
    """
    from collections import Counter

    # Cette fenêtre ne joue aucun son : sans pilote audio FACTICE, chaque `pygame.init()` du smoke
    # ouvre la carte son et chaque `pygame.quit()` la referme — mesuré le 2026-10-02 : 4,2 s contre
    # 1,9 s pour une séance guidée courte, et le smoke joue une vingtaine de `run`.
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # --- A. le rendu libre, comme avant le déménagement ---------------------------
    chk(run(smoke=True, refresh=60.0),
        "le décodage libre rend 30 frames sans erreur (aucun écran requis)")

    # --- A bis. CE QUI CLIGNOTE, lu dans les PIXELS ----------------------------------
    # Chaque disque clignote à SA période, dans l'ordre de `--freqs` (réordonné exprès), et garde au
    # moins la surface de la flèche qu'il remplace (`SURFACE_MIN_RATIO`) : une cible SSVEP plus
    # petite donne une réponse plus faible. Rien n'est demandé au plan — on regarde l'écran.
    import pygame

    plan_lu = plan_du_stimulus(60.0, [20.0, 12.0, 15.0])
    periodes, _b, _c, n_images, allumes, points = _rejouer_libre(freqs=[20.0, 12.0, 15.0])
    chk(n_images == 30 and periodes == [c["frames_per_cycle"] for c in plan_lu],
        f"chaque disque clignote à la période de SA fréquence, dans l'ordre de `--freqs`, lu dans "
        f"les PIXELS ({periodes} pour {[c['frames_per_cycle'] for c in plan_lu]} images/cycle)")
    # La surface qui clignote VRAIMENT : le disque MOINS son point de fixation, compté dans les
    # pixels — et la précondition que ce compte est bien celui-là (un disque tracé seul, moins
    # l'empreinte du point), sans quoi « au-dessus du plancher » pourrait compter le point.
    plancher = SURFACE_MIN_RATIO * min(TAILLE_FENETRE) ** 2
    empreinte = _empreinte_point()
    _p, r_disque, _c2, _a2 = geometrie(plan_lu, TAILLE_FENETRE)
    toile = pygame.Surface((2 * r_disque + 3, 2 * r_disque + 3))
    toile.fill(BG)
    pygame.draw.circle(toile, ON_COLOR, (r_disque + 1, r_disque + 1), r_disque)
    disque_seul = int((pygame.surfarray.array3d(toile) == ON_COLOR).all(axis=2).sum())
    chk(allumes and min(allumes) >= plancher
        and all(a == disque_seul - len(empreinte) for a in allumes),
        f"…et chaque disque allumé couvre au moins la surface de la flèche d'avant, point de "
        f"fixation DÉDUIT ({allumes} px allumés = {disque_seul} du disque − {len(empreinte)} du "
        f"point, plancher {plancher:.0f})")
    # L. LE POINT DE FIXATION, à chaque image, disque ALLUMÉ ET ÉTEINT (QA 1.17.1). Lu dans les
    # PIXELS : l'empreinte exacte du point, à la couleur exacte, au centre de chaque disque. Un
    # point oublié, ou dessiné dans la seule phase ON, rougit ici.
    chk(_smoke_points(points, len(plan_lu)) is None,
        f"[L] libre : le point rouge est au centre de CHAQUE disque, à chaque image, allumé ET "
        f"éteint, lu dans les PIXELS ({_smoke_points(points, len(plan_lu)) or 'ok'}, "
        f"{len(points)} images)")
    # Précondition de `_rayon_lu` : ce qu'il lit sur un cercle tracé SEUL est son rayon exact.
    toile = pygame.Surface((200, 200))
    toile.fill(BG)
    pygame.draw.circle(toile, CUE, (100, 100), 71, CUE_EPAISSEUR_PX)
    chk(_rayon_lu(toile, (100, 100), CUE, 99) == 71,
        f"(précondition) `_rayon_lu` relit le rayon EXACT d'un cercle tracé seul "
        f"({_rayon_lu(toile, (100, 100), CUE, 99)} pour 71)")

    # --- B. l'ordre des essais, sur la fonction PURE -------------------------------
    # Vérifié séparément de la séance jouée : la fonction est appelée avec des effectifs qu'une
    # séance de test ne peut pas se payer, et c'est là que la contrainte anti-série se voit.
    series, effectifs = [], set()
    for graine in range(50):
        suite = schedule(3, 12, np.random.default_rng(graine))
        series.append(max(len(g) for g in _groups(suite)))
        effectifs.add(tuple(sorted(Counter(suite).values())))
    chk(max(series) <= 2,
        f"sur 50 tirages, jamais plus de 2 fois la même cible d'affilée (série max : "
        f"{max(series)}) — une cible qui hériterait d'un bloc contigu par hasard rendrait "
        f"« quelle cible » inséparable de « quand »")
    chk(effectifs == {(12, 12, 12)},
        f"…et chaque tirage donne le MÊME effectif à chaque cible ({sorted(effectifs)})")

    # --- C. LA SÉANCE GUIDÉE, jouée pour de vrai sur un écran factice --------------
    # Un flux au nom DISTINCT du contrat public : les noms de flux sont partagés par toutes les
    # instances du projet, et un smoke ne doit jamais pouvoir répondre à la place d'un vrai
    # émetteur. `attente_consommateur_s=0` parce que personne n'écoute, par construction ; les
    # durées sont raccourcies parce qu'on teste la LIGNE DU TEMPS, pas la physiologie.
    marqueurs, designees = _rejouer_guide(per_target=4, seed=5)

    evenements = [m["event"] for m, _ts in marqueurs]
    chk(evenements[0] == "calib_start" and evenements[-1] == "calib_end",
        f"la séance s'ouvre et se ferme comme les trois autres fenêtres "
        f"({evenements[:2]}… {evenements[-1:]})")
    chk(evenements[1] == "repos",
        f"…et le plancher de repos vient AVANT le premier essai : le moteur y mesure le fond de "
        f"corrélation de chaque cible, et sans lui il n'a aucun seuil ({evenements[:3]})")
    attendu = ["calib_start", "repos"] + ["cue"] * 12 + ["calib_end"]
    chk(evenements == attendu,
        f"la séance a exactement la forme attendue ({len(evenements)} marqueurs pour "
        f"{len(attendu)} — {evenements})")

    cues = [m for m, _ts in marqueurs if m["event"] == "cue"]
    # ⚠️ LE test de cette moitié. La vérité-terrain doit être celle qui a été AFFICHÉE, pas celle
    # que le tirage avait décidée : un `cue` juste, publié sur un écran qui en désigne un autre,
    # fait mesurer la justesse du moteur contre une réponse fausse — sans lever la moindre
    # exception, et avec un taux parfaitement plausible.
    chk(designees and [c["target"] for c in cues] == designees,
        f"la cible annoncée par `cue` est celle que l'écran a RÉELLEMENT DÉSIGNÉE — UN cercle bleu, "
        f"au rayon exact, lu dans les PIXELS ({[c['target'] for c in cues]} annoncées contre "
        f"{designees} affichées ; -2 = désignation fautive)")

    # L'ENTRELACEMENT, sur la séance JOUÉE : aucune cible deux fois de suite, et chacune vue
    # autant de fois. Un bloc contigu rendrait « quelle cible » inséparable de « quand », et la
    # dérive d'impédance se confondrait avec l'effet cherché. Le c-VEP a payé ce confond 76 % de
    # débit.
    suite = [c["target"] for c in cues]
    # ⚠️ Le seuil est « pas plus de DEUX d'affilée », pas « jamais deux fois de suite », et l'écart
    # est délibéré : ce que le protocole doit empêcher, c'est un BLOC contigu par cible, qui rend
    # « quelle cible » inséparable de « quand ». Un doublon isolé ne crée aucun bloc. Le P300, lui,
    # interdit toute répétition immédiate (`stimulus/p300.py::blocs_melanges`) parce que c'est un
    # paradigme ODDBALL : un flash répété y produit une réfractarité non maîtrisée sur l'onde
    # mesurée. Le SSVEP n'a pas cette contrainte — on fixe une cible en continu, il n'y a pas
    # d'événement rare à répéter. Copier le seuil du P300 « pour être sûr » resserrerait le tirage
    # sans raison physiologique, et rendrait l'ordre moins aléatoire, pas plus.
    chk(max(len(g) for g in _groups(suite)) <= 2,
        f"jamais plus de 2 fois la même cible d'affilée : c'est le BLOC contigu qu'on interdit, "
        f"celui qui confond « quelle cible » et « quand » ({suite})")
    comptes = Counter(suite)
    chk(len(set(comptes.values())) == 1 and len(comptes) == 3,
        f"…et chacune des 3 cibles est vue le même nombre de fois ({dict(sorted(comptes.items()))})")

    # Le `cue` porte SA fréquence, et c'est celle du plan : le moteur construit son décodeur sur
    # ce que l'écran affiche, pas sur ce qu'il suppose. Une fenêtre lancée sur un écran 120 Hz
    # afficherait d'autres fréquences, et un moteur qui garderait les siennes corrélerait contre
    # des sinusoïdes que personne ne montre.
    depart = marqueurs[0][0]
    chk(depart.get("trials") == len(cues),
        f"`calib_start` annonce des ESSAIS, dans l'unité que le moteur compte "
        f"({depart.get('trials')} annoncés, {len(cues)} joués)")
    chk(depart.get("freqs") and all(
        abs(c["freq_hz"] - depart["freqs"][c["target"]]) < 1e-9 for c in cues),
        f"…et chaque `cue` porte la fréquence de SA cible, celle que `calib_start` a déclarée "
        f"({depart.get('freqs')})")

    horodatages = [ts for _m, ts in marqueurs]
    chk(all(b > a for a, b in zip(horodatages, horodatages[1:])),
        "les horodatages avancent strictement — un flip par marqueur, un horodatage par flip")

    # Les intervalles entre deux `cue` consécutifs valent bien un essai entier : c'est la seule
    # chose qui prouve que les trois phases ont été JOUÉES, et pas seulement écrites.
    ts_cues = [ts for m, ts in marqueurs if m["event"] == "cue"]
    entre = [b - a for a, b in zip(ts_cues, ts_cues[1:])]
    chk(entre and min(entre) >= (_SMOKE_FIX_S + _SMOKE_GAP_S + _SMOKE_CUE_S) * 0.8,
        f"deux essais consécutifs sont séparés par fixation + repos + consigne "
        f"({min(entre) * 1000:.0f} ms minimum pour "
        f"{(_SMOKE_FIX_S + _SMOKE_GAP_S + _SMOKE_CUE_S) * 1000:.0f} ms demandées)")

    # --- D. une séance INTERROMPUE ne publie AUCUN calib_end -----------------------
    journal_i, _d = _rejouer_guide(per_target=4, seed=5, seconds=_SMOKE_FIX_S)
    evenements_i = [m["event"] for m, _ts in journal_i]
    chk("calib_start" in evenements_i and "calib_end" not in evenements_i,
        f"une séance INTERROMPUE ne publie AUCUN calib_end — un taux mesuré sur une séance "
        f"tronquée serait indiscernable d'un taux complet ({evenements_i})")

    # --- E. les durées viennent de core/config.py, aucune copie locale -------------
    # Vérifié sur le TEXTE SOURCE, comme la pause entre manches de `stimulus/p300.py` : comparer
    # les VALEURS ne prouverait rien, une copie locale à 3,0 s étant égale à la constante à 3,0 s
    # le jour où on l'écrit — et divergeant en silence au premier changement. Ce qui se casse
    # alors n'est pas ce fichier : c'est l'endroit où le MOTEUR prélève la fenêtre de chaque essai.
    import inspect
    import re

    source = inspect.getsource(sys.modules[__name__])
    copies = re.findall(r"^\s*(?:CUE_S|FIX_S|GAP_S|REPOS_S|TRIALS_PER_TARGET)\s*=\s*[0-9]",
                        source, re.M)
    chk(not copies and "SSVEP_GUIDE_FIX_S" in source,
        f"les durées du protocole viennent de core/config.py, aucune copie locale n'est revenue "
        f"({copies or 'aucune copie'})")

    # --- F. LE MARQUEUR PART APRÈS LE FLIP, vérifié sur l'ORDRE DES APPELS ---------
    #
    # ⚠️ La sonde en pixels de la partie C ne peut PAS attraper ça, et sa propre docstring le dit :
    # sous `SDL_VIDEODRIVER=dummy` la surface porte déjà l'image AVANT le `flip`, donc elle lirait
    # la même chose des deux côtés. Elle prouve QUELLE cible est à l'écran, jamais QUAND elle y est
    # arrivée. Or « horodater avant le flip » est l'un des deux gestes que `CLAUDE.md` nomme comme
    # la panne caractéristique de cette famille de fenêtres : rien ne lève, le moteur prélève juste
    # sa fenêtre une frame trop tôt, et c'est indiscernable d'un étudiant qui fixe mal.
    #
    # L'invariant, lui, ne dépend d'aucun pixel : chaque marqueur de PHASE est publié après le
    # premier `flip` de sa phase, donc deux marqueurs consécutifs ont toujours au moins un `flip`
    # entre eux. Remonter `emet` au-dessus du `flip` colle `calib_start` et `repos` l'un contre
    # l'autre, sans une seule frame entre les deux.
    import pygame

    melange = []
    vrai_flip = pygame.display.flip
    pygame.display.flip = lambda *a, **k: (melange.append("flip"), vrai_flip(*a, **k))[1]
    try:
        _rejouer_guide(per_target=1, seed=5, journal=melange)
    finally:
        pygame.display.flip = vrai_flip

    rangs = [i for i, e in enumerate(melange) if isinstance(e, tuple)]
    frames_entre = [sum(1 for e in melange[a + 1:b] if e == "flip")
                    for a, b in zip(rangs, rangs[1:])]
    chk(len(rangs) >= 5 and melange.count("flip") >= 5,
        f"la séance courte a bien joué des frames ET publié des marqueurs "
        f"({melange.count('flip')} flips, {len(rangs)} marqueurs)")
    chk(frames_entre and min(frames_entre) >= 1,
        f"entre deux marqueurs consécutifs il y a TOUJOURS au moins une frame affichée : le "
        f"marqueur décrit un écran déjà à l'écran, pas un écran à venir ({frames_entre})")

    # --- G. `--freqs` DÉCIDE VRAIMENT DU PLAN, ET DANS L'ORDRE DONNÉ ---------------
    #
    # C'est la moitié « lecture » d'un geste dont `stimulus/registry.py` tient la moitié
    # « écriture ». Les deux défauts trouvés par la QA du 2026-09-21 ont exactement cette forme :
    # deux moitiés d'un même geste, chacune testée sur son propre décor, jamais sur leur accord.
    lu, raison = parse_freqs("12,15,20")
    chk(lu == [12.0, 15.0, 20.0] and raison is None,
        f"« --freqs 12,15,20 » se lit comme trois fréquences ({lu}, {raison})")
    plan_impose = plan_du_stimulus(60.0, [12.0, 15.0, 20.0])
    chk([round(c["actual_hz"], 3) for c in plan_impose] == [12.0, 15.0, 20.0],
        f"…et le plan AFFICHÉ porte ces fréquences-là, pas celles du dépôt "
        f"({[round(c['actual_hz'], 3) for c in plan_impose]})")
    # L'ORDRE, qui n'est pas cosmétique : l'indice qu'un `cue` publie est un rang dans ce plan, et
    # le moteur le compare au rang de SA liste. Trier ferait décrire la cible 0 par la fréquence
    # d'une autre — sans exception, et avec un taux d'émission parfaitement plausible.
    plan_desordre = plan_du_stimulus(60.0, [20.0, 12.0, 15.0])
    chk([round(c["actual_hz"], 3) for c in plan_desordre] == [20.0, 12.0, 15.0],
        f"…dans l'ORDRE DONNÉ, jamais trié : le rang EST l'identifiant de la cible "
        f"({[round(c['actual_hz'], 3) for c in plan_desordre]})")
    # L'aller-retour avec la moitié « écriture ». Un séparateur qui divergerait entre les deux
    # ferait lancer la fenêtre sur des fréquences muettes, et personne ne le verrait.
    from stimulus.registry import option_frequences
    ecrit = option_frequences("ssvep", [12.0, 15.0, 60.0 / 7])
    relu, _r = parse_freqs(ecrit[1])
    chk(ecrit[0] == "--freqs" and relu is not None
        and all(abs(a - b) < 1e-3 for a, b in zip(relu, [12.0, 15.0, 60.0 / 7])),
        f"ce que la console ÉCRIT, cette fenêtre le RELIT à l'identique ({ecrit} -> {relu})")

    # --- H. UNE FRÉQUENCE IMPOSSIBLE EST REFUSÉE, JAMAIS ARRONDIE ------------------
    #
    # ⚠️ LE test de `--freqs`. `choose_frequencies` ajuste `frames_per_cycle` en silence : 17 Hz à
    # 60 Hz deviendrait 15 Hz, affiché sans prévenir, pendant que le moteur corrèle sur 17. Il ne
    # décoderait pas mal — il ne décoderait RIEN, et rien ne le dirait.
    refuse = None
    try:
        plan_du_stimulus(60.0, [15.0, 17.0])
    except FreqsRefusees as e:
        refuse = str(e)
    chk(refuse is not None and "diviseur" in refuse,
        f"17 Hz à 60 Hz est REFUSÉ, avec la raison du MOTEUR ({(refuse or 'AUCUN REFUS')[:60]}…)")
    chk(refuse is not None and "15" in refuse and "20" in refuse,
        f"…et le refus propose les deux voisins affichables ({(refuse or '')[-40:]})")
    trop = None
    try:
        plan_du_stimulus(60.0, [12.0, 15.0, 20.0, 10.0, 6.0])
    except FreqsRefusees as e:
        trop = str(e)
    chk(trop is not None,
        f"…et cinq cibles sont refusées par la FENÊTRE : le moteur en accepte 8, cet écran a "
        f"quatre directions et ne sait pas en dessiner plus ({(trop or 'AUCUN REFUS')[:50]}…)")

    # --- H bis. LA BANDE N'EST PAS L'AFFAIRE DE LA FENÊTRE (passe C1, 2026-09-30) ----------
    #
    # Le parcours aux boutons : coupure basse à 3 Hz dans « Régler », « Proposer », « Appliquer »,
    # « Tester ». Le moteur accepte le jeu ; la fenêtre le jugeait contre la bande PAR DÉFAUT
    # (5-40 Hz) et refusait de s'ouvrir. Le jeu est celui que le moteur propose VRAIMENT, par la
    # même fonction que `propose_params`.
    from core.config import propose_frequencies
    from core.modes.contract import validate as _valider
    from core.modes.ssvep import SPEC as _SPEC_SSVEP
    propose, _note = propose_frequencies(60.0, 4, bande=(3.0, 40.0))
    moteur_v, moteur_r = _valider(_SPEC_SSVEP, {"freqs": propose, "bande_bas": 3.0})
    chk(propose and min(propose) < 5.0 and moteur_v is not None,
        f"(précondition) sous une coupure basse à 3 Hz, le moteur propose une cible sous 5 Hz et "
        f"l'accepte ({[round(f, 3) for f in propose]}, {moteur_r or 'accepté'})")
    raison_fenetre = verifie_freqs(propose, 60.0)
    chk(raison_fenetre is None,
        f"…et la FENÊTRE l'affiche : elle ne juge plus la bande, qu'elle ne reçoit pas "
        f"({raison_fenetre or 'accepté'})")
    # …mais elle ne juge pas « rien » : ce qu'AUCUNE bande réglable ne contient reste refusé.
    raison_hors = verifie_freqs([50.0, 20.0], 100.0)
    chk(raison_hors is not None and "50" in raison_hors,
        f"…alors que 50 Hz, au-dessus de TOUTE coupure haute que le mode accepte, est refusé "
        f"({(raison_hors or 'AUCUN REFUS')[:70]}…)")

    # --- I. LE COMPTEUR DE FRAMES SAUTÉES COMPTE, ET NE CORRIGE RIEN ---------------
    #
    # Observé en séance le 2026-09-21 : « périodiquement, l'image se figeait ». Rien ne levait,
    # rien ne comptait, et le verdict de la mesure n'en savait rien. Une image figée n'est pas un
    # ralentissement : c'est une cible qui CESSE de clignoter pendant que le moteur corrèle.
    net = bilan_de_seance(1000, 0, 60.0)
    abime = bilan_de_seance(1000, 37, 60.0)
    chk(net["sautees"] == 0 and abs(net["part_sautees"]) < 1e-9,
        f"une course sans saut rend 0 ({net['sautees']}, {net['part_sautees']:.3f})")
    chk(abime["sautees"] == 37 and abs(abime["part_sautees"] - 0.037) < 1e-9,
        f"…et 37 sauts sur 1000 frames donnent 3,7 %, le compte BRUT — jamais corrigé, jamais "
        f"lissé ({abime['sautees']}, {abime['part_sautees']:.3f})")

    # --- J. `--retour` ----------------------------------------------------------------
    _smoke_retour(chk)

    # --- K. AUCUN TEXTE SUR UNE CIBLE, à plusieurs résolutions --------------------------
    _smoke_textes(chk)

    # --- L. LE POINT DE FIXATION : le MÊME que celui du c-VEP et du P300 ---------------------
    # Sa présence image par image est relue en A bis (libre) et en J (guidé et libre, retour
    # branché). Ici : ses deux constantes, recopiées, comparées à leurs SOURCES — importées
    # ici seulement, une fenêtre n'en important pas une autre pour tourner.
    from stimulus import cvep as _cvep, p300 as _p300
    sources = {"cvep": (_cvep.FIX_DOT, _cvep.FIX_DOT_R), "p300": (_p300.FIX_DOT, _p300.FIX_DOT_R)}
    chk(all(v == (FIX_DOT, FIX_DOT_R) for v in sources.values()),
        f"[L] le point de fixation a la couleur et le rayon de ceux du c-VEP et du P300 "
        f"(ici {FIX_DOT}, {FIX_DOT_R} px ; {sources})")
    # …et la sonde ON/OFF ne tombe jamais dessus, à aucune taille jouée : DANS le disque, hors du
    # point, en deçà du contour (tracé sur 2 px au bord).
    fautes_sonde = []
    for taille in RESOLUTIONS_SMOKE:
        for jeu in (None, _SMOKE_QUATRE_CIBLES):
            pos, r, _c3, _a3 = geometrie(plan_du_stimulus(60.0, jeu), taille)
            for x, y in pos:
                sx, sy = point_de_sonde(x, y, r)
                d2 = (sx - x) ** 2 + (sy - y) ** 2
                if not (FIX_DOT_R + 1) ** 2 < d2 < (r - 2) ** 2:
                    fautes_sonde.append((taille, (x, y), (sx, sy)))
    chk(not fautes_sonde,
        f"[L] la sonde ON/OFF est DANS chaque disque, hors du point de fixation et du contour, aux "
        f"{len(RESOLUTIONS_SMOKE)} tailles jouées (fautes {fautes_sonde[:2]})")

    print(f"[ssvep-stim] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_retour(chk):
    """J. L'ANNEAU DE RETOUR, sur l'écran factice, avec une source de décisions FACTICE.

    Un run GUIDÉ, où un moteur factice répond à chaque `cue` par la décision de son script à la
    FIN EXACTE de la fixation (comme le vrai, qui prélève sa dernière fenêtre là, et pas une image
    plus tard : aucune marge offerte au test) ; puis le décodage LIBRE, où la source rend des
    décisions à des lectures fixées et un `status` factice dit quand le moteur se repose. Tout est
    lu dans les PIXELS, et la désignation bleue — LE test de la moitié guidée — est relue."""
    import pygame
    import pylsl

    from stimulus import retour as rt

    plan = plan_du_stimulus(60.0)
    positions, rayon_disque, rayon_cue, _local = geometrie(plan, TAILLE_FENETRE)
    # ⚠️ La règle COMMUNE, rappelée ICI et pas lue dans `geometrie` : un rayon local qui
    # s'écarterait de `retour.rayon_anneau` serait sinon d'accord avec lui-même.
    rayon = rt.rayon_anneau(rayon_disque)
    milieu = (TAILLE_FENETRE[0] / 2, TAILLE_FENETRE[1] / 2)
    trace, source = [], [None]
    vrai_flip, vrai_push = pygame.display.flip, pylsl.StreamOutlet.push_sample
    empreinte = _empreinte_point()

    def flip(*a, **k):
        r = vrai_flip(*a, **k)
        s = pygame.display.get_surface()
        trace.append(("flip", rt.anneaux_a_l_ecran(s, positions, rayon),
                      _cible_designee_a_l_ecran(s, positions, rayon_cue),
                      rt.croix_a_l_ecran(s, milieu, DIM),
                      _etats_a_l_ecran(s, positions, rayon_disque),
                      # le rayon EXACT de tout anneau à l'écran, autour de n'importe quel disque
                      {v for v in (_rayon_lu(s, p, rt.COULEUR_DECODEE, 2 * rayon)
                                   for p in positions) if v is not None},
                      _points_a_l_ecran(s, positions, empreinte)))
        return r

    def push(self, *a, **k):
        m = json.loads(a[0][0])
        trace.append(("push", m.get("event"), m))
        if hasattr(source[0], "marqueur"):
            source[0].marqueur(m)
        return vrai_push(self, *a, **k)

    duree = 0.3
    # ⚠️ `delai=duree` EXACTEMENT : la décision part à la fin de la fixation, comme celle du vrai
    # moteur (`ssvep_mesure` la date `cue` + `SSVEP_GUIDE_FIX_S`). Un « + 0,1 s » ici masquait la
    # course à marge nulle de la fermeture de l'essai (revue C-M4).
    moteur = rt.MoteurFactice(len(plan), ["juste", "faux", "rien", "tard", "faux", "juste"],
                              depart="cue", ouverture="cue", delai=duree, secondes=True,
                              trace=trace)
    statut = rt.StatutScripte({1: "warmup", 6: "baseline", 10: "decoding", 22: "baseline",
                               26: "decoding"})
    pygame.display.flip, pylsl.StreamOutlet.push_sample = flip, push
    try:
        with rt.Instrumentation(trace) as garde_guide:
            source[0] = moteur
            fait = run(windowed=True, refresh=60.0, guide=True, per_target=2, seed=5,
                       stream=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
                       attente_moteur_s=0.0, cue_s=duree, fix_s=duree, gap_s=duree,
                       repos_s=_SMOKE_REPOS_S, retour=True, source_retour=moteur)
            trace_g = list(trace)
            trace.clear()
        with rt.Instrumentation(trace) as garde_libre:
            source[0] = rt.SourceScriptee({5: 1, 15: -1, 20: 2}, trace=trace)
            run(smoke=True, refresh=60.0, retour=True, source_retour=source[0],
                source_statut=statut)
            trace_l = list(trace)
    finally:
        pygame.display.flip, pylsl.StreamOutlet.push_sample = vrai_flip, vrai_push

    images = [e for e in trace_g if e[0] == "flip"]
    n, cues, cibles = -1, [], []
    for e in trace_g:
        if e[0] == "flip":
            n += 1
        elif e[0] == "push" and e[1] == "cue":
            cues.append(n)
            cibles.append(e[2]["target"])
    chk(fait and len(cues) == 6 and len(moteur.attendues) == 6,
        f"[J] le run guidé avec retour va au bout : 6 fixations, 6 décisions scriptées "
        f"({len(cues)}, {len(moteur.attendues)})")
    # La fenêtre de retour d'un essai : son retour à la croix, des images sans désignation qui
    # suivent sa fixation, jusqu'à la consigne suivante.
    fenetres = []
    for c in cues:
        i = c
        while i < len(images) and images[i][2] != -1:
            i += 1
        j = i
        while j < len(images) and images[j][2] == -1:
            j += 1
        fenetres.append(range(i, j))
    vus = [sorted({tuple(images[i][1]) for i in w} - {()}) for w in fenetres]
    attendus = [[tuple(a)] if a else [] for a in (rt.anneau_attendu(*x) for x in moteur.attendues)]
    chk(vus == attendus,
        f"[J] l'anneau VERT entoure le disque DÉCIDÉ, désigné ou non, rien "
        f"sur −1 ni pour une décision arrivée pendant la fixation suivante — et une décision "
        f"publiée à la fin EXACTE de la fixation trouve son essai fermé — lu dans les PIXELS "
        f"(vus {vus}, attendus {attendus})")
    vus_justes = [a for x, a in zip(moteur.attendues, vus) if a and x[1] == x[2]]
    vus_faux = [a for x, a in zip(moteur.attendues, vus) if a and x[1] != x[2]]
    chk(bool(vus_justes) and bool(vus_faux),
        "[J] …et l'anneau a réellement été vu sur la cible désignée ET sur une autre (un test qui "
        "ne voit qu'un cas ne prouve rien sur l'autre)")
    # Un anneau ne coexiste JAMAIS avec une désignation : ni pendant la fixation (les données
    # notées), ni pendant la consigne qui la précède (le regard s'y déplace, le grand titre y est).
    designe = [i for i, im in enumerate(images) if im[1] and im[2] != -1]
    chk(not designe,
        f"[J] AUCUN anneau dès la consigne suivante — ni pendant la consigne, ni pendant la "
        f"fixation, ni pour la décision tardive ({len(designe)} image(s) fautive(s))")
    relues = [(images[c][2], cible) for c, cible in zip(cues, cibles)]
    chk(len(relues) == 6 and all(a == b for a, b in relues),
        f"[J] retour branché, la cible DÉSIGNÉE se relit toujours dans les pixels au `cue` "
        f"({relues})")
    chk(garde_guide.traces > 10 and garde_guide.violations == 0 and garde_guide.croix > 10,
        f"[J] ni l'anneau ni la croix ne recouvrent un pixel non-fond — ni disque, ni cercle de "
        f"consigne, ni étiquette : {garde_guide.violations} pixel(s) touché(s) sur "
        f"{garde_guide.traces} + {garde_guide.croix} tracés")
    fautes = rt.ordre_de_lecture(trace_g, {"repos", "cue"})
    lectures = sum(1 for e in trace_g if e[0] == "lecture")
    chk(not fautes and lectures == len(images),
        f"[J] le retour se lit UNE fois par image, APRÈS son flip et son marqueur ({lectures} "
        f"lectures pour {len(images)} images, fautes {fautes[:3]})")

    images_l = [e for e in trace_l if e[0] == "flip"]
    anneaux_l = [e[1] for e in images_l]
    attendus_l = [[]] * 5 + [[(1, rt.COULEUR_DECODEE)]] * 15 + [[(2, rt.COULEUR_DECODEE)]] * 10
    chk(len(anneaux_l) == 30 and anneaux_l == attendus_l and garde_libre.violations == 0,
        f"[J] libre : l'anneau VERT suit la dernière décision dès l'image suivante, un −1 ne "
        f"l'éteint PAS, et il ne touche aucun pixel non-fond (images "
        f"{[i for i, (a, b) in enumerate(zip(anneaux_l, attendus_l)) if a != b][:5]} en "
        f"désaccord, {garde_libre.violations} pixel(s) touché(s))")
    croix_l = [e[3] for e in images_l]
    croix_attendue = [i < 10 or 22 <= i < 26 for i in range(len(images_l))]
    # Pendant la croix, CHAQUE disque continue de clignoter : le plancher se mesure dans les
    # conditions visuelles du décodage, lu dans les pixels (allumé ET éteint au moins une fois).
    etats_croix = [e[4] for e, c in zip(images_l, croix_l) if c]
    clignotent = [len({etat[k] for etat in etats_croix}) == 2 for k in range(len(plan))]
    chk(croix_l == croix_attendue and garde_libre.croix > 0 and all(clignotent),
        f"[J] libre : la croix de repos tant que le `status` du moteur dit chauffe ou plancher, et "
        f"de NOUVEAU quand il refait son repos — disques toujours clignotants (images "
        f"{[i for i, (a, b) in enumerate(zip(croix_l, croix_attendue)) if a != b][:5]} en "
        f"désaccord, clignotement sous la croix {clignotent})")
    # L. Le point de fixation, en guidé (chauffe, repos, consigne, fixation, pause) et en libre,
    # anneau de retour branché : au centre de chaque disque, à chaque image, allumé ET éteint.
    for regime, imgs in (("guidé", images), ("libre", images_l)):
        faute = _smoke_points([(e[4], e[6]) for e in imgs], len(plan))
        chk(faute is None,
            f"[L] {regime} avec retour : le point rouge est au centre de CHAQUE disque, à chaque "
            f"image, allumé ET éteint, lu dans les PIXELS ({faute or 'ok'}, {len(imgs)} images)")
    # La TAILLE de l'anneau : la règle commune aux trois fenêtres (demandé au QA le 2026-10-02,
    # « uniformise »), au pixel près, en guidé comme en libre.
    rayons_vus = set().union(*(e[5] for e in images + images_l))
    chk(rayons_vus == {rayon},
        f"[J] l'anneau est tracé au rayon de `retour.rayon_anneau` — la règle du P300 — lu au "
        f"pixel près dans les PIXELS (rayons vus {sorted(rayons_vus)}, attendu {rayon})")

    nom = rt.flux_decode_de("ssvep")
    chk(nom == "EEG_API_Unicorn_decoded_ssvep",
        f"le retour écoute le flux PUBLIC du mode, lu dans son contrat — le nom que "
        f"l'application d'un étudiant résout ({nom})")
    rt.autotest_etat(chk)
    rt.autotest_source(chk)
    rt.autotest_couleurs(chk)
    rt.autotest_resolution(chk, run, "ssvep")
    rt.autotest_statut(chk)


# Les tailles que la section K joue : les trois écrans courants, et une petite fenêtre qui force les
# deux replis de `mise_en_page` — sous les cibles à 3 cibles, police RÉDUITE à 4.
RESOLUTIONS_SMOKE = ((1920, 1080), (1280, 720), (1000, 700), (900, 500))
_SMOKE_QUATRE_CIBLES = [12.0, 15.0, 20.0, 10.0]


class _Relais(list):
    """Un `journal` qui relaie chaque marqueur publié au moteur FACTICE — le `push` espionné de la
    section J, sans toucher à pylsl."""

    def __init__(self, moteur):
        super().__init__()
        self.moteur = moteur

    def append(self, entree):
        super().append(entree)
        self.moteur.marqueur(entree[0])


def _rect_touche(rect, centre, garde):
    """True si un pixel de `rect` est à moins de `garde` de `centre`. Écrite ICI, sans
    `_hors_des_cibles` : la garde ne doit pas partager le calcul de ce qu'elle garde."""
    xs = np.arange(rect.left, rect.right) - int(centre[0])
    ys = np.arange(rect.top, rect.bottom) - int(centre[1])
    if not xs.size or not ys.size:
        return False
    return int(np.abs(xs).min()) ** 2 + int(np.abs(ys).min()) ** 2 < garde ** 2


def _pixels_etrangers(surface, centre, garde, palette, empreinte):
    """Combien de pixels à moins de `garde` de `centre` ne sont d'AUCUNE couleur de `palette` —
    hormis le point de fixation : `FIX_DOT` n'est permis QUE sur `empreinte`, autour du centre.

    `draw.circle` ne lisse pas : le disque, son contour, son point, la consigne et l'anneau sont des
    couleurs EXACTES. Un texte, lui, est lissé — ses bords ne sont d'aucune couleur de la palette.
    Le rouge n'entre PAS dans la palette : permis partout, il laisserait passer un second point, ou
    un point décalé, sans un mot."""
    import pygame

    x, y = int(centre[0]), int(centre[1])
    zone = pygame.Rect(x - garde, y - garde, 2 * garde + 1, 2 * garde + 1).clip(surface.get_rect())
    px = pygame.surfarray.array3d(surface.subsurface(zone)).astype(np.int64)
    dx = np.arange(zone.left, zone.right)[:, None] - x
    dy = np.arange(zone.top, zone.bottom)[None, :] - y
    dedans = dx ** 2 + dy ** 2 < garde ** 2
    code = (px[..., 0] << 16) | (px[..., 1] << 8) | px[..., 2]
    permis = np.isin(code, [(r << 16) | (g << 8) | b for r, g, b in palette])
    a_sa_place = np.zeros(dedans.shape, dtype=bool)
    for ex, ey in empreinte:
        i, j = x + ex - zone.left, y + ey - zone.top
        if 0 <= i < a_sa_place.shape[0] and 0 <= j < a_sa_place.shape[1]:
            a_sa_place[i, j] = True
    permis |= a_sa_place & (code == ((FIX_DOT[0] << 16) | (FIX_DOT[1] << 8) | FIX_DOT[2]))
    return int((dedans & ~permis).sum())


def _smoke_textes(chk):
    """K. AUCUN TEXTE SUR UNE CIBLE — ni sur la zone de son anneau — à chaque résolution jouée.

    Le défaut (2026-10-02) : en `--guide`, le titre et le sous-titre étaient posés à 10 % de la
    hauteur, PAR-DESSUS le haut du disque AVANT pendant qu'il clignotait. Rien ne le voyait : les
    sondes lisent UN point de chaque disque et le cercle de consigne, jamais le reste de leur
    surface.

    Deux lectures, indépendantes de `mise_en_page` (qui ne pourrait que se donner raison) :
    • le RECTANGLE de chaque texte réellement posé (`pose_texte`, espionné), contre le disque de
      rayon `retour.rayon_anneau(rayon) + retour.EPAISSEUR_PX` de chaque cible — la règle COMMUNE,
      rappelée ici ; les textes d'une même image ne se chevauchent pas et restent à l'écran ;
    • les PIXELS de chaque zone après chaque flip : rien que le fond, le disque et son contour, son
      point de fixation rouge (à sa place exacte, et nulle part ailleurs), la consigne bleue et
      l'anneau vert.
    Chaque régime qui écrit est joué à chaque taille de `RESOLUTIONS_SMOKE` : le guidé avec retour
    (chauffe, repos, consigne, fixation, pause), à 3 cibles et à 4 ; l'essai libre avec retour
    (croix de chauffe et de repos, puis décodage), à 3. Un texte attendu qui n'a jamais été posé
    rougit aussi : une garde qui ne voit pas le texte ne prouve rien sur lui."""
    import contextlib
    import inspect
    import io

    import pygame

    from stimulus import retour as rt

    # Tout texte passe par `pose_texte` : un `blit` direct échapperait à l'espion ci-dessous.
    source = inspect.getsource(run) + inspect.getsource(_guide)
    chk(".blit" not in source and "pose_texte(" in source,
        "[K] tout texte de la fenêtre passe par `pose_texte` — aucun `blit` direct dans `run` ni "
        "`_guide`, qui échapperait à la garde des rectangles")

    module = sys.modules[__name__]
    vrai_pose, vrai_flip, taille_avant = module.pose_texte, pygame.display.flip, TAILLE_FENETRE
    palette = (BG, ON_COLOR, OUTLINE, CUE, rt.COULEUR_DECODEE)
    # Le point de fixation est permis à SA place et nulle part ailleurs. Précondition, sur une
    # toile : disque + point au centre -> 0 étranger ; un pixel rouge de plus à mi-rayon, ou le
    # point décalé d'un pixel -> des étrangers. Sinon « accepter le point » voudrait dire
    # « accepter le rouge ».
    empreinte = _empreinte_point()
    etrangers = []
    for decale, en_trop in ((0, False), (0, True), (1, False)):
        toile = pygame.Surface((121, 121))
        toile.fill(BG)
        pygame.draw.circle(toile, ON_COLOR, (60, 60), 40)
        pygame.draw.circle(toile, FIX_DOT, (60 + decale, 60), FIX_DOT_R)
        if en_trop:
            toile.set_at(point_de_sonde(60, 60, 40), FIX_DOT)
        etrangers.append(_pixels_etrangers(toile, (60, 60), 50, palette, empreinte))
    chk(etrangers[0] == 0 and etrangers[1] > 0 and etrangers[2] > 0,
        f"[K] (précondition) la garde des zones accepte le point rouge à SA place, et lui seul : "
        f"{etrangers[0]} étranger(s) pour le point centré, {etrangers[1]} pour un pixel rouge en "
        f"trop, {etrangers[2]} pour le point décalé d'un pixel")
    queue_hud = HUD_TEXTE.rsplit("}", 1)[1]
    pages = []
    try:
        for taille in RESOLUTIONS_SMOKE:
            for freqs in (None, _SMOKE_QUATRE_CIBLES):
                plan = plan_du_stimulus(60.0, freqs)
                positions, rayon, _c, _a = geometrie(plan, taille)
                garde = rt.rayon_anneau(rayon) + rt.EPAISSEUR_PX     # la règle COMMUNE, rappelée
                ecran = pygame.Rect((0, 0), taille)
                image, vus = [], set()
                f = {"disque": [], "texte": [], "ecran": [], "pixels": 0, "images": 0,
                     "anneaux": 0}

                def pose(win, police, texte, couleur, **ancre):
                    rect = vrai_pose(win, police, texte, couleur, **ancre)
                    image.append((texte, pygame.Rect(rect)))
                    return rect

                def flip(*a, **k):
                    r = vrai_flip(*a, **k)
                    s = pygame.display.get_surface()
                    for i, (texte, rect) in enumerate(image):
                        vus.add(texte)
                        if any(_rect_touche(rect, p, garde) for p in positions):
                            f["disque"].append((texte, tuple(rect)))
                        if not ecran.contains(rect):
                            f["ecran"].append((texte, tuple(rect)))
                        f["texte"] += [(texte, t) for t, r2 in image[i + 1:] if rect.colliderect(r2)]
                    f["pixels"] += sum(_pixels_etrangers(s, p, garde, palette, empreinte)
                                       for p in positions)
                    f["anneaux"] += bool(rt.anneaux_a_l_ecran(s, positions, rt.rayon_anneau(rayon)))
                    f["images"] += 1
                    image.clear()
                    return r

                moteur = rt.MoteurFactice(len(plan), ["juste", "faux"] * 2, depart="cue",
                                          ouverture="cue", delai=0.05, secondes=True)
                module.TAILLE_FENETRE = taille
                module.pose_texte, pygame.display.flip = pose, flip
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        fait = run(windowed=True, refresh=60.0, guide=True, per_target=1, seed=5,
                                   freqs=freqs, stream=MARKER_STREAM_DEFAULT + "_smoke",
                                   attente_consommateur_s=0.0, attente_moteur_s=0.05, cue_s=0.05,
                                   fix_s=0.08, gap_s=0.1, repos_s=0.05, journal=_Relais(moteur),
                                   retour=True, source_retour=moteur)
                        # L'essai libre : UNE fois par taille, au plan du dépôt. Même `page`, même
                        # `dessine` que le guidé — ce qu'il ajoute est SA boucle, jouée à chaque
                        # taille ; chaque `run` coûte ~2 à 5 s d'ouverture/fermeture de pygame.
                        if freqs is None:
                            run(smoke=True, refresh=60.0, freqs=freqs, retour=True,
                                source_retour=rt.SourceScriptee({3: 0, 22: len(plan) - 1}),
                                source_statut=rt.StatutScripte({1: "warmup", 10: "baseline",
                                                                20: "decoding"}))
                finally:
                    module.pose_texte, pygame.display.flip = vrai_pose, vrai_flip

                # Pour le MESSAGE et la précondition seulement : la garde, elle, a lu l'écran.
                pygame.font.init()
                page = mise_en_page(pygame, plan, taille, len(plan))
                pygame.font.quit()
                pages.append(page)
                noms = [c["name"] for c in plan]
                attendus = ({TITRE_CHAUFFE, SOUS_CHAUFFE, TITRE_REPOS, SOUS_REPOS, SOUS_FIXATION,
                             TITRE_PAUSE, SOUS_PAUSE} | set(noms)
                            | {TITRE_CONSIGNE.format(nom=n) for n in noms}
                            | {SOUS_CONSIGNE.format(i=i, n=len(plan))
                               for i in range(1, len(plan) + 1)}
                            | {etiquette(c) for c in plan})
                manquants = sorted(attendus - vus)
                hud_vu = any(t.endswith(queue_hud) for t in vus)
                nom = (f"{taille[0]}×{taille[1]}, {len(plan)} cibles, "
                       + ("guidé + libre" if freqs is None else "guidé"))
                chk(fait and not f["disque"] and not manquants and hud_vu,
                    f"[K] {nom} : AUCUN texte posé sur un disque ni sur la zone de son anneau "
                    f"(rayon {garde} px) — {len(vus)} textes vus en {f['images']} images, titres "
                    f"{page.ou} à {page.echelle:.0%} ; fautes {f['disque'][:2]}, jamais posés "
                    f"{manquants[:3]}, HUD {'vu' if hud_vu else 'JAMAIS vu'}")
                chk(not f["pixels"] and not f["texte"] and not f["ecran"] and f["anneaux"] > 0,
                    f"[K] {nom} : dans chaque zone, rien que le disque, son point rouge, la "
                    f"consigne bleue et l'anneau vert, lu dans les PIXELS ({f['pixels']} "
                    f"pixel(s) étranger(s), anneau vu sur {f['anneaux']} images) ; textes ni "
                    f"superposés {f['texte'][:2]} ni hors de l'écran {f['ecran'][:2]}")
    finally:
        module.pose_texte, pygame.display.flip = vrai_pose, vrai_flip
        module.TAILLE_FENETRE = taille_avant
    # Une garde qui ne joue que la bande du haut ne dit rien des deux replis.
    bandes = sorted({p.ou for p in pages})
    chk(bandes == ["en bas", "en haut"] and min(p.echelle for p in pages) < 1.0,
        f"[K] (précondition) les tailles jouées couvrent la bande du haut, celle du bas ET une "
        f"police réduite ({bandes}, échelles {sorted({p.echelle for p in pages})})")


# Les durées du smoke : courtes, parce qu'on teste la LIGNE DU TEMPS et pas la physiologie. Elles
# ne portent PAS les noms des constantes du protocole (`_SMOKE_` en préfixe) — le contrôle E
# ci-dessus refuse toute réécriture locale de `FIX_S` & co., et ce refus doit rester lisible.
_SMOKE_CUE_S, _SMOKE_FIX_S, _SMOKE_GAP_S, _SMOKE_REPOS_S = 0.10, 0.20, 0.08, 0.15


def _rejouer_guide(per_target, seed, seconds=None, journal=None):
    """Joue une séance guidée entière sur un écran factice. Rend (journal, cibles AFFICHÉES).

    `journal` peut être fourni par l'appelant quand il veut y MÊLER autre chose — la partie F du
    smoke y intercale les `flip` pour vérifier l'ordre des deux appels.
    """
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    journal, designees = ([] if journal is None else journal), []
    _p, _r, rayon_cue, _a = geometrie(plan_du_stimulus(60.0), TAILLE_FENETRE)
    run(windowed=True, refresh=60.0, guide=True, per_target=per_target, seed=seed,
        seconds=seconds, stream=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
        attente_moteur_s=0.0, cue_s=_SMOKE_CUE_S, fix_s=_SMOKE_FIX_S, gap_s=_SMOKE_GAP_S,
        repos_s=_SMOKE_REPOS_S, journal=journal,
        sonde_ecran=lambda surface, positions: designees.append(
            _cible_designee_a_l_ecran(surface, positions, rayon_cue)))
    return journal, designees


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Stimulus SSVEP (EEG_API_Unicorn).")
    p.add_argument("--windowed", action="store_true", help="fenetre au lieu du plein ecran")
    p.add_argument("--refresh", type=float, default=None, help="forcer le refresh (Hz)")
    p.add_argument("--seconds", type=float, default=None, help="auto-quit apres N secondes")
    p.add_argument("--freqs", type=str, default=None,
                   help="LES FRÉQUENCES DU MODE, séparées par des virgules (ex. « 12,15,20 ») — "
                        "c'est ce que la console passe elle-même quand elle lance cette fenêtre. "
                        "Le nombre de cibles est la LONGUEUR de la liste, 4 au maximum (la "
                        "géométrie a quatre places). Sans l'option, le jeu du dépôt. ⚠️ Une "
                        "fréquence qui ne divise pas le rafraîchissement est REFUSÉE (sortie 2), "
                        "jamais arrondie en silence : arrondie, elle ferait clignoter autre chose "
                        "que ce contre quoi le moteur corrèle")
    p.add_argument("--guide", action="store_true",
                   help="run GUIDÉ : désigne une cible par essai et publie la vérité-terrain sur "
                        "le flux de marqueurs. C'est le moteur qui MESURE — la console lance "
                        "cette fenêtre elle-même, la lancer à la main n'a de sens que pour la "
                        "mettre au point")
    p.add_argument("--trials", type=int, default=SSVEP_GUIDE_TRIALS_PER_TARGET,
                   help=f"essais par cible en mode guidé (défaut {SSVEP_GUIDE_TRIALS_PER_TARGET}, "
                        f"soit {SSVEP_GUIDE_TRIALS_PER_TARGET * 3} essais à 3 cibles). Sans "
                        f"--guide, ce réglage ne sert à rien")
    p.add_argument("--seed", type=int, default=None,
                   help="graine du tirage de l'ordre des essais (rejouer le même ordre)")
    p.add_argument("--retour", action="store_true",
                   help="entoure en vert la cible que le moteur DÉCODE, lue sur le flux public "
                        "decoded_ssvep en tâche de fond (avec --guide : après chaque essai)")
    p.add_argument("--smoke", action="store_true", help="test headless (SDL dummy), n'affiche rien")
    return p.parse_args(argv)


def _refuse(raison):
    """Dit le refus et sort en 2. Rien n'a été affiché — et c'est le message qui doit rester.

    ⚠️ Sortie **2**, distincte du 1 d'une séance interrompue. La console lance cette fenêtre :
    « elle a refusé de s'ouvrir » et « elle s'est arrêtée en route » appellent deux gestes
    différents, et un code de retour unique les confondrait.
    """
    print(f"[ssvep-stim] ⚠️ REFUS : {raison}")
    print("[ssvep-stim] rien n'a été affiché. Une fréquence arrondie en silence ferait clignoter "
          "autre chose que ce contre quoi le moteur corrèle : il ne décoderait pas mal, il ne "
          "décoderait RIEN, et rien ne le dirait.")
    sys.exit(2)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    if args.smoke:
        sys.exit(0 if sous_garde_data(_smoke) else 1)
    freqs = None
    if args.freqs is not None:
        freqs, raison = parse_freqs(args.freqs)
        if raison is not None:
            _refuse(raison)
    try:
        fait = run(windowed=args.windowed, refresh=args.refresh, seconds=args.seconds,
                   guide=args.guide, per_target=args.trials, seed=args.seed, freqs=freqs,
                   retour=args.retour)
    except FreqsRefusees as refus:
        # ⚠️ Le refus ne peut tomber qu'ICI, et pas plus tôt : sans `--refresh`, le
        # rafraîchissement est MESURÉ, donc on ne sait qu'après l'ouverture de l'écran si ces
        # fréquences en sont des diviseurs.
        _refuse(refus)
    # Une séance guidée INTERROMPUE sort en 1 : lancée depuis la console, « elle s'est fermée » et
    # « elle est allée au bout » ne doivent pas se ressembler.
    sys.exit(0 if fait else 1)
