## Task 6: L'émetteur de stimulus, et LE test d'alignement

**Files:**
- Create: `src/research/p300_stimulus.py`
- Modify: `src/core/modes/p300.py` (ajouter le test d'alignement à son autotest)

**Interfaces:**
- Consumes: le contrat de marqueurs (Task 1), le mode P300 (Task 5).
- Produces: `python src/research/p300_stimulus.py [--windowed] [--reps N] [--targets N]`.

- [ ] **Step 1: Écrire LE test d'alignement, dans l'autotest de `modes/p300.py`**

⚠️ **C'est le seul test qui protège vraiment ce chantier.** Un décalage de quelques échantillons
rend tous les autres verts et décode du bruit avec une confiance de 0,92 — indiscernable d'un
succès. Il doit donc vérifier une **position**, pas une réussite.

```python
    # --- LE test d'alignement ------------------------------------------------
    # On fabrique un tampon plat, on y plante un pic d'amplitude unique à un instant CONNU, et
    # on envoie un marqueur à cet instant. L'époque extraite doit contenir ce pic exactement à
    # l'échantillon `n_pre` — c'est-à-dire à l'onset. Un décalage de 3 échantillons (12 ms) ne
    # change RIEN d'autre : l'époque a la bonne taille, le décodeur tourne, les scores sortent.
    fs = 250.0
    n_pre = int(round(P300_PRE_S * fs))       # 37
    n_post = int(round(P300_EPOCH_S * fs))    # 200
    t0 = 1000.0
    ts = np.arange(t0, t0 + 4.0, 1.0 / fs)
    eeg = np.zeros((len(ts), 8))
    instant_du_pic = t0 + 2.0
    i_pic = int(np.searchsorted(ts, instant_du_pic))
    eeg[i_pic, :] = 42.0                      # une valeur qu'aucun calcul ne produit par hasard

    epoque = epoch_from_stream(eeg, ts, instant_du_pic, fs,
                              pre_s=P300_PRE_S, post_s=P300_EPOCH_S)
    chk(epoque is not None, "l'époque est extraite")
    chk(epoque.shape == (n_pre + n_post, 8),
        f"elle a exactement pré+post échantillons ({epoque.shape})")
    position = int(np.argmax(epoque[:, 0]))
    chk(position == n_pre,
        f"⚠️ ALIGNEMENT : le pic planté à l'onset se retrouve à l'échantillon {position}, "
        f"il devait être à {n_pre} (décalage de {position - n_pre} échantillons = "
        f"{(position - n_pre) / fs * 1000:+.0f} ms)")
    chk(abs(epoque[n_pre, 0] - 42.0) < 1e-9,
        f"et c'est bien LA valeur plantée qu'on retrouve ({epoque[n_pre, 0]})")

    # Le même test, décalé d'une demi-période d'échantillonnage : un marqueur ne tombe jamais
    # pile sur un échantillon dans la vraie vie. On accepte 1 échantillon d'écart, pas plus.
    epoque = epoch_from_stream(eeg, ts, instant_du_pic + 0.002, fs,
                              pre_s=P300_PRE_S, post_s=P300_EPOCH_S)
    position = int(np.argmax(epoque[:, 0]))
    chk(abs(position - n_pre) <= 1,
        f"un marqueur entre deux échantillons reste aligné à ±1 ({position} vs {n_pre})")
```

- [ ] **Step 2: Lancer pour voir l'état actuel**

Run: `python src/core/modes/p300.py`
Expected: PASSE si la tâche 5 a bien câblé `engine.recent_ts` dans le bon ordre. **Si ce test échoue, ne pas le contourner** : c'est exactement le défaut qu'il existe pour attraper.

> **Preuve rouge exigée** : avant de conclure, casser volontairement l'alignement (remplacer
> `pre_s=P300_PRE_S` par `pre_s=0.0` dans `_encaisser_flash`) et vérifier que ce test **échoue**.
> Un test qui passe dans les deux cas ne prouve rien. Remettre la valeur ensuite.

- [ ] **Step 3: Écrire `src/research/p300_stimulus.py`**

Calqué sur `src/research/ssvep_stimulus.py`. Points obligatoires :

```python
"""Le stimulus P300, en programme AUTONOME qui publie ses marqueurs.

⚠️ **Ce programme n'ouvre PAS le casque.** C'est ce qui permet de le lancer EN MÊME TEMPS que le
moteur, dans deux terminaux — le même montage que pour le SSVEP :

    python src/core/server.py --mode p300          # terminal 1 : acquiert et décode
    python src/research/p300_stimulus.py           # terminal 2 : affiche et marque

C'est aussi l'exemple de référence pour qui voudra émettre depuis Unity : le protocole est ici,
et surtout l'endroit exact où prendre l'horodatage.
"""
```

Le geste critique, à écrire avec son commentaire :

```python
        pygame.display.flip()
        # ⚠️ L'HORODATAGE SE PREND ICI, juste après le basculement de frame — pas avant de
        # dessiner, pas au moment de décider quelle cible flasher. Une charge utile parfaite
        # envoyée 40 ms trop tôt décale TOUTES les époques d'une frame, et le décodeur corrèle
        # alors contre une réponse évoquée qui n'a pas encore eu lieu.
        outlet.push_sample([json.dumps({"mode": "p300", "event": "flash", "target": cible})],
                           timestamp=local_clock())
```

Et en fin de manche :

```python
    outlet.push_sample([json.dumps({"mode": "p300", "event": "round_end"})],
                       timestamp=local_clock())
```

Le flux publié :

```python
    info = StreamInfo(MARKER_STREAM_DEFAULT, "Markers", 1, IRREGULAR_RATE, "string",
                      f"p300-stim-{os.getpid()}")
    outlet = StreamOutlet(info)
```

- [ ] **Step 4: Ajouter un `--smoke` au stimulus**

Il doit tourner **sans écran** (aucune fenêtre ouverte) et vérifier que la séquence de marqueurs
est bien formée : autant de flashs que `reps × n_targets`, chaque cible vue `reps` fois, et un
`round_end` final. Aucun `pygame.display` dans ce chemin.

- [ ] **Step 5: Lancer**

```bash
python src/research/p300_stimulus.py --smoke
python src/core/modes/p300.py
python src/research/app.py --smoke
```

Expected: `VERDICT : OK` partout.

- [ ] **Step 6: Commit**

```bash
git add src/research/p300_stimulus.py src/core/modes/p300.py
git commit -m "Ship the stimulus emitter, and pin the alignment that everything rests on"
```

---

