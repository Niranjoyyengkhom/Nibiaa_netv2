from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
def get_health():
    return {
        "status": "ok",
        "service": "nibiaanet-decoder",
        "port": 3001,
        "features": {
            "sandbox": "node-vm-runner",
            "udp_ingestion": True,
            "mqtt_ingestion": True,
            "async_queue": True
        }
    }
