from typing import Optional

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


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

    tenant_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True
    )

    application_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True
    )

    # Identifiers / keys of its network type (app/network_types.py),
    # e.g. {"dev_eui": ..., "app_eui": ..., "app_key": ...} for LoRa
    credentials: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True
    )
