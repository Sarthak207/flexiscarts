# SmartCart — Phase 2: Hardware Analysis

## 0. Important gap before anything else

Your list has **no compute board itself** — you've listed a **Pi Camera Module V2**, which physically requires a **Raspberry Pi** (CSI connector; it will not work on an ESP32, Jetson, or anything else), but no Raspberry Pi board is on the purchase list. There's also **no ESP32 dev board** listed, even though `firmware/smartcart_esp32.ino` exists in the repo and is written specifically for one.

Two realistic explanations, and the answer changes the architecture meaningfully:

- **(A)** You already own a Raspberry Pi and an ESP32 from a prior semester/kit and just didn't list them because they're not new purchases.
- **(B)** The plan has quietly shifted to **one controller (Raspberry Pi) doing everything** — camera, load cell, and driving the touchscreen directly — and the ESP32 firmware in the repo is now legacy/to-be-retired.

I'll flag this at the end with a direct question, because it decides whether Phase 3 firmware work targets two boards or one. For the rest of this analysis I'll cover the load cell + HX711 both ways (it can be read either from an ESP32 or bit-banged directly from Raspberry Pi GPIO — no ESP32 is strictly required for HX711).

---

## 1. Component-by-component analysis

### 1.1 7" Capacitive Touch LCD (HDMI + USB, ~₹3999)

- **Purpose:** Primary on-cart display — shows live cart contents, running total, product recommendations, and (once built) the checkout screen. This is the shopper-facing UI surface; everything the Pi/backend computes ultimately needs to render here.
- **Why selected:** HDMI+USB is the simplest possible integration path for a Raspberry Pi — HDMI carries video, USB carries the touch controller (usually shows up as a standard HID touchscreen, no special driver needed on recent Raspberry Pi OS). Capacitive (vs. resistive) gives multi-touch and a much better finger-swipe feel, which matters for a retail-facing UI a stranger will use with dirty/wet hands.
- **Alternatives:** DSI ribbon-cable displays (official Raspberry Pi 7" touchscreen) — lower cost, no HDMI cable clutter, but consumes the CSI-adjacent DSI port and is more fragile mechanically for a cart that will vibrate/bump around. A smaller e-paper or character LCD would be cheaper and lower power but couldn't support the recommendation/UI features the project's software goals need.
- **Advantages:** Standard HDMI/USB means it'll work with almost any single-board computer if you ever swap the Pi model; easy to source a case/mount; simple to test on a laptop even before the Pi is wired up.
- **Limitations:** HDMI+USB touch draws meaningfully more power than a DSI panel (relevant given you're running from a 5200mAh pack, not mains) and needs two separate cables routed through the cart frame — more points of mechanical failure than a single ribbon connector. Outdoor/bright-light readability of a standard LCD is also a real-world limitation the README's "supermarket" framing should account for if the cart is ever near storefront windows.
- **Communication protocol:** Video over HDMI (digital, no driver needed); touch input over USB HID (appears as a standard touch input device to Linux — no custom driver/kernel module required on modern Raspberry Pi OS).
- **Power requirements:** Powered via its own USB power input separate from the HDMI signal — typically 5V, and 7" capacitive touch panels in this class usually draw somewhere in the 300–500mA range at 5V under backlight load. This needs to come off your 5V rail (see the step-down section below), not directly off the 11.1V pack.
- **Integration:** Connects to the Raspberry Pi (HDMI-out + USB). The frontend UI (a browser in kiosk mode, or a lightweight Qt/Kivy app) runs on the Pi and renders here; this is the same UI conceptually described in the README's shopper-facing flow but currently doesn't exist in the repo at all — `webapp/dashboard/index.html` is an *admin* tool, not a shopper cart-display UI. Building the actual shopper-facing screen is new work, not a rework.

### 1.2 50kg Load Cell + HX711 Module (~₹125)

- **Purpose:** Weighs the cart's contents so the system can cross-verify what the camera *thinks* was added against an actual physical weight change — this is the "trust but verify" layer against misdetection or someone slipping an unscanned item in.
- **Why selected:** A 50kg-rated cell is a sensible choice for a *cart-mounted* platform scale (rather than a single-item scale) — you're weighing the whole basket, and a 50kg full-cart load is realistic for groceries. Load cell + HX711 (a 24-bit ADC purpose-built for load cells/strain gauges) is by far the cheapest and most widely-documented way to get precise weight into any microcontroller — hence the ₹125 price and the huge amount of existing library support (the `HX711` Arduino library your firmware already uses, plus mature Python ports for Raspberry Pi).
- **Alternatives:** A commercial digital scale module with a serial/UART output would need less calibration work but costs far more and is harder to physically integrate into cart structure. Multiple smaller load cells at each of the cart's basket corners (a "4-corner" scale design, like real retail smart-cart platforms use) would give more accurate, evenly-distributed weight sensing and let you detect *where* in the basket weight changed — but that's 4x the load cells, 4x the wiring, and a summing/averaging circuit or 4-channel ADC, which is a significant cost/complexity step up from a single 50kg cell. Given the ₹125 price point, you've clearly optimized for a single-point sensor, which is the right call for a first working system.
- **Advantages:** Extremely cheap, well-documented, works identically whether read from an ESP32 or a Raspberry Pi's GPIO (the HX711 protocol is a simple synchronous clock/data bit-bang, not I2C/SPI, so it doesn't need a hardware peripheral — any GPIO pair works).
- **Limitations:** A single centrally-mounted load cell under a cart basket will register uneven-loading errors if items are placed off-center (the same total weight registers differently depending on where in the basket it sits relative to the cell) — this is a real, non-trivial accuracy limitation for a **single-point** platform-scale mount that's worth calling out honestly in the report rather than glossing over. 24-bit HX711 resolution is more than enough precision-wise; the bigger real-world error source is mechanical (basket flex, cart vibration while pushed, item settling) rather than electrical.
- **Communication protocol:** Not I2C/SPI — HX711 uses a simple 2-wire synchronous serial protocol (clock pulses from the host, data bit read on each clock edge) at a fixed ~10Hz or ~80Hz output rate depending on the RATE pin strap. This is why it can be read equally well from ESP32 GPIO or Raspberry Pi GPIO with no dedicated bus controller needed.
- **Power requirements:** HX711 modules typically run at 2.6V–5.5V logic/supply, so it's compatible with either 3.3V (ESP32-native) or 5V logic depending on the specific breakout board's onboard regulator — worth confirming which variant you received, since some breakouts assume 5V-only. Current draw is minimal (single-digit mA), a non-issue against your battery budget.
- **Integration:** Physically mounted between the cart's basket and frame (a proper load-cell mount bracket, not just glued/taped — mechanical mounting quality directly determines reading accuracy far more than anything in software). Electrically, wired to whichever board ends up owning it (this is the open question from Section 0).

### 1.3 11.1V 5200mAh 3S Li-ion Battery (~₹1249)

- **Purpose:** Portable power source for the whole cart electronics stack, since a shopping cart obviously can't be tethered to a wall outlet.
- **Why selected:** 3S (11.1V nominal) Li-ion packs are the standard sweet spot for small robotics/cart projects — enough voltage headroom to efficiently step down to both 5V (Pi/display) and lower rails, while still being a manageable, widely-available, BMS-protected pack size. 5200mAh at 11.1V is roughly 57.7Wh, which is a reasonable capacity for a several-hour shopping-mall demo/runtime without being so large it's unsafe or hard to mount.
- **Alternatives:** A sealed lead-acid battery would be cheaper per Wh but far heavier and bulkier — bad for something mounted on a cart that needs to stay maneuverable. A larger power bank (5V-only USB) would skip the need for a buck converter entirely but couldn't supply the Pi + display + any motor/actuator loads at once without current limiting issues; most USB power banks also aggressively current-limit and can brown out a Raspberry Pi under camera+display+Wi-Fi load spikes.
- **Advantages:** Good energy density, standard 3S charge/discharge characteristics well-supported by the charger you also purchased, enough capacity headroom for the whole stack's combined draw (Pi ~500mA–1.2A depending on model/load, display ~300–500mA, ESP32 if used ~150–300mA average with Wi-Fi TX spikes to ~500mA+).
- **Limitations:** Li-ion packs need a genuine BMS (battery management system) for safe operation — over-discharge, over-current, and cell-balance protection. Confirm the specific pack you received includes a BMS (most retail "5200mAh 11.1V" packs marketed this way do, but it's worth explicitly verifying rather than assuming, since an unprotected 3S pack is a real fire/safety risk in a student project handled by many hands).
- **Communication protocol:** N/A (raw DC power source, not a data device) — though if the pack exposes a balance-lead connector, the charger needs to use it for proper 3S balance charging.
- **Power requirements:** Supplies 11.1V nominal (~12.6V full charge, ~9.9V cutoff typically for 3S) directly to the XL4015 step-down module's input.
- **Integration:** Feeds the XL4015 buck converter, which then supplies regulated 5V (or whatever you set it to) to the Pi, display, and other 5V-rail components. The ESP32 (if kept) typically wants 5V into its VIN/USB pin too (it has an onboard 3.3V regulator), so it can likely share the same 5V rail as the Pi rather than needing its own separate regulation.

### 1.4 XL4015 DC-DC Step-Down Adjustable Module (~₹71)

- **Purpose:** Steps the 11.1V battery rail down to a safe, regulated voltage (almost certainly 5V) for the Pi, display, and any other 5V logic.
- **Why selected:** XL4015 is a very common, cheap buck converter IC rated for reasonably high current (many breakout boards rate it up to ~5A continuous, though real sustainable output is usually lower — check the specific board's actual thermal/current rating rather than assuming the IC's absolute maximum), which matters because a Raspberry Pi under camera + display + Wi-Fi load can spike well above 1A.
- **Alternatives:** A linear regulator (like an LM7805) would be far simpler but hopelessly inefficient stepping 11.1V down to 5V at Pi-level currents — it would waste more power as heat than it delivers, draining your battery fast and needing a large heatsink. A purpose-built Pi-specific 5V/3A UBEC or a name-brand buck module (e.g., a Pololu or Mean Well DC-DC) would have tighter voltage regulation and better ripple filtering, at higher cost. The XL4015 is the right budget-conscious choice as long as it's tuned and tested properly.
- **Advantages:** Cheap, adjustable (a trimpot sets output voltage), efficient (switching regulator, typically 90%+ efficient vs. a linear regulator's ~45% efficiency at this voltage drop), handles enough current headroom for the whole low-voltage stack.
- **Limitations:** **This is the single most important component to get right before powering anything else on** — an XL4015 module's output voltage must be measured and precisely trimmed to 5.0–5.1V with a multimeter under no load *before* connecting the Pi, because these modules ship with an arbitrary trimpot setting from the factory and connecting an untrimmed module directly to a Raspberry Pi is one of the most common ways to destroy one. Switching regulators also introduce electrical noise that can affect nearby analog signals — worth keeping the XL4015 physically separated from the HX711/load-cell wiring if possible, since load-cell readings are sensitive to noise.
- **Communication protocol:** N/A (pure power hardware).
- **Power requirements:** Input 11.1V (nominal) from the battery pack; output configured to 5V for the digital stack.
- **Integration:** Sits electrically between the battery and everything else (Pi, display, ESP32 if kept). This should be the very first thing tested/verified in the whole build, in isolation, before any board is connected downstream.

### 1.5 Pro Range 3S Li-Ion Charger, 12.6V 2A (~₹471)

- **Purpose:** Safely recharges the 3S battery pack (balance-charges each of the 3 cells to avoid over-charging any single cell).
- **Why selected:** Matched to the 3S/11.1V pack — 12.6V is exactly a fully-charged 3S Li-ion pack's target voltage, and a dedicated Li-ion charger (rather than a generic DC power supply) is necessary because Li-ion chemistry requires constant-current/constant-voltage (CC/CV) charging with proper cutoff, not just a fixed voltage source.
- **Alternatives:** A USB-C PD "trigger board" style charger integrated into a BMS with charging support would let you charge via a common USB-C cable instead of a separate barrel-jack charger — more convenient, marginally more expensive, and would need the battery pack to expose USB-C charging (most raw 3S packs like the one you bought don't, so the dedicated charger is the correct/necessary choice here).
- **Advantages:** Purpose-matched voltage/current, straightforward barrel-jack interface, standard and safe for this pack chemistry.
- **Limitations:** 2A charge rate on a 5200mAh pack means a full charge from empty takes roughly 2.5–3+ hours (capacity ÷ current, plus CV-phase tapering) — worth factoring into your demo-day logistics (charge the night before, don't assume a quick top-up).
- **Communication protocol:** N/A.
- **Power requirements:** Mains-powered (wall adapter), outputs 12.6V/2A DC into the battery's charge port (ideally via the balance lead if the pack exposes one).
- **Integration:** Not part of the runtime system at all — purely a maintenance/charging accessory used when the cart is docked, not while it's operating.

### 1.6 Raspberry Pi Camera Module V2 (8MP, 1080p) (~₹1568)

- **Purpose:** The vision sensor for product detection — replaces whatever generic USB webcam the current `Detect_Items` script assumes (`cv2.VideoCapture(0)`, which is written generically enough to work with either, but a CSI camera needs a different capture backend on modern Raspberry Pi OS — see below).
- **Why selected:** The official Pi Camera V2 (Sony IMX219 sensor) is a well-supported, well-documented, cheap CSI camera with solid 1080p/30fps or lower-res/higher-fps modes, and integrates natively with Raspberry Pi's camera stack (`libcamera` on modern Raspberry Pi OS / Bullseye and later) without needing USB bandwidth or a separate driver.
- **Alternatives:** A USB webcam is simpler to test on a laptop and code against (`cv2.VideoCapture` "just works" via V4L2) but costs more for comparable quality and consumes a USB port that a Pi typically has few of, especially once the touchscreen's USB touch controller is also plugged in. The Pi Camera V2's successor, the **Camera Module 3**, offers autofocus (V2 is fixed-focus) which genuinely matters for a "hold item up to the camera at varying distances" use case — worth being aware of even though you've already purchased the V2; fixed-focus just means you'll want to fix/tune the mounting distance between the camera and where shoppers naturally place items rather than relying on autofocus to compensate for inconsistent distance.
- **Advantages:** Native Pi integration, no USB bandwidth contention, low power draw, small form factor easy to mount pointed into the basket.
- **Limitations:** Fixed focus (as noted above) — items held too close or too far will blur; 8MP sensor is more resolution than you'll actually run inference at (you'll downscale to whatever your model's input size is, e.g., 300×300 for MobileNet-SSD), so the extra resolution mainly matters if you ever want to *also* save full-res images for a future custom dataset/training pipeline.
- **Communication protocol:** MIPI CSI-2 (dedicated camera serial interface, not USB) — connects via the Pi's ribbon-cable CSI port.
- **Power requirements:** Powered directly through the CSI ribbon cable from the Pi's board-level 3.3V rail — no separate power wiring needed, draws a modest amount (well under 300mW).
- **Integration:** **This is the one component in your list that requires a code change, not just a wiring change** — the existing `Detect_Items` script opens the camera with `cv2.VideoCapture(0)`, which is the OpenCV/V4L2 path for USB webcams. A CSI camera on modern Raspberry Pi OS is best accessed via `libcamera`/`picamera2` (the current official Python library) rather than assuming V4L2 will just pick it up, though Raspberry Pi OS does provide a V4L2 compatibility layer that can sometimes make `cv2.VideoCapture(0)` work with CSI cameras too depending on OS version — this needs to be tested on your actual Pi/OS combination rather than assumed, and I'll account for it explicitly when I rework `Detect_Items` in Phase 3.

---

## 2. Hardware ↔ software module map (as this hardware set implies it)

| Hardware | Talks to (software) | Interface |
|---|---|---|
| Pi Camera V2 | `Detect_Items` (rewritten to use `picamera2`/`libcamera`) | CSI, via Pi's camera stack |
| Load Cell + HX711 | Either ESP32 firmware, or a new Pi-side weight-reading module — **pending your answer below** | Synchronous 2-wire bit-bang, GPIO |
| 7" Touch LCD | New shopper-facing UI (to be built — doesn't exist in repo yet) running on the Pi | HDMI (video) + USB (touch/HID) |
| Battery + XL4015 + Charger | No software interface — pure power layer | N/A |

---
