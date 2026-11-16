from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: Dict[str, Any]


class IntrospectRequest(BaseModel):
    token: str


class IntrospectResponse(BaseModel):
    active: bool
    user_id: Optional[int] = None
    username: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    tenant_id: Optional[int] = None
    roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    attributes: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class UserMeResponse(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    role: str
    tenant_id: Optional[int] = None
    is_active: bool
    roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    attributes: Dict[str, Any] = Field(default_factory=dict)
