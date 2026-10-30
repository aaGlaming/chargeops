[CmdletBinding()]
param([switch]$DockerDependencies)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StateDir = Join-Path $Root "logs\windows"

function Stop-Tree([int]$ProcessId) {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) { Stop-Tree ([int]$child.ProcessId) }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

foreach ($name in @("frontend", "backend", "chroma")) {
    $pidFile = Join-Path $StateDir "$name.pid"
    if (Test-Path $pidFile) {
        $processId = [int](Get-Content -LiteralPath $pidFile)
        Stop-Tree $processId
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }
}

if ($DockerDependencies) {
    & docker compose -f (Join-Path $Root "compose.yaml") down
    if ($LASTEXITCODE -ne 0) { throw "Docker 依赖停止失败" }
}
Write-Output "ChargeOps Windows application processes stopped"
