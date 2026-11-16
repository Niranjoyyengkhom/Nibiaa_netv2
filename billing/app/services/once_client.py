import os
import time
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("nibiaanet.1nce")


class OnceApiClient:
    """
    Client for the 1NCE Management API (Cellular IoT).
    Docs: https://help.1nce.com/api/ and https://help.1nce.com/dev-hub

    Supports:
    - OAuth 2.0 Client Credentials token management with caching
    - SIM Inventory (`GET /management-api/v1/sims`)
    - SIM Details (`GET /management-api/v1/sims/{iccid}`)
    - SIM Data Quota (`GET /management-api/v1/sims/{iccid}/quota/data`)
    - SIM SMS Quota (`GET /management-api/v1/sims/{iccid}/quota/sms`)
    - SIM Usage Consumption (`GET /management-api/v1/sims/{iccid}/usage`)
    - Real-time Connectivity Info (`GET /management-api/v1/sims/{iccid}/connectivity_info`)
    - Lifecycle Status Updates (`POST /management-api/v1/sims/{iccid}/status`)
    - Connectivity Reset (`POST /management-api/v1/sims/{iccid}/reset`)
    - Quota Top-up (`POST /management-api/v1/sims/{iccid}/quota/topup`)
    - MT-SMS Dispatch (`POST /management-api/v1/sims/{iccid}/sms`)

    Includes a full-featured Sandbox/Mock fallback for testing and development.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        timeout: float = 15.0,
        sandbox_mode: Optional[bool] = None,
    ):
        self.base_url = (
            base_url
            or os.getenv("ONCE_API_BASE_URL")
            or "https://api.1nce.com/management-api"
        ).rstrip("/")
        self.client_id = client_id or os.getenv("ONCE_CLIENT_ID") or os.getenv("ONCE_USERNAME") or ""
        self.client_secret = (
            client_secret or os.getenv("ONCE_CLIENT_SECRET") or os.getenv("ONCE_PASSWORD") or ""
        )
        self.timeout = timeout
        self._sandbox_mode = sandbox_mode

        # Token caching
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        # In-memory sandbox storage for mock testing
        self._mock_sims: Dict[str, Dict[str, Any]] = {
            "8988280666000000001": {
                "iccid": "8988280666000000001",
                "imei": "356938035643801",
                "imsi": "901405111111111",
                "msisdn": "423661111111",
                "ip_address": "10.12.34.101",
                "label": "Cold-Chain Sensor Alpha",
                "status": "Active",
                "imei_lock": False,
                "quota_total_mb": 500.0,
                "quota_remaining_mb": 345.2,
                "quota_used_mb": 154.8,
                "sms_total": 250,
                "sms_remaining": 220,
                "activation_date": "2024-01-10T08:00:00Z",
                "expiry_date": "2034-01-10T08:00:00Z",
                "radio_access_technology": "NB-IoT",
                "cell_id": "2080145",
                "connected": True,
            },
            "8988280666000000002": {
                "iccid": "8988280666000000002",
                "imei": "356938035643802",
                "imsi": "901405111111112",
                "msisdn": "423661111112",
                "ip_address": "10.12.34.102",
                "label": "Asset Tracker Beta",
                "status": "Active",
                "imei_lock": True,
                "quota_total_mb": 500.0,
                "quota_remaining_mb": 491.0,
                "quota_used_mb": 9.0,
                "sms_total": 250,
                "sms_remaining": 245,
                "activation_date": "2024-02-15T11:30:00Z",
                "expiry_date": "2034-02-15T11:30:00Z",
                "radio_access_technology": "LTE-M",
                "cell_id": "2080199",
                "connected": True,
            },
            "8988280666000000003": {
                "iccid": "8988280666000000003",
                "imei": "356938035643803",
                "imsi": "901405111111113",
                "msisdn": "423661111113",
                "ip_address": "10.12.34.103",
                "label": "Water Meter Gamma",
                "status": "Suspended",
                "imei_lock": False,
                "quota_total_mb": 500.0,
                "quota_remaining_mb": 0.0,
                "quota_used_mb": 500.0,
                "sms_total": 250,
                "sms_remaining": 0,
                "activation_date": "2023-11-01T09:00:00Z",
                "expiry_date": "2033-11-01T09:00:00Z",
                "radio_access_technology": "NB-IoT",
                "cell_id": "2080312",
                "connected": False,
            },
        }

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def is_mock_mode(self) -> bool:
        if self._sandbox_mode is not None:
            return self._sandbox_mode
        forced_mock = os.getenv("ONCE_SANDBOX_MODE", "").lower() in ("true", "1", "yes")
        return forced_mock or not self.is_configured

    async def get_access_token(self) -> str:
        """
        Obtains or returns an unexpired cached Bearer access token.
        POST /management-api/oauth/token
        """
        if self.is_mock_mode:
            return "mock-1nce-bearer-token-valid"

        now = time.time()
        if self._access_token and now < (self._token_expires_at - 60):
            return self._access_token

        token_url = f"{self.base_url}/oauth/token"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # 1NCE accepts client credentials in JSON or basic auth
                payload = {
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                }
                resp = await client.post(token_url, json=payload)
                if resp.status_code != 200:
                    # Retry with username/password format
                    alt_payload = {
                        "grant_type": "client_credentials",
                        "username": self.client_id,
                        "password": self.client_secret,
                    }
                    resp = await client.post(token_url, json=alt_payload)

                resp.raise_for_status()
                data = resp.json()
                self._access_token = data.get("access_token")
                expires_in = int(data.get("expires_in", 3600))
                self._token_expires_at = now + expires_in
                return self._access_token
            except Exception as e:
                logger.error(f"1NCE OAuth token acquisition failed: {e}")
                raise RuntimeError(f"1NCE API authentication error: {e}")

    async def test_connection(self) -> Dict[str, Any]:
        """
        Verifies connectivity and credentials against 1NCE API.
        """
        t0 = time.time()
        if self.is_mock_mode:
            return {
                "success": True,
                "mode": "sandbox_mock",
                "message": "Connected to 1NCE Mock Engine. 3 virtual SIMs available.",
                "latency_ms": round((time.time() - t0) * 1000, 2),
                "details": {
                    "base_url": self.base_url,
                    "sim_count": len(self._mock_sims),
                    "note": "Provide ONCE_CLIENT_ID and ONCE_CLIENT_SECRET to enable live 1NCE API calls.",
                },
            }

        try:
            token = await self.get_access_token()
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/v1/sims?pageSize=1", headers=headers)
                resp.raise_for_status()
            latency = round((time.time() - t0) * 1000, 2)
            return {
                "success": True,
                "mode": "live",
                "message": "1NCE Management API connection verified successfully.",
                "latency_ms": latency,
                "details": {
                    "base_url": self.base_url,
                    "status_code": resp.status_code,
                },
            }
        except Exception as e:
            return {
                "success": False,
                "mode": "live",
                "message": f"Connection to 1NCE API failed: {e}",
                "latency_ms": round((time.time() - t0) * 1000, 2),
                "details": {"error": str(e)},
            }

    async def list_sims(
        self,
        page: int = 1,
        page_size: int = 50,
        query: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetches SIM cards list from 1NCE API.
        GET /management-api/v1/sims
        """
        if self.is_mock_mode:
            sims = list(self._mock_sims.values())
            if query:
                q_low = query.lower()
                sims = [
                    s for s in sims
                    if q_low in s["iccid"].lower()
                    or (s.get("label") and q_low in s["label"].lower())
                    or (s.get("imei") and q_low in s["imei"].lower())
                ]
            start = (page - 1) * page_size
            return sims[start : start + page_size]

        token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        params: Dict[str, Any] = {"page": page, "pageSize": page_size}
        if query:
            params["q"] = query
        if sort:
            params["sort"] = sort

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/v1/sims", headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("sims", data.get("data", []))
            return []

    async def get_sim(self, iccid: str) -> Optional[Dict[str, Any]]:
        """
        Fetches single SIM details.
        GET /management-api/v1/sims/{iccid}
        """
        if self.is_mock_mode:
            return self._mock_sims.get(iccid)

        token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/v1/sims/{iccid}", headers=headers)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def get_data_quota(self, iccid: str) -> Dict[str, Any]:
        """
        Fetches data quota and remaining volume for a SIM.
        GET /management-api/v1/sims/{iccid}/quota/data
        """
        if self.is_mock_mode:
            sim = self._mock_sims.get(iccid)
            total = sim["quota_total_mb"] if sim else 500.0
            rem = sim["quota_remaining_mb"] if sim else 450.0
            used = sim["quota_used_mb"] if sim else (total - rem)
            return {
                "iccid": iccid,
                "volume_total_mb": total,
                "volume_used_mb": round(used, 2),
                "volume_remaining_mb": round(rem, 2),
                "expiry_date": sim.get("expiry_date", "2034-01-01T00:00:00Z") if sim else "2034-01-01T00:00:00Z",
                "peak_throughput": 1000000,
                "threshold_percentage": 80,
                "provider_raw": {"simulated": True},
            }

        token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/v1/sims/{iccid}/quota/data", headers=headers)
            resp.raise_for_status()
            raw = resp.json()
            # 1NCE returns: { "volume": 500, "current_volume": 350.2, "expiry_date": ... }
            total = float(raw.get("volume", 500.0))
            rem = float(raw.get("current_volume", total))
            used = max(0.0, total - rem)
            return {
                "iccid": iccid,
                "volume_total_mb": total,
                "volume_used_mb": round(used, 2),
                "volume_remaining_mb": round(rem, 2),
                "expiry_date": raw.get("expiry_date"),
                "peak_throughput": raw.get("peak_throughput", 1000000),
                "threshold_percentage": raw.get("threshold_percentage", 80),
                "provider_raw": raw,
            }

    async def get_sms_quota(self, iccid: str) -> Dict[str, Any]:
        """
        Fetches SMS quota for a SIM.
        GET /management-api/v1/sims/{iccid}/quota/sms
        """
        if self.is_mock_mode:
            sim = self._mock_sims.get(iccid)
            total = sim["sms_total"] if sim else 250
            rem = sim["sms_remaining"] if sim else 230
            return {
                "iccid": iccid,
                "sms_total": total,
                "sms_remaining": rem,
                "sms_used": total - rem,
                "expiry_date": sim.get("expiry_date", "2034-01-01T00:00:00Z") if sim else None,
            }

        token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/v1/sims/{iccid}/quota/sms", headers=headers)
            resp.raise_for_status()
            raw = resp.json()
            total = int(raw.get("volume", 250))
            rem = int(raw.get("current_volume", total))
            return {
                "iccid": iccid,
                "sms_total": total,
                "sms_remaining": rem,
                "sms_used": max(0, total - rem),
                "expiry_date": raw.get("expiry_date"),
            }

    async def get_usage(
        self,
        iccid: str,
        start_dt: Optional[str] = None,
        end_dt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetches historical data & SMS consumption for a SIM.
        GET /management-api/v1/sims/{iccid}/usage
        """
        if self.is_mock_mode:
            # Generate simulated weekly usage points
            now_iso = datetime.now(timezone.utc).isoformat()
            points = [
                {
                    "timestamp": now_iso,
                    "data_volume_rx_bytes": 1048576 * 12,
                    "data_volume_tx_bytes": 1048576 * 4,
                    "data_volume_total_bytes": 1048576 * 16,
                    "sms_mo_count": 0,
                    "sms_mt_count": 2,
                },
                {
                    "timestamp": now_iso,
                    "data_volume_rx_bytes": 1048576 * 18,
                    "data_volume_tx_bytes": 1048576 * 6,
                    "data_volume_total_bytes": 1048576 * 24,
                    "sms_mo_count": 1,
                    "sms_mt_count": 3,
                },
            ]
            total_b = sum(p["data_volume_total_bytes"] for p in points)
            return {
                "iccid": iccid,
                "start_dt": start_dt,
                "end_dt": end_dt,
                "total_bytes": total_b,
                "total_mb": round(total_b / (1024 * 1024), 2),
                "sessions_count": len(points),
                "data_points": points,
            }

        token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        params: Dict[str, Any] = {}
        if start_dt:
            params["start_dt"] = start_dt
        if end_dt:
            params["end_dt"] = end_dt

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/v1/sims/{iccid}/usage", headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            points = data if isinstance(data, list) else data.get("usage", [])
            total_b = sum(p.get("data_volume_total_bytes", 0) for p in points)
            return {
                "iccid": iccid,
                "start_dt": start_dt,
                "end_dt": end_dt,
                "total_bytes": total_b,
                "total_mb": round(total_b / (1024 * 1024), 2),
                "sessions_count": len(points),
                "data_points": points,
            }

    async def get_connectivity_info(self, iccid: str) -> Dict[str, Any]:
        """
        Retrieves real-time network attachment status and tower info.
        GET /management-api/v1/sims/{iccid}/connectivity_info
        """
        if self.is_mock_mode:
            sim = self._mock_sims.get(iccid, {})
            is_active = sim.get("status") == "Active"
            return {
                "iccid": iccid,
                "status": "Attached" if is_active else "Detached",
                "radio_access_technology": sim.get("radio_access_technology", "NB-IoT"),
                "cell_id": sim.get("cell_id", "2080145"),
                "mcc": "208",
                "mnc": "01",
                "ip_address": sim.get("ip_address", "10.12.34.101"),
                "last_connection_date": datetime.now(timezone.utc).isoformat(),
                "roaming_network": "Orange France (208 01)",
            }

        token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/v1/sims/{iccid}/connectivity_info", headers=headers
            )
            resp.raise_for_status()
            raw = resp.json()
            return {
                "iccid": iccid,
                "status": raw.get("status", "Attached"),
                "radio_access_technology": raw.get("radio_access_technology", "NB-IoT"),
                "cell_id": str(raw.get("cell_id", "")),
                "mcc": str(raw.get("mcc", "")),
                "mnc": str(raw.get("mnc", "")),
                "ip_address": raw.get("ip_address"),
                "last_connection_date": raw.get("last_connection_date"),
                "roaming_network": raw.get("roaming_network"),
            }

    async def set_sim_status(self, iccid: str, status: str) -> Dict[str, Any]:
        """
        Updates SIM status: 'Active' or 'Suspended'.
        POST /management-api/v1/sims/{iccid}/status
        """
        norm_status = status.capitalize()
        if norm_status not in ("Active", "Suspended"):
            raise ValueError(f"Invalid status '{status}'. Must be 'Active' or 'Suspended'.")

        if self.is_mock_mode:
            if iccid in self._mock_sims:
                self._mock_sims[iccid]["status"] = norm_status
                self._mock_sims[iccid]["connected"] = (norm_status == "Active")
            return {
                "iccid": iccid,
                "status": norm_status,
                "message": f"SIM {iccid} status successfully updated to {norm_status} (Mock)",
            }

        token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/v1/sims/{iccid}/status",
                headers=headers,
                json={"status": norm_status},
            )
            resp.raise_for_status()
            return {
                "iccid": iccid,
                "status": norm_status,
                "message": f"SIM {iccid} status set to {norm_status}",
            }

    async def reset_sim(self, iccid: str) -> Dict[str, Any]:
        """
        Resets SIM connectivity at the HLR/HSS level, forcing PDP session teardown.
        POST /management-api/v1/sims/{iccid}/reset
        """
        if self.is_mock_mode:
            return {
                "iccid": iccid,
                "status": "ResetInitiated",
                "message": f"HLR connectivity reset initiated for SIM {iccid} (Mock)",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/v1/sims/{iccid}/reset", headers=headers)
            resp.raise_for_status()
            return {
                "iccid": iccid,
                "status": "ResetInitiated",
                "message": f"HLR connectivity reset triggered for SIM {iccid}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def topup_quota(self, iccid: str, volume_mb: float = 500.0) -> Dict[str, Any]:
        """
        Tops up data quota for a SIM.
        POST /management-api/v1/sims/{iccid}/quota/topup
        """
        if self.is_mock_mode:
            if iccid in self._mock_sims:
                self._mock_sims[iccid]["quota_total_mb"] += volume_mb
                self._mock_sims[iccid]["quota_remaining_mb"] += volume_mb
                if self._mock_sims[iccid]["status"] == "Suspended":
                    self._mock_sims[iccid]["status"] = "Active"
            return {
                "iccid": iccid,
                "topup_volume_mb": volume_mb,
                "new_remaining_mb": self._mock_sims.get(iccid, {}).get("quota_remaining_mb", volume_mb),
                "message": f"Top-up of {volume_mb} MB applied successfully to SIM {iccid} (Mock)",
            }

        token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/v1/sims/{iccid}/quota/topup",
                headers=headers,
                json={"volume": volume_mb},
            )
            resp.raise_for_status()
            return {
                "iccid": iccid,
                "topup_volume_mb": volume_mb,
                "message": f"Top-up of {volume_mb} MB applied to SIM {iccid}",
            }

    async def send_sms(
        self,
        iccid: str,
        payload: str,
        source_address: str = "NibiaaNet",
        source_address_type: str = "alpha",
    ) -> Dict[str, Any]:
        """
        Sends Mobile-Terminated SMS (MT-SMS) to SIM.
        POST /management-api/v1/sims/{iccid}/sms
        """
        if self.is_mock_mode:
            if iccid in self._mock_sims:
                if self._mock_sims[iccid]["sms_remaining"] > 0:
                    self._mock_sims[iccid]["sms_remaining"] -= 1
            return {
                "iccid": iccid,
                "status": "Delivered",
                "payload": payload,
                "source_address": source_address,
                "message_id": f"sms_mock_{int(time.time())}",
                "message": f"MT-SMS successfully dispatched to SIM {iccid} (Mock)",
            }

        token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {
            "payload": payload,
            "source_address": source_address,
            "source_address_type": source_address_type,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/v1/sims/{iccid}/sms", headers=headers, json=body
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "iccid": iccid,
                "status": "Sent",
                "message_id": data.get("id", str(time.time())),
                "message": f"MT-SMS sent to SIM {iccid}",
            }

    # Backward compatibility aliases for adapter callers
    async def get_sim_list(
        self,
        page: int = 1,
        pageSize: Optional[int] = None,
        page_size: Optional[int] = None,
        query: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        eff_limit = pageSize if pageSize is not None else (page_size or 50)
        return await self.list_sims(page=page, page_size=eff_limit, query=query, sort=sort)

    async def get_sim_details(self, iccid: str) -> Optional[Dict[str, Any]]:
        return await self.get_sim(iccid)

    async def update_sim_status(self, iccid: str, status: str, reason: Optional[str] = None) -> Dict[str, Any]:
        return await self.set_sim_status(iccid, status=status)

    async def reset_connectivity(self, iccid: str) -> Dict[str, Any]:
        return await self.reset_sim(iccid)


# Shared singleton instance
once_client = OnceApiClient()
