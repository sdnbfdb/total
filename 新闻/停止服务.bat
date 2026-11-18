@echo off
chcp 65001 >nul
echo [*] 正在查找占用 5000 端口的进程...
set FOUND=0
REM 用 ":5000 " 带空格匹配，避免误伤 :50000 等端口
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000 " ^| findstr LISTENING') do (
    echo [!] 发现进程 PID=%%a，正在强制关闭...
    taskkill /PID %%a /F >nul 2>nul
    set FOUND=1
)
if %FOUND%==0 (
    echo [-] 5000 端口未被占用，服务未在运行。
) else (
    echo [OK] 已停止。
)
