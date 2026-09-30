"""Le filtrage des DÉCODEURS : un passe-bande à zéro phase, suivi du coupe-bande secteur.

Une seule écriture pour les quatre modes à modèle (Motor Imagery, P300, ErrP, c-VEP) : chacun
garde sa fonction `bandpass` — c'est le nom que ses appelants connaissent —, mais elle délègue ici.
Avant le 2026-09-30, trois modules écrivaient chacun leur Butterworth, identiques à l'axe près.

Pourquoi le coupe-bande est à part, et pourquoi il est là partout (2026-09-30) : un passe-bande
ne s'arrête pas net à son bord, il écrase de plus en plus à mesure qu'on s'en éloigne. Le 50 Hz
du secteur est donc écrasé quand le bord haut est loin (−114 dB pour le P300, bord à 12 Hz), et
seulement atténué quand il est proche (−12 dB pour le c-VEP, bord à 45 Hz : 20 µV de secteur y
laissaient 5 µV, autant que l'EEG). Depuis que la bande se règle, n'importe quel mode peut monter
son bord près du secteur : le coupe-bande, étroit (±~0,8 Hz), s'ajoute donc toujours, et le
secteur (50 ou 60 Hz) est un réglage du POSTE (`config.SECTEUR_HZ`), enregistré dans chaque
modèle avec sa bande.

⚠️ **Zéro phase** (`sosfiltfilt`) : le signal passe dans les deux sens. C'est ESSENTIEL ici — un
filtre à phase non nulle décalerait la réponse, et le P300 comme le c-VEP vivent de l'alignement
au stimulus. (Les tracés du Brut, eux, filtrent au fil de l'eau : `core/filtres_affichage.py`.)

⚠️ **Des sections (`sos`), pas des coefficients (b, a).** Aux bandes par défaut, les deux formes
rendent le même signal à 3·10⁻⁵ µV près (mesuré le 2026-09-30) : rien ne change pour un modèle
existant. Mais la bande se règle maintenant jusqu'à 0,1 Hz, là où la forme (b, a) d'un ordre 8
devient mal conditionnée (elle s'écarte déjà de 0,01 µV à 0,1 Hz) — les sections sont la forme
que la documentation de scipy recommande pour cette raison.

    python src/core/filtrage.py     # autotest
"""

import os
import sys

import numpy as np
from scipy.signal import butter, iirnotch, sosfiltfilt, tf2sos

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import SECTEUR_Q  # noqa: E402

#: L'ordre des Butterworth des décodeurs — celui qu'ils avaient chacun avant d'être réunis ici.
ORDRE = 4


def sections(fs, bande, secteur_hz=None, ordre=ORDRE):
    """Les sections du filtre : le passe-bande, puis le coupe-bande si `secteur_hz` est donné.

    Le bord haut est borné sous Nyquist (comme le faisait le c-VEP) : une bande réglée à 60 Hz sur
    un casque échantillonné à 100 Hz serait sinon refusée par scipy au milieu d'un entraînement.
    """
    bas, haut = float(bande[0]), float(bande[1])
    haut = min(haut, fs / 2.0 - 1.0)
    parties = [butter(ordre, [bas, haut], "bandpass", fs=fs, output="sos")]
    if secteur_hz:
        parties.append(tf2sos(*iirnotch(float(secteur_hz), SECTEUR_Q, fs=fs)))
    return np.vstack(parties)


def passe_bande(x, fs, bande, secteur_hz=None, axis=-1, ordre=ORDRE):
    """`x` filtré le long de `axis` : passe-bande `bande` (Hz), puis coupe-bande `secteur_hz`.

    Rend un NOUVEAU tableau ; `x` n'est jamais modifié. `secteur_hz=None` : pas de coupe-bande —
    c'est ce que reçoit un modèle entraîné avant le 2026-09-30, qui doit décoder comme il a appris.
    """
    return sosfiltfilt(sections(fs, bande, secteur_hz, ordre), np.asarray(x, dtype=float),
                       axis=axis)


def _selftest():
    from scipy.signal import filtfilt

    from core.config import use_utf8_console
    use_utf8_console()
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    fs = 250.0
    rng = np.random.default_rng(0)
    bruit = rng.normal(0.0, 10.0, (8, 2000))
    avant = bruit.copy()

    # (1) Rien ne change pour un modèle existant : aux bandes des quatre modes, le même signal que
    # l'ancienne écriture (b, a) + filtfilt, qu'on recalcule ici exprès.
    for bande in ((8.0, 30.0), (1.0, 12.0), (1.0, 10.0), (2.0, 45.0)):
        b, a = butter(ORDRE, [bande[0] / (fs / 2), bande[1] / (fs / 2)], btype="band")
        ancien = filtfilt(b, a, bruit, axis=-1)
        ecart = float(np.max(np.abs(passe_bande(bruit, fs, bande) - ancien)))
        chk(ecart < 1e-3, f"bande {bande} : le même signal que l'ancienne écriture "
                          f"(écart {ecart:.1e} µV)")
    chk(np.array_equal(bruit, avant), "le signal d'entrée n'est pas modifié")

    # (2) L'axe : filtrer (voies, temps) le long de -1 ou (temps, voies) le long de 0, c'est pareil.
    chk(np.allclose(passe_bande(bruit, fs, (8.0, 30.0), axis=-1),
                    passe_bande(bruit.T, fs, (8.0, 30.0), axis=0).T),
        "le long de l'axe demandé (le c-VEP filtre (temps, voies), les autres (…, temps))")

    t = np.arange(5000) / fs

    def amplitude(x):
        return float(np.sqrt(2.0) * np.std(x[500:-500]))

    # (3) Le coupe-bande : le secteur part, l'EEG voisin reste. Mesuré dans une bande qui monte à
    # 45 Hz, là où le passe-bande seul n'en retirait qu'un quart.
    secteur = 20.0 * np.sin(2 * np.pi * 50.0 * t)
    seul = amplitude(passe_bande(secteur, fs, (2.0, 45.0)))
    coupe = amplitude(passe_bande(secteur, fs, (2.0, 45.0), secteur_hz=50.0))
    chk(seul > 3.0 and coupe < 0.2,
        f"bande 2-45 Hz : 20 µV de secteur laissent {seul:.1f} µV sans coupe-bande, "
        f"{coupe:.2f} µV avec")
    # Le voisin se compare au passe-bande SEUL : à 40 Hz, près du bord de 45 Hz, c'est déjà lui qui
    # atténue. Ce qu'on vérifie, c'est que le coupe-bande n'y ajoute rien.
    a_40 = 10.0 * np.sin(2 * np.pi * 40.0 * t)
    sans = amplitude(passe_bande(a_40, fs, (2.0, 45.0)))
    avec = amplitude(passe_bande(a_40, fs, (2.0, 45.0), secteur_hz=50.0))
    chk(abs(avec - sans) < 0.05 * sans,
        f"…et le coupe-bande ne touche pas 40 Hz : {avec:.2f} µV avec, {sans:.2f} µV sans")
    soixante = amplitude(passe_bande(20.0 * np.sin(2 * np.pi * 60.0 * t), fs, (2.0, 80.0),
                                     secteur_hz=60.0))
    chk(soixante < 0.2, f"secteur à 60 Hz (Amériques) : 20 µV deviennent {soixante:.2f} µV")

    # (4) Une coupure basse réglée très bas reste un filtre : l'offset part, 5 Hz reste.
    lent = 1e5 + 5.0 * np.sin(2 * np.pi * 5.0 * t)
    sortie = passe_bande(lent, fs, (0.1, 12.0), secteur_hz=50.0)
    chk(np.all(np.isfinite(sortie)) and abs(amplitude(sortie) - 5.0) < 0.3
        and abs(float(np.mean(sortie[500:-500]))) < 1.0,
        f"bande 0,1-12 Hz : l'offset de 10⁵ µV part, 5 µV à 5 Hz restent "
        f"{amplitude(sortie):.2f} µV")

    # (5) Un bord haut au-delà de Nyquist est borné au lieu de faire lever scipy.
    chk(np.all(np.isfinite(passe_bande(bruit, 100.0, (1.0, 60.0)))),
        "un bord haut au-dessus de Nyquist est borné, pas refusé en plein entraînement")

    # (6) L'écriture elle-même : des SECTIONS, à l'ordre demandé, avec un coupe-bande de Q 30.
    # Trois mutants survivaient aux contrôles ci-dessus (revue du 2026-09-30) : revenir à (b, a)
    # — le contrôle (1) exige justement l'égalité avec (b, a) —, ignorer `ordre`, changer `Q`.
    from scipy.signal import sosfiltfilt as _sosfiltfilt
    from scipy.signal import sosfreqz
    exact = _sosfiltfilt(sections(fs, (0.5, 12.0), 50.0), bruit, axis=-1)
    chk(np.array_equal(passe_bande(bruit, fs, (0.5, 12.0), secteur_hz=50.0), exact),
        "le filtre est EXACTEMENT `sosfiltfilt(sections(...))` — pas une forme (b, a), qui "
        "s'écarte à basse coupure")
    doux = passe_bande(10.0 * np.sin(2 * np.pi * 45.0 * t), fs, (1.0, 30.0), ordre=2)
    ferme = passe_bande(10.0 * np.sin(2 * np.pi * 45.0 * t), fs, (1.0, 30.0), ordre=4)
    chk(amplitude(doux) > 3.0 * amplitude(ferme),
        f"l'ordre demandé est appliqué : 45 Hz passe à {amplitude(doux):.2f} µV à l'ordre 2, "
        f"{amplitude(ferme):.2f} µV à l'ordre 4")
    _w, h = sosfreqz(sections(fs, (2.0, 100.0), 50.0), worN=[49.0], fs=fs)
    _w, h_pb = sosfreqz(sections(fs, (2.0, 100.0)), worN=[49.0], fs=fs)
    gain_49 = float(abs(h[0]) / abs(h_pb[0])) ** 2          # au carré : zéro phase
    chk(0.45 < gain_49 < 0.75,
        f"la largeur du coupe-bande est celle de Q = 30 : à 49 Hz, gain {gain_49:.2f} (Q 15 "
        f"donnerait 0,27, Q 100 : 0,94)")

    # (7) ⚠️ CE QUE LE COUPE-BANDE NE FAIT PAS, mesuré le 2026-09-30 : sur une ÉPOQUE COURTE filtrée
    # seule, le secteur fuit aux BORDS, coupe-bande ou pas. Le prolongement impair d'une sinusoïde
    # est une sinusoïde d'une autre phase, et un filtre étroit met ~50 échantillons à s'y refaire.
    # Les chiffres « −114 dB à 50 Hz » d'une bande 1-12 Hz ne valent qu'en régime établi : sur une
    # époque P300 (238 échantillons), 20 µV de secteur en laissent ~5 µV en moyenne, AVEC OU SANS
    # coupe-bande. Le coupe-bande n'aide vraiment que là où la bande laisse passer 50 Hz — le c-VEP
    # (fenêtre décodée : ~4 → ~2 µV). C'est une caractérisation : si un jour le filtrage se fait
    # sur le signal continu AVANT la découpe, ces chiffres baisseront et ce contrôle sera à revoir.
    def _residu(n, bande, garde, secteur):
        tt = np.arange(n) / fs
        return float(np.mean([np.sqrt(np.mean(passe_bande(
            20.0 * np.sin(2 * np.pi * 50.0 * tt + phase), fs, bande, secteur)[garde] ** 2))
            for phase in np.linspace(0, 2 * np.pi, 12, endpoint=False)]))
    p300_sans = _residu(238, (1.0, 12.0), slice(None), None)
    p300_avec = _residu(238, (1.0, 12.0), slice(None), 50.0)
    cvep_sans = _residu(774, (2.0, 45.0), slice(250, None), None)
    cvep_avec = _residu(774, (2.0, 45.0), slice(250, None), 50.0)
    chk(p300_sans > 2.0 and abs(p300_avec - p300_sans) < 0.2 * p300_sans,
        f"époque P300 (~1 s) : 20 µV de secteur laissent {p300_sans:.1f} µV sans coupe-bande, "
        f"{p300_avec:.1f} µV avec — les bords dominent, le coupe-bande n'y change presque rien")
    chk(cvep_avec < 0.7 * cvep_sans,
        f"fenêtre c-VEP décodée : {cvep_sans:.1f} µV sans coupe-bande, {cvep_avec:.1f} µV avec — "
        f"là, il aide")
    print("filtrage des décodeurs :", "OK" if ok else "ÉCHEC")
    return ok


if __name__ == "__main__":
    sys.exit(0 if _selftest() else 1)
