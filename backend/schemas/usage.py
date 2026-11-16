from datetime import datetime

from pydantic import BaseModel, Field


class UsageResponse(BaseModel):
    """
    Activity counts read from the existing tables.
    This is NOT billing: there are no prices, credits or invoices.
    """

    # None = all tenants (admin without a tenant filter)
    tenant_id: int | None

    # Counting window for messages. None = no limit on that side.
    period_start: datetime | None
    period_end: datetime | None

    # Current totals, not limited by the period
    devices: int
    applications: int

    # Messages inside the period
    uplink_messages: int = Field(
        description="Telemetry records received from devices"
    )
    downlink_commands: int = Field(
        description="Commands created for devices"
    )
    downlink_commands_acknowledged: int = Field(
        description="Of those, commands the device acknowledged"
    )

    uplink_messages_by_provider: dict[str, int] = Field(
        description="Uplink messages per provider code; 'unknown' when not recorded"
    )
