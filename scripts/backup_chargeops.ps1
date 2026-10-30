[CmdletBinding()]
param([string]$OutputRoot = "backups/step39")
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $Root
try { & python scripts/backup_chargeops.py --output-root $OutputRoot; if ($LASTEXITCODE -ne 0) { throw "Backup failed" } }
finally { Pop-Location }
