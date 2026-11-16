from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# NTN = satellite, TN = terrestrial
ConnectionType = Literal["NTN", "TN"]

# planned = listed, not integrated yet
IntegrationStatus = Literal["planned", "available"]

# How a provider's ground segment delivers uplinks: HTTPS, MQTT, TCP/IP, UDP, Webhook, Custom
ProfileTransport = Literal["https", "mqtt", "tcp", "udp", "webhook", "custom", "satellite"]

# How an uplink is matched to its provider (provider_sources):
SourceTransport = Literal["https", "mqtt", "tcp", "udp", "webhook", "custom", "satellite"]


class ConnectivityProfileUpdate(BaseModel):
    name: str = Field(min_length=1)
    connection_type: ConnectionType
    integration_status: IntegrationStatus = "planned"

    # Disabled: kept for history, uplinks are refused
    enabled: bool = True

    transport: ProfileTransport | None = None

    # Larger uplinks are refused; None = no limit
    max_payload_bytes: int | None = Field(default=None, ge=1, le=65535)

    description: str | None = None


class ConnectivityProfileCreate(ConnectivityProfileUpdate):
    # Stable identifier stored in telemetry.provider, e.g. "sateliot".
    # Cannot be changed later.
    code: str = Field(
        min_length=2,
        max_length=40,
        pattern=r"^[a-z][a-z0-9_]*$"
    )


class ConnectivityProfileResponse(BaseModel):
    id: int
    code: str
    name: str
    connection_type: ConnectionType
    integration_status: IntegrationStatus
    enabled: bool
    transport: str | None
    max_payload_bytes: int | None
    description: str | None
    created_at: datetime
    updated_at: datetime

    # Source mappings (IP / client id) of this provider
    source_count: int

    # Telemetry records carried by this provider
    uplink_count: int


class ProviderSourceCreate(BaseModel):
    transport: SourceTransport

    # udp / satellite: source IP of the provider's ground segment
    # tcp / mqtt: client / session id
    identity: str = Field(min_length=1)


class ProviderSourceResponse(BaseModel):
    id: int
    provider: str
    transport: str
    identity: str
    created_at: datetime
