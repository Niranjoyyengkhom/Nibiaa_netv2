from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class MessageIngestRequest(BaseModel):
    deviceId: Optional[str] = None
    payload: str = Field(..., description="Payload string (hex, base64 or text)")
    format: Optional[str] = Field("auto", description="auto, hex, base64, text")
    transport: Optional[str] = Field("http", description="http, mqtt, udp, satellite")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    tenantId: Optional[int] = None


class MessageItemResponse(BaseModel):
    messageId: str
    receivedAt: datetime
    deviceId: Optional[str] = None
    transport: str
    status: str
    body: Dict[str, Any]
    tenantId: Optional[int] = None

    class Config:
        from_attributes = True


class MessageListResponse(BaseModel):
    items: List[MessageItemResponse]
    count: int
    nextCursor: Optional[str] = None


class DeviceRegisterRequest(BaseModel):
    deviceId: str = Field(..., description="Unique Device Identifier")
    name: Optional[str] = Field(None, description="Human readable device name")
    deviceType: Optional[str] = Field("NTN", description="Network / Device type (NTN, TN, LoRaWAN, BLE, etc.)")
    tenantId: Optional[int] = None
    applicationId: Optional[int] = None
    application: Optional[str] = None
    appName: Optional[str] = None
    credentials: Optional[Dict[str, Any]] = None

