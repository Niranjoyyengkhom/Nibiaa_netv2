import time
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.dependencies.auth import access_problem
from app.models.tenant import Tenant
from app.models.user import User
from app.services.collaborator_permission_service import (
    ADMIN,
    OWNER,
    collaborator_permission_service,
)
from app.services.user_service import verify_password


_failed_attempts: dict[str, list[float]] = defaultdict(list)
_lockout_until: dict[str, float] = {}

MAX_LOGIN_ATTEMPTS = 5
ATTEMPT_WINDOW_SECONDS = 300
LOCKOUT_DURATION_SECONDS = 900


def _clean_old_attempts(key: str, now: float):
    _failed_attempts[key] = [
        t for t in _failed_attempts[key]
        if now - t < ATTEMPT_WINDOW_SECONDS
    ]


def check_login_rate_limit(key: str):
    now = time.time()
    lockout = _lockout_until.get(key)
    if lockout and now < lockout:
        remaining = int(lockout - now)
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Locked out for {remaining} seconds."
        )

    _clean_old_attempts(key, now)
    if len(_failed_attempts[key]) >= MAX_LOGIN_ATTEMPTS:
        _lockout_until[key] = now + LOCKOUT_DURATION_SECONDS
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Temporarily locked for {LOCKOUT_DURATION_SECONDS // 60} minutes."
        )


def record_failed_login(key: str):
    now = time.time()
    _failed_attempts[key].append(now)


def clear_failed_logins(key: str):
    _failed_attempts.pop(key, None)
    _lockout_until.pop(key, None)


class AuthService:

    def login(
        self,
        db: Session,
        name: str,
        password: str,
        client_ip: str = "unknown"
    ):
        ident = name.strip()
        rate_limit_key = f"{ident.lower()}:{client_ip}"
        check_login_rate_limit(rate_limit_key)

        user = (
            db.query(User)
            .filter(
                or_(
                    func.lower(User.name) == func.lower(ident),
                    func.lower(User.email) == func.lower(ident)
                )
            )
            .first()
        )

        if user is None:
            record_failed_login(rate_limit_key)
            raise HTTPException(
                status_code=401,
                detail="Invalid username/email or password"
            )

        if user.password_hash is None:
            record_failed_login(rate_limit_key)
            raise HTTPException(
                status_code=401,
                detail="User does not have a password configured"
            )

        if not verify_password(
            password,
            user.password_hash
        ):
            record_failed_login(rate_limit_key)
            raise HTTPException(
                status_code=401,
                detail="Invalid username/email or password"
            )

        clear_failed_logins(rate_limit_key)

        problem = access_problem(db, user)

        if problem is not None:
            raise HTTPException(
                status_code=403,
                detail=problem
            )

        return user

    def me(
        self,
        db: Session,
        user: User
    ):
        """
        The signed-in user with everything the frontend needs to show
        only the pages and buttons the user can really use.
        """

        is_admin = user.role == ADMIN
        is_manager = user.role in {ADMIN, OWNER}

        # Admin has no organization or workspace (manages the global platform)
        effective_tenant_id = None if is_admin else user.tenant_id
        tenant = (
            db.get(Tenant, effective_tenant_id)
            if effective_tenant_id is not None
            else None
        )

        permission_info = (
            collaborator_permission_service.get_permissions(db, user.id, user)
            if user.role == "collaborator"
            else None
        )

        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "tenant_id": effective_tenant_id,
            "tenant_name": tenant.name if tenant else None,
            "tenant_type": tenant.type if tenant else None,
            "collaborator_role_name": (
                permission_info["role_name"] if permission_info else None
            ),
            # Collaborator functions (all true for admins and owners)
            "permissions": collaborator_permission_service.effective_permissions(db, user),
            # Admin / owner functions of the RBAC matrix
            "capabilities": {
                "manage_organizations": is_admin,
                "manage_collaborator_roles": is_admin,
                "manage_connectivity_profiles": is_admin,
                "use_ingestion": is_admin,
                "manage_users": is_manager,
                "assign_collaborator_roles": is_manager,
                "create_application": is_manager,
                "delete_application": is_manager,
                "view_usage": is_manager,
                "manage_webhooks": is_manager,
            },
        }
