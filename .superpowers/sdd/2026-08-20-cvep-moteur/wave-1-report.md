# Vague finale — lot 1 (le CŒUR) : rapport

Base `b0f857c`. Périmètre tenu : `src/core/modes/cvep.py`, `src/core/lsl_io.py`,
`src/core/modes/contract.py`, `src/core/config.py`, `src/core/server.py`, `src/core/cvep_models.py`,
`src/core/cvep_decoder.py`, `src/console/app.py`, `src/console/grid.py`, `src/console/live_views.py`.
Rien touché ailleurs (`git status` : ces dix fichiers, plus `docs/superpowers/plans/…md` **déjà
modifié avant le lot**, et `.superpowers/sdd/…` non suivi).

**Les 12 points sont traités. Aucun report.**

---

## 1. A-C1 (Critical) — le vote survit à la perte de l'horloge

`modes/cvep.py::_run_step`, branche `phase is None` : `self._votes.clear()`, symétrique de
`_reset_rest`. Règle appliquée telle que tranchée — une fenêtre non décodable pour raison
d'HORLOGE (`sans_reference`, `reference_perimee`) vide les votes ; une référence périmée rend ses
votes périmés par construction.

Test : section **9bis** de `_selftest` — fenêtre franche → fenêtre `reference_perimee` → fenêtre
franche, et la troisième ne peut pas conclure.

**Preuve rouge** (mutation : retirer le `clear`) :

```
ÉCHEC ...une fenêtre non décodable pour raison d'HORLOGE vide la file : la première fenêtre
      d'après le retour de l'émetteur ne peut pas conclure sur des votes d'avant la coupure
      ({'target_index': 2, 'confidence': 0.831, …})
[cvep] VERDICT : PROBLÈME     (exit 1, une seule assertion rouge sur 70)
```

L'échantillon fautif est bien celui que le rapport A décrivait : indice valide, confiance
au-dessus de `corr_min`, indiscernable d'une sélection franche.

## 2. A-I1 — `confidence >= corr_min` sur un réglage à chaud

Arbitrage appliqué : **auto-cohérence par échantillon**. `decide()` capture le couple qu'il vient
d'appliquer au décodeur (`_seuils_decision`) ; `_publish` accepte un argument `seuils` et publie ce
couple sur un échantillon DÉCIDÉ, les seuils VIVANTS sur une fenêtre `-1` (rien n'a été décidé
contre eux, et le chemin `phase is None` ne passe jamais par `decide`).

⚠️ **Écart signalé, et il est nécessaire** : la capture seule ne rétablit pas l'invariant. Si la
file mélange des votes jugés sous deux couples, `confidence` (leur moyenne) peut rester sous le
`corr_min` que la décision courante a utilisé — le scénario du rapport A tombe exactement là. J'ai
donc ajouté la moitié manquante : `_run_step` vide la file quand le couple capturé diffère de
celui sous lequel elle a été constituée (`_seuils_du_vote`). Après quoi la capture EST le couple
qui gouverne tous les votes, et l'arbitrage tient à la lettre. Coût : `vote_len - 1` fenêtres
(0,4 s aux défauts) après chaque réglage.

Test : section **8ter**. Le seuil n'est pas choisi à la main — il est posé entre deux corrélations
RÉELLES (moyenne mélangée 0,783 · fenêtre franche 0,849 → seuil 0,816), et l'assertion balaie tout
le flux publié : aucun échantillon `index >= 0` avec `confidence < corr_min`.

**Preuve rouge** (mutation : retirer le vidage sur changement de couple) :

```
ÉCHEC AUCUN échantillon décidé ne porte une confiance SOUS le `corr_min` qu'il annonce lui-même,
      même après un réglage à chaud ([(2, 0.783058402822619, […], 0.8160607249961256, 0.0, …)])
[cvep] VERDICT : PROBLÈME     (exit 1)
```

→ `confidence = 0,783` publiée à côté de `corr_min = 0,816`, sur la même ligne.

## 3. A-escaladé — la branche rCCA n'avait jamais tourné

* **Section 7ter** intégrée : `RCCAModel` fabriqué, sauvegardé, rechargé **par `cvep_models.charger`
  comme en production**, puis `CVEPRuntime` complet (`_DECODEURS["rCCA"]`, `.corr_min`/`.margin`/
  `.n_cycles`, `model.n_cyc`, `model.channels`, `cv_`). La chaîne décode et publie la cible 2.
  `_modele_temporaire` a dû apprendre les deux signatures de `save` (`RCCAModel.save` ne prend pas
  de `n_targets` : il le DÉDUIT de ses codes).
  Preuve rouge (mutation `_DECODEURS["rCCA"] = CVEPDecoder`) : `ÉCHEC le décodeur suit le MODÈLE…
  (rCCA, CVEPDecoder)` puis **crash** dans `classify` — les deux `scores()` n'ont pas la même
  signature. Avant le bloc, cette mutation ne rougissait rien.
* **Message de refus à `CVEP_LAG_ROTATION != 0`** (`cvep_models.charger`) : il n'accuse plus un
  changement de config. À rotation non nulle il dit que le désaccord d'ORDRE est le cas **attendu
  même sans rien avoir changé** (la calibration écrit par lag croissant, le plan fait tourner). À
  rotation nulle, le texte d'origine est conservé. La cause racine est dans `cvep_calibrate.py`,
  hors périmètre — c'est bien le message seul qui est corrigé, comme demandé.
* **`config.py`** : douze lignes au-dessus de `CVEP_RCCA_CORR_MIN`/`CVEP_RCCA_MARGIN` disant qu'elles
  **ne sont pas lues par le moteur** (`decide` impose le couple réglé, défauts eCCA), pourquoi c'est
  un choix, et où elles servent vraiment (`cvep_rcca.py --seuils`, constructions directes de
  `RCCADecoder`).

## 4. F-C1 (Critical) — use-after-free dans l'autotest de `lsl_io.py`

Les 5 sites lient désormais le `StreamInfo` à une locale (`info_in`, `info_p300`, `info_ssvep`,
`info_errp`, `info_cvep`), sur le motif d'`examples/receiver.py:52-53`, non modifié. La règle est
écrite une fois, en tête : *un `XMLElement` ne possède rien ; le `StreamInfo` dont il vient doit
rester référencé tant qu'on lit dedans.*

**Preuve rouge — la mesure qui tranche** (`junk = [bytes(4096) for _ in range(2000)]` entre la
lecture l.784 et l'assertion), AVANT le fix, 3 exécutions sur 3 :

```
run 1 : exit1     run 2 : exit1     run 3 : exit1
  decoded_ssvep no_decision_index : ''
  AssertionError: no_decision_index manquant (SSVEP)
```

**Contre-épreuve** — même mesure, même allocation, APRÈS le fix, 3 exécutions sur 3 :

```
run 1 : exit=0 :: decoded_ssvep no_decision_index : '-1' | [lsl] VERDICT : OK
run 2 : exit=0 :: decoded_ssvep no_decision_index : '-1' | [lsl] VERDICT : OK
run 3 : exit=0 :: decoded_ssvep no_decision_index : '-1' | [lsl] VERDICT : OK
```

L'échec est donc **systématique** avant et **absent** après : ce n'était pas un test instable.
La mesure a été retirée après vérification. `lsl_io.py:895` (tout en une expression) reste tel quel,
il est sain.

## 5. F-I1 — le commentaire d'`affecte_decodage`

Réécrit dans `contract.py`. Il dit maintenant que la garantie est « **pas de reconstruction du
runtime** » et rien d'autre — pas « effet immédiat » —, que la condition est « la valeur n'est
FIGÉE NULLE PART, ni dans le `__init__` du runtime ni dans un objet du MOTEUR construit à partir
d'elle », et il nomme l'exception : les trois `stream_in` sont `False` pour une autre raison, ne
prennent PAS effet à chaud (l'inlet unique est résolu une fois par `_ouvre_marker_inlet`), et
exigent d'arrêter puis redémarrer le mode.

## 6. B-C1 (Critical) — `empreinte_dossier` n'était éprouvé par rien

Sept assertions en dossier temporaire, en tête de `config._selftest` (17 assertions au total), avec
le diff calculé **comme chez l'appelant réel** (`research/app.py::_smoke`) : dossier absent →
`{}` · inchangé → vide · ajout · grossissement · **réécriture à taille égale** · dossier listé en
entier · suppression.

**Preuve rouge — les quatre mutations que le rapport B donnait pour « TOUT vert »** (injectées à
chaud, aucun fichier édité, `data/` jamais approché) :

| mutation | verdict | assertions rouges |
|---|---|---|
| `return {}` en tête | PROBLÈME | **5** |
| `(getsize(...),)` sans mtime | PROBLÈME | **1** (« RÉÉCRIT À TAILLE ÉGALE ») |
| `(getmtime(...),)` sans taille | PROBLÈME | **1** (« GROSSI ») |
| `sorted(listdir(...))[:1]` | PROBLÈME | **2** |

Une assertion par composante : chaque mutation rougit *la sienne*. La cinquième (`raise` sur
dossier absent) est couverte par la première assertion, qui exige de ne pas lever.

⚠️ **Non fait, et assumé** : le chaînage de `config._selftest()` dans `server.py::_smoke`, que B
recommandait « mieux ». Le dispatch scope le point 6 au selftest de `config.py`, et `config.py` fait
partie des suites listées. À décider par le lot doc (`CLAUDE.md` liste les suites).

## 7. B-transverse — `server.py --smoke` n'écrit plus dans le vrai `data/`

`_smoke_mi` détourné vers `tempfile.mkdtemp(prefix="smoke_mi_")`, via le levier prévu
(`mi_models.modeles_disponibles` repointée, exactement comme `mi.py::_selftest`). Le `finally`
restaure le catalogue **avant** `rmtree`/`stop`/`join` — sinon un `join` qui lève laisserait la
fonction repointée sur un dossier effacé pour tous les smokes suivants. La fenêtre d'exposition
n'est pas réduite, elle est supprimée : plus rien n'est écrit là, donc plus rien à détecter.

## 8. B-I1 — le chemin anti-pickle eCCA

Fixture eCCA à tableau d'objets (`w` en `dtype=object`, **sans** champ `decoder` — le chemin le
plus permissif) dans `cvep_models._selftest`, plus la correction de l'affirmation d'analyse de
mutation : la défense en profondeur n'existe QUE sur le chemin rCCA, l'eCCA n'a qu'une couche
(`CVEPModel.load`), parce que `charger` n'y lit qu'un champ (`decoder`, une chaîne).

**Preuve rouge** — `allow_pickle=True` sur `cvep_decoder.py::CVEPModel.load` **seul** :

```
ÉCHEC un .npz eCCA qui contient du PICKLE est refusé, pas dépickle (None)
ÉCHEC ...et il n'apparaît donc pas dans la liste proposée à l'étudiant
[cvep-models] VERDICT : PROBLÈME     (exit 1)
```

Exactement les 2 assertions prédites, et **aucune des assertions rCCA ne bouge** — ce qui est la
démonstration que la couverture précédente était aveugle à ce chemin.

## 9. B-I2 — `n_targets` prévient enfin

Contrôle ajouté dans `CVEPRuntime._desaccord_code` : `model.n_targets` renseigné et ≠ `len(self.plan)`
→ refus au démarrage, en nommant les deux nombres. `0` (modèle antérieur au champ) reste accepté —
c'est la forme de `data/cvep_model.npz`. Test : section **4bis** (refus nommé + non-refus du modèle
hérité). Preuve rouge (contrôle neutralisé) : `ÉCHEC …est refusé, en nommant les deux nombres (None)`.

## 10. B-I3 — l'affirmation sur les taps

Docstring de `cvep_models` corrigée : le refus eCCA ne compare que `code_len` (et maintenant
`n_targets`), **pas** `CVEP_TAPS` — passer `(6, 5)` à `(6, 1)` laisse `code_len = 63` et le modèle
passe. Dit comme un champ qui manque à `CVEPModel.save`, pas comme une couverture assumée. Le
contrôle n'a pas été élargi, comme demandé.

## 11. B-I5 — la réserve in-sample de `config.py`

Le 69 % est réécrit « 9 décisions justes sur 13 émises », suivi d'un ⚠️ : 4 points adossés à 13
décisions contre 37 pour la comparaison déclarée non interprétable, échantillons non indépendants
(les 13 sont un sous-ensemble des 37), et seuils choisis SUR ces mêmes décisions — même famille que
le `measured_on` de l'ErrP, cité. Conclusion inchangée : ce qui justifie ces seuils est le taux de
bruit (300 fenêtres), pas la justesse.

## 12. F-console — une seule écriture de l'échelle

`console.span_correlation(corr_min)` dans `console/__init__.py`, à côté de `SPAN_SEUILS` et de
`classement_relatif` (même leçon, même endroit). Appelée par `grid.py:240` et `live_views.py:274`.
Comportement à `corr_min = 0` **tranché** : aucun seuil ne borne l'échelle → on retombe sur
l'échelle absolue complète d'une corrélation, **1,0**, jamais 0 (une échelle nulle rend toute barre
pleine). Fixture `console/app.py:830` désormais **dérivée** de `cvep_channel_labels(6)` au lieu
d'être recopiée à 8 voies.

Test : le bloc c-VEP du smoke console est rejoué à `corr_min = 0.0`, avec l'assertion
tuile ↔ page réutilisée telle quelle.

**Preuve rouge** (la tuile reprend sa copie inline, l'état d'avant le correctif) :

```
ÉCHEC à `corr_min = 0` l'échelle retombe sur celle d'une corrélation entière (1,0)… (1e-06)
ÉCHEC ...et la tuile et la page restent d'accord — c'est le cas où elles divergeaient
      ([100, 100, 100, 100, 100, 100] contre [11, 19, 33, 8, 21, 12])
[console-smoke] VERDICT : PROBLÈME     (exit 1)
```

Les deux lectures opposées du rapport F, chiffrées : tuile toutes barres pleines, page à 33 %.

---

## Suites — toutes vertes, exit 0 hors pipe

| suite | exit | note |
|---|---|---|
| `python src/core/modes/cvep.py` | 0 | **70** assertions (58 avant) |
| `python src/core/lsl_io.py` | 0 | 3 exécutions consécutives |
| `python src/core/modes/contract.py` | 0 | |
| `python src/core/config.py` | 0 | **17** assertions (10 avant) |
| `python src/core/cvep_models.py` | 0 | **35** assertions |
| `python src/core/cvep_decoder.py` | 0 | |
| `python src/core/modes/registry.py` | 0 | non-régression |
| `python src/core/server.py --smoke` | 0 | 17 verdicts OK |
| `python src/console/app.py --smoke` | 0 | |
| `python src/research/app.py --smoke` | 0 | hors périmètre d'édition — lancé pour étayer le point 7 |

Un seul programme du projet à la fois, à chaque instant.

## État de `data/` — INTACT

Empreinte complète relevée **avant** et **après** la suite (nom · taille · `LastWriteTime` en ticks,
soit 100 ns de résolution — pas `git status`, le dossier est gitignoré) :

* **43 fichiers** avant, **43 après** ;
* `Compare-Object` sur les 43 lignes : **0 différence**, y compris après
  `research/app.py --smoke`, le seul smoke qui exécute de vraies calibrations ;
* le plus récent est toujours `cvep_rcca_model.npz` au **2026-08-21 14:17:45**.

Aucun fichier ajouté, réécrit, ni supprimé. Et `server.py --smoke` n'y écrit désormais plus rien,
même transitoirement.
