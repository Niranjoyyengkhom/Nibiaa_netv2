import asyncio
import json
import logging
import os
from typing import Optional
from app.services.queue import queue_worker

logger = logging.getLogger("nibiaanet.decoder.mqtt")


async def start_mqtt_listener():
    mqtt_url = os.getenv("MQTT_URL")
    if not mqtt_url:
        logger.info("MQTT listener not started (MQTT_URL not configured).")
        return None

    try:
        import paho.mqtt.client as mqtt

        client = mqtt.Client()
        topic = os.getenv("MQTT_TOPIC", "uplink/#")

        def on_connect(c, userdata, flags, rc):
            if rc == 0:
                logger.info(f"Connected to MQTT broker, subscribing to {topic}")
                c.subscribe(topic)
            else:
                logger.warning(f"MQTT connection failed with code {rc}")

        def on_message(c, userdata, msg):
            try:
                payload_str = msg.payload.decode("utf-8", errors="ignore")
                device_id = None
                # Check topic parts for device ID
                parts = msg.topic.split("/")
                if len(parts) >= 2 and parts[0] in ("devices", "uplink"):
                    device_id = parts[1]

                item = {
                    "payload": payload_str,
                    "format": "auto",
                    "transport": "mqtt",
                    "deviceId": device_id,
                    "context": {"mqttTopic": msg.topic},
                }
                asyncio.create_task(queue_worker.enqueue(item))
            except Exception as e:
                logger.error(f"Error handling MQTT message: {e}")

        client.on_connect = on_connect
        client.on_message = on_message

        # parse host/port from mqtt_url e.g. mqtt://localhost:1883
        clean_url = mqtt_url.replace("mqtt://", "").replace("tcp://", "")
        host = clean_url.split(":")[0]
        port = int(clean_url.split(":")[1]) if ":" in clean_url else 1883

        client.connect_async(host, port, 60)
        client.loop_start()
        logger.info(f"MQTT client initialized for {host}:{port}")
        return client
    except Exception as e:
        logger.warning(f"Failed to start MQTT listener: {e}")
        return None
