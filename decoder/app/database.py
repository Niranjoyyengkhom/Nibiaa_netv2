import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("nibiaanet.decoder.database")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgrespassword@localhost:5432/device_registry",
)


def init_engine():
    global DATABASE_URL
    logger.info("Initializing strict PostgreSQL connection pool for Decoder Service...")
    
    # Strictly PostgreSQL engine - NO SQLite fallback
    engine = create_engine(
        DATABASE_URL,
        connect_args={"connect_timeout": 5},
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
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
