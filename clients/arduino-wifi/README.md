# Arduino UNO R4 WiFi client (UDP over Wi-Fi)

An Arduino UNO R4 WiFi connected to the EEG_API_Unicorn console over Wi-Fi, with no computer in
between. It lights the LED of the decoded Motor Imagery task, or prints the Neuro values. For an
SSVEP on LEDs, use the ESP32 client ([`../esp32/`](../esp32/)): it blinks the targets in hardware.

| File | Role |
|---|---|
| `arduino_client/config.h` | the settings: Wi-Fi, name, mode, pins. Edit this one |
| `arduino_client/arduino_client.ino` | the application: replace `onDecision()` with yours |
| `arduino_client/EegApiDevice.h`, `.cpp` | the library: the UDP protocol (the same files as `clients/esp32/`) |

⚠️ `config.h` holds your Wi-Fi password: do not publish it.

## Build and upload

Needs the "Arduino UNO R4 Boards" core and the ArduinoJson 7 library. With the Arduino IDE:
install both, open `arduino_client/arduino_client.ino`, pick "Arduino UNO R4 WiFi", then Upload.
With arduino-cli:

```bash
arduino-cli core install arduino:renesas_uno
arduino-cli lib install ArduinoJson
arduino-cli compile --fqbn arduino:renesas_uno:unor4wifi arduino_client
arduino-cli upload --fqbn arduino:renesas_uno:unor4wifi -p COM6 arduino_client
```

The serial monitor (115200 bauds) says what the board does.

## `config.h`

| Setting | Meaning |
|---|---|
| `WIFI_SSID`, `WIFI_PASS` | the network the console's computer is on too (2.4 GHz) |
| `CONSOLE_IP` | `""` = announcements broadcast on the network; otherwise the console computer's IP address |
| `APP_NAME`, `DEVICE_ID` | the name the console lists, and the identifier next to it (`""` = the end of the MAC address) |
| `DEVICE_PORT`, `ENGINE_PORT` | the UDP port of this board, and the console's (`5010`) |
| `MODE` | `"mi"` (the LED of the decoded task lights up) or `"neuro"` (values on the serial monitor) |
| `TASK_PINS` | one LED per task, in the order of the model's tasks, each with a resistor in series (about 220 Ω) |
| `SETTINGS` | the settings of the mode, as a JSON object ([`docs/control.md`](../../docs/control.md)); `"{}"` = those of the console |
| `STATUS_LED` | the board's LED: on while connected, blinking after a refusal (`-1` = none) |

## What happens

1. The board announces itself every second. In the console: **Connect an application**, pick
   `arduino-app` (shown with its identifier), then **Connect**. **Identify** blinks the LEDs
   slowly, 3 times.
2. It sends its settings and starts the mode. The Motor Imagery needs a trained model: choose it
   in the console, then **Start decoding**.
3. At each decision, the LED of the decoded task lights up and the others go off; none while the
   decoder is not sure (`-1`).
4. **Disconnect** in the console, the console closed, or 5 s without news: everything goes off and
   the board announces itself again. The engine stops the mode the board started.

The library is the same as the ESP32's: see [`../esp32/README.md`](../esp32/README.md), "Using
the library in your own sketch".

## Things to know

- Only the console listens to UDP; `server.py` alone does not.
- `printf` on this board does not format floating-point numbers: print them with
  `Serial.print(value, 2)`, as the sketch does for Neuro.
- When the console never lists the board, see [`docs/network.md`](../../docs/network.md)
  (firewall, a computer on several networks), and try `CONSOLE_IP`.
