import asyncio
import logging
import os
from typing import Optional
from app.services.queue import queue_worker

logger = logging.getLogger("nibiaanet.decoder.udp")


class UdpIngestionProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
        logger.info("UDP ingestion socket ready.")

    def datagram_received(self, data: bytes, addr):
        remote_ip, remote_port = addr
        logger.debug(f"Received UDP datagram from {remote_ip}:{remote_port} ({len(data)} bytes)")

        # Create incoming message dictionary
        msg = {
            "payload": data.hex(),
            "format": "hex",
            "transport": "udp",
            "context": {
                "remoteAddress": remote_ip,
                "remotePort": remote_port,
                "protocolId": os.getenv("UDP_DEFAULT_PROTOCOL", "udp"),
            },
        }
        asyncio.create_task(queue_worker.enqueue(msg))


async def start_udp_listener(port: int = 5005) -> Optional[asyncio.DatagramTransport]:
    udp_enabled = os.getenv("UDP_INGEST_ENABLED", "true").lower() == "true"
    if not udp_enabled:
        logger.info("UDP ingestion disabled by configuration.")
        return None

    loop = asyncio.get_running_loop()
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: UdpIngestionProtocol(),
            local_addr=("0.0.0.0", port),
        )
        logger.info(f"UDP Ingestion listening on 0.0.0.0:{port}")
        return transport
    except Exception as e:
        logger.warning(f"Failed to start UDP ingestion listener on port {port}: {e}")
        return None
