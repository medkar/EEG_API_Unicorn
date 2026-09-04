## Task 4 : le flux publié et les compteurs de diagnostic

**Files:**
- Modify: `src/core/lsl_io.py`, `src/core/modes/registry.py`, `src/core/modes/external.py`,
  `src/console/grid.py`, `src/console/live_views.py`

**Interfaces:**
- Produces: `core.lsl_io.cvep_channel_labels(n_targets) -> list[str]` =
  `["target_index", "confidence"] + [f"score_{i}" for i in range(n_targets)]` ;
  `DecodedCVEPPublisher(n_targets, decoder, refresh, code_len, corr_min, margin, cv, instance)`
  avec `.push(target_index, confidence, scores, lsl_ts)`.

- [ ] **Étape 1 : écrire le test des compteurs par cause**

```python
    # ⚠️ Les trois causes de « pas de décision » doivent être SÉPARÉES dans l'état. Une séance
    # casque coûte cher et ne se répète pas : « ça ne détecte pas » sans la cause ne permet pas
    # de distinguer une phase fausse d'un contact médiocre d'un étudiant qui ne fixe pas —
    # trois causes qui appellent trois gestes opposés.
    st = rt.state()
    chk(set(st) >= {"decodages", "sans_reference", "reference_perimee", "vote_non_conclu",
                    "age_reference_s", "corr_gagnant", "corr_second"},
        f"l'état sépare les trois causes de -1 et expose l'âge de la référence ({sorted(st)})")
    chk(st["sans_reference"] == 2 and st["reference_perimee"] == 1 and st["vote_non_conclu"] == 3,
        f"...et chaque compteur compte SA cause, pas le total ({st})")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/core/modes/cvep.py` → rouge (clés absentes).

- [ ] **Étape 3 : écrire le publieur et les compteurs**

Sur le patron de `DecodedP300Publisher`. Métadonnées obligatoires, sous `decoding/` :
`paradigm="c-VEP"`, `decision_scale="correlation"`, `no_decision_index="-1"`, `code_len`,
`refresh`, `n_targets`, `decoder`, `corr_min`, `margin`, `cv`.

- [ ] **Étape 4 : enregistrer le mode, retirer l'entrée « externe »**

Ajouter `cvep.SPEC` à `registry.MODES` ; retirer l'entrée c-VEP de `modes/external.py` ; dégriser la
tuile de la console.

⚠️ **La tuile ne doit pas mettre des corrélations à l'échelle du `Z_MIN` du SSVEP** — c'est le défaut
qui a survécu deux chantiers sur la tuile P300, corrigé la semaine dernière. Le c-VEP publie un
`corr_min` : la tuile doit s'en servir. **Ajouter une assertion sur `tuiles["cvep"].apercu`**, car
c'est l'absence d'assertion qui avait laissé passer le cas P300.

- [ ] **Étape 5 : écrire le test de BOUT EN BOUT synthétique**

⚠️ **Celui-ci prouve la chaîne entière**, là où le test de phase (tâche 5) ne prouve que l'horloge.
Sans lui, on saurait que la phase est juste sans savoir qu'elle est branchée au bon endroit.

`core.cvep_decoder.synth_cvep(code, lag, n_ch, fs, refresh, snr_db, rng, latency_s)` fabrique déjà un
cycle de c-VEP pour un lag donné — on s'en sert pour construire un tampon de plusieurs cycles.

```python
    # Chaîne complète, sans casque : un EEG synthétique portant le c-VEP de la cible 2, des
    # marqueurs de cycle aux bons instants, et le moteur doit désigner LA CIBLE 2. Le test de
    # phase dit que l'horloge est juste ; celui-ci dit qu'elle est branchée au bon endroit.
    plan, code = build_targets()
    cible = 2
    lag_vrai = plan[cible]["lag"]
    eeg, ts = _tampon_synthetique(code, lag_vrai, fs=250.0, refresh=60.0,
                                  n_cycles=6, snr_db=0.0, rng=np.random.default_rng(7))
    rt = _runtime_de_test(modele=_modele_appris_sur(code, lag_vrai), code_len=len(code))
    for k in range(6):                       # un marqueur par cycle, comme l'émetteur
        rt.maj_reference(ts=ts[0] + k * len(code) / 60.0, refresh=60.0)
    publie = rt.decider_sur(eeg, ts)

    chk(publie["target_index"] == cible,
        f"le moteur désigne la cible RÉELLEMENT affichée ({publie['target_index']} au lieu de "
        f"{cible}) — la phase est juste ET branchée au bon endroit")
    chk(publie["scores"][cible] == max(publie["scores"]),
        f"...et c'est bien elle qui porte la meilleure corrélation ({publie['scores']})")
```

- [ ] **Étape 6 : prouver la mutation de ce test**

Décaler d'un lag la table `lag_to_cmd` du décodeur (apparier la corrélation du lag *j* au nom de la
cible *j+1*) : le test doit **rougir** en désignant une cible voisine. C'est l'appariement
score↔cible, exactement le défaut que la revue du P300 avait trouvé sur son propre mode. Retirer,
relancer, coller les deux sorties.

- [ ] **Étape 7 : lancer**

```bash
python src/core/modes/cvep.py
python src/core/lsl_io.py
python src/core/modes/registry.py
python src/console/app.py --smoke
```

- [ ] **Étape 8 : commit**

```bash
git add src/core/lsl_io.py src/core/modes/ src/console/
git commit -m "Publish decoded_cvep, and prove the chain picks the target that was shown"
```

---

