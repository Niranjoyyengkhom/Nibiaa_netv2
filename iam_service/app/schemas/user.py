from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator


class UserCreate(BaseModel):
    email: str = Field(min_length=3)
    name: Optional[str] = None
    role: str = Field(default="collaborator")
    tenant_id: Optional[int] = None
    password: str = Field(min_length=8)
    attributes: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        has_letter = any(c.isalpha() for c in v)
        has_digit_or_special = any(not c.isalpha() for c in v)
        if not (has_letter and has_digit_or_special):
            raise ValueError("Password must contain at least one letter and at least one number or special character")
        return v


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    tenant_id: Optional[int] = None
    password: Optional[str] = Field(default=None, min_length=8)
    current_password: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: Optional[str]):
        if v is None:
            return v
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        has_letter = any(c.isalpha() for c in v)
        has_digit_or_special = any(not c.isalpha() for c in v)
        if not (has_letter and has_digit_or_special):
            raise ValueError("Password must contain at least one letter and at least one number or special character")
        return v


class UserStatusUpdate(BaseModel):
    is_active: bool
    reason: Optional[str] = None


class UserPasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_password_complexity(cls, v: str):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        has_letter = any(c.isalpha() for c in v)
        has_digit_or_special = any(not c.isalpha() for c in v)
        if not (has_letter and has_digit_or_special):
            raise ValueError("Password must contain at least one letter and at least one number or special character")
        return v


class UserRoleAssign(BaseModel):
    role_ids: List[int]
    tenant_id: Optional[int] = None


class UserResponse(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    role: str
    tenant_id: Optional[int] = None
    tenant_name: Optional[str] = None
    is_active: bool = True
    assigned_roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    attributes: Dict[str, Any] = Field(default_factory=dict)
