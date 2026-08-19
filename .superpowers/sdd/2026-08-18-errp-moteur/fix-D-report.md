# Tranche D — correctifs : `errp_stimulus.py`, `research/__init__.py`

Périmètre tenu : **2 fichiers modifiés**, `src/research/errp_stimulus.py` (+391/−65) et
`src/research/__init__.py` (docstring). Aucun fichier des trois autres implémenteurs touché.

Autotest : `python src/research/errp_stimulus.py --smoke` → **18 contrôles, VERDICT : OK, sortie 0**
(il y en avait 8). Non-régression : `python src/research/app.py --smoke` → `[app] smoke OK`, sortie 0.
Un seul programme lancé à la fois, aucun moteur en fond (`Get-Process python` vide avant de commencer).

| # | Gravité | Traitée ? | Comment |
|---|---|---|---|
| C1 | Critical | ✅ | deux écrans statiques (0,7 s + 0,9 s) à chaque fin de course, et avant le 1er pas |
| I1 | Important | ✅ | `PAUSE_INTER_PAS_S = 0,45` → SOA 1,45 s ; tolérance du smoke resserrée à ±20 % |
| I2 | Important | ⚠️ **partielle** | test différentiel anti-dérive ; la fusion elle-même est HORS périmètre |
| I3 | Important | ✅ | `--seed` + horodatage LSL (`t=`) sur chaque ligne imprimée |
| I4 | Important | ✅ | piste statique pendant les ~23 s de chauffe+repos du moteur, et on le DIT |
| I5 | Important | ✅ | **le test central** : ordre `flip`→`push_sample` + empreinte de l'écran |
| I6 | Important | ✅ | `research/__init__.py` : les deux mises à jour |
| M1 | Minor | ✅ | `--cells >= 3` refusé au lancement, avant toute fenêtre |
| M2 | Minor | ✅ | graine + `max_run_steps` exercé + plus de division par zéro |
| M3 | Minor | ✅ | la fenêtre de feedback va à son terme même si on ferme la fenêtre |
| M4 | Minor | ❌ **reportée** | exige `src/research/app.py` (implémenteur `4a219e9`) — hors périmètre |

---

## Le fond du protocole

### C1 — la fin de course ne tombe plus dans la frame horodatée

Après `pos == cible` ou le plafond de pas, `run` tient désormais la piste IMMOBILE
`PAUSE_FIN_COURSE_S` (0,7 s) à la position finale, PUIS remet le point au centre avec une nouvelle
cible et tient `PAUSE_NOUVELLE_COURSE_S` (0,9 s) — les mêmes deux écrans, aux mêmes durées, que
`errp_calibrate._run_block:225/212` et `app.mode_errp:1025`. Le même écran sert avant le TOUT
PREMIER pas : sans lui l'utilisateur ne voyait jamais d'où le point part, donc n'avait aucune
attente à violer.

Les trois attentes passent par une seule fonction `tenir(pos, cible, secondes, note=None)` — le
`_track_hold` de la calibration, réduit à ce dont un émetteur a besoin. Elle ne dort pas : elle
continue à rafraîchir la fenêtre (sinon l'OS la déclare « ne répond pas ») et garde ESC vivant.

### I1 — la cadence est celle du modèle

`PAUSE_INTER_PAS_S = 0.45` après chaque fenêtre de feedback → **1,45 s entre deux onsets**, la
cadence de `errp_calibrate._run_block:230` sous laquelle les époques du modèle ont été
enregistrées. L'assertion du smoke ne tolère plus ±50 % autour de 1 s (qui acceptait aussi bien
1,0 s que 1,45 s) : elle sépare les écarts **intra-course** (1,45 s ±20 %) des écarts de
**transition** (≥ 2,08 s), grâce à un 4e champ `debut_de_course` ajouté au journal. Mesuré :
1,42 s intra, 2,58 s en transition.

---

## Le test central : l'ordre `flip()` → `push_sample` (I5)

`--smoke` instrumente **les deux gestes réels** — `pygame.display.flip` et
`pylsl.StreamOutlet.push_sample`, pas un proxy — dans une trace unique qui conserve leur ordre, et
prend à chaque flip une empreinte de l'écran (`pygame.transform.scale` en 100×70 puis `hash`,
~20 µs, sans rien connaître de la géométrie du stimulus). Deux assertions par passage :

1. **l'ordre brut** : un marqueur ne part jamais avant que le premier flip ait eu lieu ;
2. **le contenu de la frame** : le flip qui précède un marqueur doit être celui qui a **CHANGÉ**
   l'image — la définition même de l'onset.

### Preuve rouge — mutation : `pygame.display.flip()` déplacé APRÈS le bloc `if f == 0: emet(...)`

```
  OK   [B1] chaque marqueur part APRÈS un flip, jamais avant (4 push pour 4 feedbacks journalisés)
  ÉCHEC [B1] ...et ce flip est celui qui a CHANGÉ l'écran (le point à sa nouvelle case), pas une frame de plus du même écran (0/4)
  OK   [B2] chaque marqueur part APRÈS un flip, jamais avant (4 push pour 4 feedbacks journalisés)
  ÉCHEC [B2] ...et ce flip est celui qui a CHANGÉ l'écran (le point à sa nouvelle case), pas une frame de plus du même écran (0/4)
[errp-stim] VERDICT : PROBLÈME
EXIT=1
```

**Deux enseignements mesurés, et le second m'a fait garder les deux assertions :**

- l'assertion (2) attrape **TOUS** les marqueurs, pas seulement le premier : 0/4 en B1 comme en B2 ;
- l'assertion (1), elle, **reste verte** sous cette mutation — parce qu'il y a toujours, juste avant
  le push, le flip de la frame PRÉCÉDENTE (dernière frame du `tenir`, ou frame `f-1`). Une
  vérification de l'ordre seule n'aurait donc **rien vu**. C'est écrit tel quel dans le commentaire
  du code, avec le chiffre mesuré.

Mutation retirée, relancé : `18 OK`, `VERDICT : OK`, sortie 0.

---

## Les autres preuves rouges (mutation appliquée → relancée → retirée → relancée verte)

**C1** — les deux `tenir(...)` de fin de course supprimés :

```
  ÉCHEC ENTRE deux courses, au moins 2.08 s : les deux écrans statiques (0.7 s + 0.9 s) séparent la remise à zéro de la frame horodatée suivante ([0.95, 0.96] s)
  ÉCHEC ...et une transition est toujours PLUS LONGUE qu'un pas ordinaire (0.95 s > 1.42 s) — sans quoi la téléportation du point tomberait dans l'époque du feedback suivant
[errp-stim] VERDICT : PROBLÈME · EXIT=1
```

**I1** — `tenir(pos, cible, PAUSE_INTER_PAS_S)` remplacé par `pass` (la cadence d'avant, 1,0 s) :

```
  ÉCHEC DANS une course, 1.45 s entre deux onsets (±20 %) — la cadence de errp_calibrate, celle sous laquelle le modèle a été entraîné ([0.95, 0.97, 0.96, 0.96, 0.96, 0.97] s)
[errp-stim] VERDICT : PROBLÈME · EXIT=1
```

**M2.2 — le plafond de pas** — `n_pas_course >= max_run_steps` → `>= 10**9` :

```
  ÉCHEC ENTRE deux courses, au moins 2.08 s : ... ([] s)
  ÉCHEC ...et une transition est toujours PLUS LONGUE qu'un pas ordinaire (0.00 s > 1.43 s) ...
  ÉCHEC le PLAFOND de pas (ici 2) termine une course qui ne converge JAMAIS (100 % d'erreurs) : une nouvelle course tous les 2 pas ([True, False, False, False, False])
[errp-stim] VERDICT : PROBLÈME · EXIT=1
```

> ⚠️ **Cette mutation a révélé un défaut de mon propre smoke**, exactement du type M2.3 : le message
> `f"({min(transitions)...})"` est évalué AVANT d'entrer dans `chk`, donc une liste vide y levait un
> `ValueError` — sortie 1, mais par traceback au lieu d'un `VERDICT : PROBLÈME` lisible. Corrigé
> (min/max calculés à part), puis la mutation relancée pour obtenir la sortie ci-dessus.

**I2 — dérive entre les deux écritures du protocole** — `rng.choice([0, n_cells - 1])` →
`rng.choice([n_cells - 1, 0])` (une mutation qu'AUCUNE autre assertion ne voit) :

```
  ÉCHEC 500 pas joués à graine égale : `decide_pas`/`nouvelle_cible` et les `_decide_step`/`_new_goal` de errp_calibrate (celles qui ENTRAÎNENT le modèle) donnent EXACTEMENT la même trajectoire — le protocole est écrit deux fois, il ne doit pas dériver (cible initiale 0 vs 6)
[errp-stim] VERDICT : PROBLÈME · EXIT=1
```

**M1 — la garde `--cells`** — `if int(n_cells) < MIN_CELLS:` → `< 0:` :

```
  ÉCHEC --cells 2 est REFUSÉ avant d'ouvrir la moindre fenêtre (départ au centre = extrémité -> pas corrects étiquetés erreur) ; il en faut 3
[errp-stim] VERDICT : PROBLÈME · EXIT=1
```

**M3 — la fenêtre coupée en deux** — `if not running and f == 0: break` → `if not running: break` :

```
  ÉCHEC [B3] fenêtre fermée 10 frames après le marqueur : la fenêtre de feedback va quand même à son TERME (10 frames affichées après le marqueur, sur 60 attendues) — on ne coupe pas l'écran au milieu d'une époque
[errp-stim] VERDICT : PROBLÈME · EXIT=1
```

Ce test-là ne dépend d'aucune horloge : `--smoke` poste l'événement `QUIT` depuis le flip
instrumenté, **au 10e flip après le marqueur** — en frames, pas en secondes, donc le moment de la
coupure est le même sur toutes les machines.

---

## Le reste, en bref

- **I3** — `run(..., seed=...)` + `--seed`, et la ligne imprimée porte désormais l'horodatage LSL
  EXACT du marqueur (`[errp-stim] t=2008586.140  pas 1 : ...`). C'est ce qui rend le TPR/TNR de
  séance calculable hors ligne (appariement avec les échantillons `decoded_errp`) sans jamais
  mettre la vérité-terrain sur le réseau. La recette `docs/recette.md:582` en dépend.
- **I4** — après un `wait_for_consumers` réussi, l'émetteur ne dit plus « on peut commencer » : il
  dit que le moteur **jette tout** pendant ~23 s (`ATTENTE_MOTEUR_S = SSVEP_WARMUP_S + 8.0`, lu dans
  `core/modes/errp.py` SPEC.rest) et tient la piste STATIQUE pendant ce temps — ce qui donne aussi
  au moteur l'écran immobile que son repos réclame. `--no-wait` pour qui lance l'émetteur seul.
- **I6** — `research/__init__.py` : `errp_stimulus.py` rejoint `p300_stimulus.py` dans la liste des
  programmes qui n'ouvrent PAS le casque (règle de sécurité matérielle), et `errp_decoder` (avec
  `errp_models`) est daté du 2026-08-18 dans la liste des migrations : « tous **quatre** ».
- **M2** — les deux passages de `run()` en smoke sont graines (`seed=0`) ; B2 (`max_run_steps=2`,
  100 % d'erreurs → la cible n'est jamais atteinte) exerce le plafond à coup sûr au lieu d'une fois
  sur trois par chance ; plus aucune division par une liste vide.

Le smoke dure ~17 s (3 passages de `run()` de 6,5 s / 7 s / ~2 s) contre ~7 s avant.

---

## Dépendances hors périmètre (à traiter par qui possède ces fichiers)

1. **I2, la fusion elle-même — `src/research/errp_calibrate.py`.** Le correctif complet demande que
   `_decide_step`/`_new_goal` deviennent des adaptateurs de 2 lignes autour de
   `errp_stimulus.decide_pas`/`nouvelle_cible` (le patron du P300 : le module LÉGER possède
   l'invariant, les modules lourds l'importent). J'ai livré le garde-fou intermédiaire — un test
   différentiel de 500 pas à graine égale, prouvé rouge — mais **le protocole reste écrit deux
   fois**. Une deuxième ligne serait à ajouter au smoke d'`app.py` (assertion sur le source, comme
   pour `blocs_melanges`) le jour de la fusion.
2. **M4 — `src/research/app.py`** (implémenteur `4a219e9`) : rien n'empêche `research.errp_decoder`
   de réapparaître dans `mode_errp`/`page_errp`. L'assertion sur le source proposée par la revue
   tient en 4 lignes dans `app.py:_smoke`.
3. **I5, le jumeau — `src/research/p300_stimulus.py`** : il a exactement le même trou (l'ordre
   flip/push n'y est vérifié par rien). L'instrumentation livrée ici (`_empreinte_ecran` + trace
   `flip`/`push`) s'y transpose telle quelle ; la revue le recommandait, c'est hors de mon périmètre.
