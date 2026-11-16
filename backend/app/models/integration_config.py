from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.billing_database import BillingBase
from app.security.encrypted_types import (
    EncryptedBoolean,
    EncryptedDateTime,
    EncryptedJSON,
    EncryptedSearchableString,
    EncryptedString,
)


def utc_now():
    return datetime.now(timezone.utc)


class IntegrationConfig(BillingBase):
    """
    Stores external API configurations and credentials for integrations
    such as Odoo ERP and Network Providers (1NCE).
    Stored in dedicated 'billing' PostgreSQL database with all credentials and endpoints encrypted.
    """
    __tablename__ = "integration_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Provider identifier: '1nce', 'odoo'
    provider: Mapped[str] = mapped_column(EncryptedSearchableString, unique=True, index=True, nullable=False)

    # Endpoint URL (e.g. 'https://api.1nce.com/management-api' or 'http://localhost:8069')
    base_url: Mapped[str] = mapped_column(EncryptedString, nullable=False)

    # Username or Client ID (encrypted)
    api_user: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)

    # Password or API Key or Client Secret (Encrypted at rest)
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)

    # Database name (e.g., Odoo database name, encrypted)
    db_name: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)

    # Extra configuration parameters (encrypted JSON)
    extra_settings: Mapped[Optional[dict]] = mapped_column(EncryptedJSON, nullable=True, default=dict)

    is_enabled: Mapped[bool] = mapped_column(EncryptedBoolean, nullable=False, default=True)

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
