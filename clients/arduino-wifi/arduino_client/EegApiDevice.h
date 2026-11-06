// EegApiDevice: connects a microcontroller to the EEG_API_Unicorn console over UDP. Do not edit
// this file: the settings are in config.h, and the application is the sketch (.ino), which
// receives the decisions through callbacks.
//
// The protocol follows docs/control.md, "Over the network (UDP)": one JSON object per datagram,
// carrying "v": 1; the device announces itself every second (hello) until someone clicks
// "Connect an application", picks it, then "Connect"; it then sends its settings (set_params)
// and starts the mode (start_mode); the engine pushes its status and every decision. Both sides
// send "alive" every second; 5 s of silence ends the connection, and the device announces
// itself again. Modes served over UDP: ssvep, mi, neuro.
//
// Boards: ESP32 (lwIP sockets) and Arduino UNO R4 WiFi (WiFiS3). Library: ArduinoJson 7.
//
// Usage, in the sketch:
//   EegApiDevice eeg;
//   setup(): connect the Wi-Fi, set the callbacks, then eeg.begin(settings);
//   loop():  eeg.loop(); as often as possible, never blocked for long.

#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

#if defined(ARDUINO_ARCH_ESP32)
  #include <WiFi.h>
#elif defined(ARDUINO_UNOR4_WIFI)
  #include <WiFiS3.h>
#else
  #error "EegApiDevice: board not supported (ESP32 or Arduino UNO R4 WiFi)"
#endif

struct EegApiSettings {
  const char *appName;        // the name the console lists under "Connect an application"
  const char *deviceId;       // shown next to the name; "" = the end of the MAC address
  uint16_t devicePort;        // the UDP port this device listens to, and announces
  const char *engineIp;       // where the hellos go: "" = broadcast on the local network
  uint16_t enginePort;        // the UDP port of the console (5010)
  const char *mode;           // "ssvep", "mi" or "neuro"
  const char *settingsJson;   // the settings of the mode, a JSON object (docs/control.md); "{}" = none
};

class EegApiDevice {
 public:
  typedef void (*Callback)();
  typedef void (*TextCallback)(const char *text);
  typedef void (*DecisionCallback)(JsonObject decision);

  // A decision: "mode", then the channels of the mode's decoded stream, by name (SSVEP
  // target_index, freq_hz, confidence…). Every value is a number; -1 means "no decision".
  void onDecision(DecisionCallback callback) { decisionCallback = callback; }
  // "Identify" in the console: show which device this is (blink a LED).
  void onIdentify(Callback callback) { identifyCallback = callback; }
  // The settings are accepted (or there are none): SSVEP targets must start blinking now, before
  // the start: the engine measures its rest with the targets blinking.
  void onSettingsAccepted(Callback callback) { settingsCallback = callback; }
  // The connection ended (disconnected, console closed, 5 s of silence, or the same console
  // connecting again): announcing again, or starting over. Put the outputs back to rest.
  void onDisconnected(Callback callback) { disconnectedCallback = callback; }
  // The phase of the mode changed: "warmup", "baseline" (look at no target), "decoding"…
  void onPhase(TextCallback callback) { phaseCallback = callback; }
  // The engine refused the settings or the start (the reason, in English).
  void onRefused(TextCallback callback) { refusedCallback = callback; }

  // After the Wi-Fi is connected, and again after each reconnection of the Wi-Fi.
  bool begin(const EegApiSettings &settings);
  void loop();
  bool connected() const { return state != ANNOUNCING; }
  bool decoding() const { return state == PLAYING; }
  const char *phase() const { return currentPhase; }
  const char *id() const { return ident; }

 private:
  enum State : uint8_t { ANNOUNCING, SETTING, STARTING, PLAYING, REFUSED };

  EegApiSettings settings;
  State state = ANNOUNCING;
  char ident[6] = "";
  IPAddress engineAddress;
  uint16_t enginePortSeen = 0;
  char consoleHost[64] = "";
  long lastSeq = 0;
  uint32_t heardMs = 0, aliveMs = 0, helloMs = 0, sentMs = 0;
  long nextRef = 1, pendingRef = 0, startRef = 0;
  char command[1024];
  size_t commandLength = 0;
  char currentPhase[16] = "";
  bool open = false;

  Callback identifyCallback = nullptr, settingsCallback = nullptr, disconnectedCallback = nullptr;
  TextCallback phaseCallback = nullptr, refusedCallback = nullptr;
  DecisionCallback decisionCallback = nullptr;

  // The transport: one socket bound to the announced port sends everything.
  bool openSocket();
  void sendText(const char *text, size_t n, IPAddress ip, uint16_t port);
  void sendJson(JsonDocument &doc, IPAddress ip, uint16_t port);
  void readAll();
  IPAddress broadcastAddress();

  void hello();
  void sendCommand(JsonDocument &doc);
  void setParams();
  void startMode();
  void finish(const char *why);
  void refuse(const char *what, const char *reason);
  void connectRequest(JsonDocument &m, IPAddress ip, uint16_t port);
  void reply(JsonDocument &m);
  void receive(const char *text, size_t n, IPAddress ip, uint16_t port);
};
