# Ready-made clients

Each folder connects one kind of application to EEG_API_Unicorn. It performs the whole handshake
of [`docs/control.md`](../docs/control.md): it finds the engine, waits to be connected, sends its
settings, starts the mode, receives the decisions, and stops what it started when it ends.

Every folder works the same way:

- **one configuration file** holds everything that changes from one application to another: its
  name, the mode, the settings of the mode, the network;
- **the library** does the protocol and is used as it is;
- **the example** is a complete application whose decision handler is the place for your code.

Copy the folder into your project, edit the configuration file, then replace the decision
handler.

| Folder | For | Transport | Configuration | Your code |
|---|---|---|---|---|
| [`python-lsl/`](python-lsl/) | Python 3 on a computer | LSL | `config.json` | `on_decision()` in `example.py` |
| [`raspberry-pi/`](raspberry-pi/) | Python 3, standard library only: Raspberry Pi, any Linux board | UDP | `config.json` | `on_decision()` in `example.py` |
| [`ros2/`](ros2/) | ROS 2 (on a Raspberry Pi or any computer) | UDP | `config/params.yaml` | a node subscribed to `eeg/target` |
| [`unity/`](unity/) | Unity 6 | LSL | `StreamingAssets/eeg_api_config.json` | `onTargetChanged` or `DecisionReceived` |
| [`matlab/`](matlab/) | MATLAB R2016b or later | LSL | `config.json` | `onDecision()` in `example.m` |
| [`esp32/`](esp32/) | ESP32 (Arduino) | UDP over Wi-Fi | `config.h` | `onDecision()` in the sketch |
| [`arduino-wifi/`](arduino-wifi/) | Arduino UNO R4 WiFi | UDP over Wi-Fi | `config.h` | `onDecision()` in the sketch |

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
2. Start the client. It says it is waiting to be connected.
3. In the console: **Connect an application**, pick the client (its name starts with the
   `app_name` of its configuration), then **Connect**.
4. A mode with a model (Motor Imagery) waits: choose the model in the console, then **Start
   decoding**.

With `server.py` alone, an LSL client of the same computer is connected at once, with no click.

## What every client handles

- **The warm-up and the rest.** A mode measures its rest first (about 23 s for SSVEP): no decision
  arrives before it ends. For SSVEP, the targets blink from the moment the settings are accepted,
  and the person looks at none of them.
- **`-1` means "no decision"**, never target 0. It is a normal, frequent value.
- **The end of the connection**: "Disconnect" in the console, the console closed, or 5 s of
  silence (UDP). The clients say why, and the engine stops the mode the client started.
- **One application at a time** is connected to a console.

Across two computers, both must be on the same network and the firewall must let LSL and UDP
through: see [`docs/network.md`](../docs/network.md).
