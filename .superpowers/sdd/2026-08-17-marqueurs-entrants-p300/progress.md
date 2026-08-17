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
