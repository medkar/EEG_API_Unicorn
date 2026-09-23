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
- **Le moteur reste LE PRODUIT ; la console est devenue le POINT D'ENTRÉE** (2026-09-08), et depuis
  le **2026-09-09 il n'y a plus une seule commande d'usage réel à taper**. Le parcours d'un
  étudiant — choisir la source, vérifier le casque et le contact, régler, entraîner, **tester**,
  décoder, **regarder le flux sortant, enregistrer les verdicts** — s'y fait aux boutons, dans une
  seule fenêtre qu'on n'a plus à fermer. ⚠️ **Deux trous, datés du 2026-09-22 et connus** : la
  séance c-VEP avec journal (recette 2.9) et le décodage continu avec NOTRE fenêtre de stimulus
  n'ont plus de bouton — ils reviennent avec « Connecter », le second chantier (pas fait).
  `outils/Console EEG.bat` l'ouvre par un double-clic, sans terminal. `src/core/server.py` reste
  lançable seul : c'est l'accès *headless*, pour une machine sans écran ou un montage à deux
  terminaux, et c'est lui que consomme un client LSL.
- **Le code se divise en QUATRE paquets, sur une règle vérifiable** : `src/core/` = ce dont le
  moteur (`server.py`) a besoin pour tourner, `core/modes/` compris ; `src/stimulus/` = les
  **quatre** fenêtres pygame qui affichent un stimulus verrouillé à la frame et publient des
  marqueurs (`p300.py`, `errp.py`, `cvep.py`, et `ssvep.py` depuis le 2026-09-09) ; `src/console/`
  = la console PySide6 ; `src/research/` = tout le reste, et **rien qui ouvre le casque ou dessine**
  (analyses hors ligne, protocoles chiffrés, hypothèses réfutées).

  ```text
  core       n'importe rien du dépôt hors de lui-même   (ni research, ni console, ni stimulus)
  stimulus   -> core                                    (jamais research, jamais console)
  console    -> core, stimulus
  research   -> core, stimulus
  ```

  Si l'envie de remonter une flèche se présente, c'est que le module visé doit DÉMÉNAGER — vers
  `core` s'il sert au décodage, vers `stimulus` s'il sert au stimulus. Ni pygame ni Qt dans `core` :
  le moteur tourne sans écran. **Les INTERDITS des QUATRE lignes sont vérifiés par un test**, pas
  par la discipline : `server.py --smoke` (`[smoke-frontiere]`) parse en AST **les quatre paquets**
  — `src/core/`, `src/stimulus/`, `src/research/` et `src/console/` —, chacun avec sa liste
  d'interdits, et échoue sur le moindre import interdit. Il vérifie aussi que chaque dossier est
  **présent et non vide** : un paquet renommé ou vidé rendrait « 0 violation » et passerait pour
  un succès.

  ⚠️ **`src/console/` n'était scanné par AUCUNE règle avant le 2026-09-10**, alors que cette phrase
  promettait déjà un test sous le tableau : `console → research` et `research → console` passaient
  tous les deux. Même forme que le défaut trouvé le 2026-09-08 sur `core` (« ni pygame **ni Qt** »
  écrit, seul pygame vérifié) — **la règle écrite plus large que sa vérification**, et c'est
  toujours le cran manquant qui compte. Aucun import fautif n'existait le jour du correctif : le
  risque était théorique, mais « personne ne le fait aujourd'hui » est de la discipline, pas un
  test.
- 🔴 **TOUT L'USAGE RÉEL SE PILOTE DEPUIS L'INTERFACE. Un utilisateur ne tape aucune commande.**
  C'est une contrainte de conception permanente, du même rang que la frontière ci-dessus — pas une
  fonctionnalité qu'on ajoute quand on y pense. **Une capacité livrée sans chemin graphique est une
  tâche INCOMPLÈTE**, pas une tâche à finir plus tard.

  L'« usage réel », c'est **l'acquisition, le décodage, et le flux récupérable à l'extérieur** par
  l'application qu'écrira l'utilisateur. En sont DEHORS, et ce n'est pas une échappatoire : les
  autotests (`--smoke`, autotests de module), qui s'adressent au développeur ; et
  `server.py --mode X`, le moteur **sans écran**, dont c'est justement le contrat public.

  **Vérifié par le même test** : rien dans `src/research/` n'importe `core.acquisition`,
  `brainflow`, `pygame` ni `console`. Le banc d'essai peut tout CALCULER sur des fichiers
  archivés — c'est son métier — mais ouvrir le casque ou afficher un stimulus sont des gestes
  d'usage réel, donc ils appartiennent à l'application. **Vert depuis le 2026-09-09** :
  `[smoke-frontiere] 0 violation(s) de frontière`. (Le NOMBRE de fichiers n'est pas cité : un
  compte en prose n'est tenu par rien, et celui-ci était déjà faux deux commits plus tard — 57
  contre 58.) Il était ROUGE en le posant, sur six fichiers — c'est ce rouge-là qui a servi de
  liste de travail au chantier « plus une seule commande à taper ».

  **La RÉCIPROQUE est vérifiée depuis le 2026-09-10** : rien dans `src/console/` n'importe
  `research`. Une analyse hors ligne qui doit passer à portée de clic DÉMÉNAGE dans `core` ; elle
  ne se branche pas sur un bouton depuis le banc d'essai.

  ⚠️ **Cette règle a été demandée CINQ FOIS entre juillet et septembre 2026 avant d'être écrite
  ici.** Chaque fois elle a été traitée comme une fonctionnalité — on ajoutait un bouton — et le
  chantier suivant repartait sans elle, donc un nouveau trou apparaissait. C'est pour ça qu'elle
  est dans ce fichier ET dans un test : une contrainte tenue par la discipline n'est pas tenue.
- 🔴 **UNE PAGE DE MODE A SES GESTES NUMÉROTÉS, ET PAS UN DE PLUS ; « TESTER » POSSÈDE SA SÉQUENCE
  ENTIÈRE** (2026-09-22). Même rang que les deux règles ci-dessus. Une page = **1. Régler ·
  2. Entraîner** (si le contrat déclare une `calibration`) **· N. Tester** (s'il déclare un
  `test_id`) ; sans vérité-terrain (Neuro, Brut) : **2. Observer**, sans aucun score. La forme est
  tirée du CONTRAT (`console/mode_page.py`), jamais d'une liste de l'interface.
  « Tester » applique d'abord ce qui est à l'écran (refusé → pas de test), ouvre le test
  pré-rempli avec les réglages du mode, et « Commencer » passe le contrôle de liaison, arrête le
  mode s'il tourne, soumet la mesure PUIS lance la fenêtre, et rend un verdict. Un nouveau geste
  s'ajoute DANS une de ces séquences, pas à côté d'elles. **Tenu par `console/app.py --smoke`** :
  les titres de blocs par mode, et un parcours de l'ARBRE des widgets qui rougit si une page porte
  « Démarrer », « Lancer le stimulus », « Journal de séance », « Copier » ou « Calibrer ».
  **Pourquoi** : l'ancienne page offrait « Démarrer », « Calibrer » et « Lancer le stimulus » comme
  trois choix de même rang, alors qu'il existe un ORDRE. À la séance casque du 2026-09-22, le
  stimulus a tourné sur un mode arrêté : **dix minutes de fixation perdues**, puis « je ne
  comprends pas trop ce que l'on fait ». Un bouton qui possède toute la séquence rend ce piège
  **impossible** au lieu de le signaler. La boucle réelle est régler → tester → ajuster →
  re-tester (spec : `docs/superpowers/specs/2026-09-22-configurer-entrainer-tester-design.md`).
- **La console est un CLIENT du moteur**, pas le moteur : elle crée un `EngineServer`, lance sa
  boucle dans un fil et sonde `snapshot()`. Le fil Qt ne touche jamais la session BrainFlow — toute
  action passe par la file de commandes. Et aucune logique n'y vit que le moteur ne possède déjà :
  pas de validation côté interface, pas de catalogue de modes recopié.
- **UN RÉGLAGE SE POSE SUR UN MODE ARRÊTÉ** (2026-09-21). `set_params` le VALIDE — c'est là qu'on
  apprend que 17 Hz ne divise pas 60 — puis le RETIENT dans `EngineServer.reglages`, et le prochain
  démarrage part avec. L'accusé porte `differe: True`, que la console affiche en VERT (« réglage
  RETENU : « SSVEP » est arrêté, il démarrera avec. ») : accepté est un succès, la nuance « pas
  encore en vigueur » est dans le texte, et un « appliqué » nu ferait croire que le mode décode déjà.
  C'est le geste réel — on cale ses fréquences sur son écran et son pic alpha sur sa tête, **puis**
  on lance. Avant, il fallait démarrer sur des réglages qu'on savait faux, subir 23 s de repos,
  corriger, et refaire le repos.
  ⚠️ **Le défaut tenait à ce que les deux moitiés du même geste n'étaient pas d'accord** :
  `propose_params` acceptait un mode arrêté depuis toujours, `set_params` le refusait. Le moteur
  proposait un jeu de fréquences, le mettait dans le champ, et refusait de l'appliquer. Aucun test
  ne le voyait — les deux commandes étaient testées séparément, chacune sur son propre décor.
- **Le moteur publie les SIX modes** depuis le 2026-08-21 (SSVEP, neuro, Motor Imagery, P300, ErrP,
  c-VEP) **et joue les QUATRE calibrations** depuis le 2026-09-08. ⚠️ **Publié ≠ validé** : seul le
  SSVEP a été décodé sur un vrai cerveau À TRAVERS le moteur. Les quatre modes à modèle (MI, P300,
  ErrP, c-VEP) attendent une séance casque — c'est la recette, tests 2.6 à 2.9. **Les chantiers de
  la console n'y ont rien changé** : ils déplacent des gestes, ils ne décodent aucun cerveau. Leurs
  autotests prouvent le câblage, jamais l'ergonomie ni le décodage.
- **Le moteur joue aussi SIX MESURES** (`core/modes/mesure.py`, `MesureRuntime` ; celles qu'une
  fenêtre mène héritent de `core/modes/mesure_marqueurs.py`). Une mesure est un protocole minuté
  qui rend un **verdict**, pas un modèle : elle n'écrit **rien** sur le disque, donc ni
  « Enregistrer » ni « Refaire ». Page générique `console/mesure_page.py`. **Une seule a une tuile
  sur l'accueil** ; les cinq autres sont les « Tester » des modes (`ModeSpec.test_id`) et vivent
  sur la page de LEUR mode — la grille lit les `test_id`, elle ne tient aucune liste.
  - **`alpha` — « Vérifier le casque »** (37 s, `core/modes/alpha.py`). Yeux ouverts / yeux fermés,
    effet de Berger. C'est une **BARRIÈRE** (`MesureSpec.barriere`) : si l'alpha ne monte pas, aucun
    autre test de la séance ne veut rien dire (mot « ARRÊTE ICI »). Deux portes : la tuile de
    l'accueil, et **« Mesurer »** à côté du pic alpha de la page SSVEP — le moteur déclare quel
    réglage la mesure remplit (`ControleAlpha.REGLAGE_PRODUIT`), et la page propose d'**appliquer
    le pic mesuré** à `alpha_hz`. ⚠️ Ce bouton échouait SYSTÉMATIQUEMENT jusqu'au 2026-09-21
    (`set_params` exigeait un mode démarré) — trouvé par la QA, pas par un test.
  - **`ssvep_taux` — « Tester le SSVEP »** (≈ 3,6 min, 36 essais). Une fenêtre (`src/stimulus/ssvep.py
    --guide --freqs …`) désigne la cible **sur les fréquences du mode**, le moteur applique **sa
    propre règle de décision** et rend le taux d'émission et la justesse à l'émission. ⚠️ **Un
    essai = UNE décision** : compter les fenêtres glissantes gonflerait l'effectif d'un facteur ~7.
  - **`mi_test`, `p300_test`, `cvep_test`, `errp_test` — « Tester le … »**. Le protocole
    d'ENTRAÎNEMENT rejoué (fenêtre en `--tester` pour P300/ErrP/c-VEP ; le MI n'a pas de fenêtre),
    le moteur DÉCIDANT par le runtime de son mode au lieu d'apprendre. Exige un modèle — c'est le
    contrat qui refuse, pas l'écran. Longueur courte par défaut, dans l'unité de la fenêtre
    (`stimulus/registry.py`, `COMPTES`).
    🔴 **L'ErrP a besoin de son étiquette pour NOTER, et elle ne doit JAMAIS atteindre le
    DÉCODEUR** : le socle la retire du marqueur avant la sous-classe et ne la rend qu'au correcteur,
    le décodeur ne reçoit qu'une vue du tampon EEG. Une fuite = score parfait et faux, en silence.
    Tenu par `errp_test.py` (décodeur espion), pas par la relecture.
  - **Un résultat se lit en trois lignes** : `niveau` (bon/moyen/faible → vert/orange/rouge), `mot`,
    `chiffres` (toujours avec le hasard ou le repère), une `reserve` ; le reste est replié sous
    « Détails ». ⚠️ **Le niveau est décidé par le MOTEUR** (`core/modes/affichage.py`), par la
    même table que la phrase de verdict : une couleur déduite côté écran serait une seconde table
    de seuils, qui peindrait un jour en vert ce que le moteur juge faible.
  - ⚠️ **Une seule activité minutée à la fois** : `server.submit` refuse une calibration pendant une
    mesure **et** l'inverse. Il n'y a qu'un casque, et deux protocoles se voleraient leurs fenêtres.
  - 🔴 **Un « Tester » DÉCIDE PAR LE RUNTIME DE SON MODE**, il ne réécrit pas sa règle. Le test
    SSVEP était le dernier à le faire, jusqu'au 2026-09-22 : il prenait le σ du rejet d'artefact
    sur les **8** voies là où `modes/ssvep.py` le prend sur les **4 occipitales filtrées**. Un
    clignement frontal fort faisait rejeter au test un essai que le mode décode (taux
    sous-estimé) ; un artefact de nuque, dilué dans 8 voies, passait au test et pas au mode
    (sur-estimé). Il passe désormais par `SsvepRuntime._rest_step` / `._run_step`.
    ⚠️ **Le prix est assumé et il est dans le texte d'honnêteté** : les repères 100 %/44 % du
    2026-07-27 ont été mesurés sous l'ANCIENNE règle, donc les chiffres de ce test ne s'y
    comparent plus tels quels. La spec du chantier (§4, §9) tranche ainsi : un test décide comme
    le produit, la comparabilité est une NOTE, pas une contrainte de protocole.
- **`Calib.kind` dit QUI mène la ligne du temps, plus OÙ la calibration vit.** Deux valeurs, et le
  contrat refuse tout autre mot (l'ancien vocabulaire « console » / « natif » lève) :
  - `"moteur"` — le moteur mène : il tire les classes, affiche les consignes, décompte. C'est le
    **Motor Imagery**, endogène, sans stimulus à montrer à la frame près.
  - `"fenetre"` — une fenêtre de `src/stimulus/` mène, et le moteur est **PASSIF** : il attend
    qu'elle s'annonce (`calib_start`), encaisse ses marqueurs, découpe ses époques **par le chemin
    du décodage**, et entraîne quand elle annonce la fin (`calib_end`). C'est le P300, l'ErrP et le
    c-VEP ; `Calib.stimulus_id` dit laquelle. ⚠️ `stimulus_id` est une **CLÉ**, jamais un chemin :
    `core` ne nomme aucune fenêtre, la résolution clé → commande vit dans `src/stimulus/registry.py`
    et c'est la console qui fait le pont.
- **Le contrat PUBLIC des marqueurs a gagné trois événements** (`docs/markers.md`, en anglais) :
  `calib_start` (la fenêtre s'annonce, avec le nombre d'ÉPOQUES qu'elle promet), `cue` (la
  vérité-terrain de la manche), `calib_end` (la séance est finie → le moteur entraîne). ⚠️ **L'ErrP
  n'utilise PAS `cue`** : son étiquette voyage sur son `feedback`, qui gagne `error: true|false`
  **en calibration et en test seulement** (`--calibrer`, `--tester`) — en décodage le marqueur
  reste nu, parce que c'est une BCI **passive** et que lui donner la réponse rendrait faux tout ce
  qu'on mesure sur ce mode ; en test, le moteur la retire avant le décodeur (cf. les mesures). Le c-VEP,
  lui, ajoute `block_end` (le `round_end` du P300, transposé) et **continue de publier `cycle`**.
  **Conséquence à retenir : toute application capable d'afficher le stimulus peut désormais
  entraîner un modèle.** La calibration n'est plus verrouillée à notre pygame.
- ⚠️ **`data/` n'est écrit qu'à UN seul endroit** : la commande `save_calibration`, envoyée par la
  console quand on clique « Enregistrer le modèle ». Une calibration écrit d'abord dans un dossier
  candidat ; on voit son chiffre, puis on garde ou on jette (« Refaire »). Avant, une calibration
  sauvegardait PUIS annonçait sa précision — et comme le moteur propose le modèle chargeable le plus
  récent, une calibration ratée devenait le défaut **en silence**.
- ⚠️ **Un mode qui lit des marqueurs (P300, ErrP, c-VEP) ne tourne jamais en même temps que SA
  calibration, ni que SON TEST** (le test : depuis le 2026-09-22), et `server.submit` le refuse
  **dans les deux sens**, à la soumission comme dans la boucle. Ils liraient la même file de
  marqueurs sous le même `mode_id`
  (`EngineServer.markers_murs` tient un curseur par mode), donc chacun n'en verrait qu'une partie au
  hasard du tour de boucle : des décodages muets ou un score plausible et faux, sans la moindre
  erreur. La console, elle, arrête le mode avant TOUT entraînement et TOUT test — règle uniforme,
  SSVEP compris, pour ne pas recopier côté interface la table des conflits que le moteur possède.
- ⚠️ **Le c-VEP est le seul mode dont les marqueurs ne délimitent RIEN.** Ceux du P300 et de l'ErrP
  disent « un événement a eu lieu, découpe autour » ; celui du c-VEP dit « à cet instant, le code
  affiché était à sa frame 0 » — c'est une **HORLOGE**, et le mode décode en continu sur une fenêtre
  glissante comme le SSVEP. Sans elle il ne décode pas mal : il ne décode **rien**. Sa calibration
  continue donc de publier `cycle` : sans l'horloge, pas de phase, donc pas d'époque étiquetable.
- L'**application pygame `src/research/app.py` est SUPPRIMÉE** (2026-09-08). Ses six écrans — trois
  de PILOTAGE (SSVEP, sélection P300, démonstrateur ErrP) et trois de CALIBRATION (c-VEP, P300,
  ErrP) — sont **archivés**, pas supprimés, dans [`archive/`](archive/README.md), avec leur
  `--smoke`. Ils y restent parce qu'ils décodent **en LOCAL** : c'est ce qui, en séance, sépare
  « le décodage réseau est moins bon » de « la séance est moins bonne ». `archive/cvep_pilot.py`
  est le plus utile — même modèle, même vote 2-sur-3 (recette 2.9). L'histogramme neuro n'a pas été
  archivé : son calcul EST `core.neuro_monitor.NeuroDecoder`, l'objet même dont le moteur publie la
  sortie, et la console a repris ses textes.
  **Trois retraits de plus le 2026-09-09** : `archive/alpha_check.py` (le contrôle alpha, devenu une
  page), `archive/live_ssvep.py` (un **septième** écran de pilotage, que le tri du 2026-09-08 avait
  oublié) et `archive/ui.py` — la machinerie pygame partagée (`App`, `Abort`, `signal_check`), que
  **huit** des écrans archivés importent et que plus rien de vivant n'utilisait. `archive/` compte
  donc **13 fichiers et 12 `--smoke`** : `ui.py` n'a rien à lancer, il est couvert par les huit qui
  l'importent.
- ⚠️ **Un seul de ces trois programmes à la fois** — console, moteur, écran archivé. Le casque
  n'accepte qu'une connexion, et les noms de flux sont un contrat public : deux instances publient
  sous le même nom, donc un programme oublié répond à la place de celui qu'on teste.
  **Les quatre fenêtres de `src/stimulus/` sont l'exception** : elles n'ouvrent PAS le casque, elles
  dessinent et publient des marqueurs — c'est exactement pour ça qu'elles se lancent à côté du
  moteur, dans un second terminal, **ou que la console les lance elle-même** quand on entraîne ou
  qu'on teste.
- Public visé = **des étudiants qui vont lire et modifier ce code**. Écrire en conséquence.

## Matériel

Casque **Unicorn Hybrid Black** : 8 voies EEG sèches, 250 Hz, Bluetooth. Montage fixe
`[Fz, C3, Cz, C4, Pz, PO7, Oz, PO8]` (indices 0-7). PC de dev sous **Windows** (PowerShell).

## Façon de travailler (préférences de l'utilisateur)

- Répondre en **français** ; README, doc et messages de commit **en anglais** pour GitHub. Deux
  exceptions assumées, parce qu'elles ne s'adressent pas à GitHub : `docs/SPEC.md` (document de
  travail interne), `docs/qa.md` et `docs/recette.md` (procédures exécutées ici) restent en
  français. **`docs/qa.md` est la feuille qu'on EXÉCUTE** — action, résultat attendu, ce qui compte
  pour un échec ; `docs/recette.md` porte le pourquoi, l'histoire des défauts et les repères
  chiffrés, et c'est ce qu'on relit quand un point tombe.
- Avancer par **petits pas testés sur le matériel** : éditer → lancer → coller les logs.
- **Vérifier la doc** (SDK Unicorn, LSL, littérature BCI) avant d'affirmer ; citer les sources sur les
  points incertains.
- Recommander **une option claire** plutôt qu'un catalogue ; privilégier la simplicité.
- **Rigueur statistique** : ne jamais conclure sur du bruit. Sur de petits échantillons EEG, valider
  une hypothèse par un test (permutation, validation croisée honnête) avant d'y croire.

## Commandes utiles

**Le parcours normal n'en contient qu'une** — le reste de cette section est pour développer,
déboguer ou monter une séance à plusieurs terminaux.

```bash
outils\Console EEG.bat                     # LE point d'entrée : double-clic depuis l'explorateur,
                                           # pas de terminal. Les arguments sont transmis tels
                                           # quels ; il PAUSE si la console meurt au démarrage
python src/console/app.py                  # la même chose en ligne de commande
python src/console/app.py --synthetic      # RACCOURCI DE DÉVELOPPEUR : saute l'écran de départ et
                                           # ouvre directement le board de test. Le chemin normal
                                           # est de lancer sans drapeau et de CHOISIR la source
python src/console/app.py --mode ssvep     # + décodage SSVEP démarré au lancement
```

**Elle commence par demander sur quoi ouvrir la session** (2026-09-09) : casque Unicorn ou board de
test BrainFlow. ⚠️ **Aucun repli automatique** — basculer en douce ferait enregistrer une séance
entière de signal fabriqué en croyant tenir du vrai. Le bandeau répète la source tant que la
console tourne.

⚠️ **Ce que la console fait vraiment quand le casque refuse de s'ouvrir, depuis le 2026-09-10** :
elle le **DIT**, à l'écran. Elle ne **repropose pas** le choix — cette phrase-ci l'a affirmé, et
`docs/recette.md` §1.17 aussi, alors que ce n'était implémenté nulle part. La revue de branche l'a
trouvé. Reproposer exigerait de sortir le cycle de vie du fil du moteur de `run()` : c'est un
chantier, pas un correctif, et **une promesse écrite non tenue coûte plus qu'une absence** —
l'étudiant attend un écran qui ne viendra jamais.

Dans la console (depuis le 2026-09-22) :

- **La grille** : **sept tuiles** (les six modes plus le brut), chacune avec « publié »,
  **« Démarrer »** — le seul bouton qui démarre le décodage continu, hormis l'« Observer » du
  Neuro — et « Ouvrir » ; dessous, **une seule** tuile de séance, **« Vérifier le casque »**
  (marquée *BARRIÈRE*).
- **Une page par mode, en blocs numérotés** (règle 🔴 plus haut). La vue en direct des modes
  testables y est repliée sous **« Décodage en direct »**. **Ont quitté la page, et reviendront
  avec « Connecter »** : « Démarrer/Arrêter », « Lancer le stimulus », « Journal de séance »,
  « Brancher un client ».
- **« Entraîner »** et **« Tester »** ouvrent chacun une page (briefing, réglages, « Commencer »,
  « ← » qui ramène au mode). « Commencer » passe par un **contrôle de liaison** (σ par voie) qui
  **REFUSE** dès qu'une seule des huit voies sort de [0,5 ; 500] µV. Un entraînement fini attend
  « Enregistrer le modèle » ou « Refaire » : **rien n'atteint `data/` avant ce clic**. Un test
  n'écrit jamais rien.
- **« Ce que voit ton application »**, en bas de la grille : les flux LSL du réseau, leurs voies et
  leurs valeurs qui défilent. ⚠️ Elle lit **par LSL, comme un client** — jamais l'état interne du
  moteur : un panneau branché sur `snapshot()` défilerait joliment pendant que le réseau est muet,
  c'est-à-dire exactement la panne qu'on vient regarder. Un bouton **« Enregistrer les verdicts »**
  y écrit un JSONL dans `seances/` (`moteur_<flux>_AAAAMMJJ-HHMMSS.jsonl`), **une ligne par décision
  PUBLIÉE** — c'est le MOTEUR qui écrit, sur commande ; la console ne touche jamais au disque.
  ⚠️ `seances/` est gitignoré et **hors de `data/`** : un verdict de séance n'est ni un modèle ni un
  enregistrement EEG, et `data/` garde son autorité d'écriture unique.

Le moteur seul, sans écran — le produit, et le montage à deux terminaux :

```bash
python src/core/server.py --mode ssvep --refresh 60   # décode et publie, headless
python src/core/server.py --mode ssvep,neuro   # deux modes en même temps (repos partagé)
python src/core/server.py --mode mi        # le Motor Imagery sur le réseau (EXIGE un modèle entraîné)
python src/core/server.py --mode p300      # le P300 sur le réseau (EXIGE un modèle ET des marqueurs entrants)
python src/stimulus/p300.py                # la fenêtre P300 — n'ouvre PAS le casque, donc se lance
                                           # EN MÊME TEMPS que le moteur (2 terminaux)
python src/core/server.py --mode errp      # l'ErrP sur le réseau (EXIGE un modèle ET des marqueurs)
python src/stimulus/errp.py                # la fenêtre ErrP — n'ouvre PAS le casque non plus,
                                           # même montage à 2 terminaux que le P300
python src/core/server.py --mode cvep      # le c-VEP sur le réseau (EXIGE un modèle ET une HORLOGE)
python src/stimulus/cvep.py                # la fenêtre c-VEP : fait clignoter ET publie un marqueur
                                           # de CYCLE (~1/s). N'ouvre PAS le casque -> 2 terminaux.
                                           # --seed rejoue les consignes, --windowed pour le dev
python src/stimulus/cvep.py --log         # ⚠️ EN SÉANCE : la vérité-terrain dans un FICHIER
                                           # (une ligne par consigne, horodatée en local_clock() ;
                                           # sans valeur = nom horodaté dans seances/). Sans elle
                                           # la séance ne se dépouille pas. ⚠️ Depuis le
                                           # 2026-09-22 la console ne le passe PLUS (la case
                                           # « Journal de séance » est partie) : à taper, jusqu'à
                                           # « Connecter » (recette 2.9)
python src/stimulus/ssvep.py               # la fenêtre SSVEP : une flèche par fréquence de --freqs
                                           # (sans lui, le trio du dépôt). --guide y ajoute les
                                           # consignes et la vérité-terrain : c'est ce que lance
                                           # « Tester » sur la page SSVEP, avec les --freqs du mode
python archive/cvep_pilot.py --model data/cvep_model_….npz   # l'écran archivé : décodage LOCAL, la
                                           # RÉFÉRENCE à comparer au réseau en séance (recette 2.9).
                                           # ⚠️ --model explicite : son défaut pointe l'ancien nom fixe
```

⚠️ **Les entraînements et les tests sont des BOUTONS, pas des commandes.** « Commencer » sur la page
« Entraîner » (ou « Tester ») soumet la séance au moteur, **puis** — pour le P300, l'ErrP et le
c-VEP, et le test SSVEP — lance la fenêtre de `src/stimulus/` avec `--calibrer` (ou `--tester` /
`--guide`), seulement quand la séance apparaît dans `snapshot()`. Cet ordre est un contrat testé : la
fenêtre attend le moteur, le moteur compte ses 15 s de chauffe depuis la commande, et il n'existe
**aucune poignée de main** entre les deux processus (cf. « Ce qui n'a jamais été vérifié »). Les
fenêtres restent lançables à la main pour déboguer — `--tester` joue le même protocole que
`--calibrer` et ne change que la formulation (« TEST », « le moteur note ») :

```bash
python src/stimulus/p300.py --calibrer     # 12 manches (P300_CAL_ROUNDS) ; --rounds N
python src/stimulus/errp.py --calibrer     # 200 essais (ERRP_CAL_TRIALS) ; --essais N
python src/stimulus/cvep.py --calibrer     # blocs entrelacés, ~2,8 min (la console annonce
                                           # ~3,1 min : elle compte les 15 s de chauffe du moteur) ;
                                           # --cycles N = cycles enregistrés PAR CIBLE
```

**Après toute modification**, les deux tests headless qui couvrent le plus de code (aucun casque) :

```bash
python src/core/server.py --smoke          # moteur : registre, FRONTIÈRE (les QUATRE paquets :
                                           # core + stimulus + research + console), EXEMPLES,
                                           # repos partagé, cumul, flux, vol de marqueurs,
                                           # save/discard, ENREGISTREMENT de séance
python src/console/app.py --smoke          # console : grille, page de mode, réglages, contrôle de
                                           # liaison, lanceur de fenêtre, ORDRE, écran de départ,
                                           # page des mesures, page de flux, TRACÉS du brut
                                           # (Qt offscreen)
```

⚠️ **`examples/` n'était couvert par AUCUN test avant le 2026-09-10** — alors que c'est le seul
endroit du dépôt qui montre comment CONSOMMER le produit. `[smoke-exemples]` compare désormais les
noms de flux cités dans `examples/**` à ceux que le registre produit vraiment. La panne qu'il
attrape ne lève rien toute seule : `resolve_byprop` sur un flux renommé attend, rend une liste
vide, et l'étudiant conclut que le moteur ne publie pas. **Les deux `.cs` d'`examples/unity/` n'ont
toujours jamais été compilés** : il n'y a pas d'Unity ici, et aucun test ne peut le remplacer.

⚠️ Il n'y a plus de troisième smoke : `src/research/app.py --smoke` couvrait l'appli pygame, qui
n'existe plus. Les **douze** écrans archivés gardent chacun le leur — la liste est dans
[`archive/README.md`](archive/README.md), ils ne sont **pas** couverts par les deux ci-dessus.

Et les quatre gardes des **mesures** et de la fenêtre SSVEP, livrées le 2026-09-09, qu'aucun des
deux smokes ci-dessus n'exécute :

```bash
python src/core/modes/mesure.py            # le SOCLE : la ligne du temps, et le refus d'une SECONDE
                                           # activité minutée — dans les DEUX sens, et à la
                                           # soumission comme dans la boucle
python src/core/modes/alpha.py             # le contrôle alpha : le détrend (sans lui, l'offset DC
                                           # de 10⁵ µV fait tomber le ratio de 4,44 à 2,26 et TOUTE
                                           # séance échoue), et le refus des voies PLATES
python src/core/modes/ssvep_mesure.py      # ⚠️ LE test de ce sous-système : UN ESSAI = UNE DÉCISION
python src/stimulus/ssvep.py --smoke       # la fenêtre guidée : la cible lue dans les PIXELS,
                                           # horodatage APRÈS le flip, essais ENTRELACÉS
```

⚠️ **`modes/ssvep_mesure.py` porte le test qui protège la mesure**, et il est de la même famille que
ceux de `modes/p300.py` et `stimulus/cvep.py` : compter les fenêtres glissantes au lieu des essais
est **l'amélioration plausible** (« plus de données, intervalle plus serré ») et elle est fausse.
Mesuré : n = 24 devient **168** et l'intervalle s'effondre de 0,19 à **0,03** de large. La mutation
ne fait rougir **que** ce fichier — ni les deux smokes, ni `research/ssvep_guided.py`.

Et les six gardes du chantier **« Configurer · Entraîner · Tester »** (2026-09-22), qu'aucun des
deux smokes n'exécute :

```bash
python src/core/modes/affichage.py         # les trois lignes d'un résultat : le NIVEAU vient de la
                                           # table du verdict, jamais d'une seconde table d'écran
python src/core/modes/mesure_marqueurs.py  # le SOCLE des tests à fenêtre : épochage par le chemin du
                                           # décodage, garde de silence, CLOISON de la vérité
python src/core/modes/mi_test.py           # Tester le MI : la DERNIÈRE sortie, -1 jamais REPOS
python src/core/modes/p300_test.py         # Tester le P300 : une MANCHE = un essai, hasard 1/6
python src/core/modes/cvep_test.py         # Tester le c-VEP : un BLOC = une décision, phase APPELÉE
python src/core/modes/errp_test.py         # 🔴 Tester l'ErrP : l'étiquette au correcteur, JAMAIS au
                                           # décodeur (décodeur espion)
```

⚠️ Même famille de panne que `ssvep_mesure.py`, pour chacun : compter les fenêtres, écrire le hasard
en dur ou réécrire la décision du mode donnent un score plausible et faux sans rien casser. Ces
mutations ont été vues rougir dans leur fichier ; les deux smokes ne les exécutent pas.

Et le sous-système des **marqueurs entrants**, livré le 2026-08-17 et étendu aux calibrations le
2026-09-07, qu'aucun smoke ci-dessus ne couvre entièrement :

```bash
python src/core/markers.py                 # l'oreille du moteur : résolution PAR NOM, time_correction
python src/core/modes/marker_calib.py      # ⚠️ le SOCLE des trois calibrations à fenêtre : l'accord
                                           # des DEUX épochages, les trois causes d'abandon
python src/stimulus/registry.py            # clé -> commande, et la correspondance avec le contrat
                                           # vérifiée DANS LES DEUX SENS
python src/core/p300_models.py             # les modèles P300 : refus des hérités, tri par date
python src/core/modes/p300.py              # le mode : ALIGNEMENT des époques, abandon de manche, appariement score↔cible
python src/core/modes/p300_calib.py        # la calibration P300 : cue -> étiquette, flash -> époque
python src/core/errp_models.py             # les modèles ErrP : refus des hérités ET des calibrations dégénérées
python src/core/modes/errp.py              # le mode ErrP : ALIGNEMENT, rejet d'artefact, MONOTONIE du réglage
python src/core/modes/errp_calib.py        # la calibration ErrP : l'étiquette voyage sur le feedback
python src/core/errp_track.py              # la piste ErrP : UNE seule écriture du protocole, partagée
                                           # par la fenêtre et l'écran archivé
python src/stimulus/errp.py --smoke        # la fenêtre ErrP : piste, erreurs délibérées, horodatage au
                                           # flip, et la garde de vérité-terrain DANS LES DEUX SENS
python src/stimulus/p300.py --smoke        # la séquence de flashs : chaque cible vue `reps` fois,
                                           # et la séance de calibration bout à bout
```

⚠️ **`modes/marker_calib.py` porte l'invariant central des trois calibrations à fenêtre** :
`pre_s`/`post_s` ne sont **pas** redéclarés, ils sont LUS sur la classe du runtime de DÉCODAGE, et
l'époque est prélevée par le MÊME appel (`core.p300_decoder.epoch_from_stream`). Son test compare
les deux chemins époque par époque, sur **deux géométries** — une seule ne suffit pas : à la
géométrie du P300, `int(round(0,15 × 250))` absorbe un décalage d'un échantillon (l'arrondi bancaire
rend `round(37,5) == round(38,5) == 38`), et le test serait infalsifiable.

⚠️ **`modes/p300.py` porte LE test qui protège tout ce sous-système** : un décalage de quelques
échantillons à l'épochage rend tous les autres tests verts et fait décoder du bruit avec une
confiance de 0,92 — indiscernable d'un succès. Mesuré : la mutation déplace le pic de −38
échantillons (−152 ms) et les 46 autres assertions restent vertes.

Et les cinq gardes du Motor Imagery, qu'**aucun des deux smokes ci-dessus n'exécute** :

```bash
python src/core/acquisition.py --synthetic # fenêtre MI NON filtrée (double filtrage = bruit à p=0,99)
python src/core/modes/mi.py                # seuil, longueur du vote, appariement p_<classe> ↔ classe
python src/core/mi_models.py               # refus des modèles hérités, tri du plus récent au plus ancien
python src/core/modes/calibration.py       # la ligne du temps d'une calibration : chauffe, essais, entraînement, abandon
python src/core/modes/mi_calib.py          # calibration MI : accuracy HONNÊTE (CV par essai), jamais d'écrasement
```

Le non-filtrage de la fenêtre MI est l'invariant central du sous-système et il n'est vérifié que
par le premier : un double filtrage réintroduit demain passerait les deux smokes sans un mot.
`modes/calibration.py` est le PARENT de `modes/marker_calib.py` : c'est de lui que vient la forme de
`snapshot()["calibration"]`, celle que `console/calib_page.py` lit sans jamais la tester — un champ
qui manquerait ne lèverait rien, la page resterait simplement vide.

Et les sept gardes du **c-VEP**, livré le 2026-08-21, qu'aucun des deux smokes n'exécute :

```bash
python src/core/cvep_code.py               # la m-séquence : équilibre, autocorrélation, lags distincts,
                                           # et les blocs ENTRELACÉS que les deux écrans partagent
python src/core/cvep_decoder.py            # l'eCCA : justesse vs SNR, aller-retour du modèle
python src/core/cvep_rcca.py               # le rCCA : le 2e décodeur, sur le MÊME stimulus décalé
python src/core/cvep_models.py             # les modèles : refus des hérités, QUEL décodeur, tri par date
python src/core/modes/cvep.py              # le mode : la PHASE, les 4 causes de -1, le vote glissant
python src/core/modes/cvep_calib.py        # la calibration : la phase APPELÉE et non recopiée, McNemar
python src/stimulus/cvep.py --smoke        # la fenêtre : la phase lue dans les PIXELS, frame par frame
```

⚠️ **`src/stimulus/cvep.py --smoke` porte LE test qui protège ce sous-système**, et il est de la
même famille que celui de `modes/p300.py` : il rejoue une course de rendu image par image et compare
la phase que le moteur reconstruirait à celle réellement AFFICHÉE, lue dans les pixels de l'écran —
pas dans le compteur de l'émetteur, qui ne peut que se donner raison. L'assertion exige **zéro**
frame d'écart tant qu'aucune image n'est sautée : une tolérance à ±1 laisserait passer un décalage
systématique d'une frame, c'est-à-dire la panne. Remonter le `push_sample` au-dessus du
`display.flip()` la fait rougir — et ne fait rougir qu'elle. Sa section `[C7]` étend la même
exigence à la CALIBRATION, marqueurs de protocole compris : chaque `cue` porte la cible
**réellement cerclée**, lue elle aussi dans les pixels.

⚠️ **`modes/cvep_calib.py` tient le même invariant sur l'autre axe** : la calibration ne recopie pas
le calcul de phase, elle **APPELLE** `CVEPRuntime.phase_a` avec elle-même pour `self`. Une assertion
`ast` interdit toute arithmétique modulaire dans la classe — une réimplémentation à l'identique
passerait la comparaison de valeurs par construction, et c'est la dérive future qu'on interdit, pas
l'écart du jour.

⚠️ **La panne caractéristique du c-VEP ne casse rien** : une phase fausse de quelques frames ne lève
aucune exception, les corrélations baissent juste assez pour que rien ne se déclenche, et c'est
indiscernable d'un étudiant qui fixe mal. Deux gestes la produisent, à une ligne l'un de l'autre :
horodater AVANT le flip, ou annoncer un `refresh` que l'écran ne tient pas.

⚠️ **Ne laisser tourner AUCUN moteur pendant un test.** Les noms de flux sont un contrat public,
donc identiques pour toutes les instances : un serveur oublié répond à la place de celui qu'on teste
(les smokes filtrent sur le `source_id`, mais la confusion reste facile).

## Ce qui n'a jamais été vérifié

À lire avant de croire qu'un test vert veut dire « ça marche ». **La console n'a vu un casque que
deux fois, et en partie** (2026-09-21 et 22 : contrôle alpha, taux SSVEP, UN entraînement c-VEP à
25,0 % pour un hasard à 17 %). Les autotests prouvent le câblage entre deux processus, sur un board
synthétique ; ils ne peuvent rien dire de l'ergonomie ni du décodage.

- **QUATRE des six modes n'ont jamais été décodés au casque À TRAVERS LE MOTEUR** — MI, P300, ErrP,
  c-VEP. Seul le SSVEP l'a été. Le sixième, le **neuro**, est un cas à part et il ne faut pas le
  perdre dans l'arithmétique : sa plomberie est testée, mais **son contenu n'a jamais été validé,
  nulle part** — ni au casque, ni ailleurs (cf. test 2.5). Le moteur joue maintenant leurs quatre calibrations et la console
  les lance et les juge ; **ça n'ajoute aucune mesure**, ça rend seulement les tests 2.6 à 2.9 de
  `docs/recette.md` exécutables sans l'appli pygame. Une seule séance casque les couvre, et c'est le
  travail qui reste.
- **Le chantier « plus une seule commande à taper » (2026-09-09) n'a rien mesuré non plus.** Il
  déplace des gestes : le contrôle alpha et le taux d'émission SSVEP sont désormais des pages du
  moteur, la source se choisit à l'ouverture, le flux sortant se regarde et s'enregistre. **Aucun
  repère chiffré du projet n'a bougé, et aucun n'a été produit** — ni le 100 %/44 % du SSVEP, ni le
  46 %/71 % du c-VEP, ni l'AUC 0,776 de l'ErrP, ni le 0,71 du P300, ni les ~40 % à trois classes du
  MI. Les deux mesures nouvelles, écrites sur du bruit blanc et des sinusoïdes posées à la main,
  n'ont été jouées au casque que sur UNE personne : **le repère « ratio alpha > ~1,5 » vient
  toujours d'UNE personne, sur ce casque**, et la seconde cause d'échec du contrôle alpha (« ça
  monte, mais ce n'est pas de l'alpha ») n'a jamais été vue sur un vrai signal.
- **Le chantier « Configurer · Entraîner · Tester » (2026-09-22) n'a rien mesuré non plus**, et il
  ne change aucun chiffre du décodage. **Aucun des cinq « Tester » n'a vu un casque** (ils sont nés
  après la séance). Leurs seuils de couleur sont argumentés sur UNE séance de référence chacun ; au
  c-VEP, un système exactement au repère ne sort vert qu'environ une fois sur quatre à 18 blocs
  (calcul binomial, pas une mesure) ; le repos de référence du test ErrP (estimé 2-5 s) n'a jamais
  été mesuré et n'est affiché nulle part.
- 🟠 **Des constats de la revue du 2026-09-08 restent parqués.** La console prenait `accepted` pour
  « la séance a démarré » : corrigé pour l'enregistrement de séance et pour le lancement des
  fenêtres (elles attendent de VOIR la séance dans `snapshot()`, 2026-09-10), **pas audité
  ailleurs**. Les refus lancés depuis la GRILLE, eux, s'affichent dans le bandeau depuis
  `c960e39` (2026-09-10). Les refus et les aides du moteur qui nommaient encore un bouton
  « Calibrer » disent « Entraîner » depuis le 2026-09-23, et leurs assertions avec eux.
- 🔴 **Le contrôle de liaison peut BLOQUER une séance légitime.** Il refuse dès qu'**une seule** des
  huit voies sort de [0,5 ; 500] µV — pas seulement les voies clés du mode, qui sont surlignées mais
  ne restreignent pas le refus — et il n'offre **aucune porte de sortie**, là où
  `archive/ui.py:signal_check` laissait passer sur n'importe quelle touche (« à toi de juger »).
  C'est délibéré (un contournement à un clic est un contournement qu'on prend par réflexe), mais si
  une électrode refuse de descendre sous le seuil, la console devient inutilisable. **À trancher
  devant un casque, pas avant.** Vérifié en revanche que `--synthetic` passe : σ mesurés de 7 à
  73 µV, huit verdicts « ok », aucun refus.
- 🔴 **L'ordre de lancement fenêtre/moteur n'a AUCUNE poignée de main.** La console soumet
  `start_calibration` (ou `start_mesure`) **puis** lance la fenêtre — l'ordre est figé par un test (journal partagé,
  la mutation qui l'inverse fait rougir deux assertions) — et c'est l'initialisation de pygame plus
  l'attente de la fenêtre qui couvrent les 15 s de chauffe du moteur. **Ça tient, ce n'est pas
  garanti** : les deux processus comptent sur deux horloges différentes. Si la fenêtre prend de
  l'avance, ses premières manches tombent dans la chauffe — jetées, comptées, dites, mais la séance
  est plus courte que ce que les deux écrans annoncent.
- ⚠️ **Le compteur `marqueurs_chauffe` est TROMPEUR pour le c-VEP** : sa fenêtre continue de
  clignoter pendant la chauffe (exprès — une horloge n'a pas besoin d'être bonne pour être à
  l'heure), le socle compte ces ~14 marqueurs comme « époques jetées » et conseille à la fenêtre
  d'attendre. Elle attend déjà. Message faux, sans danger.
- ⚠️ **`--cycles` rend fausse la durée annoncée de l'entraînement c-VEP.** Sa calibration n'expose
  aucun `Param` : `duree_protocole_s` vaut pour les défauts, et une fenêtre lancée à la main avec
  `--cycles 6` sera plus courte que ce que la console annonce. Le moteur ne peut pas le savoir —
  ce n'est pas lui qui mène le protocole. (Le TEST c-VEP, lui, a sa longueur en `Param` et la passe
  à la fenêtre dans son unité : des cycles enregistrés PAR CIBLE.)
- ⚠️ **Les pages d'entraînement n'ont vu un casque qu'une fois (c-VEP), les pages de test
  jamais.** Quatre questions n'ont de réponse qu'en séance : est-ce que les ~15 s couvrent vraiment
  l'écart de lancement *sur cette machine* ; est-ce qu'un étudiant comprend qu'un chiffre affiché
  n'est pas encore un modèle enregistré ; est-ce que le contrôle de liaison est lu ou cliqué au
  travers ; et est-ce que la boucle Régler → Tester → ajuster se comprend sans explication.

## Pièges matériels à connaître

- **Ne pas fermer/rouvrir la console (ou le moteur)** en cours de séance : les voies C3/Cz saturent
  à la réouverture (redémarrage de l'amplificateur). Garder une seule session ouverte — c'est
  exactement ce que le point d'entrée unique rend possible : entraîner et tester sans jamais fermer
  la fenêtre qui tient le casque.
- **Saliner les électrodes** est le principal levier de qualité du signal (gain mesuré très net).
- Vérifier le contact **avant** d'enregistrer : une électrode ou une référence décollée produit une
  séance entière inexploitable, sans autre signal d'alerte que l'écran de contrôle de liaison.
