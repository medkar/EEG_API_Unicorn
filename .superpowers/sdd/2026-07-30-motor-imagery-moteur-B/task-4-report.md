# Task 4 Report: le moteur joue la calibration

## Statut
**DONE_WITH_CONCERNS** — tout est vert (smoke complet, console, appli pygame, aucun résidu),
mais le code livré s'écarte du brief à trois endroits précis, tous dans `_smoke_calibration()`
et tous forcés par des faits vérifiés à l'exécution (pas des préférences). Détails et
justification ci-dessous ; rien n'a été assoupli en silence.

## Commit
`144de06` — *Let the engine own and play a calibration, start to finish*
(parent : `3d46273`, un seul fichier touché : `src/core/server.py`, +286/-9).

## Ce qui a été fait

Un seul fichier modifié, `src/core/server.py`, en 6 étapes reprenant le brief pas à pas :

1. **`self.keep`** (dimensionnement du tampon) — ajout du terme `epoque_calib` (max de
   `spec.calibration.epoch_s` sur tout le registre) dans le `max(...)` qui calcule `self.keep`,
   et pose de `self.calibration = None` à côté de `self.active = {}`.
2. **Les deux commandes** — `start_calibration` et `cancel_calibration` ajoutées à `COMMANDS` ;
   bloc de validation dans `submit()` (mode inconnu / sans calibration / calibration « natif » /
   déjà une calibration en cours / `contract.validate`) inséré **avant** `self._one(...)`
   (qui exige un mode démarré, ce qu'une calibration n'exige justement pas) ; branchement dans
   `_apply()` ; méthode `_start_calibration()` ajoutée juste après `_recalibrate()`.
3. **Le tick** — `if self.calibration is not None and not self.calibration.terminee:
   self.calibration.tick(self, now)` inséré dans `run()`, juste après la boucle qui tick les
   modes actifs.
4. **La phase publique et l'état** — `"calibrating"` en tête de `_phase_of` (prioritaire sur
   tout le reste) ; `calib` ajouté au tuple de `_status_key` (pour que `status` republie à chaque
   changement de phase de calibration) ; `"calibration": ...` ajouté à `snapshot()`.
5. **Nettoyage à l'arrêt** — dans le `finally` de `run()`, juste avant `self.active = {}` :
   `self.calibration.cancel()` puis `self.calibration = None`.
6. **`_smoke_calibration()`** — écrite après `_smoke_mi()`, branchée dans `_smoke()` au même
   endroit (`and _smoke_calibration()` entre `_smoke_mi()` et `_smoke_cumul()`).

### Vérification de fidélité au brief (automatisée)
J'ai extrait les 12 blocs ```python``` du brief et vérifié, par recherche de sous-chaîne exacte,
lesquels apparaissent tels quels dans le fichier livré :

```
12 blocs de code trouves dans le brief
bloc  1 (16 lignes) : VERBATIM (trouve tel quel)   # self.keep
bloc  2 (4 lignes)  : VERBATIM (trouve tel quel)   # self.calibration = None
bloc  3 (2 lignes)  : VERBATIM (trouve tel quel)   # COMMANDS
bloc  4 (37 lignes) : VERBATIM (trouve tel quel)   # start_calibration / cancel_calibration (submit)
bloc  5 (6 lignes)  : VERBATIM (trouve tel quel)   # _apply
bloc  6 (8 lignes)  : VERBATIM (trouve tel quel)   # _start_calibration
bloc  7 (4 lignes)  : VERBATIM (trouve tel quel)   # tick dans run()
bloc  8 (6 lignes)  : VERBATIM (trouve tel quel)   # _phase_of
bloc  9 (4 lignes)  : VERBATIM (trouve tel quel)   # _status_key
bloc 10 (5 lignes)  : VERBATIM (trouve tel quel)   # snapshot()
bloc 11 (5 lignes)  : VERBATIM (trouve tel quel)   # finally de run()
bloc 12 (144 lignes): DIFFERENT                     # _smoke_calibration()
```
Les étapes 1 à 5 sont donc **verbatim, au caractère près**. Seule `_smoke_calibration()` (étape 6)
diffère du brief, à trois endroits, tous documentés ci-dessous et dans le code lui-même (commentaires
`⚠️ ÉCART AU BRIEF`).

## Écarts par rapport au brief — les trois, avec diagnostic

### 1. `trials_per_class: 6` refusé — « Essais par classe » est un `choice`, pas un entier libre

**Symptôme** (premier `python src/core/server.py --smoke`) :
```
ÉCHEC la calibration est acceptée ({'accepted': False, 'reason': "« Essais par classe » : 6
       n'est pas un choix valide (10, 14, 18, 26)"})
```
**Diagnostic** : `mi_calib.CALIB.params` déclare `trials_per_class` avec `kind="choice",
choices=MI_SESSIONS` où `MI_SESSIONS = (10, 14, 18, 26)` (`core/config.py`), posé par une tâche
antérieure de ce même chantier. `contract.validate` refuse donc toute valeur hors de cette liste,
y compris `6`. Ce n'est pas un défaut de mon câblage : `contract.validate` fait exactement ce que
son propre autotest (`contract.py::_selftest`) documente pour un « choice ».

**Correctif** : remplacé `6` par un choix valide. Voir écart 3 (le choix précis, `18`, est motivé
par la fiabilité statistique, pas seulement par la validité du contrat).

### 2. `imagery_s=0.20 / window_s=0.10` — infaisable avec le filtre réellement utilisé par `MIModel`

**Symptôme** (une fois l'écart 1 corrigé avec `trials_per_class=10`) :
```
[calib] entraînement impossible : ValueError : The length of the input vector x must be greater
        than padlen, which is 27.
```
**Diagnostic** : `MIModel._prep` passe chaque fenêtre dans `mi_decoder.bandpass()`, qui appelle
`scipy.signal.filtfilt` sur un Butterworth passe-bande d'ordre 4. Vérifié directement :
```python
>>> from scipy.signal import butter
>>> b, a = butter(4, [8/(250/2), 30/(250/2)], btype="band")
>>> len(a), len(b)
(9, 9)
>>> 3 * max(len(a), len(b))   # padlen par défaut de filtfilt
27
```
`filtfilt` exige une entrée **strictement plus longue** que `padlen`. Une fenêtre `window_s=0.10 s`
à 250 Hz ne fait que 25 échantillons — sous le plancher de 27. Le brief respecte pourtant bien sa
propre règle (« `window_s`/`step_s` se raccourcissent AVEC `imagery_s`, pas séparément », rapport
0,5 / 0,25 conservé) : le problème n'est pas le rapport, c'est l'échelle absolue.

**Correctif** : passage à `imagery_s=0.32 / window_s=0.16 / step_s=0.08` (même rapport 0,5 / 0,25,
donc toujours 3 fenêtres/essai comme en séance réelle — vérifié : `n_fenetres=162` pour 54 essais).
`window_s * 250 = 40` échantillons, confortablement au-dessus de 27.

### 3. Le modèle produit dans le dossier temporaire n'est pas « visible » pour `start_mode`

**Symptôme** (une fois les écarts 1 et 2 corrigés) :
```
ÉCHEC le mode MI démarre sur le modèle qui vient d'être entraîné ({'accepted': False, 'reason':
       "« Modèle entraîné » : aucun choix disponible — ..."})
```
**Diagnostic** : le `Param` « model » de `mi.SPEC` résout ses choix via
`choices_fn=lambda: mi_models.modeles_disponibles()` — **sans argument**, donc contre le VRAI
`DATA_DIR`. Le brief garde pourtant tout dans un dossier temporaire (c'est même l'invariant que sa
propre docstring promet : « Le vrai `data/` n'est jamais approché »). Ces deux exigences du brief
— ne jamais toucher `data/`, et voir `start_mode` accepter le modèle produit — sont donc
incompatibles telles quelles : sans redirection, `contract.validate` ne trouvera JAMAIS le modèle
temporaire dans ses choix. Ce n'est pas nouveau dans ce dépôt : `core/modes/mi.py::_selftest`
contourne exactement le même piège en monkeypatchant `mi_models.modeles_disponibles`.

**Correctif** : même monkeypatch, borné au strict nécessaire. `contract.validate` (donc
`choices_fn`) tourne de façon SYNCHRONE dans `submit()`, sur le fil du test — la redirection n'a
donc besoin de vivre que le temps de cet appel :
```python
vrai_disponibles = mi_models.modeles_disponibles
mi_models.modeles_disponibles = lambda d=dossier: vrai_disponibles(d)
try:
    demarrage = server.submit("start_mode", id="mi", params={"mi": {"model": produits[0]}})
finally:
    mi_models.modeles_disponibles = vrai_disponibles
```
Vérifié que la suite (`MIRuntime.__init__` → `mi_models.charger(params["model"])`) charge par
CHEMIN direct et ne consulte jamais `modeles_disponibles` — la restauration immédiate après
`submit()` ne casse donc rien côté boucle moteur (qui traite `start_mode` plus tard, sur son
propre fil).

### Réserve : fragilité statistique résiduelle sur `cv_groupee_ < cv_naive`

Ce n'est pas à proprement parler un « écart » (l'assertion du brief est restée intacte, stricte),
mais une propriété que j'ai mesurée et qu'il faut connaître avant de lire un futur échec de CETTE
seule ligne comme une régression.

**Ce que dit le code** (`mi_decoder.py`, docstring de `_test_cv_honnete`) : « L'invariant de la CV
groupée : elle doit être INFÉRIEURE à la naïve, toujours ». Vrai de façon fiable sur les autotests
existants (`mi_calib._selftest`, `mi_decoder._test_cv_honnete`) — mais ceux-là fabriquent une ERD
corrélée à la classe (`synth_mi_trial`). `_smoke_calibration()`, lui, entraîne sur le bruit RÉEL du
board synthétique (c'est tout l'intérêt du test : exercer `engine.recent_window` pour de vrai) —
aucun signal appris, donc la comparaison de deux estimations de CV bruitées n'est qu'une TENDANCE
statistique (le biais de fuite entre fenêtres qui se chevauchent), pas une garantie mathématique.

Mesuré en isolant juste la calibration (script jetable, contre le VRAI `EngineServer`, jamais commis) :

| `trials_per_class` | tirages | violations de l'invariant |
|---:|---:|---:|
| 10 (le plus petit choix valide) | 4 | **2/4** |
| 18 (retenu) | 6 | **1/6** |

Plus de données (18 plutôt que 10) réduit nettement le taux d'échec sans l'annuler — attendu,
puisqu'il n'y a structurellement aucun signal à apprendre dans ce bruit. Pousser à 26 (le choix
maximal) coûterait encore ~15 s de plus par run pour un gain incertain ; je n'ai pas jugé ça
rentable. J'ai donc gardé l'assertion STRICTE (pas de `<=`, pas de retrait), choisi `18` comme
compromis mesuré, et documenté le risque résiduel en commentaire à côté de l'assertion elle-même
et ici. **Un échec isolé de cette seule ligne appelle un nouveau run avant diagnostic ; un échec de
n'importe quelle autre assertion du test, lui, est significatif.**

## Commandes de test lancées, EN SÉRIE, avec leur sortie réelle

### 1. `python src/core/server.py --smoke` — état final (après les 3 corrections ci-dessus)
Sortie complète (bruit BrainFlow `netinterfaces`/`data_receiver` omis) :
```
[smoke] VERDICT : OK
[smoke-registry] 7 modes, dont 4 dans le moteur — OK
[smoke-frontiere] 0 violation(s) de frontière
[smoke-frontiere] VERDICT : OK
[smoke-repos] VERDICT : OK
[smoke-ssvep] VERDICT : OK
[smoke-neuro] VERDICT : OK
[smoke-mi] VERDICT : OK
[server] board=SYNTHETIC_BOARD fs=250 Hz instance=smoke-calib
  OK   la calibration est acceptée ({'accepted': True, 'command': 'start_calibration', 'id': 'mi',
       'params': {'trials_per_class': 18}})
[server] Calibration Motor Imagery : 54 essais, ≈ 0 min — stabilisation 0 s d'abord
  OK   une seconde calibration est refusée ({'accepted': False, 'reason': "une calibration est
       déjà en cours (Motor Imagery) — abandonne-la avant d'en lancer une autre"})
  OK   la phase publique du moteur devient « calibrating » (calibrating)
  OK   et snapshot() porte l'état complet ({'mode_id': 'mi', ..., 'total': 54, ...})
[mi-calib] accuracy HONNÊTE (validation croisée par essai) : 36.8% — hasard 33% — FAIBLE
[mi-calib] (pour mémoire, la CV naïve, fenêtres mélangées : 38.9% — gonflée, ne pas s'y fier)
  OK   la séance aboutit (fini ; problème='')
  OK   54 essais enregistrés (54)
  OK   chaque époque fait exactement 80 échantillons ([80])
  OK   le tampon du moteur tient une époque de calibration entière : keep=1250 pour 1000 + marge 250
  OK   et il en rend une COMPLÈTE : 1000 échantillons pour 1000 demandés
  OK   le modèle produit est chargeable et listé ([...mi_model_20260731-093246.joblib])
  OK   l'accuracy rapportée est l'HONNÊTE, plus basse que la naïve (0.3684848484848..., 0.389204...)
  OK   le mode MI démarre sur le modèle qui vient d'être entraîné ({'accepted': True,
       'command': 'start_mode', 'ids': ['mi']})
[server] arrêt : 6700 échantillons publiés en 26.9 s (249.2 Hz effectif)
[smoke-calib] VERDICT : OK
[smoke-cumul] VERDICT : OK
[smoke-proposition] VERDICT : OK
```
`EXIT_CODE=0`. Les deux runs précédents (avant correctifs 1, puis 2+3) sont montrés dans les
sections « Écarts » ci-dessus avec leur échec réel.

Note de calibrage du dimensionnement de `keep` : `keep=1250` pour un besoin `1000` (`MI_IMAGERY_S
× fs = 4.0 × 250`) `+ marge 250` (`margin_n`) — c'est le terme `epoque_calib` de l'étape 1 qui
porte ces 1000 échantillons ; sans lui, `keep` aurait plafonné à `int(MI_WINDOW_S × 250) = 500`
(le max des AUTRES modes), et la seconde assertion du test du tampon (`recent_window(MI_IMAGERY_S)`
rend exactement 1000 échantillons, pas moins) l'aurait détecté.

### 2. `python src/console/app.py --smoke` (non-régression)
```
  OK   [...50 lignes de chk, toutes OK...]
[console-smoke] VERDICT : OK
```
`CONSOLE_EXIT_CODE=0`.

### 3. `python src/research/app.py --smoke` (non-régression)
```
[app] smoke OK : menu + SSVEP + c-VEP (eCCA & rCCA) + MI + P300 + neuro + ErrP(cal+démo) câblés
      (headless).
```
`RESEARCH_EXIT_CODE=0`.

Les trois commandes ont été lancées STRICTEMENT en série (jamais deux processus moteur/appli en
même temps), comme l'exige le projet.

## Vérification d'absence de résidu

Après le smoke complet **et** les deux non-régressions :
```
$ git status --porcelain
 M src/core/server.py

$ ls -la --time-style=full-iso data/mi_model_* data/mi_calib_*
-rw-r--r-- ... 2026-07-22 14:18:10 data/mi_calib_last.npz
-rw-r--r-- ... 2026-07-22 13:48:38 data/mi_model_full42.joblib
-rw-r--r-- ... 2026-07-21 16:34:32 data/mi_model_pre_car.joblib
-rw-r--r-- ... 2026-07-22 14:18:10 data/mi_model_short30.joblib

$ ls data/*smoke* 2>&1
ls: cannot access 'data/*smoke*': No such file or directory
```
Aucun fichier daté d'aujourd'hui (2026-07-31) : les 4 fichiers `mi_*` de `data/` sont tous
antérieurs (21-22 juillet), donc préexistants et non touchés par ce travail. `research/app.py
--smoke` écrit puis retire lui-même ses propres `*_smoke*` (`cvep_model_smoke.npz`,
`p300_model_smoke.joblib`, etc. vus dans sa sortie) — confirmé absents après coup. Aucun dossier
temporaire (`srv_calib_*`, ni les `probe_calib_*` de mon script d'investigation jetable) n'a
survécu dans le dossier Temp de Windows. Le seul changement dans le dépôt est le fichier attendu,
`src/core/server.py`.

## Auto-relecture

### Les trois pièges signalés dans la consigne
1. **Le `finally` de restauration écrit AVANT le corps** : respecté à l'identique du brief — le
   `try/finally` extérieur englobe TOUT (monkeypatch des durées ET du `__init__`), donc la
   restauration (`mi_calib.MICalibration.__init__ = ancien_init` + restauration des 7 attributs +
   `shutil.rmtree`) s'exécute sur TOUTE sortie du bloc, y compris une levée dans
   `EngineServer(...)` ou une assertion qui lève avant la fin. Vérifié en pratique : les DEUX
   itérations ratées (écarts 1 et 2 ci-dessus) ont bien laissé `mi_calib.MICalibration` intacte
   pour le run suivant — sinon les corrections successives n'auraient pas pu être testées l'une
   après l'autre dans le même processus sans redémarrer Python.
2. **`window_s`/`step_s` raccourcis AVEC `imagery_s`, pas séparément** : respecté — et c'est
   précisément parce que je l'ai respecté (rapport 0,5 / 0,25 conservé) que l'écart 2 a été un vrai
   diagnostic (`padlen`) et non une simple relecture distraite du brief.
3. **Le test du tampon est double** : les deux assertions (`server.keep >= besoin + margin_n` ET
   `len(server.recent_window(MI_IMAGERY_S)) == besoin`) sont toutes les deux présentes, verbatim,
   et toutes les deux passent (`keep=1250` pour `besoin=1000`, bloc rendu de longueur `1000`) — sur
   des durées de PROTOCOLE rabotées (`imagery_s=0.32` pour la séance jouée) mais un test du DÉFAUT
   qui interroge `MI_IMAGERY_S` (la vraie constante, 4.0 s), exactement comme demandé.

### Ce qui n'a pas été touché en dehors du périmètre
- Aucun fichier autre que `src/core/server.py`.
- Aucune valeur de `core/config.py` (`MI_SESSIONS`, `MI_IMAGERY_S`, `MI_WINDOW_S`...) modifiée —
  les écarts jouent uniquement sur les valeurs MONKEYPATCHÉES à l'intérieur du smoke, jamais sur
  le contrat réel.
- `MI_SESSIONS`, la contrainte `padlen` du filtre, et `mi.SPEC`'s `choices_fn` sont des faits du
  code existant (posés par des tâches antérieures de ce chantier), pas des choix que j'ai
  introduits ou pourrais changer depuis `server.py`.

### Point resté ouvert, volontairement
La fragilité résiduelle sur `cv_groupee_ < cv_naive` (section dédiée plus haut) n'a pas de
correctif propre dans le périmètre de cette tâche (je ne modifie que `server.py`, et le fond du
problème — comparer deux CV sur du bruit sans signal — ne se résout pas par un réglage côté
moteur). Signalé pour triage éventuel par la revue du chantier : soit accepter le risque résiduel
mesuré (~1/6), soit revoir un jour cette assertion précise (tolérance `<=`, ou plusieurs tentatives
internes) si elle se révèle gênante en pratique — je ne l'ai pas fait moi-même pour ne pas
affaiblir un invariant du projet sans mandat explicite.

## Résumé des tests (une ligne)
3 commandes lancées EN SÉRIE (`server.py --smoke`, `console/app.py --smoke`, `research/app.py
--smoke`), toutes en exit code 0 / VERDICT OK au dernier run, `git status` propre et aucun fichier
`data/` daté d'aujourd'hui ; 3 écarts au brief dans `_smoke_calibration()` (valeur de
`trials_per_class` hors contrat, fenêtre sous le `padlen` du filtre passe-bande, modèle temporaire
invisible du `choices_fn` de `mi.SPEC`), tous diagnostiqués à la source et corrigés au minimum
nécessaire, plus une fragilité statistique résiduelle documentée (~1 tirage sur 6) sur une seule
assertion, non corrigée par choix.

---

## Tour de correction 1/5 — sortir la comparaison de CV du verdict, protéger un déréférencement

### Statut
**DONE**

### Commit
`172f32a` — *Stop asserting an order on noise, and stop crashing on a broken build*
(parent `04c7773`, qui n'est pas de moi — voir plus bas — lui-même après `144de06` ; seul fichier
touché : `src/core/server.py`, +19/-10).

### Ce que la relecture a demandé
Relecture externe (re-dérivation depuis la source) : code de production (étapes 1-5) et les 3
écarts documentés plus haut approuvés SANS réserve. Un seul constat retenu — exactement celui que
j'avais moi-même signalé comme « réserve résiduelle » sans le corriger, faute de mandat :
`chk(res.get("cv_groupee") is not None and res["cv_groupee"] < res["cv_naive"], ...)` conclut sur
du bruit (aucune ERD fabriquée dans `_smoke_calibration`, contrairement à `mi_calib._selftest` et
`mi_decoder._test_cv_honnete`) — exactement ce que la règle permanente du projet (« ne jamais
conclure sur du bruit ») interdit — et comme `_smoke()` enchaîne ses sous-smokes avec `and`, une
bascule sur cette seule ligne aurait aussi sauté silencieusement `_smoke_cumul` et
`_smoke_proposition` pour ce run.

Deux corrections demandées, rien d'autre :
1. Sortir la COMPARAISON du verdict (`chk` → `print` d'information), garder `cv_groupee is not
   None` comme assertion (fait déterministe).
2. Protéger `calib._enregistre` (ligne alors 1387), déréférencé juste après un `chk(calib is not
   None ...)` qui ne court-circuite pas.

### Ce qui a été fait
Dans `_smoke_calibration()`, à l'endroit exact indiqué :

**1. La CV, en deux morceaux.** Remplacé
```python
chk(res.get("cv_groupee") is not None and res["cv_groupee"] < res["cv_naive"],
    f"l'accuracy rapportée est l'HONNÊTE, plus basse que la naïve "
    f"({res.get('cv_groupee')}, {res.get('cv_naive')})")
```
par
```python
chk(res.get("cv_groupee") is not None,
    f"l'accuracy HONNÊTE (validation croisée par essai) est rapportée "
    f"({res.get('cv_groupee')})")
print(f"[smoke-calib] pour mémoire, PAS une assertion (cf. commentaire ci-dessus) : "
      f"cv_groupee={res.get('cv_groupee')} cv_naive={res.get('cv_naive')}")
```
avec un commentaire qui nomme explicitement `mi_calib._selftest()` et `mi_decoder._test_cv_honnete()`
comme les endroits où l'invariant a un sens et reste vérifié — pour qu'un lecteur ne lise pas ce
retrait comme un abandon.

**2. L'accès protégé.** Remplacé
```python
longueurs = {len(e) for e, _l in calib._enregistre}
```
par
```python
longueurs = {len(e) for e, _l in calib._enregistre} if calib is not None else set()
```
avec un commentaire expliquant pourquoi (`chk` n'interrompt jamais le flux). Sur un build cassé,
`longueurs` devient `set()`, le `chk(longueurs == {attendu}, ...)` échoue proprement (ÉCHEC
imprimé) et le reste du test continue à diagnostiquer ligne par ligne, au lieu de lever
`AttributeError: 'NoneType' object has no attribute '_enregistre'` — exactement ce qui s'était
produit dans MA PROPRE toute première tentative (avant correction de l'écart 1, documentée plus
haut), preuve que ce n'est pas un cas théorique.

Rien d'autre n'a été touché — en particulier, `produits[0]` (risque d'`IndexError` similaire, plus
bas dans la même fonction, si l'entraînement échoue) N'A PAS été protégé : hors du périmètre
explicitement fixé par la relecture (« Ne touche à rien d'autre »), donc laissé tel quel.

### Le commit `04c7773`, entre-temps
Signalé par le correcteur, vérifié en lecture seule (je n'y ai pas touché, hors de mon périmètre
`server.py`) : `src/core/modes/calibration.py` (fix `now=0.0` vs `now=None` dans `state()`) et
`src/core/modes/mi_calib.py` (`_chemins_libres` : recherche d'un couple de noms réellement libres
au lieu d'un simple horodatage, pour une garantie de non-écrasement qui tienne même à la même
seconde). Aucun des deux ne touche `MICalibration.__init__` ni la signification de `self.dossier` —
le mécanisme de redirection de `_smoke_calibration` (monkeypatch de `__init__` pour injecter
`dossier=dossier`) reste donc valable tel quel. Confirmé à l'exécution : cf. tests ci-dessous, dont
le run RÉEL passe maintenant par ce code modifié (nom de fichier produit :
`mi_model_20260731-100112.joblib`, cohérent avec `_chemins_libres`).

### Commandes de test lancées, EN SÉRIE, avec leur sortie réelle

**1. `python src/core/server.py --smoke`** — sortie du bloc `smoke-calib` (le reste est identique
à la section précédente, tous les autres sous-smokes toujours OK) :
```
  OK   la calibration est acceptée ({'accepted': True, 'command': 'start_calibration', 'id': 'mi',
       'params': {'trials_per_class': 18}})
[server] Calibration Motor Imagery : 54 essais, ≈ 0 min — stabilisation 0 s d'abord
  OK   une seconde calibration est refusée (...)
  OK   la phase publique du moteur devient « calibrating » (calibrating)
  OK   et snapshot() porte l'état complet (...)
[mi-calib] accuracy HONNÊTE (validation croisée par essai) : 27.6% — hasard 33% — FAIBLE — ...
[mi-calib] (pour mémoire, la CV naïve, fenêtres mélangées : 33.3% — gonflée, ne pas s'y fier)
[mi-calib] modèle : ...\srv_calib_jezw7bs8\mi_model_20260731-100112.joblib
[mi-calib] enregistrement : ...\srv_calib_jezw7bs8\mi_calib_20260731-100112_n54.npz
  OK   la séance aboutit (fini ; problème='')
  OK   54 essais enregistrés (54)
  OK   chaque époque fait exactement 80 échantillons ([80])
  OK   le tampon du moteur tient une époque de calibration entière : keep=1250 pour 1000 + marge 250
  OK   et il en rend une COMPLÈTE : 1000 échantillons pour 1000 demandés
  OK   le modèle produit est chargeable et listé ([...mi_model_20260731-100112.joblib])
  OK   l'accuracy HONNÊTE (validation croisée par essai) est rapportée (0.27636363636363637)
[smoke-calib] pour mémoire, PAS une assertion (cf. commentaire ci-dessus) : cv_groupee=0.2763... cv_naive=0.3333...
  OK   le mode MI démarre sur le modèle qui vient d'être entraîné ({'accepted': True,
       'command': 'start_mode', 'ids': ['mi']})
[server] arrêt : 6656 échantillons publiés en 26.8 s (248.6 Hz effectif)
[smoke-calib] VERDICT : OK
```
`SERVER_EXIT_CODE=0`. À noter : sur CE run, `cv_groupee (27,6 %) < cv_naive (33,3 %)` — l'ordre
« attendu » sort quand même, mais ce n'est plus lui qui fait passer ou échouer le test ; c'est bien
`res.get("cv_groupee") is not None` (toujours vrai dès que l'entraînement aboutit) qui porte
l'assertion. Le `[smoke-calib] VERDICT : OK` global, lui, reste inchangé — les 8 autres `chk` du
bloc calibration passent tous, comme lors du run précédent.

**2. `python src/console/app.py --smoke`** (non-régression, imposée par la consigne de correction) :
```
  [...50 lignes de chk, toutes OK...]
[console-smoke] VERDICT : OK
```
`CONSOLE_EXIT_CODE=0`.

Les deux commandes ont été lancées STRICTEMENT en série.

### Vérification d'absence de résidu
```
$ git status --short
 M src/core/server.py

$ ls -la --time-style=full-iso data/mi_model_* data/mi_calib_*
-rw-r--r-- ... 2026-07-22 14:18:10 data/mi_calib_last.npz
-rw-r--r-- ... 2026-07-22 13:48:38 data/mi_model_full42.joblib
-rw-r--r-- ... 2026-07-21 16:34:32 data/mi_model_pre_car.joblib
-rw-r--r-- ... 2026-07-22 14:18:10 data/mi_model_short30.joblib

$ ls data/*smoke* 2>&1
ls: cannot access 'data/*smoke*': No such file or directory
```
Toujours aucun fichier daté d'aujourd'hui, toujours le seul fichier modifié attendu.

### Auto-relecture de ce tour
- Portée respectée à la lettre : les deux seuls changements demandés, rien de plus (en particulier,
  pas de correction du risque `IndexError` sur `produits[0]`, repéré mais explicitement hors
  mandat).
- L'invariant honnête/naïve n'est pas « supprimé » : il est toujours vérifié, mais maintenant
  UNIQUEMENT là où la relecture (et moi, dans le rapport initial) avons constaté qu'il a un sens
  statistique — `mi_calib._selftest()` et `mi_decoder._test_cv_honnete()`, tous deux inchangés,
  tous deux sur de l'ERD fabriquée.
- Vérifié que la garde sur `calib._enregistre` ne change AUCUN comportement sur le chemin normal
  (`calib is not None` dans tous les runs verts) — elle ne s'active que sur le chemin d'échec, et
  seulement là.
- `04c7773` n'a pas été touché ; son impact sur ce fichier a été vérifié par lecture puis confirmé
  par l'exécution réelle (nom de fichier produit conforme à `_chemins_libres`), pas supposé.

### Résumé des tests (une ligne)
2 commandes lancées EN SÉRIE (`server.py --smoke`, `console/app.py --smoke`), toutes en exit code 0
/ VERDICT OK, `git status` propre, aucun fichier `data/` daté d'aujourd'hui ; les 2 corrections
demandées appliquées à l'identique de la consigne, rien d'autre touché.
