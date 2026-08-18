# L'ErrP sur le réseau — le moteur dit quand la machine vient de se tromper

**Date** : 2026-08-18 · **État** : conception validée, prête pour le plan d'implémentation

## 1. Le but, en une phrase

Publier l'**ErrP** comme **5e mode du moteur** : à chaque feedback affiché par une application
externe, le moteur époche l'EEG autour de cet instant et publie un verdict — la machine vient-elle
de se tromper, et avec quel score.

C'est le second client du tuyau des marqueurs entrants, livré la veille pour le P300. Le moteur
passera de **4 modes publiés sur 6 à 5 sur 6**.

## 2. Ce qui rend ce chantier différent : les chiffres existent déjà

⚠️ **La calibration réelle a été faite le 2026-07-24** (deux séances, n=200), et son résultat n'avait
jamais été remonté. Ré-entraîné depuis les époques conservées le 2026-08-18 :

| | |
|---|---|
| **AUC** | **0,7763**, validation croisée **groupée par bloc** |
| **p (permutation, 100 tirages)** | **0,0099** — la plus petite atteignable : aucune permutation ne bat l'observé |
| Effectif | 200 époques : **62 ERREUR / 138 bonnes**, 5 blocs |
| `nfilter` retenu | 4 (balayage sur 2, 3, 4) |
| Repère interne | sLDA à fenêtres glissantes : 0,710 → xDAWN+Riemann apporte +0,066 |

**C'est le mieux validé des modes non publiés**, devant le P300 (0,714) et loin devant le MI (63 %).
Le groupement par bloc est ce qui rend le chiffre crédible : il empêche les époques d'un même bloc
de fuir entre les plis — le piège exact qui avait gonflé le MI de 79 % à 63 %.

**Mais le point de fonctionnement est modeste, et c'est le fait qui structure toute la conception :**

| Bonnes commandes gardées (TNR) | Erreurs attrapées (TPR) |
|---|---|
| 95,7 % | 24,2 % |
| 91,3 % | 40,3 % |
| **85,5 %** *(défaut, seuil 0,5103)* | **50,0 %** |
| 81,2 % | 59,7 % |
| 70,3 % | 71,0 % |

Une erreur sur deux attrapée, une bonne commande sur sept annulée. Il n'y a pas de repas gratuit :
chaque erreur de plus se paie en bonnes commandes perdues.

⚠️ **n = 1 personne, 1 séance.** Comme tout le reste dans ce projet.

## 3. Ce qui est dedans, et surtout ce qui reste dehors

**Dedans** : le décodeur déménagé dans `core/` · un `errp_models.py` jumeau de `p300_models.py` ·
le modèle **ré-entraîné** depuis les époques conservées · `core/modes/errp.py` avec son runtime ·
le flux `decoded_errp` · un événement de plus au contrat public de marqueurs · le point de
fonctionnement en réglage · la documentation.

**Dehors, et il faut le dire en livrant** :

- **La calibration ErrP jouée par le moteur.** Elle reste dans l'appli pygame, qui la joue déjà et
  bien. **Exactement la décision prise pour le P300**, pour la même raison : la migrer doublerait
  le chantier. Conséquence assumée : le mode **exige un modèle entraîné**, et un étudiant doit
  passer par pygame avant que le moteur puisse décoder.
- **La période réfractaire et le veto.** Décision tranchée : le moteur **publie**, le client
  **décide** (§4.1).
- **Le control plane** (commandes JSON entrantes) : toujours entier, toujours hors sujet.
- **Une seconde séance de validation.** On part sur les données de juillet. Le jour où une seconde
  personne est mesurée, le chiffre du §2 deviendra une moyenne au lieu d'un point.

## 4. Trois décisions structurelles, à ne pas rouvrir

### 4.1 Le moteur publie, il n'annule rien

La période réfractaire de 1,5 s et la décision d'annuler une commande appartiennent à
**l'application**. Motif : la règle du projet est que chaque mode publie une **intention neutre,
jamais une commande** — or « n'annule pas cette commande » *est* une commande. Et les 1,5 s sont
calées sur la cadence du démonstrateur pygame : un jeu Unity ou un robot ont la leur.

⚠️ **Conséquence à documenter, pas à étouffer** : deux feedbacks plus rapprochés que la fenêtre
d'époque (0,9 s) produisent des époques qui **se recouvrent**, donc le même ErrP peut être noté
deux fois. C'est un artefact physiologique, pas de la politique applicative. Le contrat public le
dit ; le moteur ne tait aucun verdict pour autant.

### 4.2 L'étudiant règle un TAUX, pas un seuil

`ErrPModel` stocke ses scores out-of-fold (`oof_scores_`, `oof_y_`). Le seuil peut donc être
**recalculé à la volée** pour n'importe quelle cible, sur les données de la propre calibration de
la personne.

Le réglage exposé est donc **« quelle part des bonnes commandes garder »** (`tnr_target`), pas un
log-odds — nombre qui ne veut rien dire pour un étudiant. Le moteur en déduit le seuil par
`pick_threshold`, la fonction que la calibration utilise déjà.

C'est ce qui rend la mesure du §2 exploitable au lieu d'être une note de bas de page : la courbe
est **dans le modèle**, il suffit de la lire.

**Bornes du réglage : `tnr_target` ∈ [0,50 ; 0,99]**, défaut `ERRP_TNR_TARGET = 0,85`. En dessous de
0,50 le mode annulerait plus d'une bonne commande sur deux, ce qui n'a pas de sens pour un veto.

**Si la cible est inatteignable**, `pick_threshold` retombe déjà sur le seuil qui maximise le TNR —
comportement existant, à conserver. ⚠️ Mais il doit se **DIRE** : sans message, l'étudiant croirait
avoir obtenu ce qu'il a demandé. Le moteur annonce le TNR réellement atteint à côté de celui visé.

### 4.3 `-1` veut dire la même chose que partout ailleurs

Le SSVEP, le MI et le P300 publient tous `-1` pour « pas de décision ». L'ErrP fait pareil quand
l'époque est rejetée pour artefact — un clignement sur l'erreur est précisément le cas fréquent.
Publier `0` reviendrait à affirmer « pas d'erreur » alors qu'on n'a rien vu.

## 5. Architecture

### 5.1 Ce qui est réutilisé tel quel — la moitié chère est déjà payée

`MarkerInlet` · le tampon EEG horodaté (`recent` / `recent_ts`) · la file des marqueurs mûrs
(`markers_murs`) · le champ `ModeSpec.marker_epoch_s` et le contrôle structurel de
`registry.check()` · le dimensionnement de `keep` · les compteurs `marqueurs_perdus` /
`marqueurs_futurs` / `illisibles`, désormais exposés dans `state()` et sur le flux `status` · et le
champ `mode` du contrat public de marqueurs, **conçu exactement pour ce second client**.

Les patrons à suivre sont `core/modes/p300.py` et `core/p300_models.py`.

⚠️ **`src/research/errp_decoder.py` importe DÉJÀ `core.p300_decoder`** (`P300Model`, `bandpass`,
`build_pipe`) : sa dépendance a migré avec le P300. Le déménagement n'a donc rien à démêler.

### 5.2 Ce qui est vraiment nouveau

**Trois des pires constats du P300 n'existent pas ici**, parce qu'il n'y a pas de manche : pas de
plafond de répétitions, pas de contamination entre manches, pas d'abandon. Chaque feedback est
indépendant et produit exactement un échantillon.

Restent quatre choses :

1. **Une sortie binaire** par événement, au lieu d'une sélection parmi N.
2. **Un seuil asymétrique réglable** (§4.2).
3. **Un rejet d'artefact RELATIF AU REPOS** (`σ > ERRP_ARTIFACT_RATIO × repos`, ratio = 4,0).
4. **Une phase de repos** que le P300 n'a pas — voir §8.

### 5.3 Le piège du pickle, une victime de plus

⚠️ **`data/errp_model.joblib` ne se charge plus depuis le 2026-08-17.** Le décodeur P300 ayant
déménagé dans `core/`, le pickle de l'ErrP référence un module qui n'existe plus sous ce nom.
C'est la troisième occurrence du même piège (4 modèles MI perdus, puis le P300).

**Même issue que pour le P300, et pour la même raison : les époques ont survécu.** Trois fichiers
(`data/errp_calib_20260724_112639_n200.npz`, `…_114608_n200.npz`, `errp_calib_last.npz`). On
**ré-entraîne**, on n'écrit **aucune passerelle de compatibilité** : le refus du modèle hérité doit
être explicite et nommé, comme dans `p300_models.py`.

⚠️ **Ne pas écraser `data/errp_model.joblib`** : le nouveau modèle s'écrit horodaté à côté, comme
pour le P300.

## 6. Le contrat public des marqueurs — un événement de plus

Le contrat existe déjà (`docs/markers.md`) et porte un champ `mode` prévu pour ça. L'ErrP y ajoute
**un seul événement**, plus simple que ceux du P300 : ni cible, ni fin de manche.

```json
{"mode": "errp", "event": "feedback"}
```

Le moteur époche `[-ERRP_PRE_S, +ERRP_EPOCH_S]` = `[-0,20 s, +0,70 s]` = **0,90 s** autour de
l'horodatage du marqueur.

⚠️ **L'horodatage se prend au moment où le feedback est À L'ÉCRAN**, juste après le basculement de
frame — la même règle que pour le P300, et la seule qui décide si le décodage fonctionne.

L'application n'a **pas** à dire si le feedback était bon ou mauvais : c'est de la vérité-terrain,
et elle ne sert qu'à la calibration, qui reste dans pygame.

## 7. Le flux publié

`EEG_API_Unicorn_decoded_errp`, **un échantillon par feedback**, cadence irrégulière.

| voie | sens |
|---|---|
| `error` | `1` erreur détectée · `0` rien · **`-1` pas de verdict** |
| `score` | log-odds « erreur », non borné, non comparable entre personnes |
| `threshold` | le seuil courant, celui que `tnr_target` a produit |
| `artifact` | `1` si l'époque a été rejetée (σ > 4× repos) |

**Métadonnées** : `paradigm = ErrP` · `decision_scale = logodds` · `no_decision_index = -1` ·
`threshold` · **`tnr_target`, `tpr` et `tnr` mesurés** · et la mention que ces taux viennent d'une
personne et d'une séance.

⚠️ **Publier le point de fonctionnement est une exigence, pas un ornement.** Une application qui lit
`error = 1` doit pouvoir savoir qu'elle tient une pièce légèrement biaisée — une erreur sur deux
attrapée — et non un verdict. Sans ces champs, elle traitera le flux comme fiable, ce qu'il n'est
pas à ce point de fonctionnement.

**Le flux ne se tait jamais** : un feedback envoyé produit toujours un échantillon, même rejeté.

## 8. La phase de repos, seule addition de structure

Le rejet d'artefact compare le σ de l'époque au σ **au repos**. Le mode déclare donc un `Rest` :

- **chauffe de `SSVEP_WARMUP_S` = 15 s**, jetée — l'offset DC de l'Unicorn dérive après l'ouverture
  de session, et c'est le piège qui avait rendu le SSVEP indétectable à son premier essai casque ;
- **repos de 8 s**, la même durée que le SSVEP, pour que deux modes lancés ensemble **partagent** ce
  repos au lieu de l'additionner.

⚠️ **LE PIÈGE QUE LE P300 VIENT DE PAYER, et que cette phase de repos rend PLUS probable ici.**
Pendant la chauffe et le repos, le runtime n'est pas en phase `running`, donc il n'appelle pas
`markers_murs` — le curseur ne bouge pas, et au premier pas de décodage il avale d'un coup 23 s
d'arriéré, dont tout ce qui dépasse le tampon part en `marqueurs_perdus`. C'était le **critique n°2**
de la revue du P300, et c'était son comportement **par défaut à chaque séance**.

Le mode ErrP doit donc, dès sa première version, **consommer et jeter les marqueurs pendant la
chauffe et le repos, en le disant une fois**. Le P300 le fait déjà (`_jeter_marqueurs_de_chauffe`) :
c'est un patron à reprendre, pas à réinventer.

## 9. Les pannes à rendre bruyantes

Ce projet combat les décodeurs qui tournent, publient des scores honnêtes et ne déclenchent jamais.

| Situation | Ce que le moteur fait |
|---|---|
| Aucun flux de marqueurs trouvé | Le dire, et ne pas prétendre décoder |
| Marqueur trop vieux / dans le futur | Compté et exposé (compteurs déjà en place) |
| Époque rejetée pour artefact | Publie `error = -1`, `artifact = 1` — **jamais un silence** |
| Aucun modèle entraîné | **Refuse de démarrer**, en disant comment en obtenir un |
| Modèle hérité illisible | Refus explicite et nommé, avec la source à ré-entraîner |
| Événement d'un autre mode | Ignoré en silence — le seul rejet muet autorisé, et il est normal |

## 10. La stratégie de test — sans casque

Board synthétique et marqueurs fabriqués. `synth_errp_epoch` existe déjà pour produire des époques
erreur / non-erreur.

⚠️ **Le test d'alignement compare le CONTENU dès le premier jour, pas la position.** La revue du
chantier P300 a établi qu'un `filtfilt` ajouté par erreur **laisse le pic exactement au même
échantillon** (réponse impulsionnelle à phase nulle, maximale au lag 0) — donc une assertion de
position laisse passer le double filtrage. Or `ErrPModel` filtre déjà en interne. L'assertion est
donc `np.array_equal` contre la tranche **brute** du tampon : elle épingle d'un coup position,
forme, ordre des voies et absence de traitement.

⚠️ **Le test que le P300 n'avait pas besoin d'avoir** : demander à garder 95 % des bonnes commandes
doit produire un seuil **plus haut** et un TPR **plus bas** que d'en demander 85 %. C'est une
**monotonie** qu'une implémentation cassée ne peut pas simuler, et c'est le cœur du seul réglage du
mode. Un réglage qui ne changerait rien est exactement le genre de décor que ce projet combat.

Trois autres, hérités des leçons du P300 :

- **le refus du modèle hérité** doit être éprouvé avec un faux module nommé `errp_decoder`
  enregistré dans `sys.modules` pendant le dump **et** le chargement — sinon on teste un autre
  refus ;
- **le point de fonctionnement publié dans les métadonnées** doit correspondre à ce que le modèle
  produit réellement, pas à une constante recopiée ;
- **l'autotest sort en 1 quand il échoue** (`sys.exit(0 if … else 1)`) : `p300_decoder.py` jetait
  son verdict et sortait toujours en 0, ce qui a invalidé une preuve.

## 11. Contraintes globales

- `src/core/` n'importe **jamais** `src/research/` ni `src/console/`, et ne contient ni pygame ni
  Qt. Vérifié par `python src/core/server.py --smoke`.
- La console est un **client** du moteur : aucune logique qu'il ne possède pas déjà.
- Code, commentaires et docstrings **en français** ; commits, README et doc étudiante **en anglais**.
- Tout testable **sans casque** (`--synthetic`).
- **Aucun test n'écrit dans le vrai `data/`** : répertoire temporaire + nettoyage dans un `finally`.
- Les constantes de protocole ne bougent pas.
- ⚠️ **Aucun moteur ne tourne pendant un test** : les noms de flux sont un contrat public.

## 12. Découpage indicatif pour le plan

1. Déménagement de `errp_decoder.py` vers `core/`, `errp_models.py`, **ré-entraînement** depuis les
   époques conservées, recâblage des importeurs de `research/`.
2. `core/modes/errp.py` : le runtime, la phase de repos, le rejet d'artefact, les pannes bruyantes.
3. Le réglage `tnr_target` et le recalcul du seuil depuis les scores out-of-fold, avec le test de
   monotonie.
4. `DecodedErrPPublisher` + les métadonnées du point de fonctionnement + l'enregistrement au
   registre + le dégrisage de la tuile.
5. L'événement `feedback` dans l'émetteur d'exemple, et le test d'alignement par le contenu.
6. Documentation : `docs/markers.md`, SPEC §5 et §14, recette, README, CLAUDE.md.
