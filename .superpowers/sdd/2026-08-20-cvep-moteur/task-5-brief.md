## Task 5 : l'émetteur, et LE test qui porte le chantier

**Files:**
- Create: `src/research/cvep_stimulus.py`
- Modify: `src/research/__init__.py`

**Interfaces:**
- Consumes: `core.cvep_code.build_targets`, `core.cvep_code.is_on`,
  `core.modes.cvep.CVEPRuntime.phase_a` (pour le test).
- Produces: un exécutable `python src/research/cvep_stimulus.py [--windowed] [--refresh N]
  [--seconds N] [--seed N] [--no-wait] [--smoke]`.

Le patron est `src/research/errp_stimulus.py`, livré la semaine dernière : mêmes options, même
attente du moteur, même bilan de fin, et **le marqueur poussé APRÈS `pygame.display.flip()`**.

- [ ] **Étape 1 : écrire LE test de phase**

⚠️ **C'est le test qui porte le chantier.** Une erreur de phase ne casse rien : les corrélations
baissent, le mode continue de publier, les scores restent d'apparence honnête, et la détection se
contente de ne presque jamais se déclencher — indiscernable d'un étudiant qui ne fixe pas.

```python
    # On rejoue une course de rendu EN PUR : une frame toutes les 1/refresh s, un marqueur de
    # cycle à chaque frame 0, ET une frame SAUTÉE au milieu (le cas qui arrive vraiment). Pour
    # chaque frame on compare la phase que le MOTEUR reconstruirait à celle que l'émetteur a
    # RÉELLEMENT affichée.
    refresh, L, t0 = 60.0, 63, 1000.0
    rt = _runtime_de_test(code_len=L, refresh=refresh)
    ecarts, saut_fait = [], False
    frame = 0
    while frame < L * 8:
        t = t0 + frame / refresh
        if frame % L == 0:
            rt.maj_reference(ts=t, refresh=refresh)
        vue = rt.phase_a(t)
        ecarts.append(None if vue is None else (vue - frame % L + L // 2) % L - L // 2)
        if frame == L * 3 + 17 and not saut_fait:   # une frame sautée, une seule
            saut_fait, frame = True, frame + 1
        frame += 1

    pires = [abs(e) for e in ecarts if e is not None]
    chk(len(pires) == len(ecarts), "une phase est disponible à CHAQUE frame de la course")
    chk(max(pires) <= 1,
        f"l'écart entre la phase reconstruite et la phase AFFICHÉE ne dépasse jamais UNE frame "
        f"(pire écart mesuré : {max(pires)} frames, sur {len(pires)} frames)")
    chk(saut_fait and max(pires) <= 1,
        "...y compris après une frame sautée : le marqueur du cycle suivant RÉSORBE l'erreur "
        "au lieu de la laisser s'accumuler")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/research/cvep_stimulus.py --smoke`.

- [ ] **Étape 3 : écrire l'émetteur**

Le geste critique, identique aux deux émetteurs existants :

```python
        pygame.display.flip()
        # L'HORODATAGE SE PREND ICI, juste après que la frame est À L'ÉCRAN. Le prendre avant
        # décale TOUTES les phases d'une frame, et le décodeur cherche alors le code à un
        # endroit où il n'est pas — sans qu'aucune exception ne le signale.
        if frame % len(code) == 0:
            out.push_sample([json.dumps({"mode": "cvep", "event": "cycle",
                                         "refresh": refresh})], local_clock())
```

⚠️ **N'ouvre PAS le casque.** C'est ce qui permet de le lancer en même temps que le moteur.

- [ ] **Étape 4 : prouver le test rouge**

Décaler la phase d'une frame dans `phase_a` (`int(age * refresh) + 1`), relancer le smoke.
Attendu : **rouge**, sur l'assertion de l'écart. Retirer, relancer, coller les deux sorties.

- [ ] **Étape 5 : lancer les tests**

```bash
python src/research/cvep_stimulus.py --smoke
python src/research/app.py --smoke
```

- [ ] **Étape 6 : commit**

```bash
git add src/research/cvep_stimulus.py src/research/__init__.py
git commit -m "Ship the c-VEP emitter, and pin the phase to the frame that was shown"
```

---

