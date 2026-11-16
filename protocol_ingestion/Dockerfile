FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV BACKEND_INGEST_URL=http://backend:3000/ingest/internal-uplink

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ingestion protocol listeners:
# UDP 5001 (Datagrams), MQTT 1883 (Broker), TCP 1001 (Socket Stream), Webhook 1002 (HTTP REST)
EXPOSE 5001/udp
EXPOSE 1883
EXPOSE 1001
EXPOSE 1002

CMD ["python", "run.py"]
