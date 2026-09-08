# archive/ — what this is, and what it is not

These files are **not maintained** and **not covered by the automated tests**. They are kept
because they are the reference the current implementation was checked against: running the old
Motor Imagery calibration side by side with the engine's own, and comparing timing, labels and
recorded epochs, is a real test — and it only exists as long as both exist.

"Git keeps the history" is true but weak: nobody goes looking in the history for a file they don't
know exists.

⚠️ **Never run one of these at the same time as the engine, the console, or another archived
screen.** They open the headset THEMSELVES, and the Unicorn accepts a single connection. The
stimulus windows in `src/stimulus/` are the exception — they only draw and publish markers.

| File | What it was |
|---|---|
| `mi_calibrate.py` | The pygame Motor Imagery calibration. Replaced by the engine's own (`src/core/modes/mi_calib.py`), which measures a **honest** accuracy and never overwrites a recording. ⚠️ The accuracy this screen prints is inflated by 10 to 16 points. |
| `mi_pilot.py` | The pygame MI pilot: sliding vote over decoded windows, feedback screen, robot output. Its vote is now `MIRuntime` in `src/core/modes/mi.py`. |
| `cvep_pilot.py` | The pygame c-VEP pilot for the eCCA decoder (template matching), formerly `mode_cvep` in `src/research/app.py`. Decoding is now published by the engine (`--mode cvep` -> `decoded_cvep`) and driven from the console. Kept here, still running against a real model, as the **reference** a headset session checks the network decoding against — both must name the same target on the same fixation. Calibration is not affected by this file either way: it is the engine's job now, and the pygame screen that used to do it sits next door as `cvep_calibrate.py`. |
| `cvep_rcca_pilot.py` | The pygame c-VEP pilot AND calibration for the rCCA decoder on DISTINCT GOLD CODES, formerly `mode_cvep_rcca` and `calibrate_rcca` (`src/research/cvep_rcca.py`). This is a **refuted hypothesis**, not a removed feature: measured against the eCCA on the same conditions, Gold codes topped out at 35.6% (`data/cvep_rcca_model.npz`), while on the shared, shifted stimulus the product keeps, no difference between the two decoders is **detectable** — at the engine's own geometry (k=2), eCCA 22/37 vs rCCA 24/37, paired McNemar p = 0.727, one person, one session (see `src/core/cvep_rcca.py`). "Not detectable" is not "equivalent": with 37 decisions that test would only catch a huge gap. The live calibration now trains rCCA on that shared stimulus instead, which is what made this screen redundant. Kept runnable so the refutation stays checkable, not just asserted. |

## Arrived 2026-09-08 — "the console, the only way in"

The engine now publishes all six modes AND plays all four calibrations; the console launches them
and makes you judge a model ("Redo / Save") before it is written. Everything below was a second
way to do the same thing, from a pygame app that opened the headset itself. The three pilots are
kept for the same reason as `cvep_pilot.py` — they decode **locally**, which is what separates
"the network decoding is worse" from "the session is worse" on one and the same fixation
(recipe 2.9). The three calibrations are kept because the engine's own were written against them.

| File | What it was, and why it is here |
|---|---|
| `ssvep_pilot.py` | The pygame SSVEP pilot (CCA over flickering arrows), formerly `mode_ssvep`. Published by the engine as `decoded_ssvep` and driven from the console. It keeps two things the console does differently: the manual FREQUENCY PICKER (one per direction, among integer divisors of the refresh rate) and the resting-floor measurement that adapts the thresholds to the day. No `--model`: SSVEP needs no calibration. |
| `p300_pilot.py` | The pygame P300 selection (xDAWN+Riemann over an oddball ring), formerly `mode_p300`, with the dynamic-stopping variant. ⚠️ Its epochs are cut on the PYGAME clock (the screen timestamps its own flashes); the engine cuts them on the LSL timestamps of the incoming markers. That difference is the point: if the two disagree on the same session, look at epoch alignment before the decoder. |
| `errp_demo.py` | The pygame ErrP demonstrator (cursor-to-target, single-trial scoring, TPR/TNR scoreboard), formerly `mode_errp`. Same clock caveat as the P300. It is PASSIVE: it announces detections and compares them to ground truth, it drives nothing. |
| `cvep_calibrate.py` | The pygame c-VEP calibration, formerly `src/research/cvep_calibrate.py`, reached from the app's "c-VEP" page. It trains eCCA AND rCCA on the same epochs and names the winner (McNemar). It does not have its own training code: it CALLS `core/modes/cvep_calib.entraine_les_deux`, the same one the engine uses. |
| `p300_calibrate.py` | The pygame P300 calibration (fixate and count a cued target), formerly `src/research/p300_calibrate.py`. Calls `core/modes/p300_calib.entrainer`. `p300_pilot.py` borrows its ring and flash primitives from here. |
| `errp_calibrate.py` | The pygame ErrP calibration (the machine goes the wrong way ~30% of the time), formerly `src/research/errp_calibrate.py`. Calls `core/modes/errp_calib.entrainer` and `core/errp_track.py`. It also carries `adjust_threshold`, the manual TPR/TNR trade-off screen no other interface has yet; `errp_demo.py` imports it from here. |

⚠️ **The three calibrations were not moved for tidiness.** They write a model **straight into
`data/`**, around the guard the console now enforces — a session is displayed and judged before it
is kept. While they were on a menu, there was still a path by which a bad model silently became
the default the engine proposes. That path now requires typing an archived file's name.

⚠️ **Their epoching still differs from the engine's**, and that is not an oversight: they cut on
the pygame clock, the engine cuts on LSL marker timestamps. For a session that matters, go through
the console.

## Running them

Each file keeps its `--smoke`, which is how you check by hand that it still runs, the day you need
it:

```bash
python archive/mi_calibrate.py --smoke
python archive/mi_pilot.py --smoke
python archive/cvep_pilot.py --smoke
python archive/cvep_rcca_pilot.py --smoke
python archive/ssvep_pilot.py --smoke
python archive/p300_pilot.py --smoke
python archive/errp_demo.py --smoke
python archive/cvep_calibrate.py --smoke
python archive/p300_calibrate.py --smoke
python archive/errp_calibrate.py --smoke
```

Each is also runnable for real, on a headset, on its own — `--windowed`, `--synthetic`, and an
explicit `--model` wherever one is loaded or written. The six that arrived in 2026-09 default
`--model` to `None`, which means **the most recent LOADABLE model** for the pilots and **a
timestamped name** for the calibrations; neither ever defaults to a fixed path.

## What they are allowed to write

Outside `--smoke`, `mi_calibrate.py` / `mi_pilot.py` write to `data/` under the **old, fixed**
names (`mi_model.joblib`, `mi_calib_last.npz`) — so a real, hands-on run of an archived
calibration **overwrites** the previous one. That is one of the two defects the engine's
calibration fixed; it is left here on purpose, so the archive stays what it was.

Nothing else here does that. `cvep_rcca_pilot.py --calibrate` and the three 2026-09 calibrations
default to **timestamped** names (`chemin_modele_horodate`), same pattern as the engine — changed
after a review round found the old fixed default pointed straight at `data/cvep_rcca_model.npz`,
the file a miswired smoke run had *already* destroyed once earlier the same day. Pass `--model`
explicitly if you want the old fixed-name behavior back.

All ten `--smoke` runs are guarded by `core.config.empreinte_dossier`: it snapshots `data/` (size +
mtime per file) before and after, and fails loudly if anything changed. This is exactly the
mechanism that has cost this project four Motor Imagery models. ⚠️ The guard is blind to a
write-then-delete that happens **within** one run — see the docstring of `empreinte_dossier` for
what it does and does not catch.

⚠️ And it is blind to whatever runs BEFORE it. On 2026-09-08 the fallback test inside
`cvep_rcca_pilot.py --smoke` wrote a synthetic-board model into the real `data/`, under a name
`cvep_models.MOTIF` lists — the redirection it relied on had quietly become a no-op when
`chemin_modele_horodate` moved into `core/modes/cvep_calib.py`, and the assertion that would have
caught it sat *after* the write. It now checks the redirected path BEFORE calling anything. When
you redirect a write in a test here, assert the redirection took effect; do not assume you have
patched every name.
