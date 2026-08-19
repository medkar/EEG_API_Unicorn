# Task 1 — le décodeur ErrP déménage, et son modèle se ré-entraîne — rapport d'implémentation

Statut : **DONE**
Commit : `b35872a` — "Move the ErrP decoder into the engine, and retrain rather than shim"
Base : `02ac710` (HEAD de `main` avant cette tâche)

## Ce qui a été fait

1. **`git mv src/research/errp_decoder.py src/core/errp_decoder.py`** — historique suivi (`git log
   --follow` le confirme). Le `sys.path.insert` en tête **n'a pas bougé**, conformément au brief.
   **Une seule ligne** du fichier a changé : son propre indice d'exécution en docstring
   (`python src/research/errp_decoder.py` -> `python src/core/errp_decoder.py`), par symétrie exacte
   avec ce que le commit `2ebf022` (déménagement du P300, la veille) avait fait sur la même ligne de
   `p300_decoder.py`. Rien d'autre : pas d'import `research.*` caché à démêler ici (contrairement au
   P300 qui avait dû remplacer un `import research.itr` dans son `_demo()` — vérifié, l'ErrP n'a pas
   cet import).

2. **Recâblage des importeurs** (`grep -rn "errp_decoder" src/`) : les 3 imports nus
   (`research/app.py` ×2, `research/errp_calibrate.py` ×1) deviennent `from core.errp_decoder import
   ...`. `research.errp_calibrate` reste dans `research/` (c'est un protocole de calibration
   pygame) — seul SON import interne d'`errp_decoder` bouge, pas les imports qui pointent vers
   `errp_calibrate` lui-même.

3. **`src/core/errp_models.py`** (nouveau fichier, 344 lignes), calqué sur `p300_models.py` : `MOTIF
   = "errp_model*.joblib"`, `_MODULE_ATTENDU = "core.errp_decoder"`, `charger`/`modeles_disponibles`/
   `decrire` de forme identique. Écarts assumés par rapport au jumeau, documentés en commentaire dans
   le fichier :
   - `charger` vérifie `hasattr(modele, "score") and hasattr(modele, "is_error")` (l'interface
     réelle d'`ErrPModel`) plutôt que `select`/`scores` (P300, sélection discrète — l'ErrP est un
     détecteur binaire, pas de sélection).
   - `decrire` garde la clé `n_epoques` pour la parité de forme avec `p300_models.decrire`, mais elle
     reste toujours `None` : `ErrPModel` (contrairement à `P300Model`) ne pose pas d'attribut
     `n_epoques_`. Je n'ai pas touché `errp_decoder.py` pour l'ajouter — hors périmètre de cette
     tâche (le fichier est listé « Déplacer », pas « Modifier »).

## Deux constats du brief mesurés faux, corrigés avec preuve — pas appliqués à moitié

**1. Le snippet du test critique (Step 5) ne s'exécute pas tel quel.** Le brief définit
`_ModeleHerite` **à l'intérieur de `_selftest()`**. Testé isolément avant d'écrire le fichier réel :

```
_pickle.PicklingError: Can't pickle <class 'errp_decoder._selftest.<locals>._ModeleHerite'>:
it's not found as errp_decoder._selftest.<locals>._ModeleHerite
```

`pickle` résout une classe par `__qualname__` ; une classe locale à une fonction porte `<locals>`
dans son qualname, et `pickle._getattribute` lève dessus **avant même** de consulter `sys.modules`
— donc forcer `__module__ = "errp_decoder"` ne suffit pas si la classe elle-même est imbriquée.
C'est très exactement ce que le commentaire du jumeau P300 dit de `_ModeleEtranger` (« pickle/joblib
ne sait pas sérialiser une classe locale à une fonction ») — mais le brief n'avait pas appliqué sa
propre leçon à `_ModeleHerite`. Corrigé en sortant `_ModeleHerite` (et `_ModeleEtranger`) au niveau
du module, comme dans `p300_models.py`. Reproduit avec un script isolé AVANT et APRÈS le correctif
(les deux sorties sont dans l'historique de la session). Sémantique du test intacte : même
`sys.modules["errp_decoder"]` injecté pendant le dump ET le chargement, même refus vérifié.

**2. Le message de refus donné (Step 4) échoue son propre test (Step 5).** Le brief écrit le message
avec « **R**é-entraîne-le depuis... » (R majuscule, début de phrase) et le test vérifie
`"ré-entraîn" in raison` (r minuscule). Vérifié à l'interpréteur :

```python
>>> "re-entrain" in "... Re-entraine-le depuis les epoques ..."
False
```

(cas testé sans accents pour isoler la casse — le problème est bien la casse de la lettre initiale,
identique avec ou sans accent). Corrigé en reformulant la fin de phrase sans capitaliser le verbe :
« ... illisible depuis le déménagement du décodeur — **à ré-entraîner** depuis les époques
conservées : ... » — même sens, satisfait le test tel qu'écrit dans le brief, et se rapproche
d'ailleurs davantage du tour du jumeau P300 (« abandonné délibérément — ré-entraîner depuis les
époques... »).

Aucun autre écart : le reste du fichier (structure, `MOTIF`, `_MODULE_ATTENDU`, message du chemin
vide, ordre des vérifications) suit le brief et `p300_models.py` à la lettre.

## Preuve ROUGE-PUIS-VERT (Step 6) — refus des modèles hérités

Mutation appliquée : `if module != _MODULE_ATTENDU:` -> `if not module.endswith("errp_decoder"):`
(la passerelle que ce chantier refuse d'écrire).

**ROUGE** (`python src/core/errp_models.py`, extrait — tout le reste du fichier restait à `OK`,
y compris le test générique `_ModeleEtranger` qui NE détecte PAS cette mutation, exactement le
défaut que ce test existe pour attraper) :

```
  OK   un modèle hérité est refusé en disant quoi faire (modèle hérité (module '__main__', ...))
  OK   et il n'apparaît donc pas non plus dans la liste
  ÉCHEC un modèle dont le pickle porte le module NU 'errp_decoder' est refusé, et la raison NOMME ce module — c'est ce qui interdit la passerelle endswith() (None)
  ÉCHEC ...en disant quoi faire à la place (None)
  ÉCHEC ...et il ne se glisse pas non plus dans la liste ([..., 'errp_model_herite.joblib', 'errp_model.joblib'])
[errp-models] VERDICT : PROBLÈME
EXITCODE=1
```

Comparaison exacte restaurée, aucune trace de mutation restante (`grep -n "endswith" src/core/
errp_models.py` ne montre plus que des docstrings/messages, pas de code). **VERT** :

```
  OK   un modèle hérité est refusé en disant quoi faire (modèle hérité (module '__main__', ...))
  OK   et il n'apparaît donc pas non plus dans la liste
  OK   un modèle dont le pickle porte le module NU 'errp_decoder' est refusé, et la raison NOMME ce module — c'est ce qui interdit la passerelle endswith() (modèle hérité (module 'errp_decoder', attendu 'core.errp_decoder'), illisible depuis le déménagement du décodeur — à ré-entraîner depuis les époques conservées : data/errp_calib_*.npz)
  OK   ...en disant quoi faire à la place (...)
  OK   ...et il ne se glisse pas non plus dans la liste (['...\\errp_model.joblib'])
[errp-models] VERDICT : OK
EXITCODE=0
```

## Ré-entraînement (Step 7) — sortie brute

Script jetable (scratchpad, pas dans le dépôt), lancé depuis la racine du dépôt :

```
AUC 0.7762973352033661 | p 0.009900990099009901 | nfilter 4
seuil 0.5102908586732289 | metrics {'tpr': 0.5, 'tnr': 0.855072463768116, 'bal_acc': 0.677536231884058}
```

Comparaison à l'attendu (brief / `progress.md` / plan) :

| | attendu | obtenu |
|---|---|---|
| AUC | ≈ 0,776 | **0,7763** |
| p (100 permutations) | ≈ 0,0099 | **0,0099** (= 1/101, aucun tirage nul ne bat l'observé) |
| nfilter retenu | 4 | **4** |
| seuil | ≈ 0,510 | **0,5103** |
| TPR | ≈ 0,500 | **0,500** |
| TNR | ≈ 0,855 | **0,855** |

**Aucun écart** — reproduction quasi exacte, aux arrondis du brief près. Le modèle est sauvé
horodaté : `data/errp_model_20260818-153051.joblib`. Vérifié avant/après que `data/errp_model.joblib`
(35115 octets, 24 juillet 11:46:08) et `data/errp_calib_last.npz` sont restés **strictement
inchangés** (même taille, même date). `data/` est intégralement ignoré par git
(`.gitignore` ligne 4) — le nouveau modèle horodaté n'apparaît donc pas dans `git status`, comme
pour le P300.

## Comptage des assertions (méthode excluant `def chk(cond, msg):`)

`errp_models.py` est un fichier neuf : **avant cette tâche, 0** (le fichier n'existait pas).

**Après** : `grep -n "chk(" src/core/errp_models.py` rend 19 lignes ; moins 1 pour la ligne
`def chk(cond, msg):` (ligne 199) = **18 sites d'assertion** dans le code source.

Détail utile (écart entre sites statiques et exécutions, pour éviter l'erreur d'unité signalée) :
2 de ces 18 sites vivent dans des boucles `for entree in (None, "", 0):` et s'exécutent donc 3 fois
chacun -> **22 lignes `OK`/`ÉCHEC` à l'exécution** (16×1 + 2×3 = 22), confirmé en comptant les
lignes imprimées par le run VERT ci-dessus. Les deux chiffres (18 statique, 22 à l'exécution) sont
corrects, pour deux questions différentes ; j'ai reporté les deux pour ne pas en cacher un.

## Commandes lancées, dans l'ordre (Step 8)

Garde-fou avant chaque lancement : `Get-Process python -ErrorAction SilentlyContinue` — vide à
chaque fois (aucun moteur, aucune appli qui traîne), vérifié 3 fois pendant la tâche.

```
python src/core/errp_decoder.py
```
```
ErrP synthétique : 200 feedbacks (46 erreurs / 154 corrects, 23% erreurs — classe minoritaire), 5 blocs, fs=250 Hz
[1] balayage nfilter (AUC OOF) : nf2=86.3%  nf3=84.9%  nf4=82.0%  -> RETENU nfilter=2
[2] AUC erreur/correct (GroupKFold par bloc) : 86.3%  (hasard 50%)
    test de permutation : p=0.010 (significatif)
[errp] pipeline xDAWN+Riemann validé sur synthétique (mono-essai).
EXITCODE=0
```

```
python src/core/errp_models.py
```
VERDICT : OK, EXITCODE=0 (sortie complète dans la section VERT ci-dessus).

```
python src/core/server.py --smoke
```
```
[smoke] VERDICT : OK
[smoke-frontiere] 0 violation(s) de frontière
[smoke-frontiere] VERDICT : OK
[smoke-repos] VERDICT : OK
[smoke-ssvep] VERDICT : OK
[smoke-neuro] VERDICT : OK
[smoke-mi] VERDICT : OK
[smoke-calib] VERDICT : OK
[smoke-calib-refus] VERDICT : OK
[smoke-cumul] VERDICT : OK
[smoke-proposition] VERDICT : OK
[smoke-dimensionnement] VERDICT : OK
[smoke-tampon] VERDICT : OK
[smoke-marqueurs] VERDICT : OK
[smoke-marqueurs-file] VERDICT : OK
[smoke-marqueurs-inlet] VERDICT : OK
[smoke-marqueurs-relance] VERDICT : OK
[smoke-marqueurs-stream-in] VERDICT : OK
EXITCODE=0
```
`smoke-frontiere` scanne `src/core/**/*.py`, donc `errp_decoder.py` et `errp_models.py` désormais
dedans : **0 violation**.

```
python src/research/app.py --smoke
```
Se termine par `[app] smoke OK : menu + SSVEP + c-VEP (eCCA & rCCA) + P300 + neuro + ErrP(cal+démo)
câblés (headless).`, `EXITCODE=0`. Le smoke exerce réellement le chemin recâblé : calibration ErrP
(2 blocs × 6 pas, un modèle entraîné) PUIS démonstrateur (chargement du modèle qui vient d'être
calibré, un pas décodé) — donc `core.errp_decoder.ErrPModel` importé et exécuté de bout en bout
depuis `research/app.py`. Vérifié que ce smoke écrit ses modèles jetables
(`errp_model_smoke.joblib`) dans un dossier temporaire (`app.py:1377`, `tempfile`), jamais dans
`data/` — confirmé après coup : `data/errp_model.joblib` toujours à 35115 octets / 24 juillet.

## Commit (Step 9)

```
git add -A src/core/errp_decoder.py src/core/errp_models.py src/research/
git commit -m "Move the ErrP decoder into the engine, and retrain rather than shim"
```
```
[main b35872a] Move the ErrP decoder into the engine, and retrain rather than shim
 4 files changed, 348 insertions(+), 4 deletions(-)
 rename src/{research => core}/errp_decoder.py (99%)
 create mode 100644 src/core/errp_models.py
```

`git status --short` après coup : seul `.superpowers/sdd/.gitignore` reste modifié.

## Ce dont je doute / observations pour le coordinateur

1. **`.superpowers/sdd/.gitignore` modifié, mais HORS PÉRIMÈTRE — pas touché**, exactement la même
   situation que documentée dans `task-1-report.md` du chantier P300 (déjà réduit à la seule ligne
   `*` avant que je commence, pas par moi). Non restauré, non ajouté au commit : réglage partagé du
   chantier, pas à moi de trancher unilatéralement.

2. **Deux erreurs concrètes trouvées dans le brief et corrigées avec preuve** (détaillées plus haut) :
   la classe `_ModeleHerite` du Step 5 ne peut pas être locale à `_selftest` (PicklingError
   reproduite), et le message de refus du Step 4 rate son propre test à cause d'une majuscule
   (vérifié à l'interpréteur). Les deux corrections préservent l'intention et la sémantique du test
   protégé — rien n'a été affaibli pour les faire passer.

3. **`decrire()["n_epoques"]` reste toujours `None` pour l'ErrP** — `ErrPModel` ne pose pas
   d'attribut `n_epoques_` (contrairement à `P300Model`). J'ai gardé la clé (parité de forme avec
   `p300_models.decrire`, même dict consommé par la même future UI console) plutôt que de l'ajouter
   à `ErrPModel` dans `errp_decoder.py`, qui est listé « Déplacer » et non « Modifier » dans le
   brief. Si un futur mode veut afficher le nombre d'époques d'entraînement de l'ErrP, il faudra
   ajouter `self.n_epoques_ = int(len(y))` dans `ErrPModel.fit` — pas fait ici, volontairement.

4. **Aucun processus Python résiduel** à aucun moment (vérifié avant/après chaque lancement).

5. Rien d'autre dans le brief ne m'a semblé faux : le reste (déménagement pur, non-modification du
   `sys.path`, message du chemin vide côté appli pygame, structure du fichier) est cohérent et
   vérifié par l'exécution.
