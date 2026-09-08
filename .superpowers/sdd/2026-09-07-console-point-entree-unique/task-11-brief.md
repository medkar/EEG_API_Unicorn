# Tâche 11 — la documentation

Projet **EEG_API_Unicorn** : API BCI pour étudiants. Lire `CLAUDE.md` **en premier**, c'est le
fichier que tu vas le plus modifier.

Les tâches 1 à 10 sont livrées : le produit a changé de forme, et **toute la documentation décrit
encore l'ancienne**. Ta tâche est la dernière, et c'est celle qui décide si quelqu'un comprendra ce
qui a été fait.

⚠️ **Mesuré sur un chantier précédent de ce dépôt : 0 régression dans 2000 lignes de code relu, et
1 régression plus 8 faussetés dans la doc écrite sans relecteur.** La documentation se relit comme
du code. **Vérifie chaque commande que tu cites en la lançant**, et chaque chiffre en le retrouvant
dans le code ou dans `docs/recette.md`.

## Ta source de vérité

`.superpowers/sdd/2026-09-07-console-point-entree-unique/progress.md` — le carnet de bord du
chantier, complet, avec les arbitrages et les défauts trouvés. Puis les rapports `task-3-report.md`
à `task-10-report.md` du même dossier, et `git log --oneline 010222d..HEAD`.

La spec et le plan disent l'intention : `docs/superpowers/specs/2026-09-07-console-point-entree-unique-design.md`
et `docs/superpowers/plans/2026-09-07-console-point-entree-unique.md`. ⚠️ **Ils décrivent ce qu'on
voulait faire, pas ce qui a été fait** — plusieurs points ont bougé en chemin (le paquet
`src/stimulus/`, l'archivage des calibrations pygame, l'abandon de la compression `tanh`). Quand ils
divergent du code, **c'est le code qui a raison**.

## Ce qui a changé, en une page

- **Quatre paquets** au lieu de trois : `core`, **`stimulus`** (nouveau), `console`, `research`.
  Règle vérifiée par le scanner AST de `server.py --smoke` : `core` n'importe rien du dépôt ;
  `stimulus` n'importe que `core` ; `console` importe `core` et `stimulus` ; `research` de même.
- **Les quatre calibrations sont jouées par le MOTEUR** et affichées par la console. `Calib.kind`
  ne dit plus *où* la calibration vit (« console » / « natif ») mais **qui mène la ligne du
  temps** : `"moteur"` (le MI, endogène) ou `"fenetre"` (P300, ErrP, c-VEP).
- **Le contrat public des marqueurs a gagné trois événements** : `calib_start`, `cue`, `calib_end`.
  ⚠️ **L'ErrP n'utilise pas `cue`** : son étiquette voyage sur son `feedback`, qui gagne
  `error: true|false` **en calibration seulement** — en décodage le marqueur reste nu, parce que
  c'est une BCI passive et que lui donner la réponse rendrait faux tout ce qu'on mesure.
  ⚠️ **Le c-VEP continue de publier `cycle` pendant sa calibration** : c'est l'horloge, sans elle
  il n'y a pas de phase.
  **Conséquence à documenter** : toute application capable d'afficher le stimulus peut désormais
  entraîner un modèle. La calibration n'est plus verrouillée à notre pygame.
- **`data/` n'est écrit qu'à un seul endroit** : la commande `save_calibration`, envoyée par la
  console quand on clique « Enregistrer ». Avant, une calibration sauvegardait PUIS annonçait sa
  précision — et comme le moteur propose le modèle chargeable le plus récent, une calibration
  ratée devenait le défaut en silence.
- **Un mode et sa propre calibration ne peuvent plus tourner ensemble** : ils liraient la même file
  de marqueurs et s'en voleraient chacun une partie, sans erreur.
- **L'appli pygame `src/research/app.py` est SUPPRIMÉE.** Ses six écrans (3 pilotages + 3
  calibrations) sont dans `archive/`, avec leur `--smoke`. `archive/README.md` est à jour, ne le
  refais pas.
- **`outils/Console EEG.bat`** ouvre la console sans terminal.

## Les fichiers à reprendre

1. **`CLAUDE.md`** (français) — le plus important, c'est lui qu'on lit en arrivant. La règle des
   trois paquets devient quatre. **Toute la section « Commandes utiles » est à refaire** : plus de
   `src/research/app.py`, plus de `src/research/*_stimulus.py`, et les calibrations ne sont plus
   des commandes mais des boutons. La liste des autotests gagne `marker_calib.py`, les trois
   `*_calib.py`, `errp_track.py` et les trois `stimulus/*.py --smoke`.
2. **`docs/markers.md`** (**anglais** — contrat public) — une section « Training a model through
   the markers » : les trois événements, leur charge utile, le cas particulier de l'ErrP, et la
   conséquence pour une application tierce.
3. **`docs/recette.md`** (français) — les tests 1.14, 1.15, 1.16, 2.6, 2.7, 2.8 et 2.9 décrivent
   des montages à deux ou trois terminaux qui deviennent des clics. ⚠️ **Ne touche à AUCUN repère
   chiffré** (100 %/44 % pour le SSVEP, 46 %/71 % pour le c-VEP, une erreur sur deux pour l'ErrP,
   ~40 % à trois classes pour le MI) : ce chantier n'a rien mesuré.
4. **`README.md`** (anglais) et **`docs/SPEC.md`** (français) — le point d'entrée unique, le
   quatrième paquet.

## Ce que tu ne fais PAS

- Aucune modification de code, sauf si tu trouves une commande citée qui ne marche pas : dans ce
  cas, **dis-le dans ton rapport**, ne corrige pas le code depuis une tâche de documentation.
- `archive/README.md` est déjà fait.
- Ne réécris pas les repères chiffrés, ne réinterprète aucune mesure.

## Une honnêteté à ne pas perdre

**Rien de ce chantier n'a vu un cerveau.** Les autotests prouvent le câblage, jamais l'ergonomie ni
le décodage. Quatre modes sur six n'ont toujours jamais été décodés au casque à travers le moteur.
La documentation doit le dire aussi clairement qu'avant — c'est le genre de phrase qu'une réécriture
fait disparaître sans intention.

Et deux réserves ouvertes, à consigner là où elles seront lues :
- le **contrôle de liaison** de la console refuse dès qu'une voie sort de [0,5 ; 500] µV et n'offre
  **aucune porte de sortie**. Il peut bloquer une séance légitime ; à trancher devant un casque ;
- **l'ordre de lancement** fenêtre/moteur n'a **aucune poignée de main** entre les deux processus :
  la console envoie `start_calibration` puis lance la fenêtre, et c'est l'initialisation de pygame
  qui couvre la chauffe. Ça tient, ce n'est pas garanti.

## Quand tu as fini

Lance **chaque commande que tu cites** dans `CLAUDE.md` et `docs/recette.md` — les autotests, pas
celles qui exigent un casque. Colle la liste et son résultat dans ton rapport.

Commite (anglais), rapport dans `task-11-report.md`, message final réduit à : statut, hash, la
liste des commandes vérifiées, et **toute affirmation que tu n'as pas pu vérifier**.
