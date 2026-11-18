# ESP32 client (UDP over Wi-Fi)

`EegApiDevice` connects an ESP32 to the EEG_API_Unicorn console over Wi-Fi, with no computer in
between. This folder is the library alone, to start from scratch in your own sketch; for a
complete sketch to copy and upload (its LEDs are the SSVEP targets), see
[`../exemple/`](../exemple/).

| File | Role |
|---|---|
| `EegApiDevice.h`, `EegApiDevice.cpp` | the library: the UDP protocol. Do not edit it |

The same two files serve the Arduino UNO R4 WiFi. Needs the ESP32 core for Arduino and the
ArduinoJson 7 library (`arduino-cli lib install ArduinoJson`).

## Use it in your sketch

Copy both files into the folder of your sketch, next to its `.ino`, then:

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
- At 2.4 GHz only: the ESP32 does not see 5 GHz networks.
- The ESP32 does not reassemble fragmented datagrams: a message longer than about 1470 bytes never
  reaches it. The messages of the modes served over UDP are much shorter.
