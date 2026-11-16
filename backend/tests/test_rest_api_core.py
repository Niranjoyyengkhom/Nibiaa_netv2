"""
REST API core: devices, telemetry, latest, providers, usage.

Seed (see conftest.py): DEVICE001 belongs to Tenant 1, DEVICE002 to Tenant 2.
seed_telemetry() adds 8 readings to each (skylo / myriota).
"""

import pytest

from app.providers import DEFAULT_PROFILES
from app.seed_telemetry import READINGS_PER_DEVICE, seed_telemetry


from conftest import headers


@pytest.fixture
def telemetry_seed(db, seed):
    seed_telemetry(db)
    return seed


# --------------------------------
# Devices
# --------------------------------

def test_list_devices_by_role(client, seed):
    admin = client.get("/devices/", headers=headers(seed["admin"]))
    ta1 = client.get("/devices/", headers=headers(seed["ta1"]))

    assert sorted(d["device_id"] for d in admin.json()) == ["DEVICE001", "DEVICE002"]
    assert [d["device_id"] for d in ta1.json()] == ["DEVICE001"]

    assert client.get("/devices/", headers=headers(seed["user1"])).status_code == 403


def test_get_single_device(client, seed):
    response = client.get("/devices/DEVICE001", headers=headers(seed["ta1"]))
    assert response.status_code == 200
    assert response.json()["tenant_id"] == 1

    # Another tenant's device is not found, not revealed
    assert client.get("/devices/DEVICE002", headers=headers(seed["ta1"])).status_code == 404

    assert client.get("/devices/DEVICE002", headers=headers(seed["admin"])).status_code == 200
    assert client.get("/devices/NOPE", headers=headers(seed["admin"])).status_code == 404


def test_register_device_still_works(client, seed):
    response = client.post(
        "/devices/",
        json={
            "device_id": "DEVICE010",
            "name": "New",
            "device_type": "sensor",
            "application_id": 1,
            # Ignored for tenant admins: their own tenant is used
            "tenant_id": 2,
        },
        headers=headers(seed["ta1"])
    )

    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] == 1


# --------------------------------
# Telemetry
# --------------------------------

def test_telemetry_newest_first(client, telemetry_seed):
    response = client.get("/devices/DEVICE001/telemetry", headers=headers(telemetry_seed["ta1"]))

    assert response.status_code == 200
    records = response.json()
    assert len(records) == READINGS_PER_DEVICE

    timestamps = [record["timestamp"] for record in records]
    assert timestamps == sorted(timestamps, reverse=True)

    assert records[0]["device_id"] == "DEVICE001"
    assert records[0]["provider"] == "skylo"
    assert set(records[0]["telemetry"]) == {"temperature", "humidity"}


def test_telemetry_limit_and_time_window(client, telemetry_seed):
    ta1 = headers(telemetry_seed["ta1"])
    url = "/devices/DEVICE001/telemetry"

    assert len(client.get(url, params={"limit": 3}, headers=ta1).json()) == 3

    records = client.get(url, headers=ta1).json()
    # Window that contains exactly the 2nd and 3rd newest records
    window = client.get(
        url,
        params={"start": records[2]["timestamp"], "end": records[1]["timestamp"]},
        headers=ta1
    ).json()
    assert [r["id"] for r in window] == [records[1]["id"], records[2]["id"]]

    bad_window = client.get(
        url,
        params={"start": records[0]["timestamp"], "end": records[2]["timestamp"]},
        headers=ta1
    )
    assert bad_window.status_code == 400

    assert client.get(url, params={"limit": 0}, headers=ta1).status_code == 422


def test_latest(client, telemetry_seed):
    ta1 = headers(telemetry_seed["ta1"])

    latest = client.get("/devices/DEVICE001/latest", headers=ta1)
    newest = client.get("/devices/DEVICE001/telemetry", params={"limit": 1}, headers=ta1)

    assert latest.status_code == 200
    assert latest.json() == newest.json()[0]


def test_latest_without_telemetry(client, seed):
    response = client.get("/devices/DEVICE001/latest", headers=headers(seed["ta1"]))
    assert response.status_code == 404


def test_telemetry_tenant_isolation(client, telemetry_seed):
    ta1 = headers(telemetry_seed["ta1"])

    assert client.get("/devices/DEVICE002/telemetry", headers=ta1).status_code == 404
    assert client.get("/devices/DEVICE002/latest", headers=ta1).status_code == 404

    # Plain users cannot read device data at all (existing convention)
    user1 = headers(telemetry_seed["user1"])
    assert client.get("/devices/DEVICE001/telemetry", headers=user1).status_code == 403

    # Admin can read any tenant
    admin = headers(telemetry_seed["admin"])
    assert client.get("/devices/DEVICE002/latest", headers=admin).json()["provider"] == "myriota"


def test_seed_telemetry_is_repeatable(db, telemetry_seed):
    assert seed_telemetry(db) == 0


# --------------------------------
# Providers
# --------------------------------

def test_providers(client, seed):
    # Connectivity profiles are readable by every signed-in user
    response = client.get("/connectivity-profiles/", headers=headers(seed["user1"]))

    assert response.status_code == 200
    assert {p["code"] for p in response.json()} == {p["code"] for p in DEFAULT_PROFILES}
    assert {p["name"] for p in response.json()} >= {"Skylo", "Kinéis", "Lacuna Space"}

    assert client.get("/connectivity-profiles/", headers=headers(999)).status_code == 401


# --------------------------------
# Usage
# --------------------------------

def test_usage_tenant_admin_sees_own_tenant(client, telemetry_seed):
    ta1 = headers(telemetry_seed["ta1"])

    client.put(
        "/devices/DEVICE001/configuration",
        json={"wake_frequency_per_day": 4},
        headers=ta1
    )

    usage = client.get("/usage/", headers=ta1).json()

    assert usage["tenant_id"] == 1
    assert usage["devices"] == 1
    assert usage["applications"] == 1
    assert usage["uplink_messages"] == READINGS_PER_DEVICE
    assert usage["uplink_messages_by_provider"] == {"skylo": READINGS_PER_DEVICE}
    assert usage["downlink_commands"] == 1
    assert usage["downlink_commands_acknowledged"] == 0


def test_usage_tenant_admin_cannot_pick_other_tenant(client, telemetry_seed):
    response = client.get(
        "/usage/",
        params={"tenant_id": 2},
        headers=headers(telemetry_seed["ta1"])
    )
    assert response.status_code == 403


def test_usage_admin(client, telemetry_seed):
    admin = headers(telemetry_seed["admin"])

    everything = client.get("/usage/", headers=admin).json()
    assert everything["tenant_id"] is None
    assert everything["devices"] == 2
    assert everything["uplink_messages"] == 2 * READINGS_PER_DEVICE

    tenant2 = client.get("/usage/", params={"tenant_id": 2}, headers=admin).json()
    assert tenant2["devices"] == 1
    assert tenant2["uplink_messages_by_provider"] == {"myriota": READINGS_PER_DEVICE}

    assert client.get("/usage/", params={"tenant_id": 99}, headers=admin).status_code == 404


def test_usage_period(client, telemetry_seed):
    admin = headers(telemetry_seed["admin"])

    records = client.get("/devices/DEVICE001/telemetry", headers=admin).json()

    # Only messages received at or after DEVICE001's newest one arrived.
    # The newest reading of each seed device arrived at that same moment.
    usage = client.get(
        "/usage/",
        params={"start": records[0]["received_at"]},
        headers=admin
    ).json()

    assert usage["uplink_messages"] == 2


def test_usage_plain_user_forbidden(client, seed):
    assert client.get("/usage/", headers=headers(seed["user1"])).status_code == 403


# --------------------------------
# Swagger
# --------------------------------

def test_endpoints_in_openapi(client, seed):
    spec = client.get("/openapi.json").json()

    for path in [
        "/devices/",
        "/devices/{device_id}",
        "/devices/{device_id}/telemetry",
        "/devices/{device_id}/latest",
        "/connectivity-profiles/",
        "/collaborator-roles/",
        "/usage/",
    ]:
        assert path in spec["paths"], path
