from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import SessionStatus


# ---------- Users ----------

class UserCreate(BaseModel):
    name: str
    mobile: str
    is_admin: bool = False


class UserCreated(BaseModel):
    """Returned exactly once, at creation -- the only time the plaintext
    token is ever visible. It cannot be retrieved again afterward."""

    id: int
    name: str
    mobile: str
    token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    mobile: str
    is_admin: bool
    active: bool
    created_at: datetime


class UserUpdate(BaseModel):
    active: bool | None = None


# ---------- Products ----------

class ProductCreate(BaseModel):
    sku: str
    name: str
    price: float
    category: str = "uncategorized"
    expected_weight_grams: float
    detection_label: str


class ProductUpdate(BaseModel):
    name: str | None = None
    price: float | None = None
    category: str | None = None
    expected_weight_grams: float | None = None
    detection_label: str | None = None
    active: bool | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sku: str
    name: str
    price: float
    category: str
    expected_weight_grams: float
    detection_label: str
    active: bool


# ---------- Sessions ----------

class SessionStart(BaseModel):
    token: str
    cart_id: str = "cart-01"


class SessionListOut(BaseModel):
    """Summary shape for the admin dashboard's session list -- includes
    denormalized shopper name and a computed item_count/total instead of
    making the dashboard fetch every session's full item list just to
    show an overview table."""

    id: int
    cart_id: str
    status: SessionStatus
    shopper_name: str | None
    item_count: int
    total: float
    started_at: datetime
    ended_at: datetime | None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None
    cart_id: str
    status: SessionStatus
    started_at: datetime
    ended_at: datetime | None


# ---------- Cart items ----------

class ItemAdd(BaseModel):
    """Sent by the Pi detection module when a product is recognized."""

    detection_label: str
    confidence: float


class CartItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    product_name: str
    quantity: int
    unit_price_snapshot: float
    weight_verified: bool
    added_at: datetime


class CartSummary(BaseModel):
    session_id: int
    status: SessionStatus
    items: list[CartItemOut]
    total: float


# ---------- Weight ----------

class WeightReading(BaseModel):
    """Sent by the ESP32 roughly once per second."""

    raw_weight_grams: float


class WeightEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    raw_weight_grams: float
    delta_grams: float
    verified: bool
    created_at: datetime


# ---------- Recommendations ----------

class RecommendedProduct(BaseModel):
    product_id: int
    sku: str
    name: str
    price: float
    score: int  # co-purchase count or personal purchase count, basis-dependent


class RecommendationResponse(BaseModel):
    basis: str  # "frequently_bought_together" | "your_past_purchases" | "trending" | "not_enough_data"
    items: list[RecommendedProduct]


# ---------- Analytics ----------

class TopProduct(BaseModel):
    product_id: int
    name: str
    quantity_sold: int
    revenue: float


class AnalyticsSummary(BaseModel):
    total_closed_sessions: int
    total_revenue: float
    average_basket_value: float
    unique_shoppers: int
    top_products: list[TopProduct]


# ---------- Auth ----------

class AdminLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Receipt ----------

class ReceiptLine(BaseModel):
    product_name: str
    quantity: int
    unit_price: float
    line_total: float


class Receipt(BaseModel):
    session_id: int
    lines: list[ReceiptLine]
    total: float
    closed_at: datetime | None
