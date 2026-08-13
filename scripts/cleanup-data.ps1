[CmdletBinding()]
param(
    [ValidateRange(1, 3650)]
    [int]$TransientFrameDays = 7,

    [ValidateRange(1, 3650)]
    [int]$CacheDays = 30,

    [ValidateRange(1, 3650)]
    [int]$OrphanDays = 30,

    [ValidateRange(1, 3650)]
    [int]$EvaluationReportDays = 90,

    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$dataRoot = Join-Path $projectRoot 'data'
$catalogPath = Join-Path $dataRoot 'catalog\memory-state.json'
$now = Get-Date

# Keep this script ASCII-only so Windows PowerShell 5 and PowerShell 7 parse it equally.
# The default mode is preview. Files are deleted only when -Apply is explicitly passed.
$catalogRaw = if (Test-Path -LiteralPath $catalogPath) {
    Get-Content -LiteralPath $catalogPath -Raw -Encoding UTF8
} else {
    '{}'
}

$liveVideoIds = New-Object 'System.Collections.Generic.HashSet[string]' (
    [System.StringComparer]::OrdinalIgnoreCase
)
try {
    $catalog = $catalogRaw | ConvertFrom-Json
    foreach ($video in @($catalog.videos)) {
        if ($null -ne $video.id) {
            [void]$liveVideoIds.Add([string]$video.id)
        }
    }
} catch {
    throw "Catalog parse failed at $catalogPath. Cleanup stopped to prevent data loss. $($_.Exception.Message)"
}

$candidates = New-Object 'System.Collections.Generic.List[object]'

function Test-PathWithinRoot {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$Root
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
    return $fullPath.Equals($fullRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $fullPath.StartsWith($fullRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-KeepMarker {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$BoundaryRoot
    )

    $current = if (Test-Path -LiteralPath $Path -PathType Container) {
        New-Object System.IO.DirectoryInfo($Path)
    } else {
        (New-Object System.IO.FileInfo($Path)).Directory
    }
    $boundary = [System.IO.Path]::GetFullPath($BoundaryRoot).TrimEnd('\')

    while ($null -ne $current -and (Test-PathWithinRoot -Path $current.FullName -Root $boundary)) {
        if (Test-Path -LiteralPath (Join-Path $current.FullName '.keep')) {
            return $true
        }
        if ($current.FullName.Equals($boundary, [System.StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $current = $current.Parent
    }
    return $false
}

function Add-ExpiredFiles {
    param(
        [Parameter(Mandatory)] [string]$Root,
        [Parameter(Mandatory)] [int]$RetentionDays,
        [Parameter(Mandatory)] [string]$Category,
        [scriptblock]$AdditionalFilter = { param($File) $true }
    )

    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        return
    }

    $cutoff = $now.AddDays(-$RetentionDays)
    foreach ($file in Get-ChildItem -LiteralPath $Root -File -Recurse -Force) {
        if ($file.Name -eq '.keep' -or $file.LastWriteTime -ge $cutoff) {
            continue
        }
        if (Test-KeepMarker -Path $file.FullName -BoundaryRoot $Root) {
            continue
        }
        if (-not (& $AdditionalFilter $file)) {
            continue
        }
        $candidates.Add([pscustomobject]@{
            Category = $Category
            Path = $file.FullName
            Bytes = [int64]$file.Length
            AgeDays = [math]::Floor(($now - $file.LastWriteTime).TotalDays)
            Root = $Root
        })
    }
}

Add-ExpiredFiles `
    -Root (Join-Path $dataRoot 'frames-on-demand') `
    -RetentionDays $TransientFrameDays `
    -Category 'transient-qa-frames'

Add-ExpiredFiles `
    -Root (Join-Path $dataRoot 'processing-cache') `
    -RetentionDays $CacheDays `
    -Category 'rebuildable-processing-cache'

Add-ExpiredFiles `
    -Root (Join-Path $dataRoot 'processing') `
    -RetentionDays $OrphanDays `
    -Category 'orphan-processing-state' `
    -AdditionalFilter {
        param($file)
        return -not $liveVideoIds.Contains($file.BaseName)
    }

$framesRoot = Join-Path $dataRoot 'frames'
Add-ExpiredFiles `
    -Root $framesRoot `
    -RetentionDays $OrphanDays `
    -Category 'orphan-sampled-frames' `
    -AdditionalFilter {
        param($file)
        $prefixLength = $framesRoot.TrimEnd('\').Length
        $relative = $file.FullName.Substring($prefixLength).TrimStart('\')
        $videoDirectory = $relative.Split('\')[0]
        return -not $liveVideoIds.Contains($videoDirectory)
    }

$isUnreferencedMedia = {
    param($file)
    # Referenced path or directory names are protected regardless of age.
    return ($catalogRaw.IndexOf($file.Name, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) -and
        ($catalogRaw.IndexOf($file.Directory.Name, [System.StringComparison]::OrdinalIgnoreCase) -lt 0)
}

Add-ExpiredFiles `
    -Root (Join-Path $dataRoot 'uploads') `
    -RetentionDays $OrphanDays `
    -Category 'orphan-upload-staging' `
    -AdditionalFilter $isUnreferencedMedia

Add-ExpiredFiles `
    -Root (Join-Path $dataRoot 'web-imports') `
    -RetentionDays $OrphanDays `
    -Category 'orphan-web-import-staging' `
    -AdditionalFilter $isUnreferencedMedia

Add-ExpiredFiles `
    -Root (Join-Path $projectRoot 'evals\reports') `
    -RetentionDays $EvaluationReportDays `
    -Category 'expired-evaluation-reports'

$totalBytes = [int64](($candidates | Measure-Object -Property Bytes -Sum).Sum)
$mode = if ($Apply) { 'APPLY' } else { 'PREVIEW' }
Write-Host "Data cleanup mode: $mode"
Write-Host "Candidates: $($candidates.Count) files; estimated release: $([math]::Round($totalBytes / 1MB, 2)) MB"

if ($candidates.Count -gt 0) {
    $candidates |
        Group-Object Category |
        ForEach-Object {
            $bytes = [int64](($_.Group | Measure-Object -Property Bytes -Sum).Sum)
            [pscustomobject]@{
                Category = $_.Name
                Files = $_.Count
                SizeMB = [math]::Round($bytes / 1MB, 2)
            }
        } |
        Format-Table -AutoSize

    $candidates |
        Sort-Object Category, Path |
        Select-Object Category, AgeDays, @{Name = 'SizeMB'; Expression = { [math]::Round($_.Bytes / 1MB, 2) } }, Path |
        Format-Table -AutoSize
}

if (-not $Apply) {
    Write-Host 'No files were deleted. Review the list, then pass -Apply to execute.'
    exit 0
}

foreach ($candidate in $candidates) {
    if (-not (Test-PathWithinRoot -Path $candidate.Path -Root $candidate.Root)) {
        throw "Safety check failed. Candidate is outside its allowed root: $($candidate.Path)"
    }
    if (Test-Path -LiteralPath $candidate.Path -PathType Leaf) {
        Remove-Item -LiteralPath $candidate.Path -Force
    }
}

# Remove only empty directories under roots that contained candidates.
$candidateRoots = $candidates | Select-Object -ExpandProperty Root -Unique
foreach ($root in $candidateRoots) {
    Get-ChildItem -LiteralPath $root -Directory -Recurse -Force |
        Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object {
            if ((Get-ChildItem -LiteralPath $_.FullName -Force | Measure-Object).Count -eq 0) {
                Remove-Item -LiteralPath $_.FullName -Force
            }
        }
}

$auditDirectory = Join-Path $projectRoot 'var\logs\maintenance'
$auditPath = Join-Path $auditDirectory 'data-cleanup.jsonl'
New-Item -ItemType Directory -Path $auditDirectory -Force | Out-Null
[pscustomobject]@{
    occurred_at = (Get-Date).ToUniversalTime().ToString('o')
    mode = 'apply'
    deleted_files = $candidates.Count
    released_bytes = $totalBytes
    transient_frame_days = $TransientFrameDays
    cache_days = $CacheDays
    orphan_days = $OrphanDays
    evaluation_report_days = $EvaluationReportDays
} | ConvertTo-Json -Compress | Add-Content -LiteralPath $auditPath -Encoding UTF8

Write-Host "Cleanup finished: $($candidates.Count) files deleted; about $([math]::Round($totalBytes / 1MB, 2)) MB released."
Write-Host "Audit record: $auditPath"
