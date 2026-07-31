# SDD ledger — plan: docs/superpowers/plans/2026-07-28-console-experimentation.md

═══════════════════════════════════════════════════════════════════════════════
✅ CHANTIER TERMINÉ le 2026-07-29 — RIEN À REPRENDRE ICI
═══════════════════════════════════════════════════════════════════════════════
Les 17 tâches (0-16) sont faites, revues, corrigées, et POUSSÉES sur origin/main
(HEAD 786524e). Les trois smokes sont verts. Ce fichier est conservé comme COMPTE
RENDU, pas comme file d'attente : ne relance aucune tâche à partir de lui.
Les briefs, rapports et diffs de revue ont été supprimés (300 Ko d'échafaudage).
Le plan, lui, est dans git et survit.

SEULE CHOSE QUI RESTE DUE, et elle demande le matériel :
  la console n'a JAMAIS été ouverte en fenêtre. Voir « Après le plan » dans le plan
  committé pour les 3 vérifications casque.
═══════════════════════════════════════════════════════════════════════════════

Branche : main (workflow établi de l'utilisateur, cf. mémoire workflow-commits).
Base au démarrage : 3adaa3d

═══════════════════════════════════════════════════════════════════════════════
REPRENDRE ICI (fin de session 2026-07-28)
═══════════════════════════════════════════════════════════════════════════════
FAIT : tâches 0 à 12 complètes et revues (22 commits, HEAD = 16c33b7).
RESTE : tâches 13, 14, 15, 16,
        puis la REVUE FINALE de branche (modèle le plus capable, cf. SKILL.md),
        puis superpowers:finishing-a-development-branch.

Méthode : un sous-agent frais par tâche + revue systématique. Les briefs sont
déjà extraits dans ce dossier (`task-N-brief.md`, via `task-brief-fr`).
Le paquet de revue se construit avec :
  bash <SKILL>/scripts/review-package docs/superpowers/plans/2026-07-28-console-experimentation.md BASE HEAD
où <SKILL> = C:/Users/Lab_IA/.claude/plugins/cache/claude-plugins-official/superpowers/6.2.0/skills/subagent-driven-development

⚠️ POINTS À NE PAS PERDRE POUR LA SUITE
- Tâche 16 doit documenter le RETRAIT de `frequencies_hz`, `indices` et de
  l'`instruction` de phase décodage du payload `status` (décision assumée, voir
  « Task 7: PARKED » plus bas). Et corriger CLAUDE.md/README qui documentent
  encore `dashboard.py`, supprimé en tâche 9.
- Les rapports d'implémentation ont deux fois GÉNÉRALISÉ depuis un seul
  échantillon (chauffe partagée tâche 8, accents tâche 10). Vérifier toute
  affirmation de propriété sur TOUT le domaine avant de la croire.
- L'essai FENÊTRÉ de la console n'a jamais pu être fait (pas d'écran côté
  sous-agents). À faire à la séance matérielle, avec les 3 vérifications casque
  listées en fin de plan.
═══════════════════════════════════════════════════════════════════════════════

Convention de tests du dépôt (à rappeler à chaque relecteur) : PAS de pytest.
Chaque module porte son autotest sous `if __name__ == "__main__":`, avec un helper
`chk(cond, msg)` qui imprime `OK`/`ÉCHEC` et un `VERDICT` final, et `sys.exit(0/1)`.
Les tests de bout en bout sont des drapeaux `--smoke`. C'est ce que fait déjà
`cca_decoder.py`, `lsl_io.py`, `neuro_monitor.py`, `server.py` et `research/app.py`.

NB : `scripts/task-brief` du skill cherche « Task N » ; le plan est en français.
Extracteur équivalent écrit ici : `task-brief-fr PLAN N`.

Task 0: complete (commits 3adaa3d..0ae5703, review clean)
  PySide6 6.11.1 + pyqtgraph 0.14.0 installés, Qt vérifié en offscreen. Risque de la spec §9 LEVÉ.
  requirements.txt : -fastapi -uvicorn +PySide6 +pyqtgraph.

Task 1: complete (commits 0ae5703..1ff4ccd, review clean)
  Correction demandée AVANT revue (concern de correctness signalé par l'implémenteur, à juste titre).
  DÉFAUT DU PLAN trouvé à l'implémentation : le Param `freqs` déclare à la fois
  `min/max=BANDPASS` ET la contrainte `dans_la_bande` — deux mécanismes pour une règle.
  Les bornes gagnent, avec le message le moins utile, donc le test du brief ne peut pas passer.
  Sa correction (ne plus borner AUCUN float_list) ouvrait un trou : un futur mode déclarant
  min/max sans contrainte accepterait des valeurs hors plage EN SILENCE.
  Correction demandée : rétablir la boucle de bornes, retirer min/max du Param `freqs`,
  et ajouter un test prouvant qu'un float_list borné sans contrainte reste borné.
  ⚠️ À REPORTER EN TÂCHE 2 : `ssvep.SPEC` doit aussi déclarer `freqs` SANS min/max,
  avec `constraints=("dans_la_bande", "separables")` comme seul mécanisme de bande.

Task 1: minor (deferred): `ModeSpec.channels_for()` jamais appelé par l'autotest (couverture,
  hérité du brief) — sera exercé de fait par la tâche 2 (ssvep channels_fn) et la tâche 10.
Task 1: minor (deferred): la branche `kind="int"` de `_coerce` n'a aucun test dédié
  (aucun Param int dans l'autotest ; hérité du brief).
Task 1: minor (deferred): LATENT — un Param contraint avec `default=None` et omis des params
  ferait `lo <= None <= hi` dans `_check_constraints` -> TypeError au lieu d'un refus propre.
  Non déclenchable aujourd'hui (tous les params contraints ont un défaut concret). À corriger
  si un mode futur déclare une contrainte sans défaut.
Task 1: minor (deferred): rapport de l'implémenteur inexact (annonce 17 checks, il y en a 16 ;
  annonce 293 lignes, il y en a 288). Sans effet sur le code.

Task 2: complete (commits 1ff4ccd..924a445, review clean)
  7 ModeSpec (raw/ssvep/neuro + mi/cvep/p300/errp externes), registry.check() vérifié règle
  par règle par le relecteur. Correction Task 1 reportée : ssvep freqs sans min/max.
  Risque nommé vérifié : `ssvep_channel_labels` produit des étiquettes byte-identiques,
  et il n'existe que 2 points de construction dans tout l'arbre (lsl_io.py:209, ssvep.py:26).
Task 2: minor (deferred): `BANDPASS` encore importé dans `src/core/modes/ssvep.py:15` alors
  qu'il n'y sert plus (séquelle de ma correction). F401. ⚠️ À NETTOYER EN TÂCHE 5, qui
  retouche justement les imports de ce fichier.
Task 2: minor (deferred): `registry.serialize()` et `registry.catalog()` ne sont exercés par
  aucun autotest (vérifiés empiriquement par le relecteur, JSON-able pour les 7 specs).
  Seront exercés de fait par la tâche 11 (fake_state) et la tâche 12 (nombre de tuiles).

Task 3: complete (commits 924a445..6293a15, review clean)
  ModeRuntime : machine de phases warmup->rest->running, testée sur horloge fabriquée.
  Invariant vérifié ligne à ligne par le relecteur : aucun `time.perf_counter()` dans la
  classe, et `engine` n'est jamais touché par la base — seulement passé aux hooks.
Task 3: minor (deferred): `open()`, `close()`, `set_published()`, `state()`, `period_s()`
  ne sont appelés par AUCUN test (vérifiés à la main par le relecteur, corrects).
  ⚠️ `set_published` porte une fonctionnalité visible (la case « publié » de la grille) dont
  la panne est silencieuse : le flux ne disparaîtrait pas du réseau. À COUVRIR EN TÂCHE 8,
  dans le smoke de cumul : couper la publication d'un mode et vérifier que son flux quitte
  `state["streams"]`, puis le rallumer.
Task 4: complete (commits 6293a15..9b50be9, review clean, 0 finding)
  RawRuntime : le brut est un mode. Propriété centrale vérifiée : couper ce mode coupe la
  PUBLICATION, jamais la lecture du casque (sinon les autres décodeurs seraient affamés).
  ⚠️ du relecteur tranché par le contrôleur : `RawPublisher.__init__(ch_names, fs, instance)`
  correspond bien à l'appel — ce n'était pas une lacune.
  Registre : 7 modes, dont 1 dans le moteur.

Task 5: fix round 1/5 (3 addressed, 0 open ; commits c3781e7..3f762db, commit amendé)
Task 5: complete (commits 9b50be9..3f762db, review clean après 1 ronde)
  Portage SSVEP jugé FIDÈLE par le relecteur sur tous les points de décision (artefact,
  ordre d'ajout des échantillons, chemin d'échec de fit_baseline, sigma_ref, seuil 0,85,
  formes des dicts, format de log, branche classify None/cible) — comparé ligne à ligne
  contre `server.py` encore intact.
  1 DÉRIVE trouvée, née de MON brief : `_rest_step` avait perdu le print de fin de repos
  (« décodage en cours sur … — fixe une cible »). C'est le signal qu'attend la personne
  sous le casque. Restauration demandée, préfixe [ssvep] et non [server] (deux modes
  peuvent parler), + date « le 2026-07-27 » remise dans le commentaire σ=0,19.
Task 7: EN COURS — implémenteur abf8f2e503b404ec2, commit 9adc2e1, correction avant revue.
  DONE_WITH_CONCERNS : le smoke échouait en fin de session (cadence 43240 Hz au lieu de 250).
  VÉRIFIÉ PAR LE CONTRÔLEUR, pas cru sur parole :
   - 0 processus python parasite ;
   - échec identique sur un worktree à 1fb9716 (AVANT la tâche 7) -> pas une régression ;
   - sonde directe de BrainFlow (hors LSL, hors moteur) : le board synthétique livre PAR
     RAFALES. Écarts mesurés 6 µs à 20 ms, MÉDIANE 15,3 µs, MOYENNE 4001,2 µs = 249,9 Hz.
  => DÉFAUT DU TEST, pas du produit : `_smoke` calcule `1/median(gaps)`, ce qui mesure la
     GIGUE DE LIVRAISON et pas le débit. Passe machine au repos, échoue machine chargée —
     donc échouerait au hasard chez un étudiant, et lui apprendrait à ignorer le test.
  Correction demandée : cadence sur la DURÉE TOTALE `(n-1)/(t_der - t_prem)`, qui vaut
  249,9 Hz sur les mêmes données et attrape toujours un pont d'horloge cassé (le but réel
  du contrôle, dit par son propre commentaire).
  ⚠️ Ce défaut est ANTÉRIEUR à toute la session : le gate « smokes verts » était donc
  sensible à la charge machine depuis le début.
  L'implémenteur a aussi trouvé et corrigé HORS BRIEF un cycle de références
  (`ModeRuntime.engine` <-> `EngineServer.active`) qui laissait une session BrainFlow
  survivre à `run()` -> BOARD_NOT_CREATED_ERROR sur un 2e moteur du même processus.
  À faire juger comme code NEUF par la revue.
  Correctif de la cadence VÉRIFIÉ PAR LE CONTRÔLEUR : 249,9 Hz, 3 VERDICT OK, app.py OK.
  REVUE (opus) : 3 invariants tenus (lecture unique, arbitrage déterministe en ordre de
  registre, traduction de phase totale) ; les 11 méthodes supprimées ont toutes un domicile
  vérifié. 4 Important -> fix round 1 :
   (1) `snapshot()`/`_state` itèrent le dict VIVANT (:425, :457) -> RuntimeError dans le fil
       Qt au premier clic pendant un rafraîchissement. Copie atomique demandée.
   (2) correctif du cycle HORS `finally` (:575-589) -> sur perte de casque, le cycle survit
       et le bug revient au relancement. `try/finally` demandé.
   (3) `submit()` indexe `self.active[...]` sans garde (:330) -> KeyError au lieu d'un refus.
   (4) le commentaire du correctif décrit un mécanisme FAUX (ce n'est pas la session qui
       survit, c'est `BoardShim.__del__`, indexé sur board_id, qui ferme la session SUIVANTE).

Task 7: fix round 1/5 (3 addressed, 1 open — snapshot() ; commits 66af053..25ac08c)
  Ouvert : `_state`/`snapshot` partagent bien une copie atomique, MAIS la propriété `phase`,
  lue depuis `_state`, itère encore `self.active` VIVANT. Une propriété nue ne peut pas
  recevoir la copie. Atteignable AUJOURD'HUI via dashboard.py:55 (FastAPI) pendant run().
  ⚠️ Le re-relecteur n'a PAS pu reproduire la course (748k lectures), ni sur le motif
  d'avant correctif (1,3M lectures, témoin). Le test de charge ne tranche donc RIEN dans
  un sens comme dans l'autre : la constatation tient sur la LECTURE du code.
  Round 2 : extraire `_phase_of(active)`, la propriété fournit sa propre copie.

Task 7: fix round 2/5 (1 addressed, 0 open ; commits 25ac08c..3ad8bb9)
  `_phase_of(active)` extrait, la propriété fournit sa copie. Le re-relecteur a ÉNUMÉRÉ les
  22 accès à `self.active` et classé chacun : zéro lecture vivante atteignable hors du fil
  du moteur. `.get()` et `in` sont des lookups atomiques, pas des itérations.
Task 7: complete (commits 1fb9716..3ad8bb9, review clean après 2 rondes, 4 commits)
Task 7: minor (deferred): `server.py:638` — `for runtime in self.active.values()` dans le
  `finally` est la SEULE itération non copiée du fichier. Sûre aujourd'hui par un invariant
  implicite (la boucle a cessé de muter avant le `finally`), mais un futur changement qui
  drainerait les commandes pendant l'arrêt rouvrirait le bug en silence. Un `list(...)`
  fermerait la porte définitivement.

Task 8: fix round 1/5 (1 addressed, 0 open ; commits 7766a11..a99917c)
Task 8: complete (commits 3ad8bb9..a99917c, review clean après 1 ronde)
  6 smokes verts, vérifiés par le contrôleur. Le relecteur a retracé CHAQUE assertion contre
  le code réel (non modifié) qu'elle exerce : toutes mordent. Preuve par l'échec de 1b
  confirmée — `max`->`min` fait rougir 1b SEULE, la partie 1 reste verte.
Task 8: minor (deferred): server.py:1082-1083 — `seul_b == neuro.rest.duration_s` a un angle
  mort étroit (25 s = déjà le max), rattrapé par l'inégalité des `_warmup_until` juste après.
Task 8: minor (deferred): server.py:1226 — `stream_name("quality") not in streams` est
  tautologique (`streams` est amorcé inconditionnellement avec quality+status) ; le pouvoir
  discriminant vient du `not state["running"]` voisin.
Task 8: minor (deferred): 4 blocs de nettoyage quasi identiques dans `_smoke_repos_partage`
  pourraient être un helper local, si un 5e site apparaît.

Task 9: complete (commits a99917c..6442a50, review clean, 0 Critical/Important)
  dashboard.py + dashboard.html SUPPRIMÉS (704 lignes) — code déjà mort depuis la tâche 7
  (anciens kwargs du constructeur, anciennes commandes). Graphe de `core/__init__.py` mis à
  jour : `modes/` entre les modules feuilles et `server`, + frontière `console` documentée.
  Vérifié par le contrôleur : plus aucun .py ne référence dashboard.
  Les 3 fichiers de doc (SPEC/README/CLAUDE) laissés INTACTS -> tâche 16.
Task 9: minor (deferred): le rapport compte 7 verdicts là où il y en a 6 nommés
  (`[smoke-registry]` est une ligne d'état, pas un VERDICT). Sans effet sur le code.

Task 10: fix round 1/5 (4 addressed, 0 open ; commits 3d10cd2..c13536d)
Task 10: complete (commits 6442a50..c13536d, review clean après 1 ronde)
  28 checks verts, boucle sur les 7 modes vérifiée par le contrôleur.

Task 11: fix round 1/5 (5 addressed, 0 open ; commits 2598d0c..49ed65c, 2 commits)
Task 11: complete (commits c13536d..49ed65c, review clean après 1 ronde)
  Vérifié par le contrôleur : `QT_QPA = 'offscreen'` ET `docstring: présente` en important
  `console.banner` DIRECTEMENT, sans passer par app.py. La propriété est structurelle.
Task 11: GAP DÉCLARÉ (honnête, non résolu) : l'essai FENÊTRÉ
  (`python src/console/app.py --synthetic`) n'a PAS été fait — environnement sans écran.
  ⚠️ À FAIRE À LA SÉANCE MATÉRIELLE, avec les 3 vérifications casque déjà prévues :
  ouvrir la fenêtre, vérifier le bandeau, la FERMER et confirmer qu'aucun processus python
  ne survit (le chemin de fermeture est le correctif n°1 de cette tâche).
Task 11: DÉCISION pour la tâche 12 : nommer la méthode `Console.commande()` PUBLIQUE dès la
  tâche 12 (mon plan la crée `_commande` puis la renomme en tâche 14 — inutile).

Task 12: fix round 1/5 (3 addressed, 0 open ; commits 8368e22..16c33b7)
Task 12: complete (commits 49ed65c..16c33b7, review clean après 1 ronde)
  13 checks console verts, vérifiés par le contrôleur. `grid.py` n'importe RIEN de `core` —
  PySide6 pur au-dessus de dicts sérialisés, la séparation visée est atteinte.
  Le défaut de la tâche 11 (logique dupliquée depuis le moteur) ne se reproduit PAS :
  seul `meilleur` (barre la plus haute) est calculé côté console, et il est décoratif —
  le verdict textuel vient toujours de `output["target_index"]`.
Task 12: minor (deferred): le chemin `publier` (case à cocher -> commande -> moteur) n'est
  couvert par AUCUN test. `_FauxMoteur.submit()` existe mais n'est jamais appelé par le
  smoke, et il accepte n'importe quel nom/kwargs — il n'attraperait donc pas une commande
  mal nommée. Correctif possible : faire enregistrer les appels au stub et piloter la case
  par `.click()`. Seul l'essai fenêtré différé couvre ça aujourd'hui.
Task 12: minor (deferred): `grid.py:97` fait 118 caractères, la plus longue de `console/`
  (les autres plafonnent à 102). Toléré : `core/` compte 204 lignes > 100 caractères.
Task 12: minor (deferred): `grid.py:116-118` — le couple `blockSignals(True/False)` n'est
  pas dans un `try/finally` ; une exception entre les deux laisserait les signaux bloqués
  définitivement. Non atteignable aujourd'hui (`published` est toujours présent).

Task 11: DÉTAIL — implémenteur ad90574c745b12fbe, commit 2598d0c, fix round 1.
  Console + bandeau OK, smoke vérifié par le contrôleur (5 OK), QT_QPA ligne 46 avant
  l'import PySide6 ligne 48. 3 Important, TOUS écrits par MON brief et TOUS contredisant
  une contrainte que le plan pose lui-même :
   (1) `run()` démarre le fil du moteur AVANT le `try` -> un échec de montage Qt laisse la
       session BrainFlow pendante, alors que le commentaire voisin promet l'inverse
       (BOARD_NOT_READY). S'aggrave avec les tâches 12-15 qui grossissent Console.__init__.
   (2) `banner.py` RECALCULE le verdict des voies au lieu de lire `quality["verdicts"]` que
       le moteur publie déjà -> viole « aucune logique ici que le moteur ne possède pas »,
       dans le PREMIER fichier de console, donc précédent pour les 4 suivants.
   (3) le garde `QT_QPA_PLATFORM` est dans `app.py` : ne marche que parce qu'app.py est
       importé en premier AUJOURD'HUI. Déplacé dans `__init__.py`, que Python exécute
       toujours avant tout sous-module -> structurel au lieu d'accidentel.
  + `refresh()` n'a AUCUNE couverture alors que c'est la seule ligne touchant le moteur
    (smoke construit `Console(engine=None)` et stoppe le timer). Stub demandé.
  + rapport à corriger : affirme « aucun processus résiduel » ET « la fenêtre n'a pas pu
    être affichée ici ». Les deux ne peuvent pas être vraies.

Task 10: DÉTAIL — implémenteur a3e5ba37804ffe7c7, commit 3d10cd2, correction avant revue.
  VÉRIFIÉ PAR LE CONTRÔLEUR sur les 7 modes (l'implémenteur n'avait testé que le SSVEP) :
  les extraits `raw` et `neuro` contiennent des caractères non-ASCII (« µV à 250 Hz »,
  « en écart »), venus de `spec.summary` interpolé. Le SSVEP n'en a aucun PAR HASARD.
  => la règle « aucun accent » de MON brief était fausse ET intenable : NFKD mappe µ (U+00B5)
     vers μ grec (U+03BC), donc un strip ASCII transformerait « en µV » en « en V » —
     corruption d'une UNITÉ, bien pire qu'un accent. Python 3 lit ses sources en UTF-8 par
     défaut (PEP 3120) et `compile()` passe déjà sur les trois extraits.
  Correction : règle restreinte au GABARIT ; le test boucle désormais sur TOUT le registre
  (compile + nom de flux + toutes les voies + open_stream), les checks SSVEP spécifiques
  restant en plus car eux seuls prouvent que les voies suivent les RÉGLAGES.
  ⚠️ 2e fois qu'un test généralise depuis un seul échantillon (cf. Task 8, chauffe partagée).

Task 8: DÉTAIL — implémenteur a63ca3e5aba5d0871, commit 7766a11, correction avant revue.
  6 smokes verts. L'implémenteur a construit des PREUVES PAR L'ÉCHEC pour les 3 nouveaux
  tests (pas seulement celui exigé) : import pygame -> frontiere échoue en nommant raw.py ;
  set_published neutralisé -> cumul échoue sur la nouvelle assertion ; ligne du repos
  partagé inversée -> repos échoue.
  IL A TROUVÉ un défaut de MON brief : la vérification « chauffe partagée = max » NE PROUVE
  RIEN, car SSVEP_WARMUP_S == NEURO_WARMUP_S == 15,0. Elle passerait partage cassé. Idem
  pour l'égalité des `_warmup_until` en partie 1 (même `now` de départ).
  Correction demandée : partie 1b sur des contrats FABRIQUÉS aux valeurs distinctes, où le
  mode à la plus longue CHAUFFE n'est PAS celui au plus long REPOS — ce qui prouve d'un coup
  que les deux maximums sont calculés séparément et que la consigne suit la durée.

Task 7: PARKED (décision du contrôleur, à signaler à l'utilisateur) : le payload `status`
  perd `frequencies_hz`, `indices` et l'`instruction` de phase décodage. DÉLIBÉRÉ — avec N
  modes ces champs sont ambigus au niveau global, leurs équivalents par mode vivent dans
  `modes_state`. Aucun client du dépôt ne casse (examples/receiver.py réimprime le JSON).
  ⚠️ TÂCHE 16 : documenter ce retrait dans le contrat des flux, docs/SPEC.md §4.
Task 7: minor (deferred): `samples_published` ne compte que ce que le mode brut publie ;
  avec `--no-raw` il reste à 0 alors que l'acquisition tourne.
Task 7: minor (deferred): `rest_instruction` est un emplacement UNIQUE, pas rattaché au mode
  qui se repose -> peut mentir si deux modes se reposent en décalé. `modes_state[id].instruction`
  reste juste, donc la console s'en sort.
Task 7: minor (deferred): `src/core/dashboard.py` est CASSÉ à ce commit (passe `mode=`/`freqs=`
  au constructeur, soumet `set_mode`/`set_freqs`). État intermédiaire assumé — tâche 9 le
  supprime. ⚠️ mais il est documenté dans CLAUDE.md:46 et README.md:52,160 -> tâche 16.
Task 7: minor (deferred): `--no-raw` sans `--mode` démarre un moteur à ZÉRO mode sans le dire ;
  un `--mode inconnu` sort en traceback ValueError non attrapé.
Task 7: minor (deferred): `snapshot()` et `recent_window()` n'ont AUCUN appelant dans le dépôt
  (leur seul client était dashboard.py). Couverts à partir de la tâche 11.

Task 6: fix round 1/5 (4 addressed, 0 open ; commits 958ccfb..1fb9716)
Task 6: complete (commits 3f762db..1fb9716, review clean après 1 ronde)
  ⚠️ `server.py` garde encore SON `_json_float` local, désormais DOUBLON de `config.json_float`.
  TÂCHE 7 : importer `json_float` depuis config et supprimer la définition locale.
  Portage neuro jugé FIDÈLE (fenêtre brute, gardes, ordre du deadline, prolongation du repos,
  arrondis, throttle 2 s). `smoothing` tracé de bout en bout jusqu'à `IndexNormalizer`,
  rétro-compatible (défaut = NEURO_SMOOTH, tous les appelants vérifiés dont app.py).
  2 RÉGRESSIONS nées de MON brief :
  (a) le garde-fou NaN/Inf `_json_float` remplacé par un `round()` nu -> un NaN repartait dans
      `output()`/`state()`. Bug DÉJÀ corrigé le 2026-07-27 (une valeur non finie fait perdre
      TOUT l'état, pas une seule valeur). Invisible aux tests : l'autotest ne vérifiait la
      finitude que côté LSL, jamais côté affichage.
      -> `json_float` PROMU dans `core/config.py` (server.py ne peut pas être importé par
         modes/ : cycle). ⚠️ TÂCHE 7 : que `server.py` l'importe de config au lieu de
         redéfinir `_json_float` localement.
  (b) le nom du flux perdu du message « publication sur … » (même perte qu'en tâche 5).
Task 6: minor (deferred): le préfixe `[server]` -> `[neuro]` est un changement DÉLIBÉRÉ
  (plusieurs modes peuvent parler) — signalé comme dérive par le relecteur, assumé.
Task 6: minor (deferred): ordre alphabétique des imports rompu dans neuro.py:16-17. Cosmétique.

Task 5: minor (deferred): `_open()`/`_close()` contournés par l'autotest (`rt._opened = True`).
  Appel à `DecodedSSVEPPublisher(...)` vérifié à la main par le relecteur, correct.
  Sera exercé pour de vrai par la tâche 7.

Task 3: minor (deferred): `tick()` appelé AVANT `begin_rest()` saute la chauffe et entre
  directement en repos (sentinelle `_warmup_until is None`). Dégradation propre, non
  documentée, non testée. Non déclenchable via le moteur (tâche 7 appelle toujours
  `_begin_shared_rest` au démarrage).


Task 13: complete (commits 16c33b7..7197651 + correctif, revue faite)
  Implémenteur haiku (3 min) : les deux fichiers + le branchement + le smoke, conformes au brief.
  Relecture sonnet : conformité 6/7 étapes (l'étape 6 « regarder » non faite, pas d'écran),
  AUCUN défaut critique. Presque tous les constats venaient du BRIEF, pas de l'implémenteur.
  Tour de correction fait EN DIRECT par le coordinateur (pas de sous-agent : gain ~15 min) :
   - VIOLATION d'une contrainte globale : `2.5` et `SPAN = 3.0` recopiés en dur alors que
     `Z_MIN` et `NEURO_Z_SPAN` existent dans config.py (et que research/app.py importe déjà
     NEURO_Z_SPAN). Les deux interfaces auraient divergé au premier réglage. Corrigé par import.
   - `ActiveView._assure` n'enlevait jamais de barre : retirer une fréquence laissait une barre
     orpheline figée. Corrigé + test (3 barres -> 2).
   - `flux` montrait le SUFFIXE (`decoded_ssvep`) au lieu du nom résolvable
     (`EEG_API_Unicorn_decoded_ssvep`). Un étudiant lisant cette ligne ratait son resolve_byprop.
   - Smoke renforcé : seuil CHIFFRÉ (le mot « seuil » est en dur dans le template, l'assertion
     ne pouvait pas échouer), valeur de barre du neuro, et les DEUX boutons réellement cliqués.
  Smoke console : 26 vérifications, VERDICT OK. server --smoke et research --smoke verts.

Task 13: minor (deferred): le dict {"warmup":"chauffe","rest":"repos","running":"décode"} est
  dupliqué entre grid.py et mode_page.py — deux sources de vérité pour le même vocabulaire.
Task 13: minor (deferred): le mode « brut » retombe sur ActiveView et affiche un panneau vide —
  levé par la tâche 15, qui lui donne son propre rendu.
Task 13: note: le rapport de l'implémenteur annonce « 24 checks passed » là où sa propre
  transcription en montre 21. Rapport inexact sur son propre résultat, code correct.

⚠️ CHANGEMENT DE MÉTHODE (demandé par l'utilisateur : c'est le TEMPS qui coûte, pas les crédits)
  Mesure : le relecteur de la tâche 13 a pris 14 min 30 et 183k jetons pour un diff de 17 Ko,
  parce que mon prompt l'autorisait à explorer le dépôt et lui donnait 9 contraintes à vérifier.
  L'implémenteur, lui : 3 min. Donc pour les tâches 14-16 :
   - relecture BORNÉE AU DIFF, interdiction d'ouvrir le dépôt, contraintes réduites à ce que le
     diff peut violer ;
   - tours de correction faits en direct par le coordinateur quand les constats sont mécaniques ;
   - tâche 16 (documentation pure) écrite en direct, sans dispatche ;
   - ne pas re-vérifier soi-même ce qu'un rapport affirme, sauf soupçon.

Task 14: complete (commits 1b09d97..8f1c0b5 + correctif, revue bornée)
  Implémenteur haiku (4 min) : params_form.py + branchement + smoke contre un VRAI EngineServer.
  Rapport exact cette fois (33 vérifications annoncées, 33 comptées).
  Relecture sonnet BORNÉE AU DIFF (2 appels d'outils au lieu de 25) — un vrai défaut trouvé,
  que ma relecture préalable avait manqué :
   - CRITIQUE : `champ.setRange(param["min"], param["max"])` sur les kind int/float. Qt ÉCRÊTE
     en silence : sur le lissage du neuro (borné 0–0.99), saisir 5 envoyait 0.99 sans un mot.
     Le commentaire juste au-dessus prétendait l'inverse. C'est de la validation CÔTÉ CONSOLE,
     la seule chose que ce fichier interdit. Corrigé : bornes larges (-1e9, 1e9), le moteur
     refuse. Test ajouté sur le neuro (le SSVEP ne pouvait pas le voir : float_list, pas borné).
   - IMPORTANT : `set_values` ne se rejoue pas après un refus (les params du moteur n'ont pas
     changé), alors que son docstring promettait « après application ou refus ».
     ARBITRAGE : garder la saisie fautive dans le champ (on la corrige plutôt qu'on la retape),
     docstring corrigé, ET le refus dit désormais ce qui reste EN VIGUEUR — sinon un champ rouge
     oublié finit par se lire comme l'état du moteur.
   - MINEUR corrigé : le test du mode brut ne vérifiait pas que « aucun réglage pour ce mode »
     s'affiche (un cadre vraiment vide passait). Le label est maintenant un attribut testé.
  Smoke console : 38 vérifications, VERDICT OK.

Task 14: minor (deferred): `kind="choice"` renvoie toujours du str via currentText() — aucun mode
  n'a de paramètre choice aujourd'hui (vérifié sur les 7), donc spéculatif. À traiter le jour où
  un mode en déclare un.

MESURE de la relecture bornée : appels d'outils 25 -> 2, mais durée 14 min 30 -> 11 min et
  183k -> 105k jetons. Le coût dominant n'est donc PAS l'exploration du dépôt, c'est le
  raisonnement sur un gros diff. Prochain levier : modèle moins cher pour la relecture, pas
  des bornes plus serrées.

Task 15: complete (commits 516e2c1..4a2da60 + correctif numpy)
  Implémenteur haiku (4 min) : TracesView + build(family, ch_names) + branchement + smoke.
  DÉFAUT DU BRIEF trouvé AVANT dispatche (pré-vol du coordinateur, ~1 min) : `_FauxMoteur` du
  smoke n'a pas de `recent_window`, donc `ModePage.__init__` aurait levé un AttributeError en
  construisant la page « Brut » de la PREMIÈRE console. Correction dictée à l'implémenteur :
  c'est le moteur factice qui implémente l'interface consommée, pas la console qui se défend.
  Smoke console : 42 vérifications, VERDICT OK (le rapport annonçait 43).

  ⚠️ RELECTURE HAIKU = ÉCHEC. 84 s et 30k jetons (contre 11 min / 105k pour sonnet), mais :
   - un constat « CRITIQUE » FAUX : elle a confondu les deux moteurs du smoke (`moteur.recent`
     est posé sur le VRAI EngineServer, pas sur `_FauxMoteur`) ;
   - elle a déclaré les étapes 3 et 4 en ÉCHEC alors que le contexte fourni lui donnait le smoke
     vert, vérifié deux fois. Elle a contredit une preuve qu'on lui avait mise sous les yeux ;
   - elle n'a trouvé aucun des vrais points (rien d'important à trouver, mais rien non plus).
   Seul constat retenu : `import numpy` dans `update_from` -> remonté au module. CORRIGÉ.
  CONCLUSION : haiku ne relit pas. Pour la revue finale, prendre le modèle le plus capable.

Task 16: complete (documentation, écrite EN DIRECT par le coordinateur, sans sous-agent)
  - SPEC §3.1 : le TROISIÈME paquet `src/console/`, l'arbo corrigée (dashboard -> modes/),
    et ce que `core/modes/` apporte (le contrat génère grille + formulaires + extrait client).
  - SPEC §4 : contenu du flux `status` documenté champ par champ, ET le RETRAIT assumé de
    `frequencies_hz`, `indices` et de l'`instruction` en phase décodage (la dette du registre).
  - SPEC §12.2 : titre barré + encadré « décision renversée » AVANT le contenu d'origine, qui
    reste lisible ; bloc de renversement + table des 6 commandes à jour en fin de section.
  - SPEC §10, §14, dépendances §8 : à jour. §14 porte la dette matérielle (jamais ouvert en
    fenêtre, 3 vérifications casque à faire).
  - README : bloc « The console » à la place de « The dashboard », table de `src/console/`,
    `core/modes/` à la place de dashboard.py, smokes à jour.
  - CLAUDE.md : TROIS paquets, la console est un client du moteur, l'appli pygame ne donne plus
    accès qu'à 4 modes (pas 5), et l'avertissement « un seul des trois programmes à la fois ».
  Vérif de l'étape 6 : plus aucune référence morte hors §12.2 (où elles sont marquées comme
  renversées). Les TROIS smokes verts.

═══════════════════════════════════════════════════════════════════════════════
REVUE FINALE DE BRANCHE (2026-07-29)
═══════════════════════════════════════════════════════════════════════════════
⚠️ 4 relecteurs Opus lancés en parallèle sur des tranches de diff (210/138/69/55 Ko) :
   LES QUATRE SONT MORTS, « no progress for 600s », avant d'avoir fini de lire leur diff.
   Le chien de garde les tue pendant l'ingestion. LEÇON : ne pas donner un diff de plus de
   ~50 Ko à un sous-agent, et préférer l'ÉTAT FINAL des fichiers au diff pour une revue de
   branche. Relancé sur `src/console/` en donnant les 6 FICHIERS (pas le diff), sur sonnet.

Vérifications transverses faites par le coordinateur (celles qu'une revue par tâche ne voit pas) :
 - frontière `core` : aucun import de console/research/pygame/Qt (les occurrences sont de la
   prose dans des docstrings). Le test de `server.py --smoke` l'impose de toute façon.
 - aucune référence à un symbole supprimé (`dashboard`, `set_freqs`, `_setup_ssvep`,
   `_tick_ssvep`, `_collect_baseline`, `_restart_baseline`) nulle part dans `src/`.
 - vocabulaire public de `phase` intact : streaming / warmup / baseline / decoding.

TRI DES 27 MINEURS REPORTÉS
 RÉSOLUS par des tâches ultérieures (4) : dashboard.py cassé (supprimé t9) · brut sur ActiveView
   (TracesView t15) · snapshot()/recent_window() sans appelant (la console les appelle) ·
   BANDPASS importé sans usage dans ssvep.py (nettoyé t5).
 CORRIGÉS ICI (2) :
   - `--no-raw` sans `--mode` démarrait un moteur qui n'annonce rien et ne publie rien. Panne
     silencieuse dont le seul symptôme est un client qui ne trouve jamais son flux. Le moteur
     le DIT maintenant au démarrage.
   - le chemin « publier » (case -> signal tuile -> signal grille -> commande) n'était pas
     testé : c'est pourtant le seul geste de la grille qui change quelque chose sur le réseau.
     `_FauxMoteur.submit` retient désormais les commandes ; deux tests l'exercent, plus un
     troisième qui prouve qu'un rafraîchissement NE réémet PAS la commande (garde `blockSignals`).
 REJETÉ comme non-constat (1) : longueur de ligne > 100. `research/app.py` (pré-existant) a 62
   lignes dans ce cas et le dépôt n'a aucun fichier de configuration de style. Pas de règle,
   donc pas d'infraction.
 LAISSÉS (20) : couverture d'autotest (channels_for, _coerce int, serialize/catalog, open/close),
   cosmétiques (ordre d'imports), latents non atteignables (Param contraint à default=None,
   tick() avant begin_rest()), et inexactitudes de rapports d'implémenteurs (comptages de tests).
   Aucun n'a de conséquence pour un étudiant qui utilise le produit.

RELECTURE FINALE DE `src/console/` (sonnet, 8 min) — donnée en ÉTAT FINAL des 6 fichiers, pas en
diff. Elle a trouvé 3 défauts RÉELS qu'aucune revue par tâche n'avait vus, parce qu'ils naissent
de la COMPARAISON entre deux fichiers écrits à des moments différents. Tous vérifiés puis corrigés
(commit 786524e) :

 1. CRITIQUE — `MiniBars` (grid.py) faisait passer les scores d'un mode ACTIF et les indices d'un
    mode PASSIF par le même rendu, sans jamais consulter `family`. Il élisait un « meilleur » sur
    la valeur SIGNÉE mais dessinait la hauteur sur la valeur ABSOLUE. Deux conséquences :
      - un indice neuro se retrouvait surligné en bleu comme une SÉLECTION — le contresens exact
        que `live_views.py` documente vouloir empêcher, reproduit dans la tuile juste à côté ;
      - un score SSVEP très négatif dessinait la barre la PLUS HAUTE en gris pendant qu'un score
        positif plus petit était en bleu : la tuile désignait visuellement la mauvaise cible.
    Corrigé : rendu choisi par la famille ; la cible mise en avant est celle que le MOTEUR a
    retenue (`target_index`), plus aucun maximum recalculé côté console ; les valeurs signées se
    dessinent de part et d'autre d'un axe. Au passage, `2.5` et `3.0` étaient encore recopiés en
    dur ici — remplacés par `Z_MIN` et `NEURO_Z_SPAN`. C'est la TROISIÈME occurrence de ce défaut.
 2. CRITIQUE — `PassiveView` ajoutait une barre par indice apparu mais n'en retirait jamais, alors
    que sa cousine `ActiveView` le fait depuis la tâche 13. Un indice qui cesse d'être rapporté
    laissait sa barre figée sur sa dernière valeur, sans rien pour dire qu'elle ne mesure plus
    rien. Corrigé + test.
 3. CRITIQUE (latent) — `_resume()` indexait `sortie["target_index"]` et `sortie["freq_hz"]` en
    direct là où `ActiveView` utilise `.get()`. Cette ligne tourne 10 fois par seconde : un mode
    actif publiant des scores sans cible nommée aurait fait tomber TOUTE la grille sur un
    KeyError, pas seulement sa tuile. Non atteignable avec le registre actuel. Gardé.
 4. IMPORTANT — le bloc « brancher un client » n'était jamais rafraîchi à l'ARRÊT d'un mode :
    l'état disait « arrêté » et, juste en dessous, le nom du flux et l'extrait restaient présentés
    comme valides. Corrigé + test (et `_derniers_params` remis à None pour régénérer au retour).
 5. IMPORTANT — la table des libellés de phase était dupliquée entre grid.py et mode_page.py
    (mineur reporté en tâche 13, relevé ici comme important à juste titre : deux sources de vérité
    pour le MÊME mode). Une seule maison désormais : `console/__init__.py:PHASES_FR`.
 6. MINEUR — `sys.path.insert` mort dans banner.py (il n'importe rien de `core`). Retiré.

Smoke console : 50 vérifications, VERDICT OK. server et research : OK.

LEÇON DE MÉTHODE : donner à un relecteur l'ÉTAT FINAL des fichiers plutôt qu'un diff a été
nettement plus productif — les 3 critiques sont des incohérences ENTRE fichiers, invisibles dans
un diff par tâche. À refaire ainsi pour toute revue de fin de chantier.
