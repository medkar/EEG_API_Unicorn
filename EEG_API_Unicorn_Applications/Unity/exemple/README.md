# Unity example: read the decisions

`SsvepIntentReceiver` and `IntentToMotion` follow the SSVEP mode **started from the console**: the
scene reads the decoded target and moves an object. They read the decoded stream only, so they
need no connection. To have the application connect, set the mode up and start it itself, use the
client in [`../client/`](../client/).

| File | Role |
|---|---|
| `SsvepIntentReceiver.cs` | reads the decoded SSVEP stream and exposes the target as a C# value |
| `IntentToMotion.cs` | your application: turns the target into a motion of an object |

Compiled with Unity 6000.6.7f1, on Windows x64.

## Setup

1. Add LSL to the project. The scripts need the LSL C# binding (`LSL.cs`) and the native library
   (`lsl.dll`), published by the LSL project in
   [LSL4Unity](https://github.com/labstreaminglayer/LSL4Unity) (MIT license); they are not in this
   folder. Copy them from a clone of LSL4Unity
   (`git clone https://github.com/labstreaminglayer/LSL4Unity.git`):

   | From LSL4Unity | To your project |
   |---|---|
   | `Runtime/LSL.cs` | `Assets/Plugins/LSL/LSL.cs` |
   | `Plugins/LSL/Windows/x64/lsl.dll` and `lsl.dll.meta` | `Assets/Plugins/LSL/Windows/x64/` |
   | `LICENSE` | `Assets/Plugins/LSL/LICENSE.txt` |

   Installing the whole LSL4Unity package fails on Unity 6.6 (`error CS0619` in `BaseOutlet.cs`):
   copy the two files instead.
2. Copy both scripts into `Assets/`, add both components to an empty GameObject, and drag any
   object (a cube will do) into the `Target` field of **Intent To Motion**.
3. Start the SSVEP mode from the console (the **SSVEP** tile, **Start**), or headless:

   ```powershell
   python src/core/server.py --mode ssvep --refresh 60
   # installed program: eeg-api-unicorn-cli.exe --serveur --mode ssvep --refresh 60
   ```

4. Press Play: the cube moves while a blinking target is looked at.

`SsvepIntentReceiver` turns the stream into a C# value and nothing more; it reads the number of
targets and the decision scale from the stream's own metadata. `IntentToMotion` is where an
application decides what a target means: the engine publishes an intent ("target 1 is looked
at"), never an actuator command.

## Things to know

- **Nothing arrives before the rest phase ends.** The decoded stream exists from the start of the
  mode and stays silent during its warm-up and rest.
- **`-1` is a normal, frequent value**: no decision (no target above threshold, or a window
  rejected as an artefact). Treat it as "stop", never as "carry on".
- **The frequencies must match on both sides.** On a screen they are divisors of the refresh rate:
  15 / 20 / 8.5714 Hz at 60 Hz, 14.4 / 20.5714 / 8.4706 Hz at 144 Hz. A mismatch fails silently:
  the decoder correlates against a frequency nobody displays.
- **Changing the frequencies recreates the decoded stream**, and `SsvepIntentReceiver` does not
  open it again: set the frequencies before pressing Play.
- **Silence is not an intent.** If the engine stops, a stored value stays forever: `IntentToMotion`
  stops after `Watchdog Seconds` without a decision. Any consumer needs the same reflex.
- **Several engines on one network** publish under the same names: start the engine with
  `--id <name>` and set `Instance Id` on `SsvepIntentReceiver`.
- **Firewall**: LSL discovers streams over UDP multicast. Across two computers, allow Unity (and
  Python on the engine's computer) through the Windows firewall, public networks included.
- `LSL.LSL.resolve_stream(...)` is written twice on purpose: `LSL.cs` declares a static class
  `LSL` inside a namespace also called `LSL`.
