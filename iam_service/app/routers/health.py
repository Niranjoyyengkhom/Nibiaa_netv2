from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.models.user import User
from app.models.role import Role
from app.models.attribute import AttributeDefinition, AttributeValue
from app.models.abac_policy import ABACPolicy

router = APIRouter(tags=["Health & Diagnostics"])


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    db_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {e}"

    return {
        "status": "ok" if "error" not in db_status else "degraded",
        "service": "nibiaanet-iam-service",
        "version": "1.0.0",
        "database": db_status,
    }


@router.get("/info")
def service_info():
    return {
        "service": "NibiaaNet IAM & ABAC Microservice",
        "description": "Enterprise User, Role-Based Access Control, Dynamic Attribute Management, and Policy Decision Point",
        "version": "1.0.0",
        "capabilities": [
            "User Lifecycle & Credential Security",
            "Hierarchical RBAC & Granular Permissions",
            "Dynamic EAV Attribute Catalog (User, Resource, Tenant, Environment)",
            "NIST-compliant ABAC Policy Decision Point (PDP)",
            "Token Introspection for Distributed Microservices",
            "Granular Security Audit Logging",
        ],
    }


@router.get("/stats")
def service_stats(db: Session = Depends(get_db)):
    return {
        "total_users": db.query(User).count(),
        "active_users": db.query(User).filter(User.is_active.is_(True)).count(),
        "total_roles": db.query(Role).count(),
        "attribute_definitions": db.query(AttributeDefinition).count(),
        "assigned_attribute_values": db.query(AttributeValue).count(),
        "active_abac_policies": db.query(ABACPolicy).filter(ABACPolicy.is_active.is_(True)).count(),
    }
