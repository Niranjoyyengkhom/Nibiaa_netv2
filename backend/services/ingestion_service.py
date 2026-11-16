"""
Uplink pipeline:

  queue message (transport, source, device id, raw bytes)
    -> decoded_messages      (staging, always written first)
    -> provider resolution   (connectivity profile: adapter's provider
                              code, or provider_sources: UDP source IP /
                              client id)
    -> multi-tenant routing  (device registry: device -> tenant, application)
    -> decoder selection     (the application's decoder; else the live
                              decoder whose DecoderMatch fits best)
    -> decode                (JavaScript decoder in the sandbox, or fields)
    -> telemetry             (normalized JSON + original bytes)
    -> delivery              (REST reads telemetry; MQTT + webhooks pushed)

There is no Redis / RabbitMQ consumer yet: POST /ingest/uplinks plays
the queue. A future consumer only has to call process_uplink().
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session


from app.database import SessionLocal
from app.models.decoded_message import (
    REPROCESSABLE_STATUSES,
    DecodedMessage,
    DecodedMessageStatus,
)
from app.models.device import Device
from app.models.application import Application
from app.models.device_configuration import utc_now
from app.models.telemetry import Telemetry
from app.services import mqtt_publisher
from app.services.connectivity_profile_service import ConnectivityProfileService
from app.services.decode_schema_service import DecodeSchemaService, run_decoder
from app.services.payload_decoder import DecodeError
from app.services.webhook_service import WebhookService


logger = logging.getLogger(__name__)

# Canonical fields consumed by the pipeline, not kept in telemetry.data
ROUTING_FIELDS = ("device_id", "timestamp")

# How long staging rows are kept (see purge)
ROUTED_RETENTION = timedelta(hours=72)
FAILED_RETENTION = timedelta(days=30)

REPROCESS_LIMIT = 1000


class IngestError(Exception):
    pass


class IngestionService:

    def __init__(self):
        self.decode_schema_service = DecodeSchemaService()
        self.connectivity_profile_service = ConnectivityProfileService()
        self.webhook_service = WebhookService()

    # ================================
    # Entry points
    # ================================

    def process_uplink(
        self,
        db: Session,
        transport: str,
        raw_payload: bytes,
        source_address: str | None = None,
        client_id: str | None = None,
        device_identifier: str | None = None,
        received_at: datetime | None = None,
        provider: str | None = None,
        message_ref: str | None = None,
        remote_port: int | None = None,
        protocol_id: str | None = None,
        message_type: str | None = None,
        payload_version: str | None = None
    ):
        """
        Stages, decodes and routes one uplink and commits.
        Returns the DecodedMessage; call dispatch() for ROUTED ones
        after this returns (outside the transaction).

        provider: connectivity profile code, when the adapter that
        received the uplink knows it. Otherwise it is resolved from
        provider_sources.
        """

        message = DecodedMessage(
            status=DecodedMessageStatus.DECODE_FAILED,
            transport=transport,
            source_address=source_address,
            client_id=client_id,
            device_identifier=device_identifier,
            raw_payload=raw_payload,
            received_at=received_at or utc_now(),
            provider=provider,
            message_ref=message_ref,
            remote_port=remote_port,
            protocol_id=protocol_id,
            message_type=message_type,
            payload_version=payload_version,
            attempts=0,
        )

        db.add(message)
        db.flush()

        self._process(db, message)
        db.commit()
        db.refresh(message)

        return message

    def list_messages(
        self,
        db: Session,
        status: str | None = None,
        limit: int = 100
    ):
        # Staged uplinks, newest first
        query = db.query(DecodedMessage)

        if status is not None:
            query = query.filter(DecodedMessage.status == status)

        return (
            query
            .order_by(DecodedMessage.id.desc())
            .limit(limit)
            .all()
        )

    def reprocess(
        self,
        db: Session,
        provider: str | None = None,
        statuses: list[str] | None = None,
        limit: int = REPROCESS_LIMIT
    ):
        """
        Runs failed staged messages through the pipeline again, e.g.
        after a decoder is corrected or a device registered.
        Returns {processed, routed, messages}, messages in id order.
        """

        statuses = statuses or REPROCESSABLE_STATUSES

        query = (
            db.query(DecodedMessage)
            .filter(
                DecodedMessage.status.in_([
                    status for status in statuses
                    if status in REPROCESSABLE_STATUSES
                ])
            )
        )

        if provider is not None:
            query = query.filter(DecodedMessage.provider == provider)

        messages = (
            query
            .order_by(DecodedMessage.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .all()
        )

        for message in messages:
            self._process(db, message)

        db.commit()

        return {
            "processed": len(messages),
            "routed": sum(
                1
                for message in messages
                if message.status == DecodedMessageStatus.ROUTED
            ),
            "messages": messages,
        }

    def purge(
        self,
        db: Session
    ):
        """
        Staging is temporary: ROUTED rows are already in telemetry
        (with their raw bytes); failed rows are kept longer so they can
        still be reprocessed. Returns the number of deleted rows.
        """

        now = utc_now()

        routed = (
            db.query(DecodedMessage)
            .filter(
                DecodedMessage.status == DecodedMessageStatus.ROUTED,
                DecodedMessage.received_at < now - ROUTED_RETENTION
            )
            .delete(synchronize_session=False)
        )

        failed = (
            db.query(DecodedMessage)
            .filter(
                DecodedMessage.status != DecodedMessageStatus.ROUTED,
                DecodedMessage.received_at < now - FAILED_RETENTION
            )
            .delete(synchronize_session=False)
        )

        db.commit()

        return routed + failed

    def dispatch(
        self,
        message_id: int
    ):
        """
        Pushes a ROUTED message to MQTT and the tenant's webhooks.
        Runs after the response (background task) with its own session.
        Failed webhook attempts are retried by app/delivery_worker.py.
        """

        db = SessionLocal()

        try:
            message = db.get(DecodedMessage, message_id)

            if message is None or message.telemetry_id is None:
                return

            telemetry = db.get(Telemetry, message.telemetry_id)
            device = db.get(Device, telemetry.device_pk)

            message.mqtt_status = mqtt_publisher.publish_event(
                self.build_event(device, telemetry, message.units)
            )
            db.commit()

            self.webhook_service.attempt_for_telemetry(db, telemetry.id)

        except Exception:
            # Webhook rows stay PENDING and the worker picks them up
            logger.exception("Dispatch of decoded message %s failed", message_id)
            db.rollback()

        finally:
            db.close()

    # ================================
    # Pipeline steps
    # ================================

    def _process(
        self,
        db: Session,
        message: DecodedMessage
    ):
        message.attempts += 1
        message.processed_at = utc_now()
        message.error = None

        # A reprocessed message must not keep results
        # of an earlier attempt. The provider code is kept: it is the
        # adapter's hint, or the provider resolved last time.
        message.decoded = None
        message.units = None
        message.device_pk = None
        message.tenant_id = None
        message.telemetry_id = None
        message.connection_type = None
        message.decode_activation_id = None
        message.decode_schema_id = None
        message.decoder_selection = None

        try:
            # 1. Which provider carried it
            profile = self._resolve_provider(db, message)

            # 2. Which device (and so which tenant) sent it
            device = self._route(db, message)

            # 3. Decode with the application's decoder, else the best match
            self._decode(db, message, device, profile)

            # 4. Store decoded telemetry
            self._store(db, message, device)

        except IngestError as error:
            message.error = str(error)

            logger.info(
                "Uplink %s not routed: %s %s",
                message.id,
                message.status,
                message.error,
            )

    def _resolve_provider(
        self,
        db: Session,
        message: DecodedMessage
    ):
        profile = self.connectivity_profile_service.resolve(
            db,
            message.transport,
            message.source_address,
            message.client_id,
            message.provider
        )

        if profile is None:

            # The adapter named a provider that has no profile
            if message.provider is not None:
                message.status = DecodedMessageStatus.UNKNOWN_PROVIDER
                raise IngestError(
                    f"Connectivity profile '{message.provider}' does not exist"
                )

            # Unknown source: still decoded, provider stays unknown
            return None

        if not profile.enabled:
            message.provider = profile.code
            message.status = DecodedMessageStatus.UNKNOWN_PROVIDER
            raise IngestError(
                f"Connectivity profile '{profile.code}' is disabled"
            )

        message.provider = profile.code
        message.connection_type = profile.connection_type

        return profile

    def _route(
        self,
        db: Session,
        message: DecodedMessage
    ):
        # For now, the device identifier comes from
        # IncomingMessage.source.deviceId (set by the adapter)
        identifier = message.device_identifier

        if identifier is None:
            message.status = DecodedMessageStatus.UNKNOWN_DEVICE
            raise IngestError("No device identifier in the incoming message")

        device = (
            db.query(Device)
            .filter(Device.device_id == identifier)
            .first()
        )

        if device is None:
            message.status = DecodedMessageStatus.UNKNOWN_DEVICE
            raise IngestError(f"Device '{identifier}' is not registered")

        # The tenant comes from the registry, never from the message
        message.device_pk = device.id
        message.tenant_id = device.tenant_id

        return device

    def _decode(
        self,
        db: Session,
        message: DecodedMessage,
        device: Device,
        profile
    ):
        if (
            profile is not None
            and profile.max_payload_bytes is not None
            and len(message.raw_payload) > profile.max_payload_bytes
        ):
            message.status = DecodedMessageStatus.DECODE_FAILED
            raise IngestError(
                f"Payload is {len(message.raw_payload)} bytes, "
                f"'{profile.code}' allows at most {profile.max_payload_bytes}"
            )

        application = db.get(Application, device.application_id)

        if application is None:
            message.status = DecodedMessageStatus.NO_ACTIVE_SCHEMA
            raise IngestError(
                f"Application '{device.application_id}' is not registered"
            )

        schema = self._select_decoder(db, message, device, application)

        if schema is None:
            message.status = DecodedMessageStatus.NO_ACTIVE_SCHEMA
            raise IngestError(
                f"Application '{application.name}' has no decoder, and no live "
                f"decoder matches {self.match_attributes(message, device)}"
            )

        message.decode_schema_id = schema.id

        # Which activation decodes it (None if the version was assigned
        # to the application directly and never activated). Kept on
        # failures too, to see which version a payload did not fit.
        message.decode_activation_id = (
            self.decode_schema_service.active_activation_id(db, schema.id)
        )

        try:
            values, units = run_decoder(
                schema,
                message.raw_payload,
                self.message_context(message, device)
            )
        except DecodeError as error:
            message.status = DecodedMessageStatus.DECODE_FAILED
            raise IngestError(f"{schema.name} v{schema.version}: {error}")

        message.decoded = values
        message.units = units

    def _select_decoder(
        self,
        db: Session,
        message: DecodedMessage,
        device: Device,
        application: Application
    ):
        """
        1. The decoder version assigned to the device's application.
        2. Else the live decoder whose DecoderMatch fits best.
        """

        if application.decode_schema_id is not None:
            schema = self.decode_schema_service.get_schema_for_application(
                db,
                application.decode_schema_id
            )

            if schema is not None:
                message.decoder_selection = "application"
                return schema

        schema = self.decode_schema_service.match_decoder(
            db,
            device.tenant_id,
            self.match_attributes(message, device)
        )

        if schema is not None:
            message.decoder_selection = "match"

        return schema

    def match_attributes(
        self,
        message: DecodedMessage,
        device: Device
    ):
        # The DecoderMatch keys an uplink is compared with
        return {
            "provider_id": message.provider,
            "protocol_id": message.protocol_id or message.transport,
            "device_type_id": device.device_type,
            "message_type": message.message_type,
            "version": message.payload_version,
        }

    def message_context(
        self,
        message: DecodedMessage,
        device: Device
    ):
        """
        MessageContext passed to JavaScript decoders as input.context
        (decoderId, decoderName and decoderVersion are added when it runs).
        """

        return {
            "messageId": message.message_ref or str(message.id),
            "receivedAt": message.received_at.isoformat(),
            "transport": {
                "type": message.transport,
                "connectionId": message.client_id,
                "remoteAddress": message.source_address,
                "remotePort": message.remote_port,
            },
            "providerId": message.provider,
            "connectionType": message.connection_type,
            "protocolId": message.protocol_id or message.transport,
            "messageType": message.message_type,
            "version": message.payload_version,
            "deviceId": device.device_id,
            "deviceTypeId": device.device_type,
            "applicationId": device.application_id,
            "tenantId": device.tenant_id,
        }

    def _store(
        self,
        db: Session,
        message: DecodedMessage,
        device: Device
    ):
        timestamp = message.received_at

        if message.decoded.get("timestamp") is not None:
            try:
                timestamp = datetime.fromtimestamp(
                    message.decoded["timestamp"],
                    tz=timezone.utc
                )
            except (OverflowError, OSError, ValueError, TypeError):
                message.status = DecodedMessageStatus.DECODE_FAILED
                raise IngestError(
                    f"timestamp {message.decoded['timestamp']} is not a valid Unix time"
                )

        telemetry = Telemetry(
            device_pk=device.id,
            timestamp=timestamp,
            received_at=message.received_at,
            provider=message.provider,
            connection_type=message.connection_type,
            decode_activation_id=message.decode_activation_id,
            decode_schema_id=message.decode_schema_id,
            data={
                key: value
                for key, value in message.decoded.items()
                if key not in ROUTING_FIELDS
            },
            raw_payload=message.raw_payload,
        )

        db.add(telemetry)
        db.flush()

        message.telemetry_id = telemetry.id
        message.status = DecodedMessageStatus.ROUTED

        # Webhook deliveries are created in the same transaction,
        # so a stored uplink is never missing its deliveries.
        self.webhook_service.queue_deliveries(
            db,
            telemetry,
            self.build_event(device, telemetry, message.units)
        )

    # ================================
    # Helpers
    # ================================

    def build_event(
        self,
        device: Device,
        telemetry: Telemetry,
        units: dict | None
    ):
        # The body sent to MQTT subscribers and webhooks
        return {
            "event": "telemetry.uplink",
            "telemetry_id": telemetry.id,
            "tenant_id": device.tenant_id,
            "device_id": device.device_id,
            "application_id": device.application_id,
            "timestamp": telemetry.timestamp.isoformat(),
            "received_at": telemetry.received_at.isoformat(),
            "provider": telemetry.provider,
            "connection_type": telemetry.connection_type,
            "decode_activation_id": telemetry.decode_activation_id,
            "decode_schema_id": telemetry.decode_schema_id,
            "telemetry": telemetry.data,
            "units": units or {},
        }
