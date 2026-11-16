from typing import Optional

from sqlalchemy import ForeignKey, JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.security.encrypted_types import EncryptedJSON


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    device_id: Mapped[str] = mapped_column(
        String,
        unique=True,
        nullable=False,
        index=True
    )

    name: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    device_type: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    device_type_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("device_types.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    tenant_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True
    )

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Identifiers / keys of its network type (app/network_types.py),
    # e.g. {"dev_eui": ..., "app_eui": ..., "app_key": ...} for LoRa
    credentials: Mapped[Optional[dict]] = mapped_column(
        EncryptedJSON,
        nullable=True
    )

    application = relationship("Application", back_populates="devices")
    device_type_rel = relationship("DeviceType", back_populates="devices")
