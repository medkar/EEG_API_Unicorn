# Unity client (LSL)

Connects a Unity application to EEG_API_Unicorn over LSL: it finds the engine, waits to be
connected, sends its settings, starts the mode and exposes the decisions to your scripts.

| File | Goes to | Role |
|---|---|---|
| `StreamingAssets/eeg_api_config.json` | `Assets/StreamingAssets/` | the settings: edit this one |
| `EegApiClient.cs` | `Assets/Scripts/` | the component to drop on a GameObject |
| `EegApiLink.cs` | `Assets/Scripts/` | the handshake and the commands, on a worker thread |
| `EegApiConfig.cs` | `Assets/Scripts/` | reads the configuration file |
| `Editor/EegApiSelfTest.cs` | `Assets/Editor/` | plays the handshake without a scene (optional) |

Compiled with Unity 6000.6.7f1, on Windows x64.

## 1. Add LSL to the project

The scripts need the LSL C# binding (`LSL.cs`) and the native library (`lsl.dll`), both
published by the LSL project in [LSL4Unity](https://github.com/labstreaminglayer/LSL4Unity)
(MIT license). **The two files are enough.** Copy them from a clone of LSL4Unity
(`git clone https://github.com/labstreaminglayer/LSL4Unity.git`):

| From LSL4Unity | To your project |
|---|---|
| `Runtime/LSL.cs` | `Assets/Plugins/LSL/LSL.cs` |
| `Plugins/LSL/Windows/x64/lsl.dll` and `lsl.dll.meta` | `Assets/Plugins/LSL/Windows/x64/` |
| `LICENSE` | `Assets/Plugins/LSL/LICENSE.txt` |

The `.meta` file carries the import settings of the native library (Windows, 64 bits). For
another platform, take its library from `Plugins/LSL/` the same way.

⚠️ **Installing the whole LSL4Unity package fails on Unity 6.6**: its helper components use
`GetInstanceID()`, which Unity 6.6 rejects (`error CS0619` in `BaseOutlet.cs`), and the whole
package then refuses to compile. These scripts do not use those components. On a Unity version
where the package compiles, installing it is enough: Package Manager → "+" → "Install package from
git URL…" → `https://github.com/labstreaminglayer/LSL4Unity.git` (the name declared by the
package is `com.labstreaminglayer.lsl4unity`).

## 2. Configure and run

1. Copy the files as in the first table, and edit `eeg_api_config.json`.
2. Create an empty GameObject and add the **Eeg Api Client** component.
3. Start the console on the computer that holds the headset.
4. Press **Play**. The Unity Console shows "Waiting to be connected…".
5. In the console: **Connect an application**, pick `my-game-…`, then **Connect**.

| Key | Meaning | Default |
|---|---|---|
| `app_name` | the start of the name the console lists (a random part is added) | `my-game` |
| `mode` | `ssvep`, `mi`, `neuro`, `p300`, `errp` or `cvep` | `ssvep` |
| `params` | the settings of the mode, sent with `set_params` (keys: [`docs/control.md`](../../docs/control.md)) | `{}` |
| `propose_refresh_hz` | SSVEP on a screen: the refresh rate whose divisors the engine proposes as frequencies; `-1` = this screen's, `0` = do not ask | `-1` |
| `stop_mode_on_exit` | stop, when Play stops, the mode this application started | `true` |
| `search_timeout_s` | how long to look for an engine before giving up | `30` |

## 3. Use the decisions

From your scripts, read the component:

| Member | Content |
|---|---|
| `State` | `Searching`, `WaitingToBeConnected`, `Setting`, `WaitingForTheMode`, `Decoding`, `Disconnected`, `Failed`, `Stopped` |
| `TargetIndex` | `target_index` (SSVEP, P300, c-VEP) or `intent_index` (MI) of the last decision; `-1` = none |
| `Confidence` | the score of the last decision |
| `LastDecision` | every channel of the last decision, by name |
| `DecisionCount` | the number of decisions received, `-1` included |
| `Frequencies` | SSVEP: the frequencies proposed by the engine, one per target |
| `Message` | the last message of the link, in plain English |
| `onTargetChanged` | a UnityEvent raised when the decoded target changes (set it in the Inspector) |
| `DecisionReceived` | a C# event raised for every decision, with its channels by name |

Everything is raised on the main thread.

- **For SSVEP, your scene renders the targets**: one per entry of `Frequencies`, each blinking at
  its frequency, locked to the screen refresh (vsync on). They must blink from the start of the
  mode, during its warm-up and rest (about 23 s), while the person looks at none of them: the
  engine measures its rest with the targets blinking.
- **Every Play creates a new command stream**: the console sees a new application, to be
  connected again.
- **A mode with a model** (Motor Imagery) waits for the model to be chosen in the console, then
  **Start decoding**: `State` stays `WaitingForTheMode` until then.
- The LSL calls block: the component runs them on a worker thread. `EegApiLink` can be used
  directly to drive the engine another way.

## Check without a scene

`EegApiSelfTest` plays the whole handshake with the settings of `eeg_api_config.json` against a
running engine, and exits with 0 when every step got the expected reply:

```powershell
python src/core/server.py --synthetic       # the engine alone: no click needed
# installed program: eeg-api-unicorn-cli.exe --serveur --synthetic (in the installation folder)
& "C:\Program Files\Unity\Hub\Editor\6000.6.7f1\Editor\Unity.exe" -batchmode -projectPath <project> -executeMethod EegApiSelfTest.Run -logFile -
```

With the console instead of `server.py`, connect `unity-selftest-…` within 60 s.

## Things to know

- **`-1` is a normal, frequent value**: no decision. Treat it as "stop", never as "carry on".
- **The frequencies must match on both sides.** On a screen they are divisors of the refresh rate
  (15 / 20 / 8.5714 Hz at 60 Hz): ask the engine with `propose_refresh_hz` rather than writing
  them by hand. A mismatch fails silently.
- **Firewall**: LSL discovers streams over UDP multicast. Across two computers, allow Unity (and
  the engine's computer) through the firewall: see [`docs/network.md`](../../docs/network.md).
- `LSL.LSL.resolve_stream(...)` is written twice on purpose: `LSL.cs` declares a static class
  `LSL` inside a namespace also called `LSL`.
