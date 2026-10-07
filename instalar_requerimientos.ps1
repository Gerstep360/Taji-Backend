# ==============================================================================
# Script de Instalación Interactivo - Backend Taji
# ==============================================================================

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ForceEnv = $args -contains "-ForceEnv"

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
    <#
        Ejecuta una tarea en un job de PowerShell mostrando una barra de progreso.

        Correcciones frente a la versión anterior:
        - Distingue "falló" de "se colgó" e incluye un tiempo límite.
        - Propaga el motivo real del fallo en lugar de un mensaje genérico.
        - Captura la salida del job para poder mostrarla y evitar que contamine
          la salida del script (que antes se mezclaba con el banner).
        - No se traga los errores de comandos nativos enviados a stderr.
    #>
    param(
        [scriptblock]$Task,
        [string]$Message,
        [object[]]$ArgumentList = @(),
        [int]$TimeoutSeconds = 900
    )

    $job = Start-Job -ScriptBlock $Task -ArgumentList $ArgumentList
    $spin = @('|', '/', '-', '\')
    $step = 0
    $width = 25
    $startedAt = Get-Date
    $timedOut = $false

    while ($job.State -eq 'Running') {
        if (((Get-Date) - $startedAt).TotalSeconds -gt $TimeoutSeconds) {
            $timedOut = $true
            Stop-Job $job -ErrorAction SilentlyContinue
            break
        }

        $frame = $spin[$step % 4]
        $filledLen = ($step % $width) + 1
        $fill = "█" * $filledLen
        $empty = "░" * ($width - $filledLen)

        Write-Host "`r [$frame] $Message... [$fill$empty]" -ForegroundColor Yellow -NoNewline
        Start-Sleep -Milliseconds 80
        $step++
    }

    $state = $job.State

    # Receive-Job puede convertir el stderr del job en error terminante si la
    # preferencia es Stop; por eso se aísla en su propio try/catch.
    $output = @()
    $receiveError = $null
    try {
        $output = @(Receive-Job $job -ErrorAction SilentlyContinue 2>&1 |
            ForEach-Object { "$_" })
    }
    catch {
        $receiveError = $_.Exception.Message
    }

    $reason = $receiveError
    if (-not $reason -and $job.ChildJobs.Count -gt 0) {
        $jobReason = $job.ChildJobs[0].JobStateInfo.Reason
        if ($jobReason) { $reason = "$jobReason" }
    }

    Remove-Job $job -Force -ErrorAction SilentlyContinue

    $fullBar = "█" * $width

    if ($timedOut) {
        Write-Host "`r [TIMEOUT] $Message... [SUPERO ${TimeoutSeconds}s]              " -ForegroundColor Red
        throw "La tarea '$Message' supero el tiempo limite de ${TimeoutSeconds}s."
    }

    if ($state -ne 'Completed') {
        Write-Host "`r [ERROR] $Message... [FALLO EN EL PROCESO]     " -ForegroundColor Red
        $detalle = @($output | Where-Object { $_ -and $_.Trim() } | Select-Object -Last 5)
        if ($detalle.Count -gt 0) {
            Write-Host "        Detalle del fallo:" -ForegroundColor DarkYellow
            foreach ($line in $detalle) {
                Write-Host "        $line" -ForegroundColor DarkYellow
            }
        }
        if ($reason) {
            throw "Fallo en '$Message'. Causa: $reason"
        }
        throw "Fallo en '$Message' (estado del job: $state)."
    }

    Write-Host "`r [OK] $Message... [$fullBar] 100% COMPLETADO  " -ForegroundColor Green
    return $output
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
    $ErrorActionPreference = "Continue"
    if (Get-Command python -ErrorAction SilentlyContinue) { exit 0 }
    if (Get-Command py -ErrorAction SilentlyContinue) { exit 0 }
    throw "Python no encontrado. Instala Python 3.11+ y vuelve a ejecutar este script."
} -TimeoutSeconds 60

$pythonExecutable = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "py" }

# 2. Entorno virtual
if (-not (Test-Path ".venv")) {
    Show-ProgressBarTask -Message "Creando entorno virtual Python (.venv)" -Task {
        param($py)
        $ErrorActionPreference = "Continue"
        & $py -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "venv devolvio el codigo $LASTEXITCODE." }
    } -ArgumentList $pythonExecutable -TimeoutSeconds 180
}
else {
    Write-Host " [OK] Entorno virtual (.venv) existente detectado" -ForegroundColor Green
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "No se encontro $venvPython"
}

# 3. Instalacion de dependencias
# Se usa la ruta ABSOLUTA de requirements.txt: el CWD de un job de Start-Job no
# esta garantizado y antes pip podia no encontrar el archivo (y fallar en
# silencio porque su salida se descartaba).
$requirementsFile = Join-Path $PSScriptRoot "requirements.txt"

Show-ProgressBarTask -Message "Instalando paquetes desde requirements.txt" -Task {
    param($vPy, $reqFile)
    $ErrorActionPreference = "Continue"

    & $vPy -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "No se pudo actualizar pip (codigo $LASTEXITCODE)." }

    & $vPy -m pip install -r $reqFile
    if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias (codigo $LASTEXITCODE)." }
} -ArgumentList $venvPython, $requirementsFile

# 4. Creación/Configuración de .env
# Regla: NUNCA se sobrescribe un .env existente. Se regenera solo si no hay
# ninguno, y en ese caso se parte de .env.example para heredar los nombres de
# variable correctos (DJANGO_SECRET_KEY, JWT_SIGNING_KEY) y la base de datos
# configurada en el proyecto.
$envInfo = Show-ProgressBarTask -Message "Configurando variables de entorno (.env)" -Task {
    param($ip, $port, $subpath, $rootDir, $force)
    $ErrorActionPreference = "Continue"

    # Esta función vive DENTRO del scriptblock a proposito: Start-Job ejecuta en
    # un runspace aislado y no ve las funciones definidas en el script principal.
    # Fija CLAVE=valor en el .env: reemplaza la clave si existe o la agrega si no,
    # para no depender de un -replace que pueda duplicar la variable.
    function Set-EnvValue {
        param([string]$Content, [string]$Key, [string]$Value)
        $pattern = "(?m)^" + [regex]::Escape($Key) + "=.*$"
        if ($Content -match $pattern) {
            return ($Content -replace $pattern, "$Key=$Value")
        }
        return ($Content.TrimEnd() + "`n" + "$Key=$Value`n")
    }

    $envPath = Join-Path $rootDir ".env"
    $envExample = Join-Path $rootDir ".env.example"

    if ((Test-Path $envPath) -and (-not $force)) {
        return "INFO: .env ya existe y se conserva sin cambios."
    }

    $allowedHosts = "localhost,127.0.0.1,0.0.0.0,$ip"
    $frontendUrls = "http://localhost:4200,http://127.0.0.1:4200,http://${ip}:4200,http://${ip}${subpath},http://${ip}:$port${subpath}"
    $resetUrl = "http://${ip}${subpath}/restablecer-contrasena"

    $content = if (Test-Path $envExample) {
        Get-Content $envExample -Raw
    }
    else {
        @(
            "DEBUG=True",
            "DJANGO_SECRET_KEY=cambia-esta-clave-por-una-larga-y-aleatoria",
            "JWT_SIGNING_KEY=cambia-esta-clave-por-otra-larga-y-aleatoria"
        ) -join "`n"
    }

    # .env.example trae una linea de ejemplo comentada para ALLOWED_HOSTS; se
    # elimina primero para no dejar la variable duplicada al parchear.
    $content = $content -replace '(?m)^#\s*ALLOWED_HOSTS=.*\r?\n?', ''

    # Se ajustan solo los valores dependientes del host/IP elegido.
    $content = Set-EnvValue -Content $content -Key "ALLOWED_HOSTS" -Value $allowedHosts
    $content = Set-EnvValue -Content $content -Key "FRONTEND_URLS" -Value $frontendUrls
    $content = Set-EnvValue -Content $content -Key "PASSWORD_RESET_URL" -Value $resetUrl

    Set-Content -Path $envPath -Value $content -Encoding UTF8 -NoNewline
    return "OK: .env creado en $envPath"
} -ArgumentList $inputIp, $inputPort, $inputSubpath, $PSScriptRoot, $ForceEnv

if ($envInfo) {
    Write-Host "        $($envInfo | Select-Object -First 1)" -ForegroundColor DarkGray
}
if ($ForceEnv -and (Test-Path (Join-Path $PSScriptRoot ".env"))) {
    Write-Host "        AVISO: se regenero .env por -ForceEnv; revisa tus claves." -ForegroundColor Yellow
}

Write-Host ""
Write-Host " +----------------------------------------------------------------------+" -ForegroundColor Green
Write-Host " |   INSTALACION DEL BACKEND COMPLETADA EXITOSAMENTE!                   |" -ForegroundColor Green
Write-Host " +----------------------------------------------------------------------+" -ForegroundColor Green
Write-Host " Puedes iniciar el servidor Django ejecutando:" -ForegroundColor Yellow
Write-Host "   .\iniciar.ps1" -ForegroundColor Cyan
Write-Host ""