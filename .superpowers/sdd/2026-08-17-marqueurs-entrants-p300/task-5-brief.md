## Task 5: Le mode P300 — runtime, flux, et les cinq pannes bruyantes

**Files:**
- Create: `src/core/modes/p300.py`
- Modify: `src/core/lsl_io.py` (`p300_channel_labels`, `DecodedP300Publisher`)
- Modify: `src/core/modes/registry.py` (enregistrer, et le contrôle structurel)
- Modify: `src/core/modes/external.py` (retirer `P300`, corriger la docstring)

**Interfaces:**
- Consumes: `markers_murs` (Task 3), `core.p300_decoder` et `core.p300_models` (Task 4).
- Produces: `p300.SPEC` avec `marker_epoch_s = P300_PRE_S + P300_EPOCH_S`, flux `decoded_p300`.

- [ ] **Step 1: Le publieur, dans `src/core/lsl_io.py`**

À placer après `DecodedMIPublisher`, en suivant exactement la forme de `DecodedSSVEPPublisher` :

```python
def p300_channel_labels(n_targets):
    """Voies du flux `decoded_p300`. Une seule fonction pour le publieur ET le `ModeSpec`."""
    return (["target_index", "confidence", "n_flashes"]
            + [f"score_{i}" for i in range(int(n_targets))])


class DecodedP300Publisher:
    """`<PREFIX>_decoded_p300` : quelle cible l'utilisateur a sélectionnée. Une fois par manche.

    ⚠️ `target_index = -1` signifie **« pas de décision »** — jamais « la cible 0 », jamais
    « repos ». C'est mot pour mot la confusion qu'il a fallu inscrire en garde pour le MI, et
    elle se reproduira chez le premier client qui lira ce flux sans lire la doc.

    Ce flux est IRRÉGULIER et rare : un échantillon par `round_end`, pas ~5 Hz comme le SSVEP.
    Un client qui attend un débit régulier attendrait pour rien.
    """

    def __init__(self, n_targets, reps, instance=""):
        self.n_targets = int(n_targets)
        labels = p300_channel_labels(self.n_targets)
        info = StreamInfo(stream_name("decoded_p300"), "Decoded", len(labels),
                          IRREGULAR_RATE, "float32", _source_id("decoded_p300", instance))
        chans = info.desc().append_child("channels")
        for label in labels:
            ch = chans.append_child("channel")
            ch.append_child_value("label", label)
        desc = info.desc().append_child("decoding")
        desc.append_child_value("paradigm", "P300")
        desc.append_child_value("n_targets", str(self.n_targets))
        desc.append_child_value("reps", str(int(reps)))
        # « logodds » : les scores sont les log-odds moyens de la régression logistique, additifs
        # sur les répétitions. Ils ne sont ni bornés ni comparables d'une personne à l'autre —
        # sans cette indication, un seuil côté client n'aurait aucun sens.
        desc.append_child_value("decision_scale", "logodds")
        self.outlet = StreamOutlet(info)

    def push(self, target_index, confidence, n_flashes, scores, lsl_ts=None):
        """`scores` : un score par cible, dans l'ordre des indices 0..n_targets-1."""
        row = ([float(target_index), float(confidence), float(n_flashes)]
               + [float(s) for s in scores])
        block = np.ascontiguousarray(np.asarray(row).reshape(1, -1), dtype=np.float32)
        self.outlet.push_chunk(block, [float(lsl_ts) if lsl_ts else local_clock()])
```

- [ ] **Step 2: Écrire `src/core/modes/p300.py`**

Structure calquée sur `modes/mi.py`. Le `_run_step` est le cœur :

```python
    def _run_step(self, engine, lsl_ts):
        """Ramasser les flashs mûrs, les épocher, et décider à `round_end`."""
        for ts, marqueur in engine.markers_murs(self.spec.id, post_s=P300_EPOCH_S):
            event = marqueur.get("event")
            if event == "flash":
                self._encaisser_flash(engine, ts, marqueur)
            elif event == "round_end":
                self._decider(lsl_ts)
            # Tout autre événement est ignoré : le protocole s'enrichira, et un mode qui
            # refuserait ce qu'il ne connaît pas casserait au premier ajout.

    def _encaisser_flash(self, engine, ts, marqueur):
        cible = marqueur.get("target")
        if not isinstance(cible, int) or not 0 <= cible < self.n_targets:
            # Panne bruyante n°4 : une cible hors plage est un bug de l'application cliente.
            # Le dire une fois par manche suffit ; le répéter 48 fois noierait le terminal.
            self._refus_cible += 1
            if self._refus_cible == 1:
                print(f"[p300] cible « {cible} » hors de la plage attendue "
                      f"[0, {self.n_targets}[ — vérifie l'émetteur de marqueurs")
            return
        epoque = epoch_from_stream(engine.recent, engine.recent_ts, ts, engine.acq.fs,
                                   pre_s=P300_PRE_S, post_s=P300_EPOCH_S)
        if epoque is None:
            # Le marqueur était mûr mais l'époque déborde quand même : le tampon a été vidé
            # entre-temps. Compté, jamais tu.
            self._epoques_perdues += 1
            return
        self._epoques.append(epoque)
        self._cibles.append(cible)
```

Et la décision :

```python
    def _decider(self, lsl_ts):
        """Fin de manche : agréger les scores par cible et publier — ou dire pourquoi non."""
        if len(self._epoques) < self.n_targets:
            # Panne bruyante n°5 : une manche trop courte ne peut pas départager les cibles.
            # On publie quand même, avec -1 ET la raison : un client qui attend un échantillon
            # par manche ne doit pas rester suspendu.
            print(f"[p300] manche ignorée : {len(self._epoques)} flashs pour {self.n_targets} "
                  f"cibles — il en faut au moins un par cible")
            self._publish(-1, 0.0, len(self._epoques), [0.0] * self.n_targets, lsl_ts)
            self._vider_manche()
            return

        par_cible = {}
        for epoque, cible in zip(self._epoques, self._cibles):
            par_cible.setdefault(cible, []).append(epoque)
        if len(par_cible) < self.n_targets:
            # Une cible qui n'a jamais flashé n'a aucun score : l'argmax porterait sur un
            # sous-ensemble, et désignerait une cible « gagnante » parmi celles qui ont eu la
            # chance d'être montrées. Refuser est la seule réponse honnête.
            print(f"[p300] manche ignorée : {len(par_cible)} cibles ont flashé sur "
                  f"{self.n_targets} — l'émetteur n'a pas fini sa séquence")
            self._publish(-1, 0.0, len(self._epoques), [0.0] * self.n_targets, lsl_ts)
            self._vider_manche()
            return

        # `select` agrège lui-même les répétitions (moyenne des log-odds) et applique la marge.
        # On ne ré-agrège rien ici : ce calcul a été validé au casque, le refaire à côté en
        # créerait une seconde version qui finirait par diverger.
        choisi, moyennes = self.model.select(par_cible, margin=P300_SELECT_MARGIN)
        scores = [float(moyennes.get(i, 0.0)) for i in range(self.n_targets)]
        if choisi is None:
            self._publish(-1, 0.0, len(self._epoques), scores, lsl_ts)
        else:
            self._publish(int(choisi), float(moyennes[choisi]), len(self._epoques),
                          scores, lsl_ts)
        self._vider_manche()
```

Le `SPEC`, avec ses deux réglages et son point clé :

```python
SPEC = ModeSpec(
    id="p300",
    label="P300",
    family="actif",
    summary="Sélection parmi 6 cibles par onde P300 (oddball attentionnel).",
    status="moteur",
    params=(
        Param(key="model", label="Modèle entraîné", kind="choice",
              choices_fn=lambda: p300_models.modeles_disponibles(),
              help="Le modèle produit par une calibration P300, propre à TA personne — celui "
                   "de quelqu'un d'autre donne des scores plausibles et faux. Aucun modèle "
                   "dans la liste ? Lance `python src/research/app.py`, mode P300, et calibre."),
        Param(key="stream_in", label="Flux de marqueurs", kind="choice",
              choices=(MARKER_STREAM_DEFAULT,), default=MARKER_STREAM_DEFAULT,
              affecte_decodage=False,
              help="Le nom du flux LSL sur lequel ton application publie l'onset de chaque "
                   "flash. Le moteur l'écoute par son NOM : deux applications peuvent tourner "
                   "sur le réseau sans se mélanger."),
    ),
    rest=Rest(warmup_s=SSVEP_WARMUP_S, duration_s=0.0,
              instruction="Le casque se stabilise — reste immobile."),
    calibration=Calib(kind="natif",
                      reason="époques calées sur l'onset exact de chaque flash, rendu par "
                             "l'application externe"),
    stream="decoded_p300",
    channels_fn=_channels,
    runtime_cls=P300Runtime,
    marker_epoch_s=P300_PRE_S + P300_EPOCH_S,   # 0,95 s — dimensionne le tampon du moteur
)
```

- [ ] **Step 3: Enregistrer le mode et retirer l'entrée « appli pygame »**

Dans `src/core/modes/registry.py` : importer `p300`, remplacer `external.P300` par `p300.SPEC` **à la place du MI dans l'ordre** — non : le placer **après** `mi.SPEC`, et retirer `external.P300` de la liste.

```python
from core.modes import external, mi, neuro, p300, raw, ssvep  # noqa: E402

MODES = (
    raw.SPEC,
    ssvep.SPEC,
    neuro.SPEC,
    mi.SPEC,
    p300.SPEC,          # le P300 a rejoint le moteur : il écoute les marqueurs d'une appli externe
    external.CVEP,      # puis les modes de l'appli pygame, dans l'ordre où ils ont été écrits
    external.ERRP,
)
```

Dans `src/core/modes/external.py` : supprimer la constante `P300`, et corriger la docstring du
module, qui cite le P300 comme exemple d'absence.

- [ ] **Step 4: Ajouter le contrôle structurel dans `registry.check()`**

Sur le modèle **exact** du contrôle `epoch_s`/`imagery_s` déjà présent ([registry.py:240-254](../../../src/core/modes/registry.py#L240-L254)) :

```python
        # Le même piège que pour la calibration, un cran plus loin : `marker_epoch_s` (ici)
        # dimensionne le tampon du moteur ; `pre_s`/`post_s` (côté runtime) décident ce qu'on en
        # PRÉLÈVE. Deux sources de vérité pour le même nombre, et rien ne les lie : un
        # `marker_epoch_s` trop court tronquerait CHAQUE époque EN SILENCE.
        pre_s = getattr(spec.runtime_cls, "pre_s", None)
        post_s = getattr(spec.runtime_cls, "post_s", None)
        if pre_s is not None and post_s is not None:
            if spec.marker_epoch_s < pre_s + post_s:
                defauts.append(f"{spec.id} : marker_epoch_s={spec.marker_epoch_s:g} s est SOUS "
                               f"pre_s+post_s={pre_s + post_s:g} s de son runtime — chaque "
                               f"époque serait tronquée en silence")
        if spec.marker_epoch_s > 0 and spec.runtime_cls is None:
            defauts.append(f"{spec.id} : déclare marker_epoch_s sans runtime pour les consommer")
```

Et dans `src/core/server.py`, ajouter à `_smoke_dimensionnement` l'assertion stricte que la tâche 2
ne pouvait pas encore écrire — son implication était vraie à vide :

```python
    chk(besoin > 0.0,
        f"au moins un mode déclare une époque de marqueur ({besoin:g} s) — sans ça l'assertion "
        f"ci-dessus serait vraie à vide et ne prouverait rien")
```

- [ ] **Step 5: Lancer les autotests**

```bash
python src/core/modes/p300.py       # le mode : époques, décision, les 5 pannes
python src/core/modes/registry.py   # 7 modes dont 5 dans le moteur
python src/core/server.py --smoke   # dont [smoke-dimensionnement], qui doit passer AU VERT
python src/console/app.py --smoke   # la grille : la tuile P300 n'est plus grisée
```

Expected: `VERDICT : OK` partout. **`[smoke-dimensionnement]` passe maintenant ses DEUX `chk`** — c'est le vert qui prouve la tâche 2.

- [ ] **Step 6: Commit**

```bash
git add src/core/modes/p300.py src/core/lsl_io.py src/core/modes/registry.py src/core/modes/external.py
git commit -m "Publish the P300 as the engine's fourth mode, driven by external markers"
```

---

