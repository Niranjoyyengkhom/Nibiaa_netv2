from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.device_configuration import utc_now


class ConnectivityProfile(Base):
    """
    One satellite / terrestrial connectivity provider (Skylo, Sateliot,
    cellular, ...). Admins add and manage these from the frontend
    (Settings -> Connectivity), so onboarding a new provider needs no
    code change.

    code is the stable identifier stored in telemetry.provider and
    provider_sources.provider. It cannot be changed after creation.
    """

    __tablename__ = "connectivity_profiles"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    code: Mapped[str] = mapped_column(
        String,
        nullable=False,
        unique=True
    )

    name: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    # NTN (non-terrestrial: satellite) or TN (terrestrial: cellular ...)
    connection_type: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    # planned = listed, not integrated yet; available = integrated
    integration_status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="planned"
    )

    # Disabled profiles stay listed (telemetry history keeps its code)
    # but their uplinks are refused by the pipeline
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true")
    )

    # How the provider's ground segment delivers uplinks:
    # udp / tcp / mqtt / satellite / https
    transport: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    # Larger uplinks are refused (DECODE_FAILED); None = no limit
    max_payload_bytes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )

    description: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
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
