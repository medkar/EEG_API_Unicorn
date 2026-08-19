# Re-revue C — verdict sur la vague de correction (commit `74d78e7`)

Périmètre : `src/console/app.py`, `src/console/live_views.py`, `src/console/grid.py`,
`src/core/server.py`, `src/core/lsl_io.py`.

**Aucun programme n'a été exécuté** (quatre re-relecteurs en parallèle, noms de flux partagés).
Tout ce qui suit est lu dans le diff et dans les fichiers à HEAD. Vérifié au passage que les trois
commits postérieurs à `74d78e7` (`314fa2a`, `0dd318a`, `faa19c1`) ne retouchent **aucun** de mes
cinq fichiers : `git diff --stat` par commit, ils portent sur `research/errp_stimulus.py`,
`core/modes/errp.py` et la doc.

Vérifié aussi que `server.py` ne change **que** dans ses tests : les hunks du diff sont
`_smoke_frontiere` (2073-2099), `_AcqDeterministe` (nouveau, 2510-2549) et `_smoke_tampon_horodate`
(2568-2650). **Aucune ligne de production du moteur n'a bougé** — le risque de régression moteur
est nul par construction.

---

## Tableau des 12 verdicts

| # | Constatation | Verdict | Par où |
|---|---|---|---|
| **C1** | Page ErrP portant l'avertissement du NEURO avant le 1er feedback | **ADDRESSED** | `live_views.py:289-292` (deux constantes), `:316` (label vide), `:344` (`AVERTISSEMENT_ATTENTE` dans la branche `not z`), `:349` (`AVERTISSEMENT_Z` posé par la branche qui rend des z) ; test `app.py:604-610`. Résidu : `etat` reste vide → **N5**. |
| **I1** | Tuile P300 à l'échelle du `Z_MIN` du SSVEP | **ADDRESSED** | `grid.py:195-228` (`_apercu_scores`), `Z_MIN` retiré de l'import `grid.py:22-25` ; 4 assertions `app.py:535-552`. Réserves → **N1**, **N4**. |
| **I2** | `_smoke_frontiere` aveugle à Qt | **ADDRESSED** | `server.py:2097-2099`, docstring `:2073-2092`. Réserves → **N3** + import transitif (ci-dessous). |
| **I3** | `[smoke-tampon]` instable depuis cinq tâches | **ADDRESSED** | `server.py:2510-2549` (`_AcqDeterministe`) + `:2603-2650`. Réserve → **N2**. |
| **I4** | Nom `decoded_errp` écrit deux fois | **ADDRESSED** | `lsl_io.py:559` (`SUFFIXE`), `:565-566` (usage) et surtout `:709-716` (§8bis : nom **publié** vs `stream_name(registry.get("errp").stream)`). |
| **I5** | Fixture « mesuré : 46 % / 93 % » + assertion non ancrée | **ADDRESSED** | (a) `app.py:589-590` (`0.500` / `0.855`) et commentaire `:577-583` sans le mot « mesuré » ; (b) `app.py:626-631` (« garde 86% » / « attrape 50% » / « visé 85% ») et `:708` (« attrape 50% » dans le résumé de tuile). |
| **I6** | `taux_rejet`/`artefacts`/`epoques_vues` jetés par la console | **ADDRESSED** | `live_views.py:416-440` (`_sante`) branché sur les **trois** branches (`:402`, `:412`, `:414`) ; test `app.py:639-647`. |
| **M1** | `_span` de la tuile ErrP non vérifié + seuil illisible | **PARTIEL** | Assertion faite (`app.py:695-698`). Le **rendu** (seuil à 0,9 % de la demi-hauteur → plancher de 2 px) reste tel quel — report argumenté et **juste**. |
| **M2** | `pdf['tpr']` en accès direct | **ADDRESSED** | `grid.py:266` (`.get`) + test `app.py:718-724`. |
| **M3** | `tpr_measured`/`tnr_measured` optimistes, non dits | **ADDRESSED** | `lsl_io.py:581-599` (commentaire + `measured_on`) et assertion `:694-697`. |
| **M4** | `measured_on` = constante | **PARTIEL** | « 1 session » retiré (`lsl_io.py:597-599`), mais **« 1 person » reste un littéral non dérivé**. Dépendance `core/errp_models.py` réellement hors périmètre autorisé. |
| **M5** | Extrait « Brancher un client » muet sur le `-1` | **NON TRAITÉ** | Report **justifié** : `core/modes/contract.py` n'est pas dans le périmètre autorisé, et la constatation le classe elle-même « générique, préexistant, à arbitrer hors chantier ». |

**Décompte : 9 ADDRESSED · 2 PARTIEL · 1 NON TRAITÉ · 0 RÉGRESSION.**
Le rapport annonce « 10 traitées, 2 reportées » : compatible. Les deux reports (M4-suite, M5)
butent l'un et l'autre sur un fichier que le correcteur n'avait pas le droit de toucher, et les
deux sont remontés dans sa section « dépendances hors périmètre ». **Aucun report de confort.**

---

## Les trois dettes inter-chantiers

### Dette 1 — tuile P300 (I1) : **payée, et vérifiée contre la page**

J'ai comparé terme à terme `grid._apercu_scores` (`grid.py:221-228`) et
`live_views.ActiveView._update_selection` (`live_views.py:252-261`) :

| | page | tuile |
|---|---|---|
| borne basse / haute | `min(scores)`, `max(scores)` | idem |
| dégénérescence | `0.5 if etendue <= 0` | idem |
| valeur | `(scores[i] - bas) / etendue` | idem |
| clamp | `max(0, min(part, 1)) * 100` | `span=1.0` puis `max(-1, min(v/span, 1))`, `centre=False` → `max(part, 0)` |

**Identique.** Sur le fixture (`scores = [-1.9, -2.4, -1.2, -0.42, -2.0, -1.5]`), page et tuile
donnent tous deux `[0.2525, 0.0, 0.6061, 1.0, 0.2020, 0.4545]`. Le repli `Z_MIN` a disparu jusqu'à
l'import (`grid.py:22-25`, avec le commentaire qui interdit son retour).

**La tuile ErrP est bien couverte elle aussi**, pas seulement la P300 : `app.py:695-698` lit
`tuiles["errp"].apercu._span == 5.044` — c'était le point exact de M1, et il est fait.
Le garde-fou symétrique est là également (`app.py:549-552` : la tuile SSVEP garde son échelle
absolue), sans quoi « ne plus jamais utiliser de seuil » passerait aussi.

**Réserve** : pour le SSVEP, tuile et page ne se sont **jamais** accordées, et la nouvelle
assertion fige l'écart → **N1**. Et la normalisation est désormais écrite deux fois → **N4**.

### Dette 2 — `_smoke_frontiere` (I2) : **payée ; le motif attrape ce qu'il prétend**

Formes vérifiées à la main contre
`^\s*(?:from|import)\s+(research|console|pygame|PySide\d|PyQt\d|qtpy|pyqtgraph)\b` :

| forme | attrapée ? |
|---|---|
| `from PySide6.QtWidgets import QLabel` | ✅ (`\b` tombe entre `6` et `.`) |
| `import PySide6.QtCore as qtc` | ✅ |
| `from PyQt5 import QtCore` / `from PyQt6.QtCore import x` | ✅ |
| `import qtpy` / `from qtpy.QtWidgets import x` | ✅ |
| `import pyqtgraph as pg` (même indenté : `^\s*`) | ✅ |
| `    # import PySide6` (commentaire) | ✅ ignoré — après `\s*` vient `#`, pas `from`/`import` |
| mot « PySide6 » au milieu d'une phrase | ✅ ignoré |
| **import transitif** (`import matplotlib.backends.backend_qt5agg`, ou tout paquet qui tire Qt) | ❌ **non attrapé, et non documenté** |

**Faux positifs : aucun aujourd'hui.** J'ai passé au grep les 32 occurrences de
`PySide|PyQt|qtpy|pyqtgraph|pygame` dans `src/core/**/*.py` : toutes sont en milieu de ligne
(prose de docstring) ou après un `#`. Aucune ne commence une ligne.

La docstring documente honnêtement les deux angles morts que la constatation citait (import
dynamique, import relatif). Elle ne dit rien du transitif — à ajouter en une ligne. Et le test
scanne désormais sa propre docstring, qui contient le texte interdit → **N3**.

### Dette 3 — `[smoke-tampon]` (I3) : **oui, il teste encore `server.py`**

C'est le point que la re-revue devait trancher. Réponse détaillée.

**Ce que le double remplace** (`_AcqDeterministe`, `server.py:2510-2549`) : `__enter__`,
`__exit__`, `get_new_data`. **Rien d'autre** — `__getattr__` délègue tout le reste à l'instance
réelle d'`UnicornAcquisition` passée au constructeur.

**Ce qui reste RÉEL dans le chemin testé** :

| ce qui tourne | à qui c'est |
|---|---|
| `self.keep = max(...) + margin_n` (`server.py:197-202`) | **vraie** acquisition — la substitution a lieu APRÈS `__init__`, `keep` est donc calculé sur `fs`/`window_n`/`margin_n` réels |
| `ts_lsl = self.clock.to_lsl(ts_unix)` (`server.py:1210`) | `ClockBridge.to_lsl`, **vrai** (`lsl_io.py:103-105`) |
| `np.vstack([...])[-keep:]` et `np.concatenate([...])[-keep:]` (`:1212-1213`) | **production `server.py`** |
| `self.new_block = None` puis `(eeg, ts_lsl)` (`:1208`, `:1211`) | **production `server.py`** |
| `_publish_quality` → `acq.sigma_from_block` / `acq.common_mode` (`:1128-1136`) | **vraie** acquisition (délégué) |
| structure de boucle (`break` en haut, `POLL_S`, `finally`) | **production `server.py`** |

**Une mutation de `server.py` fait-elle encore rougir ?** Oui. Les deux mutations du rapport
portent bien sur des lignes de production (`:1213` pour le `+ 1.0/fs`, `:1210` pour la
régénération de l'axe des temps), et leurs sorties rouges sont cohérentes avec ce que je lis :
la première casse `np.array_equal(recent_ts[-n:], ts_lsl)`, la seconde casse à la fois `diffs > 0`
et l'écart de cadence. Une troisième mutation plausible — `self.new_block = (eeg, ts_unix)` —
rougirait aussi l'assertion d'alignement.

**La tolérance a bien été RESSERRÉE, pas élargie** : de `[0,5/fs ; 2/fs]` (soit ±2 ms sur 4 ms) à
`|médiane − 1/fs| < 10 µs`, ×400. Et la résolution flottante sur des dates Unix à `t0 = 1,7e9`
est de ~0,24 µs : la fenêtre de 10 µs est confortable, l'assertion n'est pas au bord.

**Deux réserves, sans lesquelles ce verdict serait complaisant** :

1. `chk(len(recent_ts) == min(produits, keep) > 0)` **n'exerce jamais la troncature** : 8 tours ×
   13 = 104 échantillons pour `keep = 1250`. Le `min()` est inerte, et le commentaire qui annonce
   « il vérifie AUSSI la troncature » est faux → **N2**.
2. Un `server.py` qui **sauterait** `to_lsl` (publier des dates Unix brutes sur un flux LSL —
   une vraie panne) resterait **vert** : les deux côtés de chaque comparaison viendraient alors du
   même tableau, et un décalage constant ne bouge ni les `diffs` ni l'alignement. Ce n'est pas une
   régression (l'ancien test ne le voyait pas non plus), mais la docstring est emphatique sur
   « `server.py` recopie les horodatages » : elle détecte une **régénération à une autre cadence**,
   pas un **oubli de conversion**.

Bilan : le double ne remplace pas trop. Il remplace exactement la session BrainFlow et la
livraison d'échantillons, c'est-à-dire les deux seules choses qui rendaient le test dépendant de
l'ordonnanceur. Le test qui reste est plus étroit qu'avant sur le papier — et strictement plus
utile, puisque avant, deux de ses six assertions ne pouvaient rougir que sur une panne de
BrainFlow.

---

## Les constatations non-ADDRESSED

### M1 (PARTIEL) — le seuil de la tuile ErrP reste une barre invisible

**Fait** : `app.py:695-698` lit `_span`, la mutation `span=NEURO_Z_SPAN` rougit. C'était le point
principal.

**Reste** : `grid.py:190-191`, `span = max(abs(score), abs(seuil), 1.0)`. Avec `score = 5,044` et
`seuil = 0,044` → `span = 5,044`, donc la barre du seuil vaut `0,044/5,044 = 0,9 %` de la
demi-hauteur, soit le plancher `max(2, int(hauteur))` de `MiniBars.paintEvent` (`grid.py:78`).

**Scénario concret.** Séance réelle, l'étudiant regarde la grille. Chaque feedback « erreur »
affiche deux barres censées se comparer : une pleine, une de 2 px. Un feedback « correct »
(`score = −4,956`) affiche une barre pleine **vers le bas** et le même moignon. Il ne peut donc
jamais lire sur la tuile de combien le score a franchi le seuil — la seule information que le
couple (score, seuil) porte. Il faut ouvrir la page, ou lire le résumé chiffré.

**Le report est justifié** : j'ai vérifié l'argument du correcteur, il est exact —
`max(5.044, 4 × 0.044, 1.0) = max(5,044 ; 0,176 ; 1,0) = 5,044`, la suggestion de la constatation
est **inerte** sur cet exemple. Le vrai correctif (dessiner le seuil comme une LIGNE) demande un
mode de dessin de plus dans `MiniBars` ; la constatation le classait « non bloquant » et le résumé
de tuile porte bien les deux nombres. À reporter tel quel, mais sans le compter comme corrigé.

### M4 (PARTIEL) — « 1 person » est toujours un littéral

`lsl_io.py:597-599` publie `"1 person; threshold picked on these same out-of-fold scores, so
tpr/tnr are optimistic"`. « 1 session » a disparu ; « 1 person » n'est dérivé de rien.

**Scénario concret.** Un binôme d'étudiants met en commun deux calibrations pour entraîner un
modèle plus riche (rien dans `errp_models.py` ne l'interdit). Le flux publie toujours
`measured_on = "1 person; …"`. Une application cliente qui lit ce champ pour décider si le point
de fonctionnement lui est transposable conclura « modèle individuel » sur un modèle qui ne l'est
pas — et c'est le champ dont le rôle est précisément de dire à quoi le contrat engage.

**Le report est justifié** : le rendre honnête exige que `ErrPModel` expose son nombre de groupes,
donc `core/errp_models.py`, absent du périmètre autorisé du correcteur. La dépendance est écrite
dans le commentaire du champ ET remontée dans le rapport. Rien à reprocher, mais la constatation
n'est pas fermée.

### M5 (NON TRAITÉ) — l'extrait « Brancher un client » ne dit toujours rien du `-1`

`core/modes/contract.py:685-701` n'est pas dans le périmètre autorisé, et la constatation
elle-même écrivait « à arbitrer hors de ce chantier ». **Report justifié.**

Mais la contrainte du projet dit : « `error = -1` = "pas de verdict", jamais "pas d'erreur", **et
ça doit se VOIR à l'écran** ». Sur l'écran de la console, c'est fait et bien fait — quatre textes
distincts, vérifiés par `app.py:655-678`. Dans **le code que l'étudiant copie**, non.

**Scénario concret.** L'étudiant copie l'extrait de la page ErrP, écrit
`if valeurs["error"]: annuler()` — vrai pour `1` **et** pour `-1` — et son application annule une
commande à chaque clignement, c'est-à-dire exactement aux instants où l'utilisateur sursaute
parce que la machine s'est trompée. Le flux, lui, avait raison : il n'affirmait rien.
**À porter au chantier suivant, une ligne dans le gabarit.**

---

## Défauts NOUVEAUX (5)

### N1 — La tuile SSVEP et sa page ne mettent toujours pas les mêmes scores à la même échelle, et `app.py:549` fige désormais l'écart

**Fichiers** : `grid.py:217-220` (tuile) contre `live_views.py:169-173` (page).

- page, `_update_scores` : `barre.setValue(min(valeur / (2 * seuil), 1.0) * 100)` — **2× le seuil**,
  avec un commentaire qui explique pourquoi (« une barre pleine à ras le seuil laisserait croire
  qu'on est au maximum alors qu'on vient à peine de déclencher ») ;
- tuile, `_apercu_scores` : `span = max(float(seuil), 1.0)` — **1× le seuil**.

**Scénario concret**, sur le fixture du smoke lui-même (`scores = [3.1, 0.4, 0.9]`, `seuil = 2,5`,
`app.py:201-203`) :

| cible | page | tuile |
|---|---|---|
| 15 Hz (3,1) | 62 % | **100 %** (1,24 écrêté) |
| 20 Hz (0,4) | 8 % | 16 % |
| 8,57 Hz (0,9) | 18 % | 36 % |

L'étudiant voit sur la grille une barre **pleine** — « c'est au maximum » — puis ouvre la page et
lit 62 %. Deux écrans, mêmes données, deux lectures : c'est mot pour mot le défaut que I1 existe
pour supprimer, survivant sur l'autre branche de la même fonction. Et la nouvelle assertion
`app.py:549-552` (`tuiles["ssvep"].apercu._span == threshold`) **verrouille** la version divergente :
aligner la tuile sur la page (`span = 2 * seuil`) fait maintenant **rougir** le smoke.

*Préexistant* — la ligne d'avant faisait déjà `max(sortie.get("threshold", Z_MIN), 1.0)`. Ce qui
est nouveau, c'est qu'un test l'interdit désormais de changer. *Correctif* : `span = max(2 *
float(seuil), 1.0)` et l'assertion sur `2 * threshold` ; ou, mieux, N4.

### N2 — `[smoke-tampon]` annonce vérifier la TRONCATURE ; le tampon ne se remplit jamais

**Fichier** : `server.py:2611-2616`.

```python
# ... Écrit ainsi, il vérifie AUSSI la troncature, et il ne vieillira pas si POLL_S ou la durée
# du test changent.
chk(len(srv.recent_ts) == min(srv.acq.produits, srv.keep) > 0, ...)
```

`duration_s = 0.4` et `POLL_S = 0.05` → 8 tours ; `par_tour = 13` → **104 échantillons produits**.
`keep = 1250` (confirmé par la sortie verte du rapport). `min(104, 1250) = 104` : le `min()` est
inerte, la branche `[-self.keep:]` n'est **jamais** empruntée.

**Scénario concret.** Quelqu'un « simplifie » `server.py:1212-1213` en retirant les deux
`[-self.keep:]` (par exemple en croyant que `keep` ne sert qu'au dimensionnement) :

```python
self.recent = np.vstack([self.recent, eeg])
self.recent_ts = np.concatenate([self.recent_ts, ts_lsl])
```

`[smoke-tampon]` reste **VERT** (104 == min(104, 1250)). `_smoke_dimensionnement` reste vert (il
teste `keep >= …`, pas le découpage). `_smoke_mi` reste vert (même chose). Le moteur se met alors
à faire croître ses deux tampons sans borne : une séance d'une heure à 250 Hz porte 900 000 lignes
× 8 voies, et chaque tour fait un `vstack` complet de ce tableau, dix fois par seconde. Ça ne casse
pas, ça ralentit puis ça sature la mémoire — la panne la plus difficile à imputer.

*Correctif* : soit produire plus que `keep` (`par_tour` élevé, ou `duration_s` calculé pour
`produits > keep`), soit ajouter une assertion dédiée sur un `EngineServer` au `keep` réduit. La
tournure `min(produits, keep)` est bonne ; c'est le régime qui manque.

**À VÉRIFIER PAR EXÉCUTION** (facultatif, avec mutation, en série) : retirer les deux
`[-self.keep:]` de `src/core/server.py:1212-1213` puis `python src/core/server.py --smoke` —
attendu **`[smoke-tampon] VERDICT : OK`**, ce qui confirmerait le trou. Remettre les deux slices
ensuite.

### N3 — `_smoke_frontiere` scanne sa propre docstring, qui contient maintenant le texte interdit

**Fichier** : `server.py:2083`.

La docstring dit désormais : « Un `from PySide6.QtCore import QTimer` glissé dans un utilitaire du
moteur passait donc en silence ». Le test lit le **texte** de tous les `.py` de `src/core/`, y
compris `server.py`. Aujourd'hui la ligne 2083 commence par `son propre nom. Un \`from PySide6…` —
le motif exige `^\s*(?:from|import)`, donc pas de match. **La marge est d'un mot.**

**Scénario concret.** Quelqu'un ajoute « du moteur » dans la phrase précédente, ou passe le fichier
dans un formateur qui reflow les docstrings. Le paragraphe se re-découpe et
`from PySide6.QtCore import QTimer` se retrouve en début de ligne. Alors :

```
[smoke-frontiere] ÉCHEC : core/server.py importe PySide6
[smoke-frontiere] 1 violation(s) de frontière
[smoke-frontiere] VERDICT : PROBLÈME
```

`python src/core/server.py --smoke` sort en 1, sur une **prose**. Le contributeur cherche
l'import fautif dans un fichier qui n'en a pas — exactement le temps perdu que la dette 3 vient de
supprimer ailleurs. *Correctif d'une ligne* : écrire le nom sans la forme d'import (« un import de
`PySide6.QtCore` »), ou exclure `server.py` de son propre scan, ou faire porter le motif par une
constante et ne jamais écrire la forme complète dans la prose.

### N4 — La normalisation relative est recopiée entre tuile et page, et **aucune** assertion ne compare les deux rendus sur les mêmes données

**Fichiers** : `grid.py:225-228` et `live_views.py:256-261` — quatre lignes identiques
(`bas/haut`, `etendue`, `0.5 if etendue <= 0`, `(s - bas) / etendue`), à deux endroits.

Les deux sont testés, mais **séparément** : `app.py:525` lit les barres de la page
(`valeurs[3] == 100 and valeurs[1] == 0`), `app.py:539` lit `_values` de la tuile. Rien ne dit
qu'ils doivent coïncider. Or l'histoire entière de I1 est « la page a été corrigée, la tuile
oubliée » : la vague a rétabli l'accord sans installer ce qui l'empêche de se défaire.

**Scénario concret.** Le P300 gagne un `n_flashes` variable et quelqu'un décide de pondérer les
barres de la page par la confiance (`part *= confidence / max_conf`) : il édite `_update_selection`,
ajuste `app.py:525`, et laisse `grid.py` intact. La tuile et la page recommencent à se contredire,
le smoke est vert, et personne ne le voit — puisque c'est déjà arrivé une fois sur cette même
paire de fonctions.

*Correctif* : extraire `classement_relatif(scores) -> list[float]` (côté console, c'est du rendu,
pas du moteur), l'appeler des deux côtés, et ajouter une assertion qui **lie** les deux :

```python
chk([round(v * 100) for v in apercu_p3._values] == [b.value() for _e, b in p3._barres],
    "la tuile et la page rendent le MÊME classement sur les mêmes données")
```

C'est cette assertion-là qui aurait attrapé I1 le jour où il est né. La même extraction règle N1 en
passant, en rendant visible que la branche SSVEP, elle, n'utilise pas la même règle.

### N5 — La page ErrP reste **sans titre** pendant ses 23 premières secondes

**Fichier** : `live_views.py:343`.

```python
self.etat.setText(mode_state["instruction"] if mode_state else "en attente")
```

C1 est corrigé — la page n'affirme plus une unité fausse. Mais elle ne dit toujours rien de
positif : après le repos, `ErrPRuntime.instruction()` rend `""`, donc `etat` — le label en gros
au-dessus des barres — devient **vide**. Reste le seul avertissement gris 11 px
(`AVERTISSEMENT_ATTENTE`).

**Scénario concret.** L'étudiant démarre l'ErrP, ouvre sa page, traverse la chauffe (15 s) et le
repos (8 s) avec leurs consignes. À la fin du repos, l'écran principal se **vide** ; l'étudiant
doit maintenant deviner qu'il lui reste à lancer `python src/research/errp_stimulus.py` dans un
second terminal, information qui n'est ni sur cette page ni dans l'avertissement. Un écran vide se
lit comme « ça ne marche pas » — la panne canonique de ce projet, sous une autre forme.

La constatation C1 proposait précisément `mode_state["instruction"] or "en attente du premier
feedback"` ; la moitié « ne pas mentir » a été prise, la moitié « dire quoi faire » pas. *Correctif*
(une ligne, sans routage sur l'identifiant) :

```python
self.etat.setText((mode_state or {}).get("instruction") or "en attente du premier échantillon")
```

et une assertion sur `errp_page.vue.etat.text()` dans l'état `errp_demarre` déjà construit à
`app.py:604`.

---

## Notes de contrôle (pas des défauts)

- **Console = client du moteur** : rien de neuf n'a été recopié. `_sante` (`live_views.py:435-440`)
  affiche `taux_rejet`/`epoques_vues`/`artefacts` **tels que publiés** et **ne recopie pas** le
  plancher `_TAUX_REJET_MIN_ECHANTILLONS` du moteur, avec l'argument juste (« le plancher décide
  quand ALARMER, pas quand informer »). Le libellé « époques de **ce repos** » est correct :
  `errp.py:341-349` documente que ces trois compteurs décrivent le repos en cours, pas la séance
  (les cumuls de séance sont `*_session`, non affichés). Aucun catalogue de modes, aucune
  validation de réglage n'a été ajouté côté Qt. `src/console/` importe `core`, jamais l'inverse.
- **Chiffres affichés vs mesurés** : le seul littéral encore présenté comme une mesure est
  « 1 person » (M4). Les taux de l'écran ErrP viennent tous de `point_de_fonctionnement` posé par
  le moteur. Le fixture 0,500/0,855 est étiqueté « calqué sur » et non « mesuré ». Petit nit :
  `app.py:578` cite « docs/SPEC.md : TPR 0,500 / TNR 0,855 » alors que SPEC.md formule la même
  chose en prose (« une erreur sur deux… une bonne commande sur sept ») ; la valeur littérale est
  dans `docs/superpowers/plans/2026-08-18-errp-moteur.md:23`.
- **Tests qui ne peuvent pas rougir** : parcouru les 12 assertions nouvelles. Onze ont une mutation
  d'une ligne de production qui les fait échouer (les 11 du tableau du rapport, recoupées sur le
  code). La douzième — `len(recent_ts) == min(produits, keep)` — n'en a pas pour sa moitié
  « troncature » : **N2**.
- **`live_views.py:16`** importe encore `Z_MIN`, utilisé en repli à `:165`
  (`float(sortie.get("threshold", Z_MIN))`). Ce repli est **inatteignable** : `update_from:156`
  n'entre dans `_update_scores` que si `"threshold" in sortie`. Sans danger aujourd'hui, mais
  `grid.py` a reçu un commentaire interdisant le retour de `Z_MIN` et `live_views.py` non — deux
  fichiers voisins, deux régimes. Une ligne de ménage.
- **`_sante`** utilise `mode_state.get('artefacts', 0)` : si un jour `taux_rejet` et `epoques_vues`
  arrivaient sans `artefacts`, l'écran afficherait « rejet artefact 90% (**0**/40 époques) », une
  fraction qui contredit son propre pourcentage. `errp.py:345-348` pose toujours les trois
  ensemble, donc pas de scénario réel — mais c'est le même raisonnement que M2, du côté du
  chiffre faux plutôt que du `KeyError`.
- **Aucun test n'écrit dans `data/`** ; `app.py --smoke` sort en 1 (`sys.exit(0 if _smoke() else 1)`),
  `lsl_io.py` idem (`:725`), et les `assert` de son autotest sortent aussi en 1 par exception.
  Qt est bien forcé en offscreen **avant** le premier import PySide6 (`app.py:44-46`).
