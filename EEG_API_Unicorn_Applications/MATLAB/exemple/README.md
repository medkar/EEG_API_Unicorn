# MATLAB example (LSL)

A complete MATLAB application that connects to EEG_API_Unicorn over LSL, from any computer of the
network, and prints every decision. This folder holds everything it needs: copy it into your
workspace and run it.

| File | Role |
|---|---|
| `config.json` | the settings: edit this one |
| `example.m` | a complete application: replace `onDecision()` with yours |
| `EegApi.m` | the library: the handshake, the commands, the decisions. Do not edit it |

Needs MATLAB R2016b or later (`jsondecode`, `jsonencode`) and
[liblsl-Matlab](https://github.com/labstreaminglayer/liblsl-Matlab): take the release for your
platform and MATLAB version from its release page, or build it from its sources (`build_mex`).

```matlab
addpath(genpath('C:\path\to\liblsl-Matlab'));
cd C:\path\to\exemple
example            % Ctrl+C stops it: the mode it started is stopped
```

Then, in the console: **Connect an application**, pick `my-matlab-app-…`, then **Connect**.

## `config.json`

| Key | Meaning | Default |
|---|---|---|
| `app_name` | the start of the name the console lists (a random part is added) | `my-app` |
| `mode` | `ssvep`, `mi`, `neuro`, `p300`, `errp` or `cvep` | `ssvep` |
| `params` | the settings of the mode, sent with `set_params` (keys: [`docs/control.md`](../../../docs/control.md)) | `{}` |
| `propose_refresh_hz` | SSVEP on a screen: the refresh rate whose divisors the engine proposes as frequencies; `0` = do not ask | `0` |
| `stop_mode_on_exit` | stop, at the end, the mode this application started | `true` |
| `search_timeout_s` | how long to look for an engine before giving up | `30` |

A key that is not in this table is refused.

## Things to know

- Use `onCleanup` in a **function**, as `example.m` does: in a script, Ctrl+C would leave the mode
  running and the streams open.
- A setting that the engine accepts, then fails to apply, stops `example` with the engine's
  reason.
- `jsondecode` turns a one-element JSON array into a number: in `config.json`, a single frequency
  or name stays a number or a text, not a list, when it is sent back. Give the lists of the mode
  at least two elements.
- To use the library in your own project: [`../client/`](../client/).
