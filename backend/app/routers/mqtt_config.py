from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.mqtt_broker_config import MqttBrokerConfig
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.mqtt_config import (
    MqttBrokerConfigCreate,
    MqttBrokerConfigResponse,
    MqttBrokerConfigUpdate,
    MqttTestRequest,
    MqttTestResponse,
)
from app.services import mqtt_publisher

router = APIRouter(
    prefix="/mqtt",
    tags=["MQTT Integration"]
)


def resolve_tenant_id(current_user: User, db: Session) -> int:
    """
    Resolves the active tenant ID for the current user.
    """
    if current_user.tenant_id:
        return current_user.tenant_id

    # Fallback to the first active tenant for platform admins
    tenant = db.query(Tenant).filter(Tenant.is_active == True).order_by(Tenant.id.asc()).first()
    if tenant:
        return tenant.id
    return 1


@router.get(
    "/config",
    response_model=MqttBrokerConfigResponse,
    summary="Get MQTT broker configuration",
    description="Returns the MQTT broker configuration for the current organization."
)
def get_mqtt_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = resolve_tenant_id(current_user, db)
    config = (
        db.query(MqttBrokerConfig)
        .filter(MqttBrokerConfig.tenant_id == tenant_id)
        .first()
    )

    if config is None:
        # Return default unconfigured state
        return MqttBrokerConfigResponse(
            tenant_id=tenant_id,
            name="My MQTT Broker",
            enabled=False,
            host="",
            port=1883,
            client_id=None,
            username=None,
            has_password=False,
            topic_prefix=f"nibiaanet/tenants/{tenant_id}/devices/{{device_id}}/telemetry",
            qos=1,
            use_tls=False,
        )

    return MqttBrokerConfigResponse(
        id=config.id,
        tenant_id=config.tenant_id,
        name=config.name,
        enabled=config.enabled,
        host=config.host,
        port=config.port,
        client_id=config.client_id,
        username=config.username,
        has_password=bool(config.password),
        topic_prefix=config.topic_prefix,
        qos=config.qos,
        use_tls=config.use_tls,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.post(
    "/config",
    response_model=MqttBrokerConfigResponse,
    summary="Save MQTT broker configuration",
    description="Configures custom MQTT broker credentials for the current organization."
)
def save_mqtt_config(
    data: MqttBrokerConfigCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = resolve_tenant_id(current_user, db)

    config = (
        db.query(MqttBrokerConfig)
        .filter(MqttBrokerConfig.tenant_id == tenant_id)
        .first()
    )

    if config is None:
        config = MqttBrokerConfig(
            tenant_id=tenant_id,
            name=data.name.strip(),
            enabled=data.enabled,
            host=data.host.strip(),
            port=data.port,
            client_id=data.client_id.strip() if data.client_id else None,
            username=data.username.strip() if data.username else None,
            password=data.password if data.password else None,
            topic_prefix=data.topic_prefix.strip(),
            qos=data.qos,
            use_tls=data.use_tls,
        )
        db.add(config)
    else:
        config.name = data.name.strip()
        config.enabled = data.enabled
        config.host = data.host.strip()
        config.port = data.port
        config.client_id = data.client_id.strip() if data.client_id else None
        config.username = data.username.strip() if data.username else None
        if data.password is not None and data.password.strip() != "":
            config.password = data.password
        config.topic_prefix = data.topic_prefix.strip()
        config.qos = data.qos
        config.use_tls = data.use_tls

    db.commit()
    db.refresh(config)

    return MqttBrokerConfigResponse(
        id=config.id,
        tenant_id=config.tenant_id,
        name=config.name,
        enabled=config.enabled,
        host=config.host,
        port=config.port,
        client_id=config.client_id,
        username=config.username,
        has_password=bool(config.password),
        topic_prefix=config.topic_prefix,
        qos=config.qos,
        use_tls=config.use_tls,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.delete(
    "/config",
    summary="Delete/Disable MQTT broker configuration",
    description="Deletes the custom MQTT broker configuration for the current organization."
)
def delete_mqtt_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = resolve_tenant_id(current_user, db)
    config = (
        db.query(MqttBrokerConfig)
        .filter(MqttBrokerConfig.tenant_id == tenant_id)
        .first()
    )

    if config:
        db.delete(config)
        db.commit()

    return {"success": True, "message": "MQTT broker configuration removed."}


@router.post(
    "/test",
    response_model=MqttTestResponse,
    summary="Test connection to MQTT broker",
    description="Attempts to connect and publish a test ping message to the specified broker."
)
def test_mqtt_config(
    data: MqttTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    password = data.password
    # If password is omitted but username matches saved config, load saved password
    if not password and data.username:
        tenant_id = resolve_tenant_id(current_user, db)
        saved = (
            db.query(MqttBrokerConfig)
            .filter(MqttBrokerConfig.tenant_id == tenant_id)
            .first()
        )
        if saved and saved.username == data.username:
            password = saved.password

    success, message = mqtt_publisher.test_connection(
        host=data.host,
        port=data.port,
        username=data.username,
        password=password,
        client_id=data.client_id,
        use_tls=data.use_tls,
        topic=data.topic or "nibiaanet/test/ping",
    )

    return MqttTestResponse(success=success, message=message)
