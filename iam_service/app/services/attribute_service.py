import re
import json
import logging
from typing import Optional, Dict, Any, List
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.attribute import AttributeDefinition, AttributeValue
from app.schemas.attribute import (
    AttributeDefinitionCreate,
    AttributeDefinitionUpdate,
)

logger = logging.getLogger("nibiaanet.iam.attributes")


class AttributeService:
    # ----------------------------------------------------
    # Attribute Definitions (Schema Catalog)
    # ----------------------------------------------------

    def get_definitions(
        self,
        db: Session,
        entity_type: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> List[AttributeDefinition]:
        query = db.query(AttributeDefinition)
        if entity_type:
            query = query.filter(AttributeDefinition.entity_type == entity_type)
        if tenant_id is not None:
            query = query.filter(
                (AttributeDefinition.tenant_id == tenant_id) | (AttributeDefinition.tenant_id.is_(None))
            )
        return query.order_by(AttributeDefinition.entity_type, AttributeDefinition.name).all()

    def get_definition(self, db: Session, def_id: int) -> AttributeDefinition:
        item = db.query(AttributeDefinition).filter(AttributeDefinition.id == def_id).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"Attribute definition #{def_id} not found")
        return item

    def get_definition_by_key(
        self,
        db: Session,
        entity_type: str,
        key: str,
        tenant_id: Optional[int] = None,
    ) -> Optional[AttributeDefinition]:
        query = db.query(AttributeDefinition).filter(
            AttributeDefinition.entity_type == entity_type,
            func.lower(AttributeDefinition.key) == key.lower().strip()
        )
        if tenant_id is not None:
            query = query.filter(
                (AttributeDefinition.tenant_id == tenant_id) | (AttributeDefinition.tenant_id.is_(None))
            )
        return query.order_by(AttributeDefinition.tenant_id.desc().nullslast()).first()

    def create_definition(
        self,
        db: Session,
        data: AttributeDefinitionCreate,
    ) -> AttributeDefinition:
        existing = (
            db.query(AttributeDefinition)
            .filter(
                AttributeDefinition.entity_type == data.entity_type,
                func.lower(AttributeDefinition.key) == data.key.lower().strip(),
                AttributeDefinition.tenant_id == data.tenant_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Attribute '{data.key}' already exists for entity type '{data.entity_type}'"
            )

        if data.data_type == "enum" and not data.allowed_values:
            raise HTTPException(
                status_code=400,
                detail="Attribute with data_type 'enum' must provide 'allowed_values' list"
            )

        new_def = AttributeDefinition(
            key=data.key.strip(),
            name=data.name.strip(),
            description=data.description,
            entity_type=data.entity_type,
            data_type=data.data_type,
            allowed_values=data.allowed_values,
            validation_regex=data.validation_regex,
            default_value=data.default_value,
            is_required=data.is_required,
            is_system=False,
            tenant_id=data.tenant_id,
        )
        db.add(new_def)
        db.commit()
        db.refresh(new_def)
        return new_def

    def update_definition(
        self,
        db: Session,
        def_id: int,
        data: AttributeDefinitionUpdate,
    ) -> AttributeDefinition:
        item = self.get_definition(db, def_id)
        if item.is_system:
            # System definitions cannot change allowed values arbitrarily if critical
            pass

        if data.name is not None:
            item.name = data.name.strip()
        if data.description is not None:
            item.description = data.description
        if data.allowed_values is not None:
            item.allowed_values = data.allowed_values
        if data.validation_regex is not None:
            item.validation_regex = data.validation_regex
        if data.default_value is not None:
            item.default_value = data.default_value
        if data.is_required is not None:
            item.is_required = data.is_required

        db.commit()
        db.refresh(item)
        return item

    def delete_definition(self, db: Session, def_id: int) -> dict:
        item = self.get_definition(db, def_id)
        if item.is_system:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete built-in system attribute definition '{item.key}'"
            )
        db.delete(item)
        db.commit()
        return {"message": f"Attribute definition '{item.key}' deleted successfully"}

    # ----------------------------------------------------
    # Attribute Values (Entity Assignments)
    # ----------------------------------------------------

    def validate_value(self, definition: AttributeDefinition, value: Any) -> Any:
        """Validates incoming value against definition data type and constraints."""
        if value is None:
            if definition.is_required:
                raise HTTPException(status_code=400, detail=f"Attribute '{definition.key}' is required")
            return None

        # Enum check
        if definition.data_type == "enum":
            allowed = definition.allowed_values or []
            if value not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=f"Value '{value}' is invalid for enum attribute '{definition.key}'. Allowed: {allowed}"
                )
            return str(value)

        # Number check
        if definition.data_type == "number":
            try:
                num = float(value)
                return num
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail=f"Value for '{definition.key}' must be numeric"
                )

        # Boolean check
        if definition.data_type == "boolean":
            if isinstance(value, bool):
                return value
            if str(value).lower() in ("true", "1", "yes"):
                return True
            if str(value).lower() in ("false", "0", "no"):
                return False
            raise HTTPException(
                status_code=400,
                detail=f"Value for '{definition.key}' must be boolean"
            )

        # JSON / List check
        if definition.data_type in ("json", "list"):
            if isinstance(value, (dict, list)):
                return value
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except Exception:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Value for '{definition.key}' must be valid JSON"
                    )

        # String check
        val_str = str(value)
        if definition.validation_regex:
            if not re.search(definition.validation_regex, val_str):
                raise HTTPException(
                    status_code=400,
                    detail=f"Value '{val_str}' fails regex validation '{definition.validation_regex}'"
                )
        return val_str

    def get_entity_attributes(
        self,
        db: Session,
        entity_type: str,
        entity_id: str | int,
    ) -> Dict[str, Any]:
        """Returns clean dictionary of all resolved attributes {key: value} for an entity."""
        ent_id = str(entity_id)
        values = (
            db.query(AttributeValue)
            .join(AttributeDefinition, AttributeValue.attribute_def_id == AttributeDefinition.id)
            .filter(
                AttributeValue.entity_type == entity_type,
                AttributeValue.entity_id == ent_id,
            )
            .all()
        )
        result = {}
        for row in values:
            result[row.definition.key] = row.value
        return result

    def get_entity_attribute_details(
        self,
        db: Session,
        entity_type: str,
        entity_id: str | int,
    ) -> List[dict]:
        """Returns detailed attribute records with metadata for an entity."""
        ent_id = str(entity_id)
        values = (
            db.query(AttributeValue)
            .join(AttributeDefinition, AttributeValue.attribute_def_id == AttributeDefinition.id)
            .filter(
                AttributeValue.entity_type == entity_type,
                AttributeValue.entity_id == ent_id,
            )
            .all()
        )
        details = []
        for row in values:
            details.append({
                "id": row.id,
                "attribute_def_id": row.attribute_def_id,
                "key": row.definition.key,
                "name": row.definition.name,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "data_type": row.definition.data_type,
                "value": row.value,
                "updated_at": row.updated_at,
            })
        return details

    def set_entity_attribute(
        self,
        db: Session,
        entity_type: str,
        entity_id: str | int,
        key: str,
        raw_value: Any,
        tenant_id: Optional[int] = None,
    ) -> AttributeValue:
        ent_id = str(entity_id)
        definition = self.get_definition_by_key(db, entity_type, key, tenant_id)
        if not definition:
            # Auto-create string attribute definition if not found
            definition = self.create_definition(
                db,
                AttributeDefinitionCreate(
                    key=key,
                    name=key.replace("_", " ").title(),
                    entity_type=entity_type,
                    data_type="string" if not isinstance(raw_value, (int, float, bool, dict, list)) else (
                        "number" if isinstance(raw_value, (int, float)) else (
                            "boolean" if isinstance(raw_value, bool) else "json"
                        )
                    ),
                    tenant_id=tenant_id,
                )
            )

        validated = self.validate_value(definition, raw_value)

        attr_val = (
            db.query(AttributeValue)
            .filter(
                AttributeValue.attribute_def_id == definition.id,
                AttributeValue.entity_type == entity_type,
                AttributeValue.entity_id == ent_id,
            )
            .first()
        )

        if not attr_val:
            attr_val = AttributeValue(
                attribute_def_id=definition.id,
                entity_type=entity_type,
                entity_id=ent_id,
                tenant_id=tenant_id,
            )
            db.add(attr_val)

        # Clear existing types
        attr_val.value_string = None
        attr_val.value_number = None
        attr_val.value_boolean = None
        attr_val.value_json = None

        if definition.data_type == "number":
            attr_val.value_number = float(validated) if validated is not None else None
        elif definition.data_type == "boolean":
            attr_val.value_boolean = bool(validated) if validated is not None else None
        elif definition.data_type in ("json", "list"):
            attr_val.value_json = validated
        else:
            attr_val.value_string = str(validated) if validated is not None else None

        db.commit()
        db.refresh(attr_val)
        return attr_val

    def batch_set_entity_attributes(
        self,
        db: Session,
        entity_type: str,
        entity_id: str | int,
        attributes: Dict[str, Any],
        tenant_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        for k, v in attributes.items():
            self.set_entity_attribute(db, entity_type, entity_id, k, v, tenant_id)
        return self.get_entity_attributes(db, entity_type, entity_id)

    def delete_entity_attribute(
        self,
        db: Session,
        entity_type: str,
        entity_id: str | int,
        key: str,
    ) -> dict:
        ent_id = str(entity_id)
        definition = self.get_definition_by_key(db, entity_type, key)
        if not definition:
            raise HTTPException(status_code=404, detail=f"Attribute '{key}' not found")

        val = (
            db.query(AttributeValue)
            .filter(
                AttributeValue.attribute_def_id == definition.id,
                AttributeValue.entity_type == entity_type,
                AttributeValue.entity_id == ent_id,
            )
            .first()
        )
        if val:
            db.delete(val)
            db.commit()
        return {"message": f"Attribute '{key}' deleted from {entity_type} {entity_id}"}


attribute_service = AttributeService()
