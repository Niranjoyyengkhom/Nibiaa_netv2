from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from collections import defaultdict

from app.database import get_db
from app.models.permission import Permission
from app.schemas.permission import (
    PermissionCreate,
    PermissionResponse,
    PermissionCategoryGroup,
)
from app.dependencies.auth import get_current_user, require_admin
from app.models.user import User

router = APIRouter(prefix="/permissions", tags=["Permissions Catalog"])


@router.get("/", response_model=List[PermissionResponse])
def get_all_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Permission).order_by(Permission.category.asc(), Permission.code.asc()).all()


@router.get("/categories", response_model=List[PermissionCategoryGroup])
def get_permissions_grouped_by_category(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    all_perms = db.query(Permission).order_by(Permission.category.asc(), Permission.code.asc()).all()
    grouped = defaultdict(list)
    for p in all_perms:
        grouped[p.category].append(p)

    return [
        PermissionCategoryGroup(
            category=cat,
            count=len(plist),
            permissions=plist,
        )
        for cat, plist in grouped.items()
    ]


@router.get("/{permission_id}", response_model=PermissionResponse)
def get_permission(
    permission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    perm = db.query(Permission).filter(Permission.id == permission_id).first()
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")
    return perm


@router.post("/", response_model=PermissionResponse)
def create_custom_permission(
    data: PermissionCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    existing = db.query(Permission).filter(Permission.code == data.code.strip()).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Permission code '{data.code}' already exists")

    new_perm = Permission(
        code=data.code.strip(),
        name=data.name.strip(),
        description=data.description,
        category=data.category.strip().lower(),
    )
    db.add(new_perm)
    db.commit()
    db.refresh(new_perm)
    return new_perm
