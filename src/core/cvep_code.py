"""Codes c-VEP : génération de la m-séquence et affectation des lags aux cibles.

Le c-VEP (code-modulated VEP) remplace le clignotement périodique du SSVEP par une
**séquence pseudo-aléatoire** de ON/OFF, la même pour toutes les cibles mais **décalée
circulairement** (lag) pour chacune. On ne cherche donc plus une fréquence, mais un
DÉCALAGE : le cerveau produit une réponse en « empreinte » qu'on recale sur le code.

Pourquoi c'est intéressant ici :
  - la m-séquence a une autocorrélation **piquée** (pic à 0, ~0 partout ailleurs) : deux
    cibles décalées sont quasi orthogonales, donc très séparables ;
  - le spectre est **étalé** : aucune concurrence avec le pic alpha (~10.5 Hz chez toi),
    contrairement au SSVEP ;
  - une seule fixation calibre TOUTES les cibles (il suffit de re-décaler le template).
Coût : il faut une calibration (le SSVEP par CCA, lui, n'en demande aucune).

Référence : Bin et al. 2011, "A high-speed BCI based on code modulation VEP",
J. Neural Eng. 8(2):025015. https://doi.org/10.1088/1741-2560/8/2/025015

    python src/core/cvep_code.py            # autotest des propriétés du code (aucun écran requis)
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (CVEP_BITS, CVEP_LAG_ROTATION, CVEP_TAPS, cvep_lag_gap_ms,  # noqa: E402
                    cvep_lags, cvep_targets, use_utf8_console)


def m_sequence(n_bits=CVEP_BITS, taps=CVEP_TAPS):
    """m-séquence binaire de longueur 2^n_bits - 1 (LFSR de Fibonacci).

    `taps` = positions (1-indexées) XORées pour la rétroaction ; le couple par défaut
    correspond à un polynôme primitif => période MAXIMALE (pas de cycle court).
    Retourne un tableau d'entiers 0/1.
    """
    reg = [1] * n_bits
    out = []
    for _ in range(2 ** n_bits - 1):
        out.append(reg[-1])
        fb = 0
        for t in taps:
            fb ^= reg[t - 1]
        reg = [fb] + reg[:-1]
    return np.asarray(out, dtype=int)


def autocorrelation(code):
    """Autocorrélation circulaire du code en ±1. Pour une m-séquence : L au décalage 0,
    et exactement -1 partout ailleurs (c'est CE qui rend les lags séparables)."""
    x = 2 * np.asarray(code, dtype=float) - 1.0   # 0/1 -> -1/+1
    return np.asarray([float(np.dot(x, np.roll(x, k))) for k in range(len(x))])


def build_targets(commands=None, n_bits=CVEP_BITS, taps=CVEP_TAPS):
    """Plan c-VEP : cibles enrichies du `lag` (en frames) et du code déjà décalé.

    La cible j affiche, à la frame f, le bit `code[(f + lag_j) % L]`. Le décodeur
    inverse exactement cette convention (cf. cvep_decoder).

    Par défaut, les cibles viennent de `config.cvep_targets()` (couronne de N cibles) et NON
    de COMMANDS : le c-VEP n'est pas limité aux 3 commandes du SSVEP, c'est tout son intérêt.
    """
    cmds = cvep_targets() if commands is None else commands
    code = m_sequence(n_bits, taps)
    lags = cvep_lags(len(cmds), len(code))
    rot = CVEP_LAG_ROTATION % len(cmds)      # décale quel lag va sur quelle position à l'écran
    lags = lags[rot:] + lags[:rot]
    return [{**cmd, "lag": lag, "code": np.roll(code, -lag)}
            for cmd, lag in zip(cmds, lags)], code


def is_on(frame, target_code):
    """Bit à afficher pour cette cible à cette frame (équivalent c-VEP de `stimulus.ssvep.is_on`)."""
    return bool(target_code[frame % len(target_code)])


def blocs_entrelaces(plan, cycles, n_blocs, rng=None):
    """Le PLAN d'une calibration : `[(cible, nb de cycles), ...]`, dans un ordre MÉLANGÉ.

    Chaque cible est découpée en `n_blocs` blocs de `cycles // n_blocs` cycles, puis TOUS les
    blocs sont mélangés ensemble.

    ⚠️ **L'entrelacement n'est pas cosmétique.** Sans lui, chaque cible occupe une tranche de temps
    distincte et « quelle cible » devient indissociable de « à quel moment » : mesuré le
    2026-07-20, l'accuracy passait de 34 % sur le premier tiers de la séance à 66 % sur le dernier,
    ce qui faisait passer les deux dernières cibles pour les meilleures. C'était un artefact de
    protocole, pas un résultat.

    ⚠️ **Né dans `research/cvep_calibrate.py::_make_blocks`, monté ici parce qu'il a maintenant DEUX
    joueurs** : l'appli pygame et la fenêtre `src/stimulus/cvep.py` (que la console lance pour
    calibrer). Deux exemplaires de la même règle de protocole finiraient par diverger sans que
    personne le voie — les deux séances resteraient plausibles, et seule la comparaison de leurs
    modèles dirait qu'elles n'ont pas joué le même jeu. Même geste, même raison, que
    `core/errp_track.py` pour la piste de l'ErrP.

    `rng` : un `random.Random` (ou le module `random`). None -> le module. Le passer EXPLICITEMENT
    est ce qui rend une séance rejouable à l'identique avec `--seed`.
    """
    import random as _random

    rng = _random if rng is None else rng
    par_bloc = max(1, int(cycles) // int(n_blocs))
    blocs = []
    for cible in plan:
        reste = int(cycles)
        for b in range(int(n_blocs)):
            n = reste if b == int(n_blocs) - 1 else min(par_bloc, reste)
            if n > 0:
                blocs.append((cible, n))
            reste -= n
    rng.shuffle(blocs)
    return blocs


# --- Autotest (aucun casque, aucun écran) ---------------------------------

def _selftest():
    code = m_sequence()
    L = len(code)
    ones = int(code.sum())
    ac = autocorrelation(code)
    side = ac[1:]
    plan, _ = build_targets()

    print(f"[cvep] m-séquence : n_bits={CVEP_BITS} taps={CVEP_TAPS} -> longueur L={L}")
    print(f"[cvep] équilibre  : {ones} uns / {L - ones} zéros  (attendu {2**(CVEP_BITS-1)}/"
          f"{2**(CVEP_BITS-1)-1})")
    print(f"[cvep] autocorr   : pic={ac[0]:.0f}  lobes latéraux min={side.min():.0f} "
          f"max={side.max():.0f}  (attendu -1 partout)")
    gap = cvep_lag_gap_ms(len(plan), L)
    print(f"[cvep] à 60 Hz    : cycle = {L}/60 = {L/60:.3f} s  -> {60/L:.2f} décisions/s max")
    print(f"[cvep] {len(plan)} cibles  : écart entre lags voisins = {gap:.0f} ms "
          f"({'OK, > durée VEP ~150 ms' if gap >= 150 else 'RISQUÉ, < durée VEP ~150 ms'})")
    for c in plan:
        print(f"[cvep]   {c['name']:<10} lag={c['lag']:>3} frames ({c['lag']/60*1000:>5.0f} ms) "
              f"jx={c['jx']:+.2f} jy={c['jy']:+.2f}  "
              f"code[0:12]={''.join(map(str, c['code'][:12]))}")

    ok = True
    ok &= (ones == 2 ** (CVEP_BITS - 1))            # équilibre exact d'une m-séquence
    ok &= bool(np.all(side == -1.0))                # autocorrélation à deux niveaux
    ok &= (ac[0] == L)
    ok &= (len({c["name"] for c in plan}) == len(plan))   # noms de cibles distincts
    ok &= (gap >= 150.0)                            # séparation > durée d'une réponse VEP

    # --- le PLAN d'une calibration : mêmes cycles pour tous, et VRAIMENT entrelacé -------------
    import random as _random

    from core.config import CVEP_CAL_BLOCKS, CVEP_CAL_CYCLES

    blocs = blocs_entrelaces(plan, CVEP_CAL_CYCLES, CVEP_CAL_BLOCKS, _random.Random(0))
    par_cible = {}
    for cible, n in blocs:
        par_cible[cible["name"]] = par_cible.get(cible["name"], 0) + n
    total_ok = set(par_cible.values()) == {CVEP_CAL_CYCLES} and len(par_cible) == len(plan)
    ok &= total_ok
    # L'entrelacement lui-même : sans lui, les blocs sortiraient groupés par cible, et « quelle
    # cible » ne se distinguerait plus de « à quel moment » (mesuré : 34 % -> 66 % du premier au
    # dernier tiers d'une séance NON entrelacée, le 2026-07-20).
    groupes = [nom for nom, _g in
               [(c["name"], None) for c, _n in blocs]]
    tranches = 1 + sum(1 for a, b in zip(groupes, groupes[1:]) if a != b)
    entrelace = tranches > len(plan)
    ok &= entrelace
    print(f"[cvep] calibration : {len(blocs)} blocs, {CVEP_CAL_CYCLES} cycles par cible "
          f"({'équilibré' if total_ok else 'DÉSÉQUILIBRÉ : ' + str(par_cible)}), "
          f"{tranches} tranches pour {len(plan)} cibles "
          f"({'entrelacé' if entrelace else 'PAS ENTRELACÉ — artefact de protocole'})")

    print("[cvep] autotest :", "OK" if ok else "ÉCHEC")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if _selftest() else 1)
