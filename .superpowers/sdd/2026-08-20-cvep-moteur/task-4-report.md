# Task 4 — le flux publié et les compteurs de diagnostic

**Statut : terminé.** Commit **`d8fd7f7`** (base `0398913`), 8 fichiers, +917/−123, dont une
suppression (`core/modes/external.py`).

Le c-VEP est le **7e mode du registre et le 7e du moteur** — le catalogue ne porte plus une seule
entrée « appli pygame ».

**Autotests, tous relancés APRÈS le commit, codes de sortie relevés HORS PIPE :**

| commande | sortie |
|---|---|
| `python src/core/modes/cvep.py` | **0** — 32 assertions |
| `python src/core/lsl_io.py` | **0** |
| `python src/core/modes/registry.py` | **0** — 7 modes, dont 7 dans le moteur |
| `python src/core/server.py --smoke` | **0** — 17 blocs |
| `python src/console/app.py --smoke` | **0** — 140 assertions |
| `python src/research/app.py --smoke` | **0** (non-régression) |
| `cvep_models` · `cvep_decoder` · `cvep_code` · `contract` · `runtime` · `markers` · `p300` · `errp` · `mi` · `mi_models` · `p300_models` · `errp_models` | **0** (non-régression) |

Et une vérification d'INTÉGRATION, board synthétique, modèle réel :
`python src/core/server.py --synthetic --mode cvep --warmup 1 --duration 5` →

```
[server] c-VEP démarré — flux EEG_API_Unicorn_decoded_cvep (silencieux pendant le repos)
[server] marqueurs entrants : « EEG_API_Unicorn_stim » pas encore là — j'attends […]
[cvep] modèle « cvep_model.npz » (eCCA, seuils 0.26/0.09) — horloge attendue sur
       « EEG_API_Unicorn_stim », publication sur EEG_API_Unicorn_decoded_cvep (6 cibles)
[cvep] — (aucun marqueur d'horloge reçu — lance l'émetteur c-VEP, et vérifie qu'il publie
       sur le flux réglé)   AVANT +0.00  AV-DROITE +0.00  …
```

**`data/` intact** : 43 fichiers, **0 modifié le 2026-08-20** (vérifié par HORODATAGE, `git status`
ne prouvant rien sur un dossier gitignoré). `data/cvep_model.npz` toujours daté du 2026-07-21 16:15.

---

## 1. Ce qui a été livré

| Fichier | Ce qui change |
|---|---|
| `src/core/lsl_io.py` | `cvep_channel_labels()` + `DecodedCVEPPublisher` (+ `SUFFIXE`), section 9/9bis de l'autotest |
| `src/core/modes/cvep.py` | recâblage sur `cvep_models`, réglage `stream_in`, choix du décodeur, consommation de l'horloge, décodage, publication, compteurs par cause, 2 tests |
| `src/core/modes/registry.py` | `cvep.SPEC` remplace `external.CVEP` |
| `src/core/modes/external.py` | **supprimé** (dernière entrée partie) |
| `src/console/grid.py` | 3e échelle d'aperçu (`corr_min`), résumé de tuile propre au c-VEP |
| `src/console/live_views.py` | 4e rendu de la famille « actif » (`_update_correlations`) |
| `src/console/__init__.py` | `SSVEP_SPAN_SEUILS` → `SPAN_SEUILS` (le facteur d'affichage n'appartient à aucun mode) |
| `src/console/app.py` | fixture c-VEP + **assertions sur `tuiles["cvep"].apercu`**, tuile dégrisée |

### Le flux

`EEG_API_Unicorn_decoded_cvep`, ~5 Hz, voies
`["target_index", "confidence", "score_0" … "score_5"]`.
Métadonnées `decoding/` : `paradigm="c-VEP"`, `decision_scale="correlation"`,
`no_decision_index="-1"`, `code_len`, `refresh`, `n_targets`, `decoder`, `corr_min`, `margin`, `cv`.

`decision_scale="correlation"` est le champ qui compte : c'est la **troisième** échelle des modes à
cibles (z pour le SSVEP, log-odds pour le P300), et `corr_min = 0,26` lu sur l'échelle z du SSVEP
passerait pour du bruit. `cv` est **vide** quand le modèle n'en porte pas — jamais `-1`, qui se
lirait comme une justesse.

### Les compteurs

`state()` expose `decodages`, `sans_reference`, `reference_perimee`, `vote_non_conclu`,
`marqueurs_refuses`, `age_reference_s`, `corr_gagnant`, `corr_second`. Les quatre premiers se
somment au nombre de fenêtres traitées ; les trois derniers décrivent la dernière fenêtre seule et
valent `None` (jamais `0`, valeur plausible pour une corrélation) tant qu'aucune ne s'applique.

Le motif d'un `-1` est publié **en clair** dans `output["motif"]`, depuis une table du **moteur**
(`_MOTIFS_FR`) : la console l'affiche sans le traduire. Un second vocabulaire côté interface aurait
fini par ne plus dire la même chose que le terminal, sur la seule ligne qui indique quel geste
faire.

---

## 2. Les trois dettes léguées

**1. `stream_in` déclaré.** Fait, sur le patron exact de `p300.py`/`errp.py`
(`choices_fn=flux_de_marqueurs_visibles`, `default=MARKER_STREAM_DEFAULT`,
`affecte_decodage=False`). Deux assertions le vérifient : le contrat le porte, et le **runtime**
aussi (c'est `rt.params["stream_in"]` que `server._nom_flux_marqueurs` va lire).

**2. Recâblage sur `cvep_models`.** Fait, avec le piège signalé :
`cvep_models.modeles_disponibles(os.path.dirname(CVEP_MODEL_PATH))`, la constante étant relue à
chaque appel (variable de module, pas valeur capturée) — c'est ce qui rend le repointage du fixture
effectif. `_charger` a disparu au profit de `cvep_models.charger`. **Vérifié : `data/` est intact**
(43 fichiers, 0 modifié le 2026-08-20 ; `cvep_model.npz` toujours daté du 2026-07-21 16:15).

**3. Le partage d'inlet — verdict en §4.**

---

## 3. La méthode : rouge puis vert

### Étape 2 — le test des compteurs échoue avant le code

```
  ÉCHEC le modèle ET le flux de marqueurs se règlent (['model'])
  ÉCHEC le RUNTIME porte le nom du flux entrant, là où le moteur va le chercher (None)
  ÉCHEC l'état sépare les trois causes de -1 et expose l'âge de la référence (['channels',
        'family', 'id', 'instruction', 'label', 'output', 'params', 'phase', 'published',
        'rest_report', 'stream'])
KeyError: 'sans_reference'
EXIT=1
```

### Mutation 1 — les deux causes d'horloge dans un seul compteur

`core/modes/cvep.py`, `_run_step` : `if cause == "sans_reference": … else: …` remplacé par
`self._sans_reference += 1`.

```
  ÉCHEC ...et chaque compteur compte SA cause, pas le total ({… 'decodages': 0,
        'sans_reference': 3, 'reference_perimee': 0, 'vote_non_conclu': 3 …})
[cvep] VERDICT : PROBLÈME        EXIT=1
```

Retirée :

```
  OK   ...et chaque compteur compte SA cause, pas le total ({… 'sans_reference': 2,
       'reference_perimee': 1, 'vote_non_conclu': 3 …})
[cvep] VERDICT : OK              EXIT=0
```

### Mutation 2 — L'APPARIEMENT SCORE↔CIBLE (brief étape 6)

`core/cvep_decoder.py` : `self.lag_to_cmd = {c["lag"]: c for c in plan}` →
`{c["lag"]: plan[(i + 1) % len(plan)] for i, c in enumerate(plan)}`.

```
[cvep] CIBLE 3 (ARRIERE)   AVANT -0.10  AV-DROITE -0.04  AR-DROITE -0.08  ARRIERE +0.82  AR-GAUCHE -0.04  AV-GAUCHE +0.04
  ÉCHEC le moteur désigne la cible RÉELLEMENT affichée (3 au lieu de 2) — la phase est juste ET branchée au bon endroit
  ÉCHEC ...et c'est bien elle qui porte la meilleure corrélation ([-0.103, -0.036, -0.081, 0.815, -0.039, 0.044])
  ÉCHEC ...et c'est CE que le flux publie, pas seulement ce que l'écran montre ((3, 0.8154753631542023, [...], 506.284))
[cvep] VERDICT : PROBLÈME        EXIT=1
```

⚠️ **Le mode ne CASSE pas** : il désigne la cible voisine avec une confiance de **0,82**,
parfaitement normale. C'est exactement le défaut que la revue du P300 avait trouvé sur son propre
mode.

**Et rien d'autre ne l'attrape.** Mutation en place, mesuré :

| commande | code de sortie |
|---|---|
| `python src/core/cvep_decoder.py` | **0** |
| `python src/core/cvep_models.py` | **0** |
| `python src/core/server.py --smoke` | **0** |
| `python src/core/modes/cvep.py` | **1** |

Retirée (`git diff` vide sur `cvep_decoder.py`) :

```
  OK   le moteur désigne la cible RÉELLEMENT affichée (2 au lieu de 2) — la phase est juste ET branchée au bon endroit
  OK   ...et c'est bien elle qui porte la meilleure corrélation ([-0.036, -0.081, 0.815, -0.039, 0.044, -0.103])
[cvep] VERDICT : OK              EXIT=0
```

**Pourquoi ce test peut rougir** : l'indice publié vient **du décodeur**
(`self._indice[cible["name"]]`) et les scores sont relus par le nom que le décodeur a attaché à
chaque corrélation. Refaire dans le mode une recherche par `lag` aurait créé une seconde table
d'appariement, qui aurait continué de désigner la bonne cible même avec celle du décodeur décalée —
la mutation serait devenue indétectable.

### Mutation 3 — la tuile console emprunte la formule du SSVEP

`console/grid.py` : `span=min(SPAN_SEUILS * corr_min, 1.0)` → `max(...)` (le plancher du SSVEP).

```
  ÉCHEC la tuile c-VEP met ses corrélations à l'échelle de SON `corr_min` publié (span=1.0 pour corr_min=0.26)
  ÉCHEC ...donc NI le seuil du SSVEP, NI le plafond 1,0 de la formule du SSVEP, qui écraserait 0,21 et 0,33 dans le tiers bas de la barre (span=1.0, Z_MIN=2.5)
  ÉCHEC la tuile et la page remplissent leurs barres à la MÊME hauteur ([11, 19, 33, 8, 21, 12] contre [21, 36, 63, 15, 40, 23])
[console-smoke] VERDICT : PROBLÈME       EXIT=1
```

Retirée : `span=0.52`, tuile et page à `[21, 36, 63, 15, 40, 23]`, `EXIT=0`.

⚠️ **Le piège du c-VEP est le SYMÉTRIQUE de celui du P300.** Le P300 n'avait pas de seuil, donc le
repli tombait sur `Z_MIN`. Le c-VEP en **publie** un — rien n'empêchait donc de lui appliquer la
formule du SSVEP, dont le `max(…, 1.0)` est un **plancher** (un z n'a pas de plafond). Sur des
corrélations bornées à 1, ce plancher devient un plafond : 0,21 et 0,33 — les deux chiffres qui
séparent une décision juste d'une fausse dans la seule séance mesurée — s'écrasent dans le tiers bas
de la barre. La correction est un `min` au lieu d'un `max`, et la raison est écrite à côté.

---

## 4. Le partage d'inlet convient-il à une horloge ? — VERDICT

**Oui, il convient — la mécanique partagée était déjà assez générique.** Vérifié point par point :

| | |
|---|---|
| **Aiguillage** | `markers_murs` filtre sur `d["mode"]`. Un tic d'horloge `{"mode":"cvep"}` n'est jamais vu par le P300 ni l'ErrP, et réciproquement. |
| **Curseur** | un par mode. Le débit très différent (~1 Hz ici, ~7 Hz pour le P300) ne fait pas se marcher dessus. |
| **Maturité** | `post_s` est un **argument d'appel**, pas une propriété du mode. Le c-VEP demande `post_s=0.0` pendant que le P300 demande 0,80 dans la même boucle. |
| **Purge** | `_purge_marqueurs` coupe au `min(curseur)` des écouteurs actifs ; l'horloge consomme à chaque tour, elle ne bloque personne. À ~0,95 marqueur/s, le seuil de 4096 n'est atteint qu'après ~72 min en solo. |

**La seule chose que j'ai eu à décider, et elle mérite d'être lue** : `post_s=0.0`. Réclamer
`marker_epoch_s` (2,1 s) comme le font le P300 et l'ErrP retarderait chaque référence d'autant, sur
des références qui ne valent que `CVEP_PEREMPTION_CYCLES` × 1,05 = **3,15 s**. Le mode aurait passé
le plus clair de son temps en `reference_perimee` sans qu'une seule ligne soit fausse. Une assertion
l'épingle (`post_s_recus == {0.0}`).

**Une limitation à écrire noir sur blanc, qui n'est pas nouvelle mais devient atteignable.** Un seul
inlet existe pour tout le moteur, résolu **par nom**. Le P300 et l'ErrP peuvent partager un émetteur
(c'est même le cas d'usage : le feedback ErrP suit la sélection P300). Le c-VEP, lui, exige un
stimulus **verrouillé à la frame**, donc un programme séparé — et « c-VEP + ErrP » (détecter l'erreur
que la sélection c-VEP vient de faire) est une combinaison plausible en TP. Deux émetteurs distincts
publiant sous le **même** nom sont arbitrés par `MarkerInlet._arbitre` : **un seul est écouté**, de
façon déterministe et bruyante. Sous des noms **différents**,
`server._nom_flux_marqueurs` signale le désaccord et **un seul nom gagne**.

→ **Je ne l'ai pas contourné en silence** ; je ne l'ai pas corrigé non plus, parce que le corriger
veut dire passer d'un inlet unique à un inlet **par nom de flux réclamé**, ce qui touche `server.py`,
`markers.py` et les trois modes — hors périmètre de cette tâche, et sans utilisateur aujourd'hui
(l'émetteur c-VEP arrive à la tâche 5). **À trancher explicitement au chantier suivant si l'on veut
un jour faire tourner c-VEP + ErrP ensemble.**

---

## 5. Écarts au brief, signalés plutôt que masqués

**1. Le test de bout en bout passe par le VRAI `_run_step`, pas par un `decider_sur(eeg, ts)`.**
Le brief esquissait une méthode `rt.decider_sur(eeg, ts)`. Un helper appelé par le test ET par
`_run_step` n'aurait pas prouvé que `_run_step` lit correctement `engine.recent`/`recent_ts` ni
qu'il sélectionne `model.channels`. Le test monte donc un faux moteur (tampon horodaté + file de
marqueurs) et appelle `rt._run_step(moteur, lsl_ts=…)` : la chaîne exercée va du marqueur au
`push()` du publieur.

**2. ⚠️ L'INSTANT auquel la phase se lit — le point le plus délicat, et le brief avait raison sans
le dire.** `CVEPModel.scores` documente `phase` comme la position du code au **DÉBUT** des cycles
repliés. L'écrire littéralement est **faux en pratique** : le début de la fenêtre est 2,1 s dans le
passé, le dernier marqueur d'horloge a moins de 1,05 s — la référence tombe donc presque **toujours
APRÈS** lui, `phase_a` voit un `age < 0` et refuse de décoder **à chaque fenêtre**. On lit donc la
phase à `t_fin` : les cycles repliés couvrent exactement `n_cycles` périodes du code, la phase y
revient à l'identique. Le placement des marqueurs du brief
(`ts[0] + k * len(code) / 60.0`, l'horloge VRAIE, pas un multiple de `n_cyc` échantillons) est
exactement ce qui rend les deux lectures cohérentes — mesuré : la phase à `t_fin` vaut 0, et le
début des cycles repliés est bien à la position 0 du code.

**3. `external.py` supprimé, pas vidé.** Le brief disait « retirer l'entrée c-VEP ». C'était la
dernière : un module qui ne déclare plus rien est du code mort. Les statuts `appli_pygame`/`prevu`
restent vérifiés par `registry.check()`, donc le prochain mode décrit avant d'être fait n'a qu'à
déclarer son `ModeSpec`. Une citation pendante de ce fichier dans `console/app.py` a été corrigée.

**4. `SSVEP_SPAN_SEUILS` renommé `SPAN_SEUILS`** (`console/__init__.py` + 3 sites). Le facteur 2
est une convention d'**affichage**, pas une constante du SSVEP — et le c-VEP l'utilise désormais.
Garder un nom de mode dessus, c'est réinstaller le raisonnement qui a laissé `Z_MIN` mettre à
l'échelle des log-odds pendant deux chantiers.

**5. Trois ajouts hors mandat strict, chacun réparant un défaut réel :**
- **`tick` redéfini** : l'horloge est encaissée **pendant la chauffe**. Sans ça, le premier
  `_run_step` avale 15 s d'arriéré, dont une douzaine de marqueurs déjà sortis du tampon EEG —
  comptés en `engine.marqueurs_perdus`, un compteur qui signale une **vraie** perte de données. Une
  alarme fausse à chaque démarrage apprend à ignorer l'alarme. (Contrairement au P300, on ne les
  **jette** pas : une horloge n'a pas besoin d'être « bonne » pour être à l'heure, et la première
  fenêtre décodée l'est donc avec une phase fraîche.)
- **`_resume` de la tuile** : le c-VEP tombait dans la branche `scores`, qui lui aurait affiché
  `cible 2 · 0 Hz` — littéralement le « CIBLE 3 · 0 Hz » du P300 rendu en SSVEP. Ce mode ne cherche
  pas une fréquence mais une phase.
- **`_reset_rest` efface la référence de phase** : « refaire le repos » se fait en touchant les
  électrodes ; l'émetteur a eu tout le temps d'être relancé.

---

## 6. Ce qui reste DEHORS

- **Rien n'a été vérifié au casque**, et **l'émetteur c-VEP n'existe pas encore**
  (`research/cvep_stimulus.py` = tâche 5). Aucun marqueur `{"mode":"cvep","event":"cycle"}` n'est
  publié par quoi que ce soit dans le dépôt aujourd'hui : le mode a été exercé sur EEG **synthétique**
  et sur board de test.
- **Les seuils ne sont pas encore réglables à chaud** (`corr_min`/`margin` viennent des constantes
  du décodeur) — c'est la tâche 7.
- **La justesse du décodage n'est pas rejugée** : ce qui est prouvé ici est que la chaîne désigne
  la cible affichée sur du synthétique à SNR 0 dB, pas que le c-VEP marche mieux ou moins bien
  qu'avant.
- **`docs/SPEC.md`, `CLAUDE.md` et `docs/recette.md` n'ont pas été touchés** : ils annoncent encore
  le c-VEP comme « le dernier mode que le moteur ne sait pas faire », ce qui est maintenant faux.
- Les deux assertions « tuiles grisées » de `console/app.py --smoke` sont désormais **vides** (plus
  aucun mode hors moteur). Elles restent parce qu'elles ne vieillissent pas ; une assertion inverse
  (tout est dégrisé) prend le relais.

---

## 7. Doutes

1. **`vote_non_conclu` est un nom trompeur.** Il vient du brief et le test s'appuie dessus, donc je
   l'ai gardé — mais il n'y a **aucun vote temporel** dans ce mode : le compteur compte les fenêtres
   dont la corrélation du gagnant est sous `corr_min`, ou dont l'écart au deuxième est sous `margin`.
   `CVEP_VOTE_LEN`/`CVEP_MIN_VOTES` existent dans `config.py` et **ne sont lus par personne** dans le
   moteur. Si un vote glissant arrive un jour, ce nom sera occupé par autre chose.
2. **La marge d'une frame entre les deux conventions de phase.** Le modèle travaille en
   `n_cyc = 262` échantillons par cycle (`round(262,5)` arrondit au PAIR — il SOUS-compte d'un
   demi-échantillon), l'horloge en 262,5 (63 frames à 60 Hz). Sur une fenêtre de deux cycles
   l'écart est de ~1 frame (17 ms), sans effet sur l'identification (les lags voisins sont à 175 ms).
   Je le note parce que c'est le genre d'écart qui devient visible si `CVEP_DECISION_CYCLES` monte.
3. **`age_reference_s` est lu à `t_fin`, la phase aussi** — mais si un jour la phase repassait à
   `t_debut`, les deux décriraient des instants différents et le tableau de diagnostic mentirait d'une
   fenêtre. C'est documenté dans `_run_step` ; ça n'est pas garanti par un test.
4. **Le rCCA n'est exercé par aucun test de ce fichier.** `_DECODEURS` l'aiguille, `cvep_models`
   prouve que la bonne classe est rendue, mais aucun test de `modes/cvep.py` ne fait décoder un
   `RCCAModel` par le mode. Le seul modèle rCCA du dépôt est refusé (codes Gold), donc la fixture
   aurait dû en fabriquer un — coûteux (~0,3 s de refit pyntbci) pour une garantie que le contrat
   partagé `classify(fenêtre, phase)` donne déjà. À faire si le rCCA est un jour retenu en séance.

---
---

# Tour de correction 1 — commit `19118eb`

Six constatations traitées (Important 1-3, Minor 4, 5, 8). Minors 6, 7 et 9 non traités, comme
demandé.

**Autotests relancés APRÈS le commit, codes de sortie hors pipe :** `modes/cvep.py` **0** (46
assertions, contre 32), `lsl_io.py` **0**, `modes/registry.py` **0**, `modes/contract.py` **0**,
`modes/mi.py` **0**, `server.py --smoke` **0** (17 blocs), `console/app.py --smoke` **0** (147
assertions, contre 140), `research/app.py --smoke` **0**. Intégration `--mode cvep` sur board
synthétique : le mode démarre, annonce ses seuils et publie. **`data/` intact** : 43 fichiers,
0 modifié.

## Important 1 — le vote glissant existe enfin dans le moteur

`CVEP_VOTE_LEN`/`CVEP_MIN_VOTES` (3 et 2) sont lus par `CVEPRuntime`, sur le patron exact de
`core/modes/mi.py` : `deque(maxlen=params["vote_len"])`, `Counter` sur les noms de cibles (le
`None` d'une fenêtre rejetée y compte, comme chez le MI), deux `Param(kind="int")` dont
`min_votes` porte `constraints=("votes_atteignables",)` — la contrainte croisée que
`contract.validate` évaluait déjà et que personne n'utilisait hors du MI.

**Rien dans le publieur** : `lsl_io.py` reste un transport sans état. En revanche `min_votes` et
`vote_len` **voyagent dans ses métadonnées** (`votes=(min, len)`, même signature que
`DecodedMIPublisher`) — sans eux, un client mesure une latence de `vote_len / 5 Hz` sans pouvoir
l'expliquer et croit le décodage lent.

Deux conséquences que j'ai tranchées explicitement :

- **`confidence` décrit désormais le VOTE**, pas la dernière fenêtre : c'est la moyenne des
  corrélations des fenêtres VOTANTES. Chacune valant au moins `corr_min` par construction, leur
  moyenne aussi — l'invariant « `confidence >= corr_min` quand `target_index >= 0` » est tenu par
  construction, pas par surveillance. Sans ça, un même échantillon dirait « CIBLE 2 » avec une
  corrélation SOUS le seuil que le flux annonce lui-même, et un client qui refiltre sur ce seuil
  (le geste naturel) jetterait les fixations stables. Documenté dans `DecodedCVEPPublisher`.
- **`_reset_rest` vide aussi la file de votes** : ses fenêtres décrivent un montage qu'on vient de
  toucher.

## Important 2 — deux compteurs, deux gestes

**Noms retenus : `sous_les_seuils` et `vote_non_conclu`.**

| compteur | ce qu'il dit | le geste |
|---|---|---|
| `sous_les_seuils` | cette fenêtre n'avait **aucun candidat** (sous `corr_min`, ou écart sous `margin`) | regarder le **signal** : contact, saline, la personne fixe-t-elle quelque chose ? |
| `vote_non_conclu` | elle en avait un, mais les fenêtres récentes **ne s'accordent pas** | regarder la **stabilité du regard** |

Les cinq compteurs (`decodages`, `sans_reference`, `reference_perimee`, `sous_les_seuils`,
`vote_non_conclu`) **partitionnent** les fenêtres traitées : chacune en incrémente exactement un.
`_MOTIFS_FR` porte les deux phrases, et le test de la §6 vérifie explicitement que
`vote_non_conclu == 0` quand les corrélations sont plates — un chiffre non nul y dirait l'inverse
et enverrait chercher un problème de fixation là où il y a un problème de signal.

## Important 3 — la branche « tuile grisée » recouverte

Une tuile est bâtie sur un `ModeSpec` **fabriqué** (`status="prevu"`, `unavailable=…`), plus une
seconde en `status="moteur"` pour le **contraste** — sans elle, les quatre assertions passeraient
sur une tuile qui masquerait ses boutons pour tout le monde. Vérifiés : grisage, message
`unavailable` à la place du résumé, statut rendu en français, les trois boutons masqués, et le fait
qu'un état reçu par erreur ne la réanime pas.

## Minor 4 — les deux comportements que personne n'attrapait

### Mutation A — l'override de `tick` supprimé (l'horloge pendant la chauffe)

```
  ÉCHEC pendant la CHAUFFE, l'horloge est encaissée : le curseur du moteur avance et la phase
        est déjà fraîche quand le décodage commence ([], None)
[cvep] VERDICT : PROBLÈME        EXIT=1
```

Retirée → `([0.0], 505.25)`, `EXIT=0`.

### Mutation B — `_reset_rest` n'efface plus la référence de phase

```
  ÉCHEC « refaire le repos » OUBLIE la référence de phase — sinon le mode déciderait sur une
        horloge périmée (505.25)
[cvep] VERDICT : PROBLÈME        EXIT=1
```

Retirée → `(None)`, `EXIT=0`. C'est la plus gênante des deux : après un « refaire le repos »
(le geste qu'on fait précisément parce qu'on vient de toucher les électrodes), le mode aurait
décodé sur une horloge qui n'a plus cours, en publiant des corrélations d'apparence normale.

### Mutation C — `min_votes` ignoré (bonus, sur le vote lui-même)

`compte < int(self.params["min_votes"])` → `compte < 1` : **5 assertions rouges**, dont
« une SEULE fenêtre, même franche, ne suffit pas à émettre » et « des fenêtres franches qui se
CONTREDISENT n'émettent rien non plus ». `EXIT=1`, puis vert.

## Minor 5 — 262, pas 263

`int(round(63 × 250 / 60))` = `round(262,5)` = **262** (arrondi au pair). Le modèle **sous-compte**
d'un demi-échantillon par cycle. Commentaires corrigés dans `modes/cvep.py` (`n_cyc` du test et
`_horloge`) ; `cvep_decoder.py` disait déjà 262. **Le §7-2 ci-dessus est corrigé en conséquence** :
lire « le modèle travaille en 262 échantillons par cycle, l'horloge en 262,5 » — la conclusion (~1
frame sur deux cycles, sans effet à 6 cibles où les lags voisins sont à 175 ms) ne change pas.

## Minor 8 — la justification de `post_s=0.0`, réécrite avec le bon chiffre

Ma seconde raison était fausse au sens littéral. Le texte dit maintenant : avec
`post_s = marker_epoch_s` (2,1 s), la référence la plus fraîche aurait toujours entre **2,1 s et
3,15 s** d'âge et la péremption tombe à `> 3,15` s — le mode ne serait donc **pas cassé** avec un
émetteur parfait, il fonctionnerait avec **zéro marge**, et le premier marqueur sauté le ferait
basculer. La première raison suffit d'ailleurs seule : `post_s` est un argument d'appel, et il n'y
a rien à attendre *après* un tic d'horloge.

## Ce que ce tour ajoute au « reste DEHORS »

- Le vote **n'a jamais tourné au casque** : ses deux constantes viennent de l'écran pygame, où
  elles étaient réglées pour la même cadence et la même géométrie, mais ce n'est pas une mesure
  refaite ici.
- **Le doute n° 1 de la §7 est levé** (le nom `vote_non_conclu` désigne maintenant un vote réel) ;
  les doutes 2, 3 et 4 restent ouverts tels quels.

---
---

# Tour de correction 2 — commit `39c249c`

Trois points, tous traités.

**Autotests, codes de sortie hors pipe :** `modes/cvep.py` **0** (48 assertions, contre 46),
`lsl_io.py` **0**, `modes/registry.py` **0**, `modes/runtime.py` **0**, `server.py --smoke` **0**,
`console/app.py --smoke` **0**. `data/` intact.

## Le trou : `_votes.clear()` n'était protégé par rien

Le re-relecteur a raison, et le défaut est bien le MÊME que celui du tour 1, revenu une ligne plus
bas sur l'état que ce tour venait d'ajouter. Assertion ajoutée, **comportementale** et non sur
`len(rt._votes)` : une file vidée par un autre chemin, ou un vote qui cesserait de lire sa file,
laisserait passer un test écrit sur l'attribut.

Le scénario tient en trois lignes — une fenêtre franche AVANT le repos laisse un vote ; si
« refaire le repos » ne vide pas la file, **une seule fenêtre neuve** atteint ensuite `min_votes`.

### Mutation D — `_reset_rest` ne vide plus la file de votes

```
  ÉCHEC ...et « refaire le repos » VIDE la file de votes : la première fenêtre d'après ne peut
        pas émettre en s'appuyant sur des votes d'avant
        ({'target_index': 2, 'confidence': 0.839, …},
         {… 'decodages': 1, 'sous_les_seuils': 0, 'vote_non_conclu': 0 …})
[cvep] VERDICT : PROBLÈME        EXIT=1
```

`decodages: 1` sur une SEULE fenêtre neuve, avec une confiance de **0,839** — le mode émet une
cible en s'appuyant sur des votes qui décrivent un montage qu'on vient de démonter, et rien ne le
dit. Retirée → `target_index: -1`, `vote_non_conclu: 1`, `decodages: 0`, `EXIT=0`.

## Deux docstrings recalées sur leur propre code

- `state()` disait « les quatre premiers se somment » → **cinq**, et j'en profite pour lever
  l'ambiguïté qui restait : `marqueurs_refuses` compte des **marqueurs**, pas des fenêtres, il
  n'entre donc pas dans cette somme.
- `_phase_et_cause` disait « la docstring du module en compte trois » → **quatre**, et nomme les
  deux causes non-horloge (`sous_les_seuils`, `vote_non_conclu`) au lieu d'une.

## ⚠️ Constatation pour la revue finale de branche — `core/modes/mi.py`

Signalée par le re-relecteur, **non traitée ici** (hors périmètre) : `MIRuntime` a le **même angle
mort**. Ses tests vident `_votes` à la main au lieu de repasser par `begin_rest`/`_reset_rest`,
donc rien ne protège l'effacement de sa file de votes au repos. Le scénario est identique — après
un « refaire le repos », une seule fenêtre neuve pourrait suffire à publier une intention en
s'appuyant sur des votes d'avant. À traiter dans une tâche à part, avec la même preuve rouge.
