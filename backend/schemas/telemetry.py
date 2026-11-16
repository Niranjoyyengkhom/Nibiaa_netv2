from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.connectivity_profile import ConnectionType


class TelemetryResponse(BaseModel):
    id: int
    device_id: str
    data_originator: str | None = None
    application_id: int | None = None

    # When the device took the measurement
    timestamp: datetime

    # When NibiaaNet received it
    received_at: datetime

    provider: str | None

    # NTN (satellite) or TN (terrestrial); None for sample data
    connection_type: ConnectionType | None

    # Decode schema activation that produced telemetry
    decode_activation_id: int | None

    # Decoder version that produced telemetry
    decode_schema_id: int | None = None
    decoder_name: str | None = None
    decoder_version: int | str | None = None

    # Original bytes as received, hex; None for sample data
    raw_payload_hex: str | None

    # Decoded values, e.g. {"temperature": 25.4, "humidity": 62}
    telemetry: dict = Field(
        examples=[{"temperature": 25.4, "humidity": 62}]
    )
