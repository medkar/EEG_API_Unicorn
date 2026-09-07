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
