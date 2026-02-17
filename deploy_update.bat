@echo off
setlocal EnableExtensions EnableDelayedExpansion

echo ==========================================
echo   Deploy NTU Pool to Cloud Run (Update)
echo ==========================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set GCLOUD_BIN=D:\Google Cloud SDK\google-cloud-sdk\bin
set PATH=%GCLOUD_BIN%;%PATH%
set SERVICE_NAME=ntu-pool
set REGION=asia-southeast1
set IMAGE=asia-southeast1-docker.pkg.dev/ntu-swimpool-web/ntu-pool-repo/ntu-pool

set "CHECK_ONLY=0"
if /i "%~1"=="--check-only" set "CHECK_ONLY=1"

where gcloud >nul 2>&1
if errorlevel 1 (
    echo [ERROR] gcloud not found. Please install Google Cloud SDK first.
    pause
    exit /b 1
)

call :load_env_file "%SCRIPT_DIR%.env"
if "%DATABASE_URL%"=="" if not "%SQLALCHEMY_DATABASE_URI%"=="" (
    set "DATABASE_URL=%SQLALCHEMY_DATABASE_URI%"
    echo [INFO] DATABASE_URL not found, using SQLALCHEMY_DATABASE_URI from environment.
)

call :require_env DATABASE_URL
if errorlevel 1 goto :fail
call :require_env OPENAI_API_KEY
if errorlevel 1 goto :fail
call :require_env SUPABASE_URL
if errorlevel 1 goto :fail
call :require_env SUPABASE_SERVICE_ROLE_KEY
if errorlevel 1 goto :fail

if "%CHECK_ONLY%"=="1" (
    echo [INFO] Environment check passed. (--check-only^)
    exit /b 0
)

if "%SECRET_KEY%"=="" (
    set SECRET_KEY=%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%
    echo [INFO] SECRET_KEY not set. Generated a temporary key for this deploy.
)

if "%OPENAI_CHAT_MODEL%"=="" set OPENAI_CHAT_MODEL=gpt-4o-mini
if "%OPENAI_EMBED_MODEL%"=="" set OPENAI_EMBED_MODEL=text-embedding-3-small
if "%CHATBOT_INTENT_BASE_URL%"=="" set CHATBOT_INTENT_BASE_URL=https://openrouter.ai/api/v1
if "%CHATBOT_INTENT_MODEL%"=="" set CHATBOT_INTENT_MODEL=liquid/lfm-2.5-1.2b-thinking:free
if "%SUPABASE_DOCS_TABLE%"=="" set SUPABASE_DOCS_TABLE=pool_documents
if "%SUPABASE_MATCH_FUNCTION%"=="" set SUPABASE_MATCH_FUNCTION=match_documents
if "%CHATBOT_TOP_K%"=="" set CHATBOT_TOP_K=3
if "%CHATBOT_MIN_SCORE%"=="" set CHATBOT_MIN_SCORE=0.45
if "%CHATBOT_MAX_CONTEXT_CHARS%"=="" set CHATBOT_MAX_CONTEXT_CHARS=4000
if "%CHATBOT_DB_TOOL_MAX_CALLS%"=="" set CHATBOT_DB_TOOL_MAX_CALLS=4

set "ENV_VARS=FLASK_ENV=production,FLASK_CONFIG=production,SECRET_KEY=%SECRET_KEY%,DATABASE_URL=%DATABASE_URL%,OPENAI_API_KEY=%OPENAI_API_KEY%,OPENAI_CHAT_MODEL=%OPENAI_CHAT_MODEL%,OPENAI_EMBED_MODEL=%OPENAI_EMBED_MODEL%,CHATBOT_INTENT_BASE_URL=%CHATBOT_INTENT_BASE_URL%,CHATBOT_INTENT_MODEL=%CHATBOT_INTENT_MODEL%,SUPABASE_URL=%SUPABASE_URL%,SUPABASE_SERVICE_ROLE_KEY=%SUPABASE_SERVICE_ROLE_KEY%,SUPABASE_DOCS_TABLE=%SUPABASE_DOCS_TABLE%,SUPABASE_MATCH_FUNCTION=%SUPABASE_MATCH_FUNCTION%,CHATBOT_TOP_K=%CHATBOT_TOP_K%,CHATBOT_MIN_SCORE=%CHATBOT_MIN_SCORE%,CHATBOT_MAX_CONTEXT_CHARS=%CHATBOT_MAX_CONTEXT_CHARS%,CHATBOT_DB_TOOL_MAX_CALLS=%CHATBOT_DB_TOOL_MAX_CALLS%"

if not "%NEA_API_KEY%"=="" set "ENV_VARS=%ENV_VARS%,NEA_API_KEY=%NEA_API_KEY%"
if not "%OPENAI_BASE_URL%"=="" set "ENV_VARS=%ENV_VARS%,OPENAI_BASE_URL=%OPENAI_BASE_URL%"
if not "%CHATBOT_INTENT_API_KEY%"=="" set "ENV_VARS=%ENV_VARS%,CHATBOT_INTENT_API_KEY=%CHATBOT_INTENT_API_KEY%"

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

:load_env_file
set "_ENV_FILE=%~1"
if not exist "%_ENV_FILE%" (
    echo [WARN] .env file not found at "%_ENV_FILE%". Using current process environment only.
    exit /b 0
)
echo [INFO] Loading environment variables from "%_ENV_FILE%"
for /f "usebackq delims=" %%L in ("%_ENV_FILE%") do (
    call :parse_env_line "%%L"
)
exit /b 0

:parse_env_line
setlocal DisableDelayedExpansion
set "line=%~1"
if not defined line exit /b 0
if "%line:~0,1%"=="#" exit /b 0
if "%line:~0,1%"==";" exit /b 0
if /i "%line:~0,7%"=="export " set "line=%line:~7%"
for /f "tokens=1* delims==" %%A in ("%line%") do (
    set "key=%%~A"
    set "value=%%~B"
)
if not defined key exit /b 0
for /f "tokens=* delims= " %%K in ("%key%") do set "key=%%K"
if not defined key exit /b 0
if defined value (
    if "%value:~0,1%"=="\"" if "%value:~-1%"=="\"" set "value=%value:~1,-1%"
)
endlocal & call :set_if_missing "%key%" "%value%"
exit /b 0

:set_if_missing
set "_DOTENV_KEY=%~1"
set "_DOTENV_VALUE=%~2"
if "%_DOTENV_KEY%"=="" exit /b 0
call set "_DOTENV_CURRENT=%%%_DOTENV_KEY%%%"
if not defined _DOTENV_CURRENT (
    set "%_DOTENV_KEY%=%_DOTENV_VALUE%"
)
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
