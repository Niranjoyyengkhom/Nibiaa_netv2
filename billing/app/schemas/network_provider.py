from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class OnceSimResponse(BaseModel):
    id: Optional[int] = None
    provider: str = "1nce"
    iccid: str = Field(..., example="8988280666000000001")
    imei: Optional[str] = Field(None, example="356938035643801")
    imsi: Optional[str] = Field(None, example="901405111111111")
    msisdn: Optional[str] = Field(None, example="423661111111")
    ip_address: Optional[str] = Field(None, example="10.0.0.15")
    label: Optional[str] = Field(None, example="Field Sensor Alpha")
    status: str = Field("Active", example="Active | Suspended | Cancelled | Inactive")
    imei_lock: bool = False
    quota_total_mb: Optional[float] = 500.0
    quota_remaining_mb: Optional[float] = 500.0
    quota_used_mb: Optional[float] = 0.0
    sms_total: Optional[int] = 250
    sms_remaining: Optional[int] = 250
    tenant_id: Optional[int] = None
    device_id: Optional[str] = None
    activation_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    last_sync_at: Optional[datetime] = None
    last_connectivity_check: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class OnceQuotaResponse(BaseModel):
    iccid: str
    volume_total_mb: float = Field(..., example=500.0)
    volume_used_mb: float = Field(..., example=120.5)
    volume_remaining_mb: float = Field(..., example=379.5)
    expiry_date: Optional[str] = Field(None, example="2034-01-01T00:00:00Z")
    peak_throughput: Optional[int] = 1000000
    threshold_percentage: Optional[int] = 80
    provider_raw: Optional[Dict[str, Any]] = None


class OnceSmsQuotaResponse(BaseModel):
    iccid: str
    sms_total: int = Field(..., example=250)
    sms_remaining: int = Field(..., example=210)
    sms_used: int = Field(..., example=40)
    expiry_date: Optional[str] = None


class OnceUsageDataPoint(BaseModel):
    timestamp: str
    data_volume_rx_bytes: int = 0
    data_volume_tx_bytes: int = 0
    data_volume_total_bytes: int = 0
    sms_mo_count: int = 0
    sms_mt_count: int = 0


class OnceUsageResponse(BaseModel):
    iccid: str
    start_dt: Optional[str] = None
    end_dt: Optional[str] = None
    total_bytes: int
    total_mb: float
    sessions_count: int
    data_points: List[OnceUsageDataPoint] = []


class OnceConnectivityResponse(BaseModel):
    iccid: str
    status: str = Field("Attached", example="Attached | Detached | Idle")
    radio_access_technology: Optional[str] = Field("NB-IoT", example="NB-IoT | LTE-M | 4G | 2G")
    cell_id: Optional[str] = Field(None, example="3456789")
    mcc: Optional[str] = Field(None, example="208")
    mnc: Optional[str] = Field(None, example="01")
    ip_address: Optional[str] = Field(None, example="10.12.34.56")
    last_connection_date: Optional[str] = None
    roaming_network: Optional[str] = None


class OnceStatusUpdateRequest(BaseModel):
    status: str = Field(..., pattern="^(Active|Suspended)$", example="Suspended")
    reason: Optional[str] = Field(None, example="Customer past due or SIM stolen")


class OnceTopupRequest(BaseModel):
    volume_mb: float = Field(500.0, ge=50.0, example=500.0)
    create_odoo_invoice: bool = Field(True, description="Create an Odoo invoice for this top-up")


class OnceSmsSendRequest(BaseModel):
    payload: str = Field(..., max_length=160, example="CONFIG:INTERVAL=600")
    source_address: Optional[str] = Field("NibiaaNet", max_length=11)
    source_address_type: Optional[str] = Field("alpha", pattern="^(alpha|numeric)$")


class OnceSimAssignRequest(BaseModel):
    tenant_id: Optional[int] = None
    device_id: Optional[str] = None
    label: Optional[str] = None
    imei: Optional[str] = None


# -----------------------------------------------------------------------------
# Dynamic Network Provider Schemas (Monogoto, 1NCE, Generic)
# -----------------------------------------------------------------------------

class DriverCatalogItem(BaseModel):
    driver_type: str
    display_name: str
    vendor: str
    description: str
    default_base_url: str
    auth_type: str
    user_label: str
    secret_label: str
    documentation_url: str
    capabilities: List[str] = Field(default_factory=list)
    supports_sandbox: bool = True


class NetworkProviderCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, example="Monogoto Global Cellular")
    provider_code: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-z0-9_-]+$", example="monogoto")
    provider_type: str = Field("generic_rest", pattern=r"^[a-z0-9_-]+$", example="monogoto")
    base_url: str = Field(..., example="https://api.monogoto.io")
    auth_type: str = Field("bearer_token", pattern=r"^(bearer_token|oauth2|api_key|basic_auth)$", example="bearer_token")
    api_user: Optional[str] = Field(None, example="developer@company.com")
    api_key: Optional[str] = Field(None, example="SecureMonogotoPasswordOrSecret")
    # Dynamic % Pricing (Billed by SIM Provider + Admin Markup %)
    markup_percentage: float = Field(20.0, ge=0.0, le=500.0, example=20.0)
    cost_per_mb: float = Field(0.03, ge=0.0, example=0.03)
    cost_per_sim: float = Field(1.00, ge=0.0, example=1.00)
    cost_per_sms: float = Field(0.01, ge=0.0, example=0.01)
    is_enabled: bool = True
    is_sandbox: bool = True
    extra_settings: Optional[Dict[str, Any]] = Field(default_factory=dict)


class NetworkProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    base_url: Optional[str] = None
    auth_type: Optional[str] = Field(None, pattern=r"^(bearer_token|oauth2|api_key|basic_auth)$")
    api_user: Optional[str] = None
    api_key: Optional[str] = None
    markup_percentage: Optional[float] = Field(None, ge=0.0, le=500.0)
    cost_per_mb: Optional[float] = Field(None, ge=0.0)
    cost_per_sim: Optional[float] = Field(None, ge=0.0)
    cost_per_sms: Optional[float] = Field(None, ge=0.0)
    is_enabled: Optional[bool] = None
    is_sandbox: Optional[bool] = None
    extra_settings: Optional[Dict[str, Any]] = None


class NetworkProviderResponse(BaseModel):
    id: int
    name: str
    provider_code: str
    provider_type: str
    base_url: str
    auth_type: str
    api_user: Optional[str] = None
    has_api_key: bool = False
    markup_percentage: float = 20.0
    cost_per_mb: float = 0.03
    cost_per_sim: float = 1.00
    cost_per_sms: float = 0.01
    effective_customer_mb_rate: Optional[float] = None
    effective_customer_sim_rate: Optional[float] = None
    effective_customer_sms_rate: Optional[float] = None
    is_enabled: bool = True
    is_sandbox: bool = True
    extra_settings: Optional[Dict[str, Any]] = None
    capabilities: List[str] = Field(default_factory=list)
    sim_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProviderTestResult(BaseModel):
    provider_code: str
    provider_name: str
    success: bool
    status_code: Optional[int] = None
    latency_ms: Optional[float] = None
    message: str
    details: Optional[Dict[str, Any]] = None


class CellularSimResponse(OnceSimResponse):
    pass
