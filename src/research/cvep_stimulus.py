"""Le stimulus c-VEP, en programme AUTONOME qui publie l'HORLOGE du code.

⚠️ **Ce programme n'ouvre PAS le casque.** C'est ce qui permet de le lancer EN MÊME TEMPS que le
moteur, dans deux terminaux — le même montage que pour le P300 et l'ErrP :

    python src/core/server.py --mode cvep          # terminal 1 : acquiert et décode (EXIGE un
                                                    # modèle entraîné, cf. research/app.py -> c-VEP)
    python src/research/cvep_stimulus.py           # terminal 2 : fait clignoter et marque

C'est aussi l'exemple de référence pour qui voudra émettre depuis Unity : le protocole est ici,
et surtout l'endroit exact où prendre l'horodatage.

Protocole publié (figé, cf. docs/SPEC.md) — UNE SEULE forme de marqueur, sur le flux
`MARKER_STREAM_DEFAULT` (core/config.py), type "Markers", 1 voie "string", cadence irrégulière :

    {"mode": "cvep", "event": "cycle", "refresh": 60.0}   # la m-séquence vient de repartir à 0

⚠️ **Ce marqueur ne délimite AUCUNE époque — il tient une HORLOGE**, et c'est toute la différence
avec `p300_stimulus.py` et `errp_stimulus.py`. Là-bas un marqueur dit « un événement a eu lieu,
découpe autour » ; ici il dit « à cet instant, le code affiché était à sa frame 0 ». Le moteur
décode ensuite en CONTINU sur une fenêtre glissante et reconstruit, à tout instant, la position du
code à partir de ce marqueur : c'est la **phase** (`core/modes/cvep.py:phase_a`). Sans elle, il ne
décode rien du tout — il ne sait pas contre quoi corréler.

⚠️ **La panne caractéristique de ce mode NE CASSE RIEN, et c'est pour ça que ce fichier existe.**
Une erreur de phase de quelques frames ne lève aucune exception : les corrélations baissent, le
moteur continue de publier, ses scores restent d'apparence honnête, et la détection se contente de
ne presque jamais se déclencher. À l'écran c'est **indiscernable d'un étudiant qui ne fixe pas sa
cible**. Deux gestes la produisent, et ils sont à une ligne l'un de l'autre :

    1. horodater AVANT `pygame.display.flip()` au lieu d'après (une frame d'avance) ;
    2. annoncer un `refresh` que l'écran ne tient pas (le moteur extrapole à la mauvaise vitesse).

Le premier est le geste critique, identique aux deux autres émetteurs :

    pygame.display.flip()
    # L'HORODATAGE SE PREND ICI, juste après que la frame est À L'ÉCRAN. Le prendre avant décale
    # TOUTES les phases d'une frame, et le décodeur cherche alors le code à un endroit où il n'est
    # pas — sans qu'aucune exception ne le signale.
    if frame % len(code) == 0:
        outlet.push_sample([json.dumps({"mode": "cvep", "event": "cycle",
                                        "refresh": refresh})], local_clock())

C'est LA raison d'être de ce fichier, donc ce que `--smoke` vérifie le plus durement — mais **pas
comme `errp_stimulus.py`, et la différence vaut d'être lue avant de recopier son test.** Là-bas,
l'assertion qui mord est « le flip qui précède le marqueur est celui qui a CHANGÉ l'écran » : elle
marche parce qu'entre deux feedbacks la piste est IMMOBILE, donc remonter le `push_sample`
au-dessus du `flip` le fait tomber sur une frame identique à la précédente. Ici l'écran change à
CHAQUE frame (c'est le clignotement), donc ce critère-là serait VERT quoi qu'on fasse — un test
creux. Le critère c-VEP est plus exigeant : le flip qui précède le marqueur doit être celui qui a
affiché la **frame 0 du code**, ni la 62 ni la 1. `--smoke` le lit dans les PIXELS de l'écran (voir
`_smoke`, section « l'alignement ») : il échantillonne l'état ON/OFF des six disques et le compare
au code attendu. Inverser les deux lignes ci-dessus le fait rougir.

⚠️ **Ce que ce fichier NE fait pas comme `errp_stimulus.py` non plus : il ne s'arrête pas pendant
la chauffe du moteur.** L'ErrP tient un écran statique pendant que le moteur chauffe, parce que
`errp._jeter_marqueurs_de_chauffe` JETTE tout ce qui arrive alors — les pas joués pendant ce
temps seraient perdus. Le c-VEP fait l'INVERSE, et c'est écrit dans `CVEPRuntime.tick` : il
ENCAISSE les marqueurs de chauffe, « une horloge n'a pas besoin d'être bonne pour être à l'heure ».
Les lui donner règle deux choses — le curseur de marqueurs du moteur avance (sinon la douzaine de
marqueurs déjà sortis de son tampon compte en `marqueurs_perdus`, une alarme fausse à chaque
démarrage), et sa première fenêtre décodée l'est avec une phase FRAÎCHE. Le clignotement démarre
donc tout de suite ; seul le décompte de `--seconds` attend, et un bandeau dit que le décodage n'a
pas encore commencé. La durée est LUE dans `core/modes/cvep.py` (`SPEC.rest`), pas devinée :
`warmup_s = SSVEP_WARMUP_S` (15 s) et `duration_s = 0.0` — le c-VEP ne mesure aucun plancher de
repos, il corrèle contre un template appris.

⚠️ **La CIBLE CONSIGNÉE (le cercle autour d'un disque) n'est pas de la décoration, et elle ne part
JAMAIS sur le réseau.** Une séance c-VEP sans vérité-terrain ne se dépouille pas : le moteur publie
un indice de cible, et sans savoir laquelle était fixée on ne peut rien en conclure — ni justesse,
ni ITR, rien qui ne soit du bruit. La consigne est donc AFFICHÉE (l'utilisateur sait quoi fixer) et
IMPRIMÉE au terminal avec son horodatage LSL exact (`t=…`), comme `errp_stimulus.py` imprime ses
pas : il suffit à raccrocher chaque ligne à l'échantillon `decoded_cvep` correspondant. Le marqueur,
lui, ne porte que `{mode, event, refresh}` — rien d'autre, le moteur n'en lit pas plus. `--seed`
rejoue la même SÉQUENCE de consignes (sa LONGUEUR, elle, peut différer d'une consigne quand la
séance est bornée en secondes : cf. le ⚠️ de `poll`), et la graine est IMPRIMÉE même quand on ne la
donne pas : une séance casque ne se répète pas, donc une séance qu'on ne peut pas rejouer ne se
dépouille pas deux fois. Le cercle est tracé à 1,7× le rayon du disque, LOIN à l'extérieur : posé dessus, un
contour lumineux statique écraserait la modulation de contraste du stimulus (même choix, et même
raison, que `research/ui.py:draw_ring`).

⚠️ **`--log CHEMIN` écrit cette vérité-terrain dans un FICHIER, et sans lui la séance 2.9 n'est pas
dépouillable.** Le terminal ne suffit pas : c'est le seul exemplaire de la consigne, un `Ctrl+C`
malheureux ou un tampon de console dépassé l'efface, et une séance casque ne se répète pas. Le
format est du **JSONL** — une ligne JSON par événement, écrite puis vidée (`flush`) tout de suite —
pour que le fichier reste complet jusqu'à la dernière ligne même si le programme est tué. Trois
genres de ligne, et rien d'autre :

    {"kind":"header","t":…,"seed":…,"refresh":60.0,"code_len":63,"cibles":[…], …}
    {"kind":"consigne","t":…,"compter_a_partir_de":…,"cible":2,"nom":"AR-DROITE","cycle":9,"frame":504}
    {"kind":"bilan","cycles":286,"frames":18018,"sautees":3,"cadence_s":1.0501, …}

⚠️ **`t` et `compter_a_partir_de` sont des `local_clock()`** : EXACTEMENT le domaine des horodatages
que porte `decoded_cvep`, et que `examples/receiver.py` imprime en tête de chaque ligne (`t=…`).
Le dépouillement devient alors une comparaison de nombres — « cet échantillon est-il postérieur au
`compter_a_partir_de` de sa consigne ? » — au lieu d'un rapprochement à l'œil entre deux fenêtres de
terminal, qui est faux la première fois. La ligne `bilan` recopie VERBATIM le dictionnaire de
`bilan_de_seance` : une seule source pour ce qui s'imprime et ce qui s'écrit.

⚠️ L'option est **opt-in et sans valeur par défaut**, pour trois raisons : `--smoke` ne doit jamais
pouvoir écrire quoi que ce soit hors d'un dossier temporaire, `data/` ne doit rien recevoir d'ici, et
l'opérateur nomme son journal comme il nomme sa séance. Le fichier est ouvert en AJOUT : relancer
l'émetteur sur le même chemin empile les séances au lieu d'en effacer une.

⚠️⚠️ **COMMENT DÉPOUILLER, et le piège qui fabrique un faux verdict.** Le moteur ne publie pas un
verdict par consigne : il décode en continu à 5 Hz. Après un changement de consigne, il lui faut
recharger DEUX mémoires avant qu'un échantillon ne parle de la nouvelle cible — sa fenêtre de
décision (`CVEP_DECISION_CYCLES` cycles = 2,1 s) puis son vote glissant (`CVEP_VOTE_LEN` fenêtres
espacées de `ModeRuntime.period_s()` = 0,6 s), soit **2,7 s pendant lesquelles chaque échantillon
publié est calculé sur du signal à cheval sur DEUX cibles**. Noter tous les `decoded_cvep` de
`[t_consigne, t_consigne + durée]` compte donc ces 2,7 s dans le score, et **plafonne la justesse
mesurée quel que soit le décodeur** : à l'ancien réglage (4 cycles = 4,2 s par consigne) la
transition couvrait 64 % de l'intervalle, donc ~40 % au maximum — de quoi conclure que le décodeur
ne marche pas en regardant une transition. D'où deux remèdes appliqués ensemble : la consigne dure
maintenant `CYCLES_PAR_CIBLE` = 8 cycles (8,4 s, dont 5,7 s exploitables = 68 %), et chaque ligne
`t=` imprime l'instant « **compter à partir de** ». **Ne note que les échantillons postérieurs à
cet instant-là.**

⚠️ **Pas de `valide_reglages` comme `p300_stimulus.py` — et ce n'est pas un oubli.** Le P300 doit
refuser `--targets 4` parce que le moteur code six cibles en dur et que la probabilité oddball
changerait. Ici il n'y a RIEN à régler qui touche le décodage : la géométrie (`CVEP_N_TARGETS`), le
code (`CVEP_BITS`/`CVEP_TAPS`) et les lags viennent tous de `core/cvep_code.build_targets()`, le
MÊME appel que fait le moteur. Émetteur et moteur ne peuvent pas diverger sans que `core/config.py`
change pour les deux à la fois. Le seul réglage qui puisse dérégler le décodage est `--refresh`, et
le moteur le REFUSE lui-même, bruyamment, quand il s'écarte de plus de 1 Hz de celui auquel le
modèle a été calibré (`CVEPRuntime.maj_reference`) — c'est-à-dire au bon endroit : celui qui
connaît le modèle.

Lancer :
    python src/research/cvep_stimulus.py                  # plein écran, ESC pour quitter
    python src/research/cvep_stimulus.py --windowed       # fenêtre 1000x700 (dev)
    python src/research/cvep_stimulus.py --refresh 60     # forcer le refresh (sinon auto-mesuré)
    python src/research/cvep_stimulus.py --seconds 20     # 20 s de STIMULATION DÉCODABLE (la
                                                          # chauffe du moteur ne compte pas)
    python src/research/cvep_stimulus.py --seed 1         # rejouer la même SÉQUENCE de consignes
    python src/research/cvep_stimulus.py --log seance.jsonl  # la VÉRITÉ-TERRAIN dans un fichier :
                                                          # sans elle, la séance ne se dépouille pas
    python src/research/cvep_stimulus.py --no-wait        # ne pas attendre le moteur (émetteur seul)
    python src/research/cvep_stimulus.py --smoke          # test sans écran (CI) : phase ET rendu
"""

import argparse
import json
import math
import os
import random
import statistics
import sys
import time

# Permet `from core.config import ...` que le module soit lancé via
# `python src/research/cvep_stimulus.py` ou importé comme `research.cvep_stimulus`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (CVEP_BITS, CVEP_DECISION_CYCLES, CVEP_VOTE_LEN,  # noqa: E402
                         MARKER_STREAM_DEFAULT, SSVEP_WARMUP_S, use_utf8_console)
from core.cvep_code import build_targets, is_on  # noqa: E402
from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, local_clock  # noqa: E402

# --- Réglages d'affichage ---------------------------------------------------

BG = (0, 0, 0)              # fond noir -> profondeur de modulation maximale
ON_COLOR = (255, 255, 255)  # disque allumé
OUTLINE = (55, 55, 70)      # contour statique : garde le repère spatial quand la cible est OFF
FIX_DOT = (200, 40, 40)     # point de fixation CHROMATIQUE (cf. research/ui.py : la réponse c-VEP
#                             est pilotée par la LUMINANCE, un point rouge n'ampute donc quasiment
#                             pas la modulation tout en restant visible allumé comme éteint)
ACCENT = (60, 200, 90)      # le cercle de consigne, LARGEMENT à l'extérieur du disque
LABEL = (120, 120, 140)
HUD = (70, 90, 70)
NOTE = (110, 150, 110)      # le bandeau de chauffe : vert éteint, ne concurrence pas le stimulus

# Rayon du point de fixation, en PIXELS et non proportionnel — la MÊME valeur que
# `research/ui.py:FIX_DOT_R`, celle sous laquelle les modèles c-VEP ont été calibrés. Quelques
# pixels suffisent à ancrer le regard, et l'emprise sur le stimulus reste négligeable (~0,1 % de la
# surface) quelle que soit la résolution.
FIX_DOT_R = 2

# La couronne : ratios de `research/ui.py:ring_spots`, c'est-à-dire la géométrie EXACTE sous
# laquelle `research/app.py` a enregistré les époques de calibration. Les changer, c'est afficher un
# stimulus que le modèle n'a jamais vu — sans qu'aucune exception ne le dise.
DIST_RATIO = 0.31
TAILLE_RATIO = 0.075

TAILLE_FENETRE = (1000, 700)   # `--windowed` (dev) et `--smoke`

# --- LA PÉRIODE INEXPLOITABLE, et pourquoi elle doit être écrite noir sur blanc ---------------
#
# ⚠️ **Après un changement de consigne, les premières secondes de `decoded_cvep` sont FAUSSES par
# construction, et rien dans le flux ne le dit.** Le moteur a DEUX mémoires en amont de chaque
# échantillon publié :
#   1. la FENÊTRE de décision — `CVEP_DECISION_CYCLES` cycles de code (2 x 63/60 = 2,1 s), repliés
#      puis corrélés ;
#   2. le VOTE GLISSANT — `CVEP_VOTE_LEN` fenêtres (3) espacées de la période du mode
#      (`ModeRuntime.period_s()` = 0,2 s, non redéfinie par `CVEPRuntime`), soit 0,6 s de plus.
# Tant que ces deux mémoires n'ont pas été ENTIÈREMENT rechargées depuis le changement, chaque
# échantillon publié est calculé sur du signal à cheval sur DEUX cibles.
#
# ⚠️ **C'est un générateur de faux verdict pour la recette.** Quelqu'un qui note tous les
# `decoded_cvep` de `[t_consigne, t_consigne + durée]` compte ces échantillons-là dans son score et
# conclut que le décodeur ne marche pas. À l'ancien réglage (4 cycles = 4,2 s), la transition
# couvrait 2,7 s sur 4,2 — soit **64 % des échantillons**, donc une justesse mesurée qui ne pouvait
# pas dépasser ~40 % même avec un décodage parfait. Deux remèdes, appliqués tous les deux :
#   • la consigne dure maintenant TROIS fois la transition, pour que la part exploitable DOMINE ;
#   • et chaque ligne `t=` du terminal imprime l'instant À PARTIR DUQUEL les échantillons comptent,
#     pour qu'un dépouillement n'ait pas à redécouvrir ce calcul (cf. `run`).
# `--smoke` arrime les deux constantes du moteur à leur source (cf. `_smoke`, section « la
# transition ») : recopiées ici, elles dériveraient en silence.
PERIODE_MOTEUR_S = 0.2        # `core/modes/runtime.py:ModeRuntime.period_s` — 5 Hz de décodage
TRANSITION_S = CVEP_DECISION_CYCLES * (2 ** CVEP_BITS - 1) / 60.0 + CVEP_VOTE_LEN * PERIODE_MOTEUR_S

# Combien de cycles du code une même cible reste consignée. DÉRIVÉ de la transition ci-dessus, pas
# posé à la main : trois fois la transition -> deux tiers de la consigne sont exploitables. À 60 Hz
# et aux réglages du dépôt : 8 cycles = 8,4 s, dont 2,7 s à jeter et 5,7 s à compter (68 %).
CYCLES_PAR_CIBLE = int(math.ceil(3 * TRANSITION_S * 60.0 / (2 ** CVEP_BITS - 1)))

# Ce que le moteur fait avant de décoder pour de bon : sa chauffe (l'offset DC de l'Unicorn dérive
# après ouverture). Valeurs LUES dans `core/modes/cvep.py` (SPEC.rest) : `warmup_s=SSVEP_WARMUP_S`,
# `duration_s=0.0` — le c-VEP ne mesure aucun plancher de repos, contrairement au SSVEP/neuro/ErrP.
# ⚠️ Le clignotement, lui, NE S'ARRÊTE PAS pendant ce temps : cf. le ⚠️ de la docstring du module.
ATTENTE_MOTEUR_S = SSVEP_WARMUP_S + 0.0

# Une image qui met plus que ça à basculer est une frame SAUTÉE. 1,5 période : un demi-intervalle de
# marge de part et d'autre, assez pour ne pas compter la gigue ordinaire du planificateur, assez peu
# pour attraper une image manquée. Le compte est AFFICHÉ, jamais corrigé — une frame sautée décale le
# code d'une frame jusqu'au marqueur suivant, et c'est le marqueur qui la résorbe (cf. `_smoke`).
SEUIL_SAUT = 1.5


# --- Géométrie (fonctions PURES, testables sans écran ni pygame) -------------

def positions_cibles(plan, size, dist_ratio=DIST_RATIO, size_ratio=TAILLE_RATIO):
    """`[(x, y, rayon), ...]` DANS L'ORDRE DU PLAN — donc dans l'ordre des indices publiés.

    C'est `research/ui.py:ring_spots` réduit à ce dont un émetteur a besoin (pas de dictionnaire
    indexé par nom : ici l'ordre EST l'information, `plan[i]` correspond à `score_i` sur le flux).
    Les angles sont LUS dans le plan, jamais recalculés en `2πi/n` : `cvep_targets(3)` reprend
    exactement les angles de `COMMANDS` et ne fait PAS trois tiers de tour — deux géométries pour le
    même protocole, et l'écran ne montrerait plus les cibles sur lesquelles le modèle a été entraîné
    (le piège que `p300_stimulus.target_positions` documente déjà).
    """
    w, h = size
    cx, cy, span = w / 2.0, h / 2.0, float(min(w, h))
    dist, r = span * dist_ratio, span * size_ratio
    return [(int(cx + math.sin(c["angle"]) * dist),
             int(cy - math.cos(c["angle"]) * dist),   # y écran vers le bas
             int(r)) for c in plan]


def point_de_sonde(x, y, r):
    """Un point de l'écran où l'état ON/OFF d'un disque se LIT dans les pixels.

    Existe pour `--smoke`, qui doit savoir ce qui est réellement affiché sans croire l'émetteur sur
    parole. PAS le centre : le point de fixation y est dessiné, et sa couleur ne dit rien de l'état
    du disque. À mi-rayon on est à l'intérieur du disque (donc blanc quand il est allumé) et à
    l'intérieur du contour (donc fond noir quand il est éteint).
    """
    return (x + r // 2, y)


def diagnostic_cadence(mesure_s, cycle_theorique_s, refresh, code_len, tolerance=0.02):
    """`(derive, avertissement)` — `avertissement` est None quand l'écran tient la cadence annoncée.

    ⚠️ **C'est la JUMELLE du geste flip->horodatage, et elle produit exactement la même panne
    muette.** Le marqueur dit « le code était à sa frame 0 à cet instant » ; entre deux marqueurs,
    le moteur EXTRAPOLE la phase à `refresh` Hz (`CVEPRuntime.phase_a` : `int(age * refresh)`). Si
    l'écran n'affiche pas à cette vitesse-là, la phase dérive à l'intérieur de chaque cycle sans
    qu'aucune exception ne soit levée : les corrélations baissent, le moteur publie, et rien ne dit
    pourquoi. Le cas concret est un écran 144 Hz lancé avec `--refresh 60` — le moteur ACCEPTE les
    marqueurs (le modèle est calibré à 60, l'émetteur annonce 60, `maj_reference` ne voit rien
    d'anormal) et décode contre une phase qui part de ~8 % par cycle.
    Une SEULE fonction produit ce verdict, et c'est elle que `--smoke` interroge point par point :
    l'écrire à même le bilan la laissait sans aucune assertion — trois mutations d'une ligne
    (comparaison inversée, compteur neutralisé, bloc supprimé) passaient toutes au vert.

    `tolerance` = 2 % : un écran 59,94 Hz annoncé à 60 dérive de 0,1 %, un vrai désaccord de mode
    d'affichage dépasse toujours les 2 % (le plus serré, 60 contre 59,94/1,001, reste sous ; le
    plus courant, 60 contre 75, fait 25 %).
    """
    derive = (float(mesure_s) - float(cycle_theorique_s)) / float(cycle_theorique_s)
    if abs(derive) < tolerance:
        return derive, None
    reel = code_len / float(mesure_s)
    return derive, (
        f"⚠️ l'écran ne tient PAS les {refresh:.0f} Hz publiés dans les marqueurs (il affiche "
        f"plutôt à {reel:.0f} Hz) : le moteur extrapole la phase à {refresh:.0f} Hz ENTRE deux "
        f"marqueurs, donc il décode contre un code qui a déjà glissé. Relance avec "
        f"`--refresh {reel:.0f}` si c'est le vrai rafraîchissement — et RECALIBRE, un modèle est "
        f"calibré à UN rafraîchissement — sinon cherche ce qui charge la machine.")


def bilan_de_seance(cycles, frames, sautees, onsets, refresh, code_len):
    """Le bilan de fin : ce qu'on IMPRIME et ce que `--smoke` relit, au même endroit.

    Un bilan qui ne serait qu'une suite de `print` n'est gardé par aucune assertion — et c'est
    précisément le bloc qui porte le diagnostic de la seconde panne muette de ce mode. Il rend donc
    un dictionnaire, que `run` recopie dans son paramètre `bilan` : les deux ne peuvent pas diverger
    puisqu'il n'y a qu'une source. Supprimer l'appel fait rougir le smoke ; le laisser en place mais
    casser le compteur de frames sautées aussi (cf. `_smoke`, passage C3).
    """
    cycle_theorique = code_len / float(refresh)
    mesure = (statistics.median(b - a for a, b in zip(onsets, onsets[1:]))
              if len(onsets) > 1 else None)
    derive, avertissement = (diagnostic_cadence(mesure, cycle_theorique, refresh, code_len)
                             if mesure is not None else (None, None))
    if frames:
        print(f"[cvep-stim] fin : {cycles} cycles émis, {frames} frames affichées, "
              f"{sautees} sautée(s) ({sautees / frames:.1%})")
    else:
        print(f"[cvep-stim] fin : {cycles} cycles émis, aucune frame affichée")
    if mesure is not None:
        print(f"[cvep-stim] cadence : {mesure * 1000:.1f} ms par cycle mesuré contre "
              f"{cycle_theorique * 1000:.1f} ms annoncés ({derive:+.1%})"
              + ("" if avertissement is None else "  " + avertissement))
    if not cycles:
        print("[cvep-stim] ⚠️ AUCUN marqueur n'est parti : `--seconds` couvre-t-il bien la durée "
              "de stimulation voulue, la fenêtre a-t-elle été fermée tout de suite ?")
    return {"cycles": cycles, "frames": frames, "sautees": sautees, "cadence_s": mesure,
            "derive": derive, "avertissement": avertissement}


def tirage_cible(rng, n_cibles, precedente=None):
    """L'indice de la prochaine cible consignée — jamais deux fois la MÊME de suite.

    Sans cette contrainte, une consigne sur six est invisible : le cercle reste au même endroit et
    l'utilisateur ne sait pas qu'un nouvel essai a commencé, donc son regard ne se recale pas. Même
    raisonnement, et même remède, que la contrainte de jonction de `p300_stimulus.blocs_melanges`.
    Sans effet si une seule cible existe : il n'y a alors aucune alternative à tirer.
    """
    n_cibles = int(n_cibles)
    if n_cibles <= 1:
        return 0
    tirage = rng.randrange(n_cibles)
    while tirage == precedente:
        tirage = rng.randrange(n_cibles)
    return tirage


# --- Boucle principale -------------------------------------------------------

def run(windowed=False, refresh=None, seconds=None, smoke=False,
        stream_name=MARKER_STREAM_DEFAULT, attente_consommateur_s=5.0, journal=None,
        seed=None, attente_moteur_s=None, cycles_par_cible=CYCLES_PAR_CIBLE, bilan=None,
        max_frames=None, log_path=None):
    """La boucle du stimulus. `journal`, s'il est fourni, reçoit `(marqueur, horodatage, frame,
    consigne)` pour CHAQUE marqueur de cycle réellement poussé ; `bilan`, s'il est fourni, reçoit
    le dictionnaire de `bilan_de_seance` — c'est ce qui permet à `--smoke` d'ASSERTER sur le
    diagnostic de fin au lieu de le laisser en simples `print` que rien ne garde.

    `log_path` (l'option `--log`) écrit la VÉRITÉ-TERRAIN en JSONL, cf. le ⚠️ de la docstring du
    module. C'est l'équivalent PERSISTANT de ce que `journal` donne à `--smoke` : un fichier, donc
    dépouillable après la séance, alors que `journal` vit en mémoire et que le terminal s'efface.

    `frame` (le compteur de l'émetteur) et `consigne` (le NOM de la cible à fixer) ne partent
    JAMAIS sur le réseau — le marqueur ne porte que `{mode, event, refresh}`, cf. le ⚠️ de la
    docstring du module. Ils n'existent que pour permettre à `--smoke` de vérifier, sur le déroulé
    RÉEL, qu'un marqueur part à chaque redémarrage du code et que la consigne tourne.

    `seed` graine le tirage des consignes : deux exécutions rejouent alors la MÊME séquence de
    cibles, ce qui est la seule façon de refaire une séance à l'identique. `attente_moteur_s`
    n'existe que pour que `--smoke` puisse EXERCER le bandeau de chauffe sans attendre 15 s.

    `max_frames` borne la séance en IMAGES au lieu de secondes. C'est ce qui rend le rejeu
    DÉTERMINISTE : à graine ET compte d'images égaux, deux exécutions produisent exactement la même
    séquence de consignes, quelle que soit la charge de la machine (cf. le ⚠️ de `poll`). Pas
    d'option de ligne de commande : une séance réelle se règle en secondes, c'est `--smoke` qui a
    besoin de reproductibilité à l'image près — même statut que `max_run_steps` chez
    `errp_stimulus.py`.
    """
    if smoke:
        return _smoke()

    # `--refresh 0` (ou négatif) divisait par zéro au premier `L / refresh`, APRÈS avoir ouvert la
    # fenêtre : traceback nu, pas de `pygame.quit()`, écran plein resté à l'écran. Le refus se pose
    # donc AVANT d'ouvrir quoi que ce soit, comme `p300_stimulus.valide_reglages`.
    if refresh is not None and float(refresh) <= 0.0:
        print(f"[cvep-stim] REFUSÉ — --refresh {refresh} : un rafraîchissement est un nombre de "
              f"frames par seconde, donc strictement positif. Laisse l'option de côté pour qu'il "
              f"soit mesuré à l'écran.")
        return False

    # Le journal s'ouvre AVANT la fenêtre, pour la même raison que le refus ci-dessus : un dossier
    # qui n'existe pas, un disque plein ou un fichier verrouillé doivent se dire au terminal, pas
    # sous un plein écran qu'on ne peut plus quitter. Ouvert en AJOUT ("a") : deux séances sur le
    # même chemin s'empilent, aucune ne s'efface.
    fichier_log = None
    if log_path:
        try:
            fichier_log = open(log_path, "a", encoding="utf-8")
        except OSError as e:
            print(f"[cvep-stim] REFUSÉ — --log {log_path} : impossible d'écrire ici ({e}). "
                  f"Sans journal, la séance ne se dépouille pas : choisis un chemin valide.")
            return False
        print(f"[cvep-stim] journal (vérité-terrain, JSONL) : {log_path}")

    def note_json(objet):
        """Une ligne JSON, écrite ET VIDÉE tout de suite. Le `flush` est le point de l'exercice :
        un émetteur tué au milieu d'une séance laisse alors un fichier complet jusqu'à sa dernière
        ligne, ce qu'un JSON global écrit à la fin ne permettrait pas."""
        if fichier_log is None:
            return
        fichier_log.write(json.dumps(objet, ensure_ascii=False) + "\n")
        fichier_log.flush()

    import pygame  # import tardif : le module s'importe même sans pygame installé

    from research.ssvep_stimulus import measure_refresh  # même mesure que les autres stimuli

    plan, code = build_targets()
    L = len(code)
    attente_moteur_s = ATTENTE_MOTEUR_S if attente_moteur_s is None else float(attente_moteur_s)

    pygame.init()
    pygame.font.init()

    if windowed:
        size = TAILLE_FENETRE
        flags = pygame.SCALED
    else:
        disp_info = pygame.display.Info()
        size = (disp_info.current_w, disp_info.current_h)
        flags = pygame.FULLSCREEN | pygame.SCALED

    # vsync=1 : le code est cadencé par le balayage écran, comme les autres stimuli — et ici c'est
    # plus qu'un confort. Le moteur extrapole la phase à `refresh` Hz entre deux marqueurs ; sans
    # vsync, l'écran affiche à la vitesse du processeur et la phase reconstruite est fausse dès la
    # deuxième frame, sans qu'aucune exception ne le signale.
    try:
        win = pygame.display.set_mode(size, flags, vsync=1)
    except (TypeError, pygame.error):
        win = pygame.display.set_mode(size, flags)
    pygame.display.set_caption("c-VEP stimulus — EEG_API_Unicorn")
    pygame.mouse.set_visible(False)

    if refresh is None:
        refresh = measure_refresh(pygame, win)

    # Le flux de marqueurs : nom et type FIGÉS (contrat public, core/config.py). `source_id`
    # unique par PID -> deux instances de ce stimulus ne se confondent jamais l'une l'autre.
    info = StreamInfo(stream_name, "Markers", 1, IRREGULAR_RATE, "string",
                      f"cvep-stim-{os.getpid()}")
    outlet = StreamOutlet(info)

    print(f"[cvep-stim] refresh écran   : {refresh:.0f} Hz")
    print(f"[cvep-stim] {len(plan)} cibles, code de {L} frames -> un cycle (et un marqueur) toutes "
          f"les {L / refresh:.3f} s ; consigne tenue {cycles_par_cible} cycles "
          f"({cycles_par_cible * L / refresh:.1f} s)")
    print(f"[cvep-stim] marqueurs publiés sur « {stream_name} » : "
          f'{{"mode": "cvep", "event": "cycle", "refresh": {refresh:.1f}}}')
    print(f"[cvep-stim] ⚠️ le moteur REFUSE ces marqueurs si son modèle a été calibré à plus de "
          f"1 Hz d'écart de {refresh:.1f} Hz — il le dit, mais lis ses premières lignes")
    # ⚠️ La graine est TIRÉE quand elle n'est pas donnée, et IMPRIMÉE dans TOUS les cas. Sans ça,
    # une séance lancée sans `--seed` était irrejouable — et personne ne le savait, puisque rien ne
    # s'affichait. Or une séance casque ne se répète pas : c'est la seule ligne qui permette de la
    # rejouer plus tard pour la dépouiller autrement.
    if seed is None:
        seed = random.randrange(2 ** 31)
    print(f"[cvep-stim] graine {seed} — REJOUE cette séance à l'identique avec `--seed {seed}`")
    transition_s = CVEP_DECISION_CYCLES * L / refresh + CVEP_VOTE_LEN * PERIODE_MOTEUR_S
    print(f"[cvep-stim] ⚠️ DÉPOUILLEMENT : les {transition_s:.1f} s qui suivent CHAQUE changement "
          f"de consigne sont INEXPLOITABLES — la fenêtre de décision du moteur "
          f"({CVEP_DECISION_CYCLES} cycles) et son vote ({CVEP_VOTE_LEN} fenêtres) y sont encore à "
          f"cheval sur la cible précédente. Chaque ligne « cycle » ci-dessous donne l'instant "
          f"« compter à partir de » : ne note les `decoded_cvep` qu'À PARTIR DE LÀ, sinon tu "
          f"mesures une justesse plafonnée par la transition, pas par le décodeur.")
    note_json({"kind": "header", "t": local_clock(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "seed": int(seed), "refresh": float(refresh), "code_len": int(L),
               "n_targets": len(plan), "cycles_par_cible": int(cycles_par_cible),
               "transition_s": round(float(transition_s), 4), "stream": stream_name,
               "cibles": [c["name"] for c in plan]})

    # ⚠️ Attendre le moteur AVANT de compter la stimulation — même raisonnement que les deux autres
    # émetteurs : sans ça, un étudiant qui a oublié de lancer le moteur regarde un écran
    # parfaitement fonctionnel sans le moindre signe que personne n'écoute. L'attente est BORNÉE et
    # on clignote de toute façon.
    #
    # ⚠️ Et ici on CLIGNOTE PENDANT la chauffe, contrairement à `errp_stimulus.py` qui tient un
    # écran statique : `CVEPRuntime.tick` ENCAISSE les marqueurs de chauffe (cf. le ⚠️ de la
    # docstring du module). Seul le décompte de `--seconds` attend.
    note = None
    fin_note = 0.0
    t_start = time.perf_counter()
    if attente_consommateur_s > 0:
        if not outlet.wait_for_consumers(attente_consommateur_s):
            print(f"[cvep-stim] ⚠️ PERSONNE n'écoute « {stream_name} » après "
                  f"{attente_consommateur_s:g} s. Le moteur est-il lancé "
                  f"(`python src/core/server.py --mode cvep`) ? Je clignote quand même — "
                  f"l'indicateur en haut de l'écran dit qui écoute, en direct.")
        else:
            print("[cvep-stim] le moteur écoute.")
        # Le bandeau est tenu dans les DEUX cas, et c'est voulu : `wait_for_consumers` répond
        # « non » aussi pendant que le moteur résout son inlet, c'est-à-dire exactement quand il
        # démarre — le moment où sa chauffe commence. `--no-wait` reste là pour s'en passer.
        print(f"[cvep-stim] le moteur chauffe ~{attente_moteur_s:g} s "
              f"(core/modes/cvep.py, SPEC.rest) : il ENCAISSE l'horloge pendant ce temps mais ne "
              f"décode pas encore. Le clignotement démarre tout de suite ; `--seconds` ne compte "
              f"qu'après.")
        note = f"le moteur chauffe (~{attente_moteur_s:g} s) — fixe la cible entourée"
        fin_note = time.perf_counter() + attente_moteur_s
        t_start = None

    spots = positions_cibles(plan, size)
    span = min(size)
    font = pygame.font.SysFont("consolas", max(14, int(span * 0.022)))
    hud_font = pygame.font.SysFont("consolas", max(12, int(span * 0.016)))
    note_font = pygame.font.SysFont("consolas", max(16, int(span * 0.030)))

    clock = pygame.time.Clock()
    rng = random.Random(seed)
    running = True
    frame = 0
    cycles = 0
    sautees = 0
    onsets = []                  # horodatages LSL des marqueurs -> cadence réelle des cycles
    i_cible = None

    def emet(m, consigne):
        """Pousse un marqueur et l'horodate. UN SEUL endroit prend `local_clock()`."""
        ts = local_clock()
        outlet.push_sample([json.dumps(m)], timestamp=ts)
        if journal is not None:
            journal.append((m, ts, frame, consigne))
        return ts

    def poll():
        """Événements + les deux limites d'arrêt, vérifiés à CHAQUE frame. Le c-VEP n'a pas d'unité
        plus grosse qu'une frame à protéger : contrairement au P300 et à l'ErrP, aucun marqueur
        déjà parti n'attend une fenêtre de signal derrière lui (les siens tiennent une horloge, ils
        ne délimitent pas d'époque) — on peut donc couper net, à la frame près.

        ⚠️ `max_frames` compte des IMAGES là où `--seconds` compte des secondes, et ce n'est pas un
        doublon : une durée dépend de l'ordonnanceur, un compte d'images non. C'est ce qui rend une
        séance REJOUABLE À L'IDENTIQUE — le tirage des consignes est graine par graine, mais deux
        exécutions bornées par le temps ne s'arrêtent pas forcément sur la même image, donc la
        seconde peut avoir une consigne de plus. Mesuré par la revue : 1 exécution sur ~8 rendait
        des journaux de longueurs différentes (4 consignes contre 5, préfixe identique). C'est la
        borne en temps qui était en cause, jamais la graine. Un stimulus verrouillé à la frame se
        borne donc en frames.
        """
        nonlocal running
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False
        if max_frames is not None and frame >= int(max_frames):
            running = False
        if seconds is not None and t_start is not None and (time.perf_counter() - t_start) >= seconds:
            running = False

    def draw(f, consigne):
        win.fill(BG)
        for i, (x, y, r) in enumerate(spots):
            pygame.draw.circle(win, OUTLINE, (x, y), r, 2)     # repère quand la cible est OFF
            if is_on(f, plan[i]["code"]):
                pygame.draw.circle(win, ON_COLOR, (x, y), r)
            pygame.draw.circle(win, FIX_DOT, (x, y), FIX_DOT_R)   # ancre le regard
            lab = font.render(plan[i]["name"], True, LABEL)
            win.blit(lab, lab.get_rect(center=(x, y + int(r * 1.9))))
        if consigne is not None:
            # ⚠️ 1,7× le rayon : LARGEMENT à l'extérieur du disque. Posé dessus, ce contour
            # lumineux STATIQUE écraserait la modulation de contraste — même valeur, et même
            # raison, que `research/ui.py:draw_ring`.
            x, y, r = spots[consigne]
            pygame.draw.circle(win, ACCENT, (x, y), int(r * 1.7), 4)
        if note is not None:
            txt = note_font.render(note, True, NOTE)
            win.blit(txt, txt.get_rect(center=(int(size[0] / 2), int(size[1] * 0.93))))
        # L'indicateur d'écoute, en direct : c'est la seule chose de cet écran qui distingue
        # « ça marche » de « ça a l'air de marcher ».
        ecoute = "moteur À L'ÉCOUTE" if outlet.have_consumers() else "PERSONNE n'écoute"
        hud = hud_font.render(
            f"cycles {cycles}  |  {refresh:.0f} fps  |  sautées {sautees}  |  "
            f"fixe « {plan[consigne]['name'] if consigne is not None else '—'} »  |  {ecoute}  |  "
            f"ESC = quitter", True, HUD)
        win.blit(hud, (12, 10))

    t_flip_precedent = None
    while running:
        poll()
        if not running:
            break
        # La consigne change au BORD d'un cycle, jamais au milieu : le moteur décide sur des
        # cycles entiers, et une consigne qui bougerait en cours de cycle rendrait la fenêtre de
        # décision à cheval sur deux cibles — donc impossible à dépouiller.
        if frame % (L * cycles_par_cible) == 0:
            i_cible = tirage_cible(rng, len(plan), i_cible)
        draw(frame, i_cible)
        pygame.display.flip()
        # ⚠️ L'HORODATAGE SE PREND ICI, juste après que la frame est À L'ÉCRAN. Le prendre avant
        # décale TOUTES les phases d'une frame, et le décodeur cherche alors le code à un endroit
        # où il n'est pas — sans qu'aucune exception ne le signale, avec des corrélations qui
        # baissent juste assez pour qu'on accuse la personne de mal fixer.
        if frame % L == 0:
            ts = emet({"mode": "cvep", "event": "cycle", "refresh": float(refresh)},
                      plan[i_cible]["name"])
            onsets.append(ts)
            cycles += 1
            # `t=` est l'horodatage LSL EXACT du marqueur : c'est lui qui permet, après la séance,
            # de raccrocher cette ligne aux échantillons `decoded_cvep` correspondants et de
            # calculer une justesse — sans jamais mettre la consigne sur le réseau.
            if frame % (L * cycles_par_cible) == 0:
                # ⚠️ DEUX horodatages, et le second est celui qui compte pour un dépouillement :
                # `compter à partir de` = `t` + la transition. Avant lui, chaque `decoded_cvep`
                # est calculé sur une fenêtre à cheval sur la cible PRÉCÉDENTE — les compter fait
                # mesurer la transition, pas le décodeur (cf. le ⚠️ de TRANSITION_S).
                print(f"[cvep-stim] t={ts:.3f}  cycle {cycles} : fixe « {plan[i_cible]['name']} » "
                      f"(cible {i_cible})  —  compter à partir de t={ts + transition_s:.3f} "
                      f"(+{transition_s:.1f} s de transition)")
                # La MÊME ligne, dans le fichier : c'est celle-ci qui survit à la séance. Une
                # entrée par CONSIGNE (~36 pour 5 min), pas par cycle — c'est toute la
                # vérité-terrain, et le reste se recalcule.
                note_json({"kind": "consigne", "t": round(ts, 6),
                           "compter_a_partir_de": round(ts + transition_s, 6),
                           "cible": int(i_cible), "nom": plan[i_cible]["name"],
                           "cycle": int(cycles), "frame": int(frame)})
        t_flip = time.perf_counter()
        if t_flip_precedent is not None and (t_flip - t_flip_precedent) > SEUIL_SAUT / refresh:
            sautees += 1
        t_flip_precedent = t_flip
        frame += 1
        if note is not None and t_flip >= fin_note:
            note = None
            t_start = time.perf_counter()   # LA STIMULATION DÉCODABLE commence ici
        clock.tick(int(refresh) + 5)

    # Un BILAN, toujours : « 0 cycle joué » doit se lire, pas se deviner. Et surtout la CADENCE
    # RÉELLE — c'est le seul chiffre de cette séance qui dise si le moteur a pu suivre l'horloge.
    # ⚠️ Il vit dans `bilan_de_seance`, PAS ici : un bilan écrit à même la boucle n'est qu'une
    # suite de `print` que rien ne garde, et c'est le bloc qui porte le diagnostic de la seconde
    # panne muette de ce mode. Une seule source pour ce qui s'imprime et ce que `--smoke` relit.
    resume = bilan_de_seance(cycles, frame, sautees, onsets, refresh, L)
    resume["graine"] = seed
    if bilan is not None:
        bilan.update(resume)
    # ⚠️ Le dictionnaire est recopié VERBATIM, jamais reconstruit : `bilan_de_seance` reste
    # l'unique source de ce qui s'imprime, de ce que `--smoke` relit et de ce qui s'écrit.
    note_json(dict(kind="bilan", **resume))
    if fichier_log is not None:
        fichier_log.close()   # chaque ligne est déjà vidée : ce `close` ne protège aucune donnée
    pygame.quit()
    return True


# --- --smoke : la phase (en pur), PUIS la boucle réelle sur un écran factice --

def _runtime_de_test(code_len=63, refresh=60.0):
    """Un `CVEPRuntime` prêt à tenir une horloge, sans moteur, sans casque et sans vrai `data/`.

    C'est le `_runtime_de_test` de `core/modes/cvep.py:_selftest`, réduit à ce dont le test de
    phase a besoin : un modèle au `code_len`/`refresh` voulus, sauvegardé dans un dossier
    TEMPORAIRE, chargé par le chemin RÉEL du runtime (`validate` puis construction).

    ⚠️ `core.modes.cvep.CVEP_MODEL_PATH` est repointé le temps de la construction, puis restauré :
    `data/` contient des enregistrements EEG d'une personne identifiable sur un dépôt public, et
    ce fichier ne doit ni le lire ni l'écrire. Le dossier temporaire part dans le `finally`.
    """
    import shutil
    import tempfile

    import numpy as np

    from core.config import CVEP_CHANNELS, CVEP_N_TARGETS
    from core.cvep_decoder import CVEPModel
    from core.modes import cvep as mode_cvep
    from core.modes.contract import validate

    modele = CVEPModel(fs=250.0, refresh=refresh, code_len=code_len, channels=CVEP_CHANNELS)
    modele.w = np.ones(len(CVEP_CHANNELS))
    modele.template = np.zeros(code_len)     # template PLAT : ce test ne décode rien, il compte
    modele.cv_ = 0.5                         # des frames — aucune corrélation n'est calculée ici

    dossier = tempfile.mkdtemp(prefix="cvep_stim_test_")
    avant = mode_cvep.CVEP_MODEL_PATH
    try:
        mode_cvep.CVEP_MODEL_PATH = modele.save(os.path.join(dossier, "cvep_model.npz"),
                                                n_targets=CVEP_N_TARGETS)
        valeurs, raison = validate(mode_cvep.SPEC, {})
        if raison is not None:
            raise RuntimeError(f"fabrique de test cassée : {raison}")
        return mode_cvep.CVEPRuntime(mode_cvep.SPEC, valeurs, engine=None)
    finally:
        mode_cvep.CVEP_MODEL_PATH = avant
        shutil.rmtree(dossier, ignore_errors=True)


def _course_de_phase(rt, refresh, L, t0=1000.0, cycles=8, saut_a=None):
    """Rejoue une course de rendu EN PUR et rend `[(frame, pos, ecart), ...]`, une entrée par image
    affichée. `ecart` = phase que le MOTEUR reconstruit MOINS phase que l'émetteur a AFFICHÉE,
    ramenée dans [-L/2, L/2[ (None si le moteur refuse de donner une phase).

    ⚠️ **Deux compteurs, et c'est tout le sujet.**
      • `pos`   : la position du code RÉELLEMENT AFFICHÉE — le compteur de l'émetteur, +1 par image
                  qu'il dessine, exactement le `frame` de `run()` ;
      • `frame` : la frame d'ÉCRAN écoulée depuis `t0` — l'horloge murale, +1 par balayage.
    Ils avancent ensemble, SAUF à `saut_a` où l'écran a basculé DEUX fois pendant que l'émetteur ne
    comptait qu'une image. C'est le cas qui arrive vraiment (vsync manqué, tour de boucle long), et
    c'est aussi le seul endroit où l'émetteur et le moteur ont le droit d'être en désaccord — d'une
    frame, et jusqu'au marqueur suivant.

    Les instants sont pris à `t0 = 1000 s` et non à 0 : `int(age * refresh)` tronque, et l'arrondi
    binaire de `1000.0 + 63/60.0 - 1000.0` ne vaut PAS 1,05 exactement. C'est ce que
    `core/modes/cvep.py:_EPS_FRAME` corrige, et une course de plusieurs centaines de frames est ce
    qui le vérifie ailleurs qu'au seul bord de cycle testé là-bas.
    """
    releve = []
    pos = frame = 0
    saute = False
    while pos < L * cycles:
        t = t0 + frame / refresh
        if pos % L == 0:
            # Le marqueur part APRÈS le flip de la frame 0 — donc à l'instant où l'écran la montre.
            rt.maj_reference(ts=t, refresh=refresh)
        vue = rt.phase_a(t)
        ecart = None if vue is None else (vue - pos % L + L // 2) % L - L // 2
        releve.append((frame, pos, ecart))
        if saut_a is not None and frame == saut_a and not saute:
            saute = True
            frame += 1          # l'écran a sauté une image ; le compteur de l'émetteur, non
        pos += 1
        frame += 1
    return releve


def _etat_ecran(pygame, sondes, seuil=3 * 128):
    """L'état ON/OFF de CHAQUE cible, lu dans les PIXELS — pas dans le compteur de l'émetteur.

    C'est ce qui permet à `--smoke` de dire QUELLE frame du code était à l'écran au moment du
    marqueur, sans jamais demander à l'émetteur de se noter lui-même. `None` si aucune surface
    n'existe encore (pygame fermé).

    ⚠️ **À QUELLE CONDITION cette sonde est valide — à lire avant de la recopier ailleurs.** Elle
    appelle `get_surface()` APRÈS `flip()` et suppose d'y lire la frame qui vient d'être affichée.
    C'est vrai sous le pilote `dummy` (que `--smoke` force), parce qu'il n'y a aucun échange de
    tampon : la surface reste celle qu'on vient de dessiner. Sous un pilote à **double tampon
    matériel**, `flip()` ÉCHANGE les tampons et `get_surface()` rend alors le tampon d'ARRIÈRE —
    c'est-à-dire l'image PRÉCÉDENTE, ou un contenu indéfini. La sonde y lirait une position de code
    décalée d'une frame et accuserait un émetteur correct. Elle n'est donc pas transposable telle
    quelle à un test qui tournerait sur un vrai écran : il faudrait alors prendre l'empreinte
    AVANT le `flip`, sur la surface qu'on vient de dessiner.
    """
    surface = pygame.display.get_surface()
    if surface is None:
        return None
    return tuple(sum(surface.get_at((x, y))[:3]) > seuil for x, y in sondes)


# Les deux durées du second passage de `--smoke` (le bandeau de chauffe, puis la stimulation
# décomptée). Nommées parce que DEUX assertions les relisent : une chauffe qui figerait l'écran ne
# se détecte qu'en comparant l'étendue des marqueurs à la seconde de ces deux durées.
C2_CHAUFFE_S = 0.8
C2_SECONDES = 1.5

# Combien de frames le passage C3 retient DÉLIBÉRÉMENT, pour que le compteur de frames sautées ait
# quelque chose à compter. Sous `dummy` il n'y a jamais de vsync manqué : sans ces cales, le
# compteur resterait à 0 en toutes circonstances et le neutraliser ne rougirait aucune assertion.
C3_CALES = 3


def _smoke():
    """Trois parties, et c'est la première qui porte le chantier.

    **A. LA PHASE.** Une course de rendu rejouée EN PUR, frame par frame, contre le `CVEPRuntime`
    RÉEL du moteur : à chaque image, la phase que le moteur reconstruirait est comparée à celle que
    l'émetteur a AFFICHÉE. C'est le seul test du dépôt qui rende visible la panne caractéristique de
    ce mode — quelques frames de décalage, aucune exception, des scores d'apparence honnête et une
    détection qui ne se déclenche presque jamais, indiscernable d'un étudiant qui ne fixe pas.

    **B. La géométrie**, en pur : la couronne, l'ordre des cibles, la contrainte de consigne.

    **C. `run()` POUR DE VRAI**, sur `SDL_VIDEODRIVER=dummy` — le patron de `p300_stimulus.py` et
    d'`errp_stimulus.py`. Un `--smoke` qui retournerait avant l'import de pygame laisserait SANS
    AUCUNE COUVERTURE les lignes qui contiennent le geste flip->horodatage, la seule chose que ce
    fichier existe pour enseigner. Et les exécuter ne suffit pas à les VÉRIFIER : `display.flip` et
    `StreamOutlet.push_sample` sont instrumentés pour enregistrer l'ordre RÉEL des deux gestes ET
    l'état ON/OFF des six disques, lu dans les pixels, à chaque flip.

    Ce qui n'est PAS revérifié ici : le transport LSL (mûrissement, horodatage, offset d'horloge)
    est déjà prouvé par `core/markers.py`.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # Posé AVANT tout import de pygame : aucun test de ce dépôt n'ouvre de fenêtre.
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

    plan, code = build_targets()
    L = len(code)

    # =====================================================================================
    # A. LA PHASE — LE test de ce fichier, et de tout le chantier c-VEP.
    # =====================================================================================
    refresh = 60.0
    rt = _runtime_de_test(code_len=L, refresh=refresh)
    saut_a = L * 3 + 17                       # une frame sautée, une seule, au milieu de la course
    releve = _course_de_phase(rt, refresh, L, cycles=8, saut_a=saut_a)
    ecarts = [e for _f, _p, e in releve]
    pires = [abs(e) for e in ecarts if e is not None]

    chk(len(pires) == len(ecarts),
        f"une phase est disponible à CHAQUE frame de la course ({len(pires)}/{len(ecarts)}) — "
        f"une seule fenêtre sans phase, et le moteur publie un -1 au lieu d'une cible")

    # Le premier marqueur du cycle qui SUIT le saut : c'est lui qui doit résorber l'erreur.
    resorption = ((saut_a // L) + 1) * L
    avant = [abs(e) for f, p, e in releve if e is not None and f <= saut_a]
    pendant = [abs(e) for f, p, e in releve if e is not None and f > saut_a and p < resorption]
    apres = [abs(e) for _f, p, e in releve if e is not None and p >= resorption]

    # ⚠️ **L'assertion qui mord, et elle exige ZÉRO, pas « au plus une frame ».** Une tolérance à
    # ±1 frame sur toute la course serait un test creux : décaler la phase d'une frame partout
    # (`int(age * refresh) + 1`) la laisserait VERTE. Avant le moindre saut, l'accord doit être
    # EXACT — c'est là, et seulement là, qu'un décalage systématique se voit.
    chk(bool(avant) and max(avant) == 0,
        f"tant qu'aucune frame n'est sautée, la phase reconstruite par le moteur est EXACTEMENT "
        f"celle que l'émetteur affiche, sur les {len(avant)} frames de la course (pire écart "
        f"{max(avant) if avant else '—'})")
    chk(bool(pendant) and max(pendant) <= 1,
        f"après une frame sautée, l'écart ne dépasse jamais UNE frame ({max(pendant) if pendant else '—'} "
        f"sur {len(pendant)} frames) — l'émetteur a une image de retard sur l'horloge murale, et "
        f"c'est tout")
    chk(bool(apres) and max(apres) == 0,
        f"...et le marqueur du cycle SUIVANT RÉSORBE l'erreur au lieu de la laisser s'accumuler "
        f"({len(apres)} frames après, pire écart {max(apres) if apres else '—'})")
    chk(bool(pires) and max(pires) <= 1,
        f"sur la course ENTIÈRE, l'écart entre la phase reconstruite et la phase AFFICHÉE ne "
        f"dépasse jamais UNE frame (pire écart mesuré : {max(pires) if pires else '—'} frames, "
        f"sur {len(pires)} frames)")

    # Le témoin de la mutation : sans frame sautée, l'accord doit être EXACT de bout en bout. Si
    # cette assertion et celle du « pendant » étaient confondues, une phase décalée d'une frame
    # passerait pour un saut d'image.
    propre = [abs(e) for _f, _p, e in _course_de_phase(rt, refresh, L, cycles=8) if e is not None]
    chk(bool(propre) and max(propre) == 0,
        f"une course SANS aucune frame sautée n'a aucun écart du tout, sur ses {len(propre)} "
        f"frames — sinon le décalage est dans la CONVENTION, pas dans l'écran")

    # =====================================================================================
    # B. La géométrie et la consigne, en pur
    # =====================================================================================
    spots = positions_cibles(plan, TAILLE_FENETRE)
    w, h = TAILLE_FENETRE
    chk(len(spots) == len(plan)
        and all(0 <= x < w and 0 <= y < h and r > 0 for x, y, r in spots),
        f"les {len(spots)} cibles tiennent dans la fenêtre {w}x{h} ({spots})")
    # L'ORDRE est le contrat public : `plan[i]` <-> `score_i` sur `decoded_cvep`. Une couronne
    # recalculée en 2πi/n donnerait le même dessin à 6 cibles et un autre à 3 (cf. la docstring de
    # `positions_cibles`) — on vérifie donc que l'angle du plan est bien celui du point.
    attendus = [(int(w / 2 + math.sin(c["angle"]) * min(w, h) * DIST_RATIO),
                 int(h / 2 - math.cos(c["angle"]) * min(w, h) * DIST_RATIO))
                for c in plan]
    chk([(x, y) for x, y, _r in spots] == attendus,
        "chaque point suit l'ANGLE de sa cible dans le plan, pas un i-ème de tour recalculé")
    sondes = [point_de_sonde(x, y, r) for x, y, r in spots]
    chk(all((px - x) ** 2 + (py - y) ** 2 < r ** 2 and (px, py) != (x, y)
            for (px, py), (x, y, r) in zip(sondes, spots)),
        "le point de sonde est DANS le disque et hors du point de fixation (sinon `--smoke` lirait "
        "la couleur du point rouge à la place de l'état ON/OFF)")

    # --- la TRANSITION : les deux constantes du moteur, arrimées à leur SOURCE ---------------
    # Recopiées ici, elles dériveraient en silence — et c'est le chiffre qu'un dépouillement lit
    # dans le terminal pour savoir quoi jeter. `period_s` surtout : ce n'est pas une constante de
    # `config.py` mais une méthode de `ModeRuntime`, que `CVEPRuntime` ne redéfinit pas.
    from core.modes.cvep import CVEPRuntime
    from core.modes.runtime import ModeRuntime
    chk(ModeRuntime.period_s(None) == PERIODE_MOTEUR_S
        and "period_s" not in CVEPRuntime.__dict__,
        f"la période du moteur ({PERIODE_MOTEUR_S:g} s) est bien celle de `ModeRuntime.period_s`, "
        f"et `CVEPRuntime` ne la redéfinit PAS "
        f"({ModeRuntime.period_s(None)}, redéfinie={'period_s' in CVEPRuntime.__dict__})")
    transition_attendue = CVEP_DECISION_CYCLES * L / 60.0 + CVEP_VOTE_LEN * PERIODE_MOTEUR_S
    chk(abs(TRANSITION_S - transition_attendue) < 1e-9,
        f"la période inexploitable après un changement de consigne vaut {TRANSITION_S:.2f} s "
        f"({CVEP_DECISION_CYCLES} cycles de décision = {CVEP_DECISION_CYCLES * L / 60.0:.2f} s + "
        f"{CVEP_VOTE_LEN} fenêtres de vote = {CVEP_VOTE_LEN * PERIODE_MOTEUR_S:.2f} s)")
    duree_consigne = CYCLES_PAR_CIBLE * L / 60.0
    part_exploitable = (duree_consigne - TRANSITION_S) / duree_consigne
    # ⚠️ L'assertion qui empêche le retour du faux verdict de recette : la part EXPLOITABLE d'une
    # consigne doit DOMINER. À 4 cycles (4,2 s) elle valait 36 % — une recette qui compte tout
    # l'intervalle plafonnait donc à ~40 % de justesse, décodeur parfait ou non.
    chk(part_exploitable >= 0.60,
        f"une consigne dure {duree_consigne:.1f} s dont {TRANSITION_S:.1f} s de transition : "
        f"{part_exploitable:.0%} d'échantillons exploitables (il en faut au moins 60 %, sinon "
        f"noter tout l'intervalle mesure la transition et pas le décodeur)")

    rng = random.Random(0)
    prec, repetitions = None, 0
    for _ in range(2000):
        tirage = tirage_cible(rng, len(plan), prec)
        repetitions += int(tirage == prec)
        prec = tirage
    chk(repetitions == 0,
        f"une consigne ne se répète JAMAIS deux fois de suite sur 2000 tirages ({repetitions}) — "
        f"sinon l'utilisateur ne voit pas qu'un nouvel essai a commencé")
    chk(tirage_cible(random.Random(0), 1, 0) == 0,
        "...et à une seule cible, la contrainte s'efface au lieu de boucler à l'infini")

    # --- Le DIAGNOSTIC DE CADENCE, point par point (la jumelle du geste flip->horodatage) ------
    # ⚠️ Ce verdict n'était gardé par AUCUNE assertion tant qu'il vivait à même le bilan : inverser
    # `abs(derive) < 0.02` en `>= 0.02` laissait le smoke entièrement vert, et l'avertissement ne
    # partait plus jamais. Le voici interrogé des DEUX côtés du seuil, plus le cas réel qui motive
    # tout ça : un écran 144 Hz lancé avec `--refresh 60`.
    cyc60 = L / 60.0
    for mesure, doit_avertir, quoi in (
            (cyc60, False, "cadence exacte"),
            (cyc60 * 1.019, False, "1,9 % de dérive (sous le seuil : 59,94 Hz annoncé 60, gigue)"),
            (cyc60 * 0.981, False, "-1,9 % de dérive"),
            (cyc60 * 1.021, True, "2,1 % de dérive (au-dessus du seuil)"),
            (cyc60 * 0.979, True, "-2,1 % de dérive"),
            (L / 144.0, True, "un écran 144 Hz lancé avec --refresh 60")):
        derive, avert = diagnostic_cadence(mesure, cyc60, 60.0, L)
        chk((avert is not None) == doit_avertir,
            f"cadence — {quoi} ({derive:+.1%}) : "
            f"{'AVERTIT' if avert is not None else 'se tait'}, "
            f"{'attendu' if (avert is not None) == doit_avertir else 'ATTENDU LE CONTRAIRE'}")
    _d, avert_144 = diagnostic_cadence(L / 144.0, cyc60, 60.0, L)
    chk(avert_144 is not None and "144" in avert_144 and "recalibre" in avert_144.lower(),
        f"...et l'avertissement NOMME le rafraîchissement réellement affiché et dit de recalibrer "
        f"({(avert_144 or '')[:80]}…)")

    # --- `--refresh 0` : refusé AVANT d'ouvrir la fenêtre, pas un ZeroDivisionError nu ---------
    for mauvais in (0.0, -60.0):
        chk(run(windowed=True, refresh=mauvais, seconds=0.1,
                stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0) is False,
            f"--refresh {mauvais:g} est REFUSÉ avant d'ouvrir la moindre fenêtre (il divisait par "
            f"zéro après, donc traceback nu et plein écran resté à l'écran)")

    # =====================================================================================
    # C. run() POUR DE VRAI, sur un écran factice
    # =====================================================================================
    # Un flux au nom DISTINCT du contrat public : les noms de flux sont partagés par toutes les
    # instances du projet, et un smoke ne doit jamais pouvoir répondre à la place d'un vrai
    # émetteur. `attente_consommateur_s=0` en C1 parce que personne n'écoute, par construction.
    import shutil
    import tempfile

    import pygame

    import pylsl

    sondes_smoke = [point_de_sonde(x, y, r) for x, y, r in positions_cibles(plan, TAILLE_FENETRE)]
    trace = []                   # l'ORDRE RÉEL des deux gestes, et l'écran à chaque flip
    vrai_flip = pygame.display.flip
    vrai_push = pylsl.StreamOutlet.push_sample
    # C3 seulement : on FABRIQUE des frames sautées, en retenant le flip assez longtemps pour
    # dépasser `SEUIL_SAUT`. C'est le seul moyen d'exercer le compteur de bout en bout — sous
    # `dummy` il n'y a jamais de vsync manqué, donc il resterait à 0 quoi qu'on fasse, et le
    # neutraliser ne rougirait rien.
    # ⚠️ `attendre` n'est pas un raffinement : l'émetteur mesure un ÉCART entre deux flips, donc le
    # tout premier flip d'une séance n'a pas de prédécesseur et ne peut par construction pas être
    # compté comme sauté. Caler les toutes premières images faisait donc poser 3 cales pour 2
    # comptées — et c'est l'assertion de C3 qui l'a montré, pas une relecture.
    cales = {"restantes": 0, "faites": 0, "duree": 0.0, "attendre": 0}

    def flip_trace(*a, **k):
        r = vrai_flip(*a, **k)
        trace.append(("flip", _etat_ecran(pygame, sondes_smoke)))   # l'écran APRÈS le basculement
        if cales["attendre"] > 0:
            cales["attendre"] -= 1
        elif cales["restantes"] > 0:
            cales["restantes"] -= 1
            cales["faites"] += 1
            time.sleep(cales["duree"])
        return r

    def push_trace(self, *a, **k):
        trace.append(("push", None))
        return vrai_push(self, *a, **k)

    pygame.display.flip = flip_trace
    pylsl.StreamOutlet.push_sample = push_trace
    try:
        journal, bilan1 = [], {}
        # `cycles_par_cible=2` et non le défaut (8 = 8,4 s) : en 6 s de passage, le défaut ne
        # ferait tourner la consigne qu'une fois. La VALEUR par défaut, elle, est vérifiée plus
        # haut, sur la part exploitable qu'elle laisse — pas ici.
        fait = run(windowed=True, refresh=60.0, seconds=6.0, cycles_par_cible=2,
                   stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
                   journal=journal, seed=0, bilan=bilan1)
        trace_c1, journal2 = list(trace), []
        trace.clear()
        # C2 : le BANDEAU DE CHAUFFE, raccourci. Le moteur encaisse les marqueurs pendant sa
        # chauffe (`CVEPRuntime.tick`), donc le clignotement ne doit PAS s'arrêter là — c'est ce
        # que ce second passage vérifie, et c'est la divergence assumée avec `errp_stimulus.py`.
        run(windowed=True, refresh=60.0, seconds=C2_SECONDES,
            stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.2,
            attente_moteur_s=C2_CHAUFFE_S, journal=journal2, seed=0)
        trace_c2 = list(trace)
        trace.clear()
        # C3 : N frames RÉELLEMENT retenues -> le compteur doit en voir exactement N.
        cales.update(restantes=C3_CALES, faites=0, duree=SEUIL_SAUT * 1.4 / 60.0, attendre=10)
        bilan3 = {}
        run(windowed=True, refresh=60.0, seconds=1.2,
            stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
            seed=0, bilan=bilan3)
        trace.clear()
        # C4/C5 : la MÊME graine doit rejouer la MÊME séquence de consignes.
        #
        # ⚠️ **Bornés en IMAGES, jamais en secondes, et c'est la correction du tour 2.** Deux
        # `run()` bornés par `seconds` ne s'arrêtent pas forcément sur la même image : la revue a
        # mesuré 1 exécution sur ~8 où le second passage rendait UNE consigne de plus (préfixes
        # identiques). Le mécanisme de graine n'y était pour rien — c'était l'ordonnanceur. Un test
        # instable qu'on relance jusqu'au vert est un test qu'on a appris à ignorer, et ce dépôt
        # vient justement d'en enterrer un ; on supprime donc la CAUSE au lieu de comparer des
        # préfixes. `max_frames` rend les deux courses identiques à l'image près.
        #
        # 6 cycles de 63 frames à `cycles_par_cible=1` = 6 consignes : une coïncidence entre deux
        # graines différentes y vaudrait 1/6 x (1/5)^5 ≈ 0,005 %.
        journal4, journal5 = [], []
        for jn in (journal4, journal5):
            run(windowed=True, refresh=120.0, max_frames=6 * L, cycles_par_cible=1,
                stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
                journal=jn, seed=20260821)
        # C6 : le JOURNAL DE FICHIER (`--log`), la moitié de la vérité-terrain qui SURVIT à la
        # séance. Le terminal n'en est pas une copie : la recette 2.9 demande de fermer les
        # terminaux entre ses blocs, et un scrollback dépassé efface la seule consigne écrite.
        # ⚠️ Un fichier temporaire, JAMAIS `data/` — et une SENTINELLE écrite avant l'appel, pour
        # que le mode d'ouverture soit vérifié et pas seulement supposé : en `"w"`, elle disparaît.
        dossier_log = tempfile.mkdtemp(prefix="cvep_stim_log_")
        chemin_log = os.path.join(dossier_log, "seance.jsonl")
        with open(chemin_log, "w", encoding="utf-8") as f:
            f.write('{"kind": "sentinelle"}\n')
        journal6, bilan6 = [], {}
        run(windowed=True, refresh=120.0, max_frames=6 * L, cycles_par_cible=2,
            stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
            journal=journal6, bilan=bilan6, seed=7, log_path=chemin_log)
        with open(chemin_log, encoding="utf-8") as f:
            lignes_log = [json.loads(l) for l in f if l.strip()]
        shutil.rmtree(dossier_log, ignore_errors=True)
    finally:
        pygame.display.flip = vrai_flip
        pylsl.StreamOutlet.push_sample = vrai_push
        cales["restantes"] = 0

    chk(fait, "run() va au bout sur un écran factice (SDL_VIDEODRIVER=dummy)")
    chk(len(journal) >= 3, f"...et a RÉELLEMENT poussé plusieurs marqueurs de cycle ({len(journal)})")
    if not journal or not journal2:
        chk(False, "aucun marqueur poussé : tout ce qui suit porterait sur une liste vide")
        print("[cvep-stim] VERDICT : PROBLÈME")
        return False

    # --- Le CONTRAT du marqueur : exactement ce que le moteur sait lire, rien de plus -------
    chk(all(m == {"mode": "cvep", "event": "cycle", "refresh": 60.0} for m, _ts, _f, _c in journal),
        "chaque marqueur est EXACTEMENT {mode: cvep, event: cycle, refresh: <float>} — le "
        "`refresh` est OBLIGATOIRE (sans lui `CVEPRuntime._encaisser_marqueurs` les refuse tous) "
        "et la cible consignée n'y figure PAS (cf. ⚠️ de la docstring du module)")
    chk(all(isinstance(m["refresh"], float) and not isinstance(m["refresh"], bool)
            for m, _ts, _f, _c in journal),
        "...et le `refresh` est un FLOTTANT : `bool` hérite de `int` en Python, donc un `true` "
        "passerait pour 1 Hz — le moteur écarte ce cas explicitement, l'émetteur ne doit pas le "
        "produire")
    chk(all(f % L == 0 for _m, _ts, f, _c in journal),
        f"un marqueur par REDÉMARRAGE du code, jamais ailleurs "
        f"({[f % L for _m, _ts, f, _c in journal][:8]})")

    horodatages = [ts for _m, ts, _f, _c in journal]
    chk(all(b > a for a, b in zip(horodatages, horodatages[1:])),
        "les horodatages avancent strictement — un flip par cycle, un horodatage par flip")

    # --- ⚠️⚠️ L'ALIGNEMENT : le flip qui précède le marqueur a-t-il montré la FRAME 0 ? -------
    # C'est LE test du geste flip->horodatage, et il ne peut pas être celui d'`errp_stimulus.py`.
    # Là-bas, « ce flip a CHANGÉ l'écran » suffit parce que la piste est immobile entre deux
    # feedbacks. Ici l'écran change à chaque frame : ce critère serait VERT même en poussant le
    # marqueur avant le flip. On lit donc CE QUI EST AFFICHÉ, dans les pixels, et on le compare au
    # code attendu.
    #
    # Une seule image ne suffit pas à identifier la position du code — mesuré : 32 motifs ON/OFF
    # distincts pour 63 positions, à 6 cibles. Une FENÊTRE de deux images consécutives, si (c'est
    # l'assertion `table` ci-dessous). On en prend trois, pour la marge.
    fen_sonde = 3
    etats = [tuple(bool(is_on(f, c["code"])) for c in plan) for f in range(L)]
    table = {tuple(etats[(f - fen_sonde + 1 + i) % L] for i in range(fen_sonde)): f
             for f in range(L)}
    chk(len(table) == L,
        f"fixture : une fenêtre de {fen_sonde} images consécutives identifie SANS AMBIGUÏTÉ la "
        f"position du code ({len(table)}/{L} motifs distincts) — sinon ce test ne saurait pas "
        f"lire l'écran")
    chk(len(set(etats)) < L,
        f"...et une SEULE image ne suffirait pas ({len(set(etats))}/{L} motifs) : c'est pourquoi "
        f"le critère « ce flip a changé l'écran » d'errp_stimulus ne peut pas servir ici")
    # Le chiffre qui rend ce critère-là VIDE de sens ici, et qui justifie tout le détour par les
    # pixels : sur 63 positions, une seule laisse l'écran identique à la précédente. « Ce flip a
    # changé l'écran » est donc vrai 62 fois sur 63, quoi que fasse l'émetteur.
    inchangees = sum(1 for f in range(L) if etats[f] == etats[(f - 1) % L])
    chk(inchangees <= 1,
        f"...et l'écran change à {L - inchangees} frames sur {L} : « ce flip a changé l'écran » "
        f"serait vert même en poussant le marqueur AVANT le flip")

    for nom, tr, jn in (("C1", trace_c1, journal), ("C2", trace_c2, journal2)):
        i_push = [i for i, (quoi, _e) in enumerate(tr) if quoi == "push"]
        chk(len(i_push) == len(jn) and all(i >= 1 and tr[i - 1][0] == "flip" for i in i_push),
            f"[{nom}] chaque marqueur part APRÈS un flip, jamais avant "
            f"({len(i_push)} push pour {len(jn)} marqueurs journalisés)")
        lues = []
        for i in i_push:
            fen = tuple(e for quoi, e in tr[:i] if quoi == "flip")[-fen_sonde:]
            if len(fen) == fen_sonde and None not in fen:
                lues.append(table.get(fen))
        chk(len(lues) >= 2 and all(p == 0 for p in lues),
            f"[{nom}] ...et le flip qui précède le marqueur est celui qui a affiché la FRAME 0 du "
            f"code, ni la {L - 1} ni la 1 — lu dans les PIXELS des {len(plan)} disques "
            f"({len(lues)} marqueurs vérifiés, positions {sorted(set(lues))})")

    # --- La CADENCE : un cycle = L frames, ni plus ni moins --------------------------------
    # Le moteur extrapole la phase à `refresh` Hz jusqu'au marqueur suivant. Un cycle qui dure
    # autre chose que `L / refresh` veut dire que l'écran ne tient pas la cadence annoncée : le
    # moteur dérive alors ENTRE deux marqueurs, sans qu'aucune exception ne le dise.
    cycle_theorique = L / 60.0
    ecarts_cycles = [b - a for a, b in zip(horodatages, horodatages[1:])]
    chk(bool(ecarts_cycles)
        and all(abs(e - cycle_theorique) <= 0.25 * cycle_theorique for e in ecarts_cycles),
        f"un cycle dure {cycle_theorique:.3f} s ({L} frames à 60 Hz), ±25 % — mesuré "
        f"{statistics.median(ecarts_cycles) * 1000:.0f} ms de médiane sur {len(ecarts_cycles)} "
        f"cycles (l'écran factice n'a pas de vsync, d'où la tolérance large)")

    # --- Le clignotement NE S'ARRÊTE PAS pendant la chauffe du moteur ------------------------
    # C2 tourne C2_CHAUFFE_S de bandeau de chauffe PUIS C2_SECONDES de stimulation décomptée. Si le
    # bandeau tenait un écran STATIQUE — le réflexe qu'on a en recopiant `errp_stimulus.py` — il
    # n'y aurait aucun marqueur pendant la chauffe, l'horloge du moteur ne partirait qu'après, et
    # sa première fenêtre décodée attendrait un marqueur de plus.
    #
    # ⚠️ **Ce qu'il faut mesurer, c'est l'ÉTENDUE, pas les trous.** Un écran figé PENDANT la chauffe
    # ne creuse aucun trou ENTRE deux marqueurs : il retarde simplement le premier. Un « plus grand
    # intervalle < X » reste donc vert, quelle que soit la valeur de X — c'est exactement le test
    # creux que la revue de l'ErrP a appris à repérer. L'étendue des marqueurs, elle, ne peut
    # dépasser la seule durée décomptée QUE si la chauffe en a produit aussi.
    ts_c2 = [ts for _m, ts, _f, _c in journal2]
    etendue = (ts_c2[-1] - ts_c2[0]) if len(ts_c2) > 1 else 0.0
    chk(etendue > C2_SECONDES,
        f"[C2] les marqueurs s'étendent sur {etendue:.2f} s, PLUS que les {C2_SECONDES:g} s "
        f"décomptées — donc le bandeau de chauffe en a produit lui aussi : le moteur les ENCAISSE "
        f"(`CVEPRuntime.tick`), il ne les jette pas comme le fait l'ErrP")
    chk(len(journal2) >= int((C2_CHAUFFE_S + C2_SECONDES) / cycle_theorique),
        f"[C2] ...et il y en a au moins un par cycle des {C2_CHAUFFE_S + C2_SECONDES:g} s totales "
        f"({len(journal2)} pour {int((C2_CHAUFFE_S + C2_SECONDES) / cycle_theorique)} attendus au "
        f"minimum)")

    # --- La consigne : elle tourne, et elle ne part pas sur le réseau ------------------------
    consignes = [c for _m, _ts, _f, c in journal]
    chk(len(set(consignes)) >= 2,
        f"la cible consignée CHANGE au fil de la séance ({consignes}) — une séance à cible unique "
        f"ne mesure rien")
    chk(all(c in {t['name'] for t in plan} for c in consignes),
        "...et c'est toujours un NOM de cible du plan, celui qu'on relira dans le terminal")

    # --- LE BILAN DE FIN : gardé par des assertions, plus seulement imprimé ------------------
    # ⚠️ C'est le seul garde-fou de la SECONDE panne muette de ce mode (un écran qui ne tient pas
    # le rafraîchissement annoncé). Tant qu'il n'était qu'une suite de `print`, TROIS mutations
    # d'une ligne le laissaient entièrement vert : comparaison de dérive inversée, compteur de
    # frames sautées neutralisé, bloc de bilan supprimé. Les trois rougissent maintenant.
    chk(bilan1.get("cycles") == len(journal) and bilan1.get("frames", 0) > 0,
        f"[C1] le bilan de fin EXISTE et compte ce que la séance a vraiment fait "
        f"({bilan1.get('cycles')} cycles, {bilan1.get('frames')} frames)")
    chk(bilan1.get("cadence_s") is not None and bilan1.get("derive") is not None,
        f"[C1] ...il MESURE la cadence réelle ({bilan1.get('cadence_s')} s/cycle, "
        f"dérive {bilan1.get('derive')})")
    # Sous `dummy` il n'y a pas de vsync : `clock.tick(refresh + 5)` impose 65 fps, soit ~-5 % —
    # au-dessus du seuil de 2 %. L'avertissement DOIT donc partir ici. C'est ce qui attrape la
    # comparaison inversée sur le chemin RÉEL, en plus des six points de la fonction pure.
    chk(bilan1.get("avertissement") is not None and abs(bilan1.get("derive", 0.0)) >= 0.02,
        f"[C1] ...et il AVERTIT, parce que l'écran factice n'a pas de vsync et dérive de "
        f"{bilan1.get('derive', 0.0):+.1%} — le chemin réel appelle bien le diagnostic")
    # Tolérance en PROPORTION et non « exactement 0 » : une pause du ramasse-miettes suffit à
    # dépasser 25 ms sur une frame, et ce test ne doit pas dépendre de la charge de la machine. Ce
    # qu'il garde, c'est l'absence de FAUX POSITIFS en masse (un seuil mal posé les ferait toutes
    # compter) ; que le compteur compte VRAIMENT est l'affaire de C3, juste en dessous.
    chk(bilan1.get("sautees", 0) <= 0.02 * bilan1.get("frames", 1),
        f"[C1] ...sans fabriquer de fausses frames sautées quand tout va bien "
        f"({bilan1.get('sautees')} sur {bilan1.get('frames')})")
    chk(cales["faites"] == C3_CALES and bilan3.get("sautees") == C3_CALES,
        f"[C3] les {C3_CALES} frames RÉELLEMENT retenues (flip bloqué "
        f"{SEUIL_SAUT * 1.4:.1f} périodes) sont comptées, toutes et seulement elles "
        f"({cales['faites']} cales posées -> {bilan3.get('sautees')} comptées) — sous `dummy` il "
        f"n'y a jamais de vsync manqué, donc sans ces cales le compteur ne prouverait rien")

    # --- `--seed` tient sa promesse, et la graine est TOUJOURS connue ------------------------
    # ⚠️ Le contrat n'était vérifié par rien : remplacer `random.Random(seed)` par
    # `random.Random()` laissait tout vert. Et sans `--seed`, la graine tirée n'était pas
    # imprimée — la séance était irrejouable et personne ne le savait. Or la séance casque est le
    # livrable de ce chantier : une séance qu'on ne peut pas rejouer ne se dépouille pas deux fois.
    consignes4 = [c for _m, _ts, _f, c in journal4]
    consignes5 = [c for _m, _ts, _f, c in journal5]
    # ⚠️ On exige la MÊME LONGUEUR autant que le même contenu, et c'est le fond de la correction du
    # tour 2 : comparer des listes de longueurs différentes est exactement ce qui rendait ce
    # contrôle instable. Bornées en frames, les deux courses en ont forcément 6.
    chk(len(consignes4) == 6 and len(consignes5) == 6 and consignes4 == consignes5,
        f"deux séances à la MÊME graine ET au MÊME compte d'images rejouent EXACTEMENT les mêmes "
        f"consignes, en même nombre ({consignes4} vs {consignes5})")
    chk(len(journal4) == len(journal5) == 6,
        f"...et le compte de marqueurs est le même à l'image près, parce que la borne est un "
        f"nombre d'IMAGES et non une durée ({len(journal4)} vs {len(journal5)})")
    chk(len(set(consignes4)) >= 2,
        f"...et cette séquence n'est pas une cible unique répétée, ce qui la rendrait "
        f"indistinguable d'un tirage cassé ({consignes4})")
    chk(bilan3.get("graine") == 0,
        f"la graine DONNÉE est celle qui a servi, et le bilan la rend ({bilan3.get('graine')})")
    bilan_sans_graine = {}
    run(windowed=True, refresh=120.0, max_frames=L, cycles_par_cible=1,
        stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
        seed=None, bilan=bilan_sans_graine)
    chk(isinstance(bilan_sans_graine.get("graine"), int),
        f"...et SANS `--seed`, une graine est TIRÉE puis annoncée, au lieu de laisser une séance "
        f"irrejouable sans le dire ({bilan_sans_graine.get('graine')})")

    # --- [C6] `--log` : la VÉRITÉ-TERRAIN dans un fichier ------------------------------------
    # ⚠️ **C'est la clé de jointure du dépouillement, et sans elle le test 2.9 de la recette n'est
    # exécutable avec AUCUN outil du dépôt.** Le moteur publie un indice de cible ; la cible
    # CONSIGNÉE ne part jamais sur le réseau. Les deux ne se rejoignent que par l'horodatage
    # `local_clock()` — celui que ces lignes portent, et que `examples/receiver.py` imprime en tête
    # de chaque échantillon. Un journal qui vivrait sur stdout ne survit ni à un Ctrl+C, ni à la
    # fermeture des terminaux que la recette demande ENTRE ses blocs A / B / A'.
    entetes = [l for l in lignes_log if l.get("kind") == "header"]
    consignes_log = [l for l in lignes_log if l.get("kind") == "consigne"]
    bilans_log = [l for l in lignes_log if l.get("kind") == "bilan"]
    # Les changements de consigne du déroulé RÉEL : `run` en imprime un par bord de
    # `L * cycles_par_cible`, et c'est exactement là qu'il doit écrire une ligne.
    changements = [(ts, c) for _m, ts, f, c in journal6 if f % (L * 2) == 0]
    chk(len(consignes_log) == len(changements) and len(changements) >= 2,
        f"[C6] une ligne `consigne` par CHANGEMENT de consigne, pas une de plus ni de moins "
        f"({len(consignes_log)} lignes pour {len(changements)} changements)")
    chk([(round(ts, 6), c) for ts, c in changements]
        == [(l["t"], l["nom"]) for l in consignes_log],
        f"[C6] ...et chaque ligne porte l'horodatage LSL EXACT du marqueur et le nom de la cible "
        f"consignée — c'est la SEULE clé qui rejoigne `decoded_cvep` "
        f"({[(l['t'], l['nom']) for l in consignes_log]})")
    transition_120 = CVEP_DECISION_CYCLES * L / 120.0 + CVEP_VOTE_LEN * PERIODE_MOTEUR_S
    chk(bool(consignes_log)
        and all(abs(l["compter_a_partir_de"] - l["t"] - transition_120) < 1e-3
                for l in consignes_log),
        f"[C6] ...et le second horodatage est bien `t` + la transition ({transition_120:.2f} s à "
        f"120 Hz) : le fichier porte l'instant À PARTIR DUQUEL un échantillon compte, pas seulement "
        f"celui où la consigne est apparue")
    chk(len(entetes) == 1 and entetes[0]["seed"] == 7 and entetes[0]["code_len"] == L
        and entetes[0]["cibles"] == [c["name"] for c in plan],
        f"[C6] un en-tête, et il contient de quoi REJOUER la séance : graine, refresh, longueur du "
        f"code, noms des cibles ({entetes[0] if entetes else entetes})")
    # ⚠️ VERBATIM : la ligne `bilan` est le dictionnaire de `bilan_de_seance`, pas une seconde
    # rédaction. Reconstruire les mêmes champs à la main ferait diverger le fichier de l'écran le
    # jour où l'un des deux change — c'est l'argument que `bilan_de_seance` fait déjà valoir.
    chk(len(bilans_log) == 1 and bilans_log[0] == dict(kind="bilan", **bilan6),
        f"[C6] ...et un bilan, RECOPIÉ du dictionnaire de `bilan_de_seance` sans le réécrire "
        f"({bilans_log[0] if bilans_log else bilans_log})")
    chk(bool(lignes_log) and lignes_log[0].get("kind") == "sentinelle",
        f"[C6] le fichier est ouvert en AJOUT : la ligne écrite AVANT la séance est toujours là "
        f"(premier enregistrement : {lignes_log[0] if lignes_log else '—'}) — en `\"w\"`, relancer "
        f"l'émetteur sur le même chemin effacerait la séance précédente")
    chk(_parse_args([]).log is None,
        f"[C6] `--log` n'a AUCUN défaut : sans l'option, rien n'est écrit nulle part — c'est ce "
        f"qui interdit à `--smoke` de toucher `data/` ({_parse_args([]).log!r})")

    n_cycles = len(journal)
    print(f"[cvep-stim] --smoke : {n_cycles} cycles RÉELS poussés (écran factice), consignes "
          f"{consignes[:6]}{'…' if len(consignes) > 6 else ''}")
    # ⚠️ Les deux bilans ci-dessus se plaignent de la cadence, et c'est ATTENDU : le pilote `dummy`
    # n'a pas de vsync, donc la boucle est cadencée par `clock.tick(refresh + 5)` — 65 fps au lieu
    # de 60, soit -5 % sur la durée d'un cycle. Sur un vrai écran, le `flip` bloque au balayage et
    # ce plafond ne sert jamais. L'avertissement n'est donc pas un faux positif : il dit vrai sur
    # un écran factice. Ne pas l'apprendre à l'ignorer sur un vrai.
    print("[cvep-stim] --smoke : l'avertissement de cadence ci-dessus est ATTENDU sous "
          "SDL_VIDEODRIVER=dummy (pas de vsync -> 65 fps imposés par clock.tick, -5 %)")
    print(f"[cvep-stim] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Stimulus c-VEP (EEG_API_Unicorn).")
    p.add_argument("--windowed", action="store_true", help="fenêtre au lieu du plein écran")
    p.add_argument("--refresh", type=float, default=None,
                   help="forcer le refresh (Hz) — sinon auto-mesuré. C'est la valeur PUBLIÉE dans "
                        "chaque marqueur : le moteur refuse tout marqueur qui s'écarte de plus de "
                        "1 Hz du refresh auquel le modèle a été calibré, et le dit")
    p.add_argument("--seconds", type=float, default=None,
                   help="auto-quit après N secondes de stimulation DÉCODABLE (le décompte démarre "
                        "après la chauffe du moteur, pas pendant)")
    p.add_argument("--seed", type=int, default=None,
                   help="graine du tirage des CONSIGNES : rejoue la même SÉQUENCE de cibles à "
                        "fixer (pour dépouiller une séance hors ligne). ⚠️ Sa LONGUEUR, elle, "
                        "peut différer d'une consigne : une séance bornée en SECONDES ne s'arrête "
                        "pas forcément sur la même image (mesuré : 1 exécution sur ~8). Le préfixe "
                        "est identique, et chaque consigne est horodatée — c'est ce qui compte "
                        "pour dépouiller. Seule une borne en IMAGES (`max_frames`, réservé à "
                        "`--smoke`) donne l'égalité stricte")
    p.add_argument("--log", default=None, metavar="CHEMIN",
                   help="écrit la VÉRITÉ-TERRAIN en JSONL (une ligne par consigne, horodatée en "
                        "`local_clock()`, plus un en-tête et le bilan). SANS DÉFAUT : rien n'est "
                        "écrit tant que l'option n'est pas donnée. ⚠️ La séance 2.9 de la recette "
                        "ne se dépouille pas sans ce fichier — le terminal est le seul autre "
                        "exemplaire, et une séance casque ne se répète pas")
    p.add_argument("--no-wait", action="store_true",
                   help=f"ne pas attendre le moteur (ni son bandeau de chauffe de "
                        f"~{ATTENTE_MOTEUR_S:g} s) : émetteur seul")
    p.add_argument("--smoke", action="store_true",
                   help="test headless (CI) : la PHASE, la géométrie et la boucle réelle")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    ok = run(windowed=args.windowed, refresh=args.refresh, seconds=args.seconds,
             smoke=args.smoke, seed=args.seed, log_path=args.log,
             attente_consommateur_s=0.0 if args.no_wait else 5.0)
    sys.exit(0 if ok else 1)
