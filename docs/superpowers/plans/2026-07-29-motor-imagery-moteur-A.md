# Motor Imagery sur le réseau — plan d'implémentation (moitié A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** publier l'intention Motor Imagery sur le réseau LSL, pour qu'une application extérieure
(Unity) puisse la consommer — sans toucher à la calibration, qui est la moitié B.

**Architecture :** le décodeur MI déménage de `src/research/` vers `src/core/` (il est déjà pur :
numpy/scipy/sklearn + `core.config`). Un `MIRuntime`, calqué sur `SsvepRuntime`, charge un modèle
entraîné, glisse une fenêtre de 2 s, vote sur 5 décisions, et publie sur `decoded_mi`. Le modèle se
choisit dans le formulaire de la console, dont la liste est **découverte à l'exécution** — ce qui
oblige à donner au contrat des choix dynamiques.

**Tech Stack :** Python 3.12, numpy, scipy, scikit-learn, joblib, pylsl. Aucune dépendance
nouvelle.

**Conception :**
[docs/superpowers/specs/2026-07-29-motor-imagery-moteur-design.md](../specs/2026-07-29-motor-imagery-moteur-design.md).
La moitié B (calibration jouée par le moteur, gestion des modèles, archivage des écrans pygame)
fera l'objet d'un plan distinct, écrit après celui-ci.

## Global Constraints

- **`src/core/` n'importe JAMAIS `src/research/` ni `src/console/`**, et ne contient ni pygame ni
  Qt. Vérifié par un test, pas par la discipline : `python src/core/server.py --smoke` scanne
  `src/core/**/*.py` et échoue sur le moindre import interdit.
- **Code, commentaires et docstrings en français. Messages de commit en anglais.**
- **Tout doit être testable sans casque** : board synthétique BrainFlow, ou signal fabriqué.
- **Les constantes du protocole MI ne bougent pas.** `MI_WINDOW_S = 2.0`, `MI_PROB_MIN = 0.60`,
  `MI_VOTE_LEN = 5`, `MI_MIN_VOTES = 3`, `MI_REREF = "car"`, `MI_METHOD = "csp"`,
  `MI_BAND = (8.0, 30.0)`, `MI_LABELS = ("GAUCHE", "DROITE", "REPOS")`. Elles portent des
  justifications datées issues du casque.
- **Aucun moteur ne doit tourner pendant un test.** Les noms de flux sont un contrat public, donc
  identiques pour toutes les instances : un serveur oublié répond à la place de celui qu'on teste.
  Vérifier avec `Get-Process python` avant chaque série.
- **Le flux publie une intention neutre**, jamais une commande d'actionneur.
- Chaque tâche finit par un commit, et par les trois smokes verts :
  `python src/core/server.py --smoke` · `python src/console/app.py --smoke` ·
  `python src/research/app.py --smoke`.

## Structure des fichiers

| Fichier | Responsabilité | Tâche |
|---|---|---|
| `src/core/mi_decoder.py` | **déplacé** depuis `research/` — CSP+LDA, `MIModel`, `MIDecoder` | 1 |
| `src/core/mi_models.py` | **créé** — découvrir les modèles sur disque, les charger sans lever, les décrire | 2 |
| `src/core/modes/contract.py` | **modifié** — choix dynamiques (`choices_fn`) | 3 |
| `src/core/modes/registry.py` | **modifié** — sérialiser les choix résolus, enregistrer le mode MI | 3, 5 |
| `src/core/acquisition.py` | **modifié** — `motor_window(block)`, fenêtre MI non filtrée | 4 |
| `src/core/lsl_io.py` | **modifié** — `mi_channel_labels`, `DecodedMIPublisher` | 4 |
| `src/core/modes/mi.py` | **créé** — le `ModeSpec` et le `MIRuntime` | 5 |
| `src/core/modes/external.py` | **modifié** — l'entrée MI disparaît (elle devient un vrai mode) | 5 |
| `src/core/server.py` | **modifié** — tampon dimensionné pour le MI, smoke du mode | 6 |
| `examples/unity/MiIntentReceiver.cs` | **créé** — le récepteur C# | 7 |
| `README.md`, `docs/SPEC.md`, `CLAUDE.md` | **modifiés** — le MI sort sur le réseau | 7 |

---

## Task 1 : déménager le décodeur MI dans `core/`

**Files:**
- Move: `src/research/mi_decoder.py` → `src/core/mi_decoder.py`
- Modify: `src/research/app.py:425`, `src/research/mi_calibrate.py:29`,
  `src/research/mi_compare.py:21`, `src/research/mi_pilot.py:29`

**Interfaces:**
- Consomme : rien.
- Produit : `core.mi_decoder` expose `MI_LABELS`, `MI_BAND`, `MIModel`, `MIDecoder`, `CSP`,
  `build_pipe`, `bandpass`, `reref`, `synth_mi_trial` — les mêmes noms qu'avant, à la même
  signature. Seul le chemin d'import change.

⚠️ **Ce déménagement invalide les modèles déjà sur disque, et c'est VOULU.** `MIModel.save` pickle
l'instance, donc le pickle porte le chemin du module. Les quatre `.joblib` de `data/` référencent
déjà un module `mi_decoder` disparu depuis la restructuration du 2026-07-27 : **ils ne se chargent
plus aujourd'hui**. La spec §3 acte leur abandon. Ne pas écrire de migration.

- [ ] **Étape 1 : déplacer le fichier en gardant l'historique**

```bash
git mv src/research/mi_decoder.py src/core/mi_decoder.py
```

- [ ] **Étape 2 : corriger le chemin d'insertion dans `sys.path`**

Dans `src/core/mi_decoder.py`, la ligne actuelle remonte de deux crans depuis `src/research/` pour
atteindre `src/`. Depuis `src/core/` elle vise le même endroit, donc **elle est déjà correcte** —
vérifier qu'elle est bien celle-ci et ne rien changer :

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

- [ ] **Étape 3 : mettre à jour les quatre importeurs**

`src/research/app.py:425` :

```python
    from core.mi_decoder import MIDecoder, MIModel
```

`src/research/mi_calibrate.py:29` :

```python
from core.mi_decoder import MI_LABELS, MIModel  # noqa: E402
```

`src/research/mi_compare.py:21` :

```python
from core.mi_decoder import MI_BAND, bandpass, build_pipe, reref  # noqa: E402
```

`src/research/mi_pilot.py:29` :

```python
from core.mi_decoder import MI_LABELS, MIDecoder, MIModel  # noqa: E402
```

- [ ] **Étape 4 : vérifier qu'il ne reste aucun import de l'ancien chemin**

Run: `grep -rn "research.mi_decoder\|research import mi_decoder" src/ examples/`
Expected: aucune ligne.

- [ ] **Étape 5 : l'autotest du décodeur, à son nouveau chemin**

Run: `python src/core/mi_decoder.py`
Expected: il se termine par un verdict OK (il valide CSP+LDA sur de l'ERD synthétique).

- [ ] **Étape 6 : les trois smokes**

Run: `python src/core/server.py --smoke` puis `python src/console/app.py --smoke` puis
`python src/research/app.py --smoke`
Expected: trois verdicts OK. Le premier est le plus important ici : il scanne `src/core/**` et
échouerait si `mi_decoder.py` importait quoi que ce soit de `research`.

- [ ] **Étape 7 : commit**

```bash
git add -A src/core/mi_decoder.py src/research/
git commit -m "Move the MI decoder into the engine's package"
```

---

## Task 2 : découvrir et décrire les modèles entraînés

**Files:**
- Create: `src/core/mi_models.py`

**Interfaces:**
- Consomme : `core.mi_decoder.MIModel` (tâche 1), `core.config.DATA_DIR`.
- Produit :
  - `modeles_disponibles(dossier=DATA_DIR) -> list[str]` — chemins des modèles **réellement
    chargeables**, du plus récent au plus ancien.
  - `charger(chemin) -> (MIModel|None, str|None)` — ne lève jamais.
  - `decrire(chemin) -> dict` avec les clés `chemin`, `nom`, `date`, `classes`, `cv_naive`,
    `cv_groupee`, `n_essais`.
  - `MOTIF = "mi_model*.joblib"`.

**Pourquoi la liste ne garde que ce qui se charge** : les quatre modèles hérités ne se chargent
plus (tâche 1). En filtrant à la découverte, ils deviennent simplement invisibles — l'abandon
décidé dans la spec est réalisé par construction, sans code d'exclusion à maintenir.

**Pourquoi on ne met PAS de cache** : la moitié B fera apparaître un modèle neuf à la fin de chaque
calibration. Un cache le masquerait jusqu'au redémarrage du moteur. La liste est appelée à la
construction du catalogue, pas dans une boucle.

- [ ] **Étape 1 : écrire l'autotest en tête du fichier de test intégré**

Créer `src/core/mi_models.py` avec, pour l'instant, uniquement son autotest — il doit échouer.

```python
"""Les modèles MI présents sur le disque : lesquels existent, lesquels se chargent, ce qu'ils valent.

Un modèle MI est un objet `MIModel` picklé par joblib. Le pickle porte le CHEMIN DU MODULE de la
classe : un modèle écrit avant que `mi_decoder` ne rejoigne `core/` ne se recharge donc plus. On
ne tente pas de les rattraper (décision de conception, cf. spec §3) — on les rend invisibles en ne
listant que ce qui se charge vraiment.

Autotest :
    python src/core/mi_models.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from core.config import DATA_DIR, use_utf8_console  # noqa: E402


def _selftest():
    """Sur un dossier temporaire : un modèle valide, un fichier corrompu, un dossier vide."""
    import shutil
    import tempfile

    import numpy as np

    from core.mi_decoder import MI_LABELS, MIModel, synth_mi_trial

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    dossier = tempfile.mkdtemp(prefix="mi_models_")
    try:
        chk(modeles_disponibles(dossier) == [],
            "un dossier sans modèle rend une liste vide, il ne lève pas")

        rng = np.random.default_rng(0)
        epochs, y = [], []
        for label in MI_LABELS:
            for _ in range(6):
                epochs.append(synth_mi_trial(label, rng=rng))
                y.append(label)
        modele = MIModel(fs=250.0).fit(np.asarray(epochs), np.asarray(y))
        bon = _os.path.join(dossier, "mi_model.joblib")
        modele.save(bon)

        chk(modeles_disponibles(dossier) == [bon],
            f"un modèle valide est listé ({modeles_disponibles(dossier)})")

        # Un fichier au bon nom mais illisible : c'est exactement l'état des modèles hérités.
        casse = _os.path.join(dossier, "mi_model_casse.joblib")
        with open(casse, "wb") as f:
            f.write(b"ceci n'est pas un pickle")
        listes = modeles_disponibles(dossier)
        chk(casse not in listes,
            f"un modèle illisible n'apparaît PAS dans la liste ({listes})")

        _m, raison = charger(casse)
        chk(_m is None and raison,
            f"et le charger rend une raison au lieu de lever ({raison})")

        _m, raison = charger(_os.path.join(dossier, "absent.joblib"))
        chk(_m is None and "introuvable" in (raison or ""),
            f"un chemin inexistant est signalé comme tel ({raison})")

        d = decrire(bon)
        chk(d["nom"] == "mi_model.joblib", f"la description porte le nom du fichier ({d['nom']})")
        chk(list(d["classes"]) == list(MI_LABELS), f"et les classes du modèle ({d['classes']})")
        chk(isinstance(d["cv_naive"], float) and 0.0 <= d["cv_naive"] <= 1.0,
            f"la CV du contrat d'entraînement est une proportion ({d['cv_naive']})")
        chk(d["cv_groupee"] is None,
            "la CV honnête est absente d'un modèle entraîné avant la moitié B — dit, pas inventé")
        chk(d["date"], f"et une date lisible ({d['date']})")

        # Le plus récent d'abord : c'est ce qui rend le défaut du réglage « le dernier entraîné ».
        recent = _os.path.join(dossier, "mi_model_2.joblib")
        modele.save(recent)
        _os.utime(bon, (1_600_000_000, 1_600_000_000))
        chk(modeles_disponibles(dossier)[0] == recent,
            f"le plus récent vient en tête ({modeles_disponibles(dossier)})")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[mi-models] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
```

- [ ] **Étape 2 : lancer l'autotest pour le voir échouer**

Run: `python src/core/mi_models.py`
Expected: `NameError: name 'modeles_disponibles' is not defined`.

- [ ] **Étape 3 : écrire les trois fonctions**

À insérer entre l'import de `core.config` et `_selftest` :

```python
import glob as _glob  # noqa: E402
import time as _time  # noqa: E402

MOTIF = "mi_model*.joblib"     # tous les modèles MI ; la calibration en écrira d'horodatés


def charger(chemin):
    """(modèle, None) ou (None, raison en clair). Ne lève JAMAIS.

    Un modèle illisible n'est pas un incident exceptionnel ici : c'est l'état normal de tout
    modèle écrit avant que `mi_decoder` ne rejoigne `core/`. Le signaler par une exception
    ferait tomber le moteur pour un fichier qu'on aurait simplement dû ignorer.
    """
    if not _os.path.isfile(chemin):
        return None, f"modèle introuvable : {chemin}"
    try:
        import joblib
        modele = joblib.load(chemin)
    except Exception as e:      # noqa: BLE001 - pickle casse de mille façons, toutes équivalentes ici
        return None, f"modèle illisible ({type(e).__name__}) : {_os.path.basename(chemin)}"
    if not hasattr(modele, "labels") or not hasattr(modele, "predict_proba"):
        return None, f"ce n'est pas un modèle MI : {_os.path.basename(chemin)}"
    return modele, None


def modeles_disponibles(dossier=DATA_DIR):
    """Les modèles MI RÉELLEMENT chargeables, du plus récent au plus ancien.

    On charge pour lister, au lieu de se fier au nom : un fichier au bon nom mais au mauvais
    format apparaîtrait dans le formulaire de la console et échouerait au démarrage du mode —
    exactement le genre de « ça a l'air bon » que ce produit cherche à supprimer. Les fichiers
    font quelques kilo-octets, la liste est construite à l'ouverture du catalogue, pas en boucle.
    """
    chemins = sorted(_glob.glob(_os.path.join(dossier, MOTIF)),
                     key=_os.path.getmtime, reverse=True)
    return [c for c in chemins if charger(c)[0] is not None]


def decrire(chemin):
    """Ce qu'il faut afficher à côté d'un modèle pour le choisir en connaissance de cause.

    `cv_groupee` est la validation croisée HONNÊTE (par essai). Elle vaut None pour tout modèle
    entraîné avant la moitié B : on l'affiche absente plutôt que de recopier `cv_naive`, qui est
    gonflée de 10 à 16 points par la fuite entre fenêtres d'un même essai.
    """
    modele, raison = charger(chemin)
    horodatage = _os.path.getmtime(chemin) if _os.path.isfile(chemin) else 0.0
    infos = {
        "chemin": chemin,
        "nom": _os.path.basename(chemin),
        "date": _time.strftime("%Y-%m-%d %H:%M", _time.localtime(horodatage)) if horodatage else "",
        "classes": (),
        "cv_naive": None,
        "cv_groupee": None,
        "n_essais": None,
        "probleme": raison,
    }
    if modele is None:
        return infos
    infos["classes"] = tuple(modele.labels)
    cv = getattr(modele, "cv_", None)
    infos["cv_naive"] = float(cv) if cv is not None else None
    groupee = getattr(modele, "cv_groupee_", None)
    infos["cv_groupee"] = float(groupee) if groupee is not None else None
    essais = getattr(modele, "n_essais_", None)
    infos["n_essais"] = int(essais) if essais is not None else None
    return infos
```

- [ ] **Étape 4 : relancer l'autotest**

Run: `python src/core/mi_models.py`
Expected: `[mi-models] VERDICT : OK`.

- [ ] **Étape 5 : vérifier sur les vrais fichiers du poste**

Run: `python -c "import sys; sys.path.insert(0,'src'); from core.mi_models import modeles_disponibles; print(modeles_disponibles())"`
Expected: **une liste vide**. Les quatre modèles de `data/` sont hérités et ne se chargent plus.
Si la liste n'est pas vide, s'arrêter et le signaler : cela voudrait dire qu'un modèle a été
entraîné entre-temps, et il faut savoir lequel.

- [ ] **Étape 6 : commit**

```bash
git add src/core/mi_models.py
git commit -m "List the MI models that actually load, newest first"
```

---

## Task 3 : des choix dynamiques dans le contrat

**Files:**
- Modify: `src/core/modes/contract.py` (`Param`, `_coerce`, `ModeSpec.defaults`)
- Modify: `src/core/modes/registry.py` (`serialize`)

**Interfaces:**
- Consomme : rien de neuf.
- Produit :
  - `Param.choices_fn: object = None` — `() -> iterable`, quand les choix sont découverts à
    l'exécution.
  - `Param.choices_now() -> tuple` — les choix résolus.
  - `Param.default_now()` — le défaut, qui vaut **le premier choix** pour un `kind="choice"` sans
    défaut explicite.
  - `ModeSpec.defaults()` utilise `default_now()`.
  - `serialize()` envoie `"choices": list(p.choices_now())`.

**Pourquoi ce détour** : la liste des modèles MI n'existe pas au moment où le `ModeSpec` est
déclaré — elle dépend du contenu de `data/`. `ModeSpec` a déjà exactement ce motif pour les voies
(`channels_fn`), parce que les voies SSVEP dépendent des fréquences réglées. On le reproduit pour
les choix plutôt que d'inventer un mécanisme différent.

- [ ] **Étape 1 : écrire les tests dans l'autotest de `contract.py`**

Ajouter, dans `_selftest()` de `src/core/modes/contract.py`, juste avant la ligne qui imprime le
verdict :

```python
    # --- choix dynamiques : la liste n'existe qu'à l'exécution -------------------
    dispo = ["a.joblib", "b.joblib"]
    spec_dyn = ModeSpec(
        id="dyn", label="Dynamique", family="actif", summary="", status="moteur",
        params=(Param(key="modele", label="Modèle entraîné", kind="choice",
                      choices_fn=lambda: list(dispo),
                      help="Produit par une calibration."),),
        stream="decoded_dyn", channels=("x",))
    p = spec_dyn.params[0]
    chk(p.choices_now() == ("a.joblib", "b.joblib"),
        f"les choix sont résolus à l'appel ({p.choices_now()})")
    chk(spec_dyn.defaults()["modele"] == "a.joblib",
        f"sans défaut déclaré, un « choice » prend le PREMIER choix ({spec_dyn.defaults()})")

    _v, raison = validate(spec_dyn, {"modele": "b.joblib"})
    chk(raison is None, f"un choix présent dans la liste est accepté ({raison})")
    _v, raison = validate(spec_dyn, {"modele": "z.joblib"})
    chk(raison is not None and "n'est pas un choix valide" in raison,
        f"un choix absent de la liste est refusé ({raison})")

    # La liste change SANS que le contrat soit rechargé : c'est tout l'intérêt.
    dispo.append("c.joblib")
    chk(p.choices_now()[-1] == "c.joblib",
        "un nouveau choix apparaît sans redémarrer — aucun cache ne le masque")

    # Liste VIDE : le refus doit dire quoi faire, sinon l'étudiant reste devant un champ mort.
    dispo.clear()
    chk(spec_dyn.defaults()["modele"] is None,
        f"sans aucun choix, le défaut est None ({spec_dyn.defaults()})")
    _v, raison = validate(spec_dyn, {})
    chk(raison is not None and "aucun choix disponible" in raison
        and "Produit par une calibration." in raison,
        f"et le refus reprend l'aide du réglage ({raison})")
```

- [ ] **Étape 2 : lancer l'autotest pour le voir échouer**

Run: `python src/core/modes/contract.py`
Expected: `TypeError: Param.__init__() got an unexpected keyword argument 'choices_fn'`.

- [ ] **Étape 3 : ajouter le champ et les deux accesseurs à `Param`**

Dans `src/core/modes/contract.py`, ajouter le champ après `choices` :

```python
    choices: tuple = ()
    choices_fn: object = None  # () -> choix, quand ils sont DÉCOUVERTS à l'exécution (modèles MI)
```

Puis, à la fin de la classe `Param` :

```python
    def choices_now(self):
        """Les choix, résolus maintenant.

        Un modèle entraîné apparaît dans `data/` à la fin d'une calibration, donc bien après que
        ce contrat a été déclaré. Résoudre à l'appel — sans cache — est ce qui fait qu'il est
        proposable tout de suite au lieu du prochain démarrage du moteur.
        """
        return tuple(self.choices_fn()) if self.choices_fn else tuple(self.choices)

    def default_now(self):
        """Le défaut de ce réglage. Pour un « choice » sans défaut : le PREMIER choix.

        Les listes dynamiques sont rendues du plus récent au plus ancien, donc « le premier »
        veut dire « le dernier entraîné » — le choix qu'un étudiant attend après une calibration.
        None quand il n'y a rien : c'est `validate` qui le refusera, avec l'aide du réglage.
        """
        if self.default is not None:
            return self.default
        if self.kind == "choice":
            choix = self.choices_now()
            return choix[0] if choix else None
        return None
```

- [ ] **Étape 4 : faire lire `default_now()` par `ModeSpec.defaults()`**

Remplacer le corps de `ModeSpec.defaults` :

```python
    def defaults(self):
        """Le jeu de réglages par défaut de ce mode, résolu maintenant."""
        return {p.key: p.default_now() for p in self.params}
```

- [ ] **Étape 5 : faire lire les choix résolus par `_coerce`**

Remplacer la branche `choice` de `_coerce` :

```python
    if param.kind == "choice":
        choix = param.choices_now()
        if not choix:
            # Cas courant, pas exceptionnel : aucun modèle entraîné encore. Le refus doit dire
            # comment en obtenir un, sinon l'étudiant voit un champ vide et rien d'autre.
            detail = f" — {param.help}" if param.help else ""
            return None, f"« {param.label} » : aucun choix disponible{detail}"
        if value not in choix:
            return None, (f"« {param.label} » : {value!r} n'est pas un choix valide "
                          f"({', '.join(str(c) for c in choix)})")
        return value, None
```

- [ ] **Étape 6 : relancer l'autotest**

Run: `python src/core/modes/contract.py`
Expected: `[contract] VERDICT : OK`.

- [ ] **Étape 7 : sérialiser les choix résolus vers la console**

Dans `src/core/modes/registry.py`, remplacer `"choices": list(p.choices),` par :

```python
             "choices": list(p.choices_now()),
```

- [ ] **Étape 8 : vérifier le registre et les smokes**

Run: `python src/core/modes/registry.py` puis les trois smokes.
Expected: quatre verdicts OK.

- [ ] **Étape 9 : commit**

```bash
git add src/core/modes/contract.py src/core/modes/registry.py
git commit -m "Let a setting discover its choices at runtime"
```

---

## Task 4 : la fenêtre MI et le flux `decoded_mi`

**Files:**
- Modify: `src/core/acquisition.py` (ajout de `motor_window`)
- Modify: `src/core/lsl_io.py` (ajout de `mi_channel_labels` et `DecodedMIPublisher`)

**Interfaces:**
- Consomme : `core.config.MI_WINDOW_S`.
- Produit :
  - `UnicornAcquisition.motor_window(block, seconds=MI_WINDOW_S) -> ndarray|None`, de forme
    `(n_échantillons, 8)`, **non filtrée**.
  - `mi_channel_labels(classes) -> list[str]` = `["intent_index", "confidence"] + [f"p_{c}" …]`.
  - `DecodedMIPublisher(classes, prob_min, votes, instance="")` avec
    `push(intent_index, confidence, probas, lsl_ts=None)`, `probas` dans l'ordre de `classes`.

⚠️ **La fenêtre MI n'est pas filtrée, exprès.** `MIModel._prep` applique lui-même le
re-référencement CAR puis le passe-bande 8-30 Hz. Filtrer ici filtrerait deux fois : la phase
serait décalée et les variances que le CSP exploite ne seraient plus celles de l'entraînement. Les
époques d'entraînement viennent de `get_epoch(...)`, dont le défaut est `filtered=False` — l'online
doit lui ressembler.

- [ ] **Étape 1 : ajouter le test de la fenêtre dans l'autotest d'`acquisition.py`**

Repérer `_selftest` (ou la fonction d'autotest du module) et y ajouter :

```python
    # Fenêtre MI : toutes les voies, 2 s, et surtout NON filtrée — le modèle filtre lui-même.
    acq_mi = UnicornAcquisition(synthetic=True)
    bloc = np.random.default_rng(0).normal(0.0, 8.0, (int(5.0 * acq_mi.fs), 8))
    fen = acq_mi.motor_window(bloc)
    chk(fen is not None and fen.shape == (int(MI_WINDOW_S * acq_mi.fs), 8),
        f"la fenêtre MI fait 2 s sur les 8 voies ({None if fen is None else fen.shape})")
    chk(np.allclose(fen, bloc[-len(fen):]),
        "et elle rend le signal TEL QUEL : le modèle applique son propre CAR et son passe-bande")
    chk(acq_mi.motor_window(bloc[:10]) is None,
        "un bloc trop court rend None plutôt qu'une fenêtre incomplète")
```

Ajouter `MI_WINDOW_S` à l'import de `core.config` en tête d'`acquisition.py`.

- [ ] **Étape 2 : lancer pour voir échouer**

Run: `python src/core/acquisition.py`
Expected: `AttributeError: 'UnicornAcquisition' object has no attribute 'motor_window'`.

- [ ] **Étape 3 : écrire `motor_window`**

Juste après `occipital_window` :

```python
    def motor_window(self, block, seconds=MI_WINDOW_S):
        """Fenêtre MI (n x 8) depuis un bloc possédé par l'appelant. **Non filtrée**, exprès.

        Le Motor Imagery utilise les 8 voies — le CSP fait lui-même le tri spatial — et le
        modèle applique son propre re-référencement CAR puis son passe-bande 8-30 Hz dans
        `MIModel._prep`. Filtrer ici filtrerait deux fois : phase décalée et variances
        modifiées, or ce sont exactement les variances que le CSP exploite. Le modèle
        décoderait alors sur autre chose que ce sur quoi il a été entraîné — sans erreur, avec
        des probabilités parfaitement plausibles.

        Retourne None tant que le bloc est trop court.
        """
        need = int(round(seconds * self.fs))
        if block is None or len(block) < need:
            return None
        return np.asarray(block[-need:], dtype=float)
```

- [ ] **Étape 4 : relancer**

Run: `python src/core/acquisition.py`
Expected: verdict OK.

- [ ] **Étape 5 : ajouter le test du publieur dans l'autotest de `lsl_io.py`**

Dans l'autotest de `src/core/lsl_io.py` :

```python
    labels = mi_channel_labels(("GAUCHE", "DROITE", "REPOS"))
    print(f"  voies decoded_mi : {labels}")
    assert labels == ["intent_index", "confidence", "p_GAUCHE", "p_DROITE", "p_REPOS"], labels
    pub = DecodedMIPublisher(("GAUCHE", "DROITE", "REPOS"), prob_min=0.6, votes=(3, 5),
                             instance="selftest-mi")
    pub.push(0, 0.81, [0.81, 0.12, 0.07])
    pub.push(-1, 0.0, [0.34, 0.33, 0.33])
    print("  [lsl] decoded_mi publie sans lever")
```

- [ ] **Étape 6 : écrire `mi_channel_labels` et `DecodedMIPublisher`**

Juste après `DecodedNeuroPublisher` dans `src/core/lsl_io.py` :

```python
def mi_channel_labels(classes):
    """Voies du flux `decoded_mi` pour ces classes.

    Une seule fonction pour le publieur ET pour le `ModeSpec`, comme pour le SSVEP : les voies
    sont du contrat public, et deux façons de les construire finiraient par diverger.
    """
    return ["intent_index", "confidence"] + [f"p_{c}" for c in classes]


class DecodedMIPublisher:
    """`<PREFIX>_decoded_mi` : quelle imagerie motrice l'utilisateur produit, ~5 Hz. BCI **active**.

    Le contrat (SPEC §5) : une **intention neutre** — quelle classe, avec quelle probabilité —
    et JAMAIS une commande d'actionneur. « GAUCHE » veut dire « imagerie de la main gauche »,
    pas « tourne à gauche » : c'est le client qui décide ce que ça déclenche.

    Voies : `intent_index`, `confidence`, puis une probabilité par classe.

    ⚠️ **`-1` et la classe REPOS sont deux choses différentes.** `-1` = le vote n'a pas conclu
    (pas assez de fenêtres d'accord, ou probabilité sous le seuil) ; l'indice de REPOS = le
    modèle a décidé que la personne se repose. « Je ne sais pas » et « elle ne fait rien »
    n'appellent pas la même réaction dans une application.

    ⚠️ Ce mode exige un modèle ENTRAÎNÉ, propre à une personne. Les probabilités d'un modèle
    entraîné sur quelqu'un d'autre sont plausibles et fausses.
    """

    def __init__(self, classes, prob_min=0.0, votes=(0, 0), instance=""):
        self.classes = [str(c) for c in classes]
        labels = mi_channel_labels(self.classes)
        info = StreamInfo(stream_name("decoded_mi"), "Decoded", len(labels),
                          IRREGULAR_RATE, "float32", _source_id("decoded_mi", instance))
        chans = info.desc().append_child("channels")
        for label in labels:
            ch = chans.append_child("channel")
            ch.append_child_value("label", label)
        desc = info.desc().append_child("decoding")
        desc.append_child_value("paradigm", "motor-imagery")
        desc.append_child_value("classes", ",".join(self.classes))
        # L'échelle est une PROBABILITÉ de classifieur, pas un z comme le SSVEP : sans cette
        # indication, un seuil posé côté client n'a pas le même sens d'un mode à l'autre.
        desc.append_child_value("decision_scale", "proba")
        desc.append_child_value("threshold", str(prob_min))
        desc.append_child_value("min_votes", str(votes[0]))
        desc.append_child_value("vote_len", str(votes[1]))
        self.outlet = StreamOutlet(info)

    def push(self, intent_index, confidence, probas, lsl_ts=None):
        """`probas` : les probabilités dans le MÊME ordre que `classes`."""
        row = [float(intent_index), float(confidence)] + [float(p) for p in probas]
        block = np.ascontiguousarray(np.asarray(row).reshape(1, -1), dtype=np.float32)
        self.outlet.push_chunk(block, [float(lsl_ts) if lsl_ts else local_clock()])
```

- [ ] **Étape 7 : relancer l'autotest LSL**

Run: `python src/core/lsl_io.py`
Expected: `[lsl] VERDICT : OK`, et la ligne des voies `decoded_mi`.

- [ ] **Étape 8 : commit**

```bash
git add src/core/acquisition.py src/core/lsl_io.py
git commit -m "Add the unfiltered MI window and the decoded_mi stream"
```

---

## Task 5 : le mode MI

**Files:**
- Create: `src/core/modes/mi.py`
- Modify: `src/core/modes/external.py` (retirer `MI`)
- Modify: `src/core/modes/registry.py` (enregistrer `mi.SPEC` à la place de `external.MI`)

**Interfaces:**
- Consomme : `core.mi_decoder.MIDecoder` et `MIModel` (tâche 1) ; `core.mi_models.modeles_disponibles`,
  `charger`, `decrire` (tâche 2) ; `Param.choices_fn` (tâche 3) ;
  `acquisition.motor_window`, `mi_channel_labels`, `DecodedMIPublisher` (tâche 4).
- Produit : `mi.SPEC` (`ModeSpec` d'id `"mi"`, `stream="decoded_mi"`) et `mi.MIRuntime`.

**La place du mode dans le registre** : `external.MI` était une entrée « appli pygame » décrivant
un mode que le moteur ne savait pas faire. Elle est remplacée, au même rang, par le vrai mode.
L'ordre du registre est celui de la grille de la console **et** l'arbitre du repos partagé : ne pas
le changer.

- [ ] **Étape 1 : écrire le fichier avec son autotest, sans l'implémentation**

Créer `src/core/modes/mi.py` avec l'en-tête, le `SPEC`, et `_selftest` (donné aux étapes 3 et 4) ;
laisser `MIRuntime` vide pour voir l'autotest échouer.

- [ ] **Étape 2 : lancer pour voir échouer**

Run: `python src/core/modes/mi.py`
Expected: un échec (`AttributeError` ou verdict PROBLÈME) — l'important est que ça échoue avant
d'écrire le runtime.

- [ ] **Étape 3 : écrire l'en-tête, le runtime et le `SPEC`**

```python
"""Mode Motor Imagery : quelle imagerie motrice l'utilisateur produit. BCI **active**.

Le décodage est dans `core/mi_decoder.py` (CSP + LDA). Ici on décrit le MODE : ce qui se règle,
ce qui se publie, et ce qu'il faut avoir avant de pouvoir décoder — à savoir un modèle ENTRAÎNÉ.

C'est la différence de nature avec le SSVEP : la CCA n'apprend rien, le MI si. Sans modèle, ce
mode ne démarre pas, et il le DIT. Un mode qui démarrerait sans modèle ne lèverait aucune erreur,
publierait des probabilités et ne déciderait jamais rien.

⚠️ Un modèle est propre à UNE personne. Les probabilités d'un modèle entraîné sur quelqu'un
d'autre sont plausibles et fausses — le pire des deux mondes.

⚠️ Le moteur ne rend AUCUN stimulus, et le MI n'en a pas besoin : il est endogène. L'application
cliente n'a rien à afficher pour que le décodage fonctionne.

Autotest :
    python src/core/modes/mi.py
"""

import os as _os
import sys as _sys
import time as _time
from collections import Counter, deque

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (MI_MIN_VOTES, MI_PROB_MIN, MI_VOTE_LEN,  # noqa: E402
                         SSVEP_WARMUP_S, use_utf8_console)
import numpy as np  # noqa: E402

from core.lsl_io import DecodedMIPublisher, mi_channel_labels, stream_name  # noqa: E402
from core.mi_decoder import MIDecoder  # noqa: E402
from core.mi_models import charger, modeles_disponibles  # noqa: E402
from core.modes.contract import ModeSpec, Param, Rest, validate  # noqa: E402
from core.modes.runtime import ModeRuntime  # noqa: E402

MI_DECODE_HZ = 5.0     # cadence de décodage — la même que le SSVEP, pour que les deux se lisent pareil


class MIRuntime(ModeRuntime):
    """Charge un modèle, glisse une fenêtre de 2 s, vote, publie. Aucun plancher à mesurer.

    Pourquoi pas de plancher, alors que le SSVEP en mesure un : ici la référence est APPRISE
    pendant la calibration, elle n'est pas un niveau de bruit du jour. Le mode garde en revanche
    la CHAUFFE : l'offset DC de l'Unicorn dérive après ouverture de session, et le MI lit C3/C4,
    précisément les voies qui saturent.

    Pourquoi un vote glissant : une décision par fenêtre serait beaucoup trop instable pour
    piloter quoi que ce soit. On exige `min_votes` fenêtres d'accord sur les `vote_len`
    dernières — c'est le lissage qui existait déjà dans le pilote pygame, aux mêmes valeurs.
    """

    def __init__(self, spec, params, engine):
        super().__init__(spec, params, engine)
        self._out = None
        self._decoded = None
        self._last_log = 0.0
        self.model, raison = charger(params["model"])
        if self.model is None:
            # On lève ICI plutôt que de démarrer un mode muet. `validate` a déjà écarté le cas
            # « aucun modèle » ; il reste celui du fichier effacé entre la validation et le
            # démarrage, que seul le moteur peut voir.
            raise ValueError(raison)
        self.decoder = MIDecoder(self.model, prob_min=float(params["prob_min"]))
        self._votes = deque(maxlen=int(params["vote_len"]))

    @property
    def classes(self):
        return list(self.model.labels)

    def _open(self):
        # Le flux est créé tout de suite, comme pour le SSVEP : un client qui cherche le flux au
        # lancement et ne le trouve pas abandonne (`resolve_byprop` a un délai fini).
        self._out = DecodedMIPublisher(
            self.classes, prob_min=float(self.params["prob_min"]),
            votes=(int(self.params["min_votes"]), int(self.params["vote_len"])),
            instance=self.engine.instance)

    def _close(self):
        self._out = None

    def _reset_rest(self):
        self._votes.clear()
        self._decoded = None

    def period_s(self):
        return 1.0 / MI_DECODE_HZ

    def output(self):
        return self._decoded

    def _rest_step(self, engine, now):
        """Rien à mesurer : le repos de ce mode dure 0 s, seule la chauffe compte.

        On rend True dès que l'échéance est passée. `begin_rest` a posé `_rest_until = now` au
        premier pas de la phase, donc c'est vrai immédiatement — le mode passe à « running » au
        tick suivant, sans avoir rien collecté.
        """
        if now < self._rest_until:
            return False
        print(f"[mi] modèle « {_os.path.basename(self.params['model'])} » — décodage en cours "
              f"sur {stream_name('decoded_mi')} ({', '.join(self.classes)})")
        self.rest_report = {"kind": "mi", "model": _os.path.basename(self.params["model"]),
                            "classes": self.classes}
        return True

    def _run_step(self, engine, lsl_ts):
        window = engine.acq.motor_window(engine.recent)
        if window is None:
            return
        label, scores = self.decoder.classify(window)
        self._votes.append(label)

        # Le vote peut désigner None : « aucune fenêtre récente n'était assez sûre » est une
        # réponse, et c'est celle qu'il faut publier plutôt qu'un second choix inventé.
        gagnant, compte = Counter(self._votes).most_common(1)[0]
        if gagnant is None or compte < int(self.params["min_votes"]):
            retenu = None
        else:
            retenu = gagnant

        probas = [float(scores.get(c, 0.0)) for c in self.classes]
        if retenu is None:
            self._publish(-1, 0.0, probas, lsl_ts)
        else:
            self._publish(self.classes.index(retenu), float(scores[retenu]), probas, lsl_ts)

    def _publish(self, index, confidence, probas, lsl_ts):
        if self._out is not None:
            self._out.push(index, confidence, probas, lsl_ts)
        self._decoded = {
            "intent_index": int(index),
            "label": self.classes[index] if index >= 0 else "",
            "confidence": round(float(confidence), 3),
            "probas": {c: round(p, 3) for c, p in zip(self.classes, probas)},
            "threshold": float(self.params["prob_min"]),
        }
        self._log(index, probas)

    def _log(self, index, probas):
        """Trace la décision ~1×/s : pendant une séance on veut voir ce qui est décodé sans
        dépendre d'un troisième terminal branché au bon moment."""
        now = _time.perf_counter()
        if now - self._last_log < 1.0:
            return
        self._last_log = now
        detail = "  ".join(f"{c} p={p:.2f}" for c, p in zip(self.classes, probas))
        verdict = (f"— (vote non conclu, seuil {self.params['prob_min']:g})" if index < 0
                   else f"INTENTION {self.classes[index]}")
        print(f"[mi] {verdict:<34} {detail}")


def _channels(params):
    """Les voies dépendent des classes DU MODÈLE choisi, pas d'une liste figée.

    Un modèle entraîné à deux classes publierait quatre voies au lieu de cinq. Lire le modèle
    est le seul moyen de ne pas mentir dans les métadonnées ; si le modèle est illisible, on rend
    les classes par défaut plutôt que de lever — cette fonction est appelée par l'affichage.
    """
    chemin = params.get("model")
    modele = charger(chemin)[0] if chemin else None
    classes = list(modele.labels) if modele is not None else ["GAUCHE", "DROITE", "REPOS"]
    return mi_channel_labels(classes)


SPEC = ModeSpec(
    id="mi",
    label="Motor Imagery",
    family="actif",
    summary="Imagination d'un mouvement main gauche / main droite (CSP+LDA).",
    status="moteur",
    params=(
        Param(
            key="model",
            label="Modèle entraîné",
            kind="choice",
            choices_fn=modeles_disponibles,
            help="Le modèle produit par une calibration MI, propre à TA personne — celui de "
                 "quelqu'un d'autre donne des probabilités plausibles et fausses. Aucun modèle "
                 "dans la liste ? Lance une calibration : "
                 "`python src/research/mi_calibrate.py`.",
        ),
        Param(
            key="prob_min",
            label="Probabilité minimale",
            kind="float",
            default=MI_PROB_MIN,
            min=0.34, max=0.99,
            help="En dessous, la fenêtre ne vote pour personne. Monter ce seuil rend le mode "
                 "plus prudent : moins d'intentions émises, mais moins de fausses.",
        ),
        Param(
            key="vote_len",
            label="Fenêtres du vote",
            kind="int",
            default=MI_VOTE_LEN,
            min=1, max=15,
            help="Sur combien de fenêtres récentes on vote. Le MI est plus bruité que le SSVEP, "
                 "d'où un lissage un peu plus long. À 5 Hz, 5 fenêtres = 1 seconde.",
        ),
        Param(
            key="min_votes",
            label="Votes concordants",
            kind="int",
            default=MI_MIN_VOTES,
            min=1, max=15,
            help="Combien de ces fenêtres doivent être d'accord pour émettre une intention. "
                 "En demander plus retarde la décision et la rend plus sûre.",
        ),
    ),
    rest=Rest(
        warmup_s=SSVEP_WARMUP_S,
        duration_s=0.0,
        instruction="Le casque se stabilise — reste immobile.",
    ),
    calibration=None,   # la calibration est la moitié B ; le mode consomme un modèle déjà entraîné
    stream="decoded_mi",
    channels_fn=_channels,
    runtime_cls=MIRuntime,
)
```

⚠️ **`SSVEP_WARMUP_S` est réutilisé volontairement** : c'est la durée de stabilisation du casque,
pas une constante propre au SSVEP. Ne pas en créer une deuxième qui dériverait.

- [ ] **Étape 4 : écrire l'autotest**

À la fin de `src/core/modes/mi.py` :

```python
def _selftest():
    """Le mode de bout en bout, sur un modèle entraîné à la volée et du signal FABRIQUÉ.

    On ne juge PAS la justesse du décodage : de l'ERD synthétique n'a pas de sens
    physiologique ici. On vérifie le CONTRAT — que le mode refuse de démarrer sans modèle, que
    la chauffe précède le décodage, que le vote retarde bien la première intention, et qu'une
    décision publiée porte un index dans les bornes.
    """
    import shutil
    import tempfile

    from core.acquisition import UnicornAcquisition
    from core.mi_decoder import MI_LABELS, MIModel, synth_mi_trial

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _FauxPublieur:
        def __init__(self):
            self.lignes = []

        def push(self, index, confidence, probas, lsl_ts=None):
            self.lignes.append((index, confidence, list(probas)))

    class _FauxMoteur:
        def __init__(self, recent):
            self.acq = UnicornAcquisition(synthetic=True)
            self.instance = "selftest"
            self.recent = recent

    dossier = tempfile.mkdtemp(prefix="mi_mode_")
    try:
        # Un modèle jetable, entraîné sur de l'ERD synthétique.
        rng = np.random.default_rng(0)
        epochs, y = [], []
        for label in MI_LABELS:
            for _ in range(8):
                epochs.append(synth_mi_trial(label, rng=rng))
                y.append(label)
        chemin = _os.path.join(dossier, "mi_model.joblib")
        MIModel(fs=250.0).fit(np.asarray(epochs), np.asarray(y)).save(chemin)

        # 1. Sans modèle du tout, le mode REFUSE et dit comment en obtenir un.
        vide = _os.path.join(dossier, "aucun")
        _os.makedirs(vide, exist_ok=True)
        sans = SPEC.params[0].choices_fn
        object.__setattr__(SPEC.params[0], "choices_fn", lambda: modeles_disponibles(vide))
        _v, raison = validate(SPEC, {})
        chk(raison is not None and "aucun choix disponible" in raison
            and "calibration" in raison,
            f"sans modèle, le mode refuse en disant quoi faire ({raison})")

        # 2. Avec un modèle, les défauts sont valides et le plus récent est pris.
        object.__setattr__(SPEC.params[0], "choices_fn", lambda: modeles_disponibles(dossier))
        values, raison = validate(SPEC, {})
        chk(values is not None, f"avec un modèle, les défauts passent ({raison})")
        chk(values["model"] == chemin, f"et c'est le modèle trouvé qui est pris ({values['model']})")
        chk(_channels(values) == ["intent_index", "confidence",
                                  "p_GAUCHE", "p_DROITE", "p_REPOS"],
            f"les voies viennent des classes DU MODÈLE ({_channels(values)})")

        bruit = rng.normal(0.0, 8.0, (int(5.0 * 250), 8))
        moteur = _FauxMoteur(bruit)
        rt = MIRuntime(SPEC, values, moteur)
        rt._out = _FauxPublieur()
        rt._opened = True
        chk(rt.phase == "warmup", "le MI commence par une chauffe")

        # 3. Chauffe puis décodage, sans plancher à mesurer.
        rt.begin_rest(now=0.0, warmup_s=0.0, duration_s=0.0)
        rt.tick(moteur, lsl_ts=0.0, now=0.1)
        rt.tick(moteur, lsl_ts=0.2, now=0.2)
        chk(rt.phase == "running", f"un repos de durée nulle passe tout de suite ({rt.phase})")
        chk(rt.rest_report and rt.rest_report["kind"] == "mi",
            f"et laisse un compte-rendu nommant le modèle ({rt.rest_report})")

        # 4. Le vote retarde la première intention : c'est le but.
        rt._votes.clear()
        rt._out.lignes.clear()
        for i in range(int(values["vote_len"])):
            moteur.recent = rng.normal(0.0, 8.0, (int(5.0 * 250), 8))
            rt.tick(moteur, lsl_ts=1.0 + i, now=1.0 + i)
        chk(len(rt._out.lignes) == int(values["vote_len"]),
            f"une décision publiée par fenêtre ({len(rt._out.lignes)})")
        index, _conf, probas = rt._out.lignes[-1]
        chk(-1 <= index < len(MI_LABELS), f"index d'intention dans les bornes ({index})")
        chk(len(probas) == len(MI_LABELS), f"une probabilité par classe ({probas})")
        chk(abs(sum(probas) - 1.0) < 1e-3, f"et elles somment à 1 ({sum(probas):.3f})")

        premiere = rt._out.lignes[0][0]
        chk(premiere == -1,
            f"la toute première fenêtre ne peut pas conclure — le vote exige "
            f"{values['min_votes']} accords (index={premiere})")

        # 5. Le contrat du mode.
        chk(SPEC.rest.duration_s == 0.0 and SPEC.rest.warmup_s == SSVEP_WARMUP_S,
            f"chauffe obligatoire, aucun plancher ({SPEC.rest})")
        chk(SPEC.stream == "decoded_mi" and SPEC.status == "moteur",
            "le mode publie decoded_mi et tourne dans le moteur")
        chk(all(p.affecte_decodage for p in SPEC.params),
            "tous les réglages du MI affectent le décodage : en changer un refait le mode")
    finally:
        object.__setattr__(SPEC.params[0], "choices_fn", sans)
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[mi] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
```

- [ ] **Étape 5 : lancer l'autotest du mode**

Run: `python src/core/modes/mi.py`
Expected: `[mi] VERDICT : OK`.

- [ ] **Étape 6 : retirer l'entrée `MI` d'`external.py`**

Supprimer le bloc `MI = ModeSpec(id="mi", …)` de `src/core/modes/external.py` (lignes 21 à 30
environ, jusqu'au c-VEP exclu). Laisser `CVEP`, `P300` et `ERRP` intacts.

- [ ] **Étape 7 : enregistrer le vrai mode, au même rang**

Dans `src/core/modes/registry.py`, remplacer l'import et la ligne du tuple `MODES` :

```python
from core.modes import external, mi, neuro, raw, ssvep  # noqa: E402
```

```python
MODES = (
    raw.SPEC,           # le brut d'abord : c'est ce qui existe même sans décodage
    ssvep.SPEC,
    neuro.SPEC,
    mi.SPEC,            # le MI a rejoint le moteur : il n'est plus une entrée « appli pygame »
    external.CVEP,      # puis les modes de l'appli pygame, dans l'ordre où ils ont été écrits
    external.P300,
    external.ERRP,
)
```

- [ ] **Étape 8 : vérifier le registre, le mode et les smokes**

Run: `python src/core/modes/registry.py` puis `python src/core/modes/mi.py` puis les trois smokes.
Expected: cinq verdicts OK.

⚠️ Si `console/app.py --smoke` échoue sur la page du mode MI, c'est attendu et à corriger ici : la
console construit une page pour tout mode de statut `"moteur"`. Le mode MI est de famille
`"actif"`, donc `live_views.build("actif", …)` s'applique déjà — vérifier que le nombre de voies
variable ne casse pas l'affichage des barres.

- [ ] **Étape 9 : commit**

```bash
git add src/core/modes/mi.py src/core/modes/external.py src/core/modes/registry.py
git commit -m "Give Motor Imagery a real mode in the engine"
```

---

## Task 6 : le moteur publie le MI

**Files:**
- Modify: `src/core/server.py` (`keep`, et un smoke du mode MI)

**Interfaces:**
- Consomme : `mi.SPEC` (tâche 5), `core.config.MI_WINDOW_S`.
- Produit : `python src/core/server.py --mode mi` fonctionne ; `--smoke` couvre le mode.

- [ ] **Étape 1 : dimensionner le tampon pour le MI**

Dans `src/core/server.py`, ajouter `MI_WINDOW_S` à l'import de `core.config`, puis étendre le
calcul de `keep` :

```python
        self.keep = max(int(QUALITY_WINDOW_S * self.acq.fs),
                        int(NEURO_WINDOW_S * self.acq.fs),
                        int(MI_WINDOW_S * self.acq.fs),
                        self.acq.window_n) + self.acq.margin_n
```

⚠️ `MI_WINDOW_S` vaut 2,0 s, comme `NEURO_WINDOW_S` : le maximum ne change donc pas aujourd'hui.
On l'écrit quand même, parce que le tampon doit rester correct si l'une des deux constantes bouge.

- [ ] **Étape 2 : écrire le smoke du mode MI**

Ajouter dans `src/core/server.py`, à côté de `_smoke_ssvep`, une fonction `_smoke_mi()` appelée
par `--smoke` :

```python
def _smoke_mi():
    """Le mode MI de bout en bout, sans casque : un modèle entraîné à la volée, puis le flux.

    Le modèle est écrit dans `data/` sous un nom réservé, puis retiré : le mode découvre ses
    choix dans ce dossier, donc un modèle ailleurs ne serait pas proposable. Le `finally` est
    obligatoire — un `mi_model_smoke.joblib` oublié se retrouverait proposé à l'étudiant.
    """
    import threading

    import numpy as np

    from core.config import DATA_DIR
    from core.mi_decoder import MI_LABELS, MIModel, synth_mi_trial

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    chemin = os.path.join(DATA_DIR, "mi_model_smoke.joblib")
    os.makedirs(DATA_DIR, exist_ok=True)
    rng = np.random.default_rng(0)
    epochs, y = [], []
    for label in MI_LABELS:
        for _ in range(8):
            epochs.append(synth_mi_trial(label, rng=rng))
            y.append(label)
    MIModel(fs=250.0).fit(np.asarray(epochs), np.asarray(y)).save(chemin)

    instance = "smoke-mi"
    server = EngineServer(synthetic=True, modes=("mi",), params={"mi": {"model": chemin}},
                          instance=instance)
    thread = threading.Thread(target=server.run,
                             kwargs={"duration_s": 12.0, "baseline_s": 0.0, "warmup_s": 1.0},
                             daemon=True)
    try:
        thread.start()
        info = _resolve_own("decoded_mi", instance, timeout=15.0)
        chk(info is not None, "le flux decoded_mi est publié")
        if info is not None:
            chk(info.channel_count() == 2 + len(MI_LABELS),
                f"5 voies : intent_index, confidence, et une par classe ({info.channel_count()})")
            from pylsl import StreamInlet
            inlet = StreamInlet(info)
            inlet.open_stream()
            recus, indices = 0, set()
            fin = time.perf_counter() + 8.0
            while time.perf_counter() < fin:
                echantillon, _ts = inlet.pull_sample(timeout=1.0)
                if echantillon is None:
                    continue
                recus += 1
                indices.add(int(round(echantillon[0])))
                somme = sum(echantillon[2:])
                if abs(somme - 1.0) > 1e-2:
                    chk(False, f"les probabilités doivent sommer à 1 (reçu {somme:.3f})")
                    break
            chk(recus >= 10, f"des décisions arrivent en continu ({recus} en 8 s)")
            chk(all(-1 <= i < len(MI_LABELS) for i in indices),
                f"tous les indices sont dans les bornes ({sorted(indices)})")
    finally:
        server.stop()
        thread.join(timeout=5.0)
        if os.path.exists(chemin):
            os.remove(chemin)

    print(f"[smoke-mi] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok
```

- [ ] **Étape 3 : brancher `_smoke_mi` dans `--smoke`**

Repérer l'endroit où `_smoke_ssvep()` est appelé et son résultat combiné, et ajouter `_smoke_mi()`
de la même façon — le verdict global doit être faux si l'un des deux échoue.

- [ ] **Étape 4 : lancer le smoke du moteur**

Run: `python src/core/server.py --smoke`
Expected: tous les verdicts OK, dont `[smoke-mi] VERDICT : OK`.

- [ ] **Étape 5 : vérifier qu'aucun modèle de test n'est resté**

Run: `python -c "import sys; sys.path.insert(0,'src'); from core.mi_models import modeles_disponibles; print(modeles_disponibles())"`
Expected: `[]`. Si `mi_model_smoke.joblib` apparaît, le `finally` n'a pas fait son travail :
corriger avant de continuer.

- [ ] **Étape 6 : les deux autres smokes**

Run: `python src/console/app.py --smoke` puis `python src/research/app.py --smoke`
Expected: deux verdicts OK.

- [ ] **Étape 7 : commit**

```bash
git add src/core/server.py
git commit -m "Run and smoke-test the Motor Imagery mode end to end"
```

---

## Task 7 : le récepteur Unity et la documentation

**Files:**
- Create: `examples/unity/MiIntentReceiver.cs`
- Modify: `examples/unity/README.md`, `README.md`, `docs/SPEC.md`, `CLAUDE.md`

**Interfaces:**
- Consomme : le flux `EEG_API_Unicorn_decoded_mi` et ses métadonnées (tâche 4).
- Produit : un composant Unity exposant `IntentIndex`, `IntentLabel`, `Confidence`,
  `OnIntentChanged`.

⚠️ **Ce script est écrit contre l'API vérifiée mais ne sera pas compilé** : il n'y a pas d'Unity
sur ce poste, exactement comme pour `SsvepIntentReceiver.cs`. Le dire dans le README plutôt que de
le laisser croire testé.

- [ ] **Étape 1 : écrire le récepteur**

Créer `examples/unity/MiIntentReceiver.cs` :

```csharp
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using LSL;

/// <summary>
/// Receives the decoded Motor Imagery intent from EEG_API_Unicorn and exposes it to your scene.
///
/// Like its SSVEP sibling, this component only turns the network stream into a C# value. It
/// deliberately does NOT move or trigger anything: the API publishes an *intent* ("the user is
/// imagining a left-hand movement"), never an actuator command.
///
/// Two values mean different things and you should handle both:
///   IntentIndex == -1  the vote did not conclude -- not enough recent windows agreed, or the
///                      classifier stayed under its threshold. "I don't know."
///   IntentIndex == index of "REPOS"  the model decided the user is at rest. "Nothing is being
///                      imagined." Treating these two as the same is the most common mistake.
///
/// Motor Imagery needs a model trained on THAT person. Someone else's model produces plausible,
/// wrong probabilities -- which is worse than no output at all.
/// </summary>
public class MiIntentReceiver : MonoBehaviour
{
    [Tooltip("Stream name published by the engine. Must match src/core/lsl_io.py.")]
    public string streamName = "EEG_API_Unicorn_decoded_mi";

    [Tooltip("Engine instance to attach to (headset serial). Leave empty to take the first one found.")]
    public string instanceId = "";

    /// <summary>Index of the decoded class, or -1 when the vote did not conclude.</summary>
    public int IntentIndex { get; private set; } = -1;

    /// <summary>Name of that class ("GAUCHE", "DROITE", "REPOS"), empty when none.</summary>
    public string IntentLabel { get; private set; } = "";

    /// <summary>Probability of the winning class, on the scale announced in the metadata.</summary>
    public float Confidence { get; private set; }

    /// <summary>Class names, in the order the engine publishes their probabilities.</summary>
    public IReadOnlyList<string> Classes => classes;

    [System.Serializable] public class IntentChangedEvent : UnityEvent<string> { }
    public IntentChangedEvent OnIntentChanged = new IntentChangedEvent();

    private StreamInlet inlet;
    private float[] sample;
    private List<string> classes = new List<string>();

    private void Start()
    {
        StartCoroutine(Connect());
    }

    private IEnumerator Connect()
    {
        while (inlet == null)
        {
            // Short timeout: resolve_stream blocks the calling thread, so a long one would stall
            // the frame. Retrying once a second lets the scene run before the engine is started.
            StreamInfo[] found = LSL.resolve_stream("name", streamName, 1, 0.2);

            if (found.Length > 0)
            {
                StreamInfo chosen = Pick(found);
                if (chosen != null)
                {
                    // Count distinct source ids, not replies: a machine with several network
                    // interfaces answers once per interface, so one engine comes back two or
                    // three times and a naive count would warn on every normal setup.
                    var ids = new HashSet<string>();
                    foreach (StreamInfo info in found) ids.Add(info.source_id());
                    if (ids.Count > 1 && string.IsNullOrEmpty(instanceId))
                    {
                        Debug.LogWarning($"[EEG] {ids.Count} engines publish '{streamName}'. " +
                                         "Set instanceId to your own headset serial.");
                    }

                    inlet = new StreamInlet(chosen);
                    // Connect before the interesting data arrives. An inlet only connects on its
                    // first pull, and LSL never replays what was sent before you attached.
                    inlet.open_stream(5.0);

                    ReadMetadata();
                    Debug.Log($"[EEG] connected to {chosen.source_id()} — classes: " +
                              string.Join(", ", classes));
                    yield break;
                }
            }
            yield return new WaitForSeconds(1.0f);
        }
    }

    private StreamInfo Pick(StreamInfo[] found)
    {
        if (string.IsNullOrEmpty(instanceId)) return found[0];
        foreach (StreamInfo info in found)
        {
            if (info.source_id().Contains(instanceId)) return info;
        }
        Debug.LogWarning($"[EEG] no engine matching instance '{instanceId}' yet.");
        return null;
    }

    private void ReadMetadata()
    {
        StreamInfo info = inlet.info();
        sample = new float[info.channel_count()];

        // Read the class names from the metadata rather than hardcoding them: a model trained
        // on two classes publishes one channel fewer, and the scene should keep working.
        classes.Clear();
        string joined = info.desc().child("decoding").child_value("classes");
        if (!string.IsNullOrEmpty(joined))
        {
            classes.AddRange(joined.Split(','));
        }
        else
        {
            // Fall back to the channel labels, which carry the same names prefixed with "p_".
            XMLElement ch = info.desc().child("channels").child("channel");
            while (!ch.empty())
            {
                string label = ch.child_value("label");
                if (label.StartsWith("p_")) classes.Add(label.Substring(2));
                ch = ch.next_sibling();
            }
        }
    }

    private void Update()
    {
        if (inlet == null) return;

        // Drain everything queued since the last frame; keep only the most recent decision. The
        // engine decodes at ~5 Hz while Unity runs far faster, so most frames pull nothing at
        // all -- that is expected, not an error.
        bool got = false;
        while (inlet.pull_sample(sample, 0.0) != 0.0) got = true;
        if (!got) return;

        int index = Mathf.RoundToInt(sample[0]);
        Confidence = sample[1];
        string label = (index >= 0 && index < classes.Count) ? classes[index] : "";

        if (index != IntentIndex)
        {
            IntentIndex = index;
            IntentLabel = label;
            OnIntentChanged.Invoke(label);
        }
    }

    /// <summary>Per-class probabilities, in the order given by Classes.</summary>
    public IEnumerable<float> Probabilities()
    {
        for (int i = 0; i < classes.Count; i++) yield return sample[2 + i];
    }

    private void OnDestroy()
    {
        if (inlet != null)
        {
            inlet.close_stream();
            inlet = null;
        }
    }
}
```

- [ ] **Étape 2 : compléter `examples/unity/README.md`**

Ajouter une section, en anglais :

```markdown
## Motor Imagery

`MiIntentReceiver.cs` reads `EEG_API_Unicorn_decoded_mi`. Start the engine with:

```bash
python src/core/server.py --mode mi
```

Motor Imagery needs a **model trained on the person wearing the headset**. Without one the mode
refuses to start and says so. Train one with `python src/research/mi_calibrate.py`.

Two values are easy to confuse and mean different things:

| `IntentIndex` | Meaning |
|---|---|
| `-1` | the vote did not conclude — not enough recent windows agreed |
| index of `REPOS` | the model decided the user is at rest |

**What to expect.** Motor Imagery is the hardest paradigm in this project. Measured honestly on
one person, one session: **63% on left-vs-right** (chance 50%, p = 0.038). It is slow and
imprecise — good for a demonstration, not for fine control. Do not design a game that needs a
correct answer every second.

⚠️ Neither C# script in this folder has ever been compiled: there is no Unity install on the
development machine. They are written against the verified LSL API. Report anything that does not
build.
```

- [ ] **Étape 3 : mettre à jour le `README.md` principal**

Dans le tableau des flux, ajouter la ligne `decoded_mi`, et ajouter après la section SSVEP :

```markdown
### Motor Imagery

`--mode mi` publishes `EEG_API_Unicorn_decoded_mi`: `intent_index`, `confidence`, then one
probability per class (`GAUCHE`, `DROITE`, `REPOS`).

Unlike SSVEP, this mode **must be trained per person** — it loads a model produced by a
calibration and refuses to start without one. `intent_index = -1` means the sliding vote did not
conclude; the index of `REPOS` means the model decided the user is resting. They are not the same
thing.

Measured honestly (cross-validation grouped by trial, one person, one session): **63% on
left-vs-right**, chance 50%, p = 0.038. Slow and imprecise — a demonstrator, not a fine control.
```

- [ ] **Étape 4 : mettre à jour `docs/SPEC.md` §14**

Remplacer la ligne du chantier 3 par :

```markdown
   - **[fait 2026-07-29 — chantier 3, moitié A]** le Motor Imagery est publié par le moteur
     (`--mode mi` → flux `decoded_mi`) : le décodeur a déménagé dans `core/`, le modèle se choisit
     dans la console, et `examples/unity/MiIntentReceiver.cs` le consomme. Conception :
     [docs/superpowers/specs/2026-07-29-motor-imagery-moteur-design.md](superpowers/specs/2026-07-29-motor-imagery-moteur-design.md).
     - **[à faire — chantier 3, moitié B]** la calibration jouée par le moteur, la gestion des
       modèles, l'accuracy honnête et l'archivage des écrans pygame.
```

- [ ] **Étape 5 : mettre à jour `CLAUDE.md`**

Deux phrases deviennent fausses. Remplacer la ligne sur l'application pygame par :

```markdown
- L'**application pygame** (`src/research/app.py`, menu à 6 modes) reste le seul accès aux **3 modes
  que le moteur ne sait pas faire** : c-VEP, P300, ErrP. Le SSVEP, le neuro et le **Motor Imagery**
  sont publiés par le moteur et pilotés depuis la console. ⚠️ La *calibration* MI, elle, vit encore
  dans l'appli pygame (`mi_calibrate.py`) : c'est la moitié B du chantier 3.
```

Et dans les commandes utiles, ajouter :

```bash
python src/core/server.py --mode mi          # le Motor Imagery sur le réseau (exige un modèle)
```

- [ ] **Étape 6 : vérifier qu'il ne reste aucune affirmation périmée**

Run: `grep -rn "4 modes\|quatre modes\|MI, ErrP\|MI, c-VEP" README.md CLAUDE.md docs/SPEC.md`
Expected: aucune ligne qui compte encore le MI parmi les modes absents du moteur.

- [ ] **Étape 7 : les trois smokes, une dernière fois**

Run: les trois `--smoke`.
Expected: trois verdicts OK.

- [ ] **Étape 8 : commit**

```bash
git add examples/unity/ README.md CLAUDE.md docs/SPEC.md
git commit -m "Give Unity a Motor Imagery receiver, and say what it is worth"
```

---

## Après le plan : ce qui reste à vérifier sur le casque

Rien de cette moitié n'est vérifiable sans matériel au-delà des smokes. Trois choses pour la
séance, à ajouter à [docs/recette.md](../../recette.md) :

1. **Entraîner un modèle, puis le voir dans la console.** Lancer
   `python src/research/mi_calibrate.py`, puis ouvrir la console : le modèle doit apparaître dans
   la liste du réglage « Modèle entraîné », avec sa date.
2. **Décoder pour de vrai.** `--mode mi`, imagerie kinesthésique main gauche puis main droite, et
   regarder si `intent_index` suit. ⚠️ Ne rien conclure d'une poignée d'essais : le chiffre honnête
   est 63 % à deux classes, donc une erreur sur trois est **attendue**.
3. **Le piège online connu** : « GAUCHE activé en permanence au repos » est un symptôme de dérive
   de mode commun, déjà diagnostiqué le 2026-07-22. Le CAR est censé l'empêcher. S'il revient,
   resaliniser et vérifier le contact de C4 avant de soupçonner le code.

## Auto-relecture

**Couverture de la spec** (moitié A seulement) :

| Spec | Tâche |
|---|---|
| §3 déménagement de `mi_decoder.py` | 1 |
| §3 modèles hérités abandonnés, pas migrés | 1 (avertissement), 2 (filtrage par chargement) |
| §4 `core/modes/mi.py`, réglages, `Rest(15, 0)` | 5 |
| §4 « aucun modèle » refuse en disant pourquoi | 3 (message), 5 (test) |
| §5 contrat du flux `decoded_mi`, `-1` ≠ REPOS | 4 (publieur), 7 (documenté) |
| §5 « dire franchement ce que ça vaut » | 7 (README et README Unity) |
| §11 tests sans casque | 1-6 |
| §12 exemple Unity, jamais compilé | 7 |

**Non couvert ici, et c'est voulu** : §6 (calibration), §7 (page de calibration, liste des
modèles), §8 (accuracy honnête, enregistrements horodatés), §9 (archivage). Ce sont les tâches de
la **moitié B**, dont le plan sera écrit quand celle-ci sera posée.

**Cohérence des noms**, vérifiée d'une tâche à l'autre : `modeles_disponibles` / `charger` /
`decrire` (2 → 5) · `Param.choices_fn` et `choices_now()` (3 → 5) · `motor_window` (4 → 5) ·
`mi_channel_labels` et `DecodedMIPublisher.push(index, confidence, probas, lsl_ts)` (4 → 5) ·
`SPEC.stream == "decoded_mi"` (5 → 6 → 7).

**Trois points à surveiller à l'exécution**, signalés à leur tâche plutôt que résolus d'avance :

- Tâche 5, étape 8 : la console construit une page pour tout mode `"moteur"`. Le nombre de voies
  du MI dépend du modèle — vérifier que les barres de `live_views` l'encaissent.
- Tâche 5, autotest : il remplace `choices_fn` sur un `Param` **gelé**, via
  `object.__setattr__`. C'est laid et volontaire : c'est le seul moyen de tester le cas « aucun
  modèle » sans toucher à `data/`. Le `finally` doit remettre la valeur d'origine, sinon les tests
  suivants du même processus verraient un dossier temporaire effacé.
- Tâche 6 : le smoke écrit dans `data/`, le vrai dossier. Le `finally` qui retire le fichier n'est
  pas une précaution mais une obligation — un modèle de test oublié serait proposé à l'étudiant
  dans la console.
