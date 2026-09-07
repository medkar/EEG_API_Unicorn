# Tâche 6 — la console : lancer, contrôler le contact, trancher

Projet **EEG_API_Unicorn** : API BCI pour étudiants. Lire `CLAUDE.md`.

C'est la tâche qui rend le chantier **visible**. Les tâches 3 à 5 ont mis dans le moteur tout ce
qu'il fallait ; aujourd'hui rien de tout ça n'est atteignable depuis l'interface. À la fin de la
tienne, une personne qui n'ouvre jamais un terminal peut calibrer le P300, lire sa précision, et
décider de garder le modèle ou de recommencer.

⚠️ **Aucune calibration n'atteint plus `data/` tant que tu n'as pas câblé « Enregistrer »** — la
tâche 5 a déplacé l'écriture derrière un geste explicite, et ce geste n'existe pas encore. Ne
branche pas de casque avant la fin de ta tâche.

## À livrer

1. **`src/console/fenetres.py`** *(créé)* — `LanceurFenetre` : un `QProcess`, son état, son arrêt.
2. **`src/console/contact_page.py`** *(créé)* — le contrôle de liaison, monté depuis
   `src/research/ui.py:signal_check`.
3. **`src/console/calib_page.py`** *(modifié)* — l'écran « Après » gagne **Refaire** et
   **Enregistrer**.
4. **`src/console/mode_page.py`** *(modifié)* — les boutons **« Calibrer »** et **« Lancer le
   stimulus »**.
5. **`src/console/app.py`** *(modifié)* — le câblage, et `EngineServer.close()` dans le
   `closeEvent`.

## Lis en premier

1. `src/console/calib_page.py` — **elle est déjà générique** : trois écrans (Avant / Pendant /
   Après), tout vient de `snapshot()["calibration"]`, elle ne connaît aucun mode. Ne la
   spécialise pas ; ajoute-lui un geste.
2. `src/console/mode_page.py` et `src/console/params_form.py` — comment une page de mode se
   construit à partir du contrat.
3. `src/core/server.py` — les commandes `start_calibration`, `cancel_calibration`,
   **`save_calibration`**, **`discard_calibration`**, leur protocole de refus
   (`{"accepted": bool, "reason": str}`), et `snapshot()["calibration"]["candidat"]`.
4. `src/stimulus/registry.py` — `commande(stimulus_id, calibrer=False)`. **C'est la seule source
   de la ligne de commande** ; ne l'écris nulle part ailleurs.
5. `src/research/ui.py`, méthode `signal_check` — ce que fait le contrôle de liaison aujourd'hui.
6. Les rapports `task-3-report.md`, `task-4-report.md`, `task-5-report.md` du même dossier.

## a. Le lanceur de fenêtre

Un `QProcess` par fenêtre. La commande vient de `stimulus.registry.commande(...)`, **jamais** d'une
chaîne écrite dans la console. Deux boutons, un seul mécanisme :

- **« Calibrer »** sur les pages P300, ErrP, c-VEP → la fenêtre en mode calibration.
- **« Lancer le stimulus »** sur les mêmes pages, en mode décodage.

⚠️ **Refuse d'en lancer deux.** Deux fenêtres publieraient les mêmes marqueurs sous le même nom, et
le moteur mélangerait les deux séances sans rien signaler.

⚠️ **Une fenêtre qui meurt anormalement doit le DIRE à l'écran.** Le silence est précisément le
défaut que ce chantier répare : la recette du projet (test 1.13) a relevé *cinq clics d'affilée* sur
un bouton qui refusait correctement — mais dans le terminal, pas dans la fenêtre.

## b. L'ordre de lancement — 🔴 le piège de cette tâche

La fenêtre attend ~15 s **à partir de son propre lancement** ; le moteur compte sa chauffe **à
partir de `start_calibration`**. Il n'existe aucune poignée de main entre les deux processus, et
c'est délibéré (les tâches 4 et 5 ont refusé d'en inventer une).

**Donc : la console envoie `start_calibration` D'ABORD, puis lance la fenêtre.** L'initialisation
de pygame (~3 s) plus l'attente propre de la fenêtre couvrent alors la chauffe du moteur. Dans
l'ordre inverse, les premières manches tombent dans la chauffe : elles sont jetées, comptées et
dites — mais la séance est plus courte que ce que l'écran annonce, et personne ne le remarque.

**Écris un test qui fixe cet ordre**, sinon il se perdra à la première réorganisation.

⚠️ Et **la console doit arrêter le mode avant de soumettre `start_calibration`** : la tâche 5
refuse qu'un mode et sa propre calibration lisent la même file de marqueurs, et son refus porte une
phrase prête à afficher. Traite le refus, ne le contourne pas.

## c. Le contrôle de liaison

Monté depuis `src/research/ui.py:signal_check`, parce que **les fenêtres de `src/stimulus/` ne
peuvent pas le reprendre : elles n'ouvrent pas le casque**. La console, elle, l'a.

Il montre le σ par voie, **surligne les `key_channels` du mode visé** (le contrat les déclare, tu
ne recopies aucune liste), et **refuse de lancer** tant qu'une voie est plate ou saturée.

⚠️ **Le verdict vient du moteur** — `core/lsl_io.py` produit déjà les verdicts de qualité. La
console n'en calcule aucun : c'est un client.

## d. L'écran de verdict

L'écran « Après » de `calib_page.py` affiche déjà le résultat. Il gagne **Refaire** et
**Enregistrer** :

- **Enregistrer** → commande `save_calibration`. Le modèle horodaté entre dans `data/` et apparaît
  en tête de la liste déroulante du mode, **sans rien relancer**.
- **Refaire** → commande `discard_calibration`, retour au briefing.

⚠️ **La console n'écrit JAMAIS sur le disque.** Elle envoie des commandes. Teste-le : compare
`core.config.empreinte_dossier(DATA_DIR)` avant et après un clic sur « Enregistrer » servi par un
moteur FACTICE — si `data/` a changé, c'est la console qui a touché au disque.

⚠️ **La phrase d'honnêteté vient du résultat du moteur** (`candidat["honnetete"]`), pas de la
constante `HONNETETE` de `calib_page.py` : elle diffère par mode. Celle du MI parle de 40 % à trois
classes et n'a aucun sens pour le P300.

## e. La fermeture

`EngineServer.close()` existe et est idempotente. La console doit l'appeler dans son `closeEvent` —
sans ça, un candidat de calibration peut survivre à la fermeture, et le dossier temporaire avec.

## Les tests

Dans `_smoke` de `src/console/app.py` (Qt **offscreen**), motif `chk(cond, msg)`, phrases
françaises qui disent ce qui est vérifié et pourquoi.

⚠️ **Aucun VRAI processus dans le smoke** : injecte un faux `QProcess`. Un smoke qui lance pygame
en CI est un smoke qu'on finit par désactiver.

À couvrir : la commande demandée vient de `stimulus/registry.py` ; le refus du second lancement ;
une fenêtre morte le dit à l'écran ; le contact mauvais empêche le lancement **et le dit** ;
`start_calibration` est envoyé AVANT le lancement de la fenêtre ; le mode est arrêté avant ;
« Enregistrer » et « Refaire » envoient leur commande ; la console n'écrit pas sur le disque ; le
`closeEvent` appelle `close()`.

## Contraintes qui te lient

- **La console est un CLIENT** : aucune logique que le moteur ne possède déjà, aucun catalogue
  recopié, **aucune écriture disque**, aucune validation côté interface.
- `src/console/` peut importer `core` et `stimulus`. **Jamais l'inverse.** Vérifié par
  `python src/core/server.py --smoke`.
- **Code et commentaires en français**, messages de commit en anglais.
- Tout testable **sans casque** et **sans écran** (Qt offscreen).
- **Aucun test n'écrit dans le vrai `data/`** — enregistrements EEG d'une personne identifiable,
  dépôt PUBLIC. `git status` ne prouve rien (`data/` est gitignoré) : `empreinte_dossier`.
- ⚠️ Aucun autre programme du projet ne tourne pendant tes tests.

## Quand tu as fini

```bash
python src/console/app.py --smoke
python src/core/server.py --smoke
python src/stimulus/registry.py
python src/core/modes/p300_calib.py
python src/research/app.py --smoke
```

Commite (anglais), rapport dans `task-6-report.md`, message final réduit à : statut, hash, une
ligne de tests, réserves.
