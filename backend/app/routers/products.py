from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.core.security import get_current_admin
from app.database import get_db
from app.models import Product

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", response_model=schemas.ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: schemas.ProductCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(get_current_admin),
):
    """
    Replaces manually importing database-structure-example.json by hand
    into the Firebase console -- the catalog is now managed through the
    API (and, in Milestone 5, the admin dashboard UI) instead of requiring
    direct database console access.
    """
    product = Product(**payload.model_dump())
    db.add(product)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "SKU already exists")
    db.refresh(product)
    return product


@router.get("", response_model=list[schemas.ProductOut])
def list_products(db: Session = Depends(get_db)):
    # Deliberately public (no admin dependency): the shopper-facing
    # touchscreen UI needs to read the catalog (e.g. to show product
    # names/prices/images) without needing admin credentials.
    return db.query(Product).filter(Product.active.is_(True)).all()


@router.get("/by-label/{detection_label}", response_model=schemas.ProductOut)
def get_product_by_label(detection_label: str, db: Session = Depends(get_db)):
    """
    Used by the Pi detection module: given a model class label, find the
    matching catalog product. This replaces the old script's in-memory
    dict built once at startup from a full /products dump -- looking it
    up per-detection means catalog changes take effect immediately
    without restarting the detection process.
    """
    product = (
        db.query(Product)
        .filter(Product.detection_label == detection_label, Product.active.is_(True))
        .first()
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No product mapped to this label")
    return product
