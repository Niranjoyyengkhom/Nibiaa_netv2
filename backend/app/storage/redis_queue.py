import os
import json
import logging
import asyncio
from typing import Optional, Dict, Any

logger = logging.getLogger("nibiaanet.storage.redis_queue")

REDIS_ENABLED = os.getenv("REDIS_ENABLED", "true").lower() in ("true", "1", "yes")
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
QUEUE_KEY = "nibiaanet:telemetry:unprocessed"
DEAD_LETTER_KEY = "nibiaanet:telemetry:deadletter"


class RedisUnprocessedQueue:
    """
    High-throughput Redis queue for buffering and handling unprocessed telemetry data.
    Decouples raw uplink ingestion (UDP/HTTP/MQTT) from payload decoding and database writes.
    """

    def __init__(self):
        self.client = None
        self.is_connected = False
        self.is_fake = False
        self.processed_counter = 0
        self.error_detail = "Initializing"

    def connect(self) -> bool:
        """Connect to real Redis server, or fallback to fakeredis emulator."""
        if not REDIS_ENABLED:
            self.error_detail = "Disabled by REDIS_ENABLED=false"
            return False

        # 1. Try real Redis server
        try:
            import redis
            real_client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
            real_client.ping()
            self.client = real_client
            self.is_connected = True
            self.is_fake = False
            self.error_detail = None
            logger.info(f"Connected to real Redis at {REDIS_URL} for unprocessed telemetry.")
            return True
        except Exception as e:
            logger.info(f"Real Redis offline ({e}). Activating embedded Redis memory queue...")

        # 2. Fallback to fakeredis memory server
        try:
            import fakeredis
            self.client = fakeredis.FakeRedis(decode_responses=True)
            self.is_connected = True
            self.is_fake = True
            self.error_detail = "Using embedded Redis engine (Real Redis at 127.0.0.1:6379 is offline)"
            logger.info("Embedded Redis Queue initialized successfully.")
            return True
        except Exception as e:
            self.is_connected = False
            self.error_detail = f"Failed to initialize Redis client: {e}"
            logger.error(self.error_detail)
            return False

    def enqueue_unprocessed(self, uplink_dict: Dict[str, Any]) -> str:
        """
        Push raw unprocessed telemetry message onto Redis queue.
        Returns the queued message ID.
        """
        if not self.client:
            self.connect()

        message_id = uplink_dict.get("id") or f"redis-{os.urandom(6).hex()}"
        uplink_dict["_queued_at"] = uplink_dict.get("_queued_at") or uplink_dict.get("received_at")

        serialized = json.dumps(uplink_dict)
        try:
            self.client.lpush(QUEUE_KEY, serialized)
            return message_id
        except Exception as e:
            logger.error(f"Failed to enqueue to Redis: {e}")
            raise

    def dequeue_unprocessed(self, timeout: int = 1) -> Optional[Dict[str, Any]]:
        """Pop an unprocessed telemetry item from the Redis queue."""
        if not self.client:
            return None

        try:
            # BRPOP returns (key, value) or None
            res = self.client.brpop(QUEUE_KEY, timeout=timeout)
            if res:
                _, raw_item = res
                self.processed_counter += 1
                return json.loads(raw_item)
            return None
        except Exception as e:
            logger.warning(f"Error dequeueing from Redis: {e}")
            return None

    def get_queue_length(self) -> int:
        """Count unprocessed telemetry items in Redis queue."""
        if not self.client:
            return 0
        try:
            return self.client.llen(QUEUE_KEY)
        except Exception:
            return 0

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic metrics for Redis unprocessed queue."""
        unprocessed_count = self.get_queue_length()
        mode = "real_redis" if not self.is_fake else "embedded_redis"
        return {
            "enabled": REDIS_ENABLED,
            "connected": self.is_connected,
            "mode": mode,
            "unprocessed_count": unprocessed_count,
            "processed_total": self.processed_counter,
            "queue_key": QUEUE_KEY,
            "status": "connected" if self.is_connected else "disconnected",
            "detail": self.error_detail or "Redis queue active and ready",
        }

    async def auto_reconnect_loop(self):
        """Background loop to check if real Redis comes online and upgrade from emulator."""
        while True:
            await asyncio.sleep(15)
            if self.is_fake:
                try:
                    import redis
                    test_client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1)
                    test_client.ping()
                    # Migrate any pending items from fake to real Redis
                    old_items = []
                    while self.client.llen(QUEUE_KEY) > 0:
                        it = self.client.rpop(QUEUE_KEY)
                        if it:
                            old_items.append(it)

                    self.client = test_client
                    self.is_fake = False
                    self.is_connected = True
                    self.error_detail = None
                    for it in old_items:
                        self.client.lpush(QUEUE_KEY, it)
                    logger.info("Successfully connected to real Redis server and migrated in-flight queue!")
                except Exception:
                    pass


redis_queue = RedisUnprocessedQueue()
