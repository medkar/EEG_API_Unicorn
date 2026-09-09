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

## Arrived 2026-09-09 — "no command left to type"

This is the round that turned the rule into a test: **nothing under `src/research/` may open the
headset or put a stimulus on screen** — no `pygame`, no `brainflow`, no `core.acquisition` —
checked by `python src/core/server.py --smoke` (the `[smoke-frontiere]` block). Acquiring and
displaying are real use, and real use is driven from the console rather than typed into a terminal;
calculating on files already recorded is bench work and stays free. The rule had been asked for
five times between July and September 2026 without ever being written down anywhere, so every round
rediscovered it by failing. A constraint held by discipline is not held.

Three files came down here as a result, and they are three different kinds of thing: a
command-line protocol, a pilot screen the previous round missed, and the machinery underneath the
screens.

| File | What it was, and why it is here |
|---|---|
| `alpha_check.py` | The Berger check (eyes open / eyes closed) on the command line, formerly `src/research/alpha_check.py` and step 2.1 of the recipe. Now a MEASURE the engine plays and the console drives (`src/core/modes/alpha.py`, "Contrôle alpha" tile), which took its protocol verbatim — 3 s / 8 s open / 3 s / 8 s closed, band 8-12 Hz, peak in 6-14 Hz, "ratio > ~1.5". Kept because that identical arithmetic is what the engine's version was written against: when the app returns a surprising number, running this one separates "the computation changed" from "the session changed". Three things it does NOT have: a sound cue (half the measure happens with the eyes closed, where a printed line is unreadable), a refusal on a dead link (four flat channels give ~1e-27 of power on both sides, so the ratio here is rounding noise), and the one-click hand-off of the measured peak to the SSVEP's `alpha_hz`. |
| `live_ssvep.py` | The live SSVEP diagnostic, formerly `src/research/live_ssvep.py`: flickering arrows with each target's CCA rho drawn on top, the winning target, the smoothed decision and the signal sigma. This is the **seventh** pilot screen, and the 2026-09-08 round simply missed it — it opens the headset itself and draws a stimulus, exactly like the six above. Both of its uses now have a path in the app: watching rho rise under fixation is the SSVEP mode's live plot in the console, and measuring the emission rate is the "Taux d'émission SSVEP" tile (`core/modes/ssvep_mesure.py`), which counts **one trial per decision** where this screen let overlapping windows be read as independent samples. Kept as a LOCAL decoder to compare against the network one in session, and because its `--guided` protocol is what wrote the `data/ssvep_guided_*.npz` archives — the only files `src/research/ssvep_analyze.py` knows how to read. ⚠️ `--guided` writes into `data/` for real; see the last section. |
| `ui.py` | **Not a screen: the machinery the eight screens above import.** The shared pygame window, the single BrainFlow session, the link-quality display, and the live-mode plumbing (`App`, `Abort`, `Live`, `_live_loop`, `_running`, `_vote`). It was `src/research/ui.py`, where it was the base of the unified pygame app deleted on 2026-09-08; from that day it had no live caller left in `research/` at all, only the archived screens here. It broke the new rule in both ways at once — pygame AND `core.acquisition` — which is unsurprising, since drawing and acquiring are precisely its job. It has **no `--smoke` of its own** because it has nothing to launch; it is covered by the twelve below, eight of which fail to import without it. |

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
python archive/alpha_check.py --smoke
python archive/live_ssvep.py --smoke
```

That is twelve commands for thirteen files: `ui.py` is machinery, not a screen, and has nothing to
launch. It is exercised by the eight smokes that import it — hide it and they stop at
`ModuleNotFoundError`.

Each is also runnable for real, on a headset, on its own. They do **not** share one set of options:
`--smoke` is on all twelve and `--synthetic` on the eleven pygame ones — `alpha_check.py` has no
`--synthetic`, because its protocol IS 22 seconds of `time.sleep` and a synthetic board would only
make you wait them; its `--smoke` therefore exercises the arithmetic alone, with no board at all.
`--windowed` is not universal either (`mi_pilot.py` calls it `--fullscreen`, `mi_calibrate.py` and
`alpha_check.py` have neither), and `--model` exists only on the **seven** that load or write one:
`cvep_pilot.py`, `cvep_rcca_pilot.py`, `p300_pilot.py`, `errp_demo.py` and the three calibrations.
`ssvep_pilot.py` and `live_ssvep.py` have none, because the SSVEP needs no calibration, which the
table above already says; `mi_pilot.py` and `mi_calibrate.py` have none either, because they still
use the old fixed names (see below).

On six of those seven, `--model` defaults to `None`, which means **the most recent LOADABLE model**
for the pilots and **a timestamped name** for the calibrations. ⚠️ **`cvep_pilot.py` is the
exception**: its default is `CVEP_MODEL_PATH`, a fixed path, so running it bare loads whatever sits
at `data/cvep_model.npz` rather than your latest calibration. Pass `--model` explicitly — this is
the one that matters in session, since it is the local reference the network decoding is compared
against, and `CLAUDE.md` carries the same warning.

## What they are allowed to write

Outside `--smoke`, `mi_calibrate.py` / `mi_pilot.py` write to `data/` under the **old, fixed**
names (`mi_model.joblib`, `mi_calib_last.npz`) — so a real, hands-on run of an archived
calibration **overwrites** the previous one. That is one of the two defects the engine's
calibration fixed; it is left here on purpose, so the archive stays what it was.

`live_ssvep.py --guided` also writes to `data/`, and that one is **not** a defect: it archives the
raw 8-channel windows of a guided run under a timestamped name, and those files are the only input
`src/research/ssvep_analyze.py` has. It overwrites nothing. Its `--smoke` runs both of its paths —
the guided one included, since that is the only one that ever writes — and refuses to touch the
folder; the guard sits at the top of `_save_raw`, **before** the `np.savez`, never after.

Nothing else here does that. `cvep_rcca_pilot.py --calibrate` and the three 2026-09 calibrations
default to **timestamped** names (`chemin_modele_horodate`), same pattern as the engine — changed
after a review round found the old fixed default pointed straight at `data/cvep_rcca_model.npz`,
the file a miswired smoke run had *already* destroyed once earlier the same day. Pass `--model`
explicitly if you want the old fixed-name behavior back.

All twelve `--smoke` runs are guarded by `core.config.empreinte_dossier`: it snapshots `data/` (size +
mtime per file) before and after, and fails loudly if anything changed. The guard exists because of
what it catches: an unchecked save is what cost this project four Motor Imagery models, and on
2026-09-08 `cvep_rcca_pilot.py` wrote a model trained on synthetic noise straight into the real
`data/`, under a name its catalogue lists -- so it would have been offered by default at the next
headset session. ⚠️ The guard is blind to a
write-then-delete that happens **within** one run — see the docstring of `empreinte_dossier` for
what it does and does not catch.

⚠️ And it is blind to whatever runs BEFORE it. On 2026-09-08 the fallback test inside
`cvep_rcca_pilot.py --smoke` wrote a synthetic-board model into the real `data/`, under a name
`cvep_models.MOTIF` lists — the redirection it relied on had quietly become a no-op when
`chemin_modele_horodate` moved into `core/modes/cvep_calib.py`, and the assertion that would have
caught it sat *after* the write. It now checks the redirected path BEFORE calling anything. When
you redirect a write in a test here, assert the redirection took effect; do not assume you have
patched every name.
