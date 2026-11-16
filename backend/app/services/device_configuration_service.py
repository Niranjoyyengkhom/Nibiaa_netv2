from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.device_command import DeviceCommand
from app.models.device_configuration import DeviceConfiguration, utc_now
from app.models.user import User
from app.services.device_service import DeviceService


class DeviceConfigurationService:
    """
    Owns the device_configurations row of a device.

    This is the lower layer: it does not create or move commands.
    DeviceControlService uses it to change the desired state when
    commands are queued and the confirmed state when they are acknowledged.
    """

    def __init__(self):
        self.device_service = DeviceService()

    def get_controllable_device(
        self,
        db: Session,
        device_id: str,
        current_user: User
    ):
        # Remote configuration is a device update: admins, owners and
        # collaborators with Manage Devices. Enforces tenant ownership.
        return self.device_service.get_device_for_user(
            db,
            device_id,
            current_user,
            "manage_devices"
        )

    def get_or_create_configuration(
        self,
        db: Session,
        device: Device
    ):
        query = (
            db.query(DeviceConfiguration)
            .filter(
                DeviceConfiguration.device_pk == device.id
            )
        )

        configuration = query.first()

        if configuration is None:
            # The page loads configuration and simulation in parallel, and
            # both may create this row. ON CONFLICT makes that safe instead
            # of failing the second request with a unique violation.
            db.execute(
                insert(DeviceConfiguration)
                .values(device_pk=device.id)
                .on_conflict_do_nothing(index_elements=["device_pk"])
            )

            configuration = query.first()

        return configuration

    def set_desired(
        self,
        configuration: DeviceConfiguration,
        desired_column: str,
        value
    ):
        setattr(configuration, desired_column, value)
        configuration.desired_updated_at = utc_now()

    def set_confirmed(
        self,
        configuration: DeviceConfiguration,
        confirmed_column: str,
        value
    ):
        setattr(configuration, confirmed_column, value)
        configuration.confirmed_at = utc_now()

    def configuration_response(
        self,
        device: Device,
        configuration: DeviceConfiguration,
        pending_command: DeviceCommand | None
    ):
        in_sync = all(
            desired is None or desired == confirmed
            for desired, confirmed in [
                (
                    configuration.desired_enabled,
                    configuration.confirmed_enabled
                ),
                (
                    configuration.desired_wake_frequency_per_day,
                    configuration.confirmed_wake_frequency_per_day
                ),
            ]
        )

        return {
            "device_id": device.device_id,
            "desired_enabled": configuration.desired_enabled,
            "desired_wake_frequency_per_day": configuration.desired_wake_frequency_per_day,
            "desired_updated_at": configuration.desired_updated_at,
            "confirmed_enabled": configuration.confirmed_enabled,
            "confirmed_wake_frequency_per_day": configuration.confirmed_wake_frequency_per_day,
            "confirmed_at": configuration.confirmed_at,
            "in_sync": in_sync,
            "pending_command_id": (
                pending_command.id if pending_command else None
            ),
            "pending_command_status": (
                pending_command.status if pending_command else None
            ),
            "created_at": configuration.created_at,
            "updated_at": configuration.updated_at,
        }
