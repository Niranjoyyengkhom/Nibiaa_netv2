from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

from app.schemas.connectivity_profile import ConnectionType


class WebhookFilters(BaseModel):
    # Empty list = no restriction
    device_ids: list[str] = []
    connection_types: list[ConnectionType] = []
    providers: list[str] = []


class WebhookCreate(BaseModel):
    name: str = Field(min_length=1)
    url: HttpUrl
    enabled: bool = True
    filters: WebhookFilters = WebhookFilters()

    # Admins only; tenant admins always get their own tenant
    tenant_id: int | None = None


class WebhookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    url: HttpUrl | None = None
    enabled: bool | None = None
    filters: WebhookFilters | None = None


class WebhookResponse(BaseModel):
    id: int
    tenant_id: int
    name: str
    url: str
    enabled: bool
    filters: WebhookFilters
    created_at: datetime
    updated_at: datetime


class WebhookCreatedResponse(WebhookResponse):
    # Shown once. Verify X-NibiaaNet-Signature with it:
    # "sha256=" + HMAC-SHA256(secret, raw request body), hex
    secret: str


class WebhookDeliveryResponse(BaseModel):
    id: int
    webhook_id: int
    telemetry_id: int | None
    status: str
    attempts: int
    next_attempt_at: datetime | None
    last_attempt_at: datetime | None
    last_status_code: int | None
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime
    payload: dict
