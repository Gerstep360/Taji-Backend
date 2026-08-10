param(
    [string]$Address = "0.0.0.0:8000"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Falta Backend/.venv. Ejecuta: python -m venv .venv"
}

& ".\.venv\Scripts\python.exe" manage.py migrate
& ".\.venv\Scripts\python.exe" manage.py runserver $Address

