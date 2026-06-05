$ErrorActionPreference = "Stop"

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  S-AI: 水利空间智能体平台 启动脚本" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

$composeFile = Join-Path $PSScriptRoot "docker-compose.yml"

if (-not (Test-Path ".env")) {
    Write-Host "[WARN] .env file not found, copying from .env.example" -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "[ACTION] Please edit .env and set ZHIPUAI_API_KEY" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[1/3] Starting data layer (PostGIS + Redis + ChromaDB)..." -ForegroundColor Green
docker compose -f $composeFile up -d postgis redis chroma

Write-Host "[2/3] Waiting for data layer to be healthy..." -ForegroundColor Green
Start-Sleep -Seconds 10

Write-Host "[3/3] Starting MCP servers and agents..." -ForegroundColor Green
docker compose -f $composeFile up -d mcp-gis mcp-data mcp-knowledge mcp-map sai-registry

Start-Sleep -Seconds 5

docker compose -f $composefile up -d router-agent gis-agent knowledge-agent

Write-Host ""
Write-Host "======================================" -ForegroundColor Green
Write-Host "  S-AI Platform Started!" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Services:" -ForegroundColor White
Write-Host "    PostGIS:        localhost:5432" -ForegroundColor Gray
Write-Host "    Redis:          localhost:6379" -ForegroundColor Gray
Write-Host "    ChromaDB:       localhost:8001" -ForegroundColor Gray
Write-Host "    Agent Registry: localhost:9000" -ForegroundColor Gray
Write-Host ""
Write-Host "  MCP Tool Servers:" -ForegroundColor White
Write-Host "    GIS:            localhost:5001" -ForegroundColor Gray
Write-Host "    Data:           localhost:5002" -ForegroundColor Gray
Write-Host "    Knowledge:      localhost:5003" -ForegroundColor Gray
Write-Host "    Map:            localhost:5004" -ForegroundColor Gray
Write-Host ""
Write-Host "  Agents:" -ForegroundColor White
Write-Host "    Router:         localhost:6000" -ForegroundColor Gray
Write-Host "    GIS:            localhost:6001" -ForegroundColor Gray
Write-Host "    Knowledge:      localhost:6005" -ForegroundColor Gray
Write-Host ""
Write-Host "  Test: curl http://localhost:6000/health" -ForegroundColor Yellow
Write-Host ""
