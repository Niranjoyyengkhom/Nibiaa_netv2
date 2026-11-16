import pytest
from app.services.once_client import OnceApiClient


@pytest.mark.asyncio
async def test_once_client_auth_mock():
    client = OnceApiClient(client_id="test_user", client_secret="test_secret", sandbox_mode=True)
    # In mock mode, returns valid mock token
    token = await client.get_access_token()
    assert token is not None
    assert "mock" in token


@pytest.mark.asyncio
async def test_once_client_list_sims():
    client = OnceApiClient()
    sims = await client.list_sims(page=1, page_size=10)
    assert len(sims) >= 3
    iccid = sims[0]["iccid"]
    assert iccid.startswith("898828")


@pytest.mark.asyncio
async def test_once_client_get_sim_and_quota():
    client = OnceApiClient()
    sim = await client.get_sim("8988280666000000001")
    assert sim is not None
    assert sim["status"] == "Active"

    quota = await client.get_data_quota("8988280666000000001")
    assert quota["iccid"] == "8988280666000000001"
    assert quota["volume_total_mb"] == 500.0
    assert quota["volume_remaining_mb"] > 0
    assert quota["volume_used_mb"] > 0

    sms_quota = await client.get_sms_quota("8988280666000000001")
    assert sms_quota["sms_total"] == 250
    assert sms_quota["sms_remaining"] <= 250


@pytest.mark.asyncio
async def test_once_client_usage():
    client = OnceApiClient()
    usage = await client.get_usage("8988280666000000001")
    assert usage["iccid"] == "8988280666000000001"
    assert usage["total_bytes"] > 0
    assert usage["total_mb"] > 0
    assert len(usage["data_points"]) > 0


@pytest.mark.asyncio
async def test_once_client_connectivity():
    client = OnceApiClient()
    conn = await client.get_connectivity_info("8988280666000000001")
    assert conn["status"] == "Attached"
    assert conn["radio_access_technology"] in ("NB-IoT", "LTE-M")
    assert conn["ip_address"] is not None


@pytest.mark.asyncio
async def test_once_client_lifecycle_and_reset():
    client = OnceApiClient()
    # Test status change to Suspended
    res = await client.set_sim_status("8988280666000000001", "Suspended")
    assert res["status"] == "Suspended"

    sim = await client.get_sim("8988280666000000001")
    assert sim["status"] == "Suspended"

    # Reset
    reset_res = await client.reset_sim("8988280666000000001")
    assert reset_res["status"] == "ResetInitiated"

    # Reactivate
    res_active = await client.set_sim_status("8988280666000000001", "Active")
    assert res_active["status"] == "Active"


@pytest.mark.asyncio
async def test_once_client_topup_and_sms():
    client = OnceApiClient()
    topup = await client.topup_quota("8988280666000000002", volume_mb=500.0)
    assert topup["topup_volume_mb"] == 500.0

    sms = await client.send_sms("8988280666000000002", payload="CMD#STATUS")
    assert sms["status"] == "Delivered"
    assert sms["payload"] == "CMD#STATUS"
