// esp32_client: an ESP32 connected to the EEG_API_Unicorn console over Wi-Fi, with no computer in
// between. The settings are in config.h; the protocol is in EegApiDevice (do not edit it).
//
// SSVEP (MODE "ssvep"): the LEDs are the targets. They blink from the moment the settings are
// accepted, at the frequencies of config.h, done in hardware by the ESP32's LEDC peripheral:
// neither the Wi-Fi nor the code can shift them. At each decision, the chosen target turns STEADY
// for HOLD_MS while the others keep blinking, then the game starts again.
// MI (MODE "mi"): the LED of the decoded task lights up. A mode with a model waits for the model
// to be chosen in the console ("Start decoding").
// Neuro (MODE "neuro"): the values go to the serial monitor (115200 bauds).
//
// In the console: "Connect an application", pick APP_NAME (shown with its identifier), then
// "Connect". "Identify" blinks the LEDs slowly, 3 times. "Disconnect", the console closed or 5 s
// without news: everything goes off and the device announces itself again.
//
// To do something else with the decisions, change onDecision() below: the rest stays as it is.
// Library: ArduinoJson 7. Board: ESP32 (compiled for the ESP32 DevKit V1).

#include <WiFi.h>
#include <WiFiMulti.h>
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "config.h"
#include "EegApiDevice.h"

const uint8_t PINS[] = TARGET_PINS;
const float FREQS[] = TARGET_FREQS;
const char *NAMES[] = TARGET_NAMES;
const uint8_t N_TARGETS = sizeof(PINS) / sizeof(PINS[0]);
static_assert(N_TARGETS <= 4, "one LEDC timer per target, and 4 timers: 4 targets at most");
static_assert(sizeof(FREQS) / sizeof(FREQS[0]) == N_TARGETS, "one frequency per pin in config.h");
static_assert(sizeof(NAMES) / sizeof(NAMES[0]) == N_TARGETS, "one name per pin in config.h");

const bool SSVEP = !strcmp(MODE, "ssvep");
const uint32_t IDENTIFY_MS = 3000;       // "Identify": 3 slow blinks, at 1 Hz

EegApiDevice eeg;
WiFiMulti wifi;
bool wifiConnected = false;
char settings[512];

// --- The LEDs -------------------------------------------------------------------------------

enum Look : uint8_t { OFF, STEADY, BLINKING };
#if SOC_LEDC_SUPPORT_HS_MODE
const ledc_mode_t SPEED_MODE = LEDC_HIGH_SPEED_MODE;
#else
const ledc_mode_t SPEED_MODE = LEDC_LOW_SPEED_MODE;   // ESP32-S2, S3, C3...: no high-speed mode
#endif
const uint32_t BITS = 14;                // resolution of the duty cycle
const uint32_t FULL = 1UL << BITS;       // a 100 % duty cycle
const double CLOCK_HZ = 80e6;            // APB clock of the LEDC
Look look[4];
float programmed[4];                     // frequency programmed in the timer, 0 if none

ledc_timer_t timerOf(uint8_t i) { return (ledc_timer_t) i; }   // one timer per target

// The divider of the LEDC timer is a fixed-point number (8 fraction bits): it also gives
// non-integer frequencies, which ledc_timer_config and ledc_set_freq (in whole Hz) cannot ask for.
// ledc_timer_set is marked deprecated by IDF 5 (a warning at compile time): it is still the only
// call that takes the divider as it is.
double setFrequency(uint8_t i, float f) {
  uint32_t div = (uint32_t) llround(CLOCK_HZ * 256.0 / ((double) f * FULL));
  ESP_ERROR_CHECK(ledc_timer_set(SPEED_MODE, timerOf(i), div, BITS, LEDC_APB_CLK));
  ESP_ERROR_CHECK(ledc_timer_rst(SPEED_MODE, timerOf(i)));
  programmed[i] = f;
  return CLOCK_HZ * 256.0 / ((double) div * FULL);
}

void prepareLed(uint8_t i) {
  ledc_timer_config_t t = {};
  t.speed_mode = SPEED_MODE;
  t.duty_resolution = (ledc_timer_bit_t) BITS;
  t.timer_num = timerOf(i);
  t.freq_hz = 13;                        // temporary: setFrequency() sets the real value
  t.clk_cfg = LEDC_USE_APB_CLK;
  ESP_ERROR_CHECK(ledc_timer_config(&t));
  ledc_channel_config_t c = {};
  c.gpio_num = PINS[i];
  c.speed_mode = SPEED_MODE;
  c.channel = (ledc_channel_t) i;
  c.intr_type = LEDC_INTR_DISABLE;
  c.timer_sel = timerOf(i);
  c.duty = 0;
  c.hpoint = 0;
  ESP_ERROR_CHECK(ledc_channel_config(&c));
  gpio_set_drive_capability((gpio_num_t) PINS[i], GPIO_DRIVE_CAP_3);  // as much current as possible
  look[i] = OFF;
  programmed[i] = 0;
}

// Sending the same state again touches nothing: a blinking is never restarted for nothing.
void show(uint8_t i, Look l) {
  bool newFreq = (l == BLINKING && FREQS[i] != programmed[i]);
  if (newFreq) {
    double actual = setFrequency(i, FREQS[i]);
    Serial.printf("target %u: %.3f Hz asked, %.5f Hz programmed\n", i, FREQS[i], actual);
  }
  if (l == look[i] && !newFreq) return;
  uint32_t duty = l == BLINKING ? FULL / 2 : (l == STEADY ? FULL : 0);
  ESP_ERROR_CHECK(ledc_set_duty(SPEED_MODE, (ledc_channel_t) i, duty));
  ESP_ERROR_CHECK(ledc_update_duty(SPEED_MODE, (ledc_channel_t) i));
  look[i] = l;
}

void showAll(Look l) {
  for (uint8_t i = 0; i < N_TARGETS; i++) show(i, l);
}

// --- What the decisions do ------------------------------------------------------------------

int held = -1;                           // SSVEP: the steady target, -1 if none
uint32_t holdEndMs = 0, rearmMs = 0;
uint32_t identifyMs = 0;
bool identifying = false;
bool refused = false;

// A decision: the channels of the mode's decoded stream, by name. Every value is a number; -1
// means "no decision", never target 0.
void onDecision(JsonObject d) {
  if (!strcmp(MODE, "neuro")) {
    Serial.printf("neuro: charge %.2f, somnolence %.2f, engagement %.2f%s\n", d["charge"] | 0.0f,
                  d["somnolence"] | 0.0f, d["engagement"] | 0.0f,
                  (d["artifact"] | 0.0f) > 0.5f ? " (artifact: last valid values)" : "");
    return;
  }
  int index = (int) lroundf(d["target_index"] | (d["intent_index"] | -1.0f));
  if (!SSVEP) {                          // MI: the LED of the decoded task, the others off
    for (uint8_t i = 0; i < N_TARGETS; i++) show(i, (int) i == index ? STEADY : OFF);
    return;
  }
  // SSVEP: only while decoding (the rest is over), out of the pause and of the dead time.
  if (index < 0 || strcmp(eeg.phase(), "decoding") || held >= 0 || (int32_t) (millis() - rearmMs) < 0) {
    return;
  }
  if (index >= N_TARGETS) return;
  held = index;
  holdEndMs = millis() + HOLD_MS;
  Serial.printf("CHOSEN: target %d (%s, %g Hz), confidence %.2f\n", index, NAMES[index],
                FREQS[index], d["confidence"] | 0.0f);
  show(index, STEADY);
}

void onSettingsAccepted() {
  refused = false;
  if (SSVEP) showAll(BLINKING);          // from now on: the engine measures its rest with them
}

void onDisconnected() {
  held = -1;
  refused = false;
  showAll(OFF);
}

void onRefused(const char *) {
  refused = true;
  showAll(OFF);
}

void onIdentify() {
  identifying = true;
  identifyMs = millis();
}

// --- setup and loop -------------------------------------------------------------------------

// The settings sent to the engine: EXTRA_SETTINGS, plus the targets for SSVEP.
void buildSettings() {
  JsonDocument doc;
  deserializeJson(doc, EXTRA_SETTINGS);
  if (!doc.is<JsonObject>()) doc.to<JsonObject>();
  if (SSVEP) {
    doc["targets_on"] = "physical";
    JsonArray f = doc["freqs"].to<JsonArray>();
    JsonArray n = doc["target_names"].to<JsonArray>();
    for (uint8_t i = 0; i < N_TARGETS; i++) {
      f.add(FREQS[i]);
      n.add(NAMES[i]);
    }
  }
  serializeJson(doc, settings, sizeof(settings));
}

void setup() {
  Serial.begin(115200);
  if (STATUS_LED >= 0) pinMode(STATUS_LED, OUTPUT);
  for (uint8_t i = 0; i < N_TARGETS; i++) prepareLed(i);
  buildSettings();

  // The reason of each disconnection: the first clue when a router refuses the ESP32.
  WiFi.onEvent([](WiFiEvent_t, WiFiEventInfo_t info) {
    Serial.printf("Wi-Fi refused or lost, reason %u\n", info.wifi_sta_disconnected.reason);
  }, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                  // no power saving: a message goes through at once
  wifi.addAP(WIFI_SSID, WIFI_PASS);
#ifdef WIFI_SSID_2
  wifi.addAP(WIFI_SSID_2, WIFI_PASS_2);
#endif

  eeg.onDecision(onDecision);
  eeg.onSettingsAccepted(onSettingsAccepted);
  eeg.onDisconnected(onDisconnected);
  eeg.onRefused(onRefused);
  eeg.onIdentify(onIdentify);
  Serial.printf("\n%s: mode %s, %u LED(s); connecting to the Wi-Fi...\n", APP_NAME, MODE, N_TARGETS);
}

void loop() {
  // Connected, run() returns at once; otherwise it searches and connects (up to 5 s).
  bool now = wifi.run(5000) == WL_CONNECTED;
  if (now != wifiConnected) {
    wifiConnected = now;
    if (now) {
      Serial.printf("Wi-Fi connected to \"%s\": ip %s, signal %d dBm\n", WiFi.SSID().c_str(),
                    WiFi.localIP().toString().c_str(), WiFi.RSSI());
      eeg.begin({APP_NAME, DEVICE_ID, DEVICE_PORT, CONSOLE_IP, ENGINE_PORT, MODE, settings});
      if (!eeg.connected()) {
        Serial.printf("announcing every second: in the console, \"Connect an application\", pick "
                      "\"%s\" (%s), then \"Connect\"\n", APP_NAME, eeg.id());
      }
    } else {
      Serial.println("Wi-Fi lost, reconnecting...");
    }
  }
  eeg.loop();

  uint32_t t = millis();
  if (held >= 0 && (int32_t) (t - holdEndMs) >= 0) {   // the pause is over: all blink again
    held = -1;
    rearmMs = t + REARM_MS;
    showAll(BLINKING);
  }
  if (identifying) {
    uint32_t d = t - identifyMs;
    if (eeg.connected() || d >= IDENTIFY_MS) {
      identifying = false;
      if (!eeg.connected()) showAll(OFF);
    } else {
      showAll(d % 1000 < 500 ? STEADY : OFF);
    }
  }
  if (STATUS_LED >= 0) {
    bool on = refused ? t % 1000 < 500 : eeg.connected();
    digitalWrite(STATUS_LED, on ? HIGH : LOW);
  }
  delay(2);
}
