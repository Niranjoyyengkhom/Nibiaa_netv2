import logging
from typing import Any, Dict, List, Optional

from app.services.monogoto_client import MonogotoApiClient
from app.services.sim_clients.base import (
    BaseSimProviderClient,
    DriverMetadata,
    SimCapability,
    UnifiedConnectivityData,
    UnifiedOperationResult,
    UnifiedQuotaData,
    UnifiedSimData,
)

logger = logging.getLogger("nibiaanet.sim_clients.monogoto")


class MonogotoProviderAdapter(BaseSimProviderClient):
    """
    Adapter integrating Monogoto Developer API into the Single SIM Provider Management System.
    Docs: https://developer.monogoto.io/overview
    """

    METADATA = DriverMetadata(
        driver_type="monogoto",
        display_name="Monogoto Global Cellular",
        vendor="Monogoto Ltd.",
        description="Software-defined connectivity for IoT, Private LTE/5G, and satellite with real-time network API control.",
        default_base_url="https://api.monogoto.io",
        auth_type="bearer_token",
        user_label="Monogoto Username / Email",
        secret_label="Monogoto Password",
        documentation_url="https://developer.monogoto.io/overview",
        capabilities=[
            SimCapability.QUOTA.value,
            SimCapability.CONNECTIVITY.value,
            SimCapability.STATUS_TOGGLE.value,
            SimCapability.NETWORK_RESET.value,
            SimCapability.TOPUP.value,
            SimCapability.SMS.value,
            SimCapability.IMEI_LOCK.value,
            SimCapability.USAGE_HISTORY.value,
        ],
        supports_sandbox=True,
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = MonogotoApiClient(
            base_url=self.base_url,
            username=self.api_user,
            password=self.api_key,
            timeout=self.timeout,
            sandbox_mode=self.is_sandbox,
        )

    async def test_connection(self) -> Dict[str, Any]:
        return await self.client.test_connection()

    async def fetch_sims(self, limit: int = 250, offset: int = 0) -> List[UnifiedSimData]:
        raw_things = await self.client.list_things(limit=limit, offset=offset)
        results = []
        for t in raw_things:
            iccid = t.get("iccid") or t.get("Id") or t.get("ThingId") or ""
            status_val = t.get("status", "ACTIVE")
            norm_status = "Active" if str(status_val).upper() in ("ACTIVE", "ENABLED", "ONLINE") else "Suspended"

            results.append(
                UnifiedSimData(
                    iccid=iccid,
                    imsi=t.get("imsi"),
                    imei=t.get("imei"),
                    msisdn=t.get("msisdn"),
                    status=norm_status,
                    ip_address=t.get("ip_address") or t.get("last_ip"),
                    label=t.get("name") or t.get("label"),
                    quota_total_mb=float(t.get("quota_total_mb", 1000.0)),
                    quota_used_mb=float(t.get("quota_used_mb", 0.0)),
                    quota_remaining_mb=float(t.get("quota_remaining_mb", 1000.0)),
                    sms_total=int(t.get("sms_total", 500)),
                    sms_remaining=int(t.get("sms_remaining", 500)),
                    imei_lock=bool(t.get("imei_lock", False)),
                    rat=t.get("rat", "LTE-M / NB-IoT / 5G"),
                    raw_payload=t,
                )
            )
        return results

    async def get_sim_details(self, iccid: str) -> Optional[UnifiedSimData]:
        t = await self.client.get_thing_details(iccid)
        if not t:
            return None
        status_val = t.get("status", "ACTIVE")
        norm_status = "Active" if str(status_val).upper() in ("ACTIVE", "ENABLED", "ONLINE") else "Suspended"

        return UnifiedSimData(
            iccid=t.get("iccid", iccid),
            imsi=t.get("imsi"),
            imei=t.get("imei"),
            msisdn=t.get("msisdn"),
            status=norm_status,
            ip_address=t.get("ip_address"),
            label=t.get("name") or t.get("label"),
            quota_total_mb=float(t.get("quota_total_mb", 1000.0)),
            quota_used_mb=float(t.get("quota_used_mb", 0.0)),
            quota_remaining_mb=float(t.get("quota_remaining_mb", 1000.0)),
            sms_total=int(t.get("sms_total", 500)),
            sms_remaining=int(t.get("sms_remaining", 500)),
            imei_lock=bool(t.get("imei_lock", False)),
            rat=t.get("rat", "LTE-M / NB-IoT / 5G"),
            raw_payload=t,
        )

    async def get_quota(self, iccid: str) -> UnifiedQuotaData:
        data = await self.client.get_thing_quota(iccid)
        return UnifiedQuotaData(
            iccid=iccid,
            volume_total_mb=float(data.get("volume_total_mb", 1000.0)),
            volume_used_mb=float(data.get("volume_used_mb", 0.0)),
            volume_remaining_mb=float(data.get("volume_remaining_mb", 1000.0)),
            expiry_date=data.get("expiry_date"),
            peak_throughput=data.get("peak_throughput"),
            threshold_percentage=data.get("threshold_percentage", 90),
            provider_raw=data,
        )

    async def get_connectivity(self, iccid: str) -> UnifiedConnectivityData:
        data = await self.client.get_thing_status(iccid)
        return UnifiedConnectivityData(
            iccid=iccid,
            status=data.get("status", "Unknown"),
            ip_address=data.get("ip_address"),
            rat=data.get("radio_access_technology", "LTE-M"),
            cell_id=data.get("cell_id"),
            operator=data.get("operator"),
            country=data.get("country"),
            last_seen=data.get("last_seen"),
            provider_raw=data,
        )

    async def set_status(self, iccid: str, status: str, reason: Optional[str] = None) -> UnifiedOperationResult:
        res = await self.client.update_thing_status(iccid, status=status, reason=reason)
        return UnifiedOperationResult(
            success=True,
            status=res.get("status", status),
            action="StatusUpdate",
            message=res.get("message", f"Monogoto Thing {iccid} updated to {status}."),
            details=res,
        )

    async def reset_connection(self, iccid: str) -> UnifiedOperationResult:
        res = await self.client.refresh_connection(iccid)
        return UnifiedOperationResult(
            success=True,
            status=res.get("status", "ResetInitiated"),
            action="RefreshConnection",
            message=res.get("message", f"Monogoto network refresh initiated for {iccid}."),
            details=res,
        )

    async def topup(self, iccid: str, volume_mb: float) -> UnifiedOperationResult:
        res = await self.client.topup_quota(iccid, volume_mb=volume_mb)
        return UnifiedOperationResult(
            success=True,
            status="Applied",
            action="TopupQuota",
            message=res.get("message", f"Recharged {volume_mb} MB for Monogoto Thing {iccid}."),
            details=res,
        )

    async def send_sms(self, iccid: str, payload: str, source: str = "NibiaaNet") -> UnifiedOperationResult:
        res = await self.client.send_sms(iccid, payload=payload, source_address=source)
        return UnifiedOperationResult(
            success=True,
            status=res.get("status", "Sent"),
            action="SendSms",
            message="Monogoto MT-SMS command dispatched successfully.",
            details=res,
        )
