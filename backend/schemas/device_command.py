from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from app.models.device_command import CommandType
from app.schemas.device_configuration import (
    MAX_WAKE_FREQUENCY_PER_DAY,
    MIN_WAKE_FREQUENCY_PER_DAY,
)


# --------------------------------
# Payloads per command type
# --------------------------------

class SetWakeFrequencyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    frequency_per_day: int = Field(
        ge=MIN_WAKE_FREQUENCY_PER_DAY,
        le=MAX_WAKE_FREQUENCY_PER_DAY
    )


class SetEnabledPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool


PAYLOAD_MODELS = {
    CommandType.SET_WAKE_FREQUENCY: SetWakeFrequencyPayload,
    CommandType.SET_ENABLED: SetEnabledPayload,
}


# --------------------------------
# Requests
# --------------------------------

class DeviceCommandCreate(BaseModel):
    command_type: CommandType
    payload: dict
    expires_in_hours: int | None = Field(
        default=None,
        ge=1,
        le=24 * 30
    )

    @model_validator(mode="after")
    def validate_payload(self):
        payload_model = PAYLOAD_MODELS[self.command_type]

        try:
            self.payload = payload_model.model_validate(
                self.payload
            ).model_dump()
        except ValidationError as error:
            raise ValueError(
                f"Invalid payload for {self.command_type.value}: {error}"
            )

        return self


class DeviceCommandSimulate(BaseModel):
    """
    DEVELOPMENT / TESTING ONLY.

    Moves a command one step along the store-and-forward path.
    ACKNOWLEDGED is not allowed here; use the ack endpoint.
    """

    status: Literal[
        "GROUND_STATION_QUEUED",
        "SATELLITE_QUEUED",
        "DEVICE_DELIVERED",
        "FAILED",
        "EXPIRED",
    ]
    detail: str | None = None


class DeviceCommandAck(BaseModel):
    """
    DEVELOPMENT / TESTING ONLY.

    success = true  -> device applied the command
    success = false -> device rejected the command
    """

    success: bool = True
    detail: str | None = None


class DeviceCommandCancel(BaseModel):
    detail: str | None = None


# --------------------------------
# Responses
# --------------------------------

class DeviceCommandEventResponse(BaseModel):
    id: int
    location: str
    event: str
    status: str
    detail: str | None
    created_at: datetime


class DeviceCommandResponse(BaseModel):
    id: int
    device_id: str
    command_type: str
    payload: dict
    status: str
    created_by_user_id: int | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    delivered_at: datetime | None
    acknowledged_at: datetime | None


class DeviceCommandDetailResponse(DeviceCommandResponse):
    events: list[DeviceCommandEventResponse]
