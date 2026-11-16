from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.connectivity_profile import (
    ConnectivityProfileCreate,
    ConnectivityProfileResponse,
    ConnectivityProfileUpdate,
    ProviderSourceCreate,
    ProviderSourceResponse,
)
from app.services.connectivity_profile_service import ConnectivityProfileService


router = APIRouter(
    prefix="/connectivity-profiles",
    tags=["Connectivity Profiles"]
)

connectivity_profile_service = ConnectivityProfileService()


@router.get(
    "/",
    response_model=list[ConnectivityProfileResponse],
    summary="List connectivity profiles (satellite / terrestrial providers)",
    description="Any signed-in user. NTN = satellite, TN = terrestrial."
)
def get_profiles(
    db: Session = Depends(get_db),
    # Any logged-in user; providers are platform information
    current_user: User = Depends(get_current_user)
):
    return connectivity_profile_service.get_profiles(db)


@router.post(
    "/",
    response_model=ConnectivityProfileResponse,
    summary="Add a connectivity profile (admin)",
    description="Onboards a new provider without a code change."
)
def create_profile(
    data: ConnectivityProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return connectivity_profile_service.create_profile(db, data, current_user)


# Declared before /{profile_id} routes with the same depth
@router.delete(
    "/sources/{source_id}",
    status_code=204,
    summary="Remove a provider source mapping (admin)"
)
def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    connectivity_profile_service.delete_source(db, source_id, current_user)


@router.get(
    "/{profile_id}",
    response_model=ConnectivityProfileResponse
)
def get_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return connectivity_profile_service.get_profile(db, profile_id)


@router.put(
    "/{profile_id}",
    response_model=ConnectivityProfileResponse,
    summary="Manage a connectivity profile (admin)",
    description="Everything except the code. Disable instead of deleting a used profile."
)
def update_profile(
    profile_id: int,
    data: ConnectivityProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return connectivity_profile_service.update_profile(db, profile_id, data, current_user)


@router.delete(
    "/{profile_id}",
    status_code=204,
    summary="Delete an unused connectivity profile (admin)",
    description="Refused while it has source mappings or telemetry."
)
def delete_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    connectivity_profile_service.delete_profile(db, profile_id, current_user)


@router.get(
    "/{profile_id}/sources",
    response_model=list[ProviderSourceResponse],
    summary="Source mappings of a provider (admin)",
    description=(
        "How an uplink is matched to this provider: UDP / satellite "
        "source IP, or TCP / MQTT client id."
    )
)
def get_sources(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return connectivity_profile_service.get_sources(db, profile_id, current_user)


@router.post(
    "/{profile_id}/sources",
    response_model=ProviderSourceResponse,
    summary="Map a source IP / client id to this provider (admin)"
)
def create_source(
    profile_id: int,
    data: ProviderSourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return connectivity_profile_service.create_source(db, profile_id, data, current_user)
