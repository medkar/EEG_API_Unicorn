# Task 3 — rapport : deux décodeurs, un seul stimulus

**Statut : DONE**
**Commits : `f79efac`** — "Split rCCA from the Gold codes it was wrongly judged with"
**puis `c0ffb06`** — "Set the rCCA thresholds to reject noise, not to keep every good trial"
**puis `0398913`** — "Measure the c-VEP thresholds where the engine actually decides"
Base : `4315d00` (fin de la tâche 2). Les seuils finalement livrés sont ceux du dernier commit :
**`CVEP_RCCA_CORR_MIN = 0.24`, `CVEP_RCCA_MARGIN = 0.08`**, mesurés à k=2.

⚠️ Les deux encadrés ci-dessous sont les tours successifs, dans l'ordre. Le **second** fait foi
pour les valeurs.

> ## ⚠️ CORRECTION — les seuils livrés sont 0,26 / 0,09, pas 0,080 / 0,011
>
> La première livraison suivait la procédure du brief (« le quantile qui garde 95 % des essais
> corrects »), mesurait qu'elle rate son but, et posait le chiffre quand même en signalant le
> problème. **Décision du coordinateur, appliquée dans `c0ffb06` : poser 0,26 / 0,09**, le point de
> fonctionnement mesuré proposé en alternative. Le raisonnement, désormais écrit dans
> `core/config.py` pour qu'il ne se reperde pas :
>
> - **La procédure du brief était un critère de SENSIBILITÉ**, pas de rejet. « Ne pas rater ce qui
>   est bon » ne répond pas à la question qu'un seuil de décision pose ici, qui est « rejeter le
>   bruit ». Mesuré : elle fait émettre sur 89 % des essais avec 48 % de justesse — la justesse
>   qu'on a **sans aucun seuil** — et laisse passer 83 % du bruit pur. *Un seuil qui ne change rien
>   n'est pas un seuil.*
> - **L'argument qui tranche entre trop strict et trop permissif** : les deux échouent, mais pas de
>   la même façon. Trop STRICT = panne **visible** (« ça ne se déclenche jamais », repérée en trente
>   secondes — c'est ce qu'a vécu le SSVEP). Trop PERMISSIF = panne **invisible** : le mode émet avec
>   assurance sur du bruit, les scores ont l'air normaux, personne ne s'en aperçoit. Ce projet
>   existe en grande partie pour éliminer la seconde. On part strict ; la tâche 7 rendra ces seuils
>   réglables à chaud pour desserrer en séance.
>
> **Point de fonctionnement livré, mesuré : 71 % de justesse à l'émission, 27 % de taux d'émission,
> 10 % de bruit pur qui passe** (40 % des essais corrects gardés). Une personne, une séance,
> **43 essais corrects sur 90**.
>
> `--seuils` affiche maintenant **les deux couples** avec leur point de fonctionnement complet, pour
> que le prochain qui voudra rediscuter le choix n'ait pas à refaire l'analyse :
>
> ```
> $ python src/core/cvep_rcca.py --seuils data/cvep_calib_last.npz
> [rcca] cvep_calib_last.npz : 90 époques, 6 cibles, voies [4, 5, 6, 7]
> [rcca] leave-one-out : 47.8 %  (43/90, hasard 16.7 %)  —  43 essais corrects
> [rcca]          seuils | corrects gardés | émission | justesse si émis | bruit passé
> [rcca]  0.260 / 0.090 |          40 % |     27 % |             71 % |       10 %   (LIVRÉS (config.py))
> [rcca]  0.080 / 0.011 |          88 % |     89 % |             48 % |       83 %   (quantile 5 % (sensibilité))
> [rcca] ⚠️ une personne, une séance : ces chiffres ne valent que pour CE fichier.
> ```
>
> Nouvelle fonction `core.cvep_rcca.point_de_fonctionnement(oof_scores, oof_y, corr_min, margin)`
> — elle **décrit**, elle ne choisit pas : `corrects_gardes`, `emission`, `justesse_si_emis`, `n`,
> `n_corrects`. C'est elle qui a rendu l'erreur visible, et son test exige que les trois proportions
> soient calculées séparément. `seuils_hors_pli` reste livrée et testée : elle chiffre la borne
> basse (le plus bas qu'on puisse descendre sans perdre de bons essais), et sa docstring dit
> maintenant que ce n'est PAS elle qui a fixé les seuils livrés.
>
> Quatre mutations neuves sur `point_de_fonctionnement`, toutes rouges puis remises au vert : N1
> (« corrects gardés » compté sur tous les essais), N2 (« justesse » comptée sur tous les essais),
> N3 (la marge comparée au gagnant au lieu de l'écart), N4 (`>` au lieu de `>=`, donc en désaccord
> avec `RCCADecoder.classify`). ⚠️ N3 **ne rougissait pas** dans la première fixture : deux essais
> `[0.50, 0.45]` ont été ajoutés — gagnant très au-dessus de `corr_min`, écart en dessous de
> `margin`, donc seule la marge peut les refuser.
>
> Le reste de ce rapport décrit la première livraison. Tout y reste vrai **sauf** les valeurs
> livrées : partout où on lit « 0,080 / 0,011 livré », lire « mesuré, et écarté au profit de
> 0,26 / 0,09 ».

> ## ⚠️ TOUR DE CORRECTION 1 — seuils re-mesurés à k=2 : **0,24 / 0,08**
>
> **Commit `0398913`.** Cinq constatations traitées.
>
> ### Important 1 — la géométrie était fausse
>
> Les 71 % / 27 % / 10 % du tour précédent étaient mesurés à **1 cycle par décision**, alors que le
> mode décidera à `CVEP_DECISION_CYCLES = 2`. Re-mesuré à k=2, et **c'est un couple différent qui
> tient le point de fonctionnement visé** :
>
> | seuils | déc. | corrects gardés | émission | justesse si émis | bruit passé |
> |---|---|---|---|---|---|
> | **0,240 / 0,080** | **rCCA** | **38 %** | **35 %** | **69 %** | **10 %** |
> | 0,240 / 0,080 | eCCA | 64 % | 51 % | 74 % | 16 % |
> | 0,260 / 0,090 | rCCA | 29 % | 30 % | 64 % | 7 % |
> | 0,260 / 0,090 | eCCA | 55 % | 46 % | 71 % | 10 % |
> | 0,113 / 0,005 (q05) | rCCA | 83 % | 86 % | 62 % | 69 % |
>
> **Seuils retenus : `CVEP_RCCA_CORR_MIN = 0.24`, `CVEP_RCCA_MARGIN = 0.08`** — à budget de bruit
> égal (~10 %), ils émettent sur 35 % des décisions contre 30 %, donc plus de décisions utilisables.
> ⚠️ **L'écart de justesse (69 % contre 64 %) porte sur 2 décisions sur 37 : il n'est pas
> interprétable.** Ce qui tranche est le taux de bruit, estimé lui sur 300 fenêtres. Écrit tel quel
> dans `config.py`. À k=2 il reste 37 décisions (24 correctes) sur 90 cycles : les groupes à cheval
> sur un changement de cible sont écartés, pas rognés.
>
> `--seuils` affiche maintenant **les deux géométries × les deux décodeurs × trois couples**.
> Corrigé au passage (Minor 3) : `RCCADecoder(n_cycles=CVEP_DECISION_CYCLES)`, aligné sur
> `CVEPDecoder`, avec le commentaire qui dit pourquoi — c'était le vecteur concret du problème.
>
> ### Important 2 — la moitié eCCA est maintenant reproductible
>
> `CVEPModel.hors_pli(epochs, lags, n_cycles)` (nouveau, `core/cvep_decoder.py`) et son jumeau
> `RCCAModel.hors_pli` : mêmes époques, même validation croisée, même géométrie, même affichage.
> Le **43/90 eCCA** qui porte tout l'argument sort désormais d'une commande du dépôt. La formulation
> prudente est conservée : « indiscernables » = absence de preuve de différence, pas preuve
> d'égalité — et à k=2 le rCCA passe même devant (24/37 contre 22/37), écart de 2 décisions dont je
> ne tire rien.
>
> Refactor associé : `RCCAModel._hors_pli` est **la seule boucle de ré-ajustement du fichier** ;
> `_loo` (k=1, pour `fit`) et `hors_pli` (k quelconque) l'appellent toutes deux. Assertion neuve :
> `hors_pli(k=1)` rend exactement `oof_scores_` — deux géométries ne peuvent pas diverger en silence.
>
> ### Minor 4 — `d["decoder"]` sans garde : corrigé
>
> `str(d["decoder"]) if "decoder" in d.files else None`. Mutation P7 (`save` cesse d'écrire le
> champ) : rouge nommé au lieu d'un `KeyError`.
>
> ### Minor 7 — le test qui écrivait dans le vrai `data/` : corrigé
>
> `research/cvep_rcca.py::_demo` écrit maintenant dans un dossier temporaire, nettoyé dans un
> `finally`. **Et la preuve de lecture seule a changé de méthode** : `git status --porcelain data/`
> ne prouvait rien (`data/` est entièrement gitignoré). Désormais : horodatage + taille des
> **43 fichiers** de `data/` relevés avant et après la suite complète → identiques.
>
> ### Minor 10 — `allow_pickle` : VERDICT, il part
>
> Mesuré : les trois fichiers réels (`cvep_model.npz`, `cvep_rcca_model.npz`,
> `cvep_calib_last.npz`) se relisent **tous sans le drapeau**. Il n'apportait rien et il coûtait —
> `np.load(..., allow_pickle=True)` dépickle au premier accès, donc exécute du code contenu dans le
> fichier, et `charger` est justement la fonction qui ouvre tout ce qui traîne dans `data/`. Retiré
> de `cvep_models.charger`, de `RCCAModel.load` et de l'autotest. Test neuf : un `.npz` à tableau
> d'objets est refusé (« modèle illisible ») et n'entre pas dans la liste.
>
> ⚠️ Honnêteté sur la portée de ce test : il y a **deux** `np.load` sur le chemin, et remettre le
> drapeau sur **un seul** laisse le test vert — l'autre refuse encore. Défense en profondeur, pas
> trou : la mutation des **deux** rougit 3 assertions (le fichier devient accepté et listé). Écrit
> dans le commentaire de la fixture.
>
> ### Preuves rouge-puis-vert de ce tour (9 mutations, toutes retirées ensuite)
>
> | # | mutation | muté | assertion rouge |
> |---|---|---|---|
> | P1 | `groupes_de_cycles` rogne la frontière au lieu de l'écarter | exit=1, 2 rouges | `un groupe à cheval… est ÉCARTÉ` |
> | P2 | `groupes_de_cycles` ignore k | exit=1, 3 rouges | idem + le compte de décisions |
> | P3 | `CVEPModel.hors_pli` laisse fuiter le pli | exit=1, 1 rouge | `sur du BRUIT PUR… (91.7 % pour 16.7 %)` |
> | P4 | `RCCAModel._hors_pli` laisse fuiter le groupe | exit=1, 1 rouge | `sur du BRUIT PUR… (75.0 % pour 16.7 %)` |
> | P5bis | les **deux** `np.load` repassent à `allow_pickle=True` | exit=1, 3 rouges | `un .npz qui contient du PICKLE est refusé` |
> | P6 | `RCCADecoder` redevient `n_cycles=1` | exit=1, 1 rouge | `les deux décodeurs décident sur le MÊME nombre de cycles` |
> | P7 | `save` cesse d'écrire `decoder` | exit=1, 1 rouge | `le fichier DÉCLARE son décodeur (None)` |
>
> ⚠️ **Deux mutations ne rougissaient pas au premier jet, et les tests ont été renforcés** : P4
> (le jeu synthétique décodait à 100 % avec ou sans fuite → test de fuite sur du **bruit pur**
> ajouté, jumeau de celui de l'eCCA) et P5 (fixture visant `w`, refusée par `CVEPModel.load` et non
> par `charger` → fixture déplacée sur `codes`, la seule clé que `charger` lit elle-même).
>
> **La méthode de détection de fuite mérite d'être retenue** : donner du bruit pur étiqueté au
> hasard à une validation croisée. La seule justesse honnête est le hasard (16,7 %) ; une fuite
> d'un douzième d'époque fait décoder ce même bruit à **91,7 % (eCCA) / 75 % (rCCA)**.

---

## Ce qui a été livré

| fichier | quoi |
|---|---|
| `src/core/cvep_rcca.py` | **créé** — `RCCAModel`, `RCCADecoder`, `seuils_hors_pli`, `--seuils` |
| `src/core/cvep_models.py` | **créé** — `charger`, `modeles_disponibles`, `decrire` |
| `src/core/cvep_decoder.py` | modifié — `CVEPModel.decoder = "eCCA"`, champ `decoder` dans `save` |
| `src/research/cvep_rcca.py` | réduit aux codes Gold (191 lignes retirées), ré-exporte le décodeur |
| `requirements.txt` | `pyntbci>=1.9` avec sa raison |
| `src/core/config.py` | les deux seuils rCCA, leur provenance et leurs limites |

---

## Étape 1-2 — le test d'abord, la preuve qu'il échoue

Le snippet du brief recopié dans `_selftest()` de `src/core/cvep_models.py`. Avant toute
implémentation :

```
$ python src/core/cvep_models.py
python.exe: can't open file '...\src\core\cvep_models.py': [Errno 2] No such file or directory
EXIT=2
$ python src/core/cvep_rcca.py
python.exe: can't open file '...\src\core\cvep_rcca.py': [Errno 2] No such file or directory
EXIT=2
```

**Une addition au snippet.** Ses trois `chk` lisent `charger(...)[0].decoder`. Une `charger` cassée
rend `(None, raison)` et le test mourait alors sur
`AttributeError: 'NoneType' object has no attribute 'decoder'` — un rouge, mais muet (mesuré :
c'est exactement ce qu'a produit la mutation M1 dans sa première forme). Remplacé par
`getattr(charger(chemin)[0], "decoder", None)`, qui donne un ÉCHEC nommé. Et une quatrième
assertion, que le snippet n'avait pas : le champ `decoder` est un attribut de CLASSE, donc une
`charger` qui rendrait toujours un `CVEPModel` en recopiant le champ du fichier passerait les trois
premières. On vérifie donc aussi `isinstance` — c'est la classe que le moteur va appeler.

## Étape 3 — le découpage

`RCCAModel` et `RCCADecoder` sont dans `src/core/cvep_rcca.py`. `make_distinct_codes`,
`build_targets_rcca` et `calibrate_rcca` restent dans `src/research/cvep_rcca.py`, dont la
docstring dit maintenant pourquoi : **une hypothèse réfutée se garde lisible, pas branchée.**

`calibrate_rcca` reste en `research/` alors que le brief ne la nomme pas : elle est appelée par
`research/app.py` (`calib_cvep_rcca`, et le smoke), et elle part dans `archive/` à la tâche 6. Les
deux classes déménagées sont **ré-exportées** depuis `research/cvep_rcca.py`
(`from core.cvep_rcca import RCCADecoder, RCCAModel`), pour ne pas toucher `research/app.py` — un
fichier que la tâche 6 va de toute façon réécrire. `python src/research/app.py --smoke` reste vert.

## Étape 4 — `pyntbci` déclaré

```
$ python -c "import pyntbci; print(pyntbci.__version__)"   ->  1.9.0
$ pip freeze | grep pyntbci                                ->  pyntbci==1.9.0
```
Épinglé `pyntbci>=1.9` dans `requirements.txt`, avec la raison exigée par le brief.

---

## Étape 5 — LES SEUILS : la mesure, les chiffres, et ce qu'ils valent

### La commande, versionnée, qui les reproduit

`errp_models.py` porte encore le regret que ses seuils aient été posés par un script jetable non
versionné, impossible à refaire. On ne recommence pas :

```
$ python src/core/cvep_rcca.py --seuils data/cvep_calib_last.npz
[rcca] cvep_calib_last.npz : 90 époques, 6 cibles, voies [4, 5, 6, 7]
[rcca] leave-one-out : 47.8 %  (43/90, hasard 16.7 %)
[rcca] seuils sur 43 essais corrects : CVEP_RCCA_CORR_MIN = 0.080  CVEP_RCCA_MARGIN = 0.011
```

⚠️ **LECTURE SEULE.** Vérifié après chaque exécution : `git status --porcelain data/` reste vide.

### Provenance

- fichier `data/cvep_calib_last.npz` — séance du **2026-07-21**, **une** personne, **6 cibles**,
  **90 cycles** (15 par cible, parfaitement équilibré), stimulus **décalé**, voies `[4,5,6,7]`
  = Pz/PO7/Oz/PO8, fs 250 Hz, refresh 60 Hz.
- procédure : `RCCAModel.fit(..., compute_cv=True)` → LOO à 90 plis → scores **hors-pli**
  (le modèle qui note un essai ne l'a jamais vu) → quantile 5 % sur les **43 essais que la
  validation croisée classe correctement**.

### Les chiffres

| | rCCA (stimulus décalé) | eCCA (mêmes époques) |
|---|---|---|
| leave-one-out | **43/90 = 47,8 %** | **43/90 = 47,8 %** |
| significativité | p = 0,0005 (permutation, 2000 tirages) | — |
| gagnant, essais corrects : médiane / q05 | 0,262 / **0,080** | 0,296 / 0,158 |
| écart 1er-2e, corrects : médiane / q05 | 0,114 / **0,011** | 0,158 / 0,038 |

**Les seuils retenus : `CVEP_RCCA_CORR_MIN = 0.080`, `CVEP_RCCA_MARGIN = 0.011`, sur 43 essais
corrects parmi 90.**

Contre-mesure à la géométrie de décision du moteur (`CVEP_DECISION_CYCLES = 2`, en appariant les
cycles consécutifs d'une même cible — 37 paires) : rCCA 24/37 = 64,9 %, eCCA 22/37 = 59,5 %
(différence non significative), q05 = 0,113 / 0,005. **Même ordre de grandeur qu'à 1 cycle** :
le choix de géométrie ne change pas la conclusion, donc on garde la mesure directe du brief, qui
utilise les 90 époques au lieu de 37 paires reconstruites.

### ⚠️ Ce que ces seuils NE font PAS — mesuré, pas supposé

| seuils appliqués | corrects gardés | émis | justesse si émis | bruit pur passé |
|---|---|---|---|---|
| rCCA 0,080 / 0,011 (**livré**) | 88 % | 89 % | **48 %** | **83 %** |
| rCCA 0,26 / 0,09 (le point de l'eCCA) | 40 % | 27 % | 71 % | 10 % |
| eCCA 0,26 / 0,09 (**livré**, sur ses scores) | 63 % | 40 % | 75 % | 10 % |
| eCCA 0,158 / 0,038 (procédure du brief) | 86 % | 71 % | 58 % | 47 % |

« bruit pur » = 300 fenêtres de bruit blanc de même σ que les époques filtrées — le geste que
`cvep_decoder._demo` utilise déjà pour « regard nulle part ».

Trois choses en sortent, toutes écrites dans `core/config.py` à côté des constantes :

1. **Le plancher livré ne discrimine pas.** 48 % de justesse quand il émet, contre 47,8 % sans
   aucun seuil. Les distributions correct/faux se recouvrent presque entièrement (0,262 contre
   0,215 en médiane). Ce qui protège contre « personne ne fixe » est le vote glissant, pas lui.
2. **La procédure du brief n'est pas celle qui a produit les seuils eCCA.** Appliquée à l'eCCA elle
   aurait donné 0,158/0,038 ; l'eCCA livre 0,26/0,09. L'eCCA a été réglé « rejeter le bruit »,
   le rCCA est réglé ici « ne rien rater de bon ». Les deux décodeurs ne sont donc pas au même
   point de fonctionnement — un lecteur qui compare leurs sorties doit le savoir.
3. **L'ancien commentaire était faux et est corrigé.** « scores rCCA sur une autre échelle » :
   non — 0,262 contre 0,296 en médiane, c'est la même échelle. La différence est de critère.

Ce qui trancherait vraiment : **un enregistrement casque de « la personne ne fixe rien »**. Il
n'existe pas dans `data/`, et aucune calibration ne le produit. Tant qu'il n'existe pas, le
plancher posé est ce que les données réelles permettent d'affirmer sous la procédure choisie.

---

## Ce que la mesure a trouvé d'autre

### 1. Le rCCA n'était pas réfuté — un défaut de SIGNE l'était

`RCCAModel.scores` recalait la fenêtre sur la phase avec `np.roll(avg, -shift(phase))`. Le bon
signe est `+`. **Mesuré**, 21 fenêtres à des phases réparties sur le cycle :

```
roll -shift (code hérité)    : 2/21
roll +shift                  : 21/21
```

Pourquoi personne ne l'avait vu : (a) la calibration n'époque qu'à la **phase 0**, donc `cv_`
restait juste — le 35,6 % des codes Gold n'est pas remis en cause ; (b) le seul test du fichier
d'origine **imprimait** le résultat de la phase glissante sans jamais l'affirmer (« recalage OK si
≈ tout ») ; (c) sa ligne de fabrication de fenêtre portait **la même erreur de signe**, si bien que
les deux s'annulaient — et seulement là. Le **pilotage en ligne**
(`research/app.py::_cvep_decode`) note à des phases quelconques, avec la convention de l'eCCA :
la variante rCCA a donc été jugée **en séance** à travers un alignement retourné.

Corrigé dans `core/cvep_rcca.py`, et la ligne de `research/cvep_rcca.py::_demo` remise à la même
convention (elle affiche maintenant 7/7 au lieu de 2/7). Une assertion neuve, dans `core`, pin la
convention à celle de l'eCCA — **le décodeur validé au casque** — plutôt qu'à une convention
maison : les deux décodeurs doivent désigner la même cible sur la même fenêtre à la même phase
(9/9). Sans elle, deux conventions opposées se seraient de nouveau annulées.

### 2. `data/cvep_rcca_model.npz` ne doit jamais apparaître dans la liste

C'est le seul modèle rCCA existant, et il est calibré sur les **codes Gold**. Même `code_len` (63),
même nombre de cibles, mêmes clés : **rien dans le mode ne peut le distinguer**. Sans garde, il
réapparaît dans le formulaire de la console dès que `cvep_models` liste les deux familles de noms,
et le moteur décode un stimulus que plus aucun émetteur n'affiche.

`charger` refuse donc tout modèle rCCA dont les `codes` ne sont pas **exactement**, ligne par ligne
et dans l'ordre, ceux que `build_targets()` affiche aujourd'hui. Le refus est posé **avant** `load`
(qui ré-ajusterait pyntbci pour rien), et il vit **dans `cvep_models` et pas dans le mode**, pour
que le fichier ne soit jamais *proposé* — un refus au démarrage du mode l'aurait laissé dans la
liste.

### 3. Décisions signalées, à valider

**La garde `code_len` du mode reste dans `core/modes/cvep.py`.** Le brief autorisait à la déplacer
ici. Trois raisons de ne pas le faire, écrites dans la docstring de `cvep_models` : (a) un modèle
eCCA calibré sous un autre `CVEP_BITS` est un fichier **valide**, seulement en désaccord avec la
config du jour — le refuser le ferait *disparaître* de la liste sans jamais dire qu'il suffit de
restaurer `CVEP_BITS`, alors que le mode nomme les deux longueurs ; (b) `errp_models` documente
explicitement que son contrôle de géométrie jumeau (`_desaccord_geometrie`) vit dans le **mode** ;
(c) le test de non-régression `python src/core/modes/cvep.py` le couvre déjà. L'asymétrie avec le
refus rCCA n° 2 ci-dessus est assumée et écrite : un modèle rCCA **porte** son stimulus, un eCCA ne
porte qu'un `code_len`.

**`core/modes/cvep.py` n'a PAS été recâblé sur `cvep_models`.** Il porte encore ses `_charger` /
`_modeles_disponibles` provisoires. Ni le brief de la tâche 3 ni celui de la tâche 4 ne listent ce
fichier ; l'instruction reçue était de le garder vert en non-régression. ⚠️ **À faire à la tâche 4**,
avec le piège : son `_modele_temporaire` repointe la **constante module** `CVEP_MODEL_PATH`. Un
`_modeles_disponibles()` qui appellerait `cvep_models.modeles_disponibles(DATA_DIR)` ferait lire le
**vrai** `data/` au test. Le recâblage sans douleur est
`cvep_models.modeles_disponibles(_os.path.dirname(CVEP_MODEL_PATH))` : la fixture existante
redirige alors le scan vers son dossier temporaire, sans une ligne de test à changer.

**Trois divergences assumées avec les jumeaux `errp_models`/`p300_models`/`mi_models`**, toutes
écrites en tête de `cvep_models.py` : pas de refus « module hérité » (le `np.savez` de tableaux purs
ne grave aucun nom de classe — c'est mesuré par `cvep_decoder._selftest`) ; un refus de **stimulus**
que les autres n'ont pas ; `decrire` rend `cv_loo` et non `cv_auc` (une justesse à 6 cibles n'est
pas une AUC — `mi_models` diverge déjà pareillement avec `cv_groupee`). Quatrième point : le brief
annonçait `modeles_disponibles() -> tuple[str]`, on rend une **liste**, comme les trois jumeaux,
dont `errp_models` explique pourquoi (`Param.choices_status` applique `tuple(...)` de toute façon).

---

## Étape 6 — les tests

```
python src/core/cvep_models.py       exit=0  rouges=0
python src/core/cvep_rcca.py         exit=0  rouges=0
python src/core/cvep_decoder.py      exit=0  rouges=0
python src/core/cvep_code.py         exit=0  rouges=0
python src/core/modes/cvep.py        exit=0  rouges=0     (non-régression tâche 2)
python src/research/cvep_rcca.py     exit=0  rouges=0
python src/core/config.py            exit=0  rouges=0
python src/core/server.py --smoke    exit=0  rouges=0     (frontière core/ verte)
python src/console/app.py --smoke    exit=0  rouges=0
python src/research/app.py --smoke   exit=0  rouges=0
git status --porcelain data/         (vide)
```

Codes de sortie relevés **hors pipe** (`cmd > fichier; echo $?`), pas derrière un `| grep`.

## Analyse de mutation — 20 mutations, chacune appliquée puis retirée

Chaque ligne : la mutation d'UNE ligne de production, le nombre d'assertions rouges, et le retour
au vert après retrait. 18 rougissent, 2 sont **équivalentes** et c'est expliqué.

| # | mutation | muté | assertion rouge (extrait) |
|---|---|---|---|
| M1 | `charger` ignore le champ `decoder` du fichier | exit=1, 9 rouges | `un modèle rCCA aussi… (None)` |
| M2 | le refus de stimulus (codes Gold) est supprimé | exit=1, 5 rouges | `un modèle rCCA calibré sur d'AUTRES codes est refusé… (None)` |
| M3 | les codes comparés en **ensemble**, pas ligne à ligne | exit=1, 2 rouges | `…les MÊMES codes dans un autre ORDRE sont refusés aussi` |
| M4 | `MOTIFS` élargi à `("*.npz",)` | exit=1, 1 rouge | `un dossier sans AUCUN modèle utilisable rend []` |
| M5 | tri alphabétique au lieu de `getmtime` | exit=1, 1 rouge | `du plus récent au plus ancien` |
| M6 | le filtre « se charge vraiment » retiré | exit=1, 5 rouges | `…et tout ce qui est listé se charge réellement` |
| M7 | contrôle des clés requises retiré | exit=1, 1 rouge | `…refusé POUR CE QU'IL EST (modèle illisible (KeyError))` |
| M8 | décodeur inconnu → retombe **silencieusement** sur l'eCCA | exit=1, 2 rouges | `un décodeur déclaré inconnu est refusé EN LE NOMMANT (None)` |
| M9 | **le recalage de phase repart dans l'autre sens** | exit=1, 2 rouges | `HORS bord de cycle… (2/9)` + `les DEUX décodeurs… (1/9)` |
| M10 | quantile à 95 % au lieu de 5 % | exit=1, 3 rouges | `corr_min = le quantile… (0.699 vs 0.511)` |
| M11 | seuils sur TOUS les essais, pas les corrects | exit=1, 3 rouges | `seuls les essais CORRECTS… (24/24)` |
| M12 | plancher d'essais supprimé | exit=1, 1 rouge | `sous le plancher, AUCUN seuil n'est rendu (0.504, …, 10)` |
| M13 | la CV ne garde plus ses scores hors-pli | exit=1, 2 rouges | `…garde ses scores HORS-PLI (None)` |
| M14 | le fichier rCCA déclare « eCCA » | exit=1, 1 rouge | `le fichier DÉCLARE son décodeur (eCCA)` |
| M15c | stimulus décalé de 3 crans (533 ms > enc 300 ms) | exit=1, 6 rouges | `leave-one-out 44 %` |
| M15e | stimulus lu à l'envers (codes miroir) | exit=1, 6 rouges | `leave-one-out 54 %` |
| M16 | `CVEPModel` se déclare « rCCA » | exit=1, 5 rouges | `un modèle eCCA se déclare comme tel (None)` |
| M17 | `_fold` moyenne les **premiers** cycles | exit=1, 3 rouges | `un repli d'un cycle rend EXACTEMENT le dernier cycle` |
| M18 | `_fold` ignore `n_cycles` | exit=1, 2 rouges | `un repli de deux cycles rend la moyenne des DEUX derniers` |

Toutes ont été **retirées** et le test relancé : `remis : exit=0 (0 rouge)` à chaque fois.

### Les deux mutations ÉQUIVALENTES, et pourquoi elles le sont

- **M15b** (`self.codes[:, frame]` → `np.roll(self.codes, 1, axis=0)[:, frame]`, décaler d'UN cran
  quel code va à quelle classe) et **M15d** (`.astype(int)` → `np.round(...)`, décalage d'une
  fraction de frame) : **vertes**, et ce n'est pas un trou de test. Nos codes sont des décalages
  circulaires d'une même m-séquence, les lags voisins sont espacés de 10-11 frames (~175 ms), et
  `CVEP_RCCA_ENC = 0,30 s` (18 frames) : le rCCA **absorbe** ces décalages en apprenant un
  transitoire retardé, exactement comme le template eCCA absorbe la latence Bluetooth du casque.
  Au-delà de la fenêtre de transitoire, ça cesse : M15c (3 crans = 533 ms) rougit franchement.
  L'endroit où un tel décalage n'est PAS absorbé est l'appariement `plan[i]` ↔ `codes[i]`, et il
  est couvert (M3, plus l'assertion « le score le plus haut porte SON nom »).

### Deux trous trouvés PAR l'analyse de mutation, puis bouchés

- M17/M18 (`_fold`) passaient au vert dans la première version : **aucune assertion n'utilisait une
  fenêtre de plus d'un cycle**, alors que le moteur passera `CVEP_DECISION_CYCLES = 2`. Trois
  assertions ajoutées (fenêtre de 3 cycles dont le premier est un leurre + égalité exacte du repli).
- M1 mourait sur un `AttributeError` au lieu d'un ÉCHEC nommé — corrigé (cf. étape 1).

---

## Doutes

1. ~~**Le seuil livré ne filtre presque rien, et je l'ai posé quand même.**~~ **TRANCHÉ** par le
   coordinateur : 0,26 / 0,09 sont livrés, la procédure du quantile est écartée comme critère de
   sensibilité mal employé, et le raisonnement complet (asymétrie panne visible / panne invisible)
   est écrit dans `core/config.py`. Voir l'encadré de correction en tête de ce rapport.
2. **Une personne, une séance, 43 essais corrects.** Écrit trois fois (docstring du module, commentaire
   de `config.py`, ici). Le quantile à 5 % de 43 points est porté par une poignée d'essais faibles.
3. **Le rCCA n'a jamais tourné au casque sur le stimulus décalé.** Tout ce qui est affirmé ici est
   du rejeu hors ligne d'époques enregistrées, plus du synthétique. Le défaut de signe corrigé
   (§ 1) n'a jamais été vérifié en séance non plus.
4. **`data/cvep_rcca_model.npz` devient inutilisable** — par décision. Il n'était plus décodable de
   toute façon (son stimulus n'existe plus dans le produit). Aucun fichier de `data/` n'a été
   modifié ni supprimé.
5. **Le fichier `docs/superpowers/plans/2026-08-20-cvep-moteur.md` était déjà modifié** dans le
   dépôt à mon arrivée (l'amendement de la tâche 7 sur `affecte_decodage`). Ce n'est pas mon
   travail et je ne l'ai **pas** inclus dans le commit.
