param([switch]$Once)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$candidates = @('.venv\Scripts\python.exe', '.venv-cu21\Scripts\python.exe')
$python = $null
foreach ($candidate in $candidates) {
    $path = Join-Path $PSScriptRoot $candidate
    if (Test-Path -LiteralPath $path) {
        try {
            & $path --version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { $python = $path; break }
        } catch {
            # Un entorno antiguo puede apuntar a un Python que ya no existe.
            continue
        }
    }
}
if (-not $python) { throw 'Instala un entorno Python válido antes de iniciar el trabajador IA.' }
$arguments = @('manage.py', 'run_incident_ai_worker')
if ($Once) { $arguments += '--once' }
Write-Host 'Taji IA: analizando incidencias en segundo plano. Ctrl+C para detener.'
& $python @arguments
