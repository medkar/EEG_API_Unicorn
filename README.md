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
> 2026-08-21**. Since **2026-09-08 the engine also plays all four calibrations**, and since
> **2026-09-09 there is no command left to type**: picking the source, checking your alpha,
> measuring the SSVEP rate, logging a session and watching the outgoing stream are all buttons, in
> one window that never has to be closed. ⚠️ Four of the six — MI, P300, ErrP, c-VEP — have
> **never been decoded from a real brain through the engine**, and neither moving the calibrations
> nor moving the measurements changed that: the pipe is verified end to end without a headset, the
> decoding was validated in the pygame app that has since been retired, and putting both halves on
> one head is the session that remains. See **[docs/SPEC.md](docs/SPEC.md)** for the stream contract
> and the roadmap.

## Requirements

Python 3.10+, an Unicorn Hybrid Black headset paired over Bluetooth.

```bash
pip install -r requirements.txt
```

## Run

**Start here: the console.** Since 2026-09-08 it is the only entry point you need — one window for
the whole path, and one you never have to close mid-session. Since 2026-09-09 it is also the only
thing you have to type: every real-use capability has a button, and a self-test fails if one
reappears as a command (see [Layout](#layout)).

```bash
outils\Console EEG.bat                        # double-click from the explorer, no terminal
python src/console/app.py                     # the same thing from a shell
python src/console/app.py --synthetic         # developer shortcut: skip the dialog, open the board
python src/console/app.py --mode ssvep        # start a mode straight away
```

**It asks what to open the session on** — the Unicorn headset, or BrainFlow's test board. ⚠️ **There
is no silent fallback.** A headset that refuses to open says so and the choice comes back; falling
through to the test board would record a whole session of manufactured signal while you believed it
was real, and nothing in the files would say otherwise. The banner repeats the source for as long
as the console runs. `--synthetic` still works and skips the dialog — that is a developer shortcut,
not the normal path.

**The engine** — no interface, streams over the network. This is the product; the console is a
client of it. Run it on its own when you want it headless, or beside a stimulus window in a second
terminal.

```bash
python src/core/server.py --mode ssvep --refresh 60   # acquire, decode, publish
python src/core/server.py --mode neuro                # passive: no stimulus, no calibration
python src/core/server.py --mode cvep                 # needs a trained model AND a clock emitter
python src/core/server.py --synthetic                 # no headset (BrainFlow test board)
```

⚠️ **Never run the console and the engine at the same time.** The console creates its own engine,
and stream names are a public contract — both would publish under the same names.

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

### What the console gives you

```bash
python src/console/app.py --mode ssvep,neuro      # start two modes at once (shared rest phase)
python src/core/server.py --no-raw --mode neuro   # engine only: decode without broadcasting raw
```

A grid of every mode. Each runnable tile has its own **Start**/**Stop**: launching with `--mode` is
a convenience for bringing up several modes at once (they then share one rest phase), not a
requirement. Open one and you get what it produces live, its settings, and a Python snippet that
consumes its stream, both generated from the mode's contract rather than written by hand. Across the
top, permanently: channel quality, a detached-reference alarm, and the state of the stimulus window
if one is running. The raw mode draws the eight channels themselves.

Settings are **not validated by the interface**. It submits, and shows the engine's refusal in its own
words — a rule copied into the UI drifts from the engine's eventually, and the day it drifts it lets
through a setting that decodes nothing, silently.

**Calibrate** — on all four modes that need a model (MI, P300, ErrP, c-VEP) since 2026-09-08. The
engine plays the session; the console shows it and judges it. For the three whose protocol needs a
frame-locked stimulus, the console also launches the window that renders it — a second process that
opens **no** headset, so the one Bluetooth connection stays with the engine.

Three things about that button are worth knowing before you press it:

- **A link check comes first.** Per-channel σ, the mode's own key channels highlighted, and a
  **refusal** if any of the eight is outside [0.5, 500] µV or the reference has come off. There is
  no override — a one-click bypass is a bypass you take by reflex. ⚠️ It has never been tried on a
  real headset, so it may yet block a legitimate session; if it does, that is worth reporting.
- **Nothing is written to `data/` until you say so.** The session ends by showing the figure it
  actually earned, and two buttons: **Save the model** or **Redo**. Before this, a calibration saved
  first and announced its accuracy afterwards — and since the engine offers the most recent loadable
  model as its default, a bad session silently became everyone's default.
- **A mode and its own calibration cannot run together**, and the engine refuses both orders: they
  would read the same marker queue and each would see a random half of it. The console stops the
  mode for you and says so.

**Launch stimulus** — the same window, without `--calibrer`, for the three modes that decode nothing
without one. Before this, the only way to run them was a second terminal.

**Session log** — a checkbox on the mode page, **ticked by default**, that hands the window `--log`.
It only appears where the stimulus registry says the window can write one, which today means c-VEP.
The window picks its own timestamped name under `seances/`; the console shows you where and writes
nothing itself. It is ticked by default because scoring a c-VEP session without that file is not
possible after the fact (see the recipe's test 2.9) — an unticked box would be a session lost by
omission.

### Checks and measurements

A second row of tiles, added 2026-09-09. A measurement is a timed protocol that returns a **verdict**
instead of a model: it writes nothing to disk, so there is no *Save* and no *Redo*. Only one timed
activity runs at a time — the engine refuses a calibration during a measurement and the reverse,
because there is one headset and two protocols would steal each other's windows.

- **Alpha check** (37 s) — eyes open, then eyes closed; the Berger effect on the occipital channels.
  It is a **barrier**, and the tile says so: if alpha does not rise, the electrodes or the reference
  are wrong and nothing else you measure today means anything. The verdict is a sentence that stops
  you, not a number to negotiate with, and it names what to check in order. When it passes, one
  click applies the measured peak to the SSVEP's `alpha_hz` setting — a value you used to write on
  paper and retype into another screen.
- **SSVEP emission rate** (3.6 min) — a window flickers the configured targets (three at the
  repository's defaults) and *designates* the one to fixate; the engine applies its own decision
  rule and reports how often it commits and how often it is right when it does. **One trial counts
  as one decision**: the engine's windows overlap (1.5 s every 0.2 s), so counting them would
  inflate the sample by a factor of about 7 and shrink the confidence interval by √7 for nothing.

⚠️ Both numbers of the SSVEP measurement are read **together**. The reference measured on hardware
on 2026-07-27 is *100 % accurate whenever it commits, but it only commits 44 % of the time*. Either
figure alone misleads: the second without the first makes a perfectly normal silence look like a
breakdown.

### What your app sees

A button at the bottom of the grid opens the outgoing side: it resolves the LSL streams on the
network, opens one, and shows its channel names and values scrolling by. ⚠️ **It reads over LSL,
like any client — never the engine's internal state.** That is the honest version: if the panel
shows values, a real client would see them too. A panel wired to `snapshot()` would scroll happily
while the network was silent, which is exactly the failure you came here to look at.

**Record the verdicts** — one button on that page writes a JSONL file to `seances/`, one line per
**published** decision, timestamped on the LSL clock. The engine holds the pen; the console sends
two commands and reads where it writes. One line per *published* decision and not per loop turn: a
mode that only emits 44 % of the time would otherwise re-read as 100 %, and the file would lie about
the one quantity you opened it for.

⚠️ `seances/` is gitignored and sits **outside `data/`**. A session verdict is neither a model nor an
EEG recording, and `data/` keeps its single writer.

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
person: the **Alpha check** tile measures it and offers to apply it, so the value never has to be
copied between two screens.

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
python src/stimulus/cvep.py                 # terminal 2: flicker, and send the clock
```

Or press **Launch stimulus** on the c-VEP page of the console, which starts the same window for you.

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

Like MI, P300 and ErrP it needs a **model trained on you** — one calibration, from the console's
**Calibrate** button, about three minutes. (The exact length is computed and printed when it starts;
at the repository's settings the window prints 2.8 min, and the console announces 3.1 min because
it counts the engine's 15 s warm-up.) That calibration trains
**both** decoders the product has for this stimulus (eCCA and rCCA) on the same epochs and compares
them with a **paired McNemar test** rather than two percentages side by side. On the reference
session they were **indistinguishable** (37 paired decisions, 8 discordant, p = 0.727), so the model
file declares its own decoder and you pick a model, never an algorithm.

**What it is worth.** At 6 targets chance is 16.7 %. The only figure that exists is offline,
leave-one-out on the reference session of 2026-07-21: **59.5 % (eCCA) and 64.9 % (rCCA)** over 37
paired decisions. At the engine's own geometry — 2 code cycles, so one decision every 2.10 s — that
is **19.1 bits/min for eCCA and 23.8 for rCCA**, which the calibration screen itself calls
**WEAK**: under half of the 25.0 bits/min the SSVEP already delivers. (Recomputable:
`research/itr.py`, and asserted in `archive/cvep_calibrate.py`. An earlier "~22 bits/min" had
no traceable source, and the screen printed exactly twice the truth until 2026-09-03.)

⚠️ Those bits/min assume **one decision published per window**. The engine publishes far fewer: it
emits only past two thresholds *and* a 2-of-3 vote, which offline fires on **46 % of windows** at
the default 0.26/0.09 (`core/config.py`). Expect roughly **half** that rate out of `decoded_cvep` —
and expect worse still live, because no c-VEP has ever been decoded from a real brain *through the
engine*. Roughly one designation in three is wrong even offline.

### The stimulus windows

Four programs, in `src/stimulus/`, one per paradigm that needs something on screen. They render a
frame-locked stimulus and publish markers — and they open **no headset**, which is the whole point:
they run beside the engine rather than instead of it.

```bash
python src/stimulus/p300.py                # the oddball ring
python src/stimulus/errp.py                # the cursor-to-target track
python src/stimulus/cvep.py                # the six flickering discs, and the clock
python src/stimulus/ssvep.py               # the flickering arrows (three at the default settings)
python src/stimulus/ssvep.py --guide       # the same, designating a target per trial (ground truth)
python src/stimulus/cvep.py --calibrer     # the same, wrapped in a calibration protocol
python src/stimulus/cvep.py --log s.jsonl  # ground truth to a FILE — required to score a session
```

You normally never type these: the console launches them for you, with `--calibrer` when you press
**Calibrate**, with `--guide` when you start the SSVEP emission-rate measurement, and bare when you
press **Launch stimulus**. Type them when you need an option the buttons do not pass — the launcher
sends the file path, `--calibrer` and the session log, so `--seed`, `--no-wait` (ErrP), `--refresh`
and `--windowed` are hand-launch only. Run `--help` on any of the four for its own list.

The SSVEP window moved here from `research/` on 2026-09-09 and gained `--guide`; the three others
arrived on 2026-09-07.

### The pygame app is gone

`src/research/app.py` was deleted on 2026-09-08. Six of its seven pages live in
[`archive/`](archive/README.md), each still runnable with its own `--smoke`: three **piloting**
screens (SSVEP, P300 selection, the ErrP demonstrator) and three **calibrations** (c-VEP, P300,
ErrP). They are kept for one reason — they decode **locally**, in the program that draws, which is
what separates "the network decoding is worse" from "the session is worse" on one and the same
fixation. `archive/cvep_pilot.py` is the clearest case: same model, same 2-of-3 vote as the engine.

Three more retirements followed on 2026-09-09, when "no command to type" became a rule a test can
fail on: `alpha_check.py` (now the Alpha check tile), `live_ssvep.py` — a **seventh** piloting
screen the previous cleanup had missed — and `ui.py`, the shared pygame machinery that eight of the
archived screens import and that nothing living used any more.

⚠️ They open the headset themselves, so **run only one program at a time** — the console, the
engine, or one archived screen. Two of them (`mi_calibrate.py`, `mi_pilot.py`) still write to
`data/` under the old, fixed filenames, so running one **overwrites** what the console last trained.
Read `archive/README.md` before reaching for any of them.

⚠️ Their epoching is not the engine's: they cut on the pygame clock, the engine cuts on the LSL
timestamps of incoming markers. For a session that matters, go through the console.

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

`receiver.py` is the *example* — the thing you copy into your own project. To simply **look** at
what is on the network, the console's **What your app sees** page does the same job without a second
terminal, and its **Record the verdicts** button files the session for you.

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

**Do not close and reopen the program that holds the headset mid-session** — C3/Cz saturate when the
amplifier restarts. That is the practical reason the console became the single entry point: contact
check, calibration and decoding now all happen in one window, so a whole session needs the headset
opened exactly once. `ESC` closes a stimulus window without touching that session.

## Decoding modes

**All six are decoded by the engine and published as streams, and all four calibrations are played
by it too.** Stimulus frequencies and codes adapt automatically to the display refresh rate.

| Mode | How it works | Calibration | Status |
|---|---|---|---|
| **SSVEP** | Arrows flicker at fixed frequencies; CCA picks the fixated one | 25 s rest baseline | ✅ most reliable; the only one validated on hardware **through the engine** |
| **c-VEP** | One m-sequence at circular shifts, learned template (eCCA or rCCA) | ~3 min, **from the console** | ✅ **published as a stream** — your app flickers frame-by-frame and sends a clock marker per code cycle ([docs/markers.md](docs/markers.md)); 6 targets, ~60-65 % offline → 19.1 (eCCA) / 23.8 (rCCA) bits/min, **WEAK** vs the SSVEP's 25.0 |
| **P300** | Oddball: targets flash one by one, xDAWN + Riemannian geometry | ~2.2 min, **from the console** | ✅ **published as a stream** — your app flashes and sends markers ([docs/markers.md](docs/markers.md)); AUC 0.71 |
| **Motor Imagery** | Imagined left/right fist squeeze, ERD on C3/C4, CSP + LDA | 5–7 min, **from the console** | ✅ **published as a stream**; left/right significant — plan for 63 %, see [Motor Imagery](#motor-imagery) |
| **Neuro-monitoring** | Passive spectral indices: workload, drowsiness, engagement | 25 s rest | 🟡 **published as a stream**, content not yet hardware-validated |
| **ErrP** | Error potential: single-trial detection when the machine errs | ~5.7 min (200 trials), **from the console** | ✅ **published as a stream** — your app shows the feedback and sends markers ([docs/markers.md](docs/markers.md)); catches ~1 error in 2 at the default operating point (AUC 0.776) |

⚠️ **"Published" is not "validated", and "calibrated by the engine" is not either.** Only SSVEP has
been decoded from a real brain *through the engine*. Four of the others — MI, P300, ErrP, c-VEP —
were validated in the pygame app that has since been retired, and their engine path is verified
without a headset. Moving the four calibrations into the engine on 2026-09-08 **measured nothing**:
it is a change of gesture, tested between two processes on a synthetic board. Moving the two
measurements in on 2026-09-09 measured nothing either, for the same reason: **not one figure on
this page was produced, changed or re-derived by that work.** **Neuro-monitoring has never been
validated at all**: its plumbing is tested, its content is not, anywhere. Every accuracy figure on
this page comes from **one person**, usually one session.

## Layout

Four packages, on a rule you can check rather than a matter of taste: **a module lives in `core/` if
and only if the engine needs it to run.**

```text
core       imports nothing else from this repository   (not research, not console, not stimulus)
stimulus   -> core                                     (never research, never console)
console    -> core, stimulus
research   -> core, stimulus
```

The prohibitions are enforced by a test, not by discipline: `python src/core/server.py --smoke`
parses every file in `src/core/`, `src/stimulus/` and `src/research/` as an AST and fails on a
single forbidden import. No pygame and no Qt in `core`, either — the engine runs on a machine
without a screen.

**And nothing in `research/` may import `core.acquisition`, `brainflow` or `pygame`** (2026-09-09).
The bench can *compute* anything it likes on archived files — that is its job — but opening the
headset and drawing a stimulus are real use, and real use is driven from the application. This is
the mechanical form of "no command to type": a capability shipped without a graphical path is an
unfinished task, not one to finish later. The rule had been asked for five times between July and
September 2026 without being written anywhere, and each cleanup rediscovered it by failing.

When a module needs to cross a boundary upwards, it *moves* rather than reaching: that is how all
six decoders arrived in `core/`, c-VEP last, how three stimulus windows became a package of their
own on 2026-09-07, and how the fourth (SSVEP) plus the alpha check followed on 2026-09-09.

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
| [`modes/`](src/core/modes/) | One contract per mode (`ModeSpec`) beside its runtime — what it is, what you can set, what it publishes. Plus `mesure.py` and its two protocols, `alpha.py` and `ssvep_mesure.py`, which return a **verdict** instead of a model |

No pygame and no Qt anywhere in here: the engine runs on a machine without a screen. A self-test
enforces it rather than trusting discipline.

### [`src/console/`](src/console/) — the desktop console, a client of the engine

It creates an engine, runs its loop in a thread, and polls `snapshot()`. Nothing else. Two rules hold
it together: the Qt thread never touches the BrainFlow session — every action goes through the
engine's command queue — and no logic lives here that the engine does not already own.

| Module | What it does |
|---|---|
| [`app.py`](src/console/app.py) | The window: reads state, sends commands, and the headless self-test |
| [`demarrage.py`](src/console/demarrage.py) | The startup dialog: headset or test board. **Never falls back in silence** |
| [`grid.py`](src/console/grid.py) | The tiles — every mode, every measurement, and the way out to the stream |
| [`mode_page.py`](src/console/mode_page.py) | One page per mode: live output · settings · how to consume it |
| [`calib_page.py`](src/console/calib_page.py) | The **Calibrate** screen: briefing · live session · honest result · **Save / Redo** — all four modes that need a model |
| [`mesure_page.py`](src/console/mesure_page.py) | Its twin for a **measurement**: briefing · live session · verdict. No Save, no Redo — a measurement writes nothing |
| [`flux_page.py`](src/console/flux_page.py) | **What your app sees**: the LSL streams, read as a client, plus the record button |
| [`contact_page.py`](src/console/contact_page.py) | The link check that stands between **Start** and anything expensive. Computes no verdict — it displays the engine's, and refuses |
| [`fenetres.py`](src/console/fenetres.py) | Launches one stimulus window as a second process, with its options, and says when it dies |
| [`params_form.py`](src/console/params_form.py) | The settings form, generated from the contract. Validates nothing |
| [`live_views.py`](src/console/live_views.py) | Rendering picked by **family** — active, passive, raw traces |
| [`banner.py`](src/console/banner.py) | The source in force, channel quality, the detached-reference alarm, and the stimulus window's state — always visible |
| [`beeps.py`](src/console/beeps.py) | The lateralised audio cues of the MI calibration, and the neutral step tone a measurement needs — you cannot read a screen with your eyes shut |

### [`src/stimulus/`](src/stimulus/) — the four windows that draw and mark

Created 2026-09-07 with three windows; SSVEP joined on 2026-09-09. They render a frame-locked
stimulus and publish markers, and they **open no headset** — which is exactly what lets them run
beside the engine, or be launched by the console as a second process. Each one plays its paradigm
twice: as a plain stimulus, and as a protocol that publishes ground truth (`--calibrer`, or
`--guide` for SSVEP).

| Module | What it does |
|---|---|
| [`p300.py`](src/stimulus/p300.py) | The oddball ring: `flash` · `round_end`, plus `calib_start` · `cue` · `calib_end` |
| [`errp.py`](src/stimulus/errp.py) | The cursor-to-target track: `feedback`, which gains `error` **in calibration only** |
| [`cvep.py`](src/stimulus/cvep.py) | Six flickering discs and the `cycle` clock, plus `cue` · `block_end` around it |
| [`ssvep.py`](src/stimulus/ssvep.py) | Three flickering arrows; with `--guide`, `calib_start` · `repos` · `cue` · `calib_end` |
| [`refresh.py`](src/stimulus/refresh.py) | Measures the real refresh rate of the screen that will show the stimulus |
| [`registry.py`](src/stimulus/registry.py) | Key → command line, and which windows can write a session log. The only file in the repo that names a window module |

### [`src/research/`](src/research/) — the bench, not the product

Not a synonym for "unfinished" — several of these were hardware-validated. It means the engine does
not publish them, so they are not part of what students consume and may still change shape. There is
no longer an application here, no decoder, no calibration, and since 2026-09-09 **nothing that opens
the headset or draws on screen**: all six decoders moved to `core/`, all four calibrations are the
engine's, the two measurements followed, and the pygame screens went to `archive/`. What is left
computes on files that were recorded earlier.

| Family | Modules |
|---|---|
| Offline analysis — replay, compare, measure | `cvep_analyze` · `p300_analyze` · `ssvep_analyze` · `ssvep_guided` (replays an archived guided run with other settings) · `mi_compare` · `itr` · `calibrate` |
| Stimulus geometry, on paper | `viewing.py` — target size and spacing in **degrees of visual angle**, the least controlled parameter of these measurements |
| Refuted hypotheses, kept readable | `cvep_rcca.py` — the **Gold code factory**, not a decoder (the rCCA *decoder* is published, in `core/`); only `archive/cvep_rcca_pilot.py` still calls it |
| Robot-testbed leftovers, kept as a baseline | `controller.py` |

### [`archive/`](archive/) — retired, but still runs

Thirteen files that used to live in `research/` and were fully replaced — not deleted, because they
are the reference the replacement was checked against, and because they decode **locally**, which is
the only way to tell "the network decoding is worse" apart from "the session is worse". Six arrived
on 2026-09-08 with the pygame app's deletion (three pilots, three calibrations), three more on
2026-09-09: the alpha check, a seventh pilot screen, and `ui.py`.

Twelve of the thirteen keep their own `--smoke`; `ui.py` has none because there is nothing to run in
it — it is the shared pygame machinery (`App`, `Abort`, `signal_check`) that eight of the others
import, and those eight cover it. See [`archive/README.md`](archive/README.md) for what moved where,
and why running one can still overwrite `data/mi_model.joblib`.

## Self-tests (no headset needed)

```bash
python src/core/server.py --smoke        # engine: registry, package boundary (core, stimulus AND
                                         #   research), shared rest, streams, marker theft,
                                         #   save/discard, session recording
python src/console/app.py --smoke        # console: grid, mode page, settings, link check, window
                                         #   launcher, launch ORDER, startup screen, measurement
                                         #   page, stream page (Qt offscreen)
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

python src/core/modes/marker_calib.py    # the base class of the three window-led calibrations:
                                         #   the two epochings agree, on two geometries
python src/core/modes/p300_calib.py      # P300 training: cue -> label, flash -> epoch
python src/core/modes/errp_calib.py      # ErrP training: the label rides on the feedback itself
python src/core/modes/cvep_calib.py      # c-VEP training: the phase is CALLED, never copied
python src/core/modes/mi_calib.py        # MI training: honest accuracy, never overwrites
python src/core/errp_track.py            # the ErrP track: one written protocol, two screens

python src/core/modes/mesure.py          # the base class of the two measurements: the timeline, and
                                         #   the refusal of a SECOND timed activity, both ways
python src/core/modes/alpha.py           # the alpha check: detrend held, flat channels refused
python src/core/modes/ssvep_mesure.py    # the emission rate: ONE TRIAL IS ONE DECISION

python src/stimulus/registry.py          # key -> command, checked against the contract BOTH ways
python src/stimulus/errp.py --smoke      # ErrP window: track, deliberate errors, stamped at flip,
                                         #   and the ground-truth guard in BOTH directions
python src/stimulus/p300.py --smoke      # P300 flash sequence: every target seen `reps` times
python src/stimulus/cvep.py --smoke      # c-VEP clock: phase read from the PIXELS, frame by frame
python src/stimulus/ssvep.py --smoke     # SSVEP arrows: cue read from the PIXELS, trials interleaved

# The twelve retired screens keep their own --smoke; see archive/README.md. No self-test above runs
# them.
python src/research/controller.py        # SSVEP decode → smoothing → UDP, verified end to end
python src/research/itr.py               # information transfer rate — common yardstick
python src/research/ssvep_guided.py --smoke   # replays an archived guided run, offline
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
