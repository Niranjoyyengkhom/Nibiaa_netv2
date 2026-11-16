from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, SessionLocal, engine
from app.migrations import run_migrations
from app.models.user import User
from app.models.notification import Notification
from app.models.tenant import Tenant
from app.models.collaborator_role import CollaboratorRole
from app.models.collaborator_permission import CollaboratorPermission
from app.models.connectivity_profile import ConnectivityProfile
from app.models.device import Device
from app.models.application import Application
from app.models.device_configuration import DeviceConfiguration
from app.models.device_command import DeviceCommand
from app.models.device_command_event import DeviceCommandEvent
from app.models.telemetry import Telemetry
from app.models.decode_schema import DecodeSchema, DecodeSchemaActivation
from app.models.provider_source import ProviderSource
from app.models.decoded_message import DecodedMessage
from app.models.webhook import Webhook, WebhookDelivery
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
from app.routers.billing import router as billing_router
from app.routers.network_provider import router as network_provider_router
from app.routers import notifications



Base.metadata.create_all(bind=engine)
run_migrations(engine)


# First start: fill the connectivity profiles with the default providers
with SessionLocal() as startup_db:
    ensure_default_profiles(startup_db)


app = FastAPI(title="NibiaaNet API")


import os

cors_origins_env = os.getenv("ALLOWED_ORIGINS", "")
allowed_origins = [
    origin.strip()
    for origin in cors_origins_env.split(",")
    if origin.strip()
]
if not allowed_origins:
    allowed_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
app.include_router(ingest_router)
app.include_router(webhooks_router)
app.include_router(notifications.router)
app.include_router(billing_router)
app.include_router(network_provider_router)

@app.get("/")
def home():
    return {
        "message": "Device Registry API is running"
    }
