### Task 3: `CalibrationRuntime` — la ligne du temps, et le protocole MI

**Files:**
- Create: `src/core/modes/calibration.py`
- Create: `src/core/modes/mi_calib.py`
- Modify: `src/core/modes/mi.py` (renseigner `calibration=` dans `SPEC`)
- Test: les autotests des deux nouveaux fichiers (`python src/core/modes/calibration.py`,
  `python src/core/modes/mi_calib.py`)

**Interfaces:**
- **Consomme** — `Calib(kind, label, briefing, params, epoch_s, runtime_cls)` et
  `MIModel.fit(epochs, y, groups=...)` (T1) ; `EngineServer.recent_window(seconds)` et
  `engine.acq.fs` (existants).
- **Produit** — `CalibrationRuntime(spec, params, engine)` avec `tick(engine, now)`,
  `cancel()`, `terminee` (booléen), `state()` (dict JSON-able) ; `mi_calib.MICalibration` ;
  `mi_calib.CALIB` (l'objet `Calib` du MI, à poser dans `mi.SPEC`).

**Contrainte d'architecture, la plus importante de la tâche :** un runtime ne lit **jamais**
l'horloge lui-même — `tick` reçoit `now`. C'est ce qui rend la ligne du temps testable sans dormir,
et c'est la règle que `ModeRuntime` suit déjà (voir sa docstring). Une calibration qui appellerait
`time.perf_counter()` obligerait son test à durer sept minutes.

- [ ] **Step 1: Écrire `src/core/modes/calibration.py`**

```python
"""`CalibrationRuntime` — la ligne du temps d'une calibration, jouée par le MOTEUR.

Ce qui est ICI est ce que **toute** calibration partage : la chauffe, l'échauffement non
enregistré, la suite d'essais tirés au hasard, l'entraînement, le résultat. Ce qui est dans les
sous-classes est ce qui diffère : les classes à cuer, les consignes, et ce qu'on fait des époques
à la fin.

⚠️ **Une calibration n'est PAS un mode.** Elle vit dans un emplacement propre du moteur
(`EngineServer.calibration`), pas dans `self.active`. La raison est concrète : le mode Motor
Imagery REFUSE de démarrer sans modèle entraîné, donc une calibration hébergée par ce mode serait
inatteignable pour la seule personne qui en a besoin — celle qui n'a pas encore de modèle.

⚠️ **Un runtime ne lit jamais l'horloge lui-même** : `tick` reçoit `now`, comme `ModeRuntime`.
C'est ce qui permet de jouer une séance de sept minutes en quelques millisecondes dans un test.

Autotest :
    python src/core/modes/calibration.py
"""

import os as _os
import random as _random
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import use_utf8_console  # noqa: E402

# Les phases publiques, dans l'ordre où elles s'enchaînent. Elles sortent telles quelles dans
# `snapshot()["calibration"]["phase"]` : la console les traduit, elle n'en invente aucune.
PHASES = ("chauffe", "echauffement", "essais", "entrainement", "fini", "annule")

# Les étapes À L'INTÉRIEUR d'un essai.
ETAPES = ("cue", "imagerie", "repos")


class CalibrationRuntime:
    """Une calibration en cours. Le moteur en tient AU PLUS UNE — le casque est unique."""

    # --- à renseigner par la sous-classe ------------------------------------
    classes = ()            # les étiquettes à cuer, dans l'ordre de déclaration
    cue_s = 3.0             # mise en route, JETÉE
    imagery_s = 4.0         # la partie ENREGISTRÉE
    rest_s = 1.5            # pause entre deux essais
    warmup_s = 15.0         # stabilisation du casque, JETÉE (dérive DC de l'Unicorn)
    warmup_per_class = 2    # essais d'échauffement NON enregistrés

    def __init__(self, spec, params, engine, rng=None):
        """`spec` : le `ModeSpec` du mode calibré. `params` : les réglages VALIDÉS de la calibration.

        `rng` est injectable pour que le test obtienne un ordre reproductible. En séance il est
        tiré au hasard, et il DOIT l'être : un ordre fixe apprendrait au sujet à anticiper la
        classe suivante, ce qui contamine l'imagerie par de l'attente motrice.
        """
        self.spec = spec
        self.calib = spec.calibration
        self.params = dict(params)
        self.engine = engine
        self.rng = rng or _random.Random()

        self.phase = "chauffe"
        self.etape = ""
        self.classe = ""
        self.essai = 0            # essais ENREGISTRÉS déjà terminés
        self.resultat = None
        self.probleme = ""
        self._echeance = None     # instant de fin de l'étape en cours (horloge de l'appelant)
        self._suite = []          # les étiquettes restantes de la phase en cours
        self._enregistre = []     # [(époque (n, 8), étiquette)]
        self._demarre = False

    # --- ce que la sous-classe fournit ---------------------------------------

    def instruction(self):
        """La consigne à afficher MAINTENANT, en grand."""
        return ""

    def rappel(self):
        """La ligne secondaire, sous la consigne. "" s'il n'y en a pas."""
        return ""

    def _entrainer(self, enregistre, fs):
        """Entraîne et sauvegarde. Rend le dict de résultat, ou lève avec un message lisible."""
        raise NotImplementedError

    # --- la ligne du temps ---------------------------------------------------

    @property
    def terminee(self):
        return self.phase in ("fini", "annule")

    def trials_per_class(self):
        return int(self.params.get("trials_per_class", 0))

    def total(self):
        """Le nombre d'essais ENREGISTRÉS de la séance. L'échauffement n'en fait pas partie."""
        return self.trials_per_class() * len(self.classes)

    def duree_estimee_s(self):
        """Le temps total, échauffement et chauffe compris. Calculé, jamais stocké."""
        par_essai = self.cue_s + self.imagery_s + self.rest_s
        n = self.total() + self.warmup_per_class * len(self.classes)
        return self.warmup_s + n * par_essai

    def cancel(self):
        """Abandon. Ce qui est déjà enregistré n'est PAS entraîné ni sauvegardé.

        Choix délibéré : une séance interrompue à cinq essais produirait un modèle que rien ne
        distingue d'un modèle complet dans la liste, et qui donnerait des probabilités plausibles
        et fausses. L'écran pygame, lui, entraînait sur ce qui restait — comportement qu'on ne
        reprend pas.
        """
        if not self.terminee:
            self.phase = "annule"
            self.etape, self.classe, self._echeance = "", "", None

    def tick(self, engine, now):
        """Un pas. Appelé par la boucle du moteur, jamais par une interface."""
        if self.terminee:
            return
        if not self._demarre:
            self._demarre = True
            self._echeance = now + self.warmup_s
            return

        if self._echeance is not None and now < self._echeance:
            return

        if self.phase == "chauffe":
            self._commencer_echauffement(now)
        elif self.phase in ("echauffement", "essais"):
            self._pas_essai(engine, now)
        elif self.phase == "entrainement":
            self._terminer(engine)

    def _commencer_echauffement(self, now):
        self._suite = self._tirage(self.warmup_per_class)
        if not self._suite:
            self._commencer_essais(now)
            return
        self.phase = "echauffement"
        self._prochain_essai(now)

    def _commencer_essais(self, now):
        self.phase = "essais"
        self._suite = self._tirage(self.trials_per_class())
        if not self._suite:
            self.phase = "entrainement"
            self.etape, self.classe, self._echeance = "", "", now
            return
        self._prochain_essai(now)

    def _tirage(self, par_classe):
        """Les étiquettes d'une phase, MÉLANGÉES. Un ordre fixe s'anticipe (cf. `__init__`)."""
        suite = [c for c in self.classes for _ in range(par_classe)]
        self.rng.shuffle(suite)
        return suite

    def _prochain_essai(self, now):
        self.classe = self._suite.pop(0)
        self.etape = "cue"
        self._echeance = now + self.cue_s

    def _pas_essai(self, engine, now):
        if self.etape == "cue":
            self.etape = "imagerie"
            self._echeance = now + self.imagery_s
            return

        if self.etape == "imagerie":
            # L'époque est prélevée À LA FIN de l'imagerie, pas au fil de l'eau : le tampon
            # glissant du moteur contient les `imagery_s` dernières secondes, et c'est exactement
            # celles-là qu'on veut. `epoch_s` du contrat garantit que le tampon est assez long.
            if self.phase == "essais":
                epoque = engine.recent_window(self.imagery_s)
                attendu = int(round(self.imagery_s * engine.acq.fs))
                if epoque is not None and len(epoque) >= attendu:
                    self._enregistre.append((epoque, self.classe))
                    self.essai += 1
                else:
                    # On le DIT plutôt que d'enregistrer une époque courte : un essai tronqué
                    # produit moins de fenêtres d'entraînement, en silence.
                    obtenu = 0 if epoque is None else len(epoque)
                    print(f"[calib] essai IGNORÉ ({self.classe}) : {obtenu} échantillons au lieu "
                          f"de {attendu} — le tampon du moteur n'était pas encore rempli")
            self.etape = "repos"
            self._echeance = now + self.rest_s
            return

        # repos terminé
        if self._suite:
            self._prochain_essai(now)
        elif self.phase == "echauffement":
            self._commencer_essais(now)
        else:
            self.phase = "entrainement"
            self.etape, self.classe, self._echeance = "", "", now

    def _terminer(self, engine):
        """L'entraînement. Bloque la boucle du moteur le temps du `fit` — quelques secondes.

        C'est assumé : à cet instant, plus rien ne doit être acquis pour cette séance, et
        déporter l'entraînement dans un fil ferait toucher `data/` par deux fils. Le décodage des
        autres modes est simplement suspendu pendant ce temps.
        """
        try:
            self.resultat = self._entrainer(self._enregistre, float(engine.acq.fs))
            self.phase = "fini"
        except Exception as e:  # noqa: BLE001 - l'échec de l'entraînement ne tue pas le moteur
            self.probleme = f"{type(e).__name__} : {e}"
            self.phase = "annule"
            print(f"[calib] entraînement impossible : {self.probleme}")
        self.etape, self.classe, self._echeance = "", "", None

    # --- l'état, pour l'afficheur -------------------------------------------

    def restant_s(self, now):
        """Secondes restantes sur l'étape en cours. 0 quand il n'y a rien à décompter."""
        if self._echeance is None:
            return 0.0
        return max(0.0, self._echeance - now)

    def state(self, now=None):
        """L'état complet, en dictionnaire JSON-able. Sûr depuis un autre fil.

        `now` est facultatif : sans lui, le décompte vaut 0. Le moteur le passe depuis sa boucle,
        et c'est la seule horloge qui fait foi.
        """
        return {
            "mode_id": self.spec.id,
            "label": self.calib.label or f"Calibration {self.spec.label}",
            "phase": self.phase,
            "etape": self.etape,
            "classe": self.classe,
            "instruction": self.instruction(),
            "rappel": self.rappel(),
            "essai": self.essai,
            "total": self.total(),
            "restant_s": round(self.restant_s(now or 0.0), 1) if now else 0.0,
            "duree_estimee_s": round(self.duree_estimee_s(), 1),
            "params": dict(self.params),
            "classes": list(self.classes),
            "resultat": self.resultat,
            "probleme": self.probleme,
        }


def _selftest():
    """La ligne du temps sur une horloge FABRIQUÉE. Aucune séance, aucune attente réelle."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    import numpy as np

    from core.modes.contract import Calib, ModeSpec, Param

    class _FausseAcq:
        fs = 250.0

    class _FauxMoteur:
        """Rend toujours une époque de la bonne longueur : on teste la LIGNE DU TEMPS, pas
        l'acquisition."""

        def __init__(self):
            self.acq = _FausseAcq()
            self.demandes = []

        def recent_window(self, seconds):
            self.demandes.append(seconds)
            return np.zeros((int(round(seconds * self.acq.fs)), 8))

    class _Essai(CalibrationRuntime):
        classes = ("A", "B")
        cue_s, imagery_s, rest_s, warmup_s, warmup_per_class = 3.0, 4.0, 1.5, 15.0, 2

        def instruction(self):
            return f"Fais {self.classe}" if self.classe else ""

        def _entrainer(self, enregistre, fs):
            return {"n_essais": len(enregistre), "fs": fs,
                    "classes": sorted({lab for _e, lab in enregistre})}

    spec = ModeSpec(
        id="essai", label="Essai", family="actif", summary="", status="moteur",
        calibration=Calib(kind="console", label="Calibration d'essai", epoch_s=4.0,
                          params=(Param("trials_per_class", "Essais par classe", "int",
                                        default=3, min=1, max=40),),
                          runtime_cls=_Essai))

    moteur = _FauxMoteur()
    rt = _Essai(spec, {"trials_per_class": 3}, moteur, rng=_random.Random(0))

    chk(rt.total() == 6, f"3 essais par classe sur 2 classes = 6 essais enregistrés ({rt.total()})")
    chk(abs(rt.duree_estimee_s() - (15.0 + 10 * 8.5)) < 1e-6,
        f"la durée estimée compte l'échauffement ET la chauffe ({rt.duree_estimee_s():.1f} s)")

    # La chauffe est JETÉE : rien n'est enregistré pendant, et elle dure ce qu'elle annonce.
    t = 100.0
    rt.tick(moteur, t)
    chk(rt.phase == "chauffe", f"on commence par la chauffe ({rt.phase})")
    rt.tick(moteur, t + 14.9)
    chk(rt.phase == "chauffe" and not moteur.demandes,
        "pendant la chauffe, RIEN n'est prélevé (la dérive DC fausserait les époques)")

    # Une horloge fabriquée, pas à pas : on avance par petits sauts jusqu'à la fin de la séance.
    t = 115.0
    for _ in range(4000):
        rt.tick(moteur, t)
        if rt.terminee:
            break
        t += 0.25

    chk(rt.phase == "fini", f"la séance se termine ({rt.phase}, problème={rt.probleme!r})")
    chk(rt.essai == 6, f"6 essais enregistrés, pas un de plus ({rt.essai})")
    chk(rt.resultat and rt.resultat["n_essais"] == 6,
        f"et c'est ce qui part à l'entraînement ({rt.resultat})")
    chk(rt.resultat and sorted(rt.resultat["classes"]) == ["A", "B"],
        f"les deux classes sont représentées ({rt.resultat})")
    # 10 essais joués (4 d'échauffement + 6 enregistrés), 6 prélèvements : l'échauffement ne
    # prélève RIEN. C'est le seul test qui distingue « non enregistré » de « enregistré puis jeté ».
    chk(len(moteur.demandes) == 6,
        f"l'échauffement ne prélève aucune époque ({len(moteur.demandes)} prélèvements pour "
        f"{4 + 6} essais joués)")
    chk(all(abs(s - 4.0) < 1e-9 for s in moteur.demandes),
        f"et chaque prélèvement demande imagery_s, pas la durée de l'essai ({set(moteur.demandes)})")

    # L'abandon : ni entraînement, ni modèle. Une séance à moitié faite ne doit pas produire un
    # modèle indiscernable d'un modèle complet.
    rt2 = _Essai(spec, {"trials_per_class": 3}, _FauxMoteur(), rng=_random.Random(1))
    t = 0.0
    for _ in range(200):
        rt2.tick(rt2.engine, t)
        t += 0.25
    rt2.cancel()
    chk(rt2.phase == "annule" and rt2.resultat is None,
        f"un abandon ne produit AUCUN modèle ({rt2.phase}, {rt2.resultat})")
    avant = rt2.essai
    rt2.tick(rt2.engine, t + 100.0)
    chk(rt2.essai == avant and rt2.phase == "annule",
        "et une calibration annulée ne repart pas toute seule au tick suivant")

    # Un entraînement qui lève ne doit pas tuer le moteur : il se solde en « annulé » + raison.
    class _Casse(_Essai):
        def _entrainer(self, enregistre, fs):
            raise ValueError("pas assez de données")

    rt3 = _Casse(spec, {"trials_per_class": 1}, _FauxMoteur(), rng=_random.Random(2))
    t = 0.0
    for _ in range(4000):
        rt3.tick(rt3.engine, t)
        if rt3.terminee:
            break
        t += 0.25
    chk(rt3.phase == "annule" and "pas assez de données" in rt3.probleme,
        f"un entraînement qui lève se solde par un refus lisible ({rt3.phase}, {rt3.probleme})")

    # L'état est JSON-able : il part dans `snapshot()`, que la console sérialise.
    import json

    json.dumps(rt.state(now=t))
    chk(True, "l'état est sérialisable en JSON")
    etat = rt.state(now=t)
    chk(set(etat) >= {"phase", "etape", "classe", "instruction", "essai", "total", "restant_s",
                      "resultat", "probleme"},
        f"et il porte tout ce que la console doit peindre ({sorted(etat)})")

    print(f"[calibration] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
```

- [ ] **Step 2: Lancer l'autotest**

Run: `python src/core/modes/calibration.py`
Expected: `[calibration] VERDICT : OK`

- [ ] **Step 3: Écrire `src/core/modes/mi_calib.py`**

```python
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
        chk(_mi.SPEC.calibration is CALIB,
            "le mode MI déclare CETTE calibration dans son contrat")
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
```

- [ ] **Step 4: Brancher la calibration sur le contrat du mode MI**

Dans `src/core/modes/mi.py`, remplacer la ligne `calibration=None,` de `SPEC` par :

```python
    calibration=mi_calib.CALIB,   # la calibration est jouée par le MOTEUR (moitié B)
```

et ajouter l'import, **après** les autres imports `core.modes` :

```python
from core.modes import mi_calib  # noqa: E402
```

⚠️ **Vérifier qu'il n'y a pas de cycle d'import** : `mi_calib` importe `core.modes.calibration` et
`core.modes.contract`, mais **pas** `core.modes.mi`. Son autotest, lui, importe `core.modes.mi` —
mais à l'intérieur de `_selftest()`, donc à l'exécution, pas à l'import. Ne pas remonter cet
import en tête de `mi_calib.py` : ce serait le cycle.

- [ ] **Step 5: Lancer les deux autotests**

Run: `python src/core/modes/calibration.py` puis `python src/core/modes/mi_calib.py`
Expected: les deux en `VERDICT : OK`.

- [ ] **Step 6: Vérifier la non-régression**

Run, EN SÉRIE : `python src/core/modes/mi.py` · `python src/core/modes/registry.py` ·
`python src/core/server.py --smoke` · `python src/console/app.py --smoke`
Expected: tous en sortie 0. `server.py --smoke` vérifie aussi la frontière `core` → pas de pygame,
pas de Qt, pas d'import de `research` : les deux nouveaux fichiers y passent.

- [ ] **Step 7: Commit**

```bash
git add src/core/modes/calibration.py src/core/modes/mi_calib.py src/core/modes/mi.py
git commit -m "Give the engine a calibration timeline, and Motor Imagery its protocol"
```

---

