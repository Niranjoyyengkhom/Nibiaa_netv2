from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.device_command import (
    FINAL_STATUSES,
    CommandLocation,
    CommandStatus,
    CommandType,
    DeviceCommand,
)
from app.models.device_command_event import DeviceCommandEvent
from app.models.device_configuration import DeviceConfiguration, utc_now
from app.models.user import User
from app.schemas.device_command import (
    DeviceCommandAck,
    DeviceCommandCancel,
    DeviceCommandCreate,
    DeviceCommandSimulate,
)
from app.schemas.device_configuration import DeviceConfigurationUpdate
from app.services.device_configuration_service import DeviceConfigurationService
from app.services.notification_service import NotificationType, notify_tenant


DEFAULT_COMMAND_TTL_HOURS = 24 * 7


# --------------------------------
# Store-and-forward state machine
# --------------------------------

# A command must pass every hop in order.
# FAILED / EXPIRED are possible from any non-final state.
# CANCELLED is possible until the command reaches the device.
ALLOWED_TRANSITIONS = {
    CommandStatus.PENDING: {
        CommandStatus.GROUND_STATION_QUEUED,
        CommandStatus.FAILED,
        CommandStatus.EXPIRED,
        CommandStatus.CANCELLED,
    },
    CommandStatus.GROUND_STATION_QUEUED: {
        CommandStatus.SATELLITE_QUEUED,
        CommandStatus.FAILED,
        CommandStatus.EXPIRED,
        CommandStatus.CANCELLED,
    },
    CommandStatus.SATELLITE_QUEUED: {
        CommandStatus.DEVICE_DELIVERED,
        CommandStatus.FAILED,
        CommandStatus.EXPIRED,
        CommandStatus.CANCELLED,
    },
    CommandStatus.DEVICE_DELIVERED: {
        CommandStatus.ACKNOWLEDGED,
        CommandStatus.FAILED,
        CommandStatus.EXPIRED,
    },
    CommandStatus.ACKNOWLEDGED: set(),
    CommandStatus.FAILED: set(),
    CommandStatus.EXPIRED: set(),
    CommandStatus.CANCELLED: set(),
}

# Return path of an acknowledgement, after the device itself
ACK_RELAY_LOCATIONS = [
    CommandLocation.SATELLITE,
    CommandLocation.GROUND_STATION,
]

# Where the command physically is while it has this status
STATUS_LOCATION = {
    CommandStatus.PENDING: CommandLocation.SERVER,
    CommandStatus.GROUND_STATION_QUEUED: CommandLocation.GROUND_STATION,
    CommandStatus.SATELLITE_QUEUED: CommandLocation.SATELLITE,
    CommandStatus.DEVICE_DELIVERED: CommandLocation.DEVICE,
    CommandStatus.ACKNOWLEDGED: CommandLocation.DEVICE,
}

# Event name recorded in the history for each hop
STATUS_EVENT = {
    CommandStatus.GROUND_STATION_QUEUED: "QUEUED",
    CommandStatus.SATELLITE_QUEUED: "QUEUED",
    CommandStatus.DEVICE_DELIVERED: "DELIVERED",
    CommandStatus.FAILED: "FAILED",
    CommandStatus.EXPIRED: "EXPIRED",
    CommandStatus.CANCELLED: "CANCELLED",
}

# Which configuration field each command type controls:
# (payload key, desired column, confirmed column)
COMMAND_FIELDS = {
    CommandType.SET_WAKE_FREQUENCY: (
        "frequency_per_day",
        "desired_wake_frequency_per_day",
        "confirmed_wake_frequency_per_day",
    ),
    CommandType.SET_ENABLED: (
        "enabled",
        "desired_enabled",
        "confirmed_enabled",
    ),
}


class DeviceControlService:

    def __init__(self):
        self.configuration_service = DeviceConfigurationService()

    # ================================
    # Configuration
    # ================================

    def get_configuration(
        self,
        db: Session,
        device_id: str,
        current_user: User
    ):
        device = self._get_device(db, device_id, current_user)

        configuration = self.configuration_service.get_or_create_configuration(
            db,
            device
        )

        # So an overdue command is not reported as pending
        self._expire_overdue_commands(db, device)
        db.commit()

        return self.configuration_service.configuration_response(
            device,
            configuration,
            self._pending_command(db, device)
        )

    def update_configuration(
        self,
        db: Session,
        device_id: str,
        data: DeviceConfigurationUpdate,
        current_user: User
    ):
        device = self._get_device(db, device_id, current_user)

        changes = {}

        if data.wake_frequency_per_day is not None:
            changes[CommandType.SET_WAKE_FREQUENCY] = data.wake_frequency_per_day

        if data.enabled is not None:
            changes[CommandType.SET_ENABLED] = data.enabled

        if not changes:
            raise HTTPException(
                status_code=400,
                detail="Provide wake_frequency_per_day and/or enabled"
            )

        configuration = self.configuration_service.get_or_create_configuration(
            db,
            device
        )
        self._expire_overdue_commands(db, device)

        queued_commands = []

        for command_type, value in changes.items():
            payload_key, desired_column, _ = COMMAND_FIELDS[command_type]

            # Only the DESIRED state changes here.
            # The confirmed state changes when the device acknowledges.
            self.configuration_service.set_desired(
                configuration,
                desired_column,
                value
            )

            if self._command_needed(db, device, configuration, command_type, value):
                queued_commands.append(
                    self._create_command(
                        db,
                        device,
                        command_type,
                        {payload_key: value},
                        DEFAULT_COMMAND_TTL_HOURS,
                        current_user
                    )
                )

        db.commit()
        db.refresh(configuration)

        response = self.configuration_service.configuration_response(
            device,
            configuration,
            self._pending_command(db, device)
        )

        response["queued_commands"] = [
            {
                "id": command.id,
                "command_type": command.command_type,
                "status": command.status,
            }
            for command in queued_commands
        ]

        return response

    # ================================
    # Commands
    # ================================

    def create_command(
        self,
        db: Session,
        device_id: str,
        data: DeviceCommandCreate,
        current_user: User
    ):
        device = self._get_device(db, device_id, current_user)

        configuration = self.configuration_service.get_or_create_configuration(
            db,
            device
        )
        self._expire_overdue_commands(db, device)

        # Keep the desired state consistent with the command
        payload_key, desired_column, _ = COMMAND_FIELDS[data.command_type]
        self.configuration_service.set_desired(
            configuration,
            desired_column,
            data.payload[payload_key]
        )

        command = self._create_command(
            db,
            device,
            data.command_type,
            data.payload,
            data.expires_in_hours or DEFAULT_COMMAND_TTL_HOURS,
            current_user
        )

        db.commit()
        db.refresh(command)

        return self._command_response(db, device, command, include_events=True)

    def get_commands(
        self,
        db: Session,
        device_id: str,
        current_user: User
    ):
        device = self._get_device(db, device_id, current_user)

        self._expire_overdue_commands(db, device)
        db.commit()

        commands = (
            db.query(DeviceCommand)
            .filter(
                DeviceCommand.device_pk == device.id
            )
            .order_by(DeviceCommand.id.desc())
            .all()
        )

        return [
            self._command_response(db, device, command)
            for command in commands
        ]

    def get_command(
        self,
        db: Session,
        device_id: str,
        command_id: int,
        current_user: User
    ):
        device = self._get_device(db, device_id, current_user)
        command = self._get_command(db, device, command_id)

        self._expire_if_overdue(db, command)
        db.commit()

        return self._command_response(db, device, command, include_events=True)

    def simulate_delivery(
        self,
        db: Session,
        device_id: str,
        command_id: int,
        data: DeviceCommandSimulate,
        current_user: User
    ):
        """
        DEVELOPMENT / TESTING ONLY.

        Stands in for the future ground station / satellite
        integration by moving the command one hop forward.
        """

        device = self._get_device(db, device_id, current_user)
        command = self._get_command(db, device, command_id)

        # Save a lazy expiry even if the transition below is rejected
        self._expire_if_overdue(db, command)
        db.commit()

        new_status = CommandStatus(data.status)

        if new_status == CommandStatus.FAILED:
            # Failed at the hop where the command currently is
            location = STATUS_LOCATION.get(
                CommandStatus(command.status),
                CommandLocation.SERVER
            )
        elif new_status == CommandStatus.EXPIRED:
            location = CommandLocation.SERVER
        else:
            location = STATUS_LOCATION[new_status]

        self._change_status(
            db,
            command,
            new_status,
            location,
            STATUS_EVENT[new_status],
            data.detail
        )

        if new_status == CommandStatus.DEVICE_DELIVERED:
            command.delivered_at = utc_now()

        db.commit()
        db.refresh(command)

        return self._command_response(db, device, command, include_events=True)

    def acknowledge_command(
        self,
        db: Session,
        device_id: str,
        command_id: int,
        data: DeviceCommandAck,
        current_user: User
    ):
        """
        DEVELOPMENT / TESTING ONLY.

        Stands in for an acknowledgement travelling
        Device -> Satellite -> Ground Station -> NibiaaNet.

        Idempotent: the satellite link may deliver the same
        acknowledgement more than once. A repeat is answered with
        the current state and changes nothing.
        """

        device = self._get_device(db, device_id, current_user)

        # Row lock until commit, so two copies of the same acknowledgement
        # arriving together cannot both apply the configuration
        command = self._get_command(db, device, command_id, lock=True)

        already_answered = (
            (data.success and command.status == CommandStatus.ACKNOWLEDGED.value)
            or (not data.success and command.status == CommandStatus.FAILED.value)
        )

        if already_answered:
            db.commit()
            return self._command_response(db, device, command, include_events=True)

        if self._expire_if_overdue(db, command):
            db.commit()

        if command.status != CommandStatus.DEVICE_DELIVERED.value:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Only a DEVICE_DELIVERED command can be acknowledged "
                    f"(current status: {command.status})"
                )
            )

        # The device answers, and the answer travels back to the server
        self._add_event(
            db,
            command,
            CommandLocation.DEVICE,
            "APPLIED" if data.success else "REJECTED",
            data.detail
        )

        for location in ACK_RELAY_LOCATIONS:
            self._add_event(db, command, location, "ACK_RELAYED", None)

        # The acknowledgement has reached the server.
        # Only now may the confirmed configuration change.
        if data.success:
            self._change_status(
                db,
                command,
                CommandStatus.ACKNOWLEDGED,
                CommandLocation.SERVER,
                "ACKNOWLEDGED",
                "Confirmed configuration updated"
            )
            command.acknowledged_at = utc_now()

            self._apply_acknowledged_command(db, device, command)

        else:
            self._change_status(
                db,
                command,
                CommandStatus.FAILED,
                CommandLocation.SERVER,
                "FAILED",
                "Device rejected the command"
            )

        db.commit()
        db.refresh(command)

        notify_tenant(
            db,
            device.tenant_id,
            "Command acknowledged" if data.success else "Command rejected",
            f"{device.device_id} {'applied' if data.success else 'rejected'} "
            f"command #{command.id} ({command.command_type}).",
            NotificationType.COMMAND,
        )

        return self._command_response(db, device, command, include_events=True)

    def cancel_command(
        self,
        db: Session,
        device_id: str,
        command_id: int,
        data: DeviceCommandCancel,
        current_user: User
    ):
        """
        Stops a command that has not reached the device yet.
        The desired configuration is left as it is, like after
        FAILED / EXPIRED, so the configuration shows as not in sync.
        """

        device = self._get_device(db, device_id, current_user)
        command = self._get_command(db, device, command_id, lock=True)

        # Cancelling twice is not an error
        if command.status == CommandStatus.CANCELLED.value:
            db.commit()
            return self._command_response(db, device, command, include_events=True)

        if self._expire_if_overdue(db, command):
            db.commit()

        if CommandStatus.CANCELLED not in ALLOWED_TRANSITIONS[CommandStatus(command.status)]:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Only a command that has not reached the device can be "
                    f"cancelled (current status: {command.status})"
                )
            )

        self._change_status(
            db,
            command,
            CommandStatus.CANCELLED,
            CommandLocation.SERVER,
            "CANCELLED",
            data.detail or f"Cancelled while at {STATUS_LOCATION[CommandStatus(command.status)].value}"
        )

        db.commit()
        db.refresh(command)

        return self._command_response(db, device, command, include_events=True)

    # ================================
    # Helpers
    # ================================

    def _pending_command(
        self,
        db: Session,
        device: Device
    ):
        # Newest command that is still on its way
        return (
            db.query(DeviceCommand)
            .filter(
                DeviceCommand.device_pk == device.id,
                DeviceCommand.status.notin_(
                    [status.value for status in FINAL_STATUSES]
                )
            )
            .order_by(DeviceCommand.id.desc())
            .first()
        )

    def _get_device(
        self,
        db: Session,
        device_id: str,
        current_user: User
    ):
        return self.configuration_service.get_controllable_device(
            db,
            device_id,
            current_user
        )

    def _get_command(
        self,
        db: Session,
        device: Device,
        command_id: int,
        lock: bool = False
    ):
        # The device is already tenant-checked, and the command
        # must belong to that device
        query = (
            db.query(DeviceCommand)
            .filter(
                DeviceCommand.id == command_id,
                DeviceCommand.device_pk == device.id
            )
        )

        if lock:
            query = query.with_for_update()

        command = query.first()

        if command is None:
            raise HTTPException(
                status_code=404,
                detail="Command not found"
            )

        return command

    def _command_needed(
        self,
        db: Session,
        device: Device,
        configuration: DeviceConfiguration,
        command_type: CommandType,
        value
    ):
        payload_key, _, confirmed_column = COMMAND_FIELDS[command_type]

        latest_in_flight = (
            db.query(DeviceCommand)
            .filter(
                DeviceCommand.device_pk == device.id,
                DeviceCommand.command_type == command_type.value,
                DeviceCommand.status.notin_(
                    [status.value for status in FINAL_STATUSES]
                )
            )
            .order_by(DeviceCommand.id.desc())
            .first()
        )

        # The newest command already on its way carries this value
        if latest_in_flight is not None:
            return latest_in_flight.payload.get(payload_key) != value

        # Nothing on its way and the device already uses this value
        return getattr(configuration, confirmed_column) != value

    def _create_command(
        self,
        db: Session,
        device: Device,
        command_type: CommandType,
        payload: dict,
        ttl_hours: int,
        current_user: User
    ):
        command = DeviceCommand(
            device_pk=device.id,
            command_type=command_type.value,
            payload=payload,
            status=CommandStatus.PENDING.value,
            created_by_user_id=current_user.id,
            expires_at=utc_now() + timedelta(hours=ttl_hours)
        )

        db.add(command)
        db.flush()

        self._add_event(
            db,
            command,
            CommandLocation.SERVER,
            "CREATED",
            "Stored on server, waiting for a ground station"
        )

        return command

    def _change_status(
        self,
        db: Session,
        command: DeviceCommand,
        new_status: CommandStatus,
        location: CommandLocation,
        event: str,
        detail: str | None
    ):
        current_status = CommandStatus(command.status)

        if new_status not in ALLOWED_TRANSITIONS[current_status]:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot move command from {current_status.value} "
                    f"to {new_status.value}"
                )
            )

        command.status = new_status.value

        self._add_event(db, command, location, event, detail)

        db.flush()

    def _add_event(
        self,
        db: Session,
        command: DeviceCommand,
        location: CommandLocation,
        event: str,
        detail: str | None
    ):
        db.add(
            DeviceCommandEvent(
                command_id=command.id,
                location=location.value,
                event=event,
                status=command.status,
                detail=detail
            )
        )

    def _expire_if_overdue(
        self,
        db: Session,
        command: DeviceCommand
    ):
        # Returns True when the command was expired just now
        if CommandStatus(command.status) in FINAL_STATUSES:
            return False

        if command.expires_at is None or command.expires_at > utc_now():
            return False

        self._change_status(
            db,
            command,
            CommandStatus.EXPIRED,
            CommandLocation.SERVER,
            "EXPIRED",
            "Not acknowledged before expires_at"
        )

        return True

    def _expire_overdue_commands(
        self,
        db: Session,
        device: Device
    ):
        overdue_commands = (
            db.query(DeviceCommand)
            .filter(
                DeviceCommand.device_pk == device.id,
                DeviceCommand.status.notin_(
                    [status.value for status in FINAL_STATUSES]
                ),
                DeviceCommand.expires_at.isnot(None),
                DeviceCommand.expires_at <= utc_now()
            )
            .all()
        )

        for command in overdue_commands:
            self._expire_if_overdue(db, command)

    def _apply_acknowledged_command(
        self,
        db: Session,
        device: Device,
        command: DeviceCommand
    ):
        command_type = CommandType(command.command_type)
        payload_key, _, confirmed_column = COMMAND_FIELDS[command_type]

        # If a newer command of the same type was already acknowledged,
        # this late acknowledgement must not roll back the confirmed value
        newer_acknowledged = (
            db.query(DeviceCommand)
            .filter(
                DeviceCommand.device_pk == device.id,
                DeviceCommand.command_type == command_type.value,
                DeviceCommand.status == CommandStatus.ACKNOWLEDGED.value,
                DeviceCommand.id > command.id
            )
            .first()
        )

        if newer_acknowledged is not None:
            return

        configuration = self.configuration_service.get_or_create_configuration(
            db,
            device
        )

        self.configuration_service.set_confirmed(
            configuration,
            confirmed_column,
            command.payload[payload_key]
        )

    def _command_response(
        self,
        db: Session,
        device: Device,
        command: DeviceCommand,
        include_events: bool = False
    ):
        response = {
            "id": command.id,
            "device_id": device.device_id,
            "command_type": command.command_type,
            "payload": command.payload,
            "status": command.status,
            "created_by_user_id": command.created_by_user_id,
            "created_at": command.created_at,
            "updated_at": command.updated_at,
            "expires_at": command.expires_at,
            "delivered_at": command.delivered_at,
            "acknowledged_at": command.acknowledged_at,
        }

        if include_events:
            events = (
                db.query(DeviceCommandEvent)
                .filter(
                    DeviceCommandEvent.command_id == command.id
                )
                .order_by(DeviceCommandEvent.id)
                .all()
            )

            response["events"] = [
                {
                    "id": event.id,
                    "location": event.location,
                    "event": event.event,
                    "status": event.status,
                    "detail": event.detail,
                    "created_at": event.created_at,
                }
                for event in events
            ]

        return response
