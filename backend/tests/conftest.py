"""
The tests run against a separate PostgreSQL database, device_registry_test,
on the same server as the real one. It is created if it does not exist,
rebuilt from the models once per test session, and emptied before every
test. The real device_registry database is never used.
"""

from datetime import datetime, timedelta, timezone

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

load_dotenv()

import app.database as database  # noqa: E402


TEST_DATABASE_NAME = "device_registry_test"

test_url = make_url(database.DATABASE_URL).set(database=TEST_DATABASE_NAME)


def create_test_database():
    # CREATE DATABASE has to be run from another database, outside a transaction
    maintenance_engine = create_engine(
        test_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT"
    )

    with maintenance_engine.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": TEST_DATABASE_NAME}
        ).scalar()

        if not exists:
            connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}"'))

    maintenance_engine.dispose()


create_test_database()

# Point the app at the test database BEFORE app.main is imported,
# because app.main runs create_all() and the migrations on import
test_engine = create_engine(test_url)
database.engine = test_engine
database.SessionLocal.configure(bind=test_engine)

# Last line of defence against wiping real data
assert test_engine.url.database.endswith("_test")

# Tables left by an older version of the models would make create_all()
# keep their old columns, so the test schema is rebuilt every session
with test_engine.begin() as connection:
    connection.execute(text("DROP SCHEMA public CASCADE"))
    connection.execute(text("CREATE SCHEMA public"))

from fastapi.testclient import TestClient  # noqa: E402
from jose import jwt  # noqa: E402

from app.dependencies.auth import ALGORITHM, SECRET_KEY  # noqa: E402
from app.main import app  # noqa: E402
from app.models.application import Application  # noqa: E402
from app.models.device import Device  # noqa: E402
from app.models.device_configuration import DeviceConfiguration  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User  # noqa: E402
from app.providers import ensure_default_profiles  # noqa: E402
from app.sequences import reset_id_sequences  # noqa: E402
from app.services.user_service import hash_password  # noqa: E402


TABLES = [
    "billing_usage_records",
    "invoices",
    "network_sim_cards",
    "tenant_subscriptions",
    "billing_plans",
    "integration_configs",
    "notifications",
    "webhook_deliveries",
    "webhooks",
    "decoded_messages",
    "provider_sources",
    "connectivity_profiles",
    "telemetry",
    "decode_schema_activations",
    "device_command_events",
    "device_commands",
    "device_configurations",
    "devices",
    "applications",
    "decode_schemas",
    "collaborator_permissions",
    "collaborator_roles",
    "users",
    "tenants",
]

PASSWORD = "Secret@123"


def headers(user_id):
    """Authorization header of a signed-in user (a real JWT)."""

    token = jwt.encode(
        {
            "sub": str(user_id),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def db():
    with test_engine.begin() as connection:
        connection.execute(
            text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
        )

    session = database.SessionLocal()

    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seed(db):
    """
    Tenant 1: DEVICE001, owner "owner1", collaborator "collaborator1"
    Tenant 2: DEVICE002, owner "owner2"
    Global admin "admin"

    Every user's password is PASSWORD.

    DEVICE001 starts as: enabled, 2 wakes/day, confirmed by the device.

    Keys "ta1" / "ta2" / "user1" are the owners and the collaborator
    under their older names (tenant admin / plain user).
    """

    db.add_all([
        Tenant(id=1, name="Tenant One"),
        Tenant(id=2, name="Tenant Two"),
    ])
    db.add_all([
        Application(id=1, name="App One", tenant_id=1),
        Application(id=2, name="App Two", tenant_id=2),
    ])

    password_hash = hash_password(PASSWORD)

    db.add_all([
        User(id=1, name="admin", role="admin", tenant_id=None, password_hash=password_hash),
        User(id=2, name="owner1", role="owner", tenant_id=1, password_hash=password_hash),
        User(id=3, name="owner2", role="owner", tenant_id=2, password_hash=password_hash),
        User(id=4, name="collaborator1", role="collaborator", tenant_id=1, password_hash=password_hash),
    ])
    db.add_all([
        Device(
            id=1,
            device_id="DEVICE001",
            name="Device One",
            device_type="sensor",
            tenant_id=1,
            application_id=1
        ),
        Device(
            id=2,
            device_id="DEVICE002",
            name="Device Two",
            device_type="sensor",
            tenant_id=2,
            application_id=2
        ),
    ])
    db.flush()

    db.add(
        DeviceConfiguration(
            device_pk=1,
            desired_enabled=True,
            confirmed_enabled=True,
            desired_wake_frequency_per_day=2,
            confirmed_wake_frequency_per_day=2,
        )
    )
    db.commit()

    # Rows above were inserted with explicit IDs
    reset_id_sequences(db)

    ensure_default_profiles(db)

    return {
        "admin": 1,
        "owner1": 2,
        "owner2": 3,
        "collaborator1": 4,
        "ta1": 2,
        "ta2": 3,
        "user1": 4,
    }


@pytest.fixture
def client():
    return TestClient(app)
