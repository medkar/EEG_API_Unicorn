# Tâche 5 — Le P300 devient le 4e mode publié par le moteur — rapport d'implémentation

Statut : **DONE**
Commit : `37dce0c` — « Publish the P300 as the engine's fourth mode, driven by external markers »
Base : `2ebf022` (HEAD de `main` avant cette tâche)

## Ce qui a été fait

- **`src/core/lsl_io.py`** : `p300_channel_labels(n_targets)` et `DecodedP300Publisher`, repris
  VERBATIM du brief, placés après `DecodedMIPublisher`. Ajouté en bonus (non demandé, mais le
  fichier promet dans sa propre docstring d'auto-tester chaque publieur) : un bloc « 6. decoded_p300 »
  dans `lsl_io._autotest()`, jumeau du bloc « 5. decoded_mi » déjà là.
- **`src/core/modes/p300.py` créé** — structure calquée sur `mi.py` : `P300Runtime(ModeRuntime)`,
  `_channels`, `SPEC`, `_selftest`. `n_targets` est FIXE (`P300_N_TARGETS`, config), pas un
  réglage — la géométrie est celle du c-VEP, pas un choix utilisateur.
- **`src/core/modes/registry.py`** : `p300.SPEC` prend la place d'`external.P300`, juste après
  `mi.SPEC`. Ajout dans `check()` du contrôle structurel `marker_epoch_s` vs `pre_s`/`post_s`,
  copie exacte du patron `epoch_s`/`imagery_s` déjà là pour les calibrations.
- **`src/core/modes/external.py`** : constante `P300` supprimée ; docstring du module corrigée
  (« trois entrées » → « deux », « quatre choses » → « cinq », et le dernier paragraphe ne dit
  plus que « le moteur ne reçoit pas de marqueurs entrants » comme raison générale — c'est
  maintenant faux, le P300 en reçoit. La vraie raison pour l'ErrP est reformulée : l'infrastructure
  existe, personne n'a encore écrit son mode).
- **`src/core/server.py`** : `chk(besoin > 0.0, ...)` ajouté à `_smoke_dimensionnement`, exactement
  le texte du brief.
- **`src/console/app.py`** (hors liste du brief, nécessaire quand même — voir « Inquiétudes »).

Les quatre résolutions d'ambiguïté et les quatre pannes bruyantes (4 et 5, les deux qui vivent
dans ce fichier) sont appliquées telles que le brief les décrit — pas de désaccord à signaler
sur le fond du brief cette fois-ci.

## Les deux preuves rouge-puis-vert (résumé — détail complet ci-dessous)

**1. Appariement `score_<i>` ↔ cible `i`.** Bug injecté : construire `scores` en triant
`moyennes.items()` par valeur décroissante au lieu de parcourir les indices dans l'ordre (une
erreur plausible — « afficher les scores du meilleur au pire » — pas juste un décalage d'index).

```
ÉCHEC score_<i> correspond EXACTEMENT à la cible i, dans l'ordre des indices
      ([7.0, 4.0, 0.5, -1.5, -2.5, -3.0] attendu [-3.0, 7.0, -1.5, 0.5, -2.5, 4.0])
[p300] VERDICT : PROBLÈME
```

Une seule assertion casse (celle-là précisément) ; bornes d'index, nombre de voies, cible choisie
et confiance restent VRAIES avec le bug — exactement ce que le brief annonçait : l'inversion ne se
voit nulle part ailleurs. Corrigé, VERDICT : OK à nouveau.

**2. Manche incomplète → `-1`, sans consulter le modèle.** Bug injecté : désactiver le garde-fou
`if len(par_cible) < self.n_targets:` (remplacé par `if False:`). Scénario : 6 flashs mais 2
cibles distinctes seulement sur 6.

```
ÉCHEC 12 flashs mais 2 cibles seulement sur 6 : refusée quand même, pas un argmax sur les 2 cibles
      vues (index=0, n_flashes=12)
ÉCHEC scores neutres, pas partiels ([99.0, 99.0, 0.0, 0.0, 0.0, 0.0])
ÉCHEC le modèle n'est TOUJOURS pas consulté — 1 appel(s) au lieu de 0
[p300] VERDICT : PROBLÈME
```

Le modèle-espion (compte ses propres appels) a bien été appelé une fois et sa réponse fabriquée
(`0`, score 99.0) est sortie sur le flux — la preuve ne se contente pas de lire `-1`, elle prouve
que le modèle n'est même pas consulté quand le garde-fou est en place. Corrigé, VERDICT : OK.

Les deux mutations ont été appliquées et révoquées AVANT le commit (`git diff` vide sur
`p300.py` après restauration, vérifié).

## Les cinq pannes bruyantes

| # | Panne | Où elle se dit / se compte |
|---|---|---|
| 1 | aucun flux de marqueurs trouvé | `EngineServer._ouvre_marker_inlet` (tâche 3, déjà prouvé) |
| 2 | marqueur plus vieux que le tampon | `engine.marqueurs_perdus` (tâche 3, déjà prouvé) |
| 3 | marqueur dans le futur | `engine.marqueurs_futurs` (tâche 3, déjà prouvé) |
| 4 | cible hors de la plage déclarée | `P300Runtime._refus_cible`, imprimé UNE fois (prouvé ici) |
| 5 | `round_end` avec trop peu de flashs | `-1` publié + raison imprimée (prouvé ici, 2 sous-cas) |

Pour la 4 : trois cibles invalides (`99`, `-1`, `"deux"`) envoyées dans la même manche → comptées
3 fois (`_refus_cible`), mais **un seul** message imprimé (capturé via `redirect_stdout`, compté
dans le texte). Pour la 5 : les deux sous-cas du garde — trop peu de flashs au total, ET assez de
flashs mais pas toutes les cibles couvertes (celui de la preuve rouge/vert ci-dessus) — plus une
variante « époque mûre mais hors tampon » (`_epoques_perdues`, comptée, jamais imprimée — même
choix que `engine.marqueurs_perdus`, qui ne l'est pas non plus).

## Tests — dans l'ordre demandé, un par un, aucun moteur laissé tournant

Garde-fou avant CHAQUE lancement : `Get-Process python -ErrorAction SilentlyContinue` vérifié vide.

| Commande | Résultat |
|---|---|
| `python src/core/modes/p300.py` | 33 `OK`, `[p300] VERDICT : OK`, exit 0 |
| `python src/core/modes/registry.py` | 7 modes dont 5 dans le moteur, `[registry] VERDICT : OK`, exit 0 |
| `python src/core/server.py --smoke` | 15 sous-verdicts, dont `[smoke-dimensionnement]` avec ses DEUX `chk` au vert ; exit 0 |
| `python src/console/app.py --smoke` | `2 tuiles pour les modes de l'appli pygame` (c-VEP, ErrP) — la tuile P300 n'est plus grisée ; `[console-smoke] VERDICT : OK`, exit 0 |
| `python src/research/app.py --smoke` | `smoke OK : menu + SSVEP + c-VEP (eCCA & rCCA) + P300 + neuro + ErrP(cal+démo) câblés`, exit 0 |

Bonus, non demandés mais touchés par cette tâche : `python src/core/lsl_io.py` (`[lsl] VERDICT :
OK`, exit 0 — exerce `DecodedP300Publisher`) et `python src/core/modes/contract.py` (`[contract]
VERDICT : OK`, exit 0 — génère et compile un extrait client pour `p300.SPEC` comme pour tous les
autres modes du registre).

Les cinq commandes du brief ont été relancées une DERNIÈRE fois après restauration complète du
répertoire de travail (post-preuves rouge/vert et post-vérification du finding console/app.py),
toutes vertes, `git status` ne portant plus que `progress.md` (voir « Inquiétudes » n°3).

## Commit

```
git add src/core/modes/p300.py src/core/lsl_io.py src/core/modes/registry.py \
        src/core/modes/external.py src/core/server.py src/console/app.py
git commit -m "Publish the P300 as the engine's fourth mode, driven by external markers"
```

```
[main 37dce0c] Publish the P300 as the engine's fourth mode, driven by external markers
 6 files changed, 640 insertions(+), 20 deletions(-)
 create mode 100644 src/core/modes/p300.py
```

Second commit, séparé, sans rapport avec le code du mode (détail en « Inquiétudes » n°3) :

```
[main ec70ae7] Recover this chantier's logbook from an untracked .gitignore regression, again
 4 files changed, 710 insertions(+)
 create mode 100644 .superpowers/sdd/2026-08-17-marqueurs-entrants-p300/task-4-brief.md
 create mode 100644 .superpowers/sdd/2026-08-17-marqueurs-entrants-p300/task-4-report.md
 create mode 100644 .superpowers/sdd/2026-08-17-marqueurs-entrants-p300/task-5-brief.md
 create mode 100644 .superpowers/sdd/2026-08-17-marqueurs-entrants-p300/task-5-report.md
```

## Inquiétudes / ce que je laisse dehors

1. **`src/console/app.py` n'était PAS dans la liste de fichiers du brief, et j'ai dû le modifier
   quand même.** Son smoke porte un compte en dur des tuiles « appli pygame » (`chk(len(externes)
   == 3, ...)`) : avec le P300 qui rejoint le moteur, ce nombre tombe à 2. Sans le corriger,
   `python src/console/app.py --smoke` — une des cinq commandes EXIGÉES par ce brief — aurait
   échoué. Vérifié empiriquement (pas seulement déduit) : en remettant temporairement `== 3` après
   coup, le smoke échoue bien avec `ÉCHEC 2 tuiles pour les modes de l'appli pygame` et
   `[console-smoke] VERDICT : PROBLÈME` — puis remis à `== 2` et re-vérifié vert avant de committer.
   C'est exactement la même correction qu'avait déjà exigée l'arrivée du MI dans le moteur
   (commit `3e6ddb3`, `== 4` → `== 3`) : un précédent direct, pas une improvisation.
2. **Le réglage « Flux de marqueurs » (`stream_in`) du mode est actuellement cosmétique.** Le
   moteur (`EngineServer._ouvre_marker_inlet`) écoute TOUJOURS `MARKER_STREAM_DEFAULT` en dur,
   quel que soit ce qu'un client choisirait pour `stream_in` (qui n'a d'ailleurs qu'un seul choix
   possible : `(MARKER_STREAM_DEFAULT,)`). Le brief le décrit ainsi mot pour mot, donc je l'ai
   suivi tel quel — mais un étudiant qui changerait ce réglage en imaginant qu'il redirige
   l'écoute serait déçu. Rien à corriger dans le périmètre de cette tâche (ce n'est pas un bug de
   CE fichier), juste un point à garder en tête si une tâche future ajoute plusieurs flux de
   marqueurs nommés.
3. **`.superpowers/sdd/.gitignore` était de nouveau revenu à `*` (tout ignoré) dans l'arbre de
   travail, non commité, AVANT que je commence** — exactement la régression que le commit `1b48a5e`
   avait déjà réparée une fois ; le rapport de la tâche 4 la signale déjà comme préexistante sans y
   toucher (« pas à moi de trancher seul »). Cette fois, elle rendait `task-5-report.md` — CE
   fichier, explicitement demandé par le brief — invisible pour git (`git check-ignore -v` confirmé),
   ainsi que `task-4-brief.md`, `task-4-report.md` et `task-5-brief.md`, jamais ajoutés depuis leur
   création. Restauré via `git checkout HEAD -- .superpowers/sdd/.gitignore` (aucun diff contre
   HEAD, donc rien à commiter sur ce fichier) puis les quatre `.md` orphelins ajoutés et commités
   SÉPARÉMENT du code (`ec70ae7`), sur le même principe que `1b48a5e`. `progress.md`, lui, reste
   modifié et non touché : son contenu non commité est un récit du coordinateur, pas un fichier
   perdu par accident — même retenue que la tâche 4.
4. **Message résiduel dans `p300_models.py`** (« lance une calibration P300 depuis la console »)
   déjà signalé et explicitement différé par la tâche 4 (« la console n'a aucune page P300 »).
   Toujours vrai après cette tâche : la calibration P300 reste `kind="natif"`, jouée par l'appli
   pygame, jamais par la console. Fichier hors de ma liste, pas touché.
