from typing import Literal

from pydantic import BaseModel


class LoginRequest(BaseModel):
    name: str | None = ""
    email: str | None = None
    identifier: str | None = None
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CurrentUserResponse(BaseModel):
    id: int
    name: str
    email: str | None = None
    role: Literal["admin", "owner", "collaborator"]
    tenant_id: int | None
    tenant_name: str | None
    tenant_type: str | None

    # Name of the assigned collaborator role; None = custom functions
    collaborator_role_name: str | None

    # Collaborator functions the user has (all true for admins/owners)
    permissions: dict[str, bool]

    # Admin / owner functions
    capabilities: dict[str, bool]
