"""
RBAC matrix: admin / owner / collaborator.

The main promise: when an owner gives a collaborator a function
(directly, or through a collaborator role), the collaborator can use
it on the very next request, and loses it as soon as it is removed.

Seed (see conftest.py): owner1 + collaborator1 in Tenant 1 (DEVICE001,
App 1), owner2 in Tenant 2 (DEVICE002, App 2), platform admin.
"""

from app.seed_telemetry import seed_telemetry

from conftest import PASSWORD, headers


NO_FUNCTIONS = {
    "manage_devices": False,
    "create_devices": False,
    "delete_devices": False,
    "manage_application": False,
    "read_application_traffic": False,
    "create_decoder": False,
    "manage_decoder": False,
}

DECODER_FIELDS = [
    {"field_name": "temperature", "byte_offset": 0, "byte_length": 2, "data_type": "int16",
     "scale_factor": 0.01, "unit": "°C"},
]


def give(client, owner, collaborator, **functions):
    response = client.put(
        f"/collaborators/{collaborator}/permissions",
        json={**NO_FUNCTIONS, **functions},
        headers=headers(owner)
    )
    assert response.status_code == 200, response.text
    return response.json()


def new_device(client, user_id, device_id="DEVICE100", application_id=1):
    return client.post(
        "/devices/",
        json={
            "device_id": device_id,
            "name": "New device",
            "device_type": "sensor",
            "application_id": application_id,
        },
        headers=headers(user_id)
    )


def login(client, name):
    return client.post("/auth/login", json={"name": name, "password": PASSWORD})


# --------------------------------
# Owner -> collaborator functions
# --------------------------------

def test_collaborator_without_functions_is_refused_everywhere(client, seed):
    collaborator = headers(seed["collaborator1"])

    assert client.get("/devices/", headers=collaborator).status_code == 403
    assert new_device(client, seed["collaborator1"]).status_code == 403
    assert client.delete("/devices/DEVICE001", headers=collaborator).status_code == 403
    assert client.get("/applications/", headers=collaborator).status_code == 403
    assert client.get("/telemetry/", headers=collaborator).status_code == 403
    assert client.get("/decode-schemas/", headers=collaborator).status_code == 403
    assert client.get("/devices/DEVICE001/configuration", headers=collaborator).status_code == 403

    # The refusal names the missing function
    detail = client.get("/devices/", headers=collaborator).json()["detail"]
    assert "Manage Devices" in detail


def test_device_functions_take_effect_immediately(client, seed):
    owner, collaborator = seed["owner1"], seed["collaborator1"]
    as_collaborator = headers(collaborator)

    # Manage Devices: view + update + remote configuration
    give(client, owner, collaborator, manage_devices=True)

    devices = client.get("/devices/", headers=as_collaborator)
    assert devices.status_code == 200
    assert [device["device_id"] for device in devices.json()] == ["DEVICE001"]

    update = client.put(
        "/devices/DEVICE001",
        json={"name": "Renamed", "device_type": "sensor", "application_id": 1},
        headers=as_collaborator
    )
    assert update.status_code == 200, update.text
    assert update.json()["name"] == "Renamed"

    configuration = client.put(
        "/devices/DEVICE001/configuration",
        json={"wake_frequency_per_day": 6},
        headers=as_collaborator
    )
    assert configuration.status_code == 200, configuration.text

    # Still another organization's device is not found
    assert client.get("/devices/DEVICE002", headers=as_collaborator).status_code == 404

    # ... but not create or delete
    assert new_device(client, collaborator).status_code == 403
    assert client.delete("/devices/DEVICE001", headers=as_collaborator).status_code == 403

    # Create Devices
    give(client, owner, collaborator, manage_devices=True, create_devices=True)
    created = new_device(client, collaborator)
    assert created.status_code == 200, created.text
    assert created.json()["tenant_id"] == 1

    # Another organization's application is refused
    assert new_device(client, collaborator, "DEVICE101", application_id=2).status_code == 403

    # Delete Devices
    give(client, owner, collaborator, manage_devices=True, delete_devices=True)
    assert client.delete("/devices/DEVICE100", headers=as_collaborator).status_code == 200

    # Removing the functions takes effect on the next request
    give(client, owner, collaborator)
    assert client.get("/devices/", headers=as_collaborator).status_code == 403


def test_application_functions(client, seed):
    owner, collaborator = seed["owner1"], seed["collaborator1"]
    as_collaborator = headers(collaborator)

    # Create Devices alone lets the collaborator see the applications
    # (to pick one), but not change them
    give(client, owner, collaborator, create_devices=True)
    assert [app["id"] for app in client.get("/applications/", headers=as_collaborator).json()] == [1]

    rename = {"name": "Renamed app", "decode_schema_id": None}
    assert client.put("/applications/1", json=rename, headers=as_collaborator).status_code == 403

    # Manage Application
    give(client, owner, collaborator, manage_application=True)
    response = client.put("/applications/1", json=rename, headers=as_collaborator)
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Renamed app"

    # Another organization's application is not found
    assert client.put("/applications/2", json=rename, headers=as_collaborator).status_code == 404

    # Creating and deleting applications stays with owners
    assert client.post(
        "/applications/",
        json={"name": "Nope"},
        headers=as_collaborator
    ).status_code == 403
    assert client.delete("/applications/1", headers=as_collaborator).status_code == 403


def test_read_application_traffic(client, seed, db):
    owner, collaborator = seed["owner1"], seed["collaborator1"]
    as_collaborator = headers(collaborator)
    seed_telemetry(db)

    assert client.get("/devices/DEVICE001/telemetry", headers=as_collaborator).status_code == 403

    give(client, owner, collaborator, read_application_traffic=True)

    device_traffic = client.get("/devices/DEVICE001/telemetry", headers=as_collaborator)
    assert device_traffic.status_code == 200
    assert len(device_traffic.json()) > 0

    fleet = client.get("/telemetry/", headers=as_collaborator).json()
    assert {row["device_id"] for row in fleet} == {"DEVICE001"}

    # Reading traffic does not allow changing devices
    assert client.put(
        "/devices/DEVICE001",
        json={"name": "x", "device_type": "sensor", "application_id": 1},
        headers=as_collaborator
    ).status_code == 403


def test_decoder_functions(client, seed):
    owner, collaborator = seed["owner1"], seed["collaborator1"]
    as_collaborator = headers(collaborator)

    create = {"name": "collab_decoder", "fields": DECODER_FIELDS}

    assert client.post("/decode-schemas/", json=create, headers=as_collaborator).status_code == 403

    # Create Decoder
    give(client, owner, collaborator, create_decoder=True)
    created = client.post("/decode-schemas/", json=create, headers=as_collaborator)
    assert created.status_code == 200, created.text
    decoder = created.json()
    assert decoder["tenant_id"] == 1

    # ... it can be seen and tested, but not activated or deleted
    assert client.get("/decode-schemas/", headers=as_collaborator).status_code == 200
    test = client.post(
        f"/decode-schemas/{decoder['id']}/test",
        json={"payload_hex": "09c4"},
        headers=as_collaborator
    )
    assert test.json()["decoded"] == {"temperature": 25.0}
    assert client.post(
        f"/decode-schemas/{decoder['id']}/activate",
        json={},
        headers=as_collaborator
    ).status_code == 403

    # Manage Decoder
    give(client, owner, collaborator, manage_decoder=True)
    assert client.post(
        f"/decode-schemas/{decoder['id']}/activate",
        json={},
        headers=as_collaborator
    ).status_code == 200
    assert client.post("/decode-schemas/", json=create, headers=as_collaborator).status_code == 403


# --------------------------------
# Collaborator roles (admin) and role assignment (owner)
# --------------------------------

def test_collaborator_roles(client, seed):
    admin, owner, collaborator = seed["admin"], seed["owner1"], seed["collaborator1"]

    role_body = {
        "name": "Field Technician",
        "description": "Installs and maintains devices",
        **NO_FUNCTIONS,
        "manage_devices": True,
        "create_devices": True,
    }

    # Only admins create roles
    assert client.post("/collaborator-roles/", json=role_body, headers=headers(owner)).status_code == 403

    role = client.post("/collaborator-roles/", json=role_body, headers=headers(admin))
    assert role.status_code == 200, role.text
    role = role.json()

    assert client.post(
        "/collaborator-roles/",
        json={**role_body, "name": "field technician"},
        headers=headers(admin)
    ).status_code == 409

    # The owner assigns the role
    assigned = client.put(
        f"/collaborators/{collaborator}/permissions",
        json={"role_id": role["id"]},
        headers=headers(owner)
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["role_name"] == "Field Technician"
    assert assigned.json()["manage_devices"] is True
    assert assigned.json()["read_application_traffic"] is False

    assert client.get("/devices/", headers=headers(collaborator)).status_code == 200
    assert client.get("/telemetry/", headers=headers(collaborator)).status_code == 403

    # Changing the role changes every collaborator that has it
    updated = client.put(
        f"/collaborator-roles/{role['id']}",
        json={**role_body, "read_application_traffic": True},
        headers=headers(admin)
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["collaborator_count"] == 1
    assert client.get("/telemetry/", headers=headers(collaborator)).status_code == 200

    me = client.get("/auth/me", headers=headers(collaborator)).json()
    assert me["collaborator_role_name"] == "Field Technician"
    assert me["permissions"]["read_application_traffic"] is True

    # A role in use cannot be deleted
    assert client.delete(f"/collaborator-roles/{role['id']}", headers=headers(admin)).status_code == 409

    # Back to custom functions
    custom = give(client, owner, collaborator, read_application_traffic=True)
    assert custom["role_id"] is None
    assert custom["manage_devices"] is False
    assert client.get("/devices/", headers=headers(collaborator)).status_code == 403

    assert client.delete(f"/collaborator-roles/{role['id']}", headers=headers(admin)).status_code == 204


def test_who_can_assign_functions(client, seed):
    collaborator = seed["collaborator1"]

    # Owner of another organization: not found
    assert client.put(
        f"/collaborators/{collaborator}/permissions",
        json={"manage_devices": True},
        headers=headers(seed["owner2"])
    ).status_code == 404

    # A collaborator cannot give themselves functions, but can read them
    assert client.put(
        f"/collaborators/{collaborator}/permissions",
        json={"manage_devices": True},
        headers=headers(collaborator)
    ).status_code == 403
    assert client.get(
        f"/collaborators/{collaborator}/permissions",
        headers=headers(collaborator)
    ).status_code == 200

    # Only collaborators have functions
    assert client.put(
        f"/collaborators/{seed['owner1']}/permissions",
        json={},
        headers=headers(seed["admin"])
    ).status_code == 400

    # Admins can assign in every organization
    assert client.put(
        f"/collaborators/{collaborator}/permissions",
        json={"manage_devices": True},
        headers=headers(seed["admin"])
    ).status_code == 200


def test_auth_me(client, seed):
    owner = client.get("/auth/me", headers=headers(seed["owner1"])).json()
    assert owner["tenant_name"] == "Tenant One"
    assert all(owner["permissions"].values())
    assert owner["capabilities"]["manage_users"] is True
    assert owner["capabilities"]["manage_organizations"] is False

    collaborator = client.get("/auth/me", headers=headers(seed["collaborator1"])).json()
    assert not any(collaborator["permissions"].values())
    assert collaborator["capabilities"]["manage_users"] is False

    admin = client.get("/auth/me", headers=headers(seed["admin"])).json()
    assert admin["capabilities"]["manage_connectivity_profiles"] is True


# --------------------------------
# Revoke collaborator / organization access
# --------------------------------

def test_revoke_and_restore_collaborator(client, seed):
    owner, collaborator = seed["owner1"], seed["collaborator1"]

    assert login(client, "collaborator1").status_code == 200

    revoked = client.post(f"/users/{collaborator}/revoke", headers=headers(owner))
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["is_active"] is False

    # Existing tokens stop working, and signing in is refused
    assert client.get("/auth/me", headers=headers(collaborator)).status_code == 401
    assert login(client, "collaborator1").status_code == 403

    assert client.post(f"/users/{collaborator}/restore", headers=headers(owner)).status_code == 200
    assert client.get("/auth/me", headers=headers(collaborator)).status_code == 200

    # Owners revoke collaborators of their own organization only
    assert client.post(f"/users/{seed['owner2']}/revoke", headers=headers(owner)).status_code == 403
    assert client.post(f"/users/{seed['admin']}/revoke", headers=headers(owner)).status_code == 403
    assert client.post(f"/users/{owner}/revoke", headers=headers(owner)).status_code == 400


def test_revoke_and_restore_organization(client, seed):
    admin = seed["admin"]

    assert client.post("/tenants/1/revoke", headers=headers(seed["owner1"])).status_code == 403

    revoked = client.post("/tenants/1/revoke", headers=headers(admin))
    assert revoked.status_code == 200
    assert revoked.json()["is_active"] is False

    assert client.get("/devices/", headers=headers(seed["owner1"])).status_code == 401
    assert login(client, "owner1").status_code == 403

    # Other organizations are not affected
    assert client.get("/devices/", headers=headers(seed["owner2"])).status_code == 200

    assert client.post("/tenants/1/restore", headers=headers(admin)).status_code == 200
    assert client.get("/devices/", headers=headers(seed["owner1"])).status_code == 200


# --------------------------------
# Users and organizations
# --------------------------------

def test_owner_manages_collaborators_only(client, seed):
    owner = headers(seed["owner1"])

    created = client.post(
        "/users/",
        json={"name": "newcollab", "role": "collaborator", "password": "Collab@123"},
        headers=owner
    )
    assert created.status_code == 200, created.text
    assert created.json()["tenant_id"] == 1
    assert created.json()["tenant_name"] == "Tenant One"

    # Names are unique (they are the login)
    assert client.post(
        "/users/",
        json={"name": "NewCollab", "role": "collaborator", "password": "Collab@123"},
        headers=owner
    ).status_code == 409

    assert client.post(
        "/users/",
        json={"name": "newowner", "role": "owner", "password": "Owner@123"},
        headers=owner
    ).status_code == 403

    new_id = created.json()["id"]

    edited = client.put(
        f"/users/{new_id}",
        json={"name": "renamedcollab", "password": "Other@123"},
        headers=owner
    )
    assert edited.status_code == 200

    # Owners cannot change or delete other owners
    assert client.put(
        f"/users/{seed['admin']}",
        json={"name": "hacked"},
        headers=owner
    ).status_code == 403
    assert client.delete(f"/users/{seed['owner2']}", headers=owner).status_code == 403

    # Everyone can change their own profile (with current password verification)
    assert client.put(
        f"/users/{seed['collaborator1']}",
        json={"name": "collaborator1", "password": "Mine@1234", "current_password": PASSWORD},
        headers=headers(seed["collaborator1"])
    ).status_code == 200

    assert client.delete(f"/users/{new_id}", headers=owner).status_code == 200


def test_admin_manages_organizations(client, seed):
    admin = headers(seed["admin"])

    created = client.post(
        "/tenants/",
        json={"name": "Solo", "type": "individual"},
        headers=admin
    ).json()

    renamed = client.put(
        f"/tenants/{created['id']}",
        json={"name": "Solo Farmer", "type": "individual"},
        headers=admin
    )
    assert renamed.json()["name"] == "Solo Farmer"

    # An organization with data cannot be deleted
    assert client.delete("/tenants/1", headers=admin).status_code == 409
    assert client.delete(f"/tenants/{created['id']}", headers=admin).status_code == 204

    # Owners see only their own organization
    own = client.get("/tenants/", headers=headers(seed["owner1"])).json()
    assert [tenant["id"] for tenant in own] == [1]
    assert client.post("/tenants/", json={"name": "x"}, headers=headers(seed["owner1"])).status_code == 403


# --------------------------------
# Connectivity profiles (admin)
# --------------------------------

def test_connectivity_profiles_are_managed_by_admins(client, seed):
    admin = headers(seed["admin"])

    new_profile = {
        "code": "astrocast",
        "name": "Astrocast",
        "connection_type": "NTN",
        "integration_status": "planned",
        "transport": "udp",
        "max_payload_bytes": 160,
    }

    assert client.post(
        "/connectivity-profiles/",
        json=new_profile,
        headers=headers(seed["owner1"])
    ).status_code == 403

    created = client.post("/connectivity-profiles/", json=new_profile, headers=admin)
    assert created.status_code == 200, created.text
    profile = created.json()
    assert profile["enabled"] is True

    assert client.post("/connectivity-profiles/", json=new_profile, headers=admin).status_code == 409

    # Every user sees it
    codes = {
        row["code"]
        for row in client.get("/connectivity-profiles/", headers=headers(seed["collaborator1"])).json()
    }
    assert "astrocast" in codes

    source = client.post(
        f"/connectivity-profiles/{profile['id']}/sources",
        json={"transport": "udp", "identity": "198.51.100.7:5683"},
        headers=admin
    )
    assert source.status_code == 200
    # Stored the way the pipeline looks it up
    assert source.json()["identity"] == "198.51.100.7"

    # A profile with a source mapping is disabled, not deleted
    assert client.delete(f"/connectivity-profiles/{profile['id']}", headers=admin).status_code == 409
    assert client.delete(
        f"/connectivity-profiles/sources/{source.json()['id']}",
        headers=admin
    ).status_code == 204
    assert client.delete(f"/connectivity-profiles/{profile['id']}", headers=admin).status_code == 204


# --------------------------------
# Decoders belong to an organization
# --------------------------------

def test_decoders_are_isolated_per_organization(client, seed):
    owner1, owner2 = headers(seed["owner1"]), headers(seed["owner2"])

    mine = client.post(
        "/decode-schemas/",
        json={"name": "farm", "fields": DECODER_FIELDS},
        headers=owner1
    ).json()
    assert mine["tenant_id"] == 1 and mine["version"] == 1

    # Another organization can use the same name: its own version 1
    theirs = client.post(
        "/decode-schemas/",
        json={"name": "farm", "fields": DECODER_FIELDS},
        headers=owner2
    ).json()
    assert theirs["version"] == 1

    assert client.get(f"/decode-schemas/{mine['id']}", headers=owner2).status_code == 404
    assert [row["id"] for row in client.get("/decode-schemas/", headers=owner2).json()] == [theirs["id"]]

    # An application can only use its organization's (or platform) decoders
    assert client.put(
        "/applications/1",
        json={"name": "App One", "decode_schema_id": theirs["id"]},
        headers=owner1
    ).status_code == 404
    assert client.put(
        "/applications/1",
        json={"name": "App One", "decode_schema_id": mine["id"]},
        headers=owner1
    ).status_code == 200

    # Platform decoders are visible to owners but managed by admins
    platform = client.post(
        "/decode-schemas/",
        json={"name": "platform", "fields": DECODER_FIELDS},
        headers=headers(seed["admin"])
    ).json()
    assert platform["tenant_id"] is None
    assert client.get(f"/decode-schemas/{platform['id']}", headers=owner1).status_code == 200
    assert client.post(
        f"/decode-schemas/{platform['id']}/activate",
        json={},
        headers=owner1
    ).status_code == 403


def test_application_delete_needs_no_devices(client, seed):
    owner = headers(seed["owner1"])

    assert client.delete("/applications/1", headers=owner).status_code == 409

    empty = client.post("/applications/", json={"name": "Empty"}, headers=owner).json()
    assert empty["tenant_id"] == 1
    assert client.delete(f"/applications/{empty['id']}", headers=owner).status_code == 204
