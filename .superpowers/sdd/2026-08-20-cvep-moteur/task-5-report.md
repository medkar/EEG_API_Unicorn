# Tâche 5 — l'émetteur c-VEP, et LE test qui porte le chantier

**Statut : terminé.** `src/research/cvep_stimulus.py` créé (850 lignes), `src/research/__init__.py`
mis à jour. Base `39c249c`.

---

## 1. Ce qui a été livré

`python src/research/cvep_stimulus.py [--windowed] [--refresh N] [--seconds N] [--seed N]
[--no-wait] [--smoke]` — mêmes options que `p300_stimulus.py` et `errp_stimulus.py`.

- Affiche la couronne de `CVEP_N_TARGETS` cibles clignotant selon la m-séquence décalée
  (`core.cvep_code.build_targets` / `is_on` — le MÊME appel que fait le moteur, donc aucune
  divergence possible sans que `core/config.py` change pour les deux).
- Publie `{"mode": "cvep", "event": "cycle", "refresh": <float>}` à chaque redémarrage du code
  (63 frames, ~1/s), **après** `pygame.display.flip()`.
- **N'ouvre pas le casque** : aucun import BrainFlow, aucune ouverture de carte. Se lance dans un
  second terminal, à côté du moteur.
- `--smoke` exécute réellement `run()` sous `SDL_VIDEODRIVER=dummy` (deux passages, C1 et C2).

### Trois écarts délibérés avec le patron `errp_stimulus.py`

1. **Le clignotement NE S'ARRÊTE PAS pendant la chauffe du moteur.** L'ErrP tient un écran statique
   parce que `errp._jeter_marqueurs_de_chauffe` JETTE tout ce qui arrive alors. Le c-VEP fait
   l'inverse et c'est écrit dans `CVEPRuntime.tick` : il ENCAISSE les marqueurs de chauffe (« une
   horloge n'a pas besoin d'être bonne pour être à l'heure »). Les lui donner fait avancer son
   curseur de marqueurs (sinon la douzaine déjà sortie de son tampon compte en `marqueurs_perdus`,
   une alarme fausse à chaque démarrage) et donne une phase FRAÎCHE à sa première fenêtre décodée.
   Durée LUE dans `SPEC.rest`, pas devinée : `warmup_s = SSVEP_WARMUP_S` (15 s), `duration_s = 0.0`
   → `ATTENTE_MOTEUR_S = 15 s`. Seul le décompte de `--seconds` attend ; un bandeau le dit.
2. **Pas de `valide_reglages`.** Rien à régler ici ne touche le décodage : géométrie, code et lags
   viennent tous de `build_targets()`. Le seul réglage dangereux est `--refresh`, et le moteur le
   refuse lui-même (`maj_reference`, tolérance 1 Hz) — au bon endroit, celui qui connaît le modèle.
3. **`--seed` graine les CONSIGNES.** Le c-VEP n'a aucun aléa de protocole. Plutôt qu'un `--seed`
   décoratif, il pilote la cible consignée (cercle à 1,7× le rayon, la valeur et la raison de
   `ui.draw_ring`), qui tourne toutes les `2 * CVEP_DECISION_CYCLES` cycles. La consigne est
   AFFICHÉE et IMPRIMÉE avec son horodatage LSL (`t=…`) mais **ne part jamais sur le réseau** — sans
   vérité-terrain une séance c-VEP ne se dépouille pas, et avec elle sur le réseau on donnerait la
   réponse au moteur.

---

## 2. Autotests

| Commande | Résultat | Code de sortie (hors pipe) |
|---|---|---|
| `python src/research/cvep_stimulus.py --smoke` | **29/29 OK**, `VERDICT : OK` | `0` |
| `python src/research/app.py --smoke` (non-régression) | `smoke OK : menu + SSVEP + c-VEP (eCCA & rCCA) + P300 + neuro + ErrP` | `0` |

**Aucune écriture dans le vrai `data/`** — vérifié par HORODATAGE (le dossier est gitignoré, donc
`git status --short data/` ne prouve rien) : fichier le plus récent = `errp_model_20260818-153051.joblib`,
**2026-08-18 15:30**, trois jours avant l'exécution des tests (2026-08-21 09:02). Le test de phase
fabrique son modèle dans un `tempfile.mkdtemp()` et repointe `core.modes.cvep.CVEP_MODEL_PATH` le
temps de la construction, restauré dans un `finally`.

---

## 3. LE test de phase — preuve rouge sur un décalage d'UNE frame

Mutation appliquée à `core/modes/cvep.py:_phase_et_cause` (l'étape 4 du brief) :

```diff
-        return int(age * self._ref_refresh + _EPS_FRAME) % self.code_len, None
+        return (int(age * self._ref_refresh + _EPS_FRAME) + 1) % self.code_len, None
```

### ROUGE — 5 assertions sur 6, sortie `1`

```
  ÉCHEC tant qu'aucune frame n'est sautée, la phase reconstruite par le moteur est EXACTEMENT
        celle que l'émetteur affiche, sur les 207 frames de la course (pire écart 1)
  ÉCHEC après une frame sautée, l'écart ne dépasse jamais UNE frame (2 sur 45 frames)
  ÉCHEC ...et le marqueur du cycle SUIVANT RÉSORBE l'erreur au lieu de la laisser s'accumuler
        (252 frames après, pire écart 1)
  ÉCHEC sur la course ENTIÈRE, l'écart ... ne dépasse jamais UNE frame (pire écart mesuré :
        2 frames, sur 504 frames)
  ÉCHEC une course SANS aucune frame sautée n'a aucun écart du tout, sur ses 504 frames
[cvep-stim] VERDICT : PROBLÈME
EXIT (hors pipe) = 1
```

### VERT — mutation retirée, sortie `0`

```
  OK   une phase est disponible à CHAQUE frame de la course (504/504)
  OK   tant qu'aucune frame n'est sautée, la phase reconstruite par le moteur est EXACTEMENT
       celle que l'émetteur affiche, sur les 207 frames de la course (pire écart 0)
  OK   après une frame sautée, l'écart ne dépasse jamais UNE frame (1 sur 45 frames)
  OK   ...et le marqueur du cycle SUIVANT RÉSORBE l'erreur (252 frames après, pire écart 0)
  OK   sur la course ENTIÈRE ... (pire écart mesuré : 1 frames, sur 504 frames)
  OK   une course SANS aucune frame sautée n'a aucun écart du tout, sur ses 504 frames
EXIT (hors pipe) = 0
```

`git diff --stat src/core/modes/cvep.py` vide après retrait : le fichier du moteur est intact.

### Le pire écart mesuré, en chiffres

Course de **504 frames** (8 cycles de 63) à `t0 = 1000 s`, une frame sautée à la frame 206 :

| Segment | Frames | Pire écart |
|---|---|---|
| Avant toute frame sautée | 207 | **0** |
| Entre la frame sautée et le marqueur suivant | 45 | **1** |
| Après le marqueur qui résorbe | 252 | **0** |
| **Course entière** | **504** | **1** |

Et sur une course **sans aucune frame sautée** : **0 sur 504 frames**.

Le `1` est donc entièrement localisé dans les 45 frames qui séparent la frame sautée du marqueur
suivant — c'est l'écart légitime (l'émetteur a une image de retard sur l'horloge murale), et le
marqueur du cycle suivant le ramène à 0 au lieu de le laisser s'accumuler.

### ⚠️ Écart signalé avec le brief : sa tolérance littérale ne suffisait pas

Le brief demandait `chk(max(pires) <= 1, ...)`. **Cette assertion seule ne rougit pas sur un
décalage systématique d'une frame** — mesuré, pas supposé : avec la mutation **`- 1`** au lieu de
`+ 1`, elle reste **verte** (pire écart 1, exactement la tolérance), parce que le décalage
systématique et le retard de la frame sautée se compensent au lieu de s'ajouter :

```
  ÉCHEC tant qu'aucune frame n'est sautée, la phase ... est EXACTEMENT celle que l'émetteur
        affiche, sur les 207 frames (pire écart 1)          <- l'assertion resserrée
  OK    après une frame sautée, l'écart ne dépasse jamais UNE frame (0 sur 45 frames)
  OK    sur la course ENTIÈRE ... (pire écart mesuré : 1 frames, sur 504 frames)  <- le brief
  ÉCHEC une course SANS aucune frame sautée n'a aucun écart du tout, sur ses 504 frames
```

Le test livré garde l'assertion du brief **et** ajoute celles qui exigent **ZÉRO** là où zéro est
dû : avant tout saut, après résorption, et sur une course propre. C'est cette exigence-là qui mord
dans les deux sens de mutation.

---

## 4. Le geste flip → horodatage : ce que le test attrape que l'ordre seul ne peut pas

**Le critère d'`errp_stimulus.py` est VIDE de sens ici, et c'est mesuré.** Là-bas, l'assertion qui
mord est « le flip qui précède le marqueur est celui qui a CHANGÉ l'écran » : elle marche parce que
la piste est IMMOBILE entre deux feedbacks. Ici l'écran change à **62 frames sur 63** (assertion
`inchangees <= 1` du smoke) — le clignotement, c'est son métier. « Ce flip a changé l'écran » serait
donc vert quoi qu'on fasse.

**Le critère c-VEP est plus exigeant : le flip qui précède le marqueur doit être celui qui a affiché
la FRAME 0 du code**, ni la 62 ni la 1. `--smoke` le lit **dans les pixels** : il échantillonne à
mi-rayon de chacun des 6 disques (`point_de_sonde`, pas le centre — le point de fixation y est) et
compare le motif ON/OFF au code attendu. Une seule image ne suffit pas à identifier la position
(**32 motifs distincts pour 63 positions**, assertion de fixture) ; une fenêtre de **3 images
consécutives**, si (**63/63**, assertion de fixture).

### La preuve que le mécanisme est indépendant de l'assertion d'ordre

Mutation appliquée à `cvep_stimulus.py` : `emet(...)` remonté **au-dessus** de
`pygame.display.flip()`. Le smoke rougit sur les deux critères — mais l'assertion d'ordre ne rougit
que par accident de structure (cet émetteur n'a aucun écran statique avant sa boucle, donc son tout
premier marqueur part avant le tout premier flip de la séance). En isolant :

```
marqueurs poussés                                          : 6
...dont le critère d'ORDRE (flip juste avant) est SATISFAIT : 5
...positions LUES DANS LES PIXELS pour ceux-là              : [62, 62, 62, 62, 62]
VERDICT sonde sur ce sous-ensemble                          : PAS à 0 -> ROUGE
```

**5 marqueurs sur 6 passent le critère d'ordre** — c'est exactement le piège de l'ErrP, le flip de
la frame précédente juste avant le push — **et la sonde pixel les rougit tous les 5**, en lisant la
position **62** au lieu de 0. Le mécanisme est donc suffisant à lui seul : il ne dépend ni du
premier marqueur, ni de la présence d'un écran statique avant la boucle.

Sortie du smoke sous cette mutation :

```
  ÉCHEC [C1] ...et le flip qui précède le marqueur est celui qui a affiché la FRAME 0 du code,
        ni la 62 ni la 1 — lu dans les PIXELS des 6 disques (5 marqueurs vérifiés, positions [62])
  ÉCHEC [C2] ... (2 marqueurs vérifiés, positions [62])
[cvep-stim] VERDICT : PROBLÈME     EXIT = 1
```

Mutation retirée → `positions [0]`, vert, sortie `0`.

---

## 5. Les autres assertions du smoke (29 au total)

- **Contrat du marqueur** : exactement `{mode, event, refresh}`, `refresh` **flottant** (pas `bool` —
  `bool` hérite de `int`, un `true` JSON passerait pour 1 Hz, cas que le moteur écarte
  explicitement), consigne ABSENTE de la charge utile.
- **Un marqueur par redémarrage du code**, jamais ailleurs (`frame % 63 == 0`).
- **Cadence** : un cycle = 63 frames à 60 Hz = 1,050 s, ±25 %.
- **Le clignotement ne s'arrête pas pendant la chauffe** (passage C2) — mesuré par l'**ÉTENDUE** des
  marqueurs (2,00 s > les 1,5 s décomptées), pas par les trous : un écran figé pendant la chauffe ne
  creuse aucun trou ENTRE deux marqueurs, il retarde seulement le premier, donc un « plus grand
  intervalle < X » serait vert quelle que soit la valeur de X. C'est le même genre de test creux que
  celui repéré sur l'ErrP.
- **Géométrie** : les points suivent l'ANGLE du plan, jamais un i-ème de tour recalculé (le piège
  documenté par `p300_stimulus.target_positions` : identique à 6 cibles, divergent à 3).
- **Consigne** : ne se répète jamais deux fois de suite (2000 tirages), s'efface à une seule cible.

---

## 6. Diagnostics ajoutés dans le bilan de fin

Le bilan imprime les cycles émis, les **frames sautées** (mesurées sur les intervalles de flip,
seuil 1,5 période) et surtout la **cadence réelle** contre celle annoncée. Au-delà de 2 % d'écart il
dit pourquoi ça compte : le moteur extrapole la phase à `refresh` Hz *entre* deux marqueurs, donc un
écran qui ne tient pas la cadence annoncée le fait décoder à côté — sans qu'aucune exception ne le
signale. C'est la seconde façon de produire la panne muette de ce mode, à côté de l'horodatage
précoce.

⚠️ Cet avertissement **se déclenche sous `--smoke`** (-5 %) : le pilote `dummy` n'a pas de vsync,
donc la boucle est cadencée par `clock.tick(refresh + 5)` = 65 fps. Ce n'est pas un faux positif —
il dit vrai sur un écran factice. Une ligne du smoke le signale pour qu'on n'apprenne pas à
l'ignorer sur un vrai écran.

---

## 7. Doutes et limites

1. **Rien n'a été vu à l'écran ni au casque.** Tout est vérifié headless. Le rendu réel (taille des
   disques, lisibilité du cercle de consigne, du bandeau de chauffe) n'a jamais été affiché.
2. **Le verrouillage à la frame n'est pas prouvé sur le vrai matériel.** Le smoke tourne sous
   `dummy`, sans vsync : il ne peut rien dire du nombre réel de frames sautées sur cette machine.
   Le compteur existe pour le mesurer en séance, il n'a pas encore de mesure.
3. **La cadence sous `dummy` dévie de 5 %** (`clock.tick(refresh + 5)`, convention reprise des deux
   autres émetteurs). La tolérance du test de cadence est donc large (±25 %) : elle attraperait un
   facteur 2, pas une dérive fine. La dérive fine est l'affaire du bilan de fin, sur un vrai écran.
4. **Le choix d'afficher une CONSIGNE est une décision de protocole que le brief ne demandait pas.**
   Elle donne un sens à `--seed` et rend la séance dépouillable, mais elle fait de cet émetteur une
   séance guidée plutôt qu'un sélecteur libre. Si la revue préfère un émetteur nu, la consigne
   s'enlève sans toucher au reste (elle n'entre ni dans le marqueur ni dans la phase).
5. **`CYCLES_PAR_CIBLE = 2 * CVEP_DECISION_CYCLES`** (= 4 cycles = 4,2 s) est un choix raisonné
   depuis la géométrie de décision du moteur, pas une valeur mesurée. La bonne durée de consigne se
   règlera à la première séance casque.
6. **Le bandeau de chauffe est tenu même quand `wait_for_consumers` répond « non »**, alors
   qu'`errp_stimulus.py` l'escamote dans ce cas. Raison : `wait_for_consumers` répond « non »
   pendant que le moteur résout son inlet, c'est-à-dire exactement au moment où sa chauffe commence.
   Le coût si personne n'écoute vraiment : 15 s de clignotement avant que `--seconds` ne compte
   (`--no-wait` s'en passe). Choix assumé, à revoir si c'est pénible en pratique.

---

# Tour de correction 1

Quatre points traités. Autotests : `cvep_stimulus --smoke` **50/50 OK exit 0** (29 → 50 assertions),
`app.py --smoke` **OK exit 0**, `core/modes/cvep.py` **OK exit 0**. `data/` toujours intact (fichier
le plus récent : 18/08 15:30, tests lancés le 21/08 09:45).

## Important 1 — le bilan de fin est désormais gardé par des assertions

Le diagnostic de la **seconde panne muette** (un écran qui ne tient pas le rafraîchissement
annoncé — un 144 Hz lancé avec `--refresh 60`) n'était qu'une suite de `print`. Trois changements :

- **`diagnostic_cadence(...)`** — le verdict devient une fonction PURE, interrogée point par point
  des deux côtés du seuil de 2 % (0 %, ±1,9 %, ±2,1 %, et le cas 144 Hz réel).
- **`bilan_de_seance(...)`** — une seule source pour ce qui s'imprime ET ce que `--smoke` relit ;
  `run()` la recopie dans un paramètre `bilan` (même patron que `journal`).
- **Passage C3** — le smoke RETIENT délibérément 3 flips au-delà de `SEUIL_SAUT` pour que le
  compteur de frames sautées ait quelque chose à compter : sous `dummy` il n'y a jamais de vsync
  manqué, donc sans ces cales le compteur resterait à 0 et le neutraliser ne rougirait rien.

### Preuve rouge des trois mutations qui laissaient le bilan vert

| Mutation | Avant | Après |
|---|---|---|
| `abs(derive) < tolerance` inversé en `>= tolerance` | vert, exit 0 | **8 ÉCHEC, exit 1** |
| compteur `sautees` neutralisé (bloc de détection supprimé) | vert, exit 0 | **1 ÉCHEC, exit 1** |
| bloc de bilan supprimé de `run()` | vert, exit 0 | **6 ÉCHEC, exit 1** |

```
--- A. comparaison de derive INVERSEE -------------------------------------------
  ECHEC cadence - cadence exacte (+0.0%) : AVERTIT, ATTENDU LE CONTRAIRE
  ECHEC cadence - 1,9 % de derive (sous le seuil) (+1.9%) : AVERTIT, ATTENDU LE CONTRAIRE
  ECHEC cadence - -1,9 % de derive (-1.9%) : AVERTIT, ATTENDU LE CONTRAIRE
  ECHEC cadence - 2,1 % de derive (au-dessus du seuil) (+2.1%) : se tait, ATTENDU LE CONTRAIRE
  ECHEC cadence - -2,1 % de derive (-2.1%) : se tait, ATTENDU LE CONTRAIRE
  ECHEC cadence - un ecran 144 Hz lance avec --refresh 60 (-58.3%) : se tait, ATTENDU LE CONTRAIRE
  ECHEC ...et l'avertissement NOMME le rafraichissement reellement affiche et dit de recalibrer
  ECHEC [C1] ...et il AVERTIT, parce que l'ecran factice derive de -6.6% - le chemin reel
        appelle bien le diagnostic
[cvep-stim] VERDICT : PROBLEME        EXIT = 1

--- B. compteur `sautees` NEUTRALISE --------------------------------------------
  ECHEC [C3] les 3 frames REELLEMENT retenues (flip bloque 2.1 periodes) sont comptees, toutes
        et seulement elles (3 cales posees -> 0 comptees)
[cvep-stim] VERDICT : PROBLEME        EXIT = 1

--- C. BLOC DE BILAN SUPPRIME de run() ------------------------------------------
  ECHEC [C1] le bilan de fin EXISTE et compte ce que la seance a vraiment fait (None, None)
  ECHEC [C1] ...il MESURE la cadence reelle (None s/cycle, derive None)
  ECHEC [C1] ...et il AVERTIT, parce que l'ecran factice derive de +0.0%
  ECHEC [C3] les 3 frames REELLEMENT retenues ... (3 cales posees -> None comptees)
  ECHEC la graine DONNEE est celle qui a servi, et le bilan la rend (None)
  ECHEC ...et SANS `--seed`, une graine est TIREE puis annoncee (None)
[cvep-stim] VERDICT : PROBLEME        EXIT = 1
```

Retrait de chaque mutation → **50/50 OK, exit 0**.

⚠️ **C3 a attrapé un défaut de mon propre harnais, et je le note parce qu'il est instructif** : en
calant les 3 PREMIÈRES images, 3 cales posées ne donnaient que **2** comptées. L'émetteur mesure un
ÉCART entre deux flips, donc le tout premier flip d'une séance n'a pas de prédécesseur et ne peut
pas être compté comme sauté. Les cales sont maintenant armées après 10 flips.

## Important 2 — la période inexploitable, chiffrée et marquée

**Le chiffre : 2,7 s après chaque changement de consigne sont INEXPLOITABLES.** Décomposition, tirée
des constantes du moteur et non estimée :

| Mémoire du moteur | Source | Durée |
|---|---|---|
| Fenêtre de décision | `CVEP_DECISION_CYCLES` (2) x 63/60 | 2,10 s |
| Vote glissant | `CVEP_VOTE_LEN` (3) x `ModeRuntime.period_s()` (0,2 s) | 0,60 s |
| **Total** | | **2,70 s** |

⚠️ `period_s` n'est pas une constante de `config.py` mais une **méthode de `ModeRuntime` que
`CVEPRuntime` ne redéfinit pas** — vérifié, pas supposé : une assertion arrime `PERIODE_MOTEUR_S` à
`ModeRuntime.period_s(None)` **et** contrôle que `"period_s" not in CVEPRuntime.__dict__`.

**J'ai appliqué les DEUX remèdes**, parce qu'allonger seul ne ramène jamais la transition à zéro et
que la recette a besoin de savoir quoi jeter :

1. **Allonger** — `CYCLES_PAR_CIBLE` passe de 4 à **8 cycles**, et il est maintenant *dérivé* :
   `ceil(3 x TRANSITION_S x 60 / 63)`. À 60 Hz : consigne de **8,4 s**, dont 2,7 s de transition et
   **5,7 s exploitables = 68 %** (contre **36 %** avant, d'où le plafond de justesse à ~40 % que la
   revue a décrit). Une assertion exige `part_exploitable >= 0,60`.
2. **Marquer** — chaque ligne `t=` imprime désormais l'instant à partir duquel compter :
   `t=... cycle N : fixe « ARRIERE » (cible 3)  —  compter à partir de t=... (+2.7 s de transition)`,
   et un bandeau au lancement explique la règle. La docstring du module porte la recette de
   dépouillement avec le chiffre.

## Minor — `--seed`

- La graine est **tirée quand elle n'est pas donnée** et **imprimée dans tous les cas** :
  `graine 437966816 — REJOUE cette séance à l'identique avec --seed 437966816`.
- Contrat épinglé : deux passages à la même graine (`refresh=120`, `cycles_par_cible=1`,
  ~5 consignes) doivent produire la MÊME séquence. Mutation `random.Random(seed)` →
  `random.Random()` :

```
  ECHEC deux seances a la MEME graine rejouent EXACTEMENT les memes consignes
        (['AV-GAUCHE', 'AR-DROITE', 'AVANT', 'AR-GAUCHE', 'AR-DROITE']
         vs ['AVANT', 'ARRIERE', 'AVANT', 'ARRIERE', 'AR-DROITE'])
[cvep-stim] VERDICT : PROBLEME        EXIT = 1
```

Probabilité de coïncidence sur 5 consignes avec la contrainte de non-répétition :
1/6 x (1/5)^4 ≈ **0,027 %**, soit ~1 exécution sur 3700 — pas de risque de test instable.

## Minor — la sonde pixel n'est pas transposable, c'est écrit

`_etat_ecran` porte maintenant sa condition de validité : elle lit `get_surface()` **après**
`flip()`, ce qui est correct sous `dummy` (aucun échange de tampon, la surface reste celle qu'on
vient de dessiner) mais **faux sous un pilote à double tampon matériel**, où `flip()` échange les
tampons et `get_surface()` rend le tampon d'arrière — l'image précédente, ou un contenu indéfini.
La sonde y lirait une position décalée d'une frame et **accuserait un émetteur correct**. Pour un
test sur vrai écran, il faudrait prendre l'empreinte AVANT le `flip`.

## Minor pris au passage — `--refresh 0`

Divisait par zéro **après** l'ouverture de la fenêtre : traceback nu, pas de `pygame.quit()`, plein
écran resté affiché. Refus posé avant d'ouvrir quoi que ce soit (patron
`p300_stimulus.valide_reglages`), assertion sur `0.0` et `-60.0`.

## Non traités (reportés au registre, sur consigne)

Vérité-terrain seulement sur stdout · HUD affichant le refresh annoncé étiqueté « fps » ·
`ATTENTE_MOTEUR_S` re-dérivé au lieu d'être lu · fragilité du `chk` sur les consignes.

## Doutes qui subsistent

1. **Rien n'a été vu à l'écran ni au casque** — inchangé depuis le premier tour.
2. **La consigne dure maintenant 8,4 s.** C'est long à tenir en fixation. Le compromis est
   défendable (68 % d'exploitable) mais **la bonne durée se règlera à la première séance casque** :
   si 8,4 s fatigue trop, la sortie est de raccourcir ET de garder le marquage, en acceptant une
   part exploitable plus faible mais explicite.
3. **La tolérance de 2 % sur la dérive de cadence n'est pas mesurée sur du matériel** : elle est
   raisonnée (59,94 Hz annoncé 60 → 0,1 % ; 60 contre 75 → 25 %). Aucun écran réel ne l'a encore
   éprouvée.
4. **Le passage C3 dépend de `time.sleep`** pour fabriquer ses frames sautées. Il prouve que le
   compteur compte, pas que le seuil de 1,5 période soit le bon sur un vrai écran.

---

# Tour de correction 2

Deux points, tous deux traités. Autotests : `cvep_stimulus --smoke` **51/51 OK, exit 0, sept fois
de suite** · `app.py --smoke` **OK exit 0** · `core/` intact.

## Le test instable que j'avais introduit — cause SUPPRIMÉE, pas accommodée

J'ai pris la **première** des deux options proposées : **borner en IMAGES plutôt qu'en secondes**.
Comparer des préfixes aurait accommodé le symptôme ; un compte d'images rend le rejeu déterministe
par construction.

`run()` prend un paramètre `max_frames`, vérifié dans `poll()` à côté de `--seconds`. Pas d'option
de ligne de commande : une séance réelle se règle en secondes, c'est `--smoke` qui a besoin de
reproductibilité à l'image près — même statut que `max_run_steps` chez `errp_stimulus.py`. Les
passages C4/C5 sont désormais bornés à `6 * 63 = 378` images.

### La cause racine, mesurée

10 exécutions de la même course, à graine égale :

| Borne | Images rendues | Étendue | Cycles |
|---|---|---|---|
| `seconds=2.6` (l'ancienne) | 291 … 298 | **7 images** | 5 |
| `max_frames=378` (la nouvelle) | 378 … 378 | **0 image** | 6 |

**7 images d'écart entre deux exécutions de la même course.** Une consigne tombant toutes les
63 images, il suffit que cette fenêtre de ±7 franchisse un multiple de 63 pour que le nombre de
consignes change — c'est exactement le 4-contre-5 observé par la revue, et pourquoi il ne se
manifeste qu'environ une fois sur huit : il faut que la limite tombe près d'un bord de cycle. Sur ma
machine la fenêtre 291-298 ne contient aucun multiple de 63, donc le compte y restait à 5 : **le
test ne devenait pas vert « parce qu'il est bon », il l'était par chance de calibrage.** C'est
précisément ce qu'un test instable fait de pire — paraître stable là où on le relance.

Bornée en images, l'étendue est **nulle** : le nombre de marqueurs ne peut plus dépendre de
l'ordonnanceur. L'assertion exige maintenant la même LONGUEUR autant que le même contenu
(`len(consignes4) == len(consignes5) == 6`), ce qui est le fond du correctif : comparer deux listes
de longueurs différentes était la faille.

### Sept exécutions consécutives

```
run 1 : 51 OK, 0 ECHEC, VERDICT : OK, exit=0
run 2 : 51 OK, 0 ECHEC, VERDICT : OK, exit=0
run 3 : 51 OK, 0 ECHEC, VERDICT : OK, exit=0
run 4 : 51 OK, 0 ECHEC, VERDICT : OK, exit=0
run 5 : 51 OK, 0 ECHEC, VERDICT : OK, exit=0
run 6 : 51 OK, 0 ECHEC, VERDICT : OK, exit=0
run 7 : 51 OK, 0 ECHEC, VERDICT : OK, exit=0
```

## Le résidu de fusion

Le bloc « Un BILAN, toujours… » était dupliqué mot pour mot (deux lignes). Supprimé.

## Doutes

Inchangés depuis le tour 1 (rien vu à l'écran ni au casque ; consigne de 8,4 s à valider en séance ;
tolérance de 2 % sur la dérive de cadence non éprouvée sur matériel ; C3 prouve que le compteur
compte, pas que le seuil de 1,5 période soit le bon hors pilote factice). Un ajout :

- **`max_frames` n'est pas exposé en ligne de commande.** C'est délibéré (une séance se règle en
  secondes), mais cela veut dire qu'un étudiant qui voudrait reproduire une séance à l'image près
  depuis le terminal ne le peut pas — il lui faudrait appeler `run()` depuis Python. Si le besoin
  apparaît en recette, l'option est à une ligne.
