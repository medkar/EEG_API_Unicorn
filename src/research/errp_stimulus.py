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
réponse.

La tâche est le curseur-vers-cible (Ferrez & Millán 2008, Chavarriaga 2010), reprise TELLE QUELLE
du démonstrateur (`research/app.py`, mode ErrP) et de la calibration (`research/errp_calibrate.py`)
— va les lire, ce protocole ne s'invente pas ici, il se reproduit : un point sur une piste de
`ERRP_TRACK_CELLS` cases part du CENTRE vers une cible tirée à l'une des DEUX EXTRÉMITÉS (50/50 —
le sens du mouvement reste décorrélé de l'étiquette erreur/correct, cf. `nouvelle_cible`) ; à chaque
pas il avance d'une case, sauf dans ~`ERRP_ERROR_RATE` des pas où la machine se trompe
DÉLIBÉRÉMENT et l'éloigne (rebond aux bords, cf. `decide_pas`). Le feedback (la nouvelle position)
reste affiché `ERRP_FEEDBACK_S` = 1 s — la fenêtre pendant laquelle l'utilisateur perçoit l'ERP
d'erreur si le pas s'est éloigné. Cible atteinte, ou `ERRP_MAX_RUN_STEPS` dépassés -> nouvelle
course, sans aucune pause : contrairement au P300, il n'y a pas de « manche » à protéger d'une
contamination (`core/modes/errp.py` : chaque feedback se décode SEUL, cf. sa docstring).

Le geste critique, identique au P300 :

    pygame.display.flip()
    # L'HORODATAGE SE PREND ICI, juste après que le feedback est À L'ÉCRAN. 40 ms d'avance
    # décalent toutes les époques de deux frames, et le décodeur moyenne une réponse qui n'a pas
    # encore eu lieu. Rien ne lève d'erreur ; les scores sortent, et ils sont du bruit.
    outlet.push_sample([json.dumps({"mode": "errp", "event": "feedback"})],
                       timestamp=local_clock())

⚠️ **Pas de `valide_reglages`, à la différence de `p300_stimulus.py` — et ce n'est pas un oubli.**
Le mode ErrP du moteur ne lit QUE l'horodatage du marqueur `feedback` : aucun nombre de cases codé
en dur, aucune manche à plafonner, rien qui s'accumule sur plusieurs pas. `--cells` et
`--error-rate` peuvent donc varier librement sans jamais dérégler le décodage — ils changent
seulement la qualité de l'élicitation RESSENTIE par l'utilisateur (la littérature situe le taux
d'erreur autour de 25-30 %), jamais le contrat réseau.

Lancer :
    python src/research/errp_stimulus.py                  # plein écran, ESC pour quitter
    python src/research/errp_stimulus.py --windowed       # fenêtre 1000x700 (dev)
    python src/research/errp_stimulus.py --cells 9        # cases de la piste (défaut ERRP_TRACK_CELLS)
    python src/research/errp_stimulus.py --error-rate 0.3 # taux d'erreurs délibérées (défaut ERRP_ERROR_RATE)
    python src/research/errp_stimulus.py --refresh 60     # forcer le refresh (sinon auto-mesuré)
    python src/research/errp_stimulus.py --seconds 20     # auto-quit après 20 s
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
                         ERRP_TRACK_CELLS, MARKER_STREAM_DEFAULT, use_utf8_console)
from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, local_clock  # noqa: E402

# --- Réglages d'affichage ---------------------------------------------------

BG = (0, 0, 0)              # fond noir -> contraste maximal, même choix que les autres stimuli
ON_COLOR = (255, 255, 255)  # le point (curseur)
GOAL_COLOR = (60, 200, 90)  # la cible : pastille verte, même choix que research/errp_calibrate.py
OUTLINE = (55, 55, 70)      # les cases de la piste
HUD = (70, 90, 70)


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
        journal=None):
    """La boucle du stimulus. `journal`, s'il est fourni, reçoit `(marqueur, horodatage, erreur)`
    pour CHAQUE feedback réellement poussé. `erreur` (bool, vérité-terrain LOCALE : ce pas a-t-il
    ÉLOIGNÉ le point de sa cible) ne part JAMAIS sur le réseau (cf. ⚠️ de la docstring du module) —
    il n'existe que pour permettre à `--smoke` de vérifier, sur le déroulé RÉEL, que le taux
    d'erreur joué reste raisonnable, en plus de la fonction pure `decide_pas` (vérifiée à grande
    échelle, sans écran, dans `_smoke`)."""
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
          f"(feedback affiché {ERRP_FEEDBACK_S:g} s/pas)")
    print(f"[errp-stim] marqueurs publiés sur « {stream_name} »")

    # ⚠️ Attendre le moteur AVANT le premier pas — même raisonnement que p300_stimulus.py : sans
    # ça, un étudiant qui a oublié de lancer le moteur regarde un écran fonctionnel sans le moindre
    # signe que personne n'écoute. L'attente est BORNÉE et on démarre quand même après.
    if attente_consommateur_s > 0 and not outlet.wait_for_consumers(attente_consommateur_s):
        print(f"[errp-stim] ⚠️ PERSONNE n'écoute « {stream_name} » après "
              f"{attente_consommateur_s:g} s. Le moteur est-il lancé "
              f"(`python src/core/server.py --mode errp`) ? Je continue quand même — l'indicateur "
              f"en haut de l'écran dit qui écoute, en direct.")
    elif attente_consommateur_s > 0:
        print("[errp-stim] le moteur écoute — on peut commencer.")

    w, h = size
    cy = h / 2
    dx = int(w * 0.09)
    x0 = int(w / 2 - (n_cells - 1) * dx / 2)
    r = max(6, int(min(dx * 0.32, h * 0.05)))

    hud_font = pygame.font.SysFont("consolas", max(12, int(min(w, h) * 0.016)))

    clock = pygame.time.Clock()
    rng = random.Random()
    running = True
    pas_total = 0
    erreurs_total = 0
    t_start = time.perf_counter()

    def emet(m, erreur):
        """Pousse un marqueur et l'horodate. UN SEUL endroit prend `local_clock()`."""
        ts = local_clock()
        outlet.push_sample([json.dumps(m)], timestamp=ts)
        if journal is not None:
            journal.append((m, ts, erreur))
        return ts

    def poll():
        """Événements + la limite `--seconds`, vérifiés à CHAQUE frame (pas seulement entre deux
        pas) : un étudiant qui règle une durée veut qu'elle soit tenue, pas arrondie au pas
        supérieur (~1 s ici, le même défaut que p300_stimulus.py corrigeait pour ses manches)."""
        nonlocal running
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False
        if seconds is not None and (time.perf_counter() - t_start) >= seconds:
            running = False

    def draw(pos, cible):
        win.fill(BG)
        for i in range(n_cells):
            pygame.draw.circle(win, OUTLINE, (x0 + i * dx, int(cy)), r, 2)
        pygame.draw.circle(win, GOAL_COLOR, (x0 + cible * dx, int(cy)), r + 3)   # la cible
        pygame.draw.circle(win, ON_COLOR, (x0 + pos * dx, int(cy)), r)          # le point
        # L'indicateur d'écoute, en direct : c'est la seule chose de cet écran qui distingue
        # « ça marche » de « ça a l'air de marcher ».
        ecoute = "moteur À L'ÉCOUTE" if outlet.have_consumers() else "PERSONNE n'écoute"
        taux_mesure = f"{erreurs_total / pas_total:.0%}" if pas_total else "—"
        hud = hud_font.render(f"pas {pas_total}  |  erreurs {taux_mesure} (visé {taux_erreur:.0%})  "
                              f"|  {refresh:.0f} fps  |  {ecoute}  |  ESC = quitter", True, HUD)
        win.blit(hud, (12, 10))

    pos = n_cells // 2
    cible = nouvelle_cible(n_cells, rng)
    n_pas_course = 0

    while running:
        nouvelle_pos, erreur = decide_pas(rng, pos, cible, n_cells, taux_erreur)
        pos = nouvelle_pos
        n_pas_course += 1
        n_fr = max(1, int(round(ERRP_FEEDBACK_S * refresh)))
        for f in range(n_fr):
            poll()
            if not running:
                break
            draw(pos, cible)
            pygame.display.flip()
            # ⚠️ L'HORODATAGE SE PREND ICI, juste après le basculement de frame — pas avant de
            # dessiner, pas au moment de décider le pas. Une charge utile parfaite envoyée 40 ms
            # trop tôt décale TOUTES les époques d'une frame, et le décodeur corrèle alors contre
            # une réponse évoquée qui n'a pas encore eu lieu.
            if f == 0:
                emet({"mode": "errp", "event": "feedback"}, erreur)
                pas_total += 1
                erreurs_total += int(erreur)
                print(f"[errp-stim] pas {pas_total} : point -> case {pos} "
                      f"({'ÉLOIGNÉ (erreur)' if erreur else 'rapproché (correct)'})")
            clock.tick(int(refresh) + 5)
        if not running:
            break

        if pos == cible or n_pas_course >= ERRP_MAX_RUN_STEPS:
            print(f"[errp-stim] {'cible atteinte' if pos == cible else 'pas max atteint'} en "
                  f"{n_pas_course} pas — nouvelle course")
            pos = n_cells // 2
            cible = nouvelle_cible(n_cells, rng)
            n_pas_course = 0

    pygame.quit()
    return True


# --- --smoke : le protocole en pur (grande échelle), PUIS la boucle réelle --

def _smoke(n_cells, taux_erreur):
    """Deux moitiés, comme `p300_stimulus._smoke`.

    **A. Le PROTOCOLE** (`decide_pas`/`nouvelle_cible`, fonctions pures) : le point reste toujours
    sur la piste après rebond, et surtout le taux d'erreur RÉEL sur un grand nombre de pas — c'est
    ICI, avec un N élevé et sans le moindre écran, que « proche de ERRP_ERROR_RATE » se vérifie
    avec une marge STATISTIQUE qui veut dire quelque chose. À l'échelle d'un `--smoke` réel (~
    quelques secondes, cf. B), on n'a que quelques pas : aucune tolérance sur un taux d'erreur n'y
    serait honnête (rigueur statistique du projet : ne jamais conclure sur du bruit).

    **B. `run()` POUR DE VRAI**, sur `SDL_VIDEODRIVER=dummy` — le patron de `p300_stimulus.py`
    depuis sa correction de revue : un `--smoke` qui retournerait avant l'import de pygame
    laisserait SANS AUCUNE COUVERTURE les lignes qui contiennent le geste flip->horodatage, la
    seule chose que ce fichier existe pour enseigner.

    Ce qui n'est PAS revérifié ici : le transport LSL (mûrissement, horodatage, offset d'horloge)
    est déjà prouvé par `core/markers.py`.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

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

    # --- B. run() POUR DE VRAI, sur un écran factice -------------------------------
    # Un flux au nom DISTINCT du contrat public : un smoke ne doit jamais pouvoir répondre à la
    # place d'un vrai émetteur (les noms de flux sont partagés par toutes les instances du projet).
    # `attente_consommateur_s=0` parce que personne n'écoute, par construction.
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    journal = []
    fait = run(windowed=True, refresh=60.0, n_cells=n_cells, taux_erreur=taux_erreur,
               seconds=6.5, stream_name=MARKER_STREAM_DEFAULT + "_smoke",
               attente_consommateur_s=0.0, journal=journal)
    chk(fait, "run() va au bout sur un écran factice (SDL_VIDEODRIVER=dummy)")

    chk(len(journal) >= 3, f"...et a RÉELLEMENT poussé plusieurs feedbacks ({len(journal)})")
    chk(all(m == {"mode": "errp", "event": "feedback"} for m, _ts, _e in journal),
        "chaque marqueur poussé est EXACTEMENT {mode: errp, event: feedback} — rien d'autre : le "
        "moteur ne doit JAMAIS recevoir la vérité-terrain (cf. ⚠️ de la docstring du module)")

    horodatages = [ts for _m, ts, _e in journal]
    chk(all(b > a for a, b in zip(horodatages, horodatages[1:])),
        "les horodatages avancent strictement — un flip par pas, un horodatage par flip")

    ecarts = [b - a for a, b in zip(horodatages, horodatages[1:])]
    chk(bool(ecarts) and all(0.5 * ERRP_FEEDBACK_S < e < 1.5 * ERRP_FEEDBACK_S for e in ecarts),
        f"...UN feedback par pas, espacés d'environ {ERRP_FEEDBACK_S:g} s -- pas de rafale, pas de "
        f"pas manquant ({[round(e, 2) for e in ecarts]} s)")

    n_err_reel = sum(1 for _m, _ts, e in journal if e)
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
                   help=f"cases de la piste (défaut {ERRP_TRACK_CELLS} — le moteur ne lit jamais "
                        f"cette valeur, cf. la docstring du module)")
    p.add_argument("--error-rate", type=float, default=ERRP_ERROR_RATE,
                   help=f"taux d'erreurs délibérées (défaut {ERRP_ERROR_RATE:g})")
    p.add_argument("--seconds", type=float, default=None, help="auto-quit après N secondes")
    p.add_argument("--smoke", action="store_true",
                   help="test headless (CI) : le protocole ET la boucle réelle, sur écran factice")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    ok = run(windowed=args.windowed, refresh=args.refresh, n_cells=args.cells,
             taux_erreur=args.error_rate, seconds=args.seconds, smoke=args.smoke)
    sys.exit(0 if ok else 1)
