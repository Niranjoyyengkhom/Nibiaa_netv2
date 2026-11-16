from datetime import datetime
from enum import StrEnum
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.device_configuration import utc_now


class DecodedMessageStatus(StrEnum):
    # Decoded, routed to a device and stored as telemetry
    ROUTED = "ROUTED"

    # No provider_sources row matches the source address / client id
    UNKNOWN_PROVIDER = "UNKNOWN_PROVIDER"

    # The provider has no active decode schema
    NO_ACTIVE_SCHEMA = "NO_ACTIVE_SCHEMA"

    # The payload does not fit the active schema
    DECODE_FAILED = "DECODE_FAILED"

    # Decoded, but the identifier matches no registered device
    UNKNOWN_DEVICE = "UNKNOWN_DEVICE"


# Everything except ROUTED can be reprocessed, e.g. after a schema
# correction is activated or the device is registered
REPROCESSABLE_STATUSES = [
    status
    for status in DecodedMessageStatus
    if status != DecodedMessageStatus.ROUTED
]


class DecodedMessage(Base):
    """
    Temporary staging record of one uplink, from receipt to routing.

    Every received payload lands here first, with the original bytes,
    whatever happens next. ROUTED rows have been copied to telemetry
    and are purged after a short retention; failed rows are kept longer
    so they can be reprocessed (see IngestionService.purge).
    """

    __tablename__ = "decoded_messages"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    status: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    error: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    # --------------------------------
    # As received (queue message)
    # --------------------------------

    # udp / tcp / mqtt
    transport: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    source_address: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    client_id: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    # Device identifier given by the transport (e.g. MQTT topic),
    # used instead of a decoded "device_id" field when present
    device_identifier: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    raw_payload: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False
    )

    # IncomingMessage.id given by the adapter
    message_ref: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    remote_port: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )

    # Optional decoder-match attributes given by the adapter
    # (IncomingMessage.source); protocol defaults to the transport type
    protocol_id: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    message_type: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    payload_version: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    # Server side receipt timestamp
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )

    # --------------------------------
    # Decoding
    # --------------------------------

    provider: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    # NTN (satellite) or TN (terrestrial); from the provider
    connection_type: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    decode_activation_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("decode_schema_activations.id", ondelete="SET NULL"),
        nullable=True
    )

    # Decoder version used, and how it was chosen: "application" or "match"
    decode_schema_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("decode_schemas.id", ondelete="SET NULL"),
        nullable=True
    )

    decoder_selection: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    # Canonical field name -> value, e.g. {"device_id": "DEVICE001", "temperature": 25.4}
    decoded: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True
    )

    # Canonical field name -> unit, e.g. {"temperature": "°C"}
    units: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True
    )

    # --------------------------------
    # Routing
    # --------------------------------

    device_pk: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("devices.id", ondelete="SET NULL"),
        nullable=True
    )

    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )

    telemetry_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("telemetry.id", ondelete="SET NULL"),
        nullable=True
    )

    # PUBLISHED / FAILED / DISABLED (no broker configured)
    mqtt_status: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )

    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    __table_args__ = (
        # Reprocessing and purging filter on status and age
        Index("ix_decoded_messages_status_received_at", "status", "received_at"),
    )
