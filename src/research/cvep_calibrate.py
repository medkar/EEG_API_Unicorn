"""Calibration c-VEP : fixer chaque cible quelques secondes -> template + filtre spatial.

Beaucoup plus courte que la calibration Motor Imagery (~1 min contre 5-7 min) parce qu'on
n'apprend pas une intention mentale, seulement la **forme de ta réponse visuelle** au code.

Déroulé : les 3 cibles clignotent en permanence avec le même code décalé ; on te demande
d'en fixer une, et on enregistre `CVEP_CAL_CYCLES` cycles complets. On recommence pour
chaque cible. Enregistrer les 3 (plutôt qu'une seule) coûte le même temps total et vérifie
en prime que l'alignement des lags est bon (l'accuracy leave-one-out le dit).

Chaque époque est prélevée EXACTEMENT à une frontière de cycle (frame % L == 0) : la
fenêtre couvre alors le cycle qui vient de s'écouler, donc démarre à la phase 0 du code.
"""

import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (CH_NAMES, CVEP_BAND, CVEP_CAL_BLOCKS,  # noqa: E402
                    CVEP_CAL_CYCLES, CVEP_CHANNELS, CVEP_DECISION_CYCLES, CVEP_LAG_ROTATION,
                    CVEP_MODEL_PATH, CVEP_RCCA_MODEL_PATH, FS_UNICORN, cvep_lag_gap_ms,
                    use_utf8_console)
from core.cvep_code import build_targets, is_on  # noqa: E402
from core.cvep_decoder import CVEPModel, groupes_de_cycles  # noqa: E402
from core.cvep_rcca import RCCAModel  # noqa: E402
from research.itr import itr  # noqa: E402
from research.ui import BG, DIM, FG, GO, WARN, Abort  # noqa: E402

SETTLE_CYCLES = 2   # cycles jetés après un changement de cible (déplacement du regard + VEP qui s'installe)
# Plancher d'utilité pour le contrôle de séance (bits/min). ~1/3 du meilleur c-VEP mesuré
# (27,1) : en dessous, la séance n'apprend rien qu'on ne sache déjà. Voir `_early_check`.
EARLY_ITR_MIN = 10.0

BRIEF = [
    "Calibration c-VEP",
    "",
    "• Les cibles clignotent selon un code pseudo-aléatoire (ça « grésille », c'est normal).",
    "• Une cible est CERCLÉE : fixe-la, sans bouger les yeux, jusqu'au changement.",
    "• Regard bien PLANTÉ sur le disque (contrairement au Motor Imagery : ici le regard compte).",
    "• Cligne le moins possible pendant l'enregistrement, reste immobile.",
    "• La durée totale est affichée dans la console au lancement.",
    "",
    "Appuie sur une touche pour commencer (ESC pour annuler).",
]


def _briefing(app):
    while True:
        pressed = []
        app.drain(on_key=lambda e: pressed.append(True))
        if pressed:
            return True
        app.win.fill(BG)
        h = app.win.get_height()
        y = int(h * 0.16)
        for i, line in enumerate(BRIEF):
            f = app.big if i == 0 else app.small
            col = FG if i == 0 else (GO if line.startswith("Appuie") else FG)
            app.center(f, line, col, y)
            y += int(h * 0.085) if i == 0 else int(h * 0.056)
        app.pygame.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return True


def _make_blocks(plan, cycles, n_blocks):
    """Découpe les cycles de chaque cible en `n_blocks` blocs, puis MÉLANGE l'ordre de passage.

    ⚠️ Sans ça, chaque cible occupe une tranche de temps distincte et « quelle cible » devient
    indissociable de « à quel moment » : mesuré le 2026-07-20, l'accuracy passait de 34% sur le
    premier tiers de la séance à 66% sur le dernier, ce qui faisait passer les deux dernières
    cibles pour les meilleures. Entrelacer répartit l'effet d'apprentissage sur toutes les cibles.
    """
    per = max(1, cycles // n_blocks)
    blocks = []
    for target in plan:
        left = cycles
        for b in range(n_blocks):
            n = left if b == n_blocks - 1 else min(per, left)
            if n > 0:
                blocks.append((target, n))
            left -= n
    random.shuffle(blocks)
    return blocks


def _wilson_hi(acc, n, z=1.96):
    """Borne SUPÉRIEURE de l'intervalle de Wilson (petits effectifs)."""
    if n == 0:
        return 1.0
    d = 1 + z * z / n
    c = (acc + z * z / (2 * n)) / d
    h = z * ((acc * (1 - acc) / n + z * z / (4 * n * n)) ** 0.5) / d
    return min(1.0, c + h)


def _early_check(model, epochs, lags, n_targets):
    """Verdict à mi-parcours : « cette séance peut-elle encore donner quelque chose ? »

    Le 2026-07-20 on a dépensé 4,5 min de casque sur une séance à 3,0 bits/min, et AUCUN
    indicateur pré-séance ne l'avait vue venir (le ratio alpha valait 18,93, le meilleur
    jamais mesuré ; la dérive brute ne discrimine pas). La seule mesure qui marche est la
    performance elle-même — autant la lire pendant l'enregistrement plutôt qu'après.

    ⚠️ Critère volontairement ASYMÉTRIQUE : on convertit la borne HAUTE de Wilson en ITR et
    on n'alerte que si même l'hypothèse la PLUS FAVORABLE reste inutile. Un LOO à mi-parcours
    porte sur peu d'époques : le lire comme une estimation ponctuelle ferait abandonner des
    séances correctes. Pas d'alerte ne veut donc PAS dire « ça va bien », seulement « on ne
    peut pas encore l'exclure » — c'est exactement ce qu'on attend d'un garde-fou.

    ⚠️ Le critère est en BITS/MIN, pas en accuracy. Une première version comparait l'accuracy
    à 2x le hasard : elle attrapait les liaisons mortes mais RATAIT la séance à 8 cibles du
    2026-07-20 (LOO 21 %, borne haute 30 %, seuil 25 % -> « continue », résultat final
    3,0 bits/min). Normal : 21 % à 8 cibles est réellement au-dessus du hasard, la séance
    n'était pas morte, elle était médiocre — et « 2x le hasard » ne veut pas dire la même
    chose à 4, 6 ou 8 cibles. L'ITR est la seule échelle comparable entre configurations.

    Le seuil vient de l'UTILITÉ projet, pas d'un ajustement sur les données : une séance qui
    ne peut pas atteindre ~1/3 de notre meilleur c-VEP (27,1 bits/min) n'apprend rien.
    Distinction importante — sur les 6 séances archivées, n'importe quel seuil entre 9 et 15
    « fonctionne », donc les valider dessus ne prouverait rien (4 points informatifs, 2
    dégénérés à 0). À revoir quand on aura une dizaine de séances.

    LIMITE CONNUE : ne détecte pas une séance qui s'effondre APRÈS le contrôle (la séance
    14:09 était à 15,8 de borne haute à 40 % puis a fini à 0, avec une accuracy décroissante
    au fil des tiers). Un contrôle ponctuel ne peut pas prédire une dégradation ultérieure.

    Retourne (alerte, accuracy, itr_borne_haute) ou None si les données ne suffisent pas.
    """
    by_lag = {}
    for l in lags:
        by_lag[l] = by_lag.get(l, 0) + 1
    if len(by_lag) < n_targets or min(by_lag.values()) < 2:
        return None                      # toutes les cibles doivent avoir été vues
    probe = CVEPModel(fs=model.fs, refresh=model.refresh, code_len=model.code_len)
    probe.channels = model.channels          # suivre le modèle réel, pas le défaut de config
    probe.fit([e[:, probe.channels] for e in epochs], lags)
    acc = probe.cv_
    if acc is None:
        return None
    hi = _wilson_hi(acc, len(epochs))
    hi_itr = itr(n_targets, hi, model.n_cyc / model.fs)
    return (hi_itr < EARLY_ITR_MIN), acc, hi_itr


def _fit_et_compte(modele, epochs, labels, **kw):
    """Ajuste `modele` sur EXACTEMENT `epochs`/`labels`, et rend `len(epochs)` — capturé ICI, au
    point d'appel, pour qu'un futur tronquage de l'ARGUMENT (`epochs[:-6]`) se voie dans le
    compte rendu, et pas seulement dans le modèle ajusté. Un `len(labels)` recalculé ailleurs,
    lui, ne bougerait pas si un seul des deux appels était tronqué — c'est exactement le trou que
    la revue de tâche 6 a trouvé dans `n_epoques`."""
    modele.fit(epochs, labels, **kw)
    return len(epochs)


def entraine_les_deux(epochs, labels, fs=FS_UNICORN, refresh=60.0, band=CVEP_BAND,
                      channels=None, n_cycles=CVEP_DECISION_CYCLES):
    """Entraîne eCCA ET rCCA sur les MÊMES époques de calibration, PARMI LE MÊME JEU DE CIBLES,
    les note HORS-PLI sur les MÊMES groupes de validation croisée, et rend
    `{"eCCA": {...}, "rCCA": {...}}`.

    ⚠️ Ce n'est PAS une nouvelle analyse : `CVEPModel.hors_pli` et `RCCAModel.hors_pli` existent
    depuis la tâche 3 (jumeaux, même contrat `(epochs, labels, n_cycles) -> scores`) et sont déjà
    éprouvés — `python src/core/cvep_rcca.py --seuils <calib.npz>` les fait déjà tourner côte à
    côte sur une calibration réelle (43/90 chacun, à k=1). Cette fonction se contente de les
    appeler tous les deux sur les mêmes entrées et de porter le résultat jusqu'à l'écran.

    `n_cycles` vaut `CVEP_DECISION_CYCLES` par défaut : c'est la géométrie où le MOTEUR décide,
    pas celle d'une époque de calibration seule — `groupes_de_cycles` prescrit littéralement de
    « mesurer un décodeur à la géométrie où il servira » (tâche 3). Mesuré sur
    `data/cvep_calib_last.npz` (lecture seule) : à k=1 les deux décodeurs sont à ÉGALITÉ EXACTE
    (43/90 chacun) ; à k=2 (la géométrie réelle), ils ne le sont plus.

    ⚠️ **Une séance INTERROMPUE (ESC pendant l'enregistrement, cf. `Abort` dans `calibrate()`) peut
    n'avoir vu qu'un SOUS-ENSEMBLE des cibles du plan.** `CVEPModel.hors_pli` ne juge alors que
    parmi les lags RÉELLEMENT VUS (son `uniq = sorted(set(lags))` rétrécit avec eux, et son hasard
    aussi) — mais un `RCCAModel` construit avec TOUS les codes du plan resterait jugé sur 1/6,
    quel que soit ce qui a été enregistré. Comparer les deux tels quels offre alors des points
    gratuits à celui jugé sur le plus petit jeu : MESURÉ sur `cvep_calib_last.npz` tronqué à 3
    cibles, eCCA 71,1 % (hasard 33,3 %) contre rCCA 51,1 % (hasard 16,7 %) — un « gagnant »
    entièrement fabriqué par l'écart de hasard, pas par le signal. On réduit donc les codes du
    rCCA aux SEULES cibles présentes dans `labels`, exactement comme `hors_pli` réduit `uniq` :
    les deux décodeurs jugent alors sur le MÊME nombre d'alternatives, quoi qu'il arrive à la
    séance.

    `epochs` : cycles BRUTS (n_cyc x n_voies enregistrées, ex. 8 pour l'Unicorn) — la réduction
    aux voies AJUSTÉES (`channels`, `CVEP_CHANNELS` par défaut) se fait ICI, la MÊME pour les deux
    décodeurs : sans ça, un montage différent d'un décodeur à l'autre biaiserait la comparaison
    (vérifié par un garde qui REFUSE plutôt que de comparer si jamais ça divergeait).
    `labels` : le LAG (frames) fixé à chaque époque, comme les stocke `calibrate()`.

    Chaque valeur du dict rendu porte :
      `modele`      — l'objet entraîné (CVEPModel ou RCCAModel), prêt pour `.save(...)` ;
      `justesse`    — accuracy HORS-PLI (jamais celle, optimiste, d'un modèle qui a vu l'essai
                      qu'il note — le piège qui a gonflé le premier écran de calibration MI) ;
      `n_epoques`   — le nombre d'époques RÉELLEMENT données à `.fit()` pour CE décodeur (lu sur
                      l'appel lui-même, `_fit_et_compte`) ; DOIT être `len(labels)` pour les deux,
                      sinon ils n'ont pas vu le même protocole ;
      `groupes`     — les groupes de validation croisée (`core.cvep_decoder.groupes_de_cycles`,
                      à la géométrie `n_cycles`) — LES MÊMES pour les deux, par construction ;
      `n_decisions` — le nombre de groupes RÉELLEMENT notés par ce décodeur (la longueur de ce
                      que SON `hors_pli` a rendu). Comparé à `len(groupes)` par l'appelant : s'il
                      diffère, ce décodeur a été noté à une AUTRE géométrie que celle annoncée
                      dans `groupes` — la comparaison ne serait plus honnête, silencieusement ;
      `n_cibles`    — le nombre d'alternatives RÉELLEMENT notées par ce décodeur (la largeur de
                      SA matrice de scores hors-pli, `sc.shape[1]`) : c'est CE nombre qui fixe le
                      hasard contre lequel lire `justesse`. DOIT être égal pour les deux, sinon
                      l'un a été jugé sur un jeu de cibles plus facile que l'autre (le Critical 1
                      de la revue de tâche 6).
    """
    plan, code = build_targets()
    codes = np.stack([np.asarray(c["code"], dtype=int) for c in plan])
    lag_a_idx = {c["lag"]: i for i, c in enumerate(plan)}

    labels = [int(l) for l in labels]
    # Les cibles RÉELLEMENT présentes dans cette séance — un sous-ensemble du plan complet si la
    # calibration a été interrompue. `RCCAModel` DOIT être construit sur CES codes-là (voir le
    # ⚠️ ci-dessus), pas sur les `CVEP_N_TARGETS` du plan complet.
    presentes = sorted(set(labels))
    codes_vus = np.stack([codes[lag_a_idx[l]] for l in presentes])
    idx_local = {l: i for i, l in enumerate(presentes)}
    idx = [idx_local[l] for l in labels]     # RCCAModel indexe ses cibles 0..n-1, pas par lag

    ecca = CVEPModel(fs=fs, refresh=refresh, code_len=len(code), band=band, channels=channels)
    rcca = RCCAModel(codes_vus, fs=fs, refresh=refresh, band=band, channels=list(ecca.channels))

    # Réduits UNE fois, puis donnés aux DEUX décodeurs — c'est cette identité qui garantit
    # « les mêmes époques », pas une conviction qu'elles seront construites pareil deux fois.
    epochs_ecca = [np.asarray(e, dtype=float)[:, ecca.channels] for e in epochs]
    epochs_rcca = epochs_ecca
    for nom, mdl, ep in (("eCCA", ecca, epochs_ecca), ("rCCA", rcca, epochs_rcca)):
        largeur = int(np.asarray(ep[0]).shape[1]) if len(ep) else None
        if largeur != len(mdl.channels):
            raise ValueError(
                f"{nom} : {len(ep)} époques à {largeur} voies pour {len(mdl.channels)} voies "
                f"déclarées ({mdl.channels}) — la comparaison ne serait pas honnête")

    n_epoques_ecca = _fit_et_compte(ecca, epochs_ecca, labels)
    n_epoques_rcca = _fit_et_compte(rcca, epochs_rcca, idx, compute_cv=False)   # cv_ ci-dessous

    groupes = groupes_de_cycles(labels, n_cycles)
    sc_e, y_e, _ = ecca.hors_pli(epochs_ecca, labels, n_cycles=n_cycles)
    sc_r, y_r = rcca.hors_pli(epochs_rcca, idx, n_cycles=n_cycles)
    ecca.cv_ = float((sc_e.argmax(axis=1) == y_e).mean()) if len(y_e) else None
    rcca.cv_ = float((sc_r.argmax(axis=1) == y_r).mean()) if len(y_r) else None
    # ⚠️ `groupes_de_cycles` peut rendre AUCUN groupe à la géométrie `n_cycles` (une séance trop
    # courte, ou — mesuré — le protocole `--smoke` d'origine, dont les blocs interrompaient
    # systématiquement toute paire de cycles consécutifs). `hors_pli` rend alors un tableau de
    # score VIDE en 1 dimension (`shape == (0,)`), et `.shape[1]` lèverait un `IndexError` au lieu
    # de dire proprement « rien à mesurer à cette géométrie ». `len(presentes)` reste le nombre
    # d'alternatives VISÉES par la comparaison (identique pour les deux, par construction) même
    # quand aucune décision n'a pu être notée.
    n_cibles_e = int(sc_e.shape[1]) if sc_e.ndim > 1 else len(presentes)
    n_cibles_r = int(sc_r.shape[1]) if sc_r.ndim > 1 else len(presentes)

    return {
        "eCCA": {"modele": ecca, "justesse": ecca.cv_, "n_epoques": n_epoques_ecca,
                 "groupes": groupes, "n_decisions": len(sc_e), "n_cibles": n_cibles_e},
        "rCCA": {"modele": rcca, "justesse": rcca.cv_, "n_epoques": n_epoques_rcca,
                 "groupes": groupes, "n_decisions": len(sc_r), "n_cibles": n_cibles_r},
    }


def _gagnant(res):
    """Le nom du décodeur qui gagne sur la justesse hors-pli, ou `None` en cas d'ÉGALITÉ EXACTE
    — le cas réellement mesuré sur la seule séance disponible (43/90 chacun, cf.
    `core/cvep_rcca.py`). Pure, sans effet de bord : testable sans casque ni pygame."""
    e, r = res["eCCA"]["justesse"], res["rCCA"]["justesse"]
    if e is None or r is None or e == r:
        return None
    return "eCCA" if e > r else "rCCA"


def _draw(app, plan, spots, frame, target, done, total, b_idx, n_blocks):
    """Rendu d'une frame : toutes les cibles clignotent, celle à fixer est cerclée."""
    app.win.fill(BG)
    app.draw_ring(plan, spots, lambda c, f: is_on(f, c["code"]), frame, cue=target["name"])
    app.center(app.big, f"FIXE la cible {target['name']}", FG, 52)
    app.center(app.mid, f"bloc {b_idx}/{n_blocks}  —  cycle {done}/{total}",
               GO if done else WARN, 100)
    app.hud("ESC = annuler")
    app.pygame.display.flip()


def chemin_modele_horodate(decodeur, dossier=None):
    """`cvep_model_AAAAMMJJ-HHMMSS.npz` (eCCA) ou `cvep_rcca_model_AAAAMMJJ-HHMMSS.npz` (rCCA) —
    un fichier NEUF, jamais un écrasement.

    ⚠️ **`calibrate()` écrivait par défaut dans `CVEP_MODEL_PATH` / `CVEP_RCCA_MODEL_PATH`, des
    noms FIXES : la calibration suivante EFFAÇAIT donc la précédente.** `data/cvep_rcca_model.npz`
    est la trace du 2026-07-21 (35,6 %, codes Gold) que ce chantier cite comme preuve du jeu égal
    eCCA/rCCA (`core/cvep_rcca.py`) — et une revue a mesuré qu'une exécution de smoke mal câblée
    suffisait à l'écraser (incident documenté dans le rapport de tâche 6). Le P300 et l'ErrP
    avaient déjà cette parade (`research.p300_calibrate.chemin_modele_horodate`,
    `research.errp_calibrate.chemin_modele_horodate`) ; le c-VEP ne l'avait pas reprise.

    `core.cvep_models.MOTIFS` liste déjà les fichiers `cvep_model*.npz` / `cvep_rcca_model*.npz`
    du plus récent au plus ancien : le moteur, la console et les applis pygame prennent donc
    automatiquement le dernier calibré, sans rien à changer côté lecture.
    """
    if decodeur not in ("eCCA", "rCCA"):
        raise ValueError(f"décodeur inconnu : {decodeur!r} (attendu 'eCCA' ou 'rCCA')")
    dossier = os.path.dirname(CVEP_MODEL_PATH) if dossier is None else dossier
    prefixe = "cvep_model" if decodeur == "eCCA" else "cvep_rcca_model"
    return os.path.join(dossier, f"{prefixe}_{time.strftime('%Y%m%d-%H%M%S')}.npz")


def calibrate(app, cycles=CVEP_CAL_CYCLES, save_path=None, rcca_save_path=None):
    """Enregistre, entraîne les DEUX décodeurs (eCCA et rCCA, `entraine_les_deux`), sauvegarde
    les deux modèles, affiche les deux justesses et NOMME le gagnant. Retourne (ok, res|None) où
    `res` est le dict rendu par `entraine_les_deux`.

    `save_path=None` / `rcca_save_path=None` -> des fichiers HORODATÉS, jamais `CVEP_MODEL_PATH` /
    `CVEP_RCCA_MODEL_PATH` : voir `chemin_modele_horodate`.
    """
    save_path = save_path or chemin_modele_horodate("eCCA")
    rcca_save_path = rcca_save_path or chemin_modele_horodate("rCCA")
    plan, code = build_targets()
    L = len(code)
    spots = app.ring_spots(plan)
    acq = app.acq
    model = CVEPModel(fs=acq.fs, refresh=app.refresh, code_len=L)
    # On ENREGISTRE les 8 voies (rien n'est perdu, on pourra chercher le meilleur sous-ensemble
    # hors ligne) mais on n'AJUSTE que sur `model.channels` — donner 8 voies à une CCA calibrée
    # sur peu de cycles surapprend.
    rows = acq.eeg_rows
    epoch_s = model.n_cyc / acq.fs
    if app.smoke:
        # ⚠️ PAS `cycles = 2` : avec `CVEP_CAL_BLOCKS = 3` blocs, `_make_blocks` aurait alors donné
        # à CHAQUE bloc UN SEUL cycle (`per = max(1, 2 // 3) = 1`), jamais deux CONSÉCUTIFS — donc
        # `groupes_de_cycles(labels, k=2)`, la géométrie de DÉCISION DU MOTEUR (tâche 6), ne
        # trouvait de paire que si le mélange des blocs en plaçait deux du MÊME bloc côte à côte
        # par CHANCE. Mesuré : 3 échecs sur 5 lancements (`IndexError`, un tableau de scores VIDE
        # n'a qu'UNE dimension). `cycles = 6` fait que CHAQUE bloc porte 2 cycles consécutifs
        # (`per = max(1, 6 // 3) = 2`), donc au moins une paire par bloc, quel que soit le mélange.
        cycles = 6

    blocks = _make_blocks(plan, cycles, CVEP_CAL_BLOCKS)
    gap = cvep_lag_gap_ms(len(plan), L, app.refresh)
    n_blk = len(blocks)
    est = (len(plan) * cycles + n_blk * SETTLE_CYCLES) * L / app.refresh / 60.0 + n_blk * 1.8 / 60.0
    print(f"[cvep-cal] code L={L} @ {app.refresh:.0f}Hz -> cycle {L/app.refresh:.2f}s "
          f"({model.n_cyc} éch.)  8 voies enregistrées, ajustement sur {model.channels}")
    print(f"[cvep-cal] {len(plan)} cibles, écart entre lags {gap:.0f} ms"
          + ("" if gap >= 150 else "  ⚠️ < durée VEP ~150 ms : cibles voisines confusables"))
    print(f"[cvep-cal] {cycles} cycles/cible, {n_blk} blocs entrelacés (ordre mélangé) "
          f" ≈ {est:.1f} min")
    if not _briefing(app):
        return False, None
    # liaison casque vérifiée AVANT d'investir 3,4 min ; voies clés (occipitales) encadrées
    if not app.signal_check(highlight=CVEP_CHANNELS, mode_label="c-VEP"):
        return False, None

    epochs, lags = [], []
    check_at = max(1, int(round(n_blk * 0.4)))   # bloc où se déclenche le contrôle de séance
    got_by_lag = {c["lag"]: 0 for c in plan}
    frame, prev_phase = 0, -1
    settle = 0 if app.smoke else SETTLE_CYCLES
    try:
        for b_idx, (target, n_cyc) in enumerate(blocks, start=1):
            # Surveillance en cours de séance : une liaison qui lâche au bloc 3 produirait
            # sinon 3 minutes de signal plat, puis un modèle à 0 % sans le moindre indice.
            if not app.smoke:
                _, qrows, _ = app.signal_ok(0.5)
                dead = [n for n, _, v in qrows if v == "morte"]
                if dead:
                    print(f"[cvep-cal] ⛔ LIAISON PERDUE (voies plates : {', '.join(dead)}) "
                          f"au bloc {b_idx}/{len(blocks)} — arrêt, rien n'est entraîné.")
                    print("[cvep-cal] vérifie le câble du casque, les électrodes et les mastoïdes.")
                    app.flash("Liaison casque perdue",
                              f"voies plates : {', '.join(dead)} — vérifie le câble", 4.0)
                    return False, None
            got, skip, start = 0, settle, frame
            while got < n_cyc:
                app.drain()
                phase = frame % L
                # frontière de cycle : la fenêtre qui précède couvre un cycle entier depuis la phase 0
                if phase == 0 and prev_phase != 0:
                    if skip > 0:
                        skip -= 1
                    else:
                        ep = acq.get_epoch(epoch_s, rows=rows, filtered=False)
                        if ep is not None and len(ep) >= model.n_cyc:
                            epochs.append(ep[:model.n_cyc])
                            lags.append(target["lag"])
                            got += 1
                            got_by_lag[target["lag"]] += 1
                prev_phase = phase
                _draw(app, plan, spots, frame, target, got, n_cyc, b_idx, len(blocks))
                app.clock.tick(int(app.refresh) + 5)
                frame += 1
                # garde-fou headless : borne le temps passé par bloc sans fausser le compte
                if app.smoke and (frame - start) > (n_cyc + settle + 2) * L:
                    break
            print(f"[cvep-cal] bloc {b_idx}/{len(blocks)} {target['name']:<10} "
                  f"lag={target['lag']:>3} : {got} cycles", flush=True)
            # Garde-fou de séance : une fois seulement, à ~40 % du parcours (assez d'époques
            # pour que le LOO ait un sens, assez tôt pour que l'abandon fasse gagner du temps).
            if b_idx == check_at and not app.smoke:
                verdict = _early_check(model, epochs, lags, len(plan))
                if verdict is not None:
                    bad, acc, hi_itr = verdict
                    print(f"[cvep-cal] contrôle à mi-parcours ({len(epochs)} cycles) : "
                          f"LOO {acc*100:.0f}% (hasard {100.0/len(plan):.0f}%)  ->  au MIEUX "
                          f"{hi_itr:.1f} bits/min"
                          + (f"  ⚠️ SOUS LE PLANCHER D'UTILITÉ ({EARLY_ITR_MIN:.0f})" if bad
                             else "  -> on continue"), flush=True)
                    if bad:
                        app.flash("Séance mal engagée",
                                  f"au mieux {hi_itr:.0f} bits/min — ESC pour arrêter "
                                  f"(le déjà-enregistré est conservé)", 6.0)
            if b_idx < len(blocks):
                # inter-bloc = point de PAUSE sûr (époques du bloc déjà ramassées, le settle du
                # bloc suivant absorbe le redémarrage) -> ESPACE met en pause pendant cet écran
                app.flash("Change de cible",
                          f"prépare-toi à fixer {blocks[b_idx][0]['name']}   ·   Espace = pause",
                          1.8, skippable=False, pausable=True)
    except Abort:
        print("[cvep-cal] interrompu — entraînement sur ce qui est déjà enregistré.")
    print("[cvep-cal] cycles par cible : "
          + "  ".join(f"{c['name']}={got_by_lag[c['lag']]}" for c in plan))

    if len(set(lags)) < 2 or len(epochs) < 4:
        print("[cvep-cal] pas assez de données pour entraîner.")
        return False, None

    # Les DEUX décodeurs, sur les MÊMES époques : « lequel est meilleur pour CETTE personne ? »
    # ne se répond que si la calibration entraîne les deux (cf. la docstring d'entraine_les_deux
    # et celle de core/cvep_rcca.py — mesuré une fois, 43/90 chacun : un jeu parfaitement égal).
    res = entraine_les_deux(epochs, lags, fs=acq.fs, refresh=app.refresh)
    ecca, rcca = res["eCCA"]["modele"], res["rCCA"]["modele"]
    ecca.save(save_path, n_targets=len(plan))
    rcca.save(rcca_save_path)
    if not app.smoke:
        # ⚠️ ARCHIVER, ne jamais écraser : dans un projet d'exploration les jeux de données SONT
        # le résultat. Une version antérieure n'écrivait que « cvep_calib_last.npz » et la
        # meilleure séance (27,1 bits/min) a été perdue à la calibration suivante — impossible
        # de comparer les amplitudes pour diagnostiquer l'effondrement.
        data = dict(epochs=np.asarray(epochs), lags=np.asarray(lags), fs=acq.fs,
                    refresh=app.refresh, n_targets=len(plan), rotation=CVEP_LAG_ROTATION,
                    channels=np.asarray(model.channels, dtype=int),   # voies AJUSTÉES
                    ch_names=np.asarray(CH_NAMES),                    # les 8 ENREGISTRÉES
                    sigma=float(np.asarray(epochs).std()))
        folder = os.path.dirname(save_path)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        archive = os.path.join(
            folder, f"cvep_calib_{stamp}_n{len(plan)}_rot{CVEP_LAG_ROTATION}.npz")
        np.savez(archive, **data)
        np.savez(os.path.join(folder, "cvep_calib_last.npz"), **data)   # raccourci d'analyse
        print(f"[cvep-cal] données archivées : {os.path.basename(archive)}")

    # Avec N cibles variable, l'accuracy brute n'est plus comparable d'une config à l'autre
    # (70% sur 6 cibles vaut bien plus que 70% sur 3). On rapporte donc l'ITR, l'échelle qui
    # combine nombre de choix, justesse et vitesse — cf. itr.py. Un ITR par décodeur : ils n'ont
    # aucune raison de dégrader à la même vitesse.
    from research.itr import itr as _itr
    cv_e, cv_r = res["eCCA"]["justesse"], res["rCCA"]["justesse"]
    chance = 100.0 / len(plan)
    cycle_s = L / app.refresh
    bits_e = _itr(len(plan), cv_e or 0.0, cycle_s)
    bits_r = _itr(len(plan), cv_r or 0.0, cycle_s)
    meilleur = max(bits_e, bits_r)
    ref = _itr(3, 0.95, 1.5)   # SSVEP actuel = la barre à battre
    nom_gagnant = _gagnant(res) or "égalité"
    verdict = ("DÉPASSE LE SSVEP" if meilleur >= ref else
               "PROMETTEUR" if meilleur >= ref / 2 else
               "FAIBLE (contact électrodes ? regard qui décroche ? refais un essai)")
    print(f"[cvep-cal] {len(epochs)} cycles sur {len(plan)} cibles (hasard {chance:.0f}%) :")
    print(f"[cvep-cal]   eCCA  leave-one-out {cv_e*100:5.1f}%  -> {bits_e:5.1f} bits/min")
    print(f"[cvep-cal]   rCCA  leave-one-out {cv_r*100:5.1f}%  -> {bits_r:5.1f} bits/min")
    print(f"[cvep-cal] gagnant : {nom_gagnant}   —   SSVEP de référence {ref:.1f} -> {verdict}")
    print(f"[cvep-cal] `python src/research/cvep_analyze.py` pour le gain en moyennant plusieurs cycles.")
    print(f"[cvep-cal] modèles sauvegardés : {save_path} (eCCA)  ·  {rcca_save_path} (rCCA)")

    t0 = time.perf_counter()
    while time.perf_counter() - t0 < (0.1 if app.smoke else 5.0):
        try:
            app.drain(on_key=lambda e: None)
        except Abort:
            break
        app.win.fill(BG)
        h = app.win.get_height()
        app.center(app.big, f"eCCA {cv_e*100:.0f}%   ·   rCCA {cv_r*100:.0f}%", FG, int(h * 0.34))
        app.center(app.mid, f"gagnant : {nom_gagnant}", GO, int(h * 0.44))
        app.center(app.mid, f"{meilleur:.0f} bits/min (meilleur des deux)   —   SSVEP réf. {ref:.0f}",
                   GO if meilleur >= ref / 2 else WARN, int(h * 0.53))
        app.center(app.small, verdict, DIM, int(h * 0.62))
        app.center(app.small, "modèles sauvegardés (eCCA et rCCA) — ESC pour continuer",
                   DIM, int(h * 0.70))
        app.pygame.display.flip()
        app.clock.tick(60)
    return meilleur >= ref / 2, res


# --- Autotest (aucun casque, c-VEP synthétique) ------------------------------

def _selftest():
    """La comparaison honnête eCCA/rCCA (tâche 6) : mêmes époques, mêmes groupes de validation
    croisée, un gagnant nommé — et les deux chiffres survivent à un aller-retour sur disque.
    Aucun casque, aucune donnée réelle."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    from core.cvep_decoder import synth_cvep

    # 8 voies BRUTES (comme l'Unicorn), réduites à 4 AJUSTÉES (comme CVEP_CHANNELS) : la
    # distinction compte pour le garde de largeur de voies (Important 6 de la revue) — un
    # fixture qui générerait directement des époques à 4 voies ne pourrait jamais faire diverger
    # « brut » et « réduit », et le garde resterait invérifiable.
    fs, refresh, n_raw, voies = 250.0, 60.0, 8, [4, 5, 6, 7]
    rng = np.random.default_rng(0)
    plan, code = build_targets()
    epochs, labels = [], []
    for c in plan:
        for _ in range(8):
            epochs.append(synth_cvep(code, c["lag"], n_raw, fs, refresh, -6.0, rng))
            labels.append(c["lag"])

    # --- LE test de cette tâche : la comparaison est honnête. ---------------------------------
    # Les deux décodeurs s'ajustent sur les MÊMES époques, en validation croisée groupée. Comparer
    # deux protocoles différents ne dirait rien ; c'est tout l'intérêt d'avoir gardé le stimulus
    # identique (cf. `core/cvep_rcca.py`, docstring du module).
    res = entraine_les_deux(epochs, labels, fs=fs, refresh=refresh, channels=voies)
    chk(set(res) == {"eCCA", "rCCA"}, f"les deux décodeurs sont entraînés ({sorted(res)})")
    chk(res["eCCA"]["n_epoques"] == res["rCCA"]["n_epoques"] == len(labels),
        f"...sur le MÊME nombre d'époques — sinon la comparaison ne veut rien dire "
        f"({res['eCCA']['n_epoques']}, {res['rCCA']['n_epoques']}, {len(labels)})")
    chk(res["eCCA"]["groupes"] == res["rCCA"]["groupes"],
        f"...et les mêmes groupes de validation croisée ({len(res['eCCA']['groupes'])} vs "
        f"{len(res['rCCA']['groupes'])} groupes)")
    # ⚠️ Ce contrôle est ce qui empêche « groupes » d'être décoratif : il compare ce que CHAQUE
    # décodeur a RÉELLEMENT noté (la longueur de son propre `hors_pli`) au nombre de groupes
    # annoncé. Si un futur appel passait un `n_cycles` différent à un seul des deux `hors_pli`
    # (l'asymétrie déjà trouvée ailleurs dans ce chantier, cf. `RCCADecoder.n_cycles`), ce
    # décodeur noterait un nombre de groupes différent de celui annoncé — silencieusement, sans
    # ce contrôle. Preuve par mutation dans le rapport de tâche.
    chk(res["eCCA"]["n_decisions"] == res["rCCA"]["n_decisions"] == len(res["eCCA"]["groupes"]),
        f"...et chaque décodeur a RÉELLEMENT noté autant de groupes qu'annoncé — sinon deux "
        f"géométries différentes se compareraient sans qu'aucun message ne le dise "
        f"({res['eCCA']['n_decisions']}, {res['rCCA']['n_decisions']}, "
        f"{len(res['eCCA']['groupes'])})")
    chk(res["eCCA"]["n_cibles"] == res["rCCA"]["n_cibles"] == len(plan),
        f"...et les deux décodeurs jugent parmi le MÊME nombre d'alternatives — ici les "
        f"{len(plan)} du plan complet ({res['eCCA']['n_cibles']}, {res['rCCA']['n_cibles']})")
    chk(0.0 <= res["eCCA"]["justesse"] <= 1.0 and 0.0 <= res["rCCA"]["justesse"] <= 1.0,
        f"...et chacun rend une justesse HORS-PLI, dans [0, 1] ({res['eCCA']['justesse']}, "
        f"{res['rCCA']['justesse']})")
    chk(res["eCCA"]["modele"].decoder == "eCCA" and res["rCCA"]["modele"].decoder == "rCCA",
        "...et chaque modèle SAIT quel décodeur il est (le champ que `save` écrit)")

    # --- Important 4 (revue) : la géométrie de MESURE est celle où le moteur DÉCIDE. ----------
    import inspect
    defaut_k = inspect.signature(entraine_les_deux).parameters["n_cycles"].default
    chk(defaut_k == CVEP_DECISION_CYCLES,
        f"la comparaison mesure par défaut à la géométrie de DÉCISION DU MOTEUR "
        f"(CVEP_DECISION_CYCLES={CVEP_DECISION_CYCLES}), pas à celle d'une époque de calibration "
        f"seule où k=1 masquerait un écart réel entre les deux décodeurs ({defaut_k})")

    # --- Critical 2 (revue) : la calibration du menu n'écrit plus JAMAIS le nom FIXE par défaut.
    # Vérifié sur le TEXTE SOURCE et pas en l'exécutant : appeler `calibrate(app)` sans chemin
    # pour voir où il écrit, c'est exactement l'accident qu'on veut interdire (celui qui a détruit
    # le modèle Gold du 21 juillet lors d'un smoke mal câblé — cf. le rapport de tâche 6).
    src_cal = inspect.getsource(calibrate)
    chk('chemin_modele_horodate("eCCA")' in src_cal and 'chemin_modele_horodate("rCCA")' in src_cal
        and "save_path=CVEP_MODEL_PATH" not in src_cal
        and "rcca_save_path=CVEP_RCCA_MODEL_PATH" not in src_cal,
        "calibrate() retombe sur des chemins HORODATÉS quand on ne lui en donne pas — jamais sur "
        "CVEP_MODEL_PATH / CVEP_RCCA_MODEL_PATH en dur dans sa signature")
    chemin_e_h = chemin_modele_horodate("eCCA")
    chemin_r_h = chemin_modele_horodate("rCCA")
    chk(chemin_e_h != CVEP_MODEL_PATH and chemin_r_h != CVEP_RCCA_MODEL_PATH,
        f"...et ces chemins horodatés ne sont VRAIMENT jamais les noms fixes ({chemin_e_h}, "
        f"{chemin_r_h})")
    import fnmatch

    from core.cvep_models import MOTIFS
    chk(fnmatch.fnmatch(os.path.basename(chemin_e_h), MOTIFS[0])
        and fnmatch.fnmatch(os.path.basename(chemin_r_h), MOTIFS[1])
        and not fnmatch.fnmatch(os.path.basename(chemin_r_h), MOTIFS[0]),
        f"...et ils restent VUS par cvep_models (motifs {MOTIFS}), chacun sous SON motif "
        f"({os.path.basename(chemin_e_h)}, {os.path.basename(chemin_r_h)})")
    chk(os.path.dirname(chemin_modele_horodate("eCCA", dossier="/tmp/xyz_cvep_test")) ==
        "/tmp/xyz_cvep_test",
        "...et un `dossier` explicite est respecté, pas toujours celui de CVEP_MODEL_PATH — "
        "c'est ce détour qu'un test ou un smoke doit prendre pour ne jamais écrire dans data/")

    # --- Critical 1 (revue) : une séance INTERROMPUE ne doit PAS fausser le hasard. -----------
    # Tronquée à 3 cibles sur 6 (le cas d'un ESC en cours d'enregistrement, cf. `Abort` dans
    # `calibrate()`) : SANS restreindre les codes du rCCA aux cibles VUES, il resterait jugé sur
    # 1/6 (hasard 16,7 %) quand eCCA rétrécit correctement à 1/3 (33,3 %) — c'est EXACTEMENT ce
    # qui a produit « gagnant : eCCA » sur des points offerts par le hasard, pas par le signal
    # (mesuré par la revue sur une séance réelle tronquée : 71,1 % contre 51,1 %).
    trois = plan[:3]
    epochs3, labels3 = [], []
    for c in trois:
        for _ in range(8):
            epochs3.append(synth_cvep(code, c["lag"], n_raw, fs, refresh, -6.0, rng))
            labels3.append(c["lag"])
    res3 = entraine_les_deux(epochs3, labels3, fs=fs, refresh=refresh, channels=voies)
    chk(res3["eCCA"]["n_cibles"] == res3["rCCA"]["n_cibles"] == 3,
        f"une séance tronquée à 3 cibles sur 6 juge les DEUX décodeurs parmi 3 alternatives, "
        f"jamais 6 pour l'un et 3 pour l'autre ({res3['eCCA']['n_cibles']}, "
        f"{res3['rCCA']['n_cibles']})")
    chk(res3["rCCA"]["modele"].n_targets == 3,
        f"...et le modèle rCCA sauvegardé porte VRAIMENT 3 codes, pas les 6 du plan complet "
        f"({res3['rCCA']['modele'].n_targets})")

    # --- Le gagnant nommé, et l'ÉGALITÉ EXACTE — le cas mesuré sur la seule séance réelle. -----
    chk(_gagnant({"eCCA": {"justesse": 0.7}, "rCCA": {"justesse": 0.3}}) == "eCCA",
        "le décodeur le plus juste est nommé gagnant")
    chk(_gagnant({"eCCA": {"justesse": 0.3}, "rCCA": {"justesse": 0.7}}) == "rCCA",
        "...dans les deux sens")
    chk(_gagnant({"eCCA": {"justesse": 0.478}, "rCCA": {"justesse": 0.478}}) is None,
        "...et une ÉGALITÉ EXACTE (43/90 chacun, le cas réellement mesuré, cf. core/cvep_rcca.py) "
        "ne nomme PERSONNE plutôt que de trancher arbitrairement")

    # --- Important 6 (revue) : « les mêmes époques » n'était vérifié que par un compte tautologique.
    # `_fit_et_compte` est le mécanisme qui rend `n_epoques` non-décoratif : il DOIT compter
    # l'ARGUMENT réellement passé à `.fit()`, jamais une longueur recalculée à côté (qui, elle,
    # ne verrait PAS un futur tronquage inline comme `epochs[:-6]`).
    class _ModeleFactice:
        def __init__(self):
            self.vu = None

        def fit(self, epochs, labels, **kw):
            self.vu = (list(epochs), list(labels), kw)

    mf = _ModeleFactice()
    n_a = _fit_et_compte(mf, [1, 2, 3], ["a", "b", "c"], compute_cv=False)
    chk(n_a == 3 and mf.vu == ([1, 2, 3], ["a", "b", "c"], {"compute_cv": False}),
        f"_fit_et_compte ajuste EXACTEMENT ce qu'on lui donne, mots-clés compris ({n_a}, {mf.vu})")
    n_b = _fit_et_compte(mf, [1, 2, 3], ["a", "b"])
    chk(n_b == 3,
        f"...et il compte les ÉPOQUES qu'il a reçues, pas les étiquettes — sinon un tronquage "
        f"appliqué à un seul des deux côtés (epochs OU labels) pourrait passer inaperçu ({n_b})")

    # --- Les deux chiffres ET le champ `decoder` partent dans le fichier de modèle. ------------
    import shutil
    import tempfile

    from core.cvep_models import charger
    from core.cvep_rcca import RCCADecoder

    tmp = tempfile.mkdtemp(prefix="cvep_calibrate_selftest_")
    try:
        chemin_e = res["eCCA"]["modele"].save(os.path.join(tmp, "cvep_model.npz"),
                                              n_targets=len(plan))
        chemin_r = res["rCCA"]["modele"].save(os.path.join(tmp, "cvep_rcca_model.npz"))
        relu_e, pb_e = charger(chemin_e)
        relu_r, pb_r = charger(chemin_r)
        chk(relu_e is not None and pb_e is None and relu_e.decoder == "eCCA"
            and abs(relu_e.cv_ - res["eCCA"]["justesse"]) < 1e-12,
            f"le modèle eCCA sauvegardé se relit, décodeur et justesse compris ({pb_e})")
        chk(relu_r is not None and pb_r is None and relu_r.decoder == "rCCA"
            and abs(relu_r.cv_ - res["rCCA"]["justesse"]) < 1e-12,
            f"...et le modèle rCCA aussi ({pb_r})")

        # --- Critical 3 (revue) : l'appariement lag -> ligne de code n'était vérifié par RIEN. -
        # La JUSTESSE seule ne suffit pas : un décalage SYSTÉMATIQUE (chaque époque appariée à
        # la cible VOISINE) reste interne cohérent — le classifieur apprend « code[i+1] pour la
        # réponse à la cible i » et `hors_pli` le note avec le MÊME décalage, donc juste EN
        # AVEUGLE (mesuré par la revue : +1 % len(plan) -> justesse 1,0/1,0, VERDICT OK). Seul un
        # contrôle EXTERNE — quelle cible le modèle sauvegardé désigne-t-il RÉELLEMENT ? — le voit.
        cible_connue = 4
        # DÉJÀ réduite aux voies AJUSTÉES (comme le fait `_cvep_decode` en ligne, avant d'appeler
        # `classify` : `dec.model.channels` sélectionne, `RCCAModel.scores` ne réduit rien lui-même).
        fenetre_connue = synth_cvep(code, plan[cible_connue]["lag"], len(voies), fs, refresh,
                                    -6.0, rng)
        dec = RCCADecoder(relu_r, plan, corr_min=-1e9, margin=0.0, n_cycles=1)
        choisi, _ = dec.classify(fenetre_connue, 0)
        chk(choisi is not None and choisi["name"] == plan[cible_connue]["name"],
            f"le modèle rCCA sauvegardé-puis-relu désigne la cible RÉELLEMENT affichée, pas sa "
            f"voisine ({None if choisi is None else choisi['name']} au lieu de "
            f"{plan[cible_connue]['name']}) — un décalage systématique de l'appariement lag -> "
            f"ligne de code resterait invisible à la seule justesse hors-pli")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"[cvep-calibrate] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if _selftest() else 1)
