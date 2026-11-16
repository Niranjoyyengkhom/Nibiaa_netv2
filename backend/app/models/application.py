from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    name: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    tenant_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True
    )

    decode_schema_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "decode_schemas.id",
            ondelete="RESTRICT"
        ),
        nullable=True,
        index=True
    )

    device_types = relationship(
        "DeviceType",
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="DeviceType.id"
    )

    devices = relationship(
        "Device",
        back_populates="application",
        cascade="all, delete-orphan"
    )

    decoders = relationship(
        "ApplicationDecoder",
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationDecoder.priority.desc()"
    )
