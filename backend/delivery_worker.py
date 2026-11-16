"""
Background worker for the data delivery layer.

Every POLL_SECONDS it
  - retries webhook deliveries that are due (PENDING / RETRYING)
  - purges old rows from the temporary decoded_messages table

Run next to the API:  python -m app.delivery_worker
Several workers can run at once; due deliveries are locked with
SKIP LOCKED so none is sent twice.
"""

import logging
import time
from datetime import timedelta

from app.database import SessionLocal
from app.models.device_configuration import utc_now
from app.services.ingestion_service import IngestionService
from app.services.webhook_service import WebhookService


POLL_SECONDS = 30

PURGE_INTERVAL = timedelta(hours=1)


logger = logging.getLogger("delivery_worker")


def run():
    webhook_service = WebhookService()
    ingestion_service = IngestionService()
    last_purge = None

    while True:
        db = SessionLocal()

        try:
            attempted = webhook_service.retry_due(db)

            if attempted:
                logger.info("Attempted %s webhook deliveries", attempted)

            if last_purge is None or utc_now() - last_purge >= PURGE_INTERVAL:
                deleted = ingestion_service.purge(db)
                last_purge = utc_now()
                logger.info("Purged %s staged messages", deleted)

        except Exception:
            logger.exception("Delivery worker cycle failed")
            db.rollback()

        finally:
            db.close()

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    # Importing app.main creates any missing tables and runs migrations
    import app.main  # noqa: F401

    logging.basicConfig(level=logging.INFO)
    run()
