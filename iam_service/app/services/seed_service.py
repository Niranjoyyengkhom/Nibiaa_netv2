import logging
from sqlalchemy.orm import Session
from app.models.permission import Permission
from app.models.role import Role
from app.models.role_permission import RolePermission
from app.models.attribute import AttributeDefinition
from app.models.abac_policy import ABACPolicy
from app.models.user import User
from app.models.user_role import UserRole
from app.services.user_service import hash_password

logger = logging.getLogger("nibiaanet.iam.seed")

DEFAULT_PERMISSIONS = [
    # Devices
    ("devices:read", "View Devices", "View device registry and status", "devices"),
    ("devices:create", "Create Devices", "Register new devices in fleet", "devices"),
    ("devices:update", "Update Devices", "Modify device properties and metadata", "devices"),
    ("devices:delete", "Delete Devices", "Remove devices from registry", "devices"),
    ("devices:command", "Send Commands", "Queue and transmit downlink commands", "devices"),
    ("devices:configure", "Configure Devices", "Push firmware configuration parameters", "devices"),
    # Applications
    ("applications:read", "View Applications", "List and view applications", "applications"),
    ("applications:manage", "Manage Applications", "Create, edit, or configure applications", "applications"),
    # Decoders
    ("decoders:read", "View Decoders", "Inspect parser definitions and schemas", "decoders"),
    ("decoders:create", "Create Decoders", "Author new dynamic payload decoders", "decoders"),
    ("decoders:manage", "Manage Decoders", "Test, activate, or roll back decoders", "decoders"),
    # Telemetry
    ("telemetry:read", "Read Live Telemetry", "Stream and view real-time decoded IoT data", "telemetry"),
    ("telemetry:export", "Export Telemetry", "Export historical telemetry datasets", "telemetry"),
    # Users & IAM
    ("users:read", "View Users", "List team members and user profiles", "iam"),
    ("users:create", "Create Users", "Invite or create user accounts", "iam"),
    ("users:update", "Update Users", "Edit profile, email, or credentials", "iam"),
    ("users:delete", "Delete Users", "Remove user accounts", "iam"),
    ("users:revoke", "Revoke Users", "Temporarily revoke account access", "iam"),
    # Roles & ABAC
    ("roles:read", "View Roles", "View role catalog and permission sets", "iam"),
    ("roles:manage", "Manage Roles", "Create or edit roles and permission mappings", "iam"),
    ("attributes:read", "View Attributes", "Inspect dynamic attribute schemas and assignments", "iam"),
    ("attributes:manage", "Manage Attributes", "Define attribute schemas and assign values", "iam"),
    ("abac:evaluate", "Evaluate Policies", "Execute ABAC authorization engine decisions", "iam"),
    ("abac:manage", "Manage ABAC Policies", "Create and tune ABAC policy rules", "iam"),
    ("audit:read", "View Audit Trail", "Inspect IAM security audit logs", "iam"),
]

DEFAULT_ROLES = [
    {
        "name": "Administrator",
        "code": "ROLE_ADMIN",
        "description": "Full platform administration across all tenants and subsystems",
        "is_system": True,
        "permissions": ["*"],
    },
    {
        "name": "Organization Owner",
        "code": "ROLE_OWNER",
        "description": "Full control over organization workspace, devices, decoders, and members",
        "is_system": True,
        "permissions": [
            "devices:read", "devices:create", "devices:update", "devices:delete",
            "devices:command", "devices:configure", "applications:read", "applications:manage",
            "decoders:read", "decoders:create", "decoders:manage", "telemetry:read",
            "telemetry:export", "users:read", "users:create", "users:update", "users:revoke",
            "roles:read", "attributes:read", "attributes:manage", "abac:evaluate", "audit:read"
        ],
    },
    {
        "name": "Collaborator",
        "code": "ROLE_COLLABORATOR",
        "description": "Standard operator with device viewing and telemetry reading capabilities",
        "is_system": True,
        "permissions": ["devices:read", "applications:read", "telemetry:read"],
    },
    {
        "name": "Field Technician",
        "code": "ROLE_FIELD_TECHNICIAN",
        "description": "Field operations specialist with device registration, command, and configuration privileges",
        "is_system": False,
        "permissions": [
            "devices:read", "devices:create", "devices:update", "devices:command",
            "devices:configure", "telemetry:read"
        ],
    },
    {
        "name": "Security Auditor",
        "code": "ROLE_SECURITY_AUDITOR",
        "description": "Compliance officer with read-only visibility into users, roles, attributes, and audit logs",
        "is_system": False,
        "permissions": [
            "devices:read", "applications:read", "users:read", "roles:read",
            "attributes:read", "abac:read", "audit:read"
        ],
    },
]

DEFAULT_ATTRIBUTE_DEFINITIONS = [
    {
        "key": "clearance_level",
        "name": "Security Clearance Level",
        "description": "Numeric security clearance level (1 to 5) required for sensitive satellite downlinks",
        "entity_type": "user",
        "data_type": "number",
        "default_value": "1",
        "is_system": True,
    },
    {
        "key": "department",
        "name": "Department / Division",
        "description": "Operational division the subject belongs to",
        "entity_type": "user",
        "data_type": "enum",
        "allowed_values": ["engineering", "operations", "support", "security", "management"],
        "default_value": "operations",
        "is_system": True,
    },
    {
        "key": "region",
        "name": "Geographic Region",
        "description": "Geographical operational jurisdiction or deployment zone",
        "entity_type": "resource",
        "data_type": "enum",
        "allowed_values": ["GLOBAL", "US-EAST", "US-WEST", "EU-CENTRAL", "APAC", "INDIA"],
        "default_value": "GLOBAL",
        "is_system": True,
    },
    {
        "key": "satellite_access",
        "name": "Satellite Link Capability",
        "description": "Flag indicating authorization to issue store-and-forward satellite downlink transmissions",
        "entity_type": "user",
        "data_type": "boolean",
        "default_value": "false",
        "is_system": True,
    },
    {
        "key": "shift",
        "name": "Work Shift",
        "description": "Operator shift assignment used for temporal access control",
        "entity_type": "user",
        "data_type": "enum",
        "allowed_values": ["morning", "evening", "night", "24x7"],
        "default_value": "morning",
        "is_system": True,
    },
]

DEFAULT_ABAC_POLICIES = [
    {
        "name": "Satellite Command Clearance Enforcement",
        "description": "Requires user security clearance level 2 or higher to dispatch downlink commands to satellite devices",
        "effect": "ALLOW",
        "priority": 10,
        "target_actions": ["devices:command"],
        "target_resource_types": ["device"],
        "subject_conditions": {"clearance_level": {"$gte": 2}},
        "resource_conditions": {},
        "environment_conditions": {},
    },
    {
        "name": "Regional Device Maintenance Scope",
        "description": "Authorizes device configuration modification for devices within authorized operational regions",
        "effect": "ALLOW",
        "priority": 5,
        "target_actions": ["devices:configure", "devices:update"],
        "target_resource_types": ["device"],
        "subject_conditions": {},
        "resource_conditions": {"region": {"$in": ["US-WEST", "GLOBAL", "INDIA"]}},
        "environment_conditions": {},
    },
    {
        "name": "Night Shift Destructive Deletion Guard",
        "description": "Explicitly denies device and user deletions during night shift hours to mitigate operational risks",
        "effect": "DENY",
        "priority": 100,
        "target_actions": ["devices:delete", "users:delete"],
        "target_resource_types": ["*"],
        "subject_conditions": {"shift": {"$eq": "night"}},
        "resource_conditions": {},
        "environment_conditions": {},
    },
]


def seed_iam_database(db: Session):
    """Idempotently seeds permissions, roles, attributes, and policies."""
    logger.info("Checking and seeding IAM database entities...")

    # 1. Seed Permissions
    for code, name, desc, cat in DEFAULT_PERMISSIONS:
        perm = db.query(Permission).filter(Permission.code == code).first()
        if not perm:
            perm = Permission(code=code, name=name, description=desc, category=cat)
            db.add(perm)
    db.commit()

    # 2. Seed Roles & Map Permissions
    for role_def in DEFAULT_ROLES:
        role = db.query(Role).filter(Role.code == role_def["code"]).first()
        if not role:
            role = Role(
                name=role_def["name"],
                code=role_def["code"],
                description=role_def["description"],
                is_system=role_def["is_system"],
            )
            db.add(role)
            db.commit()
            db.refresh(role)

        # Map permissions
        for perm_code in role_def["permissions"]:
            if perm_code == "*":
                # Give all permissions
                all_p = db.query(Permission).all()
                for p in all_p:
                    exists = db.query(RolePermission).filter(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == p.id
                    ).first()
                    if not exists:
                        db.add(RolePermission(role_id=role.id, permission_id=p.id))
            else:
                p = db.query(Permission).filter(Permission.code == perm_code).first()
                if p:
                    exists = db.query(RolePermission).filter(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == p.id
                    ).first()
                    if not exists:
                        db.add(RolePermission(role_id=role.id, permission_id=p.id))
    db.commit()

    # 3. Seed Attribute Definitions
    for attr_def in DEFAULT_ATTRIBUTE_DEFINITIONS:
        attr = db.query(AttributeDefinition).filter(
            AttributeDefinition.entity_type == attr_def["entity_type"],
            AttributeDefinition.key == attr_def["key"]
        ).first()
        if not attr:
            attr = AttributeDefinition(
                key=attr_def["key"],
                name=attr_def["name"],
                description=attr_def["description"],
                entity_type=attr_def["entity_type"],
                data_type=attr_def["data_type"],
                allowed_values=attr_def.get("allowed_values"),
                default_value=attr_def.get("default_value"),
                is_system=attr_def.get("is_system", False),
            )
            db.add(attr)
    db.commit()

    # 4. Seed ABAC Policies
    for pol_def in DEFAULT_ABAC_POLICIES:
        pol = db.query(ABACPolicy).filter(ABACPolicy.name == pol_def["name"]).first()
        if not pol:
            pol = ABACPolicy(
                name=pol_def["name"],
                description=pol_def["description"],
                effect=pol_def["effect"],
                priority=pol_def["priority"],
                target_actions=pol_def["target_actions"],
                target_resource_types=pol_def["target_resource_types"],
                subject_conditions=pol_def["subject_conditions"],
                resource_conditions=pol_def["resource_conditions"],
                environment_conditions=pol_def["environment_conditions"],
                is_active=True,
            )
            db.add(pol)
    db.commit()

    # 5. Link Admin User to Admin Role
    admin_user = db.query(User).filter(User.role == "admin").first()
    admin_role = db.query(Role).filter(Role.code == "ROLE_ADMIN").first()
    if admin_user and admin_role:
        existing_ur = db.query(UserRole).filter(
            UserRole.user_id == admin_user.id,
            UserRole.role_id == admin_role.id
        ).first()
        if not existing_ur:
            db.add(UserRole(user_id=admin_user.id, role_id=admin_role.id))
            db.commit()

    logger.info("IAM initial database seed completed successfully.")
