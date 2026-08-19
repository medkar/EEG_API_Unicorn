# fix-G1 — correction des défauts NOUVEAUX des re-revues B, C et D

Périmètre autorisé : `src/research/app.py`, `src/research/errp_stimulus.py`,
`src/research/errp_calibrate.py`, `src/console/app.py`, `src/console/grid.py`,
`src/console/live_views.py`, `src/core/server.py`. **`src/core/modes/errp.py` non touché**
(re-relecteur en lecture seule dessus) — vérifié : il n'apparaît pas dans le diff.

`src/console/__init__.py` a été ajouté au périmètre : c'est le seul point commun de `grid.py` et
`live_views.py` (il porte déjà `PHASES_FR`, avec exactement la même justification « une seule
écriture pour deux écrans »). Aucun autre fichier hors liste n'a été modifié.

**8 défauts traités · 6 reportés.**

---

## Les quatre prioritaires

### 1. Un test écrivait dans le VRAI `data/` — re-revue B, NOUVEAU-1. **TRAITÉ**

`src/research/app.py:_smoke` écrivait ses quatre modèles dans `os.path.dirname(CVEP_MODEL_PATH)`
= `DATA_DIR`, dont `errp_model_smoke.joblib` et `p300_model_smoke.joblib` — deux noms qui
correspondent à `errp_models.MOTIF` / `p300_models.MOTIF`, donc éligibles comme **modèle par
défaut** du moteur, de la console et de l'accueil. Le ménage était hors `finally`.

Fait :

- `tmp = tempfile.mkdtemp(prefix="app_smoke_")` ; les quatre chemins en dérivent ;
- toute la séquence calibrations + modes dans un `try` / `finally: shutil.rmtree(tmp,
  ignore_errors=True)` ;
- **une garde runtime** : `_empreinte_data()` (nom → taille, mtime) est prise en tête de `_smoke`
  et recomparée à la fin. Un fichier ajouté, retiré, réécrit ou seulement retouché fait rougir,
  quel que soit son nom. C'est cette garde qui empêchera le prochain test d'y revenir.

Bonus de la même passe (re-revue B, NOUVEAU-4) : `assert errp_models.charger(errp_path)[0] is not
None` juste après la calibration du smoke — sans elle, un refus de `charger` faisait sortir
`mode_errp` avant sa boucle live et le smoke restait vert avec ~120 lignes non exercées.

#### Preuve que `data/` n'est plus touché

`data/` listé **avant** toute modification, puis **après** la totalité du travail (4 smokes verts +
9 exécutions sous mutation, dont celle qui écrit délibérément à côté) :

```
IDENTIQUE apres TOUS les tests et TOUTES les mutations : 43 fichiers, memes tailles, memes mtimes
```

(`Compare-Object` sur `(Nom, Taille, mtime)` des 43 entrées, ligne à ligne : zéro différence.)

Les modèles, mtimes à la milliseconde :

| fichier | taille | mtime (avant == après) |
|---|---|---|
| `errp_model.joblib` | 35 115 | **2026-07-24 11:46:08.852** |
| `errp_model_20260818-153051.joblib` | 38 451 | 2026-08-18 15:30:51.428 |
| `p300_model.joblib` | 36 485 | 2026-07-22 15:11:34.897 |
| `p300_model_20260817-135716.joblib` | 36 493 | 2026-08-17 13:57:16.281 |
| `mi_model.joblib` | 3 309 | 2026-07-22 13:48:38.781 |

Résidus `*_smoke.*` dans `data/` : **0**.

#### Preuve rouge

Mutation *stand-in* (2 lignes) : `globals()["DATA_DIR"] = tmp` après le `mkdtemp`, et le
`shutil.rmtree` remplacé par `pass`. C'est-à-dire « le smoke écrit là où la garde regarde, et ne
nettoie pas » — la régression exacte, sans écrire dans le vrai `data/` (la mutation fidèle,
`tmp = DATA_DIR`, est **refusée** : elle écrit 8 fichiers dans `data/`, et le `rmtree` du `finally`
y détruirait le dossier entier).

```
AssertionError: le smoke a touché data/ : ['cvep_model_smoke.npz', 'cvep_rcca_model_smoke.npz',
'errp_model_smoke.joblib', 'p300_model_smoke.joblib']. Aucun test ne doit y écrire — les modèles
de test vont dans un tempfile.mkdtemp() (et le plus récent modèle CHARGEABLE de data/ est le
défaut proposé par le moteur, donc un modèle de test oublié là se fait élire)
EXIT=1
```

Les quatre fichiers nommés sont exactement ceux de la constatation. Mutation retirée → `[app] smoke
OK`, `EXIT=0`.

Preuve rouge de l'assertion `charger` : `model.oof_scores_ = None` avant `model.save` dans
`errp_calibrate.calibrate` →
`AssertionError: le modèle du smoke doit être ACCEPTÉ par errp_models.charger() … : pas de scores
hors-pli, donc aucun seuil réglable`, `EXIT=1`. Retirée → vert.

---

### 2. `[smoke-tampon]` n'exerçait pas la troncature — re-revue C, N2. **TRAITÉ**

Confirmé par exécution : phase 1 produit 104 échantillons pour `keep = 1250`, le `min()` est inerte.
Le commentaire qui annonçait « il vérifie AUSSI la troncature » est corrigé pour dire l'inverse, et
une **phase 2** est ajoutée : un second `EngineServer` à `keep = 20` avec un producteur qui rend
`keep + 17 = 37` échantillons **par tour**. Le régime plein est donc atteint dès le premier
passage : le verdict ne dépend ni de `POLL_S`, ni de `duration_s`, ni de la machine — et après
n'importe quel nombre de tours ≥ 1, le tampon doit être exactement la **fin** du dernier bloc.

Trois assertions : le producteur a bien débordé (sinon les suivantes ne prouvent rien) ; les deux
tampons saturent à `keep` ; et ce qui reste est la **fin** du dernier bloc (une troncature écrite
`[:keep]` garderait les plus vieux échantillons — variante que l'ancien test ne voyait pas non plus).

#### Preuve rouge

Mutation : les deux `[-self.keep:]` retirés de `src/core/server.py:1212-1213` (production).

```
  OK   les deux tampons ont la même longueur (104 et 104)
  OK   et ils portent tout ce que le producteur a rendu, borné à `keep` (104 pour 104 produits, keep=1250)
  OK   le temps avance strictement, sans doublon ni retour en arrière …
  OK   et la cadence RECOPIÉE vaut exactement celle du producteur, à 0.051 µs près …
  OK   le dernier tour de boucle a bien lu un bloc …
  OK   ce bloc (13 échantillons) tient dans le tampon (104)
  OK   la QUEUE de `recent` est exactement le dernier bloc lu, valeur pour valeur (13 échantillons)
  OK   ...et la queue de `recent_ts` est exactement les horodatages de CE bloc …
  OK   le producteur a bien débordé le tampon (148 échantillons pour keep=20) …
  ÉCHEC le tampon SATURE à `keep` au lieu de grandir (148 lignes et 148 dates pour keep=20) — c'est
        l'assertion qui rougit quand un `[-self.keep:]` disparaît de la boucle
  ÉCHEC et ce qui reste est la FIN du dernier bloc, pas son début — une troncature écrite `[:keep]`
        garderait les échantillons les plus VIEUX et le moteur décoderait du passé
[smoke-tampon] VERDICT : PROBLÈME
EXIT=1
```

**Les huit assertions préexistantes restent vertes** : c'est la démonstration littérale du trou que
la re-revue décrivait. Slices remises →

```
  OK   le tampon SATURE à `keep` au lieu de grandir (20 lignes et 20 dates pour keep=20) …
  OK   et ce qui reste est la FIN du dernier bloc, pas son début …
[smoke-tampon] VERDICT : OK        EXIT=0
```

---

### 3. `_smoke_frontiere` scannait sa propre docstring — re-revue C, N3. **TRAITÉ**

La détection est sortie dans `_imports_interdits(source, nom_fichier)` et **passée d'une expression
régulière à `ast`** : seuls les nœuds `Import` / `ImportFrom` sont examinés, donc ni docstrings, ni
commentaires, ni chaînes ne peuvent produire de verdict. Les noms interdits vivent dans deux
constantes (`_FRONTIERE_INTERDITS`, `_FRONTIERE_INTERDITS_RE`) et n'apparaissent nulle part ailleurs
en prose sous forme d'import complet. Gains de passage : import indenté, import multi-lignes entre
parenthèses et import **relatif** (`from ...research import x`) sont désormais attrapés — le
transitif et le dynamique restent documentés comme angles morts. Le message nomme maintenant la
**ligne**.

Un jeu de 13 extraits fabriqués est exécuté à chaque smoke : 9 formes interdites qui doivent être
attrapées, 4 formes (docstring / commentaire / chaîne / import légitime) qui doivent être ignorées.
Sans lui, une garde muette rendrait « 0 violation » et passerait pour un succès.

#### Preuves

**(a) la prose ne déclenche plus.** Ajout temporaire dans `server.py` d'une docstring reflowée
mettant `from PySide6.QtCore import QTimer` en **colonne 0** →

```
  OK   « """from PySide6.QtCore import QTimer en docstring."" » -> rien (attendu rien)
[smoke-frontiere] 27 fichiers scannés, 0 violation(s) de frontière
[smoke-frontiere] VERDICT : OK          EXIT=0
```

Sur le **même fichier**, l'ancien motif regex :

```
ANCIEN motif (celui d avant la correction) -> 2 violation(s): [(2132, 'PySide6'), (2134, 'PySide6')]
```

2132 = la **prose**, 2134 = le vrai import. L'ancien confondait les deux ; le nouveau n'en voit qu'un.

**(b) un vrai import est toujours attrapé.** Même fichier, `from PySide6.QtCore import QTimer` dans
le corps d'une fonction (jamais exécutée) →

```
[smoke-frontiere] ÉCHEC : core/server.py:2134 importe PySide6
[smoke-frontiere] 27 fichiers scannés, 1 violation(s) de frontière
[smoke-frontiere] VERDICT : PROBLÈME     EXIT=1
```

**(c) une garde muette rougit.** Mutation `_FRONTIERE_INTERDITS` privé de `"pygame"` →

```
  ÉCHEC « import pygame » -> rien (attendu ['pygame'])
[smoke-frontiere] 27 fichiers scannés, 0 violation(s) de frontière
[smoke-frontiere] VERDICT : PROBLÈME     EXIT=1
```

Les trois mutations retirées → vert.

---

### 4. La docstring de `errp_stimulus.py` affirmait une identité fausse — re-revue D, N1. **TRAITÉ (docstring seule)**

**Aucun protocole n'a été aligné** : `errp_calibrate._run_block` est resté intact, comme demandé.
Vérifié dans le source : `_track_hold(…, 0.9, "nouvelle cible")` est ligne 212, **avant** le `while`
— une fois par bloc ; en cours de bloc, `:225` tient 0,7 s puis `:228` téléporte.

La docstring a été relue **en entier**. Corrections :

1. **§ fins de course** — « les mêmes deux écrans que `errp_calibrate._run_block` et que
   `app.mode_errp` » supprimé. Remplacé par un § dédié qui dit ce que fait chacun, avec les SOA :

   | | transition (fin de course → pas suivant) | intra-course |
   |---|---|---|
   | `errp_calibrate._run_block` | 1,0 + 0,7 = **1,7 s**, transitoire à t=0 | 1,0 + 0,45 = 1,45 s |
   | cet émetteur | 1,0 + 0,7 + 0,9 = **2,6 s**, sans transitoire | 1,0 + 0,45 = 1,45 s |

   Mesuré par le smoke : transitions `[2.58] s`, intra `[1.42 … 1.39] s` — les deux chiffres écrits
   sont ceux que la boucle produit. Le § dit explicitement que l'écart est **assumé et non corrigé**,
   pourquoi (aligner `_run_block` invaliderait le modèle du 24 juillet, AUC 0,7763, d'où viennent
   tous les chiffres du mode), et que ~1 époque d'entraînement sur 7 porte un transitoire qu'aucune
   époque en ligne ne porte.
2. **§ « il se reproduit »** (ligne 26-32) — troisième affirmation d'identité, non signalée par la
   re-revue : bornée à la trajectoire et à la cadence intra-course, avec renvoi au § ci-dessus.
3. **§ cadence** — « exactement la cadence de `_run_block` » précisé en « cadence **intra-course** »
   (c'était vrai, mais pas pour les transitions).
4. **Commentaire `:399`** — « Mêmes durées, même découpe que … » remplacé par le fait et les deux SOA.
5. **Commentaire des trois `PAUSE_*_S`** — « recopiées de `_run_block` » → « les **valeurs** sont
   celles de `_run_block` », plus un ⚠️ « même valeur ≠ même place ».
6. **`app.mode_errp`** décrit correctement : `ERRP_EPOCH_S + 0,2` entre les pas, plus 2,4 s d'écran
   de verdict à chaque détection — donc référence de cadence pour personne.
7. Ligne d'exemple `--seconds 20` et aide argparse mises à jour (cf. re-revue D N2 ci-dessous).

Aucune preuve rouge : c'est de la documentation. Les chiffres écrits sont cependant **arrimés par un
test**, voir ci-dessous.

---

## Les autres, traités

### re-revue D, N3 — les trois durées ne sont ancrées à rien. **TRAITÉ**

`--smoke` compare désormais les trois `PAUSE_*_S` aux **littéraux du source** de
`errp_calibrate._run_block` (motif `, 0.45,` etc. — la forme d'appel de `_track_hold`). Le
commentaire dit ce que le contrôle prouve (les valeurs) et ce qu'il ne prouve **pas** (la place —
`PAUSE_NOUVELLE_COURSE_S` diverge délibérément).

**Preuve rouge** : `PAUSE_INTER_PAS_S = 0.45` → `0.1`.

```
  ÉCHEC les trois durées de cet émetteur sont CELLES sous lesquelles le modèle a été entraîné
        (littéraux de errp_calibrate._run_block) … (introuvables là-bas : PAUSE_INTER_PAS_S = 0.1)
  OK   DANS une course, 1.1 s entre deux onsets (±20 %) — la cadence de errp_calibrate, celle sous
       laquelle le modèle a été entraîné ([1.06, 1.07, 1.06, 1.05, 1.07, 1.06] s)
[errp-stim] VERDICT : PROBLÈME     EXIT=1
```

L'assertion de cadence reste **verte** en annonçant 1,1 s comme « la cadence de errp_calibrate » —
exactement l'auto-référence que la re-revue décrivait. Mutation retirée → 19 contrôles verts.

### re-revue D, N2 — `--seconds` < 23 s = séance muette, sortie 0. **TRAITÉ**

`t_start` part maintenant à `None` et n'est posé qu'**après** l'attente moteur : `--seconds` compte
le temps de stimulation, ce que son nom promet. Et `run` imprime toujours un **bilan** :
`[errp-stim] fin : N pas joués, …`, avec un ⚠️ explicite quand N vaut 0. Visible dans la sortie du
smoke (`fin : 5 pas joués`, `fin : 4 pas joués`, `fin : 1 pas joués`).

Pas de preuve rouge dédiée : reproduire le défaut demande un **second processus** abonné aux
marqueurs (sans consommateur, l'attente retombe à 0,9 s) — un smoke ne doit pas en lancer un. Le
changement est couvert indirectement : les trois `run()` du smoke passent par le nouveau `t_start`.

### re-revue D, M4 — rien n'interdit le retour de `research.errp_decoder`. **TRAITÉ**

Assertion ajoutée sur le source de `mode_errp` et `page_errp`, à côté de celle qui interdit
`ErrPModel.load`. **Preuve rouge** faite pour de vrai : `src/research/errp_decoder.py` recréé
temporairement + import basculé dans `mode_errp` →
`AssertionError: mode_errp doit décoder par core.errp_decoder …`, `EXIT=1`. Fichier temporaire
supprimé, import rétabli, `git status` propre.

### re-revue C, N1 — tuile et page SSVEP à deux échelles, l'écart FIGÉ par une assertion. **TRAITÉ**

`SSVEP_SPAN_SEUILS = 2.0` posé dans `console/__init__.py` ; `grid._apercu_scores` et
`live_views._update_scores` l'utilisent tous deux. L'assertion `_span == threshold` est devenue
`_span == SSVEP_SPAN_SEUILS * threshold`, plus une assertion de **rendu**.

**Preuve rouge** : tuile ramenée à `max(float(seuil), 1.0)` →

```
  ÉCHEC et la tuile SSVEP garde son échelle absolue … à la MÊME échelle que sa page (2.5 pour un seuil de 2.5)
  ÉCHEC la page SSVEP et sa tuile remplissent leurs barres à la MÊME hauteur ([62, 8, 18] contre [100, 16, 36])
[console-smoke] VERDICT : PROBLÈME     EXIT=1
```

`[62, 8, 18]` contre `[100, 16, 36]` : les chiffres exacts du tableau de la re-revue. Rétabli → vert.

### re-revue C, N4 — la normalisation relative écrite deux fois, rien ne lie les deux rendus. **TRAITÉ**

`classement_relatif(scores)` extrait dans `console/__init__.py` (côté rendu, pas moteur — la console
reste un client). Appelé par `grid._apercu_scores` **et** `live_views._update_selection`. Assertion
qui **lie** les deux rendus sur les mêmes données.

Elle a trouvé une divergence dès sa première exécution : `61` contre `60`, un écart d'arrondi
(`round` côté test, `int` côté `QProgressBar`). Corrigé en mirroring exact de la conversion de la
page — c'est le genre de détail qu'une assertion « chacun de son côté » ne pouvait pas voir.

**Preuve rouge** : mutation de la page seule (`int(parts[i] * 90)`) →

```
  ÉCHEC la tuile et la page rendent le MÊME classement sur les mêmes données
        ([25, 0, 60, 100, 20, 45] contre [22, 0, 54, 90, 18, 40])
[console-smoke] VERDICT : PROBLÈME     EXIT=1
```

C'est-à-dire : « quelqu'un édite la page et oublie la tuile » rougit maintenant. Rétabli → vert.

### re-revue C, N5 — la page ErrP sans titre pendant ses 23 premières secondes. **TRAITÉ**

`self.etat.setText((mode_state or {}).get("instruction") or "en attente du premier échantillon
décodé")`. Pas de routage sur l'identifiant du mode : la phrase vaut pour tout mode qui attend.

**Preuve rouge** : retour à `mode_state["instruction"] if mode_state else "en attente"` →

```
  ÉCHEC ...et elle dit tout de même quelque chose plutôt que de rester vide ('')
[console-smoke] VERDICT : PROBLÈME     EXIT=1
```

Rétabli → vert.

---

## Reportés, et pourquoi

| # | Constatation | Raison du report |
|---|---|---|
| re-B I3 (reste) | Remède fantôme dans la docstring et un commentaire de `core/errp_models.py` | **Hors périmètre** : `core/errp_models.py` n'est pas dans la liste autorisée. Deux phrases à réécrire, sans code. |
| re-B NOUVEAU-3 | `chk` décoratif sur un littéral, `errp_models.py:450-452` | **Hors périmètre**, même fichier. À transformer en commentaire. |
| re-B NOUVEAU-2 | `_errp_charger(None)` retombe sur `ERRP_MODEL_PATH`, donc « modèle introuvable : C:\…\data\errp_model.joblib » au lieu de « lance ErrP → Calibrer » sur un dépôt cloné | **Dans le périmètre, non fait faute de temps.** Correctif d'une ligne (`dispo[0] if dispo else None`), mais la re-revue exige de le faire **aux deux endroits** (`mode_p300`, `app.py:639-641`, fait pareil) — donc deux chemins de démarrage à re-tester, et le smoke tourne sur un poste qui a des modèles valides, où le défaut est invisible. À faire avec un test qui force la liste vide. |
| re-C M1 (reste) | Le seuil de la tuile ErrP reste une barre de 2 px | Demande un mode de dessin de plus dans `MiniBars` (dessiner le seuil comme une LIGNE). La re-revue elle-même juge le report justifié et le classe non bloquant. |
| re-C M4 (reste) | `measured_on = "1 person"` est un littéral non dérivé | **Hors périmètre** : exige que `ErrPModel` expose son nombre de groupes → `core/errp_models.py` + `core/lsl_io.py`. |
| re-C M5 | L'extrait « Brancher un client » muet sur le `-1` | **Hors périmètre** : `core/modes/contract.py`. Une ligne dans le gabarit, au chantier suivant. |
| re-D I2 (reste) | Fusionner `errp_calibrate._decide_step`/`_new_goal` en adaptateurs de `errp_stimulus` | Refactor à deux fichiers dont l'un produit le modèle ; le garde-fou différentiel existant (500 pas, graine égale) tient la dérive. À décider explicitement, comme N1. |
| re-D N4 | Deux assertions du smoke dépendent du budget horloge (~20 % de marge) | Non reproduit sur ce poste (`intra` mesuré 1,39-1,43 s contre un plafond de 1,74 s ; B2 conclut ses 4 marqueurs). Correctif proposé (couper B2 en nombre de PAS plutôt qu'en secondes) sain mais non urgent. |

## Dépendances hors périmètre à remonter

- **`core/errp_models.py`** : trois constatations y butent (re-B I3-reste, re-B NOUVEAU-3, re-C M4).
  Un seul passage sur ce fichier les ferme toutes les trois.
- **`core/modes/contract.py`** : re-C M5, une ligne dans le gabarit « Brancher un client ».
- **`errp_calibrate._run_block`** : la vraie fermeture de re-D N1 (option (a)) demande une décision
  produit — elle change le protocole sous lequel le seul modèle ErrP du dépôt a été entraîné. **Non
  prise ici, par consigne.** La docstring dit désormais l'écart et le renvoie explicitement.
- **`p300_models.py:27`** (re-B) et `mode_p300`/`_p300_status` (re-B NOUVEAU-2) : les corrections
  faites côté ErrP ne sont pas répercutées sur le jumeau P300.

## Autotests — état final

```
python src/core/server.py --smoke        17 VERDICT : OK          EXIT=0
python src/console/app.py --smoke        [console-smoke] OK       EXIT=0
python src/research/errp_stimulus.py --smoke  [errp-stim] OK      EXIT=0
python src/research/app.py --smoke       [app] smoke OK           EXIT=0
```

Un seul programme Python à la fois, du début à la fin (vérifié : aucun `python` résiduel avant la
série finale). Toutes les mutations sont retirées ; `data/` est bit-pour-bit identique à son état
initial.
