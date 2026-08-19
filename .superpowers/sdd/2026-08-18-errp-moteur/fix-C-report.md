# Tranche C — correction des constatations de la revue finale

Périmètre autorisé : `src/console/live_views.py`, `src/console/grid.py`, `src/console/app.py`,
`src/core/server.py`, `src/core/lsl_io.py`, `src/core/modes/registry.py`,
`src/core/modes/external.py`.

Fichiers réellement modifiés : **5** — `console/app.py`, `console/grid.py`,
`console/live_views.py`, `core/lsl_io.py`, `core/server.py`.
`registry.py` et `external.py` n'avaient besoin d'aucune retouche (`external.py` a servi de
support à une mutation temporaire, restauré à l'octet près par `git checkout --`).

**Bilan : 1 Critical + 6 Important + 2 Minor corrigés · 3 Minor reportés** (M3 et M4 corrigés
partiellement, la part restante étant hors périmètre).

Aucun test n'écrit dans `data/`. L'autotest sort en 1 quand il échoue (vérifié à chaque preuve
rouge ci-dessous). Un seul programme python lancé à la fois, jamais en parallèle.

---

## État de départ (avant toute modification)

```
python src/core/modes/registry.py   → [registry] VERDICT : OK          exit=0
python src/core/lsl_io.py           → [lsl] VERDICT : OK               exit=0
python src/console/app.py --smoke   → [console-smoke] VERDICT : OK     exit=0
python src/core/server.py --smoke   → 17 VERDICT : OK                  exit=0
```

## État d'arrivée

```
python src/core/modes/registry.py   → exit=0
python src/core/lsl_io.py           → exit=0
python src/console/app.py --smoke   → exit=0
python src/core/server.py --smoke   → 17 VERDICT : OK, exit=0
```

Collatéral vérifié (non modifiés, mais consommateurs de `lsl_io.py`) :
`python src/core/modes/errp.py` → OK, `python src/core/modes/p300.py` → OK.

---

## Les trois dettes inter-chantiers

### Dette 1 (I1) — la tuile P300 mise à l'échelle sur le `Z_MIN` du SSVEP

**Fichier** : `src/console/grid.py`. La branche `"scores"` de `ModeTile.update_from` est extraite
en `_apercu_scores`, qui choisit son échelle sur **ce que la sortie déclare** :

- `threshold` présent (SSVEP) → échelle ABSOLUE contre ce seuil, comportement inchangé ;
- `threshold` absent (P300, et tout futur mode qui accumule des preuves) → échelle **RELATIVE**,
  normalisée sur `[min, max]` des scores de la manche, `span=1.0`. Exactement ce que
  `ActiveView._update_selection` fait déjà sur la page.

`Z_MIN` n'est **plus importé** dans `grid.py`, avec un commentaire à l'import qui dit pourquoi
il ne doit pas revenir.

Trois assertions nouvelles dans `console/app.py`, sur l'état P300 déjà existant (aucune n'existait
— l'aperçu de la tuile P300 n'était touché par rien) :

```
OK   la tuile P300 n'emprunte PAS le seuil du SSVEP pour mettre des log-odds à l'échelle (span=1.0, Z_MIN=2.5)
OK   ...elle montre le CLASSEMENT, comme la page : la cible qui domine pleine, la plus faible vide — et AUCUNE écrasée à zéro parce qu'elle est négative ([0.2525…, 0.0, 0.6060…, 1.0, 0.2020…, 0.4545…])
OK   ...et met en avant la cible que le MOTEUR a retenue, pas un maximum recalculé (3)
OK   et la tuile SSVEP garde son échelle absolue, contre le seuil qu'elle PUBLIE (2.5)
```

La dernière est le garde-fou symétrique : sans elle, « ne plus jamais utiliser de seuil » passerait
aussi.

**Preuve rouge** — mutation d'une ligne, le repli d'avant le correctif
(`seuil = sortie.get("threshold", 2.5)`) :

```
  ÉCHEC la tuile P300 n'emprunte PAS le seuil du SSVEP pour mettre des log-odds à l'échelle (span=2.5, Z_MIN=2.5)
  ÉCHEC ...elle montre le CLASSEMENT, comme la page : la cible qui domine pleine, la plus faible vide — et AUCUNE écrasée à zéro parce qu'elle est négative ([-1.9, -2.4, -1.2, -0.42, -2.0, -1.5])
[console-smoke] VERDICT : PROBLÈME
=== exit=1 ===
```

Mutation retirée, relance : `[console-smoke] VERDICT : OK`, exit=0.

### Dette 2 (I2) — `_smoke_frontiere` aveugle à Qt

**Fichier** : `src/core/server.py`. Motif élargi :

```python
interdits = re.compile(
    r"^\s*(?:from|import)\s+(research|console|pygame|PySide\d|PyQt\d|qtpy|pyqtgraph)\b",
    re.MULTILINE)
```

Docstring corrigée (elle promettait déjà Qt sans le vérifier), et le compromis assumé du test par
expression régulière (import dynamique ou relatif) y est désormais écrit, comme le suggérait la
note secondaire de la constatation.

**Preuve rouge** — `import PySide6`, `from PyQt5 import QtCore`, `import pyqtgraph as pg` et
`import qtpy` ajoutés temporairement dans `src/core/modes/external.py` (dans une fonction jamais
appelée : le test lit le TEXTE, rien n'est exécuté) :

```
[smoke] VERDICT : OK
[smoke-frontiere] ÉCHEC : core/modes\external.py importe PySide6
[smoke-frontiere] ÉCHEC : core/modes\external.py importe PyQt5
[smoke-frontiere] ÉCHEC : core/modes\external.py importe pyqtgraph
[smoke-frontiere] ÉCHEC : core/modes\external.py importe qtpy
[smoke-frontiere] 4 violation(s) de frontière
[smoke-frontiere] VERDICT : PROBLÈME
=== exit=1 ===
```

Et la démonstration que l'ANCIEN motif ne voyait rien de tout ça, sur ce même fichier muté :

```
ancien motif : []
nouveau motif: ['PySide6', 'PyQt5', 'pyqtgraph', 'qtpy']
```

Mutation retirée (`git checkout -- src/core/modes/external.py`, diff vide), relance :
`[smoke-frontiere] 0 violation(s) de frontière · VERDICT : OK`, exit=0. Rien dans `core/`
n'importe Qt aujourd'hui, comme annoncé.

### Dette 3 (I3) — `[smoke-tampon]` instable depuis cinq tâches

**Décision : le test ne devient pas plus permissif, il change d'objet.** Sa tolérance n'a pas été
élargie d'un iota — elle a été RESSERRÉE d'un facteur ~400 (de « entre 0,5×/fs et 2×/fs » à
« 1/fs à 10 µs près »), ce qui n'est possible que parce que le test ne juge plus le producteur.

Ce qui rendait ce test dépendant de l'ordonnanceur — l'ouverture d'une session BrainFlow et la
lecture des échantillons — est remplacé par `_AcqDeterministe`, un producteur qui délègue TOUT à
la vraie `UnicornAcquisition` (`fs`, `window_n`, `margin_n`, `sigma_from_block`, `common_mode`…)
sauf `__enter__`/`__exit__` et `get_new_data`. Il rend 13 échantillons par tour, horodatés
contigus à 1/fs pile. Chaque assertion redevient alors une question sur `server.py` :

| assertion | ce qu'elle juge maintenant |
|---|---|
| mêmes longueurs | l'appariement des deux tampons |
| `len == min(produits, keep)` | la troncature `[-keep:]`, et rien n'a été perdu en route |
| `np.all(diffs > 0)` | la concaténation empile la queue APRÈS la tête |
| cadence médiane == 1/fs à 10 µs | `server.py` **recopie** les horodatages, il n'en régénère pas |
| `new_block is not None` | **garanti** : chaque tour rend des échantillons (la seconde course est fermée) |
| queue de `recent`/`recent_ts` == dernier bloc | l'ALIGNEMENT — l'assertion qui a toujours eu de la valeur |

Aucune seconde de temps mural n'entre plus dans un verdict, et la durée du test passe de 3,0 s à
0,4 s. Ce que ce test ne couvre PLUS (écrit dans sa docstring) : l'intégration avec le vrai board
BrainFlow, couverte par `_smoke`, `_smoke_ssvep`, `_smoke_mi`… qui font tourner de vrais
`EngineServer` synthétiques, et le contrat de `get_new_data` lui-même, couvert par
`python src/core/acquisition.py --synthetic`.

La seconde course (`new_block` remis à `None` à chaque tour) est fermée **côté test**, pas côté
production : mémoriser le dernier bloc NON VIDE dans `server.py` aurait été un vrai bug —
`modes/raw.py` lit `engine.new_block` à chaque tick et le publie, il republierait le même bloc en
boucle.

Sortie verte :

```
[smoke-tampon] producteur DÉTERMINISTE (13 échantillons par tour, 1/fs = 4.00 ms) — aucune session BrainFlow n'est ouverte ici
  OK   les deux tampons ont la même longueur (104 et 104)
  OK   et ils portent tout ce que le producteur a rendu, borné à `keep` (104 pour 104 produits, keep=1250)
  OK   le temps avance strictement, sans doublon ni retour en arrière — la concaténation empile bien la queue APRÈS la tête
  OK   et la cadence RECOPIÉE vaut exactement celle du producteur, à 0.051 µs près (3.9999 ms pour 4.0000 ms fournis)
  OK   le dernier tour de boucle a bien lu un bloc — désormais GARANTI…
  OK   ce bloc (13 échantillons) tient dans le tampon (104)
  OK   la QUEUE de `recent` est exactement le dernier bloc lu, valeur pour valeur (13 échantillons)
  OK   ...et la queue de `recent_ts` est exactement les horodatages de CE bloc (écart max 0.0000 ms)
[smoke-tampon] VERDICT : OK
```

**Preuve rouge n°1** — la mutation historique, celle que ce test existe pour attraper
(`np.concatenate([self.recent_ts, ts_lsl + 1.0 / self.acq.fs])`) :

```
  OK   et la cadence RECOPIÉE vaut exactement celle du producteur, à 0.051 µs près (3.9999 ms pour 4.0000 ms fournis)
  ÉCHEC ...et la queue de `recent_ts` est exactement les horodatages de CE bloc — c'est l'assertion qui rougit sur un décalage d'un seul échantillon (écart max 4.0000 ms)
[smoke-tampon] VERDICT : PROBLÈME
=== exit=1 ===
```

**Preuve rouge n°2** — que l'assertion de cadence n'est PAS du poids mort, maintenant qu'elle juge
`server.py` : régénérer l'axe des temps au lieu de recopier celui du producteur
(`ts_lsl = clock.to_lsl(ts_unix[0]) + arange(len(eeg)) / (fs / 2)`) :

```
  ÉCHEC le temps avance strictement, sans doublon ni retour en arrière — la concaténation empile bien la queue APRÈS la tête
  ÉCHEC et la cadence RECOPIÉE vaut exactement celle du producteur, à 4000.001 µs près (8.0000 ms pour 4.0000 ms fournis)
  OK   ...et la queue de `recent_ts` est exactement les horodatages de CE bloc (écart max 0.0000 ms)
[smoke-tampon] VERDICT : PROBLÈME
=== exit=1 ===
```

Cette mutation-là passe INAPERÇUE de l'assertion d'alignement (`new_block` porte le même tableau
muté) : les deux assertions attrapent des fautes disjointes, ce qui est la justification de garder
la seconde.

Les deux mutations retirées, relance : `[smoke-tampon] VERDICT : OK`, exit=0.

---

## CRITICAL

### C1 — la page ErrP affichait l'avertissement du NEURO tant qu'aucun feedback n'était décodé

**Fichier** : `src/console/live_views.py`. Variante propre retenue (celle que la constatation
elle-même recommande) : **aucun routage sur l'identifiant du mode**.

- deux constantes de module, `AVERTISSEMENT_Z` et `AVERTISSEMENT_ATTENTE` ;
- `PassiveView.__init__` construit le label **vide** ;
- la branche `not z` (mode démarré, rien de décodé) pose `AVERTISSEMENT_ATTENTE`, qui n'affirme
  AUCUNE unité ;
- la branche qui rend des z pose `AVERTISSEMENT_Z` — le texte appartient à la branche qui a mesuré
  la valeur.

Docstring de `PassiveView` corrigée : elle affirmait « l'échelle est un z », ce qui n'a jamais été
vrai des deux formes de sortie qu'elle rend.

Nouvel état de test dans `console/app.py` : `errp` démarré avec `output: None`, l'état dans lequel
la page vit ses 23 premières secondes et qu'aucun état du smoke ne construisait.

```
OK   avant le premier feedback, la page ErrP ne parle JAMAIS d'un z contre le repos du jour — c'est l'unité d'un AUTRE mode ("aucune sortie décodée pour l'instant : l'unité et l'échelle de ce mode s'affichent avec le premier échantillon, jamais avant.")
```

**Preuve rouge** — mutation d'une ligne (la branche `not z` repose le texte du neuro, comme avant) :

```
  ÉCHEC avant le premier feedback, la page ErrP ne parle JAMAIS d'un z contre le repos du jour — c'est l'unité d'un AUTRE mode ('z contre TON repos du jour, mesuré au démarrage du mode. Ni comparable entre personnes, ni entre séances, ni absolu. À lire en TENDANCE.')
[console-smoke] VERDICT : PROBLÈME
=== exit=1 ===
```

Mutation retirée, relance : OK, exit=0.

---

## IMPORTANT (I4 à I6 ; I1-I3 traités ci-dessus)

### I4 — le nom du flux `decoded_errp` écrit deux fois, sans rien pour les lier

**Fichier** : `src/core/lsl_io.py`.

1. `DecodedErrPPublisher.SUFFIXE = "decoded_errp"`, utilisé par `StreamInfo` et `_source_id`,
   comme `DecodedP300Publisher` le fait déjà.
2. Surtout : l'autotest §8bis compare le nom que **l'outlet publie réellement**
   (`pub_errp.outlet.get_info().name()`) à celui que le **contrat du mode annonce**
   (`stream_name(registry.get("errp").stream)`). C'est plus fort qu'une égalité de constantes :
   n'importe lequel des deux côtés fait rougir, y compris le côté que je n'ai pas le droit de
   modifier.

```
  decoded_errp nom publié='EEG_API_Unicorn_decoded_errp' · annoncé par le ModeSpec='EEG_API_Unicorn_decoded_errp'
```

**Preuve rouge** — `SUFFIXE = "decoded_errp_v2"` :

```
AssertionError: le flux publié ('EEG_API_Unicorn_decoded_errp_v2') et celui que le contrat du mode
annonce ('EEG_API_Unicorn_decoded_errp') ont divergé — un client s'abonnerait dans le vide
=== exit=1 ===
```

Mutation retirée, relance : `[lsl] VERDICT : OK`, exit=0.

**Dépendance hors périmètre** : `src/core/modes/errp.py:679` porte encore son propre littéral
`stream="decoded_errp"`, et son autotest compare un littéral à un littéral. La ligne à écrire est
`stream=DecodedErrPPublisher.SUFFIXE` (plus l'import). Le trou est refermé par l'assertion
ci-dessus quoi qu'il arrive, mais la source unique n'existera qu'après cette ligne.

### I5 — le point de fonctionnement du fixture console

**Fichier** : `src/console/app.py`.

(a) Fixture aligné sur **la seule mesure réelle du projet** : `tpr: 0.500`, `tnr: 0.855`
(`tnr_target = 0.85`), au lieu de 0,4615 / 0,9259 (= 6/13 et 25/27, ratios de très petit effectif).
Le mot « mesuré » a disparu du commentaire, remplacé par le renvoi à la séance de référence et par
l'explication du défaut. L'affichage devient donc « garde **86%** … attrape **50%** … visé **85%** »
— trois nombres distincts, ce qui rend les assertions ancrées réellement discriminantes.

(b) Assertions ancrées **chaque taux à son libellé**, plus une troisième sur le taux visé :

```
OK   ...ET le point de fonctionnement MESURÉ (pas seulement visé), chaque taux CÔTÉ SON LIBELLÉ : « garde 86% des bonnes commandes » / « attrape 50% des erreurs » — un échange tpr↔tnr doit rougir ICI
OK   ...et le taux VISÉ reste distinct des deux mesurés
```

Le résumé de tuile passe de `"46%"` à `"attrape 50%"` (ancré lui aussi).

**Preuve rouge** — la mutation que l'ancienne assertion laissait VERTE : échanger `tpr` et `tnr`
dans `live_views._update_errp` :

```
  ÉCHEC ...ET le point de fonctionnement MESURÉ (pas seulement visé), chaque taux CÔTÉ SON LIBELLÉ … ('score +5.044 contre seuil +0.044 · détecteur IMPARFAIT : garde 50% des bonnes commandes, attrape 86% des erreurs (visé 85%) — un verdict « erreur » est une pièce biaisée, pas une certitude.')
[console-smoke] VERDICT : PROBLÈME
=== exit=1 ===
```

Mutation retirée, relance : OK, exit=0.

### I6 — `taux_rejet` / `epoques_vues` / `artefacts` calculés pour un client qui ne les lisait pas

**Fichier** : `src/console/live_views.py`, nouvelle `PassiveView._sante`, ajoutée en queue des
**trois** branches de l'avertissement ErrP (`error < 0`, avec `pdf`, sans `pdf`).

Choix de rendu : la **fraction est affichée à côté du pourcentage**. Un plancher d'effectif
(comme `_TAUX_REJET_MIN_ECHANTILLONS = 10` côté moteur) aurait été de la logique du moteur
recopiée dans l'interface ; « 100 % (1/1) » se lit tout seul pour ce que ça vaut, là où « 100 % »
seul alarmerait pour rien. Le plancher du moteur décide quand ALARMER — ce n'est pas la même
question qu'informer.

```
OK   un sur-rejet d'artefact se VOIT sur la page, taux ET effectif — sans quoi 36 refus de suite ressemblent à 36 clignements ('aucune mesure sur ce feedback : époque perdue ou rejetée, score et seuil ne comptent pas ici. · rejet artefact 90% (36/40 époques de ce repos)')
```

**Preuve rouge** — `_sante` renvoie `""` d'emblée :

```
  ÉCHEC un sur-rejet d'artefact se VOIT sur la page, taux ET effectif … ('aucune mesure sur ce feedback : époque perdue ou rejetée, score et seuil ne comptent pas ici.')
[console-smoke] VERDICT : PROBLÈME
=== exit=1 ===
```

Mutation retirée, relance : OK, exit=0.

*(Le même trou existe pour le P300, comme le note la constatation. Non traité : `p300.py` est hors
périmètre pour la production des compteurs, et le faire côté console seulement dupliquerait la
question sans la fermer.)*

---

## MINOR

### M1 — corrigé (assertion) + reporté (rendu)

**Corrigé** : `_span` de la tuile ErrP est désormais lu par une assertion. C'était le point que le
commentaire de `grid.py` présente comme important et que rien ne vérifiait.

```
OK   ...sur SA PROPRE amplitude, jamais l'échelle de z du neuro ni un axe fixe inventé (span=5.044, NEURO_Z_SPAN=3)
```

**Preuve rouge** — `span=NEURO_Z_SPAN`, la mutation que la constatation décrit comme restant verte :

```
  ÉCHEC ...sur SA PROPRE amplitude, jamais l'échelle de z du neuro ni un axe fixe inventé (span=3.0, NEURO_Z_SPAN=3)
[console-smoke] VERDICT : PROBLÈME
=== exit=1 ===
```

**Reporté** : le second point (le seuil rendu comme une barre invisible à 0,9 % de la demi-hauteur).
La suggestion `max(abs(score), 4 * abs(seuil), 1.0)` ne change rien sur l'exemple cité
(`max(5.044, 0.176, 1.0)` vaut toujours 5,044) ; le vrai correctif est d'afficher le seuil comme
une LIGNE, ce qui demande un mode de dessin supplémentaire dans `MiniBars`. Non bloquant : la
tuile porte déjà le verdict et le score chiffrés dans son résumé, et la page donne les deux
nombres.

### M2 — corrigé

`pdf.get('tpr', 0.0)` dans `_resume`. **Preuve rouge** : avec `pdf['tpr']` restauré et un
`point_de_fonctionnement` amputé de `tpr`, l'exception remonte bien jusqu'à `ModeGrid.update_from`
— donc toute la grille, comme la constatation l'annonçait :

```
  File "…\src\console\app.py", line 122, in apply_state
    self.grid.update_from(state)
  File "…\src\console\grid.py", line 298, in update_from
    tuile.update_from(etats.get(mode_id))
  File "…\src\console\grid.py", line 266, in _resume
    taux = f" · attrape {pdf['tpr']:.0%} des erreurs" if pdf else ""
KeyError: 'tpr'
=== exit=1 ===
```

Mutation retirée, relance : OK, exit=0.

### M3 — corrigé (le contrat publié)

`measured_on` dit maintenant ce qui rend `tpr_measured`/`tnr_measured` optimistes :
`"1 person; threshold picked on these same out-of-fold scores, so tpr/tnr are optimistic"`,
avec le mécanisme (`pick_threshold` maximise la TPR parmi les seuils qui atteignent la cible, sur
ces mêmes scores) écrit en commentaire au-dessus du champ. Assertion ajoutée à l'autotest §8.

**Preuve rouge** — retour à `"1 person, 1 session"` :

```
AssertionError: measured_on doit dire que le seuil est choisi sur ces mêmes scores : '1 person, 1 session'
=== exit=1 ===
```

Le calcul lui-même (un seuil choisi sur un pli imbriqué) reste hors sujet ici, comme la
constatation le dit — c'est la tranche B.

### M4 — corrigé partiellement, la part restante hors périmètre

« 1 session » a été retiré : c'était le seul champ du point de fonctionnement à ne dériver de rien,
et un modèle entraîné sur deux séances l'aurait publié sans que rien ne s'en aperçoive. Le rendre
honnête pour de bon (publier `f"{len(np.unique(groups))} block(s)"`) exige que le modèle expose son
nombre de blocs, c'est-à-dire `core/errp_models.py` — **hors périmètre**. La dépendance est écrite
dans le commentaire du champ.

### M5 — reporté

L'extrait « Brancher un client » vit dans `src/core/modes/contract.py`, qui **n'est pas dans mon
périmètre** ; la constatation le classe elle-même « défaut générique, préexistant, à arbitrer hors
de ce chantier ».

---

## Dépendances hors périmètre à remonter

1. **`src/core/modes/errp.py`** (I4) : remplacer `stream="decoded_errp"` par
   `stream=DecodedErrPPublisher.SUFFIXE`, et le littéral de son `_selftest` par la même constante.
   La divergence est déjà attrapée par `lsl_io.py`, mais la source unique n'existe pas encore.
2. **`src/core/errp_models.py`** (M4) : exposer le nombre de blocs de calibration pour que
   `measured_on` cesse d'affirmer un nombre de séances qu'il ne connaît pas.
3. **`src/core/modes/contract.py`** (M5) : une ligne de commentaire dérivée du contrat dans le
   gabarit « Brancher un client », pour tous les modes à `no_decision_index`.
4. **`src/core/modes/p300.py`** (I6, note) : le P300 a le même trou que l'ErrP — ses compteurs de
   santé ne sont exposés nulle part à l'écran.
5. **Observation, non demandée** : l'autotest de `src/core/modes/errp.py` imprime
   `[errp] point de fonctionnement : garde 92.6% … attrape 46.2%`. C'est la source des chiffres
   46 %/93 % qui s'étaient propagés dans le fixture console — un fixture d'autotest, pas une
   affirmation sur le produit, donc bien moins grave, mais c'est de là que ça vient.

---

## Les mutations, récapitulées

| # | fichier | mutation | test qui rougit | exit |
|---|---|---|---|---|
| 1 | `live_views.py` | branche `not z` repose le texte du neuro | C1 | 1 |
| 2 | `live_views.py` | échange `tpr` ↔ `tnr` | I5(b) | 1 |
| 3 | `live_views.py` | `_sante` renvoie `""` | I6 | 1 |
| 4 | `grid.py` | `sortie.get("threshold", 2.5)` | I1 (×2 assertions) | 1 |
| 5 | `grid.py` | `span=NEURO_Z_SPAN` sur l'ErrP | M1 | 1 |
| 6 | `grid.py` | `pdf['tpr']` | M2 (KeyError, grille entière) | 1 |
| 7 | `modes/external.py` | 4 imports Qt (jamais exécutés) | I2 | 1 |
| 8 | `server.py` | `ts_lsl + 1.0 / fs` dans le concat | I3 (alignement) | 1 |
| 9 | `server.py` | axe des temps régénéré à fs/2 | I3 (cadence + monotonie) | 1 |
| 10 | `lsl_io.py` | `SUFFIXE = "decoded_errp_v2"` | I4 | 1 |
| 11 | `lsl_io.py` | `measured_on = "1 person, 1 session"` | M3 | 1 |

Toutes retirées ; les quatre autotests sont verts, exit=0.
