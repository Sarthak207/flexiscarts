from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.core.security import generate_shopper_token, get_current_admin, hash_token
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=schemas.UserCreated, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: schemas.UserCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    """
    Replaces the old dashboard's generateToken() (Math.random(), 8 chars,
    stored in plaintext). The plaintext token is returned ONCE here and
    never stored -- only its bcrypt hash is persisted, so even a full
    database leak doesn't hand out working shopper login tokens.
    """
    raw_token = generate_shopper_token()
    user = User(
        name=payload.name,
        mobile=payload.mobile,
        token_hash=hash_token(raw_token),
        is_admin=payload.is_admin,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Mobile number already registered")
    db.refresh(user)

    return schemas.UserCreated(id=user.id, name=user.name, mobile=user.mobile, token=raw_token)


@router.get("", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db), _admin: str = Depends(get_current_admin)):
    """
    Lists SHOPPERS specifically (is_admin=False), not every row in the
    users table. Found via testing the admin dashboard's Shoppers panel
    end to end: without this filter, the bootstrap admin account (and any
    other admin) shows up in a table meant for managing shopper cart-login
    codes, with a "Deactivate" button that could lock an admin out of
    their own account by mistake. Admin account management isn't a
    feature this build has a dedicated UI for -- there's exactly one
    bootstrap admin, created automatically on first startup (see
    main.py._bootstrap_admin), and adding/removing additional admins is
    documented as future scope rather than exposed here.
    """
    return (
        db.query(User)
        .filter(User.is_admin.is_(False))
        .order_by(User.created_at.desc())
        .all()
    )


@router.patch("/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    payload: schemas.UserUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if payload.active is not None:
        user.active = payload.active
    db.commit()
    db.refresh(user)
    return user
