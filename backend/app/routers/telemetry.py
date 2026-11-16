from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.connectivity_profile import ConnectionType
from app.schemas.telemetry import TelemetryResponse
from app.services.telemetry_service import (
    DEFAULT_TELEMETRY_LIMIT,
    MAX_TELEMETRY_LIMIT,
    TelemetryService,
)


router = APIRouter(
    prefix="/devices",
    tags=["Telemetry"]
)

telemetry_service = TelemetryService()


@router.get(
    "/{device_id}/telemetry",
    response_model=list[TelemetryResponse],
    summary="List telemetry of a device",
    description=(
        "Newest first. start/end filter on the measurement timestamp. "
        "Collaborators need the Read Application Traffic function."
    )
)
def get_telemetry(
    device_id: str,
    limit: int = Query(
        DEFAULT_TELEMETRY_LIMIT,
        ge=1,
        le=MAX_TELEMETRY_LIMIT
    ),
    start: datetime | None = Query(
        None,
        description="Only records at or after this time (ISO 8601; UTC if no timezone)"
    ),
    end: datetime | None = Query(
        None,
        description="Only records at or before this time (ISO 8601; UTC if no timezone)"
    ),
    connection_type: ConnectionType | None = Query(
        None,
        description="NTN (satellite) or TN (terrestrial)"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return telemetry_service.get_telemetry(
        db,
        device_id,
        current_user,
        limit,
        start,
        end,
        connection_type
    )


@router.get(
    "/{device_id}/latest",
    response_model=TelemetryResponse,
    summary="Latest telemetry of a device",
    description="404 if the device has not sent any telemetry yet."
)
def get_latest(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return telemetry_service.get_latest(
        db,
        device_id,
        current_user
    )


# Fleet-wide history, across the devices the user can see
fleet_router = APIRouter(
    prefix="/telemetry",
    tags=["Telemetry"]
)


@fleet_router.get(
    "/",
    response_model=list[TelemetryResponse],
    summary="List telemetry of the fleet (application traffic)",
    description=(
        "Newest first, across all devices of the organization. Admins see "
        "every organization, or one with tenant_id. Collaborators need "
        "the Read Application Traffic function."
    )
)
def get_fleet_telemetry(
    limit: int = Query(
        DEFAULT_TELEMETRY_LIMIT,
        ge=1,
        le=MAX_TELEMETRY_LIMIT
    ),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    connection_type: ConnectionType | None = Query(None),
    provider: str | None = Query(None),
    tenant_id: int | None = Query(None),
    application_id: int | None = Query(None),
    device_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return telemetry_service.get_fleet_telemetry(
        db,
        current_user,
        limit,
        start,
        end,
        connection_type,
        provider,
        tenant_id,
        application_id,
        device_id
    )
