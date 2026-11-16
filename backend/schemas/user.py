from typing import Literal

from pydantic import BaseModel, Field, field_validator


class UserCreate(BaseModel):
    email: str = Field(min_length=3)
    name: str | None = None
    role: Literal["admin", "owner", "collaborator"]
    tenant_id: int | None = None
    password: str = Field(min_length=8)

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
    name: str | None = None
    email: str | None = None
    password: str | None = Field(default=None, min_length=8)
    current_password: str | None = Field(default=None)

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str | None):
        if v is None:
            return v
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        has_letter = any(c.isalpha() for c in v)
        has_digit_or_special = any(not c.isalpha() for c in v)
        if not (has_letter and has_digit_or_special):
            raise ValueError("Password must contain at least one letter and at least one number or special character")
        return v


class UserResponse(BaseModel):
    id: int
    name: str
    email: str | None = None
    role: Literal["admin", "owner", "collaborator"]
    tenant_id: int | None = None
    tenant_name: str | None = None

    # False = access revoked
    is_active: bool = True

    # Collaborators only: assigned role (None = custom functions)
    # and the functions they really have
    collaborator_role_name: str | None = None
    functions: list[str] = []
