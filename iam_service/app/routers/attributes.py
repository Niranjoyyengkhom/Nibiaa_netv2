from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.attribute import (
    AttributeDefinitionCreate,
    AttributeDefinitionUpdate,
    AttributeDefinitionResponse,
    AttributeValueAssign,
    BatchAttributeAssign,
    AttributeValueResponse,
    EntityAttributesResponse,
)
from app.services.attribute_service import attribute_service
from app.dependencies.auth import get_optional_user, get_current_user

router = APIRouter(prefix="/attributes", tags=["Attribute Management & EAV Store"])


# ----------------------------------------------------
# Schema Definitions
# ----------------------------------------------------

@router.get("/definitions", response_model=List[AttributeDefinitionResponse])
def get_attribute_definitions(
    entity_type: Optional[str] = Query(None, description="user, role, resource, tenant, environment"),
    tenant_id: Optional[int] = Query(None, description="Filter by tenant ID"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    if current_user and current_user.role != "admin":
        tenant_id = current_user.tenant_id
    return attribute_service.get_definitions(db, entity_type=entity_type, tenant_id=tenant_id)


@router.get("/definitions/{def_id}", response_model=AttributeDefinitionResponse)
def get_attribute_definition(
    def_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    return attribute_service.get_definition(db, def_id)


@router.post("/definitions", response_model=AttributeDefinitionResponse)
def create_attribute_definition(
    data: AttributeDefinitionCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    if current_user and current_user.role != "admin":
        data.tenant_id = current_user.tenant_id
    return attribute_service.create_definition(db, data)


@router.put("/definitions/{def_id}", response_model=AttributeDefinitionResponse)
def update_attribute_definition(
    def_id: int,
    data: AttributeDefinitionUpdate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    item = attribute_service.get_definition(db, def_id)
    if current_user and current_user.role != "admin" and item.tenant_id != current_user.tenant_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Permission denied")
    return attribute_service.update_definition(db, def_id, data)


@router.delete("/definitions/{def_id}")
def delete_attribute_definition(
    def_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    item = attribute_service.get_definition(db, def_id)
    if current_user and current_user.role != "admin" and item.tenant_id != current_user.tenant_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Permission denied")
    return attribute_service.delete_definition(db, def_id)


# ----------------------------------------------------
# Entity Attribute Values
# ----------------------------------------------------

@router.get("/entities/{entity_type}/{entity_id}", response_model=EntityAttributesResponse)
def get_entity_attributes(
    entity_type: str,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    attrs = attribute_service.get_entity_attributes(db, entity_type, entity_id)
    return {
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "attributes": attrs,
    }


@router.get("/entities/{entity_type}/{entity_id}/details", response_model=List[AttributeValueResponse])
def get_entity_attribute_details(
    entity_type: str,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    return attribute_service.get_entity_attribute_details(db, entity_type, entity_id)


@router.put("/entities/{entity_type}/{entity_id}", response_model=EntityAttributesResponse)
def batch_set_entity_attributes(
    entity_type: str,
    entity_id: str,
    data: BatchAttributeAssign,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    tenant_id = data.tenant_id or (current_user.tenant_id if current_user else None)
    updated = attribute_service.batch_set_entity_attributes(
        db, entity_type, entity_id, data.attributes, tenant_id=tenant_id
    )
    return {
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "attributes": updated,
    }


@router.post("/entities/{entity_type}/{entity_id}")
def set_single_entity_attribute(
    entity_type: str,
    entity_id: str,
    data: AttributeValueAssign,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    tenant_id = current_user.tenant_id if current_user else None
    val = attribute_service.set_entity_attribute(
        db, entity_type, entity_id, data.key, data.value, tenant_id=tenant_id
    )
    return {
        "key": data.key,
        "value": val.value,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "updated_at": val.updated_at,
    }


@router.delete("/entities/{entity_type}/{entity_id}/{key}")
def delete_entity_attribute(
    entity_type: str,
    entity_id: str,
    key: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    return attribute_service.delete_entity_attribute(db, entity_type, entity_id, key)
