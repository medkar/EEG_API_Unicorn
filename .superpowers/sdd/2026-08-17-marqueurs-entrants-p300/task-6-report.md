# Tâche 6 — L'émetteur de stimulus, et LE test d'alignement — rapport d'implémentation

Statut : **DONE**
Commit : `d7d8060` — « Ship the stimulus emitter, and pin the alignment that everything rests on »
Base : `4aaa7de` (HEAD de `main` avant cette tâche)

## Ce qui a été fait

- **`src/research/p300_stimulus.py` créé** — calqué sur `ssvep_stimulus.py` : programme autonome
  pygame, plein écran ou `--windowed`, **n'ouvre jamais le casque**. Publie sur
  `MARKER_STREAM_DEFAULT` (type `Markers`, 1 voie `string`, `IRREGULAR_RATE`,
  `source_id=f"p300-stim-{os.getpid()}"`), exactement le `StreamInfo(...)` du brief.
  - `build_markers(n_targets, reps, rng)` : fonction PURE (aucun pygame, aucun réseau) qui produit
    la séquence complète d'une manche — `reps` répétitions de l'ordre mélangé des `n_targets`
    cibles (remélangé à CHAQUE répétition), puis un `round_end`. `run()` rejoue exactement cette
    séquence en y attachant rendu et horodatage réels : aucune divergence possible entre ce que
    `--smoke` vérifie et ce qui part sur le réseau.
  - Le geste critique : le marqueur de flash est envoyé juste après `pygame.display.flip()`
    (seulement à la 1ʳᵉ frame ON de chaque flash), avec le commentaire d'avertissement du brief
    mot pour mot. `round_end` est envoyé sans rendu associé (pas nécessaire : voir « Inquiétudes »
    n°1).
  - `--smoke` : **aucun `pygame.display` dans ce chemin** — `run()` retourne vers `_smoke()` AVANT
    le premier `import pygame`. Vérifie `build_markers` directement : `reps × n_targets` flashs,
    chaque cible vue exactement `reps` fois, `round_end` final, `mode="p300"` partout, cibles dans
    `[0, n_targets[`.
  - CLI : `--windowed --refresh --reps --targets --seconds --smoke`, réutilise
    `research.ssvep_stimulus.measure_refresh` (import tardif, pas réinventé).
- **`src/core/modes/p300.py` étendu** — le test d'alignement du brief ajouté verbatim à
  `_selftest()`, en fin de bloc `try`, avant le `finally`. Plante un pic d'amplitude unique dans un
  tampon plat à un instant connu, envoie un marqueur à cet instant, vérifie que
  `epoch_from_stream` place ce pic exactement à l'échantillon `n_pre` (et pas seulement que
  l'époque existe / a la bonne forme) — plus une variante à ±1 échantillon (un marqueur ne tombe
  jamais pile sur un échantillon dans la vraie vie).

## Écart constaté avec le brief (signalé, pas appliqué à moitié)

Le brief dit de casser l'alignement en « remplaçant `pre_s=P300_PRE_S` par `pre_s=0.0` **dans
`_encaisser_flash`** ». Or `_encaisser_flash` (ligne 198-199) appelle
`epoch_from_stream(..., pre_s=self.pre_s, post_s=self.post_s)` — un attribut de classe, pas un
littéral `pre_s=P300_PRE_S` ; cette sous-chaîne n'existe nulle part dans `_encaisser_flash`. Elle
n'existe qu'aux deux appels du NOUVEAU test lui-même (celui-ci appelle `epoch_from_stream`
directement, sans passer par le runtime). J'ai donc cassé l'alignement là où ce littéral existe
réellement — les deux occurrences du nouveau bloc — plutôt que de deviner un autre endroit.
Vérifié en plus : muter la classe (`P300Runtime.pre_s = 0.0`) n'aurait de toute façon eu AUCUN
effet sur ce test (il ne lit pas cet attribut), et l'aurait fait échouer ailleurs — `chk(SPEC.
marker_epoch_s == P300Runtime.pre_s + P300Runtime.post_s, ...)`, un des 46 tests préexistants,
puisque ce membre-là ne bouge pas avec la mutation — donc pas « tous les autres verts » comme
l'annonce le brief. La correction appliquée est la seule qui isole proprement l'effet au nouveau
test.

Détail mineur, sans conséquence : le commentaire du brief dit `n_pre` « # 37 », mais
`round(0.15 * 250) = round(37.5) = 38` (arrondi Python au pair). Le code ne code jamais 37 en dur
(il calcule `n_pre` dynamiquement et l'utilise partout), donc ça n'affecte aucune assertion — juste
le chiffre écrit dans le commentaire.

## La preuve rouge-puis-vert

Bug injecté : `pre_s=0.0` au lieu de `pre_s=P300_PRE_S` aux deux appels `epoch_from_stream` du
nouveau test (voir écart ci-dessus). `python src/core/modes/p300.py` :

```
  OK   l'époque est extraite
  ÉCHEC elle a exactement pré+post échantillons ((200, 8))
  ÉCHEC ⚠️ ALIGNEMENT : le pic planté à l'onset se retrouve à l'échantillon 0, il devait être à 38
        (décalage de -38 échantillons = -152 ms)
  ÉCHEC et c'est bien LA valeur plantée qu'on retrouve (0.0)
  ÉCHEC un marqueur entre deux échantillons reste aligné à ±1 (0 vs 38)
[p300] VERDICT : PROBLÈME
```

**Les 46 assertions préexistantes restent VRAIES** (chauffe, décisions, appariement score↔cible,
pannes n°4/5/6, `state()`, contrat du mode — tout vert) : seul le nouveau test réagit, exactement
la thèse du brief. Restauré (`pre_s=P300_PRE_S` aux deux endroits, `git diff` confirmé identique à
avant mutation), relancé :

```
  OK   l'époque est extraite
  OK   elle a exactement pré+post échantillons ((238, 8))
  OK   ⚠️ ALIGNEMENT : le pic planté à l'onset se retrouve à l'échantillon 38, il devait être à 38
       (décalage de 0 échantillons = +0 ms)
  OK   et c'est bien LA valeur plantée qu'on retrouve (42.0)
  OK   un marqueur entre deux échantillons reste aligné à ±1 (37 vs 38)
[p300] VERDICT : OK
```

## Comptage des assertions

| Fichier | Avant | Après | Détail |
|---|---|---|---|
| `src/core/modes/p300.py` (`chk(`) | 46 | 51 | +5, le test d'alignement (4) + sa variante ±1 échantillon (1) |

Rien retiré ni affaibli : `git diff` sur `p300.py` (reproduit ci-dessus dans le résumé, vérifié en
entier) n'ajoute que le nouveau bloc, ne touche aucune ligne existante.

## Tests — dans l'ordre demandé, un par un, aucun moteur laissé tournant

Garde-fou avant CHAQUE lancement : `Get-Process python -ErrorAction SilentlyContinue` vérifié vide.

| Commande | Résultat |
|---|---|
| `python src/research/p300_stimulus.py --smoke` | 5 `OK`, `[p300-stim] VERDICT : OK`, exit 0 |
| `python src/core/modes/p300.py` | 51 `OK`, `[p300] VERDICT : OK`, exit 0 |
| `python src/research/app.py --smoke` | menu + 5 modes + calibrations câblés, exit 0 (non affecté) |
| `python src/core/server.py --smoke` | 16 sous-verdicts verts, exit 0 (non affecté) |

Bonus : `p300_stimulus.py --smoke` relancé aussi avec `--reps 3 --targets 4` (paramètres non
standards) pour vérifier que `build_markers` généralise, pas seulement au défaut 8×6.

## Commit

```
git add src/research/p300_stimulus.py src/core/modes/p300.py
git commit -m "Ship the stimulus emitter, and pin the alignment that everything rests on"
```

```
[main d7d8060] Ship the stimulus emitter, and pin the alignment that everything rests on
 2 files changed, 311 insertions(+)
 create mode 100644 src/research/p300_stimulus.py
```

## Inquiétudes / ce que je laisse dehors

1. **`round_end` n'a aucun rendu associé** (pas de `flip()` juste avant), suivant le brief à la
   lettre. Vérifié que c'est sans conséquence : `EngineServer.markers_murs` applique la maturité
   `post_s` à TOUS les marqueurs d'un mode uniformément (avant même de regarder `event`,
   `server.py` ligne ~915) — donc `round_end` envoyé immédiatement après le dernier flash n'atteint
   `_decider` qu'après le même délai de 0,8 s que l'époque du dernier flash a besoin pour mûrir.
   Aucun « settle » côté émetteur n'est donc nécessaire ; je le note ici parce que ce n'est pas
   évident à la lecture du seul fichier stimulus.
2. **`--targets` accepte n'importe quelle valeur**, mais le mode P300 du moteur n'accepte QUE
   `P300_N_TARGETS` (6, fixe) — une cible hors plage serait comptée dans `refus_cible` et imprimée
   côté moteur. Documenté dans l'aide `--targets` du CLI ; utile pour explorer `build_markers` en
   isolation ou pour un `--smoke` rapide à faible N, mais un étudiant qui lancerait
   `--targets 8` contre le vrai moteur verrait des cibles 6 et 7 rejetées — comportement voulu et
   déjà couvert par la panne n°4 du mode, pas un bug de ce fichier.
3. **Aucune vérification EN CASQUE (ni même moteur+émetteur en LSL réel) n'a été faite** dans cette
   tâche : les quatre commandes demandées sont toutes headless/smoke. Le brief ne demandait pas de
   séance matérielle pour cette tâche, donc rien fait au-delà — mais ça reste une piste ouverte
   pour la recette (`docs/recette.md`), comme le reste du chantier P300.
4. **`.superpowers/sdd/2026-08-17-marqueurs-entrants-p300/progress.md`** apparaissait déjà modifié
   (non commité) en tout début de tâche — notes de clôture de la tâche 5, pas mon fait. Laissé tel
   quel, non commité, non touché : pas dans le périmètre de cette tâche, et le brief liste
   explicitement les deux seuls fichiers à ajouter au commit.

---

# Tour de correction 1 — rapport

Statut : **DONE**
Commit : `47f7137` — « Close the alignment blind spot, and stop the emitter repeating a target »
Base : `d7d8060` (le commit initial de cette tâche)

Conformité au brief ✅, aucun CRITIQUE, deux IMPORTANT — le relecteur a en plus vérifié lui-même la
piste que j'avais écartée dans le tour précédent (muter `P300Runtime.pre_s`) et confirmé qu'elle
aurait cassé un test préexistant, donc que mon constat sur le brief original était juste. Les deux
IMPORTANT de ce tour traités, aucun contesté.

## IMPORTANT 1 — le test d'alignement ne passait jamais par `_encaisser_flash`

Constat exact : mon test appelait `epoch_from_stream` en direct, donc il prouvait l'arithmétique
du décodeur, pas que le runtime lui transmet ses bornes dans le bon ordre. Le trou précis :
`round(0,15×250) + round(0,80×250) = 38 + 200 = 238 = 200 + 38` — une inversion
`pre_s=self.post_s, post_s=self.pre_s` à l'appel réel produit une époque de la MÊME forme,
invisible à tout contrôle de taille/bornes.

**Corrigé** : un second test dans `_selftest()`, juste après le premier. Il réutilise le MÊME pic
connu (`eeg`/`ts`/`instant_du_pic`/`n_pre`, inchangés depuis le premier test) mais le fait
traverser le VRAI chemin d'appel : un `_FauxMoteur` dédié dont `recent`/`recent_ts` portent ce
signal, un marqueur envoyé via `rt.tick(...)`, et la position du pic lue directement dans
`rt._epoques[-1]` — l'époque que `_encaisser_flash` a réellement construite, pas une que le test
aurait fabriquée lui-même.

### Preuve rouge-puis-vert

Mutation demandée, appliquée telle quelle : `pre_s=self.pre_s, post_s=self.post_s` →
`pre_s=self.post_s, post_s=self.pre_s` dans `_encaisser_flash`. `python src/core/modes/p300.py` :

```
  OK   le flash a produit UNE époque en passant par _encaisser_flash, le vrai chemin d'appel du runtime (1)
  ÉCHEC ⚠️ ALIGNEMENT (chemin réel _encaisser_flash) : le pic se retrouve à l'échantillon 200, il devait
        être à 38 (décalage de 162 échantillons = +648 ms) — pre_s/post_s mal transmis par le runtime
[p300] VERDICT : PROBLÈME
```

200 est exactement `round(P300_EPOCH_S × fs)` — la prédiction faite avant de lancer le test.
**Les 52 autres assertions restent vertes**, y compris le PREMIER test d'alignement (qui n'emprunte
jamais ce chemin) et le contrôle de comptage du second test lui-même (`len(rt._epoques) == 1` ne
dépend pas de l'alignement) : seule la position réagit, exactement le trou que ce tour visait à
fermer. Remis en état (`pre_s=self.pre_s, post_s=self.post_s`), relancé :

```
  OK   le flash a produit UNE époque en passant par _encaisser_flash, le vrai chemin d'appel du runtime (1)
  OK   ⚠️ ALIGNEMENT (chemin réel _encaisser_flash) : le pic se retrouve à l'échantillon 38, il devait
       être à 38 (décalage de 0 échantillons = +0 ms) — pre_s/post_s mal transmis par le runtime
[p300] VERDICT : OK
```

## IMPORTANT 2 — deux flashs de la même cible pouvaient se suivre à la jonction

Constat exact : `build_markers` remélangeait chaque répétition indépendamment sans jamais regarder
la dernière cible du bloc précédent — ~1/n_targets de chances de collision à chaque jonction, soit
aux réglages par défaut (6 cibles × 8 répétitions, 7 jonctions) environ 72 % de chances qu'au moins
une répète. Le contrat n'était pas violé (chaque cible flashe bien `reps` fois), mais c'est un
défaut scientifique dans un fichier de référence : un flash immédiatement répété introduit un effet
de réfractarité non maîtrisé sur l'onde P300 qu'on cherche à mesurer.

**Corrigé** dans `build_markers` (`src/research/p300_stimulus.py`) : après chaque mélange, on
reshuffle tant que la première cible du nouveau bloc égale la dernière du bloc précédent
(`derniere_cible`, gardée d'un tour à l'autre) ; gardé par `n_targets > 1` pour ne jamais boucler
sans fin quand une seule cible existe (aucune alternative possible). Raison expliquée dans la
docstring, comme demandé, pour l'étudiant qui adapterait ce fichier.

`--smoke` vérifie maintenant `consecutifs == 0` (aucune paire consécutive de flashs, jonctions
comprises, ne partage la même cible), avec la même garde `n_targets <= 1` pour ne pas échouer sur
une contrainte mathématiquement intenable à une seule cible.

**Robustesse vérifiée au-delà du `--smoke` par défaut** (seed 0 seule) : script jetable dans le
scratchpad, 4000 combinaisons (`n_targets` ∈ {1, 2, 3, 6, 10} × `reps` ∈ {1, 2, 8, 20} × 200
graines), y compris le cas le plus tendu (`n_targets=2`, rejet ~50 % par tentative) — 0 répétition
immédiate, aucun ralentissement perceptible (donc pas de risque pratique de boucle longue).

## Comptage des assertions, avant/après ce tour

| Fichier | Avant | Après | Détail |
|---|---|---|---|
| `src/core/modes/p300.py` (`chk(`) | 51 | 53 | +2 : le second test d'alignement (comptage d'époque + position réelle) |
| `src/research/p300_stimulus.py` (`chk(`) | 5 | 6 | +1 : aucune répétition immédiate dans `--smoke` |

Rien retiré ni affaibli — les deux diffs (revus avant commit) n'ajoutent que du texte, ne
modifient aucune assertion existante.

## Tests — relancés un par un, aucun moteur laissé tournant

Garde-fou avant CHAQUE lancement : `Get-Process python -ErrorAction SilentlyContinue` vérifié vide.

| Commande | Résultat |
|---|---|
| `python src/research/p300_stimulus.py --smoke` | 6 `OK`, `[p300-stim] VERDICT : OK`, exit 0 |
| `python src/core/modes/p300.py` | 53 `OK`, `[p300] VERDICT : OK`, exit 0 |
| `python src/core/server.py --smoke` | 16 sous-verdicts verts, exit 0 |

Bonus (non demandé ce tour, revérifié par prudence) : `python src/research/app.py --smoke`, vert.

## Commit

```
git add src/core/modes/p300.py src/research/p300_stimulus.py
git commit -m "Close the alignment blind spot, and stop the emitter repeating a target"
```

```
[main 47f7137] Close the alignment blind spot, and stop the emitter repeating a target
 2 files changed, 52 insertions(+)
```

## Inquiétudes de ce tour

1. **La garde anti-répétition ne regarde QUE la jonction immédiate** (dernière cible du bloc N,
   première du bloc N+1) — elle ne cherche pas à équilibrer l'espacement au-delà de ça (une cible
   pourrait par exemple revenir en position 2 du bloc suivant, proche mais pas immédiate). C'est
   exactement ce que le tour demandait (interdire la répétition IMMÉDIATE), pas plus ; un futur
   raffinement du protocole pourrait vouloir un espacement minimal plus large, mais ce serait un
   changement de spécification, pas un bug de celle-ci.
2. **`P300_ROUND_TIMEOUT_S` (10 s) n'est pas concerné par ce tour**, mais je note en passant que le
   second test d'alignement envoie son marqueur puis n'appelle jamais `round_end` ni n'attend —
   il nettoie explicitement avec `rt._vider_manche()` avant de rendre la main, donc n'a laissé
   aucune manche orpheline pour la suite de `_selftest` (il n'y a d'ailleurs plus rien après lui).
3. **Reportés tels quels, comme demandé** : le commentaire critique reformaté (sens intact) et le
   `# 37` faux du brief original — rien touché sur ces deux points.
