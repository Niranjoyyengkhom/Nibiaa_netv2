from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.user import (
    UserCreate,
    UserUpdate,
    UserResponse
)
from app.services.user_service import UserService
from app.dependencies.auth import get_current_user


router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

user_service = UserService()


@router.get("/", response_model=list[UserResponse])
def get_users(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return user_service.get_users(
        db,
        current_user
    )


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return user_service.get_user(
        db,
        user_id,
        current_user
    )


@router.post("/", response_model=UserResponse)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return user_service.create_user(
        db,
        data,
        current_user
    )


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return user_service.update_user(
        db,
        user_id,
        data,
        current_user
    )


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return user_service.delete_user(
        db,
        user_id,
        current_user
    )


@router.post(
    "/{user_id}/revoke",
    response_model=UserResponse,
    summary="Revoke a user's access (Revoke Collaborator)",
    description=(
        "The user can no longer sign in and existing tokens stop working. "
        "Owners: collaborators of their own organization. Admins: anyone."
    )
)
def revoke_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return user_service.set_active(
        db,
        user_id,
        False,
        current_user
    )


@router.post(
    "/{user_id}/restore",
    response_model=UserResponse,
    summary="Restore a revoked user's access"
)
def restore_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return user_service.set_active(
        db,
        user_id,
        True,
        current_user
    )