# SmartCart Kiosk UI (Milestone 4)

The shopper-facing touchscreen UI — new in this rebuild; nothing like it
existed in the original repo (`webapp/dashboard/index.html` was an admin
tool, not this). Plain HTML/CSS/JS, no build step, sized for a 7"
1024×600 landscape capacitive touch panel.

## Design

A "receipt paper + price tag" visual language rather than a generic
dashboard look — the cart contents render as a receipt-tape list
(monospace, dotted leaders), and the running total is styled as a die-cut
price tag, the one deliberately bold element in an otherwise quiet UI.
See the comment block at the top of `styles.css` for the full token
system (palette, type roles, layout rationale).

![SmartCart kiosk shopping screen](../docs/images/kiosk-shopping-cart.png)

Additional kiosk screenshots should be stored at:

- `docs/images/kiosk-login.png` — login-code keypad screen
- `docs/images/kiosk-checkout-receipt.png` — post-checkout receipt screen

## Setup

No dependencies to install — it's static files. Just point `config.js` at
your backend:

```js
window.SMARTCART_CONFIG = {
  apiBaseUrl: "http://localhost:8000", // backend runs on the same Pi 4
  cartId: "cart-01",                    // must match CART_ID in the ESP32/detection .env
  cartSummaryPollMs: 2000,
};
```

## Running as a kiosk on the Raspberry Pi 4

Serve the folder (any static file server works):

```bash
cd kiosk-ui
python3 -m http.server 8080
```

Then launch Chromium in kiosk mode pointed at it, e.g. in
`~/.config/lxsession/LXDE-pi/autostart` (adjust for your desktop
environment/OS image):

```
@chromium-browser --kiosk --noerrdialogs --disable-infobars --incognito http://localhost:8080
```

`--incognito` here isn't about privacy — it avoids the browser silently
persisting any cached state across shopper sessions on a shared public
device.

## How it stays in sync with the rest of the system

- On load, it asks the backend "is there an active session for my
  `cart_id`?" (`GET /sessions/active`) — the same pattern the ESP32
  firmware and the Pi detection module already use. This means a
  Chromium restart mid-shopping-trip recovers straight back into the
  shopping screen instead of losing the shopper's place — the backend is
  the single source of truth, not anything stored in the browser tab.
- While on the shopping screen, it polls `GET /sessions/{id}` every 2s
  (`cartSummaryPollMs`) to pick up items the camera/load cell added from
  the *other* two devices in the system — this UI never talks to the
  camera or load cell directly, only to the backend they all share.

## A backend change this milestone required

Building this surfaced that the shopper login token (originally a
32-character secure string, fine for copy-paste, unrealistic to type on
an on-screen keyboard) needed to be shorter. I changed
`generate_shopper_token()` in the backend to an 8-character code from a
32-symbol unambiguous alphabet, and added a rate limiter to
`POST /sessions/start` to compensate for the smaller search space (5
attempts per minute per client, in-memory — see the docstring on
`LoginRateLimiter` in `backend/app/core/security.py` for the documented
scale limitation of that approach). If you've already generated shopper
users against the old 32-char scheme, regenerate them — old tokens won't
match the new on-screen keyboard's alphabet.

## Known limitations

- No login method other than the on-screen keyboard — no QR/RFID scan-in,
  because that hardware isn't in your purchased list. If a QR/RFID reader
  is added later, it's a natural login-screen alternative alongside the
  keyboard, not a replacement architecture.
- The "confirming weight…" indicator on a cart item reflects
  `weight_verified` from the backend, which (see the weight-verification
  code) can occasionally mis-attribute a delta if two items are added in
  very quick succession — the UI surfaces whatever the backend reports,
  it doesn't second-guess it.
- No error-recovery UI for "the backend is completely unreachable" beyond
  a login-screen error message and shopping-screen polling silently
  retrying — a fully offline-tolerant kiosk (e.g. queuing actions locally)
  is a real future-scope item, not attempted here.
- The "You might also like" panel (Milestone 6) is informational only —
  there's no add-to-cart button, because every item in this system is
  added by the camera/load cell, never by a touchscreen tap. Suggesting
  something a shopper can't act on directly from this screen is a
  deliberate, honest scope limit, not an oversight.
