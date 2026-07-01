# SmartCart Detection Module (Milestone 3)

Camera-based product detection, reworked to talk to the FastAPI backend
instead of Firebase. Runs on the Raspberry Pi 4.

## Setup

```bash
cd detection
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: BACKEND_HOST (the Pi's own IP if the backend runs there too,
# or localhost), DEVICE_API_KEY (must match the backend's .env), CART_ID.
```

### On the actual Raspberry Pi (Pi Camera Module V2)

`picamera2` is a system package tied to `libcamera`, not something pip can
install reliably — install it via apt, then set `CAMERA_BACKEND=picamera2`
in `.env`:

```bash
sudo apt install -y python3-picamera2
```

### On a laptop / with a USB webcam

Leave `CAMERA_BACKEND=opencv` (the default) — no extra system packages
needed.

### Model files

Same stock MobileNet-SSD as the original prototype (no custom-trained
retail model — see `model.py` for why, and the Implementation Plan for
the honest scoping decision behind that):

```bash
mkdir -p models
cd models
wget https://github.com/chuanqi305/MobileNet-SSD/raw/master/mobilenet_iter_73000.caffemodel
wget https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/deploy.prototxt
```

## Running

```bash
python3 detector.py
```

Ctrl+C (or a `systemctl stop` if run as a service) shuts it down cleanly —
the camera is always released, even on a crash mid-loop.

## What to expect in the logs

- On startup, and every 30s (`CATALOG_REFRESH_INTERVAL_SEC`), it refreshes
  the product catalog from the backend and **warns loudly about any
  catalog product whose `detection_label` the loaded model can never
  output** — this is the direct fix for the original prototype's silent
  "chips_packet can never be detected" bug. If you see this warning, the
  product's `detection_label` in the catalog needs to be one of the
  classes listed in `model.py`'s `CLASSES` (or you need a different/
  retrained model).
- Every 5s (`SESSION_POLL_INTERVAL_SEC`), it checks whether a shopper is
  currently checked in for `CART_ID`. No detections are sent to the
  backend while there's no active session.
- Each detected, catalog-matched product is logged with its confidence
  score when successfully added to the cart.

## Known limitations (stated plainly)

- Still the stock 20-class MobileNet-SSD — realistically only detects
  products mapped to `bottle` (or other COCO/VOC classes that happen to
  match a real product) out of the box. Expanding real product coverage
  needs either a custom-trained model on your own product image dataset,
  or a different sensing approach (e.g. barcode) — both explicitly
  descoped for this milestone (see Implementation Plan).
- No object tracking — the same physical item re-entering frame within
  its cooldown window won't double-add, but leaving the cart and coming
  back after the cooldown expires will re-trigger a detection with no way
  to distinguish "same item picked back up" from "a second one added."
  Documented future-scope item, not implemented here.
