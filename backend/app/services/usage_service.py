from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.device import Device
from app.models.device_command import CommandStatus, DeviceCommand
from app.models.telemetry import Telemetry
from app.models.tenant import Tenant
from app.models.user import User
from app.services.telemetry_service import as_utc


class UsageService:

    def get_usage(
        self,
        db: Session,
        current_user: User,
        tenant_id: int | None,
        start: datetime | None,
        end: datetime | None
    ):
        tenant_id = self._usage_tenant(db, current_user, tenant_id)

        start = as_utc(start)
        end = as_utc(end)

        if start is not None and end is not None and start > end:
            raise HTTPException(
                status_code=400,
                detail="start must be before end"
            )

        # --------------------------------
        # Current totals
        # --------------------------------

        devices = db.query(func.count(Device.id))
        applications = db.query(func.count(Application.id))

        if tenant_id is not None:
            devices = devices.filter(Device.tenant_id == tenant_id)
            applications = applications.filter(Application.tenant_id == tenant_id)

        # --------------------------------
        # Messages in the period
        # --------------------------------

        # Telemetry and commands have no tenant column; the tenant
        # comes from the device they belong to
        telemetry = (
            db.query(Telemetry)
            .join(Device, Device.id == Telemetry.device_pk)
        )
        commands = (
            db.query(DeviceCommand)
            .join(Device, Device.id == DeviceCommand.device_pk)
        )

        if tenant_id is not None:
            telemetry = telemetry.filter(Device.tenant_id == tenant_id)
            commands = commands.filter(Device.tenant_id == tenant_id)

        if start is not None:
            telemetry = telemetry.filter(Telemetry.received_at >= start)
            commands = commands.filter(DeviceCommand.created_at >= start)

        if end is not None:
            telemetry = telemetry.filter(Telemetry.received_at <= end)
            commands = commands.filter(DeviceCommand.created_at <= end)

        by_provider = (
            telemetry
            .with_entities(Telemetry.provider, func.count(Telemetry.id))
            .group_by(Telemetry.provider)
            .all()
        )

        return {
            "tenant_id": tenant_id,
            "period_start": start,
            "period_end": end,
            "devices": devices.scalar(),
            "applications": applications.scalar(),
            "uplink_messages": telemetry.count(),
            "downlink_commands": commands.count(),
            "downlink_commands_acknowledged": (
                commands
                .filter(DeviceCommand.status == CommandStatus.ACKNOWLEDGED.value)
                .count()
            ),
            "uplink_messages_by_provider": {
                (provider or "unknown"): count
                for provider, count in by_provider
            },
        }

    def _usage_tenant(
        self,
        db: Session,
        current_user: User,
        requested_tenant_id: int | None
    ):
        """
        Which tenant's usage the user may see. None = all tenants.
        """

        if current_user.role == "admin":

            if requested_tenant_id is None:
                return None

            tenant = (
                db.query(Tenant)
                .filter(Tenant.id == requested_tenant_id)
                .first()
            )

            if tenant is None:
                raise HTTPException(
                    status_code=404,
                    detail="Tenant not found"
                )

            return requested_tenant_id

        if current_user.role == "owner":
            if current_user.tenant_id is None:
                raise HTTPException(
                    status_code=403,
                    detail="Owner has no organization"
                )

            # The organization always comes from the logged-in user;
            # asking for another organization is refused, not silently ignored
            if (
                requested_tenant_id is not None
                and requested_tenant_id != current_user.tenant_id
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Cannot view another organization's usage"
                )

            return current_user.tenant_id

        raise HTTPException(
            status_code=403,
            detail="User cannot access usage"
        )
