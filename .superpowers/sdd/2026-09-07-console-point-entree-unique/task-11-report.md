# Tâche 11 — rapport : la documentation

**Statut : terminé.** Cinq fichiers réécrits, aucun fichier de code touché.
`CLAUDE.md` · `docs/markers.md` · `docs/recette.md` · `README.md` · `docs/SPEC.md`.

⚠️ **La section 6 liste tout ce que je n'ai PAS pu vérifier.** Lire celle-là si vous n'en lisez
qu'une : elle contient trois affirmations de comportement que seule une séance tranchera, et quatre
défauts de prose PÉRIMÉE dans `src/` que le brief m'interdisait de corriger.

---

## 1. Ce qui a été réécrit, et sur quelle source

Le code, jamais la spec ni le plan. Les trois divergences annoncées par le brief se sont confirmées
à la lecture, et c'est le code qui a réglé chacune :

| Point | Ce que dit la spec/le plan | Ce que dit le CODE — retenu |
|---|---|---|
| `src/stimulus/` | absent | quatrième paquet, `p300.py` · `errp.py` · `cvep.py` · `registry.py`, frontière scannée par `server.py --smoke` |
| calibrations pygame | « réduites » | **archivées** (`archive/`, six écrans, dix au total), `src/research/app.py` **supprimée** |
| compression `tanh` | prescrite | **absente du code** — jamais documentée |
| `Calib.kind` | « console » / « natif » | `"moteur"` / `"fenetre"`, et le contrat **lève** sur l'ancien vocabulaire (`modes/contract.py:607`) |

Sources croisées, dans cet ordre : le code (`contract.py`, `marker_calib.py`, `registry.py` des deux
paquets, les trois `stimulus/*.py`, `console/{app,mode_page,contact_page,fenetres,calib_page}.py`),
puis `progress.md` et les rapports 6, 8 et 10 pour les *raisons*, puis `git log 010222d..HEAD`.

### CLAUDE.md — le fichier qui compte

- **Trois paquets → quatre**, avec le tableau des quatre arêtes. ⚠️ **Précision que le brief
  formulait trop largement** : le scanner AST ne vérifie que les **deux interdits** (`core`
  n'importe rien du dépôt ; `stimulus` n'importe ni `research` ni `console`). « `console` importe
  `core` et `stimulus` » et son jumeau `research` sont des **permissions** — il n'y a rien à y
  vérifier, et le dire autrement aurait promis une garantie qui n'existe pas. C'est écrit comme tel.
- **Section « Commandes utiles » entièrement refaite** : `outils\Console EEG.bat` en tête, plus de
  `src/research/app.py`, plus de `src/research/*_stimulus.py`, les quatre calibrations devenues des
  boutons (avec les trois `--calibrer` gardés pour le débogage).
- **Deux smokes au lieu de trois**, et la disparition du troisième est DITE plutôt que silencieuse.
- Liste des autotests : `+ marker_calib.py`, `+ p300_calib.py`, `+ errp_calib.py`, `+ cvep_calib.py`,
  `+ errp_track.py`, `+ stimulus/registry.py`, `+ les trois stimulus/*.py --smoke`. Les chemins
  `research/*_stimulus.py` deviennent `stimulus/*.py`.
- **Section neuve « Ce qui n'a jamais été vérifié »**, qui porte la phrase négative et les deux
  réserves ouvertes. Voir §3.

### docs/markers.md (anglais — contrat public)

Section neuve **« Training a model through the markers »**, placée après « Before any of this works:
a trained model », qui contient :

- les **trois événements** avec leur charge utile réelle, relevée dans les fenêtres :
  `calib_start` (+`trials`), `cue` (+`target`), `calib_end` ;
- le **cas ErrP** : pas de `cue`, l'étiquette voyage sur `feedback` avec `error: true|false`
  **en calibration seulement**, plus la règle « l'étiquette suit l'EFFET du pas, pas le tirage » ;
- le **cas c-VEP** : `block_end`, l'horloge qui continue de battre, et l'ordre au bord d'un cycle
  (`cycle` → `block_end` → `cue`) ;
- un tableau **par mode** : qui annonce, qui étiquette, où l'époque est coupée, qui ferme ;
- les **trois abandons** (30 s sans `calib_start` · 15 s de silence · « Abandonner ») et le cas gelé
  (tous les essais reçus, `calib_end` perdu → attente) ;
- **la conséquence pour une application tierce**, avec ses quatre exigences — et la phrase qui la
  résume : *« The epochs never travel »*.

Deux corrections de chemin au passage (`research/{p300,cvep}_stimulus.py` → `stimulus/`), et la
section « a trained model » qui prescrivait `python src/research/app.py` décrit maintenant le bouton.

### docs/recette.md

- **1.2** : le bouton « Calibrer » n'est plus « MI seulement » mais **les quatre modes à modèle**,
  et le critère est nommé (`calibration.jouable`, pas `kind`) — avec le rappel du défaut de la
  tâche 6, qui l'avait fait disparaître de tous les modes sans qu'un test le voie.
- **1.14 / 1.15 / 1.16** : trois terminaux → **deux**, la fenêtre étant lancée par la console. Le
  montage historique est **conservé à côté**, parce que c'est celui qu'une application tierce
  reproduit. Les points qui exigent une option (`--no-wait`, `--refresh 75`, `--seed`, `--log`) sont
  marqués « à lancer à la main » : **le bouton ne passe aucune option**, et l'ignorer ferait chercher
  un bug qui n'existe pas.
- **2.6 / 2.7 / 2.8 / 2.9** : la calibration devient un bouton dans chacun ; le contrôle de liaison,
  le couple « Enregistrer / Refaire » et le refus mode↔calibration deviennent des points cochables.
- ⚠️ **Aucun repère chiffré n'a bougé**, et c'est mesuré, pas affirmé. Voir §5.

### README.md et docs/SPEC.md

- README : la console passe **en tête** de « Run » ; sections neuves « The stimulus windows » et
  « The pygame app is gone » ; `Layout` passe de deux paquets à quatre, avec le bloc des arêtes ; la
  table des modes dit « from the console » pour les quatre calibrations ; la liste des autotests
  suit les chemins.
- SPEC : **§3.1** gagne le quatrième paquet et la règle des quatre arêtes ; **§6.1 neuve** (les
  quatre calibrations jouées par le moteur, l'invariant des deux épochages, `save_calibration`, le
  vol de marqueurs) ; **§7** documente le second renversement (la calibration suit le pilotage) ;
  **§13 F2 est marquée FAITE** — en notant qu'elle a été livrée *autrement que prévu* : l'appli
  n'envoie **pas** d'époques, elle publie trois marqueurs de plus ; **§14** referme les trois
  « [à faire] calibration X jouée par le moteur » et ouvre trois nouvelles entrées (séance casque,
  contrôle de liaison à trancher, poignée de main absente).

---

## 2. Les commandes vérifiées — toutes lancées, toutes vertes

**37 commandes, 37 × `EXIT=0`.** Toutes lancées une par une, jamais en parallèle. Empreinte de
`data/` **identique avant et après** (`core.config.empreinte_dossier`, 43 fichiers,
`sha256 = 42120328…8083d`) : la documentation n'a rien fait écrire sur le disque.

```text
=== EMPREINTE data/ AVANT ===
43 fichiers  sha256= 42120328ed4df50265e14522eb61c5035423bbb52064f33b14d3293dfae8083d
EXIT=0  | python src/core/server.py --smoke
        | [smoke-marqueurs-stream-in] VERDICT : OK
EXIT=0  | python src/console/app.py --smoke
        | [console-smoke] VERDICT : OK
EXIT=0  | python src/core/acquisition.py --synthetic
        | [acq] liaison : Fz=7.1(ok)  C3=20.1(ok)  Cz=30.1(ok)  C4=40.2(ok)  Pz=50.2(ok)  PO7=59.3(ok)  Oz=72.7(ok)  PO8=67.3(ok)
EXIT=0  | python src/core/cca_decoder.py
        | faux positifs (bruit pur)     :   0.0%  (vise ~0%)
EXIT=0  | python src/core/config.py
        | [config] VERDICT : OK
EXIT=0  | python src/core/cvep_code.py
        | [cvep] autotest : OK
EXIT=0  | python src/core/cvep_decoder.py
        | [cvep-decoder] VERDICT : OK
EXIT=0  | python src/core/cvep_models.py
        | [cvep-models] VERDICT : OK
EXIT=0  | python src/core/cvep_rcca.py
        | [cvep-rcca] VERDICT : OK
EXIT=0  | python src/core/errp_decoder.py
        | [errp-gardes] VERDICT : OK
EXIT=0  | python src/core/errp_models.py
        | [errp-models] VERDICT : OK
EXIT=0  | python src/core/errp_track.py
        | [errp-track] VERDICT : OK
EXIT=0  | python src/core/lsl_io.py
        | [lsl] VERDICT : OK
EXIT=0  | python src/core/markers.py
        | [markers] VERDICT : OK
EXIT=0  | python src/core/mi_models.py
        | [mi-models] VERDICT : OK
EXIT=0  | python src/core/modes/calibration.py
        | [calibration] VERDICT : OK
EXIT=0  | python src/core/modes/contract.py
        | [contract] VERDICT : OK
EXIT=0  | python src/core/modes/cvep.py
        | [cvep] VERDICT : OK
EXIT=0  | python src/core/modes/cvep_calib.py
        | [cvep-calib] VERDICT : OK
EXIT=0  | python src/core/modes/errp.py
        | [errp] VERDICT : OK
EXIT=0  | python src/core/modes/errp_calib.py
        | [errp-calib] VERDICT : OK
EXIT=0  | python src/core/modes/marker_calib.py
        | [marker-calib] VERDICT : OK
EXIT=0  | python src/core/modes/mi.py
        | [mi] VERDICT : OK
EXIT=0  | python src/core/modes/mi_calib.py
        | [mi-calib] VERDICT : OK
EXIT=0  | python src/core/modes/p300.py
        | [p300] VERDICT : OK
EXIT=0  | python src/core/modes/p300_calib.py
        | [p300-calib] VERDICT : OK
EXIT=0  | python src/core/modes/registry.py
        | [registry] VERDICT : OK
EXIT=0  | python src/core/modes/ssvep.py
        | [ssvep] VERDICT : OK
EXIT=0  | python src/core/neuro_monitor.py
        | [neuro] auto-test OK
EXIT=0  | python src/core/p300_models.py
        | [p300-models] VERDICT : OK
EXIT=0  | python src/stimulus/cvep.py --smoke
        | [cvep-stim] VERDICT : OK
EXIT=0  | python src/stimulus/errp.py --smoke
        | [errp-stim] VERDICT : OK
EXIT=0  | python src/stimulus/p300.py --smoke
        | [p300-stim] VERDICT : OK
EXIT=0  | python src/stimulus/registry.py
        | [stim-registry] VERDICT : OK
EXIT=0  | python src/research/controller.py
        | [sim] TOUT OK — la sortie suit l’intention.
EXIT=0  | python src/research/itr.py
        | au-delà il faut une autre géométrie (grille ou couronne de cibles).
EXIT=0  | python archive/cvep_pilot.py --smoke
        | [cvep-pilot] smoke OK : calibration + décodage + affichage câblés (headless).
=== options citees : existent-elles ? ===
  OK    src/core/server.py --duration
  OK    src/core/server.py --no-raw
  OK    src/core/server.py --refresh
  OK    src/console/app.py --mode
  OK    src/console/app.py --synthetic
  OK    src/stimulus/cvep.py --log
  OK    src/stimulus/cvep.py --calibrer
  OK    src/stimulus/cvep.py --windowed
  OK    src/stimulus/errp.py --no-wait
  OK    src/stimulus/errp.py --calibrer
  OK    src/stimulus/p300.py --calibrer
  OK    archive/cvep_pilot.py --model
=== EMPREINTE data/ APRES ===
43 fichiers  sha256= 42120328ed4df50265e14522eb61c5035423bbb52064f33b14d3293dfae8083d
=== FIN ===
```

Ce que ce relevé vérifie, au-delà du vert :

- **La ligne « Attendu » du niveau 0 de la recette est exacte** : tous les fichiers de sa liste
  impriment `VERDICT : OK`, **sauf `acquisition.py --synthetic`** qui finit sur ses σ par voie —
  c'est exactement l'exception que le document annonce, et la seule.
- **Les huit lignes que j'ai ajoutées à ce niveau 0 impriment bien `VERDICT : OK`** :
  `[marker-calib]`, `[p300-calib]`, `[errp-calib]`, `[cvep-calib]`, `[errp-track]`,
  `[stim-registry]`, `[p300-stim]`, `[errp-stim]`.
- **`archive/cvep_pilot.py --smoke` passe**, ce qui compte parce que `CLAUDE.md` et la recette 2.9
  l'envoient chercher au casque avec un `--model` explicite.
- **Les douze options citées existent toutes** (contrôlées sur `--help`), y compris les trois
  `--calibrer` et le `--model` de l'écran archivé.

⚠️ **Ce que je n'ai PAS lancé, et pourquoi** : tout ce qui ouvre une fenêtre ou exige le casque —
`src/console/app.py` (hors `--smoke`), `src/core/server.py --mode …`, les trois
`src/stimulus/*.py` hors `--smoke`, `alpha_check.py`, `ssvep_guided.py`, `examples/receiver.py`.
Ce sont les commandes du parcours de séance ; le brief les exclut explicitement.

---

## 3. La phrase négative : où elle vit maintenant

Le brief demandait qu'elle survive « aussi visible qu'avant ». Elle est présente **six fois**, dont
trois dans un emplacement neuf :

| Fichier | Où | Formulation |
|---|---|---|
| `CLAUDE.md` | puce « Le moteur publie les SIX modes » | « Publié ≠ validé … **Le chantier de la console n'y a rien changé** : il déplace le geste de calibration, il ne décode aucun cerveau. » |
| `CLAUDE.md` | **section neuve** « Ce qui n'a jamais été vérifié » | « **Rien de ce que la console fait n'a vu un cerveau.** … QUATRE des six modes … ça n'ajoute aucune mesure » |
| `README.md` | bloc « Status » | « …and moving the calibrations did not change that » |
| `README.md` | sous la table des modes | « "Published" is not "validated", **and "calibrated by the engine" is not either** … measured nothing » |
| `docs/recette.md` | **encadré neuf** en tête | « Il n'a changé **aucun repère chiffré** … **Il n'a mesuré strictement rien** » |
| `docs/recette.md` | « Ce que cette recette ne teste pas » | « **RIEN de la console n'a été vu avec un casque sur la tête** » |
| `docs/SPEC.md` | §6.1, §14 | « Aucune de ces quatre calibrations n'a jamais été jouée au casque par ce chemin » |

Les deux réserves ouvertes sont consignées **là où elles seront lues** :

- **le contrôle de liaison sans porte de sortie** : `CLAUDE.md` (« Ce qui n'a jamais été vérifié »,
  🔴), `docs/recette.md` **2.6** (point cochable, « Note ce qui s'est passé, c'est la seule mesure
  qui puisse arbitrer ») et sa section finale, `docs/SPEC.md` §14, `README.md` (« it has never been
  tried on a real headset ») ;
- **l'ordre de lancement sans poignée de main** : `CLAUDE.md` (🔴 et section « Commandes utiles »),
  `docs/recette.md` **2.7** (point cochable : *regarde le terminal, s'il dit « marqueurs reçus
  pendant la CHAUFFE », la fenêtre a pris de l'avance sur cette machine — note-le*), `docs/SPEC.md`
  §14.

---

## 4. Faits vérifiés dans le code plutôt que recopiés

Chaque chiffre écrit a été retrouvé à sa source. Les cas où j'ai dû corriger ce que j'allais écrire :

| Ce que j'allais écrire | Ce que dit le code | Source |
|---|---|---|
| « le bouton Calibrer n'existe que si `kind == "fenetre"` » | le critère est **`jouable`** (`runtime_cls is not None`) ; `stimulus_id` décide du **second** bouton | `console/mode_page.py:50-76` |
| « le contrôle de liaison porte sur les voies clés » | il porte sur **les huit**, les voies clés sont seulement surlignées | `console/contact_page.py:154,185` |
| « voies clés du MI : C3/C4 » | **C3, Cz, C4** (`key_channels = (1, 2, 3)`) | `modes/mi.py` |
| « la calibration P300 affiche l'AUC » | elle affiche la **sélection en leave-one-round-out** ; l'AUC est en détail | `console/calib_page.py:340-356` |
| « `data/p300_model_AAAAMMJJ-HHMMSS` » | **underscore** pour P300 et ErrP (`%Y%m%d_%H%M%S`), **tiret** pour MI et c-VEP | `modes/{p300,errp,mi,cvep}_calib.py` |
| « le contrôle de liaison s'intercale au clic sur Calibrer » | il s'intercale entre **« Commencer »** et le lancement | `console/app.py:224-239` |
| « une grille des six modes » | **sept tuiles** (les six modes plus le brut) | `modes/registry.py` |
| « `trials` = 12 manches » | `rounds × targets × reps` = **576 époques** | `stimulus/p300.py:450` |

Constantes citées, relues à la source (`core/config.py`) : `SSVEP_WARMUP_S = 15.0`,
`CALIB_FENETRE_ATTENTE_S = 30.0`, `CALIB_FENETRE_SILENCE_S = 15.0`, `CVEP_CAL_CYCLES = 15`,
`CVEP_CAL_SETTLE_CYCLES = 4`, `P300_CAL_ROUNDS = 12`, `ERRP_CAL_TRIALS = 200`,
`SIGNAL_DEAD_SIGMA = 0.5`, `SIGNAL_SAT_SIGMA = 500.0`, `P300_REPS = 8`, `P300_N_TARGETS = 6`.

Le repère « 19,1 / 23,8 bits/min » du README pointait `src/research/cvep_calibrate.py` : le fichier
a déménagé, l'assertion aussi. Le renvoi est corrigé en `archive/cvep_calibrate.py:752`, où elle est
toujours exécutée par `--smoke`.

---

## 5. Ce que je n'ai PAS touché

- **Aucun fichier `.py`.** `git status` : cinq `.md` modifiés, rien d'autre.
- **Aucun repère chiffré.** Mesuré plutôt qu'affirmé : j'ai extrait par expression régulière tous
  les pourcentages, AUC, `p =` et bits/min de chaque fichier **avant** (`git show HEAD:…`) et
  **après**, et comparé les deux multi-ensembles :

  | fichier | repères PERDUS | repères AJOUTÉS |
  |---|---|---|
  | `README.md` | aucun | aucun |
  | `docs/SPEC.md` | aucun | aucun |
  | `docs/markers.md` | aucun | aucun |
  | `CLAUDE.md` | aucun | aucun |
  | `docs/recette.md` | **aucun** | `100 %`, `44 %`, `46 %`, `71 %`, `40 %` |

  Les cinq « ajoutés » sont tous dans **une seule phrase neuve**, l'encadré en tête du document qui
  dit précisément qu'ils n'ont pas bougé : *« Il n'a changé aucun repère chiffré de ce document — ni
  le 100 %/44 % du SSVEP, ni le 46 %/71 % du c-VEP… »*. Aucun n'est une mesure nouvelle ; ce sont
  des citations des repères existants.
- **Aucune mesure réinterprétée.** Les lignes du README et de la SPEC qui portent des chiffres ont
  été modifiées uniquement sur leur colonne « Calibration » (« in the pygame app » → « from the
  console ») et sur leur renvoi de calibration — jamais sur un nombre.
- **`archive/README.md`**, déjà fait à la tâche 10.
- **`docs/network.md`** et `docs/robot_testbed.md` : aucune référence périmée (vérifié par grep).

---

## 6. ⚠️ Ce que je n'ai PAS pu vérifier

### 6.1 Trois affirmations de comportement que seule une séance tranchera

Elles sont écrites dans la doc **avec leur incertitude**, jamais comme des faits :

1. **« La calibration P300 se joue aussi en synthétique »** — je ne l'affirme PAS. La recette 1.14
   dit désormais : *« Ce chemin-là n'a JAMAIS été joué, ni au casque ni en synthétique — seulement
   en autotest. »* L'architecture le permet (le moteur entraîne sur ce que son tampon contient) et
   l'écran archivé le fait, mais je n'ai pas ouvert la console pour le constater : ça demande une
   session interactive de ~4 min.
2. **« Le bouton ne passe aucune option à la fenêtre »** — vérifié dans le CODE
   (`stimulus/registry.commande()` ne prend qu'un booléen `calibrer`), pas à l'écran.
3. **Les durées annoncées** (~4 min P300, ~7 min ErrP, ~2,7 min c-VEP) sont reprises telles quelles
   des constantes et de la doc antérieure. **Aucune n'a été chronométrée par moi.**

### 6.2 🔴 Quatre docstrings de `src/` envoient encore vers un fichier supprimé

Le brief interdit explicitement de corriger du code depuis cette tâche (« dis-le dans ton rapport,
ne corrige pas »). **Aucune n'est exécutable** — ce sont des commentaires et des docstrings, donc
aucun étudiant ne les voit à l'exécution — mais quiconque ouvre le fichier lit une phrase fausse :

| Site | Texte périmé | Ce qu'il faut |
|---|---|---|
| `src/console/app.py:10` | « Ne jamais la lancer en même temps que `src/core/server.py` **ni que `src/research/app.py`** » | remplacer la 2ᵉ moitié par « ni qu'un écran de `archive/` » |
| `src/console/grid.py:9` | « l'attend dans `src/research/app.py` » | le fichier n'existe plus |
| `src/core/server.py:4` | « pygame (`src/research/app.py`), la future console PySide6 … » | la console n'est plus « future », l'appli n'existe plus |
| `src/core/server.py:36` | « ils restent l'affaire de `src/research/app.py` » | ils sont l'affaire de `src/stimulus/` |
| `src/stimulus/cvep.py:7` · `errp.py:7` | « cf. `research/app.py` -> c-VEP / ErrP » (dans l'exemple de lancement à 2 terminaux) | « cf. le bouton « Calibrer » de la console » |

⚠️ Les **quatre messages d'exécution** signalés par le rapport de la tâche 10 (`cvep_models.py:202`,
`modes/cvep.py:283/298/752`), eux, **ont bien été corrigés** par `d96689a` — vérifié : le test
`modes/cvep.py:928` exige maintenant `"research/app.py" not in raison`, comme ses jumeaux P300 et
ErrP. Il ne reste que de la prose.

### 6.3 Ce que la doc affirme sur la foi des rapports, pas de mes propres mesures

- **« `--synthetic` passe le contrôle de liaison »** (CLAUDE.md, « σ mesurés de 7 à 75 µV, huit
  verdicts ok, aucun refus ») : mesure du rapport de la tâche 6. Je l'ai **corroborée
  indirectement** — `acquisition.py --synthetic` sort aujourd'hui `Fz=7.1 … PO8=67.3`, huit `(ok)` —
  mais pas en ouvrant la page de contact sur un vrai `EngineServer`.
- **Les douze preuves par mutation** de la tâche 6 et les deux de la tâche 8 : citées comme
  garanties (« l'ordre est un contrat testé », « la mutation fait rougir deux assertions »), non
  rejouées par moi. Je n'ai lancé aucune mutation.
- **La couverture annoncée des deux smokes** (« vol de marqueurs, save/discard » pour le moteur ;
  « contrôle de liaison, lanceur de fenêtre, ORDRE » pour la console) est lue dans les noms de
  section et le code des `_smoke*`, pas mesurée en couverture.

### 6.4 Une incohérence pré-existante que je n'ai pas corrigée

`docs/recette.md` niveau 0 dit « **✅ Passé le 2026-07-29, les 8 verts** » au-dessus d'une liste qui
en compte quinze. C'est un enregistrement daté (il valait 8 ce jour-là), pas une consigne — le
corriger réécrirait un fait historique. Signalé, non touché.

---

## 7. Commit

```
0724dee Tell the docs the console is the way in, and that nothing was measured

Sept fichiers : les cinq documents, plus `task-11-brief.md` et ce rapport.
Arbre propre, `data/` intact (43 fichiers, `sha256 = 42120328…8083d`, identique au début de session).
```
