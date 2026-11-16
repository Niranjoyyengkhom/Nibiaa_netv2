import base64
import binascii
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.payload_detector import detect_and_parse_payload

# ---------------------------------------------------------
# Incoming message
# ---------------------------------------------------------

def either(snake: str, camel: str):
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

    provider: str | None = Field(default=None, validation_alias=AliasChoices("provider", "providerId"))


class IncomingSource(BaseModel):
    device_id: str | None = either("device_id", "deviceId")

    protocol_id: str | None = either("protocol_id", "protocolId")
    message_type: str | None = either("message_type", "messageType")
    version: str | None = None


class IncomingPayload(BaseModel):
    """
    Dynamic incoming payload accepting Hex, Binary (bytes/bits), Base64, or JSON.
    Normalised to base64 with detected format preserved.
    """
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    data: Any
    format: str | None = None

    @model_validator(mode="before")
    @classmethod
    def process_incoming(cls, values):
        if not isinstance(values, dict):
            values = {"data": values}
        data_val = values.get("data")
        fmt_hint = values.get("format")
        try:
            raw, hex_str, detected_fmt, json_obj, b64_str, text_str = detect_and_parse_payload(data_val, fmt_hint)
        except Exception as e:
            raise ValueError(f"Could not parse payload data ({fmt_hint or 'auto'}): {e}")

        values["data"] = b64_str
        values["format"] = detected_fmt
        return values

    def raw_bytes(self) -> bytes:
        if isinstance(self.data, str):
            try:
                return base64.b64decode(self.data, validate=True)
            except Exception:
                pass
        raw, _, _, _, _, _ = detect_and_parse_payload(self.data, self.format)
        return raw

    def get_detected_format(self) -> str:
        return self.format or "binary"


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

    payload_format: str | None = either("payload_format", "payloadFormat")


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
    data_originator: str | None = None
    originator_device: str | None = None
    originator_source: str | None = None

    raw_payload_hex: str
    payload_format: str | None = None
    received_at: datetime

    provider: str | None
    connection_type: str | None
    decode_activation_id: int | None

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
    provider: str | None = None
    statuses: list[str] | None = None
    limit: int = Field(default=1000, ge=1, le=1000)


class ReprocessResponse(BaseModel):
    processed: int
    routed: int
    messages: list[DecodedMessageResponse]


# ---------------------------------------------------------
# Purging
# ---------------------------------------------------------

class PurgeResponse(BaseModel):
    deleted: int
