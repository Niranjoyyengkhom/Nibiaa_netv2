import base64
from typing import List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db as get_billing_db
from app.dependencies.auth import get_current_user, AuthUser
from app.schemas.billing import (
    BillingPlanCreate,
    BillingPlanResponse,
    BillingPlanUpdate,
    ConnectionTestResult,
    IntegrationConfigResponse,
    IntegrationConfigUpdate,
    InvoiceGenerateRequest,
    InvoicePayRequest,
    InvoiceResponse,
    TenantSubscriptionCreate,
    TenantSubscriptionResponse,
    TenantSubscriptionUpdate,
    UsageSummaryResponse,
    AdminMarkupUpdateRequest,
)
from app.services.billing_service import billing_service
from app.services.odoo_client import odoo_client
from app.services.once_client import once_client

router = APIRouter(
    prefix="/billing",
    tags=["Billing & Subscriptions"]
)


def require_admin(user: AuthUser):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Platform admin privileges required.")


def resolve_tenant_id(user: Any, requested_tenant_id: Optional[int] = None) -> int:
    is_admin = getattr(user, "role", "").lower() == "admin"
    if requested_tenant_id is not None:
        if is_admin:
            return requested_tenant_id
        if getattr(user, "tenant_id", None) == requested_tenant_id:
            return requested_tenant_id
        raise HTTPException(status_code=403, detail="Access denied to requested organization or workspace.")
    if getattr(user, "tenant_id", None) is not None:
        return user.tenant_id
    if is_admin:
        return 1
    return 1


# -----------------------------------------------------------------------------
# Plans
# -----------------------------------------------------------------------------

@router.get(
    "/plans",
    response_model=List[BillingPlanResponse],
    summary="List available billing plans",
    description="Returns active subscription tiers including included SIM allowances and data quotas."
)
def list_plans(
    all_plans: bool = Query(False, description="Admin only: include inactive plans"),
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    active_only = not (all_plans and current_user.role == "admin")
    return billing_service.list_plans(db, active_only=active_only)


@router.post(
    "/plans",
    response_model=BillingPlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a billing plan (Admin only)"
)
def create_plan(
    data: BillingPlanCreate,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    require_admin(current_user)
    return billing_service.create_plan(db, data)


@router.get(
    "/plans/{plan_id}",
    response_model=BillingPlanResponse,
    summary="Get plan details"
)
def get_plan(
    plan_id: int,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    plan = billing_service.get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found.")
    return plan


@router.put(
    "/plans/{plan_id}",
    response_model=BillingPlanResponse,
    summary="Update a billing plan (Admin only)"
)
def update_plan(
    plan_id: int,
    data: BillingPlanUpdate,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    require_admin(current_user)
    try:
        return billing_service.update_plan(db, plan_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/subscriptions/process-recurring-invoices",
    response_model=List[InvoiceResponse],
    summary="Process 30-day recurring auto-invoicing cycle",
    description="Auto-generates itemized invoices every 30 days from date of subscription for active subscriptions.",
)
async def process_recurring_invoices(
    force: bool = Query(False, description="Force generation for current cycle regardless of 30-day threshold"),
    tenant_id: Optional[int] = Query(None, description="Target specific tenant ID (admin only or current tenant)"),
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    target_tenant = tenant_id if current_user.role == "admin" else current_user.tenant_id
    if current_user.role != "admin":
        force = False
    return await billing_service.process_recurring_invoices(db, force_tenant_id=target_tenant, force=force)


# -----------------------------------------------------------------------------
# Subscriptions
# -----------------------------------------------------------------------------

@router.get(
    "/subscriptions/me",
    response_model=TenantSubscriptionResponse,
    summary="Get current organization's subscription"
)
def get_my_subscription(
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    if current_user.role == "admin":
        raise HTTPException(status_code=404, detail="Platform administrator has no individual organization subscription.")
    tenant_id = resolve_tenant_id(current_user)
    sub = billing_service.get_tenant_subscription(db, tenant_id)
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription found for your organization.")
    return sub


@router.get(
    "/subscriptions/tenant/{tenant_id}",
    response_model=TenantSubscriptionResponse,
    summary="Get tenant's subscription (Admin or Tenant Owner)"
)
def get_tenant_subscription(
    tenant_id: int,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    if current_user.role != "admin" and current_user.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Access denied.")
    sub = billing_service.get_tenant_subscription(db, tenant_id)
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription found.")
    return sub


@router.get(
    "/subscriptions",
    response_model=List[TenantSubscriptionResponse],
    summary="List subscriptions (Admin only)"
)
def list_subscriptions(
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    require_admin(current_user)
    return billing_service.list_subscriptions(db)


@router.post(
    "/subscriptions/subscribe",
    response_model=TenantSubscriptionResponse,
    summary="Subscribe organization to a plan",
    description="Subscribes or updates organization plan, synchronizing with Odoo ERP customer records."
)
async def subscribe(
    data: TenantSubscriptionCreate,
    tenant_id: Optional[int] = Query(None, description="Admin only: target tenant ID"),
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    target_tenant_id = resolve_tenant_id(current_user, tenant_id)
    try:
        return await billing_service.subscribe_tenant(
            db,
            tenant_id=target_tenant_id,
            plan_id=data.plan_id,
            interval=data.billing_interval,
            auto_renew=data.auto_renew,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/subscriptions/cancel",
    response_model=TenantSubscriptionResponse,
    summary="Cancel organization subscription"
)
def cancel_subscription(
    immediate: bool = Query(False, description="Cancel immediately without waiting for period end"),
    tenant_id: Optional[int] = Query(None, description="Admin only: target tenant ID"),
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    target_tenant_id = resolve_tenant_id(current_user, tenant_id)
    try:
        return billing_service.cancel_subscription(db, target_tenant_id, immediate=immediate)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# -----------------------------------------------------------------------------
# Usage & Metering Summary
# -----------------------------------------------------------------------------

@router.get(
    "/usage",
    response_model=UsageSummaryResponse,
    summary="Get billing usage & cellular data consumption",
    description="Calculates active 1NCE SIM cards, pooled cellular data volume, and estimated overage charges."
)
def get_usage_summary(
    tenant_id: Optional[int] = Query(None, description="Admin only: target tenant ID"),
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    if current_user.role == "admin" and tenant_id is None:
        return billing_service.get_system_usage_summary(db)
    target_tenant_id = resolve_tenant_id(current_user, tenant_id)
    return billing_service.get_tenant_usage_summary(db, target_tenant_id)


# -----------------------------------------------------------------------------
# Invoices & Odoo Synchronisation
# -----------------------------------------------------------------------------

@router.get(
    "/invoices",
    response_model=List[InvoiceResponse],
    summary="List invoices",
    description="Admins see all invoices; tenant users see their organization's invoices."
)
def list_invoices(
    tenant_id: Optional[int] = Query(None, description="Admin only: filter by tenant ID"),
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    if current_user.role == "admin":
        return billing_service.list_invoices(db, tenant_id=tenant_id)
    return billing_service.list_invoices(db, tenant_id=current_user.tenant_id)


@router.get(
    "/invoices/{invoice_id}",
    response_model=InvoiceResponse,
    summary="Get invoice details"
)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    inv = billing_service.get_invoice(db, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if current_user.role != "admin" and inv.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied.")
    return inv


@router.post(
    "/invoices/generate",
    response_model=InvoiceResponse,
    summary="Generate invoice for organization",
    description="Calculates current cycle usage, creates invoice in Odoo (account.move), and posts if requested."
)
async def generate_invoice(
    data: InvoiceGenerateRequest,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    target_tenant_id = resolve_tenant_id(current_user, data.tenant_id)
    try:
        return await billing_service.generate_invoice_for_tenant(
            db,
            tenant_id=target_tenant_id,
            billing_interval=data.billing_interval or "monthly",
            include_overages=data.include_overages,
            post_to_odoo=data.post_to_odoo,
            notes=data.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/invoices/{invoice_id}/sync-odoo",
    response_model=InvoiceResponse,
    summary="Sync invoice status with Odoo ERP",
    description="Polls Odoo ERP for updated payment state (not_paid, paid, reversed) and unlocks suspended SIMs if paid."
)
async def sync_odoo_invoice(
    invoice_id: int,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    inv = billing_service.get_invoice(db, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if current_user.role != "admin" and inv.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied.")

    return await billing_service.sync_invoice_with_odoo(db, invoice_id)


@router.post(
    "/invoices/{invoice_id}/pay",
    response_model=InvoiceResponse,
    summary="Record invoice payment & reactivate SIMs",
    description="Marks invoice as paid locally and in Odoo, automatically reactivating any suspended 1NCE SIMs."
)
async def pay_invoice(
    invoice_id: int,
    data: InvoicePayRequest,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    inv = billing_service.get_invoice(db, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if current_user.role != "admin" and inv.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied.")

    return await billing_service.pay_invoice(
        db,
        invoice_id=invoice_id,
        payment_method=data.payment_method,
        notes=data.notes,
    )


@router.get(
    "/invoices/{invoice_id}/pdf",
    summary="Download invoice PDF from Odoo",
    description="Renders or streams official invoice PDF report generated by Odoo ERP."
)
async def get_invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    inv = billing_service.get_invoice(db, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if current_user.role != "admin" and inv.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied.")

    odoo_id = inv.odoo_invoice_id or invoice_id
    try:
        pdf_b64 = await odoo_client.get_invoice_pdf_base64(odoo_id)
        pdf_bytes = base64.b64decode(pdf_b64)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename={inv.invoice_number}.pdf"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {e}")


# -----------------------------------------------------------------------------
# Integration Config & Diagnostics
# -----------------------------------------------------------------------------

@router.get(
    "/config/{provider}",
    response_model=IntegrationConfigResponse,
    summary="Get integration configuration status (Admin only)",
    description="Returns configuration for '1nce' or 'odoo' with API keys masked."
)
def get_config(
    provider: str,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    require_admin(current_user)
    cfg = billing_service.get_integration_config(db, provider)
    if not cfg:
        # Return default env-backed settings
        if provider == "1nce":
            return IntegrationConfigResponse(
                provider="1nce",
                base_url=once_client.base_url,
                api_user=once_client.client_id or None,
                has_api_key=bool(once_client.client_secret),
                is_enabled=True,
                extra_settings={"sandbox_mode": once_client.is_mock_mode},
            )
        elif provider == "odoo":
            return IntegrationConfigResponse(
                provider="odoo",
                base_url=odoo_client.url,
                api_user=odoo_client.username,
                has_api_key=bool(odoo_client.password),
                db_name=odoo_client.db,
                is_enabled=True,
                extra_settings={"sandbox_mode": odoo_client.is_mock_mode},
            )
        else:
            raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'.")

    return IntegrationConfigResponse(
        provider=cfg.provider,
        base_url=cfg.base_url,
        api_user=cfg.api_user,
        has_api_key=bool(cfg.api_key_encrypted),
        db_name=cfg.db_name,
        is_enabled=cfg.is_enabled,
        extra_settings=cfg.extra_settings,
        updated_at=cfg.updated_at,
    )


@router.put(
    "/config/{provider}",
    response_model=IntegrationConfigResponse,
    summary="Update integration credentials (Admin only)",
    description="Updates endpoint URL, credentials, and settings for '1nce' or 'odoo'."
)
def update_config(
    provider: str,
    data: IntegrationConfigUpdate,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    require_admin(current_user)
    if provider not in ("1nce", "odoo"):
        raise HTTPException(status_code=400, detail="Provider must be '1nce' or 'odoo'.")
    cfg = billing_service.update_integration_config(db, provider, data)
    return IntegrationConfigResponse(
        provider=cfg.provider,
        base_url=cfg.base_url,
        api_user=cfg.api_user,
        has_api_key=bool(cfg.api_key_encrypted),
        db_name=cfg.db_name,
        is_enabled=cfg.is_enabled,
        extra_settings=cfg.extra_settings,
        updated_at=cfg.updated_at,
    )


@router.post(
    "/config/test-1nce",
    response_model=ConnectionTestResult,
    summary="Test 1NCE Management API connectivity"
)
async def test_1nce_connection(
    current_user: AuthUser = Depends(get_current_user),
):
    require_admin(current_user)
    res = await once_client.test_connection()
    return ConnectionTestResult(
        provider="1nce",
        success=res["success"],
        mode=res.get("mode", "live"),
        message=res["message"],
        latency_ms=res.get("latency_ms"),
        details=res.get("details"),
    )


@router.post(
    "/config/test-odoo",
    response_model=ConnectionTestResult,
    summary="Test Odoo ERP XML-RPC / JSON-RPC connectivity"
)
async def test_odoo_connection(
    current_user: AuthUser = Depends(get_current_user),
):
    require_admin(current_user)
    res = await odoo_client.test_connection()
    return ConnectionTestResult(
        provider="odoo",
        success=res["success"],
        mode=res.get("mode", "live"),
        message=res["message"],
        latency_ms=res.get("latency_ms"),
        details=res.get("details"),
    )


@router.post(
    "/markup",
    summary="Update Admin Pricing Markup Percentage (No Fixed Amount)"
)
def update_admin_markup(
    data: AdminMarkupUpdateRequest,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    require_admin(current_user)
    billing_service.update_admin_markup(db, markup_pct=data.markup_percentage, provider_code=data.provider_code)
    return {
        "status": "success",
        "message": f"Pricing markup percentage successfully updated to {data.markup_percentage:.1f}% across SIM providers and plans.",
        "markup_percentage": data.markup_percentage,
        "pricing_model": "cost_plus_percentage",
        "has_fixed_amount": False,
    }
