# Configurer · Entraîner · Tester — la boucle, et rien d'autre

**Statut** : spec à valider. Aucun code écrit.
**Origine** : séance casque du 2026-09-22. Dix minutes de fixation perdues sur un mode arrêté,
suivies de ce constat : « je ne comprends pas trop ce que l'on fait », « l'app semble bien trop
compliquée là où elle ne devrait pas et pas assez de contrôles là où c'est nécessaire ».

---

## 1. Le problème, et sa racine

L'outil a été construit avec le vocabulaire et la forme des **expériences** qui ont servi à savoir
si ces six modes décodaient quelque chose : calibration, stimulus, marqueurs, plancher de repos,
mesure. C'est le vocabulaire de celui qui cherche. Le produit, lui, s'adresse à un étudiant qui
**a une application à faire marcher** et qui n'a aucune raison de connaître ces mots.

La conséquence n'est pas seulement de la verbosité. Les gestes sont à plat — « Démarrer »,
« Calibrer », « Lancer le stimulus » se présentent comme trois actions de même rang qu'on choisit
librement — alors qu'il existe **un ordre**, et qu'en sauter un rend les autres inutiles sans que
rien ne le dise. C'est très exactement ce qui s'est produit : le stimulus lancé sur un mode arrêté,
dix minutes de fixation dans le vide, et l'application qui regarde faire.

### La boucle réelle

L'utilisateur ne « pilote pas des modes ». Il cherche une configuration qui marche, par essais :

```
    régler (rafraîchissement, pic alpha)
        → proposer des fréquences
            → TESTER
                → ça ne va pas → ajuster → re-tester
                → ça tient → transcrire dans son app → connecter
```

Le tour se fait **plusieurs fois**. Exemple donné en séance : ça marche à 60 Hz, l'étudiant code son
Unity, découvre qu'il ne tiendra que 30 fps, revient, entre 30, adapte les fréquences, re-teste.

**L'outil doit rendre ce tour rapide.** Tout le reste est subordonné à ça.

---

## 2. Périmètre

**DEDANS** : configurer · entraîner (là où c'est nécessaire) · tester · afficher les résultats
lisiblement, en couleur.

**DEHORS, explicitement** — second chantier :
- **« Connecter »** : l'interface avec une application tierce, et avec elle le décodage continu
  publié sur le réseau (l'actuel « Démarrer »).
- Le **dépouillement automatique** d'une séance (jointure journal ↔ verdicts).
- Tout ce qui concerne la déclaration de paramètres *par* le client.

⚠️ Fixer les paramètres **dans l'outil** est normal et le reste : c'est un banc d'essai. On ne code
pas une application entière pour découvrir si le principe tient.

---

## 3. La forme d'une page de mode

Trois blocs numérotés, dans l'ordre, et rien d'autre :

```
  ← Modes     SSVEP — quelle cible clignotante l'utilisateur regarde

  ┌ 1. Régler ─────────────────────────────────────────────────┐
  │  Rafraîchissement de l'écran   [ 60 ] Hz                    │
  │  Pic alpha de la personne      [ 10,0 ] Hz   [ Mesurer ]    │
  │  Fréquences des cibles         [ 12, 15, 20 ]  [ Proposer ] │
  │                                              [ Appliquer ]  │
  └─────────────────────────────────────────────────────────────┘

  ┌ 2. Tester ─────────────────────────────────────────────────┐
  │                        [ Tester ]                           │
  │  🟠 UTILISABLE — 38,5 % de cibles justes (hasard 17 %)      │
  │     sur 90 essais                                           │
  │  ⚠ mesuré hors ligne : en séance le moteur se tait souvent  │
  │                                            [ Détails ▾ ]    │
  └─────────────────────────────────────────────────────────────┘
```

Pour les modes à modèle, un bloc **« 2. Entraîner »** s'intercale, et « Tester » devient le 3.

### Les trois (ou deux) gestes

| Bloc | Qui l'a | Ce qu'il fait |
|---|---|---|
| **1. Régler** | tous | Les champs du contrat, plus ce qu'il faut pour TROUVER les valeurs : « Proposer » (existe), « Mesurer » (neuf, pour le pic alpha). |
| **2. Entraîner** | MI, P300, ErrP, c-VEP | L'actuel « Calibrer ». Produit un modèle, affiche son score, propose de le garder ou de refaire. |
| **3. Tester** | SSVEP, MI, P300, ErrP, c-VEP | **UN** bouton. Joue un protocole **borné**, sur les réglages **courants**, et rend un score. |
| **Observer** | Neuro, Brut | Ces deux modes n'ont aucune vérité-terrain : il n'y a pas de bonne réponse à comparer. Montre les indices ou les tracés en direct, **sans annoncer aucun chiffre de justesse**. Ni « Entraîner », ni « Tester ». |

### Ce qui disparaît de la page

- **« Démarrer » / « Arrêter »** → partent avec « Connecter » (second chantier). Le décodage
  continu sans vérité-terrain n'aide pas à valider une configuration, et c'est lui qui a permis de
  fixer dix minutes dans le vide.
- **« Lancer le stimulus »** → n'est plus un geste de l'utilisateur. La fenêtre devient un **rouage
  interne de « Tester »**, lancé et fermé par lui.
- **« Brancher un client »** (l'extrait de code) → part avec « Connecter ».
- **Le bloc « Sortie en direct »** → n'existe plus que sous « Observer », pour Neuro et Brut.

### Ce que ça règle par construction

Un bouton unique qui **possède toute la séquence** — démarrer le mode, ouvrir la fenêtre, collecter,
fermer, conclure — rend le piège du 2026-09-22 **impossible**, au lieu de le signaler. Il n'y a plus
d'ordre à respecter : il n'y a plus qu'un geste.

---

## 4. Ce que « Tester » veut dire, mode par mode

**Définition** : un protocole **borné dans le temps**, qui **désigne** ce que l'utilisateur doit
faire, laisse le moteur **décider avec ses règles réelles**, et compare. Il rend un score **avec son
niveau de hasard**, et **n'écrit rien sur le disque**.

⚠️ **Cette machinerie existe déjà** : c'est `core/modes/mesure.py` (`MesureRuntime`) — un protocole
minuté qui rend un verdict au lieu d'un modèle, affiché par une page générique. Elle n'a jamais été
généralisée : elle sert **un mode sur six**, et elle est nommée d'après sa métrique (« Taux
d'émission SSVEP ») plutôt que d'après son but. **Ce chantier la généralise et la renomme ; il ne
l'invente pas.**

⚠️ **Et le protocole de test est le protocole d'ENTRAÎNEMENT, avec un autre consommateur.** Les
fenêtres de P300, d'ErrP et de c-VEP désignent déjà une cible et publient leur vérité-terrain en
calibration. Tester, c'est rejouer exactement ça pendant que le moteur **décode** au lieu
d'**apprendre**. Rien de nouveau à afficher, rien de nouveau à publier.

| Mode | Vérité-terrain | Score rendu | Hasard |
|---|---|---|---|
| **SSVEP** | la fenêtre guidée désigne une cible par essai | taux d'émission **et** justesse à l'émission | 1/N cibles |
| **c-VEP** | la fenêtre cercle une cible par bloc | justesse **et** taux d'émission | 1/6 |
| **P300** | la fenêtre cercle la cible de la manche | justesse de sélection | 1/6 |
| **MI** | le moteur tire la classe et l'annonce | justesse | 1/3 (ou 1/2 en G/D) |
| **ErrP** | la fenêtre commet des erreurs délibérées | **couple** : part des bonnes commandes gardées / part des erreurs attrapées | — (détecteur, pas sélecteur) |

🔴 **Le risque principal de tout ce chantier est sur l'ErrP.** Son étiquette voyage sur le marqueur
`feedback` **en calibration seulement** : en décodage le marqueur est nu, délibérément, parce que
c'est une BCI **passive** et que donner la réponse au décodeur rendrait faux tout ce qu'on mesure.
Pour un TEST, il faut la vérité-terrain — donc le marqueur étiqueté. **L'étiquette doit atteindre le
CORRECTEUR et jamais le DÉCODEUR.** Une fuite ici produit un score parfait et faux, et rien ne le
dirait. C'est le seul endroit du chantier qui demande une cloison explicite, et elle doit être tenue
par un test, pas par la relecture.

⚠️ **« Tester » exige un modèle** sur les quatre modes à modèle, et c'est le moteur qui le refuse,
pas l'interface — la règle vit déjà dans le contrat. L'ordre Entraîner → Tester n'est donc pas une
convention d'écran : il est tenu par un refus, avec sa raison.

⚠️ **Le test tourne sur les réglages COURANTS.** C'est le point entier du bouton. La mesure SSVEP
actuelle tourne sur le trio du dépôt quel que soit le réglage — j'avais noté ça comme « une
décision, pas un correctif », au motif que changer les fréquences ferait perdre la comparaison avec
les repères de juillet. C'est le réflexe de la phase d'essai : **un « Tester » qui ne teste pas ta
configuration ne sert à rien.** La comparabilité devient une note dans « Détails », pas une
contrainte sur le protocole.

---

## 5. L'affichage d'un résultat

**Visible par défaut, trois lignes :**

1. **Un verdict coloré**, en gros — le mot, pas la phrase.
2. **La mesure et son point de comparaison**, dans la même ligne : « 38,5 % de cibles justes
   (hasard 17 %) sur 90 essais ». Jamais un pourcentage seul.
3. **Une phrase de réserve**, courte, qui dit de quoi se méfier.

**Derrière « Détails ▾ »** : l'effectif détaillé, les essais jetés, les comparaisons entre décodeurs
(McNemar et sa p-value), les repères historiques du projet, le nom du fichier produit, et la phrase
d'honnêteté complète.

### Le code couleur

| | Quand | Ce que ça dit |
|---|---|---|
| 🟢 **vert** | au niveau des repères du projet, ou au-dessus | Ta configuration tient. Continue. |
| 🟠 **orange** | nettement au-dessus du hasard, mais en dessous des repères | Utilisable, mais tu peux mieux faire. La phrase dit quoi essayer. |
| 🔴 **rouge** | au niveau du hasard, ou protocole inexploitable | N'utilise pas ça. La phrase dit quoi reprendre. |

⚠️ **Les seuils viennent du MOTEUR, pas de l'interface.** Les trois niveaux existent déjà dans les
verdicts actuels (« FAIBLE », « UTILISABLE », « AU NIVEAU DU REPÈRE ») : la console les **colore**,
elle ne les recalcule pas. Une seconde table de seuils côté écran divergerait de celle du moteur, et
le jour où elle diverge, elle peint en vert un résultat que le moteur juge faible.

### Ce qu'on ne supprime pas

Les phrases d'honnêteté — « ce chiffre est hors ligne », « ce n'est pas ce que tu relèveras en
séance », « ne choisis pas sur l'écart des deux pourcentages » — **portent des réserves qui
empêchent des conclusions fausses**. Elles ne sont pas de la verbosité : chacune a été écrite après
une conclusion fausse réellement tirée. Elles sont **rangées**, pas retirées. Une seule survit en
face : celle qui changerait la décision qu'on s'apprête à prendre.

---

## 6. Le vocabulaire

| Aujourd'hui | Demain | Pourquoi |
|---|---|---|
| Calibrer | **Entraîner** | On produit un modèle. « Calibrer » est le mot de l'instrument, pas du résultat. |
| Lancer le stimulus | *(disparaît)* | Ce n'était pas une fonctionnalité : c'est un rouage de « Tester ». |
| Taux d'émission SSVEP | **Tester** (sur la page SSVEP) | Nommé d'après son but, pas d'après sa métrique. |
| Contrôle alpha | **Vérifier le casque** (grille) + **Mesurer** (champ Pic alpha) | Deux rôles : une barrière de séance, et un chercheur de paramètre. Même moteur, deux portes. |
| Démarrer / Arrêter | *(part avec « Connecter »)* | |
| mesure · calibration · marqueurs · plancher de repos | *(n'apparaissent plus à l'écran)* | Vocabulaire du moteur. Il reste dans le code, où il est juste. |

---

## 7. La grille

La seconde rangée « Contrôles et mesures » se réduit à **une** entrée : **« Vérifier le casque »**,
qui joue le contrôle alpha. Elle garde son rôle de **barrière** — si l'alpha ne monte pas, rien
d'autre de la séance ne veut rien dire — et le dit.

« Taux d'émission SSVEP » quitte la grille : elle devient le « Tester » de la page SSVEP.

Les sept tuiles de modes restent, avec leur raison quand elles sont grisées.

---

## 8. Ce que ça casse, et ce qu'il faut refaire

- **Les pages de mode** changent de forme : trois blocs au lieu de quatre, deux boutons au lieu de
  cinq. `console/mode_page.py` est réécrit, `console/calib_page.py` et `console/mesure_page.py`
  fusionnent en une page de protocole unique (elles partagent déjà le contrat de `state()`).
- **Quatre `MesureRuntime` nouveaux** : `p300_test`, `cvep_test`, `errp_test`, `mi_test`. Chacun
  rejoue le protocole d'entraînement de son mode avec un consommateur différent.
- **Le contrat gagne un champ** : un mode déclare s'il est testable et par quel runtime, comme il
  déclare déjà sa calibration. La console n'en tient aucune liste.
- **La QA** : le bloc 1 est réécrit autour des trois gestes. Les points 1.5 à 1.10 changent de
  forme ; 1.6 bis disparaît (ses six correctifs sont absorbés).
- **`docs/recette.md` et `CLAUDE.md`** : le vocabulaire y est partout.

### Ce qui ne bouge pas

Le moteur décode exactement comme aujourd'hui. Aucun seuil, aucune fenêtre, aucun modèle n'est
touché. **Ce chantier ne change pas un seul chiffre** — s'il en change un, c'est un défaut.

---

## 9. Risques, dans l'ordre

1. 🔴 **La fuite d'étiquette de l'ErrP** (§4). Un score parfait et faux, silencieux. À tenir par un
   test, pas par la relecture.
2. 🟠 **Quatre protocoles de test à écrire** là où il n'y en avait qu'un. Le patron existe, mais
   chacun a sa vérité-terrain et son niveau de hasard, et se tromper de hasard (50 % au lieu de
   1/6) produit un verdict faux sans rien casser.
3. 🟠 **Perdre une réserve en repliant.** Chaque phrase d'honnêteté a été écrite après une
   conclusion fausse. Replier n'est pas supprimer, et l'inventaire doit être fait avant.
4. 🟢 **Les repères du projet deviennent moins comparables** puisque les tests tournent sur les
   réglages de l'utilisateur. C'est voulu, c'est dit dans « Détails », et c'est le prix d'un bouton
   qui sert à quelque chose.

---

## 10. Ce qui reste à trancher

- **La durée d'un test.** Trois minutes est déjà long quand on itère. Faut-il un test **court** par
  défaut (une passe rapide, intervalle large) et un test **long** sous « Détails » ? À décider en
  écrivant le plan, avec les durées réelles de chaque protocole sous les yeux.
- **Que fait « Tester » si le contact est mauvais ?** Le contrôle de liaison est aujourd'hui
  interstitiel et refuse sans porte de sortie. Reste-t-il en travers de « Tester » ?
