# Tâche 10 — rapport : les retraits

**Statut : terminé.** Quatre commits, `96a4923` → `4446ac6`, arbre propre.
17 tests verts (10 dans `archive/`, 7 dans le reste du dépôt). `data/` **intact, prouvé par
empreinte** — mais pas sans incident : lire le §5 en premier si vous ne lisez qu'une section.

---

## 1. Ce qui a bougé

| Avant | Après |
|---|---|
| `research/app.py` : `Live`, `_sender_loop`, `_vote`, `_panel`, `_live_loop`, `_running` | `research/ui.py`, à côté de `App` et `Abort` |
| `research/app.py::mode_ssvep` (+ 6 fonctions) | `archive/ssvep_pilot.py` |
| `research/app.py::mode_p300` (+ 6 fonctions) | `archive/p300_pilot.py` |
| `research/app.py::mode_errp` (+ 5 fonctions) | `archive/errp_demo.py` |
| `src/research/cvep_calibrate.py` | `archive/cvep_calibrate.py` (`git mv`) |
| `src/research/p300_calibrate.py` | `archive/p300_calibrate.py` (`git mv`) |
| `src/research/errp_calibrate.py` | `archive/errp_calibrate.py` (`git mv`) |
| `src/research/app.py` (1544 lignes à l'origine) | **supprimé** |

`archive/` contient maintenant **dix** fichiers exécutables, chacun avec son `--smoke`, son
`--windowed`, son `--synthetic` et un `--model` explicite là où il en charge ou en écrit un.

`src/research/` ne contient plus **aucune** application ni **aucune** calibration : le socle pygame
(`ui.py`, `ssvep_stimulus.py`, `viewing.py`), les analyses hors ligne (`*_analyze.py`,
`calibrate.py`, `itr.py`, `mi_compare.py`), les protocoles chiffrés (`ssvep_guided.py`,
`alpha_check.py`), l'hypothèse réfutée gardée lisible (`cvep_rcca.py`) et l'héritage robot
(`controller.py`, `live_ssvep.py`). `__init__.py` a été réécrit en conséquence : sa famille 1 n'est
plus « l'application pygame » mais « le socle pygame », et sa famille 3 (« les calibrations ») est
désormais vide.

## 2. L'ordre, et pourquoi il a servi

L'étape 1 (machinerie → `ui.py`, imports de l'archive suivis, **quatre smokes avant tout le
reste**) n'était pas une précaution de style : elle a **trouvé un rouge**.

`archive/cvep_rcca_pilot.py --smoke` était **cassé depuis la tâche 8**, et cassé de la pire façon —
voir §5. Aucun test du dépôt ne le lançait ; il n'aurait été découvert qu'en séance, le jour où on
en a besoin. C'est exactement l'argument du brief, vérifié.

**Un écart au découpage prescrit.** Le brief séparait « les trois écrans de pilotage » et « les
trois calibrations ». Je les ai archivés dans **un seul commit** (`71e3d7c`), parce qu'ils forment
un bloc indissociable : `p300_pilot` importe la couronne et le flash de `p300_calibrate`,
`errp_demo` importe la piste et l'écran de seuil de `errp_calibrate`, `cvep_rcca_pilot` importe le
briefing et les blocs entrelacés de `cvep_calibrate`. Les séparer en deux commits n'aurait produit
qu'un import écrit deux fois — `research.p300_calibrate` puis `p300_calibrate` — c'est-à-dire du
bruit de revue sans aucun gain de sûreté : à partir du commit 1, l'archive ne dépend plus de
`app.py`, donc une interruption ne peut plus la casser. L'ordre PRESCRIT (machinerie d'abord,
`app.py` en dernier) est intégralement respecté.

## 3. Ce qui n'est PAS parti dans `archive/`, et pourquoi

**Le neuro-monitoring.** `mode_neuro` et ses cinq fonctions d'affichage ont disparu avec `app.py`,
sans copie archivée. C'est une asymétrie assumée, et elle suit le critère que `archive/README.md`
énonce déjà : on garde un écran parce qu'il **décode localement**, donc qu'il sert de référence
contre le réseau en séance. Les trois pilotes archivés ont chacun leur pile de décodage. L'écran
neuro n'en a pas : le calcul est `core.neuro_monitor.NeuroDecoder`, l'objet **même** dont le moteur
publie la sortie, et la console a repris ses textes à la tâche 9 (`INDEX_DESCRIPTIONS`). L'archiver
aurait préservé un rendu, pas une référence. Git le garde au parent de `a8513b3`.

**`research/calibrate.py`** reste dans `research/` malgré son nom : c'est l'analyse hors ligne d'un
log SSVEP guidé (elle LIT `data/session1_2026-07-17.log`, elle n'écrit rien). C'est précisément la
« moitié d'analyse hors ligne » que le brief demande de conserver.

**`_p300_status` / `_toggle_robot`** sont morts avec le menu qui les appelait (texte d'accueil,
bascule robot). `_errp_status`, lui, a suivi dans `errp_demo.py` : il y sert la ligne
« modèles ErrP : … » au lancement, et son assertion de smoke a suivi avec lui.

## 4. Les tests qui ont déménagé avec leur écran

Le `_smoke` de `research/app.py` portait des assertions qui ne protégeaient plus rien une fois le
fichier supprimé. Elles ont été **remontées dans le `--smoke` du fichier archivé correspondant**,
verbatim quant à leur intention :

| Assertion | Nouveau domicile |
|---|---|
| modèle P300 horodaté ≠ `P300_MODEL_PATH`, et conforme à `p300_models.MOTIF` | `archive/p300_calibrate.py::_invariants_smoke` |
| `calibrate()` P300 retombe sur `chemin_modele_horodate()` | idem |
| invariant oddball (`blocs_melanges`, jamais de `shuffle` local) — 2 sites | `p300_calibrate::_invariants_smoke` (`_run_round`) et `p300_pilot::main` (`mode_p300`) |
| modèle ErrP horodaté ≠ `ERRP_MODEL_PATH`, conforme à `errp_models.MOTIF`, repli horodaté | `archive/errp_calibrate.py::_invariants_smoke` |
| `mode_errp` charge par `_errp_charger`, jamais un `joblib.load` nu ; jamais `research.errp_decoder` | `archive/errp_demo.py::main` |
| le modèle du smoke est ACCEPTÉ par `errp_models.charger` | idem |
| `calibrate()` c-VEP n'a jamais `CVEP_MODEL_PATH` / `CVEP_RCCA_MODEL_PATH` en défaut | `archive/cvep_calibrate.py::_selftest` |
| `data/` ressort intact | les **dix** `--smoke` de `archive/`, via `empreinte_dossier` |

**Une assertion nouvelle, et elle a mordu tout de suite.** `archive/p300_calibrate.py --smoke`, tel
que je l'avais d'abord écrit, imprimait « smoke OK » alors que **l'entraînement avait été refusé**.
Cause : tant que cet écran était appelé par le `_smoke` de `app.py`, il passait après quatre autres
modes et le board BrainFlow avait des secondes d'historique ; lancé seul, il flashe sur un tampon
qui vient de s'ouvrir et `epoch_from_stream` ne peut pas fournir le pré-stimulus de la première
manche. Mesuré : **1 époque sur 6** à la manche 1, 7 au total, sous le plancher de `p300_calib`
(12) — `calibrate()` attrape la `ValueError`, imprime « pas d'entraînement », rend `False`, et le
smoke ne regardait pas la valeur de retour. Corrigé sur les deux axes : pré-remplissage du board
(1,2 s, comme le jumeau ErrP le faisait déjà) + 3 manches au lieu de 2, **et** une assertion qui
exige le FICHIER et son rechargement par `p300_models.charger`. C'est le même défaut que ce dépôt
attrape en boucle : un test qui vérifie qu'on n'a pas levé, pas qu'on a fait quelque chose.

## 5. ⚠️ L'incident `data/` — lu, contenu, corrigé

**Empreinte au départ** (`core.config.empreinte_dossier(DATA_DIR)`, 43 fichiers) :

```
sha256 = 42120328ed4df50265e14522eb61c5035423bbb52064f33b14d3293dfae8083d
```

**Empreinte après la dernière commande** (43 fichiers) :

```
sha256 = 42120328ed4df50265e14522eb61c5035423bbb52064f33b14d3293dfae8083d
```

**Identiques.** Mais elles ne l'ont pas été tout du long, et voici l'histoire complète.

Au premier lancement des quatre smokes de l'archive (étape 1, avant toute autre modification),
`archive/cvep_rcca_pilot.py --smoke` a **écrit dans le vrai `data/`** :
`cvep_rcca_model_20260908-122453.npz`, 106 Ko, entraîné sur un board synthétique.

Mécanisme, et il est instructif. Ce smoke éprouve le REPLI de `calibrate_rcca` (`save_path=None`)
en détournant les chemins fixes vers un dossier temporaire. Il patchait
`research.cvep_calibrate.CVEP_MODEL_PATH` et `.CVEP_RCCA_MODEL_PATH`. Or la tâche 8 a déménagé
`chemin_modele_horodate` dans `core/modes/cvep_calib.py`, qui lit **le `CVEP_MODEL_PATH` de son
propre module**. Le détournement était devenu un **no-op silencieux**. Prouvé sans rien écrire :

```
ANCIEN détournement (research.cvep_calibrate) -> …\EEG_API_Unicorn\data\cvep_rcca_model_….npz
NOUVEAU détournement (core.modes.cvep_calib)  -> …\Temp\preuve_s2x9ggsa\cvep_rcca_model_….npz
```

Gravité : le nom produit correspond à `cvep_models.MOTIF`, donc ce fichier **apparaissait dans la
liste des modèles** et pouvait être proposé comme le plus récent. C'est mot pour mot l'accident que
le dépôt documente déjà deux fois.

Pourquoi la garde n'a pas protégé : `empreinte_dossier` est appelée **après** l'appel, et
l'assertion sur le nom horodaté (`assert any(f.startswith("cvep_rcca_model_") …)`) a levé **avant**
elle. Une garde placée après l'écriture ne protège pas d'une écriture.

Ce que j'ai fait :

1. **Contenu.** Le fichier a été **retiré de `data/`** et déplacé dans le scratchpad de session
   (`…\scratchpad\cvep_rcca_model_20260908-122453.npz`) plutôt que détruit — rien n'est perdu, mais
   il n'est plus élisible. Empreinte revérifiée : retour exact au sha256 de départ.
2. **Corrigé.** `cvep_rcca_pilot.py` patche désormais `core.modes.cvep_calib`, le module que la
   fonction lit RÉELLEMENT — **et vérifie le détournement sur son résultat, avant d'appeler quoi
   que ce soit** :

   ```python
   vise = _horodate_mod.chemin_modele_horodate("rCCA")
   assert os.path.dirname(os.path.abspath(vise)) == os.path.abspath(tmp), (…)
   ```

   Le jour où cette fonction redéménage, l'assertion rougit **sans qu'une ligne ne soit écrite dans
   `data/`**. Patcher « tous les endroits » est un jeu qu'on reperd à chaque déménagement ; vérifier
   le résultat, non. La leçon est consignée dans `archive/README.md`.

## 6. Tests

**Les dix de `archive/`** — tous `EXIT=0` :

```
mi_calibrate  mi_pilot  cvep_pilot  cvep_rcca_pilot  ssvep_pilot
p300_pilot  errp_demo  cvep_calibrate  p300_calibrate  errp_calibrate
```

**Les sept du reste du dépôt** — tous `EXIT=0` / `VERDICT : OK` :

```
src/core/server.py --smoke        src/console/app.py --smoke
src/stimulus/p300.py --smoke      src/stimulus/errp.py --smoke
src/stimulus/cvep.py --smoke      src/stimulus/registry.py
src/research/cvep_rcca.py
```

`src/core/server.py --smoke` est celui qui compte pour la frontière : `core` n'importe toujours ni
`research`, ni `console`, ni `stimulus`. Aucun fichier de `src/core/`, `src/console/` ou
`src/stimulus/` n'a été modifié.

**Le critère du brief :**

```
grep -rn "research.app|research/app" src/ archive/ examples/   ->  0 occurrence de CODE
```

Les occurrences restantes sont toutes de la **prose** (commentaires, docstrings). Celles de
`archive/` ont été mises à jour pour dire « supprimé le 2026-09-08 » au lieu de désigner un fichier
au présent ; celles de `src/research/` aussi (`cvep_rcca.py`, `ui.py`, `__init__.py`).

## 7. Réserves à porter — pour la tâche 11 et pour la revue

🔴 **Trois messages d'exécution de `src/core/` envoient l'étudiant vers un fichier qui n'existe
plus.** Hors de mon périmètre (interdiction explicite de toucher `src/core/`), donc signalés :

| Site | Texte |
|---|---|
| `src/core/cvep_models.py:202` | « Recalibre (`python src/research/app.py`, mode … » |
| `src/core/modes/cvep.py:283` | « — recalibre (`python src/research/app.py`, mode c-VEP) » |
| `src/core/modes/cvep.py:298` | « Recalibre (`python src/research/app.py`, … » |
| `src/core/modes/cvep.py:752` | « `python src/research/app.py`, mode c-VEP, et calibre. » |

Ce ne sont pas des commentaires : ce sont les phrases que voit un étudiant dont le modèle est
refusé. **Et `src/core/modes/cvep.py:923` est un test qui EXIGE ce texte** (`and "research/app.py"
in raison`) — il faudra le retourner en même temps. Le P300 et l'ErrP ont déjà été corrigés aux
tâches 4 et 7, et leurs tests affirment aujourd'hui l'inverse (`"research/app.py" not in raison`,
`p300.py:785`, `errp.py:816`) : le c-VEP est le seul retardataire, et le patron du correctif est
déjà écrit deux fois à côté.

⚠️ **Prose périmée ailleurs**, à traiter en tâche 11 (aucune n'est exécutable) :
`src/console/app.py:10` et `src/console/grid.py:9` (nomment l'appli pygame comme un programme
concurrent), `src/core/server.py:4` et `:36`, `src/stimulus/{p300,errp,cvep}.py` (plusieurs
renvois à `research/app.py` / `research/*_calibrate.py`), et `CLAUDE.md`, qui décrit encore un menu
pygame à 5 pages et « les calibrations que le moteur ne sait pas jouer ».

⚠️ **`archive/mi_calibrate.py` et `archive/mi_pilot.py` écrivent toujours sous des noms FIXES** en
usage réel (`mi_model.joblib`, `mi_calib_last.npz`). C'est délibéré et documenté depuis le chantier
MI (« l'archive reste ce qu'elle était »), mais les huit autres fichiers du dossier horodatent
désormais : l'asymétrie est plus visible maintenant qu'ils sont dix. Non touché.

⚠️ **Aucun de ces dix écrans n'a vu un cerveau depuis son archivage.** Les `--smoke` prouvent le
câblage sur board synthétique. La recette 2.9 — comparer le décodage local de `cvep_pilot.py` au
décodage réseau sur la même fixation — reste à jouer, et elle a maintenant deux frères
(`p300_pilot.py`, `errp_demo.py`) qui permettent la même comparaison pour leurs modes.

## 8. Commits

```
96a4923  Move the shared pygame machinery to ui.py, where the archive can reach it
71e3d7c  Retire the six pygame screens to where they stay checkable
a8513b3  Delete the pygame app: every page it had now lives elsewhere
4446ac6  Tell the archive what the six new files are, and fix a line that lied
```
