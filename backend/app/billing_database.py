import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("nibiaanet.billing.database")

BILLING_DATABASE_NAME = os.getenv("BILLING_DATABASE_NAME", "billing")

# Base PostgreSQL URL from main app config
DEFAULT_BASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgrespassword@127.0.0.1:5432/device_registry"
)

# Explicit URL or derived with /billing
raw_billing_url = os.getenv("BILLING_DATABASE_URL")
if raw_billing_url:
    BILLING_DATABASE_URL = raw_billing_url
else:
    try:
        parsed = make_url(DEFAULT_BASE_URL)
        BILLING_DATABASE_URL = str(parsed.set(database=BILLING_DATABASE_NAME))
    except Exception:
        BILLING_DATABASE_URL = f"postgresql+psycopg://postgres:postgrespassword@127.0.0.1:5432/{BILLING_DATABASE_NAME}"

engine_kwargs = {
    "pool_size": 10,
    "max_overflow": 20,
    "pool_timeout": 15,
    "pool_pre_ping": True,
}
# For psycopg (v3) we do not pass connect_args; any extra params go in the URL.

billing_engine = create_engine(
    BILLING_DATABASE_URL,
    **engine_kwargs,
)

BillingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=billing_engine
)

BillingBase = declarative_base()


def create_billing_database_if_not_exists():
    """
    Connects to the default PostgreSQL maintenance database ('postgres')
    and creates the 'billing' database if it does not already exist.
    """
    url = make_url(BILLING_DATABASE_URL)
    if "sqlite" in url.drivername.lower():
        return

    try:
        # Maintenance connection to postgres database
        maintenance_url = url.set(database="postgres")
        maint_engine = create_engine(
            maintenance_url,
            isolation_level="AUTOCOMMIT",
            connect_args={"connect_timeout": 5}
        )

        with maint_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": BILLING_DATABASE_NAME}
            ).scalar()

            if not exists:
                logger.info(f"PostgreSQL database '{BILLING_DATABASE_NAME}' not found. Creating database...")
                conn.execute(text(f'CREATE DATABASE "{BILLING_DATABASE_NAME}"'))
                logger.info(f"Database '{BILLING_DATABASE_NAME}' successfully created.")
            else:
                logger.debug(f"PostgreSQL database '{BILLING_DATABASE_NAME}' already exists.")

        maint_engine.dispose()
    except Exception as e:
        logger.warning(
            f"Could not check/create PostgreSQL database '{BILLING_DATABASE_NAME}': {e}. "
            "Ensure PostgreSQL is running on port 5432."
        )


def migrate_billing_schema():
    """Ensures dynamic % pricing columns exist on existing tables."""
    try:
        with billing_engine.connect() as conn:
            conn.execute(text("ALTER TABLE network_providers ADD COLUMN IF NOT EXISTS markup_percentage TEXT"))
            conn.execute(text("ALTER TABLE network_providers ADD COLUMN IF NOT EXISTS cost_per_mb TEXT"))
            conn.execute(text("ALTER TABLE network_providers ADD COLUMN IF NOT EXISTS cost_per_sim TEXT"))
            conn.execute(text("ALTER TABLE network_providers ADD COLUMN IF NOT EXISTS cost_per_sms TEXT"))
            conn.execute(text("ALTER TABLE billing_plans ADD COLUMN IF NOT EXISTS pricing_model TEXT"))
            conn.execute(text("ALTER TABLE billing_plans ADD COLUMN IF NOT EXISTS markup_percentage TEXT"))
            conn.commit()
    except Exception as e:
        logger.warning(f"Schema migration note: {e}")


def init_billing_database():
    """
    Provisions the dedicated PostgreSQL billing database and creates
    all application-level encrypted billing tables.
    """
    create_billing_database_if_not_exists()
    try:
        BillingBase.metadata.create_all(bind=billing_engine)
        migrate_billing_schema()
        logger.info(f"Encrypted billing tables verified in database '{BILLING_DATABASE_NAME}'.")
    except Exception as e:
        logger.warning(f"Could not provision tables in database '{BILLING_DATABASE_NAME}': {e}")


def get_billing_db():
    """
    FastAPI dependency that provides an isolated database session
    for the dedicated Billing database.
    """
    db = BillingSessionLocal()
    try:
        yield db
    finally:
        db.close()
