"""
Publishes telemetry events to an MQTT broker, for dashboards such as
Nibiaaplax, custom IoT platforms, and other subscribers.

Configured via User/Tenant-supplied credentials in the database (MqttBrokerConfig),
with fallback to platform environment variables (MQTT_BROKER_HOST).
"""

import json
import logging
import os
import ssl
from datetime import datetime
from typing import Optional, Tuple

import paho.mqtt.publish as mqtt_publish

logger = logging.getLogger(__name__)

PUBLISHED = "PUBLISHED"
FAILED = "FAILED"
DISABLED = "DISABLED"


def get_tenant_mqtt_config(tenant_id: Optional[int], db=None):
    """
    Retrieves the tenant's active MQTT broker configuration from PostgreSQL.
    """
    if not tenant_id:
        return None

    try:
        from app.models.mqtt_broker_config import MqttBrokerConfig

        if db is not None:
            return (
                db.query(MqttBrokerConfig)
                .filter(MqttBrokerConfig.tenant_id == tenant_id)
                .first()
            )

        from app.database import SessionLocal
        with SessionLocal() as session:
            return (
                session.query(MqttBrokerConfig)
                .filter(MqttBrokerConfig.tenant_id == tenant_id)
                .first()
            )
    except Exception as e:
        logger.warning(f"Could not load MQTT broker config for tenant {tenant_id}: {e}")
        return None


def format_topic(template: str, tenant_id: int, device_id: str) -> str:
    topic = template or "nibiaanet/tenants/{tenant_id}/devices/{device_id}/telemetry"
    topic = topic.replace("{tenant_id}", str(tenant_id))
    topic = topic.replace("{device_id}", str(device_id))
    return topic


def publish_event(event: dict, db=None) -> str:
    """
    Publishes telemetry event to the user/tenant-configured MQTT broker.
    Returns PUBLISHED, FAILED, or DISABLED.
    Never raises exceptions: a broker error must not fail uplink staging/storage.
    """
    tenant_id = event.get("tenant_id")
    device_id = event.get("device_id", "unknown")

    # 1. Check if user/tenant has configured an MQTT broker
    config = get_tenant_mqtt_config(tenant_id, db=db)

    if config is not None:
        if not config.enabled:
            return DISABLED

        host = config.host
        port = config.port
        qos = config.qos if config.qos is not None else 1
        client_id = config.client_id or f"nibiaanet-pub-{tenant_id}"
        topic = format_topic(config.topic_prefix, tenant_id, device_id)

        auth = None
        if config.username or config.password:
            auth = {
                "username": config.username or "",
                "password": config.password or "",
            }

        tls = None
        if config.use_tls:
            tls = {"tls_version": ssl.PROTOCOL_TLS_CLIENT}

        try:
            mqtt_publish.single(
                topic=topic,
                payload=json.dumps(event),
                qos=qos,
                hostname=host,
                port=port,
                client_id=client_id,
                auth=auth,
                tls=tls,
            )
            logger.info("Published telemetry to tenant %s MQTT broker (%s:%s topic %s)", tenant_id, host, port, topic)
            return PUBLISHED
        except Exception:
            logger.exception("MQTT publish to tenant %s broker (%s:%s) failed for telemetry %s", tenant_id, host, port, event.get("telemetry_id"))
            return FAILED

    # 2. Fallback to platform-wide environment variables
    host = os.environ.get("MQTT_BROKER_HOST")
    if not host:
        return DISABLED

    auth = None
    if os.environ.get("MQTT_USERNAME"):
        auth = {
            "username": os.environ["MQTT_USERNAME"],
            "password": os.environ.get("MQTT_PASSWORD"),
        }

    prefix = os.environ.get("MQTT_TOPIC_PREFIX", "nibiaanet/tenants")
    topic = f"{prefix}/{tenant_id}/devices/{device_id}/telemetry"

    try:
        mqtt_publish.single(
            topic=topic,
            payload=json.dumps(event),
            qos=1,
            hostname=host,
            port=int(os.environ.get("MQTT_BROKER_PORT", "1883")),
            auth=auth,
        )
        return PUBLISHED
    except Exception:
        logger.exception("Platform MQTT fallback publish failed for telemetry %s", event.get("telemetry_id"))
        return FAILED


def test_connection(
    host: str,
    port: int = 1883,
    username: Optional[str] = None,
    password: Optional[str] = None,
    client_id: Optional[str] = None,
    use_tls: bool = False,
    topic: str = "nibiaanet/test/ping",
    timeout: int = 4
) -> Tuple[bool, str]:
    """
    Tests connectivity to the specified MQTT broker by publishing a ping message.
    """
    if not host or not host.strip():
        return False, "Broker host cannot be empty"

    auth = None
    if username or password:
        auth = {"username": username or "", "password": password or ""}

    tls = None
    if use_tls:
        tls = {"tls_version": ssl.PROTOCOL_TLS_CLIENT}

    test_payload = json.dumps({
        "test": "nibiaanet_ping",
        "timestamp": datetime.utcnow().isoformat(),
        "client": "NibiaaNet MQTT Verifier"
    })

    try:
        mqtt_publish.single(
            topic=topic,
            payload=test_payload,
            qos=1,
            hostname=host.strip(),
            port=port,
            client_id=client_id or "nibiaanet-tester",
            auth=auth,
            tls=tls,
            keepalive=timeout,
        )
        return True, f"Successfully connected to MQTT broker '{host}:{port}' and published test message to '{topic}'."
    except Exception as e:
        return False, f"MQTT connection failed ({type(e).__name__}): {str(e)}"
