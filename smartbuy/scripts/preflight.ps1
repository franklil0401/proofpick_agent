[CmdletBinding()]
param(
    [string]$MinioPath = "C:/ai/minio/minio.exe",
    [string]$RuntimeRoot = "C:/ai/proofpick-v2-rc",
    [switch]$OfflineReplay
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
$runtimeFull = [IO.Path]::GetFullPath($RuntimeRoot)
$checks = [System.Collections.Generic.List[object]]::new()

function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    $checks.Add([pscustomobject]@{ name = $Name; passed = $Passed; detail = $Detail })
    $label = if ($Passed) { "PASS" } else { "FAIL" }
    Write-Host ("[{0}] {1}: {2}" -f $label, $Name, $Detail)
}

function Test-Configured {
    param([string]$Name)
    return -not [string]::IsNullOrWhiteSpace(
        [Environment]::GetEnvironmentVariable($Name, "Process")
    )
}

$runningOnWindows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
Add-Check "Windows" $runningOnWindows "Windows 11 is the supported release target"

$python = Get-Command python -ErrorAction SilentlyContinue
$pythonVersion = if ($python) { (& python --version 2>&1 | Out-String).Trim() } else { "missing" }
Add-Check "Python" ($pythonVersion -match '^Python 3\.12\.') $pythonVersion

$uv = Get-Command uv -ErrorAction SilentlyContinue
$uvVersion = if ($uv) { (& uv --version 2>&1 | Out-String).Trim() } else { "missing" }
Add-Check "uv" ([bool]$uv) $uvVersion

$git = Get-Command git -ErrorAction SilentlyContinue
$gitVersion = if ($git) { (& git --version 2>&1 | Out-String).Trim() } else { "missing" }
Add-Check "Git" ([bool]$git) $gitVersion

Add-Check "vendor subtree" (Test-Path (Join-Path $projectRoot "vendor/youtu-rag/uv.lock")) "vendor/youtu-rag/uv.lock"
Add-Check "MinIO binary" ($OfflineReplay -or (Test-Path -LiteralPath $MinioPath -PathType Leaf)) $(if ($OfflineReplay) { "not required for offline replay" } else { "external binary only" })
$apiConfigured = Test-Configured "Qianwen_api_key"
$workspaceConfigured = Test-Configured "Qianwen_workspace_id"
$minioUserConfigured = Test-Configured "MINIO_ROOT_USER"
$minioPasswordConfigured = Test-Configured "MINIO_ROOT_PASSWORD"
Add-Check "Qianwen_api_key" ($OfflineReplay -or $apiConfigured) $(if ($OfflineReplay) { "not required for offline replay" } elseif ($apiConfigured) { "configured" } else { "missing" })
Add-Check "Qianwen_workspace_id" ($OfflineReplay -or $workspaceConfigured) $(if ($OfflineReplay) { "not required for offline replay" } elseif ($workspaceConfigured) { "configured" } else { "missing" })
Add-Check "MINIO_ROOT_USER" ($OfflineReplay -or $minioUserConfigured) $(if ($OfflineReplay) { "not required for offline replay" } elseif ($minioUserConfigured) { "configured" } else { "missing" })
Add-Check "MINIO_ROOT_PASSWORD" ($OfflineReplay -or $minioPasswordConfigured) $(if ($OfflineReplay) { "not required for offline replay" } elseif ($minioPasswordConfigured) { "configured" } else { "missing" })

$projectPrefix = $projectRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
$outsideProject = -not $runtimeFull.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)
Add-Check "runtime outside Git" $outsideProject $runtimeFull

$failed = @($checks | Where-Object { -not $_.passed })
Write-Host ("Preflight: {0}/{1} checks passed" -f ($checks.Count - $failed.Count), $checks.Count)
if ($failed.Count -gt 0) {
    exit 1
}
