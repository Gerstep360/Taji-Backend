# ==============================================================================
# Script de Instalación Interactivo - Backend Taji
# ==============================================================================

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# --- Funciones de Diseño y Animación GUI-Style ---
function Show-TajiBanner {
    param([string]$Subtitle = "INSTALADOR DE BACKEND")
    Clear-Host
    Write-Host " +----------------------------------------------------------------------+" -ForegroundColor Cyan
    Write-Host " |   TTTTT   AAA    JJJJJ  IIIII                                        |" -ForegroundColor Cyan
    Write-Host " |     T    A   A     J      I     S I S T E M A                        |" -ForegroundColor Cyan
    Write-Host " |     T    AAAAA     J      I     C O N D O M I N I O S                |" -ForegroundColor Yellow
    Write-Host " |     T    A   A  J  J      I                                          |" -ForegroundColor Magenta
    Write-Host " |     T    A   A   JJ     IIIII   * DEPLOYMENT ENGINE (DJANGO)         |" -ForegroundColor Magenta
    Write-Host " +----------------------------------------------------------------------+" -ForegroundColor Cyan
    Write-Host "       === $Subtitle ===" -ForegroundColor Green
    Write-Host ""
}

function Show-ProgressBarTask {
    param(
        [scriptblock]$Task,
        [string]$Message,
        [object[]]$ArgumentList = @()
    )
    $spin = @('|', '/', '-', '\')
    $job = Start-Job -ScriptBlock $Task -ArgumentList $ArgumentList
    $step = 0
    $width = 25

    while ($job.State -eq 'Running') {
        $frame = $spin[$step % 4]
        $filledLen = ($step % $width) + 1
        $fill = "█" * $filledLen
        $empty = "░" * ($width - $filledLen)
        
        Write-Host "`r [$frame] $Message... [$fill$empty]" -ForegroundColor Yellow -NoNewline
        Start-Sleep -Milliseconds 80
        $step++
    }
    $result = Receive-Job -Job $job
    Remove-Job -Job $job -Force
    
    $fullBar = "█" * $width
    if ($job.State -eq 'Completed') {
        Write-Host "`r [OK] $Message... [$fullBar] 100% COMPLETADO  " -ForegroundColor Green
    } else {
        Write-Host "`r [ERROR] $Message... [FALLO EN EL PROCESO]     " -ForegroundColor Red
        throw "Error al ejecutar la tarea."
    }
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

# --- Inicio del Asistente Interactivo ---
Show-TajiBanner -Subtitle "INSTALADOR INTERACTIVO BACKEND (DJANGO)"

$detectedIp = Get-TajiLanIp
Write-Host " +----------------------------------------------------------------------+" -ForegroundColor DarkGray
Write-Host " | Detector de red: IP Local / Servidor = $detectedIp" -ForegroundColor Cyan
Write-Host " +----------------------------------------------------------------------+" -ForegroundColor DarkGray
Write-Host ""

$inputIp = Read-Host " Configurar IP / Host para Backend [$detectedIp]"
if ([string]::IsNullOrWhiteSpace($inputIp)) { $inputIp = $detectedIp }

$inputPort = Read-Host " Puerto del servidor Backend API [8000]"
if ([string]::IsNullOrWhiteSpace($inputPort)) { $inputPort = "8000" }

$inputSubpath = Read-Host " Sub-ruta de aplicacion [/taji]"
if ([string]::IsNullOrWhiteSpace($inputSubpath)) { $inputSubpath = "/taji" }
if (-not $inputSubpath.StartsWith("/")) { $inputSubpath = "/$inputSubpath" }

Write-Host ""
Write-Host " +----------------------------------------------------------------------+" -ForegroundColor DarkGray
Write-Host " | Resumen de Configuracion Seleccionada:" -ForegroundColor Yellow
Write-Host " |   * IP Servidor:  $inputIp" -ForegroundColor Cyan
Write-Host " |   * Puerto API:   $inputPort" -ForegroundColor Cyan
Write-Host " |   * Sub-ruta Web: $inputSubpath" -ForegroundColor Cyan
Write-Host " +----------------------------------------------------------------------+" -ForegroundColor DarkGray
Write-Host ""

$confirm = Read-Host " Deseas proceder con la instalacion? (S/n) [S]"
if (-not [string]::IsNullOrWhiteSpace($confirm) -and $confirm -notlike "s*") {
    Write-Host "`n Instalacion cancelada por el usuario." -ForegroundColor Yellow
    exit 0
}

Write-Host ""

# 1. Verificar Python
Show-ProgressBarTask -Message "Verificando instalacion de Python" -Task {
    if (Get-Command python -ErrorAction SilentlyContinue) { exit 0 }
    if (Get-Command py -ErrorAction SilentlyContinue) { exit 0 }
    throw "Python no encontrado"
}

$pythonExecutable = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "py" }

# 2. Entorno virtual
if (-not (Test-Path ".venv")) {
    Show-ProgressBarTask -Message "Creando entorno virtual Python (.venv)" -Task {
        param($py)
        & $py -m venv .venv
    } -ArgumentList $pythonExecutable
} else {
    Write-Host " [OK] Entorno virtual (.venv) existente detectado" -ForegroundColor Green
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "No se encontro $venvPython"
}

# 3. Instalacion de dependencias
Show-ProgressBarTask -Message "Instalando paquetes desde requirements.txt" -Task {
    param($vPy)
    & $vPy -m pip install --upgrade pip --quiet 2>&1 | Out-Null
    & $vPy -m pip install -r requirements.txt --quiet 2>&1 | Out-Null
} -ArgumentList $venvPython

# 4. Creación/Configuración de .env
Show-ProgressBarTask -Message "Configurando variables de entorno (.env)" -Task {
    param($ip, $port, $subpath, $rootDir)
    $envPath = Join-Path $rootDir ".env"
    $envExample = Join-Path $rootDir ".env.example"
    
    if (-not (Test-Path $envPath) -and (Test-Path $envExample)) {
        Copy-Item $envExample $envPath
    }
    
    $allowedHosts = "localhost,127.0.0.1,0.0.0.0,$ip"
    $frontendUrls = "http://localhost:4200,http://127.0.0.1:4200,http://${ip}:4200,http://${ip}${subpath},http://${ip}:$port${subpath}"
    $resetUrl = "http://${ip}${subpath}/restablecer-contrasena"
    
    $lines = @(
        "SECRET_KEY=taji-secret-key-production-change-me",
        "DEBUG=True",
        "ALLOWED_HOSTS=$allowedHosts",
        "FRONTEND_URLS=$frontendUrls",
        "PASSWORD_RESET_URL=$resetUrl",
        "DATABASE_URL=sqlite:///db.sqlite3"
    )
    $content = $lines -join "`n"
    Set-Content -Path $envPath -Value $content -Encoding UTF8
} -ArgumentList $inputIp, $inputPort, $inputSubpath, $PSScriptRoot

Write-Host ""
Write-Host " +----------------------------------------------------------------------+" -ForegroundColor Green
Write-Host " |   INSTALACION DEL BACKEND COMPLETADA EXITOSAMENTE!                   |" -ForegroundColor Green
Write-Host " +----------------------------------------------------------------------+" -ForegroundColor Green
Write-Host " Puedes iniciar el servidor Django ejecutando:" -ForegroundColor Yellow
Write-Host "   .\iniciar.ps1" -ForegroundColor Cyan
Write-Host ""
