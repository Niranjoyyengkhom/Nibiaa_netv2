from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit import IAMAuditLog
from app.models.user import User
from app.schemas.audit import AuditLogResponse
from app.dependencies.auth import get_current_user

router = APIRouter(prefix="/audit", tags=["Security Audit Trail"])


@router.get("/", response_model=List[AuditLogResponse])
def get_audit_logs(
    action: Optional[str] = Query(None, description="Filter by action code"),
    target_type: Optional[str] = Query(None, description="user, role, attribute, policy"),
    actor_id: Optional[int] = Query(None, description="Filter by actor user ID"),
    tenant_id: Optional[int] = Query(None, description="Filter by tenant ID"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(IAMAuditLog)

    if current_user.role != "admin":
        tenant_id = current_user.tenant_id
        query = query.filter((IAMAuditLog.tenant_id == tenant_id) | (IAMAuditLog.tenant_id.is_(None)))
    elif tenant_id is not None:
        query = query.filter(IAMAuditLog.tenant_id == tenant_id)

    if action:
        query = query.filter(IAMAuditLog.action == action.strip().upper())
    if target_type:
        query = query.filter(IAMAuditLog.target_type == target_type.strip().lower())
    if actor_id is not None:
        query = query.filter(IAMAuditLog.actor_id == actor_id)

    return query.order_by(IAMAuditLog.created_at.desc()).offset(offset).limit(limit).all()
