# Control plane — plan d'exécution

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** une application de la même machine règle, démarre et arrête un mode du moteur par LSL,
reçoit une réponse en anglais à chaque commande, et la console montre ce qu'elle a fait.

**Architecture :** un adaptateur `core/pilotage.py`, dans son propre fil, écoute les flux
`EEG_API_Unicorn_control` de sa machine, traduit chaque commande JSON en un appel de
`EngineServer.submit` (le seul juge), et publie la réponse sur `EEG_API_Unicorn_replies`. Avant
lui : clés de réglage publiques en anglais, refus traduisibles jusqu'au bout, `stream_in` ouvert,
`start_mode`/`stop_mode` idempotents, échec après acceptation signalé.

**Tech Stack :** Python 3.12, pylsl (`ContinuousResolver`, `StreamOutlet.wait_for_consumers`),
PySide6 (bandeau), autotests du dépôt (`chk()`, pas de pytest).

**Spec :** [docs/superpowers/specs/2026-10-22-control-plane-design.md](../specs/2026-10-22-control-plane-design.md)
— à lire avec ce plan ; chaque tâche y renvoie par son numéro de section.

## Global Constraints

- Noms de flux : `EEG_API_Unicorn_control` (entrant, créé par l'application) et
  `EEG_API_Unicorn_replies` (sortant, créé par le moteur), type `Markers`, une chaîne JSON par
  échantillon.
- Commandes réseau permises, et seulement elles : `start_mode`, `stop_mode`, `set_params`,
  `propose_params`.
- Le contrat réseau est en ANGLAIS : clés JSON, clés de réglage publiques, `reason` et `warning`
  (relus par `i18n.pour_le_contrat`, nombres avec un point), quelle que soit la langue de l'écran.
- Clés de réglage renommées : `cibles` (SSVEP) → `targets_on`, valeurs `ecran`/`physiques` →
  `screen`/`physical` ; `noms` (SSVEP) → `target_names` ; `bande_bas`/`bande_haut` →
  `band_low`/`band_high`, PARTOUT (décodage et entraînements).
- Seuls les flux de commandes de la MÊME machine (nom d'hôte comparé sans casse) sont écoutés.
- Aucun texte affiché en dur : `tr("…")` et `src/core/langues/{fr,en}/*.json`, les deux langues ;
  `[smoke-textes]` vert.
- Frontière : `core` n'importe rien hors de `core`, ni Qt ni pygame. `examples/control_client.py`
  n'importe que `pylsl` et la bibliothèque standard (un élève le copie dans son projet).
- Les tests n'écrivent jamais dans `data/` ni `seances/` (dossiers temporaires injectés).
- 🔴 Avant tout test qui ouvre LSL ou BrainFlow : lister les processus Python, LIRE la réponse,
  puis seulement lancer — jamais dans le même lot. Si une console tourne, s'arrêter et demander.
- Code, commentaires et messages d'autotest en français, selon `docs/charte-redaction.md` (élèves
  ingénieurs, au présent, sans l'histoire du chantier). `README.md` et `docs/control.md` en anglais.
- Commits en anglais, terminés par `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`,
  sur `main`, poussés.

## Review Focus

1. **Champs JSON de mauvais type** (`"params": [1]`, `"mode": 3`, `"ref": {}`) : refus motivé en
   anglais, le fil de l'adaptateur survit et répond à la commande suivante. → test en tâche 6.
2. **L'application redémarre** (son outlet disparaît, un nouveau revient sous le même nom) : la
   commande suivante reçoit encore sa réponse, sans redémarrer le moteur. → test en tâche 6.
3. **Le moteur s'arrête** : le fil d'écoute s'arrête en moins de 2 s, et `retirer_flux()` retire
   aussi le flux `replies` (pas de flux muet sous le même nom pour le moteur suivant). → tâches 6, 7.
4. **Une commande sans objet** (`propose_params` sur `mi`, `set_params` avec une clé sur `raw`) :
   refus en anglais, aucune exception. → test en tâche 7.
5. **Un `model` inconnu** : le refus liste les NOMS de fichiers, jamais les chemins du poste. →
   test en tâche 5.

---

### Task 1: Les clés de réglage publiques en anglais

Spec §6. Renommage mécanique, un seul vocabulaire, aucune table de traduction.

**Files:**
- Modify: `src/core/modes/contract.py` (`CIBLES_PHYSIQUES`, nouvelle `CIBLES_ECRAN`, `params_bande`,
  `bande_de`, contraintes `dans_la_bande` / `divise_le_refresh`, autotest)
- Modify: `src/core/modes/ssvep.py`, `src/core/modes/ssvep_mesure.py`, `src/core/modes/mi_calib.py`,
  `src/core/modes/p300_calib.py`, `src/core/modes/errp_calib.py`, `src/core/modes/cvep_calib.py`,
  `src/core/server.py`, `src/console/app.py`, `src/stimulus/ssvep.py`, et tout autre fichier que
  la recherche de l'étape 3 désigne ; `CLAUDE.md` s'il cite une clé renommée.

**Interfaces:**
- Produces : `contract.CIBLES_ECRAN = "screen"`, `contract.CIBLES_PHYSIQUES = "physical"` ;
  clés `targets_on`, `target_names`, `band_low`, `band_high`. Toutes les tâches suivantes les
  utilisent.
- NE change PAS : la clé `cibles` des ENTRAÎNEMENTS c-VEP et P300 (liste de noms, non publique),
  le champ `noms` des FICHIERS de modèle (`cvep_decoder`, `cvep_rcca`, `cvep_models`,
  `p300_models`), les clés de catalogue de textes (`mode.ssvep.cibles.ecran`…), `SSVEP_BANDE_HAUT`.

- [ ] **Step 1: Écrire le test qui échoue** — dans l'autotest de `src/core/modes/ssvep.py` :

```python
chk({p.key for p in SPEC.params} == {"targets_on", "freqs", "target_names", "refresh_hz",
                                     "alpha_hz", "z_min", "band_low", "band_high"},
    "les clés publiques du SSVEP sont en anglais")
chk(SPEC.defaults()["targets_on"] == CIBLES_ECRAN == "screen"
    and CIBLES_PHYSIQUES == "physical", "et leurs valeurs aussi")
```

- [ ] **Step 2: Le lancer** — `python src/core/modes/ssvep.py` → ÉCHEC sur ces deux lignes.
- [ ] **Step 3: Renommer.** Repérer : `grep -rn --include=*.py -E '"(cibles|noms|ecran|physiques)"|bande_(bas|haut)\b' src examples archive`.
  Renommer chaque occurrence SSVEP-décodage et chaque `bande_bas`/`bande_haut` (y compris en
  argument nommé, `proposer(bande_bas=8.0)`) ; garder ce que « NE change PAS » protège.
- [ ] **Step 4: Vérifier** (processus Python listés d'abord, aucune console) : `python src/core/modes/ssvep.py`,
  `contract.py`, `ssvep_mesure.py`, `mi_calib.py`, `p300_calib.py`, `errp_calib.py`,
  `cvep_calib.py`, `python src/stimulus/ssvep.py --smoke`, `python src/core/i18n.py`,
  `python src/core/server.py --smoke`, `python src/console/app.py --smoke` → tous `OK`. La
  recherche de l'étape 3 ne rend plus que les exceptions listées.
- [ ] **Step 5: Commit** — `Setting keys: the public names are English (targets_on, target_names, band_low, band_high)`.

---

### Task 2: Des refus qui restent traduisibles jusqu'au réseau

Spec §5 (« ⚠️ Ce n'est pas vrai aujourd'hui pour tous les refus »).

**Files:**
- Modify: `src/core/i18n.py` (classe `Joint`, fonction `joint`, `_relit`, `message_erreur`, autotest)
- Modify: `src/core/modes/contract.py` (`_check_bounds`, `dans_la_bande`, `separables`,
  `divise_le_refresh`, et toute autre concaténation d'un `Nombre`/`Texte` dans un refus)
- Modify: `src/core/config.py` (`propose_frequencies` : la liste `hors`, et autres jointures)

**Interfaces:**
- Produces : `i18n.joint(separateur: str, morceaux: Iterable) -> Joint` — un `str` qui garde ses
  morceaux ; `retraduit()` et `pour_le_contrat()` le réécrivent morceau par morceau.
  `i18n.message_erreur(e)` rend `e.args[0]` tel quel quand c'est un `Texte` (une `ValueError(tr(…))`
  reste traduisible).
- Règle : dans un texte de refus, plus jamais `nombre(x) + unite`, `", ".join(nombre…)` ni
  `", ".join(tr…)` — toujours `joint(…)`.

- [ ] **Step 1: Écrire les tests qui échouent.**
  Dans l'autotest de `i18n.py` (écran en français) :

```python
j = joint(", ", [nombre(1.5), nombre(2.5)])
chk(str(j) == "1,5, 2,5" and pour_le_contrat(j) == "1.5, 2.5", "joint se réécrit en anglais")
chk(isinstance(message_erreur(ValueError(tr("moteur.erreur_interne", type="X", detail="y"))), Texte),
    "une ValueError portant un Texte reste traduisible")
```

  Dans l'autotest de `contract.py`, une fonction `_refus_en_anglais()` : pour chaque famille —
  hors bornes (`alpha_hz=99`), diviseur (`refresh_hz=60, freqs=[17.0, 15.0, 20.0]`), hors bande,
  trop proches, clé inconnue, choix invalide, et `config.propose_frequencies` impossible —
  produire la raison écran en français (`choisir_langue("fr")`), puis la même avec l'écran en
  anglais, et exiger :

```python
chk(pour_le_contrat(raison_fr) == str(raison_en) and not re.search(r"\d,\d", pour_le_contrat(raison_fr)),
    f"refus {famille} : identique en anglais quelle que soit la langue de l'écran")
```

  Rétablir la langue d'origine à la fin (`try/finally`).
- [ ] **Step 2: Les lancer** — `python src/core/i18n.py`, `python src/core/modes/contract.py` → ÉCHEC.
- [ ] **Step 3: Implémenter** `Joint` (comme `Nombre` : `__reduce__` rend un `str`), sa branche dans
  `_relit`, `message_erreur`, puis remplacer les concaténations dans `contract.py` et `config.py`.
- [ ] **Step 4: Vérifier** — les deux autotests ci-dessus, `python src/core/modes/ssvep.py`,
  `python src/core/server.py --smoke`, `python src/console/app.py --smoke` → `OK`.
- [ ] **Step 5: Commit** — `Refusals stay translatable down to the network: joined texts and numbers re-render in English`.

---

### Task 3: `stream_in` ouvert — le moteur

Spec §7 (partie moteur) et §5 (« `stream_in` changé sur un mode qui TOURNE »).

**Files:**
- Modify: `src/core/lsl_io.py` (constantes `NOM_FLUX_COMMANDES = stream_name("control")`,
  `NOM_FLUX_REPONSES = stream_name("replies")`)
- Modify: `src/core/modes/contract.py` (`Param.ouvert`, `_coerce`, `avertissements`, autotest)
- Modify: `src/core/modes/p300.py`, `errp.py`, `cvep.py` (`stream_in` : `ouvert=True`)
- Modify: `src/core/modes/registry.py` (sérialise `"ouvert"` dans le catalogue des réglages)
- Modify: `src/core/markers.py` (`flux_de_marqueurs_visibles` exclut les noms qui commencent par
  `NOM_FLUX_COMMANDES` et `NOM_FLUX_REPONSES`, comme il exclut déjà `status`)
- Modify: `src/core/server.py` (`submit` : `set_params` et `start_mode`)
- Modify: `src/core/langues/fr/moteur.json`, `src/core/langues/en/moteur.json`

**Interfaces:**
- Produces : `Param.ouvert: bool = False` — un `choice` ouvert accepte tout nom non vide (espaces
  retirés) SANS appeler `choices_now()` ; vide ou non-chaîne → refus `moteur.contrat.nom_vide`.
  `contract.avertissements(spec, values) -> list` — un `Texte` (`moteur.contrat.flux_pas_vu`,
  valeurs `reglage`, `nom`) par réglage ouvert dont la valeur n'est pas dans `choices_now()` ; c'est
  le SEUL appel réseau de la validation.
  L'accusé de `set_params` et `start_mode` gagne `"warning"` : `None`, ou les avertissements
  joints (`i18n.joint(" ", …)`), plus `moteur.reglage.stream_in_au_redemarrage` (valeur `mode`)
  quand `stream_in` change sur un mode qui tourne.
- Consumes : `i18n.joint` (tâche 2).

- [ ] **Step 1: Écrire les tests qui échouent.**
  Autotest `contract.py` : un `Param("stream_in", kind="choice", ouvert=True, choices_fn=espion)` —
  `validate` de `"MonJeu_markers"` accepté avec `espion` appelé 0 fois ; `""` et `3` refusés ;
  `avertissements` rend 1 texte pour un nom absent de l'espion, 0 pour un nom présent.
  Autotest `markers.py` : avec un faux `resolve_byprop` qui rend `EEG_API_Unicorn_control`,
  `EEG_API_Unicorn_control_smoke_12`, `EEG_API_Unicorn_replies` et `MonJeu_markers`, la liste vaut
  `(MARKER_STREAM_DEFAULT, "MonJeu_markers")`.
  Smoke moteur, nouvelle fonction `_smoke_stream_in_ouvert()` : `set_params` p300
  `{"stream_in": "Absent_xyz"}` sur mode arrêté → `accepted`, `differe`, `"Absent_xyz"` dans
  `warning` ; avec un faux runtime p300 dans `srv.active` (motif de `_smoke_marqueurs_stream_in`),
  changer `stream_in` → `warning` contient le texte `stream_in_au_redemarrage`.
- [ ] **Step 2: Les lancer** — `python src/core/modes/contract.py`, `python src/core/markers.py`,
  `python src/core/server.py --smoke` → ÉCHEC sur ces assertions.
- [ ] **Step 3: Implémenter** dans les fichiers listés. Les deux nouvelles clés de catalogue en FR et
  EN ; l'aide du `stream_in` des trois modes dit qu'un nom pas encore visible est accepté.
- [ ] **Step 4: Vérifier** — les trois commandes de l'étape 2 et `python src/core/i18n.py` → `OK`.
- [ ] **Step 5: Commit** — `stream_in is an open choice: a name not yet on the network is accepted with a warning`.

---

### Task 4: `stream_in` ouvert — la console (constat n° 3)

Spec §7 (partie console). `docs/qa.md`, constat ouvert n° 3 : le scénario exact à empêcher.

**Files:**
- Modify: `src/console/params_form.py` (choix ouvert : liste ÉDITABLE ; `set_choices` et
  `set_values` gardent la valeur retenue même absente de la liste, marquée
  `tr("console.params.pas_vu_reseau")` ; `values()` rend le nom brut, sans la marque)
- Modify: `src/console/mode_page.py` (`_appliquer` : accepté avec `warning` → `show_avertissement`)
- Modify: `src/core/langues/fr/console.json`, `src/core/langues/en/console.json`
- Test: `src/console/app.py` (smoke)

**Interfaces:**
- Consumes : `"ouvert"` dans le catalogue des réglages, `"warning"` dans l'accusé (tâche 3).

- [ ] **Step 1: Écrire le test qui échoue** — smoke console, page P300 :

```python
form.set_values({"stream_in": "MonJeu_markers"})
form.set_choices("stream_in", [MARKER_STREAM_DEFAULT])          # le jeu est fermé
chk(form.values()["stream_in"] == "MonJeu_markers"
    and tr("console.params.pas_vu_reseau") in form.champs["stream_in"].currentText(),
    "la valeur retenue reste choisie, marquée « pas vu sur le réseau » (constat 3)")
form.champs["stream_in"].setEditText("Tape_avant")
chk(form.values()["stream_in"] == "Tape_avant", "on peut taper le nom de son flux à l'avance")
```

  Et un accusé faux `{"accepted": True, "differe": True, "warning": "W"}` passé à `_appliquer` →
  l'étiquette d'avertissement du formulaire montre `W`.
- [ ] **Step 2: Le lancer** — `python src/console/app.py --smoke` → ÉCHEC.
- [ ] **Step 3: Implémenter.**
- [ ] **Step 4: Vérifier** — `python src/console/app.py --smoke`, `python src/core/i18n.py` → `OK`.
- [ ] **Step 5: Commit** — `Console: the retained marker stream is never replaced in silence, and can be typed ahead`.

---

### Task 5: Le moteur — idempotence, `model` par nom de fichier, échec signalé

Spec §5 (idempotence, échec après acceptation) et §6 (`model`).

**Files:**
- Modify: `src/core/server.py` (`submit`, `_start`, `_drain_commands`, nouvelle `_mettre_en_file`)
- Modify: `src/core/modes/contract.py` (`_coerce` d'un `choice` ; refus `choix_invalide`)
- Test: `src/core/server.py` (smoke, nouvelle `_smoke_reseau_moteur()`), `contract.py` (autotest)

**Interfaces:**
- Produces :
  - `EngineServer.submit(self, command, reseau=None, **params)` — `reseau` est un jeton opaque
    (la tâche 6 passe `(ref, cmd, mode)`) ; non `None`, il voyage dans la file avec la commande.
  - `EngineServer.sur_echec` — `None` ou un appelable `(reseau, command, raison)`, appelé par la
    BOUCLE quand une commande portant un jeton échoue après acceptation : refus de `_start`,
    exception attrapée par `_drain_commands` (raison : `i18n.message_erreur(e)`). Jamais pour une
    commande sans jeton (la console).
  - `start_mode` sur des modes qui tournent : leurs `params` passent par le chemin de
    `set_params` (fusion, validation, file) ; accusé `accepted`, `"deja": [ids qui tournaient]`.
    Les modes arrêtés de la même commande démarrent normalement.
  - `stop_mode` sur un mode arrêté : `{"accepted": True, "command": "stop_mode", "id": …, "deja": True}`,
    rien en file.
  - `_coerce` d'un `choice` : une valeur absente de la liste mais égale au NOM DE FICHIER
    (`os.path.basename`) d'un seul choix rend ce choix complet. `choix_invalide` liste les noms de
    fichier quand les choix sont des chemins.

- [ ] **Step 1: Écrire les tests qui échouent.**
  Autotest `contract.py` : choix `["C:/d/mi_model_A.joblib", "C:/d/mi_model_B.joblib"]` →
  `"mi_model_A.joblib"` rend `"C:/d/mi_model_A.joblib"` ; `"nope"` refusé, la raison contient
  `mi_model_A.joblib` et pas `C:/d/`.
  Smoke moteur `_smoke_reseau_moteur()` (board de test, `data_dir`/`seances_dir` temporaires) :
  `start_mode ssvep` puis, une fois actif, `start_mode ssvep params={"alpha_hz": v}` (`v` : une
  valeur valide différente de l'actuelle) → accepté, `deja == ["ssvep"]`, et après un tour
  `active["ssvep"].params["alpha_hz"] == v` ;
  `stop_mode neuro` (arrêté) → accepté, `deja is True` ; `sur_echec` = collecteur, un
  `runtime_cls` qui lève dans son constructeur, `submit("start_mode", id=…, reseau=("r1", "start_mode", "ssvep"))`
  → après un tour, collecteur `== [(("r1", "start_mode", "ssvep"), "start_mode", <raison>)]` ; la
  même panne sans `reseau` → collecteur inchangé.
- [ ] **Step 2: Les lancer** — `python src/core/modes/contract.py`, `python src/core/server.py --smoke` → ÉCHEC.
- [ ] **Step 3: Implémenter.** Les assertions existantes qui attendaient le refus « déjà démarré » /
  « n'est pas démarré » sur ces deux cas changent avec la règle (spec §13) ; le dire dans le
  commit. Le refus `deja_demarre` reste utilisé ailleurs s'il l'est ; sinon sa clé de catalogue
  part (`[smoke-textes]` le signale).
- [ ] **Step 4: Vérifier** — les deux commandes de l'étape 2, `python src/console/app.py --smoke` → `OK`.
- [ ] **Step 5: Commit** — `Engine: start and stop are idempotent, a model is named by its file, a failure after acceptance is signalled`.

---

### Task 6: `core/pilotage.py` — l'adaptateur LSL

Spec §4, §5. Testé seul, contre un FAUX moteur : aucune session BrainFlow.

**Files:**
- Create: `src/core/pilotage.py` (module + autotest `python src/core/pilotage.py`)
- Modify: `src/core/langues/fr/moteur.json`, `src/core/langues/en/moteur.json`

**Interfaces:**
- Consumes : `lsl_io.NOM_FLUX_COMMANDES`, `NOM_FLUX_REPONSES`, `_source_id` (tâche 3) ;
  `submit(command, reseau=…, **kw)` et ses accusés `deja`, `differe`, `warning` (tâches 3, 5) ;
  `i18n.pour_le_contrat`.
- Produces :
  - `COMMANDES_RESEAU = ("start_mode", "stop_mode", "set_params", "propose_params")`
  - `@dataclass Commande(ref, cmd, mode, kwargs, refus)` et `lire_commande(texte: str) -> Commande`
    — `kwargs` est prêt pour `submit(cmd, **kwargs)` (`mode` → `id`, `params`, `key`) ; `refus` est
    un `Texte` (`moteur.reseau.json_illisible`, `commande_non_permise` avec la liste des quatre,
    `champ_invalide` avec le champ) ou `None`. `ref` : chaîne ou nombre, sinon refus et `ref` nul.
  - `reponse(commande: Commande, ack: dict) -> dict` — `{"ref", "cmd", "mode", "accepted"}` +
    `"reason"` si refus ; `"params"`, `"deferred"` (← `differe`) ; `"already_running"`
    (`start_mode` : `commande.mode in ack["deja"]`) / `"already_stopped"` (`stop_mode` :
    `ack.get("deja") is True`) ; `"key"`, `"value"`, `"warning"` pour `propose_params` ;
    `"warning"` si présent. Tout passé par `pour_le_contrat`.
  - `echec(ref, cmd, mode, raison) -> dict` — `{"ref", "cmd", "mode", "event": "failed", "reason"}`.
  - `de_cette_machine(infos, hote=None) -> list` — les `StreamInfo` dont `hostname()` égale
    `socket.gethostname()` sans casse.
  - `class Pilotage(engine, nom_flux=NOM_FLUX_COMMANDES, hote=None)` :
    `__init__` crée l'outlet de réponses (source_id `_source_id("replies", engine.instance)`) ;
    `demarrer()` lance le fil (un `ContinuousResolver(prop="name", value=nom_flux)`, un inlet par
    flux local, `pull_sample(timeout=0.0)`, pause ~20 ms ; un inlet en erreur est lâché et
    recréé à la découverte suivante ; un flux étranger : un message au terminal, une fois) ;
    `arreter()` (le fil finit en < 2 s) ; `fermer()` (lâche l'outlet) ;
    `traiter(texte: str) -> dict` (lit, soumet, construit la réponse, l'inscrit au journal — le fil
    publie ce qu'elle rend) ; `signaler_echec(reseau, command, raison)` (sûr depuis n'importe quel
    fil : une file que le fil d'écoute publie) ; `journal() -> list[dict]` — les 10 dernières
    entrées `{"t": time.monotonic(), "cmd", "mode", "accepted", "raison", "event", "deja"}`,
    `raison` dans la langue de l'écran (pour la console).

- [ ] **Step 1: Écrire l'autotest qui échoue** — `_selftest()` dans `pilotage.py`, écran en français :
  - `lire_commande` : les quatre commandes valides ; `"pas du json"` ; `"[1]"` ;
    `{"cmd": "start_calibration"}` (raison qui liste les quatre) ; `{"cmd": "set_params", "mode": 3}` ;
    `{"cmd": "set_params", "mode": "ssvep", "params": [1]}` ; `{"cmd": "stop_mode", "mode": "ssvep", "ref": {}}`.
  - `reponse` : `differe` → `deferred` ; `deja` → `already_running` / `already_stopped` ; une
    raison `Texte` française sort en anglais, sans `\d,\d`.
  - `de_cette_machine` sur de faux `StreamInfo` (`POSTE-1`, `autre`, `poste-1`, hôte `poste-1`).
  - En LSL réel, contre `FauxMoteur` (`submit` enregistre ses appels, rend des accusés écrits à
    la main) et un flux `EEG_API_Unicorn_control_autotest_<pid>` : le client attend
    `wait_for_consumers(5.0)`, ouvre l'inlet de réponses (`open_stream()`) AVANT d'envoyer, envoie
    trois commandes, reçoit trois réponses aux bons `ref` ; `signaler_echec` → un `"event": "failed"`
    au bon `ref` ; Review Focus 1 : une commande mal typée reçoit un refus, la suivante une
    réponse ; Review Focus 2 : l'outlet client fermé puis recréé sous le même nom → la commande
    suivante est servie ; Review Focus 3 : `arreter()` → fil mort en < 2 s.
- [ ] **Step 2: Le lancer** — `python src/core/pilotage.py` → ÉCHEC (module vide ou absent).
- [ ] **Step 3: Implémenter** le module et les trois clés `moteur.reseau.*` en FR et EN.
- [ ] **Step 4: Vérifier** — `python src/core/pilotage.py`, `python src/core/i18n.py`,
  `python src/core/server.py --smoke` (frontière : `pilotage.py` reste dans `core`) → `OK`.
- [ ] **Step 5: Commit** — `core/pilotage: the LSL adapter that turns app commands into engine commands, with English replies`.

---

### Task 7: Le moteur écoute, le client exemple, le smoke de bout en bout

Spec §4, §9, §10.

**Files:**
- Modify: `src/core/server.py` (constructeur, `run`, `retirer_flux`, `_state`, `snapshot`,
  `[smoke-exemples]`, nouvelle `_smoke_pilotage()` appelée par `--smoke`)
- Create: `examples/control_client.py`

**Interfaces:**
- Consumes : `Pilotage` (tâche 6), `sur_echec` (tâche 5).
- Produces :
  - `EngineServer.__init__(…, flux_commandes=NOM_FLUX_COMMANDES)` ; `self.pilotage = Pilotage(self, nom_flux=flux_commandes)` ;
    `self.sur_echec = self.pilotage.signaler_echec`. `run()` démarre l'écoute après l'annonce des
    flux et l'arrête dans son `finally` ; `retirer_flux()` appelle aussi `pilotage.fermer()`.
  - `_state()["streams"]` liste `EEG_API_Unicorn_replies` ; `snapshot()["pilotage"] = self.pilotage.journal()`.
  - `[smoke-exemples]` : les suffixes connus incluent `control` et `replies`.
  - `examples/control_client.py [--stream NOM] [--timeout S]` — en anglais, commenté pour un
    élève. Déroulé, chaque réponse imprimée : (1) outlet de commandes, inlet de réponses de CETTE
    machine ouvert, `wait_for_consumers` (sinon « engine not found », code 2) ; (2) `set_params`
    ssvep `{"refresh_hz": 30}` SEUL → refusé, et le script explique pourquoi c'est attendu ;
    (3) `propose_params` ssvep `{"refresh_hz": 30}` ; (4) `set_params` `{"refresh_hz": 30, "freqs": <proposées>}` ;
    (5) `start_mode` ssvep ; (6) attendre `"ssvep"` dans `status.modes`, lire 3 échantillons de
    `decoded_ssvep` de cette machine ; (7) `stop_mode` ssvep. Code 0 si chaque étape a la réponse
    attendue, 1 sinon (en disant laquelle). Une réponse se reconnaît à son `ref`, attendue 5 s.

- [ ] **Step 1: Écrire le test qui échoue** — `_smoke_pilotage()` : moteur sur le board de test
  (`data_dir`/`seances_dir` temporaires, `flux_commandes=f"{NOM_FLUX_COMMANDES}_smoke_{os.getpid()}"`),
  `run(duration_s=…, baseline_s=1.0, warmup_s=0.5)` dans un fil, écran en français. Puis :
  - le client exemple en SOUS-PROCESSUS (`sys.executable examples/control_client.py --stream <nom> --timeout 30`)
    → code 0 ; sa sortie contient `"accepted": false` à l'étape 2, avec une raison sans `\d,\d` ;
  - `snapshot()["pilotage"]` a au moins 5 entrées ; `status` liste `EEG_API_Unicorn_replies` ;
  - perte avant connexion (spec §5, piège 1) : un outlet neuf qui pousse SANS attendre n'a aucune
    réponse en 2 s ; après `wait_for_consumers`, la même commande en a une ;
  - Review Focus 4 : `srv.pilotage.traiter('{"cmd":"propose_params","mode":"mi","ref":"a"}')` et
    `'{"cmd":"set_params","mode":"raw","params":{"x":1},"ref":"b"}'` → refus en anglais, sans exception ;
  - la boucle ne bloque pas : pendant 20 `set_params` p300 `stream_in` envoyés d'affilée,
    `srv.samples` avance d'au moins 80 % de ce que 250 Hz donnent sur la même durée ;
  - Review Focus 3 : après la fin de `run` et `retirer_flux()`, le fil d'écoute est mort et aucun
    flux `EEG_API_Unicorn_replies` de cette instance n'est résolu en 1 s.
- [ ] **Step 2: Le lancer** (processus Python listés d'abord) — `python src/core/server.py --smoke` → ÉCHEC.
- [ ] **Step 3: Implémenter** le câblage du moteur, puis l'exemple.
- [ ] **Step 4: Vérifier** — `python src/core/server.py --smoke`, `python src/console/app.py --smoke`,
  `python examples/control_client.py --help` → `OK` / aide affichée.
- [ ] **Step 5: Commit** — `Engine listens to app commands on its machine; example client, end-to-end smoke`.

---

### Task 8: Le bandeau montre ce que l'application a fait

Spec §8.

**Files:**
- Modify: `src/console/banner.py` (étiquette `application`, mise à jour depuis `state["pilotage"]`)
- Modify: `src/core/langues/fr/console.json`, `src/core/langues/en/console.json`
- Test: `src/console/app.py` (smoke)

**Interfaces:**
- Consumes : `snapshot()["pilotage"]` (tâche 7) — `t` est un `time.monotonic()` du même processus.
- Produces : `banner.AFFICHAGE_PILOTAGE_S = 10.0` ; `Banner.application` (QLabel) montre la
  dernière entrée de moins de 10 s, ou rien. Textes : `console.bandeau.application.start_mode`
  (« Application : démarrage de « {mode} » demandé »), `.stop_mode` (arrêt demandé),
  `.set_params` (réglages appliqués), `.set_params_retenu` (réglages retenus, mode arrêté),
  `.propose_params`, `.refus` (« … refusé — {raison} », rouge), `.echec` (« … a échoué — {raison} »,
  rouge). `{mode}` est le libellé du mode dans la langue de l'écran.

- [ ] **Step 1: Écrire le test qui échoue** — smoke console, bandeau nourri d'états faits main :
  entrée `start_mode` acceptée à `t = monotonic()` → le texte contient le libellé SSVEP ; entrée
  refusée → texte rouge avec la raison ; `event: "failed"` → texte `.echec` ; entrée à
  `t = monotonic() - 11` → vide ; changement de langue → le texte suit.
- [ ] **Step 2: Le lancer** — `python src/console/app.py --smoke` → ÉCHEC.
- [ ] **Step 3: Implémenter.** La largeur de la fenêtre ne bouge pas (l'étiquette passe à la ligne,
  comme les autres messages du bandeau ; l'assertion « un texte de bandeau très long n'ÉLARGIT pas
  la fenêtre » reste verte).
- [ ] **Step 4: Vérifier** — `python src/console/app.py --smoke`, `python src/core/i18n.py` → `OK`.
- [ ] **Step 5: Commit** — `Console: the banner says what the app just asked, and why it was refused`.

---

### Task 9: La documentation

Spec §11, §12. Relire chaque phrase contre le code (une doc non relue a déjà menti dans ce dépôt).

**Files:**
- Create: `docs/control.md` (anglais, public, sur le modèle de `docs/markers.md`)
- Modify: `README.md`, `docs/SPEC.md` (§4, §12.1, §14), `CLAUDE.md`, `docs/qa.md`, `docs/recette.md`

- [ ] **Step 1: `docs/control.md`** — les deux flux ; les quatre commandes et leurs champs ; la forme
  des réponses (`deferred`, `already_running`, `already_stopped`, `warning`, `event: "failed"`) ;
  les clés de réglage publiques PAR MODE (lues dans `registry.MODES`, pas recopiées de mémoire) ;
  `model` par nom de fichier ; la règle « même machine » ; les deux pièges LSL du spec §5 ;
  l'ordre recommandé `set_params` puis `start_mode` ; le geste du SSVEP (proposer, puis poser
  rafraîchissement et fréquences ensemble) ; un extrait de `examples/control_client.py`.
- [ ] **Step 2: README** — une section « Drive the engine from your app », qui renvoie à
  `docs/control.md` et à l'exemple.
- [ ] **Step 3: SPEC** — §4 : `control` livré, `replies` ajouté ; §12.1 : l'adaptateur existe ; §14 :
  le control plane `[fait 2026-10-22]`, le correctif `stream_in` `[fait]`.
- [ ] **Step 4: CLAUDE.md** — un paragraphe « control plane » (ce que l'application peut faire, les
  deux flux, la règle même machine, le dernier gagne, `core/pilotage.py`) ; `python src/core/pilotage.py`
  dans les commandes utiles ; la ligne de `server.py` qui disait « pas de control plane entrant »
  (docstring, `src/core/server.py:36`) corrigée aussi.
- [ ] **Step 5: QA et recette** — `docs/qa.md` : le constat n° 3 passe en « traité » ; un point
  **1.24** du bloc 1 (préconditions rappelées à CHAQUE sous-point : console ouverte sur le board
  de test, aucun mode démarré) : lancer `python examples/control_client.py` dans un second
  terminal → le bandeau dit chaque commande, le refus de l'étape 2 s'y lit, la tuile SSVEP passe
  en marche puis s'arrête, la page SSVEP montre 30 Hz et les fréquences proposées ; un point
  **☐ 2.x** : piloter le moteur depuis une application d'un autre langage (Unity si disponible).
  `docs/recette.md` : le pourquoi (dernier gagne, même machine, idempotence, pertes LSL).
- [ ] **Step 6: Vérifier** — `python src/core/server.py --smoke` (`[smoke-exemples]`,
  `[smoke-textes]`) → `OK`.
- [ ] **Step 7: Commit** — `Docs: the control plane contract (docs/control.md), README, SPEC, CLAUDE.md, QA 1.24`.
