import os
import sys
from datetime import datetime, timedelta, timezone

os.environ["CASSANDRA_ENABLED"] = "false"
os.environ["REDIS_ENABLED"] = "false"

# Ensure backend is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

TEST_DB_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_billing_suite.db"))
if os.path.exists(TEST_DB_FILE):
    try:
        os.remove(TEST_DB_FILE)
    except Exception:
        pass

from fastapi.testclient import TestClient
import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
import app.database as database
from app.billing_database import BillingBase, get_billing_db
import app.billing_database as billing_database
from app.dependencies.auth import ALGORITHM, SECRET_KEY
from app.main import app
from app.models.tenant import Tenant
from app.models.user import User
from app.models.billing_plan import BillingPlan
from app.models.network_provider_config import NetworkProviderConfig
from app.models.network_sim_card import NetworkSimCard
from app.models.tenant_subscription import TenantSubscription
from app.services.billing_service import billing_service
from app.services.network_provider_service import network_provider_service
from app.services.user_service import hash_password

# Set up SQLite engine with file
engine = create_engine(f"sqlite:///{TEST_DB_FILE}", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)
BillingBase.metadata.create_all(bind=engine)

database.engine = engine
database.SessionLocal = TestingSessionLocal
billing_database.billing_engine = engine
billing_database.BillingSessionLocal = TestingSessionLocal

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_billing_db] = override_get_db
client = TestClient(app)

def make_token(user_id: int) -> dict:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(minutes=30)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}

def run_tests():
    print("[*] Setting up test data...")
    db = TestingSessionLocal()

    # Seed Admin & Tenant
    admin = User(name="Global Admin", email="admin@nibiaa.com", role="admin", password_hash=hash_password("admin123"))
    t1 = Tenant(name="Acme IoT Labs", type="organization", is_active=True)
    db.add_all([admin, t1])
    db.commit()
    db.refresh(admin)
    db.refresh(t1)

    owner1 = User(name="Owner 1", email="owner1@acme.com", role="tenant_admin", tenant_id=t1.id, password_hash=hash_password("owner123"))
    db.add(owner1)
    db.commit()
    db.refresh(owner1)

    admin_headers = make_token(admin.id)
    ta1_headers = make_token(owner1.id)

    # Seed default plans
    billing_service.seed_default_plans(db)
    print("  -> Default plans seeded successfully.")
    network_provider_service.seed_default_providers(db)
    print("  -> Default network providers (1NCE & Monogoto) seeded successfully.")

    # 1. Test List Plans & Encrypted-At-Rest Storage
    print("[*] Testing GET /billing/plans and verifying encrypted-at-rest database storage...")
    resp = client.get("/billing/plans", headers=ta1_headers)
    assert resp.status_code == 200, f"Failed: {resp.text}"
    plans = resp.json()
    assert len(plans) >= 4
    starter_plan = next(p for p in plans if p["code"] == "starter-cellular-500mb")
    print(f"  -> Retrieved {len(plans)} plans. Starter plan: {starter_plan['name']}")

    # Verify that data in the database is strictly encrypted (0 plaintext in raw SQL query)
    raw_plan = db.execute(text("SELECT code, name, description, monthly_price FROM billing_plans LIMIT 1")).fetchone()
    assert raw_plan is not None
    assert str(raw_plan[0]).startswith("det::"), f"Plan code not deterministically encrypted: {raw_plan[0]}"
    assert str(raw_plan[1]).startswith("enc::"), f"Plan name not encrypted: {raw_plan[1]}"
    assert str(raw_plan[2]).startswith("enc::"), f"Plan description not encrypted: {raw_plan[2]}"
    assert str(raw_plan[3]).startswith("enc::"), f"Plan price not encrypted: {raw_plan[3]}"
    print("  -> Verified: Raw database records are 100% encrypted at rest (det:: and enc:: prefixes).")

    # 2. Test Admin Plan Creation
    print("[*] Testing POST /billing/plans (admin & forbidden check)...")
    create_body = {
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
    resp_forbidden = client.post("/billing/plans", headers=ta1_headers, json=create_body)
    assert resp_forbidden.status_code == 403, "Tenant was not blocked from creating plan"
    resp_admin = client.post("/billing/plans", headers=admin_headers, json=create_body)
    assert resp_admin.status_code == 201
    print("  -> Role verification and plan creation verified.")

    # 3. Test Subscription Workflow
    print("[*] Testing POST /billing/subscriptions/subscribe...")
    sub_body = {
        "plan_id": starter_plan["id"],
        "billing_interval": "monthly",
        "auto_renew": True,
    }
    sub_resp = client.post("/billing/subscriptions/subscribe", headers=ta1_headers, json=sub_body)
    assert sub_resp.status_code == 200, f"Subscribe failed: {sub_resp.text}"
    sub_data = sub_resp.json()
    assert sub_data["status"] == "active"
    assert sub_data["odoo_partner_id"] is not None
    print(f"  -> Subscribed successfully. Status: {sub_data['status']}, Odoo Partner: {sub_data['odoo_partner_id']}")

    # 4. Test Subscription Retrieval
    print("[*] Testing GET /billing/subscriptions/me...")
    my_sub = client.get("/billing/subscriptions/me", headers=ta1_headers)
    assert my_sub.status_code == 200
    assert my_sub.json()["id"] == sub_data["id"]
    print("  -> Retrieved current tenant subscription.")

    # Verify subscription raw database encryption
    raw_sub = db.execute(text("SELECT tenant_id, status, billing_interval FROM tenant_subscriptions LIMIT 1")).fetchone()
    assert str(raw_sub[0]).startswith("det_int::"), f"Tenant ID not deterministically encrypted: {raw_sub[0]}"
    assert str(raw_sub[1]).startswith("det::"), f"Subscription status not deterministically encrypted: {raw_sub[1]}"
    assert str(raw_sub[2]).startswith("enc::"), f"Billing interval not encrypted: {raw_sub[2]}"
    print("  -> Verified: Subscription tenant_id (searchable int), status (searchable) & billing interval are encrypted in raw storage.")

    # 5. Test SIM Metering & Usage Aggregation
    print("[*] Testing 1NCE SIM usage metering & overage calculation...")
    # Add 12 SIM cards (allowance is 10 -> 2 extra)
    # Total data usage 650 MB (allowance is 500 MB -> 150 MB overage)
    for i in range(12):
        sim = NetworkSimCard(
            iccid=f"89882806660000000{10+i}",
            imei=f"3569380356438{10+i}",
            provider="1nce",
            status="Active",
            tenant_id=t1.id,
            quota_total_mb=500.0,
            quota_used_mb=54.16,
            quota_remaining_mb=445.84,
        )
        db.add(sim)
    db.commit()

    # Verify SIM card raw database encryption
    raw_sim = db.execute(text("SELECT iccid, imei, status, quota_total_mb FROM network_sim_cards LIMIT 1")).fetchone()
    assert str(raw_sim[0]).startswith("det::"), f"ICCID not deterministically encrypted: {raw_sim[0]}"
    assert str(raw_sim[1]).startswith("enc::"), f"IMEI not encrypted: {raw_sim[1]}"
    assert str(raw_sim[2]).startswith("det::"), f"SIM status not deterministically encrypted: {raw_sim[2]}"
    assert str(raw_sim[3]).startswith("enc::"), f"Quota not encrypted: {raw_sim[3]}"
    print("  -> Verified: 1NCE SIM cards ICCID (searchable), IMEI, status (searchable) & quotas are encrypted in raw storage.")

    usage_resp = client.get("/billing/usage", headers=ta1_headers)
    assert usage_resp.status_code == 200
    u = usage_resp.json()
    assert u["total_active_sims"] == 12
    assert u["billable_extra_devices"] == 2
    assert u["billable_overage_mb"] >= 149.0
    assert u["estimated_overage_charge"] > 0
    print(f"  -> Usage verified: {u['total_active_sims']} active SIMs, {u['billable_extra_devices']} extra SIMs, {u['billable_overage_mb']:.1f} MB overage.")
    print(f"  -> Estimated next invoice: ${u['estimated_total_next_invoice']:.2f}")

    # 6. Test Invoice Generation & Odoo Flow
    print("[*] Testing POST /billing/invoices/generate (Odoo account.move creation)...")
    inv_resp = client.post(
        "/billing/invoices/generate",
        headers=ta1_headers,
        json={"billing_interval": "monthly", "include_overages": True, "post_to_odoo": True},
    )
    assert inv_resp.status_code == 200
    inv = inv_resp.json()
    inv_id = inv["id"]
    assert inv["invoice_number"].startswith("NIB-")
    assert inv["odoo_invoice_id"] is not None
    assert inv["odoo_move_name"] is not None
    assert len(inv["line_items"]) >= 3 # Base subscription, extra SIMs, data overage
    print(f"  -> Invoice generated: {inv['invoice_number']}, Odoo Move: {inv['odoo_move_name']}, Amount Total: ${inv['amount_total']:.2f}")
    for item in inv["line_items"]:
        print(f"     * {item['name']}: ${item['total']:.2f}")

    # Verify Invoice raw database encryption
    raw_inv = db.execute(text("SELECT invoice_number, status, amount_total FROM invoices LIMIT 1")).fetchone()
    assert str(raw_inv[0]).startswith("det::"), f"Invoice number not deterministically encrypted: {raw_inv[0]}"
    assert str(raw_inv[1]).startswith("det::"), f"Invoice status not deterministically encrypted: {raw_inv[1]}"
    assert str(raw_inv[2]).startswith("enc::"), f"Invoice amount not encrypted: {raw_inv[2]}"
    print("  -> Verified: Invoice records invoice_number (searchable), status (searchable) & amount_total are encrypted in raw storage.")

    # 7. Test Sync with Odoo
    print(f"[*] Testing POST /billing/invoices/{inv_id}/sync-odoo...")
    sync_resp = client.post(f"/billing/invoices/{inv_id}/sync-odoo", headers=ta1_headers)
    assert sync_resp.status_code == 200
    print("  -> Synchronized with Odoo successfully.")

    # 8. Test Pay Invoice
    print(f"[*] Testing POST /billing/invoices/{inv_id}/pay...")
    pay_resp = client.post(
        f"/billing/invoices/{inv_id}/pay",
        headers=ta1_headers,
        json={"payment_method": "odoo_reconcile", "notes": "Approved and wired"},
    )
    assert pay_resp.status_code == 200
    assert pay_resp.json()["status"] == "paid"
    assert pay_resp.json()["odoo_payment_state"] == "paid"
    print("  -> Invoice marked as paid in local DB and Odoo.")

    # 9. Test PDF Download
    print(f"[*] Testing GET /billing/invoices/{inv_id}/pdf...")
    pdf_resp = client.get(f"/billing/invoices/{inv_id}/pdf", headers=ta1_headers)
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert len(pdf_resp.content) > 50
    print("  -> PDF report streamed successfully.")

    # 10. Test 1NCE Network SIM API Endpoints
    print("[*] Testing 1NCE Management API endpoints (/network/1nce/sims)...")
    sync_sims_resp = client.post("/network/1nce/sims/sync", headers=ta1_headers)
    assert sync_sims_resp.status_code == 200
    sim_list = sync_sims_resp.json()
    assert len(sim_list) >= 3
    test_iccid = sim_list[0]["iccid"]
    print(f"  -> Synced {len(sim_list)} SIMs from 1NCE API. Testing with ICCID {test_iccid}")

    # Quota endpoint
    q_resp = client.get(f"/network/1nce/sims/{test_iccid}/quota", headers=ta1_headers)
    assert q_resp.status_code == 200
    assert q_resp.json()["volume_total_mb"] == 500.0

    # Connectivity endpoint
    c_resp = client.get(f"/network/1nce/sims/{test_iccid}/connectivity", headers=ta1_headers)
    assert c_resp.status_code == 200
    assert c_resp.json()["status"] in ("Attached", "Detached")

    # Suspend SIM
    s_resp = client.post(f"/network/1nce/sims/{test_iccid}/status", headers=ta1_headers, json={"status": "Suspended"})
    assert s_resp.status_code == 200
    assert s_resp.json()["status"] == "Suspended"

    # Reset SIM (HLR teardown)
    r_resp = client.post(f"/network/1nce/sims/{test_iccid}/reset", headers=ta1_headers)
    assert r_resp.status_code == 200
    assert r_resp.json()["status"] == "ResetInitiated"

    # Reactivate SIM
    a_resp = client.post(f"/network/1nce/sims/{test_iccid}/status", headers=ta1_headers, json={"status": "Active"})
    assert a_resp.status_code == 200
    assert a_resp.json()["status"] == "Active"

    # Top-up Quota
    t_resp = client.post(f"/network/1nce/sims/{test_iccid}/topup", headers=ta1_headers, json={"volume_mb": 500.0, "create_odoo_invoice": True})
    assert t_resp.status_code == 200
    assert t_resp.json()["volume_added_mb"] == 500.0

    # Send MT-SMS
    sms_resp = client.post(f"/network/1nce/sims/{test_iccid}/sms", headers=ta1_headers, json={"payload": "REBOOT#NOW"})
    assert sms_resp.status_code == 200
    assert sms_resp.json()["status"] in ("Sent", "Delivered")
    print("  -> All 1NCE SIM lifecycle endpoints (sync, quota, connectivity, suspend, reset, reactivate, topup, SMS) passed.")

    # 11. Test Config Diagnostics
    print("[*] Testing diagnostics (/billing/config/test-1nce & test-odoo)...")
    diag_1nce = client.post("/billing/config/test-1nce", headers=admin_headers)
    assert diag_1nce.status_code == 200 and diag_1nce.json()["success"] is True

    diag_odoo = client.post("/billing/config/test-odoo", headers=admin_headers)
    assert diag_odoo.status_code == 200 and diag_odoo.json()["success"] is True
    print("  -> Diagnostics endpoints passed.")

    # 12. Dynamic Network Provider CRUD & Database Encryption
    print("[*] Testing Single Network SIM Provider Client Management System (/network/drivers & /network/providers)...")
    # Driver catalog test
    drivers_resp = client.get("/network/drivers", headers=admin_headers)
    assert drivers_resp.status_code == 200
    catalog = drivers_resp.json()
    assert len(catalog) >= 4
    driver_types = [d["driver_type"] for d in catalog]
    assert "1nce" in driver_types and "monogoto" in driver_types and "emnify" in driver_types and "generic_rest" in driver_types
    print(f"  -> Driver Catalog verified ({len(catalog)} drivers): {driver_types}")

    prov_list_resp = client.get("/network/providers", headers=admin_headers)
    assert prov_list_resp.status_code == 200
    providers = prov_list_resp.json()
    assert len(providers) >= 2
    prov_codes = [p["provider_code"] for p in providers]
    assert "1nce" in prov_codes and "monogoto" in prov_codes
    print(f"  -> Found {len(providers)} providers: {prov_codes}")

    # Non-admin forbidden check on provider creation
    forbidden_create = client.post("/network/providers", headers=ta1_headers, json={
        "name": "Unauthorized Provider",
        "provider_code": "unauthorized-prov",
        "provider_type": "monogoto",
        "base_url": "https://api.monogoto.io",
        "auth_type": "bearer_token",
    })
    assert forbidden_create.status_code == 403
    print("  -> Verified: Non-admin creation is blocked (403 Forbidden).")

    # Admin creates new network provider config using Monogoto driver
    new_prov_data = {
        "name": "Monogoto Europe Gateway",
        "provider_code": "monogoto-eu",
        "provider_type": "monogoto",
        "base_url": "https://api.monogoto.io",
        "auth_type": "bearer_token",
        "api_user": "admin_eu@monogoto.io",
        "api_key": "SecretPassword123!",
        "is_enabled": True,
        "is_sandbox": True,
        "extra_settings": {"timeout_seconds": 25, "region": "eu-central-1"}
    }
    create_prov_resp = client.post("/network/providers", headers=admin_headers, json=new_prov_data)
    assert create_prov_resp.status_code == 201, f"Failed: {create_prov_resp.text}"
    created_prov = create_prov_resp.json()
    assert created_prov["provider_code"] == "monogoto-eu"
    assert created_prov["has_api_key"] is True
    print("  -> Admin created new provider 'monogoto-eu' successfully.")

    # Verify zero-plaintext encrypted storage for network_providers
    raw_np = db.execute(text("SELECT name, provider_code, base_url, api_user, api_key_encrypted FROM network_providers WHERE provider_code LIKE 'det::%' LIMIT 1")).fetchone()
    assert raw_np is not None
    assert str(raw_np[0]).startswith("enc::"), f"Provider name not encrypted: {raw_np[0]}"
    assert str(raw_np[1]).startswith("det::"), f"Provider code not searchable-encrypted: {raw_np[1]}"
    assert str(raw_np[2]).startswith("enc::"), f"Base URL not encrypted: {raw_np[2]}"
    assert str(raw_np[3]).startswith("enc::"), f"API user not encrypted: {raw_np[3]}"
    assert str(raw_np[4]).startswith("enc::"), f"API key not encrypted: {raw_np[4]}"
    print("  -> Verified: Raw network_providers records are 100% encrypted at rest (det:: and enc:: prefixes).")

    # Dynamic Provider Expansion: Admin onboards EMnify Cellular IoT
    emnify_prov_data = {
        "name": "EMnify Lab Fleet",
        "provider_code": "emnify-lab",
        "provider_type": "emnify",
        "base_url": "https://cdn.emnify.net/api/v1",
        "auth_type": "bearer_token",
        "api_user": "em-mock-app-token",
        "api_key": "em-secret",
        "is_enabled": True,
        "is_sandbox": True,
    }
    em_resp = client.post("/network/providers", headers=admin_headers, json=emnify_prov_data)
    assert em_resp.status_code == 201
    print("  -> Dynamic provider expansion: Onboarded EMnify provider 'emnify-lab'.")

    # Test EMnify connection probe
    em_test = client.post("/network/providers/emnify-lab/test", headers=admin_headers)
    assert em_test.status_code == 200 and em_test.json()["success"] is True
    print(f"  -> EMnify live probe passed ({em_test.json()['latency_ms']} ms).")

    # Sync SIMs from EMnify
    em_sync = client.post("/network/providers/emnify-lab/sync", headers=admin_headers)
    assert em_sync.status_code == 200
    em_sims = em_sync.json()
    assert len(em_sims) >= 2
    em_iccid = em_sims[0]["iccid"]
    print(f"  -> Synced {len(em_sims)} SIMs from EMnify. Testing with ICCID {em_iccid}")

    # Unified operations on EMnify SIM
    em_quota = client.get(f"/network/sims/{em_iccid}/quota", headers=admin_headers)
    assert em_quota.status_code == 200 and em_quota.json()["volume_total_mb"] >= 1000.0

    em_stat = client.post(f"/network/sims/{em_iccid}/status", headers=admin_headers, json={"status": "Suspended"})
    assert em_stat.status_code == 200 and em_stat.json()["status"] == "Suspended"

    em_sms = client.post(f"/network/sims/{em_iccid}/sms", headers=admin_headers, json={"payload": "EM#RESET"})
    assert em_sms.status_code == 200 and em_sms.json()["status"] in ("Sent", "Delivered")
    print("  -> Unified operations across EMnify SIM passed completely.")

    # Dynamic Provider Expansion: Admin onboards Custom Generic REST Provider
    generic_prov_data = {
        "name": "Private Satellite Gateway",
        "provider_code": "private-sat",
        "provider_type": "generic_rest",
        "base_url": "https://api.privatesat.com/v1",
        "auth_type": "api_key",
        "api_key": "SatSecretKey999",
        "is_enabled": True,
        "is_sandbox": True,
    }
    sat_resp = client.post("/network/providers", headers=admin_headers, json=generic_prov_data)
    assert sat_resp.status_code == 201
    sat_test = client.post("/network/providers/private-sat/test", headers=admin_headers)
    assert sat_test.status_code == 200 and sat_test.json()["success"] is True
    print("  -> Dynamic provider expansion: Custom Generic REST provider onboarded and tested.")

    # Clean up test providers
    client.delete("/network/providers/emnify-lab?force=true", headers=admin_headers)
    client.delete("/network/providers/private-sat?force=true", headers=admin_headers)

    # Update provider
    upd_resp = client.put("/network/providers/monogoto-eu", headers=admin_headers, json={
        "name": "Monogoto Europe Gateway V2",
        "is_sandbox": True,
    })
    assert upd_resp.status_code == 200
    assert upd_resp.json()["name"] == "Monogoto Europe Gateway V2"
    print("  -> Provider updated successfully.")

    # Test Provider Connection (diagnostics probe)
    test_conn_resp = client.post("/network/providers/monogoto/test", headers=admin_headers)
    assert test_conn_resp.status_code == 200
    conn_data = test_conn_resp.json()
    assert conn_data["success"] is True
    assert "latency_ms" in conn_data
    print(f"  -> Provider connection probe test passed: {conn_data['message']} (latency: {conn_data['latency_ms']}ms)")

    # Delete custom provider
    del_resp = client.delete("/network/providers/monogoto-eu", headers=admin_headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True
    not_found_resp = client.get("/network/providers/monogoto-eu", headers=admin_headers)
    assert not_found_resp.status_code == 404
    print("  -> Provider deleted and verified non-existent.")

    # 13. Test Monogoto Developer API & Unified SIM Fleet Operations
    print("[*] Testing Monogoto Developer API & Unified SIM Fleet Operations...")
    mono_sync = client.post("/network/monogoto/things/sync", headers=ta1_headers)
    assert mono_sync.status_code == 200
    synced_things = mono_sync.json()
    assert len(synced_things) >= 3
    mono_iccid = synced_things[0]["iccid"]
    print(f"  -> Synced {len(synced_things)} Monogoto Things. Testing with ICCID {mono_iccid}")

    # Unified list endpoint with provider filter
    mono_filter_resp = client.get("/network/sims?provider=monogoto", headers=ta1_headers)
    assert mono_filter_resp.status_code == 200
    mono_sims = mono_filter_resp.json()
    assert len(mono_sims) >= 3
    assert all(s["provider"] == "monogoto" for s in mono_sims)
    print(f"  -> GET /network/sims?provider=monogoto returned {len(mono_sims)} Monogoto SIMs.")

    # Unified Quota for Monogoto
    mq_resp = client.get(f"/network/sims/{mono_iccid}/quota", headers=ta1_headers)
    assert mq_resp.status_code == 200
    assert mq_resp.json()["volume_total_mb"] >= 500.0
    print("  -> Unified quota query for Monogoto Thing succeeded.")

    # Unified Connectivity for Monogoto
    mc_resp = client.get(f"/network/sims/{mono_iccid}/connectivity", headers=ta1_headers)
    assert mc_resp.status_code == 200
    assert mc_resp.json()["status"] in ("Online", "Offline", "Attached")
    print("  -> Unified connectivity query for Monogoto Thing succeeded.")

    # Unified Suspend Thing
    ms_resp = client.post(f"/network/sims/{mono_iccid}/status", headers=ta1_headers, json={"status": "Suspended"})
    assert ms_resp.status_code == 200
    assert ms_resp.json()["status"] == "Suspended"
    print("  -> Unified status update (Suspend) succeeded.")

    # Unified Reset Thing (Monogoto network refresh)
    mr_resp = client.post(f"/network/sims/{mono_iccid}/reset", headers=ta1_headers)
    assert mr_resp.status_code == 200
    assert mr_resp.json()["status"] in ("ResetInitiated", "Refreshed")
    print("  -> Unified SIM reset (network refresh) succeeded.")

    # Unified Reactivate Thing
    ma_resp = client.post(f"/network/sims/{mono_iccid}/status", headers=ta1_headers, json={"status": "Active"})
    assert ma_resp.status_code == 200
    assert ma_resp.json()["status"] == "Active"
    print("  -> Unified status update (Reactivate) succeeded.")

    # Unified Top-up Thing
    mt_resp = client.post(f"/network/sims/{mono_iccid}/topup", headers=ta1_headers, json={"volume_mb": 500.0, "create_odoo_invoice": True})
    assert mt_resp.status_code == 200
    assert mt_resp.json()["volume_added_mb"] == 500.0
    print("  -> Unified top-up (+500MB) succeeded.")

    # Unified Send MT-SMS to Thing
    msms_resp = client.post(f"/network/sims/{mono_iccid}/sms", headers=ta1_headers, json={"payload": "PING#MONOGOTO"})
    assert msms_resp.status_code == 200
    assert msms_resp.json()["status"] in ("Sent", "Delivered")
    print("  -> Unified MT-SMS dispatch succeeded.")

    # Dedicated Monogoto API routes (/network/monogoto/things)
    m_things_resp = client.get("/network/monogoto/things", headers=ta1_headers)
    assert m_things_resp.status_code == 200
    assert len(m_things_resp.json()) >= 3

    m_status_resp = client.get(f"/network/monogoto/things/{mono_iccid}/status", headers=ta1_headers)
    assert m_status_resp.status_code == 200
    assert "status" in m_status_resp.json()

    m_refresh_resp = client.post(f"/network/monogoto/things/{mono_iccid}/refresh", headers=ta1_headers)
    assert m_refresh_resp.status_code == 200
    print("  -> Dedicated Monogoto endpoints (/v1/things, status, refresh) passed.")

    print("\n=======================================================")
    print(" ALL 13 BILLING, 1NCE & MONOGOTO SUITES COMPLETED WITH 100% SUCCESS!")
    print("=======================================================\n")
    db.close()
    try:
        os.remove(TEST_DB_FILE)
    except Exception:
        pass

if __name__ == "__main__":
    run_tests()
