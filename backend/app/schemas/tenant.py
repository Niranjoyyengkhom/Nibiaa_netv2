from typing import Literal

from pydantic import BaseModel, Field


class TenantCreate(BaseModel):
    name: str = Field(min_length=1)
    type: Literal["organization", "individual", "workspace", "team"] = "organization"


class TenantUpdate(TenantCreate):
    pass


class TenantResponse(BaseModel):
    id: int
    name: str
    type: str

    # False = access revoked by an admin
    is_active: bool = True

    user_count: int = 0
    application_count: int = 0
    device_count: int = 0
