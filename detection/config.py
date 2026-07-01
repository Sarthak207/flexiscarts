"""
Configuration, loaded from environment variables (see .env.example).

Why: the original Detect_Items had SERVICE_ACCOUNT_PATH, FIREBASE_DATABASE_URL,
SESSION_ID, model paths, and the confidence threshold all as hardcoded
module-level constants -- changing any of them meant editing source. Here,
everything operationally variable comes from the environment, and the
module itself has no secrets in it at all (device_api_key comes from env,
same as the ESP32 firmware's secrets.h and the backend's .env).
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    backend_host: str
    backend_port: int
    device_api_key: str
    cart_id: str

    camera_backend: str  # "picamera2" or "opencv"
    opencv_device_index: int
    show_preview: bool

    prototxt_path: str
    model_path: str
    confidence_threshold: float

    detection_cooldown_sec: float
    session_poll_interval_sec: float
    catalog_refresh_interval_sec: float

    log_level: str

    @property
    def backend_base_url(self) -> str:
        return f"http://{self.backend_host}:{self.backend_port}"


def load_config() -> Config:
    return Config(
        backend_host=os.environ.get("BACKEND_HOST", "localhost"),
        backend_port=int(os.environ.get("BACKEND_PORT", "8000")),
        device_api_key=os.environ["DEVICE_API_KEY"],  # required, no insecure default
        cart_id=os.environ.get("CART_ID", "cart-01"),
        camera_backend=os.environ.get("CAMERA_BACKEND", "opencv"),
        opencv_device_index=int(os.environ.get("OPENCV_DEVICE_INDEX", "0")),
        show_preview=os.environ.get("SHOW_PREVIEW", "false").lower() == "true",
        prototxt_path=os.environ.get("PROTOTXT_PATH", "models/deploy.prototxt"),
        model_path=os.environ.get("MODEL_PATH", "models/mobilenet_iter_73000.caffemodel"),
        confidence_threshold=float(os.environ.get("CONFIDENCE_THRESHOLD", "0.5")),
        detection_cooldown_sec=float(os.environ.get("DETECTION_COOLDOWN_SEC", "3.0")),
        session_poll_interval_sec=float(os.environ.get("SESSION_POLL_INTERVAL_SEC", "5.0")),
        catalog_refresh_interval_sec=float(
            os.environ.get("CATALOG_REFRESH_INTERVAL_SEC", "30.0")
        ),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
