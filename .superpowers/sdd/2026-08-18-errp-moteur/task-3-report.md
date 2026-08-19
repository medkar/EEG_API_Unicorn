# Task 3 — le réglage : un taux, pas un seuil — rapport d'implémentation

Statut : **DONE**
Commit : `67e121e` — "Let the student set a rate, and derive the threshold from their own calibration"
Base : `3e190ef` (HEAD de `main` avant cette tâche, tour de correction 1 de la tâche 2)

## Ce qui a été fait

Un seul fichier modifié : `src/core/modes/errp.py` (+97/-10, un seul `git add` ciblé — le rapport
lui-même reste hors du commit, comme les rapports des tâches 1 et 2 : `git log` confirme que ce
dossier SDD n'a jamais été suivi pour ce chantier).

**Step 1 — le réglage.** `Param(key="tnr_target", ...)` ajouté verbatim au brief dans `SPEC.params`,
avec `ERRP_TNR_TARGET` importé de `core.config` (il existait déjà, `= 0.85`).

**Step 2 — le recalcul.** `ErrPRuntime.__init__` ne pose plus `self.seuil = float(self.model.
threshold_)` : il lit `params["tnr_target"]`, rappelle `pick_threshold(self.model.oof_y_, self.
model.oof_scores_, tnr_target=cible)` — la MÊME fonction que `ErrPModel.fit` utilise déjà pour poser
`threshold_` — et garde le résultat dans `self.point_de_fonctionnement = {"tnr_target", "seuil",
"tpr", "tnr"}`, les 4 clés exactes que la tâche 4 lira. Le message `print` (TNR visé ET obtenu côte
à côte) est verbatim le texte du brief. Ajout non demandé littéralement mais mineur : un paragraphe
dans la docstring de `ErrPRuntime` documentant ce nouvel attribut public, pour qui arrive à la
tâche 4 sans relire tout `__init__`.

**Step 3 — le test de monotonie, avec un écart DÉLIBÉRÉ par rapport au code donné.** Voir la section
suivante : c'est l'objection substantielle de cette tâche.

## ⚠️ Objection mesurée : le test donné par le brief ne peut pas réussir la preuve rouge-puis-vert que le brief lui-même demande

Le code de l'étape 3 fourni dans le brief appelle `pick_threshold(modele.oof_y_, modele.oof_scores_,
tnr_target=cible)` **directement**, sans jamais construire d'`ErrPRuntime`. L'étape 4 demande de
casser le réglage en remplaçant `tnr_target=cible` par `tnr_target=ERRP_TNR_TARGET` **dans le
recalcul de `__init__`** (Step 2) et d'observer l'échec.

Mais un test qui n'appelle que `pick_threshold` ne touche jamais `ErrPRuntime.__init__` : muter
`__init__` ne peut donc rien y changer. **Je l'ai mesuré, pas seulement raisonné** : j'ai remis
temporairement le code du test à sa forme littérale du brief (boucle directe sur `pick_threshold`,
aucun `ErrPRuntime`), appliqué la mutation exacte de l'étape 4 dans `__init__`, et relancé —

```
EXITCODE=0
  OK   viser plus de bonnes commandes MONTE le seuil ([-0.628, 0.044, 0.766])
  OK   ...et fait attraper MOINS d'erreurs ([0.538, 0.462, 0.385])
  OK   et chaque point atteint la cible demandée ([(0.7, 0.704), (0.85, 0.926), (0.95, 0.963)])
[errp] VERDICT : OK
```

**VERT, alors que `__init__` est cassé.** La boucle du brief recalcule les trois points avec sa
propre variable `cible`, sur le VRAI `pick_threshold` (jamais muté, jamais faux) — elle ne consulte
`ErrPRuntime` nulle part, donc ne peut pas voir qu'il ignore `params["tnr_target"]`. Le seul test du
brief qui approche `ErrPRuntime` (le point unique `rt.seuil == modele.threshold_`, déjà présent
avant cette tâche) ne le voit pas non plus : par construction, `values["tnr_target"]` vaut
`ERRP_TNR_TARGET` par défaut, donc la mutation est invisible sur ce point-là aussi — c'est
exactement l'angle mort qui a laissé passer `stream_in` (cosmétique) à la revue du P300, le
précédent que le brief cite lui-même comme raison d'être de ce test.

**Correctif appliqué** : le test réellement écrit construit un VRAI `ErrPRuntime` à CHAQUE cible
(`essai_cible = dict(values, tnr_target=cible)`, trois instances), lit `.seuil` et
`.point_de_fonctionnement` sur CHACUNE, et les recoupe avec un appel direct à `pick_threshold` (qui
sert de référence indépendante, pas de raccourci). Rejoué avec la mutation réelle de l'étape 4 :
**5 assertions tombent** (voir la preuve ci-dessous) — le point à `cible=0.85` reste vert par
coïncidence (`0.85 == ERRP_TNR_TARGET`), les deux autres et les trois résumés de monotonie rougissent.
J'ai gardé la boucle directe sur `pick_threshold` du brief comme croisement de référence à
l'intérieur de chaque itération (elle prouve autre chose d'utile : que le runtime retombe EXACTEMENT
sur ce que rendrait un appel direct, pas seulement « quelque chose qui varie ») — mais seule la
construction de trois `ErrPRuntime` rend la preuve rouge-puis-vert honnête.

## Comptage des assertions (méthode excluant `def chk(cond, msg):`)

`grep -n "chk(" src/core/modes/errp.py | wc -l` rend 60 lignes ; moins 1 pour `def chk(cond, msg):`
= **59 sites d'assertion**, contre **51 avant** cette tâche (confirmé par le rapport de la tâche 2)
→ **+8 sites**. Aucun site existant n'a été retiré.

Deux sites existants ont leur **texte/condition mis à jour**, pas affaiblis :
- `{p.key for p in SPEC.params} == {"model"}` → `== {"model", "tnr_target"}` : la condition change
  parce que le fait qu'elle décrit a changé (le réglage existe maintenant) — le message aussi
  (« tnr_target arrive à la tâche 3 » n'a plus de sens une fois la tâche 3 faite).
- `rt.seuil == float(modele.threshold_)` : condition **inchangée**, message reformulé (« le seuil
  de départ est celui APPRIS » → « le seuil RECALCULÉ retombe exactement sur celui qu'avait appris »)
  parce que la mécanique sous-jacente a changé (assignation directe → recalcul qui coïncide avec
  l'ancien résultat au réglage par défaut), sans changer ce qui est vérifié.

Les 8 nouveaux sites : le défaut de `tnr_target` (1) ; le message de point de fonctionnement bien
DIT au démarrage, capturé et vérifié (1) ; `point_de_fonctionnement` expose exactement les 4 clés
(1) ; ses valeurs correspondent à la cible et au seuil obtenus (1) ; le recoupement runtime ==
`pick_threshold` direct, À L'INTÉRIEUR d'une boucle sur 3 cibles — donc ce site s'exécute 3 fois (1
site, 3 exécutions) ; la monotonie des seuils (1) ; celle des TPR (1) ; l'atteinte de la cible à
chaque point (1). **Exécutions réelles** (ce que `_selftest` imprime effectivement) : 61 lignes
`OK`/`ÉCHEC`, pas 59, à cause du site bouclé — confirmé en comptant le run final (61 `OK`, 0
`ÉCHEC`) : 58 sites × 1 exécution + 1 site × 3 exécutions = 61.

## Tests lancés, dans l'ordre

Garde-fou avant chaque lancement : `Get-Process python -ErrorAction SilentlyContinue` — vide à
chaque fois (0 processus, aucun moteur qui traîne).

1. `python src/core/modes/errp.py` (implémentation correcte) → `[errp] VERDICT : OK`, **61/61 `OK`**,
   `EXITCODE=0`.
2. Mutation appliquée dans `__init__` (`tnr_target=cible` → `tnr_target=ERRP_TNR_TARGET`) → **preuve
   ROUGE** ci-dessous, `EXITCODE=1`.
3. Mutation retirée → **preuve VERTE** ci-dessous, `EXITCODE=0`, 61/61 `OK` de nouveau.
4. `python src/core/server.py --smoke` : échoue sur `[smoke-tampon]` — **pré-existant, sans rapport
   avec ce fichier**, voir plus bas.
5. Après commit, relance finale de `python src/core/modes/errp.py` sur l'état commité (belt and
   suspenders) : `EXITCODE=0`, 61 `OK`, 0 `ÉCHEC`.

## Preuve ROUGE-PUIS-VERT (test de monotonie, tâche 3)

**ROUGE** (`tnr_target=cible` remplacé par `tnr_target=ERRP_TNR_TARGET` dans le recalcul de
`__init__` — le réglage qui ne fait rien) :
```
  OK   avec le réglage par défaut (tnr_target=0.85, identique à celui de la calibration), le seuil RECALCULÉ retombe exactement sur celui qu'avait appris ErrPModel.fit (0.04441102323717849)
  OK   ...et ce recalcul se DIT au démarrage, avec le TNR visé ET celui obtenu (...)
  OK   point_de_fonctionnement expose EXACTEMENT les 4 clés promises à la tâche 4 (...)
  OK   ...avec la cible demandée et le seuil qu'elle a produit (...)
  ÉCHEC à tnr_target=0.7, le runtime recalcule EXACTEMENT ce que rend pick_threshold sur les scores de SA calibration (seuil=0.04441102323717849 vs -0.627556722690811)
  OK   à tnr_target=0.85, le runtime recalcule EXACTEMENT ce que rend pick_threshold sur les scores de SA calibration (seuil=0.04441102323717849 vs 0.04441102323717849)
  ÉCHEC à tnr_target=0.95, le runtime recalcule EXACTEMENT ce que rend pick_threshold sur les scores de SA calibration (seuil=0.04441102323717849 vs 0.7656548684139071)
  ÉCHEC viser plus de bonnes commandes MONTE le seuil ([0.044, 0.044, 0.044])
  ÉCHEC ...et fait attraper MOINS d'erreurs ([0.462, 0.462, 0.462])
  ÉCHEC et chaque point atteint la cible demandée ([(0.7, 0.926), (0.85, 0.926), (0.95, 0.926)])
[errp] VERDICT : PROBLÈME
EXITCODE=1
```
5 `ÉCHEC`, exactement localisés dans le bloc de monotonie — rien ailleurs n'a bronché (52/57 autres
sites toujours `OK`, la mutation est bien isolée à ce qu'elle prétend casser).

**VERT** (mutation retirée) :
```
[errp] point de fonctionnement : garde 70.4% des bonnes commandes (visé 70%), attrape 53.8% des erreurs — seuil -0.628
  OK   à tnr_target=0.7, le runtime recalcule EXACTEMENT ce que rend pick_threshold sur les scores de SA calibration (seuil=-0.627556722690811 vs -0.627556722690811)
[errp] point de fonctionnement : garde 92.6% des bonnes commandes (visé 85%), attrape 46.2% des erreurs — seuil 0.044
  OK   à tnr_target=0.85, le runtime recalcule EXACTEMENT ce que rend pick_threshold sur les scores de SA calibration (seuil=0.04441102323717849 vs 0.04441102323717849)
[errp] point de fonctionnement : garde 96.3% des bonnes commandes (visé 95%), attrape 38.5% des erreurs — seuil 0.766
  OK   à tnr_target=0.95, le runtime recalcule EXACTEMENT ce que rend pick_threshold sur les scores de SA calibration (seuil=0.7656548684139071 vs 0.7656548684139071)
  OK   viser plus de bonnes commandes MONTE le seuil ([-0.628, 0.044, 0.766])
  OK   ...et fait attraper MOINS d'erreurs ([0.538, 0.462, 0.385])
  OK   et chaque point atteint la cible demandée ([(0.7, 0.704), (0.85, 0.926), (0.95, 0.963)])
[errp] VERDICT : OK
EXITCODE=0
```
Sur la séance synthétique du selftest (40 essais, seed fixe) : viser 70 % de bonnes commandes gardées
attrape 54 % des erreurs, viser 85 % en attrape 46 %, viser 95 % en attrape 38 % — même sens que les
chiffres de la séance de référence cités dans l'aide du réglage (95 %→24 %, 85 %→50 %, 70 %→71 %),
échelle différente vu qu'il s'agit d'un jeu synthétique à 40 essais et non de la vraie calibration à
200.

## `server.py --smoke` : un échec pré-existant, isolé par git stash

`[smoke-tampon]` échoue (« cadence médiane 0.02 ms attendu 4.00 ms ») — texte et sous-smoke
**identiques** à la flakiness déjà documentée dans le rapport de la tâche 2 (tour de correction 1).
Avant de l'écarter j'ai vérifié, pas supposé :
1. `grep` : `errp.py` n'est importé ni par `server.py` ni par `registry.py` — il ne peut
   structurellement rien changer à ce chemin d'exécution.
2. Reproduit **2 fois de suite** avec mon changement en place.
3. `git stash push -- src/core/modes/errp.py` (retour exact à `3e190ef`) → **même échec, même
   ligne, même message** sur l'arbre non modifié. `git stash pop` a restauré mon travail ensuite
   (confirmé : `grep -c ERRP_TNR_TARGET` = 4 après restauration).

Pré-existant, sans rapport avec cette tâche. `Get-Process python` vide avant et après chacun des
lancements (3 runs de `--smoke`, aucun résidu).

## Mes inquiétudes

1. **L'objection ci-dessus est la plus substantielle** : le code de test donné par le brief à
   l'étape 3, pris littéralement, ne peut pas satisfaire la preuve rouge-puis-vert que l'étape 4
   demande — je l'ai mesuré (VERT sous la mutation), pas seulement déduit. J'ai réécrit le test
   pour qu'il construise un vrai `ErrPRuntime` par cible plutôt que d'appeler `pick_threshold` en
   direct, en gardant l'appel direct comme référence croisée à l'intérieur de chaque itération. Si
   l'intention était différente (par exemple un test à deux niveaux, l'un contre `pick_threshold`
   déjà prévu tel quel, l'autre contre `ErrPRuntime` ajouté séparément ailleurs dans le chantier),
   je ne l'ai pas vue dans le brief — à corriger si c'est le cas.

2. **Le comptage d'assertions n'est plus 1 site = 1 exécution**, contrairement aux tâches 1 et 2 :
   un des 8 nouveaux sites est à l'intérieur d'une boucle sur 3 cibles (0,70/0,85/0,95), donc
   s'exécute 3 fois. 59 sites (51+8) mais 61 lignes `OK`/`ÉCHEC` à l'exécution (58×1 + 1×3). Je l'ai
   détaillé dans la section comptage pour que la prochaine tâche qui recompte ne soit pas surprise
   par l'écart entre les deux nombres.

3. **`pick_threshold` retombe théoriquement sur son seuil « repli » (maximise le TNR) uniquement
   si AUCUN seuil n'atteint la cible** — et j'observe, sans l'avoir cherché, que `cand` inclut
   toujours `scores.max() + 1e-6` : un seuil strictement au-dessus de tous les scores classe tout
   « correct », donc TNR=1,0 est TOUJOURS atteignable (dès qu'il existe au moins une bonne commande
   dans les scores hors-pli). Pour toute cible ≤ 1,0 — donc pour tout le domaine `[0.50, 0.99]` du
   réglage — la branche de repli semble donc mathématiquement inatteignable en usage normal ; elle
   ne se déclencherait que si `oof_y_` ne contenait AUCUNE bonne commande, un cas dégénéré. Je n'ai
   PAS touché `errp_decoder.py` (hors périmètre de cette tâche, et le brief demande explicitement de
   GARDER ce comportement) — je le signale seulement parce que le brief insiste sur ce point précis
   (« il ne faut pas rater ») et que je voulais vérifier plutôt que supposer. Le message qui annonce
   le TNR obtenu à côté du visé reste correct et utile dans tous les cas (y compris celui, plus
   probable en pratique, où la cible est atteinte mais avec un TPR décevant).

4. **`self.model.oof_scores_`/`oof_y_` à `None`** (un modèle dont `fit()` n'a jamais rempli ces
   attributs — moins de 10 essais, une seule classe, ou une classe à moins de 2 membres) ferait
   lever un `TypeError` brut dans `pick_threshold` (`np.asarray(None, dtype=float)`) plutôt qu'un
   refus proprement nommé comme `_desaccord_geometrie`. Je n'ai PAS ajouté de garde : le brief ne
   la demande pas, la séance de référence (200 époques, 5 blocs) en est loin, et
   `errp_models.charger` ne garantit rien de plus que `hasattr(modele, "score"/"is_error")`. Je le
   signale plutôt que de trancher en silence — un ajout d'une poignée de lignes si quelqu'un juge
   que ça vaut la peine.

   ⚠️ **CORRECTIF (tour de correction 1) : le diagnostic ci-dessus est INEXACT, relevé par le
   relecteur et vérifié moi-même** — `np.asarray(None, dtype=float)` ne lève PAS, il rend un
   tableau 0-d contenant `nan` (`array(nan)`, mesuré). La vraie exception est un `ValueError`, une
   ligne plus loin dans `pick_threshold`, sur `np.concatenate([scores, ...])` : un tableau 0-d ne
   peut pas être concaténé (`ValueError: zero-dimensional arrays cannot be concatenated`, mesuré
   aussi). Ça ne change pas la conclusion (toujours une exception numpy brute, sans rapport avec
   ce qu'il faut faire) mais c'est le seul endroit de ce rapport où j'ai supposé au lieu de
   mesurer — voir le tour de correction 1 plus bas, où c'est corrigé ET une garde est ajoutée.

5. Le brief ne montrait aucune autre consigne fausse : les chiffres de la séance de référence cités
   dans l'aide du réglage sont repris tels quels (je n'ai pas de moyen de les revérifier sans la
   vraie séance, hors périmètre de ce fichier), et les Steps 1-2 fonctionnent verbatim.

---

# Tour de correction 1 — un modèle sans scores hors-pli faisait tomber le moteur sur une exception numpy brute

Statut : **DONE**
Commit : `362fee1` — "Refuse a model with no out-of-fold scores by name, in two places"
Base : `67e121e` (le commit initial de cette tâche, ci-dessus)

## Ce que le relecteur a trouvé

Une régression PROPRE à cette tâche, pas un trou préexistant : avant le diff de la tâche 3,
`self.seuil = float(self.model.threshold_)` retombait sur `0.0` (l'attribut par défaut d'`ErrPModel`,
jamais `None`) — le mode démarrait, silencieusement peu pertinent, mais debout. Après, la même
situation fait tomber `__init__` sur `pick_threshold(None, None, ...)`, qui lève — vérifié par le
relecteur, puis par moi-même (voir mesure ci-dessous) : `ValueError: zero-dimensional arrays cannot
be concatenated`, une exception numpy brute, à des lignes de tout message nommé — l'inverse du
standard de ce fichier (`_desaccord_geometrie`, juste au-dessus, nomme précisément son refus).

**La cause** : `ErrPModel.fit` (`errp_decoder.py:179`) ne pose `oof_scores_`/`oof_y_` que si la
calibration a ≥10 essais, 2 classes, et une classe minoritaire ≥2 membres. En dessous, ces deux
attributs restent `None` — et rien ne l'écartait : `errp_models.charger` (`errp_models.py:54-55`)
ne vérifiait que `hasattr(modele, "score"/"is_error")`, jamais `oof_scores_` ni `cv_auc_`. Un tel
modèle apparaissait donc **normalement** dans la liste de la console.

## Mesuré, pas supposé — le mécanisme exact

```
>>> np.asarray(None, dtype=float)
array(nan)          # NE LÈVE PAS — 0-d, contient nan
>>> pick_threshold(None, None)
ValueError: zero-dimensional arrays cannot be concatenated   # lève ICI, dans np.concatenate
```

Ceci corrige mon propre §4 des inquiétudes ci-dessus, où j'avais écrit que `np.asarray(None,
dtype=float)` lève un `TypeError` — inexact, relevé par le relecteur : elle ne lève pas du tout,
l'exception vient une ligne plus loin. La conclusion ne change pas (une exception numpy brute
plutôt qu'un refus nommé), mais c'était bien une supposition, pas une mesure — le relecteur l'a noté
comme le seul endroit du rapport où je n'appliquais pas ma propre rigueur.

## Correctif : deux filets nommés, indépendants

1. **`errp_models.charger()`** (`errp_models.py`) : refuse maintenant tout modèle dont
   `oof_scores_`/`oof_y_` sont `None` (via `getattr(..., None) is None`, pas `hasattr` — un objet
   satisfaisant `score`/`is_error` sans porter `oof_scores_` du tout doit être traité pareil qu'un
   modèle qui le porte à `None`), avec une raison qui dit de recalibrer avec plus d'essais. C'est la
   porte qui décide ce qui apparaît dans la liste de la console : le refus à la SOURCE.

2. **`ErrPRuntime._sans_scores_oof()`** (`errp.py`), appelée dans `__init__` juste après
   `_desaccord_geometrie` : un SECOND filet indépendant, dans le style exact de sa voisine — même
   raisonnement que la garde `self.model is None` juste au-dessus (la course entre la validation et
   le démarrage : un fichier remplacé entre les deux reste possible, et seul le moteur peut le voir).

## Effet de bord trouvé en relançant, pas supposé

Le fixture existante du test « 3bis » (géométrie étrangère) construisait `ErrPModel(fs=125.0)` **sans
jamais l'entraîner** — donc avec `oof_scores_ = None` elle aussi. Une fois le premier filet en place,
`errp_models.charger` refusait CE modèle-là aussi, mais AVANT d'atteindre `_desaccord_geometrie` :
le test échouait avec MON nouveau message (« calibration trop courte… ») au lieu du message de
géométrie attendu (`"fs"`/`"125"`). Corrigé en entraînant réellement ce fixture (même recette que le
modèle principal, juste à `fs=125.0`) — la condition de l'assertion existante n'a pas changé, seule
sa fixture a été réparée pour continuer à exercer le code qu'elle vise. Je ne l'avais pas anticipé ;
je l'ai trouvé en relançant le test après le premier correctif, pas en le devinant à l'avance.

## Preuve ROUGE-PUIS-VERT

**`errp_models.py` — ROUGE** (avant le fix 1, le modèle dégénéré n'est pas refusé) :
```
  ÉCHEC un modèle sans scores hors-pli est refusé EN LE NOMMANT, avec quoi faire (None)
  ÉCHEC ...et il n'apparaît donc pas dans la liste proposée à l'étudiant ([...errp_model_degenere.joblib, ...errp_model.joblib])
  ÉCHEC le plus récent d'abord ([...errp_model_a.joblib, ...errp_model_degenere.joblib, ...errp_model_z.joblib])
[errp-models] VERDICT : PROBLÈME
EXITCODE=1
```
(La 3e ÉCHEC est un effet de bord ATTENDU et TRANSITOIRE : le fixture dégénéré, non filtré tant que
le fix 1 n'existe pas, pollue une liste que teste un AUTRE test déjà présent — résolu tout seul une
fois le fix 1 en place, sans y toucher.)

**`errp_models.py` — VERT** (fix 1 appliqué) :
```
  OK   fixture : 5 essais (< 10) ne posent PAS de scores hors-pli, la dégénérescence est réelle, pas simulée (None)
  OK   un modèle sans scores hors-pli est refusé EN LE NOMMANT, avec quoi faire (calibration trop courte pour régler un seuil (moins de 10 essais, une seule classe, ou une classe à moins de 2 membres — pas de scores hors-pli) : recalibre avec plus d'essais (`python src/research/app.py`, mode ErrP) : errp_model_degenere.joblib)
  OK   le plus récent d'abord ([...errp_model_a.joblib, ...errp_model_z.joblib])
[errp-models] VERDICT : OK
EXITCODE=0
```

**`errp.py` — ROUGE** (avant le fix 2 ; le fixture « 3bis » pas encore réparé non plus) :
```
  ÉCHEC un modèle entraîné sur une AUTRE géométrie d'époque est refusé au démarrage, en nommant l'écart (calibration trop courte pour régler un seuil (...) : geometrie_etrangere.joblib)
  ÉCHEC un modèle sans scores hors-pli est refusé au démarrage, EN LE NOMMANT, plutôt que de laisser pick_threshold lever une exception numpy brute (zero-dimensional arrays cannot be concatenated)
[errp] VERDICT : PROBLÈME
EXITCODE=1
```
La 2e ligne ÉCHEC montre EXACTEMENT le texte brut que le relecteur avait prédit, tel quel dans le
message d'assertion — la preuve que ce test observe la vraie fuite, pas un texte inventé.

**`errp.py` — VERT** (fixture réparé + fix 2 appliqué) :
```
  OK   un modèle entraîné sur une AUTRE géométrie d'époque est refusé au démarrage, en nommant l'écart (ce modèle n'a pas été entraîné sur la géométrie d'époque que ce mode prélève (fs : modèle 125.0, moteur 250) — ses scores seraient plausibles et faux. Recalibre (`python src/research/app.py`, mode ErrP) plutôt que de le forcer.)
  OK   fixture : 5 essais (< 10) ne posent PAS de scores hors-pli, la dégénérescence est réelle, pas simulée (None)
  OK   un modèle sans scores hors-pli est refusé au démarrage, EN LE NOMMANT, plutôt que de laisser pick_threshold lever une exception numpy brute (ce modèle n'a pas de scores hors-pli (calibration trop courte : moins de 10 essais, une seule classe, ou une classe à moins de 2 membres) — impossible d'y régler un seuil. Recalibre (`python src/research/app.py`, mode ErrP) plutôt que de le forcer.)
[errp] VERDICT : OK
EXITCODE=0
```

## Comptage des assertions (méthode excluant `def chk(cond, msg):`)

- **`errp.py`** : `grep -n "chk(" | wc -l` moins 1 = **61 sites**, contre **59 avant** ce tour → **+2**
  (fixture dégénérée valide, refus nommé). Exécutions réelles : **63 `OK`**, 0 `ÉCHEC` (61 sites, dont
  un toujours bouclé sur 3 cibles depuis le tour précédent → 60×1 + 1×3 = 63). Aucun site retiré ni
  affaibli ; le fixture « 3bis » a été réparé (entraîné au lieu de simplement construit) SANS toucher
  la condition de son `chk(...)`, qui reste `"fs" in refus_geo and "125" in refus_geo`.
- **`errp_models.py`** : **21 sites**, contre **18 avant** ce tour → **+3** (fixture dégénérée
  valide, refus nommé, absence de la liste). Exécutions réelles : **25 `OK`**, 0 `ÉCHEC`.

## Tests relancés, dans l'ordre

Garde-fou avant chaque lancement : vérifié via `Get-CimInstance Win32_Process -Filter
"Name='python.exe'"` (plus fiable que `Get-Process` seul pour distinguer un processus tiers d'un
moteur de ce projet) — deux processus SANS RAPPORT sont apparus pendant ce tour
(`scripts/run_all_tests.py`, `scripts/bench_rag.py`, tous deux à des chemins RELATIFS qui n'existent
pas dans ce dépôt — `Glob` confirme leur absence ici, donc lancés depuis un AUTRE répertoire, un
AUTRE projet) ; aucun des deux n'importe BrainFlow ni ce dépôt, aucun n'a été laissé tourner par moi.

1. `python src/core/errp_models.py` (avant fix 1) → **ROUGE**, `EXITCODE=1`.
2. Fix 1 appliqué → `python src/core/errp_models.py` → **VERT**, 25/25 `OK`, `EXITCODE=0`.
3. `python src/core/modes/errp.py` (avant fix 2, fixture 3bis pas encore réparé) → **ROUGE**,
   `EXITCODE=1`, 2 `ÉCHEC` (dont l'effet de bord sur le fixture 3bis, découvert ici).
4. Fixture 3bis réparé + fix 2 appliqué → `python src/core/modes/errp.py` → **VERT**, 63/63 `OK`,
   `EXITCODE=0`.
5. `python src/core/server.py --smoke` → **VERT cette fois**, 17/17 sous-smokes `OK`, `EXITCODE=0`
   (le `[smoke-tampon]` du tour précédent ne s'est pas reproduit ici — cohérent avec une flakiness
   intermittente, pas un état permanent).
6. Relance individuelle finale, l'une après l'autre : `errp.py` (63/63, exit 0), `errp_models.py`
   (25/25, exit 0).

`Get-CimInstance`/`Get-Process python` vérifié avant chaque lancement listé ci-dessus ; aucun
résidu de ce projet à aucun moment.

## Mes inquiétudes (ce tour)

1. **La correction du §4 est documentée en place ci-dessus**, pas réécrite en silence : le texte
   original reste, avec le correctif juste en dessous. C'est la même convention que le tour de
   correction 1 de la tâche 2 (`_rest_step`) — garder la trace de ce qui a été cru avant d'être
   mesuré.
2. **L'effet de bord sur le fixture « 3bis »** aurait pu passer inaperçu si je n'avais pas relancé
   le test complet après le fix 1 seul — je ne l'avais pas anticipé en écrivant le fix. C'est
   exactement le genre d'interaction que la relance systématique (plutôt que la seule lecture du
   diff) attrape.
3. **Les deux filets se recouvrent presque toujours en pratique** : puisque `validate()` ne propose
   que des modèles déjà passés par `errp_models.charger()` (la liste `choices`), le second filet
   (`_sans_scores_oof`) ne peut se déclencher SEUL que dans la course validation→démarrage — je l'ai
   donc testé en isolant le premier filet par monkeypatch (`errp_models.charger` court-circuité)
   plutôt qu'en comptant sur cette course pour se produire naturellement dans un test déterministe.
4. Point reporté par le coordinateur, non retouché : la branche de repli de `pick_threshold` reste
   un fait connu (mathématiquement inatteignable en usage normal), pas un défaut à corriger ici.
