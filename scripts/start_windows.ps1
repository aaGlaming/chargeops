[CmdletBinding()]
param(
    [switch]$DockerDependencies,
    [switch]$StartMySqlService,
    [switch]$StartChroma,
    [switch]$SkipFrontend,
    [string]$MySqlServiceName = "MySQL84",
    [int]$ApiPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StateDir = Join-Path $Root "logs\windows"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

function Test-TcpPort([string]$HostName, [int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        return $task.Wait(500) -and $client.Connected
    } catch { return $false } finally { $client.Dispose() }
}

function Wait-TcpPort([string]$HostName, [int]$Port, [int]$TimeoutSeconds = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpPort $HostName $Port) { return }
        Start-Sleep -Seconds 1
    }
    throw "服务未在 $TimeoutSeconds 秒内监听 $HostName`:$Port"
}

function Save-ProcessId([string]$Name, [int]$ProcessId) {
    Set-Content -LiteralPath (Join-Path $StateDir "$Name.pid") -Value $ProcessId -Encoding ascii
}

if ($DockerDependencies) {
    & docker compose -f (Join-Path $Root "compose.yaml") up -d mysql chroma
    if ($LASTEXITCODE -ne 0) { throw "Docker 依赖启动失败" }
} elseif ($StartMySqlService) {
    $service = Get-Service -Name $MySqlServiceName -ErrorAction Stop
    if ($service.Status -ne "Running") { Start-Service -Name $MySqlServiceName }
}
Wait-TcpPort "127.0.0.1" 3306

if ($StartChroma -and -not (Test-TcpPort "127.0.0.1" 8001)) {
    $chromaOut = Join-Path $StateDir "chroma.out.log"
    $chromaErr = Join-Path $StateDir "chroma.err.log"
    $chroma = Start-Process -FilePath "chroma" -ArgumentList "run","--host","127.0.0.1","--port","8001","--path",(Join-Path $Root ".chroma") -WorkingDirectory $Root -RedirectStandardOutput $chromaOut -RedirectStandardError $chromaErr -PassThru
    Save-ProcessId "chroma" $chroma.Id
}
Wait-TcpPort "127.0.0.1" 8001

if (-not (Test-TcpPort "127.0.0.1" $ApiPort)) {
    $backendOut = Join-Path $StateDir "backend.out.log"
    $backendErr = Join-Path $StateDir "backend.err.log"
    $env:PYTHONPATH = "backend"
    $backend = Start-Process -FilePath "python" -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port",$ApiPort -WorkingDirectory (Join-Path $Root "backend") -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr -PassThru
    Save-ProcessId "backend" $backend.Id
}
Wait-TcpPort "127.0.0.1" $ApiPort

if (-not $SkipFrontend -and -not (Test-TcpPort "127.0.0.1" $FrontendPort)) {
    $frontendOut = Join-Path $StateDir "frontend.out.log"
    $frontendErr = Join-Path $StateDir "frontend.err.log"
    $env:VITE_API_BASE_URL = "http://127.0.0.1:$ApiPort"
    $frontendCommand = "npm run dev -- --host 127.0.0.1 --port $FrontendPort"
    $frontend = Start-Process -FilePath "cmd.exe" -ArgumentList "/d","/s","/c",$frontendCommand -WorkingDirectory (Join-Path $Root "frontend") -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr -PassThru -WindowStyle Hidden
    Save-ProcessId "frontend" $frontend.Id
    Wait-TcpPort "127.0.0.1" $FrontendPort
}

Write-Output "ChargeOps Windows services are ready: MySQL 3306, Chroma 8001, API $ApiPort, Frontend $FrontendPort"
