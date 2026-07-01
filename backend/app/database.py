"""
SQLAlchemy engine/session wiring.

Design note: this project uses SYNCHRONOUS SQLAlchemy (psycopg2), not
async SQLAlchemy + asyncpg. That's a deliberate tradeoff, not an oversight:

  - This system has exactly one cart, one camera stream, one load cell,
    and a handful of admin dashboard users at a time. Async buys you
    high-concurrency I/O overlap, which isn't the bottleneck here -- the
    camera inference loop and the physical shopper are.
  - Sync SQLAlchemy has a smaller surface area to debug (no event-loop
    interaction bugs, no async driver quirks) which matters for an
    academic project that needs to be maintainable by one student.
  - If this were ever productized to many concurrent carts, switching the
    `database_url` to an asyncpg DSN and the engine to
    create_async_engine is a contained, well-documented migration path --
    noted here explicitly as a future-scope item rather than pretending
    it isn't a limitation.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a DB session, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
