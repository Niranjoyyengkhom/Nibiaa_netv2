@echo off
title NibiaaNet v2 - Multi-Service Orchestrator
echo ====================================================================
echo             NIBIAANET v2 IoT PLATFORM LAUNCHER
echo ====================================================================
echo.

cd /d "C:\Users\Niranjoy\Desktop\nibiaanet\nibiaanetv2"

echo [1/6] Checking PostgreSQL on Port 5432...
netstat -ano | findstr 5432 >nul
if %errorlevel% neq 0 (
    echo Starting PostgreSQL Server...
    start "PostgreSQL Server" /min "C:\Users\Niranjoy\pgsql\pgsql\bin\postgres.exe" -D "C:\Users\Niranjoy\pgsql\data"
    timeout /t 3 /nobreak >nul
) else (
    echo PostgreSQL is already running on Port 5432.
)

echo [2/6] Starting Decoder Service on Port 3001...
start "Decoder Service (Port 3001)" cmd /k "cd /d C:\Users\Niranjoy\Desktop\nibiaanet\nibiaanetv2 && set PYTHONPATH=decoder&& C:\Python315\python.exe decoder/run.py"

echo [3/6] Starting Dedicated Billing Microservice on Port 3003...
start "Billing Microservice (Port 3003)" cmd /k "cd /d C:\Users\Niranjoy\Desktop\nibiaanet\nibiaanetv2 && set PYTHONPATH=billing&& C:\Python315\python.exe billing/run.py"

echo [4/6] Starting Backend API Gateway on Port 3000...
start "Backend API Gateway (Port 3000)" cmd /k "cd /d C:\Users\Niranjoy\Desktop\nibiaanet\nibiaanetv2 && set PYTHONPATH=backend&& C:\Python315\python.exe backend/run.py"

echo [5/7] Starting IAM Service on Port 3002...
start "IAM Service (Port 3002)" cmd /k "cd /d C:\Users\Niranjoy\Desktop\nibiaanet\nibiaanetv2 && set PYTHONPATH=iam_service&& C:\Python315\python.exe iam_service/run.py"

echo [6/7] Starting Protocol Ingestion Microservice (UDP 5001, MQTT 1883, TCP 1001, Webhook 1002)...
start "Protocol Ingestion (UDP 5001, MQTT 1883, TCP 1001, Webhook 1002)" cmd /k "cd /d C:\Users\Niranjoy\Desktop\nibiaanet\nibiaanetv2 && set PYTHONPATH=protocol_ingestion&& C:\Python315\python.exe protocol_ingestion/run.py"

echo [7/7] Starting Frontend Console on Port 8080...
start "Frontend Console (Port 8080)" cmd /k "cd /d C:\Users\Niranjoy\Desktop\nibiaanet\nibiaanetv2\frontend && npm run dev"

echo.
echo ====================================================================
echo All NibiaaNet Services Launched:
echo  - Decoder Service:             http://localhost:3001 (Docs: /docs)
echo  - Backend API Gateway:         http://localhost:3000 (Docs: /docs)
echo  - IAM Service:                 http://localhost:3002 (Docs: /docs)
echo  - Billing Microservice:        http://localhost:3003 (Docs: /docs)
echo  - Protocol Ingestion Gateway:  http://localhost:1002
echo     * UDP Listener:             Port 5001
echo     * MQTT Broker:              Port 1883
echo     * TCP/IP Listener:          Port 1001
echo     * Webhook Ingestion API:    Port 1002
echo  - Frontend Web Console:        http://localhost:8080
echo ====================================================================
pause
