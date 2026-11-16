import logging
import json
import httpx
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.message import DecodedMessageRecord

logger = logging.getLogger("nibiaanet.decoder.sinks")


class MessageSinks:
    @staticmethod
    def store_message(
        db: Session,
        message_id: str,
        received_at: datetime,
        device_id: Optional[str],
        transport: str,
        status: str,
        body: dict,
        tenant_id: Optional[int] = None,
    ):
        try:
            record = DecodedMessageRecord(
                message_id=message_id,
                received_at=received_at or datetime.now(timezone.utc),
                device_id=device_id,
                transport=transport,
                status=status,
                body=body,
                tenant_id=tenant_id,
                stored_at=datetime.now(timezone.utc),
            )
            db.add(record)
            db.commit()
            return record
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.warning(f"Database sink store_message skipped (PostgreSQL unavailable): {e}")
            return None

    @staticmethod
    async def forward_webhook(url: str, payload: dict):
        if not url:
            return
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                await client.post(url, json=payload)
            except Exception as e:
                logger.warning(f"Failed to forward message to webhook {url}: {e}")

    @staticmethod
    def log_console(message_id: str, status: str, device_id: str, data: Any):
        logger.info(f"[DecoderSink] ID={message_id} Device={device_id} Status={status} Data={json.dumps(data)[:120]}")


sinks = MessageSinks()
