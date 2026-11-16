import os
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

logger = logging.getLogger("nibiaanet.storage.cassandra")

# Environment configurations
CASSANDRA_ENABLED = os.getenv("CASSANDRA_ENABLED", "true").lower() in ("true", "1", "yes")
CASSANDRA_HOSTS = [h.strip() for h in os.getenv("CASSANDRA_HOSTS", "127.0.0.1").split(",") if h.strip()]
CASSANDRA_PORT = int(os.getenv("CASSANDRA_PORT", "9042"))
CASSANDRA_KEYSPACE = os.getenv("CASSANDRA_KEYSPACE", "nibiaanet")

from app.security.crypto import encrypt_json, decrypt_json, encrypt_string, decrypt_string


class CassandraTelemetryStorage:
    """
    Dedicated Apache Cassandra storage engine for high-throughput IoT time-series telemetry.
    Stores all telemetry in Cassandra with application-level encryption.
    Gracefully falls back to local encrypted store when Cassandra cluster is offline.
    """

    def __init__(self):
        self.cluster = None
        self.session = None
        self.is_connected = False
        self.error_detail = "Initializing"
        self._reconnect_task = None

    def connect(self) -> bool:
        """Attempt to connect to Cassandra cluster and provision keyspace & tables."""
        if not CASSANDRA_ENABLED:
            self.error_detail = "Disabled by CASSANDRA_ENABLED=false"
            return False

        try:
            from cassandra.cluster import Cluster
            from cassandra.policies import DCAwareRoundRobinPolicy

            logger.info(f"Connecting to Apache Cassandra cluster at {CASSANDRA_HOSTS}:{CASSANDRA_PORT}...")
            self.cluster = Cluster(
                contact_points=CASSANDRA_HOSTS,
                port=CASSANDRA_PORT,
                connect_timeout=3.0,
            )
            # Connect without keyspace first to ensure keyspace exists
            temp_session = self.cluster.connect()
            temp_session.execute(f"""
                CREATE KEYSPACE IF NOT EXISTS {CASSANDRA_KEYSPACE}
                WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 1}};
            """)
            temp_session.shutdown()

            # Connect to the target keyspace
            self.session = self.cluster.connect(CASSANDRA_KEYSPACE)
            self._ensure_tables()
            self.is_connected = True
            self.error_detail = None
            logger.info(f"Connected to Apache Cassandra keyspace '{CASSANDRA_KEYSPACE}' successfully.")
            return True

        except Exception as e:
            self.is_connected = False
            self.error_detail = f"Cassandra unreachable at {CASSANDRA_HOSTS}:{CASSANDRA_PORT}: {e}"
            logger.warning(f"Cassandra cluster offline: {e}. Telemetry dual-writing active with encrypted fallback.")
            return False

    def _ensure_tables(self):
        """Create time-series telemetry tables with clustering order."""
        # 1. Device time-series table
        self.session.execute(f"""
            CREATE TABLE IF NOT EXISTS {CASSANDRA_KEYSPACE}.device_telemetry (
                tenant_id int,
                device_id text,
                day text,
                timestamp timestamp,
                telemetry_id bigint,
                received_at timestamp,
                provider text,
                connection_type text,
                data text,
                raw_payload text,
                data_originator text,
                PRIMARY KEY ((tenant_id, device_id, day), timestamp, telemetry_id)
            ) WITH CLUSTERING ORDER BY (timestamp DESC, telemetry_id DESC);
        """)

        # 2. Fleet time-series table for organization-wide lookups
        self.session.execute(f"""
            CREATE TABLE IF NOT EXISTS {CASSANDRA_KEYSPACE}.fleet_telemetry (
                tenant_id int,
                day text,
                timestamp timestamp,
                telemetry_id bigint,
                device_id text,
                received_at timestamp,
                provider text,
                connection_type text,
                data text,
                raw_payload text,
                data_originator text,
                PRIMARY KEY ((tenant_id, day), timestamp, telemetry_id)
            ) WITH CLUSTERING ORDER BY (timestamp DESC, telemetry_id DESC);
        """)

    def store_telemetry(
        self,
        tenant_id: int,
        device_id: str,
        timestamp: datetime,
        telemetry_id: int,
        received_at: datetime,
        provider: Optional[str],
        connection_type: Optional[str],
        data: Dict[str, Any],
        raw_payload: Optional[bytes],
        data_originator: Optional[str] = None
    ) -> bool:
        """
        Store encrypted telemetry into Cassandra device and fleet tables.
        Returns True if persisted to Cassandra, False if buffered/fallback.
        """
        if not self.is_connected or not self.session:
            self.connect()
        if not self.is_connected or not self.session:
            return False

        try:
            day_bucket = timestamp.strftime("%Y-%m-%d")
            # Encrypt data using application master key before storing into Cassandra
            encrypted_data = encrypt_json(data)
            raw_hex_str = raw_payload.hex() if isinstance(raw_payload, (bytes, bytearray)) else (str(raw_payload) if raw_payload else None)
            encrypted_raw_hex = encrypt_string(raw_hex_str) if raw_hex_str else None

            # Prepare statement for device_telemetry
            cql_device = f"""
                INSERT INTO {CASSANDRA_KEYSPACE}.device_telemetry (
                    tenant_id, device_id, day, timestamp, telemetry_id,
                    received_at, provider, connection_type, data, raw_payload, data_originator
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            self.session.execute(
                cql_device,
                (
                    tenant_id, device_id, day_bucket, timestamp, telemetry_id,
                    received_at, provider, connection_type, encrypted_data, encrypted_raw_hex, data_originator
                )
            )

            # Insert into fleet_telemetry
            cql_fleet = f"""
                INSERT INTO {CASSANDRA_KEYSPACE}.fleet_telemetry (
                    tenant_id, day, timestamp, telemetry_id, device_id,
                    received_at, provider, connection_type, data, raw_payload, data_originator
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            self.session.execute(
                cql_fleet,
                (
                    tenant_id, day_bucket, timestamp, telemetry_id, device_id,
                    received_at, provider, connection_type, encrypted_data, encrypted_raw_hex, data_originator
                )
            )
            return True

        except Exception as e:
            logger.warning(f"Error writing to Cassandra: {e}. Will rely on primary store.")
            return False

    def query_device_telemetry(
        self,
        tenant_id: int,
        device_id: str,
        limit: int = 100,
        days: int = 1
    ) -> Optional[List[Dict[str, Any]]]:
        """Query Cassandra for device telemetry records."""
        if not self.is_connected or not self.session:
            return None

        try:
            # Query the current day bucket
            now = datetime.now(timezone.utc)
            day_bucket = now.strftime("%Y-%m-%d")
            cql = f"""
                SELECT timestamp, telemetry_id, received_at, provider, connection_type, data, raw_payload, data_originator
                FROM {CASSANDRA_KEYSPACE}.device_telemetry
                WHERE tenant_id = %s AND device_id = %s AND day = %s
                LIMIT %s
            """
            rows = self.session.execute(cql, (tenant_id, device_id, day_bucket, limit))
            results = []
            for r in rows:
                results.append({
                    "id": r.telemetry_id,
                    "device_id": device_id,
                    "timestamp": r.timestamp,
                    "received_at": r.received_at,
                    "provider": r.provider,
                    "connection_type": r.connection_type,
                    "telemetry": decrypt_json(r.data),
                    "raw_payload_hex": decrypt_string(r.raw_payload),
                    "data_originator": r.data_originator,
                    "storage_backend": "cassandra",
                })
            return results
        except Exception as e:
            logger.warning(f"Cassandra query error: {e}")
            return None

    get_device_telemetry = query_device_telemetry

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic status of Cassandra storage."""
        return {
            "enabled": CASSANDRA_ENABLED,
            "connected": self.is_connected,
            "hosts": CASSANDRA_HOSTS,
            "port": CASSANDRA_PORT,
            "keyspace": CASSANDRA_KEYSPACE,
            "status": "connected" if self.is_connected else "offline_fallback",
            "detail": self.error_detail or "Cluster operational",
        }

    async def auto_reconnect_loop(self):
        """Background coroutine to re-establish connection when Cassandra comes online."""
        while True:
            await asyncio.sleep(20)
            if not self.is_connected and CASSANDRA_ENABLED:
                try:
                    connected = self.connect()
                    if connected:
                        logger.info("Cassandra background reconnect succeeded!")
                except Exception:
                    pass


cassandra_storage = CassandraTelemetryStorage()
