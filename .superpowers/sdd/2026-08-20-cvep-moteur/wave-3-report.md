# Vague 3 — la séance au casque exécutable, et les documents vrais

Base `352f3e7` · commit **`1afb501`** · 11 fichiers, +552/−123.
Sources : `final-D-findings.md` (1 Critical) et `final-G-findings.md` (2 Critical).

`data/` : **43 fichiers, horodatages IDENTIQUES avant/après** (`cvep_rcca_model.npz` toujours au
2026-08-21 14:17:45.2835183). Vérifié par empreinte `nom|taille|ticks` prise avant la première
commande et rejouée après la dernière — `git status` ne prouve rien sur un dossier gitignoré.
Aucune calibration réelle lancée.

---

## Traités — les 12 points du lot

| # | Constatation | Fichier(s) | Preuve |
|---|---|---|---|
| 1 | **D-C1 = G-C1** la clé de jointure n'existe nulle part | `cvep_stimulus.py`, `receiver.py`, `recette.md` | ✅ rouge-puis-vert (×2) |
| 2 | **G-C2** l'A-B-A n'a ni protocole ni base de calcul | `recette.md` | ✅ documentaire |
| 3 | ITR : 23,8 rCCA / 19,1 eCCA, verdict FAIBLE | `README.md`, `SPEC.md`, `cvep_calibrate.py` | ✅ assertion resserrée |
| 4 | « calibration ~1 min » × 5 (réel ≈ 2,7 min) | README ×2, `markers.md`, `recette.md` ×2 (+ `cvep_calibrate.py`) | ✅ calculé |
| 5 | « les cinq autres validés dans l'appli » — le neuro ne l'a jamais été | `README.md` | ✅ documentaire |
| 6 | encadré « résultat NORMAL » : mauvais dénominateur | `recette.md` | ✅ documentaire |
| 7 | « les cinq gardes du c-VEP » au-dessus de six | `CLAUDE.md` | ✅ |
| 8 | **D-I1** `cvep_rcca` décrit comme non publié | `research/__init__.py` (+ README, SPEC) | ✅ documentaire |
| 9 | **D-m1** `--seed` promet un rejeu exact | `cvep_stimulus.py` | ✅ |
| 10 | rotation ≠ 0 : « le cas ATTENDU » est faux depuis le lot 2 | `core/cvep_models.py` | ✅ rouge-puis-vert |
| 11 | **C-I2** moitié restante : `pyntbci` absent | `core/cvep_models.py`, `requirements.txt` | ✅ rouge-puis-vert |
| 12 | **E-I3** eCCA se déclare à 6 cibles après une séance à 3 | `cvep_calibrate.py` | ✅ rouge-puis-vert |

### 1 — Le journal, et l'horodatage absolu

`cvep_stimulus.py --log CHEMIN` : **opt-in, sans défaut** (donc `--smoke` ne peut rien écrire et
`data/` reste hors d'atteinte), **JSONL append + flush**. Trois genres de ligne : `header` (graine,
refresh, `code_len`, `n_targets`, cycles par cible, `transition_s`, flux, noms des cibles) ·
`consigne` (`t`, `compter_a_partir_de`, `cible`, `nom`, `cycle`, `frame`) · `bilan`, qui **recopie
verbatim** le dictionnaire de `bilan_de_seance` (`dict(kind="bilan", **resume)` — une seule source).
`t` et `compter_a_partir_de` sont des `local_clock()`, le domaine exact des horodatages de
`decoded_cvep`.

`examples/receiver.py` imprime désormais `[t=… xx.x ms old]` : il calculait déjà `ts + offset` et le
jetait.

**Assertions C6** (7, sur `tempfile`) : une ligne `consigne` par changement de consigne et pas une de
plus · l'horodatage et le nom appariés au journal en mémoire · `compter_a_partir_de = t +
transition` · l'en-tête contient de quoi rejouer · le bilan est **égal** au dict de
`bilan_de_seance` · une **sentinelle** écrite avant l'appel survit (mode `"a"`) · `--log` n'a aucun
défaut.

Preuves rouges :
```
MUTATION  la ligne `consigne` n'est plus écrite
  ÉCHEC [C6] une ligne `consigne` par CHANGEMENT de consigne … (0 lignes pour 3 changements)   exit 1
MUTATION  open(log_path, "w") au lieu de "a"
  ÉCHEC [C6] le fichier est ouvert en AJOUT : la ligne écrite AVANT la séance est toujours là …  exit 1
```

### 2 — Le protocole de B

Ajouté à `recette.md`, sans une ligne de code nouvelle : la liste de fixations **écrite sur papier
d'avance** (6 × 3, ordre mélangé), 10 s par cible, **les 3 premières secondes ignorées**, le panneau
lu **seulement à la fin** de chaque fixation (il donne la réponse et biaise la fixation). La phrase
« même modèle, mêmes cibles, même vote » est complétée par « **mais pas le même protocole** : A est
cerclé et à l'aveugle, B est libre et en boucle fermée ». La **méthode de secours** (compter les
lignes ~1 Hz du terminal 1, jeter les 3 premières après chaque consigne, compter les ~5 suivantes)
est écrite une fois et sert à B. L'A-B-A est exigé **aux seuils par défaut avant tout desserrage**,
avec le pourquoi (l'écran archivé décode toujours à 0,26/0,09 et n'expose aucun réglage).

### 10 / 11 / 12 — les reliquats

- **10** : le paragraphe nomme maintenant **trois causes réelles** (codes Gold · `CVEP_LAG_ROTATION`
  changé · modèle antérieur au 2026-08-21) sans en excuser aucune. ⚠️ Le test **détourne
  `CVEP_LAG_ROTATION` à 2** : à 0 — la valeur du dépôt — la phrase fautive n'apparaissait jamais et
  l'assertion aurait été creuse. Rouge en restaurant l'ancien message conditionnel.
- **11** : `charger` attrape `PyntbciManquant` **avant** le `except Exception` (qui ne garde que
  `type(e).__name__`, d'où « modèle illisible (PyntbciManquant) ») ; `modeles_disponibles` compte les
  retirés et **le dit** au lieu de les faire disparaître. Simulé en détournant `RCCAModel._fit_clf`,
  le seul `import pyntbci` du produit. `requirements.txt` : borne `<2` justifiée (l'appel à
  `pyntbci.classifiers.rCCA` est direct, mesuré en 1.9.0 seulement).
- **12** : `ecca.save(save_path, n_targets=n_cibles_vues)`. Le fichier est **relu par
  `CVEPModel.load`** dans le test — c'est le fichier qui voyage jusqu'au moteur. Rouge en revenant à
  `len(plan)` : `ÉCHEC … se déclare à 3 cibles … (6)`.

---

## Traités EN PLUS — trouvés faux en vérifiant, dans mes fichiers

Le brief impose de vérifier chaque ligne des documents contre le code. Six affirmations fausses de
plus, toutes dans mon périmètre, toutes corrigées :

1. **`recette.md` 1.16, `--refresh 75`** : « il publie -1 sous `sans_reference` ». Faux —
   `sans_reference` n'est incrémenté que si `_ref_ts is None` (`modes/cvep.py:323`), et la puce
   précédente vient de faire tourner l'émetteur à 60 Hz. C'est **`reference_perimee`** qui monte, et
   le compteur qui identifie vraiment ce cas est `marqueurs_refuses`. La table du 2.9 fait lire
   `reference_perimee` comme « relance l'émetteur » — le mauvais geste ici ; c'est dit.
2. **`CLAUDE.md`, `README.md`, `recette.md`** : « il ne reste à l'appli pygame que les calibrations
   et l'histogramme neuro ». Faux — `mode_ssvep`, `mode_p300` et `mode_errp` y sont toujours
   (exercés par son propre smoke). Seuls le c-VEP et le MI y ont perdu leur pilotage.
3. **`recette.md`** : `fixe « DROITE » (cible 2)`. `cvep_targets(6)` nomme `AVANT, AV-DROITE,
   AR-DROITE, ARRIERE, AR-GAUCHE, AV-GAUCHE` : l'indice 2 est **AR-DROITE**, et « DROITE » n'existe
   qu'à 3 cibles. Vérifié à l'exécution (sortie du smoke).
4. **`markers.md`** : `p300_model_20260818-101500.joblib` / `errp_model_20260819-142230.joblib`.
   Le code écrit `%Y%m%d_%H%M%S` (**souligné**) pour le P300 et l'ErrP ; seuls le c-VEP et le MI
   utilisent le tiret. Rétabli.
5. **`recette.md` 3.1** : la sortie attendue de `receiver.py` était `[83.0 ms old] …`. Elle porte
   maintenant `t=` — l'exemple est mis à jour, sinon il ferait conclure à une régression.
6. **`recette.md` 1.16** : « c'est `sous_les_seuils` qui **doit** monter » est trop absolu — une
   fenêtre peut franchir 0,26/0,09 par hasard sur le board synthétique puis tomber en
   `vote_non_conclu`. Devenu « doit **dominer** ».

Corollaires de cohérence : budget du niveau 2 `~90 min` → `~2 h` (calibration 2,7 min + A/B/A′ à
5 min) · durées de l'A-B-A harmonisées (`~3 min` vs `~5 min` dans le même test) · `cvep_rcca.py`
ajouté à l'inventaire `research/` de `README.md` et `SPEC.md` comme **hypothèse réfutée, pas
décodeur**.

**Vérifiées VRAIES** (contrôlées, non modifiées) : `archive/cvep_pilot.py --model` existe et son
défaut pointe bien l'ancien nom fixe · il décode à `CVEP_CORR_MIN`/`CVEP_MIN_VOTES` sans aucun
réglage exposé · le repère 46 %/71 % est bien dans `core/config.py:448` · la durée de calibration
calculée vaut **2,75 min** (6 cibles, 15 cycles, 18 blocs) · l'ITR de référence vaut **19,1 / 23,8**
contre un SSVEP à 25,0, donc verdict FAIBLE.

---

## Reportés, avec motif

- **D-I2** (`chk(etendue > C2_SECONDES)`, 16 % de marge, bande de panne [42 ; 54,8) fps) — hors des
  12 points reçus ; correctif proposé par D (journaliser les marqueurs de chauffe) touche la
  signature de `run()`, déjà élargie par `--log` dans ce lot. **À traiter** : le test est instable,
  pas faux.
- **D-I3** (HUD : `refresh` annoncé étiqueté « fps », `sautees` aveugle au trop-rapide) — hors des
  12 points ; c'est la seule panne muette sans signal live.
- **D-I4** (`ATTENTE_MOTEUR_S` re-dérivé de `SSVEP_WARMUP_S` alors que deux docstrings disent
  « LUE dans SPEC.rest ») — hors des 12 points ; ⚠️ **la docstring reste fausse**.
- **D-M2** (repli sans vsync silencieux), **D-M3** (assertion « pendant » verte à écart 0),
  **D-M4** (transition figée sur `CVEP_VOTE_LEN` alors que `vote_len` est réglable dans la console —
  un opérateur qui le passe à 8 compte 5 échantillons contaminés par consigne), **D-M5** (le `print`
  de consigne tombe dans l'intervalle que `sautees` mesure), **D-M6** (la saccade non comptée dans
  la transition) — hors des 12 points.
- **G-m8** (compaction de `recette.md`) — **délibérément non fait** : ce lot a ajouté du contenu au
  2.9 (le journal, le protocole de B, le repère chiffré) ; compacter en même temps aurait rendu la
  relecture du diff impossible. Le fichier passe de 996 à ~1 070 lignes.
- **E-I2**, **E-I4**, **E-I5**, **E-M2**, **E-M3**, et les mineurs C non assignés — hors périmètre,
  déjà listés par le lot 2.

---

## Suite complète — 25 commandes, 0 échec

Les 21 de `CLAUDE.md`, une à la fois, aucun autre python en parallèle :

```
EXIT=0  src/core/server.py --smoke                    ÉCHEC=0   (cf. anomalie ci-dessous)
EXIT=0  src/console/app.py --smoke                    ÉCHEC=0
EXIT=0  src/research/app.py --smoke                   ÉCHEC=0
EXIT=0  src/core/markers.py                           ÉCHEC=0
EXIT=0  src/core/p300_models.py                       ÉCHEC=0
EXIT=0  src/core/modes/p300.py                        ÉCHEC=0
EXIT=0  src/core/errp_models.py                       ÉCHEC=0
EXIT=0  src/core/modes/errp.py                        ÉCHEC=0
EXIT=0  src/research/errp_stimulus.py --smoke         ÉCHEC=0
EXIT=0  src/research/p300_stimulus.py --smoke         ÉCHEC=0
EXIT=0  src/core/acquisition.py --synthetic           ÉCHEC=0
EXIT=0  src/core/modes/mi.py                          ÉCHEC=0
EXIT=0  src/core/mi_models.py                         ÉCHEC=0
EXIT=0  src/core/modes/calibration.py                 ÉCHEC=0
EXIT=0  src/core/modes/mi_calib.py                    ÉCHEC=0
EXIT=0  src/core/cvep_code.py                         ÉCHEC=0
EXIT=0  src/core/cvep_decoder.py                      ÉCHEC=0
EXIT=0  src/core/cvep_rcca.py                         ÉCHEC=0
EXIT=0  src/core/cvep_models.py                       ÉCHEC=0
EXIT=0  src/core/modes/cvep.py                        ÉCHEC=0
EXIT=0  src/research/cvep_stimulus.py --smoke         ÉCHEC=0
```

Plus 4 non listées dans `CLAUDE.md` mais touchées ou voisines :

```
EXIT=0  src/research/cvep_calibrate.py                ÉCHEC=0
EXIT=0  src/research/cvep_rcca.py                     ÉCHEC=0
EXIT=0  archive/cvep_pilot.py --smoke                 ÉCHEC=0
EXIT=0  archive/cvep_rcca_pilot.py --smoke            ÉCHEC=0
```

### ⚠️ Une anomalie, à ne pas enterrer

Au **premier** passage, `src/core/server.py --smoke` est sorti en **1 avec 8 assertions rouges**.
Il est reparti **vert 3 fois de suite** ensuite, seul, sans aucune modification entre-temps.

Ce premier passage a eu lieu pendant une coupure d'infrastructure où la commande a été relancée puis
basculée en arrière-plan : l'hypothèse la plus plausible est **deux `server.py --smoke` simultanés**,
c'est-à-dire exactement la collision que `CLAUDE.md` décrit (« un serveur oublié répond à la place
de celui qu'on teste »). **Je ne peux pas le prouver** : mon script ne gardait que le compte, pas le
texte des 8 échecs, et je n'ai pas voulu lancer deux python en parallèle pour le vérifier. À
surveiller au prochain passage complet ; si ça se reproduit seul, ce n'est pas une collision.
