# Motor Imagery dans le moteur — conception (chantier 3)

> Rédigé le 2026-07-29 à l'issue d'une session de conception avec l'utilisateur. Couvre le
> **chantier 3** nommé par [SPEC.md §14](../../SPEC.md) : « lancer une calibration et gérer les
> modèles depuis la console ; le MI est le premier candidat à migrer vers le moteur ».

## 1. But

Rendre le **Motor Imagery utilisable depuis une application extérieure**, Unity en particulier.
Aujourd'hui le MI est décodé par l'appli pygame, pour elle-même, à l'écran : **rien dans
`src/research/` ne publie sur LSL**. Sur les six modes de décodage du projet, deux sortent sur le
réseau (SSVEP, neuro) et quatre n'en sortent pas.

Le chantier livre trois choses : le décodeur MI dans le moteur, un flux `decoded_mi`, et une
**calibration jouée par le moteur** dont la console n'est que l'écran.

## 2. Le cadrage, tel que l'utilisateur l'a posé

Une phrase de la session de conception recadre tout le reste :

> « tout ce qu'on avait fait avant d'attaquer cette API n'a plus de raison d'exister, c'était juste
> du test »

`src/research/` est donc un **banc d'essai**, pas une surface de produit. Il n'y a par conséquent
aucun « doublon à maintenir » entre la calibration pygame et celle de la console : la pygame est
retirée, ses constantes de protocole migrent, ses écrans restent derrière.

⚠️ **Nuance à ne pas perdre** : c-VEP, P300 et ErrP n'ont **aucun chemin dans le moteur** et ne
survivent que par l'appli pygame. Ce chantier n'y touche pas.

| Décision | Choix | Motif |
|---|---|---|
| Périmètre | Publication **et** gestion des modèles **et** calibration | Choix explicite de l'utilisateur, après chiffrage du coût (« le double du chantier ») |
| Qui joue le protocole | **Le moteur** ; la console affiche | Règle du chantier 1 : aucune logique dans l'interface que le moteur ne possède pas. Et le repos partagé est déjà un protocole possédé par le moteur |
| Modèles archivés | **Abandonnés**, pas récupérés | Choix explicite. Ils datent du banc d'essai |
| Constantes du protocole | **Inchangées** | Elles portent des justifications datées issues du casque ; les changer rendrait les nouveaux modèles incomparables |
| Classes | **Trois** dans le modèle, **probabilités** sur le fil | REPOS est ce qui permet de dire « rien » ; le seuillage appartient au client |

## 3. Ce qui déménage

`src/research/mi_decoder.py` → **`src/core/mi_decoder.py`**, sans adaptation. Il n'importe que
numpy, scipy, sklearn, joblib et `core.config` — ni pygame ni Qt. Les constantes MI
(`MI_WINDOW_S`, `MI_PROB_MIN`, `MI_REREF`, `MI_VOTE_LEN`, `MI_MIN_VOTES`, `MI_METHOD`) sont **déjà**
dans `core/config.py`.

C'est le déménagement que CLAUDE.md décrit comme la seule façon correcte de publier un mode :
« publier un mode = DÉMÉNAGER son décodeur dans `core`, pas y tirer un import ».

`MIDecoder.classify(window)` porte **déjà** la même signature que `CCADecoder` — sa docstring le
dit. C'est ce qui rend le runtime petit.

### Les modèles archivés sont abandonnés — délibérément

Les quatre `.joblib` de `data/` ont été picklés quand `mi_decoder.py` était à la racine de `src/`.
Leur pickle référence le module `mi_decoder`, disparu à la restructuration `core/`/`research/` du
2026-07-27. **Aucun n'est chargeable aujourd'hui** ; `research/app.py:434` et `mi_pilot.py:93`
planteraient tous les deux. Le smoke ne le voyait pas : il entraîne un modèle neuf.

**Ce défaut est clos par abandon.** Il n'y a pas de migration à écrire : les modèles produits à
partir de maintenant se picklent sous `core.mi_decoder` et sont lisibles partout. Ce paragraphe
existe pour qu'une session future ne « redécouvre » pas le problème et n'entreprenne pas de le
réparer — c'est une décision, pas un oubli.

Conséquence assumée : **le modèle à 79 % n'est pas reproductible.** Ses époques brutes ont de toute
façon été écrasées (cf. §7), il n'en restait que le fichier modèle.

### Une donnée réelle est conservée

`data/mi_calib_last.npz` — 30 essais étiquetés, 2026-07-22 — reste sur le disque. C'est la
**seule donnée EEG MI réelle** disponible, et donc le seul moyen de vérifier le calcul d'accuracy
sans casque. `data/` étant hors dépôt, les tests automatiques ne peuvent pas en dépendre : ils
tourneront sur l'ERD synthétique de `mi_decoder.synth_mi_trial`, et cette vérification-là se fait
une fois, à la main, sur la vraie séance.

## 4. Le mode MI dans le moteur

Un fichier `src/core/modes/mi.py`, sur le patron exact de `ssvep.py` : un `SPEC` (`ModeSpec`) et un
`MIRuntime` (`ModeRuntime`).

**Réglages déclarés** (`spec.params`) :

| Clé | Genre | Défaut | Rôle |
|---|---|---|---|
| `model` | `choice` | le plus récent | Quel modèle entraîné utiliser. Les choix sont les `.joblib` lisibles de `data/` |
| `prob_min` | `float` | `MI_PROB_MIN` = 0,60 | En dessous, aucune décision |
| `vote_len` | `int` | `MI_VOTE_LEN` = 5 | Longueur du vote glissant |
| `min_votes` | `int` | `MI_MIN_VOTES` = 3 | Votes concordants requis |

`model` porte `affecte_decodage=True` : en changer recrée le flux, parce que les voies publiées
portent les noms de classes du modèle.

**Le MI exige la chauffe de 15 s.** L'offset DC de l'Unicorn dérive après ouverture de session
(mesuré : 10⁵ µV en rampe), et le MI lit C3/C4 — précisément les voies qui saturent. Le mode
déclare donc :

```python
Rest(warmup_s=15.0, duration_s=0.0,
     instruction="Le casque se stabilise — reste immobile.")
```

**Chauffe obligatoire, aucun plancher à mesurer** : le modèle est appris, pas étalonné.

Vérifié dans le code plutôt que supposé — **aucune extension du contrat n'est nécessaire** :
`begin_rest` pose `_rest_s = 0`, le premier tick de la phase `rest` calcule `_rest_until = now`, et
`MIRuntime._rest_step` n'a qu'à rendre `now >= self._rest_until` pour passer à `running` au tick
suivant. L'arbitrage du repos partagé reste cohérent : lancé seul, le MI est « meneur » et sa
consigne s'affiche pendant la chauffe ; lancé avec le SSVEP ou le neuro, il a la durée la plus
courte, donc c'est l'autre mode qui donne la consigne — et le MI attend, sans dommage.

**Aucun modèle disponible ?** Le mode refuse de démarrer, et **dit pourquoi** : « aucun modèle MI
entraîné — lance une calibration ». C'est la règle d'honnêteté de l'interface déjà en vigueur pour
les modes que le moteur ne sait pas faire, appliquée ici à un mode qu'il sait faire mais qui manque
de sa matière première. Un mode qui démarre sans modèle et ne décide jamais rien serait exactement
la panne silencieuse que ce produit passe son temps à supprimer.

## 5. Le contrat du flux `decoded_mi`

Nom complet : `EEG_API_Unicorn_decoded_mi`. Cadence ~5 Hz, comme `decoded_ssvep`.

| Voie | Contenu |
|---|---|
| `intent_index` | `-1` = aucune décision (vote non concluant ou sous le seuil) ; sinon l'indice de la classe : 0 = GAUCHE, 1 = DROITE, 2 = REPOS |
| `confidence` | probabilité de la classe désignée |
| `p_GAUCHE`, `p_DROITE`, `p_REPOS` | les trois probabilités, toujours publiées |

**`-1` et `REPOS` sont distincts, exprès.** « Je ne sais pas » et « la personne se repose » ne
demandent pas la même réaction côté client.

Les noms de voies sont **dérivés des classes du modèle**, comme les voies SSVEP sont dérivées des
fréquences. Métadonnées LSL : `decision_scale = "proba"`, seuils `(prob_min, min_votes/vote_len)`.

C'est une **intention neutre**, jamais une commande d'actionneur — règle du produit.

**Ce que ça vaut, dit franchement** : 63 % honnêtes à deux classes sur la seule séance survivante
(§8). Dans Unity ce sera imprécis et lent. Utilisable pour une démonstration, pas pour piloter
finement. Cette phrase doit se retrouver dans le README, pas seulement ici.

## 6. La calibration, jouée par le moteur

Un `CalibrationRuntime` possédé par le moteur, qui tient la ligne du temps et expose son état dans
`snapshot()`. La console **rend** cet état ; elle ne décide de rien.

**Ligne du temps**, identique au protocole validé au casque :

1. **chauffe** — 15 s jetées (la dérive DC) ;
2. **briefing** — consigne : imagerie *kinesthésique*, sentir le serrement, pas se le représenter ;
3. **échauffement** — `WARMUP_PER_CLASS` = 2 essais par classe, **non enregistrés** (le MI
   s'améliore en début de séance) ;
4. **essais**, dans un ordre tiré au hasard : pour chacun, `CUE_S` = 3 s de mise en route **non
   enregistrées**, puis `IMAGERY_S` = 4 s gardées, puis `REST_S` = 1,5 s ;
5. **entraînement** — CSP + LDA sur des fenêtres de `MI_WINDOW_S` = 2 s, pas de 1 s (3 fenêtres
   par essai) ;
6. **résultat** — accuracy honnête (§8), sauvegarde du modèle et de l'enregistrement.

**Durées de séance proposées** (essais par classe) : 10 (« court »), 14 (~5 min), 18 (~7 min),
26 (« long »).

**Ce que le moteur publie à chaque instant** : la phase, la consigne à afficher, la classe cuée,
le décompte restant, le numéro d'essai et le total. La console n'a qu'à peindre.

**Les bips latéralisés** — oreille gauche pour GAUCHE, droite pour DROITE, les deux pour REPOS —
sont joués **par la console**, via `PySide6.QtMultimedia` (vérifié disponible, PySide6 6.11.1). Le
son est de la présentation, pas du protocole : si l'audio manque, la calibration se déroule quand
même, et le dit.

**Commande** : `start_calibration(id="mi", trials_per_class=N)`. Le mode gagne une phase publique
`calibrating`, à côté de `warmup` / `baseline` / `decoding`. Une calibration en cours interdit une
seconde calibration du même mode.

**Pourquoi le moteur et pas la console** : la règle « aucune logique dans l'interface » d'abord ;
mais surtout, une calibration possédée par le moteur devient pilotable depuis un client LSL le jour
où l'adaptateur entrant existera. C'est exactement l'évolution **F2 « calibration pilotée par
l'app »** parkée en [SPEC §13](../../SPEC.md) — ce chantier la rend possible sans la livrer.

**Le MI n'exige pas de stimulus verrouillé à la frame**, contrairement au c-VEP et au P300 : il n'y
a pas de clignotement, seulement des consignes et un minutage à la dizaine de millisecondes près.
Qt suffit. C'est ce qui rend ce chantier faisable et qui interdit le même traitement aux trois
autres modes.

## 7. La console

**Page de calibration** — une page de plus dans la pile, au même titre qu'une page de mode :
consigne en grand, décompte, progression (essai *n* sur *N*), et un bouton d'abandon. Aucune
logique : elle affiche `snapshot()`.

**Gestion des modèles** — la liste des modèles disponibles avec, pour chacun, sa date, son nombre
d'essais et son **accuracy honnête**. Le choix se fait dans le formulaire de réglages, déjà généré
depuis le contrat : c'est le réglage `model` du §4.

Les métadonnées vivent **dans l'objet modèle** (`MIModel` est déjà picklé) plutôt que dans un
fichier annexe : deux fichiers à garder synchronisés, c'est deux vérités qui divergent.

## 8. Deux défauts corrigés

### L'accuracy affichée devient honnête

La calibration découpe chaque essai en fenêtres glissantes puis les mélange entre plis de validation
croisée. Des fenêtres du **même essai** se retrouvent donc en apprentissage et en test : le score
est gonflé.

Mesuré sur les 30 essais archivés, en refaisant les deux calculs :

| | CV affichée (fenêtres mélangées) | CV honnête (`GroupKFold` par essai) | p (permutation d'essais) |
|---|---|---|---|
| 3 classes G/D/REPOS | 55,6 % | **40,0 %** (hasard 33 %) | 0,082 — **pas significatif** |
| 2 classes GAUCHE vs DROITE | 73,3 % | **63,3 %** (hasard 50 %) | 0,038 — significatif |

`mi_compare.py` fait déjà le calcul correctement (`GroupKFold`, documenté dans son entête) ;
**l'écran de calibration, non**. Le chiffre montré à l'étudiant à la fin de sa séance est gonflé de
10 à 16 points.

La nouvelle calibration mesure en `GroupKFold` par essai et **n'affiche que ce chiffre-là**. Les
verdicts (« EXCELLENT / UTILISABLE / FAIBLE ») sont recalés sur cette échelle, sinon ils mentent.

⚠️ **Piège rencontré en produisant ces chiffres, à ne pas refaire** :
`permutation_test_score(..., groups=g)` permute les étiquettes **à l'intérieur** de chaque groupe.
Toutes les fenêtres d'un essai partageant leur étiquette, chaque permutation est l'identité et
p = 1,0 quel que soit le signal. Le test doit permuter **au niveau de l'essai**, puis propager
l'étiquette tirée à ses fenêtres.

### L'enregistrement cesse d'être écrasé

`mi_calib_last.npz` a un **nom fixe** : chaque calibration écrase la précédente. Le c-VEP et l'ErrP
horodatent les leurs. C'est ce qui a fait perdre les époques de la séance à 42 essais.

Nouveau nommage, aligné sur l'existant : `mi_calib_AAAAMMJJ-HHMMSS_nNN.npz`, et un modèle par
calibration. **Rien n'est jamais écrasé.**

## 9. Ce qui est retiré

**Tout ceci arrive à la FIN de la moitié B** (§10), jamais avant : tant que la console ne sait pas
calibrer, l'écran pygame est le seul moyen de produire un modèle.

- Le **mode MI de l'appli pygame** disparaît du menu : l'appli passe de 6 à 5 modes.
- `src/research/mi_calibrate.py` et `src/research/mi_pilot.py` sont **supprimés** : leur fonction
  est intégralement reprise par le moteur. Git en garde l'historique.
- `src/research/mi_compare.py` est **conservé** et repointé sur `core.mi_decoder` : c'est un outil
  d'analyse (comparer CSP et Riemannien sur une calibration enregistrée) que rien ne remplace.
- CLAUDE.md et le README disent aujourd'hui « menu à 6 modes » et « seul accès à c-VEP, P300, MI,
  ErrP ». **Les deux deviennent faux** et sont mis à jour par ce chantier.

## 10. Le chantier se découpe en deux moitiés livrables

Le périmètre retenu est large — la moitié « calibration » vaut à elle seule la moitié « publier ».
Le plan d'implémentation doit donc être **ordonné pour que la première moitié soit complète et
testable avant que la seconde commence** :

- **Moitié A — le MI sur le réseau.** Déménagement du décodeur, `core/modes/mi.py`, publication de
  `decoded_mi`, réglage `model`, exemple Unity. À la fin de A, l'objectif d'usage est atteint : le
  MI arrive dans Unity, avec un modèle entraîné par l'ancien écran pygame tant qu'il existe.
- **Moitié B — la calibration et les modèles.** `CalibrationRuntime`, page de calibration dans la
  console, accuracy honnête, archive horodatée, liste des modèles. C'est seulement à la fin de B
  que l'écran pygame est retiré.

Cet ordre a une conséquence pratique : **si le temps manque, s'arrêter après A laisse un produit
cohérent**. S'arrêter au milieu de B laisserait le MI sans aucune calibration.

## 11. Tests

Sans casque, et c'est la condition pour que le chantier avance aujourd'hui :

- **Autotest de `core/mi_decoder.py`** — conservé tel quel : il valide CSP+LDA sur de l'ERD
  synthétique.
- **Autotest de `core/modes/mi.py`** — le `SPEC` est valide au regard du contrat, les voies
  dérivent bien des classes du modèle, un modèle absent ou illisible est refusé avec un message
  qui le dit.
- **`server.py --smoke`** — un mode `mi` démarre sur board synthétique avec un modèle entraîné à la
  volée, publie `decoded_mi`, et le flux porte les bonnes voies. Plus : une calibration complète
  jouée en accéléré, jusqu'à la sauvegarde du modèle.
- **Le calcul d'accuracy** — vérifié sur ERD synthétique : la CV groupée doit être **inférieure** à
  la CV naïve dès qu'il y a plusieurs fenêtres par essai. C'est l'invariant, indépendant du jeu de
  données.
- **`console/app.py --smoke`** — la page de calibration rend chaque phase, et le bouton d'abandon
  passe bien par la file de commandes.
- **Frontière** — `server.py --smoke` scanne déjà `src/core/**` et échouerait sur un import de
  `research` : le déménagement est donc vérifié par un test, pas par la discipline.
- **Une vérification manuelle, une seule fois** : rejouer le calcul d'accuracy honnête sur
  `data/mi_calib_last.npz` et retrouver 40,0 % / 63,3 %.

## 12. Ce qui reste dehors

- **c-VEP, P300, ErrP** : inchangés, toujours accessibles seulement par l'appli pygame. Le P300 et
  l'ErrP attendent les **marqueurs entrants** ; le c-VEP attend un stimulus verrouillé à la frame.
- **Aucun nouveau stimulus.** Le MI est endogène : il n'en a pas.
- **La calibration pilotée par une app extérieure** (F2) : rendue possible, pas livrée.
- **Le contrôle à distance** de la calibration depuis un client LSL : même chose.
- Un `MiIntentReceiver.cs` est ajouté dans `examples/unity/`, sur le modèle du récepteur SSVEP —
  **écrit contre l'API, jamais compilé** : il n'y a pas d'Unity sur ce poste, comme pour le SSVEP.

## 13. Risques et inconnues

- **Le moteur gagne une notion de « calibration »** qu'il n'avait pas. C'est le vrai changement
  structurel du chantier, davantage que le MI lui-même. Le risque est qu'elle soit conçue pour le
  MI seul et ne serve à rien pour les autres modes ; la parade est de la garder **portée par le
  contrat** (`Calib`), pas codée en dur dans `mi.py`.
- **Le MI vaut 63 % honnêtes sur une séance de 20 essais utiles.** C'est significatif (p = 0,038)
  mais modeste, et mesuré sur **une personne, une séance**. Rien ne garantit qu'un étudiant
  atteigne ça. Le produit doit le dire au lieu de le laisser découvrir.
- **La fatigue est le facteur limitant mesuré**, pas la durée par essai : le 3 classes tombe de
  57 % à 33 % en deuxième moitié de séance. Les séances longues ne sont donc pas forcément
  meilleures — l'offre de quatre durées reste, mais sans laisser croire que « long » vaut mieux.
- **Jamais vérifié au casque** : ce chantier se code et se teste entièrement sans matériel. Sa
  recette matérielle s'ajoutera à [docs/recette.md](../../recette.md).

## 14. Les valeurs exactes, en un endroit

```
MI_LABELS       = ("GAUCHE", "DROITE", "REPOS")
MI_BAND         = (8.0, 30.0)     # mu + beta
MI_WINDOW_S     = 2.0             # fenêtre de décodage — entraînement ET online
MI_PROB_MIN     = 0.60
MI_VOTE_LEN     = 5 ;  MI_MIN_VOTES = 3
MI_REREF        = "car" ;  MI_METHOD = "csp"
MI_KEY_CHANNELS = [1, 2, 3]       # C3, Cz, C4

CUE_S = 3.0 ; IMAGERY_S = 4.0 ; REST_S = 1.5 ; WARMUP_PER_CLASS = 2
Durées de séance (essais par classe) : 10 · 14 · 18 · 26
Découpage d'entraînement : fenêtres de 2 s, pas de 1 s  ->  3 fenêtres par essai
Chauffe du mode : 15 s (dérive DC de l'Unicorn)
```
