from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.abac_policy import ABACPolicy
from app.models.user import User
from app.schemas.abac import (
    ABACPolicyCreate,
    ABACPolicyUpdate,
    ABACPolicyResponse,
    ABACEvaluateRequest,
    ABACEvaluateResponse,
)
from app.services.abac_engine import abac_engine
from app.services.audit_service import audit_service
from app.dependencies.auth import get_current_user, get_optional_user

router = APIRouter(prefix="/abac", tags=["ABAC Policy Engine & Decision Point (PDP)"])


# ----------------------------------------------------
# Policy Management
# ----------------------------------------------------

@router.get("/policies", response_model=List[ABACPolicyResponse])
def get_policies(
    tenant_id: Optional[int] = Query(None, description="Filter by tenant ID"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    query = db.query(ABACPolicy)
    if current_user and current_user.role != "admin":
        tenant_id = current_user.tenant_id
        query = query.filter((ABACPolicy.tenant_id == tenant_id) | (ABACPolicy.tenant_id.is_(None)))
    elif tenant_id is not None:
        query = query.filter(ABACPolicy.tenant_id == tenant_id)

    if is_active is not None:
        query = query.filter(ABACPolicy.is_active.is_(is_active))

    return query.order_by(ABACPolicy.priority.desc(), ABACPolicy.name.asc()).all()


@router.get("/policies/{policy_id}", response_model=ABACPolicyResponse)
def get_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    item = db.query(ABACPolicy).filter(ABACPolicy.id == policy_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Policy not found")
    if current_user and current_user.role != "admin" and item.tenant_id and item.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Permission denied")
    return item


@router.post("/policies", response_model=ABACPolicyResponse)
def create_policy(
    data: ABACPolicyCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    if current_user and current_user.role != "admin":
        data.tenant_id = current_user.tenant_id

    existing = db.query(ABACPolicy).filter(ABACPolicy.name == data.name.strip()).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Policy '{data.name}' already exists")

    new_policy = ABACPolicy(
        name=data.name.strip(),
        description=data.description,
        tenant_id=data.tenant_id,
        effect=data.effect,
        priority=data.priority,
        target_actions=data.target_actions,
        target_resource_types=data.target_resource_types,
        subject_conditions=data.subject_conditions or {},
        resource_conditions=data.resource_conditions or {},
        environment_conditions=data.environment_conditions or {},
        is_active=data.is_active,
    )
    db.add(new_policy)
    db.commit()
    db.refresh(new_policy)

    audit_service.log(
        db,
        action="POLICY_CREATED",
        target_type="policy",
        target_id=str(new_policy.id),
        actor_id=current_user.id if current_user else None,
        actor_name=current_user.name if current_user else "system",
        tenant_id=new_policy.tenant_id,
        details={"name": new_policy.name, "effect": new_policy.effect},
    )

    return new_policy


@router.put("/policies/{policy_id}", response_model=ABACPolicyResponse)
def update_policy(
    policy_id: int,
    data: ABACPolicyUpdate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    item = db.query(ABACPolicy).filter(ABACPolicy.id == policy_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Policy not found")
    if current_user and current_user.role != "admin" and item.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    if data.name:
        item.name = data.name.strip()
    if data.description is not None:
        item.description = data.description
    if data.effect is not None:
        item.effect = data.effect
    if data.priority is not None:
        item.priority = data.priority
    if data.target_actions is not None:
        item.target_actions = data.target_actions
    if data.target_resource_types is not None:
        item.target_resource_types = data.target_resource_types
    if data.subject_conditions is not None:
        item.subject_conditions = data.subject_conditions
    if data.resource_conditions is not None:
        item.resource_conditions = data.resource_conditions
    if data.environment_conditions is not None:
        item.environment_conditions = data.environment_conditions
    if data.is_active is not None:
        item.is_active = data.is_active

    db.commit()
    db.refresh(item)

    audit_service.log(
        db,
        action="POLICY_UPDATED",
        target_type="policy",
        target_id=str(item.id),
        actor_id=current_user.id if current_user else None,
        actor_name=current_user.name if current_user else "system",
        tenant_id=item.tenant_id,
        details={"name": item.name},
    )

    return item


@router.delete("/policies/{policy_id}")
def delete_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    item = db.query(ABACPolicy).filter(ABACPolicy.id == policy_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Policy not found")
    if current_user and current_user.role != "admin" and item.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    name = item.name
    db.delete(item)
    db.commit()

    audit_service.log(
        db,
        action="POLICY_DELETED",
        target_type="policy",
        target_id=str(policy_id),
        actor_id=current_user.id if current_user else None,
        actor_name=current_user.name if current_user else "system",
        details={"name": name},
    )

    return {"message": f"Policy '{name}' deleted successfully"}


# ----------------------------------------------------
# Policy Decision Point (PDP Evaluation)
# ----------------------------------------------------

@router.post("/evaluate", response_model=ABACEvaluateResponse)
def evaluate_policy_decision(
    data: ABACEvaluateRequest,
    db: Session = Depends(get_db),
):
    """
    Evaluates whether a subject is authorized to execute an action on a target resource.
    Does not require bearer token so other services can call directly via service mesh.
    """
    decision = abac_engine.evaluate(
        db=db,
        action=data.action,
        resource_type=data.resource_type,
        user_id=data.user_id,
        username=data.username,
        resource_id=data.resource_id,
        resource_attributes=data.resource_attributes,
        context_attributes=data.context_attributes,
    )
    return decision


@router.post("/authorize", response_model=ABACEvaluateResponse)
def authorize_alias(
    data: ABACEvaluateRequest,
    db: Session = Depends(get_db),
):
    """Alias for /evaluate for standard authorization gateways."""
    return evaluate_policy_decision(data, db)
