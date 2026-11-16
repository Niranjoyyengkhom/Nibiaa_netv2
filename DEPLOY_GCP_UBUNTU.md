# NibiaaNet v2 - GCP Ubuntu Docker Deployment Guide

This guide walks you through deploying **NibiaaNet v2** on an **Ubuntu Linux VM** running on **Google Cloud Platform (GCP)** using Docker and Docker Compose.

---

## 1. Recommended GCP Compute Engine VM Specification

* **OS**: Ubuntu 24.04 LTS or Ubuntu 22.04 LTS (x86_64)
* **Machine Type**: `e2-standard-4` (4 vCPUs, 16 GB Memory) or `e2-standard-2` (2 vCPUs, 8 GB Memory)
* **Boot Disk**: 50 GB - 100 GB SSD (Balanced persistent disk)
* **Firewall**: Check **"Allow HTTP traffic"** and **"Allow HTTPS traffic"**

---

## 2. Configure GCP VPC Firewall Rules

In the **Google Cloud Console**, go to **VPC network** → **Firewall** → **Create Firewall Rule** (or execute the `gcloud` command below in Cloud Shell):

```bash
gcloud compute firewall-rules create allow-nibiaanet-ports \
    --direction=INGRESS \
    --priority=1000 \
    --network=default \
    --action=ALLOW \
    --rules=tcp:8080,tcp:3000,tcp:3001,tcp:3002,tcp:3003,tcp:1883,tcp:1001,tcp:1002,udp:5001 \
    --source-ranges=0.0.0.0/0 \
    --target-tags=nibiaanet-server
```

> **Port Summary**:
> * `8080/tcp`: Frontend Web Console
> * `3000/tcp`: Backend API Gateway
> * `3001/tcp`: Decoder Microservice
> * `3002/tcp`: IAM Microservice (Roles, Users, Attributes)
> * `3003/tcp`: Billing & Subscription Microservice
> * `5001/udp`: Protocol Ingestion - UDP Datagram Listener
> * `1883/tcp`: Protocol Ingestion - MQTT 3.1.1 Broker
> * `1001/tcp`: Protocol Ingestion - TCP/IP Socket Stream
> * `1002/tcp`: Protocol Ingestion - HTTP Webhook Receiver

Assign the network tag `nibiaanet-server` to your VM instance.

---

## 3. One-Click Deployment on Ubuntu VM

SSH into your GCP Ubuntu instance and run the following:

```bash
# Clone the repository
git clone https://github.com/Niranjoyyengkhom/Nibiaa_netv2.git
cd Nibiaa_netv2

# Make the deploy script executable and run it
chmod +x deploy_ubuntu_gcp.sh
./deploy_ubuntu_gcp.sh
```

The script will automatically:
1. Update Ubuntu packages and install Docker + Docker Compose.
2. Configure the local UFW firewall.
3. Build all microservice images (`backend`, `decoder`, `iam`, `billing`, `protocol_ingestion`, `frontend`).
4. Start all containers in the background with automatic restart policies.

---

## 4. Manual Docker Compose Commands (Alternative)

If you prefer to run Docker Compose manually:

```bash
cd Nibiaa_netv2

# Copy environment variables
cp .env.example .env

# Build and start all 9 containers in detached mode
sudo docker compose build --parallel
sudo docker compose up -d

# Verify all containers are running and healthy
sudo docker compose ps
```

---

## 5. Verifying Deployed Services

Check the status of all containers:
```bash
sudo docker compose ps
```

Expected Output:
```text
NAME                            IMAGE                           STATUS
nibiaanet_db                    postgres:16-alpine              Up (healthy)
nibiaanet_redis                 redis:7-alpine                  Up (healthy)
nibiaanet_cassandra             cassandra:4.1                   Up (healthy)
nibiaanet_backend               nibiaa_netv2-backend            Up (healthy)
nibiaanet_decoder               nibiaa_netv2-decoder            Up (healthy)
nibiaanet_iam                   nibiaa_netv2-iam                Up (healthy)
nibiaanet_billing               nibiaa_netv2-billing            Up (healthy)
nibiaanet_protocol_ingestion    nibiaa_netv2-protocol_ingestion Up (healthy)
nibiaanet_frontend              nibiaa_netv2-frontend           Up (healthy)
```

---

## 6. Accessing NibiaaNet

Replace `<GCP_EXTERNAL_IP>` with your VM's public IP:

* **Web Console**: `http://<GCP_EXTERNAL_IP>:8080`
* **API Documentation**: `http://<GCP_EXTERNAL_IP>:3000/docs`
* **Decoder Service Docs**: `http://<GCP_EXTERNAL_IP>:3001/docs`
* **IAM Service Docs**: `http://<GCP_EXTERNAL_IP>:3002/docs`
* **Billing Service Docs**: `http://<GCP_EXTERNAL_IP>:3003/docs`
* **Ingestion Webhook**: `http://<GCP_EXTERNAL_IP>:1002/webhook`
* **Hubble Webhook Integration**: `http://<GCP_EXTERNAL_IP>:3000/webhooks/hubble`
* **MQTT Broker**: `mqtt://<GCP_EXTERNAL_IP>:1883`
* **UDP Datagram Port**: `udp://<GCP_EXTERNAL_IP>:5001`
* **TCP Stream Port**: `tcp://<GCP_EXTERNAL_IP>:1001`

---

## 7. Useful Maintenance Commands

```bash
# View live logs for all microservices
sudo docker compose logs -f

# View live logs for a specific service (e.g. protocol ingestion)
sudo docker compose logs -f protocol_ingestion

# Restart all services
sudo docker compose restart

# Update to latest code from GitHub and restart
git pull origin main
sudo docker compose build --parallel
sudo docker compose up -d
```
