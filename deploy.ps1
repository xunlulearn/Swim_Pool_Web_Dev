# NTU Pool - 快速部署到 Google Cloud Run (自动检测 gcloud)

# 设置变量
$PROJECT_ID = "ntu-swimpool-web"
$SERVICE_NAME = "ntu-pool"
$REGION = "asia-southeast1"

Write-Host "开始部署到 Google Cloud Run..." -ForegroundColor Green

# 查找 gcloud 安装路径
Write-Host "`n正在查找 gcloud 安装位置..." -ForegroundColor Yellow

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
        Write-Host "找到 gcloud: $path" -ForegroundColor Green
        break
    }
}

if (-not $gcloudPath) {
    Write-Host "未找到 gcloud 安装。请确保已安装 Google Cloud SDK。" -ForegroundColor Red
    Write-Host "下载地址: https://cloud.google.com/sdk/docs/install" -ForegroundColor Cyan
    exit 1
}

# 将 gcloud 添加到当前会话的 PATH
$env:PATH = "$gcloudPath;" + $env:PATH

# [1/4] 设置项目
Write-Host "`n[1/4] 设置 GCP 项目..." -ForegroundColor Yellow
& gcloud config set project $PROJECT_ID

# [2/4] 构建并推送镜像
Write-Host "`n[2/4] 构建 Docker 镜像 (需要几分钟)..." -ForegroundColor Yellow
& gcloud builds submit --tag "gcr.io/$PROJECT_ID/$SERVICE_NAME"

if ($LASTEXITCODE -ne 0) {
    Write-Host "构建失败！" -ForegroundColor Red
    exit 1
}

# [3/4] 部署到 Cloud Run
Write-Host "`n[3/4] 部署到 Cloud Run..." -ForegroundColor Yellow
& gcloud run deploy $SERVICE_NAME --image "gcr.io/$PROJECT_ID/${SERVICE_NAME}:latest" --platform managed --region $REGION --allow-unauthenticated --set-env-vars "FLASK_ENV=production" --memory 512Mi --cpu 1 --max-instances 10

if ($LASTEXITCODE -ne 0) {
    Write-Host "部署失败！" -ForegroundColor Red
    exit 1
}

# [4/4] 获取服务URL
Write-Host "`n[4/4] 获取服务 URL..." -ForegroundColor Yellow
$SERVICE_URL = & gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --format "value(status.url)"

Write-Host "`n部署完成！" -ForegroundColor Green
Write-Host "您的应用已上线: $SERVICE_URL" -ForegroundColor Cyan
