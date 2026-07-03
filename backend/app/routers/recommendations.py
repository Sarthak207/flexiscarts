"""
Recommendation endpoints (Milestone 6).

Scope decision, stated up front: this implements the two recommendation
features that are honestly supportable by the data this system actually
collects -- frequently-bought-together (co-occurrence across completed
carts) and personalized "buy again" suggestions (a shopper's own repeat-
purchase pattern). Both are plain SQL aggregations over real purchase
history, not a trained ML model -- there isn't remotely enough data from
a single-cart academic pilot to train anything meaningful, and pretending
otherwise would be exactly the kind of overclaiming this whole rebuild
has been trying to avoid (see Phase 1 analysis: the original README
promised recommendations with zero implementation behind it at all).

Both endpoints are honest about the cold-start problem: a brand new
catalog or a shopper with no purchase history yet gets a clearly-labeled
"trending" or "not enough data" response instead of an empty list that
looks like a bug, or fabricated suggestions.

Only CLOSED sessions feed these queries -- an in-progress cart never
counts towards its own recommendations (that would be circular: "people
who bought this also bought the thing you're currently in the middle of
buying"), and only completed purchases represent confirmed co-purchase
behavior rather than an abandoned or still-shopping cart.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.models import CartItem, CartSession, Product, SessionStatus

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

DEFAULT_LIMIT = 3


@router.get("/frequently-bought-with/{product_id}", response_model=schemas.RecommendationResponse)
def frequently_bought_with(product_id: int, limit: int = DEFAULT_LIMIT, db: Session = Depends(get_db)):
    """
    "Other shoppers who bought X also bought..." -- co-occurrence counted
    across all CLOSED sessions that contained product_id.

    Deliberately public (no admin/device auth): the kiosk UI calls this
    directly while a shopper is mid-trip to show a lightweight suggestion
    panel, the same trust level as GET /products.
    """
    closed_session_ids_with_product = (
        db.query(CartItem.session_id)
        .join(CartSession, CartItem.session_id == CartSession.id)
        .filter(CartItem.product_id == product_id, CartSession.status == SessionStatus.closed)
        .subquery()
    )

    co_occurrences = (
        db.query(CartItem.product_id, func.count(func.distinct(CartItem.session_id)).label("co_count"))
        .filter(
            CartItem.session_id.in_(select(closed_session_ids_with_product.c.session_id)),
            CartItem.product_id != product_id,
        )
        .group_by(CartItem.product_id)
        .order_by(func.count(func.distinct(CartItem.session_id)).desc())
        .limit(limit)
        .all()
    )

    if not co_occurrences:
        return schemas.RecommendationResponse(basis="not_enough_data", items=[])

    items = _hydrate_recommendations(db, co_occurrences)
    return schemas.RecommendationResponse(basis="frequently_bought_together", items=items)


@router.get("/for-shopper/{session_id}", response_model=schemas.RecommendationResponse)
def for_shopper(session_id: int, limit: int = DEFAULT_LIMIT, db: Session = Depends(get_db)):
    """
    Personalized "you usually buy" suggestions, based on the logged-in
    shopper's own past CLOSED sessions. Falls back to store-wide trending
    products (clearly labeled, not silently passed off as personalized)
    if this shopper has no purchase history yet -- the honest cold-start
    behavior called out in the Implementation Plan rather than an
    unlabeled, misleading "personalized" list with generic data in it.

    Excludes products already in the shopper's CURRENT (active) cart --
    no point suggesting something they've already picked up this trip.
    """
    session = db.get(CartSession, session_id)
    if session is None:
        return schemas.RecommendationResponse(basis="not_enough_data", items=[])

    current_cart_product_ids = {
        row[0]
        for row in db.query(CartItem.product_id).filter(CartItem.session_id == session_id).all()
    }

    personalized_items: list[schemas.RecommendedProduct] = []
    if session.user_id is not None:
        past_purchases = (
            db.query(CartItem.product_id, func.sum(CartItem.quantity).label("total_qty"))
            .join(CartSession, CartItem.session_id == CartSession.id)
            .filter(
                CartSession.user_id == session.user_id,
                CartSession.status == SessionStatus.closed,
                CartSession.id != session_id,
            )
            .group_by(CartItem.product_id)
            .order_by(func.sum(CartItem.quantity).desc())
            .limit(limit + len(current_cart_product_ids))  # pad, since we filter some out below
            .all()
        )
        candidates = [row for row in past_purchases if row[0] not in current_cart_product_ids][:limit]
        if candidates:
            personalized_items = _hydrate_recommendations(db, candidates)

    if personalized_items:
        return schemas.RecommendationResponse(basis="your_past_purchases", items=personalized_items)

    # Cold start: this shopper has no (usable) purchase history yet.
    # Fall back to store-wide trending products, still excluding what's
    # already in their current cart.
    trending = (
        db.query(CartItem.product_id, func.sum(CartItem.quantity).label("total_qty"))
        .join(CartSession, CartItem.session_id == CartSession.id)
        .filter(CartSession.status == SessionStatus.closed)
        .group_by(CartItem.product_id)
        .order_by(func.sum(CartItem.quantity).desc())
        .limit(limit + len(current_cart_product_ids))
        .all()
    )
    trending_candidates = [row for row in trending if row[0] not in current_cart_product_ids][:limit]
    if not trending_candidates:
        return schemas.RecommendationResponse(basis="not_enough_data", items=[])

    return schemas.RecommendationResponse(
        basis="trending", items=_hydrate_recommendations(db, trending_candidates)
    )


def _hydrate_recommendations(db: Session, rows: list[tuple[int, int]]) -> list[schemas.RecommendedProduct]:
    """rows: [(product_id, score), ...] -> full RecommendedProduct objects,
    skipping any product that's since been deactivated (a co-purchase
    count for a discontinued product isn't useful to show)."""
    results = []
    for product_id, score in rows:
        product = db.get(Product, product_id)
        if product is None or not product.active:
            continue
        results.append(
            schemas.RecommendedProduct(
                product_id=product.id, sku=product.sku, name=product.name,
                price=float(product.price), score=int(score),
            )
        )
    return results
