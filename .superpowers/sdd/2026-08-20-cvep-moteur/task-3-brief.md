## Task 3 : deux décodeurs, un seul stimulus

**Files:**
- Create: `src/core/cvep_rcca.py` (moitié décodeur de l'ancien), `src/core/cvep_models.py`
- Modify: `src/research/cvep_rcca.py` (réduit aux codes Gold), `requirements.txt`,
  `src/core/config.py` (seuils rCCA)

**Interfaces:**
- Produces: `core.cvep_models.modeles_disponibles() -> tuple[str]` (les fichiers, du plus récent au
  plus ancien) ; `core.cvep_models.charger(chemin) -> (modele|None, raison|None)` ;
  `core.cvep_rcca.RCCAModel(codes, fs, refresh, band, …)` avec `.scores(window, phase, n_cycles)`.

- [ ] **Étape 1 : écrire le test du champ `decoder`**

```python
    # Le fichier de modèle DÉCLARE son décodeur. Inférer d'après les clés présentes serait
    # deviner ; un champ explicite se lit et se teste. Un fichier SANS ce champ est un eCCA
    # d'avant ce chantier — c'était le seul décodeur qui existait sous ce nom de fichier.
    chk(charger(chemin_ecca)[0].decoder == "eCCA",
        "un modèle eCCA se déclare comme tel")
    chk(charger(chemin_rcca)[0].decoder == "rCCA",
        "un modèle rCCA aussi, et le moteur choisit le décodeur d'après CE champ")
    chk(charger(chemin_herite)[0].decoder == "eCCA",
        "un modèle SANS le champ est un eCCA hérité, pas une erreur")
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

Lancer : `python src/core/cvep_models.py` → `ModuleNotFoundError`.

- [ ] **Étape 3 : couper `cvep_rcca.py` en deux**

`RCCAModel` et `RCCADecoder` partent dans `src/core/cvep_rcca.py`. `make_distinct_codes` et
`build_targets_rcca` **restent** dans `src/research/cvep_rcca.py`.

⚠️ Après ce découpage, les seuls appelants des codes Gold vivront dans `archive/` (tâche 6). C'est
voulu, et il faut l'écrire dans la docstring : **une hypothèse réfutée se garde lisible, pas
branchée.**

- [ ] **Étape 4 : déclarer `pyntbci`**

Ajouter à `requirements.txt`, avec la raison en commentaire :

```
# Décodeur c-VEP par reconvolution (rCCA). Le MOTEUR en dépend : RCCAModel ne sérialise pas
# l'objet pyntbci, il stocke les époques et ré-ajuste au chargement.
pyntbci
```

Vérifier la version installée et l'épingler si `pip freeze` en donne une :
`python -c "import pyntbci; print(pyntbci.__version__)"`.

- [ ] **Étape 5 : poser les seuils rCCA**

`CVEP_RCCA_CORR_MIN = 0.0` et `CVEP_RCCA_MARGIN = 0.0` sont des placeholders assumés (« ne pas se
fier au seuil »). **Voici comment les poser**, et il faut le faire par la mesure, pas au jugé :

1. Rejouer `data/cvep_calib_last.npz` (époques réelles du 2026-07-21, 6 cibles, stimulus **décalé**)
   à travers `RCCAModel.fit(epochs, labels, compute_cv=True)`.
2. Récupérer les scores **hors-pli** produits par sa validation croisée leave-one-out : pour chaque
   essai, la corrélation du gagnant et celle du second.
3. `corr_min` = le quantile qui garde **95 % des essais corrects** de la calibration ; `margin` =
   le quantile 95 % des écarts gagnant-second sur ces mêmes essais corrects. Le c-VEP n'a pas de
   coût asymétrique comme l'ErrP : on cale sur « ne pas rater ce qui est bon ».
4. ⚠️ **Écrire le chiffre ET sa provenance** dans le commentaire de `config.py` (fichier source,
   date, nombre d'essais). Un seuil sans provenance est un seuil que personne n'osera changer.
5. ⚠️ **Ces seuils sont mesurés sur UNE personne et UNE séance.** Le dire là où ils sont écrits —
   c'est la même réserve que pour l'eCCA, et elle vaut jusqu'à ce qu'une seconde personne soit
   mesurée.

⚠️ **Ne pas écrire dans `data/`** : lire ces fichiers, jamais les modifier.

- [ ] **Étape 6 : lancer**

```bash
python src/core/cvep_models.py
python src/core/cvep_rcca.py
python src/core/server.py --smoke
```
Attendu : verts. Le smoke de frontière doit rester vert — `core/cvep_rcca.py` n'importe rien de
`research/`.

- [ ] **Étape 7 : commit**

```bash
git add src/core/cvep_rcca.py src/core/cvep_models.py src/research/cvep_rcca.py requirements.txt src/core/config.py
git commit -m "Split rCCA from the Gold codes it was wrongly judged with"
```

---

