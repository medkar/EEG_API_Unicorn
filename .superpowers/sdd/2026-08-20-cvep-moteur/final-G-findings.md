# Tranche G — la DOCUMENTATION (revue finale, lecture seule)

Vérifié contre le code du dépôt au 2026-09-03 (`src/core/modes/cvep.py`, `src/core/lsl_io.py`,
`src/core/config.py`, `src/core/modes/registry.py`, `src/research/cvep_stimulus.py`,
`src/research/cvep_calibrate.py`, `src/research/app.py`, `archive/cvep_pilot.py`,
`examples/receiver.py`). **Aucun programme exécuté** (six relecteurs en parallèle, mêmes noms de
flux LSL) : les vérifications sont statiques, et chaque point qui exigerait une exécution est
marqué « À VÉRIFIER PAR EXÉCUTION ».

**Décompte : 2 Critical · 7 Important · 8 Minor.**

Ce qui est JUSTE et que je ne redis pas point par point (recoupé ligne à ligne) : le marqueur
`{"mode":"cvep","event":"cycle","refresh":60.0}` et son horodatage après flip · les 10 voies
`target_index, confidence, score_0…5, corr_min, margin` (`lsl_io.cvep_channel_labels`) · les 12
champs de métadonnées sous `decoding/` (`paradigm`, `n_targets`, `decoder`, `decision_scale`,
`corr_min`, `margin`, `min_votes`, `vote_len`, `code_len`, `refresh`, `cv`, `no_decision_index`) ·
`decision_scale = "correlation"` et les six valeurs de `paradigm` · les quatre causes de `-1` et
leurs quatre gestes (identiques à `_MOTIFS_FR`) · péremption à 3 cycles = 3,15 s
(`CVEP_PEREMPTION_CYCLES=3`) · refus au-delà de 1 Hz d'écart, paliers 1/10/100/1000, **mode qui
continue et publie `-1`** · marqueurs de chauffe ENCAISSÉS (contrairement au P300/ErrP) · seuils
0,26/0,09 (eCCA) et 0,24/0,08 (rCCA, k=2, 1 personne, 1 séance) · transition 2,70 s = 32 % d'une
consigne de 8,4 s, et 8 cycles = `CYCLES_PAR_CIBLE` calculé, pas posé · McNemar p = 0,727 sur 37
décisions dont 8 discordantes, jamais de gagnant nommé · ordre des tuiles
`raw, ssvep, neuro, mi, p300, errp, cvep` et `status="moteur"` pour les sept · bouton « Calibrer »
console réservé à `Calib(kind="console")`, donc au seul MI · `core/modes/external.py` bien supprimé ·
toutes les commandes citées existent (options `--seed/--refresh/--seconds/--windowed/--no-wait/--smoke`
de l'émetteur, `--model` de `archive/cvep_pilot.py` dont le défaut pointe bien `data/cvep_model.npz`,
`console/app.py --mode`, `receiver.py --stream decoded_cvep`).

---

## CRITICAL

### C1 — La seule règle de dépouillement du 2.9 n'est applicable avec AUCUN outil du dépôt

- **Où** : `docs/recette.md:782` (« - [ ] **Ne note QUE les `decoded_cvep` postérieurs à ce second
  horodatage.** C'est la seule règle de dépouillement de ce test, et l'ignorer suffit à fabriquer un
  échec. »), repris en `docs/recette.md:836` et annoncé dès `docs/recette.md:462` (1.16).
- **Ce que la doc demande** : comparer l'horodatage LSL de chaque échantillon `decoded_cvep` à
  l'instant `compter à partir de t=…` imprimé par l'émetteur.
- **Ce que le code fait** : le terminal 3 prescrit par le test est
  `python -u examples/receiver.py --stream decoded_cvep`, et **`examples/receiver.py:111-116`
  n'imprime aucun horodatage** : il calcule `age_ms = (local_clock() - (ts + offset)) * 1000` et
  affiche `[  12.3 ms old] target_index=…`. Le `ts` est lu puis jeté. Le terminal 1 n'aide pas
  davantage : `CVEPRuntime._log` (`src/core/modes/cvep.py:643-657`) imprime `[cvep] CIBLE 2 (…)` à
  ~1 Hz **sans horodatage**. Et aucun outil du dépôt ne dépouille un enregistrement `decoded_cvep` :
  `src/research/cvep_analyze.py:1` travaille sur `data/cvep_calib_last.npz` (des époques de
  calibration), pas sur un flux ; les seuls fichiers qui connaissent `decoded_cvep` sont le publieur,
  le mode, la console, l'émetteur, le pilote archivé et `receiver.py`.
  Conséquence : à 5 échantillons/s sur ~5 min, l'opérateur doit rattacher ~1 500 lignes sans
  horodatage à ~35 consignes. C'est ce que T8 pressentait (« le dépouillement manuel sera faux la
  première fois ») ; ce n'est pas seulement pénible, c'est **impossible tel qu'écrit**.
- **Correction minimale (au choix, la première est la moins chère)** :
  1. Remplacer la règle par une règle que le terminal 1 rend applicable : *« le terminal 1 imprime
     une ligne par seconde ; après chaque changement de consigne, **jette les 3 premières lignes**
     (2,70 s de transition) et compte les ~5 suivantes »* — 8 lignes par consigne de 8,4 s, comptables
     à l'œil, sans horodatage.
  2. Ou, si l'on veut le dépouillement à l'horodatage : ajouter `ts` à la sortie de
     `examples/receiver.py` (une ligne : `print(f"[t={ts:.3f}] …")`) — **hors du périmètre de cette
     tranche**, donc à signaler au propriétaire de `examples/`, et la recette doit alors dire
     « redirige le terminal 3 dans un fichier ».
  3. Dans les deux cas, ajouter la phrase manquante : *« ce dépouillement se fait après la séance,
     sur un journal, pas en direct. »*

### C2 — Le bloc B de l'A-B-A (« la seule mesure qui conclut ») n'a pas de protocole : l'écran archivé n'a NI consigne NI vérité-terrain

- **Où** : `docs/recette.md:874-897` — « C'est **le seul point de 2.9 qui produise une conclusion** »,
  puis « `archive/cvep_pilot.py` … **même modèle, mêmes cibles, même vote 2-sur-3** », puis
  « - [ ] A : ______ % · B (écran archivé) : ______ % · A' : ______ % . »
- **Ce que le code fait** : la moitié technique de l'affirmation est VRAIE — `archive/cvep_pilot.py:41-56`
  décode à 5 Hz sur `CVEP_DECISION_CYCLES × n_cyc` échantillons avec `_vote(votes, CVEP_MIN_VOTES,…)`,
  soit exactement la géométrie du moteur (2,1 s, 2-sur-3). Mais l'écran **n'affiche aucune consigne** :
  il appelle `_live_loop` (`src/research/app.py:149-172`), une boucle qui dessine la couronne et un
  panneau de scores, **sans cible cerclée, sans tirage, sans graine, sans horodatage, sans journal**.
  L'utilisateur choisit lui-même ce qu'il fixe et **voit en direct ce que le décodeur répond**
  (`_panel`). Il n'existe donc :
  - aucune vérité-terrain pour calculer un « B : ____ % » ;
  - aucune règle de transition pour B (elle vaut pourtant aussi : 2,1 s de fenêtre + 0,6 s de vote
    après chaque changement de regard volontaire) ;
  - et B est en **boucle fermée** (retour visuel) là où A est en boucle ouverte (consigne imposée) —
    deux protocoles différents, dont l'écart ne s'interprète pas.
- **Correction minimale** : écrire le protocole de B au lieu de le supposer, en trois lignes :
  *« B n'a pas de consigne : choisis toi-même une cible dans une liste écrite d'avance (6 cibles ×
  3 passages, notées sur papier AVANT), fixe-la 10 s, **ignore les 3 premières secondes**, et note ce
  que le panneau affiche à la fin de chaque fixation. Ne regarde le panneau qu'à la fin — il te dit
  la réponse et biaise ta fixation. »* Et remplacer « même modèle, mêmes cibles, même vote » par
  « même modèle, mêmes cibles, même vote — **mais pas le même protocole** : A est cerclé et à
  l'aveugle, B est libre et avec retour visuel ».

---

## IMPORTANT

### I1 — « Calibration ~1 min » : le code lui-même l'estime à ~2,7 min (et le commentaire dit 3,4 min)

- **Où (4 sites)** : `README.md:195` (« one calibration in the pygame app, about a minute »),
  `README.md:286` (colonne Calibration : « ~1 min, in the pygame app »), `docs/markers.md:499`
  (« # menu -> c-VEP -> Calibrer   (~1 min) »), `docs/recette.md:427` (« page c-VEP → Calibrer,
  ~1 min ») et `docs/recette.md:791` (« Calibrer, ~1 min, fixer chaque cible »).
- **Ce que le code fait** : `src/research/cvep_calibrate.py:436` calcule et imprime la durée :
  `est = (len(plan)*cycles + n_blk*SETTLE_CYCLES) * L / refresh / 60 + n_blk*1.8/60`. Aux réglages
  du dépôt (`CVEP_CAL_CYCLES=15`, `CVEP_CAL_BLOCKS=3`, 6 cibles → `_make_blocks` rend **18 blocs**,
  `SETTLE_CYCLES=2`, L=63 à 60 Hz) : `(90 + 36) × 1,05 / 60 + 18 × 1,8 / 60` = **2,7 min**, hors
  briefing et hors contrôle de liaison. Le commentaire de `cvep_calibrate.py:445` dit d'ailleurs
  « AVANT d'investir 3,4 min ». Le « ~1 min » est un chiffre d'un ancien réglage ; il survit aussi
  dans `src/core/config.py:318` et dans le libellé de la page (`src/research/app.py:1176`).
- **Pourquoi ça compte** : dans le 2.9 la calibration est un préalable *dans la séance casque*, et
  le niveau 2 est budgété « ~90 min » (`docs/recette.md:109`). Un facteur 3 sur un préalable de
  séance se paie en fatigue et en électrodes qui sèchent.
- **Correction minimale** : « ~3 min » aux cinq endroits (et signaler au propriétaire du code que
  `config.py:318` et `app.py:1176` portent la même valeur périmée).

### I2 — 1.16, `--refresh 75` : le compteur annoncé n'est pas celui qui montera

- **Où** : `docs/recette.md:471-474` — « Attendu : le moteur **refuse tous les marqueurs** … il
  continue de tourner et de publier -1, **sous `sans_reference`** ».
- **Ce que le code fait** : `sans_reference` n'est incrémenté que si `self._ref_ts is None`
  (`src/core/modes/cvep.py:323-324`). Or la puce précédente de ce même test
  (`docs/recette.md:467-470`) fait justement tourner l'émetteur à 60 Hz, puis le relancer : le mode a
  donc une référence VALIDE en mémoire. Un marqueur refusé ne l'efface pas (`_refuse_marqueur`
  n'y touche pas ; seul `_reset_rest` remet `_ref_ts = None`). Au bout de 3,15 s c'est donc
  **`reference_perimee`** qui monte, indéfiniment — jamais `sans_reference`.
- **Pourquoi ça compte** : la table du 2.9 (`docs/recette.md:851-854`) fait lire
  `reference_perimee` comme « l'émetteur s'est tu → relance-le », c'est-à-dire exactement le
  mauvais geste ici. L'opérateur qui suit la doc conclut à une régression ou tourne en rond.
- **Correction minimale** : « … et publie -1 sous **`reference_perimee`** (l'ancienne horloge, encore
  en mémoire, expire au bout de 3,15 s ; ce serait `sans_reference` seulement si le mode venait
  d'être redémarré). **Le compteur qui identifie VRAIMENT ce cas est `marqueurs_refuses`.** »

### I3 — « Il ne reste à l'appli pygame que les calibrations + l'histogramme neuro » : faux, trois écrans de pilotage y vivent encore

- **Où (3 sites)** : `CLAUDE.md:32-36` (« Il ne lui reste que **les calibrations que le moteur ne
  sait pas jouer** — c-VEP, P300, ErrP … — et l'histogramme neuro »), `README.md:207-210` (« What is
  left here is what the engine cannot do — the **calibrations** for c-VEP, P300 and ErrP … plus the
  live histogram for neuro-monitoring »), `docs/recette.md:986-989` (« il ne lui reste que les
  **calibrations** … et l'histogramme neuro »).
- **Ce que le code fait** : `src/research/app.py` garde **cinq pages, dont trois de PILOTAGE** :
  `mode_ssvep` (`:383`, décodage SSVEP live), `mode_p300` (`:529`, sélection live avec arrêt
  dynamique), `mode_errp` (`:885`, démonstrateur ErrP mono-essai) et `mode_neuro` (`:769`). Sa propre
  docstring l'écrit (`app.py:1` : « un menu, cinq modes de décodage »), et le smoke exerce
  `mode_ssvep`, `page_p300`, `page_errp`, `mode_neuro` (`app.py:1341-1346`). **Seuls le c-VEP et le
  MI ont perdu leur pilotage** (`app.py:415-422`) — c'est vrai pour eux, faux pour les trois autres.
- **Correction minimale** : « Il lui reste les **calibrations** que le moteur ne sait pas jouer
  (c-VEP, P300, ErrP), l'histogramme neuro, **et trois écrans de pilotage que le chantier n'a pas
  retirés — SSVEP, sélection P300, démonstrateur ErrP** : ils font double emploi avec le moteur et
  ne doivent jamais tourner en même temps que lui. Seuls le c-VEP et le MI y ont perdu leur
  pilotage. »

### I4 — « The other five were validated in the pygame app » : le neuro ne l'a jamais été

- **Où** : `README.md:291-294` — « Only SSVEP has been decoded from a real brain *through the
  engine*. **The other five were validated in the pygame app**, and their engine path is verified
  without a headset. »
- **Ce que le dépôt dit ailleurs** : la ligne juste au-dessus dans le même tableau
  (`README.md:288`) classe le neuro « 🟡 published as a stream, **content not yet
  hardware-validated** », et `docs/SPEC.md:199` écrit « Plomberie testée, **contenu jamais validé sur
  casque** ». Le neuro n'a donc été validé nulle part, ni dans l'appli ni à travers le moteur.
- **Pourquoi ça compte** : c'est l'encadré « publié ≠ validé », celui dont dépend toute la crédibilité
  du reste. Une exagération là décrédibilise les avertissements honnêtes qui l'entourent.
- **Correction minimale** : « The other four (MI, P300, ErrP, c-VEP) were validated in the pygame
  app; neuro-monitoring has never been validated at all — its plumbing is tested, its content is
  not. »

### I5 — L'encadré « résultat NORMAL » compare deux choses qui n'ont pas le même dénominateur

- **Où** : `docs/recette.md:730-735` (« eCCA 59,5 %, rCCA 64,9 % … environ UNE désignation sur TROIS
  est fausse ») et surtout `docs/recette.md:839` (« **Compare au repère de l'encadré 1** : ~2 justes
  sur 3 **parmi les verdicts émis** »).
- **Ce que le code fait** : les 59,5 % / 64,9 % sont l'`argmax` hors-pli sur **toutes** les
  37 décisions k=2 (`CVEPModel.hors_pli`, `groupes_de_cycles(y, 2)`), c'est-à-dire **sans `corr_min`,
  sans `margin` et sans vote**. Le moteur, lui, n'émet une cible qu'après les deux seuils
  (`CVEPRuntime.decide`) **et** 2 votes sur 3 (`_run_step:580-604`) — les fenêtres rejetées
  deviennent des `-1`, que la recette fait compter à part (« silences »). Le repère qui correspond
  vraiment à « parmi les verdicts émis » existe déjà, mesuré, dans `src/core/config.py:437-439` :
  **k=2, seuils 0,26/0,09 → 46 % d'émission, 71 % de justesse à l'émission, 10 % de bruit passé**.
- **Pourquoi ça compte** : c'est l'encadré qui dit à l'opérateur ce qu'est un succès. Avec le mauvais
  dénominateur, un résultat à 70 % de justesse sur 45 % d'émission — c'est-à-dire le comportement
  attendu — se lit comme « mieux que prévu », et un 60 % sur 90 % d'émission comme « conforme » alors
  qu'il signalerait des seuils qui ne mordent plus.
- **Correction minimale** : ajouter au 1er encadré : *« Ces 59,5/64,9 % sont l'argmax sur TOUTES les
  décisions, **sans les deux seuils ni le vote que le moteur ajoute**. Le repère hors ligne qui
  correspond à ce que tu vas compter (les verdicts ÉMIS) est ailleurs : à k=2, aux seuils 0,26/0,09,
  l'eCCA émet sur **46 %** des fenêtres et se trompe sur **29 %** de ce qu'il émet
  (`core/config.py`). »* Puis aligner la puce `:839` dessus.

### I6 — « ~22 bits/min » : pas traçable, et calculé comme si le moteur émettait toujours

- **Où** : `README.md:201-203` (« … **59.5 % (eCCA) and 64.9 % (rCCA)**, an ITR around 22 bits/min
  with saline ») et `README.md:286` (« 6 targets, ~22 bits/min, ~60-65 % offline »).
- **Ce que le code donne** : avec `research/itr.py` à 6 cibles et une décision toutes les 2,1 s
  (k=2), 59,5 % → **19,2 bits/min** et 64,9 % → **23,9 bits/min** ; les seuls chiffres versionnés
  sont ceux de `config.py:343-344` (protocole entrelacé : k=1 → 20,2 ; k=2 → 27,1) et le 22 bits/min
  « salé » n'apparaît nulle part dans le dépôt. Surtout, ces ITR supposent **une décision publiée par
  fenêtre**, alors que le moteur n'émet qu'après seuils + vote (46 % des fenêtres hors ligne) : l'ITR
  réellement délivré par `decoded_cvep` est de l'ordre de la moitié.
- **Correction minimale** : soit dater et sourcer (« ~22 bits/min, séance salée du <date>, hors
  ligne, sans seuils ni vote »), soit remplacer par la fourchette recalculable : « ~19-24 bits/min
  hors ligne à k=2 — **et environ moitié moins en sortie du moteur, qui n'émet pas à chaque
  fenêtre** ».

### I7 — L'invitation à baisser `corr_min` en séance casse la comparabilité A vs B, sans un mot

- **Où** : `docs/recette.md:866-872` — « tu peux **descendre le seuil sans interrompre la séance** …
  **Note la valeur retenue dans ton relevé** », immédiatement suivi (`:874`) de la comparaison A-B-A.
- **Ce que le code fait** : `CVEPRuntime.decide` relit `params["corr_min"]/["margin"]` à chaque
  décision — la console peut donc les tourner à chaud. `archive/cvep_pilot.py:75` construit au
  contraire `CVEPDecoder(model, plan)` avec les défauts de classe
  (`cvep_decoder.py:272` → `CVEP_CORR_MIN`/`CVEP_MARGIN` = 0,26/0,09) et **n'expose aucun réglage**
  (`_parse` n'a que `--model/--windowed/--send/--synthetic/--smoke`). Une séance où A tourne à 0,15
  et B à 0,26 compare deux règles de décision, pas deux chemins de décodage — exactement la confusion
  que l'A-B-A existe pour éliminer.
- **Correction minimale** : ajouter à la puce du seuil : *« ⚠️ Si tu descends `corr_min`, **la
  comparaison à l'écran archivé du point suivant ne vaut plus** : lui décode toujours à 0,26/0,09 et
  n'a aucun réglage. Fais la comparaison A-B-A **d'abord**, aux seuils par défaut ; ne desserre le
  seuil qu'après, et note-le comme un bloc séparé. »*

---

## MINOR

### m1 — CLAUDE.md : « les cinq gardes du c-VEP », six commandes en dessous
`CLAUDE.md:140` annonce cinq gardes ; le bloc `:142-147` en liste six (`cvep_code`, `cvep_decoder`,
`cvep_rcca`, `cvep_models`, `modes/cvep`, `cvep_stimulus --smoke`) — toutes existantes et toutes
dotées d'un `__main__`. Corriger « cinq » → « six ».

### m2 — markers.md : les noms de modèles P300/ErrP horodatés sont donnés avec un tiret ; le code écrit un souligné
`docs/markers.md:502-503` donne `data/p300_model_20260818-101500.joblib` et
`data/errp_model_20260819-142230.joblib`. Le code écrit `p300_model_%Y%m%d_%H%M%S.joblib`
(`src/research/p300_calibrate.py:252`) et `errp_model_%Y%m%d_%H%M%S.joblib`
(`src/research/errp_calibrate.py:359`) — **souligné**. Seuls le c-VEP
(`cvep_calibrate.py:400`) et le MI (`mi_calib.py:72`) utilisent le tiret. Le diff a « corrigé » deux
exemples qui étaient justes : rétablir `20260818_101500` / `20260819_142230` et garder
`cvep_model_20260821-093000.npz`.

### m3 — recette 2.9 : l'exemple de ligne d'émetteur nomme une cible qui n'existe pas à 6 cibles
`docs/recette.md:779` : `cycle 9 : fixe « DROITE » (cible 2)`. `cvep_targets`
(`src/core/config.py:519-541`) nomme les 6 cibles `AVANT, AV-DROITE, AR-DROITE, ARRIERE, AR-GAUCHE,
AV-GAUCHE` : « DROITE » et « GAUCHE » n'apparaissent qu'à 3 cibles, et l'indice 2 est **AR-DROITE**.
Écrire `fixe « AR-DROITE » (cible 2)`.

### m4 — La ligne de cadence, seul verdict de validité de la séance, disparaît si on quitte par Ctrl+C
`docs/recette.md:828-832` fait de la ligne `cadence : … ms par cycle` le juge de « la séance est à
refaire ». Elle est produite par `bilan_de_seance`, appelé **après** la boucle
(`cvep_stimulus.py:566`) ; `__main__` (`:1154-1161`) n'attrape pas `KeyboardInterrupt`, donc un
Ctrl+C dans le terminal 2 perd le bilan (et `pygame.quit()`). Ajouter : « **quitte l'émetteur par
ESC**, jamais par Ctrl+C : le bilan de cadence ne s'imprime qu'à la sortie propre ».

### m5 — Durées incohérentes à l'intérieur du 2.9
`docs/recette.md:834` fait tourner le bloc A « ~5 min », `:887` le rappelle comme « ~3 min ».
Harmoniser (et, avec I1, revoir le « ~90 min » du niveau 2 en tête de fichier : calibration ~3 min +
A 5 + B 3 + A' 3 + montages).

### m6 — 1.16 : « c'est `sous_les_seuils` qui **doit** monter » est trop absolu
`docs/recette.md:463`. Sur le board synthétique, une fenêtre peut passer 0,26/0,09 par hasard et
tomber ensuite en `vote_non_conclu` (`cvep.py:587-592`) : les deux compteurs peuvent bouger.
Écrire « c'est `sous_les_seuils` qui doit **dominer** (quelques `vote_non_conclu` ne sont pas une
panne) ».

### m7 — L'inventaire de `research/` oublie la fabrique de codes Gold
`docs/SPEC.md:551-555` : « Ce qui reste dans `research/` … l'appli pygame, les calibrations, les
émetteurs de stimulus et les analyses hors ligne ». Il reste aussi `src/research/cvep_rcca.py`
(184 lignes : `make_distinct_codes` / `build_targets_rcca`, l'hypothèse RÉFUTÉE gardée lisible, seule
appelée par `archive/cvep_rcca_pilot.py`). Ce n'est **pas** un décodeur — l'affirmation centrale
(« plus aucun décodeur en attente ») tient — mais l'énumération est incomplète, et le tableau
`research/` de `README.md:277-283` ne le mentionne pas non plus. Ajouter une 5e famille :
« hypothèses réfutées, gardées lisibles : `cvep_rcca` (codes Gold) ».

### m8 — Compaction de `docs/recette.md` (996 lignes) sans perdre de garde-fou
Trois coupes sûres, ~80-100 lignes, sans toucher à un seul avertissement :
1. **1.16 et 2.9 répètent trois fois le même bloc** (les quatre causes de `-1` + leurs gestes :
   `:463-470`, `:845-856`, plus la table de `docs/markers.md:527-533`). Garder la table **une fois**
   dans 2.9 et y renvoyer depuis 1.16 (« mêmes quatre compteurs qu'au 2.9 »).
2. **Le rappel « deux seuils voyagent deux fois »** est écrit intégralement en `:479-484` (1.16) et
   re-résumé ailleurs ; une phrase + un lien vers `docs/markers.md#from-the-c-vep` suffit.
3. **Les trois encadrés d'entête du 2.9** (`:721-799`) réexpliquent la panne muette déjà décrite deux
   fois dans le même fichier et une fois dans `CLAUDE.md`. Fusionner les encadrés 1 et 2 (le repère
   chiffré et la période à jeter vont ensemble : ce sont les deux moitiés d'une même règle de
   comptage) et laisser l'encadré 3 (le modèle) tel quel.
   ⚠️ Ne PAS compacter : la période de 2,70 s et son « pourquoi », le tableau des quatre compteurs,
   la règle « --model explicite », l'avertissement « ne conclus rien sur six essais ».

---

## À VÉRIFIER PAR EXÉCUTION (rien n'a été lancé)

- `python src/research/cvep_calibrate.py` puis lire la ligne `[cvep-cal] … ≈ X.X min` — attendu
  **≈ 2,7 min** (I1). (Ou `python src/research/app.py --smoke`, qui la fait imprimer aussi.)
- 1.16 avec `--refresh 75` après une horloge valide — attendu : `marqueurs_refuses` monte **et
  `reference_perimee`**, pas `sans_reference` (I2).
- `python src/research/app.py --smoke` — attendu : la ligne `smoke OK : menu + SSVEP + c-VEP
  (calibration eCCA+rCCA) + P300 + neuro + …`, qui matérialise I3 (SSVEP/P300/ErrP encore là).
- `python -u examples/receiver.py --stream decoded_cvep` — attendu : des lignes
  `[  xx.x ms old] target_index=…`, **sans horodatage**, ce qui est le fond de C1.
