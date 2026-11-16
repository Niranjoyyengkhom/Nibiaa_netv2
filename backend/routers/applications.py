from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.application import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationUpdate,
)
from app.services.application_service import ApplicationService


router = APIRouter(
    prefix="/applications",
    tags=["Applications"]
)

application_service = ApplicationService()


@router.get(
    "/",
    response_model=list[ApplicationResponse],
    summary="List applications",
    description=(
        "Admins: every organization, or filter by tenant_id. Owners: their organization. "
        "Collaborators: their organization, with Manage Application, "
        "Read Application Traffic, Create Devices or Manage Devices."
    )
)
def get_applications(
    tenant_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return application_service.get_applications(
        db,
        current_user,
        tenant_id=tenant_id
    )


@router.post(
    "/",
    response_model=ApplicationResponse,
    summary="Create an application (admin, owner)"
)
def create_application(
    data: ApplicationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return application_service.create_application(
        db,
        data,
        current_user
    )


@router.put(
    "/{application_id}",
    response_model=ApplicationResponse,
    summary="Update an application (name, decoder)",
    description="Collaborators need the Manage Application function."
)
def update_application(
    application_id: int,
    data: ApplicationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return application_service.update_application(
        db,
        application_id,
        data,
        current_user
    )


@router.delete(
    "/{application_id}",
    status_code=204,
    summary="Delete an application without devices (admin, owner)"
)
def delete_application(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    application_service.delete_application(
        db,
        application_id,
        current_user
    )
