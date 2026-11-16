from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field


EntityType = Literal["user", "role", "resource", "tenant", "environment"]
DataType = Literal["string", "number", "boolean", "json", "enum", "list"]


class AttributeDefinitionCreate(BaseModel):
    key: str = Field(min_length=2, max_length=100, pattern=r"^[a-zA-Z0-9_\-\.]+$")
    name: str = Field(min_length=2, max_length=150)
    description: Optional[str] = None
    entity_type: EntityType = Field(default="user")
    data_type: DataType = Field(default="string")
    allowed_values: Optional[List[Any]] = None
    validation_regex: Optional[str] = None
    default_value: Optional[str] = None
    is_required: bool = False
    tenant_id: Optional[int] = None


class AttributeDefinitionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    allowed_values: Optional[List[Any]] = None
    validation_regex: Optional[str] = None
    default_value: Optional[str] = None
    is_required: Optional[bool] = None


class AttributeDefinitionResponse(BaseModel):
    id: int
    key: str
    name: str
    description: Optional[str] = None
    entity_type: str
    data_type: str
    allowed_values: Optional[List[Any]] = None
    validation_regex: Optional[str] = None
    default_value: Optional[str] = None
    is_required: bool = False
    is_system: bool = False
    tenant_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AttributeValueAssign(BaseModel):
    key: str
    value: Any


class BatchAttributeAssign(BaseModel):
    attributes: Dict[str, Any]
    tenant_id: Optional[int] = None


class AttributeValueResponse(BaseModel):
    id: int
    attribute_def_id: int
    key: str
    name: str
    entity_type: str
    entity_id: str
    data_type: str
    value: Any
    updated_at: datetime

    model_config = {"from_attributes": True}


class EntityAttributesResponse(BaseModel):
    entity_type: str
    entity_id: str
    attributes: Dict[str, Any]

    model_config = {"from_attributes": True}
