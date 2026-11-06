# EEG API Unicorn

A **brain-computer interface API for students**: it acquires an **Unicorn Hybrid Black** EEG
headset, decodes it with ready-made paradigms, and **streams the result over the network**, so any
application (Unity, Python, MATLAB, ROS 2, a microcontroller on the Wi-Fi) can build on it.

```
Unicorn headset ──► acquisition ──► decoding (SSVEP · c-VEP · P300 · Motor Imagery · ErrP · Neuro) ──► network ──► your application
```

The tool is **agnostic of what you build**. Each mode publishes a **neutral intent** (which
target, which class, which mental state), never an actuator command. Turning that intent into an
action (a game event, a light, a robot movement) is your application's job.

Everything happens in **one window, the console**: choose the headset, check the electrodes, set a
mode up, train it, test it, decode, watch what leaves on the network, and connect your
application. No command to type.

## Install

1. Download `EEG-API-Unicorn-Setup-<version>.exe` from the
   [Releases page](https://github.com/medkar/EEG_API_Unicorn/releases).
2. Run it. The installer is **not signed**: Windows SmartScreen shows a warning the first time.
   Click **More info**, then **Run anyway**.
3. Choose **Install for all users** if you can: the installer then allows the application through
   the Windows firewall, which applications on other computers and network devices need to reach
   it. Installed for you only, Windows asks the first time the console listens to the network:
   allow it, **public networks included** (a phone hotspot or a campus Wi-Fi is often public).

No Python needed. Pair the headset with Windows (Bluetooth) before the first launch.

**Where your work goes**: trained models in `Documents\EEG API Unicorn\modeles`, recorded session
verdicts in `Documents\EEG API Unicorn\seances`. Uninstalling the application keeps both.

## First launch

The console first asks **what to open the session on**: your Unicorn headset (by its serial
number; the console remembers the last ones), or BrainFlow's **test board**, a synthetic signal for
trying everything without a headset. It also asks the **mains frequency** (50 Hz in Europe, 60 Hz
in the Americas), used by every filter. There is **no silent fallback**: a headset that refuses to
open says so and the question comes back. Falling through to the test board would record a whole
session of manufactured signal while you believed it was real.

The console speaks English and French: the **🌐** button at the top right switches the display at
once. Only the display changes; what your application receives is always in English.

Then, in this order:

1. **Check the headset** (37 s, the tile marked *GATE*): eyes open, then eyes closed. If the alpha
   rhythm does not rise, the electrodes or the reference are wrong, and nothing else you measure
   today means anything. Its page shows each electrode's contact on a map of the head.
2. **Open a mode**. Each page has numbered steps: **1. Set up**, **2. Train** (for the modes that
   need a model), **3. Test**. A guided test gives a score; a **free test** lets you try the mode
   with its stimulus window and a green ring around the target it decodes.
3. **Start** a mode from its tile to decode continuously and publish on the network.

⚠️ Do not close and reopen the console in the middle of a session: the amplifier restarts and two
channels saturate for a while. Train, test and decode in the same window.

## The six modes

| Mode | What it decodes | Training | What it is worth (measured here, one person) |
|---|---|---|---|
| **SSVEP** | which flickering target you look at (a screen, or LEDs) | none (25 s of rest) | 100 % correct when it decides, but it decides 44 % of the time |
| **c-VEP** | which target of one shifted code you look at | ~3 min | ~60-65 % at 6 targets, offline |
| **P300** | which of several flashing targets you attend to | ~2 min | AUC 0.71 |
| **Motor Imagery** | which movement you imagine (left/right fist, or your own tasks) | 5-7 min | left/right: plan for ~63 % |
| **ErrP** | that you saw the machine make a mistake | ~6 min | catches about 1 error in 2 (AUC 0.776) |
| **Neuro** | workload, drowsiness, engagement, against your own rest | none (25 s of rest) | not validated |

These figures come from **one person**, a few sessions: they say what to expect, not what you will
get. A model belongs to the person it was trained on. Someone else's model gives plausible numbers
that are wrong.

What each mode asks of your application:

- **SSVEP**: your application shows the flickering targets. On a screen, each frequency must divide
  the screen's refresh rate (the **Suggest** button finds a valid set, away from the person's alpha
  peak). On LEDs, set the targets to *physical* and any frequency in the band is accepted.
- **c-VEP and P300**: your application shows the stimulus **and** sends the engine a marker at the
  right instant (see [docs/markers.md](docs/markers.md)). The stimulus windows of this project are
  reference implementations. For the c-VEP, the marker is a **clock**: stamp it after the frame is
  shown, never before, or the decoding fails without an error.
- **Motor Imagery**: nothing to show. `intent_index = -1` means "the vote did not conclude", not
  "rest". Add a rest task when training if your application needs to know when the user does
  nothing.
- **ErrP**: your application shows a result and sends a marker. At the default setting it catches
  one error in two and cancels one good command in seven.
- **Neuro**: nothing to show; its values are z-scores against a rest measured at the start, for
  this person, today. They compare across neither people nor sessions.

## Connect your application

**Start with the integration guide**:
[English (PDF)](docs/guide/guide-en.pdf) · [français (PDF)](docs/guide/guide-fr.pdf). It shows how to
connect an application with a ready-made client and its configuration file, how to train the
models, what your application receives, and the protocol for writing your own client.

**Ready-made clients** are in [`clients/`](clients/README.md): Python (LSL), Raspberry Pi (UDP),
ROS 2, Unity, MATLAB, ESP32 and Arduino UNO R4 WiFi. Each one performs the handshake; what changes
from one application to another is in one configuration file, and your code goes in its decision
handler.

In the console, **Connect an application** lists the applications of the local network (with the
computer they run on) and the network devices that announce themselves (with their address and
identifier; **Identify** makes the chosen one blink). Pick yours and click **Connect**: before
that click, nothing reaches the engine, so a neighbour's application cannot drive yours. The
console then shows a control page: the electrodes, the settings your application sent, the live
decoding, and its latest commands. For a mode with a model, choose the model there and click
**Start decoding**.

Your application can then set a mode up, start it and stop it with four JSON commands; the
contract, the settings of every mode and a minimal client are in [docs/control.md](docs/control.md).
A device without LSL (a microcontroller) sends the same commands over UDP (SSVEP, Motor Imagery and
Neuro). Two computers, a firewall, a hotspot: see [docs/network.md](docs/network.md).

### What your application receives

Every stream is an [LSL](https://labstreaminglayer.readthedocs.io/) stream named
`EEG_API_Unicorn_<suffix>`. The console's **What your app sees** window reads them exactly as a
client would, and **Record verdicts** saves every published decision to a file.

| Stream | Contents |
|---|---|
| `EEG_API_Unicorn_raw` | 8 channels, µV, unfiltered, 250 Hz |
| `EEG_API_Unicorn_quality` | per-channel signal level, ~1 Hz |
| `EEG_API_Unicorn_status` | the engine's state, JSON |
| `EEG_API_Unicorn_decoded_ssvep` | `target_index, freq_hz, confidence, score_<f>Hz…`, ~5 Hz |
| `EEG_API_Unicorn_decoded_cvep` | `target_index, confidence, score_0…, corr_min, margin`, ~5 Hz |
| `EEG_API_Unicorn_decoded_p300` | `target_index, confidence, n_flashes, score_0…`, one per round |
| `EEG_API_Unicorn_decoded_mi` | `intent_index, confidence, p_0…`, ~5 Hz |
| `EEG_API_Unicorn_decoded_errp` | `error, score, threshold, artifact`, one per result shown |
| `EEG_API_Unicorn_decoded_neuro` | `charge, somnolence, engagement, artifact`, ~5 Hz |
| `EEG_API_Unicorn_replies` | the engine's reply to each command of your application, JSON |

`-1` as an index always means **no decision**, never target 0. The names of the targets or tasks
of a trained model are in the stream's description (`target_names`, `classes`). The description
also carries `paradigm` and `decision_scale`: a threshold means nothing without its scale.

The simplest client is [`examples/receiver.py`](examples/receiver.py) (it needs `pylsl` only):

```bash
pip install pylsl
python examples/receiver.py --list                  # what is on the network
python examples/receiver.py --stream decoded_ssvep  # which target is being looked at
```

Other examples: [`examples/control_client.py`](examples/control_client.py) drives the engine over
LSL; [`examples/udp_device.py`](examples/udp_device.py) plays a network device over UDP (standard
library only); [`examples/esp32_leds/`](examples/esp32_leds/) is a real ESP32 driving two LEDs;
[`examples/actuator_udp.py`](examples/actuator_udp.py) turns an intent into an action, which belongs
to the client, never to the API.

## Run from the sources

Python 3.12 or 3.13 on Windows.

```bash
pip install -r requirements.txt
outils\Console EEG.bat                       # the console (double-click from the explorer)
python src/console/app.py                    # the same from a terminal
python src/core/server.py --mode ssvep       # the engine alone, without a screen
python src/core/server.py --synthetic        # ... on the test board
```

From the sources, models go to `data/` and session verdicts to `seances/`, at the root of the
repository. Run **one** program at a time (the console or the engine): the headset accepts one
connection, and every engine publishes under the same stream names.

The code is split into three packages, on a rule a test checks: `src/core/` is what the engine
needs to run (no Qt, no pygame: it runs without a screen), `src/stimulus/` the stimulus windows,
`src/console/` the console. `core` imports neither of the others; `stimulus` imports `core`;
`console` imports both. `src/eeg_api_unicorn.py` is the single entry point of the installed
program.

### Self-tests (no headset needed)

```bash
python src/core/server.py --smoke     # the engine: streams, modes, package boundaries, texts, examples
python src/console/app.py --smoke     # the console, without a screen
python src/core/i18n.py               # every text displayed is in the catalogues, in both languages
```

Most modules of `src/core/` and `src/stimulus/` also test themselves when run directly
(`python src/core/modes/cvep.py`, `python src/stimulus/ssvep.py --smoke`…). Run the tests **one at
a time**, with no console or engine open: they publish under the public stream names.

### Build the installer

See [`build/LISEZMOI.md`](build/LISEZMOI.md) (in French): PyInstaller, then Inno Setup.

## Good to know

- **Signal quality decides everything.** Wet the electrodes with saline: it is the biggest lever
  measured. A detached reference ruins a whole session, and the engine watches for it.
- **Compare paradigms by information transfer rate**, not by accuracy: 70 % over 6 targets is worth
  far more than 70 % over 3.
- **Small EEG samples lie.** Validate a hypothesis with a permutation test or an honest
  cross-validation before believing it.

## License

EEG API Unicorn is released under the [MIT License](LICENSE): the program, the clients, the
examples and the tools. You may copy a client library into your own application, whatever its
licence.

The installer also bundles libraries written by others (Python, Qt, BrainFlow, NumPy, SciPy,
pygame…). Their licences are in `THIRD-PARTY-NOTICES.txt`, in the installation folder. Some of
them are under the GNU LGPL (Qt, PySide6, pygame, FFmpeg): their source code is available at the
addresses given in that file and in the notes of
[each release](https://github.com/medkar/EEG_API_Unicorn/releases).
