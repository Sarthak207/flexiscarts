"""
Auth utilities.

Three distinct trust levels, deliberately kept separate:

  1. Shopper session token (bcrypt-hashed in DB, plaintext shown once) --
     proves "this person is a registered shopper", used only to START a
     session at the cart touchscreen. Not used for anything else
     afterward; the session_id issued at that point is what all
     subsequent item/weight calls are scoped to.

  2. Device API key (single shared secret from config, sent as a header)
     -- proves "this request came from a cart device I own" (the ESP32 or
     the Pi's detection script), not from a random client on the network.
     This directly fixes the Phase 1 finding that NOTHING validated who
     was writing to Firebase.

  3. Admin JWT -- proves "this is an authenticated admin", replacing the
     old dashboard's complete lack of any auth gate.

These are intentionally not unified into one scheme: a compromised device
key should not grant admin access, and vice versa.
"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/admin/login", auto_error=False)


def generate_shopper_token() -> str:
    """Cryptographically-secure token, unlike the old dashboard's
    Math.random()-based 8-character token."""
    return secrets.token_urlsafe(24)


def hash_token(token: str) -> str:
    return pwd_context.hash(token)


def verify_token(token: str, token_hash: str) -> bool:
    return pwd_context.verify(token, token_hash)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_admin_jwt(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def get_current_admin(token: str = Depends(oauth2_scheme)) -> str:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired admin credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_exception
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception


def require_device_api_key(x_device_key: str = Header(...)) -> None:
    """Dependency for ESP32 / Pi detection-module endpoints."""
    if not secrets.compare_digest(x_device_key, settings.device_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device API key",
        )
