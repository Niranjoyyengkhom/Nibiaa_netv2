import os
import hmac
import asyncio
import json
import logging
import socket
import uuid
from typing import Any, Dict, Optional, List
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.forwarder import forward_to_backend
from app.metrics import get_stats, record_message, LISTENER_STATUS

logger = logging.getLogger("nibiaanet.protocol_ingestion.webhook")

app = FastAPI(
    title="NibiaaNet Protocol Ingestion Microservice",
    description="Inbound protocol ingestion gateway supporting UDP (5001), MQTT (1883), TCP (1001), and Webhooks (1002).",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SimulationRequest(BaseModel):
    protocol: str  # "udp", "mqtt", "tcp", "webhook"
    device_id: str
    payload: str
    provider: Optional[str] = "custom"


@app.get("/health")
@app.get("/status")
def get_service_status():
    return {
        "status": "online",
        "service": "Protocol Ingestion Microservice",
        "version": "2.0.0",
        **get_stats(),
    }


@app.get("/metrics")
def get_service_metrics():
    return get_stats()


@app.post("/webhook")
@app.post("/ingest")
@app.post("/webhooks/{endpoint_path:path}")
@app.post("/endpoints/{endpoint_path:path}")
@app.post("/ingest/{endpoint_path:path}")
async def receive_webhook_uplink(
    request: Request,
    background_tasks: BackgroundTasks,
    endpoint_path: Optional[str] = None,
):
    # Hubble / Webhook Secret verification (No username/password required)
    token = (
        request.headers.get("HTTP-X-HUBBLE-TOKEN")
        or request.headers.get("X-Hubble-Token")
        or request.headers.get("X-Hubble-Secret")
        or request.headers.get("X-Webhook-Secret")
        or request.query_params.get("secret")
        or request.query_params.get("token")
    )
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()

    is_hubble = (
        "hubble" in (endpoint_path or "").lower()
        or bool(request.headers.get("HTTP-X-HUBBLE-TOKEN"))
        or bool(request.headers.get("X-Hubble-Token"))
    )

    configured_secret = os.getenv("HUBBLE_WEBHOOK_SECRET", "").strip()
    if is_hubble:
        if not token:
            raise HTTPException(
                status_code=401,
                detail="Hubble Webhook Secret key is required (HTTP-X-HUBBLE-TOKEN header or ?secret= parameter). No username/password required.",
            )
        if configured_secret and not hmac.compare_digest(token.strip(), configured_secret):
            raise HTTPException(status_code=401, detail="Invalid Hubble Webhook Secret Token.")
    elif configured_secret and token and not hmac.compare_digest(token.strip(), configured_secret):
        raise HTTPException(status_code=401, detail="Invalid Webhook Secret Token.")

    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    remote_ip = request.client.host if request.client else "unknown"
    remote_port = request.client.port if request.client else 1002

    # Handle batch or single
    packets = body if isinstance(body, list) else (body.get("packets") or body.get("packetBatch") or [body])

    processed = []
    for pkt in packets:
        if not isinstance(pkt, dict):
            continue

        dev_obj = pkt.get("device") if isinstance(pkt.get("device"), dict) else {}
        loc_obj = pkt.get("location") if isinstance(pkt.get("location"), dict) else {}

        device_id = (
            dev_obj.get("id")
            or pkt.get("deviceId")
            or pkt.get("device_id")
            or dev_obj.get("name")
            or pkt.get("id")
        )
        payload_val = (
            dev_obj.get("payload")
            if "payload" in dev_obj
            else (pkt.get("payload") or pkt.get("data") or pkt.get("bytes") or pkt.get("rawPayload"))
        )
        provider = pkt.get("provider") or (endpoint_path.split("/")[0] if endpoint_path else ("hubble" if dev_obj else "webhook"))

        is_hubble_pkt = is_hubble or bool(dev_obj) or bool(loc_obj)
        if is_hubble_pkt:
            # Preserve full Hubble JSON packet
            full_json_payload = dict(pkt)
            if dev_obj:
                full_json_payload["device"] = dict(dev_obj)
            if loc_obj:
                full_json_payload["location"] = dict(loc_obj)
            if payload_val:
                full_json_payload["payload"] = payload_val
                try:
                    import base64
                    b = base64.b64decode(payload_val, validate=True)
                    full_json_payload["payload_hex"] = b.hex()
                    if "device" in full_json_payload and isinstance(full_json_payload["device"], dict):
                        full_json_payload["device"]["payload_hex"] = b.hex()
                except Exception:
                    pass
            raw_bytes = json.dumps(full_json_payload).encode("utf-8")
        elif not payload_val:
            # Synthesize telemetry JSON if payload is empty beacon/ping
            lat = loc_obj.get("latitude") or pkt.get("latitude")
            lon = loc_obj.get("longitude") or pkt.get("longitude")
            telemetry_data = {
                "latitude": float(lat) if lat is not None else None,
                "longitude": float(lon) if lon is not None else None,
                "altitude": loc_obj.get("altitude"),
                "rssi": dev_obj.get("rssi") or pkt.get("rssi"),
                "sequence_number": dev_obj.get("sequence_number") or pkt.get("seq"),
                "counter": dev_obj.get("counter"),
                "device_name": dev_obj.get("name"),
            }
            telemetry_data = {k: v for k, v in telemetry_data.items() if v is not None}
            raw_bytes = json.dumps(telemetry_data).encode("utf-8")
        elif isinstance(payload_val, str):
            try:
                raw_bytes = bytes.fromhex(payload_val.replace("0x", ""))
            except ValueError:
                raw_bytes = payload_val.encode("utf-8")
        elif isinstance(payload_val, dict):
            raw_bytes = json.dumps(payload_val).encode("utf-8")
        else:
            raw_bytes = str(payload_val).encode("utf-8")

        res = forward_to_backend(
            transport="webhook",
            raw_payload_bytes=raw_bytes,
            device_id=str(device_id) if device_id else None,
            source_address=remote_ip,
            remote_port=remote_port,
            client_id=f"webhook-{remote_ip}",
            provider=provider,
            protocol_id=f"http-webhook/{endpoint_path}" if endpoint_path else "http-webhook",
            message_ref=str(pkt.get("messageId") or f"wh-{uuid.uuid4().hex[:8]}"),
        )
        processed.append(res)

    return {
        "status": "success",
        "transport": "webhook",
        "port": 1002,
        "count": len(processed),
        "results": processed,
    }


@app.post("/test/simulate")
def simulate_protocol_uplink(req: SimulationRequest):
    """
    Test helper called by the frontend Integration Protocol page to simulate
    a 3rd party system transmitting an uplink via UDP, MQTT, TCP, or Webhook.
    """
    proto = req.protocol.lower()
    dev_id = req.device_id.strip()
    data_str = req.payload.strip()

    try:
        raw_bytes = bytes.fromhex(data_str.replace("0x", ""))
    except ValueError:
        raw_bytes = data_str.encode("utf-8")

    if proto == "udp":
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            msg_bytes = json.dumps({"deviceId": dev_id, "payload": data_str}).encode("utf-8")
            sock.sendto(msg_bytes, ("127.0.0.1", 5001))
            sock.close()
            return {"status": "success", "message": f"UDP datagram sent to 127.0.0.1:5001 for {dev_id}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"UDP simulation failed: {e}")

    elif proto == "tcp":
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("127.0.0.1", 1001))
            line = json.dumps({"deviceId": dev_id, "payload": data_str}) + "\n"
            s.sendall(line.encode("utf-8"))
            resp = s.recv(1024).decode("utf-8", errors="ignore")
            s.close()
            return {"status": "success", "message": f"TCP packet delivered to 127.0.0.1:1001, ACK: {resp.strip()}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"TCP simulation failed: {e}")

    elif proto == "mqtt":
        try:
            res = forward_to_backend(
                transport="mqtt",
                raw_payload_bytes=raw_bytes,
                device_id=dev_id,
                source_address="127.0.0.1",
                remote_port=1883,
                client_id="simulated-mqtt-client",
                provider="mqtt",
                protocol_id=f"nibiaanet/uplink/{dev_id}",
                message_ref=f"sim-mqtt-{uuid.uuid4().hex[:8]}",
            )
            return {"status": "success", "message": f"MQTT simulated on topic nibiaanet/uplink/{dev_id}", "result": res}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"MQTT simulation failed: {e}")

    elif proto == "webhook":
        try:
            res = forward_to_backend(
                transport="webhook",
                raw_payload_bytes=raw_bytes,
                device_id=dev_id,
                source_address="127.0.0.1",
                remote_port=1002,
                client_id="simulated-webhook",
                provider=req.provider or "webhook",
                protocol_id="http-webhook",
                message_ref=f"sim-wh-{uuid.uuid4().hex[:8]}",
            )
            return {"status": "success", "message": f"Webhook uplink simulated on port 1002", "result": res}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Webhook simulation failed: {e}")

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported protocol: {proto}")
