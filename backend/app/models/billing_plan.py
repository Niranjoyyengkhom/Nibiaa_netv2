from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.billing_database import BillingBase
from app.security.encrypted_types import (
    EncryptedBoolean,
    EncryptedDateTime,
    EncryptedFloat,
    EncryptedInteger,
    EncryptedJSON,
    EncryptedSearchableString,
    EncryptedString,
)


def utc_now():
    return datetime.now(timezone.utc)


class BillingPlan(BillingBase):
    """
    Subscription plan tier stored in the dedicated 'billing' PostgreSQL database.
    Supports dynamic % pricing according to usage billed by SIM providers (no fixed amount).
    """
    __tablename__ = "billing_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    name: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    code: Mapped[str] = mapped_column(EncryptedSearchableString, unique=True, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)

    # Dynamic pricing model: 'cost_plus_percentage' (no fixed amount)
    pricing_model: Mapped[str] = mapped_column(EncryptedString, nullable=False, default="cost_plus_percentage")
    markup_percentage: Mapped[float] = mapped_column(EncryptedFloat, nullable=False, default=20.0)

    # Base pricing ($0.00 for pure % pricing model)
    monthly_price: Mapped[float] = mapped_column(EncryptedFloat, nullable=False, default=0.0)
    annual_price: Mapped[float] = mapped_column(EncryptedFloat, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(EncryptedString, nullable=False, default="USD")

    included_devices: Mapped[int] = mapped_column(EncryptedInteger, nullable=False, default=1)
    included_data_mb: Mapped[float] = mapped_column(EncryptedFloat, nullable=False, default=500.0)

    overage_rate_per_mb: Mapped[float] = mapped_column(EncryptedFloat, nullable=False, default=0.05)
    extra_device_price: Mapped[float] = mapped_column(EncryptedFloat, nullable=False, default=2.00)

    features: Mapped[Optional[dict]] = mapped_column(EncryptedJSON, nullable=True, default=dict)
    is_active: Mapped[bool] = mapped_column(EncryptedBoolean, nullable=False, default=True)

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

    subscriptions = relationship("TenantSubscription", back_populates="plan")
