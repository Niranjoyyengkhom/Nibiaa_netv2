import os
import sys
import pytest
from fastapi.testclient import TestClient

service_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if service_dir not in sys.path:
    sys.path.insert(0, service_dir)

from app.main import app
from app.database import Base, engine, SessionLocal
from app.services.seed_service import seed_iam_database
from app.services.user_service import user_service, hash_password
from app.models.user import User
from app.models.abac_policy import ABACPolicy

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_iam_database(db)
        admin = db.query(User).filter(User.role == "admin").first()
        if not admin:
            admin = User(
                name="admin_test",
                email="admintest@nibiaa.com",
                role="admin",
                password_hash=hash_password("Admin@123"),
                is_active=True,
            )
            db.add(admin)
            db.commit()


def get_admin_token():
    res = client.post("/auth/login", json={"username": "Nibiaa", "password": "Password123!"})
    if res.status_code != 200:
        res = client.post("/auth/login", json={"username": "admin", "password": "Password123!"})
    if res.status_code != 200:
        with SessionLocal() as db:
            admin = db.query(User).filter(User.role == "admin").first()
            if admin:
                admin.password_hash = hash_password("Admin@123")
                db.commit()
        res = client.post("/auth/login", json={"username": "admin", "password": "Admin@123"})
    return res.json().get("access_token")


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "nibiaanet-iam-service"
    assert data["status"] in ("ok", "degraded")


def test_service_info():
    response = client.get("/info")
    assert response.status_code == 200
    data = response.json()
    assert "capabilities" in data
    assert len(data["capabilities"]) > 0


def test_service_stats():
    response = client.get("/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_users" in data
    assert "total_roles" in data


def test_permissions_list():
    token = get_admin_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = client.get("/permissions/", headers=headers)
    assert response.status_code == 200
    perms = response.json()
    assert len(perms) > 0
    codes = [p["code"] for p in perms]
    assert "devices:read" in codes
    assert "telemetry:read" in codes


def test_permissions_grouped_categories():
    token = get_admin_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = client.get("/permissions/categories", headers=headers)
    assert response.status_code == 200
    cats = response.json()
    assert len(cats) > 0
    cat_names = [c["category"] for c in cats]
    assert "devices" in cat_names


def test_roles_crud_and_inheritance():
    token = get_admin_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    base_role = client.post("/roles/", json={
        "name": "Test Base Device Viewer",
        "code": "ROLE_TEST_VIEWER",
        "description": "Base viewer role for testing",
        "permission_codes": ["devices:read", "telemetry:read"]
    }, headers=headers)
    assert base_role.status_code == 200
    base_id = base_role.json()["id"]

    child_role = client.post("/roles/", json={
        "name": "Test Child Device Manager",
        "code": "ROLE_TEST_MGR",
        "description": "Inherits from viewer and adds create/update",
        "parent_role_id": base_id,
        "permission_codes": ["devices:create", "devices:update"]
    }, headers=headers)
    assert child_role.status_code == 200
    child_id = child_role.json()["id"]

    child_perms_res = client.get(f"/roles/{child_id}/permissions", headers=headers)
    assert child_perms_res.status_code == 200
    child_perms = child_perms_res.json()
    assert "devices:read" in child_perms
    assert "telemetry:read" in child_perms
    assert "devices:create" in child_perms
    assert "devices:update" in child_perms

    client.delete(f"/roles/{child_id}", headers=headers)
    client.delete(f"/roles/{base_id}", headers=headers)


def test_attribute_definitions_and_values():
    token = get_admin_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    def_res = client.post("/attributes/definitions", json={
        "key": "test_max_devices",
        "name": "Max Devices Allowed",
        "description": "Maximum registered devices limit",
        "entity_type": "user",
        "data_type": "number",
        "is_required": False
    }, headers=headers)
    assert def_res.status_code in (200, 409)
    if def_res.status_code == 200:
        def_id = def_res.json()["id"]
    else:
        defs = client.get("/attributes/definitions", headers=headers).json()
        def_id = [d["id"] for d in defs if d["key"] == "test_max_devices"][0]

    assign_res = client.post("/attributes/entities/user/1", json={
        "key": "test_max_devices",
        "value": 50
    }, headers=headers)
    assert assign_res.status_code == 200
    assert assign_res.json()["value"] == 50.0

    get_res = client.get("/attributes/entities/user/1", headers=headers)
    assert get_res.status_code == 200
    attrs = get_res.json()["attributes"]
    assert attrs.get("test_max_devices") == 50.0

    client.delete(f"/attributes/definitions/{def_id}", headers=headers)


def test_user_lifecycle_and_introspection():
    token = get_admin_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    # 1. Create new user with attributes
    user_payload = {
        "email": "test.technician@nibiaa.com",
        "name": "Test Technician",
        "role": "collaborator",
        "password": "Password123!",
        "attributes": {
            "department": "operations",
            "clearance_level": 3,
            "shift": "morning"
        }
    }
    create_res = client.post("/users/", json=user_payload, headers=headers)
    assert create_res.status_code in (200, 409)
    if create_res.status_code == 200:
        user_data = create_res.json()
        user_id = user_data["id"]
    else:
        users = client.get("/users/?search=test.technician", headers=headers).json()
        user_id = users[0]["id"]

    # 2. Login as the newly created user
    login_res = client.post("/auth/login", json={
        "username": "test.technician@nibiaa.com",
        "password": "Password123!"
    })
    assert login_res.status_code == 200
    tech_token = login_res.json()["access_token"]

    # 3. Introspect the token
    intro_res = client.post("/auth/introspect", json={"token": tech_token})
    assert intro_res.status_code == 200
    intro_data = intro_res.json()
    assert intro_data["active"] is True
    assert intro_data["email"] == "test.technician@nibiaa.com"
    assert intro_data["attributes"]["clearance_level"] == 3

    # 4. Revoke User Access
    revoke_res = client.post(f"/users/{user_id}/revoke", headers=headers)
    assert revoke_res.status_code == 200
    assert revoke_res.json()["is_active"] is False

    # 5. Token introspection should now show inactive
    intro_revoked = client.post("/auth/introspect", json={"token": tech_token})
    assert intro_revoked.json()["active"] is False

    # 6. Restore User Access
    restore_res = client.post(f"/users/{user_id}/restore", headers=headers)
    assert restore_res.status_code == 200
    assert restore_res.json()["is_active"] is True

    # 7. Clean up
    client.delete(f"/users/{user_id}", headers=headers)


def test_abac_evaluation_engine():
    eval_req = {
        "username": "Nibiaa",
        "action": "devices:command",
        "resource_type": "device",
        "resource_id": "SAT-TEST-99",
        "resource_attributes": {"region": "GLOBAL"},
        "context_attributes": {"ip": "127.0.0.1"}
    }
    response = client.post("/abac/evaluate", json=eval_req)
    assert response.status_code == 200
    decision = response.json()
    assert "allowed" in decision
    assert "effect" in decision
    assert "evaluation_time_ms" in decision
    assert decision["allowed"] is True


def test_abac_custom_policy_creation_and_deny_precedence():
    token = get_admin_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    # Create explicit DENY policy for maintenance window
    policy_res = client.post("/abac/policies", json={
        "name": "Test Maintenance Blackout Denial",
        "description": "Deny all device command operations during emergency blackout",
        "effect": "DENY",
        "priority": 200,
        "target_actions": ["devices:command"],
        "target_resource_types": ["device"],
        "context_conditions": {},
        "environment_conditions": {"blackout": {"$eq": True}},
        "is_active": True
    }, headers=headers)
    assert policy_res.status_code == 200
    pol_id = policy_res.json()["id"]

    # Evaluate without blackout -> should be allowed
    eval_res1 = client.post("/abac/evaluate", json={
        "username": "Nibiaa",
        "action": "devices:command",
        "resource_type": "device",
        "context_attributes": {"blackout": False}
    })
    assert eval_res1.json()["allowed"] is True

    # Evaluate WITH blackout -> MUST be DENIED!
    eval_res2 = client.post("/abac/evaluate", json={
        "username": "Nibiaa",
        "action": "devices:command",
        "resource_type": "device",
        "context_attributes": {"blackout": True}
    })
    assert eval_res2.json()["allowed"] is False
    assert eval_res2.json()["effect"] == "DENY"

    # Clean up policy
    client.delete(f"/abac/policies/{pol_id}", headers=headers)
