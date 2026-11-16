from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class ABACPolicy(Base):
    """
    Attribute-Based Access Control (ABAC) Policy rule definition.
    Evaluates subject attributes, resource attributes, action, and environment context.
    """
    __tablename__ = "iam_abac_policies"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    name: Mapped[str] = mapped_column(
        String(150),
        unique=True,
        index=True,
        nullable=False
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True
    )

    effect: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="ALLOW"  # "ALLOW" or "DENY"
    )

    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )

    target_actions: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list  # e.g., ["devices:*", "telemetry:read"]
    )

    target_resource_types: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list  # e.g., ["device", "application", "*"]
    )

    subject_conditions: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        default=dict  # e.g., {"department": {"$eq": "operations"}, "clearance_level": {"$gte": 2}}
    )

    resource_conditions: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        default=dict  # e.g., {"region": {"$in": ["US-WEST", "GLOBAL"]}}
    )

    environment_conditions: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        default=dict  # e.g., {"network_type": {"$eq": "satellite"}, "ip_allowlist": {"$contains": "context.ip"}}
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False
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
