@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv is required but not found.
    echo Run: python -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
set "PYTHON_BIN=.venv\Scripts\python.exe"

echo ==========================================
echo   Sync NTU Pool Chatbot Knowledge Base
echo ==========================================
echo.
echo Python: %PYTHON_BIN%
echo.

"%PYTHON_BIN%" sync_knowledge_base.py %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Sync failed with exit code %EXIT_CODE%.
    echo Check console logs, then fix config/network issues and rerun.
) else (
    echo [OK] Sync completed successfully.
)
echo.
pause
exit /b %EXIT_CODE%
