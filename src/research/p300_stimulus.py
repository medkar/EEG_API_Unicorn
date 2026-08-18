"""Le stimulus P300, en programme AUTONOME qui publie ses marqueurs.

⚠️ **Ce programme n'ouvre PAS le casque.** C'est ce qui permet de le lancer EN MÊME TEMPS que le
moteur, dans deux terminaux — le même montage que pour le SSVEP :

    python src/core/server.py --mode p300          # terminal 1 : acquiert et décode
    python src/research/p300_stimulus.py           # terminal 2 : affiche et marque

C'est aussi l'exemple de référence pour qui voudra émettre depuis Unity : le protocole est ici,
et surtout l'endroit exact où prendre l'horodatage.

Protocole publié (figé, cf. docs/SPEC.md) — deux formes de marqueurs, sur le flux
`MARKER_STREAM_DEFAULT` (core/config.py), type "Markers", 1 voie "string", cadence irrégulière :

    {"mode": "p300", "event": "flash", "target": 3}    # une cible s'allume (target : 0-based)
    {"mode": "p300", "event": "round_end"}              # la manche est finie, place à la décision

Une MANCHE = chaque cible flashée `reps` fois, dans un ordre mélangé à chaque répétition (aucune
cible ne doit être prévisible), puis le `round_end`, puis une **PAUSE** (`PAUSE_ENTRE_MANCHES_S`)
pendant laquelle rien ne clignote et l'écran dit de choisir sa cible.

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
    python src/research/p300_stimulus.py                  # plein écran, ESC pour quitter
    python src/research/p300_stimulus.py --windowed       # fenêtre 1000x700 (dev)
    python src/research/p300_stimulus.py --reps 8         # répétitions par manche (défaut P300_REPS)
    python src/research/p300_stimulus.py --targets 6      # nombre de cibles (défaut P300_N_TARGETS)
    python src/research/p300_stimulus.py --refresh 60     # forcer le refresh (sinon auto-mesuré)
    python src/research/p300_stimulus.py --seconds 20     # auto-quit après 20 s
    python src/research/p300_stimulus.py --smoke          # test sans écran (CI) : séquence ET rendu

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

# Permet `from config import ...` que le module soit lancé via `python src/research/p300_stimulus.py`
# ou importé comme `src.p300_stimulus`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (MARKER_STREAM_DEFAULT, P300_FLASH_OFF_FR, P300_FLASH_ON_FR,  # noqa: E402
                         P300_MIN_REPS, P300_N_TARGETS, P300_REPS, p300_targets,
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

# Durée de la pause entre deux manches. Calée sur les deux écrans validés au casque : 2,2 s
# (`research/app.py`, « choisis ta cible ») et 2,5 s (`research/p300_calibrate.py`). C'est le
# temps qu'il faut pour déplacer le regard ET le stabiliser avant que la manche suivante ne
# commence à découper des époques.
PAUSE_ENTRE_MANCHES_S = 2.5

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
        journal=None):
    """La boucle du stimulus. `journal`, s'il est fourni, reçoit `(marqueur, horodatage)` pour
    CHAQUE marqueur réellement poussé — c'est ce qui permet à `--smoke` de vérifier le rendu réel
    et pas seulement la séquence théorique."""
    if smoke:
        return _smoke(reps, targets)

    ok, raison = valide_reglages(reps, targets)
    if not ok:
        print(f"[p300-stim] REFUSÉ — {raison}")
        return False

    import pygame  # import tardif : le module s'importe même sans pygame installé

    from research.ssvep_stimulus import measure_refresh  # même mesure que le SSVEP, pas réinventée

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
    spots = [(int(cx + dx), int(cy + dy)) for dx, dy in target_positions(targets, span)]

    font = pygame.font.SysFont("consolas", max(14, int(span * 0.022)))
    hud_font = pygame.font.SysFont("consolas", max(12, int(span * 0.016)))
    big_font = pygame.font.SysFont("consolas", max(20, int(span * 0.045)))

    clock = pygame.time.Clock()
    rng = random.Random()
    running = True
    round_num = 0
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

    def draw(allumee):
        """`allumee` : indice de la cible ON, ou -1 si aucune (phase OFF / entre deux flashs)."""
        win.fill(BG)
        for i, (x, y) in enumerate(spots):
            pygame.draw.circle(win, OUTLINE, (x, y), rad, 2)   # repère quand la cible est OFF
            if i == allumee:
                pygame.draw.circle(win, ON_COLOR, (x, y), rad)
            pygame.draw.circle(win, FIX_DOT, (x, y), FIX_DOT_R)   # ancre le regard
            lab = font.render(str(i), True, LABEL)
            win.blit(lab, lab.get_rect(center=(x, y + int(rad * 1.9))))
        # L'indicateur d'écoute, en direct : c'est la seule chose de cet écran qui distingue
        # « ça marche » de « ça a l'air de marcher ».
        ecoute = "moteur À L'ÉCOUTE" if outlet.have_consumers() else "PERSONNE n'écoute"
        soa = f"{statistics.median(soa_mesures) * 1000:.0f} ms" if soa_mesures else "—"
        hud = hud_font.render(f"manche {round_num}  |  {refresh:.0f} fps  |  SOA mesuré {soa}  "
                              f"|  {ecoute}  |  ESC = quitter", True, HUD)
        win.blit(hud, (12, 10))

    def pause_entre_manches():
        """L'écran d'entre-manches : rien ne clignote, et on dit quoi faire.

        ⚠️ Sans lui, la frontière entre deux manches est visuellement identique à un intervalle
        entre deux flashs. L'étudiant à qui la recette demande de « recommencer six fois en
        changeant de cible » n'a alors aucun instant pour déplacer son regard : dès la 2e
        sélection, les époques contiennent la transition — et le moteur publie quand même une
        cible plausible. Les deux implémentations validées au casque ont cet écran.
        """
        t0 = time.perf_counter()
        while running and (time.perf_counter() - t0) < PAUSE_ENTRE_MANCHES_S:
            poll()
            win.fill(BG)
            for i, (x, y) in enumerate(spots):
                pygame.draw.circle(win, OUTLINE, (x, y), rad, 2)
                pygame.draw.circle(win, FIX_DOT, (x, y), FIX_DOT_R)
                lab = font.render(str(i), True, LABEL)
                win.blit(lab, lab.get_rect(center=(x, y + int(rad * 1.9))))
            titre = big_font.render("choisis ta cible et fixe-la", True, PAUSE)
            win.blit(titre, titre.get_rect(center=(int(cx), int(cy))))
            restant = PAUSE_ENTRE_MANCHES_S - (time.perf_counter() - t0)
            sous = hud_font.render(f"la manche suivante commence dans {max(0.0, restant):.1f} s",
                                   True, HUD)
            win.blit(sous, sous.get_rect(center=(int(cx), int(cy + span * 0.06))))
            pygame.display.flip()
            clock.tick(int(refresh) + 5)

    while running:
        round_num += 1
        flashs_manche = 0
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
                pause_entre_manches()

        # ⚠️ Sortir en pleine manche (ESC, fenêtre fermée, `--seconds` atteint) laissait le
        # moteur avec des flashs orphelins : il attend 10 s puis ABANDONNE la manche. Émettre le
        # `round_end` lui dit tout de suite que c'est fini — il refusera de décider (trop peu de
        # flashs) et le DIRA, au lieu de rester muet dix secondes.
        if flashs_manche:
            emet({"mode": "p300", "event": "round_end"})
            print(f"[p300-stim] interrompu en pleine manche {round_num} : round_end envoyé pour "
                  f"les {flashs_manche} flashs déjà partis (le moteur refusera de décider, et le "
                  f"dira)")

    pygame.quit()
    return True


# --- --smoke : la séquence, PUIS la boucle réelle sur un écran factice ------

def _smoke(reps, n_targets):
    """Deux moitiés, et la seconde est celle qui manquait.

    **A. La séquence** (`build_markers`, fonction pure) : sa forme, ses comptes, ses jonctions.

    **B. `run()` POUR DE VRAI**, sur `SDL_VIDEODRIVER=dummy` — le patron de `research/app.py` et
    de `ssvep_stimulus.py`. Le `--smoke` retournait avant même l'import de pygame : les ~90
    lignes qui contiennent **le geste flip→horodatage que ce fichier existe pour enseigner**
    n'avaient AUCUNE couverture. Un `push_sample` remonté au-dessus du `flip`, une pause
    supprimée, un `round_end` jamais émis en sortie — rien de tout ça n'échouait.

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
    chk(pauses and min(pauses) >= PAUSE_ENTRE_MANCHES_S * 0.9,
        f"une PAUSE sépare deux manches, elle ne se confond pas avec un intervalle inter-flash "
        f"({[round(p, 2) for p in pauses]} s pour {PAUSE_ENTRE_MANCHES_S:g} s demandées)")

    inter_flashs = [b - a for (ma, a), (mb, b) in zip(journal, journal[1:])
                    if ma["event"] == "flash" and mb["event"] == "flash"]
    chk(inter_flashs and max(inter_flashs) < PAUSE_ENTRE_MANCHES_S / 2,
        f"...et les flashs D'UNE MÊME manche, eux, restent serrés "
        f"(SOA max {max(inter_flashs) * 1000:.0f} ms)")

    # Interrompu par `--seconds` en pleine manche : le moteur doit l'apprendre tout de suite,
    # pas au bout de ses 10 s d'abandon.
    chk(journal[-1][0]["event"] == "round_end",
        f"quoi qu'il arrive, le dernier marqueur envoyé est un round_end — jamais des flashs "
        f"orphelins ({journal[-1][0]})")

    print(f"[p300-stim] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


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
    p.add_argument("--smoke", action="store_true",
                   help="test headless (CI) : la séquence ET la boucle réelle, sur écran factice")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    ok = run(windowed=args.windowed, refresh=args.refresh, reps=args.reps, targets=args.targets,
             seconds=args.seconds, smoke=args.smoke)
    # Un réglage refusé (`valide_reglages`) doit sortir en 1 même hors smoke : lancé depuis un
    # script, « ça n'a rien affiché » et « ça a refusé » ne doivent pas se ressembler.
    sys.exit(0 if ok else 1)
