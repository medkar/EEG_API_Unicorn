"""Le stimulus P300, en programme AUTONOME qui publie ses marqueurs.

⚠️ **Ce programme n'ouvre PAS le casque.** C'est ce qui permet de le lancer EN MÊME TEMPS que le
moteur, dans deux terminaux — le même montage que pour le SSVEP :

    python src/core/server.py --mode p300          # terminal 1 : acquiert et décode
    python src/stimulus/p300.py           # terminal 2 : affiche et marque

C'est aussi l'exemple de référence pour qui voudra émettre depuis Unity : le protocole est ici,
et surtout l'endroit exact où prendre l'horodatage.

Protocole publié (figé, cf. docs/SPEC.md) — deux formes de marqueurs, sur le flux
`MARKER_STREAM_DEFAULT` (core/config.py), type "Markers", 1 voie "string", cadence irrégulière :

    {"mode": "p300", "event": "flash", "target": 3}    # une cible s'allume (target : 0-based)
    {"mode": "p300", "event": "round_end"}              # la manche est finie, place à la décision

Une MANCHE = chaque cible flashée `reps` fois, dans un ordre mélangé à chaque répétition (aucune
cible ne doit être prévisible), puis le `round_end`, puis une **PAUSE** (`P300_PAUSE_MANCHE_S`)
pendant laquelle rien ne clignote et l'écran dit de choisir sa cible.

`--calibrer` joue le MÊME protocole, avec trois marqueurs de plus autour :

    {"mode": "p300", "event": "calib_start", "trials": 576}   # la séance s'ouvre, voici ses époques
    {"mode": "p300", "event": "cue", "target": 3}             # la cible DÉSIGNÉE de cette manche
    {"mode": "p300", "event": "calib_end"}                    # la séance est finie -> le moteur entraîne

Une manche de calibration est une manche NORMALE, précédée d'un `cue` : mêmes flashs, même ordre
mélangé, même `round_end`. Le `cue` est la seule chose que le décodage ne donne jamais au moteur —
la VÉRITÉ-TERRAIN, c'est-à-dire la cible que l'écran vient de désigner au sujet. Il part APRÈS le
flip qui la montre, exactement comme les flashs, et pour la même raison.

⚠️ **Une séance interrompue (ESC, `--seconds`) ne publie PAS de `calib_end`.** C'est voulu : le
moteur n'entraînera donc rien, et le dira. Une séance tronquée qui produirait quand même un modèle
donnerait une entrée que RIEN ne distingue d'un modèle complet dans la liste de la console.

⚠️ Cette pause n'est pas du confort. Sans elle, la frontière entre deux manches est visuellement
identique à un intervalle entre deux flashs (~83 ms) : dès la deuxième sélection, les époques
contiennent la transition du regard d'une cible vers la suivante, et le moteur publie quand même
une cible plausible. Les deux implémentations du même protocole validées au casque ont cet écran
(`research/p300_calibrate.py` et le mode P300 de `research/app.py`) ; l'émetteur était le seul à
l'avoir perdu. Elle a une SECONDE conséquence, côté moteur : le discriminant par ÉCART entre deux
flashs — celui qui fermerait complètement la contamination entre manches, cf. le rapport du lot 2
§4(a) — ne peut rien détecter tant qu'il n'y a aucune frontière temporelle à détecter. Cette pause
est donc ce qui rend ce garde-fou possible.

Lancer :
    python src/stimulus/p300.py                  # plein écran, ESC pour quitter
    python src/stimulus/p300.py --windowed       # fenêtre 1000x700 (dev)
    python src/stimulus/p300.py --reps 8         # répétitions par manche (défaut P300_REPS)
    python src/stimulus/p300.py --targets 6      # nombre de cibles (défaut P300_N_TARGETS)
    python src/stimulus/p300.py --refresh 60     # forcer le refresh (sinon auto-mesuré)
    python src/stimulus/p300.py --seconds 20     # auto-quit après 20 s
    python src/stimulus/p300.py --calibrer       # séance de CALIBRATION (la console la lance)
    python src/stimulus/p300.py --calibrer --rounds 12   # manches de calibration (défaut P300_CAL_ROUNDS)
    python src/stimulus/p300.py --smoke          # test sans écran (CI) : séquence ET rendu

⚠️ `--reps` et `--targets` ne sont pas libres : le moteur code `P300_N_TARGETS` en dur et APPLIQUE
`P300_REPS` comme plafond par cible (il abandonne toute manche qui le dépasse). Une valeur hors
contrat est donc REFUSÉE au lancement, en nommant la constante — cf. `_valide_reglages`.
"""

import argparse
import json
import math
import os
import random
import statistics
import sys
import time
from collections import Counter

# Permet `from config import ...` que le module soit lancé via `python src/stimulus/p300.py`
# ou importé comme `src.p300_stimulus`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (MARKER_STREAM_DEFAULT, P300_CAL_ROUNDS, P300_EPOCH_S,  # noqa: E402
                         P300_FLASH_OFF_FR, P300_FLASH_ON_FR, P300_MIN_REPS, P300_N_TARGETS,
                         P300_PAUSE_MANCHE_S, P300_REPS, SSVEP_WARMUP_S, p300_targets,
                         use_utf8_console)
from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, local_clock  # noqa: E402

# --- Réglages d'affichage ---------------------------------------------------

BG = (0, 0, 0)          # fond noir -> contraste ON/OFF maximal (meilleur P300)
ON_COLOR = (255, 255, 255)
OUTLINE = (55, 55, 70)  # contour statique : garde le repère spatial quand la cible est OFF
FIX_DOT = (200, 40, 40)  # point de fixation CHROMATIQUE : ancre le regard sans amputer le
#                          contraste (même choix que research/ui.py, cf. draw_ring)
LABEL = (120, 120, 140)
HUD = (70, 90, 70)
PAUSE = (110, 150, 110)  # l'écran d'entre-manches : vert éteint, ne concurrence pas les flashs
CUE = (60, 130, 255)     # le cercle de DÉSIGNATION, en calibration : « c'est CELLE-CI qu'on fixe »
#                          Un CERCLE et pas un disque plein : un disque, c'est un flash, et le
#                          sujet à qui l'on demande de compter les éclairs le compterait.
CUE_MARGE_PX = 8         # de combien le cercle de désignation déborde la cible
CUE_EPAISSEUR_PX = 4

# ⚠️ La durée de la pause entre deux manches est LUE dans `core/config.py`, jamais recopiée ici.
# Elle y a été hissée le 2026-09-07 parce que DEUX programmes en dépendent et qu'aucun ne peut
# importer l'autre : cette fenêtre la JOUE, et `core/modes/p300_calib.py` s'en sert pour ESTIMER la
# durée d'une séance de calibration — le chiffre que la console affiche AVANT de commencer. Deux
# copies dériveraient, et l'écran annoncerait alors une durée que la fenêtre ne tient pas. C'est la
# leçon de la piste ErrP, qui était écrite deux fois. `--smoke` vérifie qu'aucune copie locale
# n'est revenue.

# Ce que le moteur JETTE avant d'enregistrer pour de bon, EN CALIBRATION : sa chauffe (l'offset DC
# de l'Unicorn dérive après ouverture de session — 10⁵ µV en rampe, mesuré le 2026-07-27). Valeur
# lue dans `core/modes/marker_calib.py` (`warmup_s = SSVEP_WARMUP_S`), pas recopiée.
#
# ⚠️ Ce n'est PAS du confort, et `wait_for_consumers` ne le remplace pas : il répond « oui » dès
# que l'inlet du moteur est résolu, c'est-à-dire au DÉBUT de la chauffe. Flasher pendant ce
# temps-là offre au moteur des époques qu'il compte et jette (`marqueurs_chauffe`) — une séance
# plus COURTE que ce que l'écran annonce, sans qu'un étudiant puisse le voir autrement qu'en
# lisant le terminal. Le `calib_start`, lui, est bien retenu pendant la chauffe : c'est ce qui
# permet de l'annoncer tout de suite et d'occuper l'attente avec la consigne.
ATTENTE_MOTEUR_S = SSVEP_WARMUP_S

# Rayon du point de fixation, en PIXELS et non proportionnel — la MÊME valeur que
# `research/ui.py:FIX_DOT_R`, celle sous laquelle les données d'entraînement ont été
# enregistrées. Il valait 3 ici, soit 2,25× la surface : un stimulus qui n'est pas celui du
# modèle, pour une constante recopiée de travers.
FIX_DOT_R = 2


# --- Séquence de marqueurs (fonctions PURES, testables sans écran ni pygame) --

def blocs_melanges(n_targets, reps, rng):
    """`reps` blocs, chacun une permutation des `n_targets` cibles — AUCUNE cible deux fois de
    suite, y compris à la JONCTION entre deux blocs.

    Mélanger À CHAQUE répétition (pas une fois pour toute la manche) : sinon le même ordre se
    répéterait `reps` fois d'affilée, un motif prévisible qui nuirait au caractère "oddball" du
    protocole (littérature P300 classique : l'ordre de présentation doit être imprévisible).

    ⚠️ **La contrainte de jonction est l'invariant, et il vaut pour LES TROIS endroits qui
    présentent ce stimulus.** Un shuffle indépendant à chaque répétition laisse ~1/n_targets de
    chances que la dernière cible d'un bloc soit aussi la première du suivant (aux réglages par
    défaut, 6 cibles × 8 répétitions : ~72 % de chances qu'AU MOINS UNE des 7 jonctions répète —
    mesuré à 72,0 % sur 20 000 manches, 1,17 répétition par manche). Le P300 est un paradigme
    ODDBALL : un flash immédiatement répété introduit un effet de réfractarité non maîtrisé (la
    réponse évoquée au 2e flash consécutif sur la même cible est amoindrie, qu'elle soit ou non
    la cible attendue) qui abîme l'onde qu'on cherche justement à mesurer.

    Cette fonction est donc le SEUL endroit où ce mélange s'écrit. La calibration
    (`research/p300_calibrate.py`) et le P300 live de `research/app.py` l'appellent aussi : ils
    remélangeaient chacun de leur côté, sans garde de jonction — un invariant affirmé et testé
    ici, violé aux deux endroits qui produisent réellement les modèles. Une contrainte tenue à un
    seul endroit sur trois n'est pas une contrainte.

    Sans effet si `n_targets <= 1` : il n'y a alors aucune autre cible à placer en tête.
    """
    n_targets, reps = int(n_targets), int(reps)
    blocs = []
    derniere_cible = None
    for _ in range(reps):
        ordre = list(range(n_targets))
        rng.shuffle(ordre)
        # Rejoue le mélange tant que la jonction avec le bloc précédent répéterait une cible.
        # `n_targets > 1` évite une boucle infinie quand il n'y a justement aucune alternative.
        while n_targets > 1 and derniere_cible is not None and ordre[0] == derniere_cible:
            rng.shuffle(ordre)
        blocs.append(ordre)
        derniere_cible = ordre[-1]
    return blocs


def build_markers(n_targets, reps, rng):
    """La séquence COMPLÈTE des marqueurs d'UNE manche : les blocs de `blocs_melanges`, puis un
    `round_end`.

    Fonction PURE — aucun pygame, aucun réseau. `run()` rejoue exactement cette même séquence en
    y attachant le rendu et l'horodatage réels : aucune divergence possible entre ce que
    `--smoke` vérifie et ce qui part vraiment sur le réseau.
    """
    marqueurs = []
    for bloc in blocs_melanges(n_targets, reps, rng):
        marqueurs.extend({"mode": "p300", "event": "flash", "target": t} for t in bloc)
    marqueurs.append({"mode": "p300", "event": "round_end"})
    return marqueurs


# --- Réglages : ce que le MOTEUR accepte, pas ce qui est syntaxiquement valide ---

def valide_reglages(reps, targets):
    """(ok, raison). Refuse ce que le moteur ne saura pas décoder — au lancement, pas en séance.

    Documenter ne suffisait pas : `--targets 4` tournait sans un mot, les indices 0-3 étant dans
    la plage attendue, et la probabilité oddball passait de 1/6 à 1/4 — le modèle décodait alors
    avec les probabilités de quelqu'un d'autre, en publiant des sélections parfaitement
    plausibles. `--targets 0` levait un `IndexError` nu, `--targets 2` produisait une séquence
    strictement alternée donc 100 % prévisible (le contraire d'un oddball), et le smoke disait OK.

    `--reps` est devenu tout aussi contraignant depuis que le moteur applique `P300_REPS` comme
    PLAFOND PAR CIBLE : au-delà, il abandonne la manche — bruyamment, mais TOUTES les manches. Et
    en dessous de `P300_MIN_REPS`, il refuse de décider (plancher de manche). Un émetteur lancé à
    `--reps 12` ne produirait donc plus une seule sélection.
    """
    if int(targets) != P300_N_TARGETS:
        return False, (f"--targets {targets} : le mode P300 du moteur code {P300_N_TARGETS} "
                       f"cibles EN DUR (core/config.py, P300_N_TARGETS). Avec un autre nombre, "
                       f"la probabilité oddball change et le modèle décode avec les "
                       f"probabilités de quelqu'un d'autre — sans jamais rien signaler.")
    if not (P300_MIN_REPS <= int(reps) <= P300_REPS):
        return False, (f"--reps {reps} : le moteur exige entre {P300_MIN_REPS} et {P300_REPS} "
                       f"répétitions par cible (core/config.py, P300_MIN_REPS / P300_REPS). "
                       f"Au-dessus, il ABANDONNE chaque manche (plafond par cible appliqué) ; "
                       f"en dessous, il refuse de décider (plancher de manche).")
    return True, ""


# --- Géométrie (cercle, angle 0 = haut, sens horaire — même convention que research/ui.py) -

def target_positions(n_targets, span):
    """Centres (dx, dy) des `n_targets` cibles, relatifs au centre de l'écran.

    Les angles sont LUS dans `p300_targets(n)`, jamais recalculés : la couronne était réécrite
    ici en `2πi/n`, ce qui donne le même résultat pour n=6 mais DIVERGE dès n=3 (`cvep_targets(3)`
    reprend exactement les angles de `COMMANDS`, pas trois tiers de tour). Deux géométries pour
    le même protocole, et l'écran ne montre plus les cibles sur lesquelles le modèle a été
    entraîné. Les ratios (0,31 et 0,075) sont ceux de `research/ui.py:ring_spots`, pour la même
    raison.
    """
    dist = span * 0.31
    return [(dist * math.sin(c["angle"]),
             -dist * math.cos(c["angle"]))          # y écran vers le bas
            for c in p300_targets(int(n_targets))]


# --- Boucle principale ------------------------------------------------------

def run(windowed=False, refresh=None, reps=P300_REPS, targets=P300_N_TARGETS, seconds=None,
        smoke=False, stream_name=MARKER_STREAM_DEFAULT, attente_consommateur_s=5.0,
        journal=None, calibrer=False, rounds=P300_CAL_ROUNDS, attente_moteur_s=None,
        sonde_ecran=None):
    """La boucle du stimulus — décodage (défaut) ou CALIBRATION (`calibrer=True`).

    ⚠️ Les deux modes partagent la MÊME boucle et la MÊME séquence de flashs (`build_markers`).
    Une manche de calibration est une manche normale, précédée d'un `cue` : écrire une seconde
    boucle « pour la calibration » rouvrirait exactement la duplication que ce chantier a passé son
    temps à supprimer ailleurs (la piste ErrP était écrite deux fois, avec un test de 500 pas pour
    garder les copies d'accord).

    `journal`, s'il est fourni, reçoit `(marqueur, horodatage)` pour CHAQUE marqueur réellement
    poussé — c'est ce qui permet à `--smoke` de vérifier le rendu réel et pas seulement la séquence
    théorique.

    `sonde_ecran(surface, spots, rayon_cue)` n'existe QUE pour `--smoke`, et c'est le garde-fou le
    plus sérieux de ce fichier avec l'horodatage au flip : elle est appelée juste après le `flip`
    sur lequel un `cue` vient de partir, et donne donc à voir l'écran EXACT que ce marqueur
    prétend décrire. Le test y LIT la cible désignée dans les pixels, au lieu de croire le
    compteur de l'émetteur — qui, lui, ne peut que se donner raison.

    `attente_moteur_s` : combien de temps occuper avant la première manche d'une calibration, le
    temps que le moteur finisse sa chauffe (cf. `ATTENTE_MOTEUR_S`). `None` = la valeur par défaut ;
    `0` pour un test.
    """
    if smoke:
        return _smoke(reps, targets)

    ok, raison = valide_reglages(reps, targets)
    if not ok:
        print(f"[p300-stim] REFUSÉ — {raison}")
        return False

    import pygame  # import tardif : le module s'importe même sans pygame installé

    from stimulus.refresh import measure_refresh  # même mesure que le SSVEP, pas réinventée

    pygame.init()
    pygame.font.init()

    if windowed:
        size = (1000, 700)
        flags = pygame.SCALED
    else:
        disp_info = pygame.display.Info()
        size = (disp_info.current_w, disp_info.current_h)
        flags = pygame.FULLSCREEN | pygame.SCALED

    # vsync=1 : les flashs sont cadencés par le balayage écran, comme le SSVEP.
    try:
        win = pygame.display.set_mode(size, flags, vsync=1)
    except (TypeError, pygame.error):
        win = pygame.display.set_mode(size, flags)
    pygame.display.set_caption("P300 stimulus — EEG_API_Unicorn")
    pygame.mouse.set_visible(False)

    if refresh is None:
        refresh = measure_refresh(pygame, win)
    on_fr, off_fr = P300_FLASH_ON_FR, P300_FLASH_OFF_FR
    soa_theorique_ms = (on_fr + off_fr) / refresh * 1000.0

    # Le flux de marqueurs : nom et type FIGÉS (contrat public, core/config.py). `source_id`
    # unique par PID -> deux instances de ce stimulus ne se confondent jamais l'une l'autre.
    info = StreamInfo(stream_name, "Markers", 1, IRREGULAR_RATE, "string",
                      f"p300-stim-{os.getpid()}")
    outlet = StreamOutlet(info)

    print(f"[p300-stim] refresh écran   : {refresh:.0f} Hz")
    print(f"[p300-stim] {targets} cibles, {reps} répétitions/manche, "
          f"SOA={on_fr}+{off_fr} frames = {soa_theorique_ms:.0f} ms EN THÉORIE "
          f"(le mesuré s'affiche à chaque fin de manche)")
    print(f"[p300-stim] marqueurs publiés sur « {stream_name} »")

    # ⚠️ Attendre le moteur AVANT le premier flash. Sans ça, un étudiant qui a oublié de lancer
    # le moteur — ou qui a tapé un autre nom de flux — regarde un écran parfaitement fonctionnel
    # pendant des minutes, sans le moindre signe que personne n'écoute. LSL sait répondre à la
    # question (`wait_for_consumers`/`have_consumers`), on la pose. L'attente est BORNÉE et on
    # démarre quand même après : enregistrer sans moteur reste légitime, ce qu'on refuse c'est
    # de le faire sans le savoir.
    if attente_consommateur_s > 0 and not outlet.wait_for_consumers(attente_consommateur_s):
        print(f"[p300-stim] ⚠️ PERSONNE n'écoute « {stream_name} » après "
              f"{attente_consommateur_s:g} s. Le moteur est-il lancé "
              f"(`python src/core/server.py --mode p300`) ? Je flashe quand même — l'indicateur "
              f"en haut de l'écran dit qui écoute, en direct.")
    elif attente_consommateur_s > 0:
        print("[p300-stim] le moteur écoute — on peut commencer.")

    w, h = size
    cx, cy = w / 2, h / 2
    span = min(w, h)
    rad = span * 0.075
    # ENTIER, et calculé une seule fois : c'est le rayon exact auquel le cercle de désignation est
    # tracé, donc celui auquel `--smoke` va le RELIRE dans les pixels. Recalculé de son côté, le
    # test chercherait à un rayon voisin et ne trouverait rien — un test qui échoue pour la
    # mauvaise raison est pire qu'un test absent.
    rayon_cue = int(rad) + CUE_MARGE_PX
    spots = [(int(cx + dx), int(cy + dy)) for dx, dy in target_positions(targets, span)]

    font = pygame.font.SysFont("consolas", max(14, int(span * 0.022)))
    hud_font = pygame.font.SysFont("consolas", max(12, int(span * 0.016)))
    big_font = pygame.font.SysFont("consolas", max(20, int(span * 0.045)))

    clock = pygame.time.Clock()
    rng = random.Random()
    running = True
    round_num = 0
    # La cible DÉSIGNÉE de la manche en cours (calibration), ou None en décodage. Elle reste
    # cerclée PENDANT les flashs : c'est ce que faisait l'écran validé au casque
    # (`research/p300_calibrate._flash_targets`, `cue=cue_name`), et c'est nécessaire — un sujet
    # qui perd le repère de sa cible au premier flash compte les éclairs de la mauvaise.
    cue_courant = None
    flashs_manche = 0            # ce qui a déjà été envoyé dans la manche EN COURS
    soa_mesures = []             # intervalles RÉELS entre deux onsets de flash consécutifs
    dernier_onset = None
    t_start = time.perf_counter()

    def emet(m):
        """Pousse un marqueur et l'horodate. UN SEUL endroit prend `local_clock()`."""
        ts = local_clock()
        outlet.push_sample([json.dumps(m)], timestamp=ts)
        if journal is not None:
            journal.append((m, ts))
        return ts

    def poll():
        """Événements + la limite `--seconds`. Les DEUX ici : la limite n'était regardée qu'en
        fin de manche, donc `--seconds 20` pouvait tourner 25 s. Un étudiant qui règle une durée
        veut qu'elle soit tenue, pas arrondie à la manche supérieure."""
        nonlocal running
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False
        if seconds is not None and (time.perf_counter() - t_start) >= seconds:
            running = False

    def dessine_cibles(allumee=-1):
        """La couronne : contour permanent, cible ALLUMÉE s'il y en a une, cible DÉSIGNÉE cerclée
        s'il y en a une, point de fixation, numéro.

        UN SEUL dessin pour les deux écrans du programme — les flashs et les attentes. Ils avaient
        chacun leur boucle, et elles avaient déjà divergé : l'écran d'attente ne dessinait pas la
        cible allumée (normal) mais il aurait tout aussi bien pu oublier le point de fixation, et
        le sujet aurait alors changé de repère de regard entre les deux écrans sans que rien ne le
        signale.
        """
        win.fill(BG)
        for i, (x, y) in enumerate(spots):
            pygame.draw.circle(win, OUTLINE, (x, y), rad, 2)   # repère quand la cible est OFF
            if i == allumee:
                pygame.draw.circle(win, ON_COLOR, (x, y), rad)
            if i == cue_courant:
                pygame.draw.circle(win, CUE, (x, y), rayon_cue, CUE_EPAISSEUR_PX)
            pygame.draw.circle(win, FIX_DOT, (x, y), FIX_DOT_R)   # ancre le regard
            lab = font.render(str(i), True, LABEL)
            win.blit(lab, lab.get_rect(center=(x, y + int(rad * 1.9))))

    def draw(allumee):
        """`allumee` : indice de la cible ON, ou -1 si aucune (phase OFF / entre deux flashs)."""
        dessine_cibles(allumee)
        # L'indicateur d'écoute, en direct : c'est la seule chose de cet écran qui distingue
        # « ça marche » de « ça a l'air de marcher ».
        ecoute = "moteur À L'ÉCOUTE" if outlet.have_consumers() else "PERSONNE n'écoute"
        soa = f"{statistics.median(soa_mesures) * 1000:.0f} ms" if soa_mesures else "—"
        hud = hud_font.render(f"manche {round_num}  |  {refresh:.0f} fps  |  SOA mesuré {soa}  "
                              f"|  {ecoute}  |  ESC = quitter", True, HUD)
        win.blit(hud, (12, 10))

    def ecran_statique(secondes, titre, note=None, marqueur_cue=False):
        """Un écran où RIEN ne clignote. Les TROIS attentes du programme passent par ici :
        l'entre-manches du décodage, la consigne d'une manche de calibration, et l'attente de la
        chauffe du moteur au lancement d'une calibration.

        ⚠️ Cette pause n'est pas du confort. Sans elle, la frontière entre deux manches est
        visuellement identique à un intervalle entre deux flashs (~150 ms) : l'étudiant n'a aucun
        instant pour déplacer son regard, dès la 2e sélection les époques contiennent la
        transition, et le moteur publie quand même une cible plausible. Les deux implémentations
        validées au casque ont cet écran.

        ⚠️ **`marqueur_cue` : le `cue` part APRÈS le premier `flip`**, c'est-à-dire une fois que la
        cible désignée est RÉELLEMENT à l'écran. Publié avant, il annonce la consigne une frame
        trop tôt et le moteur étiquette la première époque de la manche sur la consigne
        PRÉCÉDENTE. Rien ne lève d'exception : le modèle apprend simplement une cible fausse par
        manche. C'est le même geste, et la même raison, que l'horodatage des flashs plus bas.
        """
        t0 = time.perf_counter()
        premiere = True
        while running and (time.perf_counter() - t0) < secondes:
            poll()
            dessine_cibles()
            grand = big_font.render(titre, True, PAUSE)
            win.blit(grand, grand.get_rect(center=(int(cx), int(cy))))
            restant = max(0.0, secondes - (time.perf_counter() - t0))
            sous = hud_font.render(note or f"la manche suivante commence dans {restant:.1f} s",
                                   True, HUD)
            win.blit(sous, sous.get_rect(center=(int(cx), int(cy + span * 0.06))))
            pygame.display.flip()
            if premiere:
                premiere = False
                if marqueur_cue and cue_courant is not None:
                    emet({"mode": "p300", "event": "cue", "target": int(cue_courant)})
                    if sonde_ecran is not None:
                        # L'écran EXACT sur lequel ce `cue` vient de partir. Cf. la docstring de
                        # `run` : c'est ce qui permet à `--smoke` de LIRE la cible désignée au lieu
                        # de croire le compteur de cet émetteur.
                        sonde_ecran(win, list(spots), rayon_cue)
            clock.tick(int(refresh) + 5)

    attente_moteur_s = ATTENTE_MOTEUR_S if attente_moteur_s is None else float(attente_moteur_s)
    rounds = int(rounds)
    seance_complete = False

    if calibrer:
        # ⚠️ `trials` compte des ÉPOQUES, pas des manches : c'est l'unité que le moteur incrémente
        # à chaque flash enregistré (`core/modes/marker_calib.py::total`). Annoncer des manches ne
        # casserait rien mais afficherait un avancement faux et ferait mal régler la détection de
        # fenêtre morte — la séance serait déclarée « complète » dès la première manche.
        epoques_annoncees = rounds * int(targets) * int(reps)
        emet({"mode": "p300", "event": "calib_start", "trials": epoques_annoncees})
        print(f"[p300-stim] CALIBRATION : {rounds} manches × {targets} cibles × {reps} rép "
              f"= {epoques_annoncees} époques annoncées")
        if attente_consommateur_s > 0 and not outlet.have_consumers():
            print(f"[p300-stim] ⚠️ et PERSONNE n'écoute : cette séance ne produira AUCUN modèle. "
                  f"Lance la calibration depuis la console, ou ferme cette fenêtre.")
        if attente_moteur_s > 0:
            print(f"[p300-stim] le moteur JETTE tout pendant sa chauffe (~{attente_moteur_s:g} s, "
                  f"cf. core/modes/marker_calib.py) : consigne à l'écran en attendant, la "
                  f"première manche démarre après.")
            ecran_statique(attente_moteur_s, "Calibration P300",
                           note="le casque se stabilise — installe-toi, ne bouge plus")

    while running:
        if calibrer and round_num >= rounds:
            seance_complete = True
            break
        round_num += 1
        flashs_manche = 0
        if calibrer:
            # Chaque cible désignée à tour de rôle : à 12 manches et 6 cibles, chacune est cuée
            # deux fois. Un tirage au hasard laisserait des cibles sans aucune manche, et la
            # sélection en leave-one-round-out n'aurait alors rien à retrouver pour elles.
            cue_courant = (round_num - 1) % int(targets)
            ecran_statique(P300_PAUSE_MANCHE_S,
                           f"FIXE la cible {cue_courant} et COMPTE ses éclairs",
                           note=f"manche {round_num}/{rounds} — ne bouge pas, cligne peu",
                           marqueur_cue=True)
        for m in build_markers(targets, reps, rng):
            if not running:
                break
            if m["event"] == "flash":
                cible = m["target"]
                for f in range(on_fr):
                    poll()
                    if not running:
                        break
                    draw(cible)
                    pygame.display.flip()
                    # ⚠️ L'HORODATAGE SE PREND ICI, juste après le basculement de frame — pas
                    # avant de dessiner, pas au moment de décider quelle cible flasher. Une
                    # charge utile parfaite envoyée 40 ms trop tôt décale TOUTES les époques
                    # d'une frame, et le décodeur corrèle alors contre une réponse évoquée qui
                    # n'a pas encore eu lieu.
                    if f == 0:
                        onset = emet(m)
                        flashs_manche += 1
                        if dernier_onset is not None:
                            soa_mesures.append(onset - dernier_onset)
                        dernier_onset = onset
                    clock.tick(int(refresh) + 5)
                if not running:
                    break
                for _ in range(off_fr):               # gap éteint avant le flash suivant
                    poll()
                    if not running:
                        break
                    draw(-1)
                    pygame.display.flip()
                    clock.tick(int(refresh) + 5)
            else:  # round_end : pas de rendu associé, juste le marqueur de fin de manche
                emet(m)
                mesure = (f"{statistics.median(soa_mesures) * 1000:.0f} ms mesuré"
                          if soa_mesures else "SOA non mesurable")
                print(f"[p300-stim] manche {round_num} : {flashs_manche} flashs envoyés, "
                      f"round_end ({mesure})")
                flashs_manche = 0
                dernier_onset = None      # la pause n'est pas un SOA : elle ne doit pas y entrer
                if not calibrer:
                    # En calibration, la pause est jouée EN TÊTE de la manche suivante, avec la
                    # consigne : la jouer aussi ici en ferait deux d'affilée (5 s d'écran fixe) et
                    # rien ne le dirait, sinon une séance deux fois plus longue qu'annoncée.
                    ecran_statique(P300_PAUSE_MANCHE_S, "choisis ta cible et fixe-la")

        # ⚠️ Sortir en pleine manche (ESC, fenêtre fermée, `--seconds` atteint) laissait le
        # moteur avec des flashs orphelins : il attend 10 s puis ABANDONNE la manche. Émettre le
        # `round_end` lui dit tout de suite que c'est fini — il refusera de décider (trop peu de
        # flashs) et le DIRA, au lieu de rester muet dix secondes.
        if flashs_manche:
            emet({"mode": "p300", "event": "round_end"})
            print(f"[p300-stim] interrompu en pleine manche {round_num} : round_end envoyé pour "
                  f"les {flashs_manche} flashs déjà partis (le moteur refusera de décider, et le "
                  f"dira)")

    if calibrer and seance_complete:
        # ⚠️ Laisser la DERNIÈRE époque se remplir avant d'annoncer la fin. Le moteur ne libère un
        # marqueur qu'une fois son post-stimulus écoulé (`markers_murs(post_s=…)`) : `calib_end`
        # publié dans la foulée du dernier flash arriverait bien après lui, mais l'écran, lui,
        # serait déjà noir et le sujet aurait bougé. Même geste que le `settle` de l'ancienne
        # calibration (`research/p300_calibrate._collect`).
        cue_courant = None
        ecran_statique(P300_EPOCH_S + 0.15, "Calibration terminée",
                       note="ne bouge plus — la dernière époque finit de s'enregistrer")
        emet({"mode": "p300", "event": "calib_end"})
        print(f"[p300-stim] calibration terminée : {rounds} manches, « calib_end » envoyé — "
              f"le moteur entraîne, le résultat s'affiche dans la console.")
    elif calibrer:
        # ⚠️ AUCUN `calib_end` : la séance est incomplète, et le moteur ne doit RIEN entraîner
        # dessus. Un modèle appris sur trois manches sur douze serait indiscernable d'un modèle
        # complet dans la liste de la console, et donnerait ensuite des scores plausibles et faux.
        print(f"[p300-stim] ⚠️ calibration INTERROMPUE à la manche {round_num}/{rounds} : AUCUN "
              f"« calib_end » envoyé, donc aucun modèle ne sera entraîné. Le moteur attend — "
              f"clique « Abandonner » dans la console, puis recommence.")

    pygame.quit()
    return True


# --- --smoke : la séquence, PUIS la boucle réelle sur un écran factice ------

def _cible_designee_a_l_ecran(surface, spots, rayon_cue):
    """LA cible que l'écran DÉSIGNE, lue dans les PIXELS. -1 si aucune.

    ⚠️ C'est le point de tout ce garde-fou : on ne demande pas à l'émetteur quelle cible il croit
    afficher — il ne peut que se donner raison. On regarde l'image. C'est la même famille de test
    que la sonde de `stimulus/cvep.py`, qui relit la phase du code dans les pixels plutôt que dans
    le compteur qui l'a produite.

    On balaie les quatre rayons de l'anneau de désignation (haut, bas, gauche, droite) sur son
    épaisseur : `pygame.draw.circle` avec une largeur dessine une couronne vers l'INTÉRIEUR du
    rayon donné, et l'antialiasing n'entre pas en jeu (`draw.circle` ne lisse pas), donc la
    couleur s'y retrouve EXACTE. Chercher un pixel exact plutôt qu'« un pixel bleuâtre » est
    voulu : une couleur approchée matcherait aussi le point de fixation ou un futur décor.

    ⚠️ **Ce que cette sonde n'attrape PAS, et il faut le savoir avant de s'y fier** : remonter le
    `emet` AU-DESSUS du `flip`. Sous le pilote logiciel à tampon UNIQUE (`SDL_VIDEODRIVER=dummy`,
    celui du smoke), la surface porte déjà l'image dessinée avant même le `flip` — la sonde lirait
    donc la même chose des deux côtés. Elle prouve QUELLE cible est à l'écran, jamais QUAND elle y
    est arrivée. Mesuré sur les deux mutations qu'elle attrape, en revanche : annoncer une cible
    que l'écran ne désigne pas, ou en désigner une qu'on n'annonce pas — les deux rougissent.
    Même limite, même cause et même formulation que `stimulus/cvep.py::_etat_ecran`.
    """
    largeur, hauteur = surface.get_width(), surface.get_height()
    for i, (x, y) in enumerate(spots):
        for d in range(CUE_EPAISSEUR_PX + 2):
            r = rayon_cue - d
            for px, py in ((x + r, y), (x - r, y), (x, y + r), (x, y - r)):
                if 0 <= px < largeur and 0 <= py < hauteur:
                    if tuple(surface.get_at((int(px), int(py))))[:3] == CUE:
                        return i
    return -1


def _smoke(reps, n_targets):
    """Trois moitiés — la deuxième est celle qui manquait, la troisième est la calibration.

    **A. La séquence** (`build_markers`, fonction pure) : sa forme, ses comptes, ses jonctions.

    **B. `run()` POUR DE VRAI**, sur `SDL_VIDEODRIVER=dummy` — le patron de `research/app.py` et
    de `ssvep_stimulus.py`. Le `--smoke` retournait avant même l'import de pygame : les ~90
    lignes qui contiennent **le geste flip→horodatage que ce fichier existe pour enseigner**
    n'avaient AUCUNE couverture. Un `push_sample` remonté au-dessus du `flip`, une pause
    supprimée, un `round_end` jamais émis en sortie — rien de tout ça n'échouait.

    **C. `--calibrer`**, sur le même écran factice : la forme exacte de la séance, et surtout que
    la cible annoncée par chaque `cue` est celle que l'écran a RÉELLEMENT désignée — lue dans les
    pixels (`_cible_designee_a_l_ecran`). C'est la même faute que d'horodater avant le flip, sur
    un autre axe : le marqueur est parfait, il décrit juste autre chose que ce qu'on voit.

    Ce qui n'est PAS revérifié ici : le transport LSL (mûrissement, horodatage, offset d'horloge)
    est déjà prouvé par `core/markers.py`.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    rng = random.Random(0)
    marqueurs = build_markers(n_targets, reps, rng)
    flashs = [m for m in marqueurs if m["event"] == "flash"]

    chk(len(flashs) == reps * n_targets,
        f"{reps} rép × {n_targets} cibles = {reps * n_targets} flashs attendus "
        f"({len(flashs)} obtenus)")
    compte = Counter(m["target"] for m in flashs)
    chk(all(compte.get(t) == reps for t in range(n_targets)),
        f"chaque cible vue exactement {reps} fois ({dict(sorted(compte.items()))})")
    chk(marqueurs[-1] == {"mode": "p300", "event": "round_end"},
        f"la manche se termine par un round_end ({marqueurs[-1]})")
    chk(all(m.get("mode") == "p300" for m in marqueurs),
        "tous les marqueurs portent mode=p300")
    chk(all(0 <= m["target"] < n_targets for m in flashs),
        "toutes les cibles flashées sont dans [0, n_targets[ — le contrat public")
    # Aucune cible ne flashe deux fois DE SUITE, y compris aux jonctions entre répétitions (cf.
    # la docstring de build_markers : un paradigme oddball ne doit jamais présenter deux fois le
    # même stimulus d'affilée, sous peine de réfractarité non maîtrisée sur l'onde mesurée).
    # Vide de sens si une seule cible existe (rien d'autre à placer) : la garde le dit explicitement
    # plutôt que d'échouer sur une contrainte mathématiquement impossible à tenir.
    consecutifs = sum(1 for a, b in zip(flashs, flashs[1:]) if a["target"] == b["target"])
    chk(n_targets <= 1 or consecutifs == 0,
        f"aucune cible ne flashe deux fois de suite, jonctions comprises "
        f"({consecutifs} répétition(s) immédiate(s))")

    # --- les réglages que le MOTEUR refuserait sont refusés ICI, au lancement -----
    # `--targets 4` tournait sans un mot (indices 0-3 dans la plage, donc aucune garde ne se
    # déclenchait) et changeait la probabilité oddball de 1/6 à 1/4. `--reps 12` fait désormais
    # ABANDONNER toutes les manches, le moteur appliquant P300_REPS comme plafond par cible.
    chk(valide_reglages(P300_REPS, P300_N_TARGETS)[0],
        "les valeurs par défaut sont, elles, acceptées")
    for mauvais_t in (0, 2, 4, P300_N_TARGETS + 1):
        accepte, raison = valide_reglages(P300_REPS, mauvais_t)
        chk(not accepte and "P300_N_TARGETS" in raison,
            f"--targets {mauvais_t} est refusé en nommant la constante du moteur ({raison[:60]}…)")
    for mauvais_r in (0, P300_MIN_REPS - 1, P300_REPS + 1, 12):
        accepte, raison = valide_reglages(mauvais_r, P300_N_TARGETS)
        chk(not accepte and "P300_REPS" in raison,
            f"--reps {mauvais_r} est refusé en nommant la constante du moteur ({raison[:60]}…)")

    # --- B. run() POUR DE VRAI, sur un écran factice -----------------------------
    # Un flux au nom DISTINCT du contrat public : les noms de flux sont partagés par toutes les
    # instances du projet, et un smoke ne doit jamais pouvoir répondre à la place d'un vrai
    # émetteur. `attente_consommateur_s=0` parce que personne n'écoute, par construction.
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    journal = []
    fait = run(windowed=True, refresh=60.0, reps=P300_MIN_REPS, targets=P300_N_TARGETS,
               seconds=6.0, stream_name=MARKER_STREAM_DEFAULT + "_smoke",
               attente_consommateur_s=0.0, journal=journal)
    chk(fait, "run() va au bout sur un écran factice (SDL_VIDEODRIVER=dummy)")

    evenements = [m["event"] for m, _ts in journal]
    chk(evenements.count("flash") >= P300_MIN_REPS * n_targets,
        f"...et il a RÉELLEMENT poussé les flashs d'au moins une manche complète "
        f"({evenements.count('flash')})")
    chk("round_end" in evenements,
        f"...et au moins un round_end ({evenements.count('round_end')})")

    horodatages = [ts for _m, ts in journal]
    chk(all(b > a for a, b in zip(horodatages, horodatages[1:])),
        "les horodatages avancent strictement — un flip par flash, un horodatage par flip")

    # ⚠️ LE garde-fou du critique 3.2 : il DOIT y avoir une pause entre un `round_end` et le
    # premier flash de la manche suivante. Sans elle, la frontière de manche est indiscernable
    # d'un intervalle inter-flash (~83 ms), l'étudiant n'a aucun instant pour changer de cible,
    # et le discriminant par ÉCART côté moteur (lot 2, §4a) ne pourrait rien détecter.
    pauses = [b - a for (ma, a), (mb, b) in zip(journal, journal[1:])
              if ma["event"] == "round_end" and mb["event"] == "flash"]
    chk(pauses and min(pauses) >= P300_PAUSE_MANCHE_S * 0.9,
        f"une PAUSE sépare deux manches, elle ne se confond pas avec un intervalle inter-flash "
        f"({[round(p, 2) for p in pauses]} s pour {P300_PAUSE_MANCHE_S:g} s demandées)")

    inter_flashs = [b - a for (ma, a), (mb, b) in zip(journal, journal[1:])
                    if ma["event"] == "flash" and mb["event"] == "flash"]
    chk(inter_flashs and max(inter_flashs) < P300_PAUSE_MANCHE_S / 2,
        f"...et les flashs D'UNE MÊME manche, eux, restent serrés "
        f"(SOA max {max(inter_flashs) * 1000:.0f} ms)")

    # Interrompu par `--seconds` en pleine manche : le moteur doit l'apprendre tout de suite,
    # pas au bout de ses 10 s d'abandon.
    chk(journal[-1][0]["event"] == "round_end",
        f"quoi qu'il arrive, le dernier marqueur envoyé est un round_end — jamais des flashs "
        f"orphelins ({journal[-1][0]})")

    # La pause est LUE dans `core/config.py`, pas recopiée ici. Vérifié sur le TEXTE SOURCE, comme
    # les invariants P300 de `research/app.py` : comparer les VALEURS ne prouverait rien, une
    # copie locale à 2,5 s étant égale à la constante à 2,5 s le jour où on l'écrit — et
    # divergeant en silence au premier changement. Ce qui se casse alors n'est pas ce fichier :
    # c'est `core/modes/p300_calib.py::duree_protocole_s`, donc la durée que la console ANNONCE à
    # l'étudiant avant qu'il ne s'assoie.
    import inspect
    import re

    source = inspect.getsource(sys.modules[__name__])
    copies = re.findall(r"^\s*[A-Z_]*PAUSE[A-Z_]*\s*=\s*[0-9]", source, re.M)
    chk(not copies and "P300_PAUSE_MANCHE_S" in source,
        f"la pause entre manches vient de core/config.py, aucune copie locale n'est revenue "
        f"({copies or 'aucune copie'})")

    # --- C. --calibrer : la séance, et la cible RÉELLEMENT désignée ---------------
    # `attente_moteur_s=0` : la vraie séance occupe les 15 s de chauffe du moteur, un test n'a pas
    # à les subir. `rounds=3` suffit à exercer les trois marqueurs de la séance et leur ordre.
    journal_c, designees = [], []
    fait_c = run(windowed=True, refresh=60.0, reps=P300_MIN_REPS, targets=P300_N_TARGETS,
                 calibrer=True, rounds=3, attente_moteur_s=0.0,
                 stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
                 journal=journal_c,
                 sonde_ecran=lambda surface, spots, r: designees.append(
                     _cible_designee_a_l_ecran(surface, spots, r)))
    chk(fait_c, "run(calibrer=True) va au bout sur un écran factice")

    evenements_c = [m["event"] for m, _ts in journal_c]
    attendu = ["calib_start"]
    for _ in range(3):
        attendu += ["cue"] + ["flash"] * (P300_MIN_REPS * P300_N_TARGETS) + ["round_end"]
    attendu += ["calib_end"]
    chk(evenements_c == attendu,
        f"la séance s'ouvre par calib_start, se ferme par calib_end, et chaque `cue` PRÉCÈDE les "
        f"flashs de sa manche ({evenements_c[:3]}… {evenements_c[-3:]}, "
        f"{len(evenements_c)} marqueurs pour {len(attendu)} attendus)")

    cues = [m for m, _ts in journal_c if m["event"] == "cue"]
    chk(len(cues) == 3 and all("target" in c for c in cues),
        f"un `cue` par manche, et chacun porte sa cible ({[c.get('target') for c in cues]})")

    # ⚠️ LE test de cette moitié. La vérité-terrain doit être celle qui a été AFFICHÉE, pas celle
    # que le tirage avait décidée : un `cue` juste, publié sur un écran qui en montre un autre,
    # entraîne le modèle sur une cible fausse par manche — sans lever la moindre exception.
    chk(designees and [c["target"] for c in cues] == designees,
        f"la cible annoncée par `cue` est celle que l'écran a RÉELLEMENT désignée, lue dans les "
        f"PIXELS ({[c['target'] for c in cues]} annoncées contre {designees} affichées)")

    depart = journal_c[0][0]
    chk(depart.get("trials") == evenements_c.count("flash"),
        f"`calib_start` annonce des ÉPOQUES, dans l'unité que le moteur compte — pas des manches : "
        f"une autre unité afficherait un avancement faux et ferait déclarer la séance complète dès "
        f"la première manche ({depart.get('trials')} annoncées, "
        f"{evenements_c.count('flash')} flashs poussés)")

    # Une séance INTERROMPUE ne publie PAS de calib_end : le moteur ne doit rien entraîner sur une
    # séance tronquée. `seconds` tombe pendant le premier écran de consigne.
    journal_i = []
    run(windowed=True, refresh=60.0, reps=P300_MIN_REPS, targets=P300_N_TARGETS,
        calibrer=True, rounds=3, attente_moteur_s=0.0, seconds=P300_PAUSE_MANCHE_S / 2,
        stream_name=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
        journal=journal_i)
    evenements_i = [m["event"] for m, _ts in journal_i]
    chk("calib_start" in evenements_i and "calib_end" not in evenements_i,
        f"une séance INTERROMPUE ne publie AUCUN calib_end — un modèle appris sur trois manches "
        f"sur douze serait indiscernable d'un modèle complet dans la liste ({evenements_i})")

    # ⚠️ Appelée SANS `ok and …` : `and` court-circuite, donc le bout-à-bout aurait été SAUTÉ dès
    # qu'une assertion précédente échoue — c'est-à-dire précisément quand on en a besoin. Attrapé
    # par mutation (renommer l'événement `cue` faisait rougir la moitié C et taisait la D).
    # `chk` met à jour `ok` par `nonlocal` : la valeur de retour n'a rien à faire ici.
    _smoke_bout_en_bout(chk, journal_c, designees)

    print(f"[p300-stim] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _smoke_bout_en_bout(chk, journal, designees):
    """LES MARQUEURS DE CETTE FENÊTRE, donnés à la calibration du MOTEUR. Le seul test qui les
    fait se parler.

    Les deux moitiés de ce chantier se vérifient séparément partout ailleurs : la fenêtre publie
    une séquence (juste au-dessus), et le moteur sait en faire un modèle
    (`python src/core/modes/p300_calib.py`, qui rejoue une séance qu'il FABRIQUE lui-même). Rien
    ne prouvait qu'elles parlent de la même chose. Un désaccord de protocole — un événement
    renommé, la cible sur une autre clé, un `round_end` oublié — ne lève RIEN : le moteur
    enregistre simplement moins d'époques, ou les étiquette toutes « non-cible », et la
    calibration produit un modèle plausible qui décodera du bruit.

    ⚠️ Ce test vit ICI et il ne peut pas vivre ailleurs : `core` n'a pas le droit d'importer
    `stimulus` (frontière vérifiée par `python src/core/server.py --smoke`), `stimulus -> core`
    est autorisé. C'est donc à l'émetteur de prouver que le moteur le comprend.

    Le tampon EEG est à ZÉRO, exprès : on ne juge pas ici un décodage, seulement le PROTOCOLE —
    combien d'époques, sous quelles étiquettes, sous quelle manche. Et on n'entraîne pas (aucun
    `tick` après `calib_end`), donc rien n'est écrit sur le disque.
    """
    import tempfile

    import numpy as np

    from core.modes.p300 import SPEC as SPEC_P300
    from core.modes.p300_calib import P300Calibration

    class _FausseAcq:
        fs = 250.0

    class _MoteurFactice:
        """Le strict nécessaire pour la calibration : un tampon EEG horodaté, une file vide."""

        def __init__(self, recent, recent_ts):
            self.acq = _FausseAcq()
            self.recent, self.recent_ts = recent, recent_ts

        def markers_murs(self, mode_id, post_s):
            return []      # les marqueurs sont donnés à la main, un par un, par `encaisser`

    t_debut, t_fin = journal[0][1], journal[-1][1]
    recent_ts = np.arange(t_debut - 2.0, t_fin + 2.0, 1.0 / _FausseAcq.fs)
    moteur = _MoteurFactice(np.zeros((len(recent_ts), 8)), recent_ts)

    with tempfile.TemporaryDirectory(prefix="p300_stim_smoke_") as dossier:
        rt = P300Calibration(SPEC_P300, {}, moteur, dossier=dossier)
        rt.tick(moteur, t_debut)                    # démarre la chauffe
        for m, ts_m in journal:
            rt.encaisser(moteur, ts_m, m)
            if m["event"] == "calib_start":
                # La chauffe s'écoule d'un coup : c'est l'horloge de l'APPELANT, pas celle des
                # marqueurs, et c'est justement ce qui permet de la traverser sans attendre.
                rt.tick(moteur, t_debut + rt.warmup_s + 0.01)

        flashs = sum(1 for m, _t in journal if m["event"] == "flash")
        chk(rt.essai == flashs and len(rt._enregistre) == flashs,
            f"le moteur enregistre UNE époque par flash de cette fenêtre "
            f"({rt.essai} pour {flashs} flashs poussés)")
        chk(rt.total() == flashs,
            f"...et le `trials` annoncé par la fenêtre est bien ce nombre-là : c'est sur lui que "
            f"la console affiche l'avancement et que le moteur juge une fenêtre morte "
            f"({rt.total()} annoncés)")
        chk(rt._refus == 0,
            f"aucun marqueur de cette fenêtre n'est refusé par le moteur ({rt._refus} refus)")

        etiquettes = [lab for _e, lab in rt._enregistre]
        manches = sorted({lab.manche for lab in etiquettes})
        chk(manches == list(range(len(designees))),
            f"chaque manche de l'écran est une manche du moteur ({manches} pour "
            f"{len(designees)} manches jouées)")
        chk([next(lab.attendue for lab in etiquettes if lab.manche == m) for m in manches]
            == designees,
            f"...et la vérité-terrain que le moteur retient est la cible que l'écran a DÉSIGNÉE, "
            f"manche par manche ({designees})")
        cibles = sum(1 for lab in etiquettes if lab.est_cible)
        chk(cibles == len(designees) * P300_MIN_REPS,
            f"une époque « cible » par répétition et par manche, le reste en « non-cible » — "
            f"c'est l'oddball, et un protocole désaccordé le déséquilibrerait sans un mot "
            f"({cibles} cibles sur {len(etiquettes)} époques)")
        chk(rt.phase == "entrainement" and rt.resultat is None,
            f"`calib_end` a bien clos la séance côté moteur, sans qu'on lui demande d'entraîner "
            f"ici ({rt.phase})")


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Stimulus P300 (EEG_API_Unicorn).")
    p.add_argument("--windowed", action="store_true", help="fenêtre au lieu du plein écran")
    p.add_argument("--refresh", type=float, default=None, help="forcer le refresh (Hz)")
    p.add_argument("--reps", type=int, default=P300_REPS,
                   help=f"répétitions par manche (défaut {P300_REPS} — le moteur exige entre "
                        f"{P300_MIN_REPS} et {P300_REPS}, plafond APPLIQUÉ par cible)")
    p.add_argument("--targets", type=int, default=P300_N_TARGETS,
                   help=f"nombre de cibles (défaut {P300_N_TARGETS} — le mode P300 du moteur "
                        f"n'accepte QUE cette valeur, cf. core/config.py P300_N_TARGETS)")
    p.add_argument("--seconds", type=float, default=None, help="auto-quit après N secondes")
    p.add_argument("--calibrer", action="store_true",
                   help="séance de CALIBRATION : mêmes manches, plus calib_start / cue / "
                        "calib_end. C'est le moteur qui entraîne — la console lance cette fenêtre "
                        "elle-même, la lancer à la main n'a de sens que pour la mettre au point")
    p.add_argument("--rounds", type=int, default=P300_CAL_ROUNDS,
                   help=f"manches de calibration (défaut {P300_CAL_ROUNDS}, chaque cible cuée "
                        f"{P300_CAL_ROUNDS // P300_N_TARGETS}× à {P300_N_TARGETS} cibles). Sans "
                        f"--calibrer, ce réglage ne sert à rien : le décodage enchaîne les manches "
                        f"jusqu'à ESC")
    p.add_argument("--smoke", action="store_true",
                   help="test headless (CI) : la séquence ET la boucle réelle, sur écran factice")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    ok = run(windowed=args.windowed, refresh=args.refresh, reps=args.reps, targets=args.targets,
             seconds=args.seconds, smoke=args.smoke, calibrer=args.calibrer, rounds=args.rounds)
    # Un réglage refusé (`valide_reglages`) doit sortir en 1 même hors smoke : lancé depuis un
    # script, « ça n'a rien affiché » et « ça a refusé » ne doivent pas se ressembler.
    sys.exit(0 if ok else 1)
