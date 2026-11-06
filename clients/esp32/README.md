# ESP32 client (UDP over Wi-Fi)

An ESP32 connected to the EEG_API_Unicorn console over Wi-Fi, with no computer in between. For
SSVEP, its LEDs are the targets: they blink in hardware (the ESP32's LEDC peripheral), at
frequencies that neither the Wi-Fi nor the code can shift.

| File | Role |
|---|---|
| `esp32_client/config.h` | the settings: Wi-Fi, name, mode, pins, frequencies. Edit this one |
| `esp32_client/esp32_client.ino` | the application: replace `onDecision()` with yours |
| `esp32_client/EegApiDevice.h`, `.cpp` | the library: the UDP protocol (the same files as `clients/arduino-wifi/`) |

⚠️ `config.h` holds your Wi-Fi password: do not publish it.

## Build and upload

Needs the ESP32 core for Arduino and the ArduinoJson 7 library. With the Arduino IDE: install
"esp32" (Espressif) in the Boards Manager and "ArduinoJson" in the Library Manager, open
`esp32_client/esp32_client.ino`, pick the board (an ESP32 DevKit V1: "DOIT ESP32 DEVKIT V1"),
then Upload. With arduino-cli:

```bash
arduino-cli core install esp32:esp32
arduino-cli lib install ArduinoJson
arduino-cli compile --fqbn esp32:esp32:esp32doit-devkit-v1 esp32_client
arduino-cli upload --fqbn esp32:esp32:esp32doit-devkit-v1 -p COM5 esp32_client
```

The serial monitor (115200 bauds) says what the board does.

## Wiring

One LED per target, from the pin of `TARGET_PINS` to GND, long leg on the pin side, with a
resistor in series: (3.3 V − the LED's forward voltage) / the current, under about 20 mA per pin.
33 Ω suits a white or blue LED (about 3 V), about 100 Ω a red one. The board's LED (`STATUS_LED`)
is on while a console is connected and blinks after a refusal.

## `config.h`

| Setting | Meaning |
|---|---|
| `WIFI_SSID`, `WIFI_PASS` | the network the console's computer is on too (2.4 GHz); `WIFI_SSID_2`, `WIFI_PASS_2` for a second one |
| `CONSOLE_IP` | `""` = announcements broadcast on the network; otherwise the console computer's IP address |
| `APP_NAME`, `DEVICE_ID` | the name the console lists, and the identifier next to it (`""` = the end of the MAC address) |
| `DEVICE_PORT`, `ENGINE_PORT` | the UDP port of this board, and the console's (`5010`) |
| `MODE` | `"ssvep"` (the LEDs blink: they are the targets), `"mi"` (the LED of the decoded task lights up) or `"neuro"` (values on the serial monitor) |
| `TARGET_PINS` | one pin per target (SSVEP) or per task (MI, in the order of the model's tasks); 4 at most |
| `TARGET_FREQS`, `TARGET_NAMES` | SSVEP: the frequency and the name of each target, in the order of `TARGET_PINS`, at least 0.67 Hz apart |
| `EXTRA_SETTINGS` | other settings of the mode, as a JSON object ([`docs/control.md`](../../docs/control.md)); for SSVEP, the targets are added from the lines above |
| `HOLD_MS`, `REARM_MS` | SSVEP: the chosen target stays steady `HOLD_MS`, then decisions are ignored `REARM_MS` more |
| `STATUS_LED` | the board's LED (`-1` = none) |

## What happens

1. The board announces itself every second. In the console: **Connect an application**, pick
   `esp32-app` (shown with its identifier), then **Connect**. **Identify** blinks the LEDs slowly,
   3 times.
2. It sends its settings. For SSVEP, the LEDs start blinking as soon as they are accepted, then the
   mode starts: warm-up and rest (about 23 s), during which the person looks at no target.
3. At each decision, the chosen target turns steady for `HOLD_MS` while the others keep blinking,
   then all blink again.
4. **Disconnect** in the console, the console closed, or 5 s without news: everything goes off and
   the board announces itself again. The engine stops the mode the board started.

A refused setting or start (for example, a test already running in the console): the LEDs stay
off, the board's LED blinks, the reason is on the serial monitor. **Disconnect** then **Connect**
in the console tries again.

## Using the library in your own sketch

```cpp
#include "EegApiDevice.h"
EegApiDevice eeg;

void onDecision(JsonObject d) {                 // channels by name; -1 = no decision
  int target = (int) lroundf(d["target_index"] | -1.0f);
}

void setup() {
  // ... connect the Wi-Fi first
  eeg.onDecision(onDecision);
  eeg.begin({"my-app", "", 5011, "", 5010, "ssvep", "{\"targets_on\": \"physical\", \"freqs\": [13, 15]}"});
}

void loop() {
  eeg.loop();                                   // often: never block the loop for long
}
```

The other callbacks: `onSettingsAccepted` (start the targets), `onDisconnected` (back to rest),
`onRefused`, `onPhase` (`warmup`, `baseline`, `decoding`…) and `onIdentify`.

## Things to know

- Only the console listens to UDP; `server.py` alone does not. Modes served: `ssvep`, `mi`,
  `neuro`.
- At 2.4 GHz only: the ESP32 does not see 5 GHz networks. On the Windows mobile hotspot, the
  computer is at 192.168.137.1.
- The ESP32 does not reassemble fragmented datagrams: a message longer than about 1470 bytes never
  reaches it. The messages of the modes served over UDP are much shorter.
- When the console never lists the board, see [`docs/network.md`](../../docs/network.md)
  (firewall, a computer on several networks), and try `CONSOLE_IP`.
