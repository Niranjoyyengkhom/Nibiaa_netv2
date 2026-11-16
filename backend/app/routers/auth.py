import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.auth import (
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    SignupRequest,
    SignupResponse,
    ActivateRequest,
    ActivateResponse,
    ResendActivationRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
)
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

auth_service = AuthService()
audit_service = AuditService()

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev_nibiaanet_jwt_secret_key_change_in_prod_369")
ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
)


@router.post("/login", response_model=LoginResponse)
def login(
    data: LoginRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    client_ip = request.client.host if request.client else "unknown"
    ident = (data.email or data.identifier or data.name or "").strip()
    if not ident:
        raise HTTPException(status_code=400, detail="Email or username is required")

    try:
        user = auth_service.login(
            db,
            ident,
            data.password,
            client_ip=client_ip
        )
    except Exception as exc:
        audit_service.log_event(
            db=db,
            action="USER_LOGIN_FAILED",
            category="SECURITY",
            user_name=ident,
            resource_type="auth",
            resource_id=ident,
            details={"attempted_identifier": ident, "reason": str(getattr(exc, "detail", "Invalid credentials"))},
            ip_address=client_ip,
            status="FAILED"
        )
        raise exc

    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    token = jwt.encode(
        {
            "sub": str(user.id),
            "exp": expires_at
        },
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    audit_service.log_event(
        db=db,
        action="USER_LOGIN",
        category="AUTH",
        user=user,
        resource_type="session",
        resource_id=str(user.id),
        details={"username": user.name, "role": user.role},
        ip_address=client_ip,
        status="SUCCESS"
    )

    return LoginResponse(
        access_token=token
    )


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="The signed-in user, with organization, functions and capabilities"
)
def me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return auth_service.me(
        db,
        current_user
    )


@router.post("/signup", response_model=SignupResponse)
def signup(
    data: SignupRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    origin = request.headers.get("origin") or "http://localhost:8080"
    res = auth_service.signup(db, data, base_url=origin)
    client_ip = request.client.host if request.client else "unknown"
    audit_service.log_event(
        db=db,
        action="USER_SIGNUP",
        category="AUTH",
        user_name=data.name,
        resource_type="user",
        resource_id=data.email,
        details={"email": data.email, "level": data.level, "org": data.organization_name},
        ip_address=client_ip,
        status="SUCCESS"
    )
    return res


@router.post("/activate", response_model=ActivateResponse)
def activate(
    data: ActivateRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    token, user = auth_service.activate(db, data)
    client_ip = request.client.host if request.client else "unknown"
    audit_service.log_event(
        db=db,
        action="USER_ACTIVATED",
        category="AUTH",
        user=user,
        resource_type="user",
        resource_id=str(user.id),
        details={"username": user.name, "email": user.email},
        ip_address=client_ip,
        status="SUCCESS"
    )
    return ActivateResponse(
        success=True,
        message=f"Account for {user.name} activated successfully!",
        access_token=token,
        user_name=user.name
    )


@router.post("/resend-activation")
def resend_activation(
    data: ResendActivationRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    origin = request.headers.get("origin") or "http://localhost:8080"
    return auth_service.resend_activation(db, data.email, base_url=origin)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    origin = request.headers.get("origin") or "http://localhost:8080"
    client_ip = request.client.host if request.client else "unknown"
    res = auth_service.forgot_password(db, data.email, base_url=origin)
    audit_service.log_event(
        db=db,
        action="FORGOT_PASSWORD_REQUEST",
        category="AUTH",
        user_name=data.email,
        resource_type="user",
        resource_id=data.email,
        details={"email": data.email},
        ip_address=client_ip,
        status="SUCCESS"
    )
    return res


@router.post("/reset-password", response_model=ResetPasswordResponse)
def reset_password(
    data: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    client_ip = request.client.host if request.client else "unknown"
    res = auth_service.reset_password(db, data)
    audit_service.log_event(
        db=db,
        action="PASSWORD_RESET_SUCCESS",
        category="AUTH",
        user_name=data.email,
        resource_type="user",
        resource_id=data.email,
        details={"email": data.email},
        ip_address=client_ip,
        status="SUCCESS"
    )
    return res
