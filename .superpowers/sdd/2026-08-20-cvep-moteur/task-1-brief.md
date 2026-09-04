## Task 1 : déménager le décodage dans `core/`, et PROUVER que le modèle survit

**Files:**
- Create: `src/core/cvep_code.py`, `src/core/cvep_decoder.py` (déplacés depuis `src/research/`)
- Delete: `src/research/cvep_code.py`, `src/research/cvep_decoder.py`
- Modify: les importeurs — `src/research/app.py`, `src/research/cvep_calibrate.py`,
  `src/research/cvep_analyze.py`, `src/research/cvep_rcca.py`, `README.md`,
  `src/research/__init__.py`

**Interfaces:**
- Produces: `core.cvep_code.build_targets(commands=None, n_bits=CVEP_BITS, taps=CVEP_TAPS)
  -> (plan, code)` où `plan` est une liste de dicts portant `name`, `angle`, `jx`, `jy`, `lag`,
  `code` ; `core.cvep_code.is_on(frame, target_code) -> bool` ;
  `core.cvep_decoder.CVEPModel.load(path) -> CVEPModel` ;
  `CVEPModel.scores(window, phase, lags, n_cycles=None) -> {lag: corrélation}` ;
  `CVEPDecoder(model, plan, corr_min, margin, n_cycles).classify(window, phase)
  -> (commande|None, {nom: corrélation})`.

- [ ] **Étape 1 : écrire le test qui échoue** — dans `src/core/cvep_decoder.py`, au `_selftest()`.

⚠️ **C'est LE test de cette tâche.** Le P300 et l'ErrP ont perdu leurs modèles au déménagement
(pickle `joblib` référençant un module disparu) et il a fallu ré-entraîner deux fois. Le c-VEP
écrit du `np.savez` de tableaux purs, donc il devrait survivre — **ce test transforme ce « devrait »
en fait mesuré**.

```python
    # Le modèle SURVIT au déménagement — la question qui a coûté deux ré-entraînements.
    # On écrit un modèle, on le relit, et on vérifie que les tableaux sont identiques BIT
    # POUR BIT. Pas de pickle ici (np.savez de tableaux purs), donc aucun nom de module
    # n'est gravé dans le fichier : c'est ce qui rend `core.cvep_decoder` capable de relire
    # ce que `research.cvep_decoder` avait écrit.
    import tempfile as _tf, shutil as _sh
    tmp = _tf.mkdtemp(prefix="cvep_selftest_")
    try:
        m = CVEPModel(fs=250.0, refresh=60.0, code_len=63, band=CVEP_BAND, channels=[4, 5, 6, 7])
        m.w = np.arange(4, dtype=float) * 1.5
        m.template = np.arange(63, dtype=float) / 7.0
        m.cv_ = 0.87
        chemin = m.save(_os.path.join(tmp, "cvep_model.npz"), n_targets=6)
        relu = CVEPModel.load(chemin)
        chk(np.array_equal(relu.w, m.w) and np.array_equal(relu.template, m.template),
            "un modèle écrit puis relu rend les MÊMES tableaux, bit pour bit")
        chk(relu.channels == [4, 5, 6, 7] and relu.code_len == 63 and relu.n_targets == 6,
            f"...et ses métadonnées ({relu.channels}, {relu.code_len}, {relu.n_targets})")
        chk("cvep_decoder" not in open(chemin, "rb").read(2048).decode("latin-1"),
            "le fichier ne contient AUCUN nom de module — c'est ce qui le rend déplaçable")
    finally:
        _sh.rmtree(tmp, ignore_errors=True)
```

- [ ] **Étape 2 : lancer le test, vérifier qu'il échoue**

Lancer : `python src/core/cvep_decoder.py`
Attendu : `ModuleNotFoundError` — le fichier n'existe pas encore dans `core/`.

- [ ] **Étape 3 : déplacer les deux fichiers**

```bash
git mv src/research/cvep_code.py src/core/cvep_code.py
git mv src/research/cvep_decoder.py src/core/cvep_decoder.py
```

Dans les deux fichiers, l'insertion de `sys.path` doit remonter d'un niveau de moins (ils sont
maintenant dans `core/`, plus dans `research/`). Le motif à recopier est celui de
`src/core/errp_decoder.py`.

- [ ] **Étape 4 : recâbler tous les importeurs**

```bash
grep -rn "research.cvep_code\|research.cvep_decoder\|from research import cvep" src/ README.md
```

Chaque occurrence devient `core.cvep_code` / `core.cvep_decoder`. Mettre à jour la liste des
décodeurs dans `src/research/__init__.py` (« les décodeurs des modes ») et la ligne d'autotest de
`README.md`.

- [ ] **Étape 5 : lancer les tests**

```bash
python src/core/cvep_code.py
python src/core/cvep_decoder.py
python src/research/app.py --smoke
python src/core/server.py --smoke
```
Attendu : les quatre verts, sortie 0.

- [ ] **Étape 6 : vérifier le VRAI modèle, celui du 21 juillet**

```bash
python -c "import sys; sys.path.insert(0,'src'); from core.cvep_decoder import CVEPModel; m = CVEPModel.load('data/cvep_model.npz'); print(f'n_targets={m.n_targets} refresh={m.refresh} code_len={m.code_len} cv={m.cv_}')"
```
Attendu : il se charge, `n_targets=6`. **Ne pas modifier `data/`.** Coller la sortie dans le rapport.

- [ ] **Étape 7 : commit**

```bash
git add -A src/core/cvep_code.py src/core/cvep_decoder.py src/research/ README.md
git commit -m "Move the c-VEP decoder into the engine, and prove the model survives"
```

---

