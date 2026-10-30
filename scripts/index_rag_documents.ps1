[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONPATH = "backend"
Push-Location $Root
try {
    # The public registration script is idempotent and indexes the two AFDC
    # Markdown notes into MySQL metadata and Chroma.
    & python scripts/register_afdc_public_data.py
    if ($LASTEXITCODE -ne 0) { throw "RAG document indexing failed" }
} finally { Pop-Location }
