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
    """
    Touch-friendly login code for the cart's 7" touchscreen -- NOT the
    same design goal as a URL-safe API secret.

    This was originally `secrets.token_urlsafe(24)` (32 characters) while
    only Milestone 1's admin-dashboard/API flow existed. Building the
    actual touchscreen UI (Milestone 4) surfaced that a 32-character
    token is realistic to copy-paste but not to type on an on-screen
    keyboard while standing in a store aisle -- so this shortens the
    code, and the login endpoint (see routers/sessions.py) adds rate
    limiting to compensate for the smaller search space.

    8 characters from a 32-symbol unambiguous alphabet (excludes 0/O,
    1/I/L and other easily-confused pairs, since this is read off a
    printed card or a dashboard screen and typed by hand) is
    32^8 ≈ 1.1 x 10^12 possible codes -- combined with a hashed-at-rest
    token (never stored/logged in plaintext) and the rate limiter capping
    guesses to a handful per minute per client, this is a reasonable
    tradeoff for a physical-possession-based login on a closed local
    network, not a public-internet-facing credential. Documented
    explicitly as a deliberate scope decision, not an oversight.
    """
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
    return "".join(secrets.choice(alphabet) for _ in range(8))


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


class LoginRateLimiter:
    """
    In-memory, per-client rate limiter for POST /sessions/start, added
    alongside shortening the shopper token (see generate_shopper_token
    above) -- a shorter, touch-typeable code needs guess-limiting to keep
    brute-forcing impractical.

    Deliberately simple (a dict in process memory, not Redis or a DB
    table): this system runs as a single backend process on a single Pi
    for a single cart, so there is exactly one process whose memory needs
    to hold this state. Documented here as a scale limitation rather than
    hidden: if this were ever split across multiple backend processes/
    replicas, this in-memory dict would need to move to a shared store
    (Redis is the standard choice) since each process would otherwise
    track attempts independently and the limit could be trivially
    bypassed by hitting a different replica.
    """

    def __init__(self, max_attempts: int = 5, window_seconds: float = 60.0):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = {}

    def check_and_record(self, client_id: str) -> bool:
        """Returns True if this attempt is allowed, False if rate-limited.
        Always records the attempt (callers should only call this once
        per real login attempt, not on every retry-eligible check)."""
        import time

        now = time.time()
        recent = [t for t in self._attempts.get(client_id, []) if now - t < self.window_seconds]
        allowed = len(recent) < self.max_attempts
        recent.append(now)
        self._attempts[client_id] = recent
        return allowed


login_rate_limiter = LoginRateLimiter()
