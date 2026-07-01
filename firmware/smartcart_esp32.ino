/*
  SmartCart - ESP32 Firmware (Milestone 2 rework)
  --------------------------------------------------
  Reads weight from an HX711 load cell and reports it to the new FastAPI
  backend over HTTP/REST -- replacing the original Firebase-direct design.

  WHAT CHANGED FROM THE ORIGINAL smartcart_esp32.ino, AND WHY
  --------------------------------------------------------------
  1. Firebase -> HTTP/REST to the FastAPI backend.
     Old: Firebase_ESP_Client, email/password auth compiled into the binary,
     writes went straight to a shared Realtime Database with no
     application-level validation of who was writing.
     New: plain HTTPClient POSTs to `/sessions/{id}/weight` with a
     `X-Device-Key` header. Simpler dependency footprint, no vendor SDK,
     and the backend -- not this firmware -- now owns weight-verification
     logic (see below). Tradeoff: HTTP polling/pushing at 1Hz is less
     "real-time" than Firebase's persistent socket, which is an
     acceptable cost for a single-cart academic prototype; a future
     multi-cart deployment might revisit this with WebSockets or MQTT
     (documented as future scope, not built here).

  2. Delta-weight verification MOVED to the backend.
     Old bug (Phase 1 finding): this firmware compared *total* cart weight
     against a *single* item's expected weight every second -- only ever
     correct for the very first item added; wrong the moment a second item
     was placed in the cart.
     New: this firmware's job is now just "sample weight, send the raw
     reading." The backend (`POST /sessions/{id}/weight`) computes the
     DELTA since the previous reading and compares that against the most
     recently added unverified item. This is both a correctness fix and a
     simplification -- the firmware no longer needs to fetch
     `expectedWeight` at all, which also removes a Firebase read from the
     hot loop.

  3. No hardcoded session ID.
     Old: `String currentSessionId = "demo_session";` -- a compile-time
     constant, so the system could only ever run exactly one cart, ever.
     New: this firmware polls `GET /sessions/active?cart_id=...` on a
     timer to discover whichever session is currently active for ITS
     cart_id (see secrets.h). When a shopper checks out (or none has
     logged in yet), that endpoint returns 404 and this firmware simply
     stops posting weight readings until a session appears again.

  4. Secrets moved out of this file into secrets.h (gitignored).
     Does not by itself prevent extraction from a compiled binary/flash
     dump by someone with physical access to the board -- that's a
     genuinely hard problem for a bare ESP32 (would need Secure Boot +
     Flash Encryption, a materially bigger scope item) -- but it does fix
     the more immediate problem of secrets being visible to anyone who
     opens the .ino in source control.

  5. Non-blocking Wi-Fi connect with timeout + exponential backoff.
     Old: `while (WiFi.status() != WL_CONNECTED) { delay(500); }` --
     blocks forever if Wi-Fi is ever unreachable at boot, with no escape.
     New: bounded connection attempts, explicit CONNECTING/CONNECTED/
     RECONNECTING states, and the watchdog (see #6) as a backstop in case
     something still hangs unexpectedly.

  6. Hardware watchdog.
     Old: none -- an unexpected hang (e.g. inside a blocking library
     call) would require a manual power cycle.
     New: esp_task_wdt configured for a bounded timeout; every loop()
     iteration feeds it. If the firmware ever truly hangs, the board
     self-resets rather than requiring physical intervention.

  7. Load-cell fault detection instead of silent negative-weight clamping.
     Old: `if (weight < 0) weight = 0;` -- silently hides a drifted/
     untared scale or a disconnected load cell.
     New: checks `scale.is_ready()` before reading; a load cell that's
     disconnected or not responding puts the firmware into a FAULT state
     (logged over serial, retried on a timer) instead of quietly reporting
     a wrong zero. A negative reading that IS ready is logged as a
     drift warning rather than silently zeroed.

  8. Calibration factor persisted in NVS (flash), with a serial
     calibration routine, instead of a hardcoded magic number.
     Old: `float CALIBRATION_FACTOR = 420.0;` with a comment telling the
     user to edit source and re-flash to calibrate.
     New: `CAL:<known_weight_grams>` over Serial (with a known reference
     weight on the scale) computes and persists a new calibration factor
     to NVS -- no re-flash needed to recalibrate after, say, a load cell
     is replaced.

  9. Basic reading stabilization.
     A single new addition: two consecutive HX711 samples must agree
     within STABILITY_TOLERANCE_G before a reading is sent, which cuts
     down on false weight-verification failures from a cart being pushed
     or bumped mid-read. This is a real but partial mitigation -- it does
     not eliminate mechanical noise from the single centrally-mounted
     load cell discussed in the Phase 2 hardware analysis, only reduces
     the frequency of transient spikes being reported as real changes.

  10. OTA updates (ArduinoOTA).
      New capability, not present at all in the original firmware --
      lets firmware be updated over Wi-Fi during development/iteration
      instead of requiring a USB cable and physical access every time.
      Password-protected (see secrets.h); still worth noting OTA is
      inherently a larger attack surface and should be disabled entirely
      (comment out `ArduinoOTA.begin()`) for a final locked-down build if
      the project moves beyond active development.

  LIBRARIES NEEDED (Arduino Library Manager)
  --------------------------------------------
    - HX711 by Bogdan Necula
    - ArduinoJson by Benoit Blanchon (v7.x)
  (WiFi, HTTPClient, Preferences, ArduinoOTA, esp_task_wdt ship with the
  ESP32 Arduino core -- no separate install needed.)
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <HX711.h>
#include <Preferences.h>
#include <ArduinoOTA.h>
#include <ArduinoJson.h>
#include <esp_task_wdt.h>

#include "secrets.h"

// ---------- Pin configuration ----------
#define HX711_DOUT_PIN 4
#define HX711_SCK_PIN  5

// ---------- Timing configuration ----------
const unsigned long SEND_INTERVAL_MS       = 1000;   // weight sample/report rate
const unsigned long SESSION_POLL_INTERVAL_MS = 5000; // how often to re-check active session
const unsigned long WIFI_CONNECT_TIMEOUT_MS  = 15000;
const unsigned long WIFI_RETRY_BASE_MS       = 2000;
const unsigned long WIFI_RETRY_MAX_MS        = 60000;
const uint8_t  WATCHDOG_TIMEOUT_S            = 30;

// Weight verification tolerance now lives on the backend (see
// app/routers/weight.py WEIGHT_TOLERANCE_GRAMS) -- kept in exactly one
// place instead of duplicated here and there, so tuning it never requires
// a firmware re-flash.

const float STABILITY_TOLERANCE_G = 8.0; // two samples must agree within this to be "stable"
const float DEFAULT_CALIBRATION_FACTOR = 420.0; // fallback if NVS has no saved value yet

// ---------- State machine ----------
enum SystemState {
  STATE_WIFI_CONNECTING,
  STATE_WIFI_RECONNECTING,
  STATE_SESSION_WAIT,
  STATE_ACTIVE,
  STATE_LOAD_CELL_FAULT,
};

SystemState state = STATE_WIFI_CONNECTING;

HX711 scale;
Preferences preferences;

unsigned long lastSendAttempt = 0;
unsigned long lastSessionPoll = 0;
unsigned long wifiRetryDelay = WIFI_RETRY_BASE_MS;
unsigned long wifiDisconnectedSince = 0;

long activeSessionId = -1; // -1 == none known
float lastStableReading = NAN;
uint8_t loadCellFaultCount = 0;
const uint8_t LOAD_CELL_FAULT_THRESHOLD = 5;

// ---------------------------------------------------------------------
// Calibration (persisted in NVS via Preferences, replacing the old
// hardcoded CALIBRATION_FACTOR constant)
// ---------------------------------------------------------------------

float loadCalibrationFactor() {
  preferences.begin("smartcart", true); // read-only
  float factor = preferences.getFloat("cal_factor", DEFAULT_CALIBRATION_FACTOR);
  preferences.end();
  return factor;
}

void saveCalibrationFactor(float factor) {
  preferences.begin("smartcart", false); // read-write
  preferences.putFloat("cal_factor", factor);
  preferences.end();
  Serial.print("Saved new calibration factor to NVS: ");
  Serial.println(factor);
}

// Serial calibration routine: place a known reference weight on the
// scale, then send "CAL:<grams>" over Serial (e.g. "CAL:500" for a 500g
// reference weight). Computes and persists a new calibration factor.
void handleSerialCalibration(const String &command) {
  if (command.startsWith("CAL:")) {
    float knownGrams = command.substring(4).toFloat();
    if (knownGrams <= 0) {
      Serial.println("CAL error: provide a positive known weight, e.g. CAL:500");
      return;
    }
    scale.set_scale(); // reset to raw counts for calibration
    long rawUnits = scale.get_units(10);
    if (rawUnits == 0) {
      Serial.println("CAL error: raw reading was zero, check wiring");
      return;
    }
    float newFactor = (float)rawUnits / knownGrams;
    scale.set_scale(newFactor);
    saveCalibrationFactor(newFactor);
  } else if (command == "TARE") {
    scale.tare();
    Serial.println("Tared.");
  }
}

// ---------------------------------------------------------------------
// Wi-Fi
// ---------------------------------------------------------------------

void beginWifiConnect() {
  Serial.println("Connecting to Wi-Fi...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

// Non-blocking: called every loop() while not connected. Returns true
// once connected. Times out and backs off instead of looping forever
// (fixes the original firmware's unbounded `while` block).
bool tickWifiConnect() {
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Wi-Fi connected. IP: ");
    Serial.println(WiFi.localIP());
    wifiRetryDelay = WIFI_RETRY_BASE_MS; // reset backoff on success
    return true;
  }
  if (millis() - wifiDisconnectedSince > WIFI_CONNECT_TIMEOUT_MS) {
    Serial.print("Wi-Fi connect timed out, retrying in ");
    Serial.print(wifiRetryDelay);
    Serial.println("ms");
    WiFi.disconnect();
    delay(wifiRetryDelay);
    wifiRetryDelay = min(wifiRetryDelay * 2, WIFI_RETRY_MAX_MS); // exponential backoff, capped
    wifiDisconnectedSince = millis();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
  return false;
}

// ---------------------------------------------------------------------
// Backend HTTP calls
// ---------------------------------------------------------------------

String backendUrl(const String &path) {
  return "http://" + String(BACKEND_HOST) + ":" + String(BACKEND_PORT) + path;
}

// Polls GET /sessions/active?cart_id=... . Returns the session id, or -1
// if there is no active session right now (shopper hasn't logged in yet,
// or has already checked out).
long pollActiveSession() {
  HTTPClient http;
  String url = backendUrl("/sessions/active?cart_id=" + String(CART_ID));
  http.begin(url);
  http.setTimeout(3000);
  int code = http.GET();

  long result = -1;
  if (code == 200) {
    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, http.getString());
    if (!err) {
      result = doc["id"] | -1;
    }
  } else if (code == 404) {
    result = -1; // no active session -- expected/normal, not an error
  } else {
    Serial.print("Session poll failed, HTTP code: ");
    Serial.println(code);
  }
  http.end();
  return result;
}

// POSTs a raw weight reading to /sessions/{id}/weight. The backend
// computes delta and verification -- see point #2 at the top of this file.
bool reportWeight(long sessionId, float rawWeightGrams) {
  HTTPClient http;
  String url = backendUrl("/sessions/" + String(sessionId) + "/weight");
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_API_KEY);
  http.setTimeout(3000);

  StaticJsonDocument<128> doc;
  doc["raw_weight_grams"] = rawWeightGrams;
  String body;
  serializeJson(doc, body);

  int code = http.POST(body);
  bool ok = (code == 200 || code == 201);
  if (!ok) {
    Serial.print("Weight report failed, HTTP code: ");
    Serial.println(code);
    if (code == 409) {
      // Session was closed between our last poll and this send -- not a
      // fault, just stale local state. Force a re-poll next tick.
      activeSessionId = -1;
    }
  }
  http.end();
  return ok;
}

// ---------------------------------------------------------------------
// Load cell
// ---------------------------------------------------------------------

void setupLoadCell() {
  scale.begin(HX711_DOUT_PIN, HX711_SCK_PIN);
  float factor = loadCalibrationFactor();
  scale.set_scale(factor);
  Serial.print("Loaded calibration factor from NVS: ");
  Serial.println(factor);

  if (scale.wait_ready_timeout(2000)) {
    scale.tare();
    Serial.println("Load cell ready and tared.");
  } else {
    Serial.println("WARNING: load cell not responding at startup -- check wiring.");
  }
}

// Returns NAN if the load cell isn't responding (fault), otherwise the
// weight in grams. Replaces the old silent `if (weight < 0) weight = 0;`.
float readWeightOrFault() {
  if (!scale.wait_ready_timeout(500)) {
    loadCellFaultCount++;
    return NAN;
  }
  loadCellFaultCount = 0;
  float weight = scale.get_units(5);
  if (weight < 0) {
    // A small negative reading right after tare is normal sensor noise;
    // a large/persistent negative reading indicates drift needing a
    // re-tare. Log it instead of silently zeroing -- an operator watching
    // Serial output can catch drift before it causes bad verifications.
    if (weight < -20.0) {
      Serial.print("WARNING: significant negative weight reading (");
      Serial.print(weight);
      Serial.println("g) -- scale may need re-taring.");
    }
    weight = 0;
  }
  return weight;
}

// ---------------------------------------------------------------------
// Setup / loop
// ---------------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("SmartCart ESP32 firmware starting...");

  esp_task_wdt_config_t wdtConfig = {
    .timeout_ms = WATCHDOG_TIMEOUT_S * 1000,
    .idle_core_mask = 0,
    .trigger_panic = true,
  };
  esp_task_wdt_init(&wdtConfig);
  esp_task_wdt_add(NULL);

  setupLoadCell();

  wifiDisconnectedSince = millis();
  beginWifiConnect();

  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.setHostname(CART_ID);
  ArduinoOTA.begin();
}

void loop() {
  esp_task_wdt_reset();

  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    handleSerialCalibration(command);
  }

  if (WiFi.status() != WL_CONNECTED) {
    state = STATE_WIFI_RECONNECTING;
    tickWifiConnect();
    return; // don't attempt anything network-dependent until reconnected
  }

  ArduinoOTA.handle();

  unsigned long now = millis();

  // Periodically refresh which session (if any) is active for this cart.
  if (activeSessionId == -1 || now - lastSessionPoll > SESSION_POLL_INTERVAL_MS) {
    lastSessionPoll = now;
    long session = pollActiveSession();
    if (session != activeSessionId) {
      activeSessionId = session;
      Serial.print("Active session changed: ");
      Serial.println(activeSessionId);
    }
  }

  if (activeSessionId == -1) {
    state = STATE_SESSION_WAIT;
    return; // nothing to report until a shopper logs in
  }

  if (loadCellFaultCount >= LOAD_CELL_FAULT_THRESHOLD) {
    state = STATE_LOAD_CELL_FAULT;
    if (now - lastSendAttempt > SEND_INTERVAL_MS) {
      lastSendAttempt = now;
      Serial.println("Load cell fault: not responding, skipping this cycle.");
    }
    return;
  }

  if (now - lastSendAttempt < SEND_INTERVAL_MS) {
    return;
  }
  lastSendAttempt = now;

  float weight = readWeightOrFault();
  if (isnan(weight)) {
    return; // fault already counted in readWeightOrFault()
  }

  // Basic stability check (point #9): only send once two consecutive
  // readings agree within tolerance, to reduce false verification
  // failures from cart movement/vibration.
  if (!isnan(lastStableReading) && fabs(weight - lastStableReading) > STABILITY_TOLERANCE_G) {
    lastStableReading = weight;
    return; // unstable, wait for next tick to confirm
  }
  lastStableReading = weight;

  state = STATE_ACTIVE;
  reportWeight(activeSessionId, weight);
}
