import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger("nibiaanet.monogoto")

DEFAULT_MONOGOTO_BASE_URL = "https://api.monogoto.io"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MonogotoApiClient:
    """
    Client for Monogoto Developer IoT Connectivity Management API.
    Specification: https://developer.monogoto.io/overview

    Features:
    - OAuth2 Password Grant authentication (/v1/auth/token)
    - Bearer JWT token caching and auto-renewal
    - Things (SIM) Fleet inventory and lifecycle management (/v1/things)
    - Network session diagnostics and Radio Access Technology (/v1/things/status)
    - Status management (ACTIVE, SUSPENDED, BLOCKED)
    - Soft connection refresh (HLR core detach-reattach)
    - Data usage & balance monitoring
    - Mobile-Terminated SMS (MT-SMS) command dispatch
    - Seamless Sandbox / Mock mode for offline development and testing
    """

    def __init__(
        self,
        base_url: str = DEFAULT_MONOGOTO_BASE_URL,
        username: str = "",
        password: str = "",
        sandbox_mode: bool = True,
        timeout: float = 12.0,
    ):
        self.base_url = (base_url or DEFAULT_MONOGOTO_BASE_URL).rstrip("/")
        self.username = username
        self.password = password
        self.sandbox_mode = sandbox_mode or (not username and not password)
        self.timeout = timeout

        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

        # Simulated sandbox state
        self._mock_things: Dict[str, Dict[str, Any]] = {
            "8988280666000000091": {
                "iccid": "8988280666000000091",
                "imsi": "901405111111191",
                "msisdn": "+14155552671",
                "ip_address": "100.64.12.91",
                "name": "Monogoto Solar Gate 01",
                "status": "ACTIVE",
                "imei": "356938035643891",
                "quota_total_mb": 1000.0,
                "quota_used_mb": 142.50,
                "quota_remaining_mb": 857.50,
                "sms_total": 500,
                "sms_remaining": 460,
                "rat": "LTE-M",
                "cell_id": "8472910",
                "roaming_operator": "AT&T Mobility (310-410)",
            },
            "8988280666000000092": {
                "iccid": "8988280666000000092",
                "imsi": "901405111111192",
                "msisdn": "+14155552672",
                "ip_address": "100.64.12.92",
                "name": "Monogoto Cold Chain 02",
                "status": "ACTIVE",
                "imei": "356938035643892",
                "quota_total_mb": 1000.0,
                "quota_used_mb": 89.20,
                "quota_remaining_mb": 910.80,
                "sms_total": 500,
                "sms_remaining": 490,
                "rat": "NB-IoT",
                "cell_id": "9921401",
                "roaming_operator": "T-Mobile USA (310-260)",
            },
            "8988280666000000093": {
                "iccid": "8988280666000000093",
                "imsi": "901405111111193",
                "msisdn": "+14155552673",
                "ip_address": "100.64.12.93",
                "name": "Monogoto Smart Meter 03",
                "status": "SUSPENDED",
                "imei": "356938035643893",
                "quota_total_mb": 1000.0,
                "quota_used_mb": 995.00,
                "quota_remaining_mb": 5.00,
                "sms_total": 500,
                "sms_remaining": 12,
                "rat": "LTE-Cat-1",
                "cell_id": "4561023",
                "roaming_operator": "Vodafone Global (204-04)",
            },
        }

    # -------------------------------------------------------------------------
    # Authentication & Token Caching
    # -------------------------------------------------------------------------

    async def get_access_token(self, force_refresh: bool = False) -> str:
        """
        Retrieves or proactively refreshes Monogoto JWT access token.
        Token is acquired via POST /v1/auth/token and cached in memory.
        """
        if self.sandbox_mode:
            return "mock_monogoto_bearer_jwt_token_9999"

        now = time.time()
        if not force_refresh and self._access_token and now < (self._token_expires_at - 180):
            return self._access_token

        async with self._token_lock:
            if not force_refresh and self._access_token and now < (self._token_expires_at - 180):
                return self._access_token

            auth_url = f"{self.base_url}/v1/auth/token"
            payload = {
                "username": self.username,
                "password": self.password,
            }

            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(auth_url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()

                    self._access_token = data.get("access_token") or data.get("token")
                    self._refresh_token = data.get("refresh_token")
                    expires_in = data.get("expires_in", 14400)  # Monogoto default 4 hours
                    self._token_expires_at = now + float(expires_in)
                    logger.info("Successfully authenticated with Monogoto Developer API.")
                    return self._access_token or ""
            except Exception as e:
                logger.error(f"Monogoto authentication failed: {e}")
                raise RuntimeError(f"Monogoto API Authentication failed: {e}")

    async def _headers(self) -> Dict[str, str]:
        token = await self.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "NibiaaNet-IoT-Platform/2.0",
        }

    # -------------------------------------------------------------------------
    # Things (SIM Fleet) Management
    # -------------------------------------------------------------------------

    async def list_things(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """
        Fetches list of Things (SIMs) from Monogoto API: GET /v1/things
        """
        if self.sandbox_mode:
            return list(self._mock_things.values())

        url = f"{self.base_url}/v1/things"
        params = {"limit": limit, "offset": offset}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = await self._headers()
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("things", data.get("items", []))

    async def get_thing_details(self, iccid: str) -> Dict[str, Any]:
        """
        Fetches specific Thing metadata: GET /v1/things/{iccid}
        """
        if self.sandbox_mode:
            if iccid in self._mock_things:
                return self._mock_things[iccid]
            # Generate simulated record on the fly for any new ICCID
            return {
                "iccid": iccid,
                "imsi": f"901405{iccid[-9:]}",
                "msisdn": "+14155550000",
                "ip_address": "100.64.0.10",
                "name": f"Monogoto Thing {iccid[-4:]}",
                "status": "ACTIVE",
                "imei": "356938035643800",
                "quota_total_mb": 1000.0,
                "quota_used_mb": 50.0,
                "quota_remaining_mb": 950.0,
                "sms_total": 500,
                "sms_remaining": 490,
                "rat": "LTE-M",
                "cell_id": "1002003",
                "roaming_operator": "Monogoto Global",
            }

        url = f"{self.base_url}/v1/things/{iccid}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = await self._headers()
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def get_thing_status(self, iccid: str) -> Dict[str, Any]:
        """
        Fetches live network connectivity and session status from Monogoto.
        Endpoint: GET /v1/things/status or GET /v1/things/{iccid}/status
        """
        if self.sandbox_mode:
            thing = await self.get_thing_details(iccid)
            return {
                "iccid": iccid,
                "status": "Attached" if thing.get("status") == "ACTIVE" else "Detached",
                "radio_access_technology": thing.get("rat", "LTE-M"),
                "cell_id": thing.get("cell_id", "8472910"),
                "mcc": "310",
                "mnc": "410",
                "ip_address": thing.get("ip_address", "100.64.12.91"),
                "roaming_network": thing.get("roaming_operator", "AT&T Mobility (310-410)"),
                "last_connection_date": utc_now().isoformat(),
            }

        url = f"{self.base_url}/v1/things/{iccid}/status"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = await self._headers()
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def get_thing_quota(self, iccid: str) -> Dict[str, Any]:
        """
        Retrieves data quota and consumption metrics for a Thing.
        """
        if self.sandbox_mode:
            thing = await self.get_thing_details(iccid)
            return {
                "iccid": iccid,
                "volume_total_mb": thing.get("quota_total_mb", 1000.0),
                "volume_used_mb": thing.get("quota_used_mb", 0.0),
                "volume_remaining_mb": thing.get("quota_remaining_mb", 1000.0),
                "expiry_date": "2030-12-31T23:59:59Z",
                "peak_throughput": 5000000,
                "threshold_percentage": 90,
                "provider_raw": {"provider": "monogoto", "thing": thing},
            }

        # Real Monogoto request
        thing = await self.get_thing_details(iccid)
        total = float(thing.get("quota_total_mb") or thing.get("dataLimitMb") or 1000.0)
        used = float(thing.get("quota_used_mb") or thing.get("dataConsumedMb") or 0.0)
        remaining = max(0.0, total - used)
        return {
            "iccid": iccid,
            "volume_total_mb": round(total, 2),
            "volume_used_mb": round(used, 2),
            "volume_remaining_mb": round(remaining, 2),
            "expiry_date": thing.get("expirationDate"),
            "provider_raw": thing,
        }

    async def update_thing_status(self, iccid: str, status: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Updates SIM status in Monogoto network core.
        Valid status values: 'ACTIVE', 'SUSPENDED', 'BLOCKED'
        """
        norm_status = "ACTIVE" if status.upper() in ("ACTIVE", "ENABLE") else "SUSPENDED"

        if self.sandbox_mode:
            if iccid in self._mock_things:
                self._mock_things[iccid]["status"] = norm_status
            return {
                "iccid": iccid,
                "status": "Active" if norm_status == "ACTIVE" else "Suspended",
                "message": f"Monogoto Thing {iccid} updated to {norm_status}.",
                "updated_at": utc_now().isoformat(),
            }

        url = f"{self.base_url}/v1/things/{iccid}/status"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = await self._headers()
            resp = await client.post(url, json={"status": norm_status, "reason": reason}, headers=headers)
            resp.raise_for_status()
            return {
                "iccid": iccid,
                "status": "Active" if norm_status == "ACTIVE" else "Suspended",
                "raw_response": resp.json(),
            }

    async def refresh_connection(self, iccid: str) -> Dict[str, Any]:
        """
        Triggers a network soft reset ('Refresh Connection') on Monogoto core.
        Forces the device modem to detach and re-register with MME/SGSN.
        """
        if self.sandbox_mode:
            return {
                "iccid": iccid,
                "status": "ResetInitiated",
                "action": "RefreshConnection",
                "message": f"Monogoto network session refreshed for {iccid}.",
                "timestamp": utc_now().isoformat(),
            }

        url = f"{self.base_url}/v1/things/{iccid}/refresh"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = await self._headers()
            resp = await client.post(url, headers=headers)
            resp.raise_for_status()
            return {
                "iccid": iccid,
                "status": "ResetInitiated",
                "action": "RefreshConnection",
                "raw_response": resp.json(),
            }

    async def topup_quota(self, iccid: str, volume_mb: float = 500.0) -> Dict[str, Any]:
        """
        Recharges or adds data quota to a Monogoto Thing.
        """
        if self.sandbox_mode:
            if iccid in self._mock_things:
                self._mock_things[iccid]["quota_total_mb"] += volume_mb
                self._mock_things[iccid]["quota_remaining_mb"] += volume_mb
            return {
                "iccid": iccid,
                "volume_added_mb": volume_mb,
                "status": "Applied",
                "message": f"Recharged {volume_mb} MB for Monogoto Thing {iccid}.",
                "timestamp": utc_now().isoformat(),
            }

        url = f"{self.base_url}/v1/things/{iccid}/recharge"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = await self._headers()
            resp = await client.post(url, json={"volume_mb": volume_mb}, headers=headers)
            resp.raise_for_status()
            return {
                "iccid": iccid,
                "volume_added_mb": volume_mb,
                "status": "Applied",
                "raw_response": resp.json(),
            }

    async def send_sms(
        self,
        iccid: str,
        payload: str,
        source_address: str = "NibiaaNet",
    ) -> Dict[str, Any]:
        """
        Dispatches Mobile-Terminated SMS (MT-SMS) command via Monogoto API.
        Endpoint: POST /v1/things/sms/send/{iccid}
        """
        if self.sandbox_mode:
            if iccid in self._mock_things:
                self._mock_things[iccid]["sms_remaining"] = max(0, self._mock_things[iccid]["sms_remaining"] - 1)
            return {
                "iccid": iccid,
                "payload": payload,
                "status": "Delivered",
                "source_address": source_address,
                "message_id": f"msg-mg-{int(time.time()*1000)}",
                "timestamp": utc_now().isoformat(),
            }

        url = f"{self.base_url}/v1/things/sms/send/{iccid}"
        body = {
            "message": payload,
            "sender": source_address,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = await self._headers()
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            return {
                "iccid": iccid,
                "payload": payload,
                "status": "Sent",
                "raw_response": resp.json(),
            }

    async def test_connection(self) -> Dict[str, Any]:
        """
        Validates credentials and connectivity to Monogoto Developer API.
        Returns latency and account verification info.
        """
        t0 = time.time()
        if self.sandbox_mode:
            return {
                "success": True,
                "latency_ms": 12.5,
                "status_code": 200,
                "message": "Monogoto API Sandbox connection verified (offline simulation mode).",
                "endpoint": f"{self.base_url}/v1/things",
                "auth_type": "OAuth2 / Bearer Token",
                "things_found": len(self._mock_things),
            }

        try:
            token = await self.get_access_token(force_refresh=True)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
                resp = await client.get(f"{self.base_url}/v1/things", params={"limit": 1}, headers=headers)
                latency = round((time.time() - t0) * 1000, 2)
                resp.raise_for_status()
                return {
                    "success": True,
                    "latency_ms": latency,
                    "status_code": resp.status_code,
                    "message": "Successfully connected and authenticated with Monogoto Developer API.",
                    "endpoint": f"{self.base_url}/v1/things",
                    "auth_type": "Bearer Token",
                }
        except Exception as e:
            latency = round((time.time() - t0) * 1000, 2)
            return {
                "success": False,
                "latency_ms": latency,
                "status_code": getattr(getattr(e, "response", None), "status_code", 500),
                "message": f"Monogoto API connection check failed: {e}",
            }


# Shared default singleton
monogoto_client = MonogotoApiClient()
