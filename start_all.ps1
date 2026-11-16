# NibiaaNet v2 Local Launcher
# Starts Backend (port 3002), Decoder (port 3001), IAM Service (port 3003), and Frontend (port 8081)

Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "     NibiaaNet v2 Multi-Service Startup        " -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host " [1] Backend API:       http://127.0.0.1:3002   " -ForegroundColor Green
Write-Host " [2] Decoder Service:   http://127.0.0.1:3001   " -ForegroundColor Green
Write-Host " [3] IAM Microservice:  http://127.0.0.1:3003   " -ForegroundColor Green
Write-Host " [4] React Frontend:    http://127.0.0.1:8081   " -ForegroundColor Green
Write-Host "===============================================" -ForegroundColor Cyan

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = (Get-Item $Root).Target
if ($Target) {
    if ($Target -is [array]) { $Root = $Target[0] } else { $Root = $Target }
}

# Determine best Python executable
$PyCmd = "python"
if (Test-Path "C:\Python315\python.exe") {
    $PyCmd = "C:\Python315\python.exe"
}

# 0. Ensure PostgreSQL is running on port 5432
$PgBin = "C:\Users\Niranjoy\pgsql\pgsql\bin"
$PgData = "C:\Users\Niranjoy\pgsql\data"
$Port5432 = Test-NetConnection -ComputerName 127.0.0.1 -Port 5432 -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $Port5432 -and (Test-Path "$PgBin\pg_ctl.exe")) {
    Write-Host "[*] Starting PostgreSQL Database on port 5432..." -ForegroundColor Cyan
    Start-Process -FilePath "$PgBin\pg_ctl.exe" -ArgumentList "start -D `"$PgData`" -l `"$PgData\..\postgres.log`"" -Wait
}

# 1. Start Backend on Port 3002
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root\backend'; Write-Host 'Starting Backend API on Port 3002...' -ForegroundColor Green; & '$PyCmd' run.py"

# 2. Start Decoder on Port 3001
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root\decoder'; Write-Host 'Starting Decoder Service on Port 3001...' -ForegroundColor Green; & '$PyCmd' run.py"

# 3. Start IAM Microservice on Port 3003
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root\iam_service'; Write-Host 'Starting IAM Microservice on Port 3003...' -ForegroundColor Green; & '$PyCmd' run.py"

# 4. Start Frontend on Port 8081
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root\frontend'; Write-Host 'Starting Frontend on Port 8081...' -ForegroundColor Green; npm.cmd run dev"

Write-Host "`nAll four services launched in separate windows!" -ForegroundColor Yellow
