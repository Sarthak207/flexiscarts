# SmartCart — Implementation Plan (for approval before any code is written)

Architecture confirmed: **Raspberry Pi 4 + separate ESP32**, backend moving from direct-Firebase to **FastAPI + PostgreSQL**.

---

## 1. Target architecture (proposed)

```
                                   ┌────────────────────────────┐
                                   │   FastAPI Backend (new)      │
                                   │   + PostgreSQL (new)         │
                                   │   Runs on the Pi 4 itself,   │
                                   │   or a laptop/server on the  │
                                   │   same LAN during dev/demo   │
                                   │                              │
                                   │  REST API:                   │
                                   │   /sessions  (create/close)  │
                                   │   /items     (add/remove)    │
                                   │   /weight    (from ESP32)    │
                                   │   /products  (catalog CRUD)  │
                                   │   /users     (admin)         │
                                   │   /checkout  (bill/total)    │
                                   └───────┬──────────────┬───────┘
                                           │              │
                          HTTP/REST (Wi-Fi)│              │HTTP/REST (Wi-Fi)
                                           │              │
                     ┌─────────────────────┴──┐      ┌────┴─────────────────────┐
                     │   Raspberry Pi 4         │      │   ESP32                    │
                     │   - Pi Camera V2 (CSI)   │      │   - HX711 + 50kg load cell │
                     │   - Detection module     │      │   - Posts weight readings  │
                     │     (rewritten,          │      │     to backend over HTTP   │
                     │      picamera2-based)    │      │     (replaces direct       │
                     │   - 7" touchscreen UI    │      │      Firebase writes)      │
                     │     (kiosk web app,      │      │   - Watchdog, reconnect    │
                     │      talks to backend    │      │     logic, delta-weight    │
                     │      over localhost/LAN) │      │     verification           │
                     └──────────────────────────┘      └────────────────────────────┘
```

**Firebase is fully retired** — the RTDB, the Admin SDK usage in `Detect_Items`, the Firebase ESP client in the firmware, and the Firebase JS SDK in the dashboard are all replaced by calls to the new FastAPI backend. This directly fixes the biggest issues from Phase 1: no shared business logic, no security rules, plaintext tokens, and the single hardcoded global session.

## 2. Why this direction (tradeoffs, stated up front)

- **FastAPI + Postgres over Firebase:** gains real relational integrity (proper foreign keys between sessions/items/products/users instead of a loosely-typed JSON tree), a real place to put auth, validation, and business logic once instead of three times, and standard SQL for the analytics/recommendation features the README promises. Costs: you now own running/deploying a backend and DB yourself instead of Google managing it — reasonable for an academic project where demonstrating backend engineering is itself part of the grade, and the Pi 4 has enough headroom to run FastAPI + Postgres + the detection script + a kiosk browser simultaneously, though I'll benchmark this once built rather than assume.
- **HTTP/REST between ESP32 and backend, not Firebase or MQTT:** REST is simpler to implement, test, and secure (a single token-authenticated endpoint) than standing up an MQTT broker for a system with exactly one weight-reporting device. If you ever scale to many carts reporting concurrently, MQTT's pub/sub model becomes more attractive — worth flagging as a documented future-scope item rather than building it now for a single-cart academic prototype.
- **Session creation:** currently nothing in the repo ever validates the dashboard's generated token against anything. I'll implement real session creation: shopper enters/scans their token on the touchscreen at cart start → backend validates against `/users` → creates a `sessions` row tied to that user and this specific cart → all subsequent item/weight events are scoped to that session ID instead of the hardcoded `"demo_session"`.

## 3. Scoped build order (milestones)

Rather than dumping the entire Phase 3–8 codebase at once, I'll build and share it in reviewable stages:

1. **Backend core** — FastAPI app, Postgres schema (users, products, sessions, cart_items), auth (session tokens + a real admin auth, not open access), Dockerized for easy setup. This unblocks everything else.
2. **ESP32 firmware rework** — HTTP client instead of Firebase, delta-weight verification (fixing the "total vs single item" bug), watchdog, reconnect/backoff, secrets separated from source.
3. **Pi detection module rework** — `picamera2`-based capture, config-driven, per-product cooldown (fixing the shared-cooldown bug), barcode fallback as the realistic near-term accuracy improvement, structured logging, retry logic.
4. **Touchscreen shopper UI** — new kiosk web app (doesn't exist yet): login/token entry, live cart view, running total, recommendations, checkout screen.
5. **Admin dashboard rework** — rebuilt against the new backend (auth-gated), adds product/inventory management and live session visibility, not just user tokens.
6. **AI features** — frequently-bought-together / basket-based recommendations using real SQL aggregation over purchase history (feasible with the data model above); explicitly **not** attempting a custom-trained product classifier as a "quantized edge model" claim unless you have or plan to collect a real labeled product image dataset — I'll implement barcode-based product ID as the realistic accuracy improvement instead, and document custom model training as future scope with an honest explanation of what a real dataset/training effort would require.
7. **Documentation set** : architecture diagrams, hardware/software/DB/CV/embedded docs, testing docs, README rewrite, contribution report — written against the *actual* system once it's built, not aspirational.
