import json
import logging
import urllib.request
import urllib.error
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("nibiaanet.router.protocol_ingestion")

router = APIRouter(
    prefix="/protocol-ingestion",
    tags=["Protocol Ingestion Microservice"]
)

INGESTION_SERVICE_URL = "http://127.0.0.1:1002"


@router.get("/status")
def get_ingestion_status():
    try:
        req = urllib.request.Request(f"{INGESTION_SERVICE_URL}/status", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {
            "status": "offline",
            "service": "Protocol Ingestion Microservice",
            "error": str(e),
            "listeners": {
                "udp": {"port": 5001, "status": "offline", "protocol": "UDP / Datagram"},
                "mqtt": {"port": 1883, "status": "offline", "protocol": "MQTT 3.1.1 Broker"},
                "tcp": {"port": 1001, "status": "offline", "protocol": "TCP / Socket Stream"},
                "webhook": {"port": 1002, "status": "offline", "protocol": "HTTP / Webhook REST"},
            },
            "counters": {"udp": 0, "mqtt": 0, "tcp": 0, "webhook": 0, "total": 0, "routed": 0, "errors": 0},
            "recent_activity": []
        }


@router.get("/metrics")
def get_ingestion_metrics():
    return get_ingestion_status()


@router.post("/simulate")
async def simulate_protocol_uplink(request: Request):
    try:
        body = await request.body()
        req = urllib.request.Request(
            f"{INGESTION_SERVICE_URL}/test/simulate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as he:
        err_msg = he.read().decode("utf-8")
        raise HTTPException(status_code=he.code, detail=err_msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Simulation error: {e}")
