from datetime import datetime, timezone
from typing import Optional, Any, List
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class AttributeDefinition(Base):
    """
    Attribute definition metadata catalog for ABAC & dynamic profiling.
    Target entity types: 'user', 'role', 'resource', 'tenant', 'environment'.
    Data types: 'string', 'number', 'boolean', 'json', 'enum', 'list'.
    """
    __tablename__ = "iam_attribute_definitions"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="user",
        index=True
    )

    data_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="string"
    )

    allowed_values: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True
    )

    validation_regex: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True
    )

    default_value: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    is_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    is_system: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True
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

    values: Mapped[List["AttributeValue"]] = relationship(
        "AttributeValue",
        back_populates="definition",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "entity_type", "key", name="uq_iam_attr_def_tenant_entity_key"),
    )


class AttributeValue(Base):
    """
    Stores attribute values assigned to entities (users, devices, roles, etc.).
    Uses typed columns for optimal performance, indexing, and validation.
    """
    __tablename__ = "iam_attribute_values"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    attribute_def_id: Mapped[int] = mapped_column(
        ForeignKey("iam_attribute_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True
    )

    entity_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True
    )

    value_string: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    value_number: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )

    value_boolean: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True
    )

    value_json: Mapped[Optional[Any]] = mapped_column(
        JSON,
        nullable=True
    )

    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True
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

    definition: Mapped["AttributeDefinition"] = relationship(
        "AttributeDefinition",
        back_populates="values",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("attribute_def_id", "entity_type", "entity_id", name="uq_iam_attr_val_entity"),
    )

    @property
    def value(self) -> Any:
        if self.value_string is not None:
            return self.value_string
        if self.value_number is not None:
            return self.value_number
        if self.value_boolean is not None:
            return self.value_boolean
        if self.value_json is not None:
            return self.value_json
        return None
