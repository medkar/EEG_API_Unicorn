# Passation : un jeu SSVEP sur cibles physiques (des LED dans des balles de ping-pong)

**Nature** : note de passation d'une conversation de brainstorming du 2026-10-21. **Ce n'est
pas une spec** : plusieurs points restent à vérifier (§9) avant d'en écrire une. Rien n'est
validé, aucun code écrit, aucun matériel acheté, rien n'a été essayé avec de vraies LED.
**Origine** : démontrer ce que font le casque et l'API avec un petit jeu. Les cibles sont
physiques (des LED dans des balles de ping-pong) : beaucoup de fréquences possibles, aucune
contrainte de rafraîchissement d'écran. **Un seul casque.**

---

## 1. Ce que le produit sait déjà faire, et ce qui reste dehors

- Le mode SSVEP accepte des **cibles physiques** (« Cibles affichées sur : des cibles
  physiques », `contract.CIBLES_PHYSIQUES`). La règle des diviseurs du rafraîchissement tombe,
  « Proposer » choisit au demi-hertz (`config.PAS_CIBLES_PHYSIQUES_HZ = 0.5`), avec un écart
  minimal de `1 / WINDOW_S` ≈ 0,67 Hz entre deux cibles. **Jamais joué avec de vraies LED** :
  le premier essai du plateau sera aussi la première vraie exécution de la QA 1.6 bis.
- Sur cibles physiques, les deux « Tester » sont **refusés** : rien, dans le produit, ne
  mesure aujourd'hui la justesse sur des LED. Le jeu devra apporter sa propre mesure (§7, la
  chasse).
- **Le jeu est une application CLIENTE**, comme une scène Unity. Il lit deux flux et pilote le
  plateau ; le moteur ne change pas.
  - `EEG_API_Unicorn_decoded_ssvep` : `{target_index, freq_hz, confidence, scores[]}`, environ
    5 Hz. `target_index = -1` veut dire « pas de décision » : jamais la cible 0. Le client
    associe une décision à une balle **par `freq_hz`**, pas par l'ordre des voies.
  - `EEG_API_Unicorn_status` : la phase du moteur. Pendant `warmup` et `baseline`, toutes les
    fréquences doivent clignoter sur le plateau, sans qu'on en fixe aucune : le plancher se
    mesure dans les conditions du jeu (même règle que « Tester librement »).
  - Changer le jeu de fréquences (4 pour le chaud-froid, 9 pour le morpion) se fait dans
    « 1. Régler », mode arrêté. Le flux `decoded_ssvep` est alors **recréé** et le moteur
    refait son repos (environ 23 s).
- **À confirmer** : la règle « tout l'usage réel se pilote depuis l'interface » vise le
  produit. Un jeu est une application de l'utilisateur, donc il en est dehors, comme Unity.
  Sa place naturelle est `examples/` (le client et le programme du microcontrôleur), et
  `[smoke-exemples]` y vérifiera les noms de flux cités.

## 2. Ce que les mesures du projet imposent au jeu

- **Le SSVEP est lent mais fiable.** Repère du 2026-07-27 : 100 % de justesse quand le moteur
  émet, mais il n'émet que 44 % du temps (36 essais, une personne, 3 cibles à l'écran). Une
  décision demande environ 3 s de fixation. Donc : **du tour par tour**, un jeu qui récompense
  le fait de tenir son regard, jamais la vitesse.
- **Seules 3 cibles ont été mesurées.** 4 en sont proches. 9 sont une inconnue.
- **Un temps mort après chaque changement du plateau.** La fenêtre du décodeur (1,5 s) contient
  encore l'ancien état, et l'œil doit se déplacer. Le test guidé jette 1,2 s après la consigne
  et ne garde que la dernière fenêtre d'une fixation de 3 s. Valeur de départ : ignorer les
  décisions pendant environ 2,7 s après chaque changement. À ajuster avec la chasse.
- **Un coup = une décision.** Le flux publie environ 5 fois par seconde : un client qui joue à
  chaque message jouerait plusieurs coups par fixation.
- **La lumière qui montre l'état du jeu ne touche jamais au clignotement** (même règle que
  l'anneau vert des fenêtres). Une balle qui deviendrait plus lumineuse aurait une réponse
  SSVEP plus forte : le jeu tricherait en sa faveur. L'état s'affiche en **couleur fixe**.
  Toutes les cibles clignotent dans le **même blanc**, à la même luminance.
- **Aucun retour qui clignote.** Un pion qui « flashe » pour dire « mur ! » ajoute une
  fréquence dans le champ de vision. Un refus se dit par un changement de couleur fixe ou par
  un son.

## 3. Le plateau

Une grille de **5 × 5 balles**. Le pas entre les balles est à déterminer : des balles voisines
clignotent dans la vision périphérique, et personne ne sait encore à partir de quel écart elles
ne gênent plus.

```
chaud-froid (5×5)        morpion (une balle sur deux)
●  ●  ●  ●  ●            ◉  ·  ◉  ·  ◉
●  ●  ◎  ●  ●            ·  ·  ·  ·  ·
●  ◎  ■  ◎  ●            ◉  ·  ◉  ·  ◉
●  ●  ◎  ●  ●            ·  ·  ·  ·  ·
●  ●  ●  ●  ●            ◉  ·  ◉  ·  ◉
■ pion (fixe)  ◎ clignote  ● éteinte
```

**Une fréquence n'est pas une balle.** Le moteur décode quelques fréquences, fixées dans
« 1. Régler ». Le microcontrôleur peut donner n'importe laquelle à n'importe quelle balle, et en
changer à tout moment ; le client sait laquelle porte quoi. Deux règles : jamais deux balles
allumées avec la même fréquence, et toutes les fréquences clignotent pendant le repos du moteur.
C'est ce qui permet 25 balles avec 4 fréquences.

## 4. Jeu 1 : chaud-froid

- Un **pion** en couleur fixe. Seules ses **voisines** (haut, bas, gauche, droite)
  clignotent, une fréquence par direction. On se déplace en **regardant la case où l'on veut
  aller**. Au bord, il y a 2 ou 3 voisines seulement, donc moins de cibles.
- Un **trésor** est caché sur une case. La couleur du pion passe du bleu (froid) au rouge
  (chaud) avec la distance. C'est une couleur fixe, sans risque pour le décodage.
- Après un coup, le regard est sur la case d'arrivée, qui devient le pion en lumière fixe :
  c'est un point de repos naturel avant de choisir le coup suivant.
- Variante : des **murs invisibles**. Un coup refusé se dit par une couleur fixe ou un son,
  jamais par un clignotement (§2).
- Score : le nombre de coups pour trouver le trésor. Compter environ 5 s par coup (fixation et
  temps mort), soit une à deux minutes par partie.
- **4 fréquences** : la configuration la plus proche de ce qui est mesuré. C'est le jeu le plus
  sûr des deux.

## 5. Jeu 2 : morpion contre l'ordinateur

- Sur la grille 3 × 3 prise **une balle sur deux** (lignes et colonnes 1, 3, 5) : l'écart entre
  les cibles double par rapport à un 3 × 3 serré.
- Une case libre clignote à sa fréquence. Une case prise **s'arrête de clignoter** et s'allume
  en couleur fixe (une couleur pour le joueur, une pour l'ordinateur). Chaque coup retire une
  cible : le décodage devient plus facile à mesure que la partie avance. Si l'ordinateur
  commence, le premier coup du joueur se joue entre 8 cibles.
- L'ordinateur doit pouvoir perdre : un morpion parfait finit toujours nul.
- **9 fréquences, jamais mesurées.** Dans 8–20 Hz, en évitant le pic alpha (± 1,9 Hz), elles
  rentrent à environ 1 Hz d'écart. ⚠️ À vérifier : à la lecture du code, « Proposer » maximise
  l'écart entre les fréquences mais **ne trie pas les conflits d'harmoniques**. La CCA utilise 3
  harmoniques (`N_HARMONICS = 3`) : 8 Hz et 16 Hz se ressemblent pour elle.
- **Variante à deux casques** (l'idée de départ) : un morpion coopératif où les deux joueurs
  doivent valider une case en même temps. Il faut deux PC, un moteur par casque. Les deux
  flux portent le même nom ; le client les distingue par machine (`hostname`, `source_id`).

## 6. Le matériel

### Le principe : le Wi-Fi transporte des états, jamais des clignotements

Le PC envoie « balle 12 : clignote à 13,5 Hz » ou « balle 7 : rouge fixe ». **Le
microcontrôleur fabrique le clignotement avec sa propre horloge**, en calculant la phase
(`phase = t × f mod 1`) et jamais en comptant des tours de boucle : la fréquence vient du
quartz, donc elle est exacte, et une irrégularité de quelques millisecondes ne décale qu'une
transition. Le Wi-Fi a des retards de quelques dizaines de millisecondes, parfois bien plus :
c'est invisible pour un coup de jeu, mais ça détruirait un clignotement envoyé depuis le PC.

### La carte : un ESP32 (déjà disponible)

Le Wi-Fi est demandé. Un Raspberry Pi Pico 2 W a aussi été envisagé ; l'ESP32 l'emporte parce
qu'il y en a déjà sous la main.

### Trois façons de piloter les LED

| | A. LED adressables WS2812B (« NeoPixel ») | B. LED RGB classiques + PCA9685 | C. LED RGB classiques + TLC5947 |
|---|---|---|---|
| Câblage | une chaîne de 3 fils de balle en balle ; LED individuelles, écart libre | en étoile : 4 fils par balle jusqu'au boîtier | en étoile : 4 fils par balle jusqu'au boîtier |
| Cartes pour 25 balles | aucune (1 broche de données) | 5 cartes de 16 sorties, bus I2C | 4 cartes de 24 sorties, SPI chaîné |
| Courant par couleur | fixé par la puce | une résistance par sortie (souvent 220 Ω sur la carte) ; 25 mA max | **courant constant**, une seule résistance pour 24 sorties : ~15 mA livré, jusqu'à 30 mA |
| Type de LED | intégré | **anode commune** (la carte fournit mal le courant : 10 mA) | **anode commune** uniquement |
| ESP32 | **à deux cœurs** obligatoire (ESP32 classique ou S3) | n'importe lequel | n'importe lequel |
| Coût | faible | faible (cartes à quelques euros) | ~15 € la carte, ~60 € les quatre |
| Pièges | adaptateur de niveau 3,3 → 5 V (74AHCT125) ; scintillement si Wi-Fi sur ESP32 à un cœur | bus I2C court, cartes regroupées dans le boîtier | alimentation des LED à 5 V : la tension en trop chauffe le circuit |

Notes :
- **A et le Wi-Fi.** Le signal des WS2812B est très serré. Sur ESP32, MicroPython le produit
  avec le périphérique RMT, dont il installe le pilote sur le cœur 1 pour que le Wi-Fi (cœur 0)
  ne le perturbe pas. Un ESP32 à un seul cœur (C3, S2, C6) n'a pas cette protection : des LED
  prennent une fausse couleur pendant les échanges Wi-Fi.
- **B et C ne connaissent pas ce problème** : un retard Wi-Fi retarde une mise à jour sans la
  corrompre. Ni l'une ni l'autre ne peut clignoter seule aux fréquences du SSVEP (le PWM de la
  PCA9685 ne descend pas sous 24 Hz, et ses 16 sorties partagent la même fréquence). Leur PWM
  ne sert qu'aux couleurs fixes, réglé haut (vers 1 à 1,5 kHz), loin de la bande décodée.
- **Pas de matrice multiplexée**, quelle que soit l'option : le balayage ajoute sa propre
  fréquence de clignotement et divise la luminosité.

### La luminance

- **Les mcd des fiches techniques ne se comparent pas.** La WS2812B annonce environ 550–700 mcd
  en rouge, 1100–1400 en vert et 200–400 en bleu, sur 120°. Une LED RGB de 5 mm annonce souvent
  des milliers de mcd, mais sur un faisceau de 20 à 30°. Le mcd mesure la lumière dans l'axe ;
  dans une balle qui diffuse tout, ce qui compte est le flux total, qui dépend surtout du
  courant. À courant égal, pas de gagnant clair sur le papier.
- **Les leviers** : le courant (C peut monter à 30 mA par couleur, soit deux fois le réglage
  livré) ; la diffusion (une LED dépolie, ou au dôme poncé, placée au centre de la balle, sinon
  une tache vive sur un côté) ; et surtout **l'égalité entre les balles**. Avec 12 bits de PWM,
  le programme peut garder un coefficient par balle et baisser les plus lumineuses au niveau de
  la plus faible. Une appli de luxmètre sur téléphone, à distance fixe, suffit pour comparer les
  balles entre elles (pas pour des valeurs absolues).
- Le niveau nécessaire est **inconnu** : c'est l'essai à 3 balles qui le dira (§7).

### Recommandation actuelle : C (TLC5947), avec des LED à anode commune, dépolies, du même lot

Les LED seront achetées : rien n'oblige donc à garder celles qui existent. La raison du choix
est la **marge de luminance** (jusqu'à 30 mA) et l'égalité du courant entre les balles.
⚠️ Les deux raisons données en conversation pour écarter les NeoPixel ne tiennent plus :
l'écartement n'en est pas une (elles existent en LED individuelles), et il n'y a plus de LED à
réutiliser. **A reste la plus simple à câbler** (3 fils en chaîne contre 100 fils en étoile).
Si l'essai à 3 balles montre qu'une WS2812B éclaire assez, A redevient un choix sérieux.
L'essai peut comparer les deux, pour quelques euros.

### Alimentation

En blanc plein, une balle tire 3 fois le courant d'une couleur : 45 mA à 15 mA par couleur,
90 mA à 30 mA. Pour 25 balles, c'est 1,1 A à 2,3 A dans le pire cas. Il faut une alimentation
5 V / 3 A externe (pas l'USB), avec la masse reliée à celle de l'ESP32. En jeu, le plateau
consomme bien moins : au plus 9 balles clignotent, et la moitié du temps elles sont éteintes.

### Le réseau et le protocole

- **Réseau, à trancher** :
  - A. **L'ESP32 crée son propre Wi-Fi** et le PC s'y connecte (recommandé). Ça marche partout ;
    le PC n'a plus internet, sauf par câble. Le décodage n'en a pas besoin : moteur, console
    et jeu tournent sur le même PC.
  - B. Un petit routeur dédié, qu'on emporte.
  - C. Le Wi-Fi du lieu : risqué, beaucoup de réseaux empêchent les appareils de se parler.
- **Protocole** : en conversation, TCP a été proposé. Le dépôt a déjà un patron qui convient
  mieux : `examples/actuator_udp.py`, un datagramme UDP en JSON, ré-émis en continu, avec un
  chien de garde côté récepteur. Appliqué ici : **chaque message décrit tout le plateau**, le
  PC le renvoie quelques fois par seconde, et un message perdu est remplacé par le suivant. Le
  chien de garde **éteint tout** si plus rien n'arrive (un plateau qui clignote sans personne
  aux commandes est un stimulus inutile et un risque, §8).
- **Bluetooth et Wi-Fi partagent la bande des 2,4 GHz**, souvent la même puce sur un portable.
  Le casque passe par le Bluetooth. Le plateau échange très peu, mais pendant l'essai à
  3 balles, il faut surveiller si le moteur signale des décrochages du casque. Si oui, une clé
  Wi-Fi USB séparée règle en général le problème.

### Le programme du microcontrôleur

MicroPython est proposé, pas décidé : tout le projet reste en Python pour les étudiants, et le
calcul de phase depuis l'horloge rend sans effet ses irrégularités de quelques millisecondes.
C++ serait plus régulier, mais c'est un deuxième langage à lire.

## 7. L'ordre proposé, par petits pas testés

0. **L'essai à 3 balles.** Un ESP32, un pilote, 3 balles. Le mode SSVEP en cibles physiques,
   « Démarrer », puis regarder `decoded_ssvep` dans « Ce que voit ton application » (ou
   `examples/receiver.py`). On apprend si une balle éclaire assez pour être décodée, s'il y a
   des décrochages Bluetooth, et si les fréquences sont justes (à vérifier avec une
   photodiode, ou une vidéo au ralenti dont on compte les images). On peut y comparer
   WS2812B et TLC5947.
1. **La chasse : la mesure qui manque.** Une balle est désignée par une couleur fixe à côté
   d'elle, le joueur la fixe, et le client note juste, faux ou silence, en comptant **un essai
   = une décision** (la règle de `modes/ssvep_mesure.py` : compter les fenêtres gonfle
   l'effectif d'un facteur ~7). On mesure à 4, 6 et 9 balles actives, en coupant le
   clignotement des autres, et à plusieurs écartements. Cette étape dit si le morpion à 9 se
   joue, et fixe le pas du plateau.
2. **Le chaud-froid** (4 fréquences).
3. **Le morpion**, si la chasse le permet. Sinon, repli sur le même plateau : un Simon à
   4 balles, ou une sélection en deux temps (ligne, puis colonne : 3 cibles à chaque fois).

## 8. Sécurité : épilepsie photosensible

Une lumière vive qui clignote entre environ 3 et 30 Hz peut déclencher une crise chez une
personne atteinte d'épilepsie photosensible : **ce sont les fréquences du SSVEP**. Plus le
plateau est lumineux, plus la réponse SSVEP est forte, et plus le risque l'est aussi. Le rouge
saturé est la couleur la plus à risque ; clignoter en blanc va dans le bon sens.

- Pour une démo publique : un **avertissement** et une **question à chaque volontaire** avant
  de lui poser le casque.
- Le chien de garde du plateau éteint tout quand le jeu se tait.
- ⚠️ **Le projet ne contient aujourd'hui aucun avertissement**, même pour le SSVEP sur écran
  (recherche de « épilepsie » et « photosensible » dans tout le dépôt le 2026-10-21 : aucun
  résultat). C'est un sujet à part entière, indépendant du jeu.

## 9. Questions ouvertes

1. Le réseau : point d'accès de l'ESP32 (recommandé), routeur dédié ou Wi-Fi du lieu.
2. Le pilote des LED : C (recommandé) ou A, à départager par l'essai à 3 balles.
3. Le langage du microcontrôleur : MicroPython (proposé) ou C++.
4. Le pas du plateau et la distance du joueur : à mesurer avec la chasse.
5. La règle de décision du client (première décision après le temps mort, ou deux décisions
   identiques de suite) : à régler avec la chasse.
6. La place du code : `examples/` (client et programme du microcontrôleur) est proposé.
   Confirmer que le jeu est bien hors de la règle « tout depuis l'interface ».
7. Plus tard, un « Tester » du produit pour cibles physiques passerait par le plateau, donc
   ferait entrer du matériel dans le produit. Hors sujet ici, mais c'est la question que
   posera la chasse si elle marche.
8. L'avertissement d'épilepsie dans le produit lui-même.

## Annexe : les autres idées explorées, mises de côté

Toutes reposent sur ce qu'un écran ne fait pas : des cibles placées n'importe où, déplacées,
éteintes, ou confiées à d'autres gens.

- **Lucioles** : des balles partout autour du joueur, dans le noir ; une luciole s'allume
  quelque part, on la trouve et on la fixe pour l'attraper ; les guêpes sont des pièges. Score
  sur 2 minutes. Risque : la réponse SSVEP baisse avec la distance (une balle à 3 m est petite
  dans le champ visuel).
- **Bonneteau** : trois balles identiques mélangées à la main par un complice ; le joueur suit
  la « reine » des yeux, la machine dit laquelle il suivait. Balles autonomes sur batterie.
- **1, 2, 3, soleil** : le joueur casqué est le gardien ; les autres avancent avec une balle au
  bout d'un bâton, et il les renvoie au départ en fixant leur balle. Risques : distance,
  mouvements de tête (artefacts sur électrodes sèches).
- **L'aiguilleur** : une bille (ou un petit train) attend à chaque bifurcation, deux balles
  s'allument, le joueur choisit la voie. Deux cibles à la fois, très fiable ; demande des
  servomoteurs.
- **Le mentaliste** : un numéro de 30 s ; 8 cartes, une balle au-dessus de chacune, la machine
  révèle la carte choisie « dans la tête ».
- **Simon** et **désamorçage à deux** (façon *Keep Talking and Nobody Explodes*) : écartés
  parce qu'ils dérivaient trop de l'idée de départ ; Simon reste le repli du §7.

## Sources

- WS2812B, luminance par couleur et PWM interne (~2 kHz) :
  [datasheet](https://www.superlightingled.com/PDF/WS2812B%20Datasheet.pdf)
- TLC5947, 24 sorties à courant constant, 15 mA par défaut, jusqu'à 30 V :
  [fiche Adafruit](https://littlebirdelectronics.com.au/products/adafruit-24-channel-12-bit-pwm-led-driver-spi-interface-tlc5947),
  [Texas Instruments](https://www.ti.com/product/TLC5947)
- WS2812B qui scintillent avec le Wi-Fi sur ESP32 :
  [esp32.com](https://esp32.com/viewtopic.php?p=18037) ; pilote RMT de MicroPython sur le
  cœur 1 : [esp32_rmt.c](https://git.linaro.org/plugins/gitiles/lite/micropython/+/HEAD/ports/esp32/esp32_rmt.c)
- Envoi WS2812 qui coupe les interruptions et fait perdre des octets série sur Arduino AVR :
  [forum Arduino](https://forum.arduino.cc/t/adafruit-neomatrix-mess-up-serial-rx/1059165)
- WS2812 par PIO et DMA sur RP2040 (option Pico) :
  [mcuoneclipse](https://mcuoneclipse.com/2023/04/02/rp2040-with-pio-and-dma-to-address-ws2812b-leds/)
