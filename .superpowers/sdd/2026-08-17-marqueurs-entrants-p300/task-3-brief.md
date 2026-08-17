## Task 3: La file des marqueurs mûrs, et le point d'extension du contrat

**Files:**
- Modify: `src/core/server.py` (cycle de vie de l'inlet, file par mode, `markers_murs`)
- Modify: `src/core/modes/runtime.py` (documentation du point d'extension)

**Interfaces:**
- Consumes: `MarkerInlet` (Task 1), `recent_ts` (Task 2).
- Produces: `EngineServer.markers_murs(mode_id, post_s) -> list[(ts, dict)]`, `EngineServer.marqueurs_perdus: int`, `EngineServer.marqueurs_futurs: int`, `EngineServer.marker_inlet: MarkerInlet | None`.

**La règle de maturité, en une phrase :** un marqueur n'est exploitable que lorsque `recent_ts[-1] >= ts + post_s`. Avant, l'époque déborderait du tampon et `epoch_from_stream` rendrait `None` — silencieusement.

- [ ] **Step 1: Écrire le test d'abord, dans `_smoke_marqueurs_murs`**

Test sur une horloge et un tampon **fabriqués** : aucun réseau, aucune attente réelle.

```python
def _smoke_marqueurs_murs():
    """Un marqueur n'est rendu que quand son époque tient ENTIÈREMENT dans le tampon."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    srv = EngineServer(synthetic=True, modes=(), params={})
    fs = srv.acq.fs
    # Tampon fabriqué : 3 s de temps qui avance, à partir de t=100.
    srv.recent_ts = np.arange(100.0, 103.0, 1.0 / fs)
    srv.recent = np.zeros((len(srv.recent_ts), 8))

    srv._marqueurs = [(101.0, {"mode": "p300", "event": "flash", "target": 1}),
                      (102.9, {"mode": "p300", "event": "flash", "target": 2}),
                      (101.5, {"mode": "errp", "event": "feedback"})]
    srv._marqueur_curseur = {}

    murs = srv.markers_murs("p300", post_s=0.80)
    chk([m[1]["target"] for m in murs] == [1],
        f"seul le marqueur dont les 0,80 s suivantes sont dans le tampon est rendu ({murs})")
    chk(all(m[1]["mode"] == "p300" for m in murs),
        "et le marqueur d'un AUTRE mode n'est jamais rendu à celui-ci")

    # Le curseur avance : un marqueur mûr n'est rendu qu'UNE fois.
    chk(srv.markers_murs("p300", post_s=0.80) == [],
        "un marqueur déjà rendu ne l'est pas deux fois")

    # Le tampon avance : le second devient mûr à son tour.
    srv.recent_ts = np.arange(100.0, 104.0, 1.0 / fs)
    srv.recent = np.zeros((len(srv.recent_ts), 8))
    murs = srv.markers_murs("p300", post_s=0.80)
    chk([m[1]["target"] for m in murs] == [2],
        f"le tampon ayant avancé, le suivant mûrit à son tour ({murs})")

    # Un marqueur PLUS VIEUX que le tampon est PERDU, et compté.
    avant = srv.marqueurs_perdus
    srv._marqueurs.append((50.0, {"mode": "p300", "event": "flash", "target": 3}))
    srv.markers_murs("p300", post_s=0.80)
    chk(srv.marqueurs_perdus == avant + 1,
        f"un marqueur trop vieux pour le tampon est COMPTÉ perdu, pas ignoré "
        f"({srv.marqueurs_perdus})")

    # Un marqueur dans le FUTUR est la signature du time_correction() oublié.
    avant = srv.marqueurs_futurs
    srv._marqueurs.append((200.0, {"mode": "p300", "event": "flash", "target": 4}))
    srv.markers_murs("p300", post_s=0.80)
    chk(srv.marqueurs_futurs == avant + 1,
        f"un marqueur très en avance est compté à part : c'est le piège des deux machines "
        f"({srv.marqueurs_futurs})")

    print(f"[smoke-marqueurs] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok
```

- [ ] **Step 2: Lancer pour voir échouer**

Run: `python src/core/server.py --smoke`
Expected: `AttributeError: 'EngineServer' object has no attribute 'markers_murs'`.

- [ ] **Step 3: Implémenter dans `EngineServer`**

Dans `__init__` :

```python
        self.marker_inlet = None       # créé au démarrage si un mode écoute des marqueurs
        self._marqueurs = []           # tous les marqueurs reçus, dans l'ordre d'arrivée
        self._marqueur_curseur = {}    # mode_id -> index du prochain marqueur à examiner
        self.marqueurs_perdus = 0      # arrivés trop tard pour trouver leur EEG
        self.marqueurs_futurs = 0      # horodatés en avance : time_correction() oublié ?
```

La méthode, à placer près de `_publish_quality` :

```python
    def markers_murs(self, mode_id, post_s):
        """Les marqueurs de CE mode dont l'époque tient entièrement dans le tampon.

        « Mûr » = le tampon couvre déjà les `post_s` secondes qui SUIVENT le marqueur. Avant,
        l'époque déborderait et le découpage rendrait None — sans rien dire. Cette attente est
        générique, donc elle vit ici : chaque mode qui la réimplémenterait la referait un peu
        différemment.

        Chaque marqueur n'est rendu qu'une fois par mode (curseur par mode). Ceux d'un autre
        mode sont sautés en silence : c'est le SEUL rejet muet autorisé, parce qu'il est normal.
        """
        if not len(self.recent_ts):
            return []
        plus_vieux, plus_recent = float(self.recent_ts[0]), float(self.recent_ts[-1])
        i = self._marqueur_curseur.get(mode_id, 0)
        murs = []
        while i < len(self._marqueurs):
            ts, d = self._marqueurs[i]
            if ts + post_s > plus_recent:
                # Pas encore mûr — et les suivants le sont encore moins : on s'arrête ici.
                break
            i += 1
            if d.get("mode") != mode_id:
                continue
            if ts > plus_recent + MARKER_LATE_S:
                self.marqueurs_futurs += 1
                continue
            if ts < plus_vieux:
                self.marqueurs_perdus += 1
                continue
            murs.append((ts, d))
        self._marqueur_curseur[mode_id] = i
        return murs
```

- [ ] **Step 4: Brancher l'inlet dans la boucle**

Dans `run()`, avant la boucle, créer l'inlet **seulement si un mode actif écoute** :

```python
            # L'inlet n'existe que si un mode en a besoin : ouvrir un flux entrant qui ne sert à
            # personne ferait chercher sur le réseau à chaque tour pour rien.
            besoin_marqueurs = any(rt.spec.marker_epoch_s > 0.0 for rt in self.active.values())
            if besoin_marqueurs:
                nom = MARKER_STREAM_DEFAULT
                self.marker_inlet = MarkerInlet(nom, timeout_s=0.0)
                if self.marker_inlet.resolve():
                    print(f"[server] marqueurs entrants : connecté à « {nom} »")
                else:
                    # Pas une erreur : l'application de stimulus démarre souvent APRÈS le moteur.
                    # On réessaiera dans la boucle, et le mode dira qu'il attend.
                    print(f"[server] marqueurs entrants : « {nom} » pas encore là — j'attends. "
                          f"Lance ton application de stimulus, la connexion se fera toute seule.")
```

Dans la boucle, juste après la lecture EEG :

```python
                    if self.marker_inlet is not None:
                        if not self.marker_inlet.connecte:
                            self.marker_inlet.resolve()
                        self._marqueurs.extend(self.marker_inlet.pull())
                        # Le tampon de marqueurs ne grandit pas indéfiniment : on jette ceux que
                        # TOUS les curseurs ont dépassés. Sans ça, une séance d'une heure garde
                        # 24 000 flashs en mémoire pour rien.
                        if len(self._marqueurs) > 4096 and self._marqueur_curseur:
                            coupe = min(self._marqueur_curseur.values())
                            if coupe > 2048:
                                self._marqueurs = self._marqueurs[coupe:]
                                self._marqueur_curseur = {
                                    k: v - coupe for k, v in self._marqueur_curseur.items()}
```

- [ ] **Step 5: Documenter le point d'extension dans `runtime.py`**

Dans la docstring de la classe `ModeRuntime`, section « à redéfinir dans les sous-classes », ajouter après `_run_step` :

```python
    # Un mode qui écoute des marqueurs déclare `marker_epoch_s` dans son `ModeSpec` et appelle
    # `engine.markers_murs(self.spec.id, post_s)` depuis son `_run_step`. Le moteur lui rend des
    # marqueurs SITUÉS (horodatés dans la même horloge que `engine.recent_ts`) et MÛRS (leur
    # époque tient dans le tampon). Le découpage reste au mode : les bornes ne sont pas les
    # mêmes d'un paradigme à l'autre.
```

- [ ] **Step 6: Lancer les smokes**

Run: `python src/core/server.py --smoke`
Expected: `[smoke-marqueurs] VERDICT : OK`.

- [ ] **Step 7: Commit**

```bash
git add src/core/server.py src/core/modes/runtime.py
git commit -m "Hold markers until their epoch fits, and count the ones that never will"
```

---

