from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.user import User
from app.models.collaborator_permission import CollaboratorPermission
from app.models.collaborator_role import CollaboratorRole
from app.services.notification_service import NotificationType, notify_users


ADMIN = "admin"
OWNER = "owner"
COLLABORATOR = "collaborator"


# The functions an owner can give a collaborator (RBAC matrix,
# COLLABORATORS column), in display order:
# key -> (label, what it allows)
FUNCTIONS = {
    "manage_devices": (
        "Manage Devices",
        "View and update devices, including remote configuration",
    ),
    "create_devices": (
        "Create Devices",
        "Register new devices",
    ),
    "delete_devices": (
        "Delete Devices",
        "Delete devices",
    ),
    "manage_application": (
        "Manage Application",
        "View and update applications (name, decoder)",
    ),
    "read_application_traffic": (
        "Read Application Traffic",
        "Read the telemetry received from the organization's devices",
    ),
    "create_decoder": (
        "Create Decoder",
        "Create decoders and new decoder versions",
    ),
    "manage_decoder": (
        "Manage Decoder",
        "View, test, activate (roll back) and delete decoders",
    ),
}


def function_flags(source) -> dict:
    # {function: bool} read from a CollaboratorPermission,
    # a CollaboratorRole or a request body
    return {
        function: bool(getattr(source, function, False))
        for function in FUNCTIONS
    }


class CollaboratorPermissionService:

    PERMISSIONS = set(FUNCTIONS)

    # ================================
    # Checks used by every service
    # ================================

    def effective_permissions(
        self,
        db: Session,
        user: User,
    ) -> dict:
        """
        {function: bool} the user really has.

        Admins and owners have every collaborator function through
        their role. A collaborator has the functions of the assigned
        role, or the custom functions when no role is assigned.
        """

        if user.role in {ADMIN, OWNER}:
            return {function: True for function in FUNCTIONS}

        if user.role != COLLABORATOR:
            return {function: False for function in FUNCTIONS}

        row = self._permission_row(db, user.id)

        if row is None:
            return {function: False for function in FUNCTIONS}

        if row.role_id is not None:
            role = db.get(CollaboratorRole, row.role_id)

            if role is not None:
                return function_flags(role)

        return function_flags(row)

    def has_permission(
        self,
        db: Session,
        user: User,
        permission: str,
    ) -> bool:

        if permission not in self.PERMISSIONS:
            return False

        return self.effective_permissions(db, user)[permission]

    def has_any(
        self,
        db: Session,
        user: User,
        permissions: list[str],
    ) -> bool:
        effective = self.effective_permissions(db, user)

        return any(
            effective.get(permission, False)
            for permission in permissions
        )

    def require(
        self,
        db: Session,
        user: User,
        *permissions: str,
    ):
        """
        403 unless the user has at least one of the functions.
        """

        if self.has_any(db, user, list(permissions)):
            return

        labels = " or ".join(
            FUNCTIONS[permission][0]
            for permission in permissions
        )

        raise HTTPException(
            status_code=403,
            detail=f"You need the '{labels}' function for this"
        )

    # ================================
    # Role assignment (owner / admin)
    # ================================

    def get_permissions(
        self,
        db: Session,
        collaborator_id: int,
        current_user: User,
    ):
        collaborator = self._find_collaborator(
            db,
            collaborator_id,
            current_user,
            allow_self=True,
        )

        return self.permission_response(
            db,
            collaborator,
            self._get_or_create_row(db, collaborator),
        )

    def update_permissions(
        self,
        db: Session,
        collaborator_id: int,
        permissions_data: dict,
        current_user: User,
    ):
        collaborator = self._find_collaborator(
            db,
            collaborator_id,
            current_user,
        )

        row = self._get_or_create_row(db, collaborator)

        role_id = permissions_data.get("role_id")

        if role_id is not None:
            role = db.get(CollaboratorRole, role_id)

            if role is None:
                raise HTTPException(
                    status_code=404,
                    detail="Collaborator role not found"
                )

            # The role decides. Its functions are also copied to the
            # custom set, so switching back to "custom" starts from them.
            row.role_id = role.id
            flags = function_flags(role)

        else:
            row.role_id = None
            flags = {}

            for permission, value in permissions_data.items():

                if permission == "role_id":
                    continue

                if permission not in self.PERMISSIONS:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unknown permission: {permission}"
                    )

                flags[permission] = bool(value)

        for permission, value in flags.items():
            setattr(row, permission, value)

        db.commit()
        db.refresh(row)

        if collaborator.id != current_user.id:
            granted = [
                permission.replace("_", " ")
                for permission in FUNCTIONS
                if getattr(row, permission, False)
            ]
            notify_users(
                db,
                [collaborator.id],
                "Your access changed",
                f"{current_user.name} updated your functions: "
                f"{', '.join(granted) if granted else 'none'}.",
                NotificationType.USER,
            )

        return self.permission_response(db, collaborator, row)

    def permission_response(
        self,
        db: Session,
        collaborator: User,
        row: CollaboratorPermission,
    ):
        role = (
            db.get(CollaboratorRole, row.role_id)
            if row.role_id is not None
            else None
        )

        return {
            "user_id": collaborator.id,
            "role_id": role.id if role else None,
            "role_name": role.name if role else None,
            # The functions the collaborator really has
            **self.effective_permissions(db, collaborator),
        }

    # ================================
    # Helpers
    # ================================

    def _permission_row(
        self,
        db: Session,
        user_id: int,
    ):
        return (
            db.query(CollaboratorPermission)
            .filter(
                CollaboratorPermission.user_id == user_id
            )
            .first()
        )

    def _get_or_create_row(
        self,
        db: Session,
        collaborator: User,
    ):
        row = self._permission_row(db, collaborator.id)

        if row is None:
            row = CollaboratorPermission(
                user_id=collaborator.id
            )

            db.add(row)
            db.commit()
            db.refresh(row)

        return row

    def _find_collaborator(
        self,
        db: Session,
        collaborator_id: int,
        current_user: User,
        allow_self: bool = False,
    ):
        collaborator = db.get(User, collaborator_id)

        is_self = (
            allow_self
            and current_user.id == collaborator_id
        )

        visible = collaborator is not None and (
            current_user.role == ADMIN
            or is_self
            or (
                current_user.role == OWNER
                and collaborator.tenant_id == current_user.tenant_id
            )
        )

        if not visible:
            if current_user.role not in {ADMIN, OWNER} and not is_self:
                raise HTTPException(
                    status_code=403,
                    detail="Only admins and owners can manage collaborator permissions"
                )

            # Another organization's user is not found, not revealed
            raise HTTPException(
                status_code=404,
                detail="Collaborator not found"
            )

        if collaborator.role != COLLABORATOR:
            raise HTTPException(
                status_code=400,
                detail="Permissions can only be assigned to collaborators"
            )

        return collaborator


collaborator_permission_service = CollaboratorPermissionService()
