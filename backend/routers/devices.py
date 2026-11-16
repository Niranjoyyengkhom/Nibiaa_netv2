from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.network_types import NETWORK_TYPES
from app.schemas.device import (
    DeviceCreate,
    DeviceResponse,
    DeviceUpdate,
    NetworkTypeResponse,
)
from app.services.device_service import DeviceService


router = APIRouter(
    prefix="/devices",
    tags=["Devices"]
)

device_service = DeviceService()


@router.get(
    "/",
    response_model=list[DeviceResponse],
    summary="List devices",
    description=(
        "Admins see every device. Owners see their organization's devices. "
        "Collaborators need the Manage Devices function."
    )
)
def get_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return [
        device_service.device_response(device)
        for device in device_service.get_devices(db, current_user)
    ]


# Declared before /{device_id}
@router.get(
    "/network-types",
    response_model=list[NetworkTypeResponse],
    summary="Network types a device can be registered with",
    description=(
        "NTN, TN, LoRa, BLE, ... and the identifiers / keys each needs. "
        "The console builds its register form from this list."
    )
)
def get_network_types(
    current_user: User = Depends(get_current_user)
):
    return NETWORK_TYPES


@router.get(
    "/{device_id}",
    response_model=DeviceResponse,
    summary="Get one device",
    description=(
        "Returns 404 for a device of another tenant, "
        "so its existence is not revealed."
    )
)
def get_device(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return device_service.device_response(
        device_service.get_device_for_user(
            db,
            device_id,
            current_user
        )
    )


@router.post(
    "/",
    response_model=DeviceResponse,
    summary="Register a device",
    description="Collaborators need the Create Devices function."
)
def create_device(
    data: DeviceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return device_service.device_response(
        device_service.create_device(
            db,
            data,
            current_user
        )
    )

@router.put(
    "/{device_id}",
    response_model=DeviceResponse,
    summary="Update a device",
    description="Collaborators need the Manage Devices function."
)
def update_device(
    device_id: str,
    data: DeviceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return device_service.device_response(
        device_service.update_device(
            db,
            device_id,
            data,
            current_user
        )
    )

@router.delete(
    "/{device_id}",
    summary="Delete a device",
    description="Collaborators need the Delete Devices function."
)
def delete_device(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return device_service.delete_device(
        db,
        device_id,
        current_user
    )