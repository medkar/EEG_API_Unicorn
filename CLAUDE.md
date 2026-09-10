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
  le **2026-09-09 il n'y a plus une seule commande d'usage réel à taper**. Tout le parcours d'un
  étudiant — choisir la source, contrôler l'alpha et le contact, mesurer, calibrer, choisir un
  modèle, afficher un stimulus, décoder, **regarder le flux sortant, enregistrer la séance** — s'y
  fait aux boutons, dans une seule fenêtre qu'on n'a plus à fermer.
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
  le moteur tourne sans écran. **Les INTERDITS sont vérifiés par un test**, pas par la
  discipline : `server.py --smoke` (`[smoke-frontiere]`) parse en AST tout `src/core/**/*.py`,
  tout `src/stimulus/**/*.py` et tout `src/research/**/*.py`, et échoue sur le moindre import
  interdit.
- 🔴 **TOUT L'USAGE RÉEL SE PILOTE DEPUIS L'INTERFACE. Un utilisateur ne tape aucune commande.**
  C'est une contrainte de conception permanente, du même rang que la frontière ci-dessus — pas une
  fonctionnalité qu'on ajoute quand on y pense. **Une capacité livrée sans chemin graphique est une
  tâche INCOMPLÈTE**, pas une tâche à finir plus tard.

  L'« usage réel », c'est **l'acquisition, le décodage, et le flux récupérable à l'extérieur** par
  l'application qu'écrira l'utilisateur. En sont DEHORS, et ce n'est pas une échappatoire : les
  autotests (`--smoke`, autotests de module), qui s'adressent au développeur ; et
  `server.py --mode X`, le moteur **sans écran**, dont c'est justement le contrat public.

  **Vérifié par le même test** : rien dans `src/research/` n'importe `core.acquisition`,
  `brainflow` ni `pygame`. Le banc d'essai peut tout CALCULER sur des fichiers archivés — c'est son
  métier — mais ouvrir le casque ou afficher un stimulus sont des gestes d'usage réel, donc ils
  appartiennent à l'application. **Vert depuis le 2026-09-09** : `[smoke-frontiere] 0 violation(s)
  de frontière`. (Le NOMBRE de fichiers n'est pas cité : un compte en prose n'est tenu par rien,
  et celui-ci était déjà faux deux commits plus tard — 57 contre 58.) Il était ROUGE en le posant, sur six fichiers — c'est ce
  rouge-là qui a servi de liste de travail au chantier « plus une seule commande à taper ».

  ⚠️ **Cette règle a été demandée CINQ FOIS entre juillet et septembre 2026 avant d'être écrite
  ici.** Chaque fois elle a été traitée comme une fonctionnalité — on ajoutait un bouton — et le
  chantier suivant repartait sans elle, donc un nouveau trou apparaissait. C'est pour ça qu'elle
  est dans ce fichier ET dans un test : une contrainte tenue par la discipline n'est pas tenue.
- **La console est un CLIENT du moteur**, pas le moteur : elle crée un `EngineServer`, lance sa
  boucle dans un fil et sonde `snapshot()`. Le fil Qt ne touche jamais la session BrainFlow — toute
  action passe par la file de commandes. Et aucune logique n'y vit que le moteur ne possède déjà :
  pas de validation côté interface, pas de catalogue de modes recopié.
- **Le moteur publie les SIX modes** depuis le 2026-08-21 (SSVEP, neuro, Motor Imagery, P300, ErrP,
  c-VEP) **et joue les QUATRE calibrations** depuis le 2026-09-08. ⚠️ **Publié ≠ validé** : seul le
  SSVEP a été décodé sur un vrai cerveau À TRAVERS le moteur. Les quatre modes à modèle (MI, P300,
  ErrP, c-VEP) attendent une séance casque — c'est la recette, tests 2.6 à 2.9. **Le chantier de la
  console n'y a rien changé** : il déplace le geste de calibration, il ne décode aucun cerveau. Ses
  autotests prouvent le câblage, jamais l'ergonomie ni le décodage.
- **Le moteur joue aussi DEUX MESURES** depuis le 2026-09-09 (`core/modes/mesure.py`,
  `MesureRuntime`). Une mesure est un protocole minuté qui rend un **verdict**, pas un modèle : elle
  n'écrit **rien** sur le disque, donc elle n'a ni « Enregistrer » ni « Refaire ». Elles partagent le
  contrat public de `CalibrationRuntime`, ce qui les fait afficher par une page générique
  (`console/mesure_page.py`) et poser leurs tuiles sur une seconde rangée de la grille.
  - **`alpha` — Contrôle alpha** (37 s, `core/modes/alpha.py`). Yeux ouverts / yeux fermés, effet
    de Berger. C'est une **BARRIÈRE** (`MesureSpec.barriere`) : si l'alpha ne monte pas, aucun autre
    test de la séance ne veut rien dire, et le verdict est une phrase qui ARRÊTE. La page propose
    d'**appliquer le pic mesuré** au réglage `alpha_hz` du SSVEP — la recette le faisait noter à la
    main puis retaper dans un autre écran.
  - **`ssvep_taux` — Taux d'émission SSVEP** (3,6 min). Une fenêtre (`src/stimulus/ssvep.py
    --guide`) désigne la cible, le moteur applique **sa propre règle de décision** et rend le taux
    d'émission et la justesse à l'émission. ⚠️ **Un essai = UNE décision** : les fenêtres du moteur
    se chevauchent, les compter gonflerait l'effectif d'un facteur ~7 et rétrécirait l'intervalle
    de confiance d'autant.
  - ⚠️ **Une seule activité minutée à la fois** : `server.submit` refuse une calibration pendant une
    mesure **et** l'inverse. Il n'y a qu'un casque, et deux protocoles se voleraient leurs fenêtres.
  - 🔴 **Écart connu, DIT et non corrigé** : le σ du rejet d'artefact est pris sur les **8** voies
    dans `ssvep_mesure` et sur les **4 occipitales filtrées** dans `modes/ssvep.py`. C'est la règle
    sous laquelle les repères 100 %/44 % du 2026-07-27 ont été mesurés ; l'aligner rendrait le
    prochain chiffre incomparable au seul dont on dispose. **Décision à prendre hors chantier.**
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
  **en calibration seulement** — en décodage le marqueur reste nu, parce que c'est une BCI
  **passive** et que lui donner la réponse rendrait faux tout ce qu'on mesure sur ce mode. Le c-VEP,
  lui, ajoute `block_end` (le `round_end` du P300, transposé) et **continue de publier `cycle`**.
  **Conséquence à retenir : toute application capable d'afficher le stimulus peut désormais
  entraîner un modèle.** La calibration n'est plus verrouillée à notre pygame.
- ⚠️ **`data/` n'est écrit qu'à UN seul endroit** : la commande `save_calibration`, envoyée par la
  console quand on clique « Enregistrer le modèle ». Une calibration écrit d'abord dans un dossier
  candidat ; on voit son chiffre, puis on garde ou on jette (« Refaire »). Avant, une calibration
  sauvegardait PUIS annonçait sa précision — et comme le moteur propose le modèle chargeable le plus
  récent, une calibration ratée devenait le défaut **en silence**.
- ⚠️ **Un mode et SA propre calibration ne peuvent plus tourner ensemble**, et `server.submit` le
  refuse **dans les deux sens**. Ils liraient la même file de marqueurs sous le même `mode_id`
  (`EngineServer.markers_murs` tient un curseur par mode), donc chacun n'en verrait qu'une partie au
  hasard du tour de boucle : deux décodages muets, sans la moindre erreur. La console, elle, arrête
  le mode avant TOUTE calibration — règle uniforme, pour ne pas recopier côté interface la table des
  conflits que le moteur possède.
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
  moteur, dans un second terminal, **ou que la console les lance elle-même** quand on calibre ou
  qu'on mesure.
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
test BrainFlow. ⚠️ **Aucun repli automatique** — un casque qui refuse de s'ouvrir le fait dire et
repropose le choix ; basculer en douce ferait enregistrer une séance entière de signal fabriqué en
croyant tenir du vrai. Le bandeau répète la source tant que la console tourne.

Dans la console : une grille de **sept tuiles** (les six modes plus le brut), une page par mode
(sortie en direct · réglages · extrait de code client), et **deux boutons qui sortent de la
console** sur les modes qui en ont besoin — « Calibrer » (ouvre la page de calibration : briefing,
réglages, « Commencer ») et « Lancer le stimulus ». Les deux lancements passent par un **contrôle de
liaison** (σ par voie, voies clés du mode surlignées) qui **REFUSE** dès qu'une seule des huit voies
sort de [0,5 ; 500] µV. Une calibration finie s'affiche avec son chiffre et attend « Enregistrer le
modèle » ou « Refaire » : **rien n'atteint `data/` avant ce clic**.

Trois entrées de plus, livrées le 2026-09-09, et aucune n'a d'équivalent en ligne de commande :

- **une seconde rangée de tuiles, « Contrôles et mesures »** — « Contrôle alpha » (marquée
  *BARRIÈRE*) et « Taux d'émission SSVEP ». Même page générique que les calibrations, mais un
  verdict à la place d'un modèle et **rien d'écrit sur le disque**.
- **« Journal de séance »**, une case sur la page du mode, **cochée par défaut**, qui ajoute `--log`
  à la fenêtre lancée. Elle n'apparaît que là où le registre déclare que la fenêtre sait
  journaliser — aujourd'hui le c-VEP seul. **La fenêtre choisit elle-même son nom horodaté** dans
  `seances/` ; la console affiche où c'est et n'écrit rien.
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
python src/stimulus/cvep.py --log seance.jsonl   # ⚠️ EN SÉANCE : la vérité-terrain dans un FICHIER
                                           # (une ligne par consigne, horodatée en local_clock()).
                                           # Sans elle la séance ne se dépouille pas : le terminal
                                           # en est le seul autre exemplaire. ⚠️ Depuis le
                                           # 2026-09-09 la CASE « Journal de séance » de la console
                                           # le fait par défaut : ne le taper que pour choisir le
                                           # nom soi-même (`--log` sans valeur = nom horodaté auto)
python src/stimulus/ssvep.py               # la fenêtre SSVEP : les flèches du jeu de fréquences en
                                           # vigueur — TROIS au défaut du dépôt, la géométrie en
                                           # prévoit quatre. Ex-`research/ssvep_stimulus.py`,
                                           # déménagée le 2026-09-09. --guide y ajoute les consignes
                                           # et la vérité-terrain : c'est ce que lance la mesure
                                           # « Taux d'émission SSVEP »
python archive/cvep_pilot.py --model data/cvep_model_….npz   # l'écran archivé : décodage LOCAL, la
                                           # RÉFÉRENCE à comparer au réseau en séance (recette 2.9).
                                           # ⚠️ --model explicite : son défaut pointe l'ancien nom fixe
```

⚠️ **Les quatre calibrations sont des BOUTONS, plus des commandes.** Le bouton « Calibrer » de la
page du mode démarre la séance côté moteur, **puis** — pour le P300, l'ErrP et le c-VEP — lance la
fenêtre de `src/stimulus/` avec `--calibrer`. Cet ordre est un contrat testé : la fenêtre attend le
moteur, le moteur compte ses 15 s de chauffe depuis `start_calibration`, et il n'existe **aucune
poignée de main** entre les deux processus (cf. « Ce qui n'a jamais été vérifié » plus bas). Les
trois `--calibrer` restent lançables à la main pour déboguer :

```bash
python src/stimulus/p300.py --calibrer     # 12 manches (P300_CAL_ROUNDS)
python src/stimulus/errp.py --calibrer     # 200 essais (ERRP_CAL_TRIALS)
python src/stimulus/cvep.py --calibrer     # blocs entrelacés, ~2,8 min (la console annonce
                                           # ~3,1 min : elle compte les 15 s de chauffe du moteur)
```

**Après toute modification**, les deux tests headless qui couvrent le plus de code (aucun casque) :

```bash
python src/core/server.py --smoke          # moteur : registre, FRONTIÈRE (core + stimulus +
                                           # research), repos partagé, cumul, flux, vol de
                                           # marqueurs, save/discard, ENREGISTREMENT de séance
python src/console/app.py --smoke          # console : grille, page de mode, réglages, contrôle de
                                           # liaison, lanceur de fenêtre, ORDRE, écran de départ,
                                           # page des mesures, page de flux (Qt offscreen)
```

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

À lire avant de croire qu'un test vert veut dire « ça marche ». **Rien de ce que la console fait
n'a vu un cerveau.** Les autotests prouvent le câblage entre deux processus, sur un board
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
  MI. Les deux mesures nouvelles n'ont été exercées que sur du bruit blanc et des sinusoïdes posées
  à la main : **le repère « ratio alpha > ~1,5 » vient toujours d'UNE personne, sur ce casque**, et
  la seconde cause d'échec du contrôle alpha (« ça monte, mais ce n'est pas de l'alpha ») n'a jamais
  été vue sur un vrai signal.
- 🟠 **Huit constats de la revue du 2026-09-08 restent parqués**, dont deux mordront en séance : la
  console prend `accepted` pour « la séance a démarré » — une instance a été traitée à la source
  pour l'enregistrement (le nom du fichier est décidé par la boucle, pas par l'accusé), **le motif
  reste** ailleurs —, et les refus lancés depuis la GRILLE ne vont encore que dans le terminal
  (recette 1.13).
- 🔴 **Le contrôle de liaison peut BLOQUER une séance légitime.** Il refuse dès qu'**une seule** des
  huit voies sort de [0,5 ; 500] µV — pas seulement les voies clés du mode, qui sont surlignées mais
  ne restreignent pas le refus — et il n'offre **aucune porte de sortie**, là où
  `archive/ui.py:signal_check` laissait passer sur n'importe quelle touche (« à toi de juger »).
  C'est délibéré (un contournement à un clic est un contournement qu'on prend par réflexe), mais si
  une électrode refuse de descendre sous le seuil, la console devient inutilisable. **À trancher
  devant un casque, pas avant.** Vérifié en revanche que `--synthetic` passe : σ mesurés de 7 à
  73 µV, huit verdicts « ok », aucun refus.
- 🔴 **L'ordre de lancement fenêtre/moteur n'a AUCUNE poignée de main.** La console soumet
  `start_calibration` **puis** lance la fenêtre — l'ordre est figé par un test (journal partagé,
  la mutation qui l'inverse fait rougir deux assertions) — et c'est l'initialisation de pygame plus
  l'attente de la fenêtre qui couvrent les 15 s de chauffe du moteur. **Ça tient, ce n'est pas
  garanti** : les deux processus comptent sur deux horloges différentes. Si la fenêtre prend de
  l'avance, ses premières manches tombent dans la chauffe — jetées, comptées, dites, mais la séance
  est plus courte que ce que les deux écrans annoncent.
- ⚠️ **Le compteur `marqueurs_chauffe` est TROMPEUR pour le c-VEP** : sa fenêtre continue de
  clignoter pendant la chauffe (exprès — une horloge n'a pas besoin d'être bonne pour être à
  l'heure), le socle compte ces ~14 marqueurs comme « époques jetées » et conseille à la fenêtre
  d'attendre. Elle attend déjà. Message faux, sans danger.
- ⚠️ **`--cycles` rend fausse la durée annoncée du c-VEP.** Sa calibration n'expose aucun `Param` :
  `duree_protocole_s` vaut pour les défauts, et une fenêtre lancée à la main avec `--cycles 6` sera
  deux fois plus courte que ce que la console annonce. Le moteur ne peut pas le savoir — ce n'est
  pas lui qui mène le protocole.
- ⚠️ **La console n'a jamais été ouverte AVEC un casque** sur les pages de calibration. Trois
  questions n'ont de réponse qu'en séance : est-ce que les ~15 s couvrent vraiment l'écart de
  lancement *sur cette machine* ; est-ce qu'un étudiant comprend qu'un chiffre affiché n'est pas
  encore un modèle enregistré ; et est-ce que le contrôle de liaison est lu ou cliqué au travers.

## Pièges matériels à connaître

- **Ne pas fermer/rouvrir la console (ou le moteur)** en cours de séance : les voies C3/Cz saturent
  à la réouverture (redémarrage de l'amplificateur). Garder une seule session ouverte — c'est
  exactement ce que le point d'entrée unique rend possible : calibrer et décoder sans jamais fermer
  la fenêtre qui tient le casque.
- **Saliner les électrodes** est le principal levier de qualité du signal (gain mesuré très net).
- Vérifier le contact **avant** d'enregistrer : une électrode ou une référence décollée produit une
  séance entière inexploitable, sans autre signal d'alerte que l'écran de contrôle de liaison.
