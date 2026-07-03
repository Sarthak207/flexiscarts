# SmartCart Backend (Milestones 1 & 6)

FastAPI + PostgreSQL backend replacing the old direct-to-Firebase architecture.
Runs on the Raspberry Pi 4 itself via Docker Compose, alongside the camera
detection module, the touchscreen UI, and the admin dashboard.

## Setup

```bash
cd backend
cp .env.example .env
# Edit .env: set real values for POSTGRES_PASSWORD, JWT_SECRET_KEY,
# DEVICE_API_KEY, BOOTSTRAP_ADMIN_PASSWORD. Generate secrets with:
#   python3 -c "import secrets; print(secrets.token_hex(32))"

docker compose up -d --build
```

The API is now on `http://<pi-ip>:8000`. Interactive API docs (auto-generated
by FastAPI) are at `http://<pi-ip>:8000/docs` — useful for testing endpoints
by hand before the touchscreen UI and firmware are wired up (Milestones 2–4).

## First-run: get an admin token and seed the catalog

```bash
curl -X POST http://localhost:8000/auth/admin/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<your BOOTSTRAP_ADMIN_PASSWORD>"}'
# copy the access_token from the response

python3 seed_products.py --token <access_token>
```

## Running without Docker (local development)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="sqlite:///./dev.db"   # or a local Postgres URL
export JWT_SECRET_KEY=dev-secret
export DEVICE_API_KEY=dev-device-key
export BOOTSTRAP_ADMIN_PASSWORD=dev-admin-password
uvicorn app.main:app --reload
```

(SQLite works fine for local development/testing — the ORM models use
portable SQLAlchemy types. Production/demo deployment should use the
Postgres setup above via docker-compose.)

## API overview

| Endpoint | Auth | Called by |
|---|---|---|
| `POST /auth/admin/login` | — | Admin dashboard |
| `POST /users` | Admin JWT | Admin dashboard (create shopper, returns token once) |
| `GET /users` | Admin JWT | Admin dashboard (shoppers only, admin accounts excluded) |
| `PATCH /users/{id}` | Admin JWT | Admin dashboard (activate/deactivate) |
| `POST /products` | Admin JWT | Admin dashboard / `seed_products.py` |
| `GET /products` | — | Touchscreen UI (catalog display, active only) |
| `GET /products/all` | Admin JWT | Admin dashboard (includes inactive) |
| `PATCH /products/{id}` | Admin JWT | Admin dashboard (edit / deactivate / reactivate) |
| `GET /products/by-label/{label}` | — | Pi detection module |
| `GET /sessions` | Admin JWT | Admin dashboard (live sessions overview, filterable by status) |
| `POST /sessions/start` | shopper token in body, rate-limited | Touchscreen UI (cart login) |
| `GET /sessions/active` | — | ESP32 firmware, Pi detection module, touchscreen UI (session discovery) |
| `GET /sessions/{id}` | — | Touchscreen UI (live cart view) |
| `POST /sessions/{id}/close` | — | Touchscreen UI (checkout) |
| `POST /sessions/{id}/items` | `X-Device-Key` header | Pi detection module |
| `DELETE /sessions/{id}/items/{item_id}` | `X-Device-Key` header | Pi detection module (future: item removal) |
| `POST /sessions/{id}/weight` | `X-Device-Key` header | ESP32 firmware |
| `GET /recommendations/frequently-bought-with/{product_id}` | — | (available for future UI use) |
| `GET /recommendations/for-shopper/{session_id}` | — | Touchscreen UI (shopping-screen suggestions panel) |
| `GET /analytics/summary` | Admin JWT | Admin dashboard (Analytics panel) |

## Recommendations & analytics (Milestone 6)

Both are plain SQL aggregation over real closed-session purchase history —
not a trained model. See the docstrings in `app/routers/recommendations.py`
and `app/routers/analytics.py` for the full reasoning, but briefly:

- **Frequently bought together**: co-occurrence count across all CLOSED
  sessions containing a given product.
- **Personalized "you usually buy"**: a shopper's own repeat-purchase
  pattern from their past CLOSED sessions, excluding whatever's already
  in their current cart. Falls back to store-wide trending products
  (clearly labeled `"trending"`, not silently passed off as personalized)
  for a shopper with no purchase history yet.
- Every response includes a `basis` field (`frequently_bought_together` /
  `your_past_purchases` / `trending` / `not_enough_data`) so callers never
  have to guess why a list is empty or where a suggestion came from.

## What's intentionally NOT here (see Implementation Plan / README future scope)

- Payment processing — `POST /sessions/{id}/close` computes and returns an
  itemized bill total; it does not charge anyone. Real payment gateway
  integration needs a merchant account and is out of scope for this build.
- Barcode-based product ID — descoped per your confirmation that products
  don't have real barcodes to scan; camera-only detection.
- A trained recommendation/ML model — a single-cart academic pilot doesn't
  generate remotely enough data to train one meaningfully; SQL aggregation
  over real purchase history is the honest, defensible scope (see above).
