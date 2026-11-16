import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime
from app.database import Base
from app.security.encrypted_types import EncryptedJSON


class DecodedMessageRecord(Base):
    __tablename__ = "decoded_messages_store"

    message_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    received_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    device_id = Column(String(100), nullable=True, index=True)
    transport = Column(String(50), nullable=False, default="http")
    status = Column(String(50), nullable=False, index=True)  # 'decoded' or 'failed'
    body = Column(EncryptedJSON, nullable=False, default=dict)
    tenant_id = Column(Integer, nullable=True, index=True)
    stored_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
