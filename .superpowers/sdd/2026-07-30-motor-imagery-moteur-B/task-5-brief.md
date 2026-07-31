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

