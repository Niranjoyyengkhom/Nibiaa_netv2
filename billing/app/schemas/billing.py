from datetime import date, datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# -------------------------------------------------------------
# Billing Plan Schemas
# -------------------------------------------------------------

class BillingPlanBase(BaseModel):
    name: str = Field(..., max_length=100, example="Dynamic Cellular IoT")
    code: str = Field(..., max_length=50, example="dynamic-sim-usage")
    description: Optional[str] = Field(None, example="100% Usage-based. Direct wholesale pricing billed by SIM provider + admin markup. No fixed monthly fee.")
    # Dynamic % Pricing model (no fixed amount)
    pricing_model: str = Field("cost_plus_percentage", example="cost_plus_percentage")
    markup_percentage: float = Field(20.0, ge=0.0, le=500.0, example=20.0)
    monthly_price: float = Field(0.0, ge=0, example=0.0)
    annual_price: float = Field(0.0, ge=0, example=0.0)
    currency: str = Field("USD", min_length=3, max_length=3, example="USD")
    included_devices: int = Field(0, ge=0, example=0)
    included_data_mb: float = Field(0.0, ge=0, example=0.0)
    overage_rate_per_mb: float = Field(0.036, ge=0, example=0.036)
    extra_device_price: float = Field(1.20, ge=0, example=1.20)
    features: Optional[Dict[str, Any]] = Field(default_factory=dict)
    is_active: bool = True


class BillingPlanCreate(BillingPlanBase):
    pass


class BillingPlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    pricing_model: Optional[str] = None
    markup_percentage: Optional[float] = None
    monthly_price: Optional[float] = None
    annual_price: Optional[float] = None
    currency: Optional[str] = None
    included_devices: Optional[int] = None
    included_data_mb: Optional[float] = None
    overage_rate_per_mb: Optional[float] = None
    extra_device_price: Optional[float] = None
    features: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class BillingPlanResponse(BillingPlanBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# -------------------------------------------------------------
# Tenant Subscription Schemas
# -------------------------------------------------------------

class TenantSubscriptionCreate(BaseModel):
    tenant_id: Optional[int] = None
    plan_id: int
    billing_interval: str = Field("monthly", pattern="^(monthly|annually)$")
    auto_renew: bool = True


class TenantSubscriptionUpdate(BaseModel):
    plan_id: Optional[int] = None
    billing_interval: Optional[str] = None
    auto_renew: Optional[bool] = None
    cancel_at_period_end: Optional[bool] = None
    status: Optional[str] = None


class TenantSubscriptionResponse(BaseModel):
    id: int
    tenant_id: int
    plan_id: int
    status: str
    billing_interval: str
    current_period_start: datetime
    current_period_end: datetime
    auto_renew: bool
    cancel_at_period_end: bool
    odoo_partner_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    plan: Optional[BillingPlanResponse] = None

    class Config:
        from_attributes = True


# -------------------------------------------------------------
# Invoice Schemas
# -------------------------------------------------------------

class InvoiceLineItem(BaseModel):
    name: str = Field(..., example="Starter Cellular IoT - Monthly Subscription")
    quantity: float = Field(1.0, ge=0.01)
    unit_price: float = Field(..., ge=0)
    total: float = Field(..., ge=0)
    type: str = Field("subscription", example="subscription | overage | device_fee | topup")
    details: Optional[Dict[str, Any]] = None


class InvoiceGenerateRequest(BaseModel):
    tenant_id: Optional[int] = None
    billing_interval: Optional[str] = "monthly"
    include_overages: bool = True
    post_to_odoo: bool = True
    notes: Optional[str] = None


class InvoiceResponse(BaseModel):
    id: int
    invoice_number: str
    tenant_id: int
    subscription_id: Optional[int] = None
    period_start: datetime
    period_end: datetime
    due_date: datetime
    amount_subtotal: float
    amount_tax: float
    amount_total: float
    currency: str
    status: str
    odoo_invoice_id: Optional[int] = None
    odoo_move_name: Optional[str] = None
    odoo_payment_state: Optional[str] = None
    line_items: Optional[List[InvoiceLineItem]] = None
    notes: Optional[str] = None
    paid_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InvoicePayRequest(BaseModel):
    payment_method: str = Field("odoo_reconcile", example="odoo_reconcile | credit_card | wire | mock")
    notes: Optional[str] = None


# -------------------------------------------------------------
# Usage & Metering Schemas
# -------------------------------------------------------------

class SimUsageBreakdown(BaseModel):
    iccid: str
    device_id: Optional[str] = None
    label: Optional[str] = None
    status: str
    data_used_mb: float
    quota_remaining_mb: float
    quota_total_mb: float


class UsageSummaryResponse(BaseModel):
    tenant_id: int
    subscription_status: str
    plan_name: str
    pricing_model: str = "cost_plus_percentage"
    markup_percentage: float = 20.0
    period_start: datetime
    period_end: datetime
    total_active_sims: int
    included_devices: int
    billable_extra_devices: int
    total_data_used_mb: float
    included_data_mb: float
    billable_overage_mb: float
    provider_billed_cost: float = 0.0
    markup_amount: float = 0.0
    estimated_overage_charge: float
    estimated_total_next_invoice: float
    currency: str
    sim_details: List[SimUsageBreakdown] = []


class AdminMarkupUpdateRequest(BaseModel):
    markup_percentage: float = Field(..., ge=0.0, le=500.0, example=25.0)
    provider_code: Optional[str] = Field(None, example="1nce or all")


# -------------------------------------------------------------
# Integration Config & Diagnostics Schemas
# -------------------------------------------------------------

class IntegrationConfigUpdate(BaseModel):
    base_url: str = Field(..., example="https://api.1nce.com/management-api")
    api_user: Optional[str] = Field(None, example="user@client.com or client_id")
    api_key: Optional[str] = Field(None, example="api_secret or password")
    db_name: Optional[str] = Field(None, example="odoo_database")
    is_enabled: bool = True
    extra_settings: Optional[Dict[str, Any]] = None


class IntegrationConfigResponse(BaseModel):
    provider: str
    base_url: str
    api_user: Optional[str] = None
    has_api_key: bool
    db_name: Optional[str] = None
    is_enabled: bool
    extra_settings: Optional[Dict[str, Any]] = None
    updated_at: Optional[datetime] = None


class ConnectionTestResult(BaseModel):
    provider: str
    success: bool
    mode: str = "live"
    message: str
    latency_ms: Optional[float] = None
    details: Optional[Dict[str, Any]] = None
