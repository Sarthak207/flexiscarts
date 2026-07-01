from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas
from app.core.security import require_device_api_key
from app.database import get_db
from app.models import CartItem, CartSession, SessionStatus, WeightEvent

router = APIRouter(prefix="/sessions/{session_id}/weight", tags=["weight"])

# How close (grams) a weight delta must be to a product's expected weight
# to count as verified. Real load cells + a single-point cart mount (see
# Phase 2 hardware analysis) have real mechanical noise, so this is a
# tolerance band, not exact-match -- tune this value against real
# measurements once the hardware is assembled, this is a starting estimate.
WEIGHT_TOLERANCE_GRAMS = 15.0


@router.post("", response_model=schemas.WeightEventOut, status_code=status.HTTP_201_CREATED)
def report_weight(
    session_id: int,
    payload: schemas.WeightReading,
    db: Session = Depends(get_db),
    _device=Depends(require_device_api_key),
):
    """
    Called by the ESP32 roughly once per second.

    Fixes the Phase 1 architecture bug where the firmware compared TOTAL
    cart weight against a SINGLE item's expected weight -- correct only
    for the very first item ever added, wrong for every item after that.

    Here, we instead:
      1. Look up the previous weight_events row for this session (if any)
         to compute a DELTA, not a total.
      2. Find the most recently added, not-yet-verified cart item.
      3. Check whether the delta is within tolerance of THAT item's
         expected weight.

    This is still a simplification worth stating plainly: if two items are
    added in quick succession before a stable weight reading lands between
    them, the delta will reflect both items summed together and won't
    cleanly match either one's expected weight alone. A more robust
    version would debounce for a stable reading between each detection
    event before accepting a weight sample -- documented as a concrete
    Milestone 3 firmware improvement, not implemented as a false claim of
    full robustness here.
    """
    session = db.get(CartSession, session_id)
    if session is None or session.status != SessionStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Session is not active")

    last_event = (
        db.query(WeightEvent)
        .filter(WeightEvent.session_id == session_id)
        .order_by(WeightEvent.created_at.desc())
        .first()
    )
    previous_weight = float(last_event.raw_weight_grams) if last_event else 0.0
    delta = payload.raw_weight_grams - previous_weight

    unverified_item = (
        db.query(CartItem)
        .filter(CartItem.session_id == session_id, CartItem.weight_verified.is_(False))
        .order_by(CartItem.added_at.desc())
        .first()
    )

    verified = False
    matched_item_id = None
    if unverified_item is not None:
        expected = float(unverified_item.product.expected_weight_grams)
        if abs(delta - expected) <= WEIGHT_TOLERANCE_GRAMS:
            verified = True
            matched_item_id = unverified_item.id
            unverified_item.weight_verified = True

    event = WeightEvent(
        session_id=session_id,
        raw_weight_grams=payload.raw_weight_grams,
        delta_grams=delta,
        matched_item_id=matched_item_id,
        verified=verified,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
