# SDD ledger — plan: docs/superpowers/plans/2026-08-17-marqueurs-entrants-p300.md

Chantier « marqueurs entrants + P300 sur le réseau ». 7 tâches.
Travail directement sur `main` — workflow établi de l'utilisateur, pas de worktree.
BASE du chantier : `43a9807`.

## Pré-vol du plan (coordinateur, avant la tâche 1)

Un défaut trouvé dans mon propre plan et **corrigé avant tout dispatch** : la tâche 2 commitait une
assertion (`besoin > 0.0`) qui serait restée ROUGE jusqu'à la tâche 5. Les tâches 3 et 4 auraient
travaillé avec `server.py --smoke` en échec permanent — le meilleur moyen de cesser de regarder les
échecs. Corrigé en trois points :

- la tâche 2 n'assert plus qu'une **implication**, vraie à vide, donc la suite reste verte ;
- sa preuve rouge passe par une **mutation temporaire** (`marker_epoch_s=3.0` sur `raw.SPEC`), avec
  les trois sorties à coller au rapport ;
- l'assertion stricte migre en **tâche 5**, où elle devient vraie.

Commit du correctif : voir ci-dessous.

## Journal

### Task 1 — `core/markers.py` (MarkerInlet)

- Implémenteur : `ac5aa92f1afc029b7` (sonnet). BASE `4701a94`.
- **DONE** — commit `a1d24be`, 2 fichiers, 181 insertions. Autotest lancé **3 fois**, stable.
- L'implémenteur a trouvé et corrigé un vrai défaut de MON brief avant de le transcrire : la
  boucle de réception de l'autotest (`essais < 50`, sans pause) pouvait s'épuiser en moins d'une
  milliseconde, avant que LSL ait livré quoi que ce soit — test intermittent, pire qu'un test
  toujours rouge. Remplacée par une attente bornée dans le TEMPS. C'est le comportement qu'on
  encourage : signaler plutôt qu'appliquer à moitié.
- Revue (`a6d9f25b86e46fc9d`, sonnet, bornée au diff) : **spec ✅**, rien en plus, rien en moins.
  0 critique, **3 importants**, 4 mineurs.

**Task 1: fix round 1/5** — les 3 importants sont le même défaut décliné : des gardes que le brief
déclare centrales, qu'aucune assertion ne protège.
1. le TYPE de `mode`/`event` n'est jamais éprouvé — affaiblir `isinstance(..., str)` en test de
   présence passerait tous les tests ;
2. l'idempotence de `resolve()` n'est jamais exercée — la retirer ferait re-mesurer
   `time_correction()` à chaque appel, soit exactement le SAUT d'horodatage que le brief interdit ;
3. l'application de `self.offset` n'est pas prouvée — en mono-processus la correction vaut ~0,
   donc retirer `+ self.offset` ne casse rien.

⚠️ **Le relecteur a jugé le n°3 structurellement non corrigeable en mono-machine. C'est faux, et
c'est un arbitrage du coordinateur** : il n'y a pas besoin d'un vrai décalage d'horloge, il suffit
d'en INJECTER un (`inlet.offset = 12345.678`) et de vérifier que les horodatages rendus sont
décalés d'exactement ça. Consigne envoyée avec le code.

Preuve **rouge-puis-vert** exigée en toutes lettres pour les trois, plus le comptage d'assertions
avant/après.

**Task 1: minor (deferred)** — `json.loads` peut lever `RecursionError`/`MemoryError` sur un JSON
pathologiquement imbriqué, non couvert par `except (ValueError, TypeError)` (brèche théorique,
appli mal écrite ≠ adversariale) · `import time` non préfixé alors que `os`/`sys` le sont ·
`timeout_s=0.0`, le chemin que prendra le vrai appelant, n'est exercé par aucun test · la
disparition de l'émetteur en cours de séance est sûre **par construction** mais par aucun test.

Correction livrée : commit `ecfa67c`, diff strictement additif (+40/-0). Les trois preuves
rouge-puis-vert sont dans le rapport. Sentinelles bien choisies : `999.0` pour l'idempotence et
`12345.678` pour l'offset — deux valeurs qu'aucune vraie correction d'horloge mono-machine ne peut
produire, donc le code fautif n'a aucune chance de les rendre par hasard.

L'implémenteur a signalé de lui-même un **incident de méthode** : ses deux premiers essais de
relance finale sont partis EN PARALLÈLE (deux `StreamOutlet` de même nom en même temps, ce que le
projet interdit). Il a jugé les résultats non probants, les a écartés, et refait les trois passages
en séquentiel strict. Bon réflexe, à encourager.

Re-relecture (`ab45c4603427765b9`, sonnet, bornée au diff de correction) : **les 3 ADDRESSED**,
aucune casse nouvelle, et le comptage d'assertions **recompté indépendamment du rapport** —
15 → 22, +7 exactement, 0 ligne retirée ou modifiée.

**Task 1: complete (commits 4701a94..ecfa67c, review clean)**

### Task 2 — le tampon d'horodatages et le dimensionnement de `keep`

- Implémenteur : `a8a2e153549bf618f` (sonnet). BASE `ecfa67c`. **DONE** — commit `f30be3d`.
- Revue (`ad5387ce87ba217b1`, sonnet) : **spec ✅, 0 critique, 0 important**, 1 mineur.

⚠️ **DEUX erreurs de MON brief, trouvées par l'implémenteur en MESURANT, et confirmées par le
relecteur qui a refait le calcul de son côté :**

1. **La valeur de mutation prescrite (3,0 s) ne produisait aucun rouge.** `keep` vaut déjà 1250
   échantillons avant tout correctif, dominé par l'**époque de calibration MI (4,0 s)** héritée du
   chantier 3B — or une mutation à 3,0 s n'en exige que 1000. J'avais raisonné comme si le nouveau
   terme partait de zéro. Corrigé à 6,0 s → 1750 > 1250, rouge réel.
2. **L'étape 7 de mon brief prédisait un échec qui contredisait l'étape 2 du même brief.** La
   mesure donne raison à l'étape 2.

**Conséquence à retenir pour la suite du chantier** : le terme « époque de marqueur » n'est PAS
dominant aujourd'hui (0,95 + 1,0 = 1,95 s contre 4,0 s pour la calibration MI). L'assertion de
dimensionnement est donc satisfaite **par un autre terme** ; c'est la mutation qui prouve le
câblage, pas l'assertion. Le nommage garde tout son sens — il protège le jour où les autres termes
baissent — mais il ne faut pas croire que le vert prouve le câblage.

**Un vrai défaut préexistant corrigé au passage** : `_smoke()` combinait ses 11 sous-tests par un
`and` en cascade, **avec un commentaire qui l'assumait comme délibéré**. Le premier échec
court-circuitait tous les suivants. Remplacé par une collecte puis `all(...)`. Vérifié en
conditions réelles pendant la preuve rouge : le voisin d'après s'est bien exécuté malgré l'échec.
Le relecteur a recompté les sous-tests : 11 avant, 13 après, aucun perdu ni renommé.

**Task 2: minor (deferred)** — la même quantité porte deux noms, `epoque_marqueur` dans `__init__`
et `besoin` dans `_smoke_dimensionnement` (hérité verbatim de mon brief, sans impact).

**Task 2: complete (commits ecfa67c..f30be3d, review clean)**

### Task 3 — pré-vol du coordinateur AVANT dispatch

⚠️ **Troisième erreur de mon plan, et la plus grave des trois — trouvée avant tout dispatch.**
L'ordre des contrôles que je prescris dans `markers_murs` rend le compteur `marqueurs_futurs
INATTEIGNABLE, et pire : **un seul marqueur horodaté loin dans le futur COINCE la file pour
toujours.** Un marqueur futur n'est par définition jamais « mûr », donc il déclenche le `break`
avant tout autre contrôle — le curseur ne le dépasse jamais et tous les marqueurs suivants restent
bloqués derrière lui. Or c'est exactement ce que produit un `time_correction()` oublié entre deux
machines, c'est-à-dire le cas que ce compteur existe pour diagnostiquer.

Correction transmise dans le dispatch : **contrôler le futur AVANT la maturité**, jamais après.


### Task 3 — suite

Correction en 1 tour (`9fd3499`), les 6 constats traités, aucun contesté. Re-relecture
(`a8acd33ea554912a6`) : **les 6 ADDRESSED**, aucune casse, comptages recomptés indépendamment —
`resultats` 15→16, `chk(` 81→93, et les 29 lignes supprimées sont exactement le code relocalisé
dans `_ouvre_marker_inlet`/`_tire_marqueurs`/`_purge_marqueurs`, zéro assertion touchée.

⚠️ **Le critique n°1 était atteignable AUJOURD'HUI par le chemin d'usage normal** : le bouton
« Démarrer » de la console envoie `start_mode` pendant que la boucle tourne, et l'inlet n'était
créé qu'une fois AVANT la boucle. Un mode P300 démarré depuis la grille n'aurait jamais reçu un
seul marqueur, sans log ni compteur.

**Task 3: minor (deferred)** — conditions limites des compteurs testées loin de leur frontière ·
`marqueurs_perdus`/`marqueurs_futurs`/`marqueurs_inlet_erreurs` comptés mais jamais affichés ·
pas de reconnexion explicite si l'appli de stimulus est fermée puis relancée · une assertion
PRÉEXISTANTE de `_smoke_marqueurs_murs` indexe `m[1]["target"]` sans `.get`, donc casse par
`KeyError` au lieu d'échouer proprement sous mutation.

**Task 3: complete (commits f30be3d..1b48a5e, review clean)**

### Task 4 — le décodeur P300 déménage dans `core/`

- Implémenteur `a2c053c2e14aed276` (sonnet). **DONE** — commit `2ebf022`.
- Revue (`af9a9145c9f582f2e`) : **spec ✅, 0 critique, 0 important**, 1 mineur.

🎯 **Le résultat qui compte : AUC 0,7145659722 en validation croisée par manche, BIT POUR BIT
identique** à celle de l'ancien modèle, lue en lecture seule avant le déménagement. 576 époques,
96 cibles / 480 non-cibles. Le ré-entraînement reproduit exactement l'original — le pari du plan
(« ré-entraîner plutôt qu'écrire une passerelle ») est validé par la mesure, pas par l'espoir.
`data/p300_model.joblib` intact ; nouveau modèle `data/p300_model_20260817-135716.joblib`.

**Trois pièges que MON brief n'avait pas vus, trouvés par l'implémenteur :**
1. `_demo()` importait `research.itr` — la frontière `core/` aurait sauté au premier lancement.
   Remplacé par une réplique locale de Wolpaw, que le relecteur a vérifiée ligne à ligne contre
   l'original : identique, mêmes gardes.
2. `mode_p300` (app.py) et `p300_analyze.py` testaient le modèle par `os.path.exists()`, qui ne
   détecte pas « existe mais illisible ». Un étudiant choisissant « P300 → Lancer le live » sans
   recalibrer aurait eu un crash brut EN SÉANCE. Les deux passent maintenant par `charger()`.

⚠️ **Un constat du relecteur ÉCARTÉ après vérification** : il affirmait que `main` avait avancé
« sur un tout autre chantier — dashboard web ». Faux — `2ebf022` est le sommet, rien au-dessus, et
`src/core/dashboard.py` n'existe pas (supprimé le 2026-07-28). Il a lu des commits ANCÊTRES de
juillet. Vérifié avant de transmettre, comme la règle l'impose.

**Task 4: minor (deferred)** — le message de refus d'un chemin vide dans `p300_models.py` dit
« lance une calibration depuis la console », or la console n'a aucune page P300 (c'est l'appli
pygame). Copier-coller depuis `mi_models.py`, branche aujourd'hui inatteignable.
Aussi : `research/__init__.py` et le README listent encore le P300 comme « à migrer » → tâche 7.

**Task 4: complete (commits 1b48a5e..2ebf022, review clean)**

### Task 5 — le mode P300, son runtime et son flux

- Implémenteur `a35c8fc0ee271827e` (sonnet). **DONE** — commit `37dce0c` (+ `ec70ae7`, `7d927a1`).
- Diff de 46 Ko → **découpé en 2 tranches** relues EN PARALLÈLE (des relecteurs bornés à leur diff
  n'exécutent rien, donc c'est sûr) : A = le mode (31 Ko), B = le câblage (15 Ko).
- **Spec ✅ des deux côtés.** Les deux preuves rouge/vert de l'implémenteur ont été relues et
  jugées solides — celle de l'appariement `score_<i>` ↔ cible `i` en particulier : « n'importe quel
  tri, inversion ou décalage d'index y produirait une liste différente ».

**Task 5: fix round 1/5** — 1 critique, 3 importants.

⚠️ **CRITIQUE (tranche A) — l'accumulation des époques n'a ni borne ni notion de manche.** Si
`round_end` n'arrive jamais, les listes croissent sans limite. Et surtout : **les flashs d'une
NOUVELLE manche s'empilent sur les orphelins d'une manche avortée**. Le garde-fou de couverture ne
vérifie que « chaque cible a flashé au moins une fois », pas « ces flashs sont de la même
manche » — une contamination peut donc le satisfaire, atteindre `select()` et publier une cible
avec une confiance normale, **silencieusement fausse**. Aucune des cinq pannes ne se déclenche.
Correction demandée : un délai d'abandon (nouvelle constante `P300_ROUND_TIMEOUT_S`) ET un plafond
dur, les deux abandonnant la manche À VOIX HAUTE.

**IMPORTANT (A)** — la panne « cible hors plage » ne s'affiche qu'**une fois par SESSION**, jamais
par manche, et le compteur n'a aucune seconde sortie (absent de `state()`).

**IMPORTANT (B)** — le sens de `-1` n'est écrit que dans la docstring, **jamais dans les
métadonnées LSL**. `DecodedMIPublisher`, juste au-dessus dans le même fichier, pousse pourtant
`no_decision_index` dans son `desc()` avec le commentaire qui explique pourquoi. La docstring du
P300 cite cette leçon MOT POUR MOT sans appliquer le correctif concret. Un client Unity ou MATLAB
qui lit les métadonnées sans ouvrir le `.py` ne peut pas savoir que `-1` est une sentinelle.

**IMPORTANT (B)** — `stream_in` **ne fait rien** (confirmé par grep : `MARKER_STREAM_DEFAULT` en
dur dans `_ouvre_marker_inlet`, seule lecture du réglage = un `print`), et son texte d'aide
**surpromet** : « deux applications peuvent tourner sur le réseau sans se mélanger », capacité
inexistante. Réglage-décor — exactement ce que ce projet combat. Correction : le câbler, et dire
bruyamment si deux modes actifs déclaraient deux noms différents.

**Task 5: minor (deferred)** — branche `choisi is None` morte tant que `P300_SELECT_MARGIN` vaut 0 ·
le contrôle structurel de `registry.check()` n'a aucun test dédié (son jumeau `epoch_s`/`imagery_s`
n'en a pas non plus — **c'est un trou hérité, pas une régression**) · son message unique couvre deux
cas distincts là où le jumeau en distingue deux · un futur mode consommant des marqueurs sans
déclarer `pre_s`/`post_s` passerait `check()` sans alerte · le sens de `-1` manque aussi aux
métadonnées du SSVEP (lacune préexistante).

Correction livrée : `fec9b08`. Re-relecture **en 2 tranches parallèles** (`a340c93680fad331d` sur le
mode, `aea3f5f5f91a13998` sur le câblage) : **les 4 ADDRESSED**, aucune casse.

Ce que les re-relecteurs ont apporté au-delà de la vérification demandée :
- l'**indépendance des deux garde-fous** n'est pas seulement affirmée : le plafond se déclenche
  seul dans un scénario (96 époques en ~2 s, bien sous le délai de 10 s) et le délai se déclenche
  seul dans l'autre (3 époques, très loin du plafond). Les deux sens sont exercés.
- le test de contamination porte sur **le nombre d'époques par cible transmis au modèle**
  (`{0:2, 1:2, 2:2, 3:1, 4:1, 5:1}` sous mutation), recalculé à la main par le relecteur — il
  prouve la contamination elle-même, pas seulement « ça abandonne ».
- l'assertion de `stream_in` porte sur `marker_inlet.nom`, c'est-à-dire **le nom réellement passé
  à `resolve_byprop`**, pas une variable intermédiaire qu'un code fautif remplirait quand même.
- le choix en cas de conflit de noms est **déterministe** (`self.active` est un vrai `dict`, ordre
  d'insertion garanti depuis Python 3.7), pas un pari sur l'implémentation.

⚠️ **Limite documentée, assumée** : `stream_in` ne prend effet qu'au redémarrage du MOTEUR, pas du
mode — `marker_inlet` est mis en cache pour la vie du processus et `_stop_mode` ne le libère
jamais. Le texte d'aide dit exactement cette version stricte. Le correctif évident (libérer
l'inlet quand plus aucun mode marqueur n'est actif) est laissé au triage de la revue finale.

**Task 5: complete (commits 2ebf022..fec9b08, review clean)**

### Task 6 — l'émetteur de stimulus et LE test d'alignement

- Implémenteur `aa94d36a4e550cfd0` (sonnet). **DONE** — `d7d8060`, puis correction `47f7137`.
- Revue : spec ✅, 0 critique, **2 importants**, tous deux corrigés et re-relus ADDRESSED.

🎯 **La preuve d'alignement est le résultat qui compte du chantier entier.** Mutation
`pre_s=0.0` : le pic planté à l'onset atterrit à l'échantillon 0 au lieu de 38 — **décalage de
−152 ms** — et **les 46 assertions préexistantes restent TOUTES vertes**. C'est exactement la thèse
du plan : un désalignement ne se voit nulle part ailleurs.

⚠️ **Le constat le plus fin du chantier**, trouvé en relecture : le premier test d'alignement
appelle `epoch_from_stream` en direct, donc **ne passe jamais par `_encaisser_flash`**. Or inverser
les deux mots-clés à l'appel réel (`pre_s=self.post_s, post_s=self.pre_s`) ne change PAS la forme de
l'époque — `38 + 200 = 200 + 38` — donc tous les contrôles de forme et de bornes restaient verts.
Un second test passant par un vrai `rt.tick(...)` ferme le trou : à la mutation, le pic atterrit à
200 au lieu de 38 (+648 ms), exactement `round(P300_EPOCH_S × fs)` comme le relecteur l'avait prédit
par le calcul avant de le mesurer.

**Sixième erreur de mes briefs**, trouvée par l'implémenteur : je situais la mutation sur un littéral
`pre_s=P300_PRE_S` qui n'existe pas dans ce fichier (il utilise `self.pre_s`).

**Task 6: minor (deferred)** — la garde anti-répétition ne couvre que la jonction immédiate, pas un
espacement minimal plus large · les TOTAUX d'assertions annoncés dans les rapports T6 sont décalés
de 1 (la ligne `def chk(cond, msg):` matche la sous-chaîne) — **les deltas sont justes et rien n'a
été retiré**, c'est de la comptabilité.

**Task 6: complete (commits fec9b08..47f7137, review clean)**

### Task 7 — documentation (écrite par le coordinateur, sans sous-agent)

**complete** — commit `7358d3b`. `docs/markers.md` (contrat public des marqueurs, en anglais comme
`network.md`), plus README, SPEC §5 et §14, recette (tests **1.14** et **2.7** ajoutés), CLAUDE.md,
et la docstring de `src/research/__init__.py`.

---

## ⚠️ REPRENDRE ICI — pause demandée le 2026-08-17 en fin de journée

**Les 7 tâches de code et de doc sont TERMINÉES, relues, corrigées et re-relues.**
18 commits, `43a9807..47f7137`. Arbre propre. **NON POUSSÉ** (21 commits d'avance sur `origin/main`).

**Ce qui reste, et c'est la seule chose :** la **REVUE FINALE DE BRANCHE**. Elle était lancée en
7 tranches parallèles quand la pause est arrivée ; les 7 relecteurs ont été **arrêtés en phase de
lecture, avant tout constat** — donc rien n'est perdu, mais **rien n'est acquis non plus** : il faut
les relancer entièrement.

**Les 7 tranches sont déjà construites et prêtes**, dans ce dossier :

| Tranche | Fichier | Périmètre |
|---|---|---|
| A | `final-A.diff` (13 Ko) | `core/markers.py` + `core/config.py` — l'oreille |
| B | `final-B.diff` (39 Ko) | `core/server.py` — tampon, file, cycle de vie, smokes |
| C1 | `final-C1.txt` (25 Ko) | `core/modes/p300.py` lignes 1-375 — le runtime |
| C2 | `final-C2.txt` (30 Ko) | `core/modes/p300.py` lignes 376-854 — l'autotest |
| D | `final-D.diff` (24 Ko) | `core/p300_decoder.py` + `core/p300_models.py` |
| E | `final-E.diff` (17 Ko) | `lsl_io` + `contract` + `external` + `registry` + `runtime` + console |
| F | `final-F.diff` (36 Ko) | `research/` — stimulus autonome et recâblage |

⚠️ **Toutes sous 40 Ko**, la limite au-delà de laquelle les relecteurs meurent sur ce projet.
`p300.py` est découpé en deux parce qu'il est ENTIÈREMENT nouveau : le contexte du diff n'aide pas.

**La liste des mineurs reportés à trianger par la revue finale est dans ce journal**, tâche par
tâche, sous les entrées `minor (deferred)`.

**Après la revue** : UNE seule vague de correction (pas un correcteur par constat), UNE re-relecture
bornée, puis arbitrage des résidus. Ensuite : pousser, mettre à jour la mémoire projet, et
**annoncer le périmètre** — ce qui reste DEHORS est écrit dans la spec §2 et dans SPEC §14.

## REVUE FINALE DE BRANCHE (relancée le 2026-08-18) — constats au fil de l'eau

### Tranche E — contrat et câblage : 0 critique, 5 importants, 7 mineurs

1. ⚠️ **`server.py:29-31`** : la docstring d'en-tête du MOTEUR dit encore que le P300 n'y est pas ET
   que les marqueurs entrants n'existent pas. Les deux moitiés fausses. Aucun des 7 diffs ne touche
   cette ligne ; l'inventaire des flux publiés (l. 18-20) omet aussi `decoded_p300`.
2. ⚠️ **`external.py:39`** : le champ `unavailable` de l'ErrP contredit la docstring corrigée 3
   lignes plus haut. Et c'est le CHAMP que l'étudiant lit (`grid.py:129` le pose sur la tuile,
   `server.py:547` le ressort comme refus). Le fichier « point d'honnêteté » se contredit.
3. ⚠️ **`runtime.py:173-174`** : le commentaire d'orientation promet des marqueurs « MÛRS (leur
   époque tient dans le tampon) », or `markers_murs` ne vérifie que le côté POST. La fenêtre PRÉ
   peut être sortie — d'où `_epoques_perdues` dans p300. C'est le seul cahier des charges qu'aura
   l'auteur de l'ErrP : s'il le croit, il retire la garde et perd des époques en silence.
4. **`lsl_io.py:384`** : `reps` est la seule métadonnée qui décrive une chose que le moteur ne
   contrôle pas — c'est l'appli EXTERNE qui décide (`--reps`). À `--reps 12` les métadonnées
   annoncent 8. Soit la retirer, soit la publier comme un plafond.
5. **`console/app.py:479-481`** : compte en dur jumeau de celui déjà corrigé, et son message oublie
   déjà l'ErrP.

Mineurs : comptes en dur en prose (`external.py:3-4`, `console/app.py:271`, `app.py:91-93`) ·
`lsl_io.py:8-11` « trois flux au MVP » pour 7 publieurs · le P300 est le seul `decoded_*` sans
seuil/marge dans ses métadonnées · `"decoded_p300"` écrit DEUX fois (spec + littéral du publieur),
rien ne les lie.

**Triage des 4 reportés** : (1) test rouge du contrôle → 6 lignes, à faire · (2) message unique pour
2 cas → **à corriger**, le champ vaut 0.0 par défaut donc l'oubli EST le cas par défaut · (3) un
runtime à marqueurs sans `pre_s`/`post_s` passe `check()` muet → le plus grave, **le vrai correctif
est de DÉRIVER `marker_epoch_s` du runtime** au lieu de le redéclarer ; dette assumée · (4) `-1`
absent des métadonnées SSVEP → une ligne, à faire.

### Tranche D — décodeur et modèles : 0 critique, 3 importants, 6 mineurs

1. ⚠️ **`p300_decoder.py:245-247`** : `__main__` jette le verdict de `_demo()` — **sort TOUJOURS en
   0**. Le « exit 0 » du rapport de la tâche 4 ne prouve rien. Ses deux voisins dans `core/` font
   `sys.exit(0 if … else 1)`.
2. ⚠️ **`p300_models.py:196-201`** : **l'assertion sur laquelle repose TOUTE la décision de
   conception ne peut pas attraper son assouplissement.** `_ModeleEtranger.__module__` vaut
   `"__main__"`, jamais `"p300_decoder"` : la mutation vers `endswith("p300_decoder")` — la
   passerelle qu'un contributeur écrira — laisse les 16 assertions vertes pendant que le modèle
   abandonné redevient acceptable. Correctif : enregistrer un `types.ModuleType("p300_decoder")`
   dans `sys.modules` avant le dump, et asserter que la raison cite `p300_decoder`.
3. **`p300_models.py:96`** : `decrire(None)` LÈVE, alors que `charger` a été durcie pour ça avec
   une boucle dédiée et un commentaire « une exception ici remonterait jusqu'au fil Qt ». Le
   durcissement s'est arrêté une fonction trop tôt.

**Vérifié et solide** : frontière `core/` propre (regex du smoke rejouée) · **réplique de Wolpaw
identique bit pour bit sur 910 combinaisons, écart max 0.0** · tri sur `getmtime` · tests hors
`data/` · le disque conforme (juillet intact, nouveau modèle à côté) · aucune contamination ErrP
possible (composition, pas héritage ; motif de nom disjoint).

**Conséquences HORS tranche, à router :**
- ⚠️ **`research/p300_calibrate.py:231`** : la prochaine calibration **ÉCRASE
  `data/p300_model.joblib`**, la trace de juillet que mon message de commit affirme préserver.
  Rien n'applique l'invariant.
- **`research/app.py:1070`** : l'écran d'état annonce un modèle P300 présent alors que le seul
  fichier à cette adresse est l'abandonné — le reliquat exact du correctif appliqué à `mode_p300`
  et `p300_analyze`, oublié ici.
- `P300_MODEL_PATH` pointe sur un modèle définitivement refusé, alors qu'un valide est à côté.

**Triage du reporté** : **à corriger** — la phrase fautive est IMPRIMÉE trois fois par
`python src/core/p300_models.py`, commande prescrite par CLAUDE.md. Et le dépôt se contredit déjà
(le `help` du paramètre dit la bonne chose).

### Tranche C2 — l'autotest du mode P300 : 4 critiques, 6 importants

🔬 **LE constat du chantier, et il justifie à lui seul la revue finale :**
**`p300.py:833-842` — le test d'alignement « chemin réel » ne compare que la POSITION de l'argmax,
jamais le CONTENU.** `filtfilt` est à phase nulle, sa réponse impulsionnelle équivalente est une
autocorrélation maximale au lag 0 : **ajouter un `bandpass()` dans `_encaisser_flash` laisse le pic
exactement à l'échantillon 38**. Or `P300Model._prep` filtre déjà — donc **le DOUBLE FILTRAGE passe
cet autotest sans un mot**, c'est-à-dire la panne exacte contre laquelle ce projet a écrit un garde
dédié pour le MI (« double filtrage = bruit à p=0,99 »). Idem pour une correction de ligne de base
ou une conversion d'unité ajoutées là.
→ **Correctif d'UNE assertion qui en remplace trois** :
`chk(np.array_equal(rt._epoques[-1], eeg[i_pic - n_pre:i_pic + n_post]))` — épingle d'un coup
position, forme, ordre des voies et absence de traitement.

Trois autres critiques, tous « une assertion qui regarde la bonne chose UNE CASE TROP LOIN » :
- **`_cibles` n'est lu NULLE PART** dans les 478 lignes de test. Remonter son `append` au-dessus de
  la garde `if epoque is None` (édition d'une ligne) décale les deux listes et classe chaque flash
  sous la cible du précédent — cible fausse, confiance normale.
- **`_ModeleCapture` ne capture que des COMPTES** : une permutation pure des cibles survit,
  l'égalité de dict ignorant l'ordre. L'appariement est prouvé en SORTIE, jamais en ENTRÉE.
- **La branche `choisi is None` n'est exercée par aucun test** (`P300_SELECT_MARGIN=0` la rend
  structurellement inatteignable avec le vrai `select`) : la mutation `self._publish(0, ...)` est
  littéralement la confusion « -1 = la cible 0 » que toute la docstring combat.

**Une assertion que rien ne peut faire échouer** : `etat["refus_cible"] == rt._refus_cible` vaut
`0 == 0` à cet instant. Lire `state()` 20 lignes plus haut, où le compteur vaut 1.

Importants : `gagnant=1` est aussi l'argmax (2 mutations passent — prendre `gagnant=3`) · le test
« chemin réel » n'assert pas la FORME (une troncature passe, et explose 280 lignes plus loin en
traceback) · ⚠️ **la non-contamination n'est prouvée que pour un redémarrage PLUS LENT que le délai
de 10 s** — une appli qui repart dans les 10 s rafraîchit `_dernier_flash_ts`, les orphelins
s'empilent, et une cible fausse sort avec une confiance normale · `margin=P300_SELECT_MARGIN` n'est
vérifié nulle part · `-1 <= index` accepte la non-décision dans le seul test qui fait tourner le
VRAI décodeur.

**Solide, et le relecteur insiste** : les deux garde-fous d'abandon sont réellement indépendants et
chacun éprouvé SEUL (vérifié par le calcul) · le scénario `_refus_cible` est construit juste · cas
A/B distincts avec `_ModeleEspion` · appariement en sortie exemplaire · hygiène irréprochable —
**cet autotest ne peut ni publier sur LSL ni ouvrir de session BrainFlow**, donc aucun conflit
possible avec un moteur oublié.

### Tranche C1 — le runtime P300 : 3 critiques, 7 importants

1. ⚠️⚠️ **`p300.py:241` + `:71` — le plafond vaut EXACTEMENT deux manches, et la comparaison est
   stricte.** Manche normale = 48 époques, `_MAX_EPOQUES = 6×8×2 = 96`, et **`96 > 96` est FAUX**.
   Un seul `round_end` manquant colle deux manches complètes, **les deux garde-fous se taisent**,
   `select()` reçoit 96 époques dont la moitié porte l'intention précédente → cible plausible,
   confiance normale, silencieusement fausse. Trois manches (144) déclenchent bien : le garde
   attrape l'invraisemblable et rate le seul cas crédible.
   ⚠️ **Ce n'est PAS un `>=` à corriger** : un compteur GLOBAL ne peut pas à la fois tolérer un
   protocole à plus de 8 répétitions (mon intention écrite l. 68) et détecter deux manches soudées.
   Discriminant à prendre : **PAR CIBLE** (une cible vue plus de `P300_REPS` fois) ou **l'ÉCART**
   entre flashs consécutifs (SOA 150 ms contre une frontière de manche).
2. ⚠️ **`p300.py:169-184` — pendant les 15 s de CHAUFFE, personne ne consomme les marqueurs.**
   `markers_murs` n'est appelée que depuis `_run_step`. Le curseur ne bouge pas, puis le premier
   `_run_step` avale l'arriéré — tout ce qui dépasse le tampon (~4 s) part en `marqueurs_perdus`,
   **`round_end` compris**. L'émetteur flashe 2 s après son lancement et `markers.md` dit de le
   lancer à côté du moteur : **c'est le comportement PAR DÉFAUT de la première manche de chaque
   séance.** Idem à chaque « Refaire le repos ».
3. **`p300.py:256` — le plancher de manche vaut UNE répétition** (6 flashs) alors que le flux
   annonce `reps=8` et que la config situe le genou à 7-8. Et `_log` n'imprime `n_flashes` que sur
   les `-1` : une décision sur 6 flashs s'affiche EXACTEMENT comme une sur 48.

Importants : le modèle chargé n'est jamais confronté à `fs`/`pre_s`/`post_s` du runtime (jumeau du
contrôle structurel déjà rendu obligatoire ailleurs) · la décision est horodatée « maintenant »
alors que l'instant du `round_end` est dans la variable d'à côté (~1 s de retard, tombe dans la
manche suivante) · les `tick` de modes ne sont pas protégés alors que le tick de calibration l'est
· ⚠️ **deux des « pannes bruyantes » ne le sont pas** : `marqueurs_perdus`/`marqueurs_futurs` ne
sortent NULLE PART, et **`docs/markers.md` dit pourtant à l'étudiant « si ce nombre grimpe »** —
ma doc promet une observation impossible · une manche 100 % invalide est inabandonnable et la garde
anti-bruit redevient « une fois par session » · le refus par marge est le seul `-1` sans motif, et
`_log` lui en invente un FAUX · ⚠️ **`live_views.py` rend le P300 comme un SSVEP** (aiguillage sur
`"probas"`), donc 6 barres sans étiquette et « échelle z · seuil 3 » affiché AU-DESSUS de log-odds
— mot pour mot la panne que la docstring de cet écran dit avoir été écrite pour éliminer.

### Tranche F — research/ : 1 critique, 5 importants, 8 mineurs

1. ⚠️ **`p300_stimulus.py:192-227` — aucune pause ni signal visuel entre deux manches.** La
   frontière est visuellement identique à un intervalle inter-flash (83 ms). Or **ma recette §2.7
   demande « recommence six fois en changeant de cible »** : physiquement impossible — dès la 2e
   sélection les époques contiennent la transition du regard. **Les DEUX implémentations validées
   au casque ont cet écran** (`app.py:524` 2,2 s ; `p300_calibrate.py:65` 2,5 s) ; l'émetteur est
   le seul à l'avoir perdu.

Importants : **l'invariant anti-répétition n'existe QUE dans l'émetteur** — la calibration, seul
chemin vers un modèle, ne l'a pas (mesuré : **72,0 % des manches de calibration ont au moins une
répétition, 2,44 % des époques**) · ⚠️ **`app.py:1070` : 3e site du bug `os.path.exists`, non
recâblé** — le menu dit « P300 : oui » quand le moteur refuse (**convergence avec la tranche D**)
· **le `--smoke` n'exécute jamais `run()`** : les 90 lignes contenant le geste flip→horodatage que
ce fichier existe pour enseigner n'ont AUCUNE couverture (le patron `ssvep_stimulus` fait l'inverse
avec SDL dummy) · rien n'indique si le moteur écoute (`have_consumers()` existe et n'est pas
utilisé) · `--targets` accepté sans validation alors que le moteur code 6 en dur : `--targets 4`
tourne sans un mot et fait passer l'oddball de 1/6 à 1/4.

Mineurs notables : `--targets 0` → `IndexError` nu · `--targets 2` rend une séquence **parfaitement
alternée donc 100 % prévisible**, et le smoke dit OK · **le rayon du point de fixation est 3 contre
`FIX_DOT_R = 2`** — 2,25× la surface sous laquelle les données d'entraînement ont été enregistrées
· ESC en pleine manche n'émet pas de `round_end`.

**Vérifié SAIN par cette tranche** : l'horodatage est pris après `flip()` sur TOUS les chemins · les
deux fenêtres sont en `vsync=1` donc pas de biais d'une frame entre entraînement et runtime · le
SOA est compté en FRAMES des deux côtés avec la MÊME fonction de mesure · frontière propre, aucun
importeur de l'ancien chemin · séquence nominale correcte, pas de boucle infinie (max 21
re-mélanges sur 200 000 tirages du pire cas).

### Tranche B — le moteur : 1 critique, 5 importants

⚠️⚠️ **B-C1 — fermer puis RELANCER l'application de stimulus rend le moteur MUET pour le reste du
processus, en silence. MESURÉ.** Chaîne : l'inlet n'est re-résolu que `if not connecte` ; `connecte`
reste `True` à vie (rien ne remet `marker_inlet` à `None`) ; `StreamInlet` a `recover=True` donc
liblsl retente indéfiniment l'ANCIEN `source_id` ; et l'émetteur déclare son `source_id` PAR PID,
donc l'ancien ne revient jamais. Aucune exception (recover les avale), `marqueurs_inlet_erreurs`
reste 0, **et redémarrer le MODE n'y change rien**.
```
[B] emetteur #1 vivant : 13 marqueurs | [C] ferme : 1 | [D] #2 RELANCE : 0 -> MUET POUR TOUJOURS
[E] un inlet NEUF : 13  -> le flux #2 est bien present sur le reseau
```
🎯 **Invisible depuis une seule tâche** : il faut le `source_id` par PID (tranche émetteur) +
l'idempotence de `resolve()` (tranche A) + le cache d'inlet (tranche B). **C'est la justification
de la méthode.** Correctif : libérer `marker_inlet = None` dans `_stop_mode` quand plus aucun mode
n'écoute ; côté émetteur, un `source_id` STABLE (hostname) ferait marcher la reprise native de LSL.

Importants : `_marqueurs` croît sans borne dès que le dernier écouteur s'arrête (la garde est
l'inverse de sa propre docstring) · ⚠️ **l'ALIGNEMENT `recent`/`recent_ts` n'est prouvé NULLE PART**
— le seul contrôle est une égalité de LONGUEURS, qui ne détecte aucun décalage temporel et devient
vide dès que les tampons saturent (toujours, en séance) ; le test P300 travaille sur des tableaux
FABRIQUÉS. Mutation qui passe tout : `ts_lsl + 1.0/fs`. Correctif : asserter que la QUEUE des deux
tampons est exactement `srv.new_block` · **`_smoke_dimensionnement` ne peut PAS échouer** (488 vs
1250) — correctif : patcher `registry.MODES` avec `marker_epoch_s=30.0` · un cycle
`EngineServer ↔ ModeRuntime` reste vivant → le destructeur zombie du 2026-07-28 · **7 des 8 nouveaux
`EngineServer` sans `instance=`**, et `_smoke_tampon_horodate` FAIT TOURNER un moteur 3 s publiant
sous le même nom qu'une vraie console synthétique.

Requalifié : `m[1]["target"]` sans `.get` **n'est pas cosmétique** — la liste `resultats` est
construite EN AMONT, donc une exception fait sauter TOUS les sous-tests suivants, exactement le
court-circuit que le passage à `all()` venait de supprimer.

### Tranche A — l'oreille : 3 critiques, 3 importants — TOUT EST MESURÉ

⚠️⚠️ **A-C1 — `time_correction()` est appelé SANS timeout depuis la boucle du moteur.** Mesuré :
émetteur tué dans la fenêtre, avec `source_id` (ce que publie l'émetteur du projet) → **appel
TOUJOURS bloqué au bout de 26 s**, sans exception. `resolve()` étant appelé depuis `run()`, **le
moteur ENTIER se fige** : plus de `get_new_data()` (le tampon BrainFlow déborde), plus un seul flux,
y compris pour le SSVEP/neuro/MI qui tournaient à côté — et Ctrl-C ne peut pas interrompre un appel
C bloquant. Contredit la docstring de la classe : « Ne bloque jamais la boucle du moteur ».

⚠️⚠️ **A-C2 — `resolve()` n'est pas atomique** : `self.inlet` est affecté AVANT `open_stream()` et
`time_correction()`. Mesuré : émetteur SANS `source_id` (le défaut de LSL, donc l'émetteur d'un
étudiant) mourant dans la fenêtre → `LostError` en ~4 s. Deux issues, toutes deux mauvaises :
(a) au PREMIER appel, `server.py:830` appelle `resolve()` hors de tout `try` et `run()` n'a **aucun
`except`** → l'exception TUE la boucle ; en console le fil meurt et la fenêtre Qt reste gelée.
L'invariant « une appli cliente mal écrite ne doit jamais tuer le moteur » tombe. (b) en re-tentative,
l'objet reste `connecte=True` avec `offset=0.0` → **le moteur se croit connecté et n'applique PLUS
AUCUNE correction d'horloge** : la catastrophe des 45 jours, en silence total.

⚠️ **A-C3 — deux émetteurs du même nom : `minimum=1` puis `flux[0]`, sans un mot.** Mesuré : rend
l'un des deux (pas même le premier lancé) et ne lit que celui-là. Or les étudiants utilisent tous le
nom par défaut et LSL porte sur tout le réseau → un moteur peut épocher sur les flashs du VOISIN et
publier des sélections confiantes et fausses. **Le projet a déjà le motif inverse côté sortant**
(`minimum=32` puis filtre `source_id`) : l'oreille est le seul endroit qui ne l'applique pas.
Mesuré : `minimum=32, timeout=0.2` révèle les deux en 0,2 s.

Importants : `illisibles` compté et lu par PERSONNE (**convergence A + B + C1** sur les compteurs
jamais exposés) · **le message « connecté » est sur le chemin qui n'aboutit presque jamais** —
mesuré, `resolve_byprop(timeout=0.0)` échoue aux premiers appels d'un processus neuf (0/5), puis
marche ; or la re-tentative qui connecte réellement **n'imprime rien** · un inlet perdu ne redevient
jamais « non connecté » : 310 exceptions en 20 s, une ligne imprimée 20×/s sans limitation, et
surdité définitive même après redémarrage de l'appli.

Mineurs : **l'autotest est intermittent sur son propre invariant** (attend 2 marqueurs puis vérifie
`illisibles == 1`, alimenté par un 3e encore en vol) — exactement ce que son propre commentaire
interdit · `UnicodeDecodeError` hors de la garde · `MARKER_LATE_S` documenté comme tolérance de
RETARD mais utilisé comme tolérance de FUTUR.

## VAGUE DE CORRECTION (2026-08-18) — 3 lots, puis re-relecture

**3 lots séquentiels** (ils lancent des smokes) : `b48bceb` l'oreille et le moteur · `f68e657` le mode
P300 et son autotest · `e530b8c` la vérité affichée et l'émetteur.

**Assertions** : 123→166 (lot 1), 52→87 (lot 2), 133→159 + 6 `assert` neufs (lot 3). **Aucune
retirée**, vérifié par AST à chaque lot et recompté indépendamment par les re-relecteurs.

**19 autotests relancés par le coordinateur : 0 échec, aucun processus résiduel.**

### Deux défauts trouvés par les CORRECTEURS, que la revue avait manqués

1. ⚠️ **`open_stream()` était non borné lui aussi** — la revue n'avait vu que `time_correction`.
   Mesuré : émetteur résolu puis tué, l'ancien code bloque **plus de 400 s** (mesure interrompue),
   là où la revue citait 26 s. Et borner à 0,2 s **aurait cassé la connexion** : le premier appel
   coûte 0,44-0,64 s sur un émetteur vivant. D'où 2,0 s.
2. ⚠️ **`0.15 + 0.80` vaut `0.9500000000000001`** : `registry.check()` déclarait donc en défaut un
   `marker_epoch_s=0.95`, **la valeur juste**. Le P300 y échappait PAR HASARD en réécrivant la même
   expression des deux côtés. Tolérance de 1 ns posée sur les DEUX comparaisons de durées.

### Re-relecture — 6 tranches sur 9 rendues, 3 tuées par la limite de session

**Rendues, toutes ADDRESSED, aucune casse** : l'oreille · le moteur · le code de production du P300
· la 1re moitié de son autotest · le cœur et les métadonnées · la console.

Points notables des re-relecteurs :
- l'oreille : les 22 assertions d'avant se retrouvent **verbatim** dans les 40, vérifié ligne à ligne.
- le moteur : les 25 appels `EngineServer(` portent désormais `instance=` ; les 3 `m[1]["target"]`
  sont tous en `.get`, et les 3 lignes retirées sont exactement celles-là, réécrites.
- la console : **plus aucun identifiant de mode dans le code exécutable de l'affichage** — diverger
  du moteur devient structurellement impossible. Les deux comptes en dur comparent maintenant des
  IDENTITÉS au registre.
- le cœur : le faux module doit être dans `sys.modules` **au dump ET au chargement** (`pickle`
  résout via `__module__`) — précision qui a changé le correctif.

**Non re-relues par un agent** (limite de session) : l'émetteur, la documentation, la 2e moitié de
l'autotest P300. ⚠️ **Le coordinateur a vérifié lui-même les points clés** et les donne pour ce
qu'ils sont — une vérification par lecture, pas une relecture indépendante :
pause de **2,5 s** calée sur les deux écrans validés au casque, avec visuel dédié · anti-répétition
passée dans la calibration ET le live pygame · `os.path.exists` remplacé au 3e site · l'invariant du
modèle de juillet tenu par une **assertion** · le smoke exécute `run()` sur `SDL_VIDEODRIVER=dummy`
· `wait_for_consumers` + « PERSONNE n'écoute » dans le HUD · `--targets`/`--reps` refusés en nommant
la constante · la doc donne TROIS endroits où lire les compteurs.

### RÉSIDUS PARKÉS, avec leur arbitrage

Aucun n'est porteur : rien en aval ne construit dessus, et aucun ne casse à l'exécution.

1. ⚠️ **Le message d'abandon du P300 accuse « round_end jamais reçu (application externe
   plantée ?) » même quand la cause est un `--reps` légitimement > 8.** Le nom de la constante est
   là, mais le diagnostic pointe la mauvaise piste, à chaque manche. **Ruling : réel, une ligne de
   texte, à corriger — mais la règle du dispositif est UNE seule vague de correction, et ce n'est
   pas porteur.** Le plus rentable des cinq résidus.
2. **La limite connue de la contamination (redémarrage sous 10 s + manche courte) est honnête dans
   le rapport mais ABSENTE du code** : la docstring du garde-fou se lit comme une garantie
   complète. Ruling : réel, trompeur pour le prochain lecteur, non porteur.
3. **Le compromis de `_dernier_flash_ts` n'est pas écrit non plus** : un émetteur qui n'envoie que
   des cibles hors plage repousse indéfiniment l'horloge d'abandon. Ruling : idem.
4. **L'échelle des barres P300 de la console est RELATIVE** : la plus faible est toujours vide, la
   plus forte toujours pleine, même quand l'écart réel est de 0,01. Un étudiant pressé y lirait une
   certitude qui n'existe pas. Ruling : réel, à traiter avec le lot d'affichage déjà reporté.
5. **Le pire cas des timeouts est ~4 s, pas 2 s** (`open_stream` puis `time_correction`, séquentiels
   sous le même `try`). Borné, sans commune mesure avec les 400 s d'avant. Ruling : acceptable, à
   ne pas présenter comme « 2 s » dans un futur rapport.
6. Mineur : une assertion auto-référentielle sur `_channels` (la fonction testée est un passe-plat
   d'une ligne, surface de mutation minuscule).

### DETTE DE CONCEPTION, écrite et assumée

**`marker_epoch_s` reste une seconde source de vérité.** Un futur mode à marqueurs qui oublierait
le champ passerait `registry.check()` sans un mot, et le moteur n'ouvrirait jamais d'inlet — le mode
tournerait sans rien publier. Le vrai correctif est de **DÉRIVER `marker_epoch_s` de
`runtime_cls.pre_s + runtime_cls.post_s`** au lieu de le redéclarer. C'est un changement de contrat,
donc un chantier, pas une fin de revue. Le premier exposé est nommé : **l'ErrP**.
