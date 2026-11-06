// The settings of arduino_client: the only file to edit. Everything else works as it is.
// ⚠️ This file holds your Wi-Fi password: do not publish it.

// --- The network ----------------------------------------------------------------------------

// The Wi-Fi network the console's computer is on too: that computer's mobile hotspot, or the
// Wi-Fi of a router. At 2.4 GHz: the board does not see 5 GHz.
#define WIFI_SSID "network-name"
#define WIFI_PASS "password"

// Where the announcements go. "" = broadcast on the local network, which is usually enough.
// Otherwise the IP address of the console's computer (useful when the console never lists the
// device: a computer on several networks, a VPN). On the Windows mobile hotspot, the computer is
// at 192.168.137.1.
#define CONSOLE_IP ""

// --- The application ------------------------------------------------------------------------

// The name the console lists under "Connect an application", and the identifier shown next to
// it ("" = the end of the board's MAC address).
#define APP_NAME "arduino-app"
#define DEVICE_ID ""

// The UDP port this device listens to (any free port), and the console's (5010).
#define DEVICE_PORT 5011
#define ENGINE_PORT 5010

// The mode: "mi" (the LED of the decoded task lights up) or "neuro" (the values go to the serial
// monitor). For an SSVEP on LEDs, use an ESP32 (clients/esp32): it blinks them in hardware.
#define MODE "mi"

// One LED per task, in the order of the model's tasks. Each LED has a resistor in series (about
// 220 ohm at 5 V).
#define TASK_PINS {2, 3}

// The settings of the mode, a JSON object (docs/control.md, "Settings"). "{}" = those of the
// console. Example: "{\"smoothing\": 0.9}" for neuro.
#define SETTINGS "{}"

// The board's LED: on while a console is connected, blinking after a refusal. -1 = none.
#define STATUS_LED LED_BUILTIN
