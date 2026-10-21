# Le rafraîchissement se règle, et l'écran du poste suit

**Statut** : conception validée en conversation le 2026-10-21, à relire avant le plan. Aucun code
écrit.
**Origine** : nouveau poste, écran principal à 165 Hz. Le but de l'API est de décoder pour une
application externe, dont la cadence d'affichage n'est pas forcément celle de l'écran de ce poste.

---

## 1. Le problème

**c-VEP.** Un bit du code dure une image. La cadence du code est donc celle de l'écran qui
l'affiche, et le modèle n'apprend que cette cadence-là : le moteur refuse tout marqueur de cycle
qui s'écarte de plus de 1 Hz du rafraîchissement du modèle. Aujourd'hui, la fenêtre mesure l'écran
et impose ce qu'elle trouve. Sur ce poste, tout modèle entraîné le serait à 165 Hz, et ne servirait
à rien pour une application qui affiche à 60 Hz. Rien ne permet de choisir.

**SSVEP.** Le rafraîchissement est déjà un réglage de « 1. Régler », qui sert à calculer les
fréquences. Mais la fenêtre de « Tester » mesure l'écran et refuse un jeu de fréquences prévu pour
un autre rafraîchissement : réglé à 60 Hz, le test ne se lance pas sur un écran à 165 Hz.

**Pourquoi la fenêtre ne peut pas simplement ralentir.** À 60 Hz, une image dure 16,7 ms, soit
2,75 images d'un écran à 165 Hz. Tenir les bits du code tantôt 2 images, tantôt 3, donne des bits
de 12 ou 18 ms : le code affiché est déformé, et le modèle apprendrait ce code déformé. C'est la
raison pour laquelle le SSVEP refuse déjà une fréquence qu'il ne peut pas afficher, au lieu de
l'arrondir.

**La solution.** Un écran qui tient 165 Hz propose presque toujours 60 Hz. La fenêtre demande à
Windows de passer l'écran au rafraîchissement voulu pendant qu'elle est ouverte, et le rétablit en
se fermant. Chaque bit reste exactement une image : la boucle d'images des fenêtres et leurs
autotests au pixel près ne changent pas. L'écran principal de ce poste propose 59, 60, 120, 144 et
165 Hz à sa définition actuelle.

## 2. Périmètre

Dedans :

- le c-VEP : un réglage du rafraîchissement dans « 2. Entraîner », porté par le modèle ;
- le nom des fichiers de modèle c-VEP, et leur description, qui portent ce rafraîchissement ;
- le passage de l'écran au rafraîchissement voulu, pour les fenêtres du c-VEP (Entraîner, Tester,
  Tester librement) et du SSVEP (Tester, Tester librement) ;
- les textes en français et en anglais, les autotests, la documentation et la QA.

Dehors :

- un titre de modèle pour le SSVEP : il n'a pas de modèle, le réglage de sa page suffit ;
- les fenêtres du P300, de l'ErrP et du MI : leur décodage ne dépend pas du rafraîchissement ;
- choisir l'écran où s'ouvre une fenêtre : c'est toujours l'écran principal ;
- le changement de mode hors Windows : la fenêtre y refuse si l'écran ne tient pas le réglage ;
- le contrat réseau : `decoded_cvep` publie déjà `refresh` dans ses métadonnées, c'est celui du
  modèle.

## 3. c-VEP : le réglage vit dans « 2. Entraîner »

C'est la règle du projet pour tout ce que le modèle apprend, comme la bande (QA 1.14) : un réglage
de cette nature dans « 1. Régler » ferait décoder un modèle sur autre chose que ce qu'il a appris.
Elle évite aussi une impasse : avec le réglage dans « Régler » et un refus des modèles qui ne
correspondent pas, on ne pourrait jamais appliquer 165 Hz tant que le dernier modèle est à 60 Hz.

- **Le réglage.** `refresh_hz` rejoint les `params` de la calibration c-VEP, à côté de la bande.
  Libellé « Rafraîchissement de l'écran du stimulus », en Hz, défaut 60, bornes 30 à 480. Il part
  avec « Commencer », sans « Appliquer » ; une valeur hors bornes est refusée tout de suite, avant
  le contrôle de liaison.
- **Son aide, deux à quatre phrases.** Le rafraîchissement auquel ton application affichera le
  code. Le modèle ne marchera qu'à ce rafraîchissement. Si l'écran de ce poste n'y est pas, il y
  passe le temps de l'entraînement.
- **Vers la fenêtre.** La console passe la valeur à la fenêtre d'entraînement (cf. § 6).
- **Côté moteur.** La calibration reçoit `refresh_hz` avec ses autres réglages. Elle refuse un
  marqueur de cycle dont le `refresh` s'écarte de plus de 1 Hz de ce réglage, en nommant les deux
  nombres. La fenêtre garantit l'écran ; un écart veut donc dire une fenêtre lancée à la main à un
  autre rafraîchissement, et la séance n'entraînerait pas ce qui était demandé.
- **Le modèle le porte.** Les deux décodeurs enregistrent déjà `refresh` dans leur fichier ; c'est
  la valeur des marqueurs, donc celle du réglage.
- **La durée annoncée le suit.** Le protocole compte des images : à 120 Hz il dure deux fois moins
  qu'à 60 Hz. La durée de l'entraînement suit le réglage, celle du test le modèle.
- **Les bornes.** De 30 à 480 Hz : sous 30 Hz, un cycle du code dépasserait la plus longue époque
  que couvre le tampon du moteur.
- **Le nom des fichiers.** Les trois fichiers d'un entraînement finissent par le rafraîchissement,
  écrit sans zéro inutile : `cvep_model_20261021-153000_60Hz.npz`,
  `cvep_rcca_model_20261021-153000_60Hz.npz`, `cvep_calib_20261021-153000_n108_60Hz.npz`. Les
  motifs de découverte (`cvep_model*.npz`, `cvep_rcca_model*.npz`) restent valides, et rien ne lit
  l'horodatage dans le nom. La liste de la console montre le nom du fichier : c'est le titre du
  modèle.
- **La description.** `cvep_models.decrire` gagne une clé `refresh`.
- **Relire sans recharger.** `cvep_models.refresh_de(chemin)` lit le seul champ `refresh` du
  fichier, sans `allow_pickle` et sans ré-ajuster le rCCA. Il rend `None` pour un fichier
  illisible, et ne lève jamais.

## 4. c-VEP : Tester et Tester librement suivent le modèle

- La console lit le rafraîchissement du modèle choisi avec `refresh_de`, et le passe à la fenêtre.
  Pour « Tester », c'est le modèle du test ; pour « Tester librement », celui du mode.
- Le modèle et la fenêtre sont donc toujours d'accord : aucun refus nouveau côté moteur. Le refus
  existant d'un marqueur à plus de 1 Hz du modèle reste, pour une fenêtre lancée à la main.
- Le décodage pour une application externe ne change pas : l'application doit afficher au
  rafraîchissement du modèle, qu'elle lit dans les métadonnées de `decoded_cvep` ou dans le nom du
  fichier.

## 5. SSVEP : la fenêtre suit le réglage de « 1. Régler »

- La console passe le `refresh_hz` du mode à la fenêtre de « Tester » et de « Tester librement ».
  Avec des cibles physiques, les deux tests sont déjà désactivés : la question ne se pose pas.
- La fenêtre vérifie ses fréquences contre ce rafraîchissement, une fois l'écran passé.
- L'aide du réglage ajoute une phrase : l'écran de ce poste y passe le temps d'un test.

## 6. Le passage de l'écran : `src/stimulus/ecran.py`

Une nouvelle option des fenêtres SSVEP et c-VEP, `--ecran-hz H`, dit « affiche à H Hz ». Elle se
distingue de `--refresh`, qui garde son sens : déclarer un rafraîchissement sans le mesurer, pour
le développement et les autotests. Les deux ensemble sont refusés par l'analyseur d'arguments.

**L'algorithme, avant d'ouvrir quoi que ce soit :**

1. Lire le mode actuel de l'écran principal. S'il est à 1 Hz près de H, rien à faire.
2. Sinon, lister les rafraîchissements que l'écran propose à sa définition actuelle, et prendre le
   plus proche de H à 1 Hz près. S'il n'y en a aucun, refuser, avec H et la liste proposée.
3. Passer l'écran à ce rafraîchissement, de façon temporaire, en ne changeant que la fréquence.

**Puis, la fenêtre ouverte :**

4. Mesurer le rafraîchissement, comme aujourd'hui. S'il s'écarte de H de plus de 1 Hz, refuser,
   fermer et rétablir. Sinon, continuer avec H : c'est H que portent les marqueurs.
5. À la fermeture, quelle qu'en soit la cause, rétablir le mode d'origine. Une fenêtre TUÉE ne
   passe pas par là, et Windows ne rétablit pas toujours seul un mode temporaire : la console tend
   donc un filet. Après chaque fenêtre, si l'écran n'est plus au rafraîchissement enregistré dans
   Windows, elle l'y remet ; sans écart, elle ne fait rien.

La mesure de l'étape 4 prend l'intervalle MÉDIAN entre deux images, sans l'arrondir : une image
sautée juste après le changement de mode ne doit pas faire croire à un écran plus lent.

**Hors Windows**, les étapes 1 à 3 sont sautées, et l'étape 4 refuse si l'écran ne tient pas H.

**Le refus** se fait avant la création du flux de marqueurs, pour ne laisser aucun émetteur
fantôme. La fenêtre sort en erreur, et la console affiche sa cause comme pour toute fenêtre qui
s'arrête anormalement. Le texte vient du catalogue de `fenetres.json`.

**Testable sans écran.** La décision est une fonction pure, qui reçoit les appels système en
paramètres : lire le mode, lister les modes, basculer, rétablir, mesurer. L'autotest lui passe un
faux Windows. Seule une couche mince appelle `user32` par `ctypes`.

**Le registre des fenêtres** déclare lesquelles acceptent `--ecran-hz`, comme il déclare déjà les
fréquences et les longueurs. La console demande, elle ne sait pas. Son autotest vérifie que
l'option existe dans l'analyseur des deux fenêtres.

## 7. Les textes

Français et anglais, dans les catalogues existants :

- libellé et aide du réglage de la calibration c-VEP ;
- refus de la calibration pour un marqueur à un autre rafraîchissement ;
- refus de la fenêtre : écran qui ne propose pas H, avec la liste ; mesure qui ne confirme pas H ;
- une ligne de la fenêtre quand l'écran change : « Écran passé à 60 Hz le temps de la séance. » ;
- la phrase ajoutée à l'aide du rafraîchissement du SSVEP.

## 8. Les tests

Tous dans les autotests existants, plus celui du nouveau module :

- `stimulus/ecran.py` : écran déjà au bon rafraîchissement, aucun changement ; changement vers le
  mode le plus proche ; 59 choisi pour 59,94 ; refus quand le mode n'est pas proposé, liste
  comprise ; refus quand la mesure contredit, avec rétablissement ; rétablissement sur chaque
  chemin de sortie ; chemin hors Windows.
- `stimulus/registry.py` : `--ecran-hz` existe dans les deux analyseurs ; l'option rend `()` pour
  une valeur absente ou non positive.
- `stimulus/cvep.py --smoke` et `stimulus/ssvep.py --smoke` : avec un faux écran, un refus arrive
  avant l'ouverture du flux de marqueurs ; un passage réussi publie H dans les marqueurs.
- `core/modes/cvep_calib.py` : le réglage existe avec son défaut et ses bornes ; un marqueur à un
  autre rafraîchissement est refusé en nommant les deux ; les trois noms de fichiers portent le
  suffixe.
- `core/cvep_models.py` : `refresh_de` lit sans ré-ajuster et rend `None` sur un fichier
  illisible ; `decrire` porte `refresh`.
- `console/app.py --smoke` : la ligne de commande d'« Entraîner » c-VEP porte le réglage ; celles
  de « Tester » et « Tester librement » c-VEP portent le rafraîchissement du modèle ; celles du
  SSVEP portent le réglage du mode ; « Avant de commencer » du c-VEP montre le champ ; « 1. Régler »
  du c-VEP ne le montre pas.
- `[smoke-textes]` pour les nouvelles clés.
- Sur ce poste, au point de QA : entraînement c-VEP à 60 Hz sur l'écran à 165 Hz, l'écran passe à
  60 puis revient à 165 ; même chose pour le test SSVEP ; fenêtre tuée, mode rétabli.

## 9. La documentation

- `CLAUDE.md` : une entrée datée, et le piège matériel de l'écran principal qui change.
- `README.md` : entraîner au rafraîchissement de son application, et le lire dans les métadonnées
  de `decoded_cvep`.
- `docs/qa.md` : le point 1.14 nomme le nouveau réglage du c-VEP ; un point nouveau au bloc 1
  pour le passage de l'écran.
- `docs/recette.md` : le pourquoi, avec le calcul des 2,75 images.

## 10. Risques

1. **Le rétablissement après un plantage** repose sur Windows. S'il échoue, l'écran reste à 60 Hz
   jusqu'à ce qu'on le remette à la main. À vérifier sur ce poste avant de livrer.
2. **L'écran principal et l'écran de pygame** doivent être le même. Sur un poste à trois écrans,
   c'est à vérifier.
3. **Le changement de mode prend une à deux secondes**, pendant la chauffe du moteur. Une fenêtre
   plus lente à démarrer reste dans le bon sens : ses premiers blocs n'en tombent que plus
   sûrement après la chauffe.
4. **Un écran à rafraîchissement variable**, G-Sync ou FreeSync, peut fausser la mesure. La
   mesure de l'étape 4 l'attrape et refuse, plutôt que de laisser dériver la phase.
