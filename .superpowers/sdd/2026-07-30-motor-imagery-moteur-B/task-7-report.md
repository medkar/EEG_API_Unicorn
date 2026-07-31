# Task 7 Report: l'archivage et la documentation

## Statut
**DONE** — les douze commandes de l'étape 7 sortent toutes en 0, plus deux vérifications
supplémentaires (`config.py`, et une reprise chronométrée des deux smokes `archive/`). Quelques
écarts au brief, tous des AJOUTS de correction motivés et documentés ci-dessous (jamais des
raccourcis) ; une coquille triviale dans le corps du message de commit, laissée en l'état plutôt
que d'amender (règle explicite « toujours un nouveau commit »).

## Commit
`e004958` — *Retire the pygame MI screens to archive/, and say so everywhere*
(parent `5aca940` — fin de la tâche 6 et son tour de correction, HEAD de `main` au moment du
travail). 12 fichiers, +209/-160.

## Ce qui a été fait, fichier par fichier

### `archive/` (créé)
- `archive/README.md` — contenu copié du brief, verbatim (tableau des deux fichiers, commandes
  `--smoke`, avertissement sur l'écrasement `data/`).
- `git mv src/research/mi_calibrate.py archive/mi_calibrate.py` puis deux retouches :
  1. `sys.path.insert` remplacé par la forme qui vise explicitement `<dépôt>/src` (donnée par le
     brief).
  2. Les **4 lignes d'usage du docstring** (`python src/research/mi_calibrate.py ...`) changées en
     `python archive/mi_calibrate.py ...` — **pas demandé littéralement par le brief** (qui ne
     listait que les deux retouches ci-dessus comme nécessaires à l'EXÉCUTION), mais sans ça le
     docstring du fichier archivé pointe vers un chemin qui n'existe plus plus. Aucun import
     `research.*` à corriger : ce fichier n'en avait aucun.
- `git mv src/research/mi_pilot.py archive/mi_pilot.py` puis :
  1. Même correctif `sys.path`.
  2. Mêmes **5 lignes d'usage** du docstring corrigées.
  3. `import research.mi_calibrate as mi_calibrate` → `import mi_calibrate` (les deux fichiers
     étant désormais dans le même dossier `archive/`, sur `sys.path` par défaut).
  4. `from research.ssvep_stimulus import arrow_polygon` **laissé INCHANGÉ** : ce module n'a pas
     déménagé, il reste dans `src/research/`, atteignable parce que `src/` est sur `sys.path`
     (fixé au point 1). Vérifié par `grep -n "^from research\|^import research"` avant et après.

### `src/research/app.py` (modifié — 6 modes → 5)
- Docstring de module : « six modes » → « cinq modes », « quatre voies » → « trois voies », le
  bloc `[2] MI` retiré, `c-VEP`/`P300` renumérotés `[2]`/`[3]`, et un paragraphe ajouté disant où
  le MI est parti (moteur + console) et où son écran d'origine est archivé.
- Import de `core.config` : `MI_KEY_CHANNELS`, `MI_MODEL_PATH`, `MI_PROB_MIN`, `MI_WINDOW_S`
  retirés — vérifié par `grep` qu'aucun des quatre ne sert plus ailleurs dans le fichier une fois
  `mode_mi`/`_mi_decode` supprimés (le brief ne citait que les deux premiers, mais les deux
  derniers devenaient tout aussi morts).
- `_arrow_painter` et `_live_loop` : les deux docstrings mentionnant « SSVEP et MI » corrigées en
  « SSVEP » (pas listé par le brief, mais directement adjacent au code supprimé et devenu faux).
- Fonctions `_mi_decode` et `mode_mi` supprimées entièrement ; les commentaires `# --- Mode 3 : ...`
  à `# --- Mode 6 : ...` renumérotés `Mode 2` à `Mode 5` (y compris le docstring de `mode_errp`,
  « Mode 6 » → « Mode 5 ») — pas explicitement demandé, mais un trou de numérotation (Mode 1, 3, 4,
  5, 6) aurait lu comme une erreur pour un étudiant, ce que le projet demande explicitement d'éviter.
- `calib_mi` supprimée. `_status` : ligne d'état MI retirée. `home()` : entrée « Motor Imagery »
  retirée du menu, docstring et tuple de retour mis à jour (5 valeurs). `PAGES` : clé `"mi"` retirée.
- `_smoke()` : import `_dummy_model`, `mi_path`, écriture du modèle factice et appel `mode_mi`
  retirés ; boucle de nettoyage et message de sortie mis à jour (plus de « + MI »).
- `_parse()` : description argparse, `/ MI` retiré.

### `src/research/__init__.py` (modifié — hors liste du brief)
« menu, 6 modes » → « menu, 5 modes » ; paragraphe ajouté disant que `mi_calibrate.py`/
`mi_pilot.py` ont quitté ce dossier pour `archive/`. Pas dans la liste de fichiers du brief, mais
c'est le docstring de PAQUET qui décrit `research/` — il affirmait un compte de modes désormais
faux.

### `src/core/mi_decoder.py` (modifié, conforme au brief §Step 5)
- Ligne 1-2 : vocabulaire d'actionneur (« 2 commandes », « stop fiable ») reformulé en « deux
  classes de mouvement imaginé […] distinguer un repos réel d'une simple absence de décision ».
- Ligne 5 : `[src/research/mi_calibrate.py]` → `[src/core/modes/mi_calib.py]`.
- Ligne 39 : `MI_CONTROL = (...)  # commandes réelles` → `# classes actives (hors REPOS)`.
  **`MI_CONTROL` NON renommé**, comme demandé — mais voir Écarts : la justification du brief
  (« `archive/mi_pilot.py` l'importe ») s'est révélée fausse au `grep`.
- Docstring de `MIDecoder.classify` : le paragraphe « reste utilisée par l'appli pygame
  (`research/app.py`, `mi_pilot.py`) » remplacé par le texte donné par le brief, verbatim :
  « n'est plus utilisée que par `archive/mi_pilot.py`. Le moteur, lui, passe par `scores()` : voir
  `core/modes/mi.py`. »

### `src/core/config.py` (modifié)
- Ligne 238 : `MI_PROB_MIN = 0.60  # proba mini pour émettre une commande (sinon None = stop)` →
  `# proba mini pour retenir une classe active (sinon None = indécis/repos)`.
- Ligne 254 : **écart mineur** — `MI_MIN_VOTES = 3  # votes concordants requis pour émettre une
  commande` a le MÊME défaut (vocabulaire d'actionneur), non cité par le brief (qui ne pointait que
  la ligne 238) ; corrigée en `# votes concordants requis pour retenir une classe active` par
  cohérence directe.

### `src/core/modes/mi_calib.py` (modifié — hors liste du brief)
Docstring de module : « qui vit aujourd'hui dans l'écran pygame `src/research/mi_calibrate.py` » →
« dans l'écran pygame désormais archivé (`archive/mi_calibrate.py`) », et « L'écran pygame
affiche » → « L'écran pygame archivé affiche ». Pas dans la liste du brief, mais directement
rendu faux par le déplacement (chemin qui n'existe plus, temps présent inexact).

### `CLAUDE.md` (modifié)
« menu à 6 modes » → 5 ; paragraphe sur la calibration MI réécrit (elle se lance depuis la console,
plus « vit encore dans l'appli pygame — moitié B du chantier 3 », mention de `archive/`) ;
`python src/research/mi_calibrate.py` retiré des commandes utiles, remplacé par un commentaire ;
« appli : menu + les 6 modes » → 5 ; deux nouveaux autotests ajoutés aux gardes MI
(`core/modes/calibration.py`, `core/modes/mi_calib.py`), « trois gardes » → « cinq gardes ».

### `README.md` (modifié)
- Section console : ajout de deux paragraphes (Start/Stop par tuile ; bouton Calibrate qui joue
  toute la calibration dans la même fenêtre).
- Section Motor Imagery : phrase d'entraînement réécrite (console → bouton Calibrate → CV honnête
  par essai) au lieu de `python src/research/mi_calibrate.py`.
- Paragraphe « The pygame app » : la fausse affirmation « it also still owns MI calibration »
  retirée, remplacée par « Motor Imagery has fully moved out of it » + un paragraphe sur
  `archive/` (ce qu'il contient, pourquoi, l'avertissement d'écrasement).
- Tableau des familles `research/` : `mi_calibrate` retiré de la ligne Calibrations ; « six modes »
  → « five modes » sur la ligne pygame app.
- Section Layout : nouvelle sous-section `### archive/` (hors liste du brief, mais le README est un
  des quatre fichiers explicitement visés et `archive/` n'était mentionné nulle part — un lecteur
  du README n'aurait eu aucun moyen d'apprendre son existence, l'argument même de
  `archive/README.md`).

### `docs/SPEC.md` (modifié)
- §14 : l'item « [à faire — chantier 3, moitié B] » remplacé par « [fait 2026-07-31 — chantier 3,
  moitié B] », décrivant calibration jouée par le moteur, CV honnête (≈ 40 % normal), horodatage,
  archivage, et la conséquence non livrée (F2 devient atteignable).
- **Deux écarts, hors §14** trouvés au `grep` du fichier entier : ligne ~91, « le P300 et le MI y
  sont validés sur casque » (dans l'explication de ce que `research/` veut dire) → « le P300 et le
  c-VEP », parce que le MI n'est plus DU TOUT dans `research/` sous quelque forme que ce soit ;
  et la note du roadmap v1 (§10), « la calibration reste native pygame, cf. §14 moitié B » →
  « calibration native ajoutée au moteur le 2026-07-31 » (l'ancienne note anticipait justement ce
  chantier — elle est maintenant vraie).

### `docs/recette.md` (modifié)
- Niveau 0 : deux lignes ajoutées (`calibration.py`, `mi_calib.py`) ; « 6 modes » → 5 ; « trois
  lignes MI » → « cinq lignes MI ».
- Niveau 1, préambule : le point 1 (« La console ne démarre pas un mode ») réécrit pour annoncer
  la capacité Démarrer/Arrêter — **explicitement demandé par la consigne de tâche** (pas par le
  brief lui-même), qui prévenait que README et recette devaient en tenir compte.
- Nouveau test **1.13 — Démarrer / arrêter un mode depuis la grille**, ajouté en FIN de niveau 1
  (pas inséré au milieu, pour ne renuméroter aucun test existant) : réutilise la session déjà
  ouverte du test 1.7 (Lancement B), arrête/redémarre Neuro depuis la grille, vérifie la
  disparition/réapparition du flux, et confirme que la tuile MI n'est jamais grisée.
- Test **2.6** réécrit en profondeur : un seul programme (plus de bascule pygame ↔ console),
  bouton Calibrer sur la page, accuracy honnête à 3 classes (≈ 40 % normal, hasard 33 %) au lieu
  de l'ancien cadrage « 63 % à deux classes », et un paragraphe final sur `archive/mi_calibrate.py`
  comme outil de comparaison volontaire (pas un chemin de routine).
- Section finale « Ce que cette recette ne teste pas » : le point « La console ne démarre pas un
  mode » retiré (devenu faux, remplacé par le test 1.13).

## Écarts par rapport au brief

Tous listés ci-dessus à l'endroit où ils ont eu lieu ; résumé du RAISONNEMENT commun : chaque écart
est une correction supplémentaire découverte en cherchant méthodiquement (`grep` sur des motifs
larges : `MI`, `mi_calibrate`, `mi_pilot`, `6 modes`, `research`) plutôt qu'un raccourci pris sur
ce que le brief demandait. Deux méritent un mot de plus :

1. **`MI_CONTROL` : la justification du brief était fausse.** Il écrit « Ne pas renommer
   `MI_CONTROL` : `archive/mi_pilot.py` l'importe. » — j'ai vérifié par `grep -n "MI_CONTROL"` sur
   tout le dépôt : `mi_pilot.py` importe `MI_LABELS, MIDecoder, MIModel` depuis `core.mi_decoder`,
   jamais `MI_CONTROL`. La consigne (ne pas renommer) était de toute façon ce que j'allais faire
   — je n'ai touché QUE le commentaire suivant la constante — donc aucun impact réel, mais la
   prémisse ne tenait pas et je préfère le dire que le laisser passer sans commentaire.
2. **Une coquille dans le corps du message de commit** (« the roadmap markng chantier 3 » au lieu
   de « marking ») — repérée après coup. Pas corrigée : la consigne du harnais est explicite
   (« Always create NEW commits rather than amending, unless the user explicitly requests a git
   amend »), et il n'y a pas d'autre façon propre de corriger un message de commit sans amend ni
   rebase interactif (également interdit). Le sujet du commit, lui, est correct et lisible.

## Ce que j'ai cherché sans trouver de mention fausse

- `docs/robot_testbed.md` et `examples/` : `grep` sur « Motor Imagery », `mi_calibrate`, `mi_pilot`
  — zéro occurrence, rien à corriger.
- `src/research/mi_compare.py` : confirmé par la consigne de tâche ET par le `grep` initial (déjà
  `import core.mi_decoder`) — non rouvert, rien à y faire.
- `docs/superpowers/plans/*.md` et `docs/superpowers/specs/*.md` : contiennent plusieurs mentions
  « 6 modes » / `src/research/mi_calibrate.py` désormais fausses SI on les lit comme des
  affirmations au présent. **Délibérément non touchés** : ce sont des documents de planification
  datés (comme un commit), pas de la documentation vivante — la convention du projet lui-même est
  de ne jamais réécrire l'histoire (`docs/SPEC.md` §12.2 garde intégralement décrite l'ancienne
  conception du tableau de bord web après son abandon, « Les deux restent ici volontairement »).
  Les réécrire aurait déformé ce qui était vrai/prévu au moment où ils ont été écrits.
- `src/core/config.py` en entier (au-delà des lignes 238/254) : relu pour d'autres mentions
  d'« actionneur »/« commande » dans le bloc MI (lignes 235-259) — aucune autre trouvée.

## Commandes de test lancées, EN SÉRIE, avec leur sortie réelle

### Les douze commandes de l'étape 7 (ordre du brief)

**1. `python src/core/modes/contract.py`** — `[contract] VERDICT : OK`, `EXIT: 0`, zéro `ÉCHEC`.

**2. `python src/core/modes/calibration.py`** — `[calibration] VERDICT : OK`, `EXIT: 0`.

**3. `python src/core/modes/mi_calib.py`** — `[mi-calib] VERDICT : OK`, `EXIT: 0`. Extrait :
```
[mi-calib] accuracy HONNÊTE (validation croisée par essai) : 45.0% — hasard 33% — UTILISABLE
[mi-calib] (pour mémoire, la CV naïve, fenêtres mélangées : 49.3% — gonflée, ne pas s'y fier)
...
  OK   les verdicts sont calés sur l'échelle HONNÊTE : 40 % n'est pas « utilisable »
```

**4. `python src/core/mi_decoder.py`** — `EXIT: 0`. Extrait :
```
méthode  | CV 5-fold | G/D test | repos->None
csp      |    88.8% |   86.1% |    88.9%  <- défaut
[mi] classifieur csp validé.
```

**5. `python src/core/mi_models.py`** — `[mi-models] VERDICT : OK`, `EXIT: 0`.

**6. `python src/core/modes/mi.py`** — `[mi] VERDICT : OK`, `EXIT: 0`. Confirme au passage le texte
d'aide affiché sans modèle : « […] Lance une calibration depuis cette console : bouton « Calibrer »
sur cette page. » — corrobore indépendamment ce que j'ai écrit dans README/CLAUDE.md/recette.

**7. `python src/core/acquisition.py --synthetic`** — `EXIT: 0`, pas de ligne VERDICT (normal,
documenté). Extrait, l'invariant central du sous-système :
```
  OK   la fenêtre MI fait 2 s sur les 8 voies ((500, 8))
  OK   et elle rend le signal TEL QUEL : le modèle applique son propre CAR et son passe-bande
```

**8. `python src/core/server.py --smoke`** — `EXIT: 0`, neuf lignes `VERDICT : OK` (`smoke`,
`smoke-frontiere`, `smoke-repos`, `smoke-ssvep`, `smoke-neuro`, `smoke-mi`, `smoke-calib`,
`smoke-cumul`, `smoke-proposition`).

**9. `python src/console/app.py --smoke`** — `[console-smoke] VERDICT : OK`, `EXIT: 0`. Confirme
indépendamment le formulaire de calibration et la commande `start_calibration`.

**10. `python src/research/app.py --smoke`** — `EXIT: 0`. Dernière ligne :
```
[app] smoke OK : menu + SSVEP + c-VEP (eCCA & rCCA) + P300 + neuro + ErrP(cal+démo) câblés (headless).
```
(plus de « + MI » — vérifie le retrait du menu par la sortie du programme, pas seulement en
lisant le code).

**11. `python archive/mi_calibrate.py --smoke`** — `EXIT: 0` :
```
[mi-cal] session=court  2/classe  ≈ 1 min  (imagerie 2.5s, fenêtre 2.0s)
[mi-cal] smoke OK : UI + enregistrement + découpage câblés (pas d'entraînement).
```

**12. `python archive/mi_pilot.py --smoke`** — `EXIT: 0` :
```
[mi-pilot] classes=['GAUCHE', 'DROITE', 'REPOS'] méthode=csp fenêtre=2.0s vote=3/5 UDP=off (feedback seul)
[mi-pilot] smoke OK : décodage + feedback + envoi câblés (headless).
```

Les douze en sortie 0, EN SÉRIE (jamais deux à la fois), exactement comme le Step 7 l'exige.

### Vérification supplémentaire, hors liste (fichier touché mais pas listé à l'étape 7)

**`python src/core/config.py`** — `[config] VERDICT : OK`, `EXIT: 0` (dix `OK`, zéro `ÉCHEC`) :
vérifie que les deux commentaires reformulés (lignes 238, 254) n'ont cassé ni la syntaxe ni le
comportement du module.

## Vérification d'absence de résidu

Après les deux premiers smokes `archive/` (avant le reste des retouches) :
```
$ git status --short
RM src/research/mi_calibrate.py -> archive/mi_calibrate.py
RM src/research/mi_pilot.py -> archive/mi_pilot.py
?? archive/README.md
```
Rien d'autre — les écritures dans `data/mi_model.joblib` / `data/mi_calib_last.npz` (attendues,
documentées) n'apparaissent pas : `data/` est gitignoré.

Avant `git add`, une fois TOUT le travail fait :
```
$ git status --short
 M CLAUDE.md
 M README.md
RM src/research/mi_calibrate.py -> archive/mi_calibrate.py
RM src/research/mi_pilot.py -> archive/mi_pilot.py
 M docs/SPEC.md
 M docs/recette.md
 M src/core/config.py
 M src/core/mi_decoder.py
 M src/core/modes/mi_calib.py
 M src/research/__init__.py
 M src/research/app.py
?? archive/README.md
```
Exactement les 12 fichiers attendus (2 déplacés, 1 créé, 9 modifiés), rien de plus. Après
`git add -A` puis `git commit` : `git status --short` vide, `git log --oneline -1` confirme
`e004958`.

## Auto-relecture

1. **Les fichiers archivés sont vraiment exécutables, pas juste « en apparence ».** Testés deux
   fois : une première fois isolément juste après les retouches (avant tout le reste du travail),
   une seconde fois dans le run complet de l'étape 7 à la fin — les deux fois en sortie 0, avec un
   `sys.path` qui vise `<dépôt>/src` depuis leur NOUVEL emplacement, pas depuis l'ancien.
2. **Aucun import mort laissé dans `app.py`** : `grep` final sur `MI|mi_|Motor Imagery|mode_mi|
   calib_mi` après toutes les retouches — les seules occurrences restantes sont le paragraphe
   deliberate sur le MI parti, et des faux positifs de sous-chaîne (`CVEP_MIN_VOTES`,
   `P300_MIDLINE`, `ERRP_MIDLINE`, qui contiennent « MI »/« MID » par coïncidence).
3. **Les affirmations sur la console n'ont pas été inventées.** Je n'ai lu NI `src/console/
   calib_page.py` NI `src/console/app.py` (consigne explicite — un autre agent les relit). Ce que
   j'écris sur le bouton Calibrer et Démarrer/Arrêter s'appuie sur trois sources indépendantes
   de la consigne de tâche : le texte d'aide RÉEL imprimé par `python src/core/modes/mi.py`
   (« bouton « Calibrer » sur cette page »), la sortie RÉELLE de `console/app.py --smoke`
   (`start_calibration`, formulaire de calibration), et les messages des deux commits parents
   (`95a62de` *Start and stop a mode from the console, instead of relaunching it* et `bf586c9`
   *Give the console a calibration page: brief, run, honest result*). Limite honnête : la
   formulation précise de certains libellés d'interface (ex. « Modèle entraîné » propose le
   fichier « en tête de liste ») vient du CONTRAT (`mi_models.py`, « le plus récent en tête »,
   vérifié par son propre test) plutôt que d'un examen pixel par pixel de l'écran — cohérent avec
   ce que je pouvais vérifier sans toucher aux deux fichiers interdits.
4. **La date utilisée dans les docs (2026-07-31) n'est pas inventée** : confirmée par l'horodatage
   RÉEL des fichiers produits par `mi_calib.py` pendant les tests (`mi_model_20260731-*.joblib`).
5. **Rien n'a touché aux deux fichiers hors-limites.** `git status` final ne montre ni
   `src/console/calib_page.py` ni `src/console/app.py`.
6. **Le chiffre « ≈ 40 % à 3 classes » documenté partout (CLAUDE.md via recette, README, SPEC,
   recette) est le même chiffre que celui qu'affiche RÉELLEMENT `mi_calib.py` en conditions
   comparables** (45,0 % et 41,7 % mesurés sur les runs synthétiques ci-dessus, du même ordre que
   le 40,0 % de référence cité) — pas une valeur recopiée sans vérification.

## Résumé des tests (une ligne)
14 commandes lancées EN SÉRIE (les douze de l'étape 7 + `config.py` + une reprise chronométrée des
deux smokes `archive/`), toutes en exit code 0 / `VERDICT : OK`, zéro `ÉCHEC` ; `git status` propre
après commit `e004958` (aucun résidu hors des 12 fichiers attendus, rien dans `data/` remonté —
gitignoré comme prévu).
