# La console, seul point d'entrée — conception

**Date** : 2026-09-07 · **État** : validé, prêt pour le plan d'implémentation

À la fin de ce chantier, **une personne qui n'ouvre jamais un terminal peut tout faire** : contrôler
le contact, calibrer les quatre modes à modèle, choisir un modèle, afficher un stimulus, décoder,
lire les résultats. L'appli pygame cesse d'être une application ; les trois émetteurs deviennent un
paquet du produit ; `data/` n'est plus écrit qu'à un seul endroit.

---

## 1. Ce qu'on répare, et ce n'est pas qu'une commodité

**Le défaut visible.** La console ne lance **aucun** autre programme — zéro `subprocess`, `Popen` ou
`QProcess` dans `src/console/`. Et elle n'ouvre de page de calibration que pour les modes dont le
contrat dit `kind == "console"`, c'est-à-dire **le Motor Imagery et lui seul**. Sans terminal, trois
modes sur six sont donc hors d'atteinte : on ne peut ni les calibrer, ni afficher leur stimulus.

**Le défaut invisible, et c'est lui qui justifie le chantier.** Aujourd'hui les époques
d'**entraînement** sont découpées par un chemin de code — l'appli pygame, son horloge, son
`app.acq` — et celles du **décodage** par un autre : le tampon du moteur, les marqueurs LSL,
`time_correction`. Rien ne vérifie qu'ils s'accordent. Or un décalage de quelques échantillons à
l'épochage ne lève aucune exception : il fait décoder du bruit avec une confiance élevée, et reste
vert dans tous les autres tests (c'est mesuré, cf. `CLAUDE.md` sur `modes/p300.py` : la mutation
déplace le pic de −38 échantillons et 46 assertions restent vertes). **Le P300, l'ErrP et le c-VEP
du moteur n'ayant jamais vu un cerveau, cet accord n'a jamais été vérifié** — et il ne le sera pas
par un test tant que les deux chemins existent. Les faire passer par le **même** épochage supprime
la question au lieu de la reporter.

**Le troisième défaut, plus petit mais réel.** Aucune calibration ne demande son avis avant
d'écrire : elle sauvegarde, **puis** annonce la précision. Comme le moteur propose par défaut le
modèle chargeable le plus récent, **une calibration ratée devient le défaut en silence**. Ça vaut
aussi pour le MI.

## 2. Ce qui existe déjà — à ne PAS redécouvrir

| Pièce | Où | État |
|---|---|---|
| Sélecteur de modèle (liste déroulante, tri du plus récent au plus ancien) | `console/params_form.py:90`, `console/mode_page.py:180` | **fait**, pour les quatre modes |
| Page de calibration générique (Avant / Pendant / Après), pilotée par `snapshot()["calibration"]` | `console/calib_page.py` | **faite**, ne connaît aucun mode en particulier |
| Calibration jouée par le moteur, époques prises dans son tampon (`recent_window`) | `core/modes/calibration.py`, `core/modes/mi_calib.py` | **faite** pour le MI |
| `Calib.epoch_s` — dimensionne le tampon du moteur sur la plus longue époque d'une calibration | `core/modes/contract.py:148` | **fait** |
| Emplacement dédié `EngineServer.calibration`, distinct des modes | `core/server.py` | **fait** — un mode qui refuse de démarrer sans modèle rendrait sa propre calibration inatteignable |
| Marqueurs entrants : `MarkerInlet`, tampon horodaté, file des marqueurs mûrs, `time_correction` | `core/markers.py`, contrat public `docs/markers.md` | **fait**, éprouvé par trois modes |
| Émetteurs verrouillés à la frame, horodatage **après** `display.flip()`, **sans ouvrir le casque** | `research/{p300,errp,cvep}_stimulus.py` | **faits** |
| Voies clés par mode (`OCCIPITAL`, `P300_MIDLINE`, `ERRP_MIDLINE`, `CVEP_CHANNELS`, `NEURO_KEY_CHANNELS`) | `core/config.py:130, 321, 742, 806, 850` | **faites** |
| L'émetteur ErrP importe déjà les primitives de piste de sa calibration | `research/errp_stimulus.py:574` | la fusion est à moitié faite |

## 3. Architecture — quatre paquets

`src/stimulus/` est créé. Les trois émetteurs y montent, parce que c'est ce qu'ils sont devenus :
des composants du produit que la console lance et dont la calibration dépend, déjà présentés comme
les émetteurs de référence par `docs/markers.md`.

```
core      ← n'importe rien du dépôt hors de lui-même ; ni pygame ni Qt
stimulus  → core                    (les fenêtres : dessin, marqueurs ; jamais le casque)
console   → core, stimulus          (l'interface : orchestre, décide, n'écrit pas le disque)
research  → core, stimulus          (le banc d'essai : analyses, protocoles chiffrés)
```

Fichiers : `stimulus/p300.py`, `stimulus/errp.py`, `stimulus/cvep.py`, `stimulus/registry.py`
(ce que la console peut lancer, déclaré ici et nulle part ailleurs), `stimulus/refresh.py`.

⚠️ **`measure_refresh` doit déménager avec eux.** Les trois émetteurs l'importent aujourd'hui de
`research/ssvep_stimulus.py` ; le laisser là créerait `stimulus → research`, l'arête qu'on refuse.
Il va dans `stimulus/refresh.py`, et `research/ssvep_stimulus.py` l'importe de là.

Le scanner AST de `server.py --smoke` est étendu : il vérifie aujourd'hui que `core` n'importe ni
`research` ni `console` ; il vérifiera aussi que `core` n'importe pas `stimulus`, et que `stimulus`
n'importe ni `research` ni `console` — la règle reste vérifiée par un test, pas par la discipline.

## 4. Le contrat `Calib` — qui mène la ligne du temps

`kind` cesse de dire « console » vs « natif ». « natif » signifiait *reste dans l'appli pygame*, ce
qui devient faux : les quatre calibrations sont désormais jouées par le moteur et affichées par la
console. Ce qui les distingue est **qui mène la ligne du temps** :

- `kind = "moteur"` — le moteur mène. Aucun stimulus à afficher : le Motor Imagery est endogène.
  C'est `CalibrationRuntime` tel quel.
- `kind = "fenetre"` — une fenêtre de `stimulus/` mène, parce que le protocole exige un stimulus
  verrouillé à la frame. Le moteur est **passif** : il écoute, découpe, entraîne quand on lui dit
  que c'est fini. C'est le P300, l'ErrP et le c-VEP.

Champs ajoutés à `Calib` :

- `stimulus_id: str = ""` — la clé que `stimulus/registry.py` sait résoudre en commande. Vide si
  `kind == "moteur"`. **`core` ne nomme aucun module de `stimulus`** : il nomme une clé, la
  résolution vit dans `stimulus/registry.py`, et la console fait le pont. C'est ce qui garde
  l'arête `core → stimulus` inexistante.
- `runtime_cls` continue de porter la classe du runtime (`MarkerCalibrationRuntime` et ses
  sous-classes pour les trois nouveaux).
- `reason` disparaît : il expliquait pourquoi une calibration restait dehors, et plus aucune ne
  reste dehors.

`ModeSpec` gagne `key_channels: tuple = ()`, alimenté par les constantes de `core/config.py`
listées en §2. La console s'en sert pour surligner les voies qui comptent au contrôle de liaison —
elle ne recopie aucune liste.

## 5. Le protocole public — trois événements de calibration

Ajoutés à `docs/markers.md`, à côté de `flash` / `round_end` / `feedback` / `cycle`, qui gardent
exactement leur sens actuel :

```json
{"mode": "p300", "event": "calib_start", "trials": 24}
{"mode": "p300", "event": "cue",         "target": 3}
{"mode": "p300", "event": "calib_end"}
```

- **`calib_start`** ouvre la séance et annonce le nombre d'essais attendus — la console peut donc
  afficher un avancement honnête, et le moteur détecter une fenêtre qui meurt en cours de route.
- **`cue`** porte la **vérité-terrain** : la seule information que le décodage ne donne jamais au
  moteur (`docs/markers.md` le dit aujourd'hui du c-VEP : *« One target must be fixated, and the
  engine never learns which »*). Sa charge utile diffère par mode : `target` pour le P300 et le
  c-VEP ; pour l'ErrP l'étiquette est portée par l'événement `feedback` lui-même, qui gagne un
  champ `error: true|false` **pendant la calibration seulement**.
- **`calib_end`** clôt la séance : le moteur entraîne, la fenêtre se ferme.

**Conséquence acquise, pas construite** : toute application capable d'afficher le stimulus peut
désormais entraîner un modèle. La calibration cesse d'être verrouillée à notre pygame. À documenter,
rien à coder.

⚠️ **Les événements de calibration n'ont d'effet que sur une calibration en cours.** Un `cue` reçu
alors que le mode décode est ignoré, sans erreur : c'est une fenêtre lancée en mode calibration
pendant qu'un décodage tourne, et le moteur n'a pas à s'arrêter pour ça.

## 6. `MarkerCalibrationRuntime` — la ligne du temps passive

Nouveau module `core/modes/marker_calib.py`. Il partage avec `CalibrationRuntime` le **contrat
public exact** — `PHASES`, `terminee`, `resultat`, `probleme`, `cancel()`, `duree_estimee_s()`, et
la forme de `snapshot()["calibration"]` — pour que `console/calib_page.py` l'affiche **sans une
ligne de plus**. Ce qui diffère est la ligne du temps :

| Phase | `CalibrationRuntime` (moteur) | `MarkerCalibrationRuntime` (fenêtre) |
|---|---|---|
| `chauffe` | 15 s jetées, décomptées par le moteur | idem — la dérive DC de l'Unicorn ne dépend pas de qui mène |
| `echauffement` | essais non enregistrés | **absent** : la fenêtre gère son propre briefing |
| `essais` | le moteur tire les classes et décompte | le moteur **attend** les marqueurs et compte ce qui arrive |
| `entrainement` | à la fin des essais | à `calib_end` |
| `fini` / `annule` | idem | idem, plus deux causes propres : fenêtre morte, ou `calib_start` jamais reçu |

Trois causes d'abandon à traiter explicitement, chacune avec un message lisible dans `probleme` :

1. **La fenêtre ne s'est jamais annoncée** — pas de `calib_start` dans les
   `CALIB_FENETRE_ATTENTE_S = 30.0` (nouvelle constante de `core/config.py` ; large, parce qu'une
   fenêtre pygame en plein écran met plusieurs secondes à s'initialiser). Message : la fenêtre ne
   s'est pas lancée, ou publie sous un autre nom.
2. **La fenêtre est morte en cours** — plus aucun marqueur depuis `CALIB_FENETRE_SILENCE_S = 15.0`,
   alors que `calib_start` avait annoncé davantage d'essais. Le seuil tient avec marge devant le
   plus long silence normal des trois protocoles — la pause entre deux manches P300, 2,5 s. Ce qui est enregistré n'est **ni entraîné ni sauvegardé**, même
   règle que `CalibrationRuntime.cancel()` : une séance tronquée produirait un modèle que rien ne
   distingue d'un modèle complet dans la liste.
3. **L'utilisateur annule** depuis la console.

⚠️ **L'époque est découpée par le chemin du décodage, pas par un second chemin.** Le runtime
consomme la file des marqueurs mûrs de `core/markers.py` et prélève dans le tampon horodaté du
moteur, avec le même `marker_epoch_s` et la même correction d'horloge que le mode. C'est l'invariant
central du chantier ; §11 dit comment il est protégé.

## 7. Les trois entraîneurs montent dans `core`

`core/modes/p300_calib.py`, `core/modes/errp_calib.py`, `core/modes/cvep_calib.py` — jumeaux de
`mi_calib.py`. Chacun sous-classe `MarkerCalibrationRuntime` et implémente `_entrainer`.

Le travail est surtout un **déménagement**, pas une réécriture : la moitié pure de chaque
calibration existe déjà et ne touche ni pygame ni le casque —
`research/cvep_calibrate.py:170 entraine_les_deux(epochs, labels, fs, refresh, band, …)` en est
l'exemple net. Ce qui reste dans la fenêtre est le rendu ; ce qui monte est l'entraînement, la
validation croisée et le verdict.

Les mesures d'honnêteté déjà en place suivent le code et ne sont pas rouvertes : validation croisée
**groupée par essai** (jamais par fenêtre), McNemar exact pour le c-VEP (« indiscernables » est la
réponse attendue entre eCCA et rCCA), AUC hors-pli et test de permutation pour l'ErrP.

⚠️ **Les modèles déjà sur le disque restent chargeables.** Leur format ne change pas. Ils ont été
entraînés par l'ancien chemin, ce qui est précisément la raison de les réentraîner — mais aucun
n'est invalidé par ce chantier.

## 8. La console — trois ajouts, aucun raisonnement

**a. Le contrôle de liaison.** `signal_check` (`research/ui.py:217`) est appelé par chaque
calibration et chaque écran de pilotage d'aujourd'hui. Les fenêtres de `stimulus/` **ne peuvent pas
le reprendre : elles n'ont pas le casque**. Il monte donc dans la console, qui l'a — un écran qui
montre le σ par voie, surligne les `key_channels` du mode visé, et **refuse de lancer** tant qu'une
voie est plate ou saturée. Le verdict vient du moteur (`core/lsl_io.py` porte déjà les verdicts de
qualité) ; la console ne juge rien elle-même.

**b. Le lancement d'une fenêtre.** Un `QProcess` par fenêtre, la commande venant de
`stimulus/registry.py`, jamais écrite en dur. Deux boutons, un seul mécanisme :

- **« Calibrer »** sur les pages P300, ErrP, c-VEP → lance la fenêtre en mode calibration.
- **« Lancer le stimulus »** sur les mêmes pages, mode décodage → sans lui, tester ces trois modes
  exigerait encore un terminal, et l'objectif du chantier ne serait pas atteint.

La console montre l'état du processus (lancé / fermé / échec de lancement) et **refuse d'en lancer
deux**. Si la fenêtre meurt anormalement, elle le dit — le silence est le défaut qu'on répare.

**c. L'écran de verdict.** L'écran « Après » de `calib_page.py` existe déjà et affiche le résultat.
Il gagne **Refaire** et **Enregistrer**, et perd le fait accompli : le modèle n'est plus sur le
disque quand on lit le chiffre. La phrase d'honnêteté (`HONNETETE`) reste obligatoire et devient
propre à chaque mode — celle du MI parle de validation par essai et du repère à 40 %, celle du P300
parlera de son AUC, etc. Elle vient du contrat, pas de la console.

## 9. La garde de sauvegarde — `data/` écrit à un seul endroit

`_entrainer` écrit son candidat dans un dossier **temporaire** et rend
`{"accuracy": float, "chemin": str, "details": dict}`. Rien n'entre dans `data/` avant un geste
explicite.

- **Enregistrer** → la console envoie la commande `save_calibration` au moteur, qui déplace le
  candidat sous son nom **horodaté** définitif et n'écrase jamais rien. Le modèle apparaît alors en
  tête de la liste déroulante du mode, sans rien relancer.
- **Refaire** → commande `discard_calibration` : le candidat est supprimé, retour au briefing.
- **La console n'écrit jamais sur le disque** : elle est un client, elle envoie des commandes.
- Une calibration abandonnée ou dont la fenêtre est morte ne produit aucun candidat.

⚠️ **Le nettoyage du temporaire doit être inconditionnel** — y compris si la console se ferme entre
l'entraînement et la décision. Un candidat orphelin sous un nom qui ressemble à un modèle serait
proposé par le moteur au démarrage suivant : exactement le défaut qu'on ferme. Le dossier temporaire
est donc hors de `data/` et porte un nom qui ne correspond à **aucun** motif de découverte des
catalogues (`p300_models`, `errp_models`, `cvep_models`, `mi_models`).

## 10. Ce qui se retire

**Les trois écrans de pilotage** — `mode_ssvep` (`research/app.py:383`), la sélection P300
(`:529`), le démonstrateur ErrP (`:885`) — partent dans `archive/`, avec leur `--smoke`, rejoindre
`cvep_pilot.py`. Ils ne sont **pas supprimés** : ils restent la référence de décodage **local**
contre laquelle la recette 2.9 compare le décodage réseau, et c'est ce qui sépare « le réseau est
moins bon » de « la séance est moins bonne ». `archive/README.md` gagne leurs trois lignes, et sa
ligne sur `cvep_pilot.py` — *« Calibration is unaffected: it still lives at src/research/app.py »* —
devient fausse et doit être corrigée.

**L'histogramme neuro est porté dans la console**, seul écran pygame sans doublon exact. Sans lui,
« seul point d'entrée » serait faux pour un mode sur six. La page neuro de la console affiche déjà
les indices ; elle gagne leur **histogramme temps réel**. Le calcul ne bouge pas (`NeuroDecoder`,
déjà dans `core`) : c'est un ajout de rendu.

**Les trois calibrations pygame** disparaissent en tant qu'écrans : leur moitié pure monte dans
`core` (§7), leur moitié rendu fusionne dans la fenêtre de `stimulus/` correspondante.

⚠️ **`research/app.py` ne peut pas être supprimé tel quel, et l'ordre compte.**
`archive/cvep_pilot.py:34` et `archive/cvep_rcca_pilot.py:37` importent `Live, _live_loop,
_running, _vote` de lui, et `archive/README.md` promet que ces fichiers tournent encore. Donc :
**d'abord** la machinerie pygame partagée déménage dans `research/ui.py` (qui porte déjà `App` et
`Abort`) et les imports de l'archive suivent ; **ensuite seulement**, le fichier vidé — un menu sans
page — est supprimé. Les sept `--smoke` de `archive/` sont le contrôle de cette bascule. Le paquet
`research/` garde ses analyses, ses protocoles chiffrés (`ssvep_guided.py`, `alpha_check.py`) et
`ui.py`.

**Un raccourci Windows** ouvre la console sans terminal. C'est la dernière ligne de commande du
parcours utilisateur.

## 11. Les tests

Tout headless, sans casque, un autotest par module comme partout ailleurs ; sortie 1 en cas
d'échec ; **aucun test n'écrit dans le vrai `data/`** (garde `empreinte_dossier`, déjà en place).

**LE test qui porte le chantier** — l'accord des deux épochages. Une calibration jouée sur des
marqueurs synthétiques, un décodage joué sur les **mêmes** marqueurs et le **même** signal, et
l'assertion que les époques prélevées sont **identiques à l'échantillon près**. Il doit rougir sur
une mutation d'un seul échantillon de décalage. Sans lui, ce chantier remplace deux chemins non
vérifiés par un chemin non vérifié.

Les autres, par module :

- `core/modes/marker_calib.py` — les trois causes d'abandon, le refus d'entraîner une séance
  tronquée, l'ignorance des marqueurs hors calibration, la forme du `snapshot`.
- `core/modes/{p300,errp,cvep}_calib.py` — l'accuracy honnête (CV groupée par essai), le candidat
  écrit **hors** de `data/`, le refus d'écraser.
- `core/modes/contract.py` — `kind` ∈ {moteur, fenetre}, `stimulus_id` obligatoire si `fenetre`,
  `key_channels` exposées.
- `core/server.py --smoke` — la frontière étendue (§3), les commandes `save_calibration` et
  `discard_calibration`, le nettoyage inconditionnel du temporaire.
- `console/app.py --smoke` (Qt offscreen) — le contrôle de liaison qui refuse, le verdict avec
  Refaire/Enregistrer, le lancement **simulé** (aucun vrai processus dans le smoke), le refus d'un
  second lancement, l'histogramme neuro.
- `stimulus/{p300,errp,cvep}.py --smoke` — leurs assertions actuelles de justesse à la frame
  étendues au mode calibration, et la vérité-terrain publiée conforme à ce qui est **affiché**.
  Celui du c-VEP reste le plus sévère : la phase lue dans les **pixels**, zéro frame d'écart.
- `archive/*.py --smoke` — les quatre existants plus les trois nouveaux arrivants, toujours verts.

## 12. Découpage indicatif

Ordre choisi pour que le **P300 éprouve le mécanisme avant qu'il ne soit recopié deux fois** : c'est
le mode à marqueurs le mieux connu, validé au casque par l'ancien chemin, et le seul qui porte déjà
un test d'alignement.

1. Le paquet `src/stimulus/` : déménagement des trois émetteurs, `refresh.py`, `registry.py`,
   frontière AST étendue.
2. Le contrat : `kind`, `stimulus_id`, `key_channels`, disparition de `reason`.
3. `MarkerCalibrationRuntime` + **le test d'accord des épochages**.
4. Le P300 de bout en bout : entraîneur dans `core`, `--calibrer` dans la fenêtre, marqueurs.
5. La console : lancement de fenêtre, contrôle de liaison, les deux boutons.
6. La garde de sauvegarde : temporaire, `save_calibration`, `discard_calibration` — MI compris.
7. L'ErrP de bout en bout.
8. Le c-VEP de bout en bout.
9. L'histogramme neuro porté dans la console.
10. Les retraits : trois écrans vers `archive/`, machinerie vers `research/ui.py`, `app.py`
    supprimé.
11. Le raccourci Windows.
12. La documentation : `docs/markers.md` (contrat public, en anglais), `CLAUDE.md`, `README.md`,
    `docs/recette.md`, `docs/SPEC.md`, `archive/README.md`.

## 13. Ce qui reste DEHORS

- **La séance casque.** Elle suit ce chantier et le vérifie. Tous les modèles y seront réentraînés
  depuis l'interface : la calibration fait partie de ce qui est éprouvé.
- **Le lot d'affichage parké depuis le 2026-08-17** : tracés du brut qui se chevauchent, aide grise
  tronquée, refus silencieux depuis la grille (test 1.13). Sans rapport avec ce chantier — sauf le
  refus silencieux, dont le remède est la même leçon.
- **Toute nouvelle capacité de décodage.** Aucun mode nouveau, aucun décodeur nouveau, aucun seuil
  rouvert.
- **Le portage des écrans archivés vers autre chose.** Ils restent en pygame, non maintenus, et
  c'est leur rôle.

## 14. Contraintes qui lient tout le chantier

- `core` n'importe ni `research`, ni `console`, ni `stimulus` ; ni pygame ni Qt. `stimulus`
  n'importe ni `research` ni `console`. **Vérifié par le scanner AST de `server.py --smoke`**, pas
  par la discipline.
- **La console est un client** : aucune logique que le moteur ne possède déjà, aucun catalogue
  recopié, **aucune écriture disque**. Ce qu'elle lance est déclaré par `stimulus/registry.py` ; ce
  qu'elle affiche vient de `snapshot()`.
- Une fenêtre de `stimulus/` **n'ouvre jamais le casque**. C'est ce qui lui permet de tourner à côté
  du moteur, et c'est déjà vrai des trois aujourd'hui.
- Code et commentaires **en français** ; `README.md`, `docs/markers.md` et les messages de commit
  **en anglais** ; `CLAUDE.md`, `docs/SPEC.md`, `docs/recette.md` en français.
- Tout testable **sans casque**. Aucun test n'écrit dans le vrai `data/` — enregistrements EEG d'une
  personne identifiable, dépôt public. `git status` ne prouve rien (`data/` est gitignoré) :
  vérifier par **empreinte**.
- Un seul programme du projet à la fois pendant les tests — les noms de flux sont un contrat public.
  Les fenêtres de `stimulus/` restent l'exception, par construction.
- **La contrainte est le TEMPS**, pas le coût. ~40 Ko de diff au maximum par sous-agent.
