from datetime import datetime
from enum import StrEnum
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.device_configuration import utc_now


class Webhook(Base):
    """
    An HTTP endpoint of a tenant that receives its telemetry (push).

    filters limits what is sent; a missing or empty list means "all":
    {"device_ids": [...], "connection_types": ["NTN"], "providers": [...]}
    """

    __tablename__ = "webhooks"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    tenant_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True
    )

    name: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    url: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    # Signs every request body (X-NibiaaNet-Signature)
    secret: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True
    )

    filters: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict
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


class WebhookDeliveryStatus(StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"

    # Failed, another attempt is scheduled at next_attempt_at
    RETRYING = "RETRYING"

    # Every attempt failed. Listed as an alert (GET /webhooks/alerts)
    UNDELIVERABLE = "UNDELIVERABLE"


class WebhookDelivery(Base):
    """
    One telemetry event to send to one webhook, with its attempts.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    webhook_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("webhooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    telemetry_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("telemetry.id", ondelete="SET NULL"),
        nullable=True
    )

    # The exact JSON body, so a redelivery sends the same event
    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False
    )

    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=WebhookDeliveryStatus.PENDING
    )

    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )

    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    last_status_code: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )

    last_error: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )

    __table_args__ = (
        # The retry worker looks for due deliveries
        Index("ix_webhook_deliveries_status_next_attempt", "status", "next_attempt_at"),
    )
