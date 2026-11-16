import asyncio
import json
import logging
import uuid
from typing import Tuple, Optional
from app.forwarder import forward_to_backend
from app.metrics import LISTENER_STATUS

logger = logging.getLogger("nibiaanet.protocol_ingestion.mqtt")
MQTT_PORT = 1883


def decode_remaining_length(data: bytes, offset: int = 1) -> Tuple[int, int]:
    """Decodes MQTT variable-length integer. Returns (length, bytes_consumed)."""
    multiplier = 1
    value = 0
    idx = offset
    while idx < len(data):
        encoded_byte = data[idx]
        value += (encoded_byte & 0x7F) * multiplier
        multiplier *= 128
        idx += 1
        if (encoded_byte & 0x80) == 0:
            break
    return value, (idx - offset)


class MqttClientHandler:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        peer = writer.get_extra_info("peername")
        self.remote_ip = peer[0] if peer else "unknown"
        self.remote_port = peer[1] if peer else 0
        self.client_id = f"mqtt-{self.remote_ip}:{self.remote_port}"

    async def handle(self):
        logger.info(f"MQTT client connected from {self.remote_ip}:{self.remote_port}")
        try:
            while True:
                # Read 1st byte (Packet Type & Flags)
                header = await self.reader.read(1)
                if not header:
                    break
                packet_type = header[0] >> 4
                flags = header[0] & 0x0F

                # Read remaining length
                multiplier = 1
                rem_len = 0
                while True:
                    b = await self.reader.read(1)
                    if not b:
                        return
                    byte_val = b[0]
                    rem_len += (byte_val & 0x7F) * multiplier
                    multiplier *= 128
                    if (byte_val & 0x80) == 0:
                        break

                # Read variable header and payload
                body = b""
                if rem_len > 0:
                    body = await self.reader.readexactly(rem_len)

                # Process Packet Type
                # 1 = CONNECT
                if packet_type == 1:
                    # Parse Client ID if present
                    if len(body) >= 12:
                        proto_len = int.from_bytes(body[0:2], "big")
                        idx = 2 + proto_len + 4  # skip proto name, version, flags, keepalive
                        if idx + 2 <= len(body):
                            cid_len = int.from_bytes(body[idx:idx+2], "big")
                            if idx + 2 + cid_len <= len(body):
                                self.client_id = body[idx+2:idx+2+cid_len].decode("utf-8", errors="ignore")

                    logger.debug(f"MQTT CONNECT from client_id={self.client_id}")
                    # Send CONNACK (Connection Accepted, Session Present = 0)
                    self.writer.write(bytes([0x20, 0x02, 0x00, 0x00]))
                    await self.writer.drain()

                # 3 = PUBLISH
                elif packet_type == 3:
                    qos = (flags >> 1) & 0x03
                    offset = 0
                    if len(body) < 2:
                        continue
                    topic_len = int.from_bytes(body[0:2], "big")
                    offset = 2 + topic_len
                    topic = body[2:offset].decode("utf-8", errors="ignore")

                    packet_id = None
                    if qos > 0 and len(body) >= offset + 2:
                        packet_id = body[offset:offset+2]
                        offset += 2

                    payload_bytes = body[offset:]
                    logger.info(f"MQTT PUBLISH on '{topic}' ({len(payload_bytes)} bytes) from {self.client_id}")

                    # Extract Device ID from topic or payload
                    device_id = None
                    parts = topic.strip("/").split("/")
                    # Common patterns: nibiaanet/uplink/<device_id>, devices/<device_id>/telemetry, uplink/<device_id>
                    for i, p in enumerate(parts):
                        if p in ("devices", "uplink", "device", "nodes", "tenants") and i + 1 < len(parts):
                            device_id = parts[i + 1]
                            break
                    if not device_id and len(parts) >= 2:
                        device_id = parts[-1]

                    # Parse payload if JSON
                    raw_payload = payload_bytes
                    try:
                        text = payload_bytes.decode("utf-8")
                        if text.startswith("{") and text.endswith("}"):
                            p_json = json.loads(text)
                            if not device_id:
                                device_id = p_json.get("deviceId") or p_json.get("device_id")
                            p_val = p_json.get("payload") or p_json.get("data")
                            if p_val and isinstance(p_val, str):
                                try:
                                    raw_payload = bytes.fromhex(p_val.replace("0x", ""))
                                except ValueError:
                                    raw_payload = p_val.encode("utf-8")
                    except Exception:
                        pass

                    # Forward to backend
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        forward_to_backend,
                        "mqtt",
                        raw_payload,
                        device_id,
                        self.remote_ip,
                        self.remote_port,
                        self.client_id,
                        "mqtt",
                        topic,
                        f"mqtt-{uuid.uuid4().hex[:8]}",
                    )

                    # Send PUBACK if QoS == 1
                    if qos == 1 and packet_id:
                        self.writer.write(bytes([0x40, 0x02]) + packet_id)
                        await self.writer.drain()

                # 12 = PINGREQ
                elif packet_type == 12:
                    # Send PINGRESP
                    self.writer.write(bytes([0xD0, 0x00]))
                    await self.writer.drain()

                # 14 = DISCONNECT
                elif packet_type == 14:
                    logger.debug(f"MQTT client {self.client_id} disconnected cleanly.")
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"MQTT client {self.remote_ip}:{self.remote_port} exception: {e}")
        finally:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass


async def handle_mqtt_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    handler = MqttClientHandler(reader, writer)
    await handler.handle()


async def start_mqtt_broker(port: int = MQTT_PORT):
    try:
        server = await asyncio.start_server(handle_mqtt_client, "0.0.0.0", port)
        LISTENER_STATUS["mqtt"]["status"] = "online"
        logger.info(f"MQTT Ingestion Broker online on 0.0.0.0:{port}")
        return server
    except Exception as e:
        logger.error(f"Failed to bind MQTT port {port}: {e}")
        LISTENER_STATUS["mqtt"]["status"] = f"error: {e}"
        return None
