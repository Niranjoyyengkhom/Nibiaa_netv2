from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.security.encrypted_types import (
    EncryptedBoolean,
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


class NetworkSimCard(Base):
    """
    Cellular IoT SIM card entity (e.g. 1NCE NB-IoT/LTE-M, Monogoto, etc.).
    Stored in dedicated 'billing' PostgreSQL database with encrypted identifiers and telemetry quotas.
    """
    __tablename__ = "network_sim_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(EncryptedSearchableString, nullable=False, default="1nce", index=True)

    iccid: Mapped[str] = mapped_column(EncryptedSearchableString, unique=True, index=True, nullable=False)
    imei: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
    imsi: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
    msisdn: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
    label: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)

    status: Mapped[str] = mapped_column(EncryptedSearchableString, nullable=False, default="Active", index=True)
    imei_lock: Mapped[bool] = mapped_column(EncryptedBoolean, nullable=False, default=False)

    quota_total_mb: Mapped[Optional[float]] = mapped_column(EncryptedFloat, nullable=True, default=500.0)
    quota_remaining_mb: Mapped[Optional[float]] = mapped_column(EncryptedFloat, nullable=True, default=500.0)
    quota_used_mb: Mapped[Optional[float]] = mapped_column(EncryptedFloat, nullable=True, default=0.0)

    sms_total: Mapped[Optional[int]] = mapped_column(EncryptedInteger, nullable=True, default=250)
    sms_remaining: Mapped[Optional[int]] = mapped_column(EncryptedInteger, nullable=True, default=250)

    tenant_id: Mapped[Optional[int]] = mapped_column(
        EncryptedSearchableInteger,
        nullable=True,
        index=True
    )
    device_id: Mapped[Optional[str]] = mapped_column(
        EncryptedSearchableString,
        nullable=True,
        index=True
    )

    activation_date: Mapped[Optional[datetime]] = mapped_column(EncryptedDateTime, nullable=True)
    expiry_date: Mapped[Optional[datetime]] = mapped_column(EncryptedDateTime, nullable=True)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(EncryptedDateTime, nullable=True)

    last_connectivity_check: Mapped[Optional[dict]] = mapped_column(EncryptedJSON, nullable=True)

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
