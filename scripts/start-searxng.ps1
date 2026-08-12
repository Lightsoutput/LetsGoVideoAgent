$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Backend virtual environment was not found: $python"
}

# 生命周期、等待上限和真实检索验证都收敛到一个 Python 入口，避免 PowerShell
# 在 Docker 冷启动时留下“容器起来了、MCP 没起来”的半成功状态。
& $python (Join-Path $projectRoot "scripts\ensure-search-stack.py")
if ($LASTEXITCODE -ne 0) {
    throw "Search stack recovery failed. See the layered diagnostics above."
}
