from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.schemas.tenant import TenantCreate, TenantResponse, TenantUpdate
from app.services.tenant_service import TenantService


router = APIRouter(
    prefix="/tenants",
    tags=["Tenants"]
)

tenant_service = TenantService()


@router.get(
    "/",
    response_model=list[TenantResponse],
    summary="List organizations",
    description="Admins: every organization. Others: their own organization."
)
def get_tenants(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return tenant_service.get_tenants(
        db,
        current_user
    )


@router.post(
    "/",
    response_model=TenantResponse,
    summary="Create an organization (admin)"
)
def create_tenant(
    data: TenantCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return tenant_service.create_tenant(
        db,
        data,
        current_user
    )


@router.put(
    "/{tenant_id}",
    response_model=TenantResponse,
    summary="Rename an organization or change its type (admin)"
)
def update_tenant(
    tenant_id: int,
    data: TenantUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return tenant_service.update_tenant(
        db,
        tenant_id,
        data,
        current_user
    )


@router.post(
    "/{tenant_id}/revoke",
    response_model=TenantResponse,
    summary="Revoke an organization's access (admin)",
    description="Its users can no longer sign in. Nothing is deleted."
)
def revoke_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return tenant_service.set_active(
        db,
        tenant_id,
        False,
        current_user
    )


@router.post(
    "/{tenant_id}/restore",
    response_model=TenantResponse,
    summary="Restore an organization's access (admin)"
)
def restore_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return tenant_service.set_active(
        db,
        tenant_id,
        True,
        current_user
    )


@router.delete(
    "/{tenant_id}",
    status_code=204,
    summary="Delete an empty organization (admin)",
    description="Refused while it still has users, applications, devices, decoders or webhooks."
)
def delete_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    tenant_service.delete_tenant(
        db,
        tenant_id,
        current_user
    )
