# EEG_API_Unicorn applications

Ready-made code to connect an application to EEG_API_Unicorn, one folder per platform. Each
platform has two folders:

- **`client/`**: the library alone, to start from scratch in your own project;
- **`exemple/`**: a complete application that runs as it is. It holds a copy of the library, the
  configuration file and the example program: copy this folder into your workspace, edit the
  configuration file, run it, then put your code in the decision handler.

Each library performs the whole handshake of [`docs/control.md`](../docs/control.md): it finds
the engine, waits to be connected, sends its settings, starts the mode, receives the decisions,
and stops what it started when it ends. Do not edit the library files: everything that changes
from one application to another is in the configuration file.

| Platform | For | Transport | Configuration file (`exemple/`) | Your code (`exemple/`) |
|---|---|---|---|---|
| [`Python/`](Python/) | Python 3 on a computer | LSL | `config.json` | `on_decision()` in `cibles_ssvep.py` or `example.py` |
| [`RaspberryPi/`](RaspberryPi/) | Python 3, standard library only: Raspberry Pi, any Linux board | UDP | `config.json` | `on_decision()` in `example.py` |
| [`ROS2/`](ROS2/) | ROS 2 (on a Raspberry Pi or any computer) | UDP | `eeg_api_ros_example/config/params.yaml` | a node subscribed to `eeg/target` |
| [`Unity/`](Unity/) | Unity 6 | LSL | `client/StreamingAssets/eeg_api_config.json` | `onTargetChanged`, or `IntentToMotion.cs` in `exemple/` |
| [`MATLAB/`](MATLAB/) | MATLAB R2016b or later | LSL | `config.json` | `onDecision()` in `example.m` |
| [`ESP32/`](ESP32/) | ESP32 (Arduino) | UDP over Wi-Fi | `config.h` | `onDecision()` in `exemple.ino` |
| [`ArduinoR4WiFi/`](ArduinoR4WiFi/) | Arduino UNO R4 WiFi | UDP over Wi-Fi | `config.h` | `onDecision()` in `exemple.ino` |

[`Protocole/`](Protocole/) is not a platform: it holds three Python scripts that show the raw
protocol, step by step, for writing a client in a language not covered here, and a script that
prints any stream of the engine.

## LSL or UDP

| | LSL | UDP |
|---|---|---|
| Modes | all of them | `ssvep`, `mi`, `neuro` |
| Needs | the LSL library on the device | nothing: one socket |
| Engine | the console, or `server.py` alone | the console only (`server.py` alone does not listen to UDP) |
| Decisions | read from the mode's decoded stream | pushed by the engine to the connected device |

P300, ErrP and c-VEP decode against markers in the LSL clock: they are served over LSL only, and
the application that shows their stimulus also publishes their markers
([`docs/markers.md`](../docs/markers.md)).

## Connecting

1. Start the console on the computer that holds the headset.
2. Start the application. It says it is waiting to be connected.
3. In the console: **Connect an application**, pick the application (its name starts with the
   `app_name` of its configuration), then **Connect**.
4. A mode with a model (Motor Imagery) waits: choose the model in the console, then **Start
   decoding**.

With `server.py` alone, an LSL application of the same computer is connected at once, with no
click.

## What every library handles

- **The warm-up and the rest.** A mode measures its rest first (about 23 s for SSVEP): no decision
  arrives before it ends. For SSVEP, the targets blink from the moment the settings are accepted,
  and the person looks at none of them.
- **`-1` means "no decision"**, never target 0. It is a normal, frequent value.
- **The end of the connection**: "Disconnect" in the console, the console closed, or 5 s of
  silence (UDP). The libraries say why, and the engine stops the mode the application started.
- **One application at a time** is connected to a console.

Across two computers, both must be on the same network and the firewall must let LSL and UDP
through: see [`docs/network.md`](../docs/network.md).
