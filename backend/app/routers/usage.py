from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.usage import UsageResponse
from app.services.usage_service import UsageService


router = APIRouter(
    prefix="/usage",
    tags=["Usage"]
)

usage_service = UsageService()


@router.get(
    "/",
    response_model=UsageResponse,
    summary="Usage summary",
    description=(
        "Activity counts from existing data: devices, applications, "
        "uplink telemetry messages and downlink commands. Not billing. "
        "Tenant admins always get their own tenant; admins get all "
        "tenants, or one with tenant_id."
    )
)
def get_usage(
    tenant_id: int | None = Query(
        None,
        description="Admin only: limit to one tenant"
    ),
    start: datetime | None = Query(
        None,
        description="Count messages at or after this time (UTC if no timezone)"
    ),
    end: datetime | None = Query(
        None,
        description="Count messages at or before this time (UTC if no timezone)"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return usage_service.get_usage(
        db,
        current_user,
        tenant_id,
        start,
        end
    )
