from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import schemas
from app.core.security import get_current_admin, login_rate_limiter, verify_token
from app.database import get_db
from app.models import CartItem, CartSession, SessionStatus, User

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[schemas.SessionListOut])
def list_sessions(
    status_filter: SessionStatus | None = None,
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    """
    Admin-only overview for the dashboard (Milestone 5) -- lets staff see
    every cart's status at a glance instead of needing a session id to
    look anything up. Nothing in the original prototype had ANY session
    visibility at all; the old dashboard only ever showed /users.

    NOTE on N+1 queries: this computes item_count/total per session with
    a separate query per session rather than one aggregate SQL query.
    Documented as an acceptable simplification at this project's actual
    scale (a handful of sessions per day for a single-cart academic
    build, not thousands) -- a real high-traffic deployment would want a
    single query with a SQL SUM/COUNT and a GROUP BY instead, noted here
    as a concrete optimization rather than silently living with it.
    """
    query = db.query(CartSession)
    if status_filter is not None:
        query = query.filter(CartSession.status == status_filter)
    sessions = query.order_by(CartSession.started_at.desc()).limit(200).all()

    results = []
    for session in sessions:
        items = db.query(CartItem).filter(CartItem.session_id == session.id).all()
        total = sum(float(i.unit_price_snapshot) * i.quantity for i in items)
        results.append(
            schemas.SessionListOut(
                id=session.id,
                cart_id=session.cart_id,
                status=session.status,
                shopper_name=session.user.name if session.user else None,
                item_count=sum(i.quantity for i in items),
                total=round(total, 2),
                started_at=session.started_at,
                ended_at=session.ended_at,
            )
        )
    return results


@router.post("/start", response_model=schemas.SessionOut, status_code=status.HTTP_201_CREATED)
def start_session(payload: schemas.SessionStart, request: Request, db: Session = Depends(get_db)):
    """
    Real session creation, replacing the hardcoded global "demo_session"
    path every device used to share (Phase 1 finding: the whole system
    could only ever support one cart, system-wide, ever).

    Flow: shopper enters/scans their token on the cart touchscreen -> we
    verify it against the bcrypt hash on file -> a new session row is
    created and its id becomes the scope for every item/weight event that
    follows, until checkout. Multiple carts running concurrently each get
    their own session id and don't interfere with each other.

    Rate-limited by client IP (see core/security.py LoginRateLimiter) --
    the login code is short enough to type on a touchscreen (8 chars,
    see generate_shopper_token), which means it also needs guess-limiting
    to stay brute-force-resistant.
    """
    client_id = request.client.host if request.client else "unknown"
    if not login_rate_limiter.check_and_record(client_id):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many login attempts. Please wait a minute and try again.",
        )

    candidates = db.query(User).filter(User.active.is_(True)).all()
    matched_user = None
    for user in candidates:
        if verify_token(payload.token, user.token_hash):
            matched_user = user
            break
    if matched_user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or inactive shopper token")

    session = CartSession(user_id=matched_user.id, cart_id=payload.cart_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/active", response_model=schemas.SessionOut)
def get_active_session(cart_id: str = "cart-01", db: Session = Depends(get_db)):
    """
    Lets a cart device (ESP32, Pi detection module) discover the current
    active session for its physical cart without that session's ID ever
    being hardcoded anywhere in firmware -- this is what replaces the old
    firmware's `currentSessionId = "demo_session"` constant. A device
    polls this on a timer; once a shopper logs in via /sessions/start,
    the very next poll picks up the new session automatically, and a poll
    after checkout correctly reports "no active session" (404) again.

    NOTE: this endpoint is registered ABOVE /{session_id} in this file
    deliberately -- Starlette/FastAPI match routes in registration order,
    so the literal "/active" path must be declared before the "/{session_id}"
    int-typed path or requests to /sessions/active would instead be routed
    to get_session_summary and fail path-parameter validation.
    """
    session = (
        db.query(CartSession)
        .filter(CartSession.cart_id == cart_id, CartSession.status == SessionStatus.active)
        .order_by(CartSession.started_at.desc())
        .first()
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active session for this cart")
    return session


@router.get("/{session_id}", response_model=schemas.CartSummary)
def get_session_summary(session_id: int, db: Session = Depends(get_db)):
    session = db.get(CartSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    items = db.query(CartItem).filter(CartItem.session_id == session_id).all()
    total = sum(float(i.unit_price_snapshot) * i.quantity for i in items)
    return schemas.CartSummary(
        session_id=session.id, status=session.status, items=items, total=round(total, 2)
    )


@router.post("/{session_id}/close", response_model=schemas.Receipt)
def close_session(session_id: int, db: Session = Depends(get_db)):
    """
    Checkout. NOTE: this computes and returns an itemized bill total but
    does NOT process payment -- see the README/Implementation Plan for why
    real payment-gateway integration is explicitly out of scope for this
    academic build (requires a merchant account, PCI-relevant handling,
    and a live payment provider, none of which are things to fake for a
    demo). This endpoint is the seam a real payment integration would
    plug into.
    """
    session = db.get(CartSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if session.status != SessionStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Session is not active")

    from datetime import datetime, timezone

    items = db.query(CartItem).filter(CartItem.session_id == session_id).all()
    lines = [
        schemas.ReceiptLine(
            product_name=item.product.name,
            quantity=item.quantity,
            unit_price=float(item.unit_price_snapshot),
            line_total=round(float(item.unit_price_snapshot) * item.quantity, 2),
        )
        for item in items
    ]
    total = round(sum(line.line_total for line in lines), 2)

    session.status = SessionStatus.closed
    session.ended_at = datetime.now(timezone.utc)
    db.commit()

    return schemas.Receipt(
        session_id=session.id, lines=lines, total=total, closed_at=session.ended_at
    )
