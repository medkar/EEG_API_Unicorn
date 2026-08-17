# Tâche 4 — Le P300 déménage dans `core/`, et son modèle se ré-entraîne — rapport d'implémentation

Statut : **DONE**
Commit : `2ebf022` — « Move the P300 decoder into the engine, and retrain rather than shim »
Base : `1b48a5e` (HEAD de `main` avant cette tâche)

## Vérification préalable du fait central du brief

Avant tout déplacement, chargement en LECTURE SEULE de `data/p300_model.joblib` avec
`src/research` sur `sys.path` (donc `p300_decoder` nu importable) :

```
type: <class 'p300_decoder.P300Model'> p300_decoder
cv_auc_: 0.7145659722222223
```

Confirmé : le pickle porte bien le module NU `p300_decoder`, et son AUC réelle est
**0,714566 (71,5 %)** — pas le « 73 % » approximatif de la mémoire projet (`eeg-p300.md`, notée
comme pouvant être imprécise). Cette valeur mesurée directement dans le pickle sert de référence
pour juger le ré-entraînement plus bas, plutôt que la mémoire.

## Ce qui a été fait

1. **`git mv src/research/p300_decoder.py src/core/p300_decoder.py`** — historique suivi
   (`git log --follow` le confirme), `sys.path.insert` de tête **non touché** (vérifié : les deux
   `dirname` mènent à `src/` depuis `core/` comme depuis `research/`).
2. **Recâblage des importeurs** (`grep -rn "p300_decoder" src/`) : `research/app.py` (2 sites),
   `research/errp_calibrate.py`, `research/errp_decoder.py` (import + une phrase de docstring),
   `research/p300_calibrate.py` (import + deux phrases de docstring), `research/p300_analyze.py`
   — tous `from research.p300_decoder import ...` → `from core.p300_decoder import ...`.
3. **`src/core/p300_models.py` créé**, jumeau de `mi_models.py` : `charger`, `modeles_disponibles`
   (tuple, plus récent d'abord), `decrire`. Autotest `_selftest()` dans un dossier temporaire.
4. **Ré-entraînement** depuis `data/p300_calib_20260722_151134_n12.npz` (script jetable, hors
   dépôt) → `data/p300_model_20260817-135716.joblib`. `data/p300_model.joblib` intact.

## Un piège NON signalé par le brief, trouvé en le mesurant

`_demo()`, en toute fin de `p300_decoder.py`, faisait `from research.itr import itr as _itr` pour
son print `ITR ~X bits/min`. Une fois le fichier dans `core/`, cette ligne est repérée par la
regex de `server.py::_smoke_frontiere` (`^\s*(?:from|import)\s+(research|...)`) — peu importe
qu'elle soit nichée dans une fonction : elle aurait fait échouer `[smoke-frontiere]` dès le
premier lancement, contredisant frontalement l'« Expected » de l'étape 6 du brief (« aucun import
de `research` depuis `core` »). Corrigé par une réplique locale de dix lignes de la formule de
Wolpaw (`_itr()`, documentée comme duplication délibérée), pas par une suppression du print.
Vérifié : `[smoke-frontiere] 0 violation(s) de frontière` après coup.

Au passage, `P300Model` gagne `n_epoques_` (comme `MIModel.n_essais_`), rempli dans `fit()` :
c'est ce que `p300_models.decrire()` doit afficher (« nombre d'époques », demandé par le brief) et
rien ne le portait avant.

## Le ré-entraînement — les chiffres demandés

Sortie brute du script (`retrain_p300.py`, scratchpad) :

```
[retrain] source : p300_calib_20260722_151134_n12.npz
[retrain] cohérence flashed/cues/groups <-> labels : OK
[retrain] 576 époques (12 manches) : 96 cibles / 480 non-cibles  (fs=250 Hz)
[retrain] entraînement en 2.0s  n_epoques_=576  AUC cible/non-cible (GroupKFold, 5 plis) = 71.5%
[retrain] (comparaison avec l'ancien modèle indisponible : No module named 'p300_decoder')
[retrain] (bonus) sélection leave-one-round-out : 8/12 = 67%  (hasard 17% à 6 cibles)
[retrain] modèle -> .../data/p300_model_20260817-135716.joblib
[retrain] data/p300_model.joblib intact (mtime inchangé) : Wed Jul 22 15:11:34 2026
```

**AUC en validation croisée par groupe (GroupKFold par manche), rendue par `P300Model.fit`** :
`0.7145659722222223` — vérifié **BIT POUR BIT IDENTIQUE** à celle du modèle de juillet chargé en
lecture seule ci-dessus (mêmes données, même pipeline déterministe : `GroupKFold` sans
mélange, xDAWN/TangentSpace/LogisticRegression sans aléa). **Aucun effondrement — reproduction
exacte**, donc le ré-entraînement a bien reproduit les conditions d'origine.

- 576 époques, 12 manches, **96 cibles / 480 non-cibles** (12 manches × 6 cibles × 8 rép, cohérent
  avec `P300_CAL_ROUNDS=12`, `P300_N_TARGETS=6`, `P300_REPS=8`).
- Cohérence interne vérifiée : `flashed[i]==cues[groups[i]]` reproduit exactement le tableau
  `labels` archivé.
- Bonus (pas demandé par le brief, ajouté pour corroborer) : sélection leave-one-round-out
  **8/12 = 67 %** (hasard 17 % à 6 cibles) — nettement significatif, mais sous le « 83 % » que la
  mémoire du projet prêtait à cette même séance. La mémoire date de 20 jours et se signale
  elle-même comme pouvant être approximative ; je n'ai aucune trace fichier de ce 83 % pour
  trancher plus loin. Ce n'est pas la métrique demandée par le brief (l'AUC, elle, correspond
  exactement) — signalé pour transparence, pas comme un problème.
- `data/p300_model.joblib` : mtime et taille (36485 o) inchangés — non écrasé.

## La preuve de refus — deux contextes, deux messages, jamais de plantage

`data/p300_model.joblib` (juillet) via `core.p300_models.charger`, sans `src/research` sur
`sys.path` (lancement nu / console / appli pygame) :

```
modèle illisible (ModuleNotFoundError) : p300_model.joblib
```

Même fichier, avec `src/core` sur `sys.path` (comme le fait `python src/core/server.py` en
ajoutant le dossier du script) — le pickle se charge alors, mais sous le module nu `p300_decoder`,
et c'est le contrôle d'IDENTITÉ de module qui le rattrape :

```
modèle hérité (module 'p300_decoder', attendu 'core.p300_decoder'), abandonné délibérément —
ré-entraîner depuis les époques de calibration conservées (data/p300_calib_*.npz) : p300_model.joblib
```

Les deux vérifiés empiriquement (pas déduits) ; aucun ne lève. `modeles_disponibles()` exclut le
fichier dans les deux cas et ne propose que le modèle ré-entraîné.

## Deux plantages évités, au-delà de la lettre du brief

Le brief limite `p300_analyze.py`/`app.py` à « (imports) ». En vérifiant `mode_p300` (celui que la
console… non, que **l'appli pygame** utilise réellement), j'ai trouvé que son garde-fou
(`os.path.exists(model_path)`) ne détecte que l'ABSENCE du fichier, pas son illisibilité — et
`data/p300_model.joblib` existe toujours. Un·e étudiant·e choisissant « P300 → Lancer le live »
sans recalibrer d'abord aurait donc obtenu un `ModuleNotFoundError` brut, **en pleine séance,
après le contrôle de contact** (`signal_check`). Même défaut, même correction dans
`p300_analyze.py` (déjà dans la liste des fichiers du brief). Les deux utilisent maintenant
`core.p300_models.charger()`, qui ne lève jamais. Vérifié :

```
$ python src/research/p300_analyze.py
[p300-an] pas de modèle P300 utilisable (modèle illisible (ModuleNotFoundError) : p300_model.joblib) — calibre ou ré-entraîne d'abord.
```

… au lieu d'un plantage. Re-testé par `app.py --smoke` après coup (voir plus bas) : toujours vert.

## Tests — dans l'ordre demandé, un par un, aucun moteur laissé tournant

Garde-fou avant CHAQUE lancement : `Get-Process python -ErrorAction SilentlyContinue` vérifié vide.

| Commande | Sortie |
|---|---|
| `python src/core/p300_decoder.py` | AUC synthétique 90,2 %, sélection 12/12, exit 0 |
| `python src/core/p300_models.py` | 16 `OK`, `[p300-models] VERDICT : OK`, exit 0 |
| `python src/core/server.py --smoke` | 16 sous-verdicts `OK` (dont `[smoke-frontiere] 0 violation(s)`), exit 0 |
| `python src/research/app.py --smoke` | `smoke OK : menu + SSVEP + c-VEP (eCCA & rCCA) + P300 + neuro + ErrP(cal+démo) câblés`, exit 0 |

`python src/core/p300_models.py`, les trois preuves exigées par le brief :

```
OK   un modèle hérité est refusé en disant quoi faire (modèle hérité (module '__main__', attendu 'core.p300_decoder'), abandonné délibérément — ré-entraîner depuis les époques de calibration conservées (data/p300_calib_*.npz) : p300_model_etranger.joblib)
OK   le plus récent d'abord (('...p300_model_a.joblib', '...p300_model_z.joblib'))
OK   un dossier vide rend (), sans lever
```

`app.py --smoke` ré-exécuté une seconde fois après le correctif de `mode_p300` (le premier run
avait eu lieu avant) — toujours vert, les deux variantes P300 (rép fixes + arrêt dynamique)
exercées.

## Commit

```
git add src/core/p300_decoder.py src/core/p300_models.py src/research/app.py \
        src/research/errp_calibrate.py src/research/errp_decoder.py \
        src/research/p300_analyze.py src/research/p300_calibrate.py
git commit -m "Move the P300 decoder into the engine, and retrain rather than shim"
```

```
[main 2ebf022] Move the P300 decoder into the engine, and retrain rather than shim
 7 files changed, 291 insertions(+), 21 deletions(-)
 rename src/{research => core}/p300_decoder.py (90%)
 create mode 100644 src/core/p300_models.py
```

`git status --short` après coup : seul `.superpowers/sdd/.gitignore` reste modifié — préexistant
(déjà là avant que je commence, et déjà réparé une fois dans ce chantier, commit `1b48a5e`), non
lié à cette tâche, pas touché : réglage partagé du chantier, pas à moi de trancher seul.

## Inquiétudes / ce que je laisse dehors

1. **`src/research/__init__.py` contient désormais une phrase fausse** (§2 de son docstring liste
   encore `p300_decoder` parmi les décodeurs « qui migreront vers `core` »), et la table du
   README (« migration candidates ») aussi. Je ne les ai pas touchées : la tâche 7 de ce chantier
   (« La documentation — le contrat devient public ») possède explicitement `README.md` dans son
   propre périmètre, avec des chiffres (« 4 modes sur 6 ») qui ne seront vrais qu'après les tâches
   5-6 — un correctif prématuré de ma part serait de toute façon à refaire. Signalé plutôt que
   corrigé à moitié.
2. **La sélection LORO bonus (67 %) est sous le 83 % de la mémoire projet** — voir plus haut.
   L'AUC (la métrique que le brief demande) correspond exactement, donc je ne crois pas à un
   effondrement du ré-entraînement, mais je préfère le dire que le taire.
3. **Deux plantages corrigés au-delà de la lettre du brief** (`mode_p300`, `p300_analyze.py`) —
   détaillé plus haut. Change le comportement (message au lieu d'un crash), pas l'interface
   publique ; utilise uniquement `p300_models.charger()`, déjà construit et testé dans cette même
   tâche.
4. `data/` porte maintenant deux `.joblib` P300 (`p300_model.joblib` intact +
   `p300_model_20260817-135716.joblib`) et trois `p300_calib_*.npz` inchangés — rien nettoyé,
   conforme au brief (« ne pas écraser »).
