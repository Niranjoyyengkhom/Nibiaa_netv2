from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.security.encrypted_types import (
    EncryptedBoolean,
    EncryptedDateTime,
    EncryptedJSON,
    EncryptedSearchableString,
    EncryptedString,
)


def utc_now():
    return datetime.now(timezone.utc)


class IntegrationConfig(Base):
    __tablename__ = "integration_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(EncryptedSearchableString, unique=True, index=True, nullable=False)
    base_url: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    api_user: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
    db_name: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
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
