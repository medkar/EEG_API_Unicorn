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
cible ne doit être prévisible), puis le `round_end`.

Lancer :
    python src/research/p300_stimulus.py                  # plein écran, ESC pour quitter
    python src/research/p300_stimulus.py --windowed       # fenêtre 1000x700 (dev)
    python src/research/p300_stimulus.py --reps 8         # répétitions par manche (défaut P300_REPS)
    python src/research/p300_stimulus.py --targets 6      # nombre de cibles (défaut P300_N_TARGETS)
    python src/research/p300_stimulus.py --refresh 60     # forcer le refresh (sinon auto-mesuré)
    python src/research/p300_stimulus.py --seconds 20     # auto-quit après 20 s
    python src/research/p300_stimulus.py --smoke          # test sans écran (CI), vérifie la séquence
"""

import argparse
import json
import math
import os
import random
import sys
import time
from collections import Counter

# Permet `from config import ...` que le module soit lancé via `python src/research/p300_stimulus.py`
# ou importé comme `src.p300_stimulus`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (MARKER_STREAM_DEFAULT, P300_FLASH_OFF_FR, P300_FLASH_ON_FR,  # noqa: E402
                         P300_N_TARGETS, P300_REPS, use_utf8_console)
from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, local_clock  # noqa: E402

# --- Réglages d'affichage ---------------------------------------------------

BG = (0, 0, 0)          # fond noir -> contraste ON/OFF maximal (meilleur P300)
ON_COLOR = (255, 255, 255)
OUTLINE = (55, 55, 70)  # contour statique : garde le repère spatial quand la cible est OFF
FIX_DOT = (200, 40, 40)  # point de fixation CHROMATIQUE : ancre le regard sans amputer le
#                          contraste (même choix que research/ui.py, cf. draw_ring)
LABEL = (120, 120, 140)
HUD = (70, 90, 70)


# --- Séquence de marqueurs (fonction PURE, testable sans écran ni pygame) --

def build_markers(n_targets, reps, rng):
    """La séquence COMPLÈTE des marqueurs d'UNE manche : `reps` répétitions de l'ordre mélangé
    des `n_targets` cibles, puis un `round_end`.

    Mélanger À CHAQUE répétition (pas une fois pour toute la manche) : sinon le même ordre se
    répéterait `reps` fois d'affilée, un motif prévisible qui nuirait au caractère "oddball" du
    protocole (littérature P300 classique : l'ordre de présentation doit être imprévisible).

    Fonction PURE — aucun pygame, aucun réseau — donc testable directement par `--smoke` sans le
    moindre écran. `run()` rejoue exactement cette même séquence en y attachant le rendu et
    l'horodatage réels : aucune divergence possible entre ce que `--smoke` vérifie et ce qui part
    vraiment sur le réseau.
    """
    marqueurs = []
    for _ in range(int(reps)):
        ordre = list(range(int(n_targets)))
        rng.shuffle(ordre)
        marqueurs.extend({"mode": "p300", "event": "flash", "target": t} for t in ordre)
    marqueurs.append({"mode": "p300", "event": "round_end"})
    return marqueurs


# --- Géométrie (cercle, angle 0 = haut, sens horaire — même convention que research/ui.py) -

def target_positions(n_targets, span):
    """Centres (dx, dy) des `n_targets` cibles, relatifs au centre de l'écran, réparties sur un
    cercle de rayon proportionnel à `span` (= min(largeur, hauteur))."""
    dist = span * 0.31
    return [(dist * math.sin(2 * math.pi * i / n_targets),
             -dist * math.cos(2 * math.pi * i / n_targets))  # y écran vers le bas
            for i in range(int(n_targets))]


# --- Boucle principale ------------------------------------------------------

def run(windowed=False, refresh=None, reps=P300_REPS, targets=P300_N_TARGETS, seconds=None,
        smoke=False):
    if smoke:
        return _smoke(reps, targets)

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
    soa_ms = (on_fr + off_fr) / refresh * 1000.0

    # Le flux de marqueurs : nom et type FIGÉS (contrat public, core/config.py). `source_id`
    # unique par PID -> deux instances de ce stimulus ne se confondent jamais l'une l'autre.
    info = StreamInfo(MARKER_STREAM_DEFAULT, "Markers", 1, IRREGULAR_RATE, "string",
                      f"p300-stim-{os.getpid()}")
    outlet = StreamOutlet(info)

    print(f"[p300-stim] refresh écran   : {refresh:.0f} Hz")
    print(f"[p300-stim] {targets} cibles, {reps} répétitions/manche, "
          f"SOA={on_fr}+{off_fr} frames ~= {soa_ms:.0f} ms")
    print(f"[p300-stim] marqueurs publiés sur « {MARKER_STREAM_DEFAULT} »")

    w, h = size
    cx, cy = w / 2, h / 2
    span = min(w, h)
    rad = span * 0.075
    spots = [(int(cx + dx), int(cy + dy)) for dx, dy in target_positions(targets, span)]

    font = pygame.font.SysFont("consolas", max(14, int(span * 0.022)))
    hud_font = pygame.font.SysFont("consolas", max(12, int(span * 0.016)))

    clock = pygame.time.Clock()
    rng = random.Random()
    running = True
    round_num = 0
    t_start = time.perf_counter()

    def poll():
        nonlocal running
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False

    def draw(allumee):
        """`allumee` : indice de la cible ON, ou -1 si aucune (phase OFF / entre deux flashs)."""
        win.fill(BG)
        for i, (x, y) in enumerate(spots):
            pygame.draw.circle(win, OUTLINE, (x, y), rad, 2)   # repère quand la cible est OFF
            if i == allumee:
                pygame.draw.circle(win, ON_COLOR, (x, y), rad)
            pygame.draw.circle(win, FIX_DOT, (x, y), 3)        # ancre le regard
            lab = font.render(str(i), True, LABEL)
            win.blit(lab, lab.get_rect(center=(x, y + int(rad * 1.9))))
        hud = hud_font.render(f"manche {round_num}  |  {refresh:.0f} fps  |  ESC = quitter",
                              True, HUD)
        win.blit(hud, (12, 10))

    while running:
        round_num += 1
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
                        outlet.push_sample([json.dumps(m)], timestamp=local_clock())
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
                outlet.push_sample([json.dumps(m)], timestamp=local_clock())
                print(f"[p300-stim] manche {round_num} : {reps * targets} flashs envoyés, "
                      f"round_end")
        if seconds is not None and (time.perf_counter() - t_start) >= seconds:
            running = False

    pygame.quit()


# --- --smoke : vérifie la séquence SANS écran, aucun pygame.display ici ----

def _smoke(reps, n_targets):
    """Vérifie que la séquence de marqueurs est bien formée — aucune fenêtre, aucun pygame.display
    dans ce chemin : `build_markers` est une fonction pure, ce test l'appelle directement.

    Ce qui n'est PAS revérifié ici : le transport LSL (mûrissement, horodatage, offset d'horloge)
    est déjà prouvé par `core/markers.py` — ce test se concentre sur ce qui est PROPRE à ce
    stimulus, la forme de la séquence qu'il construit.
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

    print(f"[p300-stim] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Stimulus P300 (EEG_API_Unicorn).")
    p.add_argument("--windowed", action="store_true", help="fenêtre au lieu du plein écran")
    p.add_argument("--refresh", type=float, default=None, help="forcer le refresh (Hz)")
    p.add_argument("--reps", type=int, default=P300_REPS,
                   help=f"répétitions par manche (défaut {P300_REPS:g})")
    p.add_argument("--targets", type=int, default=P300_N_TARGETS,
                   help=f"nombre de cibles (défaut {P300_N_TARGETS} — le mode P300 du moteur "
                        f"n'accepte QUE cette valeur, cf. core/config.py P300_N_TARGETS)")
    p.add_argument("--seconds", type=float, default=None, help="auto-quit après N secondes")
    p.add_argument("--smoke", action="store_true",
                   help="test headless (CI) : vérifie la séquence de marqueurs, aucun écran")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    ok = run(windowed=args.windowed, refresh=args.refresh, reps=args.reps, targets=args.targets,
             seconds=args.seconds, smoke=args.smoke)
    if args.smoke:
        sys.exit(0 if ok else 1)
