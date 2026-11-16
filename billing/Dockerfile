FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=3004
ENV HOST=0.0.0.0
ENV PYTHONPATH=/app

EXPOSE 3004

CMD ["python", "run.py"]
