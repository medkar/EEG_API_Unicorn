# MATLAB client (LSL)

Connects a MATLAB session to EEG_API_Unicorn over LSL, from any computer of the network.

| File | Role |
|---|---|
| `config.json` | the settings: edit this one |
| `EegApi.m` | the library: the handshake, the commands, the decisions |
| `example.m` | a complete application: replace `onDecision()` with yours |

Needs MATLAB R2016b or later (`jsondecode`, `jsonencode`) and
[liblsl-Matlab](https://github.com/labstreaminglayer/liblsl-Matlab): take the release for your
platform and MATLAB version from its release page, or build it from its sources (`build_mex`).

```matlab
addpath(genpath('C:\path\to\liblsl-Matlab'));
cd C:\path\to\clients\matlab
example            % Ctrl+C stops it: the mode it started is stopped
```

Then, in the console: **Connect an application**, pick `my-matlab-app-…`, then **Connect**.

## `config.json`

The same keys as the Python client ([`../python-lsl/README.md`](../python-lsl/README.md)):
`app_name`, `mode`, `params`, `propose_refresh_hz`, `stop_mode_on_exit`, `search_timeout_s`. A key
that is not one of them is refused.

## Using the library in your own code

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

## Things to know

- Use `onCleanup` in a **function**, as `example.m` does: in a script, Ctrl+C would leave the mode
  running and the streams open.
- `jsondecode` turns a one-element JSON array into a number: in `config.json`, a single frequency
  or name stays a number or a text, not a list, when it is sent back. Give the lists of the mode
  at least two elements.
