## Task 2 : le mode dans le moteur — phase, états muets, décision

**Files:**
- Create: `src/core/modes/cvep.py`
- Modify: `src/core/config.py` (ajouter `CVEP_PEREMPTION_CYCLES = 3`)

**Interfaces:**
- Consumes: `core.cvep_code.build_targets`, `core.cvep_decoder.CVEPModel`/`CVEPDecoder` (tâche 1).
- Produces: `CVEPRuntime` (sous-classe de `ModeRuntime`), `SPEC` (`ModeSpec`), et la méthode
  `CVEPRuntime.phase_a(t_fin) -> int|None` que la tâche 5 teste.

- [ ] **Étape 1 : écrire le test de phase et ses trois états muets**

```python
    # La phase, et les TROIS états où il n'y a pas de phase utilisable. Chacun est une
    # panne muette s'il n'est pas traité : le mode continuerait de publier des scores
    # d'apparence honnête calculés sur une horloge fausse.
    rt = _runtime_de_test(code_len=63, refresh=60.0)

    chk(rt.phase_a(100.0) is None,
        "sans aucun marqueur reçu, il n'y a PAS de phase — et surtout pas 0, qui serait une "
        "position valide du code")

    rt.maj_reference(ts=100.0, refresh=60.0)
    chk(rt.phase_a(100.0) == 0, f"à l'instant du marqueur, la phase vaut 0 ({rt.phase_a(100.0)})")
    chk(rt.phase_a(100.0 + 10 / 60.0) == 10,
        f"dix frames plus tard, phase = 10 ({rt.phase_a(100.0 + 10 / 60.0)})")
    chk(rt.phase_a(100.0 + 63 / 60.0) == 0,
        "un cycle entier plus tard, la phase est REVENUE à 0 (modulo la longueur du code)")

    # Péremption : au-delà de CVEP_PEREMPTION_CYCLES, la référence ne vaut plus rien. Continuer
    # en roue libre est l'approche écartée par la spec : à 59,94 Hz réels contre 60 supposés,
    # l'erreur atteint 3,6 frames en une minute sur un code qui en fait 63.
    juste_avant = 100.0 + (CVEP_PEREMPTION_CYCLES * 63 / 60.0) - 0.01
    juste_apres = 100.0 + (CVEP_PEREMPTION_CYCLES * 63 / 60.0) + 0.01
    chk(rt.phase_a(juste_avant) is not None,
        "juste avant la péremption, la référence sert encore")
    chk(rt.phase_a(juste_apres) is None,
        "juste après, elle est PÉRIMÉE : on cesse de décoder au lieu de dériver en silence")
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

Lancer : `python src/core/modes/cvep.py`
Attendu : `ModuleNotFoundError` — le fichier n'existe pas.

- [ ] **Étape 3 : écrire le cœur du runtime**

```python
    def maj_reference(self, ts, refresh):
        """Un marqueur de cycle vient d'arriver : le code était à la frame 0 à l'instant `ts`."""
        self._ref_ts = float(ts)
        self._ref_refresh = float(refresh)

    def phase_a(self, t_fin):
        """Position dans le code à l'instant LSL `t_fin`, ou None s'il n'y a pas de phase.

        ⚠️ `None` et `0` sont deux choses DIFFÉRENTES : 0 est une position valide du code,
        None veut dire « je ne sais pas où j'en suis ». Les confondre ferait décoder sur une
        horloge fausse en publiant des corrélations d'apparence normale.
        """
        if self._ref_ts is None:
            return None
        age = float(t_fin) - self._ref_ts
        if age < 0.0 or age > CVEP_PEREMPTION_CYCLES * self.code_len / self._ref_refresh:
            return None
        return int(age * self._ref_refresh) % self.code_len
```

- [ ] **Étape 4 : écrire `SPEC`, sur le patron de `errp.py`**

`id="cvep"`, `label="c-VEP"`, `family="actif"`, `status="moteur"`,
`stream="decoded_cvep"`, `runtime_cls=CVEPRuntime`,
`marker_epoch_s = CVEP_DECISION_CYCLES * (2 ** CVEP_BITS - 1) / 60.0` (la fenêtre de décision,
2 × 63 / 60 = **2,1 s**). ⚠️ Ici ce champ **dimensionne le tampon du moteur, il ne décrit pas une
époque** — contrairement au P300 et à l'ErrP. Le dire en commentaire, sinon un lecteur cherchera
une époque qui n'existe pas,
`rest=Rest(warmup_s=SSVEP_WARMUP_S, duration_s=0.0, instruction="Le casque se stabilise — reste immobile.")`,
`calibration=Calib(kind="natif", reason="stimulus verrouillé à la frame", label="Calibrer", …)`.

- [ ] **Étape 5 : le refus sans modèle et le refus de rafraîchissement**

```python
        # ⚠️ Le modèle est calibré à UN rafraîchissement, et c'est l'ÉMETTEUR qui tient
        # l'écran — le moteur ne peut pas le voir. Sans cette garde : le décodage tourne, les
        # scores restent honnêtes, et RIEN ne se déclenche jamais. C'est la panne qui a coûté
        # une séance au SSVEP.
        if abs(refresh_declare - self.model.refresh) > 1.0:
            raise ValueError(
                f"l'émetteur affiche à {refresh_declare:.1f} Hz, le modèle a été calibré à "
                f"{self.model.refresh:.1f} Hz — recalibre, ou lance l'émetteur avec "
                f"--refresh {self.model.refresh:.0f}")
```

- [ ] **Étape 6 : lancer et prouver la mutation**

Lancer : `python src/core/modes/cvep.py` → vert.
Muter `return int(age * self._ref_refresh) % self.code_len` en `... + 1) % ...` → **rouge**.
Remettre, relancer, coller les deux sorties dans le rapport.

- [ ] **Étape 7 : commit**

```bash
git add src/core/modes/cvep.py src/core/config.py
git commit -m "Give the c-VEP a runtime that knows when it does not know the phase"
```

---

