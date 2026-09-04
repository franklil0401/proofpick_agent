[CmdletBinding()]
param(
    [string]$MinioPath = "C:/ai/minio/minio.exe",
    [string]$MinioData = "C:/ai/minio-data",
    [string]$SmartBuyRuntimeRoot = "C:/ai/smartbuy-stage3",
    [string]$YoutuRuntimeRoot = "C:/ai/youtu-rag-runtime",
    [string]$ServiceRuntimeRoot = "C:/ai/smartbuy-stage7",
    [string]$V2RuntimeRoot = "C:/ai/proofpick-v2-rc",
    [int]$Port = 8000,
    [switch]$OfflineReplay
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
$databasePath = Join-Path $SmartBuyRuntimeRoot "smartbuy_monitors_v1.sqlite"
$indexPath = Join-Path $SmartBuyRuntimeRoot "vector_store_text_embedding_v4_1024/chroma.sqlite3"
$v2DataPointers = @(
    (Join-Path $V2RuntimeRoot "laptop/data/current.json"),
    (Join-Path $V2RuntimeRoot "headphone/data/current.json")
)
$v2IndexPointers = @(
    (Join-Path $V2RuntimeRoot "laptop/index/current_laptop_index.json"),
    (Join-Path $V2RuntimeRoot "headphone/index/current_headphone_index.json")
)
$statePath = Join-Path $ServiceRuntimeRoot "service_state.json"
$started = [ordered]@{ minio_pid = $null; api_pid = $null }

if ($OfflineReplay) {
    & (Join-Path $PSScriptRoot "replay.ps1") -Port 8088 -ServiceRuntimeRoot $ServiceRuntimeRoot
    exit $LASTEXITCODE
}

function Test-Listening {
    param([int]$PortNumber)
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $PortNumber -ErrorAction SilentlyContinue)
}

function Wait-Http {
    param([string]$Uri, [int]$Seconds = 60)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return $true }
        }
        catch { Start-Sleep -Milliseconds 500 }
    }
    return $false
}

function Stop-ProcessTree {
    param([int]$ProcessId)
    $children = @(
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    )
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

& (Join-Path $PSScriptRoot "preflight.ps1") -MinioPath $MinioPath -RuntimeRoot $V2RuntimeRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) {
    throw "SQLite is missing. Run smartbuy/scripts/bootstrap.ps1 first."
}
if (-not (Test-Path -LiteralPath $indexPath -PathType Leaf)) {
    throw "Chroma index is missing. Run bootstrap.ps1 without -SkipIndexBuild."
}
foreach ($pointer in @($v2DataPointers + $v2IndexPointers)) {
    if (-not (Test-Path -LiteralPath $pointer -PathType Leaf)) {
        throw "V2 Product Pack or index pointer is missing. Run bootstrap.ps1 without -SkipIndexBuild."
    }
}

New-Item -ItemType Directory -Force -Path $MinioData, $YoutuRuntimeRoot, $ServiceRuntimeRoot | Out-Null
if ([string]::IsNullOrWhiteSpace($env:MINIO_ACCESS_KEY)) { $env:MINIO_ACCESS_KEY = $env:MINIO_ROOT_USER }
if ([string]::IsNullOrWhiteSpace($env:MINIO_SECRET_KEY)) { $env:MINIO_SECRET_KEY = $env:MINIO_ROOT_PASSWORD }
$env:SMARTBUY_DB_PATH = [IO.Path]::GetFullPath($databasePath)
$env:SMARTBUY_INDEX_PATH = [IO.Path]::GetFullPath((Split-Path -Parent $indexPath))
$env:SMARTBUY_MEMORY_PATH = [IO.Path]::GetFullPath((Join-Path $SmartBuyRuntimeRoot "preferences.json"))
$env:PROOFPICK_V2_RUNTIME_ROOT = [IO.Path]::GetFullPath($V2RuntimeRoot)
$env:PROOFPICK_V2_MEMORY_PATH = [IO.Path]::GetFullPath((Join-Path $V2RuntimeRoot "memory"))
$env:PROOFPICK_DOMAIN_AGENT_ENABLED = "true"

try {
    if (-not (Test-Listening 9000)) {
        $minioOut = Join-Path $ServiceRuntimeRoot "minio.stdout.log"
        $minioErr = Join-Path $ServiceRuntimeRoot "minio.stderr.log"
        $minioArgs = "server `"$MinioData`" --address 127.0.0.1:9000 --console-address 127.0.0.1:9001"
        $minio = Start-Process -FilePath $MinioPath -ArgumentList $minioArgs -PassThru -WindowStyle Hidden -RedirectStandardOutput $minioOut -RedirectStandardError $minioErr
        $started.minio_pid = $minio.Id
    }
    if (-not (Wait-Http "http://127.0.0.1:9000/minio/health/live" 30)) {
        throw "MinIO health check did not return HTTP 200."
    }

    if (-not (Test-Listening $Port)) {
        $apiOut = Join-Path $ServiceRuntimeRoot "api.stdout.log"
        $apiErr = Join-Path $ServiceRuntimeRoot "api.stderr.log"
        $lowerStart = Join-Path $PSScriptRoot "start_youtu_rag.ps1"
        $apiArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$lowerStart`" -RuntimeRoot `"$YoutuRuntimeRoot`" -Port $Port"
        $api = Start-Process -FilePath "powershell.exe" -ArgumentList $apiArgs -PassThru -WindowStyle Hidden -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr
        $started.api_pid = $api.Id
    }

    foreach ($path in @("/health", "/", "/monitor", "/api/smartbuy/portfolio/capabilities")) {
        if (-not (Wait-Http ("http://127.0.0.1:{0}{1}" -f $Port, $path) 90)) {
            throw "Service check failed for $path."
        }
    }
    $state = [ordered]@{
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        port = $Port
        minio_pid = $started.minio_pid
        api_pid = $started.api_pid
    }
    $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
    Write-Host "MinIO API/Console: http://127.0.0.1:9000 / http://127.0.0.1:9001"
    Write-Host ("ProofPick UI/health/monitor: http://127.0.0.1:{0}/" -f $Port)
    Write-Host "Service state contains process IDs only; no credential was persisted."
}
catch {
    foreach ($pidValue in @($started.api_pid, $started.minio_pid)) {
        if ($pidValue) { Stop-ProcessTree -ProcessId ([int]$pidValue) }
    }
    throw
}
