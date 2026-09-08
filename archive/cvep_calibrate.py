"""Calibration c-VEP pygame — l'écran de CALIBRATION retiré de l'appli unifiée.

Ce fichier vivait dans `src/research/`, appelé depuis la page « c-VEP » de `src/research/app.py`,
supprimé le 2026-09-08. C'est le MOTEUR qui calibre désormais : la console lance
`src/stimulus/cvep.py --calibrer`, le moteur écoute l'horloge du stimulus et entraîne
(`core/modes/cvep_calib.py`), puis la console AFFICHE le résultat avant de demander « Refaire /
Enregistrer ». Cet écran-ci, lui, écrit son modèle DIRECTEMENT dans `data/` sans passer par ce
garde — c'est exactement pourquoi il n'est plus au menu de rien.

Gardé ici, ENCORE EXÉCUTABLE, pour deux raisons : c'est la référence contre laquelle la calibration
du moteur a été écrite (même protocole, mêmes blocs entrelacés, même entraînement — il APPELLE
`core/modes/cvep_calib.entraine_les_deux`, il n'en a pas de copie), et c'est le seul chemin qui
existe encore vers un modèle si le montage à deux processus (moteur + fenêtre) est indisponible.

⚠️ Son ÉPOCHAGE reste différent de celui du moteur, et ce n'est pas un détail : il découpe sur
l'horloge de pygame (frontières de cycle comptées en frames), le moteur sur les marqueurs LSL. Pour
une séance sérieuse, passer par la console.

⚠️ Ne jamais le lancer en même temps que le moteur, la console ou un autre écran archivé : le casque
n'accepte qu'UNE connexion.

    python archive/cvep_calibrate.py                   # plein écran, casque réel
    python archive/cvep_calibrate.py --windowed
    python archive/cvep_calibrate.py --model data/mon_ecca.npz --rcca-model data/mon_rcca.npz
    python archive/cvep_calibrate.py --synthetic       # sans casque (board de test BrainFlow)
    python archive/cvep_calibrate.py --smoke           # autotest headless (CI)

Le protocole, inchangé depuis l'appli :

Plus courte que la calibration Motor Imagery (~3 min contre 5-7 min) parce qu'on n'apprend pas
une intention mentale, seulement la **forme de ta réponse visuelle** au code. ⚠️ La durée exacte
est CALCULÉE et imprimée au lancement (`≈ X.X min`, cf. `calibrate`) : aux réglages du dépôt
(6 cibles × `CVEP_CAL_CYCLES`=15 cycles, `CVEP_CAL_BLOCKS`=3 → 18 blocs entrelacés) elle vaut
**≈ 2,7 min**, hors briefing et hors contrôle de liaison. Le « ~1 min » qui traînait dans la doc
datait d'un réglage antérieur.

Déroulé : les 3 cibles clignotent en permanence avec le même code décalé ; on te demande
d'en fixer une, et on enregistre `CVEP_CAL_CYCLES` cycles complets. On recommence pour
chaque cible. Enregistrer les 3 (plutôt qu'une seule) coûte le même temps total et vérifie
en prime que l'alignement des lags est bon (l'accuracy leave-one-out le dit).

Chaque époque est prélevée EXACTEMENT à une frontière de cycle (frame % L == 0) : la
fenêtre couvre alors le cycle qui vient de s'écouler, donc démarre à la phase 0 du code.
"""

import argparse
import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))      # -> src/
from core.config import (CH_NAMES, CVEP_CAL_BLOCKS, CVEP_CAL_CYCLES,  # noqa: E402
                    DATA_DIR, empreinte_dossier,
                    CVEP_CHANNELS, CVEP_DECISION_CYCLES, CVEP_LAG_ROTATION,
                    CVEP_MODEL_PATH, CVEP_RCCA_MODEL_PATH, cvep_lag_gap_ms,
                    use_utf8_console)
from core.cvep_code import blocs_entrelaces, build_targets, is_on  # noqa: E402
from core.cvep_decoder import CVEPModel  # noqa: E402
# ⚠️ `_mcnemar_p` et `SEUIL_MCNEMAR` sont NÉS ici (commit `bd3b588`) et ont DÉMÉNAGÉ dans `core/` :
# `core/cvep_rcca.py::_rejouer` (la commande `--seuils`) en a besoin lui aussi, et `core/`
# n'importe JAMAIS `research/`. La règle du dépôt dit exactement quoi faire dans ce cas — le module
# visé déménage. Importés ici pour que l'écran continue d'appeler LE MÊME objet, pas une seconde
# copie qui divergerait un jour.
from core.cvep_rcca import SEUIL_MCNEMAR, _mcnemar_p  # noqa: E402
# ⚠️ **TOUTE LA MOITIÉ « ENTRAÎNEMENT » DE CE FICHIER A DÉMÉNAGÉ**, chantier « la console, seul
# point d'entrée » (tâche 8), pour exactement la même raison que `_mcnemar_p` avant elle : c'est
# désormais le MOTEUR qui entraîne le c-VEP (`core/modes/cvep_calib.py`, depuis les marqueurs de
# `src/stimulus/cvep.py`), et `core/` n'importe jamais `research/`. Ce qui reste ici est la moitié
# PYGAME — enregistrer des cycles au fil d'un écran que cette appli dessine elle-même.
# Ré-importées et non recopiées : deux comparaisons eCCA/rCCA, chacune avec ses propres tests,
# finiraient par diverger sans que rien ne le dise.
from core.modes.cvep_calib import (chemin_modele_horodate,  # noqa: E402
                                   entraine_les_deux, gagnant as _gagnant)
from research.itr import itr  # noqa: E402
from research.ui import App, BG, DIM, FG, GO, WARN, Abort  # noqa: E402

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
    """Le plan des blocs entrelacés — DÉLÈGUE à `core.cvep_code.blocs_entrelaces`.

    ⚠️ La règle a DÉMÉNAGÉ dans `core/` (chantier « la console, seul point d'entrée », tâche 8) :
    la fenêtre `src/stimulus/cvep.py` la joue elle aussi maintenant, et `stimulus` n'a pas le
    droit d'importer `research`. Deux exemplaires de la même règle de protocole finiraient par
    diverger sans que personne le voie. Ce passe-plat reste pour ne pas toucher `calibrate()`.
    """
    return blocs_entrelaces(plan, cycles, n_blocks, random)


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


def _draw(app, plan, spots, frame, target, done, total, b_idx, n_blocks):
    """Rendu d'une frame : toutes les cibles clignotent, celle à fixer est cerclée."""
    app.win.fill(BG)
    app.draw_ring(plan, spots, lambda c, f: is_on(f, c["code"]), frame, cue=target["name"])
    app.center(app.big, f"FIXE la cible {target['name']}", FG, 52)
    app.center(app.mid, f"bloc {b_idx}/{n_blocks}  —  cycle {done}/{total}",
               GO if done else WARN, 100)
    app.hud("ESC = annuler")
    app.pygame.display.flip()


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
    # liaison casque vérifiée AVANT d'investir les `est` minutes annoncées juste au-dessus (≈ 2,7
    # aux réglages du dépôt) ; voies clés (occipitales) encadrées
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
                    # ⚠️ « à 1 cycle » n'est pas décoratif : ce contrôle mesure et convertit à la
                    # géométrie d'UNE époque, alors que le chiffre final de la calibration est à
                    # `CVEP_DECISION_CYCLES`. Les deux ITR ne sont donc PAS sur la même échelle,
                    # et le plancher `EARLY_ITR_MIN` s'applique à celle-ci. Le dire ici, parce que
                    # c'est là que les deux chiffres se croisent sous les yeux de l'étudiant.
                    print(f"[cvep-cal] contrôle à mi-parcours ({len(epochs)} cycles, à 1 cycle "
                          f"par décision — PAS la géométrie du chiffre final) : "
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
    # ne se répond que si la calibration entraîne les deux (cf. la docstring d'entraine_les_deux et
    # celle de core/cvep_rcca.py — mesuré une fois, aucune différence DÉTECTABLE entre les deux,
    # McNemar p=0,73 sur 37 décisions ; ce qui n'est pas « ils se valent »).
    res = entraine_les_deux(epochs, lags, fs=acq.fs, refresh=app.refresh)
    ecca, rcca = res["eCCA"]["modele"], res["rCCA"]["modele"]
    n_cibles_vues = len(set(lags))
    # ⚠️ **`n_targets` = ce que la séance a RÉELLEMENT présenté, jamais `len(plan)`.** Le template
    # eCCA est COMMUN à tous les lags : un modèle entraîné sur 3 cibles « marche » techniquement à
    # 6 et publie six corrélations d'apparence normale, dont trois sortent de lags qu'aucun cerveau
    # n'a jamais vus. C'est exactement la panne invisible que `CVEPRuntime._desaccord_code` refuse
    # (« ce modèle a été calibré sur N cible(s), le stimulus actuel en affiche M ») — mais ce refus
    # ne peut mordre que si le fichier dit la VÉRITÉ sur lui-même. Écrire `len(plan)` ici rendait le
    # contrôle du moteur inopérant sur le seul cas qu'il vise, et l'asymétrie s'était creusée : le
    # rCCA d'une séance tronquée n'est plus écrit du tout, l'eCCA l'était en se déclarant complet.
    ecca.save(save_path, n_targets=n_cibles_vues)
    # ⚠️ **Une séance INTERROMPUE ne produit PAS de fichier rCCA, et le dire.** Le modèle rCCA
    # d'une séance à 3 cibles sur 6 porte 3 codes ; `core.cvep_models.charger` exige les codes du
    # stimulus AFFICHÉ (les 6, dans l'ordre du plan) et le refuse — donc le fichier n'apparaîtrait
    # jamais dans la liste de la console ni dans `modeles_disponibles`. Le sauvegarder quand même
    # annonçait « modèles sauvegardés : … (rCCA) » à l'étudiant, et pouvait même le nommer
    # gagnant : un succès affiché pour un artefact que rien ne peut charger. La COMPARAISON,
    # elle, reste valable (les deux décodeurs jugent parmi les mêmes cibles) et s'affiche.
    if n_cibles_vues == len(plan):
        rcca.save(rcca_save_path)
        ligne_sauvegarde = (f"modèles sauvegardés : {save_path} (eCCA)  ·  "
                            f"{rcca_save_path} (rCCA)")
    else:
        ligne_sauvegarde = (
            f"séance interrompue ({n_cibles_vues} cibles sur {len(plan)}) : modèle eCCA "
            f"sauvegardé ({save_path}) mais DÉCLARÉ à {n_cibles_vues} cibles — le moteur le "
            f"REFUSERA tant que le stimulus en affiche {len(plan)}, et il dira pourquoi. Modèle "
            f"rCCA NON sauvegardé : il porterait {n_cibles_vues} codes quand le stimulus en "
            f"affiche {len(plan)}, et `core.cvep_models.charger` le refuserait. La comparaison "
            f"ci-dessous reste valable ; recalibre en entier pour obtenir des modèles utilisables.")
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

    # ⚠️ À la géométrie de DÉCISION DU MOTEUR (CVEP_DECISION_CYCLES cycles), une séance trop
    # courte ou trop fragmentée peut ne fournir AUCUNE décision : `entraine_les_deux` le dit
    # explicitement (`justesse`/`n_cibles`/`corrects` à `None`), plutôt que de rendre un chiffre
    # d'apparence normale sur du vide. Fermer ce chemin ICI, avant tout calcul : c'est le
    # `TypeError` (`cv_e*100` sur un `None`) que le tour 2 de la revue a trouvé un cran plus loin.
    cv_e, cv_r = res["eCCA"]["justesse"], res["rCCA"]["justesse"]
    n_cibles = res["eCCA"]["n_cibles"]      # == res["rCCA"]["n_cibles"], garanti par construction
    if cv_e is None or cv_r is None or not n_cibles:
        print(f"[cvep-cal] {len(epochs)} cycles enregistrés, mais AUCUNE décision à la géométrie "
              f"du moteur ({CVEP_DECISION_CYCLES} cycles) — trop peu de cycles consécutifs de la "
              f"même cible pour en former une seule. Les modèles sont sauvegardés (le filtre "
              f"spatial et le classifieur existent), mais aucune justesse fiable ne les "
              f"accompagne : recalibre, avec davantage de cycles par cible si possible.")
        print(f"[cvep-cal] {ligne_sauvegarde}")
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < (0.1 if app.smoke else 5.0):
            try:
                app.drain(on_key=lambda e: None)
            except Abort:
                break
            app.win.fill(BG)
            h = app.win.get_height()
            app.center(app.big, "Pas assez de décisions", WARN, int(h * 0.40))
            app.center(app.mid, f"{len(epochs)} cycles enregistrés, aucune paire consécutive à "
                       f"la géométrie du moteur", DIM, int(h * 0.50))
            app.center(app.small, "modèles sauvegardés, mais sans justesse fiable — recalibre",
                       DIM, int(h * 0.58))
            app.pygame.display.flip()
            app.clock.tick(60)
        return False, res

    # Avec N cibles variable, l'accuracy brute n'est plus comparable d'une config à l'autre
    # (70% sur 6 cibles vaut bien plus que 70% sur 3). On rapporte donc l'ITR, l'échelle qui
    # combine nombre de choix, justesse et vitesse — cf. itr.py. Un ITR par décodeur : ils n'ont
    # aucune raison de dégrader à la même vitesse.
    # ⚠️ `n_cibles` (ce que les DEUX décodeurs ont RÉELLEMENT jugé), jamais `len(plan)` : sur une
    # séance INTERROMPUE (Critical 1), les deux ne jugent plus que parmi un sous-ensemble, et un
    # hasard/ITR calculés à `len(plan)` restaient gonflés dans exactement ce cas-là (réserve du
    # tour 2 de la revue) — un « DÉPASSE LE SSVEP » qui ne mesure pas ce qu'il prétend mesurer.
    # ⚠️ **La DURÉE d'une décision se lit sur le MÊME dict que la justesse, jamais sur une
    # constante recopiée à côté.** `cycle_s = L / app.refresh` (UN cycle) est resté ici quand
    # `entraine_les_deux` a migré sa mesure à `CVEP_DECISION_CYCLES` : les justesses venaient de
    # k=2 et la durée de k=1, donc l'ITR affiché était EXACTEMENT DOUBLÉ. Sur la séance de
    # référence (6 cibles, eCCA 59,5 %, rCCA 64,9 %), l'écran annonçait « 48 bits/min —
    # PROMETTEUR » là où la mesure vaut 24 et où le README annonce 22 — et le verdict basculait
    # d'un cran complet (seuil `ref/2` = 25,0). Aucune des 47 assertions du fichier ne s'en
    # apercevait : aucune ne lisait une valeur d'ITR. Faire dériver la durée de `res` supprime la
    # classe entière — changer `n_cycles` déplace maintenant les deux chiffres ensemble.
    from research.itr import itr as _itr
    chance = 100.0 / n_cibles
    k_decision = res["eCCA"]["n_cycles"]      # la géométrie où cv_e/cv_r ont ÉTÉ MESURÉES
    decision_s = k_decision * L / app.refresh
    bits_e = _itr(n_cibles, cv_e, decision_s)
    bits_r = _itr(n_cibles, cv_r, decision_s)
    meilleur = max(bits_e, bits_r)
    ref = _itr(3, 0.95, 1.5)   # SSVEP actuel = la barre à battre
    # ⚠️ McNemar, PAS une comparaison de deux pourcentages : voir `_gagnant`, tour 2 de la revue.
    # « indiscernables » est la réponse honnête ET la réponse attendue — c'est précisément parce
    # que les deux décodeurs se valent que ce chantier a rouvert le rCCA (cf. core/cvep_rcca.py).
    mn = _gagnant(res)
    verdict = ("DÉPASSE LE SSVEP" if meilleur >= ref else
               "PROMETTEUR" if meilleur >= ref / 2 else
               "FAIBLE (contact électrodes ? regard qui décroche ? refais un essai)")
    print(f"[cvep-cal] {len(epochs)} cycles sur {n_cibles} cibles jugées (hasard {chance:.0f}%), "
          f"décision = {k_decision} cycle(s) ({decision_s:.2f}s) :")
    print(f"[cvep-cal]   eCCA  leave-one-out {cv_e*100:5.1f}%  -> {bits_e:5.1f} bits/min")
    print(f"[cvep-cal]   rCCA  leave-one-out {cv_r*100:5.1f}%  -> {bits_r:5.1f} bits/min")
    ligne_gagnant = (f"indiscernables sur cette séance (McNemar p={mn['p']:.3f})" if mn["gagnant"]
                     is None else f"gagnant : {mn['gagnant']} (McNemar p={mn['p']:.3f})")
    print(f"[cvep-cal] {ligne_gagnant} — {mn['n_discordantes']} décisions discordantes sur "
          f"{res['eCCA']['n_decisions']} (eCCA seul {mn['b']}, rCCA seul {mn['c']})")
    print(f"[cvep-cal]   —   SSVEP de référence {ref:.1f} -> {verdict}")
    print(f"[cvep-cal] `python src/research/cvep_analyze.py` pour le gain en moyennant plusieurs cycles.")
    print(f"[cvep-cal] {ligne_sauvegarde}")

    t0 = time.perf_counter()
    while time.perf_counter() - t0 < (0.1 if app.smoke else 5.0):
        try:
            app.drain(on_key=lambda e: None)
        except Abort:
            break
        app.win.fill(BG)
        h = app.win.get_height()
        app.center(app.big, f"eCCA {cv_e*100:.0f}%   ·   rCCA {cv_r*100:.0f}%", FG, int(h * 0.28))
        app.center(app.mid, ligne_gagnant, DIM if mn["gagnant"] is None else GO, int(h * 0.38))
        app.center(app.small, f"{mn['n_discordantes']} décisions discordantes sur "
                   f"{res['eCCA']['n_decisions']}  ({mn['b']} eCCA seul, {mn['c']} rCCA seul)",
                   DIM, int(h * 0.46))
        app.center(app.mid, f"{meilleur:.0f} bits/min (meilleur des deux, décision "
                   f"{k_decision} cycles)   —   SSVEP réf. {ref:.0f}",
                   GO if meilleur >= ref / 2 else WARN, int(h * 0.56))
        app.center(app.small, verdict, DIM, int(h * 0.65))
        app.center(app.small,
                   "modèles sauvegardés (eCCA et rCCA) — ESC pour continuer"
                   if n_cibles_vues == len(plan) else
                   f"séance interrompue : eCCA sauvegardé, rCCA NON ({n_cibles_vues}/{len(plan)} "
                   f"cibles) — ESC pour continuer",
                   DIM, int(h * 0.73))
        app.pygame.display.flip()
        app.clock.tick(60)
    return meilleur >= ref / 2, res


# --- Autotest (aucun casque, c-VEP synthétique) ------------------------------

def _selftest():
    """La comparaison honnête eCCA/rCCA (tâche 6) : mêmes époques, mêmes groupes de validation
    croisée, un gagnant nommé — et les deux chiffres survivent à un aller-retour sur disque.
    Aucun casque, aucune donnée réelle."""
    import shutil
    import tempfile

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
    # ⚠️ **Tout ce que cette comparaison garantit est testé DANS `core`** — mêmes époques,
    # mêmes groupes, même nombre d'alternatives, McNemar sur des décisions appariées, le cas
    # « zéro décision à la géométrie du moteur » : `python src/core/modes/cvep_calib.py`. Ces
    # assertions ont déménagé AVEC leur fonction (chantier « seul point d'entrée », tâche 8).
    # Ce qui reste ici est ce qui ne peut se vérifier que de CE côté de la frontière : que
    # l'écran de l'appli pygame appelle bien LES MÊMES objets, et non une seconde copie qui
    # divergerait un jour sans que rien ne le dise.
    import core.cvep_rcca as _core_rcca
    import core.modes.cvep_calib as _core_calib

    chk(entraine_les_deux is _core_calib.entraine_les_deux
        and _gagnant is _core_calib.gagnant
        and chemin_modele_horodate is _core_calib.chemin_modele_horodate
        and _mcnemar_p is _core_rcca._mcnemar_p and SEUIL_MCNEMAR == _core_rcca.SEUIL_MCNEMAR,
        "cet écran et la calibration du MOTEUR appellent les MÊMES fonctions "
        "d'entraînement et le MÊME test de McNemar — une seule implémentation dans le dépôt, "
        "donc un seul jeu de tests à tenir")

    # --- Les deux chiffres ET le champ `decoder` partent dans le fichier de modèle. ------------
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

    # --- Revue finale, Critical 2 : LE MÊME contrôle À ROTATION NON NULLE. ---------------------
    # Le contrôle ci-dessus tourne à `CVEP_LAG_ROTATION = 0` — le SEUL point où « trié par valeur
    # de lag » et « ordre du plan » coïncident. C'est cette coïncidence qui a rendu invisible le
    # défaut créé par le correctif Critical 1 : `codes_vus` empilé par lag croissant, quand le
    # rCCA et `cvep_models._codes_affiches` apparient PAR POSITION dans le plan. Hors rotation
    # zéro, les lignes du modèle sont donc une PERMUTATION de celles du stimulus, `charger` refuse
    # tout modèle fraîchement calibré, et recalibrer reproduit le même fichier refusé.
    # `config.py` dit explicitement que ce paramètre « reste disponible » : ce cas doit être testé.
    import core.cvep_code as _cc
    _rot_reelle = _cc.CVEP_LAG_ROTATION
    _cc.CVEP_LAG_ROTATION = 2
    try:
        plan_rot, code_rot = build_targets()
        lags_rot = [c["lag"] for c in plan_rot]
        chk(lags_rot != sorted(lags_rot),
            f"fixture : à CVEP_LAG_ROTATION = 2, l'ordre du plan n'est VRAIMENT plus l'ordre des "
            f"valeurs de lag — les deux tris divergent ({lags_rot})")
        epochs_rot, labels_rot = [], []
        for c in plan_rot:
            for _ in range(8):
                epochs_rot.append(synth_cvep(code_rot, c["lag"], n_raw, fs, refresh, -6.0, rng))
                labels_rot.append(c["lag"])
        res_rot = entraine_les_deux(epochs_rot, labels_rot, fs=fs, refresh=refresh, channels=voies)
        codes_plan_rot = np.stack([np.asarray(c["code"], dtype=int) for c in plan_rot])
        chk(np.array_equal(res_rot["rCCA"]["modele"].codes, codes_plan_rot),
            "le modèle rCCA calibré à rotation 2 porte les codes du plan DANS L'ORDRE DU PLAN, "
            "pas triés par valeur de lag — c'est l'ordre, et lui seul, qui apparie un score à un "
            "nom de cible")
        tmp_rot = tempfile.mkdtemp(prefix="cvep_calibrate_rot_")
        try:
            chemin_rot = res_rot["rCCA"]["modele"].save(
                os.path.join(tmp_rot, "cvep_rcca_model.npz"))
            relu_rot, pb_rot = charger(chemin_rot)
            chk(relu_rot is not None and pb_rot is None,
                f"...donc `cvep_models.charger` l'ACCEPTE — un modèle qu'on vient de calibrer "
                f"sans rien avoir changé ne doit pas être refusé ({pb_rot})")
            if relu_rot is not None:
                cible_rot = 4
                fenetre_rot = synth_cvep(code_rot, plan_rot[cible_rot]["lag"], len(voies),
                                         fs, refresh, -6.0, rng)
                choisi_rot, _ = RCCADecoder(relu_rot, plan_rot, corr_min=-1e9, margin=0.0,
                                            n_cycles=1).classify(fenetre_rot, 0)
                chk(choisi_rot is not None
                    and choisi_rot["name"] == plan_rot[cible_rot]["name"],
                    f"...et il désigne la cible RÉELLEMENT AFFICHÉE, pas sa voisine "
                    f"({None if choisi_rot is None else choisi_rot['name']} au lieu de "
                    f"{plan_rot[cible_rot]['name']})")
        finally:
            shutil.rmtree(tmp_rot, ignore_errors=True)
    finally:
        _cc.CVEP_LAG_ROTATION = _rot_reelle
    chk(_cc.CVEP_LAG_ROTATION == _rot_reelle,
        f"...et la rotation réelle est restaurée, même si le bloc ci-dessus avait levé "
        f"({_cc.CVEP_LAG_ROTATION})")

    # --- Tour 3 de la revue : PROTÉGER calibrate() lui-même, pas seulement ce qui l'alimente. ----
    # Mesuré par le re-relecteur : muter `n_cibles` en `len(plan)` (réserve C1) OU désactiver le
    # garde à zéro décision (la casse TypeError du tour 2) laissait CE FICHIER **et** `app.py
    # --smoke` VERTS TOUS LES DEUX — aucun test n'exerçait `calibrate()` lui-même sur une séance
    # TRONQUÉE ni sur une séance SANS AUCUNE paire de cycles consécutifs ; seule la donnée en amont
    # (`entraine_les_deux`) était protégée. On exerce donc le VRAI `calibrate()`, via une VRAIE
    # `App(smoke=True)`, en détournant `_make_blocks` (la fabrique de blocs d'enregistrement) pour
    # forcer les deux scénarios qu'un smoke normal n'atteint jamais.
    import contextlib
    import io
    import re as _re

    from research.itr import itr as _itr_ref
    from research.ui import App

    _ce_module = sys.modules[__name__]
    _make_blocks_original = _ce_module._make_blocks

    @contextlib.contextmanager
    def _blocs_detournes(fabrique):
        """Remplace `_make_blocks` par `fabrique` le temps du bloc, la restaure après — y compris
        si `calibrate()` lève, pour qu'un test qui rougit ne laisse rien de patché derrière lui."""
        _ce_module._make_blocks = fabrique
        try:
            yield
        finally:
            _ce_module._make_blocks = _make_blocks_original

    app_int = App(smoke=True)
    try:
        # --- Réserve C1 : le hasard et l'ITR affichés DOIVENT suivre n_cibles, pas len(plan). ---
        tmp1 = tempfile.mkdtemp(prefix="cvep_calibrate_c1_selftest_")
        try:
            with _blocs_detournes(lambda p, c, n: _make_blocks_original(p[:3], c, n)):
                capture = io.StringIO()
                with contextlib.redirect_stdout(capture):
                    ok1, res1 = calibrate(app_int, save_path=os.path.join(tmp1, "e.npz"),
                                          rcca_save_path=os.path.join(tmp1, "r.npz"))
            sortie1 = capture.getvalue()
            fichiers1 = set(os.listdir(tmp1))
            # Relu par le chemin RÉEL du moteur (`CVEPModel.load`), pas depuis l'objet en mémoire :
            # c'est le FICHIER qui voyage jusqu'au moteur, et c'est lui qui doit dire la vérité.
            ecca1 = CVEPModel.load(os.path.join(tmp1, "e.npz"))
        finally:
            shutil.rmtree(tmp1, ignore_errors=True)
        chk(res1["eCCA"]["n_cibles"] == 3,
            f"calibrate() sur une séance tronquée à 3 cibles sur 6 en juge bien 3 "
            f"({res1['eCCA']['n_cibles']})")
        m_hasard = _re.search(r"hasard (\d+)%", sortie1)
        chk(m_hasard is not None and m_hasard.group(1) == "33",
            f"...et le HASARD IMPRIMÉ par calibrate() suit n_cibles=3 (33 %), jamais len(plan)=6 "
            f"(17 %) — sinon l'ITR et le verdict affichés à l'étudiant resteraient gonflés sur "
            f"EXACTEMENT la séance que Critical 1 visait "
            f"({m_hasard.group(0) if m_hasard else sortie1!r})")
        # --- Revue finale, Critical 2 (b) : la séance tronquée n'écrit PAS de fichier rCCA. -----
        # Il porterait 3 codes pour un stimulus qui en affiche 6 : `cvep_models.charger` le
        # refuse (vérifié plus haut sur `res3`), donc il n'apparaîtrait jamais dans la liste de la
        # console. L'écrire quand même, en annonçant « modèles sauvegardés : … (rCCA) », donne un
        # succès pour un artefact que rien ne peut charger — et le gagnant nommé peut être lui.
        chk("e.npz" in fichiers1 and "r.npz" not in fichiers1,
            f"une séance tronquée sauvegarde l'eCCA et PAS le rCCA ({sorted(fichiers1)})")
        chk("rCCA NON sauvegardé" in sortie1 and "séance interrompue" in sortie1,
            f"...et calibrate() le DIT, au lieu d'annoncer « modèles sauvegardés » pour les deux "
            f"({[l for l in sortie1.splitlines() if 'sauvegard' in l]})")
        # --- Revue finale, E-I3 : le fichier eCCA DÉCLARE ce que la séance a présenté. ----------
        # ⚠️ Le template eCCA est commun à tous les lags : un modèle à 3 cibles « marche » à 6 et
        # publie six corrélations d'apparence normale, dont trois issues de lags jamais montrés.
        # `CVEPRuntime._desaccord_code` refuse précisément ce cas — mais seulement si le fichier
        # ne ment pas sur lui-même. Avec `n_targets=len(plan)`, la calibration rendait ce refus
        # INOPÉRANT sur la seule séance qu'il vise, et l'asymétrie s'était creusée : le rCCA d'une
        # séance tronquée n'est plus écrit du tout, l'eCCA l'était en se déclarant complet.
        chk(ecca1.n_targets == 3,
            f"le modèle eCCA d'une séance tronquée se déclare à 3 cibles — celles qu'il a "
            f"réellement vues —, jamais aux {len(build_targets()[0])} du plan : c'est ce champ, et "
            f"lui seul, qui permet au moteur de le refuser ({ecca1.n_targets})")
        chk("REFUSERA" in sortie1,
            f"...et calibrate() prévient que le moteur le refusera tant que le stimulus affichera "
            f"plus de cibles, au lieu d'annoncer une sauvegarde sans réserve "
            f"({[l for l in sortie1.splitlines() if 'sauvegard' in l]})")

        # --- Revue finale, Critical 1 : l'ITR IMPRIMÉ est calculé à la géométrie où la justesse
        # a été MESURÉE. `cycle_s = L / app.refresh` (un cycle) est resté ici quand la mesure est
        # passée à `CVEP_DECISION_CYCLES` : l'ITR affiché était EXACTEMENT DOUBLÉ, et le verdict
        # basculait d'un cran (« PROMETTEUR » au lieu de « FAIBLE » sur la séance de référence).
        # Aucune des 47 assertions du fichier ne lisait une valeur d'ITR — celle-ci le fait, sur
        # la sortie du VRAI `calibrate()`, et elle ne dépend pas de la justesse obtenue (qui, sur
        # un board de test, peut tomber sous le hasard et rendre tous les ITR nuls).
        L_test = len(build_targets()[1])
        m_geo = _re.search(r"décision = (\d+) cycle\(s\) \(([\d.]+)s\)", sortie1)
        chk(m_geo is not None and int(m_geo.group(1)) == res1["eCCA"]["n_cycles"]
            and abs(float(m_geo.group(2))
                    - res1["eCCA"]["n_cycles"] * L_test / app_int.refresh) < 0.01,
            f"la DURÉE de décision imprimée est celle où la justesse a été mesurée "
            f"({res1['eCCA']['n_cycles']} cycles = "
            f"{res1['eCCA']['n_cycles'] * L_test / app_int.refresh:.2f}s), pas un cycle "
            f"({L_test / app_int.refresh:.2f}s) — le facteur 2 exact "
            f"({m_geo.group(0) if m_geo else sortie1!r})")
        # ...et l'ITR imprimé se relit à partir de la DURÉE IMPRIMÉE, pas d'une autre : les deux
        # chiffres de la même ligne doivent décrire le même décodeur. (Cette assertion-ci ne
        # suffit pas à elle seule — sur un board de test, la justesse peut tomber sous le hasard
        # et les deux géométries rendent alors 0,0 bits/min : c'est l'assertion sur la DURÉE
        # ci-dessus qui porte la preuve.)
        m_bits = _re.search(r"eCCA\s+leave-one-out\s+([\d.]+)%\s+->\s+([\d.]+) bits/min", sortie1)
        chk(m_bits is not None and m_geo is not None and abs(
            float(m_bits.group(2))
            - _itr_ref(res1["eCCA"]["n_cibles"], res1["eCCA"]["justesse"],
                       float(m_geo.group(2)))) < 0.05,
            f"...et l'ITR imprimé est bien celui de la durée IMPRIMÉE à côté de lui "
            f"({m_bits.group(0) if m_bits else sortie1!r})")
        # ...et la géométrie annoncée n'est pas une constante recopiée : elle sort du dict que
        # `entraine_les_deux` rend, donc de la mesure elle-même.
        chk(res1["eCCA"]["n_cycles"] == res1["rCCA"]["n_cycles"] == CVEP_DECISION_CYCLES,
            f"la géométrie rendue par entraine_les_deux est celle du moteur "
            f"({res1['eCCA']['n_cycles']}, {res1['rCCA']['n_cycles']}, {CVEP_DECISION_CYCLES})")
        # Le chiffre CONCRET, sur la séance de référence que le dépôt documente partout (6 cibles,
        # eCCA 22/37 = 59,5 %, rCCA 24/37 = 64,9 %, code L=63 à 60 Hz) : c'est le chiffre-vedette
        # du chantier, et c'est lui qui était doublé. ⚠️ C'est CETTE assertion qui fait autorité
        # sur les 19,1 / 23,8 bits/min que README.md et docs/SPEC.md annoncent désormais — ils
        # citent la mesure d'ici, plus un « ~22 » sans provenance.
        ref_ssvep = _itr_ref(3, 0.95, 1.5)
        bits_ref_e = _itr_ref(6, 22 / 37, CVEP_DECISION_CYCLES * 63 / 60.0)
        bits_ref_r = _itr_ref(6, 24 / 37, CVEP_DECISION_CYCLES * 63 / 60.0)
        chk(abs(bits_ref_e - 19.1) < 0.1 and abs(bits_ref_r - 23.8) < 0.1
            and max(bits_ref_e, bits_ref_r) < ref_ssvep / 2,
            f"séance de RÉFÉRENCE : eCCA {bits_ref_e:.1f} et rCCA {bits_ref_r:.1f} bits/min à "
            f"{CVEP_DECISION_CYCLES} cycles — EXACTEMENT les 19,1 et 23,8 que la doc annonce, et "
            f"SOUS la moitié du SSVEP ({ref_ssvep/2:.1f}) donc verdict « FAIBLE »")
        chk(abs(_itr_ref(6, 24 / 37, 63 / 60.0) - 2 * bits_ref_r) < 1e-9
            and _itr_ref(6, 24 / 37, 63 / 60.0) >= ref_ssvep / 2,
            f"...et le calcul à UN cycle rendait exactement le DOUBLE "
            f"({_itr_ref(6, 24/37, 63/60.0):.1f}), donc « PROMETTEUR » : un cran de verdict "
            f"complet, sur un chiffre faux d'un facteur 2 exact")

        # --- La casse TypeError (tour 2) : calibrate() ne doit PAS planter à zéro décision. -----
        tmp2 = tempfile.mkdtemp(prefix="cvep_calibrate_td_selftest_")
        try:
            with _blocs_detournes(lambda p, c, n: [(cible, 1) for _ in range(2) for cible in p]):
                ok2, res2 = calibrate(app_int, save_path=os.path.join(tmp2, "e.npz"),
                                      rcca_save_path=os.path.join(tmp2, "r.npz"))
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)
        # Arriver ici EST une partie de la preuve : un `TypeError` (celui du tour 2, `chance =
        # 100.0 / n_cibles` avec `n_cibles=None`) aurait fait sortir `_selftest()` en exception
        # avant cette ligne, sans que `chk` n'ait la main pour le dire proprement.
        chk(ok2 is False,
            f"calibrate() sur une séance SANS AUCUNE paire de cycles consécutifs rend "
            f"(False, ...), jamais un TypeError ({ok2})")
        chk(res2["eCCA"]["justesse"] is None and res2["eCCA"]["n_cibles"] is None,
            f"...et le résultat dit bien qu'il n'y a rien à mesurer, ce qui est CE QUI PERMET à "
            f"calibrate() de fermer le chemin AVANT tout calcul ({res2['eCCA']['justesse']}, "
            f"{res2['eCCA']['n_cibles']})")
    finally:
        app_int.close()

    # --- Les défauts d'écriture : `calibrate()` n'écrase JAMAIS un nom FIXE. -------------------
    # Ces trois assertions vivaient dans le `_smoke` de `research/app.py` ; elles sont montées ici
    # AVEC l'écran qu'elles protègent, le 2026-09-08. Vérifiées sur le TEXTE SOURCE, comme leurs
    # jumelles P300 et ErrP : appeler `calibrate(app)` sans chemin pour VOIR où il écrit serait
    # exactement l'accident qu'on veut interdire. `CVEP_RCCA_MODEL_PATH` porte la trace du
    # 21 juillet (35,6 %, codes Gold) que ce dépôt cite comme preuve mesurée du jeu égal
    # eCCA/rCCA, et une revue a mesuré qu'un smoke mal câblé suffisait à l'écraser.
    import inspect

    src_cal = inspect.getsource(calibrate)
    chk("save_path=CVEP_MODEL_PATH" not in src_cal,
        "calibrate() n'a JAMAIS CVEP_MODEL_PATH comme défaut de save_path — un défaut fixe "
        "écraserait le modèle eCCA à chaque calibration de démonstration")
    chk("rcca_save_path=CVEP_RCCA_MODEL_PATH" not in src_cal,
        "...et rcca_save_path non plus : CVEP_RCCA_MODEL_PATH est la trace du 21 juillet "
        "(35,6 %, codes Gold), preuve mesurée du jeu égal eCCA/rCCA")
    chk("chemin_modele_horodate(" in src_cal,
        "...et calibrate() retombe sur des chemins HORODATÉS quand on ne lui en donne pas")

    print(f"[cvep-calibrate] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _parse(argv):
    p = argparse.ArgumentParser(
        description="Calibration c-VEP pygame (ARCHIVÉE — le moteur calibre désormais).")
    # ⚠️ Les deux chemins sont EXPLICITES et leur défaut est HORODATÉ, jamais un nom fixe :
    # `CVEP_RCCA_MODEL_PATH` (`data/cvep_rcca_model.npz`) porte le seul modèle Gold jamais
    # calibré au casque, et ce dépôt l'a déjà détruit une fois avec un défaut fixe.
    p.add_argument("--model", default=None,
                   help="où écrire le modèle eCCA (défaut : un nom HORODATÉ dans data/)")
    p.add_argument("--rcca-model", default=None,
                   help="où écrire le modèle rCCA (défaut : un nom HORODATÉ dans data/)")
    p.add_argument("--cycles", type=int, default=CVEP_CAL_CYCLES,
                   help="cycles enregistrés par cible")
    p.add_argument("--windowed", action="store_true", help="fenêtre au lieu du plein écran")
    p.add_argument("--synthetic", action="store_true", help="board de test (sans casque)")
    p.add_argument("--smoke", action="store_true", help="autotest headless (CI)")
    return p.parse_args(argv)


def main(argv=None):
    a = _parse(sys.argv[1:] if argv is None else argv)
    if a.smoke:
        # L'autotest ne touche QUE des dossiers temporaires — vérifié, pas supposé. `data/` porte
        # des enregistrements EEG d'une personne identifiable sur un dépôt public, et c'est un
        # smoke mal câblé de ce sous-système qui a déjà écrasé `data/cvep_rcca_model.npz`.
        empreinte_avant = empreinte_dossier(DATA_DIR)
        ok = _selftest()
        empreinte_apres = empreinte_dossier(DATA_DIR)
        assert empreinte_apres == empreinte_avant, (
            f"cet autotest a touché data/ — il doit écrire UNIQUEMENT dans des dossiers "
            f"temporaires : {set(empreinte_apres) ^ set(empreinte_avant) or 'contenu modifié'}")
        return ok
    app = App(windowed=a.windowed, synthetic=a.synthetic)
    try:
        calibrate(app, cycles=a.cycles, save_path=a.model, rcca_save_path=a.rcca_model)
    except Abort:
        print("[cvep-cal] annulé.")
    finally:
        app.close()
    return True


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if main() else 1)
