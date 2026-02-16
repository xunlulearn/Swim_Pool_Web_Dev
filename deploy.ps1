# Deploy NTU Pool to Google Cloud Run with chatbot environment variables.

$PROJECT_ID = "ntu-swimpool-web"
$SERVICE_NAME = "ntu-pool"
$REGION = "asia-southeast1"
$IMAGE = "asia-southeast1-docker.pkg.dev/$PROJECT_ID/ntu-pool-repo/ntu-pool"

Write-Host "Starting Cloud Run deployment..." -ForegroundColor Green

$possiblePaths = @(
    "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin",
    "${env:ProgramFiles(x86)}\Google\Cloud SDK\google-cloud-sdk\bin",
    "$env:ProgramFiles\Google\Cloud SDK\google-cloud-sdk\bin",
    "$env:USERPROFILE\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin"
)

$gcloudPath = $null
foreach ($path in $possiblePaths) {
    if (Test-Path "$path\gcloud.cmd") {
        $gcloudPath = $path
        break
    }
}

if (-not $gcloudPath) {
    Write-Host "gcloud not found. Install Google Cloud SDK first." -ForegroundColor Red
    Write-Host "Install guide: https://cloud.google.com/sdk/docs/install" -ForegroundColor Yellow
    exit 1
}

$env:PATH = "$gcloudPath;$env:PATH"

function Require-Env($name) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        Write-Host "Missing required env var: $name" -ForegroundColor Red
        exit 1
    }
}

Require-Env "DATABASE_URL"
Require-Env "OPENAI_API_KEY"
Require-Env "SUPABASE_URL"
Require-Env "SUPABASE_SERVICE_ROLE_KEY"

if ([string]::IsNullOrWhiteSpace($env:SECRET_KEY)) {
    $env:SECRET_KEY = -join ((48..57 + 65..90 + 97..122) | Get-Random -Count 48 | ForEach-Object {[char]$_})
    Write-Host "SECRET_KEY not set, generated temporary key for this deploy." -ForegroundColor Yellow
}

if ([string]::IsNullOrWhiteSpace($env:OPENAI_CHAT_MODEL)) { $env:OPENAI_CHAT_MODEL = "gpt-4o-mini" }
if ([string]::IsNullOrWhiteSpace($env:OPENAI_EMBED_MODEL)) { $env:OPENAI_EMBED_MODEL = "text-embedding-3-small" }
if ([string]::IsNullOrWhiteSpace($env:SUPABASE_DOCS_TABLE)) { $env:SUPABASE_DOCS_TABLE = "pool_documents" }
if ([string]::IsNullOrWhiteSpace($env:SUPABASE_MATCH_FUNCTION)) { $env:SUPABASE_MATCH_FUNCTION = "match_documents" }
if ([string]::IsNullOrWhiteSpace($env:CHATBOT_TOP_K)) { $env:CHATBOT_TOP_K = "3" }
if ([string]::IsNullOrWhiteSpace($env:CHATBOT_MIN_SCORE)) { $env:CHATBOT_MIN_SCORE = "0.65" }
if ([string]::IsNullOrWhiteSpace($env:CHATBOT_MAX_CONTEXT_CHARS)) { $env:CHATBOT_MAX_CONTEXT_CHARS = "4000" }

$envVars = @(
    "FLASK_ENV=production"
    "FLASK_CONFIG=production"
    "SECRET_KEY=$($env:SECRET_KEY)"
    "DATABASE_URL=$($env:DATABASE_URL)"
    "OPENAI_API_KEY=$($env:OPENAI_API_KEY)"
    "OPENAI_CHAT_MODEL=$($env:OPENAI_CHAT_MODEL)"
    "OPENAI_EMBED_MODEL=$($env:OPENAI_EMBED_MODEL)"
    "SUPABASE_URL=$($env:SUPABASE_URL)"
    "SUPABASE_SERVICE_ROLE_KEY=$($env:SUPABASE_SERVICE_ROLE_KEY)"
    "SUPABASE_DOCS_TABLE=$($env:SUPABASE_DOCS_TABLE)"
    "SUPABASE_MATCH_FUNCTION=$($env:SUPABASE_MATCH_FUNCTION)"
    "CHATBOT_TOP_K=$($env:CHATBOT_TOP_K)"
    "CHATBOT_MIN_SCORE=$($env:CHATBOT_MIN_SCORE)"
    "CHATBOT_MAX_CONTEXT_CHARS=$($env:CHATBOT_MAX_CONTEXT_CHARS)"
)

if (-not [string]::IsNullOrWhiteSpace($env:NEA_API_KEY)) {
    $envVars += "NEA_API_KEY=$($env:NEA_API_KEY)"
}
if (-not [string]::IsNullOrWhiteSpace($env:OPENAI_BASE_URL)) {
    $envVars += "OPENAI_BASE_URL=$($env:OPENAI_BASE_URL)"
}

$envVarsArg = [string]::Join(",", $envVars)

Write-Host "[1/3] Setting GCP project..." -ForegroundColor Cyan
& gcloud config set project $PROJECT_ID
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "[2/3] Building image..." -ForegroundColor Cyan
& gcloud builds submit --tag $IMAGE
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "[3/3] Deploying Cloud Run service..." -ForegroundColor Cyan
& gcloud run deploy $SERVICE_NAME `
    --image $IMAGE `
    --platform managed `
    --region $REGION `
    --allow-unauthenticated `
    --memory 1Gi `
    --update-env-vars $envVarsArg

if ($LASTEXITCODE -ne 0) {
    Write-Host "Deploy failed." -ForegroundColor Red
    exit 1
}

$serviceUrl = & gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --format "value(status.url)"
Write-Host "Deploy completed: $serviceUrl" -ForegroundColor Green
