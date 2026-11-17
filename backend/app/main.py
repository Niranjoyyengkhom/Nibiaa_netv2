import os
import logging
import asyncio
from datetime import timedelta
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.database import Base, SessionLocal, engine, DATABASE_URL
from app.billing_database import (
    init_billing_database,
    BillingSessionLocal,
    BILLING_DATABASE_URL,
    BILLING_DATABASE_NAME,
)
from app.migrations import run_migrations
from app.models.user import User
from app.models.notification import Notification
from app.models.tenant import Tenant
from app.models.collaborator_role import CollaboratorRole
from app.models.collaborator_permission import CollaboratorPermission
from app.models.connectivity_profile import ConnectivityProfile
from app.models.device import Device
from app.models.application import Application
from app.models.application_decoder import ApplicationDecoder
from app.models.device_type_decoder import DeviceTypeDecoder
from app.models.device_configuration import DeviceConfiguration
from app.models.device_command import DeviceCommand
from app.models.device_command_event import DeviceCommandEvent
from app.models.telemetry import Telemetry
from app.models.decode_schema import DecodeSchema, DecodeSchemaActivation
from app.models.provider_source import ProviderSource
from app.models.decoded_message import DecodedMessage
from app.models.webhook import Webhook, WebhookDelivery
from app.models.mqtt_broker_config import MqttBrokerConfig
from app.models.account_activation import AccountActivation
from app.models.audit_log import AuditLog
from app.providers import ensure_default_profiles
from app.routers.users import router as users_router
from app.routers.auth import router as auth_router
from app.routers.devices import router as devices_router
from app.routers.tenants import router as tenants_router
from app.routers.applications import router as applications_router
from app.routers.collaborator_permissions import router as collaborator_permissions_router
from app.routers.collaborator_permissions import roles_router as collaborator_roles_router
from app.routers.connectivity_profiles import router as connectivity_profiles_router
from app.routers.device_configuration import router as device_configuration_router
from app.routers.device_control import router as device_control_router
from app.routers.telemetry import fleet_router as telemetry_fleet_router
from app.routers.telemetry import router as telemetry_router
from app.routers.usage import router as usage_router
from app.routers.decode_schemas import router as decode_schemas_router
from app.routers.decoder_messages import router as decoder_messages_router
from app.routers.ingest import router as ingest_router
from app.routers.webhooks import router as webhooks_router
from app.routers.mqtt_config import router as mqtt_router
from app.routers.device_types import router as device_types_router
from app.routers.audit_logs import router as audit_logs_router
from app.routers.billing import router as billing_router
from app.routers.network_provider import router as network_provider_router
from app.routers.hubble_webhook import router as hubble_webhook_router
from app.routers.protocol_ingestion import router as protocol_ingestion_router
from app.routers.ingestion_profiles import router as ingestion_profiles_router
from app.routers import notifications
from app.services.ingestion_service import IngestionService
from app.services.audit_service import AuditService
from app.services.billing_service import billing_service
from app.services.network_provider_service import network_provider_service
from app.migrations_encryption import run_encryption_migration
from app.storage.cassandra_storage import cassandra_storage
from app.storage.redis_queue import redis_queue
from app.storage.redis_worker import redis_unprocessed_telemetry_worker
from app.security.crypto import get_encryption_key_fingerprint

logger = logging.getLogger("nibiaanet.backend")

db_status = "initializing"
try:
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    run_encryption_migration(engine)
    with SessionLocal() as startup_db:
        ensure_default_profiles(startup_db)
        if startup_db.query(User.id).first() is None:
            from app.seed import seed_database
            seed_database(startup_db)
        AuditService().seed_initial_logs(startup_db)
    # Sync PostgreSQL primary key sequences with seeded IDs
    with engine.begin() as conn:
        seq_sql = """
        SELECT c.table_name, c.column_name, pg_get_serial_sequence(c.table_name, c.column_name) as seq_name
        FROM information_schema.columns c
        WHERE c.table_schema = 'public' 
          AND pg_get_serial_sequence(c.table_name, c.column_name) IS NOT NULL;
        """
        for tbl, col, seq in conn.execute(text(seq_sql)).fetchall():
            if seq:
                max_val = conn.execute(text(f'SELECT COALESCE(MAX("{col}"), 0) FROM "{tbl}"')).scalar()
                conn.execute(text(f"SELECT setval('{seq}', {max(max_val, 1)}, true)"))
    db_status = "connected"
except Exception as e:
    logger.warning(f"PostgreSQL connection to {DATABASE_URL} failed on startup: {e}. Ensure PostgreSQL is running.", exc_info=True)
    db_status = f"disconnected: {e}"

billing_db_status = "initializing"
try:
    init_billing_database()
    with BillingSessionLocal() as billing_startup_db:
        billing_service.seed_default_plans(billing_startup_db)
        network_provider_service.seed_default_providers(billing_startup_db)
    billing_db_status = "connected"
except Exception as e:
    logger.warning(f"Billing DB connection to {BILLING_DATABASE_URL} failed on startup: {e}.", exc_info=True)
    billing_db_status = f"disconnected: {e}"

# Initialize Cassandra and Redis storage
cassandra_storage.connect()
redis_queue.connect()

_ingest_service = IngestionService()

async def telemetry_retention_worker():
    """Background task to automatically delete telemetry and staged messages older than 24 hours."""
    while True:
        try:
            with SessionLocal() as db:
                purged_count = _ingest_service.purge(db)
                if purged_count > 0:
                    logger.info(f"Auto-retention worker purged {purged_count} records older than 24 hours.")
        except Exception as e:
            logger.warning(f"Error in telemetry retention worker: {e}")
        # Run every 5 minutes
        await asyncio.sleep(300)


async def recurring_billing_worker(interval_seconds: int = 60):
    """
    Background worker that runs periodically to evaluate active subscriptions
    and auto-generate invoices every 30 days from date of subscription.
    """
    logger.info("30-Day Auto-Billing Recurring Worker initialized in Gateway.")
    while True:
        try:
            from app.billing_database import BillingSessionLocal
            from app.services.billing_service import billing_service
            db = BillingSessionLocal()
            try:
                invoices = await billing_service.process_recurring_invoices(db)
                if invoices:
                    logger.info(f"Auto-generated {len(invoices)} 30-day recurring invoice(s).")
            finally:
                db.close()
        except asyncio.CancelledError:
            logger.info("30-Day Auto-Billing Gateway Worker stopped.")
            break
        except Exception as e:
            logger.error(f"Error in gateway 30-day auto-billing worker: {e}")

        await asyncio.sleep(interval_seconds)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start auto-retention background worker
    worker_task = asyncio.create_task(telemetry_retention_worker())
    # Start Redis unprocessed telemetry consumer worker
    redis_worker_task = asyncio.create_task(redis_unprocessed_telemetry_worker())
    # Start background auto-reconnect loops for Cassandra and Redis
    cassandra_reconnect_task = asyncio.create_task(cassandra_storage.auto_reconnect_loop())
    redis_reconnect_task = asyncio.create_task(redis_queue.auto_reconnect_loop())
    # Start 30-Day Recurring Auto-Billing Background Worker
    recurring_billing_task = asyncio.create_task(recurring_billing_worker(interval_seconds=60))

    logger.info("24-Hour Telemetry Retention Worker and Redis Unprocessed Worker started.")
    logger.info("30-Day Auto-Billing Recurring Worker started.")
    try:
        yield
    finally:
        for t in (worker_task, redis_worker_task, cassandra_reconnect_task, redis_reconnect_task, recurring_billing_task):
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

app = FastAPI(title="NibiaaNet API v2", version="2.0.0", lifespan=lifespan)

cors_origins_env = os.getenv("ALLOWED_ORIGINS", "")
allowed_origins = [
    origin.strip()
    for origin in cors_origins_env.split(",")
    if origin.strip()
]
if not allowed_origins:
    allowed_origins = [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from sqlalchemy.exc import OperationalError
from fastapi.responses import JSONResponse
from fastapi import Request

@app.exception_handler(OperationalError)
async def db_operational_error_handler(request: Request, exc: OperationalError):
    err_str = str(exc).lower()
    if "connection timeout" in err_str or "could not connect" in err_str or "connectionrefused" in err_str:
        return JSONResponse(
            status_code=503,
            content={"detail": "Database connection failed. PostgreSQL is not running or unreachable at port 5432."}
        )
    logger.error(f"Database operational error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Database error: {exc}"}
    )

app.include_router(users_router)
app.include_router(auth_router)
app.include_router(collaborator_permissions_router)
app.include_router(collaborator_roles_router)
app.include_router(connectivity_profiles_router)
app.include_router(devices_router)
app.include_router(tenants_router)
app.include_router(applications_router)
app.include_router(device_configuration_router)
app.include_router(device_control_router)
app.include_router(telemetry_router)
app.include_router(telemetry_fleet_router)
app.include_router(usage_router)
app.include_router(decode_schemas_router)
app.include_router(decoder_messages_router)
app.include_router(hubble_webhook_router, prefix="/webhooks/hubble", tags=["Hubble Network Webhook"])
app.include_router(hubble_webhook_router, prefix="/webhook/hubble", tags=["Hubble Network Webhook"])
app.include_router(hubble_webhook_router, prefix="/webhooks", tags=["Hubble Network Webhook"])
app.include_router(hubble_webhook_router, prefix="/webhook", tags=["Hubble Network Webhook"])
app.include_router(hubble_webhook_router, prefix="/ingest/hubble", tags=["Hubble Network Webhook"])
app.include_router(protocol_ingestion_router)
app.include_router(ingestion_profiles_router)
app.include_router(ingest_router)
app.include_router(webhooks_router)
app.include_router(mqtt_router)
app.include_router(device_types_router)
app.include_router(audit_logs_router)
app.include_router(notifications.router)
app.include_router(billing_router)
app.include_router(network_provider_router)


@app.get("/")
def home():
    return {
        "message": "NibiaaNet Backend API is running",
        "version": "2.0.0",
        "port": int(os.getenv("PORT", 3002)),
        "database": db_status,
        "database_url": DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL,
        "billing_database": billing_db_status,
        "billing_database_name": BILLING_DATABASE_NAME,
        "security": {
            "encryption": "active (AES-256 Application-Level Encryption)",
            "key_fingerprint": get_encryption_key_fingerprint(),
            "protected_tables": [
                "telemetry",
                "decoded_messages",
                "devices",
                "decode_schemas",
                "webhooks",
                "billing_plans",
                "tenant_subscriptions",
                "invoice_records",
                "network_sim_cards",
                "billing_usage_records",
                "integration_configs",
                "network_providers",
            ],
            "raw_database_protected": "Direct SQL/disk access yields ciphertext only",
        },
        "redis_unprocessed_queue": redis_queue.get_status(),
        "cassandra_telemetry_storage": cassandra_storage.get_status(),
        "services": {
            "backend": f"http://127.0.0.1:{os.getenv('PORT', 3002)}",
            "decoder": "http://127.0.0.1:3001",
            "frontend": "http://127.0.0.1:8080"
        }
    }
