param(
    [string]$EnvFile = "$PSScriptRoot\..\.env"
)

$ErrorActionPreference = "Stop"

function Get-EnvValue([string]$Name) {
    $line = Get-Content -LiteralPath $EnvFile | Where-Object {
        $_ -match ('^' + [regex]::Escape($Name) + '=')
    } | Select-Object -First 1
    if (-not $line) { return "" }
    return (($line -split "=", 2)[1] -replace "^'|'$", "").Trim()
}

function Add-Check([System.Collections.Generic.List[object]]$Items, [string]$Name, [bool]$Ok, [string]$Detail) {
    $Items.Add([pscustomobject]@{
        service = $Name
        status = if ($Ok) { "ok" } else { "failed" }
        detail = $Detail
    })
}

$checks = [System.Collections.Generic.List[object]]::new()

$mysqlDsn = Get-EnvValue "MYSQL_DSN"
if ($mysqlDsn -match "mysql\+pymysql://([^:]+):([^@]+)@([^:]+):(\d+)/([^?]+)") {
    $mysqlUser = $Matches[1]
    $mysqlPassword = $Matches[2]
    $mysqlHost = $Matches[3]
    $mysqlPort = $Matches[4]
    $mysqlDatabase = $Matches[5]
    $env:MYSQL_PWD = $mysqlPassword
    try {
        & mysqladmin --host=$mysqlHost --port=$mysqlPort --user=$mysqlUser ping *> $null
        $ok = ($LASTEXITCODE -eq 0)
        Add-Check $checks "mysql" $ok "$mysqlHost`:$mysqlPort/$mysqlDatabase"
    } finally {
        Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
    }
} else {
    Add-Check $checks "mysql" $false "MYSQL_DSN invalid or missing"
}

$chromaHost = Get-EnvValue "CHROMA_HOST"
$chromaPort = Get-EnvValue "CHROMA_PORT"
$chromaOk = $false
$chromaEndpoint = ""
foreach ($version in @("v2", "v1")) {
    try {
        $heartbeat = Invoke-RestMethod -Uri "http://$chromaHost`:$chromaPort/api/$version/heartbeat" -TimeoutSec 5
        $chromaOk = $true
        $chromaEndpoint = "/api/$version/heartbeat"
        break
    } catch {
        continue
    }
}
Add-Check $checks "chroma" $chromaOk "$chromaHost`:$chromaPort$chromaEndpoint"

foreach ($prefix in @("LLM", "EMBEDDING", "RERANK")) {
    $baseUrl = Get-EnvValue "${prefix}_BASE_URL"
    $apiKey = Get-EnvValue "${prefix}_API_KEY"
    $model = Get-EnvValue "${prefix}_MODEL"
    if (-not $baseUrl -or -not $apiKey -or -not $model) {
        Add-Check $checks $prefix.ToLowerInvariant() $false "configuration missing"
        continue
    }
    try {
        $response = Invoke-WebRequest -Uri ($baseUrl.TrimEnd("/") + "/models") -Headers @{ Authorization = "Bearer $apiKey" } -Method Get -TimeoutSec 15 -UseBasicParsing
        Add-Check $checks $prefix.ToLowerInvariant() ($response.StatusCode -eq 200) "models endpoint; model=$model"
    } catch {
        $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        Add-Check $checks $prefix.ToLowerInvariant() $false "models endpoint status=$status"
    }
}

$checks | Format-Table -AutoSize
$required = @("mysql", "chroma", "llm", "embedding")
$failedRequired = @($checks | Where-Object { $_.service -in $required -and $_.status -ne "ok" })
if ($failedRequired.Count -gt 0) {
    exit 1
}
