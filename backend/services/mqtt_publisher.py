"""
Publishes telemetry events to an MQTT broker, for dashboards such as
Nibiaaplax and other subscribers.

Topic: {MQTT_TOPIC_PREFIX}/{tenant_id}/devices/{device_id}/telemetry
Each tenant has its own topic tree; the broker's ACLs must allow a
tenant's credentials to subscribe to its own tree only.

Configured with environment variables. Without MQTT_BROKER_HOST
publishing is disabled and messages are marked DISABLED.
"""

import json
import logging
import os

import paho.mqtt.publish as mqtt_publish


logger = logging.getLogger(__name__)

PUBLISHED = "PUBLISHED"
FAILED = "FAILED"
DISABLED = "DISABLED"


def topic_for(tenant_id: int, device_id: str):
    prefix = os.environ.get("MQTT_TOPIC_PREFIX", "nibiaanet/tenants")
    return f"{prefix}/{tenant_id}/devices/{device_id}/telemetry"


def publish_event(event: dict):
    """
    Returns PUBLISHED, FAILED or DISABLED. Never raises: a broker
    outage must not lose the uplink, which is already stored.
    """

    host = os.environ.get("MQTT_BROKER_HOST")

    if not host:
        return DISABLED

    auth = None

    if os.environ.get("MQTT_USERNAME"):
        auth = {
            "username": os.environ["MQTT_USERNAME"],
            "password": os.environ.get("MQTT_PASSWORD"),
        }

    try:
        mqtt_publish.single(
            topic_for(event["tenant_id"], event["device_id"]),
            payload=json.dumps(event),
            qos=1,
            hostname=host,
            port=int(os.environ.get("MQTT_BROKER_PORT", "1883")),
            auth=auth,
        )
    except Exception:
        logger.exception("MQTT publish failed for telemetry %s", event.get("telemetry_id"))
        return FAILED

    return PUBLISHED
