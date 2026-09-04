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

