# Arduino UNO R4 WiFi client (UDP over Wi-Fi)

`EegApiDevice` connects an Arduino UNO R4 WiFi to the EEG_API_Unicorn console over Wi-Fi, with no
computer in between. This folder is the library alone, to start from scratch in your own sketch;
for a complete sketch to copy and upload, see [`../exemple/`](../exemple/).

| File | Role |
|---|---|
| `EegApiDevice.h`, `EegApiDevice.cpp` | the library: the UDP protocol. Do not edit it |

The same two files serve the ESP32. Needs the "Arduino UNO R4 Boards" core and the ArduinoJson 7
library (`arduino-cli lib install ArduinoJson`).

## Use it in your sketch

Copy both files into the folder of your sketch, next to its `.ino`, then:

```cpp
#include "EegApiDevice.h"
EegApiDevice eeg;

void onDecision(JsonObject d) {                 // channels by name; -1 = no decision
  int task = (int) lroundf(d["intent_index"] | -1.0f);
}

void setup() {
  // ... connect the Wi-Fi first
  eeg.onDecision(onDecision);
  eeg.begin({"my-app", "", 5011, "", 5010, "mi", "{}"});
}

void loop() {
  eeg.loop();                                   // often: never block the loop for long
}
```

The other callbacks: `onSettingsAccepted`, `onDisconnected` (back to rest), `onRefused`,
`onPhase` (`warmup`, `baseline`, `decoding`…) and `onIdentify`.

## Things to know

- Only the console listens to UDP; `server.py` alone does not. Modes served: `ssvep`, `mi`,
  `neuro`. For an SSVEP on LEDs, use an ESP32: it blinks them in hardware.
- `printf` on this board does not format floating-point numbers: print them with
  `Serial.print(value, 2)`.
