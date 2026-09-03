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
> trials — but it only commits 44 % of the time. **All six decoding modes are now published**: the
> engine both sends streams and *receives* markers, so an external application can render the
> stimulus and let the engine decode — see **[docs/markers.md](docs/markers.md)**. Motor Imagery
> and neuro arrived first, P300 on 2026-08-17, ErrP on 2026-08-19, and **c-VEP closed the set on
> 2026-08-21**. ⚠️ Four of the six — MI, P300, ErrP, c-VEP — have **never been decoded from a real
> brain through the engine**: the pipe is verified end to end without a headset, the decoding was
> validated in the pygame app, and putting both halves on one head is the session that remains. See
> **[docs/SPEC.md](docs/SPEC.md)** for the stream contract and the roadmap.

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
python src/core/server.py --mode cvep                 # needs a trained model AND a clock emitter
python src/core/server.py --synthetic                 # no headset (BrainFlow test board)
```

Six published modes, and a client should not treat them alike. **SSVEP is active**: the user chooses
a target, there is a right answer, and your application must render the flickering stimulus. **Motor
Imagery is active** too, but it decodes an imagined movement — no stimulus to render, and a model
trained per person (its own section below). **P300 is active and the most demanding**: your
application renders the flashes *and* tells the engine when each one happened, because the whole
decoding rests on cutting the EEG at that instant — see [docs/markers.md](docs/markers.md). It also
needs a per-person model, and it answers once per round rather than continuously. **c-VEP is active
and the most timing-sensitive**: it reads *which shift of one pseudo-random code* your eye is
locked to, decoding continuously like SSVEP — but your application must render the flicker
frame-by-frame and send the engine a marker every time the code restarts. Those markers do not
delimit an epoch; they are a **clock**, and without one the engine has nothing to correlate against.
**Neuro is passive**: it reports a mental state, there is nothing to choose and no stimulus — but
its values are z-scores against a rest measured at the start of the mode, *for this person, today*.
They compare across neither people nor sessions, and mean nothing in absolute terms. **ErrP is
passive and the most easily misread**: it does not answer a question you asked, it reports that the
user's brain reacted the way brains react when a machine gets something wrong. Like P300 it needs
your markers — you tell the engine when you showed a result, and it answers per result.

The stream metadata carries `paradigm` so a client can tell them apart — six values, not two:
`SSVEP`, `motor-imagery`, `P300`, `neuro-passive`, `ErrP`, `c-VEP`. It also carries
`decision_scale`, and that one is not optional reading: a threshold is meaningless without it.
SSVEP decides on a `z` against a rest floor, MI on a `proba`, P300 and ErrP on unbounded `logodds`
(usually negative), c-VEP on a `correlation` in `[-1, 1]`. Put one mode's threshold on another
mode's scale and you are wrong by an order of magnitude.

⚠️ **Read the ErrP operating point before you act on it.** At the default setting it **catches one
error in two and cancels one good command in seven**; the stream publishes that in its own metadata
precisely so a client cannot mistake it for a verdict. It is the best-validated decoder here *by
AUC on grouped cross-validation* (0.776, permutation p = 0.0099) and still only that good, which is
what a single-trial ERP costs. Best-validated is not the same claim as most reliable — that one is
SSVEP, on a different axis.

**The console** — the engine plus a desktop window, one page per mode.

```bash
python src/console/app.py --mode ssvep        # set up, watch, publish
python src/console/app.py --synthetic         # no headset (BrainFlow test board)
python src/core/server.py --mode ssvep,neuro  # the engine alone, no interface (headless)
python src/core/server.py --no-raw --mode neuro   # decode without broadcasting the raw signal
```

A grid of every mode — including the ones the engine cannot run, greyed out with the reason. Each
runnable tile has its own **Start**/**Stop**: launching with `--mode` is a convenience for bringing
up several modes at once (they then share one rest phase), not a requirement — the console did not
use to be able to start a mode on its own, and now it can. Open one and you get what it produces
live, its settings, and a Python snippet that consumes its stream, both generated from the mode's
contract rather than written by hand. Across the top, permanently: channel quality and a
detached-reference alarm. The raw mode draws the eight channels themselves.

Settings are **not validated by the interface**. It submits, and shows the engine's refusal in its own
words — a rule copied into the UI drifts from the engine's eventually, and the day it drifts it lets
through a setting that decodes nothing, silently.

A mode page that needs training also has a **Calibrate** button. It runs the whole protocol —
cued trials, training, an honest accuracy figure — **inside the same window**: nothing to launch
separately, nothing to close and reopen. Motor Imagery is the one mode that uses it today (below).

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

### Motor Imagery

`--mode mi` publishes `EEG_API_Unicorn_decoded_mi`: `intent_index`, `confidence`, then one
probability per class (`GAUCHE`, `DROITE`, `REPOS`).

Unlike SSVEP, this mode **must be trained per person**. It loads a model produced by a calibration
and **refuses to start without one**, saying so — a mode that started without a model would publish
probabilities and never decide anything, which is the silent failure this project exists to remove.
Train one **from the console itself**: open Motor Imagery and click **Calibrate** — a few minutes of
cued left/right/rest trials, played by the engine, ending in a timestamped model and an accuracy
figure that is honestly cross-validated **by trial**, so no window leaks between folds. The mode
page then lists the models it finds, newest first.

Two values are easy to confuse and mean different things:

| `intent_index` | Meaning |
|---|---|
| `-1` | the sliding vote did not conclude — not enough recent windows agreed, or the classifier stayed under its threshold |
| index of `REPOS` | the model decided the user is at rest |

For an application, that is the difference between "wait" and "stop".

**What it is worth.** Motor Imagery is the hardest paradigm here. Two accuracy figures circulate for
it, and both are real — they come from two different sessions, on the same person:

- **79 %** on left-vs-right (p = 0.002, 42 trials, 2026-07-22). This is the session that first showed
  the left/right contrast exists at all. Its raw recording has since been lost, so the figure can no
  longer be re-derived or re-audited.
- **63 %** on left-vs-right (chance 50 %, p = 0.038, 30 trials), measured by cross-validation
  **grouped by trial** so that windows from one trial cannot leak across folds. This is the only
  surviving session, and therefore the number to plan against. On the three classes it falls to 40 %
  (chance 33 %, not significant).

So expect roughly **one error in three** on two classes. It is slow and imprecise: a demonstrator,
not a fine control. Do not design something that needs a correct answer every second.

A model belongs to the person it was trained on. Someone else's model produces probabilities that
look plausible and are wrong, which is worse than no output at all.

### c-VEP

`--mode cvep` publishes `EEG_API_Unicorn_decoded_cvep`: `target_index`, `confidence`, one
correlation per target, then the two thresholds in force. Continuous, about 5 samples per second.

Every target flickers the **same** 63-frame m-sequence, each at a different circular shift, and the
decoder finds which shift your response is locked to. That buys separability a set of SSVEP
frequencies cannot — but it costs an exact idea of **where in the code the screen currently is**.
That is what the marker gives it:

```bash
python src/core/server.py --mode cvep       # terminal 1: decode and publish
python src/research/cvep_stimulus.py        # terminal 2: flicker, and send the clock
```

The emitter opens no headset, which is why the two run side by side. It is also the reference
implementation to copy if you render the stimulus yourself — read
[docs/markers.md](docs/markers.md) first, and take the timestamp *after* the flip that showed frame
0 of the code, not one line earlier.

⚠️ **The characteristic failure of this mode breaks nothing.** A phase off by a few frames raises no
exception: correlations sag just enough that detection almost never fires, and on screen that is
indistinguishable from a user who is not fixating. Two one-line mistakes produce it — stamping the
marker before the flip, or announcing a refresh rate the screen does not hold. The engine defends
what it can see: it **refuses** every marker whose `refresh` is more than 1 Hz from the model's, and
says so. ⚠️ It refuses the *markers*, not the *start* — the mode keeps running and keeps publishing
`-1`, so do not wait for a crash.

`target_index = -1` has **four** distinct causes here, and they call for opposite actions: no clock
marker ever arrived · the clock went stale · correlations missed the thresholds · recent windows
disagreed. The stream carries only the `-1`; the engine's state counts the four separately, because
"it is not detecting" without the cause sends you looking in the wrong place.

Like MI, P300 and ErrP it needs a **model trained on you** — one calibration in the pygame app,
about a minute. That calibration trains **both** decoders the product has for this stimulus (eCCA
and rCCA) on the same epochs and compares them with a **paired McNemar test** rather than two
percentages side by side. On the reference session they were **indistinguishable** (37 paired
decisions, 8 discordant, p = 0.727), so the model file declares its own decoder and you pick a
model, never an algorithm.

**What it is worth.** At 6 targets chance is 16.7 %. The only figure that exists is offline,
leave-one-out on the reference session: **59.5 % (eCCA) and 64.9 % (rCCA)**, an ITR around
22 bits/min with saline. So expect roughly **one designation in three to be wrong** — and expect
worse than that live, because no c-VEP has ever been decoded from a real brain *through the engine*.

**The pygame app** — the original all-in-one. It is no longer the only way to run any mode: with
c-VEP published on 2026-08-21, all six decode in the engine. What is left here is what the engine
cannot do — the **calibrations** for c-VEP, P300 and ErrP, whose protocols need a frame-locked
stimulus that a Qt window cannot render — plus the live histogram for neuro-monitoring. Motor
Imagery has fully moved out, calibration included. It owns the headset and publishes nothing.

Its former Motor Imagery and c-VEP **piloting** screens are not deleted, kept in
[`archive/`](archive/README.md) instead: still runnable (`--smoke`), and the reference the engine's
own version was checked against. `archive/cvep_pilot.py` is the one that still earns its keep — it
decodes c-VEP locally, on the same model and the same 2-of-3 vote as the engine, so a headset
session can run both on one head and see whether they name the same target. Without that
comparison, a poor network result cannot be told apart from a poor session. The Motor Imagery ones
write to `data/` under the old, fixed filenames, so running one **overwrites** whatever the console
last trained — read `archive/README.md` before reaching for them.

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
python examples/receiver.py --stream decoded_mi     # imagined left / right hand movement
python examples/receiver.py --stream decoded_p300   # which of 6 targets was selected
python examples/receiver.py --stream decoded_errp   # did the machine just get it wrong
python examples/receiver.py --stream decoded_cvep   # which coded target is being fixated
```

Any LSL client works — Python, MATLAB, C++, a game engine. Unity happens to have a worked example
in [`examples/unity/`](examples/unity/), for SSVEP. Two machines: see
[`docs/network.md`](docs/network.md).

| Stream | Contents |
|---|---|
| `EEG_API_Unicorn_raw` | 8 channels, µV, unfiltered, 250 Hz |
| `EEG_API_Unicorn_quality` | per-channel σ, ~1 Hz |
| `EEG_API_Unicorn_status` | engine state, JSON |
| `EEG_API_Unicorn_decoded_ssvep` | `{target_index, freq_hz, confidence, scores[]}`, ~5 Hz |
| `EEG_API_Unicorn_decoded_neuro` | `{charge, somnolence, engagement, artifact}`, ~5 Hz |
| `EEG_API_Unicorn_decoded_mi` | `{intent_index, confidence, p_GAUCHE, p_DROITE, p_REPOS}`, ~5 Hz |
| `EEG_API_Unicorn_decoded_p300` | `{target_index, confidence, n_flashes, score_0…score_5}`, one sample per round |
| `EEG_API_Unicorn_decoded_errp` | `{error, score, threshold, artifact}`, one sample per feedback |
| `EEG_API_Unicorn_decoded_cvep` | `{target_index, confidence, score_0…score_5, corr_min, margin}`, ~5 Hz |

⚠️ **Two stream metadata fields are frozen when the stream opens, and two channels are not.** LSL
fixes `desc()` at creation. The c-VEP thresholds (`corr_min`, `margin`) can be retuned mid-session
without rebuilding the stream, so they travel **twice**: in the metadata, the value that was in
force when the stream opened; in the last two channels, the value in force for *that sample*. Read
the metadata to know how a session was set up, and the channels when you score a recording later
without its LSL description. ErrP does the same with its `threshold` channel, for the same reason.

The stimulus is **not** rendered by the engine: your application flickers the targets and declares
their frequencies (`--refresh` or `--freqs`). A mismatch fails silently — the decoder correlates
against a sinusoid nobody is displaying — so pass the same refresh rate to both sides. For c-VEP
that coupling is tighter still: declaring the refresh rate is not enough, you must send a marker
every time the code restarts.

`ESC` returns to the menu from any mode; the BrainFlow session stays open, so switching modes is
instant. **Do not close and reopen the app mid-session** — C3/Cz saturate when the amplifier restarts.

## Decoding modes

**All six are decoded by the engine and published as streams.** The pygame app keeps only the
calibrations the engine cannot play. Stimulus frequencies and codes adapt automatically to the
display refresh rate.

| Mode | How it works | Calibration | Status |
|---|---|---|---|
| **SSVEP** | Arrows flicker at fixed frequencies; CCA picks the fixated one | 25 s rest baseline | ✅ most reliable; the only one validated on hardware **through the engine** |
| **c-VEP** | One m-sequence at circular shifts, learned template (eCCA or rCCA) | ~1 min, in the pygame app | ✅ **published as a stream** — your app flickers frame-by-frame and sends a clock marker per code cycle ([docs/markers.md](docs/markers.md)); 6 targets, ~22 bits/min, ~60-65 % offline |
| **P300** | Oddball: targets flash one by one, xDAWN + Riemannian geometry | ~4 min, in the pygame app | ✅ **published as a stream** — your app flashes and sends markers ([docs/markers.md](docs/markers.md)); AUC 0.71 |
| **Motor Imagery** | Imagined left/right fist squeeze, ERD on C3/C4, CSP + LDA | 5–7 min, **from the console** | ✅ **published as a stream**; left/right significant — plan for 63 %, see [Motor Imagery](#motor-imagery) |
| **Neuro-monitoring** | Passive spectral indices: workload, drowsiness, engagement | 25 s rest | 🟡 **published as a stream**, content not yet hardware-validated |
| **ErrP** | Error potential: single-trial detection when the machine errs | ~7 min (200 trials), in the pygame app | ✅ **published as a stream** — your app shows the feedback and sends markers ([docs/markers.md](docs/markers.md)); catches ~1 error in 2 at the default operating point (AUC 0.776) |

⚠️ **"Published" is not "validated".** Only SSVEP has been decoded from a real brain *through the
engine*. The other five were validated in the pygame app, and their engine path is verified without
a headset. Every accuracy figure on this page comes from **one person**, usually one session.

## Layout

The source splits in two, on a rule you can check rather than a matter of taste: **a module lives in
`core/` if and only if the engine needs it to run.** Everything else is `research/`. `research` may
import `core`; `core` must never import `research`. When a mode graduates from exploration to a
published stream, its decoder *moves* to `core/` — nobody threads an import across the boundary.
All six have now made that trip, c-VEP last, so nothing in `research/` is a decoder waiting its
turn any more.

### [`src/core/`](src/core/) — the engine, and therefore the product

| Module | What it does |
|---|---|
| [`server.py`](src/core/server.py) | The headless loop: acquire, decode, publish. Start here. |
| [`lsl_io.py`](src/core/lsl_io.py) | Stream publishers and the clock bridge — **the public contract** |
| [`acquisition.py`](src/core/acquisition.py) | Unicorn via BrainFlow: sliding windows, epochs, link check |
| [`cca_decoder.py`](src/core/cca_decoder.py) | SSVEP by CCA, no training, z-scored against a rest floor |
| [`neuro_monitor.py`](src/core/neuro_monitor.py) | Passive spectral indices, z-scored against a per-session rest |
| [`mi_decoder.py`](src/core/mi_decoder.py) | Motor Imagery by CSP + LDA — trained per person |
| [`mi_models.py`](src/core/mi_models.py) | Which trained MI models exist on disk, and which actually load |
| [`cvep_code.py`](src/core/cvep_code.py) | The m-sequence and the target plan — one code, one circular shift per target |
| [`cvep_decoder.py`](src/core/cvep_decoder.py) · [`cvep_rcca.py`](src/core/cvep_rcca.py) | The two c-VEP decoders, eCCA and rCCA, on the same stimulus |
| [`cvep_models.py`](src/core/cvep_models.py) | Which c-VEP models load, and **which decoder each file declares** |
| [`markers.py`](src/core/markers.py) | The engine's ear: resolves the incoming marker stream **by name**, one shared inlet |
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
| [`calib_page.py`](src/console/calib_page.py) | The **Calibrate** screen: briefing · live trial · honest result — Motor Imagery today |
| [`params_form.py`](src/console/params_form.py) | The settings form, generated from the contract. Validates nothing |
| [`live_views.py`](src/console/live_views.py) | Rendering picked by **family** — active, passive, raw traces |
| [`banner.py`](src/console/banner.py) | Channel quality and the detached-reference alarm, always visible |
| [`beeps.py`](src/console/beeps.py) | The calibration's lateralised audio cues — left/right ear tones, honest when audio is missing |

### [`src/research/`](src/research/) — everything not yet in the engine

Not a synonym for "unfinished" — several of these modes are hardware-validated. It means the engine
does not publish them yet, so they are not part of what students consume and may still change shape.

| Family | Modules |
|---|---|
| pygame app — **opens the headset itself**, never run it beside the engine | [`app.py`](src/research/app.py) (menu, five pages; calibrations and the neuro histogram) · `ui.py` · `viewing.py` |
| Stimulus emitters — **open no headset**, meant to run *beside* the engine in a second terminal | `ssvep_stimulus.py` · [`p300_stimulus.py`](src/research/p300_stimulus.py) · `errp_stimulus.py` · [`cvep_stimulus.py`](src/research/cvep_stimulus.py) — the last three publish markers, see [`docs/markers.md`](docs/markers.md) |
| Calibrations — long protocols, train a model into `data/` | `cvep_calibrate` · `p300_calibrate` · `errp_calibrate` |
| Offline analysis — replay, compare, measure | `cvep_analyze` · `p300_analyze` · `ssvep_analyze` · `mi_compare` · `itr` · `alpha_check` |
| Robot-testbed leftovers, kept as a baseline | `controller.py` · `live_ssvep.py` |

### [`archive/`](archive/) — retired, but still runs

Code that used to live in `research/` and was fully replaced — not deleted, because it is the
reference the replacement was checked against. Each file keeps its own `--smoke`. See
[`archive/README.md`](archive/README.md) for what moved where, and why running one can still
overwrite `data/mi_model.joblib`.

## Self-tests (no headset needed)

```bash
python src/core/server.py --smoke        # engine: registry, package boundary, shared rest, streams
python src/console/app.py --smoke        # console: grid, mode page, settings (Qt offscreen)
python src/core/lsl_io.py                # stream contract: channel names, round-trip, clock bridge
python src/core/cca_decoder.py           # CCA accuracy on synthetic SSVEP
python src/core/acquisition.py --synthetic  # acquisition alone, on the test board
python src/core/neuro_monitor.py         # spectral indices on synthetic EEG
python src/core/errp_decoder.py          # ErrP pipeline on synthetic error potentials
python src/core/errp_models.py           # ErrP models: legacy refused, degenerate refused, newest first
python src/core/modes/errp.py            # the ErrP mode: epoch alignment, artifact rejection, threshold monotonicity
python src/core/cvep_code.py             # m-sequence properties (balance, autocorrelation, lags)
python src/core/cvep_decoder.py          # c-VEP accuracy vs SNR on synthetic responses, model round-trip
python src/core/cvep_rcca.py             # the second c-VEP decoder, on the same shifted stimulus
python src/core/cvep_models.py           # c-VEP models: legacy refused, which decoder each declares, newest first
python src/core/modes/cvep.py            # the c-VEP mode: PHASE, the four causes of -1, the sliding vote
python src/core/markers.py               # the engine's ear: resolve BY NAME, time_correction

python src/research/app.py --smoke       # whole app headless: menu + every mode + calibrations
python src/research/errp_stimulus.py --smoke  # ErrP marker emitter: track, deliberate errors, stamped at flip
python src/research/p300_stimulus.py --smoke  # P300 flash sequence: every target seen `reps` times
python src/research/cvep_stimulus.py --smoke  # c-VEP clock emitter: phase read from the PIXELS, frame by frame
python src/research/controller.py        # SSVEP decode → smoothing → UDP, verified end to end
python src/research/itr.py               # information transfer rate — common yardstick
```

⚠️ Run them **one at a time**. Stream names are a public contract, so every instance publishes under
the same ones: a forgotten engine answers in place of the one you are testing.

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
