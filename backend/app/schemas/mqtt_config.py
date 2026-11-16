from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class MqttBrokerConfigBase(BaseModel):
    name: str = "Default MQTT Broker"
    enabled: bool = True
    host: str = Field(..., description="MQTT Broker hostname or IP address, e.g. broker.emqx.io or 192.168.1.10")
    port: int = Field(default=1883, ge=1, le=65535, description="MQTT Broker port (1883 for plain, 8883 for TLS)")
    client_id: Optional[str] = Field(default=None, description="Optional custom MQTT Client ID")
    username: Optional[str] = Field(default=None, description="Optional MQTT username")
    password: Optional[str] = Field(default=None, description="Optional MQTT password")
    topic_prefix: str = Field(
        default="nibiaanet/tenants/{tenant_id}/devices/{device_id}/telemetry",
        description="MQTT topic template. Available placeholders: {tenant_id}, {device_id}"
    )
    qos: int = Field(default=1, ge=0, le=2, description="MQTT QoS level (0, 1, or 2)")
    use_tls: bool = Field(default=False, description="Enable TLS/SSL encryption for MQTT connection")


class MqttBrokerConfigCreate(MqttBrokerConfigBase):
    pass


class MqttBrokerConfigUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    host: Optional[str] = None
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    client_id: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    topic_prefix: Optional[str] = None
    qos: Optional[int] = Field(default=None, ge=0, le=2)
    use_tls: Optional[bool] = None


class MqttBrokerConfigResponse(BaseModel):
    id: Optional[int] = None
    tenant_id: int
    name: str = "Default MQTT Broker"
    enabled: bool = False
    host: str = ""
    port: int = 1883
    client_id: Optional[str] = None
    username: Optional[str] = None
    has_password: bool = False
    topic_prefix: str = "nibiaanet/tenants/{tenant_id}/devices/{device_id}/telemetry"
    qos: int = 1
    use_tls: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MqttTestRequest(BaseModel):
    host: str
    port: int = 1883
    client_id: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    topic: Optional[str] = "nibiaanet/test/ping"
    use_tls: bool = False


class MqttTestResponse(BaseModel):
    success: bool
    message: str
