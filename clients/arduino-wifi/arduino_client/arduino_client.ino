// arduino_client: an Arduino UNO R4 WiFi connected to the EEG_API_Unicorn console over Wi-Fi,
// with no computer in between. The settings are in config.h; the protocol is in EegApiDevice (do
// not edit it).
//
// MI (MODE "mi"): the LED of the decoded task lights up, the others go off; none while the
// decoder is not sure (-1). The Motor Imagery needs a trained model: once this device is
// connected, choose the model in the console, then "Start decoding".
// Neuro (MODE "neuro"): the values go to the serial monitor (115200 bauds).
//
// In the console: "Connect an application", pick APP_NAME (shown with its identifier), then
// "Connect". "Identify" blinks the LEDs slowly, 3 times. "Disconnect", the console closed or 5 s
// without news: everything goes off and the device announces itself again.
//
// To do something else with the decisions, change onDecision() below: the rest stays as it is.
// Library: ArduinoJson 7. Board: Arduino UNO R4 WiFi.

#include <WiFiS3.h>
#include "config.h"
#include "EegApiDevice.h"

const uint8_t PINS[] = TASK_PINS;
const uint8_t N_TASKS = sizeof(PINS) / sizeof(PINS[0]);
const uint32_t IDENTIFY_MS = 3000;       // "Identify": 3 slow blinks, at 1 Hz
const uint32_t WIFI_RETRY_MS = 10000;

EegApiDevice eeg;
bool refused = false, identifying = false;
uint32_t identifyMs = 0, wifiTryMs = 0;
int lastIndex = -2;

void say(const char *format, ...) {
  char line[160];
  va_list args;
  va_start(args, format);
  vsnprintf(line, sizeof(line), format, args);
  va_end(args);
  Serial.println(line);
}

void showOnly(int index) {
  for (uint8_t i = 0; i < N_TASKS; i++) digitalWrite(PINS[i], (int) i == index ? HIGH : LOW);
}

// A decision: the channels of the mode's decoded stream, by name. Every value is a number; -1
// means "no decision", never task 0.
void onDecision(JsonObject d) {
  if (!strcmp(MODE, "neuro")) {
    // printf on this board does not format floats: the values are written with print().
    Serial.print("neuro: charge ");
    Serial.print(d["charge"] | 0.0f, 2);
    Serial.print(", somnolence ");
    Serial.print(d["somnolence"] | 0.0f, 2);
    Serial.print(", engagement ");
    Serial.print(d["engagement"] | 0.0f, 2);
    Serial.println((d["artifact"] | 0.0f) > 0.5f ? " (artifact: last valid values)" : "");
    return;
  }
  int index = (int) lroundf(d["intent_index"] | (d["target_index"] | -1.0f));
  if (index >= N_TASKS) index = -1;      // more tasks in the model than LEDs: not shown
  if (index != lastIndex) {
    lastIndex = index;
    if (index < 0) say("decoded: none (-1)");
    else say("decoded: task %d", index);
  }
  showOnly(index);
}

void onDisconnected() {
  refused = false;
  lastIndex = -2;
  showOnly(-1);
}

void onSettingsAccepted() { refused = false; }

void onRefused(const char *) {
  refused = true;
  showOnly(-1);
}

void onIdentify() {
  identifying = true;
  identifyMs = millis();
}

void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < N_TASKS; i++) pinMode(PINS[i], OUTPUT);
  showOnly(-1);
  if (STATUS_LED >= 0) pinMode(STATUS_LED, OUTPUT);
  if (WiFi.status() == WL_NO_MODULE) say("no Wi-Fi module: is this an UNO R4 WiFi?");
  eeg.onDecision(onDecision);
  eeg.onSettingsAccepted(onSettingsAccepted);
  eeg.onDisconnected(onDisconnected);
  eeg.onRefused(onRefused);
  eeg.onIdentify(onIdentify);
  say("%s: mode %s, %u LED(s); connecting to the Wi-Fi...", APP_NAME, MODE, N_TASKS);
}

void loop() {
  uint32_t t = millis();
  if (WiFi.status() != WL_CONNECTED) {
    if (wifiTryMs == 0 || t - wifiTryMs >= WIFI_RETRY_MS) {
      wifiTryMs = t;
      WiFi.begin(WIFI_SSID, WIFI_PASS);  // waits until connected or refused (a few seconds)
      if (WiFi.status() == WL_CONNECTED) {
        // The address can be 0.0.0.0 for a moment after the connection.
        for (uint8_t k = 0; k < 20 && WiFi.localIP() == IPAddress(0, 0, 0, 0); k++) delay(100);
        say("Wi-Fi connected to \"%s\": ip %s", WIFI_SSID, WiFi.localIP().toString().c_str());
        // Again after each reconnection: the UDP socket lives in the Wi-Fi module.
        eeg.begin({APP_NAME, DEVICE_ID, DEVICE_PORT, CONSOLE_IP, ENGINE_PORT, MODE, SETTINGS});
        if (!eeg.connected()) {
          say("announcing every second: in the console, \"Connect an application\", pick "
              "\"%s\" (%s), then \"Connect\"", APP_NAME, eeg.id());
        }
      } else {
        say("Wi-Fi \"%s\" not joined, trying again in %lu s", WIFI_SSID,
            (unsigned long) (WIFI_RETRY_MS / 1000));
      }
    }
  }
  eeg.loop();

  t = millis();
  if (identifying) {
    uint32_t d = t - identifyMs;
    if (eeg.connected() || d >= IDENTIFY_MS) {
      identifying = false;
      if (!eeg.connected()) showOnly(-1);
    } else {
      for (uint8_t i = 0; i < N_TASKS; i++) digitalWrite(PINS[i], d % 1000 < 500 ? HIGH : LOW);
    }
  }
  if (STATUS_LED >= 0) {
    bool on = refused ? t % 1000 < 500 : eeg.connected();
    digitalWrite(STATUS_LED, on ? HIGH : LOW);
  }
}
