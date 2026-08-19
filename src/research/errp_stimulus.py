"""Le stimulus ErrP, en programme AUTONOME qui publie ses marqueurs de feedback.

⚠️ **Ce programme n'ouvre PAS le casque.** C'est ce qui permet de le lancer EN MÊME TEMPS que le
moteur, dans deux terminaux — le même montage que pour le P300 et le SSVEP :

    python src/core/server.py --mode errp           # terminal 1 : acquiert et décode (EXIGE un
                                                      # modèle entraîné, cf. research/app.py -> ErrP)
    python src/research/errp_stimulus.py             # terminal 2 : affiche la piste et marque

C'est aussi l'exemple de référence pour qui voudra émettre depuis Unity : le protocole est ici,
et surtout l'endroit exact où prendre l'horodatage.

Protocole publié (figé, cf. docs/SPEC.md) — UNE SEULE forme de marqueur, sur le flux
`MARKER_STREAM_DEFAULT` (core/config.py), type "Markers", 1 voie "string", cadence irrégulière :

    {"mode": "errp", "event": "feedback"}     # le point vient de sauter à sa nouvelle case

⚠️ Contrairement au P300 (qui publie sa cible), ce marqueur ne porte AUCUNE autre information — ni
la case visée, ni si CE pas est une erreur délibérée. Le moteur ne lit que l'horodatage
(`core/modes/errp.py:_run_step` ignore tout le reste) : c'est justement ce qu'il doit DEVINER
depuis l'EEG (BCI **passive**). Publier la vérité-terrain sur le réseau reviendrait à lui donner la
réponse. Pour la mesurer HORS LIGNE quand même, chaque pas est imprimé au terminal avec son
horodatage LSL exact (`t=…`) : il suffit à raccrocher chaque ligne à l'échantillon `decoded_errp`
correspondant, et `--seed` rejoue la séquence à l'identique.

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
    python src/research/errp_stimulus.py                  # plein écran, ESC pour quitter
    python src/research/errp_stimulus.py --windowed       # fenêtre 1000x700 (dev)
    python src/research/errp_stimulus.py --cells 9        # cases de la piste (défaut ERRP_TRACK_CELLS)
    python src/research/errp_stimulus.py --error-rate 0.3 # taux d'erreurs délibérées (défaut ERRP_ERROR_RATE)
    python src/research/errp_stimulus.py --refresh 60     # forcer le refresh (sinon auto-mesuré)
    python src/research/errp_stimulus.py --seconds 20     # 20 s de STIMULATION (l'attente du
                                                          # moteur ne compte pas dans le décompte)
    python src/research/errp_stimulus.py --seed 1         # rejouer EXACTEMENT la même séquence
    python src/research/errp_stimulus.py --no-wait        # ne pas attendre le moteur (émetteur seul)
    python src/research/errp_stimulus.py --smoke          # test sans écran (CI) : protocole ET rendu
"""

import argparse
import json
import os
import random
import sys
import time

# Permet `from config import ...` que le module soit lancé via `python src/research/errp_stimulus.py`
# ou importé comme `src.errp_stimulus`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (ERRP_ERROR_RATE, ERRP_FEEDBACK_S, ERRP_MAX_RUN_STEPS,  # noqa: E402
                         ERRP_TRACK_CELLS, MARKER_STREAM_DEFAULT, SSVEP_WARMUP_S,
                         use_utf8_console)
from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, local_clock  # noqa: E402

# --- Réglages d'affichage ---------------------------------------------------

BG = (0, 0, 0)              # fond noir -> contraste maximal, même choix que les autres stimuli
ON_COLOR = (255, 255, 255)  # le point (curseur)
GOAL_COLOR = (60, 200, 90)  # la cible : pastille verte, même choix que research/errp_calibrate.py
OUTLINE = (55, 55, 70)      # les cases de la piste
HUD = (70, 90, 70)
NOTE = (110, 150, 110)      # les écrans d'attente : vert éteint, ne concurrence pas le point

# --- Le TEMPS du protocole : ces trois durées ne sont PAS du confort ---------
# Les VALEURS sont celles de `research/errp_calibrate.py:_run_block`, c'est-à-dire des conditions
# sous lesquelles les époques du modèle ont été enregistrées. Les changer ici, c'est décoder une
# distribution que le modèle n'a jamais apprise — sans qu'aucune exception ne soit levée. Un test
# de `--smoke` les arrime au SOURCE de `_run_block` (cf. `_smoke`, section « les durées »).
#
# ⚠️ Même valeur ne suffit pas : il faut la même PLACE. `_run_block` n'a longtemps joué son écran
# « nouvelle cible » qu'en tête de bloc, ce qui donnait la même constante à un SOA de transition
# différent (1,7 s là-bas, 2,6 s ici). Aligné depuis — les deux jouent les deux écrans à chaque fin
# de course. Un test arrime les VALEURS ; la PLACE, elle, ne se vérifie qu'en lisant les deux
# boucles, alors relire `_run_block` avant d'affirmer quoi que ce soit ici.

PAUSE_INTER_PAS_S = 0.45        # `_run_block` « pause inter-pas / settle » -> SOA intra 1,45 s
PAUSE_FIN_COURSE_S = 0.7        # `_run_block` « atteinte » / « on recommence », état FINAL
PAUSE_NOUVELLE_COURSE_S = 0.9   # `_run_block` « nouvelle cible », état NEUF — en tête de bloc ET
                                # après chaque course, des deux côtés

# Ce que le moteur JETTE avant d'écouter pour de bon : sa chauffe (l'offset DC de l'Unicorn dérive
# après ouverture) puis son repos (il y mesure la référence du rejet d'artefact). Valeurs lues dans
# `core/modes/errp.py` (SPEC.rest) : `warmup_s=SSVEP_WARMUP_S`, `duration_s=8.0`. C'est la plus
# longue attente des cinq modes, et `wait_for_consumers` répond « oui » bien avant qu'elle finisse.
ATTENTE_MOTEUR_REPOS_S = 8.0
ATTENTE_MOTEUR_S = SSVEP_WARMUP_S + ATTENTE_MOTEUR_REPOS_S

# En dessous, la piste est dégénérée — cf. la garde de `run` et le ⚠️ de la docstring du module.
MIN_CELLS = 3


# --- Le protocole (fonctions PURES, testables sans écran ni pygame) ---------

def nouvelle_cible(n_cells, rng):
    """La cible, à L'UNE des deux extrémités de la piste (tirage 50/50).

    Même choix que `research/errp_calibrate.py:_new_goal` : sur l'ensemble d'une séance, les
    erreurs (des pas qui ÉLOIGNENT) sont autant à gauche qu'à droite -> le SENS du mouvement est
    décorrélé de l'étiquette erreur/correct, un décodeur ne peut donc pas apprendre la direction à
    la place de l'ErrP (Chavarriaga 2010 équilibre ainsi).
    """
    return rng.choice([0, n_cells - 1])


def decide_pas(rng, pos, cible, n_cells, taux_erreur, force=None):
    """Un pas du point : avance d'une case vers `cible`, ou s'en éloigne si erreur DÉLIBÉRÉE.

    Même mécanique que `research/errp_calibrate.py:_decide_step` (et le démonstrateur de
    `research/app.py`) : `force` (utilisé par `--smoke`) impose une erreur (True) ou un pas
    correct (False) ; sinon tirage à `taux_erreur`. Rebond au bord de la piste (renvoie dans
    l'autre sens) — sans lui, un point qui atteint une extrémité sortirait de la piste. Retourne
    `(nouvelle_pos, erreur)` : `erreur` suit l'EFFET RÉEL du pas, après rebond éventuel — pas
    l'intention du tirage (un rebond peut transformer un tirage « erreur » en pas qui rapproche).

    ⚠️ Cette fonction est un DOUBLE de `_decide_step`, pas encore une source unique : `--smoke`
    compare les deux trajectoires pas à pas (cf. la docstring du module).
    """
    vers = 1 if cible > pos else -1
    erreur = (rng.random() < taux_erreur) if force is None else bool(force)
    pas = -vers if erreur else vers
    nouvelle_pos = pos + pas
    if nouvelle_pos < 0 or nouvelle_pos >= n_cells:            # bord -> rebond dans l'autre sens
        nouvelle_pos = pos - pas
    erreur_reelle = abs(nouvelle_pos - cible) > abs(pos - cible)
    return nouvelle_pos, erreur_reelle


# --- Boucle principale -------------------------------------------------------

def run(windowed=False, refresh=None, n_cells=ERRP_TRACK_CELLS, taux_erreur=ERRP_ERROR_RATE,
        seconds=None, smoke=False, stream_name=MARKER_STREAM_DEFAULT, attente_consommateur_s=5.0,
        journal=None, seed=None, max_run_steps=ERRP_MAX_RUN_STEPS):
    """La boucle du stimulus. `journal`, s'il est fourni, reçoit
    `(marqueur, horodatage, erreur, debut_de_course)` pour CHAQUE feedback réellement poussé.

    `erreur` (bool, vérité-terrain LOCALE : ce pas a-t-il ÉLOIGNÉ le point de sa cible) ne part
    JAMAIS sur le réseau (cf. ⚠️ de la docstring du module) — il n'existe que pour permettre à
    `--smoke` de vérifier, sur le déroulé RÉEL, que le taux d'erreur joué reste raisonnable, en
    plus de la fonction pure `decide_pas` (vérifiée à grande échelle, sans écran, dans `_smoke`).
    `debut_de_course` dit si ce pas est le PREMIER d'une nouvelle course, donc s'il a été précédé
    des deux écrans statiques : c'est ce qui permet à `--smoke` de mesurer séparément la cadence
    intra-course (1,45 s) et l'écart de transition (2,6 s), qu'une moyenne unique confondrait.

    `seed` graine le tirage des erreurs : deux exécutions rejouent alors la MÊME séquence, ce qui
    est la seule façon de refaire une séance à l'identique. `max_run_steps` n'existe que pour que
    `--smoke` puisse EXERCER le plafond de pas (sinon jamais atteint en quelques secondes).
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

    from research.ssvep_stimulus import measure_refresh  # même mesure que les autres stimuli

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
        print(f"[errp-stim] le moteur écoute — mais il JETTE tout pendant sa chauffe et son repos "
              f"(~{ATTENTE_MOTEUR_S:g} s : {SSVEP_WARMUP_S:g} + {ATTENTE_MOTEUR_REPOS_S:g} s, cf. "
              f"core/modes/errp.py). Piste STATIQUE en attendant — les pas décodés seront ceux "
              f"d'après. `--no-wait` pour démarrer tout de suite.")
        attente_initiale_s = ATTENTE_MOTEUR_S
        note_initiale = f"le moteur chauffe (~{ATTENTE_MOTEUR_S:g} s) — la piste démarre après"

    w, h = size
    cy = h / 2
    dx = int(w * 0.09)
    x0 = int(w / 2 - (n_cells - 1) * dx / 2)
    r = max(6, int(min(dx * 0.32, h * 0.05)))

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
        for i in range(n_cells):
            pygame.draw.circle(win, OUTLINE, (x0 + i * dx, int(cy)), r, 2)
        pygame.draw.circle(win, GOAL_COLOR, (x0 + cible * dx, int(cy)), r + 3)   # la cible
        pygame.draw.circle(win, ON_COLOR, (x0 + pos * dx, int(cy)), r)          # le point
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
                ts = emet({"mode": "errp", "event": "feedback"}, erreur, debut_de_course)
                pas_total += 1
                erreurs_total += int(erreur)
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


def _ecarts(journal):
    """(intra_course, transitions) : les écarts entre onsets, séparés par CE QUE LE PROTOCOLE A
    INTERCALÉ entre eux — la pause inter-pas seule, ou les deux écrans de fin de course.

    Les confondre en une seule moyenne était exactement le trou de la revue : une tolérance de
    ±50 % autour de 1 s acceptait aussi bien 1,0 s (l'émetteur d'avant, hors protocole) que 1,45 s
    (la cadence du modèle) que 2,6 s (une transition).
    """
    intra, transitions = [], []
    for (_ma, ta, _ea, _da), (_mb, tb, _eb, debut) in zip(journal, journal[1:]):
        (transitions if debut else intra).append(tb - ta)
    return intra, transitions


def _smoke(n_cells, taux_erreur):
    """Deux moitiés, comme `p300_stimulus._smoke`.

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

    # --- Le protocole est écrit DEUX fois : au moins, qu'il ne DÉRIVE pas ----------
    # Import tardif : `errp_calibrate` traîne numpy/sklearn/pygame, dont un émetteur n'a que faire
    # (il doit rester lançable à côté du moteur, sur une machine minimale). Les deux écritures
    # consomment le même nombre de tirages (1 `choice` par cible, 1 `random` par pas) : à graine
    # égale, leurs trajectoires doivent être identiques, pas seulement « du même genre ».
    from core.errp_decoder import ERROR
    from research.errp_calibrate import _decide_step, _new_goal, _run_block
    ra, rb = random.Random(7), random.Random(7)
    pos_a, pos_b = n_cells // 2, n_cells // 2
    cible_a, cible_b = nouvelle_cible(n_cells, ra), _new_goal(rb, n_cells)
    divergence = None if cible_a == cible_b else f"cible initiale {cible_a} vs {cible_b}"
    for i in range(500):
        if divergence:
            break
        pos_a, err_a = decide_pas(ra, pos_a, cible_a, n_cells, taux_erreur)
        pos_b, label_b = _decide_step(rb, pos_b, cible_b, n_cells, taux_erreur)
        if (pos_a, err_a) != (pos_b, label_b == ERROR):
            divergence = (f"pas {i} : ici ({pos_a}, erreur={err_a}) vs errp_calibrate "
                          f"({pos_b}, label={label_b})")
        elif pos_a == cible_a:
            pos_a, cible_a = n_cells // 2, nouvelle_cible(n_cells, ra)
            pos_b, cible_b = n_cells // 2, _new_goal(rb, n_cells)
    chk(divergence is None,
        f"500 pas joués à graine égale : `decide_pas`/`nouvelle_cible` et les `_decide_step`/"
        f"`_new_goal` de errp_calibrate (celles qui ENTRAÎNENT le modèle) donnent EXACTEMENT la "
        f"même trajectoire — le protocole est écrit deux fois, il ne doit pas dériver "
        f"({divergence or 'aucune divergence'})")

    # --- ...et les trois DURÉES ne doivent pas dériver non plus ---------------------
    # Le test différentiel ci-dessus ne couvre que le protocole des PAS. Les trois `PAUSE_*_S`
    # sont, elles aussi, une recopie de `_run_block`, et l'assertion de cadence (plus bas) les
    # compare à ELLES-MÊMES : `soa_intra` est construit avec `PAUSE_INTER_PAS_S`, donc passer cette
    # constante de 0,45 à 0,1 s laisse les 18 contrôles VERTS (mesuré). Le défaut corrigé au tour 2
    # se réintroduirait ainsi sans qu'un seul test bouge, et le moteur décoderait une distribution
    # jamais apprise. On les arrime donc au SOURCE de `_run_block`, où elles sont des littéraux.
    #
    # ⚠️ Ce contrôle prouve que les VALEURS sont celles de la calibration. Il ne prouve PAS qu'elles
    # soient jouées au même ENDROIT : `PAUSE_NOUVELLE_COURSE_S` ne l'est pas (là-bas une fois par
    # BLOC, ici après chaque course). Écart assumé, chiffré dans la docstring du module.
    import inspect
    src_bloc = inspect.getsource(_run_block)
    absentes = [f"{nom} = {v:g}" for nom, v in
                (("PAUSE_INTER_PAS_S", PAUSE_INTER_PAS_S),
                 ("PAUSE_FIN_COURSE_S", PAUSE_FIN_COURSE_S),
                 ("PAUSE_NOUVELLE_COURSE_S", PAUSE_NOUVELLE_COURSE_S))
                if f", {v:g}," not in src_bloc]
    chk(not absentes,
        f"les trois durées de cet émetteur sont CELLES sous lesquelles le modèle a été entraîné "
        f"(littéraux de errp_calibrate._run_block) — sinon le moteur décode une distribution "
        f"jamais apprise, sans qu'aucune exception ne soit levée "
        f"({'introuvables là-bas : ' + ', '.join(absentes) if absentes else 'les trois y sont'})")

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
    finally:
        pygame.display.flip = vrai_flip
        pylsl.StreamOutlet.push_sample = vrai_push

    chk(fait, "run() va au bout sur un écran factice (SDL_VIDEODRIVER=dummy)")
    chk(len(journal) >= 3, f"...et a RÉELLEMENT poussé plusieurs feedbacks ({len(journal)})")
    if not journal or not journal2:
        chk(False, "aucun feedback poussé : tout ce qui suit porterait sur une liste vide")
        print("[errp-stim] VERDICT : PROBLÈME")
        return False

    chk(all(m == {"mode": "errp", "event": "feedback"} for m, _ts, _e, _d in journal),
        "chaque marqueur poussé est EXACTEMENT {mode: errp, event: feedback} — rien d'autre : le "
        "moteur ne doit JAMAIS recevoir la vérité-terrain (cf. ⚠️ de la docstring du module)")

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

    n_err_reel = sum(1 for _m, _ts, e, _d in journal if e)
    print(f"[errp-stim] --smoke : {len(journal)} pas RÉELS (écran factice), {n_err_reel} erreurs "
          f"({n_err_reel / len(journal):.0%}, visé {taux_erreur:.0%} — N trop petit ici pour "
          f"trancher statistiquement, cf. la vérification à grande échelle de la partie A)")

    print(f"[errp-stim] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


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
                   help="ne pas attendre le moteur (ni ses ~23 s de chauffe) : émetteur seul")
    p.add_argument("--smoke", action="store_true",
                   help="test headless (CI) : le protocole ET la boucle réelle, sur écran factice")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    ok = run(windowed=args.windowed, refresh=args.refresh, n_cells=args.cells,
             taux_erreur=args.error_rate, seconds=args.seconds, smoke=args.smoke,
             seed=args.seed, attente_consommateur_s=0.0 if args.no_wait else 5.0)
    # Un réglage refusé (`--cells` trop petit) doit sortir en 1 même hors smoke : lancé depuis un
    # script, « ça n'a rien affiché » et « ça a refusé » ne doivent pas se ressembler.
    sys.exit(0 if ok else 1)
