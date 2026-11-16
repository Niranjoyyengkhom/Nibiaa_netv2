from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.application_decoder import ApplicationDecoder
from app.models.decode_schema import DecodeSchema
from app.models.device import Device
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.application import (
    ApplicationCreate,
    ApplicationUpdate,
    ApplicationDecoderCreate,
    ApplicationDecoderUpdate,
)
from app.services.collaborator_permission_service import (
    collaborator_permission_service,
)
from app.services.notification_service import NotificationType, notify_tenant


# A collaborator sees the organization's applications with any of
# these functions: they all need to know which applications exist
# (to update one, read its traffic, or put a device in one).
APPLICATION_VIEW_FUNCTIONS = (
    "manage_application",
    "read_application_traffic",
    "create_devices",
    "manage_devices",
)


class ApplicationService:

    def get_applications(
        self,
        db: Session,
        current_user: User,
        tenant_id: Optional[int] = None,
    ):
        scoped_id = self._scoped_tenant_id(
            db,
            current_user,
            *APPLICATION_VIEW_FUNCTIONS
        )

        query = db.query(Application)

        if scoped_id is not None:
            query = query.filter(Application.tenant_id == scoped_id)
        elif tenant_id is not None:
            query = query.filter(Application.tenant_id == tenant_id)

        return [
            self.application_response(db, application)
            for application in query.order_by(Application.id).all()
        ]

    def create_application(
        self,
        db: Session,
        data: ApplicationCreate,
        current_user: User
    ):
        # --------------------------------
        # Admin
        # --------------------------------

        if current_user.role == "admin":

            if data.tenant_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="Admin must provide a tenant_id"
                )

            tenant = (
                db.query(Tenant)
                .filter(Tenant.id == data.tenant_id)
                .first()
            )

            if tenant is None:
                raise HTTPException(
                    status_code=404,
                    detail="Tenant not found"
                )

            tenant_id = data.tenant_id

        # --------------------------------
        # Owner
        # --------------------------------

        elif current_user.role == "owner":

            if current_user.tenant_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="Owner has no organization"
                )

            # Owner can only create applications
            # inside their own organization.
            tenant_id = current_user.tenant_id

        # --------------------------------
        # Collaborator
        # --------------------------------

        elif current_user.role == "collaborator":

            raise HTTPException(
                status_code=403,
                detail="Collaborator cannot create applications"
            )

        else:
            raise HTTPException(
                status_code=403,
                detail="Invalid role"
            )

        self._check_decoder(db, data.decode_schema_id, tenant_id)

        application = Application(
            name=data.name.strip(),
            tenant_id=tenant_id,
            decode_schema_id=data.decode_schema_id
        )

        db.add(application)
        db.commit()
        db.refresh(application)

        notify_tenant(
            db,
            application.tenant_id,
            "Application created",
            f"{current_user.name} created the application {application.name}.",
            NotificationType.APPLICATION,
        )

        return self.application_response(db, application)

    def update_application(
        self,
        db: Session,
        application_id: int,
        data: ApplicationUpdate,
        current_user: User
    ):
        """
        Manage Application: rename it or change its decoder.
        Collaborators need the Manage Application function.
        """

        application = self._get_application(
            db,
            application_id,
            current_user,
            "manage_application"
        )

        self._check_decoder(db, data.decode_schema_id, application.tenant_id)

        application.name = data.name.strip()
        application.decode_schema_id = data.decode_schema_id

        db.commit()
        db.refresh(application)

        return self.application_response(db, application)

    def delete_application(
        self,
        db: Session,
        application_id: int,
        current_user: User
    ):
        if current_user.role not in ("admin", "owner"):
            raise HTTPException(
                status_code=403,
                detail="Only admins and owners can delete applications"
            )

        application = self._get_application(
            db,
            application_id,
            current_user,
            "manage_application"
        )

        devices = self._device_count(db, application.id)

        if devices:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"The application still has {devices} device(s). "
                    "Move or delete them first."
                )
            )

        name = application.name
        tenant_id = application.tenant_id

        db.delete(application)
        db.commit()

        notify_tenant(
            db,
            tenant_id,
            "Application deleted",
            f"{current_user.name} deleted the application {name}.",
            NotificationType.APPLICATION,
        )

    def application_response(
        self,
        db: Session,
        application: Application
    ):
        decoder = (
            db.get(DecodeSchema, application.decode_schema_id)
            if application.decode_schema_id is not None
            else None
        )

        device_types_data = [
            {
                "id": dt.id,
                "name": dt.name,
                "code": dt.code,
                "description": dt.description,
                "network_type": dt.network_type,
                "decoders": [
                    {
                        "id": d.id,
                        "decode_schema_id": d.decode_schema_id,
                        "decode_schema_name": d.decode_schema.name if d.decode_schema else None,
                        "decode_schema_version": d.decode_schema.version if d.decode_schema else None,
                        "payload_format": d.payload_format,
                        "priority": d.priority,
                        "is_active": d.is_active,
                    }
                    for d in dt.decoders
                ],
            }
            for dt in (application.device_types or [])
        ]

        decoders_data = [
            {
                "id": d.id,
                "application_id": d.application_id,
                "decode_schema_id": d.decode_schema_id,
                "decode_schema_name": d.decode_schema.name if d.decode_schema else None,
                "decode_schema_version": d.decode_schema.version if d.decode_schema else None,
                "payload_format": d.payload_format,
                "priority": d.priority,
                "is_active": d.is_active,
            }
            for d in (application.decoders or [])
        ]

        return {
            "id": application.id,
            "name": application.name,
            "tenant_id": application.tenant_id,
            "decode_schema_id": application.decode_schema_id,
            "decoder_name": decoder.name if decoder else None,
            "decoder_version": decoder.version if decoder else None,
            "device_count": self._device_count(db, application.id),
            "device_type_count": len(device_types_data),
            "device_types": device_types_data,
            "decoders": decoders_data,
        }

    # ================================
    # Application Decoders
    # ================================

    def get_application_decoders(
        self,
        db: Session,
        application_id: int,
        current_user: User
    ):
        application = self._get_application(
            db,
            application_id,
            current_user,
            *APPLICATION_VIEW_FUNCTIONS
        )
        decoders = (
            db.query(ApplicationDecoder)
            .filter(ApplicationDecoder.application_id == application.id)
            .order_by(ApplicationDecoder.priority.desc(), ApplicationDecoder.id.asc())
            .all()
        )
        return [
            {
                "id": d.id,
                "application_id": d.application_id,
                "decode_schema_id": d.decode_schema_id,
                "decode_schema_name": d.decode_schema.name if d.decode_schema else None,
                "decode_schema_version": d.decode_schema.version if d.decode_schema else None,
                "payload_format": d.payload_format,
                "priority": d.priority,
                "is_active": d.is_active,
            }
            for d in decoders
        ]

    def add_application_decoder(
        self,
        db: Session,
        application_id: int,
        data: ApplicationDecoderCreate,
        current_user: User
    ):
        application = self._get_application(
            db,
            application_id,
            current_user,
            "manage_application"
        )
        self._check_decoder(db, data.decode_schema_id, application.tenant_id)

        # Check if identical decoder + format already assigned
        existing = (
            db.query(ApplicationDecoder)
            .filter(
                ApplicationDecoder.application_id == application.id,
                ApplicationDecoder.decode_schema_id == data.decode_schema_id,
                ApplicationDecoder.payload_format == data.payload_format,
            )
            .first()
        )
        if existing:
            existing.priority = data.priority
            existing.is_active = data.is_active
            db.commit()
            db.refresh(existing)
            return {
                "id": existing.id,
                "application_id": existing.application_id,
                "decode_schema_id": existing.decode_schema_id,
                "decode_schema_name": existing.decode_schema.name if existing.decode_schema else None,
                "decode_schema_version": existing.decode_schema.version if existing.decode_schema else None,
                "payload_format": existing.payload_format,
                "priority": existing.priority,
                "is_active": existing.is_active,
            }

        app_decoder = ApplicationDecoder(
            application_id=application.id,
            decode_schema_id=data.decode_schema_id,
            payload_format=data.payload_format,
            priority=data.priority,
            is_active=data.is_active,
        )
        db.add(app_decoder)
        db.commit()
        db.refresh(app_decoder)

        return {
            "id": app_decoder.id,
            "application_id": app_decoder.application_id,
            "decode_schema_id": app_decoder.decode_schema_id,
            "decode_schema_name": app_decoder.decode_schema.name if app_decoder.decode_schema else None,
            "decode_schema_version": app_decoder.decode_schema.version if app_decoder.decode_schema else None,
            "payload_format": app_decoder.payload_format,
            "priority": app_decoder.priority,
            "is_active": app_decoder.is_active,
        }

    def remove_application_decoder(
        self,
        db: Session,
        application_id: int,
        assignment_id: int,
        current_user: User
    ):
        application = self._get_application(
            db,
            application_id,
            current_user,
            "manage_application"
        )
        assignment = (
            db.query(ApplicationDecoder)
            .filter(
                ApplicationDecoder.id == assignment_id,
                ApplicationDecoder.application_id == application.id
            )
            .first()
        )
        if not assignment:
            raise HTTPException(status_code=404, detail="Decoder assignment not found")

        db.delete(assignment)
        db.commit()

    def update_application_decoder(
        self,
        db: Session,
        application_id: int,
        assignment_id: int,
        data: ApplicationDecoderUpdate,
        current_user: User
    ):
        application = self._get_application(
            db,
            application_id,
            current_user,
            "manage_application"
        )
        assignment = (
            db.query(ApplicationDecoder)
            .filter(
                ApplicationDecoder.id == assignment_id,
                ApplicationDecoder.application_id == application.id
            )
            .first()
        )
        if not assignment:
            raise HTTPException(status_code=404, detail="Decoder assignment not found")

        if data.payload_format is not None:
            assignment.payload_format = data.payload_format
        if data.priority is not None:
            assignment.priority = data.priority
        if data.is_active is not None:
            assignment.is_active = data.is_active

        db.commit()
        db.refresh(assignment)
        return {
            "id": assignment.id,
            "application_id": assignment.application_id,
            "decode_schema_id": assignment.decode_schema_id,
            "decode_schema_name": assignment.decode_schema.name if assignment.decode_schema else None,
            "decode_schema_version": assignment.decode_schema.version if assignment.decode_schema else None,
            "payload_format": assignment.payload_format,
            "priority": assignment.priority,
            "is_active": assignment.is_active,
        }

    # ================================
    # Helpers
    # ================================

    def _scoped_tenant_id(
        self,
        db: Session,
        current_user: User,
        *permissions: str
    ):
        # None = every organization (admin)
        if current_user.role == "admin":
            return None

        if current_user.role not in ("owner", "collaborator"):
            raise HTTPException(
                status_code=403,
                detail="User cannot access applications"
            )

        if current_user.role == "collaborator":
            collaborator_permission_service.require(
                db,
                current_user,
                *permissions
            )

        if current_user.tenant_id is None:
            raise HTTPException(
                status_code=403,
                detail="User has no organization"
            )

        return current_user.tenant_id

    def _get_application(
        self,
        db: Session,
        application_id: int,
        current_user: User,
        *permissions: str
    ):
        tenant_id = self._scoped_tenant_id(db, current_user, *permissions)

        application = db.get(Application, application_id)

        # Another organization's application is not found, not revealed
        if application is None or (
            tenant_id is not None and application.tenant_id != tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Application not found"
            )

        return application

    def _check_decoder(
        self,
        db: Session,
        decode_schema_id: int | None,
        tenant_id: int
    ):
        # An application can use its organization's decoders
        # and the platform decoders
        if decode_schema_id is None:
            return

        decoder = db.get(DecodeSchema, decode_schema_id)

        if decoder is None or decoder.tenant_id not in (None, tenant_id):
            raise HTTPException(
                status_code=404,
                detail="Decoder not found"
            )

    def _device_count(
        self,
        db: Session,
        application_id: int
    ):
        return (
            db.query(func.count(Device.id))
            .filter(Device.application_id == application_id)
            .scalar()
        )
