import os
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, SessionLocal, engine, DATABASE_URL
from app.models.message import DecodedMessageRecord
from app.services.queue import queue_worker
from app.ingestion.udp import start_udp_listener
from app.ingestion.mqtt import start_mqtt_listener
from app.routers import health, decoders, run, messages

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nibiaanet.decoder")

db_status = "initializing"
try:
    Base.metadata.create_all(bind=engine)
    db_status = "connected"
except Exception as e:
    logger.warning(f"PostgreSQL connection to {DATABASE_URL} failed on startup: {e}.")
    db_status = f"disconnected: {e}"


async def decoder_retention_worker():
    """Background task to delete stored decoded messages older than 24 hours."""
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            with SessionLocal() as db:
                deleted = (
                    db.query(DecodedMessageRecord)
                    .filter(DecodedMessageRecord.received_at < cutoff)
                    .delete(synchronize_session=False)
                )
                db.commit()
                if deleted > 0:
                    logger.info(f"Auto-retention: purged {deleted} decoder messages older than 24 hours.")
        except Exception as e:
            logger.warning(f"Error in decoder retention worker: {e}")
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Decoder background services...")
    # Start queue background processor
    await queue_worker.start()

    # Start 24-hour retention worker
    retention_task = asyncio.create_task(decoder_retention_worker())

    # Start UDP listener (port 5005)
    udp_port = int(os.getenv("UDP_PORT", 5005))
    udp_transport = await start_udp_listener(port=udp_port)

    # Start MQTT listener if configured
    mqtt_client = await start_mqtt_listener()

    logger.info("Decoder Service initialized successfully on Port 3001 with 24-hour retention.")
    try:
        yield
    finally:
        logger.info("Shutting down Decoder Service...")
        retention_task.cancel()
        try:
            await retention_task
        except asyncio.CancelledError:
            pass
        await queue_worker.stop()
        if udp_transport:
            udp_transport.close()
        if mqtt_client:
            try:
                mqtt_client.loop_stop()
                mqtt_client.disconnect()
            except Exception:
                pass


app = FastAPI(
    title="NibiaaNet Decoder Service",
    description="Dedicated microservice for dynamic payload decoding, ingestion, and sandboxing",
    version="2.0.0",
    lifespan=lifespan,
)

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

app.include_router(health.router)
app.include_router(decoders.router)
app.include_router(run.router)
app.include_router(messages.router)


@app.get("/")
def home():
    return {
        "service": "NibiaaNet Decoder Microservice",
        "port": 3001,
        "status": "online",
        "runtime": "Embedded V8 (py_mini_racer) + Python Native",
        "database": db_status,
        "database_url": DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL,
        "endpoints": {
            "health": "/health",
            "run": "/decode/run",
            "templates": "/decode/templates",
            "decoders": "/decoders",
            "messages": "/messages",
            "docs": "/docs",
        },
    }
