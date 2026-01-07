@echo off
chcp 65001 >nul
echo ========================================
echo NTU Pool - Deploy to Google Cloud Run
echo ========================================

set GCLOUD_PATH=D:\Google Cloud SDK\google-cloud-sdk\bin
set PROJECT_ID=ntu-swimpool-web
set SERVICE_NAME=ntu-pool
set REGION=asia-southeast1

REM Add gcloud to PATH for this session
set PATH=%GCLOUD_PATH%;%PATH%

echo.
echo [1/4] Setting GCP project...
gcloud config set project %PROJECT_ID%

echo.
echo [2/4] Building Docker image (this may take several minutes)...
gcloud builds submit --tag gcr.io/%PROJECT_ID%/%SERVICE_NAME%
if errorlevel 1 (
    echo Build failed!
    pause
    exit /b 1
)

echo.
echo [3/4] Deploying to Cloud Run...
gcloud run deploy %SERVICE_NAME% --image gcr.io/%PROJECT_ID%/%SERVICE_NAME%:latest --platform managed --region %REGION% --allow-unauthenticated --set-env-vars FLASK_ENV=production --memory 512Mi --cpu 1 --max-instances 10
if errorlevel 1 (
    echo Deploy failed!
    pause
    exit /b 1
)

echo.
echo [4/4] Getting service URL...
for /f "tokens=*" %%i in ('gcloud run services describe %SERVICE_NAME% --platform managed --region %REGION% --format "value(status.url)"') do set SERVICE_URL=%%i

echo.
echo ========================================
echo Deployment Complete!
echo ========================================
echo.
echo Your app is live at: %SERVICE_URL%
echo.
pause
