from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.models.webhook import WebhookDeliveryStatus
from app.schemas.webhook import (
    WebhookCreate,
    WebhookCreatedResponse,
    WebhookDeliveryResponse,
    WebhookResponse,
    WebhookUpdate,
)
from app.services.webhook_service import WebhookService


router = APIRouter(
    prefix="/webhooks",
    tags=["Webhooks"]
)

webhook_service = WebhookService()


@router.post(
    "/",
    response_model=WebhookCreatedResponse,
    summary="Register a webhook",
    description=(
        "Telemetry of the tenant's devices is POSTed to url as JSON, "
        "signed with the returned secret (shown only once)."
    )
)
def create_webhook(
    data: WebhookCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return webhook_service.create_webhook(db, data, current_user)


@router.get(
    "/",
    response_model=list[WebhookResponse]
)
def get_webhooks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return webhook_service.get_webhooks(db, current_user)


# Declared before /{webhook_id}
@router.get(
    "/alerts",
    response_model=list[WebhookDeliveryResponse],
    summary="Undeliverable deliveries",
    description="Deliveries that failed every attempt, newest first."
)
def get_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return webhook_service.get_alerts(db, current_user)


@router.post(
    "/deliveries/retry-due",
    summary="Retry due deliveries now",
    description="What app/delivery_worker.py does periodically. Admin only."
)
def retry_due(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    return {"attempted": webhook_service.retry_due(db)}


@router.post(
    "/deliveries/{delivery_id}/redeliver",
    response_model=WebhookDeliveryResponse
)
def redeliver(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return webhook_service.redeliver(db, delivery_id, current_user)


@router.get(
    "/{webhook_id}",
    response_model=WebhookResponse
)
def get_webhook(
    webhook_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return webhook_service.get_webhook(db, webhook_id, current_user)


@router.patch(
    "/{webhook_id}",
    response_model=WebhookResponse
)
def update_webhook(
    webhook_id: int,
    data: WebhookUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return webhook_service.update_webhook(db, webhook_id, data, current_user)


@router.delete(
    "/{webhook_id}",
    status_code=204
)
def delete_webhook(
    webhook_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    webhook_service.delete_webhook(db, webhook_id, current_user)


@router.get(
    "/{webhook_id}/deliveries",
    response_model=list[WebhookDeliveryResponse]
)
def get_deliveries(
    webhook_id: int,
    status: WebhookDeliveryStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return webhook_service.get_deliveries(db, webhook_id, status, current_user)
