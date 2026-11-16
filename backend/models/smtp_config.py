from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.device_configuration import utc_now
from app.security.encrypted_types import EncryptedString


class SmtpConfig(Base):
    """
    SMTP server configuration for outbound email dispatching.
    Passwords are encrypted at rest with EncryptedString.
    """
    __tablename__ = "smtp_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    host: Mapped[str] = mapped_column(String, nullable=False, default="localhost")
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    password: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
    from_email: Mapped[str] = mapped_column(String, nullable=False, default="noreply@nibiaa.com")
    from_name: Mapped[str] = mapped_column(String, nullable=False, default="NibiaaNet IoT")
    use_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    use_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

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
