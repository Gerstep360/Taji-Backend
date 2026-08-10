# ==============================================================================
# Script de Instalación de Requerimientos - Backend Taji
# ==============================================================================

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "   TAJI BACKEND - Instalación de Entorno y Deps   " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Verificar presencia de Python
$pythonExecutable = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonExecutable = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExecutable = "py"
} else {
    throw "Python no está instalado o no se encuentra en el PATH del sistema."
}

Write-Host "[1/4] Python detectado: $pythonExecutable" -ForegroundColor Green

# 2. Crear entorno virtual si no existe
if (-not (Test-Path ".venv")) {
    Write-Host "[2/4] Creando entorno virtual (.venv)..." -ForegroundColor Yellow
    & $pythonExecutable -m venv .venv
    Write-Host "      Entorno virtual creado exitosamente." -ForegroundColor Green
} else {
    Write-Host "[2/4] Entorno virtual (.venv) ya existe." -ForegroundColor Green
}

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "No se encontró el ejecutable de Python en el entorno virtual ($venvPython)."
}

# 3. Actualizar pip e instalar requerimientos
Write-Host "[3/4] Actualizando pip e instalando dependencias desde requirements.txt..." -ForegroundColor Yellow
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r requirements.txt

if ($LASTEXITCODE -eq 0) {
    Write-Host "      Dependencias instaladas correctamente." -ForegroundColor Green
} else {
    throw "Ocurrió un error al instalar las dependencias."
}

# 4. Archivo .env
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Host "[4/4] Copiando .env.example -> .env ..." -ForegroundColor Yellow
        Copy-Item ".env.example" ".env"
        Write-Host "      Archivo .env creado desde .env.example." -ForegroundColor Green
    } else {
        Write-Host "[4/4] AVISO: No se encontró .env.example para copiar." -ForegroundColor Yellow
    }
} else {
    Write-Host "[4/4] Archivo .env ya existe." -ForegroundColor Green
}

Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host "   Instalación completada con éxito." -ForegroundColor Green
Write-Host "   Puedes iniciar el servidor ejecutando:" -ForegroundColor Cyan
Write-Host "   .\iniciar.ps1" -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan
