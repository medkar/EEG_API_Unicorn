# Raspberry Pi client (UDP)

`eeg_api_udp.py` connects a device to the EEG_API_Unicorn console over UDP, with the Python
standard library only: a Raspberry Pi, any Linux board, or any computer without LSL. This folder
is the library alone, to start from scratch in your own project; for a complete device to copy
and run, see [`../exemple/`](../exemple/).

Needs Python 3.8 or later, nothing else.

## Use it in your project

Copy `eeg_api_udp.py` next to your program, with a `config.json` (the keys are below; an example:
[`../exemple/config.json`](../exemple/config.json)). Do not edit the library.

```python
from eeg_api_udp import EegApiDevice, load_config

device = EegApiDevice(load_config("config.json"), on_identify=my_blink)
device.connect()                       # announces itself until the console connects it
device.start()                         # sends the settings, starts the mode
for decision in device.decisions():    # one dict per decision, channels by name
    ...
device.close()                         # stops the mode it started, says "bye"
```

`connect()` and `decisions()` take `should_stop`, a function checked between messages: they
return when it is true (useful from another thread). `device.why_disconnected()` says why the
connection ended.

## `config.json`

| Key | Meaning | Default |
|---|---|---|
| `app_name` | the name the console lists | `my-device` |
| `device_id` | the identifier shown next to it; empty = the end of the MAC address | `""` |
| `device_port` | the UDP port this device listens to, and announces | `5011` |
| `engine_host` | where the announcements go: `255.255.255.255` (broadcast), or the IP address of the console's computer | `255.255.255.255` |
| `engine_port` | the UDP port of the console | `5010` |
| `mode` | `ssvep`, `mi` or `neuro` | `ssvep` |
| `params` | the settings of the mode, sent with `set_params` (keys: [`docs/control.md`](../../../docs/control.md)) | `{}` |
| `propose_refresh_hz` | SSVEP on a screen: the refresh rate whose divisors the engine proposes; `0` = do not ask | `0` |
| `stop_mode_on_exit` | stop, at the end, the mode this device started | `true` |

## Things to know

- Only the console listens to UDP; `server.py` alone does not.
- Everything is sent from the announced port: the engine recognises the device by the address its
  datagrams come from.
- No news from the engine for 5 s ends the connection, on both sides.
