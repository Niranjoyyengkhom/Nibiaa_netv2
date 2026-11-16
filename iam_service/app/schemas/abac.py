from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field


PolicyEffect = Literal["ALLOW", "DENY"]


class ABACPolicyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: Optional[str] = None
    tenant_id: Optional[int] = None
    effect: PolicyEffect = Field(default="ALLOW")
    priority: int = Field(default=0)
    target_actions: List[str] = Field(default_factory=lambda: ["*"])
    target_resource_types: List[str] = Field(default_factory=lambda: ["*"])
    subject_conditions: Optional[Dict[str, Any]] = Field(default_factory=dict)
    resource_conditions: Optional[Dict[str, Any]] = Field(default_factory=dict)
    environment_conditions: Optional[Dict[str, Any]] = Field(default_factory=dict)
    is_active: bool = True


class ABACPolicyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    effect: Optional[PolicyEffect] = None
    priority: Optional[int] = None
    target_actions: Optional[List[str]] = None
    target_resource_types: Optional[List[str]] = None
    subject_conditions: Optional[Dict[str, Any]] = None
    resource_conditions: Optional[Dict[str, Any]] = None
    environment_conditions: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class ABACPolicyResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    tenant_id: Optional[int] = None
    effect: str
    priority: int
    target_actions: List[str]
    target_resource_types: List[str]
    subject_conditions: Optional[Dict[str, Any]] = None
    resource_conditions: Optional[Dict[str, Any]] = None
    environment_conditions: Optional[Dict[str, Any]] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ABACEvaluateRequest(BaseModel):
    user_id: Optional[int] = None
    username: Optional[str] = None
    action: str = Field(description="e.g. devices:command, telemetry:read")
    resource_type: str = Field(description="e.g. device, application, telemetry")
    resource_id: Optional[str] = None
    resource_attributes: Optional[Dict[str, Any]] = Field(default_factory=dict)
    context_attributes: Optional[Dict[str, Any]] = Field(default_factory=dict)


class ABACEvaluateResponse(BaseModel):
    allowed: bool
    effect: str
    matched_policies: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    evaluation_time_ms: float
    user_attributes: Dict[str, Any] = Field(default_factory=dict)
    effective_permissions: List[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}
