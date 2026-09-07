# Tâche 3 — `MarkerCalibrationRuntime`, et LE test qui porte le chantier

Projet **EEG_API_Unicorn** : une API BCI pour étudiants. Un casque EEG est acquis et décodé par un
moteur headless (`src/core/server.py`) qui diffuse le résultat sur le réseau (LSL). Lire
`CLAUDE.md` à la racine avant de commencer.

**Ce chantier** rend la console seul point d'entrée : les quatre calibrations (MI, P300, ErrP,
c-VEP) deviennent jouées par le MOTEUR, les fenêtres de `src/stimulus/` se contentant d'afficher le
stimulus et de publier des marqueurs. Ta tâche livre le socle des trois calibrations menées par une
fenêtre. Les tâches 4, 7 et 8 en dériveront le P300, l'ErrP et le c-VEP — **tu ne fais aucun des
trois**.

## À créer

`src/core/modes/marker_calib.py` — la classe `MarkerCalibrationRuntime`.

## À modifier

`src/core/config.py` — trois constantes, aux valeurs EXACTES suivantes :

```python
CALIB_FENETRE_ATTENTE_S = 30.0   # délai pour qu'une fenêtre s'annonce (calib_start)
CALIB_FENETRE_SILENCE_S = 15.0   # silence au-delà duquel la fenêtre est réputée MORTE
CALIB_TMP_PREFIX = "calib_candidat_"   # préfixe du dossier temporaire (posé ici, utilisé T5)
```

Justifie chaque valeur en commentaire : 30 s parce qu'une fenêtre pygame plein écran met plusieurs
secondes à s'initialiser ; 15 s parce que le plus long silence NORMAL des trois protocoles est la
pause de 2,5 s entre deux manches P300 (`PAUSE_ENTRE_MANCHES_S` dans `src/stimulus/p300.py`).

## Lis ces fichiers en premier, dans cet ordre

1. `src/core/modes/calibration.py` — `CalibrationRuntime`, la calibration menée par le MOTEUR.
   **C'est le contrat public que tu dois répliquer À L'IDENTIQUE** : `PHASES`,
   `PHASES_TERMINALES`, `tick(engine, now)`, `cancel()`, `terminee`, `resultat`, `probleme`,
   `phase`, `etape`, `classe`, `essai`, `total()`, `duree_estimee_s()`, `instruction()`,
   `rappel()`, et le hook `_entrainer(enregistre, fs)`.
2. `src/core/modes/mi_calib.py` — la seule sous-classe existante ; le patron d'un `_entrainer`.
3. `src/core/modes/p300.py` — comment un mode consomme les marqueurs et découpe une époque.
4. `src/core/server.py`, autour de `_start_calibration` — comment le moteur héberge une
   calibration (`EngineServer.calibration`, un emplacement distinct des modes) et ce qu'il met
   dans `snapshot()["calibration"]`. **La console affiche cet instantané sans rien savoir du mode**
   (`src/console/calib_page.py`) : si ta forme diffère, la page reste vide.

## Ce que la classe fait

Le moteur est **PASSIF**. Il ne tire aucune consigne et ne décompte aucun essai : c'est la fenêtre
qui mène. La ligne du temps :

| phase | ce qui la déclenche |
|---|---|
| `chauffe` | au démarrage, `warmup_s` (15 s) ; **les marqueurs reçus pendant sont JETÉS** — l'offset DC de l'Unicorn dérive après ouverture, ces époques ne valent rien |
| `essais` | réception de `calib_start` ; mémorise le champ `trials` annoncé, pour l'avancement |
| `entrainement` | réception de `calib_end` |
| `fini` / `annule` | comme `CalibrationRuntime` |

Il n'y a **PAS** de phase `echauffement` : la fenêtre gère son propre briefing.

### Les trois causes d'abandon, chacune avec un `probleme` lisible

1. **La fenêtre ne s'est jamais annoncée** — pas de `calib_start` dans les
   `CALIB_FENETRE_ATTENTE_S`. Message : la fenêtre ne s'est pas lancée, ou publie sous un autre nom.
2. **La fenêtre est morte en cours** — plus aucun marqueur depuis `CALIB_FENETRE_SILENCE_S`, alors
   que `calib_start` annonçait davantage d'essais. **Ce qui est enregistré n'est NI entraîné NI
   sauvegardé** — même règle que `CalibrationRuntime.cancel()`, et pour la même raison : une séance
   tronquée produirait un modèle que rien ne distingue d'un modèle complet dans la liste, et qui
   donnerait des probabilités plausibles et fausses.
3. **L'utilisateur annule** depuis la console (`cancel()`), qui libère les époques ET la référence
   au moteur.

### ⚠️ L'INVARIANT CENTRAL DU CHANTIER

`pre_s` et `post_s` ne sont **pas** redéclarés dans la calibration. Ils sont **LUS** sur la classe
du runtime de décodage, que la sous-classe désigne par un attribut de classe
`runtime_cls_du_mode` :

```python
    @property
    def pre_s(self):
        return float(self.runtime_cls_du_mode.pre_s)

    @property
    def post_s(self):
        return float(self.runtime_cls_du_mode.post_s)
```

Et l'époque est prélevée par **le même appel que le décodage** :

```python
from core.p300_decoder import epoch_from_stream
epoque = epoch_from_stream(engine.recent, engine.recent_ts, ts, engine.acq.fs,
                           pre_s=self.pre_s, post_s=self.post_s)
```

**Pourquoi ça compte.** Aujourd'hui les époques d'entraînement sont découpées par un chemin de code
(l'appli pygame, son horloge) et celles du décodage par un autre (le tampon du moteur, les
marqueurs LSL, `time_correction`). Rien ne vérifie qu'ils s'accordent. Un décalage de quelques
échantillons ne lève **aucune exception** : le modèle est entraîné sur un alignement et appliqué
sur un autre, il décode du bruit avec une confiance élevée, et tous les autres tests restent verts.
C'est mesuré sur `src/core/modes/p300.py` : la mutation déplace le pic de −38 échantillons
(−152 ms) et 46 autres assertions restent vertes.

Lire la géométrie plutôt que la recopier rend la dérive **structurellement impossible** au lieu de
seulement testée.

## Le test, dans `_selftest()` du même fichier

Convention du projet : chaque module de `core` porte son autotest, lancé par
`python src/core/modes/marker_calib.py`, qui **sort en 1** quand il échoue et imprime
`[marker-calib] VERDICT : OK|PROBLÈME`. Utilise le motif `chk(cond, msg)` des modules voisins ; les
messages sont des **phrases françaises qui disent ce qui est vérifié et pourquoi**, pas des
étiquettes.

**LE test** — l'accord des deux épochages. Fabrique un moteur factice qui remplit `recent` /
`recent_ts` avec un signal synthétique 8 voies horodaté, puis :

- fais consommer une douzaine de marqueurs à la calibration ;
- prélève les mêmes instants par `epoch_from_stream` avec les `pre_s`/`post_s` du runtime de
  décodage ;
- exige que les tableaux soient **identiques à l'échantillon près** (`np.abs(a - b).max() == 0`),
  formes comprises ;
- et vérifie que la calibration LIT `pre_s`/`post_s` sur le runtime au lieu de les redéclarer.

Ajoute aussi : les trois causes d'abandon ; le refus d'entraîner une séance tronquée ; le fait
qu'un marqueur reçu **hors calibration** est ignoré sans erreur (c'est une fenêtre lancée en mode
calibration pendant qu'un décodage tourne — le moteur n'a pas à s'arrêter pour ça) ; et la forme du
`snapshot`.

**PROUVE que le test peut rougir.** Décale l'époque de la calibration d'un seul échantillon
(`pre_s=self.pre_s + 1.0 / fs`), relance, constate le rouge, retire, relance. **Colle les deux
sorties dans ton rapport.** Un test qui ne peut pas échouer ne teste rien.

## Contraintes qui te lient

- `src/core/` n'importe **jamais** `research`, `console` ni `stimulus`, et ne contient ni pygame ni
  Qt. Vérifié par `python src/core/server.py --smoke` — lance-le, il scanne l'arbre.
- Un runtime **ne lit jamais l'horloge lui-même** : `tick` reçoit `now`. C'est ce qui permet de
  jouer une séance de sept minutes en quelques millisecondes dans un test.
- **Code et commentaires en français.** Messages de commit en anglais.
- Tout testable **sans casque**.
- **Aucun test n'écrit dans le vrai `data/`** — ce sont des enregistrements EEG d'une personne
  identifiable sur un dépôt PUBLIC. `git status` ne prouve rien (`data/` est gitignoré) : si tu
  dois écrire, utilise un dossier temporaire et vérifie par `core.config.empreinte_dossier`.
- ⚠️ **Ne laisse tourner aucun autre programme du projet** pendant tes tests : les noms de flux LSL
  sont un contrat public, un moteur oublié répond à la place de celui que tu testes.

## Ce que tu ne fais PAS

- Aucune sous-classe concrète (P300, ErrP, c-VEP) — tâches 4, 7, 8.
- Aucune modification de `src/console/`, `src/stimulus/` ou `src/research/`.
- Aucun changement au protocole de marqueurs publié (`docs/markers.md`) : tu **consommes**
  `calib_start` / `cue` / `calib_end`, tu ne les documentes pas. Leur forme :
  `{"mode": "<id>", "event": "calib_start", "trials": 24}`,
  `{"mode": "<id>", "event": "cue", "target": 3}`, `{"mode": "<id>", "event": "calib_end"}`.
  ⚠️ L'ErrP n'utilisera pas `cue` (son étiquette voyagera sur son propre événement `feedback`) :
  ta classe ne doit donc **pas** supposer que l'étiquette arrive par `cue`. Laisse la sous-classe
  décider quel marqueur porte l'étiquette et lequel délimite l'époque.

## Quand tu as fini

Lance et colle la sortie de :

```bash
python src/core/modes/marker_calib.py
python src/core/modes/calibration.py
python src/core/server.py --smoke
```

Puis commite (message en **anglais**), et écris ton rapport dans
`.superpowers/sdd/2026-09-07-console-point-entree-unique/task-3-report.md` : ce que tu as livré, la
preuve de mutation (les deux sorties), et **tout ce qui t'a surpris ou que tu as dû arbitrer**.
Ton message final ne rend que : statut (DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT), le
hash du commit, une ligne de résumé des tests, et tes réserves.
