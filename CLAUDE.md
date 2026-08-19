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
- L'**application pygame** (`src/research/app.py`, menu à 5 modes) reste le seul accès au **dernier
  mode que le moteur ne sait pas faire** : le c-VEP. Le SSVEP, le neuro, le **Motor Imagery**, l'**ErrP** et
  le **P300** sont publiés par le moteur et pilotés depuis la console — **la calibration MI aussi** : un bouton
  « Calibrer » sur sa page joue la séance et affiche un modèle horodaté avec son accuracy honnête.
  Les anciens écrans pygame du MI (calibration, pilotage) sont **archivés**, pas supprimés, dans
  [`archive/`](archive/README.md) : ils restent la référence contre laquelle vérifier la calibration
  du moteur.
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
python src/core/server.py --mode p300      # le P300 sur le réseau (EXIGE un modèle ET des marqueurs entrants)
python src/research/p300_stimulus.py       # l'émetteur de marqueurs P300 — n'ouvre PAS le casque,
                                           # donc se lance EN MÊME TEMPS que le moteur (2 terminaux)
# calibration MI : bouton « Calibrer » sur sa page dans la console — plus de commande séparée
python src/research/app.py                 # l'appli pygame, plein écran, casque réel
python src/research/app.py --windowed      # en fenêtre (console visible à côté)
python src/research/app.py --synthetic     # sans casque (board de test BrainFlow)
```

**Après toute modification**, les trois tests headless qui couvrent le plus de code (aucun casque) :

```bash
python src/core/server.py --smoke          # moteur : registre, frontière, repos partagé, cumul, flux
python src/console/app.py --smoke          # console : grille, page de mode, réglages (Qt offscreen)
python src/research/app.py --smoke         # appli : menu + les 5 modes + les calibrations
```

Et le sous-système des **marqueurs entrants**, livré le 2026-08-17, qu'aucun smoke ci-dessus ne
couvre entièrement :

```bash
python src/core/markers.py                 # l'oreille du moteur : résolution PAR NOM, time_correction
python src/core/p300_models.py             # les modèles P300 : refus des hérités, tri par date
python src/core/modes/p300.py              # le mode : ALIGNEMENT des époques, abandon de manche, appariement score↔cible
python src/core/errp_models.py             # les modèles ErrP : refus des hérités ET des calibrations dégénérées
python src/core/modes/errp.py              # le mode ErrP : ALIGNEMENT, rejet d'artefact, MONOTONIE du réglage
python src/research/errp_stimulus.py --smoke  # l'émetteur ErrP : piste, erreurs délibérées, horodatage au flip
python src/research/p300_stimulus.py --smoke  # la séquence de flashs : chaque cible vue `reps` fois
```

⚠️ **`modes/p300.py` porte LE test qui protège tout ce sous-système** : un décalage de quelques
échantillons à l'épochage rend tous les autres tests verts et fait décoder du bruit avec une
confiance de 0,92 — indiscernable d'un succès. Mesuré : la mutation déplace le pic de −38
échantillons (−152 ms) et les 46 autres assertions restent vertes.

Et les cinq gardes du Motor Imagery, qu'**aucun des trois smokes ci-dessus n'exécute** :

```bash
python src/core/acquisition.py --synthetic # fenêtre MI NON filtrée (double filtrage = bruit à p=0,99)
python src/core/modes/mi.py                # seuil, longueur du vote, appariement p_<classe> ↔ classe
python src/core/mi_models.py               # refus des modèles hérités, tri du plus récent au plus ancien
python src/core/modes/calibration.py       # la ligne du temps d'une calibration : chauffe, essais, entraînement, abandon
python src/core/modes/mi_calib.py          # calibration MI : accuracy HONNÊTE (CV par essai), jamais d'écrasement
```

Le non-filtrage de la fenêtre MI est l'invariant central du sous-système et il n'est vérifié que
par le premier : un double filtrage réintroduit demain passerait les trois smokes sans un mot.

⚠️ **Ne laisser tourner AUCUN moteur pendant un test.** Les noms de flux sont un contrat public,
donc identiques pour toutes les instances : un serveur oublié répond à la place de celui qu'on teste
(les smokes filtrent sur le `source_id`, mais la confusion reste facile).

## Pièges matériels à connaître

- **Ne pas fermer/rouvrir l'appli** en cours de séance : les voies C3/Cz saturent à la réouverture
  (redémarrage de l'amplificateur). Garder une seule session ouverte.
- **Saliner les électrodes** est le principal levier de qualité du signal (gain mesuré très net).
- Vérifier le contact **avant** d'enregistrer : une électrode ou une référence décollée produit une
  séance entière inexploitable, sans autre signal d'alerte que l'écran de contrôle de liaison.
