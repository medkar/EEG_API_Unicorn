# Task 2 — rapport : le mode dans le moteur — phase, états muets, décision

**Statut : DONE**
**Commit : `4315d00` — "Give the c-VEP a runtime that knows when it does not know the phase"**
Base : `a0fd4ab` (fin de la tâche 1). Un seul commit, contient tout (test + implémentation +
mutations vérifiées puis retirées).

---

## Étape 1 — écrire le test de phase et ses trois états muets

Le snippet du brief (`_runtime_de_test`, `phase_a`, péremption) recopié dans `_selftest()` de
`src/core/modes/cvep.py`, avec une addition : le TROISIÈME état muet que `phase_a` documente en
commentaire (`age < 0.0`, un `t_fin` antérieur au dernier marqueur connu) n'était exercé par
AUCUN `chk()` du snippet fourni — seuls « aucun marqueur » et « périmé » l'étaient. Ajouté :

```python
chk(rt.phase_a(100.0 - 1.0) is None,
    f"un instant ANTÉRIEUR au dernier marqueur connu n'a pas de phase valide non plus "
    f"({rt.phase_a(100.0 - 1.0)})")
```

`_runtime_de_test(code_len=63, refresh=60.0)`, non défini par le brief (ambiguïté tranchée à
l'avance) : une fabrique qui construit un `CVEPModel` synthétique de la forme voulue (voies
`CVEP_CHANNELS`, `code_len`/`refresh` donnés — les valeurs de `w`/`template` n'ont aucune
importance, aucun test de ce fichier ne décode dessus), le sauvegarde dans un dossier temporaire,
et construit un `CVEPRuntime` par le chemin RÉEL (`validate(SPEC, {})` puis `CVEPRuntime(...)`) —
pas de raccourci qui court-circuiterait les refus que ce fichier protège. `CVEP_MODEL_PATH` (la
constante de `core/config.py`, importée dans `cvep.py`) est repointée le temps du bloc, via un
context manager `_modele_temporaire`, puis restaurée — jamais le vrai `data/cvep_model.npz` du
dépôt, ni lu ni modifié par ce fichier de test.

## Étape 2 — lancer, vérifier l'échec

```
$ python src/core/modes/cvep.py
...python.exe: can't open file '...\src\core\modes\cvep.py': [Errno 2] No such file or directory
EXIT CODE: 2
```

Même écart qu'à la tâche 1, pour la même raison (le lanceur Python, pas l'interpréteur, faute de
fichier à exécuter) : sens identique (le fichier n'existe pas encore, exit ≠ 0).

## Étape 3 — le cœur du runtime, et UN DÉFAUT MESURÉ dans le brief lui-même

`maj_reference`/`phase_a` écrits d'après le snippet du brief, la garde de rafraîchissement de
l'étape 5 fusionnée dans `maj_reference` (son unique point d'entrée logique : c'est le seul
endroit qui reçoit `refresh` en provenance d'un marqueur). Renommé `refresh_declare` → `refresh`
pour coller à la signature de `maj_reference(self, ts, refresh)` donnée par le brief lui-même — le
test l'appelle en mot-clé (`rt.maj_reference(ts=..., refresh=...)`), donc le paramètre DOIT
s'appeler `refresh`.

**Écart signalé au brief, mesuré, pas supposé.** Après avoir écrit `phase_a` EXACTEMENT comme
donné (`int(age * self._ref_refresh) % self.code_len`, sans tolérance), la 5ᵉ assertion du test
mandaté échouait :

```
  OK   dix frames plus tard, phase = 10 (10)
  ÉCHEC un cycle entier plus tard, la phase est REVENUE à 0 (modulo la longueur du code)
```

Diagnostic, à l'interpréteur :

```python
>>> t_fin = 100.0 + 63 / 60.0; age = t_fin - 100.0
>>> age
1.0499999999999972          # jamais 1.05 exactement — arrondi binaire
>>> age * 60.0
62.99999999999983
>>> int(age * 60.0)
62                          # tronqué vers 62 au lieu de 63 -> phase 62 au lieu de 0
```

**Exactement la même classe de bug, au même ordre de grandeur, que celle déjà documentée et
corrigée dans `src/core/modes/registry.py` (`_EPS_S = 1e-9`, commentaire : « 0.15 + 0.80 vaut
0.9500000000000001 en flottant »)** — vérifié en rejouant ce cas précis :

```python
>>> 0.15 + 0.80
0.9500000000000001
```

La formule littérale du brief échoue donc sur son PROPRE test de bord de cycle. Corrigé par une
tolérance nommée, avec sa mesure en commentaire (`_EPS_FRAME = 1e-9`, même valeur que `_EPS_S`,
même justification : 1 ns n'a aucune commune mesure avec un échantillon EEG à 250 Hz ni une frame
d'écran à 60 Hz) :

```python
return int(age * self._ref_refresh + _EPS_FRAME) % self.code_len
```

`__init__` construit aussi `self.plan, self.code = build_targets()` (interface listée comme
« consommée » par le brief) et refuse si `self.model.code_len != len(self.code)`
(`_desaccord_code`) — un modèle calibré avant un changement de `CVEP_BITS` porterait un
`code_len` différent, et `phase_a` continuerait de rendre un entier plausible modulo un AUTRE
nombre que celui du code réellement affiché. Même famille de panne que le désaccord de
rafraîchissement, découverte pour la même raison. `code_len` est pris sur `self.model` (pas sur
`len(self.code)`) : c'est le modèle qui fait autorité sur ce qu'il a appris, la config actuelle
n'intervient que pour vérifier l'accord.

Le chargement du modèle passe par `_charger(chemin)`/`_modeles_disponibles()`, deux fonctions
PROVISOIRES écrites sur le patron exact de `errp_models.charger`/`p300_models.charger`
(`(modèle, None)` ou `(None, raison)`, ne lève jamais) — `core/cvep_models.py` (catalogue
multi-modèles, tâche 3) n'existe pas encore, donc ces deux fonctions ne connaissent qu'UN chemin
fixe (`CVEP_MODEL_PATH`), documenté comme tel pour que la tâche 3 n'ait qu'à les remplacer.

## Étape 4 — SPEC

Écrite selon le brief : `id="cvep"`, `label="c-VEP"`, `family="actif"`, `status="moteur"`,
`stream="decoded_cvep"`, `runtime_cls=CVEPRuntime`, `marker_epoch_s=2.1` (2 × 63/60, avec le
commentaire explicite « dimensionne le tampon, ne décrit AUCUNE époque »), `rest` et `calibration`
recopiés tels quels (y compris `label="Calibrer"` sur la `Calib`, un détail qui diffère de
`errp.py`/`p300.py` — leurs `Calib(kind="natif", ...)` ne posent pas ce champ ; suivi à la lettre
du brief plutôt que du patron, faute d'explication pour trancher autrement).

Deux champs que le brief ne mentionne pas ont été laissés à leur défaut, en connaissance de cause :
`params=` porte SEULEMENT `model` (pas de `stream_in` : ce fichier ne consomme pas encore
`engine.markers_murs()`, cf. doutes) ; `channels=()` (pas de `channels_fn` : `cvep_channel_labels`
n'existe pas avant la tâche 4, `lsl_io.py`).

`CVEPRuntime` n'expose délibérément PAS `pre_s`/`post_s` (contrairement à `P300Runtime`/
`ErrPRuntime`) — testé explicitement (`not hasattr(CVEPRuntime, "pre_s")`) : en ajouter ferait
croire à `registry.check()` qu'il doit comparer `marker_epoch_s` à `pre_s+post_s`, la logique de
troncature d'époque qui ne s'applique pas ici.

## Étape 5 — le refus sans modèle et le refus de rafraîchissement

Les deux refus, plus un troisième ajouté (voir étape 3) :
- **Sans modèle** : `_modeles_disponibles()` rend `()` si `CVEP_MODEL_PATH` n'existe pas ou n'est
  pas chargeable → `validate(SPEC, {})` refuse avec « aucun choix disponible » et le geste à faire
  (`python src/research/app.py`, mode c-VEP). Testé via `_modele_temporaire(None)`.
- **Rafraîchissement en désaccord** : `maj_reference` refuse un écart de plus de 1 Hz, en nommant
  les deux fréquences et la commande de relance (`--refresh {…:.0f}`). Testé aux DEUX bornes : un
  désaccord franc (60 vs 75 Hz) refuse ; un petit écart de mesure (60 vs 60,4 Hz, sous la
  tolérance) passe.
- **Code en désaccord** (ajouté) : un modèle à `code_len=31` passe la validation du CHOIX (rien
  n'y regarde le code) mais la CONSTRUCTION refuse, en nommant les deux longueurs et `CVEP_BITS`.

## Étape 6 — mutation mandatée, et trois de plus (une par test ajouté)

Quatre mutations, chacune posée puis retirée séparément (jamais deux à la fois), sortie collée
telle quelle.

### Mutation mandatée : `phase_a`, `... % self.code_len` → `(... + 1) % self.code_len`

Rouge (4 assertions touchées : les trois positions de phase directement lues, plus le désaccord de
code qui suit un chemin différent — non affecté, resté vert) :

```
  OK   sans aucun marqueur reçu, il n'y a PAS de phase — et surtout pas 0, qui serait une position valide du code
  ÉCHEC à l'instant du marqueur, la phase vaut 0 (1)
  ÉCHEC dix frames plus tard, phase = 10 (11)
  ÉCHEC un cycle entier plus tard, la phase est REVENUE à 0 (modulo la longueur du code)
  OK   juste avant la péremption, la référence sert encore
  OK   juste après, elle est PÉRIMÉE : on cesse de décoder au lieu de dériver en silence
  OK   un instant ANTÉRIEUR au dernier marqueur connu n'a pas de phase valide non plus (None)
  OK   un émetteur qui affiche à un AUTRE rafraîchissement que le modèle est refusé, en nommant les deux fréquences (...)
  OK   ...et le refus n'a laissé AUCUNE référence utilisable derrière lui
  ÉCHEC un écart de 0,4 Hz (sous la tolérance de 1 Hz) est accepté (1)
[cvep] VERDICT : PROBLÈME
EXIT CODE (mutant): 1
```

Retirée, vert, `git diff` de la ligne redevenu vide :

```
  OK   à l'instant du marqueur, la phase vaut 0 (0)
  OK   dix frames plus tard, phase = 10 (10)
  OK   un cycle entier plus tard, la phase est REVENUE à 0 (modulo la longueur du code)
  ...
[cvep] VERDICT : OK
EXIT CODE (revert): 0
```

### Mutation 2 (test ajouté « sans modèle ») : `_modeles_disponibles` toujours non vide

`return (CVEP_MODEL_PATH,) if _charger(...)[0] is not None else ()` → `return (CVEP_MODEL_PATH,)`.

Rouge, UNE seule assertion touchée (isolation propre du test) :
```
  ÉCHEC sans modèle, le mode refuse en disant quoi faire (None)
[cvep] VERDICT : PROBLÈME
EXIT CODE (mutant): 1
```
Retirée → vert, `[cvep] VERDICT : OK`, exit 0.

### Mutation 3 (test ajouté « refus de rafraîchissement ») : seuil `> 1.0` → `> 1000.0`

Rouge, deux assertions (le refus attendu ET la garde qui vérifie qu'aucune référence n'a été
posée) :
```
  ÉCHEC un émetteur qui affiche à un AUTRE rafraîchissement que le modèle est refusé, en nommant les deux fréquences (None)
  ÉCHEC ...et le refus n'a laissé AUCUNE référence utilisable derrière lui
[cvep] VERDICT : PROBLÈME
EXIT CODE (mutant): 1
```
Retirée → vert, `[cvep] VERDICT : OK`, exit 0.

### Mutation 4 (test ajouté « désaccord de code ») : `_desaccord_code` neutralisé (`if False and ...`)

Rouge :
```
  ÉCHEC ...mais la CONSTRUCTION refuse un modèle calibré pour un AUTRE code que celui que la config actuelle construit, en nommant les deux longueurs (None)
[cvep] VERDICT : PROBLÈME
EXIT CODE (mutant): 1
```
Retirée → vert, `[cvep] VERDICT : OK`, exit 0.

## Non-régression

```
python src/core/modes/registry.py   → [registry] VERDICT : OK                          exit 0
                                       (le c-VEP y apparaît TOUJOURS via external.CVEP,
                                       status appli_pygame — inchangé : cvep.SPEC n'est
                                       PAS encore enregistré, c'est la tâche 4)
python src/core/server.py --smoke   → 17 sous-smokes, tous « VERDICT : OK »             exit 0
                                       [smoke-frontiere] 30 fichiers scannés (29 avant
                                       cette tâche + ce nouveau fichier), 0 violation
```

Les trois lancés un par un, jamais en parallèle. Aucun `python.exe` du projet ne tournait avant de
commencer (`Get-CimInstance Win32_Process -Filter "name='python.exe'"` vide), ni entre les
lancements. `git status --short data/` vide avant et après toute la tâche : aucun fichier de
`data/` touché.

## Étape 7 — commit

```
git add src/core/modes/cvep.py src/core/config.py
git commit -m "Give the c-VEP a runtime that knows when it does not know the phase"
```

→ `4315d00`, 2 fichiers changés (425 insertions), conforme à la liste `git add` du brief.

`docs/superpowers/plans/2026-08-20-cvep-moteur.md` apparaît modifié dans `git status` (+21/−1) :
**pas mon fait** — c'est l'amendement de la tâche 7 déjà documenté dans `progress.md` comme fait
« en début de session par un processus antérieur », avant même la tâche 1. Vérifié par
`git diff --stat` (correspond exactement au texte cité dans `progress.md`) ; laissé tel quel, non
ajouté à mon commit, comme l'avait fait l'implémenteur de la tâche 1.

## Fichiers concernés (chemins absolus)

- `C:\Users\Lab_IA\Documents\Projets_Dev\EEG_API_Unicorn\src\core\modes\cvep.py` (créé)
- `C:\Users\Lab_IA\Documents\Projets_Dev\EEG_API_Unicorn\src\core\config.py` (modifié :
  `CVEP_PEREMPTION_CYCLES = 3`, ajoutée après `CVEP_MODEL_PATH`, avec sa provenance en commentaire)
- `C:\Users\Lab_IA\Documents\Projets_Dev\EEG_API_Unicorn\.superpowers\sdd\2026-08-20-cvep-moteur\task-2-report.md`
  (ce rapport)

## Doutes / réserves

- **L'écart flottant sur `phase_a` est le point le plus important de ce rapport.** La formule
  DONNÉE LITTÉRALEMENT par le brief ne satisfait pas son PROPRE test, mesuré et reproduit ci-dessus
  — ce n'est pas une interprétation, `int(1.0499999999999972 * 60.0) == 62`. Je l'ai corrigée
  plutôt que de la recopier telle quelle et laisser le test rouge, avec la même tolérance que
  `registry._EPS_S` (même valeur, même famille de bug déjà rencontrée dans ce dépôt). Si un chiffre
  différent de `1e-9` était voulu ailleurs dans ce chantier, c'est ici qu'il faut le recaler.
- **`stream_in` n'est PAS déclaré sur `SPEC.params`**, contrairement à `errp.py`/`p300.py`. Ce
  fichier ne consomme pas encore `engine.markers_murs()`/`core.markers` (aucun `_run_step` : la
  brief liste seulement `phase_a` comme interface produite, et « décision »/publication est le
  travail de la tâche 4 d'après le plan). Sans `stream_in`, `server._nom_flux_marqueurs` retombera
  sur `MARKER_STREAM_DEFAULT` pour ce mode tant qu'il n'est pas câblé — correct pour l'instant,
  mais la tâche 4 (ou 5) devra l'ajouter en même temps que la boucle de décodage, sur le patron
  exact de `errp.py`/`p300.py`.
- **`_charger`/`_modeles_disponibles` sont volontairement un doublon réduit** de ce que
  `core/cvep_models.py` fera à la tâche 3 (catalogue multi-modèles, champ `decoder`). Documenté en
  triple (docstring du module, des deux fonctions, et du `help=` du `Param`) pour qu'un lecteur ne
  les prenne pas pour la version définitive.
- **Deux tests ajoutés au-delà du strict mandat du brief** (désaccord de `code_len`, troisième état
  muet `age < 0.0`) : les deux protègent une vraie panne silencieuse de la même famille que celles
  déjà nommées par le brief, et j'ai préféré les couvrir plutôt que laisser `build_targets()` — une
  interface que le brief liste comme consommée — sans aucun test dessus. Signalé plutôt que
  masqué : si la tâche 3 ou 4 préfère porter ce contrôle ailleurs (par ex. dans le futur
  `cvep_models.charger`), `_desaccord_code` est isolé et facile à déplacer.
- Aucun doute sur le résultat lui-même : les 20 assertions de `_selftest()` sont vertes, les 4
  mutations rougissent chacune exactement ce qu'elles ciblent et rien d'autre, et les deux suites
  de non-régression (`registry.py`, `server.py --smoke`) sortent identiques à avant cette tâche.
