import os
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.ingestion_profile import IngestionProfile
from app.models.connectivity_profile import ConnectivityProfile
from app.dependencies.auth import get_current_user
from app.models.user import User

logger = logging.getLogger("nibiaanet.router.ingestion_profiles")

security_optional = HTTPBearer(auto_error=False)


def get_current_user_flexible(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if not auth:
        return None
    try:
        return get_current_user(auth, db)
    except Exception:
        return None

router = APIRouter(
    prefix="/ingestion-profiles",
    tags=["Ingestion Profile Microservice"],
)

PROTOCOL_INGESTION_SERVICE_URL = "http://127.0.0.1:1002"

# System defaults
DEFAULT_PROFILES = [
    {
        "code": "default_udp",
        "name": "UDP Datagram Listener",
        "protocol": "udp",
        "network_profile_code": "all",
        "use_default": True,
        "default_port": 5001,
        "custom_port": None,
        "host": "localhost",
        "auth_type": "none",
        "custom_path": None,
        "is_enabled": True,
        "description": "High-throughput UDP packet listener for NTN satellite datagrams and LPWAN uplinks.",
    },
    {
        "code": "default_mqtt",
        "name": "MQTT Broker Listener",
        "protocol": "mqtt",
        "network_profile_code": "all",
        "use_default": True,
        "default_port": 1883,
        "custom_port": None,
        "host": "localhost",
        "auth_type": "none",
        "custom_path": "devices/+/up",
        "is_enabled": True,
        "description": "Built-in lightweight MQTT 3.1.1 broker for IoT sensor streams and gateway telemetry.",
    },
    {
        "code": "default_tcp",
        "name": "TCP Socket Stream Listener",
        "protocol": "tcp",
        "network_profile_code": "all",
        "use_default": True,
        "default_port": 1001,
        "custom_port": None,
        "host": "localhost",
        "auth_type": "none",
        "custom_path": None,
        "is_enabled": True,
        "description": "Direct TCP socket stream listener with newline and length-prefix packet framing.",
    },
    {
        "code": "default_webhook",
        "name": "HTTP Webhook Receiver",
        "protocol": "webhook",
        "network_profile_code": "all",
        "use_default": True,
        "default_port": 1002,
        "custom_port": None,
        "host": "localhost",
        "auth_type": "none",
        "custom_path": "/webhook",
        "is_enabled": True,
        "description": "REST Webhook receiver for third-party ground segments (Hubble, Skylo, cellular aggregators).",
    },
    {
        "code": "hubble_network",
        "name": "Hubble Network Ingestion",
        "protocol": "webhook",
        "network_profile_code": "hubble",
        "use_default": True,
        "default_port": 1002,
        "custom_port": None,
        "host": "localhost",
        "auth_type": "hubble_secret",
        "auth_username": None,
        "auth_password": None,
        "auth_token": "",
        "custom_path": "/webhooks/hubble",
        "is_enabled": True,
        "description": "Dedicated ingestion profile for Hubble Network satellite uplinks with Secret Key (HTTP-X-HUBBLE-TOKEN) authentication.",
    },
]


def ensure_default_ingestion_profiles(db: Session):
    """Seed initial ingestion profiles if table is empty and ensure Hubble uses Secret Key."""
    for item in DEFAULT_PROFILES:
        existing = db.query(IngestionProfile).filter(IngestionProfile.code == item["code"]).first()
        if not existing:
            profile = IngestionProfile(**item)
            db.add(profile)
        elif item["code"] == "hubble_network" and existing.auth_type == "basic_auth":
            # Migrate existing Hubble profile to Secret Key mode (no basic auth required)
            existing.auth_type = "hubble_secret"
            existing.auth_username = None
            db.add(existing)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error seeding default ingestion profiles: {e}")


class IngestionProfileUpdateSchema(BaseModel):
    name: Optional[str] = None
    protocol: Optional[str] = None
    network_profile_code: Optional[str] = None
    use_default: bool = True
    custom_port: Optional[int] = None
    host: Optional[str] = "localhost"
    auth_type: Optional[str] = "none"
    auth_username: Optional[str] = None
    auth_password: Optional[str] = None
    auth_token: Optional[str] = None
    custom_path: Optional[str] = None
    is_enabled: bool = True
    description: Optional[str] = None


class IngestionProfileCreateSchema(BaseModel):
    code: str
    name: str
    protocol: str  # "udp", "mqtt", "tcp", "webhook"
    network_profile_code: str = "all"
    use_default: bool = True
    default_port: Optional[int] = None
    custom_port: Optional[int] = None
    host: str = "localhost"
    auth_type: str = "none"
    auth_username: Optional[str] = None
    auth_password: Optional[str] = None
    auth_token: Optional[str] = None
    custom_path: Optional[str] = None
    is_enabled: bool = True
    description: Optional[str] = None


@router.get("")
def list_ingestion_profiles(request: Request, db: Session = Depends(get_db)):
    """List all Ingestion Profiles and their configuration (default vs admin provided)."""
    ensure_default_ingestion_profiles(db)
    profiles = db.query(IngestionProfile).order_by(IngestionProfile.id.asc()).all()
    
    # Also fetch network profiles to associate them
    net_profiles = db.query(ConnectivityProfile).all()
    net_map = {np.code: np.name for np in net_profiles}

    default_domain = os.getenv("DOMAIN", "nibiaanet.nibiaa.com").strip()
    req_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if req_host:
        req_host = req_host.split(":")[0].strip()
    live_host = req_host if (req_host and req_host not in ["backend", "frontend", "127.0.0.1", "localhost"]) else default_domain

    result = []
    for p in profiles:
        effective_host = p.host if (p.host and p.host not in ["localhost", "127.0.0.1", "0.0.0.0"]) else live_host
        is_webhook = (p.protocol or "").lower() == "webhook"
        effective_port = 443 if is_webhook else p.effective_port
        clean_path = p.custom_path or ("/webhook" if is_webhook else "")

        if is_webhook:
            live_uri = f"https://{effective_host}{clean_path if clean_path.startswith('/') else '/' + clean_path}"
        elif p.protocol == "mqtt":
            live_uri = f"mqtt://{effective_host}:{effective_port}/{clean_path or 'devices/+/up'}"
        elif p.protocol == "tcp":
            live_uri = f"tcp://{effective_host}:{effective_port}"
        elif p.protocol == "udp":
            live_uri = f"udp://{effective_host}:{effective_port}"
        else:
            live_uri = f"{effective_host}:{effective_port}"

        result.append({
            "id": p.id,
            "code": p.code,
            "name": p.name,
            "protocol": p.protocol,
            "network_profile_code": p.network_profile_code,
            "network_profile_name": net_map.get(p.network_profile_code, "Global (All Providers)"),
            "use_default": p.use_default,
            "default_port": p.default_port,
            "custom_port": p.custom_port,
            "effective_port": effective_port,
            "host": effective_host,
            "live_host": effective_host,
            "live_uri": live_uri,
            "auth_type": p.auth_type,
            "auth_username": p.auth_username,
            "auth_password": "***" if p.auth_password else None,
            "has_password": bool(p.auth_password),
            "auth_token": "***" if p.auth_token else None,
            "has_token": bool(p.auth_token),
            "custom_path": p.custom_path,
            "is_enabled": p.is_enabled,
            "description": p.description,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        })
    return {"profiles": result}


@router.post("")
def create_ingestion_profile(
    data: IngestionProfileCreateSchema,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_flexible),
):
    """Admin creates a new protocol ingestion profile."""
    existing = db.query(IngestionProfile).filter(IngestionProfile.code == data.code).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Ingestion profile '{data.code}' already exists")

    def_port = data.default_port
    if not def_port:
        defaults = {"udp": 5001, "mqtt": 1883, "tcp": 1001, "webhook": 1002}
        def_port = defaults.get(data.protocol.lower(), 1002)

    profile = IngestionProfile(
        code=data.code,
        name=data.name,
        protocol=data.protocol.lower(),
        network_profile_code=data.network_profile_code,
        use_default=data.use_default,
        default_port=def_port,
        custom_port=data.custom_port,
        host=data.host,
        auth_type=data.auth_type,
        auth_username=data.auth_username,
        auth_password=data.auth_password,
        auth_token=data.auth_token,
        custom_path=data.custom_path,
        is_enabled=data.is_enabled,
        description=data.description,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return {"status": "created", "profile_id": profile.id, "code": profile.code}


@router.put("/{profile_id}")
def update_ingestion_profile(
    profile_id: int,
    data: IngestionProfileUpdateSchema,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_flexible),
):
    """Admin updates an ingestion profile (e.g. toggles default vs custom values)."""
    profile = db.query(IngestionProfile).filter(IngestionProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Ingestion profile not found")

    if data.name is not None:
        profile.name = data.name
    if data.protocol is not None:
        profile.protocol = data.protocol.lower()
    if data.network_profile_code is not None:
        profile.network_profile_code = data.network_profile_code

    profile.use_default = data.use_default
    profile.custom_port = data.custom_port
    if data.host is not None:
        profile.host = data.host
    if data.auth_type is not None:
        profile.auth_type = data.auth_type
    if data.auth_username is not None:
        profile.auth_username = data.auth_username
    if data.auth_password is not None and data.auth_password != "***":
        profile.auth_password = data.auth_password
    if data.auth_token is not None and data.auth_token != "***":
        profile.auth_token = data.auth_token
    if data.custom_path is not None:
        profile.custom_path = data.custom_path
    profile.is_enabled = data.is_enabled
    if data.description is not None:
        profile.description = data.description

    db.commit()
    db.refresh(profile)
    return {
        "status": "updated",
        "profile": {
            "id": profile.id,
            "code": profile.code,
            "name": profile.name,
            "use_default": profile.use_default,
            "effective_port": profile.effective_port,
            "is_enabled": profile.is_enabled,
        }
    }


@router.post("/{profile_id}/toggle-mode")
def toggle_profile_mode(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_flexible),
):
    """Quickly toggle between Default Value and Admin-Provided Value."""
    profile = db.query(IngestionProfile).filter(IngestionProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Ingestion profile not found")

    profile.use_default = not profile.use_default
    db.commit()
    return {
        "status": "toggled",
        "use_default": profile.use_default,
        "effective_port": profile.effective_port,
    }


@router.delete("/{profile_id}")
def delete_ingestion_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_flexible),
):
    """Delete a custom ingestion profile."""
    profile = db.query(IngestionProfile).filter(IngestionProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Ingestion profile not found")
    if profile.code in ["default_udp", "default_mqtt", "default_tcp", "default_webhook"]:
        raise HTTPException(status_code=400, detail="Cannot delete default system ingestion listener profile")

    db.delete(profile)
    db.commit()
    return {"status": "deleted", "id": profile_id}


@router.post("/reset-defaults")
def reset_all_to_defaults(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_flexible),
):
    """Admin resets all ingestion profiles back to microservice default ports and settings."""
    profiles = db.query(IngestionProfile).all()
    for p in profiles:
        p.use_default = True
        p.custom_port = None
        p.host = "localhost"
        p.is_enabled = True
    db.commit()
    return {"status": "reset", "message": "All ingestion profiles reverted to microservice default values"}


@router.get("/microservice-status")
def get_microservice_status():
    """Proxy live status from Protocol Ingestion Microservice."""
    try:
        req = urllib.request.Request(f"{PROTOCOL_INGESTION_SERVICE_URL}/status", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data
    except Exception as e:
        return {
            "status": "offline",
            "service": "Protocol Ingestion Microservice",
            "error": str(e),
            "listeners": {
                "udp": {"port": 5001, "status": "standby", "protocol": "UDP / Datagram"},
                "mqtt": {"port": 1883, "status": "standby", "protocol": "MQTT 3.1.1 Broker"},
                "tcp": {"port": 1001, "status": "standby", "protocol": "TCP / Socket Stream"},
                "webhook": {"port": 1002, "status": "standby", "protocol": "HTTP / Webhook REST"},
            },
            "counters": {"udp": 0, "mqtt": 0, "tcp": 0, "webhook": 0, "total": 0, "routed": 0, "errors": 0},
            "recent_activity": [],
        }


@router.post("/simulate")
async def simulate_uplink(request: Request):
    """Forward simulator request to Protocol Ingestion Microservice."""
    try:
        body = await request.body()
        req = urllib.request.Request(
            f"{PROTOCOL_INGESTION_SERVICE_URL}/test/simulate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as he:
        raise HTTPException(status_code=he.code, detail=he.read().decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Simulation error: {e}")
