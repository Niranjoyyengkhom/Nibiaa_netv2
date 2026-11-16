"""
JavaScript decoders (DecoderDefinition.code) and decoder matching
(DecoderMatch): application decoder first, else the most specific live
match. Also the IncomingMessage contract in its TypeScript shape.

Seed (see conftest.py): DEVICE001 -> Tenant 1 / App 1 (device_type
"sensor"), DEVICE002 -> Tenant 2 / App 2. No application has a decoder.
"""

import base64
from datetime import datetime, timezone

import pytest

from app.services.js_decoder_runtime import js_runtime

from conftest import headers


pytestmark = pytest.mark.skipif(
    not js_runtime.available(),
    reason="Node.js is not installed"
)

SATELLITE_IP = "203.0.113.5"

# temperature int16 / 100, humidity uint16 / 10
ENV_CODE = """
function decode(input) {
  const view = new DataView(input.payload.bytes.buffer);
  return {
    data: { temperature: view.getInt16(0) / 100, humidity: view.getUint16(2) / 10 },
    units: { temperature: "°C", humidity: "%RH" },
  };
}
"""

PAYLOAD = bytes.fromhex("09c4026c")  # 25.00 °C, 62.0 %RH


def create(client, user_id, code=ENV_CODE, name="env_js", match=None, **extra):
    response = client.post(
        "/decode-schemas/",
        json={"name": name, "code": code, "match": match or {}, **extra},
        headers=headers(user_id)
    )
    assert response.status_code == 200, response.text
    return response.json()


def activate(client, user_id, schema_id):
    response = client.post(f"/decode-schemas/{schema_id}/activate", json={}, headers=headers(user_id))
    assert response.status_code == 200, response.text


def skylo_source(client, admin):
    profiles = client.get("/connectivity-profiles/", headers=headers(admin)).json()
    skylo = {p["code"]: p["id"] for p in profiles}["skylo"]
    client.post(
        f"/connectivity-profiles/{skylo}/sources",
        json={"transport": "udp", "identity": SATELLITE_IP},
        headers=headers(admin)
    )


def ingest(client, admin, raw=PAYLOAD, device_id="DEVICE001", **source):
    # The adapters' TypeScript shape: camelCase, Node Buffer via JSON.stringify
    response = client.post(
        "/ingest/uplinks",
        json={
            "id": "uplink-1",
            "receivedAt": datetime.now(timezone.utc).isoformat(),
            "transport": {"type": "udp", "remoteAddress": f"{SATELLITE_IP}:4000", "remotePort": 4000},
            "source": {"deviceId": device_id, **source},
            "payload": {"data": {"type": "Buffer", "data": list(raw)}},
        },
        headers=headers(admin)
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------
# DecoderDefinition
# --------------------------------

def test_create_javascript_decoder(client, seed):
    decoder = create(
        client,
        seed["owner1"],
        match={"providerId": "skylo", "deviceTypeId": "sensor"},
    )

    assert decoder["kind"] == "javascript"
    assert decoder["tenant_id"] == 1
    assert decoder["fields"] == []
    # DecoderMatch keeps the contract's camelCase keys
    assert decoder["match"] == {
        "providerId": "skylo",
        "protocolId": None,
        "deviceTypeId": "sensor",
        "messageType": None,
        "version": None,
    }


def test_invalid_decoder_code_is_refused(client, seed):
    owner = headers(seed["owner1"])

    syntax = client.post("/decode-schemas/", json={"name": "bad", "code": "function decode( {"}, headers=owner)
    assert syntax.status_code == 422
    assert "SyntaxError" in syntax.json()["detail"]

    missing = client.post("/decode-schemas/", json={"name": "bad", "code": "const x = 1;"}, headers=owner)
    assert missing.status_code == 422
    assert "decode(input)" in missing.json()["detail"]

    both = client.post(
        "/decode-schemas/",
        json={
            "name": "bad",
            "code": ENV_CODE,
            "fields": [{"field_name": "t", "byte_offset": 0, "byte_length": 1, "data_type": "uint8"}],
        },
        headers=owner
    )
    assert both.status_code == 422


def test_dry_run_gets_context(client, seed):
    code = """
    function decode(input) {
      return { first: input.payload.bytes[0], device: input.context.deviceId,
               decoder: input.context.decoderName };
    }
    """
    decoder = create(client, seed["owner1"], code=code, name="ctx")

    result = client.post(
        f"/decode-schemas/{decoder['id']}/test",
        json={"payload_hex": "2a", "context": {"deviceId": "DEVICE001"}},
        headers=headers(seed["owner1"])
    ).json()

    assert result == {
        "ok": True,
        "decoded": {"first": 42, "device": "DEVICE001", "decoder": "ctx"},
        "units": {},
        "error": None,
    }


# --------------------------------
# Selection: application first, then match
# --------------------------------

def test_uplink_decoded_by_matching_live_decoder(client, seed, monkeypatch):
    monkeypatch.delenv("MQTT_BROKER_HOST", raising=False)
    admin = seed["admin"]
    skylo_source(client, admin)

    decoder = create(client, seed["owner1"], match={"providerId": "skylo", "deviceTypeId": "sensor"})

    # Not live yet: matching only uses activated versions
    assert ingest(client, admin)["status"] == "NO_ACTIVE_SCHEMA"

    activate(client, seed["owner1"], decoder["id"])

    message = ingest(client, admin)
    assert message["status"] == "ROUTED", message["error"]
    assert message["decoder_selection"] == "match"
    assert message["decode_schema_id"] == decoder["id"]
    assert message["message_ref"] == "uplink-1"
    assert message["decoded"] == {"temperature": 25, "humidity": 62}
    assert message["units"] == {"temperature": "°C", "humidity": "%RH"}

    latest = client.get("/devices/DEVICE001/latest", headers=headers(seed["owner1"])).json()
    assert latest["decode_schema_id"] == decoder["id"]
    assert latest["telemetry"] == {"temperature": 25, "humidity": 62}


def test_application_decoder_wins_over_match(client, seed, monkeypatch):
    monkeypatch.delenv("MQTT_BROKER_HOST", raising=False)
    admin, owner = seed["admin"], seed["owner1"]
    skylo_source(client, admin)

    matched = create(client, owner, match={"providerId": "skylo"}, name="matched")
    activate(client, owner, matched["id"])

    assigned = create(client, owner, code="function decode(i){ return { source: 'application' } }", name="assigned")
    client.put("/applications/1", json={"name": "App One", "decode_schema_id": assigned["id"]}, headers=headers(owner))

    message = ingest(client, admin)
    assert message["decoder_selection"] == "application"
    assert message["decoded"] == {"source": "application"}


def test_most_specific_and_own_organization_win(client, seed):
    admin, owner1, owner2 = seed["admin"], seed["owner1"], seed["owner2"]

    platform_generic = create(client, admin, name="p_generic", match={"providerId": "skylo"})
    platform_specific = create(client, admin, name="p_specific", match={"providerId": "skylo", "messageType": "status"})
    own_generic = create(client, owner1, name="own_generic", match={"providerId": "skylo"})
    other_org = create(client, owner2, name="other", match={"providerId": "skylo", "messageType": "status", "version": "2"})

    for decoder, user in [(platform_generic, admin), (platform_specific, admin), (own_generic, owner1), (other_org, owner2)]:
        activate(client, user, decoder["id"])

    def pick(**attributes):
        response = client.post("/decode-schemas/match", json=attributes, headers=headers(owner1))
        assert response.status_code == 200, response.text
        body = response.json()
        return body["decoder"]["name"] if body["decoder"] else None, [c["name"] for c in body["candidates"]]

    # More criteria wins
    assert pick(providerId="skylo", messageType="status", version="2")[0] == "p_specific"
    # Same specificity: the organization's own decoder before the platform one
    assert pick(providerId="skylo")[0] == "own_generic"
    # Another organization's decoder is never a candidate
    assert "other" not in pick(providerId="skylo", messageType="status", version="2")[1]
    # A criterion that does not fit excludes the decoder
    assert pick(providerId="sateliot") == (None, [])


def test_decoder_without_criteria_is_never_matched(client, seed):
    decoder = create(client, seed["owner1"], name="no_rule")
    activate(client, seed["owner1"], decoder["id"])

    body = client.post("/decode-schemas/match", json={"providerId": "skylo"}, headers=headers(seed["owner1"])).json()
    assert body["decoder"] is None


def test_message_context_reaches_the_decoder(client, seed, monkeypatch):
    monkeypatch.delenv("MQTT_BROKER_HOST", raising=False)
    admin = seed["admin"]
    skylo_source(client, admin)

    code = "function decode(input) { const c = input.context; return { device: c.deviceId, provider: c.providerId, kind: c.messageType, protocol: c.protocolId, type: c.deviceTypeId, ref: c.messageId }; }"
    decoder = create(client, seed["owner1"], code=code, match={"messageType": "status"})
    activate(client, seed["owner1"], decoder["id"])

    message = ingest(client, admin, messageType="status")
    assert message["status"] == "ROUTED", message["error"]
    assert message["decoded"] == {
        "device": "DEVICE001",
        "provider": "skylo",
        "kind": "status",
        "protocol": "udp",
        "type": "sensor",
        "ref": "uplink-1",
    }


# --------------------------------
# Sandbox inside the pipeline
# --------------------------------

def test_failing_decoders_are_staged_and_reprocessable(client, seed, monkeypatch):
    monkeypatch.delenv("MQTT_BROKER_HOST", raising=False)
    admin, owner = seed["admin"], seed["owner1"]
    skylo_source(client, admin)

    escape = create(client, owner, name="escape", match={"providerId": "skylo"},
                    code="function decode(i){ return { pid: this.constructor.constructor('return process')().pid } }")
    activate(client, owner, escape["id"])

    failed = ingest(client, admin)
    assert failed["status"] == "DECODE_FAILED"
    assert "Code generation from strings disallowed" in failed["error"]

    loop = create(client, owner, name="escape", match={"providerId": "skylo"}, code="function decode(){ while (true) {} }")
    activate(client, owner, loop["id"])
    assert "longer than" in ingest(client, admin)["error"]

    fixed = create(client, owner, name="escape", match={"providerId": "skylo"})
    activate(client, owner, fixed["id"])

    result = client.post("/ingest/reprocess", json={}, headers=headers(admin)).json()
    assert result["routed"] == 2


def test_incoming_message_accepts_both_spellings(client, seed, monkeypatch):
    monkeypatch.delenv("MQTT_BROKER_HOST", raising=False)
    admin = seed["admin"]

    snake = client.post(
        "/ingest/uplinks",
        json={
            "id": "a",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "transport": {"type": "mqtt", "connection_id": "gw-1"},
            "source": {"device_id": "DEVICE001"},
            "payload": {"data": base64.b64encode(PAYLOAD).decode()},
        },
        headers=headers(admin)
    )
    assert snake.status_code == 200, snake.text

    camel_array = client.post(
        "/ingest/uplinks",
        json={
            "id": "b",
            "receivedAt": datetime.now(timezone.utc).isoformat(),
            "transport": {"type": "mqtt", "connectionId": "gw-1"},
            "source": {"deviceId": "DEVICE001"},
            "payload": {"data": list(PAYLOAD)},
        },
        headers=headers(admin)
    )
    assert camel_array.status_code == 200, camel_array.text
    assert camel_array.json()["raw_payload_hex"] == PAYLOAD.hex()

    bad = client.post(
        "/ingest/uplinks",
        json={
            "id": "c",
            "receivedAt": datetime.now(timezone.utc).isoformat(),
            "transport": {"type": "mqtt"},
            "source": {},
            "payload": {"data": {"type": "Buffer", "data": [300]}},
        },
        headers=headers(admin)
    )
    assert bad.status_code == 422
