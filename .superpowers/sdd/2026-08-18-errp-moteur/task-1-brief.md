## Task 1: Le décodeur déménage, et son modèle se ré-entraîne

**Files:**
- Déplacer : `src/research/errp_decoder.py` → `src/core/errp_decoder.py`
- Créer : `src/core/errp_models.py`
- Modifier : `src/research/errp_calibrate.py`, `src/research/app.py` (imports)

**Interfaces:**
- Produces : `core.errp_decoder.ErrPModel`, `rates`, `pick_threshold`, `synth_errp_epoch` · `core.errp_models.charger(chemin) -> (modele, raison)`, `modeles_disponibles(dossier=DATA_DIR) -> list[str]`, `decrire(chemin) -> list[str]`

⚠️ **Le piège central, troisième occurrence.** `data/errp_model.joblib` **ne se charge déjà plus** : le décodeur P300 ayant déménagé hier, le pickle de l'ErrP référence `p300_decoder` nu, qui n'existe plus. Ce projet a perdu 4 modèles MI comme ça. **Aucune passerelle de compatibilité** — les époques ont survécu (`data/errp_calib_last.npz`, plus deux horodatés), on ré-entraîne.

- [ ] **Step 1: Déplacer avec `git mv`, pour que l'historique suive**

```bash
git mv src/research/errp_decoder.py src/core/errp_decoder.py
```

- [ ] **Step 2: NE PAS toucher au `sys.path.insert` — vérifié, il est déjà juste**

La ligne en tête du fichier est :

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

Elle **ne change pas**, et c'est contre-intuitif au point qu'il faut le dire : `src/research/` et `src/core/` sont à la **même profondeur**, donc deux `dirname` mènent à `src` depuis l'un comme depuis l'autre. `mi_decoder.py` et `p300_decoder.py`, déjà dans `core/`, portent la même ligne. La modifier casserait l'import de `core.config`.

- [ ] **Step 3: Recâbler les importeurs**

```bash
grep -rn "errp_decoder" src/ --include=*.py
```

Chaque `from research.errp_decoder import …` (ou import nu) devient `from core.errp_decoder import …`. `research` a le droit d'importer `core` ; l'inverse est interdit.

- [ ] **Step 4: Écrire `src/core/errp_models.py`, calqué sur `src/core/p300_models.py`**

Lis `p300_models.py` en entier : c'est ton modèle de forme, de ton et de structure. Les différences :

```python
MOTIF = "errp_model*.joblib"
_MODULE_ATTENDU = "core.errp_decoder"
```

et le message de refus d'un modèle hérité doit nommer la source à ré-entraîner :

```python
        return None, (f"modèle hérité (module {module!r}, attendu {_MODULE_ATTENDU!r}), "
                      f"illisible depuis le déménagement du décodeur. Ré-entraîne-le depuis "
                      f"les époques conservées : data/errp_calib_*.npz")
```

⚠️ Le message pour un chemin vide doit dire la VÉRITÉ sur l'endroit où l'on calibre — **la console n'a pas de page de calibration ErrP**, c'est l'appli pygame :

```python
        return None, ("aucun modèle désigné — lance `python src/research/app.py`, mode ErrP, "
                      "et calibre pour en produire un")
```

- [ ] **Step 5: Écrire l'autotest de `errp_models.py`, avec LE test qui protège la décision**

⚠️ **Ce test est le seul qui protège la décision « ré-entraîner plutôt que rafistoler ».** La leçon vient de la revue du P300 : un faux modèle ordinaire porte le module `"__main__"`, **jamais** `"errp_decoder"`, donc la mutation `endswith("errp_decoder")` — la passerelle qu'un contributeur écrira un jour — passerait inaperçue.

Il faut donc **enregistrer un faux module nommé `errp_decoder` dans `sys.modules`, et l'y laisser pendant le `joblib.dump` ET pendant le chargement** — `pickle` résout la classe via `obj.__module__` au dump, pas seulement à la lecture.

```python
    import types
    faux = types.ModuleType("errp_decoder")

    class _ModeleHerite:
        """Imite un modèle enregistré AVANT le déménagement : son module est le nom NU."""
        threshold_ = 0.0
        def score(self, epochs):
            return [0.0] * len(epochs)
        def is_error(self, epoch):
            return False

    _ModeleHerite.__module__ = "errp_decoder"
    faux._ModeleHerite = _ModeleHerite
    _sys.modules["errp_decoder"] = faux
    try:
        chemin_herite = _os.path.join(dossier, "errp_model_herite.joblib")
        joblib.dump(_ModeleHerite(), chemin_herite)
        modele, raison = charger(chemin_herite)
        chk(modele is None, "un modèle hérité est REFUSÉ")
        chk(raison is not None and "errp_decoder" in raison and "ré-entraîn" in raison,
            f"et la raison nomme le module fautif ET la source à ré-entraîner ({raison})")
        chk(chemin_herite not in modeles_disponibles(dossier),
            "il n'apparaît pas non plus dans la liste des modèles utilisables")
    finally:
        _sys.modules.pop("errp_decoder", None)
```

- [ ] **Step 6: Obtenir la preuve ROUGE de ce test**

Remplace temporairement la comparaison exacte du module par `module.endswith("errp_decoder")` — c'est-à-dire la passerelle de compatibilité que ce chantier refuse d'écrire.

Run: `python src/core/errp_models.py`
Expected: **ÉCHEC** sur « un modèle hérité est REFUSÉ », et code de sortie **1**.

Remets la comparaison exacte, relance, colle le VERT. **Colle les deux sorties dans le rapport.** Sans ce rouge, l'assertion pourrait passer pour de mauvaises raisons — c'est arrivé au P300.

- [ ] **Step 7: Ré-entraîner le modèle depuis les époques conservées**

Programme **jetable**, à écrire dans le scratchpad (`C:\Users\Lab_IA\AppData\Local\Temp\claude\c--Users-Lab-IA-Documents-Projets-Dev-EEG-API-Unicorn\b4139deb-bcbe-44b9-8ad9-6c2f9e54593a\scratchpad`), **pas dans le dépôt** :

```python
import sys, numpy as np, time
sys.path.insert(0, "src")
from core.errp_decoder import ErrPModel

d = np.load("data/errp_calib_last.npz", allow_pickle=True)
m = ErrPModel(fs=float(d["fs"]), pre_s=float(d["pre_s"]), post_s=float(d["post_s"]))
m.fit(d["epochs"], d["labels"], groups=d["groups"])
print("AUC", m.cv_auc_, "| p", m.perm_p_, "| nfilter", m.nfilter_)
print("seuil", m.threshold_, "| metrics", m.metrics_)
m.save(f"data/errp_model_{time.strftime('%Y%m%d-%H%M%S')}.joblib")
```

⚠️ **NE PAS écraser `data/errp_model.joblib`.** C'est la trace de la séance du 24 juillet. Le nouveau modèle s'écrit **horodaté à côté**, comme pour le P300.

**Colle la sortie brute dans le rapport.** Attendu, aux arrondis près : AUC ≈ 0,776, p ≈ 0,0099, nfilter 4, seuil ≈ 0,510, TPR ≈ 0,500 / TNR ≈ 0,855. ⚠️ **Si l'AUC s'écarte nettement, DIS-LE** plutôt que de continuer : ça voudrait dire que le ré-entraînement n'a pas reproduit les conditions, et ça change la suite du chantier.

- [ ] **Step 8: Lancer, un par un**

```bash
python src/core/errp_decoder.py      # le décodeur depuis son nouvel emplacement
python src/core/errp_models.py       # le refus des hérités, le tri
python src/core/server.py --smoke    # la frontière core/ : aucun import interdit
python src/research/app.py --smoke   # l'appli pygame n'est pas cassée par le déménagement
```

Attendu : `VERDICT : OK` partout, et `smoke-frontiere` à 0 violation.

- [ ] **Step 9: Commit**

```bash
git add -A src/core/errp_decoder.py src/core/errp_models.py src/research/
git commit -m "Move the ErrP decoder into the engine, and retrain rather than shim"
```

---

