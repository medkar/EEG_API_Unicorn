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

