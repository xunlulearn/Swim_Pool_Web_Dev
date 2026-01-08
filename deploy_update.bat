@echo off
echo ==========================================
echo       正在准备更新 NTU Pool 网站...
echo ==========================================

:: 1. 设置环境变量 (防止找不到 gcloud 命令)
set PATH=D:\Google Cloud SDK\google-cloud-sdk\bin;%PATH%

:: 2. 构建并上传镜像 (Build)
echo.
echo [1/2] 正在构建 Docker 镜像并推送到云端仓库...
call gcloud builds submit --tag asia-southeast1-docker.pkg.dev/ntu-swimpool-web/ntu-pool-repo/ntu-pool

:: 检查上一步是否成功
if %errorlevel% neq 0 (
    echo.
    echo [错误] 构建失败！请检查报错信息。
    pause
    exit /b %errorlevel%
)

:: 3. 部署服务 (Deploy)
echo.
echo [2/2] 正在将新镜像发布到 Cloud Run...
call gcloud run deploy ntu-pool --image asia-southeast1-docker.pkg.dev/ntu-swimpool-web/ntu-pool-repo/ntu-pool --region asia-southeast1 --allow-unauthenticated

echo.
echo ==========================================
echo          恭喜！网站更新成功！
echo ==========================================
pause