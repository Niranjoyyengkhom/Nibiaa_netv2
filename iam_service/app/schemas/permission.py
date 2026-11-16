from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class PermissionCreate(BaseModel):
    code: str = Field(min_length=3, max_length=100)
    name: str = Field(min_length=2, max_length=150)
    description: Optional[str] = None
    category: str = Field(default="general")


class PermissionResponse(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    category: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PermissionCategoryGroup(BaseModel):
    category: str
    count: int
    permissions: List[PermissionResponse]

    model_config = {"from_attributes": True}
