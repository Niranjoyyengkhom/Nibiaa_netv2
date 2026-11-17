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

from sqlalchemy import func, or_
from sqlalchemy.orm import Session


from app.database import SessionLocal
from app.models.decoded_message import (
    REPROCESSABLE_STATUSES,
    DecodedMessage,
    DecodedMessageStatus,
)
from app.models.device import Device
from app.models.tenant import Tenant
from app.models.application import Application
from app.models.device_configuration import utc_now
from app.models.telemetry import Telemetry
from app.services import mqtt_publisher
from app.services.connectivity_profile_service import ConnectivityProfileService
from app.services.decode_schema_service import DecodeSchemaService, run_decoder
from app.services.payload_decoder import DecodeError
from app.services.webhook_service import WebhookService
from app.services.payload_detector import detect_and_parse_payload


logger = logging.getLogger(__name__)

# Canonical fields consumed by the pipeline, not kept in telemetry.data
ROUTING_FIELDS = (
    "device_id",
    "timestamp",
    "deviceName",
    "device_name",
    "deviceType",
    "device_type",
    "credentials",
)

# 24-hour auto-retention policy for all telemetry and staging rows
RETENTION_HOURS = 24
ROUTED_RETENTION = timedelta(hours=RETENTION_HOURS)
FAILED_RETENTION = timedelta(hours=RETENTION_HOURS)
TELEMETRY_RETENTION = timedelta(hours=RETENTION_HOURS)

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
        payload_version: str | None = None,
        payload_format: str | None = None
    ):
        """
        Stages, decodes and routes one uplink and commits.
        Returns the DecodedMessage; call dispatch() for ROUTED ones
        after this returns (outside the transaction).

        provider: connectivity profile code, when the adapter that
        received the uplink knows it. Otherwise it is resolved from
        provider_sources.
        """
        if not payload_format and raw_payload:
            try:
                _, _, detected_fmt, _, _, _ = detect_and_parse_payload(raw_payload)
                payload_format = detected_fmt
            except Exception:
                payload_format = "binary"

        message = DecodedMessage(
            status=DecodedMessageStatus.DECODE_FAILED,
            transport=transport,
            source_address=source_address,
            client_id=client_id,
            device_identifier=device_identifier,
            raw_payload=raw_payload,
            payload_format=payload_format or "binary",
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
        tenant_id: int | None = None,
        device_identifier: str | None = None,
        limit: int = 100
    ):
        # Staged uplinks, newest first
        query = db.query(DecodedMessage)

        if tenant_id is not None:
            query = query.filter(DecodedMessage.tenant_id == tenant_id)

        if device_identifier is not None:
            query = query.filter(
                (DecodedMessage.device_identifier == device_identifier)
                | (DecodedMessage.client_id.ilike(f"%{device_identifier}%"))
            )

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
        Enforces 24-hour retention: purges telemetry and staging rows older than 24 hours.
        Returns the total number of deleted rows.
        """

        now = utc_now()
        cutoff = now - timedelta(hours=RETENTION_HOURS)

        # 1. Purge telemetry records older than 24 hours
        from app.models.telemetry import Telemetry
        deleted_telemetry = (
            db.query(Telemetry)
            .filter(Telemetry.timestamp < cutoff)
            .delete(synchronize_session=False)
        )

        # 2. Purge routed staging rows older than 24 hours
        routed = (
            db.query(DecodedMessage)
            .filter(
                DecodedMessage.status == DecodedMessageStatus.ROUTED,
                DecodedMessage.received_at < cutoff
            )
            .delete(synchronize_session=False)
        )

        # 3. Purge failed staging rows older than 24 hours
        failed = (
            db.query(DecodedMessage)
            .filter(
                DecodedMessage.status != DecodedMessageStatus.ROUTED,
                DecodedMessage.received_at < cutoff
            )
            .delete(synchronize_session=False)
        )

        db.commit()

        total = deleted_telemetry + routed + failed
        logger.info(
            f"24-Hour Purge: removed {deleted_telemetry} telemetry records, {routed} routed staged rows, {failed} failed staged rows."
        )
        return total

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
                self.build_event(device, telemetry, message.units),
                db=db
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
        # Reset attempt state
        message.decoded = None
        message.units = None
        message.device_pk = None
        message.tenant_id = None
        message.telemetry_id = None
        message.connection_type = None
        message.decode_activation_id = None
        message.decode_schema_id = None
        message.decoder_selection = None

        if not getattr(message, "payload_format", None) and message.raw_payload:
            try:
                _, _, detected_fmt, _, _, _ = detect_and_parse_payload(message.raw_payload)
                message.payload_format = detected_fmt
            except Exception:
                message.payload_format = "binary"

        try:
            # 1. Which provider carried it
            profile = self._resolve_provider(db, message)

            # 2. Which device (and so which tenant) sent it
            device = self._route(db, message)

            # 3. Decode with the application's decoder, else the best match
            self._decode(db, message, device, profile)

            # Update device if decoder returned special provisioning keywords
            if isinstance(message.decoded, dict):
                dev_name = message.decoded.get("deviceName") or message.decoded.get("device_name")
                dev_type = message.decoded.get("deviceType") or message.decoded.get("device_type")
                creds = message.decoded.get("credentials")
                target_app_key = (
                    message.decoded.get("application")
                    or message.decoded.get("appName")
                    or message.decoded.get("applicationName")
                    or message.decoded.get("app")
                    or message.decoded.get("applicationId")
                    or message.decoded.get("application_id")
                )
                if dev_name and str(dev_name).strip():
                    device.name = str(dev_name).strip()
                if dev_type and str(dev_type).strip():
                    device.device_type = str(dev_type).strip()
                if creds and isinstance(creds, dict):
                    existing = device.credentials if isinstance(device.credentials, dict) else {}
                    device.credentials = {**existing, **creds}
                if target_app_key is not None:
                    t_str = str(target_app_key).strip()
                    app_obj = (
                        db.query(Application).filter(Application.id == int(t_str)).first()
                        if t_str.isdigit()
                        else db.query(Application).filter(func.lower(Application.name) == func.lower(t_str)).first()
                    )
                    if app_obj and device.application_id != app_obj.id:
                        device.application_id = app_obj.id
                db.flush()

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

        if profile is None and message.provider:
            # Check case-insensitively or auto-provision connectivity profile
            from app.models.connectivity_profile import ConnectivityProfile
            prov_code = message.provider.strip().lower()
            profile = (
                db.query(ConnectivityProfile)
                .filter(func.lower(ConnectivityProfile.code) == prov_code)
                .first()
            )
            if not profile:
                conn_type = "NTN" if ("hubble" in prov_code or "sat" in prov_code or "ntn" in prov_code) else "TN"
                prov_name = "Hubble Network (Satellite BLE)" if prov_code == "hubble" else f"{message.provider.capitalize()} Network"
                profile = ConnectivityProfile(
                    code=prov_code,
                    name=prov_name,
                    connection_type=conn_type,
                    integration_status="available",
                    transport=message.transport or "webhook",
                    description=f"Auto-configured {message.provider} connectivity profile",
                    enabled=True,
                )
                db.add(profile)
                db.flush()
                logger.info("Auto-provisioned connectivity profile '%s' (%s)", prov_code, conn_type)

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

    def _auto_register_device(
        self,
        db: Session,
        identifier: str,
        message: DecodedMessage
    ) -> Device:
        """
        Auto-register a device into the platform when its first uplink is processed by the decoder.
        """
        # 1. Resolve or create active tenant
        tenant = (
            db.query(Tenant)
            .filter(Tenant.is_active == True)
            .order_by(Tenant.id.asc())
            .first()
        )
        if tenant is None:
            tenant = Tenant(
                name="Default Organization",
                type="organization",
                is_active=True
            )
            db.add(tenant)
            db.flush()

        # 2. Resolve target application
        app_target = None
        decoded = message.decoded if isinstance(message.decoded, dict) else {}
        app_key_val = (
            decoded.get("application")
            or decoded.get("appName")
            or decoded.get("applicationName")
            or decoded.get("app")
            or decoded.get("applicationId")
            or decoded.get("application_id")
        )
        if app_key_val is not None:
            val_str = str(app_key_val).strip()
            if val_str.isdigit():
                app_target = db.query(Application).filter(Application.id == int(val_str)).first()
            elif val_str:
                app_target = db.query(Application).filter(func.lower(Application.name) == func.lower(val_str)).first()

        # If not specified in payload, check if the matched decoder is assigned to an application
        if app_target is None and message.decode_schema_id:
            # Check applications.decode_schema_id (fallback decoder)
            app_target = db.query(Application).filter(Application.decode_schema_id == message.decode_schema_id).first()
            if app_target is None:
                # Check application_decoders table (multi-decoder assignment)
                from app.models.application_decoder import ApplicationDecoder
                ad = db.query(ApplicationDecoder).filter(
                    ApplicationDecoder.decode_schema_id == message.decode_schema_id,
                    ApplicationDecoder.is_active == True
                ).first()
                if ad:
                    app_target = db.query(Application).filter(Application.id == ad.application_id).first()

        application = app_target
        if application is None:
            application = (
                db.query(Application)
                .filter(Application.tenant_id == tenant.id)
                .order_by(Application.id.asc())
                .first()
            )
        if application is None:
            application = Application(
                name="Default Decoder Application",
                tenant_id=tenant.id
            )
            db.add(application)
            db.flush()

        # 3. Detect network type
        device_type = "NTN"
        if message.connection_type:
            device_type = message.connection_type
        elif message.transport in ("udp", "tcp", "https", "http", "mqtt", "webhook", "custom"):
            device_type = "Direct IP"
        elif message.transport == "cellular":
            device_type = "TN"

        # 3b. Ensure DeviceType exists under this Application
        from app.models.device_type import DeviceType
        from app.models.device_type_decoder import DeviceTypeDecoder
        dt_code = device_type.lower().replace(" ", "_").strip()
        dt = (
            db.query(DeviceType)
            .filter(
                DeviceType.application_id == application.id,
                or_(DeviceType.code == dt_code, DeviceType.name == device_type)
            )
            .first()
        )
        if not dt:
            dt = DeviceType(
                application_id=application.id,
                name=device_type,
                code=dt_code,
                network_type=device_type,
                description=f"Auto-provisioned {device_type} device type",
            )
            db.add(dt)
            db.flush()

        # 4. Create and persist Device
        device = Device(
            device_id=identifier,
            name=f"Device {identifier}",
            device_type=device_type,
            device_type_id=dt.id if dt else None,
            tenant_id=tenant.id,
            application_id=application.id,
            credentials={
                "device_id": identifier,
                "registered_by": "decoder_ingest",
                "source": message.transport or "uplink",
                "provider": message.provider,
            }
        )
        db.add(device)
        db.flush()

        logger.info(
            "Auto-registered new device '%s' (PK: %s) via decoder under Tenant %s, Application %s",
            identifier,
            device.id,
            tenant.id,
            application.id
        )
        return device

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
            device = self._auto_register_device(db, identifier, message)

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
            # If payload format is JSON, no custom byte decoder is required!
            # The variables are assigned directly from incoming JSON data.
            is_json = (getattr(message, "payload_format", None) == "json")
            if not is_json and message.raw_payload:
                try:
                    txt = message.raw_payload.decode("utf-8").strip()
                    if (txt.startswith("{") and txt.endswith("}")) or (txt.startswith("[") and txt.endswith("]")):
                        is_json = True
                except Exception:
                    pass

            if is_json:
                values, units = self._extract_json_direct(message.raw_payload)
                message.decoded = values
                message.units = units
                message.decoder_selection = "direct_json"
                return

            # If not JSON and no schema is matched, do NOT fail the pipeline!
            # Provide a clean raw payload fallback so the uplink is ROUTED,
            # stored in telemetry, and visible in Live Data & Decoder Stream!
            try:
                hex_str = message.raw_payload.hex() if message.raw_payload else ""
                message.decoded = {
                    "raw_hex": hex_str,
                    "payload_length": len(message.raw_payload) if message.raw_payload else 0,
                    "raw_bytes": list(message.raw_payload) if message.raw_payload else [],
                }
                message.units = {}
                message.decoder_selection = "raw_fallback"
                logger.info("No custom decoder matched for device '%s'; using raw decoded fallback", device.device_id)
                return
            except Exception as fallback_err:
                logger.warning("Raw fallback decode failed: %s", fallback_err)

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

    def _extract_json_direct(self, raw_payload: bytes) -> tuple[dict, dict]:
        """
        Directly assigns incoming JSON payload keys to telemetry variables
        without requiring a binary byte-decoding schema.
        """
        import json
        try:
            text = raw_payload.decode("utf-8").strip()
            data = json.loads(text)
        except Exception as e:
            raise IngestError(f"Malformed JSON payload: {e}")

        if not isinstance(data, dict):
            return {"value": data}, {}

        # If data is nested under "data"
        if "data" in data and isinstance(data["data"], dict):
            units = data.get("units") if isinstance(data.get("units"), dict) else {}
            return dict(data["data"]), {str(k): str(v) for k, v in units.items()}

        units = data.pop("units", {}) if isinstance(data.get("units"), dict) else {}
        return dict(data), {str(k): str(v) for k, v in units.items()}

    def _select_decoder(
        self,
        db: Session,
        message: DecodedMessage,
        device: Device,
        application: Application
    ):
        """
        Dynamically chooses decoder based on:
        1. Device Type Decoders configured for this device's application & device type:
           - Exact payload format match (json, hex, binary, base64)
           - Any-format / general decoder assigned to the device type
        2. Exact match on payload format + routing criteria
        3. Application's assigned fallback decoder (if compatible)
        4. Match on other attributes without format restriction
        5. Application's default decoder fallback
        """
        detected_fmt = (getattr(message, "payload_format", None) or "binary").strip().lower()

        # 1. Device Type Decoders: Lookup device type under this application
        from app.models.device_type import DeviceType
        from app.models.device_type_decoder import DeviceTypeDecoder
        from app.models.application_decoder import ApplicationDecoder

        dt = None
        if getattr(device, "device_type_id", None):
            dt = db.query(DeviceType).filter(DeviceType.id == device.device_type_id).first()
        if not dt:
            dt_name = device.device_type or ""
            dt_code = dt_name.lower().replace(" ", "_").strip()
            dt = (
                db.query(DeviceType)
                .filter(
                    DeviceType.application_id == application.id,
                    or_(DeviceType.code == dt_code, DeviceType.name == dt_name)
                )
                .first()
            )

        if dt:
            # Query active decoders assigned to this device type
            dt_decoders = (
                db.query(DeviceTypeDecoder)
                .filter(DeviceTypeDecoder.device_type_id == dt.id, DeviceTypeDecoder.is_active == True)
                .order_by(DeviceTypeDecoder.priority.desc(), DeviceTypeDecoder.id.desc())
                .all()
            )

            # 1a. Check for exact payload format affinity on this device type
            for dtd in dt_decoders:
                fmt_affinity = (dtd.payload_format or "").strip().lower()
                if fmt_affinity == detected_fmt:
                    schema = self.decode_schema_service.get_schema_for_application(db, dtd.decode_schema_id)
                    if schema:
                        message.decoder_selection = f"device_type_{dt.code}_{detected_fmt}"
                        return schema

            # 1b. Check for general / any format decoder assigned to this device type
            for dtd in dt_decoders:
                fmt_affinity = (dtd.payload_format or "").strip().lower()
                if not fmt_affinity or fmt_affinity in ("any", "all", "*"):
                    schema = self.decode_schema_service.get_schema_for_application(db, dtd.decode_schema_id)
                    if schema:
                        message.decoder_selection = f"device_type_{dt.code}_any"
                        return schema

        # 2. Check multiple decoders assigned directly to the application
        app_decoders = (
            db.query(ApplicationDecoder)
            .filter(ApplicationDecoder.application_id == application.id, ApplicationDecoder.is_active == True)
            .order_by(ApplicationDecoder.priority.desc(), ApplicationDecoder.id.desc())
            .all()
        )

        # 2a. Check for exact payload format affinity on application decoders
        for ad in app_decoders:
            fmt_affinity = (ad.payload_format or "").strip().lower()
            if fmt_affinity == detected_fmt:
                schema = self.decode_schema_service.get_schema_for_application(db, ad.decode_schema_id)
                if schema:
                    message.decoder_selection = f"application_decoder_{detected_fmt}"
                    return schema

        # 2b. Check for general / any format decoder assigned to application
        for ad in app_decoders:
            fmt_affinity = (ad.payload_format or "").strip().lower()
            if not fmt_affinity or fmt_affinity in ("any", "all", "*"):
                schema = self.decode_schema_service.get_schema_for_application(db, ad.decode_schema_id)
                if schema:
                    message.decoder_selection = "application_decoder_any"
                    return schema

        # 3. Check if an active decoder explicitly matches this payload format + criteria
        attrs_with_fmt = self.match_attributes(message, device)
        schema = self.decode_schema_service.match_decoder(
            db,
            device.tenant_id,
            attrs_with_fmt
        )
        if schema is not None and getattr(schema, "match_payload_format", None) == detected_fmt:
            message.decoder_selection = f"match_format_{detected_fmt}"
            return schema

        # 4. Check application fallback decoder if compatible
        if application.decode_schema_id is not None:
            schema = self.decode_schema_service.get_schema_for_application(
                db,
                application.decode_schema_id
            )
            if schema is not None:
                assigned_fmt = getattr(schema, "match_payload_format", None)
                if not assigned_fmt or assigned_fmt in ("any", detected_fmt):
                    message.decoder_selection = "application"
                    return schema

        # 5. Match any live decoder matching criteria
        attrs_without_fmt = dict(attrs_with_fmt)
        attrs_without_fmt.pop("payload_format", None)
        schema = self.decode_schema_service.match_decoder(
            db,
            device.tenant_id,
            attrs_without_fmt
        )
        if schema is not None:
            message.decoder_selection = "match_fallback"
            return schema

        # 6. Final fallback to application assigned decoder
        if application.decode_schema_id is not None:
            schema = self.decode_schema_service.get_schema_for_application(
                db,
                application.decode_schema_id
            )
            if schema is not None:
                message.decoder_selection = "application_fallback"
                return schema

        return None

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
            "payload_format": getattr(message, "payload_format", None),
        }

    def message_context(
        self,
        message: DecodedMessage,
        device: Device
    ):
        """
        MessageContext passed to decoders as input.context.
        Supplies format, json (if json format), hex, base64, and transport metadata.
        """
        fmt = getattr(message, "payload_format", None) or "binary"
        json_data = None
        if fmt == "json" and message.raw_payload:
            try:
                import json
                text = message.raw_payload.decode("utf-8")
                json_data = json.loads(text)
            except Exception:
                pass

        import base64
        b64_str = base64.b64encode(message.raw_payload).decode("ascii") if message.raw_payload else ""

        return {
            "messageId": message.message_ref or str(message.id),
            "receivedAt": message.received_at.isoformat(),
            "format": fmt,
            "payloadFormat": fmt,
            "json": json_data,
            "data": json_data,
            "hex": message.raw_payload.hex() if message.raw_payload else "",
            "base64": b64_str,
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

        # Store to Apache Cassandra database for high-throughput time-series storage
        try:
            from app.storage.cassandra_storage import cassandra_storage
            originator_name = device.name or device.device_id
            originator_type = device.device_type or message.connection_type or "Device"
            data_orig = f"{originator_name} via {message.provider} ({originator_type})" if message.provider else f"{originator_name} ({originator_type})"
            cassandra_storage.store_telemetry(
                tenant_id=device.tenant_id,
                device_id=device.device_id,
                timestamp=telemetry.timestamp,
                telemetry_id=telemetry.id,
                received_at=telemetry.received_at,
                provider=telemetry.provider,
                connection_type=telemetry.connection_type,
                data=telemetry.data,
                raw_payload=telemetry.raw_payload,
                data_originator=data_orig
            )
        except Exception as e:
            logger.warning(f"Cassandra telemetry persistence note: {e}")

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
