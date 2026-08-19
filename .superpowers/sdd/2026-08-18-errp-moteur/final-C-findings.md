# Tranche C — revue finale : publication LSL + rendu console

Périmètre : `src/core/lsl_io.py`, `src/core/modes/registry.py`, `src/core/modes/external.py`,
`src/core/modes/p300.py` (fixture), `src/console/app.py`, `src/console/live_views.py`,
`src/console/grid.py` — plus les trois remontées inter-tâches (`server.py`, hors diff, lu).

**Aucun programme n'a été exécuté** (quatre relecteurs en parallèle, noms de flux partagés). Les
constatations qui exigeraient une exécution portent la ligne « À VÉRIFIER PAR EXÉCUTION ».

Bilan : **1 Critical · 6 Important · 5 Minor**.

Ce qui est solide et que je ne redis pas ailleurs : le retrait d'`external.ERRP` est complet (aucune
trace résiduelle de `status="appli_pygame"` pour l'ErrP hors des plans historiques, qui sont des
archives) ; la console n'a AUCUN compte de modes en dur (`attendu_externes`, `attendu_calib`,
`len(registry.MODES)` sont tous dérivés du registre) ; aucune validation de réglage n'a été recopiée
côté Qt ; le correctif de fixture de `p300.py` (valeur distincte par voie) fait réellement ce qu'il
annonce — une permutation de deux voies quelconques casse maintenant `np.array_equal`, ce que
`42.0` répété laissait passer ; `decision_scale="logodds"` est VRAI (`ErrPModel.score` →
`decision_function` d'une LR, `errp_decoder.py:204`), et les voies sont bien single-sourcées par
`errp_channel_labels()` pour le publieur ET le `ModeSpec`.

---

## CRITICAL

### C1 — La page ErrP affiche l'avertissement du NEURO (« z contre TON repos du jour ») tant qu'aucun feedback n'a été décodé

**Fichier** : `src/console/live_views.py:296-300` (le texte par défaut) et `:347` (`_update_errp`,
qui est le seul endroit qui l'écrase).

**Ce qui casse.** `PassiveView.__init__` initialise `self.avertissement` avec le texte du
neuro-monitoring :

```
"z contre TON repos du jour, mesuré au démarrage du mode. Ni comparable entre personnes,
 ni entre séances, ni absolu. À lire en TENDANCE."
```

`_update_errp` — la seule méthode qui remplace ce texte pour l'ErrP — n'est atteinte que par
`if "error" in sortie` (`:317`). Or `sortie` vient de `mode_state["output"]`, et
`ErrPRuntime.output()` rend `self._decoded`, qui vaut **`None` jusqu'au tout premier `_publish`**
(`core/modes/errp.py:138`, `:255`). Avant ce premier feedback, `update_from` retombe dans la branche
`z = sortie.get("z") or {}` → `if not z:` → `self.etat.setText(mode_state["instruction"])` et
**sort sans jamais toucher `avertissement`**.

La page de l'ErrP affiche donc, en toutes lettres, que son score est *un z contre le repos du jour*.
C'est faux : c'est un log-odds comparé à un seuil issu de la calibration de la personne. Ce n'est
pas un silence, c'est une **affirmation fausse sur l'unité** — la catégorie que ce chantier a
lui-même classée comme la pire (`live_views.py:313-314` : « le défaut symétrique du P300 rendu comme
un SSVEP dans `ActiveView`, qui LUI affirmait du faux »).

**Scénario concret.**
1. L'étudiant a un modèle ErrP entraîné. Il démarre le mode depuis la console (`Démarrer` sur la
   tuile), puis ouvre la page ErrP.
2. `phase = "warmup"` puis `"rest"` : 15 s + 8 s = **23 s** pendant lesquelles `etat` porte la
   consigne de repos et `avertissement` porte le texte du neuro.
3. À la fin du repos, `instruction()` rend `""` (`runtime.py:117-119`) : `etat` devient **vide**, et
   `avertissement` porte toujours « z contre TON repos du jour ».
4. Le moteur ne rend AUCUN stimulus : l'étudiant doit maintenant aller lancer
   `python src/research/errp_stimulus.py` dans un second terminal. Pendant tout ce temps — repos
   compris, donc **au minimum 23 s, en pratique le temps de changer de fenêtre et de lancer un second
   programme** — la page de l'ErrP est une page vide surmontée d'une phrase qui décrit un autre mode
   et une autre unité.
5. Au premier feedback décodé, le texte se corrige. L'étudiant qui a lu l'écran entre-temps a appris
   que « 5,044 » est un nombre d'écarts-types au-dessus de son repos.

**Pourquoi aucun test ne le voit.** `console/app.py:558-559` fait `show_mode("errp")` puis
`apply_state(errp_state)` — un état qui porte DÉJÀ un `output` complet. L'état « démarré, aucun
feedback encore » (`output: None`), le seul dans lequel le défaut existe, n'est jamais construit.
C'est exactement l'état que le fixture du `raw` (`app.py:194`) et celui du neuro savent pourtant
écrire.

**Correctif minimal.** Deux lignes dans `live_views.py`. Sortir le texte par défaut du constructeur
et le poser explicitement dans la branche neuro, ou — plus simple et plus sûr — traiter le cas
« pas encore de sortie » AVANT le routage sur `"z"` :

```python
def update_from(self, mode_state):
    sortie = (mode_state or {}).get("output") or {}
    if "error" in sortie:
        self._update_errp(mode_state, sortie)
        return
    if not sortie and (mode_state or {}).get("id") == "errp":   # ou : famille sans "z"
        self.etat.setText(mode_state["instruction"] or "en attente du premier feedback")
        self.avertissement.setText("aucun feedback décodé pour l'instant — le score de ce mode "
                                   "est un log-odds contre le seuil de TA calibration, jamais un z.")
        return
```

(Router sur l'identifiant est contraire à la règle du fichier ; la variante propre est de descendre
le texte par défaut de `avertissement` dans la branche `z`, et de laisser le label vide au départ.)

Et ajouter au smoke, juste avant `errp_state` :

```python
console.apply_state({**errp_state, "modes_state": {**errp_state["modes_state"], "errp": {
    **errp_state["modes_state"]["errp"], "output": None}}})
chk("z contre" not in errp_page.vue.avertissement.text(),
    f"avant le premier feedback, la page ErrP ne parle JAMAIS d'un z contre le repos du jour "
    f"({errp_page.vue.avertissement.text()!r})")
```

**Mutation qui rougit ce test** : remettre le texte du neuro dans le constructeur sans le neutraliser
pour l'ErrP. Aujourd'hui, aucune.

---

## IMPORTANT

### I1 — REMONTÉE 1 : **réelle**. La tuile P300 met ses log-odds à l'échelle du `Z_MIN` du SSVEP

**Fichier** : `src/console/grid.py:164-167`.

```python
if "scores" in sortie:
    self.apercu.set_values(sortie["scores"],
                           span=max(sortie.get("threshold", Z_MIN), 1.0),
                           retenue=sortie.get("target_index", -1))
```

**Ce qui casse.** La sortie du P300 (`core/modes/p300.py:490-495`) est
`{target_index, confidence, n_flashes, scores}` — **elle n'a pas de clé `threshold`**, et c'est
délibéré : `ActiveView._update_selection` documente sur 20 lignes que le P300 n'a AUCUN seuil
(`live_views.py:228-246`). Le repli `Z_MIN` (= 2,5, `core/config.py:220`) est donc systématiquement
pris, et il applique au P300 l'échelle du SSVEP — la panne exacte que le chantier précédent a
corrigée **sur la page** et jamais **sur la tuile**.

Pire : la branche `"scores"` passe aussi `centre=False`, donc `MiniBars.paintEvent` prend le chemin
« actif » (`grid.py:70-73`), où `hauteur = max(part, 0.0) * haut` — tout score négatif est écrasé à
zéro.

**Ce que l'étudiant voit exactement.** Les scores P300 sont des log-odds moyens, **négatifs le plus
souvent** (une cible flashe une fois sur six, le classifieur dit « non-cible » presque toujours —
c'est écrit noir sur blanc dans `live_views.py:239-241`). Donc, à chaque fin de manche :

- entrée : `scores = [-1.0, 0.5, 4.1, -0.2, 1.0, -3.0]`, `target_index = 2` (l'exemple de
  `lsl_io._autotest:605`) ;
- rendu : `span = 2.5`. Cible 0 → `part = -0,4` → hauteur 0 → **rectangle de 2 px** (le plancher
  `max(2, int(hauteur))`). Idem cibles 3 et 5. Cible 1 → 20 % de barre. Cible 4 → 40 %. Cible 2 →
  `4,1/2,5 = 1,64` **écrêté à 1,0**, barre pleine ;
- avec des scores tous négatifs (cas courant d'une manche peu concluante) : **six moignons de 2 px,
  dont un bleu**. L'étudiant lit « la sélection n'a aucune preuve derrière elle », ce qui est faux :
  c'est l'ÉCART 1er-2e qui décide, et il peut être franc.

La même tuile, ouverte sur sa page, montre un classement lisible (`_update_selection` : plus faible
vide, plus forte pleine, échelle relative recalculée). **La tuile et la page contredisent donc
l'une l'autre sur les mêmes données.**

**Pourquoi rien ne le voit.** Aucune assertion du smoke console ne touche
`console.grid.tuiles["p300"].apercu` (vérifié : les seules tuiles dont l'aperçu est lu sont
`ssvep`, `neuro`, `errp` — `app.py:411`, `:414`, `:466`, `:611`). Et `_span` n'est lu par **aucune**
assertion du fichier, pour aucun mode.

**Correctif minimal.** Aligner la tuile sur la page : quand `threshold` est absent, échelle
RELATIVE, jamais `Z_MIN`.

```python
if "scores" in sortie:
    scores = list(sortie["scores"])
    seuil = sortie.get("threshold")
    if seuil is None:
        # P300 : log-odds, sans seuil et sans échelle absolue (cf. ActiveView._update_selection).
        # On montre le CLASSEMENT, comme la page — jamais le Z_MIN du SSVEP.
        bas, haut = (min(scores), max(scores)) if scores else (0.0, 0.0)
        etendue = haut - bas
        valeurs = [0.5 if etendue <= 0 else (s - bas) / etendue for s in scores]
        self.apercu.set_values(valeurs, span=1.0, retenue=sortie.get("target_index", -1))
    else:
        self.apercu.set_values(scores, span=max(float(seuil), 1.0),
                               retenue=sortie.get("target_index", -1))
```

Et un test qui rougit : ajouter au smoke, sur l'état P300 existant,
`chk(console.grid.tuiles["p300"].apercu._span != Z_MIN and max(...) > 0, ...)`.

**La même question pour l'ErrP** : la nouvelle tuile ne tombe PAS dans ce piège — sa branche
(`grid.py:175-190`) construit son propre span et met `centre=True`. C'est correct. Voir toutefois M1
sur le fait que cette correction n'est vérifiée par aucune assertion, et sur sa lisibilité réelle.

---

### I2 — REMONTÉE 2 : **réelle**. `_smoke_frontiere` ne connaît ni PySide6 ni pyqtgraph

**Fichier** : `src/core/server.py:2083`.

```python
interdits = re.compile(r"^\s*(?:from|import)\s+(research|console|pygame)\b", re.MULTILINE)
```

**Ce qui casse.** Ce que le projet interdit dans `core/` est écrit en trois endroits, et les trois
disent **Qt** :

- `CLAUDE.md` : « Ni pygame **ni Qt** dans `core` : le moteur tourne sans écran. » ;
- `src/core/__init__.py:17-18` : « Aucune dépendance à pygame non plus : le moteur tourne sur une
  machine sans écran » ;
- la docstring du test lui-même, `server.py:2073` : « `core` n'importe ni `research`, ni `console`,
  ni pygame », suivie de « le moteur doit tourner sur une machine sans écran ».

Le motif attrape `console` (donc `from console.grid import ...`) mais **pas** `PySide6`, `PyQt5`,
`PyQt6`, `qtpy`, ni `pyqtgraph`. Or Qt n'arrive pas dans `core` par le paquet `console` : il arrive
par son propre nom. La règle vérifiée est donc plus étroite d'un cran que la règle écrite, et c'est
précisément le cran qui compte — `pyqtgraph` est déjà importé ailleurs dans l'arbre
(`console/live_views.py:36`, en import différé et **indenté** : le `^\s*` du motif le verrait, si le
nom était dans la liste).

**Scénario concret.** Un contributeur veut afficher les tracés dans un utilitaire du moteur et écrit
dans `src/core/quality_view.py` :

```python
from PySide6.QtCore import QTimer
```

`python src/core/server.py --smoke` affiche **« [smoke-frontiere] 0 violation(s) de frontière —
VERDICT : OK »**. Le moteur headless dépend maintenant de Qt : sur un poste sans Qt (`pip install`
minimal, machine de TP, futur CI sans `libGL`), `python src/core/server.py --mode ssvep` meurt sur
un `ImportError` au démarrage — pour un moteur dont le contrat est justement de tourner sans écran.
Aucun des trois smokes ne l'aura dit.

**Correctif minimal** (une ligne) :

```python
interdits = re.compile(
    r"^\s*(?:from|import)\s+(research|console|pygame|PySide\d|PyQt\d|qtpy|pyqtgraph)\b",
    re.MULTILINE)
```

**À VÉRIFIER PAR EXÉCUTION** : `python src/core/server.py --smoke` — attendu, avec le motif élargi :
`[smoke-frontiere] 0 violation(s) de frontière · VERDICT : OK`. J'ai vérifié par grep que **rien**
dans `src/core/**/*.py` n'importe PySide6/PyQt/pyqtgraph aujourd'hui (les deux seules occurrences des
chaînes « PySide6 » y sont dans des commentaires : `server.py:4`, `core/__init__.py:23` — le motif
ne matche pas un commentaire, il exige `from`/`import` en début de ligne). Le correctif ne devrait
donc rien faire rougir.

Note secondaire (non corrigée par la ligne ci-dessus, et acceptable) : un import dynamique
(`importlib.import_module("console.grid")`) ou un import relatif (`from ...research import x`)
échappe au motif. C'est un compromis assumé d'un test par expression régulière ; le mentionner dans
la docstring suffirait.

---

### I3 — REMONTÉE 3 : **réelle**. La course de `[smoke-tampon]` : il mesure la cadence temps réel du board BrainFlow, pas la logique de `server.py`

**Fichier** : `src/core/server.py:2494-2530`, assertions `:2526` et `:2528`.

**La course.** Ce test fait tourner un vrai `EngineServer` pendant 3 s (`srv.run(duration_s=3.0)`)
et juge ensuite **les horodatages produits par le thread interne de BrainFlow** :

```python
diffs = np.diff(srv.recent_ts)
chk(bool(np.all(diffs > 0)), "le temps avance strictement, sans doublon ni retour en arrière")
attendu = 1.0 / srv.acq.fs
chk(bool(np.median(diffs) > 0.5 * attendu and np.median(diffs) < 2.0 * attendu), ...)
```

`recent_ts` n'est rien d'autre que `clock.to_lsl(ts_unix)` où `ts_unix` est le canal TIMESTAMP rendu
par `get_board_data()` (`acquisition.py:305-308`, `server.py:1207-1213`). Le serveur **ne fabrique
aucun de ces horodatages** : il les recopie. Ces deux assertions ne testent donc pas `server.py` —
elles testent que le board synthétique de BrainFlow a produit ses échantillons à cadence régulière
pendant ces 3 secondes de temps mural.

Le journal d'exécution du chantier le confirme mot pour mot (`task-2-report.md:73-76`) :

> Un premier lancement a échoué sur `[smoke-tampon]` (« **cadence médiane 0.02 ms attendu 4.00 ms** »),
> précédé dans le log de `data_receiver.cpp ERR| Stream transmission broke off ... re-connecting`

0,02 ms de médiane sur 4,00 ms attendus = les échantillons sont arrivés en **rafale**, tous estampés
à ~50 µs d'écart : le comportement exact d'un producteur qui a été privé de CPU puis a rattrapé son
retard d'un coup. La reconnexion `data_receiver.cpp` juste avant est la cause visible. C'est aussi
pourquoi « isolé en processus seul il passe (~4 s de médiane) » (`progress.md:148`) et pourquoi il a
échoué « jusqu'à 4 fois de suite » (`task-2-report.md:251`) pendant qu'un autre travail chargeait la
machine.

**Scénario reproductible.** Charger le poste (une compilation, un autre smoke, cinq agents) pendant
les 3 s de `srv.run()`. Le thread BrainFlow est préempté ≥ 200 ms, puis vide son tampon : la médiane
des `diff` s'effondre sous `0.5/fs` → ÉCHEC. Aucune ligne de `server.py` n'est en cause. Le même
mécanisme peut faire tomber `np.all(diffs > 0)` si deux échantillons ressortent du rattrapage avec
le même horodatage.

**Une seconde course, plus rare, dans le même test** (`:2533-2536`) : `srv.new_block` est remis à
`None` **à chaque tour** (`server.py:1208`) et n'est repeuplé que si le tour a lu ≥ 1 échantillon.
La boucle sort par le `break` du HAUT (`:1197-1198`), donc `new_block` porte le dernier tour
COMPLET. Un tour de 50 ms qui ne ramène rien (board préempté) laisse `new_block = None` et
`chk(bloc is not None, ...)` rougit, en emportant les trois assertions d'alignement avec lui. Moins
probable que la précédente (50 ms de `POLL_S` pour 4 ms de période d'échantillon), mais c'est la
même cause.

**Correctif minimal — retirer la mesure de temps mural, garder l'alignement.** L'assertion qui a de
la valeur (celle qui a attrapé la mutation `ts_lsl + 1.0/fs`, cf. la docstring `:2504`) est la
comparaison `recent_ts[-n:] == ts_lsl`, et elle ne dépend d'aucune cadence. Les deux assertions
temps réel, elles, ne peuvent rougir que sur une panne de BrainFlow.

1. Supprimer l'assertion de cadence médiane, ou la transformer en **information** (un `print`, pas un
   `chk`) : elle ne teste rien que ce fichier possède.
2. Remplacer `np.all(diffs > 0)` par `np.all(diffs >= 0)` **plus** une assertion sur ce que
   `server.py` fait vraiment : la MONOTONIE de la concaténation, c'est-à-dire que la queue est
   toujours plus récente que la tête (`recent_ts[-1] >= recent_ts[0]`) — invariant du `np.concatenate`
   qui, lui, ne dépend pas du rythme du producteur.
3. Rendre `new_block` déterministe pour le test : boucler jusqu'à en obtenir un, ou faire porter
   l'alignement par le dernier bloc NON VIDE mémorisé plutôt que par le dernier tour.

**À VÉRIFIER PAR EXÉCUTION** (après correctif, en série) :
`python src/core/server.py --smoke` — attendu `[smoke-tampon] VERDICT : OK`, y compris lancé
pendant qu'une autre charge tourne. Sans correctif, la reproduction demande de charger la machine
pendant les 3 s ; ce n'est pas un test de recette.

> Le point de `progress.md:150-153` est juste et vaut d'être redit ici : trois implémenteurs ont
> dépensé du temps à prouver que ce n'était pas eux. Un test qui ne peut rougir que sur une panne
> de l'ordonnanceur n'appartient pas à une suite de recette.

---

### I4 — Le nom du flux public `decoded_errp` est écrit DEUX fois, et aucun test ne lie les deux — le P300 avait résolu exactement ça

**Fichiers** : `src/core/lsl_io.py:448` (`stream_name("decoded_errp")`) et
`src/core/modes/errp.py:492` (`stream="decoded_errp"`).

**Ce qui casse.** `DecodedP300Publisher` porte une constante de classe pour cette raison précise, et
son commentaire est explicite (`lsl_io.py:386-388`) : « Le nom du flux, écrit UNE fois :
`modes/p300.py` le reprend pour son `ModeSpec` au lieu de réécrire le littéral. **Deux sources pour
un contrat public finissent par diverger.** » `p300.py:555` fait `stream=DecodedP300Publisher.SUFFIXE`
et `p300.py:1226` **asserte** l'égalité.

L'ErrP — dont `errp.py` déclare en tête que « ton modèle de forme est `core/modes/p300.py` » — a
repris la convention du MI (deux littéraux) au lieu de celle du P300, et son autotest écrit
`chk(SPEC.status == "moteur" and SPEC.stream == "decoded_errp", ...)` (`errp.py:627`) : **un littéral
comparé à un littéral**, qui ne peut rien attraper du côté du publieur.

**Scénario concret.** Quelqu'un renomme le flux dans `DecodedErrPPublisher` (versionnage,
correction de typo, alignement de nommage) :

```python
info = StreamInfo(stream_name("decoded_errp_v2"), ...)
```

- `python src/core/modes/errp.py` : **vert** (compare `SPEC.stream` à `"decoded_errp"`).
- `python src/core/lsl_io.py` : **vert** (l'autotest §8 vérifie les voies, `no_decision_index` et le
  point de fonctionnement, jamais le NOM du flux).
- `python src/core/server.py --smoke` : **vert** — `_state()` construit `state["streams"]` depuis
  `spec.stream` (`server.py:722-726, 744`), donc depuis le littéral du contrat, jamais depuis
  l'outlet. Et aucun smoke ne démarre l'ErrP (il exige un modèle entraîné, absent d'un dépôt propre).
- `python src/console/app.py --smoke` : **vert**.
- En séance : la page ErrP affiche `EEG_API_Unicorn_decoded_errp` (`mode_page.py:143`,
  `stream_name(self.spec['stream'])`), l'extrait « Brancher un client » que l'étudiant COPIE contient
  `resolve_byprop("name", "EEG_API_Unicorn_decoded_errp", timeout=10)` (`contract.py:691`), et
  ce `resolve_byprop` **ne trouve rien** — le seul symptôme est le `SystemExit("flux introuvable -
  le moteur tourne-t-il, et ce mode est-il demarre ?")` de l'extrait, qui accuse l'étudiant.

**Correctif minimal** (trois lignes, calquées sur le P300) :

```python
# lsl_io.py
class DecodedErrPPublisher:
    SUFFIXE = "decoded_errp"
    def __init__(self, point, n_calib, instance=""):
        info = StreamInfo(stream_name(self.SUFFIXE), "Decoded", len(labels),
                          IRREGULAR_RATE, "float32", _source_id(self.SUFFIXE, instance))

# errp.py
stream=DecodedErrPPublisher.SUFFIXE,

# errp.py, _selftest — remplace le littéral :
chk(SPEC.stream == DecodedErrPPublisher.SUFFIXE, f"...({SPEC.stream})")
```

**Mutation qui rougit** : après correctif, changer `SUFFIXE` fait rougir immédiatement le test du
mode ; aujourd'hui, rien.

---

### I5 — Le « point de fonctionnement MESURÉ » du fixture console (TPR 46 %, TNR 93 %) n'existe nulle part ailleurs, et l'assertion n'ancre aucun taux à son libellé

**Fichier** : `src/console/app.py:547` (le commentaire), `:556-557` (le fixture), `:569-574`
(l'assertion).

**Deux défauts distincts, même bloc.**

**(a) Un chiffre présenté comme mesuré, qui contredit le seul chiffre mesuré du projet.** Le
commentaire écrit :

```
# Ce détecteur, au réglage courant, n'attrape qu'une partie des erreurs (mesuré :
# TPR ~46 %, TNR ~93 %)
```

et le fixture pose `"tpr": 0.4615, "tnr": 0.9259` pour `tnr_target = 0.85`. Or la séance de
référence de ce chantier, à `tnr_target = 0.85`, donne **TPR 0,500 / TNR 0,855** — et cette valeur
est écrite partout ailleurs : `progress.md:10` (« seuil 0,5103 → TPR 0,500 / TNR 0,855 »),
`task-1-report.md:113` (la sortie brute), `docs/superpowers/specs/…-design.md:37`,
`docs/superpowers/plans/…errp-moteur.md:23`, `docs/SPEC.md:491`, `docs/recette.md:560`, la docstring
de `DecodedErrPPublisher` (`lsl_io.py:440-443`), et jusqu'à l'autotest de `lsl_io.py:643`
(`point = {"tnr_target": 0.85, "seuil": 0.42, "tpr": 0.50, "tnr": 0.855}`).

0,4615 = 6/13 et 0,9259 = 25/27 : ce sont des ratios de très petit effectif, pas la séance de
référence (200 événements, 62 erreurs / 138 bonnes). Le fichier `errp.py:475-477` cite d'ailleurs un
TROISIÈME jeu (« garder 95 % n'attrape que 24 %, garder 85 % en attrape 50 %, garder 70 % en attrape
71 % ») et `task-3-report.md:143` un QUATRIÈME (« viser 85 % en attrape 46 % »). Ce projet écrit
noir sur blanc qu'« un chiffre recopié dans une prose finit toujours par mentir »
(`external.py:5-8`) : c'est arrivé, et le mot « mesuré » est de trop.

*Scénario* : un contributeur ouvre le smoke console pour comprendre ce que vaut l'ErrP, lit
« mesuré : TPR ~46 %, TNR ~93 % », et le reporte dans une doc étudiante ou dans un README. Le
produit annonce alors deux points de fonctionnement contradictoires pour le même réglage par défaut.

*Correctif* : aligner le fixture sur la seule mesure réelle — `"tpr": 0.500, "tnr": 0.855`, et les
assertions sur `"50%"` / `"86%"` (`{:.0%}` de 0,855 → `86%`, attention à l'arrondi) — et remplacer
« mesuré » par « fixture, calqué sur la séance de référence (docs/SPEC.md §…) ».

**(b) L'assertion ne dit pas QUEL taux est QUEL.**

```python
chk("46%" in errp_page.vue.avertissement.text() and "93%" in errp_page.vue.avertissement.text(), ...)
```

*Mutation d'une ligne qui reste VERTE* : dans `live_views.py:381-385`, échanger `tnr` et `tpr` —

```python
f"score {score:+.3f} contre seuil {seuil:+.3f} · détecteur IMPARFAIT : garde "
f"{pdf.get('tpr', 0.0):.0%} des bonnes commandes, attrape "
f"{pdf.get('tnr', 0.0):.0%} des erreurs (visé {pdf.get('tnr_target', 0.0):.0%}) …"
```

Le texte contient toujours « 46% » et « 93% » : `python src/console/app.py --smoke` reste **vert**.
Et l'écran annonce alors à l'étudiant que le détecteur **attrape 93 % des erreurs** et n'en garde
que 46 % des bonnes commandes — l'inverse exact de la vérité, sur le seul écran dont la raison d'être
est d'empêcher qu'on prenne ce verdict pour fiable.

*Correctif* : ancrer chaque taux à son libellé.

```python
texte = errp_page.vue.avertissement.text()
chk("garde 93%" in texte and "attrape 46%" in texte,
    f"...chaque taux CÔTÉ SON LIBELLÉ : « garde 93% des bonnes commandes » / « attrape 46% des "
    f"erreurs » — un échange tpr↔tnr doit rougir ici ({texte!r})")
```

(La même faiblesse n'existe PAS dans le test du résumé de tuile `:625`, qui n'affiche que le TPR :
là, l'échange rougit bien.)

---

### I6 — `taux_rejet` / `artefacts` / `epoques_perdues` sont calculés « pour un client » que la console n'implémente pas

**Fichiers** : `src/core/modes/errp.py:258-280` (production) et `src/console/live_views.py:347-387`
+ `src/console/grid.py:214-227` (consommation absente).

**Ce qui casse.** `ErrPRuntime.state()` expose quatre compteurs et un taux, avec cette
justification :

> « le même filet que `P300Runtime.state()` : **sans cette sortie, un client qui n'a pas la console
> ouverte au bon instant ne voit jamais combien d'époques ont été perdues ou écartées, ni si ce
> chiffre est en train de dériver.** »

La panne bruyante n°8 est bâtie dessus (`errp.py:61-66`) : « exposé dans `state()` […] sans quoi un
mode qui écarte 9 époques sur 10 tourne en silence ».

La console est le SEUL client qui lit `state()` (le flux LSL `status` ne transporte pas
`modes_state` — `_state()` s'arrête avant, `snapshot()` seul l'ajoute, `server.py:786-790`). Et elle
n'affiche **aucun** de ces cinq champs : ni la page (`_update_errp` ne lit que `error`, `score`,
`threshold`, `artifact`, `point_de_fonctionnement`), ni la tuile, ni le bandeau (vérifié par grep :
`epoques_perdues|epoques_vues|taux_rejet|artefacts|marqueurs_chauffe` n'apparaît nulle part dans
`src/console/`). Le filet documenté ne mène nulle part ; le seul canal restant est le `print` de
`_verifie_taux_rejet` sur stdout.

**Scénario concret.** Contact d'électrode médiocre, `_sigmas_repos` mesuré pendant que le casque
dérive encore. Sur 40 feedbacks, 36 sont rejetés pour artefact.

- Le flux publie 36 × `error = -1` : correct et honnête, mais indiscernable de 36 clignements.
- La tuile affiche « artefact — fenêtre rejetée » pour le feedback COURANT, et rien d'autre : elle
  dit la même chose qu'un clignement isolé.
- La page affiche « — PAS DE VERDICT : fenêtre rejetée (artefact, σ au-dessus du repos) ».
- Le `taux_rejet = 0.9` que le moteur a calculé exprès est dans `snapshot()`, lu dix fois par
  seconde par `apply_state`, et **jeté**.
- L'étudiant, casque sur la tête et console en plein écran, conclut « ça ne marche pas », refait sa
  séance, et ne saura qu'en retournant dans le terminal de lancement qu'un `[errp] ⚠️ taux de rejet
  artefact élevé : 36/40 (90 %) […] Vérifie le contact des électrodes » l'attendait.

C'est la panne canonique de ce projet (un décodeur honnête qui ne déclenche jamais) sous le visage
que `errp.py:396-408` décrit lui-même.

**Correctif minimal** — une ligne dans `_update_errp`, en queue de l'avertissement :

```python
taux, vues = mode_state.get("taux_rejet"), mode_state.get("epoques_vues") or 0
sante = (f" · rejet artefact {taux:.0%} sur {vues} époque(s)" if taux is not None and vues >= 10
         else "")
```

et l'ajouter au texte des deux branches (`pdf` et sans `pdf`), plus le cas `error < 0`. Un test :
fabriquer un état `taux_rejet: 0.9, epoques_vues: 40` et exiger `"90%"` dans l'avertissement.

*(Le P300 a le même trou. Ne rien faire ici serait cohérent avec lui ; le corriger pour les deux
serait mieux. La constatation est portée par l'ErrP parce que c'est son propre code qui promet la
sortie.)*

---

## MINOR

### M1 — L'échelle adaptative de la tuile ErrP n'est vérifiée par aucune assertion, et elle rend le seuil invisible

**Fichier** : `src/console/grid.py:186-190`, test `src/console/app.py:611-615`.

Le commentaire annonce le point important : « Échelle qui s'adapte à SA PROPRE amplitude, jamais
`NEURO_Z_SPAN` […] le même piège que le P300 rendu comme un SSVEP ». L'assertion, elle, lit
`_values`, `_centre` et `_retenue` — **jamais `_span`**.

*Mutation d'une ligne qui reste verte* : remplacer
`span=max(abs(score), abs(seuil), 1.0)` par `span=NEURO_Z_SPAN`. Le test passe ; la tuile ErrP
retombe exactement dans le défaut que la branche existe pour éviter (score 5,044 écrêté à 100 %,
score 0,8 rendu à 27 % d'une échelle de z qui n'a rien à voir). *Correctif* : ajouter
`and console.grid.tuiles["errp"].apercu._span == 5.044` à l'assertion existante.

Second point, de rendu : avec `score = 5,044` et `seuil = 0,044`, `span = 5,044` → la barre du seuil
fait 0,9 % de la demi-hauteur, donc le plancher de 2 px. Les deux barres censées se comparer sont
« une pleine, une invisible ». Un `span` qui garde un plancher relatif (par ex.
`max(abs(score), 4 * abs(seuil), 1.0)`) ou l'affichage du seuil comme une LIGNE plutôt que comme une
barre serait plus lisible. Non bloquant.

### M2 — `pdf['tpr']` en accès direct, dans la fonction même qui explique 25 lignes plus haut pourquoi il faut `.get`

**Fichier** : `src/console/grid.py:226`.

```python
taux = f" · attrape {pdf['tpr']:.0%} des erreurs" if pdf else ""
```

`_resume` s'ouvre (`:199-201`) sur : « `.get` et pas `[...]` : cette ligne tourne 10 fois par seconde
[…] un mode actif qui publierait des scores sans cible nommée y ferait tomber **TOUTE** l'interface
sur un `KeyError`, pas seulement sa propre tuile. »

Le garde `if pdf` protège du dict vide, pas du dict incomplet. *Scénario* : un futur mode passif (ou
un `ErrPRuntime` dont on ferait évoluer `point_de_fonctionnement` — par exemple en y ajoutant `auc`
et en renommant `tpr` en `tpr_oof`) publie `point_de_fonctionnement` sans clé `tpr` → `KeyError`
dans `ModeGrid.update_from` → **la grille entière** cesse de se rafraîchir, en pleine séance. Le
`_selftest` d'`errp.py:715-718` verrouille aujourd'hui les 4 clés, ce qui rend le cas peu probable —
mais c'est exactement l'argument que le commentaire de `:199` rejette. *Correctif* :
`pdf.get('tpr', 0.0)`, comme `live_views.py:383` le fait déjà pour la même valeur.

### M3 — `tpr_measured` / `tnr_measured` sont mesurés au seuil choisi SUR CES MÊMES scores

**Fichier** : `src/core/lsl_io.py:460-461`, source `core/errp_decoder.py:57-71`.

`pick_threshold` balaie **tous** les seuils candidats et retient, parmi ceux qui atteignent
`TNR >= cible`, celui qui **MAXIMISE la TPR** — puis renvoie la TPR et la TNR **de ce seuil-là, sur
les mêmes scores**. Les scores sont bien hors-pli (`cross_val_predict`, `_oof_auc`), donc honnêtes ;
mais le SEUIL, lui, est choisi en regardant la réponse. `tpr_measured` est donc un maximum sur ~N
candidats, et `tnr_measured >= tnr_target` par construction : les deux sont **optimistes**, d'autant
plus que N est petit.

Le suffixe `_measured` (par opposition à `tnr_target`, « visé ») dit à un client que ce sont des
performances constatées. *Scénario* : une application règle sa politique (« j'annule la commande si
`error == 1`, en sachant que je perds 14,5 % des bonnes commandes ») sur `tnr_measured = 0.855`, et
observe en usage un taux de faux vetos nettement supérieur, sans que rien n'ait changé. *Correctif
minimal, sans toucher au calcul* : dire ce que c'est, dans le champ qui existe déjà pour ça —

```python
desc.append_child_value("measured_on",
                        "1 person, 1 session; threshold selected on these same out-of-fold scores")
```

*(La question du calcul lui-même — un seuil choisi sur un pli imbriqué — appartient à la tranche B ;
ce qui est constaté ici, c'est le contrat publié.)*

### M4 — `measured_on = "1 person, 1 session"` est une constante, pas une mesure

**Fichier** : `src/core/lsl_io.py:463`.

Les quatre autres champs du point de fonctionnement sont réellement dérivés du modèle chargé ;
celui-ci est un littéral. Un modèle entraîné sur deux séances (`groups` porte déjà les blocs, et
`ERRP_CAL_BLOCKS = 5`) publierait « 1 session » sans que rien ne s'en aperçoive. Peu coûteux à
rendre honnête : `ErrPModel` connaît son nombre de groupes — publier
`f"{len(np.unique(groups))} block(s), 1 person"`, ou à défaut retirer la partie « 1 session ».

### M5 — L'extrait « Brancher un client » ne dit rien du `-1`

**Fichier** : `src/core/modes/contract.py:685-701`, affiché par `src/console/mode_page.py:67-76`.

L'extrait générique imprime `dict(zip(voies, valeurs))`. Pour l'ErrP, l'étudiant qui le copie voit
défiler `{'error': -1.0, 'score': 0.0, 'threshold': 0.044, 'artifact': 1.0}` sans un mot sur le fait
que `-1` **n'est pas** « pas d'erreur » et que `score`/`threshold` ne sont alors pas des mesures.
Les métadonnées portent `no_decision_index`, mais l'extrait ne lit jamais `inlet.info().desc()`.

*Scénario* : l'étudiant écrit `if error: annuler()` — vrai pour 1 ET pour -1 — et son application
annule une commande sur chaque clignement, c'est-à-dire précisément aux instants où l'utilisateur
sursaute. C'est le contresens que toute la docstring de `DecodedErrPPublisher` cherche à empêcher, à
un endroit qu'elle n'atteint pas.

Défaut **générique** (tous les modes à `no_decision_index` sont concernés) et **préexistant** : la
correction propre est une ligne de commentaire dans le gabarit, dérivée du contrat —

```python
{"# ⚠️ un indice de -1 = PAS DE DÉCISION, jamais l'indice 0 : cf. no_decision_index dans desc()"
 if any(v in voies for v in ("error", "target_index", "intent_index")) else ""}
```

À arbitrer hors de ce chantier.

---

## Verdict sur les trois remontées

| # | Remontée | Verdict |
|---|---|---|
| 1 | tuile P300 mise à l'échelle sur `Z_MIN` | **RÉELLE** — `grid.py:166`, la sortie P300 n'a pas de `threshold`, donc `Z_MIN = 2,5` s'applique à des log-odds ; avec `centre=False`, tout score négatif (le cas courant) donne un moignon de 2 px. Aucune assertion ne touche `tuiles["p300"].apercu`. La nouvelle tuile ErrP, elle, **échappe** au piège (span propre, `centre=True`) — mais sans test (M1). Détail en **I1**. |
| 2 | `_smoke_frontiere` aveugle à Qt | **RÉELLE** — `server.py:2083` interdit `research|console|pygame` ; CLAUDE.md, `core/__init__.py` et la docstring du test interdisent en plus **Qt**. `PySide6`, `PyQt*`, `qtpy`, `pyqtgraph` passeraient sans un mot. Rien dans `core/` ne les importe aujourd'hui : le correctif d'une ligne ne devrait rien faire rougir. Détail en **I2**. |
| 3 | `[smoke-tampon]` instable | **RÉELLE, et la course est identifiée** — `server.py:2526` et `:2528` jugent la **cadence temps réel du thread BrainFlow**, pas une ligne de `server.py` : les horodatages sont recopiés du board. Une préemption suivie d'un rattrapage en rafale effondre la médiane (échec journalisé : « cadence médiane 0.02 ms attendu 4.00 ms », précédé de `data_receiver.cpp ERR| Stream transmission broke off`). Seconde course, plus rare, sur `new_block` remis à `None` à chaque tour (`:1208`). Détail et correctif en **I3**. |
