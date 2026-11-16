from datetime import datetime
from typing import Optional, Union, Dict, Any
from pydantic import BaseModel


class AuditLogBase(BaseModel):
    action: str
    category: str = "GENERAL"
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[Union[Dict[str, Any], str]] = None
    ip_address: Optional[str] = None
    status: str = "SUCCESS"


class AuditLogCreate(AuditLogBase):
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    tenant_id: Optional[int] = None


class AuditLogResponse(BaseModel):
    id: int
    timestamp: datetime
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    tenant_id: Optional[int] = None
    tenant_name: Optional[str] = None
    action: str
    category: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[str] = None
    ip_address: Optional[str] = None
    status: str

    class Config:
        from_attributes = True


class AuditLogStatsResponse(BaseModel):
    total_logs: int
    success_count: int
    failed_count: int
    actions_today: int
    categories: Dict[str, int]
