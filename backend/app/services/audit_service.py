import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Union
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc, func

from app.models.audit_log import AuditLog
from app.models.user import User
from app.models.tenant import Tenant
from app.schemas.audit_log import AuditLogResponse, AuditLogStatsResponse

logger = logging.getLogger("nibiaanet.audit")


class AuditService:
    def log_event(
        self,
        db: Session,
        action: str,
        category: str = "GENERAL",
        user: Optional[User] = None,
        user_id: Optional[int] = None,
        user_name: Optional[str] = None,
        tenant_id: Optional[int] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Union[Dict[str, Any], str]] = None,
        ip_address: Optional[str] = None,
        status: str = "SUCCESS",
    ) -> AuditLog:
        """
        Record an audit log entry in the database.
        """
        try:
            uid = user_id or (user.id if user else None)
            uname = user_name or (user.name if user else "System")
            tid = tenant_id or (user.tenant_id if user else None)

            detail_str = None
            if details is not None:
                if isinstance(details, (dict, list)):
                    detail_str = json.dumps(details, default=str)
                else:
                    detail_str = str(details)

            entry = AuditLog(
                user_id=uid,
                user_name=uname,
                tenant_id=tid,
                action=action,
                category=category.upper(),
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id is not None else None,
                details=detail_str,
                ip_address=ip_address,
                status=status.upper(),
            )
            db.add(entry)
            db.commit()
            db.refresh(entry)
            return entry
        except Exception as e:
            logger.warning(f"Failed to record audit log: {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return None

    def get_audit_logs(
        self,
        db: Session,
        current_user: User,
        category: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        user_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditLogResponse]:
        """
        Query audit logs filtered by user tenant permissions and criteria.
        Admins see all logs; non-admins see logs for their tenant.
        """
        query = db.query(AuditLog)

        # Multi-tenant scoping: non-admin users only see logs for their tenant
        if current_user.role != "admin":
            if current_user.tenant_id is not None:
                query = query.filter(
                    or_(
                        AuditLog.tenant_id == current_user.tenant_id,
                        AuditLog.user_id == current_user.id
                    )
                )
            else:
                query = query.filter(AuditLog.user_id == current_user.id)

        # Filters
        if category and category.strip() and category.upper() != "ALL":
            query = query.filter(AuditLog.category == category.strip().upper())

        if status and status.strip() and status.upper() != "ALL":
            query = query.filter(AuditLog.status == status.strip().upper())

        if user_id is not None:
            query = query.filter(AuditLog.user_id == user_id)

        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    AuditLog.action.ilike(term),
                    AuditLog.user_name.ilike(term),
                    AuditLog.resource_type.ilike(term),
                    AuditLog.resource_id.ilike(term),
                    AuditLog.details.ilike(term),
                    AuditLog.ip_address.ilike(term),
                )
            )

        logs = query.order_by(desc(AuditLog.timestamp)).offset(offset).limit(limit).all()

        # Resolve tenant names
        tenant_ids = {log.tenant_id for log in logs if log.tenant_id}
        tenants_map = {}
        if tenant_ids:
            t_rows = db.query(Tenant.id, Tenant.name).filter(Tenant.id.in_(tenant_ids)).all()
            tenants_map = {t.id: t.name for t in t_rows}

        results = []
        for log in logs:
            results.append(
                AuditLogResponse(
                    id=log.id,
                    timestamp=log.timestamp,
                    user_id=log.user_id,
                    user_name=log.user_name,
                    tenant_id=log.tenant_id,
                    tenant_name=tenants_map.get(log.tenant_id),
                    action=log.action,
                    category=log.category,
                    resource_type=log.resource_type,
                    resource_id=log.resource_id,
                    details=log.details,
                    ip_address=log.ip_address,
                    status=log.status,
                )
            )
        return results

    def get_stats(self, db: Session, current_user: User) -> AuditLogStatsResponse:
        """
        Aggregate counts and metrics for the audit dashboard cards.
        """
        query = db.query(AuditLog)
        if current_user.role != "admin":
            if current_user.tenant_id is not None:
                query = query.filter(
                    or_(
                        AuditLog.tenant_id == current_user.tenant_id,
                        AuditLog.user_id == current_user.id
                    )
                )
            else:
                query = query.filter(AuditLog.user_id == current_user.id)

        total_logs = query.count()
        success_count = query.filter(AuditLog.status == "SUCCESS").count()
        failed_count = query.filter(AuditLog.status == "FAILED").count()

        # Actions today (last 24 hours)
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        actions_today = query.filter(AuditLog.timestamp >= since).count()

        # Category breakdown
        cat_counts = (
            query.with_entities(AuditLog.category, func.count(AuditLog.id))
            .group_by(AuditLog.category)
            .all()
        )
        categories = {cat: count for cat, count in cat_counts if cat}

        return AuditLogStatsResponse(
            total_logs=total_logs,
            success_count=success_count,
            failed_count=failed_count,
            actions_today=actions_today,
            categories=categories,
        )

    def seed_initial_logs(self, db: Session):
        """
        Seeds realistic system audit history if the audit log table is empty.
        """
        if db.query(AuditLog).count() > 0:
            return

        now = datetime.now(timezone.utc)
        sample_logs = [
            {
                "offset_min": 180,
                "action": "SYSTEM_STARTUP",
                "category": "SYSTEM",
                "user_name": "System",
                "tenant_id": None,
                "resource_type": "core",
                "resource_id": "v2.0",
                "details": {"event": "Server initialized with PostgreSQL & Apache Cassandra enterprise engine", "version": "2.0.0"},
                "ip_address": "127.0.0.1",
                "status": "SUCCESS",
            },
            {
                "offset_min": 165,
                "action": "USER_LOGIN",
                "category": "AUTH",
                "user_name": "Nibiaa",
                "user_id": 1,
                "tenant_id": 1,
                "resource_type": "session",
                "resource_id": "admin_session",
                "details": {"method": "password", "role": "admin", "browser": "Chrome / Windows"},
                "ip_address": "127.0.0.1",
                "status": "SUCCESS",
            },
            {
                "offset_min": 140,
                "action": "APPLICATION_CREATED",
                "category": "APPLICATION",
                "user_name": "Nibiaa",
                "user_id": 1,
                "tenant_id": 1,
                "resource_type": "application",
                "resource_id": "1",
                "details": {"name": "MainApp", "tenant": "Main Org"},
                "ip_address": "127.0.0.1",
                "status": "SUCCESS",
            },
            {
                "offset_min": 120,
                "action": "DECODER_REGISTERED",
                "category": "DECODER",
                "user_name": "Nibiaa",
                "user_id": 1,
                "tenant_id": None,
                "resource_type": "decoder",
                "resource_id": "environmental_sensors",
                "details": {"kind": "fields", "version": "v1", "scope": "platform"},
                "ip_address": "127.0.0.1",
                "status": "SUCCESS",
            },
            {
                "offset_min": 90,
                "action": "DEVICE_AUTO_PROVISIONED",
                "category": "DEVICE",
                "user_name": "DecoderService",
                "tenant_id": 1,
                "resource_type": "device",
                "resource_id": "08d1f9d120c0",
                "details": {"deviceType": "NTN", "network": "satellite", "app": "MainApp"},
                "ip_address": "127.0.0.1",
                "status": "SUCCESS",
            },
            {
                "offset_min": 60,
                "action": "USER_LOGIN_FAILED",
                "category": "SECURITY",
                "user_name": "unknown_admin",
                "tenant_id": None,
                "resource_type": "auth",
                "resource_id": "unknown_admin",
                "details": {"reason": "Invalid credentials", "attempt": 1},
                "ip_address": "192.168.1.105",
                "status": "FAILED",
            },
            {
                "offset_min": 45,
                "action": "ROLE_PERMISSIONS_UPDATED",
                "category": "USER_MANAGEMENT",
                "user_name": "Nibiaa",
                "user_id": 1,
                "tenant_id": 1,
                "resource_type": "role",
                "resource_id": "Admin",
                "details": {"role": "admin", "permissions_count": 8},
                "ip_address": "127.0.0.1",
                "status": "SUCCESS",
            },
            {
                "offset_min": 25,
                "action": "DEVICE_AUTO_PROVISIONED",
                "category": "DEVICE",
                "user_name": "DecoderService",
                "tenant_id": 1,
                "resource_type": "device",
                "resource_id": "SENSOR-901",
                "details": {"deviceType": "NTN", "network": "satellite", "app": "MainApp"},
                "ip_address": "127.0.0.1",
                "status": "SUCCESS",
            },
            {
                "offset_min": 5,
                "action": "UPLINK_DECODED",
                "category": "TELEMETRY",
                "user_name": "DecoderService",
                "tenant_id": 1,
                "resource_type": "message",
                "resource_id": "001122334455",
                "details": {"protocol": "udp", "payloadBytes": 22, "result": "temperature=20C, humidity=50%"},
                "ip_address": "127.0.0.1",
                "status": "SUCCESS",
            },
        ]

        for item in sample_logs:
            entry = AuditLog(
                timestamp=now - timedelta(minutes=item["offset_min"]),
                action=item["action"],
                category=item["category"],
                user_id=item.get("user_id"),
                user_name=item["user_name"],
                tenant_id=item.get("tenant_id"),
                resource_type=item["resource_type"],
                resource_id=item["resource_id"],
                details=json.dumps(item["details"]),
                ip_address=item["ip_address"],
                status=item["status"],
            )
            db.add(entry)
        db.commit()
        logger.info(f"Seeded {len(sample_logs)} initial audit logs.")
