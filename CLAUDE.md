# Contexte projet — EEG_API_Unicorn

Projet : **une API BCI utilisable par des étudiants**. Un casque EEG **Unicorn Hybrid Black** est
acquis et décodé par cet outil, et le résultat est **diffusé sur le réseau (LSL)** pour être consommé
par n'importe quelle application externe (Unity, Python, MATLAB, web).

## Ce qu'il faut savoir en arrivant

- **Lire [docs/SPEC.md](docs/SPEC.md) en premier** : but, architecture, contrat des flux, décisions
  figées et roadmap. C'est le document de référence du projet.
- Le produit est **agnostique de l'application avale** : chaque mode publie une **intention neutre**
  (quelle cible, quelle classe, quel état mental), **jamais une commande d'actionneur**. Traduire ça
  en action (jeu, visualisation, robot…) est le travail de l'application cliente.
- Un **TurtleBot3 Waffle** a servi de banc d'essai historique au décodage. Ce n'est **plus un
  objectif** : voir [docs/robot_testbed.md](docs/robot_testbed.md) au besoin, mais rien de neuf ne
  doit en dépendre.
- **Le code se divise en TROIS paquets, sur une règle vérifiable** : `src/core/` = ce dont le moteur
  (`server.py`) a besoin pour tourner, `core/modes/` compris ; `src/console/` = la console PySide6 ;
  `src/research/` = tout le reste (appli pygame, décodeurs des modes non publiés, calibrations,
  analyses). `console` et `research` importent `core`, **jamais l'inverse** — si l'envie s'en
  présente, c'est que le module visé doit DÉMÉNAGER dans `core`. Ni pygame ni Qt dans `core` : le
  moteur tourne sans écran. Vérifié par un test, pas par la discipline : `server.py --smoke` scanne
  `src/core/**/*.py` et échoue sur le moindre import interdit.
- **La console est un CLIENT du moteur**, pas le moteur : elle crée un `EngineServer`, lance sa
  boucle dans un fil et sonde `snapshot()`. Le fil Qt ne touche jamais la session BrainFlow — toute
  action passe par la file de commandes. Et aucune logique n'y vit que le moteur ne possède déjà :
  pas de validation côté interface, pas de catalogue de modes recopié.
- L'**application pygame** (`src/research/app.py`, menu à 6 modes) reste le seul accès aux **3 modes
  que le moteur ne sait pas faire** : c-VEP, P300, ErrP. Le SSVEP, le neuro et le **Motor Imagery**
  sont publiés par le moteur et pilotés depuis la console. ⚠️ La **calibration** MI, elle, vit encore
  dans l'appli pygame (`src/research/mi_calibrate.py`) : le moteur consomme un modèle entraîné, il ne
  sait pas encore l'entraîner. C'est la moitié B du chantier 3.
- ⚠️ **Un seul de ces trois programmes à la fois** — console, moteur, appli pygame. Le casque
  n'accepte qu'une connexion, et les noms de flux sont un contrat public : deux instances publient
  sous le même nom, donc un programme oublié répond à la place de celui qu'on teste.
- Public visé = **des étudiants qui vont lire et modifier ce code**. Écrire en conséquence.

## Matériel

Casque **Unicorn Hybrid Black** : 8 voies EEG sèches, 250 Hz, Bluetooth. Montage fixe
`[Fz, C3, Cz, C4, Pz, PO7, Oz, PO8]` (indices 0-7). PC de dev sous **Windows** (PowerShell).

## Façon de travailler (préférences de l'utilisateur)

- Répondre en **français** ; README, doc et messages de commit **en anglais** pour GitHub.
- Avancer par **petits pas testés sur le matériel** : éditer → lancer → coller les logs.
- **Vérifier la doc** (SDK Unicorn, LSL, littérature BCI) avant d'affirmer ; citer les sources sur les
  points incertains.
- Recommander **une option claire** plutôt qu'un catalogue ; privilégier la simplicité.
- **Rigueur statistique** : ne jamais conclure sur du bruit. Sur de petits échantillons EEG, valider
  une hypothèse par un test (permutation, validation croisée honnête) avant d'y croire.

## Commandes utiles

```bash
python src/console/app.py --mode ssvep     # LA console : grille des modes, réglages, tracés
python src/console/app.py --synthetic      # la console sans casque (board de test BrainFlow)
python src/core/server.py --mode ssvep --refresh 60   # le moteur seul (headless) : décode et publie
python src/core/server.py --mode ssvep,neuro   # deux modes en même temps
python src/core/server.py --mode mi        # le Motor Imagery sur le réseau (EXIGE un modèle entraîné)
python src/research/mi_calibrate.py        # entraîner ce modèle (seul chemin aujourd'hui)
python src/research/app.py                 # l'appli pygame, plein écran, casque réel
python src/research/app.py --windowed      # en fenêtre (console visible à côté)
python src/research/app.py --synthetic     # sans casque (board de test BrainFlow)
```

**Après toute modification**, les trois tests headless qui couvrent le plus de code (aucun casque) :

```bash
python src/core/server.py --smoke          # moteur : registre, frontière, repos partagé, cumul, flux
python src/console/app.py --smoke          # console : grille, page de mode, réglages (Qt offscreen)
python src/research/app.py --smoke         # appli : menu + les 6 modes + les calibrations
```

⚠️ **Ne laisser tourner AUCUN moteur pendant un test.** Les noms de flux sont un contrat public,
donc identiques pour toutes les instances : un serveur oublié répond à la place de celui qu'on teste
(les smokes filtrent sur le `source_id`, mais la confusion reste facile).

## Pièges matériels à connaître

- **Ne pas fermer/rouvrir l'appli** en cours de séance : les voies C3/Cz saturent à la réouverture
  (redémarrage de l'amplificateur). Garder une seule session ouverte.
- **Saliner les électrodes** est le principal levier de qualité du signal (gain mesuré très net).
- Vérifier le contact **avant** d'enregistrer : une électrode ou une référence décollée produit une
  séance entière inexploitable, sans autre signal d'alerte que l'écran de contrôle de liaison.
