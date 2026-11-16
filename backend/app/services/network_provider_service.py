import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.network_provider_config import NetworkProviderConfig
from app.models.network_sim_card import NetworkSimCard
from app.schemas.network_provider import (
    DriverCatalogItem,
    NetworkProviderCreate,
    NetworkProviderResponse,
    NetworkProviderUpdate,
    ProviderTestResult,
)
from app.services.sim_clients import (
    BaseSimProviderClient,
    DriverMetadata,
    sim_provider_registry,
)

logger = logging.getLogger("nibiaanet.network.service")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_PROVIDERS = [
    {
        "name": "1NCE Cellular IoT",
        "provider_code": "1nce",
        "provider_type": "1nce",
        "base_url": os.getenv("ONCE_API_BASE_URL", "https://api.1nce.com/management-api"),
        "auth_type": "oauth2",
        "api_user": os.getenv("ONCE_CLIENT_ID", ""),
        "api_key": os.getenv("ONCE_CLIENT_SECRET", ""),
        "is_enabled": True,
        "is_sandbox": os.getenv("ONCE_SANDBOX_MODE", "true").lower() in ("1", "true", "yes"),
        "extra_settings": {
            "technology": "NB-IoT / LTE-M",
            "coverage": "165+ Countries",
            "default_quota_mb": 500.0,
            "default_sms": 250,
        },
    },
    {
        "name": "Monogoto Global Cellular",
        "provider_code": "monogoto",
        "provider_type": "monogoto",
        "base_url": os.getenv("MONOGOTO_API_BASE_URL", "https://api.monogoto.io"),
        "auth_type": "bearer_token",
        "api_user": os.getenv("MONOGOTO_USERNAME", ""),
        "api_key": os.getenv("MONOGOTO_PASSWORD", ""),
        "is_enabled": True,
        "is_sandbox": os.getenv("MONOGOTO_SANDBOX_MODE", "true").lower() in ("1", "true", "yes"),
        "extra_settings": {
            "technology": "LTE-M / NB-IoT / 5G / Private Networks",
            "coverage": "180+ Countries",
            "default_quota_mb": 1000.0,
            "default_sms": 500,
            "developer_portal": "https://developer.monogoto.io/overview",
        },
    },
    {
        "name": "EMnify Global Cellular IoT",
        "provider_code": "emnify",
        "provider_type": "emnify",
        "base_url": "https://cdn.emnify.net/api/v1",
        "auth_type": "bearer_token",
        "api_user": os.getenv("EMNIFY_APPLICATION_TOKEN", ""),
        "api_key": "",
        "is_enabled": True,
        "is_sandbox": True,
        "extra_settings": {
            "technology": "LTE-M / NB-IoT / 2G / 3G / 4G",
            "coverage": "180+ Countries",
            "default_quota_mb": 1500.0,
            "default_sms": 300,
        },
    },
]


class NetworkProviderService:
    """
    Single Network SIM Provider Client Management System.
    Provides a completely decoupled, driver-based architecture where Admins can
    Add, Edit, Remove, Test, and Synchronize ANY SIM provider (1NCE, Monogoto, EMnify,
    Twilio, Generic REST, or custom carriers) through a uniform contract.
    """

    def __init__(self):
        self._client_cache: Dict[str, BaseSimProviderClient] = {}

    # -------------------------------------------------------------------------
    # Driver Catalog
    # -------------------------------------------------------------------------

    def get_driver_catalog(self) -> List[DriverCatalogItem]:
        """Returns metadata for all available SIM provider drivers."""
        metas = sim_provider_registry.list_drivers()
        return [
            DriverCatalogItem(
                driver_type=m.driver_type,
                display_name=m.display_name,
                vendor=m.vendor,
                description=m.description,
                default_base_url=m.default_base_url,
                auth_type=m.auth_type,
                user_label=m.user_label,
                secret_label=m.secret_label,
                documentation_url=m.documentation_url,
                capabilities=m.capabilities,
                supports_sandbox=m.supports_sandbox,
            )
            for m in metas
        ]

    # -------------------------------------------------------------------------
    # Seed & Configuration Management
    # -------------------------------------------------------------------------

    def seed_default_providers(self, db: Session) -> int:
        """Seeds initial default network providers (1NCE, Monogoto, EMnify) if not present."""
        count = 0
        for p_def in DEFAULT_PROVIDERS:
            existing = db.query(NetworkProviderConfig).filter(
                NetworkProviderConfig.provider_code == p_def["provider_code"]
            ).first()
            if not existing:
                cfg = NetworkProviderConfig(
                    name=p_def["name"],
                    provider_code=p_def["provider_code"],
                    provider_type=p_def["provider_type"],
                    base_url=p_def["base_url"],
                    auth_type=p_def["auth_type"],
                    api_user=p_def["api_user"],
                    api_key_encrypted=p_def["api_key"],
                    is_enabled=p_def["is_enabled"],
                    is_sandbox=p_def["is_sandbox"],
                    extra_settings=p_def["extra_settings"],
                )
                db.add(cfg)
                count += 1
        if count > 0:
            db.commit()
            logger.info(f"Seeded {count} default network providers.")
        return count

    def list_providers(self, db: Session) -> List[NetworkProviderResponse]:
        """Lists all network providers with live SIM counts, capabilities, and masked credentials."""
        configs = db.query(NetworkProviderConfig).all()
        if not configs:
            self.seed_default_providers(db)
            configs = db.query(NetworkProviderConfig).all()

        results = []
        for c in configs:
            sim_count = db.query(func.count(NetworkSimCard.id)).filter(
                NetworkSimCard.provider == c.provider_code
            ).scalar() or 0

            driver_meta = sim_provider_registry.get_driver_metadata(c.provider_type)
            capabilities = driver_meta.capabilities if driver_meta else []

            markup = getattr(c, "markup_percentage", 20.0) or 20.0
            mb_cost = getattr(c, "cost_per_mb", 0.03) or 0.03
            sim_cost = getattr(c, "cost_per_sim", 1.00) or 1.00
            sms_cost = getattr(c, "cost_per_sms", 0.01) or 0.01

            mult = 1.0 + (markup / 100.0)

            results.append(
                NetworkProviderResponse(
                    id=c.id,
                    name=c.name,
                    provider_code=c.provider_code,
                    provider_type=c.provider_type,
                    base_url=c.base_url,
                    auth_type=c.auth_type,
                    api_user=c.api_user,
                    has_api_key=bool(c.api_key_encrypted),
                    markup_percentage=markup,
                    cost_per_mb=mb_cost,
                    cost_per_sim=sim_cost,
                    cost_per_sms=sms_cost,
                    effective_customer_mb_rate=round(mb_cost * mult, 4),
                    effective_customer_sim_rate=round(sim_cost * mult, 2),
                    effective_customer_sms_rate=round(sms_cost * mult, 4),
                    is_enabled=c.is_enabled,
                    is_sandbox=c.is_sandbox,
                    extra_settings=c.extra_settings or {},
                    capabilities=capabilities,
                    sim_count=sim_count,
                    created_at=c.created_at,
                    updated_at=c.updated_at,
                )
            )
        return results

    def get_provider(self, db: Session, provider_code: str) -> Optional[NetworkProviderConfig]:
        return db.query(NetworkProviderConfig).filter(
            NetworkProviderConfig.provider_code == provider_code
        ).first()

    def create_provider(self, db: Session, data: NetworkProviderCreate) -> NetworkProviderResponse:
        """Admin: Registers a new Network Provider API configuration."""
        existing = self.get_provider(db, data.provider_code)
        if existing:
            raise ValueError(f"Network provider with code '{data.provider_code}' already exists.")

        cfg = NetworkProviderConfig(
            name=data.name,
            provider_code=data.provider_code.lower().strip(),
            provider_type=data.provider_type,
            base_url=data.base_url.rstrip("/"),
            auth_type=data.auth_type,
            api_user=data.api_user,
            api_key_encrypted=data.api_key,
            markup_percentage=data.markup_percentage,
            cost_per_mb=data.cost_per_mb,
            cost_per_sim=data.cost_per_sim,
            cost_per_sms=data.cost_per_sms,
            is_enabled=data.is_enabled,
            is_sandbox=data.is_sandbox,
            extra_settings=data.extra_settings or {},
        )
        db.add(cfg)
        db.commit()
        db.refresh(cfg)

        self._client_cache.pop(cfg.provider_code, None)

        driver_meta = sim_provider_registry.get_driver_metadata(cfg.provider_type)
        capabilities = driver_meta.capabilities if driver_meta else []

        markup = cfg.markup_percentage or 20.0
        mb_cost = cfg.cost_per_mb or 0.03
        sim_cost = cfg.cost_per_sim or 1.00
        sms_cost = cfg.cost_per_sms or 0.01
        mult = 1.0 + (markup / 100.0)

        return NetworkProviderResponse(
            id=cfg.id,
            name=cfg.name,
            provider_code=cfg.provider_code,
            provider_type=cfg.provider_type,
            base_url=cfg.base_url,
            auth_type=cfg.auth_type,
            api_user=cfg.api_user,
            has_api_key=bool(cfg.api_key_encrypted),
            markup_percentage=markup,
            cost_per_mb=mb_cost,
            cost_per_sim=sim_cost,
            cost_per_sms=sms_cost,
            effective_customer_mb_rate=round(mb_cost * mult, 4),
            effective_customer_sim_rate=round(sim_cost * mult, 2),
            effective_customer_sms_rate=round(sms_cost * mult, 4),
            is_enabled=cfg.is_enabled,
            is_sandbox=cfg.is_sandbox,
            extra_settings=cfg.extra_settings or {},
            capabilities=capabilities,
            sim_count=0,
            created_at=cfg.created_at,
            updated_at=cfg.updated_at,
        )

    def update_provider(
        self,
        db: Session,
        provider_code: str,
        data: NetworkProviderUpdate,
    ) -> NetworkProviderResponse:
        """Admin: Updates an existing Network Provider API configuration."""
        cfg = self.get_provider(db, provider_code)
        if not cfg:
            raise ValueError(f"Network provider '{provider_code}' not found.")

        if data.name is not None:
            cfg.name = data.name
        if data.base_url is not None:
            cfg.base_url = data.base_url.rstrip("/")
        if data.auth_type is not None:
            cfg.auth_type = data.auth_type
        if data.api_user is not None:
            cfg.api_user = data.api_user
        if data.api_key is not None and data.api_key.strip() != "":
            cfg.api_key_encrypted = data.api_key
        if data.markup_percentage is not None:
            cfg.markup_percentage = data.markup_percentage
        if data.cost_per_mb is not None:
            cfg.cost_per_mb = data.cost_per_mb
        if data.cost_per_sim is not None:
            cfg.cost_per_sim = data.cost_per_sim
        if data.cost_per_sms is not None:
            cfg.cost_per_sms = data.cost_per_sms
        if data.is_enabled is not None:
            cfg.is_enabled = data.is_enabled
        if data.is_sandbox is not None:
            cfg.is_sandbox = data.is_sandbox
        if data.extra_settings is not None:
            cfg.extra_settings = data.extra_settings

        db.commit()
        db.refresh(cfg)

        self._client_cache.pop(provider_code, None)

        sim_count = db.query(func.count(NetworkSimCard.id)).filter(
            NetworkSimCard.provider == provider_code
        ).scalar() or 0

        driver_meta = sim_provider_registry.get_driver_metadata(cfg.provider_type)
        capabilities = driver_meta.capabilities if driver_meta else []

        markup = cfg.markup_percentage or 20.0
        mb_cost = cfg.cost_per_mb or 0.03
        sim_cost = cfg.cost_per_sim or 1.00
        sms_cost = cfg.cost_per_sms or 0.01
        mult = 1.0 + (markup / 100.0)

        return NetworkProviderResponse(
            id=cfg.id,
            name=cfg.name,
            provider_code=cfg.provider_code,
            provider_type=cfg.provider_type,
            base_url=cfg.base_url,
            auth_type=cfg.auth_type,
            api_user=cfg.api_user,
            has_api_key=bool(cfg.api_key_encrypted),
            markup_percentage=markup,
            cost_per_mb=mb_cost,
            cost_per_sim=sim_cost,
            cost_per_sms=sms_cost,
            effective_customer_mb_rate=round(mb_cost * mult, 4),
            effective_customer_sim_rate=round(sim_cost * mult, 2),
            effective_customer_sms_rate=round(sms_cost * mult, 4),
            is_enabled=cfg.is_enabled,
            is_sandbox=cfg.is_sandbox,
            extra_settings=cfg.extra_settings or {},
            capabilities=capabilities,
            sim_count=sim_count,
            created_at=cfg.created_at,
            updated_at=cfg.updated_at,
        )

    def delete_provider(self, db: Session, provider_code: str, force: bool = False) -> Dict[str, Any]:
        """Admin: Removes a Network Provider API configuration."""
        cfg = self.get_provider(db, provider_code)
        if not cfg:
            raise ValueError(f"Network provider '{provider_code}' not found.")

        sim_count = db.query(func.count(NetworkSimCard.id)).filter(
            NetworkSimCard.provider == provider_code
        ).scalar() or 0

        if sim_count > 0 and not force:
            raise ValueError(
                f"Cannot delete provider '{provider_code}': {sim_count} SIM cards are currently associated with it. "
                "Pass force=true to delete provider and dissociate SIM cards."
            )

        if sim_count > 0 and force:
            db.query(NetworkSimCard).filter(
                NetworkSimCard.provider == provider_code
            ).update({"provider": "unassigned"})

        db.delete(cfg)
        db.commit()
        self._client_cache.pop(provider_code, None)

        return {
            "success": True,
            "provider_code": provider_code,
            "message": f"Network provider '{provider_code}' successfully removed.",
        }

    # -------------------------------------------------------------------------
    # Pluggable Provider Client Factory
    # -------------------------------------------------------------------------

    def get_provider_client(self, db: Session, provider_code: str) -> BaseSimProviderClient:
        """
        Instantiates or retrieves the unified SIM Provider Client from the Driver Registry.
        Works identically for 1NCE, Monogoto, EMnify, Twilio, Generic REST, or custom carriers.
        """
        provider_code = (provider_code or "1nce").lower().strip()
        if provider_code in self._client_cache:
            return self._client_cache[provider_code]

        cfg = self.get_provider(db, provider_code)
        if not cfg:
            # Fallback to in-memory transient configuration
            cfg = NetworkProviderConfig(
                name=provider_code.upper(),
                provider_code=provider_code,
                provider_type=provider_code,
                base_url="",
                auth_type="bearer_token",
                is_enabled=True,
                is_sandbox=True,
                extra_settings={},
            )

        client = sim_provider_registry.create_client(cfg)
        self._client_cache[provider_code] = client
        return client

    # -------------------------------------------------------------------------
    # Live Diagnostics & Testing
    # -------------------------------------------------------------------------

    async def test_provider_connection(self, db: Session, provider_code: str) -> ProviderTestResult:
        """Executes a live API connectivity and authentication check against any provider."""
        cfg = self.get_provider(db, provider_code)
        name = cfg.name if cfg else provider_code.upper()
        client = self.get_provider_client(db, provider_code)

        try:
            res = await client.test_connection()
            return ProviderTestResult(
                provider_code=provider_code,
                provider_name=name,
                success=res.get("success", False),
                status_code=res.get("status_code", 200),
                latency_ms=res.get("latency_ms"),
                message=res.get("message", "Connection test completed."),
                details=res,
            )
        except Exception as e:
            return ProviderTestResult(
                provider_code=provider_code,
                provider_name=name,
                success=False,
                status_code=500,
                latency_ms=0.0,
                message=f"Connection test failed: {e}",
            )

    # -------------------------------------------------------------------------
    # Provider-Agnostic SIM Fleet Synchronization & Operations
    # -------------------------------------------------------------------------

    async def sync_sims_from_provider(
        self,
        db: Session,
        provider_code: str,
        tenant_id: Optional[int] = None,
    ) -> List[NetworkSimCard]:
        """
        Synchronizes SIM cards from ANY provider (1NCE, Monogoto, EMnify, Twilio, Generic REST)
        into the platform's encrypted database.
        """
        provider_code = provider_code.lower().strip()
        client = self.get_provider_client(db, provider_code)
        sims = await client.fetch_sims()

        now = utc_now()
        persisted_cards = []

        for s in sims:
            iccid = s.iccid
            if not iccid:
                continue

            card = db.query(NetworkSimCard).filter(NetworkSimCard.iccid == iccid).first()
            if not card:
                card = NetworkSimCard(
                    iccid=iccid,
                    imei=s.imei if (getattr(s, "device_id", None) and s.device_id != "unassigned") else None,
                    imsi=s.imsi,
                    msisdn=s.msisdn,
                    ip_address=s.ip_address,
                    label=s.label,
                    provider=provider_code,
                    status=s.status,
                    tenant_id=tenant_id,
                    quota_total_mb=s.quota_total_mb,
                    quota_remaining_mb=s.quota_remaining_mb,
                    quota_used_mb=s.quota_used_mb,
                    sms_total=s.sms_total,
                    sms_remaining=s.sms_remaining,
                    last_sync_at=now,
                )
                db.add(card)
            else:
                card.imsi = s.imsi or card.imsi
                card.msisdn = s.msisdn or card.msisdn
                card.ip_address = s.ip_address or card.ip_address
                card.label = s.label or card.label
                card.provider = provider_code
                card.status = s.status or card.status
                card.quota_total_mb = s.quota_total_mb
                card.quota_remaining_mb = s.quota_remaining_mb
                card.quota_used_mb = s.quota_used_mb
                card.last_sync_at = now
                if tenant_id and not card.tenant_id:
                    card.tenant_id = tenant_id
                # Enforce: if Device is unassigned there will be no IMEI
                if not card.device_id or str(card.device_id).strip().lower() in ("unassigned", "none", "", "null"):
                    card.imei = None

            persisted_cards.append(card)

        db.commit()
        for c in persisted_cards:
            db.refresh(c)
        return persisted_cards

    async def get_sim_quota(self, db: Session, iccid: str) -> Dict[str, Any]:
        """Queries live data quota from the SIM card's assigned network provider."""
        card = db.query(NetworkSimCard).filter(NetworkSimCard.iccid == iccid).first()
        provider_code = card.provider if card and card.provider else "1nce"
        client = self.get_provider_client(db, provider_code)

        q = await client.get_quota(iccid)
        if card:
            card.quota_total_mb = q.volume_total_mb
            card.quota_remaining_mb = q.volume_remaining_mb
            card.quota_used_mb = q.volume_used_mb
            db.commit()

        return {
            "iccid": q.iccid,
            "volume_total_mb": q.volume_total_mb,
            "volume_used_mb": q.volume_used_mb,
            "volume_remaining_mb": q.volume_remaining_mb,
            "expiry_date": q.expiry_date,
            "peak_throughput": q.peak_throughput,
            "threshold_percentage": q.threshold_percentage,
            "provider_raw": q.provider_raw,
        }

    async def get_sim_connectivity(self, db: Session, iccid: str) -> Dict[str, Any]:
        """Queries network session diagnostics (cell ID, RAT, IP) from the SIM's provider."""
        card = db.query(NetworkSimCard).filter(NetworkSimCard.iccid == iccid).first()
        provider_code = card.provider if card and card.provider else "1nce"
        client = self.get_provider_client(db, provider_code)

        conn = await client.get_connectivity(iccid)
        res = {
            "iccid": iccid,
            "status": conn.status,
            "ip_address": conn.ip_address,
            "radio_access_technology": conn.rat,
            "cell_id": conn.cell_id,
            "operator": conn.operator,
            "country": conn.country,
            "last_connection_date": conn.last_seen,
            "roaming_network": f"{conn.operator} ({conn.country})" if conn.operator and conn.country else conn.operator,
            "provider_raw": conn.provider_raw,
        }

        if card:
            card.last_connectivity_check = res
            db.commit()
        return res

    async def update_sim_status(
        self,
        db: Session,
        iccid: str,
        status: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Updates SIM operational status (Active ↔ Suspended) on provider core."""
        card = db.query(NetworkSimCard).filter(NetworkSimCard.iccid == iccid).first()
        provider_code = card.provider if card and card.provider else "1nce"
        client = self.get_provider_client(db, provider_code)

        res = await client.set_status(iccid, status=status, reason=reason)
        if card:
            card.status = "Active" if status.lower() in ("active", "enabled") else "Suspended"
            db.commit()
            db.refresh(card)

        return {
            "iccid": iccid,
            "status": res.status,
            "message": res.message,
            "action": res.action,
            "details": res.details,
        }

    async def reset_sim(self, db: Session, iccid: str) -> Dict[str, Any]:
        """Forces network session teardown and reconnection (HLR/core soft reset)."""
        card = db.query(NetworkSimCard).filter(NetworkSimCard.iccid == iccid).first()
        provider_code = card.provider if card and card.provider else "1nce"
        client = self.get_provider_client(db, provider_code)

        res = await client.reset_connection(iccid)
        return {
            "iccid": iccid,
            "status": res.status,
            "action": res.action,
            "message": res.message,
            "details": res.details,
        }

    async def topup_sim(
        self,
        db: Session,
        iccid: str,
        volume_mb: float = 500.0,
    ) -> Dict[str, Any]:
        """Recharges or adds quota to a SIM card on its provider core."""
        card = db.query(NetworkSimCard).filter(NetworkSimCard.iccid == iccid).first()
        provider_code = card.provider if card and card.provider else "1nce"
        client = self.get_provider_client(db, provider_code)

        res = await client.topup(iccid, volume_mb=volume_mb)
        if card:
            card.quota_total_mb = (card.quota_total_mb or 0.0) + volume_mb
            card.quota_remaining_mb = (card.quota_remaining_mb or 0.0) + volume_mb
            db.commit()
            db.refresh(card)

        return {
            "iccid": iccid,
            "volume_added_mb": volume_mb,
            "status": res.status,
            "message": res.message,
            "details": res.details,
        }

    async def send_sim_sms(
        self,
        db: Session,
        iccid: str,
        payload: str,
        source_address: str = "NibiaaNet",
    ) -> Dict[str, Any]:
        """Dispatches Mobile-Terminated SMS to the SIM card."""
        card = db.query(NetworkSimCard).filter(NetworkSimCard.iccid == iccid).first()
        provider_code = card.provider if card and card.provider else "1nce"
        client = self.get_provider_client(db, provider_code)

        res = await client.send_sms(iccid, payload=payload, source=source_address)
        return {
            "iccid": iccid,
            "status": res.status,
            "message": res.message,
            "action": res.action,
            "details": res.details,
        }


# Global singleton service
network_provider_service = NetworkProviderService()
