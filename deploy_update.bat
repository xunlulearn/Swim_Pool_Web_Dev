@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ---------------------------------------------------------------------------
REM One-click safe deploy for Cloud Run with canary rollout + rollback guard.
REM Usage:
REM   deploy_update.bat
REM   deploy_update.bat --check-only
REM ---------------------------------------------------------------------------

echo ==========================================
echo   Deploy NTU Pool to Cloud Run (Safe)
echo ==========================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "PROJECT_ID=ntu-swimpool-web"
set "SERVICE_NAME=ntu-pool"
set "REGION=asia-southeast1"
set "IMAGE=asia-southeast1-docker.pkg.dev/%PROJECT_ID%/ntu-pool-repo/ntu-pool"

set "CHECK_ONLY=0"
if /i "%~1"=="--check-only" set "CHECK_ONLY=1"

REM Prefer locally installed Cloud SDK path when script is double-clicked.
if exist "D:\Google Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" (
    set "PATH=D:\Google Cloud SDK\google-cloud-sdk\bin;%PATH%"
)

where gcloud >nul 2>&1
if errorlevel 1 (
    echo [ERROR] gcloud not found. Please install Google Cloud SDK first.
    goto :fail
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
    set "SECRET_KEY=%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%"
    echo [INFO] SECRET_KEY not set. Generated a temporary key for this deploy.
)

if "%OPENAI_CHAT_MODEL%"=="" set "OPENAI_CHAT_MODEL=gpt-4o-mini"
if "%OPENAI_EMBED_MODEL%"=="" set "OPENAI_EMBED_MODEL=text-embedding-3-small"
if "%CHATBOT_INTENT_BASE_URL%"=="" set "CHATBOT_INTENT_BASE_URL=https://openrouter.ai/api/v1"
if "%CHATBOT_INTENT_MODEL%"=="" set "CHATBOT_INTENT_MODEL=liquid/lfm-2.5-1.2b-thinking:free"
if "%SUPABASE_DOCS_TABLE%"=="" set "SUPABASE_DOCS_TABLE=pool_documents"
if "%SUPABASE_MATCH_FUNCTION%"=="" set "SUPABASE_MATCH_FUNCTION=match_documents"
if "%CHATBOT_TOP_K%"=="" set "CHATBOT_TOP_K=3"
if "%CHATBOT_MIN_SCORE%"=="" set "CHATBOT_MIN_SCORE=0.45"
if "%CHATBOT_MAX_CONTEXT_CHARS%"=="" set "CHATBOT_MAX_CONTEXT_CHARS=4000"
if "%CHATBOT_DB_TOOL_MAX_CALLS%"=="" set "CHATBOT_DB_TOOL_MAX_CALLS=4"

REM Safety defaults to reduce production hangs and avoid sample data leakage.
if "%USE_SAMPLE_WEATHER_DATA%"=="" set "USE_SAMPLE_WEATHER_DATA=false"
if "%WEATHER_STATUS_CACHE_SECONDS%"=="" set "WEATHER_STATUS_CACHE_SECONDS=30"
if "%LIVE_STATUS_CACHE_SECONDS%"=="" set "LIVE_STATUS_CACHE_SECONDS=30"
if "%DB_CONNECT_TIMEOUT%"=="" set "DB_CONNECT_TIMEOUT=5"
if "%DB_STATEMENT_TIMEOUT_MS%"=="" set "DB_STATEMENT_TIMEOUT_MS=8000"
if "%DB_POOL_TIMEOUT%"=="" set "DB_POOL_TIMEOUT=10"
if "%DB_POOL_RECYCLE%"=="" set "DB_POOL_RECYCLE=1800"

set "ENV_VARS=FLASK_ENV=production,FLASK_CONFIG=production,SECRET_KEY=%SECRET_KEY%,DATABASE_URL=%DATABASE_URL%,OPENAI_API_KEY=%OPENAI_API_KEY%,OPENAI_CHAT_MODEL=%OPENAI_CHAT_MODEL%,OPENAI_EMBED_MODEL=%OPENAI_EMBED_MODEL%,CHATBOT_INTENT_BASE_URL=%CHATBOT_INTENT_BASE_URL%,CHATBOT_INTENT_MODEL=%CHATBOT_INTENT_MODEL%,SUPABASE_URL=%SUPABASE_URL%,SUPABASE_SERVICE_ROLE_KEY=%SUPABASE_SERVICE_ROLE_KEY%,SUPABASE_DOCS_TABLE=%SUPABASE_DOCS_TABLE%,SUPABASE_MATCH_FUNCTION=%SUPABASE_MATCH_FUNCTION%,CHATBOT_TOP_K=%CHATBOT_TOP_K%,CHATBOT_MIN_SCORE=%CHATBOT_MIN_SCORE%,CHATBOT_MAX_CONTEXT_CHARS=%CHATBOT_MAX_CONTEXT_CHARS%,CHATBOT_DB_TOOL_MAX_CALLS=%CHATBOT_DB_TOOL_MAX_CALLS%,USE_SAMPLE_WEATHER_DATA=%USE_SAMPLE_WEATHER_DATA%,WEATHER_STATUS_CACHE_SECONDS=%WEATHER_STATUS_CACHE_SECONDS%,LIVE_STATUS_CACHE_SECONDS=%LIVE_STATUS_CACHE_SECONDS%,DB_CONNECT_TIMEOUT=%DB_CONNECT_TIMEOUT%,DB_STATEMENT_TIMEOUT_MS=%DB_STATEMENT_TIMEOUT_MS%,DB_POOL_TIMEOUT=%DB_POOL_TIMEOUT%,DB_POOL_RECYCLE=%DB_POOL_RECYCLE%"

if not "%NEA_API_KEY%"=="" set "ENV_VARS=%ENV_VARS%,NEA_API_KEY=%NEA_API_KEY%"
if not "%OPENAI_BASE_URL%"=="" set "ENV_VARS=%ENV_VARS%,OPENAI_BASE_URL=%OPENAI_BASE_URL%"
if not "%CHATBOT_INTENT_API_KEY%"=="" set "ENV_VARS=%ENV_VARS%,CHATBOT_INTENT_API_KEY=%CHATBOT_INTENT_API_KEY%"

echo.
echo [0/7] Setting GCP project...
call gcloud config set project "%PROJECT_ID%" >nul
if errorlevel 1 (
    echo [ERROR] Failed to set project.
    goto :fail
)

echo.
echo [1/7] Reading current production revision...
call :get_active_revision
if errorlevel 1 goto :fail
set "STABLE_REV=%ACTIVE_REV%"
echo [INFO] Current stable revision: %STABLE_REV%

echo.
echo [2/7] Pinning stable tag to %STABLE_REV%...
call gcloud run services update-traffic "%SERVICE_NAME%" --region "%REGION%" --to-revisions "%STABLE_REV%=100" --set-tags "stable=%STABLE_REV%"
if errorlevel 1 (
    echo [ERROR] Failed to pin stable tag.
    goto :fail
)

for /f "delims=" %%i in ('gcloud run services describe "%SERVICE_NAME%" --region "%REGION%" --format "value(status.url)"') do set "SERVICE_URL=%%i"
if "%SERVICE_URL%"=="" (
    echo [ERROR] Cannot read service URL.
    goto :fail
)

echo.
echo [3/7] Building image...
call gcloud builds submit --tag "%IMAGE%"
if errorlevel 1 (
    echo [ERROR] Build failed.
    goto :fail
)

echo.
echo [4/7] Deploying candidate revision (0%% traffic, tag=canary)...
call gcloud run deploy "%SERVICE_NAME%" --image "%IMAGE%" --region "%REGION%" --allow-unauthenticated --memory 1Gi --update-env-vars "%ENV_VARS%" --no-traffic --tag canary
if errorlevel 1 (
    echo [ERROR] Deploy failed.
    goto :fail
)

call :get_tag_info canary CANDIDATE_URL CANDIDATE_REV
if errorlevel 1 goto :fail

echo [INFO] Candidate revision: %CANDIDATE_REV%
echo [INFO] Candidate URL: %CANDIDATE_URL%

echo.
echo [5/7] Smoke checking candidate endpoints...
call :health_check "%CANDIDATE_URL%" "candidate"
if errorlevel 1 goto :rollback

echo.
echo [6/7] Canary rollout 5%% -> 30%% -> 100%% ...
echo [INFO] Rolling out canary=5%%, stable=95%% ...
call gcloud run services update-traffic "%SERVICE_NAME%" --region "%REGION%" --to-tags "canary=5,stable=95"
if errorlevel 1 goto :rollback
timeout /t 8 >nul
call :health_check "%SERVICE_URL%" "production-5%"
if errorlevel 1 goto :rollback

echo [INFO] Rolling out canary=30%%, stable=70%% ...
call gcloud run services update-traffic "%SERVICE_NAME%" --region "%REGION%" --to-tags "canary=30,stable=70"
if errorlevel 1 goto :rollback
timeout /t 8 >nul
call :health_check "%SERVICE_URL%" "production-30%"
if errorlevel 1 goto :rollback

call gcloud run services update-traffic "%SERVICE_NAME%" --region "%REGION%" --to-revisions "%CANDIDATE_REV%=100" --set-tags "stable=%CANDIDATE_REV%"
if errorlevel 1 goto :rollback

timeout /t 8 >nul
call :health_check "%SERVICE_URL%" "production-100%"
if errorlevel 1 goto :rollback

echo.
echo [7/7] Deploy completed successfully.
echo URL: %SERVICE_URL%
echo Stable revision: %CANDIDATE_REV%
pause
exit /b 0

:rollback
echo.
echo [WARN] Canary check failed. Rolling back to stable revision: %STABLE_REV%
call gcloud run services update-traffic "%SERVICE_NAME%" --region "%REGION%" --to-revisions "%STABLE_REV%=100" --set-tags "stable=%STABLE_REV%"
if errorlevel 1 (
    echo [ERROR] Rollback command failed. Please rollback manually.
) else (
    echo [INFO] Rollback completed.
)
goto :fail

:get_active_revision
set "ACTIVE_REV="
set "ACTIVE_PCT=0"
for /f "tokens=1,2 delims=," %%A in ('gcloud run services describe "%SERVICE_NAME%" --region "%REGION%" --flatten="status.traffic[]" --format "csv[no-heading](status.traffic.percent,status.traffic.revisionName)"') do (
    if not "%%A"=="" (
        set /a CUR_PCT=%%A
        if !CUR_PCT! GTR !ACTIVE_PCT! (
            set "ACTIVE_PCT=!CUR_PCT!"
            set "ACTIVE_REV=%%B"
        )
    )
)
if "%ACTIVE_REV%"=="" (
    echo [ERROR] Unable to determine active revision.
    exit /b 1
)
exit /b 0

:get_tag_info
set "_TAG_NAME=%~1"
set "%~2="
set "%~3="
for /f "tokens=1,2,3 delims=," %%A in ('gcloud run services describe "%SERVICE_NAME%" --region "%REGION%" --flatten="status.traffic[]" --format "csv[no-heading](status.traffic.tag,status.traffic.url,status.traffic.revisionName)"') do (
    if /i "%%A"=="%_TAG_NAME%" (
        set "%~2=%%B"
        set "%~3=%%C"
    )
)
call set "_TAG_URL=%%%~2%%"
call set "_TAG_REV=%%%~3%%"
if "%_TAG_URL%"=="" (
    echo [ERROR] Cannot resolve URL for tag "%_TAG_NAME%".
    exit /b 1
)
if "%_TAG_REV%"=="" (
    echo [ERROR] Cannot resolve revision for tag "%_TAG_NAME%".
    exit /b 1
)
exit /b 0

:health_check
set "BASE_URL=%~1"
set "CHECK_LABEL=%~2"
if "%BASE_URL%"=="" exit /b 1

echo [INFO] Health check (%CHECK_LABEL%): %BASE_URL%
call :check_endpoint "%BASE_URL%/"
if errorlevel 1 exit /b 1
call :check_endpoint "%BASE_URL%/weather/status"
if errorlevel 1 exit /b 1
call :check_endpoint "%BASE_URL%/api/live-status/"
if errorlevel 1 exit /b 1
exit /b 0

:check_endpoint
set "URL=%~1"
set "HTTP_CODE="
for /l %%i in (1,1,3) do (
    for /f %%H in ('curl -sS --max-time 20 -o NUL -w "%%{http_code}" "%URL%"') do set "HTTP_CODE=%%H"
    if "!HTTP_CODE!"=="200" (
        echo [OK] %URL%
        exit /b 0
    )
    timeout /t 2 >nul
)
echo [ERROR] %URL% returned !HTTP_CODE! (expected 200)
exit /b 1

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
echo Please fix the reported issues and run deploy_update.bat again.
pause
exit /b 1
