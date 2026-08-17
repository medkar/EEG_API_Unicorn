## Task 2: Le tampon d'horodatages, et `keep` dimensionné nommément

**Files:**
- Modify: `src/core/modes/contract.py` (champ `marker_epoch_s` sur `ModeSpec`)
- Modify: `src/core/server.py` (tampon `recent_ts`, calcul de `keep`, smoke)

**Interfaces:**
- Consumes: `MARKER_LATE_S` (Task 1).
- Produces: `EngineServer.recent_ts` (numpy 1-D, même longueur que `recent`, en temps LSL) ; `ModeSpec.marker_epoch_s: float = 0.0`.

**Contexte que l'implémenteur ne peut pas deviner :** `self.acq.get_new_data()` rend DÉJÀ `(eeg (n,8), ts (n,))` — un horodatage **par échantillon**, en temps Unix. [server.py:854](../../../src/core/server.py#L854) empile `eeg` et **jette `ts`**. Il n'y a donc rien à aller chercher : il faut cesser de jeter.

- [ ] **Step 1: Ajouter le champ au contrat**

Dans `src/core/modes/contract.py`, classe `ModeSpec`, juste après `channels_fn` :

```python
    marker_epoch_s: float = 0.0   # tranche prélevée autour d'un marqueur (pré + post), 0 = ce
                                  # mode n'écoute pas les marqueurs. Dimensionne le tampon du
                                  # moteur : sous-dimensionné, CHAQUE époque serait tronquée en
                                  # silence — le décodeur recevrait moins de signal que le
                                  # contrat n'en annonce, sans la moindre erreur.
```

- [ ] **Step 2: Écrire l'assertion de dimensionnement dans le smoke, AVANT de coder**

Dans `src/core/server.py`, ajouter cette fonction et l'appeler depuis `_smoke()` :

```python
def _smoke_dimensionnement():
    """`keep` couvre-t-il l'époque du mode le plus gourmand EN MARQUEURS, retard compris ?

    ⚠️ Assertion DIRECTE sur `server.keep`, et c'est délibéré. Observer qu'une époque « sort »
    ne prouve RIEN : un tampon sous-dimensionné rend quand même ce qu'on lui demande, juste
    plus court. Ce piège a déjà été rencontré au chantier 3B, sur la calibration MI.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    srv = EngineServer(synthetic=True, modes=(), params={})
    besoin = max([spec.marker_epoch_s for spec in registry.MODES] or [0.0])
    attendu = int(round((besoin + MARKER_LATE_S) * srv.acq.fs))
    chk(srv.keep >= attendu,
        f"keep={srv.keep} couvre l'époque du marqueur ({besoin:g} s) plus le retard toléré "
        f"({MARKER_LATE_S:g} s) = {attendu} échantillons")
    print(f"[smoke-dimensionnement] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok
```

⚠️ **L'assertion est une IMPLICATION, volontairement.** Tant qu'aucun mode ne déclare
`marker_epoch_s`, `besoin` vaut 0 et elle passe — trivialement. Elle devient contraignante à la
tâche 5, quand le P300 déclare 0,95 s. C'est ce qui permet à la suite de rester **verte de bout en
bout** : une assertion qui resterait rouge pendant trois tâches apprendrait surtout à ne plus
regarder les échecs.

La tâche 5 ajoutera l'assertion stricte qui manque ici — « au moins un mode déclare une époque ».

- [ ] **Step 3: Obtenir la preuve ROUGE par une mutation temporaire**

Une implication vacuellement vraie ne prouve rien. Il faut donc la rendre contraignante le temps
d'un essai. Dans `src/core/modes/raw.py`, ajouter temporairement `marker_epoch_s=3.0` au `SPEC` :

Run: `python src/core/server.py --smoke`
Expected: **ÉCHEC** sur `[smoke-dimensionnement]` — `keep` ne couvre pas 3,0 + 1,0 = 4,0 s.

Puis appliquer l'étape 4, relancer, et vérifier que l'assertion passe **avec la mutation encore en
place**. Enfin **retirer la mutation** et relancer une dernière fois.

> Coller les trois sorties dans le rapport de tâche. Sans ce rouge, on ne saurait pas si le vert
> final prouve quoi que ce soit — et une assertion sur un `max()` de liste vide est précisément le
> genre de test qui passe pour de mauvaises raisons.

- [ ] **Step 4: Dimensionner `keep` nommément**

Dans `src/core/server.py`, remplacer le calcul de `self.keep` ([lignes 144-148](../../../src/core/server.py#L144-L148)) par :

```python
        # L'époque prélevée autour d'un marqueur, plus le retard qu'on tolère pour ce marqueur.
        # ⚠️ Ce besoin doit être NOMMÉ ici. Les 2 s qui suffisaient jusqu'ici venaient de
        # `QUALITY_WINDOW_S` et `MI_WINDOW_S` : personne ne pense à les protéger, et les baisser
        # un jour tronquerait CHAQUE époque P300 en silence.
        #
        # ⚠️ À ne pas confondre avec le filtre juste au-dessus : l'`epoch_s` d'une calibration
        # NATIVE ne dimensionne rien, parce que le moteur ne joue jamais ces calibrations. Ici
        # c'est l'époque du RUNTIME, que le moteur prélève lui-même à chaque marqueur.
        epoque_marqueur = max([spec.marker_epoch_s for spec in registry.MODES] or [0.0])
        self.keep = max(int(QUALITY_WINDOW_S * self.acq.fs),
                        int(NEURO_WINDOW_S * self.acq.fs),
                        int(MI_WINDOW_S * self.acq.fs),
                        int(epoque_calib * self.acq.fs),
                        int(round((epoque_marqueur + MARKER_LATE_S) * self.acq.fs)),
                        self.acq.window_n) + self.acq.margin_n
```

- [ ] **Step 5: Tenir le tampon d'horodatages en phase avec `recent`**

Dans `__init__`, à côté de `self.recent = np.zeros((0, len(CH_NAMES)))` :

```python
        # Les horodatages des mêmes échantillons, en temps LSL. Sans eux on ne peut pas SITUER
        # un marqueur dans le tampon — c'est ce qui manquait pour épocher sur un événement
        # extérieur. Tenus rigoureusement en phase avec `recent` : même longueur, même troncature.
        self.recent_ts = np.zeros((0,))
```

Et dans la boucle, remplacer les deux lignes de [server.py:853-854](../../../src/core/server.py#L853-L854) par :

```python
                        ts_lsl = self.clock.to_lsl(ts_unix)
                        self.new_block = (eeg, ts_lsl)
                        self.recent = np.vstack([self.recent, eeg])[-self.keep:]
                        self.recent_ts = np.concatenate([self.recent_ts, ts_lsl])[-self.keep:]
```

- [ ] **Step 6: Ajouter au smoke la vérification que les deux tampons restent en phase**

```python
def _smoke_tampon_horodate():
    """Les deux tampons ont-ils toujours la même longueur, et le temps y avance-t-il ?

    Un décalage d'un seul échantillon entre `recent` et `recent_ts` déplace TOUTES les époques
    sans rien casser de visible : le décodeur reçoit du signal, de la bonne taille, pris au
    mauvais endroit.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    srv = EngineServer(synthetic=True, modes=(), params={})
    srv.run(duration_s=3.0)
    chk(len(srv.recent) == len(srv.recent_ts),
        f"les deux tampons ont la même longueur ({len(srv.recent)} et {len(srv.recent_ts)})")
    chk(len(srv.recent_ts) > 0, "et ils ne sont pas vides après 3 s d'acquisition")
    diffs = np.diff(srv.recent_ts)
    chk(bool(np.all(diffs > 0)), "le temps avance strictement, sans doublon ni retour en arrière")
    attendu = 1.0 / srv.acq.fs
    chk(bool(np.median(diffs) > 0.5 * attendu and np.median(diffs) < 2.0 * attendu),
        f"et la cadence médiane vaut ~1/fs ({np.median(diffs) * 1000:.2f} ms attendu "
        f"{attendu * 1000:.2f} ms)")
    print(f"[smoke-tampon] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok
```

- [ ] **Step 7: Lancer les trois smokes**

Run: `python src/core/server.py --smoke`
Expected: `[smoke-tampon] VERDICT : OK`. `[smoke-dimensionnement]` échoue encore sur son PREMIER `chk` (aucun mode ne déclare d'époque) — c'est attendu jusqu'à la tâche 5.

Run: `python src/core/modes/registry.py` et `python src/console/app.py --smoke`
Expected: `VERDICT : OK` pour les deux — le champ ajouté au contrat ne doit rien casser.

- [ ] **Step 8: Commit**

```bash
git add src/core/server.py src/core/modes/contract.py
git commit -m "Stop throwing away the sample timestamps the engine already receives"
```

---

