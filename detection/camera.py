"""
Camera abstraction.

Why this exists: the original script used `cv2.VideoCapture(0)`
unconditionally, which is the correct call for a USB webcam but is not
guaranteed to work for the Pi Camera Module V2 (a MIPI CSI camera) on
every Raspberry Pi OS version -- see the Phase 2 hardware analysis. This
module makes the camera backend an explicit config choice
(CAMERA_BACKEND=picamera2|opencv) instead of a silent assumption, so
behavior is predictable rather than depending on OS-version-specific V4L2
compatibility shims.

Both backends expose the same tiny interface (`read_frame`, `release`) so
the rest of the detection code doesn't need to know which one is active.
"""
import logging
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

logger = logging.getLogger("smartcart.camera")


class CameraSource(ABC):
    @abstractmethod
    def read_frame(self) -> Optional[np.ndarray]:
        """Returns a BGR frame (OpenCV convention), or None on failure."""

    @abstractmethod
    def release(self) -> None:
        ...


class OpenCVCameraSource(CameraSource):
    """USB webcam, or a Pi Camera accessed through the V4L2 compatibility
    layer where available. Good for laptop development regardless of
    what the deployed hardware ends up being."""

    def __init__(self, device_index: int = 0):
        import cv2

        self._cv2 = cv2
        self.cap = cv2.VideoCapture(device_index)
        if not self.cap.isOpened():
            raise RuntimeError(
                f"Could not open camera at index {device_index}. "
                "Check connection/permissions, or set CAMERA_BACKEND=picamera2 "
                "if this is a Raspberry Pi with a CSI camera."
            )

    def read_frame(self) -> Optional[np.ndarray]:
        ret, frame = self.cap.read()
        if not ret:
            return None
        return frame

    def release(self) -> None:
        self.cap.release()


class PiCamera2Source(CameraSource):
    """Native CSI capture via picamera2/libcamera -- the officially
    supported path for the Pi Camera Module V2 on current Raspberry Pi OS.
    Only importable on an actual Raspberry Pi with libcamera installed
    (see requirements.txt / README for why this isn't a pip dependency)."""

    def __init__(self):
        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise RuntimeError(
                "picamera2 is not installed. On the Raspberry Pi, install it via apt "
                "(sudo apt install -y python3-picamera2), not pip -- see README.md. "
                "If you're developing on a laptop without a CSI camera, set "
                "CAMERA_BACKEND=opencv in your .env instead."
            ) from exc

        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(
            main={"format": "BGR888", "size": (640, 480)}
        )
        self.picam2.configure(config)
        self.picam2.start()
        logger.info("Pi Camera (CSI) started via picamera2.")

    def read_frame(self) -> Optional[np.ndarray]:
        try:
            return self.picam2.capture_array()
        except Exception as exc:  # picamera2 can raise various backend errors
            logger.warning("Failed to capture frame from Pi Camera: %s", exc)
            return None

    def release(self) -> None:
        self.picam2.stop()


def create_camera_source(backend: str, opencv_device_index: int = 0) -> CameraSource:
    if backend == "picamera2":
        return PiCamera2Source()
    if backend == "opencv":
        return OpenCVCameraSource(opencv_device_index)
    raise ValueError(f"Unknown CAMERA_BACKEND: {backend!r} (expected 'picamera2' or 'opencv')")
