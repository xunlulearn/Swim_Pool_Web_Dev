@echo off
setlocal EnableExtensions
REM ---------------------------------------------------------------------------
REM Small publisher for follow-up fixes: run tests, then commit + push the
REM current branch via dev.bat git-push. Vercel deploys after the PR merge.
REM Usage:
REM   push_fix.bat                       (uses the default message below)
REM   push_fix.bat "fix(scope): message" (custom conventional commit message)
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

REM Install any staged workflow files first (remote tools cannot write
REM .github\workflows directly, so they are staged in _workflow_updates\).
if exist "_workflow_updates" (
    for %%F in ("_workflow_updates\*.yml") do (
        move /Y "%%F" ".github\workflows\%%~nxF" >nul
        echo [workflow] Installed .github\workflows\%%~nxF
    )
    rmdir /S /Q "_workflow_updates" 2>nul
)

echo [1/3] Running test suite...
call dev.bat test -q
if errorlevel 1 (
    echo [ERROR] Tests failed - nothing was pushed.
    pause
    exit /b 1
)

set "MSG=%~1"
if "%MSG%"=="" set "MSG=feat(chatbot): hard knowledge base with instant answers and guided suggestions"

echo [2/3] Committing and pushing...
call dev.bat git-push "%MSG%"
if errorlevel 1 (
    echo [ERROR] Push failed. Fix git state and re-run.
    pause
    exit /b 1
)

echo [3/3] Re-syncing chatbot knowledge base (chunking strategy changed)...
call dev.bat sync
if errorlevel 1 (
    echo [WARN] Knowledge sync failed. Retry later with: dev.bat sync
    echo [WARN] Until it succeeds, new knowledge answers may be missing.
)

echo.
echo DONE. Now open the pull request page and merge to deploy:
echo   https://github.com/xunlulearn/Swim_Pool_Web_Dev/compare/main...codex/community-page-jump
pause
exit /b 0
