[CmdletBinding()]
param(
    [string]$ServiceRuntimeRoot = "C:/ai/smartbuy-stage7"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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

$runtimeFull = [IO.Path]::GetFullPath($ServiceRuntimeRoot).TrimEnd('\', '/')
$statePath = [IO.Path]::GetFullPath((Join-Path $runtimeFull "service_state.json"))
$expectedPrefix = $runtimeFull + [IO.Path]::DirectorySeparatorChar
if (-not $statePath.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to read service state outside the explicit runtime directory."
}
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    Write-Host "No SmartBuy-owned service state exists; nothing was stopped."
    exit 0
}

$state = Get-Content -Raw -Encoding UTF8 -LiteralPath $statePath | ConvertFrom-Json
foreach ($entry in @(
    [pscustomobject]@{ name = "FastAPI"; pid = $state.api_pid },
    [pscustomobject]@{ name = "MinIO"; pid = $state.minio_pid }
)) {
    if (-not $entry.pid) { continue }
    $process = Get-Process -Id ([int]$entry.pid) -ErrorAction SilentlyContinue
    if ($process) {
        Stop-ProcessTree -ProcessId $process.Id
        Write-Host ("Stopped {0} process {1}" -f $entry.name, $process.Id)
    }
}

Remove-Item -LiteralPath $statePath -Force
Write-Host "Only processes recorded by smartbuy/scripts/start.ps1 were stopped."
