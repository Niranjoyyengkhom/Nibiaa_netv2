import asyncio
import logging
import os
import sys

# Ensure current directory is in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import uvicorn
from app.udp_listener import start_udp_listener
from app.mqtt_broker import start_mqtt_broker
from app.tcp_listener import start_tcp_listener
from app.webhook_server import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("nibiaanet.protocol_ingestion")


async def main():
    logger.info("====================================================================")
    logger.info("       NIBIAANET PROTOCOL INGESTION MICROSERVICE                    ")
    logger.info("====================================================================")
    logger.info("Starting multi-protocol listeners for 3rd-party integration:")
    logger.info(" [1] UDP Ingestion Listener:    0.0.0.0:5001")
    logger.info(" [2] MQTT Ingestion Broker:     0.0.0.0:1883")
    logger.info(" [3] TCP/IP Ingestion Listener: 0.0.0.0:1001")
    logger.info(" [4] Webhook Ingestion API:     0.0.0.0:1002")
    logger.info("====================================================================")

    # Start UDP listener on port 5001
    await start_udp_listener(5001)

    # Start MQTT broker on port 1883
    await start_mqtt_broker(1883)

    # Start TCP listener on port 1001
    await start_tcp_listener(1001)

    # Start Webhook HTTP server on port 1002
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=1002,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Protocol Ingestion Microservice stopped.")
