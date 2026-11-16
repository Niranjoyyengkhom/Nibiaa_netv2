from datetime import datetime

from pydantic import BaseModel, Field


MIN_WAKE_FREQUENCY_PER_DAY = 1
MAX_WAKE_FREQUENCY_PER_DAY = 24


class DeviceConfigurationUpdate(BaseModel):
    # Only the fields that are provided are changed
    wake_frequency_per_day: int | None = Field(
        default=None,
        ge=MIN_WAKE_FREQUENCY_PER_DAY,
        le=MAX_WAKE_FREQUENCY_PER_DAY
    )
    enabled: bool | None = None


class DeviceConfigurationResponse(BaseModel):
    device_id: str

    desired_enabled: bool | None
    desired_wake_frequency_per_day: int | None
    desired_updated_at: datetime | None

    confirmed_enabled: bool | None
    confirmed_wake_frequency_per_day: int | None
    confirmed_at: datetime | None

    # True when every desired value has been confirmed by the device
    in_sync: bool

    # Newest command still on its way to the device (None if nothing is)
    pending_command_id: int | None
    pending_command_status: str | None

    created_at: datetime
    updated_at: datetime


class QueuedCommandSummary(BaseModel):
    id: int
    command_type: str
    status: str


class DeviceConfigurationUpdateResponse(DeviceConfigurationResponse):
    # Commands created by this update. Empty when no command was needed
    # (the device already confirmed the value, or it is already on its way).
    # Their status is PENDING: stored on the server, not yet on the device.
    queued_commands: list[QueuedCommandSummary]
