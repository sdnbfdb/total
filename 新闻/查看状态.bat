@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ======== 端口状态 ========
netstat -ano | findstr ":5000 " | findstr LISTENING
if errorlevel 1 (
    echo [!] 5000 端口无监听，服务未运行。
) else (
    echo [OK] 服务运行中。访问: http://127.0.0.1:5000/
)
echo.
echo ======== 最新日志（尾部20行） ========
if exist "%~dp0service.log" (
    powershell -NoProfile -Command "Get-Content '%~dp0service.log' -Tail 20 -Encoding UTF8"
) else (
    echo [-] 日志文件不存在，首次运行成功后会生成。
)
