from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.device_configuration import (
    DeviceConfigurationResponse,
    DeviceConfigurationUpdate,
    DeviceConfigurationUpdateResponse,
)
from app.services.device_control_service import DeviceControlService


router = APIRouter(
    prefix="/devices",
    tags=["Device Configuration"]
)

# Configuration is read and changed through the control service,
# because the pending commands are part of the answer
device_control_service = DeviceControlService()


@router.get(
    "/{device_id}/configuration",
    response_model=DeviceConfigurationResponse
)
def get_configuration(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return device_control_service.get_configuration(
        db,
        device_id,
        current_user
    )


@router.put(
    "/{device_id}/configuration",
    response_model=DeviceConfigurationUpdateResponse
)
def update_configuration(
    device_id: str,
    data: DeviceConfigurationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Updates the DESIRED configuration and queues PENDING commands.
    The confirmed configuration only changes after the device acknowledges.
    """
    return device_control_service.update_configuration(
        db,
        device_id,
        data,
        current_user
    )
