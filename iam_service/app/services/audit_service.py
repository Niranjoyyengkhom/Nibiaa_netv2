import logging
from typing import Optional, Any
from sqlalchemy.orm import Session
from app.models.audit import IAMAuditLog

logger = logging.getLogger("nibiaanet.iam.audit")


class AuditService:
    @staticmethod
    def log(
        db: Session,
        action: str,
        target_type: str,
        target_id: Optional[str] = None,
        actor_id: Optional[int] = None,
        actor_name: Optional[str] = None,
        tenant_id: Optional[int] = None,
        details: Optional[Any] = None,
        ip_address: Optional[str] = None,
    ) -> IAMAuditLog:
        try:
            entry = IAMAuditLog(
                actor_id=actor_id,
                actor_name=actor_name,
                action=action,
                target_type=target_type,
                target_id=str(target_id) if target_id is not None else None,
                tenant_id=tenant_id,
                details=details,
                ip_address=ip_address,
            )
            db.add(entry)
            db.commit()
            return entry
        except Exception as e:
            logger.warning(f"Failed to record IAM audit log: {e}")
            db.rollback()
            return None


audit_service = AuditService()
