# NibiaaNet v2 - Docker Startup Script
# Checks Docker installation, starts services via docker compose

Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "      NibiaaNet v2 Docker Orchestration        " -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan

# 1. Check if Docker CLI is in PATH
$DockerCmd = Get-Command docker -ErrorAction SilentlyContinue

if (-not $DockerCmd) {
    # Check common Docker Desktop installation path
    $DefaultDockerPath = "C:\Program Files\Docker\Docker\resources\bin"
    if (Test-Path "$DefaultDockerPath\docker.exe") {
        Write-Host "[+] Adding Docker to current session PATH..." -ForegroundColor Yellow
        $env:Path = "$DefaultDockerPath;$env:Path"
        $DockerCmd = Get-Command docker -ErrorAction SilentlyContinue
    }
}

if (-not $DockerCmd) {
    Write-Host "[!] Docker CLI is not installed or not in PATH." -ForegroundColor Red
    Write-Host ""
    Write-Host "To install Docker Desktop on Windows:" -ForegroundColor Yellow
    Write-Host "  1. Using winget in an Administrator terminal:" -ForegroundColor White
    Write-Host "     winget install -e --id Docker.DockerDesktop" -ForegroundColor Cyan
    Write-Host "  2. Or download directly from:" -ForegroundColor White
    Write-Host "     https://www.docker.com/products/docker-desktop/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "After installation, open Docker Desktop and ensure the Docker engine is running." -ForegroundColor Yellow
    exit 1
}

# 2. Check if Docker daemon is running
Write-Host "[*] Checking Docker engine status..." -ForegroundColor Gray
docker info > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Docker daemon is not running. Please start Docker Desktop and try again." -ForegroundColor Red
    exit 1
}

Write-Host "[+] Docker engine is running." -ForegroundColor Green
Write-Host "[*] Starting all services with docker compose..." -ForegroundColor Cyan

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

docker compose up --build
