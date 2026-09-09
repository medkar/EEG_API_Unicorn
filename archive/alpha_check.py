"""Contrôle alpha en ligne de commande (effet de Berger) — REMPLACÉ par une mesure du moteur.

Ce fichier vivait comme `src/research/alpha_check.py`. Depuis le 2026-09-09, le contrôle alpha est
une MESURE que le moteur joue et que la console pilote : tuile « Contrôle alpha » de la grille,
`core/modes/alpha.py` pour le calcul. Le protocole y a été repris TEL QUEL — 3 s de préparation,
8 s yeux ouverts, 3 s, 8 s yeux fermés ; bande 8-12 Hz ; pic cherché entre 6 et 14 Hz ; repère
« ratio > ~1,5 » —, parce que c'est sous ces durées-là que le repère a été observé sur ce casque.

⚠️ **Il est gardé ici pour la même raison que les autres écrans archivés** : c'est la référence
contre laquelle la mesure du moteur a été écrite. Son calcul (`_welch`, `_band_power`, la sélection
des voies) est le même, ligne pour ligne. Le jour où la mesure du moteur rendrait un chiffre
surprenant, comparer avec CE fichier sépare « le calcul a changé » de « la séance a changé ».

Ce que la version du moteur fait EN PLUS, et qu'on ne retrouvera pas ici :
  • un **top sonore** à chaque changement de phase — indispensable, puisque la moitié de la mesure
    se passe les yeux fermés, où l'écran ne sert plus à rien (ce fichier-ci n'affiche que du texte,
    et le sujet ne peut pas le lire au moment où il compte) ;
  • le **détrend est déjà là** (il y était), mais le moteur **refuse** en plus une liaison morte :
    quatre voies plates donnent ~10⁻²⁷ de puissance des deux côtés, donc un rapport de bruit
    d'arrondi qui franchit la barrière une fois sur deux. Ici, ce cas rend un chiffre ;
  • le pic mesuré s'**applique d'un clic** au réglage « Pic alpha » du SSVEP. Ici, il faut le noter
    et le retaper.

⚠️ Ne jamais le lancer en même temps que le moteur, la console ou un autre écran archivé : il ouvre
le casque LUI-MÊME, et l'Unicorn n'accepte qu'une connexion.

    python archive/alpha_check.py             # casque réel, à suivre en direct dans un terminal
    python archive/alpha_check.py --smoke     # test headless (CI) : le calcul, sans casque

Prérequis pour une vraie passe : casque bien porté, électrodes du fond de crâne plaquées
(gel/pression), immobile.
"""

import argparse
import os
import sys
import time

import numpy as np
from brainflow.data_filter import DataFilter, DetrendOperations, NoiseTypes

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))      # -> src/
from core.acquisition import UnicornAcquisition  # noqa: E402
from core.config import DATA_DIR, empreinte_dossier, use_utf8_console  # noqa: E402


def _welch(x, fs, seg_s=2.0):
    """PSD (Welch : segments Hann 50% overlap) d'un signal 1D. Retourne (freqs, psd)."""
    n = len(x)
    seg = min(n, int(seg_s * fs))
    win = np.hanning(seg)
    step = max(1, seg // 2)
    powers = []
    for start in range(0, n - seg + 1, step):
        spec = np.fft.rfft(x[start:start + seg] * win)
        powers.append(np.abs(spec) ** 2)
    if not powers:  # signal plus court qu'un segment
        spec = np.fft.rfft(x * np.hanning(n))
        return np.fft.rfftfreq(n, 1 / fs), np.abs(spec) ** 2
    return np.fft.rfftfreq(seg, 1 / fs), np.mean(powers, axis=0)


def _clean(sig, fs):
    """Detrend + notch 50 Hz par voie (on garde le large bande pour VOIR le pic alpha)."""
    out = np.ascontiguousarray(sig, dtype=np.float64)
    for c in range(out.shape[1]):
        col = np.ascontiguousarray(out[:, c])
        DataFilter.detrend(col, DetrendOperations.CONSTANT.value)
        DataFilter.remove_environmental_noise(col, fs, NoiseTypes.FIFTY.value)
        out[:, c] = col
    return out


def _record_psd(acq, seconds):
    """Enregistre `seconds` s, renvoie (freqs, psd moyenne sur les voies occipitales)."""
    n = int(seconds * acq.fs)
    time.sleep(seconds)
    data = acq.board.get_current_board_data(n)
    sig = _clean(data[acq.occ_rows, :].T, acq.fs)
    psds = []
    for c in range(sig.shape[1]):
        freqs, psd = _welch(sig[:, c], acq.fs)
        psds.append(psd)
    return freqs, np.mean(psds, axis=0)


def _phase(acq, label, seconds=8, prep=3):
    for k in range(prep, 0, -1):
        print(f"  {label} dans {k}...", flush=True)
        time.sleep(1)
    print(f"  >>> {label} MAINTENANT — immobile pendant {seconds}s", flush=True)
    return _record_psd(acq, seconds)


def _band_power(freqs, psd, lo, hi):
    m = (freqs >= lo) & (freqs < hi)
    return float(psd[m].sum())


def _ascii_spectrum(freqs, psd, lo=5.0, hi=15.0, width=44):
    m = (freqs >= lo) & (freqs <= hi)
    fb, pb = freqs[m], psd[m]
    peak = pb.max() if pb.size else 1.0
    print(f"  spectre yeux fermés {lo:.0f}-{hi:.0f} Hz (barre = puissance relative) :")
    for fr, pw in zip(fb, pb):
        bar = "#" * int(round(width * pw / peak)) if peak > 0 else ""
        mark = "  <- alpha" if 8 <= fr <= 12 else ""
        print(f"   {fr:5.1f} Hz | {bar}{mark}")


def main():
    with UnicornAcquisition() as acq:
        print(f"[alpha] casque OK, voies {acq.occ_names}. Test de l'alpha occipital (~10 Hz).")
        print("[alpha] Reste immobile, fixe l'écran. On fait OUVERT puis FERMÉ.\n")
        time.sleep(1.5)

        f, p_open = _phase(acq, "YEUX OUVERTS")
        print()
        f, p_closed = _phase(acq, "YEUX FERMÉS")

        a_open = _band_power(f, p_open, 8, 12)
        a_closed = _band_power(f, p_closed, 8, 12)
        band = (f >= 6) & (f <= 14)
        peak_open = f[band][np.argmax(p_open[band])]
        peak_closed = f[band][np.argmax(p_closed[band])]
        ratio = a_closed / a_open if a_open > 0 else float("inf")

        print(f"\n== Résultat alpha (8-12 Hz, moyenne {'/'.join(acq.occ_names)}) ==")
        print(f"  puissance yeux OUVERTS : {a_open:.3e}   (pic 6-14 Hz @ {peak_open:.1f} Hz)")
        print(f"  puissance yeux FERMÉS  : {a_closed:.3e}   (pic 6-14 Hz @ {peak_closed:.1f} Hz)")
        print(f"  ratio fermé/ouvert     : {ratio:.2f}   (attendu > ~1.5)\n")
        _ascii_spectrum(f, p_closed)

        ok = ratio > 1.5 and 8.0 <= peak_closed <= 12.5
        print("\n[alpha] " + (
            "OK — électrodes en contact, voies bonnes, signal exploitable pour le SSVEP."
            if ok else
            "alpha peu marqué : vérifier le contact PO7/Oz/PO8 (gel/pression), l'immobilité "
            "et que les yeux sont bien fermés, puis relancer."))
        return ok


def _smoke():
    """Le CALCUL, sans casque et sans attendre 22 s : c'est la seule chose que l'archive garde.

    ⚠️ Aucun board ici, pas même le synthétique : `main()` dort 22 secondes par construction (le
    protocole EST cette attente), et un smoke qui dort 22 s est un smoke qu'on finit par désactiver.
    Ce qui doit rester vérifiable, c'est que `_welch` + `_band_power` retrouvent une raie qu'on a
    posée — donc que ce fichier reste comparable à `core/modes/alpha.py`, ce pour quoi il est gardé.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    empreinte_avant = empreinte_dossier(DATA_DIR)
    # ⚠️ `fs` ENTIER, et ce n'est pas un détail de style : `DataFilter.remove_environmental_noise`
    # refuse un flottant (« wrong type for sampling rate »). En séance ce fichier reçoit
    # `acq.fs`, qui vient de `BoardShim.get_sampling_rate` et EST un entier — la mesure du moteur,
    # elle, reçoit un `float(engine.acq.fs)` et doit donc le reconvertir (cf. `alpha._nettoyer`).
    fs, n = 250, 2000
    rng = np.random.default_rng(20260909)
    t = np.arange(n) / fs
    ouvert = rng.normal(0.0, 8.0, (n, 4))
    ferme = rng.normal(0.0, 8.0, (n, 4)) + (4.0 * np.sin(2 * np.pi * 10.5 * t))[:, None]

    def psd(bloc):
        sig = _clean(bloc, fs)
        freqs, psds = None, []
        for c in range(sig.shape[1]):
            freqs, p = _welch(sig[:, c], fs)
            psds.append(p)
        return freqs, np.mean(psds, axis=0)

    f, p_ouvert = psd(ouvert)
    _f, p_ferme = psd(ferme)
    ratio = _band_power(f, p_ferme, 8, 12) / _band_power(f, p_ouvert, 8, 12)
    band = (f >= 6) & (f <= 14)
    pic = float(f[band][np.argmax(p_ferme[band])])

    chk(ratio > 1.5, f"une raie posée à 10,5 Hz fait monter la bande alpha (ratio {ratio:.2f})")
    chk(abs(pic - 10.5) < 1.0, f"…et le pic est retrouvé là où on l'a mis ({pic:.1f} Hz)")
    _ascii_spectrum(f, p_ferme)
    chk(empreinte_dossier(DATA_DIR) == empreinte_avant, "ce smoke n'a rien touché dans data/")

    print(f"[alpha-check] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--smoke", action="store_true", help="test headless (CI) : le calcul, sans casque")
    a = p.parse_args()
    sys.exit(0 if (_smoke() if a.smoke else main()) else 1)
