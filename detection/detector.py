"""
SmartCart - Raspberry Pi Item Detection (Milestone 3 rework)

WHAT CHANGED FROM THE ORIGINAL Detect_Items, AND WHY
--------------------------------------------------------
1. Firebase -> FastAPI backend (see backend_client.py).
   Old: firebase_admin.db, service account key file, all business logic
   (session path, quantity math) duplicated here and in the ESP32
   firmware and the dashboard.
   New: this module only ever calls three backend endpoints
   (GET /sessions/active, GET /products, POST /sessions/{id}/items) --
   all the actual cart/session/quantity logic lives once, in the backend.

2. Per-product cooldown instead of one global cooldown.
   Old bug: `DETECTION_COOLDOWN_SEC` was a single global timer shared by
   every product. Scanning item A then item B within 3 seconds silently
   dropped B.
   New: `self._last_detection_time` is a dict keyed by detection_label --
   each product has its own independent cooldown.

3. Catalog validated against the model's actual class list at startup.
   Old bug: the demo catalog referenced "chips_packet" as a
   detection_label, but the stock MobileNet-SSD model can never output
   that class -- that product was silently, permanently undetectable.
   New: at startup (and on every catalog refresh), every product's
   detection_label is checked against model.CLASSES and a clear warning
   is logged for any product that can never be detected by the currently
   loaded model. This doesn't fix the underlying limitation (still no
   custom-trained retail model -- see model.py docstring) but it turns a
   silent failure into a visible one.

4. Structured logging instead of bare print().

5. Retried, non-fatal backend calls (see backend_client.py) instead of
   letting a single dropped connection kill the whole process.

6. Session discovery via polling, replacing the hardcoded
   `SESSION_ID = "demo_session"` constant -- see backend_client.py and
   the matching change in the ESP32 firmware.

7. Headless-safe preview. Old: `cv2.imshow(...)` unconditionally, which
   throws on a Pi with no display attached. New: gated behind
   `SHOW_PREVIEW` config, off by default (a cart-mounted Pi is normally
   headless in real deployment; the touchscreen shows the shopper-facing
   UI, not a debug camera preview).

8. Graceful shutdown on SIGINT/SIGTERM, camera always released in a
   `finally` block (the original script also did this correctly for
   Ctrl+C, but had no SIGTERM handling, which matters if this process is
   ever run as a systemd service and gets a stop signal).

9. Consecutive-frame-read-failure backoff. Old: `if not ret: continue`
   spins as fast as possible, pegging a CPU core, if the camera stays
   unavailable. New: a short, increasing sleep after repeated failures.
"""
import logging
import signal
import sys
import time

from backend_client import BackendClient
from camera import create_camera_source
from config import load_config
from model import CLASSES, Detector

logger = logging.getLogger("smartcart.detector")

_running = True


def _handle_shutdown_signal(signum, frame):
    global _running
    logger.info("Received shutdown signal (%s), stopping...", signum)
    _running = False


class CatalogCache:
    """Holds the current product catalog, keyed by detection_label, and
    knows how to refresh itself from the backend on a timer."""

    def __init__(self, client: BackendClient, refresh_interval_sec: float):
        self.client = client
        self.refresh_interval_sec = refresh_interval_sec
        self.by_label: dict[str, dict] = {}
        self._last_refresh = 0.0

    def refresh_if_due(self, now: float) -> None:
        if now - self._last_refresh < self.refresh_interval_sec and self.by_label:
            return
        products = self.client.get_products()
        if not products:
            if not self.by_label:
                logger.warning("No product catalog available yet (backend unreachable?)")
            return  # keep previous catalog rather than wiping it on a transient failure

        new_by_label = {}
        for product in products:
            label = product["detection_label"]
            new_by_label[label] = product
            if label not in CLASSES:
                logger.warning(
                    "Product %r (sku=%s) maps to detection_label=%r, which the "
                    "currently loaded model can NEVER output (not in model.CLASSES). "
                    "This product cannot be detected by camera until either the "
                    "catalog mapping or the model changes.",
                    product["name"], product["sku"], label,
                )
        self.by_label = new_by_label
        self._last_refresh = now
        logger.info("Catalog refreshed: %d products", len(self.by_label))


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    logging.getLogger().setLevel(config.log_level)

    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)

    logger.info("Loading detection model...")
    detector = Detector(config.prototxt_path, config.model_path, config.confidence_threshold)

    client = BackendClient(config.backend_base_url, config.device_api_key)
    catalog = CatalogCache(client, config.catalog_refresh_interval_sec)
    catalog.refresh_if_due(time.time())

    logger.info("Starting camera (backend=%s)...", config.camera_backend)
    camera = create_camera_source(config.camera_backend, config.opencv_device_index)

    last_detection_time: dict[str, float] = {}
    active_session_id: int | None = None
    last_session_poll = 0.0
    consecutive_frame_failures = 0
    show_preview = config.show_preview  # local, mutable copy -- config itself is frozen

    try:
        while _running:
            now = time.time()

            catalog.refresh_if_due(now)

            if now - last_session_poll > config.session_poll_interval_sec:
                last_session_poll = now
                new_session_id = client.get_active_session(config.cart_id)
                if new_session_id != active_session_id:
                    logger.info("Active session changed: %s -> %s", active_session_id, new_session_id)
                    active_session_id = new_session_id

            frame = camera.read_frame()
            if frame is None:
                consecutive_frame_failures += 1
                backoff = min(0.1 * consecutive_frame_failures, 2.0)
                logger.warning("Failed to grab frame (x%d), retrying in %.1fs", consecutive_frame_failures, backoff)
                time.sleep(backoff)
                continue
            consecutive_frame_failures = 0

            if active_session_id is not None:
                try:
                    detections = detector.detect(frame)
                except Exception:
                    logger.exception("Detection inference failed on this frame, skipping")
                    detections = []

                for label, confidence in detections:
                    product = catalog.by_label.get(label)
                    if product is None:
                        continue  # not a catalog product (e.g. "person", "chair")

                    last_time = last_detection_time.get(label, 0.0)
                    if now - last_time < config.detection_cooldown_sec:
                        continue  # this specific product's own cooldown, not global

                    if client.add_item(active_session_id, label, confidence):
                        logger.info(
                            "Detected %s (confidence=%.2f) -> added to session %s",
                            product["name"], confidence, active_session_id,
                        )
                        last_detection_time[label] = now

            if show_preview:
                try:
                    import cv2
                    cv2.imshow("SmartCart Camera", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                except Exception:
                    logger.exception("Preview window failed (no display attached?) -- disabling preview")
                    # Don't crash the whole detection loop over a debug preview window.
                    show_preview = False

    finally:
        camera.release()
        if show_preview:
            import cv2
            cv2.destroyAllWindows()
        logger.info("Detection loop stopped, camera released.")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        logger.exception("Fatal error, exiting")
        sys.exit(1)
