"""
Relational schema replacing the old Firebase RTDB tree
(firebase/database-structure-example.json).

Mapping from old -> new, and why each change was made:

  /products/{key}              -> products table
      Old: flat key->object map, no id/type safety, no history.
      New: real table with a surrogate integer PK, so a product can be
      renamed/re-priced without breaking every reference to it, and so
      cart_items can snapshot the price *at time of purchase* (see below)
      instead of always pointing at today's live price.

  /sessions/demo_session        -> sessions table (one row per cart run,
                                    not a single hardcoded global session)
      Old: a single hardcoded path shared by every device, system-wide --
      the system could only ever support one active cart, ever.
      New: sessions.id is a real primary key; a session is created when a
      shopper authenticates at the cart (POST /sessions/start) and closed
      at checkout. Multiple carts / concurrent sessions become possible
      without any code change, only more hardware.

  /sessions/.../items/{key}     -> cart_items table
      Old: quantity was read-then-written with no transaction (race
      condition, see Phase 1 analysis) and never actually incremented.
      New: cart_items has its own PK and a proper quantity column updated
      inside a single DB transaction (see routers/items.py), which
      Postgres handles atomically -- no read-modify-write race.

  /sessions/.../cartWeight,
  /sessions/.../lastDetectedProduct/weightVerified
                                 -> weight_events table
      Old: verification compared TOTAL cart weight against a SINGLE
      item's expected weight -- only ever correct for the first item
      added (a real bug identified in Phase 1).
      New: each weight_events row stores the delta since the previous
      reading, which is what actually should be compared against the
      most-recently-added item's expected weight. History is kept
      instead of being overwritten every second, which also gives an
      audit trail for post-hoc debugging of misreads.

  /users/{id}                   -> users table
      Old: plaintext, non-expiring token stored directly in the DB node.
      New: token is stored as a bcrypt HASH (token_hash), never
      recoverable in plaintext from the database -- mirrors how
      passwords should be stored, applied to cart-login tokens too.
"""
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionStatus(str, enum.Enum):
    active = "active"
    closed = "closed"
    abandoned = "abandoned"


class User(Base):
    """A registered shopper who can log in at the cart with a token."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    mobile: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    # bcrypt hash of the shopper's login token. The plaintext token is shown
    # ONCE at creation time (admin dashboard) and never stored or logged.
    token_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sessions: Mapped[list["CartSession"]] = relationship(back_populates="user")


class Product(Base):
    """Product catalog -- replaces the manually-imported /products JSON."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    category: Mapped[str] = mapped_column(String(80), default="uncategorized")
    # Grams. Used by the ESP32-side delta-weight verification.
    expected_weight_grams: Mapped[float] = mapped_column(Numeric(10, 2))
    # The detection model's class label this product maps to (camera-only
    # detection, no barcode fallback in this build -- see Phase 3 scoping).
    detection_label: Mapped[str] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CartSession(Base):
    """One row per cart run, from shopper login to checkout/abandonment."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cart_id: Mapped[str] = mapped_column(String(64), default="cart-01")
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus), default=SessionStatus.active
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User | None] = relationship(back_populates="sessions")
    items: Mapped[list["CartItem"]] = relationship(back_populates="session")
    weight_events: Mapped[list["WeightEvent"]] = relationship(back_populates="session")


class CartItem(Base):
    """A product + quantity within one session."""

    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    # Price snapshot at the moment the item was added, so a later price
    # change in the catalog never retroactively changes an in-progress or
    # historical cart's total -- a correctness issue the old flat JSON
    # structure had no way to represent.
    unit_price_snapshot: Mapped[float] = mapped_column(Numeric(10, 2))
    weight_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[CartSession] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()

    @property
    def product_name(self) -> str:
        """
        Convenience accessor for API responses (see schemas.CartItemOut).
        Added while building the kiosk UI (Milestone 4), which needs to
        show a product name in the cart list without a second lookup
        round-trip per item -- reads through the existing `product`
        relationship rather than duplicating the name onto CartItem
        itself, so there's still exactly one place (Product.name) that
        can ever disagree with itself.
        """
        return self.product.name


class WeightEvent(Base):
    """Raw weight readings from the ESP32, one row per reading (audit trail)."""

    __tablename__ = "weight_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    raw_weight_grams: Mapped[float] = mapped_column(Numeric(10, 2))
    delta_grams: Mapped[float] = mapped_column(Numeric(10, 2))
    matched_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("cart_items.id"), nullable=True
    )
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[CartSession] = relationship(back_populates="weight_events")
