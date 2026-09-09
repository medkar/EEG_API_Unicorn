"""Sélection P300 par oddball (xDAWN+Riemann) — l'écran de PILOTAGE retiré de l'appli unifiée.

Ce module vivait comme `mode_p300` dans `src/research/app.py`, supprimé le 2026-09-08. Le P300 est
maintenant DÉCODÉ par le MOTEUR (`python src/core/server.py --mode p300` -> flux `decoded_p300`),
sur les marqueurs de `src/stimulus/p300.py`, et se pilote depuis la console. Ce fichier reste ici,
ENCORE EXÉCUTABLE, pour la même raison que `cvep_pilot.py` : c'est la RÉFÉRENCE de décodage LOCAL
contre laquelle une séance casque compare le décodage réseau — même modèle, mêmes cibles, deux
décodeurs indépendants qui doivent désigner la MÊME cible sur la même fixation.

⚠️ **La différence qui compte, et c'est elle qu'une séance mesure** : ici les époques sont découpées
sur l'horloge de PYGAME (`app.acq.get_raw`, l'écran horodate ses propres flashs), alors que le
moteur les découpe sur les horodatages LSL des marqueurs entrants. Les deux chemins doivent donner
la même réponse ; s'ils divergent, c'est l'alignement des époques qu'il faut regarder avant le
décodeur.

⚠️ Ne jamais le lancer en même temps que le moteur, la console ou un autre écran archivé : le casque
n'accepte qu'UNE connexion. Cet écran ouvre le casque LUI-MÊME.

    python archive/p300_pilot.py                       # plein écran, casque réel
    python archive/p300_pilot.py --model data/p300_model_20260817-135716.joblib
    python archive/p300_pilot.py --dynamic             # arrêt dynamique (plus rapide, expérimental)
    python archive/p300_pilot.py --synthetic           # sans casque (board de test BrainFlow)
    python archive/p300_pilot.py --smoke               # test headless (CI) : calibre puis pilote
"""

import argparse
import os
import shutil
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))      # -> src/
from core.config import (DATA_DIR, empreinte_dossier, P300_BURST_S,  # noqa: E402
                    P300_EPOCH_S, P300_FLASH_OFF_FR, P300_FLASH_ON_FR, P300_MIDLINE,
                    P300_MIN_REPS, P300_MODEL_PATH, P300_PRE_S, P300_REPS, P300_SELECT_MARGIN,
                    P300_STOP_MARGIN, UDP_HOST, p300_targets, use_utf8_console)
# La machinerie pygame partagée est le VOISIN `archive/ui.py` depuis le 2026-09-09 (elle était
# `research/ui.py`) : `research/` n'a plus le droit d'ouvrir le casque ni de dessiner. Nom de
# module NU, car Python met le dossier du script en tête de `sys.path`.
from ui import ACCENT, BAR_BG, BG, DIM, FG, GO, WARN, Abort, App  # noqa: E402


def _p300_ready(app, plan, spots, seconds=2.2):
    """Court écran « choisis ta cible » avant chaque sélection (anneau au repos, rien ne clignote)."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        app.drain()
        app.win.fill(BG)
        h = app.size[1]
        app.center(app.big, "Choisis ta cible", FG, int(h * 0.12))
        app.center(app.mid, "fixe-la et COMPTE ses éclairs — la sélection démarre", DIM,
                   int(h * 0.19))
        app.draw_ring(plan, spots, lambda c, f: False, 0)
        app.pygame.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return


def _p300_panel(app, order, scores, cmd):
    """Barres des scores « cible » par direction (log-odds moyens), gagnant en vert."""
    if not scores:
        return
    pg = app.pygame
    w, h = app.size
    lo = min(scores.values())
    span = max(1e-6, max(scores.values()) - lo)
    x, y, barw = int(w * 0.06), int(h * 0.66), int(w * 0.30)
    for i, name in enumerate(order):
        v = (scores.get(name, lo) - lo) / span
        ry = y + i * int(h * 0.045)
        pg.draw.rect(app.win, BAR_BG, (x + int(w * 0.16), ry, barw, 16))
        col = GO if (cmd and cmd["name"] == name) else ACCENT
        pg.draw.rect(app.win, col, (x + int(w * 0.16), ry, int(barw * v), 16))
        app.win.blit(app.small.render(f"{name:<10} {scores.get(name, 0.0):+5.2f}", True, FG),
                     (x, ry - 2))


def _p300_emit_burst(app, plan, spots, cmd, scores):
    """Exécute la commande sélectionnée en RAFALE pendant P300_BURST_S (ré-émission ~15 Hz pour
    le chien de garde de l'actionneur), puis STOP. Aucune commande nette -> rien émis."""
    order = [c["name"] for c in plan]
    t0 = time.perf_counter()
    last = 0.0
    while time.perf_counter() - t0 < P300_BURST_S:
        app.drain()
        now = time.perf_counter()
        if cmd and now - last >= 1.0 / 15.0:
            app.emit(cmd["jx"], cmd["jy"])
            last = now
        app.win.fill(BG)
        h = app.size[1]
        title = cmd["name"] if cmd else "—  (aucune sélection nette)"
        app.center(app.big, title, GO if cmd else DIM, int(h * 0.14))
        app.draw_ring(plan, spots, lambda c, f: False, 0, cue=(cmd["name"] if cmd else None))
        _p300_panel(app, order, scores, cmd)
        app.hud(f"P300 — exécution {P300_BURST_S:.1f}s   "
                f"{'⚠ UDP ROBOT ACTIF' if app.send else 'UDP off'}   ESC=menu",
                WARN if app.send else DIM)
        app.pygame.display.flip()
        app.clock.tick(int(app.refresh) + 5)
        if app.smoke:
            break
    app.emit(0.0, 0.0)


def _p300_margin(scores):
    """Marge = score du 1er - score du 2e (log-odds moyens). Critère d'arrêt dynamique."""
    vals = sorted(scores.values(), reverse=True)
    return (vals[0] - vals[1]) if len(vals) > 1 else float("inf")


def _p300_log_scores(scores, pick, by, reps):
    """Console : score moyen (log-odds « cible ») par direction, trié, + marge 1er-2e, nombre de
    répétitions utilisées et d'époques par cible. Diagnostique un biais fixe (une cible toujours
    en tête) vs un signal faible (marges minuscules), et montre l'économie de l'arrêt dynamique."""
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    margin = (ranked[0][1] - ranked[1][1]) if len(ranked) > 1 else 0.0
    print(f"[p300] pick={pick}  {reps} rép  marge_1er-2e={margin:+.2f}  "
          f"n_époques={ {nm: len(v) for nm, v in by.items()} }")
    print("        scores: " + "  ".join(f"{nm}={sc:+.2f}" for nm, sc in ranked))


def _p300_save_debug(debug, fs):
    """Sauve les époques live (par cible, par sélection) dans data/p300_live_last.npz, pour
    rejouer le décodage hors ligne — indispensable pour diagnostiquer le « toujours la même
    cible » sans monopoliser le casque."""
    eps, names, sel = [], [], []
    for si, (by, _scores, _pick) in enumerate(debug):
        for nm, arr in by.items():
            for e in arr:
                eps.append(np.asarray(e))
                names.append(nm)
                sel.append(si)
    if not eps:
        return
    path = os.path.join(os.path.dirname(P300_MODEL_PATH), "p300_live_last.npz")
    try:
        np.savez(path, epochs=np.asarray(eps), names=np.asarray(names),
                 sel=np.asarray(sel), fs=fs)
        print(f"[p300] {len(eps)} époques live sauvées -> {os.path.basename(path)} (diagnostic)")
    except OSError as e:   # best-effort, ne doit pas gêner la sortie du mode
        print(f"[p300] (sauvegarde debug live échouée : {e})")


def mode_p300(app, model_path=None, dynamic=False):
    import random as _random

    # `p300_calibrate` est le FICHIER VOISIN, dans `archive/` : les deux écrans partagent la
    # couronne et le flash, et ils ont été archivés ensemble le 2026-09-08. Même patron que
    # `mi_pilot.py`, qui importe `mi_calibrate` de la même façon.
    from p300_calibrate import _blank_ring, _flash_targets
    from stimulus.p300 import blocs_melanges
    from core.p300_decoder import epoch_from_stream
    from core.p300_models import charger, modeles_disponibles

    # `model_path=None` -> le PLUS RÉCENT des modèles réellement chargeables. Le défaut était
    # `P300_MODEL_PATH`, un nom fixe que la calibration n'écrit plus (elle horodate désormais,
    # cf. `p300_calibrate.chemin_modele_horodate`) : garder ce défaut aurait fait pointer le
    # mode sur la trace de juillet, précisément le modèle que `charger` refuse.
    if model_path is None:
        dispo = modeles_disponibles()
        model_path = dispo[0] if dispo else P300_MODEL_PATH

    # `os.path.exists` ne suffit pas : un modèle antérieur au déménagement du décodeur dans
    # core/ (2026-08-17) EXISTE toujours sur le disque mais ne se charge plus (pickle sous
    # l'ancien module nu `p300_decoder`) -> `P300Model.load` lèverait en pleine séance, après le
    # signal_check. `charger` ne lève jamais et dit quoi faire (ré-entraîner depuis une calibration).
    model, probleme = charger(model_path)
    if model is None:
        app.flash("Pas de modèle P300 utilisable",
                  probleme or "lance d'abord « P300 -> Calibrer » (~4-5 min)", 4.0)
        return
    if not app.signal_check(highlight=P300_MIDLINE, mode_label="P300"):
        return                    # liaison + voies clés (Fz/Cz/Pz) ; casque KO ou ESC -> retour
    plan = p300_targets()
    n = len(plan)
    spots = app.ring_spots(plan)
    name_to_cmd = {c["name"]: c for c in plan}
    on_fr, off_fr = P300_FLASH_ON_FR, P300_FLASH_OFF_FR
    rng = _random.Random()
    fs = app.acq.fs
    soa = (on_fr + off_fr) / app.refresh
    auc = "?" if model.cv_auc_ is None else f"{model.cv_auc_*100:.0f}%"
    mode = (f"ARRÊT DYNAMIQUE (min {P300_MIN_REPS}, max {P300_REPS} rép, marge {P300_STOP_MARGIN})"
            if dynamic else f"{P300_REPS} rép fixes (~{P300_REPS*n*soa:.1f}s)")
    print(f"[p300] {n} cibles  SOA={soa*1000:.0f}ms  AUC calib={auc}  {mode}")

    def extract(all_flashes, extracted, by, t_start):
        """Découpe les époques désormais COMPLÈTES (post-stim rempli) pas encore extraites."""
        eeg, ts = app.acq.get_raw(time.time() - t_start + P300_PRE_S + 0.5)
        if eeg is None:
            return
        for i, (t, onset) in enumerate(all_flashes):
            if i in extracted:
                continue
            ep = epoch_from_stream(eeg, ts, onset, fs)
            if ep is not None:
                by[plan[t]["name"]].append(ep)
                extracted.add(i)

    debug = []          # (by, scores, pick) par sélection -> sauvés à la sortie pour diagnostic
    try:
        while True:
            _p300_ready(app, plan, spots)
            by = {c["name"]: [] for c in plan}
            all_flashes, extracted = [], set()
            t_start = time.time()
            used = P300_REPS
            # Même invariant oddball qu'à la calibration et qu'à l'émetteur, et depuis la MÊME
            # fonction : aucune cible deux fois de suite, jonctions entre répétitions comprises.
            # Les blocs sont tirés d'avance pour toute la manche — l'arrêt dynamique peut sortir
            # de la boucle plus tôt, ce qui ne change rien à la contrainte de jonction.
            for rep, bloc in enumerate(blocs_melanges(n, P300_REPS, rng)):
                all_flashes += _flash_targets(app, plan, spots, None, bloc, on_fr, off_fr)
                if dynamic:      # accumule au fil de l'eau et stoppe si la cible se détache
                    extract(all_flashes, extracted, by, t_start)
                    if rep + 1 >= P300_MIN_REPS and all(len(v) >= P300_MIN_REPS
                                                        for v in by.values()):
                        _, sc = model.select(by)
                        if _p300_margin(sc) >= P300_STOP_MARGIN:
                            used = rep + 1
                            break
                if app.smoke:
                    used = rep + 1
                    break
            _blank_ring(app, plan, spots, None, int(round((P300_EPOCH_S + 0.15) * app.refresh)))
            extract(all_flashes, extracted, by, t_start)     # récupère les derniers flashs
            if any(by.values()):
                pick, scores = model.select(by, margin=P300_SELECT_MARGIN)
                _p300_log_scores(scores, pick, by, used)
                debug.append((by, scores, pick))
                _p300_emit_burst(app, plan, spots, name_to_cmd.get(pick), scores)
            if app.smoke:
                return
    except Abort:
        app.emit(0.0, 0.0)
        _p300_save_debug(debug, fs)                        # capture les époques live (diagnostic)
        return


def _parse(argv):
    p = argparse.ArgumentParser(
        description="Sélection P300 (ARCHIVÉ — référence de décodage local).")
    # ⚠️ `--model` EXPLICITE, et son défaut n'est pas un nom fixe : `None` -> le plus récent des
    # modèles réellement CHARGEABLES (cf. `mode_p300`). Le défaut historique était
    # `P300_MODEL_PATH`, c'est-à-dire la trace de juillet, que `p300_models.charger` refuse.
    p.add_argument("--model", default=None,
                   help="chemin du modèle P300 (défaut : le plus récent chargeable de data/)")
    p.add_argument("--dynamic", action="store_true",
                   help="arrêt dynamique : stoppe dès que la cible se détache")
    p.add_argument("--windowed", action="store_true", help="fenêtre au lieu du plein écran")
    p.add_argument("--send", action="store_true", help="armer l'envoi UDP dès le lancement")
    p.add_argument("--synthetic", action="store_true", help="board de test (sans casque)")
    p.add_argument("--host", default=UDP_HOST, help="hôte de l'actionneur UDP")
    p.add_argument("--smoke", action="store_true", help="test headless (CI)")
    return p.parse_args(argv)


def main(argv=None):
    a = _parse(sys.argv[1:] if argv is None else argv)
    app = App(windowed=a.windowed, synthetic=a.synthetic, smoke=a.smoke, send=a.send,
              host=a.host)
    tmp, model_path = None, a.model
    # `data/` porte des enregistrements EEG d'une personne identifiable sur un dépôt public :
    # aucun test n'a le droit d'y écrire. Vérifié, jamais supposé — c'est ce mécanisme-là qui
    # manquait le jour où ce projet a perdu quatre modèles Motor Imagery.
    empreinte_avant = empreinte_dossier(DATA_DIR) if a.smoke else None
    try:
        if a.smoke:
            # Un modèle chargeable n'existe pas forcément (dépôt fraîchement cloné) : on en
            # calibre un minuscule, headless, dans un dossier TEMPORAIRE — jamais dans `data/`.
            import p300_calibrate
            tmp = tempfile.mkdtemp(prefix="p300_pilot_smoke_")
            model_path = os.path.join(tmp, "p300_model_smoke.joblib")
            p300_calibrate.calibrate(app, save_path=model_path)
        # ⚠️ `mode_p300` sort AVANT sa boucle live si aucun modèle n'est chargeable — via un
        # `app.flash(...)` puis un `return`, donc SANS exception. Un smoke qui se contente de
        # constater l'absence de traceback ne prouve alors RIEN : « smoke OK », exit 0, boucle
        # jamais exercée. Même parade que `cvep_pilot.py` : on espionne `app.flash`.
        avortements = []
        flash_reel = app.flash

        def _flash_espion(titre, *a2, **kw2):
            if titre.startswith(("Pas de modèle", "Modèle")):
                avortements.append(titre)
            return flash_reel(titre, *a2, **kw2)

        app.flash = _flash_espion
        try:
            mode_p300(app, model_path=model_path, dynamic=a.dynamic)
            if a.smoke:
                mode_p300(app, model_path=model_path, dynamic=True)   # l'autre chemin
        except Abort:
            pass
        finally:
            app.flash = flash_reel
        if a.smoke:
            assert not avortements, (
                f"mode_p300 a été refusé SILENCIEUSEMENT ({avortements}) — il serait sorti AVANT "
                f"sa boucle live, et rien d'autre que cette assertion ne l'aurait remarqué")
    finally:
        app.close()
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    if a.smoke:
        # L'invariant oddball, monté ici AVEC l'écran qu'il protège (il vivait dans le `_smoke` de
        # `research/app.py`) : l'ordre des flashs vient de `stimulus/p300.blocs_melanges` et n'est
        # JAMAIS remélangé localement. Vérifié sur le TEXTE SOURCE parce que c'est la propriété
        # « une seule source » qu'on veut tenir — un `rng.shuffle` réapparu ici passerait tous les
        # tests de séquence, qui ne regardent que l'émetteur. Mesuré : sans garde de jonction,
        # 72,0 % des manches contiennent une répétition immédiate de la même cible.
        import inspect
        src = inspect.getsource(mode_p300)
        assert "blocs_melanges" in src and "shuffle" not in src, (
            "mode_p300 doit tirer son ordre de `blocs_melanges` et ne pas remélanger localement — "
            "l'invariant oddball ne vaut que s'il est tenu aux TROIS endroits qui présentent ce "
            "stimulus (émetteur, calibration, pilotage)")
        empreinte_apres = empreinte_dossier(DATA_DIR)
        assert empreinte_apres == empreinte_avant, (
            f"ce smoke a touché data/ — la calibration doit écrire UNIQUEMENT dans le dossier "
            f"temporaire ci-dessus, jamais dans data/ (dossier gitignoré, mais qui porte des "
            f"enregistrements EEG d'une personne identifiable) : "
            f"{set(empreinte_apres) ^ set(empreinte_avant) or 'contenu modifié'}")
        print("[p300-pilot] smoke OK : calibration + sélection (fixe et dynamique) câblées "
              "(headless).")
    return True


if __name__ == "__main__":
    use_utf8_console()
    main()
