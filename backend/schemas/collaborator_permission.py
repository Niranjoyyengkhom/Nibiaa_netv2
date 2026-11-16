from datetime import datetime

from pydantic import BaseModel, Field


class CollaboratorFunctions(BaseModel):
    manage_devices: bool = False
    create_devices: bool = False
    delete_devices: bool = False
    manage_application: bool = False
    read_application_traffic: bool = False
    create_decoder: bool = False
    manage_decoder: bool = False


class CollaboratorPermissionUpdate(CollaboratorFunctions):
    # A collaborator role to assign. When set, the role's functions
    # apply and the flags in this body are ignored.
    # None = custom functions (the flags in this body).
    role_id: int | None = None


class CollaboratorPermissionResponse(BaseModel):
    user_id: int
    role_id: int | None
    role_name: str | None

    # The functions the collaborator really has
    manage_devices: bool
    create_devices: bool
    delete_devices: bool
    manage_application: bool
    read_application_traffic: bool
    create_decoder: bool
    manage_decoder: bool


# --------------------------------
# Collaborator roles (admin)
# --------------------------------

class CollaboratorRoleCreate(CollaboratorFunctions):
    name: str = Field(min_length=1)
    description: str | None = None


class CollaboratorRoleUpdate(CollaboratorRoleCreate):
    pass


class CollaboratorRoleResponse(CollaboratorFunctions):
    id: int
    name: str
    description: str | None
    created_at: datetime

    # Collaborators that currently have this role
    collaborator_count: int


class CollaboratorFunctionInfo(BaseModel):
    key: str
    label: str
    description: str
