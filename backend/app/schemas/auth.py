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


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str
    level: Literal["individual", "organization"] = "individual"
    organization_name: str | None = None


class SignupResponse(BaseModel):
    status: str = "pending_activation"
    message: str
    email: str
    level: str
    dev_code: str | None = None


class ActivateRequest(BaseModel):
    email: str | None = None
    code: str | None = None
    token: str | None = None


class ActivateResponse(BaseModel):
    success: bool
    message: str
    access_token: str | None = None
    user_name: str | None = None


class ResendActivationRequest(BaseModel):
    email: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ForgotPasswordResponse(BaseModel):
    success: bool
    message: str
    email: str
    dev_code: str | None = None


class ResetPasswordRequest(BaseModel):
    email: str
    code: str | None = None
    token: str | None = None
    new_password: str


class ResetPasswordResponse(BaseModel):
    success: bool
    message: str


