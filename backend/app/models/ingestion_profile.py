from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Boolean, DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class IngestionProfile(Base):
    """
    Ingestion Profile for the Protocol Ingestion Microservice.
    Allows Admins to configure whether each Network Protocol uses Default
    Microservice values (UDP 5001, MQTT 1883, TCP 1001, Webhook 1002)
    or Admin-Provided Custom values (custom port, host, auth credentials, endpoint/topic).
    """
    __tablename__ = "ingestion_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Unique code for this profile (e.g. "udp_default", "mqtt_default", "hubble_webhook", "skylo_udp")
    code: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)

    # Human-readable name
    name: Mapped[str] = mapped_column(String, nullable=False)

    # Protocol: "udp", "mqtt", "tcp", "webhook"
    protocol: Mapped[str] = mapped_column(String, nullable=False)

    # Network Protocol / Provider code: "all", "hubble", "skylo", "kineis", "cellular", etc.
    network_profile_code: Mapped[str] = mapped_column(String, nullable=False, default="all")

    # Mode: True = Default Values, False = Admin-Provided Custom Values
    use_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Default port for this protocol (UDP=5001, MQTT=1883, TCP=1001, Webhook=1002)
    default_port: Mapped[int] = mapped_column(Integer, nullable=False)

    # Custom port provided by Admin (used when use_default is False)
    custom_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Host binding
    host: Mapped[str] = mapped_column(String, nullable=False, default="localhost")

    # Authentication type: "none", "basic_auth", "token", "user_password"
    auth_type: Mapped[str] = mapped_column(String, nullable=False, default="none")
    auth_username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    auth_password: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    auth_token: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Custom URL path or MQTT topic
    custom_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Active status
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    @property
    def effective_port(self) -> int:
        if self.use_default or not self.custom_port:
            return self.default_port
        return self.custom_port
