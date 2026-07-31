### Task 7: L'archivage et la documentation

**Files:**
- Create: `archive/README.md`
- Move: `src/research/mi_calibrate.py` → `archive/mi_calibrate.py`
- Move: `src/research/mi_pilot.py` → `archive/mi_pilot.py`
- Modify: `src/research/app.py` (6 modes → 5)
- Modify: `src/core/mi_decoder.py` (deux renvois de docstring devenus faux)
- Modify: `CLAUDE.md`, `README.md`, `docs/SPEC.md`, `docs/recette.md`

**Interfaces:** aucune. Cette tâche ne change aucun comportement du moteur.

**⚠️ Cette tâche est la DERNIÈRE.** Tant que la console ne sait pas calibrer, l'écran pygame est le
seul moyen de produire un modèle (spec §9). Ne pas la commencer avant que la tâche 6 soit verte.

- [ ] **Step 1: Créer l'archive et déplacer**

```bash
mkdir archive
git mv src/research/mi_calibrate.py archive/mi_calibrate.py
git mv src/research/mi_pilot.py archive/mi_pilot.py
```

- [ ] **Step 2: `archive/README.md`**

```markdown
# archive/ — what this is, and what it is not

These files are **not maintained** and **not covered by the automated tests**. They are kept
because they are the reference the current implementation was checked against: running the old
Motor Imagery calibration side by side with the engine's own, and comparing timing, labels and
recorded epochs, is a real test — and it only exists as long as both exist.

"Git keeps the history" is true but weak: nobody goes looking in the history for a file they don't
know exists.

| File | What it was |
|---|---|
| `mi_calibrate.py` | The pygame Motor Imagery calibration. Replaced by the engine's own (`src/core/modes/mi_calib.py`), which measures a **honest** accuracy and never overwrites a recording. ⚠️ The accuracy this screen prints is inflated by 10 to 16 points. |
| `mi_pilot.py` | The pygame MI pilot: sliding vote over decoded windows, feedback screen, robot output. Its vote is now `MIRuntime` in `src/core/modes/mi.py`. |

Each file keeps its `--smoke`, which is how you check by hand that it still runs, the day you need
it:

```bash
python archive/mi_calibrate.py --smoke
python archive/mi_pilot.py --smoke
```

They write to `data/` under the **old, fixed** names (`mi_model.joblib`,
`mi_calib_last.npz`) — so an archived calibration **overwrites** the previous one. That is one of
the two defects the engine's calibration fixed; it is left here on purpose, so the archive stays
what it was.
```

- [ ] **Step 3: Faire tourner les deux fichiers archivés**

Deux retouches par fichier (vérifiées dans le code, spec §9) :

1. Le `sys.path.insert` remonte d'un cran de trop depuis `archive/`. Remplacer
   `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` par un chemin qui vise
   explicitement `<dépôt>/src` :
   ```python
   sys.path.insert(0, os.path.join(
       os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
   ```
2. Tout `from research.X import ...` devient `from core.X import ...` là où le module a déménagé
   (vérifier avec `grep -n "^from research\|^import research" archive/*.py`). `mi_pilot.py` importe
   `research.mi_calibrate` : les deux étant dans `archive/`, l'import devient `import mi_calibrate`
   (même dossier) — vérifier que `archive/` est bien sur `sys.path` (il l'est : c'est le dossier du
   script).

Run: `python archive/mi_calibrate.py --smoke` puis `python archive/mi_pilot.py --smoke`
Expected: les deux en sortie 0.

⚠️ Ces deux smokes écrivent dans le vrai `data/`. Vérifier `git status --short` après (rien ne doit
apparaître — `data/` est gitignoré) et **ne pas s'inquiéter** d'un `mi_model.joblib` écrasé : il
n'est plus lu par rien (`mi_models.charger` refuse les modèles hérités, et la console ne propose
que ce qui se charge).

- [ ] **Step 4: L'appli pygame passe de 6 à 5 modes**

Dans `src/research/app.py` :
- retirer `mode_mi` du menu et sa fonction (lignes ~424-…), avec ses imports `MIDecoder`,
  `MIModel`, `research.mi_pilot.MIController` ;
- retirer l'entrée de calibration MI (`import research.mi_calibrate as mi_calibrate`, ~ligne 1067)
  du menu des calibrations ;
- retirer la ligne d'état `mi = "oui" if os.path.exists(MI_MODEL_PATH) else "absent"` (~1109) et
  son affichage ;
- retirer `from research.mi_pilot import _dummy_model` et l'écriture de `mi_path` du `--smoke`
  (~1388, ~1412) ;
- retirer `MI_KEY_CHANNELS` / `MI_MODEL_PATH` de l'import de `core.config` **s'ils ne servent plus
  ailleurs dans le fichier** (vérifier par `grep`).

Le menu doit annoncer **5 modes**. Chercher toute chaîne « 6 modes » dans le fichier.

Run: `python src/research/app.py --smoke`
Expected: sortie 0, et le compte de modes du smoke passé de 6 à 5.

- [ ] **Step 5: Les renvois devenus faux dans `core/`**

Dans `src/core/mi_decoder.py` :
- ligne 5 : `[src/research/mi_calibrate.py]` → `[src/core/modes/mi_calib.py]` ;
- ligne ~190 (docstring de `MIDecoder.classify`) : la phrase « reste utilisée par l'appli pygame
  (`research/app.py`, `mi_pilot.py`) » devient fausse — l'appli n'a plus de MI. La remplacer par :
  « n'est plus utilisée que par `archive/mi_pilot.py`. Le moteur, lui, passe par `scores()` : voir
  `core/modes/mi.py`. » ;
- ligne 1 et 38 : le vocabulaire d'ACTIONNEUR (« 2 commandes », « stop » fiable, `MI_CONTROL`)
  contredit la règle « intention neutre, jamais une commande » du produit. Reformuler les
  commentaires. **Ne pas renommer `MI_CONTROL`** : `archive/mi_pilot.py` l'importe.

Même vérification dans `src/core/config.py:238` (« proba mini pour émettre une commande (sinon
None = stop) »).

- [ ] **Step 6: La documentation**

| Fichier | Ce qui devient faux, et ce qu'il faut écrire |
|---|---|
| `CLAUDE.md` | « menu à 6 modes » → **5** ; « seul accès aux 3 modes… c-VEP, P300, ErrP » (le MI n'y est plus) ; retirer `python src/research/mi_calibrate.py` des commandes utiles et le remplacer par « la calibration MI se lance depuis la console » ; retirer la mention « la calibration MI vit encore dans l'appli pygame — c'est la moitié B du chantier 3 » ; ajouter `python src/core/modes/calibration.py` et `python src/core/modes/mi_calib.py` aux gardes MI (à côté des trois existants). |
| `README.md` | ligne ~94 : « Train one with `python src/research/mi_calibrate.py` » → la console ; ligne ~230 : retirer `mi_calibrate` du tableau des calibrations ; décrire la page de calibration et le bouton Démarrer/Arrêter. |
| `docs/SPEC.md` | §14 (roadmap) : le chantier 3 est TERMINÉ, ses deux moitiés ; la calibration est possédée par le moteur, ce qui rend l'évolution F2 (« calibration pilotée par l'app ») atteignable — sans la livrer. |
| `docs/recette.md` | mettre à jour le **test 2.6** : la calibration se lance depuis la console, l'accuracy affichée est l'honnête (dire quoi attendre : **≈ 40 % à 3 classes est NORMAL**), et ne plus dire de lancer `mi_calibrate.py`. Ajouter au **niveau 0** les deux nouveaux autotests. Ajouter un test « démarrer/arrêter un mode depuis la grille ». La tuile MI n'est plus grisée nulle part. |

- [ ] **Step 7: Le jeu complet, EN SÉRIE**

```bash
python src/core/modes/contract.py
python src/core/modes/calibration.py
python src/core/modes/mi_calib.py
python src/core/mi_decoder.py
python src/core/mi_models.py
python src/core/modes/mi.py
python src/core/acquisition.py --synthetic
python src/core/server.py --smoke
python src/console/app.py --smoke
python src/research/app.py --smoke
python archive/mi_calibrate.py --smoke
python archive/mi_pilot.py --smoke
```
Expected: les douze en sortie 0.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Retire the pygame MI screens to archive/, and say so everywhere"
```

---

## Ce qui reste DEHORS de ce plan

À dire en annonçant le chantier fini, pas à découvrir après.

**Parké de la moitié A, non repris ici** (les trois autres l'ont été, en T2) :

- **L'égalité du vote est tranchée par ordre d'apparition**, donc publie l'intention la plus
  ANCIENNE au moment précis où l'utilisateur bascule. Inatteignable aux réglages par défaut
  (3 + 3 > 5), atteignable dès `vote_len ≥ 6` — qui est dans la plage du curseur.
- **Un `None` majoritaire écrase une classe qui atteint pourtant `min_votes`.** L'aide du réglage
  ne le dit pas.
- **Aucun rejet d'artefact sur le MI**, contrairement au SSVEP. Le CSP lit précisément la variance
  8-30 Hz que l'EMG fait exploser : un vrai serrement de main produira une intention confiante.
- **`rest_index` vaut `-1` sur un modèle à deux classes**, donc collisionne avec
  `no_decision_index`. La calibration produit toujours trois classes, donc c'est hors d'atteinte
  aujourd'hui — mais ça le redeviendrait si on offrait une séance à deux classes.

**Décidé pendant l'écriture de ce plan :**

- **Aucun test de permutation à la fin d'une calibration.** Il donnerait la seule réponse
  vraiment honnête (« ce score est-il distinguable du hasard ? ») mais coûte quelques secondes de
  plus au moment où l'étudiant attend son résultat. La page dit à la place ce que valent les
  chiffres de référence du projet et leur significativité. À reprendre le jour où on voudra un
  verdict et pas seulement un repère.
- **La calibration ne reprend pas une séance abandonnée.** Un modèle entraîné sur cinq essais ne
  se distingue pas d'un modèle complet dans la liste, et donnerait des probabilités plausibles et
  fausses. L'écran pygame, lui, entraînait sur ce qui restait.
- **Aucune migration des `mi_calib_last.npz` existants.** Décision d'exploitation déjà prise le
  2026-07-30 : les modèles hérités sont abandonnés, `mi_models.charger` les refuse explicitement.

**Hors périmètre, comme en moitié A :** c-VEP, P300 et ErrP restent accessibles seulement par
l'appli pygame — le P300 et l'ErrP attendent les **marqueurs entrants**, le c-VEP un stimulus
verrouillé à la frame. La calibration pilotée par une app extérieure (F2) est rendue possible par
ce chantier, pas livrée. Le contrôle à distance d'une calibration depuis un client LSL non plus.

**Jamais vérifié au casque.** Tout ce chantier se code et se teste sans matériel. Sa recette
matérielle est le test 2.6 de [`docs/recette.md`](../../recette.md), mis à jour en tâche 7.
