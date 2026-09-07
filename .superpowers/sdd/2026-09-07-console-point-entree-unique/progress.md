# SDD ledger — plan: docs/superpowers/plans/2026-09-07-console-point-entree-unique.md

Chantier « la console, seul point d'entrée ». Spec `493e9fb`, plan `010222d`.

**Mode d'exécution choisi par l'utilisateur (2026-09-07) : HYBRIDE, sans point d'arrêt.**
Sous-agents pour les six tâches lourdes (3 à 8) ; les cinq autres (1, 2, 9, 10, 11) sont menées
en ligne par le contrôleur, parce que le coût d'un brief y dépasse le coût du travail. La
documentation (11) est écrite en ligne mais **relue par un sous-agent** — mesuré au chantier
précédent : 0 régression dans 2000 lignes de code relu, 1 régression et 8 faussetés dans la doc
écrite sans relecteur.

## Journal

- Atelier créé. ⚠️ `scripts/sdd-workspace` a de nouveau écrasé `.superpowers/sdd/.gitignore` avec
  son `*` par défaut — le même incident qu'au chantier c-VEP. L'avertissement laissé dans le
  fichier a de nouveau servi ; restauré par `git restore`, carnet vérifié suivi.

- **Task 1 : complete** — `68870aa`. Paquet `src/stimulus/`, frontière AST étendue (prouvée par
  mutation), et une DÉDUPLICATION non prévue au plan : la piste ErrP était écrite deux fois
  (`errp_calibrate` et l'émetteur), avec un test de 500 pas qui protégeait la copie. Les deux ont
  fusionné dans `core/errp_track.py` ; les deux tests qui gardaient la duplication ont disparu
  avec elle. Le déménagement l'a forcé : laisser la règle dans `research/` créait l'arête
  `stimulus -> research`, refusée.
- **Task 2 : complete** — `a8b4335`. `Calib.kind` = moteur|fenetre, `stimulus_id`, `reason`
  supprimé, `ModeSpec.key_channels`, `catalog()["calibration"]["jouable"]`.
  ⚠️ **La frontière AST m'a attrapé** : j'avais écrit le contrôle « chaque stimulus_id désigne une
  fenêtre » dans `core/modes/registry.py`, avec un import local de `stimulus`. Refus justifié — le
  contrôle vit maintenant dans `stimulus/registry.py`, qui détient la correspondance et vérifie
  les DEUX sens.
- **Task 3 : complete** — `e309202`, sous-agent `a98203bfe84ceb6fb`.
  ⚠️ **Le sous-agent a trouvé un défaut dans MON plan** : la mutation que j'y prescrivais
  (`pre_s + 1/fs`) est VACANTE — `epoch_from_stream` fait `int(round(pre_s*fs))` et l'arrondi
  bancaire rend `round(37,5) == round(38,5) == 38`. Le test prescrit aurait été infalsifiable à la
  géométrie du P300. Il a durci LE test sur DEUX géométries et prouvé le rouge deux fois. Vérifié
  indépendamment par moi : mutation `+4 ms` (1 échantillon) → rouge 12/12 sur les deux géométries.
  Un bug attrapé au passage : `calib_end` et l'entraînement tombaient dans le même tour de boucle,
  donc la console n'aurait jamais pu peindre « entraînement ».
- **Prose périmée corrigée en ligne** (hors périmètre du sous-agent) : `server.py`, `registry.py`
  et `p300_models.py` parlaient encore de calibrations « natives » jouées par l'appli pygame.

## Réserves à porter

- 🔴 **POUR LA TÂCHE 5** : un mode et SA calibration se voleraient les marqueurs — `markers_murs`
  n'a qu'un curseur par `mode_id`. Le runtime le dit bruyamment à la construction, mais le REFUS
  doit venir de `server.submit`. Signalé par le sous-agent de T3, hors de son périmètre.
- **Pour les tâches 4/7/8** : la fenêtre doit occuper les ~15 s de chauffe avant son premier essai
  (sinon ces époques sont jetées — comptées et dites) ; le tampon vient de `marker_epoch_s`, pas
  de `Calib.epoch_s` (qui doit juste être > 0) ; et `duree_protocole_s` reste à 0 tant que la
  sous-classe ne la renseigne pas, sinon la page affiche une durée fausse.
- **Cas gelé par choix** : tous les essais annoncés reçus mais `calib_end` perdu → attente
  indéfinie, sortie par « Abandonner ». Entraîner quand même ferait un second déclencheur à côté
  de `calib_end`, donc une seconde vérité.
- **Task 4 : complete** — `93c7d8a` → `b0c0f01` (7 commits), sous-agent `a508d4a9a16656036`,
  interrompu une fois par une erreur d'API et relancé sur son contexte intact (rien de perdu).
  Vérifié par moi : les 7 autotests verts, et **`data/` intact — contrôlé par HORODATAGE**, rien
  de postérieur au 2026-08-17 (`git status` ne prouve rien, `data/` est gitignoré).
  ⚠️ **Défaut réel trouvé et corrigé (`e3199bb`)** : `P300Model` était construit avec ses `pre_s`/
  `post_s` PAR DÉFAUT alors que les époques étaient découpées avec ceux de `P300Runtime`. Mêmes
  nombres aujourd'hui, donc tous les tests verts — et le jour où quelqu'un déplace
  `P300Runtime.pre_s`, le mode aurait refusé le modèle qu'on venait de calibrer en accusant le
  modèle. Le découpage, lui, était bien identique (structurel, via le socle) : c'est ce qui en
  était SAUVEGARDÉ qui ne l'était pas.
  Deux trouvailles de chemin : le cycle d'import `p300 ↔ p300_calib` casse vraiment
  `python src/core/modes/p300.py` (mesuré) — **patron d'import tardif à reprendre en T7 et T8** ;
  et un `ok and helper(...)` court-circuitait le bout-à-bout du sous-agent exactement quand il
  servait.

## Réserves à porter (mise à jour)

- 🔴 **T5** : vol de marqueurs mode↔calibration (`markers_murs`, un curseur par `mode_id`). Refus
  attendu côté `server.submit`, DANS LES DEUX SENS. Toujours entier.
- 🔴 **T6, ordre de lancement** : la fenêtre attend 15 s à partir de SON lancement, le moteur
  compte sa chauffe à partir de `start_calibration`. Il n'existe AUCUNE poignée de main entre les
  deux processus — le sous-agent n'en a pas inventé, à raison. La console doit donc envoyer
  `start_calibration` D'ABORD, puis lancer la fenêtre : l'initialisation pygame (~3 s) plus
  l'attente de la fenêtre couvrent alors la chauffe du moteur. À TESTER, sinon les premières
  manches tombent dans la chauffe — jetées, comptées, dites, mais la séance est plus courte que ce
  que l'écran annonce.
- ⚠️ **T11** : `docs/markers.md` et `docs/SPEC.md` ignorent encore `calib_start`/`cue`/`calib_end`.
  Le contrat PUBLIC a bougé.
- ⚠️ `research/p300_calibrate.py` reste un second chemin vers un modèle, avec son épochage propre
  (horloge pygame). Réduit et marqué, pas supprimé — à trancher à la revue finale.
