@echo off
setlocal EnableExtensions

cd /d "%~dp0"
set "PYTHON_BIN=.venv\Scripts\python.exe"
set "COMMAND=%~1"
if "%COMMAND%"=="" goto :usage
shift
set "ARGS=%1 %2 %3 %4 %5 %6 %7 %8 %9"

if /i "%COMMAND%"=="setup" goto :setup

call :ensure_venv
if errorlevel 1 goto :end

if /i "%COMMAND%"=="doctor" goto :doctor
if /i "%COMMAND%"=="run" goto :run
if /i "%COMMAND%"=="run-server" goto :run_server
if /i "%COMMAND%"=="test" goto :test
if /i "%COMMAND%"=="sync" goto :sync
if /i "%COMMAND%"=="ingest" goto :ingest
if /i "%COMMAND%"=="init-db" goto :init_db
if /i "%COMMAND%"=="reset-db" goto :reset_db
if /i "%COMMAND%"=="pip" goto :pip_cmd

echo [ERROR] Unknown command: %COMMAND%
goto :usage

:setup
if not exist "%PYTHON_BIN%" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found in PATH. Install Python 3.12+ first.
        goto :end
    )
    echo [INFO] Creating .venv ...
    python -m venv .venv
    if errorlevel 1 goto :end
)
echo [INFO] Upgrading pip in .venv ...
"%PYTHON_BIN%" -m pip install --upgrade pip
if errorlevel 1 goto :end
echo [INFO] Installing dependencies from requirements.txt ...
"%PYTHON_BIN%" -m pip install -r requirements.txt
if errorlevel 1 goto :end
echo [OK] .venv setup completed.
goto :end

:doctor
"%PYTHON_BIN%" scripts\venv_doctor.py %ARGS%
goto :end

:run
"%PYTHON_BIN%" -m flask run %ARGS%
goto :end

:run_server
"%PYTHON_BIN%" run_server.py %ARGS%
goto :end

:test
"%PYTHON_BIN%" -m pytest %ARGS%
goto :end

:sync
"%PYTHON_BIN%" sync_knowledge_base.py %ARGS%
goto :end

:ingest
"%PYTHON_BIN%" ingest.py %ARGS%
goto :end

:init_db
"%PYTHON_BIN%" init_db.py %ARGS%
goto :end

:reset_db
"%PYTHON_BIN%" reset_db.py %ARGS%
goto :end

:pip_cmd
"%PYTHON_BIN%" -m pip %ARGS%
goto :end

:ensure_venv
if not exist "%PYTHON_BIN%" (
    echo [ERROR] .venv is required but missing: %PYTHON_BIN%
    echo Run: dev.bat setup
    exit /b 1
)
exit /b 0

:usage
echo Usage: dev.bat ^<command^> [args...]
echo.
echo Commands:
echo   setup                    Create/update .venv and install requirements
echo   doctor [flags]           Validate .venv, dependencies, and tool paths
echo   run [flask args]         Run Flask dev server with .venv
echo   run-server [args]        Run run_server.py with .venv
echo   test [pytest args]       Run tests with .venv
echo   sync [sync args]         Run sync_knowledge_base.py with .venv
echo   ingest [args]            Run ingest.py with .venv
echo   init-db                  Run init_db.py with .venv
echo   reset-db                 Run reset_db.py with .venv
echo   pip [pip args]           Run pip through .venv Python
echo.
echo Doctor examples:
echo   dev.bat doctor --strict
echo   dev.bat doctor --require-runtime-env
echo   dev.bat doctor --require-release-tools
echo   dev.bat doctor --require-deploy-tools
goto :end

:end
endlocal
exit /b %ERRORLEVEL%
