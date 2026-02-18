@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if not exist "dev.bat" (
    echo [ERROR] Missing dev.bat entrypoint in project root.
    echo.
    pause
    exit /b 1
)

echo ==========================================
echo   Sync NTU Pool Chatbot Knowledge Base
echo ==========================================
echo.
echo Runtime: .venv (via dev.bat)
echo.

call "%~dp0dev.bat" sync %*
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
