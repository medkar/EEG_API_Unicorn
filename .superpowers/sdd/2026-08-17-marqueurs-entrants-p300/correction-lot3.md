# LOT 3 — ce que le produit raconte, et l'émetteur : rapport de correction

**Périmètre :** `src/core/modes/external.py`, `src/core/modes/runtime.py`,
`src/core/modes/registry.py`, `src/core/server.py` (**docstring d'en-tête seulement**),
`src/core/p300_decoder.py`, `src/core/p300_models.py`, `src/console/live_views.py`,
`src/console/app.py`, `src/research/` (`p300_stimulus.py`, `p300_calibrate.py`, `app.py`),
`docs/` (`markers.md`, `recette.md`) et `README.md`.

**Rien d'autre n'a été touché** — ni `markers.py`, ni `config.py`, ni `modes/p300.py`, ni
`lsl_io.py` (lots 1 et 2), ni le corps de `server.py`.

**Statut : TERMINÉ.** 2 critiques, 14 importants, tous les mineurs du lot. Tous les tests verts.
**Un défaut supplémentaire trouvé en mesurant**, que la revue n'avait pas vu (§4).

---

## 1. Les deux critiques

### 1.1 — La console affichait le P300 comme un SSVEP (3.1)

`ActiveView.update_from` aiguillait sur `"probas" in sortie`, donc **tout ce qui n'est pas le MI**
tombait dans le rendu du SSVEP. La sortie P300 n'a ni `freqs` dans ses params, ni `threshold` dans
sa sortie : l'écran annonçait `échelle z · seuil 2.5 — un score au-dessus déclenche` au-dessus de
log-odds, avec six barres **sans étiquette**, toutes à zéro (les log-odds sont négatifs), et
`CIBLE 3 · 0 Hz`.

**Le correctif n'ajoute pas une liste de modes** — la console est un client du moteur. Il pose à la
sortie la question « qu'est-ce que tu DÉCLARES ? », dans l'ordre du plus spécifique au plus prudent :

| clé présente | rendu | échelle |
|---|---|---|
| `probas` | `_update_probas` (MI) | probabilité, bornée à 1 |
| `threshold` | `_update_scores` (SSVEP) | z, avec un seuil de déclenchement |
| *ni l'un ni l'autre* | `_update_selection` (**neuf**) | accumulation de preuves, **sans seuil** |

Le repli `sortie.get("threshold", Z_MIN)` était le cœur du défaut : il **inventait** un seuil. Le
troisième rendu n'est branché sur aucun identifiant, à dessein — la prochaine sortie d'une forme
inconnue doit tomber dans le rendu qui n'invente ni seuil ni unité, pas dans celui du SSVEP. C'est
la panne du MI recommencée un mode plus tard ; la troisième fois est prévue.

`_update_selection` dit trois choses vraies que l'ancien écran niait : **aucun seuil** (le moteur
prend l'argmax, `P300_SELECT_MARGIN` portant sur l'écart 1er-2e), **aucune échelle absolue** (barres
relatives entre elles, valeur chiffrée à côté du nom), et **`n_flashes`** sur chaque ligne — 48 et
12 ne se lisent plus pareil.

### 1.2 — L'émetteur n'avait ni pause ni signal entre deux manches (3.2)

`PAUSE_ENTRE_MANCHES_S = 2.5` (calé sur les deux écrans validés au casque : 2,2 s dans
`research/app.py`, 2,5 s dans `p300_calibrate.py`), avec un écran « choisis ta cible et fixe-la »
et un décompte. `docs/recette.md` §2.7 redevient faisable.

**Ce n'est pas cosmétique, et c'est écrit dans le code :** le lot 2 signale que la contamination
entre manches n'est fermée qu'à moitié, et que le discriminant par **écart entre flashs** — celui
qui la fermerait — *ne peut rien détecter tant qu'il n'y a aucune frontière temporelle à détecter*.
Cette pause est donc ce qui rend ce garde-fou possible. C'est dit dans la docstring du module et
dans le commentaire de `pause_entre_manches()`.

Le smoke le mesure : `pauses = [2.51] s pour 2.5 s demandées`, contre un SOA inter-flash de 143 ms.

---

## 2. Preuves ROUGE → VERT

### 2.1 — 3.6 : `p300_decoder.py` sortait TOUJOURS en 0

Trois exécutions, dans l'ordre. La première est celle qui compte : elle montre que le « exit 0 » du
rapport de la tâche 4 ne prouvait rien.

**(a) ANCIEN `__main__` (`_demo()` nu) + autotest en échec** (mutation `sel >= 1.01`) :
```
[p300] pipeline xDAWN+Riemann à ajuster (AUC>75% et sélection>=90% attendus sur ce synthétique).
[p300-decoder] VERDICT : PROBLÈME
EXIT=0          <-- le verdict est jeté
```

**(b) NOUVEAU `__main__` + le même autotest en échec :**
```
[p300-decoder] VERDICT : PROBLÈME
EXIT=1
```

**(c) NOUVEAU `__main__`, mutation retirée :**
```
[p300-decoder] VERDICT : OK
EXIT=0
```

En passant, le fichier imprime désormais un `VERDICT :` comme ses voisins — il n'en avait pas.

### 2.2 — 3.7 : l'assertion du refus d'un modèle hérité

**Mutation demandée :** `if module != "core.p300_decoder"` → `if not module.endswith("p300_decoder")`
— la passerelle de compatibilité que ce chantier a refusé d'écrire.

```
  OK    un modèle hérité est refusé en disant quoi faire (module '__main__', …)   <-- l'ANCIENNE
  ÉCHEC un modèle dont le pickle porte le module NU 'p300_decoder' est refusé, et la raison
        NOMME ce module — c'est ce qui interdit la passerelle endswith() (None)
  ÉCHEC ...en disant quoi faire à la place (None)
  ÉCHEC ...et il ne se glisse pas non plus dans la liste (['…p300_model_herite.joblib',
        '…p300_model.joblib'])
[p300-models] VERDICT : PROBLÈME                                              EXIT=1
```

**L'assertion préexistante reste VERTE sous la mutation** — c'est exactement le trou décrit par la
revue : `_ModeleEtranger.__module__` vaut `"__main__"`, jamais `"p300_decoder"`.

**VERT après restauration :** `module 'p300_decoder', attendu 'core.p300_decoder'`, `VERDICT : OK`,
`EXIT=0`.

Mise en œuvre exactement comme prescrit : `_ModeleHerite` porte `__module__ = "p300_decoder"` en
dur, `types.ModuleType("p300_decoder")` est inscrit dans `sys.modules`, retiré dans un `finally`.
**Une précision qui a changé le correctif :** le faux module doit rester inscrit pendant le
`joblib.dump` **ET** le chargement. L'en retirer entre les deux ferait résoudre `p300_decoder` vers
le VRAI `src/core/p300_decoder.py` — importable au premier niveau sous `python src/core/…`, la
divergence même que `charger` documente — et on testerait alors un tout autre refus
(`AttributeError` → « modèle illisible »).

### 2.3 — 3.1 : la console, sous l'ANCIEN aiguillage

Mutation : retour à `if "probas" in sortie: … else: _update_scores(…)`.

```
  ÉCHEC mais il n'annonce NI le z NI le seuil du SSVEP (échelle z · seuil 2.5 — un score au-dessus déclenche)
  ÉCHEC il nomme son échelle et dit qu'il n'y a pas de seuil (échelle z · seuil 2.5 …)
  ÉCHEC six barres, et chacune porte une ÉTIQUETTE (['', '', '', '', '', ''])
  ÉCHEC le verdict nomme la cible retenue, et ne lui invente pas une fréquence (CIBLE 3 · 0 Hz)
  ÉCHEC et dit sur combien de flashs elle repose (CIBLE 3 · 0 Hz)
  ÉCHEC la cible qui domine remplit sa barre, la plus faible est vide ([0, 0, 0, 0, 0, 0])
  ÉCHEC une manche non conclue le dit sans parler ni de z ni d'une cible (aucune cible (rien au-dessus de z=2.5))
[console-smoke] VERDICT : PROBLÈME                                            EXIT=1
```

Les sept lignes reproduisent **mot pour mot** l'écran décrit par la revue. Les scores du test sont
volontairement tous NÉGATIFS : des scores positifs auraient caché la moitié du défaut (six barres à
zéro = un écran parfaitement muet).

### 2.4 — 3.9 et 3.11 (`research/`), non demandées mais faites

`research/app.py --smoke` n'a pas de `chk` : il signale par exception. Six `assert` y ont été
ajoutés, dont deux prouvés par mutation :

- **`os.path.exists` restauré dans `_status`** →
  `AssertionError: ...et l'accueil affiche RÉELLEMENT ce texte, pas un os.path.exists (modèles — c-VEP : oui    P300 : oui)`
- **`rng.shuffle` local restauré dans `_run_round`** →
  `AssertionError: _run_round doit tirer son ordre de blocs_melanges et ne pas remélanger localement`

⚠️ **Ma première version de l'assertion 3.9 ne rougissait PAS**, et je l'ai découvert en la mutant :
elle comparait la ligne d'accueil à l'état de `data/`, or ce poste a un modèle valide
(`p300_model_20260817-135716.joblib`) — « oui » et « 1 modèle » y sont tous deux cohérents.
Réécrite : `_p300_status(dispo)` est extraite, testée sur des listes FABRIQUÉES, puis on prouve que
l'accueil passe bien par elle. Machine-indépendante.

---

## 3. Le reste du lot, constat par constat

**3.3 — la docstring du moteur.** `decoded_p300` ajouté à l'inventaire des flux publiés, plus un
inventaire de ce qu'il **ÉCOUTE** (`EEG_API_Unicorn_stim`). « Pas encore dans le moteur : c-VEP,
P300, ErrP » → « c-VEP et ErrP ». « Pas encore non plus : le control plane entrant, les marqueurs »
→ le control plane seul ; les marqueurs existent depuis le 2026-08-17, avec le renvoi vers
`core/markers.py` et `docs/markers.md`. Ajouté aussi `--mode p300` aux exemples et le montage à
deux terminaux du P300, à côté de celui du SSVEP.

**3.4 — le champ `unavailable` de l'ErrP.** Il disait « Demande un MARQUEUR entrant » trois lignes
sous une docstring disant que l'infrastructure existe. Réécrit pour dire ce qui manque VRAIMENT
(le décodeur dans `core/modes/`) et que le transport, lui, est là. Comptes en dur de la docstring
retirés (`registry.MODES` est la seule source).

**3.5 — le commentaire d'orientation de `runtime.py`.** « MÛRS (leur époque tient dans le tampon) »
promettait ce que `markers_murs` ne vérifie pas : elle ne regarde que le côté **POST**. Le
commentaire dit maintenant ce que « mûr » signifie exactement, pourquoi le côté PRÉ peut manquer
(tampon glissant, tour de boucle long), et **exige** de garder `if epoque is None` en COMPTANT ce
qu'elle jette. C'est le seul cahier des charges qu'aura l'auteur de l'ErrP.

**3.8 — `decrire(None)` levait.** `os.path.isfile(None)` et `os.path.basename(None)` lèvent tous
deux un `TypeError`, sur la fonction publique qui remplit la liste de modèles de la console — à un
fil Qt de distance. Gardée comme `charger` l'avait été. Le `chemin and` court-circuite aussi
l'entier `0`, que `os.path.isfile` prendrait pour un descripteur de fichier (stdin). Trois
assertions (`None`, `""`, `0`).

**3.10 — la calibration écrasait `data/p300_model.joblib`.** `chemin_modele_horodate()` écrit
`p300_model_AAAAMMJJ_HHMMSS.joblib` — même geste que la calibration MI du moteur, et `MOTIF`
(`p300_model*.joblib`) les liste déjà du plus récent au plus ancien. Conséquence traitée :
`mode_p300(model_path=None)` prend désormais le plus récent CHARGEABLE au lieu de `P300_MODEL_PATH`
(qui est précisément le modèle que `charger` refuse). Deux `assert` : le chemin n'est jamais
`P300_MODEL_PATH`, et il correspond bien à `MOTIF` — préserver un fichier que plus personne ne peut
choisir n'aurait servi à rien.

**3.11 — l'invariant anti-répétition n'existait que dans l'émetteur.** `blocs_melanges` extraite de
`build_markers`, et **les trois sites** l'appellent maintenant : l'émetteur, la calibration
(`_run_round`) et le P300 live de `research/app.py`. Le mélange n'est plus écrit qu'une fois. Un
`assert` par inspection de source empêche un `shuffle` local de réapparaître : c'est justement la
propriété « une seule source » qu'on veut tenir, et un mélange local repasserait tous les tests de
séquence, qui ne regardent que l'émetteur.

**3.12 — le `--smoke` de l'émetteur n'exécutait jamais `run()`.** Il retournait avant l'import de
pygame. Il joue maintenant `run()` POUR DE VRAI sous `SDL_VIDEODRIVER=dummy` (le patron de
`research/app.py`), 2 manches à `P300_MIN_REPS`, avec un `journal` qui capture chaque marqueur
réellement poussé et son horodatage. Sept assertions neuves dessus, dont **la pause entre manches**
et « le dernier marqueur envoyé est toujours un `round_end` ». Coût : 11 s.

⚠️ Le smoke publie sous `EEG_API_Unicorn_stim_smoke`, **pas** sous le nom du contrat public : un
test ne doit jamais pouvoir répondre à la place d'un vrai émetteur.

**3.13 — rien n'indiquait si le moteur écoute.** `wait_for_consumers(5.0)` avant le premier flash
(borné, on démarre quand même après — enregistrer sans moteur reste légitime, ce qu'on refuse c'est
de le faire sans le savoir) et `have_consumers()` dans le HUD, en direct.

**3.14 — `--targets` accepté sans validation.** `valide_reglages()` refuse au lancement, en nommant
la constante. Étendu à `--reps` : le lot 2 en a fait un **plafond appliqué**, donc `--reps 12` ferait
abandonner toutes les manches, et sous `P300_MIN_REPS` le moteur refuse de décider. Huit assertions
(`--targets 0/2/4/7`, `--reps 0/1/9/12`). `sys.exit(1)` sur refus, même hors smoke.

**3.15 — `registry.check()` confondait ABSENT et sous-dimensionné.** Deux messages, comme le
contrôle jumeau d'`epoch_s` : le champ vaut `0.0` par défaut, donc l'oubli EST le cas par défaut du
prochain auteur, et « marker_epoch_s=0 s est SOUS 0,95 s » l'envoie vérifier une arithmétique alors
qu'il lui manque un champ. Le message d'oubli donne la valeur à écrire. Trois assertions sur un
registre fabriqué (absent / trop court / pile juste).

**3.16 — la doc.** Voir §5.

**Mineurs traités :** `--targets 0` → refusé au lieu d'un `IndexError` nu · `--targets 2` (séquence
parfaitement alternée, donc 100 % prévisible) → refusé · géométrie **lue** dans `p300_targets(n)`
au lieu d'être recalculée en `2πi/n` (identique à n=6, divergente dès n=3, `cvep_targets(3)`
reprenant les angles de `COMMANDS`) · rayon du point de fixation `3` → `FIX_DOT_R = 2`, la valeur
sous laquelle les données d'entraînement ont été enregistrées (2,25× la surface) · `--seconds` testé
dans `poll()`, donc en pleine manche et non plus seulement en fin de manche · ESC en pleine manche
émet un `round_end` (le moteur refuse de décider et le DIT, au lieu de dix secondes de silence) ·
SOA **mesuré** (médiane des intervalles réels) affiché dans le HUD et à chaque fin de manche, le
théorique restant marqué comme tel · comptes en dur en prose retirés (`external.py`,
`console/app.py` ×2 — remplacés par des comparaisons au registre) · `research/__init__.py` disait
déjà que `p300_stimulus.py` n'ouvre pas le casque ; le **README** le classait encore dans la famille
« appli pygame » → une famille « Stimulus emitters » distincte · `{auc*100:.1f}` sans garde `None`
· `select({})` levait un `IndexError` nu → `(None, {})`, le non-choix que le contrat prévoit déjà ·
`p300_models` rendait un `tuple` là où `mi_models` rend une `list` → aligné · le message « depuis la
console » de `p300_models` (la console n'a pas de page de calibration P300) → le texte du `help` du
`Param`, recopié.

---

## 4. Le défaut que la revue n'avait pas vu — trouvé en écrivant le test de 3.15

En vérifiant que « pile la bonne valeur ne signale rien », l'assertion a rougi :

```
ÉCHEC ...et pile la bonne valeur ne signale rien
      (['piege : marker_epoch_s=0.95 s est SOUS pre_s+post_s=0.95 s de son runtime —
        chaque époque serait tronquée en silence'])
```

Mesuré : **`0.15 + 0.80` vaut `0.9500000000000001`**, donc `0.95 < 0.15 + 0.80` est **VRAI**.

Un auteur de mode qui écrit `marker_epoch_s=0.95` en clair — la valeur exacte et juste —
s'entendait dire que chaque époque serait tronquée en silence. **Le vrai P300 y échappait par
hasard**, en réécrivant la MÊME expression (`P300_PRE_S + P300_EPOCH_S`) des deux côtés. Un
garde-fou qui accuse une déclaration correcte est pire qu'absent : on apprend à ignorer ce qu'il
dit — et ce contrôle-là est précisément celui que la « dette assumée » de la vague désigne comme le
seul rempart de l'ErrP.

Correctif : `_EPS_S = 1e-9` sur les **deux** comparaisons de durées de `check()` (`marker_epoch_s`
et `epoch_s`/`imagery_s`, même maladie). 1 ns est sans commune mesure avec un échantillon (4 ms à
250 Hz), donc aucune vraie troncature ne peut se glisser dessous. Le test écrit `0.95` **en clair**,
avec un commentaire disant pourquoi : réécrire la somme des deux côtés le ferait passer même sans
tolérance, exactement comme le P300 y échappait.

---

## 5. La documentation réaccordée

`docs/markers.md` et `README.md` restent en **anglais** (convention du projet pour les pages
étudiantes, comme `docs/network.md`) ; `docs/recette.md` en **français**.

**Les trois textes rendus faux par les lots 1 et 2 :**

1. « Changing it later means restarting the engine, not just the mode. » → **faux depuis le lot 1**
   (l'inlet est libéré dès qu'aucun mode actif n'écoute). Réécrit, aligné mot pour mot sur l'aide du
   réglage `stream_in` déjà réaccordée par le lot 2. Ajouté au passage : deux émetteurs du même nom
   sont signalés (lot 1, constat 1.3) — utile en salle de TP.
2. **`P300_REPS` est devenu un plafond APPLIQUÉ** (lot 2) et ce n'était documenté nulle part.
   Nouvelle section « How many times may a target flash? » : entre 2 et 8, le moteur l'applique,
   au-delà **toutes** les manches sont abandonnées, et le chiffre voyage dans
   `decoding/max_reps_per_target`.
3. « si ce nombre grimpe » (3.16) promettait une observation impossible. Les compteurs étant
   exposés par le lot 1, une section **« Where those numbers actually are »** dit les trois
   endroits : le terminal du moteur (paliers 1/10/100…), le flux `status`
   (`marqueurs.{perdus,futurs,illisibles,inlet_erreurs,connecte}` + les quatre du mode P300), et la
   console. `connecte` est désigné comme le premier à regarder.

**Autres corrections de `markers.md` :** la pause entre manches (avec son pourquoi) · les
métadonnées `decoding/` en tableau, dont `decision_scale=logodds` · un avertissement explicite
« il n'y a **aucun seuil** sur ces scores, et ils sont normalement **négatifs** — un client qui
filtre sur `confidence > 0` jette toutes les bonnes réponses » · l'émetteur d'exemple boucle
maintenant sur les manches avec sa pause, appelle `wait_for_consumers` au lieu d'un `sleep(2)`
optimiste, et rappelle d'envoyer un `round_end` même en sortie anticipée · **« It opens no
headset »** répété là où l'étudiant le lira (§ horodatage et § modèle) · les modèles horodatés.

**`docs/recette.md` §2.7** : « recommence six fois en changeant de cible » redevient faisable et
dit **quand** changer de cible (pendant la pause, le seul moment sûr). Ajouté : le contrôle
« le moteur écoute », où lire les compteurs, ce que la console doit afficher (log-odds, jamais
« échelle z »), et l'avertissement `--reps`/`--targets`.

---

## 6. Comptage des assertions

Méthode : appels `chk(` **moins** les lignes `def chk(`, plus un contrôle AST (premier argument de
chaque `chk`, blancs normalisés) pour lister les disparues.

| fichier | avant | après |
|---|---|---|
| `src/core/modes/external.py` | 0 | 0 |
| `src/core/modes/runtime.py` | 12 | 12 |
| `src/core/modes/registry.py` | 5 | **8** |
| `src/core/p300_decoder.py` | 0 | 0 |
| `src/core/p300_models.py` | 14 | **18** |
| `src/console/live_views.py` | 0 | 0 |
| `src/console/app.py` | 96 | **105** |
| `src/research/p300_stimulus.py` | 6 | **16** |
| `src/research/p300_calibrate.py` | 0 | 0 |
| `src/research/app.py` | 0 | 0 |
| **total `chk`** | **133** | **159** |

Plus **6 `assert`** dans `src/research/app.py --smoke` (ce fichier signale par exception, pas par
compteur) : 0 → 6.

**Aucune assertion préexistante n'a été retirée ni affaiblie.** Le contrôle AST liste
`DISPARUES 6`, toutes des RÉÉCRITURES, toutes justifiées :

| avant | après | pourquoi |
|---|---|---|
| `modeles_disponibles(dossier) == ()` | `== []` | mineur « tuple vs list » ; `[] == ()` est faux, donc plus STRICTE sur le type |
| `modeles_disponibles(dossier) == (bon,)` | `== [bon]` | idem |
| `dispo == (recent, ancien)` | `== [recent, ancien]` | idem |
| `modeles_disponibles(vide) == ()` | `== []` | idem |
| `len(externes) == 2` | `sorted(ids) == sorted(ids du registre)` | compare les IDENTITÉS et non un compte : « deux » resterait vrai si la grille montrait le c-VEP deux fois. Plus stricte, et ne vieillit plus |
| `len(console.calib_pages) == 1` | `sorted(pages) == sorted(ids « calibration console »)` | idem : identités contre compte, et lues dans le contrat |

---

## 7. Tests

Aucun moteur ne tournait — `Get-Process python` (via `tasklist`) vérifié **avant chaque
lancement**, 0 processus à chaque fois. Un seul programme à la fois. Aucun fichier écrit hors des
répertoires temporaires ; `data/` inchangé (vérifié par `git status`).

| commande | verdict |
|---|---|
| `python src/core/p300_decoder.py` | `VERDICT : OK`, EXIT=0 |
| `python src/core/p300_models.py` | `VERDICT : OK`, EXIT=0, **18 assertions** |
| `python src/core/modes/registry.py` | `VERDICT : OK`, EXIT=0, **8 assertions** |
| `python src/research/p300_stimulus.py --smoke` | `VERDICT : OK`, EXIT=0, **16 assertions**, 11 s |
| `python src/core/server.py --smoke` | **17 sous-tests, 17 `VERDICT : OK`**, 0 `ÉCHEC`, EXIT=0 |
| `python src/console/app.py --smoke` | `VERDICT : OK`, EXIT=0, **105 assertions** |
| `python src/research/app.py --smoke` | `smoke OK`, EXIT=0, 6 `assert` |

Et, `registry.py` ayant bougé, les cinq gardes du Motor Imagery — qu'aucun smoke n'exécute :

| commande | verdict |
|---|---|
| `python src/core/acquisition.py --synthetic` | EXIT=0 |
| `python src/core/modes/mi.py` | `VERDICT : OK`, EXIT=0 |
| `python src/core/mi_models.py` | `VERDICT : OK`, EXIT=0 |
| `python src/core/modes/calibration.py` | `VERDICT : OK`, EXIT=0 |
| `python src/core/modes/mi_calib.py` | `VERDICT : OK`, EXIT=0 |

Bonus : `python src/core/modes/runtime.py` → `VERDICT : OK`, EXIT=0.

---

## 8. Mes inquiétudes

**a) Le rendu P300 de la console n'a JAMAIS été vu à l'écran.** Il est prouvé sur un état fabriqué,
en `QT_QPA_PLATFORM=offscreen`. Les textes tiennent-ils dans la largeur ? Les six étiquettes
`cible 3 · -0,42` sont-elles lisibles ? Aucune idée. Et le reproche du lot précédent tient toujours :
**la console n'a jamais été ouverte en fenêtre**.

**b) L'échelle relative des barres du P300 est un choix, pas une évidence.** La plus faible est
toujours vide et la plus forte toujours pleine — même quand les six scores sont à 0,01 d'écart,
c'est-à-dire quand il n'y a rien à décider. L'écran dit « barres relatives entre elles, pas une
échelle absolue » et la valeur chiffrée est à côté de chaque nom, mais un étudiant pressé peut lire
une barre pleine comme une certitude. L'alternative (mettre l'échelle sur `margin`) supposerait que
le moteur publie `margin` dans sa SORTIE, ce qu'il ne fait pas — il ne la met que dans les
métadonnées du flux, que la console ne lit pas. C'est corrigeable, mais ça touche `modes/p300.py`,
hors de mon lot.

**c) `valide_reglages` refuse `--targets` autre que 6, et c'est un choix discutable.** L'argument
devient purement décoratif. Je l'ai gardé plutôt que de le supprimer parce que le message qu'il
imprime **enseigne** quelque chose (pourquoi 6, et ce qui casserait), là qu'une option absente
n'enseigne rien. Mais quelqu'un qui veut vraiment expérimenter à 4 cibles doit maintenant éditer
`config.py` — ce qui est correct (le moteur code 6 en dur), sans être agréable.

**d) `--reps` : j'ai imposé un PLANCHER que la revue ne demandait pas.** `P300_MIN_REPS <= reps` en
plus du plafond. Justification : le lot 2 a porté le plancher de manche du moteur à
`n_targets × P300_MIN_REPS`, donc `--reps 1` produirait des manches systématiquement refusées —
même panne que `--reps 12`, à l'autre bout. Si ce plancher gêne, c'est la ligne à retirer.

**e) L'`assert` par inspection de source (3.11) est inhabituel.** `"blocs_melanges" in src and
"shuffle" not in src` casse si quelqu'un renomme la fonction — avec un message clair, mais il casse.
Je l'ai préféré à un test de la séquence produite, qui ne pouvait rien prouver à l'échelle du smoke
(`eff_reps=1`, donc aucune jonction n'existe et une permutation seule n'a jamais de répétition
immédiate). C'est le seul instrument que j'aie trouvé pour la propriété « ce mélange ne s'écrit
qu'à UN endroit ».

**f) Le smoke de l'émetteur coûte 11 s de temps de mur** et touche le réseau (un `StreamOutlet` sous
`EEG_API_Unicorn_stim_smoke`). C'est le prix de « `run()` est réellement exécuté ». Il est
réductible en raccourcissant la pause, mais on ne testerait alors plus la vraie valeur.

**g) Rien de ce lot n'a été vérifié au casque**, ni avec un vrai émetteur sur une seconde machine.
En particulier : `wait_for_consumers(5.0)` n'a jamais été mesuré contre un vrai moteur qui démarre.
Si la résolution LSL est plus lente que 5 s au premier lancement d'un processus neuf — et le lot 1 a
mesuré que `resolve_byprop` échoue aux tout premiers appels d'un processus neuf — l'étudiant lira
« PERSONNE n'écoute » alors que tout va bien. Le message le dit (« je flashe quand même », et
l'indicateur du HUD est en direct), donc l'erreur est bénigne, mais **c'est un faux négatif
plausible, et c'est le premier chiffre à re-mesurer en salle.**

**h) Le point de fixation passe de 3 px à 2 px** (`FIX_DOT_R`). C'est le bon alignement sur les
données d'entraînement, mais c'est aussi 2,25× moins de surface pour un repère de fixation, sur un
écran de TP peut-être plus grand que celui de développement. À regarder de ses propres yeux avant
d'en faire une séance.

**i) `data/p300_model.joblib` est préservé mais reste ILLISIBLE.** 3.10 garantit que la prochaine
calibration ne l'écrasera pas — pas qu'il redevienne utile. Il reste un fichier que `charger` refuse,
et il continuera d'apparaître dans `ls data/` sans jamais apparaître dans une liste de modèles. Le
préserver était la décision du chantier ; je l'applique, je ne la rediscute pas.
