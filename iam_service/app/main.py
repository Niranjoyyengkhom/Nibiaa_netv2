import os
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, SessionLocal, engine, DATABASE_URL
from app.services.seed_service import seed_iam_database
from app.routers import (
    health,
    auth,
    users,
    roles,
    permissions,
    attributes,
    abac,
    audit,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nibiaanet.iam")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing IAM Microservice database schema...")
    try:
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            seed_iam_database(db)
        logger.info("IAM Microservice schema and seed initialized successfully.")
    except Exception as e:
        logger.warning(f"Failed to initialize IAM schema on startup: {e}")

    logger.info("NibiaaNet IAM Microservice running on Port 3003.")
    try:
        yield
    finally:
        logger.info("Shutting down IAM Microservice...")


app = FastAPI(
    title="NibiaaNet IAM Microservice",
    description="Dedicated microservice for Users, Roles, Dynamic Attributes, and ABAC Policy Decision Point (PDP)",
    version="1.0.0",
    lifespan=lifespan,
)

cors_origins_env = os.getenv("ALLOWED_ORIGINS", "")
allowed_origins = [
    origin.strip()
    for origin in cors_origins_env.split(",")
    if origin.strip()
] or [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:8081",
    "http://127.0.0.1:8081",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:3002",
    "http://127.0.0.1:3002",
    "http://localhost:3003",
    "http://127.0.0.1:3003",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if allowed_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register All API Routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(permissions.router)
app.include_router(attributes.router)
app.include_router(abac.router)
app.include_router(audit.router)
