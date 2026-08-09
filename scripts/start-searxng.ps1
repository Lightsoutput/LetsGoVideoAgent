$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    throw "Docker was not found. Install and start Docker Desktop, then run this script again."
}

# 本地开发只让 Docker 承载 SearXNG。Search MCP 使用项目虚拟环境运行，
# 避免为了一个轻量 Python 服务反复拉取基础镜像导致启动链路不稳定。
docker compose --project-directory $projectRoot up -d searxng
if ($LASTEXITCODE -ne 0) {
    throw "Docker could not start SearXNG. Confirm Docker Desktop is running and the current user can access Docker Engine."
}

$python = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Backend virtual environment was not found: $python"
}

$healthScript = Join-Path $projectRoot "scripts\check-search-mcp.py"
# Python 启动器先检查监听端口，已运行时不会重复创建进程；日志统一进入 var/logs。
& $python (Join-Path $projectRoot "scripts\start-search-mcp.py")
$launcherExitCode = $LASTEXITCODE
if ($launcherExitCode -ne 0) {
    throw "Search MCP background launcher failed."
}

$deadline = (Get-Date).AddSeconds(60)
do {
    try {
        $response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:8888/search?q=LetsGoVideoAgent&format=json" `
            -TimeoutSec 3 `
            -UseBasicParsing
        & $python $healthScript
        if ($response.StatusCode -eq 200 -and $LASTEXITCODE -eq 0) {
            Write-Output "SearXNG is ready: http://127.0.0.1:8888"
            Write-Output "Search MCP is ready: http://127.0.0.1:8090/mcp"
            exit 0
        }
    }
    catch {
        Start-Sleep -Seconds 2
    }
} while ((Get-Date) -lt $deadline)

throw "Search stack was not ready within 60 seconds. Check docker compose logs searxng and var/logs/search-mcp/server.err.log"
