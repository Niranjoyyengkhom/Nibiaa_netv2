import re
from typing import List, Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.models.application import Application
from app.models.device_type import DeviceType
from app.models.device_type_decoder import DeviceTypeDecoder
from app.models.decode_schema import DecodeSchema
from app.models.device import Device
from app.models.user import User
from app.schemas.device_type import (
    DeviceTypeCreate,
    DeviceTypeUpdate,
    DeviceTypeResponse,
    DeviceTypeDecoderCreate,
    DeviceTypeDecoderResponse,
)
from app.services.collaborator_permission_service import collaborator_permission_service


def sanitize_code(name: str) -> str:
    code = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.strip().lower())
    code = re.sub(r"_+", "_", code).strip("_")
    return code or "device_type"


class DeviceTypeService:

    def _get_application_for_user(
        self,
        db: Session,
        application_id: int,
        current_user: User,
        permission: Optional[str] = None
    ) -> Application:
        application = db.query(Application).filter(Application.id == application_id).first()
        if not application:
            raise HTTPException(status_code=404, detail="Application not found")

        if current_user.role == "admin":
            return application

        if current_user.tenant_id != application.tenant_id:
            raise HTTPException(status_code=403, detail="Application belongs to another organization")

        if current_user.role == "collaborator" and permission:
            collaborator_permission_service.require(db, current_user, permission)

        return application

    def _get_device_type_for_user(
        self,
        db: Session,
        device_type_id: int,
        current_user: User,
        permission: Optional[str] = None
    ) -> DeviceType:
        dt = db.query(DeviceType).filter(DeviceType.id == device_type_id).first()
        if not dt:
            raise HTTPException(status_code=404, detail="Device type not found")

        self._get_application_for_user(db, dt.application_id, current_user, permission)
        return dt

    def to_decoder_response(self, dtd: DeviceTypeDecoder) -> DeviceTypeDecoderResponse:
        schema_name = dtd.decode_schema.name if dtd.decode_schema else None
        schema_ver = dtd.decode_schema.version if dtd.decode_schema else None
        return DeviceTypeDecoderResponse(
            id=dtd.id,
            device_type_id=dtd.device_type_id,
            decode_schema_id=dtd.decode_schema_id,
            decode_schema_name=schema_name,
            decode_schema_version=schema_ver,
            payload_format=dtd.payload_format,
            priority=dtd.priority,
            is_active=dtd.is_active,
            created_at=dtd.created_at,
        )

    def to_response(self, db: Session, dt: DeviceType) -> DeviceTypeResponse:
        device_count = (
            db.query(func.count(Device.id))
            .filter(
                Device.application_id == dt.application_id,
                or_(
                    Device.device_type_id == dt.id,
                    Device.device_type == dt.name,
                    Device.device_type == dt.code,
                ),
            )
            .scalar()
            or 0
        )

        decoders = [self.to_decoder_response(d) for d in dt.decoders]

        return DeviceTypeResponse(
            id=dt.id,
            application_id=dt.application_id,
            name=dt.name,
            code=dt.code,
            description=dt.description,
            network_type=dt.network_type,
            device_count=device_count,
            decoders=decoders,
            created_at=dt.created_at,
            updated_at=dt.updated_at,
        )

    def list_device_types(
        self,
        db: Session,
        application_id: int,
        current_user: User
    ) -> List[DeviceTypeResponse]:
        self._get_application_for_user(db, application_id, current_user)
        device_types = (
            db.query(DeviceType)
            .filter(DeviceType.application_id == application_id)
            .order_by(DeviceType.id.asc())
            .all()
        )
        return [self.to_response(db, dt) for dt in device_types]

    def get_device_type(
        self,
        db: Session,
        device_type_id: int,
        current_user: User
    ) -> DeviceTypeResponse:
        dt = self._get_device_type_for_user(db, device_type_id, current_user)
        return self.to_response(db, dt)

    def create_device_type(
        self,
        db: Session,
        application_id: int,
        data: DeviceTypeCreate,
        current_user: User
    ) -> DeviceTypeResponse:
        app = self._get_application_for_user(db, application_id, current_user, "manage_application")

        code = sanitize_code(data.code or data.name)
        existing = (
            db.query(DeviceType)
            .filter(DeviceType.application_id == application_id, DeviceType.code == code)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Device type with code '{code}' already exists in this application"
            )

        new_dt = DeviceType(
            application_id=application_id,
            name=data.name.strip(),
            code=code,
            description=data.description,
            network_type=data.network_type or "Direct IP",
        )
        db.add(new_dt)
        db.flush()

        # Add initial decoders if provided
        if data.decode_schema_ids:
            for s_id in data.decode_schema_ids:
                schema = db.query(DecodeSchema).filter(DecodeSchema.id == s_id).first()
                if schema:
                    fmt = getattr(schema, "match_payload_format", None)
                    db.add(
                        DeviceTypeDecoder(
                            device_type_id=new_dt.id,
                            decode_schema_id=s_id,
                            payload_format=fmt,
                            priority=0,
                            is_active=True,
                        )
                    )

        db.commit()
        db.refresh(new_dt)
        return self.to_response(db, new_dt)

    def update_device_type(
        self,
        db: Session,
        device_type_id: int,
        data: DeviceTypeUpdate,
        current_user: User
    ) -> DeviceTypeResponse:
        dt = self._get_device_type_for_user(db, device_type_id, current_user, "manage_application")

        if data.name is not None and data.name.strip():
            dt.name = data.name.strip()
        if data.code is not None and data.code.strip():
            new_code = sanitize_code(data.code)
            conflict = (
                db.query(DeviceType)
                .filter(
                    DeviceType.application_id == dt.application_id,
                    DeviceType.code == new_code,
                    DeviceType.id != dt.id,
                )
                .first()
            )
            if conflict:
                raise HTTPException(
                    status_code=400,
                    detail=f"Device type with code '{new_code}' already exists in this application"
                )
            dt.code = new_code
        if data.description is not None:
            dt.description = data.description
        if data.network_type is not None:
            dt.network_type = data.network_type

        db.commit()
        db.refresh(dt)
        return self.to_response(db, dt)

    def delete_device_type(
        self,
        db: Session,
        device_type_id: int,
        current_user: User
    ):
        dt = self._get_device_type_for_user(db, device_type_id, current_user, "manage_application")
        db.delete(dt)
        db.commit()

    def assign_decoder(
        self,
        db: Session,
        device_type_id: int,
        data: DeviceTypeDecoderCreate,
        current_user: User
    ) -> DeviceTypeDecoderResponse:
        dt = self._get_device_type_for_user(db, device_type_id, current_user, "manage_application")

        # Verify decode schema
        schema = db.query(DecodeSchema).filter(DecodeSchema.id == data.decode_schema_id).first()
        if not schema:
            raise HTTPException(status_code=404, detail="Decode schema not found")

        fmt = data.payload_format.strip().lower() if data.payload_format else None

        # Check existing
        existing = (
            db.query(DeviceTypeDecoder)
            .filter(
                DeviceTypeDecoder.device_type_id == device_type_id,
                DeviceTypeDecoder.decode_schema_id == data.decode_schema_id,
                DeviceTypeDecoder.payload_format == fmt,
            )
            .first()
        )
        if existing:
            existing.priority = data.priority
            existing.is_active = data.is_active
            db.commit()
            db.refresh(existing)
            return self.to_decoder_response(existing)

        mapping = DeviceTypeDecoder(
            device_type_id=device_type_id,
            decode_schema_id=data.decode_schema_id,
            payload_format=fmt,
            priority=data.priority,
            is_active=data.is_active,
        )
        db.add(mapping)
        db.commit()
        db.refresh(mapping)
        return self.to_decoder_response(mapping)

    def remove_decoder(
        self,
        db: Session,
        device_type_id: int,
        assignment_id: int,
        current_user: User
    ):
        self._get_device_type_for_user(db, device_type_id, current_user, "manage_application")
        mapping = (
            db.query(DeviceTypeDecoder)
            .filter(
                DeviceTypeDecoder.id == assignment_id,
                DeviceTypeDecoder.device_type_id == device_type_id,
            )
            .first()
        )
        if not mapping:
            raise HTTPException(status_code=404, detail="Decoder assignment not found")
        db.delete(mapping)
        db.commit()
