from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CollaboratorPermission(Base):
    """
    The functions an owner (or admin) gave one collaborator.

    role_id set  -> the collaborator has the functions of that
                    CollaboratorRole (the flags below are ignored)
    role_id None -> "custom": the flags below are the functions
    """

    __tablename__ = "collaborator_permissions"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False
    )

    role_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("collaborator_roles.id", ondelete="RESTRICT"),
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
