from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.device_configuration import utc_now


class CollaboratorRole(Base):
    """
    A named set of collaborator functions, created by an admin
    ("Create Collaborator Roles"), e.g. "Field Technician" =
    manage_devices + create_devices.

    Owners assign a role to a collaborator ("Manage Role Assignment").
    While a role is assigned, the collaborator's functions are the
    role's functions, so changing the role changes every collaborator
    that has it.
    """

    __tablename__ = "collaborator_roles"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    name: Mapped[str] = mapped_column(
        String,
        nullable=False,
        unique=True
    )

    description: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    manage_devices: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    create_devices: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    delete_devices: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    manage_application: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    read_application_traffic: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    create_decoder: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    manage_decoder: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )
