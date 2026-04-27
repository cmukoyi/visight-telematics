from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://beacon_user:beacon_password@db:5432/beacon_telematics")

# PostgreSQL engine configuration
# pool_pre_ping: test connections before use, drops stale ones automatically
# pool_recycle: recycle connections after 30 min so idle-in-transaction ghosts never persist
# pool_timeout: fail fast if no connection available within 10 s
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=10,
    pool_size=5,
    max_overflow=10,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialize database — creates any missing tables.

    Uses SQLAlchemy's checkfirst=True (default in create_all) so existing
    tables are never dropped or modified; only genuinely new tables are added.
    """
    Base.metadata.create_all(bind=engine)
