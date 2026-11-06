# Unity: only read the decisions

`SsvepIntentReceiver` and `IntentToMotion` follow the SSVEP mode **started from the console**: the
scene reads the decoded target and moves an object. To have the application connect, set the mode
up and start it itself, use the ready-made client in [`clients/unity/`](../../clients/unity/).

Compiled with Unity 6000.6.7f1, on Windows x64.

## Setup

1. Add LSL to the project: the two files of
   [`clients/unity/README.md`](../../clients/unity/README.md), section 1.
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
