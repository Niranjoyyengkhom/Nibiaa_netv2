import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.payload_decoder import (
    DATA_TYPE_SIZES,
    DATA_TYPES,
    NUMERIC_TYPES,
)


FIELD_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# Canonical fields the pipeline itself uses:
#   device_id -> routing to the device / tenant
#   timestamp -> measurement time, Unix seconds (after scaling)
IDENTIFIER_TYPES = {
    "ascii",
    "hex",
    "uint8",
    "uint16",
    "uint32",
    "uint64",
}


class DecodeField(BaseModel):
    # Canonical NibiaaNet name of the value
    field_name: str

    # Where the field starts in the raw payload
    byte_offset: int = Field(ge=0)

    # How many bytes it occupies
    byte_length: int = Field(ge=1, le=255)

    data_type: Literal[tuple(DATA_TYPES)]

    # physical value = raw value * scale_factor + value_offset
    scale_factor: float = 1

    value_offset: float = 0

    # e.g. "°C", "%RH", "g", "lux", "deg"
    unit: str | None = None

    # bitfield only
    bit_offset: int | None = Field(
        default=None,
        ge=0
    )

    bit_length: int | None = Field(
        default=None,
        ge=1
    )

    @model_validator(mode="after")
    def check_consistency(self):
        if not FIELD_NAME_PATTERN.match(self.field_name):
            raise ValueError(
                f"field_name '{self.field_name}' "
                "must be lower_snake_case"
            )

        size = DATA_TYPE_SIZES.get(self.data_type)

        if size is not None and self.byte_length != size:
            raise ValueError(
                f"{self.field_name}: "
                f"{self.data_type} needs byte_length {size}"
            )

        if self.data_type == "bitfield":
            if (
                self.bit_offset is None
                or self.bit_length is None
            ):
                raise ValueError(
                    f"{self.field_name}: "
                    "bitfield needs bit_offset and bit_length"
                )

            if self.byte_length > 8:
                raise ValueError(
                    f"{self.field_name}: "
                    "bitfield can span at most 8 bytes"
                )

            if (
                self.bit_offset + self.bit_length
                > self.byte_length * 8
            ):
                raise ValueError(
                    f"{self.field_name}: "
                    f"bits do not fit in "
                    f"{self.byte_length} bytes"
                )

        elif (
            self.bit_offset is not None
            or self.bit_length is not None
        ):
            raise ValueError(
                f"{self.field_name}: "
                "bit_offset / bit_length are only for bitfield"
            )

        if self.data_type not in NUMERIC_TYPES and (
            self.scale_factor != 1
            or self.value_offset != 0
        ):
            raise ValueError(
                f"{self.field_name}: "
                f"{self.data_type} cannot be scaled"
            )

        if (
            self.field_name == "device_id"
            and self.data_type not in IDENTIFIER_TYPES
        ):
            raise ValueError(
                "device_id must be ascii, hex "
                "or an unsigned integer"
            )

        if (
            self.field_name == "timestamp"
            and self.data_type not in NUMERIC_TYPES
        ):
            raise ValueError(
                "timestamp must be numeric (Unix seconds)"
            )

        return self


# Matching criteria of a decoder (DecoderMatch). Keys are camelCase in
# JSON, as in the decoder contract; every key is optional.
class DecoderMatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # Connectivity profile code, e.g. "sateliot"
    provider_id: str | None = Field(default=None, alias="providerId", max_length=100)

    # IncomingMessage.source.protocolId, else the transport type
    protocol_id: str | None = Field(default=None, alias="protocolId", max_length=100)

    # devices.device_type of the registered device
    device_type_id: str | None = Field(default=None, alias="deviceTypeId", max_length=100)

    # IncomingMessage.source.messageType
    message_type: str | None = Field(default=None, alias="messageType", max_length=100)

    # IncomingMessage.source.version (payload / firmware version)
    version: str | None = Field(default=None, max_length=100)

    # Payload format affinity: "json" | "hex" | "binary" | "base64" (or None for any)
    payload_format: str | None = Field(default=None, alias="payloadFormat", max_length=50)

    @field_validator("*")
    @classmethod
    def blank_is_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    def criteria(self):
        # {attribute: value} of the criteria that are set
        return {
            key: value
            for key, value in self.model_dump().items()
            if value is not None
        }


MATCH_KEYS = ["provider_id", "protocol_id", "device_type_id", "message_type", "version", "payload_format"]


class DecodeSchemaCreate(BaseModel):
    # Name of the decoder, e.g. "environmental_sensors".
    # Creating a decoder with an existing name adds a new version.
    name: str = Field(min_length=1)

    # Admins only: the organization that owns the decoder;
    # None = platform decoder, usable by every organization.
    # Owners and collaborators always get their own organization.
    tenant_id: int | None = None

    # DecoderDefinition.code: JavaScript defining
    #   function decode(input) { ... return { temperature: 21.5 }; }
    # input = { payload: { bytes: Uint8Array }, context: MessageContext }
    code: str | None = Field(default=None, max_length=50_000)

    # Or a declarative field list (earlier decoders)
    byte_order: Literal["big", "little"] = "big"

    fields: list[DecodeField] | None = None

    # DecoderMatch; empty = only used when assigned to an application
    match: DecoderMatch = DecoderMatch()

    # What changed compared to the previous version
    description: str | None = None

    @field_validator("fields")
    @classmethod
    def unique_field_names(
        cls,
        fields: list[DecodeField] | None
    ):
        if fields is None:
            return fields

        names = [
            field.field_name
            for field in fields
        ]

        duplicates = sorted(
            {
                name
                for name in names
                if names.count(name) > 1
            }
        )

        if duplicates:
            raise ValueError(
                f"duplicate field_name: "
                f"{', '.join(duplicates)}"
            )

        return fields

    @model_validator(mode="after")
    def code_or_fields(self):
        has_code = bool(self.code and self.code.strip())
        has_fields = bool(self.fields)

        if has_code == has_fields:
            raise ValueError("Give either code (JavaScript) or fields, not both")

        return self


class DecodeSchemaResponse(BaseModel):
    id: int

    # None = platform decoder
    tenant_id: int | None

    name: str
    version: int

    # "javascript" or "fields"
    kind: str
    code: str | None

    byte_order: str
    fields: list[DecodeField]
    match: DecoderMatch
    description: str | None
    created_by: int | None
    created_at: datetime

    # ID of the active activation, if this
    # decoder version is currently active.
    active_activation_id: int | None

    # Applications decoding their uplinks with this version
    application_count: int


class DecodeSchemaActivate(BaseModel):
    note: str | None = None


class DecodeSchemaActivationResponse(BaseModel):
    activation_id: int
    schema_id: int
    schema_name: str
    schema_version: int
    note: str | None
    activated_by: int | None
    activated_at: datetime
    deactivated_at: datetime | None
    active: bool

    # Only when activating: applications moved to this version
    applications_updated: int | None = None


class DecodeTestRequest(BaseModel):
    payload_hex: str = Field(max_length=65536)

    # JavaScript decoders: input.context (MessageContext) for the dry run,
    # e.g. {"deviceId": "MAIN-01", "providerId": "sateliot"}
    context: dict = {}


class DecodeTestResponse(BaseModel):
    ok: bool
    decoded: dict | None
    units: dict | None
    error: str | None
    detected_format: str | None = None

class DecoderMatchRequest(DecoderMatch):
    # Admins: which organization's decoders to consider
    # (default: platform decoders only)
    tenant_id: int | None = None


class DecoderMatchCandidate(BaseModel):
    id: int
    name: str
    version: int
    tenant_id: int | None
    specificity: int


class DecoderMatchResponse(BaseModel):
    # The decoder the pipeline would pick for a device whose application
    # has no decoder, or None
    decoder: DecodeSchemaResponse | None

    # Every live decoder whose criteria fit, best first
    candidates: list[DecoderMatchCandidate]
