## Task 4: Le flux, ses métadonnées, et le mode au registre

**Files:**
- Modifier : `src/core/lsl_io.py`, `src/core/modes/registry.py`, `src/core/modes/external.py`, `src/core/modes/errp.py`, `src/console/app.py`

**Interfaces:**
- Consumes : `ErrPRuntime.point_de_fonctionnement` (T3)
- Produces : `errp_channel_labels()` → `["error", "score", "threshold", "artifact"]` · `DecodedErrPPublisher(point, n_calib, instance="")` avec `.push(error, score, threshold, artifact, lsl_ts=None)`

- [ ] **Step 1: Le publieur, dans `src/core/lsl_io.py`**

À placer après `DecodedP300Publisher`, sur la même forme.

```python
def errp_channel_labels():
    """Voies du flux `decoded_errp`. Une seule fonction pour le publieur ET le `ModeSpec`."""
    return ["error", "score", "threshold", "artifact"]


class DecodedErrPPublisher:
    """`<PREFIX>_decoded_errp` : la machine vient-elle de se tromper. Un échantillon par feedback.

    ⚠️ `error = -1` signifie **« pas de verdict »** — époque perdue ou rejetée pour artefact — et
    jamais « pas d'erreur ». Un clignement au moment où la machine se trompe est le cas FRÉQUENT :
    publier 0 affirmerait qu'il n'y a pas eu d'erreur alors qu'on n'a rien vu.

    ⚠️ **Les métadonnées portent le POINT DE FONCTIONNEMENT mesuré**, et c'est une exigence, pas un
    ornement. Au réglage par défaut ce détecteur attrape UNE ERREUR SUR DEUX et annule une bonne
    commande sur sept. Une application qui lit `error = 1` doit pouvoir savoir qu'elle tient une
    pièce légèrement biaisée, pas un verdict — sinon elle traitera le flux comme fiable.
    """

    def __init__(self, point, n_calib, instance=""):
        labels = errp_channel_labels()
        info = StreamInfo(stream_name("decoded_errp"), "Decoded", len(labels),
                          IRREGULAR_RATE, "float32", _source_id("decoded_errp", instance))
        chans = info.desc().append_child("channels")
        for label in labels:
            ch = chans.append_child("channel")
            ch.append_child_value("label", label)
        desc = info.desc().append_child("decoding")
        desc.append_child_value("paradigm", "ErrP")
        desc.append_child_value("decision_scale", "logodds")
        desc.append_child_value("no_decision_index", "-1")
        desc.append_child_value("threshold", f"{point['seuil']:.6f}")
        desc.append_child_value("tnr_target", f"{point['tnr_target']:.4f}")
        desc.append_child_value("tpr_measured", f"{point['tpr']:.4f}")
        desc.append_child_value("tnr_measured", f"{point['tnr']:.4f}")
        desc.append_child_value("calibration_epochs", str(int(n_calib)))
        desc.append_child_value("measured_on", "1 person, 1 session")
        self.outlet = StreamOutlet(info)

    def push(self, error, score, threshold, artifact, lsl_ts=None):
        row = [float(error), float(score), float(threshold), float(artifact)]
        block = np.ascontiguousarray(np.asarray(row).reshape(1, -1), dtype=np.float32)
        self.outlet.push_chunk(block, [float(lsl_ts) if lsl_ts else local_clock()])
```

- [ ] **Step 2: Enregistrer le mode, retirer l'entrée « appli pygame »**

Dans `registry.py` :

```python
from core.modes import errp, external, mi, neuro, p300, raw, ssvep  # noqa: E402

MODES = (
    raw.SPEC,
    ssvep.SPEC,
    neuro.SPEC,
    mi.SPEC,
    p300.SPEC,
    errp.SPEC,          # l'ErrP a rejoint le moteur : 2e client du tuyau des marqueurs
    external.CVEP,      # il ne reste qu'UN mode que le moteur ne sait pas faire
)
```

Dans `external.py` : supprimer la constante `ERRP`, et **corriger la docstring du module**, qui parle de « deux entrées » et cite l'ErrP. Il n'en reste qu'une.

- [ ] **Step 3: Le smoke de la console — NE RIEN TOUCHER, vérifié**

⚠️ **Il n'y a rien à faire ici, et c'est contre-intuitif : ne « corrige » pas ce fichier.**

`src/console/app.py:274-281` portait un compte en dur (`== 3`, puis `== 2`), qui a cassé à chaque
mode migré. La revue du chantier P300 l'a fait réécrire en **comparaison d'identités dérivées du
registre** :

```python
    attendu_externes = sorted(s["id"] for s in registry.catalog() if s["status"] != "moteur")
    externes = [t for t in console.grid.tuiles.values() if t.spec["status"] != "moteur"]
    chk(sorted(t.spec["id"] for t in externes) == attendu_externes, …)
```

Il **s'adapte donc tout seul** dès que `external.ERRP` disparaît du registre. Le seul travail est de
lancer le smoke et de vérifier qu'il passe — s'il échoue, c'est que l'étape 2 est incomplète, pas
que cette assertion est à retoucher.

- [ ] **Step 4: Lancer**

```bash
python src/core/lsl_io.py
python src/core/modes/registry.py     # 7 modes, dont 6 dans le moteur
python src/core/modes/errp.py
python src/core/server.py --smoke
python src/console/app.py --smoke
```

- [ ] **Step 5: Commit**

```bash
git add src/core/lsl_io.py src/core/modes/registry.py src/core/modes/external.py src/core/modes/errp.py src/console/app.py
git commit -m "Publish the ErrP as the engine's fifth mode, operating point included"
```

---

