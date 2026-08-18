# L'ErrP sur le réseau — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publier l'ErrP comme 5e mode du moteur : à chaque feedback affiché par une application externe, épocher l'EEG et publier un verdict avec son point de fonctionnement.

**Architecture:** Second client du tuyau des marqueurs entrants livré la veille. Le décodeur déménage dans `core/`, un runtime le pilote, et le seul réglage du mode est un **taux** (« quelle part des bonnes commandes garder ») dont le moteur déduit le seuil sur les scores out-of-fold du modèle.

**Tech Stack:** Python 3, `pylsl`, `numpy`, `scikit-learn`, `pyriemann` (xDAWN + espace tangent), `joblib`, `pygame` (stimulus uniquement, dans `research/`).

**Spec de référence :** [docs/superpowers/specs/2026-08-18-errp-moteur-design.md](../specs/2026-08-18-errp-moteur-design.md) (commit `c493799`).

## Ce qui est DÉJÀ MESURÉ — à citer, jamais à redécouvrir

Ré-entraîné le 2026-08-18 depuis `data/errp_calib_last.npz` (calibration réelle du 2026-07-24) :

| | |
|---|---|
| AUC | **0,7763**, validation croisée **groupée par bloc** |
| p (permutation, 100 tirages) | **0,0099** — aucune permutation ne bat l'observé |
| Effectif | 200 époques : **62 ERREUR / 138 bonnes**, 5 blocs |
| `nfilter` retenu | 4 |
| Seuil par défaut | 0,5103 → **TPR 0,500 · TNR 0,855** |
| Baseline sLDA | 0,710 |

Courbe de compromis, à reprendre verbatim dans la doc et les métadonnées :
TNR 0,95→TPR 0,24 · 0,90→0,40 · **0,85→0,50** · 0,80→0,60 · 0,70→0,71.

## Global Constraints

- `src/core/` n'importe **jamais** `src/research/` ni `src/console/`, et ne contient ni pygame ni Qt. Vérifié par `python src/core/server.py --smoke`.
- La console est un **client** du moteur : aucune logique qu'il ne possède pas déjà.
- Code, commentaires et docstrings **en français** ; messages de commit **en anglais**.
- Tout testable **sans casque** (`--synthetic`).
- **Aucun test n'écrit dans le vrai `data/`** : `tempfile.mkdtemp()` + `shutil.rmtree` dans un `finally`.
- ⚠️ **Chaque autotest sort en 1 quand il échoue** : `_sys.exit(0 if _selftest() else 1)`. `p300_decoder.py` jetait son verdict et sortait toujours en 0 — ça a invalidé une preuve de rapport.
- ⚠️ **Aucun moteur ne tourne pendant un test**, jamais deux programmes du projet en même temps : les noms de flux sont un contrat public.
- Style d'autotest : `_selftest()` avec un `chk(cond, msg)` local, ligne finale `print(f"[<nom>] VERDICT : {'OK' if ok else 'PROBLÈME'}")`.
- Valeurs figées de `src/core/config.py`, à utiliser **verbatim** : `ERRP_BAND=(1.0, 10.0)`, `ERRP_PRE_S=0.2`, `ERRP_EPOCH_S=0.7`, `ERRP_TNR_TARGET=0.85`, `ERRP_ARTIFACT_RATIO=4.0`, `ERRP_MODEL_PATH`, `ERRP_MIDLINE=[0,2,4]`, `ERRP_FEEDBACK_S=1.0`, `ERRP_ERROR_RATE=0.28`, `ERRP_TRACK_CELLS=7`, `SSVEP_WARMUP_S=15`.
- ⚠️ **`ERRP_REFRACTORY_S=1.5` reste au démonstrateur pygame. Le moteur ne l'applique PAS** — décision §4.1 de la spec : le moteur publie, le client décide.

---

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| **Déplacer** `src/research/errp_decoder.py` → `src/core/errp_decoder.py` | Le décodeur, inchangé sauf son emplacement. |
| **Créer** `src/core/errp_models.py` | Les modèles ErrP du disque : lesquels existent, lequel se charge, refus des hérités. Jumeau de `p300_models.py`. |
| **Créer** `src/core/modes/errp.py` | Le MODE : `ErrPRuntime`, le repos, le rejet d'artefact, le réglage, son `ModeSpec`. |
| **Créer** `src/research/errp_stimulus.py` | L'émetteur d'exemple : une piste, des erreurs délibérées, un marqueur `feedback` par retour affiché. N'ouvre PAS le casque. |
| **Modifier** `src/core/lsl_io.py` | `errp_channel_labels` + `DecodedErrPPublisher`. |
| **Modifier** `src/core/modes/registry.py` | Enregistrer `errp.SPEC`, retirer `external.ERRP`. |
| **Modifier** `src/core/modes/external.py` | Supprimer l'entrée `ERRP` — le catalogue tombe à **une** entrée (c-VEP). |
| **Modifier** `src/console/app.py` | Le compte des tuiles « appli pygame » dans le smoke. |
| **Modifier** `src/research/errp_calibrate.py`, `app.py` | Recâblage des imports vers `core.errp_decoder`. |

---

## Task 1: Le décodeur déménage, et son modèle se ré-entraîne

**Files:**
- Déplacer : `src/research/errp_decoder.py` → `src/core/errp_decoder.py`
- Créer : `src/core/errp_models.py`
- Modifier : `src/research/errp_calibrate.py`, `src/research/app.py` (imports)

**Interfaces:**
- Produces : `core.errp_decoder.ErrPModel`, `rates`, `pick_threshold`, `synth_errp_epoch` · `core.errp_models.charger(chemin) -> (modele, raison)`, `modeles_disponibles(dossier=DATA_DIR) -> list[str]`, `decrire(chemin) -> list[str]`

⚠️ **Le piège central, troisième occurrence.** `data/errp_model.joblib` **ne se charge déjà plus** : le décodeur P300 ayant déménagé hier, le pickle de l'ErrP référence `p300_decoder` nu, qui n'existe plus. Ce projet a perdu 4 modèles MI comme ça. **Aucune passerelle de compatibilité** — les époques ont survécu (`data/errp_calib_last.npz`, plus deux horodatés), on ré-entraîne.

- [ ] **Step 1: Déplacer avec `git mv`, pour que l'historique suive**

```bash
git mv src/research/errp_decoder.py src/core/errp_decoder.py
```

- [ ] **Step 2: NE PAS toucher au `sys.path.insert` — vérifié, il est déjà juste**

La ligne en tête du fichier est :

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

Elle **ne change pas**, et c'est contre-intuitif au point qu'il faut le dire : `src/research/` et `src/core/` sont à la **même profondeur**, donc deux `dirname` mènent à `src` depuis l'un comme depuis l'autre. `mi_decoder.py` et `p300_decoder.py`, déjà dans `core/`, portent la même ligne. La modifier casserait l'import de `core.config`.

- [ ] **Step 3: Recâbler les importeurs**

```bash
grep -rn "errp_decoder" src/ --include=*.py
```

Chaque `from research.errp_decoder import …` (ou import nu) devient `from core.errp_decoder import …`. `research` a le droit d'importer `core` ; l'inverse est interdit.

- [ ] **Step 4: Écrire `src/core/errp_models.py`, calqué sur `src/core/p300_models.py`**

Lis `p300_models.py` en entier : c'est ton modèle de forme, de ton et de structure. Les différences :

```python
MOTIF = "errp_model*.joblib"
_MODULE_ATTENDU = "core.errp_decoder"
```

et le message de refus d'un modèle hérité doit nommer la source à ré-entraîner :

```python
        return None, (f"modèle hérité (module {module!r}, attendu {_MODULE_ATTENDU!r}), "
                      f"illisible depuis le déménagement du décodeur. Ré-entraîne-le depuis "
                      f"les époques conservées : data/errp_calib_*.npz")
```

⚠️ Le message pour un chemin vide doit dire la VÉRITÉ sur l'endroit où l'on calibre — **la console n'a pas de page de calibration ErrP**, c'est l'appli pygame :

```python
        return None, ("aucun modèle désigné — lance `python src/research/app.py`, mode ErrP, "
                      "et calibre pour en produire un")
```

- [ ] **Step 5: Écrire l'autotest de `errp_models.py`, avec LE test qui protège la décision**

⚠️ **Ce test est le seul qui protège la décision « ré-entraîner plutôt que rafistoler ».** La leçon vient de la revue du P300 : un faux modèle ordinaire porte le module `"__main__"`, **jamais** `"errp_decoder"`, donc la mutation `endswith("errp_decoder")` — la passerelle qu'un contributeur écrira un jour — passerait inaperçue.

Il faut donc **enregistrer un faux module nommé `errp_decoder` dans `sys.modules`, et l'y laisser pendant le `joblib.dump` ET pendant le chargement** — `pickle` résout la classe via `obj.__module__` au dump, pas seulement à la lecture.

```python
    import types
    faux = types.ModuleType("errp_decoder")

    class _ModeleHerite:
        """Imite un modèle enregistré AVANT le déménagement : son module est le nom NU."""
        threshold_ = 0.0
        def score(self, epochs):
            return [0.0] * len(epochs)
        def is_error(self, epoch):
            return False

    _ModeleHerite.__module__ = "errp_decoder"
    faux._ModeleHerite = _ModeleHerite
    _sys.modules["errp_decoder"] = faux
    try:
        chemin_herite = _os.path.join(dossier, "errp_model_herite.joblib")
        joblib.dump(_ModeleHerite(), chemin_herite)
        modele, raison = charger(chemin_herite)
        chk(modele is None, "un modèle hérité est REFUSÉ")
        chk(raison is not None and "errp_decoder" in raison and "ré-entraîn" in raison,
            f"et la raison nomme le module fautif ET la source à ré-entraîner ({raison})")
        chk(chemin_herite not in modeles_disponibles(dossier),
            "il n'apparaît pas non plus dans la liste des modèles utilisables")
    finally:
        _sys.modules.pop("errp_decoder", None)
```

- [ ] **Step 6: Obtenir la preuve ROUGE de ce test**

Remplace temporairement la comparaison exacte du module par `module.endswith("errp_decoder")` — c'est-à-dire la passerelle de compatibilité que ce chantier refuse d'écrire.

Run: `python src/core/errp_models.py`
Expected: **ÉCHEC** sur « un modèle hérité est REFUSÉ », et code de sortie **1**.

Remets la comparaison exacte, relance, colle le VERT. **Colle les deux sorties dans le rapport.** Sans ce rouge, l'assertion pourrait passer pour de mauvaises raisons — c'est arrivé au P300.

- [ ] **Step 7: Ré-entraîner le modèle depuis les époques conservées**

Programme **jetable**, à écrire dans le scratchpad (`C:\Users\Lab_IA\AppData\Local\Temp\claude\c--Users-Lab-IA-Documents-Projets-Dev-EEG-API-Unicorn\b4139deb-bcbe-44b9-8ad9-6c2f9e54593a\scratchpad`), **pas dans le dépôt** :

```python
import sys, numpy as np, time
sys.path.insert(0, "src")
from core.errp_decoder import ErrPModel

d = np.load("data/errp_calib_last.npz", allow_pickle=True)
m = ErrPModel(fs=float(d["fs"]), pre_s=float(d["pre_s"]), post_s=float(d["post_s"]))
m.fit(d["epochs"], d["labels"], groups=d["groups"])
print("AUC", m.cv_auc_, "| p", m.perm_p_, "| nfilter", m.nfilter_)
print("seuil", m.threshold_, "| metrics", m.metrics_)
m.save(f"data/errp_model_{time.strftime('%Y%m%d-%H%M%S')}.joblib")
```

⚠️ **NE PAS écraser `data/errp_model.joblib`.** C'est la trace de la séance du 24 juillet. Le nouveau modèle s'écrit **horodaté à côté**, comme pour le P300.

**Colle la sortie brute dans le rapport.** Attendu, aux arrondis près : AUC ≈ 0,776, p ≈ 0,0099, nfilter 4, seuil ≈ 0,510, TPR ≈ 0,500 / TNR ≈ 0,855. ⚠️ **Si l'AUC s'écarte nettement, DIS-LE** plutôt que de continuer : ça voudrait dire que le ré-entraînement n'a pas reproduit les conditions, et ça change la suite du chantier.

- [ ] **Step 8: Lancer, un par un**

```bash
python src/core/errp_decoder.py      # le décodeur depuis son nouvel emplacement
python src/core/errp_models.py       # le refus des hérités, le tri
python src/core/server.py --smoke    # la frontière core/ : aucun import interdit
python src/research/app.py --smoke   # l'appli pygame n'est pas cassée par le déménagement
```

Attendu : `VERDICT : OK` partout, et `smoke-frontiere` à 0 violation.

- [ ] **Step 9: Commit**

```bash
git add -A src/core/errp_decoder.py src/core/errp_models.py src/research/
git commit -m "Move the ErrP decoder into the engine, and retrain rather than shim"
```

---

## Task 2: Le mode — runtime, repos, rejet d'artefact

**Files:**
- Créer : `src/core/modes/errp.py`

**Interfaces:**
- Consumes : `core.errp_decoder.ErrPModel`, `core.errp_models.charger/modeles_disponibles` (T1) · `engine.markers_murs(mode_id, post_s)` → `[(ts, dict)]` · `engine.recent`, `engine.recent_ts` · `engine.acq.sigma_from_block(block)` · `epoch_from_stream(eeg, ts, flash_ts, fs, pre_s, post_s)`
- Produces : `ErrPRuntime` avec les **attributs de classe** `pre_s = ERRP_PRE_S` et `post_s = ERRP_EPOCH_S` (le contrôle structurel de `registry.check()` les lit) · `errp.SPEC` avec `marker_epoch_s = ERRP_PRE_S + ERRP_EPOCH_S`

**Ton modèle de forme :** `src/core/modes/p300.py`. Lis-le avant d'écrire. Trois de ses pires défauts n'existent pas ici — pas de manche, donc **pas de plafond, pas de contamination, pas d'abandon**. Chaque feedback est indépendant et produit exactement un échantillon.

- [ ] **Step 1: Le squelette du runtime**

```python
class ErrPRuntime(ModeRuntime):
    """Un verdict par feedback : la machine vient-elle de se tromper.

    ⚠️ Le moteur PUBLIE, il n'annule rien. La période réfractaire et la décision d'annuler une
    commande appartiennent à l'application : « n'annule pas cette commande » EST une commande, et
    ce projet publie des intentions neutres. `ERRP_REFRACTORY_S` reste au démonstrateur pygame.
    """

    pre_s = ERRP_PRE_S      # attributs de CLASSE : `registry.check()` les compare à
    post_s = ERRP_EPOCH_S   # `marker_epoch_s` pour qu'aucune époque ne soit tronquée en silence
```

- [ ] **Step 2: Le repos, et le rejet d'artefact qu'il alimente**

Le mode déclare un `Rest`. Ce que le repos mesure est un **σ par voie**, la référence du rejet d'artefact :

```python
    def _reset_rest(self):
        self._sigmas_repos = None
        self._echantillons = []

    def _rest_step(self, engine, now):
        bloc = engine.recent
        sig = engine.acq.sigma_from_block(bloc)
        if sig is None:
            return False
        self._echantillons.append(sig)
        if now < self._rest_until:
            return False
        self._sigmas_repos = np.median(np.asarray(self._echantillons), axis=0)
        print(f"[errp] repos mesuré ({len(self._echantillons)} fenêtres) — σ par voie : "
              f"{np.array2string(self._sigmas_repos, precision=1)}")
        self.rest_report = {"kind": "errp", "fenetres": len(self._echantillons),
                            "sigma": [round(float(s), 2) for s in self._sigmas_repos]}
        return True
```

et le `Rest` du `ModeSpec` :

```python
    rest=Rest(
        warmup_s=SSVEP_WARMUP_S,   # 15 s : l'offset DC de l'Unicorn dérive après ouverture
        duration_s=8.0,            # même durée que le SSVEP : deux modes lancés ensemble PARTAGENT
        instruction="Repos : regarde l'écran, immobile — on mesure le bruit de fond de tes voies.",
    ),
```

- [ ] **Step 3: Consommer les marqueurs PENDANT la chauffe — le défaut que le P300 a payé**

⚠️ **Sans ça, personne n'appelle `markers_murs` pendant les 23 s de chauffe + repos** : le curseur du moteur ne bouge pas, puis le premier pas de décodage avale l'arriéré d'un coup, et tout ce qui dépasse le tampon part en `marqueurs_perdus`. C'était le **critique n°2** de la revue du P300, et son comportement **par défaut à chaque séance**. L'ErrP a une phase d'attente **plus longue**, donc le piège y est plus probable.

Le patron existe déjà dans `p300.py` (`_jeter_marqueurs_de_chauffe`) : reprends-le, en adaptant le message.

```python
    def tick(self, engine, lsl_ts, now):
        if self.phase in ("warmup", "rest"):
            self._jeter_marqueurs_de_chauffe(engine)
        super().tick(engine, lsl_ts, now)
```

- [ ] **Step 4: Le pas de décodage**

```python
    def _run_step(self, engine, lsl_ts):
        for ts, marqueur in engine.markers_murs(self.spec.id, post_s=self.post_s):
            if marqueur.get("event") != "feedback":
                continue        # un événement inconnu s'ignore : le protocole grandira
            self._traiter_feedback(engine, ts, lsl_ts)

    def _traiter_feedback(self, engine, ts, lsl_ts):
        epoque = epoch_from_stream(engine.recent, engine.recent_ts, ts, engine.acq.fs,
                                   pre_s=self.pre_s, post_s=self.post_s)
        if epoque is None:
            self._epoques_perdues += 1
            self._publish(-1, 0.0, artefact=0, lsl_ts=lsl_ts)
            return
        if self._est_artefact(epoque):
            self._artefacts += 1
            self._publish(-1, 0.0, artefact=1, lsl_ts=lsl_ts)
            return
        score = float(np.ravel(self.model.score(epoque[None, ...]))[0])
        self._publish(1 if score >= self.seuil else 0, score, artefact=0, lsl_ts=lsl_ts)
```

⚠️ **Le flux ne se tait JAMAIS** : un feedback envoyé produit toujours un échantillon, même perdu ou rejeté. Publier `0` sur un artefact reviendrait à affirmer « pas d'erreur » alors qu'on n'a rien vu — d'où `-1`, qui veut dire la même chose que dans le SSVEP, le MI et le P300.

- [ ] **Step 5: Le rejet d'artefact, relatif au repos**

```python
    def _est_artefact(self, epoque):
        """σ de l'époque contre σ du repos, voie par voie. Un clignement sur l'erreur est le cas
        FRÉQUENT : c'est justement au moment où la machine se trompe que l'utilisateur sursaute."""
        if self._sigmas_repos is None:
            return False
        sig = np.asarray(epoque, dtype=float).std(axis=0)
        return bool(np.any(sig > ERRP_ARTIFACT_RATIO * self._sigmas_repos))
```

- [ ] **Step 6: Écrire l'autotest du mode**

Sur du signal fabriqué, avec `synth_errp_epoch` pour les époques et un faux moteur. Ce qu'il doit prouver :

```python
    chk(rt.phase == "warmup", "l'ErrP commence par une chauffe")
    chk(SPEC.rest.warmup_s == SSVEP_WARMUP_S and SPEC.rest.duration_s == 8.0,
        f"chauffe 15 s puis repos 8 s, comme le SSVEP ({SPEC.rest})")
    chk(SPEC.marker_epoch_s == ERRP_PRE_S + ERRP_EPOCH_S,
        f"l'époque déclarée vaut pré+post ({SPEC.marker_epoch_s})")
    chk(ErrPRuntime.pre_s == ERRP_PRE_S and ErrPRuntime.post_s == ERRP_EPOCH_S,
        "pre_s/post_s sont des attributs de CLASSE, lisibles par registry.check()")
    # les marqueurs de la chauffe sont JETÉS, comptés, et dits une fois
    chk(rt._marqueurs_chauffe == 3 and jetes_dits == 1,
        f"3 marqueurs jetés pendant la chauffe, annoncés UNE fois ({rt._marqueurs_chauffe})")
    # un artefact publie -1, jamais 0
    chk(ligne_artefact[0] == -1 and ligne_artefact[2] == 1,
        f"une époque rejetée publie -1 et artefact=1, jamais 0 ({ligne_artefact})")
    # le flux ne se tait jamais
    chk(len(pub.lignes) == n_feedbacks,
        f"un échantillon par feedback envoyé, quoi qu'il arrive ({len(pub.lignes)}/{n_feedbacks})")
```

- [ ] **Step 7: Lancer**

```bash
python src/core/modes/errp.py
python src/core/server.py --smoke
```

- [ ] **Step 8: Commit**

```bash
git add src/core/modes/errp.py
git commit -m "Give the ErrP a runtime, a rest baseline, and a verdict per feedback"
```

---

## Task 3: Le réglage — un taux, pas un seuil

**Files:**
- Modifier : `src/core/modes/errp.py`

**Interfaces:**
- Consumes : `core.errp_decoder.pick_threshold(y, scores, tnr_target)` → `(seuil, {"tpr","tnr","bal_acc"})` · `model.oof_scores_`, `model.oof_y_`
- Produces : `ErrPRuntime.seuil`, `ErrPRuntime.point_de_fonctionnement` → `{"tnr_target", "tpr", "tnr", "seuil"}`

⚠️ **C'est le seul endroit où ce mode s'écarte du patron P300, et ce n'est pas une invention** : `ErrPModel` prend déjà `tnr_target` en paramètre et stocke `oof_scores_` / `oof_y_` avec le commentaire « pour régler le seuil a posteriori · recalcul TPR/TNR à tout seuil ». Le décodeur a été écrit pour ça.

- [ ] **Step 1: Déclarer le réglage**

```python
        Param(
            key="tnr_target",
            label="Bonnes commandes gardées",
            kind="float",
            default=ERRP_TNR_TARGET,
            min=0.50, max=0.99,
            help="La part des BONNES commandes que tu veux garder. Le moteur en déduit son seuil "
                 "sur les données de TA calibration. Monter cette valeur annule moins de bonnes "
                 "commandes mais attrape moins d'erreurs — mesuré sur la séance de référence : "
                 "garder 95 % n'attrape que 24 % des erreurs, garder 85 % en attrape 50 %, "
                 "garder 70 % en attrape 71 %. Il n'y a pas de repas gratuit.",
        ),
```

- [ ] **Step 2: Recalculer le seuil au démarrage, et DIRE ce qu'on a obtenu**

```python
        cible = float(params["tnr_target"])
        self.seuil, mesures = pick_threshold(self.model.oof_y_, self.model.oof_scores_,
                                             tnr_target=cible)
        self.point_de_fonctionnement = {"tnr_target": cible, "seuil": self.seuil,
                                        "tpr": mesures["tpr"], "tnr": mesures["tnr"]}
        # ⚠️ Le TNR obtenu n'est pas toujours celui visé : `pick_threshold` retombe sur le seuil qui
        # MAXIMISE le TNR quand la cible est inatteignable. Sans ce message, l'étudiant croirait
        # avoir obtenu ce qu'il a demandé.
        print(f"[errp] point de fonctionnement : garde {mesures['tnr']:.1%} des bonnes commandes "
              f"(visé {cible:.0%}), attrape {mesures['tpr']:.1%} des erreurs — seuil {self.seuil:.3f}")
```

- [ ] **Step 3: Écrire LE TEST DE MONOTONIE, avant de le voir passer**

⚠️ **C'est le test qui protège le seul réglage du mode.** Un réglage qui ne changerait rien est exactement le genre de décor que ce projet combat — et la revue du P300 a trouvé exactement ça (`stream_in` était cosmétique).

```python
    # Demander à garder PLUS de bonnes commandes doit donner un seuil PLUS HAUT et attraper MOINS
    # d'erreurs. C'est une MONOTONIE : une implémentation cassée (seuil constant, cible ignorée,
    # sens inversé) ne peut pas la simuler.
    points = []
    for cible in (0.70, 0.85, 0.95):
        seuil, m = pick_threshold(modele.oof_y_, modele.oof_scores_, tnr_target=cible)
        points.append((cible, seuil, m["tpr"], m["tnr"]))
    seuils = [p[1] for p in points]
    tprs = [p[2] for p in points]
    chk(seuils[0] < seuils[1] < seuils[2],
        f"viser plus de bonnes commandes MONTE le seuil ({[round(s, 3) for s in seuils]})")
    chk(tprs[0] > tprs[1] > tprs[2],
        f"...et fait attraper MOINS d'erreurs ({[round(t, 3) for t in tprs]})")
    chk(all(p[3] >= p[0] - 1e-9 for p in points),
        f"et chaque point atteint la cible demandée ({[(p[0], round(p[3], 3)) for p in points]})")
```

- [ ] **Step 4: Preuve ROUGE-PUIS-VERT du test de monotonie**

Casse le réglage : remplace `tnr_target=cible` par `tnr_target=ERRP_TNR_TARGET` dans le recalcul — c'est-à-dire un réglage qui ne fait rien, la panne exacte que ce test existe pour attraper.

Run: `python src/core/modes/errp.py`
Expected: **ÉCHEC** sur la monotonie des seuils, code de sortie **1**.

Remets, relance, colle le VERT. **Colle les deux sorties dans le rapport.**

- [ ] **Step 5: Commit**

```bash
git add src/core/modes/errp.py
git commit -m "Let the student set a rate, and derive the threshold from their own calibration"
```

---

## Task 4: Le flux, ses métadonnées, et le mode au registre

**Files:**
- Modifier : `src/core/lsl_io.py`, `src/core/modes/registry.py`, `src/core/modes/external.py`, `src/core/modes/errp.py`, `src/console/app.py`

**Interfaces:**
- Consumes : `ErrPRuntime.point_de_fonctionnement` (T3)
- Produces : `errp_channel_labels()` → `["error", "score", "threshold", "artifact"]` · `DecodedErrPPublisher(point, n_calib, instance="")` avec `.push(error, score, threshold, artifact, lsl_ts=None)`

- [ ] **Step 1: Le publieur, dans `src/core/lsl_io.py`**

À placer après `DecodedP300Publisher`, sur la même forme.

```python
def errp_channel_labels():
    """Voies du flux `decoded_errp`. Une seule fonction pour le publieur ET le `ModeSpec`."""
    return ["error", "score", "threshold", "artifact"]


class DecodedErrPPublisher:
    """`<PREFIX>_decoded_errp` : la machine vient-elle de se tromper. Un échantillon par feedback.

    ⚠️ `error = -1` signifie **« pas de verdict »** — époque perdue ou rejetée pour artefact — et
    jamais « pas d'erreur ». Un clignement au moment où la machine se trompe est le cas FRÉQUENT :
    publier 0 affirmerait qu'il n'y a pas eu d'erreur alors qu'on n'a rien vu.

    ⚠️ **Les métadonnées portent le POINT DE FONCTIONNEMENT mesuré**, et c'est une exigence, pas un
    ornement. Au réglage par défaut ce détecteur attrape UNE ERREUR SUR DEUX et annule une bonne
    commande sur sept. Une application qui lit `error = 1` doit pouvoir savoir qu'elle tient une
    pièce légèrement biaisée, pas un verdict — sinon elle traitera le flux comme fiable.
    """

    def __init__(self, point, n_calib, instance=""):
        labels = errp_channel_labels()
        info = StreamInfo(stream_name("decoded_errp"), "Decoded", len(labels),
                          IRREGULAR_RATE, "float32", _source_id("decoded_errp", instance))
        chans = info.desc().append_child("channels")
        for label in labels:
            ch = chans.append_child("channel")
            ch.append_child_value("label", label)
        desc = info.desc().append_child("decoding")
        desc.append_child_value("paradigm", "ErrP")
        desc.append_child_value("decision_scale", "logodds")
        desc.append_child_value("no_decision_index", "-1")
        desc.append_child_value("threshold", f"{point['seuil']:.6f}")
        desc.append_child_value("tnr_target", f"{point['tnr_target']:.4f}")
        desc.append_child_value("tpr_measured", f"{point['tpr']:.4f}")
        desc.append_child_value("tnr_measured", f"{point['tnr']:.4f}")
        desc.append_child_value("calibration_epochs", str(int(n_calib)))
        desc.append_child_value("measured_on", "1 person, 1 session")
        self.outlet = StreamOutlet(info)

    def push(self, error, score, threshold, artifact, lsl_ts=None):
        row = [float(error), float(score), float(threshold), float(artifact)]
        block = np.ascontiguousarray(np.asarray(row).reshape(1, -1), dtype=np.float32)
        self.outlet.push_chunk(block, [float(lsl_ts) if lsl_ts else local_clock()])
```

- [ ] **Step 2: Enregistrer le mode, retirer l'entrée « appli pygame »**

Dans `registry.py` :

```python
from core.modes import errp, external, mi, neuro, p300, raw, ssvep  # noqa: E402

MODES = (
    raw.SPEC,
    ssvep.SPEC,
    neuro.SPEC,
    mi.SPEC,
    p300.SPEC,
    errp.SPEC,          # l'ErrP a rejoint le moteur : 2e client du tuyau des marqueurs
    external.CVEP,      # il ne reste qu'UN mode que le moteur ne sait pas faire
)
```

Dans `external.py` : supprimer la constante `ERRP`, et **corriger la docstring du module**, qui parle de « deux entrées » et cite l'ErrP. Il n'en reste qu'une.

- [ ] **Step 3: Le smoke de la console — NE RIEN TOUCHER, vérifié**

⚠️ **Il n'y a rien à faire ici, et c'est contre-intuitif : ne « corrige » pas ce fichier.**

`src/console/app.py:274-281` portait un compte en dur (`== 3`, puis `== 2`), qui a cassé à chaque
mode migré. La revue du chantier P300 l'a fait réécrire en **comparaison d'identités dérivées du
registre** :

```python
    attendu_externes = sorted(s["id"] for s in registry.catalog() if s["status"] != "moteur")
    externes = [t for t in console.grid.tuiles.values() if t.spec["status"] != "moteur"]
    chk(sorted(t.spec["id"] for t in externes) == attendu_externes, …)
```

Il **s'adapte donc tout seul** dès que `external.ERRP` disparaît du registre. Le seul travail est de
lancer le smoke et de vérifier qu'il passe — s'il échoue, c'est que l'étape 2 est incomplète, pas
que cette assertion est à retoucher.

- [ ] **Step 4: Lancer**

```bash
python src/core/lsl_io.py
python src/core/modes/registry.py     # 7 modes, dont 6 dans le moteur
python src/core/modes/errp.py
python src/core/server.py --smoke
python src/console/app.py --smoke
```

- [ ] **Step 5: Commit**

```bash
git add src/core/lsl_io.py src/core/modes/registry.py src/core/modes/external.py src/core/modes/errp.py src/console/app.py
git commit -m "Publish the ErrP as the engine's fifth mode, operating point included"
```

---

## Task 5: L'émetteur d'exemple, et LE test d'alignement

**Files:**
- Créer : `src/research/errp_stimulus.py`
- Modifier : `src/core/modes/errp.py` (le test d'alignement dans son autotest)

**Ton modèle de forme :** `src/research/p300_stimulus.py`, livré la veille. Même patron : autonome, `--windowed`, `--smoke` sans écran, et **il n'ouvre PAS le casque** — c'est ce qui permet de le lancer en même temps que le moteur.

- [ ] **Step 1: Le stimulus — une piste, des erreurs délibérées**

Le protocole existe déjà dans le démonstrateur de `src/research/app.py` : un point sur une piste de `ERRP_TRACK_CELLS = 7` cases, qui avance vers une cible ; à chaque pas la machine se trompe **délibérément** avec la probabilité `ERRP_ERROR_RATE = 0.28`, et le feedback reste affiché `ERRP_FEEDBACK_S = 1.0` s.

Le geste critique, identique au P300 :

```python
        pygame.display.flip()
        # L'HORODATAGE SE PREND ICI, juste après que le feedback est À L'ÉCRAN. 40 ms d'avance
        # décalent toutes les époques de deux frames, et le décodeur moyenne une réponse qui n'a
        # pas encore eu lieu. Rien ne lève d'erreur ; les scores sortent, et ils sont du bruit.
        outlet.push_sample([json.dumps({"mode": "errp", "event": "feedback"})],
                           timestamp=local_clock())
```

- [ ] **Step 2: Le `--smoke` de l'émetteur**

⚠️ Il doit **exécuter `run()` pour de vrai** sur `SDL_VIDEODRIVER=dummy`, comme le fait `p300_stimulus.py` depuis sa correction. Un smoke qui retourne avant l'import de pygame laisse **sans aucune couverture** les lignes qui contiennent le geste flip→horodatage, c'est-à-dire la seule chose que ce fichier existe pour enseigner.

Il vérifie aussi que la séquence est bien formée : un `feedback` par pas, et un taux d'erreur proche de `ERRP_ERROR_RATE`.

- [ ] **Step 3: LE TEST D'ALIGNEMENT, par le CONTENU**

⚠️ **Écris-le d'emblée sous cette forme.** La revue du P300 a établi qu'une assertion de **position** laisse passer le double filtrage : `filtfilt` est à phase nulle, sa réponse impulsionnelle équivalente est une autocorrélation maximale au lag 0, donc un `bandpass()` ajouté par erreur **laisse le pic exactement au même échantillon**. Or `ErrPModel` filtre déjà en interne.

```python
    # Un pic d'amplitude unique planté à un instant CONNU, dans un tampon par ailleurs nul.
    fs = 250.0
    n_pre, n_post = int(round(ERRP_PRE_S * fs)), int(round(ERRP_EPOCH_S * fs))
    t0 = 1000.0
    ts = np.arange(t0, t0 + 4.0, 1.0 / fs)
    eeg = np.zeros((len(ts), 8))
    instant = t0 + 2.0
    i_pic = int(np.searchsorted(ts, instant))
    eeg[i_pic, :] = 42.0          # une valeur qu'aucun calcul ne produit par hasard

    moteur.recent, moteur.recent_ts = eeg, ts
    rt._traiter_feedback(moteur, instant, lsl_ts=instant)

    # UNE assertion qui épingle position, forme, ordre des voies ET absence de traitement.
    chk(np.array_equal(rt._derniere_epoque, eeg[i_pic - n_pre:i_pic + n_post]),
        "⚠️ ALIGNEMENT : l'époque constituée par le runtime est EXACTEMENT la tranche brute du "
        "tampon — même position, même forme, même ordre de voies, et AUCUN traitement appliqué "
        "en chemin (un filtrage ajouté ici laisserait le pic au même échantillon et passerait "
        "une assertion de position)")
```

Le runtime doit donc garder sa dernière époque (`self._derniere_epoque`) pour que le test puisse la lire.

- [ ] **Step 4: Preuve ROUGE-PUIS-VERT du test d'alignement**

Ajoute un `bandpass(epoque, engine.acq.fs)` dans `_traiter_feedback`, juste avant le scorage.

Run: `python src/core/modes/errp.py`
Expected: **ÉCHEC** sur l'assertion d'alignement, code de sortie **1**.

⚠️ **Vérifie et note dans le rapport que le pic reste au même échantillon** malgré le filtre : c'est la démonstration que seule l'égalité au contenu ferme ce trou. Retire le filtre, relance, colle le VERT.

- [ ] **Step 5: Lancer**

```bash
python src/research/errp_stimulus.py --smoke
python src/core/modes/errp.py
python src/research/app.py --smoke
python src/core/server.py --smoke
```

- [ ] **Step 6: Commit**

```bash
git add src/research/errp_stimulus.py src/core/modes/errp.py
git commit -m "Ship the ErrP stimulus, and pin the epoch by its content"
```

---

## Task 6: La documentation

**Files:** `docs/markers.md`, `docs/SPEC.md`, `docs/recette.md`, `README.md`, `CLAUDE.md`, `src/research/__init__.py`

> **Note pour le coordinateur :** cette tâche s'écrit **sans sous-agent**. Mesuré trois fois sur ce projet — un sous-agent n'apporte rien à de la documentation et coûte un tour de relecture.

- [ ] **Step 1: `docs/markers.md` — un événement de plus**

En **anglais**, comme le reste du fichier. Ajouter la section ErrP : l'événement `{"mode": "errp", "event": "feedback"}`, la fenêtre d'époque, et **les deux choses qu'un client doit savoir** :

- le flux publie son point de fonctionnement, et au défaut il attrape **une erreur sur deux** ;
- deux feedbacks plus rapprochés que 0,9 s produisent des époques qui **se recouvrent**, donc le même ErrP peut être noté deux fois. C'est un artefact, pas de la politique applicative — le moteur ne le tait pas.

Et rappeler que **la période réfractaire appartient au client** : le moteur constate, il n'annule rien.

- [ ] **Step 2: `docs/SPEC.md` — §5 et §14**

§5 : remplacer la ligne ErrP par le format réel, avec l'AUC, la p-valeur et le point de fonctionnement.
§14 : marquer le chantier fait, et **écrire ce qui reste dehors** — la calibration ErrP jouée par le moteur, le control plane, et le c-VEP qui reste le dernier mode non publié.

- [ ] **Step 3: `docs/recette.md` — deux tests**

Un test de niveau 1 (sans casque : moteur + émetteur, un verdict sort) et un **2.8** au casque, avec l'avertissement qui compte : **une erreur sur deux est attrapée au réglage par défaut**, donc ne pas conclure d'un essai. Et rappeler que le TPR se règle.

- [ ] **Step 4: `README.md` et `CLAUDE.md`**

README : **5 modes publiés sur 6**, la ligne ErrP du tableau des flux, `errp_stimulus.py` dans les commandes.
CLAUDE.md : l'appli pygame ne donne plus accès qu'au **c-VEP** ; ajouter `python src/core/errp_models.py` et `python src/core/modes/errp.py` à la liste des autotests.
`src/research/__init__.py` : `errp_decoder` a migré, `errp_stimulus.py` n'ouvre pas le casque.

- [ ] **Step 5: Relancer la totalité des autotests, un par un**

⚠️ Jamais en parallèle : ils publient tous sur les mêmes noms de flux.

- [ ] **Step 6: Commit**

```bash
git add docs/ README.md CLAUDE.md src/research/__init__.py
git commit -m "Document the ErrP, and say plainly what it is worth"
```

---

## Auto-relecture du plan

**Couverture de la spec** — §2 (les mesures) → citées en tête et en T1 step 7 · §3 (périmètre) → T6 step 2 · §4.1 (le moteur publie) → T2 step 1, docstring · §4.2 (le taux) → T3 · §4.3 (`-1`) → T2 step 4 et T4 step 1 · §5.3 (le pickle) → T1 steps 4-7 · §6 (le contrat) → T5 step 1, T6 step 1 · §7 (le flux) → T4 · §8 (le repos ET la chauffe) → T2 steps 2-3 · §9 (pannes) → T2 step 4, T4 step 1 · §10 (tests) → T1 step 6, T3 step 4, T5 step 4.

**Cohérence des types** — `point_de_fonctionnement` produit en T3 avec les clés `tnr_target`/`seuil`/`tpr`/`tnr`, consommé sous ces clés en T4. `pre_s`/`post_s` déclarés attributs de classe en T2, lus par `registry.check()` en T4. `_derniere_epoque` introduit en T5 step 3, et c'est le seul état que le test lit.

**Le point faible connu, et il est assumé** : le ré-entraînement de T1 doit reproduire l'AUC de 0,776. S'il s'en écarte, le point de fonctionnement publié en T4 sera faux, et tout le reste du chantier reposerait sur un chiffre périmé. C'est pourquoi T1 step 7 demande de **coller la sortie brute** et de le dire plutôt que de continuer.
