"""Stimulus SSVEP — les flèches clignotantes, et le run GUIDÉ qui permet de le MESURER.

⚠️ **TROIS flèches, pas quatre.** Ce fichier a annoncé « 4 flèches » jusqu'au 2026-09-09, dans sa
docstring, dans son `--help` et dans le briefing de la mesure. `choose_frequencies` en rend TROIS
(AVANT, GAUCHE, DROITE) à 60, 75, 120 et 144 Hz — vérifié aux quatre —, et le rendu ne dessine que
ce plan. La quatrième est un vestige du banc d'essai robot, retiré depuis. Le nombre vient donc du
PLAN et de nulle part ailleurs : quelqu'un qui s'assoit 3,6 minutes devant cet écran ne doit pas y
chercher une flèche qui n'existe pas.

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
  rafraîchissement écran : à 60 Hz, une flèche « ON k frames / OFF k frames » clignote
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

Lancer :
    python src/stimulus/ssvep.py                 # plein écran, ESC pour quitter
    python src/stimulus/ssvep.py --windowed      # fenêtre 1000x700 (dev)
    python src/stimulus/ssvep.py --refresh 60    # forcer le refresh (sinon auto-mesuré)
    python src/stimulus/ssvep.py --seconds 20    # auto-quit après 20 s
    python src/stimulus/ssvep.py --guide         # le run GUIDÉ (la console le lance elle-même)
    python src/stimulus/ssvep.py --guide --trials 6   # plus court (6 essais par cible)
    python src/stimulus/ssvep.py --guide --seed 5     # rejouer le MÊME ordre d'essais
    python src/stimulus/ssvep.py --smoke         # test sans écran (CI), n'affiche rien
"""

import argparse
import json
import math
import os
import sys
import time

# Permet `from core.config import ...` que le module soit lancé via `python src/stimulus/ssvep.py`
# ou importé comme `stimulus.ssvep`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402

from core.config import (MARKER_STREAM_DEFAULT,  # noqa: E402
                         SSVEP_GUIDE_CUE_S, SSVEP_GUIDE_FIX_S, SSVEP_GUIDE_GAP_S,
                         SSVEP_GUIDE_REPOS_S, SSVEP_GUIDE_TRIALS_PER_TARGET, SSVEP_WARMUP_S,
                         choose_frequencies, use_utf8_console)
from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, local_clock  # noqa: E402

# --- Réglages d'affichage (les fréquences/commandes viennent de config.py) --

BG = (0, 0, 0)          # fond noir -> contraste ON/OFF maximal (meilleur SSVEP)
ON_COLOR = (255, 255, 255)
OUTLINE = (55, 55, 70)  # contour statique : garde le repère spatial quand la flèche est OFF
LABEL = (120, 120, 140)
HUD = (70, 90, 70)

# Le mode guidé, en plus.
FG = (225, 225, 235)
DIM = (110, 110, 130)
# ⚠️ La couleur de DÉSIGNATION, et elle n'est utilisée NULLE PART AILLEURS dans ce fichier — ni
# pour un titre, ni pour un sous-titre, ni pour un décor. C'est ce qui permet à `--smoke` de LIRE
# dans les pixels quelle cible l'écran désigne (cf. `_cible_designee_a_l_ecran`) : une seconde
# utilisation de ce bleu déplacerait le centroïde et le test chercherait la mauvaise flèche.
CUE = (60, 130, 255)
CUE_EPAISSEUR_PX = 8    # épaisseur du liseré de désignation, en pixels

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


# --- Géométrie des flèches ------------------------------------------------

def _up_arrow_points(size):
    """Points d'une flèche pointant vers le haut, centrée sur (0,0), coords écran (y bas)."""
    h = size            # demi-hauteur totale
    head_h = size * 0.9  # hauteur de la pointe
    head_w = size * 0.75  # demi-largeur de la pointe
    shaft_w = size * 0.32  # demi-largeur de la tige
    top = -h
    return [
        (0.0, top),                 # pointe
        (head_w, top + head_h),     # base droite de la pointe
        (shaft_w, top + head_h),    # haut tige droite
        (shaft_w, h),               # bas tige droite
        (-shaft_w, h),              # bas tige gauche
        (-shaft_w, top + head_h),   # haut tige gauche
        (-head_w, top + head_h),    # base gauche de la pointe
    ]


_DIR_ANGLE = {"up": 0.0, "right": math.pi / 2, "down": math.pi, "left": -math.pi / 2}


def arrow_polygon(cx, cy, size, direction):
    """Points absolus (liste de (x,y)) d'une flèche orientée, centrée en (cx, cy)."""
    ang = _DIR_ANGLE[direction]
    c, s = math.cos(ang), math.sin(ang)
    pts = []
    for x, y in _up_arrow_points(size):
        rx = x * c - y * s
        ry = x * s + y * c
        pts.append((cx + rx, cy + ry))
    return pts


# --- Mesure du refresh écran ----------------------------------------------

# `measure_refresh` a DÉMÉNAGÉ dans `stimulus/refresh.py` le 2026-09-07, avec les trois fenêtres
# qui l'importaient. Réexporté sous son nom d'origine : `archive/ui.py` et les écrans de
# `archive/` l'importent encore d'ici.
from stimulus.refresh import measure_refresh  # noqa: E402,F401
from stimulus.garde import sous_garde_data  # noqa: E402


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
        per_target=SSVEP_GUIDE_TRIALS_PER_TARGET, seed=None,
        stream=MARKER_STREAM_DEFAULT, attente_consommateur_s=5.0, attente_moteur_s=None,
        journal=None, sonde_ecran=None,
        cue_s=None, fix_s=None, gap_s=None, repos_s=None):
    """La boucle du stimulus — décodage libre (défaut) ou run GUIDÉ (`guide=True`).

    ⚠️ Les deux modes partagent le MÊME rendu du clignotement et le MÊME compteur de frames.
    Écrire une seconde boucle « pour le mode guidé » rouvrirait la duplication que ce dépôt a passé
    son temps à supprimer ailleurs — et surtout, le clignotement du guidé cesserait d'être
    exactement celui du décodage, donc le taux mesuré ne dirait plus rien du taux réel.

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

    pygame.init()
    pygame.font.init()

    if windowed or smoke:
        size = (1000, 700)
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
    plan = choose_frequencies(refresh)

    print(f"[ssvep-stim] refresh ecran   : {refresh:.0f} Hz")
    print(f"[ssvep-stim] taille fenetre  : {size[0]}x{size[1]}")
    for c in plan:
        print(f"[ssvep-stim]   {c['name']:<8} {c['dir']:<5} desire={c['desired_hz']:>5.2f} Hz "
              f"-> {c['actual_hz']:>5.2f} Hz  ({c['frames_per_cycle']} frames/cycle)")

    w, h = size
    cx, cy = w / 2, h / 2
    span = min(w, h)
    dist = span * 0.30   # éloignement des flèches par rapport au centre
    asize = span * 0.13  # demi-taille d'une flèche
    pos = {
        "up":    (cx, cy - dist),
        "down":  (cx, cy + dist),
        "left":  (cx - dist, cy),
        "right": (cx + dist, cy),
    }
    polys = {c["dir"]: arrow_polygon(*pos[c["dir"]], asize, c["dir"]) for c in plan}
    # Les positions des cibles DANS L'ORDRE DU PLAN — c'est-à-dire dans l'ordre des indices que
    # les marqueurs `cue` publient et que le moteur compare à ses fréquences. Le dictionnaire
    # `pos`, lui, est indexé par direction : s'en servir pour retrouver « la cible 1 » supposerait
    # que l'ordre des directions est celui du plan, ce qui n'est vrai que par accident.
    positions = [pos[c["dir"]] for c in plan]

    font = pygame.font.SysFont("consolas", max(14, int(span * 0.022)))
    hud_font = pygame.font.SysFont("consolas", max(12, int(span * 0.016)))
    big_font = pygame.font.SysFont("consolas", max(20, int(span * 0.040)))

    clock = pygame.time.Clock()
    fps = int(refresh) + 5
    frame = 0
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
        flèches (0,13 contre 0,12 de l'empan). Un stimulus qui n'est pas celui du décodage rend le
        taux mesuré inutilisable pour prédire le décodage.
        """
        win.fill(BG)
        for c in plan:
            d = c["dir"]
            pygame.draw.polygon(win, OUTLINE, polys[d], 2)  # repère statique
            if is_on(frame, c["frames_per_cycle"]):
                pygame.draw.polygon(win, ON_COLOR, polys[d])  # phase ON
            # étiquette statique (n'interfère pas avec le clignotement)
            label = font.render(f"{c['name']}  {c['actual_hz']:.2f} Hz", True, LABEL)
            px, py = pos[d]
            win.blit(label, label.get_rect(center=(px, py + asize * 1.35)))
        if designee is not None:
            pygame.draw.polygon(win, CUE, polys[plan[designee]["dir"]], CUE_EPAISSEUR_PX)
        if croix:
            pygame.draw.line(win, DIM, (cx - 14, cy), (cx + 14, cy), 3)
            pygame.draw.line(win, DIM, (cx, cy - 14), (cx, cy + 14), 3)
        if titre:
            s = big_font.render(titre, True, FG)
            win.blit(s, s.get_rect(center=(int(cx), int(h * 0.10))))
        if sous:
            s = hud_font.render(sous, True, DIM)
            win.blit(s, s.get_rect(center=(int(cx), int(h * 0.10) + big_font.get_height())))

    def phase(duree, marqueur=None, sonde=False, **kw):
        """Affiche pendant `duree` secondes en gardant le clignotement verrouillé à la frame.

        ⚠️ **`marqueur` part APRÈS le premier `flip`**, c'est-à-dire une fois que l'écran qu'il
        décrit est RÉELLEMENT affiché. Publié avant, il annonce la phase une frame trop tôt : rien
        ne lève d'exception, le moteur prélève simplement sa fenêtre décalée. C'est le même geste,
        et la même raison, que l'horodatage des flashs de `stimulus/p300.py`.
        """
        nonlocal frame, fps_acc, fps_n, fps_show
        premiere = True
        t_end = time.perf_counter() + duree
        while running and time.perf_counter() < t_end:
            poll()
            dessine(**kw)
            pygame.display.flip()
            if premiere:
                premiere = False
                if marqueur is not None:
                    emet(marqueur)
                    if sonde and sonde_ecran is not None:
                        sonde_ecran(win, list(positions))
            dt = clock.tick(fps) / 1000.0
            if dt > 0:
                fps_acc += 1.0 / dt
                fps_n += 1
                if fps_n >= 30:
                    fps_show, fps_acc, fps_n = fps_acc / fps_n, 0.0, 0
            frame += 1
        return running

    seance_complete = False
    try:
        if not guide:
            # --- décodage libre : les flèches du plan clignotent, rien d'autre ----------------
            while running:
                poll()
                dessine()
                hud = hud_font.render(f"{fps_show:.0f} fps  |  ESC = quitter", True, HUD)
                win.blit(hud, (12, 10))
                pygame.display.flip()
                dt = clock.tick(fps) / 1000.0   # garde-fou si vsync absent
                if dt > 0:
                    fps_acc += 1.0 / dt
                    fps_n += 1
                    if fps_n >= 30:
                        fps_show, fps_acc, fps_n = fps_acc / fps_n, 0.0, 0
                frame += 1
                if smoke and frame >= 30:
                    running = False
        else:
            seance_complete = _guide(
                plan, per_target, seed, phase, emet, refresh,
                cue_s, fix_s, gap_s, repos_s, attente_moteur_s,
                outlet, attente_consommateur_s)
    finally:
        pygame.quit()

    if smoke and not guide:
        print("[ssvep-stim] smoke OK : rendu de 30 frames sans erreur (aucun ecran requis).")
    return True if not guide else seance_complete


def _guide(plan, per_target, seed, phase, emet, refresh,
           cue_s, fix_s, gap_s, repos_s, attente_moteur_s, outlet, attente_consommateur_s):
    """La ligne du temps du run guidé. Rend True si la séance est allée jusqu'au `calib_end`.

    Chauffe -> plancher de repos -> essais entrelacés -> fin. Le clignotement TOURNE du début à la
    fin, plancher de repos COMPRIS : celui-ci doit être mesuré dans les mêmes conditions visuelles
    que les essais, sinon le moteur soustrait un fond qui n'est pas celui du test.
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
                  f"(tuile « Taux d'émission SSVEP ») ? Je clignote quand même.")
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
        if not phase(attente_moteur_s, titre="Le casque se stabilise", croix=True,
                     sous="installe-toi, ne fixe aucune flèche — la mesure commence après"):
            return _interrompu(0, len(ordre))

    if not phase(repos_s, marqueur={"mode": "ssvep", "event": "repos"},
                 titre="REPOS", croix=True,
                 sous="fixe la CROIX centrale, ne suis AUCUNE flèche"):
        return _interrompu(0, len(ordre))

    for i, cible in enumerate(ordre, 1):
        # 1. La consigne : on désigne, le regard se déplace. AUCUN marqueur — cette seconde
        #    contient la saccade, et sa fin de course polluerait la fenêtre du moteur.
        if not phase(cue_s, designee=cible, titre=f"REGARDE : {noms[cible]}",
                     sous=f"essai {i}/{len(ordre)}"):
            return _interrompu(i - 1, len(ordre))
        # 2. La fixation. Le `cue` part ICI, au premier flip : c'est l'instant à partir duquel le
        #    moteur compte `SSVEP_GUIDE_FIX_S` pour prélever la DERNIÈRE fenêtre de la fixation.
        if not phase(fix_s, designee=cible, titre=noms[cible], sous="fixe la flèche entourée",
                     marqueur={"mode": "ssvep", "event": "cue", "target": int(cible),
                               "freq_hz": freqs[cible]},
                     sonde=True):
            return _interrompu(i - 1, len(ordre))
        # 3. Le retour à la croix, pour que deux essais consécutifs ne se recouvrent pas.
        if not phase(gap_s, titre="—", croix=True, sous="repose les yeux sur la croix"):
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

def _cible_designee_a_l_ecran(surface, positions):
    """LA cible que l'écran DÉSIGNE, lue dans les PIXELS. -1 si aucune.

    ⚠️ C'est le point de ce garde-fou : on ne demande pas à l'émetteur quelle cible il croit
    désigner — il ne peut que se donner raison. On regarde l'image. Même famille de test que la
    sonde de `stimulus/p300.py` (qui relit la cible cerclée) et celle de `stimulus/cvep.py` (qui
    relit la phase du code).

    On cherche la couleur `CUE` EXACTE — `pygame.draw.polygon` ne lisse pas, donc elle se retrouve
    telle quelle — et on prend le centroïde des pixels trouvés, puis la position la PLUS PROCHE.
    Un liseré polygonal n'a pas de point d'échantillonnage évident comme un cercle ; le centroïde
    en a un, et il est robuste au fait qu'une partie du liseré soit recouverte par la flèche
    allumée.

    ⚠️ **Ce que cette sonde n'attrape PAS, et il faut le savoir avant de s'y fier** : remonter le
    `emet` AU-DESSUS du `flip`. Sous le pilote logiciel à tampon UNIQUE (`SDL_VIDEODRIVER=dummy`,
    celui du smoke), la surface porte déjà l'image dessinée avant même le `flip` — la sonde lirait
    donc la même chose des deux côtés. Elle prouve QUELLE cible est à l'écran, jamais QUAND elle y
    est arrivée. Même limite, même cause et même formulation que `stimulus/p300.py`.
    """
    import pygame

    arr = pygame.surfarray.array3d(surface)          # (largeur, hauteur, 3)
    masque = ((arr[:, :, 0] == CUE[0]) & (arr[:, :, 1] == CUE[1]) & (arr[:, :, 2] == CUE[2]))
    trouves = np.argwhere(masque)
    if not len(trouves):
        return -1
    centre = trouves.mean(axis=0)                    # (x, y) — array3d est indexé (x, y)
    distances = [(centre[0] - px) ** 2 + (centre[1] - py) ** 2 for px, py in positions]
    return int(np.argmin(distances))


def _smoke():
    """Deux moitiés : le rendu libre, puis LE RUN GUIDÉ, sur `SDL_VIDEODRIVER=dummy`.

    La seconde est celle qui compte. Elle rejoue une séance entière et vérifie les trois choses
    qu'un protocole de mesure ne peut pas se permettre de perdre : la séance s'ouvre et se ferme
    comme les trois fenêtres sœurs, la cible ANNONCÉE est celle que l'écran a réellement DÉSIGNÉE
    (lue dans les pixels), et l'ordre des essais est ENTRELACÉ et équilibré.
    """
    from collections import Counter

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # --- A. le rendu libre, comme avant le déménagement ---------------------------
    chk(run(smoke=True, refresh=60.0),
        "le décodage libre rend 30 frames sans erreur (aucun écran requis)")

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
        f"la cible annoncée par `cue` est celle que l'écran a RÉELLEMENT DÉSIGNÉE, lue dans les "
        f"PIXELS ({[c['target'] for c in cues]} annoncées contre {designees} affichées)")

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

    print(f"[ssvep-stim] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


# Les durées du smoke : courtes, parce qu'on teste la LIGNE DU TEMPS et pas la physiologie. Elles
# ne portent PAS les noms des constantes du protocole (`_SMOKE_` en préfixe) — le contrôle E
# ci-dessus refuse toute réécriture locale de `FIX_S` & co., et ce refus doit rester lisible.
_SMOKE_CUE_S, _SMOKE_FIX_S, _SMOKE_GAP_S, _SMOKE_REPOS_S = 0.10, 0.20, 0.08, 0.15


def _rejouer_guide(per_target, seed, seconds=None):
    """Joue une séance guidée entière sur un écran factice. Rend (journal, cibles AFFICHÉES)."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    journal, designees = [], []
    run(windowed=True, refresh=60.0, guide=True, per_target=per_target, seed=seed,
        seconds=seconds, stream=MARKER_STREAM_DEFAULT + "_smoke", attente_consommateur_s=0.0,
        attente_moteur_s=0.0, cue_s=_SMOKE_CUE_S, fix_s=_SMOKE_FIX_S, gap_s=_SMOKE_GAP_S,
        repos_s=_SMOKE_REPOS_S, journal=journal,
        sonde_ecran=lambda surface, positions: designees.append(
            _cible_designee_a_l_ecran(surface, positions)))
    return journal, designees


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Stimulus SSVEP (EEG_API_Unicorn).")
    p.add_argument("--windowed", action="store_true", help="fenetre au lieu du plein ecran")
    p.add_argument("--refresh", type=float, default=None, help="forcer le refresh (Hz)")
    p.add_argument("--seconds", type=float, default=None, help="auto-quit apres N secondes")
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
    p.add_argument("--smoke", action="store_true", help="test headless (SDL dummy), n'affiche rien")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    if args.smoke:
        sys.exit(0 if sous_garde_data(_smoke) else 1)
    fait = run(windowed=args.windowed, refresh=args.refresh, seconds=args.seconds,
               guide=args.guide, per_target=args.trials, seed=args.seed)
    # Une séance guidée INTERROMPUE sort en 1 : lancée depuis la console, « elle s'est fermée » et
    # « elle est allée au bout » ne doivent pas se ressembler.
    sys.exit(0 if fait else 1)
