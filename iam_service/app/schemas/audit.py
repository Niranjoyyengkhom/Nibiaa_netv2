from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: int
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    action: str
    target_type: str
    target_id: Optional[str] = None
    tenant_id: Optional[int] = None
    details: Optional[Any] = None
    ip_address: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
