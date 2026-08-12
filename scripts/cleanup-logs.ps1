param(
    [ValidateRange(1, 365)]
    [int]$RetentionDays = 14,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logRoot = Join-Path $projectRoot "var\logs"

if (-not (Test-Path -LiteralPath $logRoot)) {
    Write-Output "Log directory does not exist: $logRoot"
    exit 0
}

$cutoff = (Get-Date).AddDays(-$RetentionDays)
$targets = Get-ChildItem -LiteralPath $logRoot -File -Recurse |
    Where-Object { $_.LastWriteTime -lt $cutoff }

if (-not $targets) {
    Write-Output "No logs older than $RetentionDays days."
    exit 0
}

foreach ($target in $targets) {
    if ($WhatIf) {
        Write-Output "Would remove: $($target.FullName)"
    }
    else {
        Remove-Item -LiteralPath $target.FullName -Force
        Write-Output "Removed: $($target.FullName)"
    }
}

Write-Output "Matched $($targets.Count) log file(s)."
