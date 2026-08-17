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

---

# Tour de correction 1 — rapport

Statut : **DONE**
Commits : `fec9b08` (le code) et `1f702f9` (récupération du carnet, sans rapport avec le code)
Base : `37dce0c` (le commit initial de cette tâche)

Deux relecteurs en parallèle, conformité au brief ✅ des deux côtés, quatre constats (un CRITIQUE,
trois IMPORTANT). Les quatre traités, aucun contesté.

## CRITIQUE — la contamination entre manches

`_epoques`/`_cibles` n'avaient ni borne ni notion de manche. Une application externe qui plante en
pleine manche (le cas normal d'un plantage) ne renvoie jamais `round_end` : ses flashs restaient
ORPHELINS pour toujours. Si l'application redémarre et flashe une manche neuve sans avoir renvoyé
le `round_end` de l'ancienne, les nouveaux flashs s'empilaient sur les orphelins — le garde de
couverture (`len(par_cible) < n_targets`) ne vérifie que « chaque cible a flashé au moins une
fois », pas « ces flashs viennent de la même manche ». Une contamination pouvait donc atteindre
`select()` et publier une cible choisie avec une confiance normale, silencieusement fausse.

**Corrigé par `P300Runtime._verifie_abandon`**, appelée à CHAQUE `_run_step` (pas seulement quand
un marqueur arrive — c'est `lsl_ts`, qui avance à chaque tour de la boucle du moteur, qui rend le
plantage détectable même quand plus aucun marqueur n'arrive jamais) :
- **délai d'abandon** : `P300_ROUND_TIMEOUT_S` (nouvelle constante, `core/config.py`, 10,0 s) sans
  flash accepté ;
- **plafond dur** : `P300_N_TARGETS * P300_REPS * 2` = 96 époques accumulées.

Les deux comparent des horodatages de MARQUEURS à `lsl_ts` — jamais `time.time()`, conformément à
la règle du projet (`ModeRuntime` : un runtime ne lit jamais l'horloge lui-même).

### Preuve rouge-puis-vert (le scénario de contamination, pas juste « ça abandonne »)

Bug injecté dans `_verifie_abandon` : `trop_vieille = False` (retire le délai d'abandon, garde le
plafond intact). `python src/core/modes/p300.py` :

```
  OK   les 3 flashs de la manche avortée sont bien en attente, round_end jamais arrivé (3)
  ÉCHEC la manche avortée est jetée après le délai, sans aucun nouveau marqueur (3 époque(s) restante(s))
  ÉCHEC l'abandon est COMPTÉ (0)
  ÉCHEC la manche neuve n'hérite d'AUCUN flash orphelin de l'avortée : une époque par cible, jamais deux ({0: 2, 1: 2, 2: 2, 3: 1, 4: 1, 5: 1})
  OK   le plafond (96 époques) abandonne aussi, sans attendre le délai (1)
[p300] VERDICT : PROBLÈME
```

La ligne qui compte : `{0: 2, 1: 2, 2: 2, 3: 1, 4: 1, 5: 1}` — les cibles 0/1/2 (celles de la
manche avortée) portent CHACUNE deux époques, contre une pour 3/4/5 : c'est la contamination
elle-même, mesurée, pas déduite. Le test du plafond (mécanisme indépendant) reste vert, preuve que
la mutation n'a touché QUE le délai. Remis en état, `python src/core/modes/p300.py` :

```
[p300] VERDICT : OK
```

## IMPORTANT — panne n°4 réarmée par session, jamais par manche

`if self._refus_cible == 1` comparait un compteur JAMAIS réinitialisé : toute récidive plus tard
dans la séance, même dans une manche sans rapport, était comptée mais ne s'imprimait plus jamais.
**Corrigé** : `_refus_cible` est remis à 0 dans `_vider_manche` (donc à chaque fermeture de
manche, propre ou abandonnée). Le test d'origine ne pouvait pas l'attraper : il ne jouait qu'UNE
manche. Réécrit en DEUX manches séparées par un `round_end` : la seconde réimprime
l'avertissement, preuve que la garde s'est réarmée et non « la première de la session ».

## IMPORTANT — les compteurs n'ont aucun filet hors du terminal

`P300Runtime.state()` (nouveau, appelle `super().state()` puis ajoute) expose désormais
`refus_cible`, `epoques_perdues`, `manches_abandonnees` — un client qui n'a pas la console ouverte
au bon instant peut les lire quand même.

## IMPORTANT — `no_decision_index` manquant des métadonnées LSL

Une ligne dans `DecodedP300Publisher.__init__` : `desc.append_child_value("no_decision_index",
"-1")`, jumeau exact de `DecodedMIPublisher`. Vérifié dans `lsl_io.py` en lisant directement
`pub.outlet.get_info().desc().child("decoding").child_value("no_decision_index")`.

## IMPORTANT — `stream_in` ne faisait rien

`_ouvre_marker_inlet` avait `MARKER_STREAM_DEFAULT` en dur ; la seule lecture de `stream_in` dans
tout le moteur était le `print` du mode lui-même. **Corrigé par `EngineServer._nom_flux_marqueurs`**
(nouvelle méthode) : lit `stream_in` sur les modes ACTIFS qui consomment des marqueurs
(`marker_epoch_s > 0`), retombe sur `MARKER_STREAM_DEFAULT` pour un mode qui ne le déclare pas, et
**dit bruyamment** un désaccord entre deux modes actifs plutôt que d'en choisir un en silence.
`_ouvre_marker_inlet` l'appelle désormais au lieu du nom en dur.

**Constat mesuré en le corrigeant, qui va plus loin que la consigne** : `self.marker_inlet` n'est
JAMAIS remis à `None` par `_stop_mode` — confirmé par lecture de `server.py` (aucune occurrence
hors `__init__` et hors code de test). Une fois créé, il vit pour tout le PROCESSUS moteur, jamais
par mode. Donc changer `stream_in` et **redémarrer le mode** (stop puis start du P300, moteur
resté vivant) n'a AUCUN effet — contrairement à ce que suggérait la consigne (« redémarrer le
mode »). Seul un moteur relancé (nouveau processus) reprend un nouveau nom. Le texte d'aide dit
cette version précise, pas la version suggérée.

### Preuve rouge-puis-vert (bout en bout, pas seulement le helper isolé)

Bug injecté dans `_ouvre_marker_inlet` : `nom = MARKER_STREAM_DEFAULT` (remis en dur, comme avant
ce tour). `python src/core/server.py --smoke` :

```
  ÉCHEC _ouvre_marker_inlet crée son inlet sur le nom du mode actif, pas le défaut en dur (EEG_API_Unicorn_stim)
[smoke-marqueurs-stream-in] VERDICT : PROBLÈME
```

**Exactement 1 ÉCHEC sur toute la suite** (94 → 102 `chk(` dans `server.py`, comptés avant/après —
voir plus bas) : les 15 autres sous-verdicts restent verts, la casse est isolée à l'endroit exact
du correctif. Remis en état, `python src/core/server.py --smoke` : les 16 sous-verdicts (dont
`[smoke-marqueurs-stream-in]`) repassent au vert, exit 0.

## Comptage des assertions, avant/après ce tour (rien retiré nulle part)

| Fichier | Avant | Après | Détail |
|---|---|---|---|
| `src/core/modes/p300.py` (`chk(`) | 33 | 46 | +13, réparties entre la preuve critique (contamination + plafond), la panne n°4 réécrite en deux manches, et l'exposition dans `state()` |
| `src/core/server.py` (`chk(`) | 94 | 102 | +8, tous dans la nouvelle `_smoke_marqueurs_stream_in` |
| `src/core/server.py` (`resultats`) | 15 | 16 | + `_smoke_marqueurs_stream_in()` |
| `src/core/lsl_io.py` (`assert`) | 2 | 3 | + vérification `no_decision_index` |

Compté par diff ENTRE COMMITS, pas par relecture (`git diff 37dce0c fec9b08 -- <fichier> | grep
'^+' | grep -c 'chk('` contre le même avec `'^-'`) : **13 lignes `chk(` ajoutées, 0 retirée** dans
`p300.py` ; **8 ajoutées, 0 retirée** dans `server.py`. Le seul texte de message changé est celui
de tests RESTRUCTURÉS (panne n°4, désormais deux manches au lieu d'une, chacune fermée par son
propre `round_end`) pour rester exact dans le nouveau contexte — jamais leur condition.

## Tests — relancés un par un, aucun moteur laissé tournant

| Commande | Résultat |
|---|---|
| `python src/core/modes/p300.py` | 46 `OK`, `[p300] VERDICT : OK`, exit 0 |
| `python src/core/lsl_io.py` | `[lsl] VERDICT : OK`, exit 0 |
| `python src/core/modes/registry.py` | `[registry] VERDICT : OK`, exit 0 |
| `python src/core/server.py --smoke` | 16 sous-verdicts verts, exit 0 |
| `python src/console/app.py --smoke` | `[console-smoke] VERDICT : OK`, exit 0 |

Bonus (non demandés ce tour, revérifiés par prudence vu l'ampleur du correctif) :
`python src/core/modes/contract.py` et `python src/research/app.py --smoke`, tous deux verts.

## Inquiétudes de ce tour

1. **`stream_in` reste sans effet tant que le moteur tourne déjà** — même après ce correctif, un
   changement de ce réglage n'est repris qu'au PROCHAIN démarrage du moteur (processus), jamais en
   redémarrant seulement le mode. Écrit dans l'aide du réglage et dans la docstring de
   `_ouvre_marker_inlet`, mais ça reste une limite RÉELLE, pas seulement documentée — un futur
   chantier qui voudrait un vrai changement à chaud devrait faire de `marker_inlet` une ressource
   par NOM plutôt que par moteur (plusieurs inlets simultanés), pas un simple recâblage.
2. **Le plafond dur (96 époques) n'a pas de constante dédiée dans `core/config.py`** — dérivé en
   ligne dans `p300.py` (`P300_N_TARGETS * P300_REPS * 2`) sur instruction explicite du tour de
   correction (« dérivé du protocole », pas « nouvelle constante », contrairement au délai
   d'abandon qui EN demandait une explicitement). Si `P300_N_TARGETS`/`P300_REPS` changent un
   jour, ce plafond bouge avec eux automatiquement — voulu, mais à vérifier si un futur chantier
   veut le régler indépendamment.
3. **`.superpowers/sdd/.gitignore` est retombé à `*` (tout ignoré) une TROISIÈME fois**, non
   commité, entre la fin du tour précédent et le début de celui-ci — restauré à nouveau
   (`git checkout HEAD --`, aucun diff) et le fichier qu'il cachait cette fois
   (`task-6-brief.md`, déjà écrit et complet, pas un brouillon) récupéré dans un commit séparé
   (`1f702f9`). Ce n'est plus un incident isolé : quelque chose (probablement le skill
   `subagent-driven-development`, dont le fichier cite lui-même le comportement par défaut)
   réécrit ce fichier à CHAQUE invocation. Une réparation mécanique à chaque tâche n'est pas une
   solution — vaudrait le coup d'un correctif qui empêche la réécriture plutôt que de la
   constater après coup.
4. **Reportés tels quels, comme demandé** : branche `choisi is None` morte tant que
   `P300_SELECT_MARGIN` vaut 0 · contrôle structurel de `registry.check()` sans test dédié · son
   message unique pour deux cas distincts · un futur mode marqueur sans `pre_s`/`post_s` passerait
   `check()` sans alerte. Rien touché sur ces quatre points.
