import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import socket
from datetime import timedelta
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.device_configuration import utc_now
from app.models.telemetry import Telemetry
from app.models.user import User
from app.models.webhook import Webhook, WebhookDelivery, WebhookDeliveryStatus
from app.schemas.webhook import WebhookCreate, WebhookUpdate


logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5

# Wait before attempt 2, 3, 4, 5: 1, 2, 4, 8 minutes
FIRST_RETRY_DELAY = timedelta(minutes=1)

REQUEST_TIMEOUT_SECONDS = 10

DELIVERY_LIST_LIMIT = 100


def is_safe_webhook_destination(url: str) -> tuple[bool, str]:
    """
    Validates that a webhook URL is safe from SSRF attacks:
    - Scheme must be http or https
    - Hostname must be present
    - Disallows loopback, private networks, link-local (cloud metadata 169.254.x.x), multicast, reserved IPs
    """
    allow_local = os.getenv("ALLOW_LOCAL_WEBHOOKS", "").lower() in ("true", "1")
    if allow_local:
        return True, ""

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid webhook URL format"

    if parsed.scheme not in ("http", "https"):
        return False, "Webhook URL must use http or https"

    hostname = parsed.hostname
    if not hostname:
        return False, "Webhook URL must have a valid hostname"

    # Reject localhost / obvious loopbacks directly
    if hostname.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"):
        return False, "Webhooks pointing to localhost or loopback are prohibited"

    # Check if hostname is an IP literal
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False, f"Webhooks pointing to internal/private IP ({ip}) are prohibited"
        return True, ""
    except ValueError:
        pass

    # Resolve hostname to verify destination IP addresses
    try:
        addr_info = socket.getaddrinfo(hostname, None)
        for item in addr_info:
            ip_str = item[4][0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                return False, f"Webhook host resolves to internal/private IP ({ip})"
    except socket.gaierror:
        pass

    return True, ""


def http_post(url: str, body: bytes, headers: dict):
    """
    Returns the HTTP status code. Raises httpx.HTTPError when the
    endpoint cannot be reached. Replaced in the tests.
    """
    safe, reason = is_safe_webhook_destination(url)
    if not safe:
        raise httpx.RequestError(f"Blocked SSRF destination: {reason}")

    response = httpx.post(
        url,
        content=body,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    return response.status_code


def sign(secret: str, body: bytes):
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def matches_filters(filters: dict, event: dict):
    # A missing or empty list means "everything"
    for filter_key, event_key in (
        ("device_ids", "device_id"),
        ("connection_types", "connection_type"),
        ("providers", "provider"),
    ):
        allowed = filters.get(filter_key)

        if allowed and event.get(event_key) not in allowed:
            return False

    return True


class WebhookService:

    # ================================
    # Pipeline
    # ================================

    def queue_deliveries(
        self,
        db: Session,
        telemetry: Telemetry,
        event: dict
    ):
        """
        One PENDING delivery per enabled webhook of the device's tenant
        whose filters match. Called in the ingest transaction.
        """

        webhooks = (
            db.query(Webhook)
            .filter(
                Webhook.tenant_id == event["tenant_id"],
                Webhook.enabled.is_(True)
            )
            .all()
        )

        now = utc_now()

        for webhook in webhooks:
            if not matches_filters(webhook.filters or {}, event):
                continue

            db.add(
                WebhookDelivery(
                    webhook_id=webhook.id,
                    telemetry_id=telemetry.id,
                    payload=event,
                    status=WebhookDeliveryStatus.PENDING,
                    next_attempt_at=now,
                )
            )

    def attempt(
        self,
        db: Session,
        delivery: WebhookDelivery
    ):
        webhook = db.get(Webhook, delivery.webhook_id)
        now = utc_now()

        body = json.dumps(delivery.payload).encode()
        headers = {
            "Content-Type": "application/json",
            "X-NibiaaNet-Event": delivery.payload.get("event", "telemetry.uplink"),
            "X-NibiaaNet-Delivery": str(delivery.id),
            "X-NibiaaNet-Signature": sign(webhook.secret, body),
        }

        delivery.attempts += 1
        delivery.last_attempt_at = now

        try:
            status_code = http_post(webhook.url, body, headers)
            delivery.last_status_code = status_code
            delivery.last_error = (
                None if 200 <= status_code < 300 else f"HTTP {status_code}"
            )
        except httpx.HTTPError as error:
            delivery.last_status_code = None
            delivery.last_error = f"{type(error).__name__}: {error}"[:500]

        if delivery.last_error is None:
            delivery.status = WebhookDeliveryStatus.DELIVERED
            delivery.delivered_at = now
            delivery.next_attempt_at = None

        elif delivery.attempts >= MAX_ATTEMPTS:
            # Alert: listed by GET /webhooks/alerts
            delivery.status = WebhookDeliveryStatus.UNDELIVERABLE
            delivery.next_attempt_at = None
            logger.warning(
                "Webhook delivery %s to %s is undeliverable: %s",
                delivery.id,
                webhook.url,
                delivery.last_error,
            )

        else:
            delivery.status = WebhookDeliveryStatus.RETRYING
            delivery.next_attempt_at = (
                now + FIRST_RETRY_DELAY * 2 ** (delivery.attempts - 1)
            )

    def attempt_for_telemetry(
        self,
        db: Session,
        telemetry_id: int
    ):
        deliveries = (
            db.query(WebhookDelivery)
            .filter(
                WebhookDelivery.telemetry_id == telemetry_id,
                WebhookDelivery.status == WebhookDeliveryStatus.PENDING
            )
            # Skips deliveries the retry worker is sending right now
            .with_for_update(skip_locked=True)
            .all()
        )

        for delivery in deliveries:
            self.attempt(db, delivery)

        db.commit()

    def retry_due(
        self,
        db: Session,
        limit: int = 100
    ):
        """
        Attempts every PENDING / RETRYING delivery that is due.
        Run periodically by app/delivery_worker.py.
        """

        deliveries = (
            db.query(WebhookDelivery)
            .filter(
                WebhookDelivery.status.in_([
                    WebhookDeliveryStatus.PENDING,
                    WebhookDeliveryStatus.RETRYING,
                ]),
                WebhookDelivery.next_attempt_at <= utc_now()
            )
            .order_by(WebhookDelivery.next_attempt_at)
            .limit(limit)
            # Several workers never send the same delivery twice
            .with_for_update(skip_locked=True)
            .all()
        )

        for delivery in deliveries:
            self.attempt(db, delivery)

        db.commit()

        return len(deliveries)

    # ================================
    # Management (admin / tenant_admin)
    # ================================

    def create_webhook(
        self,
        db: Session,
        data: WebhookCreate,
        current_user: User
    ):
        safe, reason = is_safe_webhook_destination(str(data.url))
        if not safe:
            raise HTTPException(
                status_code=400,
                detail=reason
            )

        tenant_id = self._tenant_for_create(data.tenant_id, current_user)

        webhook = Webhook(
            tenant_id=tenant_id,
            name=data.name,
            url=str(data.url),
            secret=secrets.token_hex(32),
            enabled=data.enabled,
            filters=data.filters.model_dump(),
        )

        db.add(webhook)
        db.commit()
        db.refresh(webhook)

        # The secret is shown only here
        return {**self.webhook_response(webhook), "secret": webhook.secret}

    def get_webhooks(
        self,
        db: Session,
        current_user: User
    ):
        query = self._webhooks_query(db, current_user)

        return [
            self.webhook_response(webhook)
            for webhook in query.order_by(Webhook.id).all()
        ]

    def get_webhook(
        self,
        db: Session,
        webhook_id: int,
        current_user: User
    ):
        return self.webhook_response(
            self._get_webhook(db, webhook_id, current_user)
        )

    def update_webhook(
        self,
        db: Session,
        webhook_id: int,
        data: WebhookUpdate,
        current_user: User
    ):
        webhook = self._get_webhook(db, webhook_id, current_user)

        if data.name is not None:
            webhook.name = data.name

        if data.url is not None:
            safe, reason = is_safe_webhook_destination(str(data.url))
            if not safe:
                raise HTTPException(
                    status_code=400,
                    detail=reason
                )
            webhook.url = str(data.url)

        if data.enabled is not None:
            webhook.enabled = data.enabled

        if data.filters is not None:
            webhook.filters = data.filters.model_dump()

        db.commit()
        db.refresh(webhook)

        return self.webhook_response(webhook)

    def delete_webhook(
        self,
        db: Session,
        webhook_id: int,
        current_user: User
    ):
        webhook = self._get_webhook(db, webhook_id, current_user)

        db.delete(webhook)
        db.commit()

    def get_deliveries(
        self,
        db: Session,
        webhook_id: int,
        status: str | None,
        current_user: User
    ):
        webhook = self._get_webhook(db, webhook_id, current_user)

        query = (
            db.query(WebhookDelivery)
            .filter(WebhookDelivery.webhook_id == webhook.id)
        )

        if status is not None:
            query = query.filter(WebhookDelivery.status == status)

        return (
            query
            .order_by(WebhookDelivery.id.desc())
            .limit(DELIVERY_LIST_LIMIT)
            .all()
        )

    def get_alerts(
        self,
        db: Session,
        current_user: User
    ):
        """
        Undeliverable deliveries of the caller's webhooks, newest first.
        """

        webhook_ids = self._webhooks_query(db, current_user).with_entities(Webhook.id)

        return (
            db.query(WebhookDelivery)
            .filter(
                WebhookDelivery.webhook_id.in_(webhook_ids),
                WebhookDelivery.status == WebhookDeliveryStatus.UNDELIVERABLE
            )
            .order_by(WebhookDelivery.id.desc())
            .limit(DELIVERY_LIST_LIMIT)
            .all()
        )

    def redeliver(
        self,
        db: Session,
        delivery_id: int,
        current_user: User
    ):
        """
        Sends a delivery again now (e.g. after the endpoint is fixed)
        and gives it a fresh set of attempts.
        """

        delivery = db.get(WebhookDelivery, delivery_id)

        if delivery is None:
            raise HTTPException(
                status_code=404,
                detail="Delivery not found"
            )

        # Enforces tenant ownership through the webhook
        self._get_webhook(db, delivery.webhook_id, current_user)

        delivery.attempts = 0
        self.attempt(db, delivery)
        db.commit()
        db.refresh(delivery)

        return delivery

    # ================================
    # Helpers
    # ================================

    def webhook_response(self, webhook: Webhook):
        return {
            "id": webhook.id,
            "tenant_id": webhook.tenant_id,
            "name": webhook.name,
            "url": webhook.url,
            "enabled": webhook.enabled,
            "filters": webhook.filters or {},
            "created_at": webhook.created_at,
            "updated_at": webhook.updated_at,
        }

    def _tenant_for_create(
        self,
        tenant_id: int | None,
        current_user: User
    ):
        if current_user.role == "admin":
            if tenant_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="Admin must provide a tenant_id"
                )

            return tenant_id

        if current_user.role == "owner" and current_user.tenant_id is not None:
            # Always their own organization, whatever was sent
            return current_user.tenant_id

        raise HTTPException(
            status_code=403,
            detail="User cannot manage webhooks"
        )

    def _webhooks_query(
        self,
        db: Session,
        current_user: User
    ):
        query = db.query(Webhook)

        if current_user.role == "admin":
            return query

        if current_user.role == "owner" and current_user.tenant_id is not None:
            return query.filter(Webhook.tenant_id == current_user.tenant_id)

        raise HTTPException(
            status_code=403,
            detail="User cannot manage webhooks"
        )

    def _get_webhook(
        self,
        db: Session,
        webhook_id: int,
        current_user: User
    ):
        # Another tenant's webhook is not found, not revealed
        webhook = (
            self._webhooks_query(db, current_user)
            .filter(Webhook.id == webhook_id)
            .first()
        )

        if webhook is None:
            raise HTTPException(
                status_code=404,
                detail="Webhook not found"
            )

        return webhook
