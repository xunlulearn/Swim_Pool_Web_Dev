@echo off
setlocal EnableExtensions EnableDelayedExpansion

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

call :require_env DATABASE_URL
if errorlevel 1 goto :fail
call :require_env OPENAI_API_KEY
if errorlevel 1 goto :fail
call :require_env SUPABASE_URL
if errorlevel 1 goto :fail
call :require_env SUPABASE_SERVICE_ROLE_KEY
if errorlevel 1 goto :fail

if "%SECRET_KEY%"=="" (
    set SECRET_KEY=%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%
    echo [INFO] SECRET_KEY not set. Generated a temporary key for this deploy.
)

if "%OPENAI_CHAT_MODEL%"=="" set OPENAI_CHAT_MODEL=gpt-4o-mini
if "%OPENAI_EMBED_MODEL%"=="" set OPENAI_EMBED_MODEL=text-embedding-3-small
if "%SUPABASE_DOCS_TABLE%"=="" set SUPABASE_DOCS_TABLE=pool_documents
if "%SUPABASE_MATCH_FUNCTION%"=="" set SUPABASE_MATCH_FUNCTION=match_documents
if "%CHATBOT_TOP_K%"=="" set CHATBOT_TOP_K=3
if "%CHATBOT_MIN_SCORE%"=="" set CHATBOT_MIN_SCORE=0.65
if "%CHATBOT_MAX_CONTEXT_CHARS%"=="" set CHATBOT_MAX_CONTEXT_CHARS=4000

set "ENV_VARS=FLASK_ENV=production,FLASK_CONFIG=production,SECRET_KEY=%SECRET_KEY%,DATABASE_URL=%DATABASE_URL%,OPENAI_API_KEY=%OPENAI_API_KEY%,OPENAI_CHAT_MODEL=%OPENAI_CHAT_MODEL%,OPENAI_EMBED_MODEL=%OPENAI_EMBED_MODEL%,SUPABASE_URL=%SUPABASE_URL%,SUPABASE_SERVICE_ROLE_KEY=%SUPABASE_SERVICE_ROLE_KEY%,SUPABASE_DOCS_TABLE=%SUPABASE_DOCS_TABLE%,SUPABASE_MATCH_FUNCTION=%SUPABASE_MATCH_FUNCTION%,CHATBOT_TOP_K=%CHATBOT_TOP_K%,CHATBOT_MIN_SCORE=%CHATBOT_MIN_SCORE%,CHATBOT_MAX_CONTEXT_CHARS=%CHATBOT_MAX_CONTEXT_CHARS%"

if not "%NEA_API_KEY%"=="" set "ENV_VARS=%ENV_VARS%,NEA_API_KEY=%NEA_API_KEY%"
if not "%OPENAI_BASE_URL%"=="" set "ENV_VARS=%ENV_VARS%,OPENAI_BASE_URL=%OPENAI_BASE_URL%"

echo.
echo [1/2] Building image...
call gcloud builds submit --tag "%IMAGE%"
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    goto :fail
)

echo.
echo [2/2] Deploying service...
call gcloud run deploy "%SERVICE_NAME%" --image "%IMAGE%" --region "%REGION%" --allow-unauthenticated --memory 1Gi --update-env-vars "%ENV_VARS%"
if errorlevel 1 (
    echo.
    echo [ERROR] Deploy failed.
    goto :fail
)

for /f "delims=" %%i in ('gcloud run services describe "%SERVICE_NAME%" --region "%REGION%" --format "value(status.url)"') do set SERVICE_URL=%%i

echo.
echo ==========================================
echo   Deploy completed
echo ==========================================
echo URL: %SERVICE_URL%
pause
exit /b 0

:require_env
set "_VAR_NAME=%~1"
set "_VAR_VALUE=!%~1!"
if "!_VAR_VALUE!"=="" (
    echo [ERROR] Missing required environment variable: %~1
    exit /b 1
)
exit /b 0

:fail
echo.
echo [ERROR] Deployment aborted.
echo Please export required variables and run again.
pause
exit /b 1
