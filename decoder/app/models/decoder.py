import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base
from app.security.encrypted_types import EncryptedString, EncryptedJSON


class DecoderDefinition(Base):
    __tablename__ = "decoder_definitions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="active")
    active_version_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    versions = relationship("DecoderVersion", back_populates="decoder", cascade="all, delete-orphan")


class DecoderVersion(Base):
    __tablename__ = "decoder_versions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    decoder_id = Column(String(36), ForeignKey("decoder_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(String(50), nullable=False)
    code = Column(EncryptedString, nullable=False)
    matching = Column(EncryptedJSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    decoder = relationship("DecoderDefinition", back_populates="versions")
