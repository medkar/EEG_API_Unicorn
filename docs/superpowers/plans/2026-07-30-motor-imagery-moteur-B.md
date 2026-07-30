# Motor Imagery dans le moteur — moitié B : la calibration — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** le moteur JOUE la calibration Motor Imagery et entraîne le modèle lui-même ; la console
la rend et la pilote ; l'accuracy affichée devient honnête ; rien n'est jamais écrasé ; l'écran
pygame part en `archive/`.

**Architecture :** une calibration est une activité du MOTEUR, tenue dans un emplacement propre
(`EngineServer.calibration`) à côté des modes actifs, pas à l'intérieur d'un `ModeRuntime`. Elle
est décrite par le contrat (`Calib` gagne ses `params` et sa `runtime_cls`), pilotée par deux
commandes (`start_calibration`, `cancel_calibration`), et son état complet sort dans
`snapshot()["calibration"]`. La console rend cet état et n'en décide rien.

**Tech Stack :** Python 3, numpy, scikit-learn (`StratifiedGroupKFold`, vérifié présent en 1.9.0),
joblib, PySide6 6.11.1 (`QtMultimedia`/`QAudioSink` vérifié présent), BrainFlow, pylsl.

**Spec de référence :** [`docs/superpowers/specs/2026-07-29-motor-imagery-moteur-design.md`](../specs/2026-07-29-motor-imagery-moteur-design.md),
sections §6 (la calibration), §7 (la console), §8 (les deux défauts corrigés), §9 (l'archivage),
§11 (tests), §14 (les valeurs exactes).

**Moitié A :** [`2026-07-29-motor-imagery-moteur-A.md`](2026-07-29-motor-imagery-moteur-A.md),
section « Bilan du chantier » — la liste parkée que ce plan reprend.

---

## Global Constraints

Ces contraintes s'appliquent à **toutes** les tâches. Elles ne sont pas rappelées tâche par tâche.

- **`src/core/` n'importe JAMAIS `src/research/` ni `src/console/`**, et ne contient ni pygame ni
  Qt : le moteur tourne sans écran. Vérifié par `python src/core/server.py --smoke`, qui scanne
  `src/core/**/*.py` et échoue sur le moindre import interdit.
- **La console est un CLIENT du moteur.** Aucune logique dans l'interface que le moteur ne possède
  déjà : pas de validation côté Qt, pas de catalogue recopié, pas de règle de décision réécrite.
  Tout geste passe par `engine.submit(...)`, qui met en file ; le fil Qt ne touche jamais la
  session BrainFlow.
- **Code, commentaires et docstrings en FRANÇAIS. Messages de commit en ANGLAIS.**
- **Tout doit être testable sans casque** (`--synthetic`, `--smoke`). Aucune tâche de ce plan
  n'exige de matériel.
- **Les constantes de protocole ne bougent pas** : `MI_LABELS`, `MI_BAND`, `MI_WINDOW_S`,
  `MI_PROB_MIN`, `MI_VOTE_LEN`, `MI_MIN_VOTES`, `MI_REREF`, `MI_METHOD`, `CUE_S`, `IMAGERY_S`,
  `REST_S`, `WARMUP_PER_CLASS`, les quatre durées de séance (10 · 14 · 18 · 26). Valeurs exactes
  en spec §14.
- **`data/` reste hors de git.** Ce sont des enregistrements EEG d'une personne identifiable sur un
  dépôt PUBLIC. Aucun test n'écrit dans le vrai `data/` : les tests écrivent dans un dossier
  temporaire et le nettoient dans un `finally`.
- **Rien n'est jamais écrasé** : modèles et enregistrements sont horodatés (spec §8).
- **Un seul programme à la fois** — console, moteur, appli pygame. Ne jamais lancer deux tests qui
  ouvrent une session BrainFlow en parallèle : les noms de flux sont un contrat public, identique
  pour toutes les instances.
- **Après toute modification**, les tests qui doivent rester verts (à lancer EN SÉRIE) :

  ```bash
  python src/core/modes/contract.py     # le contrat
  python src/core/mi_decoder.py         # CSP+LDA sur ERD synthétique
  python src/core/mi_models.py          # refus des modèles hérités, tri par date
  python src/core/modes/mi.py           # seuil, vote, appariement p_<classe>
  python src/core/acquisition.py --synthetic   # fenêtre MI NON filtrée
  python src/core/server.py --smoke     # le moteur de bout en bout
  python src/console/app.py --smoke     # la console (Qt offscreen)
  python src/research/app.py --smoke    # l'appli pygame
  ```

---

## Trois décisions prises en écrivant ce plan

La spec a été écrite avant d'ouvrir le code de la moitié A. Trois points s'y révèlent, et chacun
change ce qu'il faut construire. Ils sont tranchés ici, une fois, plutôt que découverts par un
implémenteur au milieu d'une tâche.

### 1. La calibration ne peut PAS être une phase du mode MI

La spec §6 dit « le mode gagne une phase publique `calibrating` ». C'est impossible : le mode MI
**refuse de démarrer sans modèle** — c'est son invariant, écrit dans `core/modes/mi.py` et vérifié
par son autotest. Un étudiant qui n'a aucun modèle ne pourrait donc jamais atteindre la
calibration qui lui en donnerait un. Œuf et poule.

→ **La calibration est une activité du MOTEUR**, tenue dans `EngineServer.calibration`,
indépendante de `self.active`. Elle se lance sur un mode ARRÊTÉ comme sur un mode qui tourne. La
phase globale publiée devient bien `calibrating` (le contrat public de la spec est tenu), mais
c'est le moteur qui la porte, pas un `ModeRuntime`.

### 2. Le tampon glissant du moteur est trop COURT pour une époque de calibration

`EngineServer.keep` est dimensionné sur le plus gourmand des décodeurs — `MI_WINDOW_S` = 2 s. Or
une calibration enregistre des époques de `IMAGERY_S` = **4 s**. Sans correctif, chaque époque
serait **silencieusement tronquée à 2 s** : `MIModel.fit` fonctionnerait quand même (il découpe en
fenêtres glissantes), produirait **1 fenêtre par essai au lieu de 3**, et rien ne le dirait. Le
modèle serait entraîné sur trois fois moins de données que l'écran ne l'annonce.

→ `Calib` déclare `epoch_s`, et `EngineServer.keep` l'intègre à son `max(...)`. Un test épingle la
longueur réelle des époques enregistrées.

### 3. Sans « Démarrer » dans la console, la calibration ne sert à rien — et abîme le signal

La console ne sait pas démarrer un mode : `--mode` au lancement, point. Après une calibration,
l'étudiant devrait donc **fermer la console et la relancer** avec `--mode mi`. Or CLAUDE.md :
« Ne pas fermer/rouvrir l'appli en cours de séance : les voies **C3/Cz saturent** à la réouverture
(redémarrage de l'amplificateur) ». C3 et Cz sont exactement les voies que lit le Motor Imagery
(`MI_KEY_CHANNELS = [1, 2, 3]`).

Le parcours « je calibre puis je décode » passerait donc obligatoirement par le geste qui dégrade
les voies du mode qu'on vient de calibrer. Ce n'est pas un confort manquant, c'est un défaut.

→ **Tâche 5** ajoute Démarrer / Arrêter à la grille. Le moteur possède déjà les commandes
(`start_mode`, `stop_mode`) : c'est uniquement du câblage côté console.

---

## Structure des fichiers

**Créés :**

| Fichier | Responsabilité |
|---|---|
| `src/core/modes/calibration.py` | `CalibrationRuntime` : la machine de phases générique d'une calibration. Ne sait rien du MI. |
| `src/core/modes/mi_calib.py` | `MICalibration` : le protocole MI (consignes, classes, découpage, entraînement, sauvegarde). |
| `src/console/calib_page.py` | La page de calibration : briefing, déroulé, résultat. Rend `snapshot()["calibration"]`. |
| `src/console/beeps.py` | Les bips latéralisés via `QtMultimedia`. Silencieux et honnête si l'audio manque. |
| `archive/README.md` | Ce que contient l'archive et ce qu'elle ne garantit pas. |

**Modifiés :**

| Fichier | Ce qui change |
|---|---|
| `src/core/config.py` | Les constantes du protocole de calibration MI (`MI_CUE_S`, `MI_IMAGERY_S`, `MI_REST_S`, `MI_WARMUP_PER_CLASS`, `MI_SESSIONS`). |
| `src/core/modes/contract.py` | `Calib` gagne `label`, `params`, `epoch_s`, `runtime_cls`, `briefing`, `defaults()`. |
| `src/core/mi_decoder.py` | `MIModel.fit(epochs, y, groups=None)` : CV honnête `cv_groupee_`, `n_essais_`. |
| `src/core/mi_models.py` | `charger(None)` ne lève plus. |
| `src/core/modes/mi.py` | `MIRuntime.state()` surchargé (plus de lecture disque par état) ; `Calib` renseigné ; aide du réglage `model` corrigée. |
| `src/core/modes/registry.py` | `serialize` expose le contrat de calibration en entier. |
| `src/core/server.py` | L'emplacement `calibration`, les deux commandes, le tick, `keep`, la phase publique, `_smoke_calibration`. |
| `src/console/app.py` | La page de calibration dans la pile ; le smoke. |
| `src/console/grid.py` | Démarrer / Arrêter sur la tuile. |
| `src/console/mode_page.py` | Le bouton « Calibrer » ; rafraîchir la liste des modèles. |
| `src/console/params_form.py` | `set_choices()` : recharger une liste de choix sans reconstruire le formulaire. |
| `src/research/app.py` | Le menu passe de 6 à 5 modes ; plus aucun import de `mi_pilot`/`mi_calibrate`. |
| `CLAUDE.md`, `README.md`, `docs/recette.md`, `docs/SPEC.md` | Le MI n'est plus dans l'appli pygame ; la calibration se lance depuis la console. |

**Déplacés (tâche 7, à la FIN) :** `src/research/mi_calibrate.py` → `archive/mi_calibrate.py` ·
`src/research/mi_pilot.py` → `archive/mi_pilot.py`.

**Conservé sur place :** `src/research/mi_compare.py` — outil d'analyse que rien ne remplace. Il
importe déjà `core.mi_decoder` (fait en moitié A) : rien à faire.

---

## Ordre des tâches et dépendances

```
T1 (contrat + CV honnête)  ──┬──> T3 (CalibrationRuntime + MI) ──> T4 (le moteur) ──┬──> T6 (page de calibration)
T2 (constats parkés)  ───────┘                                                       │
T5 (démarrer/arrêter) ───────────────────────────────────────────────────────────────┘
                                                                                     └──> T7 (archivage + doc)
```

T1 et T2 sont indépendantes l'une de l'autre. T5 est indépendante de tout le reste et peut être
faite à tout moment avant T6. T7 est la DERNIÈRE : tant que la console ne sait pas calibrer,
l'écran pygame est le seul moyen de produire un modèle (spec §9).

---

### Task 1: Le contrat de calibration et l'accuracy honnête

**Files:**
- Modify: `src/core/modes/contract.py` (la dataclass `Calib`, l'autotest)
- Modify: `src/core/mi_decoder.py` (`MIModel.fit`, l'autotest)
- Modify: `src/core/modes/registry.py` (`serialize`)
- Modify: `src/core/config.py` (les constantes du protocole)

**Interfaces:**
- **Produit** — `Calib(kind, reason="", label="", briefing=(), params=(), epoch_s=0.0,
  runtime_cls=None)` ; `Calib.defaults() -> dict` ; `MIModel.fit(epochs, y, groups=None)` qui pose
  `self.cv_` (naïve), `self.cv_groupee_` (honnête, ou None) et `self.n_essais_` (ou None) ;
  `registry.serialize(spec)["calibration"]` porte désormais `label`, `briefing`, `params`,
  `epoch_s`.
- **Consomme** — `contract.validate(spec, params)` tel quel : il ne lit que `.label`, `.params` et
  `.defaults()` de son premier argument, donc il marche sur un `Calib` sans une ligne de plus.
  **Ne pas écrire un second validateur.**

**Contexte :** `mi_models.decrire()` lit DÉJÀ `cv_groupee_` et `n_essais_` sur le modèle (écrit en
moitié A, en prévision de celle-ci) et rend `None` quand ils sont absents. Cette tâche les fait
enfin exister. Ne pas modifier `decrire`.

- [ ] **Step 1: Les constantes du protocole, dans `core/config.py`**

À placer juste après `MI_KEY_CHANNELS` (ligne ~259), dans le bloc MI :

```python
# --- Calibration Motor Imagery : le protocole, tel qu'il a été validé au casque ---------------
# CUE = mise en route NON enregistrée après le top (le temps d'établir l'imagerie), puis on garde
# les IMAGERY secondes suivantes. 2026-07-22 : le CUE est passé de 2 à 3 s — il faut « environ
# 2 s » pour bien lancer le poing, et 2 s ne laissaient aucune marge (le début de l'enregistrement
# attrapait la fin de la montée). IMAGERY reste à 4 s : allonger n'aiderait pas, le facteur
# limitant MESURÉ est la FATIGUE, pas la durée par essai (le 3 classes tombe de 57 % à 33 % en
# deuxième moitié de séance).
MI_CUE_S = 3.0             # mise en route, jetée
MI_IMAGERY_S = 4.0         # la partie ENREGISTRÉE d'un essai
MI_REST_S = 1.5            # pause entre deux essais
MI_WARMUP_PER_CLASS = 2    # essais d'échauffement NON enregistrés (le MI s'améliore en séance)
MI_TRAIN_STEP_S = 1.0      # pas du découpage en fenêtres -> 3 fenêtres par essai de 4 s
# Durées de séance proposées, en essais PAR CLASSE. Le temps estimé se calcule, il ne se stocke
# pas : il dépend de CUE + IMAGERY + REST, qui sont juste au-dessus.
MI_SESSIONS = (10, 14, 18, 26)
```

- [ ] **Step 2: Écrire le test du contrat AVANT de toucher `Calib`**

Dans `_selftest()` de `src/core/modes/contract.py`, à la fin, juste avant le `print` du verdict :

```python
    # --- le contrat d'une CALIBRATION ---------------------------------------------
    # `Calib` réutilise `validate` : elle expose `.label`, `.params` et `.defaults()`, exactement
    # ce que le validateur lit. Un second validateur pour les calibrations serait une deuxième
    # vérité, avec ses propres messages de refus — le défaut que ce module existe pour éliminer.
    calib = Calib(
        kind="console", label="Calibration d'essai",
        briefing=("Première ligne.", "Deuxième ligne."),
        epoch_s=4.0,
        params=(Param("trials_per_class", "Essais par classe", "int", default=14,
                      min=2, max=40, help="Plus d'essais = plus long, pas forcément mieux."),),
    )
    chk(calib.defaults() == {"trials_per_class": 14},
        f"une calibration a des défauts comme un mode ({calib.defaults()})")
    values, raison = validate(calib, {})
    chk(values == {"trials_per_class": 14} and raison is None,
        f"et le MÊME validateur les accepte ({values}, {raison})")
    values, raison = validate(calib, {"trials_per_class": 999})
    chk(values is None and raison and "maximum" in raison,
        f"les bornes s'appliquent, avec la même formulation de refus ({raison})")
    values, raison = validate(calib, {"duree": "longue"})
    chk(values is None and raison and "réglage inconnu" in raison,
        f"et un réglage inconnu est refusé pareil ({raison})")

    vide = Calib(kind="natif", reason="stimulus verrouillé à la frame")
    chk(vide.defaults() == {} and vide.runtime_cls is None and vide.epoch_s == 0.0,
        "une calibration NATIVE ne déclare ni réglage, ni runtime, ni époque")
```

- [ ] **Step 3: Lancer le test — il doit ÉCHOUER**

Run: `python src/core/modes/contract.py`
Expected: `TypeError: Calib.__init__() got an unexpected keyword argument 'label'`

- [ ] **Step 4: Étendre `Calib`**

Remplacer la dataclass `Calib` de `src/core/modes/contract.py` (lignes 115-120) par :

```python
@dataclass(frozen=True)
class Calib:
    """Comment ce mode s'entraîne : par qui, avec quels réglages, et pour quel coût en signal.

    Deux valeurs de `kind`, et elles ne décrivent pas une préférence mais une CONTRAINTE :
      - "console" — les consignes sont du texte et un décompte, rendus par la console. Le moteur
        joue le protocole et enregistre. C'est le cas du Motor Imagery : il est ENDOGÈNE, donc il
        n'a aucun stimulus à afficher à la milliseconde près.
      - "natif" — le protocole a besoin d'un stimulus verrouillé à la frame (c-VEP, P300), qui ne
        peut pas être rendu par une interface Qt. `reason` dit pourquoi, et la calibration reste
        dans l'appli pygame.

    ⚠️ `epoch_s` n'est pas décoratif : c'est la plus longue tranche que cette calibration
    prélèvera dans le tampon glissant du moteur. `EngineServer` dimensionne son tampon dessus. La
    déclarer trop courte tronquerait chaque époque enregistrée SANS erreur — l'entraînement
    porterait sur trois fois moins de données que l'écran n'en annonce.
    """

    kind: str              # "console" | "natif"
    reason: str = ""       # pourquoi "natif" — une contrainte PHYSIQUE, pas un goût
    label: str = ""        # "Calibration Motor Imagery" — le titre de la page
    briefing: tuple = ()   # les consignes à lire AVANT de commencer, une ligne par élément
    params: tuple = ()     # les `Param` de la calibration (durée de séance…)
    epoch_s: float = 0.0   # la plus longue tranche prélevée dans le tampon du moteur
    runtime_cls: object = None   # la classe `CalibrationRuntime`, ou None si "natif"

    def defaults(self):
        """Les réglages par défaut de cette calibration, résolus maintenant.

        Même corps que `ModeSpec.defaults` — et c'est ce qui permet à `validate` de traiter les
        deux sans distinction.
        """
        return {p.key: p.default_now() for p in self.params}
```

- [ ] **Step 5: Le test passe**

Run: `python src/core/modes/contract.py`
Expected: `[contract] VERDICT : OK`

- [ ] **Step 6: Écrire le test de la CV honnête AVANT de toucher `MIModel`**

Le `__main__` de `src/core/mi_decoder.py` appelle `_demo()`, qui ne rend pas de verdict binaire
utilisable. Ajouter une fonction `_test_cv_honnete()` et l'appeler dans `__main__` **avant**
`_demo()`, en cumulant les deux verdicts.

À insérer juste avant `def _demo():` :

```python
def _test_cv_honnete():
    """L'invariant de la CV groupée : elle doit être INFÉRIEURE à la naïve, toujours.

    Pourquoi c'est un invariant et pas une observation : la CV naïve mélange entre plis des
    fenêtres GLISSANTES issues du même essai. Deux fenêtres d'un même essai partagent une seconde
    de signal sur deux et la même étiquette — le classifieur retrouve donc en test un morceau
    exact de ce qu'il a vu en apprentissage. Le score obtenu ne dit plus rien de sa capacité à
    généraliser à un NOUVEL essai, qui est pourtant la seule question qui compte pour un étudiant.

    Mesuré sur les 30 essais archivés du projet : 55,6 % naïve contre 40,0 % honnête à 3 classes,
    73,3 % contre 63,3 % à 2 classes. L'écart est de 10 à 16 points, et c'est CE chiffre-là qui
    était affiché à la fin d'une séance de calibration.

    Le test ne vérifie PAS une valeur : il vérifie le SENS de l'écart, qui ne dépend d'aucun jeu
    de données. Une valeur attendue serait fausse dès qu'on change la graine.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    rng = np.random.default_rng(0)
    fs, n_essais_par_classe = 250.0, 8
    n_fen = int(round(2.0 * fs))          # MI_WINDOW_S
    pas = int(round(1.0 * fs))            # MI_TRAIN_STEP_S -> 3 fenêtres par essai de 4 s
    X, y, groupes = [], [], []
    essai = 0
    for label in MI_LABELS:
        for _ in range(n_essais_par_classe):
            # Une époque de 4 s, comme en produira la calibration : (n_ch, 4*fs).
            epoque = synth_mi_trial(label, n_samp=int(4.0 * fs), fs=fs, rng=rng)
            for debut in range(0, epoque.shape[1] - n_fen + 1, pas):
                X.append(epoque[:, debut:debut + n_fen])
                y.append(label)
                groupes.append(essai)
            essai += 1
    X, y, groupes = np.asarray(X), np.asarray(y), np.asarray(groupes)
    chk(len(X) == essai * 3, f"3 fenêtres par essai de 4 s ({len(X)} pour {essai} essais)")

    modele = MIModel(fs=fs, reref_mode="none").fit(X, y, groups=groupes)
    chk(modele.cv_ is not None and modele.cv_groupee_ is not None,
        f"les deux CV sont calculées (naïve={modele.cv_}, groupée={modele.cv_groupee_})")
    chk(modele.n_essais_ == essai,
        f"le nombre d'ESSAIS est retenu, pas celui des fenêtres ({modele.n_essais_})")
    chk(modele.cv_groupee_ < modele.cv_,
        f"la CV groupée est INFÉRIEURE à la naïve : {modele.cv_groupee_*100:.1f}% contre "
        f"{modele.cv_*100:.1f}% — la fuite entre fenêtres d'un même essai vaut "
        f"{(modele.cv_ - modele.cv_groupee_)*100:.1f} points")

    # Sans `groups`, la CV honnête n'est pas INVENTÉE : elle reste absente. Recopier la naïve
    # ferait passer un chiffre gonflé pour un chiffre honnête — exactement le défaut corrigé.
    sans = MIModel(fs=fs, reref_mode="none").fit(X, y)
    chk(sans.cv_ is not None and sans.cv_groupee_ is None and sans.n_essais_ is None,
        f"sans `groups`, la CV honnête reste absente au lieu d'être inventée "
        f"({sans.cv_groupee_}, {sans.n_essais_})")

    print(f"[mi-cv] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok
```

Et remplacer le bloc `__main__` (lignes 273-275) par :

```python
if __name__ == "__main__":
    use_utf8_console()
    ok_cv = _test_cv_honnete()
    ok_demo = _demo()
    sys.exit(0 if (ok_cv and ok_demo) else 1)
```

⚠️ `_demo()` rend déjà un booléen mais son résultat était jeté : le fichier sortait toujours en 0.
Le brancher sur le code de sortie est un correctif, pas un effet de bord — c'est ce qui fait de ce
fichier un vrai garde.

- [ ] **Step 7: Lancer — il doit ÉCHOUER**

Run: `python src/core/mi_decoder.py`
Expected: `TypeError: MIModel.fit() got an unexpected keyword argument 'groups'`

- [ ] **Step 8: La CV honnête dans `MIModel`**

Ajouter l'import en tête de `src/core/mi_decoder.py` (ligne 31, à côté de `cross_val_score`) :

```python
from sklearn.model_selection import (StratifiedGroupKFold, cross_val_score,  # noqa: E402
                                     train_test_split)
```

Dans `MIModel.__init__`, après `self.cv_ = None` :

```python
        # La CV HONNÊTE (par essai) et le nombre d'essais. `None` tant qu'on n'a pas dit à `fit`
        # à quel essai appartient chaque fenêtre — voir `fit`. `mi_models.decrire()` les lit et
        # les affiche absents plutôt que de recopier `cv_`, qui est gonflée.
        self.cv_groupee_ = None
        self.n_essais_ = None
```

Remplacer `MIModel.fit` (lignes 146-150) par :

```python
    def fit(self, epochs, y, groups=None):
        """Entraîne. `groups` = l'indice d'ESSAI de chaque fenêtre — c'est lui qui rend la CV honnête.

        Deux chiffres sortent d'ici, et ils ne disent pas la même chose :

        - `cv_` — validation croisée ORDINAIRE, fenêtres mélangées. Gardée parce qu'elle permet de
          comparer avec les mesures antérieures du projet, et parce que l'écart entre les deux EST
          l'information : c'est la fuite, chiffrée.
        - `cv_groupee_` — validation croisée par ESSAI : toutes les fenêtres d'un essai tombent
          dans le MÊME pli. C'est la seule qui réponde à la question de l'étudiant, « est-ce que ça
          marchera sur un essai que le modèle n'a jamais vu ? ». C'est celle-là, et elle seule,
          qu'on affiche.

        On prend `StratifiedGroupKFold` et non `GroupKFold` : le second ne regarde pas les
        étiquettes et peut composer un pli d'apprentissage où une classe manque entièrement — la
        LDA lève alors, ou pire, apprend sur deux classes et se fait juger sur trois. Le premier
        respecte les DEUX contraintes : groupes entiers ET classes représentées.

        `n_splits` est borné par le plus petit effectif d'essais par classe : demander 5 plis quand
        une classe n'a que 3 essais est irréalisable, et sklearn le refuserait en pleine fin de
        séance de calibration — après sept minutes d'imagerie. On borne AVANT plutôt que de laisser
        lever.
        """
        Xf, y = self._prep(epochs), np.asarray(y)
        self.cv_ = float(cross_val_score(self.pipe, Xf, y, cv=5).mean())
        self.cv_groupee_, self.n_essais_ = None, None
        if groups is not None:
            groups = np.asarray(groups)
            self.n_essais_ = int(len(np.unique(groups)))
            # Essais DISTINCTS par classe : c'est ce qui borne le nombre de plis, pas le nombre de
            # fenêtres (elles se comptent par trois pour un même essai).
            par_classe = [len(np.unique(groups[y == c])) for c in np.unique(y)]
            n_splits = min(5, min(par_classe)) if par_classe else 0
            if n_splits >= 2:
                cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=0)
                self.cv_groupee_ = float(
                    cross_val_score(self.pipe, Xf, y, groups=groups, cv=cv).mean())
        self.pipe.fit(Xf, y)
        return self
```

- [ ] **Step 9: Le test passe**

Run: `python src/core/mi_decoder.py`
Expected: `[mi-cv] VERDICT : OK` puis `[mi] classifieur csp validé.`, sortie 0.

- [ ] **Step 10: Exposer le contrat de calibration au catalogue**

Dans `src/core/modes/registry.py`, `serialize()`, remplacer le bloc `"calibration"` par :

```python
        "calibration": None if spec.calibration is None else {
            "kind": spec.calibration.kind,
            "reason": spec.calibration.reason,
            "label": spec.calibration.label,
            "briefing": list(spec.calibration.briefing),
            "epoch_s": spec.calibration.epoch_s,
            # Même forme que les `params` d'un mode, juste au-dessus : la console réutilise
            # `ParamsForm` sans une ligne de code particulière.
            "params": [
                {
                    "key": p.key, "label": p.label, "kind": p.kind, "unit": p.unit,
                    "default": p.default_now(), "min": p.min, "max": p.max,
                    "count": list(p.count) if p.count else None, "proposes": p.proposes,
                    "choices": list(p.choices_now()), "help": p.help,
                }
                for p in spec.calibration.params
            ],
        },
```

- [ ] **Step 11: Vérifier qu'on n'a rien cassé**

Run, EN SÉRIE :
```bash
python src/core/modes/contract.py
python src/core/modes/registry.py
python src/core/mi_decoder.py
python src/core/mi_models.py
python src/core/modes/mi.py
python src/core/server.py --smoke
```
Expected: tous en sortie 0.

- [ ] **Step 12: Commit**

```bash
git add src/core/config.py src/core/modes/contract.py src/core/modes/registry.py src/core/mi_decoder.py
git commit -m "Make the training contract carry calibration, and the accuracy honest"
```

---

### Task 2: Les constats parkés que la calibration rend atteignables

**Files:**
- Modify: `src/core/modes/mi.py` (`MIRuntime.state()`, l'aide du réglage `model`)
- Modify: `src/core/mi_models.py` (`charger(None)`)

**Interfaces:**
- **Produit** — `MIRuntime.state()` ne lit plus le disque ; `mi_models.charger(None)` rend
  `(None, raison)` au lieu de lever.
- **Consomme** — rien de T1.

**Contexte :** ces trois constats ont été trouvés par la revue de branche de la moitié A et parkés
délibérément — ils étaient **inertes** tant que rien n'écrivait dans `data/` pendant qu'un mode
tourne. La calibration va précisément faire ça. La liste complète est dans le plan de la moitié A,
section « Bilan du chantier », sous « Parké délibérément — à reprendre en moitié B ».

- [ ] **Step 1: Écrire le test de `charger(None)`**

Dans `_selftest()` de `src/core/mi_models.py`, après le bloc « un chemin inexistant » :

```python
        # `charger` promet dans sa docstring de ne JAMAIS lever. Elle levait pourtant sur None,
        # et la moitié B l'appelle avec ce que rend un formulaire — donc potentiellement rien du
        # tout, quand aucun modèle n'existe encore. Une exception ici remonterait jusqu'au fil Qt
        # et arrêterait toute la console.
        for entree in (None, "", 0):
            _m, raison = charger(entree)
            chk(_m is None and raison and "aucun modèle" in raison,
                f"charger({entree!r}) rend une raison au lieu de lever ({raison})")
```

- [ ] **Step 2: Lancer — il doit ÉCHOUER**

Run: `python src/core/mi_models.py`
Expected: `TypeError` sur `os.path.isfile(None)`.

- [ ] **Step 3: Corriger `charger`**

Dans `src/core/mi_models.py`, remplacer les deux premières lignes du corps de `charger` par :

```python
    # Un chemin vide n'est pas un incident : c'est l'état d'un formulaire dont la liste de
    # modèles est vide (dépôt fraîchement cloné, aucune calibration faite). La docstring promet
    # de ne jamais lever ; `os.path.isfile(None)` levait. Le refus doit dire quoi faire.
    if not chemin:
        return None, ("aucun modèle désigné — lance une calibration depuis la console pour en "
                      "produire un")
    if not _os.path.isfile(chemin):
        return None, f"modèle introuvable : {chemin}"
```

- [ ] **Step 4: Le test passe**

Run: `python src/core/mi_models.py`
Expected: `[mi-models] VERDICT : OK`

- [ ] **Step 5: Écrire le test de `MIRuntime.state()`**

Dans `_selftest()` de `src/core/modes/mi.py`, dans le bloc 9 (« Le contrat du mode »), ajouter :

```python
        # `state()` est appelé à CHAQUE `snapshot()`, donc 10 fois par seconde par la console.
        # La version héritée passait par `_channels(params)`, qui RELIT le modèle sur disque —
        # 0,348 ms mesurées, et surtout un retour SILENCIEUX à trois classes par défaut si le
        # fichier a bougé. Inerte jusqu'ici ; atteignable dès que la calibration écrit dans
        # `data/` pendant qu'un mode tourne, ce qui est précisément ce que la moitié B ajoute.
        # Le runtime a son modèle EN MÉMOIRE : il n'a aucune raison d'aller le redemander au
        # disque, et encore moins de mentir si le disque a changé sous ses pieds.
        etat = rt.state()
        chk(etat["channels"] == mi_channel_labels(rt.classes),
            f"les voies de l'état viennent du modèle CHARGÉ ({etat['channels']})")

        chemin_modele = values["model"]
        _os.rename(chemin_modele, chemin_modele + ".deplace")
        try:
            etat_apres = rt.state()
            chk(etat_apres["channels"] == etat["channels"],
                f"et elles ne changent pas si le fichier disparaît du disque — le runtime ne "
                f"relit rien ({etat_apres['channels']})")
        finally:
            _os.rename(chemin_modele + ".deplace", chemin_modele)
```

- [ ] **Step 6: Lancer — le second `chk` doit ÉCHOUER**

Run: `python src/core/modes/mi.py`
Expected: `ÉCHEC` sur « elles ne changent pas si le fichier disparaît » — `_channels` retombe sur
`["GAUCHE", "DROITE", "REPOS"]` par défaut. (Avec un modèle à 3 classes, les listes coïncident par
hasard : si le test passe malgré tout, remplacer le modèle d'essai du bloc par un modèle à DEUX
classes avant de conclure.)

- [ ] **Step 7: Surcharger `state()` dans `MIRuntime`**

Dans `src/core/modes/mi.py`, ajouter à `MIRuntime`, juste après `output()` :

```python
    def state(self):
        """L'état du mode, avec les voies tirées du modèle EN MÉMOIRE.

        `ModeRuntime.state()` passe par `spec.channels_for(self.params)`, donc par `_channels`,
        qui RELIT le modèle sur disque. Deux raisons de ne pas le faire ici, et la seconde est la
        vraie : c'est appelé dix fois par seconde par la console (0,348 ms de lecture disque à
        chaque fois), et surtout `_channels` retombe EN SILENCE sur trois classes par défaut si le
        fichier n'est plus lisible. Dès que la calibration écrit dans `data/` pendant qu'un mode
        tourne, l'état publié pourrait donc annoncer des voies que le flux ne publie pas.

        `_channels` reste ce qu'elle est — c'est ce que le CATALOGUE utilise, avant qu'aucun
        runtime n'existe, et elle n'a alors que le disque pour savoir.
        """
        etat = super().state()
        etat["channels"] = mi_channel_labels(self.classes)
        return etat
```

- [ ] **Step 8: Le test passe**

Run: `python src/core/modes/mi.py`
Expected: `[mi] VERDICT : OK`

- [ ] **Step 9: Corriger l'aide du réglage `model`**

Dans `SPEC` de `src/core/modes/mi.py`, remplacer le `help=` du `Param("model", ...)` par :

```python
            help="Le modèle produit par une calibration MI, propre à TA personne — celui de "
                 "quelqu'un d'autre donne des probabilités plausibles et fausses. Aucun modèle "
                 "dans la liste ? Lance une calibration depuis cette console : bouton "
                 "« Calibrer » sur cette page.",
```

**Pourquoi** : l'aide pointait `python src/research/mi_calibrate.py`, que la tâche 7 archive — elle
allait devenir fausse. Elle envoyait aussi l'étudiant fermer la console pour lancer un autre
programme, ce qui fait **saturer C3/Cz à la réouverture** (les voies mêmes que lit le MI). La
calibration se lance désormais sans quitter la console.

- [ ] **Step 10: Vérifier**

Run, EN SÉRIE : `python src/core/mi_models.py` · `python src/core/modes/mi.py` ·
`python src/core/server.py --smoke` · `python src/console/app.py --smoke`
Expected: tous en sortie 0.

- [ ] **Step 11: Commit**

```bash
git add src/core/mi_models.py src/core/modes/mi.py
git commit -m "Close the three parked findings a calibration would have made reachable"
```

---

### Task 3: `CalibrationRuntime` — la ligne du temps, et le protocole MI

**Files:**
- Create: `src/core/modes/calibration.py`
- Create: `src/core/modes/mi_calib.py`
- Modify: `src/core/modes/mi.py` (renseigner `calibration=` dans `SPEC`)
- Test: les autotests des deux nouveaux fichiers (`python src/core/modes/calibration.py`,
  `python src/core/modes/mi_calib.py`)

**Interfaces:**
- **Consomme** — `Calib(kind, label, briefing, params, epoch_s, runtime_cls)` et
  `MIModel.fit(epochs, y, groups=...)` (T1) ; `EngineServer.recent_window(seconds)` et
  `engine.acq.fs` (existants).
- **Produit** — `CalibrationRuntime(spec, params, engine)` avec `tick(engine, now)`,
  `cancel()`, `terminee` (booléen), `state()` (dict JSON-able) ; `mi_calib.MICalibration` ;
  `mi_calib.CALIB` (l'objet `Calib` du MI, à poser dans `mi.SPEC`).

**Contrainte d'architecture, la plus importante de la tâche :** un runtime ne lit **jamais**
l'horloge lui-même — `tick` reçoit `now`. C'est ce qui rend la ligne du temps testable sans dormir,
et c'est la règle que `ModeRuntime` suit déjà (voir sa docstring). Une calibration qui appellerait
`time.perf_counter()` obligerait son test à durer sept minutes.

- [ ] **Step 1: Écrire `src/core/modes/calibration.py`**

```python
"""`CalibrationRuntime` — la ligne du temps d'une calibration, jouée par le MOTEUR.

Ce qui est ICI est ce que **toute** calibration partage : la chauffe, l'échauffement non
enregistré, la suite d'essais tirés au hasard, l'entraînement, le résultat. Ce qui est dans les
sous-classes est ce qui diffère : les classes à cuer, les consignes, et ce qu'on fait des époques
à la fin.

⚠️ **Une calibration n'est PAS un mode.** Elle vit dans un emplacement propre du moteur
(`EngineServer.calibration`), pas dans `self.active`. La raison est concrète : le mode Motor
Imagery REFUSE de démarrer sans modèle entraîné, donc une calibration hébergée par ce mode serait
inatteignable pour la seule personne qui en a besoin — celle qui n'a pas encore de modèle.

⚠️ **Un runtime ne lit jamais l'horloge lui-même** : `tick` reçoit `now`, comme `ModeRuntime`.
C'est ce qui permet de jouer une séance de sept minutes en quelques millisecondes dans un test.

Autotest :
    python src/core/modes/calibration.py
"""

import os as _os
import random as _random
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import use_utf8_console  # noqa: E402

# Les phases publiques, dans l'ordre où elles s'enchaînent. Elles sortent telles quelles dans
# `snapshot()["calibration"]["phase"]` : la console les traduit, elle n'en invente aucune.
PHASES = ("chauffe", "echauffement", "essais", "entrainement", "fini", "annule")

# Les étapes À L'INTÉRIEUR d'un essai.
ETAPES = ("cue", "imagerie", "repos")


class CalibrationRuntime:
    """Une calibration en cours. Le moteur en tient AU PLUS UNE — le casque est unique."""

    # --- à renseigner par la sous-classe ------------------------------------
    classes = ()            # les étiquettes à cuer, dans l'ordre de déclaration
    cue_s = 3.0             # mise en route, JETÉE
    imagery_s = 4.0         # la partie ENREGISTRÉE
    rest_s = 1.5            # pause entre deux essais
    warmup_s = 15.0         # stabilisation du casque, JETÉE (dérive DC de l'Unicorn)
    warmup_per_class = 2    # essais d'échauffement NON enregistrés

    def __init__(self, spec, params, engine, rng=None):
        """`spec` : le `ModeSpec` du mode calibré. `params` : les réglages VALIDÉS de la calibration.

        `rng` est injectable pour que le test obtienne un ordre reproductible. En séance il est
        tiré au hasard, et il DOIT l'être : un ordre fixe apprendrait au sujet à anticiper la
        classe suivante, ce qui contamine l'imagerie par de l'attente motrice.
        """
        self.spec = spec
        self.calib = spec.calibration
        self.params = dict(params)
        self.engine = engine
        self.rng = rng or _random.Random()

        self.phase = "chauffe"
        self.etape = ""
        self.classe = ""
        self.essai = 0            # essais ENREGISTRÉS déjà terminés
        self.resultat = None
        self.probleme = ""
        self._echeance = None     # instant de fin de l'étape en cours (horloge de l'appelant)
        self._suite = []          # les étiquettes restantes de la phase en cours
        self._enregistre = []     # [(époque (n, 8), étiquette)]
        self._demarre = False

    # --- ce que la sous-classe fournit ---------------------------------------

    def instruction(self):
        """La consigne à afficher MAINTENANT, en grand."""
        return ""

    def rappel(self):
        """La ligne secondaire, sous la consigne. "" s'il n'y en a pas."""
        return ""

    def _entrainer(self, enregistre, fs):
        """Entraîne et sauvegarde. Rend le dict de résultat, ou lève avec un message lisible."""
        raise NotImplementedError

    # --- la ligne du temps ---------------------------------------------------

    @property
    def terminee(self):
        return self.phase in ("fini", "annule")

    def trials_per_class(self):
        return int(self.params.get("trials_per_class", 0))

    def total(self):
        """Le nombre d'essais ENREGISTRÉS de la séance. L'échauffement n'en fait pas partie."""
        return self.trials_per_class() * len(self.classes)

    def duree_estimee_s(self):
        """Le temps total, échauffement et chauffe compris. Calculé, jamais stocké."""
        par_essai = self.cue_s + self.imagery_s + self.rest_s
        n = self.total() + self.warmup_per_class * len(self.classes)
        return self.warmup_s + n * par_essai

    def cancel(self):
        """Abandon. Ce qui est déjà enregistré n'est PAS entraîné ni sauvegardé.

        Choix délibéré : une séance interrompue à cinq essais produirait un modèle que rien ne
        distingue d'un modèle complet dans la liste, et qui donnerait des probabilités plausibles
        et fausses. L'écran pygame, lui, entraînait sur ce qui restait — comportement qu'on ne
        reprend pas.
        """
        if not self.terminee:
            self.phase = "annule"
            self.etape, self.classe, self._echeance = "", "", None

    def tick(self, engine, now):
        """Un pas. Appelé par la boucle du moteur, jamais par une interface."""
        if self.terminee:
            return
        if not self._demarre:
            self._demarre = True
            self._echeance = now + self.warmup_s
            return

        if self._echeance is not None and now < self._echeance:
            return

        if self.phase == "chauffe":
            self._commencer_echauffement(now)
        elif self.phase in ("echauffement", "essais"):
            self._pas_essai(engine, now)
        elif self.phase == "entrainement":
            self._terminer(engine)

    def _commencer_echauffement(self, now):
        self._suite = self._tirage(self.warmup_per_class)
        if not self._suite:
            self._commencer_essais(now)
            return
        self.phase = "echauffement"
        self._prochain_essai(now)

    def _commencer_essais(self, now):
        self.phase = "essais"
        self._suite = self._tirage(self.trials_per_class())
        if not self._suite:
            self.phase = "entrainement"
            self.etape, self.classe, self._echeance = "", "", now
            return
        self._prochain_essai(now)

    def _tirage(self, par_classe):
        """Les étiquettes d'une phase, MÉLANGÉES. Un ordre fixe s'anticipe (cf. `__init__`)."""
        suite = [c for c in self.classes for _ in range(par_classe)]
        self.rng.shuffle(suite)
        return suite

    def _prochain_essai(self, now):
        self.classe = self._suite.pop(0)
        self.etape = "cue"
        self._echeance = now + self.cue_s

    def _pas_essai(self, engine, now):
        if self.etape == "cue":
            self.etape = "imagerie"
            self._echeance = now + self.imagery_s
            return

        if self.etape == "imagerie":
            # L'époque est prélevée À LA FIN de l'imagerie, pas au fil de l'eau : le tampon
            # glissant du moteur contient les `imagery_s` dernières secondes, et c'est exactement
            # celles-là qu'on veut. `epoch_s` du contrat garantit que le tampon est assez long.
            if self.phase == "essais":
                epoque = engine.recent_window(self.imagery_s)
                attendu = int(round(self.imagery_s * engine.acq.fs))
                if epoque is not None and len(epoque) >= attendu:
                    self._enregistre.append((epoque, self.classe))
                    self.essai += 1
                else:
                    # On le DIT plutôt que d'enregistrer une époque courte : un essai tronqué
                    # produit moins de fenêtres d'entraînement, en silence.
                    obtenu = 0 if epoque is None else len(epoque)
                    print(f"[calib] essai IGNORÉ ({self.classe}) : {obtenu} échantillons au lieu "
                          f"de {attendu} — le tampon du moteur n'était pas encore rempli")
            self.etape = "repos"
            self._echeance = now + self.rest_s
            return

        # repos terminé
        if self._suite:
            self._prochain_essai(now)
        elif self.phase == "echauffement":
            self._commencer_essais(now)
        else:
            self.phase = "entrainement"
            self.etape, self.classe, self._echeance = "", "", now

    def _terminer(self, engine):
        """L'entraînement. Bloque la boucle du moteur le temps du `fit` — quelques secondes.

        C'est assumé : à cet instant, plus rien ne doit être acquis pour cette séance, et
        déporter l'entraînement dans un fil ferait toucher `data/` par deux fils. Le décodage des
        autres modes est simplement suspendu pendant ce temps.
        """
        try:
            self.resultat = self._entrainer(self._enregistre, float(engine.acq.fs))
            self.phase = "fini"
        except Exception as e:  # noqa: BLE001 - l'échec de l'entraînement ne tue pas le moteur
            self.probleme = f"{type(e).__name__} : {e}"
            self.phase = "annule"
            print(f"[calib] entraînement impossible : {self.probleme}")
        self.etape, self.classe, self._echeance = "", "", None

    # --- l'état, pour l'afficheur -------------------------------------------

    def restant_s(self, now):
        """Secondes restantes sur l'étape en cours. 0 quand il n'y a rien à décompter."""
        if self._echeance is None:
            return 0.0
        return max(0.0, self._echeance - now)

    def state(self, now=None):
        """L'état complet, en dictionnaire JSON-able. Sûr depuis un autre fil.

        `now` est facultatif : sans lui, le décompte vaut 0. Le moteur le passe depuis sa boucle,
        et c'est la seule horloge qui fait foi.
        """
        return {
            "mode_id": self.spec.id,
            "label": self.calib.label or f"Calibration {self.spec.label}",
            "phase": self.phase,
            "etape": self.etape,
            "classe": self.classe,
            "instruction": self.instruction(),
            "rappel": self.rappel(),
            "essai": self.essai,
            "total": self.total(),
            "restant_s": round(self.restant_s(now or 0.0), 1) if now else 0.0,
            "duree_estimee_s": round(self.duree_estimee_s(), 1),
            "params": dict(self.params),
            "classes": list(self.classes),
            "resultat": self.resultat,
            "probleme": self.probleme,
        }


def _selftest():
    """La ligne du temps sur une horloge FABRIQUÉE. Aucune séance, aucune attente réelle."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    import numpy as np

    from core.modes.contract import Calib, ModeSpec, Param

    class _FausseAcq:
        fs = 250.0

    class _FauxMoteur:
        """Rend toujours une époque de la bonne longueur : on teste la LIGNE DU TEMPS, pas
        l'acquisition."""

        def __init__(self):
            self.acq = _FausseAcq()
            self.demandes = []

        def recent_window(self, seconds):
            self.demandes.append(seconds)
            return np.zeros((int(round(seconds * self.acq.fs)), 8))

    class _Essai(CalibrationRuntime):
        classes = ("A", "B")
        cue_s, imagery_s, rest_s, warmup_s, warmup_per_class = 3.0, 4.0, 1.5, 15.0, 2

        def instruction(self):
            return f"Fais {self.classe}" if self.classe else ""

        def _entrainer(self, enregistre, fs):
            return {"n_essais": len(enregistre), "fs": fs,
                    "classes": sorted({lab for _e, lab in enregistre})}

    spec = ModeSpec(
        id="essai", label="Essai", family="actif", summary="", status="moteur",
        calibration=Calib(kind="console", label="Calibration d'essai", epoch_s=4.0,
                          params=(Param("trials_per_class", "Essais par classe", "int",
                                        default=3, min=1, max=40),),
                          runtime_cls=_Essai))

    moteur = _FauxMoteur()
    rt = _Essai(spec, {"trials_per_class": 3}, moteur, rng=_random.Random(0))

    chk(rt.total() == 6, f"3 essais par classe sur 2 classes = 6 essais enregistrés ({rt.total()})")
    chk(abs(rt.duree_estimee_s() - (15.0 + 10 * 8.5)) < 1e-6,
        f"la durée estimée compte l'échauffement ET la chauffe ({rt.duree_estimee_s():.1f} s)")

    # La chauffe est JETÉE : rien n'est enregistré pendant, et elle dure ce qu'elle annonce.
    t = 100.0
    rt.tick(moteur, t)
    chk(rt.phase == "chauffe", f"on commence par la chauffe ({rt.phase})")
    rt.tick(moteur, t + 14.9)
    chk(rt.phase == "chauffe" and not moteur.demandes,
        "pendant la chauffe, RIEN n'est prélevé (la dérive DC fausserait les époques)")

    # Une horloge fabriquée, pas à pas : on avance par petits sauts jusqu'à la fin de la séance.
    t = 115.0
    for _ in range(4000):
        rt.tick(moteur, t)
        if rt.terminee:
            break
        t += 0.25

    chk(rt.phase == "fini", f"la séance se termine ({rt.phase}, problème={rt.probleme!r})")
    chk(rt.essai == 6, f"6 essais enregistrés, pas un de plus ({rt.essai})")
    chk(rt.resultat and rt.resultat["n_essais"] == 6,
        f"et c'est ce qui part à l'entraînement ({rt.resultat})")
    chk(rt.resultat and sorted(rt.resultat["classes"]) == ["A", "B"],
        f"les deux classes sont représentées ({rt.resultat})")
    # 10 essais joués (4 d'échauffement + 6 enregistrés), 6 prélèvements : l'échauffement ne
    # prélève RIEN. C'est le seul test qui distingue « non enregistré » de « enregistré puis jeté ».
    chk(len(moteur.demandes) == 6,
        f"l'échauffement ne prélève aucune époque ({len(moteur.demandes)} prélèvements pour "
        f"{4 + 6} essais joués)")
    chk(all(abs(s - 4.0) < 1e-9 for s in moteur.demandes),
        f"et chaque prélèvement demande imagery_s, pas la durée de l'essai ({set(moteur.demandes)})")

    # L'abandon : ni entraînement, ni modèle. Une séance à moitié faite ne doit pas produire un
    # modèle indiscernable d'un modèle complet.
    rt2 = _Essai(spec, {"trials_per_class": 3}, _FauxMoteur(), rng=_random.Random(1))
    t = 0.0
    for _ in range(200):
        rt2.tick(rt2.engine, t)
        t += 0.25
    rt2.cancel()
    chk(rt2.phase == "annule" and rt2.resultat is None,
        f"un abandon ne produit AUCUN modèle ({rt2.phase}, {rt2.resultat})")
    avant = rt2.essai
    rt2.tick(rt2.engine, t + 100.0)
    chk(rt2.essai == avant and rt2.phase == "annule",
        "et une calibration annulée ne repart pas toute seule au tick suivant")

    # Un entraînement qui lève ne doit pas tuer le moteur : il se solde en « annulé » + raison.
    class _Casse(_Essai):
        def _entrainer(self, enregistre, fs):
            raise ValueError("pas assez de données")

    rt3 = _Casse(spec, {"trials_per_class": 1}, _FauxMoteur(), rng=_random.Random(2))
    t = 0.0
    for _ in range(4000):
        rt3.tick(rt3.engine, t)
        if rt3.terminee:
            break
        t += 0.25
    chk(rt3.phase == "annule" and "pas assez de données" in rt3.probleme,
        f"un entraînement qui lève se solde par un refus lisible ({rt3.phase}, {rt3.probleme})")

    # L'état est JSON-able : il part dans `snapshot()`, que la console sérialise.
    import json

    json.dumps(rt.state(now=t))
    chk(True, "l'état est sérialisable en JSON")
    etat = rt.state(now=t)
    chk(set(etat) >= {"phase", "etape", "classe", "instruction", "essai", "total", "restant_s",
                      "resultat", "probleme"},
        f"et il porte tout ce que la console doit peindre ({sorted(etat)})")

    print(f"[calibration] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
```

- [ ] **Step 2: Lancer l'autotest**

Run: `python src/core/modes/calibration.py`
Expected: `[calibration] VERDICT : OK`

- [ ] **Step 3: Écrire `src/core/modes/mi_calib.py`**

```python
"""La calibration Motor Imagery : le protocole, l'entraînement, la sauvegarde.

Le protocole est celui qui a été validé au casque et qui vit aujourd'hui dans l'écran pygame
`src/research/mi_calibrate.py` — mêmes durées, mêmes consignes, même découpage. Il est repris ici
mot pour mot, à trois différences près, toutes voulues :

1. **L'accuracy affichée est HONNÊTE** (validation croisée par essai, cf. `MIModel.fit`). L'écran
   pygame affiche un chiffre gonflé de 10 à 16 points.
2. **Rien n'est jamais écrasé** : le modèle et l'enregistrement sont horodatés. `mi_calib_last.npz`
   avait un nom FIXE, et c'est ce qui a fait perdre les époques d'une séance à 42 essais.
3. **Une séance abandonnée n'entraîne rien** (cf. `CalibrationRuntime.cancel`).

Autotest :
    python src/core/modes/mi_calib.py
"""

import os as _os
import random as _random
import sys as _sys
import time as _time

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np  # noqa: E402

from core.config import (DATA_DIR, MI_CUE_S, MI_IMAGERY_S, MI_REST_S,  # noqa: E402
                         MI_SESSIONS, MI_TRAIN_STEP_S, MI_WARMUP_PER_CLASS, MI_WINDOW_S,
                         SSVEP_WARMUP_S, use_utf8_console)
from core.mi_decoder import MI_LABELS, MIModel  # noqa: E402
from core.modes.calibration import CalibrationRuntime  # noqa: E402
from core.modes.contract import Calib, Param  # noqa: E402

# Les consignes, telles qu'elles ont été validées. La formulation compte : « SENTIR le serrement »
# et non « se le représenter » est la différence entre de l'imagerie kinesthésique, qui produit
# une ERD exploitable, et de l'imagerie visuelle, qui n'en produit pas.
INSTRUCTIONS = {
    "GAUCHE": "Imagine : SERRE le POING GAUCHE",
    "DROITE": "Imagine : SERRE le POING DROIT",
    "REPOS": "REPOS — détends-toi, ne rien imaginer",
}
RAPPEL = "sens le serrement — NE BOUGE PAS"

BRIEFING = (
    "Un top au DÉBUT de chaque essai donne le côté : oreille GAUCHE = poing gauche,",
    "oreille DROITE = poing droit, les DEUX oreilles (plus long) = repos.",
    "Imagine dès le top et TIENS jusqu'à la fin du décompte.",
    "Imagine le serrement en le SENTANT (tension dans l'avant-bras), sans bouger la main.",
    "Maintiens ou pompe le serrement toute la durée — pas un seul clic.",
    "Astuce : serre vraiment 3-4 fois AVANT de commencer, pour mémoriser la sensation.",
    "Immobile, cligne le moins possible pendant l'imagerie.",
    "REPOS = ne rien faire de spécial : relâche, respire normalement, aucune imagerie de main.",
)

# Les verdicts sont calés sur l'échelle HONNÊTE, pas sur l'ancienne. Les seuils de l'écran pygame
# (75 % / 60 %) valaient pour une CV gonflée de 10 à 16 points : les reprendre tels quels
# déclarerait « FAIBLE » une séance parfaitement ordinaire. Repère du projet, mesuré honnêtement
# sur sa seule séance de référence : 40,0 % à 3 classes (p = 0,082, PAS significatif) et 63,3 % à
# 2 classes (p = 0,038). Autrement dit : autour de 40 %, on est dans le NORMAL, et ça ne suffit
# pas à piloter quoi que ce soit.
VERDICTS = ((0.60, "EXCELLENT"), (0.45, "UTILISABLE"),
            (0.00, "FAIBLE — ré-essaie : contact des électrodes, immobilité, imagerie "
                   "kinesthésique (SENTIR, pas voir)"))


def horodatage(maintenant=None):
    """`AAAAMMJJ-HHMMSS`. Le paramètre existe pour que le test soit reproductible."""
    return _time.strftime("%Y%m%d-%H%M%S", _time.localtime(maintenant or _time.time()))


def decouper(epoque, n, pas):
    """Découpe une époque (n_samp, n_ch) en fenêtres (n_ch, n) glissantes.

    L'orientation compte : `MIModel` attend (n_essais, n_ch, n_samp), et le CSP est un filtre
    SPATIAL — une transposition oubliée décoderait du bruit avec des probabilités à 0,99.
    """
    return [epoque[i:i + n].T for i in range(0, len(epoque) - n + 1, pas)]


def verdict(cv):
    for seuil, texte in VERDICTS:
        if cv >= seuil:
            return texte
    return VERDICTS[-1][1]


class MICalibration(CalibrationRuntime):
    """Le protocole MI. Sa seule particularité est ce qu'elle fait des époques à la fin."""

    classes = MI_LABELS
    cue_s = MI_CUE_S
    imagery_s = MI_IMAGERY_S
    rest_s = MI_REST_S
    warmup_s = SSVEP_WARMUP_S          # la même chauffe que les modes : c'est la même dérive DC
    warmup_per_class = MI_WARMUP_PER_CLASS
    # Le découpage en fenêtres d'entraînement. Attributs de CLASSE, comme les durées, et pour la
    # même raison : un test doit pouvoir jouer une séance entière en quelques secondes, et il ne
    # peut le faire qu'en raccourcissant la fenêtre EN MÊME TEMPS que l'imagerie. Les raccourcir
    # séparément donne `imagery_s < window_s`, donc ZÉRO fenêtre découpée et un entraînement qui
    # refuse — un piège dans lequel ce plan est tombé en s'écrivant.
    window_s = MI_WINDOW_S
    step_s = MI_TRAIN_STEP_S

    def __init__(self, spec, params, engine, rng=None, dossier=None):
        """`dossier` : où écrire. Injectable pour que les tests n'approchent jamais le vrai `data/`."""
        super().__init__(spec, params, engine, rng=rng)
        self.dossier = dossier or DATA_DIR

    def instruction(self):
        return INSTRUCTIONS.get(self.classe, "")

    def rappel(self):
        return RAPPEL if self.classe in ("GAUCHE", "DROITE") else ""

    def _entrainer(self, enregistre, fs):
        """CSP + LDA sur les fenêtres, CV honnête par essai, puis sauvegarde horodatée."""
        n = int(round(self.window_s * fs))
        pas = int(round(self.step_s * fs))
        X, y, groupes = [], [], []
        for indice, (epoque, label) in enumerate(enregistre):
            for fenetre in decouper(np.asarray(epoque, dtype=float), n, pas):
                X.append(fenetre)
                y.append(label)
                groupes.append(indice)     # le GROUPE est l'essai : c'est ce qui rend la CV honnête

        comptes = {c: y.count(c) for c in self.classes}
        if not X or min(comptes.values()) < 5:
            raise ValueError(
                f"pas assez de données pour entraîner : {comptes} fenêtres par classe, il en faut "
                f"au moins 5 — refais une séance plus longue")

        modele = MIModel(fs=fs).fit(np.asarray(X), np.asarray(y), groups=np.asarray(groupes))

        stamp = horodatage()
        _os.makedirs(self.dossier, exist_ok=True)
        # Le motif `mi_model*.joblib` est celui que `mi_models.modeles_disponibles` cherche :
        # ne pas s'en écarter, sinon le modèle produit n'apparaîtra jamais dans la liste.
        chemin_modele = _os.path.join(self.dossier, f"mi_model_{stamp}.joblib")
        chemin_npz = _os.path.join(self.dossier,
                                   f"mi_calib_{stamp}_n{len(enregistre):02d}.npz")
        modele.save(chemin_modele)
        np.savez(chemin_npz,
                 epochs=np.asarray([e for e, _l in enregistre]),
                 labels=np.asarray([l for _e, l in enregistre]),
                 fs=fs, window_s=self.window_s, step_s=self.step_s,
                 imagery_s=self.imagery_s)

        cv = modele.cv_groupee_ if modele.cv_groupee_ is not None else 0.0
        hasard = 1.0 / len(self.classes)
        print(f"[mi-calib] accuracy HONNÊTE (validation croisée par essai) : {cv*100:.1f}% "
              f"— hasard {hasard*100:.0f}% — {verdict(cv)}")
        print(f"[mi-calib] (pour mémoire, la CV naïve, fenêtres mélangées : "
              f"{modele.cv_*100:.1f}% — gonflée, ne pas s'y fier)")
        print(f"[mi-calib] modèle : {chemin_modele}")
        print(f"[mi-calib] enregistrement : {chemin_npz}")
        return {
            "modele": chemin_modele,
            "nom": _os.path.basename(chemin_modele),
            "enregistrement": chemin_npz,
            "n_essais": len(enregistre),
            "n_fenetres": len(X),
            "cv_groupee": cv,
            "cv_naive": float(modele.cv_),
            "hasard": hasard,
            "classes": list(self.classes),
            "verdict": verdict(cv),
        }


CALIB = Calib(
    kind="console",
    label="Calibration Motor Imagery",
    briefing=BRIEFING,
    epoch_s=MI_IMAGERY_S,
    params=(
        Param(
            key="trials_per_class",
            label="Essais par classe",
            kind="choice",
            default=MI_SESSIONS[1],
            choices=MI_SESSIONS,
            help="Combien d'essais par classe. Plus long n'est PAS forcément meilleur : le "
                 "facteur limitant mesuré est la FATIGUE, pas la durée — sur la séance de "
                 "référence du projet, la justesse à 3 classes tombe de 57 % à 33 % en deuxième "
                 "moitié. Commence par la valeur par défaut.",
        ),
    ),
    runtime_cls=MICalibration,
)


def _selftest():
    """Une séance complète, jouée en accéléré sur du signal FABRIQUÉ, dans un dossier temporaire."""
    import shutil
    import tempfile

    from core.mi_decoder import synth_mi_trial
    from core.modes import mi as _mi

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _FausseAcq:
        fs = 250.0

    class _FauxMoteur:
        """Rend une époque d'ERD synthétique CORRESPONDANT à la classe cuée.

        Sans ça, l'entraînement porterait sur du bruit et le test ne dirait rien du contenu — il
        ne prouverait que la plomberie. Ici, un modèle doit sortir ET les classes doivent être
        celles qu'on a cuées.
        """

        def __init__(self, runtime, rng):
            self.acq = _FausseAcq()
            self.runtime = runtime
            self.rng = rng

        def recent_window(self, seconds):
            n = int(round(seconds * self.acq.fs))
            label = self.runtime.classe or "REPOS"
            return synth_mi_trial(label, n_samp=n, fs=self.acq.fs, rng=self.rng).T

    dossier = tempfile.mkdtemp(prefix="mi_calib_")
    try:
        chk(_mi.SPEC.calibration is CALIB,
            "le mode MI déclare CETTE calibration dans son contrat")
        chk(_mi.SPEC.calibration.epoch_s == MI_IMAGERY_S,
            f"et annonce la longueur d'époque dont le moteur devra dimensionner son tampon "
            f"({_mi.SPEC.calibration.epoch_s} s)")

        rng = np.random.default_rng(0)
        rt = MICalibration(_mi.SPEC, {"trials_per_class": 6}, None,
                           rng=_random.Random(0), dossier=dossier)
        rt.engine = _FauxMoteur(rt, rng)

        t = 0.0
        for _ in range(20000):
            rt.tick(rt.engine, t)
            if rt.terminee:
                break
            t += 0.25

        chk(rt.phase == "fini", f"la séance aboutit ({rt.phase} ; problème={rt.probleme!r})")
        res = rt.resultat or {}
        chk(res.get("n_essais") == 18,
            f"6 essais × 3 classes = 18 enregistrés ({res.get('n_essais')})")
        chk(res.get("n_fenetres") == 18 * 3,
            f"et 3 fenêtres par essai de 4 s ({res.get('n_fenetres')})")

        # L'invariant du chantier : le chiffre AFFICHÉ est l'honnête, et il est plus BAS.
        chk(res.get("cv_groupee") is not None and res.get("cv_naive") is not None,
            f"les deux CV sont rapportées ({res.get('cv_groupee')}, {res.get('cv_naive')})")
        chk(res["cv_groupee"] < res["cv_naive"],
            f"et c'est l'HONNÊTE qui est affichée, plus basse que la naïve "
            f"({res['cv_groupee']*100:.1f}% contre {res['cv_naive']*100:.1f}%)")
        chk(abs(res.get("hasard", 0) - 1 / 3) < 1e-9,
            f"le niveau du hasard est rapporté à côté ({res.get('hasard')})")

        # Rien n'est écrasé : deux séances donnent deux fichiers, et le modèle est visible.
        from core import mi_models

        chk(_os.path.basename(res["modele"]).startswith("mi_model_")
            and res["modele"].endswith(".joblib"),
            f"le modèle est horodaté ({_os.path.basename(res['modele'])})")
        chk("_n18.npz" in res["enregistrement"],
            f"l'enregistrement porte le nombre d'essais ({_os.path.basename(res['enregistrement'])})")
        chk(mi_models.modeles_disponibles(dossier) == [res["modele"]],
            f"et le modèle produit est VISIBLE dans la liste — c'est le motif "
            f"`mi_model*.joblib` qui le veut ({mi_models.modeles_disponibles(dossier)})")

        d = mi_models.decrire(res["modele"])
        chk(d["cv_groupee"] is not None and abs(d["cv_groupee"] - res["cv_groupee"]) < 1e-9,
            f"la description du modèle porte la CV HONNÊTE, pas None ({d['cv_groupee']})")
        chk(d["n_essais"] == 18, f"et le nombre d'essais ({d['n_essais']})")

        # Une séance trop courte doit REFUSER d'entraîner, avec une raison, plutôt que de
        # produire un modèle que rien ne distingue d'un bon.
        court = MICalibration(_mi.SPEC, {"trials_per_class": 1}, None,
                              rng=_random.Random(1), dossier=dossier)
        court.engine = _FauxMoteur(court, rng)
        t = 0.0
        for _ in range(20000):
            court.tick(court.engine, t)
            if court.terminee:
                break
            t += 0.25
        chk(court.phase == "annule" and "pas assez de données" in court.probleme,
            f"une séance trop courte refuse d'entraîner, en disant pourquoi "
            f"({court.phase}, {court.probleme})")
        chk(len(mi_models.modeles_disponibles(dossier)) == 1,
            "et n'ajoute AUCUN modèle à la liste")

        chk(verdict(0.70) == "EXCELLENT" and verdict(0.50) == "UTILISABLE"
            and verdict(0.40).startswith("FAIBLE"),
            "les verdicts sont calés sur l'échelle HONNÊTE : 40 % n'est pas « utilisable »")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[mi-calib] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
```

- [ ] **Step 4: Brancher la calibration sur le contrat du mode MI**

Dans `src/core/modes/mi.py`, remplacer la ligne `calibration=None,` de `SPEC` par :

```python
    calibration=mi_calib.CALIB,   # la calibration est jouée par le MOTEUR (moitié B)
```

et ajouter l'import, **après** les autres imports `core.modes` :

```python
from core.modes import mi_calib  # noqa: E402
```

⚠️ **Vérifier qu'il n'y a pas de cycle d'import** : `mi_calib` importe `core.modes.calibration` et
`core.modes.contract`, mais **pas** `core.modes.mi`. Son autotest, lui, importe `core.modes.mi` —
mais à l'intérieur de `_selftest()`, donc à l'exécution, pas à l'import. Ne pas remonter cet
import en tête de `mi_calib.py` : ce serait le cycle.

- [ ] **Step 5: Lancer les deux autotests**

Run: `python src/core/modes/calibration.py` puis `python src/core/modes/mi_calib.py`
Expected: les deux en `VERDICT : OK`.

- [ ] **Step 6: Vérifier la non-régression**

Run, EN SÉRIE : `python src/core/modes/mi.py` · `python src/core/modes/registry.py` ·
`python src/core/server.py --smoke` · `python src/console/app.py --smoke`
Expected: tous en sortie 0. `server.py --smoke` vérifie aussi la frontière `core` → pas de pygame,
pas de Qt, pas d'import de `research` : les deux nouveaux fichiers y passent.

- [ ] **Step 7: Commit**

```bash
git add src/core/modes/calibration.py src/core/modes/mi_calib.py src/core/modes/mi.py
git commit -m "Give the engine a calibration timeline, and Motor Imagery its protocol"
```

---

### Task 4: Le moteur joue la calibration

**Files:**
- Modify: `src/core/server.py` (emplacement, commandes, tick, `keep`, phase publique, smoke)

**Interfaces:**
- **Consomme** — `CalibrationRuntime` (T3), `Calib.epoch_s` / `.runtime_cls` / `.params` (T1),
  `contract.validate` sur un `Calib`.
- **Produit** — `engine.submit("start_calibration", id=..., params={...})` et
  `engine.submit("cancel_calibration")` ; `snapshot()["calibration"]` = `None` ou l'état complet ;
  la phase publique `"calibrating"`.

- [ ] **Step 1: Dimensionner le tampon sur la plus longue époque de calibration**

Dans `EngineServer.__init__`, remplacer le calcul de `self.keep` (lignes 121-130) par :

```python
        # Le tampon doit satisfaire le plus gourmand des consommateurs : la qualité veut
        # QUALITY_WINDOW_S, le SSVEP WINDOW_S, le neuro NEURO_WINDOW_S, le MI MI_WINDOW_S — chacun
        # plus la marge de filtre. On dimensionne sur TOUS les modes, pas sur ceux qui tournent :
        # démarrer un mode en cours de séance ne doit pas dépendre de la taille d'un tampon.
        #
        # ⚠️ Et sur les CALIBRATIONS, qui prélèvent des tranches BIEN PLUS LONGUES que n'importe
        # quel décodeur : le MI enregistre des époques de 4 s là où il en décode 2. Sans ce terme,
        # chaque époque serait tronquée à la longueur du tampon — sans erreur, sans avertissement,
        # avec un tiers des fenêtres d'entraînement attendues. C'est `Calib.epoch_s` qui le déclare.
        epoque_calib = max([spec.calibration.epoch_s for spec in registry.MODES
                            if spec.calibration is not None] or [0.0])
        self.keep = max(int(QUALITY_WINDOW_S * self.acq.fs),
                        int(NEURO_WINDOW_S * self.acq.fs),
                        int(MI_WINDOW_S * self.acq.fs),
                        int(epoque_calib * self.acq.fs),
                        self.acq.window_n) + self.acq.margin_n
```

Et dans `__init__`, à côté de `self.active = {}` :

```python
        # AU PLUS UNE calibration à la fois, tous modes confondus : il n'y a qu'un casque et qu'une
        # personne. Elle vit ICI et non dans `self.active` — un mode qui refuse de démarrer sans
        # modèle (le MI) rendrait sa propre calibration inatteignable.
        self.calibration = None
```

- [ ] **Step 2: Les deux commandes**

Ajouter à `COMMANDS` :

```python
    COMMANDS = ("start_mode", "propose_params", "stop_mode", "set_params", "set_published",
                "recalibrate", "start_calibration", "cancel_calibration", "stop")
```

Dans `submit`, **avant** le bloc `spec, reason = self._one(params.get("id"))` (qui exige un mode
DÉMARRÉ — ce qu'une calibration n'exige justement pas), insérer :

```python
        if command == "start_calibration":
            spec = registry.get(params.get("id"))
            if spec is None:
                connus = ", ".join(s.id for s in registry.MODES if s.calibration is not None)
                return {"accepted": False,
                        "reason": f"mode inconnu : {params.get('id')} "
                                  f"(se calibrent : {connus})"}
            calib = spec.calibration
            if calib is None:
                return {"accepted": False,
                        "reason": f"« {spec.label} » n'a pas de calibration — il n'apprend rien"}
            if calib.runtime_cls is None:
                # Le c-VEP et le P300 : leur stimulus est verrouillé à la frame, une interface Qt
                # ne peut pas le rendre. La raison est dans le contrat, on la transmet telle quelle.
                return {"accepted": False,
                        "reason": f"la calibration de « {spec.label} » n'est pas jouable par le "
                                  f"moteur : {calib.reason or 'stimulus natif requis'} — passe "
                                  f"par `python src/research/app.py`"}
            # ⚠️ Ce mode n'a PAS besoin d'être démarré : c'est même le cas normal. Le mode MI
            # refuse de démarrer sans modèle, or c'est justement la calibration qui en produit un.
            if self.calibration is not None and not self.calibration.terminee:
                en_cours = self.calibration.spec.label
                return {"accepted": False,
                        "reason": f"une calibration est déjà en cours ({en_cours}) — abandonne-la "
                                  f"avant d'en lancer une autre"}
            values, reason = contract.validate(calib, params.get("params") or {})
            if values is None:
                return {"accepted": False, "reason": reason}
            self._commands.put(("start_calibration", {"id": spec.id, "params": values}))
            return {"accepted": True, "command": command, "id": spec.id, "params": values}

        if command == "cancel_calibration":
            if self.calibration is None or self.calibration.terminee:
                return {"accepted": False, "reason": "aucune calibration en cours"}
            self._commands.put(("cancel_calibration", {}))
            return {"accepted": True, "command": command,
                    "id": self.calibration.spec.id}
```

Dans `_apply`, ajouter :

```python
        elif command == "start_calibration":
            self._start_calibration(params["id"], params["params"])
        elif command == "cancel_calibration":
            if self.calibration is not None:
                self.calibration.cancel()
                print(f"[server] calibration abandonnée — aucun modèle produit")
```

Et la méthode, à placer après `_recalibrate` :

```python
    def _start_calibration(self, mode_id, values):
        """Construit la calibration. Appelée par la boucle, jamais par le fil d'une interface."""
        spec = registry.get(mode_id)
        self.calibration = spec.calibration.runtime_cls(spec, values, self)
        print(f"[server] {spec.calibration.label or spec.label} : "
              f"{self.calibration.total()} essais, "
              f"≈ {self.calibration.duree_estimee_s() / 60:.0f} min — "
              f"stabilisation {self.calibration.warmup_s:.0f} s d'abord")
```

- [ ] **Step 3: Le tick, dans la boucle**

Dans `run()`, juste APRÈS la boucle `for mode_id, runtime in list(self.active.items()):` :

```python
                    # La calibration tourne à CHAQUE tour, sans période minimale : sa ligne du
                    # temps se compte en dixièmes de seconde et un décompte qui saute serait vu.
                    if self.calibration is not None and not self.calibration.terminee:
                        self.calibration.tick(self, now)
```

- [ ] **Step 4: La phase publique et l'état**

Dans `_phase_of`, en TÊTE de la méthode :

```python
        # Une calibration en cours prime sur tout : c'est ce que la personne est en train de
        # faire, et les modes qui décodent en même temps sont secondaires. `calibrating` est une
        # valeur PUBLIQUE du flux `status` (spec §6) — un client peut s'en servir pour mettre son
        # application en pause pendant qu'on entraîne.
        if self.calibration is not None and not self.calibration.terminee:
            return "calibrating"
```

⚠️ `_phase_of` reçoit une COPIE de `self.active` mais lit `self.calibration` en direct. C'est sûr :
la référence est remplacée d'un bloc par la boucle, jamais mutée en place, et Python garantit
l'atomicité d'une lecture d'attribut.

Dans `_status_key`, ajouter la calibration au tuple pour que le flux `status` republie à chaque
changement de phase :

```python
        calib = self.calibration
        return (running, self.synthetic, self.phase,
                tuple((mid, r.phase, r.published) for mid, r in sorted(self.active.items())),
                None if calib is None else (calib.spec.id, calib.phase, calib.etape, calib.essai))
```

Dans `snapshot()`, ajouter à `state.update({...})` :

```python
            # `now` est passé pour que le décompte affiché soit celui de MAINTENANT, pas celui du
            # dernier tick. La console sonde à 10 Hz, le moteur tourne à sa propre cadence : sans
            # ça le décompte avancerait par à-coups.
            "calibration": (None if self.calibration is None
                            else self.calibration.state(now=time.perf_counter())),
```

- [ ] **Step 5: Nettoyer la calibration à l'arrêt**

Dans le `finally` de `run()`, juste avant `self.active = {}` :

```python
                # Une calibration en cours ne survit pas à l'arrêt du moteur : elle tient des
                # époques en mémoire et une référence vers `self` — le même cycle que les modes.
                if self.calibration is not None:
                    self.calibration.cancel()
                    self.calibration = None
```

- [ ] **Step 6: Écrire `_smoke_calibration()`**

À placer après `_smoke_mi()` dans `src/core/server.py`, et à brancher dans `_smoke()` comme les
autres (chercher comment `_smoke_mi` y est appelé et faire pareil).

```python
def _smoke_calibration():
    """Une calibration MI complète, jouée par le VRAI moteur sur board synthétique.

    Ce que ce test couvre et qu'aucun autre ne peut : la calibration tourne dans la boucle du
    moteur, prélève dans le tampon glissant RÉEL (donc éprouve le dimensionnement de `keep`), et
    produit un modèle que `modeles_disponibles` retrouve. L'autotest de `mi_calib.py`, lui, joue
    la même séance sur un faux moteur : il valide le protocole, pas l'intégration.

    Tout est écrit dans un dossier temporaire. Le vrai `data/` n'est jamais approché.
    """
    import shutil
    import tempfile
    import threading

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    from core.modes import mi_calib

    dossier = tempfile.mkdtemp(prefix="srv_calib_")
    # On raccourcit le protocole POUR LE TEST en remplaçant les durées sur la classe : c'est la
    # seule façon de jouer une séance de sept minutes en quelques secondes sans donner à
    # `CalibrationRuntime` une horloge accélérée, qui serait un chemin de code que la séance
    # réelle n'emprunte jamais.
    anciens = {c: getattr(mi_calib.MICalibration, c)
               for c in ("cue_s", "imagery_s", "rest_s", "warmup_s", "warmup_per_class",
                         "window_s", "step_s")}
    ancien_init = mi_calib.MICalibration.__init__

    def _init_temporaire(self, spec, params, engine, rng=None, dossier=dossier):
        ancien_init(self, spec, params, engine, rng=rng, dossier=dossier)

    try:
        # ⚠️ `window_s` et `step_s` sont raccourcis AVEC `imagery_s`, pas séparément : avec une
        # imagerie de 0,20 s et une fenêtre restée à 2 s, `decouper` ne rend AUCUNE fenêtre et
        # l'entraînement refuse. Le rapport est conservé — 0,20 / 0,10 / 0,05 donne 3 fenêtres
        # par essai, comme 4 / 2 / 1 en séance réelle.
        mi_calib.MICalibration.cue_s = 0.05
        mi_calib.MICalibration.imagery_s = 0.20
        mi_calib.MICalibration.rest_s = 0.05
        mi_calib.MICalibration.warmup_s = 0.10
        mi_calib.MICalibration.warmup_per_class = 1
        mi_calib.MICalibration.window_s = 0.10
        mi_calib.MICalibration.step_s = 0.05
        mi_calib.MICalibration.__init__ = _init_temporaire

        server = EngineServer(synthetic=True, modes=("raw",), instance="smoke-calib")
        thread = threading.Thread(target=server.run, kwargs={"duration_s": 30.0}, daemon=True)
        thread.start()
        try:
            # Laisser le tampon se remplir : sans ça les premières époques seraient trop courtes
            # et le moteur les ignorerait (il le dit, mais le test doit passer sans ce cas).
            # ⚠️ Attendre « non-None » ne suffit PAS : `recent_window` rend ce qu'elle a dès le
            # premier échantillon, sans dire qu'il en manque. On attend la LONGUEUR voulue.
            besoin_amorce = int(round(mi_calib.MICalibration.imagery_s * server.acq.fs))
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 10.0:
                bloc = server.recent_window(mi_calib.MICalibration.imagery_s)
                if bloc is not None and len(bloc) >= besoin_amorce:
                    break
                time.sleep(0.1)

            ack = server.submit("start_calibration", id="mi",
                                params={"trials_per_class": 6})
            chk(ack.get("accepted"), f"la calibration est acceptée ({ack})")

            # Une seconde calibration doit être refusée tant que la première tourne.
            t0 = time.perf_counter()
            while server.calibration is None and time.perf_counter() - t0 < 5.0:
                time.sleep(0.05)
            refus = server.submit("start_calibration", id="mi", params={})
            chk(not refus.get("accepted") and "déjà en cours" in (refus.get("reason") or ""),
                f"une seconde calibration est refusée ({refus})")
            chk(server.phase == "calibrating",
                f"la phase publique du moteur devient « calibrating » ({server.phase})")
            etat = server.snapshot().get("calibration")
            chk(etat is not None and etat["mode_id"] == "mi" and etat["total"] == 18,
                f"et snapshot() porte l'état complet ({etat})")

            t0 = time.perf_counter()
            while (server.calibration is not None and not server.calibration.terminee
                   and time.perf_counter() - t0 < 25.0):
                time.sleep(0.1)

            calib = server.calibration
            chk(calib is not None and calib.phase == "fini",
                f"la séance aboutit ({None if calib is None else calib.phase} ; "
                f"problème={None if calib is None else calib.probleme!r})")
            res = (calib.resultat if calib else None) or {}
            chk(res.get("n_essais") == 18, f"18 essais enregistrés ({res.get('n_essais')})")

            # Les époques prélevées dans le VRAI tampon glissant font la longueur annoncée.
            attendu = int(round(mi_calib.MICalibration.imagery_s * server.acq.fs))
            longueurs = {len(e) for e, _l in calib._enregistre}
            chk(longueurs == {attendu},
                f"chaque époque fait exactement {attendu} échantillons ({sorted(longueurs)})")

            # ⚠️ ET LE VRAI TEST DU DÉFAUT — celui-ci ne dépend PAS de la séance jouée, qui
            # tourne sur des durées rabotées. Le tampon du moteur doit tenir la plus longue
            # époque que le CONTRAT annonce (`Calib.epoch_s` = 4 s pour le MI), pas seulement la
            # fenêtre de décodage (2 s). Sans ce terme dans `keep`, chaque époque d'une séance
            # RÉELLE serait tronquée de moitié — sans erreur, avec un tiers des fenêtres
            # d'entraînement attendues. Deux vérifications, parce qu'aucune ne suffit seule :
            # le dimensionnement calculé, et le bloc réellement rendu.
            from core.config import MI_IMAGERY_S

            besoin = int(round(MI_IMAGERY_S * server.acq.fs))
            chk(server.keep >= besoin + server.acq.margin_n,
                f"le tampon du moteur tient une époque de calibration entière : keep="
                f"{server.keep} pour {besoin} + marge {server.acq.margin_n}")
            bloc = server.recent_window(MI_IMAGERY_S)
            chk(bloc is not None and len(bloc) == besoin,
                f"et il en rend une COMPLÈTE : {0 if bloc is None else len(bloc)} échantillons "
                f"pour {besoin} demandés")

            from core import mi_models

            produits = mi_models.modeles_disponibles(dossier)
            chk(len(produits) == 1 and produits[0] == res.get("modele"),
                f"le modèle produit est chargeable et listé ({produits})")
            chk(res.get("cv_groupee") is not None and res["cv_groupee"] < res["cv_naive"],
                f"l'accuracy rapportée est l'HONNÊTE, plus basse que la naïve "
                f"({res.get('cv_groupee')}, {res.get('cv_naive')})")

            # Et le mode MI peut alors démarrer sur ce modèle : c'est tout l'objet du chantier.
            demarrage = server.submit("start_mode", id="mi",
                                      params={"mi": {"model": produits[0]}})
            chk(demarrage.get("accepted"),
                f"le mode MI démarre sur le modèle qui vient d'être entraîné ({demarrage})")
        finally:
            server.stop()
            thread.join(timeout=10.0)
    finally:
        mi_calib.MICalibration.__init__ = ancien_init
        for cle, valeur in anciens.items():
            setattr(mi_calib.MICalibration, cle, valeur)
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[smoke-calib] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok
```

⚠️ **Le `finally` de restauration doit être écrit AVANT le corps** (comme ci-dessus) : si une
assertion lève, les durées de classe resteraient rabotées pour tous les tests suivants du même
processus, et `_smoke_mi` décoderait sur un protocole faussé — un faux vert particulièrement
difficile à voir.

⚠️ **Aucun résidu dans `data/`** : vérifier après le smoke que `git status --short` est propre et
que `data/` ne contient aucun `mi_model_*` ni `mi_calib_*` daté d'aujourd'hui.

- [ ] **Step 7: Lancer**

Run: `python src/core/server.py --smoke`
Expected: `[smoke-calib] VERDICT : OK` parmi les autres, sortie 0.

- [ ] **Step 8: Vérifier l'absence de résidu**

```bash
git status --short
ls data/mi_model_* data/mi_calib_* 2>/dev/null
```
Expected: arbre propre ; aucun fichier nouveau dans `data/`.

- [ ] **Step 9: Non-régression**

Run, EN SÉRIE : `python src/console/app.py --smoke` · `python src/research/app.py --smoke`
Expected: sortie 0 pour les deux.

- [ ] **Step 10: Commit**

```bash
git add src/core/server.py
git commit -m "Let the engine own and play a calibration, start to finish"
```

---

### Task 5: Démarrer et arrêter un mode depuis la console

**Files:**
- Modify: `src/console/grid.py` (le bouton sur la tuile)
- Modify: `src/console/app.py` (le câblage + le smoke)

**Interfaces:**
- **Consomme** — `engine.submit("start_mode", id=..., params={...})` et
  `engine.submit("stop_mode", id=...)`, tous deux existants et validés côté moteur.
- **Produit** — `ModeTile.demarrer` / `ModeGrid.demarrer` : `Signal(str, bool)` (id, on).

**Pourquoi cette tâche est dans ce plan** : voir « Trois décisions », point 3. Sans elle, calibrer
puis décoder oblige à fermer et rouvrir la console — ce qui fait **saturer C3/Cz**, exactement les
voies que lit le Motor Imagery.

- [ ] **Step 1: Le bouton sur la tuile**

Dans `ModeTile.__init__` de `src/console/grid.py`, après la création de `self.bouton` :

```python
        # Démarrer / arrêter. Le moteur possède déjà les deux commandes et les valide (mode
        # inconnu, déjà démarré, réglages invalides) : la tuile ne fait que les poster. Elle
        # n'affiche AUCUN état déduit — c'est le prochain `snapshot()` qui dira ce qui s'est
        # réellement passé.
        self.demarrage = QPushButton("Démarrer")
        self.demarrage.clicked.connect(
            lambda: self.demarrer.emit(self.spec["id"], self._arrete))
```

Déclarer le signal à côté des deux autres :

```python
    demarrer = Signal(str, bool)     # (id, on) — on=True pour démarrer, False pour arrêter
```

Ajouter `self._arrete = True` dans `__init__` (avant la création du bouton), placer
`self.demarrage` dans le layout `bas` (avant `self.bouton`), et le cacher pour les modes que le
moteur ne sait pas faire, dans le bloc `if spec["status"] != "moteur":` existant :

```python
            self.demarrage.hide()
```

Dans `ModeTile.update_from`, tenir l'étiquette à jour — au DÉBUT de chaque branche :

```python
        if mode_state is None:
            self._arrete = True
            self.demarrage.setText("Démarrer")
            ...
```

et dans la branche « mode actif », après `self.publie.setEnabled(True)` :

```python
        self._arrete = False
        self.demarrage.setText("Arrêter")
```

- [ ] **Step 2: Relayer depuis la grille**

Dans `ModeGrid` : déclarer `demarrer = Signal(str, bool)` et, dans la boucle de construction,
`tuile.demarrer.connect(self.demarrer)`.

- [ ] **Step 3: Câbler dans la console**

Dans `Console.__init__` de `src/console/app.py`, après `self.grid.publier.connect(self._publier)` :

```python
        self.grid.demarrer.connect(self._demarrer)
```

Et la méthode, à côté de `_publier` :

```python
    def _demarrer(self, mode_id, on):
        """Démarrer ou arrêter un mode. Le moteur valide et refuse ; on affiche ce qu'il dit.

        Sans ce geste, produire un modèle par calibration puis l'utiliser obligerait à fermer et
        rouvrir la console (`--mode mi` au lancement) — or **les voies C3/Cz saturent à la
        réouverture** (redémarrage de l'amplificateur), et ce sont précisément celles que lit le
        Motor Imagery. Le parcours entier du chantier passait donc par le geste qui abîme le
        signal qu'il vient de calibrer.

        On n'envoie AUCUN réglage : le moteur applique les défauts du contrat, qui pour le MI
        désignent le modèle le plus récemment entraîné. Les changer se fait ensuite dans la page
        du mode, avec les refus en clair — c'est déjà là.
        """
        self.commande("start_mode", id=mode_id) if on else self.commande("stop_mode", id=mode_id)
```

- [ ] **Step 4: Le test, dans `_smoke()` de `console/app.py`**

Après le bloc qui exerce « publier » (la case à cocher), ajouter :

```python
    # Démarrer / arrêter de bout en bout : clic -> signal de la tuile -> signal de la grille ->
    # commande au moteur. Le bouton est CLIQUÉ, pas contourné : c'est la seule façon de prouver
    # que le lambda capture le bon identifiant et le bon sens.
    moteur_faux.commandes.clear()
    console.grid.tuiles["neuro"].demarrage.click()      # neuro est arrêté dans l'état factice
    chk(("start_mode", {"id": "neuro"}) in moteur_faux.commandes,
        f"un mode arrêté se DÉMARRE depuis sa tuile ({moteur_faux.commandes})")
    chk(console.grid.tuiles["ssvep"].demarrage.text() == "Arrêter",
        f"et un mode qui décode propose « Arrêter » "
        f"({console.grid.tuiles['ssvep'].demarrage.text()})")

    moteur_faux.commandes.clear()
    console.grid.tuiles["ssvep"].demarrage.click()
    chk(("stop_mode", {"id": "ssvep"}) in moteur_faux.commandes,
        f"et un mode démarré s'ARRÊTE ({moteur_faux.commandes})")

    # Les modes que le moteur ne sait pas faire n'ont PAS de bouton : il ne mènerait qu'à un refus.
    chk(all(t.demarrage.isHidden() for t in console.grid.tuiles.values()
            if t.spec["status"] != "moteur"),
        "les modes de l'appli pygame n'exposent aucun bouton de démarrage")
```

- [ ] **Step 5: Lancer**

Run: `python src/console/app.py --smoke`
Expected: `[console-smoke] VERDICT : OK`

- [ ] **Step 6: Commit**

```bash
git add src/console/grid.py src/console/app.py
git commit -m "Start and stop a mode from the console, instead of relaunching it"
```

---

### Task 6: La console — la page de calibration, les bips, la liste des modèles

**Files:**
- Create: `src/console/beeps.py`
- Create: `src/console/calib_page.py`
- Modify: `src/console/mode_page.py` (bouton « Calibrer », rafraîchir la liste des modèles)
- Modify: `src/console/params_form.py` (`set_choices`)
- Modify: `src/console/app.py` (la page dans la pile, la navigation, le smoke)

**Interfaces:**
- **Consomme** — `snapshot()["calibration"]` (T4), `spec["calibration"]` du catalogue (T1),
  les commandes `start_calibration` / `cancel_calibration` (T4), `mi_models.decrire` (existant).
- **Produit** — `CalibPage(spec, console)` avec `update_from(state)` et le signal `retour`.

**Règle de la console, rappelée parce que cette page est celle où il est le plus tentant de
l'enfreindre** : elle RESSORT `state["calibration"]` et ne calcule rien. Pas de décompte tenu par
un `QTimer` local, pas de phase déduite, pas de verdict recalculé. Le décompte, la classe, le
numéro d'essai, le verdict : tout vient du moteur.

- [ ] **Step 1: `src/console/beeps.py`**

```python
"""Les tops latéralisés de la calibration : oreille gauche, droite, ou les deux.

Le son est de la PRÉSENTATION, pas du protocole. Si l'audio manque — machine sans carte son,
session distante, pilote absent — la calibration se déroule quand même, et la page le DIT. Un
top silencieux qui ne s'annonce pas ferait croire à l'étudiant qu'il a raté le départ.

Pourquoi latéraliser : le côté est porté par l'oreille (gauche/droite) et le repos par la durée
(les deux oreilles, plus long). L'étudiant n'a donc rien à LIRE au moment où il doit commencer à
imaginer — lire déplace le regard et contamine la fenêtre enregistrée.
"""

import numpy as np

FREQ_HZ = 880.0
SR = 44100
DUREE_COTE_S = 0.18
DUREE_CENTRE_S = 0.40


def _onde(gauche, droite, duree):
    """Un top stéréo entrelacé, en int16. Fondu de 10 ms aux deux bouts (anti-clic)."""
    t = np.linspace(0, duree, int(SR * duree), endpoint=False)
    enveloppe = np.clip(np.minimum(t / 0.01, (duree - t) / 0.01), 0, 1)
    ton = (0.35 * np.sin(2 * np.pi * FREQ_HZ * t) * enveloppe * 32767).astype(np.int16)
    stereo = np.zeros((len(ton), 2), dtype=np.int16)
    if gauche:
        stereo[:, 0] = ton
    if droite:
        stereo[:, 1] = ton
    return stereo.tobytes()


class Beeps:
    """Les trois tops. `disponible` dit franchement si le son sortira."""

    def __init__(self):
        self.disponible = False
        self.raison = ""
        self._sinks = {}
        self._données = {}
        try:
            from PySide6.QtCore import QBuffer, QByteArray
            from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

            sortie = QMediaDevices.defaultAudioOutput()
            if sortie is None or sortie.isNull():
                self.raison = "aucune sortie audio sur cette machine"
                return
            fmt = QAudioFormat()
            fmt.setSampleRate(SR)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.Int16)
            for cle, (g, d, duree) in {
                    "GAUCHE": (True, False, DUREE_COTE_S),
                    "DROITE": (False, True, DUREE_COTE_S),
                    "REPOS": (True, True, DUREE_CENTRE_S)}.items():
                octets = QByteArray(_onde(g, d, duree))
                tampon = QBuffer()
                tampon.setData(octets)
                self._données[cle] = tampon
                self._sinks[cle] = QAudioSink(sortie, fmt)
            self.disponible = True
        except Exception as e:  # noqa: BLE001 - l'audio casse de mille façons, toutes équivalentes
            self.raison = f"{type(e).__name__} : {e}"

    def jouer(self, classe):
        """Joue le top de cette classe. Ne lève jamais : un son raté n'arrête pas une séance."""
        if not self.disponible:
            return
        try:
            from PySide6.QtCore import QIODevice

            sink, tampon = self._sinks.get(classe), self._données.get(classe)
            if sink is None or tampon is None:
                return
            sink.stop()
            tampon.close()
            tampon.open(QIODevice.ReadOnly)
            tampon.seek(0)
            sink.start(tampon)
        except Exception:  # noqa: BLE001
            pass
```

- [ ] **Step 2: `set_choices` dans `params_form.py`**

Ajouter à `ParamsForm` :

```python
    def set_choices(self, cle, choix, garder=True):
        """Recharge la liste d'un champ « choice » sans reconstruire le formulaire.

        Nécessaire parce qu'une calibration fait APPARAÎTRE un modèle : la liste résolue à
        l'ouverture de la page devient fausse à la seconde où la séance se termine, et
        reconstruire tout le formulaire perdrait la saisie en cours dans les autres champs.

        ⚠️ N'est PAS appelée à chaque rafraîchissement : résoudre les choix du réglage `model`
        lit le disque (`joblib.load` par fichier). Une version antérieure de ce projet a mis
        30 % d'un cœur sur le fil Qt en résolvant un catalogue dix fois par seconde. On appelle
        ceci sur ÉVÉNEMENT — entrée dans la page, fin d'une calibration.
        """
        champ = self.champs.get(cle)
        param = self._params_par_cle.get(cle)
        if champ is None or param is None or param["kind"] != "choice":
            return
        courant = champ.currentText()
        champ.blockSignals(True)
        champ.clear()
        champ.addItems([str(c) for c in choix])
        if garder and courant in [str(c) for c in choix]:
            champ.setCurrentText(courant)
        champ.blockSignals(False)
```

- [ ] **Step 3: `src/console/calib_page.py`**

Trois écrans dans une seule page, choisis par la phase reçue :

1. **Avant** (`state["calibration"]` absent ou terminé) — le briefing du contrat, le formulaire de
   la calibration, la durée estimée, un bouton « Commencer ». Plus une ligne d'avertissement si
   l'audio manque.
2. **Pendant** — la consigne EN GRAND, la classe, le décompte, « essai *n* sur *N* », une barre de
   progression, un bouton « Abandonner ».
3. **Après** (`phase == "fini"`) — l'accuracy HONNÊTE, le niveau du hasard à côté, le verdict, le
   nom du modèle, et la phrase d'honnêteté (ci-dessous). Ou, si `phase == "annule"`, le problème.

```python
"""La page de calibration : briefing, déroulé, résultat. Elle ne décide de RIEN.

Tout ce qu'elle affiche vient de `snapshot()["calibration"]` : la phase, la consigne, la classe
cuée, le décompte, le numéro d'essai, le verdict. Aucun `QTimer` local ne tient de décompte, aucune
phase n'est déduite. C'est la règle de la console (« aucune logique que le moteur ne possède
déjà »), et ici elle a une raison de plus : le minutage d'une calibration est le protocole. Deux
horloges qui divergent donneraient un écran qui ment sur ce que le moteur enregistre vraiment.
"""
```

Points à respecter, dans l'ordre d'importance :

- **La phrase d'honnêteté, toujours affichée avec le résultat**, quelle que soit l'accuracy :

  ```python
  HONNETETE = (
      "Ce chiffre est une validation croisée PAR ESSAI : il estime ce que le modèle fera sur un "
      "essai qu'il n'a jamais vu. C'est plus bas — et plus vrai — que ce qu'affichait l'ancien "
      "écran de calibration, qui mélangeait des fenêtres d'un même essai entre apprentissage et "
      "test et se gonflait ainsi de 10 à 16 points.\n"
      "Repère : sur la seule séance de référence du projet, mesurée honnêtement, 40 % à 3 classes "
      "(pas significatif) et 63 % à 2 classes. Le Motor Imagery ne marche pas également bien chez "
      "tout le monde, et une séance modeste est un résultat ordinaire, pas une faute."
  )
  ```
- **Le niveau du hasard à côté de l'accuracy**, toujours : `f"{cv*100:.1f} % (hasard {h*100:.0f} %)"`.
  Un 40 % ne veut rien dire sans lui.
- **Le décompte** vient de `state["calibration"]["restant_s"]`, jamais d'un timer local.
- **Le bouton « Commencer »** émet `start_calibration` avec `params=self.formulaire.values()`.
- **Le bouton « Abandonner »** émet `cancel_calibration`. Il doit exister pendant TOUTE la séance :
  un étudiant qui a mal placé une électrode doit pouvoir sortir sans tuer la console.
- **Les tops** : jouer `beeps.jouer(classe)` quand `(phase, essai, etape)` passe à `etape == "cue"`
  pour un essai qu'on n'a pas encore sonné. Retenir la dernière clé jouée ; ne jamais rejouer sur
  un simple rafraîchissement (la page est mise à jour 10 fois par seconde).
- **`isEnabled` du formulaire** : désactivé pendant la séance, réactivé après. Changer la durée en
  cours de route n'aurait aucun effet, et un champ actif sans effet est un mensonge.
- Le signal `retour` ramène à la grille, comme `ModePage`.

- [ ] **Step 4: Le bouton « Calibrer » sur la page de mode**

Dans `ModePage.__init__` de `src/console/mode_page.py`, dans l'entête, avant `entete.addStretch(1)` :

```python
        # Le bouton n'existe que si le CONTRAT dit que ce mode se calibre depuis la console. Rien
        # ici ne sait qu'un MI s'entraîne et qu'un SSVEP non : c'est `Calib.kind` qui le dit.
        calib = spec.get("calibration") or {}
        self.bouton_calibrer = None
        if calib.get("kind") == "console":
            self.bouton_calibrer = QPushButton("Calibrer")
            self.bouton_calibrer.clicked.connect(
                lambda: console.show_calibration(self.mode_id))
            entete.addWidget(self.bouton_calibrer)
```

Et, à la fin de `ModePage`, une méthode pour recharger la liste des modèles :

```python
    def rafraichir_choix(self):
        """Recharge les listes de choix DYNAMIQUES de ce mode (les modèles entraînés).

        Appelée sur ÉVÉNEMENT — entrée dans la page, retour d'une calibration — jamais dans le
        rafraîchissement périodique : résoudre ces choix lit le disque, et le faire dix fois par
        seconde a déjà coûté 30 % d'un cœur à ce projet.
        """
        spec = registry.get(self.mode_id)
        if spec is None:
            return
        for param in spec.params:
            if param.choices_fn is not None:
                self.formulaire.set_choices(param.key, param.choices_now())
```

- [ ] **Step 5: Câbler dans `console/app.py`**

Dans `Console.__init__`, après la boucle qui crée les `ModePage` :

```python
        # Une page de calibration par mode qui se calibre DEPUIS la console. Les autres (c-VEP,
        # P300 : stimulus verrouillé à la frame) n'en ont pas — leur contrat le dit, et le moteur
        # refuserait la commande de toute façon.
        self.beeps = Beeps()
        self.calib_pages = {}
        for spec in registry.catalog():
            calib = spec.get("calibration") or {}
            if calib.get("kind") != "console" or spec["status"] != "moteur":
                continue
            page = CalibPage(spec, self)
            page.retour.connect(self.show_grid)
            self.calib_pages[spec["id"]] = page
            self.stack.addWidget(page)
```

Et les deux méthodes de navigation :

```python
    def show_calibration(self, mode_id):
        page = self.calib_pages.get(mode_id)
        if page is not None:
            self.stack.setCurrentWidget(page)

    def show_mode(self, mode_id):
        page = self.pages.get(mode_id)
        if page is not None:
            # Entrer dans la page est l'événement qui justifie de relire le disque : c'est là
            # qu'un modèle fraîchement entraîné doit apparaître dans la liste.
            page.rafraichir_choix()
            self.stack.setCurrentWidget(page)
```

⚠️ `apply_state` ne met à jour que `self.stack.currentWidget()`. Vérifier que la page de
calibration en bénéficie : elle est bien dans la pile, donc `currentWidget()` la désigne quand elle
est affichée. Ne pas mettre à jour toutes les pages — c'était déjà le choix, pour la même raison de
coût.

Ajouter `"calibration": None` à `fake_state()` (l'état factice doit couvrir la nouvelle clé), et
les imports en tête : `from console.beeps import Beeps` · `from console.calib_page import CalibPage`.

- [ ] **Step 6: Le test, dans `_smoke()` de `console/app.py`**

À placer après le bloc Motor Imagery existant :

```python
    # --- la page de calibration -------------------------------------------------
    # Elle est éprouvée sur des états FABRIQUÉS, phase par phase : c'est le seul moyen de
    # vérifier chaque écran sans jouer sept minutes de séance.
    console.show_calibration("mi")
    cal = console.stack.currentWidget()
    chk(cal is console.calib_pages["mi"], "« Calibrer » ouvre la page de calibration du MI")
    chk(len(console.calib_pages) == 1,
        f"et seul le MI en a une — le c-VEP et le P300 ont un stimulus natif "
        f"({sorted(console.calib_pages)})")

    # 1. Avant : le briefing du CONTRAT, pas un texte recopié dans l'interface.
    console.apply_state({**mi_state, "calibration": None})
    from core.modes import mi_calib
    chk(mi_calib.BRIEFING[0] in cal.briefing.text(),
        "le briefing affiché vient du contrat du mode")
    chk(cal.bouton_commencer.isEnabled(), "et « Commencer » est actif")

    moteur_faux.commandes.clear()
    cal.bouton_commencer.click()
    envoyees = [c for c in moteur_faux.commandes if c[0] == "start_calibration"]
    chk(envoyees and envoyees[0][1]["id"] == "mi"
        and "trials_per_class" in envoyees[0][1]["params"],
        f"cliquer « Commencer » soumet start_calibration avec la durée choisie ({envoyees})")

    # 2. Pendant : la consigne, la classe, le décompte, la progression — tous reçus, aucun calculé.
    en_cours = {**mi_state, "calibration": {
        "mode_id": "mi", "label": "Calibration Motor Imagery", "phase": "essais",
        "etape": "imagerie", "classe": "GAUCHE",
        "instruction": "Imagine : SERRE le POING GAUCHE", "rappel": "sens le serrement",
        "essai": 7, "total": 42, "restant_s": 2.4, "duree_estimee_s": 400.0,
        "params": {"trials_per_class": 14}, "classes": ["GAUCHE", "DROITE", "REPOS"],
        "resultat": None, "probleme": ""}}
    console.apply_state(en_cours)
    chk("SERRE le POING GAUCHE" in cal.consigne.text(),
        f"la consigne du moteur est affichée telle quelle ({cal.consigne.text()})")
    chk("2.4" in cal.decompte.text() or "2,4" in cal.decompte.text(),
        f"le décompte vient du moteur, pas d'un timer local ({cal.decompte.text()})")
    chk("7" in cal.progression.text() and "42" in cal.progression.text(),
        f"et la progression nomme les deux nombres ({cal.progression.text()})")
    chk(not cal.formulaire.isEnabled(),
        "le formulaire est verrouillé pendant la séance : le changer n'aurait aucun effet")

    moteur_faux.commandes.clear()
    cal.bouton_abandon.click()
    chk(("cancel_calibration", {}) in moteur_faux.commandes,
        f"« Abandonner » passe par la file de commandes ({moteur_faux.commandes})")

    # 3. Après : l'accuracy HONNÊTE, le hasard à côté, et la phrase qui dit ce que ça vaut.
    fini = {**mi_state, "calibration": {**en_cours["calibration"], "phase": "fini",
            "etape": "", "classe": "", "instruction": "", "restant_s": 0.0,
            "resultat": {"modele": "/tmp/mi_model_20260730-141205.joblib",
                         "nom": "mi_model_20260730-141205.joblib",
                         "enregistrement": "/tmp/mi_calib_20260730-141205_n42.npz",
                         "n_essais": 42, "n_fenetres": 126, "cv_groupee": 0.401,
                         "cv_naive": 0.556, "hasard": 1 / 3,
                         "classes": ["GAUCHE", "DROITE", "REPOS"],
                         "verdict": "FAIBLE — ré-essaie"}}}
    console.apply_state(fini)
    chk("40.1" in cal.resultat.text() or "40,1" in cal.resultat.text(),
        f"l'accuracy affichée est l'HONNÊTE ({cal.resultat.text()})")
    chk("55.6" not in cal.resultat.text() and "55,6" not in cal.resultat.text(),
        f"et JAMAIS la naïve, qui est gonflée de 10 à 16 points ({cal.resultat.text()})")
    chk("33" in cal.resultat.text(),
        f"le niveau du hasard est à côté — sans lui, 40 % ne veut rien dire ({cal.resultat.text()})")
    chk("mi_model_20260730-141205.joblib" in cal.details.text(),
        f"le nom du modèle produit est donné ({cal.details.text()})")
    chk("séance de référence" in cal.honnetete.text(),
        "et la page dit franchement ce qu'un résultat modeste signifie")

    # 4. Abandon : pas de modèle, et la raison.
    annule = {**mi_state, "calibration": {**en_cours["calibration"], "phase": "annule",
              "resultat": None, "probleme": "ValueError : pas assez de données"}}
    console.apply_state(annule)
    chk("pas assez de données" in cal.resultat.text(),
        f"une calibration annulée dit pourquoi ({cal.resultat.text()})")

    cal.bouton_retour.click()
    chk(console.stack.currentWidget() is console.grid,
        "et la page de calibration ramène sur la grille")
```

- [ ] **Step 7: Lancer**

Run: `python src/console/app.py --smoke`
Expected: `[console-smoke] VERDICT : OK`

- [ ] **Step 8: REGARDER la console, en vrai**

C'est la seule étape de ce plan qui demande un écran. Elle est **obligatoire** : la console n'a
**jamais été ouverte en fenêtre** de tout le projet, tout a été vérifié en Qt `offscreen`.

```bash
python src/console/app.py --synthetic
```

Vérifier de ses yeux : la tuile MI porte « Démarrer » ; sa page porte « Calibrer » ; le briefing
est lisible ; « Commencer » lance une séance dont le décompte avance ; « Abandonner » sort ; les
tops se font entendre (ou la page dit que l'audio manque). **Ne pas laisser tourner** cette console
avant de relancer un test.

- [ ] **Step 9: Commit**

```bash
git add src/console/beeps.py src/console/calib_page.py src/console/mode_page.py src/console/params_form.py src/console/app.py
git commit -m "Give the console a calibration page: brief, run, honest result"
```

---

### Task 7: L'archivage et la documentation

**Files:**
- Create: `archive/README.md`
- Move: `src/research/mi_calibrate.py` → `archive/mi_calibrate.py`
- Move: `src/research/mi_pilot.py` → `archive/mi_pilot.py`
- Modify: `src/research/app.py` (6 modes → 5)
- Modify: `src/core/mi_decoder.py` (deux renvois de docstring devenus faux)
- Modify: `CLAUDE.md`, `README.md`, `docs/SPEC.md`, `docs/recette.md`

**Interfaces:** aucune. Cette tâche ne change aucun comportement du moteur.

**⚠️ Cette tâche est la DERNIÈRE.** Tant que la console ne sait pas calibrer, l'écran pygame est le
seul moyen de produire un modèle (spec §9). Ne pas la commencer avant que la tâche 6 soit verte.

- [ ] **Step 1: Créer l'archive et déplacer**

```bash
mkdir archive
git mv src/research/mi_calibrate.py archive/mi_calibrate.py
git mv src/research/mi_pilot.py archive/mi_pilot.py
```

- [ ] **Step 2: `archive/README.md`**

```markdown
# archive/ — what this is, and what it is not

These files are **not maintained** and **not covered by the automated tests**. They are kept
because they are the reference the current implementation was checked against: running the old
Motor Imagery calibration side by side with the engine's own, and comparing timing, labels and
recorded epochs, is a real test — and it only exists as long as both exist.

"Git keeps the history" is true but weak: nobody goes looking in the history for a file they don't
know exists.

| File | What it was |
|---|---|
| `mi_calibrate.py` | The pygame Motor Imagery calibration. Replaced by the engine's own (`src/core/modes/mi_calib.py`), which measures a **honest** accuracy and never overwrites a recording. ⚠️ The accuracy this screen prints is inflated by 10 to 16 points. |
| `mi_pilot.py` | The pygame MI pilot: sliding vote over decoded windows, feedback screen, robot output. Its vote is now `MIRuntime` in `src/core/modes/mi.py`. |

Each file keeps its `--smoke`, which is how you check by hand that it still runs, the day you need
it:

```bash
python archive/mi_calibrate.py --smoke
python archive/mi_pilot.py --smoke
```

They write to `data/` under the **old, fixed** names (`mi_model.joblib`,
`mi_calib_last.npz`) — so an archived calibration **overwrites** the previous one. That is one of
the two defects the engine's calibration fixed; it is left here on purpose, so the archive stays
what it was.
```

- [ ] **Step 3: Faire tourner les deux fichiers archivés**

Deux retouches par fichier (vérifiées dans le code, spec §9) :

1. Le `sys.path.insert` remonte d'un cran de trop depuis `archive/`. Remplacer
   `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` par un chemin qui vise
   explicitement `<dépôt>/src` :
   ```python
   sys.path.insert(0, os.path.join(
       os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
   ```
2. Tout `from research.X import ...` devient `from core.X import ...` là où le module a déménagé
   (vérifier avec `grep -n "^from research\|^import research" archive/*.py`). `mi_pilot.py` importe
   `research.mi_calibrate` : les deux étant dans `archive/`, l'import devient `import mi_calibrate`
   (même dossier) — vérifier que `archive/` est bien sur `sys.path` (il l'est : c'est le dossier du
   script).

Run: `python archive/mi_calibrate.py --smoke` puis `python archive/mi_pilot.py --smoke`
Expected: les deux en sortie 0.

⚠️ Ces deux smokes écrivent dans le vrai `data/`. Vérifier `git status --short` après (rien ne doit
apparaître — `data/` est gitignoré) et **ne pas s'inquiéter** d'un `mi_model.joblib` écrasé : il
n'est plus lu par rien (`mi_models.charger` refuse les modèles hérités, et la console ne propose
que ce qui se charge).

- [ ] **Step 4: L'appli pygame passe de 6 à 5 modes**

Dans `src/research/app.py` :
- retirer `mode_mi` du menu et sa fonction (lignes ~424-…), avec ses imports `MIDecoder`,
  `MIModel`, `research.mi_pilot.MIController` ;
- retirer l'entrée de calibration MI (`import research.mi_calibrate as mi_calibrate`, ~ligne 1067)
  du menu des calibrations ;
- retirer la ligne d'état `mi = "oui" if os.path.exists(MI_MODEL_PATH) else "absent"` (~1109) et
  son affichage ;
- retirer `from research.mi_pilot import _dummy_model` et l'écriture de `mi_path` du `--smoke`
  (~1388, ~1412) ;
- retirer `MI_KEY_CHANNELS` / `MI_MODEL_PATH` de l'import de `core.config` **s'ils ne servent plus
  ailleurs dans le fichier** (vérifier par `grep`).

Le menu doit annoncer **5 modes**. Chercher toute chaîne « 6 modes » dans le fichier.

Run: `python src/research/app.py --smoke`
Expected: sortie 0, et le compte de modes du smoke passé de 6 à 5.

- [ ] **Step 5: Les renvois devenus faux dans `core/`**

Dans `src/core/mi_decoder.py` :
- ligne 5 : `[src/research/mi_calibrate.py]` → `[src/core/modes/mi_calib.py]` ;
- ligne ~190 (docstring de `MIDecoder.classify`) : la phrase « reste utilisée par l'appli pygame
  (`research/app.py`, `mi_pilot.py`) » devient fausse — l'appli n'a plus de MI. La remplacer par :
  « n'est plus utilisée que par `archive/mi_pilot.py`. Le moteur, lui, passe par `scores()` : voir
  `core/modes/mi.py`. » ;
- ligne 1 et 38 : le vocabulaire d'ACTIONNEUR (« 2 commandes », « stop » fiable, `MI_CONTROL`)
  contredit la règle « intention neutre, jamais une commande » du produit. Reformuler les
  commentaires. **Ne pas renommer `MI_CONTROL`** : `archive/mi_pilot.py` l'importe.

Même vérification dans `src/core/config.py:238` (« proba mini pour émettre une commande (sinon
None = stop) »).

- [ ] **Step 6: La documentation**

| Fichier | Ce qui devient faux, et ce qu'il faut écrire |
|---|---|
| `CLAUDE.md` | « menu à 6 modes » → **5** ; « seul accès aux 3 modes… c-VEP, P300, ErrP » (le MI n'y est plus) ; retirer `python src/research/mi_calibrate.py` des commandes utiles et le remplacer par « la calibration MI se lance depuis la console » ; retirer la mention « la calibration MI vit encore dans l'appli pygame — c'est la moitié B du chantier 3 » ; ajouter `python src/core/modes/calibration.py` et `python src/core/modes/mi_calib.py` aux gardes MI (à côté des trois existants). |
| `README.md` | ligne ~94 : « Train one with `python src/research/mi_calibrate.py` » → la console ; ligne ~230 : retirer `mi_calibrate` du tableau des calibrations ; décrire la page de calibration et le bouton Démarrer/Arrêter. |
| `docs/SPEC.md` | §14 (roadmap) : le chantier 3 est TERMINÉ, ses deux moitiés ; la calibration est possédée par le moteur, ce qui rend l'évolution F2 (« calibration pilotée par l'app ») atteignable — sans la livrer. |
| `docs/recette.md` | mettre à jour le **test 2.6** : la calibration se lance depuis la console, l'accuracy affichée est l'honnête (dire quoi attendre : **≈ 40 % à 3 classes est NORMAL**), et ne plus dire de lancer `mi_calibrate.py`. Ajouter au **niveau 0** les deux nouveaux autotests. Ajouter un test « démarrer/arrêter un mode depuis la grille ». La tuile MI n'est plus grisée nulle part. |

- [ ] **Step 7: Le jeu complet, EN SÉRIE**

```bash
python src/core/modes/contract.py
python src/core/modes/calibration.py
python src/core/modes/mi_calib.py
python src/core/mi_decoder.py
python src/core/mi_models.py
python src/core/modes/mi.py
python src/core/acquisition.py --synthetic
python src/core/server.py --smoke
python src/console/app.py --smoke
python src/research/app.py --smoke
python archive/mi_calibrate.py --smoke
python archive/mi_pilot.py --smoke
```
Expected: les douze en sortie 0.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Retire the pygame MI screens to archive/, and say so everywhere"
```

---

## Ce qui reste DEHORS de ce plan

À dire en annonçant le chantier fini, pas à découvrir après.

**Parké de la moitié A, non repris ici** (les trois autres l'ont été, en T2) :

- **L'égalité du vote est tranchée par ordre d'apparition**, donc publie l'intention la plus
  ANCIENNE au moment précis où l'utilisateur bascule. Inatteignable aux réglages par défaut
  (3 + 3 > 5), atteignable dès `vote_len ≥ 6` — qui est dans la plage du curseur.
- **Un `None` majoritaire écrase une classe qui atteint pourtant `min_votes`.** L'aide du réglage
  ne le dit pas.
- **Aucun rejet d'artefact sur le MI**, contrairement au SSVEP. Le CSP lit précisément la variance
  8-30 Hz que l'EMG fait exploser : un vrai serrement de main produira une intention confiante.
- **`rest_index` vaut `-1` sur un modèle à deux classes**, donc collisionne avec
  `no_decision_index`. La calibration produit toujours trois classes, donc c'est hors d'atteinte
  aujourd'hui — mais ça le redeviendrait si on offrait une séance à deux classes.

**Décidé pendant l'écriture de ce plan :**

- **Aucun test de permutation à la fin d'une calibration.** Il donnerait la seule réponse
  vraiment honnête (« ce score est-il distinguable du hasard ? ») mais coûte quelques secondes de
  plus au moment où l'étudiant attend son résultat. La page dit à la place ce que valent les
  chiffres de référence du projet et leur significativité. À reprendre le jour où on voudra un
  verdict et pas seulement un repère.
- **La calibration ne reprend pas une séance abandonnée.** Un modèle entraîné sur cinq essais ne
  se distingue pas d'un modèle complet dans la liste, et donnerait des probabilités plausibles et
  fausses. L'écran pygame, lui, entraînait sur ce qui restait.
- **Aucune migration des `mi_calib_last.npz` existants.** Décision d'exploitation déjà prise le
  2026-07-30 : les modèles hérités sont abandonnés, `mi_models.charger` les refuse explicitement.

**Hors périmètre, comme en moitié A :** c-VEP, P300 et ErrP restent accessibles seulement par
l'appli pygame — le P300 et l'ErrP attendent les **marqueurs entrants**, le c-VEP un stimulus
verrouillé à la frame. La calibration pilotée par une app extérieure (F2) est rendue possible par
ce chantier, pas livrée. Le contrôle à distance d'une calibration depuis un client LSL non plus.

**Jamais vérifié au casque.** Tout ce chantier se code et se teste sans matériel. Sa recette
matérielle est le test 2.6 de [`docs/recette.md`](../../recette.md), mis à jour en tâche 7.
