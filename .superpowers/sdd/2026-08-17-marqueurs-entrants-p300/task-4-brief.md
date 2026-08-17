## Task 4: Le P300 déménage dans `core/`, et son modèle se ré-entraîne

**Files:**
- Move: `src/research/p300_decoder.py` → `src/core/p300_decoder.py`
- Create: `src/core/p300_models.py`
- Modify: `src/research/p300_calibrate.py` (import)
- Modify: `src/research/p300_analyze.py`, `src/research/app.py` (imports, s'ils citent `p300_decoder`)

**Interfaces:**
- Produces: `core.p300_decoder.P300Model`, `epoch_from_stream`, `synth_p300_epoch` ; `core.p300_models.charger(chemin) -> (modele, raison)`, `modeles_disponibles(dossier=DATA_DIR) -> tuple[str]`.

⚠️ **Le piège central de cette tâche.** `data/p300_model.joblib` se charge sous le nom de module **NU** `p300_decoder` — vérifié le 2026-08-17. Le déplacer dans `core/` le rend **illisible**, exactement comme les 4 modèles MI perdus. **Ne PAS écrire de passerelle de compatibilité** : les époques de calibration ont survécu (`data/p300_calib_*.npz`), donc on a une source de vérité meilleure que le pickle. On ré-entraîne.

- [ ] **Step 1: Déplacer le fichier avec `git mv`, pour que l'historique suive**

```bash
git mv src/research/p300_decoder.py src/core/p300_decoder.py
```

- [ ] **Step 2: NE PAS toucher au `sys.path.insert` — vérifié, il est déjà juste**

La ligne en tête du fichier est :

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

Elle **ne change pas**, et c'est contre-intuitif au point qu'il faut le dire : `src/research/` et
`src/core/` sont à la **même profondeur**, donc deux `dirname` mènent à `src` depuis l'un comme
depuis l'autre. `mi_decoder.py`, déjà dans `core/`, porte exactement la même ligne
([mi_decoder.py:36](../../../src/core/mi_decoder.py#L36)).

⚠️ Ne pas « corriger » cette ligne : la modifier casserait l'import de `core.config`. Le seul
contrôle à faire est de lancer l'autotest du module depuis son nouvel emplacement (étape 6).

- [ ] **Step 3: Recâbler les importeurs**

```bash
grep -rn "p300_decoder" src/ --include=*.py
```

Chaque `from p300_decoder import ...` ou `import p300_decoder` dans `src/research/` devient `from core.p300_decoder import ...`. `research` a le droit d'importer `core` ; l'inverse est interdit.

- [ ] **Step 4: Écrire `src/core/p300_models.py`, avec son autotest**

Jumeau de `mi_models.py`. Le refus des modèles hérités est le cœur : il doit être **explicite et nommé**, pas un échec de chargement obscur.

```python
"""Les modèles P300 sur le disque : lesquels existent, lequel se charge vraiment.

Jumeau de `mi_models.py`, et pour la même raison : un modèle est propre à UNE personne, et le
mode doit pouvoir dire « aucun choix disponible » plutôt que démarrer muet.

⚠️ **Les modèles antérieurs au 2026-08-17 sont refusés, et c'est une décision.** Ils ont été
enregistrés quand le décodeur vivait dans `src/research/`, donc leur pickle référence le module
NU `p300_decoder`, qui n'existe plus sous ce nom. On ne fabrique PAS de passerelle : les époques
de calibration ayant survécu (`data/p300_calib_*.npz`), un modèle se ré-entraîne depuis le disque
en quelques secondes. C'est ce qui manquait au MI, dont les époques avaient été écrasées — et ce
qui a coûté ses 4 modèles.

Autotest :
    python src/core/p300_models.py
"""
```

L'API à écrire, calquée sur `mi_models` :

```python
MOTIF = "p300_model*.joblib"


def charger(chemin):
    """(modèle, None) si le modèle se charge, (None, raison) sinon. Ne lève jamais.

    La `raison` est destinée à un étudiant : elle dit quoi FAIRE, pas seulement ce qui a raté.
    """


def modeles_disponibles(dossier=DATA_DIR):
    """Les chemins des modèles lisibles, du PLUS RÉCENT au plus ancien.

    Le plus récent d'abord, parce que c'est le défaut proposé : après une calibration, c'est
    celui qu'on vient de faire qu'on veut essayer.
    """


def decrire(chemin):
    """Une ligne lisible pour la liste de la console : date, nombre d'époques, AUC honnête."""
```

L'autotest doit prouver **trois** choses, dans un dossier temporaire (jamais `data/`) :

```python
    # 1. Un modèle hérité est refusé EN LE NOMMANT, pas par une exception obscure.
    chk(modele is None and "ré-entraîner" in raison and "calibration" in raison,
        f"un modèle hérité est refusé en disant quoi faire ({raison})")
    # 2. Le tri va du plus récent au plus ancien.
    chk(dispo == (recent, ancien), f"le plus récent d'abord ({dispo})")
    # 3. Un dossier sans modèle rend un tuple vide, sans lever — l'état normal d'un dépôt cloné.
    chk(modeles_disponibles(vide) == (), "un dossier vide rend (), sans lever")
```

- [ ] **Step 5: Ré-entraîner le modèle depuis les époques conservées**

Écrire un petit programme **jetable, dans le scratchpad** (il ne rejoint pas le dépôt) qui charge
`data/p300_calib_20260722_151134_n12.npz`, entraîne un `P300Model` et l'enregistre horodaté sous
`data/p300_model_<AAAAMMJJ-HHMMSS>.joblib`.

⚠️ **Ne pas écraser `data/p300_model.joblib`.** Il reste la trace de la séance du 22 juillet, et
c'est la seule preuve que le décodage a marché au casque avant ce chantier.

Coller dans le rapport de tâche : le nombre d'époques, la répartition cible/non-cible, et l'**AUC
en validation croisée par groupe** rendue par `P300Model.fit`. Si l'AUC descend nettement sous
celle relevée en juillet, **le dire** plutôt que de continuer : ça signifierait que le
ré-entraînement n'a pas reproduit les conditions d'origine.

- [ ] **Step 6: Lancer tous les autotests touchés**

```bash
python src/core/p300_decoder.py     # le décodeur, depuis son nouvel emplacement
python src/core/p300_models.py      # le refus des modèles hérités, le tri
python src/research/app.py --smoke  # l'appli pygame ne doit pas être cassée par le déménagement
python src/core/server.py --smoke   # la frontière core/ : aucun import interdit
```

Expected: `VERDICT : OK` partout, et le smoke du serveur ne signale **aucun** import de `research` depuis `core`.

- [ ] **Step 7: Commit**

```bash
git add -A src/core/p300_decoder.py src/core/p300_models.py src/research/
git commit -m "Move the P300 decoder into the engine, and retrain rather than shim"
```

---

