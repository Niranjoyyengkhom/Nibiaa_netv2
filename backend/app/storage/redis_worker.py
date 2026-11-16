import base64
import logging
import asyncio
from datetime import datetime, timezone
from app.database import SessionLocal
from app.storage.redis_queue import redis_queue
from app.services.ingestion_service import IngestionService

logger = logging.getLogger("nibiaanet.storage.redis_worker")
_ingest_service = IngestionService()


async def redis_unprocessed_telemetry_worker():
    """
    Background worker that continuously pulls unprocessed telemetry uplinks
    from the Redis queue, decodes them, and routes them to Cassandra and the database.
    """
    logger.info("Redis unprocessed telemetry worker started.")
    while True:
        try:
            # Run blocking dequeue in thread pool so asyncio loop is never blocked
            msg = await asyncio.to_thread(redis_queue.dequeue_unprocessed, 1)
            if not msg:
                await asyncio.sleep(0.1)
                continue

            logger.info(f"Dequeued unprocessed telemetry from Redis: ID={msg.get('id')}, Device={msg.get('source', {}).get('device_id')}")

            # Extract and dynamically detect payload format (hex, binary, base64, json)
            from app.services.payload_detector import detect_and_parse_payload
            raw_payload = b""
            detected_fmt = None
            payload_field = msg.get("payload", {})
            data_val = payload_field.get("data") if isinstance(payload_field, dict) else payload_field
            fmt_hint = msg.get("payload_format") or (payload_field.get("format") if isinstance(payload_field, dict) else None)
            try:
                raw_payload, _, detected_fmt, _, _, _ = detect_and_parse_payload(data_val, fmt_hint)
            except Exception:
                raw_payload = str(data_val).encode("utf-8")
                detected_fmt = "binary"

            transport_info = msg.get("transport", {})
            source_info = msg.get("source", {})

            with SessionLocal() as db:
                decoded_msg = _ingest_service.process_uplink(
                    db=db,
                    transport=transport_info.get("type", "udp"),
                    raw_payload=raw_payload,
                    source_address=transport_info.get("remote_address"),
                    client_id=transport_info.get("connection_id"),
                    device_identifier=source_info.get("device_id"),
                    received_at=datetime.now(timezone.utc),
                    provider=transport_info.get("provider"),
                    message_ref=msg.get("id"),
                    remote_port=transport_info.get("remote_port"),
                    protocol_id=source_info.get("protocol_id"),
                    message_type=source_info.get("message_type"),
                    payload_version=source_info.get("version"),
                    payload_format=detected_fmt,
                )

                if decoded_msg.status == "ROUTED":
                    logger.info(f"Successfully processed Redis telemetry for message {decoded_msg.id} (status: ROUTED)")
                    _ingest_service.dispatch(decoded_msg.id)
                else:
                    logger.info(f"Processed Redis telemetry for message {decoded_msg.id} (status: {decoded_msg.status})")

        except asyncio.CancelledError:
            logger.info("Redis unprocessed telemetry worker stopping...")
            break
        except Exception as e:
            logger.warning(f"Error processing Redis telemetry item: {e}")
            await asyncio.sleep(0.5)
