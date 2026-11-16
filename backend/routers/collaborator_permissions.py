from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.collaborator_permission import (
    CollaboratorFunctionInfo,
    CollaboratorPermissionUpdate,
    CollaboratorPermissionResponse,
    CollaboratorRoleCreate,
    CollaboratorRoleResponse,
    CollaboratorRoleUpdate,
)
from app.services.collaborator_permission_service import (
    FUNCTIONS,
    collaborator_permission_service,
)
from app.services.collaborator_role_service import CollaboratorRoleService


router = APIRouter(
    prefix="/collaborators",
    tags=["Collaborator Permissions"],
)

roles_router = APIRouter(
    prefix="/collaborator-roles",
    tags=["Collaborator Roles"],
)

collaborator_role_service = CollaboratorRoleService()


@router.get(
    "/functions",
    response_model=list[CollaboratorFunctionInfo],
    summary="Functions an owner can give a collaborator",
)
def get_functions(
    current_user: User = Depends(get_current_user),
):
    return [
        {"key": key, "label": label, "description": description}
        for key, (label, description) in FUNCTIONS.items()
    ]


@router.get(
    "/{collaborator_id}/permissions",
    response_model=CollaboratorPermissionResponse,
    summary="Functions of a collaborator",
    description=(
        "Admins: any collaborator. Owners: collaborators of their own "
        "organization. Collaborators: themselves."
    ),
)
def get_collaborator_permissions(
    collaborator_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return collaborator_permission_service.get_permissions(
        db,
        collaborator_id,
        current_user,
    )


@router.put(
    "/{collaborator_id}/permissions",
    response_model=CollaboratorPermissionResponse,
    summary="Assign a role or custom functions to a collaborator",
    description=(
        "With role_id the collaborator gets that role's functions. "
        "Without it, the flags in the body are the collaborator's functions. "
        "Takes effect on the collaborator's next request."
    ),
)
def update_collaborator_permissions(
    collaborator_id: int,
    data: CollaboratorPermissionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return collaborator_permission_service.update_permissions(
        db,
        collaborator_id,
        data.model_dump(),
        current_user,
    )


# --------------------------------
# Collaborator roles
# --------------------------------

@roles_router.get(
    "/",
    response_model=list[CollaboratorRoleResponse],
    summary="List collaborator roles",
    description="Admins and owners (owners assign them to collaborators).",
)
def get_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return collaborator_role_service.get_roles(db, current_user)


@roles_router.post(
    "/",
    response_model=CollaboratorRoleResponse,
    summary="Create a collaborator role (admin)",
)
def create_role(
    data: CollaboratorRoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return collaborator_role_service.create_role(db, data, current_user)


@roles_router.put(
    "/{role_id}",
    response_model=CollaboratorRoleResponse,
    summary="Update a collaborator role (admin)",
    description="Every collaborator with this role gets the new functions.",
)
def update_role(
    role_id: int,
    data: CollaboratorRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return collaborator_role_service.update_role(db, role_id, data, current_user)


@roles_router.delete(
    "/{role_id}",
    status_code=204,
    summary="Delete a collaborator role (admin)",
    description="Refused while collaborators still have the role.",
)
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    collaborator_role_service.delete_role(db, role_id, current_user)
