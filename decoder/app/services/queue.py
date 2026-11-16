import os
import json
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any

import redis
import fakeredis

from app.services.parser import parse_payload
from app.services.executor import decoder_executor
from app.services.registry import select_best_decoder
from app.services.sinks import sinks
from app.services.device_registry import ensure_device_registered
from app.services.device_keywords import extract_device_keywords
from app.database import SessionLocal
from app.models.decoder import DecoderDefinition, DecoderVersion

logger = logging.getLogger("nibiaanet.decoder.queue")

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
QUEUE_KEY = "nibiaanet:telemetry:unprocessed"


class MessageQueueWorker:
    def __init__(self):
        self._task = None
        self._running = False
        self._init_redis()

    def _init_redis(self):
        try:
            client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
            client.ping()
            self._redis = client
            self._is_fake = False
            logger.info("Decoder queue connected to real Redis server.")
        except Exception:
            self._redis = fakeredis.FakeRedis(decode_responses=True)
            self._is_fake = True
            logger.info("Decoder queue using embedded Redis queue engine.")

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info("Redis unprocessed telemetry queue worker started.")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def enqueue(self, message: dict):
        serialized = json.dumps(message)
        await asyncio.to_thread(self._redis.lpush, QUEUE_KEY, serialized)

    async def _process_loop(self):
        while self._running:
            try:
                res = await asyncio.to_thread(self._redis.brpop, QUEUE_KEY, 1)
                if not res:
                    await asyncio.sleep(0.1)
                    continue
                _, raw = res
                msg = json.loads(raw)
                await self._process_message(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Redis queue message processing: {e}")
                await asyncio.sleep(0.5)

    async def _process_message(self, msg: dict):
        message_id = msg.get("messageId") or str(uuid.uuid4())
        device_id = msg.get("deviceId")
        transport = msg.get("transport", "http")
        payload_str = msg.get("payload", "")
        fmt = msg.get("format", "auto")
        context = msg.get("context", {})
        tenant_id = msg.get("tenantId")

        # Automatically register device into platform if deviceId provided
        if device_id:
            try:
                with SessionLocal() as db:
                    dev_rec = ensure_device_registered(
                        db=db,
                        device_id=device_id,
                        device_type=msg.get("device_type") or context.get("deviceType") or "NTN",
                        tenant_id=tenant_id,
                        application_id=context.get("applicationId") or context.get("application_id"),
                        application_name=context.get("application") or context.get("appName") or context.get("app"),
                        credentials={
                            "source": transport,
                            "registered_by": "decoder_queue",
                            "provider": msg.get("provider") or context.get("provider") or context.get("providerId"),
                        },
                    )
                    if dev_rec and not tenant_id:
                        tenant_id = dev_rec.get("tenant_id")
            except Exception as e:
                logger.warning(f"Decoder auto-registration for device '{device_id}' failed: {e}")

        try:
            raw_bytes, hex_str, detected_fmt = parse_payload(payload_str, fmt)
            if raw_bytes and raw_bytes.strip().startswith(b"{") and raw_bytes.strip().endswith(b"}"):
                detected_fmt = "json"
            context["format"] = detected_fmt
            context["payloadFormat"] = detected_fmt
            context["payload_format"] = detected_fmt
            if detected_fmt == "json":
                try:
                    context["json"] = json.loads(raw_bytes.decode("utf-8"))
                except Exception:
                    pass
        except Exception as e:
            # Store failure
            now_utc = datetime.now(timezone.utc)
            with SessionLocal() as db:
                sinks.store_message(
                    db=db,
                    message_id=message_id,
                    received_at=now_utc,
                    device_id=device_id,
                    transport=transport,
                    status="failed",
                    body={
                        "error": f"Payload parse failure: {e}",
                        "payload": payload_str,
                        "receivedAt": now_utc.isoformat(),
                        "received_at": now_utc.isoformat(),
                    },
                    tenant_id=tenant_id,
                )
            return

        # Find candidate decoders from DB
        with SessionLocal() as db:
            active_decoders = (
                db.query(DecoderDefinition)
                .filter(DecoderDefinition.status == "active")
                .all()
            )
            candidates = []
            for d in active_decoders:
                v = (
                    db.query(DecoderVersion)
                    .filter(DecoderVersion.id == d.active_version_id)
                    .first()
                )
                if v:
                    candidates.append({
                        "id": d.id,
                        "name": d.name,
                        "code": v.code,
                        "match": v.matching or {},
                        "version": v.version,
                    })

        best = select_best_decoder(candidates, context)
        if not best:
            # If payload is JSON, no custom byte decoder is required!
            # Directly assign incoming JSON variables.
            if detected_fmt == "json" and context.get("json"):
                success = True
                result = context["json"]
                logs = ["Direct variable assignment for incoming JSON payload"]
                err = None
            else:
                now_utc = datetime.now(timezone.utc)
                with SessionLocal() as db:
                    sinks.store_message(
                        db=db,
                        message_id=message_id,
                        received_at=now_utc,
                        device_id=device_id,
                        transport=transport,
                        status="failed",
                        body={
                            "error": "No matching active decoder found for context",
                            "payloadHex": hex_str,
                            "context": context,
                            "receivedAt": now_utc.isoformat(),
                            "received_at": now_utc.isoformat(),
                        },
                        tenant_id=tenant_id,
                    )
                return
        else:
            # Execute matching decoder
            success, result, logs, err = decoder_executor.execute(
                code=best["code"],
                raw_bytes=raw_bytes,
                hex_str=hex_str,
                context=context,
            )

        effective_dev_id = device_id
        decoded_output = result
        provisioned_device = None

        if success and isinstance(result, dict):
            dev_meta, clean_data, units = extract_device_keywords(
                decoded=result,
                context=context,
                default_device_id=device_id,
            )
            final_id = dev_meta.get("device_id") or device_id
            if final_id:
                effective_dev_id = final_id
                try:
                    with SessionLocal() as db:
                        provisioned_device = ensure_device_registered(
                            db=db,
                            device_id=final_id,
                            device_type=dev_meta.get("device_type") or "NTN",
                            tenant_id=dev_meta.get("tenant_id") or tenant_id,
                            application_id=dev_meta.get("application_id"),
                            application_name=dev_meta.get("application_name"),
                            decoder_id=best.get("id") if best else None,
                            decoder_name=best.get("name") if best else None,
                            name=dev_meta.get("name"),
                            credentials=dev_meta.get("credentials"),
                        )
                        if provisioned_device and not tenant_id:
                            tenant_id = provisioned_device.get("tenant_id")
                except Exception as e:
                    logger.warning(f"Failed to auto-provision device from decoder keywords: {e}")

            if "data" in result or units:
                decoded_output = {"data": clean_data, "units": units or {}}
            else:
                decoded_output = clean_data

        with SessionLocal() as db:
            now_utc = datetime.now(timezone.utc)
            status = "decoded" if success else "failed"
            body = {
                "messageId": message_id,
                "deviceId": effective_dev_id,
                "transport": transport,
                "payloadHex": hex_str,
                "decoder": {"id": best["id"], "name": best["name"], "version": best["version"]},
                "decoded": decoded_output if success else None,
                "device": provisioned_device,
                "logs": logs,
                "error": err if not success else None,
                "receivedAt": now_utc.isoformat(),
                "received_at": now_utc.isoformat(),
            }
            sinks.store_message(
                db=db,
                message_id=message_id,
                received_at=now_utc,
                device_id=effective_dev_id,
                transport=transport,
                status=status,
                body=body,
                tenant_id=tenant_id,
            )
            sinks.log_console(message_id, status, effective_dev_id, decoded_output if success else err)


queue_worker = MessageQueueWorker()
