# SmartCart — In-Progress Rebuild

This is the combined, in-progress repository after Milestones 1–3 of the
upgrade plan. **This is not the final Phase 7 README** — that comes once
the whole system (touchscreen UI, admin dashboard, documentation set) is
built. This one just orients you to what's here right now.

## Status

| Milestone | Status | Folder |
|---|---|---|
| 1. Backend core (FastAPI + Postgres) | ✅ Done, tested | `backend/` |
| 2. ESP32 firmware rework | ✅ Done, not yet flash-tested on real hardware | `firmware/` |
| 3. Pi detection module rework | ✅ Done, tested (mocked) | `detection/` |
| 4. Touchscreen shopper UI | ⏳ Not started | — |
| 5. Admin dashboard rework | ⏳ Not started | — |
| 6. AI/recommendation features | ⏳ Not started | — |
| 7. Full documentation set | ⏳ Not started | `docs/` (analysis docs only so far) |

## Architecture (current)

```
Raspberry Pi 4                          ESP32
├── backend/  (FastAPI + Postgres,      ├── firmware/  (HX711 load cell,
│   Docker Compose, runs on the Pi)     │   posts weight readings over
├── detection/  (Pi Camera V2 or        │   HTTP to the backend)
│   USB webcam, posts detections
│   over HTTP to the backend)
└── (Milestone 4: touchscreen UI,
    not yet built)
```

All three pieces above talk to the backend over plain HTTP/REST — Firebase
has been fully retired from this part of the system. See
`docs/Implementation_Plan.md` for the full architecture rationale.

## Getting the backend running first

Everything else depends on the backend being up. See `backend/README.md`
for full instructions; short version:

```bash
cd backend
cp .env.example .env   # fill in real secrets
docker compose up -d --build
python3 seed_products.py --token <admin_jwt_from_login>
```

Then `firmware/README.md` and `detection/README.md` each explain how to
point their respective device at this backend (same `DEVICE_API_KEY`,
same `CART_ID`, backend's LAN IP).

## `legacy/`

`webapp/dashboard/` and `firebase/` are the **original, not-yet-reworked**
pieces from the initial prototype, kept here for reference until
Milestone 5 replaces the dashboard with one built against the new
backend. They are **not wired into the current architecture** — the new
backend does not read from or write to Firebase at all. Don't run the old
dashboard expecting it to reflect live cart/session data; it only talks
to the old Firebase project, which nothing else in this repo touches
anymore.

## `docs/`

- `Phase1_Repository_Analysis.md` — the original prototype's full
  file-by-file analysis, bug list, and architecture findings.
- `Phase2_Hardware_Analysis.md` — component-by-component analysis of the
  purchased hardware.
- `Implementation_Plan.md` — the architecture decisions and milestone
  plan this rebuild is following.

Full project documentation (executive summary, testing docs, contribution
report, final polished README, etc. — Phases 5–7 of the original brief)
comes once Milestones 4–6 are built, so it documents what actually exists
rather than what's planned.
