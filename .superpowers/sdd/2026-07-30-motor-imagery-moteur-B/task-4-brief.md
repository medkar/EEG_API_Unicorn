### Task 4: Le moteur joue la calibration

**Files:**
- Modify: `src/core/server.py` (emplacement, commandes, tick, `keep`, phase publique, smoke)

**Interfaces:**
- **Consomme** — `CalibrationRuntime` (T3), `Calib.epoch_s` / `.runtime_cls` / `.params` (T1),
  `contract.validate` sur un `Calib`.
- **Produit** — `engine.submit("start_calibration", id=..., params={...})` et
  `engine.submit("cancel_calibration")` ; `snapshot()["calibration"]` = `None` ou l'état complet ;
  la phase publique `"calibrating"`.

- [ ] **Step 1: Dimensionner le tampon sur la plus longue époque de calibration**

Dans `EngineServer.__init__`, remplacer le calcul de `self.keep` (lignes 121-130) par :

```python
        # Le tampon doit satisfaire le plus gourmand des consommateurs : la qualité veut
        # QUALITY_WINDOW_S, le SSVEP WINDOW_S, le neuro NEURO_WINDOW_S, le MI MI_WINDOW_S — chacun
        # plus la marge de filtre. On dimensionne sur TOUS les modes, pas sur ceux qui tournent :
        # démarrer un mode en cours de séance ne doit pas dépendre de la taille d'un tampon.
        #
        # ⚠️ Et sur les CALIBRATIONS, qui prélèvent des tranches BIEN PLUS LONGUES que n'importe
        # quel décodeur : le MI enregistre des époques de 4 s là où il en décode 2. Sans ce terme,
        # chaque époque serait tronquée à la longueur du tampon — sans erreur, sans avertissement,
        # avec un tiers des fenêtres d'entraînement attendues. C'est `Calib.epoch_s` qui le déclare.
        epoque_calib = max([spec.calibration.epoch_s for spec in registry.MODES
                            if spec.calibration is not None] or [0.0])
        self.keep = max(int(QUALITY_WINDOW_S * self.acq.fs),
                        int(NEURO_WINDOW_S * self.acq.fs),
                        int(MI_WINDOW_S * self.acq.fs),
                        int(epoque_calib * self.acq.fs),
                        self.acq.window_n) + self.acq.margin_n
```

Et dans `__init__`, à côté de `self.active = {}` :

```python
        # AU PLUS UNE calibration à la fois, tous modes confondus : il n'y a qu'un casque et qu'une
        # personne. Elle vit ICI et non dans `self.active` — un mode qui refuse de démarrer sans
        # modèle (le MI) rendrait sa propre calibration inatteignable.
        self.calibration = None
```

- [ ] **Step 2: Les deux commandes**

Ajouter à `COMMANDS` :

```python
    COMMANDS = ("start_mode", "propose_params", "stop_mode", "set_params", "set_published",
                "recalibrate", "start_calibration", "cancel_calibration", "stop")
```

Dans `submit`, **avant** le bloc `spec, reason = self._one(params.get("id"))` (qui exige un mode
DÉMARRÉ — ce qu'une calibration n'exige justement pas), insérer :

```python
        if command == "start_calibration":
            spec = registry.get(params.get("id"))
            if spec is None:
                connus = ", ".join(s.id for s in registry.MODES if s.calibration is not None)
                return {"accepted": False,
                        "reason": f"mode inconnu : {params.get('id')} "
                                  f"(se calibrent : {connus})"}
            calib = spec.calibration
            if calib is None:
                return {"accepted": False,
                        "reason": f"« {spec.label} » n'a pas de calibration — il n'apprend rien"}
            if calib.runtime_cls is None:
                # Le c-VEP et le P300 : leur stimulus est verrouillé à la frame, une interface Qt
                # ne peut pas le rendre. La raison est dans le contrat, on la transmet telle quelle.
                return {"accepted": False,
                        "reason": f"la calibration de « {spec.label} » n'est pas jouable par le "
                                  f"moteur : {calib.reason or 'stimulus natif requis'} — passe "
                                  f"par `python src/research/app.py`"}
            # ⚠️ Ce mode n'a PAS besoin d'être démarré : c'est même le cas normal. Le mode MI
            # refuse de démarrer sans modèle, or c'est justement la calibration qui en produit un.
            if self.calibration is not None and not self.calibration.terminee:
                en_cours = self.calibration.spec.label
                return {"accepted": False,
                        "reason": f"une calibration est déjà en cours ({en_cours}) — abandonne-la "
                                  f"avant d'en lancer une autre"}
            values, reason = contract.validate(calib, params.get("params") or {})
            if values is None:
                return {"accepted": False, "reason": reason}
            self._commands.put(("start_calibration", {"id": spec.id, "params": values}))
            return {"accepted": True, "command": command, "id": spec.id, "params": values}

        if command == "cancel_calibration":
            if self.calibration is None or self.calibration.terminee:
                return {"accepted": False, "reason": "aucune calibration en cours"}
            self._commands.put(("cancel_calibration", {}))
            return {"accepted": True, "command": command,
                    "id": self.calibration.spec.id}
```

Dans `_apply`, ajouter :

```python
        elif command == "start_calibration":
            self._start_calibration(params["id"], params["params"])
        elif command == "cancel_calibration":
            if self.calibration is not None:
                self.calibration.cancel()
                print(f"[server] calibration abandonnée — aucun modèle produit")
```

Et la méthode, à placer après `_recalibrate` :

```python
    def _start_calibration(self, mode_id, values):
        """Construit la calibration. Appelée par la boucle, jamais par le fil d'une interface."""
        spec = registry.get(mode_id)
        self.calibration = spec.calibration.runtime_cls(spec, values, self)
        print(f"[server] {spec.calibration.label or spec.label} : "
              f"{self.calibration.total()} essais, "
              f"≈ {self.calibration.duree_estimee_s() / 60:.0f} min — "
              f"stabilisation {self.calibration.warmup_s:.0f} s d'abord")
```

- [ ] **Step 3: Le tick, dans la boucle**

Dans `run()`, juste APRÈS la boucle `for mode_id, runtime in list(self.active.items()):` :

```python
                    # La calibration tourne à CHAQUE tour, sans période minimale : sa ligne du
                    # temps se compte en dixièmes de seconde et un décompte qui saute serait vu.
                    if self.calibration is not None and not self.calibration.terminee:
                        self.calibration.tick(self, now)
```

- [ ] **Step 4: La phase publique et l'état**

Dans `_phase_of`, en TÊTE de la méthode :

```python
        # Une calibration en cours prime sur tout : c'est ce que la personne est en train de
        # faire, et les modes qui décodent en même temps sont secondaires. `calibrating` est une
        # valeur PUBLIQUE du flux `status` (spec §6) — un client peut s'en servir pour mettre son
        # application en pause pendant qu'on entraîne.
        if self.calibration is not None and not self.calibration.terminee:
            return "calibrating"
```

⚠️ `_phase_of` reçoit une COPIE de `self.active` mais lit `self.calibration` en direct. C'est sûr :
la référence est remplacée d'un bloc par la boucle, jamais mutée en place, et Python garantit
l'atomicité d'une lecture d'attribut.

Dans `_status_key`, ajouter la calibration au tuple pour que le flux `status` republie à chaque
changement de phase :

```python
        calib = self.calibration
        return (running, self.synthetic, self.phase,
                tuple((mid, r.phase, r.published) for mid, r in sorted(self.active.items())),
                None if calib is None else (calib.spec.id, calib.phase, calib.etape, calib.essai))
```

Dans `snapshot()`, ajouter à `state.update({...})` :

```python
            # `now` est passé pour que le décompte affiché soit celui de MAINTENANT, pas celui du
            # dernier tick. La console sonde à 10 Hz, le moteur tourne à sa propre cadence : sans
            # ça le décompte avancerait par à-coups.
            "calibration": (None if self.calibration is None
                            else self.calibration.state(now=time.perf_counter())),
```

- [ ] **Step 5: Nettoyer la calibration à l'arrêt**

Dans le `finally` de `run()`, juste avant `self.active = {}` :

```python
                # Une calibration en cours ne survit pas à l'arrêt du moteur : elle tient des
                # époques en mémoire et une référence vers `self` — le même cycle que les modes.
                if self.calibration is not None:
                    self.calibration.cancel()
                    self.calibration = None
```

- [ ] **Step 6: Écrire `_smoke_calibration()`**

À placer après `_smoke_mi()` dans `src/core/server.py`, et à brancher dans `_smoke()` comme les
autres (chercher comment `_smoke_mi` y est appelé et faire pareil).

```python
def _smoke_calibration():
    """Une calibration MI complète, jouée par le VRAI moteur sur board synthétique.

    Ce que ce test couvre et qu'aucun autre ne peut : la calibration tourne dans la boucle du
    moteur, prélève dans le tampon glissant RÉEL (donc éprouve le dimensionnement de `keep`), et
    produit un modèle que `modeles_disponibles` retrouve. L'autotest de `mi_calib.py`, lui, joue
    la même séance sur un faux moteur : il valide le protocole, pas l'intégration.

    Tout est écrit dans un dossier temporaire. Le vrai `data/` n'est jamais approché.
    """
    import shutil
    import tempfile
    import threading

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    from core.modes import mi_calib

    dossier = tempfile.mkdtemp(prefix="srv_calib_")
    # On raccourcit le protocole POUR LE TEST en remplaçant les durées sur la classe : c'est la
    # seule façon de jouer une séance de sept minutes en quelques secondes sans donner à
    # `CalibrationRuntime` une horloge accélérée, qui serait un chemin de code que la séance
    # réelle n'emprunte jamais.
    anciens = {c: getattr(mi_calib.MICalibration, c)
               for c in ("cue_s", "imagery_s", "rest_s", "warmup_s", "warmup_per_class",
                         "window_s", "step_s")}
    ancien_init = mi_calib.MICalibration.__init__

    def _init_temporaire(self, spec, params, engine, rng=None, dossier=dossier):
        ancien_init(self, spec, params, engine, rng=rng, dossier=dossier)

    try:
        # ⚠️ `window_s` et `step_s` sont raccourcis AVEC `imagery_s`, pas séparément : avec une
        # imagerie de 0,20 s et une fenêtre restée à 2 s, `decouper` ne rend AUCUNE fenêtre et
        # l'entraînement refuse. Le rapport est conservé — 0,20 / 0,10 / 0,05 donne 3 fenêtres
        # par essai, comme 4 / 2 / 1 en séance réelle.
        mi_calib.MICalibration.cue_s = 0.05
        mi_calib.MICalibration.imagery_s = 0.20
        mi_calib.MICalibration.rest_s = 0.05
        mi_calib.MICalibration.warmup_s = 0.10
        mi_calib.MICalibration.warmup_per_class = 1
        mi_calib.MICalibration.window_s = 0.10
        mi_calib.MICalibration.step_s = 0.05
        mi_calib.MICalibration.__init__ = _init_temporaire

        server = EngineServer(synthetic=True, modes=("raw",), instance="smoke-calib")
        thread = threading.Thread(target=server.run, kwargs={"duration_s": 30.0}, daemon=True)
        thread.start()
        try:
            # Laisser le tampon se remplir : sans ça les premières époques seraient trop courtes
            # et le moteur les ignorerait (il le dit, mais le test doit passer sans ce cas).
            # ⚠️ Attendre « non-None » ne suffit PAS : `recent_window` rend ce qu'elle a dès le
            # premier échantillon, sans dire qu'il en manque. On attend la LONGUEUR voulue.
            besoin_amorce = int(round(mi_calib.MICalibration.imagery_s * server.acq.fs))
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 10.0:
                bloc = server.recent_window(mi_calib.MICalibration.imagery_s)
                if bloc is not None and len(bloc) >= besoin_amorce:
                    break
                time.sleep(0.1)

            ack = server.submit("start_calibration", id="mi",
                                params={"trials_per_class": 6})
            chk(ack.get("accepted"), f"la calibration est acceptée ({ack})")

            # Une seconde calibration doit être refusée tant que la première tourne.
            t0 = time.perf_counter()
            while server.calibration is None and time.perf_counter() - t0 < 5.0:
                time.sleep(0.05)
            refus = server.submit("start_calibration", id="mi", params={})
            chk(not refus.get("accepted") and "déjà en cours" in (refus.get("reason") or ""),
                f"une seconde calibration est refusée ({refus})")
            chk(server.phase == "calibrating",
                f"la phase publique du moteur devient « calibrating » ({server.phase})")
            etat = server.snapshot().get("calibration")
            chk(etat is not None and etat["mode_id"] == "mi" and etat["total"] == 18,
                f"et snapshot() porte l'état complet ({etat})")

            t0 = time.perf_counter()
            while (server.calibration is not None and not server.calibration.terminee
                   and time.perf_counter() - t0 < 25.0):
                time.sleep(0.1)

            calib = server.calibration
            chk(calib is not None and calib.phase == "fini",
                f"la séance aboutit ({None if calib is None else calib.phase} ; "
                f"problème={None if calib is None else calib.probleme!r})")
            res = (calib.resultat if calib else None) or {}
            chk(res.get("n_essais") == 18, f"18 essais enregistrés ({res.get('n_essais')})")

            # Les époques prélevées dans le VRAI tampon glissant font la longueur annoncée.
            attendu = int(round(mi_calib.MICalibration.imagery_s * server.acq.fs))
            longueurs = {len(e) for e, _l in calib._enregistre}
            chk(longueurs == {attendu},
                f"chaque époque fait exactement {attendu} échantillons ({sorted(longueurs)})")

            # ⚠️ ET LE VRAI TEST DU DÉFAUT — celui-ci ne dépend PAS de la séance jouée, qui
            # tourne sur des durées rabotées. Le tampon du moteur doit tenir la plus longue
            # époque que le CONTRAT annonce (`Calib.epoch_s` = 4 s pour le MI), pas seulement la
            # fenêtre de décodage (2 s). Sans ce terme dans `keep`, chaque époque d'une séance
            # RÉELLE serait tronquée de moitié — sans erreur, avec un tiers des fenêtres
            # d'entraînement attendues. Deux vérifications, parce qu'aucune ne suffit seule :
            # le dimensionnement calculé, et le bloc réellement rendu.
            from core.config import MI_IMAGERY_S

            besoin = int(round(MI_IMAGERY_S * server.acq.fs))
            chk(server.keep >= besoin + server.acq.margin_n,
                f"le tampon du moteur tient une époque de calibration entière : keep="
                f"{server.keep} pour {besoin} + marge {server.acq.margin_n}")
            bloc = server.recent_window(MI_IMAGERY_S)
            chk(bloc is not None and len(bloc) == besoin,
                f"et il en rend une COMPLÈTE : {0 if bloc is None else len(bloc)} échantillons "
                f"pour {besoin} demandés")

            from core import mi_models

            produits = mi_models.modeles_disponibles(dossier)
            chk(len(produits) == 1 and produits[0] == res.get("modele"),
                f"le modèle produit est chargeable et listé ({produits})")
            chk(res.get("cv_groupee") is not None and res["cv_groupee"] < res["cv_naive"],
                f"l'accuracy rapportée est l'HONNÊTE, plus basse que la naïve "
                f"({res.get('cv_groupee')}, {res.get('cv_naive')})")

            # Et le mode MI peut alors démarrer sur ce modèle : c'est tout l'objet du chantier.
            demarrage = server.submit("start_mode", id="mi",
                                      params={"mi": {"model": produits[0]}})
            chk(demarrage.get("accepted"),
                f"le mode MI démarre sur le modèle qui vient d'être entraîné ({demarrage})")
        finally:
            server.stop()
            thread.join(timeout=10.0)
    finally:
        mi_calib.MICalibration.__init__ = ancien_init
        for cle, valeur in anciens.items():
            setattr(mi_calib.MICalibration, cle, valeur)
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[smoke-calib] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok
```

⚠️ **Le `finally` de restauration doit être écrit AVANT le corps** (comme ci-dessus) : si une
assertion lève, les durées de classe resteraient rabotées pour tous les tests suivants du même
processus, et `_smoke_mi` décoderait sur un protocole faussé — un faux vert particulièrement
difficile à voir.

⚠️ **Aucun résidu dans `data/`** : vérifier après le smoke que `git status --short` est propre et
que `data/` ne contient aucun `mi_model_*` ni `mi_calib_*` daté d'aujourd'hui.

- [ ] **Step 7: Lancer**

Run: `python src/core/server.py --smoke`
Expected: `[smoke-calib] VERDICT : OK` parmi les autres, sortie 0.

- [ ] **Step 8: Vérifier l'absence de résidu**

```bash
git status --short
ls data/mi_model_* data/mi_calib_* 2>/dev/null
```
Expected: arbre propre ; aucun fichier nouveau dans `data/`.

- [ ] **Step 9: Non-régression**

Run, EN SÉRIE : `python src/console/app.py --smoke` · `python src/research/app.py --smoke`
Expected: sortie 0 pour les deux.

- [ ] **Step 10: Commit**

```bash
git add src/core/server.py
git commit -m "Let the engine own and play a calibration, start to finish"
```

---

