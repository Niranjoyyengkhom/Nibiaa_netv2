import pytest
from conftest import headers
from app.models.network_sim_card import NetworkSimCard
from app.services.billing_service import billing_service


@pytest.fixture
def billing_seed(db, seed):
    # Ensure default plans are present
    billing_service.seed_default_plans(db)
    return seed


def test_list_plans_and_admin_create(client, billing_seed):
    # List plans as normal tenant user
    resp = client.get("/billing/plans", headers=headers(billing_seed["ta1"]))
    assert resp.status_code == 200
    plans = resp.json()
    assert len(plans) >= 4
    codes = [p["code"] for p in plans]
    assert "starter-cellular-500mb" in codes
    assert "1nce-metered-payg" in codes

    # Non-admin cannot create plan
    create_payload = {
        "name": "Custom VIP Tier",
        "code": "custom-vip",
        "description": "VIP plan",
        "monthly_price": 49.00,
        "annual_price": 490.00,
        "included_devices": 25,
        "included_data_mb": 1000.0,
        "overage_rate_per_mb": 0.04,
        "extra_device_price": 1.50,
    }
    resp_forbidden = client.post(
        "/billing/plans",
        headers=headers(billing_seed["ta1"]),
        json=create_payload,
    )
    assert resp_forbidden.status_code == 403

    # Admin can create plan
    resp_created = client.post(
        "/billing/plans",
        headers=headers(billing_seed["admin"]),
        json=create_payload,
    )
    assert resp_created.status_code == 201
    assert resp_created.json()["code"] == "custom-vip"


def test_subscribe_tenant_workflow(client, billing_seed):
    # Get Starter Plan ID
    plans_resp = client.get("/billing/plans", headers=headers(billing_seed["ta1"]))
    starter_plan = next(p for p in plans_resp.json() if p["code"] == "starter-cellular-500mb")

    # Subscribe Tenant 1
    sub_payload = {
        "plan_id": starter_plan["id"],
        "billing_interval": "monthly",
        "auto_renew": True,
    }
    sub_resp = client.post(
        "/billing/subscriptions/subscribe",
        headers=headers(billing_seed["ta1"]),
        json=sub_payload,
    )
    assert sub_resp.status_code == 200
    sub_data = sub_resp.json()
    assert sub_data["status"] == "active"
    assert sub_data["plan_id"] == starter_plan["id"]
    assert sub_data["odoo_partner_id"] is not None

    # Retrieve own subscription
    my_sub_resp = client.get("/billing/subscriptions/me", headers=headers(billing_seed["ta1"]))
    assert my_sub_resp.status_code == 200
    assert my_sub_resp.json()["id"] == sub_data["id"]

    # Cancel subscription
    cancel_resp = client.post("/billing/subscriptions/cancel", headers=headers(billing_seed["ta1"]))
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["cancel_at_period_end"] is True


def test_usage_metering_with_sims(client, db, billing_seed):
    # Subscribe Tenant 1
    plans_resp = client.get("/billing/plans", headers=headers(billing_seed["ta1"]))
    starter = next(p for p in plans_resp.json() if p["code"] == "starter-cellular-500mb")
    client.post(
        "/billing/subscriptions/subscribe",
        headers=headers(billing_seed["ta1"]),
        json={"plan_id": starter["id"], "billing_interval": "monthly"},
    )

    # Add 12 SIM cards (Starter includes 10 -> 2 extra)
    # Total data usage: 650 MB (Starter includes 500 MB -> 150 MB overage)
    for i in range(12):
        sim = NetworkSimCard(
            iccid=f"89882806660000000{10+i}",
            imei=f"3569380356438{10+i}",
            provider="1nce",
            status="Active",
            tenant_id=1,
            quota_total_mb=500.0,
            quota_used_mb=54.16, # 12 * 54.16 ~ 650 MB total
            quota_remaining_mb=445.84,
        )
        db.add(sim)
    db.commit()

    # Query Usage
    usage_resp = client.get("/billing/usage", headers=headers(billing_seed["ta1"]))
    assert usage_resp.status_code == 200
    u = usage_resp.json()

    assert u["total_active_sims"] == 12
    assert u["included_devices"] == 10
    assert u["billable_extra_devices"] == 2
    assert u["total_data_used_mb"] >= 649.0
    assert u["billable_overage_mb"] >= 149.0
    assert u["estimated_overage_charge"] > 0
    # Next invoice estimated total should be monthly price + overage
    assert u["estimated_total_next_invoice"] > starter["monthly_price"]


def test_invoice_generation_and_payment_flow(client, db, billing_seed):
    # Subscribe Tenant 1
    plans_resp = client.get("/billing/plans", headers=headers(billing_seed["ta1"]))
    starter = next(p for p in plans_resp.json() if p["code"] == "starter-cellular-500mb")
    client.post(
        "/billing/subscriptions/subscribe",
        headers=headers(billing_seed["ta1"]),
        json={"plan_id": starter["id"], "billing_interval": "monthly"},
    )

    # Generate Invoice
    gen_resp = client.post(
        "/billing/invoices/generate",
        headers=headers(billing_seed["ta1"]),
        json={"billing_interval": "monthly", "include_overages": True, "post_to_odoo": True},
    )
    assert gen_resp.status_code == 200
    inv = gen_resp.json()
    assert inv["invoice_number"].startswith("NIB-")
    assert inv["odoo_invoice_id"] is not None
    assert inv["odoo_move_name"] is not None
    assert inv["amount_total"] > 0
    assert inv["status"] == "posted"

    invoice_id = inv["id"]

    # Sync with Odoo
    sync_resp = client.post(f"/billing/invoices/{invoice_id}/sync-odoo", headers=headers(billing_seed["ta1"]))
    assert sync_resp.status_code == 200

    # Pay Invoice
    pay_resp = client.post(
        f"/billing/invoices/{invoice_id}/pay",
        headers=headers(billing_seed["ta1"]),
        json={"payment_method": "odoo_reconcile", "notes": "Settled via wire"},
    )
    assert pay_resp.status_code == 200
    assert pay_resp.json()["status"] == "paid"
    assert pay_resp.json()["odoo_payment_state"] == "paid"

    # Download PDF
    pdf_resp = client.get(f"/billing/invoices/{invoice_id}/pdf", headers=headers(billing_seed["ta1"]))
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"


def test_1nce_network_endpoints(client, billing_seed):
    # 1. Sync SIMs from 1NCE
    sync_resp = client.post("/network/1nce/sims/sync", headers=headers(billing_seed["ta1"]))
    assert sync_resp.status_code == 200
    sims = sync_resp.json()
    assert len(sims) >= 3

    target_iccid = sims[0]["iccid"]

    # 2. Get Single SIM
    get_resp = client.get(f"/network/1nce/sims/{target_iccid}", headers=headers(billing_seed["ta1"]))
    assert get_resp.status_code == 200
    assert get_resp.json()["iccid"] == target_iccid

    # 3. Query Live Data Quota
    quota_resp = client.get(f"/network/1nce/sims/{target_iccid}/quota", headers=headers(billing_seed["ta1"]))
    assert quota_resp.status_code == 200
    assert quota_resp.json()["volume_total_mb"] == 500.0

    # 4. Query Connectivity Info
    conn_resp = client.get(f"/network/1nce/sims/{target_iccid}/connectivity", headers=headers(billing_seed["ta1"]))
    assert conn_resp.status_code == 200
    assert conn_resp.json()["status"] in ("Attached", "Detached")

    # 5. Suspend SIM
    suspend_resp = client.post(
        f"/network/1nce/sims/{target_iccid}/status",
        headers=headers(billing_seed["ta1"]),
        json={"status": "Suspended"},
    )
    assert suspend_resp.status_code == 200
    assert suspend_resp.json()["status"] == "Suspended"

    # 6. Reset SIM Connectivity
    reset_resp = client.post(f"/network/1nce/sims/{target_iccid}/reset", headers=headers(billing_seed["ta1"]))
    assert reset_resp.status_code == 200
    assert reset_resp.json()["status"] == "ResetInitiated"

    # 7. Reactivate SIM
    activate_resp = client.post(
        f"/network/1nce/sims/{target_iccid}/status",
        headers=headers(billing_seed["ta1"]),
        json={"status": "Active"},
    )
    assert activate_resp.status_code == 200
    assert activate_resp.json()["status"] == "Active"

    # 8. Top-up Quota
    topup_resp = client.post(
        f"/network/1nce/sims/{target_iccid}/topup",
        headers=headers(billing_seed["ta1"]),
        json={"volume_mb": 500.0, "create_odoo_invoice": True},
    )
    assert topup_resp.status_code == 200
    assert topup_resp.json()["volume_added_mb"] == 500.0

    # 9. Send MT-SMS
    sms_resp = client.post(
        f"/network/1nce/sims/{target_iccid}/sms",
        headers=headers(billing_seed["ta1"]),
        json={"payload": "REBOOT#NOW"},
    )
    assert sms_resp.status_code == 200
    assert sms_resp.json()["status"] in ("Sent", "Delivered")


def test_diagnostics_and_test_endpoints(client, billing_seed):
    # Test 1NCE Connection
    t_1nce = client.post("/billing/config/test-1nce", headers=headers(billing_seed["admin"]))
    assert t_1nce.status_code == 200
    assert t_1nce.json()["success"] is True

    # Test Odoo Connection
    t_odoo = client.post("/billing/config/test-odoo", headers=headers(billing_seed["admin"]))
    assert t_odoo.status_code == 200
    assert t_odoo.json()["success"] is True
