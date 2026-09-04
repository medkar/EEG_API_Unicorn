# Task 1 — rapport : déménager le décodage c-VEP dans `core/`, et prouver que le modèle survit

**Statut : DONE**
**Commit : `a0fd4ab` — "Move the c-VEP decoder into the engine, and prove the model survives"**
Base : `c34e326`. Un seul commit, contient tout (test + déplacement + recâblage).

---

## Étape 1 — écrire le test qui échoue

Ajouté `_selftest()` dans `src/research/cvep_decoder.py` (à son emplacement d'ORIGINE, avant tout
déplacement — le fichier n'existe pas encore dans `core/`, donc c'est le seul endroit où l'écrire).
Contenu : exactement le snippet du brief (round-trip `save`/`load`, comparaison bit à bit des
tableaux, vérification des métadonnées, et absence du nom de module dans le fichier écrit).

Deux adaptations mécaniques, sans changer le sens du test :
- Le snippet utilise `_os.path.join(...)`, mais le fichier importe `os` tel quel (pas `import os as
  _os`, contrairement à `markers.py`/`p300_models.py`). Plutôt que de changer `_os` en `os` (et
  s'écarter du texte du brief), j'ai ajouté `import os as _os` en import LOCAL dans `_selftest()`,
  juste à côté de `import tempfile as _tf, shutil as _sh` déjà présent dans le snippet — le corps du
  test reste donc verbatim.
- `__main__` appelait `_demo()` sans jamais vérifier son retour : `python src/research/cvep_decoder.py`
  sortait TOUJOURS en 0, quel que soit le résultat (le même défaut que `p300_decoder.py` et
  `errp_decoder.py` avaient déjà corrigé chez eux). Corrigé au passage : `__main__` appelle
  maintenant `_demo()` (démonstration numérique, comportement inchangé) PUIS
  `sys.exit(0 if _selftest() else 1)`.

Avant de déplacer quoi que ce soit, `python src/research/cvep_decoder.py` à son emplacement encore
en place confirme que le test est LOGIQUEMENT correct (3/3 assertions vertes, VERDICT OK, exit 0) —
ça isole « le test est juste » de « le fichier est au bon endroit », qui est précisément ce que
l'étape 2 vérifie.

## Étape 2 — lancer le test, vérifier qu'il échoue

```
$ python src/core/cvep_decoder.py
C:\...\python.exe: can't open file 'C:\...\src\core\cvep_decoder.py': [Errno 2] No such file or directory
EXIT CODE: 2
```

Écart avec le brief : l'erreur attendue était `ModuleNotFoundError`. La sortie réelle est différente
(Python ne trouve même pas de FICHIER à exécuter, donc erreur du lanceur, pas de l'interpréteur) mais
le sens est identique : le fichier n'existe pas encore dans `core/`, et la commande échoue (exit ≠ 0)
pour cette raison. Sortie collée telle quelle plutôt que la sortie attendue par le brief.

## Étape 3 — déplacer les deux fichiers

```
git mv src/research/cvep_code.py src/core/cvep_code.py
git mv src/research/cvep_decoder.py src/core/cvep_decoder.py
```

**Point vérifié, pas supposé : l'insertion de `sys.path` n'a eu besoin d'AUCUN changement.** Le brief
affirmait qu'elle devait « remonter d'un niveau de moins » en passant de `research/` à `core/`. En
réalité `research/` et `core/` sont tous deux des enfants DIRECTS de `src/` — le même
`os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` (2 appels) résout donc vers `src/`
dans les deux cas, que le fichier soit dans l'un ou l'autre. Vérifié en lançant les fichiers déplacés
sans y toucher : ils fonctionnent immédiatement (voir étape 5). Le motif est bien celui de
`src/core/errp_decoder.py`, mais il était déjà identique avant le déplacement — rien à recopier.

Seuls changements dans les deux fichiers déplacés :
- `core/cvep_decoder.py` : `from research.cvep_code import build_targets, m_sequence` →
  `from core.cvep_code import build_targets, m_sequence` (le seul import à corriger réellement) ;
  ligne de commande de l'autotest en tête de docstring `python src/research/cvep_decoder.py` →
  `python src/core/cvep_decoder.py`.
- `core/cvep_code.py` : même correction cosmétique de la ligne de commande en tête de docstring.

## Étape 4 — recâbler tous les importeurs

`grep -rn "research.cvep_code\|research.cvep_decoder\|from research import cvep" src/ README.md`
(exécuté avant tout changement) a donné la liste exhaustive suivante, toutes corrigées :

| Fichier | Changement |
|---|---|
| `src/research/app.py:433-434` | `from research.cvep_code/cvep_decoder import …` → `from core.…` (dans `mode_cvep`) |
| `src/research/app.py:485` | `from research.cvep_code import is_on as cvep_on` → `from core.cvep_code import …` (dans `mode_cvep_rcca`) |
| `src/research/cvep_analyze.py:32` | `from research.cvep_decoder import CVEPModel, bandpass` → `from core.cvep_decoder import …` |
| `src/research/cvep_calibrate.py:25-26` | `from research.cvep_code/cvep_decoder import …` → `from core.…` |
| `src/research/cvep_rcca.py:26` | `from research.cvep_decoder import bandpass` → `from core.cvep_decoder import bandpass` |

`src/research/cvep_rcca.py` lui-même **reste dans `research/`** : ce chantier ne bouge que le
décodeur eCCA classique (`cvep_code`/`cvep_decoder`) ; `RCCAModel`/`RCCADecoder` migreront à la
tâche 3 du plan. Seul son import de `bandpass` a changé.

`src/research/__init__.py` (« les décodeurs des modes ») : mis à jour pour dire que `cvep_code` et
`cvep_decoder` ont rejoint `core` le 2026-08-20 (cinquième et sixième décodeurs à faire ce trajet),
et que `cvep_rcca` reste seul dans `research/` — la variante à codes distincts, jamais publiée,
réfutée face à l'eCCA (mesuré 2026-07-21, cf. sa propre docstring).

`README.md` :
- Table `src/research/` : la ligne « Mode decoders — the migration candidates » ne cite plus que
  `cvep_rcca`, en notant que les quatre autres (`cvep_decoder`, `cvep_code`, `p300_decoder`,
  `errp_decoder`) ont rejoint `core/`.
- Bloc `## Self-tests` : les deux lignes `python src/research/cvep_code.py` /
  `cvep_decoder.py` sont montées dans le groupe `core/` (à la suite de `modes/errp.py`, dans l'ordre
  chronologique des migrations), réécrites en `python src/core/cvep_code.py` /
  `cvep_decoder.py`, cette dernière complétée en « … model round-trip » pour refléter le nouveau
  contenu du test.

Confirmation finale (`grep` ré-exécuté après tous les changements) : plus aucune occurrence de
`research.cvep_code`/`research.cvep_decoder` dans `src/` ni `README.md`, à l'exception d'UNE mention
en prose, dans le docstring de `_selftest()` lui-même (« …c'est ce qui rend `core.cvep_decoder`
capable de relire ce que `research.cvep_decoder` avait écrit ») — un commentaire historique
volontaire, pas un import.

## Étape 5 — lancer les tests

Les quatre, lancés un par un (jamais en parallèle), après vérification qu'aucun python du projet ne
tournait déjà (deux processus python trouvés au départ appartenaient à un AUTRE projet,
`Promptuino/promptuinoUI`, confirmé par leur ligne de commande complète — sans rapport avec
EEG_API_Unicorn).

```
python src/core/cvep_code.py       → [cvep] autotest : OK                          exit 0
python src/core/cvep_decoder.py    → [cvep-decoder] VERDICT : OK  (3/3 assertions)  exit 0
python src/research/app.py --smoke → [app] smoke OK : menu + SSVEP + c-VEP (eCCA & rCCA)
                                      + P300 + neuro + ErrP(cal+démo) câblés (headless).  exit 0
python src/core/server.py --smoke  → 17 sous-smokes, tous « VERDICT : OK », y compris
                                      [smoke-frontiere] VERDICT : OK  (aucun import
                                      research/console/pygame/Qt détecté dans core/)      exit 0
```

Les quatre verts, sortie 0 partout, comme attendu. `app.py --smoke` exerce réellement les DEUX
chemins de calibration c-VEP (`mode_cvep` et `mode_cvep_rcca`), donc les trois import corrigés dans
`app.py` sont bien passés à l'exécution, pas seulement à l'analyse statique. `server.py --smoke`
confirme via `smoke-frontiere` que les fichiers déplacés ne violent pas la frontière core/research.

## Étape 6 — vérifier le VRAI modèle, celui du 21 juillet

Hashé avant (`certutil -hashfile … SHA256`) : `d66859856b91375ad2226bb24ee63b1f39e9a05c51ded69489f918d2720ec2de`.

```
$ python -c "import sys; sys.path.insert(0,'src'); from core.cvep_decoder import CVEPModel; m = CVEPModel.load('data/cvep_model.npz'); print(f'n_targets={m.n_targets} refresh={m.refresh} code_len={m.code_len} cv={m.cv_}')"
n_targets=6 refresh=60.0 code_len=63 cv=0.4777777777777778
```

**Verdict : le modèle survit.** Il se charge sans erreur à travers `core.cvep_decoder` (le module
qui n'existait pas quand ce fichier a été écrit), `n_targets=6` comme attendu, `refresh=60.0`,
`code_len=63`, et l'accuracy leave-one-out de calibration (`cv_`) ressort à 47,8 % — cohérente avec
un modèle à 6 cibles (hasard 16,7 %).

Hashé après le chargement : `d66859856b91375ad2226bb24ee63b1f39e9a05c51ded69489f918d2720ec2de` —
**identique**, taille et date de modification inchangées (`4424` octets, `21 juil. 16:15`). Confirmé
aussi par `git status --short data/` : rien à signaler. Le fichier n'a pas été touché.

C'est la valeur centrale de cette tâche, mesurée et non supposée : contrairement au P300 et à l'ErrP,
le c-VEP ne perd rien à son déménagement dans `core/`.

## Preuve rouge → vert (mutation, exigée par la méthode de la tâche)

Le test structurel des étapes 1-2 (fichier absent → erreur) est une preuve de DÉPLACEMENT, pas une
preuve que le contenu du test attrape une vraie régression. Complété par une mutation sur le code
déjà déplacé, ciblant exactement ce que le round-trip est censé attraper : la fidélité bit-à-bit des
tableaux sauvegardés.

Mutation appliquée dans `CVEPModel.save` (`src/core/cvep_decoder.py`) :
```diff
- np.savez(path, w=self.w, template=self.template, fs=self.fs, refresh=self.refresh,
+ np.savez(path, w=self.w, template=self.template + 1.0, fs=self.fs, refresh=self.refresh,
```

Rouge :
```
  ÉCHEC un modèle écrit puis relu rend les MÊMES tableaux, bit pour bit
  OK   ...et ses métadonnées ([4, 5, 6, 7], 63, 6)
  OK   le fichier ne contient AUCUN nom de module — c'est ce qui le rend déplaçable
[cvep-decoder] VERDICT : PROBLÈME
EXIT CODE (mutant): 1
```

Mutation retirée (fichier restauré identique à l'original, vérifié par `git diff HEAD` vide après
coup). Vert :
```
  OK   un modèle écrit puis relu rend les MÊMES tableaux, bit pour bit
  OK   ...et ses métadonnées ([4, 5, 6, 7], 63, 6)
  OK   le fichier ne contient AUCUN nom de module — c'est ce qui le rend déplaçable
[cvep-decoder] VERDICT : OK
EXIT CODE (revert): 0
```

Ça confirme au passage que la correction du bug « `_demo()` sans vérification de retour » (étape 1)
fonctionne : c'est bien `_selftest()` qui pilote le code de sortie, et un modèle corrompu fait sortir
le fichier en 1.

## Étape 7 — commit

```
git add -A src/core/cvep_code.py src/core/cvep_decoder.py src/research/ README.md
git commit -m "Move the c-VEP decoder into the engine, and prove the model survives" …
```

→ `a0fd4ab`, 8 fichiers changés (67 insertions, 17 suppressions), les deux renommages détectés par
git (`cvep_code.py` 98 % similaire, `cvep_decoder.py` 83 % — le reste est `_selftest()`).

`docs/superpowers/plans/2026-08-20-cvep-moteur.md`, modifié en début de session par un processus
antérieur (tâche 7 du plan amendée AVANT que je commence, note laissée dans `progress.md`), n'a pas
été touché par moi et n'est pas dans ce commit — conforme à la liste `git add` du brief.

## Fichiers concernés (chemins absolus)

- `C:\Users\Lab_IA\Documents\Projets_Dev\EEG_API_Unicorn\src\core\cvep_code.py` (créé par déplacement)
- `C:\Users\Lab_IA\Documents\Projets_Dev\EEG_API_Unicorn\src\core\cvep_decoder.py` (créé par déplacement + `_selftest()`)
- `C:\Users\Lab_IA\Documents\Projets_Dev\EEG_API_Unicorn\src\research\app.py`
- `C:\Users\Lab_IA\Documents\Projets_Dev\EEG_API_Unicorn\src\research\cvep_analyze.py`
- `C:\Users\Lab_IA\Documents\Projets_Dev\EEG_API_Unicorn\src\research\cvep_calibrate.py`
- `C:\Users\Lab_IA\Documents\Projets_Dev\EEG_API_Unicorn\src\research\cvep_rcca.py`
- `C:\Users\Lab_IA\Documents\Projets_Dev\EEG_API_Unicorn\src\research\__init__.py`
- `C:\Users\Lab_IA\Documents\Projets_Dev\EEG_API_Unicorn\README.md`
- `C:\Users\Lab_IA\Documents\Projets_Dev\EEG_API_Unicorn\data\cvep_model.npz` (LU seulement, hash vérifié inchangé)

## Doutes / réserves

- Aucun doute sur le résultat lui-même : les quatre tests demandés sont verts, la mutation prouve
  que le nouveau test attrape une vraie régression, et le modèle réel survit avec un hash inchangé.
- Deux écarts factuels par rapport au brief, documentés ci-dessus plutôt que corrigés en silence :
  l'erreur de l'étape 2 n'est pas littéralement `ModuleNotFoundError` (c'est le lanceur Python qui
  ne trouve pas le fichier), et le `sys.path` n'a eu besoin d'aucune correction. Aucun des deux ne
  change le résultat, mais je préfère les signaler plutôt que de recopier une prédiction non vérifiée.
- Le sous-agent qui fera la tâche 2 doit savoir que `core/cvep_decoder.py` n'a PAS encore de
  `synth_cvep`/`CVEPDecoder` renommés ni de changement de comportement de décodage — seul le fichier
  a bougé et gagné son autotest de persistance. Tout le reste (mode runtime, publication réseau,
  `cvep_models.py`) reste à faire, conformément au plan.
