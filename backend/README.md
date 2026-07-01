# SmartCart Backend (Milestone 1)

FastAPI + PostgreSQL backend replacing the old direct-to-Firebase architecture.
Runs on the Raspberry Pi 4 itself via Docker Compose, alongside the camera
detection module and the (upcoming) touchscreen UI.

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
| `GET /users` | Admin JWT | Admin dashboard |
| `PATCH /users/{id}` | Admin JWT | Admin dashboard (activate/deactivate) |
| `POST /products` | Admin JWT | Admin dashboard / `seed_products.py` |
| `GET /products` | — | Touchscreen UI (catalog display) |
| `GET /products/by-label/{label}` | — | Pi detection module |
| `POST /sessions/start` | shopper token in body | Touchscreen UI (cart login) |
| `GET /sessions/{id}` | — | Touchscreen UI (live cart view) |
| `POST /sessions/{id}/close` | — | Touchscreen UI (checkout) |
| `POST /sessions/{id}/items` | `X-Device-Key` header | Pi detection module |
| `DELETE /sessions/{id}/items/{item_id}` | `X-Device-Key` header | Pi detection module (future: item removal) |
| `POST /sessions/{id}/weight` | `X-Device-Key` header | ESP32 firmware |

## What's intentionally NOT here yet (see Implementation Plan / README future scope)

- Payment processing — `POST /sessions/{id}/close` computes and returns an
  itemized bill total; it does not charge anyone. Real payment gateway
  integration needs a merchant account and is out of scope for this build.
- Barcode-based product ID — descoped per your confirmation that products
  don't have real barcodes to scan; camera-only detection.
- Recommendation engine — planned for Milestone 6, once real purchase
  history exists to compute it from.
