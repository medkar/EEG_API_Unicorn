# Raspberry Pi client (UDP)

Connects a device to the EEG_API_Unicorn console over UDP, with the Python standard library only:
a Raspberry Pi, any Linux board, or any computer without LSL.

| File | Role |
|---|---|
| `config.json` | the settings: edit this one |
| `eeg_api_udp.py` | the library: the UDP protocol |
| `example.py` | a complete device: replace `on_decision()` and `on_identify()` with yours |

Needs Python 3.8 or later, nothing else.

```bash
python3 example.py       # Ctrl+C stops it: the mode it started is stopped
```

The device announces itself every second. In the console: **Connect an application**, pick
`my-device` (shown with its identifier), then **Connect**. **Identify** calls `on_identify()`.
After a disconnection, the example announces itself again.

## `config.json`

| Key | Meaning | Default |
|---|---|---|
| `app_name` | the name the console lists | `my-device` |
| `device_id` | the identifier shown next to it; empty = the end of the MAC address | `""` |
| `device_port` | the UDP port this device listens to, and announces | `5011` |
| `engine_host` | where the announcements go: `255.255.255.255` (broadcast), or the IP address of the console's computer | `255.255.255.255` |
| `engine_port` | the UDP port of the console | `5010` |
| `mode` | `ssvep`, `mi` or `neuro` | `ssvep` |
| `params` | the settings of the mode, sent with `set_params` (keys: [`docs/control.md`](../../docs/control.md)) | `{}` |
| `propose_refresh_hz` | SSVEP on a screen: the refresh rate whose divisors the engine proposes; `0` = do not ask | `0` |
| `stop_mode_on_exit` | stop, at the end, the mode this device started | `true` |

The provided `config.json` drives two physical targets (LEDs blinking at 13 and 15 Hz, driven by
the device). On a screen, use `"targets_on": "screen"` and `propose_refresh_hz`.

## Using the library in your own code

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

## Things to know

- Only the console listens to UDP; `server.py` alone does not.
- Everything is sent from the announced port: the engine recognises the device by the address its
  datagrams come from.
- No news from the engine for 5 s ends the connection, on both sides.
- When the console never lists the device, the broadcast does not reach it (a computer on several
  networks, a VPN, the firewall): put the console's IP address in `engine_host`, and see
  [`docs/network.md`](../../docs/network.md).
