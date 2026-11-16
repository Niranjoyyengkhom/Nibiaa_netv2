from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.device_configuration import utc_now


class DecodeSchema(Base):
    """
    One version of an application's binary payload layout.

    An application points to a DecodeSchema through
    Application.decode_schema_id.

    A schema version is never edited after creation. If the
    decoder needs to change, create a new version.

    tenant_id None = platform decoder (created by an admin, usable by
    every organization). Otherwise it belongs to that organization.
    Versions are numbered per (tenant_id, name).
    """

    __tablename__ = "decode_schemas"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True
    )

    name: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    # "javascript": code holds function decode(input) (DecoderDefinition)
    # "fields": the declarative field list below (earlier decoders)
    kind: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="fields",
        server_default=text("'fields'")
    )

    code: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    byte_order: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="big"
    )

    fields: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list
    )

    # DecoderMatch: when a device's application has no decoder, the live
    # decoder whose criteria all fit the uplink is used (most specific
    # wins). A decoder without any criterion is never picked by matching.
    match_provider_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    match_protocol_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    match_device_type_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    match_message_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    match_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    description: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    created_by: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )

    __table_args__ = (
        # Platform decoders (tenant_id NULL) count as tenant 0
        Index(
            "uq_decode_schemas_tenant_name_version",
            text("COALESCE(tenant_id, 0)"),
            "name",
            "version",
            unique=True
        ),
    )


class DecodeSchemaActivation(Base):
    """
    Keeps track of which version of a decoder is the live one.

    Activating a version deactivates the other versions with the same
    (tenant_id, name) and moves every application using one of them to
    the activated version. Activating an older version is a rollback.
    Telemetry records the activation that decoded it.
    """

    __tablename__ = "decode_schema_activations"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    schema_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "decode_schemas.id",
            ondelete="RESTRICT"
        ),
        nullable=False
    )

    note: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    activated_by: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )

    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )

    deactivated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    __table_args__ = (
        Index(
            "uq_decode_schema_activations_one_active",
            "schema_id",
            unique=True,
            postgresql_where=text(
                "deactivated_at IS NULL"
            )
        ),
    )