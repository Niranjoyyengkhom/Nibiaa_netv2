from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.device_configuration import utc_now


class Telemetry(Base):
    """
    One telemetry message received from a device (uplink).

    data holds the decoded values, for example
    {"temperature": 25.4, "humidity": 62}.

    Rows are written by the ingestion pipeline
    (app/services/ingestion_service.py) after an uplink is decoded and
    routed, and by app/seed_telemetry.py for sample data.
    """

    __tablename__ = "telemetry"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    # References devices.id (the internal integer ID)
    device_pk: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False
    )

    # When the device took the measurement
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )

    # When NibiaaNet received it. Later than timestamp, because of
    # store-and-forward through the satellite and ground station
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )

    # Code of the satellite provider that carried the message
    # (see app/providers.py); None if unknown
    provider: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    # NTN (satellite) or TN (terrestrial); None for seeded rows
    connection_type: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    data: Mapped[dict] = mapped_column(
        JSON,
        nullable=False
    )

    # Original bytes as received; None for seeded rows
    raw_payload: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary,
        nullable=True
    )

    # Which decode schema activation produced data
    decode_activation_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("decode_schema_activations.id", ondelete="SET NULL"),
        nullable=True
    )

    # Decoder version that produced data
    decode_schema_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("decode_schemas.id", ondelete="SET NULL"),
        nullable=True
    )

    __table_args__ = (
        # Serves both "latest" and time-range queries of one device
        Index("ix_telemetry_device_pk_timestamp", "device_pk", "timestamp"),
    )
