## Task 2: Le mode — runtime, repos, rejet d'artefact

**Files:**
- Créer : `src/core/modes/errp.py`

**Interfaces:**
- Consumes : `core.errp_decoder.ErrPModel`, `core.errp_models.charger/modeles_disponibles` (T1) · `engine.markers_murs(mode_id, post_s)` → `[(ts, dict)]` · `engine.recent`, `engine.recent_ts` · `engine.acq.sigma_from_block(block)` · `epoch_from_stream(eeg, ts, flash_ts, fs, pre_s, post_s)`
- Produces : `ErrPRuntime` avec les **attributs de classe** `pre_s = ERRP_PRE_S` et `post_s = ERRP_EPOCH_S` (le contrôle structurel de `registry.check()` les lit) · `errp.SPEC` avec `marker_epoch_s = ERRP_PRE_S + ERRP_EPOCH_S`

**Ton modèle de forme :** `src/core/modes/p300.py`. Lis-le avant d'écrire. Trois de ses pires défauts n'existent pas ici — pas de manche, donc **pas de plafond, pas de contamination, pas d'abandon**. Chaque feedback est indépendant et produit exactement un échantillon.

- [ ] **Step 1: Le squelette du runtime**

```python
class ErrPRuntime(ModeRuntime):
    """Un verdict par feedback : la machine vient-elle de se tromper.

    ⚠️ Le moteur PUBLIE, il n'annule rien. La période réfractaire et la décision d'annuler une
    commande appartiennent à l'application : « n'annule pas cette commande » EST une commande, et
    ce projet publie des intentions neutres. `ERRP_REFRACTORY_S` reste au démonstrateur pygame.
    """

    pre_s = ERRP_PRE_S      # attributs de CLASSE : `registry.check()` les compare à
    post_s = ERRP_EPOCH_S   # `marker_epoch_s` pour qu'aucune époque ne soit tronquée en silence
```

- [ ] **Step 2: Le repos, et le rejet d'artefact qu'il alimente**

Le mode déclare un `Rest`. Ce que le repos mesure est un **σ par voie**, la référence du rejet d'artefact :

```python
    def _reset_rest(self):
        self._sigmas_repos = None
        self._echantillons = []

    def _rest_step(self, engine, now):
        bloc = engine.recent
        sig = engine.acq.sigma_from_block(bloc)
        if sig is None:
            return False
        self._echantillons.append(sig)
        if now < self._rest_until:
            return False
        self._sigmas_repos = np.median(np.asarray(self._echantillons), axis=0)
        print(f"[errp] repos mesuré ({len(self._echantillons)} fenêtres) — σ par voie : "
              f"{np.array2string(self._sigmas_repos, precision=1)}")
        self.rest_report = {"kind": "errp", "fenetres": len(self._echantillons),
                            "sigma": [round(float(s), 2) for s in self._sigmas_repos]}
        return True
```

et le `Rest` du `ModeSpec` :

```python
    rest=Rest(
        warmup_s=SSVEP_WARMUP_S,   # 15 s : l'offset DC de l'Unicorn dérive après ouverture
        duration_s=8.0,            # même durée que le SSVEP : deux modes lancés ensemble PARTAGENT
        instruction="Repos : regarde l'écran, immobile — on mesure le bruit de fond de tes voies.",
    ),
```

- [ ] **Step 3: Consommer les marqueurs PENDANT la chauffe — le défaut que le P300 a payé**

⚠️ **Sans ça, personne n'appelle `markers_murs` pendant les 23 s de chauffe + repos** : le curseur du moteur ne bouge pas, puis le premier pas de décodage avale l'arriéré d'un coup, et tout ce qui dépasse le tampon part en `marqueurs_perdus`. C'était le **critique n°2** de la revue du P300, et son comportement **par défaut à chaque séance**. L'ErrP a une phase d'attente **plus longue**, donc le piège y est plus probable.

Le patron existe déjà dans `p300.py` (`_jeter_marqueurs_de_chauffe`) : reprends-le, en adaptant le message.

```python
    def tick(self, engine, lsl_ts, now):
        if self.phase in ("warmup", "rest"):
            self._jeter_marqueurs_de_chauffe(engine)
        super().tick(engine, lsl_ts, now)
```

- [ ] **Step 4: Le pas de décodage**

```python
    def _run_step(self, engine, lsl_ts):
        for ts, marqueur in engine.markers_murs(self.spec.id, post_s=self.post_s):
            if marqueur.get("event") != "feedback":
                continue        # un événement inconnu s'ignore : le protocole grandira
            self._traiter_feedback(engine, ts, lsl_ts)

    def _traiter_feedback(self, engine, ts, lsl_ts):
        epoque = epoch_from_stream(engine.recent, engine.recent_ts, ts, engine.acq.fs,
                                   pre_s=self.pre_s, post_s=self.post_s)
        if epoque is None:
            self._epoques_perdues += 1
            self._publish(-1, 0.0, artefact=0, lsl_ts=lsl_ts)
            return
        if self._est_artefact(epoque):
            self._artefacts += 1
            self._publish(-1, 0.0, artefact=1, lsl_ts=lsl_ts)
            return
        score = float(np.ravel(self.model.score(epoque[None, ...]))[0])
        self._publish(1 if score >= self.seuil else 0, score, artefact=0, lsl_ts=lsl_ts)
```

⚠️ **Le flux ne se tait JAMAIS** : un feedback envoyé produit toujours un échantillon, même perdu ou rejeté. Publier `0` sur un artefact reviendrait à affirmer « pas d'erreur » alors qu'on n'a rien vu — d'où `-1`, qui veut dire la même chose que dans le SSVEP, le MI et le P300.

- [ ] **Step 5: Le rejet d'artefact, relatif au repos**

```python
    def _est_artefact(self, epoque):
        """σ de l'époque contre σ du repos, voie par voie. Un clignement sur l'erreur est le cas
        FRÉQUENT : c'est justement au moment où la machine se trompe que l'utilisateur sursaute."""
        if self._sigmas_repos is None:
            return False
        sig = np.asarray(epoque, dtype=float).std(axis=0)
        return bool(np.any(sig > ERRP_ARTIFACT_RATIO * self._sigmas_repos))
```

- [ ] **Step 6: Écrire l'autotest du mode**

Sur du signal fabriqué, avec `synth_errp_epoch` pour les époques et un faux moteur. Ce qu'il doit prouver :

```python
    chk(rt.phase == "warmup", "l'ErrP commence par une chauffe")
    chk(SPEC.rest.warmup_s == SSVEP_WARMUP_S and SPEC.rest.duration_s == 8.0,
        f"chauffe 15 s puis repos 8 s, comme le SSVEP ({SPEC.rest})")
    chk(SPEC.marker_epoch_s == ERRP_PRE_S + ERRP_EPOCH_S,
        f"l'époque déclarée vaut pré+post ({SPEC.marker_epoch_s})")
    chk(ErrPRuntime.pre_s == ERRP_PRE_S and ErrPRuntime.post_s == ERRP_EPOCH_S,
        "pre_s/post_s sont des attributs de CLASSE, lisibles par registry.check()")
    # les marqueurs de la chauffe sont JETÉS, comptés, et dits une fois
    chk(rt._marqueurs_chauffe == 3 and jetes_dits == 1,
        f"3 marqueurs jetés pendant la chauffe, annoncés UNE fois ({rt._marqueurs_chauffe})")
    # un artefact publie -1, jamais 0
    chk(ligne_artefact[0] == -1 and ligne_artefact[2] == 1,
        f"une époque rejetée publie -1 et artefact=1, jamais 0 ({ligne_artefact})")
    # le flux ne se tait jamais
    chk(len(pub.lignes) == n_feedbacks,
        f"un échantillon par feedback envoyé, quoi qu'il arrive ({len(pub.lignes)}/{n_feedbacks})")
```

- [ ] **Step 7: Lancer**

```bash
python src/core/modes/errp.py
python src/core/server.py --smoke
```

- [ ] **Step 8: Commit**

```bash
git add src/core/modes/errp.py
git commit -m "Give the ErrP a runtime, a rest baseline, and a verdict per feedback"
```

---

