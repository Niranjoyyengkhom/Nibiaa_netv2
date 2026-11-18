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
from app.models.telemetry import Telemetry
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
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> str:
    """
    Authenticates Hubble Network incoming webhook requests.
    Supports:
      - HTTP header: HTTP-X-HUBBLE-TOKEN, X-Hubble-Token, X-Hubble-Secret, X-Webhook-Secret
      - Bearer token: Authorization: Bearer <secret>
      - Query parameter: ?secret=... or ?token=...
      - Open mode: If Ingestion Profile auth_type is 'none' / 'open' or no secret configured,
        uplinks are accepted openly without requiring authentication.
    """
    headers = {k.lower(): v for k, v in request.headers.items()}
    provided_token = (
        headers.get("http-x-hubble-token")
        or headers.get("x-hubble-token")
        or headers.get("x-hubble-secret")
        or headers.get("x-webhook-secret")
        or headers.get("x-secret")
        or headers.get("x-api-key")
        or request.query_params.get("secret")
        or request.query_params.get("token")
        or request.query_params.get("key")
    )

    auth_header = headers.get("authorization", "")
    if not provided_token and auth_header.lower().startswith("bearer "):
        provided_token = auth_header[7:].strip()
    elif not provided_token and credentials and (credentials.password or credentials.username):
        provided_token = (credentials.password or credentials.username).strip()

    # Query Ingestion Profile from DB
    db_profile = (
        db.query(IngestionProfile)
        .filter(
            IngestionProfile.is_enabled == True,
            (IngestionProfile.network_profile_code == "hubble")
            | (IngestionProfile.code.ilike("%hubble%")),
        )
        .first()
    )

    expected_secret = None
    profile_is_open = False

    if db_profile:
        if db_profile.auth_type in ("none", "open"):
            profile_is_open = True
        elif db_profile.auth_token and db_profile.auth_token.strip():
            expected_secret = db_profile.auth_token.strip()
        elif db_profile.auth_password and db_profile.auth_password.strip():
            expected_secret = db_profile.auth_password.strip()

    if not expected_secret:
        configured_env_secret = os.getenv("HUBBLE_WEBHOOK_SECRET", "").strip()
        if configured_env_secret:
            expected_secret = configured_env_secret

    # If sender did not supply a secret
    if not provided_token:
        if profile_is_open or not expected_secret:
            logger.info("Hubble webhook received and accepted in Open mode (no secret required)")
            return "hubble-open-access"

        logger.warning(
            "Hubble webhook rejected: Missing Hubble Secret key. Received headers: %s",
            list(headers.keys()),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Hubble Webhook Secret key is required. Please provide your Hubble secret in the HTTP-X-HUBBLE-TOKEN header or ?secret= query parameter.",
        )

    # If sender supplied a secret
    if expected_secret:
        if hmac.compare_digest(provided_token, expected_secret):
            return "hubble-secret-verified"
        logger.warning("Hubble webhook secret mismatch against configured secret")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Hubble Webhook Secret key.",
        )
    else:
        # Auto-bind token to profile if not configured yet
        if db_profile and not db_profile.auth_token and db_profile.auth_type != "none":
            db_profile.auth_token = provided_token
            db_profile.auth_type = "hubble_secret"
            db_profile.auth_username = None
            db.commit()
            logger.info("Automatically bound incoming Hubble secret key to Ingestion Profile.")
        return "hubble-secret-auto-bound"


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
        "Supports Hubble Webhook Secret Token (HTTP-X-HUBBLE-TOKEN) or open ingestion. "
        "Auto-registers new devices and stores telemetry coordinates, RSSI, and metrics."
    ),
)
@router.post(
    "/",
    summary="Hubble Network Webhook Uplink Ingestion (trailing slash)",
)
@router.post(
    "/hubble",
    summary="Hubble Network Webhook Uplink Ingestion (hubble path)",
)
@router.post(
    "/hubble/",
    summary="Hubble Network Webhook Uplink Ingestion (hubble path trailing slash)",
)
@router.post(
    "/uplink",
    summary="Hubble Network Webhook Uplink Ingestion",
)
@router.post(
    "/uplink/",
    summary="Hubble Network Webhook Uplink Ingestion (trailing slash)",
)
@router.post(
    "/packets",
    summary="Hubble Network Webhook Packet Ingestion",
)
@router.post(
    "/packets/",
    summary="Hubble Network Webhook Packet Ingestion (trailing slash)",
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

    logger.info("Hubble webhook packet received: body=%s, headers=%s", body, dict(request.headers))

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
            or dev_obj.get("device_id")
            or pkt.get("deviceId")
            or pkt.get("device_id")
            or dev_obj.get("name")
            or pkt.get("devId")
            or pkt.get("dev_id")
            or pkt.get("id")
            or pkt.get("deviceAddress")
        )
        device_name = dev_obj.get("name") or pkt.get("name")

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

        # Always extract rich location, RF and network metadata from Hubble packet
        hubble_meta = {
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
            hubble_meta["tags"] = tags
        hubble_meta = {k: v for k, v in hubble_meta.items() if v is not None}

        # If payload string is present (e.g. "01020304" or base64), decode it
        if raw_payload_data:
            raw_bytes = parse_raw_payload(raw_payload_data)
            # Check Device name dynamically from incoming raw JSON payload if missing
            if not device_name and raw_bytes:
                from app.services.device_keywords import extract_device_name
                dynamic_name = extract_device_name(raw_bytes)
                if dynamic_name:
                    device_name = dynamic_name
        else:
            if not device_name:
                device_name = str(device_id)
            # If payload is empty "" or None (e.g. Hubble location/presence beacon),
            # synthesize a rich JSON telemetry payload so NibiaaNet captures all parameters directly
            telemetry_data = dict(hubble_meta)
            telemetry_data["device_name"] = device_name
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
            clean_name = str(device_name).strip() if device_name else ""
            clean_dev_id = str(device_id).strip()
            existing_device = (
                db.query(Device)
                .filter(
                    (Device.device_id == clean_dev_id)
                    | (
                        func.lower(Device.name) == func.lower(clean_name)
                        if clean_name
                        else False
                    )
                )
                .first()
            )
            net_type_standard = "NTN" if str(network_type).upper() == "SATELLITE" else "BLE"
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
                net_type_standard = "NTN" if str(network_type).upper() == "SATELLITE" else "BLE"
                new_device = Device(
                    device_id=device_id,
                    name=device_name or f"Hubble {device_id[:8]}",
                    device_type=net_type_standard,
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
                target_dev = new_device
                logger.info("Auto-registered new Hubble device: %s (%s)", device_id, device_name)
            else:
                target_dev = existing_device
                # Dynamically update device name from incoming Hubble packet if provided
                hubble_name = dev_obj.get("name") or pkt.get("name")
                if hubble_name and str(hubble_name).strip() and str(hubble_name).strip() != str(target_dev.device_id):
                    clean_hubble_name = str(hubble_name).strip()
                    if target_dev.name != clean_hubble_name:
                        logger.info("Dynamically updated device %s name from '%s' to '%s'", target_dev.device_id, target_dev.name, clean_hubble_name)
                        target_dev.name = clean_hubble_name
                # Dynamically update network type to match the current uplink connection
                if net_type_standard and target_dev.device_type != net_type_standard:
                    target_dev.device_type = net_type_standard
                device_name = target_dev.name
                if not raw_payload_data and "telemetry_data" in locals() and isinstance(telemetry_data, dict):
                    telemetry_data["device_name"] = target_dev.name
                    raw_bytes = json.dumps(telemetry_data).encode("utf-8")
                if tags and isinstance(target_dev.credentials, dict):
                    creds = dict(target_dev.credentials)
                    creds["tags"] = tags
                    target_dev.credentials = creds
                db.commit()

            canonical_device_id = str(target_dev.device_id)

            # Ingest uplink through IngestionService
            msg = ingestion_service.process_uplink(
                db=db,
                transport="webhook",
                raw_payload=raw_bytes,
                source_address=f"hubble://{remote_ip}",
                client_id=f"hubble-{canonical_device_id}",
                device_identifier=canonical_device_id,
                received_at=rx_time,
                provider="hubble",
                message_ref=str(pkt.get("messageId") or dev_obj.get("counter") or f"hubble-{idx}-{int(rx_time.timestamp())}"),
                remote_port=443,
                protocol_id="hubble-webhook",
                payload_format="json" if not raw_payload_data else None,
            )

            # Enrich telemetry record with location, RF and network metadata
            if msg and msg.telemetry_id:
                try:
                    tel = db.get(Telemetry, msg.telemetry_id)
                    if tel:
                        existing_data = tel.data if isinstance(tel.data, dict) else {}
                        tel.data = {**hubble_meta, **existing_data}
                        tel.connection_type = "NTN" if str(network_type).upper() == "SATELLITE" else "TN"
                        db.commit()
                except Exception as enrich_err:
                    logger.warning("Could not enrich telemetry metadata: %s", enrich_err)

            # Dispatch message asynchronously for live subscribers & webhooks
            if msg and msg.status == DecodedMessageStatus.ROUTED:
                background_tasks.add_task(ingestion_service.dispatch, msg.id)
            else:
                # Direct safety guarantee: ensure Telemetry row exists so Live Data is NEVER empty
                target_dev = existing_device or new_device
                if target_dev:
                    try:
                        tel_fallback = Telemetry(
                            device_pk=target_dev.id,
                            timestamp=rx_time,
                            received_at=datetime.now(timezone.utc),
                            provider="hubble",
                            connection_type="NTN" if str(network_type).upper() == "SATELLITE" else "TN",
                            data=hubble_meta,
                            raw_payload=raw_bytes,
                        )
                        db.add(tel_fallback)
                        db.commit()
                        db.refresh(tel_fallback)
                        if msg:
                            msg.telemetry_id = tel_fallback.id
                            msg.status = DecodedMessageStatus.ROUTED
                            db.commit()
                        logger.info("Saved telemetry record for device %s (id: %s)", device_id, tel_fallback.id)
                    except Exception as store_err:
                        logger.warning("Telemetry fallback storage error: %s", store_err)

            msg_status_val = (msg.status.value if hasattr(msg.status, "value") else str(msg.status)) if msg and msg.status else "ROUTED"
            results.append({
                "index": idx,
                "device_id": str(device_id),
                "device_name": device_name,
                "message_id": msg.id if msg else None,
                "status": msg_status_val,
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
