import hashlib
import os
import logging
from typing import Optional, List, Dict, Any
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.models.user import User
from app.models.role import Role
from app.models.user_role import UserRole
from app.schemas.user import UserCreate, UserUpdate
from app.services.role_service import role_service
from app.services.attribute_service import attribute_service
from app.services.audit_service import audit_service

logger = logging.getLogger("nibiaanet.iam.users")


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
    try:
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
    except Exception:
        return False


class UserService:
    def get_users(
        self,
        db: Session,
        tenant_id: Optional[int] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[dict]:
        query = db.query(User)

        if tenant_id is not None:
            query = query.filter(User.tenant_id == tenant_id)

        if role:
            query = query.filter(func.lower(User.role) == role.lower().strip())

        if is_active is not None:
            query = query.filter(User.is_active.is_(is_active))

        if search:
            pat = f"%{search.strip().lower()}%"
            query = query.filter(
                or_(
                    func.lower(User.name).like(pat),
                    func.lower(User.email).like(pat)
                )
            )

        users = query.order_by(User.id.asc()).offset(offset).limit(limit).all()
        return [self.user_to_dict(db, u) for u in users]

    def get_user_by_id(self, db: Session, user_id: int) -> User:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"User #{user_id} not found")
        return user

    def get_user_by_name_or_email(self, db: Session, ident: str) -> Optional[User]:
        ident = ident.strip()
        return (
            db.query(User)
            .filter(
                or_(
                    func.lower(User.name) == func.lower(ident),
                    func.lower(User.email) == func.lower(ident)
                )
            )
            .first()
        )

    def user_to_dict(self, db: Session, user: User) -> dict:
        assigned_roles = role_service.get_user_roles(db, user.id)
        role_names = [r.name for r in assigned_roles]
        if user.role and user.role not in role_names:
            role_names.append(user.role)

        # Permissions collected across all roles
        perms: set[str] = set()
        for r in assigned_roles:
            perms.update(role_service.get_effective_permissions_for_role(db, r.id))

        if user.role == "admin":
            perms.add("*")

        # Dynamic Attributes
        attrs = attribute_service.get_entity_attributes(db, "user", user.id)

        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "tenant_id": user.tenant_id,
            "tenant_name": None,  # Can be expanded if joined
            "is_active": user.is_active,
            "assigned_roles": sorted(role_names),
            "permissions": sorted(list(perms)),
            "attributes": attrs,
        }

    def create_user(
        self,
        db: Session,
        data: UserCreate,
        actor: Optional[User] = None,
    ) -> dict:
        email = data.email.strip().lower()
        if db.query(User).filter(func.lower(User.email) == email).first():
            raise HTTPException(status_code=409, detail=f"User with email '{email}' already exists")

        name = data.name.strip() if data.name else email.split("@")[0]
        # Check name uniqueness
        candidate = name
        suffix = 1
        while db.query(User).filter(func.lower(User.name) == candidate.lower()).first():
            candidate = f"{name}{suffix}"
            suffix += 1
        name = candidate

        new_user = User(
            name=name,
            email=email,
            role=data.role,
            tenant_id=data.tenant_id,
            password_hash=hash_password(data.password),
            is_active=True,
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        # Set initial attributes if provided
        if data.attributes:
            attribute_service.batch_set_entity_attributes(
                db, "user", new_user.id, data.attributes, data.tenant_id
            )

        # Check if role matches a defined Role entity to link in UserRole
        matched_role = (
            db.query(Role)
            .filter(func.lower(Role.name) == data.role.lower())
            .first()
        )
        if matched_role:
            role_service.assign_role_to_user(
                db, new_user.id, matched_role.id, new_user.tenant_id, actor.id if actor else None
            )

        audit_service.log(
            db,
            action="USER_CREATED",
            target_type="user",
            target_id=str(new_user.id),
            actor_id=actor.id if actor else None,
            actor_name=actor.name if actor else "system",
            tenant_id=new_user.tenant_id,
            details={"email": email, "role": new_user.role},
        )

        return self.user_to_dict(db, new_user)

    def update_user(
        self,
        db: Session,
        user_id: int,
        data: UserUpdate,
        actor: Optional[User] = None,
    ) -> dict:
        user = self.get_user_by_id(db, user_id)

        if data.email:
            email = data.email.strip().lower()
            existing = (
                db.query(User)
                .filter(func.lower(User.email) == email, User.id != user.id)
                .first()
            )
            if existing:
                raise HTTPException(status_code=409, detail=f"Email '{email}' is already taken")
            user.email = email

        if data.name:
            name = data.name.strip()
            existing = (
                db.query(User)
                .filter(func.lower(User.name) == name.lower(), User.id != user.id)
                .first()
            )
            if existing:
                raise HTTPException(status_code=409, detail=f"Name '{name}' is already taken")
            user.name = name

        if data.role:
            user.role = data.role

        if data.tenant_id is not None:
            user.tenant_id = data.tenant_id

        if data.password is not None:
            if actor and actor.id == user.id and user.password_hash:
                if not data.current_password or not verify_password(data.current_password, user.password_hash):
                    raise HTTPException(status_code=400, detail="Current password incorrect")
            user.password_hash = hash_password(data.password)

        db.commit()
        db.refresh(user)

        audit_service.log(
            db,
            action="USER_UPDATED",
            target_type="user",
            target_id=str(user.id),
            actor_id=actor.id if actor else None,
            actor_name=actor.name if actor else "system",
            tenant_id=user.tenant_id,
            details={"name": user.name, "role": user.role},
        )

        return self.user_to_dict(db, user)

    def delete_user(
        self,
        db: Session,
        user_id: int,
        actor: Optional[User] = None,
    ) -> dict:
        user = self.get_user_by_id(db, user_id)
        if actor and actor.id == user.id:
            raise HTTPException(status_code=400, detail="Cannot delete your own account")

        name = user.name
        db.delete(user)
        db.commit()

        audit_service.log(
            db,
            action="USER_DELETED",
            target_type="user",
            target_id=str(user_id),
            actor_id=actor.id if actor else None,
            actor_name=actor.name if actor else "system",
            details={"name": name},
        )

        return {"message": f"User '{name}' deleted successfully"}

    def set_active(
        self,
        db: Session,
        user_id: int,
        is_active: bool,
        actor: Optional[User] = None,
        reason: Optional[str] = None,
    ) -> dict:
        user = self.get_user_by_id(db, user_id)
        if actor and actor.id == user.id and not is_active:
            raise HTTPException(status_code=400, detail="Cannot revoke your own access")

        user.is_active = is_active
        db.commit()
        db.refresh(user)

        action_name = "USER_RESTORED" if is_active else "USER_REVOKED"
        audit_service.log(
            db,
            action=action_name,
            target_type="user",
            target_id=str(user.id),
            actor_id=actor.id if actor else None,
            actor_name=actor.name if actor else "system",
            tenant_id=user.tenant_id,
            details={"reason": reason, "is_active": is_active},
        )

        return self.user_to_dict(db, user)

    def change_password(
        self,
        db: Session,
        user_id: int,
        current_pass: str,
        new_pass: str,
    ) -> dict:
        user = self.get_user_by_id(db, user_id)
        if user.password_hash and not verify_password(current_pass, user.password_hash):
            raise HTTPException(status_code=400, detail="Current password incorrect")

        user.password_hash = hash_password(new_pass)
        db.commit()
        return {"message": "Password changed successfully"}


user_service = UserService()
