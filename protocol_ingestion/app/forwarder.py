import json
import logging
import urllib.request
import os
from typing import Optional, Dict, Any
from app.metrics import record_message

logger = logging.getLogger("nibiaanet.protocol_ingestion.forwarder")
BACKEND_INGEST_URL = os.getenv("BACKEND_INGEST_URL", "http://127.0.0.1:3000/ingest/internal-uplink")


def forward_to_backend(
    transport: str,
    raw_payload_bytes: bytes,
    device_id: Optional[str] = None,
    source_address: Optional[str] = None,
    remote_port: Optional[int] = None,
    client_id: Optional[str] = None,
    provider: Optional[str] = None,
    protocol_id: Optional[str] = None,
    message_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Submits a raw packet from UDP/MQTT/TCP/Webhook directly to NibiaaNet Backend API Gateway.
    """
    hex_payload = raw_payload_bytes.hex()
    body = {
        "transport": transport,
        "raw_payload_hex": hex_payload,
        "device_id": device_id,
        "source_address": source_address,
        "remote_port": remote_port,
        "client_id": client_id,
        "provider": provider or transport,
        "protocol_id": protocol_id or transport,
        "message_ref": message_ref,
    }

    try:
        req = urllib.request.Request(
            BACKEND_INGEST_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            status = resp_data.get("status", "routed")
            record_message(
                protocol=transport,
                device_id=device_id or resp_data.get("device_id") or "AUTO",
                payload_summary=hex_payload[:32],
                status="routed" if "fail" not in str(status).lower() else "failed",
                details=f"Msg ID: {resp_data.get('id', 'N/A')}",
            )
            return resp_data
    except Exception as e:
        logger.warning(f"Failed to forward {transport} uplink to backend gateway: {e}")
        record_message(
            protocol=transport,
            device_id=device_id or "UNKNOWN",
            payload_summary=hex_payload[:32],
            status="error",
            details=str(e),
        )
        return {"status": "forward_failed", "error": str(e)}
