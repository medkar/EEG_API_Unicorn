# Charte de rédaction

Pour qui écrit dans ce dépôt : les textes affichés, les commentaires du code et les messages des
autotests. En français, comme les textes qu'elle règle.

**Le public : des élèves ingénieurs qui découvrent l'EEG et les interfaces cerveau-machine.** Ils
savent ce qu'est un pourcentage, une fréquence, un filtre, un signal bruité. Ils ne savent pas
forcément ce qu'est une validation croisée, une p-value, un CSP ou un plancher de corrélation.
L'outil doit les aider à prendre le casque en main : chaque texte répond à « qu'est-ce que je
fais ? » et « est-ce que c'est bon ? ».

## 1. Les textes affichés (`src/core/langues/fr/*.json`)

- **Dire quoi faire, et si c'est bon.** Une idée par phrase, des phrases courtes. Tutoiement.
- **Un chiffre a toujours son point de comparaison**, en mots : « 7 essais sur 10 reconnus (au
  hasard : 5 sur 10) ».
- **Pas d'histoire du projet** : ni dates, ni « constaté au casque le… », ni « la séance de
  référence du projet ». Un repère chiffré reste utile s'il est dit simplement : « sur ce casque,
  chez une personne, on a obtenu 63 % ».
- **Pas de nom de fichier ni de commande** dans la console (`src/…`, `--retour`) : l'élève ne
  tape rien. Exception : les noms de flux (`decoded_mi`), que son application utilise.
- **Le vocabulaire technique, au minimum.** On garde un terme que l'élève retrouvera ailleurs, et on
  l'explique en quelques mots la première fois (bulle ⓘ). On en remplace d'autres :

  | Au lieu de | Écrire |
  |---|---|
  | validation croisée | « mesuré sur des essais que le modèle n'a pas vus » |
  | test binomial exact, p-value | « ce score peut venir du hasard » ; la valeur `p` reste dans « Détails » |
  | taux d'émission | « le modèle a répondu dans N essais sur M » |
  | IC95, intervalle de Wilson | « fourchette probable » |
  | plancher, z, σ du repos | « niveau de bruit au repos », « écart au bruit » |
  | classe (pour le MI) | « tâche » |
  | kappa, McNemar, Ledoit-Wolf, covariance | jamais à l'écran |

  On garde, expliqués au besoin : alpha, SSVEP, c-VEP, P300, ErrP, Motor Imagery, électrode,
  filtre, bande (Hz), fenêtre, vote, modèle, CSP, FBCSP, LDA.
- **Les mots-verdicts en majuscules restent** (EXCELLENT, FAIBLE, ARRÊTE ICI…) : ce sont eux qu'on
  voit en premier.
- **Une bulle ⓘ : deux à quatre phrases** — à quoi sert le réglage, la valeur conseillée, quand la
  changer.
- **« Détails » peut garder la technique** (`p`, fourchette, comptes par tâche), avec une phrase qui
  dit ce qu'elle veut dire.

## 2. Les commentaires et les docstrings

- **Au présent : ce que fait le code, et pourquoi** (le principe). Le lecteur découvre le fichier.
- **Pas d'histoire** : ni dates, ni identifiants de revue (« F1-I3 », « C-M7 »), ni « une première
  version… », « avant le correctif… », « trouvé au casque le… ». L'histoire vit dans git et dans
  `docs/recette.md`.
- **Garder le « pourquoi » qui protège d'une panne silencieuse**, réécrit comme une règle :
  « Horodater APRÈS l'affichage de l'image : avant, la phase serait décalée d'une image, sans
  aucune erreur. »
- **⚠️ et 🔴 seulement pour une règle qui casse en silence**, jamais pour une anecdote.
- **Court.** Un paragraphe qui raconte trois versions successives devient une phrase.
- **On ne touche jamais au code** en réécrivant un commentaire.

## 3. Les messages des autotests

- **Au présent, ce qui est vérifié** ; la valeur observée entre parenthèses, pour le diagnostic.
- **Pas d'histoire** (« 4 avant le correctif », « vu rouge le … »).
- **On ne touche jamais à la condition testée**, seulement au texte du message.

## 4. Exemples

**Texte affiché — un résultat d'entraînement**

> Avant : « 55 % de classes justes (hasard 50 %) sur 20 essais — il faut au moins 75 % pour écarter
> le hasard »
>
> Après : « 55 % de tâches reconnues sur 20 essais (au hasard : 50 %) — il faut au moins 75 % pour
> faire mieux que le hasard »

**Texte affiché — un verdict non concluant**

> Avant : « NON SIGNIFICATIF (test binomial exact sur 20 essais, p = 0,252) : le hasard fait aussi
> bien. »
>
> Après : « NON SIGNIFICATIF — avec 20 essais, ce score peut venir du hasard (p = 0,252). »

**Bulle ⓘ**

> Avant : « Le classifieur qui trace la frontière entre les tâches estime la dispersion de leurs
> caractéristiques sur les essais d'entraînement. Avec peu d'essais pour beaucoup de
> caractéristiques […] cette estimation est bruitée ; la régularisation la stabilise. […]
> (src/research/mi_compare.py). »
>
> Après : « Une version plus robuste du dernier étage du modèle, utile quand il y a peu d'essais
> pour beaucoup d'informations à combiner (FBCSP, 4 ou 5 tâches, séance courte). Sur ce casque,
> aucune différence n'a été mesurée. Pour savoir si elle t'aide, compare deux entraînements faits
> dans la même séance. »

**Commentaire**

> Avant : « ⚠️ Ces seuils sont RELATIFS AU HASARD depuis le 2026-10-15, où le nombre de tâches est
> devenu un réglage (2 à 5) : 45 % est « utilisable » à 3 classes, SOUS le hasard à 2. »
>
> Après : « Les seuils dépendent du hasard, donc du nombre de tâches : 45 % est un bon score à 3
> tâches (hasard 33 %), mais il est sous le hasard à 2 (50 %). »

**Message d'autotest**

> Avant : « aucune page de mode n'exige plus de largeur que l'accueil (la plus exigeante : 1344 px,
> accueil 1344 px ; console 1344 px, 1 538 avant le correctif) »
>
> Après : « aucune page de mode n'exige plus de largeur que l'accueil (la plus large : 1344 px ;
> accueil : 1344 px) »
