"""Le stimulus ErrP, en programme AUTONOME qui publie ses marqueurs de feedback.

⚠️ **Ce programme n'ouvre PAS le casque.** C'est ce qui permet de le lancer EN MÊME TEMPS que le
moteur, dans deux terminaux — le même montage que pour le P300 et le SSVEP :

    python src/core/server.py --mode errp           # terminal 1 : acquiert et décode (EXIGE un
                                                      # modèle entraîné, cf. research/app.py -> ErrP)
    python src/stimulus/errp.py             # terminal 2 : affiche la piste et marque

C'est aussi l'exemple de référence pour qui voudra émettre depuis Unity : le protocole est ici,
et surtout l'endroit exact où prendre l'horodatage.

Protocole publié (figé, cf. docs/SPEC.md) — UNE SEULE forme de marqueur en DÉCODAGE, sur le flux
`MARKER_STREAM_DEFAULT` (core/config.py), type "Markers", 1 voie "string", cadence irrégulière :

    {"mode": "errp", "event": "feedback"}     # le point vient de sauter à sa nouvelle case

⚠️ Contrairement au P300 (qui publie sa cible), ce marqueur ne porte AUCUNE autre information — ni
la case visée, ni si CE pas est une erreur délibérée. Le moteur ne lit que l'horodatage
(`core/modes/errp.py:_run_step` ignore tout le reste) : c'est justement ce qu'il doit DEVINER
depuis l'EEG (BCI **passive**). Publier la vérité-terrain sur le réseau reviendrait à lui donner la
réponse. Pour la mesurer HORS LIGNE quand même, chaque pas est imprimé au terminal avec son
horodatage LSL exact (`t=…`) : il suffit à raccrocher chaque ligne à l'échantillon `decoded_errp`
correspondant, et `--seed` rejoue la séquence à l'identique.

`--calibrer` joue la MÊME piste, avec deux marqueurs de plus autour et UN CHAMP de plus dessus :

    {"mode": "errp", "event": "calib_start", "trials": 200}   # la séance s'ouvre, voici ses époques
    {"mode": "errp", "event": "feedback", "error": true}      # ce pas-là a ÉLOIGNÉ le point
    {"mode": "errp", "event": "calib_end"}                    # la séance est finie -> le moteur entraîne

⚠️⚠️ **`error` n'existe QU'EN CALIBRATION, et c'est LA faute grave de ce fichier.** L'ErrP est une
BCI *passive* : tout son objet est de deviner, depuis l'EEG seul, que la machine s'est trompée. Le
champ est la vérité-terrain — indispensable pour ÉTIQUETER les époques d'entraînement, interdit
pendant qu'on décode. Un émetteur qui le publierait en décodage donnerait la réponse au moteur, et
rien ne le signalerait : le flux `decoded_errp` garderait exactement la même forme, les scores
resteraient plausibles, et tout ce que ce produit affirme sur ce mode deviendrait faux. La
construction du marqueur est donc écrite à UN SEUL endroit (`marqueur_feedback`), et `--smoke`
vérifie les DEUX sens — en calibration chaque feedback porte son étiquette, en décodage aucun.

⚠️ Et l'étiquette publiée est celle du pas **RÉELLEMENT AFFICHÉ**, pas celle que le tirage avait
décidée : `core/errp_track.py:decide_pas` rend `erreur` d'après l'EFFET du pas, rebond de bord
compris — un tirage « erreur » au bord rapproche le point de sa cible, et ce n'est donc PAS une
erreur vécue. C'est la même faute que d'horodater avant le flip, sur un autre axe.

⚠️ **Une séance interrompue (ESC, `--seconds`) ne publie PAS de `calib_end`**, comme chez le P300 :
le moteur n'entraînera donc rien, et le dira. Un modèle appris sur un tiers de séance serait
indiscernable d'un modèle complet dans la liste de la console.

La tâche est le curseur-vers-cible (Ferrez & Millán 2008, Chavarriaga 2010), reprise des DEUX
endroits qui la jouent déjà — le démonstrateur (`research/app.py`, mode ErrP) et la calibration
(`research/errp_calibrate.py`) — va les lire, ce protocole ne s'invente pas ici, il se reproduit :
un point sur une piste de `ERRP_TRACK_CELLS` cases part du CENTRE vers une cible tirée à l'une des
DEUX EXTRÉMITÉS (50/50 — le sens du mouvement reste décorrélé de l'étiquette erreur/correct, cf.
`nouvelle_cible`) ; à chaque pas il avance d'une case, sauf en cas d'erreur DÉLIBÉRÉE qui l'éloigne
(rebond aux bords, cf. `decide_pas`). ⚠️ « Il se reproduit » vaut pour la TRAJECTOIRE et pour la
cadence intra-course ; sur la découpe des FINS DE COURSE, cet émetteur diverge délibérément de la
calibration — c'est écrit noir sur blanc plus bas, avec les deux SOA.

⚠️ **`decide_pas`/`nouvelle_cible` sont, à ce jour, une SECONDE écriture du protocole** — la
première est `errp_calibrate._decide_step`/`_new_goal`, celle sous laquelle les modèles sont
réellement entraînés. Tant que les deux n'ont pas fusionné (le sens de la fusion serait celui du
P300 : le module LÉGER possède l'invariant, les modules lourds l'importent — cf.
`p300_stimulus.blocs_melanges`), `--smoke` interdit au moins la DÉRIVE : il fait jouer 500 pas aux
deux implémentations avec la même graine et exige la MÊME trajectoire.

⚠️ **Correction de revue (tour 1) : leur TAUX d'erreur, lui, DIFFÈRE — l'attribution d'origine ici
était fausse.** La calibration vise `ERRP_ERROR_RATE` (~28 %, la valeur de littérature,
Chavarriaga/Yasemin) ; le démonstrateur vise `ERRP_DEMO_ERROR_RATE` (35 %, choisie plus haute pour
que l'expérience solo reste vivante malgré une dérive nette vers la cible — cf. son commentaire
dans `core/config.py`) : deux réglages distincts pour deux usages distincts, pas une divergence
accidentelle. Cet émetteur prend `ERRP_ERROR_RATE` par défaut, PAS la valeur du démonstrateur : il
se veut la référence RÉSEAU du protocole (cf. plus haut, l'exemple pour Unity), donc la valeur
ancrée dans la littérature plutôt que celle réglée pour l'agrément d'une démo solo —
`--error-rate` reste libre d'en changer, pour qui voudrait l'un ou l'autre.

⚠️ **La CADENCE est un paramètre du modèle, pas un réglage de confort** (correction de revue,
tour 2). Un pas = `ERRP_FEEDBACK_S` (1 s) de feedback affiché, PUIS `PAUSE_INTER_PAS_S` (0,45 s) de
piste immobile : **1,45 s entre deux onsets D'UNE MÊME COURSE**, exactement la cadence intra-course
de `errp_calibrate._run_block` (`:217` puis `:230`) sous laquelle les époques du modèle ont été
enregistrées. L'émetteur enchaînait les pas sans respiration (1,0 s) : l'époque du moteur dure déjà
0,9 s (`ERRP_PRE_S + ERRP_EPOCH_S`), il ne restait donc 0,1 s de piste libre, et la ligne de base
[-0,2 s ; 0] du pas suivant était prélevée dans la queue de la réponse précédente — que `ERRP_BAND`
(1-10 Hz) laisse passer. Rien ne lève d'exception dans ce cas : le moteur publie des scores
plausibles et faux.

⚠️ **Une fin de course intercale ici DEUX écrans statiques**, pour la même raison (correction de
revue, tour 2). Cible atteinte, ou `ERRP_MAX_RUN_STEPS` dépassés -> on tient la piste
`PAUSE_FIN_COURSE_S` (0,7 s) à sa position finale, PUIS on remet le point au centre avec une
nouvelle cible et on tient `PAUSE_NOUVELLE_COURSE_S` (0,9 s). Sans le second, la remise à zéro (le
point saute de 2 à 4 cases, et la cible change d'extrémité une fois sur deux) tombait DANS la frame
horodatée du feedback suivant : ~1 époque sur 7 commençait sur un transitoire visuel plein écran.
Le même écran sert au tout premier pas, sans quoi l'utilisateur ne voit jamais d'où le point part
et ne peut former aucune attente à violer.

⚠️ **Cet émetteur et la calibration jouent le MÊME protocole, et il a fallu trois tours pour y
arriver.** Écrit ici parce que ce fichier s'est cru identique à `errp_calibrate` trois fois sans
l'être — le taux d'erreur (corrigé au tour 1), la cadence (tour 2), la découpe des fins de course
(tour 3) — et parce que c'est la référence que lira quelqu'un qui écrit son émetteur en Unity. Une
affirmation d'identité dans ce fichier doit être VÉRIFIÉE dans l'autre, jamais supposée.

État aligné, en secondes entre deux onsets :

    SOA de TRANSITION (dernier pas d'une course -> premier pas de la suivante)
        errp_calibrate._run_block : 1,0 + 0,7 + 0,9  = 2,6 s   sans transitoire
        cet émetteur              : 1,0 + 0,7 + 0,9  = 2,6 s   sans transitoire

    SOA INTRA-course (deux pas de la même course)
        errp_calibrate._run_block : 1,0 + 0,45       = 1,45 s
        cet émetteur              : 1,0 + 0,45       = 1,45 s

⚠️ **Ce que ça change pour le modèle du 2026-07-24 (AUC 0,7763) : rien, et c'est mesuré.** Ce modèle
a été entraîné AVANT l'alignement, donc **14,9 % de ses époques** commençaient sur le transitoire
(mesuré sur 200 séances simulées, pas estimé). Cette sous-population n'existe plus dans ce que
produit l'émetteur, ce qui pourrait décaler la distribution des scores publiés — sauf que la
contamination n'était **pas corrélée à l'étiquette** : +1,2 point d'écart seulement (z = 1,84), et
il vient du rebond de bord, pas du saut (après une transition le point repart du CENTRE, où aucun
rebond ne peut retourner l'étiquette). Du bruit ajouté, donc, pas un biais appris : trop petit pour
fabriquer une AUC, et la mesure est au pire un peu pessimiste. Une future calibration produira des
époques plus propres que celles-là, pas différentes.

(Le troisième site, `app.mode_errp`, n'est une référence de cadence NI pour l'un NI pour l'autre :
il tient `ERRP_EPOCH_S + 0,2` entre les pas — `app.py:1036` — et ajoute 2,4 s d'écran de verdict à
chaque détection. C'est un démonstrateur solo ; ses époques n'entraînent aucun modèle.)

Le geste critique, identique au P300 :

    pygame.display.flip()
    # L'HORODATAGE SE PREND ICI, juste après que le feedback est À L'ÉCRAN. 40 ms d'avance
    # décalent toutes les époques de deux frames, et le décodeur moyenne une réponse qui n'a pas
    # encore eu lieu. Rien ne lève d'erreur ; les scores sortent, et ils sont du bruit.
    outlet.push_sample([json.dumps({"mode": "errp", "event": "feedback"})],
                       timestamp=local_clock())

C'est LA raison d'être de ce fichier, donc la chose que `--smoke` vérifie le plus durement : il
instrumente `pygame.display.flip` et `StreamOutlet.push_sample` pour enregistrer l'ORDRE RÉEL des
deux gestes, et prend une empreinte de l'écran à chaque flip — le flip qui précède un marqueur doit
être celui qui a CHANGÉ l'image, pas une frame de plus du même écran.

⚠️ **Pas de `valide_reglages` complet, à la différence de `p300_stimulus.py` — et ce n'est pas un
oubli.** Le mode ErrP du moteur ne lit QUE l'horodatage du marqueur `feedback` : aucun nombre de
cases codé en dur, aucune manche à plafonner, rien qui s'accumule sur plusieurs pas. `--cells` et
`--error-rate` ne peuvent donc jamais dérégler le décodage — ils changent seulement la qualité de
l'élicitation RESSENTIE (la littérature situe le taux d'erreur autour de 25-30 %), jamais le
contrat réseau. La SEULE garde est `--cells >= MIN_CELLS` (3), et elle protège de ce PROGRAMME-ci,
pas du moteur : à 1 case le point sort de la piste, à 2 cases le centre EST une extrémité, donc le
point démarre parfois sur sa cible et chaque pas « correct » est étiqueté erreur.

Lancer :
    python src/stimulus/errp.py                  # plein écran, ESC pour quitter
    python src/stimulus/errp.py --windowed       # fenêtre 1000x700 (dev)
    python src/stimulus/errp.py --cells 9        # cases de la piste (défaut ERRP_TRACK_CELLS)
    python src/stimulus/errp.py --error-rate 0.3 # taux d'erreurs délibérées (défaut ERRP_ERROR_RATE)
    python src/stimulus/errp.py --refresh 60     # forcer le refresh (sinon auto-mesuré)
    python src/stimulus/errp.py --seconds 20     # 20 s de STIMULATION (l'attente du
                                                          # moteur ne compte pas dans le décompte)
    python src/stimulus/errp.py --seed 1         # rejouer EXACTEMENT la même séquence
    python src/stimulus/errp.py --no-wait        # ne pas attendre le moteur (émetteur seul)
    python src/stimulus/errp.py --calibrer       # séance de CALIBRATION (la console la lance)
    python src/stimulus/errp.py --calibrer --essais 100   # pas de calibration (défaut ERRP_CAL_TRIALS)
    python src/stimulus/errp.py --smoke          # test sans écran (CI) : protocole ET rendu
"""

import argparse
import json
import os
import random
import sys
import time

# Permet `from config import ...` que le module soit lancé via `python src/stimulus/errp.py`
# ou importé comme `src.errp_stimulus`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (ERRP_CAL_TRIALS, ERRP_EPOCH_S, ERRP_ERROR_RATE,  # noqa: E402
                         ERRP_FEEDBACK_S, ERRP_MAX_RUN_STEPS, ERRP_TRACK_CELLS,
                         MARKER_STREAM_DEFAULT, SSVEP_WARMUP_S, use_utf8_console)
from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, local_clock  # noqa: E402

# --- Réglages d'affichage ---------------------------------------------------

BG = (0, 0, 0)              # fond noir -> contraste maximal, même choix que les autres stimuli
ON_COLOR = (255, 255, 255)  # le point (curseur)
GOAL_COLOR = (60, 200, 90)  # la cible : pastille verte, même choix que research/errp_calibrate.py
OUTLINE = (55, 55, 70)      # les cases de la piste
HUD = (70, 90, 70)
NOTE = (110, 150, 110)      # les écrans d'attente : vert éteint, ne concurrence pas le point

# --- Le TEMPS du protocole : ces trois durées ne sont PAS du confort ---------
# Elles vivent désormais dans `core/errp_track.py`, avec le reste de la piste (2026-09-07). Elles
# étaient jusque-là RECOPIÉES ici depuis les littéraux de `research/errp_calibrate.py:_run_block`,
# et un test de `--smoke` lisait le code source de cette fonction pour vérifier qu'elles n'avaient
# pas dérivé. Le test a disparu avec la recopie : les deux lisent maintenant le même nom, ce qui
# rend la dérive impossible au lieu de la détecter après coup.
#
# ⚠️ Même valeur ne suffit toujours pas : il faut la même PLACE. `_run_block` n'a longtemps joué
# son écran « nouvelle cible » qu'en tête de bloc, ce qui donnait la même constante à un SOA de
# transition différent (1,7 s là-bas, 2,6 s ici). Aligné depuis — les deux jouent les deux écrans
# à chaque fin de course. Aucun test ne couvre la PLACE : relire les deux boucles avant
# d'affirmer quoi que ce soit ici.
from core.errp_track import (PAUSE_FIN_COURSE_S, PAUSE_INTER_PAS_S,  # noqa: E402
                            PAUSE_NOUVELLE_COURSE_S, decide_pas, nouvelle_cible)

# Ce que le moteur JETTE avant d'écouter pour de bon. ⚠️ **Ce n'est PAS la même chose en décodage
# et en calibration, et les confondre a coûté une séance entière** (voir plus bas).
#
# En DÉCODAGE, c'est `ErrPRuntime` qui tourne : chauffe (l'offset DC de l'Unicorn dérive après
# ouverture) PUIS repos, pendant lequel il mesure la référence de son rejet d'artefact et veut un
# écran immobile. Les deux sont jetés (`errp.py::_jeter_marqueurs_de_chauffe`). Valeurs lues dans
# `core/modes/errp.py` (SPEC.rest) : `warmup_s=SSVEP_WARMUP_S`, `duration_s=8.0`.
ATTENTE_MOTEUR_REPOS_S = 8.0
ATTENTE_MOTEUR_DECODAGE_S = SSVEP_WARMUP_S + ATTENTE_MOTEUR_REPOS_S
# En CALIBRATION, c'est `ErrPCalibration` qui tourne, et elle n'a AUCUNE phase de repos : ses
# phases sont chauffe → essais → entraînement (`core/modes/calibration.py::PHASES`, où « rest » ne
# figure pas). Elle ne mesure aucune référence d'artefact — elle ne décode rien.
#
# ⚠️ **Cette attente a valu 23 s ici aussi, et c'était FAUX — mesuré, pas relu.** La valeur était
# lue sur le bon fichier mais sur le mauvais RUNTIME : le repos du mode de DÉCODAGE, ajouté à
# l'attente d'une CALIBRATION qui ne le joue jamais. C'est le motif « mesurer ailleurs que là où ça
# sert », relevé quatre fois au chantier c-VEP.
#
# ⚠️ Et ce n'était pas seulement 8 s perdues à fixer une piste immobile. Le socle ABANDONNE une
# calibration après `CALIB_FENETRE_SILENCE_S` (15 s) sans le moindre marqueur, décompté depuis la
# fin de SA chauffe : l'échéance du premier pas tombe donc `SSVEP_WARMUP_S +
# CALIB_FENETRE_SILENCE_S` = 30 s après `start_calibration`. En en consommant 23, la fenêtre ne
# laissait plus que 7 s à son propre démarrage — init pygame, `set_mode`, mesure du
# rafraîchissement, et jusqu'à 5 s de `wait_for_consumers`. MESURÉ en rejouant la ligne du temps du
# socle : à 7,5 s de démarrage, la calibration abandonne (« la fenêtre de stimulus s'est arrêtée en
# pleine séance ») avant qu'un seul pas ait été joué, en accusant une fenêtre parfaitement vivante.
# À la chauffe seule, le budget de démarrage repasse à 15 s, et cette fenêtre s'aligne enfin sur
# celles du P300 et du c-VEP, qui n'ont jamais attendu que leur chauffe.
ATTENTE_MOTEUR_S = SSVEP_WARMUP_S

# Les deux postes du DÉMARRAGE de cette fenêtre, ceux qui doivent tenir dans ce que l'attente
# ci-dessus ne consomme pas. Ils ne règlent rien : ils existent pour que `--smoke` puisse VÉRIFIER
# que le budget les couvre (cf. son contrôle « budget de démarrage »).
ATTENTE_CONSOMMATEUR_MAX_S = 5.0   # le défaut de `run(attente_consommateur_s=…)`
MARGE_INIT_PYGAME_S = 5.0          # init + `set_mode` plein écran + mesure du rafraîchissement

# En dessous, la piste est dégénérée — cf. la garde de `run` et le ⚠️ de la docstring du module.
MIN_CELLS = 3


# --- Le protocole (fonctions PURES) : `nouvelle_cible` et `decide_pas` -------
# Elles étaient ÉCRITES ICI, en double de `research/errp_calibrate.py`, et cette docstring-là le
# disait : « ⚠️ Cette fonction est un DOUBLE de `_decide_step`, pas encore une source unique ». Un
# test rejouait 500 pas à graine égale pour vérifier que les deux ne divergeaient pas — un test
# qui protège une duplication au lieu de la supprimer, et qui ne pouvait rien dire du 501e pas.
# Les deux écritures ont fusionné dans `core/errp_track.py` le 2026-09-07 ; elles sont importées
# en tête de ce fichier, avec les trois durées. Voir `python src/core/errp_track.py` pour les
# quatre propriétés dont dépend la validité des modèles déjà entraînés.


def marqueur_feedback(erreur, calibrer):
    """Le marqueur d'un pas. **L'UNIQUE endroit du dépôt qui décide si la vérité-terrain part.**

    `erreur` : ce pas a-t-il ÉLOIGNÉ le point de sa cible — l'EFFET réel, tel que `decide_pas` le
    rend, rebond de bord compris. `calibrer` : est-on en train de fabriquer un jeu d'entraînement.

    ⚠️ **En décodage le marqueur reste NU, et ce n'est pas une économie d'octets.** L'ErrP est une
    BCI passive : le moteur doit deviner depuis l'EEG que la machine s'est trompée. Lui glisser la
    réponse dans le marqueur qui délimite l'époque ne casserait RIEN de visible — même flux, mêmes
    scores plausibles — et rendrait faux tout ce que ce produit affirme sur ce mode. Le champ
    n'existe donc que quand quelqu'un doit ÉTIQUETER des époques, c'est-à-dire en calibration.

    Écrire ce choix dans une fonction plutôt qu'à l'endroit du `push_sample` est ce qui le rend
    testable dans les DEUX sens sans lancer d'écran (cf. `_smoke`) : « en calibration l'étiquette
    est là » et « hors calibration elle n'y est pas » sont deux assertions, pas une.
    """
    marqueur = {"mode": "errp", "event": "feedback"}
    if calibrer:
        marqueur["error"] = bool(erreur)
    return marqueur


# --- Boucle principale -------------------------------------------------------

def run(windowed=False, refresh=None, n_cells=ERRP_TRACK_CELLS, taux_erreur=ERRP_ERROR_RATE,
        seconds=None, smoke=False, stream_name=MARKER_STREAM_DEFAULT, attente_consommateur_s=5.0,
        journal=None, seed=None, max_run_steps=ERRP_MAX_RUN_STEPS,
        calibrer=False, essais=ERRP_CAL_TRIALS, attente_moteur_s=None, sonde_ecran=None):
    """La boucle du stimulus — décodage (défaut) ou CALIBRATION (`calibrer=True`).

    ⚠️ Les deux modes partagent la MÊME boucle et la MÊME piste. Une séance de calibration est une
    séance normale, bornée à `essais` pas, encadrée de `calib_start`/`calib_end`, et dont chaque
    feedback porte son étiquette. Écrire une seconde boucle « pour la calibration » rouvrirait
    exactement la duplication que la tâche 1 a supprimée (la piste était écrite deux fois, avec un
    test de 500 pas pour garder les copies d'accord).

    `journal`, s'il est fourni, reçoit `(marqueur, horodatage, erreur, debut_de_course)` pour
    CHAQUE marqueur réellement poussé — `calib_start`/`calib_end` compris, avec `erreur=None`.

    `erreur` (bool, vérité-terrain LOCALE : ce pas a-t-il ÉLOIGNÉ le point de sa cible) ne part sur
    le réseau QUE pendant une calibration (cf. `marqueur_feedback` et le ⚠️⚠️ du module) ; ici il
    permet en plus à `--smoke` de vérifier, sur le déroulé RÉEL, que le taux d'erreur joué reste
    raisonnable, en plus de la fonction pure `decide_pas` (vérifiée à grande échelle, sans écran).
    `debut_de_course` dit si ce pas est le PREMIER d'une nouvelle course, donc s'il a été précédé
    des deux écrans statiques : c'est ce qui permet à `--smoke` de mesurer séparément la cadence
    intra-course (1,45 s) et l'écart de transition (2,6 s), qu'une moyenne unique confondrait — et
    d'exclure de la vérification d'étiquette le pas qui suit une téléportation du point.

    `seed` graine le tirage des erreurs : deux exécutions rejouent alors la MÊME séquence, ce qui
    est la seule façon de refaire une séance à l'identique. `max_run_steps` n'existe que pour que
    `--smoke` puisse EXERCER le plafond de pas (sinon jamais atteint en quelques secondes).

    `sonde_ecran(surface, centres, rayon)` n'existe QUE pour `--smoke`, et c'est le garde-fou le
    plus sérieux de ce fichier avec l'horodatage au flip : elle est appelée juste après le `flip`
    sur lequel un feedback vient de partir, et donne donc à voir l'écran EXACT que ce marqueur
    prétend décrire. Le test y LIT la case du point et celle de la cible dans les pixels, au lieu
    de croire le compteur de l'émetteur — qui, lui, ne peut que se donner raison.

    `attente_moteur_s` : combien de temps occuper avant le premier pas d'une calibration, le temps
    que le moteur finisse sa chauffe ET son repos (cf. `ATTENTE_MOTEUR_S`). `None` = la valeur par
    défaut ; `0` pour un test.
    """
    if int(n_cells) < MIN_CELLS:
        print(f"[errp-stim] REFUSÉ — --cells {n_cells} : il en faut au moins {MIN_CELLS} pour "
              f"qu'un départ au CENTRE soit distinct des DEUX extrémités. En dessous, le point "
              f"démarre parfois SUR sa cible et chaque pas correct est étiqueté erreur (à 1 case, "
              f"il sort même de la piste). Le contrat réseau, lui, s'en moque : c'est ce "
              f"programme-ci qui devient faux, pas le moteur.")
        return False

    if smoke:
        return _smoke(n_cells, taux_erreur)

    import pygame  # import tardif : le module s'importe même sans pygame installé

    from stimulus.refresh import measure_refresh  # même mesure que les autres stimuli

    pygame.init()
    pygame.font.init()

    if windowed:
        size = (1000, 700)
        flags = pygame.SCALED
    else:
        disp_info = pygame.display.Info()
        size = (disp_info.current_w, disp_info.current_h)
        flags = pygame.FULLSCREEN | pygame.SCALED

    # vsync=1 : le pas est cadencé par le balayage écran, comme les autres stimuli.
    try:
        win = pygame.display.set_mode(size, flags, vsync=1)
    except (TypeError, pygame.error):
        win = pygame.display.set_mode(size, flags)
    pygame.display.set_caption("ErrP stimulus — EEG_API_Unicorn")
    pygame.mouse.set_visible(False)

    if refresh is None:
        refresh = measure_refresh(pygame, win)

    # Le flux de marqueurs : nom et type FIGÉS (contrat public, core/config.py). `source_id`
    # unique par PID -> deux instances de ce stimulus ne se confondent jamais l'une l'autre.
    info = StreamInfo(stream_name, "Markers", 1, IRREGULAR_RATE, "string",
                      f"errp-stim-{os.getpid()}")
    outlet = StreamOutlet(info)

    print(f"[errp-stim] refresh écran   : {refresh:.0f} Hz")
    print(f"[errp-stim] piste de {n_cells} cases, erreurs délibérées ≈ {taux_erreur:.0%} "
          f"(feedback {ERRP_FEEDBACK_S:g} s + pause {PAUSE_INTER_PAS_S:g} s = "
          f"{ERRP_FEEDBACK_S + PAUSE_INTER_PAS_S:g} s entre deux pas, comme la calibration)")
    print(f"[errp-stim] marqueurs publiés sur « {stream_name} »")
    if seed is not None:
        print(f"[errp-stim] graine {seed} — la séquence des erreurs est REJOUABLE à l'identique")

    # ⚠️ Attendre le moteur AVANT le premier pas — même raisonnement que p300_stimulus.py : sans
    # ça, un étudiant qui a oublié de lancer le moteur regarde un écran fonctionnel sans le moindre
    # signe que personne n'écoute. L'attente est BORNÉE et on démarre quand même après.
    attente_initiale_s, note_initiale = PAUSE_NOUVELLE_COURSE_S, "nouvelle cible"
    if attente_consommateur_s > 0 and not outlet.wait_for_consumers(attente_consommateur_s):
        print(f"[errp-stim] ⚠️ PERSONNE n'écoute « {stream_name} » après "
              f"{attente_consommateur_s:g} s. Le moteur est-il lancé "
              f"(`python src/core/server.py --mode errp`) ? Je continue quand même — l'indicateur "
              f"en haut de l'écran dit qui écoute, en direct.")
    elif attente_consommateur_s > 0:
        # ⚠️ « Quelqu'un écoute » n'est PAS « quelqu'un décode ». `wait_for_consumers` répond oui
        # dès que l'inlet du moteur est résolu, c'est-à-dire à son DÉMARRAGE ; le mode ErrP jette
        # ensuite tout ce qui arrive pendant sa chauffe et son repos (`_jeter_marqueurs_de_chauffe`
        # core/modes/errp.py). Marcher pendant ce temps, c'est offrir ~23 pas dont AUCUN ne sera
        # décodé — et le repos du moteur, lui, demande un écran immobile.
        # ⚠️ `ATTENTE_MOTEUR_DECODAGE_S`, pas `ATTENTE_MOTEUR_S` : ici c'est bien le MODE qui
        # tourne, donc chauffe ET repos. La calibration, elle, n'a pas de repos — cf. les deux
        # constantes en tête de fichier, qui ne valent PAS la même chose pour cette raison.
        print(f"[errp-stim] le moteur écoute — mais il JETTE tout pendant sa chauffe et son repos "
              f"(~{ATTENTE_MOTEUR_DECODAGE_S:g} s : {SSVEP_WARMUP_S:g} + "
              f"{ATTENTE_MOTEUR_REPOS_S:g} s, cf. core/modes/errp.py). Piste STATIQUE en attendant "
              f"— les pas décodés seront ceux d'après. `--no-wait` pour démarrer tout de suite.")
        attente_initiale_s = ATTENTE_MOTEUR_DECODAGE_S
        note_initiale = (f"le moteur chauffe (~{ATTENTE_MOTEUR_DECODAGE_S:g} s) — la piste "
                         f"démarre après")

    w, h = size
    cy = h / 2
    dx = int(w * 0.09)
    x0 = int(w / 2 - (n_cells - 1) * dx / 2)
    r = max(6, int(min(dx * 0.32, h * 0.05)))
    # ENTIERS, et calculés une SEULE fois : ce sont les centres exacts auxquels les cases sont
    # tracées, donc ceux auxquels `--smoke` va relire le point et la cible dans les pixels.
    # Recalculés de son côté, le test chercherait à quelques pixels près et ne trouverait rien —
    # un test qui échoue pour la mauvaise raison est pire qu'un test absent (même discipline que
    # `rayon_cue` dans `stimulus/p300.py`).
    centres = [(x0 + i * dx, int(cy)) for i in range(n_cells)]

    hud_font = pygame.font.SysFont("consolas", max(12, int(min(w, h) * 0.016)))
    note_font = pygame.font.SysFont("consolas", max(16, int(min(w, h) * 0.030)))

    clock = pygame.time.Clock()
    rng = random.Random(seed)
    running = True
    pas_total = 0
    erreurs_total = 0
    # ⚠️ `None` tant que la STIMULATION n'a pas commencé : `--seconds` compte le temps pendant
    # lequel des marqueurs partent, pas l'attente du moteur. Posé avant, il produisait une séance
    # entièrement muette, en silence et avec une sortie 0 : `--seconds 20` (l'exemple de la
    # docstring !) expirait PENDANT les ~23 s de chauffe+repos du moteur, la boucle principale
    # n'était jamais exécutée, l'étudiant regardait une piste immobile puis l'invite revenait sans
    # un mot. Voir aussi le bilan imprimé en fin de `run`.
    t_start = None

    def emet(m, erreur, debut_de_course):
        """Pousse un marqueur et l'horodate. UN SEUL endroit prend `local_clock()`."""
        ts = local_clock()
        outlet.push_sample([json.dumps(m)], timestamp=ts)
        if journal is not None:
            journal.append((m, ts, erreur, debut_de_course))
        return ts

    def poll():
        """Événements + la limite `--seconds`, vérifiés à CHAQUE frame (pas seulement entre deux
        pas) : un étudiant qui règle une durée veut qu'elle soit tenue, pas arrondie au pas
        supérieur (~1,45 s ici, le même défaut que p300_stimulus.py corrigeait pour ses manches).
        La fenêtre de feedback EN COURS, elle, va jusqu'au bout : cf. la boucle principale."""
        nonlocal running
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False
        if seconds is not None and t_start is not None and (time.perf_counter() - t_start) >= seconds:
            running = False

    def draw(pos, cible, note=None):
        win.fill(BG)
        for centre in centres:
            pygame.draw.circle(win, OUTLINE, centre, r, 2)
        pygame.draw.circle(win, GOAL_COLOR, centres[cible], r + 3)   # la cible : disque PLEIN
        pygame.draw.circle(win, ON_COLOR, centres[pos], r)          # le point, PAR-DESSUS
        if note is not None:
            txt = note_font.render(note, True, NOTE)
            win.blit(txt, txt.get_rect(center=(int(w / 2), int(cy + h * 0.16))))
        # L'indicateur d'écoute, en direct : c'est la seule chose de cet écran qui distingue
        # « ça marche » de « ça a l'air de marcher ».
        ecoute = "moteur À L'ÉCOUTE" if outlet.have_consumers() else "PERSONNE n'écoute"
        taux_mesure = f"{erreurs_total / pas_total:.0%}" if pas_total else "—"
        hud = hud_font.render(f"pas {pas_total}  |  erreurs {taux_mesure} (visé {taux_erreur:.0%})  "
                              f"|  {refresh:.0f} fps  |  {ecoute}  |  ESC = quitter", True, HUD)
        win.blit(hud, (12, 10))

    def tenir(pos, cible, secondes, note=None):
        """Tient la piste IMMOBILE `secondes` : aucun marqueur ne part, l'image ne change pas.

        Les trois attentes du protocole passent par ici (pause inter-pas, fin de course, nouvelle
        cible) : c'est le `_track_hold` de `research/errp_calibrate.py`, réduit à ce dont un
        émetteur a besoin. Une attente n'est PAS un `time.sleep` : la fenêtre doit continuer à se
        rafraîchir (sinon l'OS la déclare « ne répond pas ») et ESC doit rester vivant.
        """
        t0 = time.perf_counter()
        while running and (time.perf_counter() - t0) < secondes:
            poll()
            draw(pos, cible, note=note)
            pygame.display.flip()
            clock.tick(int(refresh) + 5)

    pos = n_cells // 2
    cible = nouvelle_cible(n_cells, rng)
    n_pas_course = 0
    essais = int(essais)
    seance_complete = False

    if calibrer:
        # ⚠️ `trials` compte des ÉPOQUES, et ici une époque = un pas : c'est l'unité que le moteur
        # incrémente à chaque feedback enregistré (`core/modes/marker_calib.py::total`). Une autre
        # unité n'empêcherait rien mais afficherait un avancement faux et ferait mal régler la
        # détection de fenêtre morte.
        emet({"mode": "errp", "event": "calib_start", "trials": essais}, None, False)
        print(f"[errp-stim] CALIBRATION : {essais} pas annoncés — chaque feedback portera son "
              f"étiquette `error`, ce que le décodage ne fait JAMAIS")
        if attente_consommateur_s > 0 and not outlet.have_consumers():
            print(f"[errp-stim] ⚠️ et PERSONNE n'écoute : cette séance ne produira AUCUN modèle. "
                  f"Lance la calibration depuis la console, ou ferme cette fenêtre.")
        # La CHAUFFE du moteur (~15 s) : les pas joués pendant ce temps sont comptés et JETÉS
        # (`marker_calib::encaisser`, phase « chauffe »), donc la séance serait plus courte que ce
        # que l'écran annonce. Le `calib_start`, lui, est bien retenu par le moteur pendant sa
        # chauffe — c'est pour ça qu'il part AVANT cette attente et pas après.
        # ⚠️ Pas le repos du MODE : une calibration n'en a pas, et l'attendre quand même faisait
        # abandonner la séance avant son premier pas (cf. `ATTENTE_MOTEUR_S` en tête de fichier).
        attente_initiale_s = (ATTENTE_MOTEUR_S if attente_moteur_s is None
                              else float(attente_moteur_s))
        note_initiale = "le casque se stabilise — installe-toi, ne bouge plus"
        if attente_initiale_s > 0:
            print(f"[errp-stim] le moteur JETTE tout pendant sa chauffe (~{attente_initiale_s:g} "
                  f"s) : piste STATIQUE en attendant, le premier pas part après.")

    # ⚠️ La piste doit être VUE avant son premier pas : sans cet écran, le tout premier feedback
    # est aussi la première image de la séance, l'utilisateur n'a pas eu le temps de voir d'où le
    # point part ni où il doit aller — donc aucune attente à violer, donc pas d'ErrP.
    tenir(pos, cible, attente_initiale_s, note=note_initiale)
    t_start = time.perf_counter()   # LA STIMULATION commence ici — cf. le ⚠️ de `t_start`

    while running:
        nouvelle_pos, erreur = decide_pas(rng, pos, cible, n_cells, taux_erreur)
        pos = nouvelle_pos
        n_pas_course += 1
        debut_de_course = (n_pas_course == 1)
        n_fr = max(1, int(round(ERRP_FEEDBACK_S * refresh)))
        for f in range(n_fr):
            poll()
            if not running and f == 0:
                break            # rien n'est encore parti sur le réseau : on peut couper net
            draw(pos, cible)
            pygame.display.flip()
            # ⚠️ L'HORODATAGE SE PREND ICI, juste après le basculement de frame — pas avant de
            # dessiner, pas au moment de décider le pas. Une charge utile parfaite envoyée 40 ms
            # trop tôt décale TOUTES les époques d'une frame, et le décodeur corrèle alors contre
            # une réponse évoquée qui n'a pas encore eu lieu.
            if f == 0:
                # `marqueur_feedback` est l'UNIQUE endroit qui décide si l'étiquette part : en
                # calibration oui, en décodage jamais (cf. le ⚠️⚠️ de la docstring du module).
                ts = emet(marqueur_feedback(erreur, calibrer), erreur, debut_de_course)
                pas_total += 1
                erreurs_total += int(erreur)
                if sonde_ecran is not None:
                    # L'écran EXACT sur lequel ce feedback vient de partir. Cf. la docstring de
                    # `run` : c'est ce qui permet à `--smoke` de LIRE le pas joué au lieu de croire
                    # le compteur de cet émetteur.
                    sonde_ecran(win, list(centres), r)
                # `t=` est l'horodatage LSL EXACT du marqueur : c'est lui qui permet, après la
                # séance, de raccrocher cette ligne à l'échantillon `decoded_errp` correspondant
                # et de calculer un TPR/TNR — sans jamais mettre la vérité-terrain sur le réseau.
                print(f"[errp-stim] t={ts:.3f}  pas {pas_total} : point -> case {pos} "
                      f"({'ÉLOIGNÉ (erreur)' if erreur else 'rapproché (correct)'})")
            clock.tick(int(refresh) + 5)
            # ⚠️ Pas de `if not running: break` ici : le marqueur est DÉJÀ parti, et le moteur va
            # épocher jusqu'à +ERRP_EPOCH_S après lui. Couper l'écran au milieu de cette fenêtre
            # ferait décoder une époque dont l'image a disparu en cours de route. On finit la
            # fenêtre, PUIS on sort (au pire ~1 s de plus que `--seconds`).
        if not running:
            break
        if calibrer and pas_total >= essais:
            # ⚠️ Ici, et pas après les écrans de fin de course : la séance s'arrête sur son
            # dernier PAS. Enchaîner une remise à zéro dont plus aucun feedback ne suit ferait
            # regarder l'étudiant une piste morte pendant 1,6 s avant l'écran de fin.
            seance_complete = True
            break

        if pos == cible or n_pas_course >= max_run_steps:
            atteinte = pos == cible
            print(f"[errp-stim] {'cible atteinte' if atteinte else 'pas max atteint'} en "
                  f"{n_pas_course} pas — nouvelle course")
            # ⚠️ LES DEUX ÉCRANS QUI MANQUAIENT. La remise à zéro déplace le point de 2 à 4 cases
            # ET fait changer la cible d'extrémité une fois sur deux : sans eux, ce transitoire
            # plein écran tombe DANS la frame horodatée du feedback suivant, et le moteur décode
            # une époque hors protocole (14,9 % d'entre elles, mesuré) en publiant un verdict
            # parfaitement confiant. Le premier écran montre l'état FINAL, le second l'état NEUF —
            # c'est le second qui fait le travail. `errp_calibrate._run_block` joue désormais les
            # deux au même endroit, avec les mêmes durées : les deux protocoles sont alignés.
            tenir(pos, cible, PAUSE_FIN_COURSE_S,
                  note="cible atteinte" if atteinte else "on recommence")
            pos = n_cells // 2
            cible = nouvelle_cible(n_cells, rng)
            n_pas_course = 0
            tenir(pos, cible, PAUSE_NOUVELLE_COURSE_S, note="nouvelle cible")
        else:
            tenir(pos, cible, PAUSE_INTER_PAS_S)     # pause inter-pas / settle (cadence du modèle)

    if calibrer and seance_complete:
        # ⚠️ Laisser la DERNIÈRE époque se remplir avant d'annoncer la fin. Le moteur ne libère un
        # marqueur qu'une fois son post-stimulus écoulé (`markers_murs(post_s=…)`) : un `calib_end`
        # publié dans la foulée du dernier pas arriverait bien après lui, mais l'écran, lui, serait
        # déjà noir et le sujet aurait bougé. Même geste que chez le P300.
        tenir(pos, cible, ERRP_EPOCH_S + 0.15, note="calibration terminée — ne bouge plus")
        emet({"mode": "errp", "event": "calib_end"}, None, False)
        print(f"[errp-stim] calibration terminée : {pas_total} pas, « calib_end » envoyé — le "
              f"moteur entraîne, le résultat s'affiche dans la console.")
    elif calibrer:
        # ⚠️ AUCUN `calib_end` : la séance est incomplète, et le moteur ne doit RIEN entraîner
        # dessus. Un modèle appris sur un tiers de séance serait indiscernable d'un modèle complet
        # dans la liste de la console, et donnerait ensuite des scores plausibles et faux.
        print(f"[errp-stim] ⚠️ calibration INTERROMPUE à {pas_total}/{essais} pas : AUCUN "
              f"« calib_end » envoyé, donc aucun modèle ne sera entraîné. Le moteur attend — "
              f"clique « Abandonner » dans la console, puis recommence.")

    # Un BILAN, toujours : « 0 pas joué » doit se lire, pas se deviner. Une séance muette (fenêtre
    # fermée trop tôt, `--seconds` trop court) et une séance réussie se ressemblaient à l'écran
    # comme au terminal — sortie 0 dans les deux cas.
    taux_reel = f"{erreurs_total / pas_total:.0%}" if pas_total else "—"
    print(f"[errp-stim] fin : {pas_total} pas joués, {erreurs_total} erreurs délibérées "
          f"({taux_reel}, visé {taux_erreur:.0%})"
          + ("" if pas_total else "  ⚠️ AUCUN marqueur n'est parti : `--seconds` couvre-t-il bien "
                                  "la durée de stimulation voulue, la fenêtre a-t-elle été fermée "
                                  "tout de suite ?"))
    pygame.quit()
    return True


# --- --smoke : le protocole en pur (grande échelle), PUIS la boucle réelle --

def _empreinte_ecran(pygame):
    """Une empreinte de CE QUI EST À L'ÉCRAN, sans rien savoir de la géométrie du stimulus.

    Réduire à 100x70 avant de hacher coûte ~20 µs (mesuré) : assez peu pour tenir 60 fps sous le
    pilote `dummy`, assez fin pour qu'un point qui saute d'une case change l'empreinte.
    """
    surface = pygame.display.get_surface()
    if surface is None:
        return None
    return hash(pygame.transform.scale(surface, (100, 70)).get_buffer().raw)


def _feedbacks(journal):
    """Les seules entrées du journal qui sont des PAS. `calib_start`/`calib_end` n'en sont pas :
    ils encadrent la séance et leurs écarts au premier/dernier pas n'ont aucune cadence à tenir."""
    return [e for e in journal if e[0].get("event") == "feedback"]


def _ecarts(journal):
    """(intra_course, transitions) : les écarts entre onsets, séparés par CE QUE LE PROTOCOLE A
    INTERCALÉ entre eux — la pause inter-pas seule, ou les deux écrans de fin de course.

    Les confondre en une seule moyenne était exactement le trou de la revue : une tolérance de
    ±50 % autour de 1 s acceptait aussi bien 1,0 s (l'émetteur d'avant, hors protocole) que 1,45 s
    (la cadence du modèle) que 2,6 s (une transition).
    """
    pas = _feedbacks(journal)
    intra, transitions = [], []
    for (_ma, ta, _ea, _da), (_mb, tb, _eb, debut) in zip(pas, pas[1:]):
        (transitions if debut else intra).append(tb - ta)
    return intra, transitions


def _piste_a_l_ecran(surface, centres, r):
    """(case du POINT, case de la CIBLE), lues dans les PIXELS. -1 quand on ne trouve pas.

    ⚠️ C'est le point de tout ce garde-fou : on ne demande pas à l'émetteur quel pas il croit
    avoir joué — il ne peut que se donner raison. On regarde l'image, et on en RECALCULE
    l'étiquette (« ce pas a-t-il éloigné le point de sa cible ? »). Même famille de test que la
    sonde à pixels de `stimulus/p300.py` et que celle de `stimulus/cvep.py`.

    Le point est un disque PLEIN de rayon `r` tracé PAR-DESSUS tout le reste : son centre porte
    donc `ON_COLOR` exact (`pygame.draw.circle` ne lisse pas). La cible est un disque plein de
    rayon `r + 3` tracé AVANT lui : on la lit à `r + 2` du centre — à l'intérieur d'elle, en
    dehors du point ET en dehors du contour de case (tracé à `r`, épaisseur 2, donc [r-2, r]).
    C'est ce décalage qui permet de lire les DEUX quand le point est arrivé sur sa cible.

    ⚠️ **Ce qu'elle n'attrape PAS, et il faut le savoir avant de s'y fier** : remonter le `emet`
    au-dessus du `flip`. Sous le pilote logiciel à tampon UNIQUE (`SDL_VIDEODRIVER=dummy`, celui
    du smoke), la surface porte déjà l'image dessinée avant même le `flip` — la sonde lirait la
    même chose des deux côtés. Elle prouve QUEL pas est à l'écran, jamais QUAND il y est arrivé.
    Le QUAND est gardé un cran plus haut, par l'empreinte d'écran de `_smoke` (partie B).
    """
    largeur, hauteur = surface.get_width(), surface.get_height()

    def couleur(x, y):
        if 0 <= x < largeur and 0 <= y < hauteur:
            return tuple(surface.get_at((int(x), int(y))))[:3]
        return None

    pos = cible = -1
    for i, (x, y) in enumerate(centres):
        if couleur(x, y) == ON_COLOR:
            pos = i
        if couleur(x + r + 2, y) == GOAL_COLOR:
            cible = i
    return pos, cible


def _smoke(n_cells, taux_erreur):
    """Trois moitiés, comme `stimulus/p300.py::_smoke` — la troisième est la calibration.

    **A. Le PROTOCOLE** (`decide_pas`/`nouvelle_cible`, fonctions pures) : le point reste toujours
    sur la piste après rebond, et surtout le taux d'erreur RÉEL sur un grand nombre de pas — c'est
    ICI, avec un N élevé et sans le moindre écran, que « proche de ERRP_ERROR_RATE » se vérifie
    avec une marge STATISTIQUE qui veut dire quelque chose. À l'échelle d'un `--smoke` réel (~
    quelques secondes, cf. B), on n'a que quelques pas : aucune tolérance sur un taux d'erreur n'y
    serait honnête (rigueur statistique du projet : ne jamais conclure sur du bruit). S'y ajoute le
    test DIFFÉRENTIEL contre `errp_calibrate`, tant que le protocole est écrit deux fois.

    **B. `run()` POUR DE VRAI**, sur `SDL_VIDEODRIVER=dummy` — le patron de `p300_stimulus.py`
    depuis sa correction de revue : un `--smoke` qui retournerait avant l'import de pygame
    laisserait SANS AUCUNE COUVERTURE les lignes qui contiennent le geste flip->horodatage, la
    seule chose que ce fichier existe pour enseigner. Exécuter ces lignes ne suffisait pas non plus
    à les VÉRIFIER : `pygame.display.flip` et `StreamOutlet.push_sample` sont instrumentés pour
    enregistrer l'ordre RÉEL des deux gestes et l'état de l'écran à chaque flip. Deux passages :
    B1 aux réglages normaux (cadence intra-course), B2 avec un plafond de 2 pas et 100 % d'erreurs
    — le point ne peut alors JAMAIS rejoindre sa cible, donc le plafond et les écrans de fin de
    course sont exercés à coup sûr, au lieu d'une fois sur trois par chance.

    **C. `--calibrer`**, sur le même écran factice : la forme exacte de la séance, et surtout que
    l'étiquette `error` de chaque feedback décrit le pas que l'écran a RÉELLEMENT joué — le point
    et la cible lus dans les PIXELS (`_piste_a_l_ecran`), l'étiquette RECALCULÉE à partir d'eux.
    C'est la même faute que d'horodater avant le flip, sur un autre axe : le marqueur est
    parfaitement formé, il décrit juste autre chose que ce qu'on voit. Et son pendant, qui compte
    autant : **hors calibration, AUCUN feedback ne porte d'étiquette** — vérifié sur les trois
    passages B, où le moteur ne doit jamais recevoir la réponse qu'il est censé deviner.

    Ce qui n'est PAS revérifié ici : le transport LSL (mûrissement, horodatage, offset d'horloge)
    est déjà prouvé par `core/markers.py`.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # Posé AVANT tout import de pygame (direct ou via `research.errp_calibrate`) : aucun test de ce
    # dépôt n'ouvre de fenêtre.
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

    # --- A. Le protocole, en pur, à grande échelle --------------------------------
    rng = random.Random(0)
    pos, cible = n_cells // 2, nouvelle_cible(n_cells, rng)
    n_pas_vises, n_pas, n_err, hors_piste = 5000, 0, 0, False
    for _ in range(n_pas_vises):
        pos, erreur = decide_pas(rng, pos, cible, n_cells, taux_erreur)
        n_pas += 1
        n_err += int(erreur)
        if not (0 <= pos < n_cells):
            hors_piste = True
            break
        if pos == cible:
            pos, cible = n_cells // 2, nouvelle_cible(n_cells, rng)
    chk(not hors_piste, f"le point reste toujours dans [0, {n_cells}[ après rebond ({n_pas} pas)")

    taux_mesure = n_err / n_pas
    # Marge à 5 σ (loi binomiale, N=5000) : à cette échelle, une implémentation correcte du tirage
    # ne peut PAS sortir de cette fourchette par hasard ; une implémentation cassée (taux ignoré,
    # inversé, mal câblé) le peut et le fait.
    sigma = (taux_erreur * (1 - taux_erreur) / n_pas) ** 0.5
    chk(abs(taux_mesure - taux_erreur) < 5 * sigma,
        f"le taux d'erreur RÉEL sur {n_pas} pas ({taux_mesure:.1%}) reste proche de celui visé "
        f"({taux_erreur:.0%}, marge ±{5 * sigma:.1%} à 5σ)")

    # `force=True` impose le TIRAGE (intention « erreur »), pas l'étiquette : au bord de la piste,
    # le rebond peut retourner un pas voulu erreur en pas qui RAPPROCHE réellement de la cible
    # (même comportement que `research/errp_calibrate.py:_decide_step`, documenté dans
    # `decide_pas`). Vérifié ici en position 0 -> le rebond inverse effectivement l'étiquette.
    pos_bord, erreur_bord = decide_pas(random.Random(1), 0, n_cells - 1, n_cells, taux_erreur,
                                       force=True)
    chk(pos_bord == 1 and erreur_bord is False,
        f"au bord de la piste, une erreur FORCÉE rebondit vers la cible : l'étiquette suit "
        f"l'effet RÉEL du pas, pas l'intention du tirage (pos={pos_bord}, erreur={erreur_bord})")

    # --- LA GARDE DE CE FICHIER, dans les DEUX sens, avant tout écran ---------------
    # `marqueur_feedback` est l'unique endroit qui décide si la vérité-terrain part sur le réseau.
    # Une garde écrite dans un seul sens laisse passer la moitié de la panne : « l'étiquette est
    # là en calibration » ne dit RIEN de « elle n'y est pas en décodage », qui est celui des deux
    # qui rend faux tout ce que le produit affirme sur ce mode.
    chk(marqueur_feedback(True, calibrer=False) == {"mode": "errp", "event": "feedback"}
        and marqueur_feedback(False, calibrer=False) == {"mode": "errp", "event": "feedback"},
        f"EN DÉCODAGE le marqueur est NU, quel que soit le pas joué : l'ErrP est une BCI PASSIVE, "
        f"le moteur doit DEVINER l'erreur depuis l'EEG — la lui donner ne casserait rien de "
        f"visible et rendrait faux tout ce qu'on mesure ({marqueur_feedback(True, False)})")
    chk(marqueur_feedback(True, calibrer=True) == {"mode": "errp", "event": "feedback",
                                                   "error": True}
        and marqueur_feedback(False, calibrer=True).get("error") is False,
        f"EN CALIBRATION il porte son étiquette, et elle est BOOLÉENNE : sans elle, aucune époque "
        f"n'a de vérité-terrain et il n'y a rien à entraîner "
        f"({marqueur_feedback(False, calibrer=True)})")
    chk(marqueur_feedback(erreur_bord, calibrer=True).get("error") is False,
        f"…et au bord, un tirage « erreur » qui REBONDIT vers la cible est publié `error: false` — "
        f"l'étiquette publiée suit l'EFFET du pas, jamais l'intention du tirage : l'étiqueter à "
        f"l'intention apprendrait au modèle le CONTRAIRE de ce qu'il doit détecter, sur environ un "
        f"pas de bord sur deux")

    # Le taux d'erreurs ÉTIQUETÉES, à grande échelle et sans écran — c'est ici qu'il veut dire
    # quelque chose. La séance de `--smoke` (partie C) fait quelques pas : aucune tolérance sur un
    # taux n'y serait honnête (rigueur statistique du projet : ne jamais conclure sur du bruit).
    rng_lab = random.Random(5)
    pos_lab, cible_lab, etiquettes = n_cells // 2, nouvelle_cible(n_cells, rng_lab), []
    for _ in range(5000):
        pos_lab, err_lab = decide_pas(rng_lab, pos_lab, cible_lab, n_cells, taux_erreur)
        etiquettes.append(bool(marqueur_feedback(err_lab, calibrer=True).get("error")))
        if pos_lab == cible_lab:
            pos_lab, cible_lab = n_cells // 2, nouvelle_cible(n_cells, rng_lab)
    taux_etiquete = sum(etiquettes) / len(etiquettes)
    chk(abs(taux_etiquete - taux_erreur) < 5 * sigma,
        f"le taux d'erreurs PUBLIÉES en calibration ({taux_etiquete:.1%}) reste dans sa plage "
        f"({taux_erreur:.0%}, marge ±{5 * sigma:.1%} à 5σ) — le modèle a besoin d'une classe "
        f"minoritaire d'environ un quart, pas d'un déséquilibre à 5 %")

    # --- Le protocole n'est plus écrit qu'UNE fois -------------------------------
    # Deux tests vivaient ici, et tous deux protégeaient une duplication : l'un rejouait 500 pas à
    # graine égale contre les fonctions de `research/errp_calibrate.py`, l'autre lisait le CODE
    # SOURCE de `_run_block` pour vérifier que les trois durées n'avaient pas dérivé. La
    # duplication a été supprimée le 2026-09-07 (`core/errp_track.py`) ; les deux tests avec elle.
    # Ce qui reste à vérifier n'est plus « les deux écritures s'accordent-elles » mais « cette
    # fenêtre utilise-t-elle bien la source unique » — sinon quelqu'un pourrait réintroduire une
    # copie locale, et les assertions de cadence plus bas, qui construisent `soa_intra` à partir
    # de `PAUSE_INTER_PAS_S`, se compareraient de nouveau à elles-mêmes sans rien voir.
    import core.errp_track as errp_track
    chk(decide_pas is errp_track.decide_pas and nouvelle_cible is errp_track.nouvelle_cible,
        "le protocole des pas vient de `core/errp_track.py`, pas d'une copie locale — c'est la "
        "MÊME règle qui entraîne le modèle et qui le joue")
    chk((PAUSE_INTER_PAS_S, PAUSE_FIN_COURSE_S, PAUSE_NOUVELLE_COURSE_S)
        == (errp_track.PAUSE_INTER_PAS_S, errp_track.PAUSE_FIN_COURSE_S,
            errp_track.PAUSE_NOUVELLE_COURSE_S),
        "…et les trois durées aussi : ce sont celles sous lesquelles les époques du modèle ont "
        "été enregistrées")

    # --- Le BUDGET de démarrage : ce que la fenêtre laisse au socle avant qu'il la croie morte ---
    # ⚠️ Cette assertion a été écrite APRÈS avoir mesuré la panne, pas en prévention. La fenêtre
    # attendait la chauffe du moteur PLUS le repos du MODE ErrP (8 s) — un repos qu'une CALIBRATION
    # ne joue jamais (`core/modes/calibration.py::PHASES` n'a pas de « rest »). Or le socle abandonne
    # une calibration après `CALIB_FENETRE_SILENCE_S` sans marqueur, décompté depuis la fin de sa
    # chauffe : tout ce que la fenêtre attend est pris sur CE budget-là, et le reste est ce qu'il
    # lui reste pour démarrer (init pygame, `set_mode`, mesure du rafraîchissement, jusqu'à 5 s de
    # `wait_for_consumers`). À 23 s d'attente il ne restait que 7 s, et une fenêtre lente était
    # déclarée morte avant son premier pas — en séance, cela coûte l'installation du casque.
    #
    # On exige donc que le reste couvre au moins `wait_for_consumers` PLUS une marge d'init. Écrit
    # comme une SOUSTRACTION des constantes du socle, jamais comme un nombre : sinon la prochaine
    # personne qui rallonge la chauffe rouvrirait le trou sans qu'aucun test ne bronche.
    from core.config import CALIB_FENETRE_SILENCE_S
    budget_demarrage_s = SSVEP_WARMUP_S + CALIB_FENETRE_SILENCE_S - ATTENTE_MOTEUR_S
    chk(budget_demarrage_s >= ATTENTE_CONSOMMATEUR_MAX_S + MARGE_INIT_PYGAME_S,
        f"la fenêtre laisse {budget_demarrage_s:.0f} s à son propre démarrage avant que le socle "
        f"ne la croie morte, soit au moins les {ATTENTE_CONSOMMATEUR_MAX_S:g} s de "
        f"`wait_for_consumers` plus {MARGE_INIT_PYGAME_S:g} s d'init pygame — sous ce seuil, une "
        f"calibration ABANDONNE avant son premier pas en accusant une fenêtre vivante (mesuré à "
        f"7 s de budget)")
    chk(ATTENTE_MOTEUR_S == SSVEP_WARMUP_S
        and ATTENTE_MOTEUR_DECODAGE_S == SSVEP_WARMUP_S + ATTENTE_MOTEUR_REPOS_S,
        f"...et les deux attentes restent DISTINCTES : le décodage attend le repos du mode "
        f"({ATTENTE_MOTEUR_DECODAGE_S:g} s), la calibration ne l'attend pas "
        f"({ATTENTE_MOTEUR_S:g} s) — c'est `ErrPCalibration` qui tourne alors, et elle n'a aucune "
        f"phase de repos")

    # ⚠️ Ce qu'AUCUN test ne couvre, ni avant ni maintenant : la PLACE où ces durées sont jouées.
    # `PAUSE_NOUVELLE_COURSE_S` ne l'est pas au même endroit des deux côtés (là-bas une fois par
    # BLOC, ici après chaque course). Écart assumé, chiffré dans la docstring du module.

    # --- La seule garde de réglage : une piste où le centre est une extrémité ------
    chk(run(windowed=True, refresh=60.0, n_cells=2, taux_erreur=taux_erreur, seconds=0.1,
            stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0) is False,
        f"--cells 2 est REFUSÉ avant d'ouvrir la moindre fenêtre (départ au centre = extrémité -> "
        f"pas corrects étiquetés erreur) ; il en faut {MIN_CELLS}")

    # --- B. run() POUR DE VRAI, sur un écran factice -------------------------------
    # Un flux au nom DISTINCT du contrat public : un smoke ne doit jamais pouvoir répondre à la
    # place d'un vrai émetteur (les noms de flux sont partagés par toutes les instances du projet).
    # `attente_consommateur_s=0` parce que personne n'écoute, par construction.
    import pygame

    import pylsl

    trace = []                   # l'ORDRE RÉEL des deux gestes, tel qu'il s'est produit
    vrai_flip = pygame.display.flip
    vrai_push = pylsl.StreamOutlet.push_sample
    # B3 seulement : demander la fermeture de la fenêtre EN PLEIN feedback. Compté en FRAMES
    # depuis le premier marqueur, pas en secondes -> le moment de la coupure ne dépend pas de la
    # vitesse de la machine.
    coupure = {"armee": False, "flips_depuis_push": None, "au_flip": 10}

    def flip_trace(*a, **k):
        r = vrai_flip(*a, **k)
        trace.append(("flip", _empreinte_ecran(pygame)))    # l'écran APRÈS le basculement
        if coupure["flips_depuis_push"] is not None:
            coupure["flips_depuis_push"] += 1
            if coupure["flips_depuis_push"] == coupure["au_flip"]:
                pygame.event.post(pygame.event.Event(pygame.QUIT))
        return r

    def push_trace(self, *a, **k):
        trace.append(("push", None))
        if coupure["armee"] and coupure["flips_depuis_push"] is None:
            coupure["flips_depuis_push"] = 0
        return vrai_push(self, *a, **k)

    pygame.display.flip = flip_trace
    pylsl.StreamOutlet.push_sample = push_trace
    try:
        journal = []
        fait = run(windowed=True, refresh=60.0, n_cells=n_cells, taux_erreur=taux_erreur,
                   seconds=6.5, stream_name=MARKER_STREAM_DEFAULT + "_smoke",
                   attente_consommateur_s=0.0, journal=journal, seed=0)
        trace_b1, journal2 = list(trace), []
        trace.clear()
        # B2 : 100 % d'erreurs -> la cible n'est JAMAIS atteinte ; seul le plafond peut terminer
        # une course. C'est le seul moyen d'exercer à coup sûr `max_run_steps` et les deux écrans
        # de fin de course, en quelques secondes.
        run(windowed=True, refresh=60.0, n_cells=n_cells, taux_erreur=1.0, seconds=7.0,
            stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
            journal=journal2, seed=0, max_run_steps=2)
        trace_b2, journal3 = list(trace), []
        trace.clear()
        # B3 : la fenêtre est INTERROMPUE au 10e flip après le marqueur. `seconds` reste loin
        # devant : c'est bien la fermeture de fenêtre qu'on teste, pas la limite de durée.
        coupure["armee"] = True
        run(windowed=True, refresh=60.0, n_cells=n_cells, taux_erreur=taux_erreur, seconds=20.0,
            stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
            journal=journal3, seed=0)
        trace_b3 = list(trace)
        trace.clear()
        coupure["armee"], coupure["flips_depuis_push"] = False, None

        # --- C. La CALIBRATION, sur le même écran factice -------------------------------
        # ⚠️ `taux_erreur=1.0` et un plafond de 5 pas : ce n'est pas la séance réelle, c'est la
        # séance qui EXERCE la garde. À 28 % d'erreurs, six pas peuvent très bien n'en contenir
        # aucune — et `[False]*6 == [False]*6` resterait vert avec un émetteur qui publierait
        # « correct » quoi qu'il arrive. À 100 %, le point s'éloigne à chaque pas jusqu'au BORD,
        # où le rebond le ramène vers la cible : ce pas-là est un `error: false` au milieu de
        # `error: true`, c'est-à-dire exactement le cas où intention et EFFET divergent. Le taux
        # d'erreurs, lui, se vérifie à grande échelle en partie A — pas sur six pas.
        # `attente_moteur_s=0.4` : assez pour qu'un écran statique précède le premier feedback (le
        # contrôle de frame CHANGÉE en a besoin), sans subir la chauffe réelle.
        journal_c, vues = [], []
        fait_c = run(windowed=True, refresh=60.0, n_cells=n_cells, taux_erreur=1.0,
                     calibrer=True, essais=6, max_run_steps=5, attente_moteur_s=0.4,
                     seconds=60.0, stream_name=MARKER_STREAM_DEFAULT + "_smoke",
                     attente_consommateur_s=0.0, journal=journal_c, seed=0,
                     sonde_ecran=lambda surface, centres, rayon: vues.append(
                         _piste_a_l_ecran(surface, centres, rayon)))
        trace_c = list(trace)
        trace.clear()
        # Et une séance INTERROMPUE : `--seconds` tombe pendant le premier pas.
        journal_i = []
        run(windowed=True, refresh=60.0, n_cells=n_cells, taux_erreur=taux_erreur,
            calibrer=True, essais=6, attente_moteur_s=0.0, seconds=0.1,
            stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
            journal=journal_i, seed=0)
    finally:
        pygame.display.flip = vrai_flip
        pylsl.StreamOutlet.push_sample = vrai_push

    chk(fait, "run() va au bout sur un écran factice (SDL_VIDEODRIVER=dummy)")
    chk(len(journal) >= 3, f"...et a RÉELLEMENT poussé plusieurs feedbacks ({len(journal)})")
    if not journal or not journal2:
        chk(False, "aucun feedback poussé : tout ce qui suit porterait sur une liste vide")
        print("[errp-stim] VERDICT : PROBLÈME")
        return False

    # ⚠️ LA MOITIÉ « DÉCODAGE » DE LA GARDE, sur le déroulé RÉEL des trois passages : pas un seul
    # marqueur ne porte autre chose que son mode et son événement. C'est la seule des deux moitiés
    # dont la violation ne casse RIEN de visible — mêmes flux, mêmes scores, juste faux.
    for nom, jn in (("B1", journal), ("B2", journal2), ("B3", journal3)):
        chk(jn and all(m == {"mode": "errp", "event": "feedback"} for m, _ts, _e, _d in jn),
            f"[{nom}] chaque marqueur poussé HORS calibration est EXACTEMENT "
            f"{{mode: errp, event: feedback}} — aucune étiquette, aucune case, rien : le moteur "
            f"ne doit jamais recevoir la réponse qu'il est censé deviner "
            f"({sorted({k for m, _t, _e, _d in jn for k in m})})")

    horodatages = [ts for _m, ts, _e, _d in journal]
    chk(all(b > a for a, b in zip(horodatages, horodatages[1:])),
        "les horodatages avancent strictement — un flip par pas, un horodatage par flip")

    # ⚠️⚠️ LE test de ce fichier : l'ordre flip -> push_sample, la seule chose qu'il existe pour
    # enseigner. Il tient en DEUX assertions, et c'est la seconde qui mord — mesuré, pas supposé.
    #
    # (1) L'ORDRE brut : un marqueur ne part jamais avant que le premier flip ait eu lieu. C'est
    #     l'invariant grossier, et il NE SUFFIT PAS : remonter `emet(...)` au-dessus de
    #     `pygame.display.flip()` le laisse VERT, parce qu'il reste toujours, juste avant le push,
    #     le flip de la frame PRÉCÉDENTE (la dernière du `tenir`, ou la frame f-1).
    # (2) LE CONTENU de la frame : le flip qui précède un marqueur doit être celui qui a CHANGÉ
    #     l'image — c'est la définition même de l'onset. C'est cette assertion-là qui attrape la
    #     mutation, et sur TOUS les marqueurs : mesuré 0/4 en B1 comme en B2, sortie 1.
    for nom, tr, jn in (("B1", trace_b1, journal), ("B2", trace_b2, journal2)):
        i_push = [i for i, (quoi, _e) in enumerate(tr) if quoi == "push"]
        chk(len(i_push) == len(jn) and all(i >= 1 and tr[i - 1][0] == "flip" for i in i_push),
            f"[{nom}] chaque marqueur part APRÈS un flip, jamais avant "
            f"({len(i_push)} push pour {len(jn)} feedbacks journalisés)")
        change = []
        for i in i_push:
            empreintes = [e for quoi, e in tr[:i] if quoi == "flip"]
            change.append(len(empreintes) >= 2 and empreintes[-1] != empreintes[-2])
        chk(bool(change) and all(change),
            f"[{nom}] ...et ce flip est celui qui a CHANGÉ l'écran (le point à sa nouvelle case), "
            f"pas une frame de plus du même écran ({sum(change)}/{len(change)})")

    # --- La CADENCE : celle du modèle, pas celle qui tombait bien -------------------
    soa_intra = ERRP_FEEDBACK_S + PAUSE_INTER_PAS_S
    soa_transition = ERRP_FEEDBACK_S + PAUSE_FIN_COURSE_S + PAUSE_NOUVELLE_COURSE_S
    intra1, trans1 = _ecarts(journal)
    intra2, trans2 = _ecarts(journal2)
    intra, transitions = intra1 + intra2, trans1 + trans2
    chk(bool(intra) and all(abs(e - soa_intra) <= 0.2 * soa_intra for e in intra),
        f"DANS une course, {soa_intra:g} s entre deux onsets (±20 %) — la cadence de "
        f"errp_calibrate, celle sous laquelle le modèle a été entraîné "
        f"({[round(e, 2) for e in intra]} s)")
    chk(bool(transitions) and all(e >= 0.8 * soa_transition for e in transitions),
        f"ENTRE deux courses, au moins {0.8 * soa_transition:.2f} s : les deux écrans statiques "
        f"({PAUSE_FIN_COURSE_S:g} s + {PAUSE_NOUVELLE_COURSE_S:g} s) séparent la remise à zéro de "
        f"la frame horodatée suivante ({[round(e, 2) for e in transitions]} s)")
    # ⚠️ `min`/`max` sont calculés À PART : un f-string est évalué AVANT d'entrer dans `chk`, donc
    # une liste vide y lèverait un `ValueError` — un traceback au lieu d'un « VERDICT : PROBLÈME ».
    # Mesuré en mutant le plafond de pas : le smoke sortait bien en 1, mais sans verdict lisible.
    plus_court, plus_long = (min(transitions) if transitions else 0.0,
                             max(intra) if intra else 0.0)
    chk(bool(transitions) and bool(intra) and plus_court > plus_long,
        f"...et une transition est toujours PLUS LONGUE qu'un pas ordinaire "
        f"({plus_court:.2f} s > {plus_long:.2f} s) — sans quoi la téléportation du point "
        f"tomberait dans l'époque du feedback suivant")

    # --- Le plafond de pas : exercé, pas décoratif ----------------------------------
    debuts2 = [d for _m, _ts, _e, d in journal2]
    chk(len(journal2) >= 4 and debuts2[:4] == [True, False, True, False],
        f"le PLAFOND de pas (ici 2) termine une course qui ne converge JAMAIS (100 % d'erreurs) : "
        f"une nouvelle course tous les 2 pas ({debuts2})")

    # --- Fermer la fenêtre ne coupe pas une époque en deux ---------------------------
    # Le marqueur est déjà parti quand l'utilisateur appuie sur ESC : le moteur épochera jusqu'à
    # +ERRP_EPOCH_S après lui. Si la fenêtre disparaît au milieu, il décode un verdict sur une
    # époque dont l'écran s'est éteint en cours de route — et c'est la DERNIÈRE de la séance, donc
    # celle qu'on regarde. La fenêtre de feedback en cours doit donc aller à son terme.
    n_fr_attendu = max(1, int(round(ERRP_FEEDBACK_S * 60.0)))
    i_dernier = max((i for i, (quoi, _e) in enumerate(trace_b3) if quoi == "push"), default=None)
    flips_apres = (sum(1 for quoi, _e in trace_b3[i_dernier:] if quoi == "flip")
                   if i_dernier is not None else 0)
    chk(len(journal3) == 1 and flips_apres >= 0.9 * n_fr_attendu,
        f"[B3] fenêtre fermée {coupure['au_flip']} frames après le marqueur : la fenêtre de "
        f"feedback va quand même à son TERME ({flips_apres} frames affichées après le marqueur, "
        f"sur {n_fr_attendu} attendues) — on ne coupe pas l'écran au milieu d'une époque")

    # --- C. La séance de CALIBRATION -------------------------------------------------
    chk(fait_c, "run(calibrer=True) va au bout sur un écran factice")
    evenements_c = [m["event"] for m, _ts, _e, _d in journal_c]
    chk(evenements_c == ["calib_start"] + ["feedback"] * 6 + ["calib_end"],
        f"la séance s'ouvre par calib_start, joue ses pas, et se ferme par calib_end "
        f"({evenements_c})")
    depart = journal_c[0][0]
    chk(depart.get("trials") == evenements_c.count("feedback"),
        f"`calib_start` annonce des ÉPOQUES, dans l'unité que le moteur compte — un pas, une "
        f"époque ({depart.get('trials')} annoncées, {evenements_c.count('feedback')} poussées)")

    pas_c = _feedbacks(journal_c)
    chk(all("error" in m for m, _ts, _e, _d in pas_c)
        and all(isinstance(m.get("error"), bool) for m, _ts, _e, _d in pas_c),
        f"EN CALIBRATION, chaque `feedback` porte son étiquette booléenne — sans elle, aucune "
        f"époque n'a de vérité-terrain ({[m.get('error') for m, _t, _e, _d in pas_c]})")

    # ⚠️⚠️ LE test de cette moitié, et le pendant de l'horodatage-au-flip : la vérité-terrain
    # publiée doit décrire ce que l'écran a RÉELLEMENT montré, pas ce que le tirage avait décidé.
    # On lit le point et la cible dans les PIXELS, et on RECALCULE l'étiquette (« ce pas a-t-il
    # éloigné le point ? »). Le départ d'un pas est la case lue au pas précédent — sauf en début de
    # course, où le point vient d'être remis au CENTRE devant une cible neuve : c'est justement la
    # transition que les deux écrans statiques séparent du feedback suivant.
    chk(len(vues) == len(pas_c) and all(p >= 0 and c >= 0 for p, c in vues),
        f"la sonde retrouve le point ET la cible dans les pixels, à chaque pas ({vues})")
    attendues, precedent = [], None
    for (_m, _ts, _e, debut), (pos_vu, cible_vue) in zip(pas_c, vues):
        depart_case = n_cells // 2 if debut else precedent
        attendues.append(abs(pos_vu - cible_vue) > abs(depart_case - cible_vue))
        precedent = pos_vu
    publiees = [m.get("error") for m, _ts, _e, _d in pas_c]
    chk(publiees == attendues,
        f"…et l'étiquette publiée est celle du pas RÉELLEMENT AFFICHÉ, relue à l'écran "
        f"({publiees} publiées contre {attendues} lues dans les pixels)")
    chk(len(set(publiees)) == 2,
        f"…sur une séance qui contient les DEUX étiquettes : à 100 % d'erreurs tirées, le rebond "
        f"de bord en fabrique une « correct » au milieu, donc une comparaison toute-vraie ou "
        f"toute-fausse ne peut pas passer par chance ({publiees})")

    # Le flip -> push de la calibration est un chemin de code DISTINCT (le marqueur est construit
    # par `marqueur_feedback`) : il mérite le même contrôle que B1/B2.
    i_push_c = [i for i, (quoi, _e) in enumerate(trace_c) if quoi == "push"]
    change_c = []
    for i in i_push_c[1:]:            # le premier push est `calib_start` : aucune frame à changer
        empreintes = [e for quoi, e in trace_c[:i] if quoi == "flip"]
        change_c.append(len(empreintes) >= 2 and empreintes[-1] != empreintes[-2])
    chk(len(i_push_c) == len(journal_c) and bool(change_c) and all(change_c[:len(pas_c)]),
        f"[C] en calibration aussi, chaque feedback part APRÈS le flip qui a CHANGÉ l'écran "
        f"({sum(change_c)}/{len(change_c)})")

    # Une séance INTERROMPUE ne publie AUCUN calib_end : le moteur ne doit rien entraîner sur une
    # séance tronquée, qui produirait un modèle que rien ne distingue d'un modèle complet.
    evenements_i = [m["event"] for m, _ts, _e, _d in journal_i]
    chk("calib_start" in evenements_i and "calib_end" not in evenements_i,
        f"une séance INTERROMPUE ne publie AUCUN calib_end — un modèle appris sur un pas sur six "
        f"serait indiscernable d'un modèle complet dans la liste ({evenements_i})")

    # ⚠️ Appelé SANS `ok and …` : `and` court-circuite, donc le bout-à-bout serait SAUTÉ dès qu'une
    # assertion précédente échoue — c'est-à-dire précisément quand on en a besoin. Le défaut a été
    # attrapé par mutation côté P300 ; `chk` met `ok` à jour par `nonlocal`, la valeur de retour
    # n'a rien à faire ici.
    _smoke_bout_en_bout(chk, journal_c, journal)

    n_err_reel = sum(1 for _m, _ts, e, _d in journal if e)
    print(f"[errp-stim] --smoke : {len(journal)} pas RÉELS (écran factice), {n_err_reel} erreurs "
          f"({n_err_reel / len(journal):.0%}, visé {taux_erreur:.0%} — N trop petit ici pour "
          f"trancher statistiquement, cf. la vérification à grande échelle de la partie A)")

    print(f"[errp-stim] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_bout_en_bout(chk, journal_calib, journal_decodage):
    """LES MARQUEURS DE CETTE FENÊTRE, donnés à la calibration du MOTEUR. Le seul test qui les fait
    se parler.

    Les deux moitiés du chantier se vérifient séparément partout ailleurs : la fenêtre publie une
    séquence (juste au-dessus), et le moteur sait en faire un modèle
    (`python src/core/modes/errp_calib.py`, qui rejoue une séance qu'il FABRIQUE lui-même). Rien ne
    prouvait qu'elles parlent de la même chose. Un désaccord de protocole — l'étiquette sur une
    autre clé, `calib_start` renommé, `error` publié en entier plutôt qu'en booléen — ne lève RIEN
    de visible : le moteur enregistre simplement moins d'époques, ou les refuse toutes, et l'on ne
    l'apprend qu'au bout d'une séance casque de six minutes.

    ⚠️ Ce test vit ICI et il ne peut pas vivre ailleurs : `core` n'a pas le droit d'importer
    `stimulus` (frontière vérifiée par `python src/core/server.py --smoke`), `stimulus -> core` est
    autorisé. C'est donc à l'émetteur de prouver que le moteur le comprend.

    On lui donne AUSSI le journal de DÉCODAGE, et c'est la moitié qui compte le plus : le moteur
    doit refuser ces marqueurs-là comme dépourvus de vérité-terrain. Une fenêtre laissée en
    décodage pendant une calibration ne doit pas produire un jeu d'entraînement silencieusement
    étiqueté « correct ».

    Le tampon EEG est à ZÉRO, exprès : on ne juge pas ici un décodage, seulement le PROTOCOLE —
    combien d'époques, sous quelles étiquettes. Et on n'entraîne pas (aucun `tick` après
    `calib_end`), donc rien n'est écrit sur le disque.
    """
    import tempfile

    import numpy as np

    from core.modes.errp import SPEC as SPEC_ERRP
    from core.modes.errp_calib import ErrPCalibration

    class _FausseAcq:
        fs = 250.0

    class _MoteurFactice:
        """Le strict nécessaire pour la calibration : un tampon EEG horodaté, une file vide."""

        def __init__(self, recent, recent_ts):
            self.acq = _FausseAcq()
            self.recent, self.recent_ts = recent, recent_ts

        def markers_murs(self, mode_id, post_s):
            return []      # les marqueurs sont donnés à la main, un par un, par `encaisser`

    def rejoue(journal_source, dossier, annonce=None):
        """Fait vivre une calibration du moteur sur un journal de cette fenêtre.

        `annonce` : un `calib_start` à injecter quand le journal n'en contient pas. C'est le cas du
        journal de DÉCODAGE, et il n'a rien d'artificiel — c'est la situation réelle qu'on veut
        éprouver : la console a bien demandé une calibration au moteur, mais la fenêtre lancée à
        côté, elle, tourne en décodage. Sans cette annonce, la calibration resterait en chauffe et
        jetterait tout sans jamais REGARDER un marqueur : on ne testerait pas le refus.
        """
        t_debut, t_fin = journal_source[0][1], journal_source[-1][1]
        recent_ts = np.arange(t_debut - 2.0, t_fin + 2.0, 1.0 / _FausseAcq.fs)
        moteur = _MoteurFactice(np.zeros((len(recent_ts), 8)), recent_ts)
        rt = ErrPCalibration(SPEC_ERRP, {}, moteur, dossier=dossier)
        rt.tick(moteur, t_debut)                    # démarre la chauffe

        def fin_de_chauffe():
            """La chauffe s'écoule d'un coup : c'est l'horloge de l'APPELANT, pas celle des
            marqueurs, et c'est justement ce qui permet de la traverser sans attendre. Elle ne peut
            s'écouler qu'APRÈS l'annonce — le socle n'ouvre les essais qu'une fois la fenêtre
            déclarée vivante, et tout ce qui arrive avant est jeté, pas refusé."""
            rt.tick(moteur, t_debut + rt.warmup_s + 0.01)

        if annonce is not None:
            rt.encaisser(moteur, t_debut, annonce)
            fin_de_chauffe()
        for m, ts_m, _e, _d in journal_source:
            rt.encaisser(moteur, ts_m, m)
            if m["event"] == "calib_start":
                fin_de_chauffe()
        return rt

    with tempfile.TemporaryDirectory(prefix="errp_stim_smoke_") as dossier:
        rt = rejoue(journal_calib, dossier)
        pas = _feedbacks(journal_calib)
        chk(rt.essai == len(pas) and len(rt._enregistre) == len(pas),
            f"le moteur enregistre UNE époque par pas de cette fenêtre "
            f"({rt.essai} pour {len(pas)} pas poussés)")
        chk(rt.total() == len(pas),
            f"...et le `trials` annoncé par la fenêtre est bien ce nombre-là : c'est sur lui que "
            f"la console affiche l'avancement et que le moteur juge une fenêtre morte "
            f"({rt.total()} annoncés)")
        chk(rt._refus == 0,
            f"aucun marqueur de cette fenêtre n'est refusé par le moteur ({rt._refus} refus)")
        chk([lab for _e, lab in rt._enregistre] == [m.get("error") for m, _t, _e, _d in pas],
            f"...et la vérité-terrain que le moteur retient est EXACTEMENT celle que la fenêtre a "
            f"publiée, pas par pas ({[lab for _e, lab in rt._enregistre]})")
        chk(rt.phase == "entrainement" and rt.resultat is None,
            f"`calib_end` a bien clos la séance côté moteur, sans qu'on lui demande d'entraîner "
            f"ici ({rt.phase})")

        # ⚠️ L'AUTRE SENS, et c'est celui qui protège le produit : les marqueurs du DÉCODAGE, qui
        # ne portent aucune étiquette, doivent être REFUSÉS. Une fenêtre restée en décodage
        # pendant qu'une calibration tourne ne doit pas produire un jeu entier d'époques
        # silencieusement rangées dans la classe majoritaire.
        rt_nu = rejoue(journal_decodage, dossier,
                       annonce={"mode": "errp", "event": "calib_start",
                                "trials": len(journal_decodage)})
        chk(rt_nu.essai == 0 and rt_nu._enregistre == []
            and rt_nu._refus == len(journal_decodage),
            f"les marqueurs de DÉCODAGE, eux, sont tous refusés par la calibration : ils n'ont "
            f"aucune vérité-terrain, et les ranger d'office en « correct » entraînerait le modèle "
            f"à ne jamais rien détecter ({rt_nu.essai} enregistrée(s), {rt_nu._refus} refus sur "
            f"{len(journal_decodage)} marqueurs)")


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Stimulus ErrP (EEG_API_Unicorn).")
    p.add_argument("--windowed", action="store_true", help="fenêtre au lieu du plein écran")
    p.add_argument("--refresh", type=float, default=None, help="forcer le refresh (Hz)")
    p.add_argument("--cells", type=int, default=ERRP_TRACK_CELLS,
                   help=f"cases de la piste (défaut {ERRP_TRACK_CELLS}, minimum {MIN_CELLS} — le "
                        f"moteur ne lit jamais cette valeur, cf. la docstring du module)")
    p.add_argument("--error-rate", type=float, default=ERRP_ERROR_RATE,
                   help=f"taux d'erreurs délibérées (défaut {ERRP_ERROR_RATE:g})")
    p.add_argument("--seconds", type=float, default=None,
                   help="auto-quit après N secondes de STIMULATION (le décompte démarre au premier "
                        "pas, pas pendant l'attente du moteur)")
    p.add_argument("--seed", type=int, default=None,
                   help="graine du tirage des erreurs : rejoue EXACTEMENT la même séquence (pour "
                        "refaire une séance à l'identique, ou pour la dépouiller hors ligne)")
    p.add_argument("--no-wait", action="store_true",
                   help="ne pas attendre le moteur (ni sa chauffe : ~23 s en décodage, ~15 s en "
                        "calibration, qui n'a pas de repos) : émetteur seul")
    p.add_argument("--calibrer", action="store_true",
                   help="séance de CALIBRATION : même piste, plus calib_start / calib_end, et "
                        "chaque feedback porte son étiquette `error` (ce que le décodage ne fait "
                        "JAMAIS). C'est le moteur qui entraîne — la console lance cette fenêtre "
                        "elle-même, la lancer à la main n'a de sens que pour la mettre au point")
    p.add_argument("--essais", type=int, default=ERRP_CAL_TRIALS,
                   help=f"pas de calibration (défaut {ERRP_CAL_TRIALS}). Sans --calibrer, ce "
                        f"réglage ne sert à rien : le décodage enchaîne les pas jusqu'à ESC")
    p.add_argument("--smoke", action="store_true",
                   help="test headless (CI) : le protocole ET la boucle réelle, sur écran factice")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    ok = run(windowed=args.windowed, refresh=args.refresh, n_cells=args.cells,
             taux_erreur=args.error_rate, seconds=args.seconds, smoke=args.smoke,
             seed=args.seed, attente_consommateur_s=0.0 if args.no_wait else 5.0,
             calibrer=args.calibrer, essais=args.essais)
    # Un réglage refusé (`--cells` trop petit) doit sortir en 1 même hors smoke : lancé depuis un
    # script, « ça n'a rien affiché » et « ça a refusé » ne doivent pas se ressembler.
    sys.exit(0 if ok else 1)
