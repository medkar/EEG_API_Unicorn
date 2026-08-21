# archive/ — what this is, and what it is not

These files are **not maintained** and **not covered by the automated tests**. They are kept
because they are the reference the current implementation was checked against: running the old
Motor Imagery calibration side by side with the engine's own, and comparing timing, labels and
recorded epochs, is a real test — and it only exists as long as both exist.

"Git keeps the history" is true but weak: nobody goes looking in the history for a file they don't
know exists.

| File | What it was |
|---|---|
| `mi_calibrate.py` | The pygame Motor Imagery calibration. Replaced by the engine's own (`src/core/modes/mi_calib.py`), which measures a **honest** accuracy and never overwrites a recording. ⚠️ The accuracy this screen prints is inflated by 10 to 16 points. |
| `mi_pilot.py` | The pygame MI pilot: sliding vote over decoded windows, feedback screen, robot output. Its vote is now `MIRuntime` in `src/core/modes/mi.py`. |
| `cvep_pilot.py` | The pygame c-VEP pilot for the eCCA decoder (template matching), formerly `mode_cvep` in `src/research/app.py`. Decoding is now published by the engine (`--mode cvep` -> `decoded_cvep`) and driven from the console. Kept here, still running against a real model, as the **reference** a headset session checks the network decoding against — both must name the same target on the same fixation. Calibration is unaffected: it still lives at `src/research/app.py`, page "c-VEP". |
| `cvep_rcca_pilot.py` | The pygame c-VEP pilot AND calibration for the rCCA decoder on DISTINCT GOLD CODES, formerly `mode_cvep_rcca` and `calibrate_rcca` (`src/research/cvep_rcca.py`). This is a **refuted hypothesis**, not a removed feature: measured against the eCCA on the same conditions, Gold codes topped out at 35.6% (`data/cvep_rcca_model.npz`) against ~48% for both decoders on the shared, shifted stimulus the product keeps (see `src/core/cvep_rcca.py`). The live calibration (`src/research/cvep_calibrate.py`) now trains rCCA on that shared stimulus instead, which is what made this screen redundant. Kept runnable so the refutation stays checkable, not just asserted. |

Each file keeps its `--smoke`, which is how you check by hand that it still runs, the day you need
it:

```bash
python archive/mi_calibrate.py --smoke
python archive/mi_pilot.py --smoke
python archive/cvep_pilot.py --smoke
python archive/cvep_rcca_pilot.py --smoke
```

Outside `--smoke`, `mi_calibrate.py` / `mi_pilot.py` write to `data/` under the **old, fixed**
names (`mi_model.joblib`, `mi_calib_last.npz`) — so a real, hands-on run of an archived calibration
**overwrites** the previous one. That is one of the two defects the engine's calibration fixed; it
is left here on purpose, so the archive stays what it was.

`cvep_rcca_pilot.py --calibrate` does **not** follow that convention: its default `save_path` is
**timestamped**, same pattern as the live calibration (`chemin_modele_horodate`) — changed after a
review round found the old fixed default pointed straight at `data/cvep_rcca_model.npz`, the file a
miswired smoke run had *already* destroyed once earlier the same day. Pass `--model` explicitly if
you want the old fixed-name behavior back.

All four files' `--smoke` are now guarded by `core.config.empreinte_dossier`: it snapshots `data/`
(size + mtime per file) before and after, and fails loudly if anything changed — `mi_calibrate.py`
and `mi_pilot.py` skip their save when `smoke=True` and always have, but nothing used to *check*
that, and this is exactly the mechanism that has cost this project four Motor Imagery models
before. ⚠️ The guard is blind to a write-then-delete that happens **within** one run — see the
docstring of `empreinte_dossier` for what it does and does not catch.
