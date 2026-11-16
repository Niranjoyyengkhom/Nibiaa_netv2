import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.schemas.run import RunDecoderRequest, RunDecoderResponse
from app.services.parser import parse_payload
from app.services.executor import decoder_executor
from app.services.device_keywords import extract_device_keywords
from app.services.templates import SAMPLE_TEMPLATES
from app.database import get_db

logger = logging.getLogger("nibiaanet.decoder.run")

router = APIRouter(tags=["Decoder Execution"])


@router.get("/decode/templates")
@router.get("/templates")
def get_decoder_templates():
    """
    Returns standard Python decoder templates for quick development and testing.
    """
    return {
        "success": True,
        "engine": "python_fastapi",
        "templates": SAMPLE_TEMPLATES,
    }


@router.post("/decode/run", response_model=RunDecoderResponse)
@router.post("/run", response_model=RunDecoderResponse)
def run_decoder(req: RunDecoderRequest, db: Session = Depends(get_db)):
    """
    Executes a dry-run decoder test.
    Isolated sandbox execution:
      - Does NOT create or alter devices in the database.
      - Does NOT publish data to MQTT brokers.
      - Does NOT forward data to Webhooks.
      - Does NOT store data to REST API telemetry endpoints.
    """
    if not req.code or not req.code.strip():
        raise HTTPException(
            status_code=400,
            detail="code must define function transform(input) or decode(input)"
        )

    if not req.payload:
        raise HTTPException(
            status_code=400,
            detail="payload is required (hex, base64, json or text)"
        )

    try:
        raw_bytes, hex_str, detected_format = parse_payload(req.payload, req.format or "auto")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse payload: {e}")

    context = dict(req.context or {})
    context["format"] = detected_format
    context["payloadFormat"] = detected_format
    if detected_format == "json":
        try:
            import json
            context["json"] = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            pass

    if req.deviceId:
        context["deviceId"] = req.deviceId

    # Execute code in isolated sandbox
    success, result, logs, error_msg = decoder_executor.execute(
        code=req.code,
        raw_bytes=raw_bytes,
        hex_str=hex_str,
        context=context,
    )

    data = None
    units = None
    output = None
    detected_metadata = None
    effective_dev_id = req.deviceId

    if success and isinstance(result, dict):
        dev_meta, clean_data, extracted_units = extract_device_keywords(
            decoded=result,
            context=context,
            default_device_id=req.deviceId,
        )
        data = clean_data
        units = extracted_units
        output = result
        detected_metadata = dev_meta
        effective_dev_id = dev_meta.get("device_id") or req.deviceId
    elif success:
        output = result
        data = {"value": result}

    # Build dry-run response payload (NO database write, NO MQTT, NO Webhook, NO REST API emission)
    message_payload = None
    failure_payload = None

    if success:
        message_payload = {
            "deviceId": effective_dev_id,
            "transport": "test_runner",
            "payloadHex": hex_str,
            "data": data or {},
            "units": units or {},
            "output": output,
            "logs": logs or [],
        }
    else:
        failure_payload = {
            "deviceId": effective_dev_id,
            "transport": "test_runner",
            "payloadHex": hex_str,
            "error": error_msg,
            "logs": logs or [],
        }

    return RunDecoderResponse(
        success=success,
        data=data,
        units=units,
        device=None,
        deviceProvisioned=False,
        detectedMetadata=detected_metadata,
        isTest=True,
        output=output,
        logs=logs or [],
        error=error_msg if not success else None,
        payloadHex=hex_str,
        detectedFormat=detected_format,
        message=message_payload,
        failure=failure_payload,
    )
