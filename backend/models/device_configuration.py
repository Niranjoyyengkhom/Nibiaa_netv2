from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class DeviceConfiguration(Base):
    """
    Remote configuration of one device.

    desired_*   = what the server wants the device to use
    confirmed_* = what the device has acknowledged it is using

    The desired values change immediately when an admin updates
    the configuration. The confirmed values only change when the
    device acknowledges a command through the store-and-forward path.

    NULL means "not set yet" (desired) or "not confirmed yet" (confirmed).
    """

    __tablename__ = "device_configurations"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    # References devices.id (the internal integer ID),
    # not the string devices.device_id
    device_pk: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("devices.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True
    )

    # --------------------------------
    # Desired configuration
    # --------------------------------

    desired_enabled: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True
    )

    desired_wake_frequency_per_day: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )

    desired_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    # --------------------------------
    # Confirmed configuration
    # --------------------------------

    confirmed_enabled: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True
    )

    confirmed_wake_frequency_per_day: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )

    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    # --------------------------------
    # Timestamps
    # --------------------------------

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
