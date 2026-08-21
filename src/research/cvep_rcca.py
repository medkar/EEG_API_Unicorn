"""c-VEP variante CODES GOLD DISTINCTS — l'hypothèse RÉFUTÉE, gardée lisible.

⚠️ **Ce fichier ne contient plus le décodeur, ni la calibration.** `RCCAModel` et `RCCADecoder`
sont partis dans `src/core/cvep_rcca.py` : le moteur en a besoin, donc ils suivent la règle du
déménagement. `calibrate_rcca` (l'écran pygame qui calibrait CETTE variante) est parti dans
`archive/cvep_rcca_pilot.py` (tâche 6) : la calibration au menu de `research/app.py` entraîne
désormais le rCCA sur le stimulus DÉCALÉ que le produit garde, ce qui rend cet écran-là redondant
— voir `archive/README.md` pour pourquoi il reste exécutable malgré tout. Ce qui reste ici, c'est
la **fabrique de codes Gold** et le plan de cibles qui va avec — c'est-à-dire la moitié de
l'hypothèse qui a été mesurée et **réfutée**.

Ce qui a été testé, et ce qui a été conclu :
  - stimulus classique : UNE m-séquence, décalée circulairement (un lag par cible). C'est le
    stimulus que le produit garde.
  - stimulus d'ICI : chaque cible affiche un CODE GOLD DIFFÉRENT (intercorrélation basse), décodé
    par RECONVOLUTION (rCCA de pyntbci) — on apprend une courte réponse transitoire commune à tous
    les codes, qui se transfère de l'un à l'autre. C'était LE cas où la reconvolution pouvait payer.

Verdict : **codes Gold = non**. Mais les deux moitiés de l'hypothèse (« rCCA » et « codes
distincts ») ont toujours été mesurées ENSEMBLE, et `RCCAModel` prend ses codes en paramètre — il
n'a jamais su d'où ils venaient. Rebranché sur le stimulus décalé, le rCCA fait jeu égal avec
l'eCCA (43/90 chacun, cf. `core/cvep_rcca.py`). C'est la moitié « codes Gold » qui était mauvaise.

⚠️ **Une hypothèse réfutée se garde LISIBLE, pas BRANCHÉE.** Depuis la tâche 6, le seul appelant de
`make_distinct_codes` / `build_targets_rcca` est `archive/cvep_rcca_pilot.py` — écran de calibration
ET de pilotage, archivé mais encore exécutable. C'est voulu : `cvep_models.charger` refuse
d'ailleurs tout modèle rCCA dont les codes ne sont pas ceux du stimulus affiché aujourd'hui, ce
qui met `data/cvep_rcca_model.npz` (calibré sur des codes Gold) définitivement hors de la liste
proposée à un étudiant.

    python src/research/cvep_rcca.py     # autotest sur c-VEP synthétique à codes distincts (aucun casque)
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import FS_UNICORN, use_utf8_console  # noqa: E402
# Le décodeur vit maintenant dans `core/`. Ré-exporté ici pour que `archive/cvep_rcca_pilot.py`
# continue de tourner sans dépendre directement de `core/` — un import qui casse ne rend personne
# plus savant sur une hypothèse réfutée.
from core.cvep_rcca import RCCADecoder, RCCAModel  # noqa: E402,F401  (ré-export)


def make_distinct_codes(n, seed_offset=0):
    """`n` codes Gold DISTINCTS de longueur 63 (pyntbci). Intercorrélation bornée -> séparables.

    Les codes Gold forment une famille où toutes les paires ont une intercorrélation basse, ce
    qui est exactement la propriété voulue pour des cibles à codes différents. ⚠️ Le produit ne
    les affiche plus : cf. la docstring du module.
    """
    import pyntbci.stimulus as st
    gold = np.asarray(st.make_gold_codes())          # (63, 63), valeurs 0/1
    if n > gold.shape[0]:
        raise ValueError(f"{n} codes demandés, {gold.shape[0]} disponibles")
    return gold[seed_offset:seed_offset + n].astype(int)


def build_targets_rcca(n=None):
    """Plan de cibles à CODES DISTINCTS : géométrie + joystick (cvep_targets) + un code Gold par
    cible. Retourne (plan, codes). Chaque cible porte `code` (pour l'affichage) et `idx`."""
    from core.config import CVEP_N_TARGETS, cvep_targets
    n = CVEP_N_TARGETS if n is None else int(n)
    geom = cvep_targets(n)                       # name, angle, jx, jy (même géométrie que le c-VEP classique)
    codes = make_distinct_codes(n)
    plan = [{**g, "code": codes[i].tolist(), "idx": i} for i, g in enumerate(geom)]
    return plan, codes


# --- Autotest sur c-VEP synthétique à codes distincts (aucun casque) ---------

def _vep_kernel(fs, dur=0.18):
    t = np.arange(int(dur * fs)) / fs
    return np.sin(2 * np.pi * t / dur) * np.exp(-t / (dur / 2))


def _synth(code_up, n_ch, fs, snr_db, rng, latency_s=0.06):
    n = len(code_up)
    drive = 2.0 * code_up - 1.0
    resp = np.convolve(drive, _vep_kernel(fs), "full")[:n]
    resp = np.roll(resp, int(round(latency_s * fs)))
    sig = np.outer(resp, rng.uniform(0.4, 1.0, n_ch))
    p = np.mean(sig ** 2) / (10 ** (snr_db / 10))
    return sig + rng.normal(0.0, np.sqrt(p), sig.shape)


def _demo(n_targets=6, n_ch=4, fs=FS_UNICORN, refresh=60.0, n_cal=12, n_test=48, seed=0):
    rng = np.random.default_rng(seed)
    codes = make_distinct_codes(n_targets)
    plan = [{"name": f"C{i+1}"} for i in range(n_targets)]
    model = RCCAModel(codes, fs=fs, refresh=refresh, channels=list(range(n_ch)))
    stim = model._stimulus()
    print(f"rCCA + codes distincts : {n_targets} codes Gold L={model.code_len} "
          f"cycle={model.code_len/refresh:.2f}s voies={n_ch}")

    for snr in (-6.0, -10.0, -14.0):
        ep = [_synth(stim[c], n_ch, fs, snr, rng) for c in range(n_targets) for _ in range(n_cal)]
        y = [c for c in range(n_targets) for _ in range(n_cal)]
        model = RCCAModel(codes, fs=fs, refresh=refresh, channels=list(range(n_ch))).fit(ep, y)
        dec = RCCADecoder(model, plan, n_cycles=1)
        ok = 0
        for _ in range(n_test):
            c = int(rng.integers(n_targets))
            w = _synth(stim[c], n_ch, fs, snr, rng)
            ok += int(np.argmax(model.scores(w, 0, 1)) == c)
        print(f"SNR {snr:+5.1f} dB | LOO {model.cv_*100:5.1f}% | argmax {ok/n_test*100:5.1f}% "
              f"(hasard {100/n_targets:.0f}%)")

    # Phase glissante : décodage hors frontière de cycle (le recalage doit compenser).
    #
    # ⚠️ Le `-` du `np.roll` ci-dessous était un `+`, et il CACHAIT un vrai défaut : le `scores`
    # d'origine recalait dans le mauvais sens, et cette ligne fabriquait sa fenêtre dans le
    # mauvais sens aussi — les deux erreurs s'annulaient ici, et seulement ici. Le pilotage en
    # ligne (`research/app.py::_cvep_decode`), lui, note à des phases quelconques avec la
    # convention de l'eCCA, donc à travers un alignement retourné. Le défaut a survécu parce que
    # cette ligne IMPRIME son résultat sans jamais l'affirmer. La convention, désormais commune
    # aux deux décodeurs : une fenêtre « à la phase p » est le signal AVANCÉ de p frames, donc
    # `np.roll(..., -shift(p))` (cf. `cvep_decoder._demo`, même geste).
    ep = [_synth(stim[c], n_ch, fs, -8.0, rng) for c in range(n_targets) for _ in range(n_cal)]
    model = RCCAModel(codes, fs=fs, refresh=refresh, channels=list(range(n_ch))).fit(
        ep, [c for c in range(n_targets) for _ in range(n_cal)])
    hits, phases = 0, range(0, model.code_len, 9)
    for p in phases:
        c = int(rng.integers(n_targets))
        w = np.roll(_synth(stim[c], n_ch, fs, -8.0, rng), -model._shift(p), axis=0)
        hits += int(np.argmax(model.scores(w, p, 1)) == c)
    print(f"\nPhase glissante : {hits}/{len(list(phases))} correct (recalage OK si ≈ tout)")

    # Persistance : save + reload + re-décode.
    #
    # ⚠️ Dans un dossier TEMPORAIRE, nettoyé dans un `finally`. Cette ligne écrivait
    # `data/cvep_rcca_smoke.npz` puis l'effaçait — sauf si l'autotest était interrompu, auquel cas
    # le fichier restait. `data/` porte les enregistrements EEG d'une personne identifiable sur un
    # dépôt PUBLIC : aucun test n'y écrit, même une seconde, même en promettant d'effacer. (Et
    # `git status` ne l'aurait jamais signalé : `data/` est entièrement gitignoré.)
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="cvep_rcca_demo_")
    try:
        path = model.save(os.path.join(tmp, "cvep_rcca_smoke.npz"))
        back = RCCAModel.load(path)
        same = np.array_equal(back.codes, model.codes) and back.n_targets == model.n_targets
        print(f"Save/reload : codes identiques={same}, LOO rechargé={back.cv_*100:.0f}%")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return True


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if _demo() else 1)
