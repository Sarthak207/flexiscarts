# SmartCart — Phase 1: Repository Analysis

## 0. What's actually in the repo

```
SmartCart-main/
├── README.md                              (template/placeholder, doesn't match actual repo)
├── Detect_Items                           (Python, no extension — Raspberry Pi CV script)
├── firebase/
│   └── database-structure-example.json    (example RTDB schema, for manual import)
├── firmware/
│   └── smartcart_esp32.ino                (ESP32 Arduino sketch)
└── webapp/
    └── dashboard/
        └── index.html                     (static admin page, Firebase JS SDK)
```

This is a **very early-stage prototype / proof-of-concept**, not the layered project the README claims (`hardware/`, `software/`, `src/`, `models/`, `datasets/`, `docs/` all referenced in the README don't exist). There is no `requirements.txt`, no `app.py`, no `LICENSE`, no tests, no `.gitignore`, and no actual trained model or dataset — just a wiring-together of three independent pieces via a shared Firebase Realtime Database. That's a completely reasonable place for an academic project to be at this stage; it just means Phases 2–8 are a real build, not a polish pass.

---

## 1. File-by-file analysis

### 1.1 `Detect_Items` (Raspberry Pi, Python)

**Purpose:** Captures webcam frames, runs a stock MobileNet-SSD (Caffe, 20 generic COCO-ish classes — not retail products), and if a detected class label happens to match a key in Firebase's `/products` node, writes that "detected product" plus a running cart entry to `/sessions/{SESSION_ID}`.

**How it interacts with other modules:**
- Reads `/products` from Firebase (populated manually via the JSON in `firebase/`).
- Writes `/sessions/{SESSION_ID}/lastDetectedProduct` and `/sessions/{SESSION_ID}/items/{key}` — this is the same path the ESP32 firmware reads (`lastDetectedProduct/expectedWeight`) and writes to (`cartWeight`), and the same path the dashboard *doesn't* currently read (dashboard only touches `/users`, not `/sessions` — see 1.4).
- `SESSION_ID` is a **hardcoded string** (`"demo_session"`) — there is no real per-cart or per-user session concept anywhere in the codebase yet, despite the comment claiming it's "set after login."

**Bugs:**
- Class list (`CLASSES`) is the stock 21-class VOC/MobileNet-SSD label set (`bottle`, `person`, `chair`, `sofa`...). The product DB keys (`bottle`, `chips_packet`) only coincidentally overlap on `"bottle"` — `chips_packet` can never be detected because it's not a class the model knows. This means **the core "product recognition" feature does not actually work end-to-end** as shipped; it only demos on a water bottle.
- `push_detected_product` does a **synchronous read-then-write** for quantity (`.get()` inside the write call) — this is a classic read-modify-write race: if two detections land close together, or if the ESP32/dashboard also touch `quantity`, one update can be lost (no transaction/`runTransaction`).
- Quantity is never actually incremented anywhere — it reads the existing quantity and writes the *same* value back, so repeated detections of the same item never increase count.
- No de-duplication by product identity — `DETECTION_COOLDOWN_SEC = 3` is a **global** cooldown across *all* products, not per-product, so scanning item A then quickly item B within 3s silently drops B.
- `cv2.imshow`/`cv2.waitKey` assumes a display is attached — will throw on a headless Pi (common deployment for an in-cart controller) with no fallback/flag.
- No exception handling around `net.forward()`, Firebase calls, or camera reads inside the loop beyond the single `ret` check — any transient Firebase network hiccup kills the whole process.
- Credentials (`serviceAccountKey.json` path, DB URL) are hardcoded constants, not environment/config-driven.

**Missing features:** barcode/QR fallback, OCR, multi-item/multi-object handling in a single frame (currently just fires on every matching label independently with a shared cooldown), object tracking (same item re-entering frame re-triggers), confidence-based product verification, retry/backoff, logging (uses bare `print`), any notion of "item removed from cart."

**Poor practices:** no config file/env vars, no logging module, no type hints, no docstring-driven API separation (detection, Firebase I/O, and business logic for "add to cart" are all smashed together in one 150-line script), model/paths are magic strings, no `main()` guard against partial Firebase initialization failures.

**Scalability/architecture issues:** Firebase Admin SDK write pattern doesn't scale past a handful of concurrent carts (no batching, no offline queue); single global `SESSION_ID` means the script can only ever run one cart at a time; tight-coupling of CV inference and Firebase I/O means neither can be tested or swapped independently.

**Performance:** MobileNet-SSD 300×300 Caffe inference on a Raspberry Pi CPU (no indication of NCS/Coral/GPU acceleration) typically runs low single-digit FPS — workable for a slow "hold item near camera" UX but not real-time multi-item tracking.

**Security:** service account key is a plaintext file the script expects to sit next to itself with no `.gitignore` guidance in-repo (mentioned only in a comment); Firebase Admin SDK has full DB access — if this Pi is ever compromised or the key leaks, an attacker gets full read/write on the whole database, including the `/users` node with tokens.

---

### 1.2 `firmware/smartcart_esp32.ino` (ESP32, Arduino/C++)

**Purpose:** Connects to Wi-Fi, reads an HX711 load cell, pushes `cartWeight` to Firebase every second, and cross-checks the measured weight against the `expectedWeight` of whatever the Pi last detected, writing a boolean `weightVerified` back.

**Interactions:** Shares the `/sessions/{SESSION_ID}` tree with the Pi script (same hardcoded `"demo_session"`). This is the *only* piece of hardware-verification logic in the whole system — a reasonable and legitimately good design idea (camera + load cell cross-check to catch misdetection or "shove wrong item in cart") that's currently just not fleshed out.

**Bugs:**
- Wi-Fi and Firebase credentials are compiled into the binary in plaintext (`#define WIFI_SSID "YOUR_WIFI_SSID"` etc.) — anyone with physical/flash access to the ESP32 gets your Wi-Fi password and Firebase auth email/password.
- `connectWiFi()` blocks forever in a `while` loop with no timeout — if Wi-Fi is unreachable at boot, the cart never starts (no fallback AP mode, no retry backoff, no watchdog feed inside the loop so it could reset).
- `CALIBRATION_FACTOR` is a hardcoded magic number with a comment telling the user to "calibrate for your load cell" — no runtime/serial calibration routine, no persistence (NVS/EEPROM) of the calibrated value.
- `if (weight < 0) weight = 0;` silently clamps negative readings (which usually indicate the scale needs re-taring or drifted) instead of flagging/logging a fault.
- Firebase Realtime Database auth uses **email/password auth** (`FIREBASE_USER_EMAIL`/`PASS`) — deprecated/discouraged pattern vs. Firebase Auth custom tokens or service-account-signed tokens; also means the password is in the firmware binary.
- No debounce/smoothing beyond `get_units(5)` averaging — a cart being pushed over a bump will register weight spikes as false verification failures.
- `verifyAgainstDetectedProduct` fires on **every** loop tick (every 1s) even when no new product was detected, repeatedly re-verifying the same stale `lastDetectedProduct` against the current total cart weight — which is conceptually wrong once more than one item is in the cart (total weight will never match a single item's `expectedWeight` after item #2 is added).

**Missing features:** OTA updates, hardware watchdog (`esp_task_wdt`), sensor fault detection (load cell disconnected → NaN), reconnect/backoff strategy beyond `Firebase.reconnectWiFi(true)`, structured logging, low-battery/power monitoring, tare-on-item-removal logic, per-item weight delta tracking (vs. only "total cart weight").

**Poor practices:** no separation between Wi-Fi/Firebase/sensor "drivers" and business logic; everything lives in `loop()`; no state machine (connecting/connected/verifying/error); credentials not in a separate `secrets.h` (even that would be better, though still not ideal vs. provisioning).

**Architecture issue:** the single-total-weight-vs-single-expected-weight comparison model fundamentally cannot scale to a multi-item cart — this needs to become **delta-weight-since-last-detection** compared to the newly detected item's expected weight, not cumulative-vs-single-item.

**Power:** no discussion of load cell excitation voltage stability, ESP32 brownout behavior under Wi-Fi TX current spikes while HX711 is mid-read (a known source of noisy readings on breadboard builds) — worth covering in Phase 2 once I know your actual power supply/battery setup.

---

### 1.3 `firebase/database-structure-example.json`

**Purpose:** Reference schema for manual import into Firebase Realtime Database — shows `/products`, an example `/sessions/demo_session`, and `/users`.

**Issues:**
- This is a **Realtime Database** (JSON-tree) schema, not Firestore — fine for a small prototype, but RTDB has real limitations for this use case: no native querying by multiple fields (can't easily query "all sessions for user X active in the last hour"), weaker security-rule expressiveness than Firestore, and it doesn't scale well past simple tree reads/writes. Worth flagging as a Phase 3 discussion (migrate to Firestore, or add a proper backend + relational/document DB) rather than just accepting RTDB by default.
- `/users/{id}/token` is a **plaintext, unhashed, non-expiring token** used for what looks like session/login purposes (see 1.4) — this is a real security gap: no way to revoke without deleting the whole user, no expiry, no rotation, stored in plaintext in a DB that the Pi's admin SDK, the ESP32, and the browser dashboard (via client SDK) can all potentially reach depending on security rules (which are **not included anywhere in the repo** — this is a significant gap; without rules, RTDB defaults to either fully open or fully locked, both wrong here).
- No versioning/schema documentation beyond this one example file — no indication of how `/sessions` entries get created, cleaned up, or expired (an abandoned cart session lives forever).

### 1.4 `webapp/dashboard/index.html`

**Purpose:** Single static HTML page, Firebase JS SDK loaded via CDN, lets an admin add a user (auto-generates an 8-char alphanumeric token) and deactivate users. Reads/writes only `/users`.

**Bugs / security concerns:**
- **Firebase config (including API key) is embedded directly in client-side JS**, and — more importantly — there is **no authentication gate on the page itself**. Anyone with the URL and no login can add/deactivate users, assuming Firebase security rules allow it (and since no rules are defined anywhere in the repo, this is likely wide open).
- `generateToken()` uses `Math.random()`, which is **not cryptographically secure** — 8 chars from a 62-char alphabet is also a fairly small space (~2.2 × 10^14 combinations, but `Math.random()`'s predictability matters more than the space size here) for something acting as an auth credential.
- No confirmation dialog before deactivating a user (destructive action, one click).
- Directly using `user.userId` etc. via template-literal `innerHTML` — for this specific field set it's low-risk (self-entered data, single admin), but it's the kind of pattern (unescaped interpolation into `innerHTML`) that becomes an XSS vector the moment any field could contain attacker-controlled or less-trusted input.
- No pagination/search — `usersRef.on("value", ...)` pulls and re-renders the **entire** users table on every single change, for every connected client, which won't scale past a small user list and re-downloads the whole node on any single user edit.
- Doesn't touch `/sessions` or `/products` at all — so despite being called a "dashboard," it currently has zero visibility into carts, live sessions, revenue, or inventory. It's a user-token admin tool, not a shopping dashboard.

**Missing features:** authentication (Firebase Auth, not raw open DB access), input validation (mobile number format, duplicate user IDs), session/cart visibility, product/inventory management UI, billing history, analytics, any styling beyond a single inline `<style>` block, mobile responsiveness, dark mode.

---

## 2. Cross-cutting architecture issues (whole system)

1. **No backend/API layer at all.** The Pi script, the ESP32, and the dashboard each talk **directly to Firebase** with different SDKs (Admin SDK, Arduino Firebase client, JS client SDK) and no shared business-logic layer. This means: cart totals, verification logic, and "item added" semantics are each reimplemented (or half-implemented) per-device, security rules become the *only* enforcement point (and none exist in-repo), and there's no place to plug in payment processing, receipts, or analytics without touching three separate codebases.
2. **No security rules anywhere in the repo.** This is the single biggest gap — without seeing your actual Firebase project's rules, I have to assume the honest worst case (test-mode/open rules), which given the plaintext tokens and unauthenticated dashboard would be a real vulnerability in anything beyond a closed classroom demo.
3. **Single global hardcoded session (`"demo_session"`)** everywhere — the system as-is can only support **one cart, one active session, ever**, system-wide. Multi-cart support requires session IDs to flow from a real "cart login" step (e.g., scan a QR/RFID tag mounted on the cart, or the token system in the dashboard actually being *used* somewhere — currently it's generated but nothing in the repo ever validates it).
4. **No payment integration** despite being a headline feature in the README.
5. **No product recommendation/ML logic** despite being a headline feature in the README — currently 100% aspirational text.
6. **No error/retry strategy anywhere** — camera failure, Wi-Fi drop, Firebase write failure, or load-cell fault all currently either crash, silently no-op, or block forever.
7. **No tests, no CI, no `requirements.txt`/dependency pinning, no `.gitignore`, no LICENSE file** (despite the README claiming MIT).
8. **README doesn't match the repo** — references a repo layout (`docs/`, `hardware/`, `software/`, `src/`, `models/`, `datasets/`) that doesn't exist, and lists "Embedded Controller (ESP32/Raspberry Pi/Arduino)*" as if undecided, when the actual code has clearly already committed to an ESP32 + separate Raspberry Pi split.

---

## 3. Text architecture diagram (current, as-built)

```
┌─────────────────────┐        webcam frames        ┌──────────────────────────┐
│   Raspberry Pi       │ ───────────────────────────▶│  MobileNet-SSD (Caffe)    │
│   (Detect_Items)     │                              │  local inference          │
└─────────┬────────────┘◀───────────────────────────  └──────────────────────────┘
          │  label match against /products
          │  (Firebase Admin SDK, Python)
          ▼
┌───────────────────────────────────────────────────────────────────┐
│                     Firebase Realtime Database                     │
│  /products/{key}            (manually imported, static)            │
│  /sessions/demo_session/     <- hardcoded, single global session    │
│      cartWeight                                                     │
│      lastDetectedProduct { key, name, price, expectedWeight,       │
│                             weightVerified, detectedAt }            │
│      items/{key} { name, price, quantity }                          │
│  /users/{userId} { userId, mobile, token, active, createdAt }       │
│  (no security rules defined anywhere in repo)                       │
└───────────┬───────────────────────────────────┬─────────────────────┘
            │  read expectedWeight                │  read/write /users only
            │  write cartWeight, weightVerified    │  (Firebase JS SDK, browser)
            ▼                                      ▼
┌─────────────────────┐                  ┌──────────────────────────┐
│   ESP32 firmware      │                  │  Web Dashboard (static)   │
│   + HX711 load cell   │                  │  add/deactivate users,    │
│   Wi-Fi direct to      │                  │  generate plaintext token │
│   Firebase (no backend)│                  │  NO auth gate on page     │
└─────────────────────┘                  └──────────────────────────┘

Notably absent: any backend API, any payment module, any recommendation
engine, any customer-facing UI/checkout screen, any security-rules file,
any real session-creation flow (QR/RFID scan-in), any barcode fallback.
```

---

## 4. Current end-to-end workflow (startup → shutdown), as the code actually behaves today

1. **Admin setup (manual, one-time):** Admin imports `database-structure-example.json`'s `/products` node into Firebase console by hand. No product-management UI exists to do this at runtime.
2. **Dashboard (optional, disconnected from cart flow):** Admin opens `index.html` locally/hosted, adds a user, gets a generated token — but **nothing else in the codebase ever reads or validates that token**, so this step currently has no effect on the shopping flow.
3. **ESP32 boot:** Powers on, blocks until Wi-Fi connects (no timeout), authenticates to Firebase via email/password, tares the load cell once, then loops forever: every 1s, read weight → push to `/sessions/demo_session/cartWeight` → re-fetch `lastDetectedProduct/expectedWeight` → compare and write `weightVerified`.
4. **Pi script start (manual, separately from ESP32):** Loads `/products` once at startup, opens the webcam, loops: grab frame → run detection → for any detected label that both matches a `/products` key *and* is outside the 3-second global cooldown → write `lastDetectedProduct` and bump (not really — see bug above) `items/{key}`.
5. **Shopper interaction:** Places an item in the cart. If the item happens to be visually classified as `"bottle"` by the stock model (the only class that overlaps the demo product DB), the Pi fires a Firebase write. The ESP32's next 1s tick reads the new `expectedWeight` and compares it to *total* cart weight (not item delta), which is only correct for the very first item.
6. **"Checkout":** Does not exist in code. The README describes digital payment and bill totals, but there is no billing/payment module, no total-price calculation logic anywhere (not even client-side), and no checkout UI.
7. **Shutdown:** Neither script handles `SIGTERM`/`Ctrl+C` gracefully beyond the Pi script's `try/finally` releasing the camera; the ESP32 has no shutdown state at all (it's an infinite loop firmware, as expected for embedded, but there's also no low-battery or power-loss handling).

---

## 5. What I need from you before Phase 2–8

Per the brief's own instruction to propose a plan before writing code, here's where I'm blocked without more input:

1. **Hardware list** — you mentioned you'd provide the actual hardware purchased. I don't have it yet (ESP32 board variant, camera module + host — is the Pi a Pi 4/5/Zero 2W?, load cell + HX711 specs, display if any, power source/battery, cart chassis). This materially changes Phase 2 and a lot of Phase 3's feasibility calls (e.g., quantization/edge-optimization choices depend heavily on whether inference runs on the Pi CPU, a Coral/NCS accelerator, or is offloaded elsewhere).
2. **Scope for this pass** — the full brief (Phases 1–8, ~16 deliverable categories) is a multi-week capstone-level body of work. I'd rather build it well in stages than rush a shallow version of everything. My suggested first milestone, once I have the hardware list:
   - Fix the architectural single-session/no-backend/no-security-rules issues with a small real backend (this is the highest-leverage change — almost everything else depends on it existing).
   - Rework the Pi detection script into a proper module (config-driven, logged, retried, per-item cooldown, barcode fallback as a realistic near-term win over "retrain a custom model").
   - Rework the ESP32 firmware (delta-weight verification, watchdog, secrets separated out, state machine).
   - Then documentation (Phases 5–7) once the system it's documenting is actually real.
3. **Do you have a working Firebase project already** (with data in it), or should the improved system move to a proper backend (e.g., FastAPI/Node + Postgres) with Firebase optionally kept just for realtime device sync? This is a real architectural fork and I'd rather you weigh in than assume.

Let me know on those three points and I'll move into Phase 2 (hardware) and start Phase 3 implementation in scoped, reviewable chunks rather than one giant drop.
