@echo off
setlocal EnableExtensions
REM ---------------------------------------------------------------------------
REM One-click publisher for the 2026-07 bot/search/chatbot update.
REM What it does, in order:
REM   1. Move reviewed workflow files from _workflow_updates\ into .github\workflows\
REM   2. Remove temporary _to_delete\ folder so it never enters git
REM   3. Run the full test suite (aborts on failure)
REM   4. Try to set the LIGHTNING_CRON_URL repo secret via GitHub CLI (optional)
REM   5. Commit + push via your normal dev.bat git-push flow (Vercel auto-deploys)
REM   6. Refresh the chatbot knowledge base (dev.bat sync)
REM ---------------------------------------------------------------------------

cd /d "%~dp0"
echo ==========================================
echo   NTU Pool - publish 2026-07 update
echo ==========================================

REM [1/6] Install workflow files
if exist "_workflow_updates\community-bot-posts.yml" (
    move /Y "_workflow_updates\community-bot-posts.yml" ".github\workflows\community-bot-posts.yml" >nul
    echo [1/6] Installed .github\workflows\community-bot-posts.yml
)
if exist "_workflow_updates\collect-lightning.yml" (
    move /Y "_workflow_updates\collect-lightning.yml" ".github\workflows\collect-lightning.yml" >nul
    echo [1/6] Installed .github\workflows\collect-lightning.yml
)
if exist "_workflow_updates" rmdir /S /Q "_workflow_updates"

REM [2/6] Clean temp folder so it is never committed
if exist "_to_delete" (
    rmdir /S /Q "_to_delete"
    echo [2/6] Removed _to_delete\ temp folder
)

REM [3/6] Full test suite
echo [3/6] Running test suite...
call dev.bat test -q
if errorlevel 1 (
    echo [ERROR] Tests failed - nothing was pushed. Please report the output above.
    exit /b 1
)
echo [3/6] All tests passed.

REM [4/6] Repo secret for the new lightning-collection workflow
echo [4/6] Setting LIGHTNING_CRON_URL repo secret via GitHub CLI...
where gh >nul 2>&1
if errorlevel 1 (
    echo [WARN] GitHub CLI ^(gh^) not found. Add the secret manually:
    echo        GitHub repo - Settings - Secrets and variables - Actions - New repository secret
    echo        Name : LIGHTNING_CRON_URL
    echo        Value: https://www.ntupool.org/api/cron/collect-lightning
) else (
    gh secret set LIGHTNING_CRON_URL --body "https://www.ntupool.org/api/cron/collect-lightning"
    if errorlevel 1 (
        echo [WARN] Could not set secret automatically. Add it manually ^(see above^).
    ) else (
        echo [4/6] Secret LIGHTNING_CRON_URL set.
    )
)

REM [5/6] Commit and push (uses your local git credentials; Vercel auto-deploys)
echo [5/6] Committing and pushing...
call dev.bat git-push "feat(community): operating-hours bot scheduler, interactions, feed search, chatbot latency rework"
if errorlevel 1 (
    echo [ERROR] Push failed. Fix git state and re-run this script.
    exit /b 1
)

REM [6/6] Refresh chatbot knowledge base (new KB markdown files)
echo [6/6] Syncing chatbot knowledge base...
call dev.bat sync
if errorlevel 1 (
    echo [WARN] Knowledge sync reported an error. You can retry later with: dev.bat sync
)

echo.
echo ==========================================
echo   DONE. Vercel will deploy the pushed commit automatically.
echo   Fallback manual deploy: deploy_update.bat
echo ==========================================
exit /b 0
