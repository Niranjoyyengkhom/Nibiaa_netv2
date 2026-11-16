from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.device_configuration import utc_now
from app.security.encrypted_types import EncryptedJSON


class CommandType(str, Enum):
    SET_WAKE_FREQUENCY = "SET_WAKE_FREQUENCY"
    SET_ENABLED = "SET_ENABLED"


class CommandStatus(str, Enum):
    """
    Store-and-forward delivery states.

    PENDING
      -> GROUND_STATION_QUEUED
      -> SATELLITE_QUEUED
      -> DEVICE_DELIVERED
      -> ACKNOWLEDGED

    Any non-final state can also move to FAILED or EXPIRED.
    A command can be CANCELLED until it reaches the device.
    """

    PENDING = "PENDING"
    GROUND_STATION_QUEUED = "GROUND_STATION_QUEUED"
    SATELLITE_QUEUED = "SATELLITE_QUEUED"
    DEVICE_DELIVERED = "DEVICE_DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


# A command in one of these states will never move again
FINAL_STATUSES = {
    CommandStatus.ACKNOWLEDGED,
    CommandStatus.FAILED,
    CommandStatus.EXPIRED,
    CommandStatus.CANCELLED,
}


class CommandLocation(str, Enum):
    SERVER = "SERVER"
    GROUND_STATION = "GROUND_STATION"
    SATELLITE = "SATELLITE"
    DEVICE = "DEVICE"


class DeviceCommand(Base):
    """
    A command waiting to be (or already) delivered to a device.

    Creating a command only means it is stored on the server (PENDING).
    It does NOT mean the device has received it.
    """

    __tablename__ = "device_commands"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    # References devices.id (the internal integer ID)
    device_pk: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Stored as plain strings (not a PostgreSQL ENUM)
    # so new types/states can be added without a migration
    command_type: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    payload: Mapped[dict] = mapped_column(
        EncryptedJSON,
        nullable=False
    )

    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        index=True,
        default=CommandStatus.PENDING.value
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now
    )

    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    # Set when the command reaches the device (DEVICE_DELIVERED).
    # Added to existing databases by app/migrations.py
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
