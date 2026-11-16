import uuid
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.message import DecodedMessageRecord
from app.schemas.message import MessageIngestRequest, MessageItemResponse, MessageListResponse, DeviceRegisterRequest
from app.services.queue import queue_worker
from app.services.device_registry import ensure_device_registered

router = APIRouter(prefix="/messages", tags=["Messages"])


@router.post("", status_code=202)
@router.post("/", status_code=202)
async def ingest_message(req: MessageIngestRequest):
    message_id = str(uuid.uuid4())
    msg_dict = {
        "messageId": message_id,
        "deviceId": req.deviceId,
        "payload": req.payload,
        "format": req.format or "auto",
        "transport": req.transport or "http",
        "context": req.context or {},
        "tenantId": req.tenantId,
    }
    await queue_worker.enqueue(msg_dict)
    return {
        "success": True,
        "messageId": message_id,
        "status": "enqueued",
    }


@router.post("/register-device")
def register_device_via_decoder(req: DeviceRegisterRequest, db: Session = Depends(get_db)):
    try:
        device = ensure_device_registered(
            db=db,
            device_id=req.deviceId,
            device_type=req.deviceType or "NTN",
            tenant_id=req.tenantId,
            application_id=req.applicationId,
            application_name=req.application or req.appName,
            name=req.name,
            credentials=req.credentials,
        )
        return {
            "success": True,
            "message": f"Device '{req.deviceId}' successfully registered by decoder.",
            "device": device,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))



@router.get("/", response_model=MessageListResponse)
def list_messages(
    deviceId: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    tenantId: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(DecodedMessageRecord)
    if deviceId:
        query = query.filter(DecodedMessageRecord.device_id == deviceId)
    if status:
        query = query.filter(DecodedMessageRecord.status == status)
    if tenantId:
        query = query.filter(DecodedMessageRecord.tenant_id == tenantId)

    total = query.count()
    records = query.order_by(DecodedMessageRecord.received_at.desc()).limit(limit).all()

    items = [
        MessageItemResponse(
            messageId=r.message_id,
            receivedAt=r.received_at,
            deviceId=r.device_id,
            transport=r.transport,
            status=r.status,
            body=r.body or {},
            tenantId=r.tenant_id,
        )
        for r in records
    ]

    return MessageListResponse(
        items=items,
        count=len(items),
        nextCursor=None,
    )


@router.get("/{message_id}", response_model=MessageItemResponse)
def get_message(message_id: str, db: Session = Depends(get_db)):
    record = (
        db.query(DecodedMessageRecord)
        .filter(DecodedMessageRecord.message_id == message_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Message not found")

    return MessageItemResponse(
        messageId=record.message_id,
        receivedAt=record.received_at,
        deviceId=record.device_id,
        transport=record.transport,
        status=record.status,
        body=record.body or {},
        tenantId=record.tenant_id,
    )
