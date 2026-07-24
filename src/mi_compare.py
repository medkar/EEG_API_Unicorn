"""Compare les méthodes MI (CSP vs Riemannien) sur une calibration enregistrée.

CV « par essai » (GroupKFold : les fenêtres d'un même essai restent ensemble -> pas de fuite
-> estimation honnête). Sert à choisir la méthode sur TES données réelles après calibration.

    python src/mi_compare.py                    # data/mi_calib_last.npz
    python src/mi_compare.py --drop 10           # ignore les 10 premiers essais (échauffement)
    python src/mi_compare.py --sweep             # teste l'hypothèse "meilleur à la fin"
    python src/mi_compare.py chemin/vers.npz
"""

import argparse
import os
import sys

import numpy as np
from sklearn.model_selection import GroupKFold, cross_val_score

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import MI_REREF, MI_WINDOW_S, use_utf8_console  # noqa: E402
from mi_decoder import MI_BAND, bandpass, build_pipe, reref  # noqa: E402


def _windows(epochs, labels, fs):
    n, step = int(MI_WINDOW_S * fs), int(1.0 * fs)
    X, y, g = [], [], []
    for gi, (ep, lab) in enumerate(zip(epochs, labels)):
        for i in range(0, len(ep) - n + 1, step):
            X.append(ep[i:i + n].T)          # (n_ch, n_samp)
            y.append(str(lab))
            g.append(gi)
    Xf = bandpass(reref(np.asarray(X), MI_REREF), fs, MI_BAND)   # même re-ref que le pipeline réel
    return Xf, np.asarray(y), np.asarray(g)


def _cv(Xf, y, g, method, k):
    return cross_val_score(build_pipe(method), Xf, y,
                           cv=GroupKFold(min(k, len(np.unique(g)))), groups=g).mean()


def _row(epochs, labels, fs, tag, k=5):
    Xf, y, g = _windows(epochs, labels, fs)
    print(f"{tag:<20} n={len(epochs):>3}  csp={_cv(Xf, y, g, 'csp', k)*100:5.1f}%  "
          f"riemann={_cv(Xf, y, g, 'riemann', k)*100:5.1f}%")


def compare(path, drop=0):
    d = np.load(path, allow_pickle=True)
    fs = float(d["fs"])
    print(f"{os.path.basename(path)} — CV par essai (chance 3 classes = 33%) — re-ref={MI_REREF}")
    _row(d["epochs"][drop:], d["labels"][drop:], fs, f"drop {drop} premiers")


def sweep(path):
    d = np.load(path, allow_pickle=True)
    epochs, labels, fs = d["epochs"], d["labels"], float(d["fs"])
    print(f"{os.path.basename(path)} — hypothèse « meilleur à la fin » (CV par essai)")
    for drop in (0, 5, 10, 15):
        _row(epochs[drop:], labels[drop:], fs, f"drop {drop} premiers")
    h = len(epochs) // 2
    _row(epochs[:h], labels[:h], fs, "1re moitié", k=3)
    _row(epochs[h:], labels[h:], fs, "2e moitié", k=3)


if __name__ == "__main__":
    use_utf8_console()
    p = argparse.ArgumentParser(description="Comparaison méthodes MI (EEG Waffle).")
    p.add_argument("path", nargs="?", help="fichier .npz (défaut : data/mi_calib_last.npz)")
    p.add_argument("--drop", type=int, default=0, help="ignore les N premiers essais")
    p.add_argument("--sweep", action="store_true", help="analyse échauffement (drop + moitiés)")
    a = p.parse_args(sys.argv[1:])
    path = a.path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "data", "mi_calib_last.npz")
    sweep(path) if a.sweep else compare(path, a.drop)
