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
)
from app.services.auth_service import AuthService


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

auth_service = AuthService()

SECRET_KEY = os.environ["JWT_SECRET_KEY"]
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

    user = auth_service.login(
        db,
        ident,
        data.password,
        client_ip=client_ip
    )

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
    return auth_service.signup(db, data, base_url=origin)


@router.post("/activate", response_model=ActivateResponse)
def activate(
    data: ActivateRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    token, user = auth_service.activate(db, data)
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
