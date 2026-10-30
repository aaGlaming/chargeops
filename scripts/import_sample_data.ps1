[CmdletBinding()]
param([ValidateSet("public", "synthetic", "all")][string]$Dataset = "all")

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $Root
try {
    & python scripts/import_data.py --dataset $Dataset
    if ($LASTEXITCODE -ne 0) { throw "Sample data import failed" }
} finally { Pop-Location }
