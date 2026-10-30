[CmdletBinding()]
param([switch]$SkipAuthorizationSeed)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONPATH = "backend"
Push-Location $Root
try {
    & python scripts/init_database.py
    if ($LASTEXITCODE -ne 0) { throw "Database initialization failed" }
    if (-not $SkipAuthorizationSeed) {
        & python scripts/seed_auth.py
        if ($LASTEXITCODE -ne 0) { throw "Authorization seed failed" }
    }
} finally { Pop-Location }
