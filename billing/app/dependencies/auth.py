import os
import logging
from typing import Optional
from fastapi import Depends, HTTPException, Request, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt.exceptions import InvalidTokenError
import psycopg

from app.config import JWT_SECRET_KEY, JWT_ALGORITHM, AUTH_DB_URL

logger = logging.getLogger("billing.auth")

security = HTTPBearer(auto_error=False)


class AuthUser:
    def __init__(
        self,
        id: int,
        email: str,
        role: str,
        tenant_id: Optional[int] = None,
        is_active: bool = True
    ):
        self.id = id
        self.email = email
        self.role = role
        self.tenant_id = tenant_id
        self.is_active = is_active

    def __repr__(self):
        return f"<AuthUser id={self.id} role={self.role} tenant_id={self.tenant_id}>"


def _lookup_user_by_id(user_id: int) -> Optional[AuthUser]:
    """Queries device_registry users table for user role & tenant_id."""
    try:
        with psycopg.connect(AUTH_DB_URL, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, email, role, tenant_id, is_active FROM users WHERE id = %s",
                    (user_id,)
                )
                row = cur.fetchone()
                if row:
                    return AuthUser(
                        id=row[0],
                        email=row[1],
                        role=row[2],
                        tenant_id=row[3],
                        is_active=bool(row[4])
                    )
    except Exception as e:
        logger.warning(f"Could not query auth DB for user {user_id}: {e}")
    return None


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_user_id: Optional[str] = Header(None),
    x_user_role: Optional[str] = Header(None),
    x_user_tenant_id: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None),
) -> AuthUser:
    """
    Resolves the authenticated user from:
    1. Gateway forwarded headers (X-User-Id, X-User-Role, etc.)
    2. Bearer JWT token (decoded & verified)
    """
    # 1. Check Gateway Headers
    if x_user_id:
        try:
            uid = int(x_user_id)
            tenant_id = int(x_user_tenant_id) if x_user_tenant_id and x_user_tenant_id.lower() != "none" else None
            role = x_user_role or "collaborator"
            email = x_user_email or f"user_{uid}@example.com"
            return AuthUser(id=uid, email=email, role=role, tenant_id=tenant_id, is_active=True)
        except ValueError:
            pass

    # 2. Check Bearer Token
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication credentials were not provided."
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM]
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: missing subject.")
        uid = int(user_id)
    except (InvalidTokenError, ValueError, TypeError) as e:
        raise HTTPException(status_code=401, detail=f"Invalid authentication token: {e}")

    # Check if payload contains role/tenant_id directly
    role = payload.get("role")
    tenant_id = payload.get("tenant_id")
    email = payload.get("email")

    if role:
        return AuthUser(
            id=uid,
            email=email or f"user_{uid}@example.com",
            role=role,
            tenant_id=tenant_id,
            is_active=True
        )

    # Lookup user from database
    user = _lookup_user_by_id(uid)
    if not user:
        raise HTTPException(status_code=401, detail="User account not found or access revoked.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Your user account has been deactivated.")

    return user


def require_admin(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Platform administrator privileges required.")
    return current_user
