# EEG_API_Unicorn — Spécification

> Document de conception (français, interne). Le README et la doc destinés aux étudiants seront en
> anglais. Version : brouillon 0.2 (2026-07-24). À valider avant implémentation.
>
> **Nom du produit : EEG_API_Unicorn** — dépôt, dossier, flux et documentation portent ce nom.
> Préfixe des flux LSL : `EEG_API_Unicorn_*` (s'il s'avère trop verbeux dans le code client, il peut être
> raccourci — mais **avant** toute diffusion aux étudiants, cf. §12.3).

## 1. But et public

Fournir aux étudiants d'une école d'ingénieurs un **serveur de signal BCI** prêt à l'emploi :
un casque **Unicorn Hybrid Black** est acquis et décodé par l'outil, et le résultat est **diffusé sur
le réseau** pour être consommé par n'importe quelle application externe (Unity, Python, MATLAB, web).

L'étudiant lance l'API, **calibre** une fois si le mode l'exige, puis **streame** ; son application
récupère le flux décodé et construit dessus.

L'outil est **générique et agnostique de l'application avale** : il produit un signal cérébral décodé,
il ne sait pas ce qu'on en fait (jeu, visualisation, domotique, robot…). Un pilotage de robot mobile a
servi de **banc d'essai** au décodage ; ce n'est **pas** un objectif du produit et rien dans l'API ne
doit en dépendre.

## 2. Principes directeurs

1. **Le décodé d'abord.** Le produit principal, ce sont les sorties des modes (SSVEP, MI, P300…) en
   boîte noire. Le signal brut est aussi exposé, mais en second.
2. **Un protocole standard : LSL** (Lab Streaming Layer). Clients tout-langage, horodatage sub-ms,
   horloge partagée, multi-clients, métadonnées auto-documentées.
3. **Moteur découplé de toute interface.** Le cœur (acquisition → traitement → diffusion) tourne
   **sans GUI** (mode serveur/headless). Toute interface — l'actuelle, la future, ou du code étudiant —
   n'est qu'un **client**.
4. **Unicorn uniquement.** 8 voies fixes, montage fixe (Fz, C3, Cz, C4, Pz, PO7, Oz, PO8), 250 Hz.
   Pas d'abstraction multi-casque : moins de code, plus robuste.
5. **Simple et opinionated.** Ce n'est PAS un framework généraliste (OpenViBE / BCI2000 / Timeflux
   existent). La valeur = Unicorn + modes déjà faits + exemples clairs.
6. **Calibration native standardisée, runtime flexible** (voir §6–7).

## 3. Architecture

```
        Unicorn  --BrainFlow-->  Acquisition (8 voies, 250 Hz, µV, horodatées)
                                     |
                                     |-- Filtres (par mode)
                                     |-- Décodeurs (SSVEP / MI / c-VEP / P300 / neuro / ErrP)
                                     |        ^ modèle calibré (par étudiant, par mode)
        =====================  MOTEUR (headless-capable)  =====================
                                     |
   DATA PLANE (sortant, LSL)         |   CONTROL PLANE (entrant, LSL)    MARKERS IN (entrant, LSL)
     - eeg_raw   8ch @250Hz          |     start/stop mode               onsets stimulus envoyés
     - decoded_<mode> (bas débit)    |     lancer une calibration        par l'appli externe
     - quality   (santé des voies)   |     choisir la config             (modes évoqués : P300…)
     - status    (mode, calibré ?)   |            |
     - markers   (événements API)    |            v
                                     |     API de commande INTERNE  <-- aussi appelée par le
                                     |     (start/stop/calibrate/…)     tableau de bord web
        Clients : Unity (LSL4Unity, C#) · Python (pylsl) · MATLAB · tableau de bord web
```

- Le **moteur** est le code que les étudiants liront et étendront → c'est lui qu'on nettoie/commente.
- Les commandes (LSL ou tableau de bord) convergent vers **une seule API de commande interne** : un seul
  chemin à tester, et le protocole de contrôle reste remplaçable (§12.1).
- L'**interface** (pygame actuel, futur tableau de bord web) est un client : contrôle + calibration +
  stimulus natif.
- **Sorties applicatives = hors du cœur.** Traduire un flux décodé en action (commande de robot, touche
  de clavier, événement de jeu…) est le travail de l'application avale, **pas** de l'API. L'émetteur
  UDP-JSON existant devient donc un simple **exemple** (§9), utile à qui veut recevoir sans dépendance.

### 3.1 Où vit le code (`core/` vs `research/`) — fait le 2026-07-27

Le schéma ci-dessus se lit directement dans l'arborescence, sur un critère **vérifiable** plutôt
qu'un jugement : **un module est dans `src/core/` si et seulement si `server.py` en a besoin pour
tourner.** Tout le reste est dans `src/research/`.

```
src/core/       config · acquisition · cca_decoder · lsl_io · neuro_monitor · server · modes/
src/console/    la console PySide6 : app · banner · grid · mode_page · params_form · live_views
src/research/   app + ui + stimulus · décodeurs des modes non publiés · calibrations · analyses
```

Deux règles en découlent, et elles sont ce qui empêche la frontière de s'effacer avec le temps :

1. **`core` n'importe jamais `research`** (l'inverse est permis). Le jour où l'envie s'en présente,
   c'est le signe que le module visé a fini de mûrir : il **déménage** dans `core`. C'est la
   définition opérationnelle de « publier un mode » (§10, incréments v1/v2) — on ne tire pas un fil
   à travers la frontière. La restructuration a d'ailleurs révélé une telle arête : `acquisition.py`
   importait `controller.run_live` pour une démo joystick, vestige du banc d'essai robot ; la démo a
   été supprimée (`controller.simulate()` couvre déjà ce câblage).
2. **Aucun pygame dans `core`** : le moteur doit tourner sur une machine sans écran.

`research` ne veut pas dire « brouillon » — le P300 et le c-VEP y sont validés sur casque. Ça veut
dire que le moteur ne les publie pas encore, donc qu'ils ne font pas partie du contrat rendu aux
étudiants.

Corollaire pratique : les chemins du dépôt (`PROJECT_ROOT`, `DATA_DIR`, `EXAMPLES_DIR`) sont
**centralisés dans `core/config.py`**. Ils étaient auparavant recalculés à la main dans dix modules
par `dirname(dirname(__file__))` — après déplacement, les dix auraient silencieusement pointé sur
`src/` au lieu de la racine.

**Depuis le 2026-07-28, il y a un troisième paquet : `src/console/`** (la console PySide6). La
règle ne change pas, elle s'étend : `console` importe `core`, et `core` n'importe **ni `research`,
ni `console`, ni pygame, ni Qt**. Le moteur doit continuer à tourner sur une machine sans écran.
C'est vérifié par un test, pas par la discipline : `python src/core/server.py --smoke` scanne
`src/core/**/*.py` et échoue sur le moindre import interdit.

`src/core/modes/` est arrivé en même temps : un mode y est un **contrat** (`ModeSpec` : ce qu'il
est, ce qui s'y règle, ce qu'il publie) posé à côté de son **runtime**. L'algorithme reste
séparé — `cca_decoder.py` est une CCA, indifférente au produit ; `modes/ssvep.py` est le mode.
C'est ce contrat qui génère la grille de la console, ses formulaires de réglages et l'extrait de
code client : aucun de ces trois ne recopie de catalogue, donc aucun ne peut vieillir séparément.

## 4. Les flux (contrat d'API)

Noms de flux LSL préfixés `EEG_API_Unicorn_`. **Contrat stable** : un client ne doit pas casser si on ajoute
un champ. Métadonnées (noms de voies, unités, fréquence) portées par le flux.

| Flux (type LSL) | Sens | Contenu | Débit |
|---|---|---|---|
| `EEG_API_Unicorn_raw` (EEG) | sortant | 8 voies µV **non filtrées**, float32 + timestamps | 250 Hz |
| `EEG_API_Unicorn_decoded_<mode>` | sortant | sortie du mode (voir §5) | ~5 Hz ou événementiel |
| `EEG_API_Unicorn_quality` | sortant | σ + verdict par voie (ok/douteux/mort) | ~1 Hz |
| `EEG_API_Unicorn_markers` | sortant | événements API (mode changé, calib début/fin) | événementiel |
| `EEG_API_Unicorn_status` | sortant | état du moteur (mode actif, calibré ou non, prêt) | ~1 Hz + à chaque changement |
| `EEG_API_Unicorn_control` | entrant | commandes vers le moteur (start/stop, calibrer, config) | événementiel |
| `EEG_API_Unicorn_stim` | entrant | marqueurs de stimulus depuis l'appli externe (modes évoqués) | événementiel |

**Contenu du flux `status`** (JSON, un message par changement d'état). Amendé le **2026-07-28** avec
le passage au moteur multi-modes :

| Champ | Contenu |
|---|---|
| `running` · `board` · `instance` | le moteur tourne ; `unicorn` ou `synthetic` ; quelle instance |
| `fs_hz` · `channels` | 250 Hz, et les 8 noms de voies |
| `mode` | le premier mode **décodé** actif, ou `null` — conservé pour les clients d'hier |
| `modes` | **la vérité complète** : tous les modes actifs, `raw` compris |
| `phase` | `streaming` · `warmup` · `baseline` · `decoding` — vocabulaire public inchangé |
| `samples_published` · `streams` | compteur, et les noms complets des flux réellement publiés |
| `instruction` | la consigne de repos, **seulement pendant `warmup` / `baseline`** |

⚠️ **Trois champs ont été RETIRÉS** en même temps, et c'est un changement de contrat assumé :

- `frequencies_hz` et `indices` : ils décrivaient les cibles SSVEP, donc un seul mode. Avec plusieurs
  modes actifs à la fois, un champ de premier niveau nommé d'après l'un d'eux n'a plus de sens. Ces
  informations n'ont pas disparu — elles sont dans les **métadonnées du flux `decoded_ssvep`** (où
  elles étaient déjà) et dans `modes_state` côté console.
- `instruction` **pendant la phase de décodage** : elle y restait affichée alors qu'il n'y avait plus
  rien à faire, ce qui laissait croire qu'un repos était en cours.

Un client qui lisait ces champs doit lire les métadonnées du flux décodé à la place. C'est le seul
endroit où ce chantier casse le contrat public, et il est cassé sciemment plutôt que rapiécé.

**Décidé : TOUT passe par LSL** — données ET commandes (§12.1). Une seule dépendance, un seul concept à
enseigner, et le client Unity/Python n'apprend qu'une API.

Conséquences à connaître (LSL est conçu pour *streamer*, pas pour du requête/réponse) :

- **Pas d'accusé de réception.** Une commande est *fire-and-forget* : le client envoie sur
  `EEG_API_Unicorn_control`, puis **observe le résultat** sur `EEG_API_Unicorn_status`. D'où l'ajout du flux `status`
  ci-dessus — sans lui, un client ne saurait pas si sa commande a été prise en compte.
- **Commandes = messages JSON** dans un flux de marqueurs (chaîne unique), ex. `{"cmd":"start","mode":"ssvep"}`.
- **Pas de client LSL depuis un navigateur** (liblsl est une bibliothèque native, sans binding JS) : une
  interface web doit donc être servie par le moteur lui-même, qui fait le pont (§12.2).
- ✅ **RISQUE LEVÉ ENTRE DEUX MACHINES (2026-07-27)** : découverte ET transfert validés d'un poste à
  l'autre, sans configuration particulière. Latence bout-en-bout de quelques dizaines de ms, très en
  dessous des fenêtres de décision (1-2 s). ⚠️ Un piège confirmé au passage : `local_clock()` compte
  depuis le démarrage de CHAQUE machine, donc un écart de plusieurs SEMAINES entre deux postes est
  normal — il faut appliquer `time_correction()` à tout horodatage distant, sans quoi les dates sont
  absurdes. C'est précisément le service que LSL rend et qui justifie le choix. Cf. [docs/network.md](network.md).
- ⚠️ **Risque réseau école (historique)** : LSL découvre les flux par **multicast UDP**, que des pare-feux ou des réseaux
  de campus verrouillés peuvent bloquer. En local (même machine) c'est en général transparent ; entre deux
  machines, prévoir une doc « autoriser l'appli dans le pare-feu » et, si besoin, la configuration des pairs
  connus de LSL. **À tester tôt sur le réseau de l'école.** → procédure et contournement écrits :
  [docs/network.md](network.md). Le test ne demande **pas le casque** (`--synthetic` suffit), donc il peut
  être fait avec deux portables quelconques avant d'être en salle.
- **Mesuré en local le 2026-07-27** (poste de dev Windows 11, `pylsl` 1.18.2) : `pip install pylsl` fournit
  une roue `win_amd64` avec `liblsl` embarqué — **aucune installation supplémentaire côté étudiant**.
  Découverte d'un flux par son nom en **0,04 s**, décalage d'horloge **−0,01 ms**, **0 échantillon perdu**
  sur 8 voies à 250 Hz, latence bout-en-bout médiane **0,16 ms** (p95 0,32 ms). ⚠️ **Ceci ne teste que le
  localhost** : le multicast entre deux machines sur le réseau de l'école reste à vérifier sur place.
- ⚠️ **Piège à documenter pour les étudiants** : un `StreamInlet` n'ouvre sa connexion qu'au premier `pull`,
  et LSL **ne rejoue jamais** ce qui a été publié avant. Sans `inlet.open_stream()` explicite, un client
  perd la première seconde de signal — silencieusement.

> **Porte de sortie assumée** : si le tout-LSL se révèle pénible (contrôle sans réponse, blocage réseau,
> friction d'installation), le control plane peut être remplacé par une petite **API WebSocket/JSON** sans
> toucher aux flux de données. C'est pour cela que le moteur expose une **API de commande interne** dont
> l'entrée LSL n'est qu'un *adaptateur* : en changer ne réécrit pas le moteur (§12.1).

## 5. Format des sorties décodées, par mode

| Mode | Type | Sortie décodée (`decoded_<mode>`) |
|---|---|---|
| **SSVEP** | évoqué | `{target_index, freq_hz, confidence, scores[]}` — **implémenté** ; flux numérique, `target_index = -1` quand aucune cible n'est fixée de façon fiable. Les métadonnées portent `decision_scale` (`z` après mesure du repos, sinon `rho`) et le seuil : sans cette indication, un seuil posé côté client n'a aucun sens. |
| **Motor Imagery** | endogène | `{intent_index, confidence, p_GAUCHE, p_DROITE, p_REPOS}` — **implémenté** (2026-07-30). ⚠️ `intent_index = -1` (« le vote glissant n'a pas conclu ») et l'indice de **REPOS** (« le modèle a décidé que la personne se repose ») sont **deux choses différentes** : pour une application, c'est la différence entre « attends » et « arrête ». Les voies sont dérivées des **classes du modèle chargé**, pas d'une liste figée. Métadonnées : `decision_scale = "proba"`, plus le seuil et les paramètres du vote. ⚠️ Exige un **modèle entraîné par personne** ; le mode refuse de démarrer sans, en le disant. Mesuré honnêtement (validation croisée groupée par essai, 1 personne, 1 séance) : **63 % en gauche-vs-droite** (hasard 50 %, p = 0,038), 40 % à trois classes (hasard 33 %, non significatif). Démonstrateur, pas pilotage fin. |
| **P300** | évoqué | `{target_index, confidence, n_flashes, score_0…score_5}` — **implémenté** (2026-08-17). Événementiel : **un échantillon par manche**, pas un débit régulier — un client qui attend 5 Hz attend pour rien. ⚠️ `target_index = -1` signifie « pas de décision », **jamais la cible 0** ; les métadonnées portent `no_decision_index` pour qu'un client non-Python puisse le lire sans ouvrir le code. `confidence` = log-odds moyens du gagnant : non bornés, non comparables entre personnes, d'où `decision_scale = "logodds"` dans les métadonnées. ⚠️ **Exige des MARQUEURS ENTRANTS** — avec l'ErrP, les deux seuls : l'application externe affiche les flashs et déclare l'onset de chacun — contrat public dans [markers.md](markers.md). ⚠️ Exige aussi un **modèle entraîné par personne** (calibration dans l'appli pygame ; AUC mesurée 0,71 en validation croisée par manche, 1 personne, 1 séance). |
| **Neuro-monitoring** | passif | `{charge, somnolence, engagement, artifact}` — **implémenté** (2026-07-27). z relatifs à un repos mesuré **en début de mode, pour cet utilisateur, ce jour-là** : les valeurs ne se comparent ni entre personnes, ni entre séances, et n'ont aucun sens absolu. `artifact = 1` republie les derniers z valides plutôt que des indices calculés sur un clignement — ceux-ci seraient plausibles, donc indétectables en aval. ⚠️ Plomberie testée, **contenu jamais validé sur casque**. |
| **ErrP** | passif | `{error, score, threshold, artifact}` — **implémenté** (2026-08-19). Un échantillon par marqueur `feedback`, cadence irrégulière. ⚠️ `error = -1` signifie « pas de verdict » (époque hors tampon, ou rejetée pour artefact — un clignement au moment où la machine se trompe est le cas FRÉQUENT), **jamais** « pas d'erreur ». ⚠️ **Les métadonnées portent le POINT DE FONCTIONNEMENT mesuré** (`tnr_target`, `tpr_measured`, `tnr_measured`) : au réglage par défaut ce détecteur attrape **une erreur sur deux** et annule une bonne commande sur sept — une application qui lit `error = 1` doit pouvoir le savoir sans lire le code. Le seul réglage est un **taux** (« quelle part des bonnes commandes garder »), dont le moteur déduit le seuil sur les scores hors-pli de la calibration de la personne. ⚠️ **Le moteur PUBLIE, il n'annule rien** : la période réfractaire et la décision d'annuler appartiennent au client. Mesuré honnêtement (CV groupée par bloc, 200 essais, 1 personne, 1 séance) : **AUC 0,776, p = 0,0099 sur 100 permutations** — le mieux validé des modes, devant le P300 (0,714). ⚠️ **Mais `tpr_measured`/`tnr_measured` sont OPTIMISTES et le flux le dit** (`measured_on`) : l'AUC vient de scores hors-pli, le **seuil** est choisi en les regardant, donc `tnr_measured ≥ tnr_target` est vrai *par construction* sur la calibration et pas en séance. Un client qui règle sa politique d'annulation sur ces deux nombres observera **plus** de faux vetos que promis. ⚠️ Exige lui aussi un **modèle entraîné par personne** (calibration dans l'appli pygame) ; le mode refuse de démarrer sans, en le disant. ⚠️ **Exige des MARQUEURS ENTRANTS**, comme le P300 et par le même tuyau — un seul événement, `feedback`. |
| **c-VEP** | évoqué | `{target_index, confidence}` — **stimulus natif au MVP** |

Chaque mode publie **une intention neutre** (quelle cible / quelle classe / quel état), jamais une commande
d'actionneur. La conversion en action appartient à l'application avale : c'est ce qui rend le même flux
utilisable par un jeu, une visualisation ou un robot sans rien changer côté API.

**Actif vs passif : un client ne doit pas les traiter pareil.** SSVEP, c-VEP, P300 et MI sont *actifs* —
l'utilisateur CHOISIT, il existe une bonne réponse, et (sauf MI) un stimulus est requis côté client. Le
neuro-monitoring est *passif* : on observe un état, il n'y a rien à choisir, aucun stimulus, et donc ni
justesse ni erreur à mesurer. Traiter un indice passif comme une sélection est le contresens à éviter
en premier.

L'**ErrP est passif lui aussi** — on observe une réaction, l'utilisateur ne choisit rien — mais c'est le
seul passif qui **dépend quand même d'un stimulus côté client** : sans feedback affiché ni marqueur, il
n'a rien à juger. Il ne rentre proprement dans aucune des deux moitiés, et c'est normal : la coupure
utile pour un client n'est pas « actif/passif » mais « dois-je afficher quelque chose et le déclarer ? ».
Réponse oui pour SSVEP, c-VEP, P300 et ErrP ; non pour le MI et le neuro.

C'est pourquoi les métadonnées portent `paradigm`, et il en existe **cinq** valeurs, pas deux :
`SSVEP`, `neuro-passive`, `motor-imagery`, `P300`, `ErrP`. Un client qui filtre sur ce champ doit les
connaître toutes, sans quoi il ignorera en silence un flux qu'il croit écouter.

**Le réglage SSVEP dépend de la personne, pas seulement de l'écran.** Les fréquences des cibles
doivent être des **diviseurs entiers du rafraîchissement de l'écran qui affiche le stimulus** (à
60 Hz : 30, 20, 15, 12, 10, 8,571 Hz…) — sinon l'affichage saute des cycles et le décodeur corrèle
contre une sinusoïde que personne n'affiche, sans la moindre erreur pour le signaler. Une fois ce
filtre passé, la proposition automatique de fréquences (réglage `refresh_hz` ou `alpha_hz` →
`freqs`) s'écarte en plus du **pic alpha de la personne** : ce pic varie fortement d'un individu à
l'autre (moyenne de population ≈ 9,6 Hz, plage 7-13 Hz) et une cible posée dessus ne se distingue
pas du bruit de fond au repos. Conséquence directe : **un jeu de fréquences qui marche pour une
personne peut échouer pour la suivante.** Un enseignant ne doit donc jamais distribuer un réglage
unique à toute une promotion sans le dire — chacun doit régler `alpha_hz` sur son propre pic
(mesurable avec `python src/research/alpha_check.py`) et laisser la console lui proposer son propre
jeu de fréquences.

## 6. Calibration

**Par défaut : calibration NATIVE et standardisée, possédée par l'API** (les écrans de calibration
actuels). Justification : la calibration exige une **vérité-terrain sous protocole contrôlé** (timing
maîtrisé, labels fiables) — on ne veut pas que chaque étudiant la réimplémente de travers.

- L'étudiant fait **une fois** `calibrer <mode>` (fenêtre native) → un **modèle** est sauvegardé.
- Modèles rangés dans `models/` (hors git), nommés par étudiant/mode ; l'**état** (calibré ou non) est
  exposé (control/quality) pour que l'appli externe sache si un flux est prêt.
- **Modes sans calibration** : SSVEP (juste un repos court pour caler les seuils), neuro-monitoring
  (repos de référence). **Modes avec calibration** : MI, c-VEP, P300, ErrP (par personne, quelques min).
- ⚠️ **Cohérence calibration ↔ runtime** : pour les modes évoqués, le décodeur est un peu accordé au
  stimulus de calibration. L'API publie donc une **« spec de stimulus » par mode** (fréquences
  autorisées, rythme des flashs, format des marqueurs) que l'appli externe doit respecter au runtime.

## 7. Stimulus : natif vs externalisé

Le stimulus (cibles clignotantes) peut vivre **dans l'API** (fenêtre native, timing garanti) ou **dans
l'appli externe** (ex. Unity). La faisabilité dépend du couplage temporel du mode :

| Mode | Stimulus dans l'appli externe ? | Ce que l'appli fournit |
|---|---|---|
| **MI / neuro** | sans objet (endogène) | rien |
| **SSVEP** | oui, facile | déclare le **set de fréquences** une fois (couplage lâche, pas de sync frame) |
| **P300 / ErrP** | oui, moyen | un **marqueur horodaté par événement** (flash / feedback) via `EEG_API_Unicorn_stim` |
| **c-VEP** | non (MVP) | sync frame-par-frame trop serrée → **rendu natif** par l'API |

**Mécanisme clé = le marqueur** : un message horodaté « événement X à l'instant T » que l'appli publie ;
grâce à l'horloge partagée LSL, le moteur aligne l'EEG sur l'événement au ms près, épocher, décoder.

## 8. Dépendances et installation

- `requirements.txt` : `brainflow`, `numpy`, `scipy`, `scikit-learn`, `pyriemann`, `pylsl`, `pygame`,
  `joblib`, + l'interface de la console (`PySide6` + `pyqtgraph`). `fastapi`/`uvicorn` ne sont plus
  requis depuis la suppression du tableau de bord web (§12.2).
  Installation automatique : `pip install -r requirements.txt` (idéalement `pip install -e .`).
- `pylsl` embarque `liblsl` via pip sur la plupart des plateformes (**à vérifier sur les postes de l'école**,
  avec le test pare-feu/multicast du §4).
- Côté élève consommateur : **rien à installer** pour le tableau de bord (navigateur) ; pour son application,
  seulement le client LSL de son langage (`pylsl`, LSL4Unity…).

## 9. Exemples fournis (le vrai facteur d'adoption)

- `examples/receiver.py` — s'abonne à un flux décodé (pylsl) et l'imprime : le « hello world » Python.
- `examples/unity/` — script C# minimal (LSL4Unity) : SSVEP → déplacer un objet dans une scène.
- `examples/actuator_udp.py` — **exemple** de traduction « intention décodée → action » : convertit un flux
  décodé en datagrammes UDP-JSON. Montre le patron « l'action appartient au client », sans dépendance.
  *(hérité du banc d'essai robot ; à généraliser et à débaptiser du vocabulaire « joystick/Waffle ».)*

## 10. Périmètre : MVP puis incréments

**MVP (v0) — le plus vite au contact :**
- Moteur headless + sorties LSL `eeg_raw` + `quality` + `status`.
- `SSVEP_decoded` **sans calibration** (le mode qui marche tout de suite, sans protocole).
- 1 exemple Python + 1 exemple Unity SSVEP (+ l'exemple d'actionneur UDP).

**v1 :** ~~`MI_decoded` (endogène, calibration native)~~ **[fait 2026-07-30 : flux `decoded_mi`
publié ; calibration native ajoutée au moteur le 2026-07-31, cf. §14 moitié B]** · `P300` via
marqueurs entrants · control plane LSL complet (`control` + `status`) · ~~`neuro_decoded`~~
**[fait 2026-07-27]**.

**v2 :** `ErrP` (marqueurs) · ~~tableau de bord web (§12.2)~~ **[fait 2026-07-27, puis SUPPRIMÉ 2026-07-28]** remplacé par la **console d'expérimentation** `src/console/` (PySide6) · évolutions parkées F1/F2 (§13).

## 11. Non-objectifs (assumés, à documenter)

- Pas de multi-casque (Unicorn only). Pas de framework généraliste.
- Pas de temps réel image-par-image : SSVEP/c-VEP/P300 ont des fenêtres de décision de **1–2 s**.
- **1 casque / 1 utilisateur par instance** du moteur.
- Qualité ⇒ garbage-in/garbage-out : le canal `quality` prévient, mais ne corrige pas un mauvais contact.

## 12. Décisions figées (2026-07-24)

### 12.1 Control plane : **tout LSL** ✅

Données **et** commandes passent par LSL. Motif : une seule dépendance, un seul concept à enseigner, une
seule API à apprendre côté client. Conséquences et limites : voir §4.

**Garde-fou d'architecture (important)** : le moteur expose une **API de commande interne** (objet Python :
`start(mode)`, `stop()`, `calibrate(mode)`, `set_config(...)`, `get_status()`). L'entrée LSL n'en est qu'un
**adaptateur**. Si le tout-LSL déçoit, on branche un adaptateur WebSocket/JSON **sans réécrire le moteur**,
et les flux de données ne bougent pas. Cette porte de sortie est un choix de conception, pas un regret.

### 12.2 Interface de contrôle : ~~tableau de bord web servi en local~~ → **console PySide6** ⚠️ RENVERSÉE le 2026-07-27

> **Cette décision a été renversée.** Ce qui suit décrit le choix d'origine et pourquoi il avait
> été fait ; le renversement est en fin de section. Les deux restent ici volontairement : la
> décision web était bien argumentée et pourrait redevenir la bonne le jour où le suivi à
> distance comptera plus que le tracé temps réel.

Recommandation retenue (critère demandé : le plus **ergonomique** et le plus **simple à installer** pour
l'élève). Le moteur sert une page web ; l'élève ouvre `http://localhost:<port>`.

| Option | Installation | Ergonomie | Modifiable par un élève |
|---|---|---|---|
| **Web local (retenu)** | rien à installer côté élève (le navigateur existe déjà) | familière : tout le monde sait utiliser une page web | HTML/CSS/JS : la techno la plus connue des étudiants |
| Qt (PySide6) | binaire lourd (~100 Mo), soucis d'install selon OS | correcte, look natif | verbeux, peu connu des élèves |
| Dear PyGui | pip, léger | correcte | paradigme peu connu |
| pygame (actuel) | déjà là | **mauvaise** pour des formulaires/listes | tout est à coder à la main |

Bénéfices concrets du web local :
- **zéro installation supplémentaire** pour l'élève (pas de toolkit natif à déployer en salle TP) ;
- **contrôle à distance possible** : l'encadrant peut suivre la qualité du signal depuis un autre poste
  pendant que l'élève porte le casque (vrai gain pédagogique) ;
- **le plus facile à faire évoluer** par les élèves eux-mêmes (HTML/CSS/JS).

Contreparties assumées :
- **le stimulus reste natif** (fenêtre pygame, verrouillée à la frame) : un navigateur ne garantit pas le
  timing du clignotement. Il y aura donc **deux fenêtres** : le tableau de bord (navigateur) et l'écran de
  stimulus/calibration (natif). C'est inhérent à la contrainte temporelle, pas au choix du web ;
- le navigateur **ne parle pas LSL** : le tableau de bord dialogue avec le moteur qui le sert, lequel
  applique les commandes via l'API interne (§12.1) — le même chemin que les commandes LSL externes.

**Techno RETENUE (implémentée 2026-07-27)** : Python + **FastAPI/uvicorn**, page `/docs` interactive
offerte. Rafraîchissement par **sondage** à 4 Hz : l'état complet tient en ~1 Ko et ne change qu'à
1-5 Hz, un WebSocket n'aurait ajouté qu'une reconnexion à gérer. La page est un **fichier séparé**
(`src/core/dashboard.html`), relu à chaque requête, pour qu'un étudiant l'édite et rafraîchisse sans
redémarrer le moteur ni rouvrir la session casque.

Le navigateur ne parle pas au moteur directement : ses commandes passent par l'**API de commande
interne** (§12.1), qui les met en FILE pour que la boucle du moteur les applique elle-même. La session
BrainFlow n'est donc touchée que par un seul thread, et `/api/command` répond un **accusé**, pas un
résultat — exactement comme un client LSL devra observer l'effet sur `status`. Les deux chemins de
contrôle se comportent pareil, ce qui évite qu'une interface prenne l'habitude d'un confort que
l'autre n'offre pas.

**Contenu du tableau de bord** : qualité des 8 voies en direct · choix du mode · **choix des fréquences
SSVEP** · état « calibré / non calibré » par mode · bouton de calibration · sortie décodée en direct ·
flux LSL publiés (noms/état).

#### Commandes exposées (API interne, §12.1)

| Commande | Paramètres | Effet |
|---|---|---|
| `set_mode` | `mode` (`"ssvep"` / `null`), `freqs` ou `refresh` | change de mode ; relance chauffe + repos |
| `set_freqs` | `freqs` (liste en Hz) ou `refresh` | change les cibles décodées (voir ci-dessous) |
| `recalibrate` | — | refait chauffe + repos, sans rien changer d'autre |
| `stop` | — | arrête le moteur |

**`set_freqs` a deux conséquences qu'on assume plutôt que de les masquer :**

1. **Le flux `decoded_ssvep` est RECRÉÉ.** Les fréquences ne sont pas un réglage interne : elles
   nomment les voies du flux (`score_15Hz`) et figurent dans ses métadonnées, or **les métadonnées
   LSL sont figées à la création**. Conserver l'ancien flux publierait des étiquettes fausses. Les
   clients connectés doivent donc **se réabonner** — le NOM du flux ne change pas, un nouveau
   `resolve_byprop` suffit.
2. **Le plancher de repos repart.** Il est mesuré *par fréquence* ; le réutiliser après changement
   comparerait le ρ d'une cible au bruit de fond d'une autre.

C'est aussi la seule commande **validée à la soumission** plutôt qu'à l'application : un jeu de
fréquences hors bande passante, ou dont deux cibles sont plus proches que la résolution `1/WINDOW_S`,
est refusé **avec sa raison**. Sans ça, le mode de panne serait le pire du SSVEP — aucune erreur,
seulement un décodage qui ne détecte jamais rien, indiscernable d'un utilisateur qui fixe mal.

#### Renversement (2026-07-27) : Python + PySide6

Le tableau de bord web a été implémenté, utilisé, et écarté après usage. Le cadrage du produit a
changé en même temps : d'un **moteur qui diffuse** avec une interface en périphérie, on passe à une
**console d'expérimentation** où la diffusion réseau devient une sortie parmi d'autres, activable
mode par mode. Conception complète :
[docs/superpowers/specs/2026-07-27-console-experimentation-design.md](superpowers/specs/2026-07-27-console-experimentation-design.md).

**Ce qui est perdu, et assumé :**
- **l'installation zéro** — PySide6 ajoute ~100 Mo aux dépendances ;
- **le suivi à distance** — plus d'encadrant observant la qualité du signal depuis un autre poste ;
- **la modifiabilité par un élève** — Qt est moins connu que HTML/CSS/JS, ce qui était l'argument
  numéro un du choix web.

**Ce qui est gagné :** un seul langage ; le tracé EEG temps réel devient facile au lieu d'être un
chantier ; et surtout **les consignes de calibration et le stimulus local peuvent vivre dans la
même application**, ce qui supprime la couture « navigateur pour le MI, fenêtre native pour le
c-VEP » que la section ci-dessus assumait comme inhérente.

`src/core/dashboard.py` et `src/core/dashboard.html` sont **supprimés**. Le travail moteur du
2026-07-27 reste intégralement : la validation déclarée des réglages, le flux `decoded_neuro`, le
correctif NaN→null. Seul le rendu HTML est parti.

#### Commandes exposées (API interne, §12.1) — table à jour

| Commande | Paramètres | Effet |
|---|---|---|
| `start_mode` | `id` ou `ids`, `params?` | démarre un ou plusieurs modes ; ceux lancés **ensemble** partagent une seule phase de repos |
| `stop_mode` | `id` | arrête un mode, son flux disparaît du réseau |
| `set_params` | `id`, `params` | valide contre `spec.params`, applique ; **relance le repos** si le mode en a un |
| `propose_params` | `id`, `key` | rend un jeu de valeurs proposé pour le réglage que `key` propose ; **ne l'applique pas** |
| `set_published` | `id`, `on` | publie ou non le flux de ce mode ; le décodage continue pour l'affichage |
| `recalibrate` | `id` | refait chauffe + repos de ce mode seul |
| `stop` | — | arrête le moteur |

`set_mode` et `set_freqs` **n'existent plus** : la première est remplacée par
`start_mode`/`stop_mode`, la seconde par `set_params`. Leurs deux conséquences documentées
ci-dessus (flux recréé, plancher refait) valent toujours, et s'appliquent désormais à **tout**
réglage de **tout** mode, pas seulement aux fréquences SSVEP.

### 12.3 Reste ouvert

- **« Spec de stimulus » P300** (SOA, taille des cibles) : à figer seulement quand on externalisera le P300
  (v1). Sans objet pour le MVP. ✔ accepté tel quel.
- **Nommage définitif des flux et des champs** (contrat public `EEG_API_Unicorn_*`) : à figer à l'implémentation
  du MVP, avant toute diffusion aux étudiants (le renommer après coup casserait leur code).

## 13. Évolutions futures parkées (hors MVP)

- **F1 — c-VEP externalisé** : rendre le stimulus c-VEP dans l'appli externe. Bloqué par le couplage
  frame-par-frame (le décodeur a besoin de la phase exacte du code). À explorer si besoin réel.
- **F2 — calibration externalisée (pilotée par l'app)** : l'appli externe joue le protocole et envoie
  les époques + labels à l'API pour entraîner. Avantage : stimulus calib == runtime (précision max,
  tout dans le jeu). Coût : le dev implémente le protocole → fournir un template/SDK.

## 14. Roadmap / TODO

0. **[fait 2026-07-28]** **Console d'expérimentation** : contrat de mode (`src/core/modes/`),
   moteur multi-modes avec cumul et repos partagé, console PySide6 (grille + page de mode,
   réglages en lecture-écriture, tracés EEG). Tableau de bord web supprimé.
   - **[fait 2026-07-29 — chantier 2]** proposition de fréquences SSVEP accordée au pic alpha de
     la personne (`refresh_hz` propose `freqs`), et refus d'une fréquence qui ne divise pas le
     rafraîchissement déclaré. Conception :
     [docs/superpowers/specs/2026-07-29-proposition-frequences-design.md](superpowers/specs/2026-07-29-proposition-frequences-design.md).
     - **[à faire]** mesurer le pic alpha au casque plutôt que le faire saisir — la vraie bonne
       réponse, écartée pour tenir le chantier court.
     - **[à faire]** réglages des autres modes, quand ils auront un runtime.
   - **[fait 2026-07-30 — chantier 3, moitié A]** le **Motor Imagery est publié par le moteur**
     (`--mode mi` → flux `decoded_mi`) : le décodeur a déménagé dans `core/`, un `MIRuntime` glisse
     une fenêtre de 2 s et vote, et le modèle se choisit dans la console — la liste des modèles
     entraînés est découverte à l'exécution (`Param.choices_fn`). N'importe quel client LSL le
     consomme : Python, MATLAB, C++, un moteur de jeu. Conception :
     [docs/superpowers/specs/2026-07-29-motor-imagery-moteur-design.md](superpowers/specs/2026-07-29-motor-imagery-moteur-design.md).
     ⚠️ **`intent_index = -1` (« le vote n'a pas conclu ») et l'indice de REPOS (« la personne se
     repose ») sont distincts** — pour une application, c'est la différence entre « attends » et
     « arrête ».
     ⚠️ **Les quatre modèles MI d'avant la restructuration sont abandonnés**, par décision : leur
     pickle référence un module disparu. `mi_models.charger` les refuse explicitement, y compris
     quand un accident de chemin d'import les rendrait chargeables.
     - **[fait 2026-07-31 — chantier 3, moitié B]** la calibration Motor Imagery est désormais
       **jouée par le moteur** (`CalibrationRuntime` / `MICalibration` dans `core/modes/`) : la
       console ne fait plus qu'en lancer une séance, l'afficher et en montrer le résultat — plus
       besoin d'un second programme. L'accuracy annoncée à la fin est **honnête** (validation
       croisée groupée PAR ESSAI, jamais par fenêtre) ; ≈ 40 % à 3 classes est un résultat
       **NORMAL** (hasard 33 %), là où l'écran pygame affichait un chiffre gonflé de 10 à 16
       points. Modèle et enregistrement sont **horodatés** : une séance n'écrase plus jamais la
       précédente, contrairement à l'ancien nom fixe (`mi_model.joblib`). Les écrans pygame du MI
       (`mi_calibrate.py`, `mi_pilot.py`) sont **archivés** (`archive/`, encore exécutables via
       `--smoke`) plutôt que supprimés : ils restent la référence contre laquelle vérifier la
       calibration du moteur. **Le chantier 3 est donc TERMINÉ, ses deux moitiés.** Conséquence
       qui en découle sans être livrée : le moteur sachant désormais jouer une calibration de
       bout en bout, l'évolution F2 (§13, « calibration pilotée par l'app externe ») devient
       **atteignable** — mais rien n'expose ce chemin à un client externe aujourd'hui, LSL ne
       transporte toujours pas d'époques.
     - **[à faire — lot séparé]** un exemple de récepteur pour le MI, à écrire quand on saura pour
       quel client il est le plus utile.
   - **[fait 2026-08-17 — chantier « marqueurs entrants »]** **le moteur sait ÉCOUTER**, et le P300
     est publié (`--mode p300` → `decoded_p300`). C'est le premier chantier qui ajoute une entrée
     au moteur plutôt qu'une sortie : `core/markers.py` résout un flux de marqueurs **par son nom**
     (jamais par son type — le flux `status` du moteur est lui-même de type `Markers`, il
     s'écouterait lui-même), le tampon EEG gagne ses **horodatages** sans lesquels aucun marqueur ne
     peut être situé, et une file ne rend un marqueur que lorsque son époque tient entièrement dans
     le tampon. Le décodeur P300 a **déménagé** dans `core/` et son modèle a été **ré-entraîné**
     depuis les époques conservées plutôt que rattaché par une passerelle — le pickle référençait un
     module qui n'existe plus, exactement ce qui avait coûté les 4 modèles MI. L'AUC ré-obtenue est
     **identique bit pour bit** à celle de juillet. Conception :
     [docs/superpowers/specs/2026-08-17-marqueurs-entrants-p300-design.md](superpowers/specs/2026-08-17-marqueurs-entrants-p300-design.md).
     Contrat public des marqueurs : [docs/markers.md](markers.md).
     - **[fait 2026-08-19 — chantier « l'ErrP sur le réseau »]** l'**ErrP est publié**
       (`--mode errp` → `decoded_errp`), **5e mode sur 6**. Le tuyau des marqueurs a été réutilisé
       sans rien redécouvrir : il a suffi d'ajouter un événement au contrat public.
       ⚠️ **La dette qu'on croyait ouverte ne l'était pas** : la calibration réelle DATAIT du
       2026-07-24 et son résultat n'avait jamais été lu. Ré-entraîné depuis les époques conservées :
       **AUC 0,776 en validation croisée groupée par bloc, p = 0,0099 sur 100 permutations** — le
       mieux validé de tous les décodeurs du projet. ⚠️ Mais le point de fonctionnement est
       **modeste** : une erreur sur deux attrapée pour une bonne commande sur sept annulée, et il
       n'y a pas de repas gratuit sur la courbe. C'est pourquoi **le flux publie son propre point de
       fonctionnement** dans ses métadonnées : sans ça une application lirait `error = 1` comme un
       verdict. Conception :
       [docs/superpowers/specs/2026-08-18-errp-moteur-design.md](superpowers/specs/2026-08-18-errp-moteur-design.md).
       - **[à faire]** la **calibration ErrP jouée par le moteur** : elle reste dans l'appli pygame,
         donc un étudiant doit y passer avant que le moteur puisse décoder. Même décision que pour
         le P300.
       - **[à faire]** une **seconde personne mesurée**. Tous les chiffres de ce mode viennent d'une
         personne et d'une séance ; le jour où une deuxième est mesurée, ils deviendront une moyenne
         au lieu d'un point.
     - **[à faire]** la **calibration P300 jouée par le moteur** (évolution F2, §13) : elle reste
       dans l'appli pygame, donc un étudiant doit y passer avant que le moteur puisse décoder.
     - **[à faire]** le **control plane** (commandes JSON entrantes, §12.1) reste entier : ce
       chantier n'a livré que les marqueurs de STIMULUS, qui ne partagent que le mot « marqueur ».
   - **[à faire — séance matérielle]** la console n'a **jamais été ouverte en fenêtre** : tout est
     vérifié hors écran (`--smoke`, Qt en `offscreen`). Restent à faire au casque : non-régression
     SSVEP, charge CPU en cumul de modes, et un repos partagé vécu de bout en bout.
1. **[fait]** Import du code existant dans le dépôt GitHub (`medkar/EEG_API_Unicorn`).
2. **[en cours]** Cette spec.
3. **[fait 2026-07-27]** Extraire le **moteur** en cœur réutilisable ; restructurer `core/` vs
   `research/` (détail et règles en **§3.1**). Les 8 tests headless passent aux nouveaux chemins.
   - **[fait]** vocabulaire « Waffle / robot » purgé du code et de la doc ; l'émetteur UDP est
     devenu `examples/actuator_udp.py`, `WAFFLE.md` est devenu `docs/robot_testbed.md`.
   - **[à faire]** sortir `UNICORN_SERIAL` et l'hôte de sortie du code → configuration (chaque
     élève a son casque). Aujourd'hui encore en dur dans `core/config.py`, contournable par
     `--serial` en ligne de commande.
4. Couche **LSL** : `eeg_raw` + `quality` + `SSVEP_decoded` (MVP).
   → **tester tôt** : `pip install pylsl` + découverte multicast **sur un poste et le réseau de l'école**
   (pare-feu). C'est le risque technique n°1 du choix tout-LSL : le lever avant de construire dessus.
   - **[fait 2026-07-27]** risque LSL levé **en local** (mesures au §4) ; `requirements.txt` créé.
   - **[fait 2026-07-27]** `src/core/lsl_io.py` (publication + pont d'horloge BrainFlow→LSL + autotest) et
     `src/core/server.py` (**moteur headless** : `raw` + `quality` + `status`, `--synthetic`, `--smoke`).
   - **[fait 2026-07-27]** validé sur le **vrai casque** : horodatage à ±0,5 ms, `quality` à
     4,6-9 µV sur les 8 voies. Deux défauts **pré-existants** corrigés au passage (`_filter`
     modifiait son entrée ; `quality()` mesurait le transitoire du filtre, pas l'électrode).
   - **[fait 2026-07-27]** `decoded_ssvep` : décodeur CCA branché sur la même boucle, avec
     mesure du repos, normalisation z et rejet d'artefact. **Pas encore validé sur casque.**
   - **[clos 2026-07-29 — décision d'exploitation]** le test multicast sur le réseau de l'école
     devient **sans objet** : les séances se feront sur un **routeur dédié**, pas sur le réseau de
     l'établissement. Le risque n°1 du choix tout-LSL est donc levé par l'organisation plutôt que
     par un test. ⚠️ La contrepartie est à connaître : la découverte LSL n'est plus garantie hors
     de ce routeur, donc un étudiant qui branche son poste sur le WiFi du campus ne verra rien —
     c'est [docs/network.md](network.md) qui reste la marche à suivre dans ce cas.
5. **Exemples** : `receiver.py` + Unity SSVEP.
   - **[fait 2026-07-27]** `examples/receiver.py` (`--list` / `--stream raw|quality|status|decoded_ssvep`).
   - **[fait 2026-07-27]** `examples/unity/` (SsvepIntentReceiver + IntentToMotion + README).
     ⚠️ écrit contre l'API LSL4Unity vérifiée sur les sources, mais **jamais exécuté dans Unity**
     (pas d'installation Unity sur le poste de dev) — à faire valider par un premier utilisateur.
6. Incréments v1/v2 (MI, P300, control plane, neuro, ErrP, nouvelle GUI).
7. **[fin] Nettoyage des commentaires** — mode par mode, style validé sur un fichier témoin d'abord :
   garder/écrire le « quoi + pourquoi pour un nouveau venu qui va MODIFIER le code », retirer le journal
   de debug daté.
8. **[fin] Rédaction du README (anglais) + doc d'API** — référence des flux, des commandes, de la « spec
   de stimulus » par mode, guide de démarrage étudiant, exemples.
