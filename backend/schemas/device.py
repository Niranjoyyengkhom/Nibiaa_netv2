from typing import Any

from pydantic import BaseModel, Field


class DeviceCreate(BaseModel):
    device_id: str = Field(min_length=1)
    name: str = Field(min_length=1)

    # Network type (NTN, TN, LoRa, BLE: app/network_types.py). Its
    # credentials are checked against the type's fields.
    device_type: str = Field(min_length=1)
    credentials: dict[str, str] | None = None

    # Admins only, optional: defaults to the application's organization.
    # Owners and collaborators always get their own organization.
    tenant_id: int | None = None

    application_id: int


class DeviceUpdate(BaseModel):
    name: str = Field(min_length=1)
    device_type: str = Field(min_length=1)
    application_id: int

    # None keeps the stored credentials; an empty secret keeps that secret
    credentials: dict[str, str] | None = None


class DeviceResponse(BaseModel):
    id: int
    device_id: str
    name: str
    device_type: str
    device_type_id: int | None = None
    tenant_id: int
    application_id: int
    application_name: str | None = None
    provider: str | None = None

    # Secrets (AppKey) are masked
    credentials: dict[str, Any] | None = None


class NetworkTypeField(BaseModel):
    key: str
    label: str
    placeholder: str
    pattern: str | None
    hint: str
    secret: bool
    unique: bool
    provider_type: str | None


class NetworkTypeResponse(BaseModel):
    value: str
    label: str
    description: str
    connection_type: str
    fields: list[NetworkTypeField]
