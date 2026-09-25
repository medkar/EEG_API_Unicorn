# Recette — vérifier ce qui a été livré

👉 **Pour EXÉCUTER une passe, prends [docs/qa.md](qa.md)** : la même matière, ramenée à
« action → résultat attendu → ce qui compte pour un échec », dans l'ordre où on la joue. C'est la
feuille qu'on tient à la main. **Ce document-ci est ce qu'on relit quand un point tombe** : il porte
le POURQUOI de chaque test, l'histoire des défauts trouvés, les chiffres de référence mesurés et les
procédures de dépouillement. Les deux se répondent — chaque point de la QA renvoie ici par son
numéro.

Ce document existe pour une raison précise : le produit a été construit par chantiers successifs, et
**personne ne peut retenir de tête ce que chacun a ajouté**. Chaque test ci-dessous rappelle d'abord
ce qu'il vérifie et pourquoi ça a coûté du travail, puis donne la commande exacte et le résultat
attendu. Coche au fur et à mesure.

Les tests sont rangés **par coût croissant**. Tu peux t'arrêter à la fin de n'importe quel niveau :
chacun se suffit à lui-même.

| Niveau | Ce qu'il faut | Durée | Ce qu'il prouve |
|---|---|---|---|
| 0 | rien | 5 min | le code n'est pas cassé — **déjà passé le 2026-07-29** |
| 1 | un écran | ~55 min | la console marche pour un humain — **passé le 2026-08-17, sauf 1.14 à 1.18** ; ⚠️ **1.2, 1.14, 1.15 et 1.16 ont changé le 2026-09-08** (la console lance elle-même les fenêtres de stimulus) et **1.17 / 1.18 sont NEUFS le 2026-09-09** (écran de départ, page de flux + enregistrement) ; ⚠️ **1.19 à 1.21 sont NEUFS le 2026-09-22** (page en blocs, « Tester », résultat en trois lignes), et 1.6, 1.14 à 1.16 ont perdu leur bouton ce jour-là |
| 2 | le casque | ~2 h | le décodage n'a pas régressé (dont 2.1 et 2.2, devenus des pages de la console, ~5 min à eux deux ; 2.6 : l'entraînement MI, ~15 min ; et 2.9 : entraînement c-VEP ~3 min + A 5 + B 5 + A' 5, montages compris). Depuis le 2026-09-22, chaque mode à modèle a aussi son « Tester », de 1,2 à 2,8 min par défaut |
| 3 | une 2e machine | ~15 min | c'est bien une API, pas un programme |

⚠️ **Les quatre derniers tests du niveau 2 (2.6 à 2.9) n'ont JAMAIS été joués en entier** — seul
l'entraînement c-VEP du 2.9 l'a été, une fois, le 2026-09-22 —, et ce sont eux qui portent tout ce
que le produit affirme sur les quatre modes à modèle. Une seule séance casque les couvre — c'est le
travail qui reste.

⚠️ **Ce que le chantier « la console, seul point d'entrée » (2026-09-08) a changé dans ce document,
et ce qu'il n'a PAS changé.** Il a changé les **gestes** : les quatre calibrations sont désormais
jouées par le moteur et lancées d'un bouton, la console lance elle-même les fenêtres de stimulus, et
`src/research/app.py` n'existe plus. Il n'a changé **aucun repère chiffré** de ce document — ni le
100 %/44 % du SSVEP, ni le 46 %/71 % du c-VEP, ni l'erreur sur deux de l'ErrP, ni les ~40 % à trois
classes du MI. **Il n'a mesuré strictement rien** : quatre modes sur six n'ont toujours jamais été
décodés au casque à travers le moteur, et la séance qui le ferait est exactement celle décrite en
2.6 à 2.9. Elle est simplement devenue exécutable sans l'appli pygame.

⚠️ **Et ce que le chantier « plus une seule commande à taper » (2026-09-09) y a changé.** Même
nature, même avertissement : **des gestes, aucune mesure.** Quatre tests de ce document ne se
tapent plus, ils se cliquent — **2.1** (contrôle alpha) et **2.2** (taux d'émission SSVEP) sont
devenus des pages de la console, la source (casque ou board de test) se choisit à l'ouverture au
lieu d'un `--synthetic`, et le journal de séance du **2.9** est une case cochée par défaut. Deux
choses s'ajoutent, sans rien remplacer : la page **« Ce que voit ton application »**, qui montre le
flux sortant lu comme un client, et son bouton **« Enregistrer les verdicts »**, qui écrit l'autre
moitié du dépouillement du 2.9. **Aucun repère chiffré n'a bougé, et aucun n'a été produit.** Les
deux mesures nouvelles n'ont jamais vu un cerveau : elles ont été éprouvées sur du bruit blanc et
des sinusoïdes posées à la main.

⚠️ **Et ce que le chantier « Configurer · Entraîner · Tester » (2026-09-22) y a changé** — né de la
séance casque du même matin : dix minutes de fixation perdues sur un mode arrêté, puis « je ne
comprends pas trop ce que l'on fait ». Encore **des gestes, et un nouveau geste de mesure** :

- **Le vocabulaire.** « Calibrer » s'appelle **Entraîner** ; le « Contrôle alpha » s'appelle
  **Vérifier le casque** (tuile de l'accueil) et s'ouvre aussi par **« Mesurer »** à côté du pic
  alpha de la page SSVEP ; le « Taux d'émission SSVEP » est devenu le **« Tester »** de la page
  SSVEP et n'a plus de tuile. Les tests plus anciens de ce document gardent leurs mots d'époque
  quand ils racontent l'histoire ; leurs GESTES sont corrigés.
- **Chaque mode qui a une vérité-terrain a un « Tester »** — SSVEP, MI, P300, ErrP, c-VEP. C'est le
  protocole d'entraînement rejoué, le moteur DÉCIDANT au lieu d'apprendre, et un score contre son
  hasard. Aucun n'écrit sur le disque. Aucun n'a vu un casque. Cf. 1.20.
- **Ont quitté la page d'un mode** : « Démarrer/Arrêter », « Lancer le stimulus », « Journal de
  séance », « Brancher un client ». Ils reviendront avec « Connecter », second chantier non fait.
  Conséquence à connaître AVANT une séance : **le montage « tout depuis la console » du 2.9
  n'existe plus**, et la console ne passe plus jamais `--log`.
- **Un résultat se lit en trois lignes** (mot coloré, chiffres, une réserve), le reste replié —
  rangé, pas supprimé. Cf. 1.21.

**Aucun repère chiffré n'a bougé** : le moteur décode exactement comme avant, et le chantier n'a
touché ni un seuil, ni une fenêtre, ni un modèle.

## Avant toute séance — trois pièges qui ont déjà coûté des heures

- [ ] **Un seul programme à la fois.** Le casque n'accepte qu'une connexion, et les noms de flux
  sont un contrat public, donc identiques pour toutes les instances. Un moteur oublié répond à la
  place de celui que tu testes. Vérifier d'abord :

  ```powershell
  Get-Process python
  ```

  Attendu : rien. Sinon, identifier avant de tuer — c'est peut-être ta propre console.

- [ ] **Saliner les électrodes.** C'est le principal levier de qualité du signal, gain mesuré très
  net. Et vérifier le contact **avant** d'enregistrer : une référence décollée produit une séance
  entière inexploitable.

- [ ] **Ne pas fermer/rouvrir l'application en cours de séance de CASQUE.** C3 et Cz saturent à la
  réouverture (redémarrage de l'amplificateur). Une seule session ouverte, du début à la fin. En
  synthétique (niveau 1) ce piège n'existe pas : on peut relancer autant qu'on veut.

---

## Niveau 0 — sans casque ni écran

**✅ Passé le 2026-07-29, les 8 verts.** Tu n'as pas besoin de le refaire, sauf après une modif du
code. Il est ici pour que tu saches ce qui est couvert automatiquement — et donc ce que les niveaux
suivants n'ont pas à revérifier.

Les commandes, une par une (jamais en parallèle : elles publient toutes sur les mêmes noms de flux) :

```bash
python src/core/config.py            # proposition de fréquences, choix des diviseurs
python src/core/modes/contract.py    # validation des réglages, messages de refus
python src/core/modes/registry.py    # catalogue des 7 modes, ce qui sort vers la console
python src/core/modes/ssvep.py       # les réglages du mode SSVEP
python src/core/modes/mi.py          # le mode MI : seuil, vote, appariement p_<classe> ↔ classe
python src/core/mi_models.py         # les modèles MI sur le disque : lesquels se chargent vraiment
python src/core/modes/calibration.py # la ligne du temps d'une calibration : chauffe, essais, entraînement, abandon
python src/core/modes/mi_calib.py    # calibration MI : accuracy HONNÊTE (CV par essai), jamais d'écrasement
python src/core/acquisition.py --synthetic   # acquisition seule + fenêtre MI NON filtrée
python src/core/lsl_io.py            # publication LSL, pont d'horloge, verdicts qualité
python src/core/modes/cvep.py        # le mode c-VEP : la PHASE, les 4 causes de -1, le vote
python src/core/cvep_models.py       # les modèles c-VEP : refus des hérités, quel décodeur, tri par date
python src/stimulus/cvep.py --smoke  # la fenêtre c-VEP : la phase lue dans les PIXELS
python src/core/server.py --smoke    # le moteur : frontière core/, stimulus/ ET research/, cumul,
                                     # repos partagé, flux, vol de marqueurs, save/discard,
                                     # enregistrement de séance
python src/console/app.py --smoke    # la console : grille, page de mode, formulaire, contrôle de
                                     # liaison, lanceur de fenêtre, ORDRE, écran de départ, page des
                                     # mesures, page de flux (Qt offscreen)
```

⚠️ **Les trois lignes c-VEP ne sont pas décoratives non plus**, et la troisième moins que les
autres : `src/stimulus/cvep.py --smoke` est le **seul** test du dépôt qui compare, image par image,
la phase que le moteur reconstruirait à celle réellement affichée — lue dans les **pixels**, pas dans
le compteur de l'émetteur. C'est la panne caractéristique de ce mode, celle qui ne lève aucune
exception et ressemble à un étudiant qui fixe mal. La liste complète est dans `CLAUDE.md`.

⚠️ **`python src/research/app.py --smoke` a disparu de cette liste le 2026-09-08** : l'appli pygame
est **supprimée**. Ses écrans sont dans `archive/`, chacun avec son `--smoke` — **douze** au total
pour treize fichiers (`ui.py` n'a rien à lancer : c'est la machinerie partagée, couverte par les
huit qui l'importent), listés dans [`archive/README.md`](../archive/README.md). Ils ne sont couverts
par aucun des deux smokes ci-dessus ; les lancer est un geste à part, le jour où on a besoin d'un
écran archivé.

**Les huit lignes du chantier « la console, seul point d'entrée »** (2026-09-08), qu'aucun des deux
smokes n'exécute et qui portent tout ce que la console sait faire de neuf :

```bash
python src/core/modes/marker_calib.py   # le SOCLE des 3 calibrations à fenêtre : l'accord des DEUX
                                        # épochages sur deux géométries, les 3 causes d'abandon
python src/core/modes/p300_calib.py     # la calibration P300 : cue -> étiquette, flash -> époque
python src/core/modes/errp_calib.py     # la calibration ErrP : l'étiquette voyage sur le feedback
python src/core/modes/cvep_calib.py     # la calibration c-VEP : la phase APPELÉE, jamais recopiée
python src/core/errp_track.py           # la piste ErrP : UNE écriture du protocole, deux écrans
python src/stimulus/registry.py         # clé -> commande, correspondance vérifiée DANS LES 2 SENS
python src/stimulus/p300.py --smoke     # la fenêtre P300 : séquence + séance de calibration
python src/stimulus/errp.py --smoke     # la fenêtre ErrP : la vérité-terrain DANS LES DEUX SENS
```

**Les quatre lignes du chantier « plus une seule commande à taper »** (2026-09-09), qui portent les
deux mesures des tests 2.1 et 2.2 et la fenêtre qui sert la seconde :

```bash
python src/core/modes/mesure.py         # le SOCLE des mesures : la ligne du temps, et le refus
                                        # d'une SECONDE activité minutée — dans les DEUX sens
python src/core/modes/alpha.py          # le contrôle alpha (test 2.1) : le DÉTREND tenu (sans lui,
                                        # l'offset DC de 10⁵ µV fait tomber le ratio de 4,44 à 2,26
                                        # et TOUTE séance échoue à la barrière, casque parfait
                                        # compris) et le refus des voies PLATES
python src/core/modes/ssvep_mesure.py   # le taux d'émission (test 2.2) : UN ESSAI = UNE DÉCISION
python src/stimulus/ssvep.py --smoke    # la fenêtre guidée : la cible lue dans les PIXELS,
                                        # horodatage APRÈS le flip, essais ENTRELACÉS
```

⚠️ **`ssvep_mesure.py` porte l'invariant statistique de la mesure 2.2.** Les fenêtres du moteur se
chevauchent (1,5 s toutes les 0,2 s) : compter chacune comme un essai indépendant est
l'« amélioration » qui vient naturellement à l'esprit, et elle est fausse. Mesuré en mutant le
fichier : n = 24 devient **168**, et l'intervalle de confiance s'effondre de 0,19 à **0,03** de
large. Aucun autre test du dépôt ne rougit sous cette mutation.

**Les six lignes du chantier « Configurer · Entraîner · Tester »** (2026-09-22), qui portent les
quatre tests nouveaux, leur socle et l'affichage de tous les résultats :

```bash
python src/core/modes/affichage.py         # les trois lignes d'un résultat : le NIVEAU vient de la
                                           # table du verdict, jamais d'une seconde table d'écran
python src/core/modes/mesure_marqueurs.py  # le SOCLE des tests menés par une fenêtre : épochage par
                                           # le chemin du décodage, garde de silence, et la CLOISON
                                           # qui retire la vérité avant la sous-classe
python src/core/modes/mi_test.py           # Tester le MI : la DERNIÈRE sortie, -1 jamais REPOS
python src/core/modes/p300_test.py         # Tester le P300 : une MANCHE = un essai, hasard 1/6
python src/core/modes/cvep_test.py         # Tester le c-VEP : un BLOC = une décision, phase APPELÉE
python src/core/modes/errp_test.py         # Tester l'ErrP : 🔴 l'étiquette va au correcteur, JAMAIS
                                           # au décodeur
```

⚠️ **`errp_test.py` porte la seule cloison du chantier**, et sa panne ne casse rien : si l'étiquette
`error` du feedback atteignait le décodeur, le test rendrait un score PARFAIT et faux. Son autotest
espionne le décodeur (appelé une fois par feedback, rien de ce qu'on lui passe ne mène à la
réponse) ; lui passer le moteur au lieu d'une vue du tampon EEG, ou retirer la coupure du socle, le
fait rougir.

Attendu : `VERDICT : OK` pour tous, **sauf `acquisition.py`** qui n'imprime pas de ligne de verdict
— pour celui-là, lire les `OK` ligne à ligne et le code de sortie (`$LASTEXITCODE` sous PowerShell,
qui doit valoir 0).

⚠️ **Les cinq lignes MI ne sont pas décoratives.** Aucun des trois smokes ne les exécute, et le
**non-filtrage de la fenêtre MI** — l'invariant central du mode, un double filtrage décoderait du
bruit avec des probabilités à 0,99 — n'est vérifié que par `acquisition.py --synthetic`.

**Ce que le niveau 0 ne peut pas voir** : rien de ce qui s'affiche. Qt tourne en `offscreen`, et un
écran hors écran répond même à des questions absurdes — il annonce par exemple un rafraîchissement
de 60 Hz qu'il fabrique. D'où le niveau 1.

---

## Niveau 1 — la console à l'écran, sans casque

**✅ Passé le 2026-08-17, les 13 tests.** C'était le niveau le plus rentable des trois et il l'a
prouvé : jusque-là la console n'avait jamais été ouverte dans une fenêtre, donc tout était vérifié
mécaniquement sans avoir jamais été *vu*. Trois défauts en sont sortis, dont **aucun** ne pouvait
être attrapé par les autotests du niveau 0.

- **1.13 — le seul défaut fonctionnel.** Démarrer depuis une tuile de la grille un mode qui va être
  refusé est **silencieux** : le moteur produit bien son refus, la console l'écrit dans le terminal,
  et rien n'apparaît dans la fenêtre. Depuis le formulaire de réglages (test 1.8) le même refus
  s'affiche en rouge — c'est la grille qui n'a pas de destination visuelle.
- **1.3** — les 8 tracés du brut sont trop resserrés et se chevauchent. ✅ **Corrigé le
  2026-09-10** (écart mesuré + rognage au couloir, cf. le test 1.3).
- **1.10** — le texte d'aide gris est tronqué en bas, et trop verbeux pour un étudiant. ✅
  **Corrigé le 2026-09-10.** Deux défauts distincts, et le premier était **fonctionnel** : une page
  plus haute que la fenêtre n'était pas seulement déplaisante, son bas était **inatteignable** — Qt
  écrase les blocs du bas, il ne les rend pas défilables. Le corps d'une page de mode DÉFILE
  désormais (l'en-tête, lui, reste fixe : « ← Modes » doit rester atteignable depuis le bas). Et
  l'aide grise n'affiche plus que la **première phrase** de chaque réglage — 838 caractères au lieu
  de 2 719 sur la page c-VEP —, le texte entier du contrat restant en **infobulle** et revenant à
  l'écran par la case « Aide détaillée ». Rien n'est supprimé, tout est replié. **Depuis le
  2026-09-23**, plus aucune aide en clair : une bulle « ⓘ » juste après chaque libellé montre l'aide
  complète au survol, et la case « Aide détaillée » a disparu.

Les défauts d'affichage sont groupés et traités en dernier ; le refus invisible de 1.13 ne l'est pas.

⚠️ **Le test 1.14 est arrivé APRÈS ce passage** (chantier des marqueurs entrants, livré le même
jour) : il n'a jamais été joué à l'écran. **Les tests 1.17 et 1.18 sont arrivés le 2026-09-09** et
n'ont jamais été joués non plus. Ce sont les trois du niveau 1 qui restent à faire.

Le board synthétique de BrainFlow remplace le casque : signal artificiel, aucun matériel.

⚠️ **Le `--synthetic` des lancements ci-dessous est un RACCOURCI** depuis le 2026-09-09 : il saute
l'écran de départ. C'est voulu pour cette recette — on veut le board de test sans un clic de plus —
mais ce n'est plus le chemin normal, et l'écran qu'il saute est ce que le test 1.17 vérifie.

**Deux choses à savoir avant de commencer, sinon tu vas chercher un bug qui n'existe pas :**

1. **La console sait démarrer/arrêter un mode depuis la grille** (bouton **Démarrer**/**Arrêter**
   par tuile) — ce n'était PAS le cas avant ce chantier, où il fallait la relancer avec `--mode`
   pour voir quoi que ce soit tourner. `--mode` au lancement reste un raccourci utile : il démarre
   plusieurs modes d'un coup, ce qu'on exploite au test 1.7 pour le repos partagé. ⚠️ Depuis le
   2026-09-22, la page d'un mode n'a plus de « Démarrer » : le décodage continu se démarre depuis la
   tuile — seul le Neuro garde, sur sa page, un bouton « Observer » qui le démarre (cf. 1.19).
2. ~~**« Appliquer » est refusé sur un mode arrêté** — « SSVEP n'est pas démarré ».~~ **Faux depuis
   le 2026-09-21** : un réglage se pose sur un mode arrêté, il est validé, RETENU (confirmation en
   vert) et le mode démarrera avec. Les **deux lancements** ci-dessous restent utiles pour une autre
   raison : le 1.7 s'observe dès le lancement.

**Lancement A** — pour les tests 1.1 à 1.6 :

```bash
python src/console/app.py --synthetic
```

### 1.1 — Elle s'ouvre et elle est lisible

- [ ] La fenêtre s'ouvre, titre « EEG_API_Unicorn — console d'expérimentation », 1100×720.
- [ ] En haut, un **bandeau permanent** : liaison casque, fréquence d'échantillonnage, et σ par voie.
- [ ] En dessous, une **grille de 7 tuiles** sur deux rangées de 4 : **Brut, SSVEP, c-VEP, Neuro**
      puis **Motor Imagery, P300, ErrP**. *(L'ordre suit `registry.MODES`, et il se lit : la
      première rangée est ce qu'on peut lancer sans rien avoir appris du sujet, la seconde ce qui
      exige un modèle entraîné par personne. SSVEP et c-VEP sont côte à côte parce que ce sont les
      deux seuls modes où l'on fixe une cible qui clignote — c'est la paire que le test 2.9 compare.
      ⚠️ Le c-VEP est en première rangée pour cette comparaison, pas parce qu'il serait immédiat :
      lui aussi exige un modèle, et en plus une horloge.)*
- [ ] La tuile « Brut » est **en marche** (le brut démarre par défaut) ; les six autres affichent
      « arrêté ».

> Rien ne peut être lu ? Le bandeau et les tuiles sont dimensionnés pour 1100 px de large. Note la
> taille de police du système si c'est illisible : c'est un vrai défaut, pas un détail.

### 1.2 — Plus AUCUNE tuile grisée

⚠️ **Ce test a changé de sens le 2026-08-21, et il faut le lire avant de conclure à une
régression.** Il vérifiait autrefois que les trois tuiles grisées (c-VEP, P300, ErrP) disaient
*pourquoi* elles l'étaient. Elles ne le sont plus : les trois ont rejoint le moteur, le c-VEP en
dernier. **Le moteur publie les six modes.** Le module qui portait les entrées « appli pygame »
(`core/modes/external.py`) a été supprimé avec sa dernière entrée.

- [ ] **Aucune des 7 tuiles n'est grisée.** Chacune porte sa case « publié » et son bouton
      « Ouvrir ». Si tu en vois une grise, c'est une régression — et la console le tient du
      contrat, pas d'une liste écrite à la main (`spec["status"] != "moteur"`).
- [ ] **⚠️ Ce point a changé le 2026-09-08.** Le bouton **Calibrer** apparaît maintenant sur les
      **quatre** modes à modèle — MI, P300, ErrP, c-VEP — parce que le moteur joue les quatre
      calibrations. Le critère est `calibration.jouable` dans le catalogue (« le moteur a-t-il un
      runtime pour cette calibration »), pas `kind`, qui dit seulement QUI mène le protocole.
      Un bouton absent sur l'un des quatre est une régression : c'est exactement le défaut que la
      tâche 6 du chantier a trouvé, où un critère périmé (`kind == "console"`) l'avait fait
      disparaître de tous les modes, MI compris, sans qu'aucun test ne le voie.
- [ ] Sur le P300, l'ErrP et le c-VEP, un **second** bouton apparaît à côté : **Lancer le
      stimulus**. Leur `Calib(kind="fenetre")` dit que leur protocole a besoin d'un stimulus
      verrouillé à la frame, que Qt ne sait pas rendre — la console lance donc une fenêtre de
      `src/stimulus/`, en second processus. Le MI, endogène, n'a ni ce bouton ni cette fenêtre.

> ⚠️ **Les deux cases ci-dessus ont changé le 2026-09-22.** Le bouton « Calibrer » est devenu le bloc
> **« 2. Entraîner »** de la page du mode (même critère, `calibration.jouable`), et **« Lancer le
> stimulus » n'existe plus** : la fenêtre de stimulus n'est lancée que par « Entraîner » et par
> **« Tester »**, qui la ferment eux-mêmes. Ce qui se vérifie désormais est la forme de la page,
> au 1.19. La grille, elle, n'a pas bougé : sept tuiles, aucune grisée, et en dessous **une seule**
> tuile de séance, « Vérifier le casque » — les tests n'y ont pas de tuile (un test vit sur la page
> de SON mode ; la règle est lue dans le `test_id` des modes, pas dans une liste).

> **Sans modèle entraîné sur ce poste, c'est normal** : la tuile reste active, mais lancer le mode
> sera refusé d'une ligne : « Aucun modèle entraîné : dans la console, clique « Entraîner » sur la
> page du mode. » Ça vaut pour les
> **quatre** modes à modèle : MI, P300, ErrP et c-VEP. `data/` est gitignoré, donc un dépôt
> fraîchement cloné est toujours dans cet état.

### 1.3 — Le mode brut montre vraiment le signal

- [ ] Cliquer « Ouvrir » sur **Brut** → 8 tracés qui défilent, une étiquette par voie
      (Fz, C3, Cz, C4, Pz, PO7, Oz, PO8).
- [ ] **Les 8 tracés ne se chevauchent pas**, quelle que soit l'amplitude du signal.
- [ ] La ligne grise sous le graphe annonce l'écart **en vigueur** (« un couloir = … µV ») et il
      **change** quand le signal change d'amplitude — il n'est plus fixé à 100 µV.
- [ ] « ← Modes » revient à la grille.

> 🐛 **2026-08-17** : les 8 tracés sont là et correctement étiquetés, mais **trop resserrés — ils se
> chevauchent**. Rangé dans le lot d'affichage.
>
> ✅ **Corrigé le 2026-09-10.** L'écart entre voies est désormais **mesuré sur le signal** (75e
> centile des huit étendues, posé sur une graduation ronde, avec une zone morte de deux graduations
> pour que l'échelle ne clignote pas), et **chaque tracé est rogné à son couloir** : le
> non-chevauchement est GÉOMÉTRIQUE, pas une affaire de réglage heureux. Une voie qui déborde
> s'aplatit sur son rail et **la ligne grise la nomme** — c'est justement le signal qu'on cherche
> ici (contact suspect), pas un défaut à cacher. Vérifié par `console/app.py --smoke`, quatre
> mutations rouges (rognage retiré, échelle refixée, maximum au lieu du 75e centile, zone morte
> retirée).

### 1.4 — Le bandeau vit

- [ ] Les σ se mettent à jour (~1 Hz), une valeur par voie.
- [ ] ⚠️ Sur board synthétique, la corrélation inter-voies monte à ~0,80-0,83 : c'est **normal**
      (signal artificiel corrélé), le seuil d'alarme est à 0,90. **N'en tire aucune conclusion.**
      Sur casque réel, c'est 0,31-0,50.

### 1.5 — Couper la diffusion sans arrêter le mode

- [ ] Décocher « publié » sur la tuile Brut → le tracé continue de défiler, mais le flux
      n'est plus sur le réseau.
- [ ] Recocher → il repart.

> ⚠️ **Angle mort de ce test, découvert le 2026-08-17** : la moitié qui compte — « le flux n'est
> plus sur le réseau », puis « il repart » — **ne se voit pas depuis la fenêtre**. On peut cocher ce
> test en n'ayant regardé que le tracé, et laisser la case décochée sans s'en apercevoir (c'est
> arrivé, et le test 1.6 a échoué juste après pour cette raison). Vérifier des deux côtés :
>
> ```bash
> python -u examples/receiver.py --list
> ```
>
> Attendu : `EEG_API_Unicorn_raw` **absent** quand la case est décochée, **présent** quand elle
> est cochée. `_quality` et `_status` restent là dans les deux cas.

### 1.6 — « Brancher un client » : l'extrait marche vraiment

C'est ce qu'un étudiant va copier. S'il ne tourne pas, tout le reste ne sert à rien.

- [ ] Ouvrir Brut → bloc « Brancher un client » → il nomme le flux `EEG_API_Unicorn_raw` et
      liste les 8 voies.
- [ ] Cliquer « Copier », coller dans un fichier `essai.py`, et **le lancer dans un autre terminal**
      pendant que la console tourne :

  ```bash
  python essai.py
  ```

  Attendu : des valeurs qui défilent. Pas une exception, pas un blocage muet.

> ✅ **2026-08-17** : **2931 échantillons en 11,7 s = 250,1 Hz**, les 8 voies nommées. L'extrait
> tourne tel quel, sans retouche. Il appelle `open_stream()` avant le premier `pull`, ce qui est le
> détail qui faisait perdre la première seconde en silence dans les premières versions.
>
> ⚠️ **Le bloc « Brancher un client » a quitté la page le 2026-09-22** ; il reviendra avec
> « Connecter ». Ce test ne se joue donc plus depuis la console. Le CONTENU de l'extrait reste
> vérifié par l'autotest de `core/modes/contract.py` (`client_snippet`), et les noms de flux cités
> par `examples/` par `[smoke-exemples]` ; le bouton « Copier » et la régénération de l'extrait au
> changement de réglage ne sont plus couverts nulle part. D'ici là, le client de référence est
> `examples/receiver.py` (test 3.1).

**Lancement B** — fermer la console, puis la rouvrir avec les modes démarrés. Le test 1.7 s'observe
**dès le lancement**, alors garde un œil sur la fenêtre tout de suite.

```bash
python src/console/app.py --synthetic --mode ssvep,neuro
```

### 1.7 — Le repos partagé

Deux modes lancés dans la même commande partagent une seule phase de repos. Facile à casser sans que
rien ne le signale : un mode dont le plancher n'a pas été mesuré ne lève aucune erreur, il ne détecte
simplement jamais rien.

- [ ] Chronomètre en main : **15 s de chauffe**, puis **25 s de repos** — le maximum des deux (le
      SSVEP en demande 8, le neuro 25), puis les deux modes décodent.
- [ ] **Une seule consigne** s'affiche, celle du mode au repos le plus long — le neuro :
      « Repos : regarde l'écran, immobile et détendu — on cale TON zéro du jour. »
- [ ] À la fin, **les deux** tuiles passent à « décode ». Si une seule le fait, c'est le défaut que
      ce test existe pour attraper.

### 1.8 — Le moteur REFUSE une fréquence impossible

**C'est le cœur du chantier 2.** Une fréquence qui ne divise pas le rafraîchissement de l'écran fait
sauter des cycles à l'affichage : le décodeur corrèle alors contre une sinusoïde que personne
n'affiche. Zéro détection, aucune erreur, rien à déboguer. Avant, c'était accepté en silence.

- [ ] Ouvrir **SSVEP** → bloc « 1. Régler » → champ « Fréquences des cibles ».
- [ ] Taper `15, 17` → **Appliquer**.
- [ ] Attendu : un refus **en rouge**, qui nomme le coupable et propose les deux voisins :

  > « Fréquences des cibles » : 17 Hz n'est pas un diviseur entier de 60 Hz. L'écran sauterait des
  > images et rien ne serait détecté. Les plus proches sont 15 et 20 Hz.

### 1.9 — Le bouton « Proposer » répond, et l'alpha change la réponse

Le fait scientifique derrière ce réglage : le **pic alpha est propre à chaque personne** (moyenne de
population ≈ 9,6 Hz, plage 7-13 Hz). Une cible posée sur ton pic ne se distingue pas de ton propre
fond au repos. Le trio validé sur casque (15 · 20 · 8,571) est accordé à un pic à 10,5 Hz — celui du
développeur. **Le distribuer tel quel à une promotion poserait une cible sur le pic d'une bonne
partie des étudiants.**

- [ ] Champ « Pic alpha » laissé à sa valeur par défaut **9,6** (la moyenne de population).
- [ ] Cliquer **Proposer « Fréquences des cibles »**.
- [ ] Attendu : le champ des fréquences se remplit avec **12, 15, 20**. Aucun avertissement.
- [ ] Cliquer **Appliquer** → accepté. *(Ce que le moteur propose, il doit l'accepter — ça n'a pas
      toujours été vrai : la tolérance refusait la valeur que son propre message affichait.)*
- [ ] Maintenant mettre « Pic alpha » à **10,5**, cliquer **Proposer** à nouveau.
- [ ] Attendu : **8,571 · 15 · 20** — le trio validé casque, régénéré. C'est la meilleure preuve
      disponible que la règle n'est pas arbitraire.

### 1.10 — Un écran qui n'est pas à 60 Hz

Le blocage qui a été corrigé en fin de chantier : déclarer un écran 144 Hz était refusé (les
anciennes fréquences ne le divisent plus) **et** la proposition continuait de calculer sur 60 — sans
porte de sortie.

- [ ] Survoler la bulle « ⓘ » de « Rafraîchissement » : son second paragraphe annonce le
      rafraîchissement de **cette** fenêtre, et précise que c'est celui de l'écran qui **affiche les
      cibles** qui compte.
      Vérifier qu'elle dit quelque chose de sensé sur ta machine.
- [ ] Mettre « Rafraîchissement » à **144**, cliquer **Proposer**.
- [ ] Attendu : **12 · 14,4 · 18**.
- [ ] Cliquer **Appliquer** → accepté, sans avoir eu à toucher aux fréquences d'abord.

> 🐛 **2026-08-17** : le contenu est juste — l'aide annonce bien le rafraîchissement réel de la
> fenêtre (60,0028 Hz sur le poste de dev) et renvoie vers l'écran des cibles. C'est le rendu qui
> pèche : **texte tronqué en bas**, et trop verbeux pour un étudiant. Lot d'affichage.

### 1.11 — Un avertissement n'est pas un refus

- [ ] Taper **4** fréquences dans le champ (n'importe lesquelles, par exemple `12, 15, 20, 30`),
      remettre « Rafraîchissement » à **60** et « Pic alpha » à **9,6**, puis **Proposer**.
- [ ] Attendu : le champ se remplit avec **5 · 12 · 20 · 30**, accompagné d'un message
      **orange** (pas rouge) : « hors de la plage confortable 8-20 Hz : 5, 30 — scintillement plus
      pénible, réponse plus bruitée ».
- [ ] Vérifier que ce message est **visuellement distinct** du refus rouge du test 1.8. Un succès
      peint en rouge se lit comme un échec.
- [ ] **Appliquer** → accepté.

### 1.12 — Un réglage qui ne change rien ne coûte rien

Le contrat déclare quels réglages le **décodeur** lit. Changer les fréquences invalide le plancher de
repos (il est mesuré **par fréquence**) et les étiquettes du flux : il faut donc tout refaire.
Changer le rafraîchissement ou le pic alpha ne sert qu'à proposer et à valider — refaire 23 secondes
de repos pour ça apprendrait surtout à ne plus toucher aux réglages.

Regarder le **terminal** derrière la fenêtre pendant ces deux manipulations :

- [ ] Appliquer de **nouvelles fréquences** → la tuile SSVEP repasse par chauffe puis repos (~23 s)
      avant de redécoder. C'est voulu.
- [ ] Appliquer un **rafraîchissement ou un alpha seuls**, sans toucher aux fréquences → aucun repos,
      et le terminal écrit : « (sans effet sur le décodage : ni repos refait, ni flux recréé) ».

### 1.13 — Démarrer / arrêter un mode depuis la grille

Toujours dans la fenêtre du **Lancement B** (SSVEP et Neuro tournent depuis le test 1.7) : c'est la
capacité que ce chantier a ajoutée à la console — avant, il fallait fermer et relancer avec `--mode`
pour changer l'ensemble des modes actifs.

- [ ] Revenir à la grille (« ← Modes ») → la tuile **Neuro** affiche « décode » et propose un
      bouton **Arrêter**.
- [ ] Cliquer **Arrêter** sur la tuile Neuro → elle repasse à « arrêté », et
      `EEG_API_Unicorn_decoded_neuro` disparaît du réseau (vérifiable avec
      `python -u examples/receiver.py --list` dans un second terminal — le premier fait tourner
      la console du Lancement B).
- [ ] Cliquer **Démarrer** sur la même tuile → elle repart, chauffe puis repos compris, **sans
      qu'il ait été nécessaire de fermer la console**.
- [ ] La tuile **Motor Imagery** porte le même bouton **Démarrer** ; elle n'est grisée nulle part
      (cf. 1.2). Sans modèle entraîné sur ce poste, cliquer dessus redonne le refus déjà vu en
      1.2 (« Aucun modèle entraîné… »), pas un bouton inactif.

> 🐛 **2026-08-17 — LE défaut du niveau 1, et le seul qui ne soit pas cosmétique.** Ce dernier point
> échoue : le clic est **silencieux**. Le moteur refuse correctement, avec le message complet —
> `refusé : « Modèle entraîné » : aucun choix disponible … bouton « Calibrer » sur cette page` —
> mais la console l'écrit **dans le terminal**, pas dans la fenêtre. Rien n'apparaît à l'écran.
>
> Signature relevée dans le journal : **cinq clics d'affilée**, cinq refus identiques. C'est ce que
> fait quelqu'un devant un bouton qui ne répond pas.
>
> Le refus lancé depuis le formulaire de réglages (test 1.8) s'affiche, lui, en rouge. C'est donc la
> **grille** qui n'a pas de destination visuelle pour un refus, pas le moteur qui se tait.
>
> ✅ **Corrigé le 2026-09-10** (`c960e39`) : tout refus d'une commande s'affiche dans le **bandeau**,
> visible depuis n'importe quelle page, et une commande acceptée l'efface. Vérifié par
> `console/app.py --smoke` (clic « Démarrer » sur la tuile MI d'un moteur qui refuse). Attendu
> désormais : le refus **dans le bandeau**, en UNE ligne — « Aucun modèle entraîné : dans la
> console, clique « Entraîner » sur la page du mode. » Il recopiait l'aide entière du réglage
> derrière « aucun choix disponible », un paragraphe dans un bandeau : raccourci le 2026-09-23
> (`Param.si_vide`, passe QA), après avoir dit « Calibrer » jusqu'au 2026-09-23 (`c9701fa`).

### 1.14 — Le P300 : le tuyau des marqueurs, sans casque

C'est le chantier du 2026-08-17, et c'est la première fois que le moteur **écoute** au lieu de
seulement publier. Le décodage sera du hasard en synthétique — ce n'est pas ce qu'on teste. Ce qu'on
vérifie, c'est que les marqueurs partent, arrivent, trouvent leur EEG, et qu'une décision sort.

**Du 2026-09-08 au 2026-09-22, ce test se jouait en UN seul programme** : la console démarrait le
mode ET lançait la fenêtre de stimulus (bouton **Lancer le stimulus** sur la page P300).
⚠️ **Ce bouton n'existe plus depuis le 2026-09-22** (il reviendra avec « Connecter ») : la console
démarre le mode (tuile P300 → « Démarrer »), et la fenêtre se lance **à la main, dans un second
terminal** — ce que fera toute application cliente. Ça ne coûte rien au casque : le stimulus
**n'ouvre pas le casque**, c'est ce qui lui permet de tourner à côté du moteur. Le même tuyau, avec
une vérité-terrain et un verdict, est désormais joué par **« Tester »** (1.20) ; ce test-ci garde son
intérêt propre : regarder le décodage CONTINU et ses compteurs.

```bash
# terminal 1 — la console, le mode démarré
python src/console/app.py --synthetic --mode p300
# terminal 2 — la fenêtre de décodage (ESC pour la fermer)
python src/stimulus/p300.py --windowed
# terminal 3 (facultatif) — pour voir ce qui sort
python -u examples/receiver.py --stream decoded_p300
```

⚠️ Quand c'est la CONSOLE qui lance une fenêtre (« Entraîner », « Tester »), elle passe d'abord
par le **contrôle de liaison** — en `--synthetic` il laisse passer (σ de 7 à 73 µV, huit verdicts
« ok ») —, et elle l'ouvre **en plein écran**, par-dessus elle : c'est le comportement voulu en
séance. Alt-tab pour revenir, ESC pour la fermer. Lancée à la main comme ci-dessus, la fenêtre ne
passe par rien de tout ça.

- [ ] Le moteur dit qu'il attend le flux de marqueurs, **puis** qu'il s'y connecte quand le
      stimulus démarre. S'il reste muet, c'est le défaut que ce test existe pour attraper.
- [ ] Les 6 cibles clignotent une par une, en ordre mélangé.
- [ ] À la fin de la manche, **une sélection sort** sur `decoded_p300`.
- [ ] La cible désignée sera fausse cinq fois sur six : **c'est normal**, le board synthétique ne
      produit aucun P300. On teste le tuyau, pas le cerveau.
- [ ] **Le bandeau de la console dit l'état d'une fenêtre qu'ELLE a lancée**, en permanence et même
      depuis la grille — à vérifier donc sur « Tester le P300 » (1.20), plus ici. Fermée
      normalement, le bandeau montre ses deux dernières lignes (son bilan, depuis le 2026-09-22).
      Tuée autrement (gestionnaire de tâches) : le bandeau doit annoncer une mort **anormale**, avec
      le code de sortie et la dernière ligne de sa sortie d'erreur. Un processus qui meurt en
      silence est le défaut que ce chantier répare.
- [ ] ~~Un second clic sur « Lancer le stimulus » est REFUSÉ~~ — plus de bouton depuis le
      2026-09-22. La règle tient toujours dans le lanceur (une seule fenêtre à la fois : deux
      publieraient les mêmes marqueurs sous le même nom, et le moteur mélangerait les deux séances
      sans rien signaler).
- [ ] Fermer la console pendant un test : sa fenêtre meurt avec elle (`closeEvent`). Aucun processus
      orphelin ne doit rester (`Get-Process python`). Une fenêtre lancée à la main, elle, survit :
      ferme-la par ESC.

**Le montage historique à deux terminaux reste valable**, et c'est lui qu'utilise une application
tierce :

```bash
python src/core/server.py --synthetic --mode p300   # terminal 1
python src/stimulus/p300.py --windowed              # terminal 2
```

⚠️ **Jamais la console ET le moteur en même temps** : ils publieraient `decoded_p300` deux fois sous
le même nom.

> ⚠️ Sans modèle P300 entraîné sur ce poste, le mode **refuse de démarrer** et dit d'aller cliquer
> sur « Calibrer » — le bouton s'appelle **« Entraîner »** depuis le 2026-09-22, le texte n'a pas
> suivi. C'est le comportement attendu sur un dépôt fraîchement cloné (`data/` est gitignoré), pas
> une panne. « Entraîner » (page P300, bloc « 2. Entraîner ») joue la séance (`P300_CAL_ROUNDS` = 12
> manches) : la console lance la fenêtre avec `--calibrer`, le moteur encaisse les marqueurs et
> entraîne à la fin. ⚠️ **Ce chemin-là n'a JAMAIS été joué**, ni au casque ni en synthétique —
> seulement en autotest. Un modèle obtenu en synthétique serait chargeable et dépourvu de tout sens,
> comme celui du c-VEP en 1.16 : suffisant pour tester le tuyau, rien d'autre.

### 1.15 — L'ErrP : le 5e mode, sans casque

> ⚠️ **Sans modèle ErrP entraîné sur ce poste, le mode refuse de démarrer** et dit d'aller cliquer
> sur « Calibrer » (le bouton s'appelle **« Entraîner »** depuis le 2026-09-22). C'est le
> comportement attendu sur un dépôt fraîchement cloné (`data/` est gitignoré), pas une panne. Depuis
> le 2026-09-08 ce bouton de la page ErrP joue la
> séance : la console lance `src/stimulus/errp.py --calibrer`, le moteur encaisse les `feedback`
> **étiquetés** et entraîne à la fin. ⚠️ **Mais cette calibration-là exige le casque** :
> `ERRP_CAL_TRIALS` = 200 essais, et un modèle appris sur du bruit synthétique ne dit rien du
> détecteur qu'on veut éprouver ici. Si tu n'en as jamais fait, ce test du niveau 1 n'est jouable
> **qu'après le 2.8** — c'est la seule entorse à la règle « le niveau 1 ne demande pas de
> matériel », et elle est dans la nature du mode, pas dans son code.

Le décodage sera du hasard en synthétique — ce qu'on vérifie, c'est que le tuyau porte le second
paradigme sans qu'on ait rien redécouvert.

⚠️ **La console, pas le moteur nu.** Le **dernier** point ci-dessous, et les deux encadrés ⚠️,
demandent une page et un réglage qui n'existent que dans la console ; `server.py` est *headless*, il
n'a ni page ErrP ni option `tnr_target`. La console crée son propre moteur, donc **lancer les deux
publierait `decoded_errp` deux fois sous le même nom** — exactement le piège que CLAUDE.md interdit.

**Trois terminaux de nouveau depuis le 2026-09-22** : la page ErrP a perdu son bouton **Lancer le
stimulus** (il reviendra avec « Connecter »), donc la fenêtre de décodage se lance à la main, à côté
de la console. Du 2026-09-08 au 2026-09-22 elle se lançait depuis la page.

```bash
# terminal 1 — la console (le mode démarre déjà « publié » ; la case est sur la TUILE)
python src/console/app.py --synthetic --mode errp
# terminal 2 — la fenêtre de décodage, n'ouvre pas le casque
python src/stimulus/errp.py --windowed
# terminal 3
python -u examples/receiver.py --stream decoded_errp
```

⚠️ Une seule fenêtre à la fois : ne lance pas « Tester l'ErrP » pendant que celle du terminal 2
tourne — deux fenêtres publieraient sous le même nom.

- [ ] Le moteur passe par **15 s de chauffe puis 8 s de repos** avant de décoder, et annonce le σ
      par voie qu'il a mesuré. C'est sa référence de rejet d'artefact — sans elle, pas de décodage.
- [ ] **L'émetteur**, lui, annonce qu'il attend : le moteur écoute, mais il **jette tout pendant sa
      chauffe et son repos (~23 s)** — et la piste reste **immobile** jusque-là. Le moteur ne dit
      donc **rien** sur des marqueurs jetés : ce silence est le succès, pas une panne.
- [ ] Pour voir l'autre moitié du garde-fou, relance l'émetteur avec `--no-wait` : il démarre tout de
      suite, et le moteur écrit alors « N feedback(s) reçus pendant la CHAUFFE/le REPOS : jetés ».
      C'est voulu : l'offset du casque dérive encore, ces époques ne valent rien.
      (`python src/stimulus/errp.py --windowed --no-wait`, à la place de celle du terminal 2.)
- [ ] Un point avance sur une piste, se trompe délibérément **environ une fois sur quatre** (28 %,
      le chiffre est affiché à l'écran), et montre son résultat une seconde.
- [ ] À chaque résultat affiché, **un échantillon sort** sur `decoded_errp`, visible dans le
      terminal 3. Y compris quand le moteur ne peut pas juger : il publie alors `error = -1`,
      jamais `0`.
- [ ] ⚠️ **Le marqueur de DÉCODAGE est NU** : `{"mode": "errp", "event": "feedback"}`, sans champ
      `error`. Le champ n'existe qu'en calibration (`--calibrer`) et, depuis le 2026-09-22, en test
      (`--tester`, même protocole) — où le moteur le retire avant que le décodeur ne voie le
      marqueur (cf. 2.8). S'il apparaissait ici, l'émetteur donnerait la réponse au moteur et tout
      ce que ce mode affirme deviendrait faux — sans qu'aucun compteur ne bouge. C'est ce que
      `python src/stimulus/errp.py --smoke` vérifie **dans les deux sens**.
- [ ] Sur la page ErrP — case **« Décodage en direct »** cochée depuis le 2026-09-22 —, le verdict
      s'affiche **avec le score et le point de fonctionnement**, pas comme une sentence. Et « pas
      de verdict » se distingue visuellement de « pas d'erreur ».

> ⚠️ **Le réglage « Bonnes commandes gardées » n'est pas décoratif.** Mets-le à 0,95 puis à 0,70 et
> regarde le seuil changer : c'est le compromis, et il est raide — garder 95 % des bonnes commandes
> ne laisse attraper qu'une erreur sur quatre.
>
> ⚠️ **Mais ce réglage recrée le flux.** Le moteur écrit lui-même « RECRÉÉ (réabonnez-vous) », et le
> mode **refait chauffe + repos, ~23 s**, avant de décoder à nouveau. Ton `receiver.py` du terminal 3
> est abonné à l'ancien flux : **il devient muet définitivement**. Relance-le après chaque changement
> et attends la fin du repos avant de compter quoi que ce soit — sinon tu mesureras un flux mort et
> tu concluras que baisser le réglage a cassé le détecteur, ce qui est l'inverse de la vérité.

### 1.16 — Le c-VEP : une HORLOGE dans le tuyau, sans casque

C'est le chantier du 2026-08-21, le **6e et dernier mode**. Même montage que le 1.15, et pourtant ce
test ne vérifie pas la même chose — parce que **ces marqueurs-là ne délimitent aucune époque : ils
tiennent une horloge**. Le P300 et l'ErrP demandent au moteur de découper autour d'un instant ; le
c-VEP décode en continu, comme le SSVEP, et ses marqueurs lui disent seulement **où en est le code
affiché**. Sans eux il ne décode rien du tout — pas « mal », *rien*.

> ⚠️ **Il faut un modèle c-VEP sur ce poste**, sinon le mode refuse de démarrer et dit d'aller
> cliquer sur « Calibrer » (bouton **« Entraîner »** depuis le 2026-09-22). Contrairement à l'ErrP
> (1.15), cet entraînement-là **se joue en synthétique** : `python src/console/app.py --synthetic`,
> page c-VEP → **Entraîner**, **~3 min**
> (`CVEP_CAL_CYCLES` = 15 cycles par cible, `CVEP_CAL_SETTLE_CYCLES` = 4 jetés à chaque changement ;
> la console annonce **≈ 3,1 min** — 15 s de chauffe plus ≈ 2,8 min de protocole, que la fenêtre
> calcule et imprime de son côté : `[cvep-stim] … ≈ 2.8 min`). Le
> modèle obtenu est **chargeable et dépourvu de tout sens** — il n'a vu aucun cerveau. Il suffit pour
> ce test, qui vérifie le tuyau et pas le décodage. Elle écrit **deux** fichiers horodatés
> (`data/cvep_model_*.npz` pour l'eCCA, `data/cvep_rcca_model_*.npz` pour le rCCA) et n'écrase jamais
> rien — **et rien n'est écrit tant qu'on n'a pas cliqué « Enregistrer le modèle »** : l'écran montre
> d'abord les deux justesses et le verdict de McNemar, puis on garde ou on refait.
>
> ⚠️ **Ce chemin n'a jamais été joué en synthétique** : l'ancienne calibration pygame l'a été (elle
> est archivée en `archive/cvep_calibrate.py`) ; celle du moteur l'a été une fois, **au casque**, le
> 2026-09-22 (25,0 % pour un hasard à 17 %, cf. 2.9).

**La console plutôt que le moteur nu**, comme au 1.15 : les deux seuils qu'on manipule au dernier
point n'existent que là, et les compteurs qui font tout l'intérêt de ce test s'y lisent d'un coup
d'œil (case « Décodage en direct » de la page c-VEP). Jamais les deux à la fois — ils publieraient
`decoded_cvep` deux fois sous le même nom.

**Trois terminaux de nouveau depuis le 2026-09-22** : la page c-VEP a perdu son bouton **Lancer le
stimulus** (il reviendra avec « Connecter »), donc la fenêtre de décodage se lance à la main.

```bash
# terminal 1 — la console, le mode démarré
python src/console/app.py --synthetic --mode cvep
# terminal 2 — l'émetteur : n'ouvre pas le casque
python src/stimulus/cvep.py --windowed
# terminal 3
python -u examples/receiver.py --stream decoded_cvep
```

⚠️ Les deux points ci-dessous qui demandent `--refresh 75` et `--seed` se jouent en relançant
l'émetteur du terminal 2 avec l'option : `python src/stimulus/cvep.py --windowed --refresh 75`.
Jamais deux émetteurs à la fois — ils publieraient sous le même nom.

- [ ] Le moteur annonce qu'il attend le flux de marqueurs, **puis** qu'il s'y connecte quand
      l'émetteur démarre.
- [ ] Il annonce aussi, en une ligne, **quel modèle, quel décodeur et sur quel flux il écoute
      l'horloge** — par exemple `[cvep] modèle « cvep_model_….npz » (eCCA, seuils 0.26/0.09) —
      horloge attendue sur « EEG_API_Unicorn_stim »`. C'est le réglage le plus facile à se tromper.
- [ ] Six disques clignotent, **un cercle vert** entoure la cible consignée, et elle change toutes
      les ~8,4 s. Le bandeau du haut dit en direct `moteur À L'ÉCOUTE` ou `PERSONNE n'écoute`.
- [ ] ⚠️ **Le clignotement démarre TOUT DE SUITE, pendant la chauffe de 15 s du moteur** — un
      bandeau vert le dit. C'est l'inverse de l'ErrP, qui fige son écran. Le c-VEP **encaisse** ses
      marqueurs de chauffe : une horloge n'a pas besoin d'être bonne pour être à l'heure. Si tu vois
      l'écran s'immobiliser, c'est une régression.
- [ ] L'émetteur imprime sa **graine** (`--seed N` rejoue la séance à l'identique) et, pour chaque
      consigne, **deux** horodatages : `t=` et « compter à partir de t=… (+2,7 s de transition) ».
      Le second est celui qui sert à dépouiller — voir le 2.9.
- [ ] Sur `decoded_cvep`, terminal 3 : **10 voies**, nommées
      `target_index`, `confidence`, `score_0`…`score_5`, puis `corr_min` et `margin`, à ~5 Hz.
- [ ] `target_index` vaut **-1** en permanence : **c'est le résultat attendu**, le board synthétique
      ne produit aucune réponse c-VEP. On teste le tuyau, pas le cerveau.
- [ ] **LE point de ce test.** Ouvrir la page c-VEP et regarder POURQUOI c'est -1 : c'est
      `sous_les_seuils` qui doit **dominer** (le décodage tourne, les corrélations sont trop
      faibles). Quelques `vote_non_conclu` ne sont pas une panne : sur le board synthétique une
      fenêtre peut franchir 0,26/0,09 par hasard et échouer ensuite au vote. Si c'est
      `sans_reference` qui monte, **l'horloge n'arrive pas** — l'émetteur publie sous un autre nom,
      ou il n'est pas lancé. Les deux ressemblent à « ça ne détecte pas » et appellent des gestes
      opposés ; c'est exactement ce que ces compteurs existent pour séparer. (Les quatre causes et
      les quatre gestes sont tabulés une seule fois, au **2.9** — ce sont les mêmes compteurs.)
- [ ] Fermer l'émetteur (ESC) sans arrêter le mode. Après ~3 s, `reference_perimee` se met à monter
      à la place : l'horloge s'est tue et le moteur cesse de décoder plutôt que de continuer en roue
      libre. Relancer l'émetteur → ça repart tout seul.
- [ ] Relancer l'émetteur avec **`--refresh 75`**. Attendu : le moteur **refuse tous les marqueurs**,
      le dit en nommant les deux rafraîchissements, et **`marqueurs_refuses` monte** (annoncé à 1,
      10, 100…). ⚠️ **C'est ce compteur-là, et lui seul, qui identifie ce cas.** ⚠️ **Le mode ne
      s'arrête pas pour autant** : il continue de tourner et de publier -1, sous
      **`reference_perimee`** — pas `sans_reference`. L'horloge valide du point précédent est
      encore en mémoire (un marqueur refusé ne l'efface pas) ; elle expire au bout de 3,15 s et
      c'est `reference_perimee` qui monte ensuite, indéfiniment. Ce serait `sans_reference`
      seulement si le mode venait d'être redémarré. Ne suis pas le geste que la table du 2.9
      associe à `reference_perimee` (« relance l'émetteur ») : ici il est déjà lancé, et c'est son
      `--refresh` qui est en cause. Le refus est délibéré — un moteur qui s'arrêterait emmènerait
      les autres modes avec lui. Ne guette pas un plantage : lis les premières lignes du terminal.
- [ ] Sur la page c-VEP, changer **« Corrélation minimale »** de 0,26 à 0,05 puis **Appliquer**.
      Attendu, et c'est la différence avec le réglage ErrP du 1.15 : le terminal écrit « sans effet
      sur le décodage : ni repos refait, ni flux recréé », **le flux n'est PAS recréé** et ton
      `receiver.py` du terminal 3 continue de recevoir sans rien relancer. Le seuil bas fait sortir
      des cibles au hasard : c'est normal, et c'est le but — on vérifie que le réglage mord.
- [ ] Toujours dans le terminal 3, les deux dernières voies **`corr_min` et `margin` ont suivi**
      (0,05 sur la première), alors que les métadonnées du flux, elles, portent encore 0,26. Les
      deux disent bien deux choses différentes : la métadonnée décrit le réglage **à l'ouverture**
      du flux, la voie celui **en vigueur pour cet échantillon**. C'est ce qui permet de dépouiller
      un enregistrement six mois plus tard sans sa description LSL. Remettre 0,26 avant de partir.

### 1.17 — L'écran de départ, et l'absence de repli

⚠️ **Nouveau le 2026-09-09, jamais joué à l'écran.** C'est le seul test du niveau 1 qui se lance
**sans `--synthetic`** — puisque c'est précisément le drapeau que cet écran remplace.

```bash
python src/console/app.py
```

- [ ] Une fenêtre s'ouvre AVANT la console : « sur quoi ouvrir la session ? », deux choix, casque
      Unicorn ou board de test. Chacun est décrit ; celui du board dit franchement que le signal est
      **FABRIQUÉ** et ne sert jamais à mesurer quoi que ce soit.
- [ ] Choisir le **board de test** → la console s'ouvre, et le **bandeau du haut annonce la source
      en permanence**. C'est le point : un board de test qu'on oublie est une séance entière de faux
      signal prise pour du vrai.
- [ ] Fermer la fenêtre de choix sans rien choisir (croix ou Échap) → **la console ne démarre pas**,
      et le terminal le dit. Ouvrir « par défaut » sur l'un des deux serait le repli silencieux que
      cet écran existe pour interdire, avec un clic de moins.
- [ ] ⚠️ **Le point qui demande un casque, donc à faire au niveau 2** : choisir **Unicorn** alors
      qu'aucun casque n'est appairé. Attendu — la console **ne bascule PAS** en synthétique. Un
      basculement silencieux ferait enregistrer une séance entière de signal fabriqué ; il n'en
      existe aucun dans le code, c'est vérifié.

      Ce qui se passe alors, très exactement (**corrigé le 2026-09-10 — cette case promettait
      jusque-là un écran qui n'existe pas**) : `prepare_session()` lève dans le **fil du moteur**,
      qui meurt. Le bandeau du haut affiche en rouge **« ⛔ LE MOTEUR S'EST ARRÊTÉ »** avec la
      cause la plus fréquente, et **les σ cessent d'annoncer un tampon qui ne viendra jamais**. Le
      message exact de BrainFlow, lui, est dans le terminal.

      ⚠️ ~~La console ne repropose PAS le choix~~ → **depuis le 2026-09-25, elle le repropose** :
      elle attend l'ouverture du casque AVANT de s'afficher, et un échec rouvre l'écran de départ
      avec la raison, le casque toujours coché (`console/app.py:ouvrir_session`, tenu par le
      smoke). Le bandeau rouge ne sert plus qu'à une liaison perdue en cours de séance. Le numéro
      de série se choisit dans ce même écran. **Note ce qui s'est passé.**

### 1.18 — « Ce que voit ton application », et l'enregistrement

✅ **Joué à l'écran le 2026-09-23** (QA 1.11, les trois étapes), après une trace du 2026-09-21 : un
enregistrement de 45 verdicts dans `seances/`. La passe du 23 y a trouvé un défaut : le flux affiché
dans la liste n'était pas ouvert, et le panneau restait vide jusqu'à un clic dessus. Corrigé le jour
même, sous assertion. Cette page répond à la seule question qu'un
étudiant se pose une fois son décodage lancé — *est-ce que mon appli reçoit quelque chose ?* — et à
laquelle la console ne savait pas répondre.

```bash
python src/console/app.py --synthetic --mode ssvep
```

- [ ] En bas de la grille, un bouton **« Ce que voit ton application »**. Le cliquer → la page liste
      les flux LSL trouvés **sur le réseau**, les nôtres en tête.
- [ ] Choisir `EEG_API_Unicorn_decoded_ssvep` → les **noms de voies** s'affichent
      (`target_index`, `freq_hz`, `confidence`, `score_*`) et des valeurs défilent. ⚠️ Attends la
      fin de la chauffe et du repos (~23 s) : le flux décodé n'est créé qu'à ce moment-là.
- [ ] **LE point de ce test, et il tient en une case à cocher.** Retourner à la grille, **décocher
      « publié » sur la tuile SSVEP** (le mode continue de décoder, seule la diffusion s'arrête),
      revenir sur la page de flux et **relancer « Chercher les flux »**. Attendu :
      `decoded_ssvep` a **disparu de la liste**, et l'absence se **DIT** plutôt que de laisser un
      panneau vide. Le moteur, lui, décode toujours — si le panneau montrait encore quelque chose,
      c'est qu'il lirait l'état interne au lieu du réseau, et il afficherait alors des données
      pendant qu'aucun client ne reçoit rien. C'est exactement la panne qu'on vient regarder ici.
      Recocher « publié » → le flux revient.
- [ ] Cliquer **« Enregistrer les verdicts »**. La page affiche **où** ça écrit — un `.jsonl` dans
      `seances/`, à la racine du dépôt, **jamais dans `data/`**.
      ⚠️ Le refus est explicite si le mode n'est **pas démarré** : un fichier vide se relirait après
      coup comme une séance ratée, pas comme un mode qu'on avait oublié de lancer.
- [ ] Laisser tourner une minute, cliquer **« Arrêter l'enregistrement »**, puis ouvrir le fichier.
      Attendu : une ligne `header` (le flux, le mode, les voies, les réglages en vigueur), N lignes
      `verdict` avec un `t` en horloge LSL, une ligne `fin` avec le compte.
- [ ] ⚠️ **Une ligne par décision PUBLIÉE, pas par tour de boucle.** Sur un mode qui n'émet que
      44 % du temps — le régime normal du SSVEP — un fichier qui compterait les tours se relirait à
      100 %, et il mentirait sur la seule grandeur qu'on vient y chercher.
- [ ] Vérifier que `data/` n'a **rien** gagné (`Get-ChildItem data | Measure-Object`, avant et
      après). Un verdict de séance n'est ni un modèle ni un enregistrement EEG.

### 1.19 — La page d'un mode : ses gestes numérotés, et pas un de plus

⚠️ **Nouveau le 2026-09-22, jamais joué à l'écran** — vérifié hors écran par `console/app.py
--smoke`.

**Pourquoi.** L'ancienne page mettait à plat « Démarrer », « Calibrer » et « Lancer le stimulus »,
comme trois gestes de même rang qu'on choisit librement. Il existe pourtant un ORDRE, et en sauter
un rend les autres inutiles sans que rien ne le dise : à la séance du 2026-09-22, le stimulus a
tourné sur un mode arrêté, et dix minutes de fixation se sont perdues dans le vide. La boucle
réelle d'un étudiant est **régler → tester → ajuster → re-tester**, plusieurs fois (exemple donné
en séance : ça marche à 60 Hz, son application Unity ne tiendra que 30 fps, il revient, déclare
30, adapte les fréquences, re-teste). La page ne porte donc plus que cette boucle.

| Page | Blocs |
|---|---|
| SSVEP | 1. Régler · 2. Tester |
| c-VEP, P300, ErrP, Motor Imagery | 1. Régler · 2. Entraîner · 3. Tester |
| Neuro, Brut | 1. Régler · 2. Observer |

La forme est tirée du **contrat**, jamais d'une liste de l'interface : une `calibration` déclarée
donne « Entraîner », un `test_id` donne « Tester », ni l'un ni l'autre donne « Observer ». Le
**Neuro et le Brut n'ont aucune vérité-terrain** — il n'y a pas de bonne réponse à comparer —, donc
ni Entraîner ni Tester : on regarde, et **aucun chiffre de justesse n'est annoncé**. Le Neuro a un
bouton « Observer » qui démarre le mode, dont le libellé suit l'état REÇU du moteur ; le Brut n'en a
pas, ses tracés lisent le tampon d'acquisition.

- [ ] Les blocs de la table, dans cet ordre, et aucun autre bouton : **ni « Démarrer », ni « Lancer
      le stimulus », ni « Journal de séance », ni « Brancher un client »**. Ils reviendront avec
      « Connecter » (second chantier) ; la machinerie de la console qui les servait est restée, et
      l'autotest l'exerce encore par appel direct pour qu'elle ne pourrisse pas.
- [ ] Sur une page qui a « Tester », la vue en direct est **repliée, pas supprimée** : une case
      « Décodage en direct », décochée, qui la déplie avec l'état du mode. Cachée sans case pour
      l'ouvrir, elle serait un widget testé que personne ne peut voir. L'en-tête de ces pages
      n'affiche plus « arrêté » : ce mot laissait croire qu'il fallait démarrer quelque chose avant
      de tester.
- [ ] **« Mesurer »** à côté du « Pic alpha de la personne » (page SSVEP) ouvre la page du contrôle
      alpha — la même que la tuile « Vérifier le casque » : deux portes, un seul runtime. La page ne
      nomme aucune mesure : c'est le MOTEUR qui déclare quelle mesure sait remplir quel réglage
      (`ControleAlpha.REGLAGE_PRODUIT = ("ssvep", "alpha_hz")`), et le `reglage_propose` du résultat
      est construit sur la même déclaration — la porte d'entrée et la valeur qui revient ne peuvent
      pas viser deux champs différents.
- [ ] Le **« ← »** d'une page de test, de mesure ouverte par « Mesurer », ou d'entraînement ramène
      au MODE d'où l'on vient (« ← SSVEP », « ← P300 »…), pas à l'accueil : la boucle ne passe pas
      par la grille. Ouverte depuis la tuile, la page de « Vérifier le casque » garde « ← Modes ».

⚠️ **Ce que la page a perdu, et que rien ne remplace encore** : la séance c-VEP avec journal (2.9)
et le décodage continu avec NOTRE fenêtre de stimulus n'ont plus de chemin dans la console (cf.
l'en-tête de ce document). Le bloc « Brancher un client » non plus (1.6).

> Prouvé par mutation (`d111305`, `abbf600`, `5d12710`) : case « Décodage en direct » débranchée,
> libellé « Observer » figé, « ← » toujours vers l'accueil, corps de page plafonné à 300 px, aucune
> mesure qui remplit le champ, réglages retenus non relus sur un mode arrêté, libellé « Contrôle
> alpha » remis. Le retour du pic mesuré dans le champ est vérifié contre le VRAI moteur (9 Hz
> retenus, « Mesurer », 10,5 Hz appliqués, « ← » : le champ montre 10,5) — un état fabriqué ne
> prouverait que ce qu'on y a mis.

### 1.20 — « Tester » : un bouton qui possède sa séquence entière

⚠️ **Nouveau le 2026-09-22. Aucun des cinq tests n'a vu un casque** — ils sont nés après la séance.

**Pourquoi un seul bouton.** Un bouton qui possède toute la séquence — appliquer, arrêter le mode,
lancer la mesure, ouvrir la fenêtre, conclure, la fermer — rend le piège du 2026-09-22
**impossible**, au lieu de le signaler : il n'y a plus d'ordre à respecter, il n'y a plus qu'un
geste. Et c'est le **protocole d'entraînement rejoué avec un autre consommateur** : la fenêtre
désigne la cible et publie sa vérité-terrain comme pour entraîner, le moteur DÉCIDE au lieu
d'apprendre. Rien de neuf à afficher, rien de neuf à publier.

La séquence, dans l'ordre où le code la joue :

1. **« Tester » applique ce qui est à l'écran** (`set_params`, comme « Appliquer »). Refusé (17 Hz
   ne divise pas 60) → le refus s'affiche sous « 1. Régler » et le test ne s'ouvre pas : tester
   une configuration impossible ne mesurerait rien. *Avant `fcbbd45`, on changeait une fréquence,
   on cliquait « Tester » sans « Appliquer », et c'était l'ANCIENNE configuration qui était testée
   sans que rien ne le dise — le piège exact de la boucle régler → tester.*
2. **La page du test s'ouvre pré-remplie** avec les réglages du mode, pour chaque clé qu'ils
   partagent (modèle, seuils…), après avoir relu les listes de modèles — sinon un modèle tout juste
   entraîné serait ignoré en silence par la liste déroulante. Les réglages du test SONT ceux du
   mode (mêmes objets `Param`) plus une longueur : sans modèle, c'est le moteur qui refuse, avec la
   raison du mode. L'ordre Entraîner → Tester est donc tenu par un refus, pas par l'écran.
3. **« Commencer » → contrôle de liaison.**
4. **Le mode testé est arrêté s'il tourne**, et le test attend de le voir disparaître de l'état
   avant de partir. Règle uniforme, SSVEP compris : la console ne recopie pas la table des conflits
   du moteur. Le mode **reste arrêté** après le test.
5. **`start_mesure` D'ABORD, la fenêtre ENSUITE**, et seulement quand la mesure apparaît dans
   `snapshot()` — l'accusé ne promet qu'une mise en file.
6. **La fenêtre part avec les réglages du MODE** : `--guide` (SSVEP) ou `--tester` (P300, ErrP,
   c-VEP : le protocole de `--calibrer`, mais une fenêtre qui dit « TEST » et « le moteur note »),
   `--freqs` du mode pour le SSVEP (`b1e4446` — lancée avec `--guide` seul, elle affichait le trio
   du dépôt quel que soit le réglage : un « Tester » qui ne testait pas ta configuration), et la
   longueur dans **l'unité de SA fenêtre** (`stimulus/registry.py`, `COMPTES`) : `--rounds` des
   manches, `--essais` des pas, `--cycles` des cycles enregistrés **par cible**. Une valeur dans la
   mauvaise unité ne lève rien : la séance est juste plus courte ou plus longue que l'écran ne le
   dit. Le MI n'a pas de fenêtre : le moteur mène, avec les étapes et le **top latéralisé** de
   l'entraînement.
7. **Le verdict**, en trois lignes (1.21). **Rien n'est écrit sur le disque.**

**Côté moteur, un refus de plus** (`b72ca54`) : un mode et son TEST ne tournent jamais ensemble,
dans les deux sens, à la soumission ET dans la boucle. Un test à fenêtre lit les marqueurs sous
l'identifiant du MODE, et le moteur n'y tient qu'un curseur : chacun n'en verrait qu'une partie, et
le score serait plausible et faux. Un mode qui ne lit aucun marqueur (le SSVEP) n'est pas concerné.

**Les cinq tests** — la décision est toujours celle du **mode**, jamais réécrite ; les autotests du
MI, du P300, du c-VEP et de l'ErrP la comparent, essai par essai, à celle d'un vrai runtime du mode :

| Test | Un essai = | Hasard | Par défaut | Vert quand (sinon orange ; rouge si le binomial exact ne rejette pas le hasard à p < 0,05) |
|---|---|---|---|---|
| SSVEP (`ssvep_mesure.py`) | un essai guidé, UNE décision | 1 / nombre de cibles | 36 essais, ≈ 3,6 min | justesse ≥ 90 % **et** émission ≥ 44 % |
| MI (`mi_test.py`) | un essai ; la DERNIÈRE sortie | 1 / classes du modèle | 6/classe, ≈ 2,8 min | justesse ≥ 40,0 % (3 cl.) ou 63,3 % (G/D) **et** émission ≥ 44 % |
| P300 (`p300_test.py`) | une manche | 1/6 | 6 manches, ≈ 1,2 min | ≥ 80 % — les seuils de la table d'entraînement (`p300_calib.VERDICTS`), rouge sous 60 % |
| c-VEP (`cvep_test.py`) | un bloc ; la dernière sortie votée | 1/6 | 3 cycles/cible = 18 blocs, ≈ 1,8 min | justesse ≥ 71 % **et** émission ≥ 46 % — le repère EN DIRECT |
| ErrP (`errp_test.py`) | un feedback | la diagonale : autant d'erreurs attrapées que de bonnes commandes annulées | 80 essais, ≈ 2,4 min | Fisher exact unilatéral p < 0,05, écart TPR − (1 − TNR) ≥ 0,355, et moins de 50 % sans verdict |

- **Un `-1` n'est jamais une bonne réponse.** Au MI, au SSVEP et au c-VEP c'est un silence : il
  compte dans le taux d'émission, pas comme une erreur (et au MI, jamais comme REPOS, que
  `classes[-1]` désignerait). Au P300 c'est une sélection RATÉE (marge nulle : une perte, pas une
  abstention). À l'ErrP il est compté à part, ni erreur attrapée ni bonne commande gardée.
- 🔴 **La cloison de l'ErrP.** Son étiquette voyage sur le `feedback`, et un test en a besoin pour
  NOTER. Le socle (`mesure_marqueurs.py`) la retire d'une copie du marqueur avant que le test ne le
  voie, et ne la rend qu'au correcteur, APRÈS la décision ; le décodeur ne reçoit jamais le moteur
  — dont la file de marqueurs garde les feedbacks étiquetés — mais une vue du seul tampon EEG. Une
  fuite donnerait un score parfait et faux, en silence : c'est tenu par un test espion, pas par la
  relecture.
- **Le test tourne sur TES réglages, donc il se compare moins bien aux repères du projet.** C'est
  voulu — un « Tester » qui ne teste pas ta configuration ne sert à rien — et c'est dit dans
  « Détails ». Pour comparer au 100 %/44 % du SSVEP, teste sur le trio du dépôt (2.2).
- **Le repos de référence de l'ErrP** (son rejet d'artefact) est pris sur la piste immobile, entre
  la chauffe du moteur et le premier pas, et clos au premier pas s'il n'a pas eu ses 8 s. Sa durée
  réelle, estimée à 2-5 s et jamais mesurée, est calculée (`resultat["repos"]`) mais **aucun écran
  ne l'affiche**.
- **Au c-VEP, un système exactement AU repère ne sort vert qu'environ une fois sur quatre** à 18
  blocs (calcul binomial de l'auteur, pas une mesure) : orange est l'issue attendue au repère.

Ce que ce test ne remplace PAS : l'A-B-A du 2.9 (réseau contre local) et la séance longue avec
journal. Il dit si une configuration tient, pas d'où vient un écart.

### 1.21 — Un résultat se lit en trois lignes

⚠️ **Nouveau le 2026-09-22**, sur les pages d'entraînement ET de test.

**Pourquoi.** À la séance du 2026-09-22, l'écran de résultat du c-VEP enterrait « 25,0 % pour un
hasard à 17 % » au milieu d'une phrase, après une subordonnée sur McNemar, elle-même après le
conseil de resaliner ; suivaient le nom du fichier et six lignes grises. Tout y était vrai, rien
n'était lisible — mot pour mot : « c'est pas clair du tout et beaucoup trop verbeux ».

- [ ] **En face, trois lignes** : un **mot** coloré (vert / orange / rouge), les **chiffres** avec
      leur point de comparaison (« 38 % … (hasard 17 %) sur 90 essais », jamais un pourcentage
      seul), et **une** réserve — la phrase qui changerait la décision qu'on s'apprête à prendre.
- [ ] **Derrière « Détails »**, décoché : la phrase de verdict complète, les tests statistiques,
      les repères historiques, le nom du fichier, la phrase d'honnêteté. **Rangées, pas
      supprimées** : chacune a été écrite après une conclusion fausse réellement tirée sur ce
      projet. Une fois cochée, la case **reste** cochée ; un NOUVEAU résultat repart replié.
      *(Corrigé par `07a3303`, trouvé par la revue de branche : chaque rafraîchissement — dix par
      seconde — décochait la case, le repli se refermait au bout de 100 ms, et « rangé, pas
      supprimé » ne tenait pas. L'autotest restait vert : il cochait puis lisait, sans
      rafraîchissement entre les deux.)*
- [ ] Un entraînement réussi porte toujours la même réserve : « Chiffre calculé sur les essais
      d'entraînement : c'est « Tester » qui dira ce que le mode fait vraiment. » (au c-VEP : 59,5 %
      hors ligne, 46 % d'émission en direct).
- [ ] Un abandon (séance interrompue, calcul impossible) s'affiche **en face, en gris** : pas de
      verdict, donc pas de couleur.

⚠️ **Le niveau est décidé par le MOTEUR** (`core/modes/affichage.py`), par la MÊME table que la
phrase de verdict, dans le même appel. Une couleur déduite du texte ou d'un pourcentage côté écran
serait une seconde table de seuils, qui peindrait un jour en vert ce que le moteur juge faible. La
console ne fait que peindre `niveau` ; `affichage.verifier`, appelé par l'autotest de chaque
producteur, exige que le mot OUVRE la phrase de verdict (sinon deux calculs ont divergé) et qu'aucun
pourcentage ne soit seul. Trois mots ne se confondent pas, parce qu'ils ne se corrigent pas pareil :
**FAIBLE** (mesuré, et pas utilisable en l'état), **NON MESURÉ** (rien à calculer), **MUET**
(le moteur s'est tu) — et c'est la réserve qui dit quoi reprendre dans chaque cas.

> 🐛 **Trouvé en repliant** (`c3471f0`) : la raison d'un abandon vivait dans un label que le repli a
> caché, et l'autotest restait vert parce qu'il lisait le TEXTE du label, jamais s'il était VISIBLE.
> Corrigé sur les deux pages, et les assertions vérifient désormais la visibilité. Écart assumé à la
> spec : les pages d'entraînement et de test n'ont PAS été fusionnées en une seule (refactor
> invisible, gros risque) ; ce que l'étudiant voit — une seule façon de lire un résultat — est livré.

---

## Niveau 2 — au casque

⚠️ Casque salé, contact vérifié, une seule application ouverte, aucun `python` résiduel.

### 2.1 — Ton pic alpha (à faire en premier : tout le reste en dépend)

⚠️ **Ce test ne se tape plus, il se clique** (2026-09-09). C'était `python src/research/alpha_check.py` ;
c'est maintenant une **page de la console**, et le protocole est joué par le moteur. Le script
existe encore, archivé en `archive/alpha_check.py`, et il n'y a **aucune raison de le lancer** : il
ouvrirait le casque une seconde fois.

**Le protocole n'a pas changé d'un pouce** — 8 s les yeux ouverts, 8 s les yeux fermés, bande
8-12 Hz, repère **ratio > ~1,5**. C'est délibéré : le repère a été observé sous CES durées, et
raccourcir une phase diviserait la résolution spectrale par deux en continuant d'afficher un
verdict avec le même aplomb. C'est aussi pourquoi cette mesure **n'expose aucun réglage**.

```bash
python src/console/app.py
```

Grille → seconde rangée, **« Avant tout »** → tuile **« Vérifier le casque »** (elle
s'appelait « Contrôle alpha » jusqu'au 2026-09-22), marquée **BARRIÈRE — à passer avant tout le reste**
→ **Ouvrir** → lire le briefing → **Commencer**. C'est aussi la page qu'ouvre **« Mesurer »**, à
côté du « Pic alpha de la personne » de la page SSVEP : deux portes, un seul protocole — la première
dit si la séance peut continuer, la seconde sert à trouver un réglage. Ouverte par « Mesurer », son
« ← SSVEP » ramène sur la page du SSVEP.

- [ ] La console passe d'abord par le **contrôle de liaison**, comme pour une calibration. C'est
      utile ici pour une raison propre : une voie débranchée s'y refuse en 2 s au lieu de 37.
- [ ] **Un TOP SONORE annonce chaque changement d'étape**, et il y en a cinq. Le dernier est le plus
      important : il n'annonce pas une étape mais la **fin** des yeux fermés — c'est le seul signal
      qui dise de rouvrir les yeux. Si la machine n'a pas de son, la page le **dit** : dans ce cas,
      fais-toi assister, ou renonce à ce test. ⚠️ La chauffe, elle, ne sonne pas.
- [ ] Mâchoire relâchée : un serrement de dents noie la bande alpha sous de l'EMG et le ratio
      devient illisible. Yeux ouverts, fixe un point ; yeux fermés, sans serrer les paupières.
- [ ] **Le verdict.** Il porte le **ratio** et le **pic**, et il est moyenné sur les quatre voies
      occipitales que le moteur nomme lui-même — **Pz, PO7, Oz, PO8** (`OCCIPITAL`). ⚠️ L'écran
      d'origine imprimait « PO7/Oz/PO8 » alors qu'il en moyennait quatre : la phrase avait cessé
      d'être vraie le jour où Pz a rejoint la liste, sans que rien ne le signale.
      Ratio : ______ (repère > ~1,5) · pic : ______ Hz.
- [ ] **Si la barrière n'est pas franchie, ARRÊTE LA SÉANCE ICI.** Le mot en face le dit en rouge
      — **« ARRÊTE ICI »** (depuis le 2026-09-22 ; la ligne « BARRIÈRE NON FRANCHIE » est rangée
      sous « Détails ») — et la réserve nomme les gestes : électrodes occipitales, mastoïdes,
      saline. Aucun autre test du niveau 2 ne veut rien dire sans alpha. Quand elle passe, le mot
      est **« ALPHA NET »**, en vert.
- [ ] **La boucle se ferme d'un clic** : quand la barrière passe, un bouton apparaît, du genre
      `Appliquer « Pic alpha de la personne » = 10.5 Hz à « SSVEP »` — la phrase est **composée
      par le moteur**, qui nomme lui-même le mode et le réglage. Le clic envoie `set_params` : la
      valeur ne se note plus sur un carnet pour être retapée dans un autre écran. ⚠️ Rien n'est
      proposé quand la barrière échoue, et c'est voulu : sur un signal sans alpha, le « pic » n'est
      que le plus grand bin d'un spectre de bruit. Le SSVEP n'a **pas** besoin de tourner : depuis
      le 2026-09-21, `set_params` valide et RETIENT un réglage sur un mode arrêté (réponse en vert).
      *Jusque-là ce bouton échouait à tous les coups, par « « SSVEP » n'est pas démarré » — ce
      contrôle est le premier geste d'une séance. Trouvé par la QA du 2026-09-21.*
- [ ] Sur la page SSVEP (« ← SSVEP » si tu es venu par « Mesurer »), le champ montre le pic
      appliqué ; cliquer **Proposer « Fréquences des cibles »** et noter le jeu obtenu : ______ . S'il diffère de
      8,571/15/20, c'est attendu et c'est tout l'intérêt du réglage.

### 2.2 — Non-régression du SSVEP

Le seul point où une régression silencieuse coûterait vraiment cher. Référence mesurée le
2026-07-27 : **100 % de justesse quand le moteur émet (0 confusion sur 36 essais), mais il n'émet
que 44 % du temps**.

⚠️ **Ce test ne se tape plus non plus** (2026-09-09). C'était `python src/research/ssvep_guided.py`,
un monolithe qui affichait, acquérait et analysait. Il est coupé en deux : la **fenêtre**
(`src/stimulus/ssvep.py --guide`, qui désigne la cible) et la **mesure** (`core/modes/ssvep_mesure.py`,
qui décide et compte), et la console lance les deux. `research/ssvep_guided.py` existe toujours,
réduit à sa moitié d'analyse : il **rejoue un run archivé** avec d'autres réglages, sans casque.

⚠️ **Et depuis le 2026-09-22, c'est le « Tester » de la page SSVEP.** La tuile « Taux d'émission
SSVEP » a quitté l'accueil : une mesure qui éprouve UN mode vit sur la page de ce mode. Même
protocole, même moteur, même règle « un essai = une décision » — à une différence près, qui compte
pour lire le chiffre : **le test tourne sur les fréquences RETENUES du mode** (`--freqs`, `b1e4446`),
et plus sur le trio du dépôt quel que soit le réglage.

Page **SSVEP** → « 1. Régler » : ton pic alpha (2.1) et tes fréquences → **« Tester »** (il applique
d'abord ce qui est à l'écran) → **Commencer**. Une seconde fenêtre s'ouvre et fait clignoter les
cibles du réglage du mode — **trois** au défaut du dépôt (AVANT 15 Hz, GAUCHE 20 Hz, DROITE
8,571 Hz), chaque flèche portant sa fréquence à l'écran ; **3,6 min** au total (15 s de chauffe, 12 s
de repos, 12 essais par cible soit **36**). La longueur ne se règle pas.

⚠️ **Pour comparer au repère ci-dessus, teste sur le trio du dépôt (15 · 20 · 8,571)** : c'est sous
lui que le 100 %/44 % a été mesuré. Sur un autre jeu, le chiffre décrit TA configuration — c'est le
but du bouton — mais il ne se compare plus. Et si ton pic alpha est sous ~10,5 Hz, la cible à
8,571 Hz tombe dans ta bande alpha : c'est une propriété du TRIO, pas du moteur (le 2026-09-21, pic à
10 Hz, le 100 % a tenu quand même).

*(Le 🐛 qui figurait ici — un briefing qui annonçait « quatre » flèches — ne s'applique plus : le
briefing actuel ne compte pas les flèches.)*

- [ ] ⚠️ **Fixe la flèche entourée de bleu**, dans la fenêtre de stimulus — pas la console, qui n'a
      rien à montrer pendant ce temps. Pendant le REPOS du début, fixe la **croix centrale** et ne
      suis **aucune** flèche : c'est là que le moteur mesure son fond de corrélation, et le suivre
      fausserait tout ce qui vient après.
- [ ] ⚠️ **Ne ferme pas la fenêtre de stimulus à la main.** Sans son marqueur de fin, aucun verdict
      n'est calculé — un taux sur séance tronquée serait indiscernable d'un taux complet.
- [ ] Justesse quand le moteur émet : ______ % (référence : 100 %).
- [ ] Taux d'émission : ______ % (référence : 44 %).
- [ ] **Les deux chiffres se lisent ENSEMBLE**, et la page les met sur la même ligne. Le taux seul
      fait passer un régime parfaitement normal pour une panne ; la justesse seule fait croire à un
      sans-faute. Un long silence entre deux verdicts justes **est** le régime normal de ce mode.
- [ ] **Le mot en face** (depuis le 2026-09-22, mêmes mots que le test du MI) : **AU NIVEAU DU
      REPÈRE** (vert) si la justesse atteint 90 % **et** l'émission 44 %, le hasard étant rejeté ;
      **UTILISABLE** (orange) au-dessus du hasard sans les deux ; **FAIBLE** (rouge) si le test
      binomial exact ne rejette PAS le hasard (p ≥ 0,05) ; **MUET** (rouge) si le moteur n'a rien
      annoncé. La séance
      du 2026-09-22 — 18 annonces sur 36, les 18 justes — se lirait en vert.
- [ ] ⚠️ **L'effectif annoncé est un nombre d'ESSAIS, pas de fenêtres.** Les fenêtres du moteur se
      chevauchent (1,5 s toutes les 0,2 s), donc une fixation en contient sept ou huit ; les compter
      gonflerait l'effectif d'un facteur ~7 et rétrécirait l'intervalle de confiance de √7, sans
      apporter une seule observation. L'intervalle affiché doit être **large** à n = 36 : s'il est
      étroit, c'est le défaut que cette mesure existe pour éviter.
- [ ] Aucun avertissement « cible quasi INDÉTECTABLE » au démarrage. S'il apparaît, le plancher de
      repos est trop bruité : re-saliner, revérifier les mastoïdes, refaire la chauffe.

> 🔴 **Ce test DÉCIDE PAR LE RUNTIME DU MODE depuis le 2026-09-22, et ça change ce qu'on peut
> comparer.** Jusque-là il réécrivait la règle du mode, avec un écart : le σ du rejet d'artefact
> pris sur les **8** voies ici, sur les **4 occipitales filtrées** par le mode qui décode en
> direct. Un clignement frontal fort (que Fz voit et qu'Oz voit peu) faisait rejeter au test un
> essai que le mode décode — taux **sous-estimé** ; un artefact de nuque, dilué dans 8 voies,
> passait ici et pas dans le mode — **sur-estimé**. Il passe désormais par
> `SsvepRuntime._rest_step` / `._run_step`, donc un correctif futur du mode est mesuré sans une
> ligne à reporter.
> ⚠️ **Le prix, à connaître AVANT de citer un taux** : l'écart était **antérieur**
> (`ssvep_guided.py` mesurait déjà son σ ainsi), donc c'est sous l'ANCIENNE règle que le
> 100 %/44 % du 2026-07-27 a été obtenu. **Les chiffres rendus aujourd'hui ne s'y comparent plus
> tels quels.** La spec du chantier « Configurer · Entraîner · Tester » (§4, §9) a tranché dans ce
> sens : un test décide comme le produit, la comparabilité est une note — elle est dans le texte
> d'honnêteté du résultat, sous « Détails ».

### 2.3 — Le cumul sous charge réelle

Deux décodeurs sur le même tampon est trivial en synthétique. Ce qui ne l'est pas : la charge CPU et
son effet sur la cadence d'acquisition.

**L'un APRÈS l'autre, jamais en même temps** — deux moteurs publient sous les mêmes noms de flux.

```bash
python src/core/server.py --mode ssvep --duration 120
python src/core/server.py --mode ssvep,neuro --duration 120
```

- [ ] Relever la ligne de fin (`échantillons publiés … Hz effectif`) des deux runs :
      un mode ______ Hz, deux modes ______ Hz.
- [ ] Attendu : les deux proches de 250 Hz. Un écart net signifie que la boucle n'absorbe pas deux
      décodeurs → il faudra espacer les `period_s`.

  Référence en synthétique, mesurée le 2026-07-29 avec un seul mode :
  `18741 échantillons publiés en 75.1 s (249.6 Hz effectif)`.

> ⚠️ **Un bruit de sortie à ne pas confondre avec une panne.** Après la ligne d'arrêt, BrainFlow
> peut afficher `ctypes.ArgumentError … Python is likely shutting down`, venant de son finaliseur
> `BoardShim.__del__` exécuté trop tard pendant l'extinction de l'interpréteur. Observé le
> 2026-07-29 avec un **code de sortie 0** et un arrêt propre. Ça n'invalide aucun relevé.

### 2.4 — Le repos partagé, vécu

Refaire le test 1.7, mais au casque et en le vivant : la consigne doit être tenable pendant 25 s
sans que tu te demandes ce que tu es censé faire.

- [ ] Une seule consigne, compréhensible sans explication extérieure.
- [ ] Les deux modes décodent à la fin.

### 2.5 — Le mode neuro, jamais validé au casque

⚠️ Le mode neuro **publie** depuis le 2026-07-27, mais **son contenu n'a jamais été vérifié sur
casque**. Il sort des indices, personne n'a confirmé qu'ils veulent dire quelque chose.

- [ ] Ouvrir sa page pendant qu'il tourne, et regarder les indices bouger dans un sens plausible
      (yeux fermés, calcul mental, relâchement). Ce n'est **pas** une validation — c'est un premier
      regard, à consigner tel quel.

### 2.6 — Motor Imagery : calibrer PUIS décoder, dans la MÊME console

C'est le chemin complet du chantier : une calibration écrit un modèle dans `data/`, la même
console le propose, le charge et publie `decoded_mi`. Chaque bout a été testé séparément ; les
trois ensemble, sur une tête, jamais.

Ce que ce chantier a changé : la calibration est maintenant **jouée par le moteur** et affichée
par la console elle-même, sur sa page Motor Imagery — plus de bascule entre deux programmes pour
cette étape, donc plus de risque de saturation C3/Cz à la réouverture rien que pour calibrer.

```bash
python src/console/app.py --mode mi
```

- [ ] Ouvrir **Motor Imagery** → bloc **« 2. Entraîner »** → **Entraîner** (le bouton s'appelait
      « Calibrer » jusqu'au 2026-09-22) → briefing, réglages, **Commencer**.
      ⚠️ **Depuis le 2026-09-08 un écran s'intercale entre « Commencer » et le lancement : le
      CONTRÔLE DE LIAISON.** Il montre le σ des huit voies, surligne les voies clés du mode
      (C3, Cz, C4 — elles viennent du contrat, `ModeSpec.key_channels`, pas d'une liste écrite dans
      l'interface) et **REFUSE de lancer** si une seule des huit sort de [0,5 ; 500] µV, ou si la
      référence a décroché. **Il n'y a aucune porte de sortie** — c'est délibéré, et c'est le point
      du test à trancher ici : si une électrode refuse de descendre sous le seuil malgré la saline,
      la console devient inutilisable. **Note ce qui s'est passé**, c'est la seule mesure qui puisse
      arbitrer.
- [ ] ⚠️ **Si le mode MI décodait déjà, la console l'ARRÊTE avant d'ouvrir la calibration**, et le
      dit. C'est une règle uniforme (elle vaut pour les quatre modes, même quand le moteur ne
      l'exigerait pas), et la conséquence visible est qu'il faudra le **redémarrer** depuis la grille
      ensuite — ce qu'on ferait de toute façon, pour prendre le nouveau modèle.
- [ ] La page affiche la consigne en cours (GAUCHE / DROITE / REPOS), l'essai en cours et le temps
      restant — 5 à 7 min par défaut, fatigant : sujet frais.
- [ ] La calibration va au bout et affiche son accuracy. Noter : ______ %.
- [ ] ⚠️ **Rien n'est encore écrit sur le disque.** Deux boutons apparaissent : **Enregistrer le
      modèle** et **Refaire**. C'est le geste qui a changé le 2026-09-08 : avant, une calibration
      sauvegardait PUIS annonçait sa précision, et comme le moteur propose le modèle chargeable le
      plus récent, une séance ratée devenait le défaut en silence. Vérifie que `data/` ne contient
      **rien de neuf** tant que tu n'as pas cliqué (`Get-ChildItem data -Filter mi_model_*` avant et
      après), puis clique **Enregistrer le modèle**.
- [ ] **Ce qu'il faut attendre — à lire AVANT de regarder ce chiffre.** Il est désormais
      **honnête** (validation croisée groupée PAR ESSAI, jamais par fenêtre — l'ancien écran
      pygame affichait un chiffre gonflé de 10 à 16 points) et porte sur les **trois classes**
      (GAUCHE/DROITE/REPOS, hasard 33 %). **≈ 40 % est un résultat NORMAL**, pas un échec : c'est
      le chiffre de référence mesuré honnêtement sur la seule séance archivée du projet —
      **40,0 %, p = 0,082, PAS significatif**. Un « 40 % » lu à côté d'un hasard à 33 % donne
      naturellement envie de conclure que c'est mieux que le hasard ; ce n'est **pas** le cas avec
      cette mesure. Le Motor Imagery ne marche pas également bien chez tout le monde.
- [ ] Revenir sur la page **Motor Imagery** (« ← Motor Imagery » depuis le 2026-09-22 ; rien à
      relancer, toujours la même console) → le champ « Modèle entraîné » propose le fichier qui
      vient d'être écrit, en tête de liste (le plus récent d'abord).
- [ ] **« 3. Tester »** (depuis le 2026-09-22) → **Tester** → la page « Tester le Motor Imagery »,
      **pré-remplie** avec le modèle et les seuils du mode, « Essais par classe » à 6 (≈ 2,8 min à
      trois classes) → **Commencer**. C'est le protocole d'entraînement rejoué — mêmes durées,
      mêmes consignes, **même top latéralisé** (oreille gauche = poing gauche), classes tirées parmi
      celles du modèle — et le moteur décide, par la règle réelle du mode (`MIRuntime._run_step`).
      **Un essai = une décision : la DERNIÈRE sortie**, ce que `decoded_mi` publiait quand l'imagerie
      s'est terminée ; l'essai entier (7 s) est enregistré pour que le plus long vote permis ne
      manque jamais de fenêtres. Rien n'est écrit sur le disque.
      Justesse : ______ % · émission : ______ % · mot : ______ .
      ⚠️ **Rouge est un résultat attendu ici, pas une panne de l'outil.** Depuis le 2026-09-22 la
      porte « au-dessus du hasard » est un **test binomial EXACT unilatéral à p < 0,05** (Wilson
      reste l'intervalle AFFICHÉ, il ne décide plus rien) — le changement vient d'un test c-VEP
      peint orange sur UNE décision juste. Ce que ça donne au MI, calculé, pas mesuré :

      ⚠️ La porte porte sur les essais **ANNONCÉS** (le vote a conclu), pas sur tous : un `-1` sort
      du dénominateur. Le tableau suppose que tous annoncent — le cas le plus favorable.

      | Longueur | Il faut, sur les essais annoncés | Le repère du projet |
      |---|---|---|
      | 6/classe, 3 classes (18 annoncés) | **10/18 = 56 %** (p = 0,043) | 40,0 % → p = 0,391, **rouge** |
      | 10/classe, 3 classes (30 annoncés) | **15/30 = 50 %** (p = 0,043) | 40,0 % → p = 0,276, **rouge** |
      | 6/classe, G/D (12 annoncés) | **10/12 = 83 %** (p = 0,019) | 63,3 % → **rouge** |
      | 10/classe, G/D (20 annoncés) | **15/20 = 75 %** (p = 0,021) | 63,3 % → p = 0,100, **rouge** |

      🔴 **Conséquence à connaître avant de s'asseoir : à ces longueurs, un système exactement au
      repère du projet sort ROUGE, quelle que soit l'option choisie.** Ce n'est pas un défaut du
      seuil — c'est que 18 à 30 essais ne séparent pas 40 % de 33 %. Le rouge du MI se lit donc
      « pas de preuve », jamais « ça ne marche pas » ; le chiffre et sa p-value, eux, se notent.
      Vert exige en plus d'émettre au moins 44 % du temps — le seul repère d'émission du projet,
      celui du SSVEP ; sans ce plancher, un moteur qui ne parle que sur 3 essais sur 24 et a raison
      3 fois serait vert. **MUET** : le vote ne conclut jamais — baisse « Probabilité minimale » ou
      « Votes concordants », ne resaline pas.
- [ ] **Le décodage continu, pour regarder** : grille → tuile **Motor Imagery** → **Démarrer**
      (la page n'a plus ce bouton depuis le 2026-09-22), puis page Motor Imagery → case
      **« Décodage en direct »**. Après la chauffe de 15 s, une barre par classe et un verdict qui
      alterne entre « vote non conclu » et « INTENTION … ». La règle affichée au-dessus des barres
      doit nommer le **vote** (« seuil 0,6 par fenêtre, puis 3 fenêtres d'accord sur les 5
      dernières »), pas « la classe gagnante doit dépasser le seuil ».
- [ ] Imaginer 10 fois la main gauche, 10 fois la droite, en alternant. Compter les intentions
      justes : ______ / 20. Le repère honnête à deux classes est **63 %** (cf. README) — un
      résultat proche d'une erreur sur trois est donc CONFORME. Ne conclus rien d'un écart sur
      20 essais : c'est du bruit à cette taille d'échantillon. *(C'est précisément ce que le
      « Tester » ci-dessus fait proprement : consigne tirée, décision notée, intervalle affiché.)*
- [ ] En parallèle, sur un autre terminal, vérifier que l'intention sort **vraiment** sur le
      réseau : `python -u examples/receiver.py --stream decoded_mi`. Attendu : `intent_index`,
      `confidence`, puis `p_GAUCHE`, `p_DROITE`, `p_REPOS`.
- [ ] ⚠️ `intent_index = -1` (« le vote n'a pas conclu ») et l'indice de REPOS (« la personne se
      repose ») ne veulent **pas** dire la même chose. Le flux donne les deux dans ses
      métadonnées (`no_decision_index`, `rest_index`) : vérifier qu'ils diffèrent.

**Au besoin seulement — l'ancien écran, en comparaison.** `archive/mi_calibrate.py` existe encore,
justement pour ça : comparer minutage, consignes et époques enregistrées si un doute apparaît un
jour sur la calibration du moteur. Ne PAS le lancer juste après ce test par curiosité : il écrit
sous les anciens noms FIXES (`data/mi_model.joblib`, `data/mi_calib_last.npz`), donc il
**écraserait** un enregistrement, sans toucher aux modèles horodatés que ce test vient de produire
— et il faut fermer la console avant de l'ouvrir (cf. `archive/README.md`).

### 2.7 — P300 : sélectionner une cible par la pensée, via le réseau

Le mode le plus exigeant du produit, et le seul où **ton application doit parler au moteur**.

**La calibration : un bouton, dans la même console, sans jamais fermer la session casque.** C'est
ce que le chantier du 2026-09-08 a changé ici — avant, il fallait passer par l'appli pygame, donc
fermer et rouvrir le casque, donc risquer la saturation C3/Cz pour rien.

```bash
python src/console/app.py --mode p300      # page P300 -> « Entraîner » (« Calibrer » avant le 2026-09-22)
```

- [ ] La console passe par le **contrôle de liaison** (voies clés Fz, Cz, Pz surlignées), puis
      lance la fenêtre de stimulus en mode calibration. `P300_CAL_ROUNDS` = 12 manches. La console annonce **≈ 2,2 min** (chauffe comprise) ; compte un
      peu plus, la fenêtre tenant en plus son écran de consigne à chaque manche.
- [ ] ⚠️ **L'ordre compte, et il n'est garanti par aucune poignée de main.** La console soumet
      `start_calibration` **d'abord**, lance la fenêtre **ensuite** ; le moteur compte alors 15 s de
      chauffe pendant que pygame s'initialise. **Regarde le terminal** : s'il écrit « marqueur(s)
      reçus pendant la CHAUFFE : jetés », la fenêtre a pris de l'avance sur cette machine — la
      séance n'est pas perdue, mais elle est plus courte que ce que l'écran annonce. **Note-le.**
- [ ] À la fin, l'écran montre **les cibles retrouvées (validation croisée par manche)** — « la
      cible désignée est-elle retrouvée ? », la mesure qui décide pour ce mode, pas l'AUC (qui est publiée en
      détail) — et attend : **Enregistrer le modèle** ou **Refaire**. Rien n'est écrit avant le
      clic. La sauvegarde produit un fichier **horodaté**
      (`data/p300_model_AAAAMMJJ_HHMMSS.joblib`) : elle n'écrase jamais la précédente, et le moteur
      propose la plus récente par défaut.
- [ ] ⚠️ **Le mode P300 et sa calibration ne peuvent pas tourner ensemble** — le moteur refuse, dans
      les deux sens. Ils liraient la même file de marqueurs. Vérifie le refus : démarre le mode
      depuis la grille, puis « Entraîner » → « Commencer ». La console doit **arrêter le mode
      d'abord** et le dire, jamais lancer les deux. Depuis le 2026-09-22, la même porte est fermée
      entre le mode et son **test**.

**Puis le test** (depuis le 2026-09-22) : « ← P300 » → **« 3. Tester »** → la page « Tester le
P300 », pré-remplie avec le modèle du mode, « Manches » à **6** (≈ 1,2 min) → **Commencer**. La
fenêtre joue le protocole d'entraînement (`--tester`) : elle **cercle** une cible par manche, et le
moteur SÉLECTIONNE avec ton modèle au lieu d'apprendre — chaque flash et chaque fin de manche
passent par le `_run_step` du mode lui-même (garde de cible, plafond par cible, marge). Rien n'est
écrit sur le disque.

- [ ] **Un essai = une manche** ; le hasard est **1/6** (`1 / n_targets` du runtime), jamais 50 %.
      Justes : ______ / 6 · mot : ______ .
- [ ] Les seuils sont ceux de la table d'**entraînement** (`p300_calib.VERDICTS`), lus et non
      recopiés : **vert à 80 %, orange de 60 à 80 %, rouge en dessous** — ou si le **test binomial
      exact** ne rejette pas le hasard à p < 0,05 (la porte commune à tous les tests depuis le
      2026-09-22 ; Wilson reste l'intervalle affiché, il ne décide plus). Donc **5/6 vert
      (p < 0,001), 4/6 orange (p = 0,009), 3/6 rouge (p = 0,062 — la porte se ferme là)** : une ou
      deux erreurs sur six sont attendues (paragraphe suivant). À **24** manches (≈ 4,1 min) la
      porte s'ouvre dès **8/24** (p = 0,035) : plus d'essais, moins de justes exigés en proportion.
- [ ] Une manche sans décision (`-1`) compte comme une sélection **ratée**, et la réserve en nomme
      la cause (liaison, tampon) — à marge nulle, le mode tranche toujours une manche complète, donc
      un `-1` est une perte, pas une abstention.

**Puis, si tu veux le regarder décoder en continu** : la page P300 n'a plus de bouton **Lancer le
stimulus** depuis le 2026-09-22 (il reviendra avec « Connecter »). La console décode (tuile P300 →
« Démarrer ») pendant qu'une fenêtre lancée à la main affiche les cibles, ou le moteur nu en deux
terminaux :

```bash
# terminal 1
python src/core/server.py --mode p300
# terminal 2 — n'ouvre PAS le casque, d'où les deux terminaux
python src/stimulus/p300.py
# terminal 3
python -u examples/receiver.py --stream decoded_p300
```

- [ ] Au lancement, le terminal 2 dit **« le moteur écoute — on peut commencer »**. S'il dit
      « PERSONNE n'écoute », arrête tout : le moteur n'est pas là, ou le nom du flux diffère.
      L'écran garde cet indicateur en haut, en direct, pendant toute la séance.
- [ ] Entre deux manches, l'écran affiche **« choisis ta cible et fixe-la »** pendant 2,5 s, rien
      ne clignote. C'est **le seul moment** où déplacer le regard : le faire pendant les flashs met
      la transition dans les époques, et le moteur publie quand même une cible plausible.
- [ ] Choisis une cible **pendant cette pause**, fixe-la, et **compte ses flashs** en silence. Le
      comptage n'est pas indispensable (mesuré au chantier P300) mais il aide à tenir l'attention.
- [ ] À la fin de la manche, la cible sortie sur `decoded_p300` est **celle que tu fixais**.
- [ ] Recommence **six fois, en changeant de cible à chaque pause**. ⚠️ **Une erreur ou deux sur six
      est attendue** : l'AUC mesurée est de 0,71, pas de 1,0. Un sans-faute serait une bonne
      surprise, pas la norme — et deux erreurs ne veulent pas dire que quelque chose est cassé.
- [ ] Regarde le terminal du moteur pendant ce temps. Les compteurs s'annoncent tout seuls au
      franchissement de 1, 10, 100… : aucun `marqueurs_perdus`, aucun `marqueurs_futurs`, aucune
      `manche ABANDONNÉE`. S'ils montent, le problème est dans l'horloge ou le réseau, pas dans ta
      concentration. Les mêmes chiffres sont sur le flux `status` (`marqueurs.*`) si tu préfères
      les lire depuis un client.
- [ ] Si tu ouvres la console sur la page P300, case « Décodage en direct » (⚠️ **pas en même temps
      que le moteur en terminal 1** — un seul programme à la fois), l'écran doit annoncer des
      **log-odds** et « aucun
      seuil », jamais « échelle z ». Six barres étiquetées `cible 0 … cible 5`, et la cible retenue
      avec le nombre de flashs sur lequel elle repose.

> ⚠️ **`--reps` et `--targets` ne sont pas libres.** Le moteur code 6 cibles en dur et applique
> `P300_REPS` comme plafond par cible : à `--reps 12`, il abandonnerait **toutes** les manches.
> L'émetteur refuse maintenant ces valeurs au lancement, en nommant la constante — si tu vois
> « REFUSÉ », c'est ça.

> ⚠️ **Ne conclus rien sur une seule manche.** Six essais, c'est déjà peu ; ce projet a pour règle
> de ne jamais conclure sur du bruit. Si tu veux un chiffre, il faut un protocole, pas une
> impression.

### 2.8 — ErrP : le moteur voit-il que la machine s'est trompée ?

⚠️ **Lis ceci avant de commencer, sinon tu vas mal interpréter ce que tu vois.**

Ce détecteur, au réglage par défaut, **attrape une erreur sur deux** et annule une bonne commande
sur sept. Ce n'est pas un défaut de réglage : c'est ce que vaut un ERP mono-essai sur ce matériel,
mesuré honnêtement (AUC 0,776, p = 0,0099 sur 100 permutations, 200 essais, une personne).

⚠️ **Et ces deux taux-là sont eux-mêmes optimistes.** L'AUC est honnête — elle vient de scores
hors-pli. Mais le **seuil** qui produit « une sur deux / une sur sept » a été choisi en regardant ces
mêmes scores, donc le TNR obtenu dépasse la cible *par construction* sur les 200 essais du 24
juillet, et sur eux seuls. En séance, attends-toi à annuler **plus** d'une bonne commande sur sept,
pas moins. Le moteur le dit lui-même dans le champ `measured_on` de son flux.

**Donc : ne conclus rien d'un essai, ni de dix.** Sur dix erreurs délibérées, en attraper cinq est
le résultat *attendu*. En attraper huit ou deux tient dans le bruit.

**La calibration : un bouton, ~200 essais, sans quitter la console.** Elle aussi a changé le
2026-09-08 — il n'y a plus d'appli pygame à ouvrir puis refermer.

```bash
python src/console/app.py --mode errp      # page ErrP -> « Entraîner » (« Calibrer » avant le 2026-09-22)
```

- [ ] Contrôle de liaison (voies clés Fz, Cz, Pz), puis la console lance
      `src/stimulus/errp.py --calibrer`. `ERRP_CAL_TRIALS` = 200 essais. La console annonce **≈ 5,7 min**, chauffe comprise.
- [ ] ⚠️ **Ce que ce chemin fait de plus que le décodage, et qu'il ne faut PAS confondre :** en
      calibration, chaque marqueur `feedback` porte un champ `error` — la vérité-terrain. **En
      décodage il est absent**, et il doit le rester : l'ErrP est une BCI *passive*, tout son objet
      est de deviner l'erreur depuis l'EEG seul. Si tu vois `error` dans un marqueur de décodage,
      arrête tout : le flux `decoded_errp` garderait exactement la même forme et tous les chiffres
      de ce test deviendraient faux, sans rien pour le signaler.
- [ ] ⚠️ **L'étiquette suit l'EFFET du pas, pas le tirage.** Un pas « erreur » tiré au bord de piste
      rapproche le point de sa cible : il n'y a pas d'erreur vécue, donc il est publié
      `error: false`. C'est la même faute que d'horodater avant le flip, sur un autre axe.
- [ ] À la fin, l'écran montre l'**AUC** (pas une accuracy, pas un chiffre du P300) et attend
      **Enregistrer le modèle** / **Refaire**. Le fichier est horodaté
      (`data/errp_model_AAAAMMJJ_HHMMSS.joblib`) et n'écrase jamais `data/errp_model.joblib`, qui
      est la trace casque du 24 juillet — le **seul** modèle ErrP jamais enregistré sur un vrai
      cerveau.

**Puis le test** (depuis le 2026-09-22) : « ← ErrP » → **« 3. Tester »** → « Tester l'ErrP »,
pré-rempli avec le modèle et « Bonnes commandes gardées » du mode, « Essais » à **80** (≈ 2,4 min,
~22 erreurs délibérées ; 40 ≈ 1,4 min, 200 ≈ 5,7 min) → **Commencer**. La fenêtre joue le protocole
d'entraînement (`--tester`) — erreurs délibérées, `feedback` **étiqueté** — et le moteur décide à
chaque feedback avec le seuil que son runtime déduit du réglage, rejet d'artefact compris. Rien
n'est écrit sur le disque.

- [ ] 🔴 **LA question de ce test : l'étiquette atteint le CORRECTEUR, jamais le DÉCODEUR.** Le
      test a besoin de la réponse pour noter, et c'est la seule fois où un marqueur étiqueté arrive
      pendant que le moteur DÉCIDE. Le socle la retire d'une copie du marqueur avant que le test ne
      le voie ; le décodeur ne reçoit qu'une vue du tampon EEG, jamais le moteur (dont la file
      garde les feedbacks étiquetés). **Rien de cela ne se voit à l'écran** : c'est tenu par
      `python src/core/modes/errp_test.py`, où un décodeur espion est appelé une fois par feedback
      sans que rien de ce qu'on lui passe ne mène à la réponse. ⚠️ En séance, **un score parfait
      est un signal d'alarme**, pas une réussite.
- [ ] Au début, **regarde la piste immobile sans bouger** : le mode prend là son repos de référence
      pour le rejet d'artefact (la page le dit). La fenêtre `--tester` ne joue pas de repos : elle
      tient sa piste immobile ~15 s après son propre lancement, et le repos est clos au premier pas
      s'il n'a pas eu ses 8 s. Sa durée réelle (estimée 2-5 s, jamais mesurée) n'est pas affichée.
- [ ] Le verdict est un **COUPLE** : « garde X % des bonnes commandes, attrape Y % des erreurs
      (hasard : Z %, autant qu'il en annule) ». Il n'y a pas de hasard à 50 % : un détecteur au
      hasard attrape autant d'erreurs qu'il annule de bonnes commandes, et c'est un test exact de
      Fisher unilatéral qui dit si l'écart dépasse le bruit.
      Gardées : ______ % · attrapées : ______ % · mot : ______ .
- [ ] Le mot : **FAIBLE** si Fisher ne passe pas (p ≥ 0,05) ; **BON** (vert, « AU NIVEAU DU REPÈRE » jusqu'au 2026-09-24) si
      l'écart TPR − (1 − TNR) atteint **0,355** (le repère 0,500 − 0,145) et que moins de 50 % des
      feedbacks sont restés sans verdict ; **UTILISABLE** sinon ; **NON MESURÉ** si aucune erreur
      ou aucune bonne commande n'a été jugée. Un `-1` (artefact, époque perdue) est compté À PART.
- [ ] ⚠️ **Attends-toi à garder MOINS de bonnes commandes que visé.** Le 0,855 du repère a été
      mesuré au seuil qui l'a choisi (optimiste par construction) ; ce test le mesure sur des essais
      neufs. Si la réserve dit que la part gardée est nettement sous la cible, c'est ce biais-là, et
      elle dit quel réglage monter.

**Puis, pour regarder le décodage continu** : la page ErrP n'a plus de bouton **Lancer le
stimulus** depuis le 2026-09-22 — la console décode (tuile ErrP → « Démarrer ») pendant qu'une
fenêtre lancée à la main affiche la piste (1.15), ou le moteur nu en trois terminaux :

```bash
# terminal 1
python src/core/server.py --mode errp
# terminal 2
python src/stimulus/errp.py
# terminal 3
python -u examples/receiver.py --stream decoded_errp
```

- [ ] Regarde la piste et laisse-toi surprendre par les erreurs — **ne les anticipe pas**. L'ErrP
      est une réaction à une surprise ; si tu sais que la machine va se tromper, il n'y a plus rien
      à détecter.
- [ ] Compte tes erreurs délibérées et les `error = 1` publiés. **Vise l'ordre de grandeur, pas le
      score.**
- [ ] Regarde le taux de rejet d'artefact dans l'état du moteur. **S'il dépasse 50 %, le moteur le
      dit — une seule fois, et pas avant 10 époques jugées.** Ne guette donc pas un message
      récurrent : son silence ne veut pas dire que le taux est redescendu. Pour le suivre en continu,
      lis `taux_rejet` dans l'état du moteur (flux `status`, ou la console). Un taux haut veut dire
      que le contact s'est dégradé ou que tu bouges, pas que le décodeur est cassé.
- [ ] Change « Bonnes commandes gardées » de 0,85 à 0,70 et refais une série : tu devrais attraper
      plus d'erreurs, et annuler plus de bonnes commandes. C'est le compromis, en vrai.
      ⚠️ **Ce point demande la console** — `python src/console/app.py --mode errp` **à la place** du
      terminal 1, jamais les deux en même temps : `server.py` n'a pas ce réglage. Et changer le
      réglage **recrée le flux** (« RECRÉÉ (réabonnez-vous) ») puis **refait les 23 s de chauffe et de
      repos** : relance ton `receiver.py` et attends la fin du repos, sinon tu comptes sur un flux
      mort.

> ⚠️ **Un point ouvert que ce test peut trancher** : la référence de rejet d'artefact est mesurée
> sur du signal BRUT après 15 s de chauffe, et ce délai n'a jamais été vérifié pour cet usage
> précis — il est hérité du SSVEP. Si le taux de rejet est anormalement haut dès le début de séance
> et redescend ensuite, c'est que la chauffe est trop courte. **Note-le, c'est une mesure utile.**

### 2.9 — c-VEP : le moteur lit-il la phase d'un vrai cerveau ?

⚠️⚠️ **Lis les trois encadrés qui suivent AVANT de lancer quoi que ce soit.** Ce mode est le seul du
produit dont la panne caractéristique **ne casse rien** : une phase fausse de quelques frames ne
lève aucune exception, les corrélations baissent juste assez pour que la détection ne se déclenche
presque jamais, et à l'écran c'est **indiscernable de quelqu'un qui fixe mal**. Sans ces trois
lectures, un opérateur conclut à la panne en regardant le comportement attendu — ou à la réussite en
regardant une horloge décalée.

#### ⚠️ 1. Ce qu'est un résultat NORMAL

À **6 cibles, le hasard est à 16,7 %**. Jamais 50 %.

La seule mesure qui existe pour ce décodeur vient de la **séance de référence du 2026-07-21**,
dépouillée hors ligne : sur **37 décisions appariées** à la géométrie du moteur (k = 2 cycles),
**eCCA 59,5 %, rCCA 64,9 %** — soit **8 décisions discordantes** entre les deux, et **McNemar
p = 0,727**. Traduction : les deux décodeurs sont **indiscernables**, et l'écart de 5 points entre
les deux pourcentages est du bruit. Ne choisis pas ton décodeur là-dessus.

**Donc : environ UNE désignation sur TROIS est fausse, et c'est le comportement attendu.** Une cible
sur six mal désignée n'est pas une panne — c'est la moitié d'une erreur de moins que la référence.
Un sans-faute sur six essais serait une bonne surprise, pas la norme.

⚠️ **Et ce 60-65 % est un chiffre HORS LIGNE, mesuré en validation croisée sur les époques d'une
calibration.** Ce n'est pas une justesse en direct, encore moins à travers le réseau : **le c-VEP
n'a jamais été décodé au casque par le moteur**, c'est précisément ce que ce test fait pour la
première fois. Attends-toi à **moins**, pas à plus.

⚠️⚠️ **CE 59,5 / 64,9 % N'EST PAS LE CHIFFRE QUE TU VAS COMPTER, et confondre les deux fabrique un
verdict faux.** C'est l'`argmax` hors-pli sur **TOUTES** les décisions — **sans les deux seuils ni
le vote** que le moteur ajoute. Le moteur, lui, n'émet une cible qu'après `corr_min` **et**
`margin`, puis **2 des 3 dernières fenêtres** ; tout le reste devient un `-1`, que tu comptes à
part en « silences ». Le repère qui correspond à ce que tu vas relever existe, mesuré, dans
`core/config.py` :

| à k=2, seuils 0,26/0,09 (les défauts) | valeur |
|---|---|
| **taux d'ÉMISSION** (fenêtres où une cible sort) | **46 %** |
| **justesse PARMI LES VERDICTS ÉMIS** | **71 %** (donc 29 % de faux) |
| bruit qui franchit quand même les seuils | 10 % |

**C'est ce couple-là — ~46 % d'émission, ~71 % de justesse à l'émission — qu'il faut comparer à
ton relevé**, pas le 59,5/64,9. Avec le mauvais dénominateur, 70 % de justesse sur 45 % d'émission
(c'est-à-dire le comportement attendu) se lit « mieux que prévu », et 60 % sur 90 % d'émission se
lit « conforme » alors que ça signalerait des seuils qui ne mordent plus.

⚠️ **Le moteur va donc se taire plus d'une fois sur deux, et ce n'est pas une panne.** Le repère du
projet est le SSVEP : **100 % de justesse quand il émet, mais il n'émet que 44 % du temps**. Un
long silence entre deux verdicts justes est un régime normal ici.

**Ne conclus rien de six essais, ni de dix.** Si tu veux un chiffre, il faut un protocole — c'est
`--seed` et le dépouillement ci-dessous, pas une impression.

#### ⚠️ 2. La période à JETER après chaque changement de consigne

C'est le générateur de faux verdict de ce test, et il est purement arithmétique.

L'émetteur tient chaque consigne **8 cycles de code, soit 8,4 s** à 60 Hz. Mais le moteur a **deux
mémoires** en amont de chaque échantillon publié :

| | durée |
|---|---|
| la fenêtre de décision — 2 cycles de code repliés | 2,10 s |
| le vote glissant — 3 fenêtres espacées de 0,2 s | 0,60 s |
| **total : la TRANSITION** | **2,70 s** |

Pendant ces **2,70 s**, chaque échantillon publié est calculé sur du signal **à cheval sur DEUX
cibles**. Rien dans le flux ne le dit. Ça fait **32 % des échantillons de chaque consigne**, et les
compter tire mécaniquement la justesse mesurée vers le hasard.

> **Ce n'est pas une précaution théorique.** À l'ancien réglage (4 cycles, 4,2 s par consigne) la
> transition couvrait **64 %** de l'intervalle : quelqu'un qui notait tous les verdicts mesurait
> **~40 %** quel que soit le décodeur, et concluait que le c-VEP ne marche pas — en regardant une
> transition. La consigne a été rallongée à 8 cycles pour cette raison, et il en reste 32 % à jeter.

**Chaque ligne du terminal de l'émetteur imprime l'instant exact à partir duquel les échantillons
comptent** :

```text
[cvep-stim] t=12345.678  cycle 9 : fixe « AR-DROITE » (cible 2)  —  compter à partir de t=12348.378 (+2.7 s de transition)
```

- [ ] **Ne note QUE les `decoded_cvep` postérieurs à ce second horodatage.** C'est la seule règle de
      dépouillement de ce test, et l'ignorer suffit à fabriquer un échec.

⚠️ **Cette règle ne s'applique QUE si tu écris les deux côtés dans des fichiers.** Le dépouillement
se fait **après** la séance, sur un journal — jamais en direct, et jamais en comparant deux fenêtres
de terminal à l'œil (~1 500 lignes à 5 Hz pour 5 min, contre ~35 consignes).

**Il faut DEUX fichiers.** Ils portent le **même horodatage `local_clock()`**, ce qui rend la
jointure purement numérique — c'est toute la raison d'être de ce couple. Du 2026-09-09 au 2026-09-22
la console les produisait tous les deux sans qu'on tape quoi que ce soit ; ⚠️ **depuis le
2026-09-22, la case « Journal de séance » a quitté la page c-VEP** avec « Lancer le stimulus » (les
deux reviendront avec « Connecter »), et la vérité-terrain exige de nouveau une fenêtre lancée à la
main :

| côté | ce que c'est | où il naît | comment l'obtenir |
|---|---|---|---|
| **vérité-terrain** | une ligne JSON par consigne, avec `t` et `compter_a_partir_de` | la **fenêtre** de stimulus | `python src/stimulus/cvep.py --log` à la main (sans valeur : nom horodaté dans `seances/`, choisi par la fenêtre) — **plus aucun chemin dans la console** jusqu'à « Connecter » |
| **verdicts** | une ligne par décision **publiée**, avec son `t` | le **moteur** | bouton **« Enregistrer les verdicts »** de la page « Ce que voit ton application » — ou `python -u examples/receiver.py --stream decoded_cvep > seance_recv.txt` |

Les deux atterrissent dans **`seances/`**, à la racine du dépôt, côte à côte et horodatés
(`cvep_AAAAMMJJ-HHMMSS.jsonl` pour la fenêtre, `moteur_decoded_cvep_AAAAMMJJ-HHMMSS.jsonl` pour le
moteur). ⚠️ **Jamais dans `data/`** : ce sont des verdicts de séance, ni des modèles ni des
enregistrements EEG.

- [ ] **Vérifie que tu as bien les DEUX**, avant de commencer et pas après. Sans eux la séance n'est
      **pas dépouillable** : le scrollback est le seul autre exemplaire, le 2.9 demande plus bas de
      fermer les terminaux entre ses blocs, et une séance casque ne se répète pas.
- [ ] ⚠️ **L'enregistrement du moteur écrit une ligne par décision PUBLIÉE, pas par tour de
      boucle.** C'est ce qui le rend comparable au relevé qu'on cherche : sur un mode qui se tait la
      moitié du temps, un fichier qui compterait les tours se relirait à 100 % d'émission.
- [ ] ⚠️ **Ce qui est hors des boutons : le journal ET `--seed`** (le journal y a été du 2026-09-09
      au 2026-09-22). Si tu veux pouvoir **rejouer la séance à l'identique**, lance l'émetteur avec
      `--seed N --log …` — c'est ce que les blocs A/A' utilisent pour être comparables.

#### ⚠️ 3. Il faut un modèle, et il est propre à TA personne

Le modèle de quelqu'un d'autre donne des corrélations plausibles et fausses — le pire des deux
mondes. Si tu n'en as pas :

```bash
python src/console/app.py      # page c-VEP → « Entraîner » (« Calibrer » avant le 2026-09-22),
                               # ~3 min, fixer chaque cible cerclée
```

⚠️ **Depuis le 2026-09-08, c'est le MOTEUR qui entraîne** : la console lance
`src/stimulus/cvep.py --calibrer` et le moteur découpe ses époques **par le chemin du décodage**,
sur l'horloge que la fenêtre publie déjà. L'ancien écran pygame existe toujours — il est archivé en
`archive/cvep_calibrate.py` — mais il découpe sur l'horloge pygame ; pour une séance qui compte,
passe par la console. ⚠️ **Le chemin du moteur a été joué UNE fois au casque**, le 2026-09-22 :
**25,0 % pour un hasard à 17 %**, loin des 59,5/64,9 % de référence ; un modèle a été gardé ce
jour-là. Son décodage, lui, n'a pas été mesuré.

La durée exacte est **calculée et imprimée au lancement** (`[cvep-cal] … ≈ 2.7 min`) : 6 cibles ×
15 cycles en 18 blocs entrelacés, hors briefing et hors contrôle de liaison. Budgète-la comme telle
— la « ~1 min » qui traînait dans cette recette datait d'un ancien réglage, et un facteur 3 sur un
préalable de séance se paie en fatigue et en électrodes qui sèchent.

Elle entraîne **eCCA ET rCCA sur les mêmes époques**, affiche les deux justesses et rend le **test**
de McNemar — « indiscernables » est la réponse attendue, et c'est pourquoi l'écran ne nomme aucun
gagnant. Elle écrit **deux** fichiers horodatés (`data/cvep_model_AAAAMMJJ-HHMMSS.npz` et
`data/cvep_rcca_model_*.npz`) et n'écrase jamais rien.

- [ ] ⚠️ **Rien n'est écrit avant le clic sur « Enregistrer le modèle ».** Les DEUX fichiers partent
      ensemble — le c-VEP est le seul mode à en produire deux par séance, et « Refaire » les jette
      tous les deux. Vérifie qu'ils sont bien tous les deux dans `data/` après le clic : perdre le
      `.npz` rCCA en croyant avoir tout enregistré est le défaut que la tâche 8 a corrigé.
- [ ] **Note le nom exact du fichier eCCA** : ______________________ . Tu en auras besoin pour la
      comparaison, qui n'a de sens que sur le **même modèle**.
- [ ] **Puis « Tester le c-VEP »** (depuis le 2026-09-22), AVANT la séance longue : « ← c-VEP » →
      **« 3. Tester »** → pré-rempli avec le modèle et les seuils du mode, « Longueur : cycles
      enregistrés par cible » à **3** (18 blocs, ≈ 1,8 min) → **Commencer**. La fenêtre joue le
      protocole d'entraînement (`--tester`) : une cible **cerclée** par bloc, l'horloge `cycle`
      continue. **Un bloc = une décision : la dernière sortie** que `decoded_cvep` publiait quand le
      bloc s'est fermé — une fenêtre votée, l'unité même du repère EN DIRECT ; le rejeu passe par
      le `CVEPRuntime` du mode et ne calcule aucune phase. Rien n'est écrit sur le disque.
      Justesse à l'émission : ______ % · émission : ______ % · mot : ______ .
      Le mot : **BON** (vert, « AU NIVEAU DU REPÈRE » jusqu'au 2026-09-24) au-dessus du hasard **et** à 71 % de justesse **et**
      46 % d'émission — le couple de l'encadré 1, jamais le 59,5/64,9 % ; **UTILISABLE** (orange)
      sous l'un des deux ; **FAIBLE** si l'intervalle contient 1/6 ; **MUET** s'il n'a rien émis,
      **NON MESURÉ** si l'horloge n'a servi sur aucun bloc — et la réserve nomme la cause dominante
      (seuils, vote, horloge). ⚠️ **Orange est l'issue attendue d'un système AU repère** : à 18
      blocs il ne sort vert qu'environ une fois sur quatre (calcul binomial, pas une mesure).
      ⚠️ Ce test dit si ta configuration tient ; il **ne remplace pas** l'A-B-A ci-dessous, seul à
      séparer « réseau » et « séance ».
- [ ] **Si tu pars sur le montage (b) ci-dessous, ferme la console** avant de lancer le moteur du
      bloc A. Elle ouvre le casque, et l'Unicorn n'accepte qu'une connexion. En montage (a') tu ne
      la fermes jamais — c'est précisément l'intérêt, une seule ouverture d'amplificateur pour toute
      la séance (cf. la saturation C3/Cz à la réouverture).

#### La séance

⚠️ **Ne retire pas le casque, ne resaline pas, ne referme pas la session entre les deux moitiés de
ce test.** La comparaison du dernier point ne vaut que si les deux décodages voient le même montage
sur la même tête.

**Deux montages, et il faut choisir AVANT de mettre le casque.**

~~**(a) Tout depuis la console**~~ — le chemin sans aucune commande, du 2026-09-09 au 2026-09-22
(case « Journal de séance » + « Lancer le stimulus »). **Il n'existe plus** : les deux ont quitté la
page c-VEP, et reviendront avec « Connecter ».

**(a') La console pour le casque, la fenêtre à la main** — ce qui s'en approche le plus aujourd'hui.
Un seul programme ouvre le casque ; la fenêtre, elle, ne l'ouvre pas :

```bash
python src/console/app.py --mode cvep       # la console : casque + décodage c-VEP démarré
python src/stimulus/cvep.py --log           # 2e terminal : la fenêtre, journal horodaté dans seances/
                                            # (+ --seed N pour pouvoir rejouer)
```

Puis, dans la console : grille → **« Ce que voit ton application »** → choisir
`EEG_API_Unicorn_decoded_cvep` → **Enregistrer les verdicts**. Les deux fichiers partent dans
`seances/`. ⚠️ Deux commandes tapées : c'est un trou connu de la règle « aucune commande », daté et
écrit, pas une façon de faire.

**(b) Trois terminaux** — le montage historique, et **celui que les blocs A / A' doivent utiliser**
si tu veux pouvoir rejouer. C'est aussi celui d'une application tierce :

```bash
# terminal 1 — le moteur (15 s de chauffe, PAS de repos : le c-VEP ne mesure aucun plancher)
python src/core/server.py --mode cvep
# terminal 2 — l'émetteur : n'ouvre PAS le casque, d'où les deux terminaux.
#              --log est OBLIGATOIRE ici : c'est la vérité-terrain, et rien d'autre ne la porte.
python src/stimulus/cvep.py --log seance_A_stim.jsonl
# terminal 3 — redirigé dans un fichier, pour la même raison
python -u examples/receiver.py --stream decoded_cvep > seance_A_recv.txt
```

⚠️ **Jamais la console ET le moteur en même temps** : ils publieraient `decoded_cvep` deux fois sous
le même nom. Choisis (a') OU (b).

⚠️ En montage (b), le terminal 3 **n'affiche donc plus rien** : c'est voulu, il écrit. Pour
surveiller en direct, regarde le terminal 1 (une ligne par seconde, verdict + corrélations) et le
bandeau de l'émetteur.

- [ ] Le terminal 2 dit **« le moteur écoute. »**. S'il dit « PERSONNE n'écoute », arrête tout : le
      moteur n'est pas là, ou le nom du flux diffère. Le bandeau du haut de l'écran garde cet
      indicateur en direct pendant toute la séance.
- [ ] Il imprime aussi sa **graine** (`graine 1234567 — REJOUE cette séance à l'identique avec
      --seed 1234567`). **Note-la** : ______________ . Une séance casque ne se répète pas ; sans la
      graine, elle ne se dépouille pas deux fois.
- [ ] Le terminal 1 annonce en une ligne le **modèle, le décodeur, les seuils et le flux d'horloge**.
      Vérifie que c'est bien le modèle que tu viens de calibrer.
- [ ] Le clignotement **démarre tout de suite**, pendant la chauffe, avec un bandeau qui le dit.
      C'est voulu : le moteur encaisse l'horloge pendant ce temps. Fixe déjà la cible entourée.
- [ ] Fixe la cible entourée, **sans bouger les yeux**, et laisse tourner **~5 min** (c'est le
      bloc A ; note la durée réelle, tu la rejoueras à l'identique en A'). Le terminal 1 imprime une
      ligne par seconde : le verdict et les six corrélations à côté.
- [ ] ⚠️ **Quitte l'émetteur par ESC, jamais par Ctrl+C.** La ligne de cadence et le bilan ne
      s'impriment qu'à la sortie propre — et c'est le seul verdict de validité de la séance.
- [ ] **Lis la ligne de cadence** de l'émetteur : `cadence : … ms par cycle mesuré contre 1050,0 ms
      annoncés`. Si un avertissement apparaît (« l'écran ne tient PAS les 60 Hz publiés »), **la
      séance est à refaire** : le moteur a extrapolé la phase à la mauvaise vitesse et tout ce que
      tu viens de mesurer est faux, sans que rien d'autre ne l'ait signalé. Regarde aussi le compte
      de frames sautées — quelques-unes sont sans gravité, chacune est résorbée au marqueur suivant.
      (Le même bilan est aussi la dernière ligne de `seance_A_stim.jsonl`, `"kind":"bilan"`.)
- [ ] **Dépouille, après la séance, sur les deux fichiers.** Pour chaque ligne `"kind":"consigne"`
      du journal de la fenêtre, prends les lignes de verdicts dont le `t` est **≥ son
      `compter_a_partir_de`** et **< le `t` de la consigne suivante** ; compare leur `target_index`
      au champ `cible`. Trois colonnes : cible juste, cible fausse, `-1`.
      Justes : ______ · fausses : ______ · silences : ______ .
      *(Montage (a') : `seances/cvep_*.jsonl` et `seances/moteur_decoded_cvep_*.jsonl`, le
      `target_index` étant sous `sortie`. Montage (b) : `seance_A_stim.jsonl` et
      `seance_A_recv.txt`, le `t=` étant en tête de ligne.)*
      ⚠️ Les deux `t` sont dans le **même domaine** (`local_clock()`) : c'est une comparaison de
      nombres, pas un rapprochement à l'œil. Si tu n'as qu'un seul des deux fichiers, ce point n'est
      pas faisable — reprends la séance avec `--log` et la redirection.
- [ ] **Compare au repère chiffré de l'encadré 1** : `émis / total` proche de **46 %**, et
      `justes / émis` proche de **71 %**. Ce sont ces deux ratios-là, pas le 59,5/64,9 %.
      Émission mesurée : ______ % · justesse à l'émission : ______ % .
      En dessous, va lire les compteurs avant de conclure.

> **La méthode de secours, à l'œil, quand il n'y a pas de journal** (c'est le cas du bloc B
> ci-dessous : l'écran archivé n'écrit rien). Le **terminal 1** imprime **une ligne par seconde**.
> Après chaque changement de consigne, **jette les 3 premières lignes** (2,70 s de transition) et
> compte les **~5 suivantes** : une consigne de 8,4 s en donne ~8, dont ~5 comptables. C'est
> grossier — les lignes ne sont pas horodatées et le comptage se fait au fil de l'eau — mais c'est
> exécutable sans rien d'autre, et ça donne les mêmes deux ratios. Ne mélange pas les deux méthodes
> dans un même relevé.

#### Quand ça ne détecte pas : LIS LA CAUSE, elle est comptée

⚠️ **`target_index = -1` a quatre causes, et elles appellent quatre gestes OPPOSÉS.** Le flux ne
porte que le `-1` ; les compteurs qui les séparent sont dans l'état du moteur (flux `status`, ou la
console), et le motif en clair est imprimé à côté de chaque ligne du terminal 1. Une séance casque
ne se répète pas : « ça ne détecte pas » sans la cause envoie chercher au mauvais endroit.

| Ce qui monte | Ce que ça veut dire | Ce qu'il faut faire |
|---|---|---|
| `sans_reference` | aucun marqueur d'horloge n'est jamais arrivé | relancer l'émetteur · vérifier le nom du flux |
| `reference_perimee` | l'horloge s'est tue (émetteur planté, fenêtre fermée) | relancer l'émetteur |
| `sous_les_seuils` | ça décode, les corrélations ne passent pas | **saliner**, vérifier le contact, fixer UNE cible |
| `vote_non_conclu` | elles passent, les fenêtres récentes ne s'accordent pas | tenir le regard immobile |

- [ ] Relever lequel domine : ____________________ . Ces quatre-là plus `decodages`
      **partitionnent** les fenêtres traitées — chacune en incrémente exactement un, donc la somme
      doit couvrir toute la séance. `marqueurs_refuses`, lui, compte des **marqueurs** : s'il monte,
      c'est l'émetteur qui est mal réglé, pas le cerveau.
- [ ] Regarder aussi `age_reference_s`, `corr_gagnant` et `corr_second` : ils disent en une ligne si
      l'horloge est vivante et à quelle hauteur les corrélations passent réellement.

> **Si `sous_les_seuils` domine avec des `corr_gagnant` proches de 0,26**, tu peux **descendre le
> seuil sans interrompre la séance** — c'est le seul réglage du produit qui le permette. Il faut la
> console à la place du terminal 1 (`python src/console/app.py --mode cvep`, **jamais les deux**),
> page c-VEP, champ « Corrélation minimale ». Le flux n'est **pas** recréé et la chauffe n'est
> **pas** refaite : ton `receiver.py` continue de recevoir, et les deux dernières voies
> (`corr_min`, `margin`) portent la nouvelle valeur dès l'échantillon suivant. **Note la valeur
> retenue dans ton relevé** — les métadonnées du flux, elles, garderont l'ancienne, puisqu'elles
> sont figées à l'ouverture.
>
> ⚠️⚠️ **Mais fais l'A-B-A du point suivant D'ABORD, aux seuils par DÉFAUT.** `archive/cvep_pilot.py`
> décode toujours à **0,26/0,09** et n'expose aucun réglage : une séance où A tourne à 0,15 et B à
> 0,26 compare deux **règles de décision**, pas deux **chemins de décodage** — exactement la
> confusion que l'A-B-A existe pour éliminer. Ne desserre le seuil qu'après, et note-le comme un
> **bloc séparé**, jamais comme une amélioration de A.

#### LA mesure de ce test : comparer à l'écran archivé, même personne, même séance

C'est **le seul point de 2.9 qui produise une conclusion**, et il coûte deux blocs de plus (~10 min
de casque). Tout le reste dit « ça marche » ou « ça ne marche pas » sans pouvoir dire *par rapport à
quoi*.

`archive/cvep_pilot.py` est l'écran pygame que ce chantier a retiré : **même modèle, mêmes cibles,
même vote 2-sur-3** — la géométrie de décision est identique (2 cycles repliés, 2 votes sur 3, à
5 Hz) —, mais il décode en local, dans le programme qui affiche. Deux chemins indépendants qui
doivent désigner la **même cible sur la même fixation**. Sans cette comparaison, un mauvais résultat
a deux explications qu'on ne peut pas séparer : *« le décodage réseau est moins bon »* et *« la
séance est moins bonne »* (contact qui s'est dégradé, fatigue, saline qui a séché).

⚠️⚠️ **Même modèle, mêmes cibles, même vote — mais PAS le même protocole, et c'est à toi de le
compenser.** A est **cerclé et à l'aveugle** : une consigne tirée au sort t'impose la cible, tu ne
vois jamais la réponse du décodeur. B est **libre et en boucle fermée** : l'écran archivé n'affiche
**aucune consigne**, ne tire rien, n'horodate rien, n'écrit aucun journal — et il montre la réponse
du décodeur **en direct**, dans un panneau de scores. Sans protocole écrit d'avance, B n'a **aucune
vérité-terrain** et son « ____ % » ne repose sur rien. D'où les trois règles ci-dessous, à lire
avant de lancer B.

**Fais-le en A-B-A**, dans cet ordre, sans retirer le casque, **et aux seuils par défaut
(0,26/0,09) pour les trois blocs** :

```bash
# A  — déjà fait ci-dessus : moteur + émetteur, ~5 min, avec --log, noter les deux ratios
# B  — fermer les trois terminaux, PUIS :
python archive/cvep_pilot.py --model data/cvep_model_AAAAMMJJ-HHMMSS.npz    # ~5 min
# A' — refermer, relancer EXACTEMENT le montage A (même durée, --log seance_Ap_stim.jsonl), ~5 min
```

- [ ] **`--model` explicite, obligatoire.** Le défaut de ce fichier archivé pointe sur l'ancien nom
      FIXE `data/cvep_model.npz`, que la calibration n'écrit plus. Sans cet argument tu comparerais
      deux modèles différents et l'écart mesuré ne voudrait rien dire.
- [ ] **Le protocole de B, à préparer AVANT de le lancer** (il n'en fournit aucun) :
      1. **Écris ta liste de fixations sur papier d'avance** — 6 cibles × 3 passages, dans un ordre
         mélangé, jamais deux fois la même de suite. C'est ta seule vérité-terrain pour B.
      2. **Fixe chaque cible 10 s**, et **ignore les 3 premières secondes** : la même transition
         qu'en A s'applique ici (2,10 s de fenêtre + 0,60 s de vote), pour la même raison.
      3. ⚠️ **Ne regarde le panneau de scores qu'à la FIN de chaque fixation**, et note ce qu'il
         affiche à cet instant. Le regarder pendant te dit la réponse et biaise ta fixation — c'est
         la différence de protocole avec A, et la seule que tu puisses réduire.
      Le comptage de B suit alors la **méthode de secours** décrite plus haut (jeter le début,
      compter la fin), avec les mêmes deux ratios qu'en A.
- [ ] A : ______ % émis / ______ % justes · B (écran archivé) : ______ % / ______ %
      · A' : ______ % / ______ % .
- [ ] **Comment lire ces trois nombres**, et c'est tout l'intérêt du A' :
      - A ≈ A' ≈ B → le décodage réseau vaut l'écran local. **C'est le résultat attendu.**
      - A ≈ A' **et** nettement < B → le décodage **réseau** est en cause. C'est un vrai défaut,
        à rapporter avec les compteurs de la section précédente.
      - A > A' → **la séance s'est dégradée** en cours de route. L'écart A-vs-B ne conclut rien :
        resaline et refais, ou note-le comme non concluant. Ne blâme pas le moteur.
- [ ] ⚠️ **Le seul biais connu de ce protocole** : passer de A à B ferme et rouvre la session
      BrainFlow, et l'amplificateur redémarre — le piège documenté qui fait **saturer C3/Cz**. Le
      c-VEP décode sur **Pz, PO7, Oz, PO8** (`CVEP_CHANNELS`), donc il devrait y échapper, mais ça
      n'a **jamais été mesuré**. C'est justement ce que le retour en A' contrôle. Note l'ordre réel
      dans lequel tu as joué les trois blocs.

> ⚠️ **Ne conclus rien sur une seule fixation, ni sur six.** À 6 cibles et ~60 % de justesse, six
> essais donnent un intervalle de confiance qui couvre à peu près tout ce qui est plausible. Ce
> projet a pour règle de ne jamais conclure sur du bruit ; la règle vaut aussi quand le résultat
> fait plaisir.

---

## Niveau 3 — le réseau

### 3.1 — Un client sur la même machine — ✅ passé le 2026-07-29

Refait ce jour en synthétique, résultat conservé ici comme référence.

```bash
python src/core/server.py --mode ssvep --synthetic     # terminal 1
python -u examples/receiver.py --list                  # terminal 2
python -u examples/receiver.py --stream decoded_ssvep  # terminal 2
```

- [ ] `--list` montre les flux : `_raw`, `_quality`, `_status`, `_decoded_ssvep`. ⚠️ **Attendre
      ~25 s** avant de lister : le flux décodé n'est créé qu'à la fin de la chauffe et du repos —
      ses métadonnées sont figées à la création, et les publier avant le plancher les rendrait
      fausses.
- [ ] `--stream decoded_ssvep` affiche des valeurs qui défilent. Attendu, tel qu'obtenu ce jour :

  ```text
  Connected: 6 channels  ['target_index', 'freq_hz', 'confidence',
                          'score_15Hz', 'score_20Hz', 'score_8.57143Hz']
  Clock offset: -0.014 ms
  [t=3303867.957   83.0 ms old] target_index=-1.00  freq_hz=0.00  confidence=1.23  score_15Hz=-0.61 …
  ```

  Le `t=` est l'horodatage LSL de l'échantillon, corrigé sur l'horloge de cette machine. C'est lui
  qui rend une séance dépouillable après coup : les émetteurs de stimulus horodatent leurs consignes
  sur la MÊME horloge, donc les deux fichiers se joignent dessus (cf. 2.9).

  `target_index=-1` signifie « aucune cible » : normal en synthétique, personne ne regarde rien.
  Les noms de voies **portent les fréquences réglées** — c'est pour ça que les changer recrée le
  flux.

### 3.2 — Depuis une deuxième machine

Validé le 2026-07-27 entre deux postes, sans aucune configuration. À refaire **sur le réseau de
l'école**, qui est un autre réseau : c'est le risque n°1 de la spec.

- [ ] Sur la machine B, ni dépôt ni casque : `pip install pylsl`, puis `receiver.py` copié à la main.
- [ ] La découverte trouve le flux et les **valeurs** arrivent. ⚠️ Découverte OK ≠ données OK : les
      ports diffèrent (UDP 16571 pour la découverte, TCP 16572-16604 pour les données).
- [ ] Si ça échoue : lire [docs/network.md](network.md) — ping d'abord, isolation client sur WiFi
      d'invités, `lsl_api.cfg` + `KnownPeers` si le multicast est bloqué.

### 3.3 — Unity

⚠️ Les deux scripts C# de [examples/unity/](../examples/unity/) sont écrits contre l'API vérifiée
mais **n'ont jamais été compilés** : il n'y a pas d'Unity sur ce poste.

- [ ] Projet Unity neuf + package LSL4Unity + les deux scripts → **ça compile**.
- [ ] `SsvepIntentReceiver` reçoit les intentions pendant que le moteur tourne.

---

## Ce que cette recette ne teste pas — et pourquoi

À lire avant de conclure que « tout marche ».

- **QUATRE des six modes n'ont jamais été décodés au casque À TRAVERS LE MOTEUR.** Le moteur publie
  maintenant les six — le c-VEP a fermé la marche le 2026-08-21 — mais publier n'est pas décoder un
  cerveau. Le pont modèle → moteur → flux est vérifié sans casque pour tous ; les deux bouts
  ensemble, sur une tête, restent à faire pour le **MI (2.6)**, le **P300 (2.7)**, l'**ErrP (2.8)**
  et le **c-VEP (2.9)**. Ces quatre tests sont l'essentiel de ce qui reste, et une seule séance les
  couvre.
- **La garde de 1,9 Hz autour de l'alpha repose sur une seule personne.** Elle est encadrée par les
  deux seules mesures du projet : 12 Hz à 1,50 Hz du pic échoue, 8,571 Hz à 1,93 Hz marche. n = 1.
  À réviser dès que plusieurs personnes auront été mesurées — c'est exactement le genre de chiffre
  qu'on croit acquis parce qu'il est écrit.
- **Tous les chiffres de ce projet viennent d'UNE personne.** SSVEP, MI, P300, ErrP, c-VEP : une
  tête, souvent une séance. Ce ne sont pas des moyennes, ce sont des points.
- **Le contenu du mode neuro n'a jamais été validé.** Cf. 2.5.
- **Aucune application CLIENTE n'affiche encore un stimulus.** Les quatre fenêtres
  (`src/stimulus/p300.py`, `errp.py`, `cvep.py`, `ssvep.py`) sont des références écrites ici, dans
  ce dépôt, en Python et en pygame. Qu'un moteur de jeu tienne la frame comme le c-VEP l'exige n'est
  vérifié nulle part — c'est le 3.3, et il n'a jamais été joué.
- **La console n'a vu un casque que deux fois, et en partie** — les 2026-09-21 et 2026-09-22 : le
  contrôle alpha, le taux d'émission SSVEP (100 % de justesse le 21 ; 18 annonces sur 36, les 18
  justes, le 22) et **un** entraînement c-VEP (25,0 % pour un hasard à 17 %). Ni les entraînements
  MI, P300 et ErrP, ni **aucun des cinq « Tester »** ni la page en blocs — livrés le 2026-09-22
  APRÈS la séance — n'ont vu un casque. Tout cela est vérifié **hors écran**
  (Qt en `offscreen`, board synthétique, faux processus) : ça prouve le câblage entre deux
  processus, jamais l'ergonomie ni le décodage. Quatre questions n'ont de réponse qu'en séance, et
  les tests 2.1 à 2.9 sont l'occasion de les trancher :
  est-ce que les 15 s de chauffe couvrent vraiment l'écart de lancement fenêtre/moteur **sur cette
  machine** ; est-ce qu'un étudiant comprend qu'un chiffre affiché n'est pas encore un modèle
  enregistré ; est-ce que le **contrôle de liaison bloque une séance légitime** (il refuse dès
  qu'une seule voie sort de [0,5 ; 500] µV, sans porte de sortie) ; et est-ce que le **top sonore**
  du contrôle alpha s'entend vraiment, sur cette machine et avec ce casque audio — c'est le seul
  signal qui dise de rouvrir les yeux.
- **Les mesures n'ont vu qu'UNE tête.** Le contrôle alpha et le taux d'émission SSVEP ont été
  écrits sur du bruit blanc et des sinusoïdes posées à la main, puis joués au casque les 21 et 22
  septembre, sur une seule personne. Les quatre tests nés le 2026-09-22 (MI, P300, c-VEP, ErrP)
  n'ont vu que des signaux synthétiques et des décisions fabriquées — leurs seuils de couleur sont
  argumentés sur UNE séance de référence chacun, et la cloison de l'ErrP n'est prouvée que par son
  autotest. Le repère
  « ratio > ~1,5 » vient d'**une** personne sur ce casque, et la seconde cause d'échec du contrôle
  alpha — « ça monte, mais ce n'est pas de l'alpha » — n'a **jamais** été observée sur un vrai
  signal : le test qui la couvre la fabrique avec une raie à 7,5 Hz, et que ce soit la forme qu'un
  artefact de mouvement prend réellement est une **hypothèse**.
- 🟠 **Un constat parqué de la revue du 2026-09-08 peut encore mordre.** La console prenait
  `accepted` pour « la séance a démarré » ; c'est corrigé pour l'enregistrement de séance et pour le
  lancement des fenêtres d'entraînement et de test (elles attendent de VOIR la séance dans
  `snapshot()`, 2026-09-10), mais le motif n'a pas été audité ailleurs. Le second constat de cette
  ligne — **les refus lancés depuis la GRILLE ne vont que dans le terminal** — est **corrigé depuis
  le 2026-09-10** (`c960e39`) : tout refus s'affiche dans le bandeau (1.13).
- 🟠 **Des refus nomment un bouton qui n'existe plus.** L'aide du réglage « Modèle entraîné » — que
  le moteur recopie dans son refus quand aucun modèle n'existe — dit encore de cliquer « Calibrer »
  (ou « Calibrer le P300 », « Calibrer l'ErrP », « Calibrer le c-VEP ») : c'est « Entraîner » depuis
  le 2026-09-22.
- **Les douze écrans de `archive/` ne sont couverts que par leur `--smoke`**, et par rien d'autre :
  aucun des deux smokes du dépôt ne les exécute. Trois d'entre eux décodent en LOCAL
  (`cvep_pilot.py`, `p300_pilot.py`, `errp_demo.py`) et servent de RÉFÉRENCE en séance — c'est ce
  que le 2.9 exploite pour le c-VEP, et le même geste est désormais possible pour le P300 et l'ErrP.
  ⚠️ Aucun des douze n'a vu un cerveau depuis son archivage, et deux d'entre eux
  (`mi_calibrate.py`, `mi_pilot.py`) écrivent encore sous les anciens noms FIXES : lire
  `archive/README.md` avant.

---

Les résultats chiffrés (2.2, 2.3) méritent d'être recopiés dans
[docs/SPEC.md](SPEC.md) ou dans un commit : ce sont les seules références auxquelles la prochaine
séance pourra se comparer.
