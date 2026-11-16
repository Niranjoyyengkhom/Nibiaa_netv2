from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.billing_database import BillingBase
from app.security.encrypted_types import (
    EncryptedDateTime,
    EncryptedFloat,
    EncryptedInteger,
    EncryptedJSON,
    EncryptedSearchableInteger,
    EncryptedSearchableString,
    EncryptedString,
)


def utc_now():
    return datetime.now(timezone.utc)


class InvoiceRecord(BillingBase):
    """
    Local record of customer invoices synchronized with Odoo ERP (account.move).
    Stored in dedicated 'billing' PostgreSQL database with encrypted financials and metadata.
    """
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    invoice_number: Mapped[str] = mapped_column(EncryptedSearchableString, unique=True, index=True, nullable=False)

    tenant_id: Mapped[int] = mapped_column(
        EncryptedSearchableInteger,
        nullable=False,
        index=True
    )
    subscription_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tenant_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Billing period (encrypted timestamps)
    period_start: Mapped[datetime] = mapped_column(EncryptedDateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(EncryptedDateTime, nullable=False)
    due_date: Mapped[datetime] = mapped_column(EncryptedDateTime, nullable=False)

    # Financials (encrypted floats)
    amount_subtotal: Mapped[float] = mapped_column(EncryptedFloat, nullable=False, default=0.0)
    amount_tax: Mapped[float] = mapped_column(EncryptedFloat, nullable=False, default=0.0)
    amount_total: Mapped[float] = mapped_column(EncryptedFloat, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(EncryptedString, nullable=False, default="USD")

    # Local Status: 'draft', 'posted', 'paid', 'past_due', 'cancelled', 'void'
    status: Mapped[str] = mapped_column(EncryptedSearchableString, nullable=False, default="draft")

    # Odoo Synchronization Fields (encrypted)
    odoo_invoice_id: Mapped[Optional[int]] = mapped_column(EncryptedInteger, nullable=True)
    odoo_move_name: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
    odoo_payment_state: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True, default="not_paid")

    # Line items (encrypted JSON)
    line_items: Mapped[Optional[list]] = mapped_column(EncryptedJSON, nullable=True, default=list)

    notes: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(EncryptedDateTime, nullable=True)

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

    subscription = relationship("TenantSubscription", back_populates="invoices")
