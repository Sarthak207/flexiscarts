# SmartCart ESP32 Firmware (Milestone 2)

Reads the 50kg load cell via HX711 and reports weight to the FastAPI
backend over HTTP — no Firebase dependency.

## Setup

1. Install libraries via Arduino Library Manager:
   - **HX711** by Bogdan Necula
   - **ArduinoJson** by Benoit Blanchon (v7.x)
   - (WiFi, HTTPClient, Preferences, ArduinoOTA, esp_task_wdt ship with the ESP32 board package — install the "esp32 by Espressif Systems" board package if you haven't already.)

2. Copy `secrets.h.example` to `secrets.h` and fill in:
   - Your Wi-Fi SSID/password
   - `BACKEND_HOST` — the Raspberry Pi 4's LAN IP (set a static DHCP reservation for it so this doesn't need updating later)
   - `DEVICE_API_KEY` — must exactly match `DEVICE_API_KEY` in the backend's `.env`
   - `CART_ID` — must match the `cart_id` the touchscreen UI uses when calling `POST /sessions/start`

   `secrets.h` is gitignored — never commit it.

3. Wire the HX711: `DOUT` → GPIO4, `SCK` → GPIO5 (adjust the `#define`s at the top of the `.ino` if your wiring differs).

4. Flash the board (USB, first time — OTA works for subsequent updates once this build is running).

## Calibrating the load cell

Open the Serial Monitor at 115200 baud:

1. With nothing on the scale, send `TARE`.
2. Place a known reference weight on the scale (e.g. a 500g weight, or anything with a known mass).
3. Send `CAL:<grams>`, e.g. `CAL:500`.
4. The firmware computes and saves the calibration factor to flash (NVS) — it persists across power cycles and re-flashes, so you only need to do this once per physical load cell (redo it if you ever swap the load cell for a different unit).

Prototype calibration photo slot:

`../docs/images/hx711-calibration-serial.jpg`

## What it does at runtime

1. Connects to Wi-Fi (bounded retries with backoff, not an infinite block).
2. Polls `GET /sessions/active?cart_id=<CART_ID>` every 5s to find out whether a shopper is currently checked in.
3. While a session is active, samples weight once per second and POSTs the raw reading to `POST /sessions/{id}/weight` — the backend computes the delta and verification, not the firmware (see comments at the top of the `.ino` for why this moved).
4. A hardware watchdog (30s) resets the board if the firmware ever hangs unexpectedly.
5. A disconnected/unresponsive load cell is detected and logged as a fault instead of silently reporting a wrong zero.

## Known limitations (stated plainly, not glossed over)

- Secrets are out of source control (`secrets.h`), but a compiled binary/flash dump from a physically-accessed board can still be reverse engineered — real protection against that needs ESP32 Secure Boot + Flash Encryption, which is out of scope for this milestone.
- The single-point load cell (see Phase 2 hardware analysis) still has real off-center-loading error that no amount of firmware filtering fully removes.
- If two items are added in very quick succession, before a stable weight reading settles between them, the reported delta may reflect both items summed rather than matching either one individually — a documented simplification, not a claim of full robustness.
