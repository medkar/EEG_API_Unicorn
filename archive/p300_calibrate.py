"""Calibration P300 pygame — l'écran de CALIBRATION retiré de l'appli unifiée.

Ce fichier vivait dans `src/research/`, appelé depuis la page « P300 » de `src/research/app.py`,
supprimé le 2026-09-08. C'est le MOTEUR qui calibre désormais : la console lance
`src/stimulus/p300.py --calibrer`, le moteur écoute les marqueurs et entraîne
(`core/modes/p300_calib.py`), puis la console AFFICHE le résultat avant de demander « Refaire /
Enregistrer ». Cet écran-ci écrit son modèle DIRECTEMENT dans `data/` sans passer par ce garde —
c'est exactement pourquoi il n'est plus au menu de rien.

Gardé ici, ENCORE EXÉCUTABLE, comme référence : le moteur a été écrit contre lui, et il APPELLE le
même entraînement (`core/modes/p300_calib.entrainer`), il n'en a pas de copie.

⚠️ Ne jamais le lancer en même temps que le moteur, la console ou un autre écran archivé : le casque
n'accepte qu'UNE connexion.

    python archive/p300_calibrate.py                   # plein écran, casque réel
    python archive/p300_calibrate.py --windowed
    python archive/p300_calibrate.py --model data/mon_p300.joblib
    python archive/p300_calibrate.py --synthetic       # sans casque (board de test BrainFlow)
    python archive/p300_calibrate.py --smoke           # test headless (CI)

Le protocole, inchangé depuis l'appli : fixer+compter une cible cuée pendant que les cibles
clignotent une à une.

Déroulé d'une MANCHE : une cible est cerclée (la « cible attendue »). Tu la fixes et tu COMPTES
ses flashs. On fait clignoter les N cibles chacune leur tour, en ordre mélangé, `reps` fois. Le
flash de la cible attendue est rare (1/N) et compté -> il évoque un P300 ; les autres non. On
enregistre chaque flash comme une époque étiquetée « cible / non-cible » (via le timestamp du
flux, cf. core.p300_decoder.epoch_from_stream). On change de cible attendue à chaque manche.

⚠️ **Ce fichier ne fait plus que la MOITIÉ PYGAME du travail.** L'entraînement — le `fit`, l'AUC
par manche, la sélection en leave-one-round-out, la sauvegarde horodatée — a déménagé dans
`core/modes/p300_calib.py` le 2026-09-07, parce que c'est désormais le MOTEUR qui calibre
(la console lance `src/stimulus/p300.py --calibrer`, le moteur écoute les marqueurs et entraîne).
Ce qui reste ici est ce qui touche pygame : les écrans, la couronne, le ramassage des époques par
l'horloge de l'appli. La suite est un simple appel à `p300_calib.entrainer` — une seule écriture de
l'entraînement pour les deux chemins, au lieu de deux qui dériveraient.

⚠️ **L'épochage, lui, reste DIFFÉRENT de celui du moteur**, et ce n'est pas un oubli : cet écran
découpe depuis `app.acq.get_raw` (l'horloge de l'appli), le moteur depuis son tampon et les
horodatages LSL. C'est précisément le second chemin que le chantier « la console, seul point
d'entrée » existe pour retirer. Tant qu'il vit, ne pas s'en servir pour produire le modèle d'une
séance sérieuse : passer par la console.

Compter les flashs n'est pas un gadget : la tâche mentale (« combien de fois ? ») est ce qui rend
le stimulus attendu SAILLANT et amplifie le P300. Sans tâche, l'onde s'effondre.
"""

import argparse
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))      # -> src/
from core.config import (DATA_DIR, empreinte_dossier, P300_CAL_ROUNDS,  # noqa: E402
                    P300_EPOCH_S, P300_FLASH_OFF_FR,
                    P300_FLASH_ON_FR, P300_MIDLINE, P300_MODEL_PATH, P300_PRE_S, P300_REPS,
                    p300_targets)
from core.modes import p300_calib  # noqa: E402
from core.p300_decoder import NONTARGET, TARGET, epoch_from_stream  # noqa: E402
from research.itr import itr  # noqa: E402
# `blocs_melanges` vit dans l'émetteur : c'est lui qui documente l'invariant oddball, et
# `p300_stimulus` n'importe pygame qu'à l'intérieur de `run()` — l'importer ici ne coûte rien.
from stimulus.p300 import blocs_melanges  # noqa: E402
# La machinerie pygame partagée est le VOISIN `archive/ui.py` depuis le 2026-09-09 (elle était
# `research/ui.py`) : `research/` n'a plus le droit d'ouvrir le casque ni de dessiner. Nom de
# module NU, car Python met le dossier du script en tête de `sys.path`.
from ui import ACCENT, App, BG, DIM, FG, GO, WARN, Abort  # noqa: E402

BRIEF = [
    "Calibration P300",
    "",
    "• Une cible est CERCLÉE (bleu) : c'est celle que tu dois fixer.",
    "• Les cibles s'allument une à une, en bref éclair, dans le désordre.",
    "• FIXE la cible cerclée et COMPTE mentalement ses éclairs (c'est la tâche : elle crée le P300).",
    "• Reste immobile, cligne le moins possible pendant les flashs.",
    "• À chaque manche, la cible à fixer change. Durée totale affichée dans la console.",
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
        y = int(h * 0.15)
        for i, line in enumerate(BRIEF):
            f = app.big if i == 0 else app.small
            col = FG if i == 0 else (GO if line.startswith("Appuie") else FG)
            app.center(f, line, col, y)
            y += int(h * 0.085) if i == 0 else int(h * 0.055)
        app.pygame.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return True


def _intro(app, plan, spots, cue_name, r, rounds, seconds=2.5):
    """Écran « fixe et compte X » avant les flashs de la manche (cible cerclée, rien ne clignote).
    Point de PAUSE sûr : les époques de la manche précédente sont déjà ramassées, aucun stimulus
    ne tourne encore -> ESPACE met en pause ici (entre manches)."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        app.drain(pausable=True)                 # ESPACE = pause (sûr entre deux manches)
        app.win.fill(BG)
        h = app.size[1]
        app.center(app.big, f"Manche {r + 1}/{rounds}", FG, int(h * 0.10))
        app.center(app.mid, f"FIXE et COMPTE les éclairs de : {cue_name}", GO, int(h * 0.17))
        app.draw_ring(plan, spots, lambda c, f: False, 0, cue=cue_name)
        app.center(app.small, "Espace = pause (entre les manches)", DIM, int(h * 0.92))
        app.pygame.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return


def _blank_ring(app, plan, spots, cue_name, frames):
    """Rend l'anneau ÉTEINT pendant `frames` (settle / gap), ESC actif."""
    for _ in range(frames):
        app.drain()
        app.win.fill(BG)
        app.draw_ring(plan, spots, lambda c, f: False, 0, cue=cue_name)
        app.pygame.display.flip()
        app.clock.tick(int(app.refresh) + 5)
        if app.smoke:
            return


def _flash_targets(app, plan, spots, cue_name, order, on_fr, off_fr):
    """UNE répétition P300 : flashe une fois chaque cible de `order` (indices dans plan), avec un
    gap éteint entre chaque. Retourne [(target_index, onset_unix_ts)] (onset horodaté à la 1re
    frame allumée). ESC actif. Réutilisé par la calibration ET par le live (fixe ou dynamique)."""
    flashes = []
    for t in order:
        lit = plan[t]["name"]
        for f in range(on_fr):                  # phase ALLUMÉE (la cible t)
            app.drain()
            app.win.fill(BG)
            app.draw_ring(plan, spots, lambda c, fr, L=lit: c["name"] == L, 0, cue=cue_name)
            app.pygame.display.flip()
            if f == 0:
                flashes.append((t, time.time()))
            app.clock.tick(int(app.refresh) + 5)
            if app.smoke:
                break
        for _ in range(off_fr):                 # phase ÉTEINTE (gap avant le flash suivant)
            app.drain()
            app.win.fill(BG)
            app.draw_ring(plan, spots, lambda c, fr: False, 0, cue=cue_name)
            app.pygame.display.flip()
            app.clock.tick(int(app.refresh) + 5)
            if app.smoke:
                break
    return flashes


def _run_round(app, plan, spots, cue_name, reps, on_fr, off_fr, rng):
    """Une manche de calibration = `reps` répétitions, chacune = les N cibles flashées une fois
    dans un ordre mélangé. Retourne (flashes, t_start).

    ⚠️ L'ordre vient de `blocs_melanges` (stimulus/p300.py) et n'est plus remélangé
    ici : l'invariant « aucune cible deux fois de suite, jonctions comprises » était affirmé et
    testé dans l'ÉMETTEUR seul, alors que cette calibration est le SEUL chemin vers un modèle.
    Mesuré sur 20 000 manches avec l'ancien mélange local : 72,0 % des manches de calibration
    contenaient au moins une répétition immédiate, 1,17 par manche (2,44 % des époques). Ce n'est
    pas l'ampleur qui pose problème, c'est qu'un invariant tenu à un endroit sur trois n'en est
    pas un — et que celui-ci est violé là où il compte le plus, dans les données d'entraînement.
    """
    n = len(plan)
    t_start = time.time()
    flashes = []
    eff_reps = 1 if app.smoke else reps          # headless : 1 rép (6 flashs) suffit au câblage
    for bloc in blocs_melanges(n, eff_reps, rng):
        flashes += _flash_targets(app, plan, spots, cue_name, bloc, on_fr, off_fr)
    return flashes, t_start


def _collect(app, plan, spots, cue_name, flashes, t_start, cue_idx, fs,
             epochs, labels, flashed, groups, r):
    """Laisse le dernier post-stimulus se remplir, récupère le flux de la manche, découpe et
    étiquette chaque époque. Ajoute in-place aux listes fournies."""
    settle_fr = int(round((P300_EPOCH_S + 0.15) * app.refresh))
    _blank_ring(app, plan, spots, cue_name, settle_fr)
    if app.smoke:
        time.sleep(P300_EPOCH_S + 0.3)   # headless : le rendu est instantané -> laisse le board
        #                                  synthétique accumuler le post-stimulus, sinon 0 époque
    eeg, ts = app.acq.get_raw(time.time() - t_start + P300_PRE_S + 0.5)
    if eeg is None:
        return 0
    added = 0
    for t, onset in flashes:
        ep = epoch_from_stream(eeg, ts, onset, fs)
        if ep is None:
            continue
        epochs.append(ep)
        labels.append(TARGET if t == cue_idx else NONTARGET)
        flashed.append(t)
        groups.append(r)
        added += 1
    return added


def _results(app, auc, sel_ok, sel_tot, t_sel, n_targets):
    """Écran de résultat (6 s ou une touche)."""
    sel = sel_ok / sel_tot if sel_tot else 0.0
    itr_val = itr(n_targets, sel, t_sel) if sel_tot else 0.0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 6.0:
        pressed = []
        app.drain(on_key=lambda e: pressed.append(True))
        if pressed:
            return
        app.win.fill(BG)
        h = app.size[1]
        app.center(app.big, "Calibration P300 terminée", FG, int(h * 0.20))
        auc_txt = "—" if auc is None else f"{auc * 100:.1f}%"
        app.center(app.mid, f"AUC cible/non-cible (par manche) : {auc_txt}", DIM, int(h * 0.36))
        col = GO if sel >= 0.6 else WARN
        app.center(app.mid, f"Sélection retrouvée : {sel_ok}/{sel_tot} = {sel * 100:.0f}%  "
                            f"(hasard {100 / n_targets:.0f}%)", col, int(h * 0.46))
        app.center(app.mid, f"ITR ~ {itr_val:.1f} bits/min  ({t_sel:.1f} s/sélection)",
                   DIM, int(h * 0.56))
        app.center(app.small, "une touche pour revenir au menu", DIM, int(h * 0.8))
        app.pygame.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return


def chemin_modele_horodate(dossier=None):
    """`data/p300_model_AAAAMMJJ_HHMMSS.joblib` — un fichier NEUF, jamais un écrasement.

    ⚠️ La calibration écrivait dans `P300_MODEL_PATH` (`data/p300_model.joblib`), un nom FIXE :
    la calibration suivante effaçait donc la précédente. Or `data/p300_model.joblib` est la
    trace de juillet que ce chantier a explicitement choisi de préserver — c'est le seul modèle
    P300 enregistré au casque, et le MI a déjà perdu ses quatre modèles de cette façon. Rien
    n'appliquait cet invariant : seule une prose l'affirmait.

    Le nom est fabriqué par `core/modes/p300_calib.chemins_libres`, pas ici : c'est la calibration
    du MOTEUR qui écrit désormais les modèles de séance, et deux façons de nommer le même fichier
    finiraient par diverger — celle-ci pourrait produire un nom que `p300_models.MOTIF` ne liste
    plus. Cadeau au passage : ce chemin-là est GARANTI libre, alors que `strftime` seul rendait
    deux fois le même nom pour deux calibrations finies dans la même seconde.
    """
    dossier = os.path.dirname(P300_MODEL_PATH) if dossier is None else dossier
    return p300_calib.chemins_libres(dossier, 0)[0]


def calibrate(app, rounds=P300_CAL_ROUNDS, reps=P300_REPS, save_path=None):
    """Calibration complète. En smoke : 2 manches × quelques flashs, fit léger, sauvegarde
    dans save_path (le _smoke de app.py passe un chemin _smoke). Retourne True si un modèle a
    été entraîné et sauvegardé.

    `save_path=None` -> un fichier HORODATÉ, jamais `data/p300_model.joblib` : voir
    `chemin_modele_horodate`.
    """
    save_path = save_path or chemin_modele_horodate()
    plan = p300_targets()
    n = len(plan)
    on_fr, off_fr = P300_FLASH_ON_FR, P300_FLASH_OFF_FR

    # câble/électrodes AVANT d'enregistrer (piège #0) ; voies clés P300 (Fz/Cz/Pz) encadrées
    if not app.smoke and not app.signal_check(highlight=P300_MIDLINE, mode_label="P300"):
        return False
    if not _briefing(app):
        return False

    spots = app.ring_spots(plan)
    rng = random.Random() if not app.smoke else random.Random(0)
    # ⚠️ **3 manches en smoke, pas 2, et le board PRÉ-REMPLI** (2026-09-08). Tant que cet écran
    # était appelé par le `_smoke` de `research/app.py`, il passait APRÈS quatre autres modes : le
    # board avait des secondes d'historique et les époques de la 1re manche sortaient. Lancé SEUL
    # (`python archive/p300_calibrate.py --smoke`), il flashe sur un tampon qui vient de s'ouvrir
    # et `epoch_from_stream` ne peut pas fournir leur pré-stimulus — mesuré : 1 époque sur 6 à la
    # manche 1, donc 7 au total, sous le plancher de `p300_calib` (12). L'entraînement était alors
    # REFUSÉ et le smoke imprimait « OK » quand même : un test qui n'exerçait plus rien.
    # `errp_calibrate.calibrate` porte la même seconde de pré-remplissage, pour la même raison.
    eff_rounds = 3 if app.smoke else rounds
    eff_reps = 1 if app.smoke else reps
    soa_s = (on_fr + off_fr) / app.refresh
    print(f"[p300-cal] {eff_rounds} manches × {n} cibles × {eff_reps} rép  "
          f"SOA={soa_s * 1000:.0f} ms  ~{eff_rounds * n * eff_reps * soa_s + eff_rounds * 3:.0f} s")

    epochs, labels, flashed, groups, cues = [], [], [], [], []
    fs = app.acq.fs
    if app.smoke:
        time.sleep(1.2)     # pré-remplir le board : voir le ⚠️ sur `eff_rounds` ci-dessus
    for r in range(eff_rounds):
        cue_idx = r % n
        cue_name = plan[cue_idx]["name"]
        cues.append(cue_idx)
        _intro(app, plan, spots, cue_name, r, eff_rounds)
        fl, t_start = _run_round(app, plan, spots, cue_name, eff_reps, on_fr, off_fr, rng)
        added = _collect(app, plan, spots, cue_name, fl, t_start, cue_idx, fs,
                         epochs, labels, flashed, groups, r)
        print(f"[p300-cal] manche {r + 1}/{eff_rounds} cible={cue_name}  {added} époques")

    if not app.smoke:   # fit + AUC + LORO enchaînent ~17 ré-entraînements : prévenir (écran figé)
        app.win.fill(BG)
        app.center(app.big, "Analyse...", FG, int(app.size[1] * 0.45))
        app.center(app.small, "entraînement du modèle et évaluation de la sélection", DIM,
                   int(app.size[1] * 0.55))
        app.pygame.display.flip()

    # L'entraînement vit dans `core/modes/p300_calib.py`, une seule fois pour les deux chemins
    # (cet écran et la calibration du moteur). Il LÈVE sur une séance trop pauvre, avec la phrase
    # qui dit quoi faire — on la montre telle quelle plutôt que d'en réécrire une ici.
    # ⚠️ En smoke : pas d'archive .npz (rien ne doit rester sur le disque) et pas d'évaluation
    # (~17 ré-entraînements, pour un test qui ne juge que le câblage).
    npz = None if app.smoke else p300_calib.chemins_libres(os.path.dirname(save_path), len(cues))[1]
    try:
        res = p300_calib.entrainer(epochs, labels, flashed, groups, cues, fs,
                                   chemin_modele=save_path, chemin_npz=npz,
                                   evaluer=not app.smoke)
    except ValueError as e:
        print(f"[p300-cal] {e}")
        if not app.smoke:
            app.flash("Calibration insuffisante", str(e), 4.5)
        return False

    t_sel = eff_reps * n * soa_s
    print(f"[p300-cal] modèle -> {os.path.basename(save_path)}"
          + (f"  époques -> {os.path.basename(npz)}" if npz else ""))
    if not app.smoke:
        _results(app, res["auc"], res["selection_ok"], res["selection_total"], t_sel, n)
    return True


def _parse(argv):
    p = argparse.ArgumentParser(
        description="Calibration P300 pygame (ARCHIVÉE — le moteur calibre désormais).")
    # ⚠️ `--model` EXPLICITE, et son défaut est HORODATÉ, jamais `P300_MODEL_PATH` : ce nom fixe
    # porte la trace de juillet, le seul modèle P300 enregistré au casque (cf.
    # `chemin_modele_horodate`). Le Motor Imagery a déjà perdu ses quatre modèles ainsi.
    p.add_argument("--model", default=None,
                   help="où écrire le modèle (défaut : un nom HORODATÉ dans data/)")
    p.add_argument("--rounds", type=int, default=P300_CAL_ROUNDS, help="nombre de manches")
    p.add_argument("--reps", type=int, default=P300_REPS, help="répétitions par manche")
    p.add_argument("--windowed", action="store_true", help="fenêtre au lieu du plein écran")
    p.add_argument("--synthetic", action="store_true", help="board de test (sans casque)")
    p.add_argument("--smoke", action="store_true", help="test headless (CI)")
    return p.parse_args(argv)


def main(argv=None):
    a = _parse(sys.argv[1:] if argv is None else argv)
    app = App(windowed=a.windowed, synthetic=a.synthetic, smoke=a.smoke)
    tmp, save_path = None, a.model
    # `data/` porte des enregistrements EEG d'une personne identifiable sur un dépôt public :
    # aucun test n'a le droit d'y écrire, et le plus récent modèle CHARGEABLE de `data/` est le
    # défaut que le moteur et la console proposent — un modèle de test oublié là se fait élire.
    empreinte_avant = empreinte_dossier(DATA_DIR) if a.smoke else None
    try:
        if a.smoke:
            tmp = tempfile.mkdtemp(prefix="p300_calibrate_smoke_")
            save_path = os.path.join(tmp, "p300_model_smoke.joblib")
        try:
            ok = calibrate(app, rounds=a.rounds, reps=a.reps, save_path=save_path)
        except Abort:
            ok = False
            print("[p300-cal] annulé.")
        if a.smoke:
            # ⚠️ Sans cette assertion, ce smoke MENT : `calibrate()` attrape la séance trop pauvre,
            # imprime « pas d'entraînement » et rend False, après quoi le fichier ne dit « OK »
            # que parce que rien n'a levé. Mesuré le 2026-09-08 : 7 époques au lieu de 12, aucun
            # modèle écrit, « smoke OK » imprimé quand même. On exige donc le FICHIER, et qu'il se
            # relise par le chemin RÉEL du moteur — celui qui refuse les modèles hérités.
            from core.p300_models import charger
            assert ok and os.path.exists(save_path), (
                f"la calibration n'a produit AUCUN modèle ({save_path}) : la séance de test est "
                f"passée sous le plancher d'époques, et l'entraînement n'a donc pas été exercé")
            modele, probleme = charger(save_path)
            assert modele is not None, (
                f"...et le modèle produit doit être ACCEPTÉ par `p300_models.charger`, sinon il "
                f"n'apparaîtrait dans aucune liste : {probleme}")
    finally:
        app.close()
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    if a.smoke:
        _invariants_smoke()
        empreinte_apres = empreinte_dossier(DATA_DIR)
        assert empreinte_apres == empreinte_avant, (
            f"ce smoke a touché data/ — il doit écrire UNIQUEMENT dans le dossier temporaire "
            f"ci-dessus : {set(empreinte_apres) ^ set(empreinte_avant) or 'contenu modifié'}")
        print("[p300-cal] smoke OK : manches + époques + entraînement câblés (headless).")
    return True


def _invariants_smoke():
    """Les deux invariants montés ici AVEC l'écran qu'ils protègent (ils vivaient dans le `_smoke`
    de `research/app.py`, supprimé)."""
    import fnmatch
    import inspect

    from core.p300_models import MOTIF

    # 1. Une calibration n'écrase JAMAIS `data/p300_model.joblib` — la trace de juillet, seul
    #    modèle P300 enregistré au casque. Le MI a déjà perdu ses quatre modèles ainsi.
    horodate = chemin_modele_horodate()
    assert horodate != P300_MODEL_PATH, (
        f"une calibration P300 écrirait dans data/p300_model.joblib et écraserait la trace de "
        f"juillet ({horodate})")
    # ...et le nom horodaté doit rester VU par le moteur, sinon on préserve un fichier que
    # personne ne peut plus choisir.
    assert fnmatch.fnmatch(os.path.basename(horodate), MOTIF), (
        f"le modèle horodaté {os.path.basename(horodate)} ne correspond pas à p300_models.MOTIF "
        f"({MOTIF}) : il n'apparaîtrait dans aucune liste de modèles")
    # ...et c'est bien `calibrate` qui s'en sert quand personne ne lui donne de chemin. Vérifié
    # sur le TEXTE SOURCE et pas en l'exécutant : appeler `calibrate(app)` sans `save_path` pour
    # voir où il écrit, c'est exactement l'accident qu'on veut interdire.
    src = inspect.getsource(calibrate)
    assert "chemin_modele_horodate()" in src and "or P300_MODEL_PATH" not in src, (
        "calibrate() doit retomber sur chemin_modele_horodate() quand save_path est None")
    # 2. L'invariant oddball : l'ordre des flashs vient de `stimulus/p300.blocs_melanges` et n'est
    #    JAMAIS remélangé localement. Mesuré : sans garde de jonction, 72,0 % des manches
    #    contiennent au moins une répétition immédiate de la même cible.
    src_round = inspect.getsource(_run_round)
    assert "blocs_melanges" in src_round and "shuffle" not in src_round, (
        "_run_round doit tirer son ordre de `blocs_melanges` et ne pas remélanger localement — "
        "l'invariant oddball ne vaut que s'il est tenu aux TROIS endroits qui présentent ce "
        "stimulus (émetteur, calibration, pilotage)")


if __name__ == "__main__":
    from core.config import use_utf8_console
    use_utf8_console()
    main()
