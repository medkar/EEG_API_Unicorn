# Python example (LSL)

Two complete applications that connect to EEG_API_Unicorn over LSL, from any computer of the
network. This folder holds everything they need: copy it into your workspace and run it.

| File | Role |
|---|---|
| `config.json` | the settings: edit this one |
| `cibles_ssvep.py` | an SSVEP application: it shows the blinking targets, then circles in green the target the engine decodes. Your code goes in `on_decision()` |
| `example.py` | the smallest application: it prints every decision in the terminal. Your code goes in `on_decision()` |
| `eeg_api_lsl.py` | the library: the handshake, the commands, the decisions. Do not edit it |

Needs Python 3, pylsl, and pygame for `cibles_ssvep.py`:

```bash
pip install pylsl pygame
python cibles_ssvep.py   # Esc quits: the mode it started is stopped
python example.py        # Ctrl+C stops it
```

Then, in the console: **Connect an application**, pick `mon-appli-…`, then **Connect**.

## What happens (`cibles_ssvep.py`)

1. The application sends the settings of `config.json`. The engine chooses three frequencies that
   divide the screen refresh rate (12, 15 and 20 Hz at 60 Hz) and returns them in its reply to
   the start of the mode: the three targets blink at those frequencies.
2. For about 25 s, the targets blink and the person looks at none of them: the engine warms up
   and measures its rest. The top of the window counts down.
3. The person then looks at the red dot of a target. The engine decodes it, the application
   circles it in green, and `on_decision()` is called each time the decoded target changes.
4. Esc closes the window and stops the mode.

## `config.json`

| Key | Meaning | Default |
|---|---|---|
| `app_name` | the start of the name the console lists (a random part is added) | `my-app` |
| `mode` | `ssvep`, `mi`, `neuro`, `p300`, `errp` or `cvep` (`cibles_ssvep.py`: `ssvep` only) | `ssvep` |
| `params` | the settings of the mode, sent with `set_params` (keys: [`docs/control.md`](../../../docs/control.md)) | `{}` |
| `propose_refresh_hz` | SSVEP on a screen: the refresh rate whose divisors the engine proposes as frequencies; `0` = do not ask | `0` |
| `stop_mode_on_exit` | stop, at the end, the mode this application started | `true` |
| `search_timeout_s` | how long to look for an engine before giving up | `30` |

The provided file sets an SSVEP on a screen, three targets named `haut`, `droite` and `gauche`,
and frequencies proposed for a 60 Hz screen. A key that is not in this table is refused, with the
list of the known ones.

## Things to know

- **The screen must run at `propose_refresh_hz`** (60 Hz here): the targets blink by counting
  frames. The bottom of the window shows the measured frames per second. If it is not 60, set the
  screen to 60 Hz (Windows: Settings → Display → Advanced display), or set `propose_refresh_hz`
  to the screen's rate.
- **`-1` means "no decision"**, never target 0.
- In `cibles_ssvep.py`, `on_decision()` runs on the thread that reads the decisions, not on the
  one that draws: draw nothing there, keep a value that the drawing loop reads.
- A setting that the engine accepts, then fails to apply, stops the application with the engine's
  reason.
- To use the library in your own project: [`../client/`](../client/).
