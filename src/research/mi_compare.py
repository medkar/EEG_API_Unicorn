"""Compare les méthodes MI (CSP, Riemannien, FBCSP) sur une calibration enregistrée.

CV « par essai » (GroupKFold : les fenêtres d'un même essai restent ensemble -> pas de fuite
-> estimation honnête). Sert à choisir la méthode sur TES données réelles après calibration.

Chaque méthode reçoit ce que `MIModel._prep` lui donnerait en vrai : le signal re-référencé, puis
filtré dans MI_BAND pour CSP et Riemann, NON filtré pour FBCSP — son banc filtre lui-même, sous-bande
par sous-bande. Lui passer un signal déjà filtré le comparerait sur une cascade de deux filtres que
le produit n'applique jamais.

Toutes filtrent avec le COUPE-BANDE SECTEUR, comme le produit depuis le 2026-09-30 : celui que
l'enregistrement archive (`secteur_hz`, 0 = aucun), ou `config.SECTEUR_HZ` pour un enregistrement
d'avant ce champ — l'outil dit lequel. Le FBCSP est rejoué sur deux bandes : 8-30 Hz, la même que
les deux autres, et 4-40 Hz, celle que l'aide de « Entraîner » conseille pour lui laisser le choix.

C'est ICI, et pas avec « Tester », que CSP et FBCSP se départagent : sur UNE même séance, par
validation croisée. Deux entraînements suivis de deux tests mêleraient la différence de méthode à
celle entre deux séances, sur 18 à 30 essais qui ne séparent même pas 40 % de 33 %.

    python src/research/mi_compare.py                    # le mi_calib_*.npz le PLUS RÉCENT de data/
    python src/research/mi_compare.py --drop 10           # ignore les 10 premiers essais (échauffement)
    python src/research/mi_compare.py --sweep             # teste l'hypothèse "meilleur à la fin"
    python src/research/mi_compare.py chemin/vers.npz
"""

import argparse
import glob
import os
import sys

import numpy as np
from sklearn.model_selection import GroupKFold, cross_val_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (DATA_DIR, MI_REREF, MI_WINDOW_S, SECTEUR_HZ,  # noqa: E402
                         use_utf8_console)
from core.mi_decoder import MI_BAND, bandpass, build_pipe, reref  # noqa: E402

#: La bande large du FBCSP : celle que l'aide de « Entraîner » conseille, aux bornes du produit.
BANDE_LARGE = (4.0, 40.0)


def plus_recent(dossier=DATA_DIR):
    """Le `mi_calib_*.npz` le plus récent de `dossier`, ou None s'il n'y en a aucun.

    La calibration jouée par le moteur (`core/modes/mi_calib.py`) horodate chaque enregistrement
    — `mi_calib_last.npz`, le nom FIXE que ce chantier a supprimé, n'existe plus que sur les
    postes où l'ancien écran pygame archivé a tourné. Pointer dessus par défaut analyserait cette
    séance périmée indéfiniment, sans jamais le dire : ici, le PLUS RÉCENT par date de fichier,
    quel que soit son nom, et l'appelant DIT lequel il a retenu (cf. `__main__`).
    """
    chemins = sorted(glob.glob(os.path.join(dossier, "mi_calib_*.npz")),
                     key=os.path.getmtime, reverse=True)
    return chemins[0] if chemins else None


def _windows(epochs, labels, fs):
    """Les fenêtres RE-RÉFÉRENCÉES et NON filtrées : le filtre dépend de la méthode (cf. `_cv`)."""
    n, step = int(MI_WINDOW_S * fs), int(1.0 * fs)
    X, y, g = [], [], []
    for gi, (ep, lab) in enumerate(zip(epochs, labels)):
        for i in range(0, len(ep) - n + 1, step):
            X.append(ep[i:i + n].T)          # (n_ch, n_samp)
            y.append(str(lab))
            g.append(gi)
    Xr = reref(np.asarray(X), MI_REREF)      # même re-ref que le pipeline réel
    return Xr, np.asarray(y), np.asarray(g)


def secteur_de(d):
    """(secteur en Hz ou None, d'où il vient). Celui que l'enregistrement archive (0 = aucun
    coupe-bande), sinon `config.SECTEUR_HZ` — le défaut du produit — pour un `.npz` d'avant le
    2026-09-30, qui n'en porte pas. Dit, jamais deviné en silence : sur un poste à 60 Hz, ce défaut
    serait faux."""
    if "secteur_hz" in d.files:
        s = float(d["secteur_hz"])
        return (s or None), "archivé avec la séance"
    return SECTEUR_HZ, "NON archivé, séance d'avant le 2026-09-30 : défaut du produit"


def _cv(Xr, y, g, method, k, fs, band=MI_BAND, secteur_hz=None):
    # Le filtre de `MIModel._prep` : passe-bande global pour CSP/Riemann, aucun pour FBCSP (son
    # banc filtre, coupe-bande compris).
    X = Xr if method == "fbcsp" else bandpass(Xr, fs, band, secteur_hz=secteur_hz)
    pipe = build_pipe(method, fs=fs, band=band, secteur_hz=secteur_hz,
                      n_classes=len(np.unique(y)))
    return cross_val_score(pipe, X, y,
                           cv=GroupKFold(min(k, len(np.unique(g)))), groups=g).mean()


def _row(epochs, labels, fs, tag, secteur_hz, k=5):
    Xr, y, g = _windows(epochs, labels, fs)
    csp = _cv(Xr, y, g, "csp", k, fs, secteur_hz=secteur_hz)
    riemann = _cv(Xr, y, g, "riemann", k, fs, secteur_hz=secteur_hz)
    fbcsp = _cv(Xr, y, g, "fbcsp", k, fs, secteur_hz=secteur_hz)
    large = _cv(Xr, y, g, "fbcsp", k, fs, band=BANDE_LARGE, secteur_hz=secteur_hz)
    print(f"{tag:<20} n={len(epochs):>3}  csp={csp*100:5.1f}%  riemann={riemann*100:5.1f}%  "
          f"fbcsp={fbcsp*100:5.1f}%  fbcsp {BANDE_LARGE[0]:g}-{BANDE_LARGE[1]:g}="
          f"{large*100:5.1f}%")


def _entete(path, d, titre):
    secteur, origine = secteur_de(d)
    print(f"{os.path.basename(path)} — {titre} — re-ref={MI_REREF} — bande "
          f"{MI_BAND[0]:g}-{MI_BAND[1]:g} Hz (sauf la dernière colonne) — coupe-bande "
          f"{f'{secteur:g} Hz' if secteur else 'aucun'} ({origine})")
    return secteur


def compare(path, drop=0):
    d = np.load(path, allow_pickle=True)
    fs = float(d["fs"])
    secteur = _entete(path, d, "CV par essai (chance 3 classes = 33%)")
    _row(d["epochs"][drop:], d["labels"][drop:], fs, f"drop {drop} premiers", secteur)


def sweep(path):
    d = np.load(path, allow_pickle=True)
    epochs, labels, fs = d["epochs"], d["labels"], float(d["fs"])
    secteur = _entete(path, d, "hypothèse « meilleur à la fin » (CV par essai)")
    for drop in (0, 5, 10, 15):
        _row(epochs[drop:], labels[drop:], fs, f"drop {drop} premiers", secteur)
    h = len(epochs) // 2
    _row(epochs[:h], labels[:h], fs, "1re moitié", secteur, k=3)
    _row(epochs[h:], labels[h:], fs, "2e moitié", secteur, k=3)


if __name__ == "__main__":
    use_utf8_console()
    p = argparse.ArgumentParser(description="Comparaison méthodes MI (EEG_API_Unicorn).")
    p.add_argument("path", nargs="?",
                   help="fichier .npz (défaut : le mi_calib_*.npz le plus récent de data/)")
    p.add_argument("--drop", type=int, default=0, help="ignore les N premiers essais")
    p.add_argument("--sweep", action="store_true", help="analyse échauffement (drop + moitiés)")
    a = p.parse_args(sys.argv[1:])
    path = a.path
    if path is None:
        # Choisi EN SILENCE, ce fichier analyserait indéfiniment une séance périmée sans jamais
        # le dire (cf. docstring de `plus_recent`) : dire lequel a été retenu n'est pas facultatif.
        path = plus_recent(DATA_DIR)
        if path is None:
            print(f"[mi-compare] aucun mi_calib_*.npz dans {DATA_DIR} — calibre d'abord "
                  f"(console, page Motor Imagery, « Entraîner »), ou passe un chemin en argument")
            sys.exit(1)
        print(f"[mi-compare] aucun fichier donné — le plus récent retenu : "
              f"{os.path.basename(path)}")
    sweep(path) if a.sweep else compare(path, a.drop)
