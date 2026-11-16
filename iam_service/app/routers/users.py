from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.user import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserPasswordChange,
    UserRoleAssign,
)
from app.schemas.attribute import BatchAttributeAssign
from app.services.user_service import user_service
from app.services.role_service import role_service
from app.services.attribute_service import attribute_service
from app.dependencies.auth import get_current_user, get_optional_user, require_admin

router = APIRouter(prefix="/users", tags=["User Management"])


@router.get("/", response_model=List[UserResponse])
def get_users(
    tenant_id: Optional[int] = Query(None, description="Filter by tenant ID"),
    role: Optional[str] = Query(None, description="Filter by primary role"),
    is_active: Optional[bool] = Query(None, description="Filter by account active status"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    # Non-admin users are scoped to their own tenant
    if current_user and current_user.role != "admin":
        tenant_id = current_user.tenant_id

    return user_service.get_users(
        db,
        tenant_id=tenant_id,
        role=role,
        is_active=is_active,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = user_service.get_user_by_id(db, user_id)
    if current_user.role != "admin" and user.tenant_id != current_user.tenant_id and user.id != current_user.id:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Cannot access user from another organization")
    return user_service.user_to_dict(db, user)


@router.post("/", response_model=UserResponse)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        # Tenant owners can only create users in their own tenant
        data.tenant_id = current_user.tenant_id
        if data.role == "admin":
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Only platform admins can create administrators")

    return user_service.create_user(db, data, actor=current_user)


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = user_service.get_user_by_id(db, user_id)
    if current_user.role != "admin" and target.id != current_user.id:
        if current_user.role != "owner" or target.tenant_id != current_user.tenant_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Permission denied")

    return user_service.update_user(db, user_id, data, actor=current_user)


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = user_service.get_user_by_id(db, user_id)
    if current_user.role != "admin":
        if current_user.role != "owner" or target.tenant_id != current_user.tenant_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Permission denied")

    return user_service.delete_user(db, user_id, actor=current_user)


@router.post("/{user_id}/revoke", response_model=UserResponse)
def revoke_user_access(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = user_service.get_user_by_id(db, user_id)
    if current_user.role != "admin":
        if current_user.role != "owner" or target.tenant_id != current_user.tenant_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Permission denied")

    return user_service.set_active(db, user_id, is_active=False, actor=current_user)


@router.post("/{user_id}/restore", response_model=UserResponse)
def restore_user_access(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = user_service.get_user_by_id(db, user_id)
    if current_user.role != "admin":
        if current_user.role != "owner" or target.tenant_id != current_user.tenant_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Permission denied")

    return user_service.set_active(db, user_id, is_active=True, actor=current_user)


@router.post("/{user_id}/password")
def change_user_password(
    user_id: int,
    data: UserPasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != user_id and current_user.role != "admin":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Permission denied")
    return user_service.change_password(db, user_id, data.current_password, data.new_password)


# ------------------------------------------------------------------
# User Roles
# ------------------------------------------------------------------

@router.get("/{user_id}/roles")
def get_user_assigned_roles(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_service.get_user_by_id(db, user_id)
    roles = role_service.get_user_roles(db, user_id)
    return [role_service.role_to_dict(db, r) for r in roles]


@router.post("/{user_id}/roles")
def assign_roles_to_user(
    user_id: int,
    data: UserRoleAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = user_service.get_user_by_id(db, user_id)
    for rid in data.role_ids:
        role_service.assign_role_to_user(
            db, user_id=user.id, role_id=rid, tenant_id=data.tenant_id, assigned_by=current_user.id
        )
    return user_service.user_to_dict(db, user)


@router.delete("/{user_id}/roles/{role_id}")
def remove_role_from_user(
    user_id: int,
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return role_service.remove_role_from_user(db, user_id, role_id)


# ------------------------------------------------------------------
# User Attributes
# ------------------------------------------------------------------

@router.get("/{user_id}/attributes")
def get_user_attributes(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    user_service.get_user_by_id(db, user_id)
    return attribute_service.get_entity_attributes(db, "user", user_id)


@router.put("/{user_id}/attributes")
def update_user_attributes(
    user_id: int,
    data: BatchAttributeAssign,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    user = user_service.get_user_by_id(db, user_id)
    return attribute_service.batch_set_entity_attributes(
        db, "user", user.id, data.attributes, data.tenant_id or user.tenant_id
    )
