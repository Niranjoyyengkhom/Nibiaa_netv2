import asyncio
import json
import logging
import uuid
from typing import Optional
from app.forwarder import forward_to_backend
from app.metrics import LISTENER_STATUS

logger = logging.getLogger("nibiaanet.protocol_ingestion.udp")
UDP_PORT = 5001


class UdpProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
        LISTENER_STATUS["udp"]["status"] = "online"
        logger.info(f"UDP Ingestion Listener online on 0.0.0.0:{UDP_PORT}")

    def datagram_received(self, data: bytes, addr):
        remote_ip, remote_port = addr
        logger.info(f"Received UDP datagram from {remote_ip}:{remote_port} ({len(data)} bytes)")

        device_id = None
        raw_payload = data

        # Check if incoming datagram is JSON
        try:
            text = data.decode("utf-8").strip()
            if text.startswith("{") and text.endswith("}"):
                parsed = json.loads(text)
                device_id = parsed.get("deviceId") or parsed.get("device_id") or parsed.get("id")
                payload_val = parsed.get("payload") or parsed.get("data")
                if payload_val:
                    if isinstance(payload_val, str):
                        try:
                            raw_payload = bytes.fromhex(payload_val.replace("0x", ""))
                        except ValueError:
                            raw_payload = payload_val.encode("utf-8")
                    elif isinstance(payload_val, dict):
                        raw_payload = json.dumps(payload_val).encode("utf-8")
            elif ":" in text and not text.startswith("0x"):
                parts = text.split(":", 1)
                device_id = parts[0].strip()
                try:
                    raw_payload = bytes.fromhex(parts[1].strip())
                except ValueError:
                    raw_payload = parts[1].strip().encode("utf-8")
        except Exception:
            raw_payload = data

        # Forward asynchronously to backend
        asyncio.get_event_loop().run_in_executor(
            None,
            forward_to_backend,
            "udp",
            raw_payload,
            device_id,
            remote_ip,
            remote_port,
            f"udp-{remote_ip}:{remote_port}",
            "udp",
            "udp-raw",
            f"udp-{uuid.uuid4().hex[:8]}",
        )

    def error_received(self, exc):
        logger.warning(f"UDP socket error: {exc}")


async def start_udp_listener(port: int = UDP_PORT):
    loop = asyncio.get_running_loop()
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: UdpProtocol(),
            local_addr=("0.0.0.0", port),
        )
        LISTENER_STATUS["udp"]["status"] = "online"
        return transport
    except Exception as e:
        logger.error(f"Failed to bind UDP port {port}: {e}")
        LISTENER_STATUS["udp"]["status"] = f"error: {e}"
        return None
