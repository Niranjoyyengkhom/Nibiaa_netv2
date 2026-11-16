from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
import hashlib
import os

from app.models.collaborator_role import CollaboratorRole
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.services.collaborator_permission_service import (
    collaborator_permission_service,
)
from app.services.notification_service import NotificationType, notify_owners, notify_users
from app.services.email_service import email_service


def hash_password(password: str) -> str:
    salt = os.urandom(16)

    password_hash = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1
    )

    return f"{salt.hex()}:{password_hash.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    salt_hex, hash_hex = stored_hash.split(":")

    salt = bytes.fromhex(salt_hex)

    password_hash = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1
    )

    return password_hash.hex() == hash_hex

class UserService:

    def get_users(
        self,
        db: Session,
        current_user: User
    ):

        query = db.query(User)

        # ADMIN
        if current_user.role == "admin":
            pass

        # OWNER / COLLABORATOR
        elif current_user.role in ["owner", "collaborator"]:

            if current_user.tenant_id is None:
                raise HTTPException(
                    status_code=403,
                    detail="User has no organization"
                )

            query = query.filter(
                User.tenant_id == current_user.tenant_id
            )

        else:
            raise HTTPException(
                status_code=403,
                detail="Invalid role"
            )

        return [
            self.user_response(db, user)
            for user in query.order_by(User.id).all()
        ]

    def get_user(
        self,
        db: Session,
        user_id: int,
        current_user: User
    ):

        user = self._find_user(db, user_id)

        # ADMIN
        if current_user.role == "admin":
            return self.user_response(db, user)

        # OWNER
        if current_user.role == "owner":

            if user.tenant_id != current_user.tenant_id:
                raise HTTPException(
                    status_code=403,
                    detail="Cannot access another organization"
                )

            return self.user_response(db, user)

        # COLLABORATOR
        if current_user.role == "collaborator":

            # Collaborator can access their own user record
            if user.id == current_user.id:
                return self.user_response(db, user)

            raise HTTPException(
                status_code=403,
                detail="Collaborator cannot access other users"
            )

        raise HTTPException(
            status_code=403,
            detail="Invalid role"
        )

    def create_user(
        self,
        db: Session,
        data: UserCreate,
        current_user: User
    ):

        tenant_id = data.tenant_id

        # COLLABORATOR
        if current_user.role == "collaborator":
            raise HTTPException(
                status_code=403,
                detail="Collaborator cannot create users"
            )

        # OWNER
        if current_user.role == "owner":

            # Owner can only create collaborators
            if data.role != "collaborator":
                raise HTTPException(
                    status_code=403,
                    detail="Owner can only create Collaborators"
                )

            # Owner can only create users in their organization
            if tenant_id is not None and tenant_id != current_user.tenant_id:
                raise HTTPException(
                    status_code=403,
                    detail="Cannot create user in another organization"
                )

            tenant_id = current_user.tenant_id

        # ADMIN
        if current_user.role == "admin":

            # Admins are platform users, not members of an organization
            if data.role == "admin":
                tenant_id = None

            # Admin must provide an organization for non-admin users
            elif tenant_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="Organization is required"
                )

            elif db.get(Tenant, tenant_id) is None:
                raise HTTPException(
                    status_code=404,
                    detail="Organization not found"
                )

        email = data.email.strip().lower()
        self._check_unique_email(db, email)

        if data.name and data.name.strip():
            name = data.name.strip()
            self._check_unique_name(db, name)
        else:
            base_name = email.split("@")[0]
            candidate = base_name
            suffix = 1
            while db.query(User.id).filter(func.lower(User.name) == candidate.lower()).first() is not None:
                candidate = f"{base_name}{suffix}"
                suffix += 1
            name = candidate

        new_user = User(
            name=name,
            email=email,
            role=data.role,
            tenant_id=tenant_id,
            password_hash=hash_password(data.password)
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        notify_users(
            db,
            [new_user.id],
            "Welcome to NibiaaNet",
            f"Your {new_user.role} account was created by {current_user.name}.",
            NotificationType.USER,
        )

        if new_user.tenant_id is not None:
            notify_owners(
                db,
                new_user.tenant_id,
                "New user",
                f"{current_user.name} added {new_user.name} as {new_user.role}.",
                NotificationType.USER,
            )

        if new_user.email:
            email_service.send_welcome_email_async(
                to_email=new_user.email,
                user_name=new_user.name,
                role=new_user.role,
                temporary_password=data.password,
            )

        return self.user_response(db, new_user)

    def update_user(
        self,
        db: Session,
        user_id: int,
        data: UserUpdate,
        current_user: User
    ):

        user = self._find_user(db, user_id)

        # Everyone may change their own profile (name, email, password)
        if user.id != current_user.id:
            self._check_can_manage(user, current_user, "update")

        if data.email and data.email.strip():
            email = data.email.strip().lower()
            self._check_unique_email(db, email, user.id)
            user.email = email

        if data.name and data.name.strip():
            self._check_unique_name(db, data.name, user.id)
            user.name = data.name.strip()

        if data.password is not None:
            # Self-service password changes require verifying current password
            if user.id == current_user.id and user.password_hash is not None:
                if not data.current_password:
                    raise HTTPException(
                        status_code=400,
                        detail="Current password is required to set a new password"
                    )
                if not verify_password(data.current_password, user.password_hash):
                    raise HTTPException(
                        status_code=400,
                        detail="Current password is incorrect"
                    )

            user.password_hash = hash_password(data.password)

        db.commit()
        db.refresh(user)

        return self.user_response(db, user)

    def delete_user(
        self,
        db: Session,
        user_id: int,
        current_user: User
    ):

        user = self._find_user(db, user_id)

        if user.id == current_user.id:
            raise HTTPException(
                status_code=400,
                detail="You cannot delete your own account"
            )

        self._check_can_manage(user, current_user, "delete")

        db.delete(user)
        db.commit()

        return {
            "message": "User deleted"
        }

    def set_active(
        self,
        db: Session,
        user_id: int,
        active: bool,
        current_user: User
    ):
        """
        Revoke Collaborator (active=False) / restore access (True).
        A revoked user cannot sign in, and tokens already issued stop
        working on the next request. Nothing is deleted.
        """

        user = self._find_user(db, user_id)

        if user.id == current_user.id:
            raise HTTPException(
                status_code=400,
                detail="You cannot revoke your own access"
            )

        self._check_can_manage(user, current_user, "revoke")

        user.is_active = active

        db.commit()
        db.refresh(user)

        return self.user_response(db, user)

    def user_response(
        self,
        db: Session,
        user: User
    ):
        tenant = (
            db.get(Tenant, user.tenant_id)
            if user.tenant_id is not None
            else None
        )

        response = {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "tenant_id": user.tenant_id,
            "tenant_name": tenant.name if tenant else None,
            "is_active": user.is_active,
            "collaborator_role_name": None,
            "functions": [],
        }

        if user.role == "collaborator":
            row = collaborator_permission_service._permission_row(db, user.id)

            role = (
                db.get(CollaboratorRole, row.role_id)
                if row is not None and row.role_id is not None
                else None
            )

            response["collaborator_role_name"] = role.name if role else None
            response["functions"] = [
                function
                for function, allowed in (
                    collaborator_permission_service
                    .effective_permissions(db, user)
                    .items()
                )
                if allowed
            ]

        return response

    def _check_can_manage(
        self,
        user: User,
        current_user: User,
        action: str
    ):
        """
        Admins manage every user. Owners manage the collaborators of
        their own organization ("Manage / Revoke Collaborator").
        """

        if current_user.role == "admin":
            return

        if current_user.role == "owner":

            if user.tenant_id != current_user.tenant_id:
                raise HTTPException(
                    status_code=403,
                    detail=f"Cannot {action} user from another organization"
                )

            if user.role != "collaborator":
                raise HTTPException(
                    status_code=403,
                    detail=f"Owners can only {action} collaborators"
                )

            return

        raise HTTPException(
            status_code=403,
            detail=f"Collaborator cannot {action} users"
        )

    def _check_unique_name(
        self,
        db: Session,
        name: str,
        user_id: int | None = None
    ):
        # Users sign in with their name, so it must be unique
        query = (
            db.query(User.id)
            .filter(func.lower(User.name) == name.strip().lower())
        )

        if user_id is not None:
            query = query.filter(User.id != user_id)

        if query.first() is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A user named '{name.strip()}' already exists"
            )

    def _check_unique_email(
        self,
        db: Session,
        email: str,
        user_id: int | None = None
    ):
        query = (
            db.query(User.id)
            .filter(func.lower(User.email) == email.strip().lower())
        )

        if user_id is not None:
            query = query.filter(User.id != user_id)

        if query.first() is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A user with email '{email.strip()}' already exists"
            )

    def _find_user(
        self,
        db: Session,
        user_id: int
    ):

        user = (
            db.query(User)
            .filter(User.id == user_id)
            .first()
        )

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        return user
