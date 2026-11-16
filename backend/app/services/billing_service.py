import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.billing_plan import BillingPlan
from app.models.billing_usage_record import BillingUsageRecord
from app.models.integration_config import IntegrationConfig
from app.models.invoice_record import InvoiceRecord
from app.models.network_provider_config import NetworkProviderConfig
from app.models.network_sim_card import NetworkSimCard
from app.models.tenant_subscription import TenantSubscription
from app.schemas.billing import (
    BillingPlanCreate,
    BillingPlanUpdate,
    IntegrationConfigUpdate,
    InvoiceLineItem,
    SimUsageBreakdown,
    UsageSummaryResponse,
)
from app.dependencies.auth import AUTH_DB_URL
from app.services.odoo_client import odoo_client
from app.services.once_client import once_client
import psycopg

logger = logging.getLogger("nibiaanet.billing")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_tenant_info(tenant_id: int) -> Tuple[str, str]:
    """Resolves tenant name and type from device_registry database via direct query."""
    try:
        with psycopg.connect(AUTH_DB_URL, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name, type FROM tenants WHERE id = %s", (tenant_id,))
                row = cur.fetchone()
                if row:
                    return str(row[0]), str(row[1])
    except Exception:
        pass
    return f"Organization #{tenant_id}", "organization"


def _get_tenant_device_count(tenant_id: int) -> int:
    """Gets device count from device_registry database via direct query."""
    try:
        with psycopg.connect(AUTH_DB_URL, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM devices WHERE tenant_id = %s", (tenant_id,))
                row = cur.fetchone()
                if row:
                    return int(row[0])
    except Exception:
        pass
    return 0


DEFAULT_PLANS = [
    {
        "name": "Starter Cellular IoT",
        "code": "starter-cellular-500mb",
        "description": "Perfect for small IoT deployments: up to 10 NB-IoT/LTE-M sensors with 500 MB pooled data.",
        "monthly_price": 19.00,
        "annual_price": 190.00,
        "currency": "USD",
        "included_devices": 10,
        "included_data_mb": 500.0,
        "overage_rate_per_mb": 0.05,
        "extra_device_price": 1.50,
        "features": {
            "satellite_fallback": False,
            "api_access": True,
            "sms_commands_monthly": 100,
            "retention_days": 30,
        },
        "is_active": True,
    },
    {
        "name": "Fleet Pro Cellular",
        "code": "fleet-pro-2gb",
        "description": "Comprehensive fleet tracking and telemetry with 2 GB pooled data and up to 50 active SIM cards.",
        "monthly_price": 69.00,
        "annual_price": 690.00,
        "currency": "USD",
        "included_devices": 50,
        "included_data_mb": 2048.0,
        "overage_rate_per_mb": 0.04,
        "extra_device_price": 1.25,
        "features": {
            "satellite_fallback": False,
            "api_access": True,
            "sms_commands_monthly": 500,
            "retention_days": 90,
            "priority_support": True,
        },
        "is_active": True,
    },
    {
        "name": "Enterprise NTN / TN Hybrid",
        "code": "enterprise-hybrid-10gb",
        "description": "Global connectivity: Cellular (1NCE) + Satellite NTN (Skylo/Sateliot) with 10 GB pooled data.",
        "monthly_price": 199.00,
        "annual_price": 1990.00,
        "currency": "USD",
        "included_devices": 100,
        "included_data_mb": 10240.0,
        "overage_rate_per_mb": 0.03,
        "extra_device_price": 1.00,
        "features": {
            "satellite_fallback": True,
            "api_access": True,
            "sms_commands_monthly": 2000,
            "retention_days": 365,
            "dedicated_account_manager": True,
        },
        "is_active": True,
    },
    {
        "name": "1NCE Direct Flat-Rate Metered",
        "code": "1nce-metered-payg",
        "description": "Direct pass-through for 1NCE 10-year lifetime and annual SIM subscriptions with metered telemetry.",
        "monthly_price": 9.00,
        "annual_price": 99.00,
        "currency": "USD",
        "included_devices": 5,
        "included_data_mb": 250.0,
        "overage_rate_per_mb": 0.05,
        "extra_device_price": 2.00,
        "features": {
            "direct_1nce_sync": True,
            "sms_commands_monthly": 50,
            "retention_days": 30,
        },
        "is_active": True,
    },
]


class BillingService:
    """
    Core service coordinating Billing Plans, Subscriptions, Usage Metering,
    Odoo ERP Invoicing, and 1NCE Cellular Network Operations.
    """

    # -------------------------------------------------------------------------
    # Seed & Plan Management
    # -------------------------------------------------------------------------

    def seed_default_plans(self, db: Session) -> int:
        """Seeds initial billing plans if the table is empty."""
        count = 0
        for plan_dict in DEFAULT_PLANS:
            existing = db.query(BillingPlan).filter(BillingPlan.code == plan_dict["code"]).first()
            if not existing:
                plan = BillingPlan(**plan_dict)
                db.add(plan)
                count += 1
        if count > 0:
            db.commit()
            logger.info(f"Seeded {count} default billing plans.")
        return count

    def list_plans(self, db: Session, active_only: bool = True) -> List[BillingPlan]:
        query = db.query(BillingPlan)
        if active_only:
            query = query.filter(BillingPlan.is_active == True)
        plans = query.all()
        return sorted(plans, key=lambda p: float(p.monthly_price or 0.0))

    def get_plan(self, db: Session, plan_id: int) -> Optional[BillingPlan]:
        return db.query(BillingPlan).filter(BillingPlan.id == plan_id).first()

    def create_plan(self, db: Session, data: BillingPlanCreate) -> BillingPlan:
        plan = BillingPlan(**data.model_dump())
        db.add(plan)
        db.commit()
        db.refresh(plan)
        return plan

    def update_plan(self, db: Session, plan_id: int, data: BillingPlanUpdate) -> BillingPlan:
        plan = self.get_plan(db, plan_id)
        if not plan:
            raise ValueError(f"Plan ID {plan_id} not found.")

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(plan, key, value)

        db.commit()
        db.refresh(plan)
        return plan

    # -------------------------------------------------------------------------
    # Subscription Management
    # -------------------------------------------------------------------------

    def get_tenant_subscription(self, db: Session, tenant_id: int) -> Optional[TenantSubscription]:
        return db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).first()

    def list_subscriptions(self, db: Session) -> List[TenantSubscription]:
        return db.query(TenantSubscription).all()

    async def subscribe_tenant(
        self,
        db: Session,
        tenant_id: int,
        plan_id: int,
        interval: str = "monthly",
        auto_renew: bool = True,
    ) -> TenantSubscription:
        """
        Subscribes a tenant to a billing plan.
        Syncs/creates Odoo Customer (res.partner) and sets active subscription dates.
        """
        # Resolve organization info
        tenant_name, tenant_type = _resolve_tenant_info(tenant_id)

        plan = self.get_plan(db, plan_id)
        if not plan or not plan.is_active:
            raise ValueError(f"Plan ID {plan_id} does not exist or is inactive.")

        # Sync with Odoo res.partner
        odoo_partner_id = None
        try:
            odoo_partner_id = await odoo_client.find_or_create_partner(
                name=tenant_name,
                notes=f"Tenant ID: {tenant_id} ({tenant_type})",
            )
        except Exception as oe:
            logger.warning(f"Could not sync tenant with Odoo partner: {oe}")

        now = utc_now()
        period_days = 365 if interval == "annually" else 30
        period_end = now + timedelta(days=period_days)

        subscription = self.get_tenant_subscription(db, tenant_id)
        if subscription:
            subscription.plan_id = plan_id
            subscription.billing_interval = interval
            subscription.auto_renew = auto_renew
            subscription.status = "active"
            subscription.current_period_start = now
            subscription.current_period_end = period_end
            if odoo_partner_id:
                subscription.odoo_partner_id = odoo_partner_id
        else:
            subscription = TenantSubscription(
                tenant_id=tenant_id,
                plan_id=plan_id,
                billing_interval=interval,
                status="active",
                current_period_start=now,
                current_period_end=period_end,
                auto_renew=auto_renew,
                odoo_partner_id=odoo_partner_id,
            )
            db.add(subscription)

        db.commit()
        db.refresh(subscription)
        return subscription

    def cancel_subscription(
        self,
        db: Session,
        tenant_id: int,
        immediate: bool = False,
    ) -> TenantSubscription:
        """Cancels a subscription either immediately or at period end."""
        sub = self.get_tenant_subscription(db, tenant_id)
        if not sub:
            raise ValueError(f"No active subscription found for tenant {tenant_id}.")

        if immediate:
            sub.status = "cancelled"
            sub.auto_renew = False
        else:
            sub.cancel_at_period_end = True
            sub.auto_renew = False

        db.commit()
        db.refresh(sub)
        return sub

    # -------------------------------------------------------------------------
    # Usage & Metering
    # -------------------------------------------------------------------------

    def _get_provider_rates_and_markup(self, db: Session, plan: Optional[BillingPlan] = None) -> Tuple[float, float, float, float]:
        """
        Returns (markup_percentage, cost_per_mb, cost_per_sim, cost_per_sms)
        based on active network provider configs and plan overrides.
        """
        prov = db.query(NetworkProviderConfig).filter(NetworkProviderConfig.is_enabled == True).order_by(NetworkProviderConfig.id.asc()).first()
        markup_pct = (getattr(plan, "markup_percentage", None) if plan else None)
        if markup_pct is None:
            markup_pct = (getattr(prov, "markup_percentage", None) if prov else None)
        if markup_pct is None:
            markup_pct = 20.0

        cost_mb = (getattr(prov, "cost_per_mb", None) if prov else None) or 0.03
        cost_sim = (getattr(prov, "cost_per_sim", None) if prov else None) or 1.00
        cost_sms = (getattr(prov, "cost_per_sms", None) if prov else None) or 0.01

        return float(markup_pct), float(cost_mb), float(cost_sim), float(cost_sms)

    def get_tenant_usage_summary(self, db: Session, tenant_id: int) -> UsageSummaryResponse:
        """
        Aggregates SIM data and active lines, calculating dynamic % pricing
        based on wholesale cost billed by SIM provider + Admin markup % (No fixed amount).
        """
        sub = self.get_tenant_subscription(db, tenant_id)
        plan = sub.plan if sub else self.list_plans(db, active_only=True)[0]
        sub_status = sub.status if sub else "no_subscription"
        p_start = sub.current_period_start if sub else utc_now() - timedelta(days=30)
        p_end = sub.current_period_end if sub else utc_now()

        # Query all SIM cards assigned to tenant
        sims = db.query(NetworkSimCard).filter(NetworkSimCard.tenant_id == tenant_id).all()
        total_active_sims = sum(1 for s in sims if s.status == "Active")

        if total_active_sims == 0:
            total_active_sims = _get_tenant_device_count(tenant_id)

        total_data_used_mb = 0.0
        sim_details = []
        for s in sims:
            used = s.quota_used_mb or 0.0
            total_data_used_mb += used
            sim_details.append(
                SimUsageBreakdown(
                    iccid=s.iccid,
                    device_id=s.device_id,
                    label=s.label,
                    status=s.status,
                    data_used_mb=round(used, 2),
                    quota_remaining_mb=round(s.quota_remaining_mb or 0.0, 2),
                    quota_total_mb=round(s.quota_total_mb or 500.0, 2),
                )
            )

        # Dynamic % Pricing Calculation: Billed by SIM Provider + Admin Markup %
        markup_pct, mb_rate, sim_rate, sms_rate = self._get_provider_rates_and_markup(db, plan)

        raw_data_cost = round(total_data_used_mb * mb_rate, 4)
        raw_sim_cost = round(total_active_sims * sim_rate, 4)
        provider_billed_cost = round(raw_data_cost + raw_sim_cost, 2)

        markup_amount = round(provider_billed_cost * (markup_pct / 100.0), 2)
        total_customer_charge = round(provider_billed_cost + markup_amount, 2)

        return UsageSummaryResponse(
            tenant_id=tenant_id,
            subscription_status=sub_status,
            plan_name=plan.name if plan else "Dynamic Cellular IoT",
            pricing_model="cost_plus_percentage",
            markup_percentage=markup_pct,
            period_start=p_start,
            period_end=p_end,
            total_active_sims=total_active_sims,
            included_devices=0,
            billable_extra_devices=total_active_sims,
            total_data_used_mb=round(total_data_used_mb, 2),
            included_data_mb=0.0,
            billable_overage_mb=round(total_data_used_mb, 2),
            provider_billed_cost=provider_billed_cost,
            markup_amount=markup_amount,
            estimated_overage_charge=total_customer_charge,
            estimated_total_next_invoice=total_customer_charge,
            currency="USD",
            sim_details=sim_details,
        )

    def get_system_usage_summary(self, db: Session) -> UsageSummaryResponse:
        """
        Global platform-wide usage across all tenants for Platform Administrator.
        """
        sims = db.query(NetworkSimCard).all()
        total_active_sims = sum(1 for s in sims if s.status == "Active")
        total_data_used_mb = 0.0
        sim_details = []
        for s in sims:
            used = s.quota_used_mb or 0.0
            total_data_used_mb += used
            sim_details.append(
                SimUsageBreakdown(
                    iccid=s.iccid,
                    device_id=s.device_id,
                    label=s.label,
                    status=s.status,
                    data_used_mb=round(used, 2),
                    quota_remaining_mb=round(s.quota_remaining_mb or 0.0, 2),
                    quota_total_mb=round(s.quota_total_mb or 500.0, 2),
                )
            )

        markup_pct, mb_rate, sim_rate, sms_rate = self._get_provider_rates_and_markup(db)
        raw_data_cost = round(total_data_used_mb * mb_rate, 4)
        raw_sim_cost = round(total_active_sims * sim_rate, 4)
        provider_billed_cost = round(raw_data_cost + raw_sim_cost, 2)
        markup_amount = round(provider_billed_cost * (markup_pct / 100.0), 2)
        total_customer_charge = round(provider_billed_cost + markup_amount, 2)

        return UsageSummaryResponse(
            tenant_id=0,
            subscription_status="platform_admin",
            plan_name="Global Platform Scope",
            pricing_model="cost_plus_percentage",
            markup_percentage=markup_pct,
            period_start=utc_now() - timedelta(days=30),
            period_end=utc_now(),
            total_active_sims=total_active_sims,
            included_devices=0,
            billable_extra_devices=total_active_sims,
            total_data_used_mb=round(total_data_used_mb, 2),
            included_data_mb=0.0,
            billable_overage_mb=round(total_data_used_mb, 2),
            provider_billed_cost=provider_billed_cost,
            markup_amount=markup_amount,
            estimated_overage_charge=total_customer_charge,
            estimated_total_next_invoice=total_customer_charge,
            currency="USD",
            sim_details=sim_details,
        )

    def update_admin_markup(self, db: Session, markup_pct: float, provider_code: Optional[str] = None):
        """
        Admin action: Updates the markup percentage applied on top of SIM provider billed charges.
        There is no fixed amount - customer pricing is (Provider Billed Cost) + (Markup %).
        """
        if provider_code and provider_code.lower() != "all":
            prov = db.query(NetworkProviderConfig).filter(NetworkProviderConfig.provider_code == provider_code).first()
            if prov:
                prov.markup_percentage = markup_pct
        else:
            for prov in db.query(NetworkProviderConfig).all():
                prov.markup_percentage = markup_pct
            for p in db.query(BillingPlan).all():
                p.markup_percentage = markup_pct
        db.commit()

    # -------------------------------------------------------------------------
    # Invoice Generation & Odoo Sync
    # -------------------------------------------------------------------------

    async def generate_invoice_for_tenant(
        self,
        db: Session,
        tenant_id: int,
        billing_interval: str = "monthly",
        include_overages: bool = True,
        post_to_odoo: bool = True,
        notes: Optional[str] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
    ) -> InvoiceRecord:
        """
        Creates an itemized invoice for a tenant:
        - 100% Dynamic % Pricing: NO FIXED AMOUNT.
        - Cellular Data Billed by SIM Provider + Admin Markup %
        - Active SIM Lines Billed by SIM Provider + Admin Markup %
        - Submits invoice to Odoo ERP (account.move)
        - Returns persisted InvoiceRecord.
        """
        tenant_name, tenant_type = _resolve_tenant_info(tenant_id)

        sub = self.get_tenant_subscription(db, tenant_id)
        plan = sub.plan if sub else self.list_plans(db, active_only=True)[0]

        now = utc_now()
        due_date = now + timedelta(days=14)
        invoice_seq = int(time.time())
        inv_number = f"NIB-{now.year}-{invoice_seq % 100000:05d}"

        # SIM fleet usage
        sims = db.query(NetworkSimCard).filter(NetworkSimCard.tenant_id == tenant_id).all()
        total_active_sims = sum(1 for s in sims if s.status == "Active")
        if total_active_sims == 0:
            total_active_sims = _get_tenant_device_count(tenant_id)
        total_data_used_mb = sum(s.quota_used_mb or 0.0 for s in sims)

        markup_pct, mb_rate, sim_rate, sms_rate = self._get_provider_rates_and_markup(db, plan)

        # Dynamic Line Items: Strictly % pricing on SIM provider wholesale costs (No Fixed Amount!)
        lines: List[Dict[str, Any]] = []

        eff_mb_rate = round(mb_rate * (1.0 + (markup_pct / 100.0)), 4)
        data_total = round(total_data_used_mb * eff_mb_rate, 2)
        lines.append({
            "name": f"Cellular Telemetry Data ({total_data_used_mb:.2f} MB @ ${eff_mb_rate:.4f}/MB [Provider Billed + {markup_pct:.0f}% Margin])",
            "quantity": round(total_data_used_mb, 2) if total_data_used_mb > 0 else 1.0,
            "unit_price": eff_mb_rate if total_data_used_mb > 0 else 0.0,
            "total": data_total,
            "type": "provider_data",
            "details": {
                "provider_wholesale_rate": mb_rate,
                "markup_percent": markup_pct,
                "provider_billed_cost": round(total_data_used_mb * mb_rate, 2),
            }
        })

        eff_sim_rate = round(sim_rate * (1.0 + (markup_pct / 100.0)), 2)
        sim_total = round(total_active_sims * eff_sim_rate, 2)
        lines.append({
            "name": f"Active SIM Fleet Connectivity ({total_active_sims} Lines @ ${eff_sim_rate:.2f}/Line [Provider Billed + {markup_pct:.0f}% Margin])",
            "quantity": float(total_active_sims) if total_active_sims > 0 else 1.0,
            "unit_price": eff_sim_rate if total_active_sims > 0 else 0.0,
            "total": sim_total,
            "type": "provider_sim_line",
            "details": {
                "provider_wholesale_rate": sim_rate,
                "markup_percent": markup_pct,
                "provider_billed_cost": round(total_active_sims * sim_rate, 2),
            }
        })

        subtotal = round(sum(item["total"] for item in lines), 2)
        tax = round(subtotal * 0.10, 2)
        total = round(subtotal + tax, 2)

        # Ensure Odoo partner ID exists
        partner_id = sub.odoo_partner_id if sub and sub.odoo_partner_id else None
        if not partner_id:
            try:
                partner_id = await odoo_client.find_or_create_partner(
                    name=tenant_name,
                    notes=f"Tenant ID: {tenant_id} ({tenant_type})",
                )
                if sub:
                    sub.odoo_partner_id = partner_id
            except Exception as e:
                logger.warning(f"Odoo partner lookup failed: {e}")
                partner_id = 1

        # Submit to Odoo
        odoo_invoice_id = None
        odoo_move_name = None
        odoo_payment_state = "not_paid"
        try:
            odoo_res = await odoo_client.create_customer_invoice(
                partner_id=partner_id or 1,
                line_items=lines,
                invoice_date=now.date(),
                due_date=due_date.date(),
                ref=inv_number,
                notes=notes,
                currency_code=plan.currency,
                auto_post=post_to_odoo,
            )
            odoo_invoice_id = odoo_res.get("id")
            odoo_move_name = odoo_res.get("name")
            odoo_payment_state = odoo_res.get("payment_state", "not_paid")
        except Exception as oe:
            logger.error(f"Error creating invoice in Odoo: {oe}")

        p_start = period_start or (now - timedelta(days=30))
        p_end = period_end or now

        # Create InvoiceRecord
        invoice_rec = InvoiceRecord(
            invoice_number=inv_number,
            tenant_id=tenant_id,
            subscription_id=sub.id if sub else None,
            period_start=p_start,
            period_end=p_end,
            due_date=due_date,
            amount_subtotal=subtotal,
            amount_tax=tax,
            amount_total=total,
            currency=plan.currency,
            status="posted" if post_to_odoo else "draft",
            odoo_invoice_id=odoo_invoice_id,
            odoo_move_name=odoo_move_name,
            odoo_payment_state=odoo_payment_state,
            line_items=lines,
            notes=notes,
        )
        db.add(invoice_rec)
        db.commit()
        db.refresh(invoice_rec)

        return invoice_rec

    async def process_recurring_invoices(
        self,
        db: Session,
        force_tenant_id: Optional[int] = None,
        force: bool = False,
    ) -> List[InvoiceRecord]:
        """
        Auto-generates invoices every 30 days from date of subscription for all active subscriptions.
        When current_period_end is reached (or 30 days have elapsed), creates the itemized
        invoice based on SIM provider usage + admin markup %, posts to Odoo ERP, advances the
        subscription period to the next 30-day cycle, and persists records.
        """
        now = utc_now()
        query = db.query(TenantSubscription).filter(TenantSubscription.status == "active")
        if force_tenant_id:
            query = query.filter(TenantSubscription.tenant_id == force_tenant_id)

        subscriptions = query.all()
        generated_invoices: List[InvoiceRecord] = []

        for sub in subscriptions:
            # Check if 30 days have elapsed since current_period_start or now >= current_period_end
            is_due = (now >= sub.current_period_end) or force
            if not is_due:
                continue

            # Determine period for this invoice: exactly 30 days from period start
            p_start = sub.current_period_start
            p_end = sub.current_period_end if not force else max(now, sub.current_period_start + timedelta(days=30))

            # Ensure we do not generate duplicate invoices for the exact same period
            existing = db.query(InvoiceRecord).filter(
                InvoiceRecord.subscription_id == sub.id,
                InvoiceRecord.period_start == p_start,
                InvoiceRecord.period_end == p_end,
            ).first()
            if existing and not force:
                # If already generated for this period, advance period to next 30 days
                sub.current_period_start = sub.current_period_end
                sub.current_period_end = sub.current_period_start + timedelta(days=30)
                db.commit()
                continue

            period_desc = (
                f"Auto-generated 30-day recurring subscription invoice "
                f"({p_start.strftime('%Y-%m-%d')} to {p_end.strftime('%Y-%m-%d')})"
            )
            try:
                inv = await self.generate_invoice_for_tenant(
                    db=db,
                    tenant_id=sub.tenant_id,
                    billing_interval=sub.billing_interval,
                    post_to_odoo=True,
                    notes=period_desc,
                    period_start=p_start,
                    period_end=p_end,
                )
                generated_invoices.append(inv)

                # Advance cycle by 30 days from date of subscription
                sub.current_period_start = p_end
                sub.current_period_end = sub.current_period_start + timedelta(days=30)
                sub.updated_at = now

                if sub.cancel_at_period_end:
                    sub.status = "cancelled"
                    sub.auto_renew = False

                db.commit()
                db.refresh(sub)
                logger.info(
                    f"Auto-generated recurring invoice {inv.invoice_number} for Tenant {sub.tenant_id} "
                    f"(Next 30-day cycle: {sub.current_period_start.strftime('%Y-%m-%d')} to {sub.current_period_end.strftime('%Y-%m-%d')})"
                )
            except Exception as e:
                logger.error(f"Failed to auto-generate 30-day invoice for tenant {sub.tenant_id}: {e}")
                db.rollback()

        return generated_invoices

    def list_invoices(self, db: Session, tenant_id: Optional[int] = None) -> List[InvoiceRecord]:
        query = db.query(InvoiceRecord)
        if tenant_id is not None:
            query = query.filter(InvoiceRecord.tenant_id == tenant_id)
        return query.order_by(InvoiceRecord.created_at.desc()).all()

    def get_invoice(self, db: Session, invoice_id: int) -> Optional[InvoiceRecord]:
        return db.query(InvoiceRecord).filter(InvoiceRecord.id == invoice_id).first()

    async def sync_invoice_with_odoo(self, db: Session, invoice_id: int) -> InvoiceRecord:
        """
        Synchronizes invoice payment and status from Odoo ERP.
        If invoice is paid, reactivates tenant subscription and associated 1NCE SIMs.
        """
        inv = self.get_invoice(db, invoice_id)
        if not inv:
            raise ValueError(f"Invoice ID {invoice_id} not found.")

        if inv.odoo_invoice_id:
            try:
                odoo_data = await odoo_client.get_invoice(inv.odoo_invoice_id)
                inv.odoo_payment_state = odoo_data.get("payment_state", inv.odoo_payment_state)
                inv.odoo_move_name = odoo_data.get("name", inv.odoo_move_name)

                if inv.odoo_payment_state == "paid":
                    inv.status = "paid"
                    inv.paid_at = inv.paid_at or utc_now()

                    # Reactivate subscription if it was suspended/past due
                    if inv.subscription and inv.subscription.status in ("past_due", "suspended"):
                        inv.subscription.status = "active"

                    # Reactivate any suspended SIMs under this tenant
                    await self.reactivate_tenant_sims(db, inv.tenant_id)

            except Exception as e:
                logger.error(f"Failed to sync invoice {invoice_id} with Odoo: {e}")

        db.commit()
        db.refresh(inv)
        return inv

    async def pay_invoice(
        self,
        db: Session,
        invoice_id: int,
        payment_method: str = "odoo_reconcile",
        notes: Optional[str] = None,
    ) -> InvoiceRecord:
        """
        Records invoice payment locally and on Odoo, reactivating any suspended SIMs.
        """
        inv = self.get_invoice(db, invoice_id)
        if not inv:
            raise ValueError(f"Invoice ID {invoice_id} not found.")

        if inv.odoo_invoice_id:
            try:
                await odoo_client.mark_invoice_as_paid(inv.odoo_invoice_id, payment_method)
            except Exception as e:
                logger.warning(f"Could not register payment in Odoo: {e}")

        inv.status = "paid"
        inv.odoo_payment_state = "paid"
        inv.paid_at = utc_now()
        if notes:
            inv.notes = f"{inv.notes or ''}\n[Payment]: {payment_method} - {notes}".strip()

        # Update subscription status
        if inv.subscription:
            inv.subscription.status = "active"

        # Reactivate any suspended 1NCE SIMs
        await self.reactivate_tenant_sims(db, inv.tenant_id)

        db.commit()
        db.refresh(inv)
        return inv

    async def reactivate_tenant_sims(self, db: Session, tenant_id: int):
        """Automatically reactivates any suspended SIMs for a tenant upon payment."""
        suspended_sims = (
            db.query(NetworkSimCard)
            .filter(
                NetworkSimCard.tenant_id == tenant_id,
                NetworkSimCard.status == "Suspended",
            )
            .all()
        )
        for sim in suspended_sims:
            try:
                await once_client.set_sim_status(sim.iccid, "Active")
                sim.status = "Active"
                logger.info(f"Reactivated 1NCE SIM {sim.iccid} following payment by tenant {tenant_id}.")
            except Exception as e:
                logger.error(f"Error reactivating SIM {sim.iccid}: {e}")
        db.commit()

    # -------------------------------------------------------------------------
    # 1NCE Network SIM Management
    # -------------------------------------------------------------------------

    async def sync_sims_from_1nce(self, db: Session, tenant_id: Optional[int] = None) -> List[NetworkSimCard]:
        """
        Fetches SIM inventory from 1NCE Management API and synchronizes
        into network_sim_cards database table with current quotas.
        """
        sims_raw = await once_client.list_sims(page=1, page_size=100)
        synced_cards = []

        now = utc_now()
        for raw in sims_raw:
            iccid = raw.get("iccid")
            if not iccid:
                continue

            card = db.query(NetworkSimCard).filter(NetworkSimCard.iccid == iccid).first()
            if not card:
                card = NetworkSimCard(
                    iccid=iccid,
                    provider="1nce",
                    status=raw.get("status", "Active"),
                    tenant_id=tenant_id,
                )
                db.add(card)

            card.imei = raw.get("imei") or card.imei
            card.imsi = raw.get("imsi") or card.imsi
            card.msisdn = raw.get("msisdn") or card.msisdn
            card.ip_address = raw.get("ip_address") or card.ip_address
            card.label = raw.get("label") or card.label
            card.status = raw.get("status", card.status)
            card.imei_lock = bool(raw.get("imei_lock", card.imei_lock))
            card.last_sync_at = now

            # Fetch Quota details from 1NCE
            try:
                quota = await once_client.get_data_quota(iccid)
                card.quota_total_mb = quota.get("volume_total_mb", 500.0)
                card.quota_remaining_mb = quota.get("volume_remaining_mb", 500.0)
                card.quota_used_mb = quota.get("volume_used_mb", 0.0)
            except Exception as qe:
                logger.warning(f"Could not fetch data quota for SIM {iccid}: {qe}")

            synced_cards.append(card)

        db.commit()
        for c in synced_cards:
            db.refresh(c)
        return synced_cards

    def list_sim_cards(
        self,
        db: Session,
        tenant_id: Optional[int] = None,
        status: Optional[str] = None,
        unassigned: bool = False,
    ) -> List[NetworkSimCard]:
        query = db.query(NetworkSimCard)
        if unassigned:
            query = query.filter(NetworkSimCard.tenant_id == None)
        elif tenant_id is not None:
            query = query.filter(NetworkSimCard.tenant_id == tenant_id)
        if status:
            query = query.filter(NetworkSimCard.status == status)
        cards = query.order_by(NetworkSimCard.id.asc()).all()
        # Enforce rule: if device is unassigned, there is no IMEI
        for c in cards:
            if not c.device_id or str(c.device_id).strip().lower() in ("unassigned", "none", "", "null"):
                c.imei = None
        return cards

    def get_sim_card(self, db: Session, iccid: str) -> Optional[NetworkSimCard]:
        return db.query(NetworkSimCard).filter(NetworkSimCard.iccid == iccid).first()

    async def update_sim_status(
        self,
        db: Session,
        iccid: str,
        status: str,
        tenant_id: Optional[int] = None,
    ) -> NetworkSimCard:
        """Changes SIM status (Active/Suspended) on 1NCE API and updates DB."""
        card = self.get_sim_card(db, iccid)
        if not card:
            raise ValueError(f"SIM with ICCID '{iccid}' not found in platform.")

        if tenant_id and card.tenant_id != tenant_id:
            raise PermissionError("Access denied: SIM belongs to another organization.")

        # Call 1NCE API
        await once_client.set_sim_status(iccid, status)

        card.status = status.capitalize()
        db.commit()
        db.refresh(card)
        return card

    async def reset_sim_connectivity(self, db: Session, iccid: str) -> Dict[str, Any]:
        """Triggers network detach/reattach reset on 1NCE for a SIM."""
        card = self.get_sim_card(db, iccid)
        if not card:
            raise ValueError(f"SIM with ICCID '{iccid}' not found.")
        return await once_client.reset_sim(iccid)

    async def topup_sim(
        self,
        db: Session,
        iccid: str,
        volume_mb: float = 500.0,
        create_odoo_invoice: bool = True,
    ) -> Dict[str, Any]:
        """Tops up 1NCE SIM data quota and creates an Odoo invoice if requested."""
        card = self.get_sim_card(db, iccid)
        if not card:
            raise ValueError(f"SIM with ICCID '{iccid}' not found.")

        # Apply topup via 1NCE
        topup_res = await once_client.topup_quota(iccid, volume_mb)

        # Update local card
        card.quota_total_mb = (card.quota_total_mb or 0.0) + volume_mb
        card.quota_remaining_mb = (card.quota_remaining_mb or 0.0) + volume_mb
        if card.status == "Suspended":
            card.status = "Active"
        db.commit()

        # Optional: Generate Odoo invoice for top-up
        invoice_id = None
        if create_odoo_invoice and card.tenant_id:
            topup_price = round(volume_mb * 0.04, 2) # e.g. $20 for 500MB
            lines = [{
                "name": f"1NCE Data Quota Top-Up ({volume_mb} MB for SIM {iccid})",
                "quantity": 1.0,
                "unit_price": topup_price,
                "total": topup_price,
                "type": "topup",
            }]
            now = utc_now()
            inv_rec = InvoiceRecord(
                invoice_number=f"NIB-TOPUP-{int(time.time())}",
                tenant_id=card.tenant_id,
                period_start=now,
                period_end=now,
                due_date=now + timedelta(days=7),
                amount_subtotal=topup_price,
                amount_tax=0.0,
                amount_total=topup_price,
                currency="USD",
                status="posted",
                line_items=lines,
                notes=f"Automatic top-up invoice for SIM {iccid}",
            )
            db.add(inv_rec)
            db.commit()
            invoice_id = inv_rec.id

        return {
            "success": True,
            "iccid": iccid,
            "volume_added_mb": volume_mb,
            "new_quota_remaining_mb": card.quota_remaining_mb,
            "invoice_id": invoice_id,
            "message": f"Successfully applied {volume_mb} MB top-up to SIM {iccid}.",
        }

    async def send_sim_sms(
        self,
        db: Session,
        iccid: str,
        payload: str,
        source_address: str = "NibiaaNet",
    ) -> Dict[str, Any]:
        """Dispatches MT-SMS to SIM."""
        card = self.get_sim_card(db, iccid)
        if not card:
            raise ValueError(f"SIM with ICCID '{iccid}' not found.")
        return await once_client.send_sms(iccid, payload, source_address)

    def assign_sim(
        self,
        db: Session,
        iccid: str,
        tenant_id: Optional[int] = None,
        device_id: Optional[str] = None,
        label: Optional[str] = None,
        imei: Optional[str] = None,
    ) -> NetworkSimCard:
        """Assigns SIM to a tenant and device. If device is unassigned, IMEI is cleared."""
        card = self.get_sim_card(db, iccid)
        if not card:
            card = NetworkSimCard(
                iccid=iccid,
                provider="1nce",
                status="Active",
            )
            db.add(card)

        if tenant_id is not None:
            card.tenant_id = None if tenant_id in (0, -1) else tenant_id

        # Normalize device_id
        dev_id = str(device_id).strip() if device_id is not None else None
        if dev_id in ("", "none", "null", "unassign", "unassigned", None):
            card.device_id = None
            card.imei = None  # Crucial rule: if device is unassigned, no IMEI!
        else:
            card.device_id = dev_id
            # IMEI comes after SIM is attached to device
            if imei and imei.strip():
                card.imei = imei.strip()
            elif not card.imei:
                # Look up device from main DB devices table to pull device's IMEI if available
                try:
                    from app.database import SessionLocal
                    from app.models.device import Device
                    with SessionLocal() as db_main:
                        dev = db_main.query(Device).filter(Device.device_id == dev_id).first()
                        if dev and dev.credentials and dev.credentials.get("imei"):
                            card.imei = dev.credentials["imei"]
                except Exception:
                    pass

        if label is not None:
            card.label = label.strip() if label else None

        db.commit()
        db.refresh(card)
        return card

    # -------------------------------------------------------------------------
    # Integration Configs
    # -------------------------------------------------------------------------

    def get_integration_config(self, db: Session, provider: str) -> Optional[IntegrationConfig]:
        return db.query(IntegrationConfig).filter(IntegrationConfig.provider == provider).first()

    def update_integration_config(
        self,
        db: Session,
        provider: str,
        data: IntegrationConfigUpdate,
    ) -> IntegrationConfig:
        config = self.get_integration_config(db, provider)
        if not config:
            config = IntegrationConfig(
                provider=provider,
                base_url=data.base_url,
                api_user=data.api_user,
                api_key_encrypted=data.api_key,
                db_name=data.db_name,
                is_enabled=data.is_enabled,
                extra_settings=data.extra_settings or {},
            )
            db.add(config)
        else:
            config.base_url = data.base_url
            if data.api_user is not None:
                config.api_user = data.api_user
            if data.api_key is not None:
                config.api_key_encrypted = data.api_key
            if data.db_name is not None:
                config.db_name = data.db_name
            config.is_enabled = data.is_enabled
            if data.extra_settings is not None:
                config.extra_settings = data.extra_settings

        db.commit()
        db.refresh(config)

        # Update runtime clients
        if provider == "1nce":
            once_client.base_url = config.base_url
            once_client.client_id = config.api_user or ""
            once_client.client_secret = config.api_key_encrypted or ""
        elif provider == "odoo":
            odoo_client.url = config.base_url
            odoo_client.db = config.db_name or "odoo"
            odoo_client.username = config.api_user or "admin"
            odoo_client.password = config.api_key_encrypted or ""

        return config


# Shared singleton instance
billing_service = BillingService()
