# ESP32 example: two LEDs (UDP over Wi-Fi)

A second ESP32 sketch, self-contained: two SSVEP targets (two LEDs, 13 Hz "left" and 15 Hz
"right") driven over Wi-Fi by the EEG_API_Unicorn console, with no computer in between. Unlike
[`../exemple/`](../exemple/), it speaks the protocol with its own code (no `EegApiDevice`), and its
settings are written in the sketch.

| File | Role |
|---|---|
| `exemple_leds.ino` | the whole sketch: Wi-Fi, protocol, LEDs |
| `secrets.example.h` | the Wi-Fi settings: copy it to `secrets.h`, then edit `secrets.h` |

⚠️ `secrets.h` holds your Wi-Fi password: do not publish it.

## Build and upload

Needs the ESP32 core for Arduino and the ArduinoJson 7 library:

```bash
arduino-cli core install esp32:esp32
arduino-cli lib install ArduinoJson
arduino-cli compile --fqbn esp32:esp32:esp32doit-devkit-v1 exemple_leds
arduino-cli upload --fqbn esp32:esp32:esp32doit-devkit-v1 -p COM5 exemple_leds
```

## Wiring

ESP32 DevKit V1: GPIO 25 → LED of target 0 → GND, GPIO 26 → LED of target 1 → GND, long leg on
the GPIO side, a resistor in series with each LED (33 Ω for a white or blue LED, about 100 Ω for a
red one). The board's blue LED (GPIO 2) is on while a console is connected.

## What happens

1. The board announces itself every second. In the console: **Connect an application**, pick
   `esp32-leds`, then **Connect**. **Identify** blinks both targets and the blue LED slowly.
2. It sets the SSVEP up, makes both targets blink, then starts the mode: warm-up and rest (about
   23 s), during which the person looks at no target.
3. At each decision, the chosen target turns steady for 3 s while the other keeps blinking.
4. **Disconnect** in the console, the console closed, or 5 s without news: everything goes off and
   the board announces itself again.

The serial monitor (115200 bauds) says what the board does.
