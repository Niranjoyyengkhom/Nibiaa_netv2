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
    device = (
        db.get(Device, message.device_pk)
        if message.device_pk
        else None
    )

    return {
        "id": message.id,
        "status": message.status,
        "error": message.error,
        "transport": message.transport,
        "source_address": message.source_address,
        "client_id": message.client_id,
        "device_identifier": message.device_identifier,
        "raw_payload_hex": message.raw_payload.hex(),
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

    message = ingestion_service.process_uplink(
        db,
        transport=data.transport.type.value,
        raw_payload=raw_payload,
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


# ---------------------------------------------------------
# Existing message endpoints
# ---------------------------------------------------------

@router.get(
    "/messages",
    response_model=list[DecodedMessageResponse]
)
def list_messages(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    messages = ingestion_service.list_messages(
        db,
        status=status,
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