# Re-revue cadrée des trois vagues (`b0f857c..1afb501`)

Mandat étroit : les **huit Critical** sont-ils réellement traités, et une correction en a-t-elle
défait une autre. Tout est vérifié **dans le dépôt et par exécution**, jamais sur la foi des
rapports de lot. `data/` en lecture seule, un seul python du projet à la fois.

**Résultat : 8 ADDRESSED / 8. Aucune casse nouvelle. `data/` intact.**

Six des huit ne sont pas seulement *présents* : j'ai muté **une ligne de production** par Critical
et vérifié que la suite censée le protéger rougit. Un test qui ne rougit sous aucune mutation est
décoratif ; aucun de ceux-ci ne l'est.

---

## Les huit verdicts

### 1. A-C1 — le vote glissant survivait à la perte de l'horloge → **ADDRESSED**

`src/core/modes/cvep.py:588`, dans la branche `phase is None`, `self._votes.clear()` — symétrique
du `clear` de `_reset_rest`. Test : section **9bis** (`cvep.py:1522-1553`), fenêtre franche →
fenêtre `reference_perimee` → fenêtre franche, la troisième ne conclut pas.

Mutation (retirer le `clear`) → `exit 1` :

```
ÉCHEC ...une fenêtre non décodable pour raison d'HORLOGE vide la file : la première fenêtre
      d'après le retour de l'émetteur ne peut pas conclure sur des votes d'avant la coupure
```

### 2. B-C1 — `empreinte_dossier` n'était éprouvé par aucun test → **ADDRESSED**

Sept assertions en dossier temporaire, en tête de `core/config.py::_selftest` (l. 862-926), **une
par composante** : dossier absent · inchangé · ajout · grossissement · **réécrit à taille égale**
(le cas qui a coûté les deux modèles) · dossier listé en entier · suppression. Le diff est calculé
comme chez l'appelant réel (`research/app.py::_smoke`).

Mutation (`return {}` en tête de la fonction) → `exit 1`, **5 rouges**, dont celles de la taille, du
mtime et du listage complet — chaque composante a bien sa propre assertion.

### 3. F-C1 — use-after-free sur 5 sites de l'autotest `lsl_io.py` → **ADDRESSED**

Les 5 sites lient le `StreamInfo` à une locale (`info_in`, `info_p300`, `info_ssvep`, `info_errp`,
`info_cvep`). Les 3 lectures restantes (`lsl_io.py:854`, `912`, `920`) sont **en une seule
expression** : le temporaire vit jusqu'à la fin de l'expression, elles sont saines.

**J'ai refait la mesure qui tranche** — `junk = [bytes(4096) for _ in range(2000)]` inséré entre la
lecture et l'assertion du site SSVEP, 3 exécutions :

```
run 1 : exit=0 :: [lsl] VERDICT : OK
run 2 : exit=0 :: [lsl] VERDICT : OK
run 3 : exit=0 :: [lsl] VERDICT : OK
```

**Contre-épreuve que le lot 1 n'avait pas pu rejouer** (correctif RETIRÉ, `ssvep_deco =
pub_ssvep.outlet.get_info().desc().child("decoding")`, **même** allocation) :

```
run 1 : exit=1 :: decoded_ssvep no_decision_index : ''  | AssertionError: no_decision_index manquant (SSVEP)
run 2 : exit=1 :: decoded_ssvep no_decision_index : ''  | AssertionError: no_decision_index manquant (SSVEP)
run 3 : exit=1 :: decoded_ssvep no_decision_index : ''  | AssertionError: no_decision_index manquant (SSVEP)
```

3/3 rouge sans le correctif, 3/3 vert avec, à allocation identique. Ce n'était pas un test
instable, et le correctif est réel. Mesure retirée, `git status` propre après.

### 4. E-C1 — l'ITR affiché était exactement doublé → **ADDRESSED**

`cvep_calibrate.py:636-637` : `k_decision = res["eCCA"]["n_cycles"]`, puis
`decision_s = k_decision * L / app.refresh`. **La durée sort du MÊME dict que la justesse** —
`cv_e`/`cv_r` (l. 591), `n_cibles` (l. 592) et `k_decision` viennent tous de l'unique `res` rendu par
`entraine_les_deux` (l. 537). Ce n'est pas une constante recopiée : changer `n_cycles` déplace les
deux chiffres ensemble.

**Chiffre recalculé indépendamment** (`research.itr.itr`, `CVEP_DECISION_CYCLES = 2`, T = 2,1000 s) :

| | k = 2 (T = 2,10 s) | k = 1 (T = 1,05 s) |
|---|---|---|
| eCCA 22/37 = 59,5 % | **19,13** bits/min | 38,26 |
| rCCA 24/37 = 64,9 % | **23,83** bits/min | 47,65 |
| verdict (SSVEP réf. 49,94 ; seuil `ref/2` = 24,97) | **FAIBLE** | PROMETTEUR |

Rapport k1/k2 = **2,000000** exactement. Les 19,1 / 23,8 et le verdict FAIBLE sont confirmés, et
`README.md:205`, `docs/SPEC.md:560` et l'assertion `cvep_calibrate.py:1163` disent le même chiffre.

Mutation (`decision_s = L / app.refresh`) → `exit 1` : `ÉCHEC la DURÉE de décision imprimée est
celle où la justesse a été mesurée (2 cycles = 2.10s), pas un cycle (1.05s) — le facteur 2 exact`.

### 5. E-C2 — deux correctifs de la tâche 6 s'annulaient hors rotation zéro → **ADDRESSED**

Cause corrigée : `presentes = sorted(set(labels), key=lambda l: lag_a_idx[l])`
(`cvep_calibrate.py:264`).

**Le test à rotation ≠ 0 existe** (`cvep_calibrate.py:986-1039`) : `core.cvep_code.CVEP_LAG_ROTATION`
détourné à **2**, avec (a) une assertion de fixture que les deux tris divergent vraiment, (b) codes
du modèle == codes du plan **dans l'ordre du plan**, (c) `cvep_models.charger` l'**accepte**, (d)
contrôle externe par `RCCADecoder` sur le modèle **relu** qui désigne la cible réellement affichée,
(e) restauration dans un `finally` **plus** une assertion que la rotation réelle est bien revenue.

Mutation (`presentes = sorted(set(labels))`) → `exit 1`, les deux assertions (c) et (b) rouges.

### 6. D-C1 = G-C1 — la clé de jointure du dépouillement → **ADDRESSED**

- **Opt-in sans défaut** : `p.add_argument("--log", default=None, …)` (`cvep_stimulus.py:1286`), et
  l'assertion le lit sur l'`argparse` lui-même : `chk(_parse_args([]).log is None, …)` (l. 1250).
  Le smoke ne peut donc rien écrire nulle part.
- **Append + flush** : `open(log_path, "a", encoding="utf-8")` (l. 388) et un `flush()` par ligne
  (l. 402). Une sentinelle écrite AVANT la séance survit — assertion l. 1246.
- **Même domaine d'horloge, vérifié de bout en bout** : le journal écrit `t` et
  `compter_a_partir_de` en `local_clock()` (l. 612-613, `local_clock()` pris une seule fois l. 518).
  Côté moteur, `decoded_cvep` est horodaté par `t_fin = engine.recent_ts[-1]`
  (`modes/cvep.py:569`), et `recent_ts` est rempli par `self.clock.to_lsl(ts_unix)`
  (`server.py:1210`) — **le même `local_clock()`**. `examples/receiver.py` imprime désormais
  `t = ts + offset`, qu'il calculait et jetait.

Mutation (`open(log_path, "w")`) → `exit 1` : `ÉCHEC [C6] le fichier est ouvert en AJOUT : la ligne
écrite AVANT la séance est toujours là`.

### 7. G-C2 — l'A-B-A du 2.9 n'avait ni protocole ni base de calcul → **ADDRESSED** (documentaire)

`docs/recette.md:960-1005`. Y figurent maintenant : l'avertissement explicite que **A est cerclé et
à l'aveugle, B libre et en boucle fermée** (l'écran archivé n'affiche aucune consigne, ne tire rien,
n'horodate rien, et montre la réponse en direct) ; le protocole de B à préparer **avant** de le
lancer (liste de fixations **écrite sur papier**, 6 × 3 mélangées, 10 s par cible, **3 premières
secondes ignorées**, panneau lu **seulement à la fin** de chaque fixation) ; la **base de calcul**,
qui est la « méthode de secours » écrite une seule fois (l. 904) et réutilisée ici, avec les mêmes
deux ratios qu'en A ; l'exigence des **seuils par défaut pour les trois blocs avant tout
desserrage** ; la grille de lecture des trois nombres ; et le biais C3/Cz que le retour en A′
contrôle.

### 8. Escalade A — la branche rCCA du mode n'avait jamais tourné → **ADDRESSED**

Section **7ter** (`modes/cvep.py:1347-1380`) : `RCCAModel` fabriqué et ajusté, sauvegardé, **rechargé
par `cvep_models.charger` comme en production**, puis `CVEPRuntime` complet — `_DECODEURS["rCCA"]`,
`.corr_min`/`.margin`/`.n_cycles` posés sur le `RCCADecoder`, `model.n_cyc`, `model.channels`,
`cv_` — et `_run_step` jusqu'à une décision **publiée**, avec l'appariement score↔cible vérifié.

Mutation (`_DECODEURS = {"eCCA": CVEPDecoder, "rCCA": CVEPDecoder}`) → `exit 1` :

```
ÉCHEC le décodeur suit le MODÈLE, pas un réglage — … (rCCA, CVEPDecoder)
TypeError: RCCAModel.scores() got multiple values for argument 'n_cycles'
```

Avant ce bloc, cette mutation ne rougissait rien.

---

## `server.py --smoke` × 5 — l'anomalie du lot 3

Cinq exécutions **consécutives, seules**, aucun autre python du projet en vie, codes relevés hors
pipe (`$?` capturé après chaque run, jamais derrière un `|`) :

```
run 1 exit=0      0 ÉCHEC   17 verdicts OK   0 PROBLÈME
run 2 exit=0      0 ÉCHEC   17 verdicts OK   0 PROBLÈME
run 3 exit=0      0 ÉCHEC   17 verdicts OK   0 PROBLÈME
run 4 exit=0      0 ÉCHEC   17 verdicts OK   0 PROBLÈME
run 5 exit=0      0 ÉCHEC   17 verdicts OK   0 PROBLÈME
```

**Verdict : l'hypothèse de la collision tient, rien ne justifie une chasse.** Rien n'a rougi en cinq
passages ; il n'y a pas de texte d'échec à garder.

### ⚠️ Mais une mesure de plus, qui change la lecture de « ce n'était qu'une collision »

Pendant mon banc de mutations, `src/research/cvep_stimulus.py --smoke` a sorti **deux assertions
rouges sans rapport avec la mutation appliquée** (qui ne touchait que le mode d'ouverture du
journal) :

```
ÉCHEC un cycle dure 1.050 s (63 frames à 60 Hz), ±25 % — mesuré 1008 ms de médiane sur 5 cycles
ÉCHEC [C1] ...sans fabriquer de fausses frames sautées quand tout va bien (29 sur 336)
```

Relancée **seule**, la même suite est **5/5 verte, 0 ÉCHEC**. Ces deux assertions sont donc
sensibles à la **charge machine** : elles rougissent quand la suite tourne à la file derrière
d'autres processus, pas quand elle tourne seule.

C'est exactement le **D-I2** que le lot 3 a reporté en le qualifiant de « test instable, pas faux » :
il passe de *soupçonné* à **mesuré**. Cela ne réexplique pas les 8 rouges du lot 3 (fichier
différent, `server.py` n'a pas d'assertion de cadence de ce genre), mais ça établit qu'il existe
**bien** dans ce dépôt des assertions sensibles à la charge : la collision de noms de flux n'est pas
le seul mécanisme possible pour un rouge non reproductible. À garder à l'esprit au prochain rouge
orphelin, et à traiter avec D-I2.

---

## Casse nouvelle — **aucune trouvée**

Cherchée là où le précédent avéré s'était produit : deux correctifs qui s'annulent, chacun
invisible depuis son propre verrou.

**Le reliquat signalé par le lot 2 est bien réparé.** Le lot 2 avait prévenu que son correctif E-C2
rendait faux un paragraphe de `core/cvep_models.py` (« à `CVEP_LAG_ROTATION` non nul, ce désaccord
est le cas ATTENDU même sans rien avoir changé » — soit apprendre à l'étudiant qu'un vrai défaut est
normal). Le lot 3 l'a inversé (`cvep_models.py:182-207`) : le refus est présenté comme un vrai
défaut **à toute rotation**, avec ses **trois causes réelles** nommées. ⚠️ Et son test détourne
`CVEP_LAG_ROTATION` à **2** — à 0, la valeur du dépôt, la phrase fautive n'apparaissait jamais et
l'assertion aurait été creuse. Le piège a été évité.

**Les deux fichiers touchés par deux vagues** sont sains :

- `core/cvep_models.py` (vagues 1 + 3) : les ajouts du lot 3 sont additifs (`PyntbciManquant` capté
  avant le `except Exception`, `modeles_disponibles` qui compte les retirés). Tout ce que le lot 1 y
  avait posé survit — fixture eCCA à tableau d'objets (l. 556-567), garde `n_targets`, docstring des
  taps.
- `research/cvep_calibrate.py` (vagues 2 + 3) : le `ecca.save(save_path, n_targets=n_cibles_vues)`
  du lot 3 ne touche pas l'ordre `presentes` du lot 2 ; les deux mutations correspondantes rougissent
  encore, séparément.

**Les seuils publiés — l'invariant tient.** `decide()` capture le couple appliqué
(`_seuils_decision`, `cvep.py:549`) ; `_run_step` vide la file dès que ce couple diffère de celui
sous lequel elle a été constituée (l. 623-625), **avant** d'empiler le vote de la fenêtre courante ;
la décision publie `_seuils_du_vote` (l. 657). Après le vidage, les trois valeurs sont le même
couple : « `confidence >= corr_min` par construction » est vrai à la lettre. L'assertion de la
section **8ter** ne teste pas un cas choisi à la main — le seuil est posé **entre deux corrélations
réelles** (moyenne mélangée / fenêtre franche) — et elle balaie **tout le flux publié** :
`fautives = [l for l in rt_s._out.lignes if l[0] >= 0 and l[1] < l[3]]`. Mutation (retirer le
vidage) → `exit 1`, avec `confidence = 0,783` publiée à côté de `corr_min = 0,816`.

Les fenêtres `-1` portent bien les **seuils vivants** : `_publish(seuils=None)` relit
`self.params` (l. 678-679), et l'assertion `cvep.py:1221` le vérifie sur une fenêtre qui n'est
**jamais** passée par `decide()` — plus une seconde qui exige que l'état affiché à la console dise
la même chose.

**Un changement de comportement, correct mais à connaître** (pas une casse) : depuis E-I3, le
modèle eCCA d'une **séance tronquée** déclare son vrai nombre de cibles, donc
`CVEPRuntime._desaccord_code` (garde B-I2 du lot 1) le **refusera** au démarrage. C'est l'effet
recherché — avant, il se déclarait complet et pilotait six cibles avec un modèle qui n'en avait vu
que trois — et la ligne de calibration le dit : « le moteur le REFUSERA tant que le stimulus en
affiche 6 ».

**Deux fausses pistes écartées** : `modeles_disponibles` imprime désormais un avertissement, mais
`registry.serialize` — le seul chemin qui l'atteint via `choices_fn` — n'est appelé qu'à
**l'ouverture de la console**, pas dans `snapshot()` : aucun risque de noyer le terminal.
`SPAN_SEUILS` reste **utilisé** dans `grid.py` et `live_views.py` (chemin SSVEP) après l'extraction
de `span_correlation` : pas d'import mort.

**Balayage de non-régression** (une suite à la fois, jamais deux python du projet en vie) :

```
exit=0  ÉCHEC=0   src/console/app.py --smoke
exit=0  ÉCHEC=0   src/research/app.py --smoke
exit=0  ÉCHEC=0   src/core/cvep_models.py
exit=0  ÉCHEC=0   src/core/cvep_rcca.py
exit=0  ÉCHEC=0   src/core/lsl_io.py
exit=0  ÉCHEC=0   src/core/modes/contract.py
exit=0  ÉCHEC=0   src/research/cvep_rcca.py
exit=0  ÉCHEC=0   archive/cvep_pilot.py --smoke
exit=0  ÉCHEC=0   archive/cvep_rcca_pilot.py --smoke
```

Plus, en contre-épreuve après chaque mutation restaurée : `modes/cvep.py`, `config.py`,
`cvep_calibrate.py`, `cvep_stimulus.py --smoke` → `exit 0`.

---

## État de `data/` — **INTACT**

Empreinte `mtime | chemin | taille` (résolution 100 ns) prise **avant la première commande** et
rejouée **après la dernière** — pas `git status`, le dossier est gitignoré :

* **43 fichiers** avant, **43 après** ;
* `diff` sur les 43 lignes : **aucune différence** ;
* le plus récent est toujours `data/cvep_rcca_model.npz` au **2026-08-21 14:17:45.2835183**.

Aucune calibration réelle lancée. Aucun fichier source laissé modifié : `git status` ne montre que
le `docs/superpowers/plans/…md` **déjà modifié avant cette revue** et les documents SDD non suivis.
Toutes les mutations ont été appliquées sur copie de sauvegarde et restaurées dans un `finally`.
