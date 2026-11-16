# NibiaaNet v2 — Satellite & Terrestrial IoT Telemetry Platform

A modern, multi-tenant IoT platform for Satellite (NTN) and Terrestrial (TN) devices, featuring fine-grained RBAC, device lifecycle management, store-and-forward satellite command queues, sandboxed dynamic payload decoders, real-time protocol ingestion (UDP, MQTT, TCP/IP, Webhook), and an interactive React web console.

---

## 1. Services & Port Map

| Component | Technology | Default Port | Description |
|---|---|:---:|---|
| **Frontend Web Console** | ReactJS + Vite | **`8080`** | RBAC-adaptive operator console, Ingestion Profiles & live data |
| **Backend API Gateway** | Python (FastAPI + SQLAlchemy) | **`3000`** | Core pipeline: Auth, Tenants, Devices, Configuration & Uplink router |
| **Decoder Microservice** | Python (FastAPI + Node Sandbox) | **`3001`** | High-performance decoding, validation, match engine & sinks |
| **IAM Microservice** | Python (FastAPI + SQLAlchemy) | **`3002`** | Dedicated IAM: Users, Hierarchical RBAC, Dynamic Attributes & ABAC |
| **Billing Microservice** | Python (FastAPI + Encrypted DB) | **`3003`** | Dedicated Billing: 1NCE, Monogoto SIM cards, Odoo ERP & plans |
| **Protocol Ingestion - UDP** | Asyncio Datagram Socket | **`5001`** | Direct raw datagram uplink receiver for NTN satellite & LPWAN nodes |
| **Protocol Ingestion - MQTT** | Asyncio MQTT 3.1.1 Broker | **`1883`** | Built-in MQTT broker for IoT sensor streams and gateway telemetry |
| **Protocol Ingestion - TCP** | Asyncio TCP Socket Stream | **`1001`** | Raw TCP socket stream listener with newline and length-prefix framing |
| **Protocol Ingestion - Webhook** | FastAPI HTTP REST Server | **`1002`** | Webhook gateway for Hubble Network and third-party ground segments |
| **PostgreSQL Database** | PostgreSQL 16 | **`5432`** | Relational data stores (`device_registry` and `billing`) |
| **Redis Cache** | Redis 7 | **`6379`** | Real-time queue and message broker cache |
| **Apache Cassandra** | Cassandra 4.1 | **`9042`** | Long-term high-throughput telemetry storage |

---

## 2. Directory Structure

```text
nibiaanetv2/
├── backend/                       # Platform Backend API Gateway (Port 3000)
│   ├── app/                       # Dependencies, models, routers, schemas, services
│   ├── run.py                     # Launcher for Port 3000
│   ├── requirements.txt
│   └── Dockerfile
│
├── decoder/                       # Standalone Decoder Microservice (Port 3001)
│   ├── app/                       # Ingestion, models, routers, schemas, services
│   ├── runner.js                  # Node.js VM isolated runner
│   ├── run.py                     # Launcher for Port 3001
│   ├── requirements.txt
│   └── Dockerfile
│
├── iam_service/                   # User, Roles & Attribute IAM Microservice (Port 3002)
│   ├── app/                       # Users, Roles, Permissions, Attributes, ABAC policies
│   ├── run.py                     # Launcher for Port 3002
│   ├── requirements.txt
│   └── Dockerfile
│
├── billing/                       # Billing & Subscription Microservice (Port 3003)
│   ├── app/                       # 1NCE, Monogoto, Odoo, encrypted billing database
│   ├── run.py                     # Launcher for Port 3003
│   ├── requirements.txt
│   └── Dockerfile
│
├── protocol_ingestion/            # Ingestion Microservice (UDP 5001, MQTT 1883, TCP 1001, Webhook 1002)
│   ├── app/                       # udp_listener, mqtt_broker, tcp_listener, webhook_server
│   ├── run.py                     # Concurrent launcher for all 4 protocol listeners
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/                      # ReactJS Operator Web Console (Port 8080)
│   ├── src/                       # React components, Ingestion Profiles, state management
│   ├── vite.config.js             # Vite configuration with reverse proxies
│   ├── package.json
│   └── Dockerfile
│
├── .github/workflows/             # GitHub Actions CI/CD workflows
│   └── docker-ci.yml              # Automated container build verification
│
├── docker-compose.yml             # Orchestration for all 9 containers
├── deploy_ubuntu_gcp.sh           # One-click Ubuntu on GCP deployment script
├── DEPLOY_GCP_UBUNTU.md           # Step-by-step GCP deployment documentation
├── start_all_services.bat         # Single-click Windows local launcher
└── README.md
```

---

## 3. Deployment on Ubuntu (Google Cloud Platform)

### Quick Start
```bash
# 1. Clone the repository
git clone https://github.com/Niranjoyyengkhom/Nibiaa_netv2.git
cd Nibiaa_netv2

# 2. Run the deployment script
chmod +x deploy_ubuntu_gcp.sh
./deploy_ubuntu_gcp.sh
```

### Manual Docker Compose
```bash
cp .env.example .env
sudo docker compose build --parallel
sudo docker compose up -d
sudo docker compose ps
```

Detailed GCP firewall rules and setup instructions can be found in [DEPLOY_GCP_UBUNTU.md](DEPLOY_GCP_UBUNTU.md).

---

## 4. Local Development (Windows)

1. Ensure PostgreSQL is running on port `5432`.
2. Launch all microservices and frontend simultaneously:
   ```cmd
   start_all_services.bat
   ```
3. Open your browser at `http://localhost:8080`.
