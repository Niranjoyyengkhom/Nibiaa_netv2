from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.device_configuration import utc_now
from app.security.encrypted_types import EncryptedString


class MqttBrokerConfig(Base):
    """
    User/Tenant configured MQTT Broker settings.
    Stores connection credentials (host, port, auth, topic prefix, TLS, etc.)
    Passwords and sensitive strings are encrypted at rest with EncryptedString.
    """
    __tablename__ = "mqtt_broker_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="Default MQTT Broker")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    host: Mapped[str] = mapped_column(String, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=1883)
    client_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
    password: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
    topic_prefix: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="nibiaanet/tenants/{tenant_id}/devices/{device_id}/telemetry"
    )
    qos: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    use_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

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
