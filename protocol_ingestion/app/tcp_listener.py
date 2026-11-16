import asyncio
import json
import logging
import uuid
from app.forwarder import forward_to_backend
from app.metrics import LISTENER_STATUS

logger = logging.getLogger("nibiaanet.protocol_ingestion.tcp")
TCP_PORT = 1001


async def handle_tcp_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    remote_ip, remote_port = peer[0], peer[1] if peer else ("unknown", 0)
    logger.info(f"TCP client connected from {remote_ip}:{remote_port}")

    try:
        while True:
            line = await reader.readline()
            if not line:
                break

            data = line.strip()
            if not data:
                continue

            device_id = None
            raw_payload = data

            try:
                text = data.decode("utf-8")
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

            # Forward to backend
            asyncio.get_event_loop().run_in_executor(
                None,
                forward_to_backend,
                "tcp",
                raw_payload,
                device_id,
                remote_ip,
                remote_port,
                f"tcp-{remote_ip}:{remote_port}",
                "tcp",
                "tcp-stream",
                f"tcp-{uuid.uuid4().hex[:8]}",
            )

            # Acknowledge to TCP client
            writer.write(b"OK\n")
            await writer.drain()

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning(f"TCP client {remote_ip}:{remote_port} error: {e}")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logger.debug(f"TCP client {remote_ip}:{remote_port} disconnected.")


async def start_tcp_listener(port: int = TCP_PORT):
    try:
        server = await asyncio.start_server(handle_tcp_client, "0.0.0.0", port)
        LISTENER_STATUS["tcp"]["status"] = "online"
        logger.info(f"TCP Ingestion Listener online on 0.0.0.0:{port}")
        return server
    except Exception as e:
        logger.error(f"Failed to bind TCP port {port}: {e}")
        LISTENER_STATUS["tcp"]["status"] = f"error: {e}"
        return None
