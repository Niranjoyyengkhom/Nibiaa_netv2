from app.migrations import run_migrations


from conftest import headers


def put_frequency(client, user_id, device_id, frequency):
    return client.put(
        f"/devices/{device_id}/configuration",
        json={"wake_frequency_per_day": frequency},
        headers=headers(user_id)
    )


def simulate(client, user_id, device_id, command_id, status):
    return client.post(
        f"/devices/{device_id}/commands/{command_id}/simulate",
        json={"status": status},
        headers=headers(user_id)
    )


def deliver(client, user_id, device_id, command_id):
    for status in (
        "GROUND_STATION_QUEUED",
        "SATELLITE_QUEUED",
        "DEVICE_DELIVERED",
    ):
        response = simulate(client, user_id, device_id, command_id, status)
        assert response.status_code == 200, response.text


def ack(client, user_id, device_id, command_id, success=True):
    return client.post(
        f"/devices/{device_id}/commands/{command_id}/ack",
        json={"success": success},
        headers=headers(user_id)
    )


def get_configuration(client, user_id, device_id):
    response = client.get(
        f"/devices/{device_id}/configuration",
        headers=headers(user_id)
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------
# Acceptance flow: 2/day -> 4/day
# --------------------------------

def test_full_store_and_forward_flow(client, seed):
    ta1 = seed["ta1"]

    # 1. Current configuration
    configuration = get_configuration(client, ta1, "DEVICE001")
    assert configuration["desired_wake_frequency_per_day"] == 2
    assert configuration["confirmed_wake_frequency_per_day"] == 2
    assert configuration["in_sync"] is True
    assert configuration["pending_command_id"] is None

    # 2. Request 4/day
    response = put_frequency(client, ta1, "DEVICE001", 4)
    assert response.status_code == 200, response.text
    body = response.json()

    # 3./4. Desired changes, confirmed does not
    assert body["desired_wake_frequency_per_day"] == 4
    assert body["confirmed_wake_frequency_per_day"] == 2
    assert body["in_sync"] is False

    # 5./6. One SET_WAKE_FREQUENCY command, PENDING
    assert len(body["queued_commands"]) == 1
    queued = body["queued_commands"][0]
    assert queued["command_type"] == "SET_WAKE_FREQUENCY"
    assert queued["status"] == "PENDING"
    assert body["pending_command_id"] == queued["id"]
    assert body["pending_command_status"] == "PENDING"

    command_id = queued["id"]

    # 7. Simulate delivery hop by hop; confirmed stays 2 the whole way
    for status in (
        "GROUND_STATION_QUEUED",
        "SATELLITE_QUEUED",
        "DEVICE_DELIVERED",
    ):
        response = simulate(client, ta1, "DEVICE001", command_id, status)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status

        configuration = get_configuration(client, ta1, "DEVICE001")
        assert configuration["confirmed_wake_frequency_per_day"] == 2
        assert configuration["pending_command_status"] == status

    assert response.json()["delivered_at"] is not None
    assert response.json()["acknowledged_at"] is None

    # 8. Device acknowledges
    response = ack(client, ta1, "DEVICE001", command_id)
    assert response.status_code == 200, response.text
    command = response.json()
    assert command["status"] == "ACKNOWLEDGED"
    assert command["acknowledged_at"] is not None

    # Full path there and back is in the history
    assert [
        (event["location"], event["event"])
        for event in command["events"]
    ] == [
        ("SERVER", "CREATED"),
        ("GROUND_STATION", "QUEUED"),
        ("SATELLITE", "QUEUED"),
        ("DEVICE", "DELIVERED"),
        ("DEVICE", "APPLIED"),
        ("SATELLITE", "ACK_RELAYED"),
        ("GROUND_STATION", "ACK_RELAYED"),
        ("SERVER", "ACKNOWLEDGED"),
    ]

    # 9. Confirmed is now 4
    configuration = get_configuration(client, ta1, "DEVICE001")
    assert configuration["desired_wake_frequency_per_day"] == 4
    assert configuration["confirmed_wake_frequency_per_day"] == 4
    assert configuration["in_sync"] is True
    assert configuration["pending_command_id"] is None


def test_command_list_and_detail(client, seed):
    ta1 = seed["ta1"]

    command_id = put_frequency(client, ta1, "DEVICE001", 4).json()["queued_commands"][0]["id"]

    response = client.get("/devices/DEVICE001/commands", headers=headers(ta1))
    assert response.status_code == 200
    assert [command["id"] for command in response.json()] == [command_id]

    response = client.get(
        f"/devices/DEVICE001/commands/{command_id}",
        headers=headers(ta1)
    )
    assert response.status_code == 200
    assert response.json()["payload"] == {"frequency_per_day": 4}
    assert response.json()["events"][0]["event"] == "CREATED"


def test_enabled_uses_set_enabled_and_keeps_frequency(client, seed):
    ta1 = seed["ta1"]

    response = client.put(
        "/devices/DEVICE001/configuration",
        json={"enabled": False},
        headers=headers(ta1)
    )
    body = response.json()

    assert [c["command_type"] for c in body["queued_commands"]] == ["SET_ENABLED"]
    assert body["desired_enabled"] is False
    assert body["confirmed_enabled"] is True
    # Disabling does not touch the stored frequency
    assert body["desired_wake_frequency_per_day"] == 2

    command_id = body["queued_commands"][0]["id"]
    deliver(client, ta1, "DEVICE001", command_id)
    ack(client, ta1, "DEVICE001", command_id)

    configuration = get_configuration(client, ta1, "DEVICE001")
    assert configuration["confirmed_enabled"] is False
    assert configuration["confirmed_wake_frequency_per_day"] == 2


def test_no_command_when_value_already_confirmed(client, seed):
    response = put_frequency(client, seed["ta1"], "DEVICE001", 2)

    assert response.status_code == 200
    assert response.json()["queued_commands"] == []


def test_invalid_frequency_rejected(client, seed):
    assert put_frequency(client, seed["ta1"], "DEVICE001", 0).status_code == 422
    assert put_frequency(client, seed["ta1"], "DEVICE001", 25).status_code == 422


def test_ack_before_delivery_rejected(client, seed):
    ta1 = seed["ta1"]
    command_id = put_frequency(client, ta1, "DEVICE001", 4).json()["queued_commands"][0]["id"]

    response = ack(client, ta1, "DEVICE001", command_id)
    assert response.status_code == 409

    assert get_configuration(client, ta1, "DEVICE001")["confirmed_wake_frequency_per_day"] == 2


def test_rejected_ack_keeps_confirmed(client, seed):
    ta1 = seed["ta1"]
    command_id = put_frequency(client, ta1, "DEVICE001", 4).json()["queued_commands"][0]["id"]
    deliver(client, ta1, "DEVICE001", command_id)

    response = ack(client, ta1, "DEVICE001", command_id, success=False)
    assert response.json()["status"] == "FAILED"

    configuration = get_configuration(client, ta1, "DEVICE001")
    assert configuration["confirmed_wake_frequency_per_day"] == 2
    assert configuration["in_sync"] is False


# --------------------------------
# Idempotency
# --------------------------------

def test_duplicate_ack_is_idempotent(client, seed):
    ta1 = seed["ta1"]
    command_id = put_frequency(client, ta1, "DEVICE001", 4).json()["queued_commands"][0]["id"]
    deliver(client, ta1, "DEVICE001", command_id)

    first = ack(client, ta1, "DEVICE001", command_id)
    second = ack(client, ta1, "DEVICE001", command_id)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "ACKNOWLEDGED"
    # Same history: the repeat recorded nothing
    assert second.json()["events"] == first.json()["events"]
    assert second.json()["acknowledged_at"] == first.json()["acknowledged_at"]

    assert get_configuration(client, ta1, "DEVICE001")["confirmed_wake_frequency_per_day"] == 4


def test_late_duplicate_ack_does_not_roll_back(client, seed):
    ta1 = seed["ta1"]

    old_id = put_frequency(client, ta1, "DEVICE001", 4).json()["queued_commands"][0]["id"]
    deliver(client, ta1, "DEVICE001", old_id)
    ack(client, ta1, "DEVICE001", old_id)

    new_id = put_frequency(client, ta1, "DEVICE001", 6).json()["queued_commands"][0]["id"]
    deliver(client, ta1, "DEVICE001", new_id)
    ack(client, ta1, "DEVICE001", new_id)

    # The old acknowledgement arrives again via a retransmission
    assert ack(client, ta1, "DEVICE001", old_id).status_code == 200

    assert get_configuration(client, ta1, "DEVICE001")["confirmed_wake_frequency_per_day"] == 6


def test_contradicting_ack_rejected(client, seed):
    ta1 = seed["ta1"]
    command_id = put_frequency(client, ta1, "DEVICE001", 4).json()["queued_commands"][0]["id"]
    deliver(client, ta1, "DEVICE001", command_id)
    ack(client, ta1, "DEVICE001", command_id)

    assert ack(client, ta1, "DEVICE001", command_id, success=False).status_code == 409
    assert get_configuration(client, ta1, "DEVICE001")["confirmed_wake_frequency_per_day"] == 4


# --------------------------------
# Cancel
# --------------------------------

def test_cancel_before_delivery(client, seed):
    ta1 = seed["ta1"]
    command_id = put_frequency(client, ta1, "DEVICE001", 4).json()["queued_commands"][0]["id"]
    simulate(client, ta1, "DEVICE001", command_id, "GROUND_STATION_QUEUED")

    url = f"/devices/DEVICE001/commands/{command_id}/cancel"

    response = client.post(url, json={}, headers=headers(ta1))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"

    # Cancelling twice is fine
    assert client.post(url, json={}, headers=headers(ta1)).status_code == 200

    # A cancelled command cannot be delivered or acknowledged
    assert simulate(client, ta1, "DEVICE001", command_id, "SATELLITE_QUEUED").status_code == 409
    assert ack(client, ta1, "DEVICE001", command_id).status_code == 409

    configuration = get_configuration(client, ta1, "DEVICE001")
    assert configuration["confirmed_wake_frequency_per_day"] == 2
    assert configuration["pending_command_id"] is None


def test_cannot_cancel_after_delivery(client, seed):
    ta1 = seed["ta1"]
    command_id = put_frequency(client, ta1, "DEVICE001", 4).json()["queued_commands"][0]["id"]
    deliver(client, ta1, "DEVICE001", command_id)

    response = client.post(
        f"/devices/DEVICE001/commands/{command_id}/cancel",
        json={},
        headers=headers(ta1)
    )
    assert response.status_code == 409


# --------------------------------
# RBAC / tenant isolation
# --------------------------------

def test_tenant_admin_cannot_touch_other_tenant_device(client, seed):
    ta1 = seed["ta1"]

    # A command that exists on the Tenant 2 device
    command_id = put_frequency(client, seed["ta2"], "DEVICE002", 4).json()["queued_commands"][0]["id"]

    base = "/devices/DEVICE002"
    attempts = [
        client.get(f"{base}/configuration", headers=headers(ta1)),
        put_frequency(client, ta1, "DEVICE002", 8),
        client.get(f"{base}/commands", headers=headers(ta1)),
        client.get(f"{base}/commands/{command_id}", headers=headers(ta1)),
        simulate(client, ta1, "DEVICE002", command_id, "GROUND_STATION_QUEUED"),
        ack(client, ta1, "DEVICE002", command_id),
        client.post(f"{base}/commands/{command_id}/cancel", json={}, headers=headers(ta1)),
    ]

    # The device is "not found" for another tenant, so its existence is not leaked
    assert [response.status_code for response in attempts] == [404] * len(attempts)

    # Nothing changed on the Tenant 2 device
    configuration = get_configuration(client, seed["ta2"], "DEVICE002")
    assert configuration["desired_wake_frequency_per_day"] == 4
    assert configuration["pending_command_status"] == "PENDING"


def test_command_must_belong_to_device_in_url(client, seed):
    # Tenant 2's command id used through Tenant 1's own device
    command_id = put_frequency(client, seed["ta2"], "DEVICE002", 4).json()["queued_commands"][0]["id"]

    response = client.get(
        f"/devices/DEVICE001/commands/{command_id}",
        headers=headers(seed["ta1"])
    )
    assert response.status_code == 404


def test_plain_user_cannot_configure(client, seed):
    user1 = seed["user1"]

    assert client.get("/devices/DEVICE001/configuration", headers=headers(user1)).status_code == 403
    assert put_frequency(client, user1, "DEVICE001", 4).status_code == 403
    assert client.get("/devices/DEVICE001/commands", headers=headers(user1)).status_code == 403


def test_admin_can_configure_any_tenant(client, seed):
    admin = seed["admin"]

    assert put_frequency(client, admin, "DEVICE001", 4).status_code == 200
    assert put_frequency(client, admin, "DEVICE002", 4).status_code == 200


def test_unknown_user_rejected(client, seed):
    assert client.get("/devices/DEVICE001/configuration", headers=headers(999)).status_code == 401


# --------------------------------
# Migration safety
# --------------------------------

def test_migrations_can_run_repeatedly(db):
    from app.database import engine

    run_migrations(engine)
    run_migrations(engine)
