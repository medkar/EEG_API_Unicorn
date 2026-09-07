# Tâche 4 — le P300 de bout en bout

Projet **EEG_API_Unicorn** : API BCI pour étudiants, moteur headless + LSL. Lire `CLAUDE.md`.

**Le chantier** rend la console seul point d'entrée : les calibrations deviennent jouées par le
MOTEUR, les fenêtres de `src/stimulus/` se contentant d'afficher et de publier des marqueurs. La
tâche 3 a livré le socle — `src/core/modes/marker_calib.py`, `MarkerCalibrationRuntime`. **Tu en
fais la première sous-classe concrète.** Le P300 passe en premier exprès : c'est le mode à
marqueurs le mieux connu, validé au casque par l'ancien chemin, et le seul qui porte déjà un test
d'alignement.

## À livrer

1. **`src/core/modes/p300_calib.py`** — `P300Calibration(MarkerCalibrationRuntime)` avec
   `runtime_cls_du_mode = P300Runtime`, et `_entrainer(enregistre, fs)`.
2. **`src/stimulus/p300.py`** — un mode `--calibrer`.
3. **`src/core/modes/p300.py`** — son `Calib` gagne `runtime_cls=P300Calibration` et un `epoch_s`
   non nul.
4. **`src/research/p300_calibrate.py`** — réduit : sa moitié d'entraînement monte dans `core`, il
   ne lui reste que l'analyse hors ligne d'un enregistrement existant.

## Lis en premier

1. `src/core/modes/marker_calib.py` — **surtout sa docstring de module et celle de la classe**.
   Elles disent l'invariant central et ce qu'une sous-classe doit fournir.
2. `src/core/modes/mi_calib.py` — le patron d'un `_entrainer` : ce qu'il rend, comment il nomme ses
   fichiers, comment il refuse une séance trop pauvre.
3. `src/research/p300_calibrate.py` — ce qui monte (`_loro_selection`, `_archive`, la fin de
   `calibrate`) et ce qui reste (tout ce qui touche `app`/pygame).
4. `src/stimulus/p300.py` — l'émetteur actuel. **Son `--smoke` est sérieux** : il vérifie la
   séquence de flashs et l'horodatage au flip. Ne le casse pas, étends-le.

## Le protocole de marqueurs, en calibration

`--calibrer` ajoute au déroulé existant, **sans rien changer aux `flash` / `round_end`** :

```json
{"mode": "p300", "event": "calib_start", "trials": 24}
{"mode": "p300", "event": "cue", "target": 3}
{"mode": "p300", "event": "calib_end"}
```

- `calib_start` ouvre la séance et annonce le nombre de manches attendues.
- `cue` porte la **vérité-terrain** : la cible que l'écran vient de désigner au sujet, publiée
  **avant** les flashs de sa manche. C'est la seule information que le décodage ne donne jamais au
  moteur.
- `calib_end` clôt : le moteur entraîne, la fenêtre se ferme.

⚠️ **L'horodatage se prend APRÈS `pygame.display.flip()`**, pour `cue` comme pour `flash`. Un `cue`
horodaté avant le flip annonce la cible une frame trop tôt, et la première époque de la manche est
étiquetée sur la manche précédente. Rien ne lève d'exception.

⚠️ **La fenêtre doit occuper les ~15 s de chauffe du moteur avant son premier essai** — pendant ce
temps le moteur JETTE tout ce qu'il reçoit (dérive DC de l'amplificateur). Le socle de la tâche 3
compte ces marqueurs jetés et le dit. Regarde comment `src/stimulus/errp.py` attend le moteur
(`attente_consommateur_s`, `ATTENTE_MOTEUR_S`) : le même geste s'applique, et une séance dont les
premiers essais sont silencieusement jetés est une séance plus courte que ce que l'écran annonce.

## Trois choses que la tâche 3 te lègue

- **Le tampon vient de `marker_epoch_s`**, pas de `Calib.epoch_s`. Ce dernier doit juste être `> 0`
  (`registry.check()` l'exige) ; ne t'en sers pas pour dimensionner.
- **`duree_protocole_s`** reste à 0 tant que tu ne la renseignes pas — la page de la console
  afficherait alors une durée fausse. Renseigne-la.
- 🔴 **Un mode et SA calibration se voleraient les marqueurs** (`markers_murs` n'a qu'un curseur par
  `mode_id`). Le socle le dit bruyamment à la construction. **Le refus appartient à la tâche 5, pas
  à toi** — ne le traite pas, mais n'écris rien qui le rende plus difficile à traiter.

## Où le modèle est écrit

Suis `mi_calib.py` : `__init__` accepte un `dossier` (défaut `DATA_DIR`) et `_entrainer` y écrit
sous un nom **horodaté**, jamais fixe, jamais en écrasant. **La tâche 5** fera passer un dossier
TEMPORAIRE pour que la console puisse dire « Refaire » avant que le modèle n'existe : écris donc
`_entrainer` de sorte que le chemin vienne de `self.dossier` et de nulle part ailleurs, et rends
ce chemin dans ton résultat.

Ce que `_entrainer` doit rendre, au minimum :
`{"modele": <chemin>, "nom": <basename>, "n_essais": int, "auc": float, "verdict": str,
"honnetete": str}`.

⚠️ **`honnetete` est une phrase propre au P300**, pas celle du MI. Celle du MI parle de 40 % à
trois classes et de validation croisée par essai ; la recopier ici serait faux. La tienne doit
dire ce que vaut l'AUC mesurée (référence du projet : **0,71 sur 576 époques**, une personne) et
qu'une ou deux erreurs sur six sélections sont **attendues**, pas un défaut.

⚠️ **L'accuracy annoncée est celle de la SÉLECTION**, pas celle des époques : c'est le chiffre qui
veut dire quelque chose pour l'utilisateur (« la cible désignée est-elle la bonne ? »), et
`research/p300_calibrate.py::_loro_selection` le calcule déjà. Ne le réinvente pas.

## Les tests

Convention : autotest par module, `python src/core/modes/p300_calib.py`, sortie **1** si échec,
`chk(cond, msg)` avec des phrases françaises qui disent ce qui est vérifié et pourquoi.

Côté `src/core/modes/p300_calib.py` : l'AUC est une probabilité ; le résultat porte SA phrase
d'honnêteté ; le modèle est écrit dans le dossier qu'on lui donne et **jamais** dans `data/` pendant
un test ; une séance trop pauvre est refusée avec un message qui dit quoi faire.

Côté `src/stimulus/p300.py --smoke`, en plus de l'existant : la séance s'ouvre par `calib_start` et
se ferme par `calib_end` ; un `cue` par manche ; **la cible annoncée par `cue` est celle que
l'écran a réellement DÉSIGNÉE** (pas celle que le tirage avait décidée — c'est la même faute que
d'horodater avant le flip, sur un autre axe) ; chaque `cue` précède les flashs de sa manche.

## Contraintes qui te lient

- `src/core/` n'importe **jamais** `research`, `console` ni `stimulus`, et ne contient ni pygame ni
  Qt. `src/stimulus/` n'importe **jamais** `research` ni `console`. Vérifié par
  `python src/core/server.py --smoke` — lance-le.
- Une fenêtre de `src/stimulus/` **n'ouvre JAMAIS le casque**.
- **Code et commentaires en français**, messages de commit en anglais.
- Tout testable **sans casque**.
- **Aucun test n'écrit dans le vrai `data/`** — enregistrements EEG d'une personne identifiable,
  dépôt PUBLIC. `git status` ne prouve rien (`data/` est gitignoré) : vérifie par
  `core.config.empreinte_dossier`.
- ⚠️ Aucun autre programme du projet ne tourne pendant tes tests.

## Quand tu as fini

```bash
python src/core/modes/p300_calib.py
python src/core/modes/p300.py
python src/core/modes/marker_calib.py
python src/stimulus/p300.py --smoke
python src/core/server.py --smoke
python src/console/app.py --smoke
```

Commite (anglais), écris ton rapport dans
`.superpowers/sdd/2026-09-07-console-point-entree-unique/task-4-report.md`, et ne rends dans ton
message final que : statut, hash, une ligne de tests, et tes réserves.
