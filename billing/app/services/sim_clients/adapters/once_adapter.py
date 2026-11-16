import logging
from typing import Any, Dict, List, Optional

from app.services.once_client import OnceApiClient
from app.services.sim_clients.base import (
    BaseSimProviderClient,
    DriverMetadata,
    SimCapability,
    UnifiedConnectivityData,
    UnifiedOperationResult,
    UnifiedQuotaData,
    UnifiedSimData,
)

logger = logging.getLogger("nibiaanet.sim_clients.1nce")


class OnceProviderAdapter(BaseSimProviderClient):
    """
    Adapter integrating 1NCE Cellular IoT Management API into the Single SIM Provider Management System.
    Docs: https://help.1nce.com/api/
    """

    METADATA = DriverMetadata(
        driver_type="1nce",
        display_name="1NCE Cellular IoT",
        vendor="1NCE GmbH",
        description="Global NB-IoT, LTE-M and 2G/3G/4G connectivity for IoT across 165+ countries.",
        default_base_url="https://api.1nce.com/management-api",
        auth_type="oauth2",
        user_label="Client ID",
        secret_label="Client Secret",
        documentation_url="https://help.1nce.com/api/",
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
        self.client = OnceApiClient(
            base_url=self.base_url,
            client_id=self.api_user,
            client_secret=self.api_key,
            timeout=self.timeout,
            sandbox_mode=self.is_sandbox,
        )

    async def test_connection(self) -> Dict[str, Any]:
        return await self.client.test_connection()

    async def fetch_sims(self, limit: int = 250, offset: int = 0) -> List[UnifiedSimData]:
        raw_sims = await self.client.list_sims(page=1, page_size=limit)
        results = []
        for s in raw_sims:
            results.append(
                UnifiedSimData(
                    iccid=s.get("iccid", ""),
                    imsi=s.get("imsi"),
                    imei=s.get("imei"),
                    msisdn=s.get("msisdn"),
                    status=s.get("status", "Active"),
                    ip_address=s.get("ip_address"),
                    label=s.get("label"),
                    quota_total_mb=float(s.get("quota_total_mb", 500.0)),
                    quota_used_mb=float(s.get("quota_used_mb", 0.0)),
                    quota_remaining_mb=float(s.get("quota_remaining_mb", 500.0)),
                    sms_total=int(s.get("sms_total", 250)),
                    sms_remaining=int(s.get("sms_remaining", 250)),
                    imei_lock=bool(s.get("imei_lock", False)),
                    rat="NB-IoT / LTE-M",
                    raw_payload=s,
                )
            )
        return results

    async def get_sim_details(self, iccid: str) -> Optional[UnifiedSimData]:
        s = await self.client.get_sim(iccid)
        if not s:
            return None
        return UnifiedSimData(
            iccid=s.get("iccid", iccid),
            imsi=s.get("imsi"),
            imei=s.get("imei"),
            msisdn=s.get("msisdn"),
            status=s.get("status", "Active"),
            ip_address=s.get("ip_address"),
            label=s.get("label"),
            quota_total_mb=float(s.get("quota_total_mb", 500.0)),
            quota_used_mb=float(s.get("quota_used_mb", 0.0)),
            quota_remaining_mb=float(s.get("quota_remaining_mb", 500.0)),
            sms_total=int(s.get("sms_total", 250)),
            sms_remaining=int(s.get("sms_remaining", 250)),
            imei_lock=bool(s.get("imei_lock", False)),
            rat="NB-IoT / LTE-M",
            raw_payload=s,
        )

    async def get_quota(self, iccid: str) -> UnifiedQuotaData:
        data = await self.client.get_data_quota(iccid)
        return UnifiedQuotaData(
            iccid=iccid,
            volume_total_mb=float(data.get("volume_total_mb", 500.0)),
            volume_used_mb=float(data.get("volume_used_mb", 0.0)),
            volume_remaining_mb=float(data.get("volume_remaining_mb", 500.0)),
            expiry_date=data.get("expiry_date"),
            peak_throughput=data.get("peak_throughput"),
            threshold_percentage=data.get("threshold_percentage", 80),
            provider_raw=data,
        )

    async def get_connectivity(self, iccid: str) -> UnifiedConnectivityData:
        data = await self.client.get_connectivity_info(iccid)
        return UnifiedConnectivityData(
            iccid=iccid,
            status=data.get("status", "Unknown"),
            ip_address=data.get("ip_address"),
            rat=data.get("radio_access_technology", "NB-IoT / LTE-M"),
            cell_id=data.get("cell_id"),
            operator=data.get("operator"),
            country=data.get("country"),
            last_seen=data.get("last_seen"),
            provider_raw=data,
        )

    async def set_status(self, iccid: str, status: str, reason: Optional[str] = None) -> UnifiedOperationResult:
        res = await self.client.set_sim_status(iccid, status=status)
        return UnifiedOperationResult(
            success=True,
            status=res.get("status", status),
            action="StatusUpdate",
            message=f"1NCE SIM {iccid} updated to {status}.",
            details=res,
        )

    async def reset_connection(self, iccid: str) -> UnifiedOperationResult:
        res = await self.client.reset_sim(iccid)
        return UnifiedOperationResult(
            success=True,
            status=res.get("status", "ResetInitiated"),
            action="ResetConnectivity",
            message=res.get("message", "1NCE connectivity reset initiated."),
            details=res,
        )

    async def topup(self, iccid: str, volume_mb: float) -> UnifiedOperationResult:
        res = await self.client.topup_quota(iccid, volume_mb=volume_mb)
        return UnifiedOperationResult(
            success=True,
            status="Applied",
            action="TopupQuota",
            message=f"Added {volume_mb} MB to 1NCE SIM {iccid}.",
            details=res,
        )

    async def send_sms(self, iccid: str, payload: str, source: str = "NibiaaNet") -> UnifiedOperationResult:
        res = await self.client.send_sms(iccid, payload=payload, source_address=source)
        return UnifiedOperationResult(
            success=True,
            status=res.get("status", "Sent"),
            action="SendSms",
            message="1NCE MT-SMS dispatched successfully.",
            details=res,
        )
