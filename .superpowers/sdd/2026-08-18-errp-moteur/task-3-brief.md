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

