from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    IntrospectRequest,
    IntrospectResponse,
    UserMeResponse,
)
from app.services.auth_service import auth_service
from app.services.user_service import user_service
from app.dependencies.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["Authentication & Token Introspection"])


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    return auth_service.login(db, data.username, data.password)


@router.get("/me", response_model=UserMeResponse)
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_dict = user_service.user_to_dict(db, current_user)
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role,
        "tenant_id": current_user.tenant_id,
        "is_active": current_user.is_active,
        "roles": user_dict["assigned_roles"],
        "permissions": user_dict["permissions"],
        "attributes": user_dict["attributes"],
    }


@router.post("/introspect", response_model=IntrospectResponse)
def introspect_token(data: IntrospectRequest, db: Session = Depends(get_db)):
    return auth_service.introspect(db, data.token)
