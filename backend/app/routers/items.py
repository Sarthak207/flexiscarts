from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas
from app.core.security import require_device_api_key
from app.database import get_db
from app.models import CartItem, CartSession, Product, SessionStatus

router = APIRouter(prefix="/sessions/{session_id}/items", tags=["items"])


@router.post("", response_model=schemas.CartItemOut, status_code=status.HTTP_201_CREATED)
def add_item(
    session_id: int,
    payload: schemas.ItemAdd,
    db: Session = Depends(get_db),
    _device=Depends(require_device_api_key),
):
    """
    Called by the Pi detection module when a product is recognized in
    frame. Fixes two Phase 1 bugs at once:

    1. Read-modify-write race on quantity: the old Detect_Items script did
       `current = ref.get()['quantity']; ref.update({'quantity': current})`
       as two separate, non-atomic Firebase calls, AND it wrote back the
       SAME value instead of incrementing it. Here, the existing-item
       lookup and the quantity update happen inside one DB transaction
       with a row lock (`with_for_update`), so two near-simultaneous
       detections of the same product can't stomp on each other, and the
       quantity is actually incremented.

    2. Price/weight is snapshotted from the catalog at add-time
       (unit_price_snapshot), so a later price change never silently
       alters an in-progress cart's running total.

    Per-product detection cooldown (fixing the old global 3s cooldown that
    could drop a second, different item scanned quickly after a first) is
    handled in the Pi-side detection module, not here -- this endpoint is
    intentionally "dumb": it trusts that whatever calls it already decided
    a detection event is real and cooldown-appropriate. Keeping that
    decision on the Pi side (Milestone 3) rather than in the backend keeps
    this endpoint reusable by future detection strategies (e.g. barcode)
    without backend changes.
    """
    session = db.get(CartSession, session_id)
    if session is None or session.status != SessionStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Session is not active")

    product = (
        db.query(Product)
        .filter(Product.detection_label == payload.detection_label, Product.active.is_(True))
        .first()
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No product mapped to this label")

    existing = (
        db.query(CartItem)
        .filter(CartItem.session_id == session_id, CartItem.product_id == product.id)
        .with_for_update()
        .first()
    )
    if existing is not None:
        existing.quantity += 1
        db.commit()
        db.refresh(existing)
        return existing

    item = CartItem(
        session_id=session_id,
        product_id=product.id,
        quantity=1,
        unit_price_snapshot=product.price,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item(
    session_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    _device=Depends(require_device_api_key),
):
    """
    Handles a shopper taking an item back out of the cart. The old system
    had no concept of item removal at all -- this is new functionality,
    included because the load cell hardware makes "weight went DOWN"
    physically detectable even though wiring that detection into the Pi
    detection module is future-scope work (see README future scope).
    """
    item = db.get(CartItem, item_id)
    if item is None or item.session_id != session_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found in this session")
    if item.quantity > 1:
        item.quantity -= 1
    else:
        db.delete(item)
    db.commit()
