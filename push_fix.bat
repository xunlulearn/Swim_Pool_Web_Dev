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

echo [1/2] Running test suite...
call dev.bat test -q
if errorlevel 1 (
    echo [ERROR] Tests failed - nothing was pushed.
    pause
    exit /b 1
)

set "MSG=%~1"
if "%MSG%"=="" set "MSG=feat(community): llm-generated bot content and humanized first-page commenting"

echo [2/2] Committing and pushing...
call dev.bat git-push "%MSG%"
if errorlevel 1 (
    echo [ERROR] Push failed. Fix git state and re-run.
    pause
    exit /b 1
)

echo.
echo DONE. Now open the pull request page and merge to deploy:
echo   https://github.com/xunlulearn/Swim_Pool_Web_Dev/compare/main...codex/community-page-jump
pause
exit /b 0
