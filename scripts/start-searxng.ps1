$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    throw "Docker was not found. Install and start Docker Desktop, then run this script again."
}

docker compose --project-directory $projectRoot up -d searxng search-mcp

$deadline = (Get-Date).AddSeconds(60)
do {
    try {
        $response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:8888/search?q=LetsGoVideoAgent&format=json" `
            -TimeoutSec 3 `
            -UseBasicParsing
        if ($response.StatusCode -eq 200) {
            Write-Output "SearXNG is ready: http://127.0.0.1:8888"
            Write-Output "Search MCP is ready: http://127.0.0.1:8090/mcp"
            exit 0
        }
    }
    catch {
        Start-Sleep -Seconds 2
    }
} while ((Get-Date) -lt $deadline)

throw "SearXNG was not ready within 60 seconds. Run: docker compose logs searxng"
