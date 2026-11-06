// The settings of esp32_client: the only file to edit. Everything else works as it is.
// ⚠️ This file holds your Wi-Fi password: do not publish it.

// --- The network ----------------------------------------------------------------------------

// The Wi-Fi network the console's computer is on too: that computer's mobile hotspot, or the
// Wi-Fi of a router. At 2.4 GHz: the ESP32 does not see 5 GHz.
#define WIFI_SSID "network-name"
#define WIFI_PASS "password"

// Optional, a second network: the ESP32 takes the one it sees, the strongest if it sees both.
// #define WIFI_SSID_2 "network-name-2"
// #define WIFI_PASS_2 "password-2"

// Where the announcements go. "" = broadcast on the local network, which is usually enough.
// Otherwise the IP address of the console's computer (useful when the console never lists the
// device: a computer on several networks, a VPN). On the Windows mobile hotspot, the computer is
// at 192.168.137.1.
#define CONSOLE_IP ""

// --- The application ------------------------------------------------------------------------

// The name the console lists under "Connect an application", and the identifier shown next to
// it ("" = the end of the board's MAC address).
#define APP_NAME "esp32-app"
#define DEVICE_ID ""

// The UDP port this device listens to (any free port), and the console's (5010).
#define DEVICE_PORT 5011
#define ENGINE_PORT 5010

// The mode: "ssvep" (the LEDs ARE the targets: each one blinks at its frequency), "mi" (the LED
// of the decoded task lights up) or "neuro" (the values go to the serial monitor).
#define MODE "ssvep"

// One LED per target (SSVEP), or per task (MI, in the order of the model's tasks). Each LED has a
// resistor in series: (3.3 V - the LED's forward voltage) / the current, under about 20 mA per
// pin; 33 ohm suits a white or blue LED (about 3 V), about 100 ohm a red one.
#define TARGET_PINS {25, 26}

// SSVEP: the frequency (Hz) and the name of each target, in the order of TARGET_PINS. On LEDs any
// frequency works (no screen refresh rate to divide), at least 0.67 Hz apart.
#define TARGET_FREQS {13.0, 15.0}
#define TARGET_NAMES {"left", "right"}

// Other settings of the mode, a JSON object (docs/control.md, "Settings"). For SSVEP, targets_on,
// freqs and target_names are added from the lines above. Example: "{\"band_low\": 6}".
#define EXTRA_SETTINGS "{}"

// SSVEP: the chosen target stays steady for HOLD_MS, then decisions are ignored for REARM_MS more
// (the decoder's window still contains the pause).
#define HOLD_MS 3000
#define REARM_MS 1500

// The board's LED: on while a console is connected, blinking after a refusal. -1 = none.
#define STATUS_LED 2
