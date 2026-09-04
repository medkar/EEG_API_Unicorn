# Tâche 6 — la calibration entraîne les deux et affiche les deux chiffres

**Statut : terminé.** Base `1995b22`. Fichiers modifiés : `src/research/cvep_calibrate.py`,
`src/research/app.py`, `src/research/cvep_rcca.py`, `archive/README.md`. Fichiers créés :
`archive/cvep_pilot.py`, `archive/cvep_rcca_pilot.py`.

---

## 1. Ce qui a été livré

### `src/research/cvep_calibrate.py` — `entraine_les_deux` + `_gagnant`

`entraine_les_deux(epochs, labels, fs=FS_UNICORN, refresh=60.0, band=CVEP_BAND, channels=None,
n_cycles=1)` entraîne `CVEPModel` (eCCA) et `RCCAModel` (rCCA) sur les **mêmes** époques réduites
aux mêmes voies, note chacun **hors-pli** via son `hors_pli(...)` (task 3, réutilisé tel quel — je
n'ai rien redécodé), et rend :

```python
{"eCCA": {"modele": ecca, "justesse": ..., "n_epoques": ..., "groupes": ..., "n_decisions": ...},
 "rCCA": {"modele": rcca, "justesse": ..., "n_epoques": ..., "groupes": ..., "n_decisions": ...}}
```

`_gagnant(res)` nomme le décodeur le plus juste, ou rend `None` sur une **égalité exacte** — le cas
réellement mesuré sur la seule séance disponible (43/90 chacun, cf. `core/cvep_rcca.py`).

`calibrate()` (l'écran pygame) appelle `entraine_les_deux` à la place de l'ancien `model.fit(...)`,
sauvegarde **les deux** modèles (nouveau paramètre `rcca_save_path=CVEP_RCCA_MODEL_PATH`), et
affiche les deux justesses + le gagnant, en console et à l'écran (§4).

### `archive/cvep_pilot.py` (nouveau) et `archive/cvep_rcca_pilot.py` (nouveau)

`mode_cvep` (eCCA) et `mode_cvep_rcca` (Gold/rCCA) sont sortis de `src/research/app.py` tels
quels, en scripts autonomes qui réutilisent la machinerie encore vivante dans `app.py`
(`Live`, `_running`, `_live_loop`, `_vote` — toujours nécessaire au SSVEP) plutôt que de la
dupliquer. `calibrate_rcca` (Gold) est sorti de `src/research/cvep_rcca.py` et regroupé avec
`mode_cvep_rcca` dans `archive/cvep_rcca_pilot.py`, avec un `--calibrate` qui les enchaîne (patron
`mi_pilot.py --calibrate`). Chaque fichier garde son `--smoke`.

### `src/research/app.py` — le c-VEP n'a plus qu'une calibration

`page_cvep` perd le choix de variante (eCCA / rCCA) et l'option « Lancer le live » : il ne reste
que « Calibrer ». `mode_cvep`, `mode_cvep_rcca`, `calib_cvep_rcca`, `_cvep_decode` sont supprimés
(déplacés dans `archive/`). Imports devenus inutiles retirés (`deque`, `_itr`, et 7 constantes
`CVEP_*`) — vérifié un par un par comptage d'occurrences, pas au jugé.

### `src/research/cvep_rcca.py` — allégé de sa calibration

Ne garde que `make_distinct_codes` / `build_targets_rcca` (l'hypothèse réfutée, lisible) et le
ré-export de `RCCAModel`/`RCCADecoder`. `calibrate_rcca` est parti dans `archive/`.

---

## 2. Autotests

| Commande | Résultat |
|---|---|
| `python src/research/cvep_calibrate.py` | **11/11 OK**, `VERDICT : OK`, exit 0 |
| `python src/research/app.py --smoke` | `smoke OK : menu + SSVEP + c-VEP (calibration eCCA+rCCA) + P300 + neuro + ErrP(cal+démo)`, exit 0 |
| `python src/core/server.py --smoke` (non-régression) | 17 sections, toutes `VERDICT : OK`, y compris `smoke-frontiere` (31 fichiers, 0 violation) et `smoke-mi`/`smoke-calib` — le moteur n'a pas bougé, attendu | exit 0 |
| `python src/core/cvep_decoder.py` (non-régression) | `VERDICT : OK`, exit 0 |
| `python src/core/cvep_rcca.py` (non-régression) | `VERDICT : OK`, exit 0 |
| `python src/core/cvep_models.py` (non-régression) | `VERDICT : OK`, exit 0 |
| `python src/research/cvep_rcca.py` (fichier réduit) | autotest Gold inchangé, exit 0 |
| `python archive/cvep_pilot.py --smoke` | `smoke OK : calibration + décodage + affichage câblés`, exit 0 |
| `python archive/cvep_rcca_pilot.py --smoke` | `smoke OK : calibration Gold + décodage + affichage câblés`, exit 0 |

Chaque commande lancée **seule**, jamais deux en parallèle ; aucun python du projet ne traînait
avant de conclure. `data/` vérifié par **horodatage** avant/après CHAQUE commande à risque
(snapshot taille+mtime des 43 fichiers, comparé après coup) : aucun ajout, aucune suppression,
aucune modification en dehors de mon unique correction manuelle documentée au §5.

---

## 3. La preuve rouge du test de comparaison honnête

Le test vérifie trois choses : les deux décodeurs sont entraînés, sur le **même nombre
d'époques**, avec les **mêmes groupes** de validation croisée — et un quatrième contrôle,
`n_decisions == len(groupes)`, qui est ce qui empêche « groupes » d'être décoratif : il compare ce
que CHAQUE décodeur a **réellement** noté (la longueur renvoyée par SON `hors_pli`) au nombre de
groupes annoncé.

**Mutation** (une ligne, `src/research/cvep_calibrate.py`, dans `entraine_les_deux`) :

```diff
-    sc_r, y_r = rcca.hors_pli(reduits, idx, n_cycles=n_cycles)
+    sc_r, y_r = rcca.hors_pli(reduits, idx, n_cycles=n_cycles + 1)  # rCCA noté à une AUTRE géométrie
```

C'est exactement l'asymétrie que ce chantier a déjà trouvée ailleurs et corrigée
(`RCCADecoder.n_cycles` valait 1 par défaut quand `CVEPDecoder.n_cycles` valait
`CVEP_DECISION_CYCLES`, sans commentaire) : un décodeur noté à une géométrie différente de l'autre,
en silence.

### ROUGE

```
  OK   les deux décodeurs sont entraînés (['eCCA', 'rCCA'])
  OK   ...sur le MÊME nombre d'époques — sinon la comparaison ne veut rien dire (48, 48, 48)
  OK   ...et les mêmes groupes de validation croisée (48 vs 48 groupes)
  ÉCHEC ...et chaque décodeur a RÉELLEMENT noté autant de groupes qu'annoncé — sinon deux
        géométries différentes se compareraient sans qu'aucun message ne le dise (48, 24, 48)
  OK   ...et chacun rend une justesse HORS-PLI, dans [0, 1] (1.0, 1.0)
  [...]
[cvep-calibrate] VERDICT : PROBLÈME
EXIT=1
```

(48 groupes annoncés, mais rCCA n'a réellement noté que 24 décisions — à `n_cycles+1=2`, les
groupes de deux cycles consécutifs sont deux fois moins nombreux.) Notable : le contrôle
« mêmes groupes » (comparaison brute des deux listes, calculées une seule fois) reste VERT sous
cette mutation — c'est prévu et documenté dans le commentaire du code : cette liste-là est commune
par construction, donc son égalité seule ne prouve rien sur ce que chaque décodeur a fait de son
côté. C'est `n_decisions` qui referme ce trou, en lisant la longueur réellement rendue par CE
`hors_pli`-là.

### VERT (mutation retirée)

```
  OK   les deux décodeurs sont entraînés (['eCCA', 'rCCA'])
  OK   ...sur le MÊME nombre d'époques — sinon la comparaison ne veut rien dire (48, 48, 48)
  OK   ...et les mêmes groupes de validation croisée (48 vs 48 groupes)
  OK   ...et chaque décodeur a RÉELLEMENT noté autant de groupes qu'annoncé — sinon deux
       géométries différentes se compareraient sans qu'aucun message ne le dise (48, 48, 48)
  OK   ...et chacun rend une justesse HORS-PLI, dans [0, 1] (1.0, 1.0)
  OK   ...et chaque modèle SAIT quel décodeur il est (le champ que `save` écrit)
  OK   le décodeur le plus juste est nommé gagnant
  OK   ...dans les deux sens
  OK   ...et une ÉGALITÉ EXACTE (43/90 chacun, le cas réellement mesuré, cf. core/cvep_rcca.py) ne
       nomme PERSONNE plutôt que de trancher arbitrairement
  OK   le modèle eCCA sauvegardé se relit, décodeur et justesse compris (None)
  OK   ...et le modèle rCCA aussi (None)
[cvep-calibrate] VERDICT : OK
EXIT=0
```

`git diff --stat src/research/cvep_calibrate.py` vide après retrait de la mutation : le fichier
livré est intact.

---

## 4. Ce que l'écran affiche exactement à la fin d'une calibration

**Console**, dans l'ordre :

```
[cvep-cal] <N> cycles sur <n_cibles> cibles (hasard <chance>%) :
[cvep-cal]   eCCA  leave-one-out <cv_e>%  -> <bits_e> bits/min
[cvep-cal]   rCCA  leave-one-out <cv_r>%  -> <bits_r> bits/min
[cvep-cal] gagnant : <eCCA|rCCA|égalité>   —   SSVEP de référence <ref> -> <verdict>
[cvep-cal] `python src/research/cvep_analyze.py` pour le gain en moyennant plusieurs cycles.
[cvep-cal] modèles sauvegardés : <save_path> (eCCA)  ·  <rcca_save_path> (rCCA)
```

Exemple réel, capturé sur le smoke synthétique de `app.py` :

```
[cvep-cal] 12 cycles sur 6 cibles (hasard 17%) :
[cvep-cal]   eCCA  leave-one-out  58.3%  ->  36.4 bits/min
[cvep-cal]   rCCA  leave-one-out  25.0%  ->   1.8 bits/min
[cvep-cal] gagnant : eCCA   —   SSVEP de référence 49.9 -> PROMETTEUR
```

**Écran pygame** (5 secondes, ou jusqu'à une touche), du haut vers le bas :

1. **`eCCA <cv_e>%   ·   rCCA <cv_r>%`** — les deux justesses côte à côte, police `big`.
2. **`gagnant : <nom>`** — en vert.
3. **`<meilleur> bits/min (meilleur des deux)   —   SSVEP réf. <ref>`** — vert si ≥ moitié de la
   référence, orange sinon.
4. Le verdict textuel (« DÉPASSE LE SSVEP » / « PROMETTEUR » / « FAIBLE (...) »), en gris.
5. **`modèles sauvegardés (eCCA et rCCA) — ESC pour continuer`**, en gris.

`gagnant` vaut littéralement `"égalité"` (pas un nom vide ni un tiret) quand `_gagnant` rend
`None` — c'est le cas mesuré sur la seule séance réelle disponible (43/90 chacun), donc l'écran
doit pouvoir l'afficher sans avoir l'air cassé.

---

## 5. Un incident, corrigé et documenté

En écrivant le `--smoke` de `archive/cvep_pilot.py`, j'ai appelé `cvep_calibrate.calibrate(app,
save_path=model_path)` **sans** fournir `rcca_save_path` — son défaut est `CVEP_RCCA_MODEL_PATH`,
c'est-à-dire le VRAI `data/cvep_rcca_model.npz`. Une exécution de ce smoke a donc écrit un modèle
synthétique par-dessus le seul modèle rCCA jamais calibré au casque (2026-07-21, codes Gold,
35,6 % — le chiffre cité dans la docstring de `core/cvep_rcca.py`).

**Récupéré** : les époques brutes de cette séance existent encore, archivées séparément
(`data/cvep_rcca_calib_20260721-161305_n6.npz` — identifié en ré-ajustant chacun des 5 fichiers
`cvep_rcca_calib_*` du 21 juillet et en comparant leur `cv_` au 35,6 % documenté ; un seul
correspond, exactement). Ré-ajusté et resauvegardé à l'identique du protocole d'origine
(`RCCAModel.fit(epochs, labels, compute_cv=True)` puis `.save(...)`), `cv_` retrouvé = **35,56 %**
(35,6 % arrondi). Vérifié que le fichier restauré est correctement **refusé** par
`cvep_models.charger` (codes Gold, pas ceux du stimulus actuel) — exactement le comportement
documenté pour l'original.

**Corrigé dans le code**, pas seulement réparé à la main : les deux `--smoke` (`cvep_pilot.py` ET
`cvep_rcca_pilot.py`) détournent maintenant EXPLICITEMENT `rcca_save_path` vers leur dossier
temporaire, avec un commentaire nommant le risque. Vérifié par snapshot horodatage avant/après :
`data/` intact sur les deux relances. `archive/README.md` documente pourquoi les deux fichiers
c-VEP sont plus prudents sur ce point que le couple MI.

Je le signale explicitement parce que c'est exactement le genre de panne muette que ce dépôt
existe pour éliminer — je ne voulais pas la laisser sous silence au prétexte qu'elle est réparée.

---

## 6. Doutes

1. **`n_epoques` et `n_decisions` sont redondants avec `justesse` en usage normal** — le contrôle
   `n_decisions` n'a de valeur que comme filet anti-régression (il n'est *décoratif* que si
   personne ne le lit). Je l'ai gardé parce que la preuve rouge du §3 montre qu'il mord exactement
   là où le brief demandait de vérifier, mais un relecteur pourrait juger qu'il alourdit le dict
   rendu pour un cas qui ne devrait plus jamais se produire une fois `entraine_les_deux` stabilisé.
2. **`_gagnant` compare deux `float` avec `==` pour détecter l'égalité.** C'est sûr ici parce que
   les deux justesses sortent de `k / n` avec le **même** `n` (prouvé par le contrôle du §3), donc
   une vraie égalité de fractions reste une égalité de flottants — mais ce n'est vrai que tant que
   cette contrainte tient. Si `entraine_les_deux` changeait un jour pour comparer deux comptages à
   dénominateurs différents, `==` deviendrait le mauvais outil sans qu'aucun test actuel ne le
   signale.
3. **Rien n'a été vérifié au casque.** Tout est synthétique ou smoke headless. En particulier, je
   n'ai aucune mesure de ce que `entraine_les_deux` donnerait sur une VRAIE séance à deux
   décodeurs — la seule donnée réelle disponible (`cvep_calib_last.npz`) n'a été rejouée que par
   `cvep_rcca.py --seuils` (tâche 3), pas par le chemin que `calibrate()` emprunte maintenant. Les
   deux chemins appellent les mêmes `hors_pli`, donc je m'attends au même résultat (43/90 chacun),
   mais je ne l'ai pas fait tourner pour le vérifier mot pour mot.
4. **`archive/cvep_pilot.py` et `archive/cvep_rcca_pilot.py` dupliquent `_cvep_decode`** (une
   douzaine de lignes) plutôt que de se l'importer l'un l'autre — choisi pour que chaque fichier
   archivé reste lisible et exécutable SEUL, mais c'est une duplication assumée, pas une absence
   de choix.
5. **Le message d'égalité de l'écran (`"égalité"`) n'a pas de couleur distincte** — il passe par
   la même ligne `GO` (vert) que « gagnant : eCCA » ou « gagnant : rCCA », ce qui pourrait suggérer
   à tort qu'un des deux a gagné. Personne n'a vu cet écran ; je ne sais pas si c'est lisible en
   pratique.

---

# Tour de correction 1

**La revue n'avait pas approuvé : 3 Critical, 4 Important, 2 mineurs.** Les 9 sont traités. En les
corrigeant, un DIXIÈME défaut est apparu — introduit par ma propre correction de l'Important 4, pas
signalé par la revue — et je le documente comme tel : le smoke se cassait ~40 % du temps
(`IndexError`), pour une raison structurelle et non aléatoire. Trouvé et fermé avant de rendre.

## Critical 1 — une séance interrompue truquait le hasard

`entraine_les_deux` restreint désormais les codes du rCCA aux SEULES cibles présentes dans `labels`
(`presentes = sorted(set(labels))`), exactement comme `CVEPModel.hors_pli` restreint déjà son
`uniq`. Un champ `n_cibles` (dérivé de `sc.shape[1]`, la largeur RÉELLE de la matrice de scores —
jamais une valeur redondante) rend le nombre d'alternatives que chaque décodeur a effectivement
jugées, et `calibrate()`/le selftest comparent les deux.

**Rouge** (`RCCAModel(codes, ...)` au lieu de `RCCAModel(codes_vus, ...)`, sur un fixture tronqué à
3 cibles sur 6) :
```
ÉCHEC une séance tronquée à 3 cibles sur 6 juge les DEUX décodeurs parmi 3 alternatives, jamais 6 pour l'un et 3 pour l'autre (3, 6)
ÉCHEC ...et le modèle rCCA sauvegardé porte VRAIMENT 3 codes, pas les 6 du plan complet (6)
```
**Vert** : mutation retirée, 18/18 OK (avant l'ajout des autres tests de ce tour).

## Critical 2 — la calibration du menu écrivait sur le modèle Gold du 21 juillet

`chemin_modele_horodate(decodeur, dossier=None)` reprend le patron `p300_calibrate` /
`errp_calibrate` : `data/cvep_model_AAAAMMJJ-HHMMSS.npz` / `..._rcca_..._`, jamais
`CVEP_MODEL_PATH`/`CVEP_RCCA_MODEL_PATH` en dur. `calibrate(app, ..., save_path=None,
rcca_save_path=None)` — les deux retombent dessus. Vérifié en DEUX endroits : le selftest de
`cvep_calibrate.py` (texte source + comportement) et un nouvel invariant dans `app.py::_smoke`
(texte source, sur le patron exact des invariants P300/ErrP déjà présents).

**Rouge** (défauts remis à `save_path=CVEP_MODEL_PATH, rcca_save_path=CVEP_RCCA_MODEL_PATH`) :
```
ÉCHEC calibrate() retombe sur des chemins HORODATÉS quand on ne lui en donne pas — jamais sur CVEP_MODEL_PATH / CVEP_RCCA_MODEL_PATH en dur dans sa signature
```
...et côté `app.py --smoke`, la MÊME mutation :
```
AssertionError: calibrate() ne doit JAMAIS avoir CVEP_MODEL_PATH comme défaut de save_path — un défaut fixe écraserait le modèle eCCA à chaque calibration de démonstration
```
**Vert** dans les deux cas, mutation retirée.

## Critical 3 — l'appariement lag -> ligne de code n'était vérifié par rien

Nouveau contrôle EXTERNE : le modèle rCCA, sauvegardé PUIS RELU, doit désigner via `RCCADecoder` la
cible réellement affichée dans une fenêtre synthétique de cible connue — pas seulement afficher une
bonne justesse (qui reste aveugle à un décalage systématique, cohérent avec lui-même).

**Rouge** (`idx = [(idx_local[l] + 1) % len(presentes) for l in labels]`, reproduisant exactement le
`+1 % len(plan)` de la revue) :
```
OK   ...et chacun rend une justesse HORS-PLI, dans [0, 1] (1.0, 1.0)          <- la justesse ne voit RIEN
ÉCHEC le modèle rCCA sauvegardé-puis-relu désigne la cible RÉELLEMENT affichée, pas sa voisine (AV-GAUCHE au lieu de AR-GAUCHE) — un décalage systématique de l'appariement lag -> ligne de code resterait invisible à la seule justesse hors-pli
```
Confirme exactement le diagnostic de la revue : justesse 1,0/1,0 inchangée, seul le contrôle externe
rougit. **Vert** : mutation retirée.

## Important 4 — mesurer à la géométrie où le moteur décide

`entraine_les_deux(..., n_cycles=CVEP_DECISION_CYCLES)` par défaut (était 1). Vérifié par
introspection de signature. Sur le VRAI `data/cvep_calib_last.npz` (lecture seule), la fonction
corrigée rend maintenant :

```
eCCA : justesse=59.5%  (22/37 décisions)  n_cibles=6  n_epoques=90
rCCA : justesse=64.9%  (24/37 décisions)  n_cibles=6  n_epoques=90
gagnant : rCCA
```

— exactement les 22/37 et 24/37 mesurés indépendamment par la revue. **C'est le chiffre demandé en
fin de rapport : à k=2, le gagnant est rCCA, pas l'égalité qu'affichait k=1.**

## Le dixième défaut : le smoke devenait flaky, à cause de ma PROPRE correction

En basculant `n_cycles` à 2 (Important 4), le `--smoke` d'`archive/cvep_pilot.py` s'est mis à
planter par intermittence (`IndexError: tuple index out of range` sur `sc.shape[1]`) — **3 échecs
sur 5 lancements**, mesuré. Cause structurelle, pas malchance pure : en smoke, `cycles=2` avec
`CVEP_CAL_BLOCKS=3` donne `per = max(1, 2 // 3) = 1` — chaque bloc n'enregistre donc JAMAIS deux
cycles consécutifs de la même cible, et `groupes_de_cycles(labels, k=2)` ne trouve une paire que si
le MÉLANGE ALÉATOIRE des blocs en place deux du même bloc côte à côte par chance. Deux corrections :

1. **La cause** : `cycles = 6` en smoke (au lieu de 2) — `per = max(1, 6 // 3) = 2`, donc CHAQUE
   bloc porte 2 cycles consécutifs, quel que soit l'ordre après mélange. **8/8 lancements propres**
   après correction (contre 3 échecs sur les 5 précédents).
2. **Le symptôme, en défense** : `entraine_les_deux` ne lève plus si `hors_pli` rend un tableau vide
   (`sc.ndim == 1`) — `n_cibles` retombe alors sur `len(presentes)` (le nombre VISÉ, identique pour
   les deux décodeurs par construction) au lieu de planter sur `.shape[1]`.

## Important 5 — les smokes archivés ne prouvaient pas que la boucle live tournait

`app.flash` est espionné pendant l'appel à `mode_cvep`/`mode_cvep_rcca` dans les deux `main()`
archivés : tout titre commençant par « Pas de modèle » ou « Modèle » signale un retour AVANT la
boucle live, et fait échouer le smoke par `assert`.

**Rouge**, en reproduisant EXACTEMENT le scénario de la revue (modèle fraîchement calibré, puis
resauvegardé avec `n_targets=3` en dur) :
```
AssertionError: mode_cvep a été refusé SILENCIEUSEMENT (['Modèle calibré pour 3 cibles']) — il serait sorti AVANT sa boucle live, et rien d'autre que cette assertion ne l'aurait remarqué
```
**Vert** : mutation retirée, `exit=0`.

## Important 6 — « mêmes époques » n'était vérifié que par un compte tautologique

`_fit_et_compte(modele, epochs, labels, **kw)` ajuste et rend `len(epochs)` — capturé à l'endroit
même de l'appel à `.fit()`, donc lié à l'ARGUMENT réel et non à une longueur recalculée à côté. Un
garde défensif (dans `entraine_les_deux`) lève si la largeur des époques données à un décodeur ne
correspond pas au nombre de voies qu'il déclare.

**Rouge n°1** (`rcca.fit(epochs_rcca[:-6], idx[:-6], ...)`) :
```
ÉCHEC ...sur le MÊME nombre d'époques — sinon la comparaison ne veut rien dire (48, 42, 48)
```
**Rouge n°2** (`epochs_rcca` recalculé à partir des époques BRUTES, non réduites — 8 voies au lieu
de 4) :
```
ValueError: rCCA : 48 époques à 8 voies pour 4 voies déclarées ([4, 5, 6, 7]) — la comparaison ne serait pas honnête
```
(Le fixture du selftest génère maintenant 8 voies BRUTES réduites à 4 AJUSTÉES — comme la vraie
calibration — au lieu de 4 voies générées directement, qui rendait ce garde invérifiable.)
**Vert** dans les deux cas, mutations retirées.

## Important 7 — `calibrate()` elle-même n'était jamais exercée pour SA sauvegarde

`app.py::_smoke` charge maintenant `cvep_path` ET `rcca_path` via `core.cvep_models.charger` juste
après l'appel à `cvep_calibrate.calibrate(...)`, et vérifie le `.decoder` de chacun.

**Rouge** (`rcca.save(rcca_save_path)` commenté dans `calibrate()`) :
```
AssertionError: ...et un modèle rCCA CHARGEABLE à rcca_save_path — supprimer `rcca.save(...)` dans `calibrate()` laisserait ce smoke vert sans ce contrôle : modèle introuvable : ...\cvep_rcca_model_smoke.npz
```
**Vert** : mutation retirée.

## Les deux mineurs

- **`research/cvep_rcca.py::_demo()` rendait `True` en dur.** Réécrit avec des `chk()` (justesse
  très au-dessus du hasard à chaque SNR, phase glissante correcte sur presque toutes les phases,
  save/reload identique) et un VERDICT agrégé. Rouge prouvé en réintroduisant le bug de signe que
  ce fichier documente déjà (`np.roll(..., +shift(p))` au lieu de `-shift(p)`) : phase glissante
  2/7 au lieu de 7/7, `VERDICT : PROBLÈME`, exit 1. Vert, mutation retirée.
- **`n_epoques` tautologique** : résolu par le même mécanisme que l'Important 6
  (`_fit_et_compte`) — `n_epoques_ecca`/`n_epoques_rcca` sont maintenant deux valeurs
  INDÉPENDANTES, chacune lue sur son propre appel à `.fit()`.

## La cause de l'incident, fermée — pas seulement son symptôme

`core.config.empreinte_dossier(dossier=DATA_DIR)` (déménagée depuis `research/app.py::_empreinte_data`,
qui reste un alias) est maintenant appelée par les DEUX smokes archivés (`archive/cvep_pilot.py`,
`archive/cvep_rcca_pilot.py`), avant/après tout appel de calibration, en plus d'`app.py`.

**Preuve, en processus isolé, SANS toucher au vrai `data/`** : `core.cvep_calibrate.CVEP_MODEL_PATH`
et `CVEP_RCCA_MODEL_PATH` sont redirigés vers un dossier FAUX (créé par `tempfile.mkdtemp`) avant
tout appel, `cvep_pilot.DATA_DIR` de même — puis la redirection `rcca_save_path=...` est retirée du
smoke (reproduisant l'incident EXACT du 2026-08-21). Résultat :

```
[cvep-cal] modèles sauvegardés : ...\cvep_pilot_smoke_...\cvep_model_smoke.npz (eCCA)  ·  ...\faux_data_qtmowog0\cvep_rcca_model_20260821-122753.npz (rCCA)
ASSERTION LEVÉE COMME ATTENDU : ce smoke a touché data/ — la calibration doit écrire UNIQUEMENT dans le dossier temporaire ci-dessus, jamais dans data/ ... : {'cvep_rcca_model_20260821-122753.npz'}
```

Le fichier fuit dans le dossier FAUX (jamais le vrai `data/`, vérifié par empreinte avant/après sur
le VRAI dossier aussi), et le garde le NOMME. Redirection remise → smokes verts, `exit=0` chacun,
8 lancements consécutifs sans échec.

## Autotests (tour de correction 1)

| Commande | Résultat |
|---|---|
| `python src/research/cvep_calibrate.py` | 22/22 OK, exit 0 |
| `python src/research/app.py --smoke` | OK, exit 0 |
| `python src/core/server.py --smoke` (non-régression) | 17 sections OK, exit 0 |
| `python archive/cvep_pilot.py --smoke` | OK, exit 0 (**8/8** lancements consécutifs, contre 3 échecs sur 5 avant la correction du dixième défaut) |
| `python archive/cvep_rcca_pilot.py --smoke` | OK, exit 0 |
| `python src/research/cvep_rcca.py` (`_demo` corrigée) | OK, exit 0 — peut maintenant réellement sortir en 1 |
| `python src/core/cvep_decoder.py` / `cvep_rcca.py` / `cvep_models.py` / `config.py` (non-régression) | OK, exit 0 chacun |
| `python src/console/app.py --smoke` (non-régression) | OK, exit 0 |

`data/` vérifié intact par empreinte (taille+mtime, 43 fichiers) avant/après CHAQUE commande à
risque, tout au long de ce tour — y compris la preuve du garde-fou, menée en processus isolé sur un
dossier substitué.

## Doutes (tour de correction 1)

1. **`chemin_modele_horodate` n'est testée que pour la FORME du nom, pas pour l'unicité entre deux
   appels rapprochés** — deux calibrations dans la même seconde produiraient le même nom horodaté
   et l'une écraserait l'autre. Le P300/l'ErrP ont la même limite ; je ne l'ai pas corrigée
   (hors du périmètre signalé), seulement héritée en copiant leur patron.
2. **La restriction des codes rCCA aux cibles présentes (Critical 1) laisse un modèle rCCA
   « tronqué » sauvegardable** si une séance est interrompue avant d'avoir vu les 6 cibles.
   `cvep_models.charger` le REFUSE ensuite (dimensions différentes de `_codes_affiches()`), donc
   il ne peut pas être chargé par erreur — mais le message de refus (« la config a changé depuis la
   calibration ») ne nomme pas la VRAIE cause (séance interrompue) pour ce cas précis. Je ne l'ai
   pas retouché : ce n'est pas ce que la revue demandait, et le comportement SÛR (refuser plutôt
   que charger un modèle partiel) est déjà là.
3. **L'ordre de `presentes` (trié par valeur de lag) coïncide avec l'ordre du plan uniquement parce
   que `CVEP_LAG_ROTATION = 0` aujourd'hui** — si cette constante changeait, une séance tronquée
   pourrait produire un `codes_vus` dont l'ordre relatif diverge de celui du plan complet. Je l'ai
   repéré en écrivant le test de Critical 3, choisi de ne PAS le blinder (aucun code du dépôt ne
   fait varier `CVEP_LAG_ROTATION` aujourd'hui), et je le signale plutôt que de le cacher.
4. **Le dixième défaut (smoke flaky) n'aurait montré AUCUN signe avant-coureur dans mon propre
   premier tour** : mes runs de vérification initiaux (avant ce tour de correction) sont tombés du
   bon côté du hasard. Je ne sais pas combien d'autres chemins de ce genre existent, testés
   insuffisamment de fois pour révéler leur variance.

---

# Tour de correction 2

**Le défaut central : l'écran conseillait sur du bruit.** `_gagnant` comparait deux justesses
(64,9 % contre 59,5 %) comme si elles venaient de deux échantillons INDÉPENDANTS. Sur des décisions
APPARIÉES (mêmes époques pour les deux décodeurs), c'est le mauvais test — McNemar exact bilatéral
est celui qui convient, et il rend p=0,727 sur la vraie séance : l'écart est du bruit, exactement le
péché cardinal que `CLAUDE.md` interdit.

## Le défaut central — corrigé

`_mcnemar_p(b, c)` : test binomial exact bilatéral, sans dépendance à `scipy.stats` (`math.comb`
suffit). `entraine_les_deux` expose désormais `corrects` (tableau booléen par décision, APPARIÉ
entre eCCA et rCCA — les deux `hors_pli` parcourent `groupes_de_cycles` sur des étiquettes en
bijection, donc le même ordre de groupes). `_gagnant(res, seuil=0.05)` calcule `b` (eCCA seul
correct) et `c` (rCCA seul correct), et ne nomme un gagnant QUE si `p < seuil`. Rend un dict
(`gagnant`, `p`, `b`, `c`, `n_discordantes`), pas un nom — l'écran a besoin de la p-value et du
nombre de décisions discordantes pour être honnête.

**Preuve rouge** (`if p < seuil and b != c:` → `if b != c:`, sur le fixture qui reproduit EXACTEMENT
la vraie séance, b=3/c=5) :
```
ÉCHEC ...et un écart de POURCENTAGE réel (64,9 % contre 59,5 %) mais NON DÉFENDABLE (McNemar
      p=0,73, le cas mesuré sur la vraie séance) ne nomme PERSONNE — c'est le défaut central
      trouvé au tour 2 de la revue ({'gagnant': 'rCCA', 'p': 0.7265625, 'b': 3, 'c': 5,
      'n_discordantes': 8})
```
**Vert** : mutation retirée, `gagnant` redevient `None`.

**Sur la vraie séance** (`data/cvep_calib_last.npz`, lecture seule) :
```
eCCA : justesse=59.5%  n_decisions=37  n_cibles=6
rCCA : justesse=64.9%  n_decisions=37  n_cibles=6
McNemar : {'gagnant': None, 'p': 0.7265625, 'b': 3, 'c': 5, 'n_discordantes': 8}
p arrondi a 3 decimales : 0.727
```
`0.7265625` — identique au `p=0,727` mesuré indépendamment par la revue.

**L'écran affiche désormais**, quand ce n'est pas significatif :
```
[cvep-cal] indiscernables sur cette séance (McNemar p=0.727) — 8 décisions discordantes sur 37
           (eCCA seul 3, rCCA seul 5)
```
et, capturé sur une VRAIE exécution de `calibrate()` (headless, 9 décisions, écart apparent
77,8 %/44,4 % mais non défendable à si peu de décisions) :
```
[cvep-cal] indiscernables sur cette séance (McNemar p=0.250) — 3 décisions discordantes sur 9
           (eCCA seul 3, rCCA seul 0)
```
Quand c'est significatif, la ligne devient `gagnant : eCCA (McNemar p=0.000)`. À l'écran pygame :
gros titre `eCCA X% · rCCA Y%`, puis soit `indiscernables sur cette séance (p=...)` en gris, soit
`gagnant : <nom> (p=...)` en vert, puis une ligne dédiée aux décisions discordantes.

## Réserve C1 — fermée : le hasard et l'ITR suivent `n_cibles`

`chance = 100.0 / n_cibles` (plus `len(plan)`), `bits_e/bits_r = _itr(n_cibles, cv_e/cv_r, cycle_s)`.
**Preuve intégration** (le VRAI `calibrate()`, `_make_blocks` monkey-patché pour ne produire des
blocs QUE pour 3 cibles sur 6 — simule une séance interrompue — headless, aucune écriture dans le
vrai `data/`) :

Vert (le code livré) :
```
[cvep-cal] 18 cycles sur 3 cibles jugées (hasard 33%) :
```
Rouge (`chance = 100.0 / len(plan)`) :
```
[cvep-cal] 18 cycles sur 3 cibles jugées (hasard 17%) :
```
Exactement le chiffre gonflé que la revue avait signalé. Mutation retirée → 33 % de nouveau.

## Réserve C2 — fermée : `archive/cvep_rcca_pilot.py` n'a plus de chemin de production dangereux

`calibrate_rcca(app, cycles=None, save_path=None)` : `save_path = save_path or
chemin_modele_horodate("rCCA")` (import de `research.cvep_calibrate`, même patron que
`cvep_calibrate.calibrate`). `--model` par défaut `None` : résolu en HORODATÉ pour `--calibrate`
sans override, en `CVEP_RCCA_MODEL_PATH` seulement pour piloter un modèle déjà là (lecture, pas un
danger).

**Preuve, en processus isolé, chemins redirigés vers un dossier FAUX** (jamais le vrai `data/`) :
appel direct à `calibrate_rcca(app, save_path=None)`.

Vert (le code livré) — le dossier FAUX contient un fichier HORODATÉ, jamais le nom fixe :
```
fichier au nom FIXE (cvep_rcca_model.npz) présent : False
fichier(s) HORODATÉ(S) présents : ['cvep_rcca_model_20260821-133530.npz']
VERT : calibrate_rcca(save_path=None) a écrit un nom HORODATÉ, jamais le nom fixe
```
Rouge (`save_path = save_path or CVEP_RCCA_MODEL_PATH`) — le nom fixe réapparaît :
```
fichier au nom FIXE (cvep_rcca_model.npz) présent : True
fichier(s) HORODATÉ(S) présents : []
ROUGE : calibrate_rcca(save_path=None) a écrit sur le nom FIXE
```
Mutation retirée → vert de nouveau.

## La casse nouvelle (TypeError) — fermée, et une DEUXIÈME casse trouvée en la fermant

`n_cibles` et `corrects` sont maintenant `None` quand `n_decisions == 0` (au lieu de retomber sur
`len(presentes)`, un chiffre d'apparence normale sur du vide). `calibrate()` ferme ce chemin
explicitement, AVANT tout calcul : message clair, modèles sauvegardés quand même (le classifieur
existe, seule la justesse à cette géométrie manque), écran dédié, `return False, res`.

⚠️ **En écrivant le test du cas vide, la première version de ce correctif (`sc.ndim > 1`) a
elle-même échoué** — sur `rCCA`, avec `n_cibles = 6` au lieu de `None`. Cause : `CVEPModel.hors_pli`
rend un tableau vide en **1** dimension (`np.asarray([])`, `shape (0,)`) mais `RCCAModel.hors_pli`
rend un tableau vide en **2** dimensions (`_hors_pli` PRÉ-ALLOUE `np.zeros((len(groupes),
n_targets))` avant sa boucle : la largeur `n_targets` survit même à zéro ligne). Corrigé en testant
`len(sc) == 0` (le nombre de LIGNES, identique dans les deux cas) plutôt que `.ndim`. Trouvé par le
test lui-même, avant tout retour à la revue — la preuve que la revue demande (« ferme le chemin à
zéro décision ») aurait autrement échoué UNE SEULE FOIS sur les deux décodeurs.

**Preuve intégration** (le VRAI `calibrate()`, `_make_blocks` monkey-patché pour alterner les 6
cibles une par une sur 2 tours — aucune paire consécutive possible, quel que soit le mélange —
headless, aucune écriture dans le vrai `data/`) :

Vert (le code livré) :
```
[cvep-cal] 12 cycles enregistrés, mais AUCUNE décision à la géométrie du moteur (2 cycles) —
           trop peu de cycles consécutifs de la même cible pour en former une seule. Les modèles
           sont sauvegardés [...], mais aucune justesse fiable ne les accompagne : recalibre [...]
PAS DE CRASH -- ok = False
eCCA : 0 décisions, justesse = None n_cibles = None
rCCA : 0 décisions, justesse = None n_cibles = None
```
Rouge (garde désactivé, `if False:` à la place du test) :
```
TypeError (le bug du tour 2) : unsupported operand type(s) for /: 'float' and 'NoneType'
  File "...cvep_calibrate.py", line 579, in calibrate
    chance = 100.0 / n_cibles
TypeError: unsupported operand type(s) for /: 'float' and 'NoneType'
```
Mutation retirée → plus de crash.

## Le garde `empreinte_dossier` — les deux observations traitées

1. **Branché dans `archive/mi_calibrate.py` et `archive/mi_pilot.py`** — le couple qui a coûté
   quatre modèles au projet. Les deux `__main__` snapshottent `data/` avant `--smoke`, et
   comparent après. `_train_and_save`/`pilot` sautaient déjà leur sauvegarde en smoke (rien
   n'écrivait AVANT ce tour non plus), mais rien ne le PROUVAIT — exactement la garantie
   implicite qui a cédé une fois. Pris au passage : ni l'un ni l'autre ne faisait `sys.exit()`
   selon le résultat de `calibrate()`/`pilot()` (toujours 0, quoi qu'il arrive) ; les deux
   sortent maintenant `0`/`1` correctement, sur le même geste que la ligne du garde.
2. **La limite du garde est écrite dans sa docstring** (`core/config.py::empreinte_dossier`) :
   aveugle à un créer-puis-effacer DANS la fenêtre de mesure — le cas mesuré par la revue sur
   `server.py --smoke` et `data/mi_model_smoke.joblib`. `archive/README.md` le redit en une phrase,
   à l'endroit où un lecteur croiserait la liste des quatre fichiers gardés.

## Autotests (tour de correction 2)

| Commande | Résultat |
|---|---|
| `python src/research/cvep_calibrate.py` | 36/36 OK, exit 0 |
| `python src/research/app.py --smoke` | OK, exit 0 |
| `python src/core/server.py --smoke` (non-régression) | 17 sections OK, exit 0 |
| `python archive/cvep_pilot.py --smoke` | OK, exit 0 |
| `python archive/cvep_rcca_pilot.py --smoke` | OK, exit 0 |
| `python archive/mi_calibrate.py --smoke` | OK, exit 0 (garde `empreinte_dossier` branché) |
| `python archive/mi_pilot.py --smoke` | OK, exit 0 (garde `empreinte_dossier` branché) |
| `python src/research/cvep_rcca.py` / `src/core/cvep_decoder.py` / `cvep_rcca.py` / `cvep_models.py` / `config.py` (non-régression) | OK, exit 0 chacun |
| `python src/console/app.py --smoke` (non-régression) | OK, exit 0 |

`data/` vérifié intact par empreinte (43 fichiers, taille+mtime) avant/après CHAQUE commande à
risque, y compris les quatre preuves d'intégration menées en processus isolé sur des chemins
redirigés (jamais le vrai `data/`).

## Doutes (tour de correction 2)

1. **`SEUIL_MCNEMAR = 0,05` est le seuil usuel, pas un choix motivé par CE dépôt.** À 8 décisions
   discordantes (le cas réel), il faudrait un déséquilibre proche de 0/8 ou 8/0 pour passer sous ce
   seuil — McNemar est intrinsèquement peu puissant à si peu de décisions. C'est la réponse honnête
   (« pas assez de décisions pour trancher »), mais ça veut dire qu'une vraie différence modeste
   entre les deux décodeurs resterait invisible tant que les séances ne durent pas plus longtemps.
2. **Aucune correction de continuité (Yates) n'est appliquée.** Le calcul est le test binomial EXACT
   (pas l'approximation chi-carré que `mcnemar.test()` de R utilise par défaut), donc la question
   ne se pose normalement pas — mais je ne l'ai vérifié que par comparaison à la valeur donnée par
   la revue (0,727), pas contre une bibliothèque de référence installée sur ce poste (`scipy.stats`
   n'a pas été appelé pour comparer, seulement cité comme référence dans le commentaire).
3. **La divergence `ndim` vs `len()` entre `CVEPModel.hors_pli` et `RCCAModel.hors_pli`** (trouvée
   en écrivant le test du cas vide) n'est corrigée que côté APPELANT (`entraine_les_deux`) — les
   deux fonctions `hors_pli` elles-mêmes gardent chacune leur forme de tableau vide. Un futur appelant
   qui ferait `sc.ndim > 1` directement (au lieu de `len(sc) > 0`) reproduirait le même défaut. Je
   ne les ai pas touchées (fichiers de la tâche 3, hors du périmètre demandé), mais le risque reste
   ouvert ailleurs dans le dépôt si quelqu'un écrit ce test différemment.
4. **La preuve d'intégration du garde `empreinte_dossier` sur `mi_calibrate.py`/`mi_pilot.py`
   n'a pas été refaite en mutation** (contrairement au garde c-VEP du tour 1) : les deux fichiers
   ne changent aucun comportement d'écriture existant, seulement l'observation — j'ai fait
   confiance à la preuve DÉJÀ FAITE au tour 1 sur le mécanisme identique (`archive/cvep_pilot.py`)
   plutôt que de la répéter mot pour mot sur MI.

---

# Tour de correction 3 (dernier sur cette tâche)

**Constat de la re-revue : les cinq points sont corrects dans le code, mais trois n'étaient
protégés par RIEN.** Mes preuves des tours 1 et 2 s'appuyaient sur des scripts de démonstration
jetables (mon scratchpad), jamais intégrées à la suite de tests réelle — donc invisibles à
quiconque relance `python src/research/cvep_calibrate.py` ou `archive/cvep_rcca_pilot.py --smoke`
après moi. Ce tour ajoute un test PERMANENT par cas, chacun exerçant `calibrate()` ou
`calibrate_rcca()` par le chemin que le smoke normal n'atteint jamais — et chacun prouvé
rouge-puis-vert via la VRAIE commande de test, pas un script à part.

## Cas 1 — le hasard/l'ITR sur une séance TRONQUÉE (réserve C1)

Nouveau bloc dans `_selftest()` : une VRAIE `App(smoke=True)`, `_make_blocks` détourné (module
courant, `sys.modules[__name__]._make_blocks`) pour ne produire des blocs que pour 3 cibles sur 6,
`calibrate()` appelée pour de vrai avec sa sortie CAPTURÉE (`contextlib.redirect_stdout`), et le
« hasard NN% » imprimé extrait par regex.

**Preuve rouge**, via `python src/research/cvep_calibrate.py` (pas un script à part) — mutation
`chance = 100.0 / n_cibles` → `chance = 100.0 / len(plan)` :
```
ÉCHEC ...et le HASARD IMPRIMÉ par calibrate() suit n_cibles=3 (33 %), jamais len(plan)=6 (17 %)
      — sinon l'ITR et le verdict affichés à l'étudiant resteraient gonflés sur EXACTEMENT la
      séance que Critical 1 visait ('hasard 17%')
[cvep-calibrate] VERDICT : PROBLÈME
EXIT=1
```
**Vert** : mutation retirée, 40/40 OK, exit 0.

## Cas 2 — la séance à ZÉRO décision ne doit pas planter (la casse TypeError du tour 2)

Même infrastructure (`_make_blocks` détourné pour alterner les 6 cibles une par une sur 2 tours —
aucune paire consécutive possible, quel que soit le mélange), dans le MÊME bloc de `_selftest()`.

**Preuve rouge**, via `python src/research/cvep_calibrate.py` — garde remplacé par `if False:` :
```
Traceback (most recent call last):
  File ".../cvep_calibrate.py", line 937, in _selftest
    ok2, res2 = calibrate(app_int, save_path=...)
  File ".../cvep_calibrate.py", line 579, in calibrate
    chance = 100.0 / n_cibles
TypeError: unsupported operand type(s) for /: 'float' and 'NoneType'
EXIT=1
```
Le TypeError EXACT que le tour 2 avait trouvé, reproduit par la suite de tests elle-même — pas
par un harnais externe. **Vert** : garde restauré, 40/40 OK, exit 0.

## Cas 3 — le repli de `calibrate_rcca` LUI-MÊME (réserve C2)

Ajouté dans `archive/cvep_rcca_pilot.py::main()`, à l'intérieur du bloc `--smoke` : après l'appel
normal (`save_path` explicite), un second appel `calibrate_rcca(app, save_path=None)` — LE REPLI,
jamais exercé par le premier — avec les chemins fixes détournés vers le MÊME dossier temporaire.

⚠️ **Incident en écrivant la preuve rouge, corrigé avant de rendre.** Ma première mutation
(`save_path = save_path or CVEP_RCCA_MODEL_PATH`) a RÉELLEMENT écrasé `data/cvep_rcca_model.npz`
une seconde fois : `CVEP_RCCA_MODEL_PATH` est importé indépendamment dans DEUX modules
(`archive/cvep_rcca_pilot.py` et `research/cvep_calibrate.py`, tous deux `from core.config import
...`) — deux liaisons de nom séparées vers la même valeur d'origine. Mon détournement d'origine ne
patchait que la copie lue par le code NON MUTÉ (`research.cvep_calibrate`, via
`chemin_modele_horodate`) ; la mutation, elle, lisait la copie locale à `archive/cvep_rcca_pilot.py`,
non patchée. Repéré à la première exécution (empreinte `data/` vérifiée après CHAQUE commande, par
discipline) :
```
data/cvep_rcca_model.npz: modified 41s ago  <<< RECENT
```
**Récupéré exactement comme au tour 1** : ré-ajusté depuis `data/cvep_rcca_calib_20260721-161305_
n6.npz` (le fichier source déjà identifié), `cv_` retrouvé = 0,35555… = 35,6 %, comportement de
refus (codes Gold) reconfirmé identique. Le test PERMANENT lui-même a été corrigé pour détourner
LES DEUX liaisons de nom (`research.cvep_calibrate.CVEP_RCCA_MODEL_PATH` **et**
`sys.modules[__name__].CVEP_RCCA_MODEL_PATH`) avant d'appeler le repli — défense en profondeur,
pas un correctif pour une seule mutation. Rejoué ensuite : `data/` intact, vérifié par empreinte
avant ET après.

**Preuve rouge**, via `python archive/cvep_rcca_pilot.py --smoke` (avec les deux détournements en
place, donc SANS risque pour le vrai `data/` cette fois) — mutation `save_path = save_path or
chemin_modele_horodate("rCCA")` → `save_path = save_path or CVEP_RCCA_MODEL_PATH` :
```
Traceback (most recent call last):
  File "archive\cvep_rcca_pilot.py", line 304, in main
    assert "cvep_rcca_model.npz" not in nouveaux_repli, (
AssertionError: calibrate_rcca(save_path=None) a écrit sur le nom FIXE — le repli n'est plus
horodaté ({'cvep_rcca_model.npz'})
EXIT=1
```
`data/` vérifié intact (empreinte avant/après identique) MALGRÉ la mutation, cette fois — la
défense en profondeur a tenu. **Vert** : mutation retirée, `exit=0`.

## La divergence `ndim`/`len()` — écrite en commentaire, pas seulement corrigée

Le commentaire à l'endroit du contournement (`entraine_les_deux`, juste avant `n_cibles_e = ...`)
dit maintenant explicitement : la divergence entre `CVEPModel.hors_pli` (`(0,)`) et
`RCCAModel._hors_pli` (`(0, n_targets)`, pré-alloué) sur une entrée vide est **permanente**, pas
un accident corrigé ailleurs ; les deux fichiers de `core/` n'ont pas été touchés (hors périmètre) ;
et l'alignement des deux `hors_pli` est une décision **explicitement renvoyée à la revue finale de
branche** — le commentaire porte cette phrase telle quelle.

## Autotests (tour de correction 3)

| Commande | Résultat |
|---|---|
| `python src/research/cvep_calibrate.py` | 40/40 OK, exit 0 |
| `python src/research/app.py --smoke` | OK, exit 0 |
| `python src/core/server.py --smoke` (non-régression) | 17 sections OK, exit 0 |
| `python archive/cvep_pilot.py --smoke` | OK, exit 0 |
| `python archive/cvep_rcca_pilot.py --smoke` | OK, exit 0 (repli exercé À CHAQUE lancement désormais) |
| `python archive/mi_calibrate.py --smoke` / `mi_pilot.py --smoke` | OK, exit 0 chacun |
| `python src/research/cvep_rcca.py` / `src/core/cvep_decoder.py` / `cvep_rcca.py` / `cvep_models.py` / `config.py` (non-régression) | OK, exit 0 chacun |
| `python src/console/app.py --smoke` (non-régression) | OK, exit 0 |

`data/` vérifié intact par empreinte (43 fichiers, taille+mtime) avant/après CHAQUE commande à
risque — y compris, cette fois, la mutation de la preuve n°3, qui aurait échoué SANS la défense en
profondeur ajoutée après l'incident. Un processus python orphelin (issu d'un lot de commandes
ayant dépassé le délai de l'outil) a été repéré et arrêté avant de reprendre les tests, conforme à
la règle « aucun moteur ne doit tourner pendant un test ».

## Doutes (tour de correction 3)

1. **Les nouveaux tests d'intégration (cas 1 et 2) alourdissent sensiblement `_selftest()`** :
   chaque scénario ouvre une VRAIE `App(smoke=True)` et rejoue une boucle d'enregistrement
   complète. `python src/research/cvep_calibrate.py` reste rapide (quelques secondes), mais c'est
   maintenant le plus lourd des autotests de ce fichier, et il dépend de pygame là où le reste du
   fichier n'en avait jamais eu besoin.
2. **Le détournement de `_make_blocks` est un monkeypatch du module courant**
   (`sys.modules[__name__]._make_blocks = ...`), restauré dans un `finally` — je ne l'ai vu utilisé
   nulle part ailleurs dans ce dépôt sous cette forme précise. Ça fonctionne et c'est prouvé rouge-
   puis-vert, mais c'est un style d'injection plus intrusif que le reste des tests de ce fichier,
   qui construisent des fixtures plutôt que de repeindre des fonctions du module en place.
3. **L'incident de cette section n'aurait pas été évité par une relecture attentive de MA PROPRE
   mutation** — je l'ai écrite en pensant reproduire fidèlement l'ancien défaut sans revérifier
   QUELLE liaison de nom le code lirait réellement. La leçon que j'en tire (détourner TOUTES les
   liaisons connues d'une constante avant d'en muter le point de lecture, jamais une seule) n'est
   écrite nulle part ailleurs dans ce dépôt : un futur test du même genre, sur une autre constante
   à deux copies, peut reproduire l'erreur si personne ne se souvient de celle-ci.
