"""
Centralized configuration, loaded from environment variables (see .env.example).

Why: Phase 1 found credentials hardcoded directly in the ESP32 firmware source
and the Firebase config embedded in client-side JS. Nothing in this backend
should ever hardcode a secret in source code -- everything sensitive comes
from the environment, which in turn comes from a .env file that is NOT
committed to git (see .gitignore).
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Postgres connection
    database_url: str = "postgresql+psycopg2://smartcart:smartcart@db:5432/smartcart"

    # JWT for admin dashboard auth
    jwt_secret_key: str = "CHANGE_ME_IN_ENV"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 8  # 8 hour admin session

    # Shared secret for trusted on-cart devices (ESP32 firmware, Pi detection
    # script). These are NOT end-user credentials -- they identify "this is a
    # cart device I own", separate from the per-shopper session tokens below.
    # In a larger deployment this would be per-device, issued at provisioning
    # time; a single shared key is a documented, reasonable simplification
    # for a single-cart academic prototype.
    device_api_key: str = "CHANGE_ME_IN_ENV"

    # First admin account, created automatically on first startup if the
    # users table is empty, so there's always a way in.
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "CHANGE_ME_IN_ENV"


@lru_cache
def get_settings() -> Settings:
    return Settings()
