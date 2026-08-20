# Le c-VEP sur le réseau — plan d'implémentation

> **Pour les agents :** SOUS-COMPÉTENCE REQUISE — utiliser `superpowers:subagent-driven-development`
> (recommandé) ou `superpowers:executing-plans` pour exécuter ce plan tâche par tâche. Les étapes
> utilisent des cases à cocher (`- [ ]`).

**But :** publier le c-VEP comme 6e et dernier mode du moteur (`--mode cvep` → `decoded_cvep`), avec
un émetteur autonome qui tient l'horloge du code par un marqueur par cycle.

**Architecture :** trois programmes, le patron du P300 et de l'ErrP. Le moteur décode et publie ;
`research/cvep_stimulus.py` affiche le clignotement et publie `{"mode":"cvep","event":"cycle",
"refresh":…}` horodaté au flip, sans jamais ouvrir le casque ; l'appli pygame ne garde que la
calibration. La phase du code se reconstruit côté moteur par
`int((E - T_dernier_cycle) * refresh) % code_len`, où `E` est l'instant LSL de fin de fenêtre.

**Pile technique :** numpy, scipy, pylsl, pygame (émetteur seulement), **pyntbci** (nouveau, pour le
décodeur rCCA).

**Spec :** [docs/superpowers/specs/2026-08-20-cvep-moteur-design.md](../specs/2026-08-20-cvep-moteur-design.md)

## Contraintes globales

Elles lient **toutes** les tâches, sans être répétées dans chacune.

- `src/core/` n'importe **jamais** `src/research/` ni `src/console/`, et ne contient ni pygame ni Qt.
  Vérifié par `python src/core/server.py --smoke` (`_smoke_frontiere`).
- `src/research/` et `src/console/` peuvent importer `src/core/` ; l'inverse est interdit.
- **La console est un CLIENT du moteur** : aucune logique qu'il ne possède déjà, pas de validation
  côté interface, pas de catalogue recopié.
- Code et commentaires **en français** ; `README.md`, `docs/markers.md` et les messages de commit
  **en anglais**. `docs/SPEC.md` et `docs/recette.md` restent en français.
- Tout doit être testable **sans casque**.
- **Aucun test n'écrit dans le vrai `data/`** : dossier temporaire + nettoyage dans un `finally`. Ce
  sont des enregistrements EEG d'une personne identifiable sur un dépôt PUBLIC.
- Un autotest **sort en 1** quand il échoue. Un autotest qui ne peut pas échouer ne teste rien.
- ⚠️ **Un seul programme du projet à la fois** pendant les tests : les noms de flux LSL sont un
  contrat public, donc identiques pour toutes les instances — un second programme répond à la place
  de celui qu'on teste. Vérifier qu'aucun python du projet ne traîne avant de conclure à un échec.
- Constantes exactes, déjà dans `src/core/config.py`, à utiliser telles quelles :
  `CVEP_BITS=6`, `CVEP_TAPS=(6,5)`, `CVEP_CHANNELS=[4,5,6,7]`, `CVEP_BAND=(2.0,45.0)`,
  `CVEP_DECISION_CYCLES=2`, `CVEP_CORR_MIN=0.26`, `CVEP_MARGIN=0.09`, `CVEP_VOTE_LEN=3`,
  `CVEP_MIN_VOTES=2`, `CVEP_N_TARGETS=6`, `CVEP_MODEL_PATH=data/cvep_model.npz`,
  `CVEP_RCCA_ENC=0.30`.
- **Ne pas rouvrir** : le *dynamic stopping* et les **codes Gold distincts** sont réfutés, mesurés.
- Le code fait **63 frames**, soit **1,05 s à 60 Hz**.

---

## Structure des fichiers

| fichier | responsabilité |
|---|---|
| `src/core/cvep_code.py` | *(déménagé)* m-séquence, lags, `build_targets`, `is_on` |
| `src/core/cvep_decoder.py` | *(déménagé)* `CVEPModel` (eCCA), `CVEPDecoder`, `bandpass` |
| `src/core/cvep_rcca.py` | *(créé, moitié de l'ancien)* `RCCAModel`, `RCCADecoder` |
| `src/core/cvep_models.py` | *(créé)* catalogue des modèles : `modeles_disponibles`, `charger` |
| `src/core/modes/cvep.py` | *(créé)* `CVEPRuntime` + `SPEC` : phase, états muets, décision |
| `src/core/lsl_io.py` | *(modifié)* `cvep_channel_labels`, `DecodedCVEPPublisher` |
| `src/core/modes/registry.py` | *(modifié)* enregistrement du mode |
| `src/research/cvep_stimulus.py` | *(créé)* l'émetteur + **le test de phase** |
| `src/research/cvep_rcca.py` | *(réduit)* `make_distinct_codes`, `build_targets_rcca` seulement |
| `src/research/cvep_calibrate.py` | *(modifié)* entraîne les DEUX décodeurs |
| `requirements.txt` | *(modifié)* `pyntbci` |

---

## Task 1 : déménager le décodage dans `core/`, et PROUVER que le modèle survit

**Files:**
- Create: `src/core/cvep_code.py`, `src/core/cvep_decoder.py` (déplacés depuis `src/research/`)
- Delete: `src/research/cvep_code.py`, `src/research/cvep_decoder.py`
- Modify: les importeurs — `src/research/app.py`, `src/research/cvep_calibrate.py`,
  `src/research/cvep_analyze.py`, `src/research/cvep_rcca.py`, `README.md`,
  `src/research/__init__.py`

**Interfaces:**
- Produces: `core.cvep_code.build_targets(commands=None, n_bits=CVEP_BITS, taps=CVEP_TAPS)
  -> (plan, code)` où `plan` est une liste de dicts portant `name`, `angle`, `jx`, `jy`, `lag`,
  `code` ; `core.cvep_code.is_on(frame, target_code) -> bool` ;
  `core.cvep_decoder.CVEPModel.load(path) -> CVEPModel` ;
  `CVEPModel.scores(window, phase, lags, n_cycles=None) -> {lag: corrélation}` ;
  `CVEPDecoder(model, plan, corr_min, margin, n_cycles).classify(window, phase)
  -> (commande|None, {nom: corrélation})`.

- [ ] **Étape 1 : écrire le test qui échoue** — dans `src/core/cvep_decoder.py`, au `_selftest()`.

⚠️ **C'est LE test de cette tâche.** Le P300 et l'ErrP ont perdu leurs modèles au déménagement
(pickle `joblib` référençant un module disparu) et il a fallu ré-entraîner deux fois. Le c-VEP
écrit du `np.savez` de tableaux purs, donc il devrait survivre — **ce test transforme ce « devrait »
en fait mesuré**.

```python
    # Le modèle SURVIT au déménagement — la question qui a coûté deux ré-entraînements.
    # On écrit un modèle, on le relit, et on vérifie que les tableaux sont identiques BIT
    # POUR BIT. Pas de pickle ici (np.savez de tableaux purs), donc aucun nom de module
    # n'est gravé dans le fichier : c'est ce qui rend `core.cvep_decoder` capable de relire
    # ce que `research.cvep_decoder` avait écrit.
    import tempfile as _tf, shutil as _sh
    tmp = _tf.mkdtemp(prefix="cvep_selftest_")
    try:
        m = CVEPModel(fs=250.0, refresh=60.0, code_len=63, band=CVEP_BAND, channels=[4, 5, 6, 7])
        m.w = np.arange(4, dtype=float) * 1.5
        m.template = np.arange(63, dtype=float) / 7.0
        m.cv_ = 0.87
        chemin = m.save(_os.path.join(tmp, "cvep_model.npz"), n_targets=6)
        relu = CVEPModel.load(chemin)
        chk(np.array_equal(relu.w, m.w) and np.array_equal(relu.template, m.template),
            "un modèle écrit puis relu rend les MÊMES tableaux, bit pour bit")
        chk(relu.channels == [4, 5, 6, 7] and relu.code_len == 63 and relu.n_targets == 6,
            f"...et ses métadonnées ({relu.channels}, {relu.code_len}, {relu.n_targets})")
        chk("cvep_decoder" not in open(chemin, "rb").read(2048).decode("latin-1"),
            "le fichier ne contient AUCUN nom de module — c'est ce qui le rend déplaçable")
    finally:
        _sh.rmtree(tmp, ignore_errors=True)
```

- [ ] **Étape 2 : lancer le test, vérifier qu'il échoue**

Lancer : `python src/core/cvep_decoder.py`
Attendu : `ModuleNotFoundError` — le fichier n'existe pas encore dans `core/`.

- [ ] **Étape 3 : déplacer les deux fichiers**

```bash
git mv src/research/cvep_code.py src/core/cvep_code.py
git mv src/research/cvep_decoder.py src/core/cvep_decoder.py
```

Dans les deux fichiers, l'insertion de `sys.path` doit remonter d'un niveau de moins (ils sont
maintenant dans `core/`, plus dans `research/`). Le motif à recopier est celui de
`src/core/errp_decoder.py`.

- [ ] **Étape 4 : recâbler tous les importeurs**

```bash
grep -rn "research.cvep_code\|research.cvep_decoder\|from research import cvep" src/ README.md
```

Chaque occurrence devient `core.cvep_code` / `core.cvep_decoder`. Mettre à jour la liste des
décodeurs dans `src/research/__init__.py` (« les décodeurs des modes ») et la ligne d'autotest de
`README.md`.

- [ ] **Étape 5 : lancer les tests**

```bash
python src/core/cvep_code.py
python src/core/cvep_decoder.py
python src/research/app.py --smoke
python src/core/server.py --smoke
```
Attendu : les quatre verts, sortie 0.

- [ ] **Étape 6 : vérifier le VRAI modèle, celui du 21 juillet**

```bash
python -c "import sys; sys.path.insert(0,'src'); from core.cvep_decoder import CVEPModel; m = CVEPModel.load('data/cvep_model.npz'); print(f'n_targets={m.n_targets} refresh={m.refresh} code_len={m.code_len} cv={m.cv_}')"
```
Attendu : il se charge, `n_targets=6`. **Ne pas modifier `data/`.** Coller la sortie dans le rapport.

- [ ] **Étape 7 : commit**

```bash
git add -A src/core/cvep_code.py src/core/cvep_decoder.py src/research/ README.md
git commit -m "Move the c-VEP decoder into the engine, and prove the model survives"
```

---

## Task 2 : le mode dans le moteur — phase, états muets, décision

**Files:**
- Create: `src/core/modes/cvep.py`
- Modify: `src/core/config.py` (ajouter `CVEP_PEREMPTION_CYCLES = 3`)

**Interfaces:**
- Consumes: `core.cvep_code.build_targets`, `core.cvep_decoder.CVEPModel`/`CVEPDecoder` (tâche 1).
- Produces: `CVEPRuntime` (sous-classe de `ModeRuntime`), `SPEC` (`ModeSpec`), et la méthode
  `CVEPRuntime.phase_a(t_fin) -> int|None` que la tâche 5 teste.

- [ ] **Étape 1 : écrire le test de phase et ses trois états muets**

```python
    # La phase, et les TROIS états où il n'y a pas de phase utilisable. Chacun est une
    # panne muette s'il n'est pas traité : le mode continuerait de publier des scores
    # d'apparence honnête calculés sur une horloge fausse.
    rt = _runtime_de_test(code_len=63, refresh=60.0)

    chk(rt.phase_a(100.0) is None,
        "sans aucun marqueur reçu, il n'y a PAS de phase — et surtout pas 0, qui serait une "
        "position valide du code")

    rt.maj_reference(ts=100.0, refresh=60.0)
    chk(rt.phase_a(100.0) == 0, f"à l'instant du marqueur, la phase vaut 0 ({rt.phase_a(100.0)})")
    chk(rt.phase_a(100.0 + 10 / 60.0) == 10,
        f"dix frames plus tard, phase = 10 ({rt.phase_a(100.0 + 10 / 60.0)})")
    chk(rt.phase_a(100.0 + 63 / 60.0) == 0,
        "un cycle entier plus tard, la phase est REVENUE à 0 (modulo la longueur du code)")

    # Péremption : au-delà de CVEP_PEREMPTION_CYCLES, la référence ne vaut plus rien. Continuer
    # en roue libre est l'approche écartée par la spec : à 59,94 Hz réels contre 60 supposés,
    # l'erreur atteint 3,6 frames en une minute sur un code qui en fait 63.
    juste_avant = 100.0 + (CVEP_PEREMPTION_CYCLES * 63 / 60.0) - 0.01
    juste_apres = 100.0 + (CVEP_PEREMPTION_CYCLES * 63 / 60.0) + 0.01
    chk(rt.phase_a(juste_avant) is not None,
        "juste avant la péremption, la référence sert encore")
    chk(rt.phase_a(juste_apres) is None,
        "juste après, elle est PÉRIMÉE : on cesse de décoder au lieu de dériver en silence")
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

Lancer : `python src/core/modes/cvep.py`
Attendu : `ModuleNotFoundError` — le fichier n'existe pas.

- [ ] **Étape 3 : écrire le cœur du runtime**

```python
    def maj_reference(self, ts, refresh):
        """Un marqueur de cycle vient d'arriver : le code était à la frame 0 à l'instant `ts`."""
        self._ref_ts = float(ts)
        self._ref_refresh = float(refresh)

    def phase_a(self, t_fin):
        """Position dans le code à l'instant LSL `t_fin`, ou None s'il n'y a pas de phase.

        ⚠️ `None` et `0` sont deux choses DIFFÉRENTES : 0 est une position valide du code,
        None veut dire « je ne sais pas où j'en suis ». Les confondre ferait décoder sur une
        horloge fausse en publiant des corrélations d'apparence normale.
        """
        if self._ref_ts is None:
            return None
        age = float(t_fin) - self._ref_ts
        if age < 0.0 or age > CVEP_PEREMPTION_CYCLES * self.code_len / self._ref_refresh:
            return None
        return int(age * self._ref_refresh) % self.code_len
```

- [ ] **Étape 4 : écrire `SPEC`, sur le patron de `errp.py`**

`id="cvep"`, `label="c-VEP"`, `family="actif"`, `status="moteur"`,
`stream="decoded_cvep"`, `runtime_cls=CVEPRuntime`,
`marker_epoch_s = CVEP_DECISION_CYCLES * (2 ** CVEP_BITS - 1) / 60.0` (la fenêtre de décision,
2 × 63 / 60 = **2,1 s**). ⚠️ Ici ce champ **dimensionne le tampon du moteur, il ne décrit pas une
époque** — contrairement au P300 et à l'ErrP. Le dire en commentaire, sinon un lecteur cherchera
une époque qui n'existe pas,
`rest=Rest(warmup_s=SSVEP_WARMUP_S, duration_s=0.0, instruction="Le casque se stabilise — reste immobile.")`,
`calibration=Calib(kind="natif", reason="stimulus verrouillé à la frame", label="Calibrer", …)`.

- [ ] **Étape 5 : le refus sans modèle et le refus de rafraîchissement**

```python
        # ⚠️ Le modèle est calibré à UN rafraîchissement, et c'est l'ÉMETTEUR qui tient
        # l'écran — le moteur ne peut pas le voir. Sans cette garde : le décodage tourne, les
        # scores restent honnêtes, et RIEN ne se déclenche jamais. C'est la panne qui a coûté
        # une séance au SSVEP.
        if abs(refresh_declare - self.model.refresh) > 1.0:
            raise ValueError(
                f"l'émetteur affiche à {refresh_declare:.1f} Hz, le modèle a été calibré à "
                f"{self.model.refresh:.1f} Hz — recalibre, ou lance l'émetteur avec "
                f"--refresh {self.model.refresh:.0f}")
```

- [ ] **Étape 6 : lancer et prouver la mutation**

Lancer : `python src/core/modes/cvep.py` → vert.
Muter `return int(age * self._ref_refresh) % self.code_len` en `... + 1) % ...` → **rouge**.
Remettre, relancer, coller les deux sorties dans le rapport.

- [ ] **Étape 7 : commit**

```bash
git add src/core/modes/cvep.py src/core/config.py
git commit -m "Give the c-VEP a runtime that knows when it does not know the phase"
```

---

## Task 3 : deux décodeurs, un seul stimulus

**Files:**
- Create: `src/core/cvep_rcca.py` (moitié décodeur de l'ancien), `src/core/cvep_models.py`
- Modify: `src/research/cvep_rcca.py` (réduit aux codes Gold), `requirements.txt`,
  `src/core/config.py` (seuils rCCA)

**Interfaces:**
- Produces: `core.cvep_models.modeles_disponibles() -> tuple[str]` (les fichiers, du plus récent au
  plus ancien) ; `core.cvep_models.charger(chemin) -> (modele|None, raison|None)` ;
  `core.cvep_rcca.RCCAModel(codes, fs, refresh, band, …)` avec `.scores(window, phase, n_cycles)`.

- [ ] **Étape 1 : écrire le test du champ `decoder`**

```python
    # Le fichier de modèle DÉCLARE son décodeur. Inférer d'après les clés présentes serait
    # deviner ; un champ explicite se lit et se teste. Un fichier SANS ce champ est un eCCA
    # d'avant ce chantier — c'était le seul décodeur qui existait sous ce nom de fichier.
    chk(charger(chemin_ecca)[0].decoder == "eCCA",
        "un modèle eCCA se déclare comme tel")
    chk(charger(chemin_rcca)[0].decoder == "rCCA",
        "un modèle rCCA aussi, et le moteur choisit le décodeur d'après CE champ")
    chk(charger(chemin_herite)[0].decoder == "eCCA",
        "un modèle SANS le champ est un eCCA hérité, pas une erreur")
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

Lancer : `python src/core/cvep_models.py` → `ModuleNotFoundError`.

- [ ] **Étape 3 : couper `cvep_rcca.py` en deux**

`RCCAModel` et `RCCADecoder` partent dans `src/core/cvep_rcca.py`. `make_distinct_codes` et
`build_targets_rcca` **restent** dans `src/research/cvep_rcca.py`.

⚠️ Après ce découpage, les seuls appelants des codes Gold vivront dans `archive/` (tâche 6). C'est
voulu, et il faut l'écrire dans la docstring : **une hypothèse réfutée se garde lisible, pas
branchée.**

- [ ] **Étape 4 : déclarer `pyntbci`**

Ajouter à `requirements.txt`, avec la raison en commentaire :

```
# Décodeur c-VEP par reconvolution (rCCA). Le MOTEUR en dépend : RCCAModel ne sérialise pas
# l'objet pyntbci, il stocke les époques et ré-ajuste au chargement.
pyntbci
```

Vérifier la version installée et l'épingler si `pip freeze` en donne une :
`python -c "import pyntbci; print(pyntbci.__version__)"`.

- [ ] **Étape 5 : poser les seuils rCCA**

`CVEP_RCCA_CORR_MIN = 0.0` et `CVEP_RCCA_MARGIN = 0.0` sont des placeholders assumés (« ne pas se
fier au seuil »). **Voici comment les poser**, et il faut le faire par la mesure, pas au jugé :

1. Rejouer `data/cvep_calib_last.npz` (époques réelles du 2026-07-21, 6 cibles, stimulus **décalé**)
   à travers `RCCAModel.fit(epochs, labels, compute_cv=True)`.
2. Récupérer les scores **hors-pli** produits par sa validation croisée leave-one-out : pour chaque
   essai, la corrélation du gagnant et celle du second.
3. `corr_min` = le quantile qui garde **95 % des essais corrects** de la calibration ; `margin` =
   le quantile 95 % des écarts gagnant-second sur ces mêmes essais corrects. Le c-VEP n'a pas de
   coût asymétrique comme l'ErrP : on cale sur « ne pas rater ce qui est bon ».
4. ⚠️ **Écrire le chiffre ET sa provenance** dans le commentaire de `config.py` (fichier source,
   date, nombre d'essais). Un seuil sans provenance est un seuil que personne n'osera changer.
5. ⚠️ **Ces seuils sont mesurés sur UNE personne et UNE séance.** Le dire là où ils sont écrits —
   c'est la même réserve que pour l'eCCA, et elle vaut jusqu'à ce qu'une seconde personne soit
   mesurée.

⚠️ **Ne pas écrire dans `data/`** : lire ces fichiers, jamais les modifier.

- [ ] **Étape 6 : lancer**

```bash
python src/core/cvep_models.py
python src/core/cvep_rcca.py
python src/core/server.py --smoke
```
Attendu : verts. Le smoke de frontière doit rester vert — `core/cvep_rcca.py` n'importe rien de
`research/`.

- [ ] **Étape 7 : commit**

```bash
git add src/core/cvep_rcca.py src/core/cvep_models.py src/research/cvep_rcca.py requirements.txt src/core/config.py
git commit -m "Split rCCA from the Gold codes it was wrongly judged with"
```

---

## Task 4 : le flux publié et les compteurs de diagnostic

**Files:**
- Modify: `src/core/lsl_io.py`, `src/core/modes/registry.py`, `src/core/modes/external.py`,
  `src/console/grid.py`, `src/console/live_views.py`

**Interfaces:**
- Produces: `core.lsl_io.cvep_channel_labels(n_targets) -> list[str]` =
  `["target_index", "confidence"] + [f"score_{i}" for i in range(n_targets)]` ;
  `DecodedCVEPPublisher(n_targets, decoder, refresh, code_len, corr_min, margin, cv, instance)`
  avec `.push(target_index, confidence, scores, lsl_ts)`.

- [ ] **Étape 1 : écrire le test des compteurs par cause**

```python
    # ⚠️ Les trois causes de « pas de décision » doivent être SÉPARÉES dans l'état. Une séance
    # casque coûte cher et ne se répète pas : « ça ne détecte pas » sans la cause ne permet pas
    # de distinguer une phase fausse d'un contact médiocre d'un étudiant qui ne fixe pas —
    # trois causes qui appellent trois gestes opposés.
    st = rt.state()
    chk(set(st) >= {"decodages", "sans_reference", "reference_perimee", "vote_non_conclu",
                    "age_reference_s", "corr_gagnant", "corr_second"},
        f"l'état sépare les trois causes de -1 et expose l'âge de la référence ({sorted(st)})")
    chk(st["sans_reference"] == 2 and st["reference_perimee"] == 1 and st["vote_non_conclu"] == 3,
        f"...et chaque compteur compte SA cause, pas le total ({st})")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/core/modes/cvep.py` → rouge (clés absentes).

- [ ] **Étape 3 : écrire le publieur et les compteurs**

Sur le patron de `DecodedP300Publisher`. Métadonnées obligatoires, sous `decoding/` :
`paradigm="c-VEP"`, `decision_scale="correlation"`, `no_decision_index="-1"`, `code_len`,
`refresh`, `n_targets`, `decoder`, `corr_min`, `margin`, `cv`.

- [ ] **Étape 4 : enregistrer le mode, retirer l'entrée « externe »**

Ajouter `cvep.SPEC` à `registry.MODES` ; retirer l'entrée c-VEP de `modes/external.py` ; dégriser la
tuile de la console.

⚠️ **La tuile ne doit pas mettre des corrélations à l'échelle du `Z_MIN` du SSVEP** — c'est le défaut
qui a survécu deux chantiers sur la tuile P300, corrigé la semaine dernière. Le c-VEP publie un
`corr_min` : la tuile doit s'en servir. **Ajouter une assertion sur `tuiles["cvep"].apercu`**, car
c'est l'absence d'assertion qui avait laissé passer le cas P300.

- [ ] **Étape 5 : écrire le test de BOUT EN BOUT synthétique**

⚠️ **Celui-ci prouve la chaîne entière**, là où le test de phase (tâche 5) ne prouve que l'horloge.
Sans lui, on saurait que la phase est juste sans savoir qu'elle est branchée au bon endroit.

`core.cvep_decoder.synth_cvep(code, lag, n_ch, fs, refresh, snr_db, rng, latency_s)` fabrique déjà un
cycle de c-VEP pour un lag donné — on s'en sert pour construire un tampon de plusieurs cycles.

```python
    # Chaîne complète, sans casque : un EEG synthétique portant le c-VEP de la cible 2, des
    # marqueurs de cycle aux bons instants, et le moteur doit désigner LA CIBLE 2. Le test de
    # phase dit que l'horloge est juste ; celui-ci dit qu'elle est branchée au bon endroit.
    plan, code = build_targets()
    cible = 2
    lag_vrai = plan[cible]["lag"]
    eeg, ts = _tampon_synthetique(code, lag_vrai, fs=250.0, refresh=60.0,
                                  n_cycles=6, snr_db=0.0, rng=np.random.default_rng(7))
    rt = _runtime_de_test(modele=_modele_appris_sur(code, lag_vrai), code_len=len(code))
    for k in range(6):                       # un marqueur par cycle, comme l'émetteur
        rt.maj_reference(ts=ts[0] + k * len(code) / 60.0, refresh=60.0)
    publie = rt.decider_sur(eeg, ts)

    chk(publie["target_index"] == cible,
        f"le moteur désigne la cible RÉELLEMENT affichée ({publie['target_index']} au lieu de "
        f"{cible}) — la phase est juste ET branchée au bon endroit")
    chk(publie["scores"][cible] == max(publie["scores"]),
        f"...et c'est bien elle qui porte la meilleure corrélation ({publie['scores']})")
```

- [ ] **Étape 6 : prouver la mutation de ce test**

Décaler d'un lag la table `lag_to_cmd` du décodeur (apparier la corrélation du lag *j* au nom de la
cible *j+1*) : le test doit **rougir** en désignant une cible voisine. C'est l'appariement
score↔cible, exactement le défaut que la revue du P300 avait trouvé sur son propre mode. Retirer,
relancer, coller les deux sorties.

- [ ] **Étape 7 : lancer**

```bash
python src/core/modes/cvep.py
python src/core/lsl_io.py
python src/core/modes/registry.py
python src/console/app.py --smoke
```

- [ ] **Étape 8 : commit**

```bash
git add src/core/lsl_io.py src/core/modes/ src/console/
git commit -m "Publish decoded_cvep, and prove the chain picks the target that was shown"
```

---

## Task 5 : l'émetteur, et LE test qui porte le chantier

**Files:**
- Create: `src/research/cvep_stimulus.py`
- Modify: `src/research/__init__.py`

**Interfaces:**
- Consumes: `core.cvep_code.build_targets`, `core.cvep_code.is_on`,
  `core.modes.cvep.CVEPRuntime.phase_a` (pour le test).
- Produces: un exécutable `python src/research/cvep_stimulus.py [--windowed] [--refresh N]
  [--seconds N] [--seed N] [--no-wait] [--smoke]`.

Le patron est `src/research/errp_stimulus.py`, livré la semaine dernière : mêmes options, même
attente du moteur, même bilan de fin, et **le marqueur poussé APRÈS `pygame.display.flip()`**.

- [ ] **Étape 1 : écrire LE test de phase**

⚠️ **C'est le test qui porte le chantier.** Une erreur de phase ne casse rien : les corrélations
baissent, le mode continue de publier, les scores restent d'apparence honnête, et la détection se
contente de ne presque jamais se déclencher — indiscernable d'un étudiant qui ne fixe pas.

```python
    # On rejoue une course de rendu EN PUR : une frame toutes les 1/refresh s, un marqueur de
    # cycle à chaque frame 0, ET une frame SAUTÉE au milieu (le cas qui arrive vraiment). Pour
    # chaque frame on compare la phase que le MOTEUR reconstruirait à celle que l'émetteur a
    # RÉELLEMENT affichée.
    refresh, L, t0 = 60.0, 63, 1000.0
    rt = _runtime_de_test(code_len=L, refresh=refresh)
    ecarts, saut_fait = [], False
    frame = 0
    while frame < L * 8:
        t = t0 + frame / refresh
        if frame % L == 0:
            rt.maj_reference(ts=t, refresh=refresh)
        vue = rt.phase_a(t)
        ecarts.append(None if vue is None else (vue - frame % L + L // 2) % L - L // 2)
        if frame == L * 3 + 17 and not saut_fait:   # une frame sautée, une seule
            saut_fait, frame = True, frame + 1
        frame += 1

    pires = [abs(e) for e in ecarts if e is not None]
    chk(len(pires) == len(ecarts), "une phase est disponible à CHAQUE frame de la course")
    chk(max(pires) <= 1,
        f"l'écart entre la phase reconstruite et la phase AFFICHÉE ne dépasse jamais UNE frame "
        f"(pire écart mesuré : {max(pires)} frames, sur {len(pires)} frames)")
    chk(saut_fait and max(pires) <= 1,
        "...y compris après une frame sautée : le marqueur du cycle suivant RÉSORBE l'erreur "
        "au lieu de la laisser s'accumuler")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/research/cvep_stimulus.py --smoke`.

- [ ] **Étape 3 : écrire l'émetteur**

Le geste critique, identique aux deux émetteurs existants :

```python
        pygame.display.flip()
        # L'HORODATAGE SE PREND ICI, juste après que la frame est À L'ÉCRAN. Le prendre avant
        # décale TOUTES les phases d'une frame, et le décodeur cherche alors le code à un
        # endroit où il n'est pas — sans qu'aucune exception ne le signale.
        if frame % len(code) == 0:
            out.push_sample([json.dumps({"mode": "cvep", "event": "cycle",
                                         "refresh": refresh})], local_clock())
```

⚠️ **N'ouvre PAS le casque.** C'est ce qui permet de le lancer en même temps que le moteur.

- [ ] **Étape 4 : prouver le test rouge**

Décaler la phase d'une frame dans `phase_a` (`int(age * refresh) + 1`), relancer le smoke.
Attendu : **rouge**, sur l'assertion de l'écart. Retirer, relancer, coller les deux sorties.

- [ ] **Étape 5 : lancer les tests**

```bash
python src/research/cvep_stimulus.py --smoke
python src/research/app.py --smoke
```

- [ ] **Étape 6 : commit**

```bash
git add src/research/cvep_stimulus.py src/research/__init__.py
git commit -m "Ship the c-VEP emitter, and pin the phase to the frame that was shown"
```

---

## Task 6 : la calibration entraîne les deux et affiche les deux chiffres

**Files:**
- Modify: `src/research/cvep_calibrate.py`, `src/research/app.py`
- Create: `archive/cvep_pilot.py`, `archive/cvep_rcca_pilot.py` (les écrans retirés)

- [ ] **Étape 1 : écrire le test de la comparaison honnête**

```python
    # Les deux décodeurs s'ajustent sur les MÊMES époques, en validation croisée groupée par
    # bloc. Comparer deux protocoles différents ne dirait rien ; c'est tout l'intérêt d'avoir
    # gardé le stimulus identique.
    res = entraine_les_deux(epochs, labels, groups, fs=250.0, refresh=60.0)
    chk(set(res) == {"eCCA", "rCCA"}, f"les deux décodeurs sont entraînés ({sorted(res)})")
    chk(res["eCCA"]["n_epoques"] == res["rCCA"]["n_epoques"] == len(labels),
        "...sur le MÊME nombre d'époques — sinon la comparaison ne veut rien dire")
    chk(res["eCCA"]["groupes"] == res["rCCA"]["groupes"],
        "...et les mêmes groupes de validation croisée")
```

- [ ] **Étape 2 : lancer, vérifier l'échec.**

- [ ] **Étape 3 : entraîner les deux, afficher les deux**

L'écran de résultat affiche les deux justesses côte à côte et **nomme le gagnant**. Les deux
chiffres et le champ `decoder` partent dans le fichier de modèle.

- [ ] **Étape 4 : archiver les écrans de pilotage**

`mode_cvep` (eCCA) et `mode_cvep_rcca` (Gold) partent dans `archive/`, **encore exécutables** — ils
sont la référence contre laquelle la séance casque comparera le décodage réseau. La calibration
c-VEP **reste au menu** ; la calibration rCCA (codes Gold) part aussi.

Mettre à jour `archive/README.md` en disant **pourquoi** chacun est là.

- [ ] **Étape 5 : lancer** — `python src/research/app.py --smoke`, `python src/research/cvep_calibrate.py`.

- [ ] **Étape 6 : commit**

```bash
git add src/research/ archive/
git commit -m "Train both decoders on the same epochs, and name the winner"
```

---

## Task 7 : les seuils réglables à chaud — la garde qui manque à l'ErrP

**Files:**
- Modify: `src/core/modes/cvep.py`

- [ ] **Étape 1 : écrire le test qui prouve qu'on ne recrée pas le flux**

⚠️ **C'est la garde que l'ErrP n'a pas.** Changer son `tnr_target` reconstruit le runtime, détruit et
recrée le flux, et relance 23 s de chauffe : le récepteur ouvert devient muet et l'opérateur lit ça
comme une panne. En séance casque, ça se paie en minutes de casque à chaque essai de réglage.

```python
    # Les seuils sont lus À CHAQUE DÉCISION, pas figés dans __init__. C'est ce qui permet de
    # les tourner en pleine séance sans réabonner personne ni refaire la chauffe.
    p = {p.key for p in SPEC.params if not p.affecte_decodage}
    chk({"corr_min", "margin"} <= p,
        f"les deux seuils sont déclarés SANS reconstruction du runtime ({sorted(p)})")

    rt.params["corr_min"] = 0.99          # personne ne passe ce seuil
    cmd_a, _ = rt.decide(fenetre, phase)
    rt.params["corr_min"] = 0.01          # tout le monde le passe
    cmd_b, _ = rt.decide(fenetre, phase)
    chk(cmd_a is None and cmd_b is not None,
        "changer le seuil change la décision SUR LA MÊME fenêtre, sans rien reconstruire")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** (les seuils sont encore figés à la construction).

- [ ] **Étape 3 : lire les seuils à chaque décision**

```python
    def decide(self, fenetre, phase):
        # ⚠️ Relus ICI, à chaque décision, jamais mis en cache dans __init__ : c'est la seule
        # raison pour laquelle `affecte_decodage=False` n'est pas un mensonge sur ces deux
        # réglages, et c'est ce qui rend une séance casque réglable sans la interrompre.
        corr_min = float(self.params["corr_min"])
        margin = float(self.params["margin"])
```

- [ ] **Étape 4 : prouver la mutation**

Remettre les seuils dans `__init__` (`self.corr_min = params["corr_min"]`) et les lire depuis `self`
→ le test doit **rougir**. Retirer, relancer, coller les deux sorties.

- [ ] **Étape 5 : lancer** — `python src/core/modes/cvep.py`, `python src/core/server.py --smoke`.

- [ ] **Étape 6 : commit**

```bash
git add src/core/modes/cvep.py
git commit -m "Read the c-VEP thresholds at each decision, so a session can turn them"
```

---

## Task 8 : la documentation, et la procédure de la séance

**Files:**
- Modify: `docs/markers.md`, `docs/SPEC.md` (§5 et §14), `docs/recette.md` (1.16 et 2.9),
  `README.md`, `CLAUDE.md`

- [ ] **Étape 1 : `docs/markers.md` — le troisième client du tuyau**

La page couvre déjà deux décodeurs ; elle en couvre maintenant trois. Ajouter la section c-VEP avec
le contrat exact, et dire ce qui le distingue des deux autres : **ses marqueurs ne délimitent pas
une époque, ils tiennent une horloge**.

```json
{"mode": "cvep", "event": "cycle", "refresh": 60.0}
```

Dire aussi, parce qu'un client s'y trompera : `refresh` est **obligatoire**, et un désaccord avec le
modèle fait refuser le démarrage — c'est délibéré.

- [ ] **Étape 2 : `docs/SPEC.md`**

§5 : la ligne c-VEP passe de « stimulus natif au MVP » au format réel
`{target_index, confidence, score_0…score_5}`, avec `-1` = pas de décision. §14 : marquer le chantier
fait, **et écrire ce qui reste dehors** — la séance casque, les codes Gold, le rendu par une appli
cliente, la calibration jouée par le moteur, une seconde personne mesurée.

- [ ] **Étape 3 : `docs/recette.md` — le script de la séance**

**1.16** (sans casque) : console + émetteur + récepteur, sur le montage du 1.15.
**2.9** (au casque) : la vraie question. Il doit inclure la **comparaison contre l'écran archivé**,
sur la même personne et dans la même séance.

⚠️ **Le 2.9 doit dire d'avance ce qui est un résultat NORMAL**, comme le 2.8 a dû le faire pour
l'ErrP. Sans ce garde-fou, un opérateur qui voit une cible sur six mal désignée conclut à la panne
alors qu'il regarde le comportement attendu.

- [ ] **Étape 4 : `README.md` et `CLAUDE.md`**

Six modes publiés. L'appli pygame n'est plus **que** l'endroit où l'on calibre. Ajouter
`--mode cvep` et `cvep_stimulus.py` aux commandes utiles, et les nouveaux autotests à la liste.

- [ ] **Étape 5 : la suite complète**

Lancer les autotests **un par un** (jamais en parallèle), vérifier que `data/` est intact avant et
après, et qu'aucun python du projet ne traîne.

- [ ] **Étape 6 : commit**

```bash
git add docs/ README.md CLAUDE.md
git commit -m "Document the c-VEP, and write the session script before the session"
```

---

## Le chantier est fini à la tâche 8

La **séance casque** suit comme travail distinct, et couvre d'un coup les trois modes jamais
vérifiés : les tests 2.7 (P300), 2.8 (ErrP) et 2.9 (c-VEP). Grâce à la tâche 7, elle pourra ajuster
les seuils sans rouvrir une ligne de code.

⚠️ **Ce que ce chantier ne prouve pas, et qu'il faut dire en l'annonçant** : que le c-VEP décode un
vrai cerveau à travers le réseau. La chaîne sera vérifiée de bout en bout en synthétique et la phase
gardée au niveau de la frame — mais le premier signal réel passera après.
