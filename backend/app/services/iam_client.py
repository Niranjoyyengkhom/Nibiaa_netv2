"""
Client service to communicate with the standalone IAM (User, Roles, Attribute) Microservice (Port 3003).
"""
import os
import httpx
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("nibiaanet.iam_client")

IAM_SERVICE_URL = os.getenv("IAM_SERVICE_URL", "http://127.0.0.1:3003")


class IAMClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or IAM_SERVICE_URL).rstrip("/")

    async def check_health(self) -> dict:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                res = await client.get(f"{self.base_url}/health")
                return res.json()
            except Exception as e:
                logger.error(f"IAM service unreachable at {self.base_url}: {e}")
                return {"status": "unreachable", "error": str(e)}

    async def introspect_token(self, token: str) -> dict:
        """
        Validates token signature, expiration, and resolves user roles,
        permissions, and dynamic attributes in one microservice call.
        """
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                res = await client.post(f"{self.base_url}/auth/introspect", json={"token": token})
                return res.json()
            except Exception as e:
                logger.error(f"IAM introspect failed at {self.base_url}: {e}")
                return {"active": False, "error": str(e)}

    async def evaluate_abac(
        self,
        action: str,
        resource_type: str,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        resource_id: Optional[str] = None,
        resource_attributes: Optional[Dict[str, Any]] = None,
        context_attributes: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """
        Policy Decision Point (PDP) evaluation for fine-grained authorization.
        """
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                payload = {
                    "action": action,
                    "resource_type": resource_type,
                    "user_id": user_id,
                    "username": username,
                    "resource_id": resource_id,
                    "resource_attributes": resource_attributes or {},
                    "context_attributes": context_attributes or {},
                }
                res = await client.post(f"{self.base_url}/abac/evaluate", json=payload)
                return res.json()
            except Exception as e:
                logger.error(f"IAM ABAC evaluation failed: {e}")
                return {"allowed": False, "effect": "DENY", "error": str(e)}

    async def get_user_attributes(self, user_id: int) -> dict:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                res = await client.get(f"{self.base_url}/users/{user_id}/attributes")
                return res.json()
            except Exception as e:
                logger.error(f"Failed to fetch user {user_id} attributes: {e}")
                return {}

    async def get_entity_attributes(self, entity_type: str, entity_id: str) -> dict:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                res = await client.get(f"{self.base_url}/attributes/entities/{entity_type}/{entity_id}")
                return res.json().get("attributes", {})
            except Exception as e:
                logger.error(f"Failed to fetch {entity_type} {entity_id} attributes: {e}")
                return {}


iam_client = IAMClient()
