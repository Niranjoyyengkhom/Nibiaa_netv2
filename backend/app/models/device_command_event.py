from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.device_configuration import utc_now


class DeviceCommandEvent(Base):
    """
    Delivery history of a command.

    One row is added every time a command moves along the
    communication path, for example:

    SERVER         -> CREATED
    GROUND_STATION -> QUEUED
    SATELLITE      -> QUEUED
    DEVICE         -> DELIVERED
    DEVICE         -> APPLIED        (acknowledgement starts)
    SATELLITE      -> ACK_RELAYED
    GROUND_STATION -> ACK_RELAYED
    SERVER         -> ACKNOWLEDGED   (confirmed configuration updated)
    """

    __tablename__ = "device_command_events"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    command_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("device_commands.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # SERVER, GROUND_STATION, SATELLITE or DEVICE
    location: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    # CREATED, QUEUED, DELIVERED, APPLIED, REJECTED, ACK_RELAYED,
    # ACKNOWLEDGED, FAILED, EXPIRED, CANCELLED
    event: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    # Command status after this event
    status: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    detail: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )
