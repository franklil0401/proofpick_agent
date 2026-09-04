[CmdletBinding()]
param(
    [int]$Port = 8088,
    [string]$ServiceRuntimeRoot = "C:/ai/proofpick-v2-replay",
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
$frontendRoot = Join-Path $projectRoot "vendor/youtu-rag/frontend/rag_webui"
$runtimeFull = [IO.Path]::GetFullPath($ServiceRuntimeRoot)
$statePath = Join-Path $runtimeFull "replay_state.json"

function Stop-ReplayProcess {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        Write-Host "No ProofPick replay state exists; nothing was stopped."
        return
    }
    $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($state.pid) {
        Stop-Process -Id ([int]$state.pid) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $statePath -Force
    Write-Host "Stopped the recorded offline replay process."
}

if ($Stop) {
    Stop-ReplayProcess
    exit 0
}

& (Join-Path $PSScriptRoot "preflight.ps1") -RuntimeRoot $runtimeFull -OfflineReplay
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use."
}
New-Item -ItemType Directory -Force -Path $runtimeFull | Out-Null
$stdout = Join-Path $runtimeFull "replay.stdout.log"
$stderr = Join-Path $runtimeFull "replay.stderr.log"
$process = Start-Process -FilePath "python" -ArgumentList "-m http.server $Port --bind 127.0.0.1 --directory `"$frontendRoot`"" -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$deadline = (Get-Date).AddSeconds(20)
$response = $null
do {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri ("http://127.0.0.1:{0}/app.html" -f $Port) -TimeoutSec 2
        if ($response.StatusCode -eq 200) { break }
    }
    catch { Start-Sleep -Milliseconds 250 }
} while ((Get-Date) -lt $deadline)
if (-not $response -or $response.StatusCode -ne 200) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    throw "Offline replay did not become ready."
}
[ordered]@{ pid = $process.Id; port = $Port; created_at = (Get-Date).ToUniversalTime().ToString("o") } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
Write-Host ("Offline replay: http://127.0.0.1:{0}/app.html" -f $Port)
Write-Host "This is a fixed redacted replay, not a real-time model call."
