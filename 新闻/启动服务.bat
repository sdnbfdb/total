@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [*] 正在启动新闻服务（后台无窗口模式）...

REM 优先使用装有项目依赖的 Python313，避免 PATH 里其他解释器缺 flask/fastembed
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"

if not defined PY (
    echo [X] 未找到 python.exe，请安装 Python 3 并确保已加入 PATH。
    exit /b 1
)

echo [*] 使用 Python: %PY%
"%PY%" "%~dp0_runner.py"
