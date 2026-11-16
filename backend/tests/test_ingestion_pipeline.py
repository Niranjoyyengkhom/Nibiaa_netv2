"""
Uplink pipeline: provider resolution (connectivity profiles), versioned
decoders with activation / rollback, staging (decoded_messages),
multi-tenant routing, NTN / TN, and the delivery layer
(REST, MQTT, webhooks).

Seed (see conftest.py): DEVICE001 -> Tenant 1 / App 1,
DEVICE002 -> Tenant 2 / App 2.
"""

import base64
import hashlib
import hmac
import json
import struct
from datetime import datetime, timedelta, timezone

import pytest

from app.models.decoded_message import DecodedMessage
from app.models.webhook import WebhookDelivery
from app.services import mqtt_publisher, webhook_service

from conftest import headers


SATELLITE_IP = "203.0.113.5"

MEASURED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

# Layout used by the tests (big endian):
#   0..9   device_id    ascii, NUL padded
#   10..13 timestamp    uint32, Unix seconds
#   14..15 temperature  int16 * 0.01 °C
#   16..17 humidity     uint16 * 0.1 %RH
#   18     door_open    bit 0
SCHEMA_FIELDS = [
    {"field_name": "device_id", "byte_offset": 0, "byte_length": 10, "data_type": "ascii"},
    {"field_name": "timestamp", "byte_offset": 10, "byte_length": 4, "data_type": "uint32"},
    {"field_name": "temperature", "byte_offset": 14, "byte_length": 2, "data_type": "int16",
     "scale_factor": 0.01, "unit": "°C"},
    {"field_name": "humidity", "byte_offset": 16, "byte_length": 2, "data_type": "uint16",
     "scale_factor": 0.1, "unit": "%RH"},
    {"field_name": "door_open", "byte_offset": 18, "byte_length": 1, "data_type": "bitfield",
     "bit_offset": 0, "bit_length": 1},
]


def payload(device_id="DEVICE001", temperature=-5.25, humidity=62.4, door_open=1):
    return (
        device_id.encode().ljust(10, b"\x00")
        + struct.pack(">I", int(MEASURED_AT.timestamp()))
        + struct.pack(">h", round(temperature * 100))
        + struct.pack(">H", round(humidity * 10))
        + bytes([door_open])
    )


def profile_id(client, user_id, code):
    profiles = client.get("/connectivity-profiles/", headers=headers(user_id)).json()
    return {profile["code"]: profile["id"] for profile in profiles}[code]


def add_source(client, admin, provider="skylo", transport="udp", identity=SATELLITE_IP):
    response = client.post(
        f"/connectivity-profiles/{profile_id(client, admin, provider)}/sources",
        json={"transport": transport, "identity": identity},
        headers=headers(admin)
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_schema(client, user_id, fields=SCHEMA_FIELDS, name="env_sensor", **extra):
    response = client.post(
        "/decode-schemas/",
        json={"name": name, "byte_order": "big", "fields": fields, **extra},
        headers=headers(user_id)
    )
    assert response.status_code == 200, response.text
    return response.json()


def activate(client, user_id, schema_id):
    response = client.post(
        f"/decode-schemas/{schema_id}/activate",
        json={},
        headers=headers(user_id)
    )
    assert response.status_code == 200, response.text
    return response.json()


def use_decoder(client, admin, application_id, schema_id):
    applications = client.get("/applications/", headers=headers(admin)).json()
    name = {app["id"]: app["name"] for app in applications}[application_id]

    response = client.put(
        f"/applications/{application_id}",
        json={"name": name, "decode_schema_id": schema_id},
        headers=headers(admin)
    )
    assert response.status_code == 200, response.text
    return response.json()


def ingest(
    client,
    admin,
    raw,
    transport="udp",
    source=f"{SATELLITE_IP}:4000",
    client_id=None,
    device_id="DEVICE001",
    provider=None,
):
    response = client.post(
        "/ingest/uplinks",
        json={
            "id": "msg-1",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "transport": {
                "type": transport,
                "remote_address": source,
                "connection_id": client_id,
                "provider": provider,
            },
            "source": {"device_id": device_id},
            "payload": {"data": base64.b64encode(raw).decode()},
        },
        headers=headers(admin)
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def pipeline(client, seed, monkeypatch):
    # No broker in the tests unless a test configures one
    monkeypatch.delenv("MQTT_BROKER_HOST", raising=False)

    add_source(client, seed["admin"])

    # Platform decoder, used by both organizations' applications
    schema = create_schema(client, seed["admin"])
    use_decoder(client, seed["admin"], 1, schema["id"])
    use_decoder(client, seed["admin"], 2, schema["id"])
    activation = activate(client, seed["admin"], schema["id"])

    return {**seed, "schema": schema, "activation": activation}


@pytest.fixture
def webhook_calls(monkeypatch):
    """Replaces the HTTP call; set calls.status to change the answer."""

    class Calls(list):
        status = 200

    calls = Calls()

    def fake_post(url, body, request_headers):
        calls.append({"url": url, "body": body, "headers": request_headers})
        return calls.status

    monkeypatch.setattr(webhook_service, "http_post", fake_post)

    return calls


def create_webhook(client, user_id, **body):
    response = client.post(
        "/webhooks/",
        json={"name": "hook", "url": "https://example.com/hook", **body},
        headers=headers(user_id)
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------
# Decode, route, store, REST
# --------------------------------

def test_uplink_is_decoded_routed_and_served_over_rest(client, pipeline):
    raw = payload()
    message = ingest(client, pipeline["admin"], raw)

    assert message["status"] == "ROUTED", message["error"]
    assert message["provider"] == "skylo"
    assert message["connection_type"] == "NTN"
    assert message["decode_activation_id"] == pipeline["activation"]["activation_id"]
    assert message["device_id"] == "DEVICE001"
    assert message["tenant_id"] == 1
    assert message["decoded"] == {
        "device_id": "DEVICE001",
        "timestamp": int(MEASURED_AT.timestamp()),
        "temperature": -5.25,
        "humidity": 62.4,
        "door_open": 1,
    }
    assert message["units"] == {"temperature": "°C", "humidity": "%RH"}

    latest = client.get("/devices/DEVICE001/latest", headers=headers(pipeline["ta1"]))
    assert latest.status_code == 200
    body = latest.json()

    # Routing fields are columns, not telemetry values
    assert body["telemetry"] == {"temperature": -5.25, "humidity": 62.4, "door_open": 1}
    assert datetime.fromisoformat(body["timestamp"]) == MEASURED_AT
    assert body["provider"] == "skylo"
    assert body["connection_type"] == "NTN"
    assert body["application_id"] == 1
    assert body["raw_payload_hex"] == raw.hex()
    assert body["decode_activation_id"] == pipeline["activation"]["activation_id"]


def test_fleet_rest_is_tenant_isolated(client, pipeline):
    ingest(client, pipeline["admin"], payload("DEVICE001"), device_id="DEVICE001")
    ingest(client, pipeline["admin"], payload("DEVICE002"), device_id="DEVICE002")

    ta1 = client.get("/telemetry/", headers=headers(pipeline["ta1"])).json()
    ta2 = client.get("/telemetry/?tenant_id=1", headers=headers(pipeline["ta2"])).json()
    admin = client.get("/telemetry/", headers=headers(pipeline["admin"])).json()

    assert [row["device_id"] for row in ta1] == ["DEVICE001"]
    # tenant_id is ignored for owners
    assert [row["device_id"] for row in ta2] == ["DEVICE002"]
    assert sorted(row["device_id"] for row in admin) == ["DEVICE001", "DEVICE002"]

    by_application = client.get(
        "/telemetry/?application_id=2",
        headers=headers(pipeline["admin"])
    ).json()
    assert [row["device_id"] for row in by_application] == ["DEVICE002"]

    # A collaborator without Read Application Traffic
    assert client.get("/telemetry/", headers=headers(pipeline["user1"])).status_code == 403


def test_failures_are_staged_with_a_reason(client, seed, monkeypatch):
    monkeypatch.delenv("MQTT_BROKER_HOST", raising=False)
    admin = seed["admin"]

    # The adapter names a provider that has no connectivity profile
    unknown_provider = ingest(client, admin, payload(), provider="not_a_provider")
    assert unknown_provider["status"] == "UNKNOWN_PROVIDER"

    # Unknown source: the provider stays unknown, but App 1 has no decoder
    no_decoder = ingest(client, admin, payload())
    assert no_decoder["status"] == "NO_ACTIVE_SCHEMA"
    assert no_decoder["provider"] is None

    add_source(client, admin)
    use_decoder(client, admin, 1, create_schema(client, admin)["id"])

    short = ingest(client, admin, payload()[:17])
    assert short["status"] == "DECODE_FAILED"
    assert "humidity" in short["error"]
    assert short["provider"] == "skylo"

    unknown = ingest(client, admin, payload("NOPE"), device_id="NOPE")
    assert unknown["status"] == "UNKNOWN_DEVICE"
    assert unknown["tenant_id"] is None

    staged = client.get("/ingest/messages", headers=headers(admin)).json()
    assert len(staged) == 4

    failed_only = client.get(
        "/ingest/messages?status=UNKNOWN_DEVICE",
        headers=headers(admin)
    ).json()
    assert [row["id"] for row in failed_only] == [unknown["id"]]

    # Ingestion is platform plumbing
    assert client.get("/ingest/messages", headers=headers(seed["ta1"])).status_code == 403


def test_disabled_profile_and_payload_limit(client, pipeline):
    admin = pipeline["admin"]
    skylo = profile_id(client, admin, "skylo")

    response = client.put(
        f"/connectivity-profiles/{skylo}",
        json={
            "name": "Skylo",
            "connection_type": "NTN",
            "integration_status": "available",
            "enabled": True,
            "max_payload_bytes": 10,
        },
        headers=headers(admin)
    )
    assert response.status_code == 200, response.text

    too_big = ingest(client, admin, payload())
    assert too_big["status"] == "DECODE_FAILED"
    assert "at most 10" in too_big["error"]

    response = client.put(
        f"/connectivity-profiles/{skylo}",
        json={"name": "Skylo", "connection_type": "NTN", "enabled": False},
        headers=headers(admin)
    )
    assert response.status_code == 200, response.text

    disabled = ingest(client, admin, payload())
    assert disabled["status"] == "UNKNOWN_PROVIDER"
    assert "disabled" in disabled["error"]


# --------------------------------
# Versioned decoders: activation and rollback
# --------------------------------

def test_decoder_correction_is_activated_and_reprocessed(client, seed, monkeypatch):
    monkeypatch.delenv("MQTT_BROKER_HOST", raising=False)
    admin = seed["admin"]
    add_source(client, admin)

    # v1 has a mistake: humidity at the wrong offset, beyond the payload
    wrong_fields = [dict(field) for field in SCHEMA_FIELDS]
    wrong_fields[3]["byte_offset"] = 19
    v1 = create_schema(client, admin, wrong_fields)
    use_decoder(client, admin, 1, v1["id"])
    first_activation = activate(client, admin, v1["id"])

    failed = ingest(client, admin, payload())
    assert failed["status"] == "DECODE_FAILED"
    assert failed["decode_activation_id"] == first_activation["activation_id"]

    # Dry run of the correction before going live
    v2 = create_schema(client, admin)
    assert v2["version"] == 2
    test = client.post(
        f"/decode-schemas/{v2['id']}/test",
        json={"payload_hex": payload().hex()},
        headers=headers(admin)
    ).json()
    assert test["ok"] is True
    assert test["decoded"]["humidity"] == 62.4

    # Activating the correction moves App 1 to it: no restart,
    # the next message uses it
    second_activation = activate(client, admin, v2["id"])
    assert second_activation["applications_updated"] == 1
    assert second_activation["activation_id"] != first_activation["activation_id"]
    assert ingest(client, admin, payload())["status"] == "ROUTED"

    # And the message that failed under v1 can be decoded again
    response = client.post("/ingest/reprocess", json={}, headers=headers(admin))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["processed"] == 1
    assert result["routed"] == 1
    assert result["messages"][0]["id"] == failed["id"]
    assert result["messages"][0]["decode_activation_id"] == second_activation["activation_id"]

    # Rollback = activating v1 again, as a NEW activation
    rollback = activate(client, admin, v1["id"])
    assert rollback["activation_id"] not in (
        first_activation["activation_id"],
        second_activation["activation_id"],
    )

    applications = client.get("/applications/", headers=headers(admin)).json()
    assert {app["id"]: app["decode_schema_id"] for app in applications}[1] == v1["id"]

    history = client.get(
        "/decode-schemas/activations",
        headers=headers(admin)
    ).json()
    assert [row["active"] for row in history] == [True, False, False]
    assert [row["schema_version"] for row in history] == [1, 2, 1]

    schemas = client.get("/decode-schemas/?name=env_sensor", headers=headers(admin)).json()
    assert {row["version"]: row["active_activation_id"] for row in schemas} == {
        2: None,
        1: rollback["activation_id"],
    }

    # A version in use cannot be deleted; an unused one can
    assert client.delete(f"/decode-schemas/{v1['id']}", headers=headers(admin)).status_code == 409
    assert client.delete(f"/decode-schemas/{v2['id']}", headers=headers(admin)).status_code == 204


def test_schema_validation(client, seed):
    bad_size = [{"field_name": "t", "byte_offset": 0, "byte_length": 3, "data_type": "int16"}]
    response = client.post(
        "/decode-schemas/",
        json={"name": "bad", "fields": bad_size},
        headers=headers(seed["admin"])
    )
    assert response.status_code == 422

    duplicate = [
        {"field_name": "t", "byte_offset": 0, "byte_length": 1, "data_type": "uint8"},
        {"field_name": "t", "byte_offset": 1, "byte_length": 1, "data_type": "uint8"},
    ]
    response = client.post(
        "/decode-schemas/",
        json={"name": "bad", "fields": duplicate},
        headers=headers(seed["admin"])
    )
    assert response.status_code == 422


# --------------------------------
# NTN / TN
# --------------------------------

def test_terrestrial_uplink_is_tn(client, pipeline):
    admin = pipeline["admin"]

    add_source(client, admin, provider="cellular", transport="mqtt", identity="gw-cell-01")

    message = ingest(
        client,
        admin,
        payload(),
        transport="mqtt",
        source=None,
        client_id="gw-cell-01",
    )
    assert message["status"] == "ROUTED", message["error"]
    assert message["provider"] == "cellular"
    assert message["connection_type"] == "TN"

    ingest(client, admin, payload())  # satellite (NTN)

    tn = client.get(
        "/devices/DEVICE001/telemetry?connection_type=TN",
        headers=headers(pipeline["ta1"])
    ).json()
    ntn = client.get(
        "/telemetry/?connection_type=NTN",
        headers=headers(pipeline["ta1"])
    ).json()

    assert [row["provider"] for row in tn] == ["cellular"]
    assert [row["provider"] for row in ntn] == ["skylo"]

    providers = client.get("/connectivity-profiles/", headers=headers(admin)).json()
    assert {p["code"]: p["connection_type"] for p in providers}["cellular"] == "TN"
    assert {p["code"]: p["uplink_count"] for p in providers}["cellular"] == 1


# --------------------------------
# Delivery: webhooks
# --------------------------------

def test_webhook_receives_signed_event_of_own_tenant_only(client, pipeline, webhook_calls):
    hook1 = create_webhook(client, pipeline["ta1"], filters={"connection_types": ["NTN"]})
    create_webhook(client, pipeline["ta2"], url="https://tenant-two.example.com/hook")

    assert hook1["tenant_id"] == 1

    message = ingest(client, pipeline["admin"], payload("DEVICE001"))

    # Only Tenant 1's webhook is called
    assert len(webhook_calls) == 1
    call = webhook_calls[0]
    assert call["url"] == "https://example.com/hook"

    expected = "sha256=" + hmac.new(
        hook1["secret"].encode(), call["body"], hashlib.sha256
    ).hexdigest()
    assert call["headers"]["X-NibiaaNet-Signature"] == expected

    event = json.loads(call["body"])
    assert event["device_id"] == "DEVICE001"
    assert event["tenant_id"] == 1
    assert event["connection_type"] == "NTN"
    assert event["telemetry_id"] == message["telemetry_id"]
    assert event["telemetry"]["temperature"] == -5.25

    deliveries = client.get(
        f"/webhooks/{hook1['id']}/deliveries",
        headers=headers(pipeline["ta1"])
    ).json()
    assert [d["status"] for d in deliveries] == ["DELIVERED"]

    # Another tenant's webhook is not visible
    assert client.get(f"/webhooks/{hook1['id']}", headers=headers(pipeline["ta2"])).status_code == 404


def test_webhook_filters(client, pipeline, webhook_calls):
    create_webhook(client, pipeline["ta1"], filters={"connection_types": ["TN"]})
    create_webhook(client, pipeline["ta1"], filters={"device_ids": ["OTHER"]})

    ingest(client, pipeline["admin"], payload("DEVICE001"))

    assert webhook_calls == []


def test_undeliverable_webhook_raises_alert_and_can_be_redelivered(
    client, pipeline, webhook_calls, db
):
    hook = create_webhook(client, pipeline["ta1"])
    webhook_calls.status = 500

    ingest(client, pipeline["admin"], payload())

    delivery = db.query(WebhookDelivery).one()
    assert delivery.status == "RETRYING"
    assert delivery.attempts == 1
    assert delivery.last_error == "HTTP 500"

    # Run the remaining attempts as the worker would, once each is due
    for _ in range(webhook_service.MAX_ATTEMPTS - 1):
        db.refresh(delivery)
        delivery.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

        response = client.post("/webhooks/deliveries/retry-due", headers=headers(pipeline["admin"]))
        assert response.json() == {"attempted": 1}

    db.refresh(delivery)
    assert delivery.status == "UNDELIVERABLE"
    assert delivery.attempts == webhook_service.MAX_ATTEMPTS
    assert len(webhook_calls) == webhook_service.MAX_ATTEMPTS

    alerts = client.get("/webhooks/alerts", headers=headers(pipeline["ta1"])).json()
    assert [a["id"] for a in alerts] == [delivery.id]
    assert client.get("/webhooks/alerts", headers=headers(pipeline["ta2"])).json() == []

    # Endpoint fixed: redeliver
    webhook_calls.status = 204
    response = client.post(
        f"/webhooks/deliveries/{delivery.id}/redeliver",
        headers=headers(pipeline["ta1"])
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "DELIVERED"
    assert client.get("/webhooks/alerts", headers=headers(pipeline["ta1"])).json() == []

    # The original event is sent again, unchanged
    assert webhook_calls[-1]["body"] == webhook_calls[0]["body"]
    assert hook["id"] == response.json()["webhook_id"]


# --------------------------------
# Delivery: MQTT
# --------------------------------

def test_mqtt_publish_to_tenant_topic(client, pipeline, monkeypatch, db):
    published = []

    def fake_single(topic, payload, **kwargs):
        published.append((topic, json.loads(payload), kwargs))

    monkeypatch.setenv("MQTT_BROKER_HOST", "broker.test")
    monkeypatch.setattr(mqtt_publisher.mqtt_publish, "single", fake_single)

    message = ingest(client, pipeline["admin"], payload())

    assert len(published) == 1
    topic, event, kwargs = published[0]
    assert topic == "nibiaanet/tenants/1/devices/DEVICE001/telemetry"
    assert event["telemetry"]["humidity"] == 62.4
    assert kwargs["hostname"] == "broker.test"
    assert kwargs["qos"] == 1

    assert db.get(DecodedMessage, message["id"]).mqtt_status == "PUBLISHED"


def test_mqtt_without_broker_is_disabled(client, pipeline, db):
    message = ingest(client, pipeline["admin"], payload())

    assert db.get(DecodedMessage, message["id"]).mqtt_status == "DISABLED"


# --------------------------------
# Staging is temporary
# --------------------------------

def test_purge_removes_old_staged_messages(client, pipeline, db):
    routed = ingest(client, pipeline["admin"], payload())
    failed = ingest(client, pipeline["admin"], payload("NOPE"), device_id="NOPE")
    recent_failed = ingest(client, pipeline["admin"], payload("NOPE"), device_id="NOPE")

    old = datetime.now(timezone.utc) - timedelta(days=31)

    for message_id in (routed["id"], failed["id"]):
        db.get(DecodedMessage, message_id).received_at = old

    db.commit()

    response = client.post("/ingest/purge", headers=headers(pipeline["admin"]))
    assert response.json() == {"deleted": 2}

    db.expire_all()
    remaining = [message.id for message in db.query(DecodedMessage).all()]
    assert remaining == [recent_failed["id"]]

    # The telemetry of the purged ROUTED message is kept
    latest = client.get("/devices/DEVICE001/latest", headers=headers(pipeline["ta1"]))
    assert latest.status_code == 200
