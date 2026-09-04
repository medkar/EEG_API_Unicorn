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
- **Le moteur publie les SIX modes** depuis le 2026-08-21 : SSVEP, neuro, Motor Imagery, P300, ErrP
  et **c-VEP**. Ils se pilotent tous depuis la console. ⚠️ **Publié ≠ validé** : seul le SSVEP a été
  décodé sur un vrai cerveau À TRAVERS le moteur. Les quatre modes à modèle (MI, P300, ErrP, c-VEP)
  attendent une séance casque — c'est la recette, tests 2.6 à 2.9.
- L'**application pygame** (`src/research/app.py`, menu à 5 pages) n'est plus le seul accès à aucun
  mode. Il lui reste **les calibrations que le moteur ne sait pas jouer** — c-VEP, P300, ErrP, dont
  le stimulus doit être verrouillé à la frame, d'où `Calib(kind="natif")` dans leurs trois
  `ModeSpec` —, l'histogramme neuro, **et trois écrans de PILOTAGE que ce chantier n'a pas
  retirés : SSVEP (`mode_ssvep`), sélection P300 (`mode_p300`) et démonstrateur ErrP
  (`mode_errp`)**. Ces trois-là font double emploi avec le moteur et ne doivent jamais tourner en
  même temps que lui. Seuls le c-VEP et le MI y ont perdu leur pilotage. La calibration, elle, est
  le geste que le moteur lui-même prescrit quand il refuse de démarrer.
  **La calibration MI, elle, est jouée par le moteur** : un bouton « Calibrer »
  sur sa page de la console joue la séance et écrit un modèle horodaté avec son accuracy honnête.
  Les anciens écrans pygame de **pilotage** (MI, c-VEP) sont **archivés**, pas supprimés, dans
  [`archive/`](archive/README.md) : ils restent la référence contre laquelle comparer le moteur.
  `archive/cvep_pilot.py` est le plus utile des quatre — même modèle, même vote 2-sur-3, décodage
  LOCAL : c'est lui qui, en séance, sépare « le décodage réseau est moins bon » de « la séance est
  moins bonne » (recette 2.9).
- ⚠️ **Le c-VEP est le seul mode dont les marqueurs ne délimitent RIEN.** Ceux du P300 et de l'ErrP
  disent « un événement a eu lieu, découpe autour » ; celui du c-VEP dit « à cet instant, le code
  affiché était à sa frame 0 » — c'est une **HORLOGE**, et le mode décode en continu sur une fenêtre
  glissante comme le SSVEP. Sans elle il ne décode pas mal : il ne décode **rien**.
- ⚠️ **Un seul de ces quatre programmes à la fois** — console, moteur, appli pygame, écran archivé.
  Le casque n'accepte qu'une connexion, et les noms de flux sont un contrat public : deux instances
  publient sous le même nom, donc un programme oublié répond à la place de celui qu'on teste.
  **Les trois émetteurs de stimulus sont l'exception** (`p300_stimulus.py`, `errp_stimulus.py`,
  `cvep_stimulus.py`) : ils n'ouvrent PAS le casque, ils dessinent et publient des marqueurs — c'est
  exactement pour ça qu'ils se lancent dans un second terminal, à côté du moteur.
- Public visé = **des étudiants qui vont lire et modifier ce code**. Écrire en conséquence.

## Matériel

Casque **Unicorn Hybrid Black** : 8 voies EEG sèches, 250 Hz, Bluetooth. Montage fixe
`[Fz, C3, Cz, C4, Pz, PO7, Oz, PO8]` (indices 0-7). PC de dev sous **Windows** (PowerShell).

## Façon de travailler (préférences de l'utilisateur)

- Répondre en **français** ; README, doc et messages de commit **en anglais** pour GitHub. Deux
  exceptions assumées, parce qu'elles ne s'adressent pas à GitHub : `docs/SPEC.md` (document de
  travail interne) et `docs/recette.md` (procédure exécutée ici) restent en français.
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
python src/core/server.py --mode errp      # l'ErrP sur le réseau (EXIGE un modèle ET des marqueurs)
python src/research/errp_stimulus.py       # l'émetteur de marqueurs ErrP — n'ouvre PAS le casque non
                                           # plus, même montage à 2 terminaux que le P300
python src/core/server.py --mode cvep      # le c-VEP sur le réseau (EXIGE un modèle ET une HORLOGE)
python src/research/cvep_stimulus.py       # l'émetteur c-VEP : fait clignoter ET publie un marqueur
                                           # de CYCLE (~1/s). N'ouvre PAS le casque -> 2 terminaux.
                                           # --seed rejoue les consignes, --windowed pour le dev
python src/research/cvep_stimulus.py --log seance.jsonl   # ⚠️ EN SÉANCE : la vérité-terrain dans un
                                           # FICHIER (une ligne par consigne, horodatée en
                                           # local_clock()). Sans elle la séance ne se dépouille
                                           # pas : le terminal en est le seul autre exemplaire
python archive/cvep_pilot.py --model data/cvep_model_….npz   # l'écran archivé : décodage LOCAL, la
                                           # RÉFÉRENCE à comparer au réseau en séance (recette 2.9).
                                           # ⚠️ --model explicite : son défaut pointe l'ancien nom fixe
# calibration MI : bouton « Calibrer » sur sa page dans la console — plus de commande séparée
python src/research/app.py                 # l'appli pygame, plein écran, casque réel
                                           # -> menu c-VEP / P300 / ErrP : « Calibrer », les seules
                                           #    calibrations que le moteur ne sait pas jouer
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

Et les six gardes du **c-VEP**, livré le 2026-08-21, qu'aucun des trois smokes n'exécute :

```bash
python src/core/cvep_code.py               # la m-séquence : équilibre, autocorrélation, lags distincts
python src/core/cvep_decoder.py            # l'eCCA : justesse vs SNR, aller-retour du modèle
python src/core/cvep_rcca.py               # le rCCA : le 2e décodeur, sur le MÊME stimulus décalé
python src/core/cvep_models.py             # les modèles : refus des hérités, QUEL décodeur, tri par date
python src/core/modes/cvep.py              # le mode : la PHASE, les 4 causes de -1, le vote glissant
python src/research/cvep_stimulus.py --smoke  # l'émetteur : la phase lue dans les PIXELS, frame par frame
```

⚠️ **`cvep_stimulus.py --smoke` porte LE test qui protège ce sous-système**, et il est de la même
famille que celui de `modes/p300.py` : il rejoue une course de rendu image par image et compare la
phase que le moteur reconstruirait à celle réellement AFFICHÉE, lue dans les pixels de l'écran —
pas dans le compteur de l'émetteur, qui ne peut que se donner raison. L'assertion exige **zéro**
frame d'écart tant qu'aucune image n'est sautée : une tolérance à ±1 laisserait passer un décalage
systématique d'une frame, c'est-à-dire la panne. Remonter le `push_sample` au-dessus du
`display.flip()` la fait rougir — et ne fait rougir qu'elle.

⚠️ **La panne caractéristique du c-VEP ne casse rien** : une phase fausse de quelques frames ne lève
aucune exception, les corrélations baissent juste assez pour que rien ne se déclenche, et c'est
indiscernable d'un étudiant qui fixe mal. Deux gestes la produisent, à une ligne l'un de l'autre :
horodater AVANT le flip, ou annoncer un `refresh` que l'écran ne tient pas.

⚠️ **Ne laisser tourner AUCUN moteur pendant un test.** Les noms de flux sont un contrat public,
donc identiques pour toutes les instances : un serveur oublié répond à la place de celui qu'on teste
(les smokes filtrent sur le `source_id`, mais la confusion reste facile).

## Pièges matériels à connaître

- **Ne pas fermer/rouvrir l'appli** en cours de séance : les voies C3/Cz saturent à la réouverture
  (redémarrage de l'amplificateur). Garder une seule session ouverte.
- **Saliner les électrodes** est le principal levier de qualité du signal (gain mesuré très net).
- Vérifier le contact **avant** d'enregistrer : une électrode ou une référence décollée produit une
  séance entière inexploitable, sans autre signal d'alerte que l'écran de contrôle de liaison.
