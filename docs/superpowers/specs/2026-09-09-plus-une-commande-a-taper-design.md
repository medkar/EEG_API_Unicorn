# Plus une seule commande à taper — conception

**Date** : 2026-09-09 · **État** : validé, prêt pour le plan d'implémentation

À la fin de ce chantier, **le seul programme lançable de `src/` est la console**. Tout l'usage réel
— contrôler le casque, mesurer, calibrer, décoder, regarder le flux sortant, enregistrer une séance
— se fait aux boutons. Et la règle cesse d'être une promesse : un test la vérifie.

---

## 1. Pourquoi ce chantier existe, et pourquoi il ne ressemble pas aux précédents

L'utilisateur a demandé **cinq fois**, entre juillet et septembre 2026, que tout se pilote depuis
l'interface. Cinq fois j'ai traité la demande comme **une fonctionnalité à ajouter** : j'ai ajouté
un bouton, proposé un chantier, et le chantier suivant est reparti sans la règle. Un nouveau trou
apparaissait, et on recommençait.

La cause est identifiable et réparable : **rien dans le dépôt n'écrit cette règle.** Les specs
d'ici portent une section « contraintes globales » — frontières entre paquets, langue, aucun test
n'écrit dans `data/` — et celle-ci n'y a jamais figuré. Chaque chantier la redécouvrait par
l'échec.

Ce chantier fait donc **deux** choses, et la seconde compte autant que la première :

1. boucher les cinq trous mesurés ;
2. **rendre la règle vérifiable**, à la manière du projet — la frontière entre paquets n'est pas
   tenue par la discipline, elle est tenue par un scanner qui rougit.

## 2. Le périmètre, donné mot pour mot par l'utilisateur

> « je parle ici de la partie **Utilisation réelle**, donc tout ce qui concerne **l'acquisition, le
> décodage et le flux récupérable à l'extérieur** pour l'application que développera l'utilisateur »

**DEDANS** : contrôle du casque, mesures, calibration, choix du modèle, stimulus, décodage,
réglages, travailler sans casque, journal de séance, voir le flux sortant.

**DEHORS**, et ce n'est pas une échappatoire :

- les **autotests** (`--smoke`, autotests de module) — ils s'adressent au développeur, pas à
  l'utilisateur ;
- **`server.py --mode X`** — le moteur **sans écran**. C'est son contrat public : il doit tourner
  sur une machine sans interface. Ce n'est pas un trou, c'est la raison d'être du produit.

## 3. Les cinq trous, mesurés

Inventaire des 43 commandes documentées dans `CLAUDE.md`, filtré par le périmètre ci-dessus. 25
sont des autotests. Restent cinq commandes d'usage réel :

| commande | ce qu'elle fait | pourquoi c'est un trou |
|---|---|---|
| `python src/research/alpha_check.py` | Effet de Berger : l'alpha monte-t-il à la fermeture des yeux ? | **Étape 1 de toute séance**, et barrière du niveau 2 de la recette. Aucun équivalent : la page de contact montre le σ par voie, c'est-à-dire le CONTACT, pas l'alpha |
| `--synthetic` | Travailler sans casque | Un drapeau à taper pour une décision qui devrait être un choix |
| `python src/stimulus/cvep.py --log seance.jsonl` | La vérité-terrain d'une séance c-VEP | La recette 2.9 dit qu'une séance sans ce fichier **ne se dépouille pas**. La console lance déjà cette fenêtre mais ne peut pas lui passer l'option |
| `python -u examples/receiver.py --stream …` | Voir le **flux sortant** | C'est le cœur du produit, et rien dans l'app ne le montre |
| `python src/research/ssvep_guided.py` | Le taux SSVEP **sur cette personne-là** | Seul chemin vers un chiffre comparable aux références (100 % de justesse à l'émission, 44 % d'émission, 2026-07-27) |

## 4. Trois faits de terrain qui contraignent le dessin

- **`alpha_check.py` ouvre le casque lui-même.** Il ne peut donc pas cohabiter avec la console —
  l'Unicorn n'accepte qu'une connexion. Sa mesure doit **monter dans le moteur**, comme les
  calibrations l'ont fait au chantier précédent.
- **`ssvep_guided.py` est un monolithe** : stimulus, acquisition et analyse dans un seul
  programme. Le rendre pilotable veut dire le couper en trois selon l'architecture du projet.
  C'est la plus grosse des cinq, à elle seule près de la moitié du chantier.
- **Les deux mesures ont la même forme qu'une calibration** : un protocole minuté, joué par le
  moteur, qui produit un **verdict** au lieu d'un modèle.

## 5. `MesureRuntime` — un protocole qui rend un verdict

Nouveau module `core/modes/mesure.py`. Il partage avec `CalibrationRuntime` le **contrat public
exact** — `PHASES`, `terminee`, `resultat`, `probleme`, `cancel()`, `duree_estimee_s()`, et la forme
de `snapshot()` — pour que la page générique de la console l'affiche **sans une ligne de plus**.
C'est le même geste qui a fait tenir les quatre calibrations sur une seule page.

Ce qui diffère d'une calibration : il n'écrit **aucun modèle**, donc il ne passe pas par le dossier
candidat ni par `save_calibration`. Son résultat est un verdict lu à l'écran, et rien sur le disque.

⚠️ **Le moteur tient AU PLUS UNE activité à la fois** — une calibration OU une mesure, jamais les
deux. Même raison que le refus livré au chantier précédent : il n'y a qu'un casque, et deux
protocoles minutés se voleraient les fenêtres de signal. Le refus doit venir de `submit`, **dans
les deux sens**, comme celui du vol de marqueurs.

### 5.1 Contrôle alpha — `core/modes/alpha.py`

Chauffe, puis **8 s yeux ouverts** et **8 s yeux fermés** (les durées de `alpha_check.py`, à
reprendre telles quelles : ce sont celles sous lesquelles le repère « ratio > ~1,5 » a été observé),
séparées par une préparation de 3 s. Résultat : puissance dans chaque condition, **ratio
fermé/ouvert**, **fréquence du pic** entre 6 et 14 Hz, et un verdict.

⚠️ **Il ferme une boucle aujourd'hui manuelle et recopiée à la main.** La recette fait noter le pic
puis le retaper dans « Pic alpha » de la page SSVEP pour cliquer « Proposer ». La page de résultat
proposera de l'appliquer directement. Une valeur recopiée à la main entre deux écrans est
exactement le genre de chose que ce dépôt a déjà vu diverger.

⚠️ **C'est une BARRIÈRE, et la page doit le dire.** Si l'alpha ne monte pas, aucun autre test du
niveau 2 ne veut rien dire : le verdict doit être une phrase qui arrête, pas un chiffre à
interpréter.

### 5.2 Mesure SSVEP — `core/modes/ssvep_mesure.py` + `src/stimulus/ssvep.py`

Une fenêtre de stimulus SSVEP (nouvelle dans `stimulus/`, la moitié rendu de `ssvep_guided.py`) et
une mesure côté moteur. Trois propriétés à ne pas perdre, chacune écrite dans le fichier d'origine
avec sa raison :

1. **Chauffe avant tout** — l'Unicorn sort un offset DC énorme et dérivant après ouverture ;
   mesurer le plancher là-dedans revient à étalonner sur le transitoire d'un filtre.
2. **Essais ENTRELACÉS et tirés au sort** — un bloc contigu par cible rend « quelle cible »
   inséparable de « quand » : la dérive d'impédance et la fatigue se confondent avec l'effet
   cherché. Le c-VEP a déjà payé ce confond 76 % de débit.
3. **Un essai = une décision** — les fenêtres du moteur se chevauchent (1,5 s toutes les 0,2 s) ;
   les compter comme indépendantes gonfle l'effectif d'un facteur ~7 et donne un intervalle de
   confiance faux. On archive UNE fenêtre par essai.

Résultat affiché : **justesse quand le moteur émet** et **taux d'émission**, les deux chiffres des
références du 2026-07-27, avec leur intervalle.

## 6. La source, choisie à l'ouverture

Un écran de départ avant que le moteur n'ouvre quoi que ce soit : **casque Unicorn** ou **board de
test (sans casque)**.

⚠️ **Jamais de repli automatique.** Un basculement silencieux vers le synthétique ferait enregistrer
une séance entière de faux signal en croyant tenir du vrai — et ce dépôt a déjà dû corriger un écran
qui laissait croire qu'un board de test était observé. Si le casque ne s'ouvre pas, on le **dit** et
on repropose le choix. Le bandeau annonce la source en permanence, tant que la console tourne.

## 7. Le flux sortant — « Ce que voit ton application »

Une page qui liste les flux publiés, en laisse choisir un, et montre ses voies et ses valeurs
défiler.

⚠️ **Elle le lit par LSL, comme un client** — pas dans les entrailles du moteur. C'est la version
honnête : si le panneau montre des données, un vrai client en verrait aussi. Lire l'état interne
donnerait un panneau qui marche alors que le réseau est muet, ce qui est précisément la panne qu'on
veut voir.

Elle réutilise l'extrait « Brancher un client » qui existe déjà : le panneau montre le flux, et
l'extrait montre le code qui le lit.

### 7.1 Enregistrer une séance

Un bouton **« Enregistrer cette séance »**. ⚠️ **C'est le MOTEUR qui écrit**, sur commande de la
console (`start_enregistrement` / `stop_enregistrement`), exactement comme `save_calibration` : la
console reste un client qui ne touche jamais au disque.

Le fichier porte un nom horodaté et **ne va pas dans `data/`** — ce sont des verdicts de séance, pas
des enregistrements EEG ni des modèles ; `data/` garde son autorité unique et son gitignore.

## 8. Le journal de la fenêtre

Les pages c-VEP, P300 et ErrP gagnent une case **« Journal de séance »**, **cochée par défaut** : la
recette 2.9 dit noir sur blanc qu'une séance sans elle ne se dépouille pas, et une case décochée par
défaut serait une séance perdue par omission.

La fenêtre choisit elle-même son nom horodaté ; la console affiche où il est. `LanceurFenetre` et
`stimulus/registry.py` gagnent donc la capacité de **passer des options** — aujourd'hui la commande
ne porte que `--calibrer`.

Avec le §7.1 en face, **une séance devient dépouillable sans taper une commande** : la vérité-terrain
d'un côté, les verdicts de l'autre, joints par le même horodatage `local_clock()`.

⚠️ **Le dépouillement lui-même reste DEHORS.** Il n'existe nulle part, pas même en script, et
l'écrire sur des données qu'on n'a pas encore produites reviendrait à le vérifier contre son propre
auteur. Il se fera après la séance, sur de vrais fichiers.

## 9. Ce qui se retire

`src/research/alpha_check.py` et `src/research/ssvep_guided.py` partent dans `archive/` avec leur
`--smoke`, comme les six écrans du chantier précédent : non maintenus, mais lançables, et gardés
comme la référence contre laquelle l'implémentation a été vérifiée. La moitié **analyse hors ligne**
de `ssvep_guided` (permutations, intervalles de Wilson) part avec — elle ne sert qu'à rejouer un
enregistrement archivé avec d'autres réglages, ce qui est du travail de banc d'essai.

⚠️ **`examples/receiver.py` RESTE**, et ce n'est pas une exception à la règle. `docs/markers.md` le
présente comme l'exemple qu'un étudiant copie pour écrire son propre client : c'est du **matériel
pédagogique**, pas un outil du produit. Il sort simplement de la liste des choses qu'il faut taper
pour se servir de l'application.

## 10. La règle, rendue vérifiable

Un test dans `server.py --smoke` inventorie **tout fichier de `src/` portant un
`if __name__ == "__main__"`** et échoue sur tout ce qui n'est ni :

- `src/console/app.py`, la console ;
- une fenêtre de `src/stimulus/` ;
- un module dont le point d'entrée n'est **qu'un autotest** (reconnaissable à ce qu'il appelle
  `_selftest`/`_smoke`, sans autre mode d'exécution).

Le message d'échec porte la règle en toutes lettres, pour que le prochain chantier la lise au lieu
de la redécouvrir : *« un utilisateur ne tape pas de commande ; si cette capacité lui est destinée,
elle doit avoir un chemin dans la console. »*

**Et la contrainte entre dans `CLAUDE.md`**, au même rang que la frontière entre paquets. C'est la
moitié qui manquait aux cinq fois précédentes.

⚠️ **Ce test doit être prouvé par mutation** : on ajoute un faux point d'entrée dans `src/`, il
rougit en nommant le fichier ; on le retire, il repasse. Un test d'inventaire qui compte mal est
muet exactement le jour où il servirait.

## 11. Les tests

Tout headless, sans casque, un autotest par module ; sortie 1 en cas d'échec ; **aucun test n'écrit
dans le vrai `data/`** (garde `empreinte_dossier` — `git status` ne prouve rien, `data/` est
gitignoré).

- `core/modes/mesure.py` — la ligne du temps, l'abandon, la forme du `snapshot`, et le refus
  d'une seconde activité **dans les deux sens**.
- `core/modes/alpha.py` — le ratio calculé sur un signal synthétique dont on connaît la réponse,
  et le verdict qui ARRÊTE quand l'alpha ne monte pas.
- `core/modes/ssvep_mesure.py` — un essai = une décision (l'effectif annoncé est le nombre
  d'essais, jamais celui des fenêtres), et l'entrelacement.
- `src/stimulus/ssvep.py --smoke` — la fenêtre, avec la même sévérité que ses trois sœurs :
  l'horodatage pris **après** `display.flip()`.
- `src/console/app.py --smoke` — l'écran de départ, la page de flux contre un **faux inlet**, la
  case « Journal de séance » qui arrive bien dans la commande lancée, le refus visible.
- `src/core/server.py --smoke` — les deux commandes d'enregistrement, et **le test d'inventaire**.

## 12. Découpage indicatif

L'ordre met la **règle vérifiable en premier** : écrite en dernier, elle constaterait un état déjà
propre et ne prouverait rien. Écrite en premier, elle est **rouge sur les cinq trous** et chaque
tâche la fait verdir d'un cran — c'est le seul ordre où elle démontre qu'elle mord.

1. Le test d'inventaire + la contrainte dans `CLAUDE.md`. **Rouge à la fin de cette tâche**, et
   c'est voulu : il nomme les cinq fichiers à traiter.
2. `MesureRuntime` + le refus d'une seconde activité.
3. Le contrôle alpha, de bout en bout, jusqu'à l'application du pic mesuré au réglage SSVEP.
4. Le choix de la source à l'ouverture.
5. Les options de lancement (`LanceurFenetre`, `registry`) + la case « Journal de séance ».
6. La page « Ce que voit ton application ».
7. L'enregistrement d'une séance, côté moteur puis côté console.
8. La fenêtre `stimulus/ssvep.py`.
9. La mesure SSVEP côté moteur + sa page de résultat.
10. Les retraits vers `archive/`. **Le test de la tâche 1 doit être VERT à la fin.**
11. La documentation.

## 13. Ce qui reste DEHORS

- **La séance casque.** Elle suit, et c'est elle qui vérifiera tout ceci.
- **Le dépouillement automatique** du test 2.9 (§8).
- **Les huit constats parqués** de la revue du chantier précédent, dont deux mordront en séance :
  la console prend `accepted` pour « la séance a démarré » alors que le moteur ne promet qu'une
  mise en file ; et les refus de la grille ne vont encore que dans le terminal. À traiter, mais ce
  sont des défauts du chantier précédent.
- **Toute nouvelle capacité de décodage.** Aucun mode nouveau, aucun seuil rouvert.

## 14. Contraintes qui lient tout le chantier

- `core` n'importe ni `research`, ni `console`, ni `stimulus`, ni pygame, ni Qt. `stimulus`
  n'importe ni `research` ni `console`, et **n'ouvre jamais le casque** (vérifié : `brainflow` et
  `core.acquisition` interdits).
- **La console est un CLIENT** : aucune logique que le moteur ne possède déjà, aucun catalogue
  recopié, **aucune écriture disque**.
- **Et, désormais explicite : tout l'usage réel se pilote depuis l'interface.** Une capacité livrée
  sans chemin graphique est une tâche **incomplète**, pas une tâche à compléter plus tard.
- Code et commentaires **en français** ; `README.md`, `docs/markers.md` et les commits **en
  anglais** ; `CLAUDE.md`, `docs/SPEC.md`, `docs/recette.md` en français.
- Tout testable **sans casque**. Aucun test n'écrit dans le vrai `data/`.
- Un seul programme du projet à la fois pendant les tests.
- **La contrainte est le TEMPS.** ~40 Ko de diff au maximum par sous-agent.
