import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("nibiaanet.database")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgrespassword@localhost:5432/device_registry",
)


def init_engine():
    global DATABASE_URL
    logger.info("Initializing PostgreSQL connection pool...")
    # For psycopg (SQLAlchemy 2.x) we do not pass connect_args;
    # any extra params should be encoded in the URL query string.
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
    return engine


engine = init_engine()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
