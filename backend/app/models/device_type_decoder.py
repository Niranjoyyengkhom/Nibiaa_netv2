from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import ForeignKey, Integer, String, Boolean, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class DeviceTypeDecoder(Base):
    __tablename__ = "device_type_decoders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    device_type_id: Mapped[int] = mapped_column(
        ForeignKey("device_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    decode_schema_id: Mapped[int] = mapped_column(
        ForeignKey("decode_schemas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    # Affinity: 'json', 'hex', 'binary', 'base64', or None for Any
    payload_format: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("TRUE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP")
    )

    device_type = relationship("DeviceType", back_populates="decoders")
    decode_schema = relationship("DecodeSchema")
