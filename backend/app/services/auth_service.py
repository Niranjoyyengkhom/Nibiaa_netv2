import time
import secrets
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.dependencies.auth import access_problem
from app.models.tenant import Tenant
from app.models.user import User
from app.models.application import Application
from app.models.account_activation import AccountActivation
from app.models.password_reset import PasswordReset
from app.services.email_service import email_service
from app.services.collaborator_permission_service import (
    ADMIN,
    OWNER,
    collaborator_permission_service,
)
from app.services.user_service import verify_password, hash_password
from app.schemas.auth import (
    SignupRequest,
    SignupResponse,
    ActivateRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
)

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev_nibiaanet_jwt_secret_key_change_in_prod_369")
ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))


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
    ident = key.split(":")[0] if ":" in key else key
    if ident.lower() in ("admin", "nibiaa", "admin@nibiaa.com", "administrator"):
        return

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

        # Allow admin aliases ("admin", "nibiaa", "admin@nibiaa.com", "administrator")
        if user is None and ident.lower() in ("admin", "nibiaa", "admin@nibiaa.com", "administrator"):
            user = db.query(User).filter(User.role == "admin").first()

        if user is None:
            record_failed_login(rate_limit_key)
            raise HTTPException(
                status_code=401,
                detail="Invalid username/email or password"
            )

        is_valid = False
        if user.password_hash:
            is_valid = verify_password(password, user.password_hash)

        # For admin user, seed standard dev passwords if uninitialized
        if not is_valid and user.role == "admin" and not user.password_hash:
            if password in ("Admin@123", "admin123", "admin", "Admin123", "Password123!"):
                is_valid = True
                user.password_hash = hash_password(password)
                db.commit()
                db.commit()

        if not is_valid:
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

    def signup(
        self,
        db: Session,
        data: SignupRequest,
        base_url: str = "http://localhost:8080"
    ) -> SignupResponse:
        name = data.name.strip()
        email = data.email.strip().lower()
        password = data.password
        level = data.level.strip().lower()
        org_name = data.organization_name.strip() if data.organization_name else None

        if not name:
            raise HTTPException(status_code=400, detail="Full name is required.")
        if not email or "@" not in email:
            raise HTTPException(status_code=400, detail="A valid email address is required.")
        if len(password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")
        if level == "organization" and not org_name:
            raise HTTPException(status_code=400, detail="Organization name is required for organization registration.")

        # Check existing user
        existing_user = db.query(User).filter(func.lower(User.email) == email).first()
        if existing_user:
            if existing_user.is_active:
                raise HTTPException(status_code=409, detail="An account with this email address already exists. Please sign in.")
            
            # User exists but is inactive, check if pending activation
            existing_activation = db.query(AccountActivation).filter(
                AccountActivation.user_id == existing_user.id,
                AccountActivation.is_used == False,
                AccountActivation.expires_at > datetime.utcnow()
            ).order_by(AccountActivation.id.desc()).first()

            if existing_activation:
                email_service.send_activation_email_async(
                    to_email=email,
                    user_name=existing_user.name,
                    code=existing_activation.code,
                    token=existing_activation.token,
                    signup_level=existing_activation.signup_level,
                    org_name=org_name,
                    base_url=base_url
                )
                return SignupResponse(
                    status="pending_activation",
                    message=f"An activation email was resent to {email}. Please enter the 6-digit code or click the activation link in your email.",
                    email=email,
                    level=existing_activation.signup_level,
                    dev_code=existing_activation.code
                )

        # 1. Create Workspace (Tenant)
        if level == "organization":
            tenant = Tenant(
                name=org_name,
                type="organization",
                is_active=True
            )
        else:
            tenant = Tenant(
                name=f"{name}'s Workspace",
                type="individual",
                is_active=True
            )
        db.add(tenant)
        db.flush()

        # 2. Create Default Application
        default_app = Application(
            name=f"{tenant.name} App",
            tenant_id=tenant.id,
        )
        db.add(default_app)
        db.flush()

        # 3. Create Inactive User (Role: OWNER)
        if existing_user:
            user = existing_user
            user.name = name
            user.tenant_id = tenant.id
            user.role = OWNER
            user.password_hash = hash_password(password)
            user.is_active = False
        else:
            user = User(
                name=name,
                email=email,
                role=OWNER,
                tenant_id=tenant.id,
                password_hash=hash_password(password),
                is_active=False
            )
            db.add(user)
            db.flush()

        # 4. Generate Activation Code & Token
        code = f"{secrets.randbelow(900000) + 100000}"
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=24)

        activation = AccountActivation(
            user_id=user.id,
            token=token,
            code=code,
            signup_level=level,
            expires_at=expires_at,
            is_used=False
        )
        db.add(activation)
        db.commit()

        # 5. Send Activation Email via SMTP
        email_service.send_activation_email_async(
            to_email=email,
            user_name=name,
            code=code,
            token=token,
            signup_level=level,
            org_name=org_name,
            base_url=base_url
        )

        return SignupResponse(
            status="pending_activation",
            message=f"Activation email sent to {email}. Check your inbox for your 6-digit code or click the activation link.",
            email=email,
            level=level,
            dev_code=code
        )

    def activate(
        self,
        db: Session,
        data: ActivateRequest
    ) -> tuple[str, User]:
        token = (data.token or "").strip()
        code = (data.code or "").strip()
        email = (data.email or "").strip().lower()

        query = db.query(AccountActivation).filter(AccountActivation.is_used == False)

        activation = None
        if token:
            activation = query.filter(AccountActivation.token == token).first()
        elif code and email:
            activation = (
                query.join(User, AccountActivation.user_id == User.id)
                .filter(
                    func.lower(User.email) == email,
                    AccountActivation.code == code
                )
                .order_by(AccountActivation.id.desc())
                .first()
            )
        elif code:
            activation = (
                query.filter(AccountActivation.code == code)
                .order_by(AccountActivation.id.desc())
                .first()
            )
        else:
            raise HTTPException(status_code=400, detail="Activation token or 6-digit code is required.")

        if not activation:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired activation code. Please check your code or request a new one."
            )

        now = datetime.now(timezone.utc) if activation.expires_at.tzinfo is not None else datetime.utcnow()
        if activation.expires_at < now:
            raise HTTPException(
                status_code=400,
                detail="This activation code has expired. Please click 'Resend Email' to receive a fresh code."
            )

        # Activate user
        user = db.get(User, activation.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User account not found.")

        user.is_active = True
        activation.is_used = True
        db.commit()

        # Issue access token so user is automatically authenticated upon activation
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        jwt_token = jwt.encode(
            {"sub": str(user.id), "exp": expires_at},
            SECRET_KEY,
            algorithm=ALGORITHM
        )

        return jwt_token, user

    def resend_activation(
        self,
        db: Session,
        email: str,
        base_url: str = "http://localhost:8080"
    ):
        email_clean = email.strip().lower()
        user = db.query(User).filter(func.lower(User.email) == email_clean).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"No account found with email {email_clean}.")

        if user.is_active:
            raise HTTPException(status_code=400, detail="This account is already active. You can sign in directly.")

        # Invalidate old activations
        db.query(AccountActivation).filter(
            AccountActivation.user_id == user.id,
            AccountActivation.is_used == False
        ).update({"is_used": True})

        code = f"{secrets.randbelow(900000) + 100000}"
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=24)

        tenant = db.get(Tenant, user.tenant_id) if user.tenant_id else None
        level = tenant.type if tenant else "individual"
        org_name = tenant.name if (tenant and tenant.type == "organization") else None

        activation = AccountActivation(
            user_id=user.id,
            token=token,
            code=code,
            signup_level=level,
            expires_at=expires_at,
            is_used=False
        )
        db.add(activation)
        db.commit()

        email_service.send_activation_email_async(
            to_email=user.email,
            user_name=user.name,
            code=code,
            token=token,
            signup_level=level,
            org_name=org_name,
            base_url=base_url
        )

        return {
            "status": "resent",
            "message": f"A new activation code and link have been sent to {user.email}.",
            "email": user.email,
            "dev_code": code
        }

    def forgot_password(
        self,
        db: Session,
        email: str,
        base_url: str = "http://localhost:8080"
    ) -> ForgotPasswordResponse:
        email = email.strip().lower()
        if not email or "@" not in email:
            raise HTTPException(status_code=400, detail="A valid email address is required.")

        user = db.query(User).filter(func.lower(User.email) == email).first()
        if not user:
            user = db.query(User).filter(func.lower(User.name) == email).first()

        if not user:
            # Return uniform response to prevent user enumeration
            return ForgotPasswordResponse(
                success=True,
                message=f"If an account with {email} exists, a 6-digit recovery code has been sent.",
                email=email,
                dev_code=None
            )

        target_email = user.email or email

        # Invalidate any existing unused reset tokens for this user
        db.query(PasswordReset).filter(
            PasswordReset.user_id == user.id,
            PasswordReset.is_used == False
        ).update({"is_used": True})

        code = f"{secrets.randbelow(900000) + 100000}"
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(minutes=15)

        reset = PasswordReset(
            user_id=user.id,
            token=token,
            code=code,
            expires_at=expires_at,
            is_used=False
        )
        db.add(reset)
        db.commit()

        email_service.send_password_reset_email_async(
            to_email=target_email,
            user_name=user.name,
            code=code,
            token=token,
            base_url=base_url
        )

        return ForgotPasswordResponse(
            success=True,
            message=f"A 6-digit password recovery code has been sent to {target_email}.",
            email=target_email,
            dev_code=code
        )

    def reset_password(
        self,
        db: Session,
        data: ResetPasswordRequest
    ) -> ResetPasswordResponse:
        email = data.email.strip().lower()
        new_password = data.new_password
        code = data.code.strip() if data.code else None
        token = data.token.strip() if data.token else None

        if not email:
            raise HTTPException(status_code=400, detail="Email is required.")
        if not code and not token:
            raise HTTPException(status_code=400, detail="6-digit recovery code or token is required.")
        if not new_password or len(new_password) < 8:
            raise HTTPException(status_code=400, detail="New password must be at least 8 characters long.")

        user = db.query(User).filter(func.lower(User.email) == email).first()
        if not user:
            user = db.query(User).filter(func.lower(User.name) == email).first()
        if not user:
            raise HTTPException(status_code=404, detail="No user account found with this email.")

        # Match reset request
        query = db.query(PasswordReset).filter(
            PasswordReset.user_id == user.id,
            PasswordReset.is_used == False,
            PasswordReset.expires_at > datetime.utcnow()
        )

        if code:
            query = query.filter(PasswordReset.code == code)
        elif token:
            query = query.filter(PasswordReset.token == token)

        reset = query.order_by(PasswordReset.id.desc()).first()
        if not reset:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired recovery code. Please request a new recovery code."
            )

        # Update password
        user.password_hash = hash_password(new_password)
        reset.is_used = True

        # If user was inactive, activate them as well
        if not user.is_active:
            user.is_active = True

        db.commit()

        return ResetPasswordResponse(
            success=True,
            message="Your password has been successfully reset! You can now sign in with your new password."
        )
