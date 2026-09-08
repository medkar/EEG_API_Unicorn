# Tâche 10 — les retraits, dans l'ordre qui ne casse pas l'archive

Projet **EEG_API_Unicorn** : API BCI pour étudiants. Lire `CLAUDE.md`.

Les tâches 1 à 9 ont mis dans le moteur et dans la console tout ce que l'appli pygame faisait. Ta
tâche **retire ce qui fait désormais doublon**, sans rien perdre de ce qui sert encore.

⚠️ **Retirer ne veut pas dire supprimer.** La convention du dépôt est l'archivage : `archive/`
contient déjà quatre écrans retirés, chacun avec son `--smoke`, et `archive/README.md` explique
pour chacun *ce qu'il était* et *pourquoi il est gardé*. Ce sont les références contre lesquelles
l'implémentation actuelle a été vérifiée — `archive/cvep_pilot.py` sert nommément à la recette 2.9,
qui compare le décodage réseau au décodage local sur la même fixation.

## L'ordre, et il n'est pas négociable

**`archive/cvep_pilot.py:34` et `archive/cvep_rcca_pilot.py:37` importent `Live`, `_live_loop`,
`_running`, `_vote` depuis `src/research/app.py`**, et `archive/README.md` promet que ces fichiers
tournent encore. Donc :

1. **D'abord** la machinerie pygame partagée déménage dans `src/research/ui.py` (qui porte déjà
   `App` et `Abort`), et les imports de l'archive suivent.
2. **Les quatre `--smoke` de `archive/` doivent être verts AVANT de toucher à autre chose.**
3. **Ensuite seulement** viennent les retraits ci-dessous.
4. **En dernier**, `src/research/app.py` — une fois vidé — est supprimé.

## Ce qui part dans `archive/`

**Les trois écrans de PILOTAGE**, qui font doublon avec le moteur :

| aujourd'hui | devient |
|---|---|
| `mode_ssvep` (`research/app.py`) | `archive/ssvep_pilot.py` |
| la sélection P300 (`mode_p300`) | `archive/p300_pilot.py` |
| le démonstrateur ErrP (`mode_errp`) | `archive/errp_demo.py` |

**Et les trois pages de CALIBRATION pygame** (c-VEP, P300, ErrP). Celles-là ne sont pas seulement
un doublon : **elles écrivent directement dans `data/` et contournent la garde livrée par la tâche
5**, celle qui fait qu'une calibration s'affiche avant d'être gardée. Tant qu'elles existent, un
étudiant peut produire un modèle qui échappe au « Refaire / Enregistrer ». Archive-les — elles
restent la référence contre laquelle les calibrations du moteur ont été écrites.

Chaque fichier archivé devient **autonome**, garde son `--smoke`, et — comme `cvep_pilot.py` —
expose un `--model` explicite là où il en charge un.

## Ce qui reste dans `research/`

`ui.py` (avec la machinerie qui vient d'arriver), les analyses (`*_analyze.py`, `itr.py`,
`mi_compare.py`), les protocoles chiffrés (`ssvep_guided.py`, `alpha_check.py`), et ce qui subsiste
des `*_calibrate.py` après les tâches 4, 7 et 8 — leur moitié d'**analyse hors ligne** d'un
enregistrement existant. ⚠️ **Si l'un d'eux garde une fonction qui ÉCRIT un modèle dans `data/`,
elle part avec l'écran archivé** : c'est le point de la manœuvre.

## `archive/README.md`

Trois — ou six — lignes pour les nouveaux arrivants, sur le modèle des quatre existantes : ce que
c'était, par quoi c'est remplacé, pourquoi on le garde.

⚠️ **Et corrige la ligne de `cvep_pilot.py`**, qui affirme aujourd'hui *« Calibration is
unaffected: it still lives at `src/research/app.py`, page "c-VEP" »*. C'est faux depuis la tâche 8.

## Le critère de réussite

```bash
# 1. Plus aucun code n'importe l'appli supprimée
grep -rn "research.app\|research/app" src/ archive/ examples/    # aucune occurrence de CODE

# 2. Les SEPT smokes de l'archive
python archive/mi_calibrate.py --smoke
python archive/mi_pilot.py --smoke
python archive/cvep_pilot.py --smoke
python archive/cvep_rcca_pilot.py --smoke
python archive/ssvep_pilot.py --smoke
python archive/p300_pilot.py --smoke
python archive/errp_demo.py --smoke
# ... plus les trois calibrations archivées, avec le nom que tu leur donnes

# 3. Le reste du dépôt
python src/core/server.py --smoke
python src/console/app.py --smoke
python src/stimulus/p300.py --smoke
python src/stimulus/errp.py --smoke
python src/stimulus/cvep.py --smoke
python src/stimulus/registry.py
```

## Contraintes qui te lient

- `src/core/` n'importe **jamais** `research`, `console` ni `stimulus`. `src/stimulus/` n'importe
  **jamais** `research` ni `console`. Vérifié par `python src/core/server.py --smoke`.
- **Code et commentaires en français** ; `archive/README.md` est en **anglais** (c'est du GitHub) ;
  messages de commit en anglais.
- **Aucun test n'écrit dans le vrai `data/`** — enregistrements EEG d'une personne identifiable,
  dépôt PUBLIC. `git status` ne prouve rien (`data/` est gitignoré) : vérifie l'empreinte par
  `core.config.empreinte_dossier` avant et après ta batterie, et colle les deux valeurs.
  ⚠️ **Ce risque est maximal dans TA tâche** : tu manipules des écrans de calibration dont le
  métier est précisément d'écrire des modèles.
- ⚠️ Aucun autre programme du projet ne tourne pendant tes tests.
- **Ne modifie ni `src/core/`, ni `src/console/`, ni `src/stimulus/`.** Si tu constates qu'il le
  faudrait, dis-le dans ton rapport plutôt que de le faire.

## Quand tu as fini

Commite (anglais) — **en plusieurs commits, dans l'ordre des étapes ci-dessus**, pour qu'une
interruption ne laisse pas l'archive cassée. Rapport dans `task-10-report.md`. Message final réduit
à : statut, hash, une ligne de tests, réserves.
