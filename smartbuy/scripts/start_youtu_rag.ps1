[CmdletBinding()]
param(
    [string]$ProjectRoot = (
        Resolve-Path (Join-Path $PSScriptRoot "../../vendor/youtu-rag")
    ).Path,
    [string]$RuntimeRoot = "C:/ai/youtu-rag-runtime",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-RequiredSystemEnvironment {
    param([Parameter(Mandatory = $true)][string]$Name)

    # Read only persisted Windows scopes. The parent agent process may still
    # contain a revoked key after rotation, so Process scope is intentionally
    # excluded.
    foreach ($scope in @("Machine", "User")) {
        $value = [Environment]::GetEnvironmentVariable($Name, $scope)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value.Trim()
        }
    }

    throw "Missing required Windows environment variable: $Name"
}

$apiKey = Get-RequiredSystemEnvironment -Name "Qianwen_api_key"
$workspaceId = Get-RequiredSystemEnvironment -Name "Qianwen_workspace_id"
$runtimeRootNormalized = $RuntimeRoot.Replace("\", "/").TrimEnd("/")
$compatibleBaseUrl = (
    "https://{0}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1" -f $workspaceId
)
$rerankUrl = (
    "https://{0}.cn-beijing.maas.aliyuncs.com/compatible-api/v1/reranks" -f $workspaceId
)

$env:SERVER_HOST = $HostAddress
$env:SERVER_PORT = $Port.ToString()

$env:UTU_LLM_TYPE = "chat.completions"
$env:UTU_LLM_MODEL = "qwen-plus"
$env:UTU_LLM_BASE_URL = $compatibleBaseUrl
$env:UTU_LLM_API_KEY = $apiKey

$env:UTU_EMBEDDING_MODEL = "text-embedding-v4"
$env:UTU_EMBEDDING_URL = $compatibleBaseUrl
$env:UTU_EMBEDDING_API_KEY = $apiKey

$env:UTU_RERANKER_MODEL = "qwen3-rerank"
$env:UTU_RERANKER_URL = $rerankUrl
$env:UTU_RERANKER_BASE_URL = $rerankUrl
$env:UTU_RERANKER_API_KEY = $apiKey

$env:UTU_OCR_MODEL = "disabled"
$env:UTU_OCR_BASE_URL = ""
$env:UTU_CHUNK_MODEL = "disabled"
$env:UTU_CHUNK_BASE_URL = ""
$env:memoryEnabled = "false"

$env:MINIO_ENDPOINT = "127.0.0.1:9000"
$env:MINIO_BUCKET = "ufile"
$env:MINIO_BUCKET_SYS = "sysfile"
$env:MINIO_SECURE = "false"
$env:MINIO_LOCAL_TMP_DIR = "$RuntimeRoot/minio-tmp"

$env:VECTOR_STORE_PATH = "$RuntimeRoot/vector_store_bailian_v4_1024"
$env:UTU_DB_URL = "sqlite:///$runtimeRootNormalized/relational_database/rag_demo.sqlite"
$env:RELATIONAL_DB_PATH = "$RuntimeRoot/relational_database/rag_demo.sqlite"
$env:ENABLE_VECTOR_MONITOR = "true"
$env:ENABLE_MINIO_MONITOR = "true"
$env:UTU_LOG_LEVEL = "INFO"

@(
    $RuntimeRoot,
    $env:MINIO_LOCAL_TMP_DIR,
    $env:VECTOR_STORE_PATH,
    (Join-Path $RuntimeRoot "relational_database")
) | ForEach-Object {
    New-Item -ItemType Directory -Force -Path $_ | Out-Null
}

Push-Location $ProjectRoot
try {
    & uv run uvicorn utu.rag.api.main:app --host $HostAddress --port $Port
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
