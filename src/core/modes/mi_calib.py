"""La calibration Motor Imagery : le protocole, l'entraînement, la sauvegarde.

Le protocole est celui qui a été validé au casque et qui vit aujourd'hui dans l'écran pygame
`src/research/mi_calibrate.py` — mêmes durées, mêmes consignes, même découpage. Il est repris ici
mot pour mot, à trois différences près, toutes voulues :

1. **L'accuracy affichée est HONNÊTE** (validation croisée par essai, cf. `MIModel.fit`). L'écran
   pygame affiche un chiffre gonflé de 10 à 16 points.
2. **Rien n'est jamais écrasé** : le modèle et l'enregistrement sont horodatés. `mi_calib_last.npz`
   avait un nom FIXE, et c'est ce qui a fait perdre les époques d'une séance à 42 essais.
3. **Une séance abandonnée n'entraîne rien** (cf. `CalibrationRuntime.cancel`).

Autotest :
    python src/core/modes/mi_calib.py
"""

import os as _os
import random as _random
import sys as _sys
import time as _time

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np  # noqa: E402

from core.config import (DATA_DIR, MI_CUE_S, MI_IMAGERY_S, MI_REST_S,  # noqa: E402
                         MI_SESSIONS, MI_TRAIN_STEP_S, MI_WARMUP_PER_CLASS, MI_WINDOW_S,
                         SSVEP_WARMUP_S, use_utf8_console)
from core.mi_decoder import MI_LABELS, MIModel  # noqa: E402
from core.modes.calibration import CalibrationRuntime  # noqa: E402
from core.modes.contract import Calib, Param  # noqa: E402

# Les consignes, telles qu'elles ont été validées. La formulation compte : « SENTIR le serrement »
# et non « se le représenter » est la différence entre de l'imagerie kinesthésique, qui produit
# une ERD exploitable, et de l'imagerie visuelle, qui n'en produit pas.
INSTRUCTIONS = {
    "GAUCHE": "Imagine : SERRE le POING GAUCHE",
    "DROITE": "Imagine : SERRE le POING DROIT",
    "REPOS": "REPOS — détends-toi, ne rien imaginer",
}
RAPPEL = "sens le serrement — NE BOUGE PAS"

BRIEFING = (
    "Un top au DÉBUT de chaque essai donne le côté : oreille GAUCHE = poing gauche,",
    "oreille DROITE = poing droit, les DEUX oreilles (plus long) = repos.",
    "Imagine dès le top et TIENS jusqu'à la fin du décompte.",
    "Imagine le serrement en le SENTANT (tension dans l'avant-bras), sans bouger la main.",
    "Maintiens ou pompe le serrement toute la durée — pas un seul clic.",
    "Astuce : serre vraiment 3-4 fois AVANT de commencer, pour mémoriser la sensation.",
    "Immobile, cligne le moins possible pendant l'imagerie.",
    "REPOS = ne rien faire de spécial : relâche, respire normalement, aucune imagerie de main.",
)

# Les verdicts sont calés sur l'échelle HONNÊTE, pas sur l'ancienne. Les seuils de l'écran pygame
# (75 % / 60 %) valaient pour une CV gonflée de 10 à 16 points : les reprendre tels quels
# déclarerait « FAIBLE » une séance parfaitement ordinaire. Repère du projet, mesuré honnêtement
# sur sa seule séance de référence : 40,0 % à 3 classes (p = 0,082, PAS significatif) et 63,3 % à
# 2 classes (p = 0,038). Autrement dit : autour de 40 %, on est dans le NORMAL, et ça ne suffit
# pas à piloter quoi que ce soit.
VERDICTS = ((0.60, "EXCELLENT"), (0.45, "UTILISABLE"),
            (0.00, "FAIBLE — ré-essaie : contact des électrodes, immobilité, imagerie "
                   "kinesthésique (SENTIR, pas voir)"))


def horodatage(maintenant=None):
    """`AAAAMMJJ-HHMMSS`. Le paramètre existe pour que le test soit reproductible."""
    return _time.strftime("%Y%m%d-%H%M%S", _time.localtime(maintenant or _time.time()))


def decouper(epoque, n, pas):
    """Découpe une époque (n_samp, n_ch) en fenêtres (n_ch, n) glissantes.

    L'orientation compte : `MIModel` attend (n_essais, n_ch, n_samp), et le CSP est un filtre
    SPATIAL — une transposition oubliée décoderait du bruit avec des probabilités à 0,99.
    """
    return [epoque[i:i + n].T for i in range(0, len(epoque) - n + 1, pas)]


def verdict(cv):
    for seuil, texte in VERDICTS:
        if cv >= seuil:
            return texte
    return VERDICTS[-1][1]


class MICalibration(CalibrationRuntime):
    """Le protocole MI. Sa seule particularité est ce qu'elle fait des époques à la fin."""

    classes = MI_LABELS
    cue_s = MI_CUE_S
    imagery_s = MI_IMAGERY_S
    rest_s = MI_REST_S
    warmup_s = SSVEP_WARMUP_S          # la même chauffe que les modes : c'est la même dérive DC
    warmup_per_class = MI_WARMUP_PER_CLASS
    # Le découpage en fenêtres d'entraînement. Attributs de CLASSE, comme les durées, et pour la
    # même raison : un test doit pouvoir jouer une séance entière en quelques secondes, et il ne
    # peut le faire qu'en raccourcissant la fenêtre EN MÊME TEMPS que l'imagerie. Les raccourcir
    # séparément donne `imagery_s < window_s`, donc ZÉRO fenêtre découpée et un entraînement qui
    # refuse — un piège dans lequel ce plan est tombé en s'écrivant.
    window_s = MI_WINDOW_S
    step_s = MI_TRAIN_STEP_S

    def __init__(self, spec, params, engine, rng=None, dossier=None):
        """`dossier` : où écrire. Injectable pour que les tests n'approchent jamais le vrai `data/`."""
        super().__init__(spec, params, engine, rng=rng)
        self.dossier = dossier or DATA_DIR

    def instruction(self):
        return INSTRUCTIONS.get(self.classe, "")

    def rappel(self):
        return RAPPEL if self.classe in ("GAUCHE", "DROITE") else ""

    def _entrainer(self, enregistre, fs):
        """CSP + LDA sur les fenêtres, CV honnête par essai, puis sauvegarde horodatée."""
        n = int(round(self.window_s * fs))
        pas = int(round(self.step_s * fs))
        X, y, groupes = [], [], []
        for indice, (epoque, label) in enumerate(enregistre):
            for fenetre in decouper(np.asarray(epoque, dtype=float), n, pas):
                X.append(fenetre)
                y.append(label)
                groupes.append(indice)     # le GROUPE est l'essai : c'est ce qui rend la CV honnête

        comptes = {c: y.count(c) for c in self.classes}
        if not X or min(comptes.values()) < 5:
            raise ValueError(
                f"pas assez de données pour entraîner : {comptes} fenêtres par classe, il en faut "
                f"au moins 5 — refais une séance plus longue")

        modele = MIModel(fs=fs).fit(np.asarray(X), np.asarray(y), groups=np.asarray(groupes))

        stamp = horodatage()
        _os.makedirs(self.dossier, exist_ok=True)
        # Le motif `mi_model*.joblib` est celui que `mi_models.modeles_disponibles` cherche :
        # ne pas s'en écarter, sinon le modèle produit n'apparaîtra jamais dans la liste.
        chemin_modele = _os.path.join(self.dossier, f"mi_model_{stamp}.joblib")
        chemin_npz = _os.path.join(self.dossier,
                                   f"mi_calib_{stamp}_n{len(enregistre):02d}.npz")
        modele.save(chemin_modele)
        np.savez(chemin_npz,
                 epochs=np.asarray([e for e, _l in enregistre]),
                 labels=np.asarray([l for _e, l in enregistre]),
                 fs=fs, window_s=self.window_s, step_s=self.step_s,
                 imagery_s=self.imagery_s)

        cv = modele.cv_groupee_ if modele.cv_groupee_ is not None else 0.0
        hasard = 1.0 / len(self.classes)
        print(f"[mi-calib] accuracy HONNÊTE (validation croisée par essai) : {cv*100:.1f}% "
              f"— hasard {hasard*100:.0f}% — {verdict(cv)}")
        print(f"[mi-calib] (pour mémoire, la CV naïve, fenêtres mélangées : "
              f"{modele.cv_*100:.1f}% — gonflée, ne pas s'y fier)")
        print(f"[mi-calib] modèle : {chemin_modele}")
        print(f"[mi-calib] enregistrement : {chemin_npz}")
        return {
            "modele": chemin_modele,
            "nom": _os.path.basename(chemin_modele),
            "enregistrement": chemin_npz,
            "n_essais": len(enregistre),
            "n_fenetres": len(X),
            "cv_groupee": cv,
            "cv_naive": float(modele.cv_),
            "hasard": hasard,
            "classes": list(self.classes),
            "verdict": verdict(cv),
        }


CALIB = Calib(
    kind="console",
    label="Calibration Motor Imagery",
    briefing=BRIEFING,
    epoch_s=MI_IMAGERY_S,
    params=(
        Param(
            key="trials_per_class",
            label="Essais par classe",
            kind="choice",
            default=MI_SESSIONS[1],
            choices=MI_SESSIONS,
            help="Combien d'essais par classe. Plus long n'est PAS forcément meilleur : le "
                 "facteur limitant mesuré est la FATIGUE, pas la durée — sur la séance de "
                 "référence du projet, la justesse à 3 classes tombe de 57 % à 33 % en deuxième "
                 "moitié. Commence par la valeur par défaut.",
        ),
    ),
    runtime_cls=MICalibration,
)


def _selftest():
    """Une séance complète, jouée en accéléré sur du signal FABRIQUÉ, dans un dossier temporaire."""
    import shutil
    import tempfile

    from core.mi_decoder import synth_mi_trial
    from core.modes import mi as _mi

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _FausseAcq:
        fs = 250.0

    class _FauxMoteur:
        """Rend une époque d'ERD synthétique CORRESPONDANT à la classe cuée.

        Sans ça, l'entraînement porterait sur du bruit et le test ne dirait rien du contenu — il
        ne prouverait que la plomberie. Ici, un modèle doit sortir ET les classes doivent être
        celles qu'on a cuées.
        """

        def __init__(self, runtime, rng):
            self.acq = _FausseAcq()
            self.runtime = runtime
            self.rng = rng

        def recent_window(self, seconds):
            n = int(round(seconds * self.acq.fs))
            label = self.runtime.classe or "REPOS"
            return synth_mi_trial(label, n_samp=n, fs=self.acq.fs, rng=self.rng).T

    dossier = tempfile.mkdtemp(prefix="mi_calib_")
    try:
        # PAS `is CALIB` : lancé directement (`python src/core/modes/mi_calib.py`), CE fichier
        # tourne en `__main__` avec SON `CALIB`. L'import de `core.modes.mi` juste en dessous
        # (nécessaire pour lire le contrat qu'il déclare) déclenche `from core.modes import
        # mi_calib`, qui recharge CE MÊME fichier une SECONDE fois, sous son nom de paquet
        # `core.modes.mi_calib` cette fois — avec sa PROPRE instance de `CALIB` : mêmes valeurs,
        # objet différent. Artefact mécanique du couple « script exécutable directement » +
        # « importé ailleurs par son nom de paquet », pas un défaut de câblage : comparer les
        # champs qui identifient CETTE calibration est le test qui tient, pas l'identité.
        calib_mi = _mi.SPEC.calibration
        chk(calib_mi is not None and calib_mi.label == CALIB.label
            and calib_mi.runtime_cls is not None
            and calib_mi.runtime_cls.__name__ == MICalibration.__name__,
            f"le mode MI déclare CETTE calibration dans son contrat ({calib_mi!r})")
        chk(_mi.SPEC.calibration.epoch_s == MI_IMAGERY_S,
            f"et annonce la longueur d'époque dont le moteur devra dimensionner son tampon "
            f"({_mi.SPEC.calibration.epoch_s} s)")

        rng = np.random.default_rng(0)
        rt = MICalibration(_mi.SPEC, {"trials_per_class": 6}, None,
                           rng=_random.Random(0), dossier=dossier)
        rt.engine = _FauxMoteur(rt, rng)

        t = 0.0
        for _ in range(20000):
            rt.tick(rt.engine, t)
            if rt.terminee:
                break
            t += 0.25

        chk(rt.phase == "fini", f"la séance aboutit ({rt.phase} ; problème={rt.probleme!r})")
        res = rt.resultat or {}
        chk(res.get("n_essais") == 18,
            f"6 essais × 3 classes = 18 enregistrés ({res.get('n_essais')})")
        chk(res.get("n_fenetres") == 18 * 3,
            f"et 3 fenêtres par essai de 4 s ({res.get('n_fenetres')})")

        # L'invariant du chantier : le chiffre AFFICHÉ est l'honnête, et il est plus BAS.
        chk(res.get("cv_groupee") is not None and res.get("cv_naive") is not None,
            f"les deux CV sont rapportées ({res.get('cv_groupee')}, {res.get('cv_naive')})")
        chk(res["cv_groupee"] < res["cv_naive"],
            f"et c'est l'HONNÊTE qui est affichée, plus basse que la naïve "
            f"({res['cv_groupee']*100:.1f}% contre {res['cv_naive']*100:.1f}%)")
        chk(abs(res.get("hasard", 0) - 1 / 3) < 1e-9,
            f"le niveau du hasard est rapporté à côté ({res.get('hasard')})")

        # Rien n'est écrasé : deux séances donnent deux fichiers, et le modèle est visible.
        from core import mi_models

        chk(_os.path.basename(res["modele"]).startswith("mi_model_")
            and res["modele"].endswith(".joblib"),
            f"le modèle est horodaté ({_os.path.basename(res['modele'])})")
        chk("_n18.npz" in res["enregistrement"],
            f"l'enregistrement porte le nombre d'essais ({_os.path.basename(res['enregistrement'])})")
        chk(mi_models.modeles_disponibles(dossier) == [res["modele"]],
            f"et le modèle produit est VISIBLE dans la liste — c'est le motif "
            f"`mi_model*.joblib` qui le veut ({mi_models.modeles_disponibles(dossier)})")

        d = mi_models.decrire(res["modele"])
        chk(d["cv_groupee"] is not None and abs(d["cv_groupee"] - res["cv_groupee"]) < 1e-9,
            f"la description du modèle porte la CV HONNÊTE, pas None ({d['cv_groupee']})")
        chk(d["n_essais"] == 18, f"et le nombre d'essais ({d['n_essais']})")

        # Une séance trop courte doit REFUSER d'entraîner, avec une raison, plutôt que de
        # produire un modèle que rien ne distingue d'un bon.
        court = MICalibration(_mi.SPEC, {"trials_per_class": 1}, None,
                              rng=_random.Random(1), dossier=dossier)
        court.engine = _FauxMoteur(court, rng)
        t = 0.0
        for _ in range(20000):
            court.tick(court.engine, t)
            if court.terminee:
                break
            t += 0.25
        chk(court.phase == "annule" and "pas assez de données" in court.probleme,
            f"une séance trop courte refuse d'entraîner, en disant pourquoi "
            f"({court.phase}, {court.probleme})")
        chk(len(mi_models.modeles_disponibles(dossier)) == 1,
            "et n'ajoute AUCUN modèle à la liste")

        chk(verdict(0.70) == "EXCELLENT" and verdict(0.50) == "UTILISABLE"
            and verdict(0.40).startswith("FAIBLE"),
            "les verdicts sont calés sur l'échelle HONNÊTE : 40 % n'est pas « utilisable »")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[mi-calib] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
