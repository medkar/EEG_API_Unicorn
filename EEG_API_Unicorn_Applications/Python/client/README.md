# Python client (LSL)

`eeg_api_lsl.py` connects a Python program to EEG_API_Unicorn over LSL, from any computer of the
network. This folder is the library alone, to start from scratch in your own project; for a
complete application to copy and run, see [`../exemple/`](../exemple/).

Needs Python 3 and pylsl (`pip install pylsl`).

## Use it in your project

Copy `eeg_api_lsl.py` next to your program, with a `config.json` (the keys are below; an example:
[`../exemple/config.json`](../exemple/config.json)). Do not edit the library.

```python
from eeg_api_lsl import EegApi, EegApiError, config_path, load_config

api = EegApi(load_config(config_path()))   # config.json next to your program
api.connect()                      # waits until the console connects this application
api.start()                        # sends the settings, starts the mode
for decision in api.decisions():   # one dict per decision, channels by name
    ...
api.close()                        # stops the mode it started, closes the streams
```

`decisions()` waits for the mode (warm-up, rest, or the choice of a model), opens the decoded
stream again when the engine recreates it, and ends when the connection ends.
`api.why_disconnected()` then says why. `api.send(cmd, params)` sends any of the four commands
and returns its reply.

A decision holds the channels of the mode's decoded stream: SSVEP `target_index`, `freq_hz`,
`confidence`, one `score_<f>Hz` per target; MI `intent_index`, `confidence`, `p_0`, `p_1`…; Neuro
`charge`, `somnolence`, `engagement`, `artifact`.

## `config.json`

| Key | Meaning | Default |
|---|---|---|
| `app_name` | the start of the name the console lists (a random part is added) | `my-app` |
| `mode` | `ssvep`, `mi`, `neuro`, `p300`, `errp` or `cvep` | `ssvep` |
| `params` | the settings of the mode, sent with `set_params` (keys: [`docs/control.md`](../../../docs/control.md)) | `{}` |
| `propose_refresh_hz` | SSVEP on a screen: the refresh rate whose divisors the engine proposes as frequencies; `0` = do not ask | `0` |
| `stop_mode_on_exit` | stop, at the end, the mode this application started | `true` |
| `search_timeout_s` | how long to look for an engine before giving up | `30` |

A key that is not in this table is refused, with the list of the known ones.

## Things to know

- `connect()`, `start()` and `decisions()` raise `EegApiError` with the reason: no engine, a
  refused setting, a lost connection. `start()` also raises when the engine accepts a command
  and then fails to apply it (a setting the running mode refuses, a model that cannot be loaded):
  "accepted" is not "in force".
- `decisions()` can run on its own thread while another one draws: `close()`, called from any
  thread, makes it end.
- `-1` means "no decision", never target 0.
