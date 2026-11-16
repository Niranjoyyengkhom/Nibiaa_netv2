import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import jwt
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.user_service import user_service, verify_password, hash_password
from app.services.role_service import role_service
from app.services.attribute_service import attribute_service

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev_nibiaanet_jwt_secret_key_change_in_prod_369")
ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))


class AuthService:
    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    def decode_token(self, token: str) -> dict:
        try:
            return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except jwt.PyJWTError as e:
            raise HTTPException(status_code=401, detail=f"Invalid or expired token: {e}")

    def login(
        self,
        db: Session,
        username: str,
        password: str,
    ) -> dict:
        ident = username.strip()
        user = user_service.get_user_by_name_or_email(db, ident)

        # Allow admin aliases ("admin", "nibiaa", "admin@nibiaa.com", "administrator")
        if user is None and ident.lower() in ("admin", "nibiaa", "admin@nibiaa.com", "administrator"):
            user = db.query(User).filter(User.role == "admin").first()

        if user is None:
            raise HTTPException(status_code=401, detail="Invalid username/email or password")

        is_valid = False
        if user.password_hash:
            is_valid = verify_password(password, user.password_hash)

        # Fallback developer password for uninitialized admin
        if not is_valid and user.role == "admin" and not user.password_hash:
            if password in ("Admin@123", "admin123", "admin", "Admin123", "Password123!"):
                is_valid = True
                user.password_hash = hash_password(password)
                db.commit()

        if not is_valid:
            raise HTTPException(status_code=401, detail="Invalid username/email or password")

        if not user.is_active:
            raise HTTPException(status_code=403, detail="User account is deactivated or revoked")

        user_dict = user_service.user_to_dict(db, user)

        token_data = {
            "sub": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "tenant_id": user.tenant_id,
            "permissions": user_dict["permissions"],
        }
        access_token = self.create_access_token(token_data)

        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": user_dict,
        }

    def introspect(self, db: Session, token: str) -> dict:
        """Token introspection endpoint for microservices."""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = payload.get("sub")
            if not user_id:
                return {"active": False, "error": "Missing subject claim"}

            user = db.query(User).filter(User.id == int(user_id)).first()
            if not user or not user.is_active:
                return {"active": False, "error": "User inactive or not found"}

            user_dict = user_service.user_to_dict(db, user)
            return {
                "active": True,
                "user_id": user.id,
                "username": user.name,
                "email": user.email,
                "role": user.role,
                "tenant_id": user.tenant_id,
                "roles": user_dict["assigned_roles"],
                "permissions": user_dict["permissions"],
                "attributes": user_dict["attributes"],
            }
        except Exception as e:
            return {"active": False, "error": str(e)}


auth_service = AuthService()
