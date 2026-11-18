# MATLAB client (LSL)

`EegApi.m` connects a MATLAB session to EEG_API_Unicorn over LSL, from any computer of the
network. This folder is the library alone, to start from scratch in your own project; for a
complete application to copy and run, see [`../exemple/`](../exemple/).

Needs MATLAB R2016b or later (`jsondecode`, `jsonencode`) and
[liblsl-Matlab](https://github.com/labstreaminglayer/liblsl-Matlab): take the release for your
platform and MATLAB version from its release page, or build it from its sources (`build_mex`).

## Use it in your project

Copy `EegApi.m` next to your code, with a `config.json` (the keys are below; an example:
[`../exemple/config.json`](../exemple/config.json)). Do not edit the library.

```matlab
api = EegApi(EegApi.loadConfig('config.json'));
cleanup = onCleanup(@() api.close());   % stops the mode it started, even on Ctrl+C
api.connect();                          % waits until the console connects this application
api.start();                            % sends the settings, starts the mode
while api.isConnected()
    decision = api.nextDecision(0.2);   % a struct, channels by name; [] if none yet
    if ~isempty(decision)
        ...
    end
end
disp(api.whyDisconnected());
```

`nextDecision` returns `[]` while the mode warms up, measures its rest, or waits for a model; it
opens the decoded stream again when the engine recreates it. `api.send(cmd, params)` sends any of
the four commands and returns its reply as a struct. `api.Labels` holds the channel names, in the
order of the stream.

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

- `start()` fails (`EegApi:refused`) on a refused command, and (`EegApi:failed`) when the engine
  accepts a command and then fails to apply it: "accepted" is not "in force". `nextDecision`
  fails the same way when the mode could not start.
- Use `onCleanup` in a **function**: in a script, Ctrl+C would leave the mode running and the
  streams open.
- `jsondecode` turns a one-element JSON array into a number: in `config.json`, a single frequency
  or name stays a number or a text, not a list, when it is sent back. Give the lists of the mode
  at least two elements.
