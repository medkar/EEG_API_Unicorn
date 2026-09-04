## Task 7 : les seuils réglables à chaud — la garde qui manque à l'ErrP

**Files:**
- Modify: `src/core/modes/cvep.py`, `src/core/modes/contract.py` (le commentaire du drapeau)

⚠️ **À FAIRE EN PREMIER, sinon cette tâche se contredit elle-même.** `contract.py` documente
aujourd'hui `affecte_decodage` par « **False = le décodeur ne le lit jamais** ». Or `corr_min` et
`margin` SONT lus par le décodeur, à chaque décision. Poser `False` dessus sans toucher au
commentaire écrirait un mensonge dans le contrat — et tout relecteur aurait raison de le signaler.

Le drapeau ne décrit pas *qui lit* le réglage, il décrit **si le changer exige de reconstruire le
runtime** (c'est ce que `server._set_params` en fait). Corriger le commentaire pour dire l'invariant
réel, et nommer la condition qui le rend vrai :

```python
    affecte_decodage: bool = True   # False = changer ce réglage n'exige PAS de reconstruire le
                                    # runtime (donc pas de flux recréé, pas de chauffe refaite).
                                    # ⚠️ Ce n'est PAS « le décodeur ne le lit jamais » : le c-VEP
                                    # lit `corr_min`/`margin` à CHAQUE décision, et c'est
                                    # justement ce qui rend `False` vrai chez lui. La condition à
                                    # respecter est donc : un réglage `False` ne doit jamais être
                                    # mis en cache dans `__init__`, sans quoi le changer n'aurait
                                    # plus aucun effet — en silence.
```

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

