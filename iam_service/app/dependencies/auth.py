import os
from typing import Optional, Callable
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.role_service import role_service

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev_nibiaanet_jwt_secret_key_change_in_prod_369")
ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication credentials required")

    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid authentication token payload")
        user_id = int(user_id)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication token invalid: {e}")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is deactivated or revoked")

    return user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> Optional[User]:
    if not credentials:
        return None
    try:
        return get_current_user(credentials, db)
    except Exception:
        return None


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Platform administrator privileges required")
    return current_user


def require_permission(perm_code: str) -> Callable:
    def dependency(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if current_user.role == "admin":
            return current_user

        roles = role_service.get_user_roles(db, current_user.id)
        for r in roles:
            perms = role_service.get_effective_permissions_for_role(db, r.id)
            if perm_code in perms or "*" in perms:
                return current_user

        raise HTTPException(
            status_code=403,
            detail=f"Missing required permission: '{perm_code}'"
        )
    return dependency
