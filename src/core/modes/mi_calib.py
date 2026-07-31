"""La calibration Motor Imagery : le protocole, l'entraînement, la sauvegarde.

Le protocole est celui qui a été validé au casque, dans l'écran pygame désormais archivé
(`archive/mi_calibrate.py`) — mêmes durées, mêmes consignes, même découpage. Il est repris ici
mot pour mot, à trois différences près, toutes voulues :

1. **L'accuracy affichée est HONNÊTE** (validation croisée par essai, cf. `MIModel.fit`). L'écran
   pygame archivé affiche un chiffre gonflé de 10 à 16 points.
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
    """`AAAAMMJJ-HHMMSS`. Le paramètre existe pour que le test soit reproductible.

    ⚠️ `maintenant or _time.time()` serait faux : `0.0` (l'epoch Unix, un instant valide) est
    FALSY en Python, donc `or` le remplacerait par l'heure réelle — exactement le piège que le
    commit frère du même jour documente ailleurs dans ce fichier (cf. `now=0.0` dans
    `calibration.py`). Inatteignable en séance réelle, mais un piège posé pour le prochain test.
    """
    return _time.strftime("%Y%m%d-%H%M%S",
                          _time.localtime(_time.time() if maintenant is None else maintenant))


def _chemins_libres(dossier, n_essais):
    """Le couple (chemin du modèle, chemin de l'enregistrement) pour CETTE séance — les DEUX
    chemins sont GARANTIS libres au moment du retour, sans changer le FORMAT du nom.

    `horodatage()` n'a qu'une résolution d'une seconde : deux séances qui finissent la même
    seconde produiraient sinon le MÊME couple de noms, et `save`/`savez` écrasent sans vérifier —
    exactement la panne que l'horodatage existe pour fermer (cf. docstring du module, point 2).
    On avance donc d'une seconde tant que l'un des deux fichiers existe déjà : un décalage de
    quelques secondes sur l'estampille est un prix dérisoire devant la perte d'une séance.
    """
    maintenant = _time.time()
    while True:
        stamp = horodatage(maintenant)
        chemin_modele = _os.path.join(dossier, f"mi_model_{stamp}.joblib")
        chemin_npz = _os.path.join(dossier, f"mi_calib_{stamp}_n{n_essais:02d}.npz")
        if not _os.path.exists(chemin_modele) and not _os.path.exists(chemin_npz):
            return chemin_modele, chemin_npz
        maintenant += 1.0


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
        # ⚠️ Ce seuil (5 FENÊTRES/classe) et celui de `MIModel.fit` (n_splits >= 2, donc au moins 2
        # ESSAIS DISTINCTS par classe) sont deux nombres séparés qui COÏNCIDENT aujourd'hui, sans
        # qu'aucun lien ne les garantisse : à window_s/step_s/imagery_s inchangés, un essai produit
        # 3 fenêtres, donc 5 fenêtres/classe impliquent déjà >= 2 essais/classe — assez pour que
        # `fit` calcule `cv_groupee_`. Si l'un des deux seuils bouge, ou si des essais sont IGNORÉS
        # en cours de séance (coupure Bluetooth, cf. le message « essai IGNORÉ » dans
        # `CalibrationRuntime._pas_essai`), une classe peut atteindre 5 fenêtres avec un SEUL essai
        # distinct : `cv_groupee_` redevient alors None (géré juste plus bas, jamais recopié depuis
        # la naïve). Commentaire jumeau dans `core/mi_decoder.py::MIModel.fit`.
        if not X or min(comptes.values()) < 5:
            raise ValueError(
                f"pas assez de données pour entraîner : {comptes} fenêtres par classe, il en faut "
                f"au moins 5 — refais une séance plus longue")

        modele = MIModel(fs=fs).fit(np.asarray(X), np.asarray(y), groups=np.asarray(groupes))

        _os.makedirs(self.dossier, exist_ok=True)
        # Le motif `mi_model*.joblib` est celui que `mi_models.modeles_disponibles` cherche :
        # ne pas s'en écarter, sinon le modèle produit n'apparaîtra jamais dans la liste.
        # `_chemins_libres` (pas `horodatage` appelée seule) : deux séances qui finissent la
        # même seconde ne doivent PAS produire le même couple de fichiers — cf. sa docstring.
        chemin_modele, chemin_npz = _chemins_libres(self.dossier, len(enregistre))
        # Le `.npz` D'ABORD, le `.joblib` ENSUITE : si `savez` échoue (disque plein, verrou
        # antivirus), l'exception remonte AVANT que le modèle n'existe — aucun fichier orphelin.
        # Dans l'ordre inverse, un `.npz` qui échoue après un `.joblib` déjà écrit laissait un
        # MODÈLE sur le disque, visible dans la liste de la console, sans enregistrement ni
        # provenance : exactement ce que « l'échec ne produit AUCUN fichier » interdit. Un `.npz`
        # orphelin, lui, est inoffensif — rien ne le liste, rien ne le propose.
        np.savez(chemin_npz,
                 epochs=np.asarray([e for e, _l in enregistre]),
                 labels=np.asarray([l for _e, l in enregistre]),
                 fs=fs, window_s=self.window_s, step_s=self.step_s,
                 imagery_s=self.imagery_s)
        modele.save(chemin_modele)

        # `None` PROPAGÉ, jamais recopié en 0.0 : un 0 % afficherait « FAIBLE — contact des
        # électrodes, immobilité… », un diagnostic précis et SANS RAPPORT avec la vraie cause (pas
        # assez d'essais distincts pour former deux plis). `mi_models.decrire()` et
        # `MIModel.fit` préservent déjà ce None ailleurs dans le chantier ; il doit l'être ICI aussi.
        cv = modele.cv_groupee_
        hasard = 1.0 / len(self.classes)
        if cv is None:
            verdict_txt = ("justesse non mesurable : pas assez d'essais distincts par classe "
                           "pour une validation croisée")
            print(f"[mi-calib] {verdict_txt}")
        else:
            verdict_txt = verdict(cv)
            print(f"[mi-calib] accuracy HONNÊTE (validation croisée par essai) : {cv*100:.1f}% "
                  f"— hasard {hasard*100:.0f}% — {verdict_txt}")
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
            "verdict": verdict_txt,
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
    import hashlib
    import shutil
    import tempfile

    from core.mi_decoder import synth_mi_trial
    from core.modes import mi as _mi

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    def _hash_fichier(chemin):
        """L'empreinte OCTET POUR OCTET d'un fichier — la preuve la plus directe qu'un contenu
        n'a pas bougé, plus fiable qu'une comparaison de valeurs qui pourraient coïncider."""
        with open(chemin, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

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

        # Le modèle et l'enregistrement de CETTE séance sont horodatés et visibles dans le
        # catalogue. (« Rien n'est jamais écrasé » — même à la même seconde — est prouvé plus
        # bas, par DEUX séances RÉUSSIES : une seule séance ici ne pourrait rien en dire.)
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

        # --- `_chemins_libres` seule, avant l'intégration complète --------------------------
        # Une collision sur le premier essai force une avance d'exactement 1 s, sur les DEUX
        # chemins à la fois — c'est ce qui la rend testable indépendamment de toute séance.
        sonde_dossier = _os.path.join(dossier, "sonde")
        _os.makedirs(sonde_dossier, exist_ok=True)
        vrai_time = _time.time
        _time.time = lambda: 1_800_000_000.0
        try:
            m1, n1 = _chemins_libres(sonde_dossier, 7)
            open(m1, "wb").close()
            open(n1, "wb").close()
            m2, n2 = _chemins_libres(sonde_dossier, 7)
        finally:
            _time.time = vrai_time
        chk(m1 != m2 and n1 != n2,
            f"une collision force une avance sur les DEUX chemins "
            f"({_os.path.basename(m1)} -> {_os.path.basename(m2)})")
        chk(horodatage(1_800_000_001.0) in m2,
            f"et l'avance est de exactement 1 s, pas plus ({_os.path.basename(m2)})")

        # --- « rien n'est jamais écrasé » : preuve par DEUX séances, pas affirmation --------
        # Le format du nom (AAAAMMJJ-HHMMSS) a une résolution d'une SECONDE : deux séances
        # RÉUSSIES qui finissent la même seconde sont le cas exact qui a fait perdre les époques
        # d'une séance à 42 essais (nom fixe, à l'époque). Horloge ÉPINGLÉE pour reproduire cette
        # collision à coup sûr plutôt que de compter sur la chance, restaurée dans un `finally`.
        vrai_time = _time.time
        _time.time = lambda: 1_700_000_000.0
        try:
            premiere = MICalibration(_mi.SPEC, {"trials_per_class": 6}, None,
                                     rng=_random.Random(2), dossier=dossier)
            premiere.engine = _FauxMoteur(premiere, rng)
            t = 0.0
            for _ in range(20000):
                premiere.tick(premiere.engine, t)
                if premiere.terminee:
                    break
                t += 0.25
            chk(premiere.phase == "fini",
                f"la première des deux séances à la même seconde aboutit ({premiere.phase})")

            # L'empreinte est prise ICI, entre les deux séances — c'est elle qui distingue
            # « le fichier a survécu » de « un fichier du même nom existe, peu importe lequel ».
            hash_modele_avant = (_hash_fichier(premiere.resultat["modele"])
                                 if premiere.resultat else None)
            hash_npz_avant = (_hash_fichier(premiere.resultat["enregistrement"])
                              if premiere.resultat else None)

            seconde = MICalibration(_mi.SPEC, {"trials_per_class": 6}, None,
                                    rng=_random.Random(3), dossier=dossier)
            seconde.engine = _FauxMoteur(seconde, rng)
            t = 0.0
            for _ in range(20000):
                seconde.tick(seconde.engine, t)
                if seconde.terminee:
                    break
                t += 0.25
            chk(seconde.phase == "fini",
                f"la seconde des deux séances à la même seconde aboutit ({seconde.phase})")
        finally:
            _time.time = vrai_time

        res1, res2 = premiere.resultat or {}, seconde.resultat or {}
        chk(bool(res1.get("modele")) and bool(res2.get("modele"))
            and res1["modele"] != res2["modele"],
            f"deux séances à la MÊME seconde produisent deux modèles DISTINCTS "
            f"({_os.path.basename(res1.get('modele', '?'))} vs "
            f"{_os.path.basename(res2.get('modele', '?'))})")
        chk(bool(res1.get("enregistrement")) and bool(res2.get("enregistrement"))
            and res1["enregistrement"] != res2["enregistrement"],
            f"et deux enregistrements DISTINCTS "
            f"({_os.path.basename(res1.get('enregistrement', '?'))} vs "
            f"{_os.path.basename(res2.get('enregistrement', '?'))})")
        disponibles = mi_models.modeles_disponibles(dossier)
        chk(res1.get("modele") in disponibles and res2.get("modele") in disponibles,
            f"et les DEUX modèles sont listés, aucun n'a chassé l'autre "
            f"({[_os.path.basename(p) for p in disponibles]})")
        chk(hash_modele_avant is not None and bool(res1.get("modele"))
            and _hash_fichier(res1["modele"]) == hash_modele_avant,
            "le modèle de la PREMIÈRE séance est resté OCTET POUR OCTET intact après la seconde")
        chk(hash_npz_avant is not None and bool(res1.get("enregistrement"))
            and _hash_fichier(res1["enregistrement"]) == hash_npz_avant,
            "et son enregistrement aussi")

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
