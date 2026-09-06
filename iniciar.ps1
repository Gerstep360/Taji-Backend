# ==============================================================================
# Script de Inicio Interactivo - Backend Taji (Django)
# ==============================================================================

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Show-TajiBanner {
    param([string]$Subtitle = "LANZADOR DE BACKEND")
    Clear-Host
    Write-Host "+----------------------------------------------------------+" -ForegroundColor Cyan
    Write-Host "|   TTTTT   AAA    JJJJJ  IIIII                            |" -ForegroundColor Cyan
    Write-Host "|     T    A   A     J      I                              |" -ForegroundColor Cyan
    Write-Host "|     T    AAAAA     J      I    SYSTEM CONDOMINIUMS       |" -ForegroundColor Yellow
    Write-Host "|     T    A   A  J  J      I                              |" -ForegroundColor Magenta
    Write-Host "|     T    A   A   JJ     IIIII                            |" -ForegroundColor Magenta
    Write-Host "+----------------------------------------------------------+" -ForegroundColor Cyan
    Write-Host "       === $Subtitle ===" -ForegroundColor Green
    Write-Host ""
}

function Get-TajiLanIp {
    $candidate = Get-NetIPConfiguration -ErrorAction SilentlyContinue |
        Where-Object {
            $_.NetAdapter.Status -eq "Up" -and
            $null -ne $_.IPv4Address -and
            $null -ne $_.IPv4DefaultGateway -and
            $_.IPv4Address.IPAddress -notlike "169.254.*"
        } |
        Sort-Object { $_.NetAdapter.InterfaceMetric } |
        Select-Object -First 1

    if ($null -ne $candidate) {
        return $candidate.IPv4Address.IPAddress
    }
    return "127.0.0.1"
}

Show-TajiBanner -Subtitle "SERVIDOR DE DESARROLLO DJANGO API"

$lanIp = Get-TajiLanIp
Write-Host " Detector de red IP local: " -NoNewline; Write-Host "$lanIp" -ForegroundColor Cyan
Write-Host ""

$inputPort = Read-Host " Puerto API Backend [8000]"
if ([string]::IsNullOrWhiteSpace($inputPort)) { $inputPort = "8000" }

$inputSubpath = Read-Host " Sub-ruta esperada [/taji]"
if ([string]::IsNullOrWhiteSpace($inputSubpath)) { $inputSubpath = "/taji" }
if (-not $inputSubpath.StartsWith("/")) { $inputSubpath = "/$inputSubpath" }

$env:ALLOWED_HOSTS = "localhost,127.0.0.1,0.0.0.0,$lanIp"
$env:FRONTEND_URLS = "http://localhost:4200,http://127.0.0.1:4200,http://${lanIp}:4200,http://${lanIp}${inputSubpath},http://${lanIp}:${inputPort}${inputSubpath}"
$env:PASSWORD_RESET_URL = "http://${lanIp}${inputSubpath}/restablecer-contrasena"

Write-Host ""
Write-Host " ----------------------------------------------------------" -ForegroundColor DarkGray
Write-Host " Configuración activa del Backend:" -ForegroundColor Yellow
Write-Host "   * URL API:          " -NoNewline; Write-Host "http://${lanIp}:${inputPort}/api/v1" -ForegroundColor Cyan
Write-Host "   * Hosts Permitidos: " -NoNewline; Write-Host "$env:ALLOWED_HOSTS" -ForegroundColor DarkCyan
Write-Host " ----------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""

Write-Host " Iniciando servidor Django..." -ForegroundColor Green
& (Join-Path $PSScriptRoot "run-dev.ps1") -Address "0.0.0.0:$inputPort"