import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.security import hash_password
from app.database import Base, SessionLocal, engine
from app.models import User
from app.routers import auth, items, products, sessions, users, weight

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("smartcart")

app = FastAPI(title="SmartCart API", version="1.0.0")

# The shopper touchscreen UI and the admin dashboard both run as separate
# web frontends talking to this API over HTTP -- CORS needs to allow that.
# Locked to same-origin by default in production deployments; open here
# for local dev/demo since everything runs on one Pi 4 on a closed network.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(products.router)
app.include_router(sessions.router)
app.include_router(items.router)
app.include_router(weight.router)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    _bootstrap_admin()
    logger.info("SmartCart API started")


def _bootstrap_admin():
    """
    Ensures there is always at least one working admin login, so the
    system is never accidentally locked out after a fresh deploy. Only
    creates the account if NO admin user exists yet -- never overwrites
    an existing admin's password on restart.
    """
    settings = get_settings()
    db = SessionLocal()
    try:
        existing_admin = db.query(User).filter(User.is_admin.is_(True)).first()
        if existing_admin is not None:
            return
        admin = User(
            name="Administrator",
            mobile=settings.bootstrap_admin_username,
            token_hash=hash_password(settings.bootstrap_admin_password),
            is_admin=True,
            active=True,
        )
        db.add(admin)
        db.commit()
        logger.warning(
            "Bootstrap admin account created (username=%s). "
            "Change bootstrap_admin_password in your .env before any real deployment.",
            settings.bootstrap_admin_username,
        )
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}
