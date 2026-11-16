"""
Client service to communicate with the standalone Decoder Microservice (Port 3001).
"""
import os
import httpx
import logging

logger = logging.getLogger("nibiaanet.decoder_client")

DECODER_SERVICE_URL = os.getenv("DECODER_SERVICE_URL", "http://127.0.0.1:3001")


class DecoderClient:
    def __init__(self, base_url: str = None):
        self.base_url = (base_url or DECODER_SERVICE_URL).rstrip("/")

    async def check_health(self) -> dict:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                res = await client.get(f"{self.base_url}/health")
                return res.json()
            except Exception as e:
                logger.error(f"Decoder service unreachable at {self.base_url}: {e}")
                return {"status": "unreachable", "error": str(e)}

    async def run_decode(self, code: str, payload: str, format_type: str = "auto", device_id: str = None) -> dict:
        """
        Executes decoding on the decoder service (Port 3001).
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            payload_data = {
                "code": code,
                "payload": payload,
                "format": format_type,
                "deviceId": device_id,
            }
            res = await client.post(f"{self.base_url}/decode/run", json=payload_data)
            return res.json()

    async def ingest_message(self, message: dict) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{self.base_url}/messages", json=message)
            return res.json()


decoder_client = DecoderClient()
