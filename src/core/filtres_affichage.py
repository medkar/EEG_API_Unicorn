"""Les filtres d'AFFICHAGE des tracés du Brut : ce qu'on applique pour REGARDER le signal.

Ils ne touchent QUE la copie qu'on dessine. Le tampon du moteur, le flux brut publié sur le réseau
et les époques d'entraînement restent tels quels — `EngineServer.recent_window` doit rester non
filtrée (le Motor Imagery s'entraîne dessus, et un double filtrage l'entraînerait sur autre chose
que ce qu'il voit en ligne, sans une erreur).

Pourquoi un choix, et pas un filtre fixe (2026-09-25, relevé au casque) : sur le brut, certaines
voies DÉRIVENT en y — l'Unicorn sort un offset continu énorme, qui rampe après l'ouverture de
session — et la dérive écrase l'EEG. Un passe-haut la retire. Mais le brut dit aussi des choses
qu'un filtre cache : une voie qui bourdonne à 50 Hz est une voie mal posée. D'où un choix, comme
dans la Unicorn Suite : aucun filtre, plusieurs passe-haut, quelques passe-bande, et un coupe-bande
secteur à part.

⚠️ **Causal**, comme un oscilloscope et comme la Unicorn Suite : chaque échantillon n'est filtré
qu'avec son passé, donc le bord DROIT de l'écran — le plus récent, celui qu'on regarde — est exact
et ne bouge plus quand le signal suivant arrive. (Un filtre à zéro phase, `filtfilt`, a été essayé
et écarté : il invente la suite du bloc pour filtrer son bord, et sur la dernière demi-seconde un
50 Hz de 20 µV y ressortait jusqu'à 33 µV crête, là où celui-ci n'en laisse rien.) Le prix est
connu : un passe-haut déforme un clignement (plus bas, suivi d'un rebond), d'autant plus qu'il
coupe haut — c'est dit dans la bulle.

Un bloc filtré commence par un régime transitoire : l'appelant demande `TRACES_AMORCE_S` de
signal EN PLUS de ce qu'il affiche, et le jette.
"""

import os
import sys

import numpy as np
from scipy.signal import butter, detrend, iirnotch, sosfilt, sosfilt_zi, tf2sos

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import TRACES_AMORCE_S  # noqa: E402

#: Les filtres proposés, en (bas, haut) Hz ; None = pas de coupure de ce côté. `(None, None)` est
#: le signal brut. Les passe-haut vont du plus doux (0,1 Hz : garde les ondes lentes, laisse
#: encore dériver un peu) au plus ferme (2 Hz) ; 5-40 Hz est la bande du décodage SSVEP
#: (`config.BANDPASS`), pour voir ce que le décodeur voit.
FILTRES = ((None, None),
           (0.1, None), (0.5, None), (1.0, None), (2.0, None),
           (1.0, 30.0), (1.0, 40.0), (5.0, 40.0))
#: Par défaut : assez pour retirer la dérive, pas assez pour déformer un clignement.
FILTRE_DEFAUT = (1.0, None)

#: Le secteur, en Europe. Aux Amériques ce serait 60.
SECTEUR_HZ = 50.0
#: La finesse du coupe-bande : ±~0,8 Hz autour du secteur, l'EEG voisin n'est pas touché.
SECTEUR_Q = 30.0
#: L'ordre des Butterworth — celui du filtre d'acquisition (`UnicornAcquisition.order`).
ORDRE = 4


def sections(fs, filtre=FILTRE_DEFAUT, coupe_bande=False):
    """Les sections du filtre (`sos` de scipy), ou None s'il n'y a rien à filtrer."""
    bas, haut = filtre
    parties = []
    if bas is not None and haut is not None:
        parties.append(butter(ORDRE, [bas, haut], "bandpass", fs=fs, output="sos"))
    elif bas is not None:
        parties.append(butter(ORDRE, bas, "highpass", fs=fs, output="sos"))
    elif haut is not None:
        parties.append(butter(ORDRE, haut, "lowpass", fs=fs, output="sos"))
    if coupe_bande:
        parties.append(tf2sos(*iirnotch(SECTEUR_HZ, SECTEUR_Q, fs=fs)))
    return np.vstack(parties) if parties else None


def filtrer(bloc, fs, filtre=FILTRE_DEFAUT, coupe_bande=False):
    """Une COPIE filtrée de `bloc` (n, voies). `bloc` n'est jamais modifié.

    Chaque voie est d'abord centrée sur sa médiane : l'offset de l'Unicorn (10⁵ µV) ne sert à
    rien à l'écran. Sans filtre, c'est tout ce qui est fait — la dérive reste visible, exprès.
    """
    sortie = np.array(bloc, dtype=np.float64, copy=True)
    if sortie.ndim != 2 or len(sortie) == 0:
        return sortie
    sortie -= np.median(sortie, axis=0)
    sos = sections(fs, filtre, coupe_bande)
    if sos is None or len(sortie) < 2:
        return sortie
    if filtre[0] is not None:
        # ⚠️ La RAMPE d'abord. L'offset de l'Unicorn monte en ligne droite après l'ouverture de
        # session ; un passe-haut qui démarre au milieu d'une rampe met des secondes à s'en
        # remettre — mesuré : 180 µV de sursaut à 0,1 Hz sur une dérive de 500 µV/s, encore à
        # l'écran après 4 s d'amorce. Une droite est de toute façon coupée par chacun de ces
        # passe-haut et passe-bande : la retirer avant ne change que le démarrage.
        sortie = detrend(sortie, axis=0, type="linear")
    # Le filtre démarre comme s'il avait toujours vu le premier échantillon : sans cet état
    # initial, il verrait un échelon de zéro à ce premier échantillon.
    etat = sosfilt_zi(sos)[:, :, None] * sortie[0][None, None, :]
    return sosfilt(sos, sortie, axis=0, zi=etat)[0]


def _selftest():
    from core.config import use_utf8_console
    use_utf8_console()
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    fs = 250.0
    from core.config import TRACES_AFFICHAGE_S
    n_amorce = int(round(TRACES_AMORCE_S * fs))
    n = int(round(TRACES_AFFICHAGE_S * fs)) + n_amorce
    t = np.arange(n) / fs
    rng = np.random.default_rng(0)

    def vu(x):
        """Ce que l'écran montre : le bloc sans son amorce."""
        return x[n_amorce:]

    def amplitude(x):
        return float(np.sqrt(2.0) * np.std(x))

    # Ce que sort l'Unicorn : un offset de 10⁵ µV qui RAMPE (50 µV/s), plus l'EEG.
    derive = 1e5 + 50.0 * t
    alpha = 10.0 * np.sin(2 * np.pi * 10.0 * t)
    secteur_50 = 20.0 * np.sin(2 * np.pi * SECTEUR_HZ * t)
    bloc = np.column_stack([derive + alpha, derive, alpha, derive + secteur_50])
    avant = bloc.copy()

    sortie = filtrer(bloc, fs)
    chk(sortie.shape == bloc.shape and sortie is not bloc and np.array_equal(bloc, avant),
        "une COPIE, de la même forme, et le bloc d'origine n'est PAS touché (c'est le tampon du "
        "moteur, et le MI s'entraîne dessus)")
    brut = filtrer(bloc, fs, (None, None))
    chk(np.allclose(brut, bloc - np.median(bloc, axis=0)),
        "sans filtre : seulement centré — la dérive est toujours là")
    chk(np.ptp(vu(brut[:, 1])) > 150.0,
        f"…et elle se voit : {np.ptp(vu(brut[:, 1])):.0f} µV d'amplitude sur l'écran")

    for filtre in [f for f in FILTRES if f != (None, None)]:
        reste = float(np.max(np.abs(vu(filtrer(bloc, fs, filtre)[:, 1]))))
        chk(reste < 15.0 if filtre[0] < 0.5 else reste < 2.0,
            f"{filtre} : la dérive de 50 µV/s ne laisse que {reste:.1f} µV à l'écran")

    garde = amplitude(vu(sortie[:, 2]))
    chk(abs(garde - 10.0) < 0.5, f"passe-haut 1 Hz : l'alpha à 10 µV reste à {garde:.2f} µV")
    secteur = amplitude(vu(filtrer(bloc, fs, (1.0, None), coupe_bande=True)[:, 3]))
    chk(secteur < 0.5, f"coupe-bande : 20 µV à 50 Hz deviennent {secteur:.2f} µV")
    voisin = amplitude(vu(filtrer(bloc, fs, (1.0, None), coupe_bande=True)[:, 2]))
    chk(abs(voisin - 10.0) < 0.5, f"…sans toucher l'alpha voisin ({voisin:.2f} µV)")
    seul = filtrer(bloc, fs, (None, None), coupe_bande=True)
    chk(amplitude(vu(seul[:, 3] - seul[:, 1])) < 0.5 and np.ptp(vu(seul[:, 1])) > 150.0,
        "coupe-bande SANS filtre : le 50 Hz part, la dérive reste — « aucun filtre » veut dire "
        "aucun, pas un passe-haut discret")
    haut = amplitude(vu(filtrer(np.column_stack([np.sin(2 * np.pi * 45 * t) * 10.0]), fs,
                                (1.0, 30.0))[:, 0]))
    chk(haut < 2.0, f"passe-bande 1-30 Hz : 10 µV à 45 Hz deviennent {haut:.2f} µV")

    # Causal : ce qui est à l'écran ne se réécrit pas quand le signal suivant arrive. On filtre
    # deux blocs qui GLISSENT d'un rafraîchissement (0,1 s) ; sur leur partie commune affichée,
    # le tracé doit être le même — sinon il tremblerait à chaque image.
    eeg = derive + np.cumsum(rng.normal(0, 3, n)) * 0.1 + rng.normal(0, 5, n)
    pas = int(0.1 * fs)
    suite = np.concatenate([eeg, derive[-1] + 50.0 * np.arange(1, pas + 1) / fs
                            + rng.normal(0, 5, pas)])
    for filtre in [f for f in FILTRES if f != (None, None)]:
        a = filtrer(eeg[:, None], fs, filtre)[n_amorce:, 0]
        b = filtrer(suite[pas:, None], fs, filtre)[n_amorce - pas:n - pas, 0]
        ecart = float(np.max(np.abs(a - b)))
        chk(ecart < (2.0 if filtre[0] < 0.5 else 0.5),
            f"{filtre} : d'une image à la suivante, le tracé commun bouge de {ecart:.2f} µV")

    # Le prix d'un passe-haut, écrit pour qu'il reste dit : un clignement (bosse de 150 µV,
    # σ = 0,1 s) sort plus BAS et suivi d'un REBOND, d'autant plus que la coupure est haute.
    bosse = 150.0 * np.exp(-0.5 * ((t - 6.0) / 0.1) ** 2)
    doux = filtrer(bosse[:, None], fs, (0.1, None))[:, 0]
    ferme = filtrer(bosse[:, None], fs, (2.0, None))[:, 0]
    chk(doux.max() > 110.0 and ferme.max() < 60.0 and ferme.min() < -20.0,
        f"un clignement : {doux.max():.0f} µV à 0,1 Hz, {ferme.max():.0f} µV et un rebond à "
        f"{ferme.min():.0f} µV à 2 Hz — c'est ce que dit la bulle")

    court = filtrer(bloc[:3], fs)
    chk(court.shape == (3, 4) and np.all(np.isfinite(court)),
        "un bloc de 3 échantillons (le tampon qui se remplit) ne plante pas")
    chk(FILTRE_DEFAUT in FILTRES and FILTRES[0] == (None, None),
        "le filtre par défaut est dans la liste, et « aucun » vient en premier")
    print("filtres d'affichage :", "OK" if ok else "ÉCHEC")
    return ok


if __name__ == "__main__":
    sys.exit(0 if _selftest() else 1)
