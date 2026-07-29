# Proposition de fréquences SSVEP — conception (chantier 2)

> Document de conception (français, interne). Écrit le 2026-07-29, validé section par section avec
> l'utilisateur. Couvre le **chantier 2** de [la console d'expérimentation](2026-07-27-console-experimentation-design.md).
> La mesure automatique du pic alpha est nommée ici mais **hors périmètre**.

## 1. Le problème

Le SSVEP n'est décodable que si l'application cliente fait clignoter ses cibles à des fréquences
qui sont des **diviseurs entiers du rafraîchissement de l'écran**. À 60 Hz : 30, 20, 15, 12, 10,
8,571… Toute autre valeur produit un clignotement irrégulier, et le décodeur corrèle alors contre
une sinusoïde que personne n'affiche.

**Le mode de panne est silencieux** : aucune erreur, aucun avertissement, simplement un décodage
qui ne détecte jamais rien — indiscernable d'un utilisateur qui fixe mal. C'est le pire défaut
possible pour un produit destiné à des étudiants qui débutent.

Aujourd'hui, la console laisse taper n'importe quelle liste de fréquences. La ligne de commande
`server.py --refresh 60` sait déjà en proposer, mais seulement au démarrage, et via la table
`COMMANDS` héritée du banc d'essai robot — donc exactement trois cibles nommées AVANT / GAUCHE /
DROITE.

## 2. Les décisions

| Question | Décision | Pourquoi |
|---|---|---|
| Proposer, ou refuser ? | **Les deux** | Proposer aide ; seul le refus ferme le trou pour celui qui tape à la main |
| D'où vient le rafraîchissement ? | **Un réglage déclaré, pré-rempli par la console** | Le moteur doit le posséder pour valider ; la console peut lire l'écran, mais l'écran du stimulus n'est pas forcément le sien |
| Qui déclenche la proposition ? | **`refresh_hz` propose `freqs`** | Le nombre de cibles est déjà la longueur de la liste : un `n_targets` créerait une seconde source de vérité |
| Sur quel alpha se cale-t-on ? | **Un réglage `alpha_hz`, défaut = moyenne de population** | Le pic alpha est propre à chaque personne ; celui du développeur est aujourd'hui codé en dur |
| Un réglage de proposition relance-t-il le repos ? | **Non, le contrat le dit** | Le décodeur ne lit jamais ces réglages ; refaire 23 s punirait l'étudiant qui prend la peine d'être exact |
| Que faire si `n` ne tient pas dans la plage confortable ? | **Élargir, et le dire** | Ne pas imposer un plafond arbitraire, mais ne pas cacher que la qualité baisse |

## 3. Pourquoi l'alpha est le cœur du sujet

Le pic alpha individuel (IAF) est **propre à chaque personne**, stable chez elle, fortement
héritable, et très variable d'un individu à l'autre : moyenne de population ≈ **9,6 Hz**,
écart-type ≈ **1 Hz**, plage 7–13 Hz, décroissante avec l'âge.
Sources : [Inter- and intra-individual variability in alpha peak frequency](https://www.sciencedirect.com/science/article/pii/S1053811914000792) ·
[Towards a reliable, automated method of IAF quantification](https://www.biorxiv.org/content/10.1101/176792v3.full.pdf) ·
[EEG Alpha Peak Frequencies Over the Lifespan](https://www.biorxiv.org/content/10.1101/2021.10.06.463353v1.full)

Une cible posée sur le pic alpha de la personne ne se distingue pas de son propre fond : la
corrélation de repos y est déjà élevée, donc la normalisation z ne fait plus émerger la réponse.

Ce projet en a **deux mesures**, sur une seule personne dont l'alpha est à 10,5 Hz :

- **12 Hz — à 1,5 Hz du pic — ÉCHOUE.** Séparabilité 0,3–0,5 contre 2–6 pour les autres cibles.
- **8,571 Hz — à 1,93 Hz du pic — MARCHE.** C'est une des trois fréquences validées casque.

Ces deux points **encadrent** la garde à respecter : au moins 1,5 Hz, au plus 1,93 Hz. La
conception retient **1,9 Hz**, la plus grande valeur compatible avec les deux observations.

⚠️ Réserve à garder en tête : n = 1 personne, et l'échec à 12 Hz est confirmé sur une seule séance.
La garde de 1,9 Hz est **la meilleure valeur compatible avec ce qu'on a mesuré**, pas une constante
établie. Elle vit dans une seule constante nommée, faite pour être révisée quand on aura des
mesures sur plusieurs personnes.

**Conséquence pour une promotion d'étudiants** : le trio actuel est accordé à un alpha de 10,5 Hz.
Livré tel quel à une classe, il pose une cible à 8,571 Hz sur le pic de tout étudiant dont l'alpha
est autour de 8,5–9,5 Hz — soit, autour de la moyenne de population, une fraction loin d'être
négligeable. C'est précisément l'erreur que `CLAUDE.md` interdit : généraliser depuis un échantillon
de 1.

## 4. Ce qui s'ajoute au contrat

Deux champs sur `Param`, dont **un existe déjà** :

```python
proposes: str = ""              # DÉJÀ LÀ, jamais utilisé. `refresh_hz` portera proposes="freqs"
affecte_decodage: bool = True   # NOUVEAU. False => changer ce réglage ne relance pas le repos
```

Et une contrainte nommée de plus sur `freqs` : **`divise_le_refresh`**.

Aucune chirurgie n'est nécessaire pour la contrainte : `_check_constraints(param, values)` reçoit
**déjà** tous les réglages du mode, et son docstring annonce explicitement que c'est pour ce
chantier.

`ModeRuntime` / le moteur : `set_params` ne relance chauffe et repos que si un réglage dont
`affecte_decodage` est vrai a réellement changé de valeur.

## 5. Les deux nouveaux réglages du mode SSVEP

| Clé | Type | Défaut | `affecte_decodage` | Rôle |
|---|---|---|---|---|
| `refresh_hz` | float | 60,0 | **False** | rafraîchissement de l'écran **qui affiche les cibles** — pas celui de la console. Porte `proposes="freqs"` |
| `alpha_hz` | float | 9,6 | **False** | pic alpha de la personne ; la proposition s'en écarte |

Le défaut d'`alpha_hz` est la **moyenne de population**, délibérément pas le 10,5 Hz du
développeur. `ALPHA_PEAK_HZ = 10.5` reste dans `config.py` — il n'a qu'un seul consommateur,
`research/app.py:293` — mais gagne un commentaire disant que c'est **une mesure personnelle, pas
une constante universelle**.

L'aide du champ `alpha_hz` renvoie à `python src/research/alpha_check.py`, qui existe déjà et
permet à l'étudiant de mesurer le sien.

## 6. La règle de proposition

Une fonction pure, `propose_frequencies(refresh, n, alpha)`, placée dans `core/config.py` à côté
d'`available_frequencies()`. Elle rend `(fréquences, avertissement)`.

**Filtres durs**, tous justifiés par de la physique ou de la mesure :

1. **diviseur entier du rafraîchissement** — sinon l'affichage saute des cycles ;
2. **dans `BANDPASS` (5–40 Hz)** — hors de là, le filtre d'acquisition supprime le signal ;
3. **à au moins `ALPHA_GARDE_HZ = 1,9` du pic alpha** — cf. §3 ;
4. **écart d'au moins `1/WINDOW_S` (0,67 Hz) entre cibles retenues** — la résolution d'une fenêtre
   de 1,5 s ; deux cibles plus proches ne sont pas séparables, quelle que soit la qualité du signal.

**Plage confortable** : `CONFORT_HZ = (8.0, 20.0)`. En dessous, le scintillement est pénible et la
réponse chevauche le thêta ; au-dessus, l'amplitude SSVEP décroît nettement. C'est le seul choix de
la règle qui ne s'adosse à aucune mesure de ce projet — il vient de la pratique courante du SSVEP,
et il est isolé dans une constante nommée pour être révisé.

**Sélection** : parmi les candidats, retenir les `n` qui **maximisent le plus petit écart entre
deux cibles**. La séparabilité est la seule propriété qu'on puisse affirmer depuis la résolution
fréquentielle, sans rien supposer d'autre.

**À égalité**, on retient le jeu dont les fréquences sont les plus basses (ordre lexicographique
croissant). Ce départage n'a rien de profond — il est là pour que la fonction soit **déterministe**,
condition sans laquelle ni le test de non-régression ni le rapport d'un étudiant ne veulent dire
quoi que ce soit.

**Élargissement** : si `n` ne tient pas dans la plage confortable, refaire la sélection sur toute
la bande passante et **rendre un avertissement nommant les fréquences hors plage**. Si `n` ne tient
toujours pas, ne rien rendre et **dire le maximum atteignable**.

### La règle régénère le trio validé casque

Avec `ALPHA_GARDE_HZ = 1,9` (dérivée des mesures) et `CONFORT_HZ = (8, 20)` (dérivée de la
pratique), à 60 Hz et pour l'alpha du développeur :

```
alpha = 10,5 Hz, n = 3  ->  8,571 · 15 · 20 Hz
trio validé casque      ->  8,571 · 15 · 20 Hz          IDENTIQUE
```

La règle n'a pas été ajustée pour ce résultat : les deux constantes viennent d'ailleurs, et le trio
en tombe. C'est le meilleur argument dont on dispose que la règle n'est pas arbitraire.

### Comportement vérifié

À 60 Hz :

| alpha | n=2 | n=3 | n=4 |
|---|---|---|---|
| 10,5 (dév.) | 8,571 · 20 | 8,571 · 15 · 20 | 5 · 15 · 20 · 30 ⚠️ |
| 9,6 (moyenne) | 12 · 20 | 12 · 15 · 20 | 5 · 12 · 20 · 30 ⚠️ |
| 8,5 (alpha bas) | 12 · 20 | 12 · 15 · 20 | 5 · 12 · 20 · 30 ⚠️ |

⚠️ = avertissement « hors de la plage confortable 8–20 Hz : 5, 30 — scintillement plus pénible,
réponse plus bruitée ».

**Un écran 60 Hz plafonne à 3 cibles confortables.** C'est une contrainte physique, pas une
limitation du produit, et elle mérite d'être enseignée : à 144 Hz, quatre cibles tiennent **sans
avertissement** (12 · 14,4 · 16 · 18 Hz).

`choose_frequencies` et la table `COMMANDS` **ne bougent pas** : neuf appelants en dépendent, dont
`ssvep_stimulus.py` et le défaut de `modes/ssvep.py`. La nouvelle fonction vit à côté.

## 7. L'interface

Dans le formulaire de réglages, un bouton **« Proposer »** à côté du champ des fréquences. Il
apparaît parce que le contrat déclare `proposes` — **jamais** parce que le code d'affichage
connaîtrait le SSVEP.

`refresh_hz` est **pré-rempli depuis l'écran réel** via `QScreen.refreshRate()`, et reste
corrigeable : l'écran de la console n'est pas forcément celui du stimulus (Unity sur un second
écran, ou sur une autre machine).

Le bouton **remplit le champ, il n'applique pas.** L'étudiant voit ce qu'on lui propose, puis
clique « Appliquer » comme pour n'importe quel réglage. L'avertissement éventuel s'affiche à côté.

La console **ne calcule rien** : elle soumet une commande `propose_params(id, key)` dont l'accusé
porte la valeur proposée et l'avertissement. C'est la règle de conception du chantier 1, inchangée —
aucune logique dans la console que le moteur ne possède déjà.

Deux points que la commande doit trancher explicitement, sans quoi l'implémentation devinerait :

- **Le nombre de cibles demandé** est la longueur de la liste actuellement dans le champ. Si ce
  champ est vide ou illisible, c'est la longueur du **défaut du contrat** qui sert — jamais un
  nombre inventé par l'interface.
- **Un `key` qui ne porte pas de `proposes`** (ou un mode sans ce réglage) est **refusé avec sa
  raison**, comme n'importe quelle commande invalide. Le bouton n'existe pas dans ce cas, mais la
  commande reste atteignable par un client LSL : elle ne doit pas rendre une valeur au hasard.

## 8. Le refus qui enseigne

C'est la moitié qui ferme réellement le trou. Une fréquence qui ne divise pas le rafraîchissement
déclaré est refusée, avec sa raison et les valeurs utilisables les plus proches :

> « Fréquences des cibles » : 17 Hz n'est pas un diviseur entier de 60 Hz — l'affichage sauterait
> des cycles et le décodeur corrélerait contre une sinusoïde que personne n'affiche. Les plus
> proches sont 20 et 15 Hz.

Même forme que les refus existants (« hors bande passante », « cibles trop proches »), et même
chemin : validé par le moteur à la soumission, affiché tel quel par la console.

Ce refus **n'évoque pas l'alpha** : une cible proche du pic alpha reste décodable, seulement moins
bien, et le pic déclaré n'est peut-être pas le vrai. On refuse ce qui est physiquement impossible,
on propose ce qui est prudent.

## 9. Ce qui ne change pas

**Les fréquences par défaut restent 15 · 20 · 8,571 Hz.** Elles sont validées casque ; la
proposition est une **action que l'étudiant déclenche**, pas un recalcul silencieux au démarrage.
Aucune régression possible sur ce qui marche aujourd'hui.

Le contrat public des flux ne bouge pas : mêmes noms de flux, mêmes voies, mêmes unités. Changer
les fréquences recrée `decoded_ssvep` comme aujourd'hui.

## 10. Périmètre

**Dedans** : les deux champs de contrat (`proposes` utilisé, `affecte_decodage` ajouté) ; la
contrainte `divise_le_refresh` ; `propose_frequencies()` et ses constantes ; les réglages
`refresh_hz` et `alpha_hz` du mode SSVEP ; la commande `propose_params` ; le bouton « Proposer » et
le pré-remplissage du rafraîchissement ; le repos non relancé pour un réglage sans effet sur le
décodage ; mise à jour de `SPEC.md` et du `README`.

**Dehors** :

- **la mesure automatique du pic alpha par le moteur** — c'est la bonne réponse scientifique, et
  elle supprimerait toute saisie, mais elle demande une estimation du pic sur les voies occipitales,
  une refonte de l'ordre chauffe / proposition / repos, et une validation casque. Chantier à part ;
- **les « réglages des autres modes »** que `SPEC.md` §14 rattache au chantier 2 : déclarer des
  réglages pour des modes que le moteur ne sait pas faire tourner, c'est livrer à moitié ;
- la proposition de fréquences pour le c-VEP.

## 11. Tests (aucun casque)

- `propose_frequencies` : pour les rafraîchissements 60, 75, 120, 144 et 240 Hz et `n` de 2 à 8 —
  **toute** valeur rendue divise le rafraîchissement, tient dans la bande passante, respecte la
  garde alpha et l'écart minimal. Vérifié sur tout le domaine, pas sur un échantillon.
- **Le test de non-régression qui compte** : à 60 Hz, alpha 10,5, n = 3, la fonction rend exactement
  les trois fréquences validées casque.
- L'élargissement : un cas qui déborde de la plage confortable rend bien un avertissement nommant
  les fréquences en cause ; un cas impossible ne rend rien et nomme le maximum atteignable.
- Le refus de 17 Hz **à travers le vrai moteur**, comme les refus existants du smoke de la console.
- `affecte_decodage` : changer `refresh_hz` seul ne relance pas le repos ; changer `freqs` le
  relance. Vérifié sur le moteur, pas sur une maquette.
- Console : le bouton remplit le champ, et la valeur obtenue est ensuite **acceptée par le moteur** —
  c'est ce qui prouve que la proposition et la validation sont d'accord.

## 12. Risques

| Risque | Parade |
|---|---|
| La garde de 1,9 Hz repose sur n = 1 personne | Constante nommée, documentée comme révisable ; la garde ne **refuse** rien, elle ne fait qu'orienter la proposition |
| La plage confortable 8–20 Hz ne s'adosse à aucune mesure de ce projet | Constante nommée et isolée ; l'élargissement automatique empêche qu'elle bloque quoi que ce soit |
| `QScreen.refreshRate()` peut mentir (écran secondaire, machine distante) | La valeur est **proposée**, jamais imposée : le champ reste éditable, et c'est le moteur qui valide contre ce que l'étudiant a déclaré |
| Un étudiant règle un rafraîchissement faux et ses fréquences deviennent « invalides » à tort | Le message de refus nomme le rafraîchissement déclaré, ce qui rend l'erreur visible : « n'est pas un diviseur entier de **60 Hz** » |
