import base64
import binascii
from datetime import datetime
from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------
# Incoming message
#
# Same shape as the adapters' TypeScript contract:
#
#   interface IncomingMessage {
#     id: string; receivedAt: Date;
#     transport: { type: "tcp" | "mqtt" | "udp" | "satellite";
#                  connectionId?; remoteAddress?; remotePort? };
#     source: { deviceId? };
#     payload: { data: Buffer };
#   }
#
# Keys are accepted in camelCase (as JSON.stringify sends them) or
# snake_case. payload.data may be base64, a byte array, or a Node Buffer
# serialised by JSON.stringify: {"type": "Buffer", "data": [1, 2, ...]}.
# ---------------------------------------------------------

def either(snake: str, camel: str):
    # Accept both spellings of a key
    return Field(default=None, validation_alias=AliasChoices(snake, camel))


class MessageTransport(str, Enum):
    TCP = "tcp"
    MQTT = "mqtt"
    UDP = "udp"
    SATELLITE = "satellite"


class IncomingTransport(BaseModel):
    type: MessageTransport

    connection_id: str | None = either("connection_id", "connectionId")
    remote_address: str | None = either("remote_address", "remoteAddress")
    remote_port: int | None = either("remote_port", "remotePort")

    # Connectivity profile code, when the adapter that received the
    # uplink knows its provider. Otherwise the provider is resolved
    # from the provider sources (remote_address / connection_id).
    provider: str | None = Field(default=None, validation_alias=AliasChoices("provider", "providerId"))


class IncomingSource(BaseModel):
    device_id: str | None = either("device_id", "deviceId")

    # Optional, for decoder matching (DecoderMatch) when the device's
    # application has no decoder. protocolId defaults to transport.type.
    protocol_id: str | None = either("protocol_id", "protocolId")
    message_type: str | None = either("message_type", "messageType")
    version: str | None = None


class IncomingPayload(BaseModel):
    """
    Raw binary payload, normalised to base64.
    """

    data: str = Field(max_length=1048576)

    @field_validator("data", mode="before")
    @classmethod
    def to_base64(cls, value):
        # Node Buffer through JSON.stringify
        if isinstance(value, dict) and value.get("type") == "Buffer":
            value = value.get("data")

        if isinstance(value, list):
            try:
                raw = bytes(value)
            except (TypeError, ValueError):
                raise ValueError("payload.data bytes must be integers 0..255")

        elif isinstance(value, str):
            try:
                raw = base64.b64decode(value, validate=True)
            except (ValueError, binascii.Error):
                raise ValueError("payload.data must be valid base64")

        else:
            raise ValueError("payload.data must be base64, a byte array or a Buffer")

        if not raw:
            raise ValueError("payload.data cannot be empty")

        return base64.b64encode(raw).decode()

    def raw_bytes(self) -> bytes:
        return base64.b64decode(self.data, validate=True)


class IncomingMessage(BaseModel):
    """
    Standard message entering the NibiaaNet ingestion pipeline.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str

    received_at: datetime = Field(validation_alias=AliasChoices("received_at", "receivedAt"))

    transport: IncomingTransport

    source: IncomingSource = IncomingSource()

    payload: IncomingPayload


# ---------------------------------------------------------
# Existing decoded-message response
# ---------------------------------------------------------

class DecodedMessageResponse(BaseModel):
    id: int
    status: str
    error: str | None

    transport: str
    source_address: str | None
    client_id: str | None
    device_identifier: str | None

    raw_payload_hex: str
    received_at: datetime

    # Connectivity profile code and NTN / TN; None when unknown
    provider: str | None
    connection_type: str | None
    decode_activation_id: int | None

    # IncomingMessage.id, match attributes, and the decoder used:
    # decoder_selection = "application" or "match"
    message_ref: str | None
    protocol_id: str | None
    message_type: str | None
    payload_version: str | None
    decode_schema_id: int | None
    decoder_selection: str | None

    decoded: dict | None
    units: dict | None

    device_id: str | None
    tenant_id: int | None
    telemetry_id: int | None

    mqtt_status: str | None
    attempts: int
    processed_at: datetime | None


# ---------------------------------------------------------
# Reprocessing
# ---------------------------------------------------------

class ReprocessRequest(BaseModel):
    # Only messages last seen with this provider;
    # all providers if missing.
    provider: str | None = None

    # Default: every status except ROUTED.
    statuses: list[str] | None = None

    limit: int = Field(
        default=1000,
        ge=1,
        le=1000
    )


class ReprocessResponse(BaseModel):
    processed: int
    routed: int
    messages: list[DecodedMessageResponse]


# ---------------------------------------------------------
# Purging
# ---------------------------------------------------------

class PurgeResponse(BaseModel):
    deleted: int