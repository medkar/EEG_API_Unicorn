// Two SSVEP targets (two LEDs) driven over Wi-Fi by the EEG_API_Unicorn console, with NO computer
// in between: the ESP32 speaks the engine's network protocol itself (docs/control.md, section
// "Over the network (UDP)"; the same device in Python: examples/udp_device.py).
//
// What happens:
//   1. It announces itself every second on its network (a "hello" broadcast to port 5010 of the
//      console). In the console: "Connect an application", pick "esp32-leds" (shown with the end
//      of the board's MAC address), then "Connect". "Identify" blinks both targets and the blue
//      LED slowly (3 times, at 1 Hz).
//   2. Once connected, it sets the SSVEP up (physical targets, 13 Hz "left" and 15 Hz "right"),
//      makes both targets blink, then starts the mode: warm-up and rest (~23 s), during which you
//      look at NO target.
//   3. At each decision of the engine, the chosen target turns STEADY for 3 s while the other keeps
//      blinking. Decisions are ignored during that pause, then for 1.5 s more: the decoder's window
//      still contains the pause. Then it starts again.
//   4. "Disconnect" in the console, the console closed, or 5 s without news from the engine:
//      everything goes off and it announces itself again. The engine stops by itself the SSVEP
//      the ESP32 started.
// A setting or a start refused (an SSVEP test already running in the console, for example): the
// targets stay off, the blue LED blinks, the reason is on the serial monitor. "Disconnect" then
// "Connect" in the console tries again.
//
// The blinking is done by the ESP32's LEDC peripheral, in hardware: neither the Wi-Fi nor the code
// can shift it.
//
// The network goes through the lwIP sockets, not WiFiUDP: WiFiUDP cuts every received datagram at
// 1460 bytes, and a reply of the engine can be longer (the API asks to read up to 8 KB). A single
// socket, bound to the announced port, sends everything: the engine recognises the device by the
// address its datagrams come from. Limit: the ESP32 Arduino core does not reassemble fragmented
// datagrams, so a message longer than ~1470 bytes never reaches it (the SSVEP ones are much
// shorter: about 300 bytes at most).
//
// Wiring (ESP32 DevKit V1): GPIO 25 -> LED of target 0 -> GND, GPIO 26 -> LED of target 1 -> GND,
// long leg on the GPIO side, a resistor in series with each LED: (3.3 V - the LED's forward
// voltage) / the current, under about 20 mA per pin; 33 ohm suits a white or blue LED (about
// 3 V), about 100 ohm a red one. The board's blue LED (GPIO 2) is on while a console is connected.
//
// The Wi-Fi credentials go in secrets.h (copy secrets.example.h): one network, or two.
// Library: ArduinoJson 7 (arduino-cli lib install ArduinoJson).

#include <WiFi.h>
#include <WiFiMulti.h>
#include <ArduinoJson.h>
#include "lwip/sockets.h"
#include "esp_mac.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "secrets.h"

const uint8_t N_TARGETS = 2;
const gpio_num_t PINS[N_TARGETS] = {GPIO_NUM_25, GPIO_NUM_26};
const ledc_channel_t CHANNELS[N_TARGETS] = {LEDC_CHANNEL_0, LEDC_CHANNEL_1};
const ledc_timer_t TIMERS[N_TARGETS] = {LEDC_TIMER_0, LEDC_TIMER_1};  // one timer per target
const ledc_mode_t SPEED_MODE = LEDC_HIGH_SPEED_MODE;
const uint32_t BITS = 14;                // resolution of the duty cycle
const uint32_t FULL = 1UL << BITS;       // a 100 % duty cycle
const double CLOCK_HZ = 80e6;            // APB clock of the LEDC

// The rule of the game.
const float FREQS[N_TARGETS] = {13.0, 15.0};
const char *NAMES[N_TARGETS] = {"left", "right"};
const uint32_t PAUSE_MS = 3000;          // the chosen target stays steady
const uint32_t DEAD_MS = 1500;           // decisions ignored after the restart
const uint32_t IDENTIFY_MS = 3000;       // "Identify": 3 slow blinks, at 1 Hz

// The protocol of the API.
const char *APP_NAME = "esp32-leds";     // the name the console lists
const uint16_t ENGINE_PORT = 5010;
const uint16_t DEVICE_PORT = 5011;
const uint32_t HELLO_MS = 1000;          // one hello per second while not connected
const uint32_t ALIVE_MS = 1000;          // one "alive" per second once connected
const uint32_t SILENCE_MS = 5000;        // no news from the engine: disconnected
const uint32_t RESEND_MS = 2000;         // a command with no reply goes again (safe)
const size_t MAX_DATAGRAM = 8192;        // the engine never sends bigger

const uint8_t BOARD_LED = 2;

enum Mode : uint8_t { TARGET_OFF, TARGET_STEADY, TARGET_BLINKING };
// ANNOUNCING: no console. SETTING, STARTING: a command waits for its reply. PLAYING: the SSVEP
// runs. REFUSED: the engine refused, we wait for "Disconnect".
enum State : uint8_t { ANNOUNCING, SETTING, STARTING, PLAYING, REFUSED };

Mode mode[N_TARGETS];
float freq[N_TARGETS];                   // frequency programmed in the timer, 0 if none

#ifdef WIFI_SSID_2
const char *NETWORKS[] = {WIFI_SSID, WIFI_SSID_2};
#else
const char *NETWORKS[] = {WIFI_SSID};
#endif
const uint8_t N_NETWORKS = sizeof(NETWORKS) / sizeof(NETWORKS[0]);

WiFiMulti wifi;
bool wifiConnected = false;
int sock = -1;
char ident[6];                           // the end of the MAC address: "AB:CD"
static char received[MAX_DATAGRAM + 1];

State state = ANNOUNCING;
sockaddr_in engine;                      // the engine that connected us (outside ANNOUNCING)
char consoleHost[64] = "";               // the name of its computer, to answer "busy"
long lastSeq = 0;
uint32_t heardMs = 0, aliveMs = 0, helloMs = 0;
long nextRef = 1;
long pendingRef = 0;                     // the command waiting for its reply, 0 if none
long startRef = 0;
char command[512];
size_t commandLength = 0;
uint32_t sentMs = 0;
char phase[16] = "";
int paused = -1;                         // the steady target, -1 if none
uint32_t pauseEndMs = 0, rearmMs = 0;
uint32_t selections[N_TARGETS];
uint32_t ignored = 0;
uint32_t decisionsReceived = 0;          // all of them, -1 included: does the link carry them?
bool identifying = false;
uint32_t identifyMs = 0;

// --- The targets ---------------------------------------------------------------------------

const char *modeName(Mode m) {
  return m == TARGET_OFF ? "off" : (m == TARGET_STEADY ? "steady" : "blinking");
}

// The divider of the LEDC timer is a fixed-point number (8 fraction bits): it also gives
// non-integer frequencies, which ledc_timer_config and ledc_set_freq (in whole Hz) cannot ask
// for. ledc_timer_set is marked deprecated by IDF 5 (a warning at compile time): it is still the
// only call that takes the divider as it is.
// Returns the frequency actually programmed.
double setFrequency(uint8_t i, float f) {
  uint32_t div = (uint32_t) llround(CLOCK_HZ * 256.0 / ((double) f * FULL));
  ESP_ERROR_CHECK(ledc_timer_set(SPEED_MODE, TIMERS[i], div, BITS, LEDC_APB_CLK));
  ESP_ERROR_CHECK(ledc_timer_rst(SPEED_MODE, TIMERS[i]));
  freq[i] = f;
  return CLOCK_HZ * 256.0 / ((double) div * FULL);
}

void prepareTarget(uint8_t i) {
  ledc_timer_config_t t = {};
  t.speed_mode = SPEED_MODE;
  t.duty_resolution = (ledc_timer_bit_t) BITS;
  t.timer_num = TIMERS[i];
  t.freq_hz = 13;                        // temporary: setFrequency() sets the real value
  t.clk_cfg = LEDC_USE_APB_CLK;
  ESP_ERROR_CHECK(ledc_timer_config(&t));

  ledc_channel_config_t c = {};
  c.gpio_num = PINS[i];
  c.speed_mode = SPEED_MODE;
  c.channel = CHANNELS[i];
  c.intr_type = LEDC_INTR_DISABLE;
  c.timer_sel = TIMERS[i];
  c.duty = 0;
  c.hpoint = 0;
  ESP_ERROR_CHECK(ledc_channel_config(&c));
  gpio_set_drive_capability(PINS[i], GPIO_DRIVE_CAP_3);  // as much current as possible, ~40 mA

  mode[i] = TARGET_OFF;
  freq[i] = 0;
}

// Sending the same state again touches nothing: a blinking is never restarted for nothing.
void apply(uint8_t i, Mode m, float f) {
  bool newFreq = (m == TARGET_BLINKING && f != freq[i]);
  if (newFreq) {
    double actual = setFrequency(i, f);
    Serial.printf("target %u: %.3f Hz asked, %.5f Hz programmed\n", i, f, actual);
  }
  if (m == mode[i] && !newFreq) return;
  // The new duty cycle takes effect at the start of the next period.
  uint32_t duty = (m == TARGET_BLINKING) ? FULL / 2 : (m == TARGET_STEADY ? FULL : 0);
  ESP_ERROR_CHECK(ledc_set_duty(SPEED_MODE, CHANNELS[i], duty));
  ESP_ERROR_CHECK(ledc_update_duty(SPEED_MODE, CHANNELS[i]));
  if (m != mode[i]) Serial.printf("target %u: %s\n", i, modeName(m));
  mode[i] = m;
}

void allOff() {
  for (uint8_t i = 0; i < N_TARGETS; i++) apply(i, TARGET_OFF, 0);
}

void allBlink() {
  for (uint8_t i = 0; i < N_TARGETS; i++) apply(i, TARGET_BLINKING, FREQS[i]);
}

// --- The network ---------------------------------------------------------------------------

bool openSocket() {
  sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  if (sock < 0) return false;
  int yes = 1;
  setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &yes, sizeof(yes));
  sockaddr_in here = {};
  here.sin_family = AF_INET;
  here.sin_port = htons(DEVICE_PORT);
  here.sin_addr.s_addr = htonl(INADDR_ANY);
  if (bind(sock, (sockaddr *) &here, sizeof(here)) < 0) {
    closesocket(sock);
    sock = -1;
    return false;
  }
  return true;
}

sockaddr_in address(IPAddress ip, uint16_t port) {
  sockaddr_in a = {};
  a.sin_family = AF_INET;
  a.sin_port = htons(port);
  a.sin_addr.s_addr = (uint32_t) ip;
  return a;
}

bool sameAddress(const sockaddr_in &a, const sockaddr_in &b) {
  return a.sin_addr.s_addr == b.sin_addr.s_addr && a.sin_port == b.sin_port;
}

String addressText(const sockaddr_in &a) {
  return IPAddress(a.sin_addr.s_addr).toString() + ":" + String(ntohs(a.sin_port));
}

void sendText(const char *text, size_t n, const sockaddr_in &dest) {
  if (sendto(sock, text, n, 0, (const sockaddr *) &dest, sizeof(dest)) < 0) {
    Serial.printf("cannot send UDP to %s (error %d)\n", addressText(dest).c_str(), errno);
  }
}

// One message = one JSON object = one datagram, always with "v": 1.
void sendJson(JsonDocument &doc, const sockaddr_in &dest) {
  doc["v"] = 1;
  char text[512];
  size_t n = serializeJson(doc, text, sizeof(text));
  sendText(text, n, dest);
}

void hello() {
  JsonDocument doc;
  doc["hello"] = "EEG_API_Unicorn";
  doc["app"] = APP_NAME;
  doc["id"] = ident;
  doc["port"] = DEVICE_PORT;
#ifdef CONSOLE_IP
  IPAddress dest;
  dest.fromString(CONSOLE_IP);
#else
  IPAddress dest = WiFi.broadcastIP();
#endif
  sendJson(doc, address(dest, ENGINE_PORT));
}

// Sends a command of docs/control.md and keeps it: with no reply within 2 s, it goes again as it
// is (same ref). The engine's four commands can safely arrive twice.
void sendCommand(JsonDocument &doc) {
  doc["v"] = 1;
  pendingRef = nextRef++;
  doc["ref"] = pendingRef;
  commandLength = serializeJson(doc, command, sizeof(command));
  Serial.printf("-> engine: %s\n", command);
  sendText(command, commandLength, engine);
  sentMs = millis();
}

void setParams() {
  JsonDocument doc;
  doc["cmd"] = "set_params";
  doc["mode"] = "ssvep";
  JsonObject p = doc["params"].to<JsonObject>();
  p["targets_on"] = "physical";
  JsonArray f = p["freqs"].to<JsonArray>();
  JsonArray n = p["target_names"].to<JsonArray>();
  for (uint8_t i = 0; i < N_TARGETS; i++) {
    f.add(FREQS[i]);
    n.add(NAMES[i]);
  }
  state = SETTING;
  sendCommand(doc);
}

void startMode() {
  JsonDocument doc;
  doc["cmd"] = "start_mode";
  doc["mode"] = "ssvep";
  state = STARTING;
  sendCommand(doc);
  startRef = pendingRef;
}

void summary() {
  if (startRef == 0) return;
  Serial.printf("summary: %lu decisions received; %lu selections %s, %lu %s; %lu ignored (pause, "
                "dead time or rest)\n", (unsigned long) decisionsReceived,
                (unsigned long) selections[0], NAMES[0], (unsigned long) selections[1], NAMES[1],
                (unsigned long) ignored);
}

// The end of the connection, whatever the reason: everything goes off, we announce ourselves again.
void finish(const char *why) {
  Serial.printf("%s: everything off, announcing ourselves again\n", why);
  summary();
  allOff();
  state = ANNOUNCING;
  pendingRef = startRef = 0;
  helloMs = 0;
}

void refuse(const char *what, const char *reason) {
  Serial.printf("%s: %s\n", what, reason);
  Serial.println("targets off; in the console, \"Disconnect\" then \"Connect\" tries again");
  allOff();
  state = REFUSED;
  pendingRef = 0;
}

void connectRequest(JsonDocument &m, const sockaddr_in &src) {
  const char *host = m["host"] | "?";
  if (state != ANNOUNCING && !sameAddress(src, engine)) {
    JsonDocument r;
    r["connected"] = false;
    r["busy"] = consoleHost;
    sendJson(r, src);
    Serial.printf("\"%s\" wants to connect us, but \"%s\" already has: answered busy\n", host,
                  consoleHost);
    return;
  }
  if (state != ANNOUNCING) {
    // The same console connects us again: it had lost us. Everything starts over.
    summary();
    allOff();
  }
  engine = src;
  strlcpy(consoleHost, host, sizeof(consoleHost));
  lastSeq = 0;                           // a new connection: its seq starts again from 0
  heardMs = aliveMs = millis();
  phase[0] = 0;
  paused = -1;
  rearmMs = 0;
  memset(selections, 0, sizeof(selections));
  ignored = 0;
  decisionsReceived = 0;
  startRef = 0;
  identifying = false;
  JsonDocument r;
  r["connected"] = true;
  sendJson(r, src);
  Serial.printf("connected by the console of \"%s\" (engine %s)\n", host,
                addressText(src).c_str());
  setParams();
}

void reply(JsonDocument &m) {
  if (pendingRef == 0 || !m["ref"].is<long>() || m["ref"].as<long>() != pendingRef) return;
  pendingRef = 0;                        // a duplicate reply (after a resend) is ignored
  const char *cmd = m["cmd"] | "?";
  if (!(m["accepted"] == true)) {
    refuse(state == SETTING ? "settings refused" : "start refused", m["reason"] | "?");
    return;
  }
  Serial.printf("<- engine: %s accepted%s\n", cmd, m["already_running"] == true ?
                " (the SSVEP was already running)" : "");
  if (m["warning"].is<const char *>()) {
    Serial.printf("   engine's reservation: %s\n", m["warning"].as<const char *>());
  }
  if (state == SETTING) {
    allBlink();
    startMode();
  } else if (state == STARTING) {
    state = PLAYING;
    Serial.println("LOOK AT NO TARGET during the warm-up and the rest (~23 s)");
  }
}

void status(JsonObject s) {
  const char *newPhase = s["phase"] | "";
  if (!strcmp(newPhase, phase)) return;
  strlcpy(phase, newPhase, sizeof(phase));
  Serial.printf("engine: phase %s%s\n", phase,
                !strcmp(phase, "decoding") ? " -> your turn, look at a target" : "");
  if (s["instruction"].is<const char *>()) {
    Serial.printf("   %s\n", s["instruction"].as<const char *>());
  }
}

void decision(JsonObject d) {
  if (state != PLAYING || !(d["mode"] == "ssvep")) return;
  if (decisionsReceived++ == 0) Serial.println("first decision received from the engine");
  int target = (int) lroundf(d["target_index"] | -1.0f);
  if (target < 0) return;                // -1 = no decision, never target 0
  uint32_t now = millis();
  if (strcmp(phase, "decoding") || paused >= 0 || (int32_t) (now - rearmMs) < 0) {
    ignored++;
    return;
  }
  if (target >= N_TARGETS) {
    Serial.printf("decision for an unknown target: %d\n", target);
    return;
  }
  selections[target]++;
  paused = target;
  pauseEndMs = now + PAUSE_MS;
  Serial.printf("CHOSEN: target %d (%s, %g Hz), confidence %.2f -> steady for %lu s\n", target,
                NAMES[target], FREQS[target], d["confidence"] | 0.0f,
                (unsigned long) (PAUSE_MS / 1000));
  apply(target, TARGET_STEADY, 0);
}

void disconnection(JsonDocument &m) {
  const char *cause = m["cause"] | "";
  if (!strcmp(cause, "console")) {
    finish("disconnected in the console");
  } else if (!strcmp(cause, "engine_stopped")) {
    finish("the engine stopped (console closed?)");
  } else {
    finish("disconnected");
  }
}

void receive(const char *text, size_t n, const sockaddr_in &src) {
  JsonDocument m;
  if (deserializeJson(m, text, n)) return;             // not JSON: ignored
  if (!m.is<JsonObject>() || !m["v"].is<int>() || m["v"].as<int>() != 1) return;
  if (m["identify"] == true) {
    if (state == ANNOUNCING) {
      Serial.println("identify: the targets blink slowly, 3 times");
      identifying = true;
      identifyMs = millis();
    }
    return;
  }
  if (!m["connect"].isNull()) {
    connectRequest(m, src);
    return;
  }
  if (state == ANNOUNCING || !sameAddress(src, engine)) return;  // not OUR engine
  heardMs = millis();                    // any message from the engine is a sign of life
  if (!m["alive"].isNull()) return;
  if (m["seq"].is<long>()) {
    long seq = m["seq"].as<long>();
    if (seq <= lastSeq) return;          // older than the last one: arrived late
    lastSeq = seq;
  }
  const char *event = m["event"] | "";
  if (!strcmp(event, "disconnected")) {
    disconnection(m);
  } else if (!strcmp(event, "failed")) {
    if (m["ref"].is<long>() && m["ref"].as<long>() == startRef) {
      refuse("the engine could not start the SSVEP", m["reason"] | "?");
    }
  } else if (m["status"].is<JsonObject>()) {
    status(m["status"].as<JsonObject>());
  } else if (m["decision"].is<JsonObject>()) {
    decision(m["decision"].as<JsonObject>());
  } else if (!m["ref"].isNull()) {
    reply(m);
  }
}

void readAll() {
  for (uint8_t k = 0; k < 32; k++) {     // everything waiting, without spending the day on it
    sockaddr_in src;
    socklen_t addrLen = sizeof(src);
    // One byte more than the maximum: a datagram that is too big shows, and is ignored.
    int n = recvfrom(sock, received, sizeof(received), MSG_DONTWAIT, (sockaddr *) &src, &addrLen);
    if (n <= 0) return;
    if ((size_t) n > MAX_DATAGRAM) continue;
    receive(received, n, src);
  }
}

// --- The Wi-Fi -----------------------------------------------------------------------------

const char *securityName(wifi_auth_mode_t a) {
  switch (a) {
    case WIFI_AUTH_OPEN: return "open";
    case WIFI_AUTH_WPA_PSK: return "WPA";
    case WIFI_AUTH_WPA2_PSK: return "WPA2";
    case WIFI_AUTH_WPA_WPA2_PSK: return "WPA/WPA2";
    case WIFI_AUTH_WPA3_PSK: return "WPA3";
    case WIFI_AUTH_WPA2_WPA3_PSK: return "WPA2/WPA3";
    default: return "other";
  }
}

// Diagnosis: is each network of secrets.h visible at 2.4 GHz, on which channel, with which
// security?
void scan() {
  int n = WiFi.scanNetworks();
  for (uint8_t r = 0; r < N_NETWORKS; r++) {
    bool seen = false;
    for (int i = 0; i < n; i++) {
      if (WiFi.SSID(i) != NETWORKS[r]) continue;
      seen = true;
      Serial.printf("seen: \"%s\" channel %ld, %ld dBm, security %s, access point %s\n",
                    WiFi.SSID(i).c_str(), (long) WiFi.channel(i), (long) WiFi.RSSI(i),
                    securityName(WiFi.encryptionType(i)), WiFi.BSSIDstr(i).c_str());
    }
    if (!seen) Serial.printf("\"%s\" not visible at 2.4 GHz (%d networks seen)\n", NETWORKS[r], n);
  }
  WiFi.scanDelete();
}

void setup() {
  Serial.begin(115200);
  pinMode(BOARD_LED, OUTPUT);
  digitalWrite(BOARD_LED, LOW);
  for (uint8_t i = 0; i < N_TARGETS; i++) prepareTarget(i);

  // The reason of each disconnection: the first clue when a router refuses the ESP32.
  WiFi.onEvent([](WiFiEvent_t, WiFiEventInfo_t info) {
    Serial.printf("Wi-Fi refused or lost, reason %u\n", info.wifi_sta_disconnected.reason);
  }, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                  // no power saving: a message goes through at once
  // Read from the eFuses: WiFi.macAddress() returns zeros until the station has started.
  uint8_t mac[6];
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  snprintf(ident, sizeof(ident), "%02X:%02X", mac[4], mac[5]);
  scan();
  wifi.addAP(WIFI_SSID, WIFI_PASS);
#ifdef WIFI_SSID_2
  wifi.addAP(WIFI_SSID_2, WIFI_PASS_2);
#endif
  Serial.printf("\nesp32_leds: \"%s\", identifier %s; connecting to one of the %u networks of "
                "secrets.h...\n", APP_NAME, ident, N_NETWORKS);
}

void loop() {
  // Connected, run() returns at once; otherwise it searches and connects (up to 5 s).
  bool now = wifi.run(5000) == WL_CONNECTED;
  if (now != wifiConnected) {
    wifiConnected = now;
    if (wifiConnected) {
      Serial.printf("Wi-Fi connected to \"%s\": ip %s, gateway %s, signal %d dBm\n",
                    WiFi.SSID().c_str(), WiFi.localIP().toString().c_str(),
                    WiFi.gatewayIP().toString().c_str(), WiFi.RSSI());
      if (sock < 0 && !openSocket()) Serial.printf("cannot open UDP port %u\n", DEVICE_PORT);
      if (state == ANNOUNCING) {
        Serial.printf("announcing every second: in the console, \"Connect an application\", "
                      "pick \"%s\" (%s), then \"Connect\"\n", APP_NAME, ident);
      }
    } else {
      Serial.println("Wi-Fi lost, reconnecting...");
    }
  }

  uint32_t t = millis();
  if (wifiConnected && sock >= 0) {
    readAll();
    t = millis();
    if (state == ANNOUNCING) {
      if (helloMs == 0 || t - helloMs >= HELLO_MS) {
        helloMs = t;
        hello();
      }
    } else {
      if (t - aliveMs >= ALIVE_MS) {
        aliveMs = t;
        JsonDocument alive;
        alive["alive"] = true;
        sendJson(alive, engine);
      }
      if (pendingRef != 0 && t - sentMs >= RESEND_MS) {
        Serial.println("   no reply within 2 s: command or reply lost, sending again");
        sendText(command, commandLength, engine);
        sentMs = t;
      }
    }
  }
  // Wi-Fi lost included: 5 s without news, the connection is over.
  if (state != ANNOUNCING && t - heardMs >= SILENCE_MS) finish("5 s without news from the engine");

  if (state == PLAYING && paused >= 0 && (int32_t) (t - pauseEndMs) >= 0) {
    paused = -1;
    rearmMs = t + DEAD_MS;
    allBlink();
    Serial.printf("restart: both targets blink, decisions still ignored for %lu ms\n",
                  (unsigned long) DEAD_MS);
  }

  if (identifying) {
    uint32_t d = t - identifyMs;
    if (state != ANNOUNCING || d >= IDENTIFY_MS) {
      identifying = false;
      if (state == ANNOUNCING) allOff();
    } else {
      for (uint8_t i = 0; i < N_TARGETS; i++) apply(i, d % 1000 < 500 ? TARGET_STEADY : TARGET_OFF, 0);
    }
  }

  bool blue;
  if (state == ANNOUNCING) blue = identifying && (t - identifyMs) % 1000 < 500;
  else if (state == REFUSED) blue = t % 1000 < 500;
  else blue = true;
  digitalWrite(BOARD_LED, blue ? HIGH : LOW);
  delay(2);
}
