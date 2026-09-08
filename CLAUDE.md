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
- **Le moteur reste LE PRODUIT ; la console est devenue le POINT D'ENTRÉE** (2026-09-08). Tout le
  parcours d'un étudiant — contrôler le contact, calibrer, choisir un modèle, afficher un stimulus,
  décoder, lire le résultat — s'y fait aux boutons, dans une seule fenêtre qu'on n'a plus à fermer.
  `outils/Console EEG.bat` l'ouvre par un double-clic, sans terminal. `src/core/server.py` reste
  lançable seul : c'est l'accès *headless*, pour une machine sans écran ou un montage à deux
  terminaux, et c'est lui que consomme un client LSL.
- **Le code se divise en QUATRE paquets, sur une règle vérifiable** : `src/core/` = ce dont le
  moteur (`server.py`) a besoin pour tourner, `core/modes/` compris ; `src/stimulus/` = les trois
  fenêtres pygame qui affichent un stimulus verrouillé à la frame et publient des marqueurs
  (`p300.py`, `errp.py`, `cvep.py`) ; `src/console/` = la console PySide6 ; `src/research/` = tout
  le reste (socle pygame, analyses hors ligne, protocoles chiffrés, hypothèses réfutées).

  ```text
  core       n'importe rien du dépôt hors de lui-même   (ni research, ni console, ni stimulus)
  stimulus   -> core                                    (jamais research, jamais console)
  console    -> core, stimulus
  research   -> core, stimulus
  ```

  Si l'envie de remonter une flèche se présente, c'est que le module visé doit DÉMÉNAGER — vers
  `core` s'il sert au décodage, vers `stimulus` s'il sert au stimulus. Ni pygame ni Qt dans `core` :
  le moteur tourne sans écran. **Les deux INTERDITS sont vérifiés par un test**, pas par la
  discipline : `server.py --smoke` (`[smoke-frontiere]`) parse en AST tout `src/core/**/*.py` et
  tout `src/stimulus/**/*.py`, et échoue sur le moindre import interdit. Les deux autres lignes
  sont des permissions : il n'y a rien à y vérifier.
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
- ⚠️ **Un seul de ces trois programmes à la fois** — console, moteur, écran archivé. Le casque
  n'accepte qu'une connexion, et les noms de flux sont un contrat public : deux instances publient
  sous le même nom, donc un programme oublié répond à la place de celui qu'on teste.
  **Les trois fenêtres de `src/stimulus/` sont l'exception** : elles n'ouvrent PAS le casque, elles
  dessinent et publient des marqueurs — c'est exactement pour ça qu'elles se lancent à côté du
  moteur, dans un second terminal, **ou que la console les lance elle-même** quand on calibre.
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
python src/console/app.py --synthetic      # sans casque (board de test BrainFlow)
python src/console/app.py --mode ssvep     # + décodage SSVEP démarré au lancement
```

Dans la console : une grille de **sept tuiles** (les six modes plus le brut), une page par mode
(sortie en direct · réglages · extrait de code client), et **deux boutons qui sortent de la
console** sur les modes qui en ont besoin — « Calibrer » (ouvre la page de calibration : briefing,
réglages, « Commencer ») et « Lancer le stimulus ». Les deux lancements passent par un **contrôle de
liaison** (σ par voie, voies clés du mode surlignées) qui **REFUSE** dès qu'une seule des huit voies
sort de [0,5 ; 500] µV. Une calibration finie s'affiche avec son chiffre et attend « Enregistrer le
modèle » ou « Refaire » : **rien n'atteint `data/` avant ce clic**.

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
                                           # en est le seul autre exemplaire
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
python src/core/server.py --smoke          # moteur : registre, FRONTIÈRE (core + stimulus), repos
                                           # partagé, cumul, flux, vol de marqueurs, save/discard
python src/console/app.py --smoke          # console : grille, page de mode, réglages, contrôle de
                                           # liaison, lanceur de fenêtre, ORDRE (Qt offscreen)
```

⚠️ Il n'y a plus de troisième smoke : `src/research/app.py --smoke` couvrait l'appli pygame, qui
n'existe plus. Les dix écrans archivés gardent chacun le leur — la liste est dans
[`archive/README.md`](archive/README.md), ils ne sont **pas** couverts par les deux ci-dessus.

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
- 🔴 **Le contrôle de liaison peut BLOQUER une séance légitime.** Il refuse dès qu'**une seule** des
  huit voies sort de [0,5 ; 500] µV — pas seulement les voies clés du mode, qui sont surlignées mais
  ne restreignent pas le refus — et il n'offre **aucune porte de sortie**, là où
  `research/ui.py:signal_check` laissait passer sur n'importe quelle touche (« à toi de juger »).
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
