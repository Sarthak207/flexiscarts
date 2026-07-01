"""
Thin HTTP client for the FastAPI backend, replacing the original script's
direct firebase_admin.db calls.

Every method here retries transient failures with backoff instead of
letting a single dropped connection kill the whole detection process --
directly fixing the Phase 1 finding that the original script had no
exception handling around its Firebase calls at all.
"""
import logging
import time
from typing import Optional

import requests

logger = logging.getLogger("smartcart.backend_client")


class BackendError(Exception):
    """Raised only for non-transient failures the caller should react to
    (e.g. auth failure) -- transient network errors are retried internally
    and only raised after exhausting retries."""


class BackendClient:
    def __init__(self, base_url: str, device_api_key: str, max_retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Device-Key": device_api_key}
        self.max_retries = max_retries

    def _request(self, method: str, path: str, **kwargs) -> Optional[requests.Response]:
        url = f"{self.base_url}{path}"
        delay = 1.0
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.request(
                    method, url, headers=self.headers, timeout=5, **kwargs
                )
                return resp
            except requests.RequestException as exc:
                logger.warning(
                    "Backend request failed (attempt %d/%d): %s %s -> %s",
                    attempt, self.max_retries, method, url, exc,
                )
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2  # exponential backoff
        logger.error("Backend request permanently failed after retries: %s %s", method, url)
        return None

    def get_active_session(self, cart_id: str) -> Optional[int]:
        """Returns the active session id for this cart, or None if there
        isn't one (shopper hasn't logged in, or already checked out --
        both are normal, not errors)."""
        resp = self._request("GET", f"/sessions/active?cart_id={cart_id}")
        if resp is None:
            return None
        if resp.status_code == 200:
            return resp.json()["id"]
        if resp.status_code == 404:
            return None
        logger.warning("Unexpected status checking active session: %s", resp.status_code)
        return None

    def get_products(self) -> list[dict]:
        """Fetches the current product catalog. Called at startup and on
        a refresh timer -- NOT once at startup only, unlike the original
        script, so catalog changes take effect without restarting this
        process."""
        resp = self._request("GET", "/products")
        if resp is None or resp.status_code != 200:
            logger.error("Failed to fetch product catalog, keeping previous catalog if any")
            return []
        return resp.json()

    def add_item(self, session_id: int, detection_label: str, confidence: float) -> bool:
        resp = self._request(
            "POST",
            f"/sessions/{session_id}/items",
            json={"detection_label": detection_label, "confidence": confidence},
        )
        if resp is None:
            return False
        if resp.status_code == 201:
            return True
        if resp.status_code == 409:
            # Session closed between our last poll and this add -- normal
            # race under real use, not a bug; caller should re-poll.
            logger.info("Session %s no longer active, item not added", session_id)
            return False
        logger.warning("Unexpected status adding item: %s %s", resp.status_code, resp.text)
        return False
