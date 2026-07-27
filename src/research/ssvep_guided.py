"""Run guidé SSVEP : mesurer la JUSTESSE du moteur, avec de quoi y croire.

Il existe déjà un `live_ssvep.py --guided`. Il répond à « est-ce que fixer une flèche fait
monter SON ρ ? » — une vérification qualitative, utile, mais qui ne peut pas donner un taux :
un bloc contigu de 7 s par cible, sans chauffe, soit ~5 fenêtres indépendantes par cible.

Ce fichier-ci répond à « quelle est l'accuracy du moteur ? », et il est construit autour des
trois choses qui rendent cette réponse défendable :

1. **Chauffe avant tout.** L'Unicorn sort un offset DC énorme et DÉRIVANT pendant des dizaines
   de secondes après l'ouverture de session. Mesurer le plancher de repos là-dedans revient à
   étalonner sur le transitoire du filtre. Le moteur jette `SSVEP_WARMUP_S`; on fait pareil.
2. **Essais ENTRELACÉS et tirés au sort.** Un bloc contigu par cible rend « quelle cible »
   inséparable de « quand » : la dérive d'impédance, la fatigue et l'installation des
   électrodes se confondent avec l'effet cherché. Le c-VEP a payé ce confond 76 % de débit
   (cf. README) ; on ne le refait pas ici.
3. **Un essai = une décision.** Les fenêtres du moteur se CHEVAUCHENT (1,5 s toutes les
   0,2 s) : les compter comme indépendantes gonfle l'effectif d'un facteur ~7 et donne un
   intervalle de confiance faux. On archive UNE fenêtre par essai, la dernière de la fixation,
   et l'effectif annoncé est le nombre d'essais.

Le protocole n'invente aucune règle de décision : il archive les fenêtres BRUTES 8 voies, et
`--analyze` rejoue exactement le chemin du moteur (`occipital_window` -> `CCADecoder` calé sur
le plancher -> seuil `Z_MIN`). Ce qui est mesuré est donc la règle du produit, pas une variante.
Archiver le brut permet aussi de rejouer d'autres réglages plus tard SANS reprendre de séance.

⚠️ Ce que ce run ne mesure PAS : le trajet réseau (publication LSL, horloges, deux machines).
Il est validé séparément. Ici on isole le décodage.

    python src/research/ssvep_guided.py                 # protocole complet (~4 min)
    python src/research/ssvep_guided.py --trials 8      # plus court (8 essais/cible)
    python src/research/ssvep_guided.py --analyze       # rejoue le dernier run archivé
    python src/research/ssvep_guided.py --synthetic     # sans casque, pour vérifier le câblage
"""

import argparse
import glob
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))      # -> src/
from core.acquisition import UnicornAcquisition  # noqa: E402
from core.cca_decoder import CCADecoder  # noqa: E402
from core.config import (ARTIFACT_SIGMA_RATIO, CH_NAMES, DATA_DIR,  # noqa: E402
                         SSVEP_BASELINE_S, SSVEP_WARMUP_S, WINDOW_S,
                         choose_frequencies, reference_lost, signal_verdict,
                         use_utf8_console)
from research.ssvep_stimulus import arrow_polygon, is_on, measure_refresh  # noqa: E402

# --- Chronologie d'un essai --------------------------------------------------
# CUE : on annonce la cible, l'utilisateur y amène son regard. Cette seconde n'est PAS
#   enregistrée — la saccade et sa fin de course polluent le début de la fixation.
# FIX : fixation. On n'archive que la DERNIÈRE fenêtre (WINDOW_S), donc les 1,5 premières
#   secondes servent de délai d'établissement de la réponse SSVEP.
# GAP : retour à la croix centrale, pour que deux essais consécutifs ne se recouvrent pas.
CUE_S = 1.2
FIX_S = 3.0
GAP_S = 1.0
TRIALS_PER_TARGET = 12   # 3 cibles -> 36 essais -> ~3 min de fixation

BG = (8, 8, 12)
FG = (225, 225, 235)
DIM = (110, 110, 130)
CUE = (245, 200, 90)
GO = (80, 210, 120)
WARN = (235, 120, 90)
ON_COLOR = (255, 255, 255)
OUTLINE = (55, 55, 70)


def _schedule(names, per_target, rng):
    """Ordre des essais : équilibré, tiré au sort, sans plus de 2 fois la même cible d'affilée.

    L'équilibre garantit que chaque cible est jugée sur le même effectif. Le tirage casse le
    confond « cible / moment ». La contrainte anti-série évite qu'une cible hérite d'un bloc
    contigu par hasard — ce serait retomber sur le défaut qu'on cherche justement à éviter,
    et sur 36 essais le hasard produit ce genre de série plus souvent qu'on ne le croit.
    """
    pool = list(names) * per_target
    for _ in range(200):
        rng.shuffle(pool)
        runs = max(len(list(g)) for g in _groups(pool))
        if runs <= 2:
            return pool
    return pool  # tirage acceptable non trouvé : on garde le dernier (contrainte non critique)


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


def _wilson(k, n, z=1.96):
    """Intervalle de confiance de Wilson à 95 % pour une proportion.

    Préféré à l'intervalle normal parce qu'il reste dans [0, 1] et tient debout sur de petits
    effectifs — précisément notre cas.
    """
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    demi = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - demi), min(1.0, centre + demi)


# --- Passation ---------------------------------------------------------------

def run(windowed=False, synthetic=False, smoke=False, per_target=TRIALS_PER_TARGET, seed=None):
    if smoke:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        synthetic = True
        per_target = 1

    import pygame
    pygame.init()
    pygame.font.init()

    if windowed or smoke:
        size, flags = (1100, 780), pygame.SCALED
    else:
        info = pygame.display.Info()
        size, flags = (info.current_w, info.current_h), pygame.FULLSCREEN | pygame.SCALED
    try:
        win = pygame.display.set_mode(size, flags, vsync=1)
    except (TypeError, pygame.error):
        win = pygame.display.set_mode(size, flags)
    pygame.display.set_caption("SSVEP guidé (mesure) — EEG_API_Unicorn")
    pygame.mouse.set_visible(False)

    refresh = 60.0 if smoke else measure_refresh(pygame, win)
    plan = choose_frequencies(refresh)
    names = [c["name"] for c in plan]
    freqs = [c["actual_hz"] for c in plan]

    w, h = size
    cx, cy, span = w / 2, h / 2, min(w, h)
    dist, asize = span * 0.30, span * 0.12
    pos = {"up": (cx, cy - dist), "down": (cx, cy + dist),
           "left": (cx - dist, cy), "right": (cx + dist, cy)}
    polys = {c["dir"]: arrow_polygon(*pos[c["dir"]], asize, c["dir"]) for c in plan}
    fpc = {c["dir"]: c["frames_per_cycle"] for c in plan}
    dir_of = {c["name"]: c["dir"] for c in plan}

    big = pygame.font.SysFont("consolas", max(22, int(span * 0.042)), bold=True)
    mid = pygame.font.SysFont("consolas", max(15, int(span * 0.022)))

    rng = np.random.default_rng(seed)
    order = _schedule(names, per_target, rng)

    acq = UnicornAcquisition(synthetic=synthetic).start()
    need = acq.window_n + acq.margin_n   # longueur d'un bloc brut archivé

    warmup_s = 0.5 if smoke else SSVEP_WARMUP_S
    baseline_s = 0.5 if smoke else max(SSVEP_BASELINE_S + 4.0, 12.0)
    cue_s, fix_s, gap_s = (0.2, 0.3, 0.1) if smoke else (CUE_S, FIX_S, GAP_S)

    print(f"[guidé] refresh={refresh:.1f} Hz  cibles=" +
          "  ".join(f"{c['name']}@{c['actual_hz']:.2f}Hz" for c in plan))
    print(f"[guidé] {len(order)} essais ({per_target}/cible), ordre entrelacé tiré au sort")
    print(f"[guidé] fixation utile = dernière fenêtre de {WINDOW_S} s sur {FIX_S} s")

    state = {"abort": False}

    def pump():
        """Événements + rendu d'une frame. Retourne False si l'utilisateur abandonne."""
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                state["abort"] = True
                return False
        return True

    def draw(frame, highlight=None, title="", sub="", colour=FG, cross=True):
        win.fill(BG)
        for c in plan:
            d = c["dir"]
            pygame.draw.polygon(win, OUTLINE, polys[d], 2)
            if is_on(frame, fpc[d]):
                pygame.draw.polygon(win, ON_COLOR, polys[d])
            if highlight == d:
                pygame.draw.polygon(win, CUE, polys[d], 6)
        if cross:
            pygame.draw.line(win, DIM, (cx - 14, cy), (cx + 14, cy), 3)
            pygame.draw.line(win, DIM, (cx, cy - 14), (cx, cy + 14), 3)
        if title:
            s = big.render(title, True, colour)
            win.blit(s, (cx - s.get_width() / 2, h * 0.06))
        if sub:
            s = mid.render(sub, True, DIM)
            win.blit(s, (cx - s.get_width() / 2, h * 0.06 + big.get_height() + 8))
        pygame.display.flip()

    clock = pygame.time.Clock()
    fps = int(refresh) + 5
    frame = 0

    def phase(duration, **kw):
        """Affiche pendant `duration` s en gardant le clignotement verrouillé à la frame."""
        nonlocal frame
        t_end = time.perf_counter() + duration
        while time.perf_counter() < t_end:
            if not pump():
                return False
            draw(frame, **kw)
            clock.tick(fps)
            frame += 1
        return True

    trials, labels, sigmas = [], [], []
    baseline_blocks, baseline_sigmas = [], []
    ok = True
    try:
        # --- 1. Contrôle de liaison (AVANT d'enregistrer quoi que ce soit) ---------
        ok = _link_gate(acq, pygame, win, big, mid, clock, synthetic or smoke, state)
        if ok:
            # --- 2. Chauffe : rien n'est gardé ------------------------------------
            print(f"[guidé] chauffe {warmup_s:.0f} s (amplificateur) — rien n'est enregistré")
            t_end = time.perf_counter() + warmup_s
            while ok and time.perf_counter() < t_end:
                rest = t_end - time.perf_counter()
                ok = phase(min(0.25, max(0.0, rest)),
                           title="CHAUFFE", cross=True,
                           sub=f"détends-toi, ne fixe rien — {rest:.0f} s")

        if ok:
            # --- 3. Plancher de repos --------------------------------------------
            # Le clignotement TOURNE pendant cette phase : le plancher doit être mesuré dans
            # les mêmes conditions visuelles que les essais, sinon on soustrait un fond qui
            # n'est pas celui du test.
            print(f"[guidé] plancher de repos {baseline_s:.0f} s — fixe la croix, ne suis aucune flèche")
            t_end = time.perf_counter() + baseline_s
            last = 0.0
            while ok and time.perf_counter() < t_end:
                rest = t_end - time.perf_counter()
                ok = phase(min(0.1, max(0.0, rest)), title="REPOS",
                           sub=f"fixe la croix centrale, ne suis AUCUNE flèche — {rest:.0f} s")
                now = time.perf_counter()
                if now - last >= 0.2:   # ~5 Hz, comme le moteur
                    blk = acq.get_epoch(WINDOW_S, filtered=False, margin_s=acq.margin_n / acq.fs)
                    if blk is not None and len(blk) >= need:
                        block = blk[-need:]
                        baseline_blocks.append(block.astype(np.float32))
                        s = acq.sigma_from_block(block)
                        baseline_sigmas.append(float(np.mean(s)) if s is not None else np.nan)
                        last = now

        if ok:
            # --- 4. Essais --------------------------------------------------------
            for i, target in enumerate(order, 1):
                d = dir_of[target]
                ok = phase(cue_s, highlight=d, colour=CUE, cross=False,
                           title=f"REGARDE : {target}", sub=f"essai {i}/{len(order)}")
                if not ok:
                    break
                ok = phase(fix_s, highlight=d, colour=GO, cross=False,
                           title=target, sub="fixe la flèche entourée")
                if not ok:
                    break

                blk = acq.get_epoch(WINDOW_S, filtered=False, margin_s=acq.margin_n / acq.fs)
                if blk is None or len(blk) < need:
                    print(f"[guidé] essai {i} ({target}) : tampon incomplet, essai ignoré")
                else:
                    block = blk[-need:]
                    trials.append(block.astype(np.float32))
                    labels.append(target)
                    s = acq.sigma_from_block(block)
                    sigmas.append(float(np.mean(s)) if s is not None else float("nan"))

                ok = phase(gap_s, title="—", sub="repose les yeux sur la croix")
                if not ok:
                    break
    finally:
        acq.stop()
        pygame.quit()

    if state["abort"]:
        print(f"[guidé] interrompu par l'utilisateur après {len(trials)} essais.")
    if smoke:
        print("[guidé] smoke OK : contrôle liaison + chauffe + plancher + essais câblés (headless).")
        return True

    if len(trials) < 6 or len(baseline_blocks) < 10:
        print(f"[guidé] pas de quoi conclure ({len(trials)} essais, "
              f"{len(baseline_blocks)} fenêtres de repos) — rien n'est archivé.")
        return False

    path = _save(trials, labels, sigmas, baseline_blocks, baseline_sigmas,
                 names, freqs, acq.fs, refresh)
    print(f"\n[guidé] {len(trials)} essais archivés -> {os.path.basename(path)}")
    analyze(path)
    return True


def _link_gate(acq, pygame, win, big, mid, clock, auto, state):
    """Écran de contrôle de liaison. Bloque tant que l'utilisateur n'a pas validé.

    Placé AVANT la chauffe et non après : une référence décollée rend la séance entière
    inexploitable, et rien d'autre ne le signale. Autant le voir avant d'avoir fixé 36 fois.

    `auto` (board synthétique ou smoke) enchaîne sans attendre : il n'y a pas d'électrode à
    contrôler sur un board de test, et faire semblant de le vérifier serait pire qu'inutile.
    """
    t0 = time.perf_counter()
    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                state["abort"] = True
                return False
            if e.type == pygame.KEYDOWN and e.key in (pygame.K_SPACE, pygame.K_RETURN):
                return True

        sig, common = (None, None) if auto else acq.link_check(seconds=2.0)
        win.fill(BG)
        y = win.get_height() * 0.12
        head = big.render("Contrôle de liaison", True, FG)
        win.blit(head, (win.get_width() / 2 - head.get_width() / 2, y))
        y += head.get_height() + 24

        if auto:
            s = mid.render("board de test — aucune électrode à contrôler", True, DIM)
            win.blit(s, (win.get_width() / 2 - s.get_width() / 2, y))
        elif sig is None:
            line = mid.render("remplissage du tampon...", True, DIM)
            win.blit(line, (win.get_width() / 2 - line.get_width() / 2, y))
        else:
            if reference_lost(common):
                msg = (f"RÉFÉRENCE DÉCROCHÉE (corrélation inter-voies {common:+.3f}) — "
                       "remets les mastoïdes")
                colour = WARN
            else:
                msg = f"référence en place (corrélation inter-voies {common:+.3f})"
                colour = GO
            s = big.render(msg, True, colour)
            win.blit(s, (win.get_width() / 2 - s.get_width() / 2, y))
            y += s.get_height() + 20
            for name, sd in zip(CH_NAMES, sig):
                verdict = signal_verdict(sd)
                col = GO if verdict == "ok" else WARN
                s = mid.render(f"{name:<4} σ={sd:7.1f} µV   {verdict}", True, col)
                win.blit(s, (win.get_width() / 2 - s.get_width() / 2, y))
                y += s.get_height() + 4

        y += 24
        s = mid.render("ESPACE pour démarrer  ·  ÉCHAP pour abandonner", True, DIM)
        win.blit(s, (win.get_width() / 2 - s.get_width() / 2, y))
        pygame.display.flip()
        clock.tick(30)
        if auto and time.perf_counter() - t0 > 1.0:
            return True


def _save(trials, labels, sigmas, baseline, baseline_sigmas, names, freqs, fs, refresh):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"ssvep_run_{time.strftime('%Y%m%d-%H%M%S')}.npz")
    np.savez_compressed(
        path,
        trials=np.asarray(trials), labels=np.asarray(labels), sigmas=np.asarray(sigmas),
        baseline=np.asarray(baseline), baseline_sigmas=np.asarray(baseline_sigmas),
        names=np.asarray(names), freqs=np.asarray(freqs),
        fs=fs, refresh=refresh, window_s=WINDOW_S)
    return path


# --- Analyse -----------------------------------------------------------------

def _latest():
    files = sorted(glob.glob(os.path.join(DATA_DIR, "ssvep_run_*.npz")))
    return files[-1] if files else None


def analyze(path=None, permutations=10000, seed=0):
    """Rejoue la règle du MOTEUR sur un run archivé et en donne un taux défendable."""
    path = path or _latest()
    if not path or not os.path.exists(path):
        print("[analyse] aucun run archivé (data/ssvep_run_*.npz). Lance d'abord le protocole.")
        return False

    d = np.load(path, allow_pickle=False)
    names = [str(n) for n in d["names"]]
    freqs = [float(f) for f in d["freqs"]]
    trials, labels = d["trials"], [str(s) for s in d["labels"]]
    baseline, sigmas = d["baseline"], d["sigmas"]

    print(f"\n=== {os.path.basename(path)} ===")
    print(f"{len(trials)} essais · {len(baseline)} fenêtres de repos · "
          f"refresh {float(d['refresh']):.1f} Hz")
    print("cibles : " + "  ".join(f"{n}@{f:.2f}Hz" for n, f in zip(names, freqs)))

    # Le décodeur est reconstruit à l'identique du moteur, puis calé sur le repos du run.
    acq = UnicornAcquisition(synthetic=True)   # jamais démarré : on n'utilise que ses filtres
    need = acq.window_n + acq.margin_n
    if trials.shape[1] != need or float(d["fs"]) != acq.fs:
        print(f"⚠️ le run a été enregistré avec des réglages différents "
              f"(bloc {trials.shape[1]} éch. à {float(d['fs']):g} Hz, attendu {need} à {acq.fs:g} Hz).\n"
              "   Les constantes WINDOW_S / FILTER_MARGIN_S ont changé depuis : l'analyse "
              "ne reproduirait plus la règle du moteur. Rejeu abandonné.")
        return False
    decoder = CCADecoder(freqs)
    rest_scores = [decoder.scores(acq.occipital_window(b)) for b in baseline]
    if not decoder.fit_baseline(rest_scores):
        print(f"[analyse] plancher impossible ({len(rest_scores)} fenêtres) — run inexploitable.")
        return False

    line = "  ".join(f"{f:g}Hz: μ={m:.2f} σ={s:.2f}" for f, (m, s) in decoder.baseline.items())
    print(f"plancher de repos — {line}")
    for f, (mu, sd) in decoder.baseline.items():
        needed = mu + decoder.z_min * sd
        if needed > 0.85:
            print(f"  ⚠️ {f:g} Hz : il faudrait ρ≈{needed:.2f} pour émettre — cible quasi "
                  "INDÉTECTABLE sur ce plancher (σ trop dispersé).")

    # Référence d'amplitude pour le rejet d'artefact : la MÉDIANE DU REPOS, comme dans le
    # moteur. La prendre sur les essais eux-mêmes serait circulaire — les fenêtres à juger
    # tireraient le seuil vers le haut et un essai bruité passerait pour normal.
    sigma_ref = float(np.median(d["baseline_sigmas"])) if len(d["baseline_sigmas"]) else None

    # --- Décision : une fenêtre par essai, exactement comme le moteur --------
    pred, artefacts = [], 0
    for block, sd in zip(trials, sigmas):
        if sigma_ref and sd > ARTIFACT_SIGMA_RATIO * sigma_ref:
            pred.append(None)     # le moteur publierait « aucune cible »
            artefacts += 1
            continue
        window = acq.occipital_window(block.astype(np.float64))
        freq, _ = decoder.classify(window)
        pred.append(None if freq is None else names[freqs.index(freq)])

    n = len(labels)
    emitted = [(p, y) for p, y in zip(pred, labels) if p is not None]
    correct = sum(1 for p, y in zip(pred, labels) if p == y)
    good_emitted = sum(1 for p, y in emitted if p == y)
    lo, hi = _wilson(correct, n)
    chance = 1.0 / len(names)

    print(f"\n--- Règle du moteur (z ≥ {decoder.z_min}) ---")
    print(f"ACCURACY = {correct}/{n} = {correct/n*100:.1f} %   "
          f"IC95 % [{lo*100:.1f} ; {hi*100:.1f}]   (hasard {chance*100:.1f} %)")
    print(f"  émission : {len(emitted)}/{n} essais produisent une décision "
          f"({len(emitted)/n*100:.0f} %) — les autres = sous le seuil")
    if emitted:
        print(f"  justesse QUAND ça émet : {good_emitted}/{len(emitted)} = "
              f"{good_emitted/len(emitted)*100:.1f} %")
    if artefacts:
        print(f"  {artefacts} essai(s) rejeté(s) comme artefact (σ > {ARTIFACT_SIGMA_RATIO}× repos)")

    # Test de permutation : l'accuracy observée survit-elle à un étiquetage au hasard ?
    rng = np.random.default_rng(seed)
    y = np.array(labels)
    p = np.array([x if x is not None else "" for x in pred])
    null = np.empty(permutations)
    for i in range(permutations):
        null[i] = np.mean(p == rng.permutation(y))
    pval = (np.sum(null >= correct / n) + 1) / (permutations + 1)
    print(f"  permutation ({permutations} tirages) : p = {pval:.4f}"
          + ("  -> significatif" if pval < 0.05 else "  -> NON significatif (= bruit)"))

    # --- Confusion, pour voir QUELLE cible pose problème --------------------
    print(f"\n--- Confusion (lignes = fixé, colonnes = décodé) ---")
    header = "         " + "".join(f"{c[:6]:>8}" for c in names) + f"{'rien':>8}"
    print(header)
    for t in names:
        row = [sum(1 for p_, y_ in zip(pred, labels) if y_ == t and p_ == c) for c in names]
        none_ = sum(1 for p_, y_ in zip(pred, labels) if y_ == t and p_ is None)
        tot = sum(row) + none_
        acc = row[names.index(t)] / tot * 100 if tot else 0.0
        print(f"{t[:8]:<9}" + "".join(f"{v:>8}" for v in row) + f"{none_:>8}   ({acc:.0f} %)")

    print("\nLecture : l'effectif est le nombre d'ESSAIS (fenêtres non chevauchantes), pas le "
          "nombre de fenêtres du moteur.\nUn taux au-dessus du hasard avec p < 0,05 dit que le "
          "décodage marche ; il ne dit pas qu'il marchera\ndemain — la variance entre séances "
          "est de l'ordre d'un facteur 9 sur ce casque.")
    return True


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Run guidé SSVEP : mesurer l'accuracy du moteur (protocole + analyse).")
    p.add_argument("--analyze", action="store_true", help="rejouer le dernier run archivé, sans casque")
    p.add_argument("--file", default=None, help="run précis à analyser (npz)")
    p.add_argument("--trials", type=int, default=TRIALS_PER_TARGET, help="essais par cible")
    p.add_argument("--seed", type=int, default=None, help="graine du tirage de l'ordre")
    p.add_argument("--windowed", action="store_true", help="en fenêtre (console visible)")
    p.add_argument("--synthetic", action="store_true", help="board de test BrainFlow (sans casque)")
    p.add_argument("--smoke", action="store_true", help="test headless (CI)")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    a = _parse_args(sys.argv[1:])
    if a.analyze or a.file:
        sys.exit(0 if analyze(a.file) else 1)
    sys.exit(0 if run(windowed=a.windowed, synthetic=a.synthetic, smoke=a.smoke,
                      per_target=a.trials, seed=a.seed) else 1)
