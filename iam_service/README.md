# NibiaaNet IAM Microservice — User, Roles & Attribute Management

A dedicated, enterprise-grade Identity & Access Management (IAM) and Attribute-Based Access Control (ABAC) microservice for the NibiaaNet platform. Built with **FastAPI**, **SQLAlchemy 2.0**, and **PostgreSQL**.

---

## 1. Core Architecture

```text
iam_service/
├── app/
│   ├── dependencies/          # JWT bearer auth, permission & role checks
│   ├── models/                # Database entities:
│   │   ├── user.py            # User entity with status lifecycle & credentials
│   │   ├── role.py            # Hierarchical roles (is_system, parent_role_id)
│   │   ├── permission.py      # Granular capability catalog (e.g. devices:command)
│   │   ├── role_permission.py # Role-Permission junction
│   │   ├── user_role.py       # Multi-role user assignments
│   │   ├── attribute.py       # EAV schema definitions & typed entity values
│   │   ├── abac_policy.py     # ABAC policy rules (subject, resource, env, effect)
│   │   └── audit.py           # Security audit logs
│   ├── schemas/               # Pydantic v2 validation models
│   ├── services/
│   │   ├── user_service.py    # Complete user CRUD, revoke/restore, scrypt hashing
│   │   ├── role_service.py    # Role hierarchy resolution, permission mapping
│   │   ├── attribute_service.py # Dynamic attribute validation & EAV store
│   │   ├── abac_engine.py     # Policy Decision Point (PDP) evaluator
│   │   ├── auth_service.py    # Authentication, JWT issuance & token introspection
│   │   ├── audit_service.py   # Security event logging
│   │   └── seed_service.py    # Automatic initial seed for roles, perms & policies
│   ├── routers/
│   │   ├── health.py          # /health, /info, /stats
│   │   ├── auth.py            # /auth/login, /auth/me, /auth/introspect
│   │   ├── users.py           # /users (CRUD, status, roles, attributes)
│   │   ├── roles.py           # /roles (CRUD, permissions, assigned users)
│   │   ├── permissions.py     # /permissions (all, categorized)
│   │   ├── attributes.py      # /attributes/definitions, /attributes/entities
│   │   ├── abac.py            # /abac/policies, /abac/evaluate, /authorize
│   │   └── audit.py           # /audit (security audit trail)
│   ├── database.py            # PostgreSQL connection pool with pre-ping
│   └── main.py                # FastAPI initialization, CORS, lifespan seed
├── tests/
│   └── test_iam.py            # 10 comprehensive unit & integration tests
├── run.py                     # Entry point (Default Port: 3003)
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## 2. Key Capabilities

### A. User Management
* **Lifecycle Management**: Create, list, search, update, delete, revoke access (`is_active=False`), and restore access.
* **Credential Security**: Passwords hashed using scrypt with unique salt bytes (`salt:hash`).
* **Multi-Tenancy**: Users scoped to tenant/workspace, or global administrators.
* **Multi-Role Assignment**: Users can be assigned multiple roles simultaneously (`/users/{id}/roles`).

### B. Role Management (Hierarchical RBAC)
* **Granular Permissions**: 25+ built-in permissions across devices, applications, decoders, telemetry, users, roles, and attributes.
* **Role Inheritance**: Roles can have a `parent_role_id`. Permissions from parent roles are resolved recursively!
* **System Roles Protected**: Built-in roles (`Administrator`, `Organization Owner`, `Collaborator`) cannot be deleted.

### C. Dynamic Attribute Management (EAV Store)
* **Attribute Definitions**: Register custom metadata schemas for `user`, `resource` (device), `tenant`, or `environment`.
* **Data Types**: `string`, `number`, `boolean`, `json`, `list`, `enum`.
* **Constraint Validation**: Validates regex patterns, enum allowed values, and data type bounds before storage.
* **Entity Value Assignment**: Set, update, query, or delete attributes on any entity in the platform (`/attributes/entities/{entity_type}/{entity_id}`).

### D. ABAC Policy Decision Point (PDP)
* **Evaluator**: Evaluates whether a subject is authorized to perform an action on a resource given the context.
* **Supported Operators**: `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in`, `$nin`, `$contains`, `$regex`.
* **Dynamic Cross-Referencing**: Compare resource attributes directly to user attributes:
  * e.g., `{"sensitivity": {"$lte": "subject.clearance_level"}}`
  * e.g., `{"region": {"$in": "subject.allowed_regions"}}`
* **Priority & Deny Overrides**: Explicit DENY rules override ALLOW rules (NIST standard).

### E. Token Introspection
* Endpoint: `POST /auth/introspect`
* Allows backend services, decoder microservice, and API gateways to validate a JWT token and resolve user profile, assigned roles, permissions, and dynamic attributes in a single round-trip.

---

## 3. Quick Start

### Running Locally (Port 3003)
```powershell
cd iam_service
pip install -r requirements.txt
python run.py
```

### Running with Single-Click Launcher
```powershell
.\start_all.ps1
```

### Running Tests
```powershell
pytest iam_service/tests/test_iam.py -v
```

---

## 4. API Reference

| Endpoint | Method | Description |
|---|:---:|---|
| `/health` | `GET` | Health check & database connection status |
| `/info` | `GET` | Service capabilities & metadata |
| `/stats` | `GET` | Counts of users, roles, attributes & policies |
| `/auth/login` | `POST` | Authenticate user & receive JWT token |
| `/auth/me` | `GET` | Current user profile, roles, perms & attributes |
| `/auth/introspect` | `POST` | Token introspection for microservices |
| `/users/` | `GET`, `POST` | List users (filters & pagination) or create user |
| `/users/{id}` | `GET`, `PUT`, `DELETE` | User CRUD operations |
| `/users/{id}/revoke` | `POST` | Revoke user access immediately |
| `/users/{id}/restore` | `POST` | Restore revoked user account |
| `/users/{id}/roles` | `GET`, `POST` | Get or assign roles to user |
| `/users/{id}/attributes` | `GET`, `PUT` | Get or batch set dynamic user attributes |
| `/roles/` | `GET`, `POST` | List or create roles |
| `/roles/{id}` | `GET`, `PUT`, `DELETE` | Role details, update, delete |
| `/roles/{id}/permissions` | `GET`, `POST` | Get effective permissions or assign codes |
| `/permissions/` | `GET`, `POST` | Capability catalog or custom permission |
| `/permissions/categories` | `GET` | Permissions grouped by category |
| `/attributes/definitions` | `GET`, `POST` | List or register attribute definitions |
| `/attributes/entities/{type}/{id}` | `GET`, `PUT`, `POST` | Query or assign attributes to an entity |
| `/abac/policies` | `GET`, `POST` | List or create ABAC policy rules |
| `/abac/evaluate` | `POST` | **Policy Decision Point (PDP)**: evaluate authorization |
| `/audit/` | `GET` | Query security audit log records |
