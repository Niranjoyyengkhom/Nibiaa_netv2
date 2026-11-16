import logging
from typing import Optional, List, Set, Dict, Any
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.role import Role
from app.models.permission import Permission
from app.models.role_permission import RolePermission
from app.models.user_role import UserRole
from app.models.user import User
from app.schemas.role import RoleCreate, RoleUpdate
from app.services.audit_service import audit_service

logger = logging.getLogger("nibiaanet.iam.roles")


class RoleService:
    def get_roles(
        self,
        db: Session,
        tenant_id: Optional[int] = None,
        include_global: bool = True,
    ) -> List[dict]:
        query = db.query(Role)
        if tenant_id is not None:
            if include_global:
                query = query.filter((Role.tenant_id == tenant_id) | (Role.tenant_id.is_(None)))
            else:
                query = query.filter(Role.tenant_id == tenant_id)
        roles = query.order_by(Role.is_system.desc(), Role.name.asc()).all()

        return [self.role_to_dict(db, r) for r in roles]

    def get_role_by_id(self, db: Session, role_id: int) -> Role:
        role = db.query(Role).filter(Role.id == role_id).first()
        if not role:
            raise HTTPException(status_code=404, detail=f"Role #{role_id} not found")
        return role

    def get_role_by_code(self, db: Session, code: str) -> Optional[Role]:
        return db.query(Role).filter(func.lower(Role.code) == code.lower().strip()).first()

    def role_to_dict(self, db: Session, role: Role) -> dict:
        perms = self.get_effective_permissions_for_role(db, role.id)
        user_count = db.query(UserRole).filter(UserRole.role_id == role.id).count()

        parent_name = None
        if role.parent_role_id:
            parent = db.query(Role.name).filter(Role.id == role.parent_role_id).first()
            if parent:
                parent_name = parent[0]

        return {
            "id": role.id,
            "name": role.name,
            "code": role.code,
            "description": role.description,
            "tenant_id": role.tenant_id,
            "is_system": role.is_system,
            "parent_role_id": role.parent_role_id,
            "parent_role_name": parent_name,
            "permissions": sorted(list(perms)),
            "user_count": user_count,
            "created_at": role.created_at,
            "updated_at": role.updated_at,
        }

    def get_effective_permissions_for_role(self, db: Session, role_id: int) -> Set[str]:
        """
        Recursively resolves all permissions assigned to this role,
        plus permissions inherited from parent roles.
        """
        visited_roles = set()
        all_perms: Set[str] = set()

        curr_id = role_id
        while curr_id and curr_id not in visited_roles:
            visited_roles.add(curr_id)

            # Direct permissions
            direct = (
                db.query(Permission.code)
                .join(RolePermission, Permission.id == RolePermission.permission_id)
                .filter(RolePermission.role_id == curr_id)
                .all()
            )
            for p in direct:
                all_perms.add(p[0])

            # Move to parent role
            parent = db.query(Role.parent_role_id).filter(Role.id == curr_id).first()
            curr_id = parent[0] if parent else None

        return all_perms

    def create_role(
        self,
        db: Session,
        data: RoleCreate,
        actor: Optional[User] = None,
    ) -> dict:
        # Check uniqueness
        if self.get_role_by_code(db, data.code):
            raise HTTPException(status_code=409, detail=f"Role with code '{data.code}' already exists")

        name_exists = (
            db.query(Role)
            .filter(func.lower(Role.name) == data.name.strip().lower())
            .first()
        )
        if name_exists:
            raise HTTPException(status_code=409, detail=f"Role with name '{data.name}' already exists")

        if data.parent_role_id:
            self.get_role_by_id(db, data.parent_role_id)

        role = Role(
            name=data.name.strip(),
            code=data.code.strip().upper(),
            description=data.description,
            tenant_id=data.tenant_id,
            parent_role_id=data.parent_role_id,
            is_system=False,
        )
        db.add(role)
        db.commit()
        db.refresh(role)

        if data.permission_codes:
            self.assign_permissions_by_codes(db, role.id, data.permission_codes)

        audit_service.log(
            db,
            action="ROLE_CREATED",
            target_type="role",
            target_id=str(role.id),
            actor_id=actor.id if actor else None,
            actor_name=actor.name if actor else "system",
            tenant_id=role.tenant_id,
            details={"name": role.name, "code": role.code, "permissions": data.permission_codes},
        )

        return self.role_to_dict(db, role)

    def update_role(
        self,
        db: Session,
        role_id: int,
        data: RoleUpdate,
        actor: Optional[User] = None,
    ) -> dict:
        role = self.get_role_by_id(db, role_id)

        if data.name:
            # Check unique name
            existing = (
                db.query(Role)
                .filter(func.lower(Role.name) == data.name.strip().lower(), Role.id != role.id)
                .first()
            )
            if existing:
                raise HTTPException(status_code=409, detail=f"Role name '{data.name}' is already taken")
            role.name = data.name.strip()

        if data.description is not None:
            role.description = data.description

        if data.parent_role_id is not None:
            if data.parent_role_id == role.id:
                raise HTTPException(status_code=400, detail="A role cannot be its own parent")
            self.get_role_by_id(db, data.parent_role_id)
            role.parent_role_id = data.parent_role_id

        db.commit()
        db.refresh(role)

        if data.permission_codes is not None:
            # Replace permissions
            db.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
            self.assign_permissions_by_codes(db, role.id, data.permission_codes)

        audit_service.log(
            db,
            action="ROLE_UPDATED",
            target_type="role",
            target_id=str(role.id),
            actor_id=actor.id if actor else None,
            actor_name=actor.name if actor else "system",
            tenant_id=role.tenant_id,
            details={"name": role.name, "code": role.code},
        )

        return self.role_to_dict(db, role)

    def delete_role(
        self,
        db: Session,
        role_id: int,
        actor: Optional[User] = None,
    ) -> dict:
        role = self.get_role_by_id(db, role_id)
        if role.is_system:
            raise HTTPException(status_code=400, detail=f"System role '{role.name}' cannot be deleted")

        assigned_users = db.query(UserRole).filter(UserRole.role_id == role.id).count()
        if assigned_users > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete role '{role.name}' because {assigned_users} user(s) are assigned to it. Remove assignments first."
            )

        name = role.name
        db.delete(role)
        db.commit()

        audit_service.log(
            db,
            action="ROLE_DELETED",
            target_type="role",
            target_id=str(role_id),
            actor_id=actor.id if actor else None,
            actor_name=actor.name if actor else "system",
            details={"name": name},
        )

        return {"message": f"Role '{name}' deleted successfully"}

    def assign_permissions_by_codes(
        self,
        db: Session,
        role_id: int,
        permission_codes: List[str],
    ) -> Set[str]:
        self.get_role_by_id(db, role_id)
        perms = (
            db.query(Permission)
            .filter(Permission.code.in_([c.strip() for c in permission_codes]))
            .all()
        )

        for p in perms:
            exists = (
                db.query(RolePermission)
                .filter(RolePermission.role_id == role_id, RolePermission.permission_id == p.id)
                .first()
            )
            if not exists:
                db.add(RolePermission(role_id=role_id, permission_id=p.id))

        db.commit()
        return self.get_effective_permissions_for_role(db, role_id)

    def remove_permission(
        self,
        db: Session,
        role_id: int,
        permission_id: int,
    ) -> dict:
        mapping = (
            db.query(RolePermission)
            .filter(RolePermission.role_id == role_id, RolePermission.permission_id == permission_id)
            .first()
        )
        if mapping:
            db.delete(mapping)
            db.commit()
        return {"message": "Permission removed from role"}

    # ----------------------------------------------------
    # User-Role Mapping
    # ----------------------------------------------------

    def get_user_roles(self, db: Session, user_id: int) -> List[Role]:
        return (
            db.query(Role)
            .join(UserRole, Role.id == UserRole.role_id)
            .filter(UserRole.user_id == user_id)
            .all()
        )

    def assign_role_to_user(
        self,
        db: Session,
        user_id: int,
        role_id: int,
        tenant_id: Optional[int] = None,
        assigned_by: Optional[int] = None,
    ) -> UserRole:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        role = self.get_role_by_id(db, role_id)

        existing = (
            db.query(UserRole)
            .filter(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
                UserRole.tenant_id == tenant_id,
            )
            .first()
        )
        if existing:
            return existing

        user_role = UserRole(
            user_id=user_id,
            role_id=role_id,
            tenant_id=tenant_id,
            assigned_by=assigned_by,
        )
        db.add(user_role)
        db.commit()
        db.refresh(user_role)
        return user_role

    def remove_role_from_user(
        self,
        db: Session,
        user_id: int,
        role_id: int,
    ) -> dict:
        db.query(UserRole).filter(
            UserRole.user_id == user_id,
            UserRole.role_id == role_id,
        ).delete()
        db.commit()
        return {"message": "Role removed from user"}


role_service = RoleService()
