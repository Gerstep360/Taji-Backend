param(
    [string]$MachineIp,
    [int]$ApiPort = 8000
)

$ErrorActionPreference = "Stop"

function Get-TajiLanIPv4 {
    param([string]$PreferredAddress)

    if (-not [string]::IsNullOrWhiteSpace($PreferredAddress)) {
        $parsedAddress = $null
        if (-not [System.Net.IPAddress]::TryParse($PreferredAddress, [ref]$parsedAddress)) {
            throw "La dirección '$PreferredAddress' no es una IP válida."
        }
        return $PreferredAddress
    }

    $candidate = Get-NetIPConfiguration |
        Where-Object {
            $_.NetAdapter.Status -eq "Up" -and
            $null -ne $_.IPv4Address -and
            $null -ne $_.IPv4DefaultGateway -and
            $_.IPv4Address.IPAddress -notlike "169.254.*"
        } |
        Sort-Object { $_.NetAdapter.InterfaceMetric } |
        Select-Object -First 1

    if ($null -eq $candidate) {
        throw "No se encontró una IPv4 LAN activa. Usa -MachineIp."
    }
    return $candidate.IPv4Address.IPAddress
}

$lanIp = Get-TajiLanIPv4 -PreferredAddress $MachineIp
$env:ALLOWED_HOSTS = "localhost,127.0.0.1,0.0.0.0,$lanIp"
$env:FRONTEND_URLS = "http://localhost:4200,http://127.0.0.1:4200,http://${lanIp}:4200"
$env:PASSWORD_RESET_URL = "http://${lanIp}:4200/restablecer-contrasena"

Write-Host "Taji API: http://${lanIp}:$ApiPort/api/v1" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "run-dev.ps1") -Address "0.0.0.0:$ApiPort"