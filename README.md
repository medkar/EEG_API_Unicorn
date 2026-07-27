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
> Modes beyond SSVEP are decoded by the pygame app but not yet published as streams — see
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
python src/server.py --mode ssvep --refresh 60   # acquire, decode, publish
python src/server.py --synthetic                 # no headset (BrainFlow test board)
```

**The dashboard** — the engine plus a local web page, at <http://localhost:8000>.

```bash
python src/dashboard.py --mode ssvep --refresh 60
```

Live channel quality, a detached-reference alarm, the decoded target against its threshold, and the
controls. Its `/docs` page documents the HTTP API interactively.

**The pygame app** — the original all-in-one, still the only way to run c-VEP, P300, MI, ErrP and
neuro-monitoring. It owns the headset and publishes nothing.

```bash
python src/app.py                 # fullscreen, real headset — main menu
python src/app.py --windowed      # windowed (keeps the console visible)
python src/app.py --synthetic     # no headset (BrainFlow synthetic board)
python src/app.py --smoke         # headless end-to-end self-test (CI)
```

⚠️ The engine and the app both open the headset, so **run only one at a time**.

## Consume the stream

The client depends on `pylsl` and nothing else — not on this repository.

```bash
pip install pylsl
python examples/receiver.py --list                  # what is on the network
python examples/receiver.py --stream decoded_ssvep  # which target is being looked at
```

Unity: see [`examples/unity/`](examples/unity/). Two machines: see
[`docs/network.md`](docs/network.md).

| Stream | Contents |
|---|---|
| `EEG_API_Unicorn_raw` | 8 channels, µV, unfiltered, 250 Hz |
| `EEG_API_Unicorn_quality` | per-channel σ, ~1 Hz |
| `EEG_API_Unicorn_status` | engine state, JSON |
| `EEG_API_Unicorn_decoded_ssvep` | `{target_index, freq_hz, confidence, scores[]}`, ~5 Hz |

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
| **Neuro-monitoring** | Passive spectral indices: workload, drowsiness, engagement | 25 s rest | 🟡 coded, being validated |
| **ErrP** | Error potential: single-trial detection when the machine errs | ~4 min | 🟡 demonstrator, needs real calibration |

## Layout

| Part | Where |
|---|---|
| Engine — acquisition, decoding, LSL streams | [`src/server.py`](src/server.py) |
| Stream contract — publishers, clock bridge | [`src/lsl_io.py`](src/lsl_io.py) |
| Web dashboard — server and page | [`src/dashboard.py`](src/dashboard.py) · [`src/dashboard.html`](src/dashboard.html) |
| pygame app — menu and all six modes | [`src/app.py`](src/app.py) |
| Shared config — channels, frequencies, codes, per-mode constants | [`src/config.py`](src/config.py) |
| Acquisition — Unicorn via BrainFlow, sliding windows and epochs | [`src/acquisition.py`](src/acquisition.py) |
| Shared window, headset session, signal-quality screen | [`src/ui.py`](src/ui.py) |
| Decoders | `cca_decoder` · `cvep_decoder` · `mi_decoder` · `p300_decoder` · `errp_decoder` · `neuro_monitor` |
| Calibrations | `mi_calibrate` · `cvep_calibrate` · `p300_calibrate` · `errp_calibrate` |
| Offline analysis | `cvep_analyze` · `p300_analyze` · `ssvep_analyze` · `mi_compare` · `itr` |

## Self-tests (no headset needed)

```bash
python src/server.py --smoke         # engine + streams + SSVEP decoding, end to end
python src/dashboard.py --smoke      # engine + HTTP API + page
python src/lsl_io.py                 # stream contract: channel names, round-trip, clock bridge
python src/app.py --smoke            # whole app headless: menu + every mode + calibrations
python src/cvep_code.py              # m-sequence properties (balance, autocorrelation, lags)
python src/cvep_decoder.py           # c-VEP accuracy vs SNR on synthetic responses
python src/cca_decoder.py            # CCA accuracy on synthetic SSVEP
python src/errp_decoder.py           # ErrP pipeline on synthetic error potentials
python src/neuro_monitor.py          # spectral indices on synthetic EEG
python src/itr.py                    # information transfer rate — common yardstick
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
