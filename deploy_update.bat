@echo off
setlocal EnableExtensions

echo ==========================================
echo   Deploy NTU Pool to Cloud Run (Update)
echo ==========================================

set GCLOUD_BIN=D:\Google Cloud SDK\google-cloud-sdk\bin
set PATH=%GCLOUD_BIN%;%PATH%
set SERVICE_NAME=ntu-pool
set REGION=asia-southeast1
set IMAGE=asia-southeast1-docker.pkg.dev/ntu-swimpool-web/ntu-pool-repo/ntu-pool

where gcloud >nul 2>&1
if errorlevel 1 (
    echo [ERROR] gcloud not found. Please install Google Cloud SDK first.
    pause
    exit /b 1
)

if "%SECRET_KEY%"=="" (
    set SECRET_KEY=%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%
    echo [INFO] SECRET_KEY not set. Generated a temporary key for this deploy.
)

echo.
echo [1/2] Building image...
call gcloud builds submit --tag "%IMAGE%"
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo.
echo [2/2] Deploying service...
call gcloud run deploy "%SERVICE_NAME%" --image "%IMAGE%" --region "%REGION%" --allow-unauthenticated --memory 1Gi --update-env-vars "FLASK_ENV=production,FLASK_CONFIG=production,SECRET_KEY=%SECRET_KEY%"
if errorlevel 1 (
    echo.
    echo [ERROR] Deploy failed.
    pause
    exit /b 1
)

for /f "delims=" %%i in ('gcloud run services describe "%SERVICE_NAME%" --region "%REGION%" --format "value(status.url)"') do set SERVICE_URL=%%i

echo.
echo ==========================================
echo   Deploy completed
echo ==========================================
echo URL: %SERVICE_URL%
pause
exit /b 0
