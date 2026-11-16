import io
import csv
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.audit_log import AuditLogResponse, AuditLogCreate, AuditLogStatsResponse
from app.services.audit_service import AuditService

router = APIRouter(
    prefix="/audit-logs",
    tags=["Audit & Logs"]
)

audit_service = AuditService()

AUDIT_CATEGORIES = [
    "ALL",
    "AUTH",
    "USER_MANAGEMENT",
    "ORGANIZATION",
    "APPLICATION",
    "DEVICE",
    "DECODER",
    "SECURITY",
    "TELEMETRY",
    "SYSTEM",
]


@router.get(
    "/",
    response_model=List[AuditLogResponse],
    summary="List audit logs",
    description="Retrieve system audit and activity logs with multi-tenant filtering."
)
def get_audit_logs(
    category: Optional[str] = Query(None, description="Category filter (e.g. AUTH, USER_MANAGEMENT, DEVICE)"),
    status: Optional[str] = Query(None, description="Status filter (SUCCESS, FAILED, WARNING)"),
    search: Optional[str] = Query(None, description="Search term across action, user, details, IP"),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return audit_service.get_audit_logs(
        db=db,
        current_user=current_user,
        category=category,
        status=status,
        search=search,
        user_id=user_id,
        limit=limit,
        offset=offset
    )


@router.get(
    "/stats",
    response_model=AuditLogStatsResponse,
    summary="Audit log statistics",
    description="Returns aggregate counts for audit dashboard metric cards."
)
def get_audit_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return audit_service.get_stats(db=db, current_user=current_user)


@router.get(
    "/categories",
    response_model=List[str],
    summary="Available audit categories"
)
def get_audit_categories():
    return AUDIT_CATEGORIES


@router.post(
    "/",
    response_model=AuditLogResponse,
    summary="Record custom audit log entry"
)
def create_audit_log(
    data: AuditLogCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    client_ip = data.ip_address or (request.client.host if request.client else None)
    entry = audit_service.log_event(
        db=db,
        action=data.action,
        category=data.category,
        user=current_user,
        user_id=data.user_id or current_user.id,
        user_name=data.user_name or current_user.name,
        tenant_id=data.tenant_id or current_user.tenant_id,
        resource_type=data.resource_type,
        resource_id=data.resource_id,
        details=data.details,
        ip_address=client_ip,
        status=data.status
    )
    if not entry:
        raise HTTPException(status_code=500, detail="Failed to write audit log entry")

    return AuditLogResponse(
        id=entry.id,
        timestamp=entry.timestamp,
        user_id=entry.user_id,
        user_name=entry.user_name,
        tenant_id=entry.tenant_id,
        action=entry.action,
        category=entry.category,
        resource_type=entry.resource_type,
        resource_id=entry.resource_id,
        details=entry.details,
        ip_address=entry.ip_address,
        status=entry.status
    )


@router.get(
    "/export",
    summary="Export audit logs to CSV"
)
def export_audit_logs(
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    logs = audit_service.get_audit_logs(
        db=db,
        current_user=current_user,
        category=category,
        status=status,
        search=search,
        limit=5000,
        offset=0
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Timestamp (UTC)", "User", "Tenant", "Category", 
        "Action", "Resource Type", "Resource ID", "Status", "IP Address", "Details"
    ])

    for log in logs:
        writer.writerow([
            log.id,
            log.timestamp.isoformat() if log.timestamp else "",
            log.user_name or "System",
            log.tenant_name or "Global",
            log.category,
            log.action,
            log.resource_type or "",
            log.resource_id or "",
            log.status,
            log.ip_address or "",
            log.details or ""
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=nibiaanet_audit_logs.csv"}
    )
