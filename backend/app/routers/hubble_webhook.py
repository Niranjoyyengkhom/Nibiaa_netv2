import os
import json
import base64
import hmac
import hashlib
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
from app.models.ingestion_profile import IngestionProfile
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
DEFAULT_HUBBLE_SECRET = os.getenv("HUBBLE_WEBHOOK_SECRET", "")


def authenticate_hubble(
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
    x_hubble_token: Optional[str] = Header(None, alias="X-Hubble-Token"),
    http_x_hubble_token: Optional[str] = Header(None, alias="HTTP-X-HUBBLE-TOKEN"),
    x_hubble_secret: Optional[str] = Header(None, alias="X-Hubble-Secret"),
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_hubble_username: Optional[str] = Header(None, alias="X-Hubble-Username"),
    x_hubble_password: Optional[str] = Header(None, alias="X-Hubble-Password"),
    x_username: Optional[str] = Header(None, alias="X-Username"),
    x_password: Optional[str] = Header(None, alias="X-Password"),
    query_token: Optional[str] = Query(None, alias="token"),
    query_secret: Optional[str] = Query(None, alias="secret"),
    query_username: Optional[str] = Query(None, alias="username"),
    query_password: Optional[str] = Query(None, alias="password"),
    db: Session = Depends(get_db),
) -> str:
    """
    Authenticates Hubble Network incoming webhook requests.
    Supports:
      1. Hubble Webhook Secret Token Header (HTTP-X-HUBBLE-TOKEN, X-Hubble-Token, X-Hubble-Secret, X-Webhook-Secret)
      2. Bearer Token Authorization (Authorization: Bearer <secret>)
      3. Query parameter secret token (?secret=... or ?token=...)
      4. HTTP Basic Authentication (Authorization: Basic base64(user:pass))
      5. Headers (X-Hubble-Username/Password or X-Username/Password)
      6. Query Parameters (?username=...&password=...)
    Verifies against configured HUBBLE_WEBHOOK_SECRET, HUBBLE_WEBHOOK_USERNAME/PASSWORD, or database users/profiles.
    """
    configured_secret = os.getenv("HUBBLE_WEBHOOK_SECRET", DEFAULT_HUBBLE_SECRET).strip()

    # 1. Check for incoming Secret Token from Hubble
    provided_token = None
    if http_x_hubble_token:
        provided_token = http_x_hubble_token.strip()
    elif x_hubble_token:
        provided_token = x_hubble_token.strip()
    elif x_hubble_secret:
        provided_token = x_hubble_secret.strip()
    elif x_webhook_secret:
        provided_token = x_webhook_secret.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        provided_token = authorization[7:].strip()
    elif query_token:
        provided_token = query_token.strip()
    elif query_secret:
        provided_token = query_secret.strip()

    if provided_token:
        if configured_secret:
            if hmac.compare_digest(provided_token, configured_secret):
                return "hubble-webhook-secret"
            logger.warning("Hubble webhook secret token mismatch against configured HUBBLE_WEBHOOK_SECRET")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Hubble webhook secret token.",
            )
        else:
            # Check if secret matches any active IngestionProfile in database
            try:
                db_profile = (
                    db.query(IngestionProfile)
                    .filter(
                        IngestionProfile.is_enabled == True,
                        (IngestionProfile.network_profile_code == "hubble")
                        | (IngestionProfile.code.ilike("%hubble%")),
                    )
                    .first()
                )
                if db_profile and (db_profile.auth_token or db_profile.auth_password):
                    expected = (db_profile.auth_token or db_profile.auth_password).strip()
                    if hmac.compare_digest(provided_token, expected):
                        return "hubble-profile-secret"
            except Exception as e:
                logger.debug("Database profile lookup error: %s", e)

            # If no strict secret configured yet, accept incoming secret from Hubble and log
            logger.info("Hubble webhook authenticated using incoming secret token (HUBBLE_WEBHOOK_SECRET not restricted)")
            return "hubble-token"

    # 2. Check for HTTP Basic Auth or Username/Password
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
            detail="Authentication required. Please provide Hubble Webhook Secret Token (HTTP-X-HUBBLE-TOKEN header) or HTTP Basic Auth.",
            headers={"WWW-Authenticate": 'Basic realm="Hubble Webhook"'},
        )

    # 2a. Match configured Hubble service credentials
    configured_user = os.getenv("HUBBLE_WEBHOOK_USERNAME", DEFAULT_HUBBLE_USER)
    configured_pass = os.getenv("HUBBLE_WEBHOOK_PASSWORD", DEFAULT_HUBBLE_PASS)

    if user == configured_user and password == configured_pass:
        return user

    # 2b. Match database user (e.g. admin or tenant owner)
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
        detail="Invalid Hubble webhook username, password, or secret token.",
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
        "auth_types_supported": [
            "Hubble Webhook Secret (HTTP-X-HUBBLE-TOKEN or X-Hubble-Token header)",
            "Bearer Secret Token (Authorization: Bearer <secret>)",
            "URL Secret Parameter (?secret=<secret>)",
            "HTTP Basic Authentication (Username & Password)",
        ],
        "secret_configured": bool(os.getenv("HUBBLE_WEBHOOK_SECRET")),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post(
    "",
    summary="Hubble Network Webhook Uplink Ingestion",
    description=(
        "Receives device telemetry packets from Hubble Network. "
        "Supports Hubble Webhook Secret Token (HTTP-X-HUBBLE-TOKEN) or HTTP Basic Authentication. "
        "Parses packet batches, single packets, or packet arrays, stages and decodes them, "
        "and stores telemetry in NibiaaNet."
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
            or pkt.get("telemetry")
        )

        if not device_id or raw_payload_data is None:
            logger.warning("Skipping malformed Hubble packet at index %d: missing deviceId or payload", idx)
            continue

        raw_bytes = parse_raw_payload(raw_payload_data)
        rx_time = parse_timestamp(pkt.get("timestamp") or pkt.get("rx_time") or pkt.get("time"))

        # Extract satellite and RF metadata
        rssi = pkt.get("rssi")
        snr = pkt.get("snr")
        seq = pkt.get("seq") or pkt.get("sequenceNumber") or pkt.get("seqNumber")
        freq = pkt.get("frequency") or pkt.get("freq")
        lat = pkt.get("latitude") or pkt.get("lat")
        lon = pkt.get("longitude") or pkt.get("lon") or pkt.get("lng")
        sat_id = pkt.get("satelliteId") or pkt.get("satId") or pkt.get("constellation")

        metadata: Dict[str, Any] = {
            "source": "hubble_network_webhook",
            "authenticated_as": authenticated_user,
            "remote_ip": remote_ip,
        }
        if rssi is not None:
            metadata["rssi"] = rssi
        if snr is not None:
            metadata["snr"] = snr
        if seq is not None:
            metadata["sequence_number"] = seq
        if freq is not None:
            metadata["frequency_hz"] = freq
        if lat is not None and lon is not None:
            metadata["coordinates"] = {"latitude": float(lat), "longitude": float(lon)}
        if sat_id is not None:
            metadata["satellite_id"] = str(sat_id)

        try:
            # Stage message in NibiaaNet DecodedMessage repository
            staged_msg = ingestion_service.create_staged_message(
                db=db,
                source_address=f"hubble://{remote_ip}",
                remote_port=443,
                protocol="webhook",
                payload_bytes=raw_bytes,
                client_id=f"hubble-{device_id}",
                provider="hubble",
                message_ref=str(pkt.get("messageId") or pkt.get("id") or f"hubble-{idx}-{int(rx_time.timestamp())}"),
                device_id_hint=str(device_id),
            )

            # Process / decode the uplink asynchronously or inline
            processed_record = ingestion_service.process_staged_message(
                db=db,
                message_id=staged_msg.id,
                payload_bytes=raw_bytes,
                device_id_hint=str(device_id),
                client_id=f"hubble-{device_id}",
                protocol="webhook",
                metadata=metadata,
            )

            results.append({
                "index": idx,
                "device_id": str(device_id),
                "message_id": staged_msg.id,
                "status": processed_record.status.value if processed_record else "QUEUED",
                "telemetry_id": processed_record.telemetry_id if processed_record else None,
            })
        except Exception as err:
            logger.error("Error processing Hubble uplink for device %s: %s", device_id, err, exc_info=True)
            results.append({
                "index": idx,
                "device_id": str(device_id),
                "status": "ERROR",
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
