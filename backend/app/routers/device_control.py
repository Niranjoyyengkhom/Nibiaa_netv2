import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.device_command import (
    DeviceCommandAck,
    DeviceCommandCancel,
    DeviceCommandCreate,
    DeviceCommandDetailResponse,
    DeviceCommandResponse,
    DeviceCommandSimulate,
)
from app.services.device_control_service import DeviceControlService


router = APIRouter(
    prefix="/devices",
    tags=["Device Control"]
)

device_control_service = DeviceControlService()


# --------------------------------
# Commands
# --------------------------------

@router.post(
    "/{device_id}/commands",
    response_model=DeviceCommandDetailResponse
)
def create_command(
    device_id: str,
    data: DeviceCommandCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return device_control_service.create_command(
        db,
        device_id,
        data,
        current_user
    )


@router.get(
    "/{device_id}/commands",
    response_model=list[DeviceCommandResponse]
)
def get_commands(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return device_control_service.get_commands(
        db,
        device_id,
        current_user
    )


@router.get(
    "/{device_id}/commands/{command_id}",
    response_model=DeviceCommandDetailResponse
)
def get_command(
    device_id: str,
    command_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return device_control_service.get_command(
        db,
        device_id,
        command_id,
        current_user
    )


@router.post(
    "/{device_id}/commands/{command_id}/cancel",
    response_model=DeviceCommandDetailResponse
)
def cancel_command(
    device_id: str,
    command_id: int,
    data: DeviceCommandCancel,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Stops a command that has not reached the device yet.
    """
    return device_control_service.cancel_command(
        db,
        device_id,
        command_id,
        data,
        current_user
    )


# --------------------------------
# DEVELOPMENT / TESTING ONLY
#
# These endpoints simulate the ground station, satellite and
# device. In production these transitions will be reported by
# the ground-station integration, not called by users.
# --------------------------------

def check_simulation_allowed():
    env = os.getenv("ENVIRONMENT", "development").lower()
    allowed = os.getenv(
        "ENABLE_SIMULATION_ENDPOINTS",
        "true" if env in ("development", "test") else "false"
    ).lower()
    if allowed not in ("true", "1"):
        raise HTTPException(
            status_code=403,
            detail="Simulation endpoints are disabled in production"
        )


@router.post(
    "/{device_id}/commands/{command_id}/simulate",
    response_model=DeviceCommandDetailResponse,
    summary="[DEV/TEST ONLY] Simulate one store-and-forward hop"
)
def simulate_delivery(
    device_id: str,
    command_id: int,
    data: DeviceCommandSimulate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _sim_check: None = Depends(check_simulation_allowed)
):
    return device_control_service.simulate_delivery(
        db,
        device_id,
        command_id,
        data,
        current_user
    )


@router.post(
    "/{device_id}/commands/{command_id}/ack",
    response_model=DeviceCommandDetailResponse,
    summary="[DEV/TEST ONLY] Simulate a device acknowledgement"
)
def acknowledge_command(
    device_id: str,
    command_id: int,
    data: DeviceCommandAck,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _sim_check: None = Depends(check_simulation_allowed)
):
    return device_control_service.acknowledge_command(
        db,
        device_id,
        command_id,
        data,
        current_user
    )
