[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$BackupDir, [Parameter(Mandatory=$true)][string]$RestoreDir, [string]$ApiUrl, [string]$Username, [string]$Password)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $Root
try {
    $arguments = @("scripts/restore_chargeops.py", $BackupDir, "--restore-dir", $RestoreDir, "--report", "evals/step39/reports/latest.json")
    if ($ApiUrl -and $Username -and $Password) { $arguments += @("--api-url", $ApiUrl, "--username", $Username, "--password", $Password) }
    & python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Restore verification failed" }
}
finally { Pop-Location }
