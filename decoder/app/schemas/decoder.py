from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class DecoderMatch(BaseModel):
    providerId: Optional[str] = None
    protocolId: Optional[str] = None
    deviceTypeId: Optional[str] = None
    messageType: Optional[str] = None
    version: Optional[str] = None


class DecoderCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    code: str = Field(..., min_length=1)
    match: Optional[Dict[str, Any]] = None
    matching: Optional[Dict[str, Any]] = None


class DecoderResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    version: Optional[str] = None
    match: Dict[str, Any] = Field(default_factory=dict)
    code: Optional[str] = None
    status: str = "active"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None

    class Config:
        from_attributes = True
