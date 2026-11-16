from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class DeviceTypeDecoderCreate(BaseModel):
    decode_schema_id: int
    payload_format: Optional[str] = None  # "json", "hex", "binary", "base64", or None for any
    priority: int = 0
    is_active: bool = True


class DeviceTypeDecoderResponse(BaseModel):
    id: int
    device_type_id: int
    decode_schema_id: int
    decode_schema_name: Optional[str] = None
    decode_schema_version: Optional[int] = None
    payload_format: Optional[str] = None
    priority: int = 0
    is_active: bool = True
    created_at: Optional[datetime] = None


class DeviceTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: Optional[str] = None
    description: Optional[str] = None
    network_type: Optional[str] = None  # NTN, TN, LoRa, BLE, Direct IP
    decode_schema_ids: Optional[List[int]] = None


class DeviceTypeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    code: Optional[str] = None
    description: Optional[str] = None
    network_type: Optional[str] = None


class DeviceTypeResponse(BaseModel):
    id: int
    application_id: int
    name: str
    code: str
    description: Optional[str] = None
    network_type: Optional[str] = None
    device_count: int = 0
    decoders: List[DeviceTypeDecoderResponse] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
