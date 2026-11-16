#!/bin/bash
# ====================================================================
# NibiaaNet v2 - One-Click Deployment Script for Ubuntu on Google Cloud (GCP)
# Supports: Backend, Decoder, IAM, Billing, Protocol Ingestion, Frontend,
# PostgreSQL 16, Redis 7, and Apache Cassandra 4.1
# ====================================================================

set -e

echo "===================================================================="
echo "    Starting NibiaaNet v2 Deployment on Ubuntu (GCP VM)            "
echo "===================================================================="

# 1. Update system packages
echo "[1/6] Updating system packages..."
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg lsb-release git ufw

# 2. Install Docker Engine & Docker Compose Plugin
if ! command -v docker &> /dev/null; then
    echo "[2/6] Installing Docker Engine..."
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo systemctl enable docker
    sudo systemctl start docker
    sudo usermod -aG docker $USER
    echo "Docker installed successfully."
else
    echo "[2/6] Docker already installed."
fi

# 3. Configure Ubuntu Local Firewall (UFW)
echo "[3/6] Configuring Ubuntu UFW rules..."
sudo ufw allow 22/tcp      comment 'SSH'
sudo ufw allow 8080/tcp    comment 'NibiaaNet Frontend Web Console'
sudo ufw allow 3000/tcp    comment 'Backend API Gateway'
sudo ufw allow 3001/tcp    comment 'Decoder Microservice'
sudo ufw allow 3002/tcp    comment 'IAM Microservice'
sudo ufw allow 3003/tcp    comment 'Billing Microservice'
sudo ufw allow 5001/udp    comment 'Protocol Ingestion - UDP'
sudo ufw allow 1883/tcp    comment 'Protocol Ingestion - MQTT'
sudo ufw allow 1001/tcp    comment 'Protocol Ingestion - TCP Stream'
sudo ufw allow 1002/tcp    comment 'Protocol Ingestion - Webhook'
sudo ufw --force enable

# 4. Clone or pull repository
echo "[4/6] Checking NibiaaNet repository..."
REPO_DIR="Nibiaa_netv2"
if [ ! -d "$REPO_DIR" ]; then
    git clone https://github.com/Niranjoyyengkhom/Nibiaa_netv2.git "$REPO_DIR"
    cd "$REPO_DIR"
else
    cd "$REPO_DIR"
    git pull origin main
fi

# 5. Prepare environment configuration
echo "[5/6] Setting up environment files..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
fi

# 6. Build and launch all microservices with Docker Compose
echo "[6/6] Building and starting all Docker containers..."
sudo docker compose down --remove-orphans || true
sudo docker compose build --parallel

# Clean build cache to free disk space for external image pulls
echo "Freeing build cache to preserve disk space..."
sudo docker builder prune -f || true
sudo apt-get clean || true

sudo docker compose up -d

echo "===================================================================="
echo "    NibiaaNet v2 Deployment Completed Successfully!                "
echo "===================================================================="
echo ""
echo "Access points on your GCP External IP:"
echo " - Frontend Web Console:          http://<YOUR_GCP_EXTERNAL_IP>:8080"
echo " - Backend API Gateway:           http://<YOUR_GCP_EXTERNAL_IP>:3000"
echo " - Decoder Microservice:          http://<YOUR_GCP_EXTERNAL_IP>:3001"
echo " - IAM Microservice:              http://<YOUR_GCP_EXTERNAL_IP>:3002"
echo " - Billing Microservice:          http://<YOUR_GCP_EXTERNAL_IP>:3003"
echo " - Protocol Ingestion (UDP):      udp://<YOUR_GCP_EXTERNAL_IP>:5001"
echo " - Protocol Ingestion (MQTT):     mqtt://<YOUR_GCP_EXTERNAL_IP>:1883"
echo " - Protocol Ingestion (TCP):      tcp://<YOUR_GCP_EXTERNAL_IP>:1001"
echo " - Protocol Ingestion (Webhook):  http://<YOUR_GCP_EXTERNAL_IP>:1002/webhook"
echo ""
echo "To check container status: sudo docker compose ps"
echo "To view live logs:         sudo docker compose logs -f"
echo "===================================================================="
