from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.decoded_message import DecodedMessage, DecodedMessageStatus
from app.models.device import Device
from app.models.user import User
from app.schemas.ingest import (
    DecodedMessageResponse,
    IncomingMessage,
    PurgeResponse,
    ReprocessRequest,
    ReprocessResponse,
)
from app.services.ingestion_service import IngestionService
from app.storage.redis_queue import redis_queue
from app.storage.cassandra_storage import cassandra_storage
from app.security.crypto import get_encryption_key_fingerprint


router = APIRouter(
    prefix="/ingest",
    tags=["Ingestion"]
)

ingestion_service = IngestionService()


def require_admin(
    current_user: User = Depends(get_current_user)
):
    # Ingestion is platform plumbing
    # (protocol listeners / queue consumers), not tenant-facing.
    if current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admins can use the ingestion API"
        )

    return current_user


def message_response(
    db: Session,
    message: DecodedMessage
):
    device = None
    if message.device_pk:
        device = db.get(Device, message.device_pk)
    elif message.device_identifier:
        device = db.query(Device).filter(Device.device_id == message.device_identifier).first()

    originator_device = (device.name or device.device_id) if device else message.device_identifier
    originator_source = message.transport.upper() if message.transport else "UNKNOWN"
    if message.source_address:
        originator_source += f" [{message.source_address}]"

    data_originator = f"{originator_device} via {originator_source}" if originator_device else originator_source

    return {
        "id": message.id,
        "status": message.status,
        "error": message.error,
        "transport": message.transport,
        "source_address": message.source_address,
        "client_id": message.client_id,
        "device_identifier": message.device_identifier,
        "data_originator": data_originator,
        "originator_device": originator_device,
        "originator_source": originator_source,
        "raw_payload_hex": message.raw_payload.hex(),
        "payload_format": getattr(message, "payload_format", None) or "binary",
        "received_at": message.received_at,
        "provider": message.provider,
        "connection_type": message.connection_type,
        "decode_activation_id": message.decode_activation_id,
        "message_ref": message.message_ref,
        "protocol_id": message.protocol_id,
        "message_type": message.message_type,
        "payload_version": message.payload_version,
        "decode_schema_id": message.decode_schema_id,
        "decoder_selection": message.decoder_selection,
        "decoded": message.decoded,
        "units": message.units,
        "device_id": device.device_id if device else None,
        "tenant_id": message.tenant_id,
        "telemetry_id": message.telemetry_id,
        "mqtt_status": message.mqtt_status,
        "attempts": message.attempts,
        "processed_at": message.processed_at,
    }


@router.post(
    "/uplinks",
    response_model=DecodedMessageResponse,
    summary="Ingest one uplink",
    description="Accept one raw uplink message and process it through the ingestion pipeline.",
)
def ingest_uplink(
    data: IncomingMessage,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    Receive one standardized IncomingMessage.

    Flow:

        IncomingMessage
              ↓
        raw payload bytes
              ↓
        provider resolution (connectivity profile)
              ↓
        device matching (tenant, application)
              ↓
        decoder: the application's, else the best DecoderMatch
              ↓
        telemetry + MQTT / webhook delivery
    """

    raw_payload = data.payload.raw_bytes()
    detected_fmt = data.payload.get_detected_format()

    message = ingestion_service.process_uplink(
        db,
        transport=data.transport.type.value,
        raw_payload=raw_payload,
        payload_format=detected_fmt,
        source_address=data.transport.remote_address,
        client_id=data.transport.connection_id,
        device_identifier=data.source.device_id,
        received_at=data.received_at,
        provider=data.transport.provider,
        message_ref=data.id,
        remote_port=data.transport.remote_port,
        protocol_id=data.source.protocol_id,
        message_type=data.source.message_type,
        payload_version=data.source.version,
    )

    if message.status == DecodedMessageStatus.ROUTED:
        background_tasks.add_task(
            ingestion_service.dispatch,
            message.id
        )

    return message_response(db, message)


class InternalUplinkRequest(BaseModel):
    transport: str = "webhook"
    raw_payload_hex: str
    device_id: Optional[str] = None
    source_address: Optional[str] = None
    remote_port: Optional[int] = None
    client_id: Optional[str] = None
    provider: Optional[str] = None
    protocol_id: Optional[str] = None
    message_ref: Optional[str] = None


@router.post(
    "/internal-uplink",
    summary="Internal Microservice Uplink Ingestion",
    description="Internal endpoint called by Protocol Ingestion Microservice (UDP 5001, MQTT 1883, TCP 1001, Webhook 1002)."
)
def ingest_internal_uplink(
    data: InternalUplinkRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    try:
        raw_bytes = bytes.fromhex(data.raw_payload_hex)
    except Exception:
        raw_bytes = data.raw_payload_hex.encode("utf-8")

    message = ingestion_service.process_uplink(
        db,
        transport=data.transport,
        raw_payload=raw_bytes,
        source_address=data.source_address,
        client_id=data.client_id,
        device_identifier=data.device_id,
        received_at=datetime.utcnow(),
        provider=data.provider or data.transport,
        message_ref=data.message_ref,
        remote_port=data.remote_port,
        protocol_id=data.protocol_id or data.transport,
    )

    if message.status == DecodedMessageStatus.ROUTED:
        background_tasks.add_task(
            ingestion_service.dispatch,
            message.id
        )

    return message_response(db, message)


# ---------------------------------------------------------
# Existing message endpoints
# ---------------------------------------------------------

@router.get(
    "/messages",
    response_model=list[DecodedMessageResponse]
)
def list_messages(
    status: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    tenant_id = None if current_user.role == "admin" else current_user.tenant_id
    messages = ingestion_service.list_messages(
        db,
        status=status,
        tenant_id=tenant_id,
        device_identifier=device_id,
        limit=limit,
    )

    return [
        message_response(db, message)
        for message in messages
    ]


@router.post(
    "/reprocess",
    response_model=ReprocessResponse
)
def reprocess_messages(
    data: ReprocessRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    result = ingestion_service.reprocess(
        db,
        provider=data.provider,
        statuses=data.statuses,
        limit=data.limit,
    )

    return {
        "processed": result["processed"],
        "routed": result["routed"],
        "messages": [
            message_response(db, message)
            for message in result["messages"]
        ],
    }


@router.post(
    "/purge",
    response_model=PurgeResponse
)
def purge_messages(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    deleted = ingestion_service.purge(db)

    return {
        "deleted": deleted
    }


@router.post(
    "/queue",
    summary="Enqueue unprocessed telemetry into Redis",
    description="Buffers raw unprocessed telemetry uplink into Redis queue for asynchronous high-throughput processing."
)
def enqueue_unprocessed_telemetry(
    data: IncomingMessage,
    current_user: User = Depends(require_admin)
):
    msg_dict = data.model_dump(mode="json")
    queued_id = redis_queue.enqueue_unprocessed(msg_dict)
    return {
        "success": True,
        "status": "enqueued_in_redis",
        "message_id": queued_id,
        "queue_length": redis_queue.get_queue_length(),
    }


@router.get(
    "/status",
    summary="Storage, Queue and Encryption Architecture Status",
    description="Returns live status of Redis unprocessed queue, Apache Cassandra telemetry store, and Application-Level Database Encryption."
)
def get_ingest_architecture_status(
    current_user: User = Depends(get_current_user)
):
    return {
        "encryption": {
            "enabled": True,
            "level": "Application-Level Column & Field Encryption",
            "algorithm": "AES-256 (Fernet / HKDF-SHA256)",
            "key_fingerprint": get_encryption_key_fingerprint(),
            "protected_tables": ["telemetry", "decoded_messages", "devices", "decode_schemas", "webhooks"],
            "status": "active_and_enforced",
        },
        "redis_unprocessed_queue": redis_queue.get_status(),
        "cassandra_telemetry_store": cassandra_storage.get_status(),
    }
