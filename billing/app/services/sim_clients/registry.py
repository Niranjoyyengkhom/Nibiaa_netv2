import logging
from typing import Any, Dict, List, Optional, Type

from app.models.network_provider_config import NetworkProviderConfig
from app.services.sim_clients.adapters.emnify_adapter import EMnifyProviderAdapter
from app.services.sim_clients.adapters.generic_rest_adapter import GenericRestProviderAdapter
from app.services.sim_clients.adapters.monogoto_adapter import MonogotoProviderAdapter
from app.services.sim_clients.adapters.once_adapter import OnceProviderAdapter
from app.services.sim_clients.adapters.twilio_adapter import TwilioSuperSimAdapter
from app.services.sim_clients.base import BaseSimProviderClient, DriverMetadata

logger = logging.getLogger("nibiaanet.sim_clients.registry")


class SimProviderRegistry:
    """
    Central Driver Registry & Factory for the Single Network SIM Provider Management System.
    Manages all pluggable SIM drivers (1NCE, Monogoto, EMnify, Twilio, Generic REST)
    and allows runtime expansion as network providers grow.
    """

    def __init__(self):
        self._drivers: Dict[str, Type[BaseSimProviderClient]] = {}
        self._metadata: Dict[str, DriverMetadata] = {}

        # Register default built-in drivers
        self.register_driver("1nce", OnceProviderAdapter, OnceProviderAdapter.METADATA)
        self.register_driver("monogoto", MonogotoProviderAdapter, MonogotoProviderAdapter.METADATA)
        self.register_driver("emnify", EMnifyProviderAdapter, EMnifyProviderAdapter.METADATA)
        self.register_driver("twilio", TwilioSuperSimAdapter, TwilioSuperSimAdapter.METADATA)
        self.register_driver("generic_rest", GenericRestProviderAdapter, GenericRestProviderAdapter.METADATA)
        self.register_driver("generic", GenericRestProviderAdapter, GenericRestProviderAdapter.METADATA)
        self.register_driver("custom", GenericRestProviderAdapter, GenericRestProviderAdapter.METADATA)

    def register_driver(
        self,
        driver_type: str,
        driver_class: Type[BaseSimProviderClient],
        metadata: Optional[DriverMetadata] = None,
    ):
        """Registers a new or custom SIM provider driver at runtime."""
        key = driver_type.lower().strip()
        self._drivers[key] = driver_class
        if metadata:
            self._metadata[key] = metadata
        logger.info(f"Registered SIM Provider Driver: '{key}' ({driver_class.__name__})")

    def get_driver_metadata(self, driver_type: str) -> Optional[DriverMetadata]:
        return self._metadata.get(driver_type.lower().strip())

    def list_drivers(self) -> List[DriverMetadata]:
        """Returns catalog of all registered SIM provider drivers with capabilities."""
        # Deduplicate aliases like 'generic'/'custom'
        seen = set()
        catalog = []
        for key in ("1nce", "monogoto", "emnify", "twilio", "generic_rest"):
            meta = self._metadata.get(key)
            if meta and meta.driver_type not in seen:
                seen.add(meta.driver_type)
                catalog.append(meta)
        return catalog

    def create_client(self, config: NetworkProviderConfig) -> BaseSimProviderClient:
        """
        Instantiates a unified SIM provider client from database configuration.
        """
        driver_key = (config.provider_type or config.provider_code or "generic_rest").lower().strip()
        driver_class = self._drivers.get(driver_key)

        if not driver_class:
            logger.warning(
                f"Driver type '{driver_key}' not found in registry. Falling back to Generic REST Adapter."
            )
            driver_class = GenericRestProviderAdapter

        return driver_class(
            provider_code=config.provider_code,
            name=config.name,
            base_url=config.base_url,
            auth_type=config.auth_type,
            api_user=config.api_user,
            api_key=config.api_key_encrypted,
            is_sandbox=config.is_sandbox,
            extra_settings=config.extra_settings or {},
        )


# Global singleton driver registry
sim_provider_registry = SimProviderRegistry()
