"""
Messages decoded by the decoder server.

The decoder server stores every message it decodes - from devices, and
from runs in the frontend's decoder editor - in public.decoded_messages_store
with encrypted payloads. This router reads them and decrypts the bodies.

Supports pagination via limit, page, and offset parameters.

Visible to admins, and to owners / collaborators with Read Application
Traffic for messages of their organization: runs by its users, and
messages from its devices.
"""

import json
import math
from datetime import datetime, timezone
from typing import Literal, Optional, Any, Dict, List

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError, OperationalError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services.device_service import DeviceService
from app.services.telemetry_service import TRAFFIC_PERMISSION
from app.security.crypto import decrypt_json


router = APIRouter(
    prefix="/decoder-messages",
    tags=["Decoder Messages"]
)

device_service = DeviceService()

# PostgreSQL Queries with pagination
MESSAGES_QUERY = text(
    """
    SELECT m.status, m.body, m.received_at, m.message_id, m.device_id, m.transport
    FROM public.decoded_messages_store m
    WHERE (
            CAST(:tenant_id AS INTEGER) IS NULL
            OR m.tenant_id = :tenant_id
            OR m.device_id IN (
                SELECT d.device_id
                FROM public.devices d
                WHERE d.tenant_id = :tenant_id
            )
        )
      AND (CAST(:status AS TEXT) IS NULL OR m.status = :status)
      AND (CAST(:device_id AS TEXT) IS NULL OR m.device_id = :device_id)
    ORDER BY m.received_at DESC, m.message_id DESC
    OFFSET :offset
    LIMIT :limit
    """
)

COUNT_QUERY = text(
    """
    SELECT COUNT(*)
    FROM public.decoded_messages_store m
    WHERE (
            CAST(:tenant_id AS INTEGER) IS NULL
            OR m.tenant_id = :tenant_id
            OR m.device_id IN (
                SELECT d.device_id
                FROM public.devices d
                WHERE d.tenant_id = :tenant_id
            )
        )
      AND (CAST(:status AS TEXT) IS NULL OR m.status = :status)
      AND (CAST(:device_id AS TEXT) IS NULL OR m.device_id = :device_id)
    """
)

FALLBACK_MESSAGES_QUERY = text(
    """
    SELECT m.status, m.body, m.received_at, m.message_id, m.device_id, m.transport
    FROM decoder.decoded_messages m
    WHERE (
            CAST(:tenant_id AS INTEGER) IS NULL
            OR m.tenant_id = :tenant_id
            OR m.device_id IN (
                SELECT d.device_id
                FROM public.devices d
                WHERE d.tenant_id = :tenant_id
            )
        )
      AND (CAST(:status AS TEXT) IS NULL OR m.status = :status)
      AND (CAST(:device_id AS TEXT) IS NULL OR m.device_id = :device_id)
    ORDER BY m.received_at DESC, m.message_id DESC
    OFFSET :offset
    LIMIT :limit
    """
)

FALLBACK_COUNT_QUERY = text(
    """
    SELECT COUNT(*)
    FROM decoder.decoded_messages m
    WHERE (
            CAST(:tenant_id AS INTEGER) IS NULL
            OR m.tenant_id = :tenant_id
            OR m.device_id IN (
                SELECT d.device_id
                FROM public.devices d
                WHERE d.tenant_id = :tenant_id
            )
        )
      AND (CAST(:status AS TEXT) IS NULL OR m.status = :status)
      AND (CAST(:device_id AS TEXT) IS NULL OR m.device_id = :device_id)
    """
)


@router.get(
    "/",
    summary="List messages decoded by the decoder server",
    description=(
        "Newest first. Supports pagination with page & limit. Each item is the decoded "
        "(or failed) message as the decoder server delivered it, plus its status. "
        "Collaborators need the Read Application Traffic function."
    )
)
def list_decoder_messages(
    status: Literal["decoded", "failed"] | None = Query(None),
    device_id: str | None = Query(None),
    limit: int = Query(25, ge=1, le=500),
    page: int = Query(1, ge=1),
    offset: int | None = Query(None, ge=0),
    as_list: bool = Query(False),
    response: Response = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # None = every organization (admin); enforces role and function
    tenant_id = device_service.scoped_tenant_id(
        db,
        current_user,
        TRAFFIC_PERMISSION
    )

    actual_offset = offset if offset is not None else (page - 1) * limit
    params = {
        "tenant_id": tenant_id,
        "status": status,
        "device_id": device_id,
        "limit": limit,
        "offset": actual_offset,
    }
    count_params = {
        "tenant_id": tenant_id,
        "status": status,
        "device_id": device_id,
    }

    rows = []
    total_count = 0
    try:
        rows = db.execute(MESSAGES_QUERY, params).all()
        total_count = db.execute(COUNT_QUERY, count_params).scalar() or 0
    except Exception:
        try:
            db.rollback()
            rows = db.execute(FALLBACK_MESSAGES_QUERY, params).all()
            total_count = db.execute(FALLBACK_COUNT_QUERY, count_params).scalar() or 0
        except Exception:
            db.rollback()
            if as_list:
                return []
            return {"items": [], "total": 0, "page": page, "limit": limit, "pages": 1}

    results = []
    for row in rows:
        raw_body = getattr(row, "body", None)
        body = decrypt_json(raw_body)
        if not isinstance(body, dict):
            body = {}

        # Format received_at strictly in UTC ISO-8601 string
        rec_at = getattr(row, "received_at", None)
        rec_str = None
        if rec_at is not None:
            if isinstance(rec_at, str):
                s = rec_at.strip().replace(" ", "T")
                if not s.endswith("Z") and "+" not in s:
                    s += "Z"
                rec_str = s
            elif hasattr(rec_at, "isoformat"):
                if rec_at.tzinfo is None:
                    rec_at = rec_at.replace(tzinfo=timezone.utc)
                rec_str = rec_at.isoformat()
            else:
                rec_str = str(rec_at)
        else:
            rec_str = body.get("receivedAt") or body.get("received_at") or body.get("timestamp")

        item = {
            **body,
            "status": getattr(row, "status", None) or body.get("status"),
        }
        if rec_str:
            item["received_at"] = rec_str
            item["receivedAt"] = rec_str
        elif not item.get("receivedAt") and item.get("received_at"):
            item["receivedAt"] = item["received_at"]
        if getattr(row, "message_id", None) and not item.get("messageId"):
            item["messageId"] = row.message_id
        if getattr(row, "device_id", None) and not item.get("deviceId"):
            item["deviceId"] = row.device_id
        if getattr(row, "transport", None) and not item.get("transport"):
            item["transport"] = row.transport

        results.append(item)

    total_pages = max(1, math.ceil(total_count / limit)) if limit > 0 else 1

    if response is not None:
        response.headers["X-Total-Count"] = str(total_count)
        response.headers["X-Page"] = str(page)
        response.headers["X-Per-Page"] = str(limit)
        response.headers["X-Total-Pages"] = str(total_pages)

    if as_list:
        return results

    return {
        "items": results,
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": total_pages,
    }
