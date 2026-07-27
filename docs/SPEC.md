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

**Décidé : TOUT passe par LSL** — données ET commandes (§12.1). Une seule dépendance, un seul concept à
enseigner, et le client Unity/Python n'apprend qu'une API.

Conséquences à connaître (LSL est conçu pour *streamer*, pas pour du requête/réponse) :

- **Pas d'accusé de réception.** Une commande est *fire-and-forget* : le client envoie sur
  `EEG_API_Unicorn_control`, puis **observe le résultat** sur `EEG_API_Unicorn_status`. D'où l'ajout du flux `status`
  ci-dessus — sans lui, un client ne saurait pas si sa commande a été prise en compte.
- **Commandes = messages JSON** dans un flux de marqueurs (chaîne unique), ex. `{"cmd":"start","mode":"ssvep"}`.
- **Pas de client LSL depuis un navigateur** (liblsl est une bibliothèque native, sans binding JS) : une
  interface web doit donc être servie par le moteur lui-même, qui fait le pont (§12.2).
- ⚠️ **Risque réseau école** : LSL découvre les flux par **multicast UDP**, que des pare-feux ou des réseaux
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
| **Motor Imagery** | endogène | `{class: left\|right\|rest, probs{left,right,rest}}` |
| **P300** | évoqué | `{selected_target}` (événementiel, après N répétitions) + scores par flash |
| **Neuro-monitoring** | passif | `{charge, somnolence, engagement}` (z relatifs au repos) |
| **ErrP** | évoqué | `{error: bool, score}` (événementiel, sur marqueur « feedback ») |
| **c-VEP** | évoqué | `{target_index, confidence}` — **stimulus natif au MVP** |

Chaque mode publie **une intention neutre** (quelle cible / quelle classe / quel état), jamais une commande
d'actionneur. La conversion en action appartient à l'application avale : c'est ce qui rend le même flux
utilisable par un jeu, une visualisation ou un robot sans rien changer côté API.

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
  `joblib`, + le micro-serveur du tableau de bord (`fastapi` + `uvicorn`, ou `flask`).
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

**v1 :** `MI_decoded` (endogène, calibration native) · `P300` via marqueurs entrants · control plane LSL
complet (`control` + `status`) · `neuro_decoded`.

**v2 :** `ErrP` (marqueurs) · **tableau de bord web** (§12.2) · évolutions parkées F1/F2 (§13).

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

### 12.2 Interface de contrôle : **tableau de bord web servi en local** ✅

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

**Techno** : Python + un micro-serveur HTTP (FastAPI ou Flask ; FastAPI offre en prime une page
`/docs` interactive utile pédagogiquement). Rafraîchissement de l'état par sondage périodique (simple) ou
WebSocket (plus fluide) — à trancher à l'implémentation, sans impact sur le reste.

**Contenu du tableau de bord** : qualité des 8 voies en direct · choix du mode · état « calibré / non
calibré » par mode · bouton de calibration · sortie décodée en direct · flux LSL publiés (noms/état).

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

1. **[fait]** Import du code existant dans le dépôt GitHub (`medkar/EEG_API_Unicorn`).
2. **[en cours]** Cette spec.
3. Extraire le **moteur** (acquisition + filtres + décodeurs) en cœur réutilisable ; restructurer
   `core/` (moteur) vs `research/` (calibrations lourdes, analyses, modes exploratoires).
   → au passage, **purger le vocabulaire « Waffle / robot »** du code et de la doc (le robot n'était qu'un
   banc d'essai) : `UDP_HOST`, l'exemple joystick, `WAFFLE.md`, le README, les entêtes de modules.
   Sortir aussi `UNICORN_SERIAL` et l'hôte de sortie du code → configuration (chaque élève a son casque).
4. Couche **LSL** : `eeg_raw` + `quality` + `SSVEP_decoded` (MVP).
   → **tester tôt** : `pip install pylsl` + découverte multicast **sur un poste et le réseau de l'école**
   (pare-feu). C'est le risque technique n°1 du choix tout-LSL : le lever avant de construire dessus.
   - **[fait 2026-07-27]** risque LSL levé **en local** (mesures au §4) ; `requirements.txt` créé.
   - **[fait 2026-07-27]** `src/lsl_io.py` (publication + pont d'horloge BrainFlow→LSL + autotest) et
     `src/server.py` (**moteur headless** : `raw` + `quality` + `status`, `--synthetic`, `--smoke`).
   - **[fait 2026-07-27]** validé sur le **vrai casque** : horodatage à ±0,5 ms, `quality` à
     4,6-9 µV sur les 8 voies. Deux défauts **pré-existants** corrigés au passage (`_filter`
     modifiait son entrée ; `quality()` mesurait le transitoire du filtre, pas l'électrode).
   - **[fait 2026-07-27]** `decoded_ssvep` : décodeur CCA branché sur la même boucle, avec
     mesure du repos, normalisation z et rejet d'artefact. **Pas encore validé sur casque.**
   - **[à faire]** test multicast **entre deux machines** sur le réseau de l'école.
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
