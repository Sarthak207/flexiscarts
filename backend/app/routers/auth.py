from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas
from app.core.security import create_admin_jwt, verify_password
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/admin/login", response_model=schemas.Token)
def admin_login(payload: schemas.AdminLogin, db: Session = Depends(get_db)):
    """
    Replaces the old dashboard's complete absence of a login step.

    Note: admin login uses a username+password (stored as a bcrypt hash on
    the User row, is_admin=True), which is a DIFFERENT credential from a
    shopper's cart-login token -- an admin account is not just "a user
    with is_admin=True and a token", it has an actual password, since
    admin access is a materially higher-privilege action than starting a
    shopping session.
    """
    user = (
        db.query(User)
        .filter(User.mobile == payload.username, User.is_admin.is_(True))
        .first()
    )
    # We reuse the `mobile` column as the admin "username" field to avoid
    # adding a redundant column for the bootstrap admin; a real multi-admin
    # deployment would want a dedicated `username` column instead -- noted
    # here as a schema simplification, not an oversight.
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not verify_password(payload.password, user.token_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    token = create_admin_jwt(subject=user.mobile)
    return schemas.Token(access_token=token)
