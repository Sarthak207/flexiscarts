"""
Store-performance analytics for the admin dashboard (Milestone 6).

Same honesty principle as recommendations.py: plain SQL aggregation over
real closed-session data, nothing fabricated or projected. If there are
zero closed sessions yet, every number here is correctly zero rather than
a placeholder.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import schemas
from app.core.security import get_current_admin
from app.database import get_db
from app.models import CartItem, CartSession, Product, SessionStatus

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=schemas.AnalyticsSummary)
def analytics_summary(
    top_n: int = 5, db: Session = Depends(get_db), _admin: str = Depends(get_current_admin)
):
    closed_sessions = db.query(CartSession).filter(CartSession.status == SessionStatus.closed).all()
    total_closed_sessions = len(closed_sessions)

    if total_closed_sessions == 0:
        return schemas.AnalyticsSummary(
            total_closed_sessions=0, total_revenue=0.0, average_basket_value=0.0,
            unique_shoppers=0, top_products=[],
        )

    closed_ids = [s.id for s in closed_sessions]
    items = db.query(CartItem).filter(CartItem.session_id.in_(closed_ids)).all()

    total_revenue = round(sum(float(i.unit_price_snapshot) * i.quantity for i in items), 2)
    average_basket_value = round(total_revenue / total_closed_sessions, 2)
    unique_shoppers = len({s.user_id for s in closed_sessions if s.user_id is not None})

    per_product: dict[int, dict] = {}
    for item in items:
        entry = per_product.setdefault(item.product_id, {"quantity_sold": 0, "revenue": 0.0})
        entry["quantity_sold"] += item.quantity
        entry["revenue"] += float(item.unit_price_snapshot) * item.quantity

    top_product_ids = sorted(per_product, key=lambda pid: per_product[pid]["quantity_sold"], reverse=True)[:top_n]
    top_products = []
    for pid in top_product_ids:
        product = db.get(Product, pid)
        if product is None:
            continue
        top_products.append(
            schemas.TopProduct(
                product_id=pid, name=product.name,
                quantity_sold=per_product[pid]["quantity_sold"],
                revenue=round(per_product[pid]["revenue"], 2),
            )
        )

    return schemas.AnalyticsSummary(
        total_closed_sessions=total_closed_sessions,
        total_revenue=total_revenue,
        average_basket_value=average_basket_value,
        unique_shoppers=unique_shoppers,
        top_products=top_products,
    )
