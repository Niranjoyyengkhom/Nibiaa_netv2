from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.billing_database import BillingBase
from app.security.encrypted_types import (
    EncryptedBoolean,
    EncryptedDateTime,
    EncryptedFloat,
    EncryptedJSON,
    EncryptedSearchableString,
    EncryptedString,
)


def utc_now():
    return datetime.now(timezone.utc)


class NetworkProviderConfig(BillingBase):
    """
    Stores dynamic network provider API configurations (e.g. Monogoto, 1NCE, EMnify, Twilio, Generic REST).
    Stored in the dedicated 'billing' PostgreSQL database with all credentials and endpoints encrypted.
    Supports dynamic percentage markup over SIM provider billed wholesale costs (no fixed amount).
    """
    __tablename__ = "network_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    name: Mapped[str] = mapped_column(EncryptedString, nullable=False)

    provider_code: Mapped[str] = mapped_column(
        EncryptedSearchableString,
        unique=True,
        index=True,
        nullable=False
    )

    provider_type: Mapped[str] = mapped_column(
        EncryptedSearchableString,
        nullable=False,
        default="monogoto",
        index=True
    )

    base_url: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    auth_type: Mapped[str] = mapped_column(EncryptedString, nullable=False, default="bearer_token")

    api_user: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)

    # Dynamic % Pricing (Billed by SIM provider + Admin Markup %)
    markup_percentage: Mapped[float] = mapped_column(EncryptedFloat, nullable=False, default=20.0)
    cost_per_mb: Mapped[float] = mapped_column(EncryptedFloat, nullable=False, default=0.03)
    cost_per_sim: Mapped[float] = mapped_column(EncryptedFloat, nullable=False, default=1.00)
    cost_per_sms: Mapped[float] = mapped_column(EncryptedFloat, nullable=False, default=0.01)

    is_enabled: Mapped[bool] = mapped_column(EncryptedBoolean, nullable=False, default=True)
    is_sandbox: Mapped[bool] = mapped_column(EncryptedBoolean, nullable=False, default=True)

    extra_settings: Mapped[Optional[dict]] = mapped_column(EncryptedJSON, nullable=True, default=dict)

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
