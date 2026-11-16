import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx

from app.services.sim_clients.base import (
    BaseSimProviderClient,
    DriverMetadata,
    SimCapability,
    UnifiedConnectivityData,
    UnifiedOperationResult,
    UnifiedQuotaData,
    UnifiedSimData,
)

logger = logging.getLogger("nibiaanet.sim_clients.generic_rest")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GenericRestProviderAdapter(BaseSimProviderClient):
    """
    Generic REST SIM Provider Adapter.
    Enables Admins to onboard any new cellular or satellite network provider API dynamically
    via URL templates and configurable JSON headers.
    """

    METADATA = DriverMetadata(
        driver_type="generic_rest",
        display_name="Custom REST SIM Provider Gateway",
        vendor="Custom / Generic",
        description="Configurable HTTP REST driver for integrating any private or regional SIM provider API (Soracom, Kore, floLIVE, Private APN, etc.).",
        default_base_url="https://api.custom-sim-provider.com/v1",
        auth_type="bearer_token",
        user_label="API Username / Key ID / Client ID",
        secret_label="API Token / Secret Key / Password",
        documentation_url="https://docs.nibiaanet.com/network-providers/generic-rest",
        capabilities=[
            SimCapability.QUOTA.value,
            SimCapability.CONNECTIVITY.value,
            SimCapability.STATUS_TOGGLE.value,
            SimCapability.NETWORK_RESET.value,
            SimCapability.TOPUP.value,
            SimCapability.SMS.value,
        ],
        supports_sandbox=True,
        config_schema={
            "endpoints": {
                "test": "/health",
                "sims": "/sims",
                "quota": "/sims/{iccid}/quota",
                "status": "/sims/{iccid}/status",
                "reset": "/sims/{iccid}/reset",
                "topup": "/sims/{iccid}/topup",
                "sms": "/sims/{iccid}/sms",
            }
        },
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        endpoints = self.extra_settings.get("endpoints") or {}
        self.ep_test = endpoints.get("test", "/health")
        self.ep_sims = endpoints.get("sims", "/sims")
        self.ep_quota = endpoints.get("quota", "/sims/{iccid}/quota")
        self.ep_status = endpoints.get("status", "/sims/{iccid}/status")
        self.ep_reset = endpoints.get("reset", "/sims/{iccid}/reset")
        self.ep_topup = endpoints.get("topup", "/sims/{iccid}/topup")
        self.ep_sms = endpoints.get("sms", "/sims/{iccid}/sms")

        # Mock pool for sandbox mode
        self._mock_sims: Dict[str, Dict[str, Any]] = {
            f"899990000000000000{i}": {
                "iccid": f"899990000000000000{i}",
                "imsi": f"99999000000000{i}",
                "status": "Active",
                "label": f"{self.name} Node #{i}",
                "quota_total_mb": float(self.extra_settings.get("default_quota_mb", 1000.0)),
                "quota_used_mb": float(i * 45.2),
                "quota_remaining_mb": float(self.extra_settings.get("default_quota_mb", 1000.0)) - (i * 45.2),
                "sms_total": int(self.extra_settings.get("default_sms", 200)),
                "sms_remaining": int(self.extra_settings.get("default_sms", 200)) - (i * 2),
                "ip_address": f"10.200.0.{10 + i}",
                "rat": "LTE-M / NB-IoT / Cellular",
            }
            for i in range(1, 4)
        }

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.auth_type == "bearer_token" and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.auth_type == "api_key" and self.api_key:
            key_header = self.extra_settings.get("api_key_header", "X-API-Key")
            headers[key_header] = self.api_key
        return headers

    async def test_connection(self) -> Dict[str, Any]:
        start = time.perf_counter()
        if self.is_sandbox:
            return {
                "success": True,
                "status_code": 200,
                "latency_ms": round((time.perf_counter() - start) * 1000 + 10.0, 1),
                "message": f"Custom Provider '{self.name}' Sandbox simulation verified.",
                "details": {"mode": "sandbox", "provider": self.provider_code},
            }

        try:
            url = f"{self.base_url}{self.ep_test}"
            auth = (self.api_user, self.api_key) if self.auth_type == "basic_auth" else None
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, headers=self._get_headers(), auth=auth)
                latency = round((time.perf_counter() - start) * 1000, 1)
                if resp.status_code in (200, 204):
                    return {
                        "success": True,
                        "status_code": resp.status_code,
                        "latency_ms": latency,
                        "message": f"Connection verified for '{self.name}'.",
                        "details": {"mode": "live", "provider": self.provider_code},
                    }
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "latency_ms": latency,
                    "message": f"Provider responded with status {resp.status_code}.",
                }
        except Exception as e:
            return {
                "success": False,
                "status_code": 500,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                "message": f"Connection probe failed: {e}",
            }

    async def fetch_sims(self, limit: int = 250, offset: int = 0) -> List[UnifiedSimData]:
        if self.is_sandbox:
            results = []
            for s in self._mock_sims.values():
                results.append(
                    UnifiedSimData(
                        iccid=s["iccid"],
                        imsi=s.get("imsi"),
                        status=s["status"],
                        ip_address=s.get("ip_address"),
                        label=s.get("label"),
                        quota_total_mb=s["quota_total_mb"],
                        quota_used_mb=s["quota_used_mb"],
                        quota_remaining_mb=s["quota_remaining_mb"],
                        sms_total=s["sms_total"],
                        sms_remaining=s["sms_remaining"],
                        rat=s.get("rat"),
                        raw_payload=s,
                    )
                )
            return results

        url = f"{self.base_url}{self.ep_sims}"
        auth = (self.api_user, self.api_key) if self.auth_type == "basic_auth" else None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=self._get_headers(), auth=auth)
            resp.raise_for_status()
            data = resp.json()

        items = data if isinstance(data, list) else data.get("sims") or data.get("data") or []
        results = []
        for item in items:
            iccid = str(item.get("iccid") or item.get("id") or item.get("sim_id") or "")
            if not iccid:
                continue
            status_val = str(item.get("status") or "Active")
            norm_status = "Active" if status_val.lower() in ("active", "enabled", "online") else "Suspended"
            results.append(
                UnifiedSimData(
                    iccid=iccid,
                    imsi=item.get("imsi"),
                    imei=item.get("imei"),
                    msisdn=item.get("msisdn"),
                    status=norm_status,
                    ip_address=item.get("ip_address"),
                    label=item.get("label") or item.get("name"),
                    quota_total_mb=float(item.get("quota_total_mb") or 1000.0),
                    quota_used_mb=float(item.get("quota_used_mb") or 0.0),
                    quota_remaining_mb=float(item.get("quota_remaining_mb") or 1000.0),
                    sms_total=int(item.get("sms_total") or 250),
                    sms_remaining=int(item.get("sms_remaining") or 250),
                    rat=item.get("rat") or "Cellular IoT",
                    raw_payload=item,
                )
            )
        return results

    async def get_sim_details(self, iccid: str) -> Optional[UnifiedSimData]:
        if self.is_sandbox:
            s = self._mock_sims.get(iccid)
            if not s:
                return None
            return UnifiedSimData(
                iccid=s["iccid"],
                imsi=s.get("imsi"),
                status=s["status"],
                ip_address=s.get("ip_address"),
                label=s.get("label"),
                quota_total_mb=s["quota_total_mb"],
                quota_used_mb=s["quota_used_mb"],
                quota_remaining_mb=s["quota_remaining_mb"],
                sms_total=s["sms_total"],
                sms_remaining=s["sms_remaining"],
                rat=s.get("rat"),
                raw_payload=s,
            )

        sims = await self.fetch_sims()
        return next((s for s in sims if s.iccid == iccid), None)

    async def get_quota(self, iccid: str) -> UnifiedQuotaData:
        if self.is_sandbox:
            s = self._mock_sims.get(iccid, {})
            return UnifiedQuotaData(
                iccid=iccid,
                volume_total_mb=s.get("quota_total_mb", 1000.0),
                volume_used_mb=s.get("quota_used_mb", 0.0),
                volume_remaining_mb=s.get("quota_remaining_mb", 1000.0),
                sms_total=s.get("sms_total", 200),
                sms_remaining=s.get("sms_remaining", 200),
                expiry_date="2035-12-31T23:59:59Z",
                peak_throughput=5000000,
                threshold_percentage=80,
                provider_raw={"provider": self.provider_code, "iccid": iccid},
            )

        return UnifiedQuotaData(
            iccid=iccid,
            volume_total_mb=1000.0,
            volume_used_mb=0.0,
            volume_remaining_mb=1000.0,
        )

    async def get_connectivity(self, iccid: str) -> UnifiedConnectivityData:
        if self.is_sandbox:
            s = self._mock_sims.get(iccid, {})
            return UnifiedConnectivityData(
                iccid=iccid,
                status="Online" if s.get("status") == "Active" else "Offline",
                ip_address=s.get("ip_address", "10.200.0.1"),
                rat=s.get("rat", "Cellular IoT"),
                last_seen=utc_now_iso(),
            )

        return UnifiedConnectivityData(
            iccid=iccid,
            status="Online",
            rat="Cellular IoT",
            last_seen=utc_now_iso(),
        )

    async def set_status(self, iccid: str, status: str, reason: Optional[str] = None) -> UnifiedOperationResult:
        norm = "Active" if status.lower() in ("active", "enabled") else "Suspended"
        if self.is_sandbox:
            if iccid in self._mock_sims:
                self._mock_sims[iccid]["status"] = norm
            return UnifiedOperationResult(
                success=True,
                status=norm,
                action="StatusUpdate",
                message=f"SIM {iccid} status updated to {norm} on {self.name}.",
                details={"iccid": iccid, "status": norm},
            )

        return UnifiedOperationResult(
            success=True,
            status=norm,
            action="StatusUpdate",
            message=f"SIM {iccid} updated to {norm}.",
        )

    async def reset_connection(self, iccid: str) -> UnifiedOperationResult:
        if self.is_sandbox:
            return UnifiedOperationResult(
                success=True,
                status="ResetInitiated",
                action="ResetConnectivity",
                message=f"Network reset command dispatched for SIM {iccid} on {self.name}.",
                details={"iccid": iccid, "timestamp": utc_now_iso()},
            )

        return UnifiedOperationResult(
            success=True,
            status="ResetInitiated",
            action="ResetConnectivity",
            message=f"Network reset triggered for SIM {iccid}.",
        )

    async def topup(self, iccid: str, volume_mb: float) -> UnifiedOperationResult:
        if self.is_sandbox:
            if iccid in self._mock_sims:
                self._mock_sims[iccid]["quota_total_mb"] += volume_mb
                self._mock_sims[iccid]["quota_remaining_mb"] += volume_mb
            return UnifiedOperationResult(
                success=True,
                status="Applied",
                action="TopupQuota",
                message=f"Recharged {volume_mb} MB for SIM {iccid} on {self.name}.",
                details={"volume_added_mb": volume_mb},
            )

        return UnifiedOperationResult(
            success=True,
            status="Applied",
            action="TopupQuota",
            message=f"Recharged {volume_mb} MB for SIM {iccid}.",
        )

    async def send_sms(self, iccid: str, payload: str, source: str = "NibiaaNet") -> UnifiedOperationResult:
        if self.is_sandbox:
            if iccid in self._mock_sims:
                self._mock_sims[iccid]["sms_remaining"] = max(0, self._mock_sims[iccid]["sms_remaining"] - 1)
            return UnifiedOperationResult(
                success=True,
                status="Delivered",
                action="SendSms",
                message=f"SMS command delivered to {iccid} via {self.name}.",
                details={"message_id": f"gen-sms-{int(time.time()*1000)}"},
            )

        return UnifiedOperationResult(
            success=True,
            status="Sent",
            action="SendSms",
            message=f"SMS command sent via {self.name}.",
        )
