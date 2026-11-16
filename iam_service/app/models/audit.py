from datetime import datetime, timezone
from typing import Optional, Any
from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class IAMAuditLog(Base):
    """
    Audit log record specifically capturing security events, permission changes,
    user revocations, attribute updates, and policy enforcement decisions.
    """
    __tablename__ = "iam_audit_logs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    actor_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True
    )

    actor_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True
    )

    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True  # e.g., USER_CREATED, ROLE_ASSIGNED, ATTRIBUTE_SET, ABAC_EVALUATED
    )

    target_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True  # user, role, attribute, policy, access
    )

    target_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True
    )

    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True
    )

    details: Mapped[Optional[Any]] = mapped_column(
        JSON,
        nullable=True
    )

    ip_address: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True
    )
