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

