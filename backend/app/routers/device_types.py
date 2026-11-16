from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.device_type import (
    DeviceTypeCreate,
    DeviceTypeUpdate,
    DeviceTypeResponse,
    DeviceTypeDecoderCreate,
    DeviceTypeDecoderResponse,
)
from app.services.device_type_service import DeviceTypeService

router = APIRouter(tags=["Device Types & Decoders"])
device_type_service = DeviceTypeService()


@router.get(
    "/applications/{application_id}/device-types",
    response_model=List[DeviceTypeResponse],
    summary="List device types for an application"
)
def list_application_device_types(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return device_type_service.list_device_types(db, application_id, current_user)


@router.post(
    "/applications/{application_id}/device-types",
    response_model=DeviceTypeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a device type for an application"
)
def create_application_device_type(
    application_id: int,
    data: DeviceTypeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return device_type_service.create_device_type(db, application_id, data, current_user)


@router.get(
    "/device-types/{device_type_id}",
    response_model=DeviceTypeResponse,
    summary="Get a specific device type"
)
def get_device_type(
    device_type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return device_type_service.get_device_type(db, device_type_id, current_user)


@router.put(
    "/device-types/{device_type_id}",
    response_model=DeviceTypeResponse,
    summary="Update a device type"
)
def update_device_type(
    device_type_id: int,
    data: DeviceTypeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return device_type_service.update_device_type(db, device_type_id, data, current_user)


@router.delete(
    "/device-types/{device_type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a device type"
)
def delete_device_type(
    device_type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device_type_service.delete_device_type(db, device_type_id, current_user)


@router.post(
    "/device-types/{device_type_id}/decoders",
    response_model=DeviceTypeDecoderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a decoder to a device type"
)
def assign_decoder_to_device_type(
    device_type_id: int,
    data: DeviceTypeDecoderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return device_type_service.assign_decoder(db, device_type_id, data, current_user)


@router.delete(
    "/device-types/{device_type_id}/decoders/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an assigned decoder from a device type"
)
def remove_decoder_from_device_type(
    device_type_id: int,
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device_type_service.remove_decoder(db, device_type_id, assignment_id, current_user)
