@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ---------------------------------------------------------------------------
REM One-click Vercel deploy wrapper.
REM Usage:
REM   deploy_update.bat
REM   deploy_update.bat --check-only
REM
REM Notes:
REM - The production platform is Vercel.
REM - This script no longer uses Google Cloud, Cloud Run, Docker, or gcloud.
REM - If the Vercel project is connected to GitHub, pushing main may already
REM   trigger production deployment. This script is the manual CLI fallback.
REM ---------------------------------------------------------------------------

echo ==========================================
echo   Deploy NTU Pool to Vercel
echo ==========================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "PYTHON_BIN=.venv\Scripts\python.exe"
if not exist "%PYTHON_BIN%" (
    echo [ERROR] .venv is required for maintenance but not found.
    echo Run: dev.bat setup
    goto :fail
)

set "CHECK_ONLY=0"
if /i "%~1"=="--check-only" set "CHECK_ONLY=1"

echo [PRECHECK] Validating .venv and Vercel deploy toolchain...
"%PYTHON_BIN%" scripts\venv_doctor.py --require-deploy-tools
if errorlevel 1 goto :fail

call :load_env_file "%SCRIPT_DIR%.env"
if "%DATABASE_URL%"=="" if not "%SQLALCHEMY_DATABASE_URI%"=="" (
    set "DATABASE_URL=%SQLALCHEMY_DATABASE_URI%"
    echo [INFO] DATABASE_URL not found, using SQLALCHEMY_DATABASE_URI from environment.
)

call :require_env DATABASE_URL
if errorlevel 1 goto :fail
call :require_env SECRET_KEY
if errorlevel 1 goto :fail

echo [PRECHECK] Checking Vercel CLI availability...
call npx --yes vercel --version
if errorlevel 1 (
    echo [ERROR] Unable to start Vercel CLI through npx.
    goto :fail
)

if "%CHECK_ONLY%"=="1" (
    echo [INFO] Environment check passed. (--check-only^)
    exit /b 0
)

set "VERCEL_ARGS=deploy --prod --yes"
if not "%VERCEL_TOKEN%"=="" (
    set "VERCEL_ARGS=%VERCEL_ARGS% --token %VERCEL_TOKEN%"
)

echo.
echo [1/2] Deploying current source to Vercel production...
echo [INFO] If this repository is not linked yet, run: npx vercel link
call npx --yes vercel %VERCEL_ARGS%
if errorlevel 1 (
    echo [ERROR] Vercel deploy failed.
    echo If this is the first deploy from this machine, run: npx vercel login
    echo Then link the project once with: npx vercel link
    goto :fail
)

echo.
echo [2/2] Deploy command completed.
echo [INFO] Vercel printed the production URL above.
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
echo Please fix the reported issues and run deploy_update.bat again.
exit /b 1
