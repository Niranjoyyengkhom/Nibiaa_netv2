from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.security.encrypted_types import (
    EncryptedBoolean,
    EncryptedDate,
    EncryptedDateTime,
    EncryptedFloat,
    EncryptedInteger,
    EncryptedSearchableInteger,
    EncryptedSearchableString,
    EncryptedString,
)


def utc_now():
    return datetime.now(timezone.utc)


class BillingUsageRecord(Base):
    __tablename__ = "billing_usage_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

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

    sim_iccid: Mapped[Optional[str]] = mapped_column(EncryptedSearchableString, index=True, nullable=True)
    device_id: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)

    usage_date: Mapped[date] = mapped_column(EncryptedDate, nullable=False)
    data_bytes: Mapped[int] = mapped_column(EncryptedInteger, nullable=False, default=0)
    data_mb: Mapped[float] = mapped_column(EncryptedFloat, nullable=False, default=0.0)
    sms_count: Mapped[int] = mapped_column(EncryptedInteger, nullable=False, default=0)

    source: Mapped[str] = mapped_column(EncryptedString, nullable=False, default="1nce_api")
    is_billed: Mapped[bool] = mapped_column(EncryptedBoolean, nullable=False, default=False)
    invoice_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        EncryptedDateTime,
        nullable=False,
        default=utc_now
    )

    subscription = relationship("TenantSubscription")
    invoice = relationship("InvoiceRecord")
