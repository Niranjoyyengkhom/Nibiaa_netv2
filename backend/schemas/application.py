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
