from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    code: str = Field(min_length=2, max_length=100)
    description: Optional[str] = None
    tenant_id: Optional[int] = None
    parent_role_id: Optional[int] = None
    permission_codes: Optional[List[str]] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parent_role_id: Optional[int] = None
    permission_codes: Optional[List[str]] = None


class RolePermissionAssign(BaseModel):
    permission_codes: List[str]


class RoleResponse(BaseModel):
    id: int
    name: str
    code: str
    description: Optional[str] = None
    tenant_id: Optional[int] = None
    is_system: bool = False
    parent_role_id: Optional[int] = None
    parent_role_name: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    user_count: int = 0
    created_at: datetime
    updated_at: datetime
