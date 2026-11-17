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
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.application import Application
from app.models.decoded_message import DecodedMessageStatus
from app.models.device import Device
from app.models.device_type import DeviceType
from app.models.ingestion_profile import IngestionProfile
from app.models.tenant import Tenant
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
      7. Open access when no secret or basic auth is configured
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

    if user and password:
        # Match configured Hubble service credentials
        configured_user = os.getenv("HUBBLE_WEBHOOK_USERNAME", DEFAULT_HUBBLE_USER)
        configured_pass = os.getenv("HUBBLE_WEBHOOK_PASSWORD", DEFAULT_HUBBLE_PASS)

        if user == configured_user and password == configured_pass:
            return user

        # Match database user (e.g. admin or tenant owner)
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

    # 3. Check if authentication is strictly enforced
    # If a secret is defined in environment or if IngestionProfile specifically configured a required secret
    db_profile = (
        db.query(IngestionProfile)
        .filter(
            IngestionProfile.is_enabled == True,
            (IngestionProfile.network_profile_code == "hubble")
            | (IngestionProfile.code.ilike("%hubble%")),
        )
        .first()
    )
    profile_requires_secret = db_profile and db_profile.auth_type == "hubble_secret" and (db_profile.auth_token or db_profile.auth_password)
    profile_requires_basic = db_profile and db_profile.auth_type == "basic_auth"

    if configured_secret or profile_requires_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide Hubble Webhook Secret Token (HTTP-X-HUBBLE-TOKEN header).",
        )
    elif profile_requires_basic:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide HTTP Basic Auth (Username and Password).",
            headers={"WWW-Authenticate": 'Basic realm="Hubble Webhook"'},
        )

    # When no secret or password is required, allow open Hubble webhooks
    return "hubble-open"


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
            "Open Ingestion (when configured in Ingestion Profile)",
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
        "Auto-registers new devices and stores telemetry coordinates, RSSI, and metrics."
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

    # Extract packets list (Hubble sends single object, batch, or array)
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

        # Hubble live payload format: {"device": {...}, "location": {...}, "network_type": "..."}
        dev_obj = pkt.get("device") if isinstance(pkt.get("device"), dict) else {}
        loc_obj = pkt.get("location") if isinstance(pkt.get("location"), dict) else {}

        # 1. Resolve Device ID and Name
        device_id = (
            dev_obj.get("id")
            or pkt.get("deviceId")
            or pkt.get("device_id")
            or dev_obj.get("name")
            or pkt.get("devId")
            or pkt.get("dev_id")
            or pkt.get("id")
            or pkt.get("deviceAddress")
        )
        device_name = dev_obj.get("name") or pkt.get("name") or str(device_id)

        if not device_id:
            logger.warning("Skipping malformed Hubble packet at index %d: missing device identifier in %s", idx, pkt)
            continue
        device_id = str(device_id).strip()

        # 2. Extract Location
        lat = loc_obj.get("latitude") if "latitude" in loc_obj else (pkt.get("latitude") or pkt.get("lat"))
        lon = loc_obj.get("longitude") if "longitude" in loc_obj else (pkt.get("longitude") or pkt.get("lon") or pkt.get("lng"))
        altitude = loc_obj.get("altitude") if "altitude" in loc_obj else pkt.get("altitude")
        accuracy = loc_obj.get("horizontal_accuracy") if "horizontal_accuracy" in loc_obj else pkt.get("accuracy")

        # 3. Extract RF and Network metadata
        rssi = dev_obj.get("rssi") if "rssi" in dev_obj else pkt.get("rssi")
        snr = dev_obj.get("snr") if "snr" in dev_obj else pkt.get("snr")
        seq = dev_obj.get("sequence_number") if "sequence_number" in dev_obj else (dev_obj.get("seq") or pkt.get("seq") or pkt.get("sequenceNumber"))
        counter = dev_obj.get("counter") if "counter" in dev_obj else pkt.get("counter")
        network_type = pkt.get("network_type") or dev_obj.get("network_type") or "TERRESTRIAL"
        tags = dev_obj.get("tags") if isinstance(dev_obj.get("tags"), dict) else {}

        # 4. Resolve Raw Payload
        raw_payload_data = None
        if "payload" in dev_obj:
            raw_payload_data = dev_obj.get("payload")
        elif "payload" in pkt:
            raw_payload_data = pkt.get("payload")
        elif "data" in dev_obj:
            raw_payload_data = dev_obj.get("data")
        elif "data" in pkt:
            raw_payload_data = pkt.get("data")

        # If payload string is present (e.g. "01020304" or base64), decode it
        if raw_payload_data:
            raw_bytes = parse_raw_payload(raw_payload_data)
        else:
            # If payload is empty "" or None (e.g. Hubble location/presence beacon),
            # synthesize a rich JSON telemetry payload so NibiaaNet captures all parameters directly
            telemetry_data = {
                "latitude": float(lat) if lat is not None else None,
                "longitude": float(lon) if lon is not None else None,
                "altitude": float(altitude) if altitude is not None else None,
                "horizontal_accuracy": float(accuracy) if accuracy is not None else None,
                "rssi": int(rssi) if rssi is not None else None,
                "sequence_number": int(seq) if seq is not None else None,
                "counter": int(counter) if counter is not None else None,
                "network_type": str(network_type) if network_type is not None else None,
                "device_name": device_name,
            }
            if tags:
                telemetry_data["tags"] = tags
            telemetry_data = {k: v for k, v in telemetry_data.items() if v is not None}
            raw_bytes = json.dumps(telemetry_data).encode("utf-8")

        # 5. Extract timestamps
        rx_time = parse_timestamp(
            dev_obj.get("timestamp")
            or loc_obj.get("timestamp")
            or pkt.get("timestamp")
            or pkt.get("rx_time")
        )

        try:
            # 5b. Ensure ConnectivityProfile exists for hubble
            from app.models.connectivity_profile import ConnectivityProfile
            hubble_cp = db.query(ConnectivityProfile).filter(func.lower(ConnectivityProfile.code) == "hubble").first()
            if not hubble_cp:
                hubble_cp = ConnectivityProfile(
                    code="hubble",
                    name="Hubble Network (Satellite BLE)",
                    connection_type="NTN" if str(network_type).upper() == "SATELLITE" else "Direct IP",
                    integration_status="available",
                    transport="webhook",
                    description="Global direct-to-satellite Bluetooth Low Energy (BLE) IoT network.",
                    enabled=True,
                )
                db.add(hubble_cp)
                db.commit()
                db.refresh(hubble_cp)

            # 6. AUTO-REGISTER DEVICE IF NOT REGISTERED
            existing_device = (
                db.query(Device)
                .filter((Device.device_id == device_id) | (Device.name == device_name))
                .first()
            )
            if not existing_device:
                # Find or create active tenant
                tenant = db.query(Tenant).filter(Tenant.is_active == True).first()
                if not tenant:
                    tenant = Tenant(name="Default Organization", type="organization", is_active=True)
                    db.add(tenant)
                    db.flush()

                # Find or create Application
                app_obj = (
                    db.query(Application)
                    .filter(Application.tenant_id == tenant.id)
                    .order_by(Application.id.asc())
                    .first()
                )
                if not app_obj:
                    app_obj = Application(name="Hubble Satellite Network", tenant_id=tenant.id)
                    db.add(app_obj)
                    db.flush()

                # Ensure DeviceType exists
                dt_name = "Hubble Satellite" if str(network_type).upper() == "SATELLITE" else "Hubble Terrestrial / BLE"
                dt = (
                    db.query(DeviceType)
                    .filter(DeviceType.application_id == app_obj.id, DeviceType.name == dt_name)
                    .first()
                )
                if not dt:
                    dt = DeviceType(
                        application_id=app_obj.id,
                        name=dt_name,
                        code="hubble_device",
                        network_type="NTN" if str(network_type).upper() == "SATELLITE" else "Direct IP",
                        description="Auto-registered Hubble Network device",
                    )
                    db.add(dt)
                    db.flush()

                # Create Device in DB
                new_device = Device(
                    device_id=device_id,
                    name=device_name or f"Hubble {device_id[:8]}",
                    device_type=dt_name,
                    device_type_id=dt.id,
                    tenant_id=tenant.id,
                    application_id=app_obj.id,
                    credentials={
                        "device_id": device_id,
                        "device_name": device_name,
                        "network_type": network_type,
                        "tags": tags,
                        "registered_by": "hubble_webhook",
                        "auto_registered": True,
                    },
                )
                db.add(new_device)
                db.commit()
                db.refresh(new_device)
                logger.info("Auto-registered new Hubble device: %s (%s)", device_id, device_name)

            # Ingest uplink through IngestionService
            msg = ingestion_service.process_uplink(
                db=db,
                transport="webhook",
                raw_payload=raw_bytes,
                source_address=f"hubble://{remote_ip}",
                client_id=f"hubble-{device_id}",
                device_identifier=str(device_id),
                received_at=rx_time,
                provider="hubble",
                message_ref=str(pkt.get("messageId") or dev_obj.get("counter") or f"hubble-{idx}-{int(rx_time.timestamp())}"),
                remote_port=443,
                protocol_id="hubble-webhook",
                payload_format="json" if not raw_payload_data else None,
            )

            # Dispatch message asynchronously for live subscribers & webhooks
            if msg and msg.status == DecodedMessageStatus.ROUTED:
                background_tasks.add_task(ingestion_service.dispatch, msg.id)

            results.append({
                "index": idx,
                "device_id": str(device_id),
                "device_name": device_name,
                "message_id": msg.id,
                "status": msg.status.value if msg and msg.status else "ROUTED",
                "telemetry_id": getattr(msg, "telemetry_id", None),
                "decoded": getattr(msg, "decoded", None),
            })
        except Exception as err:
            db.rollback()
            logger.error("Error processing Hubble uplink for device %s: %s", device_id, err, exc_info=True)
            results.append({
                "index": idx,
                "device_id": str(device_id),
                "device_name": device_name,
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
