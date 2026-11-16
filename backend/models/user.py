from typing import Optional

from sqlalchemy import Boolean, String, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    name: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    email: Mapped[Optional[str]] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=True
    )

    role: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )

    password_hash: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    # False = access revoked ("Revoke Collaborator"): the user can no
    # longer sign in and existing tokens are refused
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true")
    )
