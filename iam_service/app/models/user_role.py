from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class UserRole(Base):
    """
    Junction table assigning Roles to Users, supporting multi-role assignment
    and optional tenant scoping.
    """
    __tablename__ = "iam_user_roles"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    role_id: Mapped[int] = mapped_column(
        ForeignKey("iam_roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True
    )

    assigned_by: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "tenant_id", name="uq_iam_user_role_tenant"),
    )
