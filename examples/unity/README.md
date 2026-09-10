# Unity client — drive a scene with SSVEP

Read the decoded brain signal from `EEG_API_Unicorn` inside Unity, in about ten minutes.

## 1. Install the LSL package

In Unity: **Window → Package Manager → + → Add package from git URL**, then paste

```
https://github.com/labstreaminglayer/LSL4Unity.git
```

This is the only dependency. It bundles the native `liblsl` library, so there is nothing
else to install and nothing to configure.

## 2. Add the scripts

Copy `SsvepIntentReceiver.cs` and `IntentToMotion.cs` into your `Assets/` folder. Create an
empty GameObject, add both components to it, and drag any object (a cube will do) into the
`Target` field of **Intent To Motion**.

## 3. Run the engine

On the machine with the headset, the normal way is the console — double-click
`outils\Console EEG.bat`, choose the source, open the **SSVEP** tile, then **Start the
stimulus**. No command to type, and one window that holds the headset for the whole session.

The two-terminal setup below is the headless equivalent, for a machine without a screen or
when the stimulus runs on another computer:

```powershell
python src/stimulus/ssvep.py --refresh 60              # the flickering targets
python src/core/server.py --mode ssvep --refresh 60    # acquisition and decoding
```

The engine starts with a warm-up and a short rest measurement (~23 s for SSVEP) — **look at
nothing and stay still** until it says it is decoding. That rest floor is what makes the
thresholds meaningful, and a floor measured while you were staring at a target stays wrong
for the whole session.

Press Play in Unity. The cube moves while you look at a flickering target.

## What each script is for

`SsvepIntentReceiver` turns the network stream into a C# value and nothing more. It reads
the number of targets and the decision scale from the stream's own metadata, so a scene
built against three targets keeps working when the engine is started with a different
`--freqs`.

`IntentToMotion` is where you come in. The API says *which target the user is looking at*;
deciding that target 0 means "forward" is your application's business, not the engine's.
That separation is why the same stream can drive a game, a visualisation or a robot without
touching a line of Python.

## Things that will bite you

**Start Unity whenever you like, but expect nothing before the rest phase ends.** The
decoded stream exists from the moment the engine starts and stays silent until decoding
begins. `SsvepIntentReceiver` retries once a second until it appears.

**`TargetIndex == -1` is a normal, frequent value.** It means the engine saw nothing
convincing: no target above threshold, or a window thrown out as an artefact. Treat it as
"stop", never as "carry on" — an artefact must not sustain motion.

**The frequencies must match on both sides.** They are snapped to whole divisors of the
screen refresh rate, so a 60 Hz screen gives 15 / 20 / 8.5714 Hz while a 144 Hz screen gives
14.4 / 20.5714 / 8.4706 Hz. Passing the same `--refresh` to the stimulus and to the engine
guarantees they agree. A mismatch fails silently: the decoder simply never fires, because it
is correlating against a sinusoid nobody is displaying.

**Changing the frequencies mid-session RECREATES the stream.** The engine closes the outlet
and opens a new one under the same name, so clients have to re-subscribe. `SsvepIntentReceiver`
resolves once and never looks again: it will sit on a dead inlet, silently. Set the
frequencies before you press Play, or restart the scene after changing them.

**Silence is not an intent.** A decoded value is only valid while samples keep arriving. If the
engine stops, `TargetIndex` keeps its last value forever — which is why `IntentToMotion` stops
after `Watchdog Seconds` without a decision. Any consumer you write needs the same reflex.

**On a shared network, name your engine.** Every instance publishes the same stream names.
Start the engine with `--id yourname` and set `Instance Id` on the component, otherwise you
may quietly connect to a classmate's headset.

**Firewall.** LSL discovers streams over UDP multicast. Same machine is usually transparent;
across two machines, allow Python and Unity through the firewall.

## Status

⚠️ These scripts have **never been compiled or run in Unity** — there is no Unity install on
the development machine, so nobody here can tell you they build. What was done instead, on
2026-09-10, is a line-by-line reading against the LSL4Unity sources linked below.

Checked that way, and fixed: every type and method used exists with the signature used
(`resolve_stream`, `StreamInlet`, `open_stream`, `pull_sample(float[], double)`,
`time_correction`, `info`, `desc`, `child`, `child_value`, `source_id`, `channel_count`);
the stream name and the channel layout match what the engine really publishes; `-1` is
handled as "no decision" on both scripts; and the resolver call is now written `LSL.LSL.
resolve_stream(...)`, because LSL4Unity declares a static class `LSL` **inside** a namespace
also called `LSL` — a bare `LSL.resolve_stream` binds to the namespace. LSL4Unity's own code
writes `LSL.LSL.local_clock()` for exactly that reason.

Still unverified, and only Unity can answer: that it compiles under your Unity and LSL4Unity
versions; that `liblsl` loads on your platform; and everything about frame timing. Report
what breaks.

Sources: [LSL4Unity](https://github.com/labstreaminglayer/LSL4Unity),
[Runtime/LSL.cs API](https://github.com/labstreaminglayer/LSL4Unity/blob/master/Runtime/LSL.cs),
[Runtime/Scripts/TimeSync.cs](https://github.com/labstreaminglayer/LSL4Unity/blob/master/Runtime/Scripts/TimeSync.cs)
(where `LSL.LSL.local_clock()` is written that way),
[SimpleInletScaleObject sample](https://github.com/labstreaminglayer/LSL4Unity/blob/master/Samples~/SimpleInletScaleObject/SimpleInletScaleObject.cs)
