from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.collaborator_permission import CollaboratorPermission
from app.models.collaborator_role import CollaboratorRole
from app.models.user import User
from app.schemas.collaborator_permission import (
    CollaboratorRoleCreate,
    CollaboratorRoleUpdate,
)
from app.services.collaborator_permission_service import (
    ADMIN,
    OWNER,
    function_flags,
)


class CollaboratorRoleService:
    """
    Named sets of collaborator functions ("Create Collaborator Roles").
    Admins create and change them; owners and admins assign them.
    """

    def get_roles(
        self,
        db: Session,
        current_user: User
    ):
        if current_user.role not in {ADMIN, OWNER}:
            raise HTTPException(
                status_code=403,
                detail="Only admins and owners can see collaborator roles"
            )

        roles = (
            db.query(CollaboratorRole)
            .order_by(CollaboratorRole.name)
            .all()
        )

        return [
            self.role_response(db, role)
            for role in roles
        ]

    def create_role(
        self,
        db: Session,
        data: CollaboratorRoleCreate,
        current_user: User
    ):
        self._require_admin(current_user)
        self._check_unique_name(db, data.name)

        role = CollaboratorRole(
            name=data.name.strip(),
            description=data.description,
            **function_flags(data),
        )

        db.add(role)
        db.commit()
        db.refresh(role)

        return self.role_response(db, role)

    def update_role(
        self,
        db: Session,
        role_id: int,
        data: CollaboratorRoleUpdate,
        current_user: User
    ):
        self._require_admin(current_user)

        role = self._get_role(db, role_id)
        self._check_unique_name(db, data.name, role.id)

        role.name = data.name.strip()
        role.description = data.description

        for function, value in function_flags(data).items():
            setattr(role, function, value)

        db.commit()
        db.refresh(role)

        return self.role_response(db, role)

    def delete_role(
        self,
        db: Session,
        role_id: int,
        current_user: User
    ):
        self._require_admin(current_user)

        role = self._get_role(db, role_id)

        assigned = self._collaborator_count(db, role.id)

        if assigned:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{assigned} collaborator(s) still have this role. "
                    "Assign them another role or custom functions first."
                )
            )

        db.delete(role)
        db.commit()

    def role_response(
        self,
        db: Session,
        role: CollaboratorRole
    ):
        return {
            "id": role.id,
            "name": role.name,
            "description": role.description,
            "created_at": role.created_at,
            "collaborator_count": self._collaborator_count(db, role.id),
            **function_flags(role),
        }

    # ================================
    # Helpers
    # ================================

    def _collaborator_count(
        self,
        db: Session,
        role_id: int
    ):
        return (
            db.query(func.count(CollaboratorPermission.id))
            .filter(CollaboratorPermission.role_id == role_id)
            .scalar()
        )

    def _get_role(
        self,
        db: Session,
        role_id: int
    ):
        role = db.get(CollaboratorRole, role_id)

        if role is None:
            raise HTTPException(
                status_code=404,
                detail="Collaborator role not found"
            )

        return role

    def _check_unique_name(
        self,
        db: Session,
        name: str,
        role_id: int | None = None
    ):
        query = (
            db.query(CollaboratorRole.id)
            .filter(func.lower(CollaboratorRole.name) == name.strip().lower())
        )

        if role_id is not None:
            query = query.filter(CollaboratorRole.id != role_id)

        if query.first() is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A collaborator role named '{name.strip()}' already exists"
            )

    def _require_admin(
        self,
        current_user: User
    ):
        if current_user.role != ADMIN:
            raise HTTPException(
                status_code=403,
                detail="Only admins can create or change collaborator roles"
            )
