# QA — le tour complet, action par action

Feuille d'exécution. Chaque point donne **ce que tu fais**, **ce que tu dois voir** (✅) et **ce qui
compte pour un échec** (❌). Elle se coche telle quelle, dans l'ordre.

Le détail, l'histoire des défauts et les chiffres de référence vivent dans
[docs/recette.md](recette.md) ; chaque point d'ici renvoie à sa section là-bas quand il y en a une.
Cette feuille-ci est ce qu'on tient à la main ; la recette est ce qu'on relit quand un point tombe.

## Combien de temps

| Bloc | Ce qu'il faut | Durée | Mesurée ? |
|---|---|---|---|
| **0** — autotests | rien | **~6-7 min** | ⚠️ ~6 min chronométrées le 2026-09-10 ; six autotests ajoutés le 2026-09-22, pas rechronométrés |
| **1** — console à l'écran | un écran | **50-60 min** (13 points, dont ~8 min de protocoles minutés) | estimé |
| **2** — au casque | le casque + un sujet | **1 h 30 à 2 h** | estimé (~34 min de protocole minuté, longueurs par défaut) |
| **3.1-3.2** — réseau | une 2e machine | **~20 min** | estimé |
| **3.3** — Unity | Unity installé | **hors barème** | jamais compilé |

**Tout d'affilée, Unity mis à part : ~3 h.** Mais ne le fais pas d'affilée.

**Les blocs 0 et 1 se jouent SANS casque, donc dès maintenant** — et ce sont eux qui attrapent les
régressions. Les passer la veille laisse la séance casque entière pour ce qu'elle seule peut faire.

**Ce que coûte chaque geste au casque**, tel que le moteur l'annonce (`duree_estimee_s`, chauffe de
15 s comprise, écran à 60 Hz). Un test se refait à chaque réglage : il est **court par défaut**, et
sa longueur se choisit sur sa page — l'aide du réglage donne la durée de chaque valeur.

| Geste | Par défaut | Autres longueurs |
|---|---|---|
| Vérifier le casque | **37 s** | aucune — ses durées font corps avec son repère |
| Tester le SSVEP | **≈ 3,6 min** (36 essais : 12 par cible, 3 cibles) | aucune — pas de réglage de longueur |
| Entraîner le c-VEP · Tester le c-VEP | **≈ 3,1 min** · **≈ 1,8 min** (3 cycles par cible, 18 blocs) | test : 2 cycles ≈ 1,3 min |
| Entraîner le P300 · Tester le P300 | **≈ 2,2 min** (12 manches) · **≈ 1,2 min** (6 manches) | test : 12 ≈ 2,2 · 24 ≈ 4,1 min |
| Entraîner l'ErrP · Tester l'ErrP | **≈ 5,7 min** (200 essais) · **≈ 2,4 min** (80 essais) | test : 40 ≈ 1,4 · 200 ≈ 5,7 min |
| Entraîner le MI · Tester le MI | **≈ 7,1 min** (14 essais/classe) · **≈ 2,8 min** (6/classe, 3 classes) | entraîner : 10 ≈ 5,4 min ; test : 4 ≈ 2,0 · 10 ≈ 4,5 min (G/D : 6 ≈ 2,0) |
| Neuro — Observer | 15 s + 25 s de repos, puis à volonté | — |

⚠️ **Au casque, ce n'est pas le protocole qui décide de la durée.** Les ~34 min ci-dessus doublent
avec le montage et le salinage (15-20 min), les briefings, les transitions, les décisions « garder
ou refaire », et **au moins un entraînement à refaire**. Deux contraintes de terrain bornent la
séance par le haut : **la fatigue du sujet**, et **les électrodes qui sèchent** — le gain du
salinage se dégrade en une heure et quelque. C'est pourquoi l'ordre commence par le SSVEP et le
c-VEP, sur sujet frais.

⚠️ **3.3 (Unity) n'est pas un point de dix minutes.** Les deux `.cs` n'ont **jamais été compilés**,
il n'y a pas d'Unity sur la machine de dev, et LSL4Unity reste à importer. Première fois : compte
une demi-journée, et traite-le comme un chantier à part — pas comme la fin d'une passe de QA.

## Passes jouées

**2026-09-21 — blocs 0 et 1 passés, 26 points.** Deux défauts trouvés, corrigés le jour même, tous
deux invisibles aux autotests :

1. **Un bouton « Appliquer » sur un formulaire sans réglage.** Il soumettait un dictionnaire vide,
   le moteur l'acceptait, rien ne changeait. Quatre pages concernées — le Brut et les trois
   entraînements menés par une fenêtre.
2. 🔴 **Un réglage ne pouvait pas se poser sur un mode arrêté.** `set_params` exigeait un mode
   démarré, pendant que `propose_params` — l'autre moitié du même geste — acceptait un mode arrêté
   depuis toujours. En séance, le bouton « appliquer le pic » du contrôle alpha échouait donc à
   tous les coups.

Ce que ça dit de la méthode : ce sont des **désaccords entre deux moitiés d'un même geste**, et aucun
test ne les voyait parce que chaque moitié était testée sur son propre décor.

**2026-09-23 — bloc 0 rejoué, bloc 1 rejoué sur la console du chantier « Configurer · Entraîner ·
Tester ».** 19 autotests verts, `data/` intact. Au bloc 1, tout passe sauf le 1.12 et le 1.13, qui
se jouent au casque, et le verdict du 1.9, passé au point 2.2 : sur le board de test il sort MUET à
tous les coups. Six défauts, tous corrigés le jour même (`0e712cf`, puis la page des flux), aucun
visible aux autotests :

1. Le refus « sans modèle » recopiait l'aide entière du réglage : un paragraphe dans le bandeau.
   Il tient maintenant en une ligne (`Param.si_vide`).
2. Le « rouge » des refus (`#e2603f`) se lisait orange, à côté de l'ambre de « moyen ».
3. « Vérifier le casque » n'encadrait aucune voie, alors qu'il en moyenne quatre.
4. « Décodage de « SSVEP » arrêté pour ce test… » vivait moins d'une seconde : il était dans le
   bloc « Avant de commencer », caché dès le démarrage du test.
5. La page des flux affichait un flux dans sa liste sans l'ouvrir : panneau vide tant qu'on ne
   cliquait pas dessus.
6. La feuille elle-même : trois fenêtres de stimulus au lieu de quatre, une section renommée
   (« Avant tout »), un refus P300 impossible sur un poste qui a un modèle P300 (il se joue sur le
   MI), un bouton mal nommé.

Et une demande, pas un défaut : « Vérifier le casque » devrait juger CHAQUE électrode, pas seulement
l'alpha (constat ouvert n° 4).

Joués ensuite le même jour, sans casque : **1.12 ✅** (casque éteint → « ⛔ LE MOTEUR S'EST ARRÊTÉ »
à l'écran) et **1.13 : 0,6 % de frames sautées en séance ET 0,6 % fenêtre seule.** Ce n'est donc pas
la contention console + moteur : c'est la fenêtre ou le pilote. Sous le seuil de 2 % qui bloquerait
le c-VEP. **Le ramasse-miettes de Python est écarté** : coupé (`gc.disable()`), la fenêtre seule a
sauté 0,4 % puis 0,7 % des images — autant qu'avec lui. Reste le pilote graphique ou Windows, hors
de portée du code ; 0,6 % est acceptable pour le SSVEP comme pour le c-VEP.

**2026-09-24 — les textes réécrits, validés sur pièce.** Après le passage des textes dans
`src/core/langues/` et leur simplification, les textes des écrans du bloc 1 (Brut, pages de mode,
réglages et refus, contrôle de liaison, « Vérifier le casque », Entraîner et Tester le P300) ont été
relus et validés par l'utilisateur, texte par texte. Retouches demandées et faites : les bulles
« ⓘ » collées au libellé plutôt qu'en bout de ligne, l'écran détecté dit « écran principal », une
virgule décimale dans les messages, les « Détails » des quatre tests sans jargon.

**2026-09-24 — bloc 2 au casque, sur la console « Configurer · Entraîner · Tester ».** Première
fois que les « Tester » voient un casque. 2.0 ✅ · 2.1 ✅ · **2.2 : 16 justes sur 17 détections,
17 détections sur 36 essais** (94 % [73 ; 99] à l'émission, 47 % d'émission ; repères : 100 %/44 %,
puis 18/18 le 22/09) · 2.3 ✅ · 2.4 ✅ · 2.5 ✅ · 2.6 **reporté** (pièce trop bruyante pour de
l'imagerie motrice) · 2.7 ✅. Chiffres détaillés du c-VEP, du P300 et de l'ErrP non relevés.
Retours d'écran, tous traités le jour même (visibles au lancement suivant) :
1. la **corrélation inter-voies** n'était affichée nulle part hors alarme → dans le bandeau ;
2. un bon résultat portait un **⚠ orange** sur sa conclusion → ⚠ seulement s'il y a une réserve ;
3. **« AU NIVEAU DU REPÈRE »** ne se comprenait pas → « BON » ;
4. la ligne des chiffres (« 94 % … entre 73 et 99 % … il annonce sur 47 % ») → « Cible détectée
   dans 17 essais sur 36 (47 %) ; rien d'annoncé dans les 19 autres. Sur ces 17 détections, la
   bonne cible 16 fois : 94 % (hasard 33 %). » ;
5. demandé : un réglage pour régler la détection du SSVEP → **« Seuil de détection »** ;
6. la stabilisation puis le repos du Neuro (40 s) sans **indication de temps** → un compte à
   rebours (« décodage dans ≈ 32 s ») sur la tuile, la page du mode et la vue en direct.

**2026-09-21 après-midi et 2026-09-22 matin — deux séances au casque, partielles.** Le SSVEP y a été
mesuré à 100 % de justesse le 21 (avec ~0,7 % de frames sautées), puis à **18 annonces sur 36
essais, les 18 justes** le 22 ; une calibration c-VEP a rendu **25,0 % pour un hasard à 17 %**. Elles
ont surtout produit des constats : six le 21 (table ci-dessous), et le 22 **dix minutes de fixation
perdues sur un mode arrêté**, suivies de « je ne comprends pas trop ce que l'on fait ». C'est
l'origine du chantier suivant.

### Les six constats du 2026-09-21

Tous corrigés le même jour (`9b55b46`), prouvés par mutation. Ils se testaient au point « 1.6 bis »,
qui a disparu le 2026-09-22 : ce qui en reste vit aux points 1.6 et 1.9.

| # | Le défaut | Le correctif | Depuis le 2026-09-22 |
|---|---|---|---|
| 1 | Un réglage différé n'apparaissait pas sur la page — l'écran disait **le contraire de la vérité** | `snapshot()` publie `reglages` ; la page les montre, mode arrêté compris | inchangé — point 1.6 |
| 2 | « Proposer » sur un mode arrêté calculait sur l'alpha de la **population** (9,6 Hz) | `propose_params` lit le magasin | inchangé — point 1.6 |
| 3 | Une page de mode ne savait pas démarrer son mode | bouton Démarrer/Arrêter dans l'en-tête | ⚠️ **retiré de la page** (`d111305`) : le décodage continu se démarre depuis la TUILE ; il reviendra sur la page avec « Connecter » |
| 4 | Le SSVEP n'avait aucun bouton « Lancer le stimulus » | `stimulus_id` sur le `ModeSpec` | ⚠️ **retiré de la page** (`d111305`) : la fenêtre n'est plus qu'un rouage de « Tester » |
| 5 | La fenêtre SSVEP affichait le trio du dépôt quel que soit le réglage | `--freqs`, passé par la console ; une fréquence non affichable est refusée, jamais arrondie | étendu à « Tester » (`b1e4446`) — point 1.9 |
| 6 | La fenêtre SSVEP ne comptait pas les **frames sautées** | compteur `sautées` au HUD + bilan de fin | inchangé — point 1.9 |

## Le chantier du 2026-09-22 : Configurer · Entraîner · Tester

La console parlait le vocabulaire des expériences qui l'ont construite, et mettait à plat
« Démarrer », « Calibrer » et « Lancer le stimulus » alors qu'il existe un ORDRE. Ce qui a changé, en
bref (le pourquoi est en recette 1.19 à 1.21) :

- **Une page de mode = des blocs numérotés, et rien d'autre** : **1. Régler · 2. Entraîner** (si le
  mode a un modèle) **· N. Tester** (si le mode a un test). Le Neuro et le Brut n'ont aucune
  vérité-terrain : **2. Observer**, sans aucun score.
- **« Tester » possède sa séquence entière** : il applique ce qui est à l'écran, ouvre le test
  pré-rempli avec les réglages du mode, et « Commencer » passe le contrôle de liaison, arrête le
  mode s'il tourne, lance la mesure PUIS la fenêtre, et rend un verdict. **Aucun test n'écrit sur
  le disque.**
- **Un résultat se lit en trois lignes** : un MOT coloré (vert / orange / rouge, décidé par le
  MOTEUR), les chiffres avec leur point de comparaison, UNE réserve. Le reste est replié sous
  « Détails ».
- **Vocabulaire** : « Calibrer » → **Entraîner** ; « Taux d'émission SSVEP » → **Tester le SSVEP**
  (plus de tuile) ; « Contrôle alpha » → **Vérifier le casque** (tuile) et **Mesurer** (à côté du
  pic alpha de la page SSVEP).
- **Ont quitté la page, et reviendront avec « Connecter »** (second chantier, pas fait) :
  « Démarrer/Arrêter », « Lancer le stimulus », « Journal de séance », « Brancher un client ».

🔴 **Ce qui n'a PLUS de chemin dans la console jusqu'à « Connecter » — à savoir AVANT la séance :**

- **La séance c-VEP avec journal (recette 2.9)**. La case « Journal de séance » est partie avec
  « Lancer le stimulus » : la console ne passe plus jamais `--log`. Sans ce journal la séance **ne
  se dépouille pas**. En attendant, c'est le montage à trois terminaux de la recette 2.9, ou la
  console pour le casque et la fenêtre tapée à la main à côté (`python src/stimulus/cvep.py --log`) —
  des commandes, donc hors de la règle « aucune commande à taper ».
- **Le décodage continu avec NOTRE fenêtre de stimulus** (SSVEP, P300, ErrP, c-VEP). La tuile
  « Démarrer » décode et publie toujours, mais c'est à l'application cliente — ou à une fenêtre
  lancée à la main — d'afficher le stimulus. Pour savoir si une configuration marche, c'est
  « Tester » qui sert, et il lance sa fenêtre lui-même.

## 🟠 Constats ouverts

**Retirés — corrigés par le chantier du 2026-09-22 :**

- ~~La mesure du taux SSVEP tourne sur le trio du dépôt~~ → « Tester » passe à la fenêtre les
  fréquences du mode (`b1e4446`). La comparabilité aux repères du 2026-07-27 n'est plus une
  contrainte du protocole : c'est à toi de tester sur le trio du dépôt si tu veux comparer (point 2.2).
- ~~L'écran de résultat d'une calibration est illisible~~ → trois lignes en face, le reste sous
  « Détails » (`06eaeb7`, `c3471f0`).
- ~~Le bandeau déverse six lignes à la fermeture normale d'une fenêtre~~ → les deux dernières, son
  bilan (`b9b6529`).

**Retirés aussi — passe de correction des 2026-09-22 et 23 :**

- ~~Des refus et des aides nomment encore « Calibrer »~~ → ils disent « Entraîner », le nom du
  bouton, et leurs assertions avec eux (`c9701fa`). « Recalibre » est parti de la même façon.
- ~~Restes du vocabulaire d'expérience à l'écran~~ → « Commencer le test » au contrôle de liaison
  (`186510f`), « LE MOTEUR NOTE » au lieu d'« ENREGISTRE » pendant un test c-VEP, réponse du pic
  alpha reformulée (`0824088`), `research/ssvep_{analyze,guided}.py` pointent le bloc « Tester ».
- ~~Le briefing du P300 dit le comptage mental indispensable~~ → c'est la FIXATION qui fait l'onde,
  le comptage aide à tenir l'attention (`ad2d8e0`, point 2.4 du 2026-09-22).
- ~~Le contrôle de liaison d'un TEST ne surligne aucune voie clé~~ → il prend les voies clés du
  mode testé (`186510f`).
- ~~Le test ErrP n'affiche pas la durée réelle de son repos~~ → elle est dans la phrase de verdict,
  et le test REFUSE de conclure sur un repos écourté (`136583d`). ⚠️ Cette durée n'a toujours
  jamais été mesurée au casque.
- ~~Les fenêtres disent « calibration » pendant un test~~ → plein écran, fin de séance et abandon
  disent « test », sous assertion (`ad2d8e0`).

**Ouverts :**

1. **La console ne descend pas sous ~1 650 px de large** (relevé par l'auteur de la page en blocs,
   préexistant, non remesuré ici). À vérifier sur l'écran de la séance.
2. **« Appliquer » sur la page d'un mode pendant son test change encore le magasin de réglages.**
   Le bloquer côté interface serait recopier une règle que le moteur doit porter. Parqué avec
   « Connecter ».
3. **Si le flux de marqueurs d'une application n'est pas visible à l'entrée d'une page de mode**,
   la liste retombe sur le flux par défaut et écrase en silence le `stream_in` retenu. Antérieur au
   chantier ; relève de « Connecter ».
4. **« Vérifier le casque » ne vérifie que l'alpha** (passe du 2026-09-23, point 1.2). Demandé :
   que cet écran dise si le signal de CHAQUE électrode est bon (contact, bruit, saturation…), pas
   seulement mesurer l'effet de Berger. À retravailler plus tard — chantier à part.

## Deux mots de vocabulaire, et ils ne sont pas interchangeables

- **❌ Régression** — ça a déjà marché ici. Si ça tombe, quelque chose s'est cassé, et le point est
  bloquant.
- **❌ Échec** — ça n'a **jamais** été vérifié. Si ça tombe, c'est peut-être une découverte, pas une
  casse : note ce que tu as vu, ne conclus pas, et continue. **Tout le bloc 2 sauf le SSVEP est
  dans ce cas** — quatre modes n'ont jamais décodé un cerveau à travers le moteur, et **aucun
  « Tester » n'a jamais vu un casque** (ils datent du 2026-09-22, après la séance).

## Trois règles qui tiennent pendant toute la feuille

1. ⚠️ **Un seul programme du projet à la fois.** Les noms de flux LSL sont un contrat public, donc
   identiques pour toutes les instances : un moteur oublié répond à la place de celui qu'on teste.
   Les fenêtres de `src/stimulus/` sont l'exception — elles n'ouvrent pas le casque, et la console
   les lance elle-même.
2. ⚠️ **Ne jamais fermer/rouvrir la console en cours de séance.** C3 et Cz saturent à la
   réouverture (redémarrage de l'amplificateur). C'est exactement ce que le point d'entrée unique
   rend évitable : entraîner et tester sans fermer la fenêtre qui tient le casque.
3. ⚠️ **Un utilisateur ne tape aucune commande.** Si un point du bloc 1 ou 2 t'oblige à ouvrir un
   terminal pour de l'usage réel (acquisition, décodage, flux sortant), **c'est le point qui a
   échoué**, pas toi. Hors de cette règle : les autotests du bloc 0 (ils s'adressent au
   développeur), et les deux trous listés plus haut, connus et datés.

---

# Bloc 0 — sans casque, sans écran (les autotests)

À passer avant de brancher quoi que ce soit. **Aucun moteur ne doit tourner pendant ces tests**, et
jamais deux en parallèle : ils publient sur les mêmes noms de flux (collision vue le 2026-09-22,
« le flux qualité ne publie pas » — relancer seul avant de conclure).

### ☐ 0.1 — Les deux autotests principaux

```bash
python src/core/server.py --smoke
python src/console/app.py --smoke
```

✅ Les deux finissent par `VERDICT : OK` et sortent en **0** (`echo $?` / `echo %ERRORLEVEL%`).
✅ `[smoke-frontiere] … 0 violation(s) de frontière`, précédée de **trois** lignes « existe » —
`src/stimulus/`, `src/research/`, `src/console/` — chacune suivie d'un compte de fichiers non nul
(`core` est le quatrième paquet, scanné en premier).
✅ `[smoke-exemples] … 0 faute(s)`, avec un nombre de fichiers **non nul** et au moins 5 noms de
flux trouvés.
✅ `[smoke-textes] N textes en français, M appels à tr(), 0 faute(s)` — N et M **non nuls** (≈ 700
et ≈ 780 le 2026-09-23). Aucun texte affiché n'est écrit en dur : ils vivent dans
`src/core/langues/fr/*.json`.

❌ Régression : un seul `ÉCHEC`, ou une sortie ≠ 0. Ne pas continuer : tout le reste de la feuille
suppose ce bloc vert.
❌ Régression **silencieuse à surveiller** : `0 fichier(s)` ou `0 nom(s) de flux` dans
`[smoke-exemples]`, ou `0 violation` avec un compte de fichiers qui a chuté. « Rien trouvé » n'est
pas « rien à trouver » — c'est la garde muette que ces compteurs existent pour rendre visible.

### ☐ 0.2 — Les quatre fenêtres de stimulus

```bash
python src/stimulus/ssvep.py --smoke
python src/stimulus/cvep.py --smoke
python src/stimulus/p300.py --smoke
python src/stimulus/errp.py --smoke
```

✅ Quatre `VERDICT : OK`, quatre sorties à 0. Aucune fenêtre ne s'ouvre (pilote SDL factice).

❌ Régression : n'importe lequel en rouge. `cvep.py --smoke` en particulier porte **le** test du
sous-système c-VEP (la phase relue dans les pixels, frame par frame) ; `ssvep.py --smoke` porte
depuis le 2026-09-10 le test d'**ordre** flip → marqueur.

### ☐ 0.3 — Les gardes de module que les deux gros autotests n'exécutent pas

La liste complète est dans [CLAUDE.md](../CLAUDE.md) (« Commandes utiles »). Le minimum avant une
séance, parce que ce sont les sous-systèmes que la séance va exercer :

```bash
python src/core/modes/mesure.py
python src/core/modes/mesure_marqueurs.py
python src/core/modes/affichage.py
python src/core/modes/alpha.py
python src/core/modes/ssvep_mesure.py
python src/core/modes/marker_calib.py
python src/core/modes/p300.py
python src/core/modes/cvep.py
python src/core/modes/mi_test.py
python src/core/modes/p300_test.py
python src/core/modes/cvep_test.py
python src/core/modes/errp_test.py
python src/core/acquisition.py --synthetic
python src/core/i18n.py
```

✅ Quatorze sorties à 0.

❌ Régression : n'importe lequel en rouge. Ceux dont l'échec compte le plus : `modes/p300.py` et
`modes/cvep.py` (leur panne caractéristique fait décoder du bruit **avec une confiance élevée**),
et `modes/errp_test.py`, qui porte **la cloison d'étiquette** du test ErrP — une fuite y donne un
score parfait et faux, sans rien casser.

### ☐ 0.4 — Aucun test n'a touché `data/`

```bash
python -c "import sys;sys.path.insert(0,'src');from core.config import DATA_DIR,empreinte_dossier;e=empreinte_dossier(DATA_DIR);print(len(e),'fichiers')"
```

✅ Le même nombre de fichiers **avant et après** le bloc 0.

❌ Régression : le compte a bougé. ⚠️ **`git status --short data/` ne prouve RIEN** — le dossier est
gitignoré, il rend une sortie vide même après une écriture. `data/` porte des enregistrements EEG
d'une personne identifiable sur un dépôt public : un test n'y écrit jamais.

---

# Bloc 1 — la console à l'écran, sans casque

Board de test BrainFlow : signal artificiel, aucun matériel. **Un seul lancement pour tout le
bloc** — on ne ferme pas la fenêtre entre deux points. ⚠️ Sur ce signal fabriqué, **aucun verdict
n'a de sens** : on vérifie les gestes, l'ordre, les refus et la forme des résultats, jamais leurs
chiffres.

Lancement : **double-clic sur `outils/Console EEG.bat`**. (Le `--synthetic` de la recette est un
raccourci de développeur qui saute l'écran de départ ; ici on veut justement voir cet écran.)

### ☐ 1.1 — L'écran de départ, et l'absence de repli

La console s'ouvre sur une question : sur quoi ouvrir la session ?

✅ Deux choix explicites : **« Casque Unicorn Hybrid Black »** et **« Board de test, SANS casque »**.
✅ Sous le casque, un champ **« Numéro de série du casque »** (liste modifiable), grisé quand le
board de test est coché. Vide + OK → refus en rouge, le dialogue reste ouvert.
✅ Choisir le board de test → un bref « Démarrage du board de test… », puis la grille s'ouvre, et
**le bandeau du haut répète la source** tant que la console tourne.

❌ Régression : la console ouvre directement la grille sans demander ; ou le bandeau ne dit pas la
source ; ou — le plus grave — un casque introuvable **bascule tout seul** sur le board de test.
Un repli silencieux fait enregistrer une séance entière de signal fabriqué en croyant tenir du vrai.

→ recette 1.17

### ☐ 1.2 — La grille : sept tuiles, UNE tuile de séance

✅ **Sept tuiles**, sur deux rangées : Brut · SSVEP · c-VEP · Neuro, puis Motor Imagery · P300 ·
ErrP. Chacune porte sa case **« publié »**, **« Démarrer »** et **« Ouvrir »**.
✅ **Aucune n'est grisée**, même sans modèle entraîné : le manque de modèle se dit au clic, par un
refus (point 1.6), pas par une tuile éteinte.
✅ Dessous, **« Avant tout »** avec **une seule** tuile : **« Vérifier le casque »**,
marquée *BARRIÈRE — à passer avant tout le reste*.
✅ Tout en bas, **« La sortie »** et le bouton **« Ce que voit ton application »**.

❌ Régression : une tuile de mode manquante ; une tuile « Taux d'émission SSVEP » ou « Tester le … »
sur l'accueil — un test vit sur la page de SON mode, pas sur la grille.

→ recette 1.1, 1.2

### ☐ 1.3 — Le Brut montre vraiment le signal, et les tracés ne se chevauchent pas

Tuile **Brut** → « Ouvrir ».

✅ Deux blocs : **« 1. Régler »**, qui dit « Aucun réglage à changer ici. » (ni « Appliquer », ni
bulle ⓘ), et **« 2. Observer »**, sans bouton — les tracés lisent le tampon
d'acquisition, il n'y a rien à démarrer.
✅ Huit tracés qui défilent, une étiquette par voie (Fz, C3, Cz, C4, Pz, PO7, Oz, PO8), et **qui
restent séparés** quelle que soit l'amplitude.
✅ La ligne grise sous le graphe annonce l'écart **en vigueur** (« un couloir = … µV ») et **ce
chiffre change** quand l'amplitude du signal change.
✅ « ← Modes » revient à la grille.

❌ Régression : les tracés se chevauchent ; l'écart annoncé ne bouge jamais ; une voie hors échelle
est rognée **sans que la ligne grise la nomme** ; un bouton « Appliquer » qui n'aurait rien à
appliquer.

→ recette 1.3

### ☐ 1.4 — Le bandeau vit

✅ Les σ se mettent à jour (~1 Hz), une valeur par voie.
✅ La **corrélation inter-voies** est affichée en permanence (« corrélation inter-voies 0,38 (sain :
0,3 à 0,5) ») — depuis le 2026-09-24 ; avant, elle n'apparaissait que dans l'alarme au-delà de 0,90.
⚠️ Sur board de test, elle monte à ~0,80-0,83 : c'est **normal** (signal artificiel corrélé), le
seuil d'alarme est à 0,90. **N'en tire aucune conclusion.** Sur casque réel c'est 0,31-0,50.

❌ Régression : les σ restent figés, ou le bandeau alarme sur un montage sain.

→ recette 1.4

### ☐ 1.5 — La page d'un mode : ses gestes numérotés, et pas un de plus

Ouvre les sept pages une à une (tuile → « Ouvrir »).

| Page | Blocs attendus, dans cet ordre |
|---|---|
| SSVEP | **1. Régler · 2. Tester** |
| c-VEP · P300 · ErrP · Motor Imagery | **1. Régler · 2. Entraîner · 3. Tester** |
| Neuro | **1. Régler · 2. Observer**, avec un bouton « Observer » |
| Brut | **1. Régler · 2. Observer**, sans bouton (point 1.3) |

✅ **Aucune page** ne porte « Démarrer », « Lancer le stimulus », « Journal de séance » ni le bloc
« Brancher un client » : ils reviendront avec « Connecter ».
✅ Sur les cinq pages qui ont « Tester », une case **« Décodage en direct »**, **décochée** : la
cocher déplie la vue en direct et l'état (« arrêté » tant que le mode ne tourne pas), sous la phrase
« Vide tant que le décodage continu est arrêté. Il se démarre depuis la tuile du mode, sur
l'accueil. » L'en-tête de ces pages, lui, n'affiche **aucun** état.
✅ **Neuro** : « Observer » démarre le mode ; le libellé ne passe à « Arrêter » qu'une fois le moteur
d'accord (état reçu, pas une bascule locale). La vue défile en face, sans aucun chiffre de justesse.
✅ **Page c-VEP** (le cas extrême : six réglages), coche « Décodage en direct » puis **réduis la
fenêtre en hauteur** : le corps défile, « 3. Tester » se rejoint en faisant défiler, et **« ← Modes »
reste visible** (l'en-tête ne défile pas).
✅ **Aucune aide en clair sous les réglages** : chaque réglage qui a une aide porte une bulle
**« ⓘ »** bleue juste après son libellé ; la survoler (ou survoler le champ) montre l'aide complète,
qui passe à la ligne. Plus de case « Aide détaillée » (2026-09-23).

❌ Régression : un bloc hors de cette table, ou dans un autre ordre ; un des quatre boutons partis
revenu sur une page ; un score annoncé sous « Observer » (Neuro et Brut n'ont aucune bonne réponse
à comparer) ; le bas de page inatteignable.

→ recette 1.19

### ☐ 1.6 — Un réglage : retenu en vert, refusé en rouge, et le refus toujours à l'écran

Page **SSVEP**, mode **arrêté**, dans cet ordre.

1. « Pic alpha de la personne » à `10,5` → **Appliquer**.
   ✅ En **vert** : « Réglage RETENU : « SSVEP » est arrêté. « Tester » et le prochain décodage
   partiront avec. »
2. Reviens à la grille (« ← Modes »), puis rouvre la page SSVEP.
   ✅ Le champ affiche toujours **10,5**. ❌ Régression : retombé à 9,6 — l'écran dirait le contraire
   de ce que le moteur a retenu.
3. **« Proposer « Fréquences des cibles » »** (l'un ou l'autre des deux boutons).
   ✅ **8,571 · 15 · 20**, le jeu accordé à un pic de 10,5 Hz. ❌ Régression : `12 · 15 · 20`, le jeu
   accordé au pic de la **population** (9,6 Hz).
4. « Fréquences des cibles » à `15, 17` → **Appliquer**.
   ✅ Un refus **en rouge franc** (plus le corail qui se lisait orange, passe du 2026-09-23) qui
   nomme le coupable et propose les voisins : « 17 Hz n'est pas un
   diviseur entier de 60 Hz […] Les plus proches sont 15 et 20 Hz ».
   ✅ La saisie fautive **reste dans le champ**, et le refus rappelle ce qui reste **en vigueur**.
   ❌ Régression : « « SSVEP » n'est pas démarré » au lieu du refus sur les fréquences (le
   comportement d'avant le 2026-09-21).
5. Remets `12, 15, 20` → **Appliquer** → vert.
6. Grille → tuile **Motor Imagery** (sans modèle sur ce poste) → **Démarrer**.
   ✅ Le refus apparaît **dans le bandeau**, en haut de la fenêtre — pas seulement dans la console
   cmd — et il tient en **une ligne** : « Aucun modèle entraîné : dans la console, clique
   « Entraîner » sur la page du mode. »

❌ Régression : (6) écran strictement immobile après le clic — le défaut 1.13, corrigé le
2026-09-10 ; un refus qui dit encore « Calibrer » (corrigé par `c9701fa`) ; ou le paragraphe d'aide
du modèle recopié derrière « aucun choix disponible » (passe du 2026-09-23).

→ recette 1.8, 1.9, 1.13

### ☐ 1.7 — Le contrôle de liaison REFUSE, et ne se contourne pas

Il s'intercale devant **chaque** « Commencer » : Vérifier le casque, Entraîner, Tester. Tu le verras
aux points 1.8 à 1.10 ; regarde-le une fois pour lui-même.

✅ Un écran « Contrôle de la liaison casque » montre **le σ de chacune des huit voies**, un verdict par
voie, et deux boutons : **« ← Annuler »** et un bouton de lancement qui dit ce qu'il lance.
✅ **Partout**, une phrase « Voies clés : … (encadrées). Saline-les en priorité. … », et ces lignes-là
**encadrées en bleu** : les voies du mode sur « Entraîner » et « Tester » (le test prend celles de
son mode, `186510f`), et **Pz, PO7, Oz, PO8** sur « Vérifier le casque » — les quatre qu'elle
moyenne (passe du 2026-09-23). Le refus porte sur les huit dans tous les cas.
✅ Sur board de test, les huit passent (σ mesurés de 7 à 73 µV) et on continue.
✅ « ← Annuler » ramène à la page d'où l'on venait.

❌ Régression : l'écran n'apparaît pas, ou il laisse passer une voie hors de **[0,5 ; 500] µV** ;
« Vérifier le casque » sans aucune voie encadrée.
⚠️ **Il n'y a AUCUNE porte de sortie, et c'est délibéré** — un contournement à un clic est un
contournement qu'on prend par réflexe. Si au casque une électrode refuse de descendre sous le
seuil, **c'est une décision à prendre devant le casque**, pas un bug à corriger dans l'urgence.

### ☐ 1.8 — « Mesurer » le pic alpha depuis la page SSVEP, et un résultat en trois lignes

Page **SSVEP** → **« Mesurer »**, à droite du champ « Pic alpha de la personne ». ~37 s.

✅ La page **« Vérifier le casque »** s'ouvre — la même que la tuile de l'accueil — et son bouton de
retour dit **« ← SSVEP »**.
✅ Briefing, puis **« Commencer »** → contrôle de liaison → le décompte, et **un top sonore à chaque
changement d'étape** (la moitié se fait les yeux fermés). Sans son, la page **le dit** avant de
commencer.
✅ **Le résultat, en trois lignes en face** : un **mot** en couleur (« ALPHA NET » en vert, ou
« ARRÊTE ICI » en rouge), une ligne de **chiffres**, **une** phrase de réserve. Puis une case
**« Détails »**, décochée : elle déplie la ligne BARRIÈRE, la phrase de verdict complète, le ratio,
le pic, les voies moyennées et la phrase d'honnêteté — et **le repli RESTE ouvert** tant que tu ne
le refermes pas. ❌ Régression : il se referme tout seul au bout d'un instant (le défaut corrigé par
`07a3303` : chaque rafraîchissement le décochait, dix fois par seconde).
✅ Si « ALPHA NET » : un bouton « Appliquer « Pic alpha de la personne » = … Hz à « SSVEP » » →
réponse en vert → **« ← SSVEP »** → le champ montre la valeur mesurée, sans rien retaper.
⚠️ Sur ce signal fabriqué, les deux verdicts sont possibles et aucun ne veut rien dire. Si c'est
« ARRÊTE ICI », il n'y a **pas** de bouton « Appliquer » — c'est voulu (le « pic » d'un spectre sans
alpha est un bin de bruit) ; la boucle se joue au casque, point 2.1.

❌ Régression : « ← » ramène à l'accueil au lieu de la page SSVEP ; un résultat sans couleur ; un
repli « Détails » qui contient moins que ce qu'il affichait avant (tout y est RANGÉ, rien n'est
supprimé).

→ recette 1.21, 2.1

### ☐ 1.9 — « Tester » le SSVEP : les gestes et l'ordre (~1 min)

⚠️ **Ici on ne va PAS au bout** : sur le board de test il n'y a aucun SSVEP dans le signal, le verdict
sort MUET à tous les coups (vu le 2026-09-23) et 3,6 min n'apprennent rien. **Le test complet et son
verdict se jouent au casque, point 2.2.** Ce point-ci vérifie les gestes, l'ordre, et l'abandon.

Pour vérifier qu'un test arrête le mode, **démarre d'abord le SSVEP** depuis sa tuile, puis ouvre sa
page.

1. Tape `12, 15, 20` dans « Fréquences des cibles » **sans cliquer « Appliquer »**, puis
   **« Tester »**.
   ✅ La page **« Tester le SSVEP »** s'ouvre, retour « ← SSVEP ». Reviens voir : le champ dit
   **12, 15, 20** et c'est ce que le moteur a retenu — « Tester » applique ce qui est à l'écran.
   ❌ Régression : le test part sur l'ancienne configuration, sans rien dire.
2. Tape `15, 17` → **« Tester »**.
   ✅ Le refus s'affiche **sous « 1. Régler »**, et la page de test **ne s'ouvre pas** : tester une
   configuration impossible ne mesurerait rien.
3. Remets `12, 15, 20` → **« Tester »** → **« Commencer »** → contrôle de liaison → **« Commencer
   la mesure »**.
   ✅ Sous l'en-tête de la page, en gris : « Décodage de « SSVEP » arrêté pour ce test : les deux ne
   tournent pas ensemble. Il restera arrêté ensuite. Relance-le depuis sa tuile si ton application
   en a besoin. » **Elle reste affichée** pendant le test et après. ❌ Régression : elle
   disparaît dès que le test démarre (le défaut du 2026-09-23 — elle vivait moins d'une seconde).
   ✅ **Puis** la fenêtre s'ouvre, plein écran : **trois** flèches étiquetées **12.00 · 15.00 ·
   20.00 Hz**, une croix pour le repos, puis une flèche **entourée de bleu** par essai. Le HUD affiche
   `… fps | sautées N | ESC = quitter`.
   ❌ Régression : `15 · 20 · 8,571` à l'écran — le trio du dépôt, pendant que le moteur corrèle
   sur 12 · 15 · 20.
   ✅ Pendant ce temps la page montre « Mesure en cours », le décompte et une barre d'avancement.
4. Après quelques essais, **« Abandonner »** sur la page.
   ✅ La fenêtre se ferme **toute seule** (pas besoin d'Échap), et la page dit « La fenêtre du test
   a été fermée : la séance s'est interrompue ».
   ✅ Aucun verdict n'est inventé sur une séance coupée.
   ✅ La tuile SSVEP dit **« arrêté »** et le reste : le décodage continu se relance depuis sa tuile.
   ✅ `data/` n'a rien gagné (empreinte du point 0.4).

❌ Régression : la fenêtre s'ouvre **avant** que la page ne passe à « Mesure en cours » (l'ordre
moteur → fenêtre est un contrat testé) ; une fenêtre qui survit à « Abandonner » ; un fichier écrit.

→ recette 1.20

### ☐ 1.10 — Entraîner puis Tester : le P300 (~2,2 + 1,2 min)

Le plus court des modes à modèle. Page **P300**.

1. **Le refus sans modèle se joue sur la page d'un mode qui n'en a AUCUN** — sur ce poste, le
   **Motor Imagery** (le P300 a un modèle du 2026-08-17 dans `data/`, l'ErrP et le c-VEP aussi).
   Page **Motor Imagery** → **« Tester »**.
   ✅ Refus sous « 1. Régler » (« Aucun modèle entraîné : dans la console, clique « Entraîner » sur
   la page du mode. »), et le test ne s'ouvre pas. C'est le moteur qui tient l'ordre Entraîner →
   Tester, pas l'écran.
2. Page **P300** → **« 2. Entraîner »** → **« Entraîner »**.
   ✅ La page **« Entraîner le P300 »**, retour **« ← P300 »** : briefing, **« Commencer »** →
   contrôle de liaison → **« Commencer l'entraînement »**.
   ✅ La console **lance elle-même la fenêtre P300**, **après** que le moteur a démarré.
   ✅ À la fin : trois lignes en face, une ligne ambre « ⚠ Pas encore enregistré : ce modèle est dans
   un dossier temporaire. … », et **« Enregistrer le modèle »** / **« Refaire »**.
3. **« Refaire »** → rien n'a été écrit dans `data/` (empreinte). Relance, puis **« Enregistrer le
   modèle »** → « Modèle en place : … ».
4. **« ← P300 »** → le modèle est dans la liste « Modèle entraîné », horodaté, **en tête** et
   sélectionné (la liste va du plus récent au plus ancien), sans redémarrer.
5. **« 3. Tester »** → **« Tester »**.
   ✅ La page **« Tester le P300 »** est **pré-remplie** : même modèle que la page du mode, et
   « Manches » à **6**.
   ✅ « Commencer » → contrôle de liaison → la fenêtre s'ouvre **en test** : son écran de fin dit
   « Test terminé », et le bandeau « … test terminé(e) : 6 manches … le moteur note, le verdict
   s'affiche dans la console ».
   ✅ Le résultat porte **« (hasard 17 %) sur 6 manches »** — jamais 50 %.
   ✅ Rien n'a été écrit dans `data/` : un test n'a ni « Enregistrer » ni « Refaire ».

❌ Régression : le chiffre d'entraînement s'affiche **après** l'écriture du modèle ; « Refaire »
laisse un fichier ; le modèle enregistré n'apparaît pas dans la liste sans redémarrer ; la fenêtre du
test dit « CALIBRATION » ; un test qui écrit dans `data/`.
⚠️ **Vérifie `data/` par empreinte**, pas par `git status` — le dossier est gitignoré.

→ recette 1.14, 1.20

### ☐ 1.11 — « Ce que voit ton application » : le flux sortant, vu comme un client

Grille → tuile **SSVEP** → **« Démarrer »** ; attends ~23 s (chauffe + repos). Puis, en bas de la
grille, **« Ce que voit ton application »**.

✅ Les flux LSL **du réseau** apparaissent, avec leurs voies et des valeurs qui défilent — **celles
du flux affiché dans la liste, tout de suite, sans cliquer dessus**. ❌ Régression : un flux affiché
dans la liste et un panneau vide tant qu'on ne le re-choisit pas (défaut du 2026-09-23).
✅ ⚠️ Le panneau lit **par LSL, comme un client** — pas l'état interne du moteur. Décoche « publié »
sur la tuile SSVEP puis relance « Chercher les flux » : `decoded_ssvep` doit **disparaître**, et
l'absence se **dire**. S'il défile encore, il regarde le mauvais endroit. En revenant sur la page
après l'avoir décoché, elle dit « « …decoded_ssvep » n'est plus visible sur le réseau » et **n'ouvre
pas un autre flux à sa place**.
✅ **« Enregistrer les verdicts »** → un fichier `moteur_<flux>_AAAAMMJJ-HHMMSS.jsonl` dans
`seances/`, **une ligne par décision publiée**, et l'écran dit **où et combien**. Le même bouton
l'arrête.
✅ `seances/` est **hors de `data/`**.

❌ Régression : le panneau défile alors que le réseau est muet ; le chemin du fichier n'est pas
affiché.

→ recette 1.18

### ☐ 1.12 — Un casque qui refuse de s'ouvrir : la question est reposée

Il suffit d'un casque **éteint** (ou d'un numéro faux) : **choisir « Casque Unicorn »** → OK.

✅ Une fenêtre « Connexion au casque « … »… » avec **« Abandonner »**, pendant l'ouverture Bluetooth.
✅ Puis l'**écran de départ revient**, avec en rouge « Le casque « … » ne s'est pas ouvert (raison
de BrainFlow)… », le **casque toujours coché** et son numéro dans le champ. Allume le casque (ou
corrige le numéro) → OK → la console s'ouvre.
✅ Le numéro qui a réussi est proposé en premier au lancement suivant ; celui qui a échoué, non.

❌ Régression : la console s'affiche figée avec « ⛔ LE MOTEUR S'EST ARRÊTÉ » (le comportement
d'avant le 2026-09-25) ; ou — le plus grave — l'écran revient avec le **board de test** coché à la
place du casque, ou s'ouvre dessus tout seul.
⚠️ « ⛔ LE MOTEUR S'EST ARRÊTÉ » existe toujours, mais seulement pour une liaison perdue EN COURS de
séance (batterie, distance) — difficile à provoquer volontairement.

→ recette 1.17

### ☐ 1.13 — La cadence de l'écran, ISOLÉE (diagnostic, pas une barrière)

⚠️ **Ce point ne se passe ni ne se rate** : il MESURE, et c'est la comparaison de deux chiffres
qui a du sens. Il répond à une question posée en séance le 2026-09-21 : « j'ai toujours ~4 frames
sautées toutes les 10 s, périodiquement ». Périodique, ce n'est pas du jitter — c'est une **pause
de processus**, et il y a trois suspects.

**(a)** Relève d'abord le taux **EN SÉANCE**, console et moteur en marche : c'est le bilan que le
bandeau affiche à la fermeture de la fenêtre d'un test **mené à son terme** (point 2.2, ou
n'importe quel test du bloc 2 — plus le 1.9, qui s'abandonne).
**(b)** Puis **ferme la console** — rien d'autre du projet ne doit tourner — et lance la fenêtre
SEULE. Elle n'ouvre pas le casque, donc il n'y a rien à démonter :

```powershell
python src/stimulus/ssvep.py --seconds 60 --freqs 12,15,20
```

✅ Un bilan s'imprime : `fin : N frames affichées, M sautée(s) (x %)`. **Note le pourcentage.**

| (a) en séance | (b) isolée | Conclusion |
|---|---|---|
| ~0,7 % | **~0 %** | **Contention** : le moteur décode à ~5 Hz et la console sonde à 10 Hz sur la même machine. Levier réel, et il ne touche pas la fenêtre. |
| ~0,7 % | **~0,7 %** | La fenêtre ou le pilote. ⚠️ Le **GC de Python** a été testé et **écarté** le 2026-09-23 (0,4 % puis 0,7 % avec `gc.disable()`) : c'est le pilote graphique ou Windows. |
| **> 2 %** partout | — | 🔴 À traiter AVANT toute séance c-VEP : à ce niveau, la phase ne se résorbe plus entre deux cycles. |

⚠️ **Le seuil qui compte n'est pas le même selon le mode.** Pour le SSVEP, 0,7 % est négligeable —
mesuré le 2026-09-21 : 100 % de justesse avec ce taux-là. Pour le **c-VEP**, chaque saut décale la
phase jusqu'au marqueur de cycle suivant (~1/s) qui la résorbe : à 0,7 % ça fait ~0,4 frame
d'erreur par cycle, tolérable. Au-delà de ~2 %, l'erreur ne se résorbe plus et le mode **ne décode
plus rien, en silence** — sa panne caractéristique.

---

# Bloc 2 — au casque

⚠️ **Sauf le SSVEP, rien de ce bloc n'a jamais décodé un vrai cerveau à travers le moteur, et aucun
« Tester » n'a jamais vu un casque.** Les autotests prouvent le câblage, jamais l'ergonomie ni le
décodage. Un point qui tombe ici est **❌ Échec**, pas régression : note ce que tu vois, ne conclus
pas.

**Ordre arrêté, à ne pas rouvrir : Contact → SSVEP → c-VEP → P300 → ErrP**, puis MI et Neuro si le
sujet tient. Le SSVEP en référence du jour : s'il échoue, c'est la séance qui est mauvaise, pas le
mode. Le c-VEP tôt, sur sujet frais, parce que sa panne caractéristique est un décodage *dégradé
mais plausible*.

⚠️ **On réentraîne TOUT.** Aucun modèle déjà sur le disque n'est utilisé, même vérifié chargeable.

⚠️ **La boucle d'un mode à modèle est toujours la même** : « Entraîner » → lire le chiffre →
« Enregistrer le modèle » ou « Refaire » → « ← » → « Tester » (pré-rempli avec ce modèle) → lire le
verdict. Un chiffre d'entraînement est **hors ligne** (sa réserve le dit) ; c'est le test qui dit ce
que le mode fait vraiment.

### ☐ 2.0 — Le montage (chaque point a déjà coûté une séance)

✅ **Saliner les électrodes** — c'est le levier de qualité le plus fort mesuré ici (+130 % d'ITR sur
le c-VEP).
✅ **Les mastoïdes sont posées** — oubliées au moins deux fois. Une référence décollée produit un
signal qui *ressemble* à du signal.
✅ Casque bien serré, câble dégagé, sujet assis et calé.

✅ Au bandeau, la corrélation inter-voies autour de **0,3 à 0,5**.

❌ Échec : une corrélation qui monte vers **1** (alarme rouge « RÉFÉRENCE DÉCROCHÉE » au-delà de
0,90) = la référence flotte. Ne rien enregistrer, reprendre le montage.

### ☐ 2.1 — Vérifier le casque — **BARRIÈRE** (à faire en PREMIER)

Grille → **« Vérifier le casque »** → « Ouvrir » (ou, c'est la même page : page SSVEP →
**« Mesurer »**) → briefing → **« Commencer »**. **37 s** : stabilisation, 8 s **yeux ouverts**,
8 s **yeux fermés**, un **top sonore** à chaque changement.

✅ Le mot en face : **« ALPHA NET »** (vert) ou **« ARRÊTE ICI »** (rouge). Ratio et pic dans la
ligne de chiffres.
✅ Ratio **> ~1,5** → un bouton propose d'**appliquer le pic mesuré** au « Pic alpha » du SSVEP :
**accepte**. Le SSVEP n'a **pas** besoin d'être démarré — le réglage est validé, retenu, et affiché
en vert.
✅ Si le son est coupé, la page **le dit** et prévient qu'on ne saura pas quand rouvrir les yeux.

❌ **ARRÊTE ICI** si le ratio ne monte pas. Sans alpha, **aucun autre test de la séance ne veut rien
dire**. Reprendre le montage (électrodes occipitales, mastoïdes, saline), puis refaire ce point.
⚠️ Le repère « > ~1,5 » vient de **UNE personne, sur ce casque** : un ratio à 1,4 est une raison de
reprendre le montage et de remesurer, pas de conclure.
⚠️ La seconde cause d'échec — « ça monte, mais ce n'est pas de l'alpha » (pic hors bande) — **n'a
jamais été vue sur un vrai signal**. Si elle sort, c'est une première : note tout.

→ recette 2.1

### ☐ 2.2 — SSVEP : Tester, la référence du jour (~3,6 min)

Page **SSVEP** → vérifie « 1. Régler » : ton **pic alpha** (point 2.1), et des fréquences dont
**aucune** ne tombe dessus — sinon **« Proposer « Fréquences des cibles » »** et prends ce que le moteur propose.
Puis **« Tester »** → « Commencer ».

✅ **« Seuil de détection »** (depuis le 2026-09-24, défaut 2,5) : de combien le score d'une cible
doit dépasser le bruit de fond du repos. Plus bas = plus de détections et plus d'erreurs ; plus haut
= l'inverse. La page de test le montre **grisé**, avec la valeur réglée ici : le test part avec. La
boucle : régler → « Tester » → comparer. ⚠️ Deux tests de 36 essais ont des intervalles larges : lis
les deux intervalles (sous « Détails ») avant de dire qu'un seuil fait mieux qu'un autre.

⚠️ **Pour comparer aux repères du 2026-07-27, teste sur le trio du dépôt : 15 · 20 · 8,571.** C'est
sur lui qu'ils ont été mesurés. Mais si ton pic alpha est sous ~10,5 Hz, la cible à 8,571 Hz tombe
dans ton alpha — prends alors le jeu proposé, et **note que le chiffre n'est plus comparable**.

✅ **Fixe la flèche entourée de bleu**, dans la fenêtre. Pendant le **REPOS** du début, fixe la
**croix** et ne suis aucune flèche : le moteur y mesure son fond de corrélation.
✅ **Ne ferme pas la fenêtre à la main** : sans son marqueur de fin, aucun verdict.
✅ Deux chiffres dans la même ligne : la **justesse quand il annonce** et le **taux d'émission** — à
lire ENSEMBLE. Repères du **2026-07-27** : **100 % de justesse** (0 confusion sur 36) pour **44 %
d'émission**. Le 2026-09-22 : 18 annonces sur 36, les 18 justes.
✅ Le mot : vert si justesse ≥ 90 % **et** émission ≥ 44 % ; orange au-dessus du hasard ; rouge si
le **test binomial exact** ne rejette pas le hasard (p ≥ 0,05), ou **MUET** si le moteur n'a rien
annoncé. ⚠️ Wilson reste l'intervalle AFFICHÉ ; depuis le 2026-09-22 il ne décide plus rien.
✅ La fenêtre se ferme **seule** à la fin. Le **bandeau** affiche ses deux dernières lignes — son
bilan « fin : N frames affichées, M sautée(s) (x %) », et l'alerte si trop d'images ont sauté —, pas
le journal essai par essai. **Relève le x %** (point 1.13).
✅ Le résultat en trois lignes — le mot, les chiffres (« … de cibles justes quand il annonce …
(hasard 33 %) · il annonce sur … des 36 essais »), une réserve —, le reste sous « Détails ».
✅ La note grise « Décodage de « SSVEP » arrêté pour ce test… » est encore là, et le SSVEP reste
arrêté. `data/` n'a rien gagné.

❌ Régression : la justesse s'effondre — c'est le **seul** mode déjà validé sur un cerveau : suspecte
la séance (contact, saline, fatigue) avant le code.
⚠️ **Un essai = UNE décision.** Un effectif ~7× plus grand que 36, c'est que les fenêtres glissantes
ont été comptées comme indépendantes.
⚠️ Depuis le 2026-09-22 ce test **décide par le runtime du mode** (l'écart de σ — 8 voies ici,
4 occipitales filtrées dans le mode — est supprimé). **Le prix : ces chiffres ne se comparent plus
tels quels au 100 %/44 % du 2026-07-27**, mesuré sous l'ancienne règle. C'est écrit dans « Détails ».

→ recette 2.2

### ☐ 2.3 — c-VEP : Entraîner puis Tester

Page **c-VEP** → **« Entraîner »** (~3,1 min, stabilisation du casque comprise) → « Commencer ».

✅ La fenêtre c-VEP s'ouvre **toute seule**, blocs entrelacés.
✅ Le chiffre : une **justesse eCCA (validation croisée)** contre **son** hasard (1/6 ≈ 17 %, jamais 50 %), et sous
« Détails » le test **McNemar** qui compare les deux décodeurs — pas l'écart des deux pourcentages.
Repères du dépôt : **59,5 / 64,9 %** (hors ligne). Le 2026-09-22 : 25,0 %.
✅ **« Enregistrer le modèle »** → « ← c-VEP » → **« Tester »** (3 cycles par cible, 18 blocs,
~1,8 min) → « Commencer ». Fixe le disque **cerclé**, sans bouger les yeux.
✅ Deux chiffres ensemble : **justesse quand il émet** et **taux d'émission**, à comparer au couple
**EN DIRECT** du dépôt — **~46 % d'émission, ~71 % de justesse** —, jamais au 59,5/64,9 %.
⚠️ **Orange est le résultat attendu d'un système AU repère** : à 18 blocs, il ne sort vert qu'environ
une fois sur quatre (calculé, pas mesuré). La réserve nomme le réglage à tourner.

❌ Échec : **MUET** ou « NON MESURÉ » sans autre explication. ⚠️ **C'est la panne caractéristique
du c-VEP** : une phase fausse de quelques frames ne lève rien, les corrélations baissent juste assez
pour que rien ne se déclenche. La réserve distingue horloge, seuils et vote — lis-la.
🔴 **La séance longue avec journal et l'A-B-A contre l'écran archivé (recette 2.9) n'ont PLUS de
chemin dans la console** jusqu'à « Connecter » : ce sont les montages à terminaux de la recette. Le
test ne les remplace pas — il ne dit rien de « réseau contre local ».

→ recette 2.9

### ☐ 2.4 — P300 : Entraîner puis Tester

Page **P300** → **« Entraîner »** (~2,2 min, 12 manches) → « Commencer ».

✅ Le chiffre (cibles retrouvées, validation croisée par manche, hasard 17 %) → **« Enregistrer le modèle »**.
✅ « ← P300 » → **« Tester »** (6 manches, ~1,2 min) → « Commencer ». À chaque manche la fenêtre
**cercle** une cible : fixe-la.
✅ Le verdict : « … de cibles justes … (hasard 17 %) sur 6 manches ». Vert à 80 %, orange de 60 à
80 %, rouge en dessous ou si le binomial exact ne rejette pas le hasard : **5/6 vert (p < 0,001),
4/6 orange (p = 0,009), 3/6 rouge (p = 0,062 — la porte se ferme là)**.
⚠️ **Une ou deux erreurs sur six sont attendues** (AUC mesurée 0,71). À **24 manches** (~4,1 min)
la porte s'ouvre dès **8/24** (p = 0,035) : si la réserve le dit, refais à 24.
✅ ⚠️ **Le comptage mental n'est PAS requis** (validé casque) — une bonne fixation suffit, et le
briefing le dit (« Compter les éclairs de ta cible aide à rester attentif, mais ce n'est pas
obligatoire »).

❌ Échec : la cible retenue systématiquement décalée d'une position, ou une confiance élevée sur une
cible fausse — la signature d'un décalage à l'épochage, la panne qui rend tous les autres tests
verts.

→ recette 2.7

### ☐ 2.5 — ErrP : le moteur voit-il que la machine s'est trompée ?

Page **ErrP** → **« Entraîner »** (~5,7 min, 200 essais) → « Commencer » → **« Enregistrer le
modèle »** → « ← ErrP » → **« Tester »** (80 essais, ~2,4 min, ~22 erreurs délibérées).

✅ Au début du test, **regarde la piste immobile sans bouger** : le moteur y mesure ton bruit de fond
(la page le dit).
✅ Le verdict est un **COUPLE** : « garde X % des bonnes commandes, attrape Y % des erreurs (hasard :
Z %, autant qu'il en annule) ». Pas de 50 % : un détecteur au hasard attrape autant d'erreurs qu'il
annule de bonnes commandes.
✅ Repère du dépôt : **AUC 0,776** (p = 0,0099) ; au réglage 85 %, **une erreur attrapée sur deux** —
un taux optimiste, le seuil ayant été choisi sur les scores qui le mesurent. Attends-toi à garder
**moins** de bonnes commandes que visé.

❌ Échec : le détecteur annonce « erreur » sur presque tout, ou sur rien.
⚠️ **Un score PARFAIT est un signal d'alarme, pas une réussite.** Pendant le test, la fenêtre
publie la réponse de chaque pas ; elle doit atteindre le CORRECTEUR et jamais le DÉCODEUR. C'est
`errp_test.py` qui tient cette cloison (bloc 0) — l'écran ne peut pas la montrer.
⚠️ En décodage continu, le marqueur `feedback` reste **nu** : pas de `error: true|false`.

→ recette 2.8

### ☐ 2.6 — Motor Imagery : Entraîner puis Tester

Page **Motor Imagery** → **« Entraîner »** (~7,1 min à 14 essais/classe) → « Commencer ». Le moteur
mène : il tire les classes, affiche les consignes, décompte. Aucune fenêtre.

✅ Le chiffre est une **justesse honnête** (validation croisée **par essai**). Repères ré-mesurés :
**40,0 % à 3 classes** (p = 0,082, **PAS** significatif) et **63,3 % en gauche/droite** (p = 0,038).
✅ « ← Motor Imagery » → **« Tester »** (6 essais/classe, ~2,8 min) → « Commencer ». Même consignes
que l'entraînement, **même top latéralisé** (oreille gauche = poing gauche), et le moteur décide.
🔴 **Rouge est le résultat ATTENDU ici, à toutes les longueurs.** Sur les essais **annoncés**
(un `-1` sort du dénominateur), il faut **10/18** si les 18 annoncent, **15/30** à 10/classe,
pour rejeter le hasard — le repère du projet est
à 40 % (p = 0,391 et p = 0,276). 18 à 30 essais ne séparent pas 40 % de 33 %. Lis ce rouge
« pas de preuve », jamais « ça ne marche pas », et **note le chiffre et sa p-value**. Rallonger à
10 essais/classe (~4,5 min) ne suffit pas non plus : c'est un constat, pas un réglage.

❌ Échec : un chiffre d'entraînement nettement au-dessus des repères doit **éveiller un soupçon** —
c'est ce que la fuite entre fenêtres produisait (79 % non reproductible).
⚠️ **`-1` veut dire « vote non conclu »**, jamais « repos » : le test le compte dans le taux
d'émission, pas comme une erreur.

→ recette 2.6

### ☐ 2.7 — Neuro : le mode dont le CONTENU n'a jamais été validé

Page **Neuro** → **« Observer »**. Repos de 25 s, puis les indices défilent.

✅ Pendant la stabilisation et le repos, un **compte à rebours** : « décodage dans ≈ 32 s » (tuile,
page du mode et vue en direct), puis « décodage dans un instant… » si le repos se prolonge.

✅ Les trois indices bougent, et aucun chiffre de justesse n'est annoncé — il n'y a pas de bonne
réponse.

❌ Échec : les indices restent collés à zéro, ou dérivent sans jamais revenir.
⚠️ **Sa plomberie est testée, son contenu ne l'a jamais été — ni au casque, ni ailleurs.** Ce point
sert à vérifier qu'il *fonctionne*, pas qu'il *dit vrai*.

→ recette 2.5

### ☐ 2.8 — Choisir son casque parmi les casques APPAIRÉS

⚠️ **Mesuré le 2026-09-25 : aucune recherche ne dit qu'un casque est allumé.** La bibliothèque du
casque liste les casques APPAIRÉS à ce PC, instantanément, allumés ou non ; sa recherche Bluetooth
(6,4 s) ne rend que les casques NON appairés (en-tête Windows de g.tec) — elle trouve un casque
neuf, jamais le tien une fois appairé. Seule l'ouverture (« OK ») dit s'il répond. L'écran ne
promet donc rien d'autre.

✅ À l'ouverture : « 1 casque(s) appairé(s) à ce PC : UN-…. Allume le tien, puis OK : la console te
dira s'il répond. » — en **gris**, jamais « trouvé », jamais vert. Le dernier casque utilisé est en
tête de liste.
✅ « **Appairer un casque…** » ouvre la page Bluetooth des Paramètres de Windows (un casque neuf s'y
appaire, une fois par PC) ; « **Actualiser la liste** » la relit.
✅ Casque éteint + OK → l'écran revient avec la raison (point 1.12) ; casque allumé + OK → la console
s'ouvre.

❌ Échec : un message qui dit « trouvé » ou un vert pour un casque éteint ; l'écran qui se fige.

### ☐ 2.9 — Le casque décroche en pleine séance, et revient

Console ouverte sur le casque, un mode qui décode (le SSVEP par exemple). **Éteins le casque**
(ou éloigne-le hors de portée) ~10 s, puis rallume-le.

✅ En ~2 s, le bandeau : « ⚠ LIAISON PERDUE avec le casque depuis N s : plus rien n'est décodé.
Reconnexion en cours (essai n)… inutile de fermer la console. » ; les σ disent « plus aucun
échantillon ».
✅ Pendant la coupure, le flux décodé se TAIT (« Ce que voit ton application ») : aucune cible
répétée en boucle.
✅ Casque rallumé : en quelques secondes, « Liaison rétablie après N s : les modes refont leur
repos… » ; le mode repasse par la stabilisation puis le repos, et décode de nouveau **sans avoir
relancé la console**.
✅ Un test ou un entraînement en cours pendant la coupure est **annulé**, avec « La liaison avec le
casque s'est coupée pendant la séance… ».

❌ Régression : l'écran se fige et il faut relancer la console (le comportement d'avant le
2026-09-25) ; ou le flux décodé continue d'annoncer une cible pendant la coupure.
⚠️ Après la reconnexion, **regarde C3 et Cz** au bandeau : la réouverture redémarre
l'amplificateur, et elles saturaient à chaque réouverture. Note combien de temps.

---

# Bloc 3 — le réseau, vu d'une application cliente

C'est le produit. Un mode doit tourner pendant tout ce bloc : grille → sa tuile → **« Démarrer »**.

### ☐ 3.1 — Un client Python sur la même machine

Le client est **ton** application : taper sa commande est normal.

```bash
python -u examples/receiver.py --stream decoded_ssvep
```

✅ Le client trouve le flux **par son nom complet** (`EEG_API_Unicorn_decoded_ssvep`) et affiche des
décisions.
✅ « Ce que voit ton application » montre le même flux, sous le même nom.
⚠️ L'extrait « Brancher un client » a quitté la page du mode le 2026-09-22 ; il reviendra avec
« Connecter ». En attendant, la référence est `examples/`.

❌ Régression : le client ne trouve pas le flux alors qu'il est « publié » sur la tuile.
⚠️ Un flux décodé **existe dès le démarrage du mode** et reste **silencieux** pendant la chauffe et
le repos (~23 s pour le SSVEP). Ne pas relancer le moteur en croyant le flux absent.

→ recette 1.6, 3.1

### ☐ 3.2 — Depuis une deuxième machine

Même client, sur un autre PC du réseau.

✅ Le flux est trouvé, et `time_correction()` est **appliqué** — l'écart entre les deux horloges se
compte en **semaines** (`local_clock()` part du démarrage de chaque machine), pas en millisecondes.

❌ Échec : les horodatages reçus sont inutilisables pour joindre deux fichiers. Sans
`time_correction`, le dépouillement d'une séance à deux machines est faux, sans rien pour le dire.

→ recette 3.2

### ☐ 3.3 — Unity

`examples/unity/` : `SsvepIntentReceiver.cs` + `IntentToMotion.cs`, avec LSL4Unity.

✅ Les deux scripts **compilent**.
✅ La scène trouve le flux par son nom, et l'objet **s'arrête** quand le flux se tait (chien de
garde) au lieu de continuer sur une intention périmée.
✅ `-1` arrête l'objet — il ne le fait **pas** partir vers la cible 0.

❌ **Échec, et c'est le seul point de cette feuille dont on sait d'avance qu'il n'a jamais été
vérifié : les deux `.cs` n'ont JAMAIS été compilés.** Il n'y a pas d'Unity sur la machine de dev, et
aucun autotest ne peut le remplacer. Tout ce qui a été vérifié l'a été **par lecture**.
⚠️ `LSL.LSL.resolve_stream` n'est pas une faute de frappe : LSL4Unity déclare une classe statique
`LSL` dans un namespace lui aussi nommé `LSL`.

→ recette 3.3

---

## Ce que cette feuille ne teste pas, et il faut le savoir

- **L'ergonomie.** Aucun autotest ne dit si un étudiant comprend la boucle Régler → Tester →
  ajuster, qu'un chiffre d'entraînement n'est pas encore un modèle enregistré, ni si le contrôle de
  liaison est **lu** ou **cliqué au travers**. Ces questions n'ont de réponse qu'en séance, devant
  quelqu'un qui découvre l'outil.
- **L'écart de lancement fenêtre/moteur.** La console soumet la commande **puis** lance la fenêtre —
  l'ordre est figé par un test — et ce sont l'initialisation de pygame et l'attente de la fenêtre
  qui couvrent les 15 s de chauffe du moteur. **Ça tient, ce n'est pas garanti** : il n'existe
  **aucune poignée de main**. Si la fenêtre prend de l'avance, ses premiers essais tombent dans la
  chauffe — jetés, comptés, dits, mais la séance est plus courte que ce que l'écran annonce.
- **`--cycles` sur une fenêtre c-VEP lancée à la main.** Il compte des cycles enregistrés **par
  cible** ; la console le passe dans cette unité pour un test, mais une fenêtre lancée à la main
  avec `--cycles 6` jouera une séance plus courte que ce que l'entraînement annonce — le moteur ne
  mène pas ce protocole et ne peut pas le savoir.
- **La cloison d'étiquette de l'ErrP** ne se voit pas à l'écran : elle est tenue par l'autotest de
  `errp_test.py` (bloc 0.3), pas par la séance.
- **Les douze écrans archivés** (`archive/`) gardent chacun leur propre `--smoke` et ne sont couverts
  par aucun des autotests du bloc 0. `archive/cvep_pilot.py` reste utile en séance : il décode **en
  local**, ce qui sépare « le décodage réseau est moins bon » de « la séance est moins bonne ».
