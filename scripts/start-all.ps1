param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

# Windows 环境变量名不区分大小写，但部分启动器会同时注入 Path 与 PATH。
# Windows PowerShell 5.1 的 Start-Process 会把它们当成重复字典键并直接报错，
# 这正是批处理偶发“第一次启动失败”的根因。启动任何子进程前先合并为一个 Path。
$pathEntries = @(
    [Environment]::GetEnvironmentVariables().GetEnumerator() |
        Where-Object { [string]$_.Key -ieq "PATH" }
)
if ($pathEntries.Count -gt 1) {
    $canonicalPath = [string]$pathEntries[0].Value
    [Environment]::SetEnvironmentVariable("PATH", $null, "Process")
    [Environment]::SetEnvironmentVariable("Path", $canonicalPath, "Process")
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
$nextCli = Join-Path $projectRoot "frontend\node_modules\next\dist\bin\next"
$dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$backendLogDirectory = Join-Path $projectRoot "var\logs\backend"
$frontendLogDirectory = Join-Path $projectRoot "var\logs\frontend"
$dockerLogDirectory = Join-Path $projectRoot "var\logs\docker"

function Test-TcpPort {
    param([int]$Port, [int]$TimeoutMilliseconds = 700)

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        return $task.Wait($TimeoutMilliseconds) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Test-HttpEndpoint {
    param([string]$Uri)

    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

function Wait-HttpEndpoint {
    param([string]$Name, [string]$Uri, [int]$TimeoutSeconds)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-HttpEndpoint -Uri $Uri) {
            Write-Host "[READY] $Name -> $Uri" -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    throw "$Name was not ready within $TimeoutSeconds seconds."
}

function Invoke-WithRetry {
    param(
        [string]$Name,
        [scriptblock]$Action,
        [int]$Attempts = 3,
        [int]$DelaySeconds = 3
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        & $Action
        if ($LASTEXITCODE -eq 0) {
            return
        }
        if ($attempt -lt $Attempts) {
            Write-Host "[RETRY] $Name attempt $attempt/$Attempts failed; retrying in $DelaySeconds seconds." -ForegroundColor Yellow
            Start-Sleep -Seconds $DelaySeconds
        }
    }
    throw "$Name failed after $Attempts attempts."
}

function Test-DockerEngine {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        return $false
    }

    New-Item -ItemType Directory -Path $dockerLogDirectory -Force | Out-Null
    $probeOut = Join-Path $dockerLogDirectory "probe.out.log"
    $probeErr = Join-Path $dockerLogDirectory "probe.err.log"
    try {
        $probe = Start-Process `
            -FilePath $docker.Source `
            -ArgumentList @("info", "--format", "{{.ServerVersion}}") `
            -WindowStyle Hidden `
            -RedirectStandardOutput $probeOut `
            -RedirectStandardError $probeErr `
            -PassThru
        if (-not $probe.WaitForExit(6000)) {
            $probe.Kill()
            return $false
        }
        $probe.Refresh()
        # Windows PowerShell 5.1 的 Start-Process 在重定向输出时偶尔拿不到 ExitCode，
        # 即使 docker 已成功输出服务端版本也会得到 $null。版本字符串本身就是更可靠的
        # Engine 就绪信号，避免因此错误等待 90 秒。
        $serverVersion = Get-Content -LiteralPath $probeOut -Raw -ErrorAction SilentlyContinue
        return $probe.HasExited -and -not [string]::IsNullOrWhiteSpace($serverVersion)
    }
    catch {
        return $false
    }
}

function Wait-DockerEngine {
    param([int]$TimeoutSeconds)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-DockerEngine) {
            Write-Host "[READY] Docker Engine" -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Docker Engine was not ready within $TimeoutSeconds seconds."
}

function Start-LoggedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$OutputLog,
        [string]$ErrorLog
    )

    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $OutputLog `
        -RedirectStandardError $ErrorLog `
        -PassThru
    Write-Host "[START] $Name pid=$($process.Id)" -ForegroundColor Cyan
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Backend Python environment does not exist: $python"
}

$dockerReady = Test-DockerEngine
$searxngReady = Test-TcpPort -Port 8888
$mcpReady = Test-TcpPort -Port 8090
$backendReady = Test-HttpEndpoint -Uri "http://127.0.0.1:8000/api/v1/health/live"
$frontendReady = Test-HttpEndpoint -Uri "http://127.0.0.1:3000"

if ($CheckOnly) {
    Write-Host "LetsGoVideoAgent service status" -ForegroundColor Cyan
    Write-Host "  Docker Engine : $dockerReady"
    Write-Host "  SearXNG       : $searxngReady"
    Write-Host "  Search MCP    : $mcpReady"
    Write-Host "  Backend API   : $backendReady"
    Write-Host "  Frontend      : $frontendReady"
    # Docker Desktop 可能已退出，但现有 SearXNG/MCP 仍然可用；状态检查以实际服务为准。
    if ($searxngReady -and $mcpReady -and $backendReady -and $frontendReady) {
        exit 0
    }
    exit 1
}

Write-Host "Starting LetsGoVideoAgent (manual one-shot startup; no autostart/watchdog)." -ForegroundColor Cyan

if ($searxngReady -and $mcpReady) {
    # 搜索服务都已经可用时，不再仅因 Docker 探测失败而唤起 Docker Desktop。
    # 这可以避免重复点击批处理后 Docker 窗口被反复拉起。
    Write-Host "[SKIP] SearXNG and Search MCP are already available."
}
else {
    if (-not $dockerReady) {
        if (-not (Test-Path -LiteralPath $dockerDesktop)) {
            throw "Docker Desktop was not found: $dockerDesktop"
        }
        if (Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue) {
            Write-Host "[WAIT] Docker Desktop is starting; no duplicate process will be created."
        }
        else {
            Write-Host "[START] Docker Desktop (minimized)" -ForegroundColor Cyan
            Start-Process -FilePath $dockerDesktop -ArgumentList "--minimized" -WindowStyle Hidden | Out-Null
        }
        Wait-DockerEngine -TimeoutSeconds 90
    }
    else {
        Write-Host "[SKIP] Docker Engine is already running."
    }

    # 只有搜索链路确实不完整时才修复容器和本地 MCP，并自动重试。
    Invoke-WithRetry -Name "Search stack startup" -Attempts 3 -DelaySeconds 4 -Action {
        & $python (Join-Path $projectRoot "scripts\ensure-search-stack.py") --skip-real-search
    }
}

New-Item -ItemType Directory -Path $backendLogDirectory -Force | Out-Null
if (Test-TcpPort -Port 8000) {
    if (-not (Test-HttpEndpoint -Uri "http://127.0.0.1:8000/api/v1/health/live")) {
        throw "Port 8000 is occupied, but it is not LetsGoVideoAgent API."
    }
    Write-Host "[SKIP] Backend API is already running."
}
else {
    # Windows 后台服务不启用 uvicorn --reload：reloader 会再派生一个 Python，
    # 重启时容易留下幽灵监听，让 8000 看似健康却仍运行旧代码。
    Start-LoggedProcess `
        -Name "Backend API" `
        -FilePath $python `
        -Arguments @("-m", "uvicorn", "lets_go_video_agent.main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $projectRoot `
        -OutputLog (Join-Path $backendLogDirectory "api.out.log") `
        -ErrorLog (Join-Path $backendLogDirectory "api.err.log")
}
Wait-HttpEndpoint -Name "Backend API" -Uri "http://127.0.0.1:8000/api/v1/health/live" -TimeoutSeconds 45

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    throw "Node.js was not found. Install Node.js 22 or add it to PATH."
}
if (-not (Test-Path -LiteralPath $nextCli)) {
    throw "Frontend dependencies are missing. Run: corepack pnpm --dir frontend install"
}

New-Item -ItemType Directory -Path $frontendLogDirectory -Force | Out-Null
if (Test-TcpPort -Port 3000) {
    if (-not (Test-HttpEndpoint -Uri "http://127.0.0.1:3000")) {
        throw "Port 3000 is occupied, but it is not a reachable frontend."
    }
    Write-Host "[SKIP] Frontend is already running."
}
else {
    $env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8000/api/v1"
    Start-LoggedProcess `
        -Name "Next.js frontend" `
        -FilePath $node.Source `
        -Arguments @($nextCli, "dev", "--hostname", "127.0.0.1", "--port", "3000") `
        -WorkingDirectory (Join-Path $projectRoot "frontend") `
        -OutputLog (Join-Path $frontendLogDirectory "dev.out.log") `
        -ErrorLog (Join-Path $frontendLogDirectory "dev.err.log")
}
Wait-HttpEndpoint -Name "Frontend" -Uri "http://127.0.0.1:3000" -TimeoutSeconds 60

Write-Host ""
Write-Host "LetsGoVideoAgent is ready." -ForegroundColor Green
Write-Host "  Web UI : http://127.0.0.1:3000"
Write-Host "  API    : http://127.0.0.1:8000/docs"
Write-Host "  SearXNG: http://127.0.0.1:8888"
Write-Host "  MCP    : http://127.0.0.1:8090/mcp"
Write-Host "  Logs   : $projectRoot\var\logs"
