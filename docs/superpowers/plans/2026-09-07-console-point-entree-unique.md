# La console, seul point d'entrée — plan d'implémentation

> **Pour les agents :** SOUS-COMPÉTENCE REQUISE — utiliser `superpowers:subagent-driven-development`
> (recommandé) ou `superpowers:executing-plans` pour exécuter ce plan tâche par tâche. Les étapes
> utilisent des cases à cocher (`- [ ]`).

**But :** une personne qui n'ouvre jamais un terminal peut contrôler le contact, calibrer les quatre
modes à modèle, choisir un modèle, afficher un stimulus, décoder et lire les résultats — depuis la
console seule.

**Architecture :** les fenêtres de stimulus dessinent et publient des marqueurs, le moteur enregistre
et entraîne, la console orchestre et décide seule de ce qui entre dans `data/`. Les trois émetteurs
montent dans un quatrième paquet `src/stimulus/`. Les calibrations du P300, de l'ErrP et du c-VEP
deviennent des calibrations **jouées par le moteur** et pilotées par marqueurs, sur le patron de
`core/modes/mi_calib.py`.

**Pile technique :** numpy, scipy, sklearn, pyriemann, pyntbci, pylsl, pygame (fenêtres seulement),
PySide6 (console seulement).

**Spec :** [docs/superpowers/specs/2026-09-07-console-point-entree-unique-design.md](../specs/2026-09-07-console-point-entree-unique-design.md) (commit `493e9fb`)

---

## Contraintes globales

Elles lient **toutes** les tâches, sans être répétées dans chacune.

- `src/core/` n'importe **jamais** `src/research/`, `src/console/` ni `src/stimulus/`, et ne contient
  ni pygame ni Qt. `src/stimulus/` n'importe **jamais** `src/research/` ni `src/console/`. Vérifié
  par `python src/core/server.py --smoke` (`_smoke_frontiere`).
- **Une fenêtre de `src/stimulus/` n'ouvre JAMAIS le casque.** C'est ce qui lui permet de tourner à
  côté du moteur.
- **La console est un CLIENT** : aucune logique que le moteur ne possède déjà, aucun catalogue
  recopié, et **aucune écriture disque** — elle envoie des commandes.
- Code et commentaires **en français** ; `README.md`, `docs/markers.md` et les messages de commit
  **en anglais**. `CLAUDE.md`, `docs/SPEC.md` et `docs/recette.md` restent en français.
- Tout doit être testable **sans casque**.
- **Aucun test n'écrit dans le vrai `data/`** : dossier temporaire + nettoyage dans un `finally`, et
  vérification par `core.config.empreinte_dossier` — `git status` ne prouve rien, `data/` est
  gitignoré. Ce sont des enregistrements EEG d'une personne identifiable sur un dépôt PUBLIC.
- Un autotest **sort en 1** quand il échoue. Un autotest qui ne peut pas échouer ne teste rien.
- ⚠️ **Un seul programme du projet à la fois** pendant les tests : les noms de flux LSL sont un
  contrat public, donc identiques pour toutes les instances. Vérifier qu'aucun python du projet ne
  traîne avant de conclure à un échec.
- Constantes nouvelles, à poser dans `src/core/config.py` et à utiliser telles quelles :
  `CALIB_FENETRE_ATTENTE_S = 30.0`, `CALIB_FENETRE_SILENCE_S = 15.0`,
  `CALIB_TMP_PREFIX = "calib_candidat_"`.
- Voies clés déjà présentes dans `src/core/config.py`, à réutiliser sans les recopier :
  `OCCIPITAL` (:130), `CVEP_CHANNELS` (:321), `P300_MIDLINE` (:742), `NEURO_KEY_CHANNELS` (:806),
  `ERRP_MIDLINE` (:850).
- **Ne pas rouvrir** : aucun mode nouveau, aucun décodeur nouveau, aucun seuil de décision retouché.
  Les mesures d'honnêteté existantes (CV groupée par essai, McNemar exact, AUC hors-pli +
  permutation) suivent le code sans être modifiées.

---

## Structure des fichiers

| fichier | responsabilité |
|---|---|
| `src/stimulus/__init__.py` | *(créé)* le quatrième paquet |
| `src/stimulus/refresh.py` | *(créé)* `measure_refresh`, déménagé depuis `research/ssvep_stimulus.py` |
| `src/stimulus/registry.py` | *(créé)* `FENETRES`, `commande(stimulus_id, calibrer=False)` — le SEUL endroit qui nomme un module de fenêtre |
| `src/stimulus/p300.py` | *(déménagé + modifié)* ex-`research/p300_stimulus.py`, gagne `--calibrer` |
| `src/stimulus/errp.py` | *(déménagé + modifié)* ex-`research/errp_stimulus.py`, gagne `--calibrer` |
| `src/stimulus/cvep.py` | *(déménagé + modifié)* ex-`research/cvep_stimulus.py`, gagne `--calibrer` |
| `src/core/modes/marker_calib.py` | *(créé)* `MarkerCalibrationRuntime` : la ligne du temps PASSIVE |
| `src/core/modes/p300_calib.py` | *(créé)* `P300Calibration` — entraînement monté depuis `research/` |
| `src/core/modes/errp_calib.py` | *(créé)* `ErrPCalibration` |
| `src/core/modes/cvep_calib.py` | *(créé)* `CVEPCalibration` |
| `src/core/modes/contract.py` | *(modifié)* `Calib.kind`, `Calib.stimulus_id`, `ModeSpec.key_channels` |
| `src/core/config.py` | *(modifié)* les trois constantes ci-dessus |
| `src/core/server.py` | *(modifié)* `save_calibration`, `discard_calibration`, dossier temporaire, frontière AST étendue |
| `src/console/calib_page.py` | *(modifié)* écran de verdict : **Refaire** / **Enregistrer** |
| `src/console/mode_page.py` | *(modifié)* boutons « Calibrer » et « Lancer le stimulus » |
| `src/console/fenetres.py` | *(créé)* `LanceurFenetre` : un `QProcess`, son état, son arrêt |
| `src/console/contact_page.py` | *(créé)* le contrôle de liaison, monté depuis `research/ui.py` |
| `src/console/neuro_view.py` | *(créé)* l'histogramme temps réel des trois indices |
| `src/research/ui.py` | *(modifié)* accueille `Live`, `_live_loop`, `_running`, `_vote` |
| `src/research/app.py` | *(SUPPRIMÉ en dernier)*, une fois sa machinerie déménagée |
| `archive/ssvep_pilot.py`, `archive/p300_pilot.py`, `archive/errp_demo.py` | *(créés)* les trois écrans de pilotage retirés |
| `docs/markers.md` | *(modifié)* `calib_start`, `cue`, `calib_end` — contrat public, en anglais |
| `outils/Console EEG.bat` | *(créé)* le raccourci sans terminal |

---

## Task 1 : le paquet `src/stimulus/`, et la frontière qui le garde

**Files:**
- Create: `src/stimulus/__init__.py`, `src/stimulus/refresh.py`, `src/stimulus/registry.py`
- Create (déménagés) : `src/stimulus/p300.py`, `src/stimulus/errp.py`, `src/stimulus/cvep.py`
- Delete: `src/research/p300_stimulus.py`, `src/research/errp_stimulus.py`,
  `src/research/cvep_stimulus.py`
- Modify: `src/research/ssvep_stimulus.py` (importe `measure_refresh` de sa nouvelle maison),
  `src/core/server.py` (`_smoke_frontiere`, `_imports_interdits`)

**Interfaces:**
- Produces: `stimulus.refresh.measure_refresh(surface_ou_ecran) -> float` (signature INCHANGÉE,
  copiée telle quelle depuis `research/ssvep_stimulus.py`) ;
  `stimulus.registry.FENETRES: dict[str, str]` associant un `stimulus_id` à un chemin de module
  (`{"p300": "stimulus/p300.py", "errp": "stimulus/errp.py", "cvep": "stimulus/cvep.py"}`) ;
  `stimulus.registry.commande(stimulus_id, calibrer=False) -> list[str]` rendant la ligne de
  commande complète (`[sys.executable, "-u", <chemin absolu>, "--calibrer"?]`).
- Consumes: rien de nouveau.

⚠️ **`measure_refresh` doit déménager avec les fenêtres.** Les trois l'importent aujourd'hui de
`research/ssvep_stimulus.py` (`p300_stimulus.py:210`, `errp_stimulus.py:259`,
`cvep_stimulus.py:406`). Le laisser là créerait l'arête `stimulus → research`, exactement ce que la
frontière de l'étape 1 interdit.

⚠️ **`errp_stimulus.py:574` importe `_decide_step, _new_goal, _run_block` de
`research/errp_calibrate.py`.** Cet import est toléré à cette tâche-ci **uniquement dans le bloc
`--smoke`** ; la tâche 7 le supprime en fusionnant les deux. Si la frontière le refuse dès
maintenant, déplacer ces trois helpers dans `stimulus/errp.py` (ils sont la piste, ils appartiennent
à la fenêtre) et faire importer `research/errp_calibrate.py` depuis là — `research → stimulus` est
autorisé.

- [ ] **Étape 1 : étendre la frontière AST — le test d'abord**

Dans `src/core/server.py`, `_smoke_frontiere` teste `_imports_interdits` sur des extraits fabriqués
avant de scanner l'arbre. Ajouter aux extraits, et étendre le scan :

```python
    # Nouveaux extraits fabriqués (partie 1) : `stimulus` est interdit dans `core` au même titre
    # que `research` et `console`. Sans cette ligne, la règle écrite serait plus large que la
    # règle vérifiée — le cran qui compte, cf. la correction de revue du tour 2.
    fabrique.append(("from stimulus.registry import commande\n", ["stimulus"]))
    fabrique.append(("import stimulus.p300\n", ["stimulus"]))

    # Partie 3, NOUVELLE : `stimulus` est un paquet du produit, pas du banc d'essai. Il n'importe
    # ni `research` ni `console` — sinon la console, qui l'importe, tirerait tout `research` avec
    # elle, et une fenêtre de stimulus cesserait d'être lançable sur une machine sans Qt.
    violations_stim = []
    for chemin in _fichiers_py(_os.path.join(_RACINE, "src", "stimulus")):
        for nom in _imports_interdits(chemin, interdits=("research", "console")):
            violations_stim.append(f"{chemin} importe {nom}")
    chk(not violations_stim,
        f"src/stimulus/ n'importe ni research ni console ({len(violations_stim)} violation(s) : "
        f"{violations_stim[:3]})")
```

`_imports_interdits` prend aujourd'hui sa liste d'interdits en dur ; l'extraire en paramètre
`interdits=(...)` avec pour défaut la liste actuelle **plus `stimulus`**, pour que `core` et
`stimulus` soient scannés par le même code.

- [ ] **Étape 2 : lancer, vérifier l'échec**

```bash
python src/core/server.py --smoke
```

Attendu : **ÉCHEC** sur les extraits fabriqués (`stimulus` n'est pas encore dans les interdits) et
sur le scan du dossier `src/stimulus/`, qui n'existe pas.

- [ ] **Étape 3 : créer le paquet et déménager**

`git mv` les trois fichiers, créer `__init__.py`, `refresh.py` (le corps de `measure_refresh` copié
tel quel, docstring comprise) et `registry.py` :

```python
"""Ce que la console sait lancer. Le SEUL endroit du dépôt qui nomme un module de fenêtre.

`core` ne nomme aucune de ces fenêtres : le contrat d'un mode porte une CLÉ (`Calib.stimulus_id`),
et c'est ici qu'elle se résout. C'est ce qui garde l'arête `core -> stimulus` inexistante, tout en
évitant que la console ne tienne un catalogue recopié.
"""

import os
import sys

_ICI = os.path.dirname(os.path.abspath(__file__))

FENETRES = {"p300": "p300.py", "errp": "errp.py", "cvep": "cvep.py"}


def commande(stimulus_id, calibrer=False):
    """La ligne de commande complète pour lancer une fenêtre. Lève `KeyError` si la clé est inconnue.

    `-u` : la sortie de la fenêtre doit arriver non tamponnée à la console, sinon un message
    d'erreur reste bloqué dans le tampon d'un processus qui vient de mourir — c'est-à-dire
    exactement quand on en a besoin.
    """
    chemin = os.path.join(_ICI, FENETRES[stimulus_id])
    argv = [sys.executable, "-u", chemin]
    if calibrer:
        argv.append("--calibrer")
    return argv
```

Corriger les trois imports de `measure_refresh` et celui de `research/ssvep_stimulus.py`, qui
importe désormais depuis `stimulus.refresh`.

- [ ] **Étape 4 : prouver que la garde n'est pas muette**

Ajouter temporairement `from research.ui import App` en tête de `src/stimulus/p300.py`, relancer
`python src/core/server.py --smoke`. Attendu : **rouge**, en nommant le fichier. Retirer, relancer,
coller les deux sorties.

- [ ] **Étape 5 : lancer les tests**

```bash
python src/core/server.py --smoke
python src/stimulus/p300.py --smoke
python src/stimulus/errp.py --smoke
python src/stimulus/cvep.py --smoke
python src/research/app.py --smoke
```

- [ ] **Étape 6 : commit**

```bash
git add -A src/stimulus src/research src/core/server.py
git commit -m "Give the stimulus windows a package of their own"
```

---

## Task 2 : le contrat — qui mène la ligne du temps

**Files:**
- Modify: `src/core/modes/contract.py` (`Calib`, `ModeSpec`), `src/core/modes/mi.py`,
  `src/core/modes/p300.py`, `src/core/modes/errp.py`, `src/core/modes/cvep.py`,
  `src/core/modes/ssvep.py`, `src/core/modes/neuro.py`, `src/core/modes/registry.py`,
  `src/core/server.py`

**Interfaces:**
- Produces: `Calib.kind ∈ {"moteur", "fenetre"}` ; `Calib.stimulus_id: str = ""` ;
  `ModeSpec.key_channels: tuple = ()`. `Calib.reason` est SUPPRIMÉ.
- Consumes: `stimulus.registry.FENETRES` — **uniquement dans le test**, jamais depuis `core`.

`kind` disait « console » vs « natif ». « natif » signifiait *reste dans l'appli pygame*, ce qui
devient faux : les quatre calibrations sont jouées par le moteur. Il dit désormais **qui mène la
ligne du temps** — le moteur (MI, endogène) ou une fenêtre (P300, ErrP, c-VEP).

- [ ] **Étape 1 : écrire les assertions dans `contract.py::_selftest`**

```python
    # `stimulus_id` est OBLIGATOIRE quand la fenêtre mène, et INTERDIT quand c'est le moteur : un
    # `stimulus_id` posé sur une calibration "moteur" ferait apparaître un bouton « Lancer le
    # stimulus » sur un mode qui n'en a pas, et un `stimulus_id` manquant sur une calibration
    # "fenetre" donnerait un bouton « Calibrer » qui ne lance rien — le clic silencieux qu'on répare.
    try:
        Calib(kind="fenetre", stimulus_id="", runtime_cls=object)
        chk(False, "une calibration « fenetre » sans stimulus_id doit être refusée")
    except ValueError as e:
        chk("stimulus_id" in str(e), f"...et le refus nomme le champ manquant ({e})")

    try:
        Calib(kind="moteur", stimulus_id="p300", runtime_cls=object)
        chk(False, "une calibration « moteur » AVEC un stimulus_id doit être refusée")
    except ValueError as e:
        chk("moteur" in str(e), f"...et le refus dit pourquoi ({e})")

    chk(all(c.kind in ("moteur", "fenetre") for c in _toutes_les_calibs()),
        "les quatre calibrations déclarent un kind connu")
    chk(not hasattr(Calib(kind="moteur", runtime_cls=object), "reason"),
        "`reason` a disparu : plus aucune calibration ne reste dehors")
```

Et dans `registry.py::check` — le contrôle structurel qui compare déjà `spec.marker_epoch_s` aux
attributs du runtime :

```python
    # Chaque `stimulus_id` déclaré par un contrat doit exister dans le registre des fenêtres.
    # ⚠️ L'import est LOCAL à ce test, jamais en tête de module : `core` n'importe pas `stimulus`.
    from stimulus.registry import FENETRES
    manquants = [s.id for s in MODES
                 if s.calibration is not None and s.calibration.kind == "fenetre"
                 and s.calibration.stimulus_id not in FENETRES]
    chk(not manquants, f"chaque stimulus_id déclaré a une fenêtre ({manquants})")

    # Les voies clés annoncées existent sur le casque à 8 voies.
    hors_bornes = [(s.id, c) for s in MODES for c in s.key_channels if not 0 <= c < 8]
    chk(not hors_bornes,
        f"les voies clés sont des indices valides du montage 8 voies ({hors_bornes})")
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

```bash
python src/core/modes/contract.py
python src/core/modes/registry.py
```

- [ ] **Étape 3 : modifier le contrat**

```python
@dataclass(frozen=True)
class Calib:
    kind: str                   # "moteur" (le moteur mène) | "fenetre" (une fenêtre mène)
    stimulus_id: str = ""       # la CLÉ que `stimulus/registry.py` résout ; "" si kind == "moteur"
    label: str = ""
    briefing: tuple = ()
    params: tuple = ()
    epoch_s: float = 0.0
    runtime_cls: object = None

    def __post_init__(self):
        if self.kind not in ("moteur", "fenetre"):
            raise ValueError(f"kind inconnu : « {self.kind} » (attendu « moteur » ou « fenetre »)")
        if self.kind == "fenetre" and not self.stimulus_id:
            raise ValueError(
                "une calibration « fenetre » doit déclarer son stimulus_id : sans lui, le bouton "
                "« Calibrer » n'a aucune fenêtre à lancer et le clic reste silencieux")
        if self.kind == "moteur" and self.stimulus_id:
            raise ValueError(
                f"une calibration « moteur » ne lance aucune fenêtre : stimulus_id "
                f"« {self.stimulus_id} » est de trop")
```

Les quatre déclarations : le MI passe `kind="moteur"` ; le P300, l'ErrP et le c-VEP passent
`kind="fenetre"` avec leur `stimulus_id` et **gardent leur `runtime_cls` à `None` pour l'instant** —
les tâches 4, 7 et 8 les renseignent. `ModeSpec` gagne
`key_channels: tuple = ()`, renseigné depuis `core/config.py` : `OCCIPITAL` pour le SSVEP,
`CVEP_CHANNELS` pour le c-VEP, `P300_MIDLINE` pour le P300, `ERRP_MIDLINE` pour l'ErrP,
`NEURO_KEY_CHANNELS` pour le neuro, `(1, 2, 3)` (C3, Cz, C4) pour le MI.

⚠️ **`src/core/server.py:185` et son commentaire ligne 193 deviennent faux.** Le filtre
`spec.calibration.runtime_cls is not None` excluait les calibrations natives du dimensionnement du
tampon, avec un commentaire qui dit que leur `epoch_s` « ne dimensionne rien ». Les trois vont
gagner un `runtime_cls` : le filtre continue de fonctionner tel quel, mais **le commentaire doit
être réécrit** — sinon il affirmera le contraire de ce que fait le code.

- [ ] **Étape 4 : lancer les tests**

```bash
python src/core/modes/contract.py
python src/core/modes/registry.py
python src/core/server.py --smoke
python src/console/app.py --smoke
```

- [ ] **Étape 5 : commit**

```bash
git add src/core src/console
git commit -m "Say who drives the calibration timeline, not where it lives"
```

---

## Task 3 : `MarkerCalibrationRuntime`, et LE test qui porte le chantier

**Files:**
- Create: `src/core/modes/marker_calib.py`
- Modify: `src/core/config.py` (les trois constantes)

**Interfaces:**
- Consumes: `core.modes.calibration.PHASES`, `PHASES_TERMINALES`, `CalibrationRuntime` (le contrat
  public qu'on réplique) ; `engine.markers_murs(mode_id, post_s=...) -> [(ts, marqueur)]` ;
  `engine.recent`, `engine.recent_ts`, `engine.acq.fs` ;
  `core.p300_decoder.epoch_from_stream(recent, recent_ts, ts, fs, pre_s=..., post_s=...)`.
- Produces: `MarkerCalibrationRuntime(spec, params, engine)` avec `tick(engine, now)`,
  `cancel()`, `terminee`, `resultat`, `probleme`, `phase`, `essai`, `total()`,
  `duree_estimee_s()`, `instruction()`, `rappel()`, et le hook `_entrainer(enregistre, fs)`.
  Attributs de classe à renseigner par les sous-classes : `runtime_cls_du_mode` (la classe du
  `ModeRuntime` correspondant, d'où l'on LIT `pre_s`/`post_s`).

**Ce que cette classe fait, et l'invariant qu'elle existe pour tenir.** Le moteur est **passif** :
il ne tire aucune consigne et ne décompte aucun essai. Il attend `calib_start`, encaisse les
marqueurs, prélève une époque **par le chemin du décodage**, et entraîne à `calib_end`.

⚠️ **L'invariant central du chantier :** `pre_s` et `post_s` ne sont **pas** redéclarés ici. Ils
sont LUS sur la classe du runtime de décodage :

```python
    @property
    def pre_s(self):
        return float(self.runtime_cls_du_mode.pre_s)

    @property
    def post_s(self):
        return float(self.runtime_cls_du_mode.post_s)
```

C'est ce qui rend le désaccord des deux épochages **structurellement impossible** plutôt que
simplement testé : changer `P300Runtime.pre_s` déplace la calibration du même coup. Le test de
l'étape 1 vérifie que ça reste vrai.

- [ ] **Étape 1 : écrire LE test — l'accord des deux épochages**

⚠️ **C'est le test qui porte le chantier.** Un décalage de quelques échantillons entre l'époque
d'entraînement et l'époque de décodage ne lève aucune exception : le modèle est entraîné sur un
alignement et appliqué sur un autre, il décode du bruit avec une confiance élevée, et tous les
autres tests restent verts (mesuré sur `modes/p300.py` : la mutation déplace le pic de −38
échantillons et 46 assertions restent vertes).

```python
    # Un signal SYNTHÉTIQUE, horodaté, et des marqueurs. On fait deux choses avec EXACTEMENT les
    # mêmes entrées : (a) une calibration qui enregistre ses époques, (b) le chemin de décodage du
    # mode. Les tableaux prélevés doivent être identiques ÉCHANTILLON PAR ÉCHANTILLON.
    fs = 250.0
    moteur = _MoteurFactice(fs=fs, secondes=20.0)     # remplit recent / recent_ts
    instants = [moteur.t0 + 5.0 + 0.37 * i for i in range(12)]

    calib = _CalibrationDeTest(spec_p300, {}, moteur)
    for ts in instants:
        calib.encaisser(moteur, ts, {"mode": "p300", "event": "flash", "target": 1})
    epoques_calib = [np.asarray(e) for e, _l in calib._enregistre]

    epoques_decodage = [epoch_from_stream(moteur.recent, moteur.recent_ts, ts, fs,
                                          pre_s=P300Runtime.pre_s, post_s=P300Runtime.post_s)
                        for ts in instants]

    chk(len(epoques_calib) == len(instants) and all(e is not None for e in epoques_decodage),
        f"les deux chemins produisent une époque pour chacun des {len(instants)} marqueurs")
    ecarts = [int(np.abs(a - b).max() > 0) for a, b in zip(epoques_calib, epoques_decodage)]
    chk(sum(ecarts) == 0,
        f"l'époque ENREGISTRÉE et l'époque DÉCODÉE sont identiques à l'échantillon près "
        f"({sum(ecarts)} époque(s) différente(s) sur {len(ecarts)})")
    chk(all(a.shape == b.shape for a, b in zip(epoques_calib, epoques_decodage)),
        "...y compris leur forme : même nombre d'échantillons, mêmes voies")

    # Et la raison pour laquelle ça restera vrai : la géométrie n'est pas recopiée, elle est LUE.
    chk(calib.pre_s == P300Runtime.pre_s and calib.post_s == P300Runtime.post_s,
        "la calibration LIT pre_s/post_s sur le runtime de décodage au lieu de les redéclarer")
```

Ajouter les trois causes d'abandon :

```python
    rt = _CalibrationDeTest(spec_p300, {}, moteur)
    rt.tick(moteur, moteur.t0)                                   # démarre la chauffe
    rt.tick(moteur, moteur.t0 + CALIB_FENETRE_ATTENTE_S + 1.0)   # aucun calib_start n'est venu
    chk(rt.phase == "annule" and "fenêtre" in rt.probleme.lower(),
        f"sans calib_start dans les {CALIB_FENETRE_ATTENTE_S:.0f} s, la calibration s'annule en "
        f"disant que la fenêtre ne s'est pas lancée ({rt.probleme})")

    rt2 = _calibration_demarree(moteur, essais_annonces=10)
    rt2.encaisser(moteur, moteur.t0 + 5.0, {"mode": "p300", "event": "cue", "target": 0})
    rt2.tick(moteur, moteur.t0 + 5.0 + CALIB_FENETRE_SILENCE_S + 1.0)
    chk(rt2.phase == "annule" and rt2.resultat is None,
        "une fenêtre qui meurt en cours annule SANS entraîner : une séance tronquée produirait un "
        "modèle que rien ne distingue d'un modèle complet dans la liste")

    rt3 = _calibration_demarree(moteur, essais_annonces=2)
    rt3.cancel()
    chk(rt3.terminee and rt3.resultat is None and rt3._enregistre == [],
        "l'abandon libère les époques et n'entraîne rien")
```

Et l'indifférence aux marqueurs hors calibration :

```python
    rt4 = _CalibrationDeTest(spec_p300, {}, moteur)   # jamais démarrée
    avant = len(rt4._enregistre)
    rt4.encaisser(moteur, moteur.t0 + 1.0, {"mode": "p300", "event": "cue", "target": 3})
    chk(len(rt4._enregistre) == avant,
        "un `cue` reçu hors calibration est ignoré sans erreur : c'est une fenêtre lancée en mode "
        "calibration pendant qu'un décodage tourne, et le moteur n'a pas à s'arrêter pour ça")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/core/modes/marker_calib.py`.
  Attendu : `ModuleNotFoundError` puis, une fois le squelette écrit, l'échec des assertions.

- [ ] **Étape 3 : écrire `MarkerCalibrationRuntime`**

La ligne du temps, phase par phase — le tableau de la spec §6 :

| phase | ce qui la déclenche |
|---|---|
| `chauffe` | au démarrage, `warmup_s` (15 s), marqueurs **jetés** — la dérive DC de l'Unicorn ne dépend pas de qui mène |
| `essais` | réception de `calib_start` ; le runtime mémorise `trials` pour l'avancement |
| `entrainement` | réception de `calib_end` |
| `fini` / `annule` | comme `CalibrationRuntime`, plus les deux causes propres ci-dessus |

Il n'y a **pas** de phase `echauffement` : la fenêtre gère son propre briefing.

- [ ] **Étape 4 : prouver le test rouge**

Décaler l'époque de la calibration d'un seul échantillon — remplacer l'appel par
`epoch_from_stream(..., pre_s=self.pre_s + 1.0 / fs, post_s=self.post_s)`. Relancer. Attendu :
**rouge** sur l'assertion « identiques à l'échantillon près ». Retirer, relancer, coller les deux
sorties.

- [ ] **Étape 5 : lancer les tests**

```bash
python src/core/modes/marker_calib.py
python src/core/modes/calibration.py
python src/core/server.py --smoke
```

- [ ] **Étape 6 : commit**

```bash
git add src/core/modes/marker_calib.py src/core/config.py
git commit -m "Cut training epochs with the code that cuts decoding epochs"
```

---

## Task 4 : le P300 de bout en bout

**Files:**
- Create: `src/core/modes/p300_calib.py`
- Modify: `src/stimulus/p300.py` (mode `--calibrer`), `src/core/modes/p300.py` (le `Calib` gagne
  son `runtime_cls`), `src/research/p300_calibrate.py` (réduit à sa moitié d'analyse hors ligne)

**Interfaces:**
- Consumes: `MarkerCalibrationRuntime`, `core.p300_decoder.P300Model`,
  `core.p300_models.chemin_horodate`.
- Produces: `P300Calibration(spec, params, engine)` avec
  `runtime_cls_du_mode = P300Runtime` ; `_entrainer(enregistre, fs)` rendant
  `{"modele": str, "nom": str, "n_essais": int, "auc": float, "verdict": str, "honnetete": str}`.
  La fenêtre publie `calib_start` / `cue` / `flash` / `round_end` / `calib_end`.

Le P300 passe en premier : c'est le mode à marqueurs le mieux connu, validé au casque par l'ancien
chemin, et le seul qui porte déjà un test d'alignement (`src/core/modes/p300.py`).

**Le protocole, côté fenêtre** — `--calibrer` ajoute au déroulé existant : un `calib_start` au
démarrage avec le nombre de manches, un `cue` **avant chaque manche** portant la cible que l'écran
vient de désigner au sujet, et un `calib_end` à la fin. Les `flash` et `round_end` gardent
exactement leur sens et leur horodatage — **après `pygame.display.flip()`**.

- [ ] **Étape 1 : écrire les tests**

Dans `src/core/modes/p300_calib.py::_selftest` :

```python
    # L'accuracy annoncée est celle de la SÉLECTION, pas celle des époques : c'est le chiffre qui
    # veut dire quelque chose pour l'utilisateur (« la cible désignée est-elle la bonne ? »), et
    # c'est celui que `research/p300_calibrate.py::_loro_selection` calculait déjà.
    res = _entrainer_sur_donnees_factices(n_manches=8)
    chk(0.0 <= res["auc"] <= 1.0, f"l'AUC est une probabilité ({res['auc']})")
    chk("honnetete" in res and res["honnetete"],
        "le résultat porte SA phrase d'honnêteté — celle du MI parle de 40 % à trois classes et "
        "n'a aucun sens ici")
    chk(res["modele"].startswith(dossier_temporaire),
        f"le modèle est écrit dans le dossier TEMPORAIRE, pas dans data/ ({res['modele']})")
```

Dans `src/stimulus/p300.py::--smoke`, en plus des assertions existantes :

```python
    marqueurs = _rejouer_calibration(manches=3, reps=4, seed=7)
    evenements = [m["event"] for m, _ts in marqueurs]
    chk(evenements[0] == "calib_start" and evenements[-1] == "calib_end",
        f"la séance s'ouvre par calib_start et se ferme par calib_end ({evenements[:2]}…)")
    cues = [m for m, _ts in marqueurs if m["event"] == "cue"]
    chk(len(cues) == 3, f"un `cue` par manche ({len(cues)} pour 3 manches)")
    chk(all("target" in c for c in cues), "chaque `cue` porte sa cible")
    # LA vérité-terrain doit être celle qui a été AFFICHÉE, pas celle qu'on voulait afficher.
    chk([c["target"] for c in cues] == _cibles_affichees(),
        "la cible annoncée par `cue` est celle que l'écran a réellement désignée")
    for m, ts in marqueurs:
        if m["event"] == "cue":
            suivants = [t for mm, t in marqueurs if mm["event"] == "flash" and t > ts]
            chk(suivants, "chaque `cue` précède les flashs de sa manche, jamais l'inverse")
            break
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

```bash
python src/core/modes/p300_calib.py
python src/stimulus/p300.py --smoke
```

- [ ] **Étape 3 : monter l'entraînement dans `core`**

Déménager depuis `src/research/p300_calibrate.py` : `_loro_selection`, `_archive`, et le corps de
`calibrate` qui suit la collecte — c'est-à-dire tout ce qui ne touche ni pygame ni `app`. Ce qui
reste dans `research/p300_calibrate.py` est l'analyse hors ligne d'un enregistrement existant.

Le geste critique côté fenêtre, identique aux trois émetteurs :

```python
        pygame.display.flip()
        # L'HORODATAGE SE PREND ICI, juste après que la frame est À L'ÉCRAN. Vaut pour `cue`
        # comme pour `flash` : un `cue` horodaté avant le flip annonce la cible une frame trop
        # tôt, et l'époque du premier flash de la manche est étiquetée sur la manche précédente.
        if nouveau_cue is not None:
            out.push_sample([json.dumps({"mode": "p300", "event": "cue",
                                         "target": nouveau_cue})], local_clock())
```

- [ ] **Étape 4 : lancer les tests**

```bash
python src/core/modes/p300_calib.py
python src/core/modes/p300.py
python src/stimulus/p300.py --smoke
python src/core/server.py --smoke
```

- [ ] **Étape 5 : commit**

```bash
git add src/core/modes/p300_calib.py src/core/modes/p300.py src/stimulus/p300.py src/research/p300_calibrate.py
git commit -m "Let the engine train the P300 from the window's own markers"
```

---

## Task 5 : la garde de sauvegarde — `data/` écrit à un seul endroit

**Files:**
- Modify: `src/core/server.py` (dossier temporaire, `save_calibration`, `discard_calibration`,
  nettoyage), `src/core/modes/mi_calib.py` (écrit dans le dossier reçu, ne décide plus),
  `src/core/modes/p300_calib.py`

**Interfaces:**
- Produces: commandes `save_calibration` et `discard_calibration`, mêmes conventions d'acceptation
  que `start_calibration` (`{"accepted": bool, "reason": str}`) ;
  `EngineServer.dossier_candidat` (un `tempfile.mkdtemp(prefix=CALIB_TMP_PREFIX)`) ;
  `snapshot()["calibration"]["candidat"]` = le dict rendu par `_entrainer`, ou `None`.

`MICalibration.__init__` accepte déjà un `dossier` (`src/core/modes/mi_calib.py`) et `_entrainer` y
écrit via `_chemins_libres`. Le moteur passe désormais le **dossier temporaire** à toutes les
calibrations, et `save_calibration` déplace les fichiers nommés dans le résultat vers `DATA_DIR`,
sous des noms horodatés libres.

- [ ] **Étape 1 : écrire les tests dans `server.py::_smoke`**

```python
    # 1. Rien n'entre dans data/ sans un geste explicite.
    empreinte_avant = empreinte_dossier(DATA_DIR)
    moteur = _moteur_de_test()
    res = _jouer_calibration_factice(moteur)          # va jusqu'à "fini"
    chk(empreinte_dossier(DATA_DIR) == empreinte_avant,
        "une calibration TERMINÉE n'a encore rien écrit dans data/ : le chiffre se lit AVANT que "
        "le modèle n'existe, sinon une calibration ratée devient le défaut en silence")
    chk(moteur.snapshot()["calibration"]["candidat"]["modele"].startswith(moteur.dossier_candidat),
        "le candidat vit dans le dossier temporaire")

    # 2. Le nom du candidat ne doit ressembler à AUCUN modèle découvrable — sinon une console
    #    fermée entre l'entraînement et la décision laisserait un orphelin que le moteur
    #    proposerait au démarrage suivant : le défaut qu'on ferme, rouvert par sa correction.
    for catalogue in (p300_models, errp_models, cvep_models, mi_models):
        chk(catalogue.modeles_disponibles(dossier=moteur.dossier_candidat) == [],
            f"{catalogue.__name__} ne découvre RIEN dans le dossier des candidats")

    # 3. Enregistrer déplace, ne copie pas, et n'écrase jamais.
    accepte = moteur.command("save_calibration", {})
    chk(accepte["accepted"], f"save_calibration est accepté après une calibration finie ({accepte})")
    chk(not _os.path.exists(res["modele"]), "le candidat a été DÉPLACÉ, pas copié")
    chk(empreinte_dossier(DATA_DIR) != empreinte_avant, "et le modèle est arrivé dans data/")

    # 4. Refaire supprime.
    moteur2 = _moteur_de_test()
    res2 = _jouer_calibration_factice(moteur2)
    moteur2.command("discard_calibration", {})
    chk(not _os.path.exists(res2["modele"]) and moteur2.snapshot()["calibration"] is None,
        "discard_calibration supprime le candidat et efface l'écran de verdict")

    # 5. Le nettoyage est INCONDITIONNEL — y compris sans décision.
    moteur3 = _moteur_de_test()
    dossier3 = moteur3.dossier_candidat
    _jouer_calibration_factice(moteur3)
    moteur3.close()                                   # personne n'a tranché
    chk(not _os.path.isdir(dossier3),
        "fermer le moteur sans trancher ne laisse aucun candidat orphelin sur le disque")

    # 6. Les deux commandes refusent proprement quand il n'y a rien à enregistrer.
    r = _moteur_de_test().command("save_calibration", {})
    chk(not r["accepted"] and r["reason"],
        f"save_calibration sans calibration terminée est refusé, avec un motif ({r})")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/core/server.py --smoke`.

- [ ] **Étape 3 : implémenter**

Le moteur crée son dossier temporaire à la construction et le supprime dans le `finally` de `run()`
**et** dans `close()`. `save_calibration` déplace chaque chemin du résultat
(`modele`, `enregistrement` s'il existe) vers `DATA_DIR` sous un nom horodaté libre, puis remet
`snapshot()["calibration"]["candidat"]` à `None` et laisse le résultat lisible.

⚠️ **`CALIB_TMP_PREFIX = "calib_candidat_"`** — vérifier qu'il ne correspond à aucun motif de
`p300_models`, `errp_models`, `cvep_models`, `mi_models`. C'est ce que teste l'assertion 2.

- [ ] **Étape 4 : lancer les tests**

```bash
python src/core/server.py --smoke
python src/core/modes/mi_calib.py
python src/core/modes/p300_calib.py
python src/core/mi_models.py
python src/core/p300_models.py
```

- [ ] **Étape 5 : commit**

```bash
git add src/core
git commit -m "Show the accuracy before the model exists, not after"
```

---

## Task 6 : la console — lancer, contrôler le contact, trancher

**Files:**
- Create: `src/console/fenetres.py`, `src/console/contact_page.py`
- Modify: `src/console/calib_page.py`, `src/console/mode_page.py`, `src/console/app.py`

**Interfaces:**
- Consumes: `stimulus.registry.commande(stimulus_id, calibrer=False)` ;
  `snapshot()["calibration"]["candidat"]` ; `snapshot()["quality"]` (le σ par voie et les verdicts
  que `core/lsl_io.py` produit déjà) ; `spec["key_channels"]`.
- Produces: `LanceurFenetre(argv, parent)` avec `.demarrer()`, `.arreter()`, `.etat` ∈
  `{"arrete", "lance", "mort", "echec"}` et le signal `change`.

**a. Le lanceur.** Un `QProcess` par fenêtre, la commande venant de `stimulus/registry.py` — jamais
écrite en dur. Il refuse d'en lancer deux, et **dit** quand le processus meurt anormalement : le
silence est précisément le défaut qu'on répare (cf. test 1.13 de la recette, cinq clics d'affilée
sur un bouton muet).

**b. Le contrôle de liaison.** Monté depuis `research/ui.py:217 signal_check`. Il montre le σ par
voie, surligne les `key_channels` du mode visé, et **refuse de lancer** tant qu'une voie est plate
ou saturée. ⚠️ **Le verdict vient du moteur** (`core/lsl_io.py` porte déjà les verdicts de qualité) :
la console n'en calcule aucun.

**c. Le verdict.** L'écran « Après » de `calib_page.py` gagne **Refaire** et **Enregistrer**.

- [ ] **Étape 1 : écrire les tests dans `src/console/app.py::_smoke` (Qt offscreen)**

```python
    # Le lanceur : aucun VRAI processus dans le smoke. On injecte un faux QProcess et on vérifie
    # la commande demandée et le refus du doublon.
    page = console.show_mode("p300")
    faux = _FauxProcessus()
    page.lanceur._process = faux
    page.bouton_calibrer.click()
    chk(faux.argv[-1] == "--calibrer" and faux.argv[-2].endswith("p300.py"),
        f"« Calibrer » lance la fenêtre du P300 en mode calibration ({faux.argv[-2:]})")
    chk(faux.argv == commande("p300", calibrer=True),
        "…et la commande vient de stimulus/registry.py, pas d'une chaîne écrite dans la console")

    page.bouton_stimulus.click()
    chk(len(faux.lancements) == 1,
        "un second lancement est REFUSÉ tant que le premier vit — deux fenêtres publieraient les "
        "mêmes marqueurs sous le même nom")

    faux.mourir(code=1)
    console.apply_state(state)
    chk("fenêtre" in page.message.text().lower() and page.message.text(),
        f"une fenêtre qui meurt anormalement le DIT à l'écran ({page.message.text()})")

    # Le contrôle de liaison refuse, et il refuse VISIBLEMENT.
    mauvais = {**state, "quality": {"per_channel_sigma": [0.0] * 8, "verdict": "PLAT"}}
    console.apply_state(mauvais)
    page.bouton_calibrer.click()
    chk(not faux.lancements[1:],
        "contact mauvais : « Calibrer » ne lance rien")
    chk(page.message.text() and "contact" in page.message.text().lower(),
        f"…et l'écran dit pourquoi, en toutes lettres ({page.message.text()})")

    # Le verdict : deux boutons, deux commandes, aucune écriture.
    cal = console.show_calibration("p300")
    console.apply_state({**state, "calibration": {"phase": "fini", "candidat": {
        "nom": "p300_model_20260907-101500.joblib", "auc": 0.71,
        "verdict": "utilisable", "honnetete": "…"}}})
    chk(cal.bouton_enregistrer.isEnabled() and cal.bouton_refaire.isEnabled(),
        "une calibration finie propose Refaire ET Enregistrer")
    empreinte_avant = empreinte_dossier(DATA_DIR)
    cal.bouton_enregistrer.click()
    chk(("save_calibration", {}) in moteur_faux.commandes,
        "« Enregistrer » ENVOIE une commande au moteur")
    # Le moteur est FACTICE ici : il enregistre la commande et n'écrit rien. Donc si data/ a
    # changé, c'est la console qui a touché le disque — ce qu'un client ne fait jamais.
    chk(empreinte_dossier(DATA_DIR) == empreinte_avant,
        "…et data/ est inchangé : la console n'écrit pas, elle demande")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/console/app.py --smoke`.

- [ ] **Étape 3 : implémenter les trois morceaux**

⚠️ La phrase d'honnêteté cesse d'être la constante `HONNETETE` de `calib_page.py` : elle vient du
**résultat du moteur** (`candidat["honnetete"]`), parce qu'elle diffère par mode. Celle du MI (40 %
à trois classes, CV par essai) reste le texte du MI, déplacé dans `core/modes/mi_calib.py`.

- [ ] **Étape 4 : lancer les tests**

```bash
python src/console/app.py --smoke
python src/core/server.py --smoke
```

- [ ] **Étape 5 : vérifier à l'œil, une fois** — `python src/console/app.py --synthetic`, page P300 :
  cliquer « Lancer le stimulus », voir la fenêtre s'ouvrir, la fermer, voir la console le dire.
  C'est le seul point de ce plan qu'un smoke offscreen ne peut pas voir.

- [ ] **Étape 6 : commit**

```bash
git add src/console
git commit -m "Give the console a hand to launch with, and a verdict to sign"
```

---

## Task 7 : l'ErrP de bout en bout

**Files:**
- Create: `src/core/modes/errp_calib.py`
- Modify: `src/stimulus/errp.py` (mode `--calibrer`, fusion avec la piste de
  `research/errp_calibrate.py`), `src/core/modes/errp.py`, `src/research/errp_calibrate.py` (réduit)

**Interfaces:**
- Consumes: `MarkerCalibrationRuntime`, `core.errp_decoder.ErrPModel`.
- Produces: `ErrPCalibration` avec `runtime_cls_du_mode = ErrPRuntime` ; `_entrainer` rendant
  `{"modele", "nom", "n_essais", "auc", "perm_p", "tpr", "tnr", "verdict", "honnetete"}`.

⚠️ **L'ErrP n'utilise PAS `cue`.** Son étiquette est portée par son événement `feedback`, qui gagne
un champ `error: true|false` **pendant la calibration seulement** — l'événement existe déjà et
arrive au bon instant. En décodage, `feedback` reste tel quel : le moteur ne doit jamais apprendre
la vérité pendant qu'il décode.

`src/stimulus/errp.py` importe déjà `_decide_step`, `_new_goal`, `_run_block` de
`research/errp_calibrate.py` : cette tâche fait remonter ces trois helpers dans la fenêtre, qui est
leur vraie maison, et `research/errp_calibrate.py` se réduit à l'analyse hors ligne.

- [ ] **Étape 1 : écrire les tests**

```python
    # La vérité-terrain doit décrire ce qui s'est VRAIMENT passé à l'écran, pas ce que le tirage
    # avait décidé : c'est la même faute que d'horodater avant le flip, sur un autre axe.
    marqueurs, pas_joues = _rejouer_calibration_errp(essais=40, seed=3)
    feedbacks = [m for m, _ts in marqueurs if m["event"] == "feedback"]
    chk(all("error" in f for f in feedbacks),
        "en calibration, chaque `feedback` porte son étiquette")
    chk([f["error"] for f in feedbacks] == [p.eloigne_de_la_cible for p in pas_joues],
        "…et cette étiquette est celle du pas RÉELLEMENT affiché")
    taux = sum(f["error"] for f in feedbacks) / len(feedbacks)
    chk(0.15 < taux < 0.45, f"le taux d'erreurs délibérées reste dans sa plage ({taux:.2f})")

    # En DÉCODAGE, la vérité ne doit pas fuiter.
    marqueurs_dec, _ = _rejouer_decodage_errp(essais=10, seed=3)
    chk(all("error" not in m for m, _ts in marqueurs_dec if m["event"] == "feedback"),
        "hors calibration, `feedback` ne porte AUCUNE étiquette : le moteur ne doit pas connaître "
        "la réponse pendant qu'il décode")
```

Et dans `core/modes/errp_calib.py` :

```python
    res = _entrainer_sur_donnees_factices(n=120)
    chk(res["perm_p"] is not None and 0.0 <= res["perm_p"] <= 1.0,
        f"le test de permutation est calculé et rendu ({res['perm_p']})")
    chk("optimiste" in res["honnetete"].lower(),
        "la phrase d'honnêteté dit que le TPR/TNR affiché est OPTIMISTE — le seuil est choisi sur "
        "les scores qui le mesurent")
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

```bash
python src/core/modes/errp_calib.py
python src/stimulus/errp.py --smoke
```

- [ ] **Étape 3 : implémenter** — même découpe qu'à la tâche 4.

- [ ] **Étape 4 : lancer les tests**

```bash
python src/core/modes/errp_calib.py
python src/core/modes/errp.py
python src/core/errp_models.py
python src/stimulus/errp.py --smoke
python src/core/server.py --smoke
```

- [ ] **Étape 5 : commit**

```bash
git add src/core/modes/errp_calib.py src/core/modes/errp.py src/stimulus/errp.py src/research/errp_calibrate.py
git commit -m "Let the engine train the ErrP, and keep the answer out of decoding"
```

---

## Task 8 : le c-VEP de bout en bout

**Files:**
- Create: `src/core/modes/cvep_calib.py`
- Modify: `src/stimulus/cvep.py` (mode `--calibrer`), `src/core/modes/cvep.py`,
  `src/research/cvep_calibrate.py` (réduit)

**Interfaces:**
- Consumes: `MarkerCalibrationRuntime`, `core.cvep_decoder.CVEPModel`,
  `core.cvep_rcca.RCCAModel`, `core.modes.cvep.CVEPRuntime.phase_a`.
- Produces: `CVEPCalibration` avec `runtime_cls_du_mode = CVEPRuntime` ; `_entrainer` rendant
  `{"modele", "modele_rcca", "nom", "n_essais", "acc_ecca", "acc_rcca", "mcnemar_p", "verdict",
  "honnetete"}` et écrivant **deux** fichiers.

⚠️ **Le c-VEP est le seul des trois dont l'époque n'est PAS découpée par `epoch_from_stream`.** Il
décode en continu sur une fenêtre glissante, alignée par la PHASE. Le chemin partagé entre
entraînement et décodage est donc `CVEPRuntime.phase_a` — la reconstruction de la phase depuis le
marqueur `cycle` —, pas la découpe autour d'un événement. `CVEPCalibration` doit l'appeler, pas la
réimplémenter. C'est le même invariant que la tâche 3, sur l'autre axe.

⚠️ **Le stimulus continue de publier `cycle` pendant la calibration** : sans l'horloge, il n'y a pas
de phase, donc pas d'époque alignée. `cue` s'ajoute, il ne remplace rien.

- [ ] **Étape 1 : écrire les tests**

```python
    # L'invariant, sur l'axe de la phase : la calibration ne recalcule pas la phase, elle la LIT.
    # Vérifié PAR LES VALEURS, pas par l'identité des fonctions : une réimplémentation qui donne
    # aujourd'hui les mêmes nombres dérivera demain, et c'est la dérive qu'on interdit. Même
    # référence de cycle, mêmes instants, mêmes phases attendues — sur une course qui inclut une
    # frame sautée, le cas où deux implémentations divergent.
    refresh, L, t_ref = 60.0, 63, 5000.0
    decodeur = _runtime_cvep_de_test(code_len=L, refresh=refresh)
    calib = _calibration_cvep_de_test(code_len=L, refresh=refresh)
    for rt in (decodeur, calib):
        rt.maj_reference(ts=t_ref, refresh=refresh)
    instants = [t_ref + i / refresh for i in range(L * 4)] + [t_ref + 2.7183, t_ref + 3.1416]
    ecarts = [i for i, t in enumerate(instants) if calib.phase_de(t) != decodeur.phase_a(t)]
    chk(not ecarts,
        f"la calibration et le décodage reconstruisent la MÊME phase à chaque instant "
        f"({len(ecarts)} désaccord(s) sur {len(instants)} instants)")
    chk(decodeur.phase_a(instants[0]) is not None,
        "…et cette phase est bien définie : un test où les deux rendent None partout serait vert "
        "pour rien")

    # Les deux décodeurs sont entraînés sur les MÊMES époques, et le gagnant est nommé par McNemar.
    res = _entrainer_sur_donnees_factices(n_blocs=6)
    chk(res["modele"] and res["modele_rcca"], "deux fichiers candidats sont produits")
    chk(res["mcnemar_p"] is not None,
        f"McNemar exact est calculé ({res['mcnemar_p']}) — « indiscernables » est la réponse "
        f"attendue, et deux pourcentages bruts ne suffisent pas à nommer un gagnant")
    chk("indiscernable" in res["verdict"].lower() or "p =" in res["verdict"],
        f"le verdict rend le test, pas seulement l'écart ({res['verdict']})")
```

Dans `src/stimulus/cvep.py --smoke`, **conserver telle quelle** l'assertion de phase lue dans les
pixels (zéro frame d'écart) et lui ajouter :

```python
    marqueurs, cibles = _rejouer_calibration_cvep(blocs=4, seed=11)
    cues = [m for m, _ts in marqueurs if m["event"] == "cue"]
    cycles = [m for m, _ts in marqueurs if m["event"] == "cycle"]
    chk(len(cues) == 4 and [c["target"] for c in cues] == cibles,
        "un `cue` par bloc, portant la cible réellement cerclée")
    chk(cycles,
        "l'horloge continue de battre PENDANT la calibration : sans elle il n'y a pas de phase, "
        "donc pas d'époque alignée — le c-VEP ne décoderait pas mal, il ne décoderait RIEN")
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

```bash
python src/core/modes/cvep_calib.py
python src/stimulus/cvep.py --smoke
```

- [ ] **Étape 3 : implémenter** — le corps de `entraine_les_deux(epochs, labels, …)` de
  `research/cvep_calibrate.py:170` monte tel quel ; il ne touche ni pygame ni le casque.

- [ ] **Étape 4 : lancer les tests**

```bash
python src/core/modes/cvep_calib.py
python src/core/modes/cvep.py
python src/core/cvep_models.py
python src/core/cvep_rcca.py
python src/stimulus/cvep.py --smoke
python src/core/server.py --smoke
```

- [ ] **Étape 5 : commit**

```bash
git add src/core/modes/cvep_calib.py src/core/modes/cvep.py src/stimulus/cvep.py src/research/cvep_calibrate.py
git commit -m "Let the engine train the c-VEP off the same clock it decodes with"
```

---

## Task 9 : l'histogramme neuro dans la console

**Files:**
- Create: `src/console/neuro_view.py`
- Modify: `src/console/mode_page.py`

**Interfaces:**
- Consumes: `snapshot()["modes_state"]["neuro"]["indices"]` — les trois indices publiés par le mode.
- Produces: `HistogrammeNeuro(QWidget)` avec `.maj(indices: dict)`.

Le seul écran pygame sans doublon exact. Sans lui, « seul point d'entrée » serait faux pour un mode
sur six. **Le calcul ne bouge pas** (`NeuroDecoder`, déjà dans `core`) : c'est un ajout de rendu.

- [ ] **Étape 1 : écrire le test**

```python
    vue = HistogrammeNeuro()
    vue.maj({"charge": 1.2, "somnolence": -0.4, "engagement": 0.0})
    chk(vue.barres["charge"].value() > vue.barres["somnolence"].value(),
        "une valeur plus haute donne une barre plus haute")
    chk(vue.barres["engagement"].value() == vue.zero,
        "un indice à 0 se lit comme le ZÉRO du jour, pas comme le bas de l'échelle : l'échelle "
        "est un z contre le repos de CETTE personne et elle est SIGNÉE")
    vue.maj({"charge": 99.0, "somnolence": -99.0, "engagement": 0.0})
    chk(all(0 <= b.value() <= b.maximum() for b in vue.barres.values()),
        "une valeur aberrante est bornée à l'échelle au lieu de casser le rendu")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/console/app.py --smoke`.

- [ ] **Étape 3 : implémenter.**

- [ ] **Étape 4 : lancer les tests** — `python src/console/app.py --smoke`.

- [ ] **Étape 5 : commit**

```bash
git add src/console
git commit -m "Bring the neuro histogram where the rest of the product lives"
```

---

## Task 10 : les retraits, dans l'ordre qui ne casse pas l'archive

**Files:**
- Create: `archive/ssvep_pilot.py`, `archive/p300_pilot.py`, `archive/errp_demo.py`
- Modify: `src/research/ui.py` (accueille `Live`, `_live_loop`, `_running`, `_vote`),
  `archive/cvep_pilot.py`, `archive/cvep_rcca_pilot.py` (imports suivis), `archive/README.md`
- Delete: `src/research/app.py` — **en dernier**

⚠️ **L'ordre compte, et il n'est pas négociable.** `archive/cvep_pilot.py:34` et
`archive/cvep_rcca_pilot.py:37` importent `Live, _live_loop, _running, _vote` de
`src/research/app.py`, et `archive/README.md` promet que ces fichiers tournent encore. Donc :
**d'abord** la machinerie déménage dans `research/ui.py` (qui porte déjà `App` et `Abort`) et les
imports de l'archive suivent ; **ensuite seulement** le fichier vidé est supprimé.

- [ ] **Étape 1 : déménager la machinerie, archive d'abord**

Déplacer `Live`, `_live_loop`, `_running`, `_vote` vers `src/research/ui.py`, corriger les deux
imports de l'archive, lancer les quatre smokes existants :

```bash
python archive/mi_calibrate.py --smoke
python archive/mi_pilot.py --smoke
python archive/cvep_pilot.py --smoke
python archive/cvep_rcca_pilot.py --smoke
```

Les quatre doivent être verts **avant** de toucher à quoi que ce soit d'autre.

- [ ] **Étape 2 : archiver les trois écrans de pilotage**

`mode_ssvep` (`research/app.py:383`) → `archive/ssvep_pilot.py` ; la sélection P300 (`:529`) →
`archive/p300_pilot.py` ; le démonstrateur ErrP (`:885`) → `archive/errp_demo.py`. Chacun devient
autonome, garde son `--smoke`, et — comme `cvep_pilot.py` — expose un `--model` explicite là où il
en charge un.

⚠️ **Ils ne sont pas supprimés.** Ils restent la référence de décodage **local** contre laquelle la
recette 2.9 compare le décodage réseau : c'est ce qui sépare « le réseau est moins bon » de « la
séance est moins bonne ».

- [ ] **Étape 3 : supprimer `src/research/app.py`**

Une fois vidé — un menu sans page. Vérifier qu'aucun fichier du dépôt ne l'importe encore :

```bash
grep -rn "research.app\|research/app" src/ archive/ docs/ examples/ *.md
```

Attendu : plus aucune occurrence de code (les mentions dans la doc sont traitées à la tâche 11).

- [ ] **Étape 4 : `archive/README.md`**

Trois lignes pour les nouveaux arrivants, et ⚠️ **corriger la ligne de `cvep_pilot.py`**, qui dit
aujourd'hui *« Calibration is unaffected: it still lives at `src/research/app.py`, page "c-VEP" »* —
c'est faux après ce chantier.

- [ ] **Étape 5 : lancer les tests**

```bash
python archive/mi_calibrate.py --smoke
python archive/mi_pilot.py --smoke
python archive/cvep_pilot.py --smoke
python archive/cvep_rcca_pilot.py --smoke
python archive/ssvep_pilot.py --smoke
python archive/p300_pilot.py --smoke
python archive/errp_demo.py --smoke
python src/core/server.py --smoke
python src/console/app.py --smoke
```

- [ ] **Étape 6 : commit**

```bash
git add -A src/research archive
git commit -m "Retire the piloting screens to where they stay checkable"
```

---

## Task 11 : le raccourci et la documentation

**Files:**
- Create: `outils/Console EEG.bat`
- Modify: `CLAUDE.md`, `README.md`, `docs/markers.md`, `docs/recette.md`, `docs/SPEC.md`

**Interfaces:** aucune — c'est la tâche qui rend le chantier lisible par quelqu'un qui arrive.

- [ ] **Étape 1 : le raccourci**

```bat
@echo off
rem La derniere ligne de commande du parcours utilisateur, et elle est ecrite une fois pour toutes.
cd /d "%~dp0.."
python src\console\app.py %*
if errorlevel 1 pause
```

`if errorlevel 1 pause` : sans lui, une console qui meurt au démarrage ferme sa fenêtre avant que le
message ne soit lisible — le clic silencieux, encore une fois.

- [ ] **Étape 2 : `docs/markers.md`** — **en anglais**, c'est le contrat public. Ajouter une section
  « Training a model through the markers » : les trois événements, leur charge utile, le fait que
  l'ErrP passe par `feedback` plutôt que `cue`, et la conséquence — **toute application capable
  d'afficher le stimulus peut désormais entraîner un modèle**.

- [ ] **Étape 3 : `CLAUDE.md`** — la règle des trois paquets devient quatre. Les commandes utiles
  changent : plus de `src/research/app.py`, plus de `src/research/*_stimulus.py`, et les
  calibrations ne sont plus des lignes de commande mais des boutons. La liste des autotests gagne
  `marker_calib.py`, les trois `*_calib.py` et les trois `stimulus/*.py --smoke`.

- [ ] **Étape 4 : `docs/recette.md`** — les tests 1.14, 1.15, 1.16, 2.6, 2.7, 2.8 et 2.9 décrivent
  des montages à deux ou trois terminaux qui deviennent des clics. Les réécrire. ⚠️ **Ne pas
  toucher aux repères chiffrés** (100 %/44 % pour le SSVEP, 46 %/71 % pour le c-VEP, une erreur sur
  deux pour l'ErrP, ~40 % à trois classes pour le MI) : ce chantier ne mesure rien.

- [ ] **Étape 5 : `README.md`** (anglais) et `docs/SPEC.md` (français) — le point d'entrée unique,
  et le quatrième paquet.

- [ ] **Étape 6 : relire la doc comme du code**

⚠️ Mesuré sur un chantier précédent : **0 régression dans 2000 lignes de code relu, 1 régression et
8 faussetés dans la doc écrite sans relecteur.** Faire relire cette tâche par un œil neuf, avec
pour consigne de vérifier chaque commande citée et chaque chiffre.

- [ ] **Étape 7 : lancer TOUS les tests**

```bash
python src/core/server.py --smoke
python src/console/app.py --smoke
python src/core/modes/marker_calib.py
python src/core/modes/p300_calib.py
python src/core/modes/errp_calib.py
python src/core/modes/cvep_calib.py
python src/core/modes/mi_calib.py
python src/core/modes/calibration.py
python src/core/modes/contract.py
python src/core/modes/registry.py
python src/stimulus/p300.py --smoke
python src/stimulus/errp.py --smoke
python src/stimulus/cvep.py --smoke
python archive/cvep_pilot.py --smoke
```

- [ ] **Étape 8 : commit**

```bash
git add -A
git commit -m "Document the single way in, and retire the commands it replaces"
```

---

## Le chantier est fini à la tâche 11

Ce qui reste **dehors**, et qui suit : **la séance casque**. Tous les modèles y seront réentraînés
depuis l'interface — la calibration fait partie de ce qui est éprouvé. Restent aussi dehors le lot
d'affichage parké depuis le 2026-08-17 (tracés du brut qui se chevauchent, aide grise tronquée) et
toute nouvelle capacité de décodage.
