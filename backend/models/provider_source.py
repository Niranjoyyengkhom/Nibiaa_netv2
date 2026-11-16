from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.device_configuration import utc_now


class ProviderSource(Base):
    """
    Tells the decoder which provider an uplink came from
    ("provider resolution").

    transport = udp  -> identity is the source IP of the provider's
                        ground segment (satellite uplinks)
    transport = tcp / mqtt -> identity is the client / session id
    """

    __tablename__ = "provider_sources"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    # Provider code (see app/providers.py)
    provider: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    transport: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    identity: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )

    __table_args__ = (
        UniqueConstraint("transport", "identity", name="uq_provider_sources_transport_identity"),
    )
