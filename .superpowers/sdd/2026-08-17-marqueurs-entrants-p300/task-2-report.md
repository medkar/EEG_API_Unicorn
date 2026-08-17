# Task 2 — Le tampon d'horodatages, et `keep` dimensionné nommément — rapport d'implémentation

Statut : **DONE**
Commit : `f30be3d` — "Stop throwing away the sample timestamps the engine already receives"
Base : `ecfa67c` (HEAD de `main` avant cette tâche)

## Vérification préalable du fait central du brief

Avant d'écrire quoi que ce soit, lecture de `src/core/acquisition.py::get_new_data` (lignes
289-308) : confirmé, elle rend déjà `(eeg (n,8), ts (n,))` avec
`ts = data[self.ts_row, :]` — un horodatage Unix par échantillon, tiré du canal timestamp
BrainFlow. Et dans `server.py::run`, la boucle appelait bien `self.clock.to_lsl(ts_unix)` pour
construire `new_block`, puis **jetait `ts_unix`** : seul `eeg` partait dans `self.recent`. Le
constat du brief est exact — rien à aller chercher côté acquisition, juste cesser de jeter.

## Ce qui a été fait

1. **`src/core/modes/contract.py`** — champ `marker_epoch_s: float = 0.0` ajouté à `ModeSpec`,
   juste après `channels_fn`, verbatim par rapport au brief. Vérifié au préalable que **tous** les
   appels à `ModeSpec(...)` du dépôt (10 fichiers, une trentaine de sites) utilisent exclusivement
   des arguments nommés — aucun positionnel — donc l'insertion d'un nouveau champ à défaut ne peut
   rien casser silencieusement.

2. **`src/core/server.py`** :
   - Import de `MARKER_LATE_S` depuis `core.config` (déjà livré par la tâche 1).
   - `self.recent_ts = np.zeros((0,))` ajouté dans `__init__`, à côté de `self.recent`.
   - `self.keep` dimensionné avec le terme `epoque_marqueur` (`marker_epoch_s` le plus grand du
     registre + `MARKER_LATE_S`), commentaires du brief repris tels quels.
   - Boucle de `run()` : `ts_lsl` calculé une fois, réutilisé pour `new_block` **et**
     `self.recent_ts`, tenu en phase avec `self.recent` (même `[-self.keep:]`).
   - `_smoke_dimensionnement()` et `_smoke_tampon_horodate()` ajoutées avant `_parse_args`,
     code repris tel quel depuis le brief.
   - `_smoke()` : chaînage des sous-tests reconstruit (voir section dédiée) et les deux nouvelles
     fonctions y sont branchées.

## Le chaînage de `_smoke()` — il était bien cassé, corrigé

Avant cette tâche, `_smoke()` se terminait par :

```python
return (ok and integre and _smoke_frontiere() and _smoke_repos_partage()
        and _smoke_ssvep() and _smoke_neuro() and _smoke_mi() and _smoke_calibration()
        and _smoke_calibration_refus()
        and _smoke_cumul() and _smoke_proposition())
```

C'est bien un `and` en cascade, et son propre commentaire l'assumait explicitement (« `and`
court-circuite, donc l'ordre est aussi celui du diagnostic ») — un choix délibéré, mais avec l'effet
de bord exactement décrit dans la consigne : si `ok` (le smoke brut) ou `integre` (le registre) ou
n'importe quel `_smoke_*()` avant la fin de la liste rend `False`, Python **n'appelle même plus** les
suivants — ils restent muets, pas seulement « ignorés dans le résultat ». Un test instable en tête de
chaîne masquerait silencieusement tous les tests placés après lui.

Remplacé par : construire la liste `resultats` (chaque appel s'exécute, imprime son propre
`VERDICT` quoi qu'il arrive), puis `return all(resultats)` — qui ne fait que combiner des résultats
déjà tous obtenus. `_smoke_dimensionnement()` et `_smoke_tampon_horodate()` sont ajoutées à cette
même liste plutôt qu'à un `and` qui aurait reproduit le défaut à l'identique.

Preuve empirique que le correctif fonctionne (et pas seulement en théorie) : lors de la preuve
rouge ci-dessous, `[smoke-dimensionnement]` a échoué en **avant-dernière** position de la liste, et
le `[smoke-tampon]` placé juste après lui s'est bien exécuté et a imprimé son propre verdict — la
preuve qu'aucun test n'a été court-circuité par l'échec de son voisin.

## La preuve rouge (Step 3) — et une valeur du brief qui ne suffit pas

### Une divergence trouvée avant même de muter

Le brief donne deux affirmations contradictoires sur le même test :
- Step 2 : « Tant qu'aucun mode ne déclare `marker_epoch_s`, `besoin` vaut 0 et elle **passe** —
  trivialement. »
- Step 7 : après tout le reste implémenté et la mutation retirée, « `[smoke-dimensionnement]`
  **échoue** encore sur son PREMIER `chk` […] — c'est attendu jusqu'à la tâche 5. »

Ces deux phrases décrivent le même état (aucun mode ne déclare d'époque) et se contredisent. Vérifié
empiriquement plus bas : c'est Step 2 qui a raison, Step 7 est faux pour ce dépôt — voir la
dernière sortie de cette section.

### La mutation suggérée (3,0 s) ne produit PAS de rouge

Avant de muter quoi que ce soit, calcul à partir des constantes réelles du dépôt (`fs=250`,
`QUALITY_WINDOW_S=2.0`, `NEURO_WINDOW_S=2.0`, `MI_WINDOW_S=2.0`, `FILTER_MARGIN_S=1.0`, et surtout
`mi_calib.CALIB.epoch_s = MI_IMAGERY_S = 4.0`, seule calibration du registre avec
`runtime_cls is not None`) : **avant même le correctif de l'étape 4**, `self.keep` vaut déjà
`int(4.0×250) + int(1.0×250) = 1000 + 250 = 1250` échantillons (5,0 s), parce que la calibration MI
domine déjà le `max(...)` existant. Une mutation à `marker_epoch_s=3.0` demande
`(3,0+1,0)×250 = 1000` échantillons — **inférieur** à 1250 : le test passerait donc même SANS le
correctif, ce qui ne prouve rien.

Vérifié en conditions réelles (mutation appliquée à `raw.SPEC`, AVANT l'étape 4) :

```
[server] AUCUN mode demandé : seuls `quality` et `status` seront publiés. Ajoute --mode, ou retire --no-raw.
  OK   keep=1250 couvre l'époque du marqueur (3 s) plus le retard toléré (1 s) = 1000 échantillons
[smoke-dimensionnement] VERDICT : OK
```

Confirmé : **pas de rouge** avec la valeur suggérée par le brief. J'ai donc changé la mutation pour
`marker_epoch_s=6.0`, qui demande `(6,0+1,0)×250 = 1750` échantillons — au-delà des 1250 déjà
disponibles, cette fois de façon vérifiée plutôt que supposée.

### Sortie 1/3 — ROUGE (mutation 6,0 s, correctif de l'étape 4 PAS ENCORE appliqué)

`python src/core/server.py --smoke`, code de sortie **1**. Extrait (les 9 autres sous-tests
affichent tous `VERDICT : OK` juste avant — preuve vivante que le chaînage corrigé les laisse
s'exprimer) :

```
[server] AUCUN mode demandé : seuls `quality` et `status` seront publiés. Ajoute --mode, ou retire --no-raw.
  ÉCHEC keep=1250 couvre l'époque du marqueur (6 s) plus le retard toléré (1 s) = 1750 échantillons
[smoke-dimensionnement] VERDICT : PROBLÈME
```

### Sortie 2/3 — VERT (mutation 6,0 s TOUJOURS en place, correctif de l'étape 4 appliqué)

`python src/core/server.py --smoke`, code de sortie **0** :

```
[server] AUCUN mode demandé : seuls `quality` et `status` seront publiés. Ajoute --mode, ou retire --no-raw.
  OK   keep=2000 couvre l'époque du marqueur (6 s) plus le retard toléré (1 s) = 1750 échantillons
[smoke-dimensionnement] VERDICT : OK
```

`keep` est passé de 1250 à 2000 = `1750 + margin_n(250)` : c'est bien le nouveau terme
`epoque_marqueur` qui domine désormais le `max(...)`, pas un hasard.

### Sortie 3/3 — VERT final (mutation RETIRÉE, `raw.py` revenu à l'identique)

Mutation supprimée de `raw.py` (`git diff -- src/core/modes/raw.py` rend un diff **vide** après
coup — retrait confirmé propre). `python src/core/server.py --smoke`, code de sortie **0** :

```
[server] AUCUN mode demandé : seuls `quality` et `status` seront publiés. Ajoute --mode, ou retire --no-raw.
  OK   keep=1250 couvre l'époque du marqueur (0 s) plus le retard toléré (1 s) = 250 échantillons
[smoke-dimensionnement] VERDICT : OK
```

C'est un **OK**, pas un ÉCHEC — cette sortie confirme Step 2 du brief (« passe trivialement ») et
contredit Step 7 (« échoue encore »). Je m'y fie parce qu'elle est cohérente avec l'implication
elle-même : `besoin=0` donne `attendu=250`, et `keep=1250` (dominé par l'époque de calibration MI,
4,0 s, inchangée par cette tâche) le couvre très largement. Aucune régression à corriger ici — juste
une phrase du brief à ignorer.

Dans la même sortie, `[smoke-tampon] VERDICT : OK` avec le détail :

```
  OK   les deux tampons ont la même longueur (746 et 746)
  OK   et ils ne sont pas vides après 3 s d'acquisition
  OK   le temps avance strictement, sans doublon ni retour en arrière
  OK   et la cadence médiane vaut ~1/fs (4.00 ms attendu 4.00 ms)
```

## Commandes de vérification finales, dans l'ordre demandé

Garde-fou avant CHAQUE lancement : `Get-Process python -ErrorAction SilentlyContinue` vérifié vide
(aucune sortie = aucun moteur actif) — 8 fois au total sur cette tâche (les 4 lancements de la
preuve rouge/verte ci-dessus, plus les 4 ci-dessous).

**1. `python src/core/modes/contract.py`** — code de sortie 0 :
```
[contract] VERDICT : OK
```

**2. `python src/core/modes/registry.py`** — code de sortie 0, catalogue inchangé (7 modes, 4 dans
le moteur) :
```
[registry] 7 modes, dont 4 dans le moteur
[registry] VERDICT : OK
```

**3. `python src/core/server.py --smoke`** — code de sortie 0, les 12 sous-verdicts (`grep -n
"VERDICT"`) :
```
[smoke] VERDICT : OK
[smoke-frontiere] VERDICT : OK
[smoke-repos] VERDICT : OK
[smoke-ssvep] VERDICT : OK
[smoke-neuro] VERDICT : OK
[smoke-mi] VERDICT : OK
[smoke-calib] VERDICT : OK
[smoke-calib-refus] VERDICT : OK
[smoke-cumul] VERDICT : OK
[smoke-proposition] VERDICT : OK
[smoke-dimensionnement] VERDICT : OK
[smoke-tampon] VERDICT : OK
```
Aucune ligne `ÉCHEC` dans tout le fichier de sortie.

**4. `python src/console/app.py --smoke`** — code de sortie 0 :
```
[console-smoke] VERDICT : OK
```
Ce smoke exerce entre autres `recent_window` (2 s de signal, `(500, 8)`, une COPIE) — inchangé par
cette tâche mais bon signal que `self.recent`/`self.keep` restent cohérents pour un consommateur
existant.

## Commit

```
git add src/core/server.py src/core/modes/contract.py
git commit -m "Stop throwing away the sample timestamps the engine already receives"
```

```
[main f30be3d] Stop throwing away the sample timestamps the engine already receives
 2 files changed, 102 insertions(+), 9 deletions(-)
```

`git status --short` après coup : seul `.superpowers/sdd/.gitignore` reste modifié — préexistant,
non lié à cette tâche (déjà signalé par l'implémenteur de la tâche 1 ; je ne l'ai pas touché, pour
la même raison que lui : réglage partagé du chantier, pas à moi de trancher unilatéralement).

## Ce dont je doute / observations pour le coordinateur

1. **Deux erreurs trouvées dans le brief, sur le même test, cohérentes entre elles.** Step 3
   suggère `marker_epoch_s=3.0` pour la preuve rouge — insuffisant, mesuré (`keep=1250` la couvre
   déjà avant même le correctif, à cause de l'époque de calibration MI qui domine le `max(...)`
   depuis le chantier 3B). J'ai utilisé `6.0` à la place, qui produit un rouge vérifié. Step 7
   prédit que `[smoke-dimensionnement]` échoue encore une fois la mutation retirée — contredit par
   Step 2 du même brief (« passe trivialement ») et par la mesure : la sortie finale rend `OK`. Les
   deux erreurs pointent dans la même direction : je pense que l'auteur du brief a sous-estimé de
   combien l'époque de calibration MI (4,0 s) fait déjà gonfler `keep` bien au-delà des besoins
   marqueurs modestes envisagés pour la démonstration. Aucun désaccord avec l'intention du test
   lui-même (l'implication doit être rendue contraignante puis relâchée) — seulement avec les deux
   valeurs numériques attendues.

2. **Le chaînage de `_smoke()` était bien cassé**, pas une fausse alerte : le commentaire du code
   lui-même assumait le court-circuit comme un choix (« l'ordre est aussi celui du diagnostic »),
   ce qui est le symptôme exact décrit dans la consigne — un `and` en cascade n'est pas juste un
   style différent, il rend certains tests **non exécutés**, pas seulement non comptés. Corrigé en
   `resultats = [...]` puis `all(resultats)`. Comportement observé pendant la preuve rouge : les 9
   sous-tests placés avant `_smoke_dimensionnement` dans la liste ont tous continué à s'exécuter et
   à imprimer `VERDICT : OK` malgré l'échec de `_smoke_dimensionnement` juste après eux dans la
   même liste (et `_smoke_tampon_horodate`, placé après, s'est exécuté aussi) — la correction est
   vérifiée en conditions réelles d'échec, pas seulement en lecture de code.

3. **`epoque_marqueur` ne change `keep` que pour un mode qui existe déjà avec `marker_epoch_s > 0`
   dans le registre.** Aujourd'hui aucun mode n'en déclare (`raw`, `ssvep`, `neuro`, `mi` restent
   tous à `0.0` par défaut) : cette tâche pose le mécanisme, elle ne change donc **le comportement
   observable de personne** pour l'instant — vérifié par le fait que les 4 commandes de vérification
   finale, y compris les smokes complets `server.py` et `console/app.py`, rendent des sorties dont
   les valeurs numériques (`keep=1250`, tailles de tampons, etc.) sont identiques à ce qu'elles
   étaient avant cette tâche. Le premier mode qui déclarera une `marker_epoch_s > 0` (le P300, à la
   tâche 5, `0,95 s`) sera le premier à faire bouger `self.keep` pour de vrai.

4. **`recent_window()` n'a pas été touchée**, volontairement : elle continue de lire uniquement
   `self.recent`, jamais `self.recent_ts`. Le brief ne demandait pas de lui faire rendre les
   horodatages, et rien dans les 4 vérifications finales n'en dépend — cohérent avec le fait que
   c'est la tâche 3 qui doit brancher `MarkerInlet` et se servir de `recent_ts` pour situer un
   marqueur dans le tampon.

5. **Aucun moteur ni autre programme du projet actif** à aucun moment de cette tâche : vérifié par
   `Get-Process python` avant chacun des 8 lancements Python (4 pour la preuve rouge/verte, 4 pour
   la vérification finale), toujours vide juste avant de lancer.
