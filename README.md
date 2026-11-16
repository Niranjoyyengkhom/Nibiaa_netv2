# NibiaaNet v2 — Satellite & Terrestrial IoT Platform

A modern, multi-tenant IoT platform for Satellite (NTN) and Terrestrial (TN) devices, featuring fine-grained RBAC, device lifecycle management, store-and-forward satellite command queues, sandboxed dynamic payload decoders, and a React dashboard.

---

## 1. Services & Port Map

| Component | Technology | Default Port | Description |
|---|---|:---:|---|
| **Backend API** | Python (FastAPI + SQLAlchemy) | **`3000`** | Platform Core: Auth, RBAC, Tenants, Devices, Configuration & Telemetry |
| **Decoder Service** | Python (FastAPI + Node Sandbox) | **`3001`** | High-performance decoding, validation, match engine & ingestion pipeline |
| **IAM Service** | Python (FastAPI + SQLAlchemy) | **`3003`** | Dedicated IAM: Users, Hierarchical RBAC, Dynamic Attributes & ABAC Policy Decision Point |
| **UDP Ingestion** | Async UDP Socket | **`5005`** | Direct raw datagram uplink receiver for remote satellite / terrestrial nodes |
| **Frontend UI** | ReactJS + Vite | **`8080`** | RBAC-adaptive operator console and telemetry visualization |
| **PostgreSQL** | PostgreSQL 16 | **`5432`** | Dedicated relational data store (`device_registry`). |

---

## 2. Directory Structure

```text
nibiaanetv2/
├── backend/                       # Platform Backend API (Port 3000)
│   ├── app/
│   │   ├── dependencies/          # JWT auth & permission verifications
│   │   ├── models/                # SQLAlchemy database entities
│   │   ├── routers/               # FastAPI REST endpoints
│   │   ├── schemas/               # Pydantic v2 schemas
│   │   ├── services/              # Business logic, RBAC, store-and-forward
│   │   ├── decoder_runtime/       # Sandboxed JS runner script
│   │   ├── database.py            # PostgreSQL DB engine
│   │   └── main.py                # FastAPI entry point
│   ├── run.py                     # Launcher for Port 3000
│   ├── requirements.txt
│   └── Dockerfile
│
├── decoder/                       # Standalone Decoder Microservice (Port 3001)
│   ├── app/
│   │   ├── ingestion/             # UDP & MQTT async message ingest listeners
│   │   ├── models/                # Decoder definitions, versions & message store
│   │   ├── routers/               # /health, /decoders, /run, /messages
│   │   ├── schemas/               # Pydantic schemas for payload execution
│   │   ├── services/              # Sandbox executor, match specificity, sinks
│   │   └── main.py                # FastAPI entry point
│   ├── runner.js                  # Node.js VM isolated runner
│   ├── run.py                     # Launcher for Port 3001
│   ├── requirements.txt
│   └── Dockerfile
│
├── iam_service/                   # User, Roles & Attribute Management Microservice (Port 3003)
│   ├── app/
│   │   ├── dependencies/          # JWT bearer auth, permission & role checks
│   │   ├── models/                # Users, Roles, Permissions, Attributes, ABAC policies, Audit
│   │   ├── routers/               # /users, /roles, /permissions, /attributes, /abac, /auth, /audit
│   │   ├── schemas/               # Pydantic v2 schemas
│   │   ├── services/              # ABAC engine (PDP), user lifecycle, attribute EAV, seed
│   │   ├── database.py            # PostgreSQL DB engine
│   │   └── main.py                # FastAPI entry point
│   ├── tests/                     # Comprehensive test suite
│   ├── run.py                     # Launcher for Port 3003
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/                      # ReactJS Console (Port 8080)
│   ├── src/                       # React components, pages & state management
│   ├── vite.config.js             # Vite configuration with port 8080 & reverse proxy
│   ├── package.json
│   └── Dockerfile
│
├── docker-compose.yml             # Orchestration for all services
├── start_all.ps1                  # Single-click PowerShell launcher
└── README.md
```

---

## 3. Database Setup (PostgreSQL)

NibiaaNet v2 requires a PostgreSQL instance.

1. Ensure PostgreSQL is running on `localhost:5432`.
2. Create the database:
   ```powershell
   psql -U postgres -c "CREATE DATABASE device_registry;"
   ```
3. Update connection credentials in `backend/.env` and `decoder/.env`:
   ```text
   DATABASE_URL=postgresql+psycopg://postgres:yourpassword@localhost:5432/device_registry
   ```

---

## 4. Quick Start (Windows PowerShell)

### Prerequisites
* **Python 3.10+** (`python --version`)
* **Node.js 18+** (`node --version`)
* **PostgreSQL 14+** (Running on port 5432)

### Option A: One-Click Startup Script
```powershell
cd nibiaanetv2
.\start_all.ps1
```

### Option B: Manual Step-by-Step

#### 1. Start the Backend API (Port 3000)
```powershell
cd nibiaanetv2\backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```
* **API Documentation**: [http://127.0.0.1:3000/docs](http://127.0.0.1:3000/docs)

#### 2. Start the Decoder Service (Port 3001)
```powershell
cd nibiaanetv2\decoder
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```
* **Decoder Health**: [http://127.0.0.1:3001/health](http://127.0.0.1:3001/health)
* **Decoder Documentation**: [http://127.0.0.1:3001/docs](http://127.0.0.1:3001/docs)

#### 3. Start the IAM Microservice (Port 3003)
```powershell
cd nibiaanetv2\iam_service
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```
* **IAM Health & Info**: [http://127.0.0.1:3003/health](http://127.0.0.1:3003/health) / [http://127.0.0.1:3003/info](http://127.0.0.1:3003/info)
* **IAM API Documentation**: [http://127.0.0.1:3003/docs](http://127.0.0.1:3003/docs)

#### 4. Start the React Frontend (Port 8080)
```powershell
cd nibiaanetv2\frontend
npm install
npm run dev
```
* **Console URL**: [http://localhost:8080](http://localhost:8080)

---

## 5. Docker Deployment

The platform is fully containerized using Docker and Docker Compose, orchestrating the 7 core services:
* **PostgreSQL 16** (`nibiaanet_db` on `5432`) — Relational database with automatic schema migrations & seed data
* **Redis 7** (`nibiaanet_redis` on `6379`) — Decoupled high-throughput telemetry queue buffer
* **Apache Cassandra 4.1** (`nibiaanet_cassandra` on `9042`) — Dedicated IoT time-series telemetry store
* **Backend API** (`nibiaanet_backend` on `3000`) — Core platform REST API with encrypted credentials
* **Decoder Service** (`nibiaanet_decoder` on `3001` & `5005/udp`) — Isolated Node.js sandbox decoder & UDP listener
* **IAM Microservice** (`nibiaanet_iam` on `3003`) — User, Roles, Attribute management & ABAC Policy Decision Point
* **React Frontend** (`nibiaanet_frontend` on `8080`) — Single Page Application console

### Prerequisites
* **Docker Desktop for Windows** (with WSL 2 or Hyper-V enabled)
  * Install via winget (Run as Administrator):
    ```powershell
    winget install -e --id Docker.DockerDesktop
    ```
  * Or download from [Docker Official Site](https://www.docker.com/products/docker-desktop/)

### One-Click Docker Startup
```powershell
cd nibiaanetv2
.\start_docker.ps1
```

### Manual Docker Compose Commands
```powershell
# Build and start all 6 services in the foreground
docker compose up --build

# Run in background (detached mode)
docker compose up -d --build

# Check status and health of containers
docker compose ps

# View service logs
docker compose logs -f backend decoder

# Stop all containers (preserve persistent volumes)
docker compose down

# Stop and remove all containers and data volumes
docker compose down -v
```

### Container Endpoints
* **Frontend Console**: [http://localhost:8080](http://localhost:8080)
* **Backend API Root & Docs**: [http://localhost:3000](http://localhost:3000) / [http://localhost:3000/docs](http://localhost:3000/docs)
* **Decoder Service & Health**: [http://localhost:3001/health](http://localhost:3001/health) / [http://localhost:3001/docs](http://localhost:3001/docs)
* **UDP Ingestion**: `127.0.0.1:5005/udp`

---

## 6. Security & Architecture Notes

* **Sandboxed Execution**: Decoder scripts run in isolated Node.js worker contexts with memory caps, 200 ms timeout per message, and keyword normalization preventing bypasses.
* **Strict PostgreSQL**: Dedicated PostgreSQL engine with migrations and transaction-safe message delivery.
* **Cross-Tenant Guard**: Resources from other tenants return HTTP 404 rather than 403 to prevent enumeration attacks.
* **Encrypted Secrets**: Sensitive device keys (such as LoRaWAN `AppKey`) are encrypted with AES-Fernet (`enc:...`).
