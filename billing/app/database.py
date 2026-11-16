import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import DATABASE_URL, DATABASE_NAME

logger = logging.getLogger("billing.database")

engine_kwargs = {
    "pool_size": 10,
    "max_overflow": 20,
    "pool_timeout": 15,
    "pool_pre_ping": True,
}
if "postgres" in DATABASE_URL:
    engine_kwargs["connect_args"] = {"connect_timeout": 5}

engine = create_engine(
    DATABASE_URL,
    **engine_kwargs,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def create_database_if_not_exists():
    url = make_url(DATABASE_URL)
    if "sqlite" in url.drivername.lower():
        return

    try:
        maintenance_url = url.set(database="postgres")
        maint_engine = create_engine(
            maintenance_url,
            isolation_level="AUTOCOMMIT",
            connect_args={"connect_timeout": 5}
        )

        with maint_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": DATABASE_NAME}
            ).scalar()

            if not exists:
                logger.info(f"PostgreSQL database '{DATABASE_NAME}' not found. Creating database...")
                conn.execute(text(f'CREATE DATABASE "{DATABASE_NAME}"'))
                logger.info(f"Database '{DATABASE_NAME}' successfully created.")
            else:
                logger.debug(f"PostgreSQL database '{DATABASE_NAME}' already exists.")

        maint_engine.dispose()
    except Exception as e:
        logger.warning(f"Could not check/create PostgreSQL database '{DATABASE_NAME}': {e}.")


def migrate_schema():
    """Ensures dynamic % pricing columns exist on existing tables."""
    try:
        with engine.connect() as conn:
            # Network providers markup % and wholesale cost columns
            conn.execute(text("ALTER TABLE network_providers ADD COLUMN IF NOT EXISTS markup_percentage TEXT"))
            conn.execute(text("ALTER TABLE network_providers ADD COLUMN IF NOT EXISTS cost_per_mb TEXT"))
            conn.execute(text("ALTER TABLE network_providers ADD COLUMN IF NOT EXISTS cost_per_sim TEXT"))
            conn.execute(text("ALTER TABLE network_providers ADD COLUMN IF NOT EXISTS cost_per_sms TEXT"))
            # Billing plans % pricing model columns
            conn.execute(text("ALTER TABLE billing_plans ADD COLUMN IF NOT EXISTS pricing_model TEXT"))
            conn.execute(text("ALTER TABLE billing_plans ADD COLUMN IF NOT EXISTS markup_percentage TEXT"))
            conn.commit()
            logger.info("Dynamic % pricing columns verified in database.")
    except Exception as e:
        logger.warning(f"Schema migration note: {e}")


def init_db():
    create_database_if_not_exists()
    try:
        Base.metadata.create_all(bind=engine)
        migrate_schema()
        logger.info(f"Encrypted billing tables verified in database '{DATABASE_NAME}'.")
        seed_defaults()
    except Exception as e:
        logger.warning(f"Could not provision tables in database '{DATABASE_NAME}': {e}")


def seed_defaults():
    from app.models.billing_plan import BillingPlan
    from app.models.network_provider_config import NetworkProviderConfig

    db = SessionLocal()
    try:
        # Check plans
        if db.query(BillingPlan).count() == 0:
            logger.info("Seeding dynamic % pricing billing plans (no fixed amount)...")
            plans = [
                BillingPlan(
                    name="Dynamic Cellular IoT (Standard)",
                    code="dynamic_standard",
                    pricing_model="cost_plus_percentage",
                    markup_percentage=20.0,
                    monthly_price=0.0,
                    annual_price=0.0,
                    currency="USD",
                    included_devices=0,
                    included_data_mb=0.0,
                    overage_rate_per_mb=0.036,
                    extra_device_price=1.20,
                    description="100% Usage-based. Direct wholesale pricing billed by SIM provider + 20% admin markup. No fixed monthly fee.",
                    features={"dynamic_markup": True, "no_fixed_fee": True, "satellite_fallback": True},
                    is_active=True,
                ),
                BillingPlan(
                    name="Enterprise Multi-Carrier Fleet",
                    code="dynamic_enterprise",
                    pricing_model="cost_plus_percentage",
                    markup_percentage=12.0,
                    monthly_price=0.0,
                    annual_price=0.0,
                    currency="USD",
                    included_devices=0,
                    included_data_mb=0.0,
                    overage_rate_per_mb=0.030,
                    extra_device_price=1.00,
                    description="Enterprise multi-carrier volume tier. Wholesale SIM provider cost + 12% admin margin. No fixed monthly fee.",
                    features={"dynamic_markup": True, "no_fixed_fee": True, "dedicated_sla": True},
                    is_active=True,
                ),
            ]
            for p in plans:
                db.add(p)
            db.commit()

        # Check default providers
        if db.query(NetworkProviderConfig).count() == 0:
            logger.info("Seeding default SIM network providers with % pricing...")
            providers = [
                NetworkProviderConfig(
                    name="1NCE Global IoT",
                    provider_code="1nce",
                    provider_type="1nce",
                    base_url="https://api.1nce.com/management-api",
                    auth_type="oauth2",
                    api_user="",
                    api_key_encrypted="",
                    markup_percentage=20.0,
                    cost_per_mb=0.025,
                    cost_per_sim=0.85,
                    cost_per_sms=0.008,
                    extra_settings={"sandbox_mode": True, "token_endpoint": "https://api.1nce.com/management-api/oauth/token"},
                    is_enabled=True,
                    is_sandbox=True,
                ),
                NetworkProviderConfig(
                    name="Monogoto Software Defined Connectivity",
                    provider_code="monogoto",
                    provider_type="monogoto",
                    base_url="https://api.monogoto.io",
                    auth_type="bearer_token",
                    api_user="",
                    api_key_encrypted="",
                    markup_percentage=20.0,
                    cost_per_mb=0.030,
                    cost_per_sim=1.00,
                    cost_per_sms=0.010,
                    extra_settings={"sandbox_mode": True, "token_endpoint": "https://api.monogoto.io/Auth"},
                    is_enabled=True,
                    is_sandbox=True,
                ),
                NetworkProviderConfig(
                    name="EMnify IoT SuperNetwork",
                    provider_code="emnify",
                    provider_type="emnify",
                    base_url="https://cdn.emnify.net/api/v1",
                    auth_type="bearer_token",
                    api_user="",
                    api_key_encrypted="",
                    markup_percentage=18.0,
                    cost_per_mb=0.028,
                    cost_per_sim=0.90,
                    cost_per_sms=0.009,
                    extra_settings={"sandbox_mode": True},
                    is_enabled=False,
                    is_sandbox=True,
                ),
                NetworkProviderConfig(
                    name="Twilio Super SIM",
                    provider_code="twilio",
                    provider_type="twilio",
                    base_url="https://supersim.twilio.com/v1",
                    auth_type="basic_auth",
                    api_user="",
                    api_key_encrypted="",
                    markup_percentage=22.0,
                    cost_per_mb=0.035,
                    cost_per_sim=1.10,
                    cost_per_sms=0.012,
                    extra_settings={"sandbox_mode": True},
                    is_enabled=False,
                    is_sandbox=True,
                ),
                NetworkProviderConfig(
                    name="Generic REST Network Driver",
                    provider_code="generic_rest",
                    provider_type="generic_rest",
                    base_url="https://api.iotcarrier.example.com/v1",
                    auth_type="api_key",
                    api_user="",
                    api_key_encrypted="",
                    markup_percentage=20.0,
                    cost_per_mb=0.030,
                    cost_per_sim=1.00,
                    cost_per_sms=0.010,
                    extra_settings={"sandbox_mode": True},
                    is_enabled=False,
                    is_sandbox=True,
                ),
            ]
            for prov in providers:
                db.add(prov)
            db.commit()

    except Exception as e:
        db.rollback()
        logger.warning(f"Default seeding note: {e}")
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
