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
    return db.query(User).order_by(User.created_at.desc()).all()


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
