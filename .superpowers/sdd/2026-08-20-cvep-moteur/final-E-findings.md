# Revue finale de branche — tranche E : calibration à deux décodeurs + écrans archivés

Périmètre relu : `src/research/cvep_calibrate.py` (968 l.), `src/research/app.py` (points c-VEP),
`archive/cvep_pilot.py`, `archive/cvep_rcca_pilot.py`, `archive/README.md`.

**Lecture seule — aucun programme Python exécuté, aucune calibration lancée.** Les vérifications
proposées sont formulées comme « À VÉRIFIER PAR EXÉCUTION ».

Décompte : **2 Critical · 5 Important · 3 Minor**.

---

## CRITICAL

### C1 — L'ITR et le verdict affichés à l'étudiant sont exactement DOUBLÉS

`src/research/cvep_calibrate.py:588-591` (et ses conséquences 597-599, 624-625, 631)

```python
cycle_s = L / app.refresh          # <- UN cycle
bits_e = _itr(n_cibles, cv_e, cycle_s)
bits_r = _itr(n_cibles, cv_r, cycle_s)
```

`cv_e` / `cv_r` ne sont plus les justesses à un cycle. Depuis ce chantier, elles viennent de
`entraine_les_deux`, qui les mesure à `n_cycles=CVEP_DECISION_CYCLES = 2`
(`cvep_calibrate.py:256-260` → `hors_pli(..., n_cycles=2)`), et `groupes_de_cycles` consomme
littéralement **2 cycles consécutifs par décision** (`core/cvep_decoder.py:67-91`, sa docstring dit
« à k=2 sur 90 cycles, il reste 37 décisions et non 45 »). Une décision coûte donc
`2 × 63/60 = 2,10 s`, pas `1,05 s`.

**C'est une régression franche de ce chantier, pas une dette héritée.** Avant (`git show
c34e326:src/research/cvep_calibrate.py`, l. 288-298), `model.cv_` venait de `CVEPModel.fit` →
`_loo`, une LOO **par époque**, donc à 1 cycle ; `cycle_s = L / app.refresh` était juste, **et la
ligne imprimée le disait** : `f"[cvep-cal] ITR ≈ {bits:.1f} bits/min à 1 cycle ({cycle_s:.2f}s)"`.
Le chantier a migré la justesse vers k=2, n'a pas migré la durée, **et a supprimé la mention
« à 1 cycle »** qui rendait la convention lisible (l. 600-602 aujourd'hui).

Scénario concret, sur la séance de référence que le dépôt documente partout (6 cibles, eCCA 59,5 %,
rCCA 64,9 %) :

| | correct (T = 2,10 s) | imprimé par HEAD (T = 1,05 s) |
|---|---|---|
| eCCA | 19,2 bits/min | 38,3 bits/min |
| rCCA | **23,9 bits/min** | **47,7 bits/min** |
| `ref = _itr(3, 0.95, 1.5)` | 49,9 | 49,9 |
| `verdict` (seuil `ref/2` = 25,0) | **FAIBLE (contact électrodes ? regard qui décroche ?)** | **PROMETTEUR** |
| `return meilleur >= ref/2` | `False` | `True` |

Les 23,9 bits/min correspondent au **« an ITR around 22 bits/min »** de `README.md:202` et aux
22 bits/min de la mémoire projet ; les 47,7 ne correspondent à rien de mesuré. L'écran de fin de
calibration (l. 624) annonce donc « 48 bits/min — PROMETTEUR » sur la séance dont la doc du même
dépôt dit 22, et bascule le verdict d'un cran complet. C'est le chiffre-vedette du chantier, sur le
chemin de production, faux d'un facteur 2 exact.

Effet de bord : le plancher `EARLY_ITR_MIN = 10.0` (l. 35-37, justifié comme « ~1/3 du meilleur
c-VEP mesuré (27,1) », un chiffre d'époque k=2) est appliqué par `_early_check` sur une ITR calculée
à 1 cycle avec une justesse mesurée à 1 cycle (`probe.cv_` vient de `CVEPModel.fit`, l. 143-148 —
cohérent, lui). Le contrôle à mi-parcours et le chiffre final vivent maintenant sur **deux échelles
différentes**, sans que rien ne le dise.

Aucun test ne rougit : le `_selftest` n'assère **aucune** valeur d'ITR, et le tour 3 ne relit que
`hasard (\d+)%` dans stdout (l. 934).

**Correctif minimal** (2 lignes + 1 test) :

```python
# l. 588 — la géométrie où le moteur décide, la MÊME que celle où cv_ a été mesuré
cycle_s = CVEP_DECISION_CYCLES * L / app.refresh   # cf. archive/cvep_pilot.py:81, identique
```
et remettre la convention dans la ligne imprimée (l. 600) :
`f"... sur {n_cibles} cibles jugées (hasard {chance:.0f}%), décision = {CVEP_DECISION_CYCLES} cycles ({cycle_s:.2f}s) :"`.

Test qui rougit sur la mutation : la capture stdout du tour 3 existe déjà (l. 925-928) ; y ajouter
un `_re.search(r"eCCA.*?([\d,\.]+) bits/min", sortie1)` et comparer à
`_itr(3, res1["eCCA"]["justesse"], CVEP_DECISION_CYCLES * L / 60.0)`. Remettre `cycle_s = L/refresh`
double alors la valeur attendue et le test échoue.

À VÉRIFIER PAR EXÉCUTION : `python -c "import sys; sys.path.insert(0,'src'); from research.itr import itr; print(itr(6,0.649,2*63/60), itr(6,0.649,63/60), itr(3,0.95,1.5))"`
— attendu ≈ `23.86  47.72  49.94`.

---

### C2 — `codes_vus` est en ordre de LAG, alors que rCCA apparie par POSITION dans le plan

`src/research/cvep_calibrate.py:234-237` (introduit par le correctif Critical 1, commit `e3754fd`)

```python
presentes = sorted(set(labels))                              # <- trié par VALEUR DE LAG
codes_vus = np.stack([codes[lag_a_idx[l]] for l in presentes])
```

Or le contrat d'appariement du rCCA est **positionnel**, et il est écrit noir sur blanc en deux
endroits de `core/` :

- `core/cvep_rcca.py:257-260` : « `plan[i]` doit décrire la cible dont `model.codes[i]` est le code :
  c'est le SEUL appariement qui existe entre un score et un nom de cible. Décalé d'un cran, tout
  continue de tourner en désignant systématiquement la cible voisine » ;
- `core/cvep_models.py:85-95` (`_codes_affiches`) : le fichier modèle doit porter exactement les
  codes de `build_targets()`, « lignes comprises dans le même ORDRE ».

Avant le correctif C1 (`git show 2dcaf0c:src/research/cvep_calibrate.py`, l. 180-187), c'était le
cas : `codes` était pris **dans l'ordre du plan** et `idx = [lag_a_idx[l] for l in labels]`. Le
correctif a remplacé cet ordre par un tri sur la valeur du lag. **Deux déclencheurs :**

**(a) Séance tronquée — exactement le scénario pour lequel C1 a été écrit.** `codes_vus` a moins de
lignes que le plan → le modèle rCCA sauvegardé (l. 528) porte 3 codes pour un stimulus qui en
affiche 6 → `core.cvep_models.charger` le **refuse** (`cvep_models.py:156`, désaccord de forme) avec
le message « la config a changé depuis la calibration (CVEP_BITS, CVEP_TAPS, CVEP_N_TARGETS) », qui
est un diagnostic faux : rien n'a changé, la séance a été interrompue. Pendant ce temps `calibrate()`
imprime « modèles sauvegardés : … (rCCA) » (l. 560, 609), affiche les deux justesses, et peut nommer
**rCCA gagnant** — un décodeur dont le fichier n'apparaîtra jamais dans la liste de la console ni
dans `modeles_disponibles`. L'étudiant reçoit un succès pour un artefact que rien ne peut charger.

Le `_selftest` **bénit activement** la propriété qui rend le fichier inutilisable (l. 747-749) :
« …et le modèle rCCA sauvegardé porte VRAIMENT 3 codes, pas les 6 du plan complet ». L'assertion est
juste pour la comparaison hors-pli, et fausse comme propriété d'un fichier destiné au disque.

**(b) `CVEP_LAG_ROTATION != 0`.** `build_targets` fait tourner l'affectation lag↔position
(`core/cvep_code.py:69-70`), donc `sorted(set(labels))` ≠ ordre du plan. Les lignes de `codes_vus`
sont alors une **permutation** de celles de `_codes_affiches()` → `charger` refuse **tout** modèle
rCCA fraîchement calibré, avec le message « soit un CVEP_LAG_ROTATION changé, qui permute les lignes
et ferait nommer la cible voisine ». Recalibrer reproduit le même fichier refusé : impasse permanente.
`config.py:510-517` dit explicitement que ce paramètre « reste disponible ».

Tout est vert aujourd'hui uniquement parce que `CVEP_LAG_ROTATION = 0` **et** que le `_selftest`
n'écrit/relit jamais un modèle rCCA issu de `res3` (la séance tronquée). Le test C3 (l. 870-887), le
seul contrôle EXTERNE d'appariement, tourne sur le plan complet à rotation 0 — le seul point où les
deux ordres coïncident.

**Correctif minimal :**

```python
# l. 234 — l'ordre du PLAN, pas celui des valeurs de lag : c'est lui que RCCADecoder
# et core.cvep_models._codes_affiches supposent (cvep_rcca.py:257).
presentes = sorted(set(labels), key=lambda l: lag_a_idx[l])
```
plus, l. 526-528, un refus explicite plutôt qu'un fichier trompeur :

```python
if res["rCCA"]["n_cibles"] != len(plan):
    print(f"[cvep-cal] ⚠️ séance interrompue : {res['rCCA']['n_cibles']} cibles sur {len(plan)} — "
          f"le modèle rCCA n'est PAS sauvegardé (core.cvep_models.charger le refuserait : il "
          f"exige les {len(plan)} codes affichés). La comparaison ci-dessous reste valable.")
else:
    rcca.save(rcca_save_path)
```

Tests qui rougissent : (1) sauvegarder `res3["rCCA"]["modele"]` dans le tmp du selftest et asserter
`charger(...)[0] is not None` — rouge aujourd'hui ; (2) rejouer le contrôle C3 (l. 876-887) avec
`core.cvep_code.CVEP_LAG_ROTATION` monkeypatché à 2 : `choisi["name"]` désigne la voisine.

À VÉRIFIER PAR EXÉCUTION : `python -c "import sys;sys.path.insert(0,'src');from core.cvep_code import build_targets;p,_=build_targets();print([c['lag'] for c in p])"`
— attendu une liste **croissante** à rotation 0 (donc l'ordre coïncide), et non croissante dès que
`CVEP_LAG_ROTATION` est mis à 2 dans `core/config.py:517`.

---

## IMPORTANT

### I1 — « 64,9 % contre 59,5 % » : pas seulement ambigu, **inversé** (point escaladé n° 1)

`src/research/cvep_calibrate.py:343`, `754`, `775-776`, `781`

T8 signale l'ambiguïté ; c'est pire que ça. Le fichier nomme **systématiquement eCCA en premier**
(l. 186 « eCCA 71,1 % … contre rCCA 51,1 % », l. 601-602, l. 619, l. 667, l. 685). Lue avec sa propre
convention, la phrase « 64,9 % contre 59,5 % » attribue donc 64,9 % à eCCA. Les faits :

- `README.md:202` : « **59.5 % (eCCA) and 64.9 % (rCCA)** » ;
- `docs/recette.md:732` : « **eCCA 59,5 %, rCCA 64,9 %** » ;
- la fixture deux lignes plus bas, l. 778-779 : `"eCCA": {"justesse": 22/37}` (= 59,5 %),
  `"rCCA": {"justesse": 24/37}` (= 64,9 %).

Le fichier se contredit lui-même à trois lignes d'intervalle. La l. 343 est la pire :
« 24/37 contre 22/37 à k=2 » — deux fractions nues, dans l'ordre inverse de la convention, dans la
docstring de `_gagnant`, la fonction qui porte tout l'argument statistique du chantier.

**Correctif minimal** — nommer les deux, partout :
- l. 343 : `eCCA 22/37 contre rCCA 24/37 à k=2, p=0,73` ;
- l. 754 : `(rCCA 64,9 % contre eCCA 59,5 % sur la vraie séance — McNemar p=0,73, DU BRUIT)` ;
- l. 775-776 : `... 3 discordances pour eCCA seul, 5 pour rCCA seul ... eCCA 59,5 % contre rCCA 64,9 %` ;
- l. 781 : `un écart de POURCENTAGE réel (rCCA 64,9 % contre eCCA 59,5 %)`.

Formulation recommandée pour l'ensemble : **toujours `<décodeur> <valeur>`, jamais une valeur nue**,
et garder l'ordre eCCA-puis-rCCA du reste du fichier.

### I2 — `calibrate()` ne fait pas le contrôle que la docstring lui délègue explicitement

`src/research/cvep_calibrate.py:553`, `596`, `606`, `622`

La docstring d'`entraine_les_deux` promet un garde-fou **côté appelant**, deux fois :

- `n_decisions` — « Comparé à `len(groupes)` par l'appelant : s'il diffère, ce décodeur a été noté à
  une AUTRE géométrie que celle annoncée » (l. 207-210) ;
- `n_cibles` — « DOIT être égal pour les deux, sinon l'un a été jugé sur un jeu de cibles plus facile
  que l'autre (le Critical 1 …) » (l. 211-217).

Le seul appelant qui fait ces contrôles est `_selftest` (l. 680-687). Le **chemin de production**,
`calibrate()`, ne les fait ni l'un ni l'autre : l. 553 pose `n_cibles = res["eCCA"]["n_cibles"]` avec
un simple commentaire `# == res["rCCA"]["n_cibles"], garanti par construction`, et l. 606/622
impriment `res['eCCA']['n_decisions']` comme s'il valait pour les deux. Une divergence future des
deux `hors_pli` (précisément l'asymétrie `RCCADecoder.n_cycles` que la docstring cite) donne alors
soit un `ValueError` numpy brut dans `_gagnant` l. 360 (tableaux booléens de longueurs différentes),
soit un hasard/ITR lus sur le décodeur le plus favorable — après 3,4 min de casque.

**Correctif minimal**, l. 552, avant tout calcul :

```python
if (res["eCCA"]["n_decisions"] != res["rCCA"]["n_decisions"]
        or res["eCCA"]["n_cibles"] != res["rCCA"]["n_cibles"]):
    raise ValueError(
        f"les deux décodeurs n'ont pas été notés à la même géométrie "
        f"(décisions {res['eCCA']['n_decisions']}/{res['rCCA']['n_decisions']}, cibles "
        f"{res['eCCA']['n_cibles']}/{res['rCCA']['n_cibles']}) — la comparaison serait truquée")
```
Le rendre non-décoratif : dans le selftest, falsifier `res["rCCA"]["n_cibles"]` et vérifier que
`calibrate()`-équivalent refuse. (Un `assert` conviendrait aussi, mais `-O` le supprimerait.)

### I3 — Le modèle eCCA d'une séance tronquée se déclare calibré pour 6 cibles

`src/research/cvep_calibrate.py:527`

```python
ecca.save(save_path, n_targets=len(plan))     # len(plan) = 6, TOUJOURS
```

Après une séance interrompue à 3 cibles — le scénario du Critical 1, que tout le reste de la fonction
traite maintenant honnêtement via `n_cibles` — le fichier eCCA affirme `n_targets = 6`. Rien ne le
refuse : `archive/cvep_pilot.py:84-88` compare `model.n_targets` à `len(plan)`, trouve 6 == 6, et
lance le pilotage ; `core/cvep_models.decrire` l'annonce « 6 cibles » dans la liste de la console.
C'est exactement le piège que `cvep_pilot.py:82-83` documente : « un modèle à 3 cibles “fonctionne”
à 6 sans erreur, mais les 3 lags supplémentaires n'ont jamais été validés → résultats trompeurs ».
Asymétrie supplémentaire : côté rCCA, `n_targets` vaut 3 (dérivé de `codes.shape[0]`) — les deux
fichiers issus de la même séance se contredisent.

**Correctif minimal** : `ecca.save(save_path, n_targets=n_cibles_juges)` où `n_cibles_juges =
len(set(lags))` (calculé avant le bloc de sauvegarde, l. 526), et remonter le bloc de sauvegarde
après le calcul de `n_cibles` pour disposer du chiffre honnête.

### I4 — `_selftest` exécute le VRAI `calibrate()` deux fois sans garde `empreinte_dossier`

`src/research/cvep_calibrate.py:918-960` (et l'import, l. 24-27)

Le dépôt a standardisé `core.config.empreinte_dossier` **précisément pour cette classe d'accident** —
sa docstring (`config.py:84-111`) dit qu'elle vit dans `core/` « pour être appelable depuis
N'IMPORTE QUEL smoke du dépôt » et qu'« un garde-fou qui ne couvre qu'UN appelant sur plusieurs n'en
couvre aucun avec certitude ». Elle est appelée par `archive/cvep_pilot.py:129/175`,
`archive/cvep_rcca_pilot.py:259/355`, `archive/mi_calibrate.py:401/404`, `archive/mi_pilot.py:224/228`
et `src/research/app.py:1338/1514`.

Elle n'est **pas** appelée par `cvep_calibrate.py`, qui est pourtant le seul fichier du lot à faire
tourner le vrai `calibrate()` — la fonction qui a détruit deux modèles pendant ce chantier (incident
1, tour 1 ; incident 2, message de `e734836`). Les chemins sont bien détournés vers des `tempfile`
avec `finally` (l. 921-930, 942-948), donc c'est propre aujourd'hui ; mais si un futur correctif
oublie un `save_path=` (ce qui s'est déjà produit deux fois), **rien dans ce fichier ne le verra**, et
le fichier écrit dans `data/` se ferait élire comme modèle le plus récent.

**Correctif minimal** : ajouter `DATA_DIR, empreinte_dossier` à l'import l. 24-27, encadrer
`_selftest` de `avant = empreinte_dossier(DATA_DIR)` / `chk(empreinte_dossier(DATA_DIR) == avant,
"ce selftest n'a rien écrit dans le vrai data/")` en toute fin, avant le VERDICT. Six lignes,
strictement le patron des quatre archives.

### I5 — La « référence casque » archivée n'est valable qu'aux seuils PAR DÉFAUT, et le README ne le dit pas

`archive/README.md:15` · `archive/cvep_pilot.py:103-106`

Le README justifie de garder `cvep_pilot.py` par une affirmation testable et sans condition :
« the **reference** a headset session checks the network decoding against — both must name the same
target on the same fixation ».

Or les deux derniers commits du chantier (`bfcb73b` « Read the c-VEP thresholds at each decision, so
a session can turn them », `c8e5a81`) ont rendu `corr_min`, `margin`, `vote_len` et `min_votes`
**réglables en séance depuis la console** (`core/modes/cvep.py:682-722`, quatre `Param`, relus à
chaque décision l. 506-521). L'archive, elle, fige les constantes de `core/config.py` :
`CVEPDecoder(model, plan)` sans arguments (l. 75) et `CVEP_VOTE_LEN`/`CVEP_MIN_VOTES` capturés à
l'import (l. 45, 53). Les deux ne décident donc de la même façon **que tant que personne n'a touché
un curseur**. `archive/README.md` (mtime 21 août 13:28) est antérieur à ces deux commits (15:29 et
16:09) : la phrase n'a jamais été relue après.

Conséquence en séance : un désaccord entre l'écran archivé et le flux `decoded_cvep` serait imputé au
moteur ou au réseau, alors qu'il suffit d'un seuil tourné dans la console.

**Correctif minimal**, `archive/README.md:15`, en fin de cellule :
« ⚠️ This reference is only comparable **at the default thresholds**: the engine reads `corr_min`,
`margin`, `vote_len` and `min_votes` from the console at every decision (task 7), this screen hard-codes
the `core/config.py` values. Note down the console's four settings before comparing — a mismatch there
looks exactly like a decoding disagreement. »

---

## MINOR

### M1 — La fixture « cas réel » ne reproduit pas les pourcentages qu'elle annonce

`src/research/cvep_calibrate.py:757-786`

`_corrects_fabrique(29, 3, 5)` (l. 777) ne fabrique que des concordances **toutes deux correctes** :
les tableaux obtenus valent eCCA 32/37 = **86,5 %** et rCCA 34/37 = **91,9 %**, pas les 59,5 % et
64,9 % annoncés l. 776/781 ni les `justesse` passées l. 778-779 (22/37, 24/37). La vraie séance
demande 19 concordances correctes **et 10 concordances fausses**, que `_corrects_fabrique` ne sait pas
produire. Sans effet fonctionnel — `_gagnant` n'utilise que `corrects`, et `b`, `c`, `p` et
`n_discordantes` sont exacts, donc l'assertion est juste — mais les `justesse` passées sont
décoratives et contredisent les `corrects` du même dict, dans le test le plus lu du fichier.

**Correctif minimal** : donner un second paramètre `n_faux` à `_corrects_fabrique`
(`+ [False]*n_faux` des deux côtés) et appeler `_corrects_fabrique(19, 3, 5, n_faux=10)` ; les deux
moitiés de la fixture disent alors la même chose, et `sum(e)/37 == 22/37` devient vérifiable.

### M2 — L'assomption du `_cvep_decode` dupliqué est écrite, mais elle est fausse pour l'un des deux fichiers (point escaladé n° 2)

`archive/cvep_pilot.py:42-44` · `archive/cvep_rcca_pilot.py:45-47` · `archive/README.md`

L'assomption **est** écrite, et au bon endroit (la docstring de la fonction dupliquée) :
« Dupliquée dans `…` à dessein — les deux fichiers archivés doivent rester compréhensibles et
exécutables SEULS, sans dépendre l'un de l'autre. » Pour `cvep_pilot.py` c'est exact et la duplication
de 12 lignes est le bon arbitrage.

Pour `cvep_rcca_pilot.py`, la même phrase cohabite avec un import de **sept symboles — dont quatre
privés — du module vivant `research/cvep_calibrate.py`** (l. 79-81 : `_briefing`, `_draw`,
`_make_blocks`, `_wilson_hi`, `chemin_modele_horodate`, `EARLY_ITR_MIN`, `SETTLE_CYCLES`). Ce fichier
n'est donc pas autonome, et il est couplé au fichier le plus retouché du chantier — dont le
`_selftest` va jusqu'à monkeypatcher `_make_blocks` (l. 906-916). Renommer `_draw` ou `_make_blocks`
casse une archive, et aucun des trois smokes de `CLAUDE.md` ne le voit.

Ce couplage-là est justifié une ligne plus bas (« Réutilise les helpers éprouvés de cvep_calibrate …
pour ne pas diverger du protocole validé ») — le raisonnement se tient, mais l'endroit où il manque
est `archive/README.md`, qui promet « Kept runnable so the refutation stays checkable » sans dire de
quoi cette exécutabilité dépend.

**Correctif minimal**, ajouter au README, sous le tableau :
« `cvep_rcca_pilot.py` deliberately imports the recording helpers (`_briefing`, `_draw`,
`_make_blocks`, `_wilson_hi`, `chemin_modele_horodate`) from the **live**
`src/research/cvep_calibrate.py`, so its protocol cannot drift from the validated one. Renaming any
of them breaks this file and no automated test will say so — run `python archive/cvep_rcca_pilot.py
--smoke` after touching that module. Only `_cvep_decode` (12 lines) is duplicated, so that the two
archived pilots do not depend on each other. »

### M3 — Chemin POSIX en dur dans le selftest, sur un poste Windows

`src/research/cvep_calibrate.py:725-728` : `chemin_modele_horodate("eCCA", dossier="/tmp/xyz_cvep_test")`.
Passe (aucune écriture, `os.path.dirname` rend bien la chaîne d'entrée), mais contredit la consigne
projet sur les dossiers temporaires et se lit mal pour un étudiant sous PowerShell. Remplacer par
`os.path.join(tempfile.gettempdir(), "xyz_cvep_test")` — `tempfile` est déjà importé l. 851.

---

## Point escaladé n° 3 — les six verrous tiennent-ils ensemble ?

| # | Verrou | Correctif en place | Test qui rougit sur mutation | Verdict |
|---|---|---|---|---|
| V1 | Critical 1 — comparaison truquée sur séance tronquée | `presentes` / `codes_vus` / `idx_local`, l. 234-237 | l. 743-746 (`res3`, les deux à 3) + l. 931-939 (`calibrate()` réel, « hasard 33 % ») | **tient** pour la comparaison — **mais** son correctif a créé C2 |
| V2 | Critical 2 — écrasement du modèle Gold | `chemin_modele_horodate` + `save_path or …`, l. 411-412 | l. 706-728 (texte source + motifs `cvep_models`) **et** `app.py:1402-1410` (double couverture) | **tient** |
| V3 | Critical 3 — appariement lag → ligne de code | ordre de `codes_vus` / `idx` | l. 870-887, contrôle EXTERNE via `RCCADecoder` sur modèle relu | **fragile** : ne tourne qu'à `CVEP_LAG_ROTATION = 0`, le seul point où les deux ordres coïncident (voir C2b) |
| V4 | Tour 3 — `n_cibles` ≠ `len(plan)` dans `calibrate()` | l. 553, 587 | l. 920-939, `_make_blocks` détourné + regex sur stdout | **tient** (et c'est le bon patron : il exerce la vraie fonction) |
| V5 | Tour 3 — zéro décision → pas de `TypeError` | l. 287-290 (`None`) + l. 552-576 (chemin fermé) | l. 941-958, `calibrate()` sur une séance sans paire consécutive | **tient** |
| V6 | Tour 3 — repli horodaté de `calibrate_rcca` | `archive/cvep_rcca_pilot.py:78` | `archive/cvep_rcca_pilot.py:265-308`, appel `save_path=None` avec les **deux** liaisons de nom détournées + `empreinte_dossier` | **tient**, et c'est le test le mieux construit du lot |

**Verdict d'ensemble : cinq verrous sur six tiennent ; aucun n'a été défait par une fusion.** Les
six correctifs sont tous présents dans le fichier, chacun avec son test, et les mutations décrites
dans le message de `e734836` feraient toujours rougir `python src/research/cvep_calibrate.py`.

**Mais l'assemblage a produit deux défauts que personne ne pouvait voir en relisant un verrou seul :**

1. **V1 contre V3.** Le correctif de V1 a changé l'ordre des lignes de `codes_vus` (lag croissant au
   lieu de position du plan) — c'est-à-dire l'invariant que V3 existe pour protéger. V3 ne l'attrape
   pas parce que son test tourne sur le plan complet à rotation 0, le seul cas où les deux ordres
   sont identiques. Un verrou et son voisin, chacun vert, un invariant cassé entre les deux. C'est
   exactement le mode de défaillance que la revue finale devait chercher (**C2**).
2. **Le chiffre-vedette est passé entre toutes les mailles.** Les six verrous portent sur l'honnêteté
   de la *comparaison* (mêmes époques, mêmes groupes, mêmes cibles, McNemar) et aucun sur l'honnêteté
   du *chiffre affiché*. La migration vers k=2, qui est la raison d'être de la moitié de ces verrous,
   n'a pas été propagée à `cycle_s` — et l'ITR imprimé est doublé sans qu'aucune des 47 assertions du
   fichier ne s'en aperçoive (**C1**).

Sur la question laissée à cette revue par `e734836` (aligner ou non `CVEPModel.hors_pli` → `(0,)` et
`RCCAModel._hors_pli` → `(0, n_targets)` sur une entrée vide) : **ne rien changer dans `core/`.** Le
contournement `len(sc) == 0` (l. 271-290) est correct pour les deux formes, il est documenté avec sa
preuve, et il est testé (l. 819-827). Aligner les deux `hors_pli` toucherait deux fichiers de la
tâche 3 déjà validés pour ne supprimer qu'un commentaire.

---

## Ce qui est bon, et mérite d'être gardé tel quel

- `_mcnemar_p` (l. 302-328) : test binomial exact bilatéral correct, sans `scipy`, lisible en cinq
  lignes, vérifié contre la valeur indépendante du relecteur (`p(3,5) = 0,7265625`, l. 797) et sur
  les deux dégénérescences (`p(0,0) = 1`, `p(10,10) = 1`, l. 799-800).
- `_gagnant` (l. 336-366) : la garde `p < seuil and b != c` est juste, le `None` sur absence de
  mesure est traité avant tout calcul, et le dict rendu porte `p`, `b`, `c`, `n_discordantes` — donc
  l'écran ne peut pas afficher deux pourcentages sans leur incertitude. `SEUIL_MCNEMAR` est fixé à
  5 % avec la justification explicite qu'il n'a pas été ajusté sur les données.
- Le patron du tour 3 (l. 891-960) : détourner `_make_blocks` via un `contextmanager` avec `finally`
  pour exercer la **vraie** `calibrate()` sur deux scénarios qu'aucun `--smoke` normal n'atteint, puis
  relire stdout. C'est la bonne réponse au reproche « preuves en scripts jetables », et c'est
  réutilisable tel quel pour tester C1.
- `_fit_et_compte` (l. 152-159) : petit, et il rend `n_epoques` non-tautologique pour la bonne
  raison — le compte est pris sur l'argument passé à `.fit()`, pas recalculé à côté.
- `archive/cvep_rcca_pilot.py:265-308` : le seul test du dépôt qui détourne **les deux liaisons de
  nom** d'une même constante, avec dans le commentaire l'incident vécu qui l'a rendu nécessaire.
