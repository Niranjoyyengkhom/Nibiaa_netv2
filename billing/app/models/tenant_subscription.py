from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.security.encrypted_types import (
    EncryptedBoolean,
    EncryptedDateTime,
    EncryptedInteger,
    EncryptedSearchableInteger,
    EncryptedSearchableString,
    EncryptedString,
)


def utc_now():
    return datetime.now(timezone.utc)


class TenantSubscription(Base):
    """
    Organization subscription linking a Tenant to a BillingPlan.
    Stored in the dedicated 'billing' PostgreSQL database with encrypted attributes.
    """
    __tablename__ = "tenant_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    tenant_id: Mapped[int] = mapped_column(
        EncryptedSearchableInteger,
        nullable=False,
        unique=True,
        index=True
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("billing_plans.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )

    status: Mapped[str] = mapped_column(EncryptedSearchableString, nullable=False, default="trialing")
    billing_interval: Mapped[str] = mapped_column(EncryptedString, nullable=False, default="monthly")

    current_period_start: Mapped[datetime] = mapped_column(
        EncryptedDateTime,
        nullable=False,
        default=utc_now
    )
    current_period_end: Mapped[datetime] = mapped_column(
        EncryptedDateTime,
        nullable=False
    )

    auto_renew: Mapped[bool] = mapped_column(EncryptedBoolean, nullable=False, default=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(EncryptedBoolean, nullable=False, default=False)

    odoo_partner_id: Mapped[Optional[int]] = mapped_column(EncryptedInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        EncryptedDateTime,
        nullable=False,
        default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        EncryptedDateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now
    )

    plan = relationship("BillingPlan", back_populates="subscriptions")
    invoices = relationship("InvoiceRecord", back_populates="subscription", cascade="all, delete-orphan")
