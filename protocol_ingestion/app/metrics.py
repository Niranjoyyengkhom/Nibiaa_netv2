import time
from datetime import datetime, timezone
from typing import Any, Dict, List

START_TIME = time.time()

COUNTERS = {
    "udp": 0,
    "mqtt": 0,
    "tcp": 0,
    "webhook": 0,
    "total": 0,
    "routed": 0,
    "errors": 0,
}

RECENT_ACTIVITY: List[Dict[str, Any]] = []
MAX_ACTIVITY_LOGS = 50

LISTENER_STATUS = {
    "udp": {"port": 5001, "status": "initializing", "protocol": "UDP / Datagram"},
    "mqtt": {"port": 1883, "status": "initializing", "protocol": "MQTT 3.1.1 Broker"},
    "tcp": {"port": 1001, "status": "initializing", "protocol": "TCP / Socket Stream"},
    "webhook": {"port": 1002, "status": "initializing", "protocol": "HTTP / Webhook REST"},
}


def record_message(protocol: str, device_id: str, payload_summary: str, status: str = "routed", details: str = ""):
    COUNTERS["total"] += 1
    if protocol in COUNTERS:
        COUNTERS[protocol] += 1

    if status == "routed":
        COUNTERS["routed"] += 1
    else:
        COUNTERS["errors"] += 1

    entry = {
        "id": COUNTERS["total"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "protocol": protocol.upper(),
        "device_id": device_id or "UNKNOWN",
        "payload": payload_summary[:100],
        "status": status,
        "details": details,
    }

    RECENT_ACTIVITY.insert(0, entry)
    if len(RECENT_ACTIVITY) > MAX_ACTIVITY_LOGS:
        RECENT_ACTIVITY.pop()


def get_stats() -> Dict[str, Any]:
    uptime_sec = int(time.time() - START_TIME)
    return {
        "uptime_seconds": uptime_sec,
        "uptime_formatted": f"{uptime_sec // 3600}h {(uptime_sec % 3600) // 60}m {uptime_sec % 60}s",
        "listeners": LISTENER_STATUS,
        "counters": COUNTERS,
        "recent_activity": RECENT_ACTIVITY[:20],
    }
