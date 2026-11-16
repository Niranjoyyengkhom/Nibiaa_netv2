import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ALLOWED_ORIGINS
from app.database import init_db, SessionLocal
from app.routers import billing_router, network_router, health_router
from app.services.billing_service import billing_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("billing.microservice")


async def recurring_billing_worker(interval_seconds: int = 60):
    """
    Background worker that runs periodically to evaluate active subscriptions
    and auto-generate invoices every 30 days from date of subscription.
    """
    logger.info("30-Day Auto-Billing Recurring Worker initialized.")
    while True:
        try:
            db = SessionLocal()
            try:
                invoices = await billing_service.process_recurring_invoices(db)
                if invoices:
                    logger.info(f"Auto-generated {len(invoices)} 30-day recurring invoice(s).")
            finally:
                db.close()
        except asyncio.CancelledError:
            logger.info("30-Day Auto-Billing Worker stopped.")
            break
        except Exception as e:
            logger.error(f"Error in 30-day auto-billing worker: {e}")

        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Billing Microservice database & encrypted tables...")
    init_db()
    logger.info("Billing Microservice ready.")

    # Start 30-day auto-billing background worker
    auto_billing_task = asyncio.create_task(recurring_billing_worker(interval_seconds=60))
    logger.info("30-Day Auto-Billing Worker started.")

    try:
        yield
    finally:
        logger.info("Shutting down Billing Microservice.")
        auto_billing_task.cancel()
        try:
            await auto_billing_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="NibiaaNet Billing & Network Provider Microservice",
    description="Standalone microservice for Billing Plans, Subscriptions, Odoo ERP Invoicing, and Multi-Carrier SIM Management (1NCE, Monogoto, EMnify, Twilio, Generic REST).",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if "*" in ALLOWED_ORIGINS else ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(billing_router)
app.include_router(network_router)


@app.get("/")
def root():
    return {
        "service": "NibiaaNet Billing Microservice",
        "version": "2.0.0",
        "status": "healthy",
        "docs": "/docs",
    }
