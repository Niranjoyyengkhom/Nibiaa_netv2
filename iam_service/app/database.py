import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("nibiaanet.iam.database")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgrespassword@localhost:5432/device_registry",
)


def init_engine():
    global DATABASE_URL
    logger.info(f"Connecting IAM database at {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}...")

    kwargs = {
        "pool_pre_ping": True,
    }
    if "postgres" in DATABASE_URL:
        kwargs["connect_args"] = {"connect_timeout": 5}
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20

    try:
        engine = create_engine(DATABASE_URL, **kwargs)
        return engine
    except Exception as e:
        logger.error(f"Failed to initialize engine for {DATABASE_URL}: {e}")
        # Fallback in-memory sqlite if testing without PostgreSQL
        return create_engine("sqlite:///:memory:", echo=False)


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
