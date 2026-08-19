## Task 5: L'émetteur d'exemple, et LE test d'alignement

**Files:**
- Créer : `src/research/errp_stimulus.py`
- Modifier : `src/core/modes/errp.py` (le test d'alignement dans son autotest)

**Ton modèle de forme :** `src/research/p300_stimulus.py`, livré la veille. Même patron : autonome, `--windowed`, `--smoke` sans écran, et **il n'ouvre PAS le casque** — c'est ce qui permet de le lancer en même temps que le moteur.

- [ ] **Step 1: Le stimulus — une piste, des erreurs délibérées**

Le protocole existe déjà dans le démonstrateur de `src/research/app.py` : un point sur une piste de `ERRP_TRACK_CELLS = 7` cases, qui avance vers une cible ; à chaque pas la machine se trompe **délibérément** avec la probabilité `ERRP_ERROR_RATE = 0.28`, et le feedback reste affiché `ERRP_FEEDBACK_S = 1.0` s.

Le geste critique, identique au P300 :

```python
        pygame.display.flip()
        # L'HORODATAGE SE PREND ICI, juste après que le feedback est À L'ÉCRAN. 40 ms d'avance
        # décalent toutes les époques de deux frames, et le décodeur moyenne une réponse qui n'a
        # pas encore eu lieu. Rien ne lève d'erreur ; les scores sortent, et ils sont du bruit.
        outlet.push_sample([json.dumps({"mode": "errp", "event": "feedback"})],
                           timestamp=local_clock())
```

- [ ] **Step 2: Le `--smoke` de l'émetteur**

⚠️ Il doit **exécuter `run()` pour de vrai** sur `SDL_VIDEODRIVER=dummy`, comme le fait `p300_stimulus.py` depuis sa correction. Un smoke qui retourne avant l'import de pygame laisse **sans aucune couverture** les lignes qui contiennent le geste flip→horodatage, c'est-à-dire la seule chose que ce fichier existe pour enseigner.

Il vérifie aussi que la séquence est bien formée : un `feedback` par pas, et un taux d'erreur proche de `ERRP_ERROR_RATE`.

- [ ] **Step 3: LE TEST D'ALIGNEMENT, par le CONTENU**

⚠️ **Écris-le d'emblée sous cette forme.** La revue du P300 a établi qu'une assertion de **position** laisse passer le double filtrage : `filtfilt` est à phase nulle, sa réponse impulsionnelle équivalente est une autocorrélation maximale au lag 0, donc un `bandpass()` ajouté par erreur **laisse le pic exactement au même échantillon**. Or `ErrPModel` filtre déjà en interne.

```python
    # Un pic d'amplitude unique planté à un instant CONNU, dans un tampon par ailleurs nul.
    fs = 250.0
    n_pre, n_post = int(round(ERRP_PRE_S * fs)), int(round(ERRP_EPOCH_S * fs))
    t0 = 1000.0
    ts = np.arange(t0, t0 + 4.0, 1.0 / fs)
    eeg = np.zeros((len(ts), 8))
    instant = t0 + 2.0
    i_pic = int(np.searchsorted(ts, instant))
    eeg[i_pic, :] = 42.0          # une valeur qu'aucun calcul ne produit par hasard

    moteur.recent, moteur.recent_ts = eeg, ts
    rt._traiter_feedback(moteur, instant, lsl_ts=instant)

    # UNE assertion qui épingle position, forme, ordre des voies ET absence de traitement.
    chk(np.array_equal(rt._derniere_epoque, eeg[i_pic - n_pre:i_pic + n_post]),
        "⚠️ ALIGNEMENT : l'époque constituée par le runtime est EXACTEMENT la tranche brute du "
        "tampon — même position, même forme, même ordre de voies, et AUCUN traitement appliqué "
        "en chemin (un filtrage ajouté ici laisserait le pic au même échantillon et passerait "
        "une assertion de position)")
```

Le runtime doit donc garder sa dernière époque (`self._derniere_epoque`) pour que le test puisse la lire.

- [ ] **Step 4: Preuve ROUGE-PUIS-VERT du test d'alignement**

Ajoute un `bandpass(epoque, engine.acq.fs)` dans `_traiter_feedback`, juste avant le scorage.

Run: `python src/core/modes/errp.py`
Expected: **ÉCHEC** sur l'assertion d'alignement, code de sortie **1**.

⚠️ **Vérifie et note dans le rapport que le pic reste au même échantillon** malgré le filtre : c'est la démonstration que seule l'égalité au contenu ferme ce trou. Retire le filtre, relance, colle le VERT.

- [ ] **Step 5: Lancer**

```bash
python src/research/errp_stimulus.py --smoke
python src/core/modes/errp.py
python src/research/app.py --smoke
python src/core/server.py --smoke
```

- [ ] **Step 6: Commit**

```bash
git add src/research/errp_stimulus.py src/core/modes/errp.py
git commit -m "Ship the ErrP stimulus, and pin the epoch by its content"
```

---

