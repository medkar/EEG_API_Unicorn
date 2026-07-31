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

