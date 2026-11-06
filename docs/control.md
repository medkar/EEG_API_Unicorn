# Driving the engine from your application

Your application can set up the engine itself: choose a mode's settings, ask the engine to
suggest one, start the mode, and stop it when you are done. With the console, someone clicks
**Connect an application** and picks yours; after that, the only click left is for a mode with a
model (MI, P300, ErrP, c-VEP): the person at the console chooses the model and clicks **Start
decoding**. The connection lasts as long as your command stream: keep one for your whole session.
With `server.py` alone there is nothing to click at all (`server.py` is the engine without a
screen: `python src/core/server.py` from the sources, `eeg-api-unicorn-cli.exe --serveur` in the
installation folder of the installed program). Everything goes through LSL, like the
decoded streams you already read; a device that cannot speak LSL (a microcontroller on the Wi-Fi)
sends the same commands over UDP to the console (see *Over the network (UDP)*).

This page is the contract for doing that. It is public: once your code sends these commands, we
will not change their shape under you.

> **What stays in the console:** training a model and the tests ("Train", "Test…"). Train your
> model there once; your application then names it by its file name and starts decoding. With the
> console, the person at the console makes the final choice of model (see *Being connected*).

## The rules in one paragraph

Four commands, and only four: `start_mode`, `stop_mode`, `set_params`, `propose_params`. **With
the console, someone connects your application first**: the console lists the applications of
the local network that create a command stream (by their `source_id`, with their computer: this
one or another) and the network devices that announce themselves over UDP, and the person picks
yours. Before that click your commands reach nobody: in a classroom every engine listens to the
same stream name, and your neighbour's game drives your engine only if someone picks it. **While
connected, your application owns the settings**: the console shows them on its control page and
refuses to change them; to change something there, the person disconnects you first. **With
`server.py` alone** (no console, nobody to click), only an application on the **same computer**
can drive it: every application of that computer is heard at once, and the last command wins. The
engine's own rules still apply to you: for example, a frequency that does not divide the screen
refresh rate is refused, with the reason.

## The two streams

| Stream | Direction | Who creates it | One sample is |
|---|---|---|---|
| `EEG_API_Unicorn_control` | to the engine | **your application** | one command, a JSON string |
| `EEG_API_Unicorn_replies` | from the engine | the engine | one reply, a JSON string |

Both are LSL streams of type `Markers`, one channel, format `string`, irregular rate. Send your
commands as **UTF-8** text (plain ASCII with `\u` escapes is fine too): a command in another
encoding is refused. LSL cannot receive on a stream it publishes, which is why **you** create the
command stream and the engine listens to it. With `server.py` alone, the engine finds every
`EEG_API_Unicorn_control` stream of its computer by name, even one created after the engine
started. With the console, it lists those of the whole local network, and listens only to the one
someone connected (see *Being connected*).

The replies stream is shared: every application that opens it reads every reply. Its `source_id` is
`EEG_API_Unicorn_replies@<engine id>`; the engine's other streams carry the same id
(`EEG_API_Unicorn_status@<engine id>`, `EEG_API_Unicorn_decoded_ssvep@<engine id>`…). Use it to
read the decoded stream of the engine that answered you, not of a forgotten one.

## Before your first command: two LSL traps

LSL never replays what was sent before a reader connected. Both traps lose a message without any
error:

1. **Wait for the engine before sending** (`outlet.wait_for_consumers(timeout)` in pylsl). A
   command pushed before the engine has discovered your stream is gone. If the wait fails, no
   engine listens to your stream yet: is the console (or `server.py`) running? With the console,
   it also waits until someone connects your application (next section).
2. **Open your replies inlet before sending anything** (`inlet.open_stream()`). A reply published
   before you listen is gone.

So, in this order: open the replies inlet, create your command outlet, wait for the engine, send.

After that, a command with no reply within a few seconds was lost: send it again. All four
commands are safe to send twice. Do not resend in a tight loop: an application that sends more
than about 20 commands per second gets the extra ones refused.

## Being connected (with the console)

- **Name your stream.** The `source_id`, the last argument of `StreamInfo`, is the name the
  console lists under **Connect an application** (cut to 60 characters), next to the computer
  your application runs on ("this PC" for the console's own). Choose one that names your
  application (`"my-game"`; add a random part if two copies may run, even on two computers).
- **Wait to be connected.** With the console, `wait_for_consumers` only succeeds once someone has
  clicked **Connect**. Do not give up after a few seconds: wait, and print what you are waiting
  for. Before that click the engine does not read your commands at all: they get no reply.
- **Keep your command stream open.** If your application closes its command stream (it quits,
  or recreates its outlet, e.g. a Unity Play/Stop), the connection ends as if disconnected: the
  modes it started stop, and the person must click **Connect** again (a new stream is a new
  application in the list). Keep one outlet alive for your whole session.
- **Disconnected.** When the person clicks **Disconnect**, the engine stops reading your
  commands at once, and tells you on the replies stream just before it closes your command
  stream. This message is not a reply to a command: its `ref` is `null`.

  ```json
  {"ref": null, "event": "disconnected", "cause": "console", "app": "my-game", "stopped": ["ssvep"],
   "reason": "Disconnected in the console: the engine stopped what your application started, ..."}
  ```

  | Field | Meaning |
  |---|---|
  | `event` | `"disconnected"` |
  | `cause` | `"console"`: the person clicked **Disconnect**. `"engine_stopped"`: the engine stopped (the console closed, or `server.py` stopped) while it was reading your stream |
  | `app` | the full `source_id` of the command stream the engine stopped reading. The replies stream is shared: the message is yours only if `app` is your `source_id`. It is `null` when the engine could not read your `source_id`, and empty when you gave none: name your stream, in plain ASCII, or you cannot tell your message from another application's |
  | `stopped` | the modes the engine stopped: with `"console"`, the ones you started (a mode that was already running before you connected keeps running); with `"engine_stopped"`, every mode that was running |
  | `reason` | the same in plain English, for people: never make your program depend on its wording |

  The settings you sent stay retained. Nothing comes when your own application closes its command
  stream. After this message, your commands reach nobody: either quit, or close your old command
  stream, create a **new** one (a new outlet; keeping the old one alive would list your
  application twice) and wait to be connected again as at the start, then send your settings and
  your `start_mode` again (both are safe to repeat). After `"engine_stopped"`, the engine's streams
  go away too: once an engine runs again, open its replies stream again (trap 2). Keep pylsl's
  default `recover=True` on your replies inlet: with `recover=False`, a message published just
  before the engine's process exits can be lost.
  A command read just as the person clicked **Disconnect** is refused, with the reason *This
  application is not connected: in the console, click "Connect an application".*

  **Do not watch `outlet.have_consumers()` for this.** Measured with pylsl 1.18.2: once the engine
  has closed its side, `have_consumers()` stays true, and `wait_for_consumers()` answers true at
  once, until your next `push_sample`. An application that only waits for decisions pushes
  nothing, and would never notice (that is also why a new outlet is needed to wait for the next
  connection). It is still the only sign when the engine dies without stopping (a crash, a killed
  process): no message comes then, and `have_consumers()` turns false right after your next
  command.
- **A mode with a model** (`mi`, `p300`, `errp`, `cvep`). If the mode is not running yet, your
  `start_mode` is accepted with `"deferred": true` and a `warning`: the person at the console
  chooses the model, then clicks **Start decoding**. Watch `EEG_API_Unicorn_status` until `modes`
  lists it (that is what `examples/control_client.py` does); the P300 and ErrP decoded streams
  stay silent until you send markers. If that start fails (for example a model file that cannot
  be loaded), the `event: "failed"` message comes at that moment, possibly long after your
  command, with the `ref` of your `start_mode`. If the mode is already running (started before
  you connected, or your `start_mode` sent again after **Start decoding**), the reply says
  `"already_running": true`, with no `deferred`, and `model` names the model in use. While the
  mode is not running (waiting or stopped), replies carry `"model": null` in `params`; once it
  runs, `model` names the one chosen in the console. A `stop_mode` cancels the wait
  (`"already_stopped": true`).
- **The model is chosen at the console.** A `model` you send, in `start_mode` or `set_params`, is
  only a suggestion: it is never applied, and never refused either, even if no such file exists;
  the reply's `warning` says it is kept as a suggestion. The console preselects it for a mode
  that waits, if that file exists on the console's computer; a running mode keeps the model in use. The
  other settings of the same command apply as usual. Read what the chosen model imposes in the
  decoded stream's description (`n_targets`, `target_names`, `refresh`, the MI `classes`). If the
  person picks another model while decoding, the decoded stream is recreated: open it again. With
  no trained model for the mode on the console's computer, your command is refused: the person has to
  disconnect you and train one first.
- **Any language.** Unity (LSL4Unity), MATLAB (liblsl-Matlab) or C++ only need to create this
  string stream: every LSL library that reads a stream can also publish one.

## A command

One JSON object per sample:

```json
{"cmd": "set_params", "mode": "ssvep", "params": {"z_min": 3.0}, "ref": "my-game-7"}
```

| Field | Meaning |
|---|---|
| `cmd` | one of the four commands below |
| `mode` | `ssvep`, `cvep`, `p300`, `errp`, `mi`, `neuro` or `raw` |
| `params` | the settings, by their public name (table further down) |
| `ref` | a string or a number of your choice, copied back into the reply |
| `key` | `propose_params` only: leave it out (see `propose_params`) |

**Always set a unique `ref`** (for example your application's name and a counter). The replies
stream is shared: `ref` is how you recognise **your** reply. A `ref` that is neither a string nor
a number (`true`, an object…) gets the whole command refused. Unknown fields of the command are
ignored; an unknown setting **inside** `params` is refused, with the list of known ones.

### `start_mode`

Starts the mode, from its retained settings completed by `params`. The mode then warms up and
measures a rest floor before it publishes anything (about 23 s for SSVEP): `accepted: true` means
the command is accepted, not that decisions are flowing. The decoded stream appears at once but
stays silent until then: wait for its **first sample**, or watch `EEG_API_Unicorn_status`
(`modes`, `phase`). The P300 and ErrP decoded streams also stay silent until you send markers:
for them, watch `status`. (`raw` publishes `EEG_API_Unicorn_raw`, which the engine sends anyway.)

Sent to a mode that is already running, it is not refused: its `params` are applied as with
`set_params`, and the reply says `"already_running": true`. A game that restarts can send the
same `start_mode` again. With the console, that holds as long as it keeps its command stream: a
game that recreates its stream must first be connected again (see *Being connected*).

With the console, a mode with a model does not start yet: see *Being connected*.

### `stop_mode`

Stops the mode. Sent to a mode that is already stopped, the reply says `"already_stopped": true`.

### `set_params`

Changes some settings; the others keep their current value.

- **On a stopped mode**, the settings are checked, then retained: the reply says
  `"deferred": true`, and the next `start_mode` uses them. This is the normal order: **set, then
  start**.
- **On a running mode**, they are applied. Most settings change what the decoder does: the
  engine then rebuilds the mode, redoes its warm-up and rest, and **recreates its decoded
  stream**. Re-open your inlet on it. The c-VEP thresholds `corr_min` and `margin` apply at once,
  without recreating the stream; the SSVEP `targets_on`, and the settings used only to compute a
  suggestion (`refresh_hz`, `alpha_hz`), do not recreate it either.
- `stream_in` (the marker stream a P300, ErrP or c-VEP mode listens to) is a special case: the
  engine has **one shared listener** for its marker modes. On a running mode the new name only
  takes effect at the next start of the mode, and only once no other marker mode is running; the
  reply carries a `warning` saying so. Send `set_params` with your `stream_in`, **then**
  `start_mode`. If another marker mode is already running on another stream name, the mode you
  start listens to that one: stop the other mode first.
- `set_params` with empty `params` changes nothing and returns every current setting: a cheap
  way to read them.

### `propose_params`

Asks the engine to compute a setting **without applying it**. Today one mode suggests: SSVEP
computes its target frequencies from the screen refresh rate, the person's alpha peak and the
filter band. Send in `params` what you want to change (typically `refresh_hz`); the settings you
do not send keep their retained values, and the number of frequencies is the current number of
targets. With `targets_on: "physical"` (LEDs), any frequency on a half-hertz grid can be proposed.
The reply carries `key` (the setting it filled, `freqs`) and `value`. Apply it yourself with
`set_params`. It can be refused when no set of frequencies fits (for example 6 targets at 30 Hz):
the reason says how many targets fit.

Leave `key` out: SSVEP has a single setting that suggests (`alpha_hz`, the one the engine's
console button is attached to), and the engine fills it in.

## A reply

```json
{"ref": "my-game-7", "cmd": "set_params", "mode": "ssvep", "accepted": true,
 "deferred": true, "warning": null, "params": {"...": "every setting of the mode, validated"}}
```

| Field | When |
|---|---|
| `ref`, `cmd`, `mode`, `accepted` | always (`null` when your command did not carry a readable value) |
| `reason` | refused: why, in plain English; a setting is named by its screen label and the key you send, `"Low cutoff (band_low)"` |
| `params` | `set_params`, `start_mode`: all the settings the mode will use (with the console, `"model": null` while a mode with a model is not running: waiting or stopped) |
| `deferred` | `set_params`: `true` when retained for the next start; `start_mode` with the console: a mode with a model waits for the person to choose it |
| `already_running` / `already_stopped` | `start_mode` / `stop_mode` |
| `key`, `value` | `propose_params` |
| `warning` | every accepted reply: a reservation, or `null` |

Every text is in **English**, with a dot for decimals, whatever language the console shows.

**One reply per command**, an unreadable one included (over UDP, a datagram that is not a JSON
object carrying `"v": 1` gets none: see *Over the network*) — as long as the engine keeps up: about
100 commands can wait for it per application, and beyond that the oldest are dropped without a
reply (send at most about 20 per second and this never happens). And sometimes a **second message** for the
same `ref`: a command accepted by the engine can still fail a moment later, for example a model
file that cannot be loaded. It has an `event` field and no `accepted` field:

```json
{"ref": "my-game-8", "cmd": "start_mode", "mode": "mi", "event": "failed",
 "reason": "..."}
```

Without it you would wait forever for a mode that will never start.

One more message is not about a command at all: `"event": "disconnected"`, with `ref` set to
`null`, when
the engine stops reading your command stream (see *Being connected*). Keep only the one whose
`app` is your `source_id`.

## The settings, mode by mode

Public names, as `params` takes them. The console shows the same settings under their screen
labels; `params` in an accepted reply lists them all with their current value.

| Mode | Setting | Type | Default | Range |
|---|---|---|---|---|
| `ssvep` | `targets_on` | `"screen"` or `"physical"` (LEDs) | `"screen"` | |
| | `freqs` | list of Hz, one per target | 15, 20, 8.571 | 2 to 10 targets, at least 0.67 Hz apart, in the filter band, divisors of `refresh_hz` on a screen |
| | `target_names` | list of names, one per frequency, or empty | empty | at most 24 characters each, no comma, no duplicate |
| | `refresh_hz` | Hz, the stimulus screen | 60 | 20 to 480 |
| | `alpha_hz` | Hz, the person's alpha peak | 9.6 | 6 to 14 |
| | `z_min` | detection threshold | 2.5 | 1 to 6 |
| | `band_low`, `band_high` | filter band, Hz | 5, 40 | 3 to 8, 20 to 45 |
| `cvep` | `model` | model file name | see below | |
| | `stream_in` | marker stream name | `EEG_API_Unicorn_stim` | any name |
| | `corr_min`, `margin` | decision thresholds | 0.26, 0.09 | 0 to 1 |
| | `vote_len`, `min_votes` | vote windows, agreeing votes | 3, 2 | 1 to 15, `min_votes` ≤ `vote_len` |
| `p300` | `model` | model file name | see below | |
| | `stream_in` | marker stream name | `EEG_API_Unicorn_stim` | any name |
| `errp` | `model` | model file name | see below | |
| | `tnr_target` | share of correct commands kept | 0.85 | 0.5 to 0.99 |
| | `stream_in` | marker stream name | `EEG_API_Unicorn_stim` | any name |
| `mi` | `model` | model file name | see below | |
| | `prob_min` | minimum probability | 0.6 | 0.34 to 0.99 |
| | `vote_len`, `min_votes` | vote windows, agreeing votes | 5, 3 | 1 to 15, `min_votes` ≤ `vote_len` |
| `neuro` | `smoothing` | smoothing factor | 0.85 | 0 to 0.99 |
| | `rebaseline_s` | rest baseline reset, s | 180 | 0 to 1800 |
| `raw` | | no setting | | |

- **`model`** takes the **file name** the console shows (for example
  `p300_model_20261021_101500_6targets.joblib`), never a path, and replies give it back the same
  way. Leave it out and the mode uses the model the engine has retained — the last one trained
  and saved, or chosen in the console — or else the most recent one on this computer. With
  `server.py` alone, a name that does not exist is refused, and the reason lists the available
  ones. With the console, the person at the console chooses the model: yours is never applied
  nor refused, only kept as a suggestion (see *Being connected*).
- **`stream_in`** accepts any non-empty name, even one not on the network yet: the engine waits
  for it, and the reply carries a `warning` saying it has not seen it. The engine's own streams
  (`status`, `replies`, `control`) are refused.

## The SSVEP refresh rate, step by step

Your game renders at 30 frames per second. A target can only flicker at a frequency that divides
the refresh rate, so the default frequencies (15, 20, 8.571 Hz) cannot all be shown at 30 Hz.
Sending `{"refresh_hz": 30}` alone is therefore **refused**: the reason names the first frequency
that does not fit, and the two closest that would. That refusal is correct. Ask first, then set
both together:

1. `{"cmd": "propose_params", "mode": "ssvep", "params": {"refresh_hz": 30}}` → `value` is a set of
   frequencies that divide 30, away from the alpha peak.
2. `{"cmd": "set_params", "mode": "ssvep", "params": {"refresh_hz": 30, "freqs": <value>}}`.
3. `{"cmd": "start_mode", "mode": "ssvep"}`.

Do not write the frequencies in your code: they depend on the person's alpha peak (`alpha_hz`).
The engine keeps these settings afterwards, until it is closed: the console's SSVEP page will
show 30 Hz too, and its SSVEP tests will ask for a 30 Hz screen.

## A minimal client in Python

The complete, commented version is [`examples/control_client.py`](../examples/control_client.py):
it runs the whole SSVEP sequence above against the console or `server.py`, and stops the mode at
the end; with `--mode mi` it starts a mode with a model and, with the console, waits until the
person there has chosen the model. The core is short:

```python
import json, time, uuid
from pylsl import StreamInfo, StreamOutlet, StreamInlet, resolve_byprop

# 1. Listen first: every replies stream of the network (the console may run on another computer).
#    minimum=1000 makes LSL wait the whole timeout and return every answer, so a neighbour's
#    engine cannot hide yours. Only the engine that connected you answers YOUR ref.
found = {i.uid(): i for i in resolve_byprop("name", "EEG_API_Unicorn_replies",
                                            minimum=1000, timeout=2)}
if not found:
    raise SystemExit("no engine on the network: is the console (or server.py) running?")
replies = [StreamInlet(i) for i in found.values()]
for inlet in replies:
    inlet.open_stream(timeout=5)

# 2. Create the command stream, then wait for the engine to connect to it. Its source_id
#    ("my-game") is the name the console lists under "Connect an application".
info = StreamInfo("EEG_API_Unicorn_control", "Markers", 1, 0, "string", "my-game")
outlet = StreamOutlet(info)
while not outlet.wait_for_consumers(10):
    print("waiting to be connected: in the console, click 'Connect an application'")

# 3. Send, then wait for the reply carrying YOUR ref (unique: other applications read it too).
ref = f"my-game-{uuid.uuid4().hex[:6]}-1"
outlet.push_sample([json.dumps({"cmd": "start_mode", "mode": "ssvep", "ref": ref})])
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    for inlet in replies:
        sample, _ = inlet.pull_sample(timeout=0.0)
        if sample:
            reply = json.loads(sample[0])
            if reply.get("ref") == ref:
                print(reply)
                raise SystemExit
    time.sleep(0.02)
print("no reply: the command was lost, send it again")
```

With the console, this script ends right after the reply: its command stream closes with it, the
connection ends, and the engine stops at once the mode it has just started. A real application
keeps its outlet open for as long as it uses the mode.

Any language with an LSL library does the same three steps: Unity (LSL4Unity), MATLAB, C++. Only
pylsl has been tried here.

## Over the network (UDP): a device without LSL

A microcontroller (an ESP32 that drives LEDs, for example) cannot speak LSL. It can send and
receive UDP datagrams on the Wi-Fi: the **console** listens to them on **port 5010**. The commands
and the replies are the ones above, one per datagram; only how the device is found and connected
differs. [`examples/udp_device.py`](../examples/udp_device.py) plays such a device in Python, with
the standard library only: read it before writing yours. `server.py` alone does not listen to UDP:
without a screen, nobody can click **Connect**.

**One datagram = one JSON object, in UTF-8, carrying `"v": 1`**, of at most 8 KB. Any other
datagram is ignored **without a reply**: no `v`, another version, not JSON, too big. The engine's
datagrams are often longer than 255 bytes (a reply lists every setting of the mode; a refusal
explains itself): read them with a buffer of **8 KB**, not the 255 bytes of the usual Arduino
`WiFiUDP` example, or they arrive cut and their JSON does not parse.

### The handshake

| Step | Who sends | Datagram |
|---|---|---|
| 1. Announce yourself, every second, until connected | device → `255.255.255.255:5010` (broadcast), or the console's IP | `{"v": 1, "hello": "EEG_API_Unicorn", "app": "my-game", "id": "AB:CD", "port": 5011}` |
| 2. **Identify** (optional, clicked in the console) | engine → device | `{"v": 1, "identify": true}`: blink a LED, so that the person sees which line is yours |
| 3. **Connect** (clicked in the console) | engine → device | `{"v": 1, "connect": "<engine id>", "host": "<the console's PC name>"}` |
| | device → engine | `{"v": 1, "connected": true}`; already connected to another console: `{"v": 1, "connected": false, "busy": "<that console's PC name>"}` |
| 4. Commands | device → engine | one command (*A command*) per datagram: `{"v": 1, "cmd": "start_mode", "mode": "ssvep", "ref": 1}` |
| | engine → device | its reply: the JSON of `EEG_API_Unicorn_replies`, plus `"v"` and `"seq"` |

- `app` is the name the console lists. `id` tells two devices of the same program apart (on an
  ESP32: the end of its MAC address). `port` is the UDP port your device listens to.
- **Send everything from the port you announce.** The engine recognises your device by the
  address its datagrams come FROM: a datagram from another port is ignored, without a reply, and
  the console says your device does not answer.
- Answer `connect` to the address it came from: that is where the engine is (not the broadcast
  address). The engine sends `connect` **once** and waits **3 s**. No answer: the console says the
  device does not answer, and the person clicks **Connect** again.
- The console lists a device that has sent a hello in the last 5 s.

### While connected

- **Signs of life.** Both sides send `{"v": 1, "alive": true}` every second. Any VALID datagram
  from the device counts as a sign of life (a JSON object with `"v": 1`, sent from the announced
  port), except a hello. **5 s without anything valid from the device**: the
  connection ends as if the application had quit, and the modes it started stop. 5 s without
  anything from the engine: consider yourself disconnected, and announce yourself again.
- **`seq`.** Every reply and every pushed message carries, at the top level, a `"seq"` that grows:
  `{"v": 1, "seq": 12, "decision": {...}}`. UDP can deliver an old datagram late: ignore one whose
  `seq` is not greater than the last one you accepted, and start again from 0 at every `connect`.
  The engine's `identify`, `connect` and `alive` carry no `seq`.
- **What the engine pushes**, for every mode your device asked for (a `start_mode` accepted,
  `"already_running": true` included):
  - `{"v": 1, "seq": n, "status": {"phase": "decoding", "modes": {"ssvep": "decoding"}}}`, at every
    change and every second. `phase` is the least advanced of your modes: `idle` (none),
    `deferred` (a mode with a model waits for the person to choose it), `warmup`, `baseline` or
    `decoding`. During `warmup` and `baseline`, an `instruction` field says what the person should
    do, in English.
  - `{"v": 1, "seq": n, "decision": {"mode": "ssvep", "target_index": 1.0, "freq_hz": 15.0,
    "confidence": 0.82, ...}}`: every sample of the mode's decoded stream (about 5 per second),
    `-1` included, with the channels of `EEG_API_Unicorn_decoded_<mode>` by name. Every value is a
    **number**: `target_index` arrives as `1.0`, and `-1.0` means "no decision", never target 0.
  - `failed` and `disconnected`: the messages of the replies stream, plus `v` and `seq`. In
    `disconnected`, `app` is the `app` of your hello.
- **The end.** Your device stops: send `{"v": 1, "bye": true}`. The connection ends at once, and
  the engine stops what you started. (A `bye` before being connected removes you from the list.)
  The person clicks **Disconnect**, or closes the console: you receive `disconnected`.
- **UDP can lose a datagram.** A command with no reply after about 2 s: send it again (the four
  commands are safe to repeat). `status` comes again every second, and a lost decision is
  followed by the next one (about 0.2 s later). While the headset is disconnected, the engine
  decodes nothing: no decision comes until it is back.

### The modes served over UDP

`ssvep`, `mi` and `neuro`. A `start_mode` or a `set_params` for `p300`, `errp`, `cvep` or `raw` is
refused, with the reason: the first three need markers timestamped by the LSL clock, which a
microcontroller does not have, and `raw` sends too much for a network device. Use LSL for them.
For `mi`, a decision gives `intent_index` and the probabilities `p_0`, `p_1`…; the task names are
only in the description of the LSL stream `decoded_mi`, which a device cannot read: the console's
control page shows them.

## When something goes wrong

| What you see | Why |
|---|---|
| `wait_for_consumers` returns false | nobody has connected your application in the console yet (**Connect an application**); with `server.py` alone, your application does not run on the engine's computer, or no engine runs |
| the console does not list your application, or your device | it is not on the same local network, or the Windows firewall of the console's computer blocks it: allow Python, public networks included (see [network.md](network.md)). A device: its broadcast may not reach the console (a computer with several networks, a VPN): send the hello to the console's IP address |
| the console says your device does not answer | it did not answer `connect` within 3 s, or answered from another port than the one in its hello: send everything from the announced port, then click **Connect** again |
| the console says your device stopped sending news, 5 s after connecting | the engine received nothing valid from it: its `alive` lacks `"v": 1`, or leaves from another port than the one in its hello |
| your device's JSON does not parse, or a reply seems lost forever | its receive buffer is too small: the engine's datagrams can be longer than 255 bytes. Use 8 KB |
| the console says your device is already connected | it answered `"busy"`: another console has it; disconnect it there first |
| `deferred: true` on a `start_mode` | a mode with a model: the person at the console chooses it, then clicks **Start decoding** |
| `"event": "disconnected"` with your `source_id` in `app` | you were disconnected in the console (`"cause": "console"`), or the engine stopped (`"engine_stopped"`). The modes in `stopped` are stopped; to go on, create a new command stream and wait to be connected again |
| a mode you started stops when your application restarts | your application closed or recreated its command stream, which ends the connection like **Disconnect**, without a message. The modes you started are stopped; with the console, the new stream must be connected again |
| your application waits for decisions and nothing comes, no `disconnected` message either | first, the normal silences: a mode publishes nothing during its warm-up and rest (about 23 s for SSVEP), and a P300, ErrP or c-VEP decodes nothing without its markers. If `EEG_API_Unicorn_status` (republished every 2 s) went silent too, the engine died without stopping (a crash, a killed process); a command also tells: `have_consumers()` turns false right after it. Do not rely on `have_consumers()` otherwise: it stays true until your next push |
| `wait_for_consumers` returns true but nothing answers | another reader connected to your stream (a recorder, a monitor): the engine may not be listening — check that your replies inlet found an engine |
| no reply after a few seconds | the command was sent too early (trap 1) or your inlet opened too late (trap 2): send it again |
| `accepted: false` | the `reason` says why: unknown mode, a setting out of range, no trained model for the mode, too many commands per second… |
| `event: "failed"` after an accepted command | the engine could not carry it out; the `reason` says why |
| two replies for the same `ref` | two engines listen to you (two `server.py` on your computer): close one |
| replies you did not ask for | another application: the replies stream is shared, keep only your `ref` |
| `server.py` on another computer ignores you | by design: `server.py` alone only listens to its own computer. The console listens to any computer of the network, once someone has connected you |
