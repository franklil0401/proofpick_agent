[CmdletBinding()]
param(
    [string]$MinioPath = "C:/ai/minio/minio.exe",
    [string]$RuntimeRoot = "C:/ai/smartbuy-stage3",
    [string]$V2RuntimeRoot = "C:/ai/proofpick-v2-rc",
    [switch]$SkipIndexBuild,
    [switch]$RebuildIndex,
    [switch]$OfflineReplay
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
$vendorRoot = Join-Path $projectRoot "vendor/youtu-rag"
$databasePath = Join-Path $RuntimeRoot "smartbuy_monitors_v1.sqlite"
$indexPath = Join-Path $RuntimeRoot "vector_store_text_embedding_v4_1024"
$runtimeManifestPath = Join-Path $RuntimeRoot "index_manifest.json"

& (Join-Path $PSScriptRoot "preflight.ps1") -MinioPath $MinioPath -RuntimeRoot $V2RuntimeRoot -OfflineReplay:$OfflineReplay
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
$env:PYTHONPATH = $projectRoot

Write-Host "[1/6] Syncing the frozen Youtu-RAG environment"
& uv sync --project $vendorRoot --frozen
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/6] Validating governed public demo data"
& uv run --project $vendorRoot python -m smartbuy.scripts.validate_stage3_data
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/6] Rebuilding read-only SQLite from source data"
& uv run --project $vendorRoot python -m smartbuy.db.build_database --output $databasePath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[4/6] Checking the Monitor 1024-dimension Chroma index"
$indexReady = $false
if (-not $RebuildIndex -and (Test-Path (Join-Path $indexPath "chroma.sqlite3"))) {
    & uv run --project $vendorRoot python -m smartbuy.scripts.verify_stage3_index --index-dir $indexPath
    $indexReady = $LASTEXITCODE -eq 0
}
if (-not $indexReady -and -not $OfflineReplay) {
    if ($SkipIndexBuild) {
        Write-Warning "Index is missing or invalid and -SkipIndexBuild was used; KB Search is not ready."
    }
    else {
        Write-Host "Building the public fact-card index with text-embedding-v4 (small API cost)."
        & uv run --project $vendorRoot python -m smartbuy.scripts.build_stage3_index --mode full --index-dir $indexPath --manifest-output $runtimeManifestPath
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & uv run --project $vendorRoot python -m smartbuy.scripts.verify_stage3_index --index-dir $indexPath
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        $indexReady = $true
    }
}

Write-Host "[5/6] Publishing Laptop and Headphone Product Packs"
$v2Args = @("-m", "smartbuy.scripts.build_v2_release_runtime", "--runtime-root", $V2RuntimeRoot)
if (-not $SkipIndexBuild -and -not $OfflineReplay) { $v2Args += "--build-indices" }
& uv run --project $vendorRoot python @v2Args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[6/6] Bootstrap summary"
Write-Host "SQLite: configured outside Git"
Write-Host ("Chroma: {0}" -f $(if ($indexReady) { "ready" } else { "not ready" }))
Write-Host ("V2 domain indices: {0}" -f $(if (-not $SkipIndexBuild -and -not $OfflineReplay) { "ready" } else { "not built (offline/replay mode)" }))
Write-Host "No environment variable value was printed or written to disk."
