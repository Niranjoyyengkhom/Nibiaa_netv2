from pydantic import BaseModel, Field


class ApplicationCreate(BaseModel):
    name: str = Field(min_length=1)

    # Admins only: the organization. Owners always get their own.
    tenant_id: int | None = None

    # Decoder version used for the application's uplinks: one of the
    # organization's decoders or a platform decoder
    decode_schema_id: int | None = None


class ApplicationUpdate(BaseModel):
    name: str = Field(min_length=1)
    decode_schema_id: int | None = None


class ApplicationResponse(BaseModel):
    id: int
    name: str
    tenant_id: int
    decode_schema_id: int | None

    decoder_name: str | None = None
    decoder_version: int | None = None

    device_count: int = 0
    device_type_count: int = 0
    device_types: list = []
    decoders: list["ApplicationDecoderResponse"] = []


class ApplicationDecoderCreate(BaseModel):
    decode_schema_id: int
    payload_format: str | None = None  # 'json', 'hex', 'binary', 'base64', or None for Any
    priority: int = 0
    is_active: bool = True


class ApplicationDecoderUpdate(BaseModel):
    payload_format: str | None = None
    priority: int | None = None
    is_active: bool | None = None


class ApplicationDecoderResponse(BaseModel):
    id: int
    application_id: int
    decode_schema_id: int
    decode_schema_name: str | None = None
    decode_schema_version: int | None = None
    payload_format: str | None = None
    priority: int = 0
    is_active: bool = True

