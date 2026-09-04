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
