# Tâche 5 — la garde de sauvegarde : `data/` écrit à un seul endroit

Projet **EEG_API_Unicorn** : API BCI pour étudiants, moteur headless + LSL. Lire `CLAUDE.md`.

Cette tâche ferme un **défaut réel**, pas une commodité d'interface : aujourd'hui une calibration
**sauvegarde d'abord et annonce sa précision ensuite**. Comme le moteur propose par défaut le modèle
chargeable le plus récent, **une calibration ratée devient le défaut, en silence**. Personne ne peut
la refuser : quand le chiffre s'affiche, le fichier est déjà sur le disque et déjà proposé.

Après toi : le candidat vit dans un dossier **temporaire**, la console affiche la précision, et
`data/` n'est écrit que sur un geste explicite.

## À livrer

1. **`src/core/server.py`** — un dossier temporaire par moteur, les commandes `save_calibration` et
   `discard_calibration`, le nettoyage inconditionnel, et le **refus du vol de marqueurs** (voir
   plus bas, c'est le point le plus important de la tâche).
2. **`src/core/modes/mi_calib.py`** et **`src/core/modes/p300_calib.py`** — ils écrivent dans le
   dossier qu'on leur donne et ne décident plus de rien.

## Lis en premier

1. `src/core/modes/calibration.py` puis `src/core/modes/mi_calib.py` — comment `_entrainer` écrit
   aujourd'hui (`self.dossier`, `_chemins_libres`, deux fichiers : le modèle **et** son `.npz`
   d'époques).
2. `src/core/modes/marker_calib.py` — le socle des calibrations menées par une fenêtre, et sa
   docstring, qui signale le problème de vol de marqueurs.
3. `src/core/server.py`, autour de `_start_calibration`, `submit` et `snapshot` — le protocole
   d'acceptation/refus des commandes (`{"accepted": bool, "reason": str}`) et la liste des
   commandes connues.
4. `src/core/{mi,p300,errp,cvep}_models.py` — les MOTIFS de découverte des modèles. Tu dois
   t'assurer qu'aucun ne peut découvrir un candidat.

## 🔴 Le point le plus important : le vol de marqueurs

Signalé par le sous-agent de la tâche 3, hors de son périmètre. **`engine.markers_murs(mode_id)`
n'a qu'UN curseur par `mode_id`.** Si le mode P300 tourne pendant que sa propre calibration tourne,
les deux consomment la même file : chacun reçoit une PARTIE des marqueurs, l'autre partie
disparaît. Aucune exception, aucun message. La calibration s'entraîne sur des époques trouées et le
décodage rate des flashs — les deux produisent des chiffres plausibles.

**Le refus appartient à `submit`**, qui est le seul endroit qui voit les deux :

- `start_calibration` sur un mode **actuellement démarré** → refusé, en disant d'arrêter le mode
  d'abord, et en nommant le mode.
- `start_mode` sur un mode dont **la calibration est en cours** → refusé de la même façon.

Ces refus valent pour les modes à marqueurs. Écris un test pour **chacun des deux sens** : c'est le
genre de garde qu'on écrit dans un seul sens et qui laisse l'autre porte grande ouverte.

## Le dossier temporaire

`EngineServer` crée à sa construction un dossier via `tempfile.mkdtemp(prefix=CALIB_TMP_PREFIX)`
(la constante existe déjà dans `core/config.py`, posée par la tâche 3), et le passe aux
calibrations en guise de `dossier`.

⚠️ **Le nettoyage doit être INCONDITIONNEL** — dans le `finally` de `run()` **et** dans `close()`.
Si la console se ferme entre l'entraînement et la décision, aucun candidat ne doit survivre.

⚠️ **Et le nom d'un candidat ne doit correspondre à AUCUN motif de découverte** de
`p300_models` / `errp_models` / `cvep_models` / `mi_models`. Sans ça, un candidat orphelin serait
proposé au démarrage suivant comme le modèle le plus récent : le défaut qu'on ferme, rouvert par sa
propre correction. **Teste-le en appelant les quatre `modeles_disponibles(dossier=<le temporaire>)`
et en exigeant une liste vide.**

## Les deux commandes

Mêmes conventions que `start_calibration` (`{"accepted": bool, "reason": str}`), et refus propre
avec un motif quand il n'y a rien à enregistrer.

- **`save_calibration`** → DÉPLACE chaque fichier nommé dans le résultat (`modele`, et
  `enregistrement` s'il existe) vers `DATA_DIR`, sous un nom horodaté **libre**, sans jamais
  écraser. Puis le candidat cesse d'exister, tout en laissant le résultat lisible à l'écran.
- **`discard_calibration`** → supprime le candidat et efface l'écran de verdict.

⚠️ **Déplacer, pas copier.** Un candidat copié laisserait son original dans le temporaire, que le
nettoyage supprimera — bénin — mais surtout ferait exister le même modèle deux fois pendant un
instant, sous deux noms. Teste que l'original n'existe plus après `save_calibration`.

`snapshot()["calibration"]["candidat"]` porte le dict rendu par `_entrainer`, ou `None`.

## Les tests

Dans `_smoke` de `src/core/server.py`, avec le motif `chk(cond, msg)` du fichier et des phrases
françaises qui disent ce qui est vérifié et pourquoi :

1. Une calibration **terminée** n'a **rien** écrit dans `data/` — vérifié par
   `core.config.empreinte_dossier(DATA_DIR)` avant/après, jamais par `git status` (`data/` est
   gitignoré, il ne prouve rien).
2. Le candidat vit dans le dossier temporaire, et **les quatre catalogues n'y découvrent rien**.
3. `save_calibration` déplace (l'original n'existe plus), `data/` change, rien n'est écrasé.
4. `discard_calibration` supprime et efface le verdict.
5. Fermer le moteur **sans trancher** ne laisse aucun candidat orphelin.
6. Les deux commandes refusent proprement, avec un motif, quand il n'y a rien à enregistrer.
7. Les **deux sens** du refus de vol de marqueurs.

⚠️ Le test 3 est le seul qui a le droit d'écrire dans `data/`, et il ne l'a pas : fais-le écrire
dans un `DATA_DIR` détourné (dossier temporaire) et vérifie l'empreinte du VRAI `data/` avant/après
l'ensemble du smoke. Un test qui écrit un modèle dans le vrai `data/` le fait proposer par défaut à
la prochaine séance casque.

## Contraintes qui te lient

- `src/core/` n'importe **jamais** `research`, `console` ni `stimulus`, et ne contient ni pygame ni
  Qt. Vérifié par `python src/core/server.py --smoke`.
- **La console est un CLIENT** : elle enverra ces commandes, elle n'écrira jamais sur le disque.
  Tu ne touches pas à `src/console/` — c'est la tâche 6.
- **Code et commentaires en français**, messages de commit en anglais.
- Tout testable **sans casque**. Autotest sortant en **1** si échec.
- **Aucun test n'écrit dans le vrai `data/`** — enregistrements EEG d'une personne identifiable,
  dépôt PUBLIC.
- ⚠️ Aucun autre programme du projet ne tourne pendant tes tests.

## Quand tu as fini

```bash
python src/core/server.py --smoke
python src/core/modes/mi_calib.py
python src/core/modes/p300_calib.py
python src/core/modes/marker_calib.py
python src/core/modes/calibration.py
python src/core/mi_models.py
python src/core/p300_models.py
python src/console/app.py --smoke
```

Commite (anglais), rapport dans
`.superpowers/sdd/2026-09-07-console-point-entree-unique/task-5-report.md`, et message final réduit
à : statut, hash, une ligne de tests, réserves.
