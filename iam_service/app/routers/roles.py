from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.user_role import UserRole
from app.schemas.role import (
    RoleCreate,
    RoleUpdate,
    RoleResponse,
    RolePermissionAssign,
)
from app.services.role_service import role_service
from app.services.user_service import user_service
from app.dependencies.auth import get_current_user, require_admin

router = APIRouter(prefix="/roles", tags=["Role Management"])


@router.get("/", response_model=List[RoleResponse])
def get_roles(
    tenant_id: Optional[int] = Query(None, description="Filter by tenant ID"),
    include_global: bool = Query(True, description="Include global system roles"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        tenant_id = current_user.tenant_id
    return role_service.get_roles(db, tenant_id=tenant_id, include_global=include_global)


@router.get("/{role_id}", response_model=RoleResponse)
def get_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role = role_service.get_role_by_id(db, role_id)
    return role_service.role_to_dict(db, role)


@router.post("/", response_model=RoleResponse)
def create_role(
    data: RoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        data.tenant_id = current_user.tenant_id
    return role_service.create_role(db, data, actor=current_user)


@router.put("/{role_id}", response_model=RoleResponse)
def update_role(
    role_id: int,
    data: RoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role = role_service.get_role_by_id(db, role_id)
    if current_user.role != "admin" and role.tenant_id != current_user.tenant_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Permission denied")
    return role_service.update_role(db, role_id, data, actor=current_user)


@router.delete("/{role_id}")
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role = role_service.get_role_by_id(db, role_id)
    if current_user.role != "admin" and role.tenant_id != current_user.tenant_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Permission denied")
    return role_service.delete_role(db, role_id, actor=current_user)


@router.get("/{role_id}/permissions", response_model=List[str])
def get_role_permissions(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role_service.get_role_by_id(db, role_id)
    perms = role_service.get_effective_permissions_for_role(db, role_id)
    return sorted(list(perms))


@router.post("/{role_id}/permissions")
def assign_permissions_to_role(
    role_id: int,
    data: RolePermissionAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role = role_service.get_role_by_id(db, role_id)
    if current_user.role != "admin" and role.tenant_id != current_user.tenant_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Permission denied")
    return list(role_service.assign_permissions_by_codes(db, role_id, data.permission_codes))


@router.delete("/{role_id}/permissions/{permission_id}")
def remove_permission_from_role(
    role_id: int,
    permission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role = role_service.get_role_by_id(db, role_id)
    if current_user.role != "admin" and role.tenant_id != current_user.tenant_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Permission denied")
    return role_service.remove_permission(db, role_id, permission_id)


@router.get("/{role_id}/users")
def get_users_with_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role_service.get_role_by_id(db, role_id)
    user_roles = db.query(UserRole).filter(UserRole.role_id == role_id).all()
    users = []
    for ur in user_roles:
        u = user_service.get_user_by_id(db, ur.user_id)
        users.append(user_service.user_to_dict(db, u))
    return users
