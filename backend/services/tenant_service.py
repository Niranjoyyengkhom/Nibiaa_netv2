from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.decode_schema import DecodeSchema
from app.models.device import Device
from app.models.tenant import Tenant
from app.models.user import User
from app.models.webhook import Webhook
from app.schemas.tenant import TenantCreate, TenantUpdate
from app.services.notification_service import NotificationType, notify_tenant


class TenantService:

    def get_tenants(
        self,
        db: Session,
        current_user: User
    ):
        # Platform admins manage organizations globally
        if current_user.role == "admin":
            tenants = db.query(Tenant).order_by(Tenant.id).all()

        # Everyone else only sees their own organization
        # (so the frontend can show its name)
        elif current_user.tenant_id is not None:
            tenants = (
                db.query(Tenant)
                .filter(Tenant.id == current_user.tenant_id)
                .all()
            )

        else:
            tenants = []

        return [
            self.tenant_response(db, tenant)
            for tenant in tenants
        ]

    def create_tenant(
        self,
        db: Session,
        data: TenantCreate,
        current_user: User
    ):
        self._require_admin(current_user, "create organizations")

        tenant = Tenant(
            name=data.name.strip(),
            type=data.type
        )

        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        return self.tenant_response(db, tenant)

    def update_tenant(
        self,
        db: Session,
        tenant_id: int,
        data: TenantUpdate,
        current_user: User
    ):
        self._require_admin(current_user, "manage organizations")

        tenant = self._get_tenant(db, tenant_id)

        tenant.name = data.name.strip()
        tenant.type = data.type

        db.commit()
        db.refresh(tenant)

        return self.tenant_response(db, tenant)

    def set_active(
        self,
        db: Session,
        tenant_id: int,
        active: bool,
        current_user: User
    ):
        """
        Revoke Organization Access (active=False) / restore it.
        None of the organization's users can sign in or use the API
        while it is revoked. Its data is kept; uplinks of its devices
        are still received.
        """

        self._require_admin(current_user, "revoke organization access")

        tenant = self._get_tenant(db, tenant_id)
        tenant.is_active = active

        db.commit()
        db.refresh(tenant)

        notify_tenant(
            db,
            None,
            "Organization access restored" if active else "Organization access revoked",
            f"{current_user.name} {'restored' if active else 'revoked'} the access of {tenant.name}.",
            NotificationType.ORGANIZATION,
        )

        return self.tenant_response(db, tenant)

    def delete_tenant(
        self,
        db: Session,
        tenant_id: int,
        current_user: User
    ):
        self._require_admin(current_user, "delete organizations")

        tenant = self._get_tenant(db, tenant_id)

        # 1. Unlink users from this workspace
        db.query(User).filter(User.tenant_id == tenant.id).update({"tenant_id": None}, synchronize_session=False)

        # 2. Delete devices (cascades device telemetry, configurations, commands)
        devices = db.query(Device).filter(Device.tenant_id == tenant.id).all()
        for d in devices:
            db.delete(d)
        db.flush()

        # 3. Delete applications
        apps = db.query(Application).filter(Application.tenant_id == tenant.id).all()
        for a in apps:
            db.delete(a)
        db.flush()

        # 4. Delete decoders
        decoders = db.query(DecodeSchema).filter(DecodeSchema.tenant_id == tenant.id).all()
        for s in decoders:
            db.delete(s)
        db.flush()

        # 5. Delete webhooks
        webhooks = db.query(Webhook).filter(Webhook.tenant_id == tenant.id).all()
        for w in webhooks:
            db.delete(w)
        db.flush()

        # 6. Delete MQTT broker configs
        try:
            from app.models.mqtt_broker_config import MqttBrokerConfig
            db.query(MqttBrokerConfig).filter(MqttBrokerConfig.tenant_id == tenant.id).delete(synchronize_session=False)
        except Exception:
            pass

        # 7. Delete notifications
        try:
            from app.models.notification import Notification
            db.query(Notification).filter(Notification.tenant_id == tenant.id).delete(synchronize_session=False)
        except Exception:
            pass

        # 8. Unlink audit logs
        try:
            from app.models.audit_log import AuditLog
            db.query(AuditLog).filter(AuditLog.tenant_id == tenant.id).update({"tenant_id": None}, synchronize_session=False)
        except Exception:
            pass

        # 9. Delete collaborator permissions & roles
        try:
            from app.models.collaborator_permission import CollaboratorPermission
            from app.models.collaborator_role import CollaboratorRole
            db.query(CollaboratorPermission).filter(CollaboratorPermission.tenant_id == tenant.id).delete(synchronize_session=False)
            db.query(CollaboratorRole).filter(CollaboratorRole.tenant_id == tenant.id).delete(synchronize_session=False)
        except Exception:
            pass

        db.delete(tenant)
        db.commit()

    def tenant_response(
        self,
        db: Session,
        tenant: Tenant
    ):
        return {
            "id": tenant.id,
            "name": tenant.name,
            "type": tenant.type,
            "is_active": tenant.is_active,
            **self._counts(db, tenant.id),
        }

    def _counts(
        self,
        db: Session,
        tenant_id: int
    ):
        return {
            "user_count": (
                db.query(func.count(User.id))
                .filter(User.tenant_id == tenant_id)
                .scalar()
            ),
            "application_count": (
                db.query(func.count(Application.id))
                .filter(Application.tenant_id == tenant_id)
                .scalar()
            ),
            "device_count": (
                db.query(func.count(Device.id))
                .filter(Device.tenant_id == tenant_id)
                .scalar()
            ),
        }

    def _get_tenant(
        self,
        db: Session,
        tenant_id: int
    ):
        tenant = db.get(Tenant, tenant_id)

        if tenant is None:
            raise HTTPException(
                status_code=404,
                detail="Organization not found"
            )

        return tenant

    def _require_admin(
        self,
        current_user: User,
        action: str
    ):
        # Only platform admins manage organizations
        if current_user.role != "admin":
            raise HTTPException(
                status_code=403,
                detail=f"Only admins can {action}"
            )
