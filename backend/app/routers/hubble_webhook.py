import os
import json
import base64
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Header,
    Query,
    Request,
    Response,
    status,
)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.decoded_message import DecodedMessageStatus
from app.models.user import User
from app.services.ingestion_service import IngestionService
from app.services.user_service import verify_password

logger = logging.getLogger("nibiaanet.hubble_webhook")

router = APIRouter()
security = HTTPBasic(auto_error=False)
ingestion_service = IngestionService()

# Configurable Hubble Webhook credentials
DEFAULT_HUBBLE_USER = os.getenv("HUBBLE_WEBHOOK_USERNAME", "hubble")
DEFAULT_HUBBLE_PASS = os.getenv("HUBBLE_WEBHOOK_PASSWORD", "hubble123")


def authenticate_hubble(
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
    x_hubble_username: Optional[str] = Header(None, alias="X-Hubble-Username"),
    x_hubble_password: Optional[str] = Header(None, alias="X-Hubble-Password"),
    x_username: Optional[str] = Header(None, alias="X-Username"),
    x_password: Optional[str] = Header(None, alias="X-Password"),
    query_username: Optional[str] = Query(None, alias="username"),
    query_password: Optional[str] = Query(None, alias="password"),
    db: Session = Depends(get_db),
) -> str:
    """
    Authenticates Hubble Network incoming webhook requests.
    Supports:
      1. HTTP Basic Authentication (Authorization: Basic base64(user:pass))
      2. Headers (X-Hubble-Username/Password or X-Username/Password)
      3. Query Parameters (?username=...&password=...)
    Verifies against configured HUBBLE_WEBHOOK_USERNAME/PASSWORD or valid database user.
    """
    user = None
    password = None

    if credentials:
        user = credentials.username
        password = credentials.password
    elif x_hubble_username and x_hubble_password:
        user = x_hubble_username
        password = x_hubble_password
    elif x_username and x_password:
        user = x_username
        password = x_password
    elif query_username and query_password:
        user = query_username
        password = query_password

    if not user or not password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide HTTP Basic Auth (Username and Password).",
            headers={"WWW-Authenticate": 'Basic realm="Hubble Webhook"'},
        )

    # 1. Match configured Hubble service credentials
    configured_user = os.getenv("HUBBLE_WEBHOOK_USERNAME", DEFAULT_HUBBLE_USER)
    configured_pass = os.getenv("HUBBLE_WEBHOOK_PASSWORD", DEFAULT_HUBBLE_PASS)

    if user == configured_user and password == configured_pass:
        return user

    # 2. Match database user (e.g. admin or tenant owner)
    db_user = (
        db.query(User)
        .filter((User.name == user) | (User.email == user))
        .first()
    )
    if db_user and db_user.password_hash:
        try:
            if verify_password(password, db_user.password_hash):
                return db_user.email or db_user.name
        except Exception:
            pass

    logger.warning("Hubble webhook authentication failed for username: %s", user)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid Hubble webhook username or password.",
        headers={"WWW-Authenticate": 'Basic realm="Hubble Webhook"'},
    )


def parse_raw_payload(payload_val: Any) -> bytes:
    """
    Converts various payload representations (hex string, base64, JSON, text)
    into standard raw bytes for NibiaaNet decoders.
    """
    if isinstance(payload_val, bytes):
        return payload_val
    if isinstance(payload_val, dict):
        return json.dumps(payload_val).encode("utf-8")
    if not isinstance(payload_val, str):
        return str(payload_val).encode("utf-8")

    payload_str = payload_val.strip()
    if payload_str.startswith("0x") or payload_str.startswith("0X"):
        payload_str = payload_str[2:]

    # Check for hex representation
    if len(payload_str) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in payload_str):
        try:
            return bytes.fromhex(payload_str)
        except ValueError:
            pass

    # Check for base64 representation
    try:
        decoded = base64.b64decode(payload_str, validate=True)
        if len(decoded) > 0:
            return decoded
    except Exception:
        pass

    return payload_str.encode("utf-8")


def parse_timestamp(ts_val: Any) -> datetime:
    """Extracts a valid UTC datetime from numeric timestamp or ISO-8601 string."""
    if not ts_val:
        return datetime.now(timezone.utc)
    if isinstance(ts_val, (int, float)):
        # Check if millisecond timestamp
        if ts_val > 1e11:
            ts_val = ts_val / 1000.0
        return datetime.fromtimestamp(ts_val, tz=timezone.utc)
    if isinstance(ts_val, str):
        try:
            return datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime.now(timezone.utc)


@router.get(
    "",
    summary="Hubble Webhook Health Check",
    description="Endpoint verification for Hubble Network integration.",
)
@router.get(
    "/health",
    summary="Hubble Webhook Health Check",
)
def hubble_webhook_health():
    return {
        "status": "healthy",
        "provider": "hubble",
        "service": "NibiaaNet Hubble Webhook Ingestion API",
        "auth_type": "HTTP Basic Authentication (Username & Password)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post(
    "",
    summary="Hubble Network Webhook Uplink Ingestion",
    description=(
        "Receives device telemetry packets from Hubble Network. "
        "Requires HTTP Basic Authentication. Parses packet batches, single packets, "
        "or packet arrays, stages and decodes them, and stores telemetry in NibiaaNet."
    ),
)
@router.post(
    "/uplink",
    summary="Hubble Network Webhook Uplink Ingestion",
)
@router.post(
    "/packets",
    summary="Hubble Network Webhook Packet Ingestion",
)
async def ingest_hubble_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    authenticated_user: str = Depends(authenticate_hubble),
    db: Session = Depends(get_db),
):
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON payload: {str(e)}",
        )

    # Extract packets list
    packets = []
    if isinstance(body, list):
        packets = body
    elif isinstance(body, dict):
        if "packetBatch" in body and isinstance(body["packetBatch"], list):
            packets = body["packetBatch"]
        elif "packets" in body and isinstance(body["packets"], list):
            packets = body["packets"]
        elif "data" in body and isinstance(body["data"], list):
            packets = body["data"]
        else:
            packets = [body]

    if not packets:
        return {
            "status": "success",
            "provider": "hubble",
            "packets_received": 0,
            "packets_processed": 0,
            "message": "Empty packet payload received.",
        }

    results = []
    remote_ip = request.client.host if request.client else "hubble-webhook"

    for idx, pkt in enumerate(packets):
        if not isinstance(pkt, dict):
            continue

        device_id = (
            pkt.get("deviceId")
            or pkt.get("device_id")
            or pkt.get("devId")
            or pkt.get("dev_id")
            or pkt.get("id")
            or pkt.get("deviceAddress")
        )

        raw_payload_data = (
            pkt.get("payload")
            or pkt.get("data")
            or pkt.get("bytes")
            or pkt.get("rawPayload")
            or pkt.get("raw_payload")
            or pkt.get("hex")
        )

        if not device_id or raw_payload_data is None:
            logger.warning("Skipping malformed Hubble packet at index %d: missing deviceId or payload", idx)
            results.append({
                "index": idx,
                "status": "rejected",
                "error": "Missing deviceId or payload",
            })
            continue

        raw_bytes = parse_raw_payload(raw_payload_data)
        rx_time = parse_timestamp(pkt.get("timestamp") or pkt.get("time") or pkt.get("received_at"))

        # Process through NibiaaNet Ingestion Pipeline
        try:
            message = ingestion_service.process_uplink(
                db,
                transport="webhook",
                raw_payload=raw_bytes,
                source_address=remote_ip,
                client_id=f"hubble-{device_id}",
                device_identifier=str(device_id),
                received_at=rx_time,
                provider="hubble",
                message_ref=str(pkt.get("messageId") or pkt.get("id") or f"hubble-{idx}-{int(rx_time.timestamp())}"),
            )

            # If message was successfully decoded & routed, dispatch webhooks/MQTT in background
            if message.status == DecodedMessageStatus.ROUTED:
                background_tasks.add_task(
                    ingestion_service.dispatch,
                    message.id,
                )

            results.append({
                "index": idx,
                "device_id": str(device_id),
                "message_id": message.id,
                "status": message.status.value if hasattr(message.status, "value") else str(message.status),
                "telemetry_id": message.telemetry_id,
            })
        except Exception as err:
            logger.error("Error processing Hubble uplink for device %s: %s", device_id, err, exc_info=True)
            results.append({
                "index": idx,
                "device_id": str(device_id),
                "status": "error",
                "error": str(err),
            })

    return {
        "status": "success",
        "provider": "hubble",
        "authenticated_as": authenticated_user,
        "packets_received": len(packets),
        "packets_processed": len(results),
        "results": results,
    }
