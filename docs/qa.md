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
| Entraîner le c-VEP · Tester le c-VEP | **≈ 3,1 min** · **≈ 2,5 min** (3 cycles par cible, 18 blocs, phase de retour comprise) | test : 2 cycles ≈ 1,7 min |
| Entraîner le P300 · Tester le P300 | **≈ 2,2 min** (12 manches) · **≈ 1,4 min** (6 manches, phase de retour comprise) | test : 12 ≈ 2,6 · 24 ≈ 5,0 min |
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

**2026-10-21 — nouveau poste (écran à 165 Hz) : blocs 0 et 1 joués en solo par Claude**, avec une
console pilotée par script (hors écran), un vrai moteur sur le board de test et les vraies fenêtres
sur l'écran principal ; les captures d'écran relues une à une. Bloc 0 : 30 autotests verts. Bloc 1 :
1.18, 1.19 et 1.20 (livrés le jour même), 1.2 bis, 1.6 bis, 1.7 bis, et la part OUTIL du MI sur le
board de test (2.6.0, 2.6.2, `decoded_mi` à 4,9 Hz après sa chauffe, 2.12.4). Quatre défauts,
corrigés le jour même :
1. L'entraînement c-VEP abandonnait sur ce poste (« la fenêtre ne s'est pas annoncée en 30 s ») :
   la découverte LSL du moteur, à délai nul.
2. Les cibles s'ouvraient sur l'écran de la souris, pas sur l'écran principal.
3. Juste après le passage à 60 Hz, la mesure du rafraîchissement refusait à tort (61,7 Hz).
4. Les nombres des messages ne suivaient pas la langue : « 0.5 s » au décompte d'un écran français,
   des virgules écrites en dur dans les textes du moteur, et un nombre resté dans la langue où son
   texte était né.
Et la feuille : le 1.2 bis.3 attendait « 9.6 », le champ affiche « 9.600 » depuis juillet ; c'est
le séparateur qui compte. Restent au casque : 2.1.0 (le contraste du seuil de contact) et 2.9.4 bis
(les cercles vides pendant une coupure).

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
4. **« Vérifier le casque » ne vérifie que l'alpha** (passe du 2026-09-23, point 1.2). ➜ **En partie
   traité le 2026-10-20** : la page s'ouvre sur « Contact des électrodes » (point 1.7 bis), qui juge
   chaque électrode sur son σ (plate, ou trop de bruit au-delà d'un repère de 40 µV, PROVISOIRE)
   et la référence. Reste : caler le repère au casque (point 2.1.0) ; le bruit secteur et
   l'écrêtage ne sont pas mesurés par voie. Demandé :
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

✅ **0.1.1** Les deux finissent par `VERDICT : OK` et sortent en **0** (`echo $?` / `echo %ERRORLEVEL%`).
✅ **0.1.2** `[smoke-frontiere] … 0 violation(s) de frontière`, précédée de **trois** lignes « existe » —
`src/stimulus/`, `src/research/`, `src/console/` — chacune suivie d'un compte de fichiers non nul
(`core` est le quatrième paquet, scanné en premier).
✅ **0.1.3** `[smoke-exemples] … 0 faute(s)`, avec un nombre de fichiers **non nul** et au moins 5 noms de
flux trouvés.
✅ **0.1.4** `[smoke-textes] N textes en français, M appels à tr(), 0 faute(s)` — N et M **non nuls** (≈ 700
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

✅ **0.2.1** Quatre `VERDICT : OK`, quatre sorties à 0. Aucune fenêtre ne s'ouvre (pilote SDL factice).

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
python src/core/filtres_affichage.py
python src/core/i18n.py
python src/stimulus/ecran.py
```

✅ **0.3.1** Seize sorties à 0.

❌ Régression : n'importe lequel en rouge. Ceux dont l'échec compte le plus : `modes/p300.py` et
`modes/cvep.py` (leur panne caractéristique fait décoder du bruit **avec une confiance élevée**),
et `modes/errp_test.py`, qui porte **la cloison d'étiquette** du test ErrP — une fuite y donne un
score parfait et faux, sans rien casser.

### ☐ 0.4 — Aucun test n'a touché `data/`

```bash
python -c "import sys;sys.path.insert(0,'src');from core.config import DATA_DIR,empreinte_dossier;e=empreinte_dossier(DATA_DIR);print(len(e),'fichiers')"
```

✅ **0.4.1** Le même nombre de fichiers **avant et après** le bloc 0.

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

✅ **1.1.1** Deux choix explicites : **« Casque Unicorn Hybrid Black »** et **« Board de test, SANS casque »**.
✅ **1.1.2** Sous le casque, un champ **« Numéro de série du casque »** (liste modifiable), grisé quand le
board de test est coché. Vide + OK → refus en rouge, le dialogue reste ouvert.
✅ **1.1.3** Choisir le board de test → un bref « Démarrage du board de test… », puis la grille s'ouvre, et
**le bandeau du haut répète la source** tant que la console tourne.
✅ **1.1.4** Une liste **« Secteur électrique ⓘ »** : 50 Hz — Europe (le défaut) / 60 Hz — Amériques.
Choisis 60, OK, ferme la console, rouvre-la : **60 est resté choisi**. Remets 50.

❌ Régression : la console ouvre directement la grille sans demander ; ou le bandeau ne dit pas la
source ; ou — le plus grave — un casque introuvable **bascule tout seul** sur le board de test.
Un repli silencieux fait enregistrer une séance entière de signal fabriqué en croyant tenir du vrai.

→ recette 1.17

### ☐ 1.2 — La grille : sept tuiles, UNE tuile de séance

✅ **1.2.1** **Sept tuiles**, sur deux rangées : Brut · SSVEP · c-VEP · Neuro, puis Motor Imagery · P300 ·
ErrP. Chacune porte sa case **« publié »**, **« Démarrer »** et **« Ouvrir »**.
✅ **1.2.2** **Aucune n'est grisée**, même sans modèle entraîné : le manque de modèle se dit au clic, par un
refus (point 1.6), pas par une tuile éteinte.
✅ **1.2.3** Dessous, **« Avant tout »** avec **une seule** tuile : **« Vérifier le casque »**,
marquée *BARRIÈRE — à passer avant tout le reste*.
✅ **1.2.4** Tout en bas, **« La sortie »** et le bouton **« Ce que voit ton application »**.

❌ Régression : une tuile de mode manquante ; une tuile « Taux d'émission SSVEP » ou « Tester le … »
sur l'accueil — un test vit sur la page de SON mode, pas sur la grille.

→ recette 1.1, 1.2

### ☐ 1.2 bis — La langue de l'affichage, sans redémarrer

Accueil (la grille), aucune séance ni essai en cours.

1. Vérifie d'abord qu'aucun entraînement, test ou essai ne tourne. En haut à droite : le bouton
   **« 🌐 »**, suivi du nom de la langue en cours.
   ✅ **1.2 bis.1** Son menu propose **English** et **Français**, chacune écrite dans sa langue.
2. Toujours sans séance en cours, choisis l'autre langue.
   ✅ **1.2 bis.2** Tout l'affichage bascule **tout de suite** : tuiles, boutons, pages des modes,
   bulles ⓘ. Le bandeau continue de vivre (σ, liaison) : le casque n'a pas été rouvert.
   ✅ **1.2 bis.3** Page SSVEP : le pic alpha s'écrit **9.600** en anglais, **9,600** en français.
3. Ferme la console et relance-la.
   ✅ **1.2 bis.4** Elle s'ouvre dans la langue choisie en dernier — écran de départ compris.
4. Lance « Tester librement » sur un mode, puis, pendant l'essai, reviens à l'accueil et change de
   langue.
   ✅ **1.2 bis.5** Refusé, avec la raison dans le bandeau ; l'essai continue.
5. Vérifie d'abord qu'aucune séance ni essai ne tourne. Ouvre **Motor Imagery** → **« Entraîner »**,
   dans une langue puis dans l'autre.
   ✅ **1.2 bis.6** Les deux tâches par défaut s'appellent **LEFT** et **RIGHT** dans les deux
   langues : ce sont les noms que reçoit ton application (dans la description du flux), ils ne se
   traduisent pas. La bulle ⓘ de « Tâches à imaginer » dit qu'on peut aussi taper gauche, droite,
   et que les probabilités arrivent numérotées (p_0, p_1…).

❌ Régression : un texte resté dans l'ancienne langue après le changement ; le casque rouvert
(C3/Cz qui saturent) ; un « 9,600 » dans un écran anglais ; une tâche par défaut écrite GAUCHE.

### ☐ 1.3 — Le Brut montre vraiment le signal, et les tracés ne se chevauchent pas

Tuile **Brut** → « Ouvrir ».

✅ **1.3.1** Deux blocs : **« 1. Régler »**, qui dit « Aucun réglage à changer ici. » (ni « Appliquer », ni
bulle ⓘ), et **« 2. Observer »**, sans bouton — les tracés lisent le tampon
d'acquisition, il n'y a rien à démarrer.
✅ **1.3.2** Huit tracés qui défilent, une étiquette par voie (Fz, C3, Cz, C4, Pz, PO7, Oz, PO8), et **qui
restent séparés** quelle que soit l'amplitude.
✅ **1.3.3** La ligne grise sous le graphe annonce l'écart **en vigueur** (« un couloir = … µV ») et **ce
chiffre change** quand l'amplitude du signal change.
✅ **1.3.4** Au-dessus du graphe : **« Filtre d'affichage ⓘ »** sur **« Passe-haut 1 Hz »**, et une case
**« Coupe-bande 50 Hz ⓘ »** décochée. La ligne grise **commence par le filtre en vigueur**
(« Passe-haut 1 Hz · un couloir = … »).
✅ **1.3.5** La liste propose : Aucun (signal brut) · Passe-haut 0,1 / 0,5 / 1 / 2 Hz · Passe-bande 1–30 /
1–40 / 5–40 Hz. Choisir un autre filtre : la ligne grise le nomme **aussitôt**. Cocher la case :
elle ajoute « + coupe-bande 50 Hz ».
✅ **1.3.6** La molette sur la liste fait défiler la page, **pas** le filtre.
✅ **1.3.7** « ← Modes » revient à la grille.

❌ Régression : les tracés se chevauchent ; l'écart annoncé ne bouge jamais ; une voie hors échelle
est rognée **sans que la ligne grise la nomme** ; un bouton « Appliquer » qui n'aurait rien à
appliquer ; un filtre choisi que la ligne grise ne nomme pas ; la molette qui change le filtre.

→ recette 1.3

### ☐ 1.4 — Le bandeau vit

✅ **1.4.1** Les σ se mettent à jour (~1 Hz), une valeur par voie.
✅ **1.4.2** La **corrélation inter-voies** est affichée en permanence (« corrélation inter-voies 0,38 (sain :
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

✅ **1.5.1** **Aucune page** ne porte « Démarrer », « Lancer le stimulus », « Journal de séance » ni le bloc
« Brancher un client » : ils reviendront avec « Connecter ».
✅ **1.5.2** Sur les cinq pages qui ont « Tester », une case **« Décodage en direct »**, **décochée** : la
cocher déplie la vue en direct et l'état (« arrêté » tant que le mode ne tourne pas), sous la phrase
« Vide tant que le décodage continu est arrêté. Il se démarre depuis la tuile du mode, sur
l'accueil. » L'en-tête de ces pages, lui, n'affiche **aucun** état.
✅ **1.5.3** **Neuro** : « Observer » démarre le mode ; le libellé ne passe à « Arrêter » qu'une fois le moteur
d'accord (état reçu, pas une bascule locale). La vue défile en face, sans aucun chiffre de justesse.
✅ **1.5.4** **Page c-VEP** (le cas extrême : six réglages), coche « Décodage en direct » puis **réduis la
fenêtre en hauteur** : le corps défile, « 3. Tester » se rejoint en faisant défiler, et **« ← Modes »
reste visible** (l'en-tête ne défile pas).
✅ **1.5.5** **Aucune aide en clair sous les réglages** : chaque réglage qui a une aide porte une bulle
**« ⓘ »** bleue juste après son libellé ; la survoler (ou survoler le champ) montre l'aide complète,
qui passe à la ligne. Plus de case « Aide détaillée » (2026-09-23).

❌ Régression : un bloc hors de cette table, ou dans un autre ordre ; un des quatre boutons partis
revenu sur une page ; un score annoncé sous « Observer » (Neuro et Brut n'ont aucune bonne réponse
à comparer) ; le bas de page inatteignable.

→ recette 1.19

### ☐ 1.6 — Un réglage : retenu en vert, refusé en rouge, et le refus toujours à l'écran

Page **SSVEP**, mode **arrêté**, dans cet ordre.

1. « Pic alpha de la personne » à `10,5` → **Appliquer**.
   ✅ **1.6.1** En **vert** : « Réglage RETENU : « SSVEP » est arrêté. « Tester sur une session »,
   « Tester librement » et le prochain décodage partiront avec. »
2. Reviens à la grille (« ← Modes »), puis rouvre la page SSVEP.
   ✅ **1.6.2** Le champ affiche toujours **10,5**. ❌ Régression : retombé à 9,6 — l'écran dirait le contraire
   de ce que le moteur a retenu.
3. **« Proposer « Fréquences des cibles » »** (le bouton sous le pic alpha, le seul de la page).
   ✅ **1.6.3** **8,571 · 15 · 20**, le jeu accordé à un pic de 10,5 Hz. ❌ Régression : `12 · 15 · 20`, le jeu
   accordé au pic de la **population** (9,6 Hz).
4. « Fréquences des cibles » à `15, 17` → **Appliquer**.
   ✅ **1.6.4** Un refus **en rouge franc** (plus le corail qui se lisait orange, passe du 2026-09-23) qui
   nomme le coupable et propose les voisins : « 17 Hz n'est pas un
   diviseur entier de 60 Hz […] Les plus proches sont 15 et 20 Hz ».
   ✅ **1.6.5** La saisie fautive **reste dans le champ**, et le refus rappelle ce qui reste **en vigueur**.
   ❌ Régression : « « SSVEP » n'est pas démarré » au lieu du refus sur les fréquences (le
   comportement d'avant le 2026-09-21).
5. Remets `12, 15, 20` → **Appliquer** → vert.
6. Grille → tuile **Motor Imagery** (sans modèle sur ce poste) → **Démarrer**.
   ✅ **1.6.6** Le refus apparaît **dans le bandeau**, en haut de la fenêtre — pas seulement dans la console
   cmd — et il tient en **une ligne** : « Aucun modèle entraîné : dans la console, clique
   « Entraîner » sur la page du mode. »

❌ Régression : (6) écran strictement immobile après le clic — le défaut 1.13, corrigé le
2026-09-10 ; un refus qui dit encore « Calibrer » (corrigé par `c9701fa`) ; ou le paragraphe d'aide
du modèle recopié derrière « aucun choix disponible » (passe du 2026-09-23).

→ recette 1.8, 1.9, 1.13

### ☐ 1.6 bis — SSVEP : des cibles physiques (LED), sans écran

Page **SSVEP**, mode **arrêté**, dans cet ordre.

1. Vérifie d'abord que « Cibles affichées sur » montre **un écran**, puis choisis **des cibles
   physiques (LED…)**. Ne clique rien d'autre.
   ✅ **1.6 bis.1** Le champ « Rafraîchissement de l'écran du stimulus » se **grise**, les deux boutons
   « Tester sur une session » et « Tester librement » aussi, et une phrase apparaît dessous :
   « Les deux tests affichent leurs cibles à l'écran : ils ne marchent pas avec des cibles physiques… ».
2. Toujours sur **des cibles physiques**, mode arrêté : « Fréquences des cibles » à `12, 17, 20` →
   **Appliquer**.
   ✅ **1.6 bis.2** **Vert** : 17 Hz est accepté. (Sur un écran à 60 Hz, il est refusé : point 1.6.4.)
3. Toujours sur **des cibles physiques**, mode arrêté : **« Proposer « Fréquences des cibles » »**.
   ✅ **1.6 bis.3** Des fréquences au **demi-hertz** (des valeurs en ,5 ou entières), pas seulement les
   diviseurs de 60 (12 · 15 · 20…).
4. Repasse « Cibles affichées sur » à **un écran**, remets `12, 15, 20` → **Appliquer**.
   ✅ **1.6 bis.4** Vert ; le rafraîchissement et les deux « Tester » redeviennent cliquables, la phrase
   disparaît.

❌ Régression : un « Tester » cliquable sur des cibles physiques ; 17 Hz refusé sur des cibles
physiques ; « Proposer » qui ne rend que des diviseurs de 60 sur des cibles physiques ; le
rafraîchissement qui reste grisé une fois revenu à l'écran.

### ☐ 1.7 — Le contrôle de liaison REFUSE, et ne se contourne pas

Il s'intercale devant **chaque** « Commencer » : Vérifier le casque, Entraîner, Tester. Tu le verras
aux points 1.8 à 1.10 ; regarde-le une fois pour lui-même.

✅ **1.7.1** Un écran « Contrôle de la liaison casque » montre **le σ de chacune des huit voies**, un verdict par
voie, et deux boutons : **« ← Annuler »** et un bouton de lancement qui dit ce qu'il lance.
✅ **1.7.2** **Partout**, une phrase « Voies clés : … (encadrées). Saline-les en priorité. … », et ces lignes-là
**encadrées en bleu** : les voies du mode sur « Entraîner » et « Tester » (le test prend celles de
son mode, `186510f`), et **Pz, PO7, Oz, PO8** sur « Vérifier le casque » — les quatre qu'elle
moyenne (passe du 2026-09-23). Le refus porte sur les huit dans tous les cas.
✅ **1.7.3** Sur board de test, les huit passent (σ mesurés de 7 à 73 µV) et on continue.
✅ **1.7.4** « ← Annuler » ramène à la page d'où l'on venait.

❌ Régression : l'écran n'apparaît pas, ou il laisse passer une voie hors de **[0,5 ; 500] µV** ;
« Vérifier le casque » sans aucune voie encadrée.
⚠️ **Il n'y a AUCUNE porte de sortie, et c'est délibéré** — un contournement à un clic est un
contournement qu'on prend par réflexe. Si au casque une électrode refuse de descendre sous le
seuil, **c'est une décision à prendre devant le casque**, pas un bug à corriger dans l'urgence.

### ☐ 1.7 bis — Le contact de chaque électrode, sur « Vérifier le casque » (2026-10-20)

Board de test, aucune séance en cours.

1. Vérifie d'abord que la console est ouverte sur le **board de test** et que rien ne tourne.
   Grille → **« Vérifier le casque »** → « Ouvrir ».
   ✅ **1.7 bis.1** En tête de page, **« Contact des électrodes »** : la tête vue de dessus (nez en
   haut), huit cercles nommés (Fz, C3, Cz, C4, Pz, PO7, Oz, PO8), deux petits cercles derrière les
   oreilles (la référence) ; à droite, une barre par électrode coupée par un **trait vertical**, et
   dessous « Repère : 40 µV. Au-delà, le contact n'est pas bon. »
   ✅ **1.7 bis.2** Chaque cercle a la **couleur de sa barre** : vert si elle reste avant le trait, rouge
   si elle le dépasse. Le board de test a des voies jusqu'à ~73 µV : du **rouge est attendu**, et
   la phrase du haut nomme ces électrodes (« À revoir : … »).
   ✅ **1.7 bis.3** Les deux cercles de la référence restent **vides** : le board de test n'a pas de
   référence. La bulle ⓘ explique vert, rouge et vide.
2. Toujours sans séance en cours, ouvre la page **SSVEP**, puis son **« Tester sur une session »**.
   ✅ **1.7 bis.4** Ni l'une ni l'autre ne montre cette vue : elle n'est que sur « Vérifier le casque ».
3. Vérifie d'abord que rien ne tourne. Change de langue (🌐), puis reviens sur « Vérifier le casque ».
   ✅ **1.7 bis.5** Textes traduits ; « 7.2 µV » en anglais, « 7,2 µV » en français.

❌ Régression : un cercle vert à côté d'une barre rouge, ou l'inverse ; une électrode rouge que la
phrase ne nomme pas ; la vue sur une autre page.

### ☐ 1.8 — « Mesurer » le pic alpha depuis la page SSVEP, et un résultat en trois lignes

Page **SSVEP** → **« Mesurer »**, à droite du champ « Pic alpha de la personne ». ~37 s.

✅ **1.8.1** La page **« Vérifier le casque »** s'ouvre — la même que la tuile de l'accueil — et son bouton de
retour dit **« ← SSVEP »**.
✅ **1.8.2** Briefing, puis **« Commencer »** → contrôle de liaison → le décompte, et **un top sonore à chaque
changement d'étape** (la moitié se fait les yeux fermés). Sans son, la page **le dit** avant de
commencer.
✅ **1.8.3** **Le résultat, en trois lignes en face** : un **mot** en couleur (« ALPHA NET » en vert, ou
« ARRÊTE ICI » en rouge), une ligne de **chiffres**, **une** phrase de réserve. Puis une case
**« Détails »**, décochée : elle déplie la ligne BARRIÈRE, la phrase de verdict complète, le ratio,
le pic, les voies moyennées et la phrase d'honnêteté — et **le repli RESTE ouvert** tant que tu ne
le refermes pas. ❌ Régression : il se referme tout seul au bout d'un instant (le défaut corrigé par
`07a3303` : chaque rafraîchissement le décochait, dix fois par seconde).
✅ **1.8.4** Si « ALPHA NET » : un bouton « Appliquer « Pic alpha de la personne » = … Hz à « SSVEP » » →
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
   **« Tester sur une session »**.
   ✅ **1.9.1** La page **« Tester le SSVEP »** s'ouvre, retour « ← SSVEP ». Reviens voir : le champ dit
   **12, 15, 20** et c'est ce que le moteur a retenu — « Tester » applique ce qui est à l'écran.
   ❌ Régression : le test part sur l'ancienne configuration, sans rien dire.
2. Tape `15, 17` → **« Tester sur une session »**.
   ✅ **1.9.2** Le refus s'affiche **sous « 1. Régler »**, et la page de test **ne s'ouvre pas** : tester une
   configuration impossible ne mesurerait rien.
3. Remets `12, 15, 20` → **« Tester sur une session »** → **« Commencer »** → contrôle de liaison → **« Commencer
   la mesure »**.
   ✅ **1.9.3** Sous l'en-tête de la page, en gris : « Décodage de « SSVEP » arrêté pour ce test : les deux ne
   tournent pas ensemble. Il restera arrêté ensuite. Relance-le depuis sa tuile si ton application
   en a besoin. » **Elle reste affichée** pendant le test et après. ❌ Régression : elle
   disparaît dès que le test démarre (le défaut du 2026-09-23 — elle vivait moins d'une seconde).
   ✅ **1.9.4** **Puis** la fenêtre s'ouvre, plein écran : **trois** disques étiquetés **12.00 · 15.00 ·
   20.00 Hz**, une croix pour le repos, puis un disque **cerclé de bleu** par essai. Le HUD affiche
   `… fps | sautées N | ESC = quitter`.
   ❌ Régression : `15 · 20 · 8,571` à l'écran — le trio du dépôt, pendant que le moteur corrèle
   sur 12 · 15 · 20.
   ✅ **1.9.5** Pendant ce temps la page montre « Mesure en cours », le décompte et une barre d'avancement.
4. Après quelques essais, **« Abandonner »** sur la page.
   ✅ **1.9.6** La fenêtre se ferme **toute seule** (pas besoin d'Échap), et la page dit « La fenêtre du test
   a été fermée : la séance s'est interrompue ».
   ✅ **1.9.7** Aucun verdict n'est inventé sur une séance coupée.
   ✅ **1.9.8** La tuile SSVEP dit **« arrêté »** et le reste : le décodage continu se relance depuis sa tuile.
   ✅ **1.9.9** `data/` n'a rien gagné (empreinte du point 0.4).

❌ Régression : la fenêtre s'ouvre **avant** que la page ne passe à « Mesure en cours » (l'ordre
moteur → fenêtre est un contrat testé) ; une fenêtre qui survit à « Abandonner » ; un fichier écrit.

→ recette 1.20

### ☐ 1.10 — Entraîner puis Tester : le P300 (~2,2 + 1,4 min)

Le plus court des modes à modèle. Page **P300**.

1. **Le refus sans modèle se joue sur la page d'un mode qui n'en a AUCUN** — sur ce poste, le
   **Motor Imagery** (le P300 a un modèle du 2026-08-17 dans `data/`, l'ErrP et le c-VEP aussi).
   Page **Motor Imagery** → **« Tester sur une session »**.
   ✅ **1.10.1** Refus sous « 1. Régler » (« Aucun modèle entraîné : dans la console, clique « Entraîner » sur
   la page du mode. »), et le test ne s'ouvre pas. C'est le moteur qui tient l'ordre Entraîner →
   Tester, pas l'écran.
2. Page **P300** → **« 2. Entraîner »** → **« Entraîner »**.
   ✅ **1.10.2** La page **« Entraîner le P300 »**, retour **« ← P300 »** : briefing, **« Commencer »** →
   contrôle de liaison → **« Commencer l'entraînement »**.
   ✅ **1.10.3** La console **lance elle-même la fenêtre P300**, **après** que le moteur a démarré.
   ✅ **1.10.4** À la fin : trois lignes en face, une ligne ambre « ⚠ Pas encore enregistré : ce modèle est dans
   un dossier temporaire. … », et **« Enregistrer le modèle »** / **« Refaire »**.
3. **« Refaire »** → rien n'a été écrit dans `data/` (empreinte). Relance, puis **« Enregistrer le
   modèle »** → « Modèle en place : … ».
4. **« ← P300 »** → le modèle est dans la liste « Modèle entraîné », horodaté, **en tête** et
   sélectionné (la liste va du plus récent au plus ancien), sans redémarrer.
5. **« 3. Tester »** → **« Tester sur une session »**.
   ✅ **1.10.5** La page **« Tester le P300 »** est **pré-remplie** : même modèle que la page du mode, et
   « Manches » à **6**.
   ✅ **1.10.6** « Commencer » → contrôle de liaison → la fenêtre s'ouvre **en test** : son écran de fin dit
   « Test terminé », et le bandeau « … test terminé(e) : 6 manches … le moteur note, le verdict
   s'affiche dans la console ».
   ✅ **1.10.7** Le résultat porte **« (hasard 17 %) sur 6 manches »** — jamais 50 %.
   ✅ **1.10.8** Rien n'a été écrit dans `data/` : un test n'a ni « Enregistrer » ni « Refaire ».

❌ Régression : le chiffre d'entraînement s'affiche **après** l'écriture du modèle ; « Refaire »
laisse un fichier ; le modèle enregistré n'apparaît pas dans la liste sans redémarrer ; la fenêtre du
test dit « CALIBRATION » ; un test qui écrit dans `data/`.
⚠️ **Vérifie `data/` par empreinte**, pas par `git status` — le dossier est gitignoré.

→ recette 1.14, 1.20

### ☐ 1.11 — « Ce que voit ton application » : le flux sortant, vu comme un client

Grille → tuile **SSVEP** → **« Démarrer »** ; attends ~23 s (chauffe + repos). Puis, en bas de la
grille, **« Ce que voit ton application »**.

ℹ️ **`quality` et `status` sont TOUJOURS là**, même sans aucun mode démarré : le moteur les publie
dès son ouverture (la santé des électrodes, ~1 Hz, et son propre état). Ce ne sont pas des
décodages, et une application s'en sert pour savoir si le moteur tourne et si le contact est bon.
✅ **1.11.1** Les flux LSL **du réseau** apparaissent, avec leurs voies et des valeurs qui défilent — **celles
du flux affiché dans la liste, tout de suite, sans cliquer dessus**. ❌ Régression : un flux affiché
dans la liste et un panneau vide tant qu'on ne le re-choisit pas (défaut du 2026-09-23).
✅ **1.11.2** ⚠️ Le panneau lit **par LSL, comme un client** — pas l'état interne du moteur. Décoche « publié »
sur la tuile SSVEP puis relance « Chercher les flux » : `decoded_ssvep` doit **disparaître**, et
l'absence se **dire**. S'il défile encore, il regarde le mauvais endroit. En revenant sur la page
après l'avoir décoché, elle dit « « …decoded_ssvep » n'est plus visible sur le réseau » et **n'ouvre
pas un autre flux à sa place**.
✅ **1.11.3** **« Enregistrer les verdicts »** → un fichier `moteur_<flux>_AAAAMMJJ-HHMMSS.jsonl` dans
`seances/`, **une ligne par décision publiée**, et l'écran dit **où et combien**. Le même bouton
l'arrête.
✅ **1.11.4** `seances/` est **hors de `data/`**.
✅ **1.11.5** Le bouton ouvre une **fenêtre à part** : la console reste sur sa page. Ouvre un mode →
**« Tester sur une session »** → **« Commencer »** : la fenêtre des flux reste ouverte et défile pendant le test. Un
second clic sur le bouton la ramène devant, sans en ouvrir une deuxième. Fermer la console la ferme.

❌ Régression : le panneau défile alors que le réseau est muet ; le chemin du fichier n'est pas
affiché.

→ recette 1.18

### ☐ 1.12 — Un casque qui refuse de s'ouvrir : la question est reposée

Il suffit d'un casque **éteint** (ou d'un numéro faux) : **choisir « Casque Unicorn »** → OK.

✅ **1.12.1** Une fenêtre « Connexion au casque « … »… » avec **« Abandonner »**, pendant l'ouverture Bluetooth.
✅ **1.12.2** Puis l'**écran de départ revient**, avec en rouge « Le casque « … » ne s'est pas ouvert (raison
de BrainFlow)… », le **casque toujours coché** et son numéro dans le champ. Allume le casque (ou
corrige le numéro) → OK → la console s'ouvre.
✅ **1.12.3** Le numéro qui a réussi est proposé en premier au lancement suivant ; celui qui a échoué, non.

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

✅ **1.13.1** Un bilan s'imprime : `fin : N frames affichées, M sautée(s) (x %)`. **Note le pourcentage.**

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

### ☐ 1.14 — La bande d'un modèle se règle à l'ENTRAÎNEMENT (P300, ErrP, c-VEP, MI)

Page **P300** → **« Entraîner »**.

✅ **1.14.1** Dans « Avant de commencer », deux réglages : **« Coupure basse (Hz) ⓘ »** à 1 et **« Coupure
haute (Hz) ⓘ »** à 12. **Aucun bouton « Appliquer »** : les réglages partent avec « Commencer ».
✅ **1.14.2** Mets la coupure basse à **3** → « Commencer » : **refus en rouge TOUT DE SUITE**, qui donne la
borne (1 Hz), **avant** le contrôle de liaison, et le mode P300 n'est pas arrêté s'il tournait.
Remets 1.
✅ **1.14.3** Même chose sur les pages « Entraîner » de l'**ErrP** (1–10), du **c-VEP** (2–45, plus
**« Rafraîchissement de l'écran du stimulus ⓘ »** à 60) et du **MI** (8–30, plus une case
**« FBCSP (banc de filtres) »** décochée).
✅ **1.14.4** Après un entraînement P300 sur board de test (~2,2 min, comme au 1.10) : sous « Détails », une
ligne **« Filtre 1–12 Hz, coupe-bande 50 Hz »**.

❌ Régression : un réglage de bande dans « 1. Régler » d'un mode à modèle (il ferait décoder un
modèle sur un autre filtre que celui qu'il a appris) ; un refus qui n'arrive qu'après le contrôle
de liaison ; un « Appliquer » sur une page d'entraînement.

### ☐ 1.15 — La bande du SSVEP se règle dans « Régler »

Page **SSVEP**, bloc « 1. Régler ».

✅ **1.15.1** **« Coupure basse (Hz) ⓘ »** à 5 et **« Coupure haute (Hz) ⓘ »** à 40.
✅ **1.15.2** Fréquences **« 12, 20, 30 »** et coupure haute à **25**, « Appliquer » : **refus** qui nomme la
fréquence hors bande (30 Hz) et la bande réglée. (Avec les fréquences par défaut, 8,571 / 15 /
20 Hz, aucune bande permise n'en exclut une : c'est voulu.) Remets les défauts.
✅ **1.15.3** Coupure haute à **50** : **refus** (maximum 45 : une cible ou une harmonique ne doit jamais
tomber dans le coupe-bande secteur).
✅ **1.15.4** Coupure haute à 25 puis **« Proposer »** : le jeu proposé reste **sous 25 Hz**. Remets 40.

❌ Régression : une fréquence hors de la bande réglée acceptée ; « Proposer » qui propose hors de
la bande à l'écran ; une valeur hors bornes corrigée en silence au lieu d'être refusée.

### ☐ 1.16 — « Rétablir les valeurs par défaut », partout où il y a des réglages

✅ **1.16.1** Page **SSVEP**, « 1. Régler » : change le seuil et la coupure haute → **« Rétablir les valeurs
par défaut »**, **en bas à droite** du bloc : les champs reviennent aux défauts, et **rien n'est
appliqué** (pas de message vert ; il faut encore cliquer « Appliquer »).
✅ **1.16.2** Même bouton sur une page **« Entraîner »** (ex. P300 : coupure basse à 0,7 → bouton → 1).
✅ **1.16.3** Page **« Tester »** du P300 : il remet le nombre d'essais, mais **pas** le modèle, grisé, qui
vient du mode. Page **« Tester »** du SSVEP : **pas de bouton**, tous ses réglages viennent du mode.
✅ **1.16.4** **Brut** : au bout de la ligne des filtres, le même bouton remet « Passe-haut 1 Hz » et
décoche le coupe-bande. **Pas** de bouton dans son bloc « 1. Régler », qui n'a aucun réglage.

❌ Régression : le bouton applique tout seul ; il touche un champ grisé ; il apparaît là où il n'y
a rien à rétablir.

### ☐ 1.17 — Le retour en direct, sur le board de test

Les décisions du board de test sont du bruit : on vérifie la MÉCANIQUE, pas la justesse. Le bloc
« Tester » de chaque page a **deux** boutons : **« Tester sur une session »** (des consignes, un
score) et **« Tester librement »** (aucune consigne, aucun score). Dans les deux, l'anneau **VERT**
entoure la cible que le moteur DÉCODE — juste ou non : une erreur se voit, l'anneau n'est pas sur
la cible désignée. La consigne, elle, est toujours **bleue**.

⚠️ **Sur du bruit, le SSVEP et le c-VEP s'abstiennent presque toujours** (relevé le 2026-10-02) :
rien ne dépasse leurs seuils, donc pas de décision, donc pas d'anneau — c'est leur comportement
voulu. Pour voir la mécanique, **baisse les seuils AVANT de tester** (bloc « 1. Régler » →
« Appliquer »), et le moteur annonce des cibles AU HASARD — c'est ce qu'on veut ici :
- **SSVEP** : « Seuil de détection » à **1,0** (le minimum). Attendu : une décision dans ~40 %
  des essais (calcul — le maximum de 3 tirages gaussiens dépasse 1 —, pas une mesure).
- **c-VEP** : « Corrélation minimale » **0**, « Marge sur le second » **0**, « Votes concordants »
  **1** : une décision à chaque bloc.
- Le **P300** décide à chaque manche sans rien toucher.
- À la fin du point : **« Rétablir les valeurs par défaut »** sur chacune des deux pages.
- ⚠️ **Les réglages ne survivent PAS à une relance de la console** : ils reviennent aux défauts.
  Console relancée en cours de point → **rebaisse les seuils** avant de continuer (relevé le
  2026-10-02 : 1.17.3 sans anneau, seuils revenus aux défauts, un −1 à chaque bloc).

✅ **1.17.1** Page **SSVEP** — ⚠️ **vérifie d'abord** « Seuil de détection » = **1,0** → **« Tester sur une session »** → « Commencer » : le disque à fixer est cerclé de
**bleu** ; après chaque essai, le disque décodé est entouré en **vert**, rien si le moteur s'est
abstenu. L'anneau s'éteint au début de la consigne suivante.
✅ **1.17.2** Page **P300** → **« Tester sur une session »** : après chaque manche, une **phase de
retour** — le cercle bleu disparaît, l'anneau vert apparaît SEUL autour de la cible décodée
(~1 s, aucune consigne à l'écran), s'efface, et SEULEMENT ENSUITE la cible suivante est cerclée en
bleu. La dernière manche a la sienne avant l'écran de fin. L'anneau vert a la taille de la cible
(un petit écart autour).
✅ **1.17.3** Page **c-VEP** — ⚠️ **vérifie d'abord** « Corrélation minimale » **0**, « Marge sur le
second » **0**, « Votes concordants » **1** (sinon : aucun anneau, ce n'est pas une panne) → **« Tester sur une session »** : la cible à fixer est
cerclée en **bleu** (plus en vert) ; à la fin de chaque bloc, même **phase de retour** qu'au P300
— l'anneau vert seul ~1 s, puis le cercle bleu suivant (les disques continuent de clignoter). Le
vert a la **même taille qu'au P300** : collé à la cible, plus le grand cercle d'avant.
✅ **1.17.4** Pendant un de ces tests, « Ce que voit ton application » montre `decoded_<mode>` : **une ligne
par essai**.
✅ **1.17.5** Page **SSVEP** — ⚠️ **vérifie** « Seuil de détection » = **1,0** → **« Tester librement ⓘ »** : le contrôle de liaison passe, puis la fenêtre
s'ouvre **tout de suite** — les disques clignotent avec une **croix** au centre et « ne fixe aucune
cible » pendant la chauffe et le repos du moteur.
✅ **1.17.6** La croix part : l'anneau **vert** suit les décisions, sans consigne ni score, et ne clignote pas
quand le moteur s'abstient (il s'éteint seul ~1 s après la dernière décision).
✅ **1.17.7** Ferme la fenêtre (Échap) : la page dit que le SSVEP est arrêté.
✅ **1.17.8** Relance « Tester librement », reviens à la console (Alt+Tab) et change un réglage du
SSVEP (bloc « 1. Régler » → « Appliquer ») : la console **ferme** l'essai et le dit en rouge.
✅ **1.17.9** Lance « Vérifier le casque », reviens sur la page SSVEP et clique « Tester librement » pendant
la mesure : **refus** qui nomme la mesure, aucune fenêtre.
✅ **1.17.10** « Tester librement » existe sur c-VEP et P300 ; il est **absent** sur ErrP, MI, Neuro et Brut.
✅ **1.17.11** SSVEP **démarré depuis la grille** (« Démarrer » sur sa tuile), puis « Tester sur une
session » → « Commencer » : la console **arrête d'abord le SSVEP**, puis lance le test — pas de
refus (la console arrête le mode avant tout test, cf. CLAUDE.md ; le refus du moteur reste le
filet si un client le tente). Validé ainsi par l'utilisateur le 2026-10-05.

Si, seuil à 1,0, le SSVEP ne décide TOUJOURS rien sur 10 essais : note-le et passe ; 1.17.1 et
1.17.6 se vérifient alors au casque (2.2, 2.12).

❌ Échec : la fenêtre libre attend la fin du repos pour s'ouvrir, ou s'ouvre SANS croix pendant le
repos ; un anneau sur une cible qui n'est pas celle décodée (compare à « Ce que voit ton
application ») ; un anneau qui déborde sur une cible ; un anneau d'une autre couleur que le vert ;
le mode qui continue de tourner après un essai libre qu'il n'avait pas commencé.

### ☐ 1.18 — L'écran passe au rafraîchissement du stimulus (2026-10-21)

Board de test, sur un poste dont l'écran principal ne tourne pas à 60 Hz (le poste de dev : 165 Hz).
Note d'abord son rafraîchissement, dans Paramètres → Affichage → Affichage avancé : ___ Hz.

1. Page **SSVEP**, « 1. Régler » : « Rafraîchissement de l'écran du stimulus » à **60**,
   « Proposer », « Appliquer ». Puis **« Tester sur une session »**, place la souris sur un écran
   SECONDAIRE, et « Commencer ».
   ✅ **1.18.1** L'écran principal passe au noir une seconde, puis le test clignote SUR L'ÉCRAN
   PRINCIPAL, pas sur celui de la souris. Échap : l'écran revient au rafraîchissement noté plus
   haut.
2. Page **c-VEP** → **« Entraîner »**.
   ✅ **1.18.2** « Avant de commencer » montre **« Rafraîchissement de l'écran du stimulus ⓘ »** à
   60 ; « 1. Régler » ne le montre pas.
   « Commencer », laisse tourner ~30 s, puis **« Abandonner »**.
   ✅ **1.18.3** L'écran passe à 60 Hz pendant l'entraînement, et revient au rafraîchissement noté
   après l'abandon, alors que la fenêtre a été TUÉE.
3. Refais l'entraînement c-VEP jusqu'au bout (~3,1 min), et enregistre le modèle.
   ✅ **1.18.4** Dans la liste des modèles du c-VEP, son nom finit par **`_60Hz.npz`**.
4. Page **SSVEP** : un rafraîchissement que l'écran ne propose pas (75 sur le poste de dev),
   « Proposer », « Appliquer », « Tester sur une session » → « Commencer ».
   ✅ **1.18.5** La page dit que la fenêtre a refusé de s'ouvrir, avec la raison : l'écran ne sait
   pas afficher à 75 Hz, et la liste de ce qu'il propose. L'écran n'a pas changé (cf. 1.20).

❌ Régression : un écran qui ne revient pas à son rafraîchissement, une fenêtre qui s'ouvre au
mauvais rafraîchissement, un modèle c-VEP sans `_…Hz` dans son nom.

### ☐ 1.19 — L'avertissement des lumières clignotantes (2026-10-21)

Board de test.

1. Grille → ouvre la page **SSVEP**.
   ✅ **1.19.1** Sous l'en-tête, un grand cadre rouge « ⚠ ATTENTION — LUMIÈRES CLIGNOTANTES » : le
   risque d'épilepsie, et quoi faire. Aucune boîte à valider.
   ✅ **1.19.2** Fais défiler la page : le cadre reste visible. Rien ne le ferme.
2. Ouvre les pages **c-VEP** et **P300**.
   ✅ **1.19.3** Le même cadre.
3. Ouvre les pages **Motor Imagery**, **ErrP**, **Neuro** et **Brut**.
   ✅ **1.19.4** Pas de cadre : elles ne font rien clignoter.
4. Change de langue (🌐), rouvre la page SSVEP.
   ✅ **1.19.5** Le cadre est en anglais (« ⚠ WARNING — FLASHING LIGHTS »).

❌ Régression : un mode qui fait clignoter un stimulus sans avertissement, un cadre qui disparaît en
faisant défiler.

### ☐ 1.20 — Une fenêtre qui s'arrête avant la fin (2026-10-21)

Board de test.

1. Page **SSVEP** → « Tester sur une session » → « Commencer ». Dès que la fenêtre clignote,
   **Échap**.
   ✅ **1.20.1** La séance s'arrête AUSSITÔT, sans finir son décompte. La page dit en une phrase
   « séance abandonnée, la fenêtre a été fermée avant la fin », sans le journal de la fenêtre.
   ✅ **1.20.2** Reviens à la grille : plus aucun message de la fenêtre dans le bandeau.
2. Page **SSVEP** : rafraîchissement à une valeur que l'écran ne propose pas (75 sur le poste de
   dev), « Proposer », « Appliquer », puis « Tester sur une session » → « Commencer ».
   ✅ **1.20.3** La séance s'arrête aussitôt. La page dit, en rouge, que la fenêtre a refusé de
   s'ouvrir, avec la seule raison : l'écran ne sait pas afficher à 75 Hz, et ce qu'il propose.

❌ Régression : un décompte qui continue après la fermeture de la fenêtre ; le journal entier de la
fenêtre dans le bandeau ; un message qui suit l'élève sur la grille.

---

# Bloc 2 — au casque

> 🔔 **POINT DE VIGILANCE — séance du 2026-10-21 : VÉRIFIER LE SEUIL DE CONTACT.**
> Le repère vert/rouge de « Contact des électrodes » (**40 µV**, `config.CONTACT_SIGMA_MAX`) est
> **provisoire** : il ne vient pas de g.tec (qui ne publie aucun chiffre), il a été posé sur trois
> séances archivées et un seul exemple d'électrode dégradée. Même chose pour le seuil de la
> **référence** (corrélation entre voies > 0,90, une seule séance). **Fais le contraste du point
> 2.1.0 avant tout le reste**, et note les valeurs : c'est ce qui décidera de les garder ou de les
> changer. Le signal brut du contraste servira aussi à essayer, hors ligne, un critère de plus :
> la corrélation de chaque électrode avec les autres.

⚠️ **Ce bloc vérifie l'OUTIL au casque, pas le niveau de décodage.** Il a été joué en entier (le
2026-09-24, puis le MI le 2026-10-15) : une nouvelle séance ne rejoue que ce qui a été livré depuis.
Les autotests prouvent le câblage, jamais l'ergonomie. Un point qui tombe ici est **❌ Échec**, pas
régression : note ce que tu vois, ne conclus pas.

**Ordre arrêté, à ne pas rouvrir : Contact → SSVEP → c-VEP → P300 → ErrP**, puis MI et Neuro si le
sujet tient. Le SSVEP en référence du jour : s'il échoue, c'est la séance qui est mauvaise, pas le
mode. Le c-VEP tôt, sur sujet frais, parce que sa panne caractéristique est un décodage *dégradé
mais plausible*.

⚠️ **Un mode à modèle se teste sur un modèle entraîné dans la séance** : un modèle d'une autre
séance, même chargeable, a appris un autre montage.

⚠️ **La boucle d'un mode à modèle est toujours la même** : « Entraîner » → lire le chiffre →
« Enregistrer le modèle » ou « Refaire » → « ← » → « Tester sur une session » (pré-rempli avec ce modèle) → lire le
verdict. Un chiffre d'entraînement est **hors ligne** (sa réserve le dit) ; c'est le test qui dit ce
que le mode fait vraiment.

### ☐ 2.0 — Le montage (chaque point a déjà coûté une séance)

✅ **2.0.1** **Saliner les électrodes** — c'est le levier de qualité le plus fort mesuré ici (+130 % d'ITR sur
le c-VEP).
✅ **2.0.2** **Les mastoïdes sont posées** — oubliées au moins deux fois. Une référence décollée produit un
signal qui *ressemble* à du signal.
✅ **2.0.3** Casque bien serré, câble dégagé, sujet assis et calé.

✅ **2.0.4** Au bandeau, la corrélation inter-voies autour de **0,3 à 0,5**.

❌ Échec : une corrélation qui monte vers **1** (alarme rouge « RÉFÉRENCE DÉCROCHÉE » au-delà de
0,90) = la référence flotte. Ne rien enregistrer, reprendre le montage.

### ☐ 2.1 — Vérifier le casque — **BARRIÈRE** (à faire en PREMIER)

Grille → **« Vérifier le casque »** → « Ouvrir » (ou, c'est la même page : page SSVEP →
**« Mesurer »**) → briefing → **« Commencer »**. **37 s** : stabilisation, 8 s **yeux ouverts**,
8 s **yeux fermés**, un **top sonore** à chaque changement.

✅ **2.1.0** (2026-10-20) **Avant « Commencer »** — vérifie d'abord que le casque est posé, allumé, les
électrodes mouillées, et attends ~5 s sur la page. « Contact des électrodes » : chaque cercle
**vert**, et la référence (derrière les oreilles) verte aussi. Une électrode rouge : appuie-la,
mouille-la, attends quelques secondes. Un clignement fait passer Fz au rouge un instant : c'est
normal.
⚠️ **Le repère de 40 µV est provisoire : le contraste ci-dessous le calera (~5 min).** Vérifie
d'abord que le casque est bien posé et mouillé, et que tout est vert.
0. **Enregistre le signal brut pendant tout le contraste** : dans un second terminal, console
   ouverte, `python src/research/enregistre_brut.py`. À CHAQUE geste, tape une note puis Entrée
   (« tout bien posé », « C3 décollée », « C3 remise », « pastille gauche décollée »…) ; « fin »
   arrête. Il n'ouvre pas le casque : il écoute le flux brut comme une application. Le fichier va
   dans `seances/brut_….npz` — c'est lui qui servira à essayer la corrélation par électrode.
1. **Bien posé** — note le σ affiché de chaque électrode, après ~30 s sans bouger :
   Fz ___ · C3 ___ · Cz ___ · C4 ___ · Pz ___ · PO7 ___ · Oz ___ · PO8 ___ µV
2. **Mal posé, exprès** — décolle légèrement OU sèche UNE électrode, attends ~10 s, note son σ et
   sa couleur ; remets-la, attends qu'elle redevienne verte. Recommence sur deux autres :
   ______ : ___ µV (couleur ___) · ______ : ___ µV (___) · ______ : ___ µV (___)
3. **Toute électrode qui reste rouge malgré tes soins** : nom et σ ______
4. **La référence** — décolle UNE pastille derrière l'oreille ~10 s : les deux petits cercles
   passent au **rouge** et le bandeau dit « RÉFÉRENCE DÉCROCHÉE ». Note la corrélation du bandeau
   pastille décollée ___ , puis recollée ___ (attendu : vers 1, puis 0,3 à 0,5).
Le bon seuil passe ENTRE les valeurs du 1 et celles du 2. Si une électrode mal posée reste verte,
ou une bien posée rouge, le seuil est à revoir : rapporte les chiffres.

✅ **2.1.1** Le mot en face : **« ALPHA NET »** (vert) ou **« ARRÊTE ICI »** (rouge). Ratio et pic dans la
ligne de chiffres.
✅ **2.1.2** Ratio **> ~1,5** → un bouton propose d'**appliquer le pic mesuré** au « Pic alpha » du SSVEP :
**accepte**. Le SSVEP n'a **pas** besoin d'être démarré — le réglage est validé, retenu, et affiché
en vert.
✅ **2.1.3** Si le son est coupé, la page **le dit** et prévient qu'on ne saura pas quand rouvrir les yeux.

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
Puis **« Tester sur une session »** → « Commencer ».

✅ **2.2.1** **« Seuil de détection »** (depuis le 2026-09-24, défaut 2,5) : de combien le score d'une cible
doit dépasser le bruit de fond du repos. Plus bas = plus de détections et plus d'erreurs ; plus haut
= l'inverse. La page de test le montre **grisé**, avec la valeur réglée ici : le test part avec. La
boucle : régler → « Tester sur une session » → comparer. ⚠️ Deux tests de 36 essais ont des intervalles larges : lis
les deux intervalles (sous « Détails ») avant de dire qu'un seuil fait mieux qu'un autre.

⚠️ **Pour comparer aux repères du 2026-07-27, teste sur le trio du dépôt : 15 · 20 · 8,571.** C'est
sur lui qu'ils ont été mesurés. Mais si ton pic alpha est sous ~10,5 Hz, la cible à 8,571 Hz tombe
dans ton alpha — prends alors le jeu proposé, et **note que le chiffre n'est plus comparable**.

✅ **2.2.2** **Fixe le disque cerclé de bleu**, dans la fenêtre. Pendant le **REPOS** du début, fixe la
**croix** et ne suis aucun disque : le moteur y mesure son fond de corrélation.
✅ **2.2.3** **Ne ferme pas la fenêtre à la main** : sans son marqueur de fin, aucun verdict.
✅ **2.2.4** Deux chiffres dans la même ligne : la **justesse quand il annonce** et le **taux d'émission** — à
lire ENSEMBLE. Repères du **2026-07-27** : **100 % de justesse** (0 confusion sur 36) pour **44 %
d'émission**. Le 2026-09-22 : 18 annonces sur 36, les 18 justes.
✅ **2.2.5** Le mot : vert si justesse ≥ 90 % **et** émission ≥ 44 % ; orange au-dessus du hasard ; rouge si
le **test binomial exact** ne rejette pas le hasard (p ≥ 0,05), ou **MUET** si le moteur n'a rien
annoncé. ⚠️ Wilson reste l'intervalle AFFICHÉ ; depuis le 2026-09-22 il ne décide plus rien.
✅ **2.2.6** La fenêtre se ferme **seule** à la fin. Le **bandeau** affiche ses deux dernières lignes — son
bilan « fin : N frames affichées, M sautée(s) (x %) », et l'alerte si trop d'images ont sauté —, pas
le journal essai par essai. **Relève le x %** (point 1.13).
✅ **2.2.7** Le résultat en trois lignes — le mot, les chiffres (« … de cibles justes quand il annonce …
(hasard 33 %) · il annonce sur … des 36 essais »), une réserve —, le reste sous « Détails ».
✅ **2.2.8** La note grise « Décodage de « SSVEP » arrêté pour ce test… » est encore là, et le SSVEP reste
arrêté. `data/` n'a rien gagné.

❌ Régression : la justesse s'effondre — c'est le **seul** mode déjà validé sur un cerveau : suspecte
la séance (contact, saline, fatigue) avant le code.
⚠️ **Un essai = UNE décision.** Un effectif ~7× plus grand que 36, c'est que les fenêtres glissantes
ont été comptées comme indépendantes.
⚠️ Depuis le 2026-09-22 ce test **décide par le runtime du mode** (l'écart de σ — 8 voies ici,
4 occipitales filtrées dans le mode — est supprimé). **Le prix : ces chiffres ne se comparent plus
tels quels au 100 %/44 % du 2026-07-27**, mesuré sous l'ancienne règle. C'est écrit dans « Détails ».

→ recette 2.2

✅ **2.2.9** (2026-10-01) **Retour en direct** : après chaque essai, le disque décodé est entouré en vert
(juste ou non), rien si le moteur s'est abstenu. ⚠️ Le test SSVEP décide désormais essai par
essai pendant la séance (pour publier en direct) — par le même chemin que le verdict.

### ☐ 2.3 — c-VEP : Entraîner puis Tester

Page **c-VEP** → **« Entraîner »** (~3,1 min, stabilisation du casque comprise) → « Commencer ».

✅ **2.3.1** La fenêtre c-VEP s'ouvre **toute seule**, blocs entrelacés.
✅ **2.3.2** Le chiffre : une **justesse eCCA (validation croisée)** contre **son** hasard (1/6 ≈ 17 %, jamais 50 %), et sous
« Détails » le test **McNemar** qui compare les deux décodeurs — pas l'écart des deux pourcentages.
Repères du dépôt : **59,5 / 64,9 %** (hors ligne). Le 2026-09-22 : 25,0 %.
✅ **2.3.3** **« Enregistrer le modèle »** → « ← c-VEP » → **« Tester sur une session »** (3 cycles par cible, 18 blocs,
~2,5 min) → « Commencer ». Fixe le disque **cerclé**, sans bouger les yeux.
ℹ️ Si tu refais un test, **note l'ordre et l'heure de chacun** : le 2026-10-05, trois tests c-VEP à la suite ont donné 11 %, 22 % puis 50 % d'émission (même modèle). Observé UNE fois, cause inconnue (recette 2.9) — ce n'est pas une règle.
✅ **2.3.4** Deux chiffres ensemble : **justesse quand il émet** et **taux d'émission**, à comparer au couple
**EN DIRECT** du dépôt — **~46 % d'émission, ~71 % de justesse** —, jamais au 59,5/64,9 %.
⚠️ **Orange est le résultat attendu d'un système AU repère** : à 18 blocs, il ne sort vert qu'environ
une fois sur quatre (calculé, pas mesuré). La réserve nomme le réglage à tourner.

✅ **2.3.5** (2026-10-01) **Retour en direct** : à la fin de chaque bloc, le disque décodé est entouré en vert
(juste ou non), SEUL pendant ~1 s (phase de retour : plus de cercle bleu, les disques clignotent
toujours), puis le cercle bleu suivant. Note si l'anneau arrive **trop tard** ou part trop vite pour
être vu, et si le voir change ta façon de fixer.

❌ Échec : **MUET** ou « NON MESURÉ » sans autre explication. ⚠️ **C'est la panne caractéristique
du c-VEP** : une phase fausse de quelques frames ne lève rien, les corrélations baissent juste assez
pour que rien ne se déclenche. La réserve distingue horloge, seuils et vote — lis-la.
🔴 **La séance longue avec journal et l'A-B-A contre l'écran archivé (recette 2.9) n'ont PLUS de
chemin dans la console** jusqu'à « Connecter » : ce sont les montages à terminaux de la recette. Le
test ne les remplace pas — il ne dit rien de « réseau contre local ».

→ recette 2.9

### ☐ 2.4 — P300 : Entraîner puis Tester

Page **P300** → **« Entraîner »** (~2,2 min, 12 manches) → « Commencer ».

✅ **2.4.1** Le chiffre (cibles retrouvées, validation croisée par manche, hasard 17 %) → **« Enregistrer le modèle »**.
✅ **2.4.2** « ← P300 » → **« Tester sur une session »** (6 manches, ~1,4 min) → « Commencer ». À chaque manche la fenêtre
**cercle** une cible : fixe-la.
✅ **2.4.3** Le verdict : « … de cibles justes … (hasard 17 %) sur 6 manches ». Vert à 80 %, orange de 60 à
80 %, rouge en dessous ou si le binomial exact ne rejette pas le hasard : **5/6 vert (p < 0,001),
4/6 orange (p = 0,009), 3/6 rouge (p = 0,062 — la porte se ferme là)**.
⚠️ **Une ou deux erreurs sur six sont attendues** (AUC mesurée 0,71). À **24 manches** (~5,0 min)
la porte s'ouvre dès **8/24** (p = 0,035) : si la réserve le dit, refais à 24.
✅ **2.4.4** ⚠️ **Le comptage mental n'est PAS requis** (validé casque) — une bonne fixation suffit, et le
briefing le dit (« Compter les éclairs de ta cible aide à rester attentif, mais ce n'est pas
obligatoire »).

✅ **2.4.5** (2026-10-01) **Retour en direct** : après chaque manche, la cible retenue est entourée en vert
(juste ou non).

❌ Échec : la cible retenue systématiquement décalée d'une position, ou une confiance élevée sur une
cible fausse — la signature d'un décalage à l'épochage, la panne qui rend tous les autres tests
verts. Avec le retour, ça se VOIT : l'anneau toujours sur la voisine de la cible désignée.

→ recette 2.7

### ☐ 2.5 — ErrP : le moteur voit-il que la machine s'est trompée ?

Page **ErrP** → **« Entraîner »** (~5,7 min, 200 essais) → « Commencer » → **« Enregistrer le
modèle »** → « ← ErrP » → **« Tester sur une session »** (80 essais, ~2,4 min, ~22 erreurs délibérées).

✅ **2.5.1** Au début du test, **regarde la piste immobile sans bouger** : le moteur y mesure ton bruit de fond
(la page le dit).
✅ **2.5.2** Le verdict est un **COUPLE** : « garde X % des bonnes commandes, attrape Y % des erreurs (hasard :
Z %, autant qu'il en annule) ». Pas de 50 % : un détecteur au hasard attrape autant d'erreurs qu'il
annule de bonnes commandes.
✅ **2.5.3** Repère du dépôt : **AUC 0,776** (p = 0,0099) ; au réglage 85 %, **une erreur attrapée sur deux** —
un taux optimiste, le seuil ayant été choisi sur les scores qui le mesurent. Attends-toi à garder
**moins** de bonnes commandes que visé.

❌ Échec : le détecteur annonce « erreur » sur presque tout, ou sur rien.
⚠️ **Un score PARFAIT est un signal d'alarme, pas une réussite.** Pendant le test, la fenêtre
publie la réponse de chaque pas ; elle doit atteindre le CORRECTEUR et jamais le DÉCODEUR. C'est
`errp_test.py` qui tient cette cloison (bloc 0) — l'écran ne peut pas la montrer.
⚠️ En décodage continu, le marqueur `feedback` reste **nu** : pas de `error: true|false`.

→ recette 2.8

### ☐ 2.6 — Motor Imagery : Entraîner puis Tester

Page **Motor Imagery** → **« Entraîner »** → choisis les **tâches** → « Commencer ». Le moteur
mène : il tire les tâches, affiche les consignes, décompte. Aucune fenêtre. Durée à 14 essais par
tâche : **~4,8 min à 2 tâches**, ~7,0 min à 3.

✅ **2.6.0** (2026-10-15) **« Tâches à imaginer »** : un nombre (2 à 5, **2 par défaut** : LEFT,
RIGHT), puis autant de champs. Passe à 3 : un 3ᵉ champ apparaît ; repasse à 2 puis 3 : ce que tu y
avais tapé est toujours là. « Essais par classe » propose aussi **40** (~12 min à 2 tâches : la
fatigue joue contre, ce n'est pas le défaut). Un champ vide ou deux fois la même tâche → « Commencer » est **refusé**,
avec la raison. Pendant l'essai, l'écran **nomme** la tâche tapée (« Imagine : PIEDS ») ; LEFT et
RIGHT gardent leur consigne détaillée et leur top latéralisé, toute autre tâche — un repos compris
— a un top **court et centré**. « gauche » tapé devient LEFT (2026-10-20 : les noms que reçoit
l'application sont en anglais) ; « repos » reste « repos », une tâche comme les autres. (2026-10-15) Une **croix** « + » au-dessus de
la consigne pendant la mise en route et l'imagerie, pour TOUTES les tâches : fixe-la ; elle s'efface
pendant la pause **sans que la page bouge**.
🟡 **2.6.0 bis** (2026-10-15) **« Mise en route »** (1 à 3 s, défaut 3 s) : le temps, après le top,
avant que l'enregistrement ne commence. Pour savoir laquelle te convient, **dans la même séance** :
entraîne un modèle à 3 s puis un à 1 s (mêmes tâches), « Tester sur une session » chacun, et note
les deux chiffres. « Détails » dit la mise en route du modèle (« … · mise en route 1 s »), et le test
la rejoue d'elle-même. ⚠️ Deux tests de 12 essais ne séparent qu'un écart énorme : c'est un premier
relevé, pas une preuve.
✅ **2.6.1** Le chiffre est une **justesse honnête** (validation croisée **par essai**), contre le
hasard de **ton** nombre de tâches (50 % à 2, 33 % à 3), et le **seuil** à atteindre pour
l'écarter (« il faut au moins 75 % » à 20 essais et 2 tâches). Repères ré-mesurés, **pour les poings
seulement** : **40,0 % à 3 classes** (p = 0,082, **PAS** significatif) et **63,3 % en
gauche/droite** (p = 0,038). Pour d'autres tâches (pieds/mains…), **aucun repère** : le résultat le
dit.
✅ **2.6.2** « ← Motor Imagery » → **« Tester sur une session »** (6 essais par tâche, ~1,9 min à 2
tâches) → « Commencer ». Mêmes tâches et mêmes consignes que l'entraînement — elles viennent du
modèle —, et le moteur décide.
🔴 **Rouge est le résultat ATTENDU ici, à toutes les longueurs.** Sur les essais **annoncés**
(un `-1` sort du dénominateur), il faut **10/12** à 2 tâches, **10/18** à 3 si les 18 annoncent,
**15/30** à 3 tâches et 10/classe, pour rejeter le hasard — le repère du projet est à 63 % en
gauche/droite et 40 % à 3 classes, en dessous de ces portes. Lis ce rouge « pas de preuve », jamais
« ça ne marche pas », et **note le chiffre et sa p-value**. Rallonger à 10 essais/classe ne suffit
pas non plus : c'est un constat, pas un réglage. Sans repère (pieds/mains), le mieux possible est
**orange** : au-dessus du hasard, sans rien à quoi comparer.

🟡 **2.6.3** **Facultatif, si le temps le permet : FBCSP.** Refais un entraînement avec la case **« FBCSP »**
cochée et la bande à **4–40 Hz**, puis « Tester sur une session ». Note les deux chiffres et « Détails » (qui dit
la méthode). Même geste pour la case **« LDA régularisée (shrinkage) »** (2026-10-15) : « Détails » dit
« … + LDA régularisée ». Sans refaire de séance, `python src/research/mi_compare.py` compare toutes les
variantes sur l'enregistrement du dernier entraînement. ⚠️ **Ce n'est PAS une comparaison** : deux séances différentes, et le test MI ne
sépare même pas 40 % de 33 %. C'est un premier relevé ; la comparaison honnête se fait sur UNE
séance, par validation croisée (`research/mi_compare.py`).

❌ Échec : un chiffre d'entraînement nettement au-dessus des repères doit **éveiller un soupçon** —
c'est ce que la fuite entre fenêtres produisait (79 % non reproductible).
⚠️ **`-1` veut dire « vote non conclu »**, jamais « repos » : le test le compte dans le taux
d'émission, pas comme une erreur.

→ recette 2.6

### ☐ 2.7 — Neuro : le mode dont le CONTENU n'a jamais été validé

Page **Neuro** → **« Observer »**. Repos de 25 s, puis les indices défilent.

✅ **2.7.1** Pendant la stabilisation et le repos, un **compte à rebours** : « décodage dans ≈ 32 s » (tuile,
page du mode et vue en direct), puis « décodage dans un instant… » si le repos se prolonge.

✅ **2.7.2** Les trois indices bougent, et aucun chiffre de justesse n'est annoncé — il n'y a pas de bonne
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

✅ **2.8.1** À l'ouverture : « 1 casque(s) appairé(s) à ce PC : UN-…. Allume le tien, puis OK : la console te
dira s'il répond. » — en **gris**, jamais « trouvé », jamais vert. Le dernier casque utilisé est en
tête de liste.
✅ **2.8.2** « **Appairer un casque…** » ouvre la page Bluetooth des Paramètres de Windows (un casque neuf s'y
appaire, une fois par PC) ; « **Actualiser la liste** » la relit.
✅ **2.8.3** Casque éteint + OK → l'écran revient avec la raison (point 1.12) ; casque allumé + OK → la console
s'ouvre.

❌ Échec : un message qui dit « trouvé » ou un vert pour un casque éteint ; l'écran qui se fige.

### ☐ 2.9 — Le casque décroche en pleine séance, et revient

Console ouverte sur le casque, un mode qui décode (le SSVEP par exemple). **Éteins le casque**
(ou éloigne-le hors de portée) ~10 s, puis rallume-le.

✅ **2.9.1** En ~2 s, le bandeau : « ⚠ LIAISON PERDUE avec le casque depuis N s : plus rien n'est décodé.
Reconnexion en cours (essai n)… inutile de fermer la console. » ; les σ disent « plus aucun
échantillon ».
✅ **2.9.2** Pendant la coupure, le flux décodé se TAIT (« Ce que voit ton application ») : aucune cible
répétée en boucle.
✅ **2.9.3** Casque rallumé : en quelques secondes, « Liaison rétablie après N s : les modes refont leur
repos… » ; le mode repasse par la stabilisation puis le repos, et décode de nouveau **sans avoir
relancé la console**.
✅ **2.9.4** Un test ou un entraînement en cours pendant la coupure est **annulé**, avec « La liaison avec le
casque s'est coupée pendant la séance… ».
✅ **2.9.4 bis** (2026-10-20) Pendant la coupure, sur **« Vérifier le casque »**, tous les cercles sont
**vides** et la phrase dit « Pas de mesure » ; ils se recolorent quand la liaison revient.

❌ Régression : l'écran se fige et il faut relancer la console (le comportement d'avant le
2026-09-25) ; ou le flux décodé continue d'annoncer une cible pendant la coupure ; ou les essais de
reconnexion s'enchaînent avec `ANOTHER_BOARD_IS_CREATED_ERROR:16` (l'ancienne session n'a pas été
libérée — le défaut corrigé le 2026-09-25).
✅ **2.9.5** **Joué au casque le 2026-09-25 : la liaison se rétablit seule.** Le premier passage avait échoué
(81 essais refusés), le correctif `6f61db4` l'a réglé.
✅ **2.9.6** **À rejouer (2026-10-01) : casque éteint LONGTEMPS** (une minute, ou batterie à plat). Le
2026-09-25, la première réouverture avait réussi ; quand elle échoue, le moteur MOURAIT (« LE MOTEUR
S'EST ARRÊTÉ », vu avec une batterie à plat). Attendu : le bandeau compte les essais (n, n+1…)
toute la minute, la console reste vivante, et le casque rallumé (ou rechargé) revient seul.
❌ Échec : « LE MOTEUR S'EST ARRÊTÉ » pendant une coupure, quelle que soit sa durée.
⚠️ Après la reconnexion, **regarde C3 et Cz** au bandeau : la réouverture redémarre
l'amplificateur, et elles saturaient à chaque réouverture. Note combien de temps.

### ☐ 2.10 — Batterie et liaison : les icônes du bandeau

Console ouverte sur le casque.

✅ **2.10.1** **Tout à droite de la première ligne** : une **pile** qui se remplit selon la batterie, suivie de
« 73 % » (lu sur le casque le 2026-09-25), puis **4 barres** de liaison. Au survol des barres :
« N % des échantillons perdus sur les 10 dernières secondes ».
✅ **2.10.2** Les **messages** (référence décrochée, liaison perdue, refus…) sont sur une **seconde ligne**, qui
n'apparaît que s'il y a quelque chose à dire.
✅ **2.10.3** Éloigne le casque du PC (autre pièce) : les barres **baissent** (3 jusqu'à 1 % de pertes, 2
jusqu'à 5 %, puis 1), et dès 1 % un message orange « liaison dégradée… rapproche le casque ».
**Note à quelle distance, et quel taux** : aucune perte n'a encore été observée (0 sur 2 490).
✅ **2.10.4** Liaison perdue : 0 barre, barrée d'une croix rouge. Sous 20 % de batterie, la pile rougit et
« recharge le casque avant ta prochaine séance » apparaît en dessous.
✅ **2.10.5** Sur le board de test : **ni pile ni barres** (sa batterie est fabriquée, il n'a pas de liaison
radio).

❌ Échec : une pile ou des barres sur le board de test ; des barres pleines pendant une coupure.

### ☐ 2.12 — « Tester librement », au casque (c-VEP, SSVEP, P300, MI)

Page du mode → bloc Tester → **« Tester librement »**. La fenêtre s'ouvre tout de suite : tant
que la **croix** est là, fixe-la, ne fixe aucune cible (c'est le repos du moteur, mesuré AVEC le
clignotement).

✅ **2.12.1** Fixe la cible de ton choix : l'anneau **vert** vient sur elle en quelques secondes, et la suit
quand tu changes. Au P300, il apparaît à la fin de chaque manche.
✅ **2.12.2** Regarde ailleurs (entre les cibles) : l'anneau **disparaît** en ~1 s — le mode s'abstient.
✅ **2.12.3** Ferme la fenêtre : le mode s'arrête s'il ne tournait pas avant, et la page le dit.
**Note** le délai entre « je fixe » et « l'anneau arrive », par mode.

✅ **2.12.4** (2026-10-15) **Motor Imagery** — vérifie d'abord le **modèle** choisi dans « 1. Régler »
(celui des tâches que tu veux essayer) et que C3/Cz ne saturent pas au bandeau. Page MI → « Tester
librement » → contrôle de liaison → la fenêtre s'ouvre : une **croix** pendant la stabilisation
(~15 s), puis **les tâches du modèle**, en grand (PIEDS, MAINS…). Imagine-en une : son cadre devient
**vert** et la ligne du bas dit « Décodé : … » ; ne fais rien : « Rien de décodé » (le vote ne
conclut pas — sauf si un repos est une des tâches, qui s'encadre alors comme les autres). Échap
ferme, et le mode s'arrête s'il ne tournait pas avant. **Note** le délai entre « j'imagine » et « le
cadre arrive ».

❌ Échec : l'anneau ne suit jamais la cible fixée alors que « Tester sur une session » est bon ; ou il reste sur
une cible quand tu regardes ailleurs. Pour le MI : la fenêtre reste sur « Je cherche le flux… »
alors que le mode tourne, ou affiche d'autres tâches que celles du modèle.

### ☐ 2.11 — Les filtres d'affichage du Brut, sur un vrai signal

Console ouverte sur le casque, depuis au moins une minute. Tuile **Brut** → « Ouvrir ».

✅ **2.11.1** Sur **« Aucun (signal brut) »** : certaines voies **dérivent** en y (relevé le 2026-09-25) — c'est
le point de départ, pas un défaut.
✅ **2.11.2** Sur **« Passe-haut 1 Hz »** (le défaut) : plus aucune dérive, les huit tracés sont centrés dans
leur couloir, et l'écart (« un couloir = … µV ») baisse nettement.
✅ **2.11.3** Cligne des yeux : une **bosse sur Fz**, suivie d'un petit rebond (le prix d'un passe-haut, dit
dans la bulle ⓘ). Elle est plus haute à 0,1 Hz qu'à 2 Hz.
✅ **2.11.4** Coupe-bande **décoché** : si une voie est nettement plus « épaisse » que les autres, c'est du
50 Hz — un contact à reprendre. Coche-le : l'épaisseur disparaît.
✅ **2.11.5** Pendant qu'on change de filtre, **« Ce que voit ton application »** montre toujours le même flux
brut : le filtre ne touche **que** le tracé.
**Compare avec la Unicorn Suite** si tu l'as sous la main : la liste est une proposition, faite de
mémoire. Note ce qui manque.

❌ Échec : une dérive qui reste à 0,5, 1 ou 2 Hz ; des tracés qui **tremblent** à chaque
rafraîchissement ; le flux publié qui change avec le filtre.

---

# Bloc 3 — le réseau, vu d'une application cliente

C'est le produit. Un mode doit tourner pendant tout ce bloc : grille → sa tuile → **« Démarrer »**.

### ☐ 3.1 — Un client Python sur la même machine

Le client est **ton** application : taper sa commande est normal.

```bash
python -u examples/receiver.py --stream decoded_ssvep
```

✅ **3.1.1** Le client trouve le flux **par son nom complet** (`EEG_API_Unicorn_decoded_ssvep`) et affiche des
décisions.
✅ **3.1.2** « Ce que voit ton application » montre le même flux, sous le même nom.
⚠️ L'extrait « Brancher un client » a quitté la page du mode le 2026-09-22 ; il reviendra avec
« Connecter ». En attendant, la référence est `examples/`.

❌ Régression : le client ne trouve pas le flux alors qu'il est « publié » sur la tuile.
⚠️ Un flux décodé **existe dès le démarrage du mode** et reste **silencieux** pendant la chauffe et
le repos (~23 s pour le SSVEP). Ne pas relancer le moteur en croyant le flux absent.

→ recette 1.6, 3.1

### ☐ 3.2 — Depuis une deuxième machine

Même client, sur un autre PC du réseau.

✅ **3.2.1** Le flux est trouvé, et `time_correction()` est **appliqué** — l'écart entre les deux horloges se
compte en **semaines** (`local_clock()` part du démarrage de chaque machine), pas en millisecondes.

❌ Échec : les horodatages reçus sont inutilisables pour joindre deux fichiers. Sans
`time_correction`, le dépouillement d'une séance à deux machines est faux, sans rien pour le dire.

→ recette 3.2

### ☐ 3.3 — Unity

`examples/unity/` : `SsvepIntentReceiver.cs` + `IntentToMotion.cs`, avec LSL4Unity.

✅ **3.3.1** Les deux scripts **compilent**.
✅ **3.3.2** La scène trouve le flux par son nom, et l'objet **s'arrête** quand le flux se tait (chien de
garde) au lieu de continuer sur une intention périmée.
✅ **3.3.3** `-1` arrête l'objet — il ne le fait **pas** partir vers la cible 0.

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
