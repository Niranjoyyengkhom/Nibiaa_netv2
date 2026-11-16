from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.device_configuration import utc_now
from app.models.telemetry import Telemetry
from app.models.user import User
from app.services.device_service import DeviceService


DEFAULT_TELEMETRY_LIMIT = 100
MAX_TELEMETRY_LIMIT = 1000

# Reading telemetry is "Read Application Traffic" in the RBAC matrix
TRAFFIC_PERMISSION = "read_application_traffic"


def as_utc(value: datetime | None):
    # A query parameter without a timezone is taken as UTC
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value


class TelemetryService:

    def __init__(self):
        self.device_service = DeviceService()

    def get_telemetry(
        self,
        db: Session,
        device_id: str,
        current_user: User,
        limit: int,
        start: datetime | None,
        end: datetime | None,
        connection_type: str | None = None
    ):
        # Enforces role, function and tenant ownership
        device = self.device_service.get_device_for_user(
            db,
            device_id,
            current_user,
            TRAFFIC_PERMISSION
        )

        query = (
            db.query(Telemetry)
            .filter(
                Telemetry.device_pk == device.id
            )
        )

        query = self._filter(query, start, end, connection_type)

        records = (
            query
            .order_by(Telemetry.timestamp.desc(), Telemetry.id.desc())
            .limit(limit)
            .all()
        )

        return [
            self._telemetry_response(device, record)
            for record in records
        ]

    def get_fleet_telemetry(
        self,
        db: Session,
        current_user: User,
        limit: int,
        start: datetime | None,
        end: datetime | None,
        connection_type: str | None,
        provider: str | None,
        tenant_id: int | None,
        application_id: int | None = None,
        device_id: str | None = None
    ):
        """
        Telemetry of every device the user can see, newest first.
        Owners and collaborators with Read Application Traffic: their
        own organization. Admins: all, or one tenant_id.
        """

        scoped_tenant_id = self.device_service.scoped_tenant_id(
            db,
            current_user,
            TRAFFIC_PERMISSION
        )

        query = (
            db.query(Telemetry, Device)
            .join(Device, Device.id == Telemetry.device_pk)
        )

        if scoped_tenant_id is not None:
            # Always their own organization, whatever tenant_id was sent
            query = query.filter(Device.tenant_id == scoped_tenant_id)

        elif tenant_id is not None:
            query = query.filter(Device.tenant_id == tenant_id)

        query = self._filter(query, start, end, connection_type)

        if provider is not None:
            query = query.filter(Telemetry.provider == provider)

        if application_id is not None:
            query = query.filter(Device.application_id == application_id)

        if device_id and device_id.strip():
            query = query.filter(Device.device_id == device_id.strip())

        rows = (
            query
            .order_by(Telemetry.timestamp.desc(), Telemetry.id.desc())
            .limit(limit)
            .all()
        )

        schema_ids = {record.decode_schema_id for record, _ in rows if record.decode_schema_id}
        schemas_by_id = {}
        if schema_ids:
            try:
                from app.models.decode_schema import DecodeSchema
                for s in db.query(DecodeSchema).filter(DecodeSchema.id.in_(schema_ids)).all():
                    schemas_by_id[s.id] = s
            except Exception:
                pass

        return [
            self._telemetry_response(device, record, schemas_by_id.get(record.decode_schema_id))
            for record, device in rows
        ]

    def get_latest(
        self,
        db: Session,
        device_id: str,
        current_user: User
    ):
        device = self.device_service.get_device_for_user(
            db,
            device_id,
            current_user,
            TRAFFIC_PERMISSION
        )

        record = (
            db.query(Telemetry)
            .filter(
                Telemetry.device_pk == device.id
            )
            .order_by(Telemetry.timestamp.desc(), Telemetry.id.desc())
            .first()
        )

        if record is None:
            raise HTTPException(
                status_code=404,
                detail="No telemetry received from this device yet"
            )

        schema = None
        if record.decode_schema_id:
            try:
                from app.models.decode_schema import DecodeSchema
                schema = db.query(DecodeSchema).filter(DecodeSchema.id == record.decode_schema_id).first()
            except Exception:
                pass

        return self._telemetry_response(device, record, schema)

    def _filter(
        self,
        query,
        start: datetime | None,
        end: datetime | None,
        connection_type: str | None
    ):
        start = as_utc(start)
        end = as_utc(end)

        if start is not None and end is not None and start > end:
            raise HTTPException(
                status_code=400,
                detail="start must be before end"
            )

        # 24-hour retention window
        twenty_four_hours_ago = utc_now() - timedelta(hours=24)
        if start is not None:
            effective_start = max(start, twenty_four_hours_ago)
        else:
            effective_start = twenty_four_hours_ago

        query = query.filter(Telemetry.timestamp >= effective_start)

        if end is not None:
            query = query.filter(Telemetry.timestamp <= end)

        if connection_type is not None:
            query = query.filter(Telemetry.connection_type == connection_type)

        return query

    def _telemetry_response(
        self,
        device: Device,
        record: Telemetry,
        schema: Any | None = None
    ):
        originator_name = device.name or device.device_id
        originator_type = device.device_type or record.connection_type or "Device"
        if record.provider:
            data_originator = f"{originator_name} via {record.provider} ({originator_type})"
        else:
            data_originator = f"{originator_name} ({originator_type})"

        telemetry_dict = record.data
        if not isinstance(telemetry_dict, dict):
            if isinstance(telemetry_dict, str):
                try:
                    import json
                    parsed = json.loads(telemetry_dict)
                    telemetry_dict = parsed if isinstance(parsed, dict) else {"raw": telemetry_dict}
                except Exception:
                    telemetry_dict = {"raw": telemetry_dict}
            else:
                telemetry_dict = {"value": telemetry_dict} if telemetry_dict is not None else {}

        return {
            "id": record.id,
            "device_id": device.device_id,
            "device_name": device.name,
            "data_originator": data_originator,
            "application_id": device.application_id,
            "timestamp": record.timestamp,
            "received_at": record.received_at,
            "provider": record.provider,
            "connection_type": record.connection_type,
            "decode_activation_id": record.decode_activation_id,
            "decode_schema_id": record.decode_schema_id,
            "decoder_name": schema.name if schema else None,
            "decoder_version": schema.version if schema else None,
            "raw_payload_hex": (
                record.raw_payload.hex()
                if record.raw_payload is not None
                else None
            ),
            "telemetry": telemetry_dict,
        }
