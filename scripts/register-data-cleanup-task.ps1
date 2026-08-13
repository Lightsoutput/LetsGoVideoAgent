[CmdletBinding()]
param(
    [string]$TaskName = 'LetsGoVideoAgent-WeeklyDataCleanup',
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$cleanupScript = Join-Path $projectRoot 'scripts\cleanup-data.ps1'

if (-not (Test-Path -LiteralPath $cleanupScript -PathType Leaf)) {
    throw "Cleanup script not found: $cleanupScript"
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Unregister) {
    if ($null -eq $existing) {
        Write-Host "Scheduled task does not exist: $TaskName"
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Scheduled task removed: $TaskName"
    exit 0
}

$powerShellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$cleanupScript`" -Apply"
$action = New-ScheduledTaskAction -Execute $powerShellExe -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '03:30'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
$description = 'Weekly reference-aware cleanup for LetsGoVideoAgent transient frames, rebuildable cache, orphan staging files, and old evaluation reports.'

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description $description `
    -Force | Out-Null

Write-Host "Scheduled task registered: $TaskName"
Write-Host 'Schedule: every Sunday at 03:30; missed runs start when the computer is next available.'
Write-Host "Command: $powerShellExe $arguments"
