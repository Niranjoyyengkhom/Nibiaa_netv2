from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class SimCapability(str, Enum):
    QUOTA = "quota"
    CONNECTIVITY = "connectivity"
    STATUS_TOGGLE = "status_toggle"
    NETWORK_RESET = "network_reset"
    TOPUP = "topup"
    SMS = "sms"
    IMEI_LOCK = "imei_lock"
    USAGE_HISTORY = "usage_history"


@dataclass
class DriverMetadata:
    """Metadata describing a SIM Provider Driver for Admin discovery."""
    driver_type: str                   # e.g. "monogoto", "1nce", "emnify", "twilio", "generic_rest"
    display_name: str                  # e.g. "Monogoto Global Cellular"
    vendor: str                        # e.g. "Monogoto"
    description: str
    default_base_url: str
    auth_type: str                     # "bearer_token", "oauth2", "api_key", "basic_auth"
    user_label: str                    # e.g. "Username / Email" or "Client ID" or "Account SID"
    secret_label: str                  # e.g. "Password / API Token" or "Client Secret" or "Auth Token"
    documentation_url: str
    capabilities: List[str]            # List of SimCapability strings
    supports_sandbox: bool = True
    config_schema: Optional[Dict[str, Any]] = None


@dataclass
class UnifiedSimData:
    """Standardized representation of a SIM card / IoT Thing across all providers."""
    iccid: str
    imsi: Optional[str] = None
    imei: Optional[str] = None
    msisdn: Optional[str] = None
    status: str = "Active"             # "Active", "Suspended", "Inactive", "Terminated"
    ip_address: Optional[str] = None
    label: Optional[str] = None
    quota_total_mb: float = 500.0
    quota_used_mb: float = 0.0
    quota_remaining_mb: float = 500.0
    sms_total: int = 250
    sms_remaining: int = 250
    imei_lock: bool = False
    rat: Optional[str] = None          # Radio Access Technology (LTE-M, NB-IoT, 5G, 4G, 2G)
    activation_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    raw_payload: Optional[Dict[str, Any]] = None


@dataclass
class UnifiedQuotaData:
    """Standardized data quota metrics from any provider."""
    iccid: str
    volume_total_mb: float
    volume_used_mb: float
    volume_remaining_mb: float
    sms_total: Optional[int] = None
    sms_used: Optional[int] = None
    sms_remaining: Optional[int] = None
    expiry_date: Optional[str] = None
    peak_throughput: Optional[int] = None
    threshold_percentage: Optional[int] = 80
    provider_raw: Optional[Dict[str, Any]] = None


@dataclass
class UnifiedConnectivityData:
    """Standardized real-time connectivity status from any provider core."""
    iccid: str
    status: str                        # "Online", "Offline", "Attached", "Detached"
    ip_address: Optional[str] = None
    rat: Optional[str] = None
    cell_id: Optional[str] = None
    operator: Optional[str] = None
    country: Optional[str] = None
    last_seen: Optional[str] = None
    provider_raw: Optional[Dict[str, Any]] = None


@dataclass
class UnifiedOperationResult:
    """Standardized result for SIM lifecycle mutations (suspend, reset, topup, sms)."""
    success: bool
    status: str
    action: str
    message: str
    details: Optional[Dict[str, Any]] = None


class BaseSimProviderClient(ABC):
    """
    Abstract Base Class for all Network SIM Provider Clients.
    Every provider (1NCE, Monogoto, EMnify, Twilio, Generic REST) conforms to this contract,
    ensuring the entire NibiaaNet platform operates identically regardless of carrier.
    """

    def __init__(
        self,
        provider_code: str,
        name: str,
        base_url: str,
        auth_type: str,
        api_user: Optional[str] = None,
        api_key: Optional[str] = None,
        is_sandbox: bool = True,
        extra_settings: Optional[Dict[str, Any]] = None,
        timeout: float = 15.0,
    ):
        self.provider_code = provider_code
        self.name = name
        self.base_url = (base_url or "").rstrip("/")
        self.auth_type = auth_type
        self.api_user = api_user or ""
        self.api_key = api_key or ""
        self.is_sandbox = is_sandbox
        self.extra_settings = extra_settings or {}
        self.timeout = timeout

    @abstractmethod
    async def test_connection(self) -> Dict[str, Any]:
        """
        Executes a diagnostic ping and authentication check against the provider's API.
        Returns dict with: success (bool), latency_ms (float), message (str), status_code (int).
        """
        pass

    @abstractmethod
    async def fetch_sims(self, limit: int = 250, offset: int = 0) -> List[UnifiedSimData]:
        """
        Fetches inventory of active SIM cards / Things from the provider API.
        """
        pass

    @abstractmethod
    async def get_sim_details(self, iccid: str) -> Optional[UnifiedSimData]:
        """
        Queries full details for a single SIM card by its ICCID.
        """
        pass

    @abstractmethod
    async def get_quota(self, iccid: str) -> UnifiedQuotaData:
        """
        Retrieves real-time data quota consumption and limits.
        """
        pass

    @abstractmethod
    async def get_connectivity(self, iccid: str) -> UnifiedConnectivityData:
        """
        Queries live network session diagnostics (Cell ID, RAT, IP address, status).
        """
        pass

    @abstractmethod
    async def set_status(self, iccid: str, status: str, reason: Optional[str] = None) -> UnifiedOperationResult:
        """
        Updates SIM state on network core: Active, Suspended, Blocked.
        """
        pass

    @abstractmethod
    async def reset_connection(self, iccid: str) -> UnifiedOperationResult:
        """
        Forces network soft reset / HLR detachment to force device re-registration.
        """
        pass

    @abstractmethod
    async def topup(self, iccid: str, volume_mb: float) -> UnifiedOperationResult:
        """
        Adds / recharges data quota on provider core.
        """
        pass

    @abstractmethod
    async def send_sms(self, iccid: str, payload: str, source: str = "NibiaaNet") -> UnifiedOperationResult:
        """
        Dispatches Mobile-Terminated SMS (MT-SMS) command to the device.
        """
        pass
