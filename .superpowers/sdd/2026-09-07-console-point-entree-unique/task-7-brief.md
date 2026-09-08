# Tâche 7 — l'ErrP de bout en bout

Projet **EEG_API_Unicorn** : API BCI pour étudiants, moteur headless + LSL. Lire `CLAUDE.md`.

Le P300 (tâche 4) a ouvert la voie : **suis-le pas à pas**, c'est le même geste sur un autre
paradigme. Lis `.superpowers/sdd/2026-09-07-console-point-entree-unique/task-4-report.md` avant de
commencer — il décrit deux pièges que tu vas rencontrer tels quels.

## À livrer

1. **`src/core/modes/errp_calib.py`** — `ErrPCalibration(MarkerCalibrationRuntime)` avec
   `runtime_cls_du_mode = ErrPRuntime` et `_entrainer(enregistre, fs)`.
2. **`src/stimulus/errp.py`** — un mode `--calibrer`.
3. **`src/core/modes/errp.py`** — son `Calib` gagne `runtime_cls=ErrPCalibration` et un `epoch_s`
   non nul.
4. **`src/research/errp_calibrate.py`** — réduit à sa moitié pygame / analyse hors ligne.

## ⚠️ Ce qui distingue l'ErrP des deux autres, et c'est central

**L'ErrP n'utilise PAS `cue`.** Son étiquette voyage sur son propre événement `feedback`, qui gagne
un champ `error: true|false` **pendant la calibration seulement** :

```json
{"mode": "errp", "event": "calib_start", "trials": 200}
{"mode": "errp", "event": "feedback", "error": true}
{"mode": "errp", "event": "calib_end"}
```

**En décodage, `feedback` reste nu.** Le moteur ne doit jamais connaître la réponse pendant qu'il
décode — c'est une BCI *passive*, tout son objet est de DEVINER depuis l'EEG. Publier la
vérité-terrain sur le réseau en décodage reviendrait à lui donner la réponse.

**Écris le test dans les deux sens** : en calibration chaque `feedback` porte son étiquette ; hors
calibration **aucun** ne la porte. C'est le genre de garde qu'on écrit dans un sens seulement.

⚠️ Et l'étiquette publiée doit être celle du pas **RÉELLEMENT AFFICHÉ**, pas celle que le tirage
avait décidée : `core/errp_track.py:decide_pas` rend `erreur` d'après l'EFFET du pas, rebond de bord
compris — un tirage « erreur » au bord rapproche le point de sa cible et n'est donc PAS une erreur
vécue. C'est la même faute que d'horodater avant le flip, sur un autre axe.

## Ce que la tâche 1 t'a déjà donné

`src/core/errp_track.py` existe : `nouvelle_cible`, `decide_pas`, et les trois durées
`PAUSE_INTER_PAS_S` / `PAUSE_FIN_COURSE_S` / `PAUSE_NOUVELLE_COURSE_S`. La règle de la piste était
écrite **deux fois** (calibration et émetteur) avec un test de 500 pas pour garder les copies
d'accord ; elle ne l'est plus. **N'en réintroduis pas une troisième écriture.**

⚠️ Ces trois durées sont celles sous lesquelles les époques du modèle du 2026-07-24 (AUC 0,776) ont
été enregistrées. Les changer sans réentraîner décale le feedback dans l'époque, en silence.

## Deux pièges hérités de la tâche 4, à reprendre tels quels

- **Le cycle d'import.** `errp.py` ↔ `errp_calib.py` cassera `python src/core/modes/errp.py` —
  c'est mesuré côté P300. Le patron est un **import tardif dans une propriété** ; va le lire dans
  `p300.py`/`p300_calib.py` et reprends-le.
- **La géométrie SAUVEGARDÉE.** Côté P300, `P300Model` était construit avec ses `pre_s`/`post_s`
  par défaut alors que les époques étaient découpées avec ceux du runtime. Mêmes nombres, donc tous
  les tests verts — et un refus certain du modèle fraîchement calibré au premier déplacement de
  constante. **`ErrPModel` doit recevoir la géométrie avec laquelle les époques ont RÉELLEMENT été
  découpées**, c'est-à-dire `self.pre_s`/`self.post_s` du socle. Ferme l'aller-retour par un test :
  le modèle produit doit être accepté par un vrai `ErrPRuntime`.

## Le résultat de `_entrainer`

Au minimum : `{"modele", "nom", "n_essais", "auc", "perm_p", "tpr", "tnr", "verdict", "honnetete"}`.

⚠️ **La tâche 6 a découvert que le verdict ET la phrase d'honnêteté étaient écrits aux mesures du
MI** : la page affichait « 576 essais, 0 fenêtres d'entraînement — classes : » sous un résultat
P300. Ils sont maintenant indexés **par clé de résultat, jamais par identifiant de mode**. Respecte
ce dispositif : ajoute tes clés, ne branche pas sur `mode_id`.

**La phrase d'honnêteté de l'ErrP doit dire trois choses** — elles sont dans `docs/recette.md` §2.8
et dans le README, vérifie-les plutôt que de me croire :
- au réglage par défaut le détecteur **attrape une erreur sur deux** et annule une bonne commande
  sur sept (TPR 0,50 / TNR 0,855) ;
- **ces deux taux sont eux-mêmes OPTIMISTES** : l'AUC (0,776, p = 0,0099 sur 100 permutations, 200
  essais, une personne) est honnête car hors-pli, mais le SEUIL a été choisi en regardant ces mêmes
  scores — le TNR dépasse donc sa cible *par construction* ;
- **sur dix erreurs délibérées, en attraper cinq est le résultat ATTENDU.**

## Les tests

Autotest par module, `python src/core/modes/errp_calib.py`, sortie **1** si échec, `chk(cond, msg)`
avec des phrases françaises qui disent ce qui est vérifié et pourquoi.

Côté `src/stimulus/errp.py --smoke`, en plus de l'existant : `calib_start` puis `calib_end` ; chaque
`feedback` de calibration porte son `error` ; ces étiquettes sont celles des pas RÉELLEMENT joués ;
**hors calibration, aucun `feedback` ne porte d'étiquette** ; le taux d'erreurs reste dans sa plage.

Côté `errp_calib.py` : le test de permutation est calculé et rendu ; la phrase d'honnêteté dit que
les taux sont OPTIMISTES ; le modèle est écrit dans le dossier qu'on lui donne et jamais dans
`data/` ; l'aller-retour de géométrie est fermé.

## Contraintes qui te lient

- `src/core/` n'importe **jamais** `research`, `console` ni `stimulus`, ni pygame ni Qt.
  `src/stimulus/` n'importe **jamais** `research` ni `console`. Vérifié par
  `python src/core/server.py --smoke`.
- Une fenêtre de `src/stimulus/` **n'ouvre JAMAIS le casque**.
- **Ne touche pas au décodage de l'ErrP**, ni à ses seuils, ni à ses bornes d'époque. Tu déplaces un
  entraînement, tu n'en changes pas la règle. Si tu constates un désaccord, **dis-le, ne corrige
  pas en silence**.
- **Code et commentaires en français**, commits en anglais.
- **Aucun test n'écrit dans le vrai `data/`** — enregistrements EEG d'une personne identifiable,
  dépôt PUBLIC. `git status` ne prouve rien : `core.config.empreinte_dossier`.
- ⚠️ Aucun autre programme du projet ne tourne pendant tes tests.

## Quand tu as fini

```bash
python src/core/modes/errp_calib.py
python src/core/modes/errp.py
python src/core/errp_models.py
python src/core/errp_track.py
python src/core/modes/marker_calib.py
python src/stimulus/errp.py --smoke
python src/core/server.py --smoke
python src/console/app.py --smoke
```

Commite (anglais), rapport dans `task-7-report.md`, message final réduit à : statut, hash, une
ligne de tests, réserves.
