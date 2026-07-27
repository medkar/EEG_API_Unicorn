"""Sanity check EEG : pic alpha occipital (~10 Hz) yeux fermés vs yeux ouverts.

But — AVANT tout SSVEP, confirmer d'un seul test que :
  (a) les électrodes PO7/Oz/PO8 touchent bien le cuir chevelu,
  (b) l'ordre des voies est correct,
  (c) le signal est exploitable.
Test de référence = effet de Berger : l'alpha (~8-12 Hz) monte franchement quand on ferme
les yeux. Si on voit ça sur les voies occipitales, le casque est prêt pour le SSVEP.

⚠️ À lancer EN DIRECT dans un terminal (il faut suivre les consignes yeux ouverts/fermés) :
    python src/research/alpha_check.py

Prérequis : casque bien porté, électrodes du fond de crâne plaquées (gel/pression), immobile.
"""

import os
import sys
import time

import numpy as np
from brainflow.data_filter import DataFilter, DetrendOperations, NoiseTypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.acquisition import UnicornAcquisition  # noqa: E402
from core.config import use_utf8_console  # noqa: E402


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

        print("\n== Résultat alpha (8-12 Hz, moyenne PO7/Oz/PO8) ==")
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


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if main() else 1)
