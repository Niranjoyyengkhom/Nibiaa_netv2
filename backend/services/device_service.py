from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.user import User
from app.models.application import Application
from app.network_types import (
    encrypt_credentials,
    mask_credentials,
    network_type,
    unique_keys,
    validate_credentials,
)
from app.schemas.device import DeviceCreate
from app.services.collaborator_permission_service import (
    collaborator_permission_service,
)
from app.services.notification_service import NotificationType, notify_tenant


class DeviceService:

    # --------------------------------
    # Access
    # --------------------------------

    def scoped_tenant_id(
        self,
        db: Session,
        current_user: User,
        permission: str
    ):
        """
        Which organization's devices the user may act on with this
        collaborator function. None = every organization (admin).

        Owners have every function in their organization.
        Collaborators need the function from their owner.
        """

        if current_user.role == "admin":
            return None

        if current_user.role not in ("owner", "collaborator"):
            raise HTTPException(
                status_code=403,
                detail="User cannot access devices"
            )

        if current_user.role == "collaborator":
            collaborator_permission_service.require(
                db,
                current_user,
                permission
            )

        if current_user.tenant_id is None:
            raise HTTPException(
                status_code=403,
                detail="User has no tenant"
            )

        return current_user.tenant_id

    def get_devices(
        self,
        db: Session,
        current_user: User,
        permission: str = "manage_devices"
    ):
        tenant_id = self.scoped_tenant_id(db, current_user, permission)

        query = db.query(Device)

        if tenant_id is not None:
            query = query.filter(Device.tenant_id == tenant_id)

        return query.order_by(Device.id).all()

    def get_device_for_user(
        self,
        db: Session,
        device_id: str,
        current_user: User,
        permission: str = "manage_devices"
    ):
        """
        The device, if the user may act on it with this function.
        Another organization's device is not found, not revealed.
        """

        tenant_id = self.scoped_tenant_id(db, current_user, permission)

        query = (
            db.query(Device)
            .filter(
                Device.device_id == device_id
            )
        )

        if tenant_id is not None:
            query = query.filter(Device.tenant_id == tenant_id)

        device = query.first()

        if device is None:
            raise HTTPException(
                status_code=404,
                detail="Device not found"
            )

        return device

    # --------------------------------
    # Create / update / delete
    # --------------------------------

    def create_device(
        self,
        db: Session,
        data: DeviceCreate,
        current_user: User
    ):
        tenant_id = self.scoped_tenant_id(db, current_user, "create_devices")

        application = self._get_application(db, data.application_id)

        # --------------------------------
        # Admin: any organization
        # --------------------------------

        if tenant_id is None:

            # Without a tenant_id the device joins
            # the application's organization
            if (
                data.tenant_id is not None
                and application.tenant_id != data.tenant_id
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Application does not belong to the selected tenant"
                )

            tenant_id = application.tenant_id

        # --------------------------------
        # Owner / collaborator: own organization
        # --------------------------------

        elif application.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Application does not belong to your tenant"
            )

        # --------------------------------
        # Check duplicate device ID
        # --------------------------------

        existing_device = (
            db.query(Device)
            .filter(
                Device.device_id == data.device_id
            )
            .first()
        )

        if existing_device:
            raise HTTPException(
                status_code=400,
                detail="Device ID already exists"
            )

        credentials = self._clean_credentials(data.device_type, data.credentials)
        self._check_unique_credentials(db, data.device_type, credentials)
        encrypted_credentials = encrypt_credentials(data.device_type, credentials)

        new_device = Device(
            device_id=data.device_id,
            name=data.name,
            device_type=data.device_type,
            credentials=encrypted_credentials,
            tenant_id=tenant_id,
            application_id=application.id
        )

        db.add(new_device)
        db.commit()
        db.refresh(new_device)

        notify_tenant(
            db,
            new_device.tenant_id,
            "Device registered",
            f"{current_user.name} registered {new_device.device_id} "
            f"({self._type_label(new_device.device_type)}) in {application.name}.",
            NotificationType.DEVICE,
        )

        return new_device

    def update_device(
        self,
        db: Session,
        device_id: str,
        data,
        current_user: User
    ):
        device = self.get_device_for_user(
            db,
            device_id,
            current_user,
            "manage_devices"
        )

        application = self._get_application(db, data.application_id)

        # A device stays in its organization, so it can only move to
        # another application of the same organization (also for admins)
        if application.tenant_id != device.tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Application does not belong to the device's tenant"
            )

        # Credentials are kept unless sent; a changed type needs its own
        if data.credentials is not None or data.device_type != device.device_type:
            keep = device.credentials if data.device_type == device.device_type else None
            credentials = self._clean_credentials(
                data.device_type,
                data.credentials,
                keep
            )
            self._check_unique_credentials(db, data.device_type, credentials, device.id)
            device.credentials = encrypt_credentials(data.device_type, credentials)

        device.name = data.name
        device.device_type = data.device_type
        device.application_id = application.id

        db.commit()
        db.refresh(device)

        return device

    def delete_device(
        self,
        db: Session,
        device_id: str,
        current_user: User
    ):
        device = self.get_device_for_user(
            db,
            device_id,
            current_user,
            "delete_devices"
        )

        # Telemetry, configuration and commands are deleted with it
        # (ON DELETE CASCADE)
        tenant_id = device.tenant_id

        db.delete(device)
        db.commit()

        notify_tenant(
            db,
            tenant_id,
            "Device deleted",
            f"{current_user.name} deleted {device_id} and its data.",
            NotificationType.DEVICE,
        )

        return {
            "message": "Device deleted successfully"
        }

    # --------------------------------
    # Network type credentials
    # --------------------------------

    def device_response(self, device: Device, db: Session | None = None):
        creds = mask_credentials(device.device_type, device.credentials) or {}
        if not isinstance(creds, dict):
            creds = {}
        else:
            creds = dict(creds)

        provider = (
            creds.get("provider")
            or creds.get("satellite_provider_id")
            or creds.get("sim_provider_id")
            or creds.get("provider_id")
        )

        if not provider and db:
            try:
                from app.models.telemetry import Telemetry
                last_tel = (
                    db.query(Telemetry.provider)
                    .filter(Telemetry.device_pk == device.id, Telemetry.provider.isnot(None))
                    .order_by(Telemetry.timestamp.desc(), Telemetry.id.desc())
                    .first()
                )
                if last_tel and last_tel[0]:
                    provider = last_tel[0]
                    creds["provider"] = provider
            except Exception:
                pass

        return {
            "id": device.id,
            "device_id": device.device_id,
            "name": device.name,
            "device_type": device.device_type,
            "tenant_id": device.tenant_id,
            "application_id": device.application_id,
            "provider": provider,
            "credentials": creds,
        }

    def _clean_credentials(self, device_type, credentials, keep=None):
        try:
            return validate_credentials(device_type, credentials, keep)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    def _check_unique_credentials(self, db, device_type, credentials, exclude_id=None):
        # DevEUI, IMEI, MAC, ... identify one device only
        for key in unique_keys(device_type):
            value = (credentials or {}).get(key)

            query = db.query(Device).filter(Device.credentials[key].as_string() == value)

            if exclude_id is not None:
                query = query.filter(Device.id != exclude_id)

            other = query.first()

            if other is not None:
                spec = next(
                    f for f in network_type(device_type)["fields"] if f["key"] == key
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"{spec['label']} {value} is already used by device {other.device_id}"
                )

    def _type_label(self, device_type):
        definition = network_type(device_type)
        return definition["label"] if definition else device_type

    def _get_application(
        self,
        db: Session,
        application_id: int
    ):
        application = db.get(Application, application_id)

        if application is None:
            raise HTTPException(
                status_code=404,
                detail="Application not found"
            )

        return application
