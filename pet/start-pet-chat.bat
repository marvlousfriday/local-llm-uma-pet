@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 优先用 PATH 里的 pythonw，找不到再退回 py 启动器
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0pet_chat.py"
    exit /b 0
)

where py >nul 2>nul
if %errorlevel%==0 (
    start "" pyw "%~dp0pet_chat.py"
    exit /b 0
)

echo [x] 找不到 pythonw，请安装 Python 3.x 并勾选 Add to PATH
pause
