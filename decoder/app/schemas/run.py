from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class RunDecoderRequest(BaseModel):
    code: str = Field(..., description="Decoder script defining transform(input) or decode(input)")
    payload: str = Field(..., description="Payload as hex, base64, or text string")
    format: Optional[str] = Field("auto", description="auto, hex, base64, or text")
    deviceId: Optional[str] = None
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    isTest: bool = Field(default=True, description="Flag indicating decoder test run (isolated from DB, MQTT, Webhook, REST API)")


class RunDecoderResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    units: Optional[Dict[str, Any]] = None
    device: Optional[Dict[str, Any]] = None
    deviceProvisioned: Optional[bool] = False
    detectedMetadata: Optional[Dict[str, Any]] = None
    isTest: bool = True
    output: Optional[Any] = None
    logs: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    payloadHex: Optional[str] = None
    detectedFormat: Optional[str] = "binary"
    message: Optional[Dict[str, Any]] = None
    failure: Optional[Dict[str, Any]] = None
