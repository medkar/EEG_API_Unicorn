# EEG_API_Unicorn

A **BCI signal API for students**: acquire an **Unicorn Hybrid Black** EEG headset, decode it with
ready-made paradigms, and **stream the result over the network** so any external application — Unity,
Python, MATLAB, web — can build on it.

```
Unicorn headset ──► acquisition ──► decoding (SSVEP / MI / c-VEP / P300 / …) ──► network stream ──► your app
```

The tool is **agnostic of what you build**. Each mode publishes a **neutral intent** (which target,
which class, which mental state) — never an actuator command. Turning that intent into an action (a
game event, a visualisation, a robot command) is the client application's job.

> **Status.** The engine streams over the network and is hardware-validated end to end: raw EEG,
> signal quality and decoded SSVEP reach a client on another machine, with millisecond timestamps.
> SSVEP decoding is measured, not asserted: 100 % accurate whenever it commits, on 36 interleaved
> trials — but it only commits 44 % of the time. Neuro-monitoring is published too, though its
> content is not yet hardware-validated. c-VEP, P300 and MI still live in the pygame app only —
> see **[docs/SPEC.md](docs/SPEC.md)** for the stream contract and the roadmap.

## Requirements

Python 3.10+, an Unicorn Hybrid Black headset paired over Bluetooth.

```bash
pip install -r requirements.txt
```

## Run

Three entry points, from the most useful to the most specialised.

**The engine** — no interface, streams over the network. This is the product.

```bash
python src/core/server.py --mode ssvep --refresh 60   # acquire, decode, publish
python src/core/server.py --mode neuro                # passive: no stimulus, no calibration
python src/core/server.py --synthetic                 # no headset (BrainFlow test board)
```

Two published modes, and a client should not treat them alike. **SSVEP is active**: the user chooses a
target, there is a right answer, and your application must render the flickering stimulus. **Neuro is
passive**: it reports a mental state, there is nothing to choose and no stimulus — but its values are
z-scores against a rest measured at the start of the mode, *for this person, today*. They compare
across neither people nor sessions, and mean nothing in absolute terms. The stream metadata carries
`paradigm` so a client can tell the two apart.

**The console** — the engine plus a desktop window, one page per mode.

```bash
python src/console/app.py --mode ssvep        # set up, watch, publish
python src/console/app.py --synthetic         # no headset (BrainFlow test board)
python src/core/server.py --mode ssvep,neuro  # the engine alone, no interface (headless)
python src/core/server.py --no-raw --mode neuro   # decode without broadcasting the raw signal
```

A grid of every mode — including the ones the engine cannot run, greyed out with the reason. Open one
and you get what it produces live, its settings, and a Python snippet that consumes its stream, both
generated from the mode's contract rather than written by hand. Across the top, permanently: channel
quality and a detached-reference alarm. The raw mode draws the eight channels themselves.

Settings are **not validated by the interface**. It submits, and shows the engine's refusal in its own
words — a rule copied into the UI drifts from the engine's eventually, and the day it drifts it lets
through a setting that decodes nothing, silently.

Changing the frequencies **recreates the `decoded_ssvep` stream**: they name its channels
(`score_15Hz`) and LSL metadata is fixed at creation, so keeping the old stream would publish labels
that lie. Connected clients must re-resolve — the stream name itself does not change. The rest floor
restarts too, since it is measured per frequency. A frequency set outside the acquisition band, or
with two targets closer than the `1/WINDOW_S` resolution, is rejected with a reason rather than
accepted and decoded into the void.

Frequencies must be **integer divisors of the refresh rate of the screen showing the targets** — at
60 Hz: 30, 20, 15, 12, 10, 8.571. Anything else makes the display skip cycles, and the decoder
correlates against a sinusoid nobody is displaying: no error, no detection, nothing to debug. The
engine now refuses those, and the console has a **Propose** button that asks it for a valid set.

The proposal steers away from the **individual alpha peak**, which is a per-person trait (population
mean ≈ 9.6 Hz, range 7–13). A target sitting on someone's peak does not stand out from their own
resting background — so the set that works for one person can fail for the next. Set `alpha_hz` per
person; `python src/research/alpha_check.py` measures it.

**The pygame app** — the original all-in-one, still the only way to run c-VEP, P300, MI and ErrP,
and the only place with a live histogram for neuro-monitoring. It owns the headset and publishes
nothing.

```bash
python src/research/app.py                 # fullscreen, real headset — main menu
python src/research/app.py --windowed      # windowed (keeps the console visible)
python src/research/app.py --synthetic     # no headset (BrainFlow synthetic board)
python src/research/app.py --smoke         # headless end-to-end self-test (CI)
```

⚠️ The engine and the app both open the headset, so **run only one at a time**.

## Consume the stream

The client depends on `pylsl` and nothing else — not on this repository.

```bash
pip install pylsl
python examples/receiver.py --list                  # what is on the network
python examples/receiver.py --stream decoded_ssvep  # which target is being looked at
python examples/receiver.py --stream decoded_neuro  # workload / drowsiness / engagement
```

Unity: see [`examples/unity/`](examples/unity/). Two machines: see
[`docs/network.md`](docs/network.md).

| Stream | Contents |
|---|---|
| `EEG_API_Unicorn_raw` | 8 channels, µV, unfiltered, 250 Hz |
| `EEG_API_Unicorn_quality` | per-channel σ, ~1 Hz |
| `EEG_API_Unicorn_status` | engine state, JSON |
| `EEG_API_Unicorn_decoded_ssvep` | `{target_index, freq_hz, confidence, scores[]}`, ~5 Hz |
| `EEG_API_Unicorn_decoded_neuro` | `{charge, somnolence, engagement, artifact}`, ~5 Hz |

The stimulus is **not** rendered by the engine: your application flickers the targets and declares
their frequencies (`--refresh` or `--freqs`). A mismatch fails silently — the decoder correlates
against a sinusoid nobody is displaying — so pass the same refresh rate to both sides.

`ESC` returns to the menu from any mode; the BrainFlow session stays open, so switching modes is
instant. **Do not close and reopen the app mid-session** — C3/Cz saturate when the amplifier restarts.

## Decoding modes

All six share one acquisition session and one UI core. Stimulus frequencies and codes adapt
automatically to the display refresh rate.

| Mode | How it works | Calibration | Status |
|---|---|---|---|
| **SSVEP** | Arrows flicker at fixed frequencies; CCA picks the fixated one | 25 s rest baseline | ✅ most reliable |
| **c-VEP** | One m-sequence at circular shifts, learned template (eCCA) | ~1 min | ✅ 6 targets, ~22 bits/min |
| **P300** | Oddball: targets flash one by one, xDAWN + Riemannian geometry | ~4 min | ✅ validated on hardware |
| **Motor Imagery** | Imagined left/right fist squeeze, ERD on C3/C4, CSP + LDA | 5–7 min | ✅ left/right significant (79 %) |
| **Neuro-monitoring** | Passive spectral indices: workload, drowsiness, engagement | 25 s rest | 🟡 **published as a stream**, content not yet hardware-validated |
| **ErrP** | Error potential: single-trial detection when the machine errs | ~4 min | 🟡 demonstrator, needs real calibration |

## Layout

The source splits in two, on a rule you can check rather than a matter of taste: **a module lives in
`core/` if and only if the engine needs it to run.** Everything else is `research/`. `research` may
import `core`; `core` must never import `research`. When a mode graduates from exploration to a
published stream, its decoder *moves* to `core/` — nobody threads an import across the boundary.

### [`src/core/`](src/core/) — the engine, and therefore the product

| Module | What it does |
|---|---|
| [`server.py`](src/core/server.py) | The headless loop: acquire, decode, publish. Start here. |
| [`lsl_io.py`](src/core/lsl_io.py) | Stream publishers and the clock bridge — **the public contract** |
| [`acquisition.py`](src/core/acquisition.py) | Unicorn via BrainFlow: sliding windows, epochs, link check |
| [`cca_decoder.py`](src/core/cca_decoder.py) | SSVEP by CCA, no training, z-scored against a rest floor |
| [`neuro_monitor.py`](src/core/neuro_monitor.py) | Passive spectral indices, z-scored against a per-session rest |
| [`config.py`](src/core/config.py) | Channels, frequencies, codes, per-mode constants, repo paths |
| [`modes/`](src/core/modes/) | One contract per mode (`ModeSpec`) beside its runtime — what it is, what you can set, what it publishes |

No pygame and no Qt anywhere in here: the engine runs on a machine without a screen. A self-test
enforces it rather than trusting discipline.

### [`src/console/`](src/console/) — the desktop console, a client of the engine

It creates an engine, runs its loop in a thread, and polls `snapshot()`. Nothing else. Two rules hold
it together: the Qt thread never touches the BrainFlow session — every action goes through the
engine's command queue — and no logic lives here that the engine does not already own.

| Module | What it does |
|---|---|
| [`app.py`](src/console/app.py) | The window: reads state, sends commands, and the headless self-test |
| [`grid.py`](src/console/grid.py) | The mode grid — every mode, runnable or not |
| [`mode_page.py`](src/console/mode_page.py) | One page per mode: live output · settings · how to consume it |
| [`params_form.py`](src/console/params_form.py) | The settings form, generated from the contract. Validates nothing |
| [`live_views.py`](src/console/live_views.py) | Rendering picked by **family** — active, passive, raw traces |
| [`banner.py`](src/console/banner.py) | Channel quality and the detached-reference alarm, always visible |

### [`src/research/`](src/research/) — everything not yet in the engine

Not a synonym for "unfinished" — several of these modes are hardware-validated. It means the engine
does not publish them yet, so they are not part of what students consume and may still change shape.

| Family | Modules |
|---|---|
| pygame app | [`app.py`](src/research/app.py) (menu, six modes) · `ui.py` · `ssvep_stimulus.py` · `viewing.py` |
| Mode decoders — the migration candidates | `cvep_decoder` · `cvep_code` · `mi_decoder` · `p300_decoder` · `errp_decoder` |
| Calibrations — long protocols, train a model into `data/` | `mi_calibrate` · `cvep_calibrate` · `p300_calibrate` · `errp_calibrate` |
| Offline analysis — replay, compare, measure | `cvep_analyze` · `p300_analyze` · `ssvep_analyze` · `mi_compare` · `itr` · `alpha_check` |
| Robot-testbed leftovers, kept as a baseline | `controller.py` · `live_ssvep.py` |

## Self-tests (no headset needed)

```bash
python src/core/server.py --smoke        # engine: registry, package boundary, shared rest, streams
python src/console/app.py --smoke        # console: grid, mode page, settings (Qt offscreen)
python src/core/lsl_io.py                # stream contract: channel names, round-trip, clock bridge
python src/core/cca_decoder.py           # CCA accuracy on synthetic SSVEP
python src/core/acquisition.py --synthetic  # acquisition alone, on the test board
python src/core/neuro_monitor.py         # spectral indices on synthetic EEG

python src/research/app.py --smoke       # whole app headless: menu + every mode + calibrations
python src/research/cvep_code.py         # m-sequence properties (balance, autocorrelation, lags)
python src/research/cvep_decoder.py      # c-VEP accuracy vs SNR on synthetic responses
python src/research/errp_decoder.py      # ErrP pipeline on synthetic error potentials
python src/research/controller.py        # SSVEP decode → smoothing → UDP, verified end to end
python src/research/itr.py               # information transfer rate — common yardstick
```

## Things worth knowing

- **Signal quality dominates everything.** Saline on the electrodes is the single biggest lever
  measured. A detached reference produces a whole unusable session, and per-channel σ does not
  reveal it — every channel then measures the same floating reference at a plausible amplitude. The
  engine watches inter-channel correlation instead: above 0.90, the reference has come off.
- **The Unicorn has a huge, drifting DC offset** (10⁵ µV, ramping for tens of seconds after a session
  opens). Any σ computed without discarding the filter's settling transient measures the filter, not
  the electrode — by a factor of a hundred. Let the amplifier settle before measuring anything.
- **Compare paradigms by information transfer rate** (`itr.py`), not raw accuracy — 70 % over 6
  targets is worth far more than 70 % over 3.
- **Per-frequency noise floor.** Each SSVEP target sits on a different amount of background alpha, and
  that floor moves between sessions. A single global threshold is structurally unfair, so SSVEP mode
  measures μ/σ at rest and decides on the z-score instead. This fixed the weakest target without
  retuning any frequency.
- **Protocol confounds are expensive.** Recording each c-VEP target as one contiguous block made
  "which target" inseparable from "when"; interleaving and shuffling the blocks raised throughput by
  76 % with no change to the decoder.
- **Small EEG samples lie.** Validate a hypothesis with a permutation test or honest cross-validation
  before believing it.

## History

A TurtleBot3 Waffle robot served as the original **testbed** for this work — proof that a decoded
intent could drive something real. It is no longer a goal of the project; see
[docs/robot_testbed.md](docs/robot_testbed.md) if you want to reproduce that demo, and
[`examples/actuator_udp.py`](examples/actuator_udp.py) for the pattern it left behind: turning an
intent into an action belongs to the client, never to the API.
