# The protocol, step by step

Three Python scripts that are not ready-made clients: they show what the libraries of the other
folders hide. Read them to write a client in a language not covered here; the full contract is in
[`docs/control.md`](../../docs/control.md).

| File | What it does | Needs |
|---|---|---|
| `receiver.py` | prints, one line per sample, any stream the engine publishes (`--list` shows what is on the network). A quick way to check that the engine publishes | pylsl |
| `control_client.py` | drives the engine over LSL with the raw handshake: creates the command stream, waits to be connected, sets the SSVEP up, starts it, reads three decisions, stops it. Every command and reply is printed | pylsl |
| `udp_device.py` | plays an ESP32 over UDP, with the standard library only: announces itself, waits to be connected, sets the SSVEP up, prints the decisions the engine pushes | nothing |

```bash
python receiver.py --stream decoded_ssvep
python control_client.py
python udp_device.py --engine-host 127.0.0.1
```

`--help` lists the options of each script.

- `receiver.py` and `control_client.py` work with the console or with `server.py` alone. With the
  console, `control_client.py` waits until someone clicks **Connect an application**, picks it,
  then **Connect**.
- `udp_device.py` needs the console: `server.py` alone does not listen to UDP.
