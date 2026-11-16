"""
Devices registered by network type (NTN, TN, LoRa, BLE) with their
keys, and the in-app notifications that actions create.

Seed (see conftest.py): Tenant 1 has owner1, collaborator1 and App One.
"""

from conftest import headers


LORA = {
    "dev_eui": "70b3d57ed0012345",
    "app_eui": "0000000000000001",
    "app_key": "2B7E151628AED2A6ABF7158809CF4F3C",
}


def register(client, user_id, device_id, device_type, credentials):
    return client.post(
        "/devices/",
        json={
            "device_id": device_id,
            "name": device_id,
            "device_type": device_type,
            "credentials": credentials,
            "application_id": 1,
        },
        headers=headers(user_id)
    )


# --------------------------------
# Network types
# --------------------------------

def test_network_types_list_their_fields(client, seed):
    response = client.get("/devices/network-types", headers=headers(seed["owner1"]))

    assert response.status_code == 200
    types = {t["value"]: [f["key"] for f in t["fields"]] for t in response.json()}

    assert types["LoRa"] == ["dev_eui", "app_eui", "app_key"]
    assert types["NTN"] == ["imei", "satellite_provider_id", "hardware_serial"]
    assert types["TN"] == ["imei", "sim_provider_id", "hardware_serial"]
    assert types["BLE"] == ["mac_address", "hardware_serial"]


def test_lora_device_keys_are_checked_and_app_key_masked(client, seed):
    missing = register(client, seed["owner1"], "LORA-01", "LoRa", {"dev_eui": LORA["dev_eui"]})
    assert missing.status_code == 400
    assert "AppEUI" in missing.json()["detail"]

    bad = register(client, seed["owner1"], "LORA-01", "LoRa", {**LORA, "app_key": "123"})
    assert bad.status_code == 400

    created = register(client, seed["owner1"], "LORA-01", "LoRa", LORA)
    assert created.status_code == 200, created.text

    credentials = created.json()["credentials"]
    assert credentials["dev_eui"] == "70B3D57ED0012345"
    assert credentials["app_key"] == "••••••••4F3C"

    # The same DevEUI cannot identify a second device
    duplicate = register(client, seed["owner1"], "LORA-02", "LoRa", LORA)
    assert duplicate.status_code == 400
    assert "LORA-01" in duplicate.json()["detail"]


def test_update_keeps_secret_left_empty(client, seed, db):
    register(client, seed["owner1"], "LORA-01", "LoRa", LORA)

    response = client.put(
        "/devices/LORA-01",
        json={
            "name": "Renamed",
            "device_type": "LoRa",
            "application_id": 1,
            "credentials": {**LORA, "app_eui": "0000000000000002", "app_key": ""},
        },
        headers=headers(seed["owner1"])
    )

    assert response.status_code == 200, response.text
    assert response.json()["credentials"]["app_eui"] == "0000000000000002"
    assert response.json()["credentials"]["app_key"] == "••••••••4F3C"


def test_cellular_and_ble_devices(client, seed):
    ntn = register(client, seed["owner1"], "NTN-01", "NTN", {
        "imei": "356938035643809",
        "satellite_provider_id": "skylo",
        "hardware_serial": "SN-1",
    })
    assert ntn.status_code == 200, ntn.text

    # An IMEI is unique across NTN and TN devices
    tn = register(client, seed["owner1"], "TN-01", "TN", {
        "imei": "356938035643809",
        "sim_provider_id": "airtel",
        "hardware_serial": "SN-2",
    })
    assert tn.status_code == 400

    ble = register(client, seed["owner1"], "BLE-01", "BLE", {
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "hardware_serial": "SN-3",
    })
    assert ble.status_code == 200, ble.text
    assert ble.json()["credentials"]["mac_address"] == "AA:BB:CC:DD:EE:FF"


# --------------------------------
# Notifications
# --------------------------------

def test_registering_a_device_notifies_the_organization(client, seed):
    register(client, seed["owner1"], "LORA-01", "LoRa", LORA)

    for user in ("owner1", "collaborator1", "admin"):
        count = client.get("/notifications/unread-count", headers=headers(seed[user]))
        assert count.json()["unread_count"] == 1, user

    # Another organization is not told
    other = client.get("/notifications/unread-count", headers=headers(seed["owner2"]))
    assert other.json()["unread_count"] == 0

    notifications = client.get("/notifications/", headers=headers(seed["owner1"])).json()
    assert notifications[0]["title"] == "Device registered"
    assert "LORA-01" in notifications[0]["message"]


def test_read_and_delete_notifications(client, seed):
    register(client, seed["owner1"], "LORA-01", "LoRa", LORA)
    client.delete("/devices/LORA-01", headers=headers(seed["owner1"]))

    owner = headers(seed["owner1"])
    first, second = client.get("/notifications/", headers=owner).json()

    assert client.patch(f"/notifications/{first['id']}/read", headers=owner).status_code == 200
    assert client.get("/notifications/unread-count", headers=owner).json()["unread_count"] == 1

    # Someone else's notification is not found
    assert client.patch(
        f"/notifications/{second['id']}/read",
        headers=headers(seed["owner2"])
    ).status_code == 404

    client.patch("/notifications/read-all", headers=owner)
    assert client.get("/notifications/unread-count", headers=owner).json()["unread_count"] == 0

    assert client.delete(f"/notifications/{first['id']}", headers=owner).status_code == 204
    assert len(client.get("/notifications/", headers=owner).json()) == 1

    assert client.delete("/notifications/", headers=owner).status_code == 204
    assert client.get("/notifications/", headers=owner).json() == []
